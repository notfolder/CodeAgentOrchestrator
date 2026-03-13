"""
コンテキスト圧縮サービス

context_messagesテーブルのトークン数を監視し、閾値を超えた場合に
古いメッセージをLLMで要約して圧縮するサービス。
PostgreSqlChatHistoryProviderと連携して動作する。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import asyncpg

if TYPE_CHECKING:
    from shared.config.models import ContextCompressionConfig

logger = logging.getLogger(__name__)

# 要約プロンプトテンプレート
_SUMMARY_PROMPT_TEMPLATE = (
    "以下の会話履歴（メッセージ {start_seq}〜{end_seq}）を簡潔に要約してください。"
    "重要なコンテキスト、決定事項、および主要な情報を保持してください。\n\n"
    "{messages_text}"
)


class ContextCompressionService:
    """
    コンテキスト圧縮サービスクラス。

    context_messagesテーブルのトークン数がユーザー設定の閾値を超えた場合に、
    古いメッセージをLLMで要約してメッセージを圧縮する。
    圧縮履歴はmessage_compressionsテーブルへ記録する。

    Attributes:
        _pool: asyncpg接続プール
        _llm_client: 要約生成用LLMクライアント
        _config: コンテキスト圧縮設定
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        llm_client: Any,
        config: "ContextCompressionConfig",
    ) -> None:
        """
        ContextCompressionServiceを初期化する。

        Args:
            db_pool: asyncpg接続プール
            llm_client: 要約生成用LLMクライアント（generate(prompt)メソッドを持つ）
            config: コンテキスト圧縮設定（ContextCompressionConfig）
        """
        self._pool = db_pool
        self._llm_client = llm_client
        self._config = config

    async def check_and_compress_async(
        self, task_uuid: str, user_email: str
    ) -> bool:
        """
        トークン数を確認し、必要に応じてコンテキストを圧縮する。

        user_configsテーブルからユーザー設定を取得し、圧縮が有効かつ
        トークン数が閾値を超えた場合に圧縮処理を実行する。

        Args:
            task_uuid: タスクUUID
            user_email: ユーザーメールアドレス

        Returns:
            圧縮を実行した場合はTrue、圧縮不要または無効の場合はFalse
        """
        async with self._pool.acquire() as conn:
            user_config_row = await conn.fetchrow(
                """
                SELECT context_compression_enabled, token_threshold,
                       keep_recent_messages, min_to_compress,
                       min_compression_ratio, model_name
                FROM user_configs
                WHERE user_email = $1
                """,
                user_email,
            )

        # ユーザー設定が取得できない場合はデフォルト設定を使用する
        if user_config_row is None:
            logger.debug(
                "ユーザー設定が見つかりません。圧縮をスキップ: user_email=%s",
                user_email,
            )
            return False

        # 圧縮が無効な場合は即時Falseを返す
        if not user_config_row["context_compression_enabled"]:
            logger.debug(
                "コンテキスト圧縮が無効: user_email=%s", user_email
            )
            return False

        # effective_token_threshold を決定する
        # ユーザー設定が明示的に指定されている場合はその値を優先する
        user_config_threshold: int | None = user_config_row["token_threshold"]
        model_name: str = user_config_row["model_name"] or ""
        if user_config_threshold is not None:
            effective_token_threshold: int = user_config_threshold
        else:
            effective_token_threshold = self._config.model_recommendations.get(
                model_name, self._config.default_token_threshold
            )

        # 各パラメータはNoneチェックで判定する（0を有効な値として扱う）
        keep_recent_raw = user_config_row["keep_recent_messages"]
        keep_recent: int = (
            keep_recent_raw
            if keep_recent_raw is not None
            else self._config.default_keep_recent
        )
        min_to_compress_raw = user_config_row["min_to_compress"]
        min_to_compress: int = (
            min_to_compress_raw
            if min_to_compress_raw is not None
            else self._config.default_min_to_compress
        )
        min_compression_ratio_raw = user_config_row["min_compression_ratio"]
        min_compression_ratio: float = (
            min_compression_ratio_raw
            if min_compression_ratio_raw is not None
            else self._config.default_min_compression_ratio
        )

        # 現在のトークン数を確認する
        async with self._pool.acquire() as conn:
            total_tokens_raw = await conn.fetchval(
                "SELECT SUM(tokens) FROM context_messages WHERE task_uuid = $1",
                task_uuid,
            )
        total_tokens: int = int(total_tokens_raw or 0)

        if total_tokens <= effective_token_threshold:
            logger.debug(
                "圧縮不要のため終了: task_uuid=%s, tokens=%d, threshold=%d",
                task_uuid,
                total_tokens,
                effective_token_threshold,
            )
            return False

        # 保持対象のseqセット（最新N件 + systemメッセージ）を構築する
        async with self._pool.acquire() as conn:
            recent_rows = await conn.fetch(
                """
                SELECT seq FROM context_messages
                WHERE task_uuid = $1
                ORDER BY seq DESC
                LIMIT $2
                """,
                task_uuid,
                keep_recent,
            )
            system_rows = await conn.fetch(
                """
                SELECT seq FROM context_messages
                WHERE task_uuid = $1 AND role = 'system'
                """,
                task_uuid,
            )

        keep_seqs: set[int] = {row["seq"] for row in recent_rows}
        keep_seqs.update(row["seq"] for row in system_rows)

        # 圧縮対象のseqリストを抽出する（is_compressed_summary=falseのもの）
        async with self._pool.acquire() as conn:
            candidate_rows = await conn.fetch(
                """
                SELECT seq, role FROM context_messages
                WHERE task_uuid = $1 AND is_compressed_summary = false
                ORDER BY seq ASC
                """,
                task_uuid,
            )

        compress_seqs = [
            row["seq"]
            for row in candidate_rows
            if row["seq"] not in keep_seqs
        ]

        # 圧縮対象数が最小件数未満の場合は終了する
        if len(compress_seqs) < min_to_compress:
            logger.debug(
                "圧縮対象が最小件数未満: task_uuid=%s, 対象=%d, 最小=%d",
                task_uuid,
                len(compress_seqs),
                min_to_compress,
            )
            return False

        start_seq = compress_seqs[0]
        end_seq = compress_seqs[-1]

        # 圧縮前のトークン数を取得する
        async with self._pool.acquire() as conn:
            original_tokens_raw = await conn.fetchval(
                """
                SELECT SUM(tokens) FROM context_messages
                WHERE task_uuid = $1 AND seq >= $2 AND seq <= $3
                """,
                task_uuid,
                start_seq,
                end_seq,
            )
        original_tokens: int = int(original_tokens_raw or 0)

        # 要約を生成する
        summary_text, compressed_tokens = await self.compress_messages_async(
            task_uuid, start_seq, end_seq
        )

        # 圧縮率を検証する（圧縮後/圧縮前が閾値以上の場合は効果が薄いためスキップ）
        if original_tokens > 0:
            compression_ratio = compressed_tokens / original_tokens
            if compression_ratio >= min_compression_ratio:
                logger.info(
                    "圧縮率が不十分のため圧縮スキップ: task_uuid=%s, ratio=%.2f, threshold=%.2f",
                    task_uuid,
                    compression_ratio,
                    min_compression_ratio,
                )
                return False

        # メッセージを要約で置き換える
        await self.replace_with_summary_async(
            task_uuid,
            summary_text,
            start_seq,
            end_seq,
            original_tokens,
            compressed_tokens,
        )
        logger.info(
            "コンテキスト圧縮完了: task_uuid=%s, original_tokens=%d, compressed_tokens=%d",
            task_uuid,
            original_tokens,
            compressed_tokens,
        )
        return True

    async def compress_messages_async(
        self, task_uuid: str, start_seq: int, end_seq: int
    ) -> tuple[str, int]:
        """
        指定seq範囲のメッセージをLLMで要約する。

        対象メッセージを取得してテキストに整形し、LLMクライアントで要約を生成する。
        トークン数はlen(summary.split()) * 1.3の近似値を使用する。

        Args:
            task_uuid: タスクUUID
            start_seq: 圧縮開始seq（含む）
            end_seq: 圧縮終了seq（含む）

        Returns:
            (要約テキスト, トークン数)のタプル
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content
                FROM context_messages
                WHERE task_uuid = $1 AND seq >= $2 AND seq <= $3
                ORDER BY seq ASC
                """,
                task_uuid,
                start_seq,
                end_seq,
            )

        # メッセージテキストを整形する
        messages_text = "\n".join(
            f"[{row['role']}]: {row['content']}" for row in rows
        )

        # 要約プロンプトを構築してLLMを呼び出す
        prompt = _SUMMARY_PROMPT_TEMPLATE.format(
            start_seq=start_seq,
            end_seq=end_seq,
            messages_text=messages_text,
        )
        summary: str = await self._llm_client.generate(prompt)

        # トークン数を近似値で計算する
        token_count = int(len(summary.split()) * 1.3)

        logger.debug(
            "メッセージ要約生成完了: task_uuid=%s, seq=%d-%d, tokens=%d",
            task_uuid,
            start_seq,
            end_seq,
            token_count,
        )
        return summary, token_count

    async def replace_with_summary_async(
        self,
        task_uuid: str,
        summary: str,
        start_seq: int,
        end_seq: int,
        original_tokens: int,
        compressed_tokens: int,
    ) -> None:
        """
        指定seq範囲のメッセージを要約メッセージで置き換える。

        トランザクション内で以下を実行する:
        1. 指定seq範囲のメッセージを削除する
        2. 要約メッセージをstart_seqに挿入する
        3. 後続メッセージのseqを再番号化する
        4. message_compressionsテーブルへ圧縮履歴を記録する

        Args:
            task_uuid: タスクUUID
            summary: LLMが生成した要約テキスト
            start_seq: 圧縮開始seq
            end_seq: 圧縮終了seq
            original_tokens: 圧縮前のトークン数
            compressed_tokens: 圧縮後のトークン数
        """
        summary_content = (
            f"[Summary of previous conversation "
            f"(messages {start_seq}-{end_seq})]: {summary}"
        )
        compressed_range = json.dumps(
            {"start_seq": start_seq, "end_seq": end_seq}
        )
        # 削除するメッセージ数分だけseqをシフトする
        shift_amount = end_seq - start_seq
        compression_ratio = (
            compressed_tokens / original_tokens
            if original_tokens > 0
            else 0.0
        )
        summary_seq = start_seq

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. 圧縮対象メッセージを削除する
                await conn.execute(
                    """
                    DELETE FROM context_messages
                    WHERE task_uuid = $1 AND seq >= $2 AND seq <= $3
                    """,
                    task_uuid,
                    start_seq,
                    end_seq,
                )

                # 2. 要約メッセージを挿入する
                await conn.execute(
                    """
                    INSERT INTO context_messages
                        (task_uuid, seq, role, content, tokens,
                         is_compressed_summary, compressed_range)
                    VALUES ($1, $2, 'user', $3, $4, true, $5::jsonb)
                    """,
                    task_uuid,
                    summary_seq,
                    summary_content,
                    compressed_tokens,
                    compressed_range,
                )

                # 3. 後続メッセージのseqを再番号化する
                await conn.execute(
                    """
                    UPDATE context_messages
                    SET seq = seq - $1
                    WHERE task_uuid = $2 AND seq > $3
                    """,
                    shift_amount,
                    task_uuid,
                    end_seq,
                )

                # 4. 圧縮履歴を記録する
                await conn.execute(
                    """
                    INSERT INTO message_compressions
                        (task_uuid, start_seq, end_seq, summary_seq,
                         original_token_count, compressed_token_count, compression_ratio)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    task_uuid,
                    start_seq,
                    end_seq,
                    summary_seq,
                    original_tokens,
                    compressed_tokens,
                    compression_ratio,
                )

        logger.info(
            "メッセージ置き換え完了: task_uuid=%s, seq=%d-%d → %d, ratio=%.2f",
            task_uuid,
            start_seq,
            end_seq,
            summary_seq,
            compression_ratio,
        )
