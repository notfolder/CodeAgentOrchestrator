# クラス実装詳細仕様書

本ドキュメントは、AUTOMATA_CODEX_SPEC.mdで定義されたシステムの主要クラスの実装詳細を記載する。各クラスの責務、保持データ、メソッドの処理フローを日本語で具体的に記述し、コード例は含めない。

---

## 1. ConfigurableAgent（汎用エージェントクラス）

### 1.1 概要

ConfigurableAgentはグラフ内のすべてのエージェントノードを実装する単一クラス。エージェント定義ファイルの設定に基づいて動作する。

### 1.2 継承関係

Agent Frameworkの[Executor](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_workflows/_executor.py)を継承する。

### 1.3 保持データ

- **config: AgentNodeConfig** - エージェント定義から取得した設定
  - node_id: ノードID
  - agent_definition_id: エージェント定義ID
  - role: ロール（planning/reflection/execution/review）
  - input_keys: 入力キー一覧
  - output_keys: 出力キー一覧
  - mcp_servers: 利用するMCPサーバー名一覧（実MCPサーバーおよび仮想MCPサーバー `todo_list`）
  - environment_mode: は廃止。代替は`env_ref`フィールド（グラフ定義の`AgentNodeConfig`に保持）
  - env_ref: 使用する実行環境の参照（"plan": plan共有環境、"1"/"2"/"3": 分岐内の第N実行環境、省略: 環境不要）
  - prompt_id: プロンプト定義ID
- **agent: Agent** - Agent Frameworkの[Agent](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_agents.py)インスタンス（LLM呼び出し）
- **tools: list[MCPStdioTool | FunctionTool]** - エージェントが使用するツールリスト（`mcp_servers` の各サーバーを解決して生成した [MCPStdioTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py) / [FunctionTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_tools.py) の結合リスト）
- **progress_reporter: ProgressReporter** - 進捗報告インスタンス
- **environment_id: str** - ビルド時に確定したDocker環境ID。`env_ref`が"plan"の場合はコンテキストの`plan_environment_id`から、"1"/"2"/"3"の場合はコンテキストの`branch_envs[N]["env_id"]`からビルド時に取得する。省略の場合はNone
- **prompt_content: str** - プロンプト定義から取得したシステムプロンプト

### 1.4 主要メソッド

#### @handler async def handle(self, msg, ctx: WorkflowContext)

**処理フロー**:

1. **タスクMR/Issue IID取得**
   - ctx.get_state("task_mr_iid")でMR IIDを取得
   - 存在しない場合は"task_issue_iid"を取得
   - task_iid変数に保存

2. **入力データ取得**
   - config.input_keysをループ
   - 各キーについてctx.get_state(key)を呼び出し
   - 取得した値をinput_data辞書に格納

3. **進捗報告（開始）**
   - progress_reporter.report_progress(task_iid, event="start", agent_definition_id=config.agent_definition_id, node_id=config.node_id, details={})を呼び出し

4. **プロンプト生成**
   - prompt_contentをベースにプロンプトを構築
   - input_dataの各キーをプレースホルダーとして置換
   - 例: `{task_description}`を`input_data['task_description']`で置換

5. **Agent Frameworkの[Agent.run()](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_agents.py)呼び出し**
   - await agent.run([Message(role="user", text=prompt)], session=session)を呼び出し
   - sessionはエージェント生成時に作成したAgentSessionを使用
   - 会話履歴は[BaseHistoryProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)経由で自動的にロードされる（PostgreSqlChatHistoryProvider経由）

6. **LLM応答取得**
   - Agent Frameworkから[Message](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_types.py)を取得
   - メッセージ内容をテキストまたはJSON形式でパース

7. **進捗報告（LLM応答）**
   - response_summary = 応答内容の要約（最初の200文字程度）
   - progress_reporter.report_progress(task_iid, event="llm_response", agent_definition_id=config.agent_definition_id, node_id=config.node_id, details={"summary": response_summary})を呼び出し

8. **ツール呼び出し処理**
   - Agent Frameworkが[MCPStdioTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py)を自動的に呼び出すため、明示的な実装は不要
     - tool_choice="auto"の設定により、LLMがツール呼び出しを判断して自動実行
     - ツール実行結果をLLMに返すフィードバックループはフレームワークが管理
     - 最終応答を取得

9. **ロール別の後処理**
   - **planning**: Todoリスト作成
   - **reflection**: 改善判定
   - **execution**: ファイル操作結果の確認、git操作の実行
   - **review**: レビューコメント生成

10. **進捗報告（完了）**
   - progress_reporter.report_progress(task_iid, event="complete", agent_definition_id=config.agent_definition_id, node_id=config.node_id, details=output_data)を呼び出し

11. **出力データ保存**
   - config.output_keysをループ
   - 各キーについてctx.set_state(key, value)を呼び出し
   - LLM応答から抽出した値を保存

12. **output_dataを返す**
   - output_dataを戻り値として返す

**注意**: environment_idはビルド時（AgentFactory.create_agent()）に確定済みのため、handle()での動的割り当ては行わない。

#### get_chat_history() → list[Message]

**処理フロー**:

1. [BaseHistoryProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)（PostgreSqlChatHistoryProvider）からget_messages()でメッセージを取得
2. Agent Frameworkの[Message](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_types.py)一覧として返す

#### get_context(keys: List[str]) → Dict[str, Any]

**処理フロー**:

1. keysをループ
2. 各キーについてctx.get_state(key)を呼び出し
3. 取得した値を辞書に格納して返す

#### store_result(output_keys: List[str], result: Dict[str, Any]) → None

**処理フロー**:

1. output_keysをループ
2. 各キーについてresult辞書から値を取得
3. ctx.set_state(key, value)を呼び出し

#### invoke_mcp_tool(tool_name: str, params: Dict[str, Any]) → Dict[str, Any]

**処理フロー**:

1. config.mcp_serversにtool_nameが含まれているか確認（含まれていない場合はエラー）
2. [MCPStdioTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py)経由でtool_nameのツールを呼び出す（Agent Frameworkが自動的に実行するため、エージェントがツール呼び出しを求めた場合に使用）
3. 結果を辞書形式で返す

---

## 2. Factory群

### 2.1 WorkflowFactory

WorkflowFactoryはAgent FrameworkのProcess Frameworkを使用してワークフローを生成する。グラフ定義からAgent FrameworkのWorkflowインスタンスを動的に構築し、必要なExecutorとAgentを登録する。

**主要メソッド**:
- `create_workflow_from_definition(user_id, task_context)`: グラフ定義からWorkflowを生成
- `_build_nodes(graph_def, agent_def, prompt_def, user_id)`: ノードをExecutorまたはAgentとして生成（`user_id`を渡してAgentFactoryへ伝播させる）
- `_inject_learning_node(workflow, user_id)`: GuidelineLearningAgentノードをワークフローの末尾に自動挿入する（グラフ定義への明示的記載不要）
- `_setup_plan_environment()`: ワークフロー開始前にpython固定のplan環境を1つ作成しリポジトリをclone、`plan_environment_id`をコンテキストに保存する
- `save_workflow_state(execution_id, current_node_id, completed_nodes)`: ワークフロー状態をDBに保存
- `load_workflow_state(execution_id)`: ワークフロー状態をDBから復元
- `resume_workflow(execution_id)`: 停止したワークフローを再開

**停止・再開関連メソッドの処理フロー**:

#### save_workflow_state(execution_id: str, current_node_id: str, completed_nodes: List[str]) → None

1. **データベース接続取得**
   - PostgreSQLのデータベース接続を取得

2. **ワークフロー状態レコード挿入または更新**
   - workflow_execution_statesテーブルにINSERTまたはUPDATE
   - フィールド: execution_id（PK）、task_uuid（tasksテーブルから取得）、workflow_definition_id（現在使用中の定義ID）、current_node_id、completed_nodes（JSON配列）、workflow_status（'suspended'）、suspended_at（現在時刻）、updated_at（現在時刻）

3. **コミット**
   - データベースコミット

#### load_workflow_state(execution_id: str) → Dict[str, Any]

1. **データベース接続取得**
   - PostgreSQLのデータベース接続を取得

2. **ワークフロー状態検索**
   - workflow_execution_statesテーブルからexecution_idに一致するレコードをSELECT
   - レコードが存在しない場合: ValueErrorをスロー

3. **状態辞書生成**
   - レコードから以下を取得してDictに格納:
     - task_uuid
     - workflow_definition_id
     - current_node_id
     - completed_nodes（JSON配列をList[str]にデコード）
     - suspended_at

4. **状態辞書返却**

#### resume_workflow(execution_id: str) → None

1. **ワークフロー状態読み込み**
   - load_workflow_state(execution_id)を呼び出し
   - task_uuid、workflow_definition_id、current_node_id、completed_nodesを取得

2. **タスクコンテキスト取得**
   - tasksテーブルからtask_uuidに一致するレコードを検索
   - TaskContextインスタンスを生成

3. **ワークフロー定義読み込み**
   - workflow_definition_idに対応するグラフ定義、Agent定義、プロンプト定義をDBまたは設定ファイルから読み込み

4. **ワークフローインスタンス生成**
   - create_workflow_from_definition()を呼び出してWorkflowインスタンスを生成

5. **完了ノードスキップ**
   - ワークフローのcompleted_nodesプロパティにcompleted_nodesをセット（Agent Frameworkがこれらのノードをスキップする）

6. **ワークフロー再開実行**
   - ワークフローの実行状態（`current_node_id`）をコンテキストに設定し、`WorkflowFactory.start_workflow()`を呼び出してワークフローを再開する。Semantic Kernel Process Frameworkでは実行コンテキスト経由でノードスキップを制御する（`start_from_node()`は公開APIとして存在しないため、完了済みノードの状態をコンテキストに格納して実行エンジン側でスキップさせる設計を採用する）。

