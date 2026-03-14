"""
初期管理者作成CLIツール

コマンドラインから管理者ユーザーを作成する。
対話式モード・環境変数モード・コマンドライン引数モードをサポートする。

使用方法:
    python -m backend.user_management.cli.create_admin
    python -m backend.user_management.cli.create_admin --email admin@example.com --username Admin --password SecurePass1!
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import re
import sys

import asyncpg

from shared.database.connection import close_pool, create_pool

from ..auth import hash_password, validate_password_strength

logger = logging.getLogger(__name__)

# user_configsのデフォルト設定値（§5.5）
_DEFAULT_CONFIG = {
    "llm_provider": "openai",
    "model_name": "gpt-4o",
    "temperature": 0.2,
    "max_tokens": 4096,
    "context_compression_enabled": True,
    "token_threshold": None,
    "keep_recent_messages": 10,
    "min_to_compress": 5,
    "min_compression_ratio": 0.8,
    "learning_enabled": True,
    "learning_llm_model": "gpt-4o",
    "learning_llm_temperature": 0.3,
    "learning_llm_max_tokens": 8000,
    "learning_exclude_bot_comments": True,
    "learning_only_after_task_start": True,
}


def _validate_email(email: str) -> None:
    """
    メールアドレスの形式をバリデーションする。

    Args:
        email: バリデーション対象のメールアドレス

    Raises:
        ValueError: メールアドレス形式が不正な場合
    """
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email):
        raise ValueError(f"無効なメールアドレス形式です: {email}")


def _validate_username(username: str) -> None:
    """
    ユーザー名をバリデーションする。

    Args:
        username: バリデーション対象のユーザー名

    Raises:
        ValueError: ユーザー名が要件を満たさない場合
    """
    if not username or len(username) == 0:
        raise ValueError("ユーザー名は1文字以上である必要があります")
    if len(username) > 255:
        raise ValueError("ユーザー名は255文字以下である必要があります")


async def _check_user_exists(pool: asyncpg.Pool, email: str) -> bool:
    """
    指定したメールアドレスのユーザーが既に存在するか確認する。

    Args:
        pool: asyncpg接続プール
        email: 確認するメールアドレス

    Returns:
        ユーザーが存在する場合 True、存在しない場合 False
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT email FROM users WHERE email = $1",
            email.lower(),
        )
    return row is not None


async def _create_admin_user(
    pool: asyncpg.Pool,
    email: str,
    username: str,
    password_hash: str,
) -> None:
    """
    管理者ユーザーをトランザクション内で作成する。

    usersテーブルとuser_configsテーブルにINSERTを行う。
    エラー時はROLLBACKする。

    Args:
        pool: asyncpg接続プール
        email: 管理者メールアドレス
        username: 管理者ユーザー名
        password_hash: bcryptハッシュ済みパスワード

    Raises:
        asyncpg.PostgresError: DB操作エラー時
    """
    normalized_email = email.lower()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # usersテーブルへINSERT
            await conn.execute(
                """
                INSERT INTO users (email, username, password_hash, role, is_active)
                VALUES ($1, $2, $3, 'admin', true)
                """,
                normalized_email,
                username,
                password_hash,
            )

            # user_configsテーブルへデフォルト設定でINSERT
            await conn.execute(
                """
                INSERT INTO user_configs (
                    user_email, llm_provider, model_name, temperature, max_tokens,
                    context_compression_enabled, token_threshold,
                    keep_recent_messages, min_to_compress, min_compression_ratio,
                    learning_enabled, learning_llm_model, learning_llm_temperature,
                    learning_llm_max_tokens, learning_exclude_bot_comments,
                    learning_only_after_task_start
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7,
                    $8, $9, $10,
                    $11, $12, $13,
                    $14, $15,
                    $16
                )
                """,
                normalized_email,
                _DEFAULT_CONFIG["llm_provider"],
                _DEFAULT_CONFIG["model_name"],
                _DEFAULT_CONFIG["temperature"],
                _DEFAULT_CONFIG["max_tokens"],
                _DEFAULT_CONFIG["context_compression_enabled"],
                _DEFAULT_CONFIG["token_threshold"],
                _DEFAULT_CONFIG["keep_recent_messages"],
                _DEFAULT_CONFIG["min_to_compress"],
                _DEFAULT_CONFIG["min_compression_ratio"],
                _DEFAULT_CONFIG["learning_enabled"],
                _DEFAULT_CONFIG["learning_llm_model"],
                _DEFAULT_CONFIG["learning_llm_temperature"],
                _DEFAULT_CONFIG["learning_llm_max_tokens"],
                _DEFAULT_CONFIG["learning_exclude_bot_comments"],
                _DEFAULT_CONFIG["learning_only_after_task_start"],
            )


