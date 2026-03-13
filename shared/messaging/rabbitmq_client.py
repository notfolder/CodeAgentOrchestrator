"""
RabbitMQクライアントモジュール

aio-pikaライブラリを使用してRabbitMQへの接続・パブリッシュ・サブスクライブを提供する。
Producer・Consumerの両方から利用可能な共通クライアントとして実装する。

AUTOMATA_CODEX_SPEC.md § 2.2.1、§ 2.2.2（Producer/Consumer）、§ 13.1（RabbitMQ設定）に準拠する。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import aio_pika
import aio_pika.abc

from config.models import RabbitMQConfig

logger = logging.getLogger(__name__)

# メッセージ再配信フラグ（NACKかつrequeue=Trueで再配信）
_DEFAULT_REQUEUE_ON_NACK = False


class RabbitMQConnectionError(Exception):
    """RabbitMQ接続失敗時に発生する例外"""


class RabbitMQPublishError(Exception):
    """メッセージ送信失敗時に発生する例外"""


class RabbitMQClient:
    """
    RabbitMQへの非同期接続・パブリッシュ・サブスクライブを行うクライアントクラス。

    aio-pikaのRobustConnectionを使用して自動再接続機能を提供する。
    接続失敗時はaio-pikaが自動的に再接続を試みる。
    メッセージのACK/NACK処理、キューの永続化設定をサポートする。

    AUTOMATA_CODEX_SPEC.md § 14.1（config.yaml: rabbitmq設定項目）に準拠する。

    Attributes:
        config: RabbitMQ接続設定
    """

    def __init__(self, config: RabbitMQConfig) -> None:
        """
        RabbitMQClientを初期化する。

        Args:
            config: RabbitMQ接続設定（RabbitMQConfigインスタンス）
        """
        self.config = config
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._queue: aio_pika.abc.AbstractQueue | None = None

    def _build_url(self) -> str:
        """
        接続URL文字列を構築する。

        configにurlが設定されている場合はそれを使用する。
        Noneの場合はhost/port/user/passwordから構築する。

        Returns:
            amqp://user:password@host:port/ 形式の接続URL文字列
        """
        if self.config.url is not None:
            return self.config.url
        return (
            f"amqp://{self.config.user}:{self.config.password}"
            f"@{self.config.host}:{self.config.port}/"
        )

    async def connect(self) -> None:
        """
        RabbitMQへ接続し、チャンネルとキューを設定する。

        aio_pika.connect_robust()を使用して自動再接続機能付き接続を確立する。
        接続後にチャンネルを開き、設定に従ってキューを宣言する。
        prefetch_countを設定してConsumer1台あたりの同時処理数を制限する。

        Raises:
            RabbitMQConnectionError: 接続失敗時
        """
        url = self._build_url()
        try:
            logger.info("RabbitMQに接続します: host=%s, port=%d", self.config.host, self.config.port)
            self._connection = await aio_pika.connect_robust(
                url,
                heartbeat=self.config.heartbeat,
                connection_timeout=float(self.config.connection_timeout),
            )
            # チャンネルを開く
            self._channel = await self._connection.channel()
            # prefetch_countを設定（Consumer1台あたりの同時処理数制限）
            await self._channel.set_qos(prefetch_count=self.config.prefetch_count)
            # キューを宣言する（永続化設定に従う）
            self._queue = await self._channel.declare_queue(
                self.config.queue_name,
                durable=self.config.durable,
            )
            logger.info(
                "RabbitMQ接続完了: queue=%s, durable=%s",
                self.config.queue_name,
                self.config.durable,
            )
        except Exception as exc:
            logger.error("RabbitMQ接続失敗: %s", exc)
            raise RabbitMQConnectionError(
                f"RabbitMQへの接続に失敗しました: {exc}"
            ) from exc

    async def publish(
        self,
        message_body: dict[str, Any] | str | bytes,
        routing_key: str | None = None,
    ) -> None:
        """
        メッセージをキューにパブリッシュする。

        Args:
            message_body: 送信するメッセージ本体。辞書の場合はJSONにシリアライズする。
            routing_key: ルーティングキー。Noneの場合はconfig.queue_nameを使用する。

        Raises:
            RabbitMQConnectionError: 接続されていない場合
            RabbitMQPublishError: 送信失敗時
        """
        if self._channel is None:
            raise RabbitMQConnectionError(
                "RabbitMQに接続されていません。connect()を先に呼び出してください。"
            )

        # メッセージ本体をバイト列に変換する
        if isinstance(message_body, dict):
            body_bytes = json.dumps(message_body, ensure_ascii=False).encode("utf-8")
        elif isinstance(message_body, str):
            body_bytes = message_body.encode("utf-8")
        else:
            body_bytes = message_body

        target_routing_key = routing_key or self.config.queue_name

        try:
            message = aio_pika.Message(
                body=body_bytes,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # 永続化メッセージ
                content_type="application/json",
            )
            await self._channel.default_exchange.publish(
                message,
                routing_key=target_routing_key,
            )
            logger.debug(
                "メッセージをパブリッシュしました: routing_key=%s, size=%d",
                target_routing_key,
                len(body_bytes),
            )
        except Exception as exc:
            logger.error("メッセージパブリッシュ失敗: %s", exc)
            raise RabbitMQPublishError(
                f"メッセージのパブリッシュに失敗しました: {exc}"
            ) from exc

    async def subscribe(
        self,
        callback: Callable[
            [dict[str, Any]],
            Coroutine[Any, Any, bool],
        ],
        auto_ack: bool = False,
    ) -> None:
        """
        キューからメッセージを受信し、コールバック関数で処理する。

        aio-pikaのイテレータ方式でメッセージを順次受信する。
        コールバック関数がTrueを返した場合はACK、Falseを返した場合はNACKを送信する。

        Args:
            callback: メッセージ処理コールバック関数。
                      引数として解析済みのメッセージ辞書を受け取り、
                      処理成功時はTrue、失敗時はFalseを返す非同期関数。
            auto_ack: Trueの場合は自動ACK（デフォルト: False）

        Raises:
            RabbitMQConnectionError: 接続されていない場合
        """
        if self._queue is None:
            raise RabbitMQConnectionError(
                "RabbitMQに接続されていません。connect()を先に呼び出してください。"
            )

        logger.info("メッセージの受信を開始します: queue=%s", self.config.queue_name)

        async with self._queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(requeue=_DEFAULT_REQUEUE_ON_NACK):
                    try:
                        # メッセージ本体をJSONデコードする
                        body_str = message.body.decode("utf-8")
                        message_data: dict[str, Any] = json.loads(body_str)
                        logger.debug(
                            "メッセージを受信しました: routing_key=%s",
                            message.routing_key,
                        )

                        if auto_ack:
                            # auto_ackの場合はコールバック後にcontextmanagerがACKを送信する
                            await callback(message_data)
                        else:
                            # コールバックの戻り値に応じてACK/NACKを制御する
                            success = await callback(message_data)
                            if not success:
                                # 処理失敗: NACKを送信（再配信しない）
                                logger.warning(
                                    "メッセージ処理失敗: NACKを送信します"
                                )
                                await message.nack(requeue=_DEFAULT_REQUEUE_ON_NACK)
                                return

                    except json.JSONDecodeError as exc:
                        logger.error(
                            "メッセージのJSONデコードに失敗しました: %s", exc
                        )
                        # 不正なJSONはNACKを送信して破棄する
                        await message.nack(requeue=False)

    async def close(self) -> None:
        """
        RabbitMQ接続を閉じる。

        チャンネルと接続を順番にクローズする。
        接続されていない場合は何もしない。
        """
        if self._channel is not None:
            try:
                await self._channel.close()
            except Exception as exc:
                logger.warning("チャンネルクローズ時にエラーが発生しました: %s", exc)
            finally:
                self._channel = None
                self._queue = None

        if self._connection is not None:
            try:
                await self._connection.close()
                logger.info("RabbitMQ接続を閉じました")
            except Exception as exc:
                logger.warning("接続クローズ時にエラーが発生しました: %s", exc)
            finally:
                self._connection = None

    @property
    def is_connected(self) -> bool:
        """
        RabbitMQに接続されているかどうかを返す。

        Returns:
            接続済みの場合はTrue、未接続の場合はFalse
        """
        return (
            self._connection is not None
            and not self._connection.is_closed
        )
