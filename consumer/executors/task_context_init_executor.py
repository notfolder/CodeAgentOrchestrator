"""
TaskContextInitExecutor モジュール

TaskContext の値をワークフローコンテキスト（WorkflowContext）に転写する
軽量 Executor を定義する。

ユーザー解決・user_config 取得は MergeRequestStrategy 側で完了済みのため、
本 Executor はキャッシュ済みの値をコンテキストにコピーするだけである。

CLASS_IMPLEMENTATION_SPEC.md § 3.2（TaskContextInitExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import WorkflowContext, handler

from consumer.executors.base_executor import BaseExecutor

logger = logging.getLogger(__name__)


class TaskContextInitExecutor(BaseExecutor):
    """
    タスクコンテキスト初期化 Executor

    TaskContext に格納されたユーザー情報・タスク情報を
    WorkflowContext の state に転写する。

    MergeRequestStrategy が事前にユーザー解決（bot→reviewer 切り替え）と
    user_config 取得・キャッシュを完了しているため、本 Executor は
    外部 API 呼び出しを行わず、値のコピーのみを担当する。
    """

    def __init__(self) -> None:
        """TaskContextInitExecutor を初期化する。"""
        super().__init__(id=self.__class__.__name__)

    @handler(input=Any, output=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext[Any]) -> None:
        """
        TaskContext の値を WorkflowContext に転写する。

        処理フロー:
        1. TaskContext から username, cached_user_config, project_id, mr_iid, issue_iid を取得
        2. WorkflowContext の state にコピー
        3. 下流ノードが参照する task_identifier を構築して保存

        Args:
            msg: ワークフロー初期メッセージ（TaskContext）
            ctx: ワークフローコンテキスト
        """
        # TaskContext からフィールドを取得する
        task_uuid: str = getattr(msg, "task_uuid", None) or ""
        username: str = getattr(msg, "username", None) or ""
        user_config: Any = getattr(msg, "cached_user_config", None)
        project_id: int = getattr(msg, "project_id", 0)
        mr_iid: int = getattr(msg, "mr_iid", 0) or 0
        issue_iid: int | None = getattr(msg, "issue_iid", None)

        logger.info(
            "TaskContextをワークフローコンテキストに転写します: "
            "task_uuid=%s, username=%s, project_id=%s, mr_iid=%s",
            task_uuid,
            username,
            project_id,
            mr_iid,
        )

        # WorkflowContext state にコピーする
        self.set_context_value(ctx, "task_uuid", task_uuid)
        self.set_context_value(ctx, "username", username)
        self.set_context_value(ctx, "user_config", user_config)
        self.set_context_value(ctx, "task_mr_iid", mr_iid)
        self.set_context_value(ctx, "task_issue_iid", issue_iid)
        self.set_context_value(ctx, "project_id", project_id)
        self.set_context_value(
            ctx,
            "task_identifier",
            {"project_id": project_id, "mr_iid": mr_iid},
        )

        logger.info("TaskContext転写が完了しました: username=%s", username)
        # 後続ノードへ msg を送信する
        await ctx.send_message(msg)
