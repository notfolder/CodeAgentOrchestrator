"""
TaskRepository の単体テスト

tasksテーブルへのCRUD操作の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from database.repositories.task_repository import TaskRepository


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """asyncpg.Pool のモックを生成する"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


class TestCreateTask:
    """create_task のテスト"""

    async def test_create_task_success(self):
        """タスクを正常に作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "uuid": "task-uuid-1",
            "task_type": "issue_to_mr",
            "task_identifier": "12345/issues/1",
            "repository": "owner/repo",
            "username": "testuser",
            "status": "running",
            "workflow_definition_id": None,
            "metadata": {},
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.create_task(
            "task-uuid-1",
            "issue_to_mr",
            "12345/issues/1",
            "owner/repo",
            "user@example.com",
        )

        assert result["uuid"] == "task-uuid-1"
        assert result["status"] == "running"
        conn.fetchrow.assert_awaited_once()

    async def test_create_task_with_metadata(self):
        """メタデータを指定してタスクを作成できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"uuid": "task-uuid-2"})

        repo = TaskRepository(pool)
        await repo.create_task(
            "task-uuid-2",
            "mr_processing",
            "12345/merge_requests/1",
            "owner/repo",
            "user@example.com",
            metadata={"gitlab_project_id": 12345},
        )

        conn.fetchrow.assert_awaited_once()
        call_args = conn.fetchrow.call_args[0]
        # JSONエンコードされたメタデータが引数に含まれることを確認する
        assert any("gitlab_project_id" in str(a) for a in call_args)


class TestGetTask:
    """get_task のテスト"""

    async def test_returns_task_when_found(self):
        """タスクが存在する場合にレコードを返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-uuid-1", "status": "running"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.get_task("task-uuid-1")

        assert result is not None
        assert result["uuid"] == "task-uuid-1"

    async def test_returns_none_when_not_found(self):
        """タスクが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = TaskRepository(pool)
        result = await repo.get_task("nonexistent-uuid")

        assert result is None


class TestUpdateTaskStatus:
    """update_task_status のテスト"""

    async def test_update_to_completed(self):
        """ステータスをcompletedに更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-1", "status": "completed"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_task_status("task-1", "completed")

        assert result is not None
        assert result["status"] == "completed"
        # completed_at が設定されることを確認する
        call_args = conn.fetchrow.call_args[0]
        assert "completed" in [str(a) for a in call_args]

    async def test_update_to_failed_with_error_message(self):
        """ステータスをfailedに更新しエラーメッセージを設定できることを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-1", "status": "failed", "error_message": "Error occurred"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_task_status(
            "task-1", "failed", error_message="Error occurred"
        )

        assert result is not None
        conn.fetchrow.assert_awaited_once()
        call_args = conn.fetchrow.call_args[0]
        assert "Error occurred" in [str(a) for a in call_args]

    async def test_returns_none_when_task_not_found(self):
        """対象タスクが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = TaskRepository(pool)
        result = await repo.update_task_status("nonexistent", "completed")

        assert result is None


class TestUpdateTaskMetadata:
    """update_task_metadata のテスト"""

    async def test_update_metadata(self):
        """タスクのメタデータを更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-1", "metadata": {"new_key": "new_value"}}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_task_metadata("task-1", {"new_key": "new_value"})

        assert result is not None
        conn.fetchrow.assert_awaited_once()


class TestUpdateTaskCounters:
    """update_task_counters のテスト"""

    async def test_update_message_count(self):
        """メッセージ数カウンターを更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-1", "total_messages": 5}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_task_counters("task-1", total_messages=5)

        assert result is not None
        conn.fetchrow.assert_awaited_once()

    async def test_update_with_no_fields_returns_current(self):
        """更新フィールドが空の場合はget_taskを呼び出すことを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-1", "total_messages": 0}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_task_counters("task-1")

        # get_task が呼ばれる（fetchrow 1回）
        conn.fetchrow.assert_awaited_once()


class TestUpdateAssignedBranches:
    """update_assigned_branches のテスト"""

    async def test_update_branches(self):
        """ブランチ割り当てを更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "uuid": "task-1",
            "assigned_branches": {"1": "feature/branch-1", "2": "feature/branch-2"},
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_assigned_branches(
            "task-1",
            {"1": "feature/branch-1", "2": "feature/branch-2"},
        )

        assert result is not None
        conn.fetchrow.assert_awaited_once()


class TestUpdateSelectedBranch:
    """update_selected_branch のテスト"""

    async def test_update_selected_branch_success(self):
        """選択ブランチを更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"uuid": "task-1", "selected_branch": "feature/branch-1"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TaskRepository(pool)
        result = await repo.update_selected_branch("task-1", "feature/branch-1")

        assert result is not None
        assert result["selected_branch"] == "feature/branch-1"
        conn.fetchrow.assert_awaited_once()

    async def test_update_selected_branch_returns_none_when_not_found(self):
        """対象タスクが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = TaskRepository(pool)
        result = await repo.update_selected_branch("nonexistent", "feature/branch-1")

        assert result is None


class TestCreateTaskDuplicate:
    """create_task の重複キー違反テスト"""

    async def test_create_task_raises_on_duplicate_uuid(self):
        """同一UUIDでタスクを重複作成するとUniqueViolationErrorが伝播することを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError())

        repo = TaskRepository(pool)
        with pytest.raises(asyncpg.UniqueViolationError):
            await repo.create_task(
                "dup-uuid",
                "issue_to_mr",
                "12345/issues/1",
                "owner/repo",
                "user@example.com",
            )


class TestDeleteTask:
    """delete_task のテスト"""

    async def test_delete_existing_task(self):
        """存在するタスクを削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = TaskRepository(pool)
        result = await repo.delete_task("task-1")

        assert result is True

    async def test_delete_nonexistent_task(self):
        """存在しないタスクを削除しようとした場合にFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = TaskRepository(pool)
        result = await repo.delete_task("nonexistent")

        assert result is False


class TestListTasks:
    """list_tasks のテスト"""

    async def test_list_all_tasks(self):
        """全タスク一覧を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"uuid": "task-1", "status": "running"},
            {"uuid": "task-2", "status": "completed"},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = TaskRepository(pool)
        result = await repo.list_tasks()

        assert len(result) == 2

    async def test_filter_by_status(self):
        """ステータスでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TaskRepository(pool)
        await repo.list_tasks(status="running")

        call_args = conn.fetch.call_args[0]
        assert any("status" in str(a) for a in call_args)

    async def test_filter_by_username(self):
        """ユーザーメールアドレスでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TaskRepository(pool)
        await repo.list_tasks(username="testuser")

        call_args = conn.fetch.call_args[0]
        assert any("username" in str(a) for a in call_args)

    async def test_filter_by_repository(self):
        """リポジトリでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TaskRepository(pool)
        await repo.list_tasks(repository="owner/repo")

        call_args = conn.fetch.call_args[0]
        assert "owner/repo" in call_args


class TestDeleteOldCompletedTasks:
    """delete_old_completed_tasks のテスト"""

    async def test_delete_old_tasks(self):
        """古い完了済みタスクを削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 5")

        repo = TaskRepository(pool)
        result = await repo.delete_old_completed_tasks(retention_days=30)

        assert result == 5
        conn.execute.assert_awaited_once()

    async def test_delete_with_custom_retention(self):
        """保持日数をカスタマイズして削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = TaskRepository(pool)
        result = await repo.delete_old_completed_tasks(retention_days=90)

        assert result == 0
        call_args = conn.execute.call_args[0]
        assert "90" in [str(a) for a in call_args]
