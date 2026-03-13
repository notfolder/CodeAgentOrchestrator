"""
MCPクライアントの単体テスト

stdioプロセスをモックし、MCPClient・EnvironmentAwareMCPClientの
接続・ツール呼び出し・切断のライフサイクルを検証する。
"""

from __future__ import annotations

import json
import subprocess
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from config.models import MCPServerConfig
from mcp.mcp_client import (
    EnvironmentAwareMCPClient,
    MCPClient,
    MCPConnectionError,
    MCPTool,
    MCPToolCallError,
)


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def server_config() -> MCPServerConfig:
    """テスト用MCPServerConfigを返す"""
    return MCPServerConfig(
        name="test-server",
        command=["python", "test_server.py"],
        env={"TEST_ENV": "test_value"},
    )


@pytest.fixture
def mcp_client(server_config: MCPServerConfig) -> MCPClient:
    """テスト用MCPClientを返す（未接続状態）"""
    return MCPClient(server_config=server_config)


def _make_json_line(data: dict[str, Any]) -> bytes:
    """辞書をJSON行（改行付き）に変換する"""
    return (json.dumps(data) + "\n").encode("utf-8")


def _make_mock_process(
    responses: list[dict[str, Any]],
) -> MagicMock:
    """
    標準入出力をモックしたsubprocess.Popen相当のオブジェクトを生成する。

    Args:
        responses: stdoutから順番に返すレスポンス辞書のリスト

    Returns:
        モックプロセスオブジェクト
    """
    mock_process = MagicMock()
    mock_process.stdin = MagicMock()

    # 複数レスポンスをreadlineで順番に返す
    response_lines = [_make_json_line(r) for r in responses]
    mock_process.stdout.readline = MagicMock(side_effect=response_lines)

    return mock_process


# ========================================
# MCPClientテスト
# ========================================


class TestMCPClientConnect:
    """MCPClient.connect()のテスト"""

    def test_正常に接続できる(self, mcp_client: MCPClient) -> None:
        """connect()がプロセスを起動してMCP初期化を行うことを確認する"""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test-server", "version": "1.0.0"},
            },
        }
        mock_process = _make_mock_process([init_response])

        with patch("subprocess.Popen", return_value=mock_process):
            mcp_client.connect()

        assert mcp_client._process is mock_process
        assert mcp_client._stdin is not None
        assert mcp_client._stdout is not None
        # 初期化メッセージが送信されたことを確認する
        assert mock_process.stdin.write.called

    def test_プロセス起動失敗時にMCPConnectionErrorが発生する(
        self, mcp_client: MCPClient
    ) -> None:
        """プロセス起動失敗時にMCPConnectionErrorが発生することを確認する"""
        with patch("subprocess.Popen", side_effect=OSError("command not found")):
            with pytest.raises(MCPConnectionError, match="起動に失敗"):
                mcp_client.connect()

    def test_初期化レスポンスにエラーがある場合にMCPConnectionErrorが発生する(
        self, mcp_client: MCPClient
    ) -> None:
        """初期化レスポンスにエラーがある場合にMCPConnectionErrorが発生することを確認する"""
        error_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
        mock_process = _make_mock_process([error_response])

        with patch("subprocess.Popen", return_value=mock_process):
            with pytest.raises(MCPConnectionError, match="エラーが返されました"):
                mcp_client.connect()


