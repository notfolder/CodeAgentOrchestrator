"""
UserRepository の単体テスト

usersテーブルとuser_configsテーブルへのCRUD操作、
およびAES-256-GCMによるAPIキーの暗号化・復号を検証する。
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from database.repositories.user_repository import (
    UserRepository,
    decrypt_api_key,
    encrypt_api_key,
)


# ========================================
# 暗号化・復号のテスト
# ========================================


class TestEncryptDecryptApiKey:
    """APIキーの暗号化・復号テスト"""

    def test_encrypt_returns_string(self):
        """暗号化結果が文字列で返ることを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "a" * 32}):
            result = encrypt_api_key("test-api-key")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_decrypt_returns_original(self):
        """暗号化後に復号すると元の値に戻ることを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "a" * 32}):
            encrypted = encrypt_api_key("sk-test-12345")
            decrypted = decrypt_api_key(encrypted)
        assert decrypted == "sk-test-12345"

    def test_different_nonce_each_encryption(self):
        """同じAPIキーを2回暗号化しても異なる結果になることを検証する（ランダムnonce）"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "b" * 32}):
            encrypted1 = encrypt_api_key("same-key")
            encrypted2 = encrypt_api_key("same-key")
        assert encrypted1 != encrypted2

    def test_encrypt_requires_32_byte_key(self):
        """32バイト以外のキーを指定した場合にValueErrorが発生することを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "short"}):
            with pytest.raises(ValueError, match="32バイト"):
                encrypt_api_key("test")

    def test_encrypt_requires_key_set(self):
        """ENCRYPTION_KEYが未設定の場合にValueErrorが発生することを検証する"""
        env = os.environ.copy()
        env.pop("ENCRYPTION_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
                encrypt_api_key("test")


# ========================================
# UserRepository のテスト
# ========================================


def _make_pool() -> MagicMock:
    """asyncpg.Pool のモックを生成する"""
    pool = MagicMock()
    # acquire() はコンテキストマネージャを返すため非同期対応のモックにする
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


class TestCreateUser:
    """create_user のテスト"""

    async def test_create_user_success(self):
        """ユーザーを正常に作成できることを検証する"""
        pool, conn = _make_pool()
        expected_row = {
            "username": "testuser",
            "username": "Test User",
            "password_hash": "hashed",
            "role": "user",
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
        conn.fetchrow = AsyncMock(return_value=expected_row)

        repo = UserRepository(pool)
        result = await repo.create_user(
            "test@example.com",
            "Test User",
            "hashed",
        )

        assert result["username"] == "testuser"
        conn.fetchrow.assert_awaited_once()
        # メールアドレスが小文字に正規化されていることを確認する
        call_args = conn.fetchrow.call_args[0]
        assert "testuser" in call_args

    async def test_create_user_normalizes_username(self):
        """ユーザー名が小文字に正規化されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"username": "testuser"})

        repo = UserRepository(pool)
        await repo.create_user("User", "hash")

        call_args = conn.fetchrow.call_args[0]
        assert "testuser" in call_args

    async def test_create_user_raises_on_duplicate_username(self):
        """重複するユーザー名でユーザー作成するとUniqueViolationErrorが伝播することを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError())

        repo = UserRepository(pool)
        with pytest.raises(asyncpg.UniqueViolationError):
            await repo.create_user("Dup User", "hash")


class TestGetUserByUsername:
    """get_user_by_username のテスト"""

    async def test_returns_user_when_found(self):
        """ユーザーが存在する場合にレコードを返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"username": "Found"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.get_user_by_username("found@example.com")

        assert result is not None
        assert result["username"] == "Found"

    async def test_returns_none_when_not_found(self):
        """ユーザーが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = UserRepository(pool)
        result = await repo.get_user_by_username("notfound@example.com")

        assert result is None


class TestUpdateUser:
    """update_user のテスト"""

    async def test_update_role(self):
        """ロールを更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"username": "user", "role": "admin"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.update_user("user@example.com", role="admin")

        assert result is not None
        assert result["role"] == "admin"
        conn.fetchrow.assert_awaited_once()

    async def test_update_with_no_fields_returns_current(self):
        """更新フィールドが空の場合は既存レコードをそのまま返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"username": "user", "role": "user"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.update_user("user@example.com")

        # get_user_by_username を呼び出すため fetchrow が1回呼ばれる
        conn.fetchrow.assert_awaited_once()
        assert result is not None

    async def test_returns_none_when_user_not_found(self):
        """対象ユーザーが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = UserRepository(pool)
        result = await repo.update_user("notfound@example.com", role="admin")

        assert result is None


