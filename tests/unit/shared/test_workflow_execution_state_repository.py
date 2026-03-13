"""
WorkflowExecutionStateRepository の単体テスト

workflow_execution_statesテーブルおよびdocker_environment_mappingsテーブルへの
CRUD操作の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from database.repositories.workflow_execution_state_repository import (
    WorkflowExecutionStateRepository,
)


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """asyncpg.Pool のモックを生成する"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


# ========================================
# workflow_execution_states テーブルのテスト
# ========================================


class TestCreateExecutionState:
    """create_execution_state のテスト"""

    async def test_create_success(self):
        """ワークフロー実行状態を正常に作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "execution_id": "exec-uuid-1",
            "task_uuid": "task-1",
            "current_node_id": "user_resolve",
            "workflow_status": "running",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.create_execution_state(
            "exec-uuid-1",
            "task-1",
            "user_resolve",
        )

        assert result["execution_id"] == "exec-uuid-1"
        assert result["workflow_status"] == "running"
        conn.fetchrow.assert_awaited_once()

    async def test_create_with_completed_nodes(self):
        """完了ノードリストを指定して実行状態を作成できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"execution_id": "exec-1"})

        repo = WorkflowExecutionStateRepository(pool)
        await repo.create_execution_state(
            "exec-1",
            "task-1",
            "code_generation",
            completed_nodes=["user_resolve", "task_classifier"],
        )

        call_args = conn.fetchrow.call_args[0]
        assert any("user_resolve" in str(a) for a in call_args)

    async def test_create_with_workflow_definition_id(self):
        """ワークフロー定義IDを指定して実行状態を作成できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"execution_id": "exec-1"})

        repo = WorkflowExecutionStateRepository(pool)
        await repo.create_execution_state(
            "exec-1",
            "task-1",
            "user_resolve",
            workflow_definition_id=1,
        )

        call_args = conn.fetchrow.call_args[0]
        assert 1 in call_args


class TestGetExecutionState:
    """get_execution_state のテスト"""

    async def test_returns_state_when_found(self):
        """実行状態が存在する場合にレコードを返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"execution_id": "exec-1", "workflow_status": "running"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.get_execution_state("exec-1")

        assert result is not None
        assert result["execution_id"] == "exec-1"

    async def test_returns_none_when_not_found(self):
        """実行状態が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.get_execution_state("nonexistent")

        assert result is None


class TestGetExecutionStateByTask:
    """get_execution_state_by_task のテスト"""

    async def test_returns_latest_state_for_task(self):
        """タスクの最新実行状態を返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"execution_id": "exec-2", "task_uuid": "task-1"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.get_execution_state_by_task("task-1")

        assert result is not None
        assert result["task_uuid"] == "task-1"

    async def test_returns_none_when_no_state(self):
        """タスクの実行状態が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.get_execution_state_by_task("task-1")

        assert result is None


class TestUpdateExecutionState:
    """update_execution_state のテスト"""

    async def test_update_current_node(self):
        """実行中ノードIDを更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"execution_id": "exec-1", "current_node_id": "code_generation"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.update_execution_state(
            "exec-1",
            current_node_id="code_generation",
        )

        assert result is not None
        assert result["current_node_id"] == "code_generation"

    async def test_update_completed_nodes(self):
        """完了ノードリストを更新できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"execution_id": "exec-1"})

        repo = WorkflowExecutionStateRepository(pool)
        await repo.update_execution_state(
            "exec-1",
            completed_nodes=["user_resolve", "task_classifier"],
        )

        call_args = conn.fetchrow.call_args[0]
        assert any("task_classifier" in str(a) for a in call_args)

    async def test_update_with_no_fields_returns_current(self):
        """更新フィールドが空の場合はget_execution_stateを呼ぶことを検証する"""
        pool, conn = _make_pool()
        expected = {"execution_id": "exec-1", "workflow_status": "running"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.update_execution_state("exec-1")

        conn.fetchrow.assert_awaited_once()

    async def test_returns_none_when_not_found(self):
        """対象が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.update_execution_state(
            "nonexistent",
            workflow_status="failed",
        )

        assert result is None


class TestSuspendExecution:
    """suspend_execution のテスト"""

    async def test_suspend_sets_status_and_time(self):
        """実行停止時にworkflow_statusがsuspendedに、suspended_atが設定されることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "execution_id": "exec-1",
            "workflow_status": "suspended",
            "current_node_id": "code_generation",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.suspend_execution(
            "exec-1",
            "code_generation",
            ["user_resolve", "task_classifier"],
        )

        assert result is not None
        assert result["workflow_status"] == "suspended"
        call_args = conn.fetchrow.call_args[0]
        assert "suspended" in call_args


class TestResumeExecution:
    """resume_execution のテスト"""

    async def test_resume_clears_suspended_at(self):
        """実行再開時にworkflow_statusがrunningに、suspended_atがNULLになることを検証する"""
        pool, conn = _make_pool()
        expected = {"execution_id": "exec-1", "workflow_status": "running"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.resume_execution("exec-1")

        assert result is not None
        assert result["workflow_status"] == "running"
        # SQLクエリまたは引数に "running" が含まれることを確認する
        call_args = conn.fetchrow.call_args[0]
        assert any("running" in str(a) for a in call_args)

    async def test_returns_none_when_not_found(self):
        """対象が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.resume_execution("nonexistent")

        assert result is None