7. **ワークフロー状態更新**
   - workflow_execution_statesテーブルのworkflow_statusを'running'に更新

8. **コミット**
   - データベースコミット

**シグナルハンドラ**:

WorkflowFactoryはSIGTERMシグナルを受信した際の処理を実装する。

#### _setup_signal_handlers() → None

1. **シャットダウンフラグ初期化**
   - グローバル変数shutdown_requested = False

2. **SIGTERMハンドラ登録**
   - signal.signal(signal.SIGTERM, _handle_sigterm)を呼び出し

#### _handle_sigterm(signum, frame) → None

1. **シャットダウンフラグ設定**
   - shutdown_requested = True

2. **ログ出力**
   - "SIGTERM received. Graceful shutdown initiated."

#### _check_shutdown_between_nodes() → bool

1. **シャットダウンフラグ確認**
   - shutdown_requestedがTrueの場合:
     - 現在のノード完了を待機
     - save_workflow_state()を呼び出してワークフロー状態を保存
     - ExecutionEnvironmentManager.save_environment_mapping()を呼び出して環境マッピングを保存
     - ExecutionEnvironmentManager.stop_all_containers()を呼び出してすべてのコンテナを停止
     - "Graceful shutdown completed."ログ出力
     - Trueを返す

2. **通常処理継続**
   - Falseを返す

このメソッドはワークフローの各ノード実行前に呼び出し、停止要求がある場合は安全に停止処理を実行する。

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

##### create_plan_env_setup() → PlanEnvSetupExecutor

**処理フロー**:

1. PlanEnvSetupExecutorインスタンスを生成
2. env_managerとconfigを渡す
3. 返却

##### create_branch_merge(context) → BranchMergeExecutor

**処理フロー**:

1. ワークフローコンテキストから `branch_envs`（並列実行環境一覧）と `selected_implementation`（code_reviewが選択した最良実装のエージェント定義ID）を取得
2. BranchMergeExecutorインスタンスを生成し、gitlab_clientを渡す
3. 返却

### 2.3 AgentFactory

#### 2.3.1 概要

AgentFactoryはConfigurableAgentインスタンスを生成する。

#### 2.3.2 保持データ

- **mcp_server_configs: Dict[str, MCPServerConfig]** - MCPサーバー設定（create_agent()呼び出し時にMCPClientFactoryを新規生成するため、設定情報のみを保持）
- **chat_history_provider: PostgreSqlChatHistoryProvider** - チャット履歴Provider
- **planning_context_provider: PlanningContextProvider** - プランニングコンテキストProvider
- **tool_result_context_provider: ToolResultContextProvider** - ツール結果コンテキストProvider

#### 2.3.3 主要メソッド

##### create_agent(agent_config: AgentNodeConfig, prompt_config: PromptConfig, user_email: str, progress_reporter: ProgressReporter, env_id: str | None = None) → ConfigurableAgent

**処理フロー**:

1. **ツールリスト構築とMCPClientFactory新規生成**
   - mcp_server_configsを渡して、このエージェント専用のMCPClientFactoryインスタンスを新規生成する

2. **ツールリスト構築**
   - agent_config.mcp_serversをループ
   - 各サーバー名について:
     - `todo_list` の場合（仮想MCPサーバー）: TodoManagementToolのFunctionTool群（`create_todo_list` / `get_todo_list` / `update_todo_status`）をツールリストに追加する
     - それ以外の場合（実MCPサーバー）: mcp_client_factory.create_mcp_tool(server_name, env_id)で[MCPStdioTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py)オブジェクトを生成してツールリストに追加する

3. **User Config取得**
   - UserConfigClientからuser_emailのLLM設定を取得
   - api_key、model_name、temperature等を取得

4. **ChatClient生成**
   - Agent Frameworkの[OpenAIChatClient](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/openai/_chat_client.py)または[AzureOpenAIChatClient](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/azure/_chat_client.py)を生成
   - OpenAI/Azure OpenAI/Ollama/LM Studioプロバイダーに応じて適切なクライアントを選択
   - api_key、model_name等を設定

5. **システムプロンプト構築**
   - `chat_options.instructions`に設定するプロンプトを組み立てる
   - プロンプト冒頭にリポジトリから読み込んだ以下のファイルを含める（YAMLフロントマターを持つため自動組み込み）:
     - **AGENTS.md**: エージェントの動作モード定義（ドキュメント作成モード、コード実装モード等）
     - **PROJECT_GUIDELINES.md**: プロジェクト固有の品質基準（学習機能により自動成長、存在しない場合はスキップ）
   - その後に`prompt_config.content`（プロンプト定義のシステムプロンプト）を連結する
   - 両ファイルはワークフロー開始時に最新内容を読み込み、すべてのエージェント呼び出しで同一内容を使用する

6. **Agent生成**
   - Agent(client=chat_client, tools=tool_list, context_providers=[planning_context_provider, tool_result_context_provider])を呼び出し
   - 引数を設定:
     - client: 手順4で生成したOpenAIChatClientまたはAzureOpenAIChatClient
     - instructions: 手順5で組み立てたシステムプロンプト
     - tools: tool_list（FunctionTool、MCPStdioTool等を含む）
     - context_providers: [planning_context_provider, tool_result_context_provider]
   - Agentインスタンスを取得

7. **ConfigurableAgentインスタンス生成**
   - agent_config、Agent、prompt_config.content、progress_reporterを渡す
   - `env_ref`が"plan"の場合、environment_idにはワークフローコンテキストの`plan_environment_id`をビルド時に設定する（AgentFactory.create_agent()呼び出し元がplan_environment_idをenv_idとして渡す）
   - `env_ref`が数値文字列（"1"/"2"/"3"等）の場合、environment_idには`branch_envs[N]["env_id"]`をビルド時に設定する。さらに`branch_envs[N]["branch"]`を`task_context.assigned_branch`に設定することで、エージェントが作業ブランチ名を取得できるようにする（standard/multiの区別なく共通で適用する）
   - `env_ref`が省略の場合、environment_idにはNoneを設定する（`task_context.assigned_branch`は変更しない）

8. **ConfigurableAgent返却**

### 2.4 MCPClientFactory

#### 2.4.1 概要

MCPClientFactoryはMCPサーバーへの[MCPStdioTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py)を生成し、Agentのtoolsリストに渡せる形で返す。Agent FrameworkはMCPStdioToolをAgentのコンストラクタに直接渡す設計のため、Kernelへの登録は不要。

#### 2.4.2 保持データ

- **mcp_server_configs: Dict[str, MCPServerConfig]** - サーバー設定辞書
- **mcp_tool_registry: Dict[str, MCPStdioTool]** - 生成済みMCPStdioToolの管理辞書

#### 2.4.3 主要メソッド

##### create_mcp_tool(server_name: str, env_id: str) → [MCPStdioTool](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_mcp.py)

**処理フロー**:

1. **既存ツール確認**
   - mcp_tool_registryでserver_nameが登録済みか確認
   - 登録済みの場合: 既存のMCPStdioToolを返す

2. **サーバー設定取得**
   - mcp_server_configsからserver_nameに対応するMCPServerConfigを取得
   - 存在しない場合: エラーをスロー

3. **MCPStdioToolインスタンス生成**
   - MCPServerConfigのcommandにenv_idを埋め込み、接続対象のDockerコンテナを特定する
   - commandとenvを使用してMCPStdioTool(command=..., args=..., env=...)を生成する
   - Agent FrameworkがAgent.run()呼び出し時にMCPStdioTool経由でMCPサーバーに自動接続する

4. **ツール登録**
   - mcp_tool_registryにserver_nameとmcp_toolを登録

5. **MCPStdioTool返却**

##### create_text_editor_tool(env_id: str) → MCPStdioTool

**処理フロー**:

1. create_mcp_tool('text-editor', env_id)を呼び出す
2. 返却

##### create_command_executor_tool(env_id: str) → MCPStdioTool

**処理フロー**:

1. create_mcp_tool('command-executor', env_id)を呼び出す
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

### 2.6 WorkflowBuilder

#### 2.6.1 概要

WorkflowBuilderはグラフ定義のノード・エッジを受け取り、Agent FrameworkのWorkflowオブジェクトを組み立てる独立クラス。WorkflowFactoryがコンストラクタで保持し、各ノード登録後に`build()`を呼び出す。

#### 2.6.2 保持データ

- **workflow: Workflow** - Agent Framework Workflowインスタンス（未完成状態）
- **node_registry: Dict[str, Any]** - ノードID → 登録済みノードインスタンスのマッピング
- **edge_registry: List[Dict]** - 追加予定のエッジ定義リスト

#### 2.6.3 主要メソッド

##### add_node(node_id: str, node_instance: Any) → None

**処理フロー**:

1. **ノード登録**
   - workflow.add_node(node_id, node_instance)を呼び出し
   - node_registry[node_id] = node_instanceを記録

##### add_edge(from_node_id: str, to_node_id: str, condition: Optional[str] = None) → None

**処理フロー**:

1. **エッジ情報をキュー登録**
   - edge_registry に {"from": from_node_id, "to": to_node_id, "condition": condition} を追加

##### build() → Workflow

**処理フロー**:

1. **エッジ追加**
   - edge_registryをイテレートし、conditionが指定されている場合はworkflow.add_conditional_edge()、ない場合はworkflow.add_edge()を呼び出す

2. **エントリポイント設定**
   - node_registryの最初に登録されたノードをエントリポイントとして設定

3. **Workflowオブジェクト返却**
   - 完成したworkflowを返す

---

### 2.7 ITaskStrategy（戦略インターフェース）

#### 2.7.1 概要

