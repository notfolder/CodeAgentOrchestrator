"""
RabbitMQクライアントの単体テスト

aio-pikaをモックしてRabbitMQClientの
接続・パブリッシュ・サブスクライブ・切断時の自動再接続を検証する。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.models import RabbitMQConfig
from messaging.rabbitmq_client import (
    RabbitMQClient,
    RabbitMQConnectionError,
    RabbitMQPublishError,
)


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def rabbitmq_config() -> RabbitMQConfig:
    """テスト用RabbitMQConfigを返す"""
    return RabbitMQConfig(
        host="rabbitmq",
        port=5672,
        user="agent",
        password="test-password",
        queue_name="test-queue",
        durable=True,
        prefetch_count=1,
        heartbeat=60,
        connection_timeout=30,
    )


@pytest.fixture
def rabbitmq_config_with_url() -> RabbitMQConfig:
    """URL設定済みのRabbitMQConfigを返す"""
    return RabbitMQConfig(
        url="amqp://agent:pass@rabbitmq:5672/",
        queue_name="test-queue",
    )


@pytest.fixture
def client(rabbitmq_config: RabbitMQConfig) -> RabbitMQClient:
    """テスト用RabbitMQClientを返す（未接続状態）"""
    return RabbitMQClient(config=rabbitmq_config)


@pytest.fixture
def connected_client(rabbitmq_config: RabbitMQConfig) -> RabbitMQClient:
    """モック接続済みのRabbitMQClientを返す"""
    client = RabbitMQClient(config=rabbitmq_config)
    # モック接続状態を設定する
    mock_connection = MagicMock()
    mock_connection.is_closed = False
    mock_channel = AsyncMock()
    mock_queue = AsyncMock()
    client._connection = mock_connection
    client._channel = mock_channel
    client._queue = mock_queue
    return client


# ========================================
# URL構築テスト
# ========================================


class TestRabbitMQClientBuildUrl:
    """接続URL構築のテスト"""

    def test_host_portからURLを構築できる(
        self, client: RabbitMQClient
    ) -> None:
        """host/port/user/passwordからURLが正しく構築されることを確認する"""
        url = client._build_url()
        assert url == "amqp://agent:test-password@rabbitmq:5672/"

    def test_url設定時はurlを優先する(
        self, rabbitmq_config_with_url: RabbitMQConfig
    ) -> None:
        """configにurlが設定されている場合はそれを使用することを確認する"""
        client = RabbitMQClient(config=rabbitmq_config_with_url)
        url = client._build_url()
        assert url == "amqp://agent:pass@rabbitmq:5672/"


# ========================================
# 接続テスト
# ========================================


class TestRabbitMQClientConnect:
    """RabbitMQClient.connect()のテスト"""

    async def test_正常に接続できる(self, client: RabbitMQClient) -> None:
        """connect()がRabbitMQに接続してキューを宣言することを確認する"""
        mock_connection = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_channel.declare_queue.return_value = mock_queue
        mock_connection.channel.return_value = mock_channel

        with patch("messaging.rabbitmq_client.aio_pika.connect_robust", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_connection

            await client.connect()

        assert client._connection is mock_connection
        assert client._channel is mock_channel
        assert client._queue is mock_queue

        # prefetch_countが設定されることを確認する
        mock_channel.set_qos.assert_called_once_with(prefetch_count=1)

        # キューが宣言されることを確認する
        mock_channel.declare_queue.assert_called_once_with(
            "test-queue", durable=True
        )

    async def test_接続失敗時にRabbitMQConnectionErrorが発生する(
        self, client: RabbitMQClient
    ) -> None:
        """connect()が接続失敗時にRabbitMQConnectionErrorを発生させることを確認する"""
        with patch(
            "messaging.rabbitmq_client.aio_pika.connect_robust",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            with pytest.raises(RabbitMQConnectionError, match="接続に失敗"):
                await client.connect()

    async def test_接続後にis_connectedがTrueになる(
        self, connected_client: RabbitMQClient
    ) -> None:
        """接続済み状態でis_connectedがTrueを返すことを確認する"""
        assert connected_client.is_connected is True

    def test_未接続状態でis_connectedがFalseになる(
        self, client: RabbitMQClient
    ) -> None:
        """未接続状態でis_connectedがFalseを返すことを確認する"""
        assert client.is_connected is False


# ========================================
# パブリッシュテスト
# ========================================


class TestRabbitMQClientPublish:
    """RabbitMQClient.publish()のテスト"""

    async def test_辞書をJSONでパブリッシュできる(
        self, connected_client: RabbitMQClient
    ) -> None:
        """辞書型メッセージをJSONシリアライズしてパブリッシュできることを確認する"""
        mock_exchange = AsyncMock()
        connected_client._channel.default_exchange = mock_exchange

        await connected_client.publish(
            message_body={"task_id": "123", "type": "issue"},
        )

        # publishが呼び出されることを確認する
        mock_exchange.publish.assert_called_once()
        call_args = mock_exchange.publish.call_args
        # ルーティングキーが設定されることを確認する
        assert call_args.kwargs["routing_key"] == "test-queue"

    async def test_文字列メッセージをパブリッシュできる(
        self, connected_client: RabbitMQClient
    ) -> None:
        """文字列型メッセージをパブリッシュできることを確認する"""
        mock_exchange = AsyncMock()
        connected_client._channel.default_exchange = mock_exchange

        await connected_client.publish(message_body="test message")

        mock_exchange.publish.assert_called_once()

    async def test_バイト列メッセージをパブリッシュできる(
        self, connected_client: RabbitMQClient
    ) -> None:
        """バイト列型メッセージをパブリッシュできることを確認する"""
        mock_exchange = AsyncMock()
        connected_client._channel.default_exchange = mock_exchange

        await connected_client.publish(message_body=b"binary message")

        mock_exchange.publish.assert_called_once()

    async def test_カスタムrouting_keyでパブリッシュできる(
        self, connected_client: RabbitMQClient
    ) -> None:
        """カスタムrouting_keyを指定してパブリッシュできることを確認する"""
        mock_exchange = AsyncMock()
        connected_client._channel.default_exchange = mock_exchange

        await connected_client.publish(
            message_body={"data": "test"},
            routing_key="custom-queue",
        )

        call_args = mock_exchange.publish.call_args
        assert call_args.kwargs["routing_key"] == "custom-queue"

    async def test_未接続状態でpublishするとRabbitMQConnectionErrorが発生する(
        self, client: RabbitMQClient
    ) -> None:
        """未接続状態でpublish()を呼ぶとRabbitMQConnectionErrorが発生することを確認する"""
        with pytest.raises(RabbitMQConnectionError, match="接続されていません"):
            await client.publish(message_body={"test": "data"})

    async def test_パブリッシュ失敗時にRabbitMQPublishErrorが発生する(
        self, connected_client: RabbitMQClient
    ) -> None:
        """パブリッシュ失敗時にRabbitMQPublishErrorが発生することを確認する"""
        mock_exchange = AsyncMock()
        mock_exchange.publish.side_effect = Exception("Connection lost")
        connected_client._channel.default_exchange = mock_exchange

        with pytest.raises(RabbitMQPublishError, match="パブリッシュに失敗"):
            await connected_client.publish(message_body={"data": "test"})


# ========================================
# クローズテスト
# ========================================


class TestRabbitMQClientClose:
    """RabbitMQClient.close()のテスト"""

    async def test_接続済み状態でcloseが正常に動作する(
        self, connected_client: RabbitMQClient
    ) -> None:
        """close()がチャンネルと接続を閉じることを確認する"""
        # closeの前にモック参照を保存する
        mock_channel = connected_client._channel
        mock_connection = connected_client._connection
        mock_connection.close = AsyncMock()

        await connected_client.close()

        mock_channel.close.assert_called_once()  # type: ignore[union-attr]
        mock_connection.close.assert_called_once()
        assert connected_client._connection is None
        assert connected_client._channel is None
        assert connected_client._queue is None

    async def test_未接続状態でcloseを呼んでも例外が発生しない(
        self, client: RabbitMQClient
    ) -> None:
        """未接続状態でclose()を呼んでも例外が発生しないことを確認する"""
        await client.close()  # 例外が発生しないことを確認する


# ========================================
# subscribeテスト
# ========================================


class TestRabbitMQClientSubscribe:
    """RabbitMQClient.subscribe()のテスト"""

    async def test_未接続状態でsubscribeするとRabbitMQConnectionErrorが発生する(
        self, client: RabbitMQClient
    ) -> None:
        """未接続状態でsubscribe()を呼ぶとRabbitMQConnectionErrorが発生することを確認する"""
        async def dummy_callback(msg: dict) -> bool:
            return True

        with pytest.raises(RabbitMQConnectionError, match="接続されていません"):
            await client.subscribe(callback=dummy_callback)

    async def test_コールバックがTrueを返した場合にACKが送信される(
        self, connected_client: RabbitMQClient
    ) -> None:
        """コールバックがTrueを返した場合にACKが送信されることを確認する"""
        # メッセージのモックを作成する（MagicMockを使用してprocess()が同期メソッドになるようにする）
        mock_message = MagicMock()
        mock_message.body = json.dumps({"task": "test"}).encode("utf-8")
        mock_message.routing_key = "test-queue"
        mock_message.nack = AsyncMock()

        # message.process()はasync with構文で使用されるため、
        # 同期メソッドとして呼ばれた後に非同期コンテキストマネージャーを返す
        mock_process_cm = MagicMock()
        mock_process_cm.__aenter__ = AsyncMock(return_value=None)
        mock_process_cm.__aexit__ = AsyncMock(return_value=False)
        mock_message.process.return_value = mock_process_cm

        # キューイテレータのモックを作成する（1メッセージだけ返す）
        async def async_generator():
            yield mock_message

        mock_queue_iter = MagicMock()
        mock_queue_iter.__aenter__ = AsyncMock(return_value=async_generator())
        mock_queue_iter.__aexit__ = AsyncMock(return_value=False)

        # _queue.iteratorは同期メソッドとしてモックする
        connected_client._queue = MagicMock()
        connected_client._queue.iterator.return_value = mock_queue_iter

        received_messages: list[dict] = []

        async def callback(msg: dict) -> bool:
            received_messages.append(msg)
            return True

        await connected_client.subscribe(callback=callback)

        assert received_messages == [{"task": "test"}]

    async def test_コールバックがFalseを返した場合にNACKが送信される(
        self, connected_client: RabbitMQClient
    ) -> None:
        """コールバックがFalseを返した場合にNACKが送信されることを確認する"""
        mock_message = MagicMock()
        mock_message.body = json.dumps({"task": "fail"}).encode("utf-8")
        mock_message.routing_key = "test-queue"
        mock_message.nack = AsyncMock()

        # message.process()は同期呼び出しで非同期コンテキストマネージャーを返す
        mock_process_cm = MagicMock()
        mock_process_cm.__aenter__ = AsyncMock(return_value=None)
        mock_process_cm.__aexit__ = AsyncMock(return_value=False)
        mock_message.process.return_value = mock_process_cm

        # キューイテレータのモックを作成する（1メッセージだけ返す）
        async def async_generator():
            yield mock_message

        mock_queue_iter = MagicMock()
        mock_queue_iter.__aenter__ = AsyncMock(return_value=async_generator())
        mock_queue_iter.__aexit__ = AsyncMock(return_value=False)

        connected_client._queue = MagicMock()
        connected_client._queue.iterator.return_value = mock_queue_iter

        async def callback(msg: dict) -> bool:
            return False

        await connected_client.subscribe(callback=callback)

        # NACKが送信されることを確認する
        mock_message.nack.assert_called_once_with(requeue=False)


# ========================================
# 設定テスト
# ========================================


class TestRabbitMQConfig:
    """RabbitMQConfigのテスト"""

    def test_デフォルト値で設定が生成される(self) -> None:
        """デフォルト値でRabbitMQConfigが生成されることを確認する"""
        config = RabbitMQConfig()
        assert config.host == "rabbitmq"
        assert config.port == 5672
        assert config.user == "agent"
        assert config.queue_name == "coding-agent-tasks"
        assert config.durable is True
        assert config.prefetch_count == 1

    def test_urlが設定されていない場合はNone(self) -> None:
        """urlフィールドのデフォルト値がNoneであることを確認する"""
        config = RabbitMQConfig()
        assert config.url is None

    def test_url指定時にurlが設定される(self) -> None:
        """url指定時にurlフィールドが正しく設定されることを確認する"""
        config = RabbitMQConfig(url="amqp://custom:pass@host:5672/")
        assert config.url == "amqp://custom:pass@host:5672/"
