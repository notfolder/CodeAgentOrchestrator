# クラス実装詳細仕様書

本ドキュメントは、CODE_AGENT_ORCHESTRATOR_SPEC.mdで定義されたシステムの主要クラスの実装詳細を記載する。各クラスの責務、保持データ、メソッドの処理フローを日本語で具体的に記述し、コード例は含めない。

---

## 1. ConfigurableAgent（汎用エージェントクラス）

### 1.1 概要

ConfigurableAgentはグラフ内のすべてのエージェントノードを実装する単一クラス。エージェント定義ファイルの設定に基づいて動作する。

### 1.2 継承関係

Agent FrameworkのChatCompletionAgentを継承する。

### 1.3 保持データ

- **config: AgentNodeConfig** - エージェント定義から取得した設定
  - node_id: ノードID
  - agent_definition_id: エージェント定義ID
  - role: ロール（planning/reflection/execution/review）
  - input_keys: 入力キー一覧
  - output_keys: 出力キー一覧
  - tools: ツール名一覧
  - requires_environment: 環境必要フラグ
  - prompt_id: プロンプト定義ID
- **agent: ChatCompletionAgent** - Agent FrameworkのChatCompletionAgentインスタンス
- **kernel: Kernel** - Agent FrameworkのKernelインスタンス（ツール管理）
- **progress_reporter: ProgressReporter** - 進捗報告インスタンス
- **environment_id: str** - Docker環境ID（requires_environment=trueの場合）
- **prompt_content: str** - プロンプト定義から取得したシステムプロンプト

### 1.4 主要メソッド

#### execute_async(context: IWorkflowContext) → NodeResult

**処理フロー**:

1. **タスクMR/Issue IID取得**
   - context.read_state_async("task_mr_iid", scope_name='workflow')でMR IIDを取得
   - 存在しない場合は"task_issue_iid"を取得
   - task_iid変数に保存

2. **入力データ取得**
   - config.input_keysをループ
   - 各キーについてcontext.read_state_async(key, scope_name='workflow')を呼び出し
   - 取得した値をinput_data辞書に格納

3. **進捗報告（開始）**
   - progress_reporter.report_progress(task_iid, config.role + "_start", "処理を開始します", {"node_id": config.node_id})を呼び出し

4. **プロンプト生成**
   - prompt_contentをベースにプロンプトを構築
   - input_dataの各キーをプレースホルダーとして置換
   - 例: `{task_description}`を`input_data['task_description']`で置換

5. **Agent FrameworkのChatCompletionAgent呼び出し**
   - agent.invoke_async(kernel=kernel, messages=[user_message])を呼び出し
   - user_messageは生成したプロンプト
   - ChatHistory内の過去の会話履歴が自動的にロードされる（PostgreSqlChatHistoryProvider経由）

6. **LLM応答取得**
   - Agent FrameworkからChatMessageContentを取得
   - メッセージ内容をテキストまたはJSON形式でパース

7. **進捗報告（LLM応答）**
   - response_summary = 応答内容の要約（最初の200文字程度）
   - progress_reporter.report_progress(task_iid, config.role + "_llm_response", "LLM応答を取得しました", {"summary": response_summary})を呼び出し

8. **ツール呼び出し処理**
   - LLMがfunction_callを返した場合:
     - Kernelから該当ツールを取得
     - ツールを実行（MCPツールの場合はMCPClientを経由）
     - ツール実行結果をLLMに返してフィードバックループ
     - 最終応答を取得

9. **ロール別の後処理**
   - **planning**: Todoリスト作成
   - **reflection**: 改善判定
   - **execution**: ファイル操作結果の確認、git操作の実行
   - **review**: レビューコメント生成

10. **進捗報告（完了）**
   - progress_reporter.report_progress(task_iid, config.role + "_complete", "処理が完了しました", output_data)を呼び出し

11. **出力データ保存**
   - config.output_keysをループ
   - 各キーについてcontext.queue_state_update_async(key, value, scope_name='workflow')を呼び出し
   - LLM応答から抽出した値を保存

12. **NodeResult返却**
   - status='success'
   - result=output_data
   - execution_time=実行時間

#### get_chat_history() → List[ChatMessage]

**処理フロー**:

1. PostgreSqlChatHistoryProvider経由でChatHistoryを取得
2. Agent FrameworkのChatMessage一覧として返す

#### get_context(keys: List[str]) → Dict[str, Any]

**処理フロー**:

1. keysをループ
2. 各キーについてcontext.read_state_async(key, scope_name='workflow')を呼び出し
3. 取得した値を辞書に格納して返す

#### store_result(output_keys: List[str], result: Dict[str, Any]) → None

**処理フロー**:

1. output_keysをループ
2. 各キーについてresult辞書から値を取得
3. context.queue_state_update_async(key, value, scope_name='workflow')を呼び出し

#### invoke_mcp_tool(tool_name: str, params: Dict[str, Any]) → Dict[str, Any]

**処理フロー**:

1. config.toolsにtool_nameが含まれているか確認（含まれていない場合はエラー）
2. kernelからtool_nameに対応するKernelFunctionを取得
3. KernelFunction.invoke_async(kernel, params)を呼び出し
4. 結果を辞書形式で返す

---

## 2. Factory群

### 2.1 WorkflowFactory

WorkflowFactoryはAgent FrameworkのProcess Frameworkを使用してワークフローを生成する。グラフ定義からAgent FrameworkのWorkflowインスタンスを動的に構築し、必要なExecutorとAgentを登録する。

**主要メソッド**:
- `create_workflow_from_definition(user_id, task_context)`: グラフ定義からWorkflowを生成
- `_build_nodes(graph_def, agent_def, prompt_def)`: ノードをExecutorまたはAgentとして生成
- `_setup_environments(graph_def)`: Docker環境を準備

### 2.2 ExecutorFactory

#### 2.2.1 概要

ExecutorFactoryはタスク処理に必要なExecutorインスタンスを生成する。

#### 2.2.2 保持データ

- **user_config_client: UserConfigClient** - ユーザー設定クライアント
- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **env_manager: ExecutionEnvironmentManager** - 環境マネージャー

