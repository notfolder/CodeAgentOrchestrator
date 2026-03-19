"""
GitLabタスク取得モジュール

GitLab APIからIssueとMerge Requestを取得し、処理対象タスクをフィルタリングする。

AUTOMATA_CODEX_SPEC.md § 2.3.1（TaskGetterFromGitLab コンポーネント一覧）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.3 Producer（タスク検出コンポーネント）に準拠する。
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.config.models import GitLabConfig
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.gitlab import GitLabIssue, GitLabMergeRequest
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class TaskGetterFromGitLab:
    """
    GitLabからタスクを取得するクラス

    GitLab APIを使用して、処理対象のIssueとMerge Requestを取得し、
    タスクオブジェクトに変換してフィルタリングする。

    処理対象判定ルール（AUTOMATA_CODEX_SPEC.md § 4.3 準拠）:
    - bot_label（"coding agent"）が付与されている
    - processing_label（"coding agent processing"）が付与されていない
    - done_label（"coding agent done"）が付与されていない
    - paused_label（"coding agent paused"）が付与されていない
    - stopped_label（"coding agent stopped"）が付与されていない

    Attributes:
        gitlab_client: GitLab APIクライアント
        gitlab_config: GitLab設定
        project_id: 対象GitLabプロジェクトID（Noneの場合は全プロジェクト横断）
    """

    def __init__(
        self,
        gitlab_client: GitlabClient,
        gitlab_config: GitLabConfig,
        project_id: int | None,
    ) -> None:
        """
        TaskGetterFromGitLabを初期化する。

        Args:
            gitlab_client: GitLab APIクライアントインスタンス
            gitlab_config: GitLab設定（ラベル名等を含む）
            project_id: 対象GitLabプロジェクトID。Noneを指定すると
                        PATユーザーにアサインされた全プロジェクトを横断取得する。
        """
        self.gitlab_client = gitlab_client
        self.gitlab_config = gitlab_config
        self.project_id = project_id

    def _is_processing_target(self, labels: list[str]) -> bool:
        """
        ラベルリストから処理対象かどうかを判定する。

        bot_labelが付与されており、かつ除外ラベル（processing/done/paused/stopped）が
        付与されていない場合のみ処理対象とする。

        Args:
            labels: GitLabエンティティのラベルリスト

        Returns:
            処理対象の場合True、それ以外はFalse
        """
        bot_label = self.gitlab_config.bot_label
        exclude_labels = {
            self.gitlab_config.processing_label,
            self.gitlab_config.done_label,
            self.gitlab_config.paused_label,
            self.gitlab_config.stopped_label,
        }
        label_set = set(labels)

        if bot_label not in label_set:
            return False

        if label_set & exclude_labels:
            return False

        return True

    def get_unprocessed_issues(self) -> list[GitLabIssue]:
        """
        処理対象のIssue一覧を取得する。

        project_idがNoneの場合は全プロジェクト横断で取得する。
        bot_labelが付与された未処理のIssueをGitLab APIから取得し、
        除外ラベルが付いていないものをフィルタリングして返す。

        Returns:
            処理対象のGitLabIssueリスト
        """
        logger.info(
            "未処理Issue一覧を取得します: project_id=%s",
            self.project_id if self.project_id is not None else "全プロジェクト横断",
        )
        try:
            if self.project_id is None:
                # 全プロジェクト横断: PATユーザーにアサインされた全Issueを取得する
                issues = self.gitlab_client.list_all_assigned_issues(
                    labels=[self.gitlab_config.bot_label],
                    state="opened",
                )
            else:
                issues = self.gitlab_client.list_issues(
                    project_id=self.project_id,
                    labels=[self.gitlab_config.bot_label],
                    state="opened",
                )
        except Exception as exc:
            logger.error(
                "GitLab APIからのIssue取得に失敗しました: project_id=%s, error=%s",
                self.project_id,
                exc,
            )
            return []

        unprocessed = [
            issue for issue in issues if self._is_processing_target(issue.labels)
        ]
        logger.info(
            "未処理Issue: total=%d, unprocessed=%d",
            len(issues),
            len(unprocessed),
        )
        return unprocessed

    def get_unprocessed_merge_requests(self) -> list[GitLabMergeRequest]:
        """
        処理対象のMerge Request一覧を取得する。

        project_idがNoneの場合は全プロジェクト横断で取得する。
        bot_labelが付与された未処理のMRをGitLab APIから取得し、
        除外ラベルが付いていないものをフィルタリングして返す。

        Returns:
            処理対象のGitLabMergeRequestリスト
        """
        logger.info(
            "未処理MR一覧を取得します: project_id=%s",
            self.project_id if self.project_id is not None else "全プロジェクト横断",
        )
        try:
            if self.project_id is None:
                # 全プロジェクト横断: PATユーザーにアサインされた全MRを取得する
                mrs = self.gitlab_client.list_all_assigned_merge_requests(
                    labels=[self.gitlab_config.bot_label],
                    state="opened",
                )
            else:
                mrs = self.gitlab_client.list_merge_requests(
                    project_id=self.project_id,
                    labels=[self.gitlab_config.bot_label],
                    state="opened",
                )
        except Exception as exc:
            logger.error(
                "GitLab APIからのMR取得に失敗しました: project_id=%s, error=%s",
                self.project_id,
                exc,
            )
            return []

        unprocessed = [mr for mr in mrs if self._is_processing_target(mr.labels)]
        logger.info(
            "未処理MR: total=%d, unprocessed=%d",
            len(mrs),
            len(unprocessed),
        )
        return unprocessed

    def issue_to_task(self, issue: GitLabIssue, user_email: str | None = None) -> Task:
        """
        GitLabIssueをTaskオブジェクトに変換する。

        Args:
            issue: 変換対象のGitLabIssue
            user_email: タスク実行ユーザーのメールアドレス

        Returns:
            Taskオブジェクト
        """
        from shared.models.task import Task

        task_uuid = str(uuid.uuid4())
        # 全プロジェクト横断モード（project_id=None）の場合は issue 自身の project_id を使う
        resolved_project_id = (
            self.project_id if self.project_id is not None else issue.project_id
        )
        return Task(
            task_uuid=task_uuid,
            task_type="issue",
            project_id=resolved_project_id,
            issue_iid=issue.iid,
            mr_iid=None,
            user_email=user_email,
        )

    def mr_to_task(self, mr: GitLabMergeRequest, user_email: str | None = None) -> Task:
        """
        GitLabMergeRequestをTaskオブジェクトに変換する。

        Args:
            mr: 変換対象のGitLabMergeRequest
            user_email: タスク実行ユーザーのメールアドレス

        Returns:
            Taskオブジェクト
        """
        from shared.models.task import Task

        task_uuid = str(uuid.uuid4())
        # 全プロジェクト横断モード（project_id=None）の場合は mr 自身の project_id を使う
        resolved_project_id = (
            self.project_id if self.project_id is not None else mr.project_id
        )
        return Task(
            task_uuid=task_uuid,
            task_type="merge_request",
            project_id=resolved_project_id,
            issue_iid=None,
            mr_iid=mr.iid,
            user_email=user_email,
        )

    def get_all_unprocessed_tasks(self, user_email: str | None = None) -> list[Task]:
        """
        すべての未処理タスク（Issue・MR）を取得してTaskリストに変換する。

        Args:
            user_email: タスク実行ユーザーのメールアドレス

        Returns:
            未処理タスクのTaskリスト（Issue→MR順）
        """
        tasks: list[Task] = []

        # Issue取得（author.email を優先して user_email として使用する）
        issues = self.get_unprocessed_issues()
        for issue in issues:
            issue_user_email = (
                issue.author.email
                if issue.author and issue.author.email
                else user_email
            )
            tasks.append(self.issue_to_task(issue, user_email=issue_user_email))

        # MR取得（author.email を優先して user_email として使用する）
        mrs = self.get_unprocessed_merge_requests()
        for mr in mrs:
            mr_user_email = (
                mr.author.email if mr.author and mr.author.email else user_email
            )
            tasks.append(self.mr_to_task(mr, user_email=mr_user_email))

        logger.info(
            "未処理タスク合計: issues=%d, mrs=%d, total=%d",
            len(issues),
            len(mrs),
            len(tasks),
        )
        return tasks
