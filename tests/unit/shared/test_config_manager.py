"""
ConfigManager の単体テスト

YAMLファイル読み込み・環境変数による上書き・各設定カテゴリーのロードを検証する。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from config.config_manager import (
    ConfigManager,
    _cast_env_value,
    _get_nested,
    _set_nested,
)
from config.models import (
    AgentFrameworkConfig,
    AlertsConfig,
    DatabaseConfig,
    GitLabConfig,
    IssueToMRConfig,
    LLMConfig,
    MetricsConfig,
    ProducerConfig,
    RabbitMQConfig,
    SecurityConfig,
    UserConfigAPIConfig,
)


@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    """テスト用の設定ファイルを作成する"""
    config = {
        "gitlab": {
            "api_url": "https://gitlab.example.com/api/v4",
            "owner": "test-owner",
            "bot_name": "test-bot",
            "bot_label": "coding agent",
            "processing_label": "coding agent processing",
            "done_label": "coding agent done",
            "paused_label": "coding agent paused",
            "stopped_label": "coding agent stopped",
            "pat": "test-pat-token",
            "polling_interval": 30,
            "request_timeout": 60,
        },
        "issue_to_mr": {
            "branch_prefix": "issue-",
            "source_branch_template": "{prefix}{issue_iid}",
            "target_branch": "main",
            "mr_title_template": "Draft: {issue_title}",
        },
        "llm": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.2,
            "max_tokens": 4096,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        },
        "database": {
            "url": "postgresql://agent:password@postgres:5432/coding_agent",
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_recycle": 3600,
        },
        "rabbitmq": {
            "host": "rabbitmq",
            "port": 5672,
            "user": "agent",
            "password": "test-pass",
            "queue_name": "coding-agent-tasks",
            "durable": True,
            "prefetch_count": 1,
            "heartbeat": 60,
            "connection_timeout": 30,
        },
        "producer": {
            "interval_seconds": 60,
            "batch_size": 10,
            "enabled": True,
        },
        "agent_framework": {
            "workflows": {
                "human_in_loop": False,
                "checkpoint_interval": 10,
            },
            "observability": {
                "opentelemetry": {
                    "enabled": True,
                    "endpoint": "",
                    "service_name": "coding-agent-orchestrator",
                    "trace_exporter": "otlp",
                }
            },
        },
        "metrics": {
            "enabled": True,
            "collection_interval": 60,
        },
        "alerts": {
            "notification_channel": "gitlab",
            "thresholds": {
                "task_failure_rate": 0.1,
                "queue_length": 100,
                "disk_usage": 0.8,
                "memory_usage": 0.9,
                "api_rate_limit_remaining": 0.1,
            },
        },
        "security": {
            "encryption": {
                "key": "test-encryption-key-32bytes-long!",
                "algorithm": "AES-256-GCM",
            },
            "jwt": {
                "secret": "test-jwt-secret",
                "algorithm": "HS256",
                "expiration": 86400,
            },
        },
        "user_config_api": {
            "enabled": True,
            "url": "http://user-config-api:8080",
            "api_key": "test-api-key",
            "timeout": 30,
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config, f)
    return config_file


class TestConfigManagerLoad:
    """設定ファイル読み込みのテスト"""

    def test_存在するYAMLファイルを読み込める(self, sample_config: Path) -> None:
        """存在するYAMLファイルから設定をロードできることを確認する"""
        manager = ConfigManager(sample_config)
        assert manager.get("gitlab.api_url") == "https://gitlab.example.com/api/v4"

    def test_存在しないYAMLファイルでもデフォルト値を返す(self, tmp_path: Path) -> None:
        """存在しないYAMLファイルを指定した場合もデフォルト値で動作することを確認する"""
        manager = ConfigManager(tmp_path / "nonexistent.yaml")
        # デフォルト値が返ること
        assert manager.get_gitlab_config().api_url == "https://gitlab.com/api/v4"

    def test_ドット区切りキーで設定値を取得できる(self, sample_config: Path) -> None:
        """ドット区切りキーパスで設定値が取得できることを確認する"""
        manager = ConfigManager(sample_config)
        assert manager.get("llm.model") == "gpt-4o"
        assert manager.get("llm.temperature") == 0.2
        assert manager.get("rabbitmq.port") == 5672

    def test_存在しないキーでデフォルト値を返す(self, sample_config: Path) -> None:
        """存在しないキーに対してデフォルト値を返すことを確認する"""
        manager = ConfigManager(sample_config)
        assert manager.get("nonexistent.key") is None
        assert manager.get("nonexistent.key", "default") == "default"

    def test_reload後に設定が再読み込みされる(self, sample_config: Path) -> None:
        """reload()で設定が再読み込みされることを確認する"""
        manager = ConfigManager(sample_config)
        original_url = manager.get("gitlab.api_url")

        # 設定ファイルを更新
        with open(sample_config, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        config["gitlab"]["api_url"] = "https://new.example.com/api/v4"
        with open(sample_config, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        manager.reload()
        assert manager.get("gitlab.api_url") == "https://new.example.com/api/v4"
        assert manager.get("gitlab.api_url") != original_url


class TestConfigManagerEnvOverride:
    """環境変数による上書きのテスト"""

    def test_環境変数でGitLab設定を上書きできる(self, sample_config: Path) -> None:
        """環境変数 GITLAB_API_URL が設定を上書きすることを確認する"""
        with patch.dict(
            os.environ, {"GITLAB_API_URL": "https://env.gitlab.com/api/v4"}
        ):
            manager = ConfigManager(sample_config)
            assert manager.get("gitlab.api_url") == "https://env.gitlab.com/api/v4"

    def test_環境変数でRabbitMQポートを上書きできる(self, sample_config: Path) -> None:
        """環境変数 RABBITMQ_PORT が整数型で設定を上書きすることを確認する"""
        with patch.dict(os.environ, {"RABBITMQ_PORT": "5673"}):
            manager = ConfigManager(sample_config)
            rabbitmq = manager.get_rabbitmq_config()
            assert rabbitmq.port == 5673

    def test_環境変数でブール値を上書きできる(self, sample_config: Path) -> None:
        """環境変数でブール値の設定を上書きできることを確認する"""
        with patch.dict(os.environ, {"PRODUCER_ENABLED": "false"}):
            manager = ConfigManager(sample_config)
            producer = manager.get_producer_config()
            assert producer.enabled is False

    def test_環境変数でGITLAB_PATを設定できる(self, tmp_path: Path) -> None:
        """GITLAB_PAT 環境変数が設定に反映されることを確認する"""
        # YAMLにPATがない場合でも環境変数から取得できること
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(os.environ, {"GITLAB_PAT": "env-pat-token"}):
            manager = ConfigManager(config_file)
            assert manager.get("gitlab.pat") == "env-pat-token"

    def test_YAMLプレースホルダーが環境変数で解決される(self, tmp_path: Path) -> None:
        """YAMLの ${ENV_VAR} プレースホルダーが環境変数で解決されることを確認する"""
        config = {"gitlab": {"pat": "${GITLAB_PAT}"}}
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        with patch.dict(os.environ, {"GITLAB_PAT": "resolved-pat"}):
            manager = ConfigManager(config_file)
            assert manager.get("gitlab.pat") == "resolved-pat"

    def test_環境変数が未設定の場合はYAMLの値を使用する(
        self, sample_config: Path
    ) -> None:
        """環境変数が未設定の場合はYAMLファイルの値を使用することを確認する"""
        # GITLAB_BOT_NAME 環境変数がない場合
        env_without_bot_name = {
            k: v for k, v in os.environ.items() if k != "GITLAB_BOT_NAME"
        }
        with patch.dict(os.environ, env_without_bot_name, clear=True):
            manager = ConfigManager(sample_config)
            assert manager.get("gitlab.bot_name") == "test-bot"


class TestConfigManagerGetters:
    """各設定カテゴリーのゲッターメソッドのテスト"""

    def test_get_gitlab_configがGitLabConfigを返す(self, sample_config: Path) -> None:
        """get_gitlab_config()がGitLabConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_gitlab_config()
        assert isinstance(config, GitLabConfig)
        assert config.api_url == "https://gitlab.example.com/api/v4"
        assert config.bot_label == "coding agent"

    def test_get_llm_configがLLMConfigを返す(self, sample_config: Path) -> None:
        """get_llm_config()がLLMConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_llm_config()
        assert isinstance(config, LLMConfig)
        assert config.model == "gpt-4o"
        assert config.temperature == 0.2

    def test_get_database_configがDatabaseConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_database_config()がDatabaseConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_database_config()
        assert isinstance(config, DatabaseConfig)
        assert config.pool_size == 10

    def test_get_rabbitmq_configがRabbitMQConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_rabbitmq_config()がRabbitMQConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_rabbitmq_config()
        assert isinstance(config, RabbitMQConfig)
        assert config.host == "rabbitmq"
        assert config.port == 5672

    def test_get_producer_configがProducerConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_producer_config()がProducerConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_producer_config()
        assert isinstance(config, ProducerConfig)
        assert config.interval_seconds == 60
        assert config.enabled is True

    def test_get_agent_framework_configがAgentFrameworkConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_agent_framework_config()がAgentFrameworkConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_agent_framework_config()
        assert isinstance(config, AgentFrameworkConfig)
        assert config.workflows.human_in_loop is False

    def test_get_metrics_configがMetricsConfigを返す(self, sample_config: Path) -> None:
        """get_metrics_config()がMetricsConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_metrics_config()
        assert isinstance(config, MetricsConfig)
        assert config.enabled is True

    def test_get_alerts_configがAlertsConfigを返す(self, sample_config: Path) -> None:
        """get_alerts_config()がAlertsConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_alerts_config()
        assert isinstance(config, AlertsConfig)
        assert config.notification_channel == "gitlab"

    def test_get_security_configがSecurityConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_security_config()がSecurityConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_security_config()
        assert isinstance(config, SecurityConfig)
        assert config.encryption.algorithm == "AES-256-GCM"

    def test_get_user_config_api_configがUserConfigAPIConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_user_config_api_config()がUserConfigAPIConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_user_config_api_config()
        assert isinstance(config, UserConfigAPIConfig)
        assert config.enabled is True

    def test_get_issue_to_mr_configがIssueToMRConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_issue_to_mr_config()がIssueToMRConfigインスタンスを返すことを確認する"""
        manager = ConfigManager(sample_config)
        config = manager.get_issue_to_mr_config()
        assert isinstance(config, IssueToMRConfig)
        assert config.branch_prefix == "issue-"
        assert config.target_branch == "main"


