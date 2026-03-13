"""
ワークフロー実行状態リポジトリ

workflow_execution_statesテーブルおよびdocker_environment_mappingsテーブルへの
CRUD操作を提供する。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class WorkflowExecutionStateRepository:
    """
    ワークフロー実行状態リポジトリクラス

    workflow_execution_statesテーブルおよびdocker_environment_mappingsテーブルへの
    CRUD操作を提供する。ワークフローの停止・再開処理で使用する。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    # ===========================
    # workflow_execution_states テーブル操作
    # ===========================

    async def create_execution_state(
        self,
        execution_id: str,
        task_uuid: str,
        current_node_id: str,
        *,
        workflow_definition_id: int | None = None,
        completed_nodes: list[str] | None = None,
        workflow_status: str = "running",
    ) -> dict[str, Any]:
        """
        ワークフロー実行状態を作成する。

        Args:
            execution_id: ワークフロー実行の一意識別子（UUID文字列）
            task_uuid: タスクUUID
            current_node_id: 実行中または次に実行するノードID
            workflow_definition_id: 使用中のワークフロー定義ID
            completed_nodes: 完了したノードIDのリスト
            workflow_status: 実行状態（'running'/'suspended'/'completed'/'failed'）

        Returns:
            作成したワークフロー実行状態レコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一execution_idが既に存在する場合
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO workflow_execution_states (
                    execution_id, task_uuid, workflow_definition_id,
                    current_node_id, completed_nodes, workflow_status
                ) VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6)
                RETURNING *
                """,
                execution_id,
                task_uuid,
                workflow_definition_id,
                current_node_id,
                json.dumps(completed_nodes or []),
                workflow_status,
            )
        return dict(row)

    async def get_execution_state(
        self,
        execution_id: str,
    ) -> dict[str, Any] | None:
        """
        execution_idでワークフロー実行状態を取得する。

        Args:
            execution_id: ワークフロー実行の一意識別子

        Returns:
            ワークフロー実行状態レコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_execution_states WHERE execution_id = $1::uuid",
                execution_id,
            )
        return dict(row) if row else None

    async def get_execution_state_by_task(
        self,
        task_uuid: str,
    ) -> dict[str, Any] | None:
        """
        task_uuidでワークフロー実行状態を取得する（最新の実行状態）。

        Args:
            task_uuid: タスクUUID

        Returns:
            ワークフロー実行状態レコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM workflow_execution_states
                WHERE task_uuid = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                task_uuid,
            )
        return dict(row) if row else None

    async def update_execution_state(
        self,
        execution_id: str,
        *,
        current_node_id: str | None = None,
        completed_nodes: list[str] | None = None,
        workflow_status: str | None = None,
        suspended_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        """
        ワークフロー実行状態を更新する。

        Args:
            execution_id: ワークフロー実行の一意識別子
            current_node_id: 新しい実行中ノードID
            completed_nodes: 新しい完了ノードIDリスト
            workflow_status: 新しい実行状態
            suspended_at: 停止日時（workflow_status='suspended'の場合に設定）

        Returns:
            更新後のワークフロー実行状態レコード辞書。対象が存在しない場合はNone。
        """
        fields: list[str] = []
        values: list[Any] = []
        idx = 1

        if current_node_id is not None:
            fields.append(f"current_node_id = ${idx}")
            values.append(current_node_id)
            idx += 1
        if completed_nodes is not None:
            fields.append(f"completed_nodes = ${idx}::jsonb")
            values.append(json.dumps(completed_nodes))
            idx += 1
        if workflow_status is not None:
            fields.append(f"workflow_status = ${idx}")
            values.append(workflow_status)
            idx += 1
        if suspended_at is not None:
            fields.append(f"suspended_at = ${idx}")
            values.append(suspended_at)
            idx += 1

        if not fields:
            return await self.get_execution_state(execution_id)

        fields.append(f"updated_at = ${idx}")
        values.append(datetime.now(timezone.utc))
        idx += 1
        values.append(execution_id)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE workflow_execution_states
                SET {', '.join(fields)}
                WHERE execution_id = ${idx}::uuid
                RETURNING *
                """,
                *values,
            )
        return dict(row) if row else None

    async def suspend_execution(
        self,
        execution_id: str,
        current_node_id: str,
        completed_nodes: list[str],
    ) -> dict[str, Any] | None:
        """
        ワークフロー実行を停止状態にする。

        Args:
            execution_id: ワークフロー実行の一意識別子
            current_node_id: 停止時のノードID
            completed_nodes: 完了済みノードIDリスト

        Returns:
            更新後のワークフロー実行状態レコード辞書。対象が存在しない場合はNone。
        """
        return await self.update_execution_state(
            execution_id,
            current_node_id=current_node_id,
            completed_nodes=completed_nodes,
            workflow_status="suspended",
            suspended_at=datetime.now(timezone.utc),
        )

    async def resume_execution(
        self,
        execution_id: str,
    ) -> dict[str, Any] | None:
        """
        ワークフロー実行を再開状態にする。

        Args:
            execution_id: ワークフロー実行の一意識別子

        Returns:
            更新後のワークフロー実行状態レコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE workflow_execution_states
                SET workflow_status = 'running',
                    suspended_at = NULL,
                    updated_at = $1
                WHERE execution_id = $2::uuid
                RETURNING *
                """,
                datetime.now(timezone.utc),
                execution_id,
            )
        return dict(row) if row else None

    async def list_suspended_executions(
        self,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        停止中のワークフロー実行状態を古い順に取得する。

        Args:
            limit: 取得件数上限

        Returns:
            停止中のワークフロー実行状態レコード辞書のリスト（suspended_at昇順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM workflow_execution_states
                WHERE workflow_status = 'suspended'
                ORDER BY suspended_at ASC
                LIMIT $1
                """,
                limit,
            )
        return [dict(row) for row in rows]

    async def delete_execution_state(self, execution_id: str) -> bool:
        """
        ワークフロー実行状態を削除する。

        CASCADE設定により、関連するdocker_environment_mappingsも削除される。

        Args:
            execution_id: ワークフロー実行の一意識別子

        Returns:
            削除に成功した場合はTrue、対象が存在しない場合はFalse。
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM workflow_execution_states WHERE execution_id = $1::uuid",
                execution_id,
            )
        return result == "DELETE 1"

    # ===========================
    # docker_environment_mappings テーブル操作
    # ===========================

    async def save_environment_mapping(
        self,
        mapping_id: str,
        execution_id: str,
        node_id: str,
        container_id: str,
        container_name: str,
        environment_name: str,
        *,
        status: str = "running",
    ) -> dict[str, Any]:
        """
        Docker環境マッピングを保存する。

        同一execution_id・node_idの組み合わせが既に存在する場合は更新する（UPSERT）。

        Args:
            mapping_id: マッピングの一意識別子（UUID文字列）
            execution_id: workflow_execution_statesへの外部キー
            node_id: ワークフローノードID
            container_id: DockerコンテナID
            container_name: Dockerコンテナ名
            environment_name: 環境名（'python'/'miniforge'/'node'/'default'）
            status: コンテナ状態（'running'/'stopped'）

        Returns:
            作成または更新したDocker環境マッピングレコード辞書
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO docker_environment_mappings (
                    mapping_id, execution_id, node_id,
                    container_id, container_name, environment_name, status
                ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
                ON CONFLICT (execution_id, node_id) DO UPDATE
                SET container_id = EXCLUDED.container_id,
                    container_name = EXCLUDED.container_name,
                    environment_name = EXCLUDED.environment_name,
                    status = EXCLUDED.status,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
                """,
                mapping_id,
                execution_id,
                node_id,
                container_id,
                container_name,
                environment_name,
                status,
            )
        return dict(row)

    async def get_environment_mapping(
        self,
        execution_id: str,
        node_id: str,
    ) -> dict[str, Any] | None:
        """
        execution_idとnode_idでDocker環境マッピングを取得する。

        Args:
            execution_id: ワークフロー実行の一意識別子
            node_id: ワークフローノードID

        Returns:
            Docker環境マッピングレコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM docker_environment_mappings
                WHERE execution_id = $1::uuid AND node_id = $2
                """,
                execution_id,
                node_id,
            )
        return dict(row) if row else None

    async def load_environment_mappings(
        self,
        execution_id: str,
    ) -> list[dict[str, Any]]:
        """
        execution_idに紐付く全Docker環境マッピングを取得する。

        Args:
            execution_id: ワークフロー実行の一意識別子

        Returns:
            Docker環境マッピングレコード辞書のリスト（作成日時昇順）
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM docker_environment_mappings
                WHERE execution_id = $1::uuid
                ORDER BY created_at ASC
                """,
                execution_id,
            )
        return [dict(row) for row in rows]

    async def update_environment_mapping_status(
        self,
        execution_id: str,
        node_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """
        Docker環境マッピングのコンテナ状態を更新する。

        Args:
            execution_id: ワークフロー実行の一意識別子
            node_id: ワークフローノードID
            status: 新しいコンテナ状態（'running'/'stopped'）

        Returns:
            更新後のDocker環境マッピングレコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE docker_environment_mappings
                SET status = $1,
                    updated_at = $2
                WHERE execution_id = $3::uuid AND node_id = $4
                RETURNING *
                """,
                status,
                datetime.now(timezone.utc),
                execution_id,
                node_id,
            )
        return dict(row) if row else None

    async def delete_environment_mappings(self, execution_id: str) -> int:
        """
        execution_idに紐付く全Docker環境マッピングを削除する。

        Args:
            execution_id: ワークフロー実行の一意識別子

        Returns:
            削除されたマッピング件数
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM docker_environment_mappings WHERE execution_id = $1::uuid",
                execution_id,
            )
        count_str = result.split()[-1] if result else "0"
        return int(count_str)
