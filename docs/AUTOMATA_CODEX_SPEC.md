# GitLab Coding Agent: AutomataCodex — Agent Framework 設計

**参考**: [Agent Framework Documentation (Python)](https://github.com/microsoft/agent-framework)

**関連ドキュメント**:
- [CLASS_IMPLEMENTATION_SPEC.md](CLASS_IMPLEMENTATION_SPEC.md) - クラス設計
- [AGENT_DEFINITION_SPEC.md](AGENT_DEFINITION_SPEC.md) - エージェント定義仕様（コンテキストデータ構造を含む）
- [GRAPH_DEFINITION_SPEC.md](GRAPH_DEFINITION_SPEC.md) - ワークフローグラフ定義
- [DATABASE_SCHEMA_SPEC.md](DATABASE_SCHEMA_SPEC.md) - データベーススキーマ定義
- [STANDARD_MR_PROCESSING_FLOW.md](STANDARD_MR_PROCESSING_FLOW.md) - 標準MR処理フロー

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

- **[Microsoft Agent Framework](https://github.com/microsoft/agent-framework)（Python）**: エージェントオーケストレーション基盤（MR処理のみ）
  - **[Filters (Middleware)](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_middleware.py)**: リクエスト/レスポンス処理、例外ハンドリング、カスタムパイプライン
  - **[OpenTelemetry統合](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/observability.py)**: 分散トレーシング、モニタリング、デバッグ
  - **[AI Services](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_clients.py)**: 複数のLLMプロバイダーサポート
  - **[Process Framework (Workflow/Executor)](https://github.com/microsoft/agent-framework/tree/main/python/packages/core/agent_framework/_workflows)**: ワークフロー実行とExecutor管理
- **Producer/Consumerパターン（[coding_agent](https://github.com/notfolder/coding_agent)踏襲）**: タスクキュー管理
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
- **Producer/Consumerパターン（[coding_agent](https://github.com/notfolder/coding_agent)踏襲）**
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
    subgraph Producer ["Producer Layer（[coding_agent](https://github.com/notfolder/coding_agent)踏襲）"]
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
        W4[GuidelineLearningAgent<br/>学習エージェント]
        
        C4 --> W1
        W1 --> W2
        W2 --> W3
        W3 --> W4
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
- **Producer/Consumer分離**: [coding_agent](https://github.com/notfolder/coding_agent)のパターンを踏襲し、スケーラビリティを確保
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

**Producer実装（[coding_agent](https://github.com/notfolder/coding_agent)踏襲）**:
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
            WF->>FS: Docker環境でgit操作（commit等）
            WF->>FS: ツール実行結果保存
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

**Consumer実装（[coding_agent](https://github.com/notfolder/coding_agent)踏襲）**:
- `consumer.py: consume_tasks()` - タスクデキューロジック
- `consumer.py: run_consumer_continuous()` - Consumer実行ループ
- `handlers/task_handler.py: TaskHandler.handle()` - タスク処理分岐
  - `_should_convert_issue_to_mr()` - Issue判定
  - `_convert_issue_to_mr()` - 前処理フロー実行
  - その他メソッド - 本フロー実行（Agent Framework呼び出し）

---

### 2.3 主要コンポーネント

#### 2.3.1 Producer/Consumer Layer（[coding_agent](https://github.com/notfolder/coding_agent)踏襲）

| コンポーネント | 責務 | 実装技術 | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|---------------------|
| **Producer** | Issue/MR検出・キューイング | Python + GitLab API + RabbitMQ | `producer.py`は[coding_agent](https://github.com/notfolder/coding_agent)の[main.py](https://github.com/notfolder/coding_agent/blob/main/main.py)のコードをベースに新規作成<br/>`queueing.py` |
| **Consumer** | タスクデキュー・処理振り分け | Python + RabbitMQ | `consumer.py`は[coding_agent](https://github.com/notfolder/coding_agent)の[main.py](https://github.com/notfolder/coding_agent/blob/main/main.py)のコードをベースに新規作成<br/>`queueing.py` |
| **TaskHandler** | タスク処理分岐（Issue/MR判定） | Python | `handlers/task_handler.py` |
| **RabbitMQ** | 分散タスクキュー | RabbitMQ（durable queue） | - |
| **TaskGetterFromGitLab** | GitLab API経由タスク取得 | Python + GitLab API | [coding_agent](https://github.com/notfolder/coding_agent)のものをそのまま流用 |
| **FileLock** | 並行ファイルアクセスの排他制御 | Python | [filelock_util.py](https://github.com/notfolder/coding_agent/blob/main/filelock_util.py)をそのまま移植 |

#### 2.3.2 Issue→MR変換 Layer（前処理フロー）

| コンポーネント | 責務 | Agent Frameworkクラス | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|---------------------|
| **IssueToMRConverter** | Issue→MR変換 | Agent Framework Workflow | Agent FrameworkのProcess Frameworkを使用してIssue→MR変換ワークフローを実装 |
| **Branch Naming Agent** | ブランチ名生成 | [`Agent`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_agents.py) | [coding_agent](https://github.com/notfolder/coding_agent)を参考にして、Agent FrameworkのAgentを使用してLLMにブランチ名生成を依頼 |

#### 2.3.3 MR処理 Layer（本フロー - Agent Framework）

| コンポーネント | 責務 | Agent Frameworkクラス | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|---------------------|
| **WorkflowFactory** | ワークフロー生成・環境準備 | Agent Framework Process Framework | グラフ定義からAgent FrameworkのWorkflowを動的に生成し、Docker環境を準備する |
| **WorkflowBuilder** | グラフ構造からワークフロー構築 | Agent Framework Workflow | グラフ定義のノード・エッジをAgent FrameworkのWorkflow構造に変換 |
| **ConfigurableAgent** | エージェントノード実行 | [`Executor`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_workflows/_executor.py) | エージェント定義とプロンプト定義に基づいて動作する汎用エージェント |
| **MCPToolClient** | ファイル編集・コマンド実行 | Agent Framework MCP統合 | Agent FrameworkのMCPツール統合機能を使用してMCP Server (text-editor、command-executor)をAgent Frameworkツールとして統合 |
| **PrePlanningManager** | 計画前情報収集・環境選択 | 独自実装 | [handlers/pre_planning_manager.py](https://github.com/notfolder/coding_agent/blob/main/handlers/pre_planning_manager.py)を参考に実装。タスク種別判定、環境ファイル検出、LLMによるプロジェクト言語判定と実行環境選択を担当 |
| **EnvironmentAnalyzer** | 環境ファイル検出 | 独自実装 | [handlers/environment_analyzer.py](https://github.com/notfolder/coding_agent/blob/main/handlers/environment_analyzer.py)を移植。requirements.txt、package.json等の環境構築関連ファイルをリポジトリから検出 |
| **ExecutionEnvironmentManager** | Docker環境管理・環境名マッピング | 独自実装 | [handlers/execution_environment_manager.py](https://github.com/notfolder/coding_agent/blob/main/handlers/execution_environment_manager.py) 参考、独自クラスとして実装。環境名（python、node等）からDockerイメージへのマッピング、環境プール管理、割り当て、クリーンアップを担当。詳細は[セクション8.7](#87-実行環境管理executionenvironmentmanager)を参照 |

**実装方針**: 
- グラフ定義・エージェント定義・プロンプト定義をworkflow_definitionsテーブルから読み込み、動的にワークフローを構築
- MCPサーバー（text-editor、command-executor）はAgent FrameworkのMCPツール統合機能を使用してAgent Frameworkのツールとして登録する
- カスタムツール（todo管理等）はMCPサーバーではなく、Agent Frameworkのネイティブツールとして直接実装する

#### 2.3.4 Runtime Layer

| コンポーネント | 責務 | 実装技術 | Agent Framework | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|----------------|---------------------|
| **UserManager** | ユーザー情報・APIキー管理 | PostgreSQL + FastAPI | - | - |
| **PostgreSqlChatHistoryProvider** | 会話履歴永永化 | PostgreSQL | Agent Framework [BaseHistoryProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)パターン | [context_storage/message_store.py](https://github.com/notfolder/coding_agent/blob/main/context_storage/message_store.py)参考、独自のHistory管理クラス実装 |
| **PlanningContextProvider** | プラン・要約永続化 | PostgreSQL | 独自Provider実装 | [context_storage/summary_store.py](https://github.com/notfolder/coding_agent/blob/main/context_storage/summary_store.py)参考、カスタムコンテキスト管理 |
| **ToolResultContextProvider** | ツール実行結果永続化 | File + PostgreSQL | 独自Provider実装 | [context_storage/tool_store.py](https://github.com/notfolder/coding_agent/blob/main/context_storage/tool_store.py)参考、ファイル+DB複合ストレージ |
| **TaskDBManager** | 処理済みタスクのDB記録・重複排除 | PostgreSQL | - | [db/task_db.py](https://github.com/notfolder/coding_agent/blob/main/db/task_db.py)参考、処理済みMR/Issue重複防止 |
| **PostgreSQL** | Context Storage + ユーザー情報 | PostgreSQL | - | - |
| **File Storage** | ツール実行結果保存 | ローカルファイルシステム | - | - |

---

## 3. ユーザー管理システム

ユーザーごとのOpenAI APIキー、LLM設定、プロンプトカスタマイズ、ワークフロー定義の選択を管理する。詳細な設計、データベーススキーマ、API仕様については**[USER_MANAGEMENT_SPEC.md](USER_MANAGEMENT_SPEC.md)**を参照。

**主要機能**:
- **ユーザー登録・管理**: メールアドレスベースのユーザー管理
- **APIキー管理**: OpenAI APIキーの暗号化保存（AES-256-GCM）
- **プロンプトカスタマイズ**: ワークフロー定義のプロンプト定義をカスタマイズ（標準MR処理では13エージェント対応）
- **ワークフロー定義管理**: システムプリセット（standard_mr_processing、multi_codegen_mr_processing）とユーザー独自定義
- **トークン統計**: ユーザー別のLLMトークン使用量記録
- **Web管理画面**: Vue.js + FastAPI バックエンド

**データベーステーブル**（詳細は [DATABASE_SCHEMA_SPEC.md](DATABASE_SCHEMA_SPEC.md) を参照）:
- `users` - ユーザー基本情報
- `user_configs` - LLM設定（APIキー、モデル、プロバイダ）
- `todos` - Todoリスト管理
- `workflow_definitions` - ワークフロー定義（グラフ・エージェント・プロンプト）
- `user_workflow_settings` - ユーザー別ワークフロー選択
- `token_usage` - トークン使用量統計
- その他、コンテキストストレージ関連テーブル（context_messages、context_planning_history等）

---

## 4. エージェント構成

**標準MR処理フローのエージェント構成については [STANDARD_MR_PROCESSING_FLOW.md セクション2](docs/STANDARD_MR_PROCESSING_FLOW.md#2-エージェント構成) を参照してください。**

### 4.1 Factory設計

#### 4.2.1 WorkflowFactory

**責務**: ワークフロー定義ファイルに基づいて適切なWorkflowを生成する

**保持オブジェクト**:
- `WorkflowBuilder`: Workflow構築
- `ExecutorFactory`: Executor生成
- `AgentFactory`: Agent生成
- `mcp_server_configs`: MCPサーバー設定（AgentFactoryがcreate_agent()呼び出し時にMCPClientFactoryを新規生成するため、設定情報のみを保持）
- `ContextStorageManager`: コンテキスト管理
- `TodoManager`: Todo管理
- `TokenUsageMiddleware`: トークン統計
- `DefinitionLoader`: 定義ファイル読み込み
- `config`: システム全体の設定（ユーザー別学習機能設定はUser Config APIから取得）
- `gitlab_client`: GitLab APIクライアント（学習ノード生成時のみ使用、他エージェントには渡さない）

**主要メソッド**:
- `create_workflow_from_definition(user_id, task_context)`: ユーザーのワークフロー定義に基づいてWorkflowを生成する
- `_build_nodes(graph_def, agent_def, prompt_def, user_id)`: グラフ定義の各ノードに対してConfigurableAgentインスタンスを生成する
- `_setup_plan_environment()`: ワークフロー開始前にpython固定のplan環境を1つ作成し、リポジトリをcloneする。作成した環境IDはコンテキストの`plan_environment_id`キーに保存する
- `_inject_learning_node(graph_def)`: 学習機能が有効な場合、グラフ定義にGuidelineLearningAgentノードを自動挿入する

**実装方針**:
1. コンストラクタで各Factory、Manager、Middleware、DefinitionLoaderを保持
2. ワークフロー生成時にDefinitionLoaderでユーザーのワークフロー定義を取得する
3. `_setup_plan_environment()`でpython固定のplan環境を1つ事前作成しコンテキストの`plan_environment_id`に保存する。実行環境は、グラフ実行中に各タスク分岐内の`exec_env_setup_*`ノード（ExecEnvSetupExecutor）がplanning完了後に`selected_environment`を参照し、ノード設定の`env_count`数分を作成する
4. WorkflowBuilderを使用してExecutorを追加（UserResolver、PlanEnvSetup等）
5. グラフ定義に従って各ノードの確定したenv_idをcreate_agent()に渡し、ConfigurableAgentをWorkflowBuilderに追加する
6. TokenUsageMiddlewareをWorkflowBuilderに追加する
7. WorkflowBuilderのbuild()メソッドでWorkflowオブジェクトを生成して返却する
8. タスク処理開始時にUser Config APIからユーザーの`user_config`を取得し、`user_config.learning_enabled=true`の場合、ワークフロー生成前に`_inject_learning_node()`を呼び出す
9. 注入された学習ノードはGuidelineLearningAgentインスタンスとして生成し、`gitlab_client`およびuser_configの学習設定を注入する

**学習ノード自動挿入メカニズム**:

`_inject_learning_node(graph_def)`は、学習機能が有効な場合にグラフ定義へ透過的に学習ノードを追加する。

処理手順:
1. `user_config.learning_enabled`をチェックし、falseの場合は即座に戻る
2. グラフ定義の`nodes`配列から`is_end_node=true`のノードを検索する
3. エンドノードへの接続エッジ（例: `review→end`）を特定する
4. 学習ノード（`node_id="learning"`、`agent_definition_id="guideline_learning"`）を`nodes`配列に追加する
5. エンドノードへの既存エッジを学習ノードに向け直す（例: `review→learning`）
6. 学習ノードからエンドノードへのエッジを追加する（例: `learning→end`）

グラフ構造の変化:

```mermaid
graph LR
    subgraph "元のグラフ"
    A1[Planning] --> B1[Execution]
    B1 --> C1[Review]
    C1 --> E1[end]
    end

    subgraph "学習ノード挿入後"
    A2[Planning] --> B2[Execution]
    B2 --> C2[Review]
    C2 --> L2[GuidelineLearningAgent]
    L2 --> E2[end]
    end
```

#### 4.2.2 ExecutorFactory

**責務**: タスク処理に必要なExecutorを生成する

**保持オブジェクト**:
- `UserConfigClient`: ユーザー設定取得
- `GitLabClient`: GitLab API操作
- `ExecutionEnvironmentManager`: Docker環境管理

**主要メソッド**:
- `create_user_resolver(context)`: UserResolverExecutor生成
- `create_content_transfer(context)`: ContentTransferExecutor生成
- `create_plan_env_setup(context)`: PlanEnvSetupExecutor生成（グラフ開始前にWorkflowFactoryが使用）
- `create_branch_merge(context)`: BranchMergeExecutor生成（multi_codegen_mr_processing用）

**実装方針**:
1. コンストラクタでUserConfigClient、GitLabClient、ExecutionEnvironmentManagerを保持
2. UserResolverExecutor生成時はWorkflowContextとUserConfigClientを渡してインスタンス化
3. ContentTransferExecutor生成時はWorkflowContextとGitLabClientを渡してインスタンス化
4. PlanEnvSetupExecutor生成時はWorkflowContext、ExecutionEnvironmentManager、config（`plan_environment_name`を含む）を渡してインスタンス化
5. BranchMergeExecutor生成時はWorkflowContextとGitLabClientを渡し、`selected_implementation`から選択ブランチを取得してマージ実行
6. 各ExecutorはWorkflowContextを介してタスク全体の状態を共有

#### 4.2.3 TaskStrategyFactory

**責務**: タスクの処理戦略を決定する（Issue→MR変換判定など）

**保持オブジェクト**:
- `GitLabClient`: GitLab API操作
- `ConfigManager`: 設定管理

**主要メソッド**:
- `create_strategy(task, workflow_factory=None, definition_loader=None, task_repository=None, issue_to_mr_converter=None)`: タスクに対する処理戦略を生成
- `should_convert_issue_to_mr(task)`: Issue→MR変換が必要か判定

**実装方針**:
1. コンストラクタでGitLabClientとConfigManagerを保持
2. create_strategy()でタスクタイプを判定して適切な戦略クラスを生成
   - Issueタイプ：should_convert_issue_to_mr()でIssue→MR変換判定を実行
     - 変換必要な場合: IssueToMRConversionStrategyを生成
     - 変換不要な場合: IssueOnlyStrategyを生成
   - MergeRequestタイプ: MergeRequestStrategyを生成
   - 不明なタイプ: ValueErrorをスロー
3. should_convert_issue_to_mr()で[coding_agent](https://github.com/notfolder/coding_agent)から移植した判定ロジックを実行
   - 設定で指定されたbotラベルがIssueに付いているか確認
   - 同じIssue番号に対応するsource_branchを持つMRが既に存在しないか確認
   - 設定で自動変換が有効か確認
   - 全ての条件を満たす場合はTrueを返却

#### 4.2.4 MCPClientFactory

**責務**: MCPサーバーへのクライアント接続を生成し、Agent Frameworkのツールとして登録する

**保持オブジェクト**:
- `Dict[str, MCPServerConfig]`: サーバー設定
- `MCPClientRegistry`: クライアント登録管理

**主要メソッド**:
- `create_client(server_name, env_id)`: 指定されたMCPサーバーへのクライアント生成
- `create_text_editor_client(env_id)`: text-editorクライアント生成（Agent FrameworkのMCPStdioToolとしてtools listに登録）
- `create_command_executor_client(env_id)`: command-executorクライアント生成（Agent FrameworkのMCPStdioToolとしてtools listに登録）

**実装方針**:
1. コンストラクタでMCPServerConfig辞書とMCPClientRegistryを保持する。MCPStdioToolはAgentFactoryがエージェントごとに生成してtools listに渡すため、MCPClientFactoryは保持しない
2. create_client(server_name, env_id)でMCPクライアント生成とツール登録を実施
   - 既にレジストリに登録済みの場合は既存クライアントを返却
   - 設定から指定されたサーバー名のMCPServerConfigを取得
   - MCPServerConfigのcommandにenv_idを埋め込んで対象Dockerコンテナを特定し、MCPStdioToolを生成してstdio経由で接続する
   - レジストリに登録し、MCPStdioToolオブジェクトを返却
3. 返却されたMCPStdioToolはAgentFactoryがAgent(tools=[...])として直接渡す
4. create_text_editor_client(env_id)とcreate_command_executor_client(env_id)は各MCPサーバーへのエイリアス

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

**継承元**: [`Executor`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_workflows/_executor.py)

**責務**: グラフ内のすべてのエージェントノードを実装する単一クラス。エージェント定義ファイルの設定に基づいて動作する。

**保持する設定（AgentNodeConfig）**:
- `node_id`: グラフノードID（例: "code_generation_a"）
- `agent_definition_id`: エージェント定義ID（例: "code_generation_fast"）。グラフ定義の`agent_definition_id`フィールドから取得
- `role`: エージェント役割（"planning" | "reflection" | "execution" | "review"）
- `input_keys`: 前ステップから受け取るワークフローコンテキストのキー一覧
- `output_keys`: 次ステップへ渡すワークフローコンテキストのキー一覧
- `mcp_servers`: 利用するMCPサーバー名一覧（`"text_editor"`, `"command_executor"`, `"todo_list"`（仮想） 等。省略時は空配列扱い）
- `env_ref`: 使用する実行環境の参照（"plan": plan共有環境、"1"/"2"/"3": 分岐内の第N実行環境、省略: 環境不要）
- `prompt_id`: プロンプト定義ファイル内のプロンプト識別子

**保持する依存性**:
- `agent`: Agentインスタンス（Agent Framework提供）
- `progress_reporter`: ProgressReporterインスタンス（進捗報告機能）
- `environment_id`: Docker環境ID（env_refが"plan"または"1"/"2"/"3"の場合）
- `prompt_content`: プロンプト定義から取得したシステムプロンプト

**重要**: `node_id`と`agent_definition_id`の使い分け：
- `node_id`: グラフ内での位置を識別（例: code_generation_a、code_generation_b）。ExecutionEnvironmentManagerへの環境割り当てに使用
- `agent_definition_id`: エージェントの定義を識別（例: code_generation_fast、code_generation_standard）。ワークフローコンテキストの`execution_results`辞書のキーとして使用

**共通メソッド**:
- `handle(self, msg, ctx: WorkflowContext)`: エージェント定義に従ってLLMを呼び出し、結果をコンテキストに保存する
- `get_chat_history()`: 会話履歴を取得する
- `get_context(keys)`: 指定キーのワークフローコンテキスト値を取得する
- `store_result(output_keys, result)`: 指定キーにエージェント実行結果を保存する
- `invoke_mcp_tool(tool_name, params)`: 設定で許可されたMCPツールを呼び出す
- `get_environment_id()`: `env_ref`の値に応じて環境IDを返す。"plan"の場合はコンテキストの`plan_environment_id`を返す。"1"/"2"/"3"の場合はコンテキストの`branch_envs[N]["env_id"]`を返す。省略の場合はNoneを返す。環境自体は同一分岐内のExecEnvSetupExecutorが事前作成済みみ
- `report_progress(phase, message, details)`: 進捗状況をMRコメントとして投稿する（内部でProgressReporterを使用）

**ロール別の処理内容**:
- **planning**: コンテキスト取得（`task_mr_iid`、`plan_environment_id`含む）→plan環境IDをコンテキストの`plan_environment_id`から取得→進捗報告（開始）→plan環境のtext_editor MCPでclone済みリポジトリのコードを参照→LLM呼び出し（プランニング）→進捗報告（LLM応答）→Todoリスト作成→進捗報告（計画完了）→コンテキスト保存
- **reflection**: プラン取得→進捗報告（開始）→LLM呼び出し（検証）→進捗報告（LLM応答）→改善判定→進捗報告（検証完了）→コンテキスト保存
- **execution**: プラン取得→`get_environment_id()`で`branch_envs[1]["env_id"]`から環境ID取得→進捗報告（開始）→LLM呼び出し（実装/生成）→進捗報告（LLM応答）→ファイル操作（MCPツール）→git操作→進捗報告（実行完了）→コンテキスト保存
- **review**: MR差分取得→`get_environment_id()`で`branch_envs[1]`から環境ID取得→進捗報告（開始）→LLM呼び出し（レビュー）→進捗報告（LLM応答）→コメント生成→進捗報告（レビュー完了）→コンテキスト保存

**進捗報告の実装方針**:

各エージェントは実行の各イベントで`report_progress()`メソッドを呼び出し、進捗状況をMRコメントとして投稿する。表示ラベルは`role`ではなく`agent_definition_id`から生成するため、ユーザーがグラフに新しいノード（例: セキュリティ検証ノード）を追加した場合でも、`agent_definition_id`をそのままラベルとして使用できる。具体的な呼び出しタイミング：

1. **処理開始時**: ワークフローコンテキストから`task_mr_iid`を取得し、`report_progress(event="start", agent_definition_id=self.agent_definition_id, node_id=self.node_id, details=details)`を呼び出す
2. **LLM応答後**: LLM呼び出しが完了したら、`report_progress(event="llm_response", agent_definition_id=self.agent_definition_id, node_id=self.node_id, details={"summary": response_summary})`を呼び出す
3. **処理完了時**: ロール別の後処理が完了したら、`report_progress(event="complete", agent_definition_id=self.agent_definition_id, node_id=self.node_id, details=details)`を呼び出す

ProgressReporterは`agent_definition_id`を表示ラベルとして使用し、`format_progress_comment()`でMarkdown形式のコメントを生成してGitLab APIを介してMRに投稿する。`role`はProgressReporterに渡さない。

**ワークフローコンテキストへの並列書き込み対応**:

並列実行時に複数のエージェントが同時に`execution_results`辞書へ書き込む場合、Agent FrameworkのBSP（Bulk Synchronous Parallel）モデルによりデータ競合は発生しない。具体的な実装方針：

1. **ConfigurableAgentの書き込み処理**:
   - 実行エージェントは環境ID取得後、`execution_results`辞書の該当キー（`agent_definition_id`）のみを更新
   - 辞書全体を読み取り→更新→書き戻しはせず、キー単位で更新
   - `ctx.set_state(key, value)`（同期）で安全に状態を更新する

2. **BSPモデルによる安全性保証**:
   - Agent FrameworkのBSPモデルでは、同一スーパーステップ内で並列実行が行われ、スーパーステップ間でのデータ競合は発生しない
   - `WorkflowContext`は`ctx.get_state(key)`（同期）で状態を読み出し、`ctx.set_state(key, value)`（同期）で安全に状態を更新できる
   - 本システムは適切なAPIを呼び出すことで、並列安全性をフレームワークに委譲

**ツール登録**:
- エージェント定義の`mcp_servers`フィールドに基づき、`AgentFactory`がツールリストに動的に登録する
- 登録可能なサーバー: `text_editor`（実MCPサーバー）、`command_executor`（実MCPサーバー）、`todo_list`（仮想MCPサーバー。`create_todo_list` / `get_todo_list` / `update_todo_status` の3ツールを内包）。`mcp_server_configs` 設定で実MCPサーバーを追加可能

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

### 4.3.2 エージェントノード一覧

グラフ内の各ノードは`ConfigurableAgent`クラス（定義ファイルで設定可能）または`BaseExecutor`サブクラス（固定実装）で実装される。

#### 固定実装のExecutor群

定義ファイルで定義されず、フレームワークに組み込まれた固定実装のExecutorは以下の通り。

##### User Resolver Executor

**Agent Frameworkクラス**: `Executor`

**責務**: メールアドレスからユーザー設定を取得し、ワークフロー内で利用可能にする

**実装方法**:
- `Executor`クラスを継承し、`@MessageHandler`デコレータでメッセージハンドラを定義する
- User Config APIへのHTTPリクエストを実行する
- 取得したOpenAI APIキーをワークフローコンテキストに保存する（`ctx.set_state()`）

**処理フロー**:
1. ワークフローからメールアドレスを受け取る
2. User Config APIに問い合わせる (GET /api/v1/config/{email})
3. ユーザーが未登録の場合、例外をスローしてワークフローを停止する
4. OpenAI APIキーを復号化してワークフローコンテキストに保存する
5. 後続のExecutor/AgentがこのOpenAI APIキーを使用してLLMにアクセスする

**注**: GitLab PATはシステム全体で1つのbot用トークンを使用するため、ユーザーごとには管理しない。環境変数`GITLAB_PAT`で設定する。

##### Plan Environment Setup Executor

**Agent Frameworkクラス**: `Executor`

**責務**: ワークフロー開始前（グラフ実行前）にpython固定のplan環境を1つ作成し、リポジトリをcloneする

**処理フロー**:
1. configから`plan_environment_name`（デフォルト: `"python"`）を取得
2. ワークフローコンテキストから`task_mr_iid`とリポジトリURLを取得
3. ExecutionEnvironmentManager.prepare_plan_environment(environment_name=plan_environment_name, mr_iid=MR IID)を呼び出し、plan環境を1つ作成
4. 返された環境IDをワークフローコンテキストの`plan_environment_id`に保存
5. 作成した環境でリポジトリをclone（ExecutionEnvironmentManager.clone_repository()を使用）
6. plan環境の準備完了をワークフローコンテキストに記録

##### Exec Environment Setup Executor

**Agent Frameworkクラス**: `Executor`

**責務**: 各タスク分岐内のplanning完了後にグラフノードとして実行し、`selected_environment`を参照してノード設定の`env_count`数分の実行環境を作成する

**処理フロー**:
1. ワークフローコンテキストから`task_mr_iid`を取得
2. ノード自身の設定から`env_count`を取得（作成する実行環境の数）
3. ワークフローコンテキストから`selected_environment`（task_classifierが決定した環境名）を取得
4. ExecutionEnvironmentManager.prepare_environments(count=env_count, environment_name=選択された環境名, mr_iid=MR IID, node_id=自ノードID)を呼び出し
5. 返された環境IDリストを確認（各環境IDは`codeagent-{environment_name}-mr{mr_iid}-{自ノードID}-{N}`形式）
6. `branch_envs: {1: {"env_id": env_id_1, "branch": branch_1}, 2: {"env_id": env_id_2, "branch": branch_2}, ...}`をワークフローコンテキストに保存
7. 各実行エージェントがget_environment_id()を呼び出して`branch_envs`から環境IDを取得する

#### 定義ファイルで設定可能なエージェントノード群

以下のエージェントノードは`ConfigurableAgent`として実装され、エージェント定義ファイル・プロンプト定義ファイルで完全にカスタマイズ可能。

**主要なエージェントノード**:
- Task Classifier Agent（タスク分類）
- Planning Agent群（code_generation_planning, bug_fix_planning, test_creation_planning, documentation_planning）
- Plan Reflection Agent（プラン検証）
- Execution Agent群（code_generation, bug_fix, documentation, test_creation）
- Test Execution & Evaluation Agent（テスト実行・評価）
- Review Agent群（code_review, documentation_review）

**注**: 上記の各ノードの**詳細な処理フロー、エージェント定義設定、利用可能なツール、出力形式、エラーハンドリング**については[AGENT_DEFINITION_SPEC.md](AGENT_DEFINITION_SPEC.md)のセクション7を参照。プロンプト詳細は[PROMPTS.md](PROMPTS.md)および各プロンプト定義ファイルを参照。

---

### 4.4 定義ファイル管理

グラフ・エージェント・プロンプトの各定義はJSON形式で`workflow_definitions`テーブルの3つのJSONBカラムに1セットとして保存・管理される。システムが複数のプリセットを提供し、ユーザーがプリセットを選択したうえで独自にカスタマイズすることができる。各定義の詳細設計は以下のファイルを参照する。

- **グラフ定義ファイル詳細設計**: [GRAPH_DEFINITION_SPEC.md](GRAPH_DEFINITION_SPEC.md)
- **エージェント定義ファイル詳細設計**: [AGENT_DEFINITION_SPEC.md](AGENT_DEFINITION_SPEC.md)
- **プロンプト定義ファイル詳細設計**: [PROMPT_DEFINITION_SPEC.md](PROMPT_DEFINITION_SPEC.md)
- **デフォルトプロンプト定義**: [PROMPTS.md](PROMPTS.md)

**システムプリセット（standard_mr_processing）の定義ファイル例**:
- [グラフ定義](definitions/standard_mr_processing_graph.json)
- [エージェント定義](definitions/standard_mr_processing_agents.json)
- [プロンプト定義](definitions/standard_mr_processing_prompts.json)

#### 4.4.1 定義ファイルの関係

```mermaid
flowchart LR
    subgraph DBレコード["workflow_definitionsテーブル（1レコード = 1セット）"]
        G[graph_definition JSONB<br/>フロー・ノード・エッジ定義]
        A[agent_definition JSONB<br/>各ノードの設定・データ定義]
        P[prompt_definition JSONB<br/>システムプロンプト・LLMパラメータ]
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

#### 4.4.2 システムプリセットの初期登録

システムプリセット（`is_preset=true`）はDBマイグレーション（初期データ投入スクリプト）によって`workflow_definitions`テーブルに登録される。マイグレーション実行時に以下の2プリセットが存在しない場合に挿入する。

- `standard_mr_processing`: 標準MR処理（コード生成・バグ修正・テスト作成・ドキュメント生成の4タスク対応）
  - [グラフ定義JSON](definitions/standard_mr_processing_graph.json)
  - [エージェント定義JSON](definitions/standard_mr_processing_agents.json)
  - [プロンプト定義JSON](definitions/standard_mr_processing_prompts.json)
- `multi_codegen_mr_processing`: 複数コード生成並列実行（3種類のモデル・温度設定で並列実行し、レビュー時に自動選択）
  - グラフ定義: 標準と同じグラフに並列実行ノードを追加
  - エージェント定義: [AGENT_DEFINITION_SPEC.md セクション4.2](AGENT_DEFINITION_SPEC.md#42-複数コード生成並列エージェント定義multi_codegen_mr_processing)参照
  - プロンプト定義: [PROMPT_DEFINITION_SPEC.md セクション4.2](PROMPT_DEFINITION_SPEC.md#42-複数コード生成並列プロンプト定義multi_codegen_mr_processing)参照
  - 各エージェントは専用ブランチ（例: `feature/login-code-gen-1`, `feature/login-code-gen-2`, `feature/login-code-gen-3`）で作業し、レビューエージェントが最良のブランチを自動選択してマージ

システムプリセットは`is_preset=true`のレコードとして登録され、ユーザーによる更新・削除はAPIで拒否される。

#### 4.4.3 ユーザーカスタマイズワークフローの管理

ユーザーは以下のフローで独自のワークフロー定義を作成・管理できる。

```mermaid
flowchart TD
    A[ユーザーがプリセット一覧を確認<br/>GET workflow_definitions] --> B[ベースにするプリセットを取得<br/>GET workflow_definitions/ID]
    B --> C[JSONを編集してカスタム定義を作成<br/>POST workflow_definitions<br/>ユーザー作成フラグを設定]
    C --> D[カスタム定義をワークフローとして選択<br/>PUT users/USER_ID/workflow_setting]
    D --> E[以降のタスクでカスタム定義が使用される]
    C --> F[カスタム定義を更新<br/>PUT workflow_definitions/ID]
    C --> G[カスタム定義を削除<br/>DELETE workflow_definitions/ID]
```

カスタムワークフロー定義は`is_preset=false`・`created_by=user_id`として保存され、作成したユーザーのみが更新・削除できる。`workflow_definition_id`を削除する前にそれを参照している`user_workflow_settings`レコードを確認し、使用中の場合はシステムデフォルトへフォールバックする。

#### 4.4.4 DefinitionLoader

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

**バリデーション詳細仕様**:

##### validate_graph_definition(graph_def)

グラフ定義の構造的整合性を検証する。以下のチェックを実施する:

1. **必須フィールドの存在確認**:
   - `version`, `name`, `entry_node`, `nodes`, `edges`がすべて存在するか
   - 各ノードに`id`, `type`が存在するか
   - 各エッジに`from`が存在するか（`to`はnull許容）

2. **エントリノードの存在確認**:
   - `entry_node`に指定されたIDが`nodes`配列内に存在するか

3. **エッジの参照整合性チェック**:
   - すべてのエッジの`from`が`nodes`配列内に存在するノードIDを参照しているか
   - すべてのエッジの`to`がnullまたは`nodes`配列内に存在するノードIDを参照しているか
   - `to: null`のエッジはワークフロー終了を意味する

4. **孤立ノードのチェック**:
   - `entry_node`から到達できないノードが存在しないか
   - BFS（幅優先探索）で到達可能性を確認する

5. **終了ノードの存在確認**:
   - グラフ内に少なくとも1つの`to: null`のエッジが存在するか
   - 存在しない場合はワークフローが正常終了できないため、`DefinitionValidationError`をスロー
   - 理由: 構造的に終了条件が存在しないグラフは設計ミスを示す

6. **条件式の構文チェック**:
   - `condition`フィールドが存在する場合、その条件式が有効なPython式として評価可能か
   - 基本チェック: `eval(condition, {"context": {}, "config": {}})`で構文エラーが発生しないか

7. **env_refバリデーション**:
   - 各ノードの`env_ref`値が有効か（"plan"、"1"〜"N"の整数文字列、または省略）
   - `executor_class: "ExecEnvSetupExecutor"`のノードは`env_count`フィールドが必須でまた整数値であるか
   - 同一分岐内で`env_ref: "N"`を持つノードの最大N値が同分岐のExecEnvSetupExecutorの`env_count`以下であるか

**戻り値**: 検証成功時はTrue。検証失敗時は`DefinitionValidationError`例外をスローする。

##### validate_agent_definition(agent_def, graph_def)

エージェント定義がグラフ定義と整合しているか検証する。以下のチェックを実施する:

1. **必須フィールドの存在確認**:
   - `version`, `agents`が存在するか
   - 各エージェントに`id`, `role`, `input_keys`, `output_keys`, `prompt_id`が存在するか（`mcp_servers`は任意フィールドのため省略可）

2. **グラフ定義との整合性**:
   - グラフ定義の各ノードで参照される`agent_definition_id`に対応するエージェント定義が`agents`配列内に存在するか
   - ノードタイプが`"agent"`の場合、対応するエージェント定義が必須

3. **roleの有効値チェック**:
   - 各エージェントの`role`が"planning"、"reflection"、"execution"、"review"のいずれかであるか
   - `role`は処理ロジック（環境モード決定・ツール使用可否の制御）のみに使用する。MRへの表示ラベルは`agent_definition_id`を使用するため、新規ノード追加時でも`role`の有効値を変更する必要はない

4. **mcp_serversの有効値チェック**:
   - 各エージェントの`mcp_servers`配列内のサーバー名がすべてシステムに登録済みの値に含まれるか
   - 組み込みの指定可能値: `text_editor`, `command_executor`, `todo_list`（仮想MCPサーバー）
   - `mcp_server_configs` 設定に登録された実MCPサーバー名も追加で指定可能

5. **input_keysとoutput_keysの一貫性**:
   - 同じエージェント内で`input_keys`と`output_keys`に同じキー名が含まれていないか
   - エージェントは入力か出力のどちらか一方のみでキーを使用するべき

6. **output_keysの一意性（並列実行対応）**:
   - 単一エージェントも並列エージェントも同じ辞書型キー（`branch_envs`、`execution_results`）への書き込みは複数エージェントで共有可能
   - 各エージェントは自身のエージェント定義IDをキーとして辞書に書き込む

7. **mcp_serversとroleの整合性**:
   - `env_ref`値が有効か（"plan"、"1"〜"N"の整数文字列、または省略）
   - "planning"ロールは`env_ref: "plan"`または省略のみ許容（planningエージェントはplan環境またはDocker環境不要のいずれかで動作する）
   - "reflection"ロールの`env_ref`は省略・`"plan"`・整数文字列いずれも許容（plan_reflectionは`"plan"`、実行リフレクションエージェントは実行環境の`env_ref`を使用する）
   - "execution"ロールは`env_ref: "1"`以上の整数文字列を指定する（新規実行環境が必要）
   - "review"ロールは`env_ref: "1"`以上の整数文字列を指定する（実行エージェントと同じ実行環境を共有）

8. **コンテキストキーの連続性**:
   - エージェントの`output_keys`が後続ノードの`input_keys`として参照されているか
   - グラフのエッジ関係とエージェントの入出力キーが論理的に整合しているか

**戻り値**: 検証成功時はTrue。検証失敗時は`DefinitionValidationError`例外をスローする。

##### validate_prompt_definition(prompt_def, agent_def)

プロンプト定義がエージェント定義と整合しているか検証する。以下のチェックを実施する:

1. **必須フィールドの存在確認**:
   - `version`, `prompts`が存在するか
   - 各プロンプトに`prompt_id`, `role`, `content`が存在するか

2. **prompt_idの整合性**:
   - エージェント定義の各エージェントで参照される`prompt_id`に対応するプロンプト定義が`prompts`配列内に存在するか

3. **roleの一致**:
   - プロンプト定義の`role`とエージェント定義の`role`が一致しているか
   - 例: エージェント定義で`role: "planning"`の場合、対応するプロンプト定義も`role: "planning"`であるべき

4. **プレースホルダーの妥当性**:
   - プロンプト`content`内のプレースホルダー（例: `{task_description}`, `{related_files}`）がエージェントの`input_keys`に対応しているか
   - 未定義のプレースホルダーが使用されていないか

5. **未使用プロンプトの警告**:
   - `prompts`配列内にあるが、どのエージェントからも参照されていないプロンプト定義が存在する場合、警告を出力する（エラーではない）

**戻り値**: 検証成功時はTrue。検証失敗時は`DefinitionValidationError`例外をスローする。

---

#### 4.4.5 WorkflowFactory（更新）

`WorkflowFactory`はグラフ定義ファイルに基づいてワークフローを動的に構築する。以前のタスク種別別ハードコードされたメソッド（`create_code_generation_workflow`等）は廃止し、定義ファイルからの動的構築に置き換える。

**更新後の主要メソッド**:
- `create_workflow_from_definition(user_id, task_context)`: ユーザーのワークフロー定義を読み込み、グラフ定義に従ってAgent FrameworkのWorkflowを生成する
- `_build_nodes(graph_def, agent_def, prompt_def, user_id)`: グラフ定義の各ノードに対して`ConfigurableAgent`インスタンスまたはAgent FrameworkのExecutorを生成する
- `_setup_plan_environment()`: ワークフロー開始前にpython固定のplan環境を1つ作成しリポジトリをclone、`plan_environment_id`をコンテキストに保存する

**複数環境のサポート**:
グラフ定義でノードごとに`env_ref`を設定することで、分岐ごとに独立した実行環境を準備する。ワークフロー開始前にplan環境（python固定・1つ）を作成し、各タスク分岐のplanning完了後にその分岐専用の`exec_env_setup_*`ノードが実行環境を`env_count`数分作成することで、複数のコーディングエージェントノードが独立した環境で並列実行可能になる。

**環境準備と割り当ての詳細**:
1. **plan環境の事前準備**: ワークフロー開始前に`PlanEnvSetupExecutor`がpython固定のplan環境を1つ作成しリポジトリをcloneする。環境IDはコンテキストの`plan_environment_id`に保存される。`env_ref: "plan"`のplanningエージェント（task_classifierを含む）はすべてこの環境を共有して使用する
2. **実行環境の分岐別作成**: 各タスク分岐内の`exec_env_setup_*`ノード（ExecEnvSetupExecutor）がplanning完了後に実行され、ノード設定の`env_count`数分の実行環境を作成する。作成された環境情報は`branch_envs: {1: {"env_id": "...", "branch": "..."}, ...}`としてコンテキストに保存される。`env_count = 1`（standard）の場合はサブブランチを作成せず`branch`には`original_branch`をそのまま格納し、`env_count ≥ 2`（multi）の場合はnode_id由来のサフィックスを付与したサブブランチを作成する
3. **環境プール管理**: ExecutionEnvironmentManager が環境プールを管理。`env_ref: "1"/"2"/"3"`のノードは`branch_envs`コンテキストから対応する番号の環境IDを取得して使用する
4. **並列実行時の分離**: 並列に実行される複数のコード生成ノード（例: code_generation_a, code_generation_b, code_generation_c）は、それぞれ独立したDocker環境を使用し、相互に干渉しない
5. **環境のクリーンアップ**: ワークフロー完了時または異常終了時に、plan環境・実行環境すべてを自動的にクリーンアップする

詳細設計は[セクション8.7](#87-実行環境管理executionenvironmentmanager)を参照。

**例**: `multi_codegen_mr_processing` プリセットでは、`exec_env_setup_code_gen`ノードが`env_count: 3`を持ち、3つの並列コード生成ノード（code_generation_a、code_generation_b、code_generation_c）がそれぞれ`branch_envs`から独自の環境を取得して実行する。

### 4.5 ブランチ管理

すべてのワークフロープリセット（`standard_mr_processing`・`multi_codegen_mr_processing`）で共通のブランチ管理ルールを適用する。ブランチ作成の責務は`ExecEnvSetupExecutor`が担い、`env_count`の値に応じて動作を切り替える。

#### 4.5.1 ブランチ作成戦略

**ExecEnvSetupExecutorによるブランチ作成**:

`env_count`の値に基づいて以下の通り動作する。

- **env_count = 1（standard）**: サブブランチは作成しない。`original_branch`をそのまま作業ブランチとして使用する。
- **env_count ≥ 2（multi）**: サブブランチを`env_count`本作成する。

**ブランチ名の自動生成ルール（env_count ≥ 2 の場合）**:

ノードIDから以下の変換を行い、サフィックスを導出する。

1. `exec_env_setup_` プレフィックスを除去
2. `_` を `-` に変換
3. 末尾に `-{N}`（Nは1始まりの環境番号）を付与

例：ノードID `exec_env_setup_code_gen`、`original_branch = feature/login`、`env_count = 3` の場合：

```
feature/login-code-gen-1
feature/login-code-gen-2
feature/login-code-gen-3
```

**branch_envsへの格納**:

`ExecEnvSetupExecutor`はブランチ情報を含む辞書を`branch_envs`コンテキストキーに保存する。

- キー: 1始まりの環境番号（整数）
- 値: `{env_id: "...", branch: "..."}` 形式の辞書

`env_count = 1` の場合でも同一形式で保存し、`branch`フィールドには`original_branch`をそのまま格納する。

**assigned_branchの設定**:

`AgentFactory`がエージェントノードを生成する際に、グラフ定義の`env_ref`フィールドと`branch_envs`コンテキストを参照し、対応する`branch`を`task_context.assigned_branch`に設定する。これにより、すべてのエージェントが`task_context.assigned_branch`から自身の作業ブランチ名を取得できる（standard/multiの区別なし）。

#### 4.5.2 各エージェントの作業フロー

すべての実行エージェント（standard/multi共通）は以下のフローで作業する：

1. **ブランチの取得**: `task_context.assigned_branch`から自身の担当ブランチ名を取得
2. **リポジトリのclone**: Docker環境内で`command-executor` MCPを使用してリポジトリをclone
3. **ブランチのcheckout**: `git checkout {assigned_branch}`で担当ブランチに切り替え
4. **実装作業**: `text-editor` MCPでファイル生成/修正
5. **Git操作**: エージェントの判断でcommit・pushを実行（commit単位はエージェントに委ねる）

**注意**:
- commit操作のタイミングと単位は各エージェントの判断に任せる（仕様に明示しない）
- 各エージェントは独立したDocker環境で動作するため競合は発生しない
- env_count = 1（standard）の場合、`assigned_branch`は`original_branch`と同じ値となる

#### 4.5.3 レビューと自動選択（multi_codegen_mr_processing専用）

**レビューフェーズ**:

1. **複数の成果物を一括レビュー**: `code_review`エージェント（`code_review_multi`プロンプト使用）が以下を実行
   - `execution_results`辞書から複数の実行結果を比較
   - コード品質、アーキテクチャ、実装の適切性を評価
   - テスト結果、パフォーマンス、保守性を比較

2. **最良のブランチを自動選択**: レビュー結果に基づいて最良のブランチを決定
   - 評価基準: コード品質スコア、テスト成功率、実装の適切性
   - 選択結果を`selected_implementation`として出力
   - 選択理由をGitLab MRにコメント投稿

3. **マージ処理**:
   - 選択されたブランチ（例: `feature/login-code-gen-2`）を元MRブランチ（`feature/login`）にマージ
   - `GitLabClient.merge_branch(source=selected_branch, target=original_branch)`を使用
   - マージコミットメッセージ: "Merge {selected_branch}: {selection_reason}"

#### 4.5.4 ブランチの保持（multi_codegen_mr_processing専用）

**すべてのサブブランチを保持**:
- 選択されなかったサブブランチもGitLab上に残す
- ユーザーは後からGitLab UI上で各ブランチを確認・比較可能
- 自動削除はしない（ユーザーが手動で削除可能）

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

#### 5.0.3 IssueToMRConverter（Agent Framework Workflow実装）

**実装方法**:
Agent FrameworkのProcess Framework (Workflow/Executor)を使用してワークフロー管理を実装する。[clients/gitlab_client.py](https://github.com/notfolder/coding_agent/blob/main/clients/gitlab_client.py)はそのまま流用する。

| コンポーネント | 参照元 | 役割 | 実装方法 |
|----------------|-----------|------|---------|
| **IssueToMRConverter** | `handlers/issue_to_mr_converter.py` | Issue→MR変換のメインクラス | Agent Framework Workflowとして定義 |
| **BranchNameGenerator** | `handlers/issue_to_mr_converter.py` | LLMを使用したブランチ名生成 | [`Agent`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_agents.py)で実装 |
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

**標準MR処理フローの詳細については [STANDARD_MR_PROCESSING_FLOW.md](STANDARD_MR_PROCESSING_FLOW.md) を参照してください。**

以下のトピックは[STANDARD_MR_PROCESSING_FLOW.md](STANDARD_MR_PROCESSING_FLOW.md)で詳細に説明されています：
- エージェント構成と役割
- MR処理の全体フロー
- 各フェーズの詳細（計画前情報収集、計画、実行、レビュー、テスト実行・評価、リフレクション、差分計画パターン）
- タスク種別別詳細フロー（コード生成、バグ修正、ドキュメント生成、テスト作成）
- 仕様ファイル管理（命名規則、テンプレート、自動レビュープロセス）

---

### 5.1 オブジェクト構造設計

#### 5.1.1 概要

本システムは、Agent Frameworkの標準機能を活用しながら、独自のオブジェクト管理を実装する。以下では、各オブジェクトの保持関係とライフサイクル管理を明示する。

**主要な設計パターン**:
1. **Provider方式によるコンテキスト管理**: `PostgreSqlChatHistoryProvider`、`PlanningContextProvider`、`ToolResultContextProvider`を使用し、Agent Framework [BaseHistoryProvider/BaseContextProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)パターンでコンテキストを永続化する
2. **Filters方式によるトークン統計**: `TokenUsageMiddleware`を使用し、すべての[`Agent`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_agents.py)呼び出しを自動的にインターセプトしてトークン使用量を記録する
3. **定義ベースのワークフロー構築**: ワークフロー定義ファイル（グラフ定義・エージェント定義・プロンプト定義）に基づいてWorkflowを動的に生成する。ユーザーはシステムプリセットをベースに独自のワークフロー定義を作成し、プロンプト定義をカスタマイズ可能（標準MR処理では13エージェント対応）
4. **Factory方式によるオブジェクト生成**: `AgentFactory`、`MCPClientFactory`を使用し、定義ファイルに基づいて適切なエージェントとコンポーネントを生成する
5. **Strategy方式によるタスク処理**: `TaskStrategyFactory`を使用し、Issue→MR変換判定などのタスク固有の処理戦略を決定する
6. **共有リソースの再利用**: `ExecutionEnvironmentManager`、`MCPClientRegistry`、`ContextStorageManager`等を複数タスク処理で再利用し、リソース効率を最適化する

#### 5.1.2 オブジェクト構造図

システム全体のオブジェクト構造とコンポーネント間の関係を以下に示す。この図はドキュメント内に登場するすべての主要なオブジェクトを省略なく表現している。

```mermaid
graph TB
    subgraph "メッセージング層"
        Producer[Producer<br/>タスク検出・キューイング]
        RabbitMQ[(RabbitMQ<br/>メッセージキュー)]
        Consumer[Consumer<br/>タスク処理実行]
        TaskHandler[TaskHandler<br/>タスク処理分岐]
    end
    
    subgraph "Issue→MR変換層"
        IssueToMRConverter[IssueToMRConverter<br/>Issue→MR変換ワークフロー]
        BranchNameGenerator[BranchNameGenerator<br/>LLMでブランチ名生成]
        ContentTransferManager[ContentTransferManager<br/>コンテンツ転記]
    end
    
    subgraph "戦略判定層"
        TaskStrategyFactory[TaskStrategyFactory<br/>タスク処理戦略決定]
        IssueToMRStrategy[IssueToMRConversionStrategy<br/>Issue→MR変換戦略]
        IssueOnlyStrategy[IssueOnlyStrategy<br/>Issueのみ戦略]
        MRStrategy[MergeRequestStrategy<br/>MR処理戦略]
    end
    
    subgraph "ワークフロー管理層"
        WorkflowFactory[WorkflowFactory<br/>グラフ定義解析<br/>Workflow生成<br/>環境準備]
        DefinitionLoader[DefinitionLoader<br/>定義ファイル読み込み]
        Workflow[Agent Framework Workflow<br/>ワークフロー実行エンジン]
        WorkflowBuilder[WorkflowBuilder<br/>Workflowオブジェクト構築]
    end
    
    subgraph "Executor層"
        ExecutorFactory[ExecutorFactory<br/>Executor生成]
        UserResolverExec[UserResolverExecutor<br/>ユーザー情報解決]
        ContentTransferExec[ContentTransferExecutor<br/>コンテンツ転記]
        PlanEnvSetupExec[PlanEnvSetupExecutor<br/>plan環境セットアップ]
        ExecEnvSetupExec[ExecEnvSetupExecutor<br/>実行環境セットアップ]
        BranchMergeExec[BranchMergeExecutor<br/>ブランチマージ]
    end
    
    subgraph "エージェント管理層"
        AgentFactory[AgentFactory<br/>ConfigurableAgent生成<br/>プロンプト適用<br/>ツール登録]
        PrePlanningMgr[PrePlanningManager<br/>計画前情報収集<br/>環境選択]
        EnvironmentAnalyzer[EnvironmentAnalyzer<br/>環境ファイル検出]
    end
    
    subgraph "エージェント実装層"
        Agent1[ConfigurableAgent<br/>計画エージェント]
        Agent2[ConfigurableAgent<br/>コード生成エージェント]
        Agent3[ConfigurableAgent<br/>レビューエージェント]
        Agent4[ConfigurableAgent<br/>テストエージェント]
        Agent5[ConfigurableAgent<br/>バグ修正エージェント]
        Agent6[ConfigurableAgent<br/>差分計画エージェント]
        Agent7[ConfigurableAgent<br/>リフレクションエージェント]
        AgentN[ConfigurableAgent<br/>その他エージェント]
        LearningAgent[GuidelineLearningAgent<br/>学習エージェント<br/>GitLabClient保持]
    end
    
    subgraph "MCP/ツール管理層"
        MCPClientFactory[MCPClientFactory<br/>MCPクライアント生成<br/>ツール登録<br/>（エージェントごとに新規生成）]
    end
    
    subgraph "MCPサーバー層"
        GitLabMCP[GitLab MCP<br/>Issue/MR/コメント操作]
        EditorMCP[text-editor MCP<br/>ファイル編集]
        CommandMCP[command-executor MCP<br/>コマンド実行]
    end
    
    subgraph "実行環境管理層"
        EnvManager[ExecutionEnvironmentManager<br/>Docker環境管理<br/>環境ID生成<br/>環境プール管理<br/>環境割り当て]
        Docker[Docker Containers<br/>python/miniforge/node]
    end
    
    subgraph "コンテキスト管理層"
        ContextManager[ContextStorageManager<br/>永続化管理]
        ChatHistoryProvider[PostgreSqlChatHistoryProvider<br/>会話履歴永続化]
        PlanningProvider[PlanningContextProvider<br/>プランニング履歴永続化]
        ToolResultProvider[ToolResultContextProvider<br/>ツール実行結果永続化]
        InheritanceProvider[TaskInheritanceContextProvider<br/>過去タスク継承]
        CompressionService[ContextCompressionService<br/>コンテキスト圧縮]
    end
    
    subgraph "Middleware層"
        TokenMiddleware[TokenUsageMiddleware<br/>トークン統計・記録]
        ErrorMiddleware[ErrorHandlingMiddleware<br/>エラー処理・リトライ]
        CommentMiddleware[CommentWatchMiddleware<br/>コメント監視<br/>差分計画]
        MetricsCollector[MetricsCollector<br/>メトリクス収集・送信]
    end
    
    subgraph "外部クライアント層"
        GitLabClient[GitLabClient<br/>GitLab API操作]
        UserConfigClient[UserConfigClient<br/>ユーザー設定取得]
    end
    
    subgraph "その他コンポーネント"
        TodoManager[TodoManager<br/>Todo管理]
        ConfigManager[ConfigManager<br/>設定管理]
        ProgressReporter[ProgressReporter<br/>進捗報告]
    end
    
    subgraph "データベース層"
        PostgreSQL[(PostgreSQL<br/>tasks/users/user_configs<br/>context_messages<br/>token_usage<br/>workflow_definitions等)]
        FileStorage[(File Storage<br/>tool_results)]
    end
    
    %% メッセージング層の接続
    Producer -->|タスク送信| RabbitMQ
    RabbitMQ -->|タスク受信| Consumer
    Consumer -->|タスク処理分岐| TaskHandler
    
    %% 戦略判定
    TaskHandler -->|戦略判定| TaskStrategyFactory
    TaskStrategyFactory -->|Issue→MR変換必要| IssueToMRStrategy
    TaskStrategyFactory -->|Issue処理のみ| IssueOnlyStrategy
    TaskStrategyFactory -->|MR処理| MRStrategy
    
    %% Issue→MR変換
    IssueToMRStrategy -->|変換実行| IssueToMRConverter
    IssueToMRConverter -->|ブランチ名生成| BranchNameGenerator
    IssueToMRConverter -->|コンテンツ転記| ContentTransferManager
    IssueToMRConverter -->|GitLab操作| GitLabClient
    
    %% ワークフロー生成
    TaskHandler -->|ワークフロー生成| WorkflowFactory
    WorkflowFactory -->|定義読み込み| DefinitionLoader
    WorkflowFactory -->|Factory保持| ExecutorFactory
    WorkflowFactory -->|Factory保持| AgentFactory
    WorkflowFactory -->|mcp_server_configs渡し| AgentFactory
    WorkflowFactory -->|Manager保持| EnvManager
    WorkflowFactory -->|Manager保持| ContextManager
    WorkflowFactory -->|Manager保持| TodoManager
    WorkflowFactory -->|Reporter保持| ProgressReporter
    WorkflowFactory -->|Middleware登録| TokenMiddleware
    WorkflowFactory -->|Middleware登録| ErrorMiddleware
    WorkflowFactory -->|Middleware登録| CommentMiddleware
    WorkflowFactory -->|Builder使用| WorkflowBuilder
    WorkflowBuilder -->|Workflow生成| Workflow
    
    %% Executor生成
    ExecutorFactory -->|Client参照| UserConfigClient
    ExecutorFactory -->|Client参照| GitLabClient
    ExecutorFactory -->|Manager参照| EnvManager
    ExecutorFactory -->|Executor生成| UserResolverExec
    ExecutorFactory -->|Executor生成| ContentTransferExec
    ExecutorFactory -->|Executor生成| EnvironmentSetupExec
    ExecutorFactory -->|Executor生成| BranchMergeExec
    
    %% Workflow実行
    Workflow -->|Executor実行| UserResolverExec
    Workflow -->|Executor実行| ContentTransferExec
    Workflow -->|Executor実行| EnvironmentSetupExec
    Workflow -->|Executor実行| BranchMergeExec
    
    %% エージェント生成
    AgentFactory -->|Manager使用| PrePlanningMgr
    PrePlanningMgr -->|環境解析| EnvironmentAnalyzer
    AgentFactory -->|Provider登録| ChatHistoryProvider
    AgentFactory -->|Provider登録| PlanningProvider
    AgentFactory -->|Provider登録| ToolResultProvider
    AgentFactory -->|Provider登録| InheritanceProvider
    AgentFactory -->|Middleware登録| TokenMiddleware
    AgentFactory -->|Middleware登録| ErrorMiddleware
    AgentFactory -->|Agent生成| Agent1
    AgentFactory -->|Agent生成| Agent2
    AgentFactory -->|Agent生成| Agent3
    AgentFactory -->|Agent生成| Agent4
    AgentFactory -->|Agent生成| Agent5
    AgentFactory -->|Agent生成| Agent6
    AgentFactory -->|Agent生成| Agent7
    AgentFactory -->|Agent生成| AgentN
    AgentFactory -->|create_agentごとに新規生成| MCPClientFactory
    WorkflowFactory -->|学習ノード自動挿入| LearningAgent
    
    %% Workflow→Agent実行
    Workflow -->|Agent実行| Agent1
    Workflow -->|Agent実行| Agent2
    Workflow -->|Agent実行| Agent3
    Workflow -->|Agent実行| Agent4
    Workflow -->|Agent実行| Agent5
    Workflow -->|Agent実行| Agent6
    Workflow -->|Agent実行| Agent7
    Workflow -->|学習Agent実行| LearningAgent
    
    %% Agent→MCP（各エージェントは専用MCPClientFactoryインスタンスのKernel経由でツール使用）
    Agent1 -->|tools list経由でツール使用| MCPClientFactory
    Agent2 -->|tools list経由でツール使用| MCPClientFactory
    Agent3 -->|tools list経由でツール使用| MCPClientFactory
    Agent4 -->|tools list経由でツール使用| MCPClientFactory
    Agent5 -->|tools list経由でツール使用| MCPClientFactory
    Agent6 -->|tools list経由でツール使用| MCPClientFactory
    Agent7 -->|tools list経由でツール使用| MCPClientFactory
    
    %% MCP管理（ビルド時にenv_idでDockerコンテナを特定して接続）
    MCPClientFactory -->|クライアント生成| GitLabMCP
    MCPClientFactory -->|ビルド時env_id埋め込みで接続| EditorMCP
    MCPClientFactory -->|ビルド時env_id埋め込みで接続| CommandMCP
    
    %% コンテキスト管理
    ChatHistoryProvider -->|永続化| ContextManager
    PlanningProvider -->|永続化| ContextManager
    ToolResultProvider -->|永続化| ContextManager
    ToolResultProvider -->|ファイル保存| FileStorage
    InheritanceProvider -->|過去タスク検索| ContextManager
    ChatHistoryProvider -->|圧縮実行| CompressionService
    CompressionService -->|圧縮履歴保存| ContextManager
    
    %% Middleware→DB/外部
    TokenMiddleware -->|統計記録| ContextManager
    TokenMiddleware -->|メトリクス送信| MetricsCollector
    ErrorMiddleware -->|エラー記録| ContextManager
    ErrorMiddleware -->|GitLab通知| GitLabClient
    CommentMiddleware -->|コメント監視| GitLabClient
    
    %% 進捗報告
    ProgressReporter -->|GitLab通知| GitLabClient
    ProgressReporter -->|進捗記録| ContextManager
    Agent1 -->|進捗報告| ProgressReporter
    Agent2 -->|進捗報告| ProgressReporter
    Agent3 -->|進捗報告| ProgressReporter
    LearningAgent -->|進捗報告| ProgressReporter
    
    %% 学習エージェントの外部操作
    LearningAgent -->|MRコメント取得/投稿| GitLabClient
    LearningAgent -.->|PROJECT_GUIDELINES.md更新<br/>commit & push| GitLabClient
    
    %% データベース
    ContextManager -->|読み書き| PostgreSQL
    UserConfigClient -->|読み書き| PostgreSQL
    TaskHandler -->|タスク記録| PostgreSQL
    
    %% 実行環境管理
    EnvManager -->|環境作成・管理| Docker
    EnvironmentSetupExec -->|環境準備| EnvManager
    
    %% 設定管理
    WorkflowFactory -->|設定取得| ConfigManager
    TaskStrategyFactory -->|設定取得| ConfigManager
    EnvManager -->|設定取得| ConfigManager
    
    %% スタイル
    style WorkflowFactory fill:#e1f5ff
    style AgentFactory fill:#fff4e1
    style MCPClientFactory fill:#ffe1f5
    style ExecutorFactory fill:#f5e1ff
    style ContextManager fill:#f0f0f0
    style EnvManager fill:#e8f5e9
    style LearningAgent fill:#e8ffe8
    style TaskStrategyFactory fill:#ffe8e1
```

**主要コンポーネント間の関係**:
- **Producer/Consumer層**: RabbitMQ経由でタスクをやり取り
- **TaskHandler**: タスク種別を判定し、適切な処理戦略を選択
- **TaskStrategyFactory**: Issue→MR変換判定、タスク処理戦略の決定
- **IssueToMRConverter**: Issue→MR変換の専用ワークフロー（BranchNameGenerator、ContentTransferManagerを使用）
- **WorkflowFactory**: グラフ定義に基づいてWorkflowを生成し、各種Factory・Managerを保持
- **ExecutorFactory**: カスタムExecutorを生成（UserResolver、ContentTransfer、EnvironmentSetup、BranchMerge）
- **AgentFactory**: エージェント定義に基づいてAgentを生成し、Provider・Middlewareを登録
- **PrePlanningManager**: 計画前にプロジェクト環境を解析し、適切な実行環境を選択
- **EnvironmentAnalyzer**: リポジトリから環境ファイル（requirements.txt、package.json等）を検出
- **MCPClientFactory**: AgentFactory.create_agent()ごとに新規生成され、ビルド時にenv_idをMCPServerConfig.commandに埋め込んで特定のDockerコンテナへ接続し、MCPStdioToolとしてAgentのtoolsリストに登録する。内部にMCPClientRegistry（server_nameをキーとするクライアント管理辞書）を保持する
- **ContextStorageManager**: PostgreSQL経由でコンテキストを永続化
- **ExecutionEnvironmentManager**: Docker環境を複数タスクで共有管理、環境ID生成、プール管理
- **PostgreSqlChatHistoryProvider**: 会話履歴をPostgreSQLに永続化（Agent Framework標準BaseHistoryProviderを継承）
- **PlanningContextProvider**: プランニング履歴をPostgreSQLに永続化（Agent Framework標準BaseContextProviderを継承）
- **ToolResultContextProvider**: ツール実行結果をファイル+PostgreSQLに永続化（Agent Framework標準BaseContextProviderを継承）
- **TaskInheritanceContextProvider**: 同一Issue/MRの過去タスクから継承データを提供（Agent Framework標準BaseContextProviderを継承）
- **ContextCompressionService**: 会話履歴のトークン数削減（要約生成）
- **TokenUsageMiddleware**: すべてのノード実行のトークン使用量を自動記録（Agent Framework Middlewareとして実装）
- **ErrorHandlingMiddleware**: エラー分類、リトライ判定、ユーザー通知を実行（Agent Framework Middlewareとして実装）
- **CommentWatchMiddleware**: ユーザーコメント監視、差分計画パターンの実装（Agent Framework Middlewareとして実装）
- **MetricsCollector**: OpenTelemetry経由でメトリクスを送信
- **GitLabClient**: システム全体で共有するbot用PATでGitLab API操作
- **UserConfigClient**: ユーザーごとのLLM設定・APIキーを管理
- **TodoManager**: Agent FrameworkのTodo管理機能を統合
- **ConfigManager**: config.yaml設定の読み込みと管理
- **ProgressReporter**: 各フェーズでの進捗状況をMRにコメント投稿

---

## 6. 進捗報告機能

### 6.1 概要

タスクの進捗状況をMRコメントとして可視化する。**1タスクにつき1コメントを作成し、以降のすべてのイベントで同じコメントを上書き更新する**方式を採用する。コメントはMermaidフローチャート（ノードの状態を色で表現）と最新状態テキストで構成され、新規コメントの追加は行わない。

グラフ定義の`label`フィールドの値をノード名として使用するため、グラフ定義を変更して新規ノードを追加した場合でも固定の記述変更なしに対応できる。

### 6.2 報告タイミング

各イベントでWorkflowContextに保存した`progress_comment_id`を使い、既存コメントを上書き更新する。

| イベント | 内容 | 備考 |
|---------|------|------|
| **タスク全体開始時** | 全ノードをpending状態としたMermaidグラフコメントを**新規作成**する。取得したGitLab Note IDを`progress_comment_id`としてWorkflowContextに保存する | コメント作成はこの1回のみ |
| **start（ノード開始）** | 対象ノードをrunning状態に変更し、最新イベントサマリ行を更新してコメントを上書きする | |
| **llm_response（LLM応答取得）** | 最新LLM応答欄をLLM応答の先頭200文字程度で上書きする | 追記・蓄積はしない |
| **todo_changed（Todo変更）** | `create_todo_list` / `update_todo_status` / `add_todo` / `delete_todo` / `reorder_todos` 呼び出し直後にセクション③.5（Todoリスト）を更新してコメントを上書きする | `TodoManagementTool`が呈出する |
| **complete（ノード完了）** | 対象ノードをdone状態に変更し、最新イベントサマリ行を更新してコメントを上書きする | |
| **error（エラー発生）** | 対象ノードをerror状態に変更し、エラー詳細を`<details>`で付記してコメントを上書きする | |
| **タスク全体完了時** | 全ノードをdone状態に変更し、最終サマリ行を付記してコメントを上書きする | |

### 6.3 コメントフォーマット

1コメントは以下の4セクションで構成される。各イベントで該当セクションを変更し、コメント全体を再構築して上書きする。

**セクション①: Mermaidフローチャート**

コメント冒頭に`## ⚙️ タスク進捗`ヘッダーを置き、その下にMermaidフローチャートのコードブロックを配置する。ノード一覧・エッジ定義・classDef行で構成され、各ノードには現在の状態に対応するクラスが付与される。

**セクション②: 最新状態（1行テキスト）**

`**最新状態**: {絵文字} [{label}] {メッセージ} ― {timestamp}` の形式で1行出力する。イベント発生のたびに行全体を上書きする。

**セクション③: 最新LLM応答**

`**最新LLM応答**:` の見出しの下に引用形式でLLM応答テキストの先頭200文字程度を表示する。`llm_response`イベントのたびに全体を上書きする（追記・蓄積はしない）。

**セクション③.5: Todoリスト（Todoが存在する場合のみ）**

`**📋 Todoリスト**:` の見出しの下に現在のTodoリストをMarkdownのチェックボックス形式で表示する。`todo_changed`イベント（`TodoManagementTool`から呈出）のたびに全体を上書きする。Todoが1つも存在しない場合は本セクションをまるごと省略する。

**セクション④: エラー詳細（エラー時のみ）**

エラー発生時のみ`<details><summary>❌ エラー詳細</summary>...</details>`ブロックを追加する。エラー種別・メッセージ・リトライ情報を含む。

#### ノード状態と色定義

| 状態 | 説明 | Mermaid classDef |
|------|------|------------------|
| `pending` | 未実行 | `fill:#9e9e9e,color:#fff,stroke:#616161` |
| `running` | 実行中 | `fill:#ff9800,color:#fff,stroke:#e65100,stroke-width:3px` |
| `done` | 完了 | `fill:#4caf50,color:#fff,stroke:#388e3c` |
| `error` | エラー | `fill:#f44336,color:#fff,stroke:#b71c1c` |
| `skipped` | スキップ | `fill:#eeeeee,color:#9e9e9e,stroke:#bdbdbd,stroke-dasharray:4` |

#### ノード種別とMermaid構文

| ノード種別（type） | Mermaid記法 |
|------------------|-------------|
| `agent` | `id["label"]` （矩形） |
| `executor` | `id(["label"])` （角丸矩形） |
| `condition` | `id{"label"}` （菱形） |

#### Mermaidフローチャートサンプル（standard単一フロー）

コード生成タスク実行中（`code_generation`ノードがrunning）の状態例:

```mermaid
flowchart TD
    user_resolve(["ユーザー情報取得"]):::done
    task_classifier["タスク分類"]:::done
    task_type_branch{"タスク種別判定"}:::done
    code_generation_planning["コード生成計画"]:::done
    exec_env_setup_code(["実行環境セットアップ（コード生成）"]):::done
    code_generation["コード生成"]:::running
    code_generation_reflection["コード生成リフレクション"]:::pending
    code_review["コードレビュー"]:::pending
    user_resolve --> task_classifier
    task_classifier --> task_type_branch
    task_type_branch -- コード生成 --> code_generation_planning
    code_generation_planning --> exec_env_setup_code
    exec_env_setup_code --> code_generation
    code_generation --> code_generation_reflection
    code_generation_reflection --> code_review
    classDef done fill:#4caf50,color:#fff,stroke:#388e3c
    classDef running fill:#ff9800,color:#fff,stroke:#e65100,stroke-width:3px
    classDef pending fill:#9e9e9e,color:#fff,stroke:#616161
```

#### Mermaidフローチャートサンプル（multi_codegen 3並列）

並列コード生成実行中（`code_generation_standard`ノードがrunning）の状態例:

```mermaid
flowchart TD
    code_generation_planning["コード生成計画"]:::done
    subgraph parallel["並列コード生成（3実装）"]
        direction LR
        code_generation_fast["コード生成（高速）"]:::done
        code_generation_standard["コード生成（標準）"]:::running
        code_generation_creative["コード生成（創造的）"]:::pending
    end
    code_review["コードレビュー"]:::pending
    code_generation_planning --> code_generation_fast & code_generation_standard & code_generation_creative
    code_generation_fast & code_generation_standard & code_generation_creative --> code_review
    classDef done fill:#4caf50,color:#fff,stroke:#388e3c
    classDef running fill:#ff9800,color:#fff,stroke:#e65100,stroke-width:3px
    classDef pending fill:#9e9e9e,color:#fff,stroke:#616161
```

### 6.4 実装方法

以下の3クラスで進捗報告機能を実現する。詳細設計は`CLASS_IMPLEMENTATION_SPEC.md`の§8.3〜§8.5を参照。

| クラス | 責務 |
|--------|------|
| `MermaidGraphRenderer` | グラフ定義とノード状態dictからMermaidフローチャート文字列を生成する。並列グループを自動検出してsubgraphとして出力する |
| `ProgressCommentManager` | MRへのコメント新規作成（タスク開始時）と上書き更新（各イベント時）を担当する。`progress_comment_id`をWorkflowContextに保存・参照する。スロットリング（1秒間隔）を実施する |
| `ProgressReporter` | `ConfigurableAgent`・各`Executor`から呼び出されるファサード。イベント受信時に`MermaidGraphRenderer`でコメントを再構築し`ProgressCommentManager`に渡す。ノード名の表示にはグラフ定義の`label`フィールドを使用する |

### 6.5 進捗報告のメリット

1. **可視性**: ユーザーがエージェントの進捗をリアルタイムで確認できる
2. **コメントの整理**: 1タスク1コメントのため、MRのコメント欄が散乱しない
3. **状態の一覧性**: Mermaidグラフで全ノードの状態を一覧できる
4. **デバッグ性**: 問題発生時にどのフェーズでエラーが起きたか明確
5. **信頼性**: エージェントが止まっているのか、実行中なのかが分かる

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
- `create_merge_request_note(mr_iid, body) → int`: 新規コメントを作成し、GitLab Note IDを返す
- `update_merge_request_note(mr_iid, note_id, body) → None`: 指定Note IDのコメントを上書き更新する（GitLab `PUT /projects/:id/merge_requests/:mr_iid/notes/:note_id` APIを使用）

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

#### **AF標準クラスと本システムでの活用対応**

| AF標準クラス | 本システムでの実装 | 参照セクション |
|------------|----------------|-------------|
| [`Agent`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_agents.py) / [`Executor`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_workflows/_executor.py) | `ConfigurableAgent`・`WorkflowFactory` | §2.3.3 |
| [`BaseHistoryProvider`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py) | `PostgreSqlChatHistoryProvider` | §8.2 |
| Filters（[`_middleware.py`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_middleware.py)） | エラーハンドリング・ログ・認証の統一 | §8.8 |
| [`OpenAIChatClient`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/openai/_chat_client.py) / [`AzureOpenAIChatClient`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/azure/_chat_client.py) | OpenAI/Azure OpenAI両対応 | §1.2 |
| [`FunctionTool`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_tools.py) / [`MCPStdioTool`](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py) | GitLab API・MCPサーバー連携 | §9 |
| [Process Framework](https://github.com/microsoft/agent-framework/tree/main/python/packages/core/agent_framework/_workflows) | `WorkflowBuilder`・`ExecEnvSetupExecutor` | §2.3.3 |

本システムでは、Agent Frameworkの標準機能に加えて以下のカスタム実装を追加する：

#### ワークフローコンテキストの主要キー定義

Agent FrameworkのWorkflowContextを介してワークフロー全体で共有されるデータのキー定義。

#### タスク情報キー

| キー名 | データ型 | 説明 | 設定タイミング |
|--------|---------|------|-------------|
| `task_uuid` | str | タスクの一意識別子 | Consumerがワークフロー開始時 |
| `task_type` | str | タスク種別（issue/merge_request） | Consumerがワークフロー開始時 |
| `task_mr_iid` | int | MR IID（MRタスクの場合） | Consumerがワークフロー開始時 |
| `task_issue_iid` | int | Issue IID（Issueタスクの場合） | Consumerがワークフロー開始時 |
| `project_id` | int | GitLabプロジェクトID | Consumerがワークフロー開始時 |
| `user_email` | str | タスク実行ユーザーのメールアドレス | UserResolverExecutor実行時 |

#### 計画・実行キー

| キー名 | データ型 | 説明 | 設定タイミング |
|--------|---------|------|-------------|
| `plan_result` | dict | 計画フェーズの結果 | planエージェント実行時 |
| `previous_plan_result` | dict | 前回の計画結果（再計画時の参照用） | plan_reflectionエージェント実行時 |
| `branch_envs` | dict | 番号をキーとした環境情報辞書（`{1: {"env_id": "...", "branch": "..."}, ...}`） | ExecEnvSetupExecutor実行時 |
| `execution_results` | dict | エージェント定義IDをキーとした実行結果辞書 | executionエージェント実行時 |
| `selected_implementation` | dict | 選択された実装の情報 | reviewエージェント実行時 |

#### コメント・フィードバックキー

| キー名 | データ型 | 説明 | 設定タイミング |
|--------|---------|------|-------------|
| `user_new_comments` | list | ユーザーからの新規コメント配列 | CommentCheckMiddleware検出時 |
| `progress_comment_id` | int | 進捗コメントのGitLab Note ID | `ProgressCommentManager.create_progress_comment()`実行時（タスク全体開始時） |

#### 内部管理キー

| キー名 | データ型 | 説明 | 設定タイミング |
|--------|---------|------|-------------|
| `_node_visit_counts` | dict | ノード別訪問回数辞書 | InfiniteLoopDetectionMiddleware更新時 |
| `_execution_history` | list | 実行履歴配列（ノードID一覧） | InfiniteLoopDetectionMiddleware更新時 |

**注意事項**:
- `task_mr_iid`と`task_issue_iid`は排他的（どちらか一方のみが設定される）
- ConfigurableAgentは`task_mr_iid`または`task_issue_iid`を使用して進捗報告先を特定する
- `_`で始まるキーはシステム内部管理用であり、エージェントから直接参照すべきではない

### 8.2 Agent Framework標準Providerのカスタム実装

Agent Frameworkが提供する`BaseHistoryProvider`と`BaseContextProvider`を継承したカスタム実装を行う。

#### 8.2.1 PostgreSqlChatHistoryProvider（会話履歴の永続化）

**基底クラス**: `agent_framework.BaseHistoryProvider`

**責務**:
- LLMの会話履歴をPostgreSQLに永続化する
- タスクUUID単位で会話履歴を読み込み・保存する
- トークン数を記録し管理する

**主要メソッド**:

- **`async def get_messages(session_id: str, **kwargs) -> list[Message]`**
  - Agent Frameworkがエージェント実行前に呼び出すメソッド
  - `session_id`からタスクUUIDを特定する
  - PostgreSQLの`context_messages`テーブルから当該タスクの会話履歴を時系列順に取得する
  - 取得したメッセージをAgent Frameworkの`Message`オブジェクトのリストとして返す
  - エージェントはこの履歴を含めてLLMに送信する

- **`async def save_messages(session_id: str, messages: list[Message], **kwargs) -> None`**
  - Agent Frameworkがエージェント実行後に呼び出すメソッド
  - `messages`から新しい会話メッセージ（ユーザー入力とアシスタント応答）を取得する
  - 各メッセージをPostgreSQLの`context_messages`テーブルに保存する
  - トークン数を計算し、メッセージと共に保存する
  - セッション状態にメッセージ総数とトークン総数を更新する

**セッション状態管理**:

- `state: dict`を使用してセッション状態を管理する（`ProviderSessionState<ChatHistorySessionState>`型はPython AFでは使用しない）
- `state`辞書には以下の情報を保持する：
  - `task_uuid`: タスクUUID（文字列型）
  - `message_count`: メッセージ総数（整数型）
  - `total_tokens`: トークン総数（整数型）
- Agent Frameworkの`AgentSession`に鏈ついて自動的に管理される
- 状態キーは`"PostgreSqlChatHistory"`として他のProviderと衝突しないようにする

#### 8.2.2 PlanningContextProvider（プランニング履歴管理）

**基底クラス**: `agent_framework.BaseContextProvider`

**責務**:
- プランニング履歴を永続化し復元する
- 過去の計画・実行・検証結果をコンテキストとしてエージェントに提供する

**主要メソッド**:

- **`async def before_run(self, *, agent, session, context: SessionContext, state: dict) -> None`**
  - Agent Frameworkがエージェント実行前に呼び出すメソッド
  - `session`または`state`からタスクUUIDを取得する
  - PostgreSQLの`context_planning_history`テーブルから当該タスクの過去のプランニング履歴を取得する
  - 取得したプランニング履歴を人間が読める形式のテキストに整形する
  - `context.context_messages[self.source_id]`に整形したテキストを追加メッセージとして設定する
  - エージェントはこのコンテキストを参照してプランニングを行う

- **`async def after_run(self, *, agent, session, context: SessionContext, state: dict) -> None`**
  - Agent Frameworkがエージェント実行後に呼び出すメソッド
  - `context`からエージェントの応答メッセージを解析し、プランニング結果を抽出する
  - プランニングフェーズ（planning/execution/reflection）を判定する
  - 計画データ、アクションID、実行結果をJSONB形式で構造化する
  - PostgreSQLの`context_planning_history`テーブルに保存する

#### 8.2.3 ToolResultContextProvider（ツール実行結果管理）

**基底クラス**: `agent_framework.BaseContextProvider`

**責務**:
- ツール実行結果（ファイル読み込み、コマンド出力）を保存し復元する
- ツール実行結果はファイル内容を参照することが多く巨大化する傾向があるため、ファイルベースストレージに永続化する
- メタデータ（ツール名、実行日時、サイズ等）のみをPostgreSQLに保存し、実際の結果データはファイルに保存する

**主要メソッド**:

- **`async def before_run(self, *, agent, session, context: SessionContext, state: dict) -> None`**
  - Agent Frameworkがエージェント実行前に呼び出すメソッド
  - `session`または`state`からタスクUUIDを取得する
  - PostgreSQLの`context_tool_results_metadata`テーブルから当該タスクのツール実行メタデータを取得する
  - ファイルストレージ（`tool_results/{task_uuid}/`）から実際のツール実行結果を読み込む
  - ファイル読み込み結果とコマンド実行結果をそれぞれ時系列でソートする
  - 直近のツール実行結果（例: 最新10件）を要約形式で抽出する
  - 大きなファイル内容は省略し、サマリー情報のみを含める
  - `context.context_messages[self.source_id]`に整形したテキストを追加メッセージとして設定する
  - エージェントはこの情報を参照して次のアクションを決定する

- **`async def after_run(self, *, agent, session, context: SessionContext, state: dict) -> None`**
  - Agent Frameworkがエージェント実行後に呼び出すメソッド
  - `context`からツール呼び出し情報を取得する
  - ツール実行結果をJSON形式でファイルに保存:
    - ファイル読み込みツールの場合、ファイルパス、内容（全体）、MIMEタイプをJSON形式で保存する
    - コマンド実行ツールの場合、コマンド、終了コード、標準出力、標準エラー出力をJSON形式で保存する
    - MCPツール呼び出しの場合、ツール名、引数、結果（全体）をJSON形式で保存する
  - タイムスタンプ付きのファイル名で`tool_results/{task_uuid}/{timestamp}_{tool_name}.json`に保存する
  - PostgreSQLの`context_tool_results_metadata`テーブルにメタデータを保存:
    - `tool_name`, `file_path`, `file_size`, `created_at`
  - `metadata.json`にツール実行統計情報を更新する（ファイル数、総サイズ、最終更新日時）

#### 8.2.4 データベーススキーマ設計

**使用テーブル**:

本システムが使用する全テーブルの詳細定義は **[DATABASE_SCHEMA_SPEC.md](DATABASE_SCHEMA_SPEC.md)** を参照してください。

**PostgreSqlChatHistoryProviderが使用するテーブル**:
- `context_messages`: LLM会話履歴を保存（詳細は[DATABASE_SCHEMA_SPEC.md セクション5.1](DATABASE_SCHEMA_SPEC.md#51-context_messagesテーブル)参照）

**PlanningContextProviderが使用するテーブル**:
- `context_planning_history`: プランニング履歴を保存（詳細は[DATABASE_SCHEMA_SPEC.md セクション5.2](DATABASE_SCHEMA_SPEC.md#52-context_planning_historyテーブル)参照）
- `context_metadata`: タスクメタデータを保存（詳細は[DATABASE_SCHEMA_SPEC.md セクション5.3](DATABASE_SCHEMA_SPEC.md#53-context_metadataテーブル)参照）

**ToolResultContextProviderが使用するテーブル**:
- `context_tool_results_metadata`: ツール実行メタデータを保存（詳細は[DATABASE_SCHEMA_SPEC.md セクション5.4](DATABASE_SCHEMA_SPEC.md#54-context_tool_results_metadataテーブル)参照）

#### 8.2.5 ファイルベースストレージ設計（ToolResultContextProvider）

**ディレクトリ構造**:
```
tool_results/
├── {task_uuid}/
│   ├── mcp_tool_calls/          # MCPツール呼び出し履歴（ファイル読み込み・コマンド実行含む）
│   │   └── {timestamp}_tool.json
│   └── metadata.json            # ツール実行メタデータ
```

**metadata.jsonのフィールド**:

- `task_uuid`: タスクUUID（文字列）
- `total_mcp_calls`: MCPツール呼び出し総数（整数）
- `started_at`: 開始日時（ISO 8601形式文字列）
- `last_updated_at`: 最終更新日時（ISO 8601形式文字列）

**MCPツール呼び出し履歴（mcp_tool_calls/*.json）のフィールド**:

- `timestamp`: 実行日時（ISO 8601形式文字列）
- `tool_name`: MCPツール名（例: "text_editor", "command_executor"）
- `arguments`: ツールに渡した引数（JSONB）
- `result`: ツール実行結果（JSONB）
- `success`: 成功フラグ（真偽値）
- `error_message`: エラーメッセージ（文字列、失敗時のみ）

**ファイル保持期限**: 設定で指定（デフォルト30日後に自動削除）

#### 8.2.6 エージェント設定への統合

**AgentへのProvider登録手順**:

1. **カスタムProviderのインスタンス化**
   - `PostgreSqlChatHistoryProvider`をPostgreSQLデータベース接続情報と共にインスタンス化する
   - `PlanningContextProvider`をPostgreSQLデータベース接続情報と共にインスタンス化する
   - `ToolResultContextProvider`をファイルストレージパスと共にインスタンス化する

2. **エージェント作成時の設定**
   - `Agent(client=chat_client, tools=tool_list, context_providers=[postgres_history_provider, planning_provider, tool_result_provider])`を呼び出す
   - 引数を設定する：
     - `client`: OpenAIChatClientまたはAzureOpenAIChatClientインスタンス
     - `instructions`: システムプロンプト
     - `tools`: FunctionTool、MCPStdioTool等のツールリスト
     - `context_providers`: `PostgreSqlChatHistoryProvider`、`PlanningContextProvider`、`ToolResultContextProvider`のリスト
   - `Agent`オブジェクトが返される

3. **セッション作成**
   - `agent.create_session(session_id=task_uuid)`でセッションを作成する
   - Agent FrameworkがBaseHistoryProviderとBaseContextProvidersを自動的に初期化する
   - セッション状態は各Providerの`state: dict`として管理される

4. **セッションの永続化**
   - セッション識別子（`session_id`）をPostgreSQLのtasksテーブルのmetadataカラム（JSONB型）に保存する
   - 各Providerの`state`はAgent Frameworkが管理するため、session_idのみ保存すれば復元可能
   - タスク一時停止や再起動時に使用する

5. **セッションの復元**
   - 保存された`session_id`を取得する
   - `agent.create_session(session_id=saved_session_id)`で同じsession_idを使ってセッションを再作成する
   - 各ProviderがPostgreSQLからセッション状態を復元して処理を継続できる

#### 会話履歴管理（メッセージ種別）

- **システムプロンプト**: タスク開始時に設定（英語）
- **ユーザーメッセージ**: Issue/MR内容、コメント
- **アシスタント応答**: LLMからの応答
- **ツール呼び出し**: function_call とその結果

### 8.3 Execution State

タスク実行状態はPostgreSQLで管理します。

#### tasksテーブル

タスクの実行状態、進捗、メタデータを管理するテーブルです。詳細定義は **[DATABASE_SCHEMA_SPEC.md セクション4.1](DATABASE_SCHEMA_SPEC.md#41-tasksテーブル)** を参照してください。

**主要フィールド**:
- `uuid`: タスクUUID（主キー）
- `task_type`: タスク種別（issue_to_mr/mr_processing）
- `status`: 状態（running/completed/paused/failed）
- `metadata`: シリアル化されたセッション情報を含むJSONBデータ

### 8.4 コンテキスト圧縮

会話履歴のトークン数が設定閾値を超えた場合、古いメッセージ群を要約して単一のメッセージに置き換えることでトークン数を削減する。圧縮処理は**ContextCompressionService**が担当し、PostgreSqlChatHistoryProviderと連携して動作する。

#### 8.4.1 設定パラメータ

コンテキスト圧縮の設定はユーザー単位で管理される。user_configsテーブルに各ユーザーの圧縮設定が保存され、ユーザーがLLMモデルを選択する際に適切なtoken_thresholdが自動的に設定される。

**ユーザー設定カラム（user_configsテーブル）**:

| カラム名 | デフォルト値 | 説明 |
|---------|-------------|------|
| `context_compression_enabled` | true | コンテキスト圧縮を有効化するか |
| `token_threshold` | NULL | 圧縮を開始するトークン数の閾値（NULLの場合はモデル推奨値を使用） |
| `keep_recent_messages` | 10 | 最新から保持するメッセージ数（圧縮対象外） |
| `min_to_compress` | 5 | 圧縮する最小メッセージ数（これ未満は圧縮しない） |
| `min_compression_ratio` | 0.8 | 圧縮率の最小値（0.8=20%削減、これ未満の効果なら圧縮しない） |

**モデル別推奨token_threshold**:

ユーザーがtoken_thresholdをNULLのまま（未設定）にした場合、model_nameに基づいて以下の推奨値が自動的に適用される。推奨値はモデルのコンテキストウィンドウの70%として計算される。

| モデル名 | コンテキストウィンドウ | 推奨token_threshold | 備考 |
|---------|----------------------|---------------------|------|
| gpt-4o | 128k | 90,000 | ウィンドウの70%で圧縮開始 |
| gpt-4-turbo | 128k | 90,000 | ウィンドウの70%で圧縮開始 |
| gpt-4 | 8k | 5,600 | ウィンドウの70%で圧縮開始 |
| gpt-3.5-turbo | 16k | 11,000 | ウィンドウの70%で圧縮開始 |
| gpt-3.5-turbo-16k | 16k | 11,000 | ウィンドウの70%で圧縮開始 |
| o1-preview | 128k | 90,000 | ウィンドウの70%で圧縮開始 |
| o1-mini | 128k | 90,000 | ウィンドウの70%で圧縮開始 |
| 未知のモデル | 仮定8k | 5,600 | 保守的な値を使用 |

**設定の優先順位**:

1. **ユーザー明示設定**: user_configs.token_thresholdがNULLでない場合、その値を使用
2. **モデル推奨値**: token_thresholdがNULLの場合、model_nameに基づく推奨値を使用
3. **システムデフォルト**: 未知のモデルで推奨値がない場合、5,600を使用

**設定の検証範囲**:

User Config APIでユーザー設定を更新する際、以下の範囲で検証される:
- token_threshold: 1,000〜150,000
- keep_recent_messages: 1〜50  
- min_to_compress: 1〜20
- min_compression_ratio: 0.5〜0.95

#### 8.4.2 圧縮トリガー

PostgreSqlChatHistoryProvider.save_messages()メソッドがメッセージを保存した後、自動的にContextCompressionService.check_and_compress_async()を呼び出す。この際、user_emailを渡すことで、ContextCompressionServiceがuser_configsテーブルからユーザーの圧縮設定を読み込む。

context_compression_enabled=falseの場合、圧縮処理をスキップする。セッション状態のtotal_tokensがユーザーのtoken_threshold（またはモデル推奨値）を超えている場合のみ圧縮処理を実行する。

#### 8.4.3 圧縮対象の選択基準

1. **保持対象の特定**:
   - 最新のkeep_recent_messages件（デフォルト10件）のメッセージは常に保持
   - role="system"のメッセージは常に保持（システムプロンプトは圧縮しない）
   - is_compressed_summary=trueのメッセージは再圧縮しない（既に圧縮済み）

2. **圧縮対象の抽出**:
   - 保持対象以外のメッセージ（role="user"/"assistant"/"tool"）を抽出
   - 抽出されたメッセージ数がmin_to_compressを下回る場合は圧縮を実行しない
   - 連続するseq範囲（start_seq～end_seq）を特定

3. **具体例**:
   - 総メッセージ数: 60件、total_tokens: 9500（閾値超過）
   - seq 1: role="system" → 保持
   - seq 2-50: role="user"/"assistant"/"tool" → 圧縮対象（49件）
   - seq 51-60: 最新10件 → 保持
   - 結果: seq 2-50を1つの要約メッセージ（role="user"）に置き換え

#### 8.4.4 要約生成処理

圧縮対象のメッセージをLLMに送信して要約を生成する。プロンプトは英語で記述し、重要な情報を保持した簡潔な要約を要求する。

**要約プロンプトの内容**:
- 保持すべき情報: 重要な意思決定、コード変更、エラー・問題、タスク進捗
- 形式: 自然な会話要約として整形
- 言語: 英語

**要約メッセージのフォーマット**:
- role: "user"（会話フローに自然に統合）
- content: `[Summary of previous conversation (messages {start_seq}-{end_seq})]: {要約内容}`
- is_compressed_summary: true
- compressed_range: `{"start_seq": 2, "end_seq": 50}`（圧縮範囲を記録）

#### 8.4.5 メッセージ置き換え処理

1. **トランザクション開始**: データベース整合性を保証

2. **圧縮対象メッセージ削除**:
   - context_messagesテーブルからstart_seq～end_seqの範囲を削除
   - 削除件数を記録（圧縮履歴用）

3. **要約メッセージ挿入**:
   - 圧縮範囲の先頭seq（start_seq）を再利用してINSERT
   - is_compressed_summary=true、compressed_rangeに範囲を記録

4. **後続メッセージのseq再番号化**:
   - end_seqより後ろのメッセージのseqを前詰め
   - 例: 50件削除した場合、seq 51→2、seq 52→3のように調整

5. **圧縮履歴記録**:
   - message_compressionsテーブルに圧縮実行記録をINSERT
   - 圧縮前後のトークン数、圧縮率を記録

6. **コミット**: すべての変更を確定

#### 8.4.6 圧縮効果の検証

要約生成後、圧縮率（圧縮後トークン数 / 圧縮前トークン数）を計算する。圧縮率がmin_compression_ratio以上（デフォルト0.8、つまり20%未満の削減）の場合、圧縮効果が不十分と判断して圧縮を実行しない。この場合、元のメッセージを保持したまま処理を終了する。

#### 8.4.7 エラーハンドリング

- **LLM呼び出し失敗**: 圧縮を中断、エラーログ記録、次回メッセージ追加時に再試行
- **トークン数削減不足**: 圧縮率が基準未満の場合は圧縮を実行せず、元のメッセージを保持
- **データベースエラー**: トランザクションロールバック、エラーログ記録、次回再試行

#### 8.4.8 圧縮履歴の管理

message_compressionsテーブルで圧縮の実行履歴を管理する。各圧縮処理について、対象範囲（start_seq～end_seq）、圧縮前後のトークン数、圧縮率、実行日時を記録する。この履歴データは圧縮処理の監視、デバッグ、最適化に使用する。

### 8.5 コンテキスト継承

同一Issue/MRに対する過去のタスク実行履歴から有用な情報を抽出し、新しいタスクのコンテキストとして提供する。継承処理は**TaskInheritanceContextProvider**が担当し、Agent FrameworkのBaseContextProviderとして実装される。

#### 8.5.1 継承データの構造

過去タスクから以下の情報を継承する。これらの情報はtasksテーブルのmetadataカラム（JSONB型）にinheritance_dataキーで保存される。

**InheritanceData構造**:
- **final_summary**: タスク完了時の最終要約（文字列）
  - 内容: タスク全体の要約、達成内容、重要な決定事項
  - 生成元: context_messagesテーブルの最後の圧縮要約（is_compressed_summary=true）、または完了時に新規生成
- **planning_history**: プランニングフェーズの履歴（配列）
  - 内容: phase、node_id、plan（Todoリスト、アクション一覧）、created_at
  - 生成元: context_planning_historyテーブル
- **implementation_patterns**: 成功した実装パターン（配列）
  - 内容: pattern_type（file_structure/test_approach/framework等）、description、success（真偽値）
  - 生成元: ツール実行結果やメタデータから抽出
- **key_decisions**: 重要な技術的決定事項（配列）
  - 内容: 決定事項の文字列（例: "FastAPIでREST API実装"、"PostgreSQL 15使用"）
  - 生成元: プランニング履歴やメッセージから抽出

#### 8.5.2 継承データの生成タイミング

タスク完了時（status="completed"に更新時）に、WorkflowFactoryまたはConsumerのタスク完了ハンドラがInheritanceDataを生成する。

**生成処理フロー**:
1. context_messagesテーブルから最後の圧縮要約を取得（role="user", is_compressed_summary=true, 最新）→ final_summaryにセット
2. 圧縮要約が存在しない場合、全メッセージをLLMに送信して要約を生成 → final_summaryにセット
3. context_planning_historyテーブルから全履歴を取得 → planning_historyにセット
4. ツール実行結果やメタデータから成功パターンを抽出 → implementation_patternsにセット
5. プランニング履歴やメッセージから重要な決定事項を抽出 → key_decisionsにセット
6. InheritanceDataオブジェクトを構築し、tasksテーブルのmetadata["inheritance_data"]に保存

#### 8.5.3 過去タスクの検索

TaskInheritanceContextProviderは、新しいタスク開始時に同一Issue/MRの過去タスクを検索する。

**検索条件**:
- task_identifierが一致（同一Issue/MRを特定）
  - Issueタスク: `{project_id}/issues/{issue_iid}`形式
  - MRタスク: `{project_id}/merge_requests/{mr_iid}`形式
- repository名が一致
- statusが"completed"（完了タスクのみ）
- created_atが有効期限内（デフォルト30日以内）

**検索クエリ**:
tasksテーブルに対して、task_identifierとrepositoryでフィルタリングし、completed_at降順でソートして最新の成功タスクを取得する。LIMIT 5で直近5件のタスクを取得し、そのうち最新の1件を使用する。

#### 8.5.4 継承データの適用

TaskInheritanceContextProvider.before_run()メソッドが、過去タスクのInheritanceDataを取得し、Markdown形式に整形してコンテキストに注入する。

**整形フォーマット**:
```
## Previous Task Context

### Summary
{final_summary}

### Planning History
- Phase: {phase}, Node: {node_id}
  Plan: {plan内容}
  Created: {created_at}

### Successful Implementation Patterns
- {pattern_type}: {description}

### Key Technical Decisions
- {decision}
```

このMarkdownテキストがLLMのコンテキストとして自動的に挿入され、エージェントは過去の知見を参照しながらタスクを実行できる。

#### 8.5.5 有効期限の管理

継承データの有効期限はデフォルト30日とし、created_atを基準に判定する。30日を超えた過去タスクは検索対象から除外される。有効期限は設定ファイルで変更可能。

**期限切れタスクの扱い**:
- 検索クエリでフィルタリング（created_at > NOW() - INTERVAL '30 days'）
- tasksテーブルのレコード自体は削除しない（履歴として保持）
- metadata["inheritance_data"]も削除しない（監査・分析用に保持）

#### 8.5.6 継承優先順位

複数の過去タスクが見つかった場合、以下の優先順位で継承データを選択する:
1. **最新の完了タスク**: completed_atが最も新しいタスク
2. **成功タスク**: status="completed"かつerror_messageがNULLのタスク
3. **実装パターン数**: metadata["inheritance_data"]["implementation_patterns"]の要素数が多いタスク

TaskInheritanceContextProviderは上記の優先順位で最適な過去タスクを選択し、そのInheritanceDataをコンテキストとして提供する。

#### 8.5.7 継承の無効化

ユーザーが過去タスクの継承を望まない場合、タスク作成時にメタデータで継承を無効化できる。tasksテーブルのmetadata["disable_inheritance"]=trueを設定すると、TaskInheritanceContextProviderは過去タスクの検索をスキップする。

### 8.6 ワークフロー状態管理（WorkflowContext）

Agent FrameworkのWorkflow機能を使用する場合、**`WorkflowContext`**を通じて複数のExecutor間で共有状態を管理する。

**状態の書き込み処理**:

- Executor内で`ctx.set_state(key, value)`メソッドを呼び出す
- 引数として以下を指定する：
  - `key`: 状態を識別するキー（文字列）
  - `value`: 保存する値（任意の型、JSON serializable）
- Agent FrameworkのBSPモデルにより、ワークフロー実行中に安全に状態を保持する
- 一意のkeyで状態を管理する

**状態の読み込み処理**:

- 別のExecutor内で`ctx.get_state(key)`メソッドを呼び出す
- 引数として以下を指定する：
  - `key`: 取得したい状態のキー（文字列）
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

### 8.7 実行環境管理（ExecutionEnvironmentManager）

#### 8.7.1 概要

`ExecutionEnvironmentManager`はDocker環境のライフサイクル（作成、割り当て、クリーンアップ）を管理する独自実装クラスである。ワークフロー開始前に`PlanEnvSetupExecutor`が作成するplan環境（python固定、1つ）と、各タスク分岐内の`ExecEnvSetupExecutor`が作成する実行環境（各ノードの`env_count`数分）の両方を管理する。プロジェクト言語に応じた適切なDockerイメージを選択して環境を作成する。

#### 8.7.2 責務

1. **環境名マッピング管理**: 環境名（python、node等）からDockerイメージ名へのマッピングを管理
2. **plan環境管理**: ワークフロー開始前にpython固定のplan環境を1つ作成し、`plan_environment_id`として管理する。planningエージェント全員で共有する
3. **実行環境作成**: 各タスク分岐のplanning完了後に`ExecEnvSetupExecutor`が呼び出し、`env_count`数分の実行環境を一括作成して`branch_envs`に保存する
4. **環境割り当て**: `env_ref: "1"/"2"/"3"`のノードは`branch_envs`から対応する番号の環境IDを取得して使用する
5. **環境分離**: 並列実行されるノードが独立した環境で動作することを保証
6. **環境クリーンアップ**: ワークフロー完了時または異常終了時にplan環境・実行環境の全環境を削除

#### 8.7.3 環境名マッピング

**環境名とDockerイメージの対応**:

環境名は設定ファイル（config.yaml）で定義され、以下のようにマッピングされる：

- `python`: プリビルドPythonイメージ（例: `code-orchestrator-executor-python:latest`）
  - Python 3.11、pip、git、一般的な開発ツールを含む
- `miniforge`: プリビルドMiniconda/Mambaイメージ（例: `code-orchestrator-executor-miniforge:latest`）
  - Miniconda、mamba、conda、git、一般的なデータサイエンスツールを含む
- `node`: プリビルドNode.jsイメージ（例: `code-orchestrator-executor-node:latest`）
  - Node.js 20、npm、yarn、git、一般的な開発ツールを含む
- `default`: デフォルトイメージ（例: `ubuntu:22.04`）
  - 基本的なUbuntu環境、環境判定失敗時のフォールバック

**環境名の選択**:

PrePlanningManagerがLLMを使用してプロジェクト言語を判定し、適切な環境名を選択する。選択された環境名はワークフローコンテキストの`selected_environment`キーに保存され、ExecutionEnvironmentManagerはこの値を参照して適切なDockerイメージを選択する。

#### 8.7.4 主要メソッド

| メソッド | 説明 |
|---------|------|
| `prepare_plan_environment(environment_name, mr_iid)` | python固定（configの`plan_environment_name`）のplan環境を1つ作成し、環境IDを返す。環境IDは`codeagent-plan-mr{mr_iid}`形式で生成される |
| `prepare_environments(count, environment_name, mr_iid, node_ids)` | 指定された環境名のイメージでcount個の実行環境を一括作成し、環境IDリストを返す。環境IDは`codeagent-{environment_name}-mr{mr_iid}-{node_id}`形式で生成される |
| `get_environment(node_id)` | ノードIDに対応する環境IDを返す（初回呼び出し時に環境プールから割り当て） |
| `execute_command(node_id, command)` | 指定ノードの環境でコマンドを実行 |
| `clone_repository(node_id, repo_url, branch)` | 指定ノードの環境でリポジトリをクローン |
| `cleanup_environments()` | すべての環境を削除 |

**環境ID命名規則**:

環境IDは人間可読な形式で生成される：`codeagent-{environment_name}-mr{mr_iid}-{node_id}`

**構成要素**:
- `codeagent`: システム識別プレフィックス（複数システムが同じDockerホストを使う場合の識別）
- `{environment_name}`: 環境名（python, miniforge, node, default）
- `mr{mr_iid}`: MR IID（GitLabのMR番号）
- `{node_id}`: グラフ定義のノードID（code_generation, bug_fix等）

**例**:
- `codeagent-python-mr123-code_generation`
- `codeagent-miniforge-mr456-bug_fix`
- `codeagent-node-mr789-test_creation`

**利点**:
- 人間可読性: どのMRのどのノードの環境か一目で分かる
- 一意性: MR IIDとノードIDの組み合わせにより、複数のOrchestratorインスタンスが異なるMRを処理しても重複しない
- 運用性: `docker ps`でMR番号やノードIDで検索可能、システムプレフィックスで一括クリーンアップ可能
- 再実行対応: 再計画やワークフロー再開時に同じ環境IDが生成されるため、環境の再利用やトラブルシューティングが容易

#### 8.7.5 環境割り当てロジック

ExecutionEnvironmentManagerクラスは以下の内部データ構造を保持し、環境の割り当てを管理する：

**内部データ構造**:
- **環境プール（environment_pool）**: 準備済みの環境IDをリスト形式で保持する
- **ノード環境マッピング（node_to_env_map）**: ノードIDと環境IDの対応関係を辞書形式で管理する
- **次の割り当てインデックス（next_env_index）**: 次に割り当てる環境のインデックスを記録する
- **ロックオブジェクト（_lock）**: スレッド間の排他制御用。並列実行時の競合状態を防止する

**並列実行時の競合制御**:

並列実行時に複数のエージェントが同時に`get_environment()`を呼び出す可能性があるため、クリティカルセクションをロックで保護する。具体的には以下の処理：

1. **環境取得処理全体をロック**:
   - ロックを取得してから、ノード環境マッピングの確認→環境割り当て→インデックス更新までを実行
   - ロック解放後に環境IDを返す
   - これにより、同じ環境が複数のノードに割り当てられることを防止

2. **デッドロック回避**:
   - ロックのネストは行わない
   - ロック保持時間を最小限にする（環境作成処理はロック外で実行）

3. **環境作成（prepare_environments）の並列化**:
   - 環境作成自体は並列化可能（各環境が独立しているため）
   - 作成後の環境プールへの追加のみをロックで保護

**環境準備処理（prepare_environments）**:
1. 環境名からDockerイメージ名を取得
   - 設定ファイルの環境名マッピングを参照
   - 環境名が無効またはnullの場合はdefault環境を使用
2. 提供されたnode_idsリストをループ処理する
3. 各反復で人間可読な環境ID（`codeagent-{environment_name}-mr{mr_iid}-{node_id}`形式）を生成する
4. Docker APIを呼び出して選択されたイメージでDocker環境を作成する（環境名として人間可読な環境IDを設定、並列化可能）
5. ロックを取得して環境プールに追加する
6. ロック解放
7. 準備済み環境IDのリストを返す

**環境取得処理（get_environment）**:
1. ロックを取得する
2. ノードIDがノード環境マッピングに存在するか確認する
3. 存在する場合: マッピングから環境IDを取得（ロック解放後に返す）
4. 存在しない場合（初回呼び出し時）:
   - 次の割り当てインデックスが環境プールのサイズを超えていないか確認する
   - 超えている場合: ロック解放してRuntimeErrorをスローする（環境プール不足）
   - 問題ない場合: 環境プールから次のインデックスの環境IDを取得する
   - ノード環境マッピングにノードIDと環境IDの対応を記録する
   - 次の割り当てインデックスを1増やす
5. ロックを解放する
6. 割り当てた環境IDを返す

この仕組みにより、各ノードは初回実行時に一意の環境が割り当てられ、以降の呼び出しでは同じ環境が再利用される。並列実行時でも競合状態は発生しない。

#### 8.7.5 環境の引き継ぎ（Environment Inheritance）

**設計原則**: **環境そのものを次のエージェントに引き継ぐ**

実行エージェント（code_generation、bug_fix等）で生成されたファイルを後続のエージェント（code_review、test_execution_evaluation等）が使用するため、Docker環境を引き継ぐ仕組みを実装する。

**環境引き継ぎの仕組み**:

1. **実行エージェントが環境IDを使用**:
   - 実行エージェント（code_generation、bug_fix等）は、`branch_envs`から`env_ref`で指定された番号の環境IDを取得して使用する
   - コンテキストキー: `branch_envs`（辞書型、番号をキーとする）
   - スコープ: `workflow`（ワークフロー全体で共有）

2. **レビューエージェントが同じ環境IDを使用**:
   - レビューエージェント（code_review等）は、`branch_envs`から`env_ref`で指定された番号の環境IDを取得する
   - これにより、実行エージェントが生成したファイルに直接アクセス可能

3. **MCPToolWrapperの拡張**:
   - `EnvironmentAwareMCPClient`を拡張し、コンテキストから環境IDを取得する機能を追加
   - `env_ref`が指定されている場合は`branch_envs`から対応する環境IDを取得し、"plan"の場合は`plan_environment_id`を使用する
   - 辞書型キー（`branch_envs`）を使用し、単一・並列両方のエージェントに対応

**マルチエージェント時の環境引き継ぎ**:

```mermaid
graph TB
    Plan[計画フェーズ] --> ExecSetup[exec_env_setup_code_gen<br/>env_count: 3]
    ExecSetup --> Branch[サブブランチ作成]
    Branch --> A[code_generation_a<br/>env_ref: 1]
    Branch --> B[code_generation_b<br/>env_ref: 2]
    Branch --> C[code_generation_c<br/>env_ref: 3]
    
    A -->|"branch_envs[1]"| Rev[code_review<br/>3つの環境を順次確認]
    B -->|"branch_envs[2]"| Rev
    C -->|"branch_envs[3]"| Rev
    
    style A fill:#99ccff
    style B fill:#99ccff
    style C fill:#99ccff
    style Rev fill:#ffcc99
```

**選択された環境の引き継ぎ**:

code_reviewエージェント（マルチエージェント用）は、最良の実装を選択する際に以下の情報を`selected_implementation`に含める：
- `environment_id`: 選択された実装が存在するDocker環境のID
- `branch_name`: 選択されたブランチ名
- `selection_reason`: 選択理由の詳細説明
- `quality_score`: 品質スコア（0.0～1.0）
- `evaluation_details`: 評価の詳細情報（各評価項目のスコア等）

**利点**:

1. **ファイル共有の簡素化**: コンテキストに大量のファイル内容を含める必要がない
2. **効率的なレビュー**: レビューエージェントは実際のファイルを直接確認できる
3. **テスト環境の一貫性**: 生成されたコードと同じ環境でテストを実行できる
4. **マルチエージェント対応**: 各並列エージェントの成果物を独立した環境で保持し、選択された環境のみを後続に渡す

#### 8.7.6 並列実行時の動作

**例**: `multi_codegen_mr_processing`で3つのコード生成ノードが並列実行される場合（MR 123の場合）

1. **環境準備**: `exec_env_setup_code_gen`ノードが `prepare_environments(count=3, environment_name="python", mr_iid=123, node_id="exec_env_setup_code_gen")` を呼び出し
   - 生成される環境ID:
     - `codeagent-python-mr123-exec_env_setup_code_gen-1`
     - `codeagent-python-mr123-exec_env_setup_code_gen-2`
     - `codeagent-python-mr123-exec_env_setup_code_gen-3`
2. **branch_envs保存**: `branch_envs = {1: "codeagent-python-mr123-exec_env_setup_code_gen-1", 2: "...-2", 3: "...-3"}` をコンテキストに保存
3. **並列実行**: 各ノードは`env_ref`番号に対応する`branch_envs`の環境IDで独立して動作
   - `code_generation_a`（`env_ref: "1"`）→ `branch_envs[1]`の環境を使用
   - `code_generation_b`（`env_ref: "2"`）→ `branch_envs[2]`の環境を使用
   - `code_generation_c`（`env_ref: "3"`）→ `branch_envs[3]`の環境を使用
4. **code_reviewが全環境を参照**: `env_ref`省略・`input_keys`に`branch_envs`を含む → 全3環境の成果物を比較評価
5. **クリーンアップ**: ワークフロー完了時に3つの環境を一括削除

#### 8.7.7 エラーハンドリング

- **環境作成失敗**: Docker APIエラー時は例外をスローし、ワークフロー実行を中断
- **環境不足**: `get_environment()` でプールが枯渇した場合は RuntimeError をスロー
- **異常終了時のクリーンアップ**: `try-finally` パターンで必ず `cleanup_environments()` を実行

---

### 8.8 Middleware機構

#### 8.8.1 概要

Middlewareは、ノード実行の前後に自動的に介入する横断的な機能を提供します。グラフ構造を汚さずに、認証、ロギング、コメント監視などの共通処理を実装できます。

**主な用途**:
- ユーザーコメント監視（差分計画パターン）
- 実行時間の監視とタイムアウト処理
- エラーハンドリングの共通化
- デバッグ用ロギング

#### 8.8.2 Middleware実行タイミング

Middlewareは以下の3つのフェーズで実行されます：

1. **before_execution**: ノード実行前
2. **after_execution**: ノード実行後（成功時）
3. **on_error**: ノード実行中にエラーが発生した場合

#### 8.8.3 Middleware実装

**基底クラス（WorkflowMiddleware）**:

**責務**: すべてのMiddlewareが継承する抽象基底クラス

**主要メソッド**:
- `intercept(phase, node_id, context)`: ノード実行の前後で呼ばれる介入メソッド
  - **引数**:
    - `phase`: 実行フェーズ（"before_execution" | "after_execution" | "on_error"）
    - `node_id`: 対象ノードID
    - `context`: ワークフローコンテキスト
  - **戻り値**:
    - `None`: 通常フローを継続
    - `MiddlewareSignal`: フロー制御シグナル（リダイレクト、中断など）

**MiddlewareSignal（フロー制御シグナル）**:

**目的**: Middlewareがワークフローの実行フローを制御するための指示を伝達

**主要フィールド**:
- `action`: アクション種別（"redirect" | "abort" | "skip"）
  - **redirect**: 別のノードへリダイレクト
  - **abort**: ワークフロー全体を中断
  - **skip**: 現在のノード実行をスキップ
- `redirect_to`: リダイレクト先ノードID（actionがredirectの場合のみ）
- `reason`: フロー制御の理由（ログ・デバッグ用）
- `metadata`: 追加の制御情報（辞書型）

#### 8.8.4 CommentCheckMiddleware実装

**責務**: ノード実行前にGitLab MR/Issueの新規コメントをチェックし、検出時はノードmetadataの`comment_redirect_to`で指定されたノードへリダイレクト

**初期化処理**:
- GitLabクライアントへの参照を保持
- 最終チェック済みコメントIDを初期化（初期値はnull）

**intercept メソッドの処理フロー**:

1. **フェーズ判定**: 
   - `phase`が"before_execution"でない場合は何もせず終了（nullを返す）
   
2. **ノード設定確認**:
   - グラフからノード情報を取得
   - ノードのmetadataから`check_comments_before`フィールドを確認
   - falseまたは未設定の場合は何もせず終了（nullを返す）
   
3. **新規コメント取得**:
   - GitLab APIを使用してMR/Issueの全コメントを取得
   - 前回チェック済みコメントID以降の新規コメントのみをフィルタリング
   - 初回チェック時は新規コメント扱いしない（空リストを返す）
   - 最新コメントIDを更新して次回チェックに備える
   
4. **コメント判定**:
   - 新規コメントがない場合は何もせず終了（nullを返す）
   
5. **コンテキスト更新**:
   - ワークフローコンテキストに`user_new_comments`キーで新規コメント配列を設定
   - 現在の`plan_result`を`previous_plan_result`キーにコピー（再計画時の参照用）
   
6. **リダイレクト先の決定**:
   - ノードのmetadataから`comment_redirect_to`フィールドを取得（`check_comments_before: true`の場合は必須のため、バリデーション時点で存在が保証されている）
   
7. **リダイレクトシグナル生成**:
   - MiddlewareSignalを生成して返す
     - `action`: "redirect"
     - `redirect_to`: 上記で決定したノードID
     - `reason`: "New user comments detected"
     - `metadata`: コメント数、中断されたノードIDを含む

**新規コメント取得ロジック**:
- GitLab APIから全コメントを取得
- 保持している最終チェック済みコメントIDと各コメントのIDを比較
- IDが大きい（より新しい）コメントのみを新規として抽出
- 取得した全コメントの最後のIDを最終チェック済みコメントIDとして更新

#### 8.8.5 TokenUsageMiddleware実装

**責務**: すべてのAIエージェント呼び出しを自動的にインターセプトして、トークン使用量を記録し、メトリクスとして送信

**初期化処理**:
- ContextStorageManagerへの参照を保持（トークン使用量をデータベースに記録）
- MetricsCollectorへの参照を保持（OpenTelemetryへメトリクス送信）

**intercept メソッドの処理フロー**:

1. **フェーズ判定**:
   - `phase`が"after_execution"でない場合は何もせず終了（nullを返す）
   - トークン情報はエージェント実行後にのみ取得可能

2. **ノード種別判定**:
   - 対象ノードがConfigurableAgent（AIエージェント）でない場合は何もせず終了
   - Executorノードはトークンを使用しないためスキップ

3. **レスポンス情報取得**:
   - エージェント実行結果からLLMレスポンス情報を取得
   - レスポンスにトークン情報が含まれているか確認

4. **トークン情報抽出**:
   - prompt_tokens: 入力プロンプトのトークン数
   - completion_tokens: LLM生成出力のトークン数
   - total_tokens: 合計トークン数（prompt + completion）
   - model: 使用したモデル名（例: "gpt-4o"）

5. **データベース記録**:
   - ContextStorageManagerを使用して`token_usage`テーブルに記録
   - 記録フィールド:
     - user_email: ワークフローコンテキストから取得（token_usageテーブルのFK: users.email）
     - task_uuid: ワークフローコンテキストから取得
     - node_id: 実行ノードID（グラフノードID）
     - model: 使用モデル名
     - prompt_tokens、completion_tokens、total_tokens
     - created_at: 記録日時

6. **メトリクス送信**:
   - OpenTelemetry経由でメトリクスを送信
   - メトリクス名: `token_usage_total`
   - ラベル: model、node_id、user_email
   - 値: total_tokens

**並行実行時の動作**:
- 複数タスクが同時に実行される場合でも、各タスクのuser_emailとtask_uuidで区別
- 並列エージェント（例: code_generation_fast、code_generation_standard、code_generation_creative）は、agent_definition_idで明確に識別
- データベース書き込みはトランザクション管理で競合回避
- メトリクス送信は非同期で実行し、ワークフロー実行をブロックしない

#### 8.8.6 ErrorHandlingMiddleware実装

**責務**: すべてのノード実行時のエラーを統一的にハンドリングし、エラー分類、リトライ判定、ユーザー通知を実行

**初期化処理**:
- ContextStorageManagerへの参照を保持（エラー情報をデータベースに記録）
- GitLabClientへの参照を保持（エラー通知コメントを投稿）
- MetricsCollectorへの参照を保持（エラーメトリクスを送信）
- リトライポリシー設定を保持（最大リトライ回数、基本遅延時間）

**intercept メソッドの処理フロー**:

1. **フェーズ判定**:
   - `phase`が"on_error"でない場合は何もせず終了（nullを返す）
   - エラー処理は例外発生時のみ実行

2. **エラー情報取得**:
   - 発生した例外オブジェクトを取得
   - スタックトレース、エラーメッセージ、発生ノードIDを取得

3. **エラー分類**:
   - 例外の種類とエラーメッセージからエラーカテゴリを判定
   - **transient（一時的障害）**:
     - ネットワークタイムアウト
     - APIレート制限超過
     - サービス一時的不可（503エラー）
     - 接続タイムアウト
   - **configuration（設定エラー）**:
     - 環境変数の欠落
     - 無効な認証情報（401 Unauthorized）
     - 誤った設定値
     - 権限不足（403 Forbidden）
   - **implementation（実装バグ）**:
     - 未処理の例外
     - 予期しないデータ型
     - Null参照エラー
     - インデックス範囲外
   - **resource（リソース不足）**:
     - ディスク空間不足
     - メモリ不足
     - APIクォータ超過
     - ファイルディスクリプタ枯渇

4. **リトライ判定**:
   - エラーカテゴリが`transient`の場合、リトライ可能と判定
   - 現在のリトライ回数を確認（最大3回）
   - その他のカテゴリはリトライ不可

5. **リトライ実行（transientエラーの場合）**:
   - 指数バックオフ戦略を適用:
     - 1回目: 5秒待機
     - 2回目: 10秒待機（5秒 × 2）
     - 3回目: 20秒待機（5秒 × 4）
   - 待機後、同じノードを再実行
   - リトライ回数をワークフローコンテキストに記録

6. **エラー記録**:
   - ContextStorageManagerを使用してエラー情報をデータベースに記録
   - 記録フィールド:
     - task_uuid
     - node_id
     - error_category
     - error_message
     - stack_trace
     - retry_count
     - created_at

7. **ユーザー通知**:
   - リトライ不可のエラー、またはリトライ上限到達の場合
   - GitLabClientを使用してエラー通知コメントをIssue/MRに投稿
   - コメント内容:
     - エラー種別
     - 発生日時
     - エラー詳細メッセージ
     - スタックトレース（一部）
     - 推奨アクション（カテゴリに応じて）

8. **メトリクス送信**:
   - OpenTelemetry経由でエラーメトリクスを送信
   - メトリクス名: `workflow_errors_total`
   - ラベル: error_category、node_id、retry_attempted
   - 値: エラー発生回数

9. **タスク状態更新**:
   - リトライ不可のエラーの場合、タスク状態を"failed"に更新
   - ワークフロー実行を中断するMiddlewareSignalを返す（action: "abort"）

**エラーカテゴリ別の推奨アクション**:
- **transient**: 自動リトライ実行、リトライ失敗時はユーザーに手動再実行を促す
- **configuration**: 設定の確認と修正をユーザーに依頼、修正後に再実行
- **implementation**: 開発チームにバグ報告、システム管理者へ通知
- **resource**: 運用チームにリソース増強を依頼、一時的な負荷軽減策を実施

#### 8.8.7 InfiniteLoopDetectionMiddleware実装

**責務**: ワークフロー実行中の無限ループを検出し、異常な繰り返し実行を防止する

**設計思想**:

グラフ定義では循環（ループ）は意図的な設計パターンである（例: plan_reflection → plan のフィードバックループ）。静的検証では正常なループと異常な無限ループを区別できないため、実行時の動的検証により実際の実行パスを監視する。

**初期化処理**:
- 最大訪問回数（max_visits_per_node）: デフォルト10回
- 最大総ステップ数（max_total_steps）: デフォルト200ステップ
- 許容パターン設定（allowed_retry_patterns）: 辞書形式で特定のループパターンを許容

**intercept メソッドの処理フロー**:

1. **フェーズ判定**:
   - `phase`が"before_execution"でない場合は何もせず終了（nullを返す）
   - ノード実行前に訪問履歴をチェック

2. **実行履歴の取得と更新**:
   - ワークフローコンテキストから`_node_visit_counts`（ノード別訪問回数辞書）を取得
   - ワークフローコンテキストから`_execution_history`（実行履歴配列）を取得
   - 現在のノードIDの訪問回数を1増加
   - 実行履歴配列に現在のノードIDを追加

3. **ノード別訪問回数の超過チェック**:
   - 現在のノードの訪問回数が`max_visits_per_node`を超えているか確認
   - 超えている場合: 許容パターンチェックメソッドを呼び出し
   - 許容パターンに該当しない場合: abortシグナルを返す
     - `action`: "abort"
     - `reason`: "Infinite loop detected: node 'ノードID' visited 回数 times"
     - `metadata`: 実行履歴、訪問回数辞書を含む

4. **総ステップ数の超過チェック**:
   - 実行履歴配列の長さが`max_total_steps`を超えているか確認
   - 超えている場合: abortシグナルを返す
     - `action`: "abort"
     - `reason`: "Workflow exceeded maximum steps (最大ステップ数)"
     - `metadata`: 実行履歴、訪問回数辞書を含む

5. **コンテキスト保存**:
   - 更新された`_node_visit_counts`と`_execution_history`をワークフローコンテキストに保存
   - スコープ: workflow（ワークフロー全体で共有）

6. **正常終了**:
   - すべてのチェックをパスした場合、nullを返してノード実行を継続

**許容パターンチェックメソッド**:

**引数**: ノードID、実行履歴配列

**処理内容**:
1. `allowed_retry_patterns`辞書からノードIDに対応するパターン設定を取得
2. パターン設定が存在しない場合: Falseを返す（許容しない）
3. パターン設定が存在する場合: 実行履歴の最後の数ステップが許容パターンに一致するか確認
   - 例: plan_reflectionノードの場合、直前のノードがplanであれば許容
   - パターン例: `{"plan_reflection": {"allowed_from": ["plan"], "max_retries": 3}}`
4. パターンに一致し、かつリトライ回数が上限以内の場合: Trueを返す（許容）
5. それ以外: Falseを返す（許容しない）

**許容パターンの構築**:

LoopGuardMiddlewareの初期化時に、グラフ定義内の`role: "reflection"`を持つすべてのノードとその入辺エッジから`allowed_retry_patterns`を自動的に構築する。

- 各reflectionノードについて、入辺（そのノードへのエッジ）の`from`ノードIDを`allowed_from`として収集する
- `max_retries`はノードの`metadata.max_retries`から取得する（省略時は3）
- 構築例: `{"plan_reflection": {"allowed_from": ["code_generation_planning"], "max_retries": 3}}`

ハードコードされたデフォルトパターンは存在しない。グラフ定義の`role: "reflection"`ノードが存在しない場合、`allowed_retry_patterns`は空辞書となり、すべてのループが`max_visits_per_node`を超えた時点で異常と判定される。

**並行実行時の動作**:

各ワークフローは独立したコンテキストを持つため、訪問回数カウンターは他のワークフローと干渉しない。同一ワークフロー内では逐次実行されるため、カウンター更新の競合は発生しない。

**GitLab通知**:

無限ループ検出時にabortシグナルが返されると、WorkflowFactoryがWorkflowAbortedExceptionをスローし、最終的にConsumerのエラーハンドリングによってGitLabに以下の内容が通知される:

- エラー種別: "Infinite Loop Detected"
- 検出理由: 訪問回数超過またはステップ数超過
- 実行履歴: 最後の20ステップ
- 推奨アクション: グラフ定義の条件分岐を確認、または手動介入

##### 8.9.7.1 ContextStorageManagerの並列実行時の実装詳細

**責務**: ワークフローコンテキスト、タスク状態、エラー情報、トークン使用量などの永続化データの安全な並列アクセス制御

**トランザクション分離レベル**:

- **推奨レベル**: READ COMMITTED
  - 理由: 並列実行時の各エージェントは独立したタスクに対して動作するため、ダーティリードを防げば十分
  - 同一タスク内の複数ノード間での整合性はワークフローコンテキストで管理
  - 異なるタスク間では強い整合性は不要

**ロック戦略**:

1. **書き込み操作（楽観的ロック）**:
   - **対象**: タスク状態更新、ワークフローコンテキスト更新
   - **実装方式**: version列による楽観的ロック
   - **処理フロー**:
     1. 現在のversionとともにデータを読み出し
     2. 更新処理を実行（version = version + 1 WHERE version = 元のversion）
     3. 更新行数が0の場合は他のトランザクションが先に更新済みと判断
     4. 最大3回までリトライ（指数バックオフ: 100ms→200ms→400ms）
     5. リトライ失敗時はOptimisticLockExceptionをスロー
   - **並列実行時の動作**: 
     - 同一タスクの並列更新は通常発生しない（グラフの依存関係により逐次実行）
     - リトライ・再実行時のみ競合が発生する可能性あり

2. **読み取り操作（ロック不要）**:
   - **対象**: タスク情報取得、ワークフローコンテキスト取得、トークン使用量取得
   - **実装方式**: ロックなしの通常のSELECT
   - **理由**: READ COMMITTEDレベルで十分な一貫性を保証

3. **追記操作（ロック不要）**:
   - **対象**: エラー情報記録、トークン使用量記録、ログ記録
   - **実装方式**: 単純なINSERT（主キー自動生成）
   - **理由**: 追記のみで既存データを変更しないため競合が発生しない
   - **並列実行時の動作**: 複数エージェントが同時にエラー・トークン情報を記録可能

**非同期処理の範囲**:

1. **同期処理が必須の操作**:
   - タスク状態更新（pending→running→completed/failed）
   - ワークフローコンテキスト更新（エージェント間でのデータ受け渡しに使用）
   - エラー情報記録（エラー発生時の即座な記録が必須）
   - 理由: Middleware処理の成功・失敗判定、次ノードの実行可否判断に影響

2. **非同期処理が可能な操作**:
   - トークン使用量の詳細記録（メトリクス送信と同様）
   - ログの詳細記録（デバッグ目的の補足情報）
   - 理由: ワークフロー実行の制御フローに影響しない、遅延書き込みが許容される

**デッドロック回避策**:

- **単一テーブルアクセス**: 各操作は原則として単一テーブルのみをロック
- **ロック順序の統一**: 複数テーブルアクセスが必要な場合は常に tasks -> contexts -> errors の順序で取得
- **ロック保持時間の最小化**: トランザクション開始直前にデータ準備、クエリ実行後すぐにコミット
- **タイムアウト設定**: データベースクエリタイムアウトを10秒に設定（通常は1秒以内で完了）

**並列実行時の使用パターン例**:

- **TokenUsageMiddleware**:
  - 記録フィールド: task_uuid, node_id, agent_definition_id, execution_attempt, prompt_tokens, completion_tokens, total_tokens, cost, created_at
  - 操作種別: INSERT（追記、ロック不要）
  - 並列動作: 複数エージェントが同時にトークン使用量を記録可能

- **ErrorHandlingMiddleware**:
  - 記録フィールド: task_uuid, node_id, error_category, error_message, stack_trace, retry_count, created_at
  - 操作種別: INSERT（追記、ロック不要）
  - 並列動作: 複数エージェントが同時にエラー情報を記録可能

- **ConfigurableAgent（execution役割）**:
  - 操作: タスク状態更新（running → completed）、ワークフローコンテキスト更新（execution_results書き込み）
  - 操作種別: UPDATE（楽観的ロック使用）
  - 並列動作: 通常は発生しない（グラフ依存関係により逐次実行）

#### 8.8.8 Middlewareの登録と実行

**WorkflowFactory（ワークフローファクトリ）の役割**:

**責務**: Middlewareの登録管理とノード実行時の自動介入

**初期化処理**:
- Middlewareリスト（空配列）を初期化

**Middleware登録処理**:
- 引数として受け取ったMiddlewareインスタンスをリストに追加
- 登録順序が実行順序となる

**ノード実行メソッドの処理フロー**:

1. **before_executionフェーズのMiddleware実行**:
   - 登録されたすべてのMiddlewareを順番にループ
   - 各Middlewareの`intercept`メソッドを"before_execution"フェーズで呼び出し
   - MiddlewareSignalが返された場合、即座にシグナル処理メソッドを呼び出して終了
   - すべてのMiddlewareがnullを返した場合、次のステップへ

2. **ノード本体の実行**:
   - try-catchブロック内でノードのロジックを実行
   
3. **after_executionフェーズのMiddleware実行（成功時）**:
   - 登録されたすべてのMiddlewareを順番にループ
   - 各Middlewareの`intercept`メソッドを"after_execution"フェーズで呼び出し
   - 戻り値は無視（after_executionではフロー制御しない）
   
4. **on_errorフェーズのMiddleware実行（エラー時）**:
   - 例外が発生した場合のcatchブロック内で実行
   - 登録されたすべてのMiddlewareを順番にループ
   - 各Middlewareの`intercept`メソッドを"on_error"フェーズで呼び出し
   - 戻り値は無視
   - 最後に例外を再スロー

**Middlewareシグナル処理メソッド**:

**引数**: MiddlewareSignalオブジェクト、ワークフローコンテキスト

**処理分岐**:
- **actionが"redirect"の場合**:
  - `signal.redirect_to`で指定されたノードIDのノード実行メソッドを再帰的に呼び出し
  - 結果を返す
- **actionが"abort"の場合**:
  - ワークフロー中断例外（WorkflowAbortedException）をスロー
  - 例外メッセージには`signal.reason`を含める
- **actionが"skip"の場合**:
  - nullを返してノード実行をスキップ

**システム起動時の初期化処理**:

1. WorkflowFactoryインスタンスを生成
2. GitLabClientインスタンスを生成
3. ContextStorageManagerインスタンスを生成
4. MetricsCollectorインスタンスを生成
5. ProgressReporterインスタンスを生成（GitLabClient、ContextStorageManagerを引数に渡す）
6. 4つのMiddlewareインスタンスを生成:
   - CommentCheckMiddleware（GitLabClientを引数に渡す）
   - InfiniteLoopDetectionMiddleware（デフォルト設定で生成）
   - TokenUsageMiddleware（ContextStorageManager、MetricsCollectorを引数に渡す）
   - ErrorHandlingMiddleware（ContextStorageManager、GitLabClient、MetricsCollectorを引数に渡す）
7. WorkflowFactoryに対して4つのMiddlewareを順番に登録
8. AgentFactoryインスタンス生成時にProgressReporterを渡す
9. WorkflowFactoryインスタンスを返す

**Middleware実行順序の重要性**:
- CommentCheckMiddlewareは最初に実行（before_executionで早期リダイレクト可能）
- InfiniteLoopDetectionMiddlewareは2番目（before_executionで訪問回数チェック）
- TokenUsageMiddlewareは3番目（after_executionで記録）
- ErrorHandlingMiddlewareは最後に実行（on_errorで統一的にハンドリング）

#### 8.8.9 グラフ定義での適用指定

**CommentCheckMiddleware有効化**:

ノードmetadataで`check_comments_before: true`を指定。合わせて`comment_redirect_to`でリダイレクト先ノードIDを指定する。

| ノードタイプ | 適用推奨 | 推奨redirect_to | 理由 |
|------------|----------|-----------------|------|
| Planning系ノード | ✅ 推奨 | `task_classifier` | タスク種別の再判定が必要 |
| Plan Reflection | ✅ 推奨 | `task_classifier` | コメントによりタスク全体が変わりうる |
| Execution系ノード | ✅ 推奨 | `plan_reflection` | 既存の`plan_result`・Todoを保持したまま差分判定させるため |
| Review・テスト実行系ノード | ✅ 推奨 | `plan_reflection` | 実行結果を加味しながらコメントを差分判定させるため |

`check_comments_before: true`を指定する場合は`comment_redirect_to`も必須である。省略した場合は`validate_graph_definition()`でバリデーションエラーとなる。

**TokenUsageMiddleware、ErrorHandlingMiddleware、InfiniteLoopDetectionMiddleware**:

これらはすべてのノードに自動適用されるため、グラフ定義での個別指定は不要。WorkflowFactoryへの登録のみで全ワークフローに適用される。

#### 8.8.10 Middleware機構の利点

1. **グラフがシンプル**: ビジネスロジックに集中、横断的関心事は分離
2. **一元管理**: 共通処理が1箇所に集約され保守性が高い
3. **宣言的設定**: metadataで有効化するだけで機能追加
4. **テスト容易**: Middleware単体でテスト可能
5. **拡張性**: 新しいMiddleware（タイムアウト監視、監査ログなど）を追加しやすい
6. **非侵入的**: 既存ノードロジックを変更せずに機能追加
7. **デバッグ容易**: Middlewareのログで実行フローを追跡可能

## 9. Tool管理設計 (MCP)

### 9.1 MCP概要とAgent Framework統合

**参考**: [Model Context Protocol 公式サイト](https://modelcontextprotocol.io/) | [MCP Specification](https://spec.modelcontextprotocol.io/) | [MCP Servers](https://github.com/modelcontextprotocol/servers)

Model Context Protocol (MCP) を使用してツール実行を標準化し、Agent Frameworkのツールとして統合します。

**MCPサーバーとして実装し、Agent Frameworkツールとして統合するツール**:
- **Command Executor MCP**: Docker環境でのコマンド実行（`execute_command`、`clone_repository`、`install_dependencies`等）
  - Git操作は`command-executor` MCPを通じてgitコマンドを実行（例: `git add`, `git commit`, `git push`）
- **Text Editor MCP**: ファイル編集操作（`view_file`、`create_file`、`str_replace`、`insert_line`、`undo_edit`等）

**Agent Frameworkのネイティブツールとして実装するツール**:
- **TodoManagementTool**: Todoリスト管理（`create_todo_list`, `get_todo_list`, `update_todo_status`, `add_todo`, `delete_todo`, `reorder_todos`）
  - 注: Todoの作成・更新時に自動的にGitLab Issue/MRへ同期する。エージェントが明示的に同期ツールを呼ぶ必要はない

#### Agent FrameworkでのMCP統合パターン

**実装方法**:
1. **MCPクライアント生成**: stdio経由でMCPサーバーと通信するクライアントを生成
2. **Agent Frameworkツールとしてラップ**: MCPクライアントをAgent FrameworkのMCPStdioToolとしてラップ
3. **toolsリストに登録**: ラップしたツールをAgentのtools引数に直接渡す
4. **Agentで使用**: Agent FrameworkのAgentがツールとして使用可能になる

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

**注意**: `mcp/command_executor.py` は [coding_agent](https://github.com/notfolder/coding_agent) の [mcp/command_executor.py](https://github.com/notfolder/coding_agent/blob/main/mcp/command_executor.py) をそのまま使用する（新規実装不要）。

#### 9.2.1 ExecutionEnvironmentManager連携

command-executorとtext-editorはMCPサーバーとして実装するが、ExecutionEnvironmentManager上で動くので、handlers/execution_environment_mcp_wrapper.pyを参照して設計する。

**連携フロー**:

1. **Agent FrameworkがMCPツールを呼び出す**: ConfigurableAgent(Executor)がツール実行を要求
2. **MCPToolWrapperがノードIDを取得**: 現在実行中のノードIDをコンテキストから取得
3. **ExecutionEnvironmentManagerで環境IDを解決**: `get_environment(node_id)`で環境IDを取得
4. **環境内でMCPサーバーを起動**: 該当する環境のDocker内でMCPサーバープロセスを起動
5. **MCPクライアントが通信**: 環境内MCPサーバーにリクエストを送信
6. **結果を返す**: MCPサーバーからの結果をAgent Frameworkに返却

**実装クラス**:
- `ExecutionEnvironmentMCPWrapper`: 環境内MCPサーバー起動・通信を管理
- `EnvironmentAwareMCPClient`: ノードIDから環境IDを解決してMCP通信を行うクライアント

詳細設計は[セクション8.7](#87-実行環境管理executionenvironmentmanager)を参照。

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
| `create_todo_list` | Todoリスト作成（進捗コメントへ自動反映） | project_id, issue_iid/mr_iid, todos |
| `get_todo_list` | Todoリスト取得 | project_id, issue_iid/mr_iid |
| `update_todo_status` | Todo状態更新（進捗コメントへ自動反映） | todo_id, status |
| `add_todo` | Todo追加（進捗コメントへ自動反映） | project_id, issue_iid/mr_iid, title, description, parent_todo_id |
| `delete_todo` | Todo削除（進捗コメントへ自動反映） | todo_id |
| `reorder_todos` | Todo順序変更（進捗コメントへ自動反映） | todo_ids |

**Todo状態遷移**:
- `not-started` → `in-progress` → `completed`
- `not-started` → `failed`
- `in-progress` → `failed`

**進捗報告コメントへの統合**: 
Todoツール（`create_todo_list`, `update_todo_status`, `add_todo`, `delete_todo`, `reorder_todos`）は、実行後に自動的に`ProgressReporter`に`todo_changed`イベントを呈出する。`ProgressReporter`は最新のTodoリスト状態を進捗報告コメントのセクション③.5に反映してコメントを上書き更新する。Todo情報はGitLab Issue/MRへの別途投稿は行わず、進捗報告コメントに統合される。エージェントが明示的に同期ツールを呼ぶ必要はない。

### 9.4 Tool実行フロー

```mermaid
sequenceDiagram
    participant LLM
    participant Agent as ConfigurableAgent
    participant MCP as MCPToolClient
    participant Server as MCP Server
    participant External as External Service
    
    LLM->>Agent: function_call
    Agent->>MCP: call_tool(tool_name, args)
    MCP->>Server: execute(tool_name, args)
    Server->>External: API/Command
    External-->>Server: Result
    Server-->>MCP: Result
    MCP-->>Agent: Result
    Agent->>LLM: tool_result
```

---

## 10. エラー処理設計

### 10.1 エラー分類

| エラー種別 | 具体例 | 対応 |
|----------|--------|------|
| transient（一時的） | HTTP 5xx、タイムアウト | 自動リトライ |
| configuration（設定エラー） | HTTP 401、認証エラー、設定不正 | エラー通知、処理中断 |
| implementation（実装エラー） | バグ、未実装機能 | エラー通知、処理中断 |
| resource（リソースエラー） | メモリ不足、ディスク不足 | アラート、緊急停止 |

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

### 10.3 エラーハンドリングフロー

```mermaid
flowchart TD
    Error[エラー発生] --> Classify{エラー分類}
    
    Classify -->|transient| CheckRetry{リトライ回数}
    CheckRetry -->|上限未満| Backoff[バックオフ待機]
    Backoff --> Retry[リトライ実行]
    CheckRetry -->|上限到達| Notify
    
    Classify -->|configuration/implementation| Notify[エラー通知]
    Classify -->|resource| Alert[緊急アラート]
    
    Notify --> Record[エラー記録]
    Alert --> Emergency[緊急停止]
    
    Record --> Continue{処理継続可能?}
    Continue -->|Yes| Resume[処理再開]
    Continue -->|No| Stop[タスク中断]
```

### 10.4 エラー通知

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

## 11. 学習機能（Self-Learning System）

### 11.1 概要と目的

ワークフロー終了時にユーザーのMRコメントから自動的にガイドラインを学習し、PROJECT_GUIDELINES.mdを更新する機能。タスク処理の自然なサイクルの中でPROJECT_GUIDELINES.mdが成長し、システムの品質が向上する。

**目的**:
- ユーザーフィードバックから汎用的なルールを自動抽出
- プロジェクト固有の知見を体系的に蓄積
- 同じ指摘の繰り返しを防止
- ユーザー負担を軽減（明示的なガイドライン更新作業が不要）

**特徴**:
- データベース不要（ファイルベース）
- リアルタイム更新のみ（バッチ処理なし）
- グラフノードとして透過的に動作
- 設定でデフォルト有効

### 11.2 GuidelineLearningAgent

#### 基本設計

**継承元**: `BaseExecutor`（本システム共通Executor基底クラス）

**責務**: ワークフロー最終段階でユーザーフィードバックを学習してPROJECT_GUIDELINES.mdを更新する

**特徴**:
- グラフ定義ファイルに記載不要（WorkflowFactoryが自動挿入）
- 例外的に`GitLabClient`を保持してファイルコミット操作（PROJECT_GUIDELINES.md更新）が可能
- 他のエージェント（ConfigurableAgent等）と異なり固定実装
- 学習失敗してもワークフローは継続（エラー耐性）

#### 保持する依存性

- `config`: 学習機能の設定
- `gitlab_client`: GitLab API操作（例外的に保持）
- `progress_reporter`: 進捗報告機能

#### 主要処理フロー

`handle(self, msg, ctx: WorkflowContext)`メソッドで以下を実行する：

1. **学習機能有効性チェック**: 設定で無効な場合は即座に終了
2. **タスク情報取得**: ワークフローコンテキストからタスク情報を取得
3. **MRコメント取得**: GitLab APIでMRコメント一覧を取得し、以下の条件でフィルタリング
   - タスク開始時刻以降のコメントのみ
   - 人間が投稿したコメントのみ（Botコメントを除外）
4. **ガイドライン読み込み**: PROJECT_GUIDELINES.mdを読み込む（存在しない場合は初期テンプレートを使用）
5. **LLM判断**: Agent標準機能を使用してLLMに単一呼び出し
   - 入力: ユーザーコメント、現在のガイドライン、タスクコンテキスト
   - 出力: JSON形式（should_update, updated_guidelines, rationale, category）
6. **ガイドライン更新**: 更新が必要な場合のみ実行
   - ファイル書き込み
   - git commit & push（例外的に許可）
   - MRコメント投稿（更新通知）
7. **応答返却**: AgentResponseを返してワークフロー継続

#### LLMプロンプト設計

**システムプロンプト**:

プロジェクトのガイドライン管理者として、ユーザーのフィードバックから一般化可能なルールを抽出する役割を担う。以下の判断基準で評価する：

- **汎用性**: このルールは他のタスクでも適用できるか
- **妥当性**: ルールは合理的で制限が厳しすぎないか
- **新規性**: 既存のガイドラインに含まれていないか
- **明確性**: ルールは明確で誤解の余地がないか

**ユーザープロンプト構成**:

- タスク情報（タスク種別、タイトル、説明）
- ユーザーコメント一覧（投稿者名、本文）
- 現在のPROJECT_GUIDELINES.md全文
- 抽出対象（含めるべきもの）と除外対象（含めないもの）の明示
- 出力形式の指定（JSON）

**出力形式**:

JSON形式で以下を含む：
- `should_update`: 更新が必要か（true/false）
- `rationale`: 更新判断の理由（日本語）
- `category`: カテゴリ（documentation, code, review, workflow, general）
- `updated_guidelines`: 更新後のPROJECT_GUIDELINES.md全文（更新時のみ）

### 11.3 処理フロー

```mermaid
sequenceDiagram
    participant WF as WorkflowFactory
    participant Graph as Workflow Graph
    participant LA as GuidelineLearningAgent
    participant GL as GitLab API
    participant LLM as LLM
    participant Git as Git Repository
    
    Note over WF: ワークフロー生成時
    WF->>WF: load_graph_definition()
    WF->>UserAPI: get_user_config(user_email)
    UserAPI-->>WF: learning_enabled他学習設定
    WF->>WF: check user_config.learning_enabled
    
    alt user_config.learning_enabled = true
        WF->>Graph: 学習ノードを自動挿入<br/>review→learning→end
        WF->>LA: GuidelineLearningAgent生成<br/>（gitlab_client注入）
        WF->>LA: user_configの学習設定を注入
    end
    
    Note over Graph: ワークフロー実行時
    Graph->>Graph: Planning実行
    Graph->>Graph: Execution実行
    Graph->>Graph: Review実行
    Graph->>LA: invoke_async()<br/>学習ノード自動実行
    
    LA->>GL: get_mr_comments()<br/>（人間コメントのみ）
    GL-->>LA: コメント一覧
    
    LA->>Git: read_file(PROJECT_GUIDELINES.md)
    Git-->>LA: 現在の内容
    
    LA->>LLM: get_chat_completion()<br/>（判断+更新内容生成）
    LLM-->>LA: JSON応答
    
    alt should_update = true
        LA->>Git: write_file(PROJECT_GUIDELINES.md)
        LA->>Git: commit_and_push()<br/>（例外的に許可）
        LA->>GL: post_mr_comment()<br/>「ガイドライン更新」
    end
    
    LA-->>Graph: AgentResponse(success=True)
    Graph->>Graph: ワークフロー完了
```

### 11.4 設定

学習機能の各パラメータはシステムのconfig.yamlではなく、ユーザー管理画面（SC-04/SC-05/SC-06/SC-13）でユーザーごとに設定・変更する。デフォルト値は全ユーザーで共通。

**設定項目**（`user_configs`テーブルの学習機能関連カラム）:

- `learning_enabled`: 学習機能の有効/無効（デフォルト: true。trueでノード自動挿入、falseで挿入しない）
- `learning_llm_model`: 判断用LLMモデル（デフォルト: 'gpt-4o'。ユーザーの通常タスク用モデル（model_name）とは独立して設定できる）
- `learning_llm_temperature`: LLM温度パラメータ（デフォルト: 0.3。低めで安定した判断）
- `learning_llm_max_tokens`: 最大トークン数（デフォルト: 8000。全文生成のため多めに設定）
- `learning_exclude_bot_comments`: Botコメントを除外するか（デフォルト: true）
- `learning_only_after_task_start`: タスク開始後のコメントのみ対象とするか（デフォルト: true）

**設定の検証範囲**: learning_llm_temperature (0.0〜2.0)、learning_llm_max_tokens (1,000〜32,000)

### 11.5 例外処理：git操作の許可

#### 設計原則

**原則**: 通常のエージェント（ConfigurableAgent等）はgit commit & push操作を行わない。コード変更はMCPツール（text-editor）経由で行い、git操作はワークフロー外で実行する。

**例外**: GuidelineLearningAgentのみが例外的にgit commit & pushを実行する。

#### 例外の理由

- ガイドライン更新は特殊な操作であり、ワークフロー内で完結させる必要がある
- PROJECT_GUIDELINES.mdはコード実装とは独立したメタデータである
- 更新履歴をGit履歴で追跡可能にする必要がある
- セキュリティリスクを局所化（1つのエージェントクラスのみに制限）

#### 実装上の制御

- GuidelineLearningAgentのコンストラクタでのみgitlab_clientを注入
- 他のエージェント（ConfigurableAgent）はこのクライアントを保持しない
- コードレビュー時に例外処理であることを明示的に確認

### 11.6 エラーハンドリング

学習処理が失敗してもワークフローは継続する。

**エラー処理方針**:

- すべての処理をtry-exceptブロックで囲む
- 例外発生時はエラーログを記録し、`AgentResponse(success=False)`を返す
- ワークフローエンジンはfalse応答でもワークフローを継続
- 学習はオプショナルな機能であり、失敗してもタスク自体は成功とみなす

**エラー種別と対応**:

- GitLab API エラー: ログ記録して継続（コメント取得失敗は致命的ではない）
- ファイル読み込みエラー: 初期テンプレートを使用して継続
- LLM呼び出しエラー: リトライ（最大3回）後、失敗したら継続
- JSON解析エラー: ログ記録して継続（LLM応答が不正な場合）
- Git操作エラー: ログ記録して継続（競合等）

### 11.7 PROJECT_GUIDELINES.md構造

YAMLフロントマター形式でシステムプロンプトに自動組み込まれる。

**ファイル構造**:

```markdown
---
name: ProjectGuidelines
about: タスク処理から学習したプロジェクトガイドライン
---

# プロジェクトガイドライン

本ファイルは、タスク処理中のユーザーフィードバックから自動的に学習・更新されます。

## 1. ドキュメント作成ガイドライン

### ER図は全エンティティを省略せず描くこと

**理由**: データベース設計の全体像を正確に把握するため
**出典**: タスクXYZ（2026/03/09）

### コード例は記述せず、日本語で処理を記述すること

**理由**: 仕様書はコード実装の前段階であり、コード例は実装時の制約となるため
**出典**: 複数のタスクで指摘

## 2. コード実装ガイドライン

（LLMが自動追加）

## 3. レビューガイドライン

（LLMが自動追加）

## 4. ワークフローガイドライン

（LLMが自動追加）

## 5. 一般ガイドライン

（LLMが自動追加）
```

**カテゴリ別セクション**:

- documentation: ドキュメント作成の規約
- code: コード実装の規約
- review: レビュー観点
- workflow: ワークフロー実行の基準
- general: その他の一般的なルール

---

## 12. セキュリティ設計

### 12.1 認証・認可

#### GitLab認証

システム全体で1つのGitLab bot用Personal Access Token（PAT）を使用する。環境変数`GITLAB_PAT`で設定し、すべてのGitLab API操作に使用する。

#### OpenAI API認証

ユーザーごとにOpenAI APIキーを管理する。User Config APIから暗号化されたAPIキーを取得し、復号化して使用する。

#### User Config API認証

Bearer TokenによるJWT（HS256）認証を使用する。トークン有効期限は24時間とし、自動リフレッシュを行う。

### 12.2 暗号化

#### APIキー暗号化

AES-256-GCMアルゴリズムを使用してAPIキーを暗号化する。暗号化キーは環境変数ENCRYPTION_KEYで管理し（32バイト）、Pythonのcryptographyライブラリで実装する。暗号化・復号化はEncryptionServiceクラスに集約し、DBへの保存前に必ず暗号化を行う。

---

## 13. 運用設計

### 13.1 デプロイ構成（Producer/Consumer + RabbitMQ）

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
    command: npm run dev -- --host 0.0.0.0
    working_dir: /app/web-config
    env_file: .env
    environment:
      VITE_API_URL: http://user-config-api:8080
    ports:
      - "5173:5173"
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

### 13.2 スケーリング戦略（Producer/Consumerパターン）

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

### 13.3 監視・ログ

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

### 13.4 ワークフロー停止・再開機構

#### 13.4.1 概要と目的

メンテナンスやシステムアップデート時に、実行中のワークフローを安全に停止し、作業完了後に処理を継続できる仕組みを提供する。Dockerコンテナが存在する前提での停止・再開をサポートし、コンテナが失われた場合はタスクを失敗として扱う。

**対応範囲**:
- 計画的な停止（メンテナンス、アップデート）
- Dockerコンテナの保持（停止のみ、削除しない）
- ワークフロー状態とDocker環境マッピングの永続化
- 再起動時の自動再開処理

**対応外**:
- Dockerコンテナが失われた場合の復旧（タスク失敗として扱う）
- Dockerボリュームの永続化（不要）
- クラッシュからの復旧（計画停止のみ対応）

#### 13.4.2 ワークフロー状態の永続化

**データベーステーブル: workflow_execution_states**

ワークフロー実行の状態を記録し、再開時に復元するための情報を保存する。

| カラム名 | 型 | 説明 |
|---------|-----|------|
| execution_id | UUID (PK) | ワークフロー実行の一意識別子 |
| task_uuid | UUID (FK) | tasksテーブルへの外部キー |
| workflow_definition_id | VARCHAR | 使用中のワークフロー定義ID |
| current_node_id | VARCHAR | 実行中または次に実行するノードID |
| completed_nodes | JSONB | 完了したノードIDの配列 |
| workflow_status | VARCHAR | 実行状態（running/suspended/completed/failed） |
| suspended_at | TIMESTAMP | 停止日時 |
| created_at | TIMESTAMP | ワークフロー開始日時 |
| updated_at | TIMESTAMP | 最終更新日時 |

**データベーステーブル: docker_environment_mappings**

Docker環境とノードの対応関係を永続化し、再開時にコンテナを再利用するための情報を保存する。

| カラム名 | 型 | 説明 |
|---------|-----|------|
| mapping_id | UUID (PK) | マッピングの一意識別子 |
| execution_id | UUID (FK) | workflow_execution_statesへの外部キー |
| node_id | VARCHAR | ワークフローノードID |
| container_id | VARCHAR | DockerコンテナID |
| container_name | VARCHAR | Dockerコンテナ名 |
| environment_name | VARCHAR | 環境名（python/miniforge/node/default） |
| status | VARCHAR | コンテナ状態（running/stopped） |
| created_at | TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | 最終更新日時 |

**コンテナ命名規則**:
```
coding-agent-exec-{execution_id}-{node_id}
```

実行IDとノードIDを含めることで、停止後の再開時にコンテナを一意に識別可能とする。

#### 13.4.3 グレースフルシャットダウン

**シグナルハンドリング**

Consumerプロセスが受信するシグナルと動作：

- **SIGTERM（計画停止）**:
  1. 新規タスクの受信を停止（RabbitMQからのprefetch停止）
  2. 実行中のワークフローが現在のノード処理を完了するまで待機（最大5分）
  3. 現在のノード完了後、ワークフロー状態をworkflow_execution_statesテーブルに保存
  4. Docker環境マッピングをdocker_environment_mappingsテーブルに保存
  5. すべてのDockerコンテナを停止（docker stop、削除しない）
  6. プロセス終了

- **タイムアウト処理**: 
  - ノード完了を5分待機しても完了しない場合は強制停止
  - 実行中のノードはcurrent_node_idに記録して次回再実行

**停止可能なタイミング**

安全に停止できるポイント：
- ノード実行完了後（出力データをワークフローコンテキストに保存済み）
- 次のノードに進む直前

停止すべきでないタイミング：
- LLM呼び出し中
- ツール実行中
- Git操作実行中（これらは完了を待つ）

#### 13.4.4 再開処理

**再開フロー**

```mermaid
flowchart TD
    Start[Consumer起動] --> Query[DB検索: workflow_status=suspended]
    Query --> HasSuspended{停止中タスクあり?}
    HasSuspended -->|No| Normal[通常処理開始<br/>RabbitMQからタスク取得]
    HasSuspended -->|Yes| LoadState[ワークフロー状態読み込み<br/>workflow_execution_states]
    LoadState --> LoadMapping[環境マッピング読み込み<br/>docker_environment_mappings]
    LoadMapping --> CheckContainers[Docker: コンテナ存在確認<br/>docker ps -a]
    CheckContainers --> AllExist{すべて存在?}
    AllExist -->|No| MarkFailed[タスクを失敗としてマーク<br/>GitLabにエラーコメント投稿]
    AllExist -->|Yes| StartContainers[コンテナ起動<br/>docker start]
    StartContainers --> RestoreContext[ワークフローコンテキスト復元<br/>PostgreSQLから読み込み]
    RestoreContext --> RestoreEnvManager[ExecutionEnvironmentManager<br/>環境マッピング復元]
    RestoreEnvManager --> ResumeWorkflow[current_node_idから<br/>ワークフロー再開]
    ResumeWorkflow --> UpdateStatus[workflow_status=running更新]
    UpdateStatus --> Execute[ノード実行継続]
    MarkFailed --> Next[次の停止タスク処理]
    Execute --> Next
    Next --> HasSuspended
```

**コンテナ存在確認**

docker ps -aコマンドで停止中を含むすべてのコンテナを検索し、必要なコンテナがすべて存在するか確認する。フィルタ条件としてコンテナ名のパターン（coding-agent-exec-{execution_id}-*）を使用する。

**コンテナが失われた場合の処理**

一つでもコンテナが存在しない場合：
1. workflow_statusをfailedに更新
2. GitLab MRにエラーコメントを投稿（「メンテナンス中にDocker環境が失われたため、タスクを継続できません」）
3. 存在するコンテナをすべて削除（docker rm -f）
4. 環境マッピングレコードを削除
5. 次の停止タスクの処理に進む

**コンテナ起動とワークフロー再開**

すべてのコンテナが存在する場合：
1. 各コンテナをdocker startで起動
2. ワークフローコンテキストをPostgreSQLから読み込む
3. ExecutionEnvironmentManagerの環境マッピング（node_to_env_map）を復元
4. Agent FrameworkのWorkflowをcurrent_node_idから再開
5. workflow_statusをrunningに更新
6. 通常のノード実行を継続

#### 13.4.5 実装への影響

**ExecutionEnvironmentManagerの拡張**

新規メソッド：
- `save_environment_mapping(execution_id)`: 環境マッピングをDBに保存
- `load_environment_mapping(execution_id)`: 環境マッピングをDBから復元
- `stop_all_containers(execution_id)`: 実行IDに関連するすべてのコンテナを停止
- `start_all_containers(execution_id)`: 実行IDに関連するすべてのコンテナを起動
- `check_containers_exist(execution_id)`: すべてのコンテナが存在するか確認

コンテナ作成時の変更：
- コンテナ名に実行IDとノードIDを含める（coding-agent-exec-{execution_id}-{node_id}）
- 作成時にdocker_environment_mappingsテーブルにレコード挿入

**WorkflowFactoryの拡張**

新規メソッド：
- `save_workflow_state(execution_id, current_node_id, completed_nodes)`: ワークフロー状態をDBに保存
- `load_workflow_state(execution_id)`: ワークフロー状態をDBから復元
- `resume_workflow(execution_id)`: 停止したワークフローを再開

シグナルハンドラの実装：
- SIGTERMシグナルをキャッチする処理を追加
- 実行中のノード完了を最大5分待機
- タイムアウト時は強制停止してワークフロー状態を保存

**Consumerの拡張**

起動時処理：
1. workflow_status=suspendedのレコードをworkflow_execution_statesテーブルから検索
2. 各停止タスクに対して再開処理を実行（コンテナ確認→起動→再開）
3. すべての再開処理完了後、通常のキュー処理を開始

シャットダウン処理：
1. SIGTERMシグナル受信時にシャットダウンフラグを設定
2. RabbitMQからの新規メッセージ受信を停止
3. 実行中のワークフローの現在ノード完了を待機
4. ワークフロー状態とDocker環境マッピングを保存
5. Dockerコンテナを停止
6. プロセス終了

#### 13.4.6 運用手順

**計画停止の手順**

1. Producerを停止（新規タスク検出を停止）
2. 全ConsumerにSIGTERMシグナルを送信（docker-compose stop consumer または kill -TERM）
3. Consumerのログで「Graceful shutdown completed」メッセージを確認
4. PostgreSQLとRabbitMQのバックアップを実施
5. メンテナンス作業を実施
6. Consumer再起動（docker-compose start consumer）
7. Consumerログで停止タスクの再開を確認
8. Producer再起動

---

## 14. 設定ファイル定義

### 14.1 config.yaml（完全定義）

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
    # システムデフォルト（ユーザー設定とモデル推奨値がない場合の最終フォールバック）
    default_token_threshold: 5600  # 環境変数: CONTEXT_COMPRESSION_DEFAULT_TOKEN_THRESHOLD
    default_keep_recent: 10  # 環境変数: CONTEXT_COMPRESSION_DEFAULT_KEEP_RECENT
    default_min_to_compress: 5  # 環境変数: CONTEXT_COMPRESSION_DEFAULT_MIN_TO_COMPRESS
    default_min_compression_ratio: 0.8  # 環境変数: CONTEXT_COMPRESSION_DEFAULT_MIN_COMPRESSION_RATIO
    
    # モデル別推奨token_threshold（コンテキストウィンドウの70%）
    model_recommendations:
      "gpt-4o": 90000
      "gpt-4-turbo": 90000
      "gpt-4": 5600
      "gpt-3.5-turbo": 11000
      "gpt-3.5-turbo-16k": 11000
      "o1-preview": 90000
      "o1-mini": 90000
    
    # 要約生成用LLM設定
    summary_llm_model: "gpt-4o-mini"  # 環境変数: CONTEXT_COMPRESSION_SUMMARY_LLM_MODEL
    summary_llm_temperature: 0.3  # 環境変数: CONTEXT_COMPRESSION_SUMMARY_LLM_TEMPERATURE
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

```

### 14.2 設定管理クラス設計

#### 14.2.1 ConfigManager

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
- `validate()`: 設定値のバリデーションを実行しエラーリストを返す
- `reload()`: 設定をリロード（開発/テスト用）

#### 14.2.2 設定データクラス

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

各データクラスはPydanticの`BaseModel`を継承し、`Field`でデフォルト値と検証ルールを定義する。必要に応じて`@validator`デコレータでカスタムバリデーションを追加する。

#### 14.2.3 環境変数マッピング

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

**環境変数の優先順位**:
1. 環境変数（最優先）
2. config.yamlのデフォルト値
3. Pydanticモデルのデフォルト値

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
   - BaseHistoryProvider: PostgreSQL永続化（PostgreSqlChatHistoryProvider）
   - BaseContextProvider: プランニング履歴管理（PlanningContextProvider）
   - BaseContextProvider: ツール実行結果管理（ToolResultContextProvider）
   - state: dict: セッション状態管理（ProviderSessionState<T>はPython AFでは使用しない）
   - WorkflowContext: ワークフロー内共有状態管理

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
   - BaseHistoryProviderを継承してPostgreSQL永続化を実装
   - BaseContextProviderを継承してプランニング・ツール結果管理を実装
   - state: dictでセッション状態管理を実現（ProviderSessionState<T>はPython AFでは使用しない）
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

## 付録B: Agent Framework vs coding_agent 対応表

| 機能 | coding_agent | # AutomataCodex (Agent Framework) |
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
