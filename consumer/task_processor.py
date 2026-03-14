"""
TaskProcessorモジュール

ConsumerからのTaskをTaskHandlerに委譲してワークフローを構築・実行するクラス。
WorkflowFactoryとTaskStrategyFactoryを組み合わせてタスク処理フローを管理する。

AUTOMATA_CODEX_SPEC.md § 2.2.2（Consumer: タスク処理）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.3 Consumer（タスク処理コンポーネント）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.handlers.task_handler import TaskHandler
    from consumer.factories.workflow_factory import WorkflowFactory
    from shared.database.repositories.workflow_execution_state_repository import (
        WorkflowExecutionStateRepository,
    )
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class TaskProcessor:
    """
    タスク処理クラス

    ConsumerがRabbitMQから取得したタスクをTaskHandlerに委譲し、
    ワークフロー状態の管理と中断タスクの再開を担当する。

    AUTOMATA_CODEX_SPEC.md § 2.2.2（Consumer実装）に準拠する。

    Attributes:
        task_handler: タスク処理ハンドラー
        workflow_factory: ワークフロー生成クラス（状態保存・再開用）
        workflow_exec_state_repo: ワークフロー実行状態リポジトリ
    """

    def __init__(
        self,
        task_handler: TaskHandler,
        workflow_factory: WorkflowFactory | None = None,
        workflow_exec_state_repo: WorkflowExecutionStateRepository | None = None,
    ) -> None:
        """
        TaskProcessorを初期化する。

        Args:
            task_handler: TaskHandlerインスタンス
            workflow_factory: WorkflowFactoryインスタンス（状態管理用。Noneの場合は無効）
            workflow_exec_state_repo: ワークフロー実行状態リポジトリ（中断タスク再開用）
        """
        self.task_handler = task_handler
        self.workflow_factory = workflow_factory
        self.workflow_exec_state_repo = workflow_exec_state_repo

    async def process(self, task: Task) -> bool:
        """
        タスクを処理する。

        TaskHandlerのhandle()に処理を委譲し、結果を返す。

        処理フロー:
        1. TaskHandler.handle(task)を呼び出す
        2. 処理結果（成功/失敗）を返す

        Args:
            task: 処理対象のTaskオブジェクト

        Returns:
            処理成功時True、失敗時False
        """
        logger.info(
            "タスク処理を開始します: task_uuid=%s, task_type=%s",
            task.task_uuid,
            task.task_type,
        )

        try:
            result = await self.task_handler.handle(task)
            if result:
                logger.info(
                    "タスク処理が正常に完了しました: task_uuid=%s", task.task_uuid
                )
            else:
                logger.warning(
                    "タスク処理が失敗しました: task_uuid=%s", task.task_uuid
                )
            return result
        except Exception as exc:
            logger.error(
                "タスク処理中に予期しないエラーが発生しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )
            return False

    async def resume_suspended_tasks(self) -> int:
        """
        中断されたタスクを再開する。

        workflow_execution_statesテーブルに保存された中断タスクを取得し、
        WorkflowFactory.resume_workflow()で再開する。

        AUTOMATA_CODEX_SPEC.md § 13.4（ワークフロー停止・再開機構）に準拠する。

        Returns:
            再開したタスク数
        """
        if self.workflow_exec_state_repo is None or self.workflow_factory is None:
            logger.debug("ワークフロー実行状態リポジトリまたはファクトリが未設定のため再開をスキップします")
            return 0

        try:
            suspended = await self.workflow_exec_state_repo.list_suspended_executions()
        except Exception as exc:
            logger.error(
                "中断タスク一覧の取得に失敗しました: error=%s", exc
            )
            return 0

        if not suspended:
            logger.info("再開すべき中断タスクはありません")
            return 0

        logger.info("中断タスクを再開します: count=%d", len(suspended))
        resumed_count = 0

        for state in suspended:
            execution_id = state.get("execution_id")
            if execution_id is None:
                continue
            try:
                await self.workflow_factory.resume_workflow(execution_id)
                resumed_count += 1
                logger.info(
                    "中断タスクを再開しました: execution_id=%s", execution_id
                )
            except Exception as exc:
                logger.error(
                    "中断タスクの再開に失敗しました: execution_id=%s, error=%s",
                    execution_id,
                    exc,
                )

        logger.info(
            "中断タスク再開完了: resumed=%d, total=%d",
            resumed_count,
            len(suspended),
        )
        return resumed_count
