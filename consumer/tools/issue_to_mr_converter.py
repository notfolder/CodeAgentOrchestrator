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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_framework.openai import OpenAIChatClient
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.gitlab import GitLabIssue, GitLabMergeRequest

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
        done_label: Issue を Done 化するラベル名（デフォルト "coding agent done"）
        processing_label: 処理中ラベル名。Done 化時に削除する（デフォルト "coding agent processing"）
    """

    branch_prefix: str = field(default="feature/")
    target_branch: str = field(default="main")
    mr_title_template: str = field(default="WIP: {issue_title}")
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
        config: IssueToMRConfig 設定オブジェクト
    """

    def __init__(
        self,
        gitlab_client: "GitlabClient",
        chat_client: "OpenAIChatClient | None" = None,
        config: IssueToMRConfig | None = None,
    ) -> None:
        """
        初期化。

        Args:
            gitlab_client: GitLab API クライアント
            chat_client: AF の ChatClient（ブランチ名生成用。None の場合はデフォルト形式を使用）
            config: Issue → MR 変換設定（省略時はデフォルト設定を使用）
        """
        self.gitlab_client = gitlab_client
        self.chat_client = chat_client
        self.config = config if config is not None else IssueToMRConfig()

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

    async def _generate_branch_name(self, issue: "GitLabIssue") -> str:
        """
        AF Agent を使ってブランチ名を生成する。

        chat_client が設定されている場合は Agent.run() でブランチ名を生成し、
        生成したブランチ名が GitLab 上で既に存在する場合は再生成する（最大 _BRANCH_NAME_MAX_RETRIES 回）。
        全リトライが失敗した場合、または chat_client が None の場合はデフォルト形式を使用する。

        Args:
            issue: 変換対象の GitLab Issue

        Returns:
            生成されたブランチ名文字列
        """
        if self.chat_client is None:
            branch_name = self._make_default_branch_name(issue)
            logger.info(
                "chat_clientが未設定のためデフォルトブランチ名を使用します: %s",
                branch_name,
            )
            return branch_name

        from agent_framework import Agent

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

        agent = Agent(client=self.chat_client)

        for attempt in range(_BRANCH_NAME_MAX_RETRIES):
            try:
                response = await agent.run([{"role": "user", "content": prompt}])
                # AgentResponseから応答テキストを取得する
                branch_name = ""
                if hasattr(response, "content") and isinstance(response.content, list):
                    # content がリストの場合は text 属性を持つ最初のアイテムを取得する
                    for item in response.content:
                        if hasattr(item, "text"):
                            branch_name = item.text.strip()
                            break
                    if not branch_name:
                        # text 属性を持つアイテムが存在しない場合はデフォルト形式にフォールバックする
                        logger.warning(
                            "LLM応答のcontentリストにtext属性が見つかりません（試行%d/%d）。"
                            "再試行します。",
                            attempt + 1,
                            _BRANCH_NAME_MAX_RETRIES,
                        )
                        continue
                elif hasattr(response, "content") and isinstance(response.content, str):
                    branch_name = response.content.strip()
                else:
                    branch_name = str(response).strip()

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
        return branch_name

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

        if isinstance(issue_or_task, _Task):
            # Task が渡された場合は GitLab API から GitLabIssue を取得する
            task = issue_or_task
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

        # ① ブランチ名の生成
        branch_name = await self._generate_branch_name(issue)

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

        # ④ MR 作成（タイトルと説明のみ設定。ラベル・アサイニーは次のステップで設定する）
        mr_title = self.config.mr_title_template.format(issue_title=issue.title)

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

        # ⑥ Issueのラベル・アサイニーをMRにコピーする
        try:
            # u.id が None になりうる場合（GitLabUser.email同様にオプション）に備えてフィルタリングする
            assignee_ids: list[int] = [
                u.id for u in issue.assignees if u.id is not None
            ]
            mr = self.gitlab_client.update_merge_request(
                project_id=project_id,
                mr_iid=mr.iid,
                labels=issue.labels or None,
                assignee_ids=assignee_ids or None,
            )
            logger.info(
                "MRへのラベル・アサイニーコピー完了: labels=%s, assignee_ids=%s",
                issue.labels,
                assignee_ids,
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
            done_labels = list(
                (set(issue.labels) - {self.config.processing_label})
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

        logger.info(
            "Issue→MR変換完了: project_id=%d, issue_iid=%d, mr_iid=%d",
            project_id,
            issue.iid,
            mr.iid,
        )
        return mr
