"""
TokenUsageMiddleware モジュール

AI エージェント呼び出しのトークン使用量を自動記録する Middleware を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 5.3（TokenUsageMiddleware）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from consumer.middleware.i_middleware import IMiddleware, MiddlewareSignal, WorkflowNode
from consumer.middleware.metrics_collector import MetricsCollector

if TYPE_CHECKING:
    from consumer.agents.configurable_agent import WorkflowContext
    from consumer.providers.context_storage_manager import ContextStorageManager

logger = logging.getLogger(__name__)


class TokenUsageMiddleware(IMiddleware):
    """
    トークン使用量記録 Middleware

    AI エージェントノードの実行後にトークン使用量を自動的に記録する。
    ContextStorageManager でデータベースに保存し、
    MetricsCollector で OpenTelemetry メトリクスを送信する。

    Attributes:
        context_storage_manager: コンテキストストレージマネージャー
        metrics_collector: メトリクスコレクター
    """

    def __init__(
        self,
        context_storage_manager: ContextStorageManager,
        metrics_collector: MetricsCollector,
    ) -> None:
        """
        初期化

        Args:
            context_storage_manager: コンテキストストレージマネージャー
            metrics_collector: メトリクスコレクター
        """
        self.context_storage_manager = context_storage_manager
        self.metrics_collector = metrics_collector

    async def intercept(
        self,
        phase: str,
        node: WorkflowNode,
        context: WorkflowContext,
        **kwargs: Any,
    ) -> Optional[MiddlewareSignal]:
        """
        トークン使用量記録介入処理

        after_execution フェーズかつ agent ノードのみ動作する。
        実行結果からトークン情報を抽出してデータベースとメトリクスに記録する。

        Args:
            phase: 実行フェーズ
            node: 実行対象ノード情報
            context: ワークフローコンテキスト
            **kwargs: 追加引数（result: エージェント実行結果を含む）

        Returns:
            None: 常に通常フローを継続する
        """
        # after_execution フェーズ以外はスキップする
        if phase != "after_execution":
            return None

        # agent ノード以外はスキップする
        if node.node_type != "agent":
            return None

        # 実行結果を取得する
        result: Any = kwargs.get("result")
        if result is None:
            return None

        # 実行結果からトークン使用量情報を抽出する
        token_info = _extract_token_info(result)
        if token_info is None:
            return None

        prompt_tokens: int = token_info.get("prompt_tokens", 0)
        completion_tokens: int = token_info.get("completion_tokens", 0)
        total_tokens: int = token_info.get("total_tokens", 0)
        model: str = token_info.get("model", "unknown")

        # コンテキストからタスク・ユーザー情報を取得する
        task_uuid: str | None = await context.get_state("task_uuid")
        user_email: str | None = await context.get_state("user_email")

        # トークン使用量をデータベースに保存する
        try:
            await self.context_storage_manager.save_token_usage(
                user_email=user_email or "",
                task_uuid=task_uuid or "",
                node_id=node.node_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except Exception as exc:
            logger.warning(
                "TokenUsageMiddleware: トークン使用量のDB保存に失敗した: node_id=%s, error=%s",
                node.node_id,
                exc,
            )

        # OpenTelemetry メトリクスを送信する
        self.metrics_collector.send_metric(
            metric_name="token_usage_total",
            labels={
                "model": model,
                "node_id": node.node_id,
                "user_email": user_email or "",
            },
            value=float(total_tokens),
        )

        return None


def _extract_token_info(result: Any) -> dict[str, Any] | None:
    """
    実行結果からトークン使用量情報を抽出する

    result が dict の場合は token_usage キーから取得を試みる。
    トークン情報が存在しない場合は None を返す。

    Args:
        result: エージェント実行結果（dict の場合は token_usage キーを参照する）

    Returns:
        dict[str, Any]: トークン情報辞書
            - prompt_tokens (int): プロンプトトークン数
            - completion_tokens (int): 補完トークン数
            - total_tokens (int): 合計トークン数
            - model (str): 使用モデル名
        None: トークン情報が存在しない場合
    """
    token_usage: dict[str, Any] | None = None

    if isinstance(result, dict):
        token_usage = result.get("token_usage")

    # token_usage が取得できなかった、または空の場合は None を返す
    if not token_usage:
        return None

    # 最低限 total_tokens が含まれていることを確認する
    if "total_tokens" not in token_usage and "prompt_tokens" not in token_usage:
        return None

    return token_usage
