"""
CommentCheckMiddleware モジュール

ノード実行前に GitLab MR の新規コメントを確認し、
新規コメントが存在する場合にリダイレクトシグナルを返す Middleware を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 5.2（CommentCheckMiddleware）に準拠する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from consumer.middleware.i_middleware import IMiddleware, MiddlewareSignal, WorkflowNode

if TYPE_CHECKING:
    from agent_framework import WorkflowContext
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)


class CommentCheckMiddleware(IMiddleware):
    """
    コメントチェック Middleware

    ノード実行前に GitLab MR の新規コメントを確認する。
    新規ユーザーコメントが検出された場合はリダイレクトシグナルを返す。
    ノードのメタデータに check_comments_before=True が設定されている場合のみ動作する。

    Attributes:
        gitlab_client: GitLab API クライアント
        last_comment_check_time: タスクID → 最終チェック日時のマッピング
    """

    def __init__(self, gitlab_client: GitlabClient) -> None:
        """
        初期化

        Args:
            gitlab_client: GitLab API クライアント
        """
        self.gitlab_client = gitlab_client
        # タスクID → 最終コメントチェック日時のマッピング
        self.last_comment_check_time: dict[str, datetime] = {}

    async def intercept(
        self,
        phase: str,
        node: WorkflowNode,
        context: WorkflowContext,
        **kwargs: Any,
    ) -> Optional[MiddlewareSignal]:
        """
        コメントチェック介入処理

        before_execution フェーズでのみ動作する。
        ノードのメタデータに check_comments_before=True が設定されている場合、
        GitLab MR の新規コメントを確認し、存在すればリダイレクトシグナルを返す。

        Args:
            phase: 実行フェーズ
            node: 実行対象ノード情報
            context: ワークフローコンテキスト
            **kwargs: 追加引数（未使用）

        Returns:
            MiddlewareSignal: 新規コメントが存在する場合（action="redirect"）
            None: コメントなし、またはチェック対象外のフェーズ・ノードの場合
        """
        # before_execution フェーズ以外はスキップする
        if phase != "before_execution":
            return None

        # メタデータの check_comments_before フラグを確認する
        if not getattr(node.metadata, "check_comments_before", False):
            return None

        # コンテキストからタスク識別情報を取得する
        project_id: int | None = context.get_state("project_id")
        mr_iid: int | None = context.get_state("mr_iid")
        task_uuid: str | None = context.get_state("task_uuid")

        if project_id is None or mr_iid is None:
            logger.warning(
                "CommentCheckMiddleware: project_id または mr_iid が未設定のためスキップする"
            )
            return None

        # 最終チェック時刻を取得する（未設定の場合はタスク開始時刻を使用する）
        task_key = str(task_uuid or f"{project_id}_{mr_iid}")
        if task_key in self.last_comment_check_time:
            last_check_time = self.last_comment_check_time[task_key]
        else:
            task_start_time: datetime | None = context.get_state("task_start_time")
            if task_start_time is not None:
                last_check_time = task_start_time
            else:
                # タスク開始時刻も未設定の場合は現在時刻を基準とする
                last_check_time = datetime.now(timezone.utc)

        # GitLab MR のコメント一覧を取得する
        try:
            all_notes = self.gitlab_client.get_merge_request_notes(
                project_id=project_id,
                mr_iid=mr_iid,
            )
        except Exception as exc:
            logger.warning(
                "CommentCheckMiddleware: コメント取得に失敗した: %s",
                exc,
            )
            return None

        # 最終チェック時刻以降のユーザーコメントをフィルタリングする（システムコメントは除外）
        # GitLab API は created_at を UTC で返すが、タイムゾーン情報が付与されない場合があるため
        # _ensure_aware() で UTC として扱い、比較可能な形式に統一する
        new_comments = [
            note
            for note in all_notes
            if not note.system
            and note.created_at is not None
            and _ensure_aware(note.created_at) > _ensure_aware(last_check_time)
        ]

        # 現在日時で最終チェック時刻を更新する
        self.last_comment_check_time[task_key] = datetime.now(timezone.utc)

        if not new_comments:
            return None

        # 新規コメントをコンテキストに保存してリダイレクトシグナルを返す
        logger.info(
            "CommentCheckMiddleware: 新規ユーザーコメント %d 件を検出した: node_id=%s",
            len(new_comments),
            node.node_id,
        )
        context.set_state("user_new_comments", new_comments)

        redirect_to: str | None = getattr(node.metadata, "comment_redirect_to", None)
        return MiddlewareSignal(
            action="redirect",
            redirect_to=redirect_to,
            reason="New user comments detected",
        )


def _ensure_aware(dt: datetime) -> datetime:
    """
    タイムゾーン情報を付与する

    タイムゾーン情報のない datetime に UTC を付与する。

    Args:
        dt: datetime オブジェクト

    Returns:
        タイムゾーン情報付き datetime
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
