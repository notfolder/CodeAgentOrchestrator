"""
BranchMergeExecutor モジュール

選択された実装ブランチをオリジナルブランチにマージし、
非選択ブランチを削除する Executor を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 3.6（BranchMergeExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_framework import WorkflowContext, handler

from consumer.executors.base_executor import BaseExecutor

if TYPE_CHECKING:
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)


class BranchMergeExecutor(BaseExecutor):
    """
    ブランチマージ Executor

    コードレビューで選択された実装ブランチを MR 経由でオリジナルブランチに
    マージし、非選択ブランチを削除する。

    Attributes:
        gitlab_client: GitLabAPI クライアント
    """

    def __init__(self, gitlab_client: GitlabClient) -> None:
        """
        BranchMergeExecutor を初期化する。

        Args:
            gitlab_client: GitLabAPI クライアント
        """
        self.gitlab_client = gitlab_client
        super().__init__(id=self.__class__.__name__)

    @handler(input=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext) -> None:
        """
        選択された実装ブランチをオリジナルブランチにマージする。

        処理フロー:
        1. コンテキストから selected_implementation を取得する
        2. コンテキストから branch_envs を取得する
        3. selected_implementation に対応するブランチを特定する
        4. コンテキストから original_branch と project_id を取得する
        5. 選択ブランチ → original_branch の MR を作成してマージする
        6. 非選択ブランチを削除する
        7. merged_branch をコンテキストに保存する

        Args:
            msg: 受け取るメッセージ（未使用）
            ctx: ワークフローコンテキスト
        """
        # 選択された実装番号をコンテキストから取得する
        selected_implementation: int | None = self.get_context_value(
            ctx, "selected_implementation"
        )

        # selected_implementationが存在しない場合はノーオペレーション（バグ修正・テスト作成・ドキュメントタスク）
        if selected_implementation is None:
            logger.info(
                "selected_implementationが設定されていないためブランチマージをスキップします。"
                "（バグ修正・テスト作成・ドキュメント生成タスクの場合）"
            )
            # マージ不要でも後続ノード（plan_reflection）へ伝播する
            await ctx.send_message(msg)
            return

        # branch_envsをコンテキストから取得する
        branch_envs: dict[int, dict[str, Any]] = self.get_context_value(
            ctx, "branch_envs"
        )

        # 選択された実装に対応するブランチを取得する
        selected_entry = branch_envs.get(selected_implementation)
        if selected_entry is None:
            logger.error(
                "selected_implementationに対応するbranch_envsエントリが見つかりません: "
                "selected_implementation=%s",
                selected_implementation,
            )
            raise ValueError(
                f"selected_implementationに対応するbranch_envsエントリが見つかりません: "
                f"selected_implementation={selected_implementation}"
            )
        selected_branch: str = selected_entry["branch"]

        # original_branchとproject_idをコンテキストから取得する
        original_branch: str = self.get_context_value(ctx, "original_branch")
        project_id: int = self.get_context_value(ctx, "project_id")

        logger.info(
            "選択ブランチをオリジナルブランチにマージします: "
            "selected_branch=%s → original_branch=%s, project_id=%s",
            selected_branch,
            original_branch,
            project_id,
        )

        # 選択ブランチが既にoriginal_branchと同じ場合はマージをスキップする
        if selected_branch == original_branch:
            logger.info(
                "選択ブランチとオリジナルブランチが同一のためマージをスキップします: "
                "branch=%s",
                selected_branch,
            )
        else:
            # MRを作成せず選択ブランチ → original_branchへ直接マージする
            self.gitlab_client.merge_branch(
                project_id=project_id,
                source_branch=selected_branch,
                target_branch=original_branch,
            )

            logger.info(
                "ブランチを直接マージしました: %s → %s",
                selected_branch,
                original_branch,
            )

        # 非選択ブランチを削除する
        non_selected_branches = [
            entry["branch"]
            for key, entry in branch_envs.items()
            if key != selected_implementation and entry["branch"] != original_branch
        ]

        for branch_name in non_selected_branches:
            try:
                # ブランチの存在を確認してから削除する
                if self.gitlab_client.branch_exists(
                    project_id=project_id,
                    branch_name=branch_name,
                ):
                    self.gitlab_client.delete_branch(
                        project_id=project_id,
                        branch_name=branch_name,
                    )
                    logger.info(
                        "非選択ブランチを削除しました: branch_name=%s", branch_name
                    )
                else:
                    logger.warning(
                        "削除対象ブランチが存在しません: branch_name=%s", branch_name
                    )
            except Exception:
                logger.exception(
                    "非選択ブランチの削除に失敗しました: branch_name=%s", branch_name
                )

        # merged_branchをコンテキストに保存する
        self.set_context_value(ctx, "merged_branch", selected_branch)

        logger.info("ブランチマージが完了しました: merged_branch=%s", selected_branch)
        # 後続ノードへ msg を送信する
        await ctx.send_message(msg)