class TestConfigManagerValidation:
    """バリデーションのテスト"""

    def test_必須項目が設定されている場合バリデーション成功(
        self, sample_config: Path
    ) -> None:
        """必須項目が設定されている場合はバリデーションが成功することを確認する"""
        manager = ConfigManager(sample_config)
        errors = manager.validate()
        assert errors == []

    def test_ENCRYPTION_KEYが未設定の場合エラーが返る(self, tmp_path: Path) -> None:
        """ENCRYPTION_KEY が未設定の場合バリデーションエラーが返ることを確認する"""
        config = {
            "gitlab": {"pat": "test-pat"},
            "security": {
                "encryption": {"key": ""},
                "jwt": {"secret": "test-secret"},
            },
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        env_without_enc = {k: v for k, v in os.environ.items() if k != "ENCRYPTION_KEY"}
        with patch.dict(os.environ, env_without_enc, clear=True):
            manager = ConfigManager(config_file)
            errors = manager.validate()
            assert any("ENCRYPTION_KEY" in e for e in errors)

    def test_GITLAB_PATが未設定の場合エラーが返る(self, tmp_path: Path) -> None:
        """GITLAB_PAT が未設定の場合バリデーションエラーが返ることを確認する"""
        config = {
            "security": {
                "encryption": {"key": "valid-key"},
                "jwt": {"secret": "valid-secret"},
            }
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        env_without_pat = {k: v for k, v in os.environ.items() if k != "GITLAB_PAT"}
        with patch.dict(os.environ, env_without_pat, clear=True):
            manager = ConfigManager(config_file)
            errors = manager.validate()
            assert any("GITLAB_PAT" in e for e in errors)


class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_set_nestedでネストされた辞書に値をセットできる(self) -> None:
        """_set_nested でネストされたキーパスに値をセットできることを確認する"""
        data: dict = {}
        _set_nested(data, "gitlab.api_url", "https://example.com")
        assert data == {"gitlab": {"api_url": "https://example.com"}}

    def test_get_nestedでネストされた辞書から値を取得できる(self) -> None:
        """_get_nested でネストされたキーパスから値を取得できることを確認する"""
        data = {"gitlab": {"api_url": "https://example.com"}}
        assert _get_nested(data, "gitlab.api_url") == "https://example.com"

    def test_get_nestedで存在しないキーはデフォルト値を返す(self) -> None:
        """_get_nested で存在しないキーに対してデフォルト値を返すことを確認する"""
        data = {"gitlab": {}}
        assert _get_nested(data, "gitlab.api_url", "default") == "default"
        assert _get_nested(data, "nonexistent.key") is None

    def test_cast_env_valueでブール値に変換できる(self) -> None:
        """_cast_env_value でブール値への変換が正しく動作することを確認する"""
        assert _cast_env_value("true", False) is True
        assert _cast_env_value("false", True) is False
        assert _cast_env_value("1", False) is True
        assert _cast_env_value("yes", False) is True
        assert _cast_env_value("no", True) is False

    def test_cast_env_valueで整数値に変換できる(self) -> None:
        """_cast_env_value で整数値への変換が正しく動作することを確認する"""
        assert _cast_env_value("42", 0) == 42
        assert _cast_env_value("5672", 5672) == 5672

    def test_cast_env_valueで浮動小数点値に変換できる(self) -> None:
        """_cast_env_value で浮動小数点値への変換が正しく動作することを確認する"""
        assert _cast_env_value("0.5", 0.0) == pytest.approx(0.5)


class TestEnvVarSupportForImplementationPlan:
    """IMPLEMENTATION_PLAN § 1-1 で要求された環境変数のサポートを検証するテスト

    実装計画が要求する 6 つの環境変数
    (POSTGRES_PASSWORD, ENCRYPTION_KEY, GITLAB_PAT, GITLAB_URL,
     RABBITMQ_URL, USER_CONFIG_API_URL) が正しく機能することを確認する。
    """

    def test_GITLAB_URLが設定をgitlab_urlフィールドに反映する(
        self, tmp_path: Path
    ) -> None:
        """GITLAB_URL 環境変数が GitLabConfig.url フィールドに反映されることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(os.environ, {"GITLAB_URL": "https://mygitlab.example.com"}):
            manager = ConfigManager(config_file)
            config = manager.get_gitlab_config()
            assert config.url == "https://mygitlab.example.com"

    def test_GITLAB_URLとGITLAB_API_URLを同時に設定できる(self, tmp_path: Path) -> None:
        """GITLAB_URL と GITLAB_API_URL が独立したフィールドに設定されることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(
            os.environ,
            {
                "GITLAB_URL": "https://mygitlab.example.com",
                "GITLAB_API_URL": "https://mygitlab.example.com/api/v4",
            },
        ):
            manager = ConfigManager(config_file)
            config = manager.get_gitlab_config()
            assert config.url == "https://mygitlab.example.com"
            assert config.api_url == "https://mygitlab.example.com/api/v4"

    def test_RABBITMQ_URLが設定をrabbitmq_urlフィールドに反映する(
        self, tmp_path: Path
    ) -> None:
        """RABBITMQ_URL 環境変数が RabbitMQConfig.url フィールドに反映されることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(
            os.environ,
            {"RABBITMQ_URL": "amqp://agent:pass@rabbitmq:5672/"},
        ):
            manager = ConfigManager(config_file)
            config = manager.get_rabbitmq_config()
            assert config.url == "amqp://agent:pass@rabbitmq:5672/"

    def test_RABBITMQ_URLが未設定の場合はNone(self, tmp_path: Path) -> None:
        """RABBITMQ_URL が未設定の場合 RabbitMQConfig.url は None になることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        env_without_url = {k: v for k, v in os.environ.items() if k != "RABBITMQ_URL"}
        with patch.dict(os.environ, env_without_url, clear=True):
            manager = ConfigManager(config_file)
            config = manager.get_rabbitmq_config()
            assert config.url is None

    def test_USER_CONFIG_API_URLが設定に反映される(self, tmp_path: Path) -> None:
        """USER_CONFIG_API_URL 環境変数が UserConfigAPIConfig.url に反映されることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(os.environ, {"USER_CONFIG_API_URL": "http://backend:8080"}):
            manager = ConfigManager(config_file)
            config = manager.get_user_config_api_config()
            assert config.url == "http://backend:8080"

    def test_POSTGRES_PASSWORDがDATABASE_URLプレースホルダーで解決される(
        self, tmp_path: Path
    ) -> None:
        """POSTGRES_PASSWORD が DATABASE_URL の ${POSTGRES_PASSWORD} プレースホルダーで解決されることを確認する"""
        config = {
            "database": {
                "url": "postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/coding_agent"
            }
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        with patch.dict(os.environ, {"POSTGRES_PASSWORD": "secret123"}):
            manager = ConfigManager(config_file)
            db_config = manager.get_database_config()
            assert "secret123" in db_config.url


class TestConfigManagerGettersAdditional:
    """設定ゲッターの追加テスト（get_retry_policy_config・get_execution_environment_config・
    get_logging_config・get_mcp_server_configs）"""

    def test_get_retry_policy_configがRetryPolicyConfigを返す(
        self, sample_config: Path
    ) -> None:
        """get_retry_policy_config()がRetryPolicyConfigインスタンスを返すことを確認する"""
        from config.models import RetryPolicyConfig

        manager = ConfigManager(sample_config)
        config = manager.get_retry_policy_config()
        assert isinstance(config, RetryPolicyConfig)
        # デフォルト値の確認
        assert config.http_errors.error_5xx.max_attempts == 3
        assert config.http_errors.error_429.max_attempts == 5
        assert config.tool_errors.max_attempts == 2
        assert config.llm_errors.max_attempts == 3

    def test_get_retry_policy_configでYAML値を反映する(self, tmp_path: Path) -> None:
        """get_retry_policy_config()がYAMLで設定したリトライ設定を返すことを確認する"""
        from config.models import RetryPolicyConfig

        config = {
            "retry_policy": {
                "http_errors": {
                    "5xx": {"max_attempts": 5, "backoff": "linear", "base_delay": 2.0},
                    "429": {
                        "max_attempts": 10,
                        "backoff": "exponential",
                        "base_delay": 30.0,
                    },
                },
                "tool_errors": {
                    "max_attempts": 3,
                    "backoff": "constant",
                    "base_delay": 1.0,
                },
                "llm_errors": {
                    "max_attempts": 4,
                    "backoff": "exponential",
                    "base_delay": 5.0,
                },
            }
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        manager = ConfigManager(config_file)
        retry_config = manager.get_retry_policy_config()
        assert isinstance(retry_config, RetryPolicyConfig)
        assert retry_config.http_errors.error_5xx.max_attempts == 5
        assert retry_config.http_errors.error_429.max_attempts == 10
        assert retry_config.tool_errors.max_attempts == 3

    def test_get_execution_environment_configがExecutionEnvironmentConfigを返す(
        self, tmp_path: Path
    ) -> None:
        """get_execution_environment_config()がExecutionEnvironmentConfigを返すことを確認する"""
        from config.models import ExecutionEnvironmentConfig

        config = {
            "execution_environment": {
                "docker": {
                    "image": "python:3.11-slim",
                    "network": "coding-agent-network",
                    "cpu_limit": "4.0",
                    "memory_limit": "8g",
                },
                "workspace": {
                    "base_path": "/workspace",
                    "mount_path": "/mnt/workspace",
                },
            }
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        manager = ConfigManager(config_file)
        env_config = manager.get_execution_environment_config()
        assert isinstance(env_config, ExecutionEnvironmentConfig)
        assert env_config.docker.image == "python:3.11-slim"
        assert env_config.docker.cpu_limit == "4.0"
        assert env_config.docker.memory_limit == "8g"
        assert env_config.workspace.base_path == "/workspace"

    def test_get_execution_environment_configのデフォルト値が正しい(
        self, tmp_path: Path
    ) -> None:
        """execution_environment が未設定の場合にデフォルト値が返ることを確認する"""
        from config.models import ExecutionEnvironmentConfig

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        manager = ConfigManager(config_file)
        env_config = manager.get_execution_environment_config()
        assert isinstance(env_config, ExecutionEnvironmentConfig)
        assert env_config.docker.image == "automatacodex-executor-python:latest"
        assert env_config.docker.network == "coding-agent-network"
        assert env_config.workspace.base_path == "/workspace"

    def test_DOCKER_IMAGE環境変数がDockerConfigに反映される(
        self, tmp_path: Path
    ) -> None:
        """DOCKER_IMAGE 環境変数が ExecutionEnvironmentConfig.docker.image に反映されることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(os.environ, {"DOCKER_IMAGE": "python:3.12-slim"}):
            manager = ConfigManager(config_file)
            env_config = manager.get_execution_environment_config()
            assert env_config.docker.image == "python:3.12-slim"

    def test_get_logging_configがLoggingConfigを返す(self, tmp_path: Path) -> None:
        """get_logging_config()がLoggingConfigインスタンスを返すことを確認する"""
        from config.models import LoggingConfig

        config = {
            "logging": {
                "level": "DEBUG",
                "file": "logs/debug.log",
                "max_bytes": 5242880,
                "backup_count": 5,
            }
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        manager = ConfigManager(config_file)
        log_config = manager.get_logging_config()
        assert isinstance(log_config, LoggingConfig)
        assert log_config.level == "DEBUG"
        assert log_config.file == "logs/debug.log"
        assert log_config.max_bytes == 5242880
        assert log_config.backup_count == 5

    def test_get_logging_configのデフォルト値が正しい(self, tmp_path: Path) -> None:
        """logging が未設定の場合にデフォルト値が返ることを確認する"""
        from config.models import LoggingConfig

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        manager = ConfigManager(config_file)
        log_config = manager.get_logging_config()
        assert isinstance(log_config, LoggingConfig)
        assert log_config.level == "INFO"
        assert log_config.backup_count == 10

    def test_LoggingConfigの不正なlevelでバリデーションエラー(self) -> None:
        """無効なログレベルでValidationErrorが発生することを確認する"""
        from config.models import LoggingConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LoggingConfig(level="VERBOSE")

    def test_LOG_LEVEL環境変数がLoggingConfigに反映される(self, tmp_path: Path) -> None:
        """LOG_LEVEL 環境変数が LoggingConfig.level に反映されることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}):
            manager = ConfigManager(config_file)
            log_config = manager.get_logging_config()
            assert log_config.level == "WARNING"

    def test_get_mcp_server_configsが空リストを返す(self, tmp_path: Path) -> None:
        """mcp_servers が未設定の場合に空リストを返すことを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        manager = ConfigManager(config_file)
        mcp_configs = manager.get_mcp_server_configs()
        assert mcp_configs == []

    def test_get_mcp_server_configsがMCPServerConfigリストを返す(
        self, tmp_path: Path
    ) -> None:
        """get_mcp_server_configs()がMCPServerConfigのリストを返すことを確認する"""
        from config.models import MCPServerConfig

        config = {
            "mcp_servers": [
                {
                    "name": "text_editor",
                    "command": ["python", "-m", "mcp_server.text_editor"],
                    "env": {"LOG_LEVEL": "INFO"},
                },
                {
                    "name": "command_executor",
                    "command": ["python", "-m", "mcp_server.command_executor"],
                    "env": {},
                },
            ]
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        manager = ConfigManager(config_file)
        mcp_configs = manager.get_mcp_server_configs()
        assert len(mcp_configs) == 2
        assert isinstance(mcp_configs[0], MCPServerConfig)
        assert mcp_configs[0].name == "text_editor"
        assert mcp_configs[0].command == ["python", "-m", "mcp_server.text_editor"]
        assert mcp_configs[0].env == {"LOG_LEVEL": "INFO"}
        assert mcp_configs[1].name == "command_executor"


class TestConfigManagerValidationAdditional:
    """バリデーションの追加テスト（JWT_SECRET 未設定など）"""

    def test_JWT_SECRETが未設定の場合エラーが返る(self, tmp_path: Path) -> None:
        """JWT_SECRET が未設定の場合バリデーションエラーが返ることを確認する"""
        config = {
            "gitlab": {"pat": "test-pat"},
            "security": {
                "encryption": {"key": "valid-32byte-encryption-key-here!"},
                "jwt": {"secret": ""},
            },
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        env_without_jwt = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
        with patch.dict(os.environ, env_without_jwt, clear=True):
            manager = ConfigManager(config_file)
            errors = manager.validate()
            assert any("JWT_SECRET" in e for e in errors)

    def test_全て必須項目が未設定の場合3件のエラーが返る(self, tmp_path: Path) -> None:
        """ENCRYPTION_KEY・JWT_SECRET・GITLAB_PAT が全て未設定の場合3件のエラーが返ることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        env_without_required = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ENCRYPTION_KEY", "JWT_SECRET", "GITLAB_PAT")
        }
        with patch.dict(os.environ, env_without_required, clear=True):
            manager = ConfigManager(config_file)
            errors = manager.validate()
            assert len(errors) == 3

    def test_ENCRYPTION_KEYのみ設定された場合2件のエラーが返る(
        self, tmp_path: Path
    ) -> None:
        """ENCRYPTION_KEY のみ設定された場合は2件のエラーが返ることを確認する"""
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        env_only_enc = {
            k: v for k, v in os.environ.items() if k not in ("JWT_SECRET", "GITLAB_PAT")
        }
        env_only_enc["ENCRYPTION_KEY"] = "valid-key"
        with patch.dict(os.environ, env_only_enc, clear=True):
            manager = ConfigManager(config_file)
            errors = manager.validate()
            assert len(errors) == 2
