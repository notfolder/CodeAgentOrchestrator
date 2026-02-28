# GitLab Coding Agent — Agent Framework 設計

## 1. 目的と範囲

### 1.1 目的

GitLabのIssueとMerge Requestを対象として、以下を実現する自律型コーディングエージェントを構築する：

- **Issue→MR自動変換**: Issueにアサインされると自動的にMRを作成し、以降はMR上で作業
- **自動検出・分類**: ラベルベースでのIssue/MR検出とタスク分類
- **内容理解**: LLMによる要求内容の深い理解と意図解析
- **自律的なコード修正・提案**: 計画的なコード生成と修正
- **MR操作の自動化**: コメント、レビュー反映、マージ判定の自動実行
- **ユーザー別設定管理**: メールアドレスベースでのAPIキー管理と設定分離

**重要**: Issueで直接作業は行わず、Issue→MR変換後にMR上で全ての処理を実行する方針を採用。

### 1.2 適用技術

- **Microsoft Agent Framework（Python）**: エージェントオーケストレーション基盤（MR処理のみ）
  - **Graph-based Workflows**: ストリーミング、チェックポイント、human-in-the-loop機能
  - **OpenTelemetry統合**: 分散トレーシング、モニタリング、デバッグ
  - **Middleware System**: リクエスト/レスポンス処理、例外ハンドリング、カスタムパイプライン
  - **Agent Providers**: 複数のLLMプロバイダーサポート
- **Producer/Consumerパターン（coding_agent踏襲）**: タスクキュー管理
  - **RabbitMQ**: 分散タスクキュー（100人規模対応）
  - **Producer**: GitLabからIssue/MR検出、キューに投入
  - **Consumer**: キューからタスク取得、Issue→MR変換またはMR処理
- **GitLab REST API**: GitLab操作の実行
- **LLM**: Azure OpenAI / OpenAI / Ollama / LM Studio
- **MCP (Model Context Protocol)**: ツール実行の標準化
- **PostgreSQL**: ユーザー情報・コンテキストの永続化
- **ファイルベースストレージ**: ツール実行結果やファイル情報の外部出力
- **Docker**: コマンド実行環境とデプロイ基盤

### 1.3 スコープ

本仕様でカバーする範囲：

- **GitLab専用の自動コーディングエージェント（100人規模対応）**
  - Issueにアサインされると自動的にMerge Requestを作成
  - Issue上では作業せず、作成されたMR上で全ての処理を実行
- **Producer/Consumerパターン（coding_agent踏襲）**
  - RabbitMQによる分散タスクキュー管理
  - Producer: Issue/MR検出とキュー投入
  - Consumer: タスク処理（5-10並列実行）
- **ユーザー登録・管理機能（メールアドレスベース）**
- **状態管理とコンテキスト永続化**
  - RabbitMQ: タスクキュー
  - PostgreSQL: Agent Framework Context Storage + ユーザー情報
  - ファイルベースストレージ（ツール実行結果、大規模コンテキスト）
- **プランニングベースの構造化タスク実行（MR処理のみ）**
- **複数ユーザーの同時利用対応（100人規模）**
- **セキュリティとアクセス制御**

**スコープ外**:
- GitHubサポート（GitLab専用）
- Issue上での直接作業（全てMRに変換してから処理）

---

## 2. システムアーキテクチャ

### 2.1 レイヤー構成（Producer/Consumerパターン）

```mermaid
flowchart TB
    subgraph Producer ["Producer Layer（coding_agent踏襲）"]
        P1[定期実行 or Webhook]
        P2[TaskGetterFromGitLab]
        P3[Issue/MR検出]
        P4[ラベルフィルタリング]
        
        P1 --> P2
        P2 --> P3
        P3 --> P4
        P4 --> RabbitMQ
    end
    
    subgraph Queue ["Task Queue Layer"]
        RabbitMQ[RabbitMQ<br/>durable queue]
    end
    
    subgraph Consumer ["Consumer Layer（5-10並列）"]
        C1[TaskHandler]
        C2{Issueか?}
        C3[Issue→MR変換<br/>IssueToMRConverter]
        C4[MR処理<br/>Agent Framework]
        
        RabbitMQ --> C1
        C1 --> C2
        C2 -->|Yes| C3
        C2 -->|No| C4
    end
    
    subgraph Workflow ["MR処理 Workflow Layer（Agent Framework）"]
        W1[Planning Agent]
        W2[Execution Agents]
        W3[Review Agents]
        
        C4 --> W1
        W1 --> W2
        W2 --> W3
    end
    
    subgraph Runtime ["Runtime Layer"]
        DB[(PostgreSQL<br/>Context Storage)]
        FS[File Storage<br/>Tool Results]
        UserAPI[User Config API]
    end
    
    subgraph External ["External Services"]
        GitLab[GitLab API]
        LLM[OpenAI/Azure OpenAI]
        Docker[Docker Runtime]
    end
    
    C3 --> GitLab
    W2 --> GitLab
    W2 --> Docker
    C1 --> DB
    C1 --> FS
    C1 --> UserAPI
    W1 --> LLM
    W2 --> LLM
```

**アーキテクチャの特徴**:
- **Producer/Consumer分離**: coding_agentのパターンを踏襲し、スケーラビリティを確保
- **RabbitMQ必須**: 100人規模での同時利用に対応
- **Consumer並列実行**: 5-10コンテナで並列処理
- **Agent Frameworkは部分的**: MR処理（本フロー）のみで使用

---

### 2.2 データフロー（Producer/Consumer + Issue→MR変換）

#### 2.2.1 Producer: タスク検出＆キューイング

```mermaid
sequenceDiagram
    participant GL as GitLab API
    participant P as Producer<br/>(producer.py)
    participant RMQ as RabbitMQ<br/>(durable queue)
    
    Note over P: 定期実行（30秒〜1分間隔）<br/>or Webhook起動
    P->>GL: Issue/MR一覧取得<br/>(ラベルフィルタリング:<br/>coding_agent, auto_merge等)
    GL-->>P: Issue/MR情報
    P->>P: 処理済みチェック<br/>(処理中ラベル除外:<br/>in_progress, done等)
    loop 未処理タスクごと
        P->>RMQ: タスクエンキュー<br/>(type: issue/mr, id, project_id等)
        P->>GL: 処理中ラベル付与<br/>(in_progress)
    end
    Note over RMQ: タスクはdurable=Trueで永続化
```

**Producer実装（coding_agent踏襲）**:
- `producer.py: produce_tasks()` - タスク検出ロジック
- `producer.py: run_producer_continuous()` - 定期実行ループ
- `queueing.py: get_rabbitmq_connection()` - RabbitMQ接続管理

#### 2.2.2 Consumer: タスク処理（Issue→MR変換 or MR処理）

```mermaid
sequenceDiagram
    participant RMQ as RabbitMQ
    participant C as Consumer<br/>(consumer.py)
    participant TH as TaskHandler<br/>(task_handler.py)
    participant Conv as IssueToMRConverter
    participant WF as Agent Workflow<br/>(MR処理)
    participant GL as GitLab API
    participant LLM as OpenAI/Azure
    participant DB as PostgreSQL
    participant FS as File Storage
    
    RMQ->>C: タスクデキュー
    C->>TH: TaskHandler.handle(task)
    TH->>TH: _should_convert_issue_to_mr()?
    
    alt Issueの場合: 前処理フロー
        TH->>Conv: _convert_issue_to_mr()
        Conv->>DB: ユーザー情報取得
        DB-->>Conv: APIキー/設定
        Conv->>LLM: ブランチ名生成
        LLM-->>Conv: ブランチ名
        Conv->>GL: ブランチ作成
        Conv->>GL: 空コミット作成
        Conv->>GL: MR作成
        GL-->>Conv: MR情報
        Conv->>GL: Issueにコメント（MR作成通知）
        Conv->>GL: Issue Done化
        Conv-->>TH: 変換完了
        TH->>DB: タスクステータス更新(completed)
        Note over TH: 作成されたMRはProducerが<br/>次回検出して処理
    else MRの場合: 本フロー（Agent Framework）
        TH->>WF: Agent Workflow開始
        WF->>DB: コンテキストロード
        DB-->>WF: 過去のコンテキスト
        WF->>FS: ツール実行結果取得
        FS-->>WF: 過去のツール結果
        WF->>LLM: タスク分析＋計画生成
        LLM-->>WF: 実行プラン
        loop アクション実行
            WF->>GL: GitLab API操作（コミット等）
            GL-->>WF: 結果
            WF->>FS: ツール結果保存
            WF->>DB: コンテキスト更新
            WF->>LLM: 結果フィードバック
            LLM-->>WF: 次のアクション
        end
        WF->>DB: 最終状態保存
        WF->>GL: MRにコメント（完了通知）
        WF-->>TH: MR処理完了
        TH->>DB: タスクステータス更新(completed)
    end
    TH-->>C: 処理完了
    C->>RMQ: ACK送信
```

**Consumer実装（coding_agent踏襲）**:
- `consumer.py: consume_tasks()` - タスクデキューロジック
- `consumer.py: run_consumer_continuous()` - Consumer実行ループ
- `handlers/task_handler.py: TaskHandler.handle()` - タスク処理分岐
  - `_should_convert_issue_to_mr()` - Issue判定
  - `_convert_issue_to_mr()` - 前処理フロー実行
  - その他メソッド - 本フロー実行（Agent Framework呼び出し）

---

### 2.3 主要コンポーネント

#### 2.3.1 Producer/Consumer Layer（coding_agent踏襲）

| コンポーネント | 責務 | 実装技術 | coding_agent流用ファイル |
|------------|------|---------|---------------------|
| **Producer** | Issue/MR検出・キューイング | Python + GitLab API + RabbitMQ | `producer.py`はcoding_agentの`main.py`のコードをベースに新規作成<br/>`queueing.py` |
| **Consumer** | タスクデキュー・処理振り分け | Python + RabbitMQ | `consumer.py`はcoding_agentの`main.py`のコードをベースに新規作成<br/>`queueing.py` |
| **TaskHandler** | タスク処理分岐（Issue/MR判定） | Python | `handlers/task_handler.py` |
| **RabbitMQ** | 分散タスクキュー | RabbitMQ（durable queue） | - |
| **TaskGetterFromGitLab** | GitLab API経由タスク取得 | Python + GitLab API | coding_agentのものをそのまま流用 |

#### 2.3.2 Issue→MR変換 Layer（前処理フロー）

| コンポーネント | 責務 | 実装技術 | coding_agentを参考にAgent Frameworkで実装 |
|------------|------|---------|---------------------|
| **IssueToMRConverter** | Issue→MR変換 | Agent Framework Workflow | coding_agentを参考にして、Agent Frameworkのワークフローとして新規実装 |
| **Branch Naming Agent** | ブランチ名生成 | LLM | coding_agentを参考にして、Agent Frameworkのワークフローとして新規実装 |

#### 2.3.3 MR処理 Layer（本フロー - Agent Framework）

| コンポーネント | 責務 | 実装技術 | coding_agent流用ファイル |
|------------|------|---------|---------------------|
| **PlanningCoordinator** | 計画実行制御 | Agent Framework | `handlers/pre_planning_manager.py` 参考 |
| **MCPToolClient** | Agent FrameworkのTextEditorMCPClient等を完全に使用する | Python + MCP | `clients/mcp_tool_client.py` |
| **TextEditorMCPClient** | ファイル編集 | Python + MCP | `clients/text_editor_mcp_client.py` |
| **ExecutionEnvironmentManager** | Docker環境管理 | Python + Docker | `handlers/execution_environment_manager.py` 参考 |
| **LLMClient** | Agent FrameworkのAgent Providersを完全に使用する | OpenAI SDK | `clients/llm_*.py` 参考 |

> 「カスタムツール（todo管理等）はMCPではなくAgent Frameworkのツールとして実装する」

#### 2.3.4 Runtime Layer

| コンポーネント | 責務 | 実装技術 | coding_agent流用ファイル |
|------------|------|---------|---------------------|
| **UserManager** | ユーザー情報・APIキー管理 | PostgreSQL + FastAPI | - |
| **TaskContextManager** | コンテキスト永続化 | File + PostgreSQL | `context_storage/*` |
| **PostgreSQL** | Context Storage + ユーザー情報 | PostgreSQL | - |
| **File Storage** | ツール実行結果保存 | ローカルファイルシステム | - |

---

## 3. ユーザー管理システム

### 3.1 概要

Issue/MRの作成者メールアドレスをキーとして、ユーザーごとのOpenAI APIキーと設定を管理する。これにより、複数ユーザーが同一エージェントシステムを利用しながら、各自のAPIキーとコストを分離できる。

