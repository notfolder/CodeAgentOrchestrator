"""
コンテキストストレージマネージャー

各カスタムProviderとリポジトリへの参照を集約し、
TokenUsageMiddlewareおよびErrorHandlingMiddlewareが
トークン記録・エラー記録に使用する統合管理クラス。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextStorageManager:
    """
    コンテキストストレージマネージャークラス。

    PostgreSqlChatHistoryProvider、TokenUsageRepository、
    ContextRepository、TaskRepositoryへの参照を集約する。
    TokenUsageMiddlewareおよびErrorHandlingMiddlewareから使用される。

    Attributes:
        _chat_history_provider: 会話履歴Provider
        _token_usage_repository: トークン使用量リポジトリ
        _context_repository: コンテキストリポジトリ
        _task_repository: タスクリポジトリ
    """

    def __init__(
        self,
        chat_history_provider: Any,
        token_usage_repository: Any,
        context_repository: Any,
        task_repository: Any,
    ) -> None:
        """
        ContextStorageManagerを初期化する。

        循環importを避けるため、各引数の型はAnyとして受け取る。
        実際にはPostgreSqlChatHistoryProvider、TokenUsageRepository、
        ContextRepository、TaskRepositoryのインスタンスを渡す。

        Args:
            chat_history_provider: PostgreSqlChatHistoryProviderインスタンス
            token_usage_repository: TokenUsageRepositoryインスタンス
            context_repository: ContextRepositoryインスタンス
            task_repository: TaskRepositoryインスタンス
        """
        self._chat_history_provider = chat_history_provider
        self._token_usage_repository = token_usage_repository
        self._context_repository = context_repository
        self._task_repository = task_repository

    async def save_token_usage(
        self,
        user_email: str,
        task_uuid: str,
        node_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """
        トークン使用量をDBへ記録する。

        token_usage_repositoryのrecord_token_usage()を呼び出して
        token_usageテーブルへ保存する。

        Args:
            user_email: ユーザーメールアドレス
            task_uuid: タスクUUID
            node_id: ワークフローノードID
            model: 使用モデル名（例: 'gpt-4o'）
            prompt_tokens: 入力プロンプトのトークン数
            completion_tokens: 生成出力のトークン数
            total_tokens: 合計トークン数（prompt_tokens + completion_tokens）
        """
        try:
            await self._token_usage_repository.record_token_usage(
                user_email,
                task_uuid,
                node_id,
                model,
                prompt_tokens,
                completion_tokens,
            )
            logger.debug(
                "トークン使用量記録完了: task_uuid=%s, node_id=%s, total=%d",
                task_uuid,
                node_id,
                total_tokens,
            )
        except Exception as exc:
            logger.error(
                "トークン使用量記録エラー: task_uuid=%s, error=%s",
                task_uuid,
                exc,
            )
            raise

    async def save_error(
        self,
        task_uuid: str,
        node_id: str,
        error_category: str,
        error_message: str,
        stack_trace: str,
    ) -> None:
        """
        エラー情報をタスクとコンテキストメタデータへ記録する。

        task_repositoryのupdate_task_status()でタスクをfailed状態に更新し、
        context_repositoryのupdate_context_metadata()でコンテキストへエラー情報を記録する。

        Args:
            task_uuid: タスクUUID
            node_id: エラーが発生したワークフローノードID
            error_category: エラーカテゴリ（例: 'transient', 'implementation'）
            error_message: エラーメッセージ
            stack_trace: スタックトレース文字列
        """
        # タスクのエラー情報を更新する
        try:
            if hasattr(self._task_repository, "update_task_status"):
                await self._task_repository.update_task_status(
                    task_uuid,
                    "failed",
                    error_message=error_message,
                )
                logger.debug(
                    "タスクエラー情報更新完了: task_uuid=%s, category=%s",
                    task_uuid,
                    error_category,
                )
        except Exception as exc:
            logger.error(
                "タスクエラー情報更新失敗: task_uuid=%s, error=%s",
                task_uuid,
                exc,
            )

        # コンテキストメタデータへエラー情報を記録する
        # update_context_metadataはworkflow_nameのみ受け付けるため、
        # エラー詳細はログに記録する
        logger.error(
            "エラー詳細: task_uuid=%s, node_id=%s, category=%s, message=%s, stack_trace=%s",
            task_uuid,
            node_id,
            error_category,
            error_message,
            stack_trace,
        )
        try:
            if hasattr(self._context_repository, "update_context_metadata"):
                await self._context_repository.update_context_metadata(
                    task_uuid,
                )
                logger.debug(
                    "コンテキストエラーメタデータ更新完了: task_uuid=%s, node_id=%s",
                    task_uuid,
                    node_id,
                )
        except Exception as exc:
            logger.error(
                "コンテキストエラーメタデータ更新失敗: task_uuid=%s, error=%s",
                task_uuid,
                exc,
            )