class TestDeleteUser:
    """delete_user のテスト"""

    async def test_delete_existing_user(self):
        """存在するユーザーを削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = UserRepository(pool)
        result = await repo.delete_user("user@example.com")

        assert result is True

    async def test_delete_nonexistent_user(self):
        """存在しないユーザーを削除しようとした場合にFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = UserRepository(pool)
        result = await repo.delete_user("notfound@example.com")

        assert result is False


class TestListUsers:
    """list_users のテスト"""

    async def test_list_all_users(self):
        """全ユーザー一覧を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"username": "A"},
            {"username": "B"},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = UserRepository(pool)
        result = await repo.list_users()

        assert len(result) == 2
        conn.fetch.assert_awaited_once()

    async def test_filter_by_is_active(self):
        """is_activeでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = UserRepository(pool)
        await repo.list_users(is_active=True)

        call_args = conn.fetch.call_args[0]
        assert any("is_active" in str(arg) for arg in call_args)


# ========================================
# user_configs テーブルのテスト
# ========================================


class TestCreateUserConfig:
    """create_user_config のテスト"""

    async def test_create_config_without_api_key(self):
        """APIキーなしでユーザー設定を作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {"username": "testuser", "api_key_encrypted": None}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.create_user_config("testuser")

        assert result["username"] == "testuser"
        # APIキーなしの場合 api_key_encrypted が NULL になることを確認する
        call_args = conn.fetchrow.call_args[0]
        assert None in call_args

    async def test_create_config_with_api_key_encrypts_it(self):
        """APIキーが暗号化されてDBに保存されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"username": "testuser"})

        with patch.dict(os.environ, {"ENCRYPTION_KEY": "c" * 32}):
            repo = UserRepository(pool)
            await repo.create_user_config("testuser", api_key="sk-secret")

        # 呼び出し時の引数に平文APIキーが含まれていないことを確認する
        call_args = conn.fetchrow.call_args[0]
        assert "sk-secret" not in [str(a) for a in call_args]

    async def test_create_config_raises_on_duplicate(self):
        """同一メールアドレスの設定を重複作成した場合にUniqueViolationErrorが伝播することを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError())

        repo = UserRepository(pool)
        with pytest.raises(asyncpg.UniqueViolationError):
            await repo.create_user_config("dup@example.com")


class TestGetDecryptedApiKey:
    """get_decrypted_api_key のテスト"""

    async def test_returns_decrypted_key(self):
        """暗号化されたAPIキーを復号して返すことを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "d" * 32}):
            encrypted = encrypt_api_key("sk-original-key")

        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={
            "username": "testuser",
            "api_key_encrypted": encrypted,
        })

        with patch.dict(os.environ, {"ENCRYPTION_KEY": "d" * 32}):
            repo = UserRepository(pool)
            result = await repo.get_decrypted_api_key("user@example.com")

        assert result == "sk-original-key"

    async def test_returns_none_when_no_config(self):
        """設定が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = UserRepository(pool)
        result = await repo.get_decrypted_api_key("notfound@example.com")

        assert result is None

    async def test_returns_none_when_no_api_key(self):
        """APIキーが未設定の場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={
            "username": "testuser",
            "api_key_encrypted": None,
        })

        repo = UserRepository(pool)
        result = await repo.get_decrypted_api_key("user@example.com")

        assert result is None


