"""
WorkflowBuilder モジュール

グラフ定義のノード・エッジを受け取り、Agent FrameworkのWorkflowオブジェクトを
組み立てる独立クラスを提供する。WorkflowFactoryがコンストラクタで保持し、
各ノード登録後にbuild()を呼び出す。

CLASS_IMPLEMENTATION_SPEC.md § 2.6（WorkflowBuilder）に準拠する。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Workflow:
    """
    Agent Framework Workflowスタブ

    Agent Framework の Workflow クラスに相当するスタブ実装。
    実際の Agent Framework が利用可能になった際に差し替える。
    """

    def __init__(self) -> None:
        """Workflowを初期化する。"""
        self._nodes: dict[str, Any] = {}
        self._edges: list[dict[str, Any]] = []
        self._entry_node: str | None = None

    def add_node(self, node_id: str, node_instance: Any) -> None:
        """
        ノードを追加する。

        Args:
            node_id: ノードID
            node_instance: ノードインスタンス
        """
        self._nodes[node_id] = node_instance

    def add_edge(self, from_node_id: str, to_node_id: str | None) -> None:
        """
        エッジを追加する。

        Args:
            from_node_id: 遷移元ノードID
            to_node_id: 遷移先ノードID（Noneはワークフロー終了）
        """
        self._edges.append(
            {"from": from_node_id, "to": to_node_id, "condition": None}
        )

    def add_conditional_edge(
        self,
        from_node_id: str,
        to_node_id: str | None,
        condition: str,
    ) -> None:
        """
        条件付きエッジを追加する。

        Args:
            from_node_id: 遷移元ノードID
            to_node_id: 遷移先ノードID（Noneはワークフロー終了）
            condition: 遷移条件式
        """
        self._edges.append(
            {"from": from_node_id, "to": to_node_id, "condition": condition}
        )

    def set_entry_point(self, node_id: str) -> None:
        """
        エントリポイントを設定する。

        Args:
            node_id: エントリポイントのノードID
        """
        self._entry_node = node_id

    async def run(self, context: Any) -> None:
        """
        ワークフローを実行する（スタブ）。

        Args:
            context: ワークフローコンテキスト
        """
        logger.info(
            "ワークフロー実行開始: entry_node=%s, nodes=%s",
            self._entry_node,
            list(self._nodes.keys()),
        )


class WorkflowBuilder:
    """
    ワークフロービルダークラス

    グラフ定義のノード・エッジを受け取り、Agent FrameworkのWorkflowオブジェクトを
    組み立てる独立クラス。WorkflowFactoryがコンストラクタで保持し、
    各ノード登録後にbuild()を呼び出す。

    CLASS_IMPLEMENTATION_SPEC.md § 2.6 に準拠する。

    Attributes:
        workflow: Agent Framework Workflowインスタンス（未完成状態）
        node_registry: ノードID → 登録済みノードインスタンスのマッピング
        edge_registry: 追加予定のエッジ定義リスト
        _first_node_id: 最初に登録されたノードID（エントリポイント設定用）
    """

    def __init__(self) -> None:
        """WorkflowBuilderを初期化する。"""
        self.workflow: Workflow = Workflow()
        self.node_registry: dict[str, Any] = {}
        self.edge_registry: list[dict[str, Any]] = []
        self._first_node_id: str | None = None

    def add_node(self, node_id: str, node_instance: Any) -> None:
        """
        ノードをワークフローに登録する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.6.3 に準拠する。

        処理フロー:
        1. workflow.add_node(node_id, node_instance)を呼び出し
        2. node_registry[node_id] = node_instanceを記録

        Args:
            node_id: ノードID
            node_instance: ノードインスタンス（Executor/ConfigurableAgent等）
        """
        if self._first_node_id is None:
            self._first_node_id = node_id

        self.workflow.add_node(node_id, node_instance)
        self.node_registry[node_id] = node_instance
        logger.debug("ノードを登録しました: node_id=%s", node_id)

    def add_edge(
        self,
        from_node_id: str,
        to_node_id: str | None,
        condition: str | None = None,
    ) -> None:
        """
        エッジ情報をキューに登録する。

        conditionを省略した場合は無条件遷移エッジとして登録する。
        conditionを指定した場合は条件付き遷移エッジとして登録し、
        build()時にadd_conditional_edge()で追加される。

        CLASS_IMPLEMENTATION_SPEC.md § 2.6.3 に準拠する。

        処理フロー:
        1. edge_registryに{"from": from_node_id, "to": to_node_id, "condition": condition}を追加

        Args:
            from_node_id: 遷移元ノードID
            to_node_id: 遷移先ノードID（Noneはワークフロー終了）
            condition: 遷移条件式（省略時はNone → 無条件遷移エッジとして扱う）
        """
        self.edge_registry.append(
            {
                "from": from_node_id,
                "to": to_node_id,
                "condition": condition,
            }
        )
        logger.debug(
            "エッジをキューに追加しました: %s -> %s (condition=%s)",
            from_node_id,
            to_node_id,
            condition,
        )

    def build(self) -> Workflow:
        """
        エッジを追加してWorkflowオブジェクトを完成させる。

        CLASS_IMPLEMENTATION_SPEC.md § 2.6.3 に準拠する。

        処理フロー:
        1. edge_registryをイテレートし、conditionが指定されている場合は
           workflow.add_conditional_edge()、ない場合はworkflow.add_edge()を呼び出す
        2. node_registryの最初に登録されたノードをエントリポイントとして設定
        3. 完成したworkflowを返す

        Returns:
            完成したWorkflowインスタンス
        """
        # 1. エッジ追加
        for edge_info in self.edge_registry:
            from_node = edge_info["from"]
            to_node = edge_info["to"]
            condition = edge_info["condition"]

            if condition is not None:
                self.workflow.add_conditional_edge(from_node, to_node, condition)
            else:
                self.workflow.add_edge(from_node, to_node)

        # 2. エントリポイント設定
        if self._first_node_id is not None:
            self.workflow.set_entry_point(self._first_node_id)
            logger.debug(
                "エントリポイントを設定しました: node_id=%s", self._first_node_id
            )
        else:
            logger.warning("ノードが1件も登録されていません。エントリポイントが設定されません。")

        logger.info(
            "ワークフローを構築しました: nodes=%s, edges=%d件",
            list(self.node_registry.keys()),
            len(self.edge_registry),
        )
        # 3. Workflowオブジェクト返却
        return self.workflow
