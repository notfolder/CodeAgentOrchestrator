"""
Producerの単体テスト

FastAPIのTestClientとRabbitMQClientのモックを用いて、
Webhook受信時のタスクエンキュー・重複タスク検出・処理対象外イベントの除外を検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from producer.producer import Producer, create_webhook_app, is_webhook_mode
from shared.config.models import GitLabConfig, ProducerConfig, RabbitMQConfig
from shared.models.task import Task


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    client = MagicMock()
    return client


@pytest.fixture
def mock_rabbitmq_client() -> MagicMock:
    """テスト用RabbitMQClientモックを返す"""
    client = MagicMock()
    client.publish = AsyncMock()
    return client


@pytest.fixture
def mock_config_manager() -> MagicMock:
    """テスト用ConfigManagerモックを返す"""
    manager = MagicMock()
    manager.get_gitlab_config.return_value = GitLabConfig(
        bot_label="coding agent",
        processing_label="coding agent processing",
        done_label="coding agent done",
        paused_label="coding agent paused",
        stopped_label="coding agent stopped",
    )
    manager.get_producer_config.return_value = ProducerConfig(
        interval_seconds=30,
    )
    return manager


@pytest.fixture
def mock_task_repository() -> MagicMock:
    """テスト用TaskRepositoryモックを返す"""
    repo = MagicMock()
    repo.list_tasks = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def producer(
    mock_gitlab_client: MagicMock,
    mock_rabbitmq_client: MagicMock,
    mock_config_manager: MagicMock,
    mock_task_repository: MagicMock,
) -> Producer:
    """テスト用Producerインスタンスを返す"""
    return Producer(
        gitlab_client=mock_gitlab_client,
        rabbitmq_client=mock_rabbitmq_client,
        config_manager=mock_config_manager,
        task_repository=mock_task_repository,
        project_id=1,
    )


def _make_task(
    task_type: str = "issue",
    issue_iid: int | None = 1,
    mr_iid: int | None = None,
) -> Task:
    """テスト用Taskを生成する"""
    return Task(
        task_uuid="test-uuid-001",
        task_type=task_type,
        project_id=1,
        issue_iid=issue_iid,
        mr_iid=mr_iid,
        username="testuser",
    )


class TestIsDuplicateTask:
    """_is_duplicate_task()のテスト"""

    async def test_重複タスクがない場合はFalseを返す(
        self,
        producer: Producer,
        mock_task_repository: MagicMock,
    ) -> None:
        """tasksテーブルに該当タスクがない場合はFalseが返されることを確認する"""
        mock_task_repository.list_tasks = AsyncMock(return_value=[])
        task = _make_task(task_type="issue", issue_iid=1)

        result = await producer._is_duplicate_task(task)
        assert result is False

    async def test_処理中タスクが存在する場合はTrueを返す(
        self,
        producer: Producer,
        mock_task_repository: MagicMock,
    ) -> None:
        """tasksテーブルにrunningのタスクが存在する場合はTrueが返されることを確認する"""
        mock_task_repository.list_tasks = AsyncMock(return_value=[{"uuid": "existing"}])
        task = _make_task(task_type="issue", issue_iid=1)

        result = await producer._is_duplicate_task(task)
        assert result is True

    async def test_issue_iidがNoneの場合はFalseを返す(
        self,
        producer: Producer,
    ) -> None:
        """issue_iidがNoneの場合はFalseが返されることを確認する"""
        task = Task(
            task_uuid="test-uuid",
            task_type="issue",
            project_id=1,
            issue_iid=None,
            mr_iid=None,
        )
        result = await producer._is_duplicate_task(task)
        assert result is False

    async def test_リポジトリ例外時はFalseを返す(
        self,
        producer: Producer,
        mock_task_repository: MagicMock,
    ) -> None:
        """リポジトリがエラーを投げた場合はFalseが返されることを確認する"""
        mock_task_repository.list_tasks = AsyncMock(side_effect=Exception("DB error"))
        task = _make_task(task_type="issue", issue_iid=1)

        result = await producer._is_duplicate_task(task)
        assert result is False


class TestEnqueueTask:
    """_enqueue_task()のテスト"""

    async def test_新規タスクをエンキューできる(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """重複なしのタスクがRabbitMQにパブリッシュされることを確認する"""
        mock_task_repository.list_tasks = AsyncMock(return_value=[])
        mock_rabbitmq_client.publish = AsyncMock()
        issue = MagicMock()
        issue.labels = ["coding agent"]
        producer.gitlab_client.get_issue.return_value = issue

        task = _make_task(task_type="issue", issue_iid=1)
        result = await producer._enqueue_task(task)

        assert result is True
        mock_rabbitmq_client.publish.assert_awaited_once()

    async def test_重複タスクはスキップされる(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """既存タスクが存在する場合はエンキューされないことを確認する"""
        mock_task_repository.list_tasks = AsyncMock(return_value=[{"uuid": "existing"}])

        task = _make_task(task_type="issue", issue_iid=1)
        result = await producer._enqueue_task(task)

        assert result is False
        mock_rabbitmq_client.publish.assert_not_awaited()

    async def test_RabbitMQ送信失敗時はFalseを返す(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """RabbitMQ送信に失敗した場合はFalseが返されることを確認する"""
        mock_task_repository.list_tasks = AsyncMock(return_value=[])
        mock_rabbitmq_client.publish = AsyncMock(side_effect=Exception("publish error"))

        task = _make_task(task_type="issue", issue_iid=1)
        result = await producer._enqueue_task(task)

        assert result is False


class TestProduceTasks:
    """produce_tasks()のテスト"""

    async def test_未処理タスクをエンキューできる(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """GitLab APIからタスクを取得してエンキューできることを確認する"""
        mock_task_repository.list_tasks = AsyncMock(return_value=[])
        mock_rabbitmq_client.publish = AsyncMock()

        from shared.models.gitlab import GitLabIssue

        issue = GitLabIssue(iid=1, title="Test", project_id=1, labels=["coding agent"])
        producer.gitlab_client.list_issues.return_value = [issue]
        producer.gitlab_client.list_merge_requests.return_value = []
        issue_obj = MagicMock()
        issue_obj.labels = ["coding agent"]
        producer.gitlab_client.get_issue.return_value = issue_obj

        count = await producer.produce_tasks()

        assert count == 1
        mock_rabbitmq_client.publish.assert_awaited_once()

    async def test_タスクが0件の場合は0を返す(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
    ) -> None:
        """GitLab APIがタスクを返さない場合にカウントが0であることを確認する"""
        producer.gitlab_client.list_issues.return_value = []
        producer.gitlab_client.list_merge_requests.return_value = []

        count = await producer.produce_tasks()

        assert count == 0
        mock_rabbitmq_client.publish.assert_not_awaited()

    async def test_produce_tasks実行中にFileLockが取得される(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
    ) -> None:
        """produce_tasks()がFileLockを取得してから処理することを確認する"""
        producer.gitlab_client.list_issues.return_value = []
        producer.gitlab_client.list_merge_requests.return_value = []

        acquired = []

        with patch("producer.filelock_util.FileLock") as mock_filelock_cls:
            # コンテキストマネージャとして使えるモックを生成する
            mock_lock_instance = MagicMock()
            mock_lock_instance.__enter__ = lambda self: (acquired.append(True), self)[1]
            mock_lock_instance.__exit__ = MagicMock(return_value=False)
            mock_filelock_cls.return_value = mock_lock_instance

            await producer.produce_tasks()

        # FileLockが生成されてコンテキストマネージャが呼ばれたことを確認する
        mock_filelock_cls.assert_called_once()
        assert acquired, "FileLockのコンテキストマネージャが呼ばれていません"


class TestIsWebhookMode:
    """is_webhook_mode()のテスト"""

    def test_環境変数が未設定の場合はPollingモード(self) -> None:
        """PRODUCER_WEBHOOK_MODEが未設定の場合はFalseが返されることを確認する"""
        with patch.dict("os.environ", {}, clear=True):
            assert is_webhook_mode() is False

    def test_trueを設定するとWebhookモードになる(self) -> None:
        """PRODUCER_WEBHOOK_MODE=trueの場合はTrueが返されることを確認する"""
        with patch.dict("os.environ", {"PRODUCER_WEBHOOK_MODE": "true"}):
            assert is_webhook_mode() is True

    def test_大文字小文字を区別しない(self) -> None:
        """PRODUCER_WEBHOOK_MODE=TRUEでもTrueが返されることを確認する"""
        with patch.dict("os.environ", {"PRODUCER_WEBHOOK_MODE": "TRUE"}):
            assert is_webhook_mode() is True

    def test_false設定でPollingモードになる(self) -> None:
        """PRODUCER_WEBHOOK_MODE=falseの場合はFalseが返されることを確認する"""
        with patch.dict("os.environ", {"PRODUCER_WEBHOOK_MODE": "false"}):
            assert is_webhook_mode() is False


class TestWebhookApp:
    """create_webhook_app()のテスト"""

    def test_アプリケーションが生成される(self, producer: Producer) -> None:
        """create_webhook_app()でFastAPIアプリが返されることを確認する"""
        from fastapi import FastAPI

        app = create_webhook_app(producer)
        assert isinstance(app, FastAPI)

    async def test_webhookエンドポイントがTaskをエンキューする(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
        mock_task_repository: MagicMock,
    ) -> None:
        """POST /webhookでIssueイベントを受信するとタスクがエンキューされることを確認する"""
        import anyio
        from httpx import ASGITransport, AsyncClient

        mock_task_repository.list_tasks = AsyncMock(return_value=[])
        mock_rabbitmq_client.publish = AsyncMock()
        issue_obj = MagicMock()
        issue_obj.labels = ["coding agent"]
        producer.gitlab_client.get_issue.return_value = issue_obj

        app = create_webhook_app(producer)

        payload = {
            "object_attributes": {"iid": 1, "action": "open"},
            "project": {"id": 1},
            "labels": [{"title": "coding agent"}],
            "user": {"username": "testuser"},
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/webhook",
                json=payload,
                headers={"X-Gitlab-Event": "Issue Hook"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "enqueued"

    async def test_処理対象外イベントはskippedを返す(self, producer: Producer) -> None:
        """処理対象外のWebhookイベントはskippedレスポンスを返すことを確認する"""
        from httpx import ASGITransport, AsyncClient

        app = create_webhook_app(producer)

        payload = {
            "object_attributes": {"iid": 1, "action": "close"},
            "project": {"id": 1},
            "labels": [],
            "user": {"username": "testuser"},
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/webhook",
                json=payload,
                headers={"X-Gitlab-Event": "Issue Hook"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"

    async def test_ヘルスチェックエンドポイントが機能する(
        self, producer: Producer
    ) -> None:
        """GET /healthが200とok状態を返すことを確認する"""
        from httpx import ASGITransport, AsyncClient

        app = create_webhook_app(producer)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestRunProducerContinuous:
    """run_producer_continuous()のテスト"""

    async def test_shutdownフラグでループが停止する(
        self,
        producer: Producer,
        mock_rabbitmq_client: MagicMock,
    ) -> None:
        """_shutdown=Trueになるとrun_producer_continuous()のループが終了することを確認する"""
        import asyncio

        producer.gitlab_client.list_issues.return_value = []
        producer.gitlab_client.list_merge_requests.return_value = []

        call_count = 0

        async def fake_produce_tasks() -> int:
            nonlocal call_count
            call_count += 1
            # 1回目の呼び出し後にシャットダウンフラグを立てる
            producer._shutdown = True
            return 0

        with patch.object(producer, "produce_tasks", side_effect=fake_produce_tasks):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await producer.run_producer_continuous()

        # produce_tasks()が1回呼ばれた後にループを抜けたことを確認する
        assert call_count == 1
        assert producer._shutdown is True