### 3.2 ユーザー登録フロー

```mermaid
sequenceDiagram
    participant Admin as 管理者
    participant Web as Web管理画面
    participant API as User Config API
    participant DB as PostgreSQL
    participant Enc as Encryption Service
    
    Admin->>Web: ユーザー登録
    Web->>API: POST /api/v1/users
    API->>Enc: APIキー暗号化
    Enc-->>API: 暗号化済みキー
    API->>DB: INSERT user, config
    DB-->>API: 成功
    API-->>Web: 登録完了
    Web-->>Admin: 確認画面
```

### 3.3 データベース設計

#### users テーブル

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | INTEGER | PK, AUTO | ユーザーID |
| email | TEXT | UNIQUE, NOT NULL | メールアドレス |
| display_name | TEXT | | 表示名 |
| is_active | BOOLEAN | DEFAULT true | アクティブフラグ |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |

#### user_configs テーブル

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | INTEGER | PK, AUTO | 設定ID |
| user_id | INTEGER | FK(users.id), UNIQUE | ユーザーID |
| llm_provider | TEXT | NOT NULL | LLMプロバイダ |
| openai_api_key_encrypted | TEXT | | 暗号化済みAPIキー |
| openai_model | TEXT | | 使用モデル |
| ollama_endpoint | TEXT | | Ollamaエンドポイント |
| ollama_model | TEXT | | Ollamaモデル |
| lmstudio_base_url | TEXT | | LM StudioベースURL |
| lmstudio_model | TEXT | | LM Studioモデル |
| system_prompt_override | TEXT | | カスタムシステムプロンプト |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |

#### todos テーブル

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | INTEGER | PK, AUTO | Todo ID |
| project_id | TEXT | NOT NULL | GitLabプロジェクトID |
| issue_iid | INTEGER | | Issue IID（NULL許可） |
| mr_iid | INTEGER | | MR IID（NULL許可） |
| parent_todo_id | INTEGER | FK(todos.id) | 親TodoのID（階層構造） |
| title | TEXT | NOT NULL | Todoのタイトル |
| description | TEXT | | Todoの詳細説明 |
| status | TEXT | NOT NULL | 状態（not-started/in-progress/completed/failed） |
| order_index | INTEGER | NOT NULL | 表示順序 |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |
| completed_at | TIMESTAMP | | 完了日時 |

**インデックス**:
- `idx_todos_issue` ON (`project_id`, `issue_iid`)
- `idx_todos_mr` ON (`project_id`, `mr_iid`)
- `idx_todos_parent` ON (`parent_todo_id`)

**制約**:
- CHK: `issue_iid` と `mr_iid` のいずれかが NOT NULL
- CHK: `status` IN ('not-started', 'in-progress', 'completed', 'failed')

### 3.4 APIキー暗号化

- **暗号化方式**: AES-256-GCM
- **キー管理**: 環境変数 `ENCRYPTION_KEY` で管理
- **暗号化範囲**: OpenAI APIキーのみ
- **復号化タイミング**: Consumer実行時にメモリ内で復号化

### 3.5 User Config API

#### エンドポイント

**GET /api/v1/config/{email}**
- Purpose: メールアドレスからユーザー設定を取得
- Authentication: Bearer Token
- Response: ユーザー設定（APIキー復号化済み）

**POST /api/v1/users**
- Purpose: 新規ユーザー登録
- Authentication: Bearer Token (Admin)
- Body: ユーザー情報とLLM設定

**PUT /api/v1/users/{user_id}**
- Purpose: ユーザー設定更新
- Authentication: Bearer Token
- Body: 更新する設定項目

**GET /api/v1/users**
- Purpose: ユーザー一覧取得
- Authentication: Bearer Token (Admin)
- Response: ユーザーリスト

### 3.6 Web管理画面

Streamlitベースの管理画面を提供：

- **ダッシュボード**: 登録ユーザー数、アクティブタスク数
- **ユーザー管理**: ユーザーCRUD操作
- **設定管理**: LLM設定の編集
- **トークン使用量**: ユーザー別トークン消費統計

---

### 3.7 ユーザー別トークン統計処理

coding_agentと同様に、各タスク実行時のトークン消費を記録し、ユーザー別の累計を管理する。

#### token_usageテーブル

```sql
CREATE TABLE token_usage (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    task_uuid TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_token_usage_user_id ON token_usage(user_id);
CREATE INDEX idx_token_usage_task_uuid ON token_usage(task_uuid);
```

Web管理画面では、ユーザー別のトークン使用量の累計・推移を確認できるダッシュボードを提供する。

---

## 4. エージェント構成

### 4.1 エージェント一覧

| エージェント名 | 役割 | 入力 | 出力 |
|--------------|------|------|------|
| Task Classifier Agent | タスク分類 | Issue内容 | コード生成/バグ修正/ドキュメント生成/テスト作成 |
| User Resolver Agent | ユーザー情報取得 | メールアドレス | LLM設定 |
| コード生成 Planning Agent | コード生成タスクの実行計画生成 | タスク内容、仕様書 | コード生成アクションプラン |
| バグ修正 Planning Agent | バグ修正タスクの実行計画生成 | タスク内容、エラー情報 | バグ修正アクションプラン |
| テスト生成 Planning Agent | テスト作成タスクの実行計画生成 | タスク内容、対象コード | テスト作成アクションプラン |
| ドキュメント生成 Planning Agent | ドキュメント生成タスクの実行計画生成 | タスク内容、コードベース | ドキュメント生成アクションプラン |
| Code Generation Agent | コード生成実装 | プラン、仕様書 | 新規コード |
| Bug Fix Agent | バグ修正実装 | プラン、バグ情報 | 修正コード |
| Documentation Agent | ドキュメント作成 | プラン、コードベース | ドキュメントファイル |
| Test Creation Agent | テスト作成 | プラン、対象コード | テストコード |
| Test Execution & Evaluation Agent | テスト実行・評価 | テストコード、対象コード | テスト結果、評価レポート |
| Code Review Agent | コードレビュー実施 | 生成/修正コード | レビュー結果 |
| Documentation Review Agent | ドキュメントレビュー実施 | ドキュメント | レビュー結果 |
| Error Handler Agent | 失敗処理 | エラー情報 | リトライ/通知 |

> 「各エージェントのLLM呼び出し時には、プロンプト冒頭にAGENTS.mdの内容を含める。プロンプト詳細はPROMPTS.mdを参照」

### 4.2 エージェント詳細

#### Producer（タスク検出エージェント）

**責務**: GitLabから処理対象のIssue/MRを検出し、RabbitMQにキューイングする

**処理フロー**:
1. GitLab APIで指定ラベル（coding_agent, auto_merge等）のIssue/MR一覧取得
2. 処理中ラベル（in_progress, done等）が付いていないものをフィルタ
3. 未処理タスクをRabbitMQにエンキュー
4. タスクに処理中ラベル（in_progress）を付与
5. issueのラベルはcoding_agentの慣習（task_label, processing_label等）に従う

**責務**: RabbitMQからタスクをデキューし、Issue→MR変換またはMR処理を実行する

**処理フロー**:
1. RabbitMQからタスクをデキュー
2. TaskHandler.handle()でタスク処理分岐
   - Issueの場合: Issue→MR変換（前処理フロー）
   - MRの場合: Agent Framework Workflow実行（本フロー）
3. 処理完了後、RabbitMQにACK送信
4. タスクに完了ラベル（done）を付与
5. issueのラベルはcoding_agentの慣習（task_label, processing_label等）に従う

#### User Resolver Agent

**責務**: メールアドレスからユーザー設定を取得する

**処理フロー**:
1. User Config APIに問い合わせ (GET /api/v1/config/{email})
2. ユーザーが未登録の場合、issue/mrにエラーコメントを投稿して処理しない
3. APIキーを復号化してLLMクライアントに設定

#### コード生成 Planning Agent

**責務**: タスク内容から実行計画を生成する。プロンプト詳細はPROMPTS.mdを参照

#### バグ修正 Planning Agent

**責務**: タスク内容から実行計画を生成する。プロンプト詳細はPROMPTS.mdを参照

#### テスト生成 Planning Agent

**責務**: タスク内容から実行計画を生成する。プロンプト詳細はPROMPTS.mdを参照

#### ドキュメント生成 Planning Agent

**責務**: タスク内容から実行計画を生成する。プロンプト詳細はPROMPTS.mdを参照

#### Code Generation Agent

**責務**: 新規コードを生成する

**処理フロー**:
1. 仕様書の理解
   - 仕様ファイルの読み込みと解析
   - 要件、設計、インターフェースの把握
   - 既存コードベースとの関係性の理解
2. 設計の詳細化
   - モジュール構成の決定
   - クラス・関数設計
   - データフロー設計
3. コード生成
   - 仕様に基づいた新規ファイル作成
   - 適切なデザインパターンの適用
   - エラーハンドリングの実装
   - MCPツール（Text Editor）を使用したファイル作成
4. 初期テストの作成
   - 基本的な動作確認用テストコード
   - エッジケースの考慮
5. 実行結果のコンテキストへの記録
6. git操作とテスト実行はExecutionEnvironmentManagerを使用して行う

#### Bug Fix Agent
   - エラーメッセージ、スタックトレースの解析
   - 再現手順の理解
   - 影響範囲の特定
2. 根本原因の特定
   - 関連コードの読み込み
   - デバッグ情報の収集
   - 仮説の立案と検証
3. 修正実装
   - 最小限の変更で修正
   - エッジケースの考慮
   - MCPツール（Text Editor）を使用したコード編集
4. 修正の検証
   - テストケースの実行
   - リグレッションチェック
5. 実行結果のコンテキストへの記録
6. git操作とテスト実行はExecutionEnvironmentManagerを使用して行う

#### Documentation Agent

**処理フロー**:
1. ドキュメント要件の理解
   - 対象読者の特定（ユーザー/開発者/運用担当者）
   - ドキュメント種別の判定（README/API仕様/運用手順等）
   - 必要な情報の洗い出し
2. 情報収集
   - コードベースの分析
   - 既存ドキュメントの確認
   - 設定ファイル、コメントの読み込み
3. ドキュメント作成
   - Markdown形式での記述
   - コード例の生成（必要に応じて）
   - Mermaid図の作成（複雑な処理フロー時）
   - MCPツール（Text Editor）を使用したファイル作成
4. 構造化と一貫性の確保
   - 見出し階層の整理
   - 用語の統一
   - リンクの整合性確認
5. 実行結果のコンテキストへの記録

#### Test Creation Agent

**責務**: テストコードを作成する

**処理フロー**:
1. テスト対象の分析
   - 関数/クラス/モジュールの理解
   - 入出力仕様の把握
   - エッジケースの特定
2. テスト戦略の決定
   - テスト種別の選択（ユニット/統合/E2E）
   - カバレッジ目標の設定
   - モック/スタブの必要性判断
3. テストケース作成
   - 正常系テストの実装
   - 異常系テストの実装
   - 境界値テストの実装
   - MCPツール（Text Editor）を使用したテストファイル作成
4. テスト実行と検証
   - テストフレームワークでの実行
   - カバレッジ測定
   - 失敗時の修正
5. 実行結果のコンテキストへの記録
6. git操作とテスト実行はExecutionEnvironmentManagerを使用して行う

#### Test Execution & Evaluation Agent

**処理フロー**:
1. テスト環境のセットアップ
   - テスト実行環境（Docker）の準備
   - 依存関係のインストール
   - 環境変数の設定
   - テストデータの準備
2. テストコードの実行
   - **ユニットテスト**: 個別関数/メソッドのテスト実行
   - **統合テスト**: モジュール間連携のテスト実行
   - **E2Eテスト**: エンドツーエンドのシナリオテスト実行
   - **回帰テスト**: 既存機能の影響確認（バグ修正時）
   - MCPツール（Command Executor）でテストコマンド実行
3. テスト結果の収集
   - 実行結果（成功/失敗）の取得
   - 実行時間の測定
   - カバレッジ情報の取得
   - エラーメッセージ、スタックトレースの収集
4. テスト結果の評価
   - **成功率**: テスト全体の成功率を計算
   - **カバレッジ**: コードカバレッジ率の評価（目標: 80%以上）
   - **失敗原因の分析**:
     - 実装の問題（バグ、ロジックエラー、エラーハンドリング不足）
     - テストの問題（テストケースの誤り、環境依存、タイムアウト）
   - **パフォーマンス**: 実行時間の妥当性評価
5. テスト結果レポートの生成
   - 成功/失敗の詳細レポート作成
   - カバレッジレポートの生成
   - 失敗したテストの詳細（原因、修正提案）
   - GitLabにコメント投稿（テスト結果サマリ）