ITaskStrategyはTaskStrategyFactoryが返す処理戦略の共通インターフェース。タスク種別に応じた具体的な戦略クラス（IssueToMRConversionStrategy・IssueOnlyStrategy・MergeRequestStrategy）がこのインターフェースを実装する。

#### 2.7.2 抽象メソッド

##### execute(task: Task) → None

**処理フロー**:

各サブクラスに処理を委譲する抽象メソッド。TaskHandlerはITaskStrategyを受け取り、具体的なクラスを意識せずに `execute(task)` を呼び出す。

---

### 2.8 IssueToMRConversionStrategy（Issue→MR変換戦略）

#### 2.8.1 概要

IssueをGitLab MRに変換した後、タスクステータスをcompletedに更新して処理を完了する戦略クラス。作成されたMRはProducerが次回ポーリング時に検出し、MR処理ワークフローとして独立して処理される。

#### 2.8.2 保持データ

- **issue_to_mr_converter: IssueToMRConverter** - Issue→MR変換クラス
- **task_repository: TaskRepository** - タスクステータス更新用リポジトリ

#### 2.8.3 主要メソッド

##### execute(task: Task) → None

**処理フロー**:

1. **Issue→MR変換実行**
   - issue_to_mr_converter.convert(task)を呼び出し、Issue情報を取得してブランチ・空コミット・MRを作成する
   - 変換処理の詳細は`AUTOMATA_CODEX_SPEC.md §5.0.2〜§5.0.5`を参照

2. **タスクステータス更新**
   - task_repository.update_status(task.task_uuid, "completed")を呼び出す
   - 作成されたMRはProducerが次回ポーリング時に検出し、MergeRequestStrategyとして独立して処理される

---

### 2.9 IssueOnlyStrategy（Issueのみ処理戦略）

#### 2.9.1 概要

Issue→MR変換が不要な場合（変換設定無効・変換条件不成立など）に、MRを作成せずIssue上で処理を完結させる戦略クラス。処理済みラベルを付与し、Issueにコメントを投稿してタスクを完了する。

#### 2.9.2 保持データ

- **gitlab_client: GitLabClient** - GitLab API操作クライアント
- **config_manager: ConfigManager** - 設定管理（doneラベル名の取得に使用）
- **task_repository: TaskRepository** - タスクステータス更新用リポジトリ

#### 2.9.3 主要メソッド

##### execute(task: Task) → None

**処理フロー**:

1. **Issue情報取得**
   - gitlab_client.get_issue(task.project_id, task.issue_iid)でIssue情報を取得する

2. **処理済みラベル付与**
   - gitlab_client.add_label(task.project_id, task.issue_iid, config_manager.get_done_label())を呼び出し、Issueに処理済みラベルを付与する

3. **完了コメント投稿**
   - gitlab_client.create_issue_comment()でIssueに「このIssueはMRへの変換を行わずに処理を完了しました。」とコメントを投稿する

4. **タスクステータス更新**
   - task_repository.update_status(task.task_uuid, "completed")を呼び出す

---

### 2.10 MergeRequestStrategy（MR処理戦略）

#### 2.10.1 概要

MR処理ワークフローをDefinitionLoaderで定義をロードし、WorkflowFactoryでワークフローを構築・実行する戦略クラス。ConsumerがMRタスクを受信した際に使用される主要戦略。

#### 2.10.2 保持データ

- **workflow_factory: WorkflowFactory** - ワークフロー生成クラス
- **definition_loader: DefinitionLoader** - ワークフロー定義ロードクラス
- **task_repository: TaskRepository** - タスクステータス更新用リポジトリ

#### 2.10.3 主要メソッド

##### execute(task: Task) → None

**処理フロー**:

1. **タスクステータスをin_progressに更新**
   - task_repository.update_status(task.task_uuid, "in_progress")を呼び出す

2. **ワークフロー定義ロード**
   - definition_loader.load_workflow_definition(user_workflow_definition_id)でグラフ定義・エージェント定義・プロンプト定義を取得する
   - user_workflow_definition_idはtaskのuser_idからUserRepositoryで取得したuser_workflow_settingsから参照する

3. **ワークフロー構築・実行**
   - workflow_factory.create_workflow_from_definition(task.user_id, task_context)を呼び出し、ワークフローを構築して実行する
   - 停止・再開機構（SIGTERMハンドラー・workflow_execution_statesへの永続化）はWorkflowFactoryが内部で管理する

4. **タスクステータス更新**
   - 正常完了時: task_repository.update_status(task.task_uuid, "completed")を呼び出す
   - 異常終了時: task_repository.update_status(task.task_uuid, "failed")を呼び出す

---

## 3. Executor群

### 3.1 BaseExecutor（抽象基底クラス）

#### 3.1.1 概要

BaseExecutorはすべてのExecutorの共通機能を提供する抽象基底クラス。

#### 3.1.2 保持データ

- **WorkflowContext** - ワークフローコンテキスト（handle()の引数ctxとして受け取る、フィールドとしては保持しない）

#### 3.1.3 抽象メソッド

##### @handler async def handle(self, msg, ctx: WorkflowContext)

サブクラスで実装する。

#### 3.1.4 共通ヘルパーメソッド

##### get_context_value(key: str, scope_name: str = 'workflow') → Any

**処理フロー**:

1. ctx.get_state(key)を呼び出し
2. 値を返す

##### set_context_value(key: str, value: Any, scope_name: str = 'workflow') → None

**処理フロー**:

1. ctx.set_state(key, value)を呼び出し

### 3.2 UserResolverExecutor

#### 3.2.1 概要

UserResolverExecutorはユーザー情報を取得し、LLM設定をワークフローコンテキストに保存する。

#### 3.2.2 保持データ

- **user_config_client: UserConfigClient** - ユーザー設定クライアント

#### 3.2.3 主要メソッド

##### @handler async def handle(self, msg, ctx: WorkflowContext)

**処理フロー**:

1. **タスク情報取得**
   - ctx.get_state('task_identifier')を呼び出し
   - task_identifierから project_id、mr_iid等を抽出

2. **GitLabからユーザー情報取得**
   - gitlab_client.get_merge_request(project_id, mr_iid)を呼び出し
   - MR.authorからユーザーメールアドレスを取得

3. **User Config取得**
   - user_config_client.get_user_config(user_email)を呼び出し
   - LLM設定（api_key、model_name、temperature等）を取得

4. **ワークフローコンテキストに保存**
   - ctx.set_state('user_email', user_email)
   - ctx.set_state('user_config', user_config)

5. **処理完了**
   - 実行を終了する

### 3.3 ContentTransferExecutor

#### 3.3.1 概要

ContentTransferExecutorはIssueコメントをMRに転記する。

#### 3.3.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント

#### 3.3.3 主要メソッド

##### @handler async def handle(self, msg, ctx: WorkflowContext)

**処理フロー**:

1. **Issue情報取得**
   - ctx.get_state('issue_iid')を呼び出し
   - ctx.get_state('project_id')を呼び出し

2. **Issueコメント取得**
   - gitlab_client.list_issue_notes(project_id, issue_iid)を呼び出し
   - コメント一覧を取得

3. **MR情報取得**
   - ctx.get_state('mr_iid')を呼び出し

4. **MRにコメント転記**
   - コメント一覧をループ
   - 各コメントについてgitlab_client.add_merge_request_note(project_id, mr_iid, comment.body)を呼び出し

5. **転記数記録**
   - ctx.set_state('transferred_comments_count', count)

6. **処理完了**
   - 実行を終了する

### 3.4 PlanEnvSetupExecutor

#### 3.4.1 概要

PlanEnvSetupExecutorはワークフロー開始前（グラフ実行前）にpython固定のplan環境を1つ作成し、リポジトリをcloneする。作成した環境IDはコンテキストの`plan_environment_id`に保存する。

#### 3.4.2 保持データ

- **env_manager: ExecutionEnvironmentManager** - 環境マネージャー
- **config: Dict** - plan_environment_name（デフォルト: "python"）を含む設定辞書

#### 3.4.3 主要メソッド

##### @handler async def handle(self, msg, ctx: WorkflowContext)

**処理フロー**:

1. **設定取得**
   - configから`plan_environment_name`を取得（存在しない場合は"python"をデフォルト値として使用）

2. **MR情報取得**
   - ctx.get_state('task_mr_iid')を呼び出し

3. **plan環境の作成**
   - env_manager.prepare_plan_environment(environment_name=plan_environment_name, mr_iid=mr_iid)を呼び出し
   - 環境IDは`codeagent-plan-mr{mr_iid}`形式で生成される

4. **plan環境IDをコンテキストに保存**
   - ctx.set_state('plan_environment_id', plan_env_id)

5. **リポジトリclone**
   - ctx.get_state('repo_url')でリポジトリURLを取得
   - ctx.get_state('original_branch')でブランチ名を取得
   - env_manager.clone_repository(node_id='plan', repo_url=repo_url, branch=branch)を呼び出し

6. **処理完了**
   - 実行を終了する

### 3.5 ExecEnvSetupExecutor

#### 3.5.1 概要

ExecEnvSetupExecutorはPrePlan（task_classifier）完了後にグラフノードとして実行し、`selected_environment`を参照して`"create"`ノード数分の実行環境を作成する。

#### 3.5.2 保持データ

- **env_manager: ExecutionEnvironmentManager** - 環境マネージャー
- **gitlab_client: GitLabClient** - GitLabクライアント（サブブランチ作成用）
- **graph_definition: Dict** - ワークフローのグラフ定義

#### 3.5.3 主要メソッド

##### @handler async def handle(self, msg, ctx: WorkflowContext)

**処理フロー**:

1. **MR IID取得**
   - ctx.get_state('task_mr_iid')を呼び出し

2. **env_count取得**
   - ノード自身の設定（node_config）から`env_count`フィールドを読み取る（作成する実行環境の数）

