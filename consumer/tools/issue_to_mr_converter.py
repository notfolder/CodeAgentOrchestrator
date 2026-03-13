"""
IssueToMRConverter モジュール

GitLab Issue から Merge Request への変換を実行するクラスを定義する。
LLM を使ったブランチ名生成、MR 作成、Issue コメント転記、
Issue の Done 化までを一連の流れとして実行する。

CLASS_IMPLEMENTATION_SPEC.md § 10.2（IssueToMRConverter）に準拠する。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.gitlab import GitLabIssue, GitLabMergeRequest

logger = logging.getLogger(__name__)


@dataclass
class IssueToMRConfig:
    """
    Issue → MR 変換設定。

    Attributes:
        branch_prefix: ブランチ名のプレフィックス（デフォルト "feature/"）
        target_branch: MR のターゲットブランチ（デフォルト "main"）
        mr_title_template: MR タイトルのテンプレート（デフォルト "WIP: {issue_title}"）
        done_label: Issue を Done 化するラベル名（デフォルト "Done"）
    """

    branch_prefix: str = field(default="feature/")
    target_branch: str = field(default="main")
    mr_title_template: str = field(default="WIP: {issue_title}")
    done_label: str = field(default="Done")


class IssueToMRConverter:
    """
    Issue から Merge Request への変換クラス。

    LLM クライアントを使ってブランチ名を生成し、GitLab API を通じて
    ブランチ作成・MR 作成・コメント転記・Issue Done 化を一連の流れで実行する。

    CLASS_IMPLEMENTATION_SPEC.md § 10.2 に準拠する。

    Attributes:
        gitlab_client: GitLab API クライアント
        llm_client: LLM クライアント（ブランチ名生成用）
        config: IssueToMRConfig 設定オブジェクト
    """

    def __init__(
        self,
        gitlab_client: "GitlabClient",
        llm_client: Any,
        config: IssueToMRConfig | None = None,
    ) -> None:
        """
        初期化。

        Args:
            gitlab_client: GitLab API クライアント
            llm_client: LLM クライアント（generate メソッドを持つことが期待される）
            config: Issue → MR 変換設定（省略時はデフォルト設定を使用）
        """
        self.gitlab_client = gitlab_client
        self.llm_client = llm_client
        self.config = config if config is not None else IssueToMRConfig()

    async def _generate_branch_name(self, issue: "GitLabIssue") -> str:
        """
        LLM を使ってブランチ名を生成する。

        llm_client に generate メソッドがある場合は LLM でブランチ名を生成し、
        ない場合はデフォルト形式（{prefix}{iid}-{title[:30]}）を使用する。

        Args:
            issue: 変換対象の GitLab Issue

        Returns:
            生成されたブランチ名文字列
        """
        if hasattr(self.llm_client, "generate"):
            prompt = (
                f"Generate a git branch name for the following issue: "
                f"{issue.title}. Use format: {self.config.branch_prefix}{{issue_iid}}"
            )
            try:
                generate_fn = self.llm_client.generate
                # generate メソッドが非同期の場合は await する
                if inspect.iscoroutinefunction(generate_fn):
                    branch_name: str = await generate_fn(prompt)
                else:
                    branch_name = generate_fn(prompt)
                branch_name = branch_name.strip()
                if branch_name:
                    logger.info("LLMによるブランチ名生成: %s", branch_name)
                    return branch_name
            except Exception as exc:
                logger.warning(
                    "LLMブランチ名生成に失敗しました。デフォルト形式を使用します: %s",
                    exc,
                )

        # デフォルト: {prefix}{iid}-{title の先頭30文字をハイフン区切り}
        safe_title = issue.title[:30].replace(" ", "-")
        branch_name = f"{self.config.branch_prefix}{issue.iid}-{safe_title}"
        logger.info("デフォルト形式でブランチ名を生成: %s", branch_name)
        return branch_name

    async def convert(self, issue: "GitLabIssue") -> "GitLabMergeRequest":
        """
        Issue から Merge Request への変換を実行する。

        処理フロー:
        1. LLM でブランチ名を生成する
        2. ブランチを作成する
        3. 空コミットを作成する（create_commit が利用可能な場合のみ）
        4. MR を作成する（Issue のラベル・アサイニーも設定）
        5. Issue のコメントを MR に転記する
        6. Issue にコメントで MR リンクを投稿する
        7. Issue を Done ラベルでクローズ化する

        Args:
            issue: 変換対象の GitLab Issue

        Returns:
            作成された GitLabMergeRequest オブジェクト
        """
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
                )
                logger.info("空コミット作成完了: branch=%s", branch_name)
            except Exception as exc:
                logger.warning("空コミット作成をスキップします: %s", exc)
        else:
            logger.info("create_commit が利用不可のため空コミット作成をスキップします")

        # ④ MR 作成（Issue のラベルとアサイニーを設定する）
        mr_title = self.config.mr_title_template.format(issue_title=issue.title)
        assignee_ids: list[int] = [u.id for u in issue.assignees if u.id]

        mr = self.gitlab_client.create_merge_request(
            project_id=project_id,
            source_branch=branch_name,
            target_branch=self.config.target_branch,
            title=mr_title,
            description=issue.description,
            labels=issue.labels if issue.labels else None,
            assignee_ids=assignee_ids if assignee_ids else None,
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
                "Issueコメント転記完了: %d 件", sum(1 for n in issue_notes if not n.system)
            )
        except Exception as exc:
            logger.warning("Issueコメントの転記に失敗しました: %s", exc)

        # ⑥ Issue に MR リンクのコメントを投稿する
        try:
            self.gitlab_client.create_issue_note(
                project_id=project_id,
                issue_iid=issue.iid,
                body=f"Created MR: !{mr.iid}",
            )
            logger.info("IssueへのMRリンクコメント投稿完了: !%d", mr.iid)
        except Exception as exc:
            logger.warning("IssueへのMRリンクコメント投稿に失敗しました: %s", exc)

        # ⑦ Issue に Done ラベルを追加してクローズ化する
        try:
            done_labels = list(issue.labels) + [self.config.done_label]
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