#### 2.2.3 主要メソッド

##### create_user_resolver() → UserResolverExecutor

**処理フロー**:

1. UserResolverExecutorインスタンスを生成
2. user_config_clientを渡す
3. 返却

##### create_content_transfer() → ContentTransferExecutor

**処理フロー**:

1. ContentTransferExecutorインスタンスを生成
2. gitlab_clientを渡す
3. 返却

##### create_environment_setup() → EnvironmentSetupExecutor

**処理フロー**:

1. EnvironmentSetupExecutorインスタンスを生成
2. env_managerを渡す
3. 返却

### 2.3 AgentFactory

#### 2.3.1 概要

AgentFactoryはConfigurableAgentインスタンスを生成する。

#### 2.3.2 保持データ

- **kernel: Kernel** - Agent FrameworkのKernelインスタンス
- **mcp_client_factory: MCPClientFactory** - MCPクライアントファクトリ
- **chat_history_provider: PostgreSqlChatHistoryProvider** - チャット履歴Provider
- **planning_context_provider: PlanningContextProvider** - プランニングコンテキストProvider
- **tool_result_context_provider: ToolResultContextProvider** - ツール結果コンテキストProvider

#### 2.3.3 主要メソッド

##### create_agent(agent_config: AgentNodeConfig, prompt_config: PromptConfig, user_email: str, progress_reporter: ProgressReporter) → ConfigurableAgent

**処理フロー**:

1. **Kernel設定**
   - agent_config.toolsをループ
   - 各ツール名について:
     - MCPツールの場合: mcp_client_factory.create_client(tool_name)でMCPクライアントを取得し、Kernelに登録
     - ネイティブツールの場合: kernel.add_function()で直接登録（TodoManagementTool等）

2. **User Config取得**
   - UserConfigClientからuser_emailのLLM設定を取得
   - api_key、model_name、temperature等を取得

3. **ChatClient生成**
   - Agent FrameworkのChatClientを生成
   - OpenAI/Ollama/LM Studioプロバイダーに応じて適切なクライアントを選択
   - api_key、model_name等を設定

4. **ChatCompletionAgent生成**
   - ChatClient.as_ai_agent()を呼び出し
   - ChatClientAgentOptionsを設定:
     - name: agent_config.node_id
     - chat_options.instructions: prompt_config.content
     - chat_history_provider: chat_history_provider
     - ai_context_providers: [planning_context_provider, tool_result_context_provider]
     - chat_options.temperature: prompt_config.temperature_overrideまたはデフォルト値
     - chat_options.model: prompt_config.model_overrideまたはデフォルト値
   - AIAgentインスタンスを取得

5. **ConfigurableAgentインスタンス生成**
   - agent_config、ChatCompletionAgent、Kernel、prompt_config.content、progress_reporterを渡す
   - requires_environment=trueの場合、environment_idを設定（後で割り当て）

6. **ConfigurableAgent返却**

### 2.4 MCPClientFactory

#### 2.4.1 概要

MCPClientFactoryはMCPサーバーへのクライアント接続を生成し、Agent FrameworkのKernelにツールとして登録する。

#### 2.4.2 保持データ

- **mcp_server_configs: Dict[str, MCPServerConfig]** - サーバー設定辞書
- **mcp_client_registry: MCPClientRegistry** - クライアント登録管理
- **kernel: Kernel** - Agent FrameworkのKernel

#### 2.4.3 主要メソッド

##### create_client(server_name: str) → MCPClient

**処理フロー**:

1. **既存クライアント確認**
   - mcp_client_registryでserver_nameが登録済みか確認
   - 登録済みの場合: 既存クライアントを返す

2. **サーバー設定取得**
   - mcp_server_configsからserver_nameに対応するMCPServerConfigを取得
   - 存在しない場合: エラーをスロー

3. **MCPClientインスタンス生成**
   - MCPServerConfigのcommand、envを使用してMCPClientを生成
   - stdio経由で接続

4. **MCP接続**
   - MCPClient.connect()を呼び出してMCPサーバーとの通信を開始

5. **Kernelへのツール登録**
   - _register_mcp_tools_to_kernel(server_name, mcp_client)を呼び出し

6. **クライアント登録**
   - mcp_client_registryにserver_nameとmcp_clientを登録

7. **MCPClient返却**

##### _register_mcp_tools_to_kernel(server_name: str, mcp_client: MCPClient) → None

**処理フロー**:

1. **ツール一覧取得**
   - mcp_client.list_tools()を呼び出してMCPサーバーが提供するツール一覧を取得

2. **各ツールをKernelFunctionに変換**
   - ツール一覧をループ
   - 各ツールについて_create_kernel_function_from_mcp_tool(tool, mcp_client)を呼び出し
   - KernelFunctionインスタンスを取得

3. **Kernelに登録**
   - kernel.add_function(plugin_name=server_name, function=kernel_function)を呼び出し

##### _create_kernel_function_from_mcp_tool(tool: MCPTool, mcp_client: MCPClient) → KernelFunction

**処理フロー**:

1. **非同期wrapper関数定義**
   - MCPツール呼び出しをラップする非同期関数を定義
   - 関数内でmcp_client.call_tool(tool.name, arguments)を呼び出す

2. **KernelFunction生成**
   - KernelFunction.from_native_method(wrapper_function, tool.name, description=tool.description)を呼び出し
   - KernelFunctionインスタンスを取得

3. **KernelFunction返却**

##### create_text_editor_client() → MCPClient

**処理フロー**:

1. create_client('text-editor')を呼び出す
2. 返却

##### create_command_executor_client() → MCPClient

**処理フロー**:

1. create_client('command-executor')を呼び出す
2. 返却

### 2.5 TaskStrategyFactory

#### 2.5.1 概要

TaskStrategyFactoryはタスクの処理戦略を決定する。

#### 2.5.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **config_manager: ConfigManager** - 設定管理

#### 2.5.3 主要メソッド

##### create_strategy(task: Task) → ITaskStrategy

**処理フロー**:

1. **タスクタイプ判定**
   - task.task_typeを確認

