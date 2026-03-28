"""
チャット履歴Provider

LLM会話履歴をPostgreSQLのcontext_messagesテーブルに永続化し、
Agent Frameworkへ提供するカスタムHistoryProvider。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import asyncpg
import tiktoken

if TYPE_CHECKING:
    from consumer.providers.context_compression_service import ContextCompressionService

logger = logging.getLogger(__name__)


def _count_tokens(content: str, model_name: str) -> int:
    """
    tiktokenを使用してテキストのトークン数を計算する。

    指定されたモデル名に対応するエンコーダを取得してトークン数を返す。
    モデル名が不明な場合はcl100k_baseフォールバックエンコーダを使用する。

    Args:
        content: トークン数を計算するテキスト
        model_name: エンコーダを選択するモデル名（例: "gpt-4o"）

    Returns:
        トークン数
    """
    try:
        enc = tiktoken.encoding_for_model(model_name)
    except KeyError:
        # 未知のモデル名の場合はcl100k_baseを使用する
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(content))


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
    メッセージ保存後にContextCompressionServiceを呼び出してトークン数を監視し、
    閾値超過時に自動圧縮を行う（CLASS_IMPLEMENTATION_SPEC.md § 4.1.5 手順5に準拠）。

    Attributes:
        _pool: asyncpg接続プール
        _compression_service: コンテキスト圧縮サービス（省略可能）
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        compression_service: "ContextCompressionService | None" = None,
    ) -> None:
        """
        PostgreSqlChatHistoryProviderを初期化する。

        Args:
            db_pool: asyncpg接続プール
            compression_service: コンテキスト圧縮サービス（省略時は圧縮なし）
        """
        self._pool = db_pool
        self._compression_service = compression_service

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
        トークン数はtiktokenを使用して計算する。kwargsのmodel_nameでエンコーダを選択し、
        未知のモデルの場合はcl100k_baseフォールバックを使用する。
        保存後、compression_serviceが設定されておりkwargsにusernameが含まれている場合は
        ContextCompressionService.check_and_compress_async()を呼び出してトークン数を監視する。
        （CLASS_IMPLEMENTATION_SPEC.md § 4.1.5 手順5に準拠）

        Args:
            session_id: タスクUUID（セッションID）
            messages: 保存するメッセージのリスト（role、contentを含む辞書）
            **kwargs: 追加引数。
                model_name（str）: トークン計算に使用するモデル名（デフォルト: "gpt-4o"）。
                username（str）: 含む場合にコンテキスト圧縮チェックを実行する。
        """
        task_uuid = session_id
        model_name: str = kwargs.get("model_name", "gpt-4o")  # type: ignore[assignment]

        async with self._pool.acquire() as conn:
            # 既存メッセージ数を取得して差分のみ処理する
            existing_count: int = await conn.fetchval(
                "SELECT COUNT(*) FROM context_messages WHERE task_uuid = $1",
                task_uuid,
            )

            # 新規メッセージのみを抽出する
            new_messages = messages[existing_count:]
            if not new_messages:
                logger.debug("新規メッセージなし: task_uuid=%s", task_uuid)
                return

            # 新規メッセージを順次INSERTする
            for i, msg in enumerate(new_messages):
                seq = existing_count + i
                content = msg.get("content", "")
                # tiktokenでトークン数を計算する
                tokens = _count_tokens(content, model_name)
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

        # コンテキスト圧縮チェックを実行する（CLASS_IMPLEMENTATION_SPEC.md § 4.1.5 手順5）
        # compression_serviceが設定されており、usernameが非空文字列で提供されている場合のみ実行する
        # None・空文字列・未指定の場合はすべてスキップする
        username: str | None = kwargs.get("username")
        if (
            self._compression_service is not None
            and isinstance(username, str)
            and username
        ):
            try:
                await self._compression_service.check_and_compress_async(
                    task_uuid, username
                )
            except Exception:
                # 圧縮失敗はログのみとして主処理を継続する
                logger.warning(
                    "コンテキスト圧縮チェック中にエラーが発生しました（無視して継続）: task_uuid=%s",
                    task_uuid,
                )
