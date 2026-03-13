"""
チャット履歴Provider

LLM会話履歴をPostgreSQLのcontext_messagesテーブルに永続化し、
Agent Frameworkへ提供するカスタムHistoryProvider。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class BaseHistoryProvider(ABC):
    """
    会話履歴Providerの抽象基底クラス。

    Agent FrameworkのBaseHistoryProviderに相当する自前定義のABC。
    サブクラスはget_messagesおよびsave_messagesを実装する必要がある。
    """

    @abstractmethod
    async def get_messages(
        self, session_id: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """会話履歴を取得する。"""

    @abstractmethod
    async def save_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        """会話履歴を保存する。"""


class PostgreSqlChatHistoryProvider(BaseHistoryProvider):
    """
    PostgreSQL会話履歴Providerクラス。

    LLM会話履歴をPostgreSQLのcontext_messagesテーブルに永続化する。
    session_idをtask_uuidとして使用してメッセージを取得・保存する。

    Attributes:
        _pool: asyncpg接続プール
    """

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        """
        PostgreSqlChatHistoryProviderを初期化する。

        Args:
            db_pool: asyncpg接続プール
        """
        self._pool = db_pool

    async def get_messages(
        self, session_id: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """
        会話履歴をPostgreSQLから取得する。

        session_idをtask_uuidとして使用し、context_messagesテーブルから
        seq昇順で全メッセージを取得する。

        Args:
            session_id: タスクUUID（セッションID）
            **kwargs: 追加引数（未使用）

        Returns:
            role、content、tokensをキーとする辞書のリスト（seq昇順）
        """
        task_uuid = session_id
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, role, content, tokens
                FROM context_messages
                WHERE task_uuid = $1
                ORDER BY seq ASC
                """,
                task_uuid,
            )
        messages = [
            {
                "role": row["role"],
                "content": row["content"],
                "tokens": row["tokens"],
            }
            for row in rows
        ]
        logger.debug(
            "会話履歴取得完了: task_uuid=%s, 件数=%d", task_uuid, len(messages)
        )
        return messages

    async def save_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        """
        会話履歴をPostgreSQLに保存する。

        既存のメッセージ数を取得し、差分（新規追加分）のみをINSERTする。
        トークン数はlen(content.split()) * 1.3の近似値を使用する。

        Args:
            session_id: タスクUUID（セッションID）
            messages: 保存するメッセージのリスト（role、contentを含む辞書）
            **kwargs: 追加引数（未使用）
        """
        task_uuid = session_id

        async with self._pool.acquire() as conn:
            # 既存メッセージ数を取得して差分のみ処理する
            existing_count: int = await conn.fetchval(
                "SELECT COUNT(*) FROM context_messages WHERE task_uuid = $1",
                task_uuid,
            )

            # 新規メッセージのみを抽出する
            new_messages = messages[existing_count:]
            if not new_messages:
                logger.debug(
                    "新規メッセージなし: task_uuid=%s", task_uuid
                )
                return

            # 新規メッセージを順次INSERTする
            for i, msg in enumerate(new_messages):
                seq = existing_count + i
                content = msg.get("content", "")
                # tiktokenの代わりに単語数×1.3の近似値を使用する
                tokens = int(len(content.split()) * 1.3)
                await conn.execute(
                    """
                    INSERT INTO context_messages
                        (task_uuid, seq, role, content, tokens)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    task_uuid,
                    seq,
                    msg.get("role", "user"),
                    content,
                    tokens,
                )

        logger.info(
            "会話履歴保存完了: task_uuid=%s, 新規件数=%d",
            task_uuid,
            len(new_messages),
        )
