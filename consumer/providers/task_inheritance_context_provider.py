"""
タスク継承コンテキストProvider

同一Issue/MRの過去タスクから継承データを取得し、
Markdown形式でエージェントへコンテキストとして提供するカスタムContextProvider。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from consumer.providers.planning_context_provider import BaseContextProvider

logger = logging.getLogger(__name__)


class TaskInheritanceContextProvider(BaseContextProvider):
    """
    タスク継承コンテキストProviderクラス。

    tasksテーブルから同一task_identifier・repositoryを持つ成功済みタスクを検索し、
    そのmetadata内のinheritance_dataをMarkdown形式に整形してエージェントへ提供する。
    disable_inheritanceフラグが設定されている場合はコンテキスト注入をスキップする。

    Attributes:
        _pool: asyncpg接続プール
        _expiry_days: 過去タスクの検索期間（日数）
    """

    def __init__(
        self, db_pool: asyncpg.Pool, expiry_days: int = 30
    ) -> None:
        """
        TaskInheritanceContextProviderを初期化する。

        Args:
            db_pool: asyncpg接続プール
            expiry_days: 過去タスクを検索する期間（日数）
        """
        self._pool = db_pool
        self._expiry_days = expiry_days

    async def before_run(
        self, *, task_uuid: str, **kwargs: Any
    ) -> str | None:
        """
        エージェント実行前に過去タスクの継承データをMarkdown形式で返す。

        tasksテーブルから現在タスクのtask_identifier・repositoryを取得し、
        同一の値を持つ成功済み過去タスクの継承データを検索して返す。
        disable_inheritanceフラグがある場合・過去タスクがない場合はNoneを返す。

        Args:
            task_uuid: タスクUUID
            **kwargs: 追加引数（未使用）

        Returns:
            Markdown形式の継承データ文字列。スキップ条件を満たす場合はNone。
        """
        async with self._pool.acquire() as conn:
            task_row = await conn.fetchrow(
                "SELECT metadata FROM tasks WHERE task_uuid = $1",
                task_uuid,
            )

        if task_row is None:
            logger.warning("タスクが見つかりません: task_uuid=%s", task_uuid)
            return None

        # metadataからdisable_inheritanceとtask_identifier・repositoryを取得する
        metadata_raw = task_row["metadata"]
        if isinstance(metadata_raw, str):
            metadata: dict[str, Any] = json.loads(metadata_raw)
        elif metadata_raw is not None:
            metadata = dict(metadata_raw)
        else:
            metadata = {}

        # 継承無効化チェック
        if metadata.get("disable_inheritance", False):
            logger.debug(
                "継承が無効化されています: task_uuid=%s", task_uuid
            )
            return None

        task_identifier: str = metadata.get("task_identifier", "")
        repository: str = metadata.get("repository", "")

        if not task_identifier or not repository:
            logger.debug(
                "task_identifierまたはrepositoryが未設定です: task_uuid=%s",
                task_uuid,
            )
            return None

        # 過去の成功タスクを取得する
        past_task = await self._get_past_tasks_async(
            task_identifier, repository
        )
        if past_task is None:
            logger.debug(
                "継承対象の過去タスクなし: task_identifier=%s, repository=%s",
                task_identifier,
                repository,
            )
            return None

        # 継承データをmetadataから取得する
        past_metadata_raw = past_task.get("metadata")
        if isinstance(past_metadata_raw, str):
            past_metadata: dict[str, Any] = json.loads(past_metadata_raw)
        elif past_metadata_raw is not None:
            past_metadata = dict(past_metadata_raw)
        else:
            past_metadata = {}

        inheritance_data: dict[str, Any] = past_metadata.get(
            "inheritance_data", {}
        )
        if not inheritance_data:
            logger.debug(
                "inheritance_dataが空です: past_task_uuid=%s",
                past_task.get("task_uuid"),
            )
            return None

        return self._format_inheritance_data(inheritance_data)

    async def after_run(
        self, *, task_uuid: str, **kwargs: Any
    ) -> None:
        """
        エージェント実行後の処理（本Providerでは何もしない）。

        Args:
            task_uuid: タスクUUID
            **kwargs: 追加引数（未使用）
        """

    async def _get_past_tasks_async(
        self, task_identifier: str, repository: str
    ) -> dict[str, Any] | None:
        """
        同一task_identifier・repositoryを持つ成功済み過去タスクを取得する。

        expiry_days以内に完了し、エラーなしで完了したタスクを最大5件取得する。
        最新のcompleted_atを持つタスクを選択して返す。

        Args:
            task_identifier: タスク識別子（例: Issue IID）
            repository: リポジトリ名（例: owner/repo）

        Returns:
            選択された過去タスクの辞書。見つからない場合はNone。
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT task_uuid, metadata, completed_at
                FROM tasks
                WHERE task_identifier = $1
                  AND repository = $2
                  AND status = 'completed'
                  AND error_message IS NULL
                  AND created_at > NOW() - ($3 * INTERVAL '1 day')
                ORDER BY completed_at DESC
                LIMIT 5
                """,
                task_identifier,
                repository,
                self._expiry_days,
            )

        if not rows:
            return None

        # 最新のcompleted_atを持つタスクを返す（ORDER BY DESC LIMIT 5の先頭）
        return dict(rows[0])

    def _format_inheritance_data(
        self, inheritance_data: dict[str, Any]
    ) -> str:
        """
        継承データをMarkdown形式に整形する。

        Summary、Planning History、Successful Implementation Patterns、
        Key Technical Decisionsの各セクションを生成する。

        Args:
            inheritance_data: 継承データ辞書

        Returns:
            Markdown形式の整形済みテキスト
        """
        lines: list[str] = ["## Previous Task Context\n"]

        # Summary セクション
        final_summary = inheritance_data.get("final_summary", "")
        lines.append(f"### Summary\n{final_summary}\n")

        # Planning History セクション
        planning_history: list[dict[str, Any]] = inheritance_data.get(
            "planning_history", []
        )
        lines.append("### Planning History")
        for entry in planning_history:
            phase = entry.get("phase", "")
            node_id = entry.get("node_id", "")
            plan = entry.get("plan", "")
            created_at = entry.get("created_at", "")
            lines.append(
                f"- Phase: {phase}, Node: {node_id}, Plan: {plan}, "
                f"Created: {created_at}"
            )
        lines.append("")

        # Successful Implementation Patterns セクション
        implementation_patterns: list[dict[str, Any]] = (
            inheritance_data.get("implementation_patterns", [])
        )
        lines.append("### Successful Implementation Patterns")
        for pattern in implementation_patterns:
            pattern_type = pattern.get("pattern_type", "")
            description = pattern.get("description", "")
            lines.append(f"- {pattern_type}: {description}")
        lines.append("")

        # Key Technical Decisions セクション
        key_decisions: list[str] = inheritance_data.get("key_decisions", [])
        lines.append("### Key Technical Decisions")
        for decision in key_decisions:
            lines.append(f"- {decision}")
        lines.append("")

        return "\n".join(lines)
