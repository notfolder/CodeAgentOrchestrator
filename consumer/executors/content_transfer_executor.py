"""
ContentTransferExecutor モジュール

Issue のコメント（Note）を対応する MR に転記する Executor を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 3.3（ContentTransferExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from consumer.executors.base_executor import BaseExecutor

if TYPE_CHECKING:
    from consumer.agents.configurable_agent import WorkflowContext
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)


class ContentTransferExecutor(BaseExecutor):
    """
    コンテンツ転記 Executor

    Issue のコメント（Note）を取得し、対応する MR にそのまま転記する。
    転記したコメント数をワークフローコンテキストに保存する。

    Attributes:
        gitlab_client: GitLabAPI クライアント
    """

    def __init__(self, gitlab_client: GitlabClient) -> None:
        """
        ContentTransferExecutor を初期化する。

        Args:
            gitlab_client: GitLabAPI クライアント
        """
        self.gitlab_client = gitlab_client

    async def handle(self, msg: Any, ctx: WorkflowContext) -> None:
        """
        Issue のコメントを MR に転記する。

        処理フロー:
        1. コンテキストから issue_iid と project_id を取得する
        2. GitLab から Issue のコメント一覧を取得する
        3. コンテキストから mr_iid を取得する
        4. 各コメントを MR に転記する
        5. 転記したコメント数をコンテキストに保存する

        Args:
            msg: 受け取るメッセージ（未使用）
            ctx: ワークフローコンテキスト
        """
        # コンテキストからIssue情報を取得する
        issue_iid: int = await self.get_context_value(ctx, "issue_iid")
        project_id: int = await self.get_context_value(ctx, "project_id")
        mr_iid: int = await self.get_context_value(ctx, "mr_iid")

        logger.info(
            "IssueコメントをMRに転記します: project_id=%s, issue_iid=%s → mr_iid=%s",
            project_id,
            issue_iid,
            mr_iid,
        )

        # IssueのNote一覧を取得する（システムコメントは除外する）
        notes = self.gitlab_client.get_issue_notes(
            project_id=project_id,
            issue_iid=issue_iid,
        )
        non_system_notes = [note for note in notes if not note.system]

        logger.info(
            "Issueのコメントを取得しました: issue_iid=%s, count=%d",
            issue_iid,
            len(non_system_notes),
        )

        # 各コメントをMRに転記する
        transferred_count = 0
        failed_note_ids: list[int] = []
        for note in non_system_notes:
            try:
                self.gitlab_client.create_merge_request_note(
                    project_id=project_id,
                    mr_iid=mr_iid,
                    body=note.body,
                )
                transferred_count += 1
                logger.debug(
                    "コメントを転記しました: note_id=%s", note.id
                )
            except Exception:
                logger.exception(
                    "コメントの転記に失敗しました: note_id=%s", note.id
                )
                failed_note_ids.append(note.id)

        # 転記結果をコンテキストに保存する
        await self.set_context_value(
            ctx, "transferred_comments_count", transferred_count
        )
        # 転記失敗したコメントIDを保存して後続処理・デバッグで活用できるようにする
        await self.set_context_value(
            ctx, "failed_transfer_note_ids", failed_note_ids
        )

        logger.info(
            "コメント転記が完了しました: mr_iid=%s, transferred=%d/%d",
            mr_iid,
            transferred_count,
            len(non_system_notes),
        )
