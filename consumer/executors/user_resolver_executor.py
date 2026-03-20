"""
UserResolverExecutor モジュール

GitLab の MR 情報からユーザーの username を取得し、
ユーザー設定（UserConfig）をワークフローコンテキストに保存する Executor を定義する。

CLASS_IMPLEMENTATION_SPEC.md § 3.2（UserResolverExecutor）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_framework import WorkflowContext, handler

from consumer.executors.base_executor import BaseExecutor

if TYPE_CHECKING:
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)


class UserResolverExecutor(BaseExecutor):
    """
    ユーザー情報解決 Executor

    タスク識別子から project_id と mr_iid を取得し、
    GitLab MR の author username を元にユーザー設定を取得して
    ワークフローコンテキストに保存する。
    MRのauthorがbotの場合は、reviewersの1人目のusernameを使用する。

    Attributes:
        gitlab_client: GitLabAPI クライアント
        user_config_client: ユーザー設定取得クライアント（未実装のため Any 型）
        bot_name: botアカウント名（authorがbotか判定するために使用）
    """

    def __init__(
        self,
        gitlab_client: GitlabClient,
        user_config_client: Any,
        bot_name: str = "",
    ) -> None:
        """
        UserResolverExecutor を初期化する。

        Args:
            gitlab_client: GitLabAPI クライアント
            user_config_client: ユーザー設定取得クライアント
            bot_name: botアカウント名
        """
        self.gitlab_client = gitlab_client
        self.user_config_client = user_config_client
        self.bot_name = bot_name
        super().__init__(id=self.__class__.__name__)

    @handler(input=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext) -> None:
        """
        ユーザー情報を解決してコンテキストに保存する。

        処理フロー:
        1. TaskContextにキャッシュ済みのusername/user_configがあればそれを使用する
        2. なければGitLab から MR 詳細を取得し author の username を取得する
        3. user_config_client からユーザー設定を取得する
        4. コンテキストに username, user_config, タスク情報を保存する

        Args:
            msg: ワークフロー初期メッセージ（TaskContext）
            ctx: ワークフローコンテキスト
        """
        # 初期メッセージ（TaskContext）からプロジェクトIDとMR IIDを取得する
        project_id: int = getattr(msg, "project_id", 0)
        mr_iid: int = getattr(msg, "mr_iid", 0) or 0
        issue_iid: int | None = getattr(msg, "issue_iid", None)

        # TaskContextにキャッシュ済みのusernameとuser_configがあればスキップする
        cached_username: str | None = getattr(msg, "username", None)
        cached_user_config: Any = getattr(msg, "cached_user_config", None)

        if cached_username and cached_user_config:
            logger.info(
                "キャッシュ済みのユーザー情報を使用します: username=%s, project_id=%s",
                cached_username,
                project_id,
            )
            self.set_context_value(ctx, "username", cached_username)
            self.set_context_value(ctx, "user_config", cached_user_config)
            self.set_context_value(ctx, "task_mr_iid", mr_iid)
            self.set_context_value(ctx, "task_issue_iid", issue_iid)
            self.set_context_value(ctx, "project_id", project_id)
            self.set_context_value(
                ctx,
                "task_identifier",
                {"project_id": project_id, "mr_iid": mr_iid},
            )
            logger.info(
                "ユーザー情報をコンテキストに保存しました: username=%s", cached_username
            )
            return

        logger.info(
            "ユーザー情報を解決します: project_id=%s, mr_iid=%s", project_id, mr_iid
        )

        # GitLabからMRの詳細を直接取得してauthorのusernameを抽出する
        target_mr = self.gitlab_client.get_merge_request(
            project_id=project_id,
            mr_iid=mr_iid,
        )

        # MR authorのusernameを取得する
        author = target_mr.author
        if author is None or author.username is None:
            logger.warning(
                "MR authorのusernameが取得できませんでした: mr_iid=%s", mr_iid
            )
            username: str = ""
        else:
            username = author.username

        # MRのauthorがbotの場合、reviewersの1人目のusernameを使用する
        if self.bot_name and username.lower() == self.bot_name.lower():
            if target_mr.reviewers:
                first_reviewer = target_mr.reviewers[0]
                if first_reviewer.username:
                    logger.info(
                        "MR authorがbot(%s)のためレビュアーのusernameを使用します: %s",
                        self.bot_name,
                        first_reviewer.username,
                    )
                    username = first_reviewer.username
                else:
                    logger.warning(
                        "MR authorがbotですがレビュアーのusernameが取得できませんでした: mr_iid=%s",
                        mr_iid,
                    )
            else:
                logger.warning(
                    "MR authorがbotですがレビュアーが未設定です: mr_iid=%s",
                    mr_iid,
                )

        logger.info("MRのタスク対象usernameを取得しました: username=%s", username)

        # ユーザー設定を取得する
        user_config: Any = await self.user_config_client.get_user_config(username)

        # コンテキストにユーザー情報を保存する
        self.set_context_value(ctx, "username", username)
        self.set_context_value(ctx, "user_config", user_config)
        # 下流ノードが参照するタスク情報をコンテキストに保存する
        self.set_context_value(ctx, "task_mr_iid", mr_iid)
        self.set_context_value(ctx, "task_issue_iid", issue_iid)
        self.set_context_value(ctx, "project_id", project_id)
        self.set_context_value(
            ctx, "task_identifier", {"project_id": project_id, "mr_iid": mr_iid}
        )

        logger.info("ユーザー情報をコンテキストに保存しました: username=%s", username)
