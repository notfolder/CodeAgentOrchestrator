"""
データベース接続モジュール

asyncpgを使用した非同期PostgreSQL接続プール管理。
マイグレーション適用機能も提供する。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

# デフォルト接続プール設定
_DEFAULT_POOL_MIN_SIZE = 5
_DEFAULT_POOL_MAX_SIZE = 10
_DEFAULT_POOL_TIMEOUT = 30.0

# グローバル接続プール（シングルトン）
_pool: asyncpg.Pool | None = None


def _build_dsn() -> str:
    """
    環境変数からDSN（Data Source Name）を組み立てる。

    環境変数:
        DATABASE_URL: DSN文字列が直接設定されている場合はそれを使用する
        POSTGRES_HOST: PostgreSQLホスト名（デフォルト: postgres）
        POSTGRES_PORT: ポート番号（デフォルト: 5432）
        POSTGRES_DB: データベース名（デフォルト: coding_agent）
        POSTGRES_USER: ユーザー名（デフォルト: agent）
        POSTGRES_PASSWORD: パスワード（必須）

    Returns:
        DSN文字列
    """
    if url := os.getenv("DATABASE_URL"):
        return url

    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "coding_agent")
    user = os.getenv("POSTGRES_USER", "agent")
    password = os.getenv("POSTGRES_PASSWORD", "")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


async def create_pool(
    dsn: str | None = None,
    *,
    min_size: int = _DEFAULT_POOL_MIN_SIZE,
    max_size: int = _DEFAULT_POOL_MAX_SIZE,
    timeout: float = _DEFAULT_POOL_TIMEOUT,
) -> asyncpg.Pool:
    """
    非同期接続プールを作成してグローバル変数に保存する。

    すでにプールが存在する場合は既存のプールをそのまま返す。

    Args:
        dsn: 接続DSN。Noneの場合は環境変数から構築する。
        min_size: 最小接続数（デフォルト: 5）
        max_size: 最大接続数（デフォルト: 10）
        timeout: 接続タイムアウト秒数（デフォルト: 30.0）

    Returns:
        asyncpg.Pool インスタンス

    Raises:
        asyncpg.PostgresError: 接続失敗時
    """
    global _pool

    if _pool is not None:
        return _pool

    target_dsn = dsn or _build_dsn()
    logger.info("PostgreSQL接続プールを作成します: min_size=%d, max_size=%d", min_size, max_size)

    _pool = await asyncpg.create_pool(
        target_dsn,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        command_timeout=60,
    )

    logger.info("PostgreSQL接続プールを作成しました")
    return _pool


async def get_pool() -> asyncpg.Pool:
    """
    グローバル接続プールを取得する。

    create_pool()が呼ばれていない場合は自動的に作成する。

    Returns:
        asyncpg.Pool インスタンス

    Raises:
        asyncpg.PostgresError: 接続失敗時
    """
    global _pool
    if _pool is None:
        await create_pool()
    assert _pool is not None
    return _pool


async def close_pool() -> None:
    """
    グローバル接続プールを閉じる。

    アプリケーション終了時に呼び出すこと。
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL接続プールを閉じました")


async def get_connection(dsn: str | None = None) -> asyncpg.Connection:
    """
    プールから接続を取得する。

    通常のCRUD操作にはget_pool()を使用することを推奨する。
    本メソッドはプールが不要な単体利用（マイグレーション等）向け。

    Args:
        dsn: 接続DSN。Noneの場合は環境変数から構築する。

    Returns:
        asyncpg.Connection インスタンス
    """
    pool = await get_pool()
    return await pool.acquire()


async def run_migration(
    migration_file: Path,
    pool: asyncpg.Pool | None = None,
) -> None:
    """
    マイグレーションSQLファイルを実行する。

    schema_versionsテーブルで適用済みバージョンを管理し、
    未適用のマイグレーションのみをべき等に適用する。

    Args:
        migration_file: マイグレーションSQLファイルのパス
        pool: 使用する接続プール。Noneの場合はグローバルプールを使用する。

    Raises:
        FileNotFoundError: マイグレーションファイルが見つからない場合
        asyncpg.PostgresError: SQL実行エラー時
    """
    if not migration_file.exists():
        raise FileNotFoundError(f"マイグレーションファイルが見つかりません: {migration_file}")

    # ファイル名からバージョンを抽出する（例: 1.0.0_initial_schema.sql → 1.0.0）
    version = migration_file.stem.split("_")[0]

    target_pool = pool or await get_pool()

    async with target_pool.acquire() as conn:
        # schema_versionsテーブルが存在しない場合は先に作成する
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_versions (
                version     TEXT      PRIMARY KEY,
                applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
            """
        )

        # 適用済みか確認する
        applied = await conn.fetchval(
            "SELECT version FROM schema_versions WHERE version = $1",
            version,
        )
        if applied:
            logger.info("マイグレーション %s は適用済みです。スキップします", version)
            return

        # SQLを読み込んでトランザクション内で実行する
        sql = migration_file.read_text(encoding="utf-8")
        logger.info("マイグレーション %s を適用します", version)
        async with conn.transaction():
            await conn.execute(sql)

    logger.info("マイグレーション %s を適用しました", version)


async def run_all_migrations(
    migrations_dir: Path | None = None,
    pool: asyncpg.Pool | None = None,
) -> None:
    """
    migrationsディレクトリ内の全マイグレーションをバージョン順に適用する。

    Args:
        migrations_dir: マイグレーションファイルが格納されたディレクトリ。
                       Noneの場合は本ファイルと同階層のmigrationsディレクトリを使用する。
        pool: 使用する接続プール。Noneの場合はグローバルプールを使用する。

    Raises:
        asyncpg.PostgresError: SQL実行エラー時
    """
    if migrations_dir is None:
        migrations_dir = Path(__file__).parent / "migrations"

    if not migrations_dir.exists():
        logger.warning("マイグレーションディレクトリが存在しません: %s", migrations_dir)
        return

    # ファイル名でソートして順番に適用する
    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        logger.info("適用するマイグレーションファイルがありません")
        return

    for migration_file in migration_files:
        await run_migration(migration_file, pool=pool)

    logger.info("全マイグレーションの適用が完了しました（%d 件）", len(migration_files))


def get_encryption_key() -> bytes:
    """
    環境変数からAES-256-GCM暗号化キーを取得する。

    Returns:
        32バイトの暗号化キー

    Raises:
        ValueError: ENCRYPTION_KEY が設定されていない、または長さが不正な場合
    """
    raw = os.getenv("ENCRYPTION_KEY", "")
    if not raw:
        raise ValueError("環境変数 ENCRYPTION_KEY が設定されていません")

    key_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(key_bytes) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY は32バイトである必要があります（現在: {len(key_bytes)}バイト）"
        )
    return key_bytes
