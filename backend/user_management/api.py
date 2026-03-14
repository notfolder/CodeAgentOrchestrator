"""
ユーザー管理 API モジュール

FastAPI の APIRouter を使って以下のエンドポイントを提供する。
- 認証エンドポイント (POST /auth/login, POST /auth/refresh)
- ユーザー管理エンドポイント (GET/POST /users, GET/PUT /config/{email}, PUT /users/{email}/password)
- ワークフロー定義管理エンドポイント (GET/POST/PUT/DELETE /workflow_definitions)
- ユーザー別ワークフロー設定エンドポイント (GET/PUT /users/{user_id}/workflow_setting)
- ダッシュボード統計エンドポイント (GET /dashboard/stats)
- トークン使用量統計エンドポイント (GET /statistics/tokens)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import asyncpg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, field_validator

from shared.database.connection import close_pool, get_pool
from shared.database.repositories.task_repository import TaskRepository
from shared.database.repositories.token_usage_repository import TokenUsageRepository
from shared.database.repositories.user_repository import UserRepository
from shared.database.repositories.workflow_definition_repository import (
    WorkflowDefinitionRepository,
)

from .auth import (
    ACCESS_TOKEN_EXPIRE_SECONDS,
    create_access_token,
    get_admin_user,
    get_current_user,
    hash_password,
    validate_password_strength,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# =====================================================================
# Pydantic スキーマ定義
# =====================================================================


class LoginRequest(BaseModel):
    """ログインリクエストスキーマ"""

    email: str
    password: str


class TokenResponse(BaseModel):
    """トークンレスポンススキーマ"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS


class UserCreateRequest(BaseModel):
    """ユーザー作成リクエストスキーマ"""

    email: str
    username: str
    password: str
    role: str = "user"
    is_active: bool = True
    # LLM設定
    llm_provider: str = "openai"
    api_key: str | None = None
    model_name: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    base_url: str | None = None
    timeout: int = 120
    # コンテキスト圧縮設定
    context_compression_enabled: bool = True
    token_threshold: int | None = None
    keep_recent_messages: int = 10
    min_to_compress: int = 5
    min_compression_ratio: float = 0.8
    # 学習機能設定
    learning_enabled: bool = True
    learning_llm_model: str = "gpt-4o"
    learning_llm_temperature: float = 0.3
    learning_llm_max_tokens: int = 8000
    learning_exclude_bot_comments: bool = True
    learning_only_after_task_start: bool = True

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """パスワード強度バリデーション"""
        validate_password_strength(v)
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """ロールバリデーション"""
        if v not in ("admin", "user"):
            raise ValueError("role は 'admin' または 'user' のみ指定できます")
        return v

    @field_validator("min_compression_ratio")
    @classmethod
    def validate_min_compression_ratio(cls, v: float) -> float:
        """圧縮率バリデーション（0.0〜1.0）"""
        if not 0.0 <= v <= 1.0:
            raise ValueError("min_compression_ratio は 0.0 以上 1.0 以下である必要があります")
        return v

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """temperature バリデーション（0.0〜2.0）"""
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature は 0.0 以上 2.0 以下である必要があります")
        return v


class UserUpdateRequest(BaseModel):
    """ユーザー設定更新リクエストスキーマ"""

    username: str | None = None
    role: str | None = None
    is_active: bool | None = None
    # LLM設定
    llm_provider: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    base_url: str | None = None
    timeout: int | None = None
    # コンテキスト圧縮設定
    context_compression_enabled: bool | None = None
    token_threshold: int | None = None
    keep_recent_messages: int | None = None
    min_to_compress: int | None = None
    min_compression_ratio: float | None = None
    # 学習機能設定
    learning_enabled: bool | None = None
    learning_llm_model: str | None = None
    learning_llm_temperature: float | None = None
    learning_llm_max_tokens: int | None = None
    learning_exclude_bot_comments: bool | None = None
    learning_only_after_task_start: bool | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        """ロールバリデーション"""
        if v is not None and v not in ("admin", "user"):
            raise ValueError("role は 'admin' または 'user' のみ指定できます")
        return v

    @field_validator("min_compression_ratio")
    @classmethod
    def validate_min_compression_ratio(cls, v: float | None) -> float | None:
        """圧縮率バリデーション（0.0〜1.0）"""
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("min_compression_ratio は 0.0 以上 1.0 以下である必要があります")
        return v

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float | None) -> float | None:
        """temperature バリデーション（0.0〜2.0）"""
        if v is not None and not 0.0 <= v <= 2.0:
            raise ValueError("temperature は 0.0 以上 2.0 以下である必要があります")
        return v


