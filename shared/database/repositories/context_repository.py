"""
コンテキストリポジトリ

コンテキストストレージ関連テーブル（context_messages, message_compressions,
context_planning_history, context_metadata, context_tool_results_metadata, todos）
へのCRUD操作を提供する。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class ContextRepository:
    """
    コンテキストリポジトリクラス

    コンテキストストレージ関連テーブルへのCRUD操作を提供する。
    PostgreSqlChatHistoryProvider、PlanningContextProvider、
    ToolResultContextProvider、ContextCompressionService が使用する。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    # ===========================
    # context_messages テーブル操作
    # ===========================

    async def add_message(
        self,
        task_uuid: str,
        seq: int,
        role: str,
        content: str,
        *,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tokens: int | None = None,
        is_compressed_summary: bool = False,
        compressed_range: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """
        会話メッセージを追加する。

        Args:
            task_uuid: タスクUUID
            seq: シーケンス番号（0から開始）
            role: ロール（'system'/'user'/'assistant'/'tool'）
            content: メッセージ内容
            tool_call_id: ツール呼び出しID（roleが'tool'の場合）
            tool_name: ツール名（roleが'tool'の場合）
            tokens: トークン数
            is_compressed_summary: 圧縮要約フラグ
            compressed_range: 圧縮されたメッセージ範囲（例: {"start_seq": 0, "end_seq": 10}）

        Returns:
            作成したメッセージのレコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一task_uuid・seqの組み合わせが既に存在する場合
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO context_messages (
                    task_uuid, seq, role, content,
                    tool_call_id, tool_name, tokens,
                    is_compressed_summary, compressed_range
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                RETURNING *
                """,
                task_uuid,
                seq,
                role,
                content,
                tool_call_id,
                tool_name,
                tokens,
                is_compressed_summary,
                json.dumps(compressed_range) if compressed_range else None,
            )
        return dict(row)

    async def get_messages(
        self,
        task_uuid: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        タスクの会話履歴を時系列順に取得する。

        Args:
            task_uuid: タスクUUID
            limit: 取得件数上限（Noneの場合は全件）
            offset: 取得開始位置

        Returns:
            メッセージレコード辞書のリスト（seq昇順）
        """
        if limit is not None:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_messages
                    WHERE task_uuid = $1
                    ORDER BY seq ASC
                    LIMIT $2 OFFSET $3
                    """,
                    task_uuid,
                    limit,
                    offset,
                )
        else:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_messages
                    WHERE task_uuid = $1
                    ORDER BY seq ASC
                    OFFSET $2
                    """,
                    task_uuid,
                    offset,
                )
        return [dict(row) for row in rows]

    async def get_latest_messages(
        self,
        task_uuid: str,
        count: int,
    ) -> list[dict[str, Any]]:
        """
        タスクの最新N件のメッセージを取得する。

        Args:
            task_uuid: タスクUUID
            count: 取得件数

        Returns:
            メッセージレコード辞書のリスト（seq昇順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM (
                    SELECT * FROM context_messages
                    WHERE task_uuid = $1
                    ORDER BY seq DESC
                    LIMIT $2
                ) sub
                ORDER BY seq ASC
                """,
                task_uuid,
                count,
            )
        return [dict(row) for row in rows]

    async def delete_messages_in_range(
        self,
        task_uuid: str,
        start_seq: int,
        end_seq: int,
    ) -> int:
        """
        指定seq範囲のメッセージを削除する（圧縮時の古いメッセージ削除）。

        Args:
            task_uuid: タスクUUID
            start_seq: 削除開始seq（含む）
            end_seq: 削除終了seq（含む）

        Returns:
            削除したメッセージ件数
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM context_messages
                WHERE task_uuid = $1 AND seq >= $2 AND seq <= $3
                """,
                task_uuid,
                start_seq,
                end_seq,
            )
        count_str = result.split()[-1] if result else "0"
        return int(count_str)

    async def get_message_count(self, task_uuid: str) -> int:
        """
        タスクのメッセージ件数を取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            メッセージ件数
        """
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM context_messages WHERE task_uuid = $1",
                task_uuid,
            )
        return int(count or 0)

    async def get_total_tokens(self, task_uuid: str) -> int:
        """
        タスクの全メッセージのトータルトークン数を取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            トータルトークン数
        """
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COALESCE(SUM(tokens), 0) FROM context_messages WHERE task_uuid = $1",
                task_uuid,
            )
        return int(total or 0)

    # ===========================
    # message_compressions テーブル操作
    # ===========================

    async def add_message_compression(
        self,
        task_uuid: str,
        start_seq: int,
        end_seq: int,
        summary_seq: int,
        original_token_count: int,
        compressed_token_count: int,
        *,
        compression_ratio: float | None = None,
    ) -> dict[str, Any]:
        """
        メッセージ圧縮履歴を記録する。

        Args:
            task_uuid: タスクUUID
            start_seq: 圧縮開始seq
            end_seq: 圧縮終了seq
            summary_seq: 要約メッセージのseq
            original_token_count: 圧縮前トークン数
            compressed_token_count: 圧縮後トークン数
            compression_ratio: 圧縮率（compressed/original）

        Returns:
            作成した圧縮履歴レコード辞書
        """
        ratio = compression_ratio
        if ratio is None and original_token_count > 0:
            ratio = compressed_token_count / original_token_count

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO message_compressions (
                    task_uuid, start_seq, end_seq, summary_seq,
                    original_token_count, compressed_token_count, compression_ratio
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                task_uuid,
                start_seq,
                end_seq,
                summary_seq,
                original_token_count,
                compressed_token_count,
                ratio,
            )
        return dict(row)

    async def get_compression_history(
        self,
        task_uuid: str,
    ) -> list[dict[str, Any]]:
        """
        タスクのメッセージ圧縮履歴を取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            圧縮履歴レコード辞書のリスト（作成日時降順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM message_compressions
                WHERE task_uuid = $1
                ORDER BY created_at DESC
                """,
                task_uuid,
            )
        return [dict(row) for row in rows]

    # ===========================
    # context_planning_history テーブル操作
    # ===========================

    async def add_planning_history(
        self,
        task_uuid: str,
        phase: str,
        node_id: str,
        *,
        plan: dict[str, Any] | None = None,
        action_id: str | None = None,
        result: str | None = None,
    ) -> dict[str, Any]:
        """
        プランニング履歴を追加する。

        Args:
            task_uuid: タスクUUID
            phase: フェーズ（'planning'/'execution'/'reflection'）
            node_id: 実行ノードID
            plan: 計画データ（JSONB）
            action_id: アクションID（executionフェーズの場合）
            result: 実行結果またはリフレクション結果

        Returns:
            作成したプランニング履歴レコード辞書
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO context_planning_history (
                    task_uuid, phase, node_id, plan, action_id, result
                ) VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                RETURNING *
                """,
                task_uuid,
                phase,
                node_id,
                json.dumps(plan) if plan else None,
                action_id,
                result,
            )
        return dict(row)

    async def get_planning_history(
        self,
        task_uuid: str,
        *,
        phase: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        タスクのプランニング履歴を取得する。

        Args:
            task_uuid: タスクUUID
            phase: フェーズでフィルタリング（Noneの場合は全フェーズ取得）

        Returns:
            プランニング履歴レコード辞書のリスト（作成日時昇順）
        """
        if phase is not None:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_planning_history
                    WHERE task_uuid = $1 AND phase = $2
                    ORDER BY created_at ASC
                    """,
                    task_uuid,
                    phase,
                )
        else:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_planning_history
                    WHERE task_uuid = $1
                    ORDER BY created_at ASC
                    """,
                    task_uuid,
                )
        return [dict(row) for row in rows]

    # ===========================
    # context_metadata テーブル操作
    # ===========================

    async def create_context_metadata(
        self,
        task_uuid: str,
        task_type: str,
        task_identifier: str,
        repository: str,
        user_email: str,
        *,
        workflow_name: str | None = None,
    ) -> dict[str, Any]:
        """
        コンテキストメタデータを作成する。

        Args:
            task_uuid: タスクUUID
            task_type: タスク種別
            task_identifier: GitLab Issue/MR識別子
            repository: リポジトリ名
            user_email: ユーザーメールアドレス
            workflow_name: 使用ワークフロー名

        Returns:
            作成したコンテキストメタデータレコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一task_uuidのメタデータが既に存在する場合
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO context_metadata (
                    task_uuid, task_type, task_identifier, repository,
                    user_email, workflow_name
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                task_uuid,
                task_type,
                task_identifier,
                repository,
                user_email.lower(),
                workflow_name,
            )
        return dict(row)

    async def get_context_metadata(self, task_uuid: str) -> dict[str, Any] | None:
        """
        タスクのコンテキストメタデータを取得する。

        Args:
            task_uuid: タスクUUID

        Returns:
            コンテキストメタデータレコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM context_metadata WHERE task_uuid = $1",
                task_uuid,
            )
        return dict(row) if row else None

    async def update_context_metadata(
        self,
        task_uuid: str,
        *,
        workflow_name: str | None = None,
    ) -> dict[str, Any] | None:
        """
        コンテキストメタデータを更新する。

        Args:
            task_uuid: タスクUUID
            workflow_name: 新しいワークフロー名

        Returns:
            更新後のコンテキストメタデータレコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE context_metadata
                SET workflow_name = COALESCE($1, workflow_name),
                    updated_at = $2
                WHERE task_uuid = $3
                RETURNING *
                """,
                workflow_name,
                datetime.now(timezone.utc),
                task_uuid,
            )
        return dict(row) if row else None

    # ===========================
    # context_tool_results_metadata テーブル操作
    # ===========================

    async def add_tool_result_metadata(
        self,
        task_uuid: str,
        tool_name: str,
        file_path: str,
        file_size: int,
        *,
        tool_command: str | None = None,
        success: bool = True,
    ) -> dict[str, Any]:
        """
        ツール実行結果のメタデータを追加する。

        実際のツール実行結果はファイルシステムに保存し、
        本テーブルにはメタデータのみを記録する。

        Args:
            task_uuid: タスクUUID
            tool_name: ツール名（例: 'text_editor', 'command_executor'）
            file_path: ファイルストレージパス
            file_size: ファイルサイズ（バイト）
            tool_command: ツールコマンド（例: 'view', 'execute_command'）
            success: 実行成功フラグ

        Returns:
            作成したツール結果メタデータレコード辞書
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO context_tool_results_metadata (
                    task_uuid, tool_name, tool_command, file_path, file_size, success
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                task_uuid,
                tool_name,
                tool_command,
                file_path,
                file_size,
                success,
            )
        return dict(row)

    async def get_tool_result_metadata(
        self,
        task_uuid: str,
        *,
        tool_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        タスクのツール実行結果メタデータを取得する。

        Args:
            task_uuid: タスクUUID
            tool_name: ツール名でフィルタリング（Noneの場合は全ツール取得）
            limit: 取得件数上限

        Returns:
            ツール実行結果メタデータレコード辞書のリスト（作成日時降順）
        """
        if tool_name is not None:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_tool_results_metadata
                    WHERE task_uuid = $1 AND tool_name = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    task_uuid,
                    tool_name,
                    limit,
                )
        else:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_tool_results_metadata
                    WHERE task_uuid = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    task_uuid,
                    limit,
                )
        return [dict(row) for row in rows]

    # ===========================
    # todos テーブル操作
    # ===========================

    async def create_todo(
        self,
        task_uuid: str,
        title: str,
        order_index: int,
        *,
        todo_id: int | None = None,
        parent_todo_id: int | None = None,
        description: str | None = None,
        status: str = "not-started",
    ) -> dict[str, Any]:
        """
        Todoを作成する。

        Args:
            task_uuid: タスクUUID
            title: Todoタイトル
            order_index: 表示順序
            todo_id: GitLab TodoID（外部システムとの対応）
            parent_todo_id: 親TodoID（階層構造用）
            description: Todo詳細説明
            status: 初期状態（デフォルト: 'not-started'）

        Returns:
            作成したTodoレコード辞書
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO todos (
                    task_uuid, todo_id, parent_todo_id, title,
                    description, status, order_index
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                task_uuid,
                todo_id,
                parent_todo_id,
                title,
                description,
                status,
                order_index,
            )
        return dict(row)

    async def get_todos(
        self,
        task_uuid: str,
        *,
        parent_todo_id: int | None = None,
        include_all: bool = True,
    ) -> list[dict[str, Any]]:
        """
        タスクのTodoリストを取得する。

        Args:
            task_uuid: タスクUUID
            parent_todo_id: 親TodoIDでフィルタリング（Noneかつinclude_all=FalseでルートTodoのみ）
            include_all: Trueの場合は全Todoを取得する（parent_todo_idは無視される）

        Returns:
            Todoレコード辞書のリスト（order_index昇順）
        """
        if include_all:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM todos
                    WHERE task_uuid = $1
                    ORDER BY order_index ASC
                    """,
                    task_uuid,
                )
        elif parent_todo_id is not None:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM todos
                    WHERE task_uuid = $1 AND parent_todo_id = $2
                    ORDER BY order_index ASC
                    """,
                    task_uuid,
                    parent_todo_id,
                )
        else:
            # ルートレベルのTodoのみ取得する
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM todos
                    WHERE task_uuid = $1 AND parent_todo_id IS NULL
                    ORDER BY order_index ASC
                    """,
                    task_uuid,
                )
        return [dict(row) for row in rows]

    async def update_todo_status(
        self,
        todo_id: int,
        status: str,
    ) -> dict[str, Any] | None:
        """
        TodoのステータスをID（内部ID）で更新する。

        status='completed' の場合は completed_at も設定する。

        Args:
            todo_id: TodoID（内部ID）
            status: 新しい状態（'not-started'/'in-progress'/'completed'/'failed'）

        Returns:
            更新後のTodoレコード辞書。対象が存在しない場合はNone。
        """
        now = datetime.now(timezone.utc)
        completed_at = now if status == "completed" else None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE todos
                SET status = $1,
                    completed_at = $2,
                    updated_at = $3
                WHERE id = $4
                RETURNING *
                """,
                status,
                completed_at,
                now,
                todo_id,
            )
        return dict(row) if row else None

    async def delete_todo(self, todo_id: int) -> bool:
        """
        TodoをID（内部ID）で削除する。

        CASCADE設定により、子Todoも削除される。

        Args:
            todo_id: TodoID（内部ID）

        Returns:
            削除に成功した場合はTrue、対象が存在しない場合はFalse。
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM todos WHERE id = $1",
                todo_id,
            )
        return result == "DELETE 1"
