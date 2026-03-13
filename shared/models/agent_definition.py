"""
エージェント定義ドメインモデル定義

グラフ内の各エージェントノードの設定（ロール・コンテキストキー・利用ツール等）を
表すPydanticモデルを定義する。
AGENT_DEFINITION_SPEC.md § 3（JSON形式の仕様）に準拠する。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TodoListStrategy(BaseModel):
    """
    planningエージェントのTodoリスト戦略設定

    エージェント定義の metadata フィールドに含まれる。
    """

    on_initial_plan: str | None = Field(
        default=None,
        description="初回計画時のTodo操作（'create': 新規作成 / 'update': 更新）",
    )
    preserve_completed: bool = Field(
        default=True, description="完了済みTodoを保持するフラグ"
    )
    preserve_in_progress: bool = Field(
        default=True, description="進行中Todoを保持するフラグ"
    )


class AgentNodeMetadata(BaseModel):
    """
    エージェントノード固有の追加設定

    planningロールでは todo_list_strategy を持つ。
    """

    todo_list_strategy: TodoListStrategy | None = Field(
        default=None, description="Todoリスト戦略設定（planningロールのみ）"
    )

    model_config = {"extra": "allow"}


class AgentNodeConfig(BaseModel):
    """
    エージェントノード設定

    AGENT_DEFINITION_SPEC.md § 3.2 に準拠したエージェントノード1件の定義。
    ConfigurableAgent クラスがこの設定を元に動作する。
    """

    id: str = Field(
        description=(
            "エージェントの一意識別子"
            "（グラフ定義の agent_definition_id と一致させる）"
        )
    )
    node_id: str | None = Field(
        default=None,
        description=(
            "グラフ上のノードID。"
            "WorkflowFactory がエージェントをグラフノードとして配置する際に設定する。"
            "エージェント定義ファイル単体からロードした場合は None となる。"
        ),
    )
    role: Literal["planning", "reflection", "execution", "review"] = Field(
        description="エージェント役割（planning / reflection / execution / review）"
    )
    input_keys: list[str] = Field(
        description="ワークフローコンテキストから受け取るキー一覧"
    )
    output_keys: list[str] = Field(
        description="ワークフローコンテキストへ書き込むキー一覧"
    )
    mcp_servers: list[str] = Field(
        default_factory=list,
        description=(
            "利用するMCPサーバー名一覧"
            "（text_editor / command_executor / todo_list 等）"
        ),
    )
    env_ref: str | None = Field(
        default=None,
        description=(
            "使用する実行環境の参照。"
            "\"plan\": plan共有環境、\"1\"/\"2\"/\"3\": 分岐内の第N実行環境、"
            "省略(None): 環境不要。ビルド時に environment_id として確定される。"
            "CLASS_IMPLEMENTATION_SPEC.md § 1.3 に準拠する。"
        ),
    )
    prompt_id: str = Field(description="プロンプト定義ファイル内の対応するプロンプトID")
    max_iterations: int = Field(default=20, ge=1, description="LLMとのターン数上限")
    timeout_seconds: int = Field(default=600, ge=1, description="タイムアウト秒数")
    description: str | None = Field(default=None, description="エージェントの説明文")
    metadata: AgentNodeMetadata = Field(
        default_factory=AgentNodeMetadata,
        description="エージェント種別固有の追加設定",
    )


class AgentDefinition(BaseModel):
    """
    エージェント定義

    AGENT_DEFINITION_SPEC.md § 3.1 に準拠したエージェント定義全体。
    workflow_definitions テーブルの agent_definition カラム（JSONB）に保存される。
    """

    version: str = Field(description="定義フォーマットバージョン（例: '1.0'）")
    agents: list[AgentNodeConfig] = Field(description="各エージェントノードの定義配列")

    def get_agent(self, agent_id: str) -> AgentNodeConfig | None:
        """指定されたIDのエージェントノード設定を返す。存在しない場合はNoneを返す。"""
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentDefinition":
        """辞書からAgentDefinitionインスタンスを生成する。"""
        return cls.model_validate(data)