2. **Issueタイプの場合**
   - should_convert_issue_to_mr(task)を呼び出し
   - Trueの場合: IssueToMRConversionStrategyインスタンスを生成して返す
   - Falseの場合: IssueOnlyStrategyインスタンスを生成して返す

3. **MergeRequestタイプの場合**
   - MergeRequestStrategyインスタンスを生成して返す

4. **不明なタイプの場合**
   - ValueErrorをスロー

##### should_convert_issue_to_mr(task: Task) → bool

**処理フロー**:

1. **設定確認**
   - config_manager.get_issue_to_mr_config()でIssue→MR変換設定を取得
   - 自動変換が無効の場合: Falseを返す

2. **botラベル確認**
   - gitlab_client.get_issue(task.project_id, task.issue_iid)でIssue情報を取得
   - Issue.labelsにconfig.bot_labelが含まれているか確認
   - 含まれていない場合: Falseを返す

3. **既存MR確認**
   - gitlab_client.list_merge_requests(project_id=task.project_id, source_branch=f"issue-{task.issue_iid}")を呼び出し
   - 既存MRがある場合: Falseを返す（既に変換済み）

4. **変換可能判定**
   - すべての条件を満たす場合: Trueを返す

---

## 3. Executor群

### 3.1 BaseExecutor（抽象基底クラス）

#### 3.1.1 概要

BaseExecutorはすべてのExecutorの共通機能を提供する抽象基底クラス。

#### 3.1.2 保持データ

- **context: IWorkflowContext** - ワークフローコンテキスト（execute_async()呼び出し時に設定）

#### 3.1.3 抽象メソッド

##### execute_async(context: IWorkflowContext) → NodeResult

サブクラスで実装する。

#### 3.1.4 共通ヘルパーメソッド

##### get_context_value(key: str, scope_name: str = 'workflow') → Any

**処理フロー**:

1. context.read_state_async(key, scope_name)を呼び出し
2. 値を返す

##### set_context_value(key: str, value: Any, scope_name: str = 'workflow') → None

**処理フロー**:

1. context.queue_state_update_async(key, value, scope_name)を呼び出し

### 3.2 UserResolverExecutor

#### 3.2.1 概要

UserResolverExecutorはユーザー情報を取得し、LLM設定をワークフローコンテキストに保存する。

#### 3.2.2 保持データ

- **user_config_client: UserConfigClient** - ユーザー設定クライアント

#### 3.2.3 主要メソッド

##### execute_async(context: IWorkflowContext) → NodeResult

**処理フロー**:

1. **タスク情報取得**
   - context.read_state_async('task_identifier', 'workflow')を呼び出し
   - task_identifierから project_id、mr_iid等を抽出

2. **GitLabからユーザー情報取得**
   - gitlab_client.get_merge_request(project_id, mr_iid)を呼び出し
   - MR.authorからユーザーメールアドレスを取得

3. **User Config取得**
   - user_config_client.get_user_config(user_email)を呼び出し
   - LLM設定（api_key、model_name、temperature等）を取得

4. **ワークフローコンテキストに保存**
   - context.queue_state_update_async('user_email', user_email, 'workflow')
   - context.queue_state_update_async('user_config', user_config, 'workflow')

5. **NodeResult返却**
   - status='success'
   - result={'user_email': user_email, 'user_config': user_config}

### 3.3 ContentTransferExecutor

#### 3.3.1 概要

ContentTransferExecutorはIssueコメントをMRに転記する。

#### 3.3.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント

#### 3.3.3 主要メソッド

##### execute_async(context: IWorkflowContext) → NodeResult

**処理フロー**:

1. **Issue情報取得**
   - context.read_state_async('issue_iid', 'workflow')を呼び出し
   - context.read_state_async('project_id', 'workflow')を呼び出し

2. **Issueコメント取得**
   - gitlab_client.list_issue_notes(project_id, issue_iid)を呼び出し
   - コメント一覧を取得

3. **MR情報取得**
   - context.read_state_async('mr_iid', 'workflow')を呼び出し

4. **MRにコメント転記**
   - コメント一覧をループ
   - 各コメントについてgitlab_client.add_merge_request_note(project_id, mr_iid, comment.body)を呼び出し

5. **転記数記録**
   - context.queue_state_update_async('transferred_comments_count', count, 'workflow')

6. **NodeResult返却**
   - status='success'
   - result={'transferred_comments_count': count}

### 3.4 EnvironmentSetupExecutor

#### 3.4.1 概要

EnvironmentSetupExecutorはDocker環境の準備を確認する。

#### 3.4.2 保持データ

- **env_manager: ExecutionEnvironmentManager** - 環境マネージャー

#### 3.4.3 主要メソッド

##### execute_async(context: IWorkflowContext) → NodeResult

**処理フロー**:

1. **環境ID一覧取得**
   - context.read_state_async('environment_ids', 'workflow')を呼び出し

2. **各環境の準備確認**
   - 環境ID一覧をループ
   - 各環境IDについてenv_manager.check_environment(env_id)を呼び出し
   - 環境が準備済みか確認

3. **すべて準備済みの場合**
   - context.queue_state_update_async('environments_ready', True, 'workflow')
   - NodeResult返却（status='success'）

4. **準備されていない環境がある場合**
   - エラーをスロー

---

## 4. Custom Provider群

### 4.1 PostgreSqlChatHistoryProvider

#### 4.1.1 概要

PostgreSqlChatHistoryProviderはLLM会話履歴をPostgreSQLに永続化するカスタムProvider。

#### 4.1.2 継承関係

Agent FrameworkのChatHistoryProviderを継承する。

#### 4.1.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **session_state: ProviderSessionState[ChatHistorySessionState]** - セッション状態

#### 4.1.4 SessionState構造

ChatHistorySessionStateクラス:
- task_uuid: str - タスクUUID
- message_count: int - メッセージ総数
- total_tokens: int - トークン総数

#### 4.1.5 主要メソッド

##### provide_chat_history_async(context: AgentContext, cancellation_token: CancellationToken) → List[ChatMessage]

**処理フロー**:

1. **セッション状態取得**
   - contextからProviderSessionState[ChatHistorySessionState]を取得
   - session_state.task_uuidを取得

