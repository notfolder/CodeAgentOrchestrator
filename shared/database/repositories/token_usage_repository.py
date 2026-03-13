"""
トークン使用量リポジトリ

token_usageテーブルへの操作を提供する。
TokenUsageMiddlewareが使用する。
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class TokenUsageRepository:
    """
    トークン使用量リポジトリクラス

    token_usageテーブルへの操作を提供する。
    ユーザー別・タスク別・ノード別のトークン使用量の記録と集計を行う。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    async def record_token_usage(
        self,
        user_email: str,
        task_uuid: str,
        node_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> dict[str, Any]:
        """
        トークン使用量を記録する。

        total_tokens は prompt_tokens + completion_tokens として自動計算する。

        Args:
            user_email: ユーザーメールアドレス
            task_uuid: タスクUUID
            node_id: ワークフローノードID
            model: 使用モデル名（例: 'gpt-4o'）
            prompt_tokens: 入力プロンプトのトークン数
            completion_tokens: 生成出力のトークン数

        Returns:
            作成したトークン使用量レコード辞書
        """
        total_tokens = prompt_tokens + completion_tokens

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO token_usage (
                    user_email, task_uuid, node_id, model,
                    prompt_tokens, completion_tokens, total_tokens
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                user_email.lower(),
                task_uuid,
                node_id,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
        return dict(row)

    async def get_usage_by_task(
        self,
        task_uuid: str,
    ) -> list[dict[str, Any]]:
        """
        タスク別のトークン使用量一覧を取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            トークン使用量レコード辞書のリスト（作成日時昇順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM token_usage
                WHERE task_uuid = $1
                ORDER BY created_at ASC
                """,
                task_uuid,
            )
        return [dict(row) for row in rows]

    async def get_usage_by_user(
        self,
        user_email: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        ユーザー別のトークン使用量一覧を取得する（最新順）。

        Args:
            user_email: ユーザーメールアドレス
            limit: 取得件数上限
            offset: 取得開始位置

        Returns:
            トークン使用量レコード辞書のリスト（作成日時降順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM token_usage
                WHERE user_email = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_email.lower(),
                limit,
                offset,
            )
        return [dict(row) for row in rows]

    async def get_total_usage_by_task(
        self,
        task_uuid: str,
    ) -> dict[str, int]:
        """
        タスクのトークン使用量合計を取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            合計トークン数の辞書（prompt_tokens, completion_tokens, total_tokens）
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM token_usage
                WHERE task_uuid = $1
                """,
                task_uuid,
            )
        return {
            "prompt_tokens": int(row["prompt_tokens"]),
            "completion_tokens": int(row["completion_tokens"]),
            "total_tokens": int(row["total_tokens"]),
        }

    async def get_total_usage_by_user(
        self,
        user_email: str,
    ) -> dict[str, int]:
        """
        ユーザーのトークン使用量合計を取得する。

        Args:
            user_email: ユーザーメールアドレス

        Returns:
            合計トークン数の辞書（prompt_tokens, completion_tokens, total_tokens）
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM token_usage
                WHERE user_email = $1
                """,
                user_email.lower(),
            )
        return {
            "prompt_tokens": int(row["prompt_tokens"]),
            "completion_tokens": int(row["completion_tokens"]),
            "total_tokens": int(row["total_tokens"]),
        }

    async def get_usage_by_model(
        self,
        *,
        task_uuid: str | None = None,
        user_email: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        モデル別のトークン使用量集計を取得する。

        Args:
            task_uuid: タスクUUIDでフィルタリング
            user_email: ユーザーメールアドレスでフィルタリング

        Returns:
            モデル別集計レコードのリスト（total_tokens降順）
        """
        conditions: list[str] = []
        values: list[Any] = []
        idx = 1

        if task_uuid is not None:
            conditions.append(f"task_uuid = ${idx}")
            values.append(task_uuid)
            idx += 1
        if user_email is not None:
            conditions.append(f"user_email = ${idx}")
            values.append(user_email.lower())
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    model,
                    COUNT(*) AS call_count,
                    SUM(prompt_tokens) AS prompt_tokens,
                    SUM(completion_tokens) AS completion_tokens,
                    SUM(total_tokens) AS total_tokens
                FROM token_usage
                {where_clause}
                GROUP BY model
                ORDER BY total_tokens DESC
                """,
                *values,
            )
        return [dict(row) for row in rows]

    async def get_usage_by_node(
        self,
        task_uuid: str,
    ) -> list[dict[str, Any]]:
        """
        ノード別のトークン使用量集計を取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            ノード別集計レコードのリスト（total_tokens降順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    node_id,
                    COUNT(*) AS call_count,
                    SUM(prompt_tokens) AS prompt_tokens,
                    SUM(completion_tokens) AS completion_tokens,
                    SUM(total_tokens) AS total_tokens
                FROM token_usage
                WHERE task_uuid = $1
                GROUP BY node_id
                ORDER BY total_tokens DESC
                """,
                task_uuid,
            )
        return [dict(row) for row in rows]
