"""
IssueOnlyStrategy モジュール

Issue→MR変換が不要な場合に、MRを作成せずIssue上で処理を完結させる
戦略クラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 2.9（IssueOnlyStrategy）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from consumer.strategies.i_task_strategy import ITaskStrategy

if TYPE_CHECKING:
    from shared.config.config_manager import ConfigManager
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class IssueOnlyStrategy(ITaskStrategy):
    """
    Issueのみ処理戦略クラス

    Issue→MR変換が不要な場合（変換設定無効・変換条件不成立など）に、
    MRを作成せずIssue上で処理を完結させる。処理済みラベルを付与し、
    Issueにコメントを投稿してタスクを完了する。

    CLASS_IMPLEMENTATION_SPEC.md § 2.9 に準拠する。

    Attributes:
        gitlab_client: GitLab API操作クライアント
        config_manager: 設定管理（doneラベル名の取得に使用）
        task_repository: タスクステータス更新用リポジトリ
    """

    def __init__(
        self,
        gitlab_client: GitlabClient,
        config_manager: ConfigManager,
        task_repository: Any,
    ) -> None:
        """
        IssueOnlyStrategyを初期化する。

        Args:
            gitlab_client: GitLab APIクライアント
            config_manager: 設定管理クラス
            task_repository: TaskRepositoryインスタンス
        """
        self.gitlab_client = gitlab_client
        self.config_manager = config_manager
        self.task_repository = task_repository

    async def execute(self, task: Task) -> None:
        """
        Issueのみ処理を実行し、タスクを完了する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.9.3 に準拠する。

        処理フロー:
        1. gitlab_client.get_issue()でIssue情報を取得
        2. gitlab_client.add_label()で処理済みラベルを付与
        3. gitlab_client.create_issue_comment()で完了コメントを投稿
        4. task_repository.update_task_status()でステータスをcompletedに更新

        Args:
            task: 処理対象のタスク
        """
        logger.info(
            "Issueのみ処理を開始します: task_uuid=%s, issue_iid=%s",
            task.task_uuid,
            task.issue_iid,
        )

        if task.issue_iid is None:
            logger.warning(
                "issue_iidが未設定のため処理をスキップします: task_uuid=%s",
                task.task_uuid,
            )
            return

        # GitLabの設定を取得
        gitlab_config = self.config_manager.get_gitlab_config()
        done_label = gitlab_config.done_label

        # 1. Issue情報取得
        try:
            issue = self.gitlab_client.get_issue(
                project_id=task.project_id,
                issue_iid=task.issue_iid,
            )
            logger.debug(
                "Issue情報を取得しました: project_id=%s, issue_iid=%s",
                task.project_id,
                task.issue_iid,
            )
        except Exception as exc:
            logger.error(
                "Issue情報の取得に失敗しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )
            raise

        # 2. 処理済みラベル付与
        try:
            self.gitlab_client.add_label(
                project_id=task.project_id,
                issue_iid=task.issue_iid,
                label=done_label,
            )
            logger.info(
                "処理済みラベルを付与しました: issue_iid=%s, label=%s",
                task.issue_iid,
                done_label,
            )
        except Exception as exc:
            logger.warning(
                "処理済みラベルの付与に失敗しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )

        # 3. 完了コメント投稿
        comment_body = (
            "このIssueはMRへの変換を行わずに処理を完了しました。"
        )
        try:
            self.gitlab_client.create_issue_comment(
                project_id=task.project_id,
                issue_iid=task.issue_iid,
                comment=comment_body,
            )
            logger.info(
                "完了コメントを投稿しました: issue_iid=%s",
                task.issue_iid,
            )
        except Exception as exc:
            logger.warning(
                "完了コメントの投稿に失敗しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )

        # 4. タスクステータスを完了に更新
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
