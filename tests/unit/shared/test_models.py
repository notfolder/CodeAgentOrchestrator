"""
ドメインモデルの単体テスト

Task・GraphDefinition・AgentDefinition・PromptConfigの各Pydanticモデルについて、
バリデーション成功・バリデーションエラー・シリアライズ・デシリアライズを検証する。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from models.task import (
    ClassificationResult,
    ExecutionReflectionResult,
    ExecutionResult,
    PlanAction,
    PlanResult,
    ReflectionResult,
    ReviewIssue,
    ReviewResult,
    SelectedImplementation,
    Task,
    TaskContext,
    TodoItem,
    TodoList,
)
from models.graph_definition import (
    GraphDefinition,
    GraphEdgeDefinition,
    GraphNodeDefinition,
    NodeMetadata,
)
from models.agent_definition import (
    AgentDefinition,
    AgentNodeConfig,
    AgentNodeMetadata,
    TodoListStrategy,
)
from models.prompt_definition import LLMParams, PromptConfig, PromptDefinition


# ========================================
# Task モデルのテスト
# ========================================


class TestTask:
    """Taskモデルのテスト"""

    def test_正常なTaskを作成できる(self) -> None:
        """正常なフィールド値でTaskインスタンスを作成できることを確認する"""
        task = Task(
            task_uuid="550e8400-e29b-41d4-a716-446655440000",
            task_type="issue",
            project_id=123,
            issue_iid=42,
        )
        assert task.task_uuid == "550e8400-e29b-41d4-a716-446655440000"
        assert task.task_type == "issue"
        assert task.project_id == 123
        assert task.issue_iid == 42
        assert task.mr_iid is None

    def test_MRタイプのTaskを作成できる(self) -> None:
        """merge_requestタイプのTaskを作成できることを確認する"""
        task = Task(
            task_uuid="550e8400-e29b-41d4-a716-446655440001",
            task_type="merge_request",
            project_id=456,
            mr_iid=99,
        )
        assert task.task_type == "merge_request"
        assert task.mr_iid == 99

    def test_不正なtask_typeでバリデーションエラーが発生する(self) -> None:
        """無効なtask_typeでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            Task(
                task_uuid="uuid",
                task_type="invalid_type",
                project_id=1,
            )

    def test_created_atが自動設定される(self) -> None:
        """created_atが自動的にdatetimeで設定されることを確認する"""
        task = Task(
            task_uuid="uuid",
            task_type="issue",
            project_id=1,
        )
        assert isinstance(task.created_at, datetime)

    def test_Taskのシリアライズが正しく動作する(self) -> None:
        """model_dump()でTaskが正しくシリアライズされることを確認する"""
        task = Task(
            task_uuid="test-uuid",
            task_type="issue",
            project_id=1,
            issue_iid=10,
        )
        data = task.model_dump()
        assert data["task_uuid"] == "test-uuid"
        assert data["task_type"] == "issue"
        assert data["project_id"] == 1

    def test_TaskContextを正常に作成できる(self) -> None:
        """TaskContextインスタンスを正常に作成できることを確認する"""
        ctx = TaskContext(
            task_uuid="uuid",
            task_type="merge_request",
            project_id=100,
            mr_iid=5,
            username="testuser",
            workflow_definition_id=1,
        )
        assert ctx.task_type == "merge_request"
        assert ctx.username == "testuser"
        assert ctx.workflow_definition_id == 1


