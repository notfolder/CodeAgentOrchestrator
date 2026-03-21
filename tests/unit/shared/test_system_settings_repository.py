"""
SystemSettingsRepository の単体テスト

system_settingsテーブルへの get/set/get_all 操作の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from database.repositories.system_settings_repository import SystemSettingsRepository


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """asyncpg.Pool のモックを生成するヘルパー"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


class TestGet:
    """SystemSettingsRepository.get のテスト"""

    async def test_get_existing_key(self):
        """存在するキーの設定値を取得できることを検証する"""
        pool, conn = _make_pool()
        # fetchrow がレコードを返すように設定する
        row = {"value": "1"}
        conn.fetchrow = AsyncMock(return_value=row)

        repo = SystemSettingsRepository(pool)
        result = await repo.get("default_workflow_definition_id")

        assert result == "1"
        conn.fetchrow.assert_awaited_once_with(
            "SELECT value FROM system_settings WHERE key = $1",
            "default_workflow_definition_id",
        )

    async def test_get_nonexistent_key_returns_none(self):
        """存在しないキーを取得した場合は None が返ることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = SystemSettingsRepository(pool)
        result = await repo.get("nonexistent_key")

        assert result is None


class TestSet:
    """SystemSettingsRepository.set のテスト"""

    async def test_set_calls_upsert(self):
        """set() が正しくUPSERT SQLを実行することを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock()

        repo = SystemSettingsRepository(pool)
        await repo.set("default_workflow_definition_id", "2")

        # execute が1回呼ばれたことを確認する
        conn.execute.assert_awaited_once()
        call_args = conn.execute.call_args
        # SQLに UPSERT の ON CONFLICT 句が含まれることを確認する
        assert "ON CONFLICT" in call_args[0][0]
        # キーと値が正しく渡されることを確認する
        assert call_args[0][1] == "default_workflow_definition_id"
        assert call_args[0][2] == "2"


class TestGetAll:
    """SystemSettingsRepository.get_all のテスト"""

    async def test_get_all_returns_dict(self):
        """get_all() が全設定をdict形式で返すことを検証する"""
        pool, conn = _make_pool()
        # fetch が複数レコードを返すように設定する
        rows = [
            {"key": "default_workflow_definition_id", "value": "1"},
            {"key": "another_setting", "value": "foo"},
        ]
        conn.fetch = AsyncMock(return_value=rows)

        repo = SystemSettingsRepository(pool)
        result = await repo.get_all()

        assert result == {
            "default_workflow_definition_id": "1",
            "another_setting": "foo",
        }

    async def test_get_all_empty_table_returns_empty_dict(self):
        """テーブルが空の場合は空dictが返ることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = SystemSettingsRepository(pool)
        result = await repo.get_all()

        assert result == {}
