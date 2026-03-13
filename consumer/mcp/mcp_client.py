"""
MCPクライアント実装モジュール

stdio経由でMCPサーバーと通信するMCPClientクラスと、
ノードIDから環境IDを解決するEnvironmentAwareMCPClientクラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 9（MCPClient関連）に準拠する。
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import IO, Any

from config.models import MCPServerConfig

logger = logging.getLogger(__name__)

# MCP JSON-RPCリクエストのバージョン
_JSONRPC_VERSION = "2.0"
# 初期化リクエストID
_INIT_REQUEST_ID = 1


class MCPConnectionError(Exception):
    """MCPサーバーへの接続失敗時に発生する例外"""


class MCPToolCallError(Exception):
    """MCPツール呼び出し失敗時に発生する例外"""


class MCPTool:
    """
    MCPサーバーが提供するツールの情報を保持するデータクラス。

    Attributes:
        name: ツール名
        description: ツールの説明
        input_schema: ツールの入力スキーマ（JSONスキーマ形式）
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        """
        MCPToolを初期化する。

        Args:
            name: ツール名
            description: ツールの説明
            input_schema: 入力スキーマ
        """
        self.name = name
        self.description = description
        self.input_schema: dict[str, Any] = input_schema or {}

    def __repr__(self) -> str:
        """ツール名を含む文字列表現を返す。"""
        return f"MCPTool(name={self.name!r})"


