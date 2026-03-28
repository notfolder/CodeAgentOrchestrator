"""
認証モジュール

JWT トークンの生成・検証・有効期限管理および
bcrypt によるパスワードハッシュ化と照合を提供する。
FastAPI の依存関数として get_current_user / get_admin_user も提供する。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# JWT設定
_JWT_ALGORITHM = "HS256"
# アクセストークンの有効期限（秒）
ACCESS_TOKEN_EXPIRE_SECONDS = 86400  # 24時間

# bcrypt コストファクタ
_BCRYPT_ROUNDS = 12

# Bearer Token 抽出スキーム
_bearer_scheme = HTTPBearer()


def _get_jwt_secret_key() -> str:
    """
    環境変数 JWT_SECRET_KEY から署名キーを取得する。

    Returns:
        JWT署名キー文字列

    Raises:
        ValueError: JWT_SECRET_KEY が未設定の場合
    """
    secret = os.getenv("JWT_SECRET_KEY", "")
    if not secret:
        raise ValueError("環境変数 JWT_SECRET_KEY が設定されていません")
    return secret


def hash_password(password: str) -> str:
    """
    パスワードを bcrypt でハッシュ化する（コストファクタ12）。

    Args:
        password: 平文パスワード

    Returns:
        bcrypt ハッシュ文字列
    """
    # bcrypt ライブラリを直接使用（passlib との非互換を回避）
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    平文パスワードと bcrypt ハッシュを照合する。

    Args:
        plain_password: 照合する平文パスワード
        hashed_password: 保存済みの bcrypt ハッシュ

    Returns:
        照合成功の場合 True、失敗の場合 False
    """
    # bcrypt ライブラリを直接使用（passlib との非互換を回避）
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def validate_password_strength(password: str) -> None:
    """
    パスワード強度をバリデーションする。

    要件:
    - 8文字以上

    Args:
        password: バリデーション対象のパスワード

    Raises:
        ValueError: パスワードが要件を満たさない場合
    """
    if len(password) < 8:
        raise ValueError("パスワードは8文字以上である必要があります")


def create_access_token(
    username: str,
    role: str,
    expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS,
) -> str:
    """
    JWT アクセストークンを生成する。

    ペイロード:
    - sub: GitLabユーザー名
    - role: ユーザーロール
    - exp: 有効期限（UTC）
    - iat: 発行時刻（UTC）

    Args:
        username: GitLabユーザー名（subject）
        role: ユーザーロール（'admin' または 'user'）
        expires_in: 有効期限（秒）、デフォルト86400秒

    Returns:
        署名済みの JWT 文字列
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(seconds=expires_in)
    payload: dict[str, Any] = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, _get_jwt_secret_key(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    JWT トークンを検証・デコードしてペイロードを返す。

    Args:
        token: 検証する JWT 文字列

    Returns:
        デコードされたペイロード辞書

    Raises:
        HTTPException 401: トークンが無効または有効期限切れの場合
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret_key(), algorithms=[_JWT_ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning("JWTトークンの検証に失敗しました: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証トークンが無効または期限切れです",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """
    Bearer トークンからカレントユーザー情報を取得する FastAPI 依存関数。

    Args:
        credentials: HTTP Authorization ヘッダーから抽出した資格情報

    Returns:
        ユーザー情報辞書（username, role を含む）

    Raises:
        HTTPException 401: トークンが無効な場合
    """
    payload = decode_access_token(credentials.credentials)
    username: str | None = payload.get("sub")
    role: str | None = payload.get("role")

    if not username or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証トークンのペイロードが不正です",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"username": username, "role": role}


async def get_admin_user(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    カレントユーザーが管理者権限を持つことを確認する FastAPI 依存関数。

    Args:
        current_user: get_current_user から取得したユーザー情報

    Returns:
        管理者ユーザー情報辞書

    Raises:
        HTTPException 403: 管理者権限がない場合
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者権限が必要です",
        )
    return current_user
