"""
ExecutionEnvironmentMCPWrapperモジュール

Dockerコンテナ内のMCPサーバーの起動・通信・終了を管理するクラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 9.3（ExecutionEnvironmentMCPWrapper）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from config.models import MCPServerConfig

from .mcp_client import MCPClient, MCPConnectionError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ExecutionEnvironmentMCPWrapper:
    """
    Docker実行環境内でMCPサーバーの起動・通信・終了を管理するクラス。

    ExecutionEnvironmentManagerを通じてDockerコンテナを取得し、
    コンテナ内でMCPサーバープロセスをDocker exec API経由で起動する。
    起動済みの接続はキャッシュして再利用する。

    CLASS_IMPLEMENTATION_SPEC.md § 9.3 に準拠する。

    Attributes:
        env_manager: Docker環境管理クラスへの参照
        active_connections: "{env_id}:{server_name}" をキーとした起動済みMCPClientのキャッシュ
        server_configs: MCPサーバー設定リスト
    """

    def __init__(
        self,
        env_manager: Any,
        server_configs: list[MCPServerConfig],
    ) -> None:
        """
        ExecutionEnvironmentMCPWrapperを初期化する。

        Args:
            env_manager: ExecutionEnvironmentManagerインスタンス
                         （get_container(env_id)メソッドを持つ）
            server_configs: MCPサーバー設定リスト
        """
        self.env_manager = env_manager
        self.active_connections: dict[str, MCPClient] = {}
        self.server_configs = server_configs
        logger.debug(
            "ExecutionEnvironmentMCPWrapperを初期化しました: server_count=%d",
            len(server_configs),
        )

    def _get_server_config(self, server_name: str) -> MCPServerConfig | None:
        """
        サーバー名に一致するMCPServerConfigを返す。

        Args:
            server_name: 検索するサーバー名

        Returns:
            一致するMCPServerConfig、存在しない場合はNone
        """
        for config in self.server_configs:
            if config.name == server_name:
                return config
        return None

    def _build_cache_key(self, env_id: str, server_name: str) -> str:
        """
        キャッシュキー文字列を生成する。

        Args:
            env_id: 環境ID
            server_name: サーバー名

        Returns:
            "{env_id}:{server_name}" 形式のキャッシュキー
        """
        return f"{env_id}:{server_name}"

    def start_mcp_server(self, env_id: str, server_name: str) -> MCPClient:
        """
        指定した環境のDockerコンテナ内でMCPサーバーを起動する。

        既にキャッシュに接続が存在する場合はそれを返す。
        存在しない場合はコンテナ内でプロセスを起動してMCP初期化を行い、
        キャッシュに登録して返す。

        Args:
            env_id: 実行環境ID（Dockerコンテナの識別子）
            server_name: 起動するMCPサーバー名

        Returns:
            接続済みMCPClientインスタンス

        Raises:
            ValueError: 指定されたserver_nameの設定が存在しない場合
            MCPConnectionError: MCPサーバーの起動・接続に失敗した場合
        """
        cache_key = self._build_cache_key(env_id, server_name)

        # キャッシュに既存接続があれば返す
        if cache_key in self.active_connections:
            logger.debug(
                "既存MCPサーバー接続を再利用: env_id=%s, server=%s",
                env_id,
                server_name,
            )
            return self.active_connections[cache_key]

        # MCPサーバー設定を取得する
        server_config = self._get_server_config(server_name)
        if server_config is None:
            raise ValueError(
                f"MCPサーバー設定が見つかりません: server_name={server_name}"
            )

        # Dockerコンテナを取得する
        container = self.env_manager.get_container(env_id)
        logger.info(
            "Dockerコンテナ内でMCPサーバーを起動します: env_id=%s, server=%s",
            env_id,
            server_name,
        )

        # Docker exec APIでコンテナ内にMCPサーバープロセスを起動する
        # コンテナのstdin/stdoutをPipeとして接続する
        exec_result = container.exec_run(
            cmd=server_config.command,
            stdin=True,
            stdout=True,
            stderr=True,
            stream=True,
            socket=True,
            environment=server_config.env,
        )

        # コンテナプロセスのstdin/stdoutに接続するMCPClientを生成する
        mcp_client = MCPClient(server_config=server_config)

        # Dockerソケットをstdio代わりに使用するためプロセスオブジェクトをラップする
        mcp_client._process = exec_result  # type: ignore[assignment]

        # MCP接続初期化を行う
        try:
            mcp_client.connect()
        except MCPConnectionError:
            logger.error(
                "コンテナ内MCPサーバー起動失敗: env_id=%s, server=%s",
                env_id,
                server_name,
            )
            raise

        # キャッシュに登録する
        self.active_connections[cache_key] = mcp_client
        logger.info(
            "MCPサーバー起動完了: env_id=%s, server=%s",
            env_id,
            server_name,
        )
        return mcp_client

    def stop_mcp_server(self, env_id: str, server_name: str) -> None:
        """
        指定した環境のMCPサーバー接続を切断・停止する。

        キャッシュに接続が存在する場合は切断してキャッシュから削除する。
        存在しない場合は何もしない。

        Args:
            env_id: 実行環境ID
            server_name: 停止するMCPサーバー名
        """
        cache_key = self._build_cache_key(env_id, server_name)

        # キャッシュに接続がなければ処理終了
        if cache_key not in self.active_connections:
            logger.debug(
                "停止対象のMCPサーバー接続が存在しません: env_id=%s, server=%s",
                env_id,
                server_name,
            )
            return

        mcp_client = self.active_connections[cache_key]

        # 接続を切断する
        mcp_client.disconnect()

        # キャッシュから削除する
        del self.active_connections[cache_key]
        logger.info(
            "MCPサーバー停止完了: env_id=%s, server=%s",
            env_id,
            server_name,
        )

    def stop_all_servers(self, env_id: str) -> None:
        """
        指定した環境のすべてのMCPサーバー接続を停止する。

        env_idに紐づくすべてのキャッシュエントリを切断・削除する。

        Args:
            env_id: 実行環境ID
        """
        prefix = f"{env_id}:"
        keys_to_stop = [k for k in self.active_connections if k.startswith(prefix)]
        for key in keys_to_stop:
            server_name = key[len(prefix):]
            self.stop_mcp_server(env_id, server_name)
        logger.info(
            "環境のすべてのMCPサーバーを停止しました: env_id=%s, count=%d",
            env_id,
            len(keys_to_stop),
        )