def _get_input_interactive() -> tuple[str, str, str]:
    """
    対話式モードでメールアドレス・ユーザー名・パスワードを入力させる。

    パスワード入力は画面にマスキングされる。
    パスワードは確認入力で一致することを確認する。

    Returns:
        (email, username, password) のタプル

    Raises:
        ValueError: 入力値が要件を満たさない場合
        SystemExit: 入力のキャンセル時
    """
    print("=== 管理者ユーザー作成ツール ===\n")

    # メールアドレス入力
    email = input("Enter admin email: ").strip()
    _validate_email(email)

    # ユーザー名入力
    username = input("Enter admin username: ").strip()
    _validate_username(username)

    # パスワード入力（マスキング）
    password = getpass.getpass("Enter admin password: ")
    validate_password_strength(password)

    # パスワード確認入力
    confirm_password = getpass.getpass("Confirm password: ")
    if password != confirm_password:
        raise ValueError("パスワードが一致しません。再度実行してください。")

    return email, username, password


def _get_input_from_env() -> tuple[str, str, str] | None:
    """
    環境変数からメールアドレス・ユーザー名・パスワードを取得する。

    Returns:
        (email, username, password) のタプル。環境変数が未設定の場合は None。
    """
    email = os.getenv("ADMIN_EMAIL", "").strip()
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "").strip()

    if not email or not username or not password:
        return None
    return email, username, password


def _parse_args() -> argparse.Namespace:
    """
    コマンドライン引数を解析する。

    Returns:
        解析済みの引数 Namespace
    """
    parser = argparse.ArgumentParser(
        description="AutomataCodex 初期管理者ユーザー作成ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 対話式モード（推奨）
  python -m backend.user_management.cli.create_admin

  # コマンドライン引数モード
  python -m backend.user_management.cli.create_admin \\
    --email admin@example.com \\
    --username Administrator \\
    --password SecurePassword123!

  # 環境変数モード
  ADMIN_EMAIL=admin@example.com \\
  ADMIN_USERNAME=Administrator \\
  ADMIN_PASSWORD=SecurePassword123! \\
  python -m backend.user_management.cli.create_admin
        """,
    )
    parser.add_argument("--email", type=str, default=None, help="管理者メールアドレス")
    parser.add_argument("--username", type=str, default=None, help="管理者ユーザー名")
    parser.add_argument("--password", type=str, default=None, help="管理者パスワード（セキュリティ上、対話式推奨）")
    return parser.parse_args()


async def _run(email: str, username: str, password: str) -> None:
    """
    管理者ユーザー作成のメイン処理。

    バリデーション → 重複チェック → ハッシュ化 → DB挿入の順で処理する。

    Args:
        email: 管理者メールアドレス
        username: 管理者ユーザー名
        password: 平文パスワード

    Raises:
        SystemExit: エラー発生時
    """
    # バリデーション
    try:
        _validate_email(email)
        _validate_username(username)
        validate_password_strength(password)
    except ValueError as e:
        print(f"\n❌ バリデーションエラー: {e}", file=sys.stderr)
        sys.exit(1)

    pool: asyncpg.Pool | None = None
    try:
        # DB接続プール作成
        pool = await create_pool()
    except Exception as e:
        print(
            f"\n❌ データベース接続エラー: {e}\n"
            "  接続情報（DATABASE_URL または POSTGRES_* 環境変数）を確認してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        # 既存ユーザーチェック
        if await _check_user_exists(pool, email):
            print(
                f"\n❌ メールアドレス '{email}' は既に登録されています。",
                file=sys.stderr,
            )
            sys.exit(1)

        print("\n管理者ユーザーを作成中...")

        # パスワードハッシュ化（bcrypt, コストファクタ12）
        password_hash = hash_password(password)

        # トランザクション内でDB挿入
        await _create_admin_user(pool, email, username, password_hash)

        print(
            f"\n✓ 管理者ユーザーを作成しました\n"
            f"  Email: {email.lower()}\n"
            f"  Username: {username}\n"
            f"  Role: admin"
        )

    except asyncpg.PostgresError as e:
        print(f"\n❌ データベースエラー: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if pool is not None:
            await close_pool()


def main() -> None:
    """
    CLIエントリーポイント。

    入力取得の優先順位:
    1. コマンドライン引数（--email, --username, --password が全て指定された場合）
    2. 環境変数（ADMIN_EMAIL, ADMIN_USERNAME, ADMIN_PASSWORD が全て設定された場合）
    3. 対話式入力
    """
    args = _parse_args()

    # コマンドライン引数モード
    if args.email and args.username and args.password:
        email = args.email.strip()
        username = args.username.strip()
        password = args.password
        asyncio.run(_run(email, username, password))
        return

    # 環境変数モード
    env_input = _get_input_from_env()
    if env_input is not None:
        email, username, password = env_input
        asyncio.run(_run(email, username, password))
        return

    # 対話式モード
    try:
        email, username, password = _get_input_interactive()
    except ValueError as e:
        print(f"\n❌ {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n操作がキャンセルされました。", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run(email, username, password))


if __name__ == "__main__":
    main()
