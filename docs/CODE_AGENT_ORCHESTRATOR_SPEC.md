# GitLab Coding Agent — Agent Framework 設計

**参考**: [Microsoft Semantic Kernel (Agent Framework)](https://learn.microsoft.com/en-us/semantic-kernel/?pivots=programming-language-python) | [GitHub Repository (Python)](https://github.com/microsoft/semantic-kernel/tree/main/python) | [Agent Framework Documentation (Python)](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)

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

- **[Microsoft Agent Framework](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)（Python）**: エージェントオーケストレーション基盤（MR処理のみ）
  - **[Filters (Middleware)](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters?pivots=programming-language-python)**: リクエスト/レスポンス処理、例外ハンドリング、カスタムパイプライン
  - **[OpenTelemetry統合](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/observability/?pivots=programming-language-python)**: 分散トレーシング、モニタリング、デバッグ
  - **[AI Services](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion?pivots=programming-language-python)**: 複数のLLMプロバイダーサポート
  - **注**: Process Framework（Workflow/Executor）はPython版で開発中
- **Producer/Consumerパターン（coding_agent踏襲）**: タスクキュー管理
  - **RabbitMQ**: 分散タスクキュー（100人規模対応）
  - **Producer**: GitLabからIssue/MR検出、キューに投入
  - **Consumer**: キューからタスク取得、Issue→MR変換またはMR処理
- **GitLab REST API**: GitLab操作の実行
- **LLM**: Azure OpenAI / OpenAI / Ollama / LM Studio
- **[MCP (Model Context Protocol)](https://modelcontextprotocol.io/)**: ツール実行の標準化
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

| コンポーネント | 責務 | 実装技術 | coding_agent参照・実装方針 |
|------------|------|---------|---------------------|
| **Producer** | Issue/MR検出・キューイング | Python + GitLab API + RabbitMQ | `producer.py`はcoding_agentの`main.py`のコードをベースに新規作成<br/>`queueing.py` |
| **Consumer** | タスクデキュー・処理振り分け | Python + RabbitMQ | `consumer.py`はcoding_agentの`main.py`のコードをベースに新規作成<br/>`queueing.py` |
| **TaskHandler** | タスク処理分岐（Issue/MR判定） | Python | `handlers/task_handler.py` |
| **RabbitMQ** | 分散タスクキュー | RabbitMQ（durable queue） | - |
| **TaskGetterFromGitLab** | GitLab API経由タスク取得 | Python + GitLab API | coding_agentのものをそのまま流用 |

#### 2.3.2 Issue→MR変換 Layer（前処理フロー）

| コンポーネント | 責務 | Agent Frameworkクラス | coding_agent参照・実装方針 |
|------------|------|---------|---------------------|
| **IssueToMRConverter** | Issue→MR変換 | 独自Workflow実装 | coding_agentを参考にして、独自のワークフロー管理クラスを実装 |
| **Branch Naming Agent** | ブランチ名生成 | [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python) | coding_agentを参考にして、Semantic KernelのChatCompletionAgentを使用してLLMにブランチ名生成を依頼 |

#### 2.3.3 MR処理 Layer（本フロー - Agent Framework）

| コンポーネント | 責務 | Agent Frameworkクラス | coding_agent参照・実装方針 |
|------------|------|---------|---------------------|
| **PlanningCoordinator** | 計画実行制御 | 独自Workflow実装 | 独自のフロー制御クラスでプランニング・実行・検証のフローを実装 |
| **MCPToolClient** | ファイル編集・コマンド実行 | Agent Framework MCP統合 | Agent FrameworkのMCPツール統合機能を使用してMCP Server (text-editor、command-executor)をAgent Frameworkツールとして統合 |
| **ExecutionEnvironmentManager** | Docker環境管理 | 独自実装 | `handlers/execution_environment_manager.py` 参考、独自クラスとして実装 |
| **ChatCompletionAgent (プランニング/実行/レビュー)** | LLM呼び出し | [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python) | `clients/llm_*.py` 参考、Semantic Kernelの[`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)を使用してLLM呼び出し |

**実装方針**: 
- MCPサーバー（text-editor、command-executor）はAgent FrameworkのMCPツール統合機能を使用してAgent Frameworkのツールとして登録する
- カスタムツール（todo管理等）はMCPサーバーではなく、Agent Frameworkのネイティブツールとして直接実装する

#### 2.3.4 Runtime Layer

| コンポーネント | 責務 | 実装技術 | Agent Framework | coding_agent参照・実装方針 |
|------------|------|---------|----------------|---------------------|
| **UserManager** | ユーザー情報・APIキー管理 | PostgreSQL + FastAPI | - | - |
| **PostgreSqlChatHistoryProvider** | 会話履歴永続化 | PostgreSQL | Semantic Kernel [ChatHistory](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python)パターン | `context_storage/message_store.py`参考、独自のHistory管理クラス実装 |
| **PlanningContextProvider** | プラン・要約永続化 | PostgreSQL | 独自Provider実装 | `context_storage/summary_store.py`参考、カスタムコンテキスト管理 |
| **ToolResultContextProvider** | ツール実行結果永続化 | File + PostgreSQL | 独自Provider実装 | `context_storage/tool_store.py`参考、ファイル+DB複合ストレージ |
| **PostgreSQL** | Context Storage + ユーザー情報 | PostgreSQL | - | - |
| **File Storage** | ツール実行結果保存 | ローカルファイルシステム | - | - |

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
| system_prompt_override | TEXT | | カスタムシステムプロンプト（非推奨、agent_prompt_overridesテーブル使用推奨） |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |

#### agent_prompt_overrides テーブル

エージェントごとのプロンプト上書き設定を管理する。ユーザーは各エージェントのプロンプトを個別にカスタマイズできる。

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | INTEGER | PK, AUTO | ID |
| user_id | INTEGER | FK(users.id), NOT NULL | ユーザーID |
| agent_name | TEXT | NOT NULL | エージェント名（task_classifier, code_generation_planning等） |
| prompt_override | TEXT | NOT NULL | カスタムプロンプト（PROMPTS.mdのデフォルトプロンプトを上書き） |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |

**制約**:
- UNIQUE(user_id, agent_name) - 1ユーザーにつき1エージェント1プロンプト

**エージェント名一覧**:
- `task_classifier` - Task Classifier Agent
- `code_generation_planning` - Code Generation Planning Agent
- `bug_fix_planning` - Bug Fix Planning Agent
- `test_creation_planning` - Test Creation Planning Agent
- `documentation_planning` - Documentation Planning Agent
- `plan_reflection` - Plan Reflection Agent
- `code_generation` - Code Generation Agent
- `bug_fix` - Bug Fix Agent
- `documentation` - Documentation Agent
- `test_creation` - Test Creation Agent
- `test_execution_evaluation` - Test Execution & Evaluation Agent
- `code_review` - Code Review Agent
- `documentation_review` - Documentation Review Agent

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

#### workflow_definitions テーブル

グラフ定義・エージェント定義・プロンプト定義のセット（ワークフロープリセット）を管理する。

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | INTEGER | PK, AUTO | 定義ID |
| name | TEXT | NOT NULL | プリセット名（例: "標準MR処理"） |
| description | TEXT | | 説明文 |
| graph_definition | JSONB | NOT NULL | グラフ定義（ノード・エッジ・条件分岐） |
| agent_definition | JSONB | NOT NULL | エージェント定義（各ノードのエージェント設定・ステップ間データ定義） |
| prompt_definition | JSONB | NOT NULL | プロンプト定義（各エージェントのシステムプロンプト・LLMパラメータ） |
| is_preset | BOOLEAN | DEFAULT false | システムプリセットフラグ（true=システム提供、false=ユーザー作成） |
| created_by | INTEGER | FK(users.id) | 作成者ユーザーID（NULLはシステム作成） |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |

**制約**:
- システムプリセット（is_preset=true）はユーザーによる削除・変更不可

**システム提供プリセット一覧**:
- `standard_mr_processing` - 標準MR処理（デフォルト）
- `multi_codegen_mr_processing` - コード生成を複数モデル・温度設定で並列実行

#### user_workflow_settings テーブル

ユーザーごとのワークフロー定義選択を管理する。

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | INTEGER | PK, AUTO | 設定ID |
| user_id | INTEGER | FK(users.id), UNIQUE | ユーザーID |
| workflow_definition_id | INTEGER | FK(workflow_definitions.id), NOT NULL | 使用するワークフロー定義ID |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |

**制約**:
- UNIQUE(user_id) - 1ユーザーにつき1つのワークフロー設定

### 3.4 APIキー暗号化

- **暗号化方式**: AES-256-GCM
- **キー管理**: 環境変数 `ENCRYPTION_KEY` で管理
- **暗号化範囲**: OpenAI APIキーのみ
- **復号化タイミング**: Consumer実行時にメモリ内で復号化

### 3.5 User Config API

User Config APIはユーザーごとのOpenAI APIキーとLLM設定を管理する。ユーザーの登録、更新、設定取得を行う。

#### エンドポイント

**GET /api/v1/config/{email}**
- Purpose: メールアドレスからユーザー設定を取得（OpenAI APIキー等）
- Authentication: Bearer Token
- Response: ユーザー設定（OpenAI APIキー復号化済み）

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

**GET /api/v1/users/{user_id}/prompt_overrides**
- Purpose: ユーザーのプロンプト上書き設定を取得
- Authentication: Bearer Token
- Response: エージェント名とカスタムプロンプトのリスト

**PUT /api/v1/users/{user_id}/prompt_overrides/{agent_name}**
- Purpose: 特定エージェントのプロンプトを上書き
- Authentication: Bearer Token
- Body: `{"prompt_override": "カスタムプロンプト"}`
- Response: 更新されたプロンプト設定

**DELETE /api/v1/users/{user_id}/prompt_overrides/{agent_name}**
- Purpose: プロンプト上書きを削除（デフォルトに戻す）
- Authentication: Bearer Token
- Response: 削除成功メッセージ

**GET /api/v1/workflow_definitions**
- Purpose: ワークフロー定義一覧取得（システムプリセット＋ユーザー作成）
- Authentication: Bearer Token
- Response: ワークフロー定義リスト（id, name, description, is_preset）

**GET /api/v1/workflow_definitions/{definition_id}**
- Purpose: ワークフロー定義詳細取得（グラフ定義・エージェント定義・プロンプト定義を含む）
- Authentication: Bearer Token
- Response: ワークフロー定義の全フィールド

**POST /api/v1/workflow_definitions**
- Purpose: ユーザー独自のワークフロー定義を新規作成
- Authentication: Bearer Token
- Body: name, description, graph_definition, agent_definition, prompt_definition
- Response: 作成されたワークフロー定義

**PUT /api/v1/workflow_definitions/{definition_id}**
- Purpose: ユーザー作成のワークフロー定義を更新（システムプリセットは更新不可）
- Authentication: Bearer Token
- Body: 更新する項目（name/description/graph_definition/agent_definition/prompt_definition）
- Response: 更新されたワークフロー定義

**DELETE /api/v1/workflow_definitions/{definition_id}**
- Purpose: ユーザー作成のワークフロー定義を削除（システムプリセットは削除不可）
- Authentication: Bearer Token
- Response: 削除成功メッセージ

**GET /api/v1/users/{user_id}/workflow_setting**
- Purpose: ユーザーの現在選択中のワークフロー定義を取得
- Authentication: Bearer Token
- Response: 選択中のワークフロー定義ID・名前

**PUT /api/v1/users/{user_id}/workflow_setting**
- Purpose: ユーザーが使用するワークフロー定義を選択・変更
- Authentication: Bearer Token
- Body: `{"workflow_definition_id": 1}`
- Response: 更新されたワークフロー設定

### 3.6 Web管理画面

Streamlitベースの管理画面を提供：

- **ダッシュボード**: 登録ユーザー数、アクティブタスク数
- **ユーザー管理**: ユーザーCRUD操作
- **設定管理**: LLM設定の編集
- **プロンプト管理**: エージェントごとのプロンプト上書き編集（全13エージェント対応）
- **ワークフロー管理**: ワークフロー定義の選択・カスタマイズ（グラフ定義・エージェント定義・プロンプト定義の編集）
- **トークン使用量**: ユーザー別トークン消費統計

---

### 3.7 ユーザー別トークン統計処理

各タスク実行時のトークン消費を記録し、ユーザー別の累計を管理する。

**実装方法**: Agent Frameworkの[Filters機能](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters?pivots=programming-language-python)を使用して、すべての[`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)呼び出しをインターセプトし、トークン消費を記録する。

#### 実装モジュール

**TokenUsageMiddleware**（Agent Framework [Filters](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters?pivots=programming-language-python)）:
- すべての[`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)呼び出しの前後で実行される
- [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)のレスポンスからトークン情報（`prompt_tokens`、`completion_tokens`、`total_tokens`）を取得
- ワークフローコンテキストから`user_id`と`task_uuid`を取得
- PostgreSQLの`token_usage`テーブルに記録
- Observability機能（[OpenTelemetry](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/observability/?pivots=programming-language-python)）と統合し、メトリクスとして送信

**WorkflowOrchestrator**での統合:
- ワークフローを構築する際に`TokenUsageMiddleware`を登録
- すべてのワークフロー実行で自動的にトークン統計が記録される

#### token_usageテーブル

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| id | SERIAL | PK | 統計ID |
| user_id | INTEGER | FK(users.id), NOT NULL | ユーザーID |
| task_uuid | TEXT | NOT NULL | タスクUUID |
| prompt_tokens | INTEGER | NOT NULL DEFAULT 0 | プロンプトトークン数 |
| completion_tokens | INTEGER | NOT NULL DEFAULT 0 | 応答トークン数 |
| total_tokens | INTEGER | NOT NULL DEFAULT 0 | 合計トークン数 |
| recorded_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 記録日時 |

**インデックス**:
- `idx_token_usage_user_id` ON (user_id)
- `idx_token_usage_task_uuid` ON (task_uuid)

Web管理画面では、ユーザー別のトークン使用量の累計・推移を確認できるダッシュボードを提供する。

---

## 4. エージェント構成

### 4.1 エージェント一覧

すべてのエージェントノードは同一の`ConfigurableAgent`クラスで実装される。エージェント定義IDによって動作が決まる。

| エージェント定義ID | 役割 | 入力コンテキストキー | 出力コンテキストキー |
|--------------|------|------|------|
| task_classifier | タスク分類 | task_context | classification_result |
| code_generation_planning | コード生成タスクの実行計画生成 | task_context, classification_result | plan_result, todo_list |
| bug_fix_planning | バグ修正タスクの実行計画生成 | task_context, classification_result | plan_result, todo_list |
| test_creation_planning | テスト作成タスクの実行計画生成 | task_context, classification_result | plan_result, todo_list |
| documentation_planning | ドキュメント生成タスクの実行計画生成 | task_context, classification_result | plan_result, todo_list |
| plan_reflection | プラン検証・改善 | plan_result, todo_list, task_context | reflection_result |
| code_generation | コード生成実装 | plan_result, task_context | execution_result |
| bug_fix | バグ修正実装 | plan_result, task_context | execution_result |
| documentation | ドキュメント作成 | plan_result, task_context | execution_result |
| test_creation | テスト作成 | plan_result, task_context | execution_result |
| test_execution_evaluation | テスト実行・評価 | execution_result, task_context | review_result |
| code_review | コードレビュー実施 | execution_result, task_context | review_result |
| documentation_review | ドキュメントレビュー実施 | execution_result, task_context | review_result |

#### 4.1.1 共通実装ルール

**プロンプト管理**:
- 各エージェントノードのデフォルトプロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照
- プロンプト定義ファイルはユーザーごとに選択・カスタマイズ可能（`workflow_definitions`テーブルで管理）
- プロンプト取得優先順位:
  1. ユーザーが選択した`workflow_definitions`内のプロンプト定義
  2. PROMPTS.mdのデフォルトプロンプト
- LLM呼び出し時には、プロンプト冒頭にAGENTS.mdの内容を含める

**プロンプト設定実装**:
- `AgentFactory`が`ConfigurableAgent`生成時にプロンプト定義ファイルから対応するプロンプトを取得する
- `ChatClientAgentOptions.instructions`にプロンプトを設定する

### 4.2 Factory設計

#### 4.2.1 WorkflowFactory

**責務**: ワークフロー定義ファイルに基づいて適切なWorkflowを生成する

**保持オブジェクト**:
- `WorkflowBuilder`: Workflow構築
- `ExecutorFactory`: Executor生成
- `AgentFactory`: AIAgent生成
- `MCPClientFactory`: MCPClient生成
- `ContextStorageManager`: コンテキスト管理
- `TodoManager`: Todo管理
- `TokenUsageMiddleware`: トークン統計
- `DefinitionLoader`: 定義ファイル読み込み

**主要メソッド**:
- `create_workflow_from_definition(user_id, task_context)`: ユーザーのワークフロー定義に基づいてWorkflowを生成する
- `_build_nodes(graph_def, agent_def, prompt_def, user_id)`: グラフ定義の各ノードに対してConfigurableAgentインスタンスを生成する
- `_setup_environments(graph_def)`: グラフ定義内でrequires_environment=trueのノード分のDocker環境を準備する

**実装方針**:
1. コンストラクタで各Factory、Manager、Middleware、DefinitionLoaderを保持
2. ワークフロー生成時にDefinitionLoaderでユーザーのワークフロー定義を取得する
3. グラフ定義のrequires_environment=trueのノード数分のDocker環境を事前準備する
4. WorkflowBuilderを使用してExecutorを追加（UserResolver、EnvironmentSetup等）
5. グラフ定義に従って各ノードのConfigurableAgentをWorkflowBuilderに追加する
6. TokenUsageMiddlewareをWorkflowBuilderに追加する
7. WorkflowBuilderのbuild()メソッドでWorkflowオブジェクトを生成して返却する

#### 4.2.2 ExecutorFactory

**責務**: タスク処理に必要なExecutorを生成する

**保持オブジェクト**:
- `UserConfigClient`: ユーザー設定取得
- `GitLabClient`: GitLab API操作
- `ExecutionEnvironmentManager`: Docker環境管理

**主要メソッド**:
- `create_user_resolver(context)`: UserResolverExecutor生成
- `create_content_transfer(context)`: ContentTransferExecutor生成
- `create_environment_setup(context)`: EnvironmentSetupExecutor生成

**実装方針**:
1. コンストラクタでUserConfigClient、GitLabClient、ExecutionEnvironmentManagerを保持
2. UserResolverExecutor生成時はWorkflowContextとUserConfigClientを渡してインスタンス化
3. ContentTransferExecutor生成時はWorkflowContextとGitLabClientを渡してインスタンス化
4. EnvironmentSetupExecutor生成時はWorkflowContextとExecutionEnvironmentManagerを渡してインスタンス化
5. 各Executorは共通のIWorkflowContextを介してタスク全体の状態を共有

#### 4.2.3 TaskStrategyFactory

**責務**: タスクの処理戦略を決定する（Issue→MR変換判定など）

**保持オブジェクト**:
- `GitLabClient`: GitLab API操作
- `ConfigManager`: 設定管理

**主要メソッド**:
- `create_strategy(task)`: タスクに対する処理戦略を生成
- `should_convert_issue_to_mr(task)`: Issue→MR変換が必要か判定

**実装方針**:
1. コンストラクタでGitLabClientとConfigManagerを保持
2. create_strategy()でタスクタイプを判定して適切な戦略クラスを生成
   - Issueタイプ：should_convert_issue_to_mr()でIssue→MR変換判定を実行
     - 変換必要な場合: IssueToMRConversionStrategyを生成
     - 変換不要な場合: IssueOnlyStrategyを生成
   - MergeRequestタイプ: MergeRequestStrategyを生成
   - 不明なタイプ: ValueErrorをスロー
3. should_convert_issue_to_mr()でcoding_agentから移植した判定ロジックを実行
   - 設定で指定されたbotラベルがIssueに付いているか確認
   - 同じIssue番号に対応するsource_branchを持つMRが既に存在しないか確認
   - 設定で自動変換が有効か確認
   - 全ての条件を満たす場合はTrueを返却

#### 4.2.4 MCPClientFactory

**責務**: MCPサーバーへのクライアント接続を生成し、Agent Frameworkのツールとして登録する

**保持オブジェクト**:
- `Dict[str, MCPServerConfig]`: サーバー設定
- `MCPClientRegistry`: クライアント登録管理
- `Kernel`: Agent Frameworkのカーネル（ツール登録用）

**主要メソッド**:
- `create_client(server_name)`: 指定されたMCPサーバーへのクライアント生成
- `create_text_editor_client()`: text-editorクライアント生成（Agent Frameworkツールとして登録）
- `create_command_executor_client()`: command-executorクライアント生成（Agent Frameworkツールとして登録）
- `register_mcp_tools_to_kernel(kernel)`: MCPツールをAgent Frameworkのカーネルに登録

**実装方針**:
1. コンストラクタでMCPServerConfig辞書、MCPClientRegistry、Agent FrameworkのKernelを保持
2. create_client()でMCPクライアント生成とツール登録を実施
   - 既にレジストリに登録済みの場合は既存クライアントを返却
   - 設定から指定されたサーバー名のMCPServerConfigを取得
   - MCPClientを生成してstdio経由で接続
   - レジストリに登録
   - _register_mcp_tools_to_kernel()を呼び出してAgent Frameworkのツールとして登録
3. _register_mcp_tools_to_kernel()でMCPツールをKernelに登録
   - MCPクライアントから利用可能なツール一覧を取得
   - 各ツールを_create_kernel_function_from_mcp_tool()でKernelFunctionに変換
   - kernel.add_function()でKernelに登録（plugin_name=サーバー名、function_name=ツール名）
4. _create_kernel_function_from_mcp_tool()でMCPツールをKernelFunctionとしてラップ
   - 非同期wrapper関数を定義してMCPツールを呼び出す
   - KernelFunction.from_native_method()でKernelFunctionとしてラップ
5. create_text_editor_client()とcreate_command_executor_client()は各MCPサーバーへのエイリアス

**Agent Frameworkツール統合のポイント**:
1. **MCPクライアント通信**: `MCPClient`でstdio経由でMCPサーバーと通信
2. **KernelFunctionラップ**: MCPツールを`KernelFunction`としてラップし、Agent Frameworkから呼び出し可能にする
3. **Kernel登録**: ラップしたツールを`kernel.add_function()`でKernelに登録
4. **ChatCompletionAgentで使用**: Kernelに登録されたツールは、同じKernelを使用する`ChatCompletionAgent`から自動的に利用可能になる

---

### 4.3 エージェント詳細

#### Producer（タスク検出コンポーネント）

**注意**: ProducerはAgent Frameworkの外側で動作する独立コンポーネントであり、Agent Frameworkのクラスを使用しない

**責務**: GitLabから処理対象のIssue/MRを検出し、RabbitMQにキューイングする

**処理フロー**:
1. GitLab APIで指定ラベル（`bot_label`: "coding agent"）のIssue/MR一覧取得
2. 処理中ラベル（`processing_label`: "coding agent processing"、`done_label`: "coding agent done"等）が付いていないものをフィルタ
3. 未処理タスクをRabbitMQにエンキュー
4. タスクに処理中ラベル（`processing_label`: "coding agent processing"）を付与

**ラベル仕様**: 以下のラベルを使用する。
- `bot_label`: "coding agent" - 処理対象タスク識別用
- `processing_label`: "coding agent processing" - 処理中状態
- `done_label`: "coding agent done" - 完了状態
- `paused_label`: "coding agent paused" - 一時停止状態
- `stopped_label`: "coding agent stopped" - 停止状態

#### Consumer（タスク処理コンポーネント）

**注意**: Consumer自体はAgent Frameworkの外側で動作するが、内部でAgent Frameworkのワークフローを呼び出す

**責務**: RabbitMQからタスクをデキューし、Issue→MR変換またはMR処理を実行する

**処理フロー**:
1. RabbitMQからタスクをデキューする
2. TaskHandler.handle()でタスク処理分岐を行う
   - Issueの場合: Issue→MR変換ワークフローを呼び出す（`WorkflowBuilder`で構築した`Workflow`を実行）
   - MRの場合: MR処理ワークフローを呼び出す（`WorkflowBuilder`で構築した`Workflow`を実行）
3. 処理完了後、RabbitMQにACKを送信する
4. タスクに完了ラベル（`done_label`: "coding agent done"）を付与する
5. エラー時は`stopped_label`: "coding agent stopped"を付与、一時停止時は`paused_label`: "coding agent paused"を付与する

---

### 4.3.1 エージェント共通設計

#### エージェントクラス設計方針

グラフ内の各エージェントノードは、**タスク種別ごとに異なるクラスを定義せず**、単一の `ConfigurableAgent` クラスで実装する。ノードごとの動作の違いは、グラフ定義ファイル・エージェント定義ファイル・プロンプト定義ファイルの設定によって制御する。

この設計により、以下のことが可能になる：
- コーディングエージェントを複数モデル・温度設定で並列実行し、レビュー時にユーザーが選択する等の柔軟なフロー変更
- コード変更なしにグラフ構造・エージェント動作・プロンプトを変更
- ユーザーごとにワークフロー全体をカスタマイズ

#### ConfigurableAgent（単一エージェントクラス）

**継承元**: [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)

**責務**: グラフ内のすべてのエージェントノードを実装する単一クラス。エージェント定義ファイルの設定に基づいて動作する。

**保持する設定（AgentNodeConfig）**:
- `node_id`: グラフノードID（例: "code_generation_planning"）
- `role`: エージェント役割（"planning" | "reflection" | "execution" | "review"）
- `input_keys`: 前ステップから受け取るワークフローコンテキストのキー一覧
- `output_keys`: 次ステップへ渡すワークフローコンテキストのキー一覧
- `tools`: 利用するツール名一覧（"text_editor", "command_executor", "todo_management" 等）
- `requires_environment`: 実行環境（Docker）が必要か（true/false）
- `prompt_id`: プロンプト定義ファイル内のプロンプト識別子

**共通メソッド**:
- `invoke_async(context)`: エージェント定義に従ってLLMを呼び出し、結果をコンテキストに保存する
- `get_chat_history()`: 会話履歴を取得する
- `get_context(keys)`: 指定キーのワークフローコンテキスト値を取得する
- `store_result(output_keys, result)`: 指定キーにエージェント実行結果を保存する
- `invoke_mcp_tool(tool_name, params)`: 設定で許可されたMCPツールを呼び出す

**ロール別の処理内容**:
- **planning**: コンテキスト取得→LLM呼び出し（プランニング）→Todoリスト作成→GitLab投稿→コンテキスト保存
- **reflection**: プラン取得→LLM呼び出し（検証）→改善判定→GitLab投稿→コンテキスト保存
- **execution**: プラン取得→LLM呼び出し（実装/生成）→ファイル操作（MCPツール）→git操作→コンテキスト保存
- **review**: MR差分取得→LLM呼び出し（レビュー）→コメント生成→GitLab投稿→コンテキスト保存

**ツール登録**:
- エージェント定義の`tools`フィールドに基づき、`AgentFactory`が`ChatClientAgentOptions.tools`に動的に登録する
- 登録可能なツール: text-editor MCPツール、command-executor MCPツール、create_todo_list、get_todo_list、update_todo_status、sync_to_gitlab

#### BaseExecutor（Executor基底クラス）

**責務**: すべてのExecutorの共通機能を提供する

**抽象メソッド**:
- `execute_async()`: 実行処理（各具体的Executorで実装）

**共通ヘルパーメソッド**:
- `get_context_value(key)`: ワークフローコンテキストから値を取得
- `set_context_value(key, value)`: ワークフローコンテキストに値を設定

**実装方法**:
- Agent Frameworkの`Executor`を継承
- `@MessageHandler`デコレータでメッセージハンドラを定義
- 共通リソース（ExecutionEnvironmentManager、MCPClientRegistry）への参照を保持

---

### 4.3.2 具体的エージェント実装

#### User Resolver Executor

**Agent Frameworkクラス**: `Executor`

**責務**: メールアドレスからユーザー設定を取得し、ワークフロー内で利用可能にする

**実装方法**:
- `Executor`クラスを継承し、`@MessageHandler`デコレータでメッセージハンドラを定義する
- User Config APIへのHTTPリクエストを実行する
- 取得したOpenAI APIキーをワークフローコンテキストに保存する（`IWorkflowContext.queue_state_update_async()`）

**処理フロー**:
1. ワークフローからメールアドレスを受け取る
2. User Config APIに問い合わせる (GET /api/v1/config/{email})
3. ユーザーが未登録の場合、例外をスローしてワークフローを停止する
4. OpenAI APIキーを復号化してワークフローコンテキストに保存する
5. 後続のExecutor/AIAgentがこのOpenAI APIキーを使用してLLMにアクセスする

**注**: GitLab PATはシステム全体で1つのbot用トークンを使用するため、ユーザーごとには管理しない。環境変数`GITLAB_PAT`で設定する。

#### Task Classifier Agent

**Agent Frameworkクラス**: `TaskClassifierAgent`（`ChatCompletionAgent`を継承）

**責務**: Issue/MR内容を分析し、タスクを4つのカテゴリのいずれかに分類する。プロンプト詳細はPROMPTS.mdを参照。

**実装方法**:
- `ChatCompletionAgent`を直接使用し、タスク分類専用のシステムプロンプトを設定する
- 分類結果を`ClassificationResult`データクラスで構造化する
- ワークフローコンテキストに分類結果を保存する（`IWorkflowContext.set_classification_result()`）

**処理フロー**:
1. Issue/MR情報の取得
   - タイトル、説明文、ラベル、添付ファイル、コメントの取得
   - GitLab APIから取得したデータをLLMに渡す形式に整形
2. リポジトリ構造の把握
   - `list_repository_files`ツールでファイル一覧を取得
   - プロジェクトの主要なディレクトリ構造を理解
3. タスク種別の判定
   - **code_generation**: 新機能実装、新規ファイル作成の要求を含む
   - **bug_fix**: エラーメッセージ、スタックトレース、再現手順が含まれる
   - **documentation**: README、API仕様、設計ドキュメント、運用手順等の要求
   - **test_creation**: テストコード、テストケース追加、テストカバレッジ向上の要求
4. 関連ファイルの特定
   - タスク内容から関連する可能性のあるファイルをリストアップ
   - `search_code`ツールで関連コードを検索
5. 仕様書の存在確認
   - code_generation、bug_fix、test_creationタスクの場合、関連する仕様/設計ファイル（docs/SPEC_*.md等）の存在を確認
   - `read_file`ツールで仕様書の内容を確認
6. 分類結果の構造化
   - `ClassificationResult`データクラスにマッピング
   - 信頼度スコア（confidence）を算出（0.0～1.0）
   - 分類理由（reasoning）を記録
7. コンテキスト保存
   - ワークフローコンテキストに分類結果を保存
   - 後続のPlanning Agentが参照可能にする

**利用可能なツール**（`ChatClientAgentOptions.tools`に登録）:
- `list_repository_files`: リポジトリ内のファイルをリスト表示（Agent FrameworkのMCPツールとして統合されたtext-editor MCPサーバーのツール）
- `read_file`: 特定のファイルの内容を読み込む（Agent FrameworkのMCPツールとして統合されたtext-editor MCPサーバーのツール）
- `search_code`: リポジトリ内のコードパターンを検索（Agent FrameworkのMCPツールとして統合されたtext-editor MCPサーバーのツール）

**出力形式**:
`ClassificationResult`データクラス（セクション5.5.6で定義）：
- `task_type`: タスク種別
- `confidence`: 分類信頼度
- `reasoning`: 分類理由
- `related_files`: 関連ファイルリスト
- `spec_file_exists`: 仕様書の存在フラグ
- `spec_file_path`: 仕様書パス（存在する場合）

**エラーハンドリング**:
- LLM APIエラー: 3回リトライ（指数バックオフ）
- 低信頼度（< 0.7）: GitLabにコメント投稿し、ユーザーに確認を求める
- 仕様書不在（code_generation/bug_fix/test_creation）: documentationタイプへのフォールバック判定

#### コード生成 Planning Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `code_generation_planning`）

**責務**: コード生成タスクの実行計画を生成する。プロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照。

**エージェント定義の主要設定**:
- `role`: "planning"
- `input_keys`: ["task_context", "classification_result"]
- `output_keys`: ["plan_result", "todo_list"]
- `tools`: ["text_editor", "create_todo_list", "sync_to_gitlab"]
- `requires_environment`: false

**処理フロー**:
1. 計画前情報収集（Issue/MR内容、関連ファイル、依存関係の分析）
2. 仕様ファイルの存在確認（docs/SPEC_*.md等）
3. 仕様ファイルが存在しない場合はドキュメント生成ワークフロー（5.3.3）にリダイレクト
4. 仕様ファイルが存在する場合、コード生成のためのアクションプランを生成
5. Todoリストの作成（`create_todo_list`ツールで永続化）
6. GitLabへのTodoリスト投稿（`sync_to_gitlab`ツール）

#### バグ修正 Planning Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `bug_fix_planning`）

**責務**: バグ修正タスクの実行計画を生成する。プロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照。

**エージェント定義の主要設定**:
- `role`: "planning"
- `input_keys`: ["task_context", "classification_result"]
- `output_keys`: ["plan_result", "todo_list"]
- `tools`: ["text_editor", "create_todo_list", "sync_to_gitlab"]
- `requires_environment`: false

**処理フロー**:
1. バグ情報の収集（エラーメッセージ、スタックトレース、再現手順）
2. 対象機能の仕様ファイルの存在確認
3. 仕様ファイルが存在しない場合はドキュメント生成ワークフロー（5.3.3）にリダイレクト
4. 仕様ファイルが存在する場合、バグ修正のためのアクションプランを生成
5. 修正対象ファイルと変更箇所の特定
6. Todoリストの作成と投稿

#### テスト生成 Planning Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `test_creation_planning`）

**責務**: テスト作成タスクの実行計画を生成する。プロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照。

**エージェント定義の主要設定**:
- `role`: "planning"
- `input_keys`: ["task_context", "classification_result"]
- `output_keys`: ["plan_result", "todo_list"]
- `tools`: ["text_editor", "create_todo_list", "sync_to_gitlab"]
- `requires_environment`: false

**処理フロー**:
1. テスト対象コードの分析（関数・クラス・モジュールの把握）
2. 対象機能の仕様ファイルの存在確認
3. 仕様ファイルが存在しない場合はドキュメント生成ワークフロー（5.3.3）にリダイレクト
4. テスト戦略の決定（ユニット/統合/E2Eテストの選択）
5. テストケースの設計（正常系・異常系・境界値）
6. Todoリストの作成と投稿

#### ドキュメント生成 Planning Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `documentation_planning`）

**責務**: ドキュメント生成タスクの実行計画を生成する。プロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照。

**エージェント定義の主要設定**:
- `role`: "planning"
- `input_keys`: ["task_context", "classification_result"]
- `output_keys`: ["plan_result", "todo_list"]
- `tools`: ["text_editor", "create_todo_list", "sync_to_gitlab"]
- `requires_environment`: false

**処理フロー**:
1. ドキュメント要件の収集（対象読者・ドキュメント種別の特定）
2. 既存ドキュメントの確認と整合性チェック
3. コードベース分析（ドキュメント対象の仕様・実装の把握）
4. ドキュメント構成の決定（セクション構成・図表の計画）
5. Todoリストの作成と投稿

#### Plan Reflection Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `plan_reflection`）

**責務**: プランニング後にプランを検証し、問題点を特定して改善案を提示する。プロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照。

**エージェント定義の主要設定**:
- `role`: "reflection"
- `input_keys`: ["plan_result", "todo_list", "task_context"]
- `output_keys`: ["reflection_result"]
- `tools`: ["text_editor", "get_todo_list", "sync_to_gitlab"]
- `requires_environment`: false

**処理フロー**:
1. プランとTodoリストの取得
   - ワークフローコンテキストから実行計画を取得
   - Todoリストの詳細を確認
   - Issue/MRの要求内容を確認
2. プランの検証
   - **整合性チェック**: プランの各ステップが論理的に整合しているか
   - **完全性チェック**: 必要な手順がすべて含まれているか（例: テスト、エラーハンドリング、エッジケース）
   - **実現可能性チェック**: 各ステップが実行可能か（例: 必要なファイルが存在するか、依存関係が解決できるか）
   - **明確性チェック**: 各ステップの説明が具体的で明確か
3. 問題点の特定
   - プランの曖昧な部分をリスト化
   - 矛盾している箇所を特定
   - 不足している情報や手順を特定
4. 改善案の生成
   - 問題点ごとに具体的な改善案を作成
   - 改善の優先度を設定（critical/major/minor）
   - 改善案を構造化された形式で出力
5. 改善判定
   - critical問題がある場合: 必ず改善が必要と判定
   - major問題のみの場合: 改善を推奨
   - minor問題のみの場合: そのまま実行可能と判定
6. GitLab投稿
   - 検証結果をMRまたはIssueにコメント投稿
   - 問題点と改善案を見やすい形式で提示
7. コンテキスト保存
   - 検証結果と改善案をワークフローコンテキストに保存
   - 反復回数をカウント（max_reflection_count以内）

**検証結果の出力形式**:
- `reflection_result`: "approved" | "needs_revision"（承認/改善必要）
- `issues`: 問題点のリスト（severity, category, description, improvement_suggestion）
- `overall_assessment`: プラン全体の評価コメント
- `action`: "proceed" | "revise_plan"（実行続行/プラン再作成）

#### Code Generation Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `code_generation`）

**責務**: 新規コードを生成する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_result"]
- `tools`: ["text_editor", "command_executor", "update_todo_status", "sync_to_gitlab"]
- `requires_environment`: true

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

#### Bug Fix Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `bug_fix`）

**責務**: バグ修正を実装する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_result"]
- `tools`: ["text_editor", "command_executor", "update_todo_status", "sync_to_gitlab"]
- `requires_environment`: true

**処理フロー**:
1. バグ情報の分析
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

#### Documentation Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `documentation`）

**責務**: ドキュメントを作成する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_result"]
- `tools`: ["text_editor", "update_todo_status", "sync_to_gitlab"]
- `requires_environment`: false

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

#### Test Creation Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `test_creation`）

**責務**: テストコードを作成する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_result"]
- `tools`: ["text_editor", "command_executor", "update_todo_status", "sync_to_gitlab"]
- `requires_environment`: true

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

#### Test Execution & Evaluation Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `test_execution_evaluation`）

**責務**: テストコードを実行し、結果を評価する

**エージェント定義の主要設定**:
- `role`: "review"
- `input_keys`: ["execution_result", "task_context"]
- `output_keys`: ["review_result"]
- `tools`: ["command_executor", "sync_to_gitlab"]
- `requires_environment`: true

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

プロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照

#### Code Review Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `code_review`）

**責務**: コードレビューを実施する

**エージェント定義の主要設定**:
- `role`: "review"
- `input_keys`: ["execution_result", "task_context"]
- `output_keys`: ["review_result"]
- `tools`: ["text_editor", "sync_to_gitlab"]
- `requires_environment`: false

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

LLMへ渡すロール定義・チェック項目・出力フォーマットのプロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照

#### Documentation Review Agent ノード

**Agent Frameworkクラス**: `ConfigurableAgent`（エージェント定義: `documentation_review`）

**責務**: ドキュメントレビューを実施する

**エージェント定義の主要設定**:
- `role`: "review"
- `input_keys`: ["execution_result", "task_context"]
- `output_keys`: ["review_result"]
- `tools`: ["text_editor", "sync_to_gitlab"]
- `requires_environment`: false

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

LLMへ渡すロール定義・チェック項目・出力フォーマットのプロンプト詳細はPROMPTS.mdおよびプロンプト定義ファイルを参照

---

### 4.4 定義ファイル管理

グラフ・エージェント・プロンプトの各定義ファイルはシステムが複数のプリセットを提供し、ユーザーがプリセットを選択したうえで独自にカスタマイズすることができる。各定義の詳細設計は以下のファイルを参照する。

- **グラフ定義ファイル詳細設計**: [GRAPH_DEFINITION_SPEC.md](GRAPH_DEFINITION_SPEC.md)
- **エージェント定義ファイル詳細設計**: [AGENT_DEFINITION_SPEC.md](AGENT_DEFINITION_SPEC.md)
- **プロンプト定義ファイル詳細設計**: [PROMPT_DEFINITION_SPEC.md](PROMPT_DEFINITION_SPEC.md)

#### 4.4.1 定義ファイルの関係

```mermaid
flowchart LR
    subgraph 定義ファイル
        G[グラフ定義ファイル<br/>フロー・ノード・エッジ定義]
        A[エージェント定義ファイル<br/>各ノードの設定・データ定義]
        P[プロンプト定義ファイル<br/>システムプロンプト・LLMパラメータ]
    end

    subgraph ランタイム
        DL[DefinitionLoader]
        WB[WorkflowBuilder]
        CA[ConfigurableAgent]
    end

    G --> DL
    A --> DL
    P --> DL
    DL --> WB
    WB --> CA
```

#### 4.4.2 DefinitionLoader

**責務**: グラフ定義・エージェント定義・プロンプト定義をロードし、WorkflowBuilderに渡せる形式に変換する

**主要メソッド**:
- `load_workflow_definition(definition_id)`: 指定IDのワークフロー定義をDBから取得し、グラフ・エージェント・プロンプト定義をパースして返す
- `get_preset_definitions()`: システムプリセットのワークフロー定義一覧を返す
- `validate_graph_definition(graph_def)`: グラフ定義の整合性チェック（参照されるノードが存在するか等）
- `validate_agent_definition(agent_def, graph_def)`: エージェント定義がグラフ定義のノードと整合するかチェック
- `validate_prompt_definition(prompt_def, agent_def)`: プロンプト定義がエージェント定義のプロンプトIDと整合するかチェック

**実装方針**:
1. `WorkflowFactory`がタスク処理開始時に`DefinitionLoader`を呼び出す
2. ユーザーの`user_workflow_settings`から選択中の`workflow_definition_id`を取得する
3. `workflow_definitions`テーブルから定義を取得してパースする
4. パースした定義を`WorkflowBuilder`に渡し、`ConfigurableAgent`のインスタンスを生成させる

#### 4.4.3 WorkflowFactory（更新）

`WorkflowFactory`はグラフ定義ファイルに基づいてワークフローを動的に構築する。以前のタスク種別別ハードコードされたメソッド（`create_code_generation_workflow`等）は廃止し、定義ファイルからの動的構築に置き換える。

**更新後の主要メソッド**:
- `create_workflow_from_definition(user_id, task_context)`: ユーザーのワークフロー定義を読み込み、グラフ定義に従ってWorkflowを生成する
- `_build_nodes(graph_def, agent_def, prompt_def, user_id)`: グラフ定義の各ノードに対して`ConfigurableAgent`インスタンスを生成する
- `_setup_environments(graph_def)`: グラフ定義内で`requires_environment: true`のノードに対してDocker環境を準備する

**複数環境のサポート**:
グラフ定義でノードごとに`requires_environment`フラグを設定することで、必要なノード分の実行環境を事前に作成する。これにより、複数のコーディングエージェントノードが独立した環境で並列実行可能になる。

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

#### 5.0.3 IssueToMRConverter（独自Workflow実装）

**実装方法**:
coding_agentを参考にして、ワークフロー管理クラスを実装する。clients/gitlab_client.pyはそのまま流用する。
※Python版Agent FrameworkはProcess Framework (Workflow/Executor)が未実装のため、独自のワークフロークラスで実装する。

| コンポーネント | 参照元 | 役割 | 実装方法 |
|----------------|-----------|------|---------|
| **IssueToMRConverter** | `handlers/issue_to_mr_converter.py` | Issue→MR変換のメインクラス | 独自ワークフロークラスとして定義 |
| **BranchNameGenerator** | `handlers/issue_to_mr_converter.py` | LLMを使用したブランチ名生成 | [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)で実装 |
| **ContentTransferManager** | `handlers/issue_to_mr_converter.py` | IssueコメントのMRへの転記 | 独自ヘルパークラスで実装 |
| **GitlabClient** | `clients/gitlab_client.py` | GitLab API操作（ブランチ、コミット、MR作成） | 適切なAPIクライアントとして使用 |

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

**Agent Frameworkワークフロー実装**:
- グラフ定義ファイルに定義されたフローに従い、`WorkflowBuilder`でノードをステップとして登録する
- 各ノードは同一の`ConfigurableAgent`クラスで実装し、エージェント定義ファイルの設定によって動作を制御する
- `IWorkflowContext`でステップ間のデータ（プラン、実行結果等）を共有する
- Agent FrameworkのGraph-based Workflows機能を使用して分岐とループを実現する
- グラフ定義ファイルで`requires_environment: true`が設定されたノードに対しては、ワークフロー開始前にDocker実行環境を準備する

**注**: Issue→MR変換後、作成されたMRは次回のワークフロー実行時に以下のフローで処理される。グラフ内の各ノード（Code Generation Planning Agent等）はすべて`ConfigurableAgent`の同一クラスであり、グラフ定義ファイル・エージェント定義ファイル・プロンプト定義ファイルによって動作が決まる。

```mermaid
flowchart TD
    Start([タスク開始]) --> LoadDef[定義ファイル読み込み<br/>DefinitionLoader]
    LoadDef --> SetupEnv[実行環境セットアップ<br/>requires_environment=trueのノード分]
    SetupEnv --> Fetch[MR情報取得<br/>Consumer]
    Fetch --> UserResolve[ユーザー情報取得<br/>User Resolver Agent]
    UserResolve --> PrePlanning[計画前情報収集<br/>+ タスク分類<br/>Task Classifier Agent]
    
    PrePlanning --> TaskType{タスク種別判定}
    
    TaskType -->|コード生成| CodeGenPlanning[ConfigurableAgent<br/>code_generation_planning]
    TaskType -->|バグ修正| BugFixPlanning[ConfigurableAgent<br/>bug_fix_planning]
    TaskType -->|ドキュメント生成| DocPlanning[ConfigurableAgent<br/>documentation_planning]
    TaskType -->|テスト作成| TestPlanning[ConfigurableAgent<br/>test_creation_planning]
    
    CodeGenPlanning --> CodeGenSpec{仕様書確認}
    CodeGenSpec -->|仕様書なし| DocPlanning
    CodeGenSpec -->|仕様書あり| CodeGenTodo[Todo投稿]
    
    BugFixPlanning --> BugFixSpec{仕様書確認}
    BugFixSpec -->|仕様書なし| DocPlanning
    BugFixSpec -->|仕様書あり| BugFixTodo[Todo投稿]
    
    TestPlanning --> TestSpec{仕様書確認}
    TestSpec -->|仕様書なし| DocPlanning
    TestSpec -->|仕様書あり| TestTodo[Todo投稿]
    
    DocPlanning --> DocTodo[Todo投稿]
    
    CodeGenTodo --> Execute
    BugFixTodo --> Execute
    TestTodo --> Execute
    DocTodo --> Execute
    
    Execute{タスク実行}
    Execute -->|コード生成| CodeGen[ConfigurableAgent<br/>code_generation]
    Execute -->|バグ修正| BugFix[ConfigurableAgent<br/>bug_fix]
    Execute -->|ドキュメント生成| DocGen[ConfigurableAgent<br/>documentation]
    Execute -->|テスト作成| TestGen[ConfigurableAgent<br/>test_creation]
    
    CodeGen --> CodeReview[ConfigurableAgent<br/>code_review]
    BugFix --> CodeReview
    TestGen --> CodeReview
    DocGen --> DocReview[ConfigurableAgent<br/>documentation_review]
    
    CodeReview --> Reflection[ConfigurableAgent<br/>plan_reflection]
    DocReview --> Reflection
    
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| TaskType
    ReplanCheck -->|No 問題なし/軽微| Complete{完了?}
    
    Complete -->|No 追加作業| Execute
    Complete -->|Yes| Finish[タスク完了]
    
    Finish --> End([終了])
```

**主要ノード構成**:

| フェーズ | エージェント定義ID | 目的 |
|---------|---------------|------|
| 定義読み込み | DefinitionLoader | グラフ/エージェント/プロンプト定義をロード |
| 環境セットアップ | EnvironmentSetupExecutor | requires_environment=trueノード分の環境を準備 |
| Issue/MR取得 | Consumer | RabbitMQからタスクデキュー |
| ユーザー情報取得 | User Resolver Agent | OpenAI APIキー・LLM設定取得 |
| 計画前情報収集 | task_classifier | タスク種別判定（4種類） |
| 計画 | code_generation_planning / bug_fix_planning / test_creation_planning / documentation_planning | タスク種別別実行プラン生成 |
| 実行 | code_generation / bug_fix / documentation / test_creation | タスク実装 |
| レビュー | code_review / documentation_review | 品質確認 |
| テスト実行・評価 | test_execution_evaluation | テスト実行・結果評価（コード生成/バグ修正のみ） |
| リフレクション | plan_reflection | 結果評価・再計画判断 |

**重要なフロー特性**:

1. **同一クラスによる実装**: すべてのグラフノードは`ConfigurableAgent`クラスで実装し、エージェント定義IDによって動作が異なる
2. **設定ベースの柔軟性**: グラフ定義・エージェント定義・プロンプト定義を変更することでコード変更なしにフローを変更可能
3. **仕様ファイル必須（コード生成系）**: コード生成、バグ修正、テスト作成で仕様ファイルがなければドキュメント生成計画を立案し、仕様書作成後にタスク完了
4. **自動レビュー**: 実行後に必ずレビューエージェントが品質確認（ユーザー承認不要）
5. **再計画ループ**: レビューで重大な問題があれば計画フェーズに戻る
6. **複数環境サポート**: グラフ定義で`requires_environment: true`のノードに対してDocker環境を事前準備

### 5.2 フェーズ詳細

#### 5.2.1 計画前情報収集フェーズ

**目的**: タスク種別を判定し、計画に必要な情報を収集する

**使用エージェント**: `ConfigurableAgent`（エージェント定義: `task_classifier`）

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

**使用エージェント**: `ConfigurableAgent`（エージェント定義: `code_generation_planning` / `bug_fix_planning` / `test_creation_planning` / `documentation_planning`）

**実行内容**:
1. 目標の明確化 (Goal Understanding)
2. タスク分解 (Task Decomposition)
3. アクション系列生成 (Action Sequence Generation)
4. **Todoリストの作成**: `create_todo_list` ツールで構造化
5. **仕様ファイル確認**: 
   - コード生成系タスク（バグ修正、テスト作成）の場合、関連する仕様/設計ファイル（Markdown）の存在確認
   - ファイルパス: `docs/SPEC_*.md`, `docs/DESIGN_*.md`, `SPECIFICATION.md` 等
6. 依存関係の定義

**出力形式**: 以下の情報を含むJSONオブジェクトを返す
- `goal`: 目標の明確な記述
- `task_type`: タスク種別（code_generation / bug_fix / documentation / test_creation）
- `spec_file_path`: 仕様ファイルのパス
- `spec_file_exists`: 仕様ファイルの存在可否（true/false）
- `transition_to_doc_generation`: ドキュメント生成への遷移が必要か（true/false）
- `success_criteria`: 完了基準のリスト
- `subtasks`: サブタスクの一覧（id, description, dependencies）
- `actions`: 実行アクションの一覧（action_id, task_id, agent, tool, purpose）

**仕様ファイルがない場合の処理**:
- コード生成系タスク（`code_generation`, `bug_fix`, `test_creation`）で `spec_file_exists: false` の場合
- `documentation_planning`エージェント定義を使用したドキュメント生成のための計画を立案
- `documentation`エージェント定義 → `documentation_review`エージェント定義 で仕様書を作成
- `plan_reflection`エージェント定義で問題があれば再計画
- 問題なければ仕様書作成完了で終了（コード生成/バグ修正/テスト作成は実行しない）

#### 5.2.4 実行フェーズ

**目的**: 計画されたアクションを実行する

**使用エージェント**: `ConfigurableAgent`（エージェント定義: `code_generation` / `bug_fix` / `documentation` / `test_creation`）

**実行内容**:
1. タスク種別別実行
   - **`code_generation`エージェント定義**: 新規コード生成
   - **`bug_fix`エージェント定義**: バグ修正実装
   - **`documentation`エージェント定義**: ドキュメント作成
   - **`test_creation`エージェント定義**: テストコード作成
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

**使用エージェント**: `ConfigurableAgent`（エージェント定義: `plan_reflection`）

**実行タイミング**:
- レビューで問題が検出された時
- アクション失敗時
- ユーザーコメント受信時

**評価項目**:
- レビューコメントの重大度
- 修正の複雑さ
- 計画との乖離
- 代替アプローチの検討

**出力形式**: 以下の情報を含むJSONオブジェクトを返す（`reflection`キー配下）
- `status`: 評価結果（success / needs_revision / needs_replan）
- `review_issues`: レビュー指摘の一覧（severity: critical/major/minor, description, suggestion）
- `plan_revision_needed`: 計画修正が必要か（true/false）
- `revision_actions`: 修正アクションの一覧（action_id, purpose, agent）
- `replan_reason`: 再計画が必要な理由（needs_replanの場合）

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
    Start[コード生成タスク開始] --> Planning[ConfigurableAgent<br/>code_generation_planning<br/>実行計画生成]
    Planning --> SpecCheck{仕様ファイル確認}
    
    SpecCheck -->|存在する| Todo[Todo投稿]
    SpecCheck -->|存在しない| End1([ドキュメント生成フロー])
        
    Todo --> CodeGen[ConfigurableAgent<br/>code_generation<br/>コード生成実装]
    CodeGen --> CodeReview[ConfigurableAgent<br/>code_review<br/>コードレビュー]
    
    CodeReview --> TestExec[ConfigurableAgent<br/>test_execution_evaluation<br/>テスト実行・評価]
    
    TestExec --> TestResult{テスト結果}
    TestResult -->|成功| Reflection[ConfigurableAgent<br/>plan_reflection]
    TestResult -->|失敗| TestReflection[ConfigurableAgent<br/>plan_reflection<br/>テスト失敗分析]
    
    TestReflection --> TestReplan{再計画必要?}
    TestReplan -->|Yes 実装の問題| CodeGen
    TestReplan -->|テストの問題| TestCreate[ConfigurableAgent<br/>test_creation<br/>テスト修正]
    TestCreate --> TestExec
    
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| CodeGen
    Complete -->|Yes| Finish[完了]
    Finish --> End2([終了])
```

**フロー詳細**:
1. `code_generation_planning`エージェント定義のConfigurableAgentが実行計画を生成
2. 関連する仕様ファイルの存在確認
3. **仕様ファイルがない場合**:
   - `documentation_planning`エージェント定義のConfigurableAgentがドキュメント生成計画を立案
   - `documentation`エージェント定義のConfigurableAgentが仕様書を作成
   - `documentation_review`エージェント定義のConfigurableAgentが自動レビュー（ユーザー承認不要）
   - `plan_reflection`エージェント定義のConfigurableAgentで問題があれば再計画（ドキュメント生成）
   - 問題なければ仕様書作成完了で終了（コード生成は実行しない）
4. **仕様ファイルがある場合**:
   - `code_generation`エージェント定義のConfigurableAgentが新規コード生成
   - `code_review`エージェント定義のConfigurableAgentがコードレビュー（仕様書との整合性を含む）
   - **`test_execution_evaluation`エージェント定義のConfigurableAgentがテスト実行・評価**
     - 既存のテストコードを実行（ユニット、統合、E2E）
     - テスト結果を評価（成功率、カバレッジ、失敗原因）
     - **テスト失敗時**: `plan_reflection`エージェント定義で原因分析
       - 実装の問題 → `code_generation`エージェント定義に戻って修正
       - テストの問題 → `test_creation`エージェント定義でテスト修正
     - **テスト成功時**: `plan_reflection`フェーズへ進む
   - `plan_reflection`エージェント定義で問題を評価
     - 重大な問題（アーキテクチャ、仕様乖離）→ 再計画
     - 軽微な修正（コーディング規約）→ 修正後完了チェック
   - 問題なければ完了

#### 5.3.2 バグ修正フロー

```mermaid
flowchart TD
    Start[バグ修正タスク開始] --> Planning[ConfigurableAgent<br/>bug_fix_planning<br/>実行計画生成]
    Planning --> SpecCheck{仕様ファイル確認}
    
    SpecCheck -->|存在する| Todo[Todo投稿]
    SpecCheck -->|存在しない| End1([ドキュメント生成フロー])
    
    Todo --> BugFix[ConfigurableAgent<br/>bug_fix<br/>バグ修正実装]
    BugFix --> CodeReview[ConfigurableAgent<br/>code_review<br/>コードレビュー]
    
    CodeReview --> TestExec[ConfigurableAgent<br/>test_execution_evaluation<br/>テスト実行・評価]
    
    TestExec --> TestResult{テスト結果}
    TestResult -->|成功| Reflection[ConfigurableAgent<br/>plan_reflection]
    TestResult -->|失敗| TestReflection[ConfigurableAgent<br/>plan_reflection<br/>テスト失敗分析]
    
    TestReflection --> TestReplan{再計画必要?}
    TestReplan -->|Yes 修正の問題| BugFix
    TestReplan -->|テストの問題| TestCreate[ConfigurableAgent<br/>test_creation<br/>テスト修正]
    TestCreate --> TestExec
    
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| BugFix
    Complete -->|Yes| Finish[完了]
    Finish --> End2([終了])
```

**フロー詳細**:
1. `bug_fix_planning`エージェント定義のConfigurableAgentが実行計画を生成
2. 関連する仕様ファイル（バグ修正対象機能の仕様）の存在確認
3. **仕様ファイルがない場合**:
   - `documentation_planning`エージェント定義のConfigurableAgentがドキュメント生成計画を立案
   - `documentation`エージェント定義のConfigurableAgentが仕様書を作成
   - `documentation_review`エージェント定義のConfigurableAgentが自動レビュー（ユーザー承認不要）
   - `plan_reflection`エージェント定義のConfigurableAgentで問題があれば再計画（ドキュメント生成）
   - 問題なければ仕様書作成完了で終了（バグ修正は実行しない）
4. **仕様ファイルがある場合**:
   - `bug_fix`エージェント定義のConfigurableAgentがバグ修正を実装
   - `code_review`エージェント定義のConfigurableAgentがコードレビュー（仕様書との整合性を含む）
   - **`test_execution_evaluation`エージェント定義のConfigurableAgentがテスト実行・評価**
     - 既存のテストコードを実行（回帰テスト含む）
     - テスト結果を評価（バグ修正の検証、副作用の検出）
     - **テスト失敗時**: `plan_reflection`エージェント定義で原因分析
       - 修正の問題（バグが残っている、新たなバグ）→ `bug_fix`エージェント定義に戻って修正
       - テストの問題（テストケースの誤り）→ `test_creation`エージェント定義でテスト修正
     - **テスト成功時**: `plan_reflection`フェーズへ進む
   - `plan_reflection`エージェント定義で問題を評価
     - 重大な問題（根本原因の誤認識）→ 再計画
     - 軽微な修正（コーディング規約）→ 修正後完了チェック
   - 問題なければ完了

#### 5.3.3 ドキュメント生成フロー

```mermaid
flowchart TD
    Start[ドキュメント生成タスク開始] --> Planning[ConfigurableAgent<br/>documentation_planning<br/>実行計画生成]
    Planning --> Todo[Todo投稿]
    
    Todo --> DocCreate[ConfigurableAgent<br/>documentation<br/>ドキュメント作成]
    DocCreate --> DocReview[ConfigurableAgent<br/>documentation_review<br/>ドキュメントレビュー]
    
    DocReview --> Reflection[ConfigurableAgent<br/>plan_reflection]
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| DocCreate
    Complete -->|Yes| Finish[完了]
    Finish --> End([終了])
```

**フロー詳細**:
1. `documentation_planning`エージェント定義のConfigurableAgentが実行計画を生成
2. `documentation`エージェント定義のConfigurableAgentがドキュメントを作成（README、API仕様、運用手順、仕様書等）
3. `documentation_review`エージェント定義のConfigurableAgentが自動レビュー（正確性、構造、完全性）
4. `plan_reflection`エージェント定義のConfigurableAgentで問題を評価
   - 重大な問題（技術的誤り、構造の欠陥）→ 再計画
   - 軽微な修正（表記ゆれ、リンク切れ）→ 修正後完了チェック
5. 問題なければ完了

**注意**: ドキュメント生成タスクでは仕様ファイル確認は不要（作成するのがドキュメント自体のため）

#### 5.3.4 テスト作成フロー

```mermaid
flowchart TD
    Start[テスト作成タスク開始] --> Planning[ConfigurableAgent<br/>test_creation_planning<br/>実行計画生成]
    Planning --> SpecCheck{仕様ファイル確認}
    
    SpecCheck -->|存在する| Todo[Todo投稿]
    SpecCheck -->|存在しない| End1([ドキュメント生成フロー])
    
    Todo --> TestCreate[ConfigurableAgent<br/>test_creation<br/>テスト作成]
    TestCreate --> CodeReview[ConfigurableAgent<br/>code_review<br/>コードレビュー]
    
    CodeReview --> Reflection[ConfigurableAgent<br/>plan_reflection]
    Reflection --> ReplanCheck{再計画必要?}
    ReplanCheck -->|Yes 重大な問題| Planning
    ReplanCheck -->|No 軽微な修正| Complete{完了?}
    
    Complete -->|No| TestCreate
    Complete -->|Yes| Finish[完了]
    Finish --> End2([終了])
```

**フロー詳細**:
1. `test_creation_planning`エージェント定義のConfigurableAgentが実行計画を生成
2. テスト対象コードの仕様ファイルの存在確認
3. **仕様ファイルがない場合**:
   - `documentation_planning`エージェント定義のConfigurableAgentがドキュメント生成計画を立案
   - `documentation`エージェント定義のConfigurableAgentが仕様書を作成
   - `documentation_review`エージェント定義のConfigurableAgentが自動レビュー（ユーザー承認不要）
   - `plan_reflection`エージェント定義のConfigurableAgentで問題があれば再計画（ドキュメント生成）
   - 問題なければ仕様書作成完了で終了（テスト作成は実行しない）
4. **仕様ファイルがある場合**:
   - `test_creation`エージェント定義のConfigurableAgentがテストコードを作成（ユニット/統合/E2E）
   - `code_review`エージェント定義のConfigurableAgentがテストコードをレビュー（網羅性、品質、仕様書との整合性）
   - `plan_reflection`エージェント定義のConfigurableAgentで問題を評価
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

### 5.5 オブジェクト構造設計

#### 5.5.1 概要

本システムは、Agent Frameworkの標準機能を活用しながら、独自のオブジェクト管理を実装する。以下では、各オブジェクトの保持関係とライフサイクル管理を明示する。

**主要な設計パターン**:
1. **Provider方式によるコンテキスト管理**: `PostgreSqlChatHistoryProvider`、`PlanningContextProvider`、`ToolResultContextProvider`を使用し、[ChatHistory](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python)パターンでコンテキストを永続化する
2. **Filters方式によるトークン統計**: `TokenUsageMiddleware`を使用し、すべての[`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)呼び出しを自動的にインターセプトしてトークン使用量を記録する
3. **プロンプト上書き機能**: `PromptOverrideManager`と`agent_prompt_overrides`テーブルを使用し、ユーザーごとに全6エージェントのプロンプトを個別カスタマイズ可能にする
4. **Factory方式によるオブジェクト生成**: `AgentFactory`、`MCPClientFactory`を使用し、タスクタイプに応じた適切なエージェントとコンポーネントを生成する
5. **Strategy方式によるタスク処理**: `TaskStrategyFactory`を使用し、Issue→MR変換判定などのタスク固有の処理戦略を決定する
6. **共有リソースの再利用**: `ExecutionEnvironmentManager`、`MCPClientRegistry`、`ContextStorageManager`等を複数タスク処理で再利用し、リソース効率を最適化する

#### 5.5.2 オブジェクト構造図

```mermaid
classDiagram
    %% Producer/Consumer層（Agent Framework外）
    class Consumer {
        -RabbitMQConnection connection
        -TaskHandler task_handler
        +consume_tasks() void
        +run_consumer_continuous() void
    }
    
    class TaskHandler {
        -WorkflowExecutor executor
        -GitLabClient gitlab_client
        -TaskStatusManager status_manager
        -TaskStrategyFactory strategy_factory
        +handle(task) TaskResult
        +_determine_task_strategy(task) TaskStrategy
    }
    
    %% ワークフローオーケストレーション
    class WorkflowExecutor {
        -WorkflowFactory workflow_factory
        -ExecutionEnvironmentManager env_manager
        -ProgressReporter progress_reporter
        +execute_workflow(task_type, user_id, context) WorkflowResult
        +cleanup_resources(task_uuid) void
    }
    
    class WorkflowFactory {
        -WorkflowBuilder builder
        -ExecutorFactory executor_factory
        -AgentFactory agent_factory
        -MCPClientFactory mcp_factory
        -ContextStorageManager context_storage
        -TodoManager todo_manager
        -TokenUsageMiddleware token_middleware
        -ErrorHandlingMiddleware error_handling_middleware
        -PromptOverrideManager prompt_override_manager
        +create_code_generation_workflow(user_id) Workflow
        +create_bug_fix_workflow(user_id) Workflow
        +create_test_generation_workflow(user_id) Workflow
        +create_refactoring_workflow(user_id) Workflow
        +create_document_workflow(user_id) Workflow
        +create_code_review_workflow(user_id) Workflow
    }
    
    %% Factory群
    class ExecutorFactory {
        -UserConfigClient config_client
        -GitLabClient gitlab_client
        -ExecutionEnvironmentManager env_manager
        +create_user_resolver(context) UserResolverExecutor
        +create_content_transfer(context) ContentTransferExecutor
        +create_environment_setup(context) EnvironmentSetupExecutor
    }
    
    class TaskStrategyFactory {
        -GitLabClient gitlab_client
        -ConfigManager config_manager
        +create_strategy(task) TaskStrategy
        +should_convert_issue_to_mr(task) bool
    }
    
    class MCPClientFactory {
        -Dict~str,MCPServerConfig~ server_configs
        -MCPClientRegistry registry
        +create_client(server_name) MCPClient
        +create_text_editor_client() MCPClient
        +create_command_executor_client() MCPClient
    }
    
    %% Agent Frameworkコアオブジェクト
    class Workflow {
        -List~Executor~ executors
        -List~AIAgent~ agents
        -IWorkflowContext context
        -List~Middleware~ middlewares
        +add_step(step) void
        +add_middleware(middleware) void
        +execute() WorkflowResult
    }
    
    class WorkflowBuilder {
        -ExecutorFactory executor_factory
        -AgentFactory agent_factory
        -TokenUsageMiddleware token_middleware
        -ErrorHandlingMiddleware error_handling_middleware
        +add_executor(executor_type) WorkflowBuilder
        +add_agent(agent_type, config) WorkflowBuilder
        +add_middleware(middleware) WorkflowBuilder
        +build() Workflow
    }
    
    class IWorkflowContext {
        -Dict state
        -ContextStorageManager storage
        +queue_state_update_async(key, value) void
        +get_state(key) Any
        +get_chat_history() List~Message~
    }
    
    class AgentSession {
        -str session_id
        -ChatHistoryProvider history_provider
        -List~AIContextProvider~ context_providers
        -ProviderSessionState state
        +get_history() List~Message~
        +add_context(provider) void
    }
    
    %% Provider実装（セクション8で定義）
    class PostgreSqlChatHistoryProvider {
        -ContextStorageManager storage
        +provide_history_async(session) List~Message~
        +store_message_async(session, message) void
    }
    
    class PlanningContextProvider {
        -ContextStorageManager storage
        +provide_context_async(session) PlanningContext
        +store_plan_async(session, plan) void
    }
    
    class ToolResultContextProvider {
        -ContextStorageManager storage
        +provide_context_async(session) ToolResults
        +store_result_async(session, result) void
    }
    
    %% Executor群（抽象メソッド明記）
    class BaseExecutor {
        <<abstract>>
        #IWorkflowContext context
        #ExecutionEnvironmentManager env_manager
        #MCPClientRegistry mcp_registry
        +execute_async()* ExecutorResult
        #get_context_value(key) Any
        #set_context_value(key, value) void
    }
    
    class UserResolverExecutor {
        -UserConfigClient config_client
        +execute_async() ExecutorResult
        -_fetch_user_config(email) UserConfig
        -_decrypt_api_key(encrypted_key) str
    }
    
    class ContentTransferExecutor {
        -GitLabClient gitlab_client
        +execute_async() ExecutorResult
        -_transfer_issue_to_mr(issue, mr) void
    }
    
    class EnvironmentSetupExecutor {
        -ExecutionEnvironmentManager env_manager
        +execute_async() ExecutorResult
        -_setup_docker_environment() Environment
    }
    
    %% AIAgent群（ConfigurableAgentに統一）
    class ConfigurableAgent {
        -AgentNodeConfig node_config
        -AIAgent agent
        -AgentSession session
        -IWorkflowContext context
        -List~Tool~ tools
        +invoke_async(context) AgentResult
        #get_chat_history() List~Message~
        #get_context(keys) Dict
        #store_result(output_keys, result) void
        #invoke_mcp_tool(tool_name, params) ToolResult
    }
    
    class AgentNodeConfig {
        +str node_id
        +str role
        +List~str~ input_keys
        +List~str~ output_keys
        +List~str~ tools
        +bool requires_environment
        +str prompt_id
    }
    
    %% 支援オブジェクト
    class ExecutionEnvironmentManager {
        -DockerClient docker
        -Dict~str,Container~ containers
        -ExecutionConfig config
        +create_environment(project_id) Environment
        +execute_command(cmd, env_id) CommandResult
        +cleanup(env_id) void
    }
    
    class MCPClientRegistry {
        -Dict~str,MCPClient~ clients
        -MCPClientFactory factory
        +get_client(name) MCPClient
        +register_client(name, client) void
        +list_clients() List~str~
    }
    
    class MCPClient {
        -Connection connection
        -List~Tool~ tools
        +invoke_tool(name, params) ToolResult
        +list_tools() List~Tool~
        +connect() void
        +disconnect() void
    }
    
    class GitLabClient {
        -HTTPClient http
        -str api_token
        -str base_url
        +get_mr(project_id, mr_iid) MR
        +post_comment(mr_id, comment) void
        +create_branch(project_id, branch_name) Branch
        +create_merge_request(project_id, params) MR
        +get_issue(project_id, issue_iid) Issue
    }
    
    class TodoManager {
        -ContextStorageManager storage
        -GitLabClient gitlab_client
        +create_todo_list(items) TodoList
        +update_todo_status(id, status) void
        +sync_to_gitlab(mr_id, todos) void
        +get_todos(task_uuid) List~Todo~
    }
    
    class ContextStorageManager {
        -PostgreSQLClient db
        -FileStorage file_storage
        +save_chat_history(session_id, messages) void
        +save_planning_history(session_id, plan) void
        +save_tool_result(session_id, result) void
        +load_context(session_id) Context
        +delete_context(session_id) void
    }
    
    class ProgressReporter {
        -GitLabClient gitlab_client
        -MessageFormatter formatter
        +report_task_start(mr_id, task_type) void
        +report_phase_complete(mr_id, phase, result) void
        +report_error(mr_id, error) void
        +report_task_complete(mr_id, summary) void
    }
    
    class UserConfigClient {
        -HTTPClient http
        -str api_url
        -str api_key
        +get_user_config(email) UserConfig
        +create_user_config(email, config) UserConfig
        +update_user_config(email, config) UserConfig
        +decrypt_api_key(encrypted_key) str
    }
    
    class TaskStatusManager {
        -ContextStorageManager storage
        +update_status(task_uuid, status) void
        +get_status(task_uuid) TaskStatus
        +mark_completed(task_uuid) void
        +mark_failed(task_uuid, error) void
    }
    
    %% Agent Providersとの統合
    class AgentFactory {
        -ChatClient chat_client
        -PostgreSqlChatHistoryProvider history_provider
        -List~AIContextProvider~ context_providers
        -AgentProviderConfig config
        -DefinitionLoader definition_loader
        +create_configurable_agent(node_config, session_id, user_id) ConfigurableAgent
        -_create_session(session_id) AgentSession
        -_get_prompt(prompt_id, workflow_def) str
        -_register_tools(tools_list) List~Tool~
    }
    
    class DefinitionLoader {
        -ContextStorageManager storage
        +load_workflow_definition(definition_id) WorkflowDefinition
        +get_preset_definitions() List~WorkflowDefinition~
        +validate_graph_definition(graph_def) bool
        +validate_agent_definition(agent_def, graph_def) bool
        +validate_prompt_definition(prompt_def, agent_def) bool
    }
    
    %% Middleware
    class TokenUsageMiddleware {
        -ContextStorageManager storage
        -MetricsCollector metrics
        +on_agent_invoked(agent, context) void
        +on_agent_completed(agent, result, context) void
        +record_token_usage(user_id, task_uuid, tokens) void
    }
    
    class ErrorHandlingMiddleware {
        -ContextStorageManager storage
        -GitLabClient gitlab_client
        -MetricsCollector metrics
        +on_error(error, context) ErrorAction
        +classify_error(error) ErrorCategory
        +should_retry(error_category) bool
        +notify_user(error, mr_id) void
        +update_task_status(task_uuid, error) void
        +record_error_log(error, context) void
    }
    
    %% プロンプト管理
    class PromptOverrideManager {
        -PostgreSQLClient db
        -Dict~str,str~ default_prompts
        +get_prompt(agent_name, user_id) str
        +set_prompt_override(user_id, agent_name, prompt) void
        +delete_prompt_override(user_id, agent_name) void
        +load_default_prompts() void
    }
    
    %% 関係性
    Consumer --> TaskHandler : 保持
    TaskHandler --> WorkflowExecutor : 保持
    TaskHandler --> GitLabClient : 保持
    TaskHandler --> TaskStrategyFactory : 保持
    TaskHandler --> TaskStatusManager : 保持
    
    WorkflowExecutor --> WorkflowFactory : 使用
    WorkflowExecutor --> ExecutionEnvironmentManager : 保持（共有）
    WorkflowExecutor --> ProgressReporter : 保持
    
    WorkflowFactory --> WorkflowBuilder : 使用して生成
    WorkflowFactory --> ExecutorFactory : 保持
    WorkflowFactory --> AgentFactory : 保持
    WorkflowFactory --> MCPClientFactory : 保持
    WorkflowFactory --> ContextStorageManager : 保持
    WorkflowFactory --> TodoManager : 保持
    WorkflowFactory --> TokenUsageMiddleware : 保持
    WorkflowFactory --> ErrorHandlingMiddleware : 保持
    WorkflowFactory --> DefinitionLoader : 保持
    
    WorkflowBuilder --> Workflow : 生成
    WorkflowBuilder --> ExecutorFactory : 使用
    WorkflowBuilder --> AgentFactory : 使用
    WorkflowBuilder --> TokenUsageMiddleware : 登録
    WorkflowBuilder --> ErrorHandlingMiddleware : 登録
    
    ExecutorFactory --> UserResolverExecutor : 生成
    ExecutorFactory --> ContentTransferExecutor : 生成
    ExecutorFactory --> EnvironmentSetupExecutor : 生成
    ExecutorFactory --> UserConfigClient : 使用
    ExecutorFactory --> GitLabClient : 使用
    ExecutorFactory --> ExecutionEnvironmentManager : 使用
    
    MCPClientFactory --> MCPClient : 生成
    MCPClientFactory --> MCPClientRegistry : 登録
    
    Workflow --> IWorkflowContext : 保持（全ステップで共有）
    Workflow "1" *-- "n" BaseExecutor : 複数保持
    Workflow "1" *-- "n" ConfigurableAgent : 複数保持
    Workflow "1" *-- "n" TokenUsageMiddleware : 複数保持
    Workflow "1" *-- "n" ErrorHandlingMiddleware : 複数保持
    
    ConfigurableAgent --> AgentNodeConfig : 保持
    ConfigurableAgent --> AgentSession : 保持
    AgentSession --> PostgreSqlChatHistoryProvider : 使用
    AgentSession --> PlanningContextProvider : 使用
    AgentSession --> ToolResultContextProvider : 使用
    
    PostgreSqlChatHistoryProvider --> ContextStorageManager : 使用
    PlanningContextProvider --> ContextStorageManager : 使用
    ToolResultContextProvider --> ContextStorageManager : 使用
    
    BaseExecutor --> IWorkflowContext : 参照
    BaseExecutor --> ExecutionEnvironmentManager : 参照
    BaseExecutor --> MCPClientRegistry : 参照
    
    ConfigurableAgent --> IWorkflowContext : 参照
    ConfigurableAgent --> MCPClientRegistry : 参照
    
    UserResolverExecutor --|> BaseExecutor : 継承
    ContentTransferExecutor --|> BaseExecutor : 継承
    EnvironmentSetupExecutor --|> BaseExecutor : 継承
    
    MCPClientRegistry --> MCPClient : 複数保持
    
    IWorkflowContext --> ContextStorageManager : 使用
    
    TodoManager --> ContextStorageManager : 使用
    TodoManager --> GitLabClient : 使用
    
    AgentFactory --> ConfigurableAgent : 生成
    AgentFactory --> DefinitionLoader : 使用
    
    DefinitionLoader --> ContextStorageManager : 使用
    
    TokenUsageMiddleware --> ContextStorageManager : 使用
    
    ErrorHandlingMiddleware --> ContextStorageManager : 使用
    ErrorHandlingMiddleware --> GitLabClient : 使用
    
    UserResolverExecutor --> UserConfigClient : 使用
    
    TaskStatusManager --> ContextStorageManager : 使用
    
    TaskStrategyFactory --> GitLabClient : 使用
```

#### 5.5.3 オブジェクトライフサイクル管理

##### Consumer層（アプリケーション起動時に1回初期化）

**初期化順序**:
1. `Consumer`の起動
   - RabbitMQ接続の確立（永続接続）
   - `TaskHandler`のインスタンス化

2. `TaskHandler`の初期化
   - `WorkflowExecutor`のインスタンス化
   - `GitLabClient`のインスタンス化（API Token設定）
   - `TaskStrategyFactory`のインスタンス化
   - `TaskStatusManager`のインスタンス化

3. `WorkflowExecutor`の初期化（タスク処理間で再利用）
   - `WorkflowFactory`のインスタンス化
   - `ExecutionEnvironmentManager`のインスタンス化（Docker Client初期化）
   - `ProgressReporter`のインスタンス化

4. `WorkflowFactory`の初期化
   - `ExecutorFactory`のインスタンス化（UserConfigClient、GitLabClient、ExecutionEnvironmentManagerを使用）
   - `AgentFactory`のインスタンス化
   - `MCPClientFactory`のインスタンス化
   - `ContextStorageManager`のインスタンス化（PostgreSQL接続プール）
   - `PostgreSqlChatHistoryProvider`のインスタンス化（ContextStorageManagerを使用）
   - `PlanningContextProvider`のインスタンス化（ContextStorageManagerを使用）
   - `ToolResultContextProvider`のインスタンス化（ContextStorageManagerを使用）
   - `TodoManager`のインスタンス化
   - `TokenUsageMiddleware`のインスタンス化（ContextStorageManagerを使用）
   - `DefinitionLoader`のインスタンス化（workflow_definitionsテーブルとPROMPTS.mdからデフォルト定義をロード）
   - `WorkflowBuilder`のインスタンス化

**ライフサイクル**:
- Consumer起動から終了まで存続
- 各オブジェクトは複数タスク処理で再利用される
- RabbitMQ接続、PostgreSQL接続プールは永続化

##### Workflow層（タスクごとに生成）

**生成タイミング**: タスクがRabbitMQからデキューされた時

**初期化順序**:
1. `TaskHandler`が`TaskStrategyFactory`でタスク戦略を決定（Issue→MR変換判定等）
2. 必要に応じてIssue→MR変換を`ContentTransferExecutor`が実行
3. `WorkflowExecutor.execute_workflow(user_id, task_context)`でワークフロー実行開始
4. `WorkflowFactory`がユーザーのワークフロー定義に基づいてWorkflowを生成
   - `DefinitionLoader`でユーザーの`user_workflow_settings`から選択中の`workflow_definition_id`を取得
   - `workflow_definitions`テーブルから3つの定義（グラフ定義・エージェント定義・プロンプト定義）を1セットのJSONとして取得
   - グラフ定義の`requires_environment: true`のノード数分のDocker環境を事前準備
   - `create_workflow_from_definition(user_id, task_context)`でWorkflowを生成
5. `WorkflowBuilder`が`Workflow`オブジェクトを構築
   - `IWorkflowContext`を生成（タスク専用、セッションID付き）
   - `ExecutorFactory`から必要な`Executor`を生成して追加
   - グラフ定義に従って各ノードの`ConfigurableAgent`を生成して追加（エージェント定義とプロンプト定義を参照）
   - `TokenUsageMiddleware`を登録（Workflow実行時に自動的にトークン使用量を記録）
6. `ExecutorFactory`が各`Executor`を生成
   - `UserResolverExecutor`: UserConfigClientを使用してユーザー設定取得
   - `ContentTransferExecutor`: GitLabClientを使用してIssue→MR転記
   - `EnvironmentSetupExecutor`: ExecutionEnvironmentManagerを使用してDocker環境構築
7. `AgentFactory`が各`ConfigurableAgent`を生成
   - ワークフロー定義のプロンプト定義JSON（`prompt_definition`フィールド）から対応するプロンプトを取得
   - エージェント定義JSON（`agent_definition`フィールド）から各ノードの設定（AgentNodeConfig）を構築
   - `AgentSession`を生成（セッションID、Provider登録）
   - `PostgreSqlChatHistoryProvider`、`PlanningContextProvider`、`ToolResultContextProvider`を`AgentSession`に登録
   - `ChatClient.as_ai_agent()`でAgent Providersから`AIAgent`を取得（カスタムプロンプトを`instructions`に設定）
   - ツール登録（`ChatClientAgentOptions.tools`）
   - `IWorkflowContext`と`AgentSession`への参照を設定
8. 各`Executor`のインスタンス化
   - `IWorkflowContext`への参照を設定
   - 共有リソース（`ExecutionEnvironmentManager`、`MCPClientRegistry`）への参照を設定

**実行フロー**:
1. `Workflow.execute()`でワークフロー開始
2. Graph-based Workflowsに従ってステップを順次実行
3. 各ステップ（`Executor`または`AIAgent`）が`IWorkflowContext`でデータを共有
4. `IWorkflowContext.queue_state_update_async()`で状態をPostgreSQLに永続化
5. `ProgressReporter`が各フェーズ完了時にGitLabにコメント投稿

**破棄タイミング**: タスク処理完了またはエラー時

**クリーンアップ**:
- `ExecutionEnvironmentManager.cleanup(env_id)`でDocker環境を破棄
- `IWorkflowContext`のメモリ解放
- `Workflow`オブジェクトのガベージコレクション

##### 共有リソース（複数タスク処理で再利用）

**ExecutionEnvironmentManager**:
- Consumer起動時に1回初期化
- 複数タスクで同時使用可能（内部でロック管理）
- タスクごとに専用のDocker環境を作成（`create_environment()`）
- タスク完了時に環境を破棄（`cleanup()`）
- Consumer終了時にすべてのDocker環境をクリーンアップ

**MCPClientRegistry**:
- Consumer起動時に1回初期化
- 必要なMCPサーバー（text-editor、command-executor等）へのクライアントを登録
- 複数タスクで同時使用可能（内部で接続プール管理）
- Consumer終了時にすべての接続をクローズ

**ContextStorageManager**:
- Consumer起動時に1回初期化
- PostgreSQL接続プール（asyncpg）を使用
- 複数タスクで同時使用可能（トランザクション分離）
- タスクごとに異なるセッションIDでデータを分離

**GitLabClient**:
- Consumer起動時に1回初期化
- HTTPクライアントは接続プールを使用
- レート制限管理（最大100 req/min）
- 複数タスクで同時使用可能

**TodoManager**:
- Consumer起動時に1回初期化
- `ContextStorageManager`と`GitLabClient`を使用
- 複数タスクで同時使用可能

**TokenUsageMiddleware**:
- Consumer起動時に1回初期化
- すべてのWorkflowに登録され、AIAgent呼び出しを自動的にインターセプト
- AIAgentのレスポンスからトークン情報（`prompt_tokens`、`completion_tokens`、`total_tokens`）を取得
- `ContextStorageManager`を使用して`token_usage`テーブルに記録
- OpenTelemetryと統合してメトリクスとして送信
- 複数タスクで同時使用可能（タスクごとに異なるuser_idとtask_uuidで記録）

**ErrorHandlingMiddleware**:
- Consumer起動時に1回初期化
- すべてのWorkflowに登録され、AIAgentおよびExecutor呼び出し時のエラーを統一的にハンドリング
- エラー発生時に自動的にインターセプトし、エラーカテゴリを分類
- エラーカテゴリ:
  - `transient`: 一時的な障害（ネットワークタイムアウト、レート制限、サービス不可等）→ リトライ適用
  - `configuration`: 設定エラー（環境変数の欠落、無効な認証情報、誤った設定）→ ユーザーアクション必要
  - `implementation`: 実装バグ（未処理の例外、予期しないデータ）→ 開発者アクション必要
  - `resource`: リソース不足（ディスク空間、メモリ、APIクォータ）→ 運用担当者アクション必要
- リトライポリシー適用:
  - `transient`エラー: 指数バックオフで最大3回リトライ（基本遅延: 5秒）
  - その他のエラー: リトライせず、ユーザーに通知して処理を停止
- GitLab通知:
  - エラー通知コメントを関連するIssue/MRに自動投稿
  - エラー種別、発生箇所、エラー内容、ユーザーアクション（該当する場合）を含む
- データベース更新:
  - タスクステータスを"failed"に更新
  - エラーメッセージとスタックトレースを`tasks`テーブルに記録
- コンテキスト保存:
  - 完全なエラー詳細を`ContextStorageManager`を通じて永続化
  - 事後分析とデバッグ用にエラーログを保持
- OpenTelemetryと統合:
  - エラー発生時に分散トレースにエラー情報を記録
  - エラー率メトリクスを収集
- 複数タスクで同時使用可能（タスクごとに独立したエラーハンドリング）

**DefinitionLoader**:
- Consumer起動時に1回初期化
- `workflow_definitions`テーブルからシステムプリセット（is_preset=true）の定義をプリロードしてキャッシュ
- ユーザーのワークフロー定義取得時は`user_workflow_settings`→`workflow_definitions`の順でDBから取得
- 3つの定義（グラフ定義・エージェント定義・プロンプト定義）を1レコード・1セットとして返す
- 各定義はJSON形式でDBに保存され、JSONB型で高速に参照可能
- 複数タスクで同時使用可能（読み取り専用操作が中心）

#### 5.5.4 オブジェクト間の依存関係とデータフロー

```mermaid
sequenceDiagram
    participant C as Consumer
    participant TH as TaskHandler
    participant TSF as TaskStrategyFactory
    participant WE as WorkflowExecutor
    participant WF as WorkflowFactory
    participant DL as DefinitionLoader
    participant WB as WorkflowBuilder
    participant W as Workflow
    participant IWC as IWorkflowContext
    participant CA as ConfigurableAgent
    participant TUM as TokenUsageMiddleware
    participant AS as AgentSession
    participant PCHP as PostgreSqlChatHistoryProvider
    participant PCP as PlanningContextProvider
    participant TRCP as ToolResultContextProvider
    participant LLM as LLM
    participant TM as TodoManager
    participant CSM as ContextStorageManager
    participant GL as GitLabClient
    participant PR as ProgressReporter
    participant MCPR as MCPClientRegistry
    participant MCPC as MCPClient
    participant EEM as ExecutionEnvironmentManager
    
    Note over C,TH: 1. タスク開始フロー
    C->>TH: タスク受信
    TH->>TSF: create_strategy(task)
    TSF-->>TH: タスク戦略
    TH->>WE: execute_workflow(user_id, task_context)
    WE->>WF: create_workflow_from_definition(user_id, task_context)
    WF->>DL: load_workflow_definition(definition_id)
    DL->>CSM: workflow_definitionsテーブルから1セット取得(JSON)
    CSM-->>DL: {graph_definition, agent_definition, prompt_definition}
    DL-->>WF: WorkflowDefinition(1セット)
    WF->>WB: Workflowビルド開始（グラフ定義に従う）
    WB->>WB: ExecutorFactory.create_*_executor(context)
    WB->>WB: AgentFactory.create_configurable_agent(node_config, session_id, user_id)
    WB->>W: Workflowオブジェクト生成
    W->>IWC: コンテキスト初期化
    IWC->>CSM: コンテキスト初期化
    
    Note over W,PR: 2. プランニングフェーズ（ConfigurableAgent role=planning）
    W->>TUM: on_agent_invoked()
    W->>CA: invoke_async(context)
    CA->>AS: 履歴とコンテキスト取得
    AS->>PCHP: provide_history_async()
    PCHP-->>AS: 会話履歴
    AS->>PCP: provide_context_async()
    PCP-->>AS: プランニングコンテキスト
    CA->>LLM: プロンプト送信（履歴+コンテキスト）
    LLM-->>CA: プラン生成結果
    CA->>TUM: on_agent_completed(tokens)
    TUM->>CSM: トークン使用量記録(user_id, task_uuid, tokens)
    CA->>TM: create_todo_list()
    CA->>PCP: store_plan_async()
    PCP->>CSM: save_planning_history()
    CA->>PCHP: store_message_async()
    PCHP->>CSM: 会話履歴保存
    CA->>IWC: queue_state_update_async()
    CA->>GL: プラン投稿
    CA->>PR: report_phase_complete()
    
    Note over W,PR: 3. 実行フェーズ（ConfigurableAgent role=execution）
    W->>TUM: on_agent_invoked()
    W->>CA: invoke_async(context)
    CA->>AS: 履歴とコンテキスト取得
    AS->>PCHP: provide_history_async()
    PCHP-->>AS: 会話履歴
    AS->>PCP: provide_context_async()
    PCP-->>AS: プラン
    AS->>TRCP: provide_context_async()
    TRCP-->>AS: ツール実行結果
    CA->>MCPR: get_client("text-editor")
    MCPR-->>CA: MCPClient
    CA->>MCPC: invoke_tool("create_file", params)
    MCPC-->>CA: 実行結果
    CA->>TUM: on_agent_completed(tokens)
    TUM->>CSM: トークン使用量記録(user_id, task_uuid, tokens)
    CA->>TRCP: store_result_async()
    TRCP->>CSM: save_tool_result()
    CA->>EEM: execute_command("git add ...")
    CA->>PCHP: store_message_async()
    PCHP->>CSM: 会話履歴保存
    CA->>IWC: queue_state_update_async()
    CA->>TM: update_todo_status("completed")
    CA->>GL: 進捗投稿
    CA->>PR: report_phase_complete()
    
    Note over W,PR: 4. レビューフェーズ（ConfigurableAgent role=review）
    W->>TUM: on_agent_invoked()
    W->>CA: invoke_async(context)
    CA->>AS: 履歴とコンテキスト取得
    AS->>PCHP: provide_history_async()
    PCHP-->>AS: 会話履歴
    AS->>TRCP: provide_context_async()
    TRCP-->>AS: 実行結果
    CA->>GL: get_mr_diff()
    GL-->>CA: MR差分
    CA->>LLM: レビュー実行（履歴+コンテキスト）
    LLM-->>CA: レビュー結果
    CA->>TUM: on_agent_completed(tokens)
    TUM->>CSM: トークン使用量記録(user_id, task_uuid, tokens)
    CA->>GL: post_comment()
    CA->>PCHP: store_message_async()
    PCHP->>CSM: 会話履歴保存
    CA->>IWC: queue_state_update_async()
    CA->>PR: report_phase_complete()
    
    Note over W,PR: 5. エラーハンドリング
    alt エラー発生
        CA->>TUM: on_agent_completed(tokens, error)
        TUM->>CSM: トークン使用量記録
        CA->>PCHP: store_message_async(error)
        CA->>IWC: queue_state_update_async(error)
        BEA->>PR: report_error()
        BEA->>GL: post_comment(error)
        BEA->>EEM: cleanup()
        W->>W: 中断またはリトライ
    end
```

#### 5.5.5 並行処理とスレッドセーフティ

**複数Consumer**:
- 複数のConsumerプロセスを並行起動可能
- 各ConsumerはRabbitMQから独立してタスクをデキュー
- 共有リソースはプロセス間で共有されない（各ConsumerがExecutionEnvironmentManager等を独自に保持）

**単一Consumer内の並行処理**:
- Workflowの実行は直列（1タスクずつ処理）
- Agent FrameworkのGraph-based Workflowsは内部で非同期実行をサポート
- 共有リソース（ExecutionEnvironmentManager、ContextStorageManager等）はスレッドセーフ

**リソースロック**:
- `ExecutionEnvironmentManager`: Docker環境作成時にロック（環境ID単位）
- `ContextStorageManager`: PostgreSQLのトランザクション分離（セッションID単位）
- `MCPClientRegistry`: 接続プール管理（接続単位でロック）

#### 5.5.6 IWorkflowContextデータクラス定義

IWorkflowContextでステップ間のデータ共有に使用する具象クラスを定義する。すべてのデータクラスはPydantic BaseModelを継承し、JSON serializableとする。

**TaskContext（タスク共通情報）**:
- タスクUUID（文字列）
- タスク種別（"code_generation" | "bug_fix" | "documentation" | "test_creation"）
- ユーザーメールアドレス（文字列）
- リポジトリ名（文字列）
- GitLabプロジェクトID（文字列）
- MR IID（整数）
- MR URL（文字列）
- ソースブランチ名（文字列）
- ターゲットブランチ名（文字列）
- タスク作成日時（日時型）

**ClassificationResult（タスク分類結果）**:
- タスク種別（"code_generation" | "bug_fix" | "documentation" | "test_creation"）
- 分類信頼度（0.0～1.0の浮動小数点数）
- 分類理由（文字列）
- 関連ファイルパスのリスト（文字列配列）
- 仕様書の存在フラグ（真偽値）
- 仕様書パス（文字列、オプショナル）

**ActionItem（アクション項目）**:
- アクション一意ID（文字列、例: "action_1"）
- アクション説明（文字列）
- 実行エージェント種別（文字列）
- 使用ツール名（文字列、オプショナル）
- 対象ファイルパス（文字列、オプショナル）
- 受入基準（文字列）
- 依存するアクションIDのリスト（文字列配列、デフォルト空配列）
- 見積り複雑度（"low" | "medium" | "high"）

**PlanResult（プランニング結果）**:
- プランUUID（文字列）
- タスク要約（文字列）
- 作成予定ファイルのリスト（文字列配列）
- 修正予定ファイルのリスト（文字列配列）
- アクション系列（ActionItemオブジェクトの配列）
- 依存モジュール/ライブラリのリスト（文字列配列）
- 見積り複雑度（"low" | "medium" | "high"）
- プラン作成日時（日時型）

**ReflectionIssue（リフレクション問題点）**:
- 深刻度（"critical" | "major" | "minor"）
- カテゴリ（"consistency" | "completeness" | "feasibility" | "clarity"）
- 問題説明（文字列）
- 改善提案（文字列）
- 影響を受けるアクションIDのリスト（文字列配列、デフォルト空配列）

**ReflectionResult（リフレクション結果）**:
- リフレクション結果（"approved" | "needs_revision"）
- 全体評価コメント（文字列）
- 問題点リスト（ReflectionIssueオブジェクトの配列）
- アクション（"proceed" | "revise_plan"）
- リフレクション実行回数（整数）
- リフレクション実行日時（日時型）

**FileModification（ファイル変更情報）**:
- ファイルパス（文字列）
- 操作種別（"create" | "modify" | "delete"）
- 追加行数（整数）
- 削除行数（整数）
- 変更内容要約（文字列）

**TestResult（テスト結果）**:
- テスト名（文字列）
- ステータス（"passed" | "failed" | "skipped"）
- 実行時間（秒、浮動小数点数）
- エラーメッセージ（文字列、オプショナル）
- スタックトレース（文字列、オプショナル）

**ExecutionResult（実行結果）**:
- 実行成功フラグ（真偽値）
- 変更ファイル情報のリスト（FileModificationオブジェクトの配列）
- テスト結果（TestResultオブジェクトの配列、オプショナル、該当する場合のみ）
- カバレッジ率（0.0～1.0の浮動小数点数、オプショナル）
- エラーメッセージ（文字列、オプショナル）
- 実行時間（秒、浮動小数点数）
- 実行完了日時（日時型）

**ReviewComment（レビューコメント）**:
- ファイルパス（文字列）
- 行番号（整数、オプショナル）
- 深刻度（"critical" | "major" | "minor" | "suggestion"）
- カテゴリ（"correctness" | "security" | "performance" | "maintainability" | "test_coverage" | "accuracy" | "completeness" | "structure" | "readability" | "broken_link"）
- コメント内容（文字列）

**ReviewResult（レビュー結果）**:
- 承認ステータス（"approved" | "needs_changes" | "rejected"）
- 全体評価コメント（文字列）
- レビューコメントリスト（ReviewCommentオブジェクトの配列）
- クリティカル問題数（整数）
- 重大問題数（整数）
- 軽微問題数（整数）
- レビュー実行日時（日時型）

**IWorkflowContextヘルパーメソッド**:

IWorkflowContextに型安全なヘルパーメソッドを追加することを推奨：
- タスクコンテキスト取得メソッド（戻り値: TaskContextまたはNone）
- タスクコンテキスト設定メソッド（引数: TaskContext）
- 分類結果取得メソッド（戻り値: ClassificationResultまたはNone）
- 分類結果設定メソッド（引数: ClassificationResult）
- プラン取得メソッド（戻り値: PlanResultまたはNone）
- プラン設定メソッド（引数: PlanResult）
- リフレクション結果取得メソッド（戻り値: ReflectionResultまたはNone）
- リフレクション結果設定メソッド（引数: ReflectionResult）
- 実行結果取得メソッド（戻り値: ExecutionResultまたはNone）
- 実行結果設定メソッド（引数: ExecutionResult）
- レビュー結果取得メソッド（戻り値: ReviewResultまたはNone）
- レビュー結果設定メソッド（引数: ReviewResult）

**利用フロー**:

Planning Agentでのプラン保存処理：
1. PlanResultオブジェクトを生成する
   - プランUUIDを生成
   - タスク要約を設定（例: "新規API実装"）
   - 作成予定ファイルリストを設定（例: ["src/api/users.py"]）
   - 修正予定ファイルリストを設定（例: ["src/api/__init__.py"]）
   - ActionItemオブジェクトの配列を設定（例: User APIエンドポイント実装、複雑度medium）
   - 依存ライブラリリストを設定（例: ["fastapi", "sqlalchemy"]）
   - 見積り複雑度を設定（例: "medium"）
   - 現在日時を設定
2. コンテキストのプラン設定メソッドを呼び出してPlanResultを保存する

Execution Agentでのプラン取得処理：
1. コンテキストのプラン取得メソッドを呼び出す
2. プランが存在する場合、アクション配列を順次処理する
3. 各アクションを実行する

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

（生成されたコードの詳細をここに表示）

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

**重要**: GitLab PATはシステム全体で1つのbot用Personal Access Tokenを使用する。環境変数`GITLAB_PAT`で設定する。ユーザーごとに管理するのはOpenAI API keyである。

### 7.2 GitlabClientクラスの責務

- システム全体で共有するbot用Personal Access Tokenを使用してGitLab REST APIを呼び出す
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
- **AgentSession**: 会話状態を管理するコンテナー（StateBagを含む）
  - エージェントの実行全体で使用される状態を保持
  - セッションのシリアル化・復元が可能
  - サービス管理の履歴との統合が可能

#### **Middleware System**
- リクエスト/レスポンス処理のインターセプト
- 統一的なエラーハンドリング
- ログ記録とテレメトリ統合

#### **OpenTelemetry統合**
- 分散トレーシング
- パフォーマンス監視
- メトリクス収集

本システムでは、Agent Frameworkの標準機能に加えて以下のカスタム実装を追加する：

### 8.2 Agent Framework標準Providerのカスタム実装

Agent Frameworkが提供する`ChatHistoryProvider`と`AIContextProvider`を継承したカスタム実装を行う。

#### 8.2.1 PostgreSqlChatHistoryProvider（会話履歴の永続化）

**基底クラス**: `Microsoft.Agents.AI.ChatHistoryProvider`

**責務**:
- LLMの会話履歴をPostgreSQLに永続化する
- タスクUUID単位で会話履歴を読み込み・保存する
- トークン数を記録し管理する

**主要メソッド**:

- **`provide_chat_history_async(context, cancellation_token)`**
  - Agent Frameworkがエージェント実行前に呼び出すメソッド
  - `context`からセッション情報を取得し、タスクUUIDを特定する
  - PostgreSQLの`context_messages`テーブルから当該タスクの会話履歴を時系列順に取得する
  - 取得したメッセージをAgent Frameworkの`ChatMessage`オブジェクトのリストとして返す
  - エージェントはこの履歴を含めてLLMに送信する

- **`store_chat_history_async(context, cancellation_token)`**
  - Agent Frameworkがエージェント実行後に呼び出すメソッド
  - `context`から新しい会話メッセージ（ユーザー入力とアシスタント応答）を取得する
  - 各メッセージをPostgreSQLの`context_messages`テーブルに保存する
  - トークン数を計算し、メッセージと共に保存する
  - セッション状態にメッセージ総数とトークン総数を更新する

**セッション状態管理**:

- **`ProviderSessionState<ChatHistorySessionState>`クラス**を使用して型安全にセッション状態を管理する
- **`ChatHistorySessionState`**には以下の情報を保持する：
  - `task_uuid`: タスクUUID（文字列型）
  - `message_count`: メッセージ総数（整数型）
  - `total_tokens`: トークン総数（整数型）
- Agent FrameworkのAgentSession内に自動的にシリアル化・デシリアル化される
- 状態キーは`"PostgreSqlChatHistory"`として他のProviderと衝突しないようにする

#### 8.2.2 PlanningContextProvider（プランニング履歴管理）

**基底クラス**: `Microsoft.Agents.AI.AIContextProvider`

**責務**:
- プランニング履歴を永続化し復元する
- 過去の計画・実行・検証結果をコンテキストとしてエージェントに提供する

**主要メソッド**:

- **`provide_ai_context_async(context, cancellation_token)`**
  - Agent Frameworkがエージェント実行前に呼び出すメソッド
  - `context`からタスクUUIDを取得する
  - PostgreSQLの`context_planning_history`テーブルから当該タスクの過去のプランニング履歴を取得する
  - 取得したプランニング履歴を人間が読める形式のテキストに整形する
  - Agent Frameworkの`AIContext`オブジェクトとして返す（追加メッセージまたは追加指示として）
  - エージェントはこのコンテキストを参照してプランニングを行う

- **`store_ai_context_async(context, cancellation_token)`**
  - Agent Frameworkがエージェント実行後に呼び出すメソッド
  - `context`からエージェントの応答メッセージを解析し、プランニング結果を抽出する
  - プランニングフェーズ（planning/execution/reflection）を判定する
  - 計画データ、アクションID、実行結果をJSONB形式で構造化する
  - PostgreSQLの`context_planning_history`テーブルに保存する

#### 8.2.3 ToolResultContextProvider（ツール実行結果管理）

**基底クラス**: `Microsoft.Agents.AI.AIContextProvider`

**責務**:
- ツール実行結果（ファイル読み込み、コマンド出力）を保存し復元する
- ツール実行結果はファイル内容を参照することが多く巨大化する傾向があるため、ファイルベースストレージに永続化する
- メタデータ（ツール名、実行日時、サイズ等）のみをPostgreSQLに保存し、実際の結果データはファイルに保存する

**主要メソッド**:

- **`provide_ai_context_async(context, cancellation_token)`**
  - Agent Frameworkがエージェント実行前に呼び出すメソッド
  - `context`からタスクUUIDを取得する
  - PostgreSQLの`context_tool_results_metadata`テーブルから当該タスクのツール実行メタデータを取得する
  - ファイルストレージ（`tool_results/{task_uuid}/`）から実際のツール実行結果を読み込む
  - ファイル読み込み結果とコマンド実行結果をそれぞれ時系列でソートする
  - 直近のツール実行結果（例: 最新10件）を要約形式で抽出する
  - 大きなファイル内容は省略し、サマリー情報のみを含める
  - Agent Frameworkの`AIContext`オブジェクトとして返す（追加メッセージとして）
  - エージェントはこの情報を参照して次のアクションを決定する

- **`store_ai_context_async(context, cancellation_token)`**
  - Agent Frameworkがエージェント実行後に呼び出すメソッド
  - `context`からツール呼び出し情報を取得する
  - ツール実行結果をJSON形式でファイルに保存:
    - ファイル読み込みツールの場合、ファイルパス、内容（全体）、MIMEタイプをJSON形式で保存する
    - コマンド実行ツールの場合、コマンド、終了コード、標準出力、標準エラー出力をJSON形式で保存する
    - MCPツール呼び出しの場合、ツール名、引数、結果（全体）をJSON形式で保存する
  - タイムスタンプ付きのフ ァイル名で`tool_results/{task_uuid}/{timestamp}_{tool_name}.json`に保存する
  - PostgreSQLの`context_tool_results_metadata`テーブルにメタデータを保存:
    - `tool_name`, `file_path`, `file_size`, `created_at`
  - `metadata.json`にツール実行統計情報を更新する（ファイル数、総サイズ、最終更新日時）

#### 8.2.4 データベーススキーマ設計

**PostgreSqlChatHistoryProviderが使用するテーブル**:

**context_messagesテーブル**: LLM会話履歴を保存する

| カラム | 型 | 説明 |
|-------|------|------|
| id | SERIAL PK | メッセージID |
| task_uuid | TEXT NOT NULL | タスクUUID |
| seq | INTEGER NOT NULL | シーケンス番号 |
| role | TEXT NOT NULL | ロール（system/user/assistant） |
| content | TEXT NOT NULL | メッセージ内容 |
| tokens | INTEGER | トークン数 |
| created_at | TIMESTAMP | 作成日時 |

**context_planning_historyテーブル**: プランニング履歴を保存する

| カラム | 型 | 説明 |
|-------|------|------|
| id | SERIAL PK | 履歴ID |
| task_uuid | TEXT NOT NULL | タスクUUID |
| phase | TEXT NOT NULL | フェーズ（planning/execution/reflection） |
| plan | JSONB | 計画データ |
| action_id | TEXT | アクションID |
| result | TEXT | 実行結果 |
| created_at | TIMESTAMP | 作成日時 |

**context_metadataテーブル**: タスクメタデータを保存する

| カラム | 型 | 説明 |
|-------|------|------|
| task_uuid | TEXT PK | タスクUUID |
| task_type | TEXT NOT NULL | タスク種別 |
| task_identifier | TEXT NOT NULL | GitLab Issue/MR識別子 |
| repository | TEXT NOT NULL | リポジトリ名 |
| user_email | TEXT NOT NULL | ユーザーメールアドレス |
| created_at | TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | 更新日時 |

**PlanningContextProviderが使用するテーブル**:

同上の`context_planning_history`テーブルと`context_metadata`テーブルを使用

#### 8.2.5 ファイルベースストレージ設計（ToolResultContextProvider）

**ディレクトリ構造**:
```
tool_results/
├── {task_uuid}/
│   ├── file_reads/              # ファイル読み込み結果
│   │   └── {timestamp}_{path}.json
│   ├── command_outputs/         # コマンド実行結果
│   │   └── {timestamp}_{command}.json
│   ├── mcp_tool_calls/          # MCPツール呼び出し履歴
│   │   └── {timestamp}_tool.json
│   └── metadata.json            # ツール実行メタデータ
```

**metadata.jsonのフィールド**:

- `task_uuid`: タスクUUID（文字列）
- `total_file_reads`: ファイル読み込み総数（整数）
- `total_command_executions`: コマンド実行総数（整数）
- `total_mcp_calls`: MCPツール呼び出し総数（整数）
- `started_at`: 開始日時（ISO 8601形式文字列）
- `last_updated_at`: 最終更新日時（ISO 8601形式文字列）

**ファイル読み込み結果（file_reads/*.json）のフィールド**:

- `timestamp`: 実行日時（ISO 8601形式文字列）
- `tool`: 使用ツール名（例: "text_editor"）
- `command`: コマンド種別（例: "view"）
- `path`: 対象ファイルパス（文字列）
- `content_preview`: 内容プレビュー（先頭500文字程度）
- `content_length`: コンテンツ全体の長さ（バイト数、整数）
- `mime_type`: MIMEタイプ（例: "text/plain", "application/json"）

**コマンド実行結果（command_outputs/*.json）のフィールド**:

- `timestamp`: 実行日時（ISO 8601形式文字列）
- `tool`: 使用ツール名（例: "command-executor"）
- `command`: 実行コマンド（文字列）
- `exit_code`: 終了コード（整数）
- `stdout`: 標準出力（文字列）
- `stderr`: 標準エラー出力（文字列）
- `duration_ms`: 実行時間（ミリ秒、整数）

**MCPツール呼び出し履歴（mcp_tool_calls/*.json）のフィールド**:

- `timestamp`: 実行日時（ISO 8601形式文字列）
- `tool_name`: MCPツール名（文字列）
- `arguments`: ツールに渡した引数（JSONB）
- `result`: ツール実行結果（JSONB）
- `success`: 成功フラグ（真偽値）
- `error_message`: エラーメッセージ（文字列、失敗時のみ）

**ファイル保持期限**: 設定で指定（デフォルト30日後に自動削除）

#### 8.2.6 エージェント設定への統合

**AIAgentへのProvider登録手順**:

1. **カスタムProviderのインスタンス化**
   - `PostgreSqlChatHistoryProvider`をPostgreSQLデータベース接続情報と共にインスタンス化する
   - `PlanningContextProvider`をPostgreSQLデータベース接続情報と共にインスタンス化する
   - `ToolResultContextProvider`をファイルストレージパスと共にインスタンス化する

2. **エージェント作成時の設定**
   - Agent FrameworkのChatClientから`as_ai_agent()`メソッドを呼び出す
   - `ChatClientAgentOptions`を使用して以下を設定する：
     - `name`: エージェント名（例: "CodingAgent"）
     - `chat_options.instructions`: システムプロンプト（英語）
     - `chat_history_provider`: `PostgreSqlChatHistoryProvider`インスタンスを指定
     - `ai_context_providers`: リスト形式で`PlanningContextProvider`と`ToolResultContextProvider`を指定
   - 設定完了後、`AIAgent`オブジェクトが返される

3. **セッション作成**
   - エージェントの`create_session_async()`メソッドを呼び出してセッションを作成する
   - Agent FrameworkがChatHistoryProviderとAIContextProvidersを自動的に初期化する
   - セッション内にProviderSessionStateが自動的に格納される

4. **セッションの永続化**
   - エージェントの`serialize_session(session)`メソッドを呼び出す
   - セッション全体（状態、履歴ID、メタデータ）がJSON形式でシリアル化される
   - シリアル化されたJSONをPostgreSQLのtasksテーブルのmetadataカラム（JSONB型）に保存する
   - タスク一時停止や再起動時に使用する

5. **セッションの復元**
   - 保存されたシリアル化JSONを取得する
   - エージェントの`deserialize_session_async(serialized)`メソッドを呼び出す
   - Agent Frameworkが各Providerの状態を復元する
   - 復元されたセッションで処理を継続できる

### 8.3 会話履歴管理

- **システムプロンプト**: タスク開始時に設定（英語）
- **ユーザーメッセージ**: Issue/MR内容、コメント
- **アシスタント応答**: LLMからの応答
- **ツール呼び出し**: function_call とその結果

### 8.4 Execution State

タスクデータベース (PostgreSQL) で管理：

#### tasks テーブル

| カラム | 型 | 制約 | 説明 |
|-------|------|------|------|
| uuid | TEXT | PK | タスクUUID |
| task_type | TEXT | NOT NULL | タスク種別 |
| task_identifier | TEXT | NOT NULL | GitLab Issue/MR識別子 |
| repository | TEXT | NOT NULL | リポジトリ名 |
| user_email | TEXT | NOT NULL | ユーザーメールアドレス |
| status | TEXT | NOT NULL | 状態（running/completed/paused/failed） |
| created_at | TIMESTAMP | NOT NULL | 作成日時 |
| updated_at | TIMESTAMP | | 更新日時 |
| completed_at | TIMESTAMP | | 完了日時 |
| total_messages | INTEGER | DEFAULT 0 | 総メッセージ数 |
| total_summaries | INTEGER | DEFAULT 0 | 総要約数 |
| total_tool_calls | INTEGER | DEFAULT 0 | 総ツール呼び出し数 |
| final_token_count | INTEGER | | 最終トークン数 |
| error_message | TEXT | | エラーメッセージ |
| metadata | JSONB | | メタデータ |

**インデックス**:
- `idx_tasks_status` ON (status)
- `idx_tasks_user_email` ON (user_email)
- `idx_tasks_repository` ON (repository)

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

### 8.7 ワークフロー状態管理（IWorkflowContext）

Agent FrameworkのWorkflow機能を使用する場合、**`IWorkflowContext`インターフェース**を通じて複数のExecutor間で共有状態を管理する。

**状態の書き込み処理**:

- Executor内で`context.queue_state_update_async()`メソッドを呼び出す
- 引数として以下を指定する：
  - `key`: 状態を識別するキー（文字列）
  - `value`: 保存する値（任意の型、JSON serializable）
  - `scope_name`: 状態のスコープ名（名前空間として機能）
- Agent Frameworkがワークフロー実行中にこの状態を保持する
- 同じscope_name内では一意のkeyで状態を管理する

**状態の読み込み処理**:

- 別のExecutor内で`context.read_state_async()`メソッドを呼び出す
- 引数として以下を指定する：
  - `key`: 取得したい状態のキー（文字列）
  - `scope_name`: 状態のスコープ名（書き込み時と同じ）
- Agent Frameworkが保持している状態を取得する
- 状態が存在しない場合はNoneまたは例外を返す

**状態の分離方針**:

- **タスクごとに新しいワークフローインスタンスを生成する**
  - 各タスク実行時にWorkflowBuilderから新しいWorkflowインスタンスを作成する
  - これによりタスク間で状態が混在しないことを保証する
  
- **ヘルパーメソッドでワークフロービルドを行う**
  - `create_task_workflow(task_uuid)`のようなヘルパーメソッドを実装する
  - メソッド内でWorkflowBuilderを初期化し、Executorを登録する
  - ビルドしたWorkflowインスタンスを返す
  - 各タスク実行時にこのヘルパーメソッドを呼び出して新しいワークフローを生成する

**利用例シナリオ**:

- ファイル読み込みExecutorが読み込んだファイル内容を状態として保存する
- ファイル解析Executorがその状態を読み込んで解析を行う
- コード生成Executorが解析結果の状態を参照してコードを生成する
- このように異なるExecutor間でデータを受け渡す場合に使用する

---

## 9. Tool管理設計 (MCP)

### 9.1 MCP概要とAgent Framework統合

**参考**: [Model Context Protocol 公式サイト](https://modelcontextprotocol.io/) | [MCP Specification](https://spec.modelcontextprotocol.io/) | [MCP Servers](https://github.com/modelcontextprotocol/servers)

Model Context Protocol (MCP) を使用してツール実行を標準化し、Agent Frameworkのツールとして統合します。

**MCPサーバーとして実装し、Agent Frameworkツールとして統合するツール**:
- **Command Executor MCP**: Docker環境でのコマンド実行（`execute_command`、`clone_repository`、`install_dependencies`等）
- **Text Editor MCP**: ファイル編集操作（`view_file`、`create_file`、`str_replace`、`insert_line`、`undo_edit`等）

**Agent Frameworkのネイティブツールとして実装するツール**:
- **TodoManagementTool**: Todoリスト管理（`create_todo_list`, `get_todo_list`, `update_todo_status`, `add_todo`, `delete_todo`, `reorder_todos`, `sync_to_gitlab`）
- **GitOperationTool**: Git操作は`command-executor` MCPを通じてgitコマンドを実行することで実現

#### Agent FrameworkでのMCP統合パターン

**実装方法**:
1. **MCPクライアント生成**: stdio経由でMCPサーバーと通信するクライアントを生成
2. **Agent Frameworkツールとしてラップ**: MCPクライアントをAgent Framework（Semantic Kernel）のツール（Plugin/KernelFunction）としてラップ
3. **Kernelに登録**: ラップしたツールをAgent FrameworkのKernelに登録
4. **ChatCompletionAgentで使用**: Agent FrameworkのChatCompletionAgentがツールとして使用可能になる

**実装クラス**:
- `MCPClient`: MCPサーバー通信クライアント
- `MCPToolWrapper`: MCPツールをAgent Frameworkのツールとしてラップするクラス
- `MCPClientFactory`: MCPクライアント生成とAgent Frameworkツール登録を管理

**注意**: 
- GitLab MCP Serverは使用しません。GitLab API操作はシステム側がPython GitLab クライアント経由で直接実行します。
- Git操作は専用のGit MCPを使わず、`command-executor` MCPでgitコマンドを実行します（例: `git clone`, `git add`, `git commit`, `git push`）。

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

#### 9.2.1 ExecutionEnvironmentManager連携

command-executorとtext-editorはMCPサーバーとして実装するが、ExecutionEnvironmentManager上で動くので、handlers/execution_environment_mcp_wrapper.pyを参照して設計する。

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

#### Todo Managementツール（Agent Framework独自実装）

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

#### GitLab認証

システム全体で1つのGitLab bot用Personal Access Token（PAT）を使用する。環境変数`GITLAB_PAT`で設定し、すべてのGitLab API操作に使用する。

#### OpenAI API認証

ユーザーごとにOpenAI APIキーを管理する。User Config APIから暗号化されたAPIキーを取得し、復号化して使用する。

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
      GITLAB_PAT: ${GITLAB_PAT}
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

- **日次バックアップ**: `pg_dump`コマンドでデータベース全体をgzip圧縮してバックアップする
- **リストア**: 圧縮バックアップを`psql`コマンドでリストアする

#### コンテキストバックアップ

- **週次バックアップ**: contextディレクトリ全体をtarでアーカイブしてバックアップする
- **古いバックアップ削除**: 30日以上前のバックアップファイルを自動削除する

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

## 13. 設定ファイル定義

### 13.1 config.yaml（完全定義）

すべての設定項目を以下に定義する。環境変数で上書き可能な項目は`${ENV_VAR_NAME}`形式で記載。

```yaml
# GitLab設定（bot用PATは環境変数GITLAB_PATで設定）
gitlab:
  api_url: "https://gitlab.com/api/v4"  # 環境変数: GITLAB_API_URL
  owner: "notfolder"  # 環境変数: GITLAB_OWNER
  bot_name: "notfolder-bot"  # 環境変数: GITLAB_BOT_NAME
  bot_label: "coding agent"  # 環境変数: GITLAB_BOT_LABEL
  processing_label: "coding agent processing"  # 環境変数: GITLAB_PROCESSING_LABEL
  done_label: "coding agent done"  # 環境変数: GITLAB_DONE_LABEL
  paused_label: "coding agent paused"  # 環境変数: GITLAB_PAUSED_LABEL
  stopped_label: "coding agent stopped"  # 環境変数: GITLAB_STOPPED_LABEL
  pat: "${GITLAB_PAT}"  # 必須: システム全体で1つのbot用PAT
  polling_interval: 30  # 環境変数: GITLAB_POLLING_INTERVAL（秒）
  request_timeout: 60  # 環境変数: GITLAB_REQUEST_TIMEOUT（秒）

# Issue→MR変換設定（常時有効。ラベルとアサイニーも常にコピー）
issue_to_mr:
  branch_prefix: "issue-"  # 環境変数: ISSUE_TO_MR_BRANCH_PREFIX（ブランチ名プレフィックス）
  source_branch_template: "{prefix}{issue_iid}"  # 環境変数: ISSUE_TO_MR_SOURCE_BRANCH_TEMPLATE
  target_branch: "main"  # 環境変数: ISSUE_TO_MR_TARGET_BRANCH（デフォルトのターゲットブランチ）
  mr_title_template: "Draft: {issue_title}"  # 環境変数: ISSUE_TO_MR_TITLE_TEMPLATE

# LLMデフォルト設定（ユーザーごとのOpenAI APIキーはUser Config APIから取得）
llm:
  provider: "openai"  # 環境変数: LLM_PROVIDER（値: openai, ollama, lmstudio）
  model: "gpt-4o"  # 環境変数: LLM_MODEL
  temperature: 0.2  # 環境変数: LLM_TEMPERATURE
  max_tokens: 4096  # 環境変数: LLM_MAX_TOKENS
  top_p: 1.0  # 環境変数: LLM_TOP_P
  frequency_penalty: 0.0  # 環境変数: LLM_FREQUENCY_PENALTY
  presence_penalty: 0.0  # 環境変数: LLM_PRESENCE_PENALTY

# OpenAI設定（デフォルト値、User Config APIに登録されていないユーザー用フォールバック）
openai:
  api_key: "${OPENAI_API_KEY}"  # 必須: フォールバック用APIキー
  base_url: "https://api.openai.com/v1"  # 環境変数: OPENAI_BASE_URL
  timeout: 120  # 環境変数: OPENAI_TIMEOUT（秒）

# User Config API設定
user_config_api:
  enabled: true  # 環境変数: USER_CONFIG_API_ENABLED（値: true, false）
  url: "http://user-config-api:8080"  # 環境変数: USER_CONFIG_API_URL
  api_key: "${USER_CONFIG_API_KEY}"  # 必須: User Config APIの認証キー
  timeout: 30  # 環境変数: USER_CONFIG_API_TIMEOUT（秒）

# PostgreSQL設定
database:
  url: "postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/coding_agent"  # 環境変数: DATABASE_URL（完全上書き可能）
  pool_size: 10  # 環境変数: DATABASE_POOL_SIZE
  max_overflow: 20  # 環境変数: DATABASE_MAX_OVERFLOW
  pool_timeout: 30  # 環境変数: DATABASE_POOL_TIMEOUT（秒）
  pool_recycle: 3600  # 環境変数: DATABASE_POOL_RECYCLE（秒）

# RabbitMQ設定（Producer/Consumerパターン）
rabbitmq:
  host: "rabbitmq"  # 環境変数: RABBITMQ_HOST
  port: 5672  # 環境変数: RABBITMQ_PORT
  user: "${RABBITMQ_USER:-agent}"  # 環境変数: RABBITMQ_USER（デフォルト: agent）
  password: "${RABBITMQ_PASS}"  # 必須: 環境変数: RABBITMQ_PASS
  queue_name: "coding-agent-tasks"  # 環境変数: RABBITMQ_QUEUE_NAME
  durable: true  # 環境変数: RABBITMQ_DURABLE（永続化キュー）
  prefetch_count: 1  # 環境変数: RABBITMQ_PREFETCH_COUNT（Consumer 1台あたりの同時処理タスク数）
  heartbeat: 60  # 環境変数: RABBITMQ_HEARTBEAT（秒）
  connection_timeout: 30  # 環境変数: RABBITMQ_CONNECTION_TIMEOUT（秒）

# Producer設定（タスク検出・キューイング）
producer:
  interval_seconds: 60  # 環境変数: PRODUCER_INTERVAL_SECONDS（タスク検出の間隔）
  batch_size: 10  # 環境変数: PRODUCER_BATCH_SIZE（一度に取得する最大タスク数）
  enabled: true  # 環境変数: PRODUCER_ENABLED（Producer有効化）

# Agent Framework設定（streaming, checkpointing, middleware機能は常時有効）
agent_framework:
  workflows:
    human_in_loop: false  # 環境変数: AGENT_WORKFLOWS_HUMAN_IN_LOOP
    checkpoint_interval: 10  # 環境変数: AGENT_WORKFLOWS_CHECKPOINT_INTERVAL（ステップ数）
  observability:
    opentelemetry:
      enabled: true  # 環境変数: AGENT_OBSERVABILITY_ENABLED
      endpoint: "${OTEL_EXPORTER_OTLP_ENDPOINT}"  # 環境変数で設定
      service_name: "coding-agent-orchestrator"  # 環境変数: OTEL_SERVICE_NAME
      trace_exporter: "otlp"  # 環境変数: OTEL_TRACE_EXPORTER（値: otlp, console, jaeger）

# コンテキストストレージ設定（compression, inheritanceは常時有効）
context_storage:
  base_dir: "contexts"  # 環境変数: CONTEXT_STORAGE_BASE_DIR
  compression:
    token_threshold: 8000  # 環境変数: CONTEXT_COMPRESSION_TOKEN_THRESHOLD
    keep_recent: 10  # 環境変数: CONTEXT_COMPRESSION_KEEP_RECENT
    min_to_compress: 5  # 環境変数: CONTEXT_COMPRESSION_MIN_TO_COMPRESS
  inheritance:
    max_summary_tokens: 4000  # 環境変数: CONTEXT_INHERITANCE_MAX_SUMMARY_TOKENS
    expiry_days: 30  # 環境変数: CONTEXT_INHERITANCE_EXPIRY_DAYS

# ファイルストレージ設定（ツール実行結果、大きなコンテキストデータなど）
file_storage:
  base_dir: "tool_results"  # 環境変数: FILE_STORAGE_BASE_DIR
  retention_days: 30  # 環境変数: FILE_STORAGE_RETENTION_DAYS
  max_file_size_mb: 100  # 環境変数: FILE_STORAGE_MAX_FILE_SIZE_MB
  formats:
    - "json"
    - "txt"
    - "md"
    - "log"

# プランニング設定（planning, verificationは常時有効）
planning:
  max_reflection_count: 3  # 環境変数: PLANNING_MAX_REFLECTION_COUNT
  max_plan_revision_count: 2  # 環境変数: PLANNING_MAX_PLAN_REVISION_COUNT
  reflection_interval: 5  # 環境変数: PLANNING_REFLECTION_INTERVAL（ステップ数）
  verification:
    max_rounds: 2  # 環境変数: PLANNING_VERIFICATION_MAX_ROUNDS

# MCP設定
mcp_servers:
  - name: "command-executor"
    command: ["python", "mcp/command_executor.py"]
    env:
      DOCKER_ENABLED: "true"  # 環境変数: MCP_COMMAND_EXECUTOR_DOCKER_ENABLED
      TIMEOUT: "300"  # 環境変数: MCP_COMMAND_EXECUTOR_TIMEOUT
  
  - name: "text-editor"
    command: ["npx", "@modelcontextprotocol/server-text-editor"]
    env:
      ALLOWED_DIRECTORIES: "/workspace"  # 環境変数: MCP_TEXT_EDITOR_ALLOWED_DIRECTORIES
  
# Docker実行環境設定（dockerは常時有効、cleanup_on_exitも常時有効）
execution_environment:
  docker:
    image: "python:3.11-slim"  # 環境変数: DOCKER_IMAGE
    network: "coding-agent-network"  # 環境変数: DOCKER_NETWORK
    cpu_limit: "2.0"  # 環境変数: DOCKER_CPU_LIMIT
    memory_limit: "4g"  # 環境変数: DOCKER_MEMORY_LIMIT
  workspace:
    base_path: "/workspace"  # 環境変数: WORKSPACE_BASE_PATH
    mount_path: "/mnt/workspace"  # 環境変数: WORKSPACE_MOUNT_PATH

# リトライポリシー
retry_policy:
  http_errors:
    5xx:
      max_attempts: 3  # 環境変数: RETRY_HTTP_5XX_MAX_ATTEMPTS
      backoff: exponential  # 環境変数: RETRY_HTTP_5XX_BACKOFF（値: exponential, linear, constant）
      base_delay: 1.0  # 環境変数: RETRY_HTTP_5XX_BASE_DELAY（秒）
    429:
      max_attempts: 5  # 環境変数: RETRY_HTTP_429_MAX_ATTEMPTS
      backoff: exponential  # 環境変数: RETRY_HTTP_429_BACKOFF
      base_delay: 60.0  # 環境変数: RETRY_HTTP_429_BASE_DELAY（秒）
  tool_errors:
    max_attempts: 2  # 環境変数: RETRY_TOOL_MAX_ATTEMPTS
    backoff: linear  # 環境変数: RETRY_TOOL_BACKOFF
    base_delay: 5.0  # 環境変数: RETRY_TOOL_BASE_DELAY（秒）
  llm_errors:
    max_attempts: 3  # 環境変数: RETRY_LLM_MAX_ATTEMPTS
    backoff: exponential  # 環境変数: RETRY_LLM_BACKOFF
    base_delay: 2.0  # 環境変数: RETRY_LLM_BASE_DELAY（秒）

# ログ設定
logging:
  level: INFO  # 環境変数: LOG_LEVEL（値: DEBUG, INFO, WARNING, ERROR, CRITICAL）
  file: "logs/agent.log"  # 環境変数: LOG_FILE
  max_bytes: 10485760  # 環境変数: LOG_MAX_BYTES（10MB）
  backup_count: 10  # 環境変数: LOG_BACKUP_COUNT
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"  # 環境変数: LOG_FORMAT
  date_format: "%Y-%m-%d %H:%M:%S"  # 環境変数: LOG_DATE_FORMAT

# セキュリティ設定
security:
  encryption:
    key: "${ENCRYPTION_KEY}"  # 必須: 32バイト以上のランダムキー（User Config APIのAPIキー暗号化用）
    algorithm: "AES-256-GCM"  # 環境変数: ENCRYPTION_ALGORITHM
  jwt:
    secret: "${JWT_SECRET}"  # 必須: JWT署名用秘密鍵（User Config API認証用）
    algorithm: "HS256"  # 環境変数: JWT_ALGORITHM
    expiration: 86400  # 環境変数: JWT_EXPIRATION（秒、デフォルト24時間）

# タスク処理設定
task_processing:
  max_concurrent_tasks: 3  # 環境変数: TASK_MAX_CONCURRENT
  task_timeout: 3600  # 環境変数: TASK_TIMEOUT（秒）
  cleanup_completed_after_days: 30  # 環境変数: TASK_CLEANUP_DAYS
  max_retries: 3  # 環境変数: TASK_MAX_RETRIES

# メトリクス設定
metrics:
  enabled: true  # 環境変数: METRICS_ENABLED
  collection_interval: 60  # 環境変数: METRICS_COLLECTION_INTERVAL（秒）
  task_processing_time: true  # 環境変数: METRICS_TASK_PROCESSING_TIME
  success_rate: true  # 環境変数: METRICS_SUCCESS_RATE
  queue_length: true  # 環境変数: METRICS_QUEUE_LENGTH
  api_rate_limits: true  # 環境変数: METRICS_API_RATE_LIMITS
  token_usage: true  # 環境変数: METRICS_TOKEN_USAGE
  system_resources: true  # 環境変数: METRICS_SYSTEM_RESOURCES（CPU、メモリ、ディスク）

# アラート設定（常時有効）
alerts:
  notification_channel: "gitlab"  # 環境変数: ALERTS_NOTIFICATION_CHANNEL（値: gitlab, email, slack）
  thresholds:
    task_failure_rate: 0.1  # 環境変数: ALERTS_THRESHOLD_TASK_FAILURE_RATE（タスク失敗率10%超過でアラート）
    queue_length: 100  # 環境変数: ALERTS_THRESHOLD_QUEUE_LENGTH（キュー長100超過でアラート）
    disk_usage: 0.8  # 環境変数: ALERTS_THRESHOLD_DISK_USAGE（ディスク使用率80%超過でアラート）
    memory_usage: 0.9  # 環境変数: ALERTS_THRESHOLD_MEMORY_USAGE（メモリ使用率90%超過でアラート）
    api_rate_limit_remaining: 0.1  # 環境変数: ALERTS_THRESHOLD_API_RATE_LIMIT（APIレート制限残り10%でアラート）

# バックアップ設定
backup:
  enabled: true  # 環境変数: BACKUP_ENABLED
  database:
    enabled: true  # 環境変数: BACKUP_DATABASE_ENABLED
    schedule: "0 2 * * *"  # 環境変数: BACKUP_DATABASE_SCHEDULE（cron形式、デフォルト: 毎日2:00）
    retention_days: 30  # 環境変数: BACKUP_DATABASE_RETENTION_DAYS
    output_dir: "backups/database"  # 環境変数: BACKUP_DATABASE_OUTPUT_DIR
  contexts:
    enabled: true  # 環境変数: BACKUP_CONTEXTS_ENABLED
    schedule: "0 3 * * 0"  # 環境変数: BACKUP_CONTEXTS_SCHEDULE（cron形式、デフォルト: 毎週日曜日3:00）
    retention_days: 30  # 環境変数: BACKUP_CONTEXTS_RETENTION_DAYS
    output_dir: "backups/contexts"  # 環境変数: BACKUP_CONTEXTS_OUTPUT_DIR
  tool_results:
    enabled: true  # 環境変数: BACKUP_TOOL_RESULTS_ENABLED
    schedule: "0 3 * * 0"  # 環境変数: BACKUP_TOOL_RESULTS_SCHEDULE（cron形式、デフォルト: 毎週日曜日3:00）
    retention_days: 30  # 環境変数: BACKUP_TOOL_RESULTS_RETENTION_DAYS
    output_dir: "backups/tool_results"  # 環境変数: BACKUP_TOOL_RESULTS_OUTPUT_DIR
```

### 13.2 設定管理クラス設計

#### 13.2.1 ConfigManager

設定ファイルと環境変数を統合管理するクラス。

**責務**:
- config.yamlをロードしてデフォルト設定を取得
- 環境変数で該当する設定項目を上書き
- 設定値のバリデーション（必須項目チェック、型検証、値の範囲検証）
- 設定値へのアクセスインターフェース提供

**主要メソッド**:
- `__init__(config_path)`: 設定ファイルと環境変数から設定をロード
- `get(key, default)`: ドット区切りのキーで設定値を取得（例: "gitlab.api_url"）
- `get_gitlab_config()`: GitLab設定を取得
- `get_llm_config()`: LLM設定を取得
- `get_database_config()`: PostgreSQL設定を取得
- `get_user_config_api_config()`: User Config API設定を取得
- `get_agent_framework_config()`: Agent Framework設定を取得
- `get_rabbitmq_config()`: RabbitMQ設定を取得
- `get_producer_config()`: Producer設定を取得
- `get_issue_to_mr_config()`: Issue → MR変換設定を取得
- `get_metrics_config()`: メトリクス設定を取得
- `get_alerts_config()`: アラート設定を取得
- `get_backup_config()`: バックアップ設定を取得
- `validate()`: 設定値のバリデーションを実行しエラーリストを返す
- `reload()`: 設定をリロード（開発/テスト用）

#### 13.2.2 設定データクラス

各設定カテゴリごとにPydanticモデルで定義し、バリデーションを実装する。

**主要な設定クラス**:
- `GitLabConfig`: GitLab API設定、ボット設定、ラベル設定
- `LLMConfig`: LLMプロバイダー、モデル、温度等のパラメータ
- `DatabaseConfig`: PostgreSQL接続情報、コネクションプール設定
- `UserConfigAPIConfig`: User Config API接続情報
- `AgentFrameworkConfig`: ワークフロー、監視、Middleware設定
- `RabbitMQConfig`: RabbitMQ接続情報、キュー設定
- `ProducerConfig`: タスク生成間隔、バッチサイズ設定
- `IssueToMRConfig`: Issue→MR自動変換設定、ブランチ名テンプレート
- `MetricsConfig`: メトリクス収集設定
- `AlertsConfig`: アラート通知設定
- `BackupConfig`: バックアップ設定

各データクラスはPydanticの`BaseModel`を継承し、`Field`でデフォルト値と検証ルールを定義する。必要に応じて`@validator`デコレータでカスタムバリデーションを追加する。

#### 13.2.3 環境変数マッピング

ConfigManager内で環境変数をYAML設定キーにマッピングする。

**マッピング方針**:
- 環境変数名: `CATEGORY_SUBCATEGORY_KEY`形式（例: `GITLAB_API_URL`）
- YAML設定キー: `category.subcategory.key`形式（例: `gitlab.api_url`）
- 主要な環境変数カテゴリ:
  - `GITLAB_*`: GitLab関連設定
  - `LLM_*`: LLM関連設定
  - `OPENAI_*`: OpenAI固有設定
  - `USER_CONFIG_API_*`: User Config API設定
  - `DATABASE_*`: PostgreSQL設定
  - `RABBITMQ_*`: RabbitMQ設定
  - `PRODUCER_*`: Producer設定
  - `ISSUE_TO_MR_*`: Issue→MR変換設定
  - `METRICS_*`: メトリクス設定
  - `ALERTS_*`: アラート設定
  - `BACKUP_*`: バックアップ設定

**環境変数の優先順位**:
1. 環境変数（最優先）
2. config.yamlのデフォルト値
3. Pydanticモデルのデフォルト値

---

## 14. 改善ポイント（coding_agent比較）

### 14.1 アーキテクチャ改善

**参考**: [Semantic Kernel and Microsoft Agent Framework](https://devblogs.microsoft.com/semantic-kernel/semantic-kernel-and-microsoft-agent-framework/) | [Migration Guide](https://devblogs.microsoft.com/semantic-kernel/migrate-your-semantic-kernel-and-autogen-projects-to-microsoft-agent-framework-release-candidate/)

| 項目 | coding_agent | 本設計 | 改善内容 |
|------|-------------|--------|---------|
| フレームワーク | 独自実装 | Microsoft Agent Framework | 標準化、Graph-based Workflows、OpenTelemetry統合 |
| 状態管理 | ファイルベース | PostgreSQL + ファイル | 検索性向上、スケーラビリティ |
| ワークフロー | 固定フェーズ | Agent Framework Workflowsプランニングベース | 柔軟な分岐・チェックポイント・リトライ |
| ツール管理 | 直接API呼び出し | Agent Framework + MCP | Middleware統合、標準準拠 |
| エラー処理 | 分散実装 | Agent Framework Middleware | 統一的なエラーハンドリング |

### 14.2 Microsoft Semantic Kernel (Python)標準機能の活用

**参考**: [Semantic Kernel (Python)](https://learn.microsoft.com/en-us/semantic-kernel/?pivots=programming-language-python) | [Agent Framework Documentation (Python)](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)

| 標準機能 | 用途 | メリット | ドキュメント |
|---------|------|---------|------------|
| ChatCompletionAgent | AIエージェント基盤 | LLM呼び出し、会話フロー制御 | [Agent Chat](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python) |
| ChatHistory | 会話履歴管理 | 簡単なメッセージ管理、独自Providerで永続化可能 | [Chat History](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python) |
| Memory / Embeddings | ベクトルメモリー管理 | コンテキスト検索、プランニング履歴管理 | [Vector Stores](https://learn.microsoft.com/en-us/semantic-kernel/concepts/vector-store-connectors?pivots=programming-language-python) |
| OpenTelemetry統合 | 分散トレーシング | 監視、デバッグ、パフォーマンス分析 | [Observability](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/observability/?pivots=programming-language-python) |
| Filters | リクエスト処理 | エラーハンドリング、ログ記録、認証の統一 | [Filters](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters?pivots=programming-language-python) |
| AI Services | LLM統合 | 複数プロバイダー対応、統一API | [Chat Completion](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion?pivots=programming-language-python) |
| Plugins | ツール/プラグイン | GitLab API、MCP、カスタムツール統合 | [Adding Native Plugins](https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/adding-native-plugins?pivots=programming-language-python) |

※Python版はProcess Framework (Workflow/Executor)が未実装。MR処理フローは独自ワークフロークラスで実装。

### 14.3 coding_agentからの移植対象ファイル

#### 14.3.1 必須移植コンポーネント（Issue→MR変換）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`handlers/issue_to_mr_converter.py`** | `IssueToMRConverter` | Issue→MR変換メインロジック | ほぼそのまま移植 | Agent Framework Workflowノードとして実装 |
| | `BranchNameGenerator` | LLMによるブランチ名生成 | そのまま移植 | Agent Framework LLM Clientを使用 |
| | `ContentTransferManager` | IssueコメントのMRへの転記 | そのまま移植 | GitlabClientと連携 |
| **`clients/gitlab_client.py`** | `GitlabClient` | GitLab REST API操作 | そのまま移植 | 適切なAPIクライアントとして使用 |
| | `create_merge_request()` | MR作成 | そのまま移植 | - |
| | `create_branch()` | ブランチ作成 | そのまま移植 | - |
| | `create_commit()` | コミット作成 | そのまま移植 | - |
| | `add_merge_request_note()` | MRにコメント追加 | そのまま移植 | - |
| | `update_merge_request()` | MR更新 | そのまま移植 | - |
| | `list_merge_requests()` | MRリスト取得 | そのまま移植 | - |
| | `list_merge_request_notes()` | MRコメントリスト取得 | そのまま移植 | - |
| **`handlers/task_getter_gitlab.py`** | `TaskGitLabIssue` | GitLab Issue操作 | 独自ワークフロークラスに統合 | - |
| | `TaskGitLabMergeRequest` | GitLab MR操作 | 独自ワークフロークラスに統合 | - |
| | `TaskGetterFromGitLab` | GitLabタスク取得 | 独自ワークフロークラスに統合 | PostgreSQLで処理済みタスクを除外 |
| **`handlers/task_factory.py`** | `GitLabTaskFactory` | TaskオブジェクトをTaskKeyから生成 | ワークフローに統合 | - |
| **`handlers/task_key.py`** | `GitLabIssueTaskKey` | IssueのTaskKey | そのまま移植 | - |
| | `GitLabMergeRequestTaskKey` | MRのTaskKey | そのまま移植 | - |

#### 14.3.2 コンテキスト管理（独自Providerパターンで再実装）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`context_storage/task_context_manager.py`** | `TaskContextManager` | タスクコンテキスト管理 | **独自マネージャーで再実装** | **PostgreSQLベースの独自コンテキスト管理クラス** |
| **`context_storage/message_store.py`** | `MessageStore` | LLM会話履歴保存 | **PostgreSqlChatHistoryProviderで再実装** | **[ChatHistory](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python)パターンを活用** |
| **`context_storage/summary_store.py`** | `SummaryStore` | 要約保存 | **PlanningContextProviderに統合** | **[Vector Stores](https://learn.microsoft.com/en-us/semantic-kernel/concepts/vector-store-connectors?pivots=programming-language-python)パターンを活用** |
| **`context_storage/tool_store.py`** | `ToolStore` | ツール実行履歴 | **ToolResultContextProviderで再実装** | **独自ストレージクラスとして実装** |
| **`context_storage/context_compressor.py`** | `ContextCompressor` | コンテキスト圧縮 | 参考にして再実装 | LLMはSemantic Kernel経由 |
| **`context_storage/context_inheritance_manager.py`** | `ContextInheritanceManager` | コンテキスト継承 | 参考にして再実装 | 独自管理クラスで実装 |

**重要**: coding_agentのファイルベースのコンテキスト管理を、PostgreSQLベースの独自コンテキスト管理クラスで再設計する。[ChatHistory](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python)と[Vector Stores](https://learn.microsoft.com/en-us/semantic-kernel/concepts/vector-store-connectors?pivots=programming-language-python)パターンを参考にすることで、保守性が向上する。

#### 14.3.4 ユーザー管理（User Config API）

| ファイルパス | 用途 | 移植方法 | 変更点 |
|------------|------|---------|--------|
| **`user-config-api/app.py`** | FastAPI: ユーザー設定管理API | そのまま移植 | PostgreSQLスキーマを統合 |
| **`user-config-api/models.py`** | Pydanticモデル | そのまま移植 | - |
| **`user-config-api/database.py`** | SQLAlchemy DB接続 | そのまま移植 | - |
| **`user-config-api/encryption.py`** | APIキー暗号化 | そのまま移植 | - |
| **`web-config/app.py`** | Streamlit Web UI | そのまま移植 | - |

#### 14.3.5 環境管理（Docker実行環境）

| ファイルパス | 主要クラス/関数 | 用途 | 移植方法 | 変更点 |
|------------|---------------|------|---------|--------|
| **`handlers/execution_environment_manager.py`** | `ExecutionEnvironmentManager` | Docker環境管理 | 参考にして再実装 | 独自ワークフロークラスに統合 |
| **`handlers/execution_environment_mcp_wrapper.py`** | `ExecutionEnvironmentMCPWrapper` | MCP Wrapper | Pluginまたはツールとして登録 | - |
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

4. **Agent Framework標準Providerのカスタム実装**
   - ChatHistoryProvider: PostgreSQL永続化（PostgreSqlChatHistoryProvider）
   - AIContextProvider: プランニング履歴管理（PlanningContextProvider）
   - AIContextProvider: ツール実行結果管理（ToolResultContextProvider）
   - ProviderSessionState<T>: 型安全なセッション状態管理
   - IWorkflowContext: ワークフロー内共有状態管理

5. **標準化されたツール管理**
   - MCP (Model Context Protocol) 採用
   - Agent Framework Middlewareとの統合
   - coding_agentのMCPクライアント流用

6. **coding_agentからの資産流用**
   - データベーススキーマ: `context_storage/*` のテーブル設計を参考
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

1. **Agent Framework標準Providerパターンの活用**
   - ChatHistoryProviderを継承してPostgreSQL永続化を実装
   - AIContextProviderを継承してプランニング・ツール結果管理を実装
   - ProviderSessionState<T>で型安全なセッション状態管理を実現
   - 独自実装を避け、標準パターンに準拠

2. **coding_agent資産の活用**: 実績あるコンポーネントを積極活用
   - データベーススキーマ設計を参考
   - MCPクライアントの統合
   - 環境管理ロジックの再利用

3. **PostgreSQLとファイルストレージの適切な使い分け**: 検索性とデバッグ性のバランス
   - 構造化データ（会話履歴、プランニング履歴）: PostgreSQL
   - 非構造化データ（ツール実行結果、ファイル内容）: ファイルストレージ

4. **OpenTelemetry統合**: 初期から監視基盤を構築
   - Agent Framework標準のテレメトリ機能を活用
   - カスタムProviderでもトレーシング情報を記録
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

### A.4 環境管理

```
handlers/execution_environment_manager.py
  - ExecutionEnvironmentManager: Docker環境管理

handlers/execution_environment_mcp_wrapper.py
  - ExecutionEnvironmentMCPWrapper: MCP Wrapper

handlers/environment_analyzer.py
  - EnvironmentAnalyzer: 環境解析
```

### A.5 プランニング

```
handlers/pre_planning_manager.py
  - PrePlanningManager: 事前計画管理
```

### A.6 LLMクライアント

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

### A.7 ユーザー管理

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
