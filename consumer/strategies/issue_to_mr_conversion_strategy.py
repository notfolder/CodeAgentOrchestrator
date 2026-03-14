"""
IssueToMRConversionStrategy モジュール

IssueをGitLab MRに変換した後、タスクステータスをcompletedに更新して
処理を完了する戦略クラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 2.8（IssueToMRConversionStrategy）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from consumer.strategies.i_task_strategy import ITaskStrategy

if TYPE_CHECKING:
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class IssueToMRConversionStrategy(ITaskStrategy):
    """
    Issue→MR変換戦略クラス

    IssueをGitLab MRに変換した後、タスクステータスをcompletedに更新して
    処理を完了する。作成されたMRはProducerが次回ポーリング時に検出し、
    MR処理ワークフローとして独立して処理される。

    CLASS_IMPLEMENTATION_SPEC.md § 2.8 に準拠する。

    Attributes:
        issue_to_mr_converter: Issue→MR変換クラスのインスタンス
        task_repository: タスクステータス更新用リポジトリ
    """

    def __init__(
        self,
        issue_to_mr_converter: Any,
        task_repository: Any,
    ) -> None:
        """
        IssueToMRConversionStrategyを初期化する。

        Args:
            issue_to_mr_converter: IssueToMRConverterインスタンス
            task_repository: TaskRepositoryインスタンス
        """
        self.issue_to_mr_converter = issue_to_mr_converter
        self.task_repository = task_repository

    async def execute(self, task: Task) -> None:
        """
        Issue→MR変換を実行し、タスクステータスを更新する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.8.3 に準拠する。

        処理フロー:
        1. issue_to_mr_converter.convert(task)を呼び出し、Issue情報を取得して
           ブランチ・空コミット・MRを作成する
        2. task_repository.update_status(task.task_uuid, "completed")を呼び出す
           （作成されたMRはProducerが次回ポーリング時に検出し、
           MergeRequestStrategyとして独立して処理される）

        Args:
            task: 処理対象のタスク
        """
        logger.info(
            "Issue→MR変換を開始します: task_uuid=%s, issue_iid=%s",
            task.task_uuid,
            task.issue_iid,
        )

        # 1. Issue→MR変換実行
        if self.issue_to_mr_converter is not None:
            import asyncio
            import inspect

            if inspect.iscoroutinefunction(self.issue_to_mr_converter.convert):
                await self.issue_to_mr_converter.convert(task)
            else:
                await asyncio.to_thread(self.issue_to_mr_converter.convert, task)
            logger.info(
                "Issue→MR変換が完了しました: task_uuid=%s",
                task.task_uuid,
            )
        else:
            logger.warning(
                "issue_to_mr_converterが未設定のため変換をスキップします: task_uuid=%s",
                task.task_uuid,
            )

        # 2. タスクステータスを完了に更新
        if self.task_repository is not None:
            await self.task_repository.update_task_status(task.task_uuid, "completed")
            logger.info(
                "タスクステータスをcompletedに更新しました: task_uuid=%s",
                task.task_uuid,
            )
        else:
            logger.warning(
                "task_repositoryが未設定のためステータス更新をスキップします: task_uuid=%s",
                task.task_uuid,
            )