class TestMCPClientListTools:
    """MCPClient.list_tools()のテスト"""

    def test_ツール一覧を正しく取得できる(self, mcp_client: MCPClient) -> None:
        """list_tools()がMCPToolのリストを返すことを確認する"""
        list_tools_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "execute_command",
                        "description": "コマンドを実行する",
                        "inputSchema": {"type": "object"},
                    },
                    {
                        "name": "view_file",
                        "description": "ファイルを表示する",
                        "inputSchema": {"type": "object"},
                    },
                ]
            },
        }
        mock_process = _make_mock_process([list_tools_response])
        # _stdin/_stdoutを直接設定して接続済み状態にする
        mcp_client._stdin = mock_process.stdin
        mcp_client._stdout = mock_process.stdout

        result = mcp_client.list_tools()

        assert len(result) == 2
        assert isinstance(result[0], MCPTool)
        assert result[0].name == "execute_command"
        assert result[1].name == "view_file"

    def test_ツール一覧取得でエラーが返された場合にMCPToolCallErrorが発生する(
        self, mcp_client: MCPClient
    ) -> None:
        """list_tools()でエラーレスポンスを受信した場合にMCPToolCallErrorが発生することを確認する"""
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32601, "message": "Method not found"},
        }
        mock_process = _make_mock_process([error_response])
        mcp_client._stdin = mock_process.stdin
        mcp_client._stdout = mock_process.stdout

        with pytest.raises(MCPToolCallError, match="ツール一覧取得でエラー"):
            mcp_client.list_tools()

    def test_未接続状態でlist_toolsを呼ぶとMCPConnectionErrorが発生する(
        self, mcp_client: MCPClient
    ) -> None:
        """未接続状態でlist_tools()を呼ぶとMCPConnectionErrorが発生することを確認する"""
        with pytest.raises(MCPConnectionError, match="接続されていません"):
            mcp_client.list_tools()


class TestMCPClientCallTool:
    """MCPClient.call_tool()のテスト"""

    def test_ツールを正しく呼び出せる(self, mcp_client: MCPClient) -> None:
        """call_tool()がツール呼び出し結果を返すことを確認する"""
        call_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "コマンド実行結果"}],
                "isError": False,
            },
        }
        mock_process = _make_mock_process([call_response])
        # _stdin/_stdoutを直接設定して接続済み状態にする
        mcp_client._stdin = mock_process.stdin
        mcp_client._stdout = mock_process.stdout

        result = mcp_client.call_tool(
            tool_name="execute_command",
            arguments={"command": "ls -la"},
        )

        assert "content" in result
        # 送信メッセージにツール名と引数が含まれることを確認する
        sent_data = json.loads(
            mock_process.stdin.write.call_args[0][0].decode("utf-8").strip()
        )
        assert sent_data["method"] == "tools/call"
        assert sent_data["params"]["name"] == "execute_command"
        assert sent_data["params"]["arguments"]["command"] == "ls -la"

    def test_ツール呼び出しでエラーが返された場合にMCPToolCallErrorが発生する(
        self, mcp_client: MCPClient
    ) -> None:
        """call_tool()でエラーレスポンスを受信した場合にMCPToolCallErrorが発生することを確認する"""
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32602, "message": "Invalid params"},
        }
        mock_process = _make_mock_process([error_response])
        mcp_client._stdin = mock_process.stdin
        mcp_client._stdout = mock_process.stdout

        with pytest.raises(MCPToolCallError, match="ツール呼び出しでエラー"):
            mcp_client.call_tool(tool_name="execute_command", arguments={})


class TestMCPClientDisconnect:
    """MCPClient.disconnect()のテスト"""

    def test_接続済み状態でdisconnectが正常に動作する(
        self, mcp_client: MCPClient
    ) -> None:
        """disconnect()がプロセスを終了し、ストリームをクリアすることを確認する"""
        mock_process = MagicMock()
        mcp_client._process = mock_process
        mcp_client._stdin = MagicMock()
        mcp_client._stdout = MagicMock()

        mcp_client.disconnect()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()
        assert mcp_client._process is None
        assert mcp_client._stdin is None
        assert mcp_client._stdout is None

    def test_未接続状態でdisconnectを呼んでも例外が発生しない(
        self, mcp_client: MCPClient
    ) -> None:
        """未接続状態でdisconnect()を呼んでも例外が発生しないことを確認する"""
        mcp_client.disconnect()  # 例外が発生しないことを確認する


# ========================================
# EnvironmentAwareMCPClientテスト
# ========================================


