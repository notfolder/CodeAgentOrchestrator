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
        username: str,
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
            username: GitLabユーザー名
            task_uuid: タスクUUID
            node_id: ワークフローノードID
            model: 使用モデル名（例: 'gpt-4o'）
            prompt_tokens: 入力プロンプトのトークン数
            completion_tokens: 生成出力のトークン数
            total_tokens: 合計トークン数（prompt_tokens + completion_tokens）
        """
        try:
            await self._token_usage_repository.record_token_usage(
                username,
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
        エラー情報をタスクとタスクメタデータへ記録する。

        §4.6.3 の仕様に基づき以下を実行する:
        1. task_repository.update_task_status() でタスクを failed 状態に更新し error_message を保存する
        2. task_repository.update_task_metadata() でタスクメタデータへエラー詳細（category/message/stack_trace）を記録する
           （仕様書の context_repository.save_metadata() に相当する最善実装。context_repository には
           エラー詳細を保存できる適切なメソッドが存在しないため task_repository を代替使用する）

        Args:
            task_uuid: タスクUUID
            node_id: エラーが発生したワークフローノードID
            error_category: エラーカテゴリ（例: 'transient', 'implementation'）
            error_message: エラーメッセージ
            stack_trace: スタックトレース文字列
        """
        # 1. タスクを failed 状態に更新し error_message を保存する
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

        # 2. タスクメタデータへエラー詳細を記録する
        # 仕様書: context_repository.save_metadata(task_uuid, node_id, {"error": {...}})
        # context_repositoryには適切なメソッドが存在しないため、
        # task_repository.update_task_metadata()でエラー詳細をタスクメタデータに保存する
        error_metadata: dict = {
            "error": {
                "node_id": node_id,
                "category": error_category,
                "message": error_message,
                "stack_trace": stack_trace,
            }
        }
        try:
            if hasattr(self._task_repository, "update_task_metadata"):
                await self._task_repository.update_task_metadata(
                    task_uuid,
                    error_metadata,
                )
                logger.debug(
                    "タスクエラーメタデータ保存完了: task_uuid=%s, node_id=%s, category=%s",
                    task_uuid,
                    node_id,
                    error_category,
                )
        except Exception as exc:
            logger.error(
                "タスクエラーメタデータ保存失敗: task_uuid=%s, error=%s",
                task_uuid,
                exc,
            )
