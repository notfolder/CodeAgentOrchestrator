"""
MermaidGraphRenderer 後方互換モジュール

実装は shared.graph.mermaid_renderer に移動した。
このモジュールは後方互換のために shared から再エクスポートする。

CLASS_IMPLEMENTATION_SPEC.md § 10.4（MermaidGraphRenderer）に準拠する。
"""

from shared.graph.mermaid_renderer import (
    MermaidGraphRenderer as MermaidGraphRenderer,
)  # noqa: F401

# 以下の実装は shared/graph/mermaid_renderer.py に移動済み

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# 各ノード状態に対応する classDef スタイル定義（AUTOMATA_CODEX_SPEC.md §6.3 準拠）
_CLASS_DEFS: dict[str, str] = {
    "pending": "classDef pending fill:#9e9e9e,color:#fff,stroke:#616161",
    "running": "classDef running fill:#ff9800,color:#fff,stroke:#e65100,stroke-width:3px",
    "done": "classDef done fill:#4caf50,color:#fff,stroke:#388e3c",
    "error": "classDef error fill:#f44336,color:#fff,stroke:#b71c1c",
    "skipped": "classDef skipped fill:#eeeeee,color:#9e9e9e,stroke:#bdbdbd,stroke-dasharray:4",
}


def _make_node_def(node_id: str, label: str, node_type: str, state: str) -> str:
    """
    ノード種別に応じた Mermaid ノード定義行を生成する。

    Args:
        node_id: ノードの識別子
        label: ノードの表示ラベル
        node_type: ノード種別（agent / executor / condition）
        state: 現在の状態（pending / running / done / error / skipped）

    Returns:
        Mermaid ノード定義文字列
    """
    # condition ノードは菱形（{ } 記法）で表現する
    if node_type == "condition":
        return f'{node_id}{{"{label}"}}:::{state}'
    # executor ノードはスタジアム形状（([ ]) 記法）
    if node_type == "executor":
        return f'{node_id}(["{label}"]):::{state}'
    # agent およびその他は矩形（[ ] 記法）
    return f'{node_id}["{label}"]:::{state}'


class MermaidGraphRenderer:
    """
    Mermaid フローチャート生成クラス。

    グラフ定義とノード状態 dict を受け取り、Mermaid フローチャート文字列を生成する。
    同一ノードから 2 つ以上のノードへのファンアウトを並列グループとして自動検出し、
    subgraph でまとめて表示する（condition ノードからのファンアウトは除外）。

    CLASS_IMPLEMENTATION_SPEC.md § 10.4 に準拠する。

    Attributes:
        graph_def: グラフ定義辞書（nodes / edges を含む）
    """

    def __init__(self, graph_def: dict[str, Any]) -> None:
        """
        初期化。

        Args:
            graph_def: グラフ定義辞書
                nodes: list of {"id": str, "label": str, "type": str}
                edges: list of {"from": str, "to": str, "label": str (optional)}
        """
        self.graph_def = graph_def

    def render(self, node_states: dict[str, str]) -> str:
        """
        グラフ定義とノード状態からMermaidフローチャート文字列を生成する。

        処理フロー:
        1. 並列グループを検出する
        2. ノード定義行を生成する（並列グループは subgraph にまとめる）
        3. エッジ定義行を生成する（並列ファンアウトは & 記法でまとめる）
        4. classDef 行を生成する
        5. 全体を結合して返す

        Args:
            node_states: ノードID → 状態文字列のdict

        Returns:
            Mermaid フローチャート文字列
        """
        nodes: list[dict[str, Any]] = self.graph_def.get("nodes", [])
        edges: list[dict[str, Any]] = self.graph_def.get("edges", [])

        # ノード情報をIDでインデックス化する
        node_map: dict[str, dict[str, Any]] = {n["id"]: n for n in nodes}
        node_type_map: dict[str, str] = {n["id"]: n.get("type", "agent") for n in nodes}

        # ① 並列グループ検出
        # 同一 from ノードから出るエッジを集計する
        from_to_map: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            from_to_map[edge["from"]].append(edge["to"])

        # condition 以外の from ノードで 2 つ以上の to ノードを持つものを並列グループとする
        # key: from_id, value: to_id のリスト
        parallel_groups: dict[str, list[str]] = {
            from_id: to_ids
            for from_id, to_ids in from_to_map.items()
            if len(to_ids) >= 2 and node_type_map.get(from_id) != "condition"
        }

        # 並列グループに属する to ノード（subgraph 内に配置するノード）の集合
        parallel_target_nodes: set[str] = set()
        for to_ids in parallel_groups.values():
            parallel_target_nodes.update(to_ids)

        # ② ノード定義行の生成
        lines: list[str] = ["flowchart TD"]

        # 並列グループに属さないノードを先に出力する
        for node in nodes:
            node_id = node["id"]
            if node_id in parallel_target_nodes:
                continue  # subgraph 内で出力する
            label = node.get("label", node_id)
            node_type = node.get("type", "agent")
            state = node_states.get(node_id, "pending")
            lines.append(f"  {_make_node_def(node_id, label, node_type, state)}")

        # 並列グループのノードを subgraph でまとめて出力する
        for group_idx, (from_id, to_ids) in enumerate(parallel_groups.items(), start=1):
            lines.append(f'  subgraph parallel{group_idx}["並列処理{group_idx}"]')
            lines.append("    direction LR")
            for node_id in to_ids:
                node = node_map.get(
                    node_id, {"id": node_id, "label": node_id, "type": "agent"}
                )
                label = node.get("label", node_id)
                node_type = node.get("type", "agent")
                state = node_states.get(node_id, "pending")
                lines.append(f"    {_make_node_def(node_id, label, node_type, state)}")
            lines.append("  end")

        # ③ エッジ定義行の生成
        processed_parallel_from: set[str] = set()
        for edge in edges:
            from_id = edge["from"]
            to_id = edge["to"]
            edge_label: str = edge.get("label", "")

            if from_id in parallel_groups:
                if from_id in processed_parallel_from:
                    # 同一ファンアウト元のエッジは最初の1回だけ & 記法で出力する
                    continue
                # 並列ファンアウト: A --> B & C 形式でまとめて出力する
                to_str = " & ".join(parallel_groups[from_id])
                lines.append(f"  {from_id} --> {to_str}")
                processed_parallel_from.add(from_id)
            else:
                # 通常エッジ
                if edge_label:
                    lines.append(f"  {from_id} -- {edge_label} --> {to_id}")
                else:
                    lines.append(f"  {from_id} --> {to_id}")

        # ④ classDef 行の生成（全状態種別を常に出力する）
        for class_def in _CLASS_DEFS.values():
            lines.append(f"  {class_def}")

        return "\n".join(lines)
