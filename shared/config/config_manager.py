"""
設定管理クラス

config.yamlをロードし、環境変数による上書きを適用して設定を提供する。
環境変数の優先順位: 環境変数 > config.yaml > Pydanticモデルのデフォルト値
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .models import (
    AgentFrameworkConfig,
    AlertsConfig,
    DatabaseConfig,
    ExecutionEnvironmentConfig,
    GitLabConfig,
    IssueToMRConfig,
    LLMConfig,
    LoggingConfig,
    MCPServerConfig,
    MetricsConfig,
    OpenAIConfig,
    ProducerConfig,
    RabbitMQConfig,
    RetryPolicyConfig,
    SecurityConfig,
    TaskProcessingConfig,
    UserConfigAPIConfig,
)

# 環境変数と設定キーのマッピング定義
# キー: 環境変数名、値: ドット区切りの設定キーパス
ENV_VAR_MAPPING: dict[str, str] = {
    # GitLab設定
    "GITLAB_API_URL": "gitlab.api_url",
    "GITLAB_OWNER": "gitlab.owner",
    "GITLAB_BOT_NAME": "gitlab.bot_name",
    "GITLAB_BOT_LABEL": "gitlab.bot_label",
    "GITLAB_PROCESSING_LABEL": "gitlab.processing_label",
    "GITLAB_DONE_LABEL": "gitlab.done_label",
    "GITLAB_PAUSED_LABEL": "gitlab.paused_label",
    "GITLAB_STOPPED_LABEL": "gitlab.stopped_label",
    "GITLAB_PAT": "gitlab.pat",
    "GITLAB_POLLING_INTERVAL": "gitlab.polling_interval",
    "GITLAB_REQUEST_TIMEOUT": "gitlab.request_timeout",
    # Issue→MR変換設定
    "ISSUE_TO_MR_BRANCH_PREFIX": "issue_to_mr.branch_prefix",
    "ISSUE_TO_MR_SOURCE_BRANCH_TEMPLATE": "issue_to_mr.source_branch_template",
    "ISSUE_TO_MR_TARGET_BRANCH": "issue_to_mr.target_branch",
    "ISSUE_TO_MR_TITLE_TEMPLATE": "issue_to_mr.mr_title_template",
    # LLM設定
    "LLM_PROVIDER": "llm.provider",
    "LLM_MODEL": "llm.model",
    "LLM_TEMPERATURE": "llm.temperature",
    "LLM_MAX_TOKENS": "llm.max_tokens",
    "LLM_TOP_P": "llm.top_p",
    "LLM_FREQUENCY_PENALTY": "llm.frequency_penalty",
    "LLM_PRESENCE_PENALTY": "llm.presence_penalty",
    # OpenAI設定
    "OPENAI_API_KEY": "openai.api_key",
    "OPENAI_BASE_URL": "openai.base_url",
    "OPENAI_TIMEOUT": "openai.timeout",
    # User Config API設定
    "USER_CONFIG_API_ENABLED": "user_config_api.enabled",
    "USER_CONFIG_API_URL": "user_config_api.url",
    "USER_CONFIG_API_KEY": "user_config_api.api_key",
    "USER_CONFIG_API_TIMEOUT": "user_config_api.timeout",
    # データベース設定
    "DATABASE_URL": "database.url",
    "DATABASE_POOL_SIZE": "database.pool_size",
    "DATABASE_MAX_OVERFLOW": "database.max_overflow",
    "DATABASE_POOL_TIMEOUT": "database.pool_timeout",
    "DATABASE_POOL_RECYCLE": "database.pool_recycle",
    # RabbitMQ設定
    "RABBITMQ_HOST": "rabbitmq.host",
    "RABBITMQ_PORT": "rabbitmq.port",
    "RABBITMQ_USER": "rabbitmq.user",
    "RABBITMQ_PASS": "rabbitmq.password",
    "RABBITMQ_QUEUE_NAME": "rabbitmq.queue_name",
    "RABBITMQ_DURABLE": "rabbitmq.durable",
    "RABBITMQ_PREFETCH_COUNT": "rabbitmq.prefetch_count",
    "RABBITMQ_HEARTBEAT": "rabbitmq.heartbeat",
    "RABBITMQ_CONNECTION_TIMEOUT": "rabbitmq.connection_timeout",
    # Producer設定
    "PRODUCER_INTERVAL_SECONDS": "producer.interval_seconds",
    "PRODUCER_BATCH_SIZE": "producer.batch_size",
    "PRODUCER_ENABLED": "producer.enabled",
    # Agent Framework設定
    "AGENT_WORKFLOWS_HUMAN_IN_LOOP": "agent_framework.workflows.human_in_loop",
    "AGENT_WORKFLOWS_CHECKPOINT_INTERVAL": "agent_framework.workflows.checkpoint_interval",
    "AGENT_OBSERVABILITY_ENABLED": (
        "agent_framework.observability.opentelemetry.enabled"
    ),
    "OTEL_SERVICE_NAME": "agent_framework.observability.opentelemetry.service_name",
    "OTEL_TRACE_EXPORTER": "agent_framework.observability.opentelemetry.trace_exporter",
    "OTEL_EXPORTER_OTLP_ENDPOINT": (
        "agent_framework.observability.opentelemetry.endpoint"
    ),
    # メトリクス設定
    "METRICS_ENABLED": "metrics.enabled",
    "METRICS_COLLECTION_INTERVAL": "metrics.collection_interval",
    # アラート設定
    "ALERTS_NOTIFICATION_CHANNEL": "alerts.notification_channel",
    "ALERTS_THRESHOLD_TASK_FAILURE_RATE": "alerts.thresholds.task_failure_rate",
    "ALERTS_THRESHOLD_QUEUE_LENGTH": "alerts.thresholds.queue_length",
    "ALERTS_THRESHOLD_DISK_USAGE": "alerts.thresholds.disk_usage",
    "ALERTS_THRESHOLD_MEMORY_USAGE": "alerts.thresholds.memory_usage",
    "ALERTS_THRESHOLD_API_RATE_LIMIT": "alerts.thresholds.api_rate_limit_remaining",
    # セキュリティ設定
    "ENCRYPTION_KEY": "security.encryption.key",
    "JWT_SECRET": "security.jwt.secret",
    "JWT_EXPIRATION": "security.jwt.expiration",
    # ログ設定
    "LOG_LEVEL": "logging.level",
    "LOG_FILE": "logging.file",
    # Docker設定
    "DOCKER_IMAGE": "execution_environment.docker.image",
    "DOCKER_NETWORK": "execution_environment.docker.network",
    "DOCKER_CPU_LIMIT": "execution_environment.docker.cpu_limit",
    "DOCKER_MEMORY_LIMIT": "execution_environment.docker.memory_limit",
    "WORKSPACE_BASE_PATH": "execution_environment.workspace.base_path",
    "WORKSPACE_MOUNT_PATH": "execution_environment.workspace.mount_path",
    # タスク処理設定
    "TASK_MAX_CONCURRENT": "task_processing.max_concurrent_tasks",
    "TASK_TIMEOUT": "task_processing.task_timeout",
    "TASK_CLEANUP_DAYS": "task_processing.cleanup_completed_after_days",
    "TASK_MAX_RETRIES": "task_processing.max_retries",
}

# YAMLの環境変数プレースホルダーを解決する正規表現
_ENV_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _resolve_env_placeholders(value: Any) -> Any:
    """
    YAML値内の ${ENV_VAR} または ${ENV_VAR:-default} プレースホルダーを環境変数で解決する。

    Args:
        value: 解決対象の値（文字列・辞書・リスト等）

    Returns:
        プレースホルダーを解決した値
    """
    if isinstance(value, str):
        def replace_match(m: re.Match) -> str:
            env_name = m.group(1)
            default = m.group(2) if m.group(2) is not None else ""
            return os.environ.get(env_name, default)

        return _ENV_PLACEHOLDER_RE.sub(replace_match, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    return value


def _set_nested(data: dict[str, Any], key_path: str, value: Any) -> None:
    """
    ドット区切りキーパスで辞書にネストされた値をセットする。

    Args:
        data: 対象の辞書
        key_path: ドット区切りキーパス（例: "gitlab.api_url"）
        value: セットする値
    """
    keys = key_path.split(".")
    current = data
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value


def _get_nested(data: dict[str, Any], key_path: str, default: Any = None) -> Any:
    """
    ドット区切りキーパスで辞書からネストされた値を取得する。

    Args:
        data: 対象の辞書
        key_path: ドット区切りキーパス（例: "gitlab.api_url"）
        default: キーが存在しない場合のデフォルト値

    Returns:
        取得した値またはデフォルト値
    """
    keys = key_path.split(".")
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _cast_env_value(value: str, current_value: Any) -> Any:
    """
    環境変数の文字列値を既存の設定値の型にキャストする。

    Args:
        value: 環境変数の文字列値
        current_value: 既存の設定値（型参照用）

    Returns:
        キャストした値
    """
    if isinstance(current_value, bool):
        return value.lower() in ("true", "1", "yes")
    elif isinstance(current_value, int):
        return int(value)
    elif isinstance(current_value, float):
        return float(value)
    return value


class ConfigManager:
    """
    設定ファイルと環境変数を統合管理するクラス。

    config.yamlをロードしてデフォルト設定を取得し、環境変数による上書きを適用する。
    設定値のバリデーションを実施し、型安全なアクセスインターフェースを提供する。
    """

    def __init__(self, config_path: str | Path = "config.yaml") -> None:
        """
        設定ファイルと環境変数から設定をロードする。

        Args:
            config_path: 設定ファイルのパス（デフォルト: "config.yaml"）
        """
        self._config_path = Path(config_path)
        self._raw: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """設定ファイルをロードし、環境変数プレースホルダーを解決後、環境変数で上書きする。"""
        # YAMLファイルの読み込み
        if self._config_path.exists():
            with open(self._config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        # YAMLプレースホルダーを解決
        self._raw = _resolve_env_placeholders(raw)

        # 環境変数マッピングによる上書き
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """環境変数マッピングに基づいて設定を環境変数で上書きする。"""
        for env_var, key_path in ENV_VAR_MAPPING.items():
            env_value = os.environ.get(env_var)
            if env_value is None:
                continue

            # 既存値の型を参照してキャスト
            current_value = _get_nested(self._raw, key_path)
            try:
                casted = _cast_env_value(env_value, current_value)
            except (ValueError, TypeError):
                casted = env_value

            _set_nested(self._raw, key_path, casted)

    def get(self, key: str, default: Any = None) -> Any:
        """
        ドット区切りのキーで設定値を取得する。

        Args:
            key: ドット区切りキーパス（例: "gitlab.api_url"）
            default: キーが存在しない場合のデフォルト値

        Returns:
            設定値またはデフォルト値
        """
        return _get_nested(self._raw, key, default)

    def reload(self) -> None:
        """設定をリロードする（開発・テスト用）。"""
        self._raw = {}
        self._load()

    def validate(self) -> list[str]:
        """
        設定値のバリデーションを実行し、エラーメッセージのリストを返す。

        Returns:
            バリデーションエラーのリスト（空リストの場合はバリデーション成功）
        """
        errors: list[str] = []

        # 必須項目チェック
        required_keys = [
            ("security.encryption.key", "ENCRYPTION_KEY"),
            ("security.jwt.secret", "JWT_SECRET"),
        ]
        for key_path, env_name in required_keys:
            value = self.get(key_path, "")
            if not value:
                errors.append(
                    f"必須設定 '{key_path}' が未設定です（環境変数: {env_name}）"
                )

        # GitLab PATのチェック（必須）
        gitlab_pat = self.get("gitlab.pat", "")
        if not gitlab_pat:
            errors.append(
                "必須設定 'gitlab.pat' が未設定です（環境変数: GITLAB_PAT）"
            )

        return errors

    def get_gitlab_config(self) -> GitLabConfig:
        """GitLab設定を取得する。"""
        data = self._raw.get("gitlab", {})
        return GitLabConfig.model_validate(data)

    def get_issue_to_mr_config(self) -> IssueToMRConfig:
        """Issue→MR変換設定を取得する。"""
        data = self._raw.get("issue_to_mr", {})
        return IssueToMRConfig.model_validate(data)

    def get_llm_config(self) -> LLMConfig:
        """LLM設定を取得する。"""
        data = self._raw.get("llm", {})
        return LLMConfig.model_validate(data)

    def get_openai_config(self) -> OpenAIConfig:
        """OpenAI固有設定を取得する。"""
        data = self._raw.get("openai", {})
        return OpenAIConfig.model_validate(data)

    def get_user_config_api_config(self) -> UserConfigAPIConfig:
        """User Config API設定を取得する。"""
        data = self._raw.get("user_config_api", {})
        return UserConfigAPIConfig.model_validate(data)

    def get_database_config(self) -> DatabaseConfig:
        """PostgreSQL設定を取得する。"""
        data = self._raw.get("database", {})
        return DatabaseConfig.model_validate(data)

    def get_rabbitmq_config(self) -> RabbitMQConfig:
        """RabbitMQ設定を取得する。"""
        data = self._raw.get("rabbitmq", {})
        return RabbitMQConfig.model_validate(data)

    def get_producer_config(self) -> ProducerConfig:
        """Producer設定を取得する。"""
        data = self._raw.get("producer", {})
        return ProducerConfig.model_validate(data)

    def get_agent_framework_config(self) -> AgentFrameworkConfig:
        """Agent Framework設定を取得する。"""
        data = self._raw.get("agent_framework", {})
        return AgentFrameworkConfig.model_validate(data)

    def get_metrics_config(self) -> MetricsConfig:
        """メトリクス設定を取得する。"""
        data = self._raw.get("metrics", {})
        return MetricsConfig.model_validate(data)

    def get_alerts_config(self) -> AlertsConfig:
        """アラート設定を取得する。"""
        data = self._raw.get("alerts", {})
        return AlertsConfig.model_validate(data)

    def get_retry_policy_config(self) -> RetryPolicyConfig:
        """リトライポリシー設定を取得する。"""
        data = self._raw.get("retry_policy", {})
        return RetryPolicyConfig.model_validate(data)

    def get_logging_config(self) -> LoggingConfig:
        """ログ設定を取得する。"""
        data = self._raw.get("logging", {})
        return LoggingConfig.model_validate(data)

    def get_security_config(self) -> SecurityConfig:
        """セキュリティ設定を取得する。"""
        data = self._raw.get("security", {})
        return SecurityConfig.model_validate(data)

    def get_task_processing_config(self) -> TaskProcessingConfig:
        """タスク処理設定を取得する。"""
        data = self._raw.get("task_processing", {})
        return TaskProcessingConfig.model_validate(data)

    def get_execution_environment_config(self) -> ExecutionEnvironmentConfig:
        """Docker実行環境設定を取得する。"""
        data = self._raw.get("execution_environment", {})
        return ExecutionEnvironmentConfig.model_validate(data)

    def get_mcp_server_configs(self) -> list[MCPServerConfig]:
        """MCPサーバー設定リストを取得する。"""
        data_list = self._raw.get("mcp_servers", [])
        return [MCPServerConfig.model_validate(item) for item in data_list]
