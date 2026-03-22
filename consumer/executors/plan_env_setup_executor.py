"""
PlanEnvSetupExecutor モジュール

計画（planning）フェーズで使用する Docker 実行環境を準備し、
リポジトリをクローンする Executor を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 3.4（PlanEnvSetupExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_framework import WorkflowContext, handler

from consumer.executors.base_executor import BaseExecutor

if TYPE_CHECKING:
    from consumer.execution.execution_environment_manager import (
        ExecutionEnvironmentManager,
    )

logger = logging.getLogger(__name__)

# plan環境のデフォルト環境名
_DEFAULT_PLAN_ENVIRONMENT_NAME = "python"


class PlanEnvSetupExecutor(BaseExecutor):
    """
    計画環境セットアップ Executor

    計画フェーズで使用する Docker 環境を作成し、リポジトリをクローンする。
    作成した環境 ID をワークフローコンテキストに保存する。

    Attributes:
        env_manager: 実行環境マネージャー
        config: 環境設定辞書（plan_environment_name を含む）
    """

    def __init__(
        self,
        env_manager: ExecutionEnvironmentManager,
        config: dict[str, Any],
    ) -> None:
        """
        PlanEnvSetupExecutor を初期化する。

        Args:
            env_manager: 実行環境マネージャー
            config: 環境設定辞書。以下のキーを含む:
                - plan_environment_name: 使用する環境名（省略時は "python"）
        """
        self.env_manager = env_manager
        self.config = config
        super().__init__(id=self.__class__.__name__)

    @handler(input=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext) -> None:
        """
        計画フェーズの Docker 環境を準備してリポジトリをクローンする。

        処理フロー:
        1. config から plan_environment_name を取得する（デフォルト: "python"）
        2. コンテキストから task_mr_iid を取得する
        3. plan 環境を作成する
        4. plan_environment_id をコンテキストに保存する
        5. コンテキストから repo_url と original_branch を取得する
        6. plan 環境にリポジトリをクローンする

        Args:
            msg: 受け取るメッセージ（未使用）
            ctx: ワークフローコンテキスト
        """
        # 使用する環境名を設定から取得する（デフォルト: "python"）
        plan_environment_name: str = self.config.get(
            "plan_environment_name", _DEFAULT_PLAN_ENVIRONMENT_NAME
        )

        # MR IIDをコンテキストから取得する
        mr_iid: int = self.get_context_value(ctx, "task_mr_iid")

        logger.info(
            "計画環境を準備します: environment_name=%s, mr_iid=%s",
            plan_environment_name,
            mr_iid,
        )

        # plan環境を作成する
        plan_env_id: str = self.env_manager.prepare_plan_environment(
            environment_name=plan_environment_name,
            mr_iid=mr_iid,
        )

        # plan環境IDをコンテキストに保存する
        self.set_context_value(ctx, "plan_environment_id", plan_env_id)

        logger.info("計画環境を作成しました: env_id=%s", plan_env_id)

        # リポジトリURLとブランチ名をコンテキストから取得する
        repo_url: str = self.get_context_value(ctx, "repo_url")
        original_branch: str = self.get_context_value(ctx, "original_branch")

        logger.info(
            "リポジトリをクローンします: node_id=plan, repo_url=%s, branch=%s",
            repo_url,
            original_branch,
        )

        # plan環境にリポジトリをクローンする
        self.env_manager.clone_repository(
            node_id="plan",
            repo_url=repo_url,
            branch=original_branch,
        )

        logger.info(
            "計画環境のセットアップが完了しました: env_id=%s, branch=%s",
            plan_env_id,
            original_branch,
        )
        # 後続ノードへ msg を送信する
        await ctx.send_message(msg)
