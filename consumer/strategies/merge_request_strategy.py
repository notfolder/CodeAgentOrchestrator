"""
MergeRequestStrategy モジュール

MR処理ワークフローをDefinitionLoaderで定義をロードし、WorkflowFactoryで
ワークフローを構築・実行する戦略クラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 2.10（MergeRequestStrategy）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from consumer.strategies.i_task_strategy import ITaskStrategy

if TYPE_CHECKING:
    from consumer.definitions.definition_loader import DefinitionLoader
    from consumer.factories.workflow_factory import WorkflowFactory
    from shared.models.task import Task, TaskContext

logger = logging.getLogger(__name__)


class MergeRequestStrategy(ITaskStrategy):
    """
    MR処理戦略クラス

    MR処理ワークフローをDefinitionLoaderで定義をロードし、WorkflowFactoryで
    ワークフローを構築・実行する。ConsumerがMRタスクを受信した際に使用される
    主要戦略クラス。

    CLASS_IMPLEMENTATION_SPEC.md § 2.10 に準拠する。

    Attributes:
        workflow_factory: ワークフロー生成クラス
        definition_loader: ワークフロー定義ロードクラス
        task_repository: タスクステータス更新用リポジトリ
    """

    def __init__(
        self,
        workflow_factory: WorkflowFactory,
        definition_loader: DefinitionLoader,
        task_repository: Any,
    ) -> None:
        """
        MergeRequestStrategyを初期化する。

        Args:
            workflow_factory: WorkflowFactoryインスタンス
            definition_loader: DefinitionLoaderインスタンス
            task_repository: TaskRepositoryインスタンス
        """
        self.workflow_factory = workflow_factory
        self.definition_loader = definition_loader
        self.task_repository = task_repository

    async def execute(self, task: Task) -> None:
        """
        MR処理ワークフローを構築・実行する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.10.3 に準拠する。

        処理フロー:
        1. タスクステータスをin_progressに更新
        2. ワークフロー定義ロード
        3. ワークフロー構築・実行
        4. タスクステータス更新（正常完了: completed、異常終了: failed）

        Args:
            task: 処理対象のタスク
        """
        logger.info(
            "MR処理を開始します: task_uuid=%s, mr_iid=%s",
            task.task_uuid,
            task.mr_iid,
        )

        # 1. タスクステータスをin_progressに更新（CLASS_IMPLEMENTATION_SPEC.md § 2.10.3 準拠）
        if self.task_repository is not None:
            await self.task_repository.update_task_status(task.task_uuid, "in_progress")
            logger.info(
                "タスクステータスをin_progressに更新しました: task_uuid=%s",
                task.task_uuid,
            )

        try:
            # 2-3. ワークフロー構築・実行
            await self._run_workflow(task)

            # 4. 正常完了時: タスクステータスをcompletedに更新
            if self.task_repository is not None:
                await self.task_repository.update_task_status(
                    task.task_uuid, "completed"
                )
                logger.info(
                    "タスクステータスをcompletedに更新しました: task_uuid=%s",
                    task.task_uuid,
                )

        except Exception as exc:
            logger.error(
                "MR処理中にエラーが発生しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
                exc_info=True,
            )
            # 4. 異常終了時: タスクステータスをfailedに更新
            if self.task_repository is not None:
                await self.task_repository.update_task_status(task.task_uuid, "failed")
                logger.info(
                    "タスクステータスをfailedに更新しました: task_uuid=%s",
                    task.task_uuid,
                )
            raise

    async def _resolve_username(self, task: Task) -> str:
        """
        タスクのusernameを解決する。MR authorがbotの場合はレビュアーのusernameを使用する。

        Args:
            task: 処理対象のタスク

        Returns:
            解決されたusername
        """
        username = task.username or ""

        if not self.workflow_factory:
            return username

        # bot_name設定を取得
        try:
            bot_name = self.workflow_factory.config_manager.get_gitlab_config().bot_name
        except Exception:
            return username

        if not bot_name or username.lower() != bot_name.lower():
            return username

        # MR IIDがない場合はそのまま返す
        if task.mr_iid is None:
            return username

        # GitLabからMRを取得し、レビュアーのusernameを使用する
        try:
            mr = self.workflow_factory.gitlab_client.get_merge_request(
                project_id=task.project_id,
                mr_iid=task.mr_iid,
            )
            if mr.reviewers:
                reviewer_username = mr.reviewers[0].username
                if reviewer_username:
                    logger.info(
                        "MR authorがbot(%s)のためレビュアーのusernameを使用します: %s",
                        bot_name,
                        reviewer_username,
                    )
                    return reviewer_username
            logger.warning(
                "MR authorがbotですがレビュアーが未設定または無効です: mr_iid=%s",
                task.mr_iid,
            )
        except Exception as exc:
            logger.warning(
                "MRレビュアーの解決に失敗しました: mr_iid=%s, error=%s",
                task.mr_iid,
                exc,
            )

        return username

    async def _run_workflow(self, task: Task) -> None:
        """
        ワークフローを構築して実行する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.10.3 ステップ2-3 に準拠する。

        処理フロー:
        1. usernameを解決（botの場合はレビュアーのusernameに切り替え）
        2. 解決されたusernameからuser_configを取得し、workflow_definition_idを事前設定
        3. ワークフローを構築・実行

        Args:
            task: 処理対象のタスク
        """
        if self.workflow_factory is None:
            logger.warning(
                "workflow_factoryが未設定のためワークフロー実行をスキップします: task_uuid=%s",
                task.task_uuid,
            )
            return

        # 1. usernameを解決（botの場合はレビュアーに切り替え）
        resolved_username = await self._resolve_username(task)

        # TaskContextを生成
        task_context = self._create_task_context(task)
        task_context.username = resolved_username

        # 2. user_configからworkflow_definition_idを事前取得
        if resolved_username and self.workflow_factory:
            try:
                user_config = (
                    await self.workflow_factory.user_config_client.get_user_config(
                        resolved_username
                    )
                )
                # user_configをキャッシュして下流の重複フェッチを防止する
                task_context.cached_user_config = user_config
                if user_config.workflow_definition_id:
                    task_context.workflow_definition_id = (
                        user_config.workflow_definition_id
                    )
                    logger.info(
                        "ユーザー設定からworkflow_definition_idを取得しました: username=%s, id=%s",
                        resolved_username,
                        user_config.workflow_definition_id,
                    )
            except Exception as exc:
                logger.warning(
                    "ユーザー設定の事前取得に失敗しました: username=%s, error=%s",
                    resolved_username,
                    exc,
                )

        # 3. ワークフローを構築
        workflow = await self.workflow_factory.create_workflow_from_definition(
            user_id=resolved_username,
            task_context=task_context,
        )

        # ワークフローを実行（コンテキスト付き）
        if hasattr(workflow, "run"):
            await workflow.run(task_context)
            logger.info(
                "ワークフローの実行が完了しました: task_uuid=%s",
                task.task_uuid,
            )

    def _create_task_context(self, task: Task) -> TaskContext:
        """
        TaskからTaskContextを生成する。

        Args:
            task: 処理対象のタスク

        Returns:
            TaskContextインスタンス
        """
        from shared.models.task import TaskContext

        return TaskContext(
            task_uuid=task.task_uuid,
            task_type=task.task_type,
            project_id=task.project_id,
            issue_iid=task.issue_iid,
            mr_iid=task.mr_iid,
            username=task.username,
        )
