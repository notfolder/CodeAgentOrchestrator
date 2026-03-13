"""
ContextRepository の単体テスト

context_messages, message_compressions, context_planning_history,
context_metadata, context_tool_results_metadata, todos テーブルへの
CRUD操作の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from database.repositories.context_repository import ContextRepository


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """asyncpg.Pool のモックを生成する"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


# ========================================
# context_messages テーブルのテスト
# ========================================


class TestAddMessage:
    """add_message のテスト"""

    async def test_add_user_message(self):
        """ユーザーメッセージを追加できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "task_uuid": "task-1",
            "seq": 0,
            "role": "user",
            "content": "Hello",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.add_message("task-1", 0, "user", "Hello")

        assert result["seq"] == 0
        assert result["role"] == "user"
        conn.fetchrow.assert_awaited_once()

    async def test_add_tool_message(self):
        """ツールメッセージにtool_call_idとtool_nameを設定できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 2, "role": "tool"})

        repo = ContextRepository(pool)
        await repo.add_message(
            "task-1",
            1,
            "tool",
            "tool result",
            tool_call_id="call-123",
            tool_name="text_editor",
        )

        call_args = conn.fetchrow.call_args[0]
        assert "call-123" in call_args
        assert "text_editor" in call_args

    async def test_add_compressed_summary(self):
        """圧縮要約メッセージを追加できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 3, "is_compressed_summary": True})

        repo = ContextRepository(pool)
        await repo.add_message(
            "task-1",
            5,
            "user",
            "[Summary of previous conversation (messages 0-4)]: ...",
            is_compressed_summary=True,
            compressed_range={"start_seq": 0, "end_seq": 4},
        )

        call_args = conn.fetchrow.call_args[0]
        assert True in call_args


class TestGetMessages:
    """get_messages のテスト"""

    async def test_get_all_messages(self):
        """全メッセージを時系列順に取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"id": 1, "seq": 0, "role": "system"},
            {"id": 2, "seq": 1, "role": "user"},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = ContextRepository(pool)
        result = await repo.get_messages("task-1")

        assert len(result) == 2

    async def test_get_messages_with_limit(self):
        """limitを指定してメッセージを取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[{"id": 1}])

        repo = ContextRepository(pool)
        await repo.get_messages("task-1", limit=10)

        call_args = conn.fetch.call_args[0]
        assert 10 in call_args


class TestGetLatestMessages:
    """get_latest_messages のテスト"""

    async def test_get_latest_n_messages(self):
        """最新N件のメッセージを取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [{"id": 5, "seq": 4}, {"id": 6, "seq": 5}]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = ContextRepository(pool)
        result = await repo.get_latest_messages("task-1", 5)

        assert len(result) == 2
        call_args = conn.fetch.call_args[0]
        assert 5 in call_args


class TestDeleteMessagesInRange:
    """delete_messages_in_range のテスト"""

    async def test_delete_in_range(self):
        """指定seq範囲のメッセージを削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 5")

        repo = ContextRepository(pool)
        count = await repo.delete_messages_in_range("task-1", 0, 4)

        assert count == 5
        call_args = conn.execute.call_args[0]
        assert 0 in call_args
        assert 4 in call_args


class TestGetMessageCount:
    """get_message_count のテスト"""

    async def test_get_count(self):
        """メッセージ件数を取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=10)

        repo = ContextRepository(pool)
        result = await repo.get_message_count("task-1")

        assert result == 10

    async def test_returns_zero_when_no_messages(self):
        """メッセージが0件の場合に0を返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=None)

        repo = ContextRepository(pool)
        result = await repo.get_message_count("task-1")

        assert result == 0


class TestGetTotalTokens:
    """get_total_tokens のテスト"""

    async def test_get_total_tokens(self):
        """トータルトークン数を取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=1500)

        repo = ContextRepository(pool)
        result = await repo.get_total_tokens("task-1")

        assert result == 1500


