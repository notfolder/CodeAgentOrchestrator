"""
Producer エントリーポイント

python -m producer で呼び出されるエントリーポイント。
1回実行して終了する設計とし、docker-compose の restart: always と組み合わせて
定期的にタスク検出を繰り返す。

動作概要:
1. GitLab の全プロジェクトを横断し、PATユーザーにアサインされかつ
   bot ラベルが付与された Issue/MR を検出する。
2. 検出したタスクを RabbitMQ にエンキューし、処理中ラベルを付与する。
3. スキャン完了後、config.yaml の producer.interval_seconds 秒待機してから終了する。
4. docker-compose の restart: always によって再起動され、繰り返しスキャンが実行される。

AUTOMATA_CODEX_SPEC.md § 2.2.1（Producer: タスク検出＆キューイング）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.3 Producer（タスク検出コンポーネント）に準拠する。
"""

from __future__ import annotations

import asyncio
import logging
import sys

from shared.config.config_manager import ConfigManager
from shared.database.connection import create_pool, close_pool
from shared.database.repositories.task_repository import TaskRepository
from shared.gitlab_client.gitlab_client import GitlabClient
from shared.messaging.rabbitmq_client import RabbitMQClient

from producer.producer import Producer


def _setup_logging() -> None:
    """標準出力にラインバッファリングしたログ設定を行う。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
    # 標準出力をラインバッファリングに設定する
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)


async def main() -> None:
    """
    Producerのメイン処理を1回実行して終了する。

    依存関係の初期化（ConfigManager, GitlabClient, RabbitMQClient, asyncpg.Pool,
    TaskRepository）を行い、全プロジェクト横断でタスク検出・エンキューを実行する。
    """
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Producer を起動します")

    # 設定の初期化（config.yaml が存在しない場合は環境変数のみで動作する）
    config_manager = ConfigManager("/app/config.yaml")

    # GitLab クライアントの初期化（GITLAB_URL, GITLAB_PAT 環境変数を使用）
    gitlab_client = GitlabClient()

    # RabbitMQ クライアントの初期化
    rabbitmq_config = config_manager.get_rabbitmq_config()
    rabbitmq_client = RabbitMQClient(rabbitmq_config)

    # データベース接続プールの初期化
    database_config = config_manager.get_database_config()
    pool = await create_pool(database_config.url)
    task_repository = TaskRepository(pool)

    # Producer の初期化
    # project_id=None を指定することで、PATユーザーにアサインされた
    # 全プロジェクトを横断してIssue/MRを検出する。
    producer = Producer(
        gitlab_client=gitlab_client,
        rabbitmq_client=rabbitmq_client,
        config_manager=config_manager,
        task_repository=task_repository,
        project_id=None,
    )

    # 次回スキャンまでの待機間隔を取得する
    producer_config = config_manager.get_producer_config()
    interval_seconds = producer_config.interval_seconds

    try:
        await rabbitmq_client.connect()
        logger.info("RabbitMQ に接続しました。タスク検出を開始します")

        # 1回だけタスク検出・エンキューを実行する
        # docker-compose の restart: always で繰り返し実行される
        count = await producer.produce_tasks()
        logger.info("タスク投入完了: enqueued=%d", count)

        # 次回スキャンまで待機してから終了する
        # （即時終了するとdocker-composeが高頻度で再起動しGitLab APIのレート制限に達する）
        logger.info("次回スキャンまで %d 秒待機します", interval_seconds)
        await asyncio.sleep(interval_seconds)

    except Exception as exc:
        logger.error("Producer の実行中にエラーが発生しました: %s", exc)
        raise

    finally:
        # 接続リソースを確実に解放する
        await rabbitmq_client.close()
        await close_pool()
        logger.info("Producer を終了します")


if __name__ == "__main__":
    asyncio.run(main())
