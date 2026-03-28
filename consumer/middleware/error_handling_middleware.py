"""
ErrorHandlingMiddleware モジュール

ノード実行時のエラーを統一的にハンドリングする Middleware を定義する。
エラーを分類してリトライ判定を行い、リトライ上限超過時はユーザーに通知する。

CLASS_IMPLEMENTATION_SPEC.md § 5.4（ErrorHandlingMiddleware）に準拠する。
"""

from __future__ import annotations

import asyncio
import errno
import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from consumer.middleware.i_middleware import IMiddleware, MiddlewareSignal, WorkflowNode
from consumer.middleware.metrics_collector import MetricsCollector

if TYPE_CHECKING:
    from agent_framework import WorkflowContext
    from consumer.providers.context_storage_manager import ContextStorageManager
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)

# エラーカテゴリ定数
_CATEGORY_TRANSIENT = "transient"
_CATEGORY_CONFIGURATION = "configuration"
_CATEGORY_IMPLEMENTATION = "implementation"
_CATEGORY_RESOURCE = "resource"

# エラーメッセージのキーワードマッチング定数
# transientエラーに対応するキーワード
_TRANSIENT_KEYWORDS: tuple[str, ...] = ("5xx", "503", "502", "504", "timeout", "rate limit")
# configurationエラーに対応するキーワード
_CONFIGURATION_KEYWORDS: tuple[str, ...] = ("authentication", "config", "unauthorized", "forbidden")


@dataclass
class RetryPolicy:
    """
    リトライポリシー

    エラー発生時のリトライ動作を定義するデータクラス。

    Attributes:
        max_attempts: 最大リトライ回数（デフォルト 3）
        base_delay: 基本遅延秒数（指数バックオフの基準値、デフォルト 1.0）
    """

    max_attempts: int = field(default=3)
    base_delay: float = field(default=1.0)


