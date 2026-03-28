"""
ConfigurableAgentの単体テスト

AgentNodeConfig・WorkflowContext・ProgressReporterをモックして
ConfigurableAgentのhandle()・store_result()・invoke_mcp_tool()を検証する。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_framework import InProcRunnerContext, WorkflowContext
from agent_framework._workflows._state import State

from agents.configurable_agent import ConfigurableAgent
from shared.models.agent_definition import AgentNodeConfig


# ========================================
# テスト用ヘルパー関数・フィクスチャ
# ========================================


def _make_workflow_context(
    executor_instance: Any, state_data: dict | None = None
) -> WorkflowContext:
    """テスト用WorkflowContextを作成するヘルパー"""
    state = State()
    if state_data:
        for k, v in state_data.items():
            state.set(k, v)
        state.commit()
    return WorkflowContext(
        executor=executor_instance,
        source_executor_ids=["test-source"],
        state=state,
        runner_context=InProcRunnerContext(),
    )


def _make_agent_node_config(
    role: str = "planning",
    input_keys: list[str] | None = None,
    output_keys: list[str] | None = None,
    mcp_servers: list[str] | None = None,
) -> AgentNodeConfig:
    """テスト用AgentNodeConfigを生成する"""
    return AgentNodeConfig(
        id="test-agent-node",
        role=role,
        input_keys=input_keys or ["task_description"],
        output_keys=output_keys or ["planning_result"],
        mcp_servers=mcp_servers or ["text_editor"],
        prompt_id="test-prompt",
    )


@pytest.fixture
def agent_config() -> AgentNodeConfig:
    """テスト用AgentNodeConfigを返す"""
    return _make_agent_node_config()


@pytest.fixture
def mock_agent() -> MagicMock:
    """モックエージェント（LLMエージェント）を返す"""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="LLMの応答テキスト")
    return agent


@pytest.fixture
def mock_progress_reporter() -> MagicMock:
    """モック進捗レポーターを返す"""
    reporter = MagicMock()
    reporter.report_progress = AsyncMock()
    return reporter


@pytest.fixture
def configurable_agent(
    agent_config: AgentNodeConfig,
    mock_agent: MagicMock,
    mock_progress_reporter: MagicMock,
) -> ConfigurableAgent:
    """テスト用ConfigurableAgentを返す"""
    return ConfigurableAgent(
        config=agent_config,
        agent=mock_agent,
        prompt_content="タスク: {task_description}",
        progress_reporter=mock_progress_reporter,
    )


@pytest.fixture
def mock_ctx(configurable_agent: ConfigurableAgent) -> WorkflowContext:
    """テスト用WorkflowContextを返す（初期状態を設定済み）"""
    return _make_workflow_context(
        configurable_agent,
        state_data={
            "task_mr_iid": 42,
            "task_description": "テストタスクの説明",
        },
    )


# ========================================
# TestConfigurableAgentHandle
# ========================================


class TestConfigurableAgentHandle:
    """ConfigurableAgent.handle()のテスト"""

    @pytest.mark.asyncio
    async def test_handleが入力データを取得してプロンプトを生成する(
        self,
        configurable_agent: ConfigurableAgent,
        mock_ctx: WorkflowContext,
        mock_agent: MagicMock,
    ) -> None:
        """handle()を実行し、入力データが正しく取得されてagent.run()が呼ばれることを確認する"""
        await configurable_agent.handle({}, mock_ctx)

        # agent.run()が呼ばれていることを確認する
        mock_agent.run.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["planning", "execution", "reflection", "review"])
    async def test_handleがroleに応じた後処理を実行する(
        self,
        role: str,
        mock_agent: MagicMock,
        mock_progress_reporter: MagicMock,
        mock_ctx: WorkflowContext,
    ) -> None:
        """roleが各値の場合にエラーなくhandle()が実行されることを確認する"""
        config = _make_agent_node_config(role=role)
        agent = ConfigurableAgent(
            config=config,
            agent=mock_agent,
            prompt_content="タスク: {task_description}",
            progress_reporter=mock_progress_reporter,
        )

        # 例外が発生しないことを確認する（handle() は None を返す）
        await agent.handle({}, mock_ctx)

    @pytest.mark.asyncio
    async def test_進捗報告がstart_llm_response_completeの順に呼び出される(
        self,
        configurable_agent: ConfigurableAgent,
        mock_ctx: WorkflowContext,
        mock_progress_reporter: MagicMock,
    ) -> None:
        """progress_reporter.report_progressが3回呼び出されることを確認する"""
        await configurable_agent.handle({}, mock_ctx)

        # start・llm_response・completeの3回呼ばれることを確認する
        assert mock_progress_reporter.report_progress.call_count == 3

        # 呼び出し順序を確認する
        calls = mock_progress_reporter.report_progress.call_args_list
        events = [
            c.kwargs.get("event") or c.args[1] if c.args else c.kwargs.get("event")
            for c in calls
        ]
        # call_argsはkeyword-onlyなので kwargs で確認する
        event_values = [c.kwargs["event"] for c in calls]
        assert event_values[0] == "start"
        assert event_values[1] == "llm_response"
        assert event_values[2] == "complete"

    @pytest.mark.asyncio
    async def test_エラー発生時にevent_errorで進捗報告する(
        self,
        agent_config: AgentNodeConfig,
        mock_progress_reporter: MagicMock,
        mock_ctx: WorkflowContext,
    ) -> None:
        """handle()内でエラーが発生した場合にevent='error'で報告されることを確認する"""
        # agent.run()が例外をスローするモックを作成する
        error_agent = MagicMock()
        error_agent.run = AsyncMock(side_effect=RuntimeError("テストエラー"))

        agent = ConfigurableAgent(
            config=agent_config,
            agent=error_agent,
            prompt_content="テスト",
            progress_reporter=mock_progress_reporter,
        )

        with pytest.raises(RuntimeError, match="テストエラー"):
            await agent.handle({}, mock_ctx)

        # エラー進捗報告が呼ばれていることを確認する
        error_calls = [
            c
            for c in mock_progress_reporter.report_progress.call_args_list
            if c.kwargs.get("event") == "error"
        ]
        assert len(error_calls) == 1


# ========================================
# TestConfigurableAgentMethods
# ========================================


class TestConfigurableAgentMethods:
    """ConfigurableAgentのユーティリティメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_invoke_mcp_toolで未登録ツールはValueErrorが発生する(
        self,
        configurable_agent: ConfigurableAgent,
    ) -> None:
        """config.mcp_serversに含まれないツール名でValueErrorが発生することを確認する"""
        with pytest.raises(ValueError, match="登録されていません"):
            await configurable_agent.invoke_mcp_tool(
                tool_name="unregistered_tool",
                params={"key": "value"},
            )

    @pytest.mark.asyncio
    async def test_invoke_mcp_toolが登録済みツールを正常に呼び出す(
        self,
        agent_config: AgentNodeConfig,
        mock_progress_reporter: MagicMock,
    ) -> None:
        """tool_callメソッドを持つagentに対して登録済みツールを呼び出せることを確認する"""
        expected_result = {"output": "ツール実行結果"}
        # tool_callを持つモックエージェントを作成する（configurable_agentのmock_agentはtool_callなし）
        mock_agent_with_tool = MagicMock()
        mock_agent_with_tool.tool_call = AsyncMock(return_value=expected_result)

        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent_with_tool,
            prompt_content="テスト",
            progress_reporter=mock_progress_reporter,
        )

        # agent_configのmcp_servers=["text_editor"]に登録されているツールを呼び出す
        result = await agent.invoke_mcp_tool("text_editor", {"path": "/workspace"})

        assert result == expected_result
        mock_agent_with_tool.tool_call.assert_called_once_with(
            "text_editor", {"path": "/workspace"}
        )

    @pytest.mark.asyncio
    async def test_invoke_mcp_toolでtool_callなしはNotImplementedErrorが発生する(
        self,
        agent_config: AgentNodeConfig,
        mock_progress_reporter: MagicMock,
    ) -> None:
        """agentにtool_callメソッドがない場合にNotImplementedErrorが発生することを確認する"""
        # tool_callを持たないモックエージェントを作成する（spec(MagicMock)はhasattrでFalseにならないためMagicMock()からspec削除）
        mock_agent_no_tool = MagicMock(spec=[])  # 空のspecでhasattrがFalseになる

        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent_no_tool,
            prompt_content="テスト",
            progress_reporter=mock_progress_reporter,
        )

        with pytest.raises(NotImplementedError):
            await agent.invoke_mcp_tool("text_editor", {"path": "/workspace"})

    @pytest.mark.asyncio
    async def test_store_resultがcontextにoutput_keysを保存する(
        self,
        configurable_agent: ConfigurableAgent,
        mock_ctx: WorkflowContext,
    ) -> None:
        """store_result()がctx.set_state()を正しく呼び出すことを確認する"""
        output_keys = ["planning_result"]
        result_data = {"planning_result": "生成されたプラン"}

        await configurable_agent.store_result(
            output_keys=output_keys,
            result=result_data,
            ctx=mock_ctx,
        )

        # contextに保存されていることを確認する
        saved_value = mock_ctx.get_state("planning_result")
        assert saved_value == "生成されたプラン"


