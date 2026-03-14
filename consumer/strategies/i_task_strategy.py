"""
ITaskStrategy モジュール

タスク処理戦略の共通インターフェースを定義する。
TaskStrategyFactoryが返す処理戦略の共通インターフェースとして機能する。

CLASS_IMPLEMENTATION_SPEC.md § 2.7（ITaskStrategy）に準拠する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.models.task import Task


class ITaskStrategy(ABC):
    """
    タスク処理戦略インターフェース

    TaskStrategyFactoryが返す処理戦略の共通インターフェース。
    タスク種別に応じた具体的な戦略クラスがこのインターフェースを実装する。

    実装クラス:
    - IssueToMRConversionStrategy: IssueをMRに変換後にMR処理を実行する戦略
    - IssueOnlyStrategy: MR変換なしでIssue上で処理を完結させる戦略
    - MergeRequestStrategy: MR処理ワークフローを構築・実行する戦略

    CLASS_IMPLEMENTATION_SPEC.md § 2.7 に準拠する。
    """

    @abstractmethod
    async def execute(self, task: Task) -> None:
        """
        タスクを処理する。

        各サブクラスはタスク種別に応じた処理をこのメソッドに実装する。
        TaskHandlerはITaskStrategyを受け取り、具体的なクラスを意識せずに
        execute(task)を呼び出す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.7.2 に準拠する。

        Args:
            task: 処理対象のタスク
        """
        ...
