"""
暗号化モジュールの単体テスト

AES-256-GCMによるAPIキーの暗号化・復号の正確性と、
不正キーでの復号失敗を検証する。
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from backend.user_management.encryption import decrypt_api_key, encrypt_api_key


class TestEncryptApiKey:
    """encrypt_api_key のテスト"""

    def test_暗号化結果が文字列で返ること(self):
        """暗号化結果が文字列型で返ることを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "a" * 32}):
            result = encrypt_api_key("sk-test-12345")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_暗号化と復号で元の値に戻ること(self):
        """暗号化後に復号すると元のAPIキーに戻ることを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "b" * 32}):
            original = "sk-proj-abcdefghijklmnopqrstuvwxyz"
            encrypted = encrypt_api_key(original)
            decrypted = decrypt_api_key(encrypted)
        assert decrypted == original

    def test_同じキーを2回暗号化すると異なる結果になること(self):
        """ランダムnonceにより同一入力でも毎回異なる暗号化結果になることを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "c" * 32}):
            enc1 = encrypt_api_key("same-key")
            enc2 = encrypt_api_key("same-key")
        assert enc1 != enc2

    def test_32バイト以外のキーでValueErrorが発生すること(self):
        """32バイト以外のENCRYPTION_KEYではValueErrorが発生することを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "short"}):
            with pytest.raises(ValueError, match="32バイト"):
                encrypt_api_key("test")

    def test_キーが未設定の場合ValueErrorが発生すること(self):
        """ENCRYPTION_KEYが未設定の場合にValueErrorが発生することを検証する"""
        env = os.environ.copy()
        env.pop("ENCRYPTION_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
                encrypt_api_key("test")

    def test_空文字列を暗号化できること(self):
        """空文字列のAPIキーを暗号化・復号できることを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "d" * 32}):
            encrypted = encrypt_api_key("")
            decrypted = decrypt_api_key(encrypted)
        assert decrypted == ""


class TestDecryptApiKey:
    """decrypt_api_key のテスト"""

    def test_不正なBase64文字列で復号に失敗すること(self):
        """不正なBase64文字列を渡した場合にエラーが発生することを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "e" * 32}):
            with pytest.raises(Exception):
                decrypt_api_key("not-valid-base64!!!")

    def test_別のキーで復号に失敗すること(self):
        """暗号化に使用したキーと異なるキーで復号するとエラーが発生することを検証する"""
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "f" * 32}):
            encrypted = encrypt_api_key("my-secret-key")

        # 異なるキーで復号しようとするとエラーになること
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "g" * 32}):
            with pytest.raises(Exception):
                decrypt_api_key(encrypted)