3. **実行環境名の決定**
   - ctx.get_state('selected_environment')を呼び出し（task_classifierが設定した値を取得）

4. **Docker実行環境の準備**
   - env_manager.prepare_environments(count=env_count, environment_name=selected_environment, mr_iid=mr_iid, node_id=自ノードID)を呼び出し
   - 人間可読な環境ID（`codeagent-{environment_name}-mr{mr_iid}-{自ノードID}-{N}`形式）のリストを取得

5. **GitLabブランチの決定と作成**
   - ctx.get_state('original_branch')を呼び出してoriginal_branchを取得
   - env_count = 1 の場合: サブブランチは作成せず、original_branchを各環境の作業ブランチとして使用する
   - env_count ≥ 2 の場合: サブブランチをenv_count本作成する
     - サフィックスの導出: 自ノードIDから`exec_env_setup_`プレフィックスを除去し、`_`を`-`に変換する（例: `exec_env_setup_code_gen` → `code-gen`）
     - 各N（1〜env_count）に対してブランチ名を`{original_branch}-{サフィックス}-{N}`形式で生成する
     - gitlab_client.create_branch(project_id=task_mr.project_id, branch_name=branch_name, ref=original_branch)を呼び出し

6. **branch_envsをコンテキストに保存**
   - `{N: {"env_id": env_id_N, "branch": branch_name_N}}`形式の辞書を生成して`ctx.set_state('branch_envs', branch_envs)`を呼び出し
   - env_count = 1 の場合、branchにはoriginal_branchを格納する

7. **処理完了**
   - 実行を終了する

### 3.6 BranchMergeExecutor

#### 3.6.1 概要

BranchMergeExecutorはmulti_codegen_mr_processingフローの比較レビューフェーズ（`code_review`）完了後にグラフノードとして実行し、`selected_implementation`が示す最良実装ブランチをオリジナルブランチにマージする。

#### 3.6.2 保持データ

- **gitlab_client: GitLabClient** - GitLabクライアント（MR/ブランチ操作・マージ用）

#### 3.6.3 主要メソッド

##### @handler async def handle(self, msg, ctx: WorkflowContext)

**処理フロー**:

1. **選択実装の取得**
   - ctx.get_state('selected_implementation')を呼び出し（`code_review`エージェントが出力したエージェント定義ID、例: `code_generation_fast`）

2. **ブランチ情報の取得**
   - ctx.get_state('branch_envs')を呼び出し
   - `selected_implementation`に対応するエントリを取得し、`branch`フィールドから選択ブランチ名を取得

3. **オリジナルブランチ取得**
   - ctx.get_state('original_branch')を呼び出し

4. **ブランチマージ**
   - `gitlab_client.merge_branch(source=selected_branch, target=original_branch)`を呼び出し（コンフリクト発生時はエラーを記録して処理を中断）

5. **GitLabへの反映**
   - gitlab_client.update_mr_source_branch(mr_iid, original_branch)を呼び出し（MRのソースブランチを更新）

6. **後処理**
   - 選択されなかった並列ブランチを削除（gitlab_client.delete_branch()）

7. **処理完了**
   - 実行を終了する

---

## 4. Custom Provider群

### 4.1 PostgreSqlChatHistoryProvider

#### 4.1.1 概要

PostgreSqlChatHistoryProviderはLLM会話履歴をPostgreSQLに永続化するカスタムProvider。

#### 4.1.2 継承関係

Agent Frameworkの[BaseHistoryProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)を継承する。

#### 4.1.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続

#### 4.1.4 セッション状態の管理

セッション状態（task_uuid、message_count、total_tokens等）は`before_run`/`after_run`の引数`state: dict`に格納して管理する。C#固有の`ProviderSessionState[ChatHistorySessionState]`型は使用しない。

#### 4.1.5 主要メソッド

##### async def get_messages(self, session_id: str, **kwargs) -> list[[Message](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_types.py)]

**処理フロー**:

1. **session_idからtask_uuidを解決**
   - session_idをtask_uuidとして使用

2. **PostgreSQLから会話履歴取得**
   - SQLクエリ実行: `SELECT role, content, tokens FROM context_messages WHERE task_uuid = ? ORDER BY seq ASC`
   - 結果をループして各行を処理

3. **Message変換**
   - 各行についてAgent Frameworkの[Message](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_types.py)オブジェクトを生成
   - roleに応じてrole="system"、role="user"、role="assistant"、role="tool"を設定
   - contentを設定

4. **Message一覧返却**

##### async def save_messages(self, session_id: str, messages: list[Message], **kwargs) -> None

**処理フロー**:

1. **新規メッセージ処理**
   - session_idをtask_uuidとして使用
   - 保存済みのメッセージ数をpostgresqlから取得し、差分のみ処理対象とする

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

5. **コンテキスト圧縮チェック**
   - contextからユーザーメールアドレス（user_email）を取得
   - ContextCompressionService.check_and_compress_async(task_uuid, user_email)を呼び出し
   - 非同期で実行されるため、結果を待たずに次に進む

### 4.2 PlanningContextProvider

#### 4.2.1 概要

PlanningContextProviderはプランニング履歴を永続化し、コンテキストとしてエージェントに提供するカスタムProvider。

#### 4.2.2 継承関係

Agent Frameworkの[BaseContextProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)を継承する。

#### 4.2.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続

#### 4.2.4 主要メソッド

##### async def before_run(self, *, agent, session, context: [SessionContext](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py), state: dict) -> None

**処理フロー**:

1. **task_uuid取得**
   - sessionまたはstateからtask_uuidを取得

2. **PostgreSQLからプランニング履歴取得**
   - SQLクエリ実行: `SELECT phase, node_id, plan, action_id, result FROM context_planning_history WHERE task_uuid = ? ORDER BY created_at ASC`
   - 結果をループして各行を処理

3. **テキスト整形**
   - planningフェーズ: 計画内容をMarkdown形式で整形
   - executionフェーズ: 実行結果をテキスト形式で整形
   - reflectionフェーズ: リフレクション結果をテキスト形式で整形
   - すべてを連結して大きなテキストブロックを生成

4. **コンテキストに注入**
   - context.context_messages[self.source_id]に整形したテキストを追加メッセージとして設定する

##### async def after_run(self, *, agent, session, context: SessionContext, state: dict) -> None

**処理フロー**:

1. **task_uuid取得**
   - sessionまたはstateからtask_uuidを取得

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

Agent Frameworkの[BaseContextProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)を継承する。

#### 4.3.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **file_storage_base_dir: str** - ファイルストレージのベースディレクトリ

#### 4.3.4 主要メソッド

##### async def before_run(self, *, agent, session, context: [SessionContext](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py), state: dict) -> None

**処理フロー**:

1. **task_uuid取得**
   - sessionまたはstateからtask_uuidを取得

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

5. **コンテキストに注入**
   - context.context_messages[self.source_id]に整形したテキストを追加メッセージとして設定する

##### async def after_run(self, *, agent, session, context: SessionContext, state: dict) -> None

**処理フロー**:

1. **task_uuid取得**
   - sessionまたはstateからtask_uuidを取得

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

### 4.4 ContextCompressionService

#### 4.4.1 概要

ContextCompressionServiceはcontext_messagesテーブルのトークン数を監視し、閾値を超えた場合に古いメッセージを要約して圧縮する。PostgreSqlChatHistoryProviderと連携して動作する。

#### 4.4.2 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **llm_client: LLMClient** - 要約生成用LLMクライアント
- **user_email: str** - ユーザーメールアドレス（設定取得用）
- **config: CompressionConfig** - 圧縮設定（ユーザー設定とモデル推奨値から構築）
- **system_config: Dict** - システムデフォルト設定とモデル推奨値マッピング

#### 4.4.3 主要メソッド

##### check_and_compress_async(task_uuid: str, user_email: str) → bool

**処理フロー**:

1. **ユーザー圧縮設定取得**
   - SQLクエリ実行: `SELECT context_compression_enabled, token_threshold, keep_recent_messages, min_to_compress, min_compression_ratio, model_name FROM user_configs WHERE user_email = ?`
   - context_compression_enabled=falseの場合、False（圧縮無効）を返して終了

2. **token_threshold決定**
   - user_configs.token_thresholdがNULLでない場合: その値を使用
   - NULLの場合: model_nameからsystem_config["model_recommendations"]を参照
     - マッピングに存在する場合: その推奨値を使用
     - 存在しない場合: system_config["default_token_threshold"]を使用

3. **トークン数確認**
   - SQLクエリ実行: `SELECT SUM(tokens) FROM context_messages WHERE task_uuid = ?`
   - total_tokensを計算
   - total_tokens <= token_thresholdなら終了（圧縮不要）

4. **保持対象の特定**
   - SQLクエリ実行: `SELECT seq FROM context_messages WHERE task_uuid = ? ORDER BY seq DESC LIMIT ?`（?=keep_recent_messages）
   - 最新メッセージのseqをセットに追加
   - SQLクエリ実行: `SELECT seq FROM context_messages WHERE task_uuid = ? AND role = 'system'`
   - systemメッセージのseqをセットに追加

5. **圧縮対象の抽出**
   - SQLクエリ実行: `SELECT seq, role FROM context_messages WHERE task_uuid = ? AND is_compressed_summary = false ORDER BY seq ASC`
   - 保持セットに含まれないseqを圧縮対象として抽出
   - 圧縮対象が min_to_compress未満なら終了（圧縮対象不足）
   - 連続するseq範囲を特定: start_seq, end_seq

6. **要約生成**
   - compress_messages_async(task_uuid, start_seq, end_seq)を呼び出し
   - 要約文字列とトークン数を取得

