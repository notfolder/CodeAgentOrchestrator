"""
Consumerモジュール

RabbitMQからタスクをデキューし、TaskProcessorに処理を委譲するメインクラス。
SIGTERMシグナル受信時のグレースフルシャットダウンと、
workflow_execution_statesテーブルへの実行状態保存・再開をサポートする。

AUTOMATA_CODEX_SPEC.md § 2.2.2（Consumer: タスク処理）に準拠する。
AUTOMATA_CODEX_SPEC.md § 2.3.1（TaskHandler コンポーネント一覧）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13（運用設計）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13.2（スケーリング戦略）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13.3（監視・ログ）に準拠する。
AUTOMATA_CODEX_SPEC.md § 13.4（ワークフロー停止・再開機構）に準拠する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.task_processor import TaskProcessor
    from shared.messaging.rabbitmq_client import RabbitMQClient
    from shared.models.task import Task

logger = logging.getLogger(__name__)


class Consumer:
    """
    Consumerクラス

    RabbitMQからタスクをデキューし、TaskProcessorに処理を委譲する。
    キュー管理のみに集中し、タスク処理の分岐ロジックはTaskHandler/TaskProcessorに分離する。

    SIGTERMシグナル受信時はグレースフルシャットダウンを実行し、
    処理中のタスクが完了するまで待機した後に終了する。

    AUTOMATA_CODEX_SPEC.md § 2.2.2 に準拠する。

    Attributes:
        rabbitmq_client: RabbitMQクライアント
        task_processor: タスク処理クラス
    """

    def __init__(
        self,
        rabbitmq_client: RabbitMQClient,
        task_processor: TaskProcessor,
    ) -> None:
        """
        Consumerを初期化する。

        Args:
            rabbitmq_client: RabbitMQクライアントインスタンス
            task_processor: TaskProcessorインスタンス
        """
        self.rabbitmq_client = rabbitmq_client
        self.task_processor = task_processor
        self._shutdown = False
        self._processing = False

    def _setup_signal_handlers(self) -> None:
        """
        SIGTERMシグナルハンドラーを登録する。

        SIGTERMを受信した際にグレースフルシャットダウンを開始するよう設定する。
        AUTOMATA_CODEX_SPEC.md § 13.4.3（グレースフルシャットダウン）に準拠する。
        """
        def _handle_sigterm(signum: int, frame: Any) -> None:
            logger.info(
                "SIGTERMを受信しました。グレースフルシャットダウンを開始します"
            )
            self._shutdown = True

        signal.signal(signal.SIGTERM, _handle_sigterm)
        signal.signal(signal.SIGINT, _handle_sigterm)
        logger.debug("SIGTERMシグナルハンドラーを登録しました")

    async def consume_tasks(self) -> None:
        """
        RabbitMQからタスクをデキューして処理するメインループ。

        RabbitMQClientのsubscribe()を使用してメッセージを受信し、
        各タスクをTaskProcessor.process()に委譲する。

        シャットダウンフラグが立った場合は現在処理中のタスクが完了した後に停止する。

        AUTOMATA_CODEX_SPEC.md § 2.2.2（Consumer: タスクデキューロジック）に準拠する。
        """
        logger.info("タスクの受信を開始します")

        async def _message_callback(message_data: dict[str, Any]) -> bool:
            """
            メッセージコールバック関数。

            RabbitMQから受信したメッセージをTaskに変換してTaskProcessorに委譲する。

            Args:
                message_data: RabbitMQから受信したメッセージ辞書

            Returns:
                処理成功時True、失敗時False
            """
            if self._shutdown:
                logger.info(
                    "シャットダウン中のためメッセージ処理をスキップします"
                )
                return False

            self._processing = True
            try:
                task = self._parse_task(message_data)
                if task is None:
                    logger.warning(
                        "タスクのパースに失敗しました: message=%s", message_data
                    )
                    return False

                result = await self.task_processor.process(task)
                return result
            finally:
                self._processing = False

        await self.rabbitmq_client.subscribe(
            callback=_message_callback,
            auto_ack=False,
        )

    def _parse_task(self, message_data: dict[str, Any]) -> Task | None:
        """
        メッセージ辞書をTaskオブジェクトに変換する。

        Args:
            message_data: RabbitMQから受信したメッセージ辞書

        Returns:
            Taskオブジェクト。パース失敗時はNone。
        """
        try:
            from shared.models.task import Task

            task = Task.model_validate(message_data)
            logger.debug(
                "タスクをパースしました: task_uuid=%s, task_type=%s",
                task.task_uuid,
                task.task_type,
            )
            return task
        except Exception as exc:
            logger.error(
                "タスクのパースに失敗しました: error=%s, data=%s",
                exc,
                message_data,
            )
            return None

    async def run_consumer_continuous(self) -> None:
        """
        Consumerの実行ループを開始する。

        以下の処理を順に実行する:
        1. シグナルハンドラーの設定
        2. 中断タスクの再開（TaskProcessor.resume_suspended_tasks()）
        3. consume_tasks()によるメッセージ受信ループ開始
        4. シャットダウン時のグレースフル停止

        AUTOMATA_CODEX_SPEC.md § 13.4（ワークフロー停止・再開機構）に準拠する。
        """
        self._setup_signal_handlers()

        # 中断タスクの再開
        try:
            resumed_count = await self.task_processor.resume_suspended_tasks()
            if resumed_count > 0:
                logger.info(
                    "中断タスクを再開しました: count=%d", resumed_count
                )
        except Exception as exc:
            logger.warning(
                "中断タスクの再開中にエラーが発生しました: error=%s", exc
            )

        logger.info("Consumerを開始します")
        try:
            await self.consume_tasks()
        except asyncio.CancelledError:
            logger.info("Consumerタスクがキャンセルされました")
        except Exception as exc:
            logger.error(
                "Consumer実行中に予期しないエラーが発生しました: error=%s", exc
            )
            raise

        logger.info("Consumerを停止しました")

    def stop(self) -> None:
        """
        Consumerのシャットダウンフラグを設定する。

        処理中のタスクが完了した後に停止する。
        """
        self._shutdown = True
        logger.info("Consumerの停止が要求されました")
