"""
プランニングコンテキストProvider

プランニング履歴をPostgreSQLのcontext_planning_historyテーブルに保存し、
Markdown形式でエージェントへ提供するカスタムContextProvider。
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class BaseContextProvider(ABC):
    """
    コンテキストProviderの抽象基底クラス。

    Agent FrameworkのBaseContextProviderに相当する自前定義のABC。
    サブクラスはbefore_runおよびafter_runを実装する必要がある。
    """

    @abstractmethod
    async def before_run(self, *, task_uuid: str, **kwargs: Any) -> str | None:
        """エージェント実行前にコンテキストを返す。"""

    @abstractmethod
    async def after_run(self, *, task_uuid: str, **kwargs: Any) -> None:
        """エージェント実行後にコンテキストを保存する。"""


class PlanningContextProvider(BaseContextProvider):
    """
    プランニングコンテキストProviderクラス。

    context_planning_historyテーブルからプランニング履歴を取得し、
    Markdown形式に整形してエージェントへ提供する。
    エージェント実行後は新たなプランニング結果をテーブルへ保存する。

    Attributes:
        _pool: asyncpg接続プール
    """

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        """
        PlanningContextProviderを初期化する。

        Args:
            db_pool: asyncpg接続プール
        """
        self._pool = db_pool

    async def before_run(
        self, *, task_uuid: str, **kwargs: Any
    ) -> str | None:
        """
        エージェント実行前にプランニング履歴をMarkdown形式で返す。

        context_planning_historyテーブルから対象タスクのプランニング履歴を
        作成日時昇順で取得し、Markdown形式に整形して返す。
        履歴が存在しない場合はNoneを返す。

        Args:
            task_uuid: タスクUUID
            **kwargs: 追加引数（未使用）

        Returns:
            Markdown形式のプランニング履歴文字列。データなしの場合はNone。
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT phase, node_id, plan, action_id, result
                FROM context_planning_history
                WHERE task_uuid = $1
                ORDER BY created_at ASC
                """,
                task_uuid,
            )

        if not rows:
            logger.debug(
                "プランニング履歴なし: task_uuid=%s", task_uuid
            )
            return None

        lines: list[str] = ["## プランニング履歴"]
        for row in rows:
            phase = row["phase"] or ""
            node_id = row["node_id"] or ""
            # planカラムはJSONBなのでdictまたはstrとして取得される
            plan_raw = row["plan"]
            if isinstance(plan_raw, str):
                plan_text = plan_raw
            elif plan_raw is not None:
                plan_text = json.dumps(plan_raw, ensure_ascii=False)
            else:
                plan_text = ""
            action_id = row["action_id"] or ""
            result = row["result"] or ""

            lines.append(f"\n### {phase} - {node_id}")
            lines.append(f"**計画**: {plan_text}")
            lines.append(f"**アクションID**: {action_id}")
            lines.append(f"**結果**: {result}")

        context_text = "\n".join(lines)
        logger.debug(
            "プランニング履歴取得完了: task_uuid=%s, 件数=%d",
            task_uuid,
            len(rows),
        )
        return context_text

    async def after_run(
        self,
        *,
        task_uuid: str,
        phase: str,
        node_id: str,
        plan: dict[str, Any] | None = None,
        action_id: str | None = None,
        result: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        エージェント実行後にプランニング結果をDBへ保存する。

        context_planning_historyテーブルにプランニング結果を1件INSERTする。
        planカラムはJSONB型のため、::jsonbキャストを使用する。

        Args:
            task_uuid: タスクUUID
            phase: 実行フェーズ（例: 'planning', 'execution', 'reflection'）
            node_id: ワークフローノードID
            plan: 計画データ（JSONB形式で保存）
            action_id: アクションID
            result: 実行結果テキスト
            **kwargs: 追加引数（未使用）
        """
        plan_json = json.dumps(plan, ensure_ascii=False) if plan is not None else None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO context_planning_history
                    (task_uuid, phase, node_id, plan, action_id, result)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                task_uuid,
                phase,
                node_id,
                plan_json,
                action_id,
                result,
            )

        logger.info(
            "プランニング履歴保存完了: task_uuid=%s, phase=%s, node_id=%s",
            task_uuid,
            phase,
            node_id,
        )