2. **PostgreSQLから会話履歴取得**
   - SQLクエリ実行: `SELECT role, content, tokens FROM context_messages WHERE task_uuid = ? ORDER BY seq ASC`
   - 結果をループして各行を処理

3. **ChatMessage変換**
   - 各行についてAgent FrameworkのChatMessageオブジェクトを生成
   - roleに応じてSystemMessage、UserMessage、AssistantMessage、ToolMessageに変換
   - contentを設定

4. **ChatMessage一覧返却**

##### store_chat_history_async(context: AgentContext, cancellation_token: CancellationToken) → None

**処理フロー**:

1. **新規メッセージ取得**
   - contextから新しく追加されたChatMessageを取得
   - ChatHistoryの最後のN件を取得（Nは前回保存時のmessage_countとの差分）

2. **トークン数計算**
   - 各メッセージのcontentをtiktokenでトークン数計算
   - message_count、total_tokensを更新

3. **PostgreSQLに保存**
   - 新規メッセージをループ
   - 各メッセージについてSQLクエリ実行: `INSERT INTO context_messages (task_uuid, seq, role, content, tokens) VALUES (?, ?, ?, ?, ?)`
   - seqはmessage_countから順次インクリメント

4. **セッション状態更新**
   - session_state.message_count = message_count
   - session_state.total_tokens = total_tokens

### 4.2 PlanningContextProvider

#### 4.2.1 概要

PlanningContextProviderはプランニング履歴を永続化し、コンテキストとしてエージェントに提供するカスタムProvider。

#### 4.2.2 継承関係

Agent FrameworkのAIContextProviderを継承する。

#### 4.2.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続

#### 4.2.4 主要メソッド

##### provide_ai_context_async(context: AgentContext, cancellation_token: CancellationToken) → AIContext

**処理フロー**:

1. **task_uuid取得**
   - contextからtask_uuidを取得

2. **PostgreSQLからプランニング履歴取得**
   - SQLクエリ実行: `SELECT phase, node_id, plan, result FROM context_planning_history WHERE task_uuid = ? ORDER BY created_at ASC`
   - 結果をループして各行を処理

3. **テキスト整形**
   - planningフェーズ: 計画内容をMarkdown形式で整形
   - executionフェーズ: 実行結果をテキスト形式で整形
   - reflectionフェーズ: リフレクション結果をテキスト形式で整形
   - すべてを連結して大きなテキストブロックを生成

4. **AIContextオブジェクト生成**
   - Agent FrameworkのAIContextを生成
   - additional_messagesまたはadditional_instructionsとして整形したテキストを設定

5. **AIContext返却**

##### store_ai_context_async(context: AgentContext, cancellation_token: CancellationToken) → None

**処理フロー**:

1. **task_uuid取得**
   - contextからtask_uuidを取得

2. **エージェント応答解析**
   - contextからエージェントの最後の応答メッセージを取得
   - メッセージ内容をJSON形式でパース

3. **フェーズ判定**
   - メッセージ内容から現在のフェーズを判定
   - planning: 計画データを抽出
   - execution: アクションIDと実行結果を抽出
   - reflection: リフレクション結果を抽出

4. **PostgreSQLに保存**
   - SQLクエリ実行: `INSERT INTO context_planning_history (task_uuid, phase, node_id, plan, action_id, result) VALUES (?, ?, ?, ?, ?, ?)`
   - planはJSON形式でJSONBカラムに保存

### 4.3 ToolResultContextProvider

#### 4.3.1 概要

ToolResultContextProviderはツール実行結果をファイルストレージとPostgreSQLに保存し、コンテキストとしてエージェントに提供するカスタムProvider。

#### 4.3.2 継承関係

Agent FrameworkのAIContextProviderを継承する。

#### 4.3.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **file_storage_base_dir: str** - ファイルストレージのベースディレクトリ

#### 4.3.4 主要メソッド

##### provide_ai_context_async(context: AgentContext, cancellation_token: CancellationToken) → AIContext

**処理フロー**:

1. **task_uuid取得**
   - contextからtask_uuidを取得

2. **PostgreSQLからツール実行メタデータ取得**
   - SQLクエリ実行: `SELECT tool_name, tool_command, file_path, created_at FROM context_tool_results_metadata WHERE task_uuid = ? ORDER BY created_at DESC LIMIT 10`
   - 直近10件のツール実行メタデータを取得

3. **ファイルストレージからツール実行結果取得**
   - メタデータをループ
   - 各file_pathについてJSONファイルを読み込み
   - ファイルサイズが大きい場合は先頭500文字のみ取得

4. **要約形式で整形**
   - ツール名、実行日時、結果のプレビューをMarkdown形式で整形
   - すべてを連結して大きなテキストブロックを生成

5. **AIContextオブジェクト生成**
   - Agent FrameworkのAIContextを生成
   - additional_messagesとして整形したテキストを設定

6. **AIContext返却**

##### store_ai_context_async(context: AgentContext, cancellation_token: CancellationToken) → None

**処理フロー**:

1. **task_uuid取得**
   - contextからtask_uuidを取得

2. **ツール呼び出し情報取得**
   - contextから最後に実行されたツール呼び出し情報を取得
   - tool_name、arguments、resultを抽出

3. **ファイルパス生成**
   - タイムスタンプ付きファイル名を生成: `{timestamp}_{tool_name}.json`
   - ファイルパス: `tool_results/{task_uuid}/{filename}`

4. **ファイルストレージに保存**
   - ツール呼び出し情報をJSON形式でファイルに保存
   - timestamp、tool_name、arguments、resultを含める

5. **PostgreSQLにメタデータ保存**
   - SQLクエリ実行: `INSERT INTO context_tool_results_metadata (task_uuid, tool_name, tool_command, file_path, file_size, success) VALUES (?, ?, ?, ?, ?, ?)`

6. **metadata.json更新**
   - tool_results/{task_uuid}/metadata.jsonを読み込み
   - total_file_reads、total_command_executions等をインクリメント
   - ファイルに書き戻し

---

## 5. Middleware実装