# ========================================
# TestConfigurableAgentContextMethods
# ========================================


class TestConfigurableAgentContextMethods:
    """ConfigurableAgentのコンテキスト関連メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_contextが複数キーの値を返す(
        self,
        configurable_agent: ConfigurableAgent,
        mock_ctx: WorkflowContext,
    ) -> None:
        """get_context()が指定したキー一覧のコンテキスト値をまとめて返すことを確認する"""
        mock_ctx.set_state("key1", "value1")
        mock_ctx.set_state("key2", "value2")

        result = await configurable_agent.get_context(["key1", "key2"], mock_ctx)

        assert result == {"key1": "value1", "key2": "value2"}

    @pytest.mark.asyncio
    async def test_get_contextが存在しないキーはNoneを返す(
        self,
        configurable_agent: ConfigurableAgent,
        mock_ctx: WorkflowContext,
    ) -> None:
        """get_context()で存在しないキーはNoneを返すことを確認する"""
        result = await configurable_agent.get_context(["nonexistent_key"], mock_ctx)

        assert result["nonexistent_key"] is None

    @pytest.mark.asyncio
    async def test_get_chat_historyがproviderからメッセージを取得する(
        self,
        agent_config: AgentNodeConfig,
        mock_agent: MagicMock,
    ) -> None:
        """get_chat_history()がprogress_reporter.chat_history_providerのget_messages()を呼び出すことを確認する"""
        mock_messages = [{"role": "user", "content": "テスト"}]
        mock_history_provider = MagicMock()
        mock_history_provider.get_messages = AsyncMock(return_value=mock_messages)

        mock_reporter = MagicMock()
        mock_reporter.chat_history_provider = mock_history_provider

        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent,
            prompt_content="テスト",
            progress_reporter=mock_reporter,
        )

        result = await agent.get_chat_history("test-session-id")

        assert result == mock_messages
        mock_history_provider.get_messages.assert_called_once_with("test-session-id")

    @pytest.mark.asyncio
    async def test_get_chat_historyがagent_history_providerにフォールバックする(
        self,
        agent_config: AgentNodeConfig,
    ) -> None:
        """progress_reporter.chat_history_providerがNoneの場合、agent.history_providerを使用することを確認する"""
        mock_messages = [{"role": "assistant", "content": "フォールバック応答"}]
        mock_history_provider = MagicMock()
        mock_history_provider.get_messages = AsyncMock(return_value=mock_messages)

        # reporter側はproviderなし、agent側がhistory_providerを持つ状態を作成する
        mock_reporter = MagicMock()
        mock_reporter.chat_history_provider = None
        mock_agent_with_provider = MagicMock()
        mock_agent_with_provider.history_provider = mock_history_provider

        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent_with_provider,
            prompt_content="テスト",
            progress_reporter=mock_reporter,
        )

        result = await agent.get_chat_history("test-session-id")

        assert result == mock_messages
        mock_history_provider.get_messages.assert_called_once_with("test-session-id")

    @pytest.mark.asyncio
    async def test_get_chat_historyがproviderない場合は空リストを返す(
        self,
        agent_config: AgentNodeConfig,
    ) -> None:
        """get_chat_history()でchat_history_providerが存在しない場合に空リストを返すことを確認する"""
        mock_reporter = MagicMock()
        # chat_history_providerをNoneに設定してproviderがない状態を再現する
        mock_reporter.chat_history_provider = None
        # agentもhistory_providerなしに設定する
        mock_agent_no_provider = MagicMock()
        mock_agent_no_provider.history_provider = None

        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent_no_provider,
            prompt_content="テスト",
            progress_reporter=mock_reporter,
        )

        result = await agent.get_chat_history("test-session-id")

        assert result == []


# ========================================
# TestConfigurableAgentTools
# ========================================


class TestConfigurableAgentTools:
    """ConfigurableAgentのtoolsフィールドのテスト（§1.3 保持データ）"""

    def test_toolsフィールドがデフォルトで空リストを返す(
        self,
        agent_config: AgentNodeConfig,
        mock_agent: MagicMock,
        mock_progress_reporter: MagicMock,
    ) -> None:
        """toolsを指定しない場合はデフォルトで空リストが設定されることを確認する"""
        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent,
            prompt_content="テスト",
            progress_reporter=mock_progress_reporter,
        )
        assert agent.tools == []

    def test_toolsフィールドに指定ツールが設定される(
        self,
        agent_config: AgentNodeConfig,
        mock_agent: MagicMock,
        mock_progress_reporter: MagicMock,
    ) -> None:
        """tools引数に指定したリストがself.toolsに保持されることを確認する"""
        mock_tool_1 = MagicMock(name="MCPStdioTool")
        mock_tool_2 = MagicMock(name="FunctionTool")
        tools = [mock_tool_1, mock_tool_2]

        agent = ConfigurableAgent(
            config=agent_config,
            agent=mock_agent,
            prompt_content="テスト",
            progress_reporter=mock_progress_reporter,
            tools=tools,
        )
        assert agent.tools == tools
        assert len(agent.tools) == 2


# ========================================
# TestAgentNodeConfigEnvRef
# ========================================


class TestAgentNodeConfigEnvRef:
    """AgentNodeConfig.env_ref フィールドのテスト（§1.3 保持データ）"""

    def test_env_refデフォルトはNone(self) -> None:
        """env_refを省略した場合はNoneになることを確認する（CLASS_IMPLEMENTATION_SPEC.md § 1.3）"""
        config = AgentNodeConfig(
            id="test-agent",
            role="planning",
            input_keys=["task_description"],
            output_keys=["result"],
            prompt_id="prompt-1",
        )
        assert config.env_ref is None

    def test_env_refにplanを設定できる(self) -> None:
        """env_refに'plan'を設定した場合にその値が保持されることを確認する"""
        config = AgentNodeConfig(
            id="test-agent",
            role="planning",
            input_keys=["task_description"],
            output_keys=["result"],
            prompt_id="prompt-1",
            env_ref="plan",
        )
        assert config.env_ref == "plan"

    def test_env_refに分岐番号を設定できる(self) -> None:
        """env_refに'1'/'2'/'3'を設定した場合にその値が保持されることを確認する"""
        for ref in ("1", "2", "3"):
            config = AgentNodeConfig(
                id="test-agent",
                role="execution",
                input_keys=["task_description"],
                output_keys=["result"],
                prompt_id="prompt-1",
                env_ref=ref,
            )
            assert config.env_ref == ref


# ========================================
# TestReportProgressNodeId
# ========================================


class TestReportProgressNodeId:
    """report_progress()のnode_idフォールバック動作のテスト（§1.4 report_progress）"""

    @pytest.mark.asyncio
    async def test_report_progressがnode_idを優先して使用する(
        self,
        mock_ctx: WorkflowContext,
    ) -> None:
        """config.node_idが設定されている場合はnode_idをprogress_reporterに渡すことを確認する"""
        # graph構築時にnode_idが設定された状態を再現する
        config = AgentNodeConfig(
            id="agent-def-id",
            node_id="graph-node-id",
            role="planning",
            input_keys=["task_description"],
            output_keys=["result"],
            prompt_id="prompt-1",
        )
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="応答テキスト")
        mock_progress_reporter = MagicMock()
        mock_progress_reporter.report_progress = AsyncMock()

        agent = ConfigurableAgent(
            config=config,
            agent=mock_agent,
            prompt_content="タスク: {task_description}",
            progress_reporter=mock_progress_reporter,
        )

        await agent.handle({}, mock_ctx)

        calls = mock_progress_reporter.report_progress.call_args_list
        assert len(calls) >= 1
        # 全ての呼び出しでnode_id="graph-node-id"が使用されることを確認する
        for call in calls:
            assert call.kwargs["node_id"] == "graph-node-id"

    @pytest.mark.asyncio
    async def test_report_progressがnode_id未設定時はidをフォールバック(
        self,
        mock_ctx: WorkflowContext,
    ) -> None:
        """config.node_idがNoneの場合はconfig.idをnode_idとして使用することを確認する"""
        # node_idが設定されていない（デフォルトNone）状態を再現する
        config = AgentNodeConfig(
            id="agent-def-id",
            node_id=None,
            role="planning",
            input_keys=["task_description"],
            output_keys=["result"],
            prompt_id="prompt-1",
        )
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="応答テキスト")
        mock_progress_reporter = MagicMock()
        mock_progress_reporter.report_progress = AsyncMock()

        agent = ConfigurableAgent(
            config=config,
            agent=mock_agent,
            prompt_content="タスク: {task_description}",
            progress_reporter=mock_progress_reporter,
        )

        await agent.handle({}, mock_ctx)

        calls = mock_progress_reporter.report_progress.call_args_list
        assert len(calls) >= 1
        # node_id未設定のため、config.idをnode_idとして代替使用することを確認する
        for call in calls:
            assert call.kwargs["node_id"] == "agent-def-id"