# ========================================
# message_compressions テーブルのテスト
# ========================================


class TestAddMessageCompression:
    """add_message_compression のテスト"""

    async def test_add_compression_record(self):
        """メッセージ圧縮履歴を記録できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "task_uuid": "task-1",
            "start_seq": 0,
            "end_seq": 10,
            "summary_seq": 11,
            "original_token_count": 1000,
            "compressed_token_count": 200,
            "compression_ratio": 0.2,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.add_message_compression(
            "task-1",
            start_seq=0,
            end_seq=10,
            summary_seq=11,
            original_token_count=1000,
            compressed_token_count=200,
        )

        assert result["start_seq"] == 0
        assert result["end_seq"] == 10

    async def test_auto_calculates_compression_ratio(self):
        """compression_ratioがNullの場合は自動計算されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 1})

        repo = ContextRepository(pool)
        await repo.add_message_compression(
            "task-1",
            start_seq=0,
            end_seq=10,
            summary_seq=11,
            original_token_count=1000,
            compressed_token_count=200,
        )

        call_args = conn.fetchrow.call_args[0]
        # 自動計算された圧縮率 0.2 が引数に含まれることを確認する
        assert 0.2 in call_args


class TestGetCompressionHistory:
    """get_compression_history のテスト"""

    async def test_get_history(self):
        """圧縮履歴を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [{"id": 1}, {"id": 2}]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = ContextRepository(pool)
        result = await repo.get_compression_history("task-1")

        assert len(result) == 2


# ========================================
# context_planning_history テーブルのテスト
# ========================================


class TestAddPlanningHistory:
    """add_planning_history のテスト"""

    async def test_add_planning_entry(self):
        """プランニング履歴を追加できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "task_uuid": "task-1",
            "phase": "planning",
            "node_id": "code_planning",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.add_planning_history(
            "task-1",
            "planning",
            "code_planning",
            plan={"todos": [{"id": 1, "title": "実装"}]},
        )

        assert result["phase"] == "planning"
        conn.fetchrow.assert_awaited_once()

    async def test_add_execution_entry_with_action_id(self):
        """executionフェーズのアクションIDを設定できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 2, "phase": "execution"})

        repo = ContextRepository(pool)
        await repo.add_planning_history(
            "task-1",
            "execution",
            "code_execution",
            action_id="act-001",
            result="実装完了",
        )

        call_args = conn.fetchrow.call_args[0]
        assert "act-001" in call_args


class TestGetPlanningHistory:
    """get_planning_history のテスト"""

    async def test_get_all_history(self):
        """全プランニング履歴を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [{"id": 1, "phase": "planning"}, {"id": 2, "phase": "execution"}]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = ContextRepository(pool)
        result = await repo.get_planning_history("task-1")

        assert len(result) == 2

    async def test_filter_by_phase(self):
        """フェーズでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = ContextRepository(pool)
        await repo.get_planning_history("task-1", phase="planning")

        call_args = conn.fetch.call_args[0]
        assert "planning" in call_args


# ========================================
# context_metadata テーブルのテスト
# ========================================


class TestCreateContextMetadata:
    """create_context_metadata のテスト"""

    async def test_create_metadata(self):
        """コンテキストメタデータを作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "task_uuid": "task-1",
            "task_type": "issue_to_mr",
            "repository": "owner/repo",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.create_context_metadata(
            "task-1",
            "issue_to_mr",
            "12345/issues/1",
            "owner/repo",
            "user@example.com",
        )

        assert result["task_uuid"] == "task-1"
        conn.fetchrow.assert_awaited_once()


class TestGetContextMetadata:
    """get_context_metadata のテスト"""

    async def test_returns_metadata_when_found(self):
        """メタデータが存在する場合にレコードを返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"task_uuid": "task-1"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.get_context_metadata("task-1")

        assert result is not None
        assert result["task_uuid"] == "task-1"

    async def test_returns_none_when_not_found(self):
        """メタデータが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = ContextRepository(pool)
        result = await repo.get_context_metadata("nonexistent")

        assert result is None