### 5.1 IMiddlewareインターフェース

すべてのMiddlewareが実装する共通インターフェース。

#### intercept(phase: str, node: WorkflowNode, context: IWorkflowContext, **kwargs) → Optional[MiddlewareSignal]

**引数**:
- phase: 実行フェーズ（before_execution/after_execution/on_error）
- node: 実行対象ノード
- context: ワークフローコンテキスト
- kwargs: 追加引数（result、exceptionなど）

**戻り値**:
- MiddlewareSignal: フロー制御シグナル
- None: 通常処理継続

### 5.2 CommentCheckMiddleware

#### 5.2.1 概要

CommentCheckMiddlewareは新規コメントをチェックし、plan_reflectionノードへリダイレクトする。

#### 5.2.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **last_comment_check_time: Dict[str, datetime]** - タスクごとの最終チェック時刻

#### 5.2.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: IWorkflowContext, **kwargs) → Optional[MiddlewareSignal]

**処理フロー**:

1. **フェーズ判定**
   - phaseが'before_execution'でない場合: Noneを返す（何もしない）

2. **メタデータ確認**
   - node.metadata.check_comments_beforeがTrueでない場合: Noneを返す

3. **タスク情報取得**
   - context.read_state_async('project_id', 'workflow')を呼び出し
   - context.read_state_async('mr_iid', 'workflow')を呼び出し

4. **最終チェック時刻取得**
   - last_comment_check_timeから該当タスクの最終チェック時刻を取得
   - 存在しない場合: タスク開始時刻を使用

5. **新規コメント確認**
   - gitlab_client.list_merge_request_notes(project_id, mr_iid, since=last_check_time)を呼び出し
   - 新規コメント一覧を取得

6. **新規コメントがない場合**
   - last_comment_check_timeを現在日時に更新
   - Noneを返す

7. **新規コメントがある場合**
   - context.queue_state_update_async('user_new_comments', new_comments, 'workflow')
   - MiddlewareSignalを生成:
     - action='redirect'
     - redirect_to='plan_reflection'
     - reason='New user comments detected'
   - MiddlewareSignal返却

### 5.3 TokenUsageMiddleware

#### 5.3.1 概要

TokenUsageMiddlewareはすべてのAIエージェント呼び出しを自動的にインターセプトして、トークン使用量を記録する。

#### 5.3.2 保持データ

- **context_storage_manager: ContextStorageManager** - コンテキストストレージマネージャー
- **metrics_collector: MetricsCollector** - メトリクスコレクター

#### 5.3.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: IWorkflowContext, **kwargs) → Optional[MiddlewareSignal]

**処理フロー**:

1. **フェーズ判定**
   - phaseが'after_execution'でない場合: Noneを返す

2. **ノード種別判定**
   - node.node_typeが'agent'でない場合: Noneを返す

3. **レスポンス情報取得**
   - kwargsから'result'を取得
   - result内のLLMレスポンス情報を抽出

4. **トークン情報抽出**
   - prompt_tokens: 入力プロンプトのトークン数
   - completion_tokens: LLM生成出力のトークン数
   - total_tokens: 合計トークン数
   - model: 使用したモデル名

5. **データベース記録**
   - context_storage_manager.save_token_usage()を呼び出し
   - user_id、task_uuid、node_id、model、prompt_tokens、completion_tokens、total_tokensを渡す
   - token_usageテーブルに保存

6. **メトリクス送信**
   - metrics_collector.send_metric()を呼び出し
   - metric_name='token_usage_total'
   - labels={'model': model, 'node_id': node_id, 'user_id': user_id}
   - value=total_tokens

7. **Noneを返す**（フロー制御なし）

### 5.4 ErrorHandlingMiddleware

#### 5.4.1 概要

ErrorHandlingMiddlewareはすべてのノード実行時のエラーを統一的にハンドリングし、エラー分類、リトライ判定、ユーザー通知を実行する。

#### 5.4.2 保持データ

- **context_storage_manager: ContextStorageManager** - コンテキストストレージマネージャー
- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **metrics_collector: MetricsCollector** - メトリクスコレクター
- **retry_policy: RetryPolicy** - リトライポリシー設定

#### 5.4.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: IWorkflowContext, **kwargs) → Optional[MiddlewareSignal]

**処理フロー**:

1. **フェーズ判定**
   - phaseが'on_error'でない場合: Noneを返す

2. **エラー情報取得**
   - kwargsから'exception'を取得
   - exception.type、exception.message、exception.stack_traceを抽出

3. **エラー分類**
   - exception.typeに基づいてエラーカテゴリを判定
   - transient（一時的）: HTTP 5xx、タイムアウト
   - configuration（設定エラー）: 認証エラー、設定不正
   - implementation（実装エラー）: バグ、未実装機能
   - resource（リソースエラー）: メモリ不足、ディスク不足

4. **リトライ判定**
   - エラーカテゴリがtransientの場合: リトライ対象
   - context.read_state_async('retry_count', 'workflow')を呼び出し
   - retry_countがmax_attemptsより小さい場合: リトライ実行

5. **リトライ実行**
   - retry_count += 1
   - context.queue_state_update_async('retry_count', retry_count, 'workflow')
   - 指数バックオフ計算: delay = base_delay * (2 ** retry_count) + random_jitter
   - delay秒待機
   - Noneを返す（ノード再実行）

6. **リトライ上限到達またはリトライ不可の場合**
   - エラー記録: context_storage_manager.save_error()を呼び出し
   - ユーザー通知: gitlab_client.add_merge_request_note()でエラーコメント投稿
   - メトリクス送信: metrics_collector.send_metric(metric_name='workflow_errors_total', labels={'error_category': category})
   - タスク状態更新: context.queue_state_update_async('status', 'failed', 'workflow')
   - MiddlewareSignalを生成:
     - action='abort'
     - reason=f'Error: {exception.message}, Retries exhausted'
   - MiddlewareSignal返却

---

## 6. ExecutionEnvironmentManager

### 6.1 概要

ExecutionEnvironmentManagerはDocker環境のライフサイクル（作成、割り当て、クリーンアップ）を管理する。プロジェクト言語に応じた適切なDockerイメージで環境を作成し、環境プールとして管理する。

