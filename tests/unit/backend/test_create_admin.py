"""
初期管理者作成CLIツールの単体テスト

メールアドレスバリデーション・重複ユーザー検出・パスワード強度チェックの
各条件分岐を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from backend.user_management.cli.create_admin import (
    _check_user_exists,
    _create_admin_user,
    _get_input_from_env,
    _validate_email,
    _validate_username,
)


# =====================================================================
# メールアドレスバリデーションのテスト
# =====================================================================


class TestValidateEmail:
    """_validate_email のテスト"""

    @pytest.mark.parametrize(
        "email",
        [
            "admin@example.com",
            "user.name+tag@subdomain.example.co.jp",
            "test123@test-domain.org",
        ],
    )
    def test_有効なメールアドレスで例外が発生しないこと(self, email: str):
        """有効なメールアドレス形式でValueErrorが発生しないことを検証する"""
        _validate_email(email)  # 例外なし

    @pytest.mark.parametrize(
        "email",
        [
            "not-an-email",
            "@no-local-part.com",
            "missing-at-sign.com",
            "spaces in@email.com",
            "",
            "double@@at.com",
        ],
    )
    def test_無効なメールアドレスでValueErrorが発生すること(self, email: str):
        """無効なメールアドレス形式でValueErrorが発生することを検証する"""
        with pytest.raises(ValueError, match="メールアドレス"):
            _validate_email(email)


# =====================================================================
# ユーザー名バリデーションのテスト
# =====================================================================


class TestValidateUsername:
    """_validate_username のテスト"""

    def test_有効なユーザー名で例外が発生しないこと(self):
        """1文字以上255文字以下のユーザー名でValueErrorが発生しないことを検証する"""
        _validate_username("Administrator")  # 例外なし
        _validate_username("A")  # 最小1文字
        _validate_username("x" * 255)  # 最大255文字

    def test_空文字列でValueErrorが発生すること(self):
        """空文字列でValueErrorが発生することを検証する"""
        with pytest.raises(ValueError):
            _validate_username("")

    def test_255文字超過でValueErrorが発生すること(self):
        """255文字を超えるユーザー名でValueErrorが発生することを検証する"""
        with pytest.raises(ValueError):
            _validate_username("a" * 256)


# =====================================================================
# 重複ユーザー検出のテスト
# =====================================================================


class TestCheckUserExists:
    """_check_user_exists のテスト"""

    def _make_pool(self, fetchrow_result) -> MagicMock:
        """asyncpg.Pool のモックを生成する"""
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=fetchrow_result)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        return pool

    async def test_ユーザーが存在する場合にTrueが返ること(self):
        """既にGitLabユーザー名が登録済みの場合にTrueが返ることを検証する"""
        pool = self._make_pool({"username": "existing_user"})
        result = await _check_user_exists(pool, "existing_user")
        assert result is True

    async def test_ユーザーが存在しない場合にFalseが返ること(self):
        """GitLabユーザー名が未登録の場合にFalseが返ることを検証する"""
        pool = self._make_pool(None)
        result = await _check_user_exists(pool, "new_user")
        assert result is False

    async def test_ユーザー名がDBに渡されてチェックされること(self):
        """指定したGitLabユーザー名がDBのfetchrowに渡されることを検証する"""
        pool = self._make_pool(None)
        conn = pool.acquire.return_value.__aenter__.return_value
        await _check_user_exists(pool, "target_username")
        # fetchrowが呼ばれた引数にユーザー名が含まれることを確認する
        call_args = conn.fetchrow.call_args[0]
        assert "target_username" in call_args


# =====================================================================
# 管理者ユーザー作成のテスト
# =====================================================================


class TestCreateAdminUser:
    """_create_admin_user のテスト"""

    def _make_pool_with_transaction(self) -> tuple[MagicMock, AsyncMock]:
        """トランザクションをサポートするasyncpg.Poolモックを生成する"""
        pool = MagicMock()
        conn = AsyncMock()
        conn.execute = AsyncMock()

        # トランザクションコンテキストマネージャのモック
        transaction = AsyncMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=transaction)

        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        return pool, conn

    async def test_管理者ユーザーが正常に作成されること(self):
        """usersとuser_configsの両テーブルにINSERTが実行されることを検証する"""
        pool, conn = self._make_pool_with_transaction()

        await _create_admin_user(
            pool,
            
            username="Administrator",
            password_hash="$2b$12$hashed_password",
        )

        # conn.execute が2回（users + user_configs）呼ばれていることを確認する
        assert conn.execute.call_count == 2

    async def test_ユーザー名が正しくINSERTされること(self):
        """指定したGitLabユーザー名がusersテーブルにINSERTされることを検証する"""
        pool, conn = self._make_pool_with_transaction()

        await _create_admin_user(
            pool,
            username="Administrator",
            password_hash="$2b$12$hashed",
        )

        # 最初のINSERT (users テーブル) の引数を確認する
        first_call_args = conn.execute.call_args_list[0][0]
        # ユーザー名が含まれることを確認する
        assert "Administrator" in first_call_args


# =====================================================================
# 環境変数入力モードのテスト
# =====================================================================


class TestGetInputFromEnv:
    """_get_input_from_env のテスト"""

    def test_環境変数が全て設定されている場合にタプルが返ること(self):
        """ADMIN_USERNAME, ADMIN_PASSWORDが設定されている場合に2要素タプルが返ることを検証する"""
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "Admin User",
                "ADMIN_PASSWORD": "SecurePass1!",
            },
        ):
            result = _get_input_from_env()

        assert result is not None
        username, password = result
        assert username == "Admin User"
        assert password == "SecurePass1!"

    def test_環境変数が未設定の場合にNoneが返ること(self):
        """ADMIN_*環境変数が未設定の場合にNoneが返ることを検証する"""
        import os
        from unittest.mock import patch

        env = os.environ.copy()
        env.pop("ADMIN_USERNAME", None)
        env.pop("ADMIN_PASSWORD", None)

        with patch.dict(os.environ, env, clear=True):
            result = _get_input_from_env()

        assert result is None

    def test_一部の環境変数が未設定の場合にNoneが返ること(self):
        """ADMIN_PASSWORDのみ未設定の場合にNoneが返ることを検証する"""
        import os
        from unittest.mock import patch

        env = os.environ.copy()
        env.pop("ADMIN_PASSWORD", None)

        with patch.dict(
            os.environ,
            {**env, "ADMIN_USERNAME": "Admin"},
            clear=True,
        ):
            result = _get_input_from_env()

        assert result is None