6. 実行結果のコンテキストへの記録

プロンプト詳細はPROMPTS.mdを参照

#### Code Review Agent

**責務**: コードレビューを実施する

**処理フロー**:
1. MR差分の取得
   - GitLab APIでMR差分を取得
   - 変更ファイルのリスト化
   - 変更規模の把握
2. コード品質チェック
   - コーディング規約準拠確認
   - 命名規則の検証
   - コードの可読性評価
   - 重複コードの検出
3. ロジックレビュー
   - バグやエッジケースの洗い出し
   - パフォーマンスの考慮事項
   - セキュリティリスクの確認
   - エラーハンドリングの妥当性
4. テストカバレッジ確認
   - テストコードの有無
   - テストの網羅性
5. レビューコメント生成
   - 具体的な改善提案
   - コード例の提示
   - LLMの応答をシステムがMRコメントとしてGitLab API経由で投稿
プロンプト詳細はPROMPTS.mdを参照

#### Documentation Review Agent

**責務**: ドキュメントレビューを実施する

**処理フロー**:
1. ドキュメント差分の取得
   - GitLab APIでMR差分を取得
   - 変更されたドキュメントファイルの特定
2. 内容の正確性チェック
   - コードとの整合性確認
   - 技術的な誤りの検出
   - 設定値や例の妥当性確認
3. 構造と可読性のチェック
   - 見出し階層の適切性
   - 段落構成の妥当性
   - 用語の統一性
   - コード例の動作確認
4. 完全性のチェック
   - 必要な情報の網羅性
   - リンク切れの確認
   - 図表の適切性
5. レビューコメント生成
   - 具体的な修正提案
   - 改善例の提示
   - LLMの応答をシステムがMRコメントとしてGitLab API経由で投稿
プロンプト詳細はPROMPTS.mdを参照

---

## 5. ワークフロー（プランニングベース）

### 5.0 Issue→MR変換フロー（前処理）

Issueにアサインされた場合、実際の処理を開始する前に自動的にMerge Requestへ変換する。

#### 5.0.1 変換条件

- タスクがIssueタイプである
- Issue→MR変換機能が有効化されている（config設定）
- 処理対象ラベル（例: `coding agent`）が付与されている

#### 5.0.2 変換処理フロー

```mermaid
flowchart TD
    Start([Issue検出]) --> GetIssue[Issue情報収集]
    GetIssue --> GenBranch[LLM: ブランチ名生成]
    GenBranch --> CheckBranch{ブランチ名<br/>重複チェック}
    CheckBranch -->|重複| GenBranch
    CheckBranch -->|OK| CreateBranch[GitLab: ブランチ作成]
    CreateBranch --> EmptyCommit[GitLab: 空コミット作成]
    EmptyCommit --> CreateMR[GitLab: MR作成]
    CreateMR --> NotifyIssue[元Issueに通知コメント]
    NotifyIssue --> UpdateStatus[Issue Done化]
    UpdateStatus --> SaveDB[DB: ステータス更新<br/>completed]
    SaveDB --> End([変換完了<br/>MRは次回処理])
```

#### 5.0.3 IssueToMRConverter（Agent Frameworkワークフロー）

coding_agentを参考にして、Agent Frameworkのワークフローとして実装する。clients/gitlab_client.pyはそのまま流用する。

| コンポーネント | 参照元 | 役割 |
|----------------|-----------|------|
| **IssueToMRConverter** | `handlers/issue_to_mr_converter.py` | Issue→MR変換のメインクラス |
| **BranchNameGenerator** | `handlers/issue_to_mr_converter.py` | LLMを使用したブランチ名生成 |
| **ContentTransferManager** | `handlers/issue_to_mr_converter.py` | IssueコメントのMRへの転記 |
| **GitlabClient** | `clients/gitlab_client.py` | GitLab API操作（ブランチ、コミット、MR作成） |

#### 5.0.4 処理詳細

1. **Issue情報収集** (`_collect_issue_info()`):
   - Issueタイトル、説明、ラベル、アサイン者を取得

2. **ブランチ名生成** (`BranchNameGenerator.generate()`):
   - LLMにIssue情報を渡してブランチ名を生成
   - 英数字とハイフンのみ、最大50文字
   - 予約語（main, master, develop等）は禁止
   - 既存ブランチとの重複チェック

3. **ブランチ作成** (`GitlabClient.create_branch()`):
   - ベースブランチ（デフォルト: main）から新ブランチを作成

4. **空コミット作成** (`_create_empty_commit()`):
   - 初回コミットを作成（MR作成に必要）

5. **MR作成** (`GitlabClient.create_merge_request()`):
   - タイトル: Issueのタイトル
   - 説明: `この MR は Issue #<issue_iid> から自動生成されました。`
   - ドラフト: 設定に応じて自動設定
   - アサイン: 元Issueのアサイン者

6. **コンテンツ転記** (`ContentTransferManager.transfer()`):
   - Issueの説明をMRの説明に追加
   - Issueのコメントを直近50件までMRにコピー

7. **元Issueに通知** (`_notify_source_issue()`):
   - Issueに「MR #<mr_iid> を作成しました」とコメント

8. **自動タスク化設定** (`_setup_auto_task()`):
   - 設定により、MRにbotラベル（例: `coding agent`）を追加
   - 次回スケジューリングで自動的に処理対象となる

9. **Issue Done化**:
   - Issueに`done`ラベルを追加、または状態をクローズ

#### 5.0.5 エラーハンドリング

- ブランチ作成失敗: リトライ（最大3回）
- MR作成失敗: ブランチクリーンアップ後、Issueにエラーコメント
- LLMエラー: ブランチ名をフォールバック生成（`issue-<iid>-<uuid>`）

---

### 5.1 全体フロー（MR処理）

**注**: Issue→MR変換後、作成されたMRは次回のワークフロー実行時に以下のフローで処理される。

```mermaid
flowchart TD
    Start([タスク開始]) --> Fetch[MR情報取得<br/>Consumer]
    Fetch --> UserResolve[ユーザー情報取得<br/>User Resolver Agent]
    UserResolve --> PrePlanning[計画前情報収集<br/>+ タスク分類<br/>Task Classifier Agent]
    
    PrePlanning --> TaskType{タスク種別判定}
    
    TaskType -->|バグ修正| BugFixFlow[バグ修正フロー]
    TaskType -->|ドキュメント生成| DocFlow[ドキュメント生成フロー]
    TaskType -->|テスト作成| TestFlow[テスト作成フロー]
    TaskType -->|コード生成| SpecCheck[仕様書確認]
    
    SpecCheck --> |仕様書なし| DocFlow
    SpecCheck --> |仕様書あり| CodeGenFlow[コード生成フロー]
    CodeGenFlow --> Planning[計画<br/>Planning Agent]
    DocFlow --> Planning
    BugFixFlow --> Planning
    TestFlow --> Planning
    
    Planning --> TodoPost[Todo投稿]
    
    TodoPost --> Execute{タスク実行}
    Execute -->|コード生成| CodeGen[Code Generation Agent]
    Execute -->|バグ修正| BugFix[Bug Fix Agent]
    Execute -->|ドキュメント生成| DocGen[Documentation Agent]
    Execute -->|テスト作成| TestGen[Test Creation Agent]
    
    CodeGen --> CodeReview[Code Review Agent<br/>コードレビュー]
    BugFix --> CodeReview
    TestGen --> CodeReview
    DocGen --> DocReview[Doc Review Agent<br/>ドキュメントレビュー]
    
    CodeReview --> Reflection[リフレクション<br/>Planning Agent]
    DocReview --> Reflection
    
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 問題なし/軽微| Complete{完了?}
    
    Complete -->|No 追加作業| Execute
    Complete -->|Yes| Finish[タスク完了]
    
    Finish --> End([終了])
```

**主要ノード構成**:

| フェーズ | 使用エージェント | 目的 |
|---------|---------------|------|
| Issue/MR取得 | Consumer | RabbitMQからタスクデキュー |
| ユーザー情報取得 | User Resolver Agent | APIキー・設定取得 |
| 計画前情報収集 | Task Classifier Agent | タスク種別判定（4種類） |
| 計画 | Planning Agent | 実行プラン生成 |
| 実行 | Code Generation/Bug Fix/Documentation/Test Creation Agent | タスク実装 |
| レビュー | Code/Documentation Review Agent | 品質確認 |
| テスト実行・評価 | Test Execution & Evaluation Agent | テスト実行・結果評価（コード生成/バグ修正のみ） |
| リフレクション | Planning Agent | 結果評価・再計画判断 |

**重要なフロー特性**:

1. **仕様ファイル必須（コード生成系）**: コード生成、バグ修正、テスト作成で仕様ファイルがなければドキュメント生成計画を立案し、仕様書作成後に元の計画に戻る
2. **共通の計画フェーズ**: ドキュメント生成後は同じPlanning Agentで元のタスクの計画を再立案
3. **自動レビュー**: 実行後に必ずレビューエージェントが品質確認（ユーザー承認不要）
4. **再計画ループ**: レビューで重大な問題があれば計画フェーズに戻る
5. **タスク種別別分岐**: 4種類のタスクに応じて適切なエージェントを起動

### 5.2 フェーズ詳細

#### 5.2.1 計画前情報収集フェーズ

**目的**: タスク種別を判定し、計画に必要な情報を収集する

**使用エージェント**: Task Classifier Agent

**実行内容**:
1. Issue/MR内容の解析
   - タイトル、説明文、ラベルの分析
   - 添付ファイル、コメントの確認
2. タスク種別の判定
   - **コード生成**: 新規機能実装、新規ファイル作成の要求
   - **バグ修正**: エラーメッセージ、スタックトレース、再現手順が含まれる
   - **ドキュメント生成**: README、API仕様、運用手順等のドキュメント要求
   - **テスト作成**: テストコード、テストケース追加の要求
3. リポジトリ構造の把握
4. 関連ファイルの特定

プロンプト詳細はPROMPTS.mdを参照

#### 5.2.2 計画フェーズ

**目的**: タスク種別に応じた実行可能なアクションプランを生成する

**使用エージェント**: Planning Agent

**実行内容**:
1. 目標の明確化 (Goal Understanding)
2. タスク分解 (Task Decomposition)
3. アクション系列生成 (Action Sequence Generation)
4. **Todoリストの作成**: `create_todo_list` ツールで構造化
5. **仕様ファイル確認**: 
   - コード生成系タスク（バグ修正、テスト作成）の場合、関連する仕様/設計ファイル（Markdown）の存在確認
   - ファイルパス: `docs/SPEC_*.md`, `docs/DESIGN_*.md`, `SPECIFICATION.md` 等
6. 依存関係の定義

**出力形式** (JSON):
```json
{
  "goal": "目標の明確な記述",
  "task_type": "code_generation",
  "spec_file_path": "docs/SPEC_USER_AUTH.md",
  "spec_file_exists": false,
  "transition_to_doc_generation": true,
  "success_criteria": ["成功基準1", "成功基準2"],
  "subtasks": [
    {
      "id": "task_1",
      "description": "サブタスクの説明",
      "dependencies": []
    }
  ],
  "actions": [
    {
      "action_id": "action_1",
      "task_id": "task_1",
      "agent": "code_generation_agent",
      "tool": "create_file",
      "purpose": "アクションの目的"
    }
  ]
}
```

**仕様ファイルがない場合の処理**:
- コード生成系タスク（`code_generation`, `bug_fix`, `test_creation`）で `spec_file_exists: false` の場合
- Planning Agentがドキュメント生成のための計画を立案
- Documentation Agent → Documentation Review Agent で仕様書を作成
- リフレクションで問題があれば再計画（ドキュメント生成）
- 問題なければ仕様書作成完了で終了（コード生成/バグ修正/テスト作成は実行しない）

#### 5.2.3 仕様書作成サブフロー（条件付き）

仕様ファイルが存在しない場合はドキュメント生成ワークフロー（5.3.3）を最初から実行する。

仕様書作成後にコード実装を行う場合は新たなIssue/MRを作成する。

#### 5.2.4 実行フェーズ

**目的**: 計画されたアクションを実行する

**使用エージェント**: Code Generation Agent / Bug Fix Agent / Documentation Agent / Test Creation Agent

**実行内容**:
1. タスク種別別実行
   - **Code Generation Agent**: 新規コード生成
   - **Bug Fix Agent**: バグ修正実装
   - **Documentation Agent**: ドキュメント作成
   - **Test Creation Agent**: テストコード作成
2. **進捗報告** (各ステップでMRにコメント投稿)
   - 現在のフローステータスをMRにコメント
   - LLMの応答をMRコメントとして投稿
   - エラー発生時の詳細情報もコメントで通知
