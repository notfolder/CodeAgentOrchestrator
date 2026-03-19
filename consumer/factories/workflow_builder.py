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

from agent_framework import (
    Workflow,
    WorkflowBuilder as AFWorkflowBuilder,
)

logger = logging.getLogger(__name__)

# agent_framework.Workflow を re-export して
# 他モジュールが ``from consumer.factories.workflow_builder import Workflow`` で
# 参照できるようにする。
__all__ = ["Workflow", "WorkflowBuilder"]


class WorkflowBuilder:
    """
    ワークフロービルダークラス

    グラフ定義のノード・エッジを受け取り、Agent FrameworkのWorkflowオブジェクトを
    組み立てる独立クラス。WorkflowFactoryがコンストラクタで保持し、
    各ノード登録後にbuild()を呼び出す。

    内部では Agent Framework の WorkflowBuilder API を使用し、
    add_node() で登録された Executor/Agent インスタンスと
    add_edge() で登録されたエッジ定義を build() 時に一括で
    AF WorkflowBuilder に反映して Workflow を構築する。

    CLASS_IMPLEMENTATION_SPEC.md § 2.6 に準拠する。

    Attributes:
        node_registry: ノードID → 登録済みノードインスタンスのマッピング
        edge_registry: 追加予定のエッジ定義リスト
        _first_node_id: 最初に登録されたノードID（エントリポイント設定用）
    """

    def __init__(self) -> None:
        """WorkflowBuilderを初期化する。"""
        self.node_registry: dict[str, Any] = {}
        self.edge_registry: list[dict[str, Any]] = []
        self._first_node_id: str | None = None

    def add_node(self, node_id: str, node_instance: Any) -> None:
        """
        ノードをワークフローに登録する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.6.3 に準拠する。

        処理フロー:
        1. node_registry[node_id] = node_instanceを記録
        2. 最初に登録されたノードをエントリポイント候補として記録

        Args:
            node_id: ノードID
            node_instance: ノードインスタンス（Executor/ConfigurableAgent等）
        """
        if self._first_node_id is None:
            self._first_node_id = node_id

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
        build()時にadd_edge(condition=...)で追加される。

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
        1. 最初に登録されたノードを start_executor として AF WorkflowBuilder を生成
        2. edge_registryをイテレートし、ノードインスタンスを解決してエッジを追加
           - conditionが指定されている場合はラムダ関数に変換して条件付きエッジとする
           - to_node が None のエッジは終了エッジとして扱い、スキップする
        3. build() で Workflow を構築して返す

        Returns:
            Agent Framework の Workflow インスタンス

        Raises:
            ValueError: ノードが1件も登録されていない場合
        """
        if self._first_node_id is None or not self.node_registry:
            raise ValueError(
                "ノードが1件も登録されていません。build() を呼び出す前に add_node() でノードを登録してください。"
            )

        # エントリポイントとなるノードインスタンスを取得する
        start_instance = self.node_registry[self._first_node_id]
        af_builder = AFWorkflowBuilder(start_executor=start_instance)

        # AF WorkflowBuilder は同一 from→to ペアの重複エッジを許可しないため、
        # 同一ペアに複数の条件が定義されている場合は OR 結合して単一エッジにまとめる
        merged_edges: dict[tuple[str, str | None], list[str | None]] = {}
        for edge_info in self.edge_registry:
            key = (edge_info["from"], edge_info["to"])
            merged_edges.setdefault(key, []).append(edge_info["condition"])

        # エッジを追加する
        for (from_id, to_id), conditions in merged_edges.items():
            # to_node が None は終了エッジ（AF では output_executors で表現する）
            # ここではスキップする（start_executor 以外に出力先がない場合はそのまま終了する）
            if to_id is None:
                logger.debug(
                    "終了エッジをスキップしました: from=%s -> None", from_id
                )
                continue

            from_instance = self.node_registry.get(from_id)
            to_instance = self.node_registry.get(to_id)

            if from_instance is None or to_instance is None:
                logger.warning(
                    "エッジのノードが見つかりません: from=%s(%s), to=%s(%s)。スキップします",
                    from_id,
                    "found" if from_instance else "missing",
                    to_id,
                    "found" if to_instance else "missing",
                )
                continue

            # 条件リストから None を除外し、有効な条件のみ取得する
            valid_conditions = [c for c in conditions if c is not None]

            if not valid_conditions:
                # 全て無条件の場合は無条件エッジとして追加
                af_builder.add_edge(from_instance, to_instance)
            else:
                # 複数条件がある場合は OR 結合して単一の条件関数にする
                combined = " or ".join(f"({c})" for c in valid_conditions)
                condition_func = self._make_condition_func(combined)
                af_builder.add_edge(from_instance, to_instance, condition=condition_func)

        workflow = af_builder.build()

        logger.info(
            "ワークフローを構築しました: nodes=%s, edges=%d件",
            list(self.node_registry.keys()),
            len(self.edge_registry),
        )
        return workflow

    @staticmethod
    def _make_condition_func(condition_expr: str) -> Any:
        """
        DSL条件式文字列をAF互換の条件関数に変換する。

        "true" は常に True を返す関数、それ以外はメッセージ内容に対する
        評価関数を返す。実行時エラーが発生した場合は False を返す。

        Args:
            condition_expr: DSL条件式（例: "true", "task_type == 'code_generation'"）

        Returns:
            条件判定関数（msg を引数に取り bool を返す）
        """
        if condition_expr.strip().lower() == "true":
            return lambda msg: True

        def _evaluate(msg: Any) -> bool:
            try:
                # メッセージが辞書の場合はキーをローカル変数として評価する
                local_vars: dict[str, Any] = {}
                if isinstance(msg, dict):
                    local_vars.update(msg)
                return bool(eval(condition_expr, {"__builtins__": {}}, local_vars))  # noqa: S307
            except Exception:
                logger.debug(
                    "条件式の評価に失敗しました: condition=%s, msg=%s",
                    condition_expr,
                    msg,
                )
                return False

        return _evaluate
