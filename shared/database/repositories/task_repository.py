"""
タスクリポジトリ

tasksテーブルへのCRUD操作を提供する。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class TaskRepository:
    """
    タスクリポジトリクラス

    tasksテーブルへのCRUD操作を提供する。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    async def create_task(
        self,
        uuid: str,
        task_type: str,
        task_identifier: str,
        repository: str,
        user_email: str,
        *,
        workflow_definition_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        assigned_branches: dict[str, str] | None = None,
        selected_branch: str | None = None,
        status: str = "running",
    ) -> dict[str, Any]:
        """
        タスクを作成する。

        Args:
            uuid: タスクUUID
            task_type: タスク種別（'issue_to_mr' または 'mr_processing'）
            task_identifier: GitLab Issue/MR識別子
            repository: リポジトリ名（例: owner/repo）
            user_email: 処理ユーザーのメールアドレス
            workflow_definition_id: 使用するワークフロー定義ID
            metadata: タスクメタデータ（JSONB）
            assigned_branches: 並列コード生成時のブランチ割り当て（JSONB）
            selected_branch: レビュー後に選択されたブランチ名
            status: タスク状態（デフォルト: 'running'）

        Returns:
            作成したタスクのレコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一UUIDのタスクが既に存在する場合
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO tasks (
                    uuid, task_type, task_identifier, repository, user_email,
                    status, workflow_definition_id, metadata, assigned_branches, selected_branch
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10)
                RETURNING *
                """,
                uuid,
                task_type,
                task_identifier,
                repository,
                user_email.lower(),
                status,
                workflow_definition_id,
                json.dumps(metadata or {}),
                json.dumps(assigned_branches) if assigned_branches else None,
                selected_branch,
            )
        return dict(row)

    async def get_task(self, uuid: str) -> dict[str, Any] | None:
        """
        UUIDでタスクを取得する。

        Args:
            uuid: タスクUUID

        Returns:
            タスクレコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tasks WHERE uuid = $1",
                uuid,
            )
        return dict(row) if row else None

    async def update_task_status(
        self,
        uuid: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        """
        タスクのステータスを更新する。

        status='completed' の場合は completed_at も設定する。

        Args:
            uuid: タスクUUID
            status: 新しい状態（'running'/'completed'/'paused'/'failed'）
            error_message: エラーメッセージ（status='failed'の場合に設定）

        Returns:
            更新後のタスクレコード辞書。対象が存在しない場合はNone。
        """
        now = datetime.now(timezone.utc)
        completed_at = now if status == "completed" else None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE tasks
                SET status = $1,
                    error_message = $2,
                    completed_at = $3,
                    updated_at = $4
                WHERE uuid = $5
                RETURNING *
                """,
                status,
                error_message,
                completed_at,
                now,
                uuid,
            )
        return dict(row) if row else None

    async def update_task_metadata(
        self,
        uuid: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        タスクのメタデータを更新する。

        Args:
            uuid: タスクUUID
            metadata: 新しいメタデータ辞書（JSONB全体を置き換える）

        Returns:
            更新後のタスクレコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE tasks
                SET metadata = $1::jsonb,
                    updated_at = $2
                WHERE uuid = $3
                RETURNING *
                """,
                json.dumps(metadata),
                datetime.now(timezone.utc),
                uuid,
            )
        return dict(row) if row else None

    async def update_task_counters(
        self,
        uuid: str,
        *,
        total_messages: int | None = None,
        total_summaries: int | None = None,
        total_tool_calls: int | None = None,
        final_token_count: int | None = None,
    ) -> dict[str, Any] | None:
        """
        タスクのカウンター値を更新する。

        Args:
            uuid: タスクUUID
            total_messages: 総メッセージ数
            total_summaries: 総要約数
            total_tool_calls: 総ツール呼び出し数
            final_token_count: 最終トークン数

        Returns:
            更新後のタスクレコード辞書。対象が存在しない場合はNone。
        """
        fields: list[str] = []
        values: list[Any] = []
        idx = 1

        if total_messages is not None:
            fields.append(f"total_messages = ${idx}")
            values.append(total_messages)
            idx += 1
        if total_summaries is not None:
            fields.append(f"total_summaries = ${idx}")
            values.append(total_summaries)
            idx += 1
        if total_tool_calls is not None:
            fields.append(f"total_tool_calls = ${idx}")
            values.append(total_tool_calls)
            idx += 1
        if final_token_count is not None:
            fields.append(f"final_token_count = ${idx}")
            values.append(final_token_count)
            idx += 1

        if not fields:
            return await self.get_task(uuid)

        fields.append(f"updated_at = ${idx}")
        values.append(datetime.now(timezone.utc))
        idx += 1
        values.append(uuid)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE tasks SET {', '.join(fields)} WHERE uuid = ${idx} RETURNING *",
                *values,
            )
        return dict(row) if row else None

    async def update_assigned_branches(
        self,
        uuid: str,
        assigned_branches: dict[str, str],
    ) -> dict[str, Any] | None:
        """
        タスクの並列コード生成ブランチ割り当てを更新する。

        Args:
            uuid: タスクUUID
            assigned_branches: ブランチ割り当て辞書（キー: 戦略番号, 値: ブランチ名）

        Returns:
            更新後のタスクレコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE tasks
                SET assigned_branches = $1::jsonb,
                    updated_at = $2
                WHERE uuid = $3
                RETURNING *
                """,
                json.dumps(assigned_branches),
                datetime.now(timezone.utc),
                uuid,
            )
        return dict(row) if row else None

    async def update_selected_branch(
        self,
        uuid: str,
        selected_branch: str,
    ) -> dict[str, Any] | None:
        """
        タスクの選択ブランチ名を更新する。

        Args:
            uuid: タスクUUID
            selected_branch: 選択されたブランチ名

        Returns:
            更新後のタスクレコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE tasks
                SET selected_branch = $1,
                    updated_at = $2
                WHERE uuid = $3
                RETURNING *
                """,
                selected_branch,
                datetime.now(timezone.utc),
                uuid,
            )
        return dict(row) if row else None

    async def delete_task(self, uuid: str) -> bool:
        """
        タスクを削除する。

        CASCADE設定により、関連するコンテキスト・Todo・トークン使用量も削除される。

        Args:
            uuid: タスクUUID

        Returns:
            削除に成功した場合はTrue、対象が存在しない場合はFalse。
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM tasks WHERE uuid = $1",
                uuid,
            )
        return result == "DELETE 1"

    async def list_tasks(
        self,
        *,
        user_email: str | None = None,
        repository: str | None = None,
        status: str | None = None,
        task_identifier: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        タスク一覧を取得する。

        Args:
            user_email: ユーザーメールアドレスでフィルタリング
            repository: リポジトリ名でフィルタリング
            status: ステータスでフィルタリング
            task_identifier: タスク識別子でフィルタリング
            limit: 取得件数上限
            offset: 取得開始位置

        Returns:
            タスクレコード辞書のリスト（作成日時降順）
        """
        conditions: list[str] = []
        values: list[Any] = []
        idx = 1

        if user_email is not None:
            conditions.append(f"user_email = ${idx}")
            values.append(user_email.lower())
            idx += 1
        if repository is not None:
            conditions.append(f"repository = ${idx}")
            values.append(repository)
            idx += 1
        if status is not None:
            conditions.append(f"status = ${idx}")
            values.append(status)
            idx += 1
        if task_identifier is not None:
            conditions.append(f"task_identifier = ${idx}")
            values.append(task_identifier)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM tasks
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *values,
            )
        return [dict(row) for row in rows]

    async def delete_old_completed_tasks(self, retention_days: int = 30) -> int:
        """
        指定日数を超えた完了済みタスクを削除する。

        Args:
            retention_days: 保持日数（デフォルト: 30日）

        Returns:
            削除されたタスク件数
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM tasks
                WHERE status = 'completed'
                  AND completed_at < NOW() - ($1 || ' days')::INTERVAL
                """,
                str(retention_days),
            )
        # "DELETE N" 形式の結果から件数を取得する
        count_str = result.split()[-1] if result else "0"
        return int(count_str)
