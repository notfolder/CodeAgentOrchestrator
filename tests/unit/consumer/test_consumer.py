"""
Consumerの単体テスト

RabbitMQClientとTaskHandlerをモックし、タスク取得・ステータス更新・
SIGTERMシグナル受信時のグレースフルシャットダウンを検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consumer.consumer import Consumer
from shared.models.task import Task


@pytest.fixture
def mock_rabbitmq_client() -> MagicMock:
    """テスト用RabbitMQClientモックを返す"""
    client = MagicMock()
    client.subscribe = AsyncMock()
    return client


@pytest.fixture
def mock_task_processor() -> MagicMock:
    """テスト用TaskProcessorモックを返す"""
    processor = MagicMock()
    processor.process = AsyncMock(return_value=True)
    processor.resume_suspended_tasks = AsyncMock(return_value=0)
    return processor


@pytest.fixture
def consumer(
    mock_rabbitmq_client: MagicMock,
    mock_task_processor: MagicMock,
) -> Consumer:
    """テスト用Consumerインスタンスを返す"""
    return Consumer(
        rabbitmq_client=mock_rabbitmq_client,
        task_processor=mock_task_processor,
    )


def _make_message_data() -> dict:
    """テスト用メッセージデータを生成する"""
    return {
        "task_uuid": "msg-uuid-001",
        "task_type": "merge_request",
        "project_id": 1,
        "issue_iid": None,
        "mr_iid": 10,
        "username": "testuser",
    }


class TestParseTask:
    """_parse_task()のテスト"""

    def test_正常なメッセージをTaskに変換できる(
        self, consumer: Consumer
    ) -> None:
        """有効なメッセージ辞書からTaskオブジェクトが生成されることを確認する"""
        message_data = _make_message_data()
        task = consumer._parse_task(message_data)

        assert task is not None
        assert task.task_uuid == "msg-uuid-001"
        assert task.task_type == "merge_request"
        assert task.project_id == 1

    def test_不正なメッセージはNoneを返す(
        self, consumer: Consumer
    ) -> None:
        """不正な形式のメッセージはNoneが返されることを確認する"""
        task = consumer._parse_task({"invalid": "data"})
        assert task is None

    def test_空辞書はNoneを返す(self, consumer: Consumer) -> None:
        """空の辞書はNoneが返されることを確認する"""
        task = consumer._parse_task({})
        assert task is None


class TestSetupSignalHandlers:
    """_setup_signal_handlers()のテスト"""

    def test_SIGTERMでshutdownフラグが立つ(
        self, consumer: Consumer
    ) -> None:
        """SIGTERMシグナルを送信するとshutdownフラグがTrueになることを確認する"""
        consumer._setup_signal_handlers()
        assert consumer._shutdown is False

        # SIGTERMシグナルを模擬する
        signal.raise_signal(signal.SIGTERM)

        assert consumer._shutdown is True


class TestStop:
    """stop()のテスト"""

    def test_stopでshutdownフラグが立つ(self, consumer: Consumer) -> None:
        """stop()を呼び出すとshutdownフラグがTrueになることを確認する"""
        assert consumer._shutdown is False
        consumer.stop()
        assert consumer._shutdown is True


class TestConsumeTasks:
    """consume_tasks()のテスト"""

    async def test_正常なタスクを処理できる(
        self,
        consumer: Consumer,
        mock_rabbitmq_client: MagicMock,
        mock_task_processor: MagicMock,
    ) -> None:
        """RabbitMQからタスクを受け取りTaskProcessor.process()が呼ばれることを確認する"""
        import asyncio

        message_data = _make_message_data()
        callback_registered = asyncio.Event()
        captured_callback = None

        async def fake_subscribe(callback, auto_ack):
            nonlocal captured_callback
            captured_callback = callback
            callback_registered.set()  # コールバック登録完了を通知する
            # consumeTasksが終了しないよう待機する
            await asyncio.get_event_loop().create_future()

        mock_rabbitmq_client.subscribe = fake_subscribe

        # consume_tasksをバックグラウンドで開始する
        task = asyncio.ensure_future(consumer.consume_tasks())
        # コールバックが登録されるまで待機する
        await callback_registered.wait()

        assert captured_callback is not None
        result = await captured_callback(message_data)

        assert result is True
        mock_task_processor.process.assert_awaited_once()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_シャットダウン時はメッセージをスキップする(
        self,
        consumer: Consumer,
        mock_rabbitmq_client: MagicMock,
        mock_task_processor: MagicMock,
    ) -> None:
        """shutdownフラグが立っている場合はメッセージ処理をスキップすることを確認する"""
        import asyncio

        consumer._shutdown = True
        message_data = _make_message_data()
        callback_registered = asyncio.Event()
        captured_callback = None

        async def fake_subscribe(callback, auto_ack):
            nonlocal captured_callback
            captured_callback = callback
            callback_registered.set()
            await asyncio.get_event_loop().create_future()

        mock_rabbitmq_client.subscribe = fake_subscribe

        task = asyncio.ensure_future(consumer.consume_tasks())
        await callback_registered.wait()

        assert captured_callback is not None
        result = await captured_callback(message_data)

        # シャットダウン時はFalseを返す（スキップ）
        assert result is False
        mock_task_processor.process.assert_not_awaited()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_不正なメッセージはFalseを返す(
        self,
        consumer: Consumer,
        mock_rabbitmq_client: MagicMock,
        mock_task_processor: MagicMock,
    ) -> None:
        """パース不能なメッセージはFalseが返されることを確認する"""
        import asyncio

        callback_registered = asyncio.Event()
        captured_callback = None

        async def fake_subscribe(callback, auto_ack):
            nonlocal captured_callback
            captured_callback = callback
            callback_registered.set()
            await asyncio.get_event_loop().create_future()

        mock_rabbitmq_client.subscribe = fake_subscribe

        task = asyncio.ensure_future(consumer.consume_tasks())
        await callback_registered.wait()

        assert captured_callback is not None
        result = await captured_callback({"invalid": "data"})

        assert result is False
        mock_task_processor.process.assert_not_awaited()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestRunConsumerContinuous:
    """run_consumer_continuous()のテスト"""

    async def test_開始時に中断タスクを再開する(
        self,
        consumer: Consumer,
        mock_task_processor: MagicMock,
        mock_rabbitmq_client: MagicMock,
    ) -> None:
        """Consumer起動時にTaskProcessor.resume_suspended_tasks()が呼ばれることを確認する"""
        mock_task_processor.resume_suspended_tasks = AsyncMock(return_value=2)

        # subscribe()を即座に終了させる
        async def fake_subscribe(callback, auto_ack):
            pass

        mock_rabbitmq_client.subscribe = fake_subscribe

        await consumer.run_consumer_continuous()

        mock_task_processor.resume_suspended_tasks.assert_awaited_once()

    async def test_中断タスク再開エラー時も処理を継続する(
        self,
        consumer: Consumer,
        mock_task_processor: MagicMock,
        mock_rabbitmq_client: MagicMock,
    ) -> None:
        """resume_suspended_tasks()がエラーを投げても処理が継続することを確認する"""
        mock_task_processor.resume_suspended_tasks = AsyncMock(
            side_effect=Exception("resume error")
        )

        async def fake_subscribe(callback, auto_ack):
            pass

        mock_rabbitmq_client.subscribe = fake_subscribe

        # 例外が発生せずに完了することを確認する
        await consumer.run_consumer_continuous()
