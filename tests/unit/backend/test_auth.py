"""
認証モジュールの単体テスト

JWTトークン生成・検証・有効期限切れを検証する。
また、パスワードのbcryptハッシュ化と照合を検証する。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.user_management.auth import (
    ACCESS_TOKEN_EXPIRE_SECONDS,
    create_access_token,
    decode_access_token,
    get_admin_user,
    get_current_user,
    hash_password,
    validate_password_strength,
    verify_password,
)


# =====================================================================
# パスワードハッシュ化・照合のテスト
# =====================================================================


class TestHashPassword:
    """hash_password のテスト"""

    def test_ハッシュが文字列で返ること(self):
        """bcryptハッシュ結果が文字列で返ることを検証する"""
        result = hash_password("TestPass1!")
        assert isinstance(result, str)
        # bcryptハッシュは$2b$で始まる
        assert result.startswith("$2b$") or result.startswith("$2a$")

    def test_同じパスワードでも毎回異なるハッシュになること(self):
        """ソルト付きbcryptにより同一パスワードでも毎回異なるハッシュになることを検証する"""
        hash1 = hash_password("TestPass1!")
        hash2 = hash_password("TestPass1!")
        assert hash1 != hash2


class TestVerifyPassword:
    """verify_password のテスト"""

    def test_正しいパスワードで照合成功すること(self):
        """正しいパスワードとハッシュが照合成功することを検証する"""
        password = "CorrectPass1!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_誤ったパスワードで照合失敗すること(self):
        """誤ったパスワードとハッシュが照合失敗することを検証する"""
        hashed = hash_password("CorrectPass1!")
        assert verify_password("WrongPass1!", hashed) is False

    def test_空文字列で照合失敗すること(self):
        """空文字列は正規のハッシュと照合失敗することを検証する"""
        hashed = hash_password("ValidPass1!")
        assert verify_password("", hashed) is False


# =====================================================================
# パスワード強度バリデーションのテスト
# =====================================================================


class TestValidatePasswordStrength:
    """validate_password_strength のテスト"""

    def test_8文字以上で例外が発生しないこと(self):
        """8文字以上のパスワードでValueErrorが発生しないことを検証する"""
        validate_password_strength("password")  # 例外なし

    def test_8文字未満でValueErrorが発生すること(self):
        """8文字未満のパスワードでValueErrorが発生することを検証する"""
        with pytest.raises(ValueError, match="8文字"):
            validate_password_strength("short")

    def test_ちょうど8文字で例外が発生しないこと(self):
        """ちょうど8文字のパスワードで例外が発生しないことを検証する"""
        validate_password_strength("12345678")  # 例外なし

    def test_空文字列でValueErrorが発生すること(self):
        """空文字列のパスワードでValueErrorが発生することを検証する"""
        with pytest.raises(ValueError, match="8文字"):
            validate_password_strength("")

    @pytest.mark.parametrize(
        "password",
        [
            "password",  # ちょうど8文字
            "longerpassword",  # 長いパスワード
            "12345678",  # 数字のみ8文字
            "ValidPass1!",  # 英字+数字+記号
        ],
    )
    def test_8文字以上の様々なパターンが通ること(self, password: str):
        """8文字以上の様々なパスワードパターンでValueErrorが発生しないことを検証する"""
        validate_password_strength(password)  # 例外なし


# =====================================================================
# JWTトークン生成・検証のテスト
# =====================================================================


class TestCreateAccessToken:
    """create_access_token のテスト"""

    def test_トークンが文字列で返ること(self):
        """JWTトークンが文字列で返ることを検証する"""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key"}):
            token = create_access_token("testuser", "user")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_トークンが3つのピリオド区切りであること(self):
        """JWTトークンがheader.payload.signatureの形式であることを検証する"""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key"}):
            token = create_access_token("testuser", "user")
        parts = token.split(".")
        assert len(parts) == 3

    def test_JWT_SECRET_KEY未設定でValueErrorが発生すること(self):
        """JWT_SECRET_KEYが未設定の場合にValueErrorが発生することを検証する"""
        env = os.environ.copy()
        env.pop("JWT_SECRET_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
                create_access_token("testuser", "user")


class TestDecodeAccessToken:
    """decode_access_token のテスト"""

    def test_正常なトークンをデコードできること(self):
        """生成したトークンを正しくデコードしてペイロードが取得できることを検証する"""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key-32chars"}):
            token = create_access_token("admin", "admin")
            payload = decode_access_token(token)
        assert payload["sub"] == "admin"
        assert payload["role"] == "admin"

    def test_不正なトークンで401エラーが発生すること(self):
        """不正なトークン文字列でHTTP 401エラーが発生することを検証する"""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key"}):
            with pytest.raises(HTTPException) as exc_info:
                decode_access_token("invalid.token.string")
        assert exc_info.value.status_code == 401

    def test_有効期限切れトークンで401エラーが発生すること(self):
        """有効期限切れのトークンでHTTP 401エラーが発生することを検証する"""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key"}):
            # 有効期限を-1秒にしてすでに期限切れのトークンを生成する
            token = create_access_token("testuser", "user", expires_in=-1)
            with pytest.raises(HTTPException) as exc_info:
                decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_異なるキーで署名されたトークンで401エラーが発生すること(self):
        """異なるキーで署名されたトークンの検証に失敗することを検証する"""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "original-key-xxxxxxxxxxxxx"}):
            token = create_access_token("testuser", "user")

        with patch.dict(os.environ, {"JWT_SECRET_KEY": "different-key-xxxxxxxxxxxx"}):
            with pytest.raises(HTTPException) as exc_info:
                decode_access_token(token)
        assert exc_info.value.status_code == 401


# =====================================================================
# FastAPI 依存関数のテスト
# =====================================================================


class TestGetCurrentUser:
    """get_current_user のテスト"""

    async def test_有効なトークンからユーザー情報を取得できること(self):
        """有効なBearerトークンからユーザー情報が取得できることを検証する"""
        from fastapi.security import HTTPAuthorizationCredentials

        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key-xyz"}):
            token = create_access_token("testuser", "user")
            credentials = HTTPAuthorizationCredentials(
                scheme="bearer", credentials=token
            )
            result = await get_current_user(credentials)

        assert result["username"] == "testuser"
        assert result["role"] == "user"

    async def test_不正なトークンで401エラーが発生すること(self):
        """不正なトークンでHTTP 401エラーが発生することを検証する"""
        from fastapi.security import HTTPAuthorizationCredentials

        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret-key-xyz"}):
            credentials = HTTPAuthorizationCredentials(
                scheme="bearer", credentials="invalid-token"
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials)

        assert exc_info.value.status_code == 401


class TestGetAdminUser:
    """get_admin_user のテスト"""

    async def test_管理者ユーザーで通過できること(self):
        """roleがadminのユーザー情報で403エラーが発生しないことを検証する"""
        admin_user = {"username": "admin", "role": "admin"}
        result = await get_admin_user(admin_user)
        assert result["role"] == "admin"

    async def test_一般ユーザーで403エラーが発生すること(self):
        """roleがuserのユーザー情報でHTTP 403エラーが発生することを検証する"""
        user = {"username": "testuser", "role": "user"}
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user(user)
        assert exc_info.value.status_code == 403
