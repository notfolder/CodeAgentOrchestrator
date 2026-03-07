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
  - **[Process Framework (Workflow/Executor)](https://learn.microsoft.com/ja-jp/python/api/agent-framework-core/agent_framework.executor)**: ワークフロー実行とExecutor管理
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

#### 2.3.2 Issue→MR変換 Layer（前処理フロー）

| コンポーネント | 責務 | Agent Frameworkクラス | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|---------------------|
| **IssueToMRConverter** | Issue→MR変換 | Agent Framework Workflow | Agent FrameworkのProcess Frameworkを使用してIssue→MR変換ワークフローを実装 |
| **Branch Naming Agent** | ブランチ名生成 | [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python) | [coding_agent](https://github.com/notfolder/coding_agent)を参考にして、Semantic KernelのChatCompletionAgentを使用してLLMにブランチ名生成を依頼 |

#### 2.3.3 MR処理 Layer（本フロー - Agent Framework）

| コンポーネント | 責務 | Agent Frameworkクラス | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|---------------------|
| **WorkflowFactory** | ワークフロー生成・環境準備 | Agent Framework Process Framework | グラフ定義からAgent FrameworkのWorkflowを動的に生成し、Docker環境を準備する |
| **WorkflowBuilder** | グラフ構造からワークフロー構築 | Agent Framework Workflow | グラフ定義のノード・エッジをAgent FrameworkのWorkflow構造に変換 |
| **ConfigurableAgent** | エージェントノード実行 | [`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python) | エージェント定義とプロンプト定義に基づいて動作する汎用エージェント |
| **MCPToolClient** | ファイル編集・コマンド実行 | Agent Framework MCP統合 | Agent FrameworkのMCPツール統合機能を使用してMCP Server (text-editor、command-executor)をAgent Frameworkツールとして統合 |
| **ExecutionEnvironmentManager** | Docker環境管理・環境プール管理 | 独自実装 | [handlers/execution_environment_manager.py](https://github.com/notfolder/coding_agent/blob/main/handlers/execution_environment_manager.py) 参考、独自クラスとして実装。Docker環境のプール管理、割り当て、クリーンアップを担当。詳細は[セクション8.8](#88-実行環境管理executionenvironmentmanager)を参照 |

**実装方針**: 
- グラフ定義・エージェント定義・プロンプト定義をworkflow_definitionsテーブルから読み込み、動的にワークフローを構築
- MCPサーバー（text-editor、command-executor）はAgent FrameworkのMCPツール統合機能を使用してAgent Frameworkのツールとして登録する
- カスタムツール（todo管理等）はMCPサーバーではなく、Agent Frameworkのネイティブツールとして直接実装する

#### 2.3.4 Runtime Layer

| コンポーネント | 責務 | 実装技術 | Agent Framework | [coding_agent](https://github.com/notfolder/coding_agent)参照・実装方針 |
|------------|------|---------|----------------|---------------------|
| **UserManager** | ユーザー情報・APIキー管理 | PostgreSQL + FastAPI | - | - |
| **PostgreSqlChatHistoryProvider** | 会話履歴永永化 | PostgreSQL | Semantic Kernel [ChatHistory](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python)パターン | [context_storage/message_store.py](https://github.com/notfolder/coding_agent/blob/main/context_storage/message_store.py)参考、独自のHistory管理クラス実装 |
| **PlanningContextProvider** | プラン・要約永続化 | PostgreSQL | 独自Provider実装 | [context_storage/summary_store.py](https://github.com/notfolder/coding_agent/blob/main/context_storage/summary_store.py)参考、カスタムコンテキスト管理 |
| **ToolResultContextProvider** | ツール実行結果永続化 | File + PostgreSQL | 独自Provider実装 | [context_storage/tool_store.py](https://github.com/notfolder/coding_agent/blob/main/context_storage/tool_store.py)参考、ファイル+DB複合ストレージ |
| **PostgreSQL** | Context Storage + ユーザー情報 | PostgreSQL | - | - |
| **File Storage** | ツール実行結果保存 | ローカルファイルシステム | - | - |

---

## 3. ユーザー管理システム

ユーザーごとのOpenAI APIキー、LLM設定、プロンプトカスタマイズ、ワークフロー定義の選択を管理する。詳細な設計、データベーススキーマ、API仕様については**[USER_MANAGEMENT_SPEC.md](USER_MANAGEMENT_SPEC.md)**を参照。

**主要機能**:
- **ユーザー登録・管理**: メールアドレスベースのユーザー管理
- **APIキー管理**: OpenAI APIキーの暗号化保存（AES-256-GCM）
- **プロンプトカスタマイズ**: エージェントごとのプロンプト上書き（13エージェント対応）
- **ワークフロー定義管理**: システムプリセット（standard_mr_processing、multi_codegen_mr_processing）とユーザー独自定義
- **トークン統計**: ユーザー別のLLMトークン使用量記録
- **Web管理画面**: Streamlitベースのダッシュボード

**データベーステーブル**（詳細は [DATABASE_SCHEMA_SPEC.md](DATABASE_SCHEMA_SPEC.md) を参照）:
- `users` - ユーザー基本情報
- `user_configs` - LLM設定（APIキー、モデル、プロバイダ）
- `agent_prompt_overrides` - エージェント別プロンプト上書き
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

### 4.3.2 エージェントノード一覧

グラフ内の各ノードは`ConfigurableAgent`クラスまたは`BaseExecutor`サブクラスで実装される。各ノードの詳細な処理フロー・責務・設定については**[AGENT_DEFINITION_SPEC.md](AGENT_DEFINITION_SPEC.md)のセクション7「各エージェントノードの詳細説明」**を参照する。

**主要なエージェントノード**:
- User Resolver Executor（前処理）
- Task Classifier Agent（タスク分類）
- Planning Agent群（code_generation_planning, bug_fix_planning, test_creation_planning, documentation_planning）
- Plan Reflection Agent（プラン検証）
- Execution Agent群（code_generation, bug_fix, documentation, test_creation）
- Test Execution & Evaluation Agent（テスト実行・評価）
- Review Agent群（code_review, documentation_review）

**注**: 上記の各ノードの**詳細な処理フロー、エージェント定義設定、利用可能なツール、出力形式、エラーハンドリング**については[AGENT_DEFINITION_SPEC.md](AGENT_DEFINITION_SPEC.md)を参照。プロンプト詳細は[PROMPTS.md](PROMPTS.md)および各プロンプト定義ファイルを参照。

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
- `multi_codegen_mr_processing`: 複数コード生成並列実行（3種類のモデル・温度設定で並列実行）
  - グラフ定義: 標準と同じグラフに並列実行ノードを追加
  - エージェント定義: [AGENT_DEFINITION_SPEC.md セクション4.2](AGENT_DEFINITION_SPEC.md#42-複数コード生成並列エージェント定義multi_codegen_mr_processing)参照
  - プロンプト定義: [PROMPT_DEFINITION_SPEC.md セクション4.2](PROMPT_DEFINITION_SPEC.md#42-複数コード生成並列プロンプト定義multi_codegen_mr_processing)参照

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

4. **循環依存チェック**:
   - グラフ内に無限ループを引き起こす循環依存が存在しないか
   - 具体的には、各ノードから到達可能な終了ノード（`to: null`のエッジを持つノード）が少なくとも1つ存在するか
   - DFS（深さ優先探索）を使用して循環を検出する

5. **孤立ノードのチェック**:
   - `entry_node`から到達できないノードが存在しないか
   - BFS（幅優先探索）で到達可能性を確認する

6. **条件式の構文チェック**:
   - `condition`フィールドが存在する場合、その条件式が有効なPython式として評価可能か
   - 基本チェック: `eval(condition, {"context": {}, "config": {}})`で構文エラーが発生しないか

7. **requires_environment集計**:
   - `requires_environment: true`のノード数を数えて返す
   - この数値は`WorkflowFactory._setup_environments()`で必要なDocker環境数の根拠となる

**戻り値**: 検証成功時は`requires_environment: true`のノード数を返す。検証失敗時は`DefinitionValidationError`例外をスローする。

##### validate_agent_definition(agent_def, graph_def)

エージェント定義がグラフ定義と整合しているか検証する。以下のチェックを実施する:

1. **必須フィールドの存在確認**:
   - `version`, `agents`が存在するか
   - 各エージェントに`id`, `role`, `input_keys`, `output_keys`, `tools`, `prompt_id`が存在するか

2. **グラフ定義との整合性**:
   - グラフ定義の各ノードで参照される`agent_definition_id`に対応するエージェント定義が`agents`配列内に存在するか
   - ノードタイプが`"agent"`の場合、対応するエージェント定義が必須

3. **roleの有効値チェック**:
   - 各エージェントの`role`が"planning"、"reflection"、"execution"、"review"のいずれかであるか

4. **toolsの有効値チェック**:
   - 各エージェントの`tools`配列内のツール名がすべてシステムに登録済みのツール名一覧に含まれるか
   - 登録可能なツール: `text_editor`, `command_executor`, `create_todo_list`, `get_todo_list`, `update_todo_status`, `sync_to_gitlab`, `get_mr_context`, `get_issue_context`

5. **input_keysとoutput_keysの一貫性**:
   - 同じエージェント内で`input_keys`と`output_keys`に同じキー名が含まれていないか
   - エージェントは入力か出力のどちらか一方のみでキーを使用するべき

6. **output_keysの一意性（並列実行対応）**:
   - 複数のエージェントが同じ`output_keys`を使用していないか
   - 並列実行ノードの場合、`execution_result_fast`のようにサフィックスを付与して区別する必要がある

7. **toolsとroleの整合性**:
   - `requires_environment: true`のノードの場合、`role`が"execution"または"review"であるか
   - "planning"と"reflection"は環境不要のため、`requires_environment: false`であるべき

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
- `_setup_environments(graph_def)`: グラフ定義内で`requires_environment: true`のノードに対してDocker環境を準備する（Agent FrameworkのExecutorとして実装）

**複数環境のサポート**:
グラフ定義でノードごとに`requires_environment`フラグを設定することで、必要なノード分の実行環境を事前に作成する。これにより、複数のコーディングエージェントノードが独立した環境で並列実行可能になる。

**環境準備と割り当ての詳細**:
1. **環境数の決定**: `validate_graph_definition()` が `requires_environment: true` のノード数を集計し、WorkflowFactory がその数分のDocker環境を準備する
2. **環境プール管理**: ExecutionEnvironmentManager が環境プールを管理し、各 `requires_environment: true` ノードに一意の環境IDを割り当てる
3. **並列実行時の分離**: 並列に実行される複数のコード生成ノード（例: code_generation_fast, code_generation_standard, code_generation_creative）は、それぞれ独立したDocker環境を使用し、相互に干渉しない
4. **環境のクリーンアップ**: ワークフロー完了時または異常終了時に、すべての準備済み環境を自動的にクリーンアップする

詳細設計は[セクション8.8](#88-実行環境管理executionenvironmentmanager)を参照。

**例**: `multi_codegen_mr_processing` プリセットでは、3つの並列コード生成ノード + test_execution_evaluation ノード = 合計4つのDocker環境が事前に準備される。

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
1. **Provider方式によるコンテキスト管理**: `PostgreSqlChatHistoryProvider`、`PlanningContextProvider`、`ToolResultContextProvider`を使用し、[ChatHistory](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history?pivots=programming-language-python)パターンでコンテキストを永続化する
2. **Filters方式によるトークン統計**: `TokenUsageMiddleware`を使用し、すべての[`ChatCompletionAgent`](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-chat?pivots=programming-language-python)呼び出しを自動的にインターセプトしてトークン使用量を記録する
3. **プロンプト上書き機能**: `PromptOverrideManager`と`agent_prompt_overrides`テーブルを使用し、ユーザーごとに全6エージェントのプロンプトを個別カスタマイズ可能にする
4. **Factory方式によるオブジェクト生成**: `AgentFactory`、`MCPClientFactory`を使用し、タスクタイプに応じた適切なエージェントとコンポーネントを生成する
5. **Strategy方式によるタスク処理**: `TaskStrategyFactory`を使用し、Issue→MR変換判定などのタスク固有の処理戦略を決定する
6. **共有リソースの再利用**: `ExecutionEnvironmentManager`、`MCPClientRegistry`、`ContextStorageManager`等を複数タスク処理で再利用し、リソース効率を最適化する

#### 5.1.2 オブジェクト構造図

オブジェクト構造の詳細な図（Producer/Consumer層、Agent Framework層、MCPクライアント層、共有リソース層の関係）は実装フェーズで作成予定。

**主要コンポーネント間の関係**:
- **Producer/Consumer層**: RabbitMQ経由でタスクをやり取り
- **WorkflowFactory**: グラフ定義に基づいてWorkflowを生成し、各種Factoryを保持
- **ExecutorFactory**: グラフ定義のexecutor_typeに基づいてExecutorを生成
- **AgentFactory**: エージェント定義に基づいてConfigurableAgentを生成
- **MCPClientFactory**: MCPサーバーとの通信クライアントを生成
- **ContextStorageManager**: PostgreSQL経由でコンテキストを永続化
- **ExecutionEnvironmentManager**: Docker環境を複数タスクで共有管理

---

## 6. 進捗報告機能

### 6.1 概要

[coding_agent](https://github.com/notfolder/coding_agent)と同様に、各フェーズでの進捗状況をMRにコメントとして投稿し、ユーザーに可視性を提供します。

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

ProgressReporterクラスを実装し、各エージェントから呼び出す。[coding_agent](https://github.com/notfolder/coding_agent)のコードを参考にして実装する。

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

タスク実行状態はPostgreSQLで管理します。

#### tasksテーブル

タスクの実行状態、進捗、メタデータを管理するテーブルです。詳細定義は **[DATABASE_SCHEMA_SPEC.md セクション4.1](DATABASE_SCHEMA_SPEC.md#41-tasksテーブル)** を参照してください。

**主要フィールド**:
- `uuid`: タスクUUID（主キー）
- `task_type`: タスク種別（issue_to_mr/mr_processing）
- `status`: 状態（running/completed/paused/failed）
- `metadata`: シリアル化されたセッション情報を含むJSONBデータ

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

### 8.8 実行環境管理（ExecutionEnvironmentManager）

#### 8.8.1 概要

`ExecutionEnvironmentManager`はDocker環境のライフサイクル（作成、割り当て、クリーンアップ）を管理する独自実装クラスである。グラフ定義の`requires_environment: true`ノード数に基づいて環境プールを準備し、各ノードに一意の環境を割り当てる。

#### 8.8.2 責務

1. **環境プール管理**: ワークフロー開始時に必要な数のDocker環境を一括作成
2. **環境割り当て**: 各`requires_environment: true`ノードに一意の環境IDを割り当て
3. **環境分離**: 並列実行されるノードが独立した環境で動作することを保証
4. **環境クリーンアップ**: ワークフロー完了時または異常終了時に全環境を削除

#### 8.8.3 主要メソッド

| メソッド | 説明 |
|---------|------|
| `prepare_environments(count)` | 指定数のDocker環境を一括作成し、環境IDリストを返す |
| `get_environment(node_id)` | ノードIDに対応する環境IDを返す（初回呼び出し時に割り当て） |
| `execute_command(node_id, command)` | 指定ノードの環境でコマンドを実行 |
| `clone_repository(node_id, repo_url, branch)` | 指定ノードの環境でリポジトリをクローン |
| `cleanup_environments()` | すべての環境を削除 |

#### 8.8.4 環境割り当てロジック

ExecutionEnvironmentManagerクラスは以下の内部データ構造を保持し、環境の割り当てを管理する：

**内部データ構造**:
- **環境プール（environment_pool）**: 準備済みの環境IDをリスト形式で保持する
- **ノード環境マッピング（node_to_env_map）**: ノードIDと環境IDの対応関係を辞書形式で管理する
- **次の割り当てインデックス（next_env_index）**: 次に割り当てる環境のインデックスを記録する

**環境準備処理（prepare_environments）**:
1. 指定された数だけループ処理を行う
2. 各反復で一意の環境ID（UUID形式）を生成する
3. Docker APIを呼び出してDocker環境を作成する
4. 作成した環境IDを環境プールに追加する
5. 準備済み環境IDのリストを返す

**環境取得処理（get_environment）**:
1. ノードIDがノード環境マッピングに存在するか確認する
2. 存在する場合: マッピングから環境IDを取得して返す（既に割り当て済み）
3. 存在しない場合（初回呼び出し時）:
   - 次の割り当てインデックスが環境プールのサイズを超えていないか確認する
   - 超えている場合: RuntimeErrorをスローする（環境プール不足）
   - 問題ない場合: 環境プールから次のインデックスの環境IDを取得する
   - ノード環境マッピングにノードIDと環境IDの対応を記録する
   - 次の割り当てインデックスを1増やす
   - 割り当てた環境IDを返す

この仕組みにより、各ノードは初回実行時に一意の環境が割り当てられ、以降の呼び出しでは同じ環境が再利用される。

#### 8.8.5 並列実行時の動作

**例**: `multi_codegen_mr_processing`で3つのコード生成ノードが並列実行される場合

1. **環境準備**: WorkflowFactory が `prepare_environments(4)` を呼び出し（code_generation × 3 + test_execution_evaluation × 1）
2. **環境割り当て**: 各ノード初回実行時に一意の環境IDを取得
   - `code_generation_fast` → env_1
   - `code_generation_standard` → env_2
   - `code_generation_creative` → env_3
   - `test_execution_evaluation` → env_4
3. **並列実行**: 各ノードは割り当てられた環境で独立して動作
4. **クリーンアップ**: ワークフロー完了時に4つの環境を一括削除

#### 8.8.6 エラーハンドリング

- **環境作成失敗**: Docker APIエラー時は例外をスローし、ワークフロー実行を中断
- **環境不足**: `get_environment()` でプールが枯渇した場合は RuntimeError をスロー
- **異常終了時のクリーンアップ**: `try-finally` パターンで必ず `cleanup_environments()` を実行

---

### 8.9 Middleware機構

#### 8.9.1 概要

Middlewareは、ノード実行の前後に自動的に介入する横断的な機能を提供します。グラフ構造を汚さずに、認証、ロギング、コメント監視などの共通処理を実装できます。

**主な用途**:
- ユーザーコメント監視（差分計画パターン）
- 実行時間の監視とタイムアウト処理
- エラーハンドリングの共通化
- デバッグ用ロギング

#### 8.9.2 Middleware実行タイミング

Middlewareは以下の3つのフェーズで実行されます：

1. **before_execution**: ノード実行前
2. **after_execution**: ノード実行後（成功時）
3. **on_error**: ノード実行中にエラーが発生した場合

#### 8.9.3 Middleware実装

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

#### 8.9.4 CommentCheckMiddleware実装

**責務**: ノード実行前にGitLab MR/Issueの新規コメントをチェックし、検出時は計画見直しにリダイレクト

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
   
6. **リダイレクトシグナル生成**:
   - MiddlewareSignalを生成して返す
     - `action`: "redirect"
     - `redirect_to`: "plan_reflection"
     - `reason`: "New user comments detected"
     - `metadata`: コメント数、中断されたノードIDを含む

**新規コメント取得ロジック**:
- GitLab APIから全コメントを取得
- 保持している最終チェック済みコメントIDと各コメントのIDを比較
- IDが大きい（より新しい）コメントのみを新規として抽出
- 取得した全コメントの最後のIDを最終チェック済みコメントIDとして更新

#### 8.9.5 TokenUsageMiddleware実装

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
     - user_id: ワークフローコンテキストから取得
     - task_uuid: ワークフローコンテキストから取得
     - node_id: 実行ノードID
     - model: 使用モデル名
     - prompt_tokens、completion_tokens、total_tokens
     - created_at: 記録日時

6. **メトリクス送信**:
   - OpenTelemetry経由でメトリクスを送信
   - メトリクス名: `token_usage_total`
   - ラベル: model、node_id、user_id
   - 値: total_tokens

**並行実行時の動作**:
- 複数タスクが同時に実行される場合でも、各タスクのuser_idとtask_uuidで区別
- データベース書き込みはトランザクション管理で競合回避
- メトリクス送信は非同期で実行し、ワークフロー実行をブロックしない

#### 8.9.6 ErrorHandlingMiddleware実装

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

#### 8.9.7 Middlewareの登録と実行

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
5. 3つのMiddlewareインスタンスを生成:
   - CommentCheckMiddleware（GitLabClientを引数に渡す）
   - TokenUsageMiddleware（ContextStorageManager、MetricsCollectorを引数に渡す）
   - ErrorHandlingMiddleware（ContextStorageManager、GitLabClient、MetricsCollectorを引数に渡す）
6. WorkflowFactoryに対して3つのMiddlewareを順番に登録
7. WorkflowFactoryインスタンスを返す

**Middleware実行順序の重要性**:
- CommentCheckMiddlewareは最初に実行（before_executionで早期リダイレクト可能）
- TokenUsageMiddlewareは2番目（after_executionで記録）
- ErrorHandlingMiddlewareは最後に実行（on_errorで統一的にハンドリング）

#### 8.9.8 グラフ定義での適用指定

**CommentCheckMiddleware有効化**:

ノードmetadataで`check_comments_before: true`を指定:

| ノードタイプ | 適用推奨 | 理由 |
|------------|----------|------|
| Planning系ノード | ✅ 推奨 | 計画作成前にコメントチェック |
| Plan Reflection | ✅ 推奨 | 検証前にコメントチェック |
| Execution系ノード | ⚠️ 任意 | 長時間実行の場合に推奨 |
| Review系ノード | ❌ 不要 | 最終フェーズのため |

**TokenUsageMiddlewareとErrorHandlingMiddleware**:

これらはすべてのノードに自動適用されるため、グラフ定義での個別指定は不要。WorkflowFactoryへの登録のみで全ワークフローに適用される。

#### 8.9.9 Middleware機構の利点

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
- **TodoManagementTool**: Todoリスト管理（`create_todo_list`, `get_todo_list`, `update_todo_status`, `add_todo`, `delete_todo`, `reorder_todos`, `sync_to_gitlab`）

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

**連携フロー**:

1. **Agent FrameworkがMCPツールを呼び出す**: ChatCompletionAgentがツール実行を要求
2. **MCPToolWrapperがノードIDを取得**: 現在実行中のノードIDをコンテキストから取得
3. **ExecutionEnvironmentManagerで環境IDを解決**: `get_environment(node_id)`で環境IDを取得
4. **環境内でMCPサーバーを起動**: 該当する環境のDocker内でMCPサーバープロセスを起動
5. **MCPクライアントが通信**: 環境内MCPサーバーにリクエストを送信
6. **結果を返す**: MCPサーバーからの結果をAgent Frameworkに返却

**実装クラス**:
- `ExecutionEnvironmentMCPWrapper`: 環境内MCPサーバー起動・通信を管理
- `EnvironmentAwareMCPClient`: ノードIDから環境IDを解決してMCP通信を行うクライアント

詳細設計は[セクション8.8](#88-実行環境管理executionenvironmentmanager)を参照。

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
| Process Framework | Workflow/Executor管理 | ワークフロー実行、Executor管理 | [Executor API](https://learn.microsoft.com/ja-jp/python/api/agent-framework-core/agent_framework.executor) |

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
| **`handlers/task_getter_gitlab.py`** | `TaskGitLabIssue` | GitLab Issue操作 | Agent Framework Workflowに統合 | - |
| | `TaskGitLabMergeRequest` | GitLab MR操作 | Agent Framework Workflowに統合 | - |
| | `TaskGetterFromGitLab` | GitLabタスク取得 | Agent Framework Workflowに統合 | PostgreSQLで処理済みタスクを除外 |
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
| **`handlers/execution_environment_manager.py`** | `ExecutionEnvironmentManager` | Docker環境管理 | 参考にして再実装 | Agent Framework Workflowに統合 |
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
