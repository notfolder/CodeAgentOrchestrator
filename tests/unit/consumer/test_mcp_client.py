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
        mcp_client._process = mock_process

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
        mcp_client._process = mock_process

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
        mcp_client._process = mock_process

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
        mcp_client._process = mock_process

        with pytest.raises(MCPToolCallError, match="ツール呼び出しでエラー"):
            mcp_client.call_tool(tool_name="execute_command", arguments={})


class TestMCPClientDisconnect:
    """MCPClient.disconnect()のテスト"""

    def test_接続済み状態でdisconnectが正常に動作する(
        self, mcp_client: MCPClient
    ) -> None:
        """disconnect()がプロセスを終了することを確認する"""
        mock_process = MagicMock()
        mcp_client._process = mock_process

        mcp_client.disconnect()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()
        assert mcp_client._process is None

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
    def env_aware_client(
        self,
        base_client: MagicMock,
    ) -> EnvironmentAwareMCPClient:
        """テスト用EnvironmentAwareMCPClientを返す"""
        return EnvironmentAwareMCPClient(
            base_client=base_client,
            current_node_id="node-01",
        )

    def test_call_toolでenvironment_idが引数に追加される(
        self,
        env_aware_client: EnvironmentAwareMCPClient,
        base_client: MagicMock,
    ) -> None:
        """call_tool()がenvironment_idを引数に追加してbase_clientを呼び出すことを確認する"""
        base_client.call_tool.return_value = {"result": "success"}

        result = env_aware_client.call_tool(
            tool_name="execute_command",
            arguments={"command": "ls"},
            env_id="env-container-001",
        )

        # base_clientのcall_toolが呼び出されることを確認する
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
            env_id="env-001",
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