7. **圧縮率検証**
   - 圧縮前トークン数をSQLクエリで取得: `SELECT SUM(tokens) FROM context_messages WHERE task_uuid = ? AND seq >= ? AND seq <= ?`
   - 圧縮率 = 圧縮後トークン数 / 圧縮前トークン数
   - 圧縮率 >= min_compression_ratioなら終了（圧縮効果不足）

8. **メッセージ置き換え**
   - replace_with_summary_async(task_uuid, summary, start_seq, end_seq, 圧縮前トークン数, 圧縮後トークン数)を呼び出し

9. **結果返却**
   - True（圧縮実行）またはFalse（圧縮不要/失敗）を返す

##### compress_messages_async(task_uuid: str, start_seq: int, end_seq: int) → Tuple[str, int]

**処理フロー**:

1. **圧縮対象メッセージ取得**
   - SQLクエリ実行: `SELECT role, content FROM context_messages WHERE task_uuid = ? AND seq >= ? AND seq <= ? ORDER BY seq ASC`
   - 全メッセージを取得してテキスト整形

2. **要約プロンプト構築**
   - 要約生成用プロンプトテンプレートを読み込み
   - start_seq、end_seq、メッセージテキストを埋め込み

3. **LLM呼び出し**
   - llm_client.generate_completion()で要約を生成
   - model=config.summary_llm_model（デフォルト: "gpt-4o-mini"）
   - temperature=config.summary_llm_temperature（デフォルト: 0.3）

4. **トークン数計算**
   - 要約テキストをtiktokenでトークン数計算

5. **結果返却**
   - (要約テキスト, トークン数)のタプルを返す

##### replace_with_summary_async(task_uuid: str, summary: str, start_seq: int, end_seq: int, original_tokens: int, compressed_tokens: int) → None

**処理フロー**:

1. **トランザクション開始**
   - BEGIN TRANSACTION

2. **圧縮対象メッセージ削除**
   - SQLクエリ実行: `DELETE FROM context_messages WHERE task_uuid = ? AND seq >= ? AND seq <= ?`
   - 削除件数を記録

3. **要約メッセージ挿入**
   - summary_text = `[Summary of previous conversation (messages {start_seq}-{end_seq})]: {summary}`
   - compressed_range = `{"start_seq": start_seq, "end_seq": end_seq}`をJSON化
   - SQLクエリ実行: `INSERT INTO context_messages (task_uuid, seq, role, content, tokens, is_compressed_summary, compressed_range, created_at) VALUES (?, ?, 'user', ?, ?, true, ?, NOW())`
   - summary_seq = start_seq（圧縮範囲の先頭seqを再利用）

4. **後続メッセージのseq再番号化**
   - shift_amount = end_seq - start_seq（削除された件数分）
   - SQLクエリ実行: `UPDATE context_messages SET seq = seq - ? WHERE task_uuid = ? AND seq > ?`（?=shift_amount, ?=task_uuid, ?=end_seq）

5. **圧縮履歴記録**
   - compression_ratio = compressed_tokens / original_tokens
   - SQLクエリ実行: `INSERT INTO message_compressions (task_uuid, start_seq, end_seq, summary_seq, original_token_count, compressed_token_count, compression_ratio, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, NOW())`

6. **コミット**
   - COMMIT TRANSACTION

7. **エラーハンドリング**
   - 例外発生時はROLLBACK TRANSACTION
   - エラーログ記録

---

### 4.5 TaskInheritanceContextProvider

#### 4.5.1 概要

TaskInheritanceContextProviderは同一Issue/MRの過去タスクから継承データを取得し、AIContextとして提供するカスタムProvider。

#### 4.5.2 継承関係

Agent Frameworkの[BaseContextProvider](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py)を継承する。

#### 4.5.3 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **config: InheritanceConfig** - 継承設定（expiry_days、enabled等）

#### 4.5.4 主要メソッド

##### async def before_run(self, *, agent, session, context: [SessionContext](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_sessions.py), state: dict) -> None

**処理フロー**:

1. **継承無効化チェック**
   - sessionまたはstateからtask_uuidを取得
   - SQLクエリ実行: `SELECT metadata->'disable_inheritance' FROM tasks WHERE uuid = ?`
   - disable_inheritance=trueの場合、コンテキストへの注入をスキップして終了

2. **現在タスク情報取得**
   - SQLクエリ実行: `SELECT task_identifier, repository FROM tasks WHERE uuid = ?`
   - task_identifier、repositoryを取得

3. **過去タスク検索**
   - _get_past_tasks_async(task_identifier, repository)を呼び出し
   - 最新の成功タスクを1件取得

4. **継承データ取得**
   - 過去タスクが見つからない場合、コンテキストへの注入をスキップして終了
   - SQLクエリ実行: `SELECT metadata->'inheritance_data' FROM tasks WHERE uuid = ?`（過去タスクのuuid）
   - inheritance_dataをJSONBから取得

5. **Markdown整形**
   - _format_inheritance_data(inheritance_data)を呼び出し
   - Markdown形式のテキストに整形

6. **コンテキストに注入**
   - context.context_messages[self.source_id]に整形したテキストを追加メッセージとして設定する

##### _get_past_tasks_async(task_identifier: str, repository: str) → Optional[Task]

**処理フロー**:

1. **検索クエリ実行**
   - SQLクエリ実行: `SELECT uuid, status, completed_at, error_message, metadata FROM tasks WHERE task_identifier = ? AND repository = ? AND status = 'completed' AND error_message IS NULL AND created_at > NOW() - INTERVAL '? days' ORDER BY completed_at DESC LIMIT 5`（?=config.expiry_days、デフォルト30）
   - 最大5件の過去タスクを取得

2. **優先順位選択**
   - 最新のcompleted_atを持つタスクを選択
   - metadata['inheritance_data']['implementation_patterns']の要素数が多いタスクを優先

3. **結果返却**
   - 選択されたタスクオブジェクトを返す
   - 見つからない場合はNoneを返す

##### _format_inheritance_data(inheritance_data: Dict) → str

**処理フロー**:

1. **Markdown構築開始**
   - markdown_text = "## Previous Task Context\n\n"

2. **final_summary整形**
   - final_summary = inheritance_data.get('final_summary', '')
   - markdown_text += f"### Summary\n{final_summary}\n\n"

3. **planning_history整形**
   - planning_history = inheritance_data.get('planning_history', [])
   - markdown_text += "### Planning History\n"
   - 各履歴についてループ: "- Phase: {phase}, Node: {node_id}, Plan: {plan}, Created: {created_at}\n"

4. **implementation_patterns整形**
   - implementation_patterns = inheritance_data.get('implementation_patterns', [])
   - markdown_text += "### Successful Implementation Patterns\n"
   - 各パターンについてループ: "- {pattern_type}: {description}\n"

5. **key_decisions整形**
   - key_decisions = inheritance_data.get('key_decisions', [])
   - markdown_text += "### Key Technical Decisions\n"
   - 各決定についてループ: "- {decision}\n"

6. **Markdown返却**
   - markdown_textを返す

---

### 4.6 ContextStorageManager

#### 4.6.1 概要

ContextStorageManagerは各カスタムProviderとリポジトリへの参照を集約し、TokenUsageMiddlewareおよびErrorHandlingMiddlewareがトークン記録・エラー記録に使用する統合管理クラス。

#### 4.6.2 保持データ

- **chat_history_provider: PostgreSqlChatHistoryProvider** - 会話履歴Provider
- **token_usage_repository: TokenUsageRepository** - トークン使用量リポジトリ
- **context_repository: ContextRepository** - コンテキストリポジトリ
- **task_repository: TaskRepository** - タスクリポジトリ

#### 4.6.3 主要メソッド

##### save_token_usage(user_id: str, task_uuid: str, node_id: str, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int) → None

**処理フロー**:

1. **TokenUsageRecordの生成**
   - 引数をTokenUsageRecordデータクラスに格納

2. **リポジトリへの保存**
   - token_usage_repository.save(record)を呼び出してtoken_usageテーブルに記録

##### save_error(task_uuid: str, node_id: str, error_category: str, error_message: str, stack_trace: str) → None

**処理フロー**:

1. **エラー情報のタスクへの記録**
   - task_repository.update_error(task_uuid, error_category, error_message)を呼び出す

2. **コンテキストへの記録**
   - context_repository.save_metadata(task_uuid, node_id, {"error": {"category": error_category, "message": error_message, "stack_trace": stack_trace}})を呼び出す

---

## 5. Middleware実装

### 5.1 IMiddlewareインターフェース

すべてのMiddlewareが実装する共通インターフェース。

#### intercept(phase: str, node: WorkflowNode, context: WorkflowContext, **kwargs) → Optional[MiddlewareSignal]

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

CommentCheckMiddlewareは新規コメントをチェックし、ノードmetadataの`comment_redirect_to`で指定されたノードへリダイレクトする。

#### 5.2.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **last_comment_check_time: Dict[str, datetime]** - タスクごとの最終チェック時刻

#### 5.2.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: WorkflowContext, **kwargs) → Optional[MiddlewareSignal]

**処理フロー**:

1. **フェーズ判定**
   - phaseが'before_execution'でない場合: Noneを返す（何もしない）

2. **メタデータ確認**
   - node.metadata.check_comments_beforeがTrueでない場合: Noneを返す

3. **タスク情報取得**
   - context.get_state('project_id')を呼び出し
   - context.get_state('mr_iid')を呼び出し

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
   - context.set_state('user_new_comments', new_comments)
   - MiddlewareSignalを生成:
     - action='redirect'
     - redirect_to=node.metadata.comment_redirect_to
     - reason='New user comments detected'
   - MiddlewareSignal返却

### 5.3 TokenUsageMiddleware

#### 5.3.1 概要

TokenUsageMiddlewareはすべてのAIエージェント呼び出しを自動的にインターセプトして、トークン使用量を記録する。