class PasswordChangeRequest(BaseModel):
    """パスワード変更リクエストスキーマ"""

    # ユーザー自身による変更時は current_password が必須
    current_password: str | None = None
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        """新パスワード強度バリデーション"""
        validate_password_strength(v)
        return v


class WorkflowDefinitionCreateRequest(BaseModel):
    """ワークフロー定義作成リクエストスキーマ"""

    name: str
    display_name: str
    description: str | None = None
    graph_definition: dict[str, Any]
    agent_definition: dict[str, Any]
    prompt_definition: dict[str, Any]


class WorkflowDefinitionUpdateRequest(BaseModel):
    """ワークフロー定義更新リクエストスキーマ"""

    display_name: str | None = None
    description: str | None = None
    graph_definition: dict[str, Any] | None = None
    agent_definition: dict[str, Any] | None = None
    prompt_definition: dict[str, Any] | None = None
    version: str | None = None
    is_active: bool | None = None


class WorkflowSettingUpdateRequest(BaseModel):
    """ユーザー別ワークフロー設定更新リクエストスキーマ"""

    workflow_definition_id: int


# =====================================================================
# 依存関数: DB プールからリポジトリを生成
# =====================================================================


async def _get_user_repository() -> UserRepository:
    """
    DB プールから UserRepository インスタンスを生成する。

    Returns:
        UserRepository インスタンス
    """
    pool = await get_pool()
    return UserRepository(pool)


async def _get_workflow_definition_repository() -> WorkflowDefinitionRepository:
    """
    DB プールから WorkflowDefinitionRepository インスタンスを生成する。

    Returns:
        WorkflowDefinitionRepository インスタンス
    """
    pool = await get_pool()
    return WorkflowDefinitionRepository(pool)


async def _get_token_usage_repository() -> TokenUsageRepository:
    """
    DB プールから TokenUsageRepository インスタンスを生成する。

    Returns:
        TokenUsageRepository インスタンス
    """
    pool = await get_pool()
    return TokenUsageRepository(pool)


async def _get_task_repository() -> TaskRepository:
    """
    DB プールから TaskRepository インスタンスを生成する。

    Returns:
        TaskRepository インスタンス
    """
    pool = await get_pool()
    return TaskRepository(pool)


# =====================================================================
# 認証エンドポイント (§6.3)
# =====================================================================


@router.post("/auth/login", response_model=TokenResponse, tags=["認証"])
async def login(
    body: LoginRequest,
    user_repo: UserRepository = Depends(_get_user_repository),
) -> TokenResponse:
    """
    ログインしてJWTアクセストークンを発行する。

    メールアドレスとパスワードを照合し、成功した場合はトークンを返す。
    アカウントが無効の場合も認証失敗として扱う。
    """
    user = await user_repo.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="メールアドレスまたはパスワードが正しくありません",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="アカウントが無効化されています",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user["email"], user["role"])
    return TokenResponse(access_token=token)


@router.post("/auth/refresh", response_model=TokenResponse, tags=["認証"])
async def refresh_token(
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> TokenResponse:
    """
    アクセストークンをリフレッシュする。

    現在の有効なトークンからユーザー情報を取得し、新しいトークンを発行する。
    """
    # DB から最新のユーザー情報を取得して role を確認する
    user = await user_repo.get_user_by_email(current_user["email"])
    if not user or not user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザーが存在しないか無効化されています",
        )
    token = create_access_token(user["email"], user["role"])
    return TokenResponse(access_token=token)


# =====================================================================
# ユーザー管理エンドポイント (§6.1)
# =====================================================================


@router.get("/users", tags=["ユーザー管理"])
async def list_users(
    admin: dict[str, Any] = Depends(get_admin_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> list[dict[str, Any]]:
    """
    ユーザー一覧を取得する（管理者専用）。

    email, username, role, is_active, created_at を返す。
    """
    users = await user_repo.list_users()
    return [
        {
            "email": u["email"],
            "username": u["username"],
            "role": u["role"],
            "is_active": u["is_active"],
            "created_at": u["created_at"],
        }
        for u in users
    ]


@router.get("/config/{email}", tags=["ユーザー管理"])
async def get_user_config(
    email: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> dict[str, Any]:
    """
    ユーザー設定を取得する（APIキーは復号済みで返す）。

    一般ユーザーは自分の設定のみ取得可能。
    管理者は全ユーザーの設定を取得可能。
    """
    # 権限チェック: 一般ユーザーは自分自身のみ
    if current_user["role"] != "admin" and current_user["email"] != email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="他のユーザーの設定を取得する権限がありません",
        )

    user = await user_repo.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ユーザーが見つかりません",
        )

    config = await user_repo.get_user_config(email)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ユーザー設定が見つかりません",
        )

    # APIキーを復号して返す
    decrypted_key = await user_repo.get_decrypted_api_key(email)
    result = dict(config)
    # 暗号化済みフィールドを除外して復号済みを設定する
    result.pop("api_key_encrypted", None)
    result["api_key"] = decrypted_key

    return result


