"""
ツール実行結果コンテキストProvider

ツール実行結果をJSONファイルとしてファイルシステムに保存し、
メタデータをPostgreSQLに記録してエージェントへコンテキストとして提供する
カスタムContextProvider。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from consumer.providers.planning_context_provider import BaseContextProvider

logger = logging.getLogger(__name__)

# ツール実行結果のプレビュー最大文字数
_RESULT_PREVIEW_MAX_CHARS = 500
# 取得するメタデータの最大件数
_METADATA_FETCH_LIMIT = 10


class ToolResultContextProvider(BaseContextProvider):
    """
    ツール実行結果コンテキストProviderクラス。

    context_tool_results_metadataテーブルから直近10件のメタデータを取得し、
    対応するJSONファイルから結果を読み込んでMarkdown形式でエージェントへ提供する。
    エージェント実行後はツール実行結果をJSONファイルに保存し、メタデータをDBへ記録する。

    Attributes:
        _pool: asyncpg接続プール
        _file_storage_base_dir: ファイルストレージのベースディレクトリ
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        file_storage_base_dir: str = "tool_results",
    ) -> None:
        """
        ToolResultContextProviderを初期化する。

        Args:
            db_pool: asyncpg接続プール
            file_storage_base_dir: ファイルストレージのベースディレクトリ
        """
        self._pool = db_pool
        self._file_storage_base_dir = file_storage_base_dir

    async def before_run(
        self, *, task_uuid: str, **kwargs: Any
    ) -> str | None:
        """
        エージェント実行前にツール実行結果の要約をMarkdown形式で返す。

        context_tool_results_metadataテーブルから直近10件のメタデータを取得し、
        対応するJSONファイルの先頭500文字をプレビューとして整形して返す。
        メタデータが存在しない場合はNoneを返す。

        Args:
            task_uuid: タスクUUID
            **kwargs: 追加引数（未使用）

        Returns:
            Markdown形式のツール実行結果要約文字列。データなしの場合はNone。
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tool_name, tool_command, file_path, created_at
                FROM context_tool_results_metadata
                WHERE task_uuid = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                task_uuid,
                _METADATA_FETCH_LIMIT,
            )

        if not rows:
            logger.debug(
                "ツール実行結果なし: task_uuid=%s", task_uuid
            )
            return None

        lines: list[str] = ["## 直近のツール実行結果"]
        for row in rows:
            tool_name = row["tool_name"] or ""
            tool_command = row["tool_command"] or ""
            file_path = row["file_path"] or ""
            created_at = row["created_at"]

            # ファイルからツール実行結果を読み込む（先頭500文字のみ）
            result_preview = self._read_result_preview(file_path)

            lines.append(f"\n### {tool_name} ({tool_command})")
            lines.append(f"**実行日時**: {created_at}")
            lines.append(f"**結果プレビュー**:\n{result_preview}")

        context_text = "\n".join(lines)
        logger.debug(
            "ツール実行結果取得完了: task_uuid=%s, 件数=%d",
            task_uuid,
            len(rows),
        )
        return context_text

    def _read_result_preview(self, file_path: str) -> str:
        """
        指定されたJSONファイルから先頭500文字のプレビューを読み込む。

        ファイルが存在しない場合や読み込みに失敗した場合は空文字列を返す。

        Args:
            file_path: JSONファイルのパス

        Returns:
            ファイル内容の先頭500文字
        """
        if not file_path:
            return ""
        try:
            path = Path(file_path)
            if not path.exists():
                logger.warning("ツール実行結果ファイルが見つかりません: %s", file_path)
                return ""
            content = path.read_text(encoding="utf-8")
            return content[:_RESULT_PREVIEW_MAX_CHARS]
        except Exception as exc:
            logger.warning(
                "ツール実行結果ファイル読み込みエラー: %s, error=%s",
                file_path,
                exc,
            )
            return ""

    async def after_run(
        self,
        *,
        task_uuid: str,
        tool_name: str,
        tool_command: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """
        エージェント実行後にツール実行結果をファイルに保存しメタデータをDBへ記録する。

        タイムスタンプ付きファイル名でJSONファイルを生成し、
        {file_storage_base_dir}/{task_uuid}/ ディレクトリに保存する。
        その後、context_tool_results_metadataテーブルへメタデータをINSERTする。

        Args:
            task_uuid: タスクUUID
            tool_name: ツール名（例: 'text_editor'）
            tool_command: ツールコマンド（例: 'view'）
            arguments: ツールへ渡した引数
            result: ツール実行結果
            **kwargs: 追加引数（未使用）
        """
        # タイムスタンプ付きファイル名を生成する
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{tool_name}.json"

        # ファイルパスを構築してディレクトリを作成する
        file_dir = Path(self._file_storage_base_dir) / task_uuid
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / filename

        # ツール実行結果をJSONファイルに保存する
        payload = {
            "timestamp": timestamp,
            "tool_name": tool_name,
            "tool_command": tool_command,
            "arguments": arguments,
            "result": result,
        }
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        file_size = file_path.stat().st_size
        success = True

        # メタデータをDBへ記録する
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO context_tool_results_metadata
                    (task_uuid, tool_name, tool_command, file_path, file_size, success)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                task_uuid,
                tool_name,
                tool_command,
                str(file_path),
                file_size,
                success,
            )

        logger.info(
            "ツール実行結果保存完了: task_uuid=%s, tool_name=%s, file=%s",
            task_uuid,
            tool_name,
            file_path,
        )
