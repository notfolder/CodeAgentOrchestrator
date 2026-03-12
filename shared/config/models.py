"""
設定データクラス定義

各設定カテゴリをPydantic BaseModelとして定義し、バリデーション付きで管理する。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class GitLabConfig(BaseModel):
    """GitLab API・ボット・ラベル設定"""

    api_url: str = Field(default="https://gitlab.com/api/v4", description="GitLab API URL")
    owner: str = Field(default="", description="GitLabオーナー名")
    bot_name: str = Field(default="", description="botアカウント名")
    bot_label: str = Field(default="coding agent", description="処理対象タスク識別ラベル")
    processing_label: str = Field(default="coding agent processing", description="処理中ラベル")
    done_label: str = Field(default="coding agent done", description="完了ラベル")
    paused_label: str = Field(default="coding agent paused", description="一時停止ラベル")
    stopped_label: str = Field(default="coding agent stopped", description="停止ラベル")
    pat: str = Field(default="", description="bot用Personal Access Token")
    polling_interval: int = Field(default=30, ge=1, description="ポーリング間隔（秒）")
    request_timeout: int = Field(default=60, ge=1, description="APIリクエストタイムアウト（秒）")


class IssueToMRConfig(BaseModel):
    """Issue→MR自動変換設定"""

    branch_prefix: str = Field(default="issue-", description="ブランチ名プレフィックス")
    source_branch_template: str = Field(
        default="{prefix}{issue_iid}", description="ソースブランチ名テンプレート"
    )
    target_branch: str = Field(default="main", description="デフォルトターゲットブランチ")
    mr_title_template: str = Field(
        default="Draft: {issue_title}", description="MRタイトルテンプレート"
    )


class LLMConfig(BaseModel):
    """LLMプロバイダー・モデル・パラメータ設定"""

    provider: str = Field(default="openai", description="LLMプロバイダー（openai/ollama/lmstudio）")
    model: str = Field(default="gpt-4o", description="使用モデル名")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="生成温度")
    max_tokens: int = Field(default=4096, ge=1, description="最大生成トークン数")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="nucleus sampling閾値")
    frequency_penalty: float = Field(
        default=0.0, ge=-2.0, le=2.0, description="frequency penalty"
    )
    presence_penalty: float = Field(
        default=0.0, ge=-2.0, le=2.0, description="presence penalty"
    )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """許可されたプロバイダーのみ受け付ける"""
        allowed = {"openai", "ollama", "lmstudio"}
        if v not in allowed:
            raise ValueError(f"providerは{allowed}のいずれかである必要があります: {v}")
        return v


class OpenAIConfig(BaseModel):
    """OpenAI固有設定（フォールバック用）"""

    api_key: str = Field(default="", description="フォールバック用APIキー")
    base_url: str = Field(
        default="https://api.openai.com/v1", description="OpenAI API ベースURL"
    )
    timeout: int = Field(default=120, ge=1, description="タイムアウト（秒）")


class UserConfigAPIConfig(BaseModel):
    """User Config API接続設定"""

    enabled: bool = Field(default=True, description="User Config API有効フラグ")
    url: str = Field(default="http://user-config-api:8080", description="APIエンドポイントURL")
    api_key: str = Field(default="", description="認証キー")
    timeout: int = Field(default=30, ge=1, description="タイムアウト（秒）")


class DatabaseConfig(BaseModel):
    """PostgreSQL接続・コネクションプール設定"""

    url: str = Field(
        default="postgresql://agent:@postgres:5432/coding_agent",
        description="データベース接続URL",
    )
    pool_size: int = Field(default=10, ge=1, description="コネクションプールサイズ")
    max_overflow: int = Field(default=20, ge=0, description="最大オーバーフロー接続数")
    pool_timeout: int = Field(default=30, ge=1, description="プール取得タイムアウト（秒）")
    pool_recycle: int = Field(default=3600, ge=1, description="接続再作成間隔（秒）")


class RabbitMQConfig(BaseModel):
    """RabbitMQ接続・キュー設定"""

    host: str = Field(default="rabbitmq", description="RabbitMQホスト名")
    port: int = Field(default=5672, ge=1, le=65535, description="ポート番号")
    user: str = Field(default="agent", description="ユーザー名")
    password: str = Field(default="", description="パスワード")
    queue_name: str = Field(default="coding-agent-tasks", description="キュー名")
    durable: bool = Field(default=True, description="永続化キューフラグ")
    prefetch_count: int = Field(
        default=1, ge=1, description="Consumer1台あたりの同時処理タスク数"
    )
    heartbeat: int = Field(default=60, ge=0, description="ハートビート間隔（秒）")
    connection_timeout: int = Field(default=30, ge=1, description="接続タイムアウト（秒）")


class ProducerConfig(BaseModel):
    """タスク生成・キューイング設定"""

    interval_seconds: int = Field(default=60, ge=1, description="タスク検出間隔（秒）")
    batch_size: int = Field(default=10, ge=1, description="一度に取得する最大タスク数")
    enabled: bool = Field(default=True, description="Producer有効フラグ")


class AgentWorkflowsConfig(BaseModel):
    """Agent Frameworkワークフロー設定"""

    human_in_loop: bool = Field(default=False, description="Human-in-the-loop有効フラグ")
    checkpoint_interval: int = Field(
        default=10, ge=1, description="チェックポイント保存間隔（ステップ数）"
    )


class OpenTelemetryConfig(BaseModel):
    """OpenTelemetry設定"""

    enabled: bool = Field(default=True, description="OpenTelemetry有効フラグ")
    endpoint: str = Field(default="", description="OTLPエクスポーターエンドポイント")
    service_name: str = Field(
        default="coding-agent-orchestrator", description="サービス名"
    )
    trace_exporter: str = Field(default="otlp", description="トレースエクスポーター種別")


class AgentObservabilityConfig(BaseModel):
    """Agent Framework監視設定"""

    opentelemetry: OpenTelemetryConfig = Field(default_factory=OpenTelemetryConfig)


class AgentFrameworkConfig(BaseModel):
    """Agent Framework全体設定"""

    workflows: AgentWorkflowsConfig = Field(default_factory=AgentWorkflowsConfig)
    observability: AgentObservabilityConfig = Field(default_factory=AgentObservabilityConfig)


class ContextCompressionConfig(BaseModel):
    """コンテキスト圧縮設定"""

    default_token_threshold: int = Field(default=5600, ge=1)
    default_keep_recent: int = Field(default=10, ge=1)
    default_min_to_compress: int = Field(default=5, ge=1)
    default_min_compression_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    model_recommendations: dict[str, int] = Field(default_factory=dict)
    summary_llm_model: str = Field(default="gpt-4o-mini")
    summary_llm_temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class ContextInheritanceConfig(BaseModel):
    """コンテキスト継承設定"""

    max_summary_tokens: int = Field(default=4000, ge=1)
    expiry_days: int = Field(default=30, ge=1)


class ContextStorageConfig(BaseModel):
    """コンテキストストレージ設定"""

    base_dir: str = Field(default="contexts")
    compression: ContextCompressionConfig = Field(default_factory=ContextCompressionConfig)
    inheritance: ContextInheritanceConfig = Field(default_factory=ContextInheritanceConfig)


class FileStorageConfig(BaseModel):
    """ファイルストレージ設定"""

    base_dir: str = Field(default="tool_results")
    retention_days: int = Field(default=30, ge=1)
    max_file_size_mb: int = Field(default=100, ge=1)
    formats: list[str] = Field(default_factory=lambda: ["json", "txt", "md", "log"])


class RetryPolicyErrorConfig(BaseModel):
    """特定エラー種別のリトライ設定"""

    max_attempts: int = Field(default=3, ge=1)
    backoff: str = Field(default="exponential")
    base_delay: float = Field(default=1.0, ge=0.0)

    @field_validator("backoff")
    @classmethod
    def validate_backoff(cls, v: str) -> str:
        """許可されたバックオフ戦略のみ受け付ける"""
        allowed = {"exponential", "linear", "constant"}
        if v not in allowed:
            raise ValueError(f"backoffは{allowed}のいずれかである必要があります: {v}")
        return v


class HTTPErrorsRetryConfig(BaseModel):
    """HTTPエラーのリトライ設定"""

    # 5xx エラー用設定
    error_5xx: RetryPolicyErrorConfig = Field(
        default_factory=lambda: RetryPolicyErrorConfig(
            max_attempts=3, backoff="exponential", base_delay=1.0
        ),
        alias="5xx",
    )
    # 429 エラー用設定
    error_429: RetryPolicyErrorConfig = Field(
        default_factory=lambda: RetryPolicyErrorConfig(
            max_attempts=5, backoff="exponential", base_delay=60.0
        ),
        alias="429",
    )

    model_config = {"populate_by_name": True}


class RetryPolicyConfig(BaseModel):
    """リトライポリシー全体設定"""

    http_errors: HTTPErrorsRetryConfig = Field(default_factory=HTTPErrorsRetryConfig)
    tool_errors: RetryPolicyErrorConfig = Field(
        default_factory=lambda: RetryPolicyErrorConfig(
            max_attempts=2, backoff="linear", base_delay=5.0
        )
    )
    llm_errors: RetryPolicyErrorConfig = Field(
        default_factory=lambda: RetryPolicyErrorConfig(
            max_attempts=3, backoff="exponential", base_delay=2.0
        )
    )


class LoggingConfig(BaseModel):
    """ログ設定"""

    level: str = Field(default="INFO")
    file: str = Field(default="logs/agent.log")
    max_bytes: int = Field(default=10485760, ge=1)
    backup_count: int = Field(default=10, ge=0)
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    date_format: str = Field(default="%Y-%m-%d %H:%M:%S")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """許可されたログレベルのみ受け付ける"""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"levelは{allowed}のいずれかである必要があります: {v}")
        return v_upper


class EncryptionConfig(BaseModel):
    """暗号化設定"""

    key: str = Field(default="", description="暗号化キー（32バイト以上）")
    algorithm: str = Field(default="AES-256-GCM", description="暗号化アルゴリズム")


class JWTConfig(BaseModel):
    """JWT認証設定"""

    secret: str = Field(default="", description="JWT署名用秘密鍵")
    algorithm: str = Field(default="HS256", description="署名アルゴリズム")
    expiration: int = Field(default=86400, ge=1, description="有効期限（秒）")


class SecurityConfig(BaseModel):
    """セキュリティ設定"""

    encryption: EncryptionConfig = Field(default_factory=EncryptionConfig)
    jwt: JWTConfig = Field(default_factory=JWTConfig)


class TaskProcessingConfig(BaseModel):
    """タスク処理設定"""

    max_concurrent_tasks: int = Field(default=3, ge=1)
    task_timeout: int = Field(default=3600, ge=1)
    cleanup_completed_after_days: int = Field(default=30, ge=1)
    max_retries: int = Field(default=3, ge=0)


class MetricsConfig(BaseModel):
    """メトリクス収集設定"""

    enabled: bool = Field(default=True)
    collection_interval: int = Field(default=60, ge=1)
    task_processing_time: bool = Field(default=True)
    success_rate: bool = Field(default=True)
    queue_length: bool = Field(default=True)
    api_rate_limits: bool = Field(default=True)
    token_usage: bool = Field(default=True)
    system_resources: bool = Field(default=True)


class AlertThresholdsConfig(BaseModel):
    """アラート閾値設定"""

    task_failure_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    queue_length: int = Field(default=100, ge=1)
    disk_usage: float = Field(default=0.8, ge=0.0, le=1.0)
    memory_usage: float = Field(default=0.9, ge=0.0, le=1.0)
    api_rate_limit_remaining: float = Field(default=0.1, ge=0.0, le=1.0)


class AlertsConfig(BaseModel):
    """アラート通知設定"""

    notification_channel: str = Field(default="gitlab")
    thresholds: AlertThresholdsConfig = Field(default_factory=AlertThresholdsConfig)

    @field_validator("notification_channel")
    @classmethod
    def validate_notification_channel(cls, v: str) -> str:
        """許可された通知チャネルのみ受け付ける"""
        allowed = {"gitlab", "email", "slack"}
        if v not in allowed:
            raise ValueError(f"notification_channelは{allowed}のいずれかである必要があります: {v}")
        return v


class MCPServerEnvConfig(BaseModel):
    """MCPサーバー環境変数設定"""

    model_config = {"extra": "allow"}

    def model_dump_extras(self) -> dict[str, Any]:
        """追加フィールドを含む辞書を返す"""
        return dict(self.model_extra or {})


class MCPServerConfig(BaseModel):
    """MCPサーバー設定"""

    name: str = Field(description="サーバー名")
    command: list[str] = Field(description="サーバー起動コマンド")
    env: dict[str, str] = Field(default_factory=dict, description="環境変数")


class DockerConfig(BaseModel):
    """Docker実行環境設定"""

    image: str = Field(default="python:3.11-slim", description="Dockerイメージ")
    network: str = Field(default="coding-agent-network", description="Dockerネットワーク名")
    cpu_limit: str = Field(default="2.0", description="CPUリミット")
    memory_limit: str = Field(default="4g", description="メモリリミット")


class WorkspaceConfig(BaseModel):
    """ワークスペース設定"""

    base_path: str = Field(default="/workspace", description="ベースパス")
    mount_path: str = Field(default="/mnt/workspace", description="マウントパス")


class ExecutionEnvironmentConfig(BaseModel):
    """実行環境全体設定"""

    docker: DockerConfig = Field(default_factory=DockerConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