3. 結果記録
   - 実行結果のコンテキスト保存
   - **Todo状態更新**: `update_todo_status` ツールで更新
   - **GitLabへの進捗同期**: `sync_to_gitlab` ツールで反映

**注意**: LLMは直接GitLab APIを呼び出すことはしません。LLMの応答（コード生成結果、レビューコメント等）はシステム側が処理し、GitLab API経由でIssue/MRにコメントとして投稿します。

**リトライポリシー**:
- HTTP 5xx エラー: 3回リトライ (指数バックオフ)
- ツール実行エラー: 2回リトライ
- LLM APIエラー: 3回リトライ

#### 5.2.5 レビューフェーズ

**目的**: 実装の品質を確認する

**使用エージェント**: Code Review Agent / Documentation Review Agent

**実行内容**:
1. **タスク種別による分岐**
   - コード生成・バグ修正・テスト作成 → Code Review Agent
   - ドキュメント生成 → Documentation Review Agent
2. **Code Review Agentの場合**
   - コード品質チェック（規約準拠、命名規則）
   - ロジックレビュー（バグ、パフォーマンス）
   - テストカバレッジ確認
   - セキュリティリスク確認
   - 仕様書との整合性確認
3. **Documentation Review Agentの場合**
   - 内容の正確性
   - 構造と可読性
   - 完全性
   - コードとの整合性
4. **レビュー結果の判定**
   - **問題なし**: テスト実行・評価フェーズへ（コード生成・バグ修正の場合）またはリフレクションへ（ドキュメント生成・テスト作成の場合）
   - **軽微な問題**: リフレクションで修正アクション生成
   - **重大な問題**: リフレクションで再計画判断

#### 5.2.6 テスト実行・評価フェーズ（コード生成・バグ修正のみ）

**目的**: 実装したコードの動作を検証し、テスト結果を評価する

**使用エージェント**: Test Execution & Evaluation Agent

**適用タスク**: コード生成、バグ修正（ドキュメント生成、テスト作成では実行しない）

**実行内容**:
1. **テスト環境のセットアップ**
   - Docker環境の準備
   - 依存関係のインストール
   - テストデータの準備
2. **テストコードの実行**
   - 既存のテストコードを実行（ユニット、統合、E2E）
   - バグ修正の場合は回帰テストを重点的に実施
   - テスト実行時間の測定
3. **テスト結果の収集**
   - 成功/失敗の判定
   - カバレッジ情報の取得
   - エラーメッセージ、スタックトレースの収集
4. **テスト結果の評価**
   - **成功率**: 全テスト成功 → リフレクションフェーズへ
   - **失敗時**: 失敗原因の分析
     - 実装の問題（バグ、ロジックエラー）→ 実装フェーズに戻って修正
     - テストの問題（テストケースの誤り）→ Test Creation Agentでテスト修正
   - **カバレッジ**: 80%以上を目標、不足時は追加テスト作成を提案
5. **テスト結果レポートの生成**
   - GitLabにコメント投稿（テスト結果サマリ、カバレッジ情報）
   - 失敗時は詳細な原因と修正提案を記載
6. **結果の記録**
   - テスト結果をコンテキストに保存
   - Todo状態更新

**分岐ロジック**:
- **テスト成功** → リフレクションフェーズへ
- **テスト失敗（実装の問題）** → 実行フェーズへ（コード修正）
- **テスト失敗（テストの問題）** → テスト修正後、再度テスト実行

#### 5.2.7 リフレクションフェーズ

**目的**: レビュー結果を評価し、再計画の必要性を判断する

**使用エージェント**: Planning Agent

**実行タイミング**:
- レビューで問題が検出された時
- アクション失敗時
- ユーザーコメント受信時

**評価項目**:
- レビューコメントの重大度
- 修正の複雑さ
- 計画との乖離
- 代替アプローチの検討

**出力形式**:
```json
{
  "reflection": {
    "status": "success|needs_revision|needs_replan",
    "review_issues": [
      {
        "severity": "critical|major|minor",
        "description": "指摘内容",
        "suggestion": "修正提案"
      }
    ],
    "plan_revision_needed": false,
    "revision_actions": [
      {
        "action_id": "revision_1",
        "purpose": "レビュー指摘への対応",
        "agent": "code_generation_agent"
      }
    ],
    "replan_reason": "アプローチの根本的な変更が必要"
  }
}
```

**分岐ロジック**:
- `success` → 完了処理へ
- `needs_revision` (軽微な問題) → 実行フェーズへ（修正アクション）
- `needs_replan` (重大な問題) → 計画フェーズへ（再計画ループ）

**再計画判断基準**:
- **needs_replan**: アーキテクチャの根本的な問題、仕様との大幅な乖離、セキュリティの重大な欠陥
- **needs_revision**: コーディング規約違反、軽微なバグ、ドキュメントの不備

---

### 5.3 タスク種別別詳細フロー

#### 5.3.1 コード生成フロー

```mermaid
flowchart TD
    Start[コード生成タスク開始] --> Planning[Planning Agent<br/>実行計画生成]
    Planning --> SpecCheck{仕様ファイル確認}
    
    SpecCheck -->|存在する| Todo[Todo投稿]
    SpecCheck -->|存在しない| End1([ドキュメント生成フロー])
        
    Todo --> CodeGen[Code Generation Agent<br/>コード生成実装]
    CodeGen --> CodeReview[Code Review Agent<br/>コードレビュー]
    
    CodeReview --> TestExec[Test Execution &<br/>Evaluation Agent<br/>テスト実行・評価]
    
    TestExec --> TestResult{テスト結果}
    TestResult -->|成功| Reflection[Reflection<br/>リフレクション]
    TestResult -->|失敗| TestReflection[Reflection<br/>テスト失敗分析]
    
    TestReflection --> TestReplan{再計画必要?}
    TestReplan -->|Yes 実装の問題| CodeGen
    TestReplan -->|テストの問題| TestCreate[Test Creation Agent<br/>テスト修正]
    TestCreate --> TestExec
    
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| CodeGen
    Complete -->|Yes| Finish[完了]
    Finish --> End2([終了])
```

**フロー詳細**:
1. Planning Agentが実行計画を生成
2. 関連する仕様ファイルの存在確認
3. **仕様ファイルがない場合**:
   - Planning Agentがドキュメント生成計画を立案
   - Documentation Agentが仕様書を作成
   - Documentation Review Agentが自動レビュー（ユーザー承認不要）
   - リフレクションで問題があれば再計画（ドキュメント生成）
   - 問題なければ仕様書作成完了で終了（コード生成は実行しない）
4. **仕様ファイルがある場合**:
   - Code Generation Agentが新規コード生成
   - Code Review Agentがコードレビュー（仕様書との整合性を含む）
   - **Test Execution & Evaluation Agentがテスト実行・評価**
     - 既存のテストコードを実行（ユニット、統合、E2E）
     - テスト結果を評価（成功率、カバレッジ、失敗原因）
     - **テスト失敗時**: Reflectionで原因分析
       - 実装の問題 → Code Generation Agentに戻って修正
       - テストの問題 → Test Creation Agentでテスト修正
     - **テスト成功時**: リフレクションフェーズへ進む
   - リフレクションで問題を評価
     - 重大な問題（アーキテクチャ、仕様乖離）→ 再計画
     - 軽微な修正（コーディング規約）→ 修正後完了チェック
   - 問題なければ完了

#### 5.3.2 バグ修正フロー

```mermaid
flowchart TD
    Start[バグ修正タスク開始] --> Planning[Planning Agent<br/>実行計画生成]
    Planning --> SpecCheck{仕様ファイル確認}
    
    SpecCheck -->|存在する| Todo[Todo投稿]
    SpecCheck -->|存在しない| End1([ドキュメント生成フロー])
    
    Todo --> BugFix[Bug Fix Agent<br/>バグ修正実装]
    BugFix --> CodeReview[Code Review Agent<br/>コードレビュー]
    
    CodeReview --> TestExec[Test Execution &<br/>Evaluation Agent<br/>テスト実行・評価]
    
    TestExec --> TestResult{テスト結果}
    TestResult -->|成功| Reflection[Reflection<br/>リフレクション]
    TestResult -->|失敗| TestReflection[Reflection<br/>テスト失敗分析]
    
    TestReflection --> TestReplan{再計画必要?}
    TestReplan -->|Yes 修正の問題| BugFix
    TestReplan -->|テストの問題| TestCreate[Test Creation Agent<br/>テスト修正]
    TestCreate --> TestExec
    
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| BugFix
    Complete -->|Yes| Finish[完了]
    Finish --> End2([終了])
```

**フロー詳細**:
1. Planning Agentが実行計画を生成
2. 関連する仕様ファイル（バグ修正対象機能の仕様）の存在確認
3. **仕様ファイルがない場合**:
   - Planning Agentがドキュメント生成計画を立案
   - Documentation Agentが仕様書を作成
   - Documentation Review Agentが自動レビュー（ユーザー承認不要）
   - リフレクションで問題があれば再計画（ドキュメント生成）
   - 問題なければ仕様書作成完了で終了（バグ修正は実行しない）
4. **仕様ファイルがある場合**:
   - Bug Fix Agentがバグ修正を実装
   - Code Review Agentがコードレビュー（仕様書との整合性を含む）
   - **Test Execution & Evaluation Agentがテスト実行・評価**
     - 既存のテストコードを実行（回帰テスト含む）
     - テスト結果を評価（バグ修正の検証、副作用の検出）
     - **テスト失敗時**: Reflectionで原因分析
       - 修正の問題（バグが残っている、新たなバグ）→ Bug Fix Agentに戻って修正
       - テストの問題（テストケースの誤り）→ Test Creation Agentでテスト修正
     - **テスト成功時**: リフレクションフェーズへ進む
   - リフレクションで問題を評価
     - 重大な問題（根本原因の誤認識）→ 再計画
     - 軽微な修正（コーディング規約）→ 修正後完了チェック
   - 問題なければ完了

#### 5.3.3 ドキュメント生成フロー

```mermaid
flowchart TD
    Start[ドキュメント生成タスク開始] --> Planning[Planning Agent<br/>実行計画生成]
    Planning --> Todo[Todo投稿]
    
    Todo --> DocCreate[Documentation Agent<br/>ドキュメント作成]
    DocCreate --> DocReview[Doc Review Agent<br/>ドキュメントレビュー]
    
    DocReview --> Reflection[Reflection<br/>リフレクション]
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| DocCreate
    Complete -->|Yes| Finish[完了]
    Finish --> End([終了])
```

**フロー詳細**:
1. Planning Agentが実行計画を生成
2. Documentation Agentがドキュメントを作成（README、API仕様、運用手順、仕様書等）
3. Documentation Review Agentが自動レビュー（正確性、構造、完全性）
4. リフレクションで問題を評価
   - 重大な問題（技術的誤り、構造の欠陥）→ 再計画
   - 軽微な修正（表記ゆれ、リンク切れ）→ 修正後完了チェック
5. 問題なければ完了

**注意**: ドキュメント生成タスクでは仕様ファイル確認は不要（作成するのがドキュメント自体のため）

#### 5.3.4 テスト作成フロー

```mermaid
flowchart TD
    Start[テスト作成タスク開始] --> Planning[Planning Agent<br/>実行計画生成]
    Planning --> SpecCheck{仕様ファイル確認}
    
    SpecCheck -->|存在する| Todo[Todo投稿]
    SpecCheck -->|存在しない| End1([ドキュメント生成フロー])
    
    Todo --> TestCreate[Test Creation Agent<br/>テスト作成]
    TestCreate --> CodeReview[Code Review Agent<br/>コードレビュー]
    
    CodeReview --> Reflection[Reflection<br/>リフレクション]
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| TestCreate
    Complete -->|Yes| Finish[完了]
    Finish --> End2([終了])
```

**フロー詳細**:
1. Planning Agentが実行計画を生成
2. テスト対象コードの仕様ファイルの存在確認
3. **仕様ファイルがない場合**:
   - Planning Agentがドキュメント生成計画を立案
   - Documentation Agentが仕様書を作成
   - Documentation Review Agentが自動レビュー（ユーザー承認不要）
   - リフレクションで問題があれば再計画（ドキュメント生成）
   - 問題なければ仕様書作成完了で終了（テスト作成は実行しない）
4. **仕様ファイルがある場合**:
   - Test Creation Agentがテストコードを作成（ユニット/統合/E2E）
   - Code Review Agentがテストコードをレビュー（網羅性、品質、仕様書との整合性）
   - リフレクションで問題を評価
     - 重大な問題（テスト戦略の誤り）→ 再計画
     - 軽微な修正（テストケースの追加）→ 修正後完了チェック
   - 問題なければ完了