### 6.2 保持データ

- **docker_client: DockerClient** - Dockerクライアント
- **environment_name_mapping: Dict[str, str]** - 環境名とDockerイメージのマッピング（設定ファイルから読み込み）
- **environment_pool: List[str]** - 準備済み環境ID一覧
- **node_to_env_map: Dict[str, str]** - ノードIDと環境IDのマッピング
- **next_env_index: int** - 次に割り当てる環境のインデックス
- **selected_environment_name: str** - 選択された環境名（python, miniforge, node, default）

### 6.3 主要メソッド

#### prepare_environments(count: int, environment_name: str) → List[str]

**処理フロー**:

1. **環境名からDockerイメージ取得**
   - environment_name_mapping[environment_name]でイメージ名を取得
   - 環境名が無効またはnullの場合はenvironment_name_mapping['default']を使用

2. **環境ID一覧初期化**
   - environment_ids = []

3. **環境作成ループ**
   - countの回数だけループ
   - 各反復で:
     - 一意の環境ID生成（UUID）
     - docker_client.containers.create()で取得したイメージ名のDockerコンテナ作成
     - image、network、cpu_limit、memory_limit等を設定
     - コンテナ起動
     - 環境IDをenvironment_idsに追加

4. **環境プール設定**
   - environment_pool = environment_ids
   - selected_environment_name = environment_name

5. **環境ID一覧返却**

#### get_environment(node_id: str) → str

**処理フロー**:

1. **既存割り当て確認**
   - node_to_env_mapにnode_idが存在するか確認
   - 存在する場合: マッピングから環境IDを取得して返す

2. **環境プール確認**
   - next_env_indexがenvironment_poolのサイズを超えていないか確認
   - 超えている場合: RuntimeErrorをスロー（環境プール不足）

3. **環境割り当て**
   - environment_pool[next_env_index]から環境IDを取得
   - node_to_env_map[node_id] = env_id
   - next_env_index += 1

4. **環境ID返却**

#### execute_command(node_id: str, command: str) → CommandResult

**処理フロー**:

1. **環境ID取得**
   - env_id = get_environment(node_id)

2. **Dockerコンテナ取得**
   - container = docker_client.containers.get(env_id)

3. **コマンド実行**
   - exit_code, output = container.exec_run(command)

4. **結果返却**
   - CommandResult(exit_code, stdout, stderr)

#### clone_repository(node_id: str, repo_url: str, branch: str) → None

**処理フロー**:

1. **環境ID取得**
   - env_id = get_environment(node_id)

2. **git cloneコマンド構築**
   - command = f"git clone -b {branch} {repo_url} /workspace"

3. **コマンド実行**
   - execute_command(node_id, command)

4. **結果確認**
   - exit_codeが0でない場合: エラーをスロー

#### cleanup_environments() → None

**処理フロー**:

1. **環境プールループ**
   - environment_poolをループ
   - 各環境IDについて:
     - docker_client.containers.get(env_id)でコンテナ取得
     - container.stop()でコンテナ停止
     - container.remove()でコンテナ削除

2. **環境プールクリア**
   - environment_pool = []
   - node_to_env_map = {}
   - next_env_index = 0

---

## 7. EnvironmentAnalyzer

### 7.1 概要

EnvironmentAnalyzerはプロジェクト内の環境構築関連ファイルを検出するクラス。requirements.txt、package.json、environment.yml等の存在を確認し、プロジェクト言語の判定材料を提供する。

### 7.2 保持データ

- **mcp_clients: Dict[str, MCPToolClient]** - MCPツールクライアントの辞書
- **environment_file_patterns: Dict[str, List[str]]** - 環境タイプ別のファイルパターン定義

**environment_file_patterns**の内容:
- `python`: requirements.txt, pyproject.toml, setup.py, Pipfile, poetry.lock
- `conda`: environment.yml, condaenv.yaml
- `node`: package.json, package-lock.json, yarn.lock, pnpm-lock.yaml
- `common`: Dockerfile, docker-compose.yml, Makefile

### 7.3 主要メソッド

#### detect_environment_files(file_list: List[str]) → Dict[str, List[str]]

**処理フロー**:

1. **検出結果の初期化**
   - detected_files = {}

2. **環境タイプ別ループ**
   - environment_file_patternsの各環境タイプ（python, conda, node, common）をループ
   - 各環境タイプについて:
     - パターン一覧を取得
     - file_listの中から各パターンに一致するファイルを検索
     - 一致するファイルが見つかった場合:
       - detected_files[環境タイプ]にファイルパスを追加

3. **検出結果返却**
   - detected_files辞書を返す
   - 例: {"python": ["requirements.txt", "setup.py"], "node": ["package.json"]}

#### analyze_environment_files(detected_files: Dict[str, List[str]]) → Dict[str, Any]

**処理フロー**:

1. **環境情報初期化**
   - environment_info = {"detected_files": {}, "file_contents": {}}

2. **ファイル内容読み込みループ**
   - detected_filesの各環境タイプとファイルパスをループ
   - 各ファイルについて:
     - MCPクライアントを使用してファイル内容を読み込み
     - environment_info["detected_files"][ファイルパス] = 環境タイプ
     - ファイル内容が5000文字を超える場合は切り詰め
     - environment_info["file_contents"][ファイルパス] = ファイル内容

3. **環境情報返却**
   - environment_info辞書を返す

---

## 8. PrePlanningManager

### 8.1 概要

PrePlanningManagerは計画前情報収集フェーズを管理するクラス。タスク内容の理解、環境情報の収集、LLMによるプロジェクト言語判定と実行環境選択を担当する。

### 8.2 保持データ

- **config: Dict[str, Any]** - 計画前情報収集の設定
- **llm_client: LLMClient** - LLMクライアント
- **mcp_clients: Dict[str, MCPToolClient]** - MCPツールクライアントの辞書
- **task: Task** - 処理対象のタスク
- **progress_manager: ProgressManager** - 進捗報告マネージャー
- **understanding_result: Dict[str, Any]** - 依頼内容の理解結果
- **environment_info: Dict[str, Any]** - 環境情報
- **selected_environment: str** - 選択された環境名
- **selection_details: Dict[str, Any]** - 環境選択の詳細情報