class TestClassificationResult:
    """ClassificationResultモデルのテスト"""

    def test_正常なClassificationResultを作成できる(self) -> None:
        """正常なClassificationResultインスタンスを作成できることを確認する"""
        result = ClassificationResult(
            task_type="code_generation",
            confidence=0.95,
            reasoning="コード生成タスクと判定",
            related_files=["src/main.py"],
        )
        assert result.task_type == "code_generation"
        assert result.confidence == 0.95
        assert result.spec_file_exists is False

    def test_confidence範囲外でバリデーションエラー(self) -> None:
        """confidence が0.0〜1.0の範囲外の場合エラーになることを確認する"""
        with pytest.raises(ValidationError):
            ClassificationResult(
                task_type="code_generation",
                confidence=1.5,  # 範囲外
                reasoning="test",
            )

    def test_不正なtask_typeでバリデーションエラー(self) -> None:
        """無効なtask_typeでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            ClassificationResult(
                task_type="unknown_type",
                confidence=0.9,
                reasoning="test",
            )

    def test_全task_typeが有効である(self) -> None:
        """全ての有効なtask_typeが受け付けられることを確認する"""
        for task_type in [
            "code_generation",
            "bug_fix",
            "test_creation",
            "documentation",
        ]:
            result = ClassificationResult(
                task_type=task_type,
                confidence=0.8,
                reasoning="test",
            )
            assert result.task_type == task_type


class TestPlanResult:
    """PlanResultモデルのテスト"""

    def test_正常なPlanResultを作成できる(self) -> None:
        """正常なPlanResultインスタンスを作成できることを確認する"""
        action = PlanAction(
            id="action_1",
            description="テスト実装",
            agent="code_generation_agent",
            tool="create_file",
            target_file="src/test.py",
        )
        plan = PlanResult(
            plan_id="plan-uuid-001",
            task_summary="新機能の実装",
            actions=[action],
        )
        assert plan.plan_id == "plan-uuid-001"
        assert len(plan.actions) == 1
        assert plan.actions[0].id == "action_1"

    def test_空のPlanResultが作成できる(self) -> None:
        """最小フィールドのみでPlanResultを作成できることを確認する"""
        plan = PlanResult(plan_id="plan-001")
        assert plan.files_to_create == []
        assert plan.files_to_modify == []
        assert plan.actions == []


class TestExecutionResult:
    """ExecutionResultモデルのテスト"""

    def test_正常なExecutionResultを作成できる(self) -> None:
        """正常なExecutionResultインスタンスを作成できることを確認する"""
        result = ExecutionResult(
            environment_id="env-001",
            branch_name="issue-42",
            changed_files=["src/main.py"],
            summary="ファイルを更新しました",
        )
        assert result.environment_id == "env-001"
        assert result.branch_name == "issue-42"
        assert isinstance(result.created_at, datetime)


class TestReflectionResult:
    """ReflectionResultモデルのテスト"""

    def test_正常なReflectionResultを作成できる(self) -> None:
        """正常なReflectionResultインスタンスを作成できることを確認する"""
        result = ReflectionResult(
            action="proceed",
            status="success",
            confidence=0.9,
        )
        assert result.action == "proceed"
        assert result.status == "success"

    def test_不正なactionでバリデーションエラー(self) -> None:
        """無効なactionでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            ReflectionResult(
                action="invalid_action",
                status="success",
                confidence=0.9,
            )


class TestTodoList:
    """TodoListモデルのテスト"""

    def test_正常なTodoListを作成できる(self) -> None:
        """正常なTodoListインスタンスを作成できることを確認する"""
        todo_list = TodoList(
            items=[
                TodoItem(
                    id="todo-001",
                    description="テストを書く",
                    status="pending",
                )
            ]
        )
        assert len(todo_list.items) == 1
        assert todo_list.items[0].id == "todo-001"


# ========================================
# GraphDefinition モデルのテスト
# ========================================