---

### 5.4 仕様ファイル管理

#### 5.4.1 仕様ファイル命名規則

コード生成系タスク（コード生成、バグ修正、テスト作成）では、以下の命名規則で仕様ファイルを探索：

```
docs/SPEC_<機能名>.md
docs/DESIGN_<機能名>.md
docs/specifications/<機能名>.md
SPECIFICATION.md
README.md (関連セクション)
```

**例**:
- ユーザー認証機能 → `docs/SPEC_USER_AUTH.md`
- API設計 → `docs/DESIGN_API.md`
- データベース → `docs/SPEC_DATABASE.md`

#### 5.4.2 仕様ファイル作成テンプレート

Documentation Agentが仕様を作成する際のテンプレート：

**セクション構成**:
1. **概要**: 機能の目的と概要
2. **要件**: 機能要件、非機能要件
3. **設計**: アーキテクチャ図（mermaid）、データモデル、インターフェース
4. **実装詳細**: 具体的な処理フロー、アルゴリズム
5. **テスト方針**: テストケース、カバレッジ目標

**アーキテクチャ図の例**:
- mermaid形式のフローチャート、シーケンス図、クラス図を使用
- コンポーネント間の関係性を明示

#### 5.4.3 自動レビュープロセス

仕様ファイル作成後の自動レビューフロー：

1. Documentation Agentが仕様を作成
2. Documentation Review Agentが自動レビュー
   - 内容の正確性（技術的な誤りがないか）
   - 構造の妥当性（見出し階層、セクション構成）
   - 完全性（必要な情報が網羅されているか）
   - コードとの整合性（既存コードとの矛盾がないか）
3. リフレクションで問題を評価
   - **重大な問題**: 技術的誤り、仕様の矛盾 → 再計画（ドキュメント生成計画へ戻る）
   - **軽微な問題**: 表記ゆれ、構造の改善 → 修正後に元のタスクへ復帰
   - **問題なし**: 元のタスク（コード生成/バグ修正/テスト作成）へ復帰
4. 元のタスクの計画フェーズに戻り、作成した仕様書を使用して再計画

**ユーザー承認は不要**: Documentation Review Agentの自動レビューのみで判断し、即座に次フェーズへ進む

---

## 6. 進捗報告機能

### 6.1 概要

coding_agentと同様に、各フェーズでの進捗状況をMRにコメントとして投稿し、ユーザーに可視性を提供します。

### 6.2 報告タイミング

以下のタイミングでMRにコメント投稿：

1. **タスク開始時**
   - メッセージ: "🚀 タスク処理を開始します: [task_type]"
   - 内容: タスク種別、担当エージェント、開始時刻

2. **計画フェーズ完了**
   - メッセージ: "📋 実行計画を生成しました"
   - 内容: 主要ステップのサマリ、Todoリストへのリンク

3. **仕様ファイルチェック結果**
   - メッセージ: "📄 仕様ファイル: [found/not_found]"
   - 内容: ファイルパスまたはドキュメント生成への遷移通知

4. **各ステップ実行中**
   - メッセージ: "⏳ [step_name] を実行中..."
   - 内容: 現在のステップ、進捗率

5. **LLM応答の要約**
   - メッセージ: "🤖 LLM応答"
   - 内容: コード生成結果のサマリ、修正内容の要約

6. **レビュー結果**
   - メッセージ: "🔍 コードレビュー結果"
   - 内容: 問題点のリスト、修正提案

7. **テスト実行結果**
   - メッセージ: "✅ テスト結果: [success/failure]"
   - 内容: 成功率、カバレッジ、失敗詳細

8. **エラー発生時**
   - メッセージ: "❌ エラー発生: [error_type]"
   - 内容: エラーメッセージ、スタックトレース、リトライ情報

9. **タスク完了時**
   - メッセージ: "✨ タスク完了"
   - 内容: 実行時間、主要な変更のサマリ、次のアクション

### 6.3 コメントフォーマット

```markdown
### 🚀 タスク開始: コード生成

- **タスク種別**: code_generation
- **担当エージェント**: Code Generation Agent
- **開始時刻**: 2026-02-28 14:30:00 UTC

---

### 📋 実行計画生成完了

以下のステップで実行します：
1. ユーザー認証機能の実装
2. APIエンドポイントの作成
3. テストコードの作成

[Todoリストを表示](#todo-list)

---

### 📄 仕様ファイル確認

✅ 仕様ファイルを発見: `docs/SPEC_USER_AUTH.md`

---

### ⏳ コード生成中...

進捗: 1/3 - ユーザー認証機能の実装

---

### 🤖 LLM応答サマリ

以下のファイルを作成しました：
- `src/auth/user_auth.py` - 認証ロジック
- `src/auth/token_manager.py` - トークン管理

<details>
<summary>生成されたコードの詳細</summary>

```
# コードのサンプル...
```

</details>

---

### 🔍 コードレビュー結果

**結果**: 問題なし

---

### ✅ テスト実行結果

- **成功率**: 100% (25/25)
- **カバレッジ**: 87%
- **実行時間**: 12.5s

---

### ✨ タスク完了

- **実行時間**: 8分15秒
- **変更ファイル**: 5ファイル
- **コミット**: `abc123f`

次のアクション: MRのレビューをお願いします。
```

### 6.4 実装方法

ProgressReporterクラスを実装し、各エージェントから呼び出す。coding_agentのコードを参考にして実装する。

**ProgressReporterクラスの責務**:
- タスクの進捗状況をMRコメントとして投稿する
- コンテキストストレージに進捗ログを記録する
- フェーズ（start, planning, execution, review, test, complete, error）に応じたコメントフォーマットを生成する

**主要メソッド**:
- `report_progress(mr_iid, phase, message, details)`: 指定フェーズの進捗コメントをMRに投稿する
- `format_progress_comment(phase, message, details)`: フェーズとメッセージからMarkdown形式のコメントを生成する
- `add_progress_log(mr_iid, phase, message, details)`: 進捗情報をコンテキストストレージに記録する

### 6.5 進捗報告のメリット

1. **可視性**: ユーザーがエージェントの進捗をリアルタイムで確認できる
2. **デバッグ性**: 問題発生時にどのフェーズでエラーが起きたか明確
3. **信頼性**: エージェントが止まっているのか、実行中なのかが分かる
4. **学習**: 過去のタスク実行履歴を確認でき、改善に役立つ

---

## 7. GitLab API 操作設計

### 7.1 実装方針

GitLab API操作はcoding_agentの`clients/gitlab_client.py`を参照して実装する。

**重要**: PATは必ずユーザー毎のPersonal Access Tokenを使用する。`GITLAB_PERSONAL_ACCESS_TOKEN`などの共有トークンは使用しない。

### 7.2 GitlabClientクラスの責務

- ユーザー毎のPersonal Access Tokenを使用してGitLab REST APIを呼び出す
- Issue・MR・ブランチ・コミット・コメント等の各種GitLab操作をメソッドとして提供する
- リトライ・エラーハンドリングを内包し、呼び出し元から透過的に利用できるようにする
- レスポンスを適切なデータクラスに変換して返す

### 7.3 主要メソッドグループ

**Issue操作**:
- 指定ラベルのIssue一覧取得、Issue詳細取得、Issueへのコメント追加、Issueラベル更新

**MR操作**:
- 指定ラベルのMR一覧取得、MR作成、MRへのコメント追加・更新、MRマージ

**ブランチ操作**:
- ブランチ作成、ブランチ存在確認

**リポジトリ操作**:
- ファイル内容取得、ファイルツリー取得、コミット作成

**コメント操作**:
- Issue/MRへの進捗コメント投稿・更新

### 7.4 エラーハンドリングポリシー

| HTTPステータス | 対応 |
|-------------|------|
| 401 Unauthorized | トークン再確認、エラー通知 |
| 403 Forbidden | 権限不足エラー、処理中断 |
| 404 Not Found | リソース不存在、エラー通知 |
| 409 Conflict | 競合エラー、リトライ |
| 429 Too Many Requests | レート制限、指数バックオフ |
| 500 Internal Server Error | 3回リトライ、失敗時は通知 |
| 502/503/504 | 3回リトライ、バックオフ |

---

## 8. 状態管理設計

### 8.1 Agent Framework標準機能の活用

Microsoft Agent Frameworkは以下の標準機能を提供しており、本システムで活用する：

#### **Graph-based Workflows**
- **Checkpointing**: ワークフロー実行中の状態を自動保存
- **Time-travel**: 過去の状態へのロールバック
- **Streaming**: リアルタイムの実行状況配信
- **Human-in-the-loop**: 必要に応じてユーザー介入ポイントを設定

#### **State Management**
- **Workflow State**: Agent Frameworkが管理する実行状態
- **Conversation State**: エージェント間のメッセージ履歴
- **Tool State**: ツール実行履歴と結果

本システムでは、Agent Frameworkの標準機能に加えて以下を実装する：

### 8.2 コンテキストストレージ

ContextStoreクラスを基底クラスとして、FileStoreとSqlStoreをメンバーとして持つ構成とする。

- **SqlStore**: 過去のコンテキスト（LLMの会話履歴、プランニング履歴、メタデータ）を保存する
- **FileStore**: 過去のツール実行結果（ファイル読み込み結果、コマンド実行結果）を保存する

コンテキスト復元時はSqlStoreから過去のコンテキストを取得し、FileStoreから過去のツール実行結果を取得して、合成したコンテキストを構築する。

#### SqlStoreのデータ設計

```sql
CREATE TABLE context_messages (
    id SERIAL PRIMARY KEY,
    task_uuid TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tokens INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE context_planning_history (
    id SERIAL PRIMARY KEY,
    task_uuid TEXT NOT NULL,
    phase TEXT NOT NULL,
    plan JSONB,
    action_id TEXT,
    result TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE context_metadata (
    task_uuid TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    task_identifier TEXT NOT NULL,
    repository TEXT NOT NULL,
    user_email TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP
);
```

#### FileStoreのデータ設計（ディレクトリ構造）

```
file_store/
├── {task_uuid}/
│   ├── file_reads/              # ファイル読み込み結果
│   │   └── {timestamp}_{path}.json
│   ├── command_outputs/         # コマンド実行結果
│   │   └── {timestamp}_{command}.json
│   └── metadata.json
```

#### ContextStoreクラスの主要メソッド

- `save_message(task_uuid, role, content, tokens)`: LLM会話メッセージをSqlStoreに保存する
- `save_planning_history(task_uuid, phase, plan)`: プランニング履歴をSqlStoreに保存する
- `save_file_read_result(task_uuid, path, content)`: ファイル読み込み結果をFileStoreに保存する
- `save_command_result(task_uuid, command, result)`: コマンド実行結果をFileStoreに保存する
- `restore_context(task_uuid)`: SqlStoreとFileStoreから過去の情報を取得し、合成したコンテキストを返す

### 8.3 Conversation State

- **システムプロンプト**: タスク開始時に設定（英語）
- **ユーザーメッセージ**: Issue/MR内容、コメント
- **アシスタント応答**: LLMからの応答
- **ツール呼び出し**: function_call とその結果

### 8.4 Execution State

タスクデータベース (PostgreSQL) で管理：

#### tasks テーブル

```sql
CREATE TABLE tasks (
    uuid TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    task_identifier TEXT NOT NULL,
    repository TEXT NOT NULL,
    user_email TEXT NOT NULL,
    status TEXT NOT NULL,  -- running, completed, paused, failed
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_messages INTEGER DEFAULT 0,
    total_summaries INTEGER DEFAULT 0,
    total_tool_calls INTEGER DEFAULT 0,
    final_token_count INTEGER,
    error_message TEXT,
    metadata JSONB
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_user_email ON tasks(user_email);
CREATE INDEX idx_tasks_repository ON tasks(repository);
```

### 8.5 コンテキスト圧縮

トークン数が閾値を超えた場合、古いメッセージを要約して圧縮：

**設定**:
- `token_threshold`: 8000
- `keep_recent`: 10 (最近のメッセージ数)
- `min_to_compress`: 5 (圧縮する最小メッセージ数)

**処理フロー**:
1. トークン数チェック
2. 圧縮対象メッセージ抽出
3. LLMで要約生成（英語プロンプト使用）
4. 要約をコンテキストに挿入
5. 古いメッセージを削除

### 8.6 コンテキスト継承

同一Issue/MRの過去タスクから情報を引き継ぐ：

**引き継ぎ内容**:
- 最終要約
- プランニング履歴
- 成功した実装パターン

**有効期限**: 30日（設定可能）

### 8.7 ファイルストレージ（ツール実行結果）