### 8.3 主要メソッド

#### execute() → Dict[str, Any]

**処理フロー**:

1. **開始通知**
   - progress_manager.add_history_entry()で計画前情報収集フェーズ開始を通知

2. **依頼内容の理解**
   - execute_understanding()を呼び出し
   - タスク情報をLLMに渡して理解結果を取得
   - understanding_resultに保存

3. **環境情報の収集**
   - collect_environment_info()を呼び出し
   - ファイルリストを取得（FileListContextLoader使用）
   - EnvironmentAnalyzerで環境ファイルを検出・解析
   - environment_infoに保存

4. **プロジェクト言語判定と環境選択**
   - select_execution_environment()を呼び出し
   - 環境情報をLLMに渡してプロジェクト言語を判定させる
   - LLMが適切な環境名（python, miniforge, node, default）を選択
   - selected_environmentに保存
   - selection_detailsに判定理由等を保存

5. **完了通知**
   - progress_manager.add_history_entry()で完了を通知

6. **結果返却**
   - understanding_result、environment_info、selected_environment、selection_detailsを含む辞書を返す

#### select_execution_environment() → Tuple[str, Dict[str, Any]]

**処理フロー**:

1. **環境ファイル情報取得**
   - environment_infoから検出されたファイル情報を取得

2. **LLMプロンプト構築**
   - 検出された環境ファイル一覧を整形
   - 利用可能な環境名（python, miniforge, node, default）をリスト化
   - 判定基準を明記（複数言語の場合の優先順位等）
   - プロンプトに環境ファイル情報と判定指示を含める

3. **LLM呼び出し**
   - llm_client.send_user_message()でプロンプト送信
   - llm_client.get_response()で応答取得

4. **応答パース**
   - LLM応答からJSON形式で環境名を抽出
   - 期待フォーマット: {"selected_environment": "python", "reasoning": "..."}

5. **環境名検証**
   - 選択された環境名が有効（python, miniforge, node, default）か確認
   - 無効な場合は"default"を使用

6. **結果返却**
   - (選択環境名, 判定詳細辞書)のタプルを返す

---

## 9. MCPClient関連

### 7.1 MCPClient

#### 7.1.1 概要

MCPClientはstdio経由でMCPサーバーと通信するクライアント。

#### 7.1.2 保持データ

- **server_config: MCPServerConfig** - サーバー設定
- **process: subprocess.Popen** - MCPサーバープロセス
- **stdin: IO** - 標準入力
- **stdout: IO** - 標準出力

#### 7.1.3 主要メソッド

##### connect() → None

**処理フロー**:

1. **プロセス起動**
   - subprocess.Popenでserver_config.commandを実行
   - stdin=subprocess.PIPE、stdout=subprocess.PIPE、stderr=subprocess.PIPE
   - env=server_config.envを設定

2. **初期化メッセージ送信**
   - MCPプロトコルの初期化メッセージをstdinに送信
   - JSONフォーマット: {"jsonrpc": "2.0", "method": "initialize", "params": {...}}

3. **初期化レスポンス受信**
   - stdoutから初期化レスポンスを読み込み
   - JSONパース

4. **接続確立**

##### list_tools() → List[MCPTool]

**処理フロー**:

1. **list_toolsリクエスト送信**
   - MCPプロトコルのlist_toolsメッセージをstdinに送信
   - JSONフォーマット: {"jsonrpc": "2.0", "method": "tools/list", "params": {}}

2. **レスポンス受信**
   - stdoutからレスポンスを読み込み
   - JSONパース

3. **ツール一覧抽出**
   - レスポンスのresult.toolsからツール一覧を抽出
   - 各ツールをMCPToolオブジェクトに変換

4. **ツール一覧返却**

##### call_tool(tool_name: str, arguments: Dict[str, Any]) → Dict[str, Any]

**処理フロー**:

1. **call_toolリクエスト送信**
   - MCPプロトコルのcall_toolメッセージをstdinに送信
   - JSONフォーマット: {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}

2. **レスポンス受信**
   - stdoutからレスポンスを読み込み
   - JSONパース

3. **結果抽出**
   - レスポンスのresultフィールドを抽出

4. **結果返却**

##### disconnect() → None

**処理フロー**:

1. **プロセス終了**
   - process.terminate()でプロセス終了
   - process.wait()で終了待機

### 7.2 EnvironmentAwareMCPClient

#### 7.2.1 概要

EnvironmentAwareMCPClientはノードIDから環境IDを解決してMCP通信を行うクライアント。

#### 7.2.2 保持データ

- **base_client: MCPClient** - ベースMCPクライアント
- **env_manager: ExecutionEnvironmentManager** - 環境マネージャー
- **current_node_id: str** - 現在実行中のノードID

#### 7.2.3 主要メソッド

##### call_tool(tool_name: str, arguments: Dict[str, Any]) → Dict[str, Any]

**処理フロー**:

1. **環境ID取得**
   - env_id = env_manager.get_environment(current_node_id)

2. **引数に環境ID追加**
   - arguments['environment_id'] = env_id

3. **ベースクライアント呼び出し**
   - result = base_client.call_tool(tool_name, arguments)

4. **結果返却**

---

## 8. その他の主要クラス

### 8.1 TodoManagementTool

#### 8.1.1 概要

TodoManagementToolはAgent Frameworkのネイティブツールとして実装されるTodo管理ツール。

#### 8.1.2 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **gitlab_client: GitLabClient** - GitLab APIクライアント

#### 8.1.3 主要メソッド

各メソッドはKernelFunctionとして登録される。

##### create_todo_list(project_id: int, mr_iid: int, todos: List[Dict]) → Dict

**処理フロー**:

1. **タスクUUID取得**
   - contextからtask_uuidを取得

2. **Todoループ**
   - todosをループ
   - 各todoについて:
     - SQLクエリ実行: `INSERT INTO todos (task_uuid, title, description, status, order_index) VALUES (?, ?, ?, ?, ?)`
     - 生成されたtodo_idを取得

