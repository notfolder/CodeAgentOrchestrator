"""
TaskHandlerの単体テスト

handle(task)の処理分岐・_should_convert_issue_to_mr()の判定ロジック・
TaskStrategyFactory呼び出しを検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consumer.handlers.task_handler import TaskHandler
from shared.models.task import Task


@pytest.fixture
def mock_task_strategy_factory() -> MagicMock:
    """テスト用TaskStrategyFactoryモックを返す"""
    factory = MagicMock()
    factory.should_convert_issue_to_mr.return_value = False
    strategy = MagicMock()
    strategy.execute = AsyncMock()
    factory.create_strategy.return_value = strategy
    return factory


@pytest.fixture
def mock_task_repository() -> MagicMock:
    """テスト用TaskRepositoryモックを返す"""
    repo = MagicMock()
    repo.create_task = AsyncMock(return_value={"uuid": "test-uuid"})
    repo.update_task_status = AsyncMock()
    return repo


@pytest.fixture
def task_handler(
    mock_task_strategy_factory: MagicMock,
    mock_task_repository: MagicMock,
) -> TaskHandler:
    """テスト用TaskHandlerインスタンスを返す"""
    return TaskHandler(
        task_strategy_factory=mock_task_strategy_factory,
        task_repository=mock_task_repository,
    )


def _make_issue_task() -> Task:
    """テスト用IssueタスクMockを返す"""
    return Task(
        task_uuid="issue-uuid-001",
        task_type="issue",
        project_id=1,
        issue_iid=10,
        mr_iid=None,
        username="testuser",
    )


def _make_mr_task() -> Task:
    """テスト用MRタスクMockを返す"""
    return Task(
        task_uuid="mr-uuid-001",
        task_type="merge_request",
        project_id=1,
        issue_iid=None,
        mr_iid=20,
        username="testuser",
    )


class TestShouldConvertIssueToMr:
    """_should_convert_issue_to_mr()のテスト"""

    def test_Issueタスクの場合にファクトリに委譲する(
        self,
        task_handler: TaskHandler,
        mock_task_strategy_factory: MagicMock,
    ) -> None:
        """issue型タスクの場合にTaskStrategyFactoryに委譲することを確認する"""
        mock_task_strategy_factory.should_convert_issue_to_mr.return_value = True
        task = _make_issue_task()

        result = task_handler._should_convert_issue_to_mr(task)

        assert result is True
        mock_task_strategy_factory.should_convert_issue_to_mr.assert_called_once_with(task)

    def test_MRタスクの場合はFalseを返す(
        self, task_handler: TaskHandler
    ) -> None:
        """merge_request型タスクの場合はFalseを返すことを確認する"""
        task = _make_mr_task()
        result = task_handler._should_convert_issue_to_mr(task)
        assert result is False

    def test_変換不要の場合はFalseを返す(
        self,
        task_handler: TaskHandler,
        mock_task_strategy_factory: MagicMock,
    ) -> None:
        """should_convert_issue_to_mrがFalseを返す場合はFalseになることを確認する"""
        mock_task_strategy_factory.should_convert_issue_to_mr.return_value = False
        task = _make_issue_task()

        result = task_handler._should_convert_issue_to_mr(task)
        assert result is False


class TestHandle:
    """handle(task)のテスト"""

    async def test_MRタスクを正常に処理できる(
        self,
        task_handler: TaskHandler,
        mock_task_strategy_factory: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """MRタスクがMergeRequestStrategyで正常に処理されることを確認する"""
        task = _make_mr_task()
        strategy_mock = MagicMock()
        strategy_mock.execute = AsyncMock()
        mock_task_strategy_factory.create_strategy.return_value = strategy_mock

        result = await task_handler.handle(task)

        assert result is True
        strategy_mock.execute.assert_awaited_once_with(task)

    async def test_Issueタスクを正常に処理できる(
        self,
        task_handler: TaskHandler,
        mock_task_strategy_factory: MagicMock,
    ) -> None:
        """Issueタスクが適切な戦略で処理されることを確認する"""
        task = _make_issue_task()
        strategy_mock = MagicMock()
        strategy_mock.execute = AsyncMock()
        mock_task_strategy_factory.create_strategy.return_value = strategy_mock

        result = await task_handler.handle(task)

        assert result is True
        mock_task_strategy_factory.create_strategy.assert_called_once()

    async def test_タスクDBへの記録が行われる(
        self,
        task_handler: TaskHandler,
        mock_task_repository: MagicMock,
        mock_task_strategy_factory: MagicMock,
    ) -> None:
        """タスク処理前にDBにタスクが記録されることを確認する"""
        task = _make_mr_task()
        strategy_mock = MagicMock()
        strategy_mock.execute = AsyncMock()
        mock_task_strategy_factory.create_strategy.return_value = strategy_mock

        await task_handler.handle(task)

        mock_task_repository.create_task.assert_awaited_once()

    async def test_戦略生成失敗時にFalseを返す(
        self,
        task_handler: TaskHandler,
        mock_task_strategy_factory: MagicMock,
    ) -> None:
        """TaskStrategyFactory.create_strategy()がValueErrorを投げた場合はFalseを返すことを確認する"""
        mock_task_strategy_factory.create_strategy.side_effect = ValueError(
            "Unknown task type"
        )
        task = _make_mr_task()

        result = await task_handler.handle(task)

        assert result is False

    async def test_戦略実行失敗時にFalseを返す(
        self,
        task_handler: TaskHandler,
        mock_task_strategy_factory: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """strategy.execute()が例外を投げた場合はFalseを返しステータスをfailedに更新することを確認する"""
        task = _make_mr_task()
        strategy_mock = MagicMock()
        strategy_mock.execute = AsyncMock(side_effect=Exception("execution error"))
        mock_task_strategy_factory.create_strategy.return_value = strategy_mock

        result = await task_handler.handle(task)

        assert result is False
        mock_task_repository.update_task_status.assert_awaited_with(task.task_uuid, "failed")

    async def test_task_repositoryがNoneでも動作する(
        self, mock_task_strategy_factory: MagicMock
    ) -> None:
        """task_repositoryがNoneの場合でも正常に処理されることを確認する"""
        handler = TaskHandler(
            task_strategy_factory=mock_task_strategy_factory,
            task_repository=None,
        )
        task = _make_mr_task()
        strategy_mock = MagicMock()
        strategy_mock.execute = AsyncMock()
        mock_task_strategy_factory.create_strategy.return_value = strategy_mock

        result = await handler.handle(task)
        assert result is True


class TestUpdateTaskStatus:
    """_update_task_status()のテスト"""

    async def test_completedステータスに更新できる(
        self,
        task_handler: TaskHandler,
        mock_task_repository: MagicMock,
    ) -> None:
        """タスクステータスをcompletedに更新できることを確認する"""
        await task_handler._update_task_status("test-uuid", "completed")
        mock_task_repository.update_task_status.assert_awaited_once_with(
            "test-uuid", "completed"
        )

    async def test_task_repositoryがNoneの場合は何もしない(self) -> None:
        """task_repositoryがNoneの場合はエラーなく終了することを確認する"""
        handler = TaskHandler(
            task_strategy_factory=MagicMock(),
            task_repository=None,
        )
        # 例外が発生しないことを確認する
        await handler._update_task_status("test-uuid", "failed")
