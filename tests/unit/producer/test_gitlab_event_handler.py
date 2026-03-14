"""
GitLabEventHandlerの単体テスト

Issue・MR・コメントの各Webhookペイロードを用いて処理対象判定ロジックと
重複タスク検出を検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from producer.gitlab_event_handler import (
    ISSUE_EVENT,
    MR_EVENT,
    NOTE_EVENT,
    GitLabEventHandler,
)
from shared.config.models import GitLabConfig


@pytest.fixture
def gitlab_config() -> GitLabConfig:
    """テスト用GitLabConfigを返す"""
    return GitLabConfig(
        bot_label="coding agent",
        processing_label="coding agent processing",
        done_label="coding agent done",
        paused_label="coding agent paused",
        stopped_label="coding agent stopped",
    )


@pytest.fixture
def handler(gitlab_config: GitLabConfig) -> GitLabEventHandler:
    """テスト用GitLabEventHandlerインスタンスを返す"""
    return GitLabEventHandler(gitlab_config=gitlab_config)


def _make_issue_payload(
    iid: int,
    project_id: int,
    labels: list[str],
    action: str = "open",
) -> dict:
    """テスト用IssueイベントWebhookペイロードを生成する"""
    return {
        "object_attributes": {"iid": iid, "action": action},
        "project": {"id": project_id},
        "labels": [{"title": lbl} for lbl in labels],
        "user": {"email": "user@example.com"},
    }


def _make_mr_payload(
    iid: int,
    project_id: int,
    labels: list[str],
    action: str = "open",
) -> dict:
    """テスト用MRイベントWebhookペイロードを生成する"""
    return {
        "object_attributes": {"iid": iid, "action": action},
        "project": {"id": project_id},
        "labels": [{"title": lbl} for lbl in labels],
        "user": {"email": "user@example.com"},
    }


def _make_note_payload(
    noteable_type: str,
    project_id: int,
    iid: int,
    labels: list[str],
) -> dict:
    """テスト用NoteイベントWebhookペイロードを生成する"""
    payload: dict = {
        "object_attributes": {"noteable_type": noteable_type},
        "project": {"id": project_id},
        "user": {"email": "user@example.com"},
    }
    if noteable_type == "Issue":
        payload["issue"] = {
            "iid": iid,
            "labels": [{"title": lbl} for lbl in labels],
        }
    elif noteable_type == "MergeRequest":
        payload["merge_request"] = {
            "iid": iid,
            "labels": [{"title": lbl} for lbl in labels],
        }
    return payload


class TestHandleIssueEvent:
    """handle_issue_event()のテスト"""

    def test_処理対象IssueイベントからTaskを生成できる(
        self, handler: GitLabEventHandler
    ) -> None:
        """bot_labelのあるIssueイベントからTaskが正しく生成されることを確認する"""
        payload = _make_issue_payload(1, 100, ["coding agent"])
        task = handler.handle_issue_event(payload)

        assert task is not None
        assert task.task_type == "issue"
        assert task.project_id == 100
        assert task.issue_iid == 1

    def test_処理済みIssueは対象外(
        self, handler: GitLabEventHandler
    ) -> None:
        """processing_labelが付いているIssueはNoneが返されることを確認する"""
        payload = _make_issue_payload(
            1, 100, ["coding agent", "coding agent processing"]
        )
        task = handler.handle_issue_event(payload)
        assert task is None

    def test_bot_labelのないIssueは対象外(
        self, handler: GitLabEventHandler
    ) -> None:
        """bot_labelがないIssueはNoneが返されることを確認する"""
        payload = _make_issue_payload(1, 100, ["other-label"])
        task = handler.handle_issue_event(payload)
        assert task is None

    def test_closeアクションは対象外(
        self, handler: GitLabEventHandler
    ) -> None:
        """closeアクションのIssueイベントはNoneが返されることを確認する"""
        payload = _make_issue_payload(1, 100, ["coding agent"], action="close")
        task = handler.handle_issue_event(payload)
        assert task is None

    def test_updateアクションは処理対象(
        self, handler: GitLabEventHandler
    ) -> None:
        """updateアクションのIssueイベントはTaskが返されることを確認する"""
        payload = _make_issue_payload(1, 100, ["coding agent"], action="update")
        task = handler.handle_issue_event(payload)
        assert task is not None

    def test_reopenアクションは処理対象(
        self, handler: GitLabEventHandler
    ) -> None:
        """reopenアクションのIssueイベントはTaskが返されることを確認する"""
        payload = _make_issue_payload(1, 100, ["coding agent"], action="reopen")
        task = handler.handle_issue_event(payload)
        assert task is not None


class TestHandleMrEvent:
    """handle_mr_event()のテスト"""

    def test_処理対象MRイベントからTaskを生成できる(
        self, handler: GitLabEventHandler
    ) -> None:
        """bot_labelのあるMRイベントからTaskが正しく生成されることを確認する"""
        payload = _make_mr_payload(5, 200, ["coding agent"])
        task = handler.handle_mr_event(payload)

        assert task is not None
        assert task.task_type == "merge_request"
        assert task.project_id == 200
        assert task.mr_iid == 5

    def test_done_labelのあるMRは対象外(
        self, handler: GitLabEventHandler
    ) -> None:
        """done_labelが付いているMRはNoneが返されることを確認する"""
        payload = _make_mr_payload(5, 200, ["coding agent", "coding agent done"])
        task = handler.handle_mr_event(payload)
        assert task is None

    def test_mergeアクションは対象外(
        self, handler: GitLabEventHandler
    ) -> None:
        """mergeアクションのMRイベントはNoneが返されることを確認する"""
        payload = _make_mr_payload(5, 200, ["coding agent"], action="merge")
        task = handler.handle_mr_event(payload)
        assert task is None


class TestHandleNoteEvent:
    """handle_note_event()のテスト"""

    def test_Issue上のNoteからTaskを生成できる(
        self, handler: GitLabEventHandler
    ) -> None:
        """bot_label付きIssueのコメントからTaskが生成されることを確認する"""
        payload = _make_note_payload("Issue", 100, 1, ["coding agent"])
        task = handler.handle_note_event(payload)

        assert task is not None
        assert task.task_type == "issue"
        assert task.issue_iid == 1

    def test_MR上のNoteからTaskを生成できる(
        self, handler: GitLabEventHandler
    ) -> None:
        """bot_label付きMRのコメントからTaskが生成されることを確認する"""
        payload = _make_note_payload("MergeRequest", 200, 5, ["coding agent"])
        task = handler.handle_note_event(payload)

        assert task is not None
        assert task.task_type == "merge_request"
        assert task.mr_iid == 5

    def test_処理済みIssue上のNoteは対象外(
        self, handler: GitLabEventHandler
    ) -> None:
        """processing_label付きIssueのコメントはNoneが返されることを確認する"""
        payload = _make_note_payload(
            "Issue", 100, 1, ["coding agent", "coding agent processing"]
        )
        task = handler.handle_note_event(payload)
        assert task is None

    def test_未対応のnoteable_typeはNoneを返す(
        self, handler: GitLabEventHandler
    ) -> None:
        """未対応のnoteable_typeはNoneが返されることを確認する"""
        payload = _make_note_payload("Commit", 100, 1, ["coding agent"])
        task = handler.handle_note_event(payload)
        assert task is None

    def test_project_idがない場合はNoneを返す(
        self, handler: GitLabEventHandler
    ) -> None:
        """project_idが含まれないペイロードはNoneが返されることを確認する"""
        payload = {
            "object_attributes": {"noteable_type": "Issue"},
            "user": {"email": "user@example.com"},
        }
        task = handler.handle_note_event(payload)
        assert task is None


class TestHandleEvent:
    """handle_event()のテスト"""

    def test_IssueイベントをルーティングできるTaskが返る(
        self, handler: GitLabEventHandler
    ) -> None:
        """ISSUE_EVENTがhandle_issue_event()にルーティングされることを確認する"""
        payload = _make_issue_payload(1, 100, ["coding agent"])
        task = handler.handle_event(ISSUE_EVENT, payload)
        assert task is not None
        assert task.task_type == "issue"

    def test_MRイベントをルーティングできるTaskが返る(
        self, handler: GitLabEventHandler
    ) -> None:
        """MR_EVENTがhandle_mr_event()にルーティングされることを確認する"""
        payload = _make_mr_payload(5, 200, ["coding agent"])
        task = handler.handle_event(MR_EVENT, payload)
        assert task is not None
        assert task.task_type == "merge_request"

    def test_NoteイベントをルーティングできるTaskが返る(
        self, handler: GitLabEventHandler
    ) -> None:
        """NOTE_EVENTがhandle_note_event()にルーティングされることを確認する"""
        payload = _make_note_payload("Issue", 100, 1, ["coding agent"])
        task = handler.handle_event(NOTE_EVENT, payload)
        assert task is not None

    def test_未知のイベント種別はNoneを返す(
        self, handler: GitLabEventHandler
    ) -> None:
        """未対応のイベント種別はNoneが返されることを確認する"""
        task = handler.handle_event("Unknown Hook", {})
        assert task is None