@router.post("/users", status_code=status.HTTP_201_CREATED, tags=["ユーザー管理"])
async def create_user(
    body: UserCreateRequest,
    admin: dict[str, Any] = Depends(get_admin_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> dict[str, Any]:
    """
    新規ユーザーを登録する（管理者専用）。

    パスワードは bcrypt でハッシュ化（コストファクタ12）して保存する。
    ユーザー設定（LLM設定、学習機能設定）も同時に作成する。
    """
    password_hash = hash_password(body.password)

    try:
        # users テーブルにユーザーを作成する
        user = await user_repo.create_user(
            email=body.email,
            username=body.username,
            password_hash=password_hash,
            role=body.role,
            is_active=body.is_active,
        )
        # user_configs テーブルに設定を作成する
        await user_repo.create_user_config(
            user_email=body.email,
            llm_provider=body.llm_provider,
            api_key=body.api_key,
            model_name=body.model_name,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            top_p=body.top_p,
            frequency_penalty=body.frequency_penalty,
            presence_penalty=body.presence_penalty,
            base_url=body.base_url,
            timeout=body.timeout,
            context_compression_enabled=body.context_compression_enabled,
            token_threshold=body.token_threshold,
            keep_recent_messages=body.keep_recent_messages,
            min_to_compress=body.min_to_compress,
            min_compression_ratio=body.min_compression_ratio,
            learning_enabled=body.learning_enabled,
            learning_llm_model=body.learning_llm_model,
            learning_llm_temperature=body.learning_llm_temperature,
            learning_llm_max_tokens=body.learning_llm_max_tokens,
            learning_exclude_bot_comments=body.learning_exclude_bot_comments,
            learning_only_after_task_start=body.learning_only_after_task_start,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="指定されたメールアドレスは既に登録されています",
        )

    return {
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
        "is_active": user["is_active"],
        "created_at": user["created_at"],
    }


@router.put("/users/{email}", tags=["ユーザー管理"])
async def update_user(
    email: str,
    body: UserUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> dict[str, Any]:
    """
    ユーザー設定を更新する。

    一般ユーザーは自分の LLM 設定のみ変更可能。
    管理者は全ユーザーの全設定を変更可能。
    """
    is_admin = current_user["role"] == "admin"
    is_self = current_user["email"] == email.lower()

    # 権限チェック
    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="他のユーザーの設定を変更する権限がありません",
        )

    # 一般ユーザーは管理者専用フィールドを変更できない
    if not is_admin:
        if any(v is not None for v in [body.role, body.is_active, body.username]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="一般ユーザーは role, is_active, username を変更できません",
            )

    # ユーザーの存在確認
    user = await user_repo.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ユーザーが見つかりません",
        )

    # users テーブルの更新（管理者のみ）
    if is_admin and any(v is not None for v in [body.username, body.role, body.is_active]):
        updated_user = await user_repo.update_user(
            email,
            username=body.username,
            role=body.role,
            is_active=body.is_active,
        )
        if updated_user:
            user = updated_user

    # user_configs テーブルの更新（LLM設定・学習設定）
    llm_fields = [
        body.llm_provider, body.api_key, body.model_name, body.temperature,
        body.max_tokens, body.top_p, body.frequency_penalty, body.presence_penalty,
        body.base_url, body.timeout, body.context_compression_enabled,
        body.token_threshold, body.keep_recent_messages, body.min_to_compress,
        body.min_compression_ratio, body.learning_enabled, body.learning_llm_model,
        body.learning_llm_temperature, body.learning_llm_max_tokens,
        body.learning_exclude_bot_comments, body.learning_only_after_task_start,
    ]
    if any(v is not None for v in llm_fields):
        await user_repo.update_user_config(
            email,
            llm_provider=body.llm_provider,
            api_key=body.api_key,
            model_name=body.model_name,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            top_p=body.top_p,
            frequency_penalty=body.frequency_penalty,
            presence_penalty=body.presence_penalty,
            base_url=body.base_url,
            timeout=body.timeout,
            context_compression_enabled=body.context_compression_enabled,
            token_threshold=body.token_threshold,
            keep_recent_messages=body.keep_recent_messages,
            min_to_compress=body.min_to_compress,
            min_compression_ratio=body.min_compression_ratio,
            learning_enabled=body.learning_enabled,
            learning_llm_model=body.learning_llm_model,
            learning_llm_temperature=body.learning_llm_temperature,
            learning_llm_max_tokens=body.learning_llm_max_tokens,
            learning_exclude_bot_comments=body.learning_exclude_bot_comments,
            learning_only_after_task_start=body.learning_only_after_task_start,
        )

    return {
        "email": user["email"],
        "username": user["username"],
        "role": user["role"],
        "is_active": user["is_active"],
    }


@router.put("/users/{email}/password", tags=["ユーザー管理"])
async def change_password(
    email: str,
    body: PasswordChangeRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> dict[str, str]:
    """
    パスワードを変更する。

    一般ユーザーは自分のパスワードのみ変更可能（current_password 必須）。
    管理者は全ユーザーのパスワードを代理変更可能（current_password 不要）。
    """
    is_admin = current_user["role"] == "admin"
    is_self = current_user["email"] == email.lower()

    # 権限チェック
    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="他のユーザーのパスワードを変更する権限がありません",
        )

    # ユーザーの存在確認
    user = await user_repo.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ユーザーが見つかりません",
        )

    # 管理者以外のパスワード変更時は current_password が必須
    if not is_admin:
        if not body.current_password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="現在のパスワード (current_password) が必要です",
            )
        if not verify_password(body.current_password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="現在のパスワードが正しくありません",
            )

    new_hash = hash_password(body.new_password)
    # password_hash を直接更新する（update_user は password を持たないため直接実行）
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE email = $2",
            new_hash,
            email.lower(),
        )

    return {"message": "パスワードを変更しました"}


