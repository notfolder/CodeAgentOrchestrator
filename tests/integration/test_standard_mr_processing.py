"""
標準MR処理フロー（standard_mr_processing）統合テスト

コード生成・バグ修正・テスト作成・ドキュメント生成の4タスクについて、
ワークフロー全体（task_classifier → planning → execution → reflection
→ review → plan_reflection）が正常に動作することを確認する。

IMPLEMENTATION_PLAN.md フェーズ9-2 に準拠する。
参照ドキュメント:
  - STANDARD_MR_PROCESSING_FLOW.md § 3（MR処理の全体フロー）
  - STANDARD_MR_PROCESSING_FLOW.md § 4（フェーズ詳細）
  - STANDARD_MR_PROCESSING_FLOW.md § 5（タスク種別別詳細フロー）
  - AGENT_DEFINITION_SPEC.md § 6（各エージェントノードの詳細説明）
  - AGENT_DEFINITION_SPEC.md § 5（コンテキストキー一覧）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

# 定義ファイルパス
_DEFINITIONS_DIR = (
    Path(__file__).parents[2] / "docs" / "definitions"
)


# ========================================
# ヘルパー関数・フィクスチャ
# ========================================


def _load_definition(filename: str) -> dict[str, Any]:
    """docs/definitions/ 配下のJSONを読み込む"""
    filepath = _DEFINITIONS_DIR / filename
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def _make_workflow_definition_row(
    workflow_id: int = 1,
) -> dict[str, Any]:
    """
    テスト用のworkflow_definitionsテーブル行データを生成する。

    標準MR処理フローの定義を使用する。
    """
    graph_def = _load_definition("standard_mr_processing_graph.json")
    agent_def = _load_definition("standard_mr_processing_agents.json")
    prompt_def = _load_definition("standard_mr_processing_prompts.json")

    return {
        "id": workflow_id,
        "name": "standard_mr_processing",
        "display_name": "標準MR処理",
        "description": "コード生成・バグ修正・テスト作成・ドキュメント生成の4タスクに対応する標準フロー",
        "is_preset": True,
        "graph_definition": graph_def,
        "agent_definition": agent_def,
        "prompt_definition": prompt_def,
        "version": "1.0.0",
        "is_active": True,
        "created_by": None,
    }


@pytest.fixture
def workflow_definition_row() -> dict[str, Any]:
    """標準MR処理ワークフロー定義のDBレコードを返す"""
    return _make_workflow_definition_row()


@pytest.fixture
def mock_workflow_def_repo(
    workflow_definition_row: dict[str, Any],
) -> MagicMock:
    """WorkflowDefinitionRepositoryのモックを返す"""
    repo = MagicMock()
    repo.get_workflow_definition = AsyncMock(return_value=workflow_definition_row)
    repo.get_workflow_definition_by_name = AsyncMock(
        return_value=workflow_definition_row
    )
    return repo


@pytest.fixture
def mock_user_config_client() -> MagicMock:
    """UserConfigClientのモックを返す"""
    client = MagicMock()
    user_config = MagicMock()
    user_config.learning_enabled = False
    user_config.openai_api_key = "test-api-key"
    user_config.model_name = "gpt-4o"
    client.get_user_config = AsyncMock(return_value=user_config)
    client.get_user_workflow_setting = AsyncMock(
        return_value={"workflow_definition_id": 1}
    )
    return client


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """GitlabClientのモックを返す"""
    client = MagicMock()
    client.get_merge_request = AsyncMock(return_value={
        "iid": 10,
        "title": "テストMR",
        "description": "テスト用MRの説明",
        "source_branch": "feature/test",
    })
    client.create_mr_note = AsyncMock()
    return client


@pytest.fixture
def mock_env_manager() -> MagicMock:
    """ExecutionEnvironmentManagerのモックを返す"""
    manager = MagicMock()
    manager.create_environment = AsyncMock(return_value="env-test-001")
    manager.delete_environment = AsyncMock()
    return manager


@pytest.fixture
def mock_config_manager() -> MagicMock:
    """ConfigManagerのモックを返す"""
    manager = MagicMock()
    manager.get_gitlab_config.return_value = MagicMock(
        bot_label="coding agent",
        done_label="coding agent done",
    )
    manager.get_issue_to_mr_config.return_value = MagicMock(
        branch_prefix="issue-",
        source_branch_template="{prefix}{issue_iid}",
        target_branch="main",
    )
    return manager


def _make_executor_factory() -> MagicMock:
    """ExecutorFactoryのモックを生成する"""
    from consumer.executors.base_executor import PassthroughExecutor

    factory = MagicMock()
    # AF WorkflowBuilder は Executor インスタンスを要求するため、
    # MagicMock ではなく PassthroughExecutor を返す
    factory.create_executor_by_class_name = MagicMock(
        side_effect=lambda class_name, **kwargs: PassthroughExecutor(id=class_name)
    )
    return factory


def _make_agent_factory() -> MagicMock:
    """AgentFactoryのモックを生成する"""
    from consumer.executors.base_executor import PassthroughExecutor

    factory = MagicMock()
    # AF WorkflowBuilder は Executor インスタンスを要求するため、
    # MagicMock ではなく PassthroughExecutor を返す
    factory.create_agent = AsyncMock(
        side_effect=lambda agent_config, **kwargs: PassthroughExecutor(id=agent_config.id)
    )
    return factory


def _make_definition_loader(workflow_def_repo: MagicMock) -> MagicMock:
    """DefinitionLoaderのモックを生成する（実際の定義JSONを使用する）"""
    from consumer.definitions.definition_loader import DefinitionLoader

    loader = DefinitionLoader(workflow_definition_repo=workflow_def_repo)
    return loader


def _make_task_context(
    workflow_definition_id: int = 1,
    mr_iid: int = 10,
    user_email: str = "user@example.com",
) -> Any:
    """テスト用TaskContextを生成する"""
    from shared.models.task import TaskContext

    return TaskContext(
        task_uuid="integration-test-uuid-001",
        task_type="merge_request",
        project_id=1,
        mr_iid=mr_iid,
        user_email=user_email,
        workflow_definition_id=workflow_definition_id,
    )


# ========================================
# TestStandardMrProcessingWorkflowBuild
# ========================================


class TestStandardMrProcessingWorkflowBuild:
    """
    標準MR処理ワークフロー構築テスト

    WorkflowFactoryがstandard_mr_processing定義を正しく読み込み、
    必要な全エージェント・Executorノードを含むワークフローを構築できることを確認する。
    """

    @pytest.fixture
    def workflow_factory(
        self,
        mock_workflow_def_repo: MagicMock,
        mock_user_config_client: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_env_manager: MagicMock,
        mock_config_manager: MagicMock,
    ) -> Any:
        """テスト用WorkflowFactoryインスタンスを返す"""
        from consumer.factories.workflow_factory import WorkflowFactory

        definition_loader = _make_definition_loader(mock_workflow_def_repo)
        executor_factory = _make_executor_factory()
        agent_factory = _make_agent_factory()

        return WorkflowFactory(
            definition_loader=definition_loader,
            executor_factory=executor_factory,
            agent_factory=agent_factory,
            user_config_client=mock_user_config_client,
            gitlab_client=mock_gitlab_client,
            config_manager=mock_config_manager,
        )

    async def test_ワークフローが正常に構築される(
        self,
        workflow_factory: Any,
    ) -> None:
        """standard_mr_processing定義からWorkflowインスタンスが生成されることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        # Workflowが返されることを確認する
        assert workflow is not None
        assert type(workflow).__name__ == "Workflow"

    async def test_エントリポイントが設定される(
        self,
        workflow_factory: Any,
    ) -> None:
        """ワークフローのエントリポイントがuser_resolveに設定されることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        # エントリポイントが設定されていることを確認する
        assert workflow.get_start_executor().id == "user_resolve"

    async def test_全Executorノードが登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        標準フローで使用されるExecutorノード（user_resolve・exec_env_setup_*）が
        全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_executor_nodes = {
            "user_resolve",
            "exec_env_setup_code_gen",
            "exec_env_setup_bug_fix",
            "exec_env_setup_test",
            "exec_env_setup_doc",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_executor_nodes.issubset(registered_nodes), (
            f"未登録のExecutorノード: {expected_executor_nodes - registered_nodes}"
        )

    async def test_task_classifierノードが登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """task_classifierエージェントノードが登録されることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        assert "task_classifier" in workflow.executors

    async def test_4タスク種別のPlanningエージェントが全て登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        コード生成・バグ修正・テスト作成・ドキュメント生成の4タスクに対応する
        Planningエージェントが全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_planning_nodes = {
            "code_generation_planning",
            "bug_fix_planning",
            "test_creation_planning",
            "documentation_planning",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_planning_nodes.issubset(registered_nodes), (
            f"未登録のPlanningノード: {expected_planning_nodes - registered_nodes}"
        )

    async def test_4タスク種別のExecutionエージェントが全て登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        コード生成・バグ修正・テスト作成・ドキュメント生成の4つの実行エージェントが
        全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_execution_nodes = {
            "code_generation",
            "bug_fix",
            "test_creation",
            "documentation",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_execution_nodes.issubset(registered_nodes), (
            f"未登録のExecutionノード: {expected_execution_nodes - registered_nodes}"
        )

    async def test_Reflectionエージェントが全て登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        コード生成・テスト作成・ドキュメント生成のリフレクションエージェントと
        plan_reflectionが全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_reflection_nodes = {
            "code_generation_reflection",
            "test_creation_reflection",
            "documentation_reflection",
            "plan_reflection",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_reflection_nodes.issubset(registered_nodes), (
            f"未登録のReflectionノード: {expected_reflection_nodes - registered_nodes}"
        )

    async def test_Reviewエージェントが全て登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        code_review・documentation_review・test_execution_evaluationが
        全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_review_nodes = {
            "code_review",
            "documentation_review",
            "test_execution_evaluation",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_review_nodes.issubset(registered_nodes), (
            f"未登録のReviewノード: {expected_review_nodes - registered_nodes}"
        )

    async def test_条件ノードが全て登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        タスク分岐・仕様書確認・リフレクション判断・再計画分岐の条件ノードが
        全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_condition_nodes = {
            "task_type_branch",
            "spec_check_branch",
            "code_gen_reflection_branch",
            "test_reflection_branch",
            "doc_reflection_branch",
            "execution_type_branch",
            "replan_branch",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_condition_nodes.issubset(registered_nodes), (
            f"未登録の条件ノード: {expected_condition_nodes - registered_nodes}"
        )

    async def test_エッジが登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """ワークフローにエッジが登録されていることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        # エッジが登録されていることを確認する（標準フローは多数のエッジを持つ）
        assert len(workflow.edge_groups) > 0


# ========================================
# TestStandardMrProcessingDefinitionLoading
# ========================================


class TestStandardMrProcessingDefinitionLoading:
    """
    標準MR処理定義ファイルのロードテスト

    DefinitionLoaderがstandard_mr_processing定義を正しくロード・バリデーションできることを確認する。
    """

    @pytest.fixture
    def definition_loader(
        self,
        mock_workflow_def_repo: MagicMock,
    ) -> Any:
        """テスト用DefinitionLoaderインスタンスを返す"""
        return _make_definition_loader(mock_workflow_def_repo)

    async def test_ワークフロー定義をロードできる(
        self,
        definition_loader: Any,
    ) -> None:
        """load_workflow_definition()で標準MR処理定義がロードできることを確認する"""
        graph_def, agent_def, prompt_def = (
            await definition_loader.load_workflow_definition(1)
        )

        assert graph_def is not None
        assert agent_def is not None
        assert prompt_def is not None

    async def test_グラフ定義のエントリノードが正しい(
        self,
        definition_loader: Any,
    ) -> None:
        """グラフ定義のentry_nodeがuser_resolveであることを確認する"""
        graph_def, _, _ = await definition_loader.load_workflow_definition(1)

        assert graph_def.entry_node == "user_resolve"

    async def test_グラフ定義の全ノードが取得できる(
        self,
        definition_loader: Any,
    ) -> None:
        """グラフ定義から全28ノードが読み込めることを確認する"""
        graph_def, _, _ = await definition_loader.load_workflow_definition(1)

        # 標準フローは28ノードを持つ
        assert len(graph_def.nodes) == 28

    async def test_エージェント定義の全エージェントが取得できる(
        self,
        definition_loader: Any,
    ) -> None:
        """エージェント定義から全16エージェントが読み込めることを確認する"""
        _, agent_def, _ = await definition_loader.load_workflow_definition(1)

        # 標準フローは16エージェントを持つ
        assert len(agent_def.agents) == 16

    async def test_プロンプト定義の全プロンプトが取得できる(
        self,
        definition_loader: Any,
    ) -> None:
        """プロンプト定義から全16プロンプトが読み込めることを確認する"""
        _, _, prompt_def = await definition_loader.load_workflow_definition(1)

        # 標準フローは16プロンプトを持つ
        assert len(prompt_def.prompts) == 16

    async def test_グラフ定義バリデーションが通過する(
        self,
        definition_loader: Any,
    ) -> None:
        """
        validate_graph_definition()でstandard_mr_processing定義が
        バリデーションを通過することを確認する。
        """
        graph_def, _, _ = await definition_loader.load_workflow_definition(1)

        # バリデーションが例外なく完了することを確認する
        definition_loader.validate_graph_definition(graph_def)

    async def test_エージェント定義バリデーションが通過する(
        self,
        definition_loader: Any,
    ) -> None:
        """
        validate_agent_definition()でstandard_mr_processing定義が
        バリデーションを通過することを確認する。
        """
        graph_def, agent_def, _ = await definition_loader.load_workflow_definition(1)

        # バリデーションが例外なく完了することを確認する
        definition_loader.validate_agent_definition(agent_def, graph_def)

    async def test_プロンプト定義バリデーションが通過する(
        self,
        definition_loader: Any,
    ) -> None:
        """
        validate_prompt_definition()でstandard_mr_processing定義が
        バリデーションを通過することを確認する。
        """
        _, agent_def, prompt_def = await definition_loader.load_workflow_definition(1)

        # バリデーションが例外なく完了することを確認する
        definition_loader.validate_prompt_definition(prompt_def, agent_def)


# ========================================
# TestStandardMrProcessingTaskTypeFlow
# ========================================


class TestStandardMrProcessingTaskTypeFlow:
    """
    標準MR処理タスク種別フローテスト

    コード生成・バグ修正・テスト作成・ドキュメント生成の4タスクについて、
    対応するエージェントノードがワークフローに含まれ、定義が整合していることを確認する。
    """

    def test_コード生成タスクのエージェント定義が存在する(self) -> None:
        """
        コード生成タスクに必要なエージェント定義
        （code_generation_planning・code_generation・code_generation_reflection・code_review）
        が全て存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        required_agents = [
            "code_generation_planning",
            "code_generation",
            "code_generation_reflection",
            "code_review",
            "test_execution_evaluation",
        ]
        for agent_id in required_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None, (
                f"コード生成タスクに必要なエージェント定義 '{agent_id}' が見つかりません"
            )

    def test_バグ修正タスクのエージェント定義が存在する(self) -> None:
        """
        バグ修正タスクに必要なエージェント定義
        （bug_fix_planning・bug_fix・code_generation_reflection・code_review）
        が全て存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        required_agents = [
            "bug_fix_planning",
            "bug_fix",
            "code_generation_reflection",
            "code_review",
            "test_execution_evaluation",
        ]
        for agent_id in required_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None, (
                f"バグ修正タスクに必要なエージェント定義 '{agent_id}' が見つかりません"
            )

    def test_テスト作成タスクのエージェント定義が存在する(self) -> None:
        """
        テスト作成タスクに必要なエージェント定義
        （test_creation_planning・test_creation・test_creation_reflection・code_review）
        が全て存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        required_agents = [
            "test_creation_planning",
            "test_creation",
            "test_creation_reflection",
            "code_review",
        ]
        for agent_id in required_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None, (
                f"テスト作成タスクに必要なエージェント定義 '{agent_id}' が見つかりません"
            )

    def test_ドキュメント生成タスクのエージェント定義が存在する(self) -> None:
        """
        ドキュメント生成タスクに必要なエージェント定義
        （documentation_planning・documentation・documentation_reflection・documentation_review）
        が全て存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        required_agents = [
            "documentation_planning",
            "documentation",
            "documentation_reflection",
            "documentation_review",
        ]
        for agent_id in required_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None, (
                f"ドキュメント生成タスクに必要なエージェント定義 '{agent_id}' が見つかりません"
            )

    def test_各エージェントにプロンプト定義が対応している(self) -> None:
        """
        全エージェント定義のprompt_idに対応するプロンプトが
        プロンプト定義ファイルに存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition
        from shared.models.prompt_definition import PromptDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        prompt_def_data = _load_definition("standard_mr_processing_prompts.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)
        prompt_def = PromptDefinition.from_dict(prompt_def_data)

        for agent_config in agent_def.agents:
            prompt_config = prompt_def.get_prompt(agent_config.prompt_id)
            assert prompt_config is not None, (
                f"エージェント '{agent_config.id}' のprompt_id "
                f"'{agent_config.prompt_id}' に対応するプロンプト定義が見つかりません"
            )

    def test_plan_reflectionエージェントが全入力キーを持つ(self) -> None:
        """
        plan_reflectionエージェントがplan_result・todo_list・task_context等の
        必要な入力キーを持つことを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        plan_reflection = agent_def.get_agent("plan_reflection")
        assert plan_reflection is not None

        # plan_reflectionの必須入力キーを確認する
        required_input_keys = {"plan_result", "todo_list", "task_context"}
        actual_input_keys = set(plan_reflection.input_keys)
        assert required_input_keys.issubset(actual_input_keys), (
            f"plan_reflectionの入力キーが不足しています: "
            f"{required_input_keys - actual_input_keys}"
        )

    def test_task_classifierが正しい入出力キーを持つ(self) -> None:
        """
        task_classifierエージェントがtask_contextを入力として受け取り、
        classification_resultを出力することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        task_classifier = agent_def.get_agent("task_classifier")
        assert task_classifier is not None
        assert "task_context" in task_classifier.input_keys
        assert "classification_result" in task_classifier.output_keys

    def test_グラフに終端エッジが存在する(self) -> None:
        """
        グラフ定義にto=NULLの終端エッジが少なくとも1つ存在することを確認する。
        """
        from shared.models.graph_definition import GraphDefinition

        graph_def_data = _load_definition("standard_mr_processing_graph.json")
        graph_def = GraphDefinition.from_dict(graph_def_data)

        terminal_edges = [
            edge for edge in graph_def.edges if edge.to_node is None
        ]
        assert len(terminal_edges) > 0, (
            "グラフ定義に終端エッジ（to=null）が存在しません"
        )

    def test_replan_branchからtask_type_branchへのエッジが存在する(self) -> None:
        """
        再計画時のフロー（replan_branch → task_type_branch）に対応する
        エッジが存在することを確認する。
        """
        from shared.models.graph_definition import GraphDefinition

        graph_def_data = _load_definition("standard_mr_processing_graph.json")
        graph_def = GraphDefinition.from_dict(graph_def_data)

        replan_edges = graph_def.get_outgoing_edges("replan_branch")
        target_nodes = {edge.to_node for edge in replan_edges}

        assert "task_type_branch" in target_nodes, (
            "replan_branchからtask_type_branchへの再計画エッジが存在しません"
        )


# ========================================
# TestStandardMrProcessingContextKeys
# ========================================


class TestStandardMrProcessingContextKeys:
    """
    標準MR処理コンテキストキーテスト

    AGENT_DEFINITION_SPEC.md § 5 に定義されたコンテキストキーが
    正しく各エージェントに設定されていることを確認する。
    """

    def test_execution_resultsが実行エージェントの出力キーに含まれる(self) -> None:
        """
        code_generation・bug_fix・test_creation・documentationの各実行エージェントが
        execution_resultsをoutput_keysに持つことを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        execution_agents = [
            "code_generation",
            "bug_fix",
            "test_creation",
            "documentation",
        ]
        for agent_id in execution_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None
            assert "execution_results" in agent_config.output_keys, (
                f"実行エージェント '{agent_id}' のoutput_keysに"
                f"execution_resultsが含まれていません"
            )

    def test_review_resultがレビューエージェントの出力キーに含まれる(self) -> None:
        """
        code_review・documentation_review・test_execution_evaluationの
        各レビューエージェントがreview_resultをoutput_keysに持つことを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        review_agents = [
            "code_review",
            "documentation_review",
            "test_execution_evaluation",
        ]
        for agent_id in review_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None
            assert "review_result" in agent_config.output_keys, (
                f"レビューエージェント '{agent_id}' のoutput_keysに"
                f"review_resultが含まれていません"
            )

    def test_reflection_resultがplan_reflectionの出力キーに含まれる(self) -> None:
        """
        plan_reflectionエージェントがreflection_resultをoutput_keysに持つことを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        plan_reflection = agent_def.get_agent("plan_reflection")
        assert plan_reflection is not None
        assert "reflection_result" in plan_reflection.output_keys

    def test_plan_resultがplanningエージェントの出力キーに含まれる(self) -> None:
        """
        各planningエージェントがplan_result・todo_listをoutput_keysに持つことを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("standard_mr_processing_agents.json")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        planning_agents = [
            "code_generation_planning",
            "bug_fix_planning",
            "test_creation_planning",
            "documentation_planning",
        ]
        for agent_id in planning_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None
            assert "plan_result" in agent_config.output_keys, (
                f"planningエージェント '{agent_id}' のoutput_keysに"
                f"plan_resultが含まれていません"
            )
            assert "todo_list" in agent_config.output_keys, (
                f"planningエージェント '{agent_id}' のoutput_keysに"
                f"todo_listが含まれていません"
            )