class TestEnvironmentAwareMCPClient:
    """EnvironmentAwareMCPClientのテスト"""

    @pytest.fixture
    def base_client(self, server_config: MCPServerConfig) -> MagicMock:
        """モックMCPClientを返す"""
        mock = MagicMock(spec=MCPClient)
        mock.server_config = server_config
        return mock

    @pytest.fixture
    def mock_env_manager(self) -> MagicMock:
        """モックExecutionEnvironmentManagerを返す"""
        env_manager = MagicMock()
        env_manager.get_environment.return_value = "env-container-001"
        return env_manager

    @pytest.fixture
    def env_aware_client(
        self,
        base_client: MagicMock,
        mock_env_manager: MagicMock,
    ) -> EnvironmentAwareMCPClient:
        """テスト用EnvironmentAwareMCPClientを返す"""
        return EnvironmentAwareMCPClient(
            base_client=base_client,
            env_manager=mock_env_manager,
            current_node_id="node-01",
        )

    def test_call_toolでenv_managerからenvironment_idが解決される(
        self,
        env_aware_client: EnvironmentAwareMCPClient,
        base_client: MagicMock,
        mock_env_manager: MagicMock,
    ) -> None:
        """call_tool()がenv_manager.get_environment()でenv_idを取得して引数に追加することを確認する"""
        base_client.call_tool.return_value = {"result": "success"}

        result = env_aware_client.call_tool(
            tool_name="execute_command",
            arguments={"command": "ls"},
        )

        # env_managerのget_environmentがcurrent_node_idで呼び出されることを確認する
        mock_env_manager.get_environment.assert_called_once_with("node-01")

        # base_clientのcall_toolがenvironment_idを含む引数で呼び出されることを確認する
        base_client.call_tool.assert_called_once_with(
            "execute_command",
            {"command": "ls", "environment_id": "env-container-001"},
        )
        assert result == {"result": "success"}

    def test_call_toolで元の引数辞書が変更されない(
        self,
        env_aware_client: EnvironmentAwareMCPClient,
        base_client: MagicMock,
    ) -> None:
        """call_tool()が呼び出し元の引数辞書を変更しないことを確認する"""
        base_client.call_tool.return_value = {}
        original_arguments = {"command": "ls"}

        env_aware_client.call_tool(
            tool_name="execute_command",
            arguments=original_arguments,
        )

        # 元の辞書に変更がないことを確認する
        assert original_arguments == {"command": "ls"}
        assert "environment_id" not in original_arguments

    def test_node_idが正しく保持される(
        self,
        env_aware_client: EnvironmentAwareMCPClient,
    ) -> None:
        """current_node_idが正しく保持されることを確認する"""
        assert env_aware_client.current_node_id == "node-01"

    def test_env_managerが正しく保持される(
        self,
        env_aware_client: EnvironmentAwareMCPClient,
        mock_env_manager: MagicMock,
    ) -> None:
        """env_managerが正しく保持されることを確認する"""
        assert env_aware_client.env_manager is mock_env_manager


class TestMCPClientConnectWithStreams:
    """MCPClient.connect_with_streams()のテスト"""

    def test_外部ストリームで接続できる(self, mcp_client: MCPClient) -> None:
        """connect_with_streams()が外部ストリームを使用してMCP初期化を行うことを確認する"""
        init_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test-server", "version": "1.0.0"},
            },
        }
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        response_line = (json.dumps(init_response) + "\n").encode("utf-8")
        mock_stdout.readline.return_value = response_line

        mcp_client.connect_with_streams(stdin=mock_stdin, stdout=mock_stdout)

        # ストリームが設定されることを確認する
        assert mcp_client._stdin is mock_stdin
        assert mcp_client._stdout is mock_stdout
        # subprocess.Popenは起動されないことを確認する
        assert mcp_client._process is None
        # 初期化メッセージが送信されたことを確認する
        assert mock_stdin.write.called


# ========================================
# ExecutionEnvironmentMCPWrapperテスト
# ========================================