class TestUpdateUserConfig:
    """update_user_config のテスト"""

    async def test_update_model_name(self):
        """モデル名を更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"username": "testuser", "model_name": "gpt-4"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.update_user_config("user@example.com", model_name="gpt-4")

        assert result is not None
        assert result["model_name"] == "gpt-4"

    async def test_update_api_key_encrypts(self):
        """APIキー更新時に暗号化されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"username": "testuser"})

        with patch.dict(os.environ, {"ENCRYPTION_KEY": "e" * 32}):
            repo = UserRepository(pool)
            await repo.update_user_config("user@example.com", api_key="new-sk-key")

        call_args = conn.fetchrow.call_args[0]
        assert "new-sk-key" not in [str(a) for a in call_args]

    async def test_returns_none_when_not_found(self):
        """対象ユーザーが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = UserRepository(pool)
        result = await repo.update_user_config("notfound@example.com", model_name="gpt-4")

        assert result is None


class TestDeleteUserConfig:
    """delete_user_config のテスト"""

    async def test_delete_existing_config(self):
        """存在するユーザー設定を削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = UserRepository(pool)
        result = await repo.delete_user_config("user@example.com")

        assert result is True

    async def test_delete_nonexistent_config(self):
        """存在しないユーザー設定を削除しようとした場合にFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = UserRepository(pool)
        result = await repo.delete_user_config("notfound@example.com")

        assert result is False


# ========================================
# user_workflow_settings テーブルのテスト
# ========================================


class TestCreateUserWorkflowSetting:
    """create_user_workflow_setting のテスト"""

    async def test_create_setting(self):
        """ワークフロー設定を正常に作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "username": "testuser",
            "workflow_definition_id": 1,
            "custom_settings": None,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.create_user_workflow_setting("testuser", 1)

        assert result["workflow_definition_id"] == 1
        conn.fetchrow.assert_awaited_once()

    async def test_create_setting_raises_on_duplicate(self):
        """同一メールアドレスの設定を重複作成した場合にUniqueViolationErrorが伝播することを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UniqueViolationError())

        repo = UserRepository(pool)
        with pytest.raises(asyncpg.UniqueViolationError):
            await repo.create_user_workflow_setting("testuser", 1)


class TestGetUserWorkflowSetting:
    """get_user_workflow_setting のテスト"""

    async def test_returns_setting_when_found(self):
        """ワークフロー設定が存在する場合にレコード辞書を返すことを検証する"""
        pool, conn = _make_pool()
        expected = {
            "username": "testuser",
            "workflow_definition_id": 1,
            "custom_settings": None,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.get_user_workflow_setting("user@example.com")

        assert result is not None
        assert result["workflow_definition_id"] == 1

    async def test_returns_none_when_not_found(self):
        """ワークフロー設定が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = UserRepository(pool)
        result = await repo.get_user_workflow_setting("notfound@example.com")

        assert result is None


class TestUpdateUserWorkflowSetting:
    """update_user_workflow_setting のテスト"""

    async def test_update_setting(self):
        """ワークフロー設定を更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "username": "testuser",
            "workflow_definition_id": 2,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = UserRepository(pool)
        result = await repo.update_user_workflow_setting("user@example.com", 2)

        assert result is not None
        assert result["workflow_definition_id"] == 2

    async def test_returns_none_when_not_found(self):
        """対象ユーザーが存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = UserRepository(pool)
        result = await repo.update_user_workflow_setting("notfound@example.com", 2)

        assert result is None


class TestDeleteUserWorkflowSetting:
    """delete_user_workflow_setting のテスト"""

    async def test_delete_existing_setting(self):
        """存在するワークフロー設定を削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = UserRepository(pool)
        result = await repo.delete_user_workflow_setting("user@example.com")

        assert result is True
        conn.execute.assert_awaited_once()

    async def test_delete_nonexistent_setting(self):
        """存在しないワークフロー設定の削除はFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = UserRepository(pool)
        result = await repo.delete_user_workflow_setting("notfound_user")

        assert result is False

    async def test_username_is_passed_as_is(self):
        """ユーザー名がそのままDELETE文に渡されることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = UserRepository(pool)
        await repo.delete_user_workflow_setting("testuser")

        call_args = conn.execute.call_args
        # インデックス1（位置引数の2番目）がそのまま渡されることを確認する
        assert call_args.args[1] == "testuser"
