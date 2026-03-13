"""
ExecEnvSetupExecutor モジュール

実行（execution）フェーズで使用する複数の Docker 実行環境を準備し、
env_count >= 2 の場合はサブブランチを作成する Executor を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 3.5（ExecEnvSetupExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from consumer.executors.base_executor import BaseExecutor

if TYPE_CHECKING:
    from consumer.agents.configurable_agent import WorkflowContext
    from consumer.execution.execution_environment_manager import (
        ExecutionEnvironmentManager,
    )
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)

# exec_env_setup_ プレフィックス（サフィックス生成時に除去する）
_NODE_ID_PREFIX = "exec_env_setup_"


class ExecEnvSetupExecutor(BaseExecutor):
    """
    実行環境セットアップ Executor

    graph_definition から自ノードの env_count を取得し、
    指定数の Docker 環境を作成する。
    env_count >= 2 の場合はブランチを分岐させてそれぞれのブランチに
    対応する環境を割り当てる。

    Attributes:
        node_id: このノードのグラフ定義上の ID
        env_manager: 実行環境マネージャー
        gitlab_client: GitLabAPI クライアント
        graph_definition: グラフ全体の定義辞書（nodes リストを含む）
    """

    def __init__(
        self,
        node_id: str,
        env_manager: ExecutionEnvironmentManager,
        gitlab_client: GitlabClient,
        graph_definition: dict[str, Any],
    ) -> None:
        """
        ExecEnvSetupExecutor を初期化する。

        Args:
            node_id: このノードのグラフ定義上の ID
            env_manager: 実行環境マネージャー
            gitlab_client: GitLabAPI クライアント
            graph_definition: グラフ全体の定義辞書（nodes リストを含む）
        """
        self.node_id = node_id
        self.env_manager = env_manager
        self.gitlab_client = gitlab_client
        self.graph_definition = graph_definition

    def _get_node_config(self) -> dict[str, Any]:
        """
        graph_definition から自ノードの設定を取得する。

        Returns:
            自ノードの設定辞書。見つからない場合は空辞書。
        """
        nodes: list[dict[str, Any]] = self.graph_definition.get("nodes", [])
        for node in nodes:
            if node.get("id") == self.node_id:
                return node.get("config", {})
        logger.warning(
            "graph_definitionに自ノードの設定が見つかりませんでした: node_id=%s",
            self.node_id,
        )
        return {}

    def _build_branch_suffix(self) -> str:
        """
        自ノード ID からブランチ名サフィックスを生成する。

        ノード ID の "exec_env_setup_" プレフィックスを除去し、
        アンダースコアをハイフンに変換する。

        Returns:
            ブランチ名サフィックス文字列
        """
        suffix = self.node_id
        if suffix.startswith(_NODE_ID_PREFIX):
            suffix = suffix[len(_NODE_ID_PREFIX):]
        return suffix.replace("_", "-")

    async def handle(self, msg: Any, ctx: WorkflowContext) -> None:
        """
        実行フェーズの Docker 環境を準備し、必要に応じてサブブランチを作成する。

        処理フロー:
        1. コンテキストから task_mr_iid を取得する
        2. graph_definition の自ノード設定から env_count を取得する
        3. コンテキストから selected_environment を取得する
        4. 指定数の実行環境を作成する
        5. コンテキストから original_branch を取得する
        6. env_count == 1: サブブランチを作成しない
           env_count >= 2: 各環境に対応するサブブランチを作成する
        7. branch_envs をコンテキストに保存する

        Args:
            msg: 受け取るメッセージ（未使用）
            ctx: ワークフローコンテキスト
        """
        # MR IIDをコンテキストから取得する
        mr_iid: int = await self.get_context_value(ctx, "task_mr_iid")

        # graph_definitionから自ノードのenv_countを取得する
        node_config = self._get_node_config()
        env_count: int = node_config.get("env_count", 1)

        # 使用する環境名をコンテキストから取得する
        selected_environment: str = await self.get_context_value(
            ctx, "selected_environment"
        )

        logger.info(
            "実行環境を準備します: node_id=%s, env_count=%d, environment=%s, mr_iid=%s",
            self.node_id,
            env_count,
            selected_environment,
            mr_iid,
        )

        # env_count個の実行環境を作成する
        node_ids_for_envs = [
            f"{self.node_id}-{n}" for n in range(1, env_count + 1)
        ]
        env_ids: list[str] = self.env_manager.prepare_environments(
            count=env_count,
            environment_name=selected_environment,
            mr_iid=mr_iid,
            node_ids=node_ids_for_envs,
        )

        logger.info(
            "実行環境を作成しました: env_ids=%s", env_ids
        )

        # original_branchとproject_idをコンテキストから取得する
        original_branch: str = await self.get_context_value(ctx, "original_branch")
        project_id: int = await self.get_context_value(ctx, "project_id")

        # branch_envs辞書を構築する（キーは環境番号N: 1〜env_count）
        branch_envs: dict[int, dict[str, Any]] = {}

        if env_count == 1:
            # 環境が1つの場合はブランチを分岐させない
            branch_envs[1] = {
                "env_id": env_ids[0],
                "branch": original_branch,
            }
            logger.info(
                "env_count=1のためサブブランチを作成しません: branch=%s",
                original_branch,
            )
        else:
            # 環境が複数の場合は各環境にサブブランチを作成する
            suffix = self._build_branch_suffix()
            # 作成済みブランチを記録してロールバック可能にする
            created_branches: list[str] = []
            try:
                for n in range(1, env_count + 1):
                    branch_name = f"{original_branch}-{suffix}-{n}"
                    logger.info(
                        "サブブランチを作成します: branch_name=%s, ref=%s",
                        branch_name,
                        original_branch,
                    )
                    self.gitlab_client.create_branch(
                        project_id=project_id,
                        branch_name=branch_name,
                        ref=original_branch,
                    )
                    created_branches.append(branch_name)
                    logger.info(
                        "サブブランチを作成しました: branch_name=%s", branch_name
                    )
                    branch_envs[n] = {
                        "env_id": env_ids[n - 1],
                        "branch": branch_name,
                    }
            except Exception:
                # サブブランチ作成失敗時は作成済みのブランチを削除して
                # リソースが残留しないようにロールバックを試みる
                logger.exception(
                    "サブブランチの作成に失敗しました。作成済みブランチのロールバックを試みます: "
                    "created_branches=%s",
                    created_branches,
                )
                for branch_to_remove in created_branches:
                    try:
                        self.gitlab_client.delete_branch(
                            project_id=project_id,
                            branch_name=branch_to_remove,
                        )
                        logger.info(
                            "ロールバック: サブブランチを削除しました: branch=%s",
                            branch_to_remove,
                        )
                    except Exception:
                        logger.exception(
                            "ロールバック: サブブランチの削除に失敗しました: branch=%s",
                            branch_to_remove,
                        )
                raise

        # branch_envsをコンテキストに保存する
        await self.set_context_value(ctx, "branch_envs", branch_envs)

        logger.info(
            "実行環境のセットアップが完了しました: node_id=%s, branch_envs=%s",
            self.node_id,
            branch_envs,
        )