# =====================================================================
# ワークフロー定義管理エンドポイント (§6.2)
# =====================================================================


@router.get("/workflow_definitions", tags=["ワークフロー定義"])
async def list_workflow_definitions(
    current_user: dict[str, Any] = Depends(get_current_user),
    wf_repo: WorkflowDefinitionRepository = Depends(_get_workflow_definition_repository),
) -> list[dict[str, Any]]:
    """
    ワークフロー定義一覧を取得する。
    """
    definitions = await wf_repo.list_workflow_definitions()
    return [_serialize_workflow_definition(d) for d in definitions]


@router.get("/workflow_definitions/{definition_id}", tags=["ワークフロー定義"])
async def get_workflow_definition(
    definition_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
    wf_repo: WorkflowDefinitionRepository = Depends(_get_workflow_definition_repository),
) -> dict[str, Any]:
    """
    ワークフロー定義を ID で取得する。
    """
    definition = await wf_repo.get_workflow_definition(definition_id)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー定義が見つかりません",
        )
    return _serialize_workflow_definition(definition)


@router.post(
    "/workflow_definitions",
    status_code=status.HTTP_201_CREATED,
    tags=["ワークフロー定義"],
)
async def create_workflow_definition(
    body: WorkflowDefinitionCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    wf_repo: WorkflowDefinitionRepository = Depends(_get_workflow_definition_repository),
) -> dict[str, Any]:
    """
    ワークフロー定義を新規作成する。

    作成者は現在のユーザーのメールアドレスで記録される。
    """
    try:
        definition = await wf_repo.create_workflow_definition(
            name=body.name,
            display_name=body.display_name,
            graph_definition=body.graph_definition,
            agent_definition=body.agent_definition,
            prompt_definition=body.prompt_definition,
            description=body.description,
            is_preset=False,
            created_by=current_user["email"],
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一名称のワークフロー定義が既に存在します",
        )
    return _serialize_workflow_definition(definition)


