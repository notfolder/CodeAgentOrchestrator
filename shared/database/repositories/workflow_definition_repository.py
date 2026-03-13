"""
ワークフロー定義リポジトリ

workflow_definitionsテーブルへのCRUD操作を提供する。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class WorkflowDefinitionRepository:
    """
    ワークフロー定義リポジトリクラス

    workflow_definitionsテーブルへのCRUD操作を提供する。
    graph_definition・agent_definition・prompt_definition はJSONBとして管理する。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    async def create_workflow_definition(
        self,
        name: str,
        display_name: str,
        graph_definition: dict[str, Any],
        agent_definition: dict[str, Any],
        prompt_definition: dict[str, Any],
        *,
        description: str | None = None,
        is_preset: bool = False,
        created_by: str | None = None,
        version: str = "1.0.0",
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        ワークフロー定義を作成する。

        Args:
            name: ワークフロー定義名（一意）
            display_name: 表示用ワークフロー名
            graph_definition: グラフ定義（JSONB）
            agent_definition: エージェント定義（JSONB）
            prompt_definition: プロンプト定義（JSONB）
            description: ワークフロー説明
            is_preset: システムプリセットフラグ
            created_by: 作成者メールアドレス
            version: 定義バージョン
            is_active: 有効状態

        Returns:
            作成したワークフロー定義のレコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一名称の定義が既に存在する場合
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO workflow_definitions (
                    name, display_name, description, is_preset, created_by,
                    graph_definition, agent_definition, prompt_definition,
                    version, is_active
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6::jsonb, $7::jsonb, $8::jsonb,
                    $9, $10
                )
                RETURNING *
                """,
                name,
                display_name,
                description,
                is_preset,
                created_by.lower() if created_by else None,
                json.dumps(graph_definition),
                json.dumps(agent_definition),
                json.dumps(prompt_definition),
                version,
                is_active,
            )
        return dict(row)

    async def get_workflow_definition(self, workflow_id: int) -> dict[str, Any] | None:
        """
        IDでワークフロー定義を取得する。

        Args:
            workflow_id: ワークフロー定義ID

        Returns:
            ワークフロー定義レコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_definitions WHERE id = $1",
                workflow_id,
            )
        return dict(row) if row else None

    async def get_workflow_definition_by_name(self, name: str) -> dict[str, Any] | None:
        """
        名前でワークフロー定義を取得する。

        Args:
            name: ワークフロー定義名

        Returns:
            ワークフロー定義レコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_definitions WHERE name = $1",
                name,
            )
        return dict(row) if row else None

    async def update_workflow_definition(
        self,
        workflow_id: int,
        *,
        display_name: str | None = None,
        description: str | None = None,
        graph_definition: dict[str, Any] | None = None,
        agent_definition: dict[str, Any] | None = None,
        prompt_definition: dict[str, Any] | None = None,
        version: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        """
        ワークフロー定義を更新する。

        is_preset=true の定義は更新できない。

        Args:
            workflow_id: ワークフロー定義ID
            display_name: 新しい表示名
            description: 新しい説明
            graph_definition: 新しいグラフ定義（JSONB）
            agent_definition: 新しいエージェント定義（JSONB）
            prompt_definition: 新しいプロンプト定義（JSONB）
            version: 新しいバージョン
            is_active: 新しい有効状態

        Returns:
            更新後のワークフロー定義レコード辞書。
            対象が存在しない場合、またはis_preset=trueの場合はNone。
        """
        fields: list[str] = []
        values: list[Any] = []
        idx = 1

        if display_name is not None:
            fields.append(f"display_name = ${idx}")
            values.append(display_name)
            idx += 1
        if description is not None:
            fields.append(f"description = ${idx}")
            values.append(description)
            idx += 1
        if graph_definition is not None:
            fields.append(f"graph_definition = ${idx}::jsonb")
            values.append(json.dumps(graph_definition))
            idx += 1
        if agent_definition is not None:
            fields.append(f"agent_definition = ${idx}::jsonb")
            values.append(json.dumps(agent_definition))
            idx += 1
        if prompt_definition is not None:
            fields.append(f"prompt_definition = ${idx}::jsonb")
            values.append(json.dumps(prompt_definition))
            idx += 1
        if version is not None:
            fields.append(f"version = ${idx}")
            values.append(version)
            idx += 1
        if is_active is not None:
            fields.append(f"is_active = ${idx}")
            values.append(is_active)
            idx += 1

        if not fields:
            return await self.get_workflow_definition(workflow_id)

        fields.append(f"updated_at = ${idx}")
        values.append(datetime.now(timezone.utc))
        idx += 1
        values.append(workflow_id)

        async with self._pool.acquire() as conn:
            # is_preset=true の定義は更新しない
            row = await conn.fetchrow(
                f"""
                UPDATE workflow_definitions
                SET {', '.join(fields)}
                WHERE id = ${idx} AND is_preset = false
                RETURNING *
                """,
                *values,
            )
        return dict(row) if row else None

    async def delete_workflow_definition(self, workflow_id: int) -> bool:
        """
        ワークフロー定義を削除する。

        is_preset=true の定義は削除できない。

        Args:
            workflow_id: ワークフロー定義ID

        Returns:
            削除に成功した場合はTrue、対象が存在しない・is_preset=trueの場合はFalse。
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM workflow_definitions WHERE id = $1 AND is_preset = false",
                workflow_id,
            )
        return result == "DELETE 1"

    async def list_workflow_definitions(
        self,
        *,
        is_preset: bool | None = None,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        ワークフロー定義一覧を取得する。

        Args:
            is_preset: プリセットフラグでフィルタリング
            created_by: 作成者メールアドレスでフィルタリング
            is_active: 有効状態でフィルタリング
            limit: 取得件数上限
            offset: 取得開始位置

        Returns:
            ワークフロー定義レコード辞書のリスト（作成日時降順）
        """
        conditions: list[str] = []
        values: list[Any] = []
        idx = 1

        if is_preset is not None:
            conditions.append(f"is_preset = ${idx}")
            values.append(is_preset)
            idx += 1
        if created_by is not None:
            conditions.append(f"created_by = ${idx}")
            values.append(created_by.lower())
            idx += 1
        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            values.append(is_active)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM workflow_definitions
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *values,
            )
        return [dict(row) for row in rows]