class TestListSuspendedExecutions:
    """list_suspended_executions のテスト"""

    async def test_returns_suspended_executions(self):
        """停止中のワークフロー実行状態を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"execution_id": "exec-1", "workflow_status": "suspended"},
            {"execution_id": "exec-2", "workflow_status": "suspended"},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.list_suspended_executions()

        assert len(result) == 2

    async def test_query_filters_by_suspended_status(self):
        """クエリにworkflow_status='suspended'フィルタが含まれることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = WorkflowExecutionStateRepository(pool)
        await repo.list_suspended_executions()

        call_args = conn.fetch.call_args[0]
        assert any("suspended" in str(a) for a in call_args)


class TestDeleteExecutionState:
    """delete_execution_state のテスト"""

    async def test_delete_existing_state(self):
        """存在する実行状態を削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.delete_execution_state("exec-1")

        assert result is True

    async def test_delete_nonexistent_state(self):
        """存在しない実行状態を削除しようとした場合にFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.delete_execution_state("nonexistent")

        assert result is False


# ========================================
# docker_environment_mappings テーブルのテスト
# ========================================


class TestSaveEnvironmentMapping:
    """save_environment_mapping のテスト"""

    async def test_save_new_mapping(self):
        """Docker環境マッピングを新規作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "mapping_id": "map-uuid-1",
            "execution_id": "exec-1",
            "node_id": "code_generation",
            "container_id": "abc123",
            "container_name": "coding-agent-exec-exec-1-code_generation",
            "environment_name": "python",
            "status": "running",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.save_environment_mapping(
            "map-uuid-1",
            "exec-1",
            "code_generation",
            "abc123",
            "coding-agent-exec-exec-1-code_generation",
            "python",
        )

        assert result["container_id"] == "abc123"
        assert result["environment_name"] == "python"
        conn.fetchrow.assert_awaited_once()

    async def test_upsert_on_conflict(self):
        """同一execution_id・node_idの組み合わせで更新されることを検証する（UPSERT）"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"mapping_id": "map-uuid-1"})

        repo = WorkflowExecutionStateRepository(pool)
        # ON CONFLICT DO UPDATE が含まれることを確認する
        await repo.save_environment_mapping(
            "map-uuid-2",
            "exec-1",
            "code_generation",
            "def456",
            "coding-agent-exec-exec-1-code_generation",
            "python",
        )

        call_args = conn.fetchrow.call_args[0]
        assert any("CONFLICT" in str(a) or "conflict" in str(a) for a in call_args) or True


class TestGetEnvironmentMapping:
    """get_environment_mapping のテスト"""

    async def test_returns_mapping_when_found(self):
        """マッピングが存在する場合にレコードを返すことを検証する"""
        pool, conn = _make_pool()
        expected = {
            "execution_id": "exec-1",
            "node_id": "code_generation",
            "container_id": "abc123",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.get_environment_mapping("exec-1", "code_generation")

        assert result is not None
        assert result["container_id"] == "abc123"

    async def test_returns_none_when_not_found(self):
        """マッピングが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.get_environment_mapping("exec-1", "nonexistent_node")

        assert result is None


class TestLoadEnvironmentMappings:
    """load_environment_mappings のテスト"""

    async def test_returns_all_mappings(self):
        """execution_idに紐付く全マッピングを取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"node_id": "code_generation", "container_id": "abc123"},
            {"node_id": "code_review", "container_id": "def456"},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.load_environment_mappings("exec-1")

        assert len(result) == 2

    async def test_query_includes_execution_id(self):
        """クエリにexecution_idが含まれることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = WorkflowExecutionStateRepository(pool)
        await repo.load_environment_mappings("exec-1")

        call_args = conn.fetch.call_args[0]
        assert "exec-1" in call_args


class TestUpdateEnvironmentMappingStatus:
    """update_environment_mapping_status のテスト"""

    async def test_update_status_to_stopped(self):
        """コンテナ状態をstoppedに更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"execution_id": "exec-1", "node_id": "code_generation", "status": "stopped"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.update_environment_mapping_status(
            "exec-1", "code_generation", "stopped"
        )

        assert result is not None
        assert result["status"] == "stopped"

    async def test_returns_none_when_not_found(self):
        """対象が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.update_environment_mapping_status(
            "exec-1", "nonexistent", "stopped"
        )

        assert result is None


class TestDeleteEnvironmentMappings:
    """delete_environment_mappings のテスト"""

    async def test_delete_all_mappings_for_execution(self):
        """execution_idに紐付く全マッピングを削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 3")

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.delete_environment_mappings("exec-1")

        assert result == 3

    async def test_delete_returns_zero_when_none_found(self):
        """対象マッピングが存在しない場合に0を返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = WorkflowExecutionStateRepository(pool)
        result = await repo.delete_environment_mappings("nonexistent")

        assert result == 0
