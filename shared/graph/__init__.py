"""
shared.graph パッケージ

グラフ定義のレンダリングに関する共有ユーティリティを提供する。
consumer と backend の双方から利用可能な共通実装を収録する。
"""

from shared.graph.mermaid_renderer import MermaidGraphRenderer

__all__ = ["MermaidGraphRenderer"]
