"""
MCPClientFactoryモジュール

エージェント定義のmcp_serversリストからAgent FrameworkのMCPStdioToolインスタンスを
生成するファクトリクラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 2.4（MCPClientFactory）に準拠する。
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import MCPStdioTool

from config.models import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPClientFactory:
    """
    エージェントごとにAgent FrameworkのMCPStdioToolインスタンスを生成するファクトリクラス。

    MCPServerConfigのリストからサーバー設定を管理し、
    エージェントのmcp_serversリストに応じてMCPStdioToolを生成する。
    生成済みのツールはmcp_tool_registryにキャッシュして再利用する。

    Agent FrameworkはMCPStdioToolをAgentのコンストラクタに直接渡す設計のため、
    Kernelへの登録は不要。

    CLASS_IMPLEMENTATION_SPEC.md § 2.4 に準拠する。

    Attributes:
        mcp_server_configs: サーバー名をキーとするMCPServerConfig辞書
        mcp_tool_registry: サーバー名をキーとする生成済みMCPStdioTool辞書。
            キーは "{server_name}:{env_id}" 形式。
    """

    def __init__(self, server_configs: list[MCPServerConfig]) -> None:
        """
        MCPClientFactoryを初期化する。

        Args:
            server_configs: MCPサーバー設定リスト（config.yamlのmcp_servers設定）
        """
        self.mcp_server_configs: dict[str, MCPServerConfig] = {
            cfg.name: cfg for cfg in server_configs
        }
        self.mcp_tool_registry: dict[str, MCPStdioTool] = {}
        logger.debug(
            "MCPClientFactoryを初期化しました: server_names=%s",
            list(self.mcp_server_configs.keys()),
        )

    def create_mcp_tool(
        self,
        server_name: str,
        env_id: str,
    ) -> MCPStdioTool:
        """
        指定したサーバー名とenv_idからAgent FrameworkのMCPStdioToolを生成する。

        既にmcp_tool_registryに登録済みの場合はキャッシュを返す。
        MCPServerConfigのcommandにenv_idを埋め込み、
        接続対象のDockerコンテナを特定できるようにする。
        Agent FrameworkがAgent.run()呼び出し時にMCPStdioTool経由で
        MCPサーバーに自動接続する。

        Args:
            server_name: MCPサーバー名（config.yamlのmcp_servers[].name）
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            MCPStdioToolインスタンス

        Raises:
            ValueError: 指定されたserver_nameの設定が存在しない場合
        """
        # env_idを含むキーでレジストリを検索する
        registry_key = f"{server_name}:{env_id}"

        # 登録済みの場合はキャッシュを返す
        if registry_key in self.mcp_tool_registry:
            logger.debug(
                "キャッシュからMCPStdioToolを返します: server=%s, env_id=%s",
                server_name,
                env_id,
            )
            return self.mcp_tool_registry[registry_key]

        # サーバー設定を取得する
        server_config = self.mcp_server_configs.get(server_name)
        if server_config is None:
            raise ValueError(
                f"MCPサーバー設定が見つかりません: server_name={server_name}. "
                f"利用可能なサーバー: {list(self.mcp_server_configs.keys())}"
            )

        # コマンドリストからcommand（実行ファイル）とargs（引数）を分離する
        if not server_config.command:
            raise ValueError(
                f"MCPサーバーのコマンドが設定されていません: server_name={server_name}"
            )

        base_command = server_config.command[0]
        base_args = list(server_config.command[1:])

        # env_idを環境変数として追加してDockerコンテナを特定できるようにする
        merged_env = dict(server_config.env)
        merged_env["MCP_ENV_ID"] = env_id

        # Agent FrameworkのMCPStdioToolインスタンスを生成する
        mcp_tool = MCPStdioTool(
            name=server_name,
            command=base_command,
            args=base_args,
            env=merged_env,
        )

        # レジストリに登録する
        self.mcp_tool_registry[registry_key] = mcp_tool
        logger.info(
            "MCPStdioToolを生成しました: server=%s, env_id=%s",
            server_name,
            env_id,
        )
        return mcp_tool

    def create_text_editor_tool(self, env_id: str) -> MCPStdioTool:
        """
        text-editorサーバーのMCPStdioToolを生成する。

        Args:
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            text-editor用MCPStdioToolインスタンス
        """
        return self.create_mcp_tool("text-editor", env_id)

    def create_command_executor_tool(self, env_id: str) -> MCPStdioTool:
        """
        command-executorサーバーのMCPStdioToolを生成する。

        Args:
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            command-executor用MCPStdioToolインスタンス
        """
        return self.create_mcp_tool("command-executor", env_id)

    def create_tools_for_agent(
        self,
        mcp_server_names: list[str],
        env_id: str,
    ) -> list[MCPStdioTool]:
        """
        エージェント定義のmcp_serversリストに基づいてツールリストを生成する。

        Args:
            mcp_server_names: エージェント定義に記載されたMCPサーバー名リスト
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            MCPStdioToolのリスト
        """
        tools: list[MCPStdioTool] = []
        for server_name in mcp_server_names:
            tool = self.create_mcp_tool(server_name, env_id)
            tools.append(tool)
        logger.debug(
            "エージェント用ツール生成完了: server_names=%s, env_id=%s, count=%d",
            mcp_server_names,
            env_id,
            len(tools),
        )
        return tools
