"""
Consumer エントリーポイント

python -m consumer で呼び出されるエントリーポイント。
依存オブジェクトを組み立てて Consumer.run_consumer_continuous() を実行する。

動作概要:
1. DB接続プール・RabbitMQクライアント・GitLabクライアントを初期化する
2. Provider・Factory 群を初期化して Consumer インスタンスを組み立てる
3. Consumer.run_consumer_continuous() でタスク受信ループを開始する
4. シャットダウン時は接続を解放して終了する

AUTOMATA_CODEX_SPEC.md § 2.2.2（Consumer: タスク処理）に準拠する。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import docker

from shared.config.config_manager import ConfigManager
from shared.database.connection import create_pool, close_pool
from consumer.execution.execution_environment_manager import ExecutionEnvironmentManager
from shared.database.repositories.task_repository import TaskRepository
from shared.database.repositories.token_usage_repository import TokenUsageRepository
from shared.database.repositories.workflow_definition_repository import (
    WorkflowDefinitionRepository,
)
from shared.database.repositories.workflow_execution_state_repository import (
    WorkflowExecutionStateRepository,
)
from shared.gitlab_client.gitlab_client import GitlabClient
from shared.messaging.rabbitmq_client import RabbitMQClient

from consumer.tools.issue_to_mr_converter import (
    IssueToMRConverter,
    IssueToMRConfig as IssueToMRConverterConfig,
)
from consumer.consumer import Consumer
from consumer.definitions.definition_loader import DefinitionLoader
from consumer.factories.agent_factory import AgentFactory
from consumer.factories.executor_factory import ExecutorFactory
from consumer.factories.task_strategy_factory import TaskStrategyFactory
from consumer.factories.workflow_factory import WorkflowFactory
from consumer.handlers.task_handler import TaskHandler
from consumer.providers.chat_history_provider import PostgreSqlChatHistoryProvider
from consumer.providers.planning_context_provider import PlanningContextProvider
from consumer.providers.tool_result_context_provider import ToolResultContextProvider
from consumer.task_processor import TaskProcessor
from consumer.user_config_client import UserConfigClient


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
    Consumer のメイン処理を起動する。

    依存関係を初期化して Consumer インスタンスを組み立て、
    タスク受信ループを開始する。
    """
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Consumer を起動します")

    # 設定の初期化
    config_manager = ConfigManager("/app/config.yaml")

    # RabbitMQ クライアントの初期化
    rabbitmq_config = config_manager.get_rabbitmq_config()
    rabbitmq_client = RabbitMQClient(rabbitmq_config)

    # データベース接続プールの初期化（shared.database.connection 経由でシングルトン管理）
    database_config = config_manager.get_database_config()
    pool = await create_pool(database_config.url)

    # GitLab クライアントの初期化
    gitlab_client = GitlabClient()

    # User Config API クライアントの初期化
    user_config_api = config_manager.get_user_config_api_config()
    user_config_client = UserConfigClient(
        base_url=user_config_api.url,
        api_key=user_config_api.api_key,
        timeout=user_config_api.timeout,
        service_username=user_config_api.service_username,
        service_password=user_config_api.service_password,
    )

    # リポジトリの初期化
    task_repository = TaskRepository(pool)
    token_usage_repository = TokenUsageRepository(pool)
    workflow_def_repo = WorkflowDefinitionRepository(pool)
    workflow_exec_state_repo = WorkflowExecutionStateRepository(pool)

    # 初期ワークフロー定義を投入する（未登録の場合のみ。冪等）
    from shared.database.seeds.seed_workflow_definitions import (
        seed_workflow_definitions,
    )

    await seed_workflow_definitions(workflow_def_repo)

    # Provider の初期化（DBプールを直接渡す）
    chat_history_provider = PostgreSqlChatHistoryProvider(db_pool=pool)
    planning_context_provider = PlanningContextProvider(db_pool=pool)
    tool_result_context_provider = ToolResultContextProvider(db_pool=pool)

    # MCPサーバー設定の取得（AgentFactory はサーバー名→設定の辞書を要求する）
    mcp_server_configs = {c.name: c for c in config_manager.get_mcp_server_configs()}

    # Docker実行環境マネージャーの初期化
    exec_env_config = config_manager.get_execution_environment_config()
    docker_client = docker.from_env()
    # 環境名→Dockerイメージのマッピング（設定ファイルの docker.image をデフォルト環境として登録）
    environment_name_mapping: dict[str, str] = {
        "default": exec_env_config.docker.image,
    }
    env_manager = ExecutionEnvironmentManager(
        docker_client=docker_client,
        environment_name_mapping=environment_name_mapping,
        db_pool=pool,
    )

    # Factory の初期化
    executor_factory = ExecutorFactory(
        user_config_client=user_config_client,
        gitlab_client=gitlab_client,
        env_manager=env_manager,
        config_manager=config_manager,
    )
    agent_factory = AgentFactory(
        mcp_server_configs=mcp_server_configs,
        chat_history_provider=chat_history_provider,
        planning_context_provider=planning_context_provider,
        tool_result_context_provider=tool_result_context_provider,
        user_config_client=user_config_client,
        db_connection=pool,
        gitlab_client=gitlab_client,
        openai_base_url=config_manager.get_openai_config().base_url,
    )
    definition_loader = DefinitionLoader(
        workflow_definition_repo=workflow_def_repo,
    )
    workflow_factory = WorkflowFactory(
        definition_loader=definition_loader,
        executor_factory=executor_factory,
        agent_factory=agent_factory,
        user_config_client=user_config_client,
        gitlab_client=gitlab_client,
        config_manager=config_manager,
        workflow_exec_state_repo=workflow_exec_state_repo,
        workflow_def_repo=workflow_def_repo,
    )
    task_strategy_factory = TaskStrategyFactory(
        gitlab_client=gitlab_client,
        config_manager=config_manager,
    )

    # IssueToMRConverter の設定を組み立てる
    issue_to_mr_app_config = config_manager.get_issue_to_mr_config()
    gitlab_config = config_manager.get_gitlab_config()

    # username から ChatClient を動的生成するファクトリ関数
    async def _chat_client_factory(username: str) -> Any:
        """UserConfigClient から設定を取得し、AgentFactory で ChatClient を生成する。"""
        user_config = await user_config_client.get_user_config(username)
        return agent_factory.create_chat_client(user_config)

    issue_to_mr_converter = IssueToMRConverter(
        gitlab_client=gitlab_client,
        chat_client_factory=_chat_client_factory,
        token_usage_repository=token_usage_repository,
        config=IssueToMRConverterConfig(
            branch_prefix=issue_to_mr_app_config.branch_prefix,
            target_branch=issue_to_mr_app_config.target_branch,
            mr_title_template=issue_to_mr_app_config.mr_title_template,
            bot_label=gitlab_config.bot_label,
            done_label=gitlab_config.done_label,
            processing_label=gitlab_config.processing_label,
        ),
    )

    # TaskHandler の初期化
    task_handler = TaskHandler(
        task_strategy_factory=task_strategy_factory,
        workflow_factory=workflow_factory,
        definition_loader=definition_loader,
        task_repository=task_repository,
        issue_to_mr_converter=issue_to_mr_converter,
        gitlab_client=gitlab_client,
    )

    # TaskProcessor の初期化
    task_processor = TaskProcessor(
        task_handler=task_handler,
        workflow_factory=workflow_factory,
        workflow_exec_state_repo=workflow_exec_state_repo,
    )

    # Consumer の初期化
    consumer = Consumer(
        rabbitmq_client=rabbitmq_client,
        task_processor=task_processor,
    )

    try:
        await rabbitmq_client.connect()
        logger.info("RabbitMQ に接続しました。タスク受信ループを開始します")
        await consumer.run_consumer_continuous()
    except Exception as exc:
        logger.error("Consumer の実行中にエラーが発生しました: %s", exc)
        raise
    finally:
        # 接続リソースを確実に解放する
        await rabbitmq_client.close()
        # close_pool() がグローバルプールを閉じるため、個別の pool.close() は不要
        await close_pool()
        logger.info("Consumer を終了します")


if __name__ == "__main__":
    asyncio.run(main())
