"""
GuidelineLearningAgent モジュール

ワークフロー最終段階でMRコメントを読み込み、PROJECT_GUIDELINES.mdへの
追記が必要かLLMに判断させ、必要な場合はファイルを更新してgit commit & pushまで
行う専用エージェントを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 11（GuidelineLearningAgent）に準拠する。
AUTOMATA_CODEX_SPEC.md § 11（学習機能）に準拠する。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from agent_framework import Executor, WorkflowContext, handler

if TYPE_CHECKING:
    from consumer.user_config_client import UserConfig
    from shared.database.repositories.token_usage_repository import TokenUsageRepository
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)

# PROJECT_GUIDELINES.mdの初期テンプレート
_INITIAL_GUIDELINES_TEMPLATE = """\
---
name: PROJECT_GUIDELINES
about: プロジェクト固有の品質基準とガイドライン
---
# プロジェクトガイドライン（自動育成中）
## 1. ドキュメント作成
## 2. コード実装
## 3. レビュー観点
## 4. ワークフロー
## 5. その他
"""


class GuidelineLearningAgent(Executor):
    """
    ガイドライン学習エージェント

    ワークフロー最終ノードとしてグラフに自動挿入される固定実装エージェント。
    ユーザーコメントに対しLLMでガイドライン化すべき内容かを判定し、
    学習が必要な場合はリポジトリのPROJECT_GUIDELINES.mdを取得・更新して
    GitLab APIに直接コミットする。

    このクラスのみGitLab APIを通じたgit操作を例外的に許可される。
    GuidelineLearningAgent自体の実行エラーはワークフローに影響させず、
    ログ記録のみとする。

    CLASS_IMPLEMENTATION_SPEC.md § 11 に準拠する。
    AUTOMATA_CODEX_SPEC.md § 11 に準拠する。

    Attributes:
        user_config: ユーザー別学習機能設定
        gitlab_client: GitLabAPIクライアント（例外的に保持）
        progress_reporter: 進捗報告インスタンス
    """

    def __init__(
        self,
        user_config: UserConfig,
        gitlab_client: GitlabClient,
        progress_reporter: Any = None,
        token_usage_repository: TokenUsageRepository | None = None,
    ) -> None:
        """
        GuidelineLearningAgentを初期化する。

        Args:
            user_config: ユーザー設定（学習機能設定を含む）
            gitlab_client: GitLab APIクライアント（MRコメント取得・ファイル更新用）
            progress_reporter: 進捗報告インスタンス（省略可能）
            token_usage_repository: トークン使用量記録リポジトリ（省略時は記録しない）
        """
        self.user_config = user_config
        self.gitlab_client = gitlab_client
        self.progress_reporter = progress_reporter
        self.token_usage_repository = token_usage_repository
        super().__init__(id=self.__class__.__name__)

    @handler(input=Any, output=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext[Any]) -> None:
        """
        ガイドライン学習処理を実行する。

        CLASS_IMPLEMENTATION_SPEC.md § 11.4 invoke_async() の処理フローに準拠する。

        処理フロー:
        1. 有効チェック（learning_enabled）
        2. タスク情報取得（task_mr_iid, task_project_id, task_start_time）
        3. MRコメント取得・フィルタリング
        4. ガイドライン読み込み
        5. LLM単一呼び出し（更新判定）
        6. ガイドライン更新（should_update=trueの場合のみ）
        7. エラーハンドリング（例外をキャッチしてログ記録のみ、ワークフローは継続）

        Args:
            msg: 受け取るメッセージ（未使用）
            ctx: ワークフローコンテキスト
        """
        try:
            await self._process(ctx)
        except Exception as exc:
            # 7. エラーハンドリング: 例外をキャッチしてログのみ。ワークフローは継続。
            logger.error(
                "GuidelineLearningAgentの実行中にエラーが発生しました。"
                "ワークフローは継続します: %s",
                exc,
                exc_info=True,
            )
        await ctx.send_message(msg)

    async def _process(self, ctx: WorkflowContext) -> None:
        """
        ガイドライン学習の実際の処理を実行する。

        Args:
            ctx: ワークフローコンテキスト
        """
        # 1. 有効チェック
        if not self.user_config.learning_enabled:
            logger.info("学習機能が無効のためGuidelineLearningAgentをスキップします")
            return

        # 2. タスク情報取得
        task_mr_iid = ctx.get_state("task_mr_iid")
        task_project_id = ctx.get_state("task_project_id")
        task_start_time = ctx.get_state("task_start_time")

        if task_mr_iid is None or task_project_id is None:
            logger.warning(
                "タスク情報が取得できませんでした。"
                "GuidelineLearningAgentをスキップします: "
                "task_mr_iid=%s, task_project_id=%s",
                task_mr_iid,
                task_project_id,
            )
            return

        # 3. MRコメント取得・フィルタリング
        comments = self._get_filtered_comments(
            project_id=task_project_id,
            mr_iid=task_mr_iid,
            task_start_time=task_start_time,
        )

        if not comments:
            logger.info(
                "対象コメントが存在しないためGuidelineLearningAgentをスキップします: "
                "mr_iid=%s",
                task_mr_iid,
            )
            return

        # 4. ガイドライン読み込み
        branch = ctx.get_state("assigned_branch") or "main"
        current_guidelines = self._get_guidelines(
            project_id=task_project_id,
            branch=branch,
        )

        # 5. LLM単一呼び出し（更新判定）
        task_uuid: str | None = ctx.get_state("task_uuid")
        username: str | None = ctx.get_state("username")
        llm_result = await self._call_llm_for_guideline_judgment(
            task_mr_iid=task_mr_iid,
            comments=comments,
            current_guidelines=current_guidelines,
            task_uuid=task_uuid,
            username=username,
        )

        # 6. ガイドライン更新（should_update=trueの場合のみ）
        if llm_result.get("should_update"):
            await self._update_guidelines(
                project_id=task_project_id,
                mr_iid=task_mr_iid,
                updated_guidelines=llm_result.get("updated_guidelines", ""),
                branch=branch,
            )
            logger.info(
                "ガイドラインを更新しました: mr_iid=%s, category=%s, rationale=%s",
                task_mr_iid,
                llm_result.get("category"),
                llm_result.get("rationale"),
            )
        else:
            logger.info(
                "ガイドライン更新不要と判定されました: mr_iid=%s, rationale=%s",
                task_mr_iid,
                llm_result.get("rationale"),
            )

    def _get_filtered_comments(
        self,
        project_id: int,
        mr_iid: int,
        task_start_time: Any | None,
    ) -> list[dict[str, Any]]:
        """
        MRコメントを取得してフィルタリングする。

        CLASS_IMPLEMENTATION_SPEC.md § 11.4 ステップ3 に準拠する。

        フィルタリング:
        - learning_only_after_task_start=true: task_start_time以降のコメントのみ
        - learning_exclude_bot_comments=true: botコメントを除外

        Args:
            project_id: GitLabプロジェクトID
            mr_iid: MR IID
            task_start_time: タスク開始時刻（datetimeまたはISO文字列）

        Returns:
            フィルタリング済みのコメントリスト
        """
        try:
            raw_comments = self.gitlab_client.get_mr_comments(
                project_id=project_id,
                mr_iid=mr_iid,
            )
        except Exception as exc:
            logger.warning(
                "MRコメントの取得に失敗しました: mr_iid=%s, error=%s",
                mr_iid,
                exc,
            )
            return []

        comments: list[dict[str, Any]] = []
        for comment in raw_comments:
            # task_start_time以降のコメントのみ残す
            if (
                self.user_config.learning_only_after_task_start
                and task_start_time is not None
            ):
                created_at = (
                    comment.get("created_at")
                    if isinstance(comment, dict)
                    else getattr(comment, "created_at", None)
                )
                if created_at is not None:
                    # datetimeオブジェクトに変換して比較する
                    created_at_norm = self._normalize_datetime(created_at)
                    task_start_norm = self._normalize_datetime(task_start_time)
                    if created_at_norm is not None and task_start_norm is not None:
                        if created_at_norm < task_start_norm:
                            continue

            # botコメントを除外する
            if self.user_config.learning_exclude_bot_comments:
                author = (
                    comment.get("author")
                    if isinstance(comment, dict)
                    else getattr(comment, "author", None)
                )
                if author is not None:
                    is_bot = (
                        author.get("bot")
                        if isinstance(author, dict)
                        else getattr(author, "bot", False)
                    )
                    if is_bot:
                        continue

            if isinstance(comment, dict):
                comments.append(comment)
            else:
                comments.append({"body": getattr(comment, "body", str(comment))})

        return comments

    def _normalize_datetime(self, value: Any) -> Any:
        """
        日時値をdatetimeオブジェクトに正規化する。

        ISO 8601形式の文字列またはdatetimeオブジェクトを受け取り、
        datetimeオブジェクトとして返す。変換できない場合はNoneを返す。

        Args:
            value: 正規化対象の日時値（datetimeまたはISO 8601文字列）

        Returns:
            datetimeオブジェクト（変換失敗時はNone）
        """
        from datetime import datetime

        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                # ISO 8601形式（Z後置など）をパースする
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("日時文字列のパースに失敗しました: %s", value)
        return None

    def _get_guidelines(self, project_id: int, branch: str) -> str:
        """
        リポジトリからPROJECT_GUIDELINES.mdを取得する。

        CLASS_IMPLEMENTATION_SPEC.md § 11.4 ステップ4 に準拠する。

        Args:
            project_id: GitLabプロジェクトID
            branch: ブランチ名

        Returns:
            ガイドライン内容（存在しない場合は初期テンプレート）
        """
        try:
            content = self.gitlab_client.get_file_content(
                project_id=project_id,
                file_path="PROJECT_GUIDELINES.md",
                branch=branch,
            )
            if content:
                return content
        except Exception as exc:
            logger.info(
                "PROJECT_GUIDELINES.mdが存在しないため初期テンプレートを使用します: %s",
                exc,
            )

        return _INITIAL_GUIDELINES_TEMPLATE

    async def _call_llm_for_guideline_judgment(
        self,
        task_mr_iid: int,
        comments: list[dict[str, Any]],
        current_guidelines: str,
        task_uuid: str | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        """
        LLMを呼び出してガイドライン更新判定を行う。

        CLASS_IMPLEMENTATION_SPEC.md § 11.4 ステップ5 に準拠する。

        期待するJSON応答:
        - should_update: 更新が必要か（true/false）
        - rationale: 更新判断の理由（日本語）
        - category: カテゴリ（documentation/code/review/workflow/general）
        - updated_guidelines: 更新後のPROJECT_GUIDELINES.md全文（should_update=trueのみ）

        Args:
            task_mr_iid: タスクのMR IID
            comments: フィルタリング済みのコメントリスト
            current_guidelines: 現在のガイドライン内容
            task_uuid: トークン使用量記録用のタスク UUID（省略可能）
            username: トークン使用量記録用のユーザー名（省略可能）

        Returns:
            LLMの判定結果辞書
        """
        # コメントのテキストを抽出
        comments_text = "\n".join(
            [
                f"- {c.get('body', '') if isinstance(c, dict) else str(c)}"
                for c in comments
            ]
        )

        system_prompt = (
            "あなたはプロジェクトガイドライン管理者です。"
            "開発者のコメントを読み、プロジェクト全体に適用できる汎用的なガイドラインとして"
            "記録する価値があるかを判断してください。"
            "判断基準: 汎用性・妥当性・新規性・明確性。"
            "応答はJSON形式で返してください。"
        )

        user_prompt = (
            f"## タスク情報\nMR IID: !{task_mr_iid}\n\n"
            f"## コメント一覧\n{comments_text}\n\n"
            f"## 現在のガイドライン\n{current_guidelines}\n\n"
            "## 出力形式（JSON）\n"
            '{"should_update": true/false, "rationale": "判断理由", '
            '"category": "documentation/code/review/workflow/general", '
            '"updated_guidelines": "更新後のPROJECT_GUIDELINES.md全文（should_update=trueのみ）"}'
        )

        logger.debug(
            "LLMでガイドライン更新判定を実行します: mr_iid=%s, model=%s",
            task_mr_iid,
            self.user_config.learning_llm_model,
        )

        # Agent FrameworkのAgentを使用してLLM呼び出しを実行する
        try:
            from agent_framework import Agent
            from agent_framework.openai import OpenAIChatClient

            model_name: str = getattr(self.user_config, "learning_llm_model", "gpt-4o")
            chat_client = OpenAIChatClient(model_id=model_name)
            agent = Agent(
                client=chat_client,
                instructions=system_prompt,
            )

            # Agent.run() には文字列を直接渡す（自動的にuserメッセージに変換される）
            response = await agent.run(user_prompt)

            # AgentResponse.text で応答テキストを取得する
            response_text: str = response.text or ""

            # トークン使用量を記録する
            if self.token_usage_repository is not None:
                try:
                    usage = getattr(response, "usage_details", None)
                    model: str = str(getattr(chat_client, "model", "unknown"))
                    prompt_tokens: int = 0
                    completion_tokens: int = 0
                    if usage is not None:
                        prompt_tokens = int(usage.get("input_token_count") or 0)
                        completion_tokens = int(usage.get("output_token_count") or 0)
                    # usage_details が None の場合は tiktoken で推定する
                    if prompt_tokens == 0 and completion_tokens == 0:
                        from consumer.tools.token_estimator import estimate_token_count

                        prompt_tokens = estimate_token_count(user_prompt, model)
                        completion_tokens = estimate_token_count(response_text, model)
                        logger.warning(
                            "tiktokenによるトークン数推定: node_id=learning, model=%s,"
                            " prompt=%d, completion=%d",
                            model,
                            prompt_tokens,
                            completion_tokens,
                        )
                    if prompt_tokens > 0 or completion_tokens > 0:
                        await self.token_usage_repository.record_token_usage(
                            username=username or "",
                            task_uuid=task_uuid or "",
                            node_id="learning",
                            model=model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                        )
                        logger.info(
                            "トークン使用量を記録しました: node_id=learning, task_uuid=%s,"
                            " total=%d",
                            task_uuid,
                            prompt_tokens + completion_tokens,
                        )
                except Exception as _rec_exc:
                    logger.warning(
                        "トークン使用量の記録に失敗しました（無視）: node_id=learning, error=%s",
                        _rec_exc,
                    )

            # JSON応答をパースする
            return json.loads(response_text)

        except Exception as exc:
            logger.warning(
                "LLMによるガイドライン更新判定に失敗しました: mr_iid=%s, error=%s",
                task_mr_iid,
                exc,
            )
            return {
                "should_update": False,
                "rationale": f"LLM呼び出しエラー: {exc}",
                "category": "general",
            }

    async def _update_guidelines(
        self,
        project_id: int,
        mr_iid: int,
        updated_guidelines: str,
        branch: str,
    ) -> None:
        """
        PROJECT_GUIDELINES.mdをGitLabにコミットし、MRにコメントを投稿する。

        CLASS_IMPLEMENTATION_SPEC.md § 11.4 ステップ6 に準拠する。

        このメソッドのみGitLabに直接ファイル更新コミットを行うことが
        例外的に許可されている。

        CLASS_IMPLEMENTATION_SPEC.md § 11.5 例外的なGitLab API直接操作の許可 に準拠する。

        Args:
            project_id: GitLabプロジェクトID
            mr_iid: MR IID
            updated_guidelines: 更新後のガイドライン内容
            branch: コミット先ブランチ名
        """
        # ファイルをコミット
        self.gitlab_client.update_file(
            project_id=project_id,
            file_path="PROJECT_GUIDELINES.md",
            content=updated_guidelines,
            commit_message="自動学習: ガイドライン更新",
            branch=branch,
        )

        # MRに更新通知コメントを投稿
        comment_body = (
            "📚 **プロジェクトガイドライン自動更新**\n\n"
            "このMRのコメントを基にPROJECT_GUIDELINES.mdを自動更新しました。"
        )
        self.gitlab_client.post_mr_comment(
            project_id=project_id,
            mr_iid=mr_iid,
            comment=comment_body,
        )

        logger.info(
            "PROJECT_GUIDELINES.mdを更新しGitLabにコミットしました: "
            "project_id=%s, branch=%s",
            project_id,
            branch,
        )