class TestGraphDefinition:
    """GraphDefinitionモデルのテスト"""

    @pytest.fixture
    def sample_graph_data(self) -> dict:
        """テスト用のグラフ定義データ"""
        return {
            "version": "1.0",
            "name": "テストグラフ",
            "description": "テスト用グラフ定義",
            "entry_node": "node_a",
            "nodes": [
                {
                    "id": "node_a",
                    "type": "executor",
                    "executor_class": "TaskContextInitExecutor",
                    "label": "タスクコンテキスト初期化",
                },
                {
                    "id": "node_b",
                    "type": "agent",
                    "agent_definition_id": "task_classifier",
                    "label": "タスク分類",
                },
            ],
            "edges": [
                {"from": "node_a", "to": "node_b"},
                {"from": "node_b", "to": None},
            ],
        }

    def test_正常なGraphDefinitionを作成できる(self, sample_graph_data: dict) -> None:
        """正常なGraphDefinitionインスタンスを作成できることを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        assert graph.version == "1.0"
        assert graph.name == "テストグラフ"
        assert graph.entry_node == "node_a"
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 2

    def test_get_nodeで正しいノードを取得できる(self, sample_graph_data: dict) -> None:
        """get_node()で指定IDのノードが取得できることを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        node = graph.get_node("node_a")
        assert node is not None
        assert node.type == "executor"
        assert node.executor_class == "TaskContextInitExecutor"

    def test_get_nodeで存在しないノードはNoneを返す(
        self, sample_graph_data: dict
    ) -> None:
        """get_node()で存在しないIDに対してNoneを返すことを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        assert graph.get_node("nonexistent") is None

    def test_get_outgoing_edgesで送出エッジを取得できる(
        self, sample_graph_data: dict
    ) -> None:
        """get_outgoing_edges()で指定ノードの送出エッジが取得できることを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        edges = graph.get_outgoing_edges("node_a")
        assert len(edges) == 1
        assert edges[0].to_node == "node_b"

    def test_エッジのtoがnullの場合ワークフロー終了を表す(
        self, sample_graph_data: dict
    ) -> None:
        """to=null のエッジがワークフロー終了を意味することを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        edges = graph.get_outgoing_edges("node_b")
        assert len(edges) == 1
        assert edges[0].to_node is None

    def test_agentノードにagent_definition_idが設定される(
        self, sample_graph_data: dict
    ) -> None:
        """agentタイプのノードにagent_definition_idが設定されることを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        node = graph.get_node("node_b")
        assert node is not None
        assert node.agent_definition_id == "task_classifier"

    def test_GraphDefinitionのシリアライズが正しく動作する(
        self, sample_graph_data: dict
    ) -> None:
        """model_dump()でGraphDefinitionが正しくシリアライズされることを確認する"""
        graph = GraphDefinition.from_dict(sample_graph_data)
        data = graph.model_dump(by_alias=True)
        assert data["version"] == "1.0"
        assert len(data["nodes"]) == 2


# ========================================
# AgentDefinition モデルのテスト
# ========================================


