"""
DefinitionLoader単体テスト

正常な定義JSON・バリデーションエラーとなる定義JSON（ノードID不一致・
エントリポイント欠落等）を用いて各validate_*()メソッドを検証する。

IMPLEMENTATION_PLAN.md フェーズ6-5 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from definitions.definition_loader import DefinitionLoader, DefinitionValidationError
from shared.models.agent_definition import AgentDefinition, AgentNodeConfig
from shared.models.graph_definition import GraphDefinition
from shared.models.prompt_definition import PromptConfig, PromptDefinition


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def mock_repo() -> MagicMock:
    """テスト用WorkflowDefinitionRepositoryモックを返す"""
    return MagicMock()


@pytest.fixture
def loader(mock_repo: MagicMock) -> DefinitionLoader:
    """テスト用DefinitionLoaderインスタンスを返す"""
    return DefinitionLoader(workflow_definition_repo=mock_repo)


@pytest.fixture
def valid_graph_def() -> GraphDefinition:
    """バリデーション通過する最小限のグラフ定義を返す"""
    return GraphDefinition.from_dict(
        {
            "version": "1.0",
            "name": "テストグラフ",
            "entry_node": "node_a",
            "nodes": [
                {"id": "node_a", "type": "agent", "agent_definition_id": "agent_1"},
                {"id": "node_b", "type": "agent", "agent_definition_id": "agent_2"},
            ],
            "edges": [
                {"from": "node_a", "to": "node_b"},
                {"from": "node_b", "to": None},
            ],
        }
    )


@pytest.fixture
def valid_agent_def() -> AgentDefinition:
    """バリデーション通過する最小限のエージェント定義を返す"""
    return AgentDefinition.from_dict(
        {
            "version": "1.0",
            "agents": [
                {
                    "id": "agent_1",
                    "role": "planning",
                    "input_keys": ["task_description"],
                    "output_keys": ["plan"],
                    "prompt_id": "prompt_1",
                    "mcp_servers": [],
                },
                {
                    "id": "agent_2",
                    "role": "execution",
                    "input_keys": ["plan"],
                    "output_keys": ["result"],
                    "prompt_id": "prompt_2",
                    "env_ref": "1",
                    "mcp_servers": [],
                },
            ],
        }
    )


@pytest.fixture
def valid_prompt_def() -> PromptDefinition:
    """バリデーション通過する最小限のプロンプト定義を返す"""
    return PromptDefinition.from_dict(
        {
            "version": "1.0",
            "prompts": [
                {
                    "id": "prompt_1",
                    "system_prompt": "あなたはプランニングエージェントです。",
                },
                {
                    "id": "prompt_2",
                    "system_prompt": "あなたは実行エージェントです。",
                },
            ],
        }
    )


# ========================================
# TestValidateGraphDefinition
# ========================================


class TestValidateGraphDefinition:
    """validate_graph_definition()のテスト"""

    def test_正常なグラフ定義はTrueを返す(
        self, loader: DefinitionLoader, valid_graph_def: GraphDefinition
    ) -> None:
        """正常なグラフ定義でvalidate_graph_definition()がTrueを返すことを確認する"""
        result = loader.validate_graph_definition(valid_graph_def)
        assert result is True

    def test_entry_nodeが存在しない場合はエラーが発生する(
        self, loader: DefinitionLoader
    ) -> None:
        """entry_nodeがnodesに存在しない場合にDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "nonexistent_node",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                ],
                "edges": [
                    {"from": "node_a", "to": None},
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="entry_node"):
            loader.validate_graph_definition(graph_def)

    def test_エッジのfrom_nodeが存在しない場合はエラーが発生する(
        self, loader: DefinitionLoader
    ) -> None:
        """エッジのfrom_nodeがnodesに存在しない場合にDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                ],
                "edges": [
                    {"from": "node_a", "to": None},
                    {"from": "nonexistent", "to": "node_a"},
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="from_node"):
            loader.validate_graph_definition(graph_def)

    def test_エッジのto_nodeが存在しない場合はエラーが発生する(
        self, loader: DefinitionLoader
    ) -> None:
        """エッジのto_nodeがnodesに存在しない場合にDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                ],
                "edges": [
                    {"from": "node_a", "to": "nonexistent_node"},
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="to_node"):
            loader.validate_graph_definition(graph_def)

    def test_到達不能なノードが存在する場合はエラーが発生する(
        self, loader: DefinitionLoader
    ) -> None:
        """BFSでentry_nodeから到達できないノードが存在する場合にDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                    {"id": "isolated_node", "type": "agent"},  # 到達不能ノード
                ],
                "edges": [
                    {"from": "node_a", "to": None},
                    {"from": "isolated_node", "to": None},
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="到達不能"):
            loader.validate_graph_definition(graph_def)

    def test_終了エッジが存在しない場合はエラーが発生する(
        self, loader: DefinitionLoader
    ) -> None:
        """グラフに終了エッジ（to: null）が存在しない場合にDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                    {"id": "node_b", "type": "agent"},
                ],
                "edges": [
                    {"from": "node_a", "to": "node_b"},
                    {"from": "node_b", "to": "node_a"},  # 循環するが終了なし
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="終了エッジ"):
            loader.validate_graph_definition(graph_def)

    def test_条件式の構文エラーでエラーが発生する(
        self, loader: DefinitionLoader
    ) -> None:
        """不正な条件式でDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                    {"id": "node_b", "type": "agent"},
                ],
                "edges": [
                    {
                        "from": "node_a",
                        "to": "node_b",
                        "condition": "!!!invalid python syntax!!!",
                    },
                    {"from": "node_b", "to": None},
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="条件式"):
            loader.validate_graph_definition(graph_def)

    def test_正常な条件式はバリデーション通過する(
        self, loader: DefinitionLoader
    ) -> None:
        """有効なPython条件式でバリデーションが通過することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "agent"},
                    {"id": "node_b", "type": "agent"},
                ],
                "edges": [
                    {"from": "node_a", "to": "node_b", "condition": "True"},
                    {"from": "node_b", "to": None},
                ],
            }
        )
        result = loader.validate_graph_definition(graph_def)
        assert result is True

    def test_DSL条件式はバリデーション通過する(self, loader: DefinitionLoader) -> None:
        """
        グラフ定義で使用されるDSL形式の条件式（&&・||・true・false）が
        バリデーションを通過することを確認する。
        """
        # グラフ定義JSONで実際に使用されるDSL形式の条件式
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {"id": "node_a", "type": "condition"},
                    {"id": "node_b", "type": "agent"},
                    {"id": "node_c", "type": "agent"},
                ],
                "edges": [
                    {
                        "from": "node_a",
                        "to": "node_b",
                        # DSL形式: &&（AND）・true/false（リテラル）を組み合わせた条件式
                        "condition": "context.plan_result.spec_file_exists == true && context.classification_result.task_type == 'code_generation'",
                    },
                    {
                        "from": "node_a",
                        "to": "node_c",
                        # DSL形式: ||（OR）を含む条件式
                        "condition": "context.reflection_result.action == 'revise_plan' && (context.reflection_result.severity == 'critical' || context.reflection_result.replan_mode == 'full')",
                    },
                    {"from": "node_b", "to": None},
                    {"from": "node_c", "to": None},
                ],
            }
        )

        # バリデーションが例外なく通過することを確認する
        result = loader.validate_graph_definition(graph_def)
        assert result is True

    def test_ExecEnvSetupExecutorノードにenv_countが必須(
        self, loader: DefinitionLoader
    ) -> None:
        """ExecEnvSetupExecutorノードにenv_countがない場合にDefinitionValidationErrorが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {
                        "id": "node_a",
                        "type": "executor",
                        "executor_class": "ExecEnvSetupExecutor",
                        # env_countが未設定
                    },
                ],
                "edges": [
                    {"from": "node_a", "to": None},
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="env_count"):
            loader.validate_graph_definition(graph_def)


# ========================================
# TestValidateAgentDefinition
# ========================================


class TestValidateAgentDefinition:
    """validate_agent_definition()のテスト"""

    def test_正常なエージェント定義はTrueを返す(
        self,
        loader: DefinitionLoader,
        valid_graph_def: GraphDefinition,
        valid_agent_def: AgentDefinition,
    ) -> None:
        """正常なエージェント定義でvalidate_agent_definition()がTrueを返すことを確認する"""
        result = loader.validate_agent_definition(valid_agent_def, valid_graph_def)
        assert result is True

    def test_グラフが参照するagent_definition_idが存在しない場合はエラー(
        self,
        loader: DefinitionLoader,
        valid_agent_def: AgentDefinition,
    ) -> None:
        """グラフ定義がエージェント定義に存在しないagent_definition_idを参照する場合にエラーが発生することを確認する"""
        graph_def = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {
                        "id": "node_a",
                        "type": "agent",
                        "agent_definition_id": "nonexistent_agent",
                    },
                ],
                "edges": [{"from": "node_a", "to": None}],
            }
        )
        with pytest.raises(DefinitionValidationError, match="agent_definition_id"):
            loader.validate_agent_definition(valid_agent_def, graph_def)

    def test_不正なroleでエラーが発生する(
        self,
        loader: DefinitionLoader,
        valid_graph_def: GraphDefinition,
    ) -> None:
        """不正なroleを持つエージェントでDefinitionValidationErrorが発生することを確認する"""
        # Pydanticモデルは直接不正なroleを受け付けないため、
        # モックオブジェクトを使用してvalidate_agent_definition()のroleチェックを検証する
        import unittest.mock as mock

        mock_agent = MagicMock()
        mock_agent.id = "agent_1"
        mock_agent.role = "invalid_role"  # 不正なrole
        mock_agent.input_keys = ["task_description"]
        mock_agent.output_keys = ["plan"]
        mock_agent.env_ref = None
        mock_agent.mcp_servers = []

        mock_agent_def = MagicMock()
        mock_agent_def.agents = [mock_agent]

        # グラフがagent_definition_idを参照していないので、
        # agentタイプのノードを空にして整合性チェックをパスさせる
        simple_graph = GraphDefinition.from_dict(
            {
                "version": "1.0",
                "name": "テストグラフ",
                "entry_node": "node_a",
                "nodes": [
                    {
                        "id": "node_a",
                        "type": "executor",
                        "executor_class": "TaskContextInitExecutor",
                    },
                ],
                "edges": [{"from": "node_a", "to": None}],
            }
        )

        # agentタイプのノードがない場合、グラフ整合性チェックはスキップされ
        # roleバリデーションのみが実行される
        mock_agent_def_ids = set()
        with pytest.raises(DefinitionValidationError, match="role"):
            loader.validate_agent_definition(mock_agent_def, simple_graph)

    def test_input_keysとoutput_keysに重複がある場合はエラー(
        self,
        loader: DefinitionLoader,
        valid_graph_def: GraphDefinition,
    ) -> None:
        """input_keysとoutput_keysに重複するキーがある場合にDefinitionValidationErrorが発生することを確認する"""
        agent_def = AgentDefinition.from_dict(
            {
                "version": "1.0",
                "agents": [
                    {
                        "id": "agent_1",
                        "role": "planning",
                        "input_keys": ["task_description", "duplicate_key"],
                        "output_keys": ["plan", "duplicate_key"],  # 重複キー
                        "prompt_id": "prompt_1",
                    },
                    {
                        "id": "agent_2",
                        "role": "execution",
                        "input_keys": ["plan"],
                        "output_keys": ["result"],
                        "prompt_id": "prompt_2",
                        "env_ref": "1",
                    },
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="重複"):
            loader.validate_agent_definition(agent_def, valid_graph_def)

    def test_planningエージェントの不正なenv_refでエラー(
        self,
        loader: DefinitionLoader,
        valid_graph_def: GraphDefinition,
    ) -> None:
        """planningエージェントのenv_refが'plan'以外の場合にDefinitionValidationErrorが発生することを確認する"""
        agent_def = AgentDefinition.from_dict(
            {
                "version": "1.0",
                "agents": [
                    {
                        "id": "agent_1",
                        "role": "planning",
                        "input_keys": ["task_description"],
                        "output_keys": ["plan"],
                        "prompt_id": "prompt_1",
                        "env_ref": "1",  # planningにenv_ref="1"は不正
                    },
                    {
                        "id": "agent_2",
                        "role": "execution",
                        "input_keys": ["plan"],
                        "output_keys": ["result"],
                        "prompt_id": "prompt_2",
                        "env_ref": "1",
                    },
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="planning"):
            loader.validate_agent_definition(agent_def, valid_graph_def)


# ========================================
# TestValidatePromptDefinition
# ========================================


class TestValidatePromptDefinition:
    """validate_prompt_definition()のテスト"""

    def test_正常なプロンプト定義はTrueを返す(
        self,
        loader: DefinitionLoader,
        valid_agent_def: AgentDefinition,
        valid_prompt_def: PromptDefinition,
    ) -> None:
        """正常なプロンプト定義でvalidate_prompt_definition()がTrueを返すことを確認する"""
        result = loader.validate_prompt_definition(valid_prompt_def, valid_agent_def)
        assert result is True

    def test_エージェントが参照するprompt_idが存在しない場合はエラー(
        self,
        loader: DefinitionLoader,
        valid_agent_def: AgentDefinition,
    ) -> None:
        """エージェント定義が存在しないprompt_idを参照する場合にDefinitionValidationErrorが発生することを確認する"""
        prompt_def = PromptDefinition.from_dict(
            {
                "version": "1.0",
                "prompts": [
                    {
                        "id": "prompt_1",
                        "system_prompt": "プランニングプロンプト",
                    },
                    # prompt_2が存在しない
                ],
            }
        )
        with pytest.raises(DefinitionValidationError, match="prompt_id"):
            loader.validate_prompt_definition(prompt_def, valid_agent_def)


# ========================================
# TestLoadWorkflowDefinition
# ========================================


class TestLoadWorkflowDefinition:
    """load_workflow_definition()のテスト"""

    async def test_正常なワークフロー定義をロードできる(
        self,
        loader: DefinitionLoader,
        mock_repo: MagicMock,
        valid_graph_def: GraphDefinition,
        valid_agent_def: AgentDefinition,
        valid_prompt_def: PromptDefinition,
    ) -> None:
        """正常なワークフロー定義のロードが成功することを確認する"""
        # モックの設定
        mock_repo.get_workflow_definition = AsyncMock(
            return_value={
                "id": 1,
                "name": "test_workflow",
                "graph_definition": valid_graph_def.model_dump(by_alias=True),
                "agent_definition": valid_agent_def.model_dump(),
                "prompt_definition": valid_prompt_def.model_dump(),
            }
        )

        graph, agent, prompt = await loader.load_workflow_definition(1)
        assert isinstance(graph, GraphDefinition)
        assert isinstance(agent, AgentDefinition)
        assert isinstance(prompt, PromptDefinition)

    async def test_存在しないIDの場合はValueErrorが発生する(
        self,
        loader: DefinitionLoader,
        mock_repo: MagicMock,
    ) -> None:
        """存在しないワークフロー定義IDでValueErrorが発生することを確認する"""
        mock_repo.get_workflow_definition = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="ワークフロー定義が見つかりません"):
            await loader.load_workflow_definition(999)

    async def test_プリセット一覧を取得できる(
        self,
        loader: DefinitionLoader,
        mock_repo: MagicMock,
    ) -> None:
        """get_preset_definitions()がプリセット一覧を返すことを確認する"""
        mock_repo.list_workflow_definitions = AsyncMock(
            return_value=[
                {"id": 1, "name": "standard_mr_processing", "is_preset": True}
            ]
        )

        result = await loader.get_preset_definitions()
        assert len(result) == 1
        assert result[0]["name"] == "standard_mr_processing"
        mock_repo.list_workflow_definitions.assert_called_once_with(
            is_preset=True,
            is_active=True,
        )
