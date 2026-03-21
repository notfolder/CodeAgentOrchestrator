"""
システム設定リポジトリ

system_settingsテーブルへのCRUD操作を提供する。
キー・バリュー形式でシステム全体の設定を管理する。
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class SystemSettingsRepository:
    """
    システム設定リポジトリクラス

    system_settingsテーブルへのCRUD操作を提供する。
    キー・バリュー形式でシステム全体の設定を保持する。

    Attributes:
        _pool: asyncpg接続プール
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    async def get(self, key: str) -> str | None:
        """
        指定キーの設定値を取得する。

        Args:
            key: 設定キー

        Returns:
            設定値文字列。キーが存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM system_settings WHERE key = $1",
                key,
            )
        if row is None:
            return None
        return str(row["value"])

    async def set(self, key: str, value: str) -> None:
        """
        指定キーの設定値を登録または更新する（UPSERT）。

        既存キーが存在する場合は value と updated_at を更新する。
        存在しない場合は新規挿入する。

        Args:
            key: 設定キー
            value: 設定値
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                """,
                key,
                value,
            )
        logger.debug("システム設定を更新しました: key=%s", key)

    async def get_all(self) -> dict[str, str]:
        """
        全設定をキー・バリュー辞書として取得する。

        Returns:
            全設定を格納した辞書 {key: value}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM system_settings")
        return {row["key"]: row["value"] for row in rows}