class TestAgentDefinition:
    """AgentDefinitionモデルのテスト"""

    @pytest.fixture
    def sample_agent_data(self) -> dict:
        """テスト用のエージェント定義データ"""
        return {
            "version": "1.0",
            "agents": [
                {
                    "id": "task_classifier",
                    "role": "planning",
                    "input_keys": ["task_context"],
                    "output_keys": ["classification_result"],
                    "mcp_servers": ["text_editor"],
                    "prompt_id": "task_classifier",
                    "max_iterations": 5,
                    "timeout_seconds": 120,
                    "description": "タスク種別分類エージェント",
                },
                {
                    "id": "code_generation",
                    "role": "execution",
                    "input_keys": ["plan_result", "task_context"],
                    "output_keys": ["execution_results"],
                    "mcp_servers": ["text_editor", "command_executor"],
                    "prompt_id": "code_generation",
                    "max_iterations": 20,
                    "timeout_seconds": 600,
                },
            ],
        }

    def test_正常なAgentDefinitionを作成できる(self, sample_agent_data: dict) -> None:
        """正常なAgentDefinitionインスタンスを作成できることを確認する"""
        agent_def = AgentDefinition.from_dict(sample_agent_data)
        assert agent_def.version == "1.0"
        assert len(agent_def.agents) == 2

    def test_get_agentで正しいエージェントを取得できる(
        self, sample_agent_data: dict
    ) -> None:
        """get_agent()で指定IDのエージェント設定が取得できることを確認する"""
        agent_def = AgentDefinition.from_dict(sample_agent_data)
        agent = agent_def.get_agent("task_classifier")
        assert agent is not None
        assert agent.role == "planning"
        assert "text_editor" in agent.mcp_servers

    def test_get_agentで存在しないエージェントはNoneを返す(
        self, sample_agent_data: dict
    ) -> None:
        """get_agent()で存在しないIDに対してNoneを返すことを確認する"""
        agent_def = AgentDefinition.from_dict(sample_agent_data)
        assert agent_def.get_agent("nonexistent") is None

    def test_不正なroleでバリデーションエラー(self) -> None:
        """無効なroleでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            AgentNodeConfig(
                id="test",
                role="invalid_role",
                input_keys=[],
                output_keys=[],
                prompt_id="test",
            )

    def test_全ての有効なroleが受け付けられる(self) -> None:
        """全ての有効なroleが受け付けられることを確認する"""
        for role in ["planning", "reflection", "execution", "review"]:
            config = AgentNodeConfig(
                id=f"agent_{role}",
                role=role,
                input_keys=["input"],
                output_keys=["output"],
                prompt_id=f"prompt_{role}",
            )
            assert config.role == role

    def test_mcp_serversのデフォルトは空リスト(self) -> None:
        """mcp_serversが省略された場合デフォルトで空リストになることを確認する"""
        config = AgentNodeConfig(
            id="test",
            role="planning",
            input_keys=[],
            output_keys=[],
            prompt_id="test",
        )
        assert config.mcp_servers == []

    def test_max_iterationsのデフォルト値が20(self) -> None:
        """max_iterationsのデフォルト値が20であることを確認する"""
        config = AgentNodeConfig(
            id="test",
            role="planning",
            input_keys=[],
            output_keys=[],
            prompt_id="test",
        )
        assert config.max_iterations == 20

    def test_timeout_secondsのデフォルト値が600(self) -> None:
        """timeout_secondsのデフォルト値が600であることを確認する"""
        config = AgentNodeConfig(
            id="test",
            role="planning",
            input_keys=[],
            output_keys=[],
            prompt_id="test",
        )
        assert config.timeout_seconds == 600

    def test_planningロールでtodo_list_strategyを設定できる(self) -> None:
        """planningロールのエージェントにtodo_list_strategyが設定できることを確認する"""
        config = AgentNodeConfig(
            id="planning_agent",
            role="planning",
            input_keys=["task_context"],
            output_keys=["plan_result"],
            prompt_id="planning",
            metadata=AgentNodeMetadata(
                todo_list_strategy=TodoListStrategy(
                    on_initial_plan="create",
                    preserve_completed=True,
                    preserve_in_progress=False,
                )
            ),
        )
        assert config.metadata.todo_list_strategy is not None
        assert config.metadata.todo_list_strategy.on_initial_plan == "create"


# ========================================
# PromptDefinition モデルのテスト
# ========================================


class TestPromptDefinition:
    """PromptDefinitionモデルのテスト"""

    @pytest.fixture
    def sample_prompt_data(self) -> dict:
        """テスト用のプロンプト定義データ"""
        return {
            "version": "1.0",
            "default_llm_params": {
                "model": "gpt-4o",
                "temperature": 0.2,
                "max_tokens": 4096,
                "top_p": 1.0,
            },
            "prompts": [
                {
                    "id": "task_classifier",
                    "description": "タスク種別分類エージェントのプロンプト",
                    "system_prompt": "あなたはタスク分類エージェントです。",
                    "llm_params": {
                        "temperature": 0.1,
                        "max_tokens": 1024,
                    },
                },
                {
                    "id": "code_generation",
                    "description": "コード生成エージェントのプロンプト",
                    "system_prompt": "あなたはコード生成エージェントです。",
                },
            ],
        }

    def test_正常なPromptDefinitionを作成できる(self, sample_prompt_data: dict) -> None:
        """正常なPromptDefinitionインスタンスを作成できることを確認する"""
        prompt_def = PromptDefinition.from_dict(sample_prompt_data)
        assert prompt_def.version == "1.0"
        assert len(prompt_def.prompts) == 2

    def test_get_promptで正しいプロンプトを取得できる(
        self, sample_prompt_data: dict
    ) -> None:
        """get_prompt()で指定IDのプロンプト設定が取得できることを確認する"""
        prompt_def = PromptDefinition.from_dict(sample_prompt_data)
        prompt = prompt_def.get_prompt("task_classifier")
        assert prompt is not None
        assert "タスク分類エージェント" in prompt.system_prompt

    def test_get_promptで存在しないプロンプトはNoneを返す(
        self, sample_prompt_data: dict
    ) -> None:
        """get_prompt()で存在しないIDに対してNoneを返すことを確認する"""
        prompt_def = PromptDefinition.from_dict(sample_prompt_data)
        assert prompt_def.get_prompt("nonexistent") is None

    def test_get_effective_llm_paramsでデフォルトとエージェント固有パラメータがマージされる(
        self, sample_prompt_data: dict
    ) -> None:
        """
        get_effective_llm_params()でデフォルトパラメータと
        エージェント固有パラメータがマージされることを確認する
        """
        prompt_def = PromptDefinition.from_dict(sample_prompt_data)
        params = prompt_def.get_effective_llm_params("task_classifier")
        # デフォルト: model=gpt-4o, temperature=0.2, max_tokens=4096
        # task_classifierの上書き: temperature=0.1, max_tokens=1024
        assert params.model == "gpt-4o"  # デフォルトを引き継ぐ
        assert params.temperature == pytest.approx(0.1)  # 上書きされる
        assert params.max_tokens == 1024  # 上書きされる

    def test_エージェント固有パラメータなしはデフォルトをそのまま使用する(
        self, sample_prompt_data: dict
    ) -> None:
        """
        llm_params が未設定のプロンプトでは
        default_llm_params がそのまま使用されることを確認する
        """
        prompt_def = PromptDefinition.from_dict(sample_prompt_data)
        params = prompt_def.get_effective_llm_params("code_generation")
        assert params.model == "gpt-4o"
        assert params.temperature == pytest.approx(0.2)
        assert params.max_tokens == 4096

    def test_LLMParamsのtemperature範囲外でバリデーションエラー(self) -> None:
        """temperatureが0.0〜2.0の範囲外の場合エラーになることを確認する"""
        with pytest.raises(ValidationError):
            LLMParams(temperature=3.0)

    def test_LLMParamsのtop_p範囲外でバリデーションエラー(self) -> None:
        """top_pが0.0〜1.0の範囲外の場合エラーになることを確認する"""
        with pytest.raises(ValidationError):
            LLMParams(top_p=1.5)

    def test_PromptDefinitionのシリアライズが正しく動作する(
        self, sample_prompt_data: dict
    ) -> None:
        """model_dump()でPromptDefinitionが正しくシリアライズされることを確認する"""
        prompt_def = PromptDefinition.from_dict(sample_prompt_data)
        data = prompt_def.model_dump()
        assert data["version"] == "1.0"
        assert len(data["prompts"]) == 2
        assert data["prompts"][0]["id"] == "task_classifier"

    def test_default_llm_paramsなしでも動作する(self) -> None:
        """default_llm_params が省略された場合も正常に動作することを確認する"""
        data = {
            "version": "1.0",
            "prompts": [
                {
                    "id": "test",
                    "system_prompt": "テストプロンプト",
                }
            ],
        }
        prompt_def = PromptDefinition.from_dict(data)
        assert prompt_def.default_llm_params is None
        params = prompt_def.get_effective_llm_params("test")
        # デフォルトがない場合は全フィールドがNone
        assert params.model is None


# ========================================
# SelectedImplementation・ExecutionReflectionResult の追加テスト
# ========================================


class TestSelectedImplementation:
    """SelectedImplementationモデルのテスト"""

    def test_正常なSelectedImplementationを作成できる(self) -> None:
        """正常なSelectedImplementationインスタンスを作成できることを確認する"""
        selected = SelectedImplementation(
            environment_id="env-002",
            branch_name="issue-42-standard",
            selection_reason="テストカバレッジが最も高い実装を選択",
            quality_score=0.92,
            evaluation_details={"test_coverage": 0.95, "lint_errors": 0},
        )
        assert selected.environment_id == "env-002"
        assert selected.branch_name == "issue-42-standard"
        assert selected.quality_score == pytest.approx(0.92)
        assert selected.evaluation_details["test_coverage"] == pytest.approx(0.95)

    def test_quality_score範囲外でバリデーションエラー(self) -> None:
        """quality_scoreが0.0〜1.0の範囲外でValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            SelectedImplementation(
                environment_id="env-001",
                branch_name="branch",
                selection_reason="test",
                quality_score=1.5,  # 範囲外
            )

    def test_quality_scoreが0_0の境界値を受け付ける(self) -> None:
        """quality_scoreが0.0（最小値）でも受け付けられることを確認する"""
        selected = SelectedImplementation(
            environment_id="env-001",
            branch_name="branch",
            selection_reason="テスト失敗",
            quality_score=0.0,
        )
        assert selected.quality_score == 0.0

    def test_quality_scoreが1_0の境界値を受け付ける(self) -> None:
        """quality_scoreが1.0（最大値）でも受け付けられることを確認する"""
        selected = SelectedImplementation(
            environment_id="env-001",
            branch_name="branch",
            selection_reason="完璧な実装",
            quality_score=1.0,
        )
        assert selected.quality_score == 1.0

    def test_evaluation_detailsのデフォルトが空辞書(self) -> None:
        """evaluation_detailsが省略された場合デフォルトで空辞書になることを確認する"""
        selected = SelectedImplementation(
            environment_id="env-001",
            branch_name="branch",
            selection_reason="テスト",
            quality_score=0.8,
        )
        assert selected.evaluation_details == {}


