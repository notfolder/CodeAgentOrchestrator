"""
TaskGetterFromGitLabの単体テスト

GitLab APIモックを用いてIssue・MR取得・フィルタリングロジックを検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from producer.task_getter_from_gitlab import TaskGetterFromGitLab
from shared.config.models import GitLabConfig
from shared.models.gitlab import GitLabIssue, GitLabMergeRequest


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
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    return MagicMock()


@pytest.fixture
def task_getter(
    mock_gitlab_client: MagicMock, gitlab_config: GitLabConfig
) -> TaskGetterFromGitLab:
    """テスト用TaskGetterFromGitLabインスタンスを返す"""
    return TaskGetterFromGitLab(
        gitlab_client=mock_gitlab_client,
        gitlab_config=gitlab_config,
        project_id=1,
    )


def _make_issue(iid: int, labels: list[str]) -> GitLabIssue:
    """テスト用GitLabIssueを生成する"""
    return GitLabIssue(
        iid=iid,
        title=f"Test Issue {iid}",
        project_id=1,
        labels=labels,
    )


def _make_mr(iid: int, labels: list[str]) -> GitLabMergeRequest:
    """テスト用GitLabMergeRequestを生成する"""
    return GitLabMergeRequest(
        iid=iid,
        title=f"Test MR {iid}",
        project_id=1,
        source_branch="feature",
        target_branch="main",
        labels=labels,
    )


class TestIsProcessingTarget:
    """_is_processing_target()のテスト"""

    def test_bot_labelのみの場合は処理対象(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """bot_labelのみ付与されている場合に処理対象と判定されることを確認する"""
        assert task_getter._is_processing_target(["coding agent"]) is True

    def test_bot_labelがない場合は対象外(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """bot_labelが付与されていない場合に処理対象外と判定されることを確認する"""
        assert task_getter._is_processing_target(["other label"]) is False

    def test_processing_labelがある場合は対象外(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """processing_labelが付与されている場合に処理対象外と判定されることを確認する"""
        assert (
            task_getter._is_processing_target(
                ["coding agent", "coding agent processing"]
            )
            is False
        )

    def test_done_labelがある場合は対象外(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """done_labelが付与されている場合に処理対象外と判定されることを確認する"""
        assert (
            task_getter._is_processing_target(
                ["coding agent", "coding agent done"]
            )
            is False
        )

    def test_paused_labelがある場合は対象外(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """paused_labelが付与されている場合に処理対象外と判定されることを確認する"""
        assert (
            task_getter._is_processing_target(
                ["coding agent", "coding agent paused"]
            )
            is False
        )

    def test_stopped_labelがある場合は対象外(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """stopped_labelが付与されている場合に処理対象外と判定されることを確認する"""
        assert (
            task_getter._is_processing_target(
                ["coding agent", "coding agent stopped"]
            )
            is False
        )

    def test_空リストは対象外(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """ラベルが空の場合に処理対象外と判定されることを確認する"""
        assert task_getter._is_processing_target([]) is False


class TestGetUnprocessedIssues:
    """get_unprocessed_issues()のテスト"""

    def test_未処理Issueを取得できる(
        self,
        task_getter: TaskGetterFromGitLab,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """処理対象のIssueのみが返されることを確認する"""
        mock_gitlab_client.list_issues.return_value = [
            _make_issue(1, ["coding agent"]),
            _make_issue(2, ["coding agent", "coding agent processing"]),
            _make_issue(3, ["coding agent", "coding agent done"]),
        ]

        result = task_getter.get_unprocessed_issues()

        assert len(result) == 1
        assert result[0].iid == 1

    def test_APIエラー時は空リストを返す(
        self,
        task_getter: TaskGetterFromGitLab,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """GitLab APIエラー時に空リストが返されることを確認する"""
        mock_gitlab_client.list_issues.side_effect = Exception("API Error")

        result = task_getter.get_unprocessed_issues()

        assert result == []

    def test_全てのIssueが除外された場合は空リスト(
        self,
        task_getter: TaskGetterFromGitLab,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """全Issueが除外条件に該当する場合に空リストが返されることを確認する"""
        mock_gitlab_client.list_issues.return_value = [
            _make_issue(1, ["coding agent", "coding agent processing"]),
        ]

        result = task_getter.get_unprocessed_issues()
        assert result == []


class TestGetUnprocessedMergeRequests:
    """get_unprocessed_merge_requests()のテスト"""

    def test_未処理MRを取得できる(
        self,
        task_getter: TaskGetterFromGitLab,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """処理対象のMRのみが返されることを確認する"""
        mock_gitlab_client.list_merge_requests.return_value = [
            _make_mr(10, ["coding agent"]),
            _make_mr(11, ["coding agent", "coding agent done"]),
        ]

        result = task_getter.get_unprocessed_merge_requests()

        assert len(result) == 1
        assert result[0].iid == 10

    def test_APIエラー時は空リストを返す(
        self,
        task_getter: TaskGetterFromGitLab,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """GitLab APIエラー時に空リストが返されることを確認する"""
        mock_gitlab_client.list_merge_requests.side_effect = Exception("API Error")

        result = task_getter.get_unprocessed_merge_requests()

        assert result == []


class TestIssueToTask:
    """issue_to_task()のテスト"""

    def test_IssueをTaskに変換できる(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """GitLabIssueがTaskオブジェクトに正しく変換されることを確認する"""
        issue = _make_issue(5, ["coding agent"])
        task = task_getter.issue_to_task(issue, user_email="user@example.com")

        assert task.task_type == "issue"
        assert task.project_id == 1
        assert task.issue_iid == 5
        assert task.mr_iid is None
        assert task.user_email == "user@example.com"
        assert task.task_uuid is not None

    def test_UUIDはユニークである(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """2つのTaskのtask_uuidが異なることを確認する"""
        issue = _make_issue(1, ["coding agent"])
        task1 = task_getter.issue_to_task(issue)
        task2 = task_getter.issue_to_task(issue)
        assert task1.task_uuid != task2.task_uuid


class TestMrToTask:
    """mr_to_task()のテスト"""

    def test_MRをTaskに変換できる(
        self, task_getter: TaskGetterFromGitLab
    ) -> None:
        """GitLabMergeRequestがTaskオブジェクトに正しく変換されることを確認する"""
        mr = _make_mr(20, ["coding agent"])
        task = task_getter.mr_to_task(mr, user_email="dev@example.com")

        assert task.task_type == "merge_request"
        assert task.project_id == 1
        assert task.mr_iid == 20
        assert task.issue_iid is None
        assert task.user_email == "dev@example.com"


class TestGetAllUnprocessedTasks:
    """get_all_unprocessed_tasks()のテスト"""

    def test_IssueとMRをまとめて取得できる(
        self,
        task_getter: TaskGetterFromGitLab,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """未処理のIssueとMRが合計でリストに含まれることを確認する"""
        mock_gitlab_client.list_issues.return_value = [
            _make_issue(1, ["coding agent"]),
        ]
        mock_gitlab_client.list_merge_requests.return_value = [
            _make_mr(10, ["coding agent"]),
        ]

        tasks = task_getter.get_all_unprocessed_tasks()

        assert len(tasks) == 2
        task_types = {t.task_type for t in tasks}
        assert "issue" in task_types
        assert "merge_request" in task_types