class TestExecutionEnvironmentMCPWrapper:
    """ExecutionEnvironmentMCPWrapperのテスト"""

    @pytest.fixture
    def mock_env_manager(self) -> MagicMock:
        """モックExecutionEnvironmentManagerを返す"""
        env_manager = MagicMock()
        mock_container = MagicMock()
        # exec_runがソケットを返すようにモックする
        mock_socket = MagicMock()
        mock_socket.makefile.side_effect = lambda mode: MagicMock()
        exec_result = MagicMock()
        exec_result.output = mock_socket
        mock_container.exec_run.return_value = exec_result
        env_manager.get_container.return_value = mock_container
        return env_manager

    @pytest.fixture
    def server_configs(self, server_config: MCPServerConfig) -> list[MCPServerConfig]:
        """テスト用サーバー設定リストを返す"""
        return [server_config]

    @pytest.fixture
    def wrapper(
        self,
        mock_env_manager: MagicMock,
        server_configs: list[MCPServerConfig],
    ) -> "ExecutionEnvironmentMCPWrapper":
        """テスト用ExecutionEnvironmentMCPWrapperを返す"""
        from mcp.execution_environment_mcp_wrapper import ExecutionEnvironmentMCPWrapper
        return ExecutionEnvironmentMCPWrapper(
            env_manager=mock_env_manager,
            server_configs=server_configs,
        )

    def test_初期化時にactive_connectionsが空である(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
    ) -> None:
        """初期化時にactive_connectionsが空であることを確認する"""
        assert wrapper.active_connections == {}

    def test_サーバー設定が正しく保持される(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
        server_configs: list[MCPServerConfig],
    ) -> None:
        """server_configsが正しく保持されることを確認する"""
        assert wrapper.server_configs == server_configs

    def test_存在しないserver_nameでstart_mcp_serverを呼ぶとValueErrorが発生する(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
    ) -> None:
        """存在しないserver_nameを指定するとValueErrorが発生することを確認する"""
        from mcp.execution_environment_mcp_wrapper import ExecutionEnvironmentMCPWrapper
        with pytest.raises(ValueError, match="MCPサーバー設定が見つかりません"):
            wrapper.start_mcp_server(env_id="env-001", server_name="non-existent")

    def test_stop_mcp_serverで存在しない接続を停止しても例外が発生しない(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
    ) -> None:
        """存在しない接続をstop_mcp_server()で停止しても例外が発生しないことを確認する"""
        # 例外が発生しないことを確認する
        wrapper.stop_mcp_server(env_id="env-001", server_name="test-server")

    def test_stop_mcp_serverで接続が切断されキャッシュが削除される(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
    ) -> None:
        """stop_mcp_server()が接続を切断してキャッシュから削除することを確認する"""
        # モック接続をキャッシュに追加する
        mock_client = MagicMock()
        cache_key = "env-001:test-server"
        wrapper.active_connections[cache_key] = mock_client

        wrapper.stop_mcp_server(env_id="env-001", server_name="test-server")

        # disconnect()が呼び出されることを確認する
        mock_client.disconnect.assert_called_once()
        # キャッシュから削除されることを確認する
        assert cache_key not in wrapper.active_connections

    def test_キャッシュが存在する場合はstart_mcp_serverがキャッシュを返す(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
    ) -> None:
        """キャッシュ済みの接続がある場合は既存のMCPClientを返すことを確認する"""
        mock_client = MagicMock()
        cache_key = "env-001:test-server"
        wrapper.active_connections[cache_key] = mock_client

        result = wrapper.start_mcp_server(env_id="env-001", server_name="test-server")

        assert result is mock_client

    def test_stop_all_serversで環境の全接続が停止される(
        self,
        wrapper: "ExecutionEnvironmentMCPWrapper",
    ) -> None:
        """stop_all_servers()が対象env_idの全接続を停止することを確認する"""
        # 複数のモック接続をキャッシュに追加する
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        wrapper.active_connections["env-001:server-a"] = mock_client1
        wrapper.active_connections["env-001:server-b"] = mock_client2
        # 別env_idの接続（停止対象外）
        mock_client3 = MagicMock()
        wrapper.active_connections["env-002:server-a"] = mock_client3

        wrapper.stop_all_servers(env_id="env-001")

        # env-001の接続が全て切断されることを確認する
        mock_client1.disconnect.assert_called_once()
        mock_client2.disconnect.assert_called_once()
        # env-002の接続は切断されないことを確認する
        mock_client3.disconnect.assert_not_called()
        # キャッシュからenv-001のエントリが削除されることを確認する
        assert "env-001:server-a" not in wrapper.active_connections
        assert "env-001:server-b" not in wrapper.active_connections
        assert "env-002:server-a" in wrapper.active_connections
