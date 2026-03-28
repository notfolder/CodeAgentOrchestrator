"""
MCPClientFactoryの単体テスト

MCPServerConfigのモックを用いて、MCPClientFactoryが
正しいAgent Framework MCPStdioToolを生成することを検証する。
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_framework import MCPStdioTool

from config.models import MCPServerConfig
from mcp.mcp_client_factory import MCPClientFactory


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def command_executor_config() -> MCPServerConfig:
    """command-executor用MCPServerConfigを返す"""
    return MCPServerConfig(
        name="command-executor",
        command=["python", "mcp/command_executor.py"],
        env={"DOCKER_ENABLED": "true"},
    )


@pytest.fixture
def text_editor_config() -> MCPServerConfig:
    """text-editor用MCPServerConfigを返す"""
    return MCPServerConfig(
        name="text-editor",
        command=["npx", "@modelcontextprotocol/server-text-editor"],
        env={"ALLOWED_DIRECTORIES": "/workspace"},
    )


@pytest.fixture
def factory(
    command_executor_config: MCPServerConfig,
    text_editor_config: MCPServerConfig,
) -> MCPClientFactory:
    """2つのサーバー設定を持つMCPClientFactoryを返す"""
    return MCPClientFactory(
        server_configs=[command_executor_config, text_editor_config]
    )


# ========================================
# MCPClientFactory初期化テスト
# ========================================


class TestMCPClientFactoryInit:
    """MCPClientFactory初期化のテスト"""

    def test_サーバー設定を正しく保持する(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """初期化時にmcp_server_configsが正しく設定されることを確認する"""
        assert "command-executor" in factory.mcp_server_configs
        assert "text-editor" in factory.mcp_server_configs
        assert len(factory.mcp_server_configs) == 2

    def test_レジストリが空の状態で初期化される(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """初期化時にmcp_tool_registryが空であることを確認する"""
        assert len(factory.mcp_tool_registry) == 0

    def test_空のリストで初期化できる(self) -> None:
        """空のserver_configsリストでも初期化できることを確認する"""
        factory = MCPClientFactory(server_configs=[])
        assert len(factory.mcp_server_configs) == 0


# ========================================
# create_mcp_toolテスト
# ========================================


class TestCreateMCPTool:
    """MCPClientFactory.create_mcp_tool()のテスト"""

    def test_command_executorツールを生成できる(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_mcp_tool()がcommand-executor用MCPStdioToolを生成することを確認する"""
        tool = factory.create_mcp_tool(server_name="command-executor", env_id="env-001")

        assert isinstance(tool, MCPStdioTool)
        assert tool.name == "command-executor"

    def test_text_editorツールを生成できる(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_mcp_tool()がtext-editor用MCPStdioToolを生成することを確認する"""
        tool = factory.create_mcp_tool(server_name="text-editor", env_id="env-002")

        assert isinstance(tool, MCPStdioTool)
        assert tool.name == "text-editor"

    def test_存在しないサーバー名でValueErrorが発生する(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """存在しないserver_nameを指定するとValueErrorが発生することを確認する"""
        with pytest.raises(ValueError, match="MCPサーバー設定が見つかりません"):
            factory.create_mcp_tool(server_name="non-existent-server", env_id="env-001")

    def test_同じenv_idのツールはキャッシュから返される(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """同じserver_nameとenv_idでcreate_mcp_tool()を2回呼ぶと同じオブジェクトが返されることを確認する"""
        tool1 = factory.create_mcp_tool(server_name="command-executor", env_id="env-001")
        tool2 = factory.create_mcp_tool(server_name="command-executor", env_id="env-001")

        assert tool1 is tool2

    def test_異なるenv_idでは別のツールが生成される(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """異なるenv_idで呼ぶと別のMCPStdioToolが生成されることを確認する"""
        tool1 = factory.create_mcp_tool(server_name="command-executor", env_id="env-001")
        tool2 = factory.create_mcp_tool(server_name="command-executor", env_id="env-002")

        assert tool1 is not tool2

    def test_キャッシュにレジストリが登録される(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_mcp_tool()呼び出し後にmcp_tool_registryにエントリが登録されることを確認する"""
        factory.create_mcp_tool(server_name="command-executor", env_id="env-001")

        assert "command-executor:env-001" in factory.mcp_tool_registry


# ========================================
# 便利メソッドテスト
# ========================================


class TestConvenienceMethods:
    """MCPClientFactoryの便利メソッドのテスト"""

    def test_create_text_editor_toolでtext_editorツールが生成される(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_text_editor_tool()がtext-editor用ツールを生成することを確認する"""
        tool = factory.create_text_editor_tool(env_id="env-001")

        assert isinstance(tool, MCPStdioTool)
        assert tool.name == "text-editor"

    def test_create_command_executor_toolでcommand_executorツールが生成される(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_command_executor_tool()がcommand-executor用ツールを生成することを確認する"""
        tool = factory.create_command_executor_tool(env_id="env-001")

        assert isinstance(tool, MCPStdioTool)
        assert tool.name == "command-executor"

    def test_create_tools_for_agentで複数ツールを一括生成できる(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_tools_for_agent()がエージェント定義のサーバーリストに対してツールを一括生成することを確認する"""
        tools = factory.create_tools_for_agent(
            mcp_server_names=["command-executor", "text-editor"],
            env_id="env-001",
        )

        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "command-executor" in tool_names
        assert "text-editor" in tool_names

    def test_create_tools_for_agentで空リストを渡すと空リストが返る(
        self,
        factory: MCPClientFactory,
    ) -> None:
        """create_tools_for_agent()に空リストを渡すと空のリストが返ることを確認する"""
        tools = factory.create_tools_for_agent(
            mcp_server_names=[],
            env_id="env-001",
        )

        assert tools == []