@router.put("/workflow_definitions/{definition_id}", tags=["ワークフロー定義"])
async def update_workflow_definition(
    definition_id: int,
    body: WorkflowDefinitionUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    wf_repo: WorkflowDefinitionRepository = Depends(_get_workflow_definition_repository),
) -> dict[str, Any]:
    """
    ワークフロー定義を更新する。

    システムプリセット（is_preset=True）の定義は更新できない。
    """
    # 存在確認とプリセットチェック
    existing = await wf_repo.get_workflow_definition(definition_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー定義が見つかりません",
        )
    if existing.get("is_preset"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="システムプリセットのワークフロー定義は変更できません",
        )

    updated = await wf_repo.update_workflow_definition(
        definition_id,
        display_name=body.display_name,
        description=body.description,
        graph_definition=body.graph_definition,
        agent_definition=body.agent_definition,
        prompt_definition=body.prompt_definition,
        version=body.version,
        is_active=body.is_active,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー定義が見つかりません",
        )
    return _serialize_workflow_definition(updated)


@router.delete(
    "/workflow_definitions/{definition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["ワークフロー定義"],
)
async def delete_workflow_definition(
    definition_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
    wf_repo: WorkflowDefinitionRepository = Depends(_get_workflow_definition_repository),
) -> None:
    """
    ワークフロー定義を削除する。

    システムプリセット（is_preset=True）の定義は削除できない。
    """
    existing = await wf_repo.get_workflow_definition(definition_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー定義が見つかりません",
        )
    if existing.get("is_preset"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="システムプリセットのワークフロー定義は削除できません",
        )

    deleted = await wf_repo.delete_workflow_definition(definition_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー定義が見つかりません",
        )


# =====================================================================
# ユーザー別ワークフロー設定エンドポイント (§6.4)
# =====================================================================


@router.get("/users/{user_id}/workflow_setting", tags=["ワークフロー設定"])
async def get_user_workflow_setting(
    user_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(_get_user_repository),
) -> dict[str, Any]:
    """
    ユーザーのワークフロー設定を取得する。

    user_id はメールアドレス。一般ユーザーは自分の設定のみ取得可能。
    """
    is_admin = current_user["role"] == "admin"
    is_self = current_user["email"] == user_id.lower()

    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="他のユーザーのワークフロー設定を取得する権限がありません",
        )

    setting = await user_repo.get_user_workflow_setting(user_id)
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー設定が見つかりません",
        )
    return dict(setting)


@router.put("/users/{user_id}/workflow_setting", tags=["ワークフロー設定"])
async def update_user_workflow_setting(
    user_id: str,
    body: WorkflowSettingUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    user_repo: UserRepository = Depends(_get_user_repository),
    wf_repo: WorkflowDefinitionRepository = Depends(_get_workflow_definition_repository),
) -> dict[str, Any]:
    """
    ユーザーのワークフロー設定を更新する。

    user_id はメールアドレス。一般ユーザーは自分の設定のみ更新可能。
    指定されたワークフロー定義IDが存在しない場合は 404 を返す。
    ワークフロー設定が未作成の場合は新規作成する。
    """
    is_admin = current_user["role"] == "admin"
    is_self = current_user["email"] == user_id.lower()

    if not is_admin and not is_self:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="他のユーザーのワークフロー設定を変更する権限がありません",
        )

    # ワークフロー定義の存在確認
    definition = await wf_repo.get_workflow_definition(body.workflow_definition_id)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたワークフロー定義が見つかりません",
        )

    # 既存設定があれば更新、なければ新規作成する
    existing = await user_repo.get_user_workflow_setting(user_id)
    if existing:
        setting = await user_repo.update_user_workflow_setting(
            user_id,
            body.workflow_definition_id,
        )
    else:
        setting = await user_repo.create_user_workflow_setting(
            user_id,
            body.workflow_definition_id,
        )

    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ワークフロー設定の更新に失敗しました",
        )
    return dict(setting)


# =====================================================================
# ダッシュボード統計エンドポイント
# =====================================================================