#### 5.3.2 保持データ

- **context_storage_manager: ContextStorageManager** - コンテキストストレージマネージャー
- **metrics_collector: MetricsCollector** - メトリクスコレクター

#### 5.3.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: WorkflowContext, **kwargs) → Optional[MiddlewareSignal]

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

ErrorHandlingMiddlewareはすべてのノード実行時のエラーを統一的にハンドリングし、エラー分類、リトライ判定、ユーザー通知を実行する。本クラスのエラー分類（transient/configuration/implementation/resource）は、AUTOMATA_CODEX_SPEC.md §10のエラー処理設計を実装レベルに具体化したものである。

#### 5.4.2 保持データ

- **context_storage_manager: ContextStorageManager** - コンテキストストレージマネージャー
- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **metrics_collector: MetricsCollector** - メトリクスコレクター
- **retry_policy: RetryPolicy** - リトライポリシー設定

#### 5.4.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: WorkflowContext, **kwargs) → Optional[MiddlewareSignal]

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
   - context.get_state('retry_count')を呼び出し
   - retry_countがmax_attemptsより小さい場合: リトライ実行

5. **リトライ実行**
   - retry_count += 1
   - context.set_state('retry_count', retry_count)
   - 指数バックオフ計算: delay = base_delay * (2 ** retry_count) + random_jitter
   - delay秒待機
   - Noneを返す（ノード再実行）

6. **リトライ上限到達またはリトライ不可の場合**
   - エラー記録: context_storage_manager.save_error()を呼び出し
   - ユーザー通知: gitlab_client.add_merge_request_note()でエラーコメント投稿
   - メトリクス送信: metrics_collector.send_metric(metric_name='workflow_errors_total', labels={'error_category': category})
   - タスク状態更新: context.set_state('status', 'failed')
   - MiddlewareSignalを生成:
     - action='abort'
     - reason=f'Error: {exception.message}, Retries exhausted'
   - MiddlewareSignal返却

---

### 5.5 InfiniteLoopDetectionMiddleware

#### 5.5.1 概要

InfiniteLoopDetectionMiddlewareは同一ノードへの到達回数を追跡し、設定された上限を超過した場合にワークフローを異常終了させる。`AUTOMATA_CODEX_SPEC.md §8.8.7` の設計を実装したクラス。

#### 5.5.2 保持データ

- **max_node_visits: int** - 各ノードへの最大到達回数（config.yamlのmiddleware.max_node_visits設定値）
- **node_visit_counts: Dict[str, int]** - ノードID → 到達回数のカウンター（タスクごとに初期化）

#### 5.5.3 主要メソッド

##### intercept(phase: str, node: WorkflowNode, context: WorkflowContext, **kwargs) → Optional[MiddlewareSignal]

**処理フロー**:

1. **フェーズ判定**
   - phaseが'before_execution'でない場合: Noneを返す

2. **ノード到達カウンター更新**
   - node_visit_counts[node.node_id]をインクリメント（初回は0から開始）

3. **上限チェック**
   - node_visit_counts[node.node_id] > max_node_visitsの場合:
     - エラーログを記録: f"Infinite loop detected at node {node.node_id}: {count} visits"
     - MiddlewareSignalを生成:
       - action='abort'
       - reason=f'Infinite loop detected: node {node.node_id} has been visited {count} times'
     - MiddlewareSignal返却

4. **通常処理継続**
   - Noneを返す

---

### 5.6 MetricsCollector

#### 5.6.1 概要

MetricsCollectorはOpenTelemetry経由でメトリクスをエクスポートするユーティリティクラス。TokenUsageMiddlewareとErrorHandlingMiddlewareがコンストラクタ引数として受け取り、メトリクス送信に使用する。

#### 5.6.2 保持データ

- **meter_provider: MeterProvider** - OpenTelemetry MeterProvider
- **meter: Meter** - メトリクス収集メーター
- **counters: Dict[str, Counter]** - メトリクス名 → OpenTelemetryカウンターのマッピング

#### 5.6.3 主要メソッド

##### send_metric(metric_name: str, labels: Dict[str, str], value: float) → None

**処理フロー**:

1. **カウンター取得または生成**
   - metric_nameに対応するカウンターがcountersに存在する場合: 取得
   - 存在しない場合: meter.create_counter(metric_name)で生成してcountersに登録

2. **メトリクス送信**
   - counter.add(value, attributes=labels)を呼び出し

3. **エラーハンドリング**
   - 送信失敗時はログ記録のみとし、例外を呼び出し元に伝播させない

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

#### prepare_environments(count: int, environment_name: str, mr_iid: int, node_ids: List[str]) → List[str]

**処理フロー**:

1. **環境名からDockerイメージ取得**
   - environment_name_mapping[environment_name]でイメージ名を取得
   - 環境名が無効またはnullの場合はenvironment_name_mapping['default']を使用

2. **環境ID一覧初期化**
   - environment_ids = []

3. **環境作成ループ（Docker環境の作成とID生成）**
   - node_idsの各要素をループ（countと同じ数）
   - 各反復で:
     - **人間可読な環境ID生成**: `f"codeagent-{environment_name}-mr{mr_iid}-{node_id}"`形式で環境IDを生成
       - 例: `codeagent-python-mr123-code_generation`
       - 構成要素:
         - `codeagent`: システム識別プレフィックス（複数システムが同じDockerホストを使う場合の識別）
         - `{environment_name}`: 環境名（python, miniforge, node, default）
         - `mr{mr_iid}`: MR IID（GitLabのMR番号）
         - `{node_id}`: グラフ定義のノードID（code_generation, bug_fix等）
     - docker_client.containers.create()で取得したイメージ名のDockerコンテナ作成
     - name=環境IDとしてコンテナ名を設定
     - image、network、cpu_limit、memory_limit等を設定
     - コンテナ起動
     - 環境IDをenvironment_idsに追加

4. **環境プール設定**
   - environment_pool = environment_ids
   - selected_environment_name = environment_name

5. **環境ID一覧返却**

**重要**: このメソッドでDocker環境の作成と環境IDの生成を完了する。環境プールには作成済みの環境IDが保存される。環境IDは人間可読な形式で、MR番号とノードIDから構成されるため、デバッグやトラブルシューティングが容易。

**環境ID命名規則の利点**:
- **人間可読性**: `codeagent-python-mr123-code_generation`のように、どのMRのどのノードの環境か一目で分かる
- **一意性**: MR IIDとノードIDの組み合わせにより、複数のOrchestratorインスタンスが異なるMRを処理しても重複しない
- **運用性**: `docker ps`でMR番号やノードIDで検索可能、システムプレフィックスで一括クリーンアップ可能
- **再実行対応**: 再計画やワークフロー再開時に同じ環境IDが生成されるため、環境の再利用やトラブルシューティングが容易

#### get_environment(node_id: str) → str

**処理フロー**:

1. **既存割り当て確認**
   - node_to_env_mapにnode_idが存在するか確認
   - 存在する場合: マッピングから環境IDを取得して返す

2. **環境プール確認**
   - next_env_indexがenvironment_poolのサイズを超えていないか確認
   - 超えている場合: RuntimeErrorをスロー（環境プール不足）

3. **環境割り当て（プールから未使用環境IDを割り当て）**
   - environment_pool[next_env_index]から環境IDを取得
   - node_to_env_map[node_id] = env_id
   - next_env_index += 1

4. **環境ID返却**

**重要**: このメソッドは新規環境を作成せず、prepare_environments()で事前に作成済みの環境プールから未使用の環境IDを割り当てるだけである。

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

#### save_environment_mapping(execution_id: str) → None

**処理フロー**:

1. **データベース接続取得**
   - PostgreSQLのデータベース接続を取得

2. **環境マッピングレコード挿入ループ**
   - node_to_env_mapの各エントリ（node_id, container_id）についてループ
   - 各エントリについて:
     - コンテナ名を生成（f"coding-agent-exec-{execution_id}-{node_id}"）
     - docker_environment_mappingsテーブルにINSERT
     - フィールド: mapping_id（UUID生成）、execution_id、node_id、container_id、container_name、environment_name（selected_environment_name）、status（'stopped'）、created_at、updated_at

3. **コミット**
   - データベースコミット

#### load_environment_mapping(execution_id: str) → None

**処理フロー**:

1. **データベース接続取得**
   - PostgreSQLのデータベース接続を取得

2. **環境マッピング検索**
   - docker_environment_mappingsテーブルからexecution_idに一致するレコードをSELECT

3. **マッピング復元**
   - 各レコードについて:
     - node_to_env_map[node_id] = container_id
     - environment_pool.append(container_id)

4. **環境名復元**
   - レコードからenvironment_nameを取得してselected_environment_nameに設定

#### stop_all_containers(execution_id: str) → None

**処理フロー**:

1. **環境プールループ**
   - environment_poolの各container_idについてループ
   - 各container_idについて:
     - docker_client.containers.get(container_id)でコンテナ取得
     - container.stop()でコンテナ停止

2. **ステータス更新**
   - docker_environment_mappingsテーブルのstatusカラムを'stopped'に更新

#### start_all_containers(execution_id: str) → None

**処理フロー**:

1. **環境プールループ**
   - environment_poolの各container_idについてループ
   - 各container_idについて:
     - docker_client.containers.get(container_id)でコンテナ取得
     - container.start()でコンテナ起動

2. **ステータス更新**
   - docker_environment_mappingsテーブルのstatusカラムを'running'に更新

#### check_containers_exist(execution_id: str) → bool

**処理フロー**:

1. **データベースから環境マッピング取得**
   - docker_environment_mappingsテーブルからexecution_idに一致するレコードをSELECT

