"""
ユーザーリポジトリ

usersテーブルおよびuser_configsテーブルへのCRUD操作を提供する。
APIキーの暗号化・復号は本クラス内で透過的に処理する。
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any

import asyncpg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# AES-GCMのnonce（ナンス）バイト長
_NONCE_BYTES = 12


def _get_encryption_key() -> bytes:
    """
    環境変数 ENCRYPTION_KEY から32バイトの暗号化キーを取得する。

    Returns:
        32バイトのキー

    Raises:
        ValueError: キーが未設定または長さが不正な場合
    """
    raw = os.getenv("ENCRYPTION_KEY", "")
    if not raw:
        raise ValueError("環境変数 ENCRYPTION_KEY が設定されていません")
    key_bytes = raw.encode("utf-8")
    if len(key_bytes) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY は32バイトである必要があります（現在: {len(key_bytes)}バイト）"
        )
    return key_bytes


def encrypt_api_key(plaintext: str) -> str:
    """
    APIキーをAES-256-GCMで暗号化し、Base64エンコードされた文字列を返す。

    暗号化データの形式: Base64(nonce + ciphertext + tag)

    Args:
        plaintext: 暗号化対象のAPIキー文字列

    Returns:
        Base64エンコードされた暗号化文字列
    """
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # nonce + ciphertext（tagを含む）をBase64エンコードして保存する
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_api_key(encrypted: str) -> str:
    """
    Base64エンコードされた暗号化APIキーを復号する。

    Args:
        encrypted: encrypt_api_key()で生成した暗号化文字列

    Returns:
        復号されたAPIキー文字列

    Raises:
        cryptography.exceptions.InvalidTag: 復号失敗（改ざん検出）時
    """
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(encrypted.encode("utf-8"))
    nonce = raw[:_NONCE_BYTES]
    ciphertext = raw[_NONCE_BYTES:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


class UserRepository:
    """
    ユーザーリポジトリクラス

    usersテーブルおよびuser_configsテーブルへのCRUD操作を提供する。
    api_key_encrypted カラムの暗号化・復号は本クラス内で透過的に処理する。
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """
        Args:
            pool: asyncpg接続プール
        """
        self._pool = pool

    # ===========================
    # users テーブル操作
    # ===========================

    async def create_user(
        self,
        email: str,
        username: str,
        password_hash: str,
        role: str = "user",
        is_active: bool = True,
    ) -> dict[str, Any]:
        """
        ユーザーを作成する。

        メールアドレスは小文字に正規化して保存する。

        Args:
            email: メールアドレス（一意識別子）
            username: ユーザー表示名
            password_hash: bcryptハッシュ済みパスワード
            role: ユーザーロール（'admin' または 'user'）
            is_active: アカウント有効状態

        Returns:
            作成したユーザーのレコード辞書

        Raises:
            asyncpg.UniqueViolationError: メールアドレスが重複する場合
        """
        normalized_email = email.lower()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, username, password_hash, role, is_active)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                normalized_email,
                username,
                password_hash,
                role,
                is_active,
            )
        return dict(row)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """
        メールアドレスでユーザーを取得する。

        Args:
            email: メールアドレス

        Returns:
            ユーザーレコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1",
                email.lower(),
            )
        return dict(row) if row else None

    async def update_user(
        self,
        email: str,
        *,
        username: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        """
        ユーザー情報を更新する。

        Args:
            email: 更新対象のメールアドレス
            username: 新しいユーザー表示名（Noneの場合は更新しない）
            role: 新しいロール（Noneの場合は更新しない）
            is_active: 新しい有効状態（Noneの場合は更新しない）

        Returns:
            更新後のユーザーレコード辞書。対象が存在しない場合はNone。
        """
        fields: list[str] = []
        values: list[Any] = []
        idx = 1

        if username is not None:
            fields.append(f"username = ${idx}")
            values.append(username)
            idx += 1
        if role is not None:
            fields.append(f"role = ${idx}")
            values.append(role)
            idx += 1
        if is_active is not None:
            fields.append(f"is_active = ${idx}")
            values.append(is_active)
            idx += 1

        if not fields:
            return await self.get_user_by_email(email)

        fields.append(f"updated_at = ${idx}")
        values.append(datetime.now(timezone.utc))
        idx += 1
        values.append(email.lower())

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE users SET {', '.join(fields)} WHERE email = ${idx} RETURNING *",
                *values,
            )
        return dict(row) if row else None

    async def delete_user(self, email: str) -> bool:
        """
        ユーザーを削除する。

        CASCADE設定により、関連する全レコードも削除される。

        Args:
            email: 削除対象のメールアドレス

        Returns:
            削除に成功した場合はTrue、対象が存在しない場合はFalse。
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM users WHERE email = $1",
                email.lower(),
            )
        return result == "DELETE 1"

    async def list_users(
        self,
        *,
        is_active: bool | None = None,
        role: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        ユーザー一覧を取得する。

        Args:
            is_active: 有効状態でフィルタリング（Noneの場合はすべて取得）
            role: ロールでフィルタリング（Noneの場合はすべて取得）
            limit: 取得件数上限
            offset: 取得開始位置

        Returns:
            ユーザーレコード辞書のリスト
        """
        conditions: list[str] = []
        values: list[Any] = []
        idx = 1

        if is_active is not None:
            conditions.append(f"is_active = ${idx}")
            values.append(is_active)
            idx += 1
        if role is not None:
            conditions.append(f"role = ${idx}")
            values.append(role)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM users
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *values,
            )
        return [dict(row) for row in rows]

    # ===========================
    # user_configs テーブル操作
    # ===========================

    async def create_user_config(
        self,
        user_email: str,
        *,
        llm_provider: str = "openai",
        api_key: str | None = None,
        model_name: str = "gpt-4o",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        base_url: str | None = None,
        timeout: int = 120,
        context_compression_enabled: bool = True,
        token_threshold: int | None = None,
        keep_recent_messages: int = 10,
        min_to_compress: int = 5,
        min_compression_ratio: float = 0.8,
        learning_enabled: bool = True,
        learning_llm_model: str = "gpt-4o",
        learning_llm_temperature: float = 0.3,
        learning_llm_max_tokens: int = 8000,
        learning_exclude_bot_comments: bool = True,
        learning_only_after_task_start: bool = True,
    ) -> dict[str, Any]:
        """
        ユーザー設定を作成する。

        api_keyが指定された場合はAES-256-GCMで暗号化して保存する。

        Args:
            user_email: ユーザーメールアドレス
            llm_provider: LLMプロバイダ名
            api_key: 平文APIキー（暗号化して保存される）
            model_name: 使用モデル名
            temperature: LLM温度パラメータ
            max_tokens: 最大トークン数
            top_p: Top-pサンプリングパラメータ
            frequency_penalty: 頻度ペナルティ
            presence_penalty: 存在ペナルティ
            base_url: カスタムエンドポイントURL
            timeout: APIタイムアウト秒数
            context_compression_enabled: コンテキスト圧縮有効フラグ
            token_threshold: 圧縮開始閾値トークン数
            keep_recent_messages: 最新から保持するメッセージ数
            min_to_compress: 圧縮する最小メッセージ数
            min_compression_ratio: 圧縮率の最小値
            learning_enabled: 学習機能有効フラグ
            learning_llm_model: 学習用LLMモデル名
            learning_llm_temperature: 学習用LLM温度パラメータ
            learning_llm_max_tokens: 学習用最大トークン数
            learning_exclude_bot_comments: Botコメントを学習対象から除外するか
            learning_only_after_task_start: タスク開始後のコメントのみ学習対象とするか

        Returns:
            作成したuser_configsレコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一メールアドレスの設定が既に存在する場合
        """
        api_key_encrypted: str | None = None
        if api_key:
            api_key_encrypted = encrypt_api_key(api_key)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_configs (
                    user_email, llm_provider, api_key_encrypted, model_name,
                    temperature, max_tokens, top_p, frequency_penalty, presence_penalty,
                    base_url, timeout, context_compression_enabled, token_threshold,
                    keep_recent_messages, min_to_compress, min_compression_ratio,
                    learning_enabled, learning_llm_model, learning_llm_temperature,
                    learning_llm_max_tokens, learning_exclude_bot_comments,
                    learning_only_after_task_start
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16,
                    $17, $18, $19,
                    $20, $21,
                    $22
                )
                RETURNING *
                """,
                user_email.lower(),
                llm_provider,
                api_key_encrypted,
                model_name,
                temperature,
                max_tokens,
                top_p,
                frequency_penalty,
                presence_penalty,
                base_url,
                timeout,
                context_compression_enabled,
                token_threshold,
                keep_recent_messages,
                min_to_compress,
                min_compression_ratio,
                learning_enabled,
                learning_llm_model,
                learning_llm_temperature,
                learning_llm_max_tokens,
                learning_exclude_bot_comments,
                learning_only_after_task_start,
            )
        return dict(row)

    async def get_user_config(self, user_email: str) -> dict[str, Any] | None:
        """
        ユーザー設定を取得する。

        api_key_encryptedは暗号化されたまま返す（復号には get_decrypted_api_key を使用する）。

        Args:
            user_email: ユーザーメールアドレス

        Returns:
            user_configsレコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_configs WHERE user_email = $1",
                user_email.lower(),
            )
        return dict(row) if row else None

    async def get_decrypted_api_key(self, user_email: str) -> str | None:
        """
        ユーザーのAPIキーを復号して返す。

        Args:
            user_email: ユーザーメールアドレス

        Returns:
            復号されたAPIキー文字列。設定が存在しない、またはAPIキー未設定の場合はNone。
        """
        config = await self.get_user_config(user_email)
        if not config or not config.get("api_key_encrypted"):
            return None
        return decrypt_api_key(config["api_key_encrypted"])

    async def update_user_config(
        self,
        user_email: str,
        *,
        llm_provider: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        context_compression_enabled: bool | None = None,
        token_threshold: int | None = None,
        keep_recent_messages: int | None = None,
        min_to_compress: int | None = None,
        min_compression_ratio: float | None = None,
        learning_enabled: bool | None = None,
        learning_llm_model: str | None = None,
        learning_llm_temperature: float | None = None,
        learning_llm_max_tokens: int | None = None,
        learning_exclude_bot_comments: bool | None = None,
        learning_only_after_task_start: bool | None = None,
    ) -> dict[str, Any] | None:
        """
        ユーザー設定を更新する。

        api_keyが指定された場合はAES-256-GCMで暗号化して保存する。
        Noneを指定したフィールドは更新されない。

        Args:
            user_email: ユーザーメールアドレス
            その他の引数: 更新するフィールドと値

        Returns:
            更新後のuser_configsレコード辞書。対象が存在しない場合はNone。
        """
        fields: list[str] = []
        values: list[Any] = []
        idx = 1

        # フィールド更新マッピング
        field_map: dict[str, Any] = {
            "llm_provider": llm_provider,
            "model_name": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "base_url": base_url,
            "timeout": timeout,
            "context_compression_enabled": context_compression_enabled,
            "token_threshold": token_threshold,
            "keep_recent_messages": keep_recent_messages,
            "min_to_compress": min_to_compress,
            "min_compression_ratio": min_compression_ratio,
            "learning_enabled": learning_enabled,
            "learning_llm_model": learning_llm_model,
            "learning_llm_temperature": learning_llm_temperature,
            "learning_llm_max_tokens": learning_llm_max_tokens,
            "learning_exclude_bot_comments": learning_exclude_bot_comments,
            "learning_only_after_task_start": learning_only_after_task_start,
        }

        for field_name, value in field_map.items():
            if value is not None:
                fields.append(f"{field_name} = ${idx}")
                values.append(value)
                idx += 1

        # APIキーは暗号化してから設定する
        if api_key is not None:
            fields.append(f"api_key_encrypted = ${idx}")
            values.append(encrypt_api_key(api_key))
            idx += 1

        if not fields:
            return await self.get_user_config(user_email)

        fields.append(f"updated_at = ${idx}")
        values.append(datetime.now(timezone.utc))
        idx += 1
        values.append(user_email.lower())

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE user_configs SET {', '.join(fields)} WHERE user_email = ${idx} RETURNING *",
                *values,
            )
        return dict(row) if row else None

    async def delete_user_config(self, user_email: str) -> bool:
        """
        ユーザー設定を削除する。

        Args:
            user_email: ユーザーメールアドレス

        Returns:
            削除に成功した場合はTrue、対象が存在しない場合はFalse。
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM user_configs WHERE user_email = $1",
                user_email.lower(),
            )
        return result == "DELETE 1"

    # ===========================
    # user_workflow_settings テーブル操作
    # ===========================

    async def create_user_workflow_setting(
        self,
        user_email: str,
        workflow_definition_id: int,
        custom_settings: str | None = None,
    ) -> dict[str, Any]:
        """
        ユーザーのワークフロー設定を作成する。

        Args:
            user_email: ユーザーメールアドレス
            workflow_definition_id: ワークフロー定義ID
            custom_settings: ユーザー固有の追加設定（JSON文字列）

        Returns:
            作成したuser_workflow_settingsレコード辞書

        Raises:
            asyncpg.UniqueViolationError: 同一ユーザーの設定が既に存在する場合
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_workflow_settings
                    (user_email, workflow_definition_id, custom_settings)
                VALUES ($1, $2, $3)
                RETURNING *
                """,
                user_email.lower(),
                workflow_definition_id,
                custom_settings,
            )
        return dict(row)

    async def get_user_workflow_setting(self, user_email: str) -> dict[str, Any] | None:
        """
        ユーザーのワークフロー設定を取得する。

        Args:
            user_email: ユーザーメールアドレス

        Returns:
            user_workflow_settingsレコード辞書。存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_workflow_settings WHERE user_email = $1",
                user_email.lower(),
            )
        return dict(row) if row else None

    async def update_user_workflow_setting(
        self,
        user_email: str,
        workflow_definition_id: int,
        custom_settings: str | None = None,
    ) -> dict[str, Any] | None:
        """
        ユーザーのワークフロー設定を更新する。

        Args:
            user_email: ユーザーメールアドレス
            workflow_definition_id: 新しいワークフロー定義ID
            custom_settings: ユーザー固有の追加設定（JSON文字列）

        Returns:
            更新後のuser_workflow_settingsレコード辞書。対象が存在しない場合はNone。
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE user_workflow_settings
                SET workflow_definition_id = $1,
                    custom_settings = $2,
                    updated_at = $3
                WHERE user_email = $4
                RETURNING *
                """,
                workflow_definition_id,
                custom_settings,
                datetime.now(timezone.utc),
                user_email.lower(),
            )
        return dict(row) if row else None