@router.get("/dashboard/stats", tags=["ダッシュボード"])
async def get_dashboard_stats(
    admin: dict[str, Any] = Depends(get_admin_user),
    user_repo: UserRepository = Depends(_get_user_repository),
    task_repo: TaskRepository = Depends(_get_task_repository),
    token_repo: TokenUsageRepository = Depends(_get_token_usage_repository),
) -> dict[str, Any]:
    """
    ダッシュボード統計情報を取得する（管理者専用）。

    - 登録ユーザー数
    - 実行中タスク数
    - 今月のトークン使用量合計
    - 最近のタスク一覧（最新10件）
    """
    # 登録ユーザー数を取得する
    all_users = await user_repo.list_users()
    user_count = len(all_users)

    # 実行中タスク数を取得する
    running_tasks = await task_repo.list_tasks(status="running", limit=1000)
    running_task_count = len(running_tasks)

    # 今月のトークン使用量を取得する（全ユーザー合計）
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM token_usage
            WHERE created_at >= date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
            """
        )
    monthly_tokens = {
        "prompt_tokens": int(row["prompt_tokens"]),
        "completion_tokens": int(row["completion_tokens"]),
        "total_tokens": int(row["total_tokens"]),
    }

    # 最近のタスク一覧を取得する（最新10件）
    recent_tasks = await task_repo.list_tasks(limit=10)

    return {
        "user_count": user_count,
        "running_task_count": running_task_count,
        "monthly_token_usage": monthly_tokens,
        "recent_tasks": [
            {
                "uuid": t["uuid"],
                "task_type": t["task_type"],
                "task_identifier": t["task_identifier"],
                "repository": t["repository"],
                "user_email": t["user_email"],
                "status": t["status"],
                "created_at": t["created_at"],
            }
            for t in recent_tasks
        ],
    }


# =====================================================================
# トークン使用量統計エンドポイント
# =====================================================================


@router.get("/statistics/tokens", tags=["統計"])
async def get_token_statistics(
    user_email: str | None = Query(default=None, description="フィルタリングするユーザーメールアドレス"),
    period: int = Query(default=30, ge=1, description="集計期間（日数）"),
    admin: dict[str, Any] = Depends(get_admin_user),
) -> dict[str, Any]:
    """
    トークン使用量統計を取得する（管理者専用）。

    ユーザー別にトークン使用量を集計して返す。
    user_email を指定した場合はそのユーザーのみ集計する。
    period で集計期間（日数）を指定する（デフォルト30日）。
    """
    pool = await get_pool()

    # ユーザー別トークン使用量集計クエリ
    if user_email:
        # 特定ユーザーの集計
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    user_email,
                    COUNT(*) AS call_count,
                    SUM(prompt_tokens) AS prompt_tokens,
                    SUM(completion_tokens) AS completion_tokens,
                    SUM(total_tokens) AS total_tokens
                FROM token_usage
                WHERE user_email = $1
                  AND created_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - ($2 || ' days')::INTERVAL)
                GROUP BY user_email
                ORDER BY total_tokens DESC
                """,
                user_email.lower(),
                str(period),
            )
    else:
        # 全ユーザーの集計
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    user_email,
                    COUNT(*) AS call_count,
                    SUM(prompt_tokens) AS prompt_tokens,
                    SUM(completion_tokens) AS completion_tokens,
                    SUM(total_tokens) AS total_tokens
                FROM token_usage
                WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - ($1 || ' days')::INTERVAL)
                GROUP BY user_email
                ORDER BY total_tokens DESC
                """,
                str(period),
            )

    return {
        "period_days": period,
        "user_email_filter": user_email,
        "stats": [
            {
                "user_email": row["user_email"],
                "call_count": int(row["call_count"]),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"]),
            }
            for row in rows
        ],
    }


# =====================================================================
# ヘルパー関数
# =====================================================================


def _serialize_workflow_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """
    ワークフロー定義レコードをシリアライズして返す。

    JSONB カラム（graph_definition, agent_definition, prompt_definition）は
    asyncpg が自動的に Python 辞書型に変換するが、
    文字列として返ってくる場合に備えて辞書型に変換する。

    Args:
        definition: ワークフロー定義レコード辞書

    Returns:
        シリアライズされたワークフロー定義辞書
    """
    import json

    result = dict(definition)
    for key in ("graph_definition", "agent_definition", "prompt_definition"):
        val = result.get(key)
        if isinstance(val, str):
            result[key] = json.loads(val)
    return result


# =====================================================================
# FastAPI アプリケーション生成
# =====================================================================


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI アプリケーションのライフサイクル管理。

    起動時に DB 接続プールを初期化し、
    終了時に接続プールを閉じる。
    """
    logger.info("ユーザー管理 API を起動しています...")
    await get_pool()
    logger.info("DB接続プールを初期化しました")
    yield
    logger.info("ユーザー管理 API をシャットダウンしています...")
    await close_pool()
    logger.info("DB接続プールを閉じました")


def create_app() -> FastAPI:
    """
    FastAPI アプリケーションを生成して返す。

    DB 接続プールの初期化・終了を lifespan で管理する。

    Returns:
        設定済みの FastAPI アプリケーションインスタンス
    """
    app = FastAPI(
        title="AutomataCodex ユーザー管理 API",
        description="ユーザー管理・認証・ワークフロー定義管理を提供するAPIサーバー",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.include_router(router)
    return app