2. **各コンテナの存在確認**
   - 各レコードのcontainer_idについて:
     - docker_client.containers.listでコンテナ一覧を取得（停止中を含む、all=True）
     - container_idが一覧に存在するか確認
     - 存在しない場合: Falseを返す

3. **すべて存在する場合**
   - Trueを返す

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
- **selected_environment: str** - 選択された環境名（task_classifierが決定してコンテキストに保存した値）
- **plan_environment_id: str** - PlanEnvSetupExecutorが作成したplan環境のID（コンテキストから取得、planningエージェントが使用）
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
   - plan環境（コンテキストの`plan_environment_id`で識別）のtext_editor MCPを使用してclone済みリポジトリのファイルリストを直接取得
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

### 9.1 MCPClient

#### 9.1.1 概要

MCPClientはstdio経由でMCPサーバーと通信するクライアント。

#### 9.1.2 保持データ

- **server_config: MCPServerConfig** - サーバー設定
- **process: subprocess.Popen** - MCPサーバープロセス
- **stdin: IO** - 標準入力
- **stdout: IO** - 標準出力

#### 9.1.3 主要メソッド

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

### 9.2 EnvironmentAwareMCPClient

#### 9.2.1 概要

EnvironmentAwareMCPClientはノードIDから環境IDを解決してMCP通信を行うクライアント。

#### 9.2.2 保持データ

- **base_client: MCPClient** - ベースMCPクライアント
- **env_manager: ExecutionEnvironmentManager** - 環境マネージャー
- **current_node_id: str** - 現在実行中のノードID

#### 9.2.3 主要メソッド

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

### 9.3 ExecutionEnvironmentMCPWrapper

#### 9.3.1 概要

ExecutionEnvironmentMCPWrapperは環境内MCPサーバーの起動・通信を管理する独立クラス。EnvironmentAwareMCPClientから呼び出され、対象Dockerコンテナ内でMCPサーバープロセスを起動してStdio通信を確立する。詳細設計は`AUTOMATA_CODEX_SPEC.md §9.2.1`を参照。

#### 9.3.2 保持データ

- **env_manager: ExecutionEnvironmentManager** - Docker環境管理クラスへの参照
- **active_connections: Dict[str, MCPClient]** - env_id → 起動済みMCPClientのキャッシュ
- **server_configs: List[MCPServerConfig]** - MCPサーバー設定リスト

#### 9.3.3 主要メソッド

##### start_mcp_server(env_id: str, server_name: str) → MCPClient

**処理フロー**:

1. **キャッシュ確認**
   - active_connections[f"{env_id}:{server_name}"]が存在する場合: 既存接続を返す

2. **対象コンテナ取得**
   - env_manager.get_container(env_id)でDockerコンテナオブジェクトを取得

3. **MCPサーバー設定取得**
   - server_configsからserver_nameに一致する設定を取得

4. **コンテナ内プロセス起動**
   - Docker exec API経由でコンテナ内にMCPサーバープロセスを起動
   - stdin/stdout/stderrをPipeとして接続

5. **MCPClient生成・接続**
   - MCPClientを生成してコンテナプロセスのstdin/stdoutに接続
   - mcp_client.connect()でMCPプロトコル初期化

6. **キャッシュ登録・返却**
   - active_connections[f"{env_id}:{server_name}"] = mcp_client
   - mcp_clientを返す

##### stop_mcp_server(env_id: str, server_name: str) → None

**処理フロー**:

1. **接続確認**
   - active_connectionsに該当エントリが存在しない場合: 処理終了

2. **接続切断**
   - mcp_client.disconnect()を呼び出し

3. **キャッシュ削除**
   - active_connectionsから削除

---

## 10. その他の主要クラス

### 10.1 TodoManagementTool

#### 10.1.1 概要

TodoManagementToolはAgent Frameworkのネイティブツールとして実装されるTodo管理ツール。

**TodoManagerとの関係**: AUTOMATA_CODEX_SPEC.mdで言及される`TodoManager`はAgent Frameworkが提供する組み込みコンポーネントであり、本クラス（`TodoManagementTool`）はそのラッパーとして機能しLLMエージェントがFunctionToolとしてTodo操作を呼び出せるインターフェースを提供する。PostgreSQLへの直接操作はこの`TodoManagementTool`が担う。

#### 10.1.2 保持データ

- **db_connection: DatabaseConnection** - PostgreSQL接続
- **gitlab_client: GitLabClient** - GitLab APIクライアント

#### 10.1.3 主要メソッド

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

### 10.2 IssueToMRConverter

#### 10.2.1 概要

IssueToMRConverterはIssueからMRへの変換を実行する。

#### 10.2.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **llm_client: LLMClient** - LLMクライアント（ブランチ名生成用）
- **config: IssueToMRConfig** - Issue→MR変換設定

#### 10.2.3 主要メソッド

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

### 10.3 ProgressReporter

#### 10.3.1 概要

ProgressReporterはタスクの進捗状況を1タスク1コメント上書き方式でMRに反映するファサードクラス。`ConfigurableAgent`・各`Executor`からイベントを受け取り、`MermaidGraphRenderer`でコメント全体を再構築し、`ProgressCommentManager`に渡して上書き更新を実行する。ノード名の表示はグラフ定義の`label`フィールドを使用する。

#### 10.3.2 保持データ

- **graph_def: dict** - グラフ定義（labelフィールドの参照に使用）
- **mermaid_renderer: MermaidGraphRenderer** - Mermaidフローチャート生成クラス
- **comment_manager: ProgressCommentManager** - 1コメント管理クラス
- **node_states: dict[str, str]** - ノードIDをキーとした現在の状態辞書（pending/running/done/error/skipped）
- **latest_llm_response: str** - 最後に受信したLLM応答の先頭200文字
- **latest_event_summary: str** - 最新イベントのサマリ文字列
- **error_detail: str | None** - エラー詳細テキスト（エラー発生時のみ）

#### 10.3.3 主要メソッド

##### initialize(context: WorkflowContext, mr_iid: int) → None

タスク開始時に呼び出し、全ノードをpendingで初期化したコメントをMRに新規作成する。

**処理フロー**:

1. **ノード状態の初期化**
   - graph_defの全ノードIDに対して`node_states[node_id] = "pending"`を設定する

2. **初期コメント作成**
   - `comment_manager.create_progress_comment(context, mr_iid, node_states)`を呼び出す
   - GitLab Note IDをWorkflowContext `progress_comment_id`に保存する

##### report_progress(context: WorkflowContext, event: str, node_id: str, details: dict) → None

各イベント発生時に呼び出し、コメントを上書き更新する。

**処理フロー**:

1. **ノード状態の更新**
   - `start`: `node_states[node_id] = "running"`
   - `complete`: `node_states[node_id] = "done"`
   - `error`: `node_states[node_id] = "error"`
   - `llm_response`: node_statesは変更しない

2. **サマリ・応答の更新**
   - labelの取得: graph_defのnodesからnode_idに対応するlabelを参照する
   - `start`: `latest_event_summary = "⏳ [{label}] 処理を開始します ― {timestamp}"`
   - `complete`: `latest_event_summary = "✅ [{label}] 完了しました ― {elapsed}秒"`
   - `error`: `latest_event_summary = "❌ [{label}] エラーが発生しました"`、`error_detail`にエラー情報を格納する
   - `llm_response`: `latest_llm_response = details["response"][:200]`

3. **コメント上書き**
   - `comment_manager.update_progress_comment(context, mr_iid, node_states, latest_event_summary, latest_llm_response, error_detail)`を呼び出す

##### finalize(context: WorkflowContext, mr_iid: int, summary: str) → None

タスク全体完了時に呼び出し、全ノードをdoneにして最終サマリを付記したコメントを上書きする。

**処理フロー**:

1. **全ノードをdone化**
   - pendingまたはrunningのまま残っているノードをすべて`"done"`に更新する

2. **最終サマリ設定**
   - `latest_event_summary = "✨ タスク完了 ― {summary}"`

3. **コメント上書き**
   - `comment_manager.update_progress_comment(context, mr_iid, node_states, latest_event_summary, latest_llm_response, error_detail)`を呼び出す

---

### 10.4 MermaidGraphRenderer

#### 10.4.1 概要

MermaidGraphRendererはグラフ定義（graph_def）とノード状態dict（node_states）からMermaidフローチャート文字列を生成するクラス。並列グループ（同一ノードから複数ノードへのファンアウト）を自動検出し、subgraphとして出力する。

#### 10.4.2 保持データ

- **graph_def: dict** - グラフ定義（nodesとedgesを含む）

#### 10.4.3 主要メソッド

##### render(node_states: dict[str, str]) → str

graph_defとnode_statesからMermaidフローチャート文字列を生成して返す。

**処理フロー**:

1. **並列グループ検出**
   - graph_defのedgesを走査し、同一fromノードから2つ以上のtoノードへエッジが出ているグループを並列グループとして検出する
   - fromノードがcondition typeの場合は並列グループとして扱わない（条件分岐のため）

2. **ノード定義行の生成**
   - 各ノードのtypeに応じてMermaid記法でノード定義行を生成する
     - `agent`: `{id}["{label}"]:::{state}`
     - `executor`: `{id}(["{label}"]):::{state}`
     - `condition`: `{id}{"{label"}:::{state}` （`{`と`}`が菱形を表す）
   - 並列グループに属するノードは`subgraph parallel["並列..."]{ direction LR ... }`でまとめる

3. **エッジ定義行の生成**
   - graph_defのedgesをMermaidの`-->`記法で出力する
   - labelが設定されているエッジは`-- {edge_label} -->`記法を使用する
   - 並列グループのファンアウト・ファンインエッジは`&`記法（`A --> B & C`）でまとめて記述する

4. **classDef行の生成**
   - node_statesに含まれる状態種別に応じてclassDef行を出力する
   - 出力するclassDef: pending/running/done/error/skipped

