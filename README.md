# AutomataCodex

GitLab上のIssue/MRを自動的に処理するコードエージェントオーケストレーションシステム。

## 概要

本システムはGitLabのIssueやMerge Requestを検出し、AIエージェントを使って自動的にコード生成・バグ修正・テスト作成・ドキュメント生成を実行する。Microsoft Agent Frameworkを基盤とし、グラフ定義・エージェント定義・プロンプト定義ファイルによって柔軟なワークフローを実現する。

詳細な設計仕様は [`docs/AUTOMATA_CODEX_SPEC.md`](docs/AUTOMATA_CODEX_SPEC.md) を参照。

## 主要コンポーネント

- **Producer**: GitLabのIssue/MRを検出し、RabbitMQにキューイング
- **Consumer**: RabbitMQからタスクをデキューし、ワークフローを実行
- **Agent Framework Workflow**: グラフ定義に基づく柔軟なエージェントフロー
- **PostgreSQL**: タスク状態・コンテキスト・ワークフロー定義を管理
- **RabbitMQ**: 分散タスクキュー（100人規模対応）
- **Docker**: 各エージェントの実行環境を分離

## ドキュメント

| ファイル | 内容 |
|---------|------|
| [`docs/AUTOMATA_CODEX_SPEC.md`](docs/AUTOMATA_CODEX_SPEC.md) | システム全体設計仕様書 |
| [`docs/GRAPH_DEFINITION_SPEC.md`](docs/GRAPH_DEFINITION_SPEC.md) | グラフ定義ファイル仕様 |
| [`docs/AGENT_DEFINITION_SPEC.md`](docs/AGENT_DEFINITION_SPEC.md) | エージェント定義ファイル仕様 |
| [`docs/PROMPT_DEFINITION_SPEC.md`](docs/PROMPT_DEFINITION_SPEC.md) | プロンプト定義ファイル仕様 |
| [`docs/CLASS_IMPLEMENTATION_SPEC.md`](docs/CLASS_IMPLEMENTATION_SPEC.md) | クラス実装詳細仕様 |
| [`docs/DATABASE_SCHEMA_SPEC.md`](docs/DATABASE_SCHEMA_SPEC.md) | データベーススキーマ仕様 |
| [`docs/STANDARD_MR_PROCESSING_FLOW.md`](docs/STANDARD_MR_PROCESSING_FLOW.md) | 標準MR処理フロー仕様 |
| [`docs/MULTI_MR_PROCESSING_FLOW.md`](docs/MULTI_MR_PROCESSING_FLOW.md) | 複数コード生成並列処理フロー仕様 |
| [`docs/USER_MANAGEMENT_SPEC.md`](docs/USER_MANAGEMENT_SPEC.md) | ユーザー管理・Web管理画面仕様 |
| [`docs/PROMPTS.md`](docs/PROMPTS.md) | 各エージェントのシステムプロンプト |

## セットアップ

### 前提条件

- Docker / Docker Compose
- PostgreSQL 15以上
- RabbitMQ 3.12以上
- Python 3.11以上

### 環境変数

以下の環境変数を設定する（`.env` ファイルまたは環境変数で指定）。

| 変数名 | 説明 |
|-------|------|
| `POSTGRES_PASSWORD` | PostgreSQL パスワード |
| `ENCRYPTION_KEY` | APIキー暗号化用32バイトキー |
| `GITLAB_PAT` | GitLab bot用 Personal Access Token |
| `GITLAB_URL` | GitLab インスタンスURL |
| `RABBITMQ_URL` | RabbitMQ接続URL |

### 起動手順

1. PostgreSQL・RabbitMQを含むDockerコンテナを起動する
2. DBマイグレーションスクリプトを実行してテーブル作成・システムプリセット（standard_mr_processing等）の初期データを投入する（`docs/DATABASE_SCHEMA_SPEC.md` §9参照）
3. ProducerとConsumerを起動する
