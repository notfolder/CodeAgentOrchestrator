# AutomataCodex

GitLab上のIssue/MRを自動的に処理するコードエージェントオーケストレーションシステム。

![AutomataCodex](AutomataCodex.svg)

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
3. 初期管理者ユーザーを作成する（下記「初期管理者ユーザーの作成」を参照）
4. ProducerとConsumerを起動する

### 初期管理者ユーザーの作成

システム初回セットアップ時に管理者ユーザーを作成する必要がある。
CLIツールを使って `backend` コンテナ内で実行する。

```bash
# 対話式モード（推奨）
docker compose exec backend \
  python -m backend.user_management.cli.create_admin

# コマンドライン引数モード
docker compose exec backend \
  python -m backend.user_management.cli.create_admin \
    --username <GitLabユーザー名> \
    --password <パスワード>

# 環境変数モード
docker compose exec -e ADMIN_USERNAME=<GitLabユーザー名> -e ADMIN_PASSWORD=<パスワード> \
  backend python -m backend.user_management.cli.create_admin
```

パスワードは以下の要件を満たす必要がある：

- 8文字以上
- 大文字・小文字・数字・記号をそれぞれ1文字以上含む

作成後、Web管理画面（`http://localhost:<ポート>`）に作成した管理者アカウントでログインできる。
管理画面から一般ユーザーの追加やLLM設定の変更が可能。

### プリセット定義の更新

`docs/definitions/` 配下のJSONファイルを編集した後、以下のコマンドでDB上のプリセットを最新の定義に更新する。
起動時に自動実行される `seed_workflow_definitions` は既存レコードをスキップする（冪等な挿入のみ）ため、編集内容を反映するには本コマンドを手動実行する必要がある。

```bash
docker compose exec backend \
  python -m shared.database.seeds.update_preset_workflow_definitions
```

実行後、更新・新規登録・失敗の件数がログに出力される。
