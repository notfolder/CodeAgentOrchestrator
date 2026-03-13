"""
BaseExecutor モジュール

すべての Executor の基底クラスを定義する。
WorkflowContext へのアクセスを簡略化するヘルパーメソッドと、
サブクラスが必ず実装しなければならない抽象メソッドを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 3.1（BaseExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

# 循環インポートを避けるため型チェック時のみインポートする
if TYPE_CHECKING:
    from consumer.agents.configurable_agent import WorkflowContext

# configurable_agent.py で定義済みの BaseExecutor を継承して拡張する
from consumer.agents.configurable_agent import BaseExecutor as _AgentBaseExecutor

logger = logging.getLogger(__name__)


class BaseExecutor(_AgentBaseExecutor):
    """
    Executor 基底クラス

    すべての Executor に共通するヘルパーメソッドと抽象インターフェースを定義する。
    サブクラスは handle() を必ず実装しなければならない。

    Attributes:
        なし（サブクラスで定義する）
    """

    async def get_context_value(self, ctx: WorkflowContext, key: str) -> Any:
        """
        ワークフローコンテキストから値を取得する。

        Args:
            ctx: ワークフローコンテキスト
            key: 取得するキー名

        Returns:
            キーに対応する値。存在しない場合は None。
        """
        return await ctx.get_state(key)

    async def set_context_value(
        self, ctx: WorkflowContext, key: str, value: Any
    ) -> None:
        """
        ワークフローコンテキストに値を保存する。

        Args:
            ctx: ワークフローコンテキスト
            key: 保存するキー名
            value: 保存する値
        """
        await ctx.set_state(key, value)

    @abstractmethod
    async def handle(self, msg: Any, ctx: WorkflowContext) -> Any:
        """
        メッセージを処理して結果を返す。

        サブクラスはこのメソッドを必ず実装しなければならない。

        Args:
            msg: 受け取るメッセージ（型は Agent Framework に依存）
            ctx: ワークフローコンテキスト

        Returns:
            処理結果
        """
        ...
