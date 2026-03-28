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
from consumer.utils.token_utils import estimate_token_count

if TYPE_CHECKING:
    from agent_framework import WorkflowContext
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

        after_execution フェーズではノード実行結果の token_usage から記録する。
        on_error フェーズでは ctx に中間保存された _pending_token_usage から記録する。
        これにより、agent.run() 成功後に後続ステップ（進捗報告など）でエラーが
        起きた場合でもトークン使用量を記録できる。
        クォータエラーなど agent.run() 自体が失敗した場合は _pending_token_usage が
        セットされないため自然に除外される。

        フェーズが after_execution / on_error 以外、またはノード種別が agent 以外の
        場合はスキップする。

        Args:
            phase: 実行フェーズ
            node: 実行対象ノード情報
            context: ワークフローコンテキスト
            **kwargs: 追加引数（result: エージェント実行結果、exception: 発生した例外）

        Returns:
            None: 常に通常フローを継続する
        """
        # after_execution / on_error 以外はスキップする
        if phase not in ("after_execution", "on_error"):
            return None

        # agent ノード以外はスキップする
        if node.node_type != "agent":
            return None

        token_info: dict[str, Any] | None = None

        if phase == "after_execution":
            # after_execution フェーズ: 実行結果の token_usage から抽出する
            result: Any = kwargs.get("result")
            if result is not None:
                token_info = _extract_token_info(result)

        elif phase == "on_error":
            # on_error フェーズ: agent.run() 成功後に ctx へ中間保存された
            # _pending_token_usage から抽出する。
            # クォータエラーなど agent.run() 自体が失敗した場合は
            # _pending_token_usage がセットされていないためスキップされる。
            pending: Any = context.get_state("_pending_token_usage")
            if pending is not None:
                token_info = _extract_token_info({"token_usage": pending})
                # 次のリトライや再実行で二重計上しないよう中間保存を消去する
                context.set_state("_pending_token_usage", None)

        if token_info is None:
            return None

        prompt_tokens: int = token_info.get("prompt_tokens", 0)
        completion_tokens: int = token_info.get("completion_tokens", 0)
        total_tokens: int = token_info.get("total_tokens", 0)
        model: str = token_info.get("model", "unknown")

        # コンテキストからタスク・ユーザー情報を取得する
        task_uuid: str | None = context.get_state("task_uuid")
        username: str | None = context.get_state("username")

        # task_uuid が未設定の場合は外部キー制約違反を引き起こすため明示的にエラーにする
        if not task_uuid:
            raise ValueError(
                f"TokenUsageMiddleware: task_uuid がコンテキストに存在しません: node_id={node.node_id}"
            )

        # トークン使用量をデータベースに保存する
        try:
            await self.context_storage_manager.save_token_usage(
                username=username or "",
                task_uuid=task_uuid,
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
                "username": username or "",
            },
            value=float(total_tokens),
        )

        return None


def _extract_token_info(result: Any) -> dict[str, Any] | None:
    """
    実行結果からトークン使用量情報を抽出する

    result が dict の場合は token_usage キーから取得を試みる。
    以下の 2 つのフォーマットに対応する。

    旧フォーマット（後方互換）:
        {"token_usage": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N, "model": "..."}}

    新フォーマット（ConfigurableAgent から渡される）:
        {"token_usage": {"usage_details": <UsageDetails|None>, "prompt_text": str, "response_text": str, "model": str}}
        usage_details が None の場合は tiktoken でトークン数を推定する。

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

    # --- 新フォーマット: usage_details キーが存在する場合 ---
    if "usage_details" in token_usage:
        return _extract_token_info_new_format(token_usage)

    # --- 旧フォーマット: prompt_tokens / total_tokens キーが存在する場合 ---
    if "total_tokens" not in token_usage and "prompt_tokens" not in token_usage:
        return None

    return token_usage


def _extract_token_info_new_format(
    token_usage: dict[str, Any],
) -> dict[str, Any] | None:
    """
    新フォーマットの token_usage からトークン情報を抽出する。

    usage_details が存在する場合はその値を使用し、
    存在しない（非公式エンドポイント等）場合は tiktoken で推定する。

    Args:
        token_usage: 新フォーマットの token_usage 辞書

    Returns:
        旧フォーマット互換のトークン情報辞書。抽出不能な場合は None。
    """
    model: str = token_usage.get("model") or "unknown"
    usage_details: dict[str, Any] | None = token_usage.get("usage_details")

    prompt_tokens: int = 0
    completion_tokens: int = 0

    if usage_details is not None:
        # usage_details は UsageDetails（TypedDict / 辞書）
        prompt_tokens = int(usage_details.get("input_token_count") or 0)
        completion_tokens = int(usage_details.get("output_token_count") or 0)

    # usage_details が None、または両方 0 の場合は tiktoken で推定する
    if prompt_tokens == 0 and completion_tokens == 0:
        prompt_text: str = token_usage.get("prompt_text") or ""
        response_text: str = token_usage.get("response_text") or ""

        if not prompt_text and not response_text:
            # 推定に必要なテキストが存在しないため処理をスキップする
            return None

        prompt_tokens = estimate_token_count(prompt_text, model)
        completion_tokens = estimate_token_count(response_text, model)

        logger.warning(
            "tiktokenによるトークン数推定: model=%s, prompt=%d, completion=%d",
            model,
            prompt_tokens,
            completion_tokens,
        )

    total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "model": model,
    }
