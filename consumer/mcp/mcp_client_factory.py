"""
MCPClientFactoryモジュール

エージェント定義のmcp_serversリストからMCPStdioTool相当の設定オブジェクトを生成する。

CLASS_IMPLEMENTATION_SPEC.md § 2.4（MCPClientFactory）に準拠する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from config.models import MCPServerConfig

logger = logging.getLogger(__name__)


@dataclass
class MCPStdioToolConfig:
    """
    MCPStdioTool生成に必要な設定情報を保持するデータクラス。

    Agent FrameworkのMCPStdioTool（agent_framework._mcp.MCPStdioTool）の
    コンストラクタに渡す情報を保持する。Agent Framework統合後は
    このクラスの代わりに直接MCPStdioToolを使用する。

    Attributes:
        server_name: MCPサーバー名
        command: サーバー起動コマンドリスト（最初の要素がコマンド本体）
        args: コマンド引数リスト（commandの2番目以降の要素）
        env: サーバー起動時の環境変数辞書
        env_id: 対象Dockerコンテナの環境ID
    """

    server_name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    env_id: str = ""

    def __repr__(self) -> str:
        """クラス情報を含む文字列表現を返す。"""
        return (
            f"MCPStdioToolConfig(server_name={self.server_name!r}, "
            f"command={self.command!r}, env_id={self.env_id!r})"
        )


class MCPClientFactory:
    """
    エージェントごとにMCPStdioTool設定オブジェクトを生成するファクトリクラス。

    MCPServerConfigのリストからサーバー設定を管理し、
    エージェントのmcp_serversリストに応じてMCPStdioToolConfigを生成する。
    生成済みのツールはmcp_tool_registryにキャッシュして再利用する。

    CLASS_IMPLEMENTATION_SPEC.md § 2.4 に準拠する。

    Attributes:
        mcp_server_configs: サーバー名をキーとするMCPServerConfig辞書
        mcp_tool_registry: サーバー名をキーとする生成済みMCPStdioToolConfig辞書
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
        self.mcp_tool_registry: dict[str, MCPStdioToolConfig] = {}
        logger.debug(
            "MCPClientFactoryを初期化しました: server_names=%s",
            list(self.mcp_server_configs.keys()),
        )

    def create_mcp_tool(
        self,
        server_name: str,
        env_id: str,
    ) -> MCPStdioToolConfig:
        """
        指定したサーバー名とenv_idからMCPStdioToolConfigを生成する。

        既にmcp_tool_registryに登録済みの場合はキャッシュを返す。
        MCPServerConfigのcommandにenv_idを埋め込み、
        接続対象のDockerコンテナを特定できるようにする。

        Args:
            server_name: MCPサーバー名（config.yamlのmcp_servers[].name）
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            MCPStdioToolConfigインスタンス

        Raises:
            ValueError: 指定されたserver_nameの設定が存在しない場合
        """
        # env_idを含むキーでレジストリを検索する
        registry_key = f"{server_name}:{env_id}"

        # 登録済みの場合はキャッシュを返す
        if registry_key in self.mcp_tool_registry:
            logger.debug(
                "キャッシュからMCPStdioToolConfigを返します: server=%s, env_id=%s",
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

        # MCPStdioToolConfigを生成する
        mcp_tool = MCPStdioToolConfig(
            server_name=server_name,
            command=base_command,
            args=base_args,
            env=merged_env,
            env_id=env_id,
        )

        # レジストリに登録する
        self.mcp_tool_registry[registry_key] = mcp_tool
        logger.info(
            "MCPStdioToolConfigを生成しました: server=%s, env_id=%s",
            server_name,
            env_id,
        )
        return mcp_tool

    def create_text_editor_tool(self, env_id: str) -> MCPStdioToolConfig:
        """
        text-editorサーバーのMCPStdioToolConfigを生成する。

        Args:
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            text-editor用MCPStdioToolConfigインスタンス
        """
        return self.create_mcp_tool("text-editor", env_id)

    def create_command_executor_tool(self, env_id: str) -> MCPStdioToolConfig:
        """
        command-executorサーバーのMCPStdioToolConfigを生成する。

        Args:
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            command-executor用MCPStdioToolConfigインスタンス
        """
        return self.create_mcp_tool("command-executor", env_id)

    def create_tools_for_agent(
        self,
        mcp_server_names: list[str],
        env_id: str,
    ) -> list[MCPStdioToolConfig]:
        """
        エージェント定義のmcp_serversリストに基づいてツール設定リストを生成する。

        Args:
            mcp_server_names: エージェント定義に記載されたMCPサーバー名リスト
            env_id: 対象Dockerコンテナの環境ID

        Returns:
            MCPStdioToolConfigのリスト
        """
        tools: list[MCPStdioToolConfig] = []
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