3. **結果返却**
   - {"status": "success", "todo_ids": [id1, id2, ...]}

##### sync_to_gitlab(project_id: int, mr_iid: int) → Dict

**処理フロー**:

1. **タスクUUID取得**
   - contextからtask_uuidを取得

2. **TodoリストSQL取得**
   - SQLクエリ実行: `SELECT id, title, status, parent_todo_id FROM todos WHERE task_uuid = ? ORDER BY order_index`

3. **Markdown形式変換**
   - Todoリストを階層構造でMarkdown形式に変換
   - completed: `[x]`、not-started/in-progress: `[ ]`

4. **GitLabに投稿**
   - gitlab_client.add_merge_request_note(project_id, mr_iid, markdown_content)

5. **結果返却**
   - {"status": "success"}

### 8.2 IssueToMRConverter

#### 8.2.1 概要

IssueToMRConverterはIssueからMRへの変換を実行する。

#### 8.2.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **llm_client: LLMClient** - LLMクライアント（ブランチ名生成用）
- **config: IssueToMRConfig** - Issue→MR変換設定

#### 8.2.3 主要メソッド

##### convert(issue: Issue) → MergeRequest

**処理フロー**:

1. **ブランチ名生成**
   - llm_client.generate()でLLMにブランチ名生成を依頼
   - プロンプト: f"Generate a git branch name for the following issue: {issue.title}. Use format: {config.branch_prefix}{{issue_iid}}"
   - 生成されたブランチ名を取得

2. **ブランチ作成**
   - gitlab_client.create_branch(project_id=issue.project_id, branch_name=branch_name, ref=config.target_branch)

3. **空コミット作成**
   - commit_message = f"Initial commit for issue #{issue.iid}"
   - gitlab_client.create_commit(project_id, branch_name, commit_message, actions=[])

4. **MR作成**
   - title = config.mr_title_template.format(issue_title=issue.title)
   - description = issue.description
   - gitlab_client.create_merge_request(project_id, source_branch=branch_name, target_branch=config.target_branch, title=title, description=description)
   - 作成されたMRオブジェクトを取得

5. **Issueコメント転記**
   - gitlab_client.list_issue_notes(project_id, issue.iid)でコメント一覧取得
   - コメントをループしてgitlab_client.add_merge_request_note(project_id, mr.iid, comment.body)

6. **Issueラベル・アサイニーコピー**
   - gitlab_client.update_merge_request(project_id, mr.iid, labels=issue.labels, assignees=issue.assignees)

7. **Issueにコメント投稿**
   - gitlab_client.add_issue_note(project_id, issue.iid, f"Created MR: !{mr.iid}")

8. **Issue Done化**
   - gitlab_client.update_issue(project_id, issue.iid, labels=issue.labels + [config.done_label])

9. **MR返却**

### 8.3 ProgressReporter

#### 8.3.1 概要

ProgressReporterはタスクの進捗状況をMRコメントとして投稿する。

#### 8.3.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **context_storage_manager: ContextStorageManager** - コンテキストストレージマネージャー

#### 8.3.3 主要メソッド

##### report_progress(mr_iid: int, phase: str, message: str, details: Dict) → None

**処理フロー**:

1. **コメント生成**
   - format_progress_comment(phase, message, details)を呼び出し
   - Markdown形式のコメントを取得

2. **GitLabに投稿**
   - gitlab_client.add_merge_request_note(project_id, mr_iid, comment)

3. **進捗ログ記録**
   - add_progress_log(mr_iid, phase, message, details)を呼び出し

##### format_progress_comment(phase: str, message: str, details: Dict) → str

**処理フロー**:

1. **フェーズ別フォーマット**
   - start: 🚀 絵文字、タスク種別、担当エージェント、開始時刻
   - planning: 📋 絵文字、主要ステップのサマリ、Todoリストへのリンク
   - execution: ⏳ 絵文字、現在のステップ、進捗率
   - review: 🔍 絵文字、問題点のリスト、修正提案
   - test: ✅ 絵文字、成功率、カバレッジ、失敗詳細
   - complete: ✨ 絵文字、実行時間、主要な変更のサマリ
   - error: ❌ 絵文字、エラー種別、エラーメッセージ

2. **Markdown生成**
   - フェーズに応じたMarkdownテンプレートを使用
   - detailsの各フィールドをテンプレートに埋め込み

3. **Markdown返却**

##### add_progress_log(mr_iid: int, phase: str, message: str, details: Dict) → None

**処理フロー**:

1. **ログエントリ生成**
   - log_entry = {"phase": phase, "message": message, "details": details, "timestamp": datetime.now()}

2. **コンテキストストレージに記録**
   - context_storage_manager.append_progress_log(task_uuid, log_entry)

---

## 9. まとめ

本仕様書では、CODE_AGENT_ORCHESTRATORで実装する主要クラスの詳細設計を記載した。

**記載した主要クラス**:
- ConfigurableAgent: 汎用エージェントクラス
- Factory群: WorkflowFactory、ExecutorFactory、AgentFactory、MCPClientFactory、TaskStrategyFactory
- Executor群: BaseExecutor、UserResolverExecutor、ContentTransferExecutor、EnvironmentSetupExecutor
- Custom Provider群: PostgreSqlChatHistoryProvider、PlanningContextProvider、ToolResultContextProvider
- Middleware実装: CommentCheckMiddleware、TokenUsageMiddleware、ErrorHandlingMiddleware
- ExecutionEnvironmentManager: Docker環境管理
- MCPClient関連: MCPClient、EnvironmentAwareMCPClient
- その他: TodoManagementTool、IssueToMRConverter、ProgressReporter

**実装時の注意点**:
- すべてのメソッドは非同期（async/await）で実装する
- エラーハンドリングは適切に実施する
- ログ記録は構造化ログで実施する
- テストは単体テスト・統合テストを両方実施する

実装時は本仕様書を参照し、Agent FrameworkのProcess Framework（Workflow/Executor）の標準機能を活用して実装する。コード例を含まず日本語で記述された処理フローに基づいて実装する。
