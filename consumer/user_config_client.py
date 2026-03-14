"""
UserConfigClient モジュール

ConsumerコンテナがUSER_CONFIG_API_URL経由でUser Config APIへHTTPで問い合わせる
クライアントを提供する。ユーザーのLLM設定・APIキー取得に使用し、
AgentFactoryとUserResolverExecutorが依存する。

IMPLEMENTATION_PLAN.md フェーズ6-2、USER_MANAGEMENT_SPEC.md § 6.1 に準拠する。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class UserConfig:
    """
    ユーザー設定データクラス

    User Config APIから取得したユーザー別設定を保持する。

    Attributes:
        email: ユーザーのメールアドレス
        llm_provider: LLMプロバイダー（openai/azure/ollama/lmstudio）
        model_name: 使用モデル名
        api_key: LLM APIキー（復号化済み）
        temperature: 生成温度
        max_tokens: 最大生成トークン数
        base_url: OpenAI互換エンドポイントURL（Ollama/LM Studio用）
        learning_enabled: 学習機能の有効フラグ
        learning_llm_model: 学習判断用LLMモデル
        learning_llm_temperature: 学習用LLM温度
        learning_llm_max_tokens: 学習用LLM最大トークン数
        learning_exclude_bot_comments: Botコメントを除外するフラグ
        learning_only_after_task_start: タスク開始後コメントのみ対象とするフラグ
        workflow_definition_id: ユーザーが選択中のワークフロー定義ID
    """

    def __init__(self, data: dict[str, Any]) -> None:
        """
        ユーザー設定を辞書から初期化する。

        Args:
            data: User Config APIから取得したユーザー設定辞書
        """
        self.email: str = data.get("email", "")
        self.llm_provider: str = data.get("llm_provider", "openai")
        self.model_name: str = data.get("model_name", "gpt-4o")
        self.api_key: str = data.get("api_key", "")
        self.temperature: float = float(data.get("temperature", 0.2))
        self.max_tokens: int = int(data.get("max_tokens", 4096))
        self.base_url: str | None = data.get("base_url")
        # base_urlはOllama/LM Studio等のOpenAI互換エンドポイントURL。
        # Noneの場合はプロバイダーのデフォルトURLが使用される（OpenAIの場合はhttps://api.openai.com/v1）。
        # 学習機能設定
        self.learning_enabled: bool = bool(data.get("learning_enabled", False))
        self.learning_llm_model: str = data.get("learning_llm_model", "gpt-4o")
        self.learning_llm_temperature: float = float(
            data.get("learning_llm_temperature", 0.3)
        )
        self.learning_llm_max_tokens: int = int(
            data.get("learning_llm_max_tokens", 8000)
        )
        self.learning_exclude_bot_comments: bool = bool(
            data.get("learning_exclude_bot_comments", True)
        )
        self.learning_only_after_task_start: bool = bool(
            data.get("learning_only_after_task_start", True)
        )
        # ワークフロー設定
        self.workflow_definition_id: int | None = data.get("workflow_definition_id")

    def to_dict(self) -> dict[str, Any]:
        """
        設定内容を辞書として返す。

        Returns:
            設定内容を表す辞書
        """
        return {
            "email": self.email,
            "llm_provider": self.llm_provider,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url,
            "learning_enabled": self.learning_enabled,
            "learning_llm_model": self.learning_llm_model,
            "learning_llm_temperature": self.learning_llm_temperature,
            "learning_llm_max_tokens": self.learning_llm_max_tokens,
            "learning_exclude_bot_comments": self.learning_exclude_bot_comments,
            "learning_only_after_task_start": self.learning_only_after_task_start,
            "workflow_definition_id": self.workflow_definition_id,
        }


class UserConfigClient:
    """
    User Config APIクライアント

    ConsumerコンテナがUSER_CONFIG_API_URL経由でUser Config APIへHTTPで問い合わせる。
    ユーザーのLLM設定・APIキー取得に使用し、AgentFactoryとUserResolverExecutorが依存する。

    IMPLEMENTATION_PLAN.md フェーズ6-2、USER_MANAGEMENT_SPEC.md § 6.1 に準拠する。

    Attributes:
        base_url: User Config APIのベースURL
        api_key: 認証用APIキー
        timeout: リクエストタイムアウト秒数
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: int = 30,
    ) -> None:
        """
        UserConfigClientを初期化する。

        Args:
            base_url: User Config APIのベースURL（例: "http://user-config-api:8080"）
            api_key: 認証用APIキー
            timeout: リクエストタイムアウト秒数
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _build_headers(self) -> dict[str, str]:
        """
        認証ヘッダーを構築する。

        Returns:
            ヘッダー辞書
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get_user_config(self, email: str) -> UserConfig:
        """
        メールアドレスからユーザー設定を取得する。

        User Config APIの GET /api/v1/config/{email} エンドポイントを呼び出し、
        ユーザーのLLM設定・APIキー・学習機能設定を取得する。

        USER_MANAGEMENT_SPEC.md § 6.1 に準拠する。

        Args:
            email: ユーザーのメールアドレス

        Returns:
            UserConfigインスタンス

        Raises:
            httpx.HTTPStatusError: APIからエラーレスポンスが返された場合
            httpx.RequestError: ネットワークエラーが発生した場合
        """
        url = f"{self.base_url}/api/v1/config/{email}"
        logger.info("ユーザー設定を取得します: email=%s, url=%s", email, url)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._build_headers())
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        logger.info("ユーザー設定を取得しました: email=%s", email)
        return UserConfig(data)

    async def get_user_workflow_setting(self, user_id: int) -> dict[str, Any]:
        """
        ユーザーの現在選択中のワークフロー定義設定を取得する。

        User Config APIの GET /api/v1/users/{user_id}/workflow_setting を呼び出す。

        USER_MANAGEMENT_SPEC.md § 6.4 に準拠する。

        Args:
            user_id: ユーザーID

        Returns:
            ワークフロー設定辞書（workflow_definition_id等を含む）

        Raises:
            httpx.HTTPStatusError: APIからエラーレスポンスが返された場合
            httpx.RequestError: ネットワークエラーが発生した場合
        """
        url = f"{self.base_url}/api/v1/users/{user_id}/workflow_setting"
        logger.info(
            "ユーザーのワークフロー設定を取得します: user_id=%s, url=%s", user_id, url
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._build_headers())
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        logger.info("ワークフロー設定を取得しました: user_id=%s", user_id)
        return data
