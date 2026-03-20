"""
TokenUsageRepository の単体テスト

token_usageテーブルへのCRUD操作の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from database.repositories.token_usage_repository import TokenUsageRepository


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """asyncpg.Pool のモックを生成する"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


class TestRecordTokenUsage:
    """record_token_usage のテスト"""

    async def test_record_success(self):
        """トークン使用量を正常に記録できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "username": "testuser",
            "task_uuid": "task-1",
            "node_id": "code_generation",
            "model": "gpt-4o",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = TokenUsageRepository(pool)
        result = await repo.record_token_usage(
            "user@example.com",
            "task-1",
            "code_generation",
            "gpt-4o",
            100,
            50,
        )

        assert result["total_tokens"] == 150
        conn.fetchrow.assert_awaited_once()

    async def test_total_tokens_is_sum(self):
        """total_tokensがprompt+completionの合計として記録されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 1})

        repo = TokenUsageRepository(pool)
        await repo.record_token_usage(
            "user@example.com",
            "task-1",
            "node-1",
            "gpt-4o",
            200,
            300,
        )

        call_args = conn.fetchrow.call_args[0]
        # 合計トークン数 500 が引数に含まれることを確認する
        assert 500 in call_args

    async def test_username_is_normalized(self):
        """ユーザー名が小文字に正規化されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 1})

        repo = TokenUsageRepository(pool)
        await repo.record_token_usage(
            "UPPER@EXAMPLE.COM",
            "task-1",
            "node-1",
            "gpt-4o",
            100,
            50,
        )

        call_args = conn.fetchrow.call_args[0]
        assert "upper@example.com" in call_args


class TestGetUsageByTask:
    """get_usage_by_task のテスト"""

    async def test_returns_all_records_for_task(self):
        """タスクの全トークン使用量を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"id": 1, "node_id": "code_planning", "total_tokens": 100},
            {"id": 2, "node_id": "code_generation", "total_tokens": 500},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = TokenUsageRepository(pool)
        result = await repo.get_usage_by_task("task-1")

        assert len(result) == 2

    async def test_query_includes_task_uuid(self):
        """クエリにtask_uuidが含まれることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TokenUsageRepository(pool)
        await repo.get_usage_by_task("task-1")

        call_args = conn.fetch.call_args[0]
        assert "task-1" in call_args


class TestGetUsageByUser:
    """get_usage_by_user のテスト"""

    async def test_returns_records_for_user(self):
        """ユーザーのトークン使用量一覧を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [{"id": 1, "total_tokens": 300}]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = TokenUsageRepository(pool)
        result = await repo.get_usage_by_user("user@example.com")

        assert len(result) == 1

    async def test_supports_pagination(self):
        """ページネーションのlimitとoffsetをサポートすることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TokenUsageRepository(pool)
        await repo.get_usage_by_user("user@example.com", limit=10, offset=20)

        call_args = conn.fetch.call_args[0]
        assert 10 in call_args
        assert 20 in call_args


class TestGetTotalUsageByTask:
    """get_total_usage_by_task のテスト"""

    async def test_returns_aggregated_totals(self):
        """タスクのトークン使用量合計を取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={
            "prompt_tokens": 500,
            "completion_tokens": 300,
            "total_tokens": 800,
        })

        repo = TokenUsageRepository(pool)
        result = await repo.get_total_usage_by_task("task-1")

        assert result["prompt_tokens"] == 500
        assert result["completion_tokens"] == 300
        assert result["total_tokens"] == 800

    async def test_returns_zeros_when_no_records(self):
        """レコードが0件の場合に全て0を返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        })

        repo = TokenUsageRepository(pool)
        result = await repo.get_total_usage_by_task("task-1")

        assert result["total_tokens"] == 0


class TestGetTotalUsageByUser:
    """get_total_usage_by_user のテスト"""

    async def test_returns_aggregated_totals(self):
        """ユーザーのトークン使用量合計を取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
        })

        repo = TokenUsageRepository(pool)
        result = await repo.get_total_usage_by_user("user@example.com")

        assert result["total_tokens"] == 1500


class TestGetUsageByModel:
    """get_usage_by_model のテスト"""

    async def test_get_model_stats_for_task(self):
        """タスク別モデル統計を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"model": "gpt-4o", "call_count": 5, "total_tokens": 2000},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = TokenUsageRepository(pool)
        result = await repo.get_usage_by_model(task_uuid="task-1")

        assert len(result) == 1
        assert result[0]["model"] == "gpt-4o"

    async def test_get_model_stats_for_user(self):
        """ユーザー別モデル統計を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"model": "gpt-4o", "total_tokens": 5000},
            {"model": "gpt-3.5-turbo", "total_tokens": 1000},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = TokenUsageRepository(pool)
        result = await repo.get_usage_by_model(username="testuser")

        assert len(result) == 2

    async def test_get_all_model_stats(self):
        """フィルタなしで全モデル統計を取得できることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TokenUsageRepository(pool)
        await repo.get_usage_by_model()

        conn.fetch.assert_awaited_once()


class TestGetUsageByNode:
    """get_usage_by_node のテスト"""

    async def test_get_node_stats(self):
        """ノード別統計を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"node_id": "code_generation", "call_count": 3, "total_tokens": 1500},
            {"node_id": "code_planning", "call_count": 1, "total_tokens": 300},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = TokenUsageRepository(pool)
        result = await repo.get_usage_by_node("task-1")

        assert len(result) == 2
        assert result[0]["node_id"] == "code_generation"

    async def test_query_includes_task_uuid(self):
        """クエリにtask_uuidが含まれることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = TokenUsageRepository(pool)
        await repo.get_usage_by_node("task-1")

        call_args = conn.fetch.call_args[0]
        assert "task-1" in call_args
