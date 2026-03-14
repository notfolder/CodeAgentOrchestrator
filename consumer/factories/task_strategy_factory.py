"""
TaskStrategyFactory モジュール

タスクの処理戦略を決定するファクトリクラスを提供する。
タスク種別に応じたITaskStrategyインスタンスを生成して返す。

CLASS_IMPLEMENTATION_SPEC.md § 2.5（TaskStrategyFactory）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.2.3（TaskStrategyFactory）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.strategies.i_task_strategy import ITaskStrategy
    from shared.config.config_manager import ConfigManager
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class TaskStrategyFactory:
    """
    タスク戦略ファクトリクラス

    タスクの処理戦略を決定する。タスク種別と設定に基づいて
    適切なITaskStrategyサブクラスのインスタンスを生成して返す。

    CLASS_IMPLEMENTATION_SPEC.md § 2.5 に準拠する。

    Attributes:
        gitlab_client: GitLab APIクライアント
        config_manager: 設定管理クラス
    """

    def __init__(
        self,
        gitlab_client: GitlabClient,
        config_manager: ConfigManager,
    ) -> None:
        """
        TaskStrategyFactoryを初期化する。

        Args:
            gitlab_client: GitLab APIクライアント
            config_manager: 設定管理クラス
        """
        self.gitlab_client = gitlab_client
        self.config_manager = config_manager

    def create_strategy(
        self,
        task: Task,
        workflow_factory: Any | None = None,
        definition_loader: Any | None = None,
        task_repository: Any | None = None,
        issue_to_mr_converter: Any | None = None,
    ) -> ITaskStrategy:
        """
        タスクに対する処理戦略を生成して返す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.5.3 に準拠する。

        処理フロー:
        1. task.task_typeを確認
        2. Issueタイプの場合: should_convert_issue_to_mr()でMR変換判定
           - Trueの場合: IssueToMRConversionStrategyを返す
           - Falseの場合: IssueOnlyStrategyを返す
        3. MergeRequestタイプの場合: MergeRequestStrategyを返す
        4. 不明なタイプの場合: ValueErrorをスロー

        Args:
            task: 処理対象タスク
            workflow_factory: WorkflowFactoryインスタンス（MergeRequestStrategy用）
            definition_loader: DefinitionLoaderインスタンス（MergeRequestStrategy用）
            task_repository: TaskRepositoryインスタンス（各戦略用）
            issue_to_mr_converter: IssueToMRConverterインスタンス（変換戦略用）

        Returns:
            タスクに対応するITaskStrategyインスタンス

        Raises:
            ValueError: 不明なタスクタイプが指定された場合
        """
        from consumer.strategies.issue_only_strategy import IssueOnlyStrategy
        from consumer.strategies.issue_to_mr_conversion_strategy import (
            IssueToMRConversionStrategy,
        )
        from consumer.strategies.merge_request_strategy import MergeRequestStrategy

        task_type = task.task_type
        logger.info(
            "タスク戦略を生成します: task_uuid=%s, task_type=%s",
            task.task_uuid,
            task_type,
        )

        if task_type == "issue":
            if self.should_convert_issue_to_mr(task):
                logger.info(
                    "IssueToMRConversionStrategyを選択しました: task_uuid=%s",
                    task.task_uuid,
                )
                return IssueToMRConversionStrategy(
                    issue_to_mr_converter=issue_to_mr_converter,
                    task_repository=task_repository,
                )
            else:
                logger.info(
                    "IssueOnlyStrategyを選択しました: task_uuid=%s",
                    task.task_uuid,
                )
                return IssueOnlyStrategy(
                    gitlab_client=self.gitlab_client,
                    config_manager=self.config_manager,
                    task_repository=task_repository,
                )
        elif task_type == "merge_request":
            logger.info(
                "MergeRequestStrategyを選択しました: task_uuid=%s",
                task.task_uuid,
            )
            return MergeRequestStrategy(
                workflow_factory=workflow_factory,
                definition_loader=definition_loader,
                task_repository=task_repository,
            )
        else:
            raise ValueError(
                f"不明なタスクタイプ: '{task_type}'。"
                "有効値: 'issue', 'merge_request'"
            )

    def should_convert_issue_to_mr(self, task: Task) -> bool:
        """
        Issue→MR変換が必要かどうかを判定する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.5.3 に準拠する。

        処理フロー:
        1. 設定確認: 自動変換が無効な場合はFalseを返す
        2. botラベル確認: Issueにbotラベルが付いているか確認
        3. 既存MR確認: 同一Issueに対応するMRが既に存在しないか確認
        4. 全条件満たす場合: Trueを返す

        Args:
            task: 判定対象のタスク

        Returns:
            変換が必要な場合はTrue、不要な場合はFalse
        """
        # 1. 設定確認
        issue_to_mr_config = self.config_manager.get_issue_to_mr_config()
        gitlab_config = self.config_manager.get_gitlab_config()

        if not gitlab_config.bot_label:
            logger.info(
                "botラベルが未設定のためIssue→MR変換をスキップします: task_uuid=%s",
                task.task_uuid,
            )
            return False

        # issue_iidがない場合はスキップ
        if task.issue_iid is None:
            logger.info(
                "issue_iidが未設定のためIssue→MR変換をスキップします: task_uuid=%s",
                task.task_uuid,
            )
            return False

        try:
            # 2. botラベル確認
            issue = self.gitlab_client.get_issue(
                project_id=task.project_id,
                issue_iid=task.issue_iid,
            )
            issue_labels = getattr(issue, "labels", []) or []
            if gitlab_config.bot_label not in issue_labels:
                logger.info(
                    "botラベルがIssueに付いていないためMR変換をスキップします: "
                    "task_uuid=%s, issue_iid=%s",
                    task.task_uuid,
                    task.issue_iid,
                )
                return False

            # 3. 既存MR確認
            source_branch = issue_to_mr_config.source_branch_template.format(
                prefix=issue_to_mr_config.branch_prefix,
                issue_iid=task.issue_iid,
            )
            existing_mrs = self.gitlab_client.list_merge_requests(
                project_id=task.project_id,
                source_branch=source_branch,
            )
            if existing_mrs:
                logger.info(
                    "既存のMRが存在するためMR変換をスキップします: "
                    "task_uuid=%s, source_branch=%s",
                    task.task_uuid,
                    source_branch,
                )
                return False

        except Exception as exc:
            logger.warning(
                "Issue→MR変換判定中にエラーが発生しました。変換をスキップします: "
                "task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )
            return False

        # 4. 全条件を満たす場合: Trueを返す
        return True
