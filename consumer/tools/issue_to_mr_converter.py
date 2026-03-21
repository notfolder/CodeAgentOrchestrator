"""
IssueToMRConverter モジュール

GitLab Issue から Merge Request への変換を実行するクラスを定義する。
LLM を使ったブランチ名生成、MR 作成、Issue コメント転記、
Issue の Done 化までを一連の流れとして実行する。

CLASS_IMPLEMENTATION_SPEC.md § 10.2（IssueToMRConverter）に準拠する。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_framework.openai import OpenAIChatClient
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.gitlab import GitLabIssue, GitLabMergeRequest
    from shared.database.repositories.token_usage_repository import TokenUsageRepository

# chat_client ファクトリ関数の型エイリアス
# username を受け取り、OpenAIChatClient | None を返す非同期関数
ChatClientFactory = Callable[[str], Awaitable[Any]]

logger = logging.getLogger(__name__)

# ブランチ名生成の最大リトライ回数（重複があった場合に再生成する回数）
_BRANCH_NAME_MAX_RETRIES = 3


@dataclass
class IssueToMRConfig:
    """
    Issue → MR 変換設定。

    Attributes:
        branch_prefix: ブランチ名のプレフィックス（デフォルト "feature/"）
        target_branch: MR のターゲットブランチ（デフォルト "main"）
        mr_title_template: MR タイトルのテンプレート（デフォルト "WIP: {issue_title}"）
        bot_label: bot処理対象ラベル名。MRに付与して後続処理をトリガーする（デフォルト "coding agent"）
        done_label: Issue を Done 化するラベル名（デフォルト "coding agent done"）
        processing_label: 処理中ラベル名。Done 化時に削除する（デフォルト "coding agent processing"）
    """

    branch_prefix: str = field(default="feature/")
    target_branch: str = field(default="main")
    mr_title_template: str = field(default="WIP: {issue_title}")
    bot_label: str = field(default="coding agent")
    done_label: str = field(default="coding agent done")
    processing_label: str = field(default="coding agent processing")


class IssueToMRConverter:
    """
    Issue から Merge Request への変換クラス。

    Agent Framework の OpenAIChatClient を使ってブランチ名を生成し、
    GitLab API を通じてブランチ作成・MR 作成・コメント転記・Issue Done 化を
    一連の流れで実行する。

    ブランチ名生成時はブランチ重複チェック付きリトライを行い、重複がなくなるまで
    最大 _BRANCH_NAME_MAX_RETRIES 回再生成する。それでも重複が解消しない場合は
    デフォルト形式（{prefix}{iid}-{title[:30]}）を使用する。

    CLASS_IMPLEMENTATION_SPEC.md § 10.2 に準拠する。

    Attributes:
        gitlab_client: GitLab API クライアント
        chat_client: AF ChatClient（ブランチ名生成用）
        chat_client_factory: username から ChatClient を動的生成するファクトリ関数
        config: IssueToMRConfig 設定オブジェクト
    """

    def __init__(
        self,
        gitlab_client: "GitlabClient",
        chat_client: "OpenAIChatClient | None" = None,
        config: IssueToMRConfig | None = None,
        chat_client_factory: ChatClientFactory | None = None,
        token_usage_repository: "TokenUsageRepository | None" = None,
    ) -> None:
        """
        初期化。

        Args:
            gitlab_client: GitLab API クライアント
            chat_client: AF の ChatClient（ブランチ名生成用。None の場合はデフォルト形式を使用）
            config: Issue → MR 変換設定（省略時はデフォルト設定を使用）
            chat_client_factory: username から ChatClient を動的生成するファクトリ関数。
                chat_client が None の場合に使用される。
            token_usage_repository: トークン使用量記録用リポジトリ（None の場合は記録しない）
        """
        self.gitlab_client = gitlab_client
        self.chat_client = chat_client
        self.chat_client_factory = chat_client_factory
        self.config = config if config is not None else IssueToMRConfig()
        self.token_usage_repository = token_usage_repository

    def _make_default_branch_name(self, issue: "GitLabIssue") -> str:
        """
        デフォルト形式のブランチ名を生成する。

        AUTOMATA_CODEX_SPEC.md § 5.0.5 に準拠する形式:
        {prefix}{iid}-{title の先頭30文字をハイフン区切り}

        Args:
            issue: 変換対象の GitLab Issue

        Returns:
            デフォルトブランチ名文字列
        """
        safe_title = issue.title[:30].replace(" ", "-")
        return f"{self.config.branch_prefix}{issue.iid}-{safe_title}"

    async def _record_token_usage(
        self,
        response: Any,
        username: str | None,
        task_uuid: str | None,
        node_id: str,
        chat_client: Any,
    ) -> None:
        """
        LLM 呼び出し結果のトークン使用量を token_usage_repository に記録する。

        token_usage_repository が未設定の場合や usage_details が取得できない場合は何もしない。
        記録失敗は警告ログのみとし、処理フローに影響させない。

        Args:
            response: agent.run() の戻り値（AgentResponse）
            username: タスク実行ユーザー名
            task_uuid: タスク UUID
            node_id: トークン使用量レコードのノード ID
            chat_client: 使用した ChatClient（モデル名取得に使用）
        """
        if self.token_usage_repository is None:
            return

        try:
            usage = getattr(response, "usage_details", None)
            if usage is None:
                return

            prompt_tokens: int = int(getattr(usage, "input_token_count", 0) or 0)
            completion_tokens: int = int(getattr(usage, "output_token_count", 0) or 0)
            if prompt_tokens == 0 and completion_tokens == 0:
                return

            # chat_client からモデル名を取得する（取得できない場合は "unknown"）
            model: str = str(getattr(chat_client, "model", "unknown"))

            await self.token_usage_repository.record_token_usage(
                username=username or "",
                task_uuid=task_uuid or "",
                node_id=node_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            logger.info(
                "トークン使用量を記録しました: node_id=%s, task_uuid=%s, total=%d",
                node_id,
                task_uuid,
                prompt_tokens + completion_tokens,
            )
        except Exception as exc:
            logger.warning(
                "トークン使用量の記録に失敗しました（無視）: node_id=%s, error=%s",
                node_id,
                exc,
            )

    async def _generate_branch_name(
        self,
        issue: "GitLabIssue",
        username: str | None = None,
        task_uuid: str | None = None,
        llm_warnings: list[str] | None = None,
    ) -> str:
        """
        AF Agent を使ってブランチ名を生成する。

        chat_client が設定されている場合は Agent.run() でブランチ名を生成し、
        生成したブランチ名が GitLab 上で既に存在する場合は再生成する（最大 _BRANCH_NAME_MAX_RETRIES 回）。
        全リトライが失敗した場合、または chat_client が None の場合はデフォルト形式を使用する。
        LLM 呼び出し後に token_usage_repository が設定されている場合はトークン使用量を記録する。

        Args:
            issue: 変換対象の GitLab Issue
            username: タスク実行ユーザーの GitLab ユーザー名（chat_client_factory 呼び出しに使用）
            task_uuid: トークン使用量記録用のタスク UUID
            llm_warnings: LLM処理失敗時の警告メッセージを追記するリスト（Noneの場合は追記しない）

        Returns:
            生成されたブランチ名文字列
        """
        # chat_client が未設定の場合、ファクトリ関数で動的に生成を試みる
        chat_client = self.chat_client
        factory_exc: Exception | None = None
        if chat_client is None and self.chat_client_factory is not None and username:
            try:
                chat_client = await self.chat_client_factory(username)
                logger.info(
                    "chat_client_factoryからchat_clientを生成しました: username=%s",
                    username,
                )
            except Exception as exc:
                factory_exc = exc
                logger.warning(
                    "chat_client_factoryによるchat_client生成に失敗しました: username=%s, error=%s",
                    username,
                    exc,
                )

        if chat_client is None:
            branch_name = self._make_default_branch_name(issue)
            if factory_exc is not None:
                # ファクトリ失敗によるフォールバック: Issueに警告を通知する
                logger.warning(
                    "LLMクライアント生成失敗のためデフォルトブランチ名を使用します: %s",
                    branch_name,
                )
                if llm_warnings is not None:
                    llm_warnings.append(
                        f"LLMクライアントの生成に失敗したためブランチ名を自動生成できませんでした"
                        f"（エラー: {factory_exc}）。デフォルト名を使用します: {branch_name}"
                    )
            else:
                logger.info(
                    "chat_clientが未設定のためデフォルトブランチ名を使用します: %s",
                    branch_name,
                )
            return branch_name

        from agent_framework import Agent

        # 既存ブランチ名の一覧を取得してプロンプトに含める（重複回避のため）
        existing_branches: list[str] = []
        try:
            existing_branches = self.gitlab_client.list_branches(issue.project_id)
        except Exception as exc:
            logger.warning("既存ブランチ一覧の取得に失敗しました: %s", exc)

        prompt = (
            f"次のIssueに対するGitブランチ名を生成してください。\n"
            f"プレフィックス: {self.config.branch_prefix}\n"
            f"Issue IID: {issue.iid}\n"
            f"Issue タイトル: {issue.title}\n\n"
            f"要件:\n"
            f"- 先頭に '{self.config.branch_prefix}' を付ける\n"
            f"- 英小文字・数字・ハイフンのみを使用する\n"
            f"- スペースは '-' に変換する\n"
            f"- Issue IID を含める\n"
            f"- ブランチ名のみを出力する（説明文は不要）"
        )
        if existing_branches:
            branch_list_str = ", ".join(existing_branches)
            prompt += (
                f"\n\n以下のブランチ名は既に存在します。重複しないようにしてください:\n"
                f"{branch_list_str}"
            )

        agent = Agent(client=chat_client)
        last_exc: Exception | None = None

        for attempt in range(_BRANCH_NAME_MAX_RETRIES):
            try:
                # Agent.run() には文字列を直接渡す（自動的にuserメッセージに変換される）
                response = await agent.run(prompt)
                # AgentResponse.text で応答テキストを取得する
                branch_name = (response.text or "").strip()

                # 不正文字を除去して正規化する（英小文字・数字・ハイフン・スラッシュのみ許可）
                branch_name = re.sub(r"[^a-zA-Z0-9\-/]", "-", branch_name)
                branch_name = re.sub(r"-{2,}", "-", branch_name).strip("-")

                if not branch_name:
                    logger.warning(
                        "LLMのブランチ名生成結果が空でした（試行%d/%d）。再試行します。",
                        attempt + 1,
                        _BRANCH_NAME_MAX_RETRIES,
                    )
                    continue

                # ブランチ重複チェック
                branch_exists = self.gitlab_client.branch_exists(
                    project_id=issue.project_id,
                    branch_name=branch_name,
                )
                if not branch_exists:
                    logger.info(
                        "LLMによるブランチ名生成成功（試行%d/%d）: %s",
                        attempt + 1,
                        _BRANCH_NAME_MAX_RETRIES,
                        branch_name,
                    )
                    # トークン使用量を記録する（成功時のみ）
                    await self._record_token_usage(
                        response=response,
                        username=username,
                        task_uuid=task_uuid,
                        node_id="issue_to_mr_branch_name",
                        chat_client=chat_client,
                    )
                    return branch_name

                logger.warning(
                    "生成したブランチ名が既に存在します（試行%d/%d）: %s 再生成します。",
                    attempt + 1,
                    _BRANCH_NAME_MAX_RETRIES,
                    branch_name,
                )
                # リトライ時はIssue番号のサフィックスをプロンプトに追加する
                prompt = (
                    f"{prompt}\n\n"
                    f"注意: '{branch_name}' は既に存在します。"
                    f" 末尾に '-v{attempt + 2}' を付けるなど、異なる名前を生成してください。"
                )

            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLMブランチ名生成に失敗しました（試行%d/%d）: %s",
                    attempt + 1,
                    _BRANCH_NAME_MAX_RETRIES,
                    exc,
                )

        # 全リトライ失敗: デフォルト形式にフォールバックする
        branch_name = self._make_default_branch_name(issue)
        logger.warning(
            "LLMブランチ名生成が全て失敗しました。デフォルト形式を使用します: %s",
            branch_name,
        )
        if llm_warnings is not None and last_exc is not None:
            llm_warnings.append(
                f"LLMによるブランチ名の自動生成に失敗しました"
                f"（最終エラー: {last_exc}）。デフォルト名を使用します: {branch_name}"
            )
        return branch_name

    async def _generate_mr_title(
        self,
        issue: "GitLabIssue",
        username: str | None = None,
        task_uuid: str | None = None,
        llm_warnings: list[str] | None = None,
    ) -> str:
        """
        AF Agent を使って MR タイトルを生成する。

        chat_client が設定されている場合は Agent.run() で Issueタイトル・説明から
        適切な MR タイトルを生成する。生成に失敗した場合はデフォルトテンプレートを使用する。
        LLM 呼び出し後に token_usage_repository が設定されている場合はトークン使用量を記録する。

        Args:
            issue: 変換対象の GitLab Issue
            username: タスク実行ユーザーの GitLab ユーザー名（chat_client_factory 呼び出しに使用）
            task_uuid: トークン使用量記録用のタスク UUID
            llm_warnings: LLM処理失敗時の警告メッセージを追記するリスト（Noneの場合は追記しない）

        Returns:
            生成された MR タイトル文字列
        """
        # chat_client が未設定の場合、ファクトリ関数で動的に生成を試みる
        chat_client = self.chat_client
        factory_exc: Exception | None = None
        if chat_client is None and self.chat_client_factory is not None and username:
            try:
                chat_client = await self.chat_client_factory(username)
            except Exception as exc:
                factory_exc = exc
                logger.warning(
                    "MRタイトル生成用chat_clientの生成に失敗しました: %s", exc
                )

        default_title = self.config.mr_title_template.format(issue_title=issue.title)

        if chat_client is None:
            if factory_exc is not None:
                # ファクトリ失敗によるフォールバック: Issueに警告を通知する
                logger.warning(
                    "LLMクライアント生成失敗のためデフォルトMRタイトルを使用します: %s",
                    default_title,
                )
                if llm_warnings is not None:
                    llm_warnings.append(
                        f"LLMクライアントの生成に失敗したためMRタイトルを自動生成できませんでした"
                        f"（エラー: {factory_exc}）。デフォルトタイトルを使用します: {default_title}"
                    )
            else:
                logger.info(
                    "chat_clientが未設定のためデフォルトMRタイトルを使用します: %s",
                    default_title,
                )
            return default_title

        from agent_framework import Agent

        # Issue説明の先頭500文字を渡す（長すぎるとトークンの無駄になるため）
        description_excerpt = (issue.description or "")[:500]
        prompt = (
            f"次のGitLab IssueからMerge Requestのタイトルを生成してください。\n"
            f"Issue タイトル: {issue.title}\n"
            f"Issue 説明: {description_excerpt}\n\n"
            f"要件:\n"
            f"- 先頭に 'Draft: ' を付ける\n"
            f"- Issue の内容を簡潔に表す日本語または英語のタイトルにする\n"
            f"- 50文字以内にする\n"
            f"- タイトルの文字列のみを出力する（説明文は不要）"
        )

        try:
            agent = Agent(client=chat_client)
            response = await agent.run(prompt)
            mr_title = (response.text or "").strip()
            # 改行やMarkdown装飾が混入した場合は除去する
            mr_title = mr_title.split("\n")[0].strip("`").strip()
            if mr_title:
                logger.info("LLMによるMRタイトル生成成功: %s", mr_title)
                # トークン使用量を記録する
                await self._record_token_usage(
                    response=response,
                    username=username,
                    task_uuid=task_uuid,
                    node_id="issue_to_mr_mr_title",
                    chat_client=chat_client,
                )
                return mr_title
        except Exception as exc:
            logger.warning("LLMによるMRタイトル生成に失敗しました: %s", exc)
            if llm_warnings is not None:
                llm_warnings.append(
                    f"LLMによるMRタイトルの自動生成に失敗しました"
                    f"（エラー: {exc}）。デフォルトタイトルを使用します: {default_title}"
                )

        logger.info("デフォルトMRタイトルを使用します: %s", default_title)
        return default_title

    async def convert(self, issue_or_task: "GitLabIssue | Any") -> "GitLabMergeRequest":
        """
        Issue から Merge Request への変換を実行する。

        引数に Task が渡された場合は gitlab_client で GitLabIssue を取得してから処理する。
        引数に GitLabIssue が直接渡された場合はそのまま使用する。

        処理フロー:
        1. LLM でブランチ名を生成する
        2. ブランチを作成する
        3. 空コミットを作成する（create_commit が利用可能な場合のみ）
        4. MR を作成する（タイトル・説明のみ設定）
        5. Issue のコメントを MR に転記する
        6. Issue のラベル・アサイニーを MR にコピーする（update_merge_request）
        7. Issue にコメントで MR リンクを投稿する
        8. Issue を Done ラベルでクローズ化する

        Args:
            issue_or_task: 変換対象の GitLab Issue または Task オブジェクト

        Returns:
            作成された GitLabMergeRequest オブジェクト
        """
        from shared.models.task import Task as _Task

        # タスク実行ユーザー名とタスク UUID（chat_client_factory およびトークン記録に使用する）
        username: str | None = None
        task_uuid: str | None = None

        if isinstance(issue_or_task, _Task):
            # Task が渡された場合は GitLab API から GitLabIssue を取得する
            task = issue_or_task
            username = task.username
            task_uuid = task.task_uuid
            issue = self.gitlab_client.get_issue(
                project_id=task.project_id,
                issue_iid=task.issue_iid,
            )
        else:
            issue = issue_or_task

        project_id = issue.project_id
        logger.info(
            "Issue→MR変換開始: project_id=%d, issue_iid=%d, title=%s",
            project_id,
            issue.iid,
            issue.title,
        )

        # ① ブランチ名の生成（LLM失敗時の警告を収集するリスト）
        llm_warnings: list[str] = []
        branch_name = await self._generate_branch_name(
            issue, username=username, task_uuid=task_uuid, llm_warnings=llm_warnings
        )

        # ② ブランチ作成
        self.gitlab_client.create_branch(
            project_id=project_id,
            branch_name=branch_name,
            ref=self.config.target_branch,
        )
        logger.info("ブランチ作成完了: %s", branch_name)

        # ③ 空コミット作成（create_commit が利用可能な場合のみ実行する）
        if hasattr(self.gitlab_client, "create_commit"):
            try:
                self.gitlab_client.create_commit(
                    project_id=project_id,
                    branch=branch_name,
                    commit_message=f"Initial commit for issue #{issue.iid}",
                    actions=[],
                    allow_empty=True,
                )
                logger.info("空コミット作成完了: branch=%s", branch_name)
            except Exception as exc:
                logger.warning("空コミット作成をスキップします: %s", exc)
        else:
            logger.info("create_commit が利用不可のため空コミット作成をスキップします")

        # ④ MR 作成（タイトルはLLMで生成。ラベル・アサイニーは次のステップで設定する）
        mr_title = await self._generate_mr_title(
            issue, username=username, task_uuid=task_uuid, llm_warnings=llm_warnings
        )

        mr = self.gitlab_client.create_merge_request(
            project_id=project_id,
            source_branch=branch_name,
            target_branch=self.config.target_branch,
            title=mr_title,
            description=issue.description,
        )
        logger.info("MR作成完了: mr_iid=%d, title=%s", mr.iid, mr_title)

        # ⑤ Issue コメントを MR に転記する
        try:
            issue_notes = self.gitlab_client.get_issue_notes(project_id, issue.iid)
            for note in issue_notes:
                # システムコメントは転記しない
                if note.system:
                    continue
                self.gitlab_client.create_merge_request_note(
                    project_id, mr.iid, note.body
                )
            logger.info(
                "Issueコメント転記完了: %d 件",
                sum(1 for n in issue_notes if not n.system),
            )
        except Exception as exc:
            logger.warning("Issueコメントの転記に失敗しました: %s", exc)

        # ⑥ Issueのラベル・アサイニー・レビュアーをMRに設定する
        try:
            # ラベル操作の直前にIssueを再取得して最新のラベルを使用する
            fresh_issue = self.gitlab_client.get_issue(
                project_id=project_id, issue_iid=issue.iid
            )
            # u.id が None になりうる場合（GitLabUser.email同様にオプション）に備えてフィルタリングする
            assignee_ids: list[int] = [
                u.id for u in fresh_issue.assignees if u.id is not None
            ]
            # 最新の Issue ラベルから processing_label を除去し、bot_label を付与する
            mr_labels: list[str] = list(
                (set(fresh_issue.labels or []) - {self.config.processing_label})
                | {self.config.bot_label}
            )
            # Issue の author をレビュアーとして設定する
            reviewer_ids: list[int] = []
            if issue.author and issue.author.id is not None:
                reviewer_ids = [issue.author.id]
            mr = self.gitlab_client.update_merge_request(
                project_id=project_id,
                mr_iid=mr.iid,
                labels=mr_labels or None,
                assignee_ids=assignee_ids or None,
                reviewer_ids=reviewer_ids or None,
            )
            logger.info(
                "MRへのラベル・アサイニー・レビュアー設定完了: labels=%s, assignee_ids=%s, reviewer_ids=%s",
                mr_labels,
                assignee_ids,
                reviewer_ids,
            )
        except Exception as exc:
            logger.warning("MRへのラベル・アサイニーコピーに失敗しました: %s", exc)

        # ⑦ Issue に MR リンクのコメントを投稿する
        try:
            self.gitlab_client.create_issue_note(
                project_id=project_id,
                issue_iid=issue.iid,
                body=f"Created MR: !{mr.iid}",
            )
            logger.info("IssueへのMRリンクコメント投稿完了: !%d", mr.iid)
        except Exception as exc:
            logger.warning("IssueへのMRリンクコメント投稿に失敗しました: %s", exc)

        # ⑧ Issue に Done ラベルを追加する（processing_label を削除して done_label を追加: coding_agent 準拠）
        try:
            # ラベル操作の直前にIssueを再取得して最新のラベルを使用する
            fresh_issue_for_done = self.gitlab_client.get_issue(
                project_id=project_id, issue_iid=issue.iid
            )
            done_labels = list(
                (set(fresh_issue_for_done.labels) - {self.config.processing_label})
                | {self.config.done_label}
            )
            self.gitlab_client.update_issue_labels(
                project_id=project_id,
                issue_iid=issue.iid,
                labels=done_labels,
            )
            logger.info("IssueのDoneラベル設定完了: %s", done_labels)
        except Exception as exc:
            logger.warning("IssueのDoneラベル設定に失敗しました: %s", exc)

        # LLM処理失敗の警告をIssueにコメントとして通知する
        if llm_warnings:
            try:
                warning_lines = "\n".join(f"- {w}" for w in llm_warnings)
                warning_body = (
                    "⚠️ **LLM処理に関する警告**\n\n"
                    f"{warning_lines}\n\n"
                    "_この警告はAutomata Codexにより自動投稿されました。_"
                )
                self.gitlab_client.create_issue_note(
                    project_id=project_id,
                    issue_iid=issue.iid,
                    body=warning_body,
                )
                logger.info(
                    "LLM警告コメントをIssueに投稿しました: %d件", len(llm_warnings)
                )
            except Exception as exc:
                logger.warning("LLM警告コメントのIssueへの投稿に失敗しました: %s", exc)

        logger.info(
            "Issue→MR変換完了: project_id=%d, issue_iid=%d, mr_iid=%d",
            project_id,
            issue.iid,
            mr.iid,
        )
        return mr