class TestExecutionReflectionResult:
    """ExecutionReflectionResultモデルのテスト"""

    def test_正常なExecutionReflectionResultを作成できる(self) -> None:
        """正常なExecutionReflectionResultインスタンスを作成できることを確認する"""
        result = ExecutionReflectionResult(
            action="proceed",
            status="success",
            confidence=0.95,
        )
        assert result.action == "proceed"
        assert result.status == "success"
        assert result.confidence == pytest.approx(0.95)
        assert result.issues == []
        assert result.suggestions == []

    def test_全ての有効なactionが受け付けられる(self) -> None:
        """proceed・revise・abort の全てのactionが受け付けられることを確認する"""
        for action in ["proceed", "revise", "abort"]:
            result = ExecutionReflectionResult(
                action=action,
                status="success",
                confidence=0.8,
            )
            assert result.action == action

    def test_全ての有効なstatusが受け付けられる(self) -> None:
        """success・needs_revision・failed の全てのstatusが受け付けられることを確認する"""
        for status in ["success", "needs_revision", "failed"]:
            result = ExecutionReflectionResult(
                action="proceed",
                status=status,
                confidence=0.8,
            )
            assert result.status == status

    def test_不正なactionでバリデーションエラー(self) -> None:
        """無効なactionでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            ExecutionReflectionResult(
                action="retry",  # 無効なaction（ReflectionResultのactionと混同しないこと）
                status="success",
                confidence=0.8,
            )

    def test_不正なstatusでバリデーションエラー(self) -> None:
        """無効なstatusでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            ExecutionReflectionResult(
                action="proceed",
                status="unknown_status",
                confidence=0.8,
            )

    def test_confidence範囲外でバリデーションエラー(self) -> None:
        """confidenceが0.0〜1.0の範囲外でValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            ExecutionReflectionResult(
                action="proceed",
                status="success",
                confidence=1.1,  # 範囲外
            )

    def test_issues_とsuggestionsを含むExecutionReflectionResultを作成できる(
        self,
    ) -> None:
        """issuesとsuggestionsを含むインスタンスを作成できることを確認する"""
        result = ExecutionReflectionResult(
            action="revise",
            status="needs_revision",
            issues=["テストが失敗しています", "型ヒントが不足しています"],
            suggestions=["pytest を実行して修正箇所を確認してください"],
            confidence=0.4,
        )
        assert len(result.issues) == 2
        assert len(result.suggestions) == 1
        assert result.action == "revise"


# ========================================
# NodeMetadata・GraphNodeDefinition の追加テスト
# ========================================


class TestNodeMetadataAdditional:
    """NodeMetadataの追加テスト（カスタムフィールド・env_count制約など）"""

    def test_NodeMetadataにカスタムフィールドを追加できる(self) -> None:
        """extra='allow' により任意の追加フィールドを持てることを確認する"""
        metadata = NodeMetadata(
            check_comments_before=True,
            comment_redirect_to="plan_reflection",
            custom_field="custom_value",  # type: ignore[call-arg]
            another_field=42,  # type: ignore[call-arg]
        )
        assert metadata.check_comments_before is True
        assert metadata.comment_redirect_to == "plan_reflection"
        # extra フィールドがモデルに保持されている
        assert metadata.model_extra is not None
        assert metadata.model_extra.get("custom_field") == "custom_value"
        assert metadata.model_extra.get("another_field") == 42

    def test_NodeMetadataのデフォルト値が正しい(self) -> None:
        """NodeMetadataのデフォルト値を確認する"""
        metadata = NodeMetadata()
        assert metadata.check_comments_before is False
        assert metadata.comment_redirect_to is None
        assert metadata.preserve_context == []
        assert metadata.max_retries == 3

    def test_max_retriesの境界値0が受け付けられる(self) -> None:
        """max_retriesが0（ge=0の最小値）でも受け付けられることを確認する"""
        metadata = NodeMetadata(max_retries=0)
        assert metadata.max_retries == 0

    def test_max_retriesが負の値でバリデーションエラー(self) -> None:
        """max_retriesが負の値でValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            NodeMetadata(max_retries=-1)


