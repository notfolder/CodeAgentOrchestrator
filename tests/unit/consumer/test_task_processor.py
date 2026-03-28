"""
TaskProcessorの単体テスト

WorkflowFactoryとTaskStrategyFactoryをモックし、ワークフロー構築・実行・
ステータス遷移を検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from consumer.task_processor import TaskProcessor
from shared.models.task import Task


@pytest.fixture
def mock_task_handler() -> MagicMock:
    """テスト用TaskHandlerモックを返す"""
    handler = MagicMock()
    handler.handle = AsyncMock(return_value=True)
    return handler


@pytest.fixture
def mock_workflow_factory() -> MagicMock:
    """テスト用WorkflowFactoryモックを返す"""
    factory = MagicMock()
    factory.resume_workflow = AsyncMock()
    return factory


@pytest.fixture
def mock_workflow_exec_state_repo() -> MagicMock:
    """テスト用WorkflowExecutionStateRepositoryモックを返す"""
    repo = MagicMock()
    repo.list_suspended_executions = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def task_processor(
    mock_task_handler: MagicMock,
    mock_workflow_factory: MagicMock,
    mock_workflow_exec_state_repo: MagicMock,
) -> TaskProcessor:
    """テスト用TaskProcessorインスタンスを返す"""
    return TaskProcessor(
        task_handler=mock_task_handler,
        workflow_factory=mock_workflow_factory,
        workflow_exec_state_repo=mock_workflow_exec_state_repo,
    )


def _make_task() -> Task:
    """テスト用Taskを生成する"""
    return Task(
        task_uuid="proc-uuid-001",
        task_type="merge_request",
        project_id=1,
        issue_iid=None,
        mr_iid=5,
        username="testuser",
    )


class TestProcess:
    """process()のテスト"""

    async def test_タスクを正常に処理できる(
        self,
        task_processor: TaskProcessor,
        mock_task_handler: MagicMock,
    ) -> None:
        """TaskHandler.handle()が呼ばれて成功した場合はTrueが返されることを確認する"""
        task = _make_task()
        mock_task_handler.handle = AsyncMock(return_value=True)

        result = await task_processor.process(task)

        assert result is True
        mock_task_handler.handle.assert_awaited_once_with(task)

    async def test_処理失敗時はFalseを返す(
        self,
        task_processor: TaskProcessor,
        mock_task_handler: MagicMock,
    ) -> None:
        """TaskHandler.handle()がFalseを返した場合はFalseが返されることを確認する"""
        task = _make_task()
        mock_task_handler.handle = AsyncMock(return_value=False)

        result = await task_processor.process(task)

        assert result is False

    async def test_例外発生時はFalseを返す(
        self,
        task_processor: TaskProcessor,
        mock_task_handler: MagicMock,
    ) -> None:
        """TaskHandler.handle()が例外を投げた場合はFalseが返されることを確認する"""
        task = _make_task()
        mock_task_handler.handle = AsyncMock(side_effect=Exception("unexpected error"))

        result = await task_processor.process(task)

        assert result is False


class TestResumeSuspendedTasks:
    """resume_suspended_tasks()のテスト"""

    async def test_中断タスクが0件の場合は0を返す(
        self,
        task_processor: TaskProcessor,
        mock_workflow_exec_state_repo: MagicMock,
    ) -> None:
        """中断タスクがない場合は0が返されることを確認する"""
        mock_workflow_exec_state_repo.list_suspended_executions = AsyncMock(
            return_value=[]
        )

        result = await task_processor.resume_suspended_tasks()

        assert result == 0

    async def test_中断タスクを再開できる(
        self,
        task_processor: TaskProcessor,
        mock_workflow_exec_state_repo: MagicMock,
        mock_workflow_factory: MagicMock,
    ) -> None:
        """中断タスクが存在する場合にWorkflowFactory.resume_workflow()が呼ばれることを確認する"""
        mock_workflow_exec_state_repo.list_suspended_executions = AsyncMock(
            return_value=[
                {"execution_id": "exec-001"},
                {"execution_id": "exec-002"},
            ]
        )
        mock_workflow_factory.resume_workflow = AsyncMock()

        result = await task_processor.resume_suspended_tasks()

        assert result == 2
        assert mock_workflow_factory.resume_workflow.await_count == 2

    async def test_再開失敗したタスクはカウントされない(
        self,
        task_processor: TaskProcessor,
        mock_workflow_exec_state_repo: MagicMock,
        mock_workflow_factory: MagicMock,
    ) -> None:
        """resume_workflow()が例外を投げたタスクはカウントされないことを確認する"""
        mock_workflow_exec_state_repo.list_suspended_executions = AsyncMock(
            return_value=[
                {"execution_id": "exec-ok"},
                {"execution_id": "exec-fail"},
            ]
        )
        mock_workflow_factory.resume_workflow = AsyncMock(
            side_effect=[None, Exception("resume error")]
        )

        result = await task_processor.resume_suspended_tasks()

        assert result == 1

    async def test_workflow_factoryがNoneの場合は0を返す(
        self,
        mock_task_handler: MagicMock,
        mock_workflow_exec_state_repo: MagicMock,
    ) -> None:
        """workflow_factoryがNoneの場合は0が返されることを確認する"""
        processor = TaskProcessor(
            task_handler=mock_task_handler,
            workflow_factory=None,
            workflow_exec_state_repo=mock_workflow_exec_state_repo,
        )
        result = await processor.resume_suspended_tasks()
        assert result == 0

    async def test_repoがNoneの場合は0を返す(
        self,
        mock_task_handler: MagicMock,
        mock_workflow_factory: MagicMock,
    ) -> None:
        """workflow_exec_state_repoがNoneの場合は0が返されることを確認する"""
        processor = TaskProcessor(
            task_handler=mock_task_handler,
            workflow_factory=mock_workflow_factory,
            workflow_exec_state_repo=None,
        )
        result = await processor.resume_suspended_tasks()
        assert result == 0

    async def test_リポジトリエラー時は0を返す(
        self,
        task_processor: TaskProcessor,
        mock_workflow_exec_state_repo: MagicMock,
    ) -> None:
        """list_suspended_executions()がエラーを投げた場合は0が返されることを確認する"""
        mock_workflow_exec_state_repo.list_suspended_executions = AsyncMock(
            side_effect=Exception("DB error")
        )

        result = await task_processor.resume_suspended_tasks()
        assert result == 0

    async def test_execution_idがNoneのタスクはスキップされる(
        self,
        task_processor: TaskProcessor,
        mock_workflow_exec_state_repo: MagicMock,
        mock_workflow_factory: MagicMock,
    ) -> None:
        """execution_idがNoneのタスクはスキップされることを確認する"""
        mock_workflow_exec_state_repo.list_suspended_executions = AsyncMock(
            return_value=[
                {"execution_id": None},
                {"execution_id": "exec-valid"},
            ]
        )
        mock_workflow_factory.resume_workflow = AsyncMock()

        result = await task_processor.resume_suspended_tasks()

        assert result == 1