Agent FrameworkのFileStoreを使用して、ツールで読んだファイル情報やコマンド実行結果を保存する。ディレクトリ構造とファイル形式はAgent Framework FileStore APIに従う。

#### ディレクトリ構造

```
tool_results/
├── {task_uuid}/
│   ├── file_reads/              # ファイル読み込み結果
│   │   ├── {timestamp}_path.txt
│   │   └── {timestamp}_path.json
│   ├── command_outputs/         # コマンド実行結果
│   │   ├── {timestamp}_command.txt
│   │   └── {timestamp}_command.json
│   ├── mcp_tool_calls/          # MCPツール呼び出し履歴
│   │   └── {timestamp}_tool.json
│   └── metadata.json            # ツール実行メタデータ
```

#### metadata.json

```json
{
  "task_uuid": "task-uuid",
  "total_file_reads": 15,
  "total_command_executions": 8,
  "total_mcp_calls": 25,
  "started_at": "2024-01-01T00:00:00Z",
  "last_updated_at": "2024-01-01T01:00:00Z"
}
```

#### ファイル読み込み結果例

```json
{
  "timestamp": "2024-01-01T00:10:00Z",
  "tool": "text_editor",
  "command": "view",
  "path": "src/main.py",
  "content_preview": "#!/usr/bin/env python\n...",
  "content_length": 1524,
  "mime_type": "text/x-python"
}
```

#### コマンド実行結果例

```json
{
  "timestamp": "2024-01-01T00:15:00Z",
  "tool": "command-executor",
  "command": "pytest tests/",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "duration_ms": 3500
}
```

**保持期限**: 設定で指定（デフォルト30日）

---

## 9. Tool管理設計 (MCP)

### 9.1 MCP概要

Model Context Protocol (MCP) を使用してツール実行を標準化：

- **Command Executor MCP**: Docker環境でのコマンド実行
- **Text Editor MCP**: ファイル編集操作
- **Git MCP**: Git操作（オプション）
- **Todo Management MCP**: Todoリスト管理
- **カスタム実装ツール（todo管理等）**: Agent Frameworkのツールとして実装する（MCPにしない）

**注意**: GitLab MCP Serverは使用しません。GitLab API操作はシステム側がPython GitLab クライアント経由で直接実行します。

### 9.2 MCPサーバー構成

```yaml
mcp_servers:
  # GitLab MCP Serverは使用しない（システム側で直接GitLab API呼び出し）
  
  - name: "command-executor"
    command: ["python", "mcp/command_executor.py"]
    env:
      DOCKER_ENABLED: "true"
  
  - name: "text-editor"
    command: ["npx", "@modelcontextprotocol/server-text-editor"]
    env:
      ALLOWED_DIRECTORIES: "/workspace"
```

「command-executorとtext-editorはMCPサーバーとして実装するが、ExecutionEnvironmentManager上で動くので、handlers/execution_environment_mcp_wrapper.pyを参照して設計する。」

### 9.3 ツール一覧

#### Command Executor MCP Tools

| ツール名 | 説明 | パラメータ |
|---------|------|----------|
| `execute_command` | コマンド実行 | command, working_directory, environment |
| `clone_repository` | リポジトリクローン | repository_url, branch |
| `install_dependencies` | 依存関係インストール | package_manager, packages |

#### Text Editor MCP Tools

| ツール名 | 説明 | パラメータ |
|---------|------|----------|
| `view_file` | ファイル表示 | file_path |
| `create_file` | ファイル作成 | file_path, content |
| `str_replace` | 文字列置換 | file_path, old_str, new_str |
| `insert_line` | 行挿入 | file_path, line_number, content |
| `undo_edit` | 編集取り消し | file_path |

#### Todo Managementツール（Agent Frameworkツール・独自実装）

Todo管理ツールはMCPではなくAgent Frameworkのツールとして独自実装する。

| ツール名 | 説明 | パラメータ |
|---------|------|----------|
| `create_todo_list` | Todoリスト作成 | project_id, issue_iid/mr_iid, todos |
| `get_todo_list` | Todoリスト取得 | project_id, issue_iid/mr_iid |
| `update_todo_status` | Todo状態更新 | todo_id, status |
| `add_todo` | Todo追加 | project_id, issue_iid/mr_iid, title, description, parent_todo_id |
| `delete_todo` | Todo削除 | todo_id |
| `reorder_todos` | Todo順序変更 | todo_ids |
| `sync_to_gitlab` | GitLabへ同期 | project_id, issue_iid/mr_iid |

**Todo状態遷移**:
- `not-started` → `in-progress` → `completed`
- `not-started` → `failed`
- `in-progress` → `failed`

**GitLab同期**: 
`sync_to_gitlab` ツールは、TodoリストをGitLab Issue/MRのdescriptionまたはコメントにMarkdown形式で投稿する。これにより、GitLab UI上でも進捗を確認できる。

```markdown
## タスク進捗

- [x] Todo 1: データベーススキーマ設計
- [ ] Todo 2: API実装
  - [x] Todo 2.1: エンドポイント定義
  - [ ] Todo 2.2: 認証実装
- [ ] Todo 3: テスト作成
```

### 9.4 Tool実行フロー

```mermaid
sequenceDiagram
    participant LLM
    participant PC as PlanningCoordinator
    participant MCP as MCPToolClient
    participant Server as MCP Server
    participant External as External Service
    
    LLM->>PC: function_call
    PC->>MCP: call_tool(tool_name, args)
    MCP->>Server: execute(tool_name, args)
    Server->>External: API/Command
    External-->>Server: Result
    Server-->>MCP: Result
    MCP-->>PC: Result
    PC->>LLM: tool_result
```

---

## 10. エラー処理設計

### 10.1 エラー分類

| エラー種別 | 具体例 | 対応 |
|----------|--------|------|
| 一時的エラー | HTTP 5xx, タイムアウト | 自動リトライ |
| 永続的エラー | HTTP 401, 404 | エラー通知、処理中断 |
| ユーザーエラー | 不正なパラメータ | エラーメッセージ、人間介入 |
| システムエラー | メモリ不足 | アラート、緊急停止 |

### 10.2 リトライポリシー

#### 指数バックオフ

指数バックオフはattempt回数とbase_delay、max_delayを元に遅延時間を計算する。ジッターを加えてリトライの集中を防ぐ。

#### リトライ設定

```yaml
retry_policy:
  http_errors:
    5xx:
      max_attempts: 3
      backoff: exponential
      base_delay: 1.0
    429:  # Rate limit
      max_attempts: 5
      backoff: exponential
      base_delay: 60.0
  
  tool_errors:
    max_attempts: 2
    backoff: linear
    base_delay: 5.0
  
  llm_errors:
    max_attempts: 3
    backoff: exponential
    base_delay: 2.0
```

### 9.3 エラーハンドリングフロー

```mermaid
flowchart TD
    Error[エラー発生] --> Classify{エラー分類}
    
    Classify -->|一時的| CheckRetry{リトライ回数}
    CheckRetry -->|上限未満| Backoff[バックオフ待機]
    Backoff --> Retry[リトライ実行]
    CheckRetry -->|上限到達| Notify
    
    Classify -->|永続的| Notify[エラー通知]
    Classify -->|ユーザー| Human[人間介入要求]
    Classify -->|システム| Alert[緊急アラート]
    
    Notify --> Record[エラー記録]
    Human --> Record
    Alert --> Emergency[緊急停止]
    
    Record --> Continue{処理継続可能?}
    Continue -->|Yes| Resume[処理再開]
    Continue -->|No| Stop[タスク中断]
```

### 9.4 エラー通知

#### Issue/MRコメント

```markdown
## ⚠️ エラー通知

**エラー種別**: ツール実行エラー

**発生時刻**: 2024-01-01 12:34:56 UTC

**詳細**:
```
Error executing tool 'edit_file':
File not found: /path/to/file.py
```

**対応**:
- [ ] ファイルパスを確認
- [ ] エージェントを再実行

このエラーは自動リトライ後も解決できませんでした。人間の介入が必要です。
```

#### ログ記録

エラー発生時は、task_uuid・tool_name・error_type・error_message・traceback・retry_countを含む構造化ログをエラーレベルで記録する。

---

## 11. セキュリティ設計

### 11.1 認証・認可

ユーザー毎のPersonal Access Token（PAT）を必ず使用する。GITLAB_PERSONAL_ACCESS_TOKENなどの共有トークンは使用しない。

#### User Config API認証

Bearer TokenによるJWT（HS256）認証を使用する。トークン有効期限は24時間とし、自動リフレッシュを行う。

### 11.2 暗号化

#### APIキー暗号化

AES-256-GCMアルゴリズムを使用してAPIキーを暗号化する。暗号化キーは環境変数ENCRYPTION_KEYで管理し（32バイト）、Pythonのcryptographyライブラリで実装する。暗号化・復号化はEncryptionServiceクラスに集約し、DBへの保存前に必ず暗号化を行う。

---

## 12. 運用設計

### 12.1 デプロイ構成（Producer/Consumer + RabbitMQ）

#### Docker Compose構成

```yaml
version: '3.8'

services:
  # RabbitMQ（分散タスクキュー）
  rabbitmq:
    image: rabbitmq:3-management
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER:-agent}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASS}
    ports:
      - "5672:5672"      # AMQP
      - "15672:15672"    # Management UI
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
  
  # Producer（タスク検出・キューイング）
  producer:
    build: .
    command: python producer.py
    env_file: .env
    environment:
      RABBITMQ_HOST: rabbitmq
      RABBITMQ_PORT: 5672
      RABBITMQ_USER: ${RABBITMQ_USER:-agent}
      RABBITMQ_PASS: ${RABBITMQ_PASS}
      GITLAB_URL: ${GITLAB_URL}
      GITLAB_TOKEN: ${GITLAB_TOKEN}
      PRODUCER_INTERVAL_SECONDS: ${PRODUCER_INTERVAL_SECONDS:-60}
    depends_on:
      rabbitmq:
        condition: service_healthy
      postgres:
        condition: service_started
    deploy:
      replicas: 1  # Producer は1つ
  
  # Consumer（タスク処理）
  consumer:
    build: .
    command: python consumer.py
    env_file: .env
    environment:
      RABBITMQ_HOST: rabbitmq
      RABBITMQ_PORT: 5672
      RABBITMQ_USER: ${RABBITMQ_USER:-agent}
      RABBITMQ_PASS: ${RABBITMQ_PASS}
      GITLAB_URL: ${GITLAB_URL}
      USER_CONFIG_API_URL: http://user-config-api:8080
    volumes:
      - ./contexts:/app/contexts
      - ./tool_results:/app/tool_results
      - /var/run/docker.sock:/var/run/docker.sock  # Docker実行環境
    depends_on:
      rabbitmq:
        condition: service_healthy
      postgres:
        condition: service_started
      user-config-api:
        condition: service_started
    deploy:
      replicas: 5  # 100人規模対応: 5-10並列推奨
  
  # User Config API
  user-config-api:
    build: .
    command: uvicorn user_config_api.server:app --host 0.0.0.0 --port 8080
    env_file: .env
    environment:
      DATABASE_URL: postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/coding_agent
      ENCRYPTION_KEY: ${ENCRYPTION_KEY}
    ports:
      - "8080:8080"
    depends_on:
      - postgres
  
  # Web管理画面
  user-config-web:
    build: .
    command: streamlit run user_config_api/streamlit_app.py --server.port 8501
    env_file: .env
    environment:
      USER_CONFIG_API_URL: http://user-config-api:8080
    ports:
      - "8501:8501"
    depends_on:
      - user-config-api
  
  # PostgreSQL
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: coding_agent
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"

volumes:
  postgres_data:
  rabbitmq_data:
```

**デプロイ構成の特徴**:
- **Producer 1台**: タスク検出を1プロセスで実行（定期実行）
- **Consumer 5-10台**: 100人規模対応のため並列実行
- **RabbitMQ**: durable queueで永続化、タスクロスト防止
- **healthcheck**: RabbitMQ起動完了を待ってからProducer/Consumer起動

### 12.2 スケーリング戦略（Producer/Consumerパターン）

#### 水平スケーリング

- **Consumer数調整**: 
  - 100人規模: 5-10 replicas推奨
  - タスク処理時間監視: 平均待ち時間が閾値超過時にreplicas増加
  - RabbitMQメトリクス: キュー長が常に閾値（例: 50）を超える場合はreplicas増加
  
- **Producer**: 
  - 基本的に1台で十分（定期実行間隔: 30秒〜1分）
  - 大規模環境（1000人超）では2台に増やし、プロジェクトIDでパーティショニング
  
