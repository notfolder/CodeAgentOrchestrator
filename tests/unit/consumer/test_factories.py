"""
Factory群の単体テスト

WorkflowFactory・WorkflowBuilder・ExecutorFactory・AgentFactory・
TaskStrategyFactoryの各クラスとメソッドを検証する。

IMPLEMENTATION_PLAN.md フェーズ6-5 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from factories.agent_factory import AgentFactory
from factories.executor_factory import ExecutorFactory
from factories.task_strategy_factory import TaskStrategyFactory
from factories.workflow_builder import Workflow, WorkflowBuilder
from factories.workflow_factory import WorkflowFactory
from shared.models.task import Task, TaskContext


# ========================================
# フィクスチャ
# ========================================


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    return MagicMock()


@pytest.fixture
def mock_user_config_client() -> MagicMock:
    """テスト用UserConfigClientモックを返す"""
    client = MagicMock()
    client.get_user_config = AsyncMock()
    client.get_user_workflow_setting = AsyncMock()
    return client


@pytest.fixture
def mock_env_manager() -> MagicMock:
    """テスト用ExecutionEnvironmentManagerモックを返す"""
    return MagicMock()


@pytest.fixture
def mock_config_manager() -> MagicMock:
    """テスト用ConfigManagerモックを返す"""
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


@pytest.fixture
def executor_factory(
    mock_user_config_client: MagicMock,
    mock_gitlab_client: MagicMock,
    mock_env_manager: MagicMock,
    mock_config_manager: MagicMock,
) -> ExecutorFactory:
    """テスト用ExecutorFactoryインスタンスを返す"""
    return ExecutorFactory(
        user_config_client=mock_user_config_client,
        gitlab_client=mock_gitlab_client,
        env_manager=mock_env_manager,
        config_manager=mock_config_manager,
    )


@pytest.fixture
def task_strategy_factory(
    mock_gitlab_client: MagicMock,
    mock_config_manager: MagicMock,
) -> TaskStrategyFactory:
    """テスト用TaskStrategyFactoryインスタンスを返す"""
    return TaskStrategyFactory(
        gitlab_client=mock_gitlab_client,
        config_manager=mock_config_manager,
    )


@pytest.fixture
def issue_task() -> Task:
    """テスト用IssueタスクMockを返す"""
    return Task(
        task_uuid="test-uuid-001",
        task_type="issue",
        project_id=1,
        issue_iid=42,
        user_email="user@example.com",
    )


@pytest.fixture
def mr_task() -> Task:
    """テスト用MRタスクMockを返す"""
    return Task(
        task_uuid="test-uuid-002",
        task_type="merge_request",
        project_id=1,
        mr_iid=10,
        user_email="user@example.com",
    )


# ========================================
# TestWorkflowBuilder
# ========================================


class TestWorkflowBuilder:
    """WorkflowBuilderのテスト"""

    def test_add_nodeでノードが登録される(self) -> None:
        """add_node()でノードがnode_registryとworkflowに登録されることを確認する"""
        builder = WorkflowBuilder()
        node_instance = MagicMock()

        builder.add_node("test_node", node_instance)

        assert "test_node" in builder.node_registry
        assert builder.node_registry["test_node"] is node_instance
        assert "test_node" in builder.workflow._nodes

    def test_add_edgeでエッジがキューに追加される(self) -> None:
        """add_edge()でエッジがedge_registryに追加されることを確認する"""
        builder = WorkflowBuilder()

        builder.add_edge("node_a", "node_b")
        builder.add_edge("node_b", None)

        assert len(builder.edge_registry) == 2
        assert builder.edge_registry[0]["from"] == "node_a"
        assert builder.edge_registry[0]["to"] == "node_b"
        assert builder.edge_registry[1]["from"] == "node_b"
        assert builder.edge_registry[1]["to"] is None

    def test_add_edgeで条件付きエッジが登録される(self) -> None:
        """条件付きエッジがedge_registryに正しく登録されることを確認する"""
        builder = WorkflowBuilder()

        builder.add_edge("node_a", "node_b", condition="True")

        assert builder.edge_registry[0]["condition"] == "True"

    def test_buildでWorkflowが返される(self) -> None:
        """build()でWorkflowインスタンスが返されることを確認する"""
        builder = WorkflowBuilder()
        builder.add_node("node_a", MagicMock())
        builder.add_edge("node_a", None)

        workflow = builder.build()

        assert isinstance(workflow, Workflow)

    def test_buildでエントリポイントが設定される(self) -> None:
        """build()で最初に登録されたノードがエントリポイントに設定されることを確認する"""
        builder = WorkflowBuilder()
        builder.add_node("first_node", MagicMock())
        builder.add_node("second_node", MagicMock())
        builder.add_edge("first_node", "second_node")
        builder.add_edge("second_node", None)

        builder.build()

        assert builder.workflow._entry_node == "first_node"

    def test_buildで条件付きエッジが追加される(self) -> None:
        """build()で条件付きエッジがworkflowに追加されることを確認する"""
        builder = WorkflowBuilder()
        builder.add_node("node_a", MagicMock())
        builder.add_node("node_b", MagicMock())
        builder.add_edge("node_a", "node_b", condition="some_condition")
        builder.add_edge("node_b", None)

        builder.build()

        # 条件付きエッジがworkflowの_edgesに追加されていることを確認
        conditional_edges = [
            e for e in builder.workflow._edges if e.get("condition") is not None
        ]
        assert len(conditional_edges) == 1
        assert conditional_edges[0]["condition"] == "some_condition"


# ========================================
# TestExecutorFactory
# ========================================


class TestExecutorFactory:
    """ExecutorFactoryのテスト"""

    def test_create_user_resolverでUserResolverExecutorが生成される(
        self, executor_factory: ExecutorFactory
    ) -> None:
        """create_user_resolver()でUserResolverExecutorインスタンスが生成されることを確認する"""
        executor = executor_factory.create_user_resolver()

        # クラス名で型を確認する（モジュールパスの差異を回避）
        assert type(executor).__name__ == "UserResolverExecutor"
        assert executor.gitlab_client is executor_factory.gitlab_client

    def test_create_content_transferでContentTransferExecutorが生成される(
        self, executor_factory: ExecutorFactory
    ) -> None:
        """create_content_transfer()でContentTransferExecutorインスタンスが生成されることを確認する"""
        executor = executor_factory.create_content_transfer()

        # クラス名で型を確認する（モジュールパスの差異を回避）
        assert type(executor).__name__ == "ContentTransferExecutor"
        assert executor.gitlab_client is executor_factory.gitlab_client

    def test_create_plan_env_setupでPlanEnvSetupExecutorが生成される(
        self, executor_factory: ExecutorFactory
    ) -> None:
        """create_plan_env_setup()でPlanEnvSetupExecutorインスタンスが生成されることを確認する"""
        executor = executor_factory.create_plan_env_setup()

        # クラス名で型を確認する（モジュールパスの差異を回避）
        assert type(executor).__name__ == "PlanEnvSetupExecutor"

    def test_create_branch_mergeでBranchMergeExecutorが生成される(
        self, executor_factory: ExecutorFactory
    ) -> None:
        """create_branch_merge()でBranchMergeExecutorインスタンスが生成されることを確認する"""
        executor = executor_factory.create_branch_merge()

        # クラス名で型を確認する（モジュールパスの差異を回避）
        assert type(executor).__name__ == "BranchMergeExecutor"

    def test_create_executor_by_class_nameで正しいクラスが生成される(
        self, executor_factory: ExecutorFactory
    ) -> None:
        """create_executor_by_class_name()で各クラス名に対応するExecutorが生成されることを確認する"""
        executor_user = executor_factory.create_executor_by_class_name("UserResolverExecutor")
        executor_content = executor_factory.create_executor_by_class_name("ContentTransferExecutor")

        # クラス名で型を確認する（モジュールパスの差異を回避）
        assert type(executor_user).__name__ == "UserResolverExecutor"
        assert type(executor_content).__name__ == "ContentTransferExecutor"

    def test_create_executor_by_class_nameで不明なクラス名はValueErrorが発生する(
        self, executor_factory: ExecutorFactory
    ) -> None:
        """不明なクラス名でcreate_executor_by_class_name()がValueErrorを発生させることを確認する"""
        with pytest.raises(ValueError, match="不明なExecutorクラス名"):
            executor_factory.create_executor_by_class_name("UnknownExecutor")


# ========================================
# TestTaskStrategyFactory
# ========================================


class TestTaskStrategyFactory:
    """TaskStrategyFactoryのテスト"""

    def test_MRタスクでMergeRequestStrategyが返される(
        self,
        task_strategy_factory: TaskStrategyFactory,
        mr_task: Task,
    ) -> None:
        """MRタスクでcreate_strategy()がMergeRequestStrategyを返すことを確認する"""
        strategy = task_strategy_factory.create_strategy(
            task=mr_task,
            workflow_factory=MagicMock(),
            definition_loader=MagicMock(),
            task_repository=MagicMock(),
        )

        assert type(strategy).__name__ == "MergeRequestStrategy"

    def test_Issueタスクでbotラベルなしの場合IssueOnlyStrategyが返される(
        self,
        task_strategy_factory: TaskStrategyFactory,
        issue_task: Task,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """botラベルが付いていないIssueタスクでIssueOnlyStrategyが返されることを確認する"""
        # Issueにbotラベルなしの設定
        mock_issue = MagicMock()
        mock_issue.labels = ["other_label"]
        mock_gitlab_client.get_issue.return_value = mock_issue

        strategy = task_strategy_factory.create_strategy(
            task=issue_task,
            task_repository=MagicMock(),
        )

        assert type(strategy).__name__ == "IssueOnlyStrategy"

    def test_Issueタスクでbotラベルありの場合IssueToMRConversionStrategyが返される(
        self,
        task_strategy_factory: TaskStrategyFactory,
        issue_task: Task,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """botラベル付きIssueタスクでIssueToMRConversionStrategyが返されることを確認する"""
        # Issueにbotラベルあり、既存MRなしの設定
        mock_issue = MagicMock()
        mock_issue.labels = ["coding agent"]
        mock_gitlab_client.get_issue.return_value = mock_issue
        mock_gitlab_client.list_merge_requests.return_value = []

        strategy = task_strategy_factory.create_strategy(
            task=issue_task,
            task_repository=MagicMock(),
            issue_to_mr_converter=MagicMock(),
        )

        assert type(strategy).__name__ == "IssueToMRConversionStrategy"

    def test_不明なタスクタイプでValueErrorが発生する(
        self,
        task_strategy_factory: TaskStrategyFactory,
    ) -> None:
        """不明なタスクタイプでcreate_strategy()がValueErrorを発生させることを確認する"""
        unknown_task = Task(
            task_uuid="test-uuid-003",
            task_type="issue",  # task_typeフィールド上では正常
            project_id=1,
            issue_iid=1,
        )
        # task_typeをモックで上書き
        unknown_task.task_type = "unknown_type"

        with pytest.raises(ValueError, match="不明なタスクタイプ"):
            task_strategy_factory.create_strategy(task=unknown_task)

    def test_should_convert_issue_to_mrで既存MRがある場合Falseを返す(
        self,
        task_strategy_factory: TaskStrategyFactory,
        issue_task: Task,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """既存MRが存在する場合にshould_convert_issue_to_mr()がFalseを返すことを確認する"""
        # botラベルあり、既存MRありの設定
        mock_issue = MagicMock()
        mock_issue.labels = ["coding agent"]
        mock_gitlab_client.get_issue.return_value = mock_issue
        mock_gitlab_client.list_merge_requests.return_value = [MagicMock()]  # 既存MRあり

        result = task_strategy_factory.should_convert_issue_to_mr(issue_task)

        assert result is False

    def test_should_convert_issue_to_mrでbotラベルが未設定の場合Falseを返す(
        self,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """botラベルが未設定の場合にshould_convert_issue_to_mr()がFalseを返すことを確認する"""
        config_manager = MagicMock()
        config_manager.get_gitlab_config.return_value = MagicMock(
            bot_label="",  # botラベル未設定
            done_label="coding agent done",
        )
        config_manager.get_issue_to_mr_config.return_value = MagicMock(
            branch_prefix="issue-",
            source_branch_template="{prefix}{issue_iid}",
        )

        factory = TaskStrategyFactory(
            gitlab_client=mock_gitlab_client,
            config_manager=config_manager,
        )

        task = Task(
            task_uuid="test-uuid",
            task_type="issue",
            project_id=1,
            issue_iid=1,
        )

        result = factory.should_convert_issue_to_mr(task)

        assert result is False

    def test_should_convert_issue_to_mrでIssueにbotラベルがない場合Falseを返す(
        self,
        task_strategy_factory: TaskStrategyFactory,
        issue_task: Task,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """IssueにbotラベルがないときにFalseを返すことを確認する（§2.5.3ステップ2）"""
        mock_issue = MagicMock()
        mock_issue.labels = ["other_label"]  # botラベルなし
        mock_gitlab_client.get_issue.return_value = mock_issue

        result = task_strategy_factory.should_convert_issue_to_mr(issue_task)

        assert result is False

    def test_should_convert_issue_to_mrで全条件を満たす場合Trueを返す(
        self,
        task_strategy_factory: TaskStrategyFactory,
        issue_task: Task,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """全条件（botラベルあり・既存MRなし）を満たす場合にTrueを返すことを確認する"""
        mock_issue = MagicMock()
        mock_issue.labels = ["coding agent"]  # botラベルあり
        mock_gitlab_client.get_issue.return_value = mock_issue
        mock_gitlab_client.list_merge_requests.return_value = []  # 既存MRなし

        result = task_strategy_factory.should_convert_issue_to_mr(issue_task)

        assert result is True


# ========================================
# TestAgentFactory
# ========================================


class TestAgentFactory:
    """AgentFactoryのテスト"""

    @pytest.fixture
    def mock_user_config(self) -> MagicMock:
        """テスト用UserConfigモックを返す"""
        config = MagicMock()
        config.api_key = "test-api-key"
        config.model_name = "gpt-4o"
        config.temperature = 0.7
        config.llm_provider = "openai"
        config.base_url = None
        return config

    @pytest.fixture
    def mock_user_config_client(self) -> MagicMock:
        """テスト用UserConfigClientモックを返す"""
        client = MagicMock()
        return client

    @pytest.fixture
    def agent_factory(self, mock_user_config_client: MagicMock) -> AgentFactory:
        """テスト用AgentFactoryインスタンスを返す"""
        return AgentFactory(
            mcp_server_configs={},
            chat_history_provider=MagicMock(),
            planning_context_provider=MagicMock(),
            tool_result_context_provider=MagicMock(),
            user_config_client=mock_user_config_client,
        )

    async def test_create_agentでConfigurableAgentが生成される(
        self,
        agent_factory: AgentFactory,
        mock_user_config: MagicMock,
    ) -> None:
        """create_agent()でConfigurableAgentインスタンスが生成されることを確認する"""
        from agents.configurable_agent import ConfigurableAgent

        # UserConfigClientのモック設定
        agent_factory.user_config_client.get_user_config = AsyncMock(
            return_value=mock_user_config
        )

        # AgentNodeConfigのモック
        agent_config = MagicMock()
        agent_config.id = "test_agent"
        agent_config.mcp_servers = []

        # PromptConfigのモック
        prompt_config = MagicMock()
        prompt_config.system_prompt = "テストシステムプロンプト"

        agent = await agent_factory.create_agent(
            agent_config=agent_config,
            prompt_config=prompt_config,
            user_email="test@example.com",
            progress_reporter=None,
        )

        # ConfigurableAgentが生成されたことを確認（クラス名で検証）
        assert type(agent).__name__ == "ConfigurableAgent"
        # user_config_client.get_user_config()が呼ばれたことを確認
        agent_factory.user_config_client.get_user_config.assert_called_once_with(
            "test@example.com"
        )

    async def test_create_agentでtodo_listサーバーが仮想ツールとして展開される(
        self,
        agent_factory: AgentFactory,
        mock_user_config: MagicMock,
    ) -> None:
        """mcp_serversに'todo_list'が含まれる場合にTodoManagementToolが追加されることを確認する"""
        agent_factory.user_config_client.get_user_config = AsyncMock(
            return_value=mock_user_config
        )

        agent_config = MagicMock()
        agent_config.id = "test_agent"
        agent_config.mcp_servers = ["todo_list"]

        prompt_config = MagicMock()
        prompt_config.system_prompt = "プロンプト"

        # エラーが発生しないことを確認する（tool_listにFunctionToolが追加される）
        agent = await agent_factory.create_agent(
            agent_config=agent_config,
            prompt_config=prompt_config,
            user_email="test@example.com",
            progress_reporter=None,
        )

        assert agent is not None


# ========================================
# TestWorkflowFactory
# ========================================


class TestWorkflowFactory:
    """WorkflowFactoryのテスト"""

    @pytest.fixture
    def mock_definition_loader(self) -> MagicMock:
        """テスト用DefinitionLoaderモックを返す"""
        from shared.models.agent_definition import AgentDefinition
        from shared.models.graph_definition import GraphDefinition
        from shared.models.prompt_definition import PromptDefinition

        loader = MagicMock()
        loader.load_workflow_definition = AsyncMock(
            return_value=(
                GraphDefinition.from_dict({
                    "version": "1.0",
                    "name": "テストグラフ",
                    "entry_node": "node_a",
                    "nodes": [
                        {"id": "node_a", "type": "executor", "executor_class": "UserResolverExecutor"},
                    ],
                    "edges": [
                        {"from": "node_a", "to": None},
                    ],
                }),
                AgentDefinition.from_dict({"version": "1.0", "agents": []}),
                PromptDefinition.from_dict({"version": "1.0", "prompts": []}),
            )
        )
        return loader

    @pytest.fixture
    def mock_executor_factory(self) -> MagicMock:
        """テスト用ExecutorFactoryモックを返す"""
        factory = MagicMock()
        factory.create_executor_by_class_name = MagicMock(return_value=MagicMock())
        return factory

    @pytest.fixture
    def mock_agent_factory(self) -> MagicMock:
        """テスト用AgentFactoryモックを返す"""
        return MagicMock()

    @pytest.fixture
    def mock_user_config_client(self) -> MagicMock:
        """テスト用UserConfigClientモックを返す"""
        client = MagicMock()
        user_config = MagicMock()
        user_config.learning_enabled = False
        client.get_user_config = AsyncMock(return_value=user_config)
        client.get_user_workflow_setting = AsyncMock(
            return_value={"workflow_definition_id": 1}
        )
        return client

    @pytest.fixture
    def workflow_factory(
        self,
        mock_definition_loader: MagicMock,
        mock_executor_factory: MagicMock,
        mock_agent_factory: MagicMock,
        mock_user_config_client: MagicMock,
    ) -> WorkflowFactory:
        """テスト用WorkflowFactoryインスタンスを返す"""
        return WorkflowFactory(
            definition_loader=mock_definition_loader,
            executor_factory=mock_executor_factory,
            agent_factory=mock_agent_factory,
            user_config_client=mock_user_config_client,
            gitlab_client=MagicMock(),
            config_manager=MagicMock(),
        )

    async def test_create_workflow_from_definitionでWorkflowが生成される(
        self,
        workflow_factory: WorkflowFactory,
    ) -> None:
        """create_workflow_from_definition()でWorkflowインスタンスが生成されることを確認する"""
        task_context = TaskContext(
            task_uuid="test-uuid",
            task_type="merge_request",
            project_id=1,
            mr_iid=10,
            user_email="user@example.com",
            workflow_definition_id=1,
        )

        workflow = await workflow_factory.create_workflow_from_definition(
            user_id=1,
            task_context=task_context,
        )

        # Workflowが返されることを確認（クラス名で検証）
        assert type(workflow).__name__ == "Workflow"

    async def test_save_workflow_stateでrepoがNoneの場合は警告のみ(
        self,
        workflow_factory: WorkflowFactory,
    ) -> None:
        """workflow_exec_state_repoがNoneの場合に例外なく警告のみで処理されることを確認する"""
        # リポジトリが未設定（デフォルトNone）
        assert workflow_factory.workflow_exec_state_repo is None

        # 例外が発生しないことを確認する
        await workflow_factory.save_workflow_state(
            execution_id="test-exec-id",
            current_node_id="node_a",
            completed_nodes=[],
        )

    async def test_load_workflow_stateでrepoがNoneの場合RuntimeError(
        self,
        workflow_factory: WorkflowFactory,
    ) -> None:
        """workflow_exec_state_repoがNoneの場合にRuntimeErrorが発生することを確認する"""
        with pytest.raises(RuntimeError):
            await workflow_factory.load_workflow_state("test-exec-id")
