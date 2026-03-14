"""
TaskHandlerモジュール

ConsumerからのタスクをTaskStrategyFactoryに委譲し、適切な処理戦略を選択・実行する。
Issue→MR変換の要否を判定し、ステータス管理を行う独立クラスとして実装する。

AUTOMATA_CODEX_SPEC.md § 2.2.2（Consumer: タスク処理・TaskHandler.handle() シーケンス図）に準拠する。
AUTOMATA_CODEX_SPEC.md § 2.3.1（TaskHandler コンポーネント一覧）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.3 Consumer（タスク処理コンポーネント）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.factories.task_strategy_factory import TaskStrategyFactory
    from consumer.factories.workflow_factory import WorkflowFactory
    from consumer.definitions.definition_loader import DefinitionLoader
    from shared.database.repositories.task_repository import TaskRepository
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class TaskHandler:
    """
    タスク処理ハンドラークラス

    ConsumerがRabbitMQから取得したタスクを受け取り、TaskStrategyFactoryに
    処理を委譲する独立クラス。Issue→MR変換要否を判定し、タスクステータスを
    管理する。

    AUTOMATA_CODEX_SPEC.md § 2.2.2 に準拠する。

    Attributes:
        task_strategy_factory: タスク処理戦略ファクトリ
        workflow_factory: ワークフロー生成クラス
        definition_loader: ワークフロー定義ロードクラス
        task_repository: タスクステータス更新用リポジトリ
    """

    def __init__(
        self,
        task_strategy_factory: TaskStrategyFactory,
        workflow_factory: WorkflowFactory | None = None,
        definition_loader: DefinitionLoader | None = None,
        task_repository: TaskRepository | None = None,
        issue_to_mr_converter: Any | None = None,
    ) -> None:
        """
        TaskHandlerを初期化する。

        Args:
            task_strategy_factory: TaskStrategyFactoryインスタンス
            workflow_factory: WorkflowFactoryインスタンス（MR処理用）
            definition_loader: DefinitionLoaderインスタンス（ワークフロー定義用）
            task_repository: TaskRepositoryインスタンス（ステータス更新用）
            issue_to_mr_converter: IssueToMRConverterインスタンス（変換戦略用）
        """
        self.task_strategy_factory = task_strategy_factory
        self.workflow_factory = workflow_factory
        self.definition_loader = definition_loader
        self.task_repository = task_repository
        self.issue_to_mr_converter = issue_to_mr_converter

    def _should_convert_issue_to_mr(self, task: Task) -> bool:
        """
        Issue→MR変換が必要かどうかを判定する。

        TaskStrategyFactoryのshould_convert_issue_to_mr()に処理を委譲する。

        Args:
            task: 判定対象のタスク

        Returns:
            変換が必要な場合はTrue、不要な場合はFalse
        """
        if task.task_type != "issue":
            return False

        return self.task_strategy_factory.should_convert_issue_to_mr(task)

    async def handle(self, task: Task) -> bool:
        """
        タスクを処理する。

        TaskStrategyFactoryに適切な処理戦略を生成させ、strategyのexecute()を呼び出す。

        AUTOMATA_CODEX_SPEC.md § 2.2.2 シーケンス図に準拠する。

        処理フロー:
        1. tasksテーブルにタスクを記録する（status=running）
        2. TaskStrategyFactory.create_strategy()で処理戦略を選択する
        3. strategy.execute(task)でタスクを実行する
        4. タスクステータスをcompleted/failedに更新する

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

        # 1. タスクをDBに記録する（重複の場合もstatusはrunning）
        if self.task_repository is not None:
            try:
                # タスク識別子を構築する
                if task.task_type == "issue" and task.issue_iid is not None:
                    task_identifier = f"{task.project_id}/issues/{task.issue_iid}"
                    task_db_type = "issue_to_mr"
                elif task.task_type == "merge_request" and task.mr_iid is not None:
                    task_identifier = f"{task.project_id}/merge_requests/{task.mr_iid}"
                    task_db_type = "mr_processing"
                else:
                    task_identifier = str(task.task_uuid)
                    task_db_type = task.task_type

                await self.task_repository.create_task(
                    uuid=task.task_uuid,
                    task_type=task_db_type,
                    task_identifier=task_identifier,
                    repository=str(task.project_id),
                    user_email=task.user_email or "",
                    status="running",
                )
                logger.info(
                    "タスクをDBに記録しました: task_uuid=%s", task.task_uuid
                )
            except Exception as exc:
                logger.warning(
                    "タスクのDB記録に失敗しました（処理は続行）: task_uuid=%s, error=%s",
                    task.task_uuid,
                    exc,
                )

        # 2. 処理戦略を選択する
        try:
            strategy = self.task_strategy_factory.create_strategy(
                task=task,
                workflow_factory=self.workflow_factory,
                definition_loader=self.definition_loader,
                task_repository=self.task_repository,
                issue_to_mr_converter=self.issue_to_mr_converter,
            )
        except ValueError as exc:
            logger.error(
                "タスク戦略の生成に失敗しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )
            await self._update_task_status(task.task_uuid, "failed")
            return False

        # 3. タスクを実行する
        try:
            await strategy.execute(task)
            logger.info(
                "タスク処理が完了しました: task_uuid=%s", task.task_uuid
            )
        except Exception as exc:
            logger.error(
                "タスク実行中にエラーが発生しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )
            await self._update_task_status(task.task_uuid, "failed")
            return False

        return True

    async def _update_task_status(self, task_uuid: str, status: str) -> None:
        """
        タスクのステータスをDBで更新する。

        Args:
            task_uuid: タスクのUUID
            status: 新しいステータス（'completed' / 'failed'）
        """
        if self.task_repository is None:
            return

        try:
            await self.task_repository.update_status(task_uuid, status)
            logger.info(
                "タスクステータスを更新しました: task_uuid=%s, status=%s",
                task_uuid,
                status,
            )
        except Exception as exc:
            logger.warning(
                "タスクステータスの更新に失敗しました: task_uuid=%s, status=%s, error=%s",
                task_uuid,
                status,
                exc,
            )
