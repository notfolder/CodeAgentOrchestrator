"""
Producerモジュール

GitLabからIssue・MRを検出し、RabbitMQにタスクをエンキューする。
WebhookモードとPollingモードの両方に対応し、環境変数で切り替え可能とする。

AUTOMATA_CODEX_SPEC.md § 2.2.1（Producer: タスク検出＆キューイング）に準拠する。
AUTOMATA_CODEX_SPEC.md § 2.3.1（Producer コンポーネント一覧）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.3 Producer（タスク検出コンポーネント）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13.1（デプロイ構成）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13.2（スケーリング戦略）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13.3（監視・ログ）に準拠する。
AUTOMATA_CODEX_SPEC.md § 14.1（producer.interval_seconds 設定）に準拠する。
"""

# NOTE: from __future__ import annotations は FastAPI のルート定義と
# 相性が悪いため使用しない。FastAPIはアノテーション型を実行時に評価するため、
# 文字列アノテーションに変換すると型解決に失敗する。

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 環境変数: Webhookモードを有効にするフラグ
_ENV_WEBHOOK_MODE = "PRODUCER_WEBHOOK_MODE"
# Webhookモードのデフォルトポート
_DEFAULT_WEBHOOK_PORT = 8080


class Producer:
    """
    Producerクラス

    GitLabのIssue・MRを検出してRabbitMQにエンキューするコンポーネント。
    WebhookモードとPollingモードをサポートし、環境変数で切り替える。

    Webhookモード:
        FastAPIによるエンドポイント（POST /webhook）でGitLabのWebhookを受信し、
        リアルタイムでタスクをエンキューする。

    Pollingモード:
        interval_secondsごとにGitLab APIをポーリングして未処理タスクを検出し、
        エンキューする。FileLockで複数Producerの排他制御を行う。

    Attributes:
        gitlab_client: GitLab APIクライアント
        rabbitmq_client: RabbitMQクライアント
        config_manager: 設定管理クラス
        task_repository: タスクリポジトリ（重複検出用）
        project_id: 対象GitLabプロジェクトID（Noneの場合は全プロジェクト横断）
    """

    def __init__(
        self,
        gitlab_client: Any,
        rabbitmq_client: Any,
        config_manager: Any,
        task_repository: Any,
        project_id: int | None,
    ) -> None:
        """
        Producerを初期化する。

        Args:
            gitlab_client: GitLab APIクライアントインスタンス
            rabbitmq_client: RabbitMQクライアントインスタンス
            config_manager: 設定管理クラスインスタンス
            task_repository: タスクリポジトリ（重複タスク検出用）
            project_id: 対象GitLabプロジェクトID。
                        Noneを指定するとPATユーザーにアサインされた全プロジェクトを横断取得する。
        """
        self.gitlab_client = gitlab_client
        self.rabbitmq_client = rabbitmq_client
        self.config_manager = config_manager
        self.task_repository = task_repository
        self.project_id = project_id
        self._shutdown = False

    async def _is_duplicate_task(self, task: Any) -> bool:
        """
        タスクが重複（既に処理中または完了済み）かどうかを確認する。

        tasksテーブルを参照して、同一の識別子を持つタスクが
        running/completed状態で存在する場合は重複とみなす。

        Args:
            task: 検査対象のTaskオブジェクト

        Returns:
            重複している場合True、新規タスクの場合False
        """
        try:
            # タスク識別子を構築する（project_id/issue_iid or mr_iid）
            if task.task_type == "issue" and task.issue_iid is not None:
                task_identifier = f"{task.project_id}/issues/{task.issue_iid}"
            elif task.task_type == "merge_request" and task.mr_iid is not None:
                task_identifier = f"{task.project_id}/merge_requests/{task.mr_iid}"
            else:
                return False

            # tasksテーブルで処理中のタスクを確認する（status=running）
            running_tasks = await self.task_repository.list_tasks(
                task_identifier=task_identifier,
                status="running",
            )
            if running_tasks:
                logger.info(
                    "重複タスクを検出しました（処理中）: task_identifier=%s, existing_count=%d",
                    task_identifier,
                    len(running_tasks),
                )
                return True

        except Exception as exc:
            logger.warning(
                "重複タスク確認中にエラーが発生しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )

        return False

    async def _enqueue_task(self, task: Any) -> bool:
        """
        タスクをRabbitMQにエンキューし、GitLabに処理中ラベルを付与する。

        処理フロー:
        1. 重複チェック: 既に処理中・完了済みの場合はスキップする
        2. RabbitMQにタスクをパブリッシュする
        3. GitLabの対象Issue/MRにprocessing_labelを付与する

        Args:
            task: エンキューするTaskオブジェクト

        Returns:
            エンキュー成功時True、スキップ・失敗時False
        """
        # 1. 重複チェック
        if await self._is_duplicate_task(task):
            logger.info("重複タスクのためスキップします: task_uuid=%s", task.task_uuid)
            return False

        # 2. RabbitMQにパブリッシュ
        try:
            await self.rabbitmq_client.publish(task.model_dump(mode="json"))
            logger.info(
                "タスクをエンキューしました: task_uuid=%s, task_type=%s",
                task.task_uuid,
                task.task_type,
            )
        except Exception as exc:
            logger.error(
                "タスクのエンキューに失敗しました: task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )
            return False

        # 3. GitLabに処理中ラベルを付与する（bot_labelを削除してprocessing_labelを追加する）
        gitlab_config = self.config_manager.get_gitlab_config()
        processing_label = gitlab_config.processing_label
        bot_label = gitlab_config.bot_label
        try:
            if task.task_type == "issue" and task.issue_iid is not None:
                issue = self.gitlab_client.get_issue(
                    project_id=task.project_id,
                    issue_iid=task.issue_iid,
                )
                # bot_labelを削除してprocessing_labelを追加する（coding_agent準拠）
                new_labels = list(
                    (set(issue.labels) - {bot_label}) | {processing_label}
                )
                self.gitlab_client.update_issue_labels(
                    project_id=task.project_id,
                    issue_iid=task.issue_iid,
                    labels=new_labels,
                )
                logger.info(
                    "Issueに処理中ラベルを付与しました: issue_iid=%d", task.issue_iid
                )
            elif task.task_type == "merge_request" and task.mr_iid is not None:
                mr = self.gitlab_client.get_merge_request(
                    project_id=task.project_id,
                    mr_iid=task.mr_iid,
                )
                # bot_labelを削除してprocessing_labelを追加する（coding_agent準拠）
                new_labels = list((set(mr.labels) - {bot_label}) | {processing_label})
                self.gitlab_client.update_merge_request(
                    project_id=task.project_id,
                    mr_iid=task.mr_iid,
                    labels=new_labels,
                )
                logger.info("MRに処理中ラベルを付与しました: mr_iid=%d", task.mr_iid)
        except Exception as exc:
            logger.warning(
                "処理中ラベルの付与に失敗しました（タスクはエンキュー済み）: "
                "task_uuid=%s, error=%s",
                task.task_uuid,
                exc,
            )

        return True

    async def produce_tasks(self) -> int:
        """
        GitLab APIをポーリングして未処理タスクを検出・エンキューする。

        FileLockを使用して複数のProducerプロセスが同時に実行される場合の
        排他制御を行う。

        処理フロー:
        1. FileLockを取得する（取得できない場合はスキップ）
        2. TaskGetterFromGitLabで未処理タスクを取得する
        3. 各タスクを_enqueue_task()でエンキューする

        Returns:
            エンキューしたタスク数
        """
        from producer.filelock_util import FileLock
        from producer.task_getter_from_gitlab import TaskGetterFromGitLab

        gitlab_config = self.config_manager.get_gitlab_config()
        # project_id が None の場合は全プロジェクト横断なので "global" を識別名とする
        lock_name = (
            f"producer_{self.project_id}"
            if self.project_id is not None
            else "producer_global"
        )
        lock = FileLock(lock_name)

        enqueued_count = 0
        with lock:
            logger.info("タスク検出を開始します: project_id=%s", self.project_id)
            getter = TaskGetterFromGitLab(
                gitlab_client=self.gitlab_client,
                gitlab_config=gitlab_config,
                project_id=self.project_id,
            )
            tasks = getter.get_all_unprocessed_tasks()

            for task in tasks:
                success = await self._enqueue_task(task)
                if success:
                    enqueued_count += 1

            logger.info(
                "タスク検出完了: enqueued=%d, total=%d",
                enqueued_count,
                len(tasks),
            )

        return enqueued_count

    async def enqueue_task_from_webhook(self, task: Any) -> bool:
        """
        WebhookイベントからのタスクをエンキューするためのパブリックAPI。

        GitLabEventHandlerで生成したTaskをRabbitMQにエンキューする。
        重複チェックを行った上でエンキューする。

        Args:
            task: エンキューするTaskオブジェクト

        Returns:
            エンキュー成功時True、スキップ・失敗時False
        """
        return await self._enqueue_task(task)

    async def run_producer_continuous(self) -> None:
        """
        Pollingモードでのタスク検出ループを実行する。

        interval_seconds（config.yamlのproducer.interval_seconds）ごとに
        produce_tasks()を呼び出し、未処理タスクを定期的にエンキューする。
        SIGTERMシグナルまたは_shutdownフラグによって停止する。

        AUTOMATA_CODEX_SPEC.md § 2.2.1（定期実行）に準拠する。
        """
        producer_config = self.config_manager.get_producer_config()
        interval = producer_config.interval_seconds

        logger.info("Pollingモードを開始します: interval_seconds=%d", interval)

        while not self._shutdown:
            try:
                count = await self.produce_tasks()
                logger.info("ポーリング完了: enqueued=%d", count)
            except Exception as exc:
                logger.error("タスク検出中にエラーが発生しました: %s", exc)

            # シャットダウン要求があるまで待機する
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Producerポーリングがキャンセルされました")
                break

        logger.info("Producerポーリングを停止しました")

    def stop(self) -> None:
        """
        Producerのポーリングループを停止するシグナルを設定する。

        run_producer_continuous()の次のループ開始前に停止する。
        """
        self._shutdown = True
        logger.info("Producerの停止が要求されました")


def create_webhook_app(
    producer: Producer,
) -> Any:
    """
    FastAPIアプリケーションを生成してWebhookエンドポイントを設定する。

    GitLab WebhookのPOSTリクエストを受け取り、Producerにタスクエンキューを委譲する。
    エンドポイント: POST /webhook

    Args:
        producer: Producerインスタンス

    Returns:
        FastAPIアプリケーションインスタンス
    """
    import fastapi
    import fastapi.requests

    from producer.gitlab_event_handler import GitLabEventHandler

    app = fastapi.FastAPI(title="AutomataCodex Producer Webhook")
    gitlab_config = producer.config_manager.get_gitlab_config()
    event_handler = GitLabEventHandler(gitlab_config=gitlab_config)

    @app.post("/webhook")
    async def receive_webhook(request: fastapi.requests.Request) -> dict:
        """
        GitLab Webhookエンドポイント

        X-Gitlab-Eventヘッダーでイベント種別を判定し、
        処理対象タスクをRabbitMQにエンキューする。

        Args:
            request: FastAPIリクエストオブジェクト

        Returns:
            処理結果のJSONレスポンス
        """
        event_type = request.headers.get("X-Gitlab-Event", "")
        try:
            payload = await request.json()
        except Exception as exc:
            logger.warning("Webhookペイロードのパースに失敗しました: %s", exc)
            raise fastapi.HTTPException(
                status_code=400, detail="Invalid JSON payload"
            ) from exc

        task = event_handler.handle_event(event_type=event_type, payload=payload)
        if task is None:
            logger.debug("処理対象外のWebhookイベント: event_type=%s", event_type)
            return {"status": "skipped", "reason": "not a processing target"}

        success = await producer.enqueue_task_from_webhook(task)
        if success:
            return {"status": "enqueued", "task_uuid": task.task_uuid}
        else:
            return {"status": "skipped", "reason": "duplicate or error"}

    @app.get("/health")
    async def health_check() -> dict:
        """ヘルスチェックエンドポイント"""
        return {"status": "ok"}

    return app


def is_webhook_mode() -> bool:
    """
    Webhookモードが有効かどうかを環境変数から判定する。

    PRODUCER_WEBHOOK_MODE 環境変数が "true"（大文字小文字を問わない）に
    設定されている場合はWebhookモード、それ以外はPollingモードとする。

    Returns:
        Webhookモードの場合True、Pollingモードの場合False
    """
    return os.environ.get(_ENV_WEBHOOK_MODE, "").lower() == "true"
