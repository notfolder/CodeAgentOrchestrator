"""
ExecutorFactory モジュール

タスク処理に必要なExecutorインスタンスを生成するファクトリクラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 2.2（ExecutorFactory）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.2.2（ExecutorFactory）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.executors.branch_merge_executor import BranchMergeExecutor
    from consumer.executors.content_transfer_executor import ContentTransferExecutor
    from consumer.executors.plan_env_setup_executor import PlanEnvSetupExecutor
    from consumer.executors.task_context_init_executor import TaskContextInitExecutor
    from consumer.user_config_client import UserConfigClient
    from shared.config.config_manager import ConfigManager
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)


class ExecutorFactory:
    """
    Executorファクトリクラス

    タスク処理に必要なExecutorインスタンスを生成する。
    各Executorに適切な依存オブジェクトを注入してインスタンスを返す。

    CLASS_IMPLEMENTATION_SPEC.md § 2.2 に準拠する。

    Attributes:
        user_config_client: ユーザー設定クライアント
        gitlab_client: GitLab APIクライアント
        env_manager: 実行環境マネージャー
        config_manager: 設定管理クラス
    """

    def __init__(
        self,
        user_config_client: UserConfigClient,
        gitlab_client: GitlabClient,
        env_manager: Any,
        config_manager: ConfigManager | None = None,
    ) -> None:
        """
        ExecutorFactoryを初期化する。

        Args:
            user_config_client: ユーザー設定クライアント
            gitlab_client: GitLab APIクライアント
            env_manager: 実行環境マネージャー（ExecutionEnvironmentManager）
            config_manager: 設定管理クラス
        """
        self.user_config_client = user_config_client
        self.gitlab_client = gitlab_client
        self.env_manager = env_manager
        self.config_manager = config_manager

    def create_task_context_init(self) -> TaskContextInitExecutor:
        """
        TaskContextInitExecutorインスタンスを生成して返す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.2.3 に準拠する。

        処理フロー:
        1. TaskContextInitExecutorインスタンスを生成
        2. 返却

        Returns:
            TaskContextInitExecutorインスタンス
        """
        from consumer.executors.task_context_init_executor import (
            TaskContextInitExecutor,
        )

        return TaskContextInitExecutor()

    def create_content_transfer(self) -> ContentTransferExecutor:
        """
        ContentTransferExecutorインスタンスを生成して返す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.2.3 に準拠する。

        処理フロー:
        1. ContentTransferExecutorインスタンスを生成
        2. gitlab_clientを渡す
        3. 返却

        Returns:
            ContentTransferExecutorインスタンス
        """
        from consumer.executors.content_transfer_executor import ContentTransferExecutor

        return ContentTransferExecutor(gitlab_client=self.gitlab_client)

    def create_plan_env_setup(self) -> PlanEnvSetupExecutor:
        """
        PlanEnvSetupExecutorインスタンスを生成して返す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.2.3 に準拠する。

        処理フロー:
        1. PlanEnvSetupExecutorインスタンスを生成
        2. env_managerとconfig辞書を渡す
        3. 返却

        Returns:
            PlanEnvSetupExecutorインスタンス
        """
        from consumer.executors.plan_env_setup_executor import PlanEnvSetupExecutor

        # config_managerから設定辞書を構築する
        config: dict[str, Any] = {}
        if self.config_manager is not None:
            try:
                exec_env_config = self.config_manager.get_execution_environment_config()
                config["plan_environment_name"] = (
                    getattr(getattr(exec_env_config, "docker", None), "image", "python")
                    or "python"
                )
            except Exception:
                config["plan_environment_name"] = "python"

        return PlanEnvSetupExecutor(
            env_manager=self.env_manager,
            config=config,
        )

    def create_branch_merge(self, context: Any | None = None) -> BranchMergeExecutor:
        """
        BranchMergeExecutorインスタンスを生成して返す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.2.3 に準拠する。

        処理フロー:
        1. ワークフローコンテキストからbranch_envsとselected_implementationを取得
        2. BranchMergeExecutorインスタンスを生成し、gitlab_clientを渡す
        3. 返却

        Args:
            context: ワークフローコンテキスト（省略可能）

        Returns:
            BranchMergeExecutorインスタンス
        """
        from consumer.executors.branch_merge_executor import BranchMergeExecutor

        return BranchMergeExecutor(gitlab_client=self.gitlab_client)

    def create_executor_by_class_name(self, class_name: str) -> Any:
        """
        クラス名からExecutorインスタンスを生成して返す。

        グラフ定義のexecutor_classフィールドを元にExecutorを動的生成する。

        Args:
            class_name: Executorクラス名
                （"TaskContextInitExecutor"/"ContentTransferExecutor"/
                  "PlanEnvSetupExecutor"/"ExecEnvSetupExecutor"/"BranchMergeExecutor"）

        Returns:
            該当するExecutorインスタンス

        Raises:
            ValueError: 不明なクラス名が指定された場合
        """
        creator_map = {
            "TaskContextInitExecutor": self.create_task_context_init,
            "ContentTransferExecutor": self.create_content_transfer,
            "PlanEnvSetupExecutor": self.create_plan_env_setup,
            "BranchMergeExecutor": self.create_branch_merge,
        }

        if class_name == "ExecEnvSetupExecutor":
            from consumer.executors.exec_env_setup_executor import ExecEnvSetupExecutor

            return ExecEnvSetupExecutor(
                node_id="exec_env_setup",
                env_manager=self.env_manager,
                gitlab_client=self.gitlab_client,
                graph_definition={},
            )

        if class_name not in creator_map:
            raise ValueError(
                f"不明なExecutorクラス名: '{class_name}'。"
                f"有効値: {list(creator_map.keys()) + ['ExecEnvSetupExecutor']}"
            )

        return creator_map[class_name]()
