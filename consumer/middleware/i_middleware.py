"""
IMiddleware モジュール

Middleware の基底インターフェース、フロー制御シグナル、ノード情報スタブを定義する。

CLASS_IMPLEMENTATION_SPEC.md § 5.1（IMiddlewareインターフェース）に準拠する。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_framework import WorkflowContext

logger = logging.getLogger(__name__)


@dataclass
class MiddlewareSignal:
    """
    フロー制御シグナル

    Middleware が返すシグナルで、ワークフローエンジンに対して
    ノード実行のフロー制御を指示する。

    Attributes:
        action: フロー制御アクション（"redirect" / "abort" / "skip"）
        redirect_to: リダイレクト先ノードID（action が "redirect" の場合のみ使用）
        reason: フロー制御の理由（ログ・デバッグ用）
    """

    action: str
    reason: str
    redirect_to: str | None = field(default=None)


@dataclass
class WorkflowNode:
    """
    ワークフローノード情報スタブ

    Middleware に渡されるノード情報を表す。
    実際のノード実装はワークフローエンジン側で管理される。

    Attributes:
        node_id: ノードID
        node_type: ノード種別（"agent" / "executor" / "condition"）
        metadata: メタデータ（check_comments_before, comment_redirect_to 属性を持つ想定）
    """

    node_id: str
    node_type: str
    metadata: Any = field(default=None)


class IMiddleware(ABC):
    """
    Middleware インターフェース

    すべての Middleware が実装しなければならない基底インターフェース。
    intercept() を実装することで、ノード実行の前後や
    エラー発生時に横断的な処理を挿入できる。
    """

    @abstractmethod
    async def intercept(
        self,
        phase: str,
        node: WorkflowNode,
        context: WorkflowContext,
        **kwargs: Any,
    ) -> Optional[MiddlewareSignal]:
        """
        ノード実行への介入処理

        Args:
            phase: 実行フェーズ（"before_execution" / "after_execution" / "on_error"）
            node: 実行対象ノード情報
            context: ワークフローコンテキスト
            **kwargs: 追加引数（result、exception など）

        Returns:
            MiddlewareSignal: フロー制御が必要な場合
            None: 通常フローを継続する場合
        """
        ...