class MCPClient:
    """
    stdio経由でMCPサーバーと通信するクライアントクラス。

    subprocess.Popenでサーバープロセスを起動し、
    stdin/stdoutを通じてJSON-RPC形式でMCPプロトコルメッセージを送受信する。
    外部から提供されたIOストリームを使用することもできる（Docker exec対応）。

    CLASS_IMPLEMENTATION_SPEC.md § 9.1 に準拠する。

    Attributes:
        server_config: サーバー設定（コマンド・環境変数等）
    """

    def __init__(self, server_config: MCPServerConfig) -> None:
        """
        MCPClientを初期化する。

        Args:
            server_config: MCPサーバー設定（コマンド・環境変数等）
        """
        self.server_config = server_config
        self._process: subprocess.Popen[bytes] | None = None
        # stdin/stdoutストリームを別途保持し、subprocessとDocker execの両方に対応する
        self._stdin: IO[bytes] | None = None
        self._stdout: IO[bytes] | None = None
        self._request_id_counter: int = _INIT_REQUEST_ID + 1

    def _next_request_id(self) -> int:
        """次のリクエストIDを返す。"""
        request_id = self._request_id_counter
        self._request_id_counter += 1
        return request_id

    def _send_message(self, message: dict[str, Any]) -> None:
        """
        MCPサーバーのstdinにJSON-RPCメッセージを送信する。

        Args:
            message: 送信するJSON-RPCメッセージ辞書

        Raises:
            MCPConnectionError: ストリームが設定されていない場合
        """
        if self._stdin is None:
            raise MCPConnectionError(
                "MCPサーバーに接続されていません。connect()を先に呼び出してください。"
            )
        line = json.dumps(message) + "\n"
        self._stdin.write(line.encode("utf-8"))
        self._stdin.flush()

    def _receive_message(self) -> dict[str, Any]:
        """
        MCPサーバーのstdoutからJSON-RPCメッセージを受信する。

        Returns:
            受信したJSON-RPCレスポンス辞書

        Raises:
            MCPConnectionError: ストリームが設定されていない場合、またはEOFの場合
        """
        if self._stdout is None:
            raise MCPConnectionError(
                "MCPサーバーに接続されていません。connect()を先に呼び出してください。"
            )
        line = self._stdout.readline()
        if not line:
            raise MCPConnectionError(
                "MCPサーバーからのレスポンスが読み取れません。プロセスが終了した可能性があります。"
            )
        response: dict[str, Any] = json.loads(line.decode("utf-8").strip())
        return response

    def _initialize_handshake(self) -> None:
        """
        MCPプロトコルの初期化ハンドシェイクを実行する。

        接続後に初期化メッセージを送信し、initialized通知を送る。

        Raises:
            MCPConnectionError: 初期化失敗時
        """
        init_message: dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": _INIT_REQUEST_ID,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "automata-codex",
                    "version": "0.1.0",
                },
            },
        }
        try:
            self._send_message(init_message)
            response = self._receive_message()
            if "error" in response:
                raise MCPConnectionError(
                    f"MCPサーバーの初期化でエラーが返されました: {response['error']}"
                )
            logger.debug("MCPサーバー初期化完了: server=%s", self.server_config.name)

            # initialized通知送信（MCPプロトコル要件）
            initialized_notification: dict[str, Any] = {
                "jsonrpc": _JSONRPC_VERSION,
                "method": "notifications/initialized",
                "params": {},
            }
            self._send_message(initialized_notification)
        except (json.JSONDecodeError, OSError) as exc:
            raise MCPConnectionError(
                f"MCPサーバーの初期化ハンドシェイクに失敗しました: {exc}"
            ) from exc

    def connect(self) -> None:
        """
        MCPサーバープロセスを起動し、MCP初期化ハンドシェイクを行う。

        subprocess.Popenでserver_config.commandを実行し、
        stdin/stdoutをPIPEとして接続する。
        その後、MCPプロトコルの初期化メッセージを送信してレスポンスを受信する。

        Raises:
            MCPConnectionError: プロセス起動失敗または初期化失敗時
        """
        try:
            # サーバープロセス起動
            self._process = subprocess.Popen(
                self.server_config.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.server_config.env or None,
            )
            logger.info(
                "MCPサーバープロセスを起動しました: command=%s",
                self.server_config.command,
            )
        except (OSError, ValueError) as exc:
            raise MCPConnectionError(
                f"MCPサーバープロセスの起動に失敗しました: {exc}"
            ) from exc

        # subprocessのstdin/stdoutをストリームとして設定する
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout

        # MCP初期化ハンドシェイクを実行する
        self._initialize_handshake()

    def connect_with_streams(
        self,
        stdin: IO[bytes],
        stdout: IO[bytes],
    ) -> None:
        """
        外部から提供されたIOストリームを使用してMCPサーバーに接続する。

        Docker exec API等で既にプロセスが起動されている場合に使用する。
        subprocessの起動は行わず、提供されたストリームでMCP初期化のみ行う。

        Args:
            stdin: MCPサーバーへの標準入力ストリーム
            stdout: MCPサーバーからの標準出力ストリーム

        Raises:
            MCPConnectionError: 初期化失敗時
        """
        self._stdin = stdin
        self._stdout = stdout
        logger.info(
            "外部ストリームでMCPサーバーに接続します: server=%s",
            self.server_config.name,
        )
        # MCP初期化ハンドシェイクを実行する
        self._initialize_handshake()

    def list_tools(self) -> list[MCPTool]:
        """
        MCPサーバーが提供するツール一覧を取得する。

        JSON-RPCの tools/list リクエストを送信し、
        レスポンスからMCPToolオブジェクトのリストを生成して返す。

        Returns:
            MCPToolのリスト

        Raises:
            MCPConnectionError: 接続されていない場合
            MCPToolCallError: ツール一覧取得でエラーが返された場合
        """
        request_id = self._next_request_id()
        request: dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": request_id,
            "method": "tools/list",
            "params": {},
        }
        self._send_message(request)
        response = self._receive_message()

        if "error" in response:
            raise MCPToolCallError(
                f"ツール一覧取得でエラーが返されました: {response['error']}"
            )

        tools_data = response.get("result", {}).get("tools", [])
        tools = [
            MCPTool(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema"),
            )
            for tool in tools_data
        ]
        logger.debug(
            "ツール一覧取得: server=%s, count=%d",
            self.server_config.name,
            len(tools),
        )
        return tools

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        MCPサーバーのツールを呼び出す。

        JSON-RPCの tools/call リクエストを送信し、
        レスポンスのresultフィールドを返す。

        Args:
            tool_name: 呼び出すツール名
            arguments: ツールへの引数辞書

        Returns:
            ツール呼び出し結果の辞書

        Raises:
            MCPConnectionError: 接続されていない場合
            MCPToolCallError: ツール呼び出しでエラーが返された場合
        """
        request_id = self._next_request_id()
        request: dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        self._send_message(request)
        response = self._receive_message()

        if "error" in response:
            raise MCPToolCallError(
                f"ツール呼び出しでエラーが返されました: tool={tool_name}, error={response['error']}"
            )

        result: dict[str, Any] = response.get("result", {})
        logger.debug("ツール呼び出し完了: tool=%s", tool_name)
        return result

    def disconnect(self) -> None:
        """
        MCPサーバープロセスを終了する。

        process.terminate()でプロセスに終了シグナルを送り、
        process.wait()で終了を待機する。
        外部ストリーム（Docker exec等）で接続した場合は
        プロセスの終了は行わず、ストリームをクリアする。
        プロセスが起動していない場合は何もしない。
        """
        # ストリームをクリアする
        self._stdin = None
        self._stdout = None

        if self._process is None:
            return

        try:
            self._process.terminate()
            self._process.wait(timeout=5)
            logger.info(
                "MCPサーバープロセスを終了しました: server=%s",
                self.server_config.name,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning(
                "MCPサーバープロセス終了時にエラーが発生しました: %s",
                exc,
            )
        finally:
            self._process = None


class EnvironmentAwareMCPClient:
    """
    ノードIDから環境IDを解決し、ツール引数に自動付与するMCPクライアントラッパー。

    ベースとなるMCPClientに対して、各ツール呼び出し時に
    environment_id引数を自動追加する機能を提供する。

    CLASS_IMPLEMENTATION_SPEC.md § 9.2 に準拠する。

    Attributes:
        base_client: ベースMCPクライアント
        current_node_id: 現在実行中のノードID
    """

    def __init__(
        self,
        base_client: MCPClient,
        current_node_id: str,
    ) -> None:
        """
        EnvironmentAwareMCPClientを初期化する。

        Args:
            base_client: ベースMCPクライアント
            current_node_id: 現在実行中のノードID
        """
        self.base_client = base_client
        self.current_node_id = current_node_id

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        env_id: str,
    ) -> dict[str, Any]:
        """
        ツールを呼び出す前にenvironment_idを引数に追加する。

        環境ID（env_id）を引数辞書に追加してからベースクライアントのcall_toolを呼び出す。

        Args:
            tool_name: 呼び出すツール名
            arguments: ツールへの引数辞書（environment_idが自動追加される）
            env_id: 実行環境ID（Dockerコンテナの識別子）

        Returns:
            ツール呼び出し結果の辞書
        """
        # 元の引数辞書を変更しないようにコピーする
        merged_arguments = dict(arguments)
        merged_arguments["environment_id"] = env_id
        logger.debug(
            "EnvironmentAwareMCPClient: tool=%s, node_id=%s, env_id=%s",
            tool_name,
            self.current_node_id,
            env_id,
        )
        return self.base_client.call_tool(tool_name, merged_arguments)
