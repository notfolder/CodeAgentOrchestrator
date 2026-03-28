"""
GitLab Webhookイベントハンドラーモジュール

GitLab Webhookから受信したイベントを解析し、処理対象かどうかを判定する。
Issue・MR・コメントの各Webhookペイロードを処理する。

AUTOMATA_CODEX_SPEC.md § 2.2.1（Producer: タスク検出＆キューイング）に準拠する。
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.config.models import GitLabConfig
    from shared.models.task import Task

logger = logging.getLogger(__name__)

# GitLab Webhookイベント種別
ISSUE_EVENT = "Issue Hook"
MR_EVENT = "Merge Request Hook"
NOTE_EVENT = "Note Hook"


class GitLabEventHandler:
    """
    GitLab Webhookイベントを処理するクラス

    GitLab WebhookからPOSTされたペイロードを解析し、処理対象タスクを
    生成する。Issue・MR・コメントの各イベント種別に対応する。

    処理対象判定ルール（AUTOMATA_CODEX_SPEC.md § 4.3 準拠）:
    - Issueイベント: bot_labelが付与されており、処理済みでないIssue
    - MRイベント: bot_labelが付与されており、処理済みでないMR
    - コメントイベント: 対象IssueまたはMRがbot_label付き

    Attributes:
        gitlab_config: GitLab設定（ラベル名等を含む）
    """

    def __init__(self, gitlab_config: GitLabConfig) -> None:
        """
        GitLabEventHandlerを初期化する。

        Args:
            gitlab_config: GitLab設定
        """
        self.gitlab_config = gitlab_config

    def _get_exclude_labels(self) -> set[str]:
        """
        除外ラベルセットを返す。

        Returns:
            除外ラベルの集合（processing/done/paused/stopped）
        """
        return {
            self.gitlab_config.processing_label,
            self.gitlab_config.done_label,
            self.gitlab_config.paused_label,
            self.gitlab_config.stopped_label,
        }

    def _is_processing_target(self, labels: list[str]) -> bool:
        """
        ラベルリストから処理対象かどうかを判定する。

        Args:
            labels: GitLabエンティティのラベルリスト

        Returns:
            処理対象の場合True
        """
        bot_label = self.gitlab_config.bot_label
        exclude_labels = self._get_exclude_labels()
        label_set = set(labels)

        if bot_label not in label_set:
            return False

        if label_set & exclude_labels:
            return False

        return True

    def handle_issue_event(self, payload: dict[str, Any]) -> Task | None:
        """
        IssueイベントのWebhookペイロードを処理する。

        ペイロードを解析してIssueラベルを確認し、処理対象であれば
        Taskオブジェクトを生成して返す。

        Args:
            payload: GitLab Webhookペイロード（Issue Hook）

        Returns:
            処理対象の場合はTaskオブジェクト、対象外の場合はNone
        """
        from shared.models.task import Task

        object_attributes = payload.get("object_attributes", {})
        action = object_attributes.get("action", "")

        # openまたはreopenイベントのみ処理する
        if action not in ("open", "reopen", "update"):
            logger.debug("処理対象外のIssueイベント: action=%s", action)
            return None

        labels_data = payload.get("labels", [])
        labels = [lbl.get("title", "") for lbl in labels_data]

        if not self._is_processing_target(labels):
            logger.debug(
                "処理対象外のIssue: labels=%s", labels
            )
            return None

        project_id = payload.get("project", {}).get("id")
        issue_iid = object_attributes.get("iid")
        username = payload.get("user", {}).get("username")

        if project_id is None or issue_iid is None:
            logger.warning(
                "IssueイベントペイロードにプロジェクトIDまたはIssue IIDが含まれていません"
            )
            return None

        task_uuid = str(uuid.uuid4())
        task = Task(
            task_uuid=task_uuid,
            task_type="issue",
            project_id=int(project_id),
            issue_iid=int(issue_iid),
            mr_iid=None,
            username=username,
        )
        logger.info(
            "IssueイベントからTaskを生成しました: task_uuid=%s, issue_iid=%d",
            task_uuid,
            int(issue_iid),
        )
        return task

    def handle_mr_event(self, payload: dict[str, Any]) -> Task | None:
        """
        MRイベントのWebhookペイロードを処理する。

        ペイロードを解析してMRラベルを確認し、処理対象であれば
        Taskオブジェクトを生成して返す。

        Args:
            payload: GitLab Webhookペイロード（Merge Request Hook）

        Returns:
            処理対象の場合はTaskオブジェクト、対象外の場合はNone
        """
        from shared.models.task import Task

        object_attributes = payload.get("object_attributes", {})
        action = object_attributes.get("action", "")

        # openまたはupdateイベントのみ処理する
        if action not in ("open", "reopen", "update"):
            logger.debug("処理対象外のMRイベント: action=%s", action)
            return None

        labels_data = payload.get("labels", [])
        labels = [lbl.get("title", "") for lbl in labels_data]

        if not self._is_processing_target(labels):
            logger.debug(
                "処理対象外のMR: labels=%s", labels
            )
            return None

        project_id = payload.get("project", {}).get("id")
        mr_iid = object_attributes.get("iid")
        username = payload.get("user", {}).get("username")

        if project_id is None or mr_iid is None:
            logger.warning(
                "MRイベントペイロードにプロジェクトIDまたはMR IIDが含まれていません"
            )
            return None

        task_uuid = str(uuid.uuid4())
        task = Task(
            task_uuid=task_uuid,
            task_type="merge_request",
            project_id=int(project_id),
            issue_iid=None,
            mr_iid=int(mr_iid),
            username=username,
        )
        logger.info(
            "MRイベントからTaskを生成しました: task_uuid=%s, mr_iid=%d",
            task_uuid,
            int(mr_iid),
        )
        return task

    def handle_note_event(self, payload: dict[str, Any]) -> Task | None:
        """
        コメント（Note）イベントのWebhookペイロードを処理する。

        コメントが付いたIssueまたはMRがbot_label付きの場合にTaskを生成する。
        コメント種別（issue / merge_request）に応じてタスク種別を設定する。

        Args:
            payload: GitLab Webhookペイロード（Note Hook）

        Returns:
            処理対象の場合はTaskオブジェクト、対象外の場合はNone
        """
        from shared.models.task import Task

        noteable_type = payload.get("object_attributes", {}).get("noteable_type", "")
        project_id = payload.get("project", {}).get("id")
        username = payload.get("user", {}).get("username")

        if project_id is None:
            logger.warning("NoteイベントペイロードにプロジェクトIDが含まれていません")
            return None

        if noteable_type == "Issue":
            issue_data = payload.get("issue", {})
            labels_data = issue_data.get("labels", [])
            labels = [lbl.get("title", "") for lbl in labels_data]

            if not self._is_processing_target(labels):
                return None

            issue_iid = issue_data.get("iid")
            if issue_iid is None:
                return None

            task_uuid = str(uuid.uuid4())
            task = Task(
                task_uuid=task_uuid,
                task_type="issue",
                project_id=int(project_id),
                issue_iid=int(issue_iid),
                mr_iid=None,
                username=username,
            )
            logger.info(
                "Noteイベント（Issue）からTaskを生成しました: task_uuid=%s, issue_iid=%d",
                task_uuid,
                int(issue_iid),
            )
            return task

        elif noteable_type == "MergeRequest":
            mr_data = payload.get("merge_request", {})
            labels_data = mr_data.get("labels", [])
            labels = [lbl.get("title", "") for lbl in labels_data]

            if not self._is_processing_target(labels):
                return None

            mr_iid = mr_data.get("iid")
            if mr_iid is None:
                return None

            task_uuid = str(uuid.uuid4())
            task = Task(
                task_uuid=task_uuid,
                task_type="merge_request",
                project_id=int(project_id),
                issue_iid=None,
                mr_iid=int(mr_iid),
                username=username,
            )
            logger.info(
                "Noteイベント（MR）からTaskを生成しました: task_uuid=%s, mr_iid=%d",
                task_uuid,
                int(mr_iid),
            )
            return task

        else:
            logger.debug("処理対象外のNoteイベント: noteable_type=%s", noteable_type)
            return None

    def handle_event(self, event_type: str, payload: dict[str, Any]) -> Task | None:
        """
        WebhookイベントのタイプとペイロードからTaskを生成する。

        イベント種別（X-Gitlab-Event ヘッダー値）に応じて適切なハンドラーに委譲する。

        Args:
            event_type: Webhookイベント種別（X-Gitlab-Event ヘッダー値）
            payload: GitLab Webhookペイロード

        Returns:
            処理対象の場合はTaskオブジェクト、対象外の場合はNone
        """
        logger.debug("Webhookイベントを処理します: event_type=%s", event_type)

        if event_type == ISSUE_EVENT:
            return self.handle_issue_event(payload)
        elif event_type == MR_EVENT:
            return self.handle_mr_event(payload)
        elif event_type == NOTE_EVENT:
            return self.handle_note_event(payload)
        else:
            logger.debug("未対応のイベント種別: event_type=%s", event_type)
            return None