class TestGraphNodeDefinitionAdditional:
    """GraphNodeDefinitionの追加テスト（env_ref・env_count・conditionノードなど）"""

    def test_env_refを設定できる(self) -> None:
        """env_ref フィールドを正しく設定できることを確認する"""
        node = GraphNodeDefinition(
            id="exec_node",
            type="agent",
            agent_definition_id="code_generation",
            env_ref="1",
        )
        assert node.env_ref == "1"

    def test_env_refがplanの場合を設定できる(self) -> None:
        """env_ref='plan' を設定できることを確認する"""
        node = GraphNodeDefinition(
            id="plan_node",
            type="executor",
            executor_class="PlanEnvSetupExecutor",
            env_ref="plan",
        )
        assert node.env_ref == "plan"

    def test_env_countを設定できる(self) -> None:
        """env_count フィールドを正しく設定できることを確認する"""
        node = GraphNodeDefinition(
            id="exec_env_setup",
            type="executor",
            executor_class="ExecEnvSetupExecutor",
            env_count=3,
        )
        assert node.env_count == 3

    def test_env_countが0以下でバリデーションエラー(self) -> None:
        """env_countが0以下（ge=1に違反）でValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            GraphNodeDefinition(
                id="node",
                type="executor",
                executor_class="ExecEnvSetupExecutor",
                env_count=0,  # ge=1 に違反
            )

    def test_conditionノードタイプを設定できる(self) -> None:
        """type='condition' のノードを作成できることを確認する"""
        node = GraphNodeDefinition(
            id="branch_node",
            type="condition",
            label="分岐判定",
        )
        assert node.type == "condition"
        assert node.agent_definition_id is None
        assert node.executor_class is None

    def test_不正なtypeでバリデーションエラー(self) -> None:
        """無効なtypeでValidationErrorが発生することを確認する"""
        with pytest.raises(ValidationError):
            GraphNodeDefinition(
                id="node",
                type="invalid_type",
            )

    def test_conditionエッジを持つグラフを作成できる(self) -> None:
        """condition付きエッジを含むGraphDefinitionを作成できることを確認する"""
        data = {
            "version": "1.0",
            "name": "条件分岐テスト",
            "entry_node": "start",
            "nodes": [
                {
                    "id": "start",
                    "type": "executor",
                    "executor_class": "TaskContextInitExecutor",
                },
                {"id": "node_a", "type": "agent", "agent_definition_id": "agent_a"},
                {"id": "node_b", "type": "agent", "agent_definition_id": "agent_b"},
            ],
            "edges": [
                {
                    "from": "start",
                    "to": "node_a",
                    "condition": "classification_result == 'code_generation'",
                    "label": "コード生成へ",
                },
                {
                    "from": "start",
                    "to": "node_b",
                    "condition": "classification_result == 'bug_fix'",
                    "label": "バグ修正へ",
                },
                {"from": "node_a", "to": None},
                {"from": "node_b", "to": None},
            ],
        }
        graph = GraphDefinition.from_dict(data)
        edges_from_start = graph.get_outgoing_edges("start")
        assert len(edges_from_start) == 2
        assert (
            edges_from_start[0].condition
            == "classification_result == 'code_generation'"
        )
        assert edges_from_start[1].condition == "classification_result == 'bug_fix'"
