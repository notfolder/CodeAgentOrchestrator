"""
複数コード生成並列処理フロー（multi_codegen_mr_processing）統合テスト

code_generation_fast・code_generation_standard・code_generation_creativeの
3エージェントが並列実行され、code_reviewによる自動選択・BranchMergeによる
マージが正常に完了することを確認する。

IMPLEMENTATION_PLAN.md フェーズ9-3 に準拠する。
参照ドキュメント:
  - MULTI_MR_PROCESSING_FLOW.md § 3（MR処理の全体フロー）
  - MULTI_MR_PROCESSING_FLOW.md § 4（フェーズ詳細）
  - MULTI_MR_PROCESSING_FLOW.md § 5（コード生成タスクの詳細フロー）
  - MULTI_MR_PROCESSING_FLOW.md § 6（ブランチ管理）
  - AGENT_DEFINITION_SPEC.md § 5（コンテキストキー一覧）
  - AGENT_DEFINITION_SPEC.md § 6（各エージェントノードの詳細説明）
"""

from __future__ import annotations

import json

import yaml
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# 定義ファイルパス
_DEFINITIONS_DIR = Path(__file__).parents[2] / "docs" / "definitions"


# ========================================
# ヘルパー関数・フィクスチャ
# ========================================


def _load_definition(filename: str) -> dict[str, Any]:
    """docs/definitions/ 配下のJSONまたはYAMLファイルを読み込む"""
    filepath = _DEFINITIONS_DIR / filename
    with open(filepath, encoding="utf-8") as f:
        if filepath.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def _make_workflow_definition_row(
    workflow_id: int = 2,
) -> dict[str, Any]:
    """
    テスト用のworkflow_definitionsテーブル行データを生成する。

    複数コード生成並列処理フローの定義を使用する。
    """
    graph_def = _load_definition("multi_codegen_mr_processing_graph.yaml")
    agent_def = _load_definition("multi_codegen_mr_processing_agents.yaml")
    prompt_def = _load_definition("multi_codegen_mr_processing_prompts.yaml")

    return {
        "id": workflow_id,
        "name": "multi_codegen_mr_processing",
        "display_name": "複数コード生成並列処理",
        "description": (
            "3種類のエージェントが並列でコードを生成し、"
            "コードレビューで最良の実装を自動選択するフロー"
        ),
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
    """複数コード生成並列処理ワークフロー定義のDBレコードを返す"""
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
    user_config.openai_api_key = "test-api-key"
    user_config.model_name = "gpt-4o"
    client.get_user_config = AsyncMock(return_value=user_config)
    client.get_user_workflow_setting = AsyncMock(
        return_value={"workflow_definition_id": 2}
    )
    return client


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """GitlabClientのモックを返す"""
    client = MagicMock()
    client.get_merge_request = AsyncMock(
        return_value={
            "iid": 10,
            "title": "テストMR",
            "description": "テスト用MRの説明",
            "source_branch": "feature/test",
        }
    )
    client.create_mr_note = AsyncMock()
    client.create_branch = AsyncMock()
    client.merge_branch = MagicMock()
    client.delete_branch = MagicMock()
    client.branch_exists = MagicMock(return_value=True)
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
    factory.create_executor_by_class_name = MagicMock(
        side_effect=lambda class_name, **kwargs: PassthroughExecutor(id=class_name)
    )
    return factory


def _make_agent_factory() -> MagicMock:
    """AgentFactoryのモックを生成する"""
    from consumer.executors.base_executor import PassthroughExecutor

    factory = MagicMock()
    factory.create_agent = AsyncMock(
        side_effect=lambda agent_config, **kwargs: PassthroughExecutor(
            id=agent_config.id
        )
    )
    return factory


def _make_definition_loader(workflow_def_repo: MagicMock) -> Any:
    """DefinitionLoaderのモックを生成する（実際の定義JSONを使用する）"""
    from consumer.definitions.definition_loader import DefinitionLoader

    return DefinitionLoader(workflow_definition_repo=workflow_def_repo)


def _make_task_context(
    workflow_definition_id: int = 2,
    mr_iid: int = 10,
    username: str = "testuser",
) -> Any:
    """テスト用TaskContextを生成する"""
    from shared.models.task import TaskContext

    return TaskContext(
        task_uuid="integration-multi-test-uuid-001",
        task_type="merge_request",
        project_id=1,
        mr_iid=mr_iid,
        username=username,
        workflow_definition_id=workflow_definition_id,
    )


# ========================================
# TestMultiCodegenWorkflowBuild
# ========================================


class TestMultiCodegenWorkflowBuild:
    """
    複数コード生成並列処理ワークフロー構築テスト

    WorkflowFactoryがmulti_codegen_mr_processing定義を正しく読み込み、
    3つの並列エージェントノードを含むワークフローを構築できることを確認する。
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
        """multi_codegen_mr_processing定義からWorkflowインスタンスが生成されることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        assert workflow is not None
        assert type(workflow).__name__ == "Workflow"

    async def test_3並列コード生成エージェントが全て登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        code_generation_fast・code_generation_standard・code_generation_creativeの
        3並列エージェントが全て登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        parallel_agents = {
            "code_generation_fast",
            "code_generation_standard",
            "code_generation_creative",
        }
        registered_nodes = set(workflow.executors.keys())
        assert parallel_agents.issubset(
            registered_nodes
        ), f"未登録の並列エージェント: {parallel_agents - registered_nodes}"

    async def test_BranchMergeExecutorノードが登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """BranchMergeExecutor（branch_merge_executor）が登録されることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        assert (
            "branch_merge_executor" in workflow.executors
        ), "BranchMergeExecutor（branch_merge_executor）ノードが登録されていません"

    async def test_標準フローと同一のExecutorノードが登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        user_resolve・exec_env_setup_*等の標準フローと共通のExecutorノードが
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
        assert expected_executor_nodes.issubset(
            registered_nodes
        ), f"未登録のExecutorノード: {expected_executor_nodes - registered_nodes}"

    async def test_バグ修正テスト作成ドキュメント生成エージェントが登録される(
        self,
        workflow_factory: Any,
    ) -> None:
        """
        バグ修正・テスト作成・ドキュメント生成の各エージェントが
        標準フローと同一で登録されることを確認する。
        """
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        expected_non_codegen_nodes = {
            "bug_fix",
            "test_creation",
            "documentation",
        }
        registered_nodes = set(workflow.executors.keys())
        assert expected_non_codegen_nodes.issubset(
            registered_nodes
        ), f"未登録のノード: {expected_non_codegen_nodes - registered_nodes}"

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

        assert workflow.get_start_executor().id == "user_resolve"

    async def test_全ノード数が正しい(
        self,
        workflow_factory: Any,
    ) -> None:
        """複数コード生成並列処理フローの全31ノードが登録されることを確認する"""
        task_context = _make_task_context()

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        # multi_codegen_mr_processingグラフは31ノード + progress_finalizeノード = 32ノードを持つ
        assert (
            len(workflow.executors) == 32
        ), f"登録ノード数が不正です: 期待={32}, 実際={len(workflow.executors)}"


# ========================================
# TestMultiCodegenDefinitionLoading
# ========================================


class TestMultiCodegenDefinitionLoading:
    """
    複数コード生成並列処理定義ファイルのロードテスト

    DefinitionLoaderがmulti_codegen_mr_processing定義を正しくロード・
    バリデーションできることを確認する。
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
        """load_workflow_definition()でmulti_codegen定義がロードできることを確認する"""
        graph_def, agent_def, prompt_def = (
            await definition_loader.load_workflow_definition(2)
        )

        assert graph_def is not None
        assert agent_def is not None
        assert prompt_def is not None

    async def test_グラフ定義の全ノードが取得できる(
        self,
        definition_loader: Any,
    ) -> None:
        """グラフ定義から全31ノードが読み込めることを確認する"""
        graph_def, _, _ = await definition_loader.load_workflow_definition(2)

        # multi_codegen_mr_processingフローは31ノードを持つ
        assert len(graph_def.nodes) == 31

    async def test_エージェント定義の全エージェントが取得できる(
        self,
        definition_loader: Any,
    ) -> None:
        """エージェント定義から全18エージェントが読み込めることを確認する"""
        _, agent_def, _ = await definition_loader.load_workflow_definition(2)

        # multi_codegen_mr_processingは18エージェントを持つ
        assert len(agent_def.agents) == 18

    async def test_プロンプト定義の全プロンプトが取得できる(
        self,
        definition_loader: Any,
    ) -> None:
        """プロンプト定義から全18プロンプトが読み込めることを確認する"""
        _, _, prompt_def = await definition_loader.load_workflow_definition(2)

        # multi_codegen_mr_processingは18プロンプトを持つ
        assert len(prompt_def.prompts) == 18

    async def test_グラフ定義バリデーションが通過する(
        self,
        definition_loader: Any,
    ) -> None:
        """
        validate_graph_definition()でmulti_codegen定義が
        バリデーションを通過することを確認する。
        """
        graph_def, _, _ = await definition_loader.load_workflow_definition(2)

        # バリデーションが例外なく完了することを確認する
        definition_loader.validate_graph_definition(graph_def)

    async def test_エージェント定義バリデーションが通過する(
        self,
        definition_loader: Any,
    ) -> None:
        """
        validate_agent_definition()でmulti_codegen定義が
        バリデーションを通過することを確認する。
        """
        graph_def, agent_def, _ = await definition_loader.load_workflow_definition(2)

        # バリデーションが例外なく完了することを確認する
        definition_loader.validate_agent_definition(agent_def, graph_def)

    async def test_プロンプト定義バリデーションが通過する(
        self,
        definition_loader: Any,
    ) -> None:
        """
        validate_prompt_definition()でmulti_codegen定義が
        バリデーションを通過することを確認する。
        """
        _, agent_def, prompt_def = await definition_loader.load_workflow_definition(2)

        # バリデーションが例外なく完了することを確認する
        definition_loader.validate_prompt_definition(prompt_def, agent_def)


# ========================================
# TestParallelCodeGenerationAgentConfig
# ========================================


class TestParallelCodeGenerationAgentConfig:
    """
    並列コード生成エージェント設定テスト

    code_generation_fast・code_generation_standard・code_generation_creativeの
    各エージェントが正しいロール・設定（temperature・timeout・max_iterations）を
    持つことを確認する。
    """

    def test_3並列エージェントの定義が存在する(self) -> None:
        """
        code_generation_fast・code_generation_standard・code_generation_creativeの
        3エージェント定義が存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        parallel_agents = [
            "code_generation_fast",
            "code_generation_standard",
            "code_generation_creative",
        ]
        for agent_id in parallel_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert (
                agent_config is not None
            ), f"並列エージェント定義 '{agent_id}' が見つかりません"

    def test_並列エージェントのロールがexecutionである(self) -> None:
        """
        3並列エージェントのroleが全て'execution'であることを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        parallel_agents = [
            "code_generation_fast",
            "code_generation_standard",
            "code_generation_creative",
        ]
        for agent_id in parallel_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None
            assert agent_config.role == "execution", (
                f"並列エージェント '{agent_id}' のroleが'execution'ではありません: "
                f"{agent_config.role}"
            )

    def test_code_generation_fastのmax_iterationsが30(self) -> None:
        """
        code_generation_fastのmax_iterationsが速度優先の30であることを確認する。
        MULTI_MR_PROCESSING_FLOW.md §2.1 の仕様に準拠する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        agent_config = agent_def.get_agent("code_generation_fast")
        assert agent_config is not None
        assert agent_config.max_iterations == 30, (
            f"code_generation_fastのmax_iterationsが不正です: "
            f"期待=30, 実際={agent_config.max_iterations}"
        )

    def test_code_generation_standardのmax_iterationsが40(self) -> None:
        """
        code_generation_standardのmax_iterationsが品質重視の40であることを確認する。
        MULTI_MR_PROCESSING_FLOW.md §2.1 の仕様に準拠する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        agent_config = agent_def.get_agent("code_generation_standard")
        assert agent_config is not None
        assert agent_config.max_iterations == 40, (
            f"code_generation_standardのmax_iterationsが不正です: "
            f"期待=40, 実際={agent_config.max_iterations}"
        )

    def test_code_generation_creativeのmax_iterationsが40(self) -> None:
        """
        code_generation_creativeのmax_iterationsが代替アプローチ探索の40であることを確認する。
        MULTI_MR_PROCESSING_FLOW.md §2.1 の仕様に準拠する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        agent_config = agent_def.get_agent("code_generation_creative")
        assert agent_config is not None
        assert agent_config.max_iterations == 40, (
            f"code_generation_creativeのmax_iterationsが不正です: "
            f"期待=40, 実際={agent_config.max_iterations}"
        )

    def test_並列エージェントはexecution_resultsを出力する(self) -> None:
        """
        3並列エージェントがexecution_resultsをoutput_keysに持つことを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        parallel_agents = [
            "code_generation_fast",
            "code_generation_standard",
            "code_generation_creative",
        ]
        for agent_id in parallel_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None
            assert "execution_results" in agent_config.output_keys, (
                f"並列エージェント '{agent_id}' のoutput_keysに"
                f"execution_resultsが含まれていません"
            )

    def test_各並列エージェントのプロンプトが存在する(self) -> None:
        """
        code_generation_fast・code_generation_standard・code_generation_creativeの
        各エージェントに対応するプロンプト定義が存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition
        from shared.models.prompt_definition import PromptDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        prompt_def_data = _load_definition("multi_codegen_mr_processing_prompts.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)
        prompt_def = PromptDefinition.from_dict(prompt_def_data)

        parallel_agents = [
            "code_generation_fast",
            "code_generation_standard",
            "code_generation_creative",
        ]
        for agent_id in parallel_agents:
            agent_config = agent_def.get_agent(agent_id)
            assert agent_config is not None
            prompt_config = prompt_def.get_prompt(agent_config.prompt_id)
            assert prompt_config is not None, (
                f"並列エージェント '{agent_id}' の"
                f"prompt_id '{agent_config.prompt_id}' に対応する"
                f"プロンプト定義が見つかりません"
            )


# ========================================
# TestMultiCodegenCodeReviewSelection
# ========================================


class TestMultiCodegenCodeReviewSelection:
    """
    複数コード生成のcode_review自動選択テスト

    code_reviewエージェントがbranch_envsを入力として受け取り、
    selected_implementationを出力する設定になっていることを確認する。
    """

    def test_code_reviewがbranch_envsを入力キーに持つ(self) -> None:
        """
        multi_codegen用のcode_reviewエージェントが
        branch_envsをinput_keysに持つことを確認する。
        AGENT_DEFINITION_SPEC.md § 5 のコンテキストキー設計方針に準拠する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        code_review = agent_def.get_agent("code_review")
        assert code_review is not None
        assert (
            "branch_envs" in code_review.input_keys
        ), "multi_codegen用code_reviewのinput_keysにbranch_envsが含まれていません"

    def test_code_reviewがselected_implementationを出力キーに持つ(self) -> None:
        """
        code_reviewエージェントがselected_implementationをoutput_keysに持つことを確認する。
        自動選択結果をBranchMergeExecutorへ渡すために必要。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        code_review = agent_def.get_agent("code_review")
        assert code_review is not None
        assert (
            "selected_implementation" in code_review.output_keys
        ), "code_reviewのoutput_keysにselected_implementationが含まれていません"

    def test_code_review_multiプロンプトが存在する(self) -> None:
        """
        複数実装を比較するcode_review_multiプロンプトが
        プロンプト定義ファイルに存在することを確認する。
        """
        from shared.models.prompt_definition import PromptDefinition

        prompt_def_data = _load_definition("multi_codegen_mr_processing_prompts.yaml")
        prompt_def = PromptDefinition.from_dict(prompt_def_data)

        # code_reviewエージェントはcode_review_multiプロンプトを使用する
        code_review_multi_prompt = prompt_def.get_prompt("code_review_multi")
        assert (
            code_review_multi_prompt is not None
        ), "code_review_multiプロンプトがプロンプト定義ファイルに存在しません"

    def test_code_reviewエージェントがcode_review_multiプロンプトを参照している(
        self,
    ) -> None:
        """
        multi_codegen用のcode_reviewエージェントのprompt_idが
        code_review_multiを参照していることを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        code_review = agent_def.get_agent("code_review")
        assert code_review is not None
        assert code_review.prompt_id == "code_review_multi", (
            f"code_reviewのprompt_idが不正です: "
            f"期待=code_review_multi, 実際={code_review.prompt_id}"
        )


# ========================================
# TestBranchMergeExecutorIntegration
# ========================================


class TestBranchMergeExecutorIntegration:
    """
    BranchMergeExecutor統合テスト

    selected_implementationに基づいて選択されたブランチが元MRブランチにマージされ、
    非選択ブランチが削除されることを確認する。
    """

    def _make_context(self, state: dict[str, Any]) -> Any:
        """テスト用WorkflowContextを生成する"""
        from agent_framework import InProcRunnerContext, WorkflowContext
        from agent_framework._workflows._state import State
        from executors.branch_merge_executor import BranchMergeExecutor

        # ダミーのgitlab_clientでexecutorインスタンスを作成してcontextに渡す
        from unittest.mock import MagicMock

        dummy_executor = BranchMergeExecutor(gitlab_client=MagicMock())
        s = State()
        for k, v in state.items():
            s.set(k, v)
        s.commit()
        return WorkflowContext(
            executor=dummy_executor,
            source_executor_ids=["test-source"],
            state=s,
            runner_context=InProcRunnerContext(),
        )

    async def test_選択ブランチが元ブランチにマージされる(
        self,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """
        selected_implementationで指定された番号のブランチが
        original_branchにマージされることを確認する。
        MULTI_MR_PROCESSING_FLOW.md § 4.6（ブランチマージフェーズ）に準拠する。
        """
        from executors.branch_merge_executor import BranchMergeExecutor

        ctx = self._make_context(
            {
                "selected_implementation": 2,
                "branch_envs": {
                    1: {"env_id": "env-001", "branch": "feature/test-code-gen-1"},
                    2: {"env_id": "env-002", "branch": "feature/test-code-gen-2"},
                    3: {"env_id": "env-003", "branch": "feature/test-code-gen-3"},
                },
                "original_branch": "feature/test",
                "project_id": 1,
            }
        )

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle({}, ctx)

        # 選択された実装（env-002: feature/test-code-gen-2）がマージされることを確認する
        mock_gitlab_client.merge_branch.assert_called_once_with(
            project_id=1,
            source_branch="feature/test-code-gen-2",
            target_branch="feature/test",
        )

    async def test_非選択ブランチが削除される(
        self,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """
        selected_implementationで選択されなかったブランチが削除されることを確認する。
        MULTI_MR_PROCESSING_FLOW.md § 6.2（ブランチのライフサイクル）に準拠する。
        """
        from executors.branch_merge_executor import BranchMergeExecutor

        ctx = self._make_context(
            {
                "selected_implementation": 2,
                "branch_envs": {
                    1: {"env_id": "env-001", "branch": "feature/test-code-gen-1"},
                    2: {"env_id": "env-002", "branch": "feature/test-code-gen-2"},
                    3: {"env_id": "env-003", "branch": "feature/test-code-gen-3"},
                },
                "original_branch": "feature/test",
                "project_id": 1,
            }
        )

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle({}, ctx)

        # 非選択ブランチ（1, 3）が削除されることを確認する
        deleted_branches = {
            call_args.kwargs["branch_name"]
            for call_args in mock_gitlab_client.delete_branch.call_args_list
        }
        assert deleted_branches == {
            "feature/test-code-gen-1",
            "feature/test-code-gen-3",
        }, f"削除されたブランチが不正です: {deleted_branches}"

    async def test_selected_implementationがない場合はマージをスキップする(
        self,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """
        コンテキストにselected_implementationが存在しない場合（バグ修正・テスト作成・
        ドキュメント生成タスク）はマージ処理をスキップすることを確認する。
        MULTI_MR_PROCESSING_FLOW.md § 4.6（ブランチマージフェーズ）に準拠する。
        """
        from executors.branch_merge_executor import BranchMergeExecutor

        # selected_implementationなし（バグ修正タスク等）
        ctx = self._make_context(
            {
                "original_branch": "feature/bug-fix",
                "project_id": 1,
            }
        )

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle({}, ctx)

        # マージが呼ばれないことを確認する
        mock_gitlab_client.merge_branch.assert_not_called()
        mock_gitlab_client.delete_branch.assert_not_called()

    async def test_merged_branchがコンテキストに保存される(
        self,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """
        マージ完了後にmerged_branchがワークフローコンテキストに保存されることを確認する。
        """
        from executors.branch_merge_executor import BranchMergeExecutor

        ctx = self._make_context(
            {
                "selected_implementation": 1,
                "branch_envs": {
                    1: {"env_id": "env-001", "branch": "feature/test-code-gen-1"},
                    2: {"env_id": "env-002", "branch": "feature/test-code-gen-2"},
                    3: {"env_id": "env-003", "branch": "feature/test-code-gen-3"},
                },
                "original_branch": "feature/test",
                "project_id": 1,
            }
        )

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle({}, ctx)

        # merged_branchが保存されていることを確認する
        merged_branch = ctx.get_state("merged_branch")
        assert merged_branch == "feature/test-code-gen-1"


# ========================================
# TestMultiCodegenVsStandardDifferences
# ========================================


class TestMultiCodegenVsStandardDifferences:
    """
    multi_codegenとstandard_mr_processingの差異テスト

    MULTI_MR_PROCESSING_FLOW.md § 1.2（標準フローとの主な違い）に記載された
    差異が正しく反映されていることを確認する。
    """

    def test_multi_codegenにはcode_generationノードが存在しない(self) -> None:
        """
        multi_codegenグラフには単一のcode_generationノードは存在せず、
        代わりに3並列エージェントが存在することを確認する。
        """
        from shared.models.graph_definition import GraphDefinition

        graph_def_data = _load_definition("multi_codegen_mr_processing_graph.yaml")
        graph_def = GraphDefinition.from_dict(graph_def_data)

        node_ids = {node.id for node in graph_def.nodes}

        # 単一のcode_generationノードは存在しない
        assert (
            "code_generation" not in node_ids
        ), "multi_codegenグラフに単一のcode_generationノードが存在します（不正）"

        # 3並列エージェントが存在する
        assert "code_generation_fast" in node_ids
        assert "code_generation_standard" in node_ids
        assert "code_generation_creative" in node_ids

    def test_multi_codegenにはbranch_merge_executorが存在する(self) -> None:
        """
        multi_codegenグラフにはBranchMergeExecutorノードが存在し、
        標準フローには存在しないことを確認する。
        """
        from shared.models.graph_definition import GraphDefinition

        # multi_codegenグラフ確認
        multi_graph_data = _load_definition("multi_codegen_mr_processing_graph.yaml")
        multi_graph = GraphDefinition.from_dict(multi_graph_data)
        multi_node_ids = {node.id for node in multi_graph.nodes}
        assert (
            "branch_merge_executor" in multi_node_ids
        ), "multi_codegenグラフにbranch_merge_executorが存在しません"

        # 標準グラフ確認（BranchMergeExecutorは存在しない）
        std_graph_data = _load_definition("standard_mr_processing_graph.yaml")
        std_graph = GraphDefinition.from_dict(std_graph_data)
        std_node_ids = {node.id for node in std_graph.nodes}
        assert (
            "branch_merge_executor" not in std_node_ids
        ), "標準グラフにbranch_merge_executorが存在します（不正）"

    def test_exec_env_setup_code_genのenv_countが3(self) -> None:
        """
        multi_codegenのexec_env_setup_code_genノードのenv_countが3であることを確認する。
        3並列エージェントのために3つの実行環境を作成するため。
        MULTI_MR_PROCESSING_FLOW.md § 4.3（並列実行環境セットアップフェーズ）に準拠する。
        """
        from shared.models.graph_definition import GraphDefinition

        graph_def_data = _load_definition("multi_codegen_mr_processing_graph.yaml")
        graph_def = GraphDefinition.from_dict(graph_def_data)

        exec_env_node = graph_def.get_node("exec_env_setup_code_gen")
        assert exec_env_node is not None
        assert exec_env_node.env_count == 3, (
            f"multi_codegenのexec_env_setup_code_genのenv_countが不正です: "
            f"期待=3, 実際={exec_env_node.env_count}"
        )

    def test_標準フローのexec_env_setup_code_genのenv_countが1(self) -> None:
        """
        標準フローのexec_env_setup_code_genノードのenv_countが1であることを確認する。
        標準フローは1エージェントのみのため環境は1つのみ。
        """
        from shared.models.graph_definition import GraphDefinition

        graph_def_data = _load_definition("standard_mr_processing_graph.yaml")
        graph_def = GraphDefinition.from_dict(graph_def_data)

        exec_env_node = graph_def.get_node("exec_env_setup_code_gen")
        assert exec_env_node is not None
        assert exec_env_node.env_count == 1, (
            f"標準フローのexec_env_setup_code_genのenv_countが不正です: "
            f"期待=1, 実際={exec_env_node.env_count}"
        )

    def test_multi_codegenのcode_reviewロールがreviewである(self) -> None:
        """
        multi_codegen用のcode_reviewエージェントのroleがreviewであることを確認する。
        """
        from shared.models.agent_definition import AgentDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)

        code_review = agent_def.get_agent("code_review")
        assert code_review is not None
        assert (
            code_review.role == "review"
        ), f"code_reviewのroleが不正です: 期待=review, 実際={code_review.role}"

    def test_全エージェントにプロンプト定義が対応している(self) -> None:
        """
        multi_codegen定義の全エージェント定義のprompt_idに対応するプロンプトが
        プロンプト定義ファイルに存在することを確認する。
        """
        from shared.models.agent_definition import AgentDefinition
        from shared.models.prompt_definition import PromptDefinition

        agent_def_data = _load_definition("multi_codegen_mr_processing_agents.yaml")
        prompt_def_data = _load_definition("multi_codegen_mr_processing_prompts.yaml")
        agent_def = AgentDefinition.from_dict(agent_def_data)
        prompt_def = PromptDefinition.from_dict(prompt_def_data)

        for agent_config in agent_def.agents:
            prompt_config = prompt_def.get_prompt(agent_config.prompt_id)
            assert prompt_config is not None, (
                f"エージェント '{agent_config.id}' のprompt_id "
                f"'{agent_config.prompt_id}' に対応するプロンプト定義が見つかりません"
            )