class ErrorHandlingMiddleware(IMiddleware):
    """
    エラーハンドリング Middleware

    ノード実行時のエラーを統一的にハンドリングする。
    エラーを transient / configuration / implementation / resource に分類し、
    transient エラーは指数バックオフでリトライする。
    リトライ上限超過または非 transient エラーの場合は、
    データベースにエラーを記録してユーザーに通知し、ワークフローを中断する。

    Attributes:
        context_storage_manager: コンテキストストレージマネージャー
        gitlab_client: GitLab API クライアント
        metrics_collector: メトリクスコレクター
        retry_policy: リトライポリシー
    """

    def __init__(
        self,
        context_storage_manager: ContextStorageManager,
        gitlab_client: GitlabClient,
        metrics_collector: MetricsCollector,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """
        初期化

        Args:
            context_storage_manager: コンテキストストレージマネージャー
            gitlab_client: GitLab API クライアント
            metrics_collector: メトリクスコレクター
            retry_policy: リトライポリシー（None の場合はデフォルト値を使用する）
        """
        self.context_storage_manager = context_storage_manager
        self.gitlab_client = gitlab_client
        self.metrics_collector = metrics_collector
        self.retry_policy = retry_policy if retry_policy is not None else RetryPolicy()

    async def intercept(
        self,
        phase: str,
        node: WorkflowNode,
        context: WorkflowContext,
        **kwargs: Any,
    ) -> Optional[MiddlewareSignal]:
        """
        エラーハンドリング介入処理

        on_error フェーズでのみ動作する。
        例外を分類してリトライ判定を行い、リトライ上限超過時は
        ユーザー通知とワークフロー中断を行う。

        Args:
            phase: 実行フェーズ
            node: 実行対象ノード情報
            context: ワークフローコンテキスト
            **kwargs: 追加引数（exception: 発生した例外を含む）

        Returns:
            MiddlewareSignal: リトライ上限超過または非 transient エラーの場合（action="abort"）
            None: transient エラーでリトライを実行する場合
        """
        # on_error フェーズ以外はスキップする
        if phase != "on_error":
            return None

        exception: BaseException | None = kwargs.get("exception")
        if exception is None:
            logger.warning(
                "ErrorHandlingMiddleware: on_error フェーズで exception が未設定: node_id=%s",
                node.node_id,
            )
            return None

        # エラーを分類する
        category = _classify_error(exception)
        exception_msg = str(exception)

        logger.info(
            "ErrorHandlingMiddleware: エラーを検出した: node_id=%s, category=%s, error=%s",
            node.node_id,
            category,
            exception_msg,
        )

        # transient エラーはリトライを試みる
        if category == _CATEGORY_TRANSIENT:
            retry_count: int = context.get_state("retry_count") or 0

            if retry_count < self.retry_policy.max_attempts:
                retry_count += 1
                context.set_state("retry_count", retry_count)

                # 指数バックオフ + ジッター で遅延する
                jitter = random.uniform(0.0, 0.1)  # noqa: S311
                delay = self.retry_policy.base_delay * (2 ** retry_count) + jitter

                logger.info(
                    "ErrorHandlingMiddleware: transient エラーのためリトライする: "
                    "node_id=%s, retry_count=%d/%d, delay=%.2fs",
                    node.node_id,
                    retry_count,
                    self.retry_policy.max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
                # None を返してノードを再実行する
                return None

        # リトライ上限超過または非 transient エラー: エラー処理を実施してワークフローを中断する
        await self._handle_fatal_error(
            context=context,
            node=node,
            category=category,
            exception=exception,
            exception_msg=exception_msg,
        )

        return MiddlewareSignal(
            action="abort",
            reason=f"Error: {exception_msg}, Retries exhausted",
        )

    async def _handle_fatal_error(
        self,
        context: WorkflowContext,
        node: WorkflowNode,
        category: str,
        exception: BaseException,
        exception_msg: str,
    ) -> None:
        """
        致命的エラーの処理を行う

        データベースへのエラー記録、GitLab MR へのコメント投稿、
        メトリクス送信、コンテキストのステータス更新を行う。

        Args:
            context: ワークフローコンテキスト
            node: 実行対象ノード情報
            category: エラーカテゴリ
            exception: 発生した例外
            exception_msg: エラーメッセージ文字列
        """
        import traceback

        # コンテキストからタスク識別情報を取得する
        task_uuid: str | None = context.get_state("task_uuid")
        project_id: int | None = context.get_state("project_id")
        mr_iid: int | None = context.get_state("mr_iid")

        # データベースにエラーを記録する（メソッドが存在する場合のみ）
        if hasattr(self.context_storage_manager, "save_error"):
            try:
                stack_trace = traceback.format_exc()
                await self.context_storage_manager.save_error(
                    task_uuid=task_uuid or "",
                    node_id=node.node_id,
                    error_category=category,
                    error_message=exception_msg,
                    stack_trace=stack_trace,
                )
            except Exception as save_exc:
                logger.warning(
                    "ErrorHandlingMiddleware: エラーのDB保存に失敗した: %s",
                    save_exc,
                )

        # GitLab MR にエラーコメントを投稿する
        if project_id is not None and mr_iid is not None:
            try:
                comment_body = (
                    f"⚠️ ワークフローエラーが発生しました\n\n"
                    f"- **ノード**: `{node.node_id}`\n"
                    f"- **カテゴリ**: `{category}`\n"
                    f"- **エラー**: {exception_msg}"
                )
                self.gitlab_client.create_merge_request_note(
                    project_id=project_id,
                    mr_iid=mr_iid,
                    body=comment_body,
                )
            except Exception as comment_exc:
                logger.warning(
                    "ErrorHandlingMiddleware: GitLab コメント投稿に失敗した: %s",
                    comment_exc,
                )

        # メトリクスを送信する
        self.metrics_collector.send_metric(
            metric_name="workflow_errors_total",
            labels={
                "error_category": category,
                "node_id": node.node_id,
            },
        )

        # コンテキストのステータスを failed に更新する
        context.set_state("status", "failed")


def _classify_error(exception: BaseException) -> str:
    """
    例外を分類する

    例外の型とメッセージに基づいてエラーカテゴリを判定する。

    Args:
        exception: 分類対象の例外

    Returns:
        エラーカテゴリ文字列
        ("transient" / "configuration" / "implementation" / "resource")
    """
    exception_msg = str(exception).lower()

    # resource エラーの判定
    if isinstance(exception, MemoryError):
        return _CATEGORY_RESOURCE
    if isinstance(exception, OSError) and exception.errno in (
        errno.ENOSPC,  # ディスク不足
        errno.EDQUOT,  # クォータ超過
        errno.ENOMEM,  # メモリ不足
    ):
        return _CATEGORY_RESOURCE

    # transient エラーの判定
    if isinstance(exception, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
        return _CATEGORY_TRANSIENT
    if any(keyword in exception_msg for keyword in _TRANSIENT_KEYWORDS):
        return _CATEGORY_TRANSIENT

    # configuration エラーの判定
    if isinstance(exception, PermissionError):
        return _CATEGORY_CONFIGURATION
    if any(keyword in exception_msg for keyword in _CONFIGURATION_KEYWORDS):
        return _CATEGORY_CONFIGURATION

    # implementation エラーの判定（バグ・未実装）
    if isinstance(exception, (ValueError, TypeError, AttributeError, NotImplementedError)):
        return _CATEGORY_IMPLEMENTATION

    # その他はすべて implementation として扱う
    return _CATEGORY_IMPLEMENTATION