- **RabbitMQ**: 
  - クラスタリング（HA構成）で耐障害性向上
  - ミラーキュー設定でタスクロスト防止

#### 垂直スケーリング

- **Consumer**: 
  - LLM処理の並列実行: Consumer 1台あたり複数タスク処理
  - メモリ: 最低2GB/Consumer、推奨4GB（Context保持のため）
  
- **RabbitMQ**: 
  - メモリ: 最低1GB、推奨2GB以上
  - ディスク: durable queue永続化のため十分な容量確保
  
- **PostgreSQL**: 
  - メモリ、ストレージ拡張（Context Storage増加に対応）

### 12.3 監視・ログ

#### メトリクス

- **タスクメトリクス**
  - タスク処理時間
  - 成功率
  - 失敗率
  - キュー長

- **APIメトリクス**
  - GitLab APIレート制限残量
  - OpenAI APIトークン使用量
  - レスポンスタイム

- **システムメトリクス**
  - CPU使用率
  - メモリ使用率
  - ディスク使用量

#### ログ管理

```yaml
logging:
  version: 1
  handlers:
    file:
      class: logging.handlers.RotatingFileHandler
      filename: logs/agent.log
      maxBytes: 10485760  # 10MB
      backupCount: 10
      formatter: json
    
  formatters:
    json:
      class: pythonjsonlogger.jsonlogger.JsonFormatter
      format: '%(asctime)s %(name)s %(levelname)s %(message)s'
  
  loggers:
    agent:
      level: INFO
      handlers: [file]
```

#### アラート

- タスク失敗率が10%を超えた場合
- キュー長が100を超えた場合
- APIレート制限に到達した場合
- ディスク使用率が80%を超えた場合

### 12.4 バックアップ・リカバリ

#### PostgreSQLバックアップ

```bash
# 日次バックアップ
pg_dump -U agent coding_agent | gzip > backup/db_$(date +%Y%m%d).sql.gz

# リストア
gunzip -c backup/db_20240101.sql.gz | psql -U agent coding_agent
```

#### コンテキストバックアップ

```bash
# 週次バックアップ
tar -czf backup/contexts_$(date +%Y%m%d).tar.gz contexts/

# 古いバックアップ削除（30日以上前）
find backup/ -name "*.tar.gz" -mtime +30 -delete
```

### 12.5 メンテナンス

#### 定期メンテナンス

- **日次**
  - ログローテーション
  - 完了タスクのアーカイブ（30日以上前）
  
- **週次**
  - データベースVACUUM
  - メトリクス分析
  
- **月次**
  - APIトークンローテーション確認
  - セキュリティパッチ適用

#### タスククリーンアップ

指定日数（デフォルト30日）より古い完了タスクをDBとファイルシステムから削除する。DBはstatus='completed'かつcompleted_atが閾値より古いレコードを削除し、ファイルシステムのcontexts/completedディレクトリ内の対象タスクディレクトリを削除する。

---

## 13. 設定ファイル例

### 13.1 config.yaml

```yaml
# GitLab設定
gitlab:
  api_url: "https://gitlab.com/api/v4"
  personal_access_token: "${GITLAB_PERSONAL_ACCESS_TOKEN}"
  task_label: "coding-agent"
  processing_label: "coding-agent-processing"
  done_label: "coding-agent-done"
  bot_name: "coding-agent-bot"

# LLMデフォルト設定
llm:
  provider: "openai"  # openai, ollama, lmstudio
  model: "gpt-4o"
  temperature: 0.2
  max_tokens: 4096

# OpenAI設定
openai:
  api_key: "${OPENAI_API_KEY}"
  base_url: "https://api.openai.com/v1"

# User Config API設定
user_config_api:
  enabled: true
  url: "http://user-config-api:8080"
  api_key: "${USER_CONFIG_API_KEY}"

# PostgreSQL設定
database:
  url: "postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/coding_agent"

# Agent Framework設定
agent_framework:
  workflows:
    streaming: true
    checkpointing: true
    human_in_loop: false
  observability:
    opentelemetry:
      enabled: true
      endpoint: "${OTEL_EXPORTER_OTLP_ENDPOINT}"
  middleware:
    enabled: true
    error_handling: true
    request_logging: true

# コンテキストストレージ設定
context_storage:
  base_dir: "contexts"
  compression:
    token_threshold: 8000
    keep_recent: 10
    min_to_compress: 5
  inheritance:
    enabled: true
    max_summary_tokens: 4000
    expiry_days: 30

# ファイルストレージ設定（ツール実行結果など）
file_storage:
  base_dir: "tool_results"
  retention_days: 30
  formats:
    - "json"
    - "txt"
    - "md"

# プランニング設定
planning:
  enabled: true
  max_reflection_count: 3
  max_plan_revision_count: 2
  reflection_interval: 5
  verification:
    enabled: true
    max_rounds: 2

# MCP設定
mcp_servers:
  - name: "command-executor"
    command: ["python", "mcp/command_executor.py"]
  
  - name: "text-editor"
    command: ["npx", "@modelcontextprotocol/server-text-editor"]
  
# リトライポリシー
retry_policy:
  http_errors:
    5xx:
      max_attempts: 3
      backoff: exponential
      base_delay: 1.0
    429:
      max_attempts: 5
      backoff: exponential
      base_delay: 60.0
  tool_errors:
    max_attempts: 2
    backoff: linear
    base_delay: 5.0
  llm_errors:
    max_attempts: 3
    backoff: exponential
    base_delay: 2.0

# ログ設定
logging:
  level: INFO
  file: "logs/agent.log"
  max_bytes: 10485760  # 10MB
  backup_count: 10
```

---

## 14. 改善ポイント（coding_agent比較）

### 14.1 アーキテクチャ改善

| 項目 | coding_agent | 本設計 | 改善内容 |
|------|-------------|--------|---------|
| フレームワーク | 独自実装 | Microsoft Agent Framework | 標準化、Graph-based Workflows、OpenTelemetry統合 |
| 状態管理 | ファイルベース | PostgreSQL + ファイル | 検索性向上、スケーラビリティ |
| ワークフロー | 固定フェーズ | Agent Framework Workflowsプランニングベース | 柔軟な分岐・チェックポイント・リトライ |
| ツール管理 | 直接API呼び出し | Agent Framework + MCP | Middleware統合、標準準拠 |
| エラー処理 | 分散実装 | Agent Framework Middleware | 統一的なエラーハンドリング |

### 14.2 Microsoft Agent Framework標準機能の活用

| 標準機能 | 用途 | メリット |
|---------|------|---------|
| Graph-based Workflows | タスクフロー制御 | ストリーミング、チェックポイント、タイムトラベル、視覚化 |
| OpenTelemetry統合 | 分散トレーシング | 監視、デバッグ、パフォーマンス分析 |
| Middleware System | リクエスト処理 | エラーハンドリング、ログ記録、認証の統一 |
| Agent Providers | LLM統合 | 複数プロバイダー対応、統一API |
| DevUI | 開発支援 | インタラクティブデバッグ、ワークフローテスト |

### 14.3 coding_agentからの移植対象ファイル

#### 14.3.1 必須移植コンポーネント（Issue→MR変換）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`handlers/issue_to_mr_converter.py`** | `IssueToMRConverter` | Issue→MR変換メインロジック | ほぼそのまま移植 | Agent Framework Workflowノードとして実装 |
| | `BranchNameGenerator` | LLMによるブランチ名生成 | そのまま移植 | Agent Framework LLM Clientを使用 |
| | `ContentTransferManager` | IssueコメントのMRへの転記 | そのまま移植 | GitlabClientと連携 |
| **`clients/gitlab_client.py`** | `GitlabClient` | GitLab REST API操作 | そのまま移植 | Agent Framework Toolとして登録 |
| | `create_merge_request()` | MR作成 | そのまま移植 | - |
| | `create_branch()` | ブランチ作成 | そのまま移植 | - |
| | `create_commit()` | コミット作成 | そのまま移植 | - |
| | `add_merge_request_note()` | MRにコメント追加 | そのまま移植 | - |
| | `update_merge_request()` | MR更新 | そのまま移植 | - |
| | `list_merge_requests()` | MRリスト取得 | そのまま移植 | - |
| | `list_merge_request_notes()` | MRコメントリスト取得 | そのまま移植 | - |
| **`handlers/task_getter_gitlab.py`** | `TaskGitLabIssue` | GitLab Issue操作 | Agent Framework Workflowノードとして実装 | - |
| | `TaskGitLabMergeRequest` | GitLab MR操作 | Agent Framework Workflowノードとして実装 | - |
| | `TaskGetterFromGitLab` | GitLabタスク取得 | Agent Framework Workflowノードとして実装 | PostgreSQLで処理済みタスクを除外 |
| **`handlers/task_factory.py`** | `GitLabTaskFactory` | TaskオブジェクトをTaskKeyから生成 | ワークフローに統合 | - |
| **`handlers/task_key.py`** | `GitLabIssueTaskKey` | IssueのTaskKey | そのまま移植 | - |
| | `GitLabMergeRequestTaskKey` | MRのTaskKey | そのまま移植 | - |

#### 14.3.2 コンテキスト管理（文字数が大きくなったときの外部出力対応）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`context_storage/task_context_manager.py`** | `TaskContextManager` | タスクコンテキスト管理 | そのまま移植 | **PostgreSQL連携を追加** |
| **`context_storage/message_store.py`** | `MessageStore` | LLM会話履歴保存 | そのまま移植 | ファイルベース保持 |
| **`context_storage/summary_store.py`** | `SummaryStore` | 要約保存 | そのまま移植 | ファイルベース保持 |
| **`context_storage/tool_store.py`** | `ToolStore` | ツール実行履歴 | そのまま移植 | ファイルベース保持 |
| **`context_storage/context_compressor.py`** | `ContextCompressor` | コンテキスト圧縮 | そのまま移植 | LLMは Agent Framework経由 |
| **`context_storage/context_inheritance_manager.py`** | `ContextInheritanceManager` | コンテキスト継承 | そのまま移植 | - |

#### 14.3.3 MCPクライアント（Agent Framework統合）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`clients/mcp_tool_client.py`** | `MCPToolClient` | MCP通信基盤 | Agent Framework Middleware統合 | Agent Frameworkの標準MCPモジュール優先 |
| **`clients/text_editor_mcp_client.py`** | `TextEditorMCPClient` | ファイル編集MCP | Agent Framework Tool登録 | - |

#### 14.3.4 ユーザー管理（User Config API）

| ファイルパス | 用途 | 移植方法 | 変更点 |
|------------|------|---------|--------|
| **`user-config-api/app.py`** | FastAPI: ユーザー設定管理API | そのまま移植 | PostgreSQLスキーマをAgent Frameworkと統合 |
| **`user-config-api/models.py`** | Pydanticモデル | そのまま移植 | - |
| **`user-config-api/database.py`** | SQLAlchemy DB接続 | そのまま移植 | - |
| **`user-config-api/encryption.py`** | APIキー暗号化 | そのまま移植 | - |
| **`web-config/app.py`** | Streamlit Web UI | そのまま移植 | - |

#### 14.3.5 環境管理（Docker実行環境）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`handlers/execution_environment_manager.py`** | `ExecutionEnvironmentManager` | Docker環境管理 | 参考にして再実装 | Agent Framework Workflowに統合 |
| **`handlers/execution_environment_mcp_wrapper.py`** | `ExecutionEnvironmentMCPWrapper` | MCP Wrapper | Agent Framework Tool登録 | - |
| **`handlers/environment_analyzer.py`** | `EnvironmentAnalyzer` | 環境解析 | 参考にして再実装 | - |

#### 14.3.6 プランニング

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`handlers/pre_planning_manager.py`** | `PrePlanningManager` | 事前計画管理 | Agent Framework Workflowノードとして実装 | - |

#### 14.3.7 LLMクライアント（Agent Providers優先）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`clients/llm_base.py`** | `LLMClient` | LLM基底クラス | 互換レイヤーとして保持 | Agent Framework標準のAgent Providersを優先使用 |
| **`clients/llm_openai.py`** | `LLMClientOpenAI` | OpenAI実装 | 互換レイヤーとして保持 | Agent Framework標準のAgent Providersを優先使用 |
| **`clients/llm_ollama.py`** | `LLMClientOllama` | Ollama実装 | 互換レイヤーとして保持 | Agent Framework標準のAgent Providersを優先使用 |
| **`clients/lm_client.py`** | `get_llm_client()` | LLMクライアント取得 | Agent Framework統合 | - |

#### 14.3.8 ユーティリティ

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`filelock_util.py`** | `FileLock` | ファイルロック | そのまま移植 | - |

