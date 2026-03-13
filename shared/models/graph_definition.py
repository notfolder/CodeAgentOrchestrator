"""
グラフ定義ドメインモデル定義

ワークフローのフロー構造（ノード・エッジ・条件分岐）を表すPydanticモデルを定義する。
GRAPH_DEFINITION_SPEC.md § 3（JSON形式の仕様）に準拠する。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeMetadata(BaseModel):
    """
    ノード固有の拡張設定

    グラフノードのmetadataフィールドに格納される追加設定。
    """

    check_comments_before: bool = Field(
        default=False,
        description=(
            "trueの場合、ノード実行前にCommentCheckMiddlewareが新規コメントを確認する"
        ),
    )
    comment_redirect_to: str | None = Field(
        default=None,
        description=(
            "新規コメント検出時のリダイレクト先ノードID。"
            "check_comments_before: trueを指定する場合は必須"
        ),
    )
    preserve_context: list[str] = Field(
        default_factory=list,
        description="再計画時に保持するコンテキストキーのリスト",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="reflectionノードの最大リトライ回数",
    )

    model_config = {"extra": "allow"}


class GraphNodeDefinition(BaseModel):
    """
    グラフノード定義

    GRAPH_DEFINITION_SPEC.md § 3.2 に準拠したノード1件の定義。
    """

    id: str = Field(description="ノードの一意識別子")
    type: Literal["agent", "executor", "condition"] = Field(
        description="ノード種別（agent / executor / condition）"
    )
    agent_definition_id: str | None = Field(
        default=None,
        description="エージェント定義ファイル内のエージェントID（type=agentの場合必須）",
    )
    executor_class: str | None = Field(
        default=None,
        description="使用するExecutorクラス名（type=executorの場合必須）",
    )
    env_ref: str | None = Field(
        default=None,
        description=(
            "使用する実行環境の参照（'plan': plan共有環境、"
            "'1'/'2'/'3': 分岐内の第N実行環境、省略: 環境不要）"
        ),
    )
    env_count: int | None = Field(
        default=None,
        ge=1,
        description=(
            "作成する実行環境の数。ExecEnvSetupExecutorノードにのみ指定する"
        ),
    )
    label: str | None = Field(default=None, description="表示用ラベル")
    metadata: NodeMetadata = Field(
        default_factory=NodeMetadata, description="ノード固有の拡張設定"
    )


class GraphEdgeDefinition(BaseModel):
    """
    グラフエッジ定義

    GRAPH_DEFINITION_SPEC.md § 3.3 に準拠したエッジ1件の定義。
    """

    # 'from' は Python の予約語のため、エイリアスを使用する
    from_node: str = Field(alias="from", description="遷移元ノードのID")
    to_node: str | None = Field(
        alias="to",
        description="遷移先ノードのID（nullの場合はワークフロー終了）",
    )
    condition: str | None = Field(
        default=None,
        description=(
            "遷移条件式（省略時は無条件遷移）。"
            "ワークフローコンテキストのキーを参照して評価する"
        ),
    )
    label: str | None = Field(default=None, description="表示用ラベル")

    model_config = {"populate_by_name": True}


class GraphDefinition(BaseModel):
    """
    グラフ定義

    GRAPH_DEFINITION_SPEC.md § 3.1 に準拠したワークフロー全体のグラフ定義。
    workflow_definitions テーブルの graph_definition カラム（JSONB）に保存される。
    """

    version: str = Field(description="定義フォーマットバージョン（例: '1.0'）")
    name: str = Field(description="グラフの名前")
    description: str | None = Field(default=None, description="グラフの説明文")
    entry_node: str = Field(description="最初に実行するノードのID")
    nodes: list[GraphNodeDefinition] = Field(
        description="ノード定義の配列"
    )
    edges: list[GraphEdgeDefinition] = Field(
        description="エッジ定義の配列"
    )

    def get_node(self, node_id: str) -> GraphNodeDefinition | None:
        """指定されたIDのノード定義を返す。存在しない場合はNoneを返す。"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_outgoing_edges(self, node_id: str) -> list[GraphEdgeDefinition]:
        """指定されたノードから出るエッジの一覧を返す。"""
        return [edge for edge in self.edges if edge.from_node == node_id]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphDefinition":
        """辞書からGraphDefinitionインスタンスを生成する。"""
        return cls.model_validate(data)