# ========================================
# context_tool_results_metadata テーブルのテスト
# ========================================


class TestAddToolResultMetadata:
    """add_tool_result_metadata のテスト"""

    async def test_add_metadata(self):
        """ツール実行結果メタデータを追加できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "task_uuid": "task-1",
            "tool_name": "text_editor",
            "file_path": "tool_results/task-1/result.json",
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.add_tool_result_metadata(
            "task-1",
            "text_editor",
            "tool_results/task-1/result.json",
            1024,
        )

        assert result["tool_name"] == "text_editor"
        conn.fetchrow.assert_awaited_once()


class TestGetToolResultMetadata:
    """get_tool_result_metadata のテスト"""

    async def test_get_all_metadata(self):
        """全ツール実行結果メタデータを取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [{"id": 1, "tool_name": "text_editor"}]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = ContextRepository(pool)
        result = await repo.get_tool_result_metadata("task-1")

        assert len(result) == 1

    async def test_filter_by_tool_name(self):
        """ツール名でフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = ContextRepository(pool)
        await repo.get_tool_result_metadata("task-1", tool_name="command_executor")

        call_args = conn.fetch.call_args[0]
        assert "command_executor" in call_args


# ========================================
# todos テーブルのテスト
# ========================================


class TestCreateTodo:
    """create_todo のテスト"""

    async def test_create_root_todo(self):
        """ルートレベルのTodoを作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "task_uuid": "task-1",
            "title": "実装を完了する",
            "status": "not-started",
            "order_index": 0,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.create_todo("task-1", "実装を完了する", 0)

        assert result["title"] == "実装を完了する"
        assert result["status"] == "not-started"
        conn.fetchrow.assert_awaited_once()

    async def test_create_sub_todo_with_parent(self):
        """親TodoIDを指定してサブTodoを作成できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 2, "parent_todo_id": 1})

        repo = ContextRepository(pool)
        result = await repo.create_todo(
            "task-1",
            "サブタスク",
            0,
            parent_todo_id=1,
        )

        call_args = conn.fetchrow.call_args[0]
        assert 1 in call_args


class TestGetTodos:
    """get_todos のテスト"""

    async def test_get_all_todos(self):
        """タスクの全Todoを取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = ContextRepository(pool)
        result = await repo.get_todos("task-1")

        assert len(result) == 3

    async def test_get_root_todos_only(self):
        """ルートレベルのTodoのみを取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = ContextRepository(pool)
        await repo.get_todos("task-1", include_all=False)

        # parent_todo_id IS NULL の条件で取得する
        call_args = conn.fetch.call_args[0]
        assert any("parent_todo_id" in str(a) for a in call_args)


class TestUpdateTodoStatus:
    """update_todo_status のテスト"""

    async def test_update_to_completed(self):
        """Todoをcompletedに更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "status": "completed"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.update_todo_status(1, "completed")

        assert result is not None
        assert result["status"] == "completed"

    async def test_update_to_in_progress(self):
        """Todoをin-progressに更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "status": "in-progress"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = ContextRepository(pool)
        result = await repo.update_todo_status(1, "in-progress")

        assert result is not None

    async def test_returns_none_when_not_found(self):
        """対象Todoが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = ContextRepository(pool)
        result = await repo.update_todo_status(9999, "completed")

        assert result is None


class TestDeleteTodo:
    """delete_todo のテスト"""

    async def test_delete_existing_todo(self):
        """存在するTodoを削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = ContextRepository(pool)
        result = await repo.delete_todo(1)

        assert result is True

    async def test_delete_nonexistent_todo(self):
        """存在しないTodoを削除しようとした場合にFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = ContextRepository(pool)
        result = await repo.delete_todo(9999)

        assert result is False