#### 14.3.9 移植不要（Agent Framework標準機能で代替）

| ファイルパス | 理由 |
|------------|------|
| **`queueing.py`** (`RabbitMQTaskQueue`, `InMemoryTaskQueue`) | RabbitMQは使用しない。タスク管理はPostgreSQLとAgent Framework Workflowsで代替 |
| **`main.py`** (Producer/Consumer管理部分) | Agent Framework Workflowsで代替。定期実行はcron/webhookで制御 |
| **`pause_resume_manager.py`** | PostgreSQL + Agent Framework Workflowsの状態管理で代替 |

#### 14.3.10 移植時の統合方針

**Agent Framework統合における変更点**:

1. **LLM呼び出し**: coding_agentの独自LLMクライアント → Agent Framework標準のAgent Providers
2. **状態管理**: ファイルベース単独 → PostgreSQL + ファイルベースのハイブリッド
3. **タスクキュー**: RabbitMQ → PostgreSQL + Webhook/Cron
4. **エラーハンドリング**: 個別実装 → Agent Framework Middleware統合
5. **トレーシング**: 独自ログ → OpenTelemetry統合

**統合の方針**:
- coding_agentから移植したモジュールは、Agent Framework WorkflowのNodeとして実装する
- IssueToMRConverterは、Agent Framework Workflowの条件分岐ノードから呼び出す
- GitlabClientは、Agent Framework Toolとして登録し、Middlewareを経由して呼び出す
- コンテキスト管理（context_storage/*）は、ファイルベース部分はそのまま移植し、PostgreSQL連携を追加する

### 14.4 機能追加

| 機能 | 説明 | メリット |
|------|------|---------|
| ユーザー管理 | メールアドレスベースの設定管理 | マルチユーザー対応 |
| APIキー管理 | ユーザー毎のOpenAI APIキー | コスト分離 |
| Web管理画面 | Streamlitベースの設定UI | 設定変更が容易 |
| トークン追跡 | ユーザー別トークン使用量 | コスト可視化 |
| コンテキスト継承 | 過去タスクの知識活用 | 処理精度向上 |
| ファイル出力 | ツール実行結果の外部保存 | デバッグ、監査容易 |

### 14.5 運用改善

| 項目 | 改善内容 | 効果 |
|------|---------|------|
| スケーリング | Agent Framework Workflows並列処理 | 処理能力向上 |
| 監視 | OpenTelemetry統合 | 障害早期検知、分散トレーシング |
| バックアップ | 自動バックアップ | データ保護 |
| メンテナンス | 自動クリーンアップ | 運用負荷軽減 |

---

## 15. まとめ

### 15.1 設計の特徴

本設計は、GitLab専用の自律型コーディングエージェントを **Microsoft Agent Framework** をベースに構築し、`https://github.com/notfolder/coding_agent` の実績あるコンポーネントを流用するものである。

**主要な特徴**:

1. **Microsoft Agent Framework標準機能の活用**
   - Graph-based Workflows: チェックポイント、ストリーミング、タイムトラベル
   - OpenTelemetry統合: 分散トレーシング、パフォーマンス監視
   - Middleware System: 統一的なエラーハンドリング、ログ記録
   - Agent Providers: 複数LLMプロバイダー対応

2. **ユーザー管理の統合**
   - メールアドレスベースの設定管理
   - ユーザー毎のAPIキー分離
   - マルチユーザー対応

3. **プランニングベースのワークフロー**
   - 計画→実行→検証のサイクル
   - 柔軟な分岐とリトライ
   - 自律的な計画修正

4. **ハイブリッド状態管理**
   - Agent Framework標準: Workflow State、Conversation State
   - 追加の永続化機能: PostgreSQL + ファイルベース（coding_agent流用）
   - ファイルストレージ: ツール実行結果の外部出力

5. **標準化されたツール管理**
   - MCP (Model Context Protocol) 採用
   - Agent Framework Middlewareとの統合
   - coding_agentのMCPクライアント流用

6. **coding_agentからの資産流用**
   - コンテキスト管理: `context_storage/*` をそのまま流用
   - MCPクライアント: `clients/mcp_*.py` を統合
   - 環境管理: `handlers/*` を参考に再実装

### 15.2 期待される効果

- **開発効率の向上**: GitLab Issue/MRの自動処理によるコーディング作業の効率化
- **コスト管理**: ユーザー毎のAPIキー管理によるコスト分離と可視化
- **品質向上**: 計画・検証フェーズとAgent Framework標準機能による実装品質の向上
- **運用負荷軽減**: OpenTelemetry統合による監視強化と自動化
- **ツール追加の容易さ**: MCPとAgent Framework Middlewareによる標準化されたツール統合
- **保守性向上**: 標準フレームワーク活用と実績あるコンポーネント流用

### 15.3 実装時の重点事項

1. **Agent Framework標準機能を最大限活用**: 独自実装を避け、標準機能を優先
2. **coding_agent資産の活用**: 実績あるコンポーネントを積極活用
3. **PostgreSQLとファイルストレージの適切な使い分け**: 検索性とデバッグ性のバランス
4. **OpenTelemetry統合**: 初期から監視基盤を構築
5. **基本機能の確実な実装**: チェックポイント、コンテキスト継承等の高度な機能も含めて実装

---

**文書バージョン**: 3.0  
**最終更新日**: 2026-02-28  
**ステータス**: 設計完了（Agent Framework標準機能統合、Issue→MR変換特化、coding_agent流用明記）

---

## 付録A: coding_agent参照ファイル一覧

本仕様書で参照・移植対象としたcoding_agentリポジトリのファイル一覧。  
**リポジトリ**: `https://github.com/notfolder/coding_agent`

### A.0 Producer/Consumer関連（新規作成）

```
producer.py
  - produce_tasks(): タスク検出・キューイング
  - run_producer_continuous(): 定期実行ループ
  - TaskGetterFromGitLab: GitLab API経由タスク取得

consumer.py
  - consume_tasks(): タスクデキュー・処理
  - run_consumer_continuous(): Consumer実行ループ

queueing.py
  - get_rabbitmq_connection(): RabbitMQ接続管理
  - declare_task_queue(): キュー宣言（durable=True）

handlers/task_handler.py
  - TaskHandler.handle(task): タスク処理分岐
  - _should_convert_issue_to_mr(): Issue判定
  - _convert_issue_to_mr(): Issue→MR変換実行
```

### A.1 Issue→MR変換関連

```
handlers/issue_to_mr_converter.py
  - IssueToMRConverter: Issue→MR変換メインクラス
  - BranchNameGenerator: LLMによるブランチ名生成
  - ContentTransferManager: Issueコメント転記
  - ConversionResult: 変換結果データクラス

handlers/task_getter_gitlab.py
  - TaskGitLabIssue: GitLab Issue操作クラス
  - TaskGitLabMergeRequest: GitLab MR操作クラス
  - TaskGetterFromGitLab: GitLabタスク取得クラス

handlers/task_factory.py
  - GitLabTaskFactory: TaskKey→Taskオブジェクト生成

handlers/task_key.py
  - GitLabIssueTaskKey: IssueのTaskKey
  - GitLabMergeRequestTaskKey: MRのTaskKey

handlers/task_handler.py
  - TaskHandler._should_convert_issue_to_mr(): Issue→MR変換判定
  - TaskHandler._convert_issue_to_mr(): Issue→MR変換実行
  - TaskHandler._get_platform_for_task(): プラットフォーム判定
  - TaskHandler._get_mcp_client_for_task(): MCPクライアント取得
```

### A.2 GitLab API操作

```
clients/gitlab_client.py
  - GitlabClient: GitLab REST API wrapper
  - create_merge_request(): MR作成
  - update_merge_request(): MR更新
  - list_merge_requests(): MRリスト取得
  - list_merge_request_notes(): MRコメント取得
  - add_merge_request_note(): MRコメント追加
  - create_branch(): ブランチ作成
  - create_commit(): コミット作成
  - search_merge_requests(): MR検索
  - _fetch_paginated_list(): ページネーション処理
```

### A.3 コンテキスト管理

```
context_storage/task_context_manager.py
  - TaskContextManager: タスクコンテキスト管理

context_storage/message_store.py
  - MessageStore: LLM会話履歴保存

context_storage/summary_store.py
  - SummaryStore: 要約保存

context_storage/tool_store.py
  - ToolStore: ツール実行履歴

context_storage/context_compressor.py
  - ContextCompressor: コンテキスト圧縮

context_storage/context_inheritance_manager.py
  - ContextInheritanceManager: コンテキスト継承
```

### A.4 MCPクライアント

```
clients/mcp_tool_client.py
  - MCPToolClient: MCP通信基盤

clients/text_editor_mcp_client.py
  - TextEditorMCPClient: ファイル編集MCP
```

### A.5 環境管理

```
handlers/execution_environment_manager.py
  - ExecutionEnvironmentManager: Docker環境管理

handlers/execution_environment_mcp_wrapper.py
  - ExecutionEnvironmentMCPWrapper: MCP Wrapper

handlers/environment_analyzer.py
  - EnvironmentAnalyzer: 環境解析
```

### A.6 プランニング

```
handlers/pre_planning_manager.py
  - PrePlanningManager: 事前計画管理
```

### A.7 LLMクライアント

```
clients/llm_base.py
  - LLMClient: LLM基底クラス

clients/llm_openai.py
  - LLMClientOpenAI: OpenAI実装

clients/llm_ollama.py
  - LLMClientOllama: Ollama実装

clients/lm_client.py
  - get_llm_client(): LLMクライアント取得
```

### A.8 ユーザー管理

```
user-config-api/app.py
  - FastAPI: ユーザー設定管理API

user-config-api/models.py
  - Pydanticモデル

user-config-api/database.py
  - SQLAlchemy DB接続

user-config-api/encryption.py
  - APIキー暗号化

web-config/app.py
  - Streamlit Web UI
```

### A.9 データベース

```
db/task_db.py
  - TaskDBManager: タスクDB操作

db/models.py
  - Task: タスクモデル
```

### A.10 ユーティリティ

```
filelock_util.py
  - FileLock: ファイルロック
```

### A.11 メインエントリーポイント（参考）

```
main.py
  - produce_tasks(): タスク取得＆キュー投入
  - consume_tasks(): キューからタスク取得＆処理
  - run_producer_continuous(): Producer継続動作
  - run_consumer_continuous(): Consumer継続動作
  ※ CodeAgentOrchestratorでは不使用（Agent Framework Workflowsで代替）
```

### A.12 キュー管理（移植対象）

```
queueing.py
  - get_rabbitmq_connection(): RabbitMQ接続管理
  - declare_task_queue(): キュー宣言（durable=True）
  - RabbitMQTaskQueue: RabbitMQキュー（移植対象）
  - InMemoryTaskQueue: インメモリキュー（開発・テスト用、本番はRabbitMQ使用）
  ※ CodeAgentOrchestratorではRabbitMQを使用（Producer/Consumerパターン踏襲）

pause_resume_manager.py
  - PauseResumeManager: 一時停止管理
  ※ CodeAgentOrchestratorでは不使用（PostgreSQL状態管理で代替）
```

### A.13 設計ドキュメント（参考）

```
docs/MAIN_SPEC.md
  - main.py, TaskHandlerの設計書

docs/CLASS_SPEC.md
  - クラス設計・関係図

docs/spec/ISSUE_TO_MR_CONVERSION_SPECIFICATION.md
  - Issue→MR変換仕様書
```

---

## 付録B: Agent Framework vs coding_agent 対応表

| 機能 | coding_agent | CodeAgentOrchestrator (Agent Framework) |
|------|--------------|----------------------------------------|
| **タスクキュー** | RabbitMQ / InMemory | RabbitMQ（Producer/Consumerパターン踏襲） |
| **ワークフロー制御** | 独自実装（main.py） | Producer/Consumer + Agent Framework Workflows |
| **LLM呼び出し** | 独自LLMClient | Agent Framework Agent Providers |
| **状態管理** | ファイルベース | PostgreSQL + ファイルベース |
| **エラーハンドリング** | 個別実装 | Agent Framework Middleware |
| **監視・トレーシング** | 独自ログ | OpenTelemetry統合 |
| **コンテキスト管理** | context_storage/* | context_storage/* (coding_agentから移植) + Agent Framework Context Storage |
| **Issue→MR変換** | issue_to_mr_converter.py | issue_to_mr_converter.py (coding_agentから移植) + Consumer統合 |
| **GitLab操作** | gitlab_client.py | gitlab_client.py (coding_agentから移植) |
| **Producer/Consumer** | 分離実行可能 | Producer（定期実行）+ Consumer（5-10並列、Agent Framework Workflow統合） |

---
