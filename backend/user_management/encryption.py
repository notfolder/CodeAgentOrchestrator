"""
暗号化モジュール

shared.database.repositories.user_repository に実装済みの
AES-256-GCM 暗号化・復号関数を再エクスポートする薄いラッパー。
auth.py や api.py から統一的にインポートできるようにする。
"""

from shared.database.repositories.user_repository import (
    decrypt_api_key,
    encrypt_api_key,
)

__all__ = ["encrypt_api_key", "decrypt_api_key"]
