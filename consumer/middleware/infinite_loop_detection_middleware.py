"""
InfiniteLoopDetectionMiddleware モジュール

ワークフロー実行中の無限ループを検出し、異常な繰り返し実行を防止する
Middleware を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 5.5（InfiniteLoopDetectionMiddleware）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from consumer.middleware.i_middleware import IMiddleware, MiddlewareSignal, WorkflowNode

if TYPE_CHECKING:
    from consumer.agents.configurable_agent import WorkflowContext

logger = logging.getLogger(__name__)

# config.yaml に middleware セクションが存在しないため、デフォルト値を使用する
_DEFAULT_MAX_NODE_VISITS = 10


class InfiniteLoopDetectionMiddleware(IMiddleware):
    """
    無限ループ検出 Middleware

    ノード実行前に各ノードへの訪問回数をチェックし、
    設定された上限を超えた場合に中断シグナルを返す。

    Attributes:
        max_node_visits: 各ノードへの最大到達回数
        node_visit_counts: ノードID → 到達回数のマッピング
    """

    def __init__(self, max_node_visits: int = _DEFAULT_MAX_NODE_VISITS) -> None:
        """
        初期化

        Args:
            max_node_visits: 各ノードへの最大到達回数
                             config.yaml の middleware.max_node_visits から取得することを推奨する
        """
        self.max_node_visits = max_node_visits
        # ノードID → 到達回数のマッピング（タスクごとに初期化する）
        self.node_visit_counts: dict[str, int] = {}

    def reset_counts(self) -> None:
        """
        訪問カウントをリセットする

        新しいタスクを開始する前に呼び出すことで、
        前のタスクの訪問回数をクリアする。
        """
        self.node_visit_counts = {}

    async def intercept(
        self,
        phase: str,
        node: WorkflowNode,
        context: WorkflowContext,
        **kwargs: Any,
    ) -> Optional[MiddlewareSignal]:
        """
        無限ループ検出介入処理

        before_execution フェーズでのみ動作する。
        ノードへの訪問回数をインクリメントし、上限を超えた場合は
        中断シグナルを返す。

        Args:
            phase: 実行フェーズ
            node: 実行対象ノード情報
            context: ワークフローコンテキスト
            **kwargs: 追加引数（未使用）

        Returns:
            MiddlewareSignal: 訪問回数が上限を超えた場合（action="abort"）
            None: 正常範囲内の場合
        """
        # before_execution フェーズ以外はスキップする
        if phase != "before_execution":
            return None

        # 訪問カウントをインクリメントする（初回は 0 から始まり 1 になる）
        current_count = self.node_visit_counts.get(node.node_id, 0) + 1
        self.node_visit_counts[node.node_id] = current_count

        # 最大訪問回数を超えた場合は中断シグナルを返す
        if current_count > self.max_node_visits:
            logger.error(
                "InfiniteLoopDetectionMiddleware: 無限ループを検出した: "
                "node_id=%s, 訪問回数=%d, 上限=%d",
                node.node_id,
                current_count,
                self.max_node_visits,
            )
            return MiddlewareSignal(
                action="abort",
                reason=(
                    f"Infinite loop detected: node {node.node_id} has been visited "
                    f"{current_count} times"
                ),
            )

        return None