5. **全体的な文字列組み立て**
   - `flowchart TD`ヘッダから始まり、ノード定義行・エッジ定義行・classDef行を順に結合して返す

---

### 10.5 ProgressCommentManager

#### 10.5.1 概要

ProgressCommentManagerはMRへの1コメント作成と上書き更新を管理するクラス。タスク開始時のコメント新規作成（GitLab Note IDをWorkflowContextに保存）と、各イベント時の上書き更新（スロットリング付き）を担当する。

#### 10.5.2 保持データ

- **gitlab_client: GitLabClient** - GitLab APIクライアント
- **mermaid_renderer: MermaidGraphRenderer** - Mermaidフローチャート生成クラス
- **last_update_time: float** - 直前のコメント更新時刻（Unix時刻。スロットリング用）

#### 10.5.3 主要メソッド

##### create_progress_comment(context: WorkflowContext, mr_iid: int, node_states: dict[str, str]) → int

タスク開始時に1度だけ呼び出し、初期コメントをMRに作成してGitLab Note IDを返す。

**処理フロー**:

1. **初期コメント本文の組み立て**
   - `mermaid_renderer.render(node_states)`でMermaidフローチャートを生成する
   - 最新状態行は`🚀 ワークフローを開始します ― {timestamp}`とする
   - 最新LLM応答欄・エラー詳細欄は空欄とする
   - 4セクション構成のコメント本文を組み立てる

2. **GitLabにコメント投稿**
   - `gitlab_client.create_merge_request_note(mr_iid, body)`を呼び出す
   - 返却されたGitLab Note IDを取得する

3. **WorkflowContextへの保存**
   - `context.set_state("progress_comment_id", note_id)`でNote IDを保存する

4. **Note IDを返却**

##### update_progress_comment(context: WorkflowContext, mr_iid: int, node_states: dict[str, str], event_summary: str, llm_response: str, error_detail: str | None) → None

各イベント発生時に呼び出し、既存コメントを上書き更新する。

**処理フロー**:

1. **スロットリング**
   - `time.time() - last_update_time < 1.0`の場合は差分を待機する
   - 待機後、`last_update_time`を現在時刻に更新する

2. **Note IDの取得**
   - `context.get_state("progress_comment_id")`でNote IDを取得する
   - Note IDが未設定の場合はエラーログを出力して処理を中断する

3. **コメント本文の再構築**
   - `mermaid_renderer.render(node_states)`でMermaidフローチャートを生成する
   - event_summary・llm_response・error_detailを各セクションにはめ込んで本文を組み立てる
   - error_detailがNoneの場合はエラー詳細セクション（`<details>`）を省略する

4. **GitLabコメントを上書き**
   - `gitlab_client.update_merge_request_note(mr_iid, note_id, body)`を呼び出す

---

## 11. GuidelineLearningAgent（学習エージェント）

### 11.1 概要

GuidelineLearningAgentはワークフロー最終段階でMRコメントを読み込み、PROJECT_GUIDELINES.mdへの追記が必要かLLMに判断させ、必要な場合はファイルを更新してgit commit & pushまで行う専用エージェント。

**継承元**: `Agent`（Agent Framework標準クラス）

**特徴**:
- グラフ定義ファイルに記載不要（WorkflowFactoryが`_inject_learning_node()`で自動挿入）
- 他のエージェント（ConfigurableAgent）と異なり、`gitlab_client`を例外的に保持する固定実装
- 学習処理が失敗してもワークフローは継続する（エラー耐性設計）

### 11.2 継承関係

```
Agent (Agent Framework標準クラス)
  └── GuidelineLearningAgent（本システム固定実装）
```

### 11.3 保持データ

- **user_config**: ユーザー別学習機能設定（User Config APIから取得）
  - `learning_enabled`: bool（有効/無効）
  - `learning_llm_model`: str（学習判断用モデル、例: "gpt-4o"）
  - `learning_llm_temperature`: float（温度、例: 0.3）
  - `learning_llm_max_tokens`: int（最大トークン数、例: 8000）
  - `learning_exclude_bot_comments`: bool（Botコメント除外、デフォルト: true）
  - `learning_only_after_task_start`: bool（タスク開始後コメントのみ抽出、デフォルト: true）
- **gitlab_client**: GitLabClient（MRコメント取得・投稿・ファイル更新用、例外的に保持）
- **progress_reporter**: ProgressReporter（進捗報告）

### 11.4 invoke_async(context) の処理フロー

1. **有効チェック**
   - `self.user_config.learning_enabled`がfalseの場合、即座に`AgentResponse(success=True)`を返して終了

2. **タスク情報取得**
   - ワークフローコンテキストから`task_mr_iid`、`task_project_id`、`task_start_time`を取得
   - 取得失敗時は警告ログを出力して終了

3. **MRコメント取得・フィルタリング**
   - `gitlab_client.get_mr_comments(project_id, mr_iid)`でコメント一覧を取得
   - `user_config.learning_only_after_task_start=true`の場合: `created_at >= task_start_time`のコメントのみ残す
   - `user_config.learning_exclude_bot_comments=true`の場合: `author.is_bot == false`のコメントのみ残す
   - フィルタ後のコメント数が0の場合は終了

4. **ガイドライン読み込み**
   - `gitlab_client.get_file_content(project_id, "PROJECT_GUIDELINES.md", branch)`でファイルを読み込む
   - ファイルが存在しない場合は以下の初期テンプレートを使用する:
     ```
     ---
     name: PROJECT_GUIDELINES
     about: プロジェクト固有の品質基準とガイドライン
     ---
     # プロジェクトガイドライン（自動育成中）
     ## 1. ドキュメント作成
     ## 2. コード実装
     ## 3. レビュー観点
     ## 4. ワークフロー
     ## 5. その他
     ```

5. **LLM単一呼び出し**
   - Agent標準機能でLLMを呼び出す
   - システムプロンプト: ガイドライン管理者としての役割と判断基準（汎用性・妥当性・新規性・明確性）を指定
   - ユーザープロンプト: タスク情報・コメント一覧・現在のガイドライン全文・出力形式（JSON）を組み合わせたプロンプト
   - LLM設定: `user_config.learning_llm_model`、`user_config.learning_llm_temperature`、`user_config.learning_llm_max_tokens`を使用
   - 期待するJSON応答:
     - `should_update`: 更新が必要か（true/false）
     - `rationale`: 更新判断の理由（日本語）
     - `category`: カテゴリ（documentation/code/review/workflow/general）
     - `updated_guidelines`: 更新後のPROJECT_GUIDELINES.md全文（`should_update=true`のみ）

6. **ガイドライン更新**（`should_update=true`の場合のみ）
   - `gitlab_client.update_file(project_id, "PROJECT_GUIDELINES.md", response.updated_guidelines, commit_message="自動学習: ガイドライン更新", branch)`でファイルをコミット＆プッシュする
   - `gitlab_client.post_mr_comment(project_id, mr_iid, comment)`でMRに更新通知コメントを投稿する

7. **エラーハンドリング**
   - すべての例外をキャッチし、エラーログを出力する
   - ワークフローは継続させるため、例外発生時も`AgentResponse(success=True)`を返す

8. **応答返却**
   - `AgentResponse(success=True)`を返してワークフロー完了

### 11.5 例外的なGitLab API直接操作の許可

GuidelineLearningAgentは唯一`gitlab_client`を通じてPROJECT_GUIDELINES.mdのファイル更新コミットを実行できる。これはシステムの明示的な例外として設計されている。

**例外が許容される条件**:
- 本エージェントは全ワークフロー完了後に実行される（他のgit操作との競合なし）
- 対象ファイル（PROJECT_GUIDELINES.md）は通常の実装ファイルと独立している（影響範囲限定）
- `WorkflowFactory._inject_learning_node()`でのみインスタンス生成され、`gitlab_client`はここでのみ注入される

**制約**:
- 他のエージェント（ConfigurableAgent等）はファイル更新コミット操作を行わない
- 更新先はタスクのブランチに限定される

---

## 12. まとめ

本仕様書では、CODE_AGENT_ORCHESTRATORで実装する主要クラスの詳細設計を記載した。

**記載した主要クラス**:
- ConfigurableAgent: 汎用エージェントクラス
- Factory群: WorkflowFactory、WorkflowBuilder、ExecutorFactory、AgentFactory、MCPClientFactory、TaskStrategyFactory
- Strategy群: ITaskStrategy、IssueToMRConversionStrategy、IssueOnlyStrategy、MergeRequestStrategy
- Executor群: BaseExecutor、UserResolverExecutor、ContentTransferExecutor、PlanEnvSetupExecutor、ExecEnvSetupExecutor、BranchMergeExecutor
- Custom Provider群: PostgreSqlChatHistoryProvider、PlanningContextProvider、ToolResultContextProvider、TaskInheritanceContextProvider、ContextStorageManager
- Middleware実装: CommentCheckMiddleware、TokenUsageMiddleware、ErrorHandlingMiddleware、InfiniteLoopDetectionMiddleware、MetricsCollector
- ExecutionEnvironmentManager: Docker環境管理
- MCPClient関連: MCPClient、EnvironmentAwareMCPClient、ExecutionEnvironmentMCPWrapper
- その他: TodoManagementTool、IssueToMRConverter、ProgressReporter、MermaidGraphRenderer、ProgressCommentManager

**実装時の注意点**:
- すべてのメソッドは非同期（async/await）で実装する
- エラーハンドリングは適切に実施する
- ログ記録は構造化ログで実施する
- テストは単体テスト・統合テストを両方実施する

実装時は本仕様書を参照し、Agent FrameworkのProcess Framework（Workflow/Executor）の標準機能を活用して実装する。コード例を含まず日本語で記述された処理フローに基づいて実装する。
