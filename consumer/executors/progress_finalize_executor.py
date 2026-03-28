"""
ProgressFinalizeExecutor モジュール

ワークフローの最終ノードとして ProgressReporter.finalize() を呼び出す専用 Executor。
常にワークフロー末尾に自動挿入される。

CLASS_IMPLEMENTATION_SPEC.md § 3（Executor群）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_framework import Executor, WorkflowContext, handler

if TYPE_CHECKING:
    from consumer.tools.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class ProgressFinalizeExecutor(Executor):
    """
    ProgressReporter の finalize を担当する専用 Executor。

    ワークフローの最終ノードとして配置され、進捗コメントの最終更新を行う。
    progress_reporter が None の場合はパススルーのみを行う。

    Attributes:
        progress_reporter: 進捗報告インスタンス（None の場合はパススルーのみ）
    """

    def __init__(self, progress_reporter: Any = None) -> None:
        """
        初期化。

        Args:
            progress_reporter: 進捗報告インスタンス（省略可能）
        """
        super().__init__(id=self.__class__.__name__)
        self.progress_reporter = progress_reporter

    @handler(input=Any, output=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext[Any]) -> None:
        """
        ProgressReporter を finalize して後続ノードへメッセージを転送する。

        後続ノードへの伝播は ``await ctx.send_message(msg)`` で行う。

        Args:
            msg: 受け取るメッセージ
            ctx: ワークフローコンテキスト
        """
        if self.progress_reporter is not None:
            try:
                mr_iid: int | None = ctx.get_state("task_mr_iid")
                if mr_iid is not None:
                    await self.progress_reporter.finalize(
                        ctx, mr_iid, "ワークフロー処理が完了しました"
                    )
            except Exception:
                logger.exception(
                    "ProgressReporter の finalize 中にエラーが発生しました。"
                )
        await ctx.send_message(msg)
