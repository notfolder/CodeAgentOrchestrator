# データベーススキーマ仕様書

本ドキュメントは、CODE_AGENT_ORCHESTRATOR_SPEC.mdで定義されたシステムで使用するPostgreSQLデータベースの完全なスキーマ定義を記載する。

## 1. 概要

### 1.1 データベース構成

データベース名: `coding_agent`

**主要テーブルグループ**:
- ユーザー管理テーブル群（users, user_configs, user_workflow_settings）
- ワークフロー定義テーブル群（workflow_definitions）
- タスク管理テーブル群（tasks）
- ワークフロー実行管理テーブル群（workflow_execution_states, docker_environment_mappings）
- コンテキストストレージテーブル群（context_messages, context_planning_history, context_metadata, context_tool_results_metadata）
- Todo管理テーブル（todos）
- メトリクステーブル（token_usage）

---

## 2. ユーザー管理テーブル群

### 2.1 usersテーブル

ユーザー基本情報を管理する。メールアドレスをプライマリキーとして使用する。

**テーブル名**: `users`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| email | TEXT | PRIMARY KEY | ユーザーのメールアドレス（一意識別子） |
| username | TEXT | NOT NULL | ユーザー表示名 |
| is_active | BOOLEAN | NOT NULL DEFAULT true | アカウント有効状態 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | アカウント作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**インデックス**:
- `PRIMARY KEY (email)` - メールアドレスでの高速検索
- `idx_users_is_active` ON (is_active) - 有効ユーザーフィルタリング用

**備考**:
- メールアドレスは大文字小文字を区別せず、すべて小文字に正規化して保存する
- is_activeがfalseの場合、システムへのアクセスを拒否する

---

### 2.2 user_configsテーブル

ユーザーごとのLLM設定（APIキー、モデル、プロバイダ等）を管理する。

**テーブル名**: `user_configs`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| user_email | TEXT | PRIMARY KEY | ユーザーメールアドレス（外部キー） |
| llm_provider | TEXT | NOT NULL DEFAULT 'openai' | LLMプロバイダ（openai/ollama/lmstudio） |
| api_key_encrypted | TEXT | | APIキー（AES-256-GCM暗号化済み） |
| model_name | TEXT | NOT NULL DEFAULT 'gpt-4o' | 使用モデル名 |
| temperature | REAL | NOT NULL DEFAULT 0.2 | LLM温度パラメータ |
| max_tokens | INTEGER | NOT NULL DEFAULT 4096 | 最大トークン数 |
| top_p | REAL | NOT NULL DEFAULT 1.0 | Top-pサンプリングパラメータ |
| frequency_penalty | REAL | NOT NULL DEFAULT 0.0 | 頻度ペナルティ |
| presence_penalty | REAL | NOT NULL DEFAULT 0.0 | 存在ペナルティ |
| base_url | TEXT | | カスタムエンドポイントURL（Ollama/LM Studio用） |
| timeout | INTEGER | NOT NULL DEFAULT 120 | API呼び出しタイムアウト（秒） |
| context_compression_enabled | BOOLEAN | NOT NULL DEFAULT true | コンテキスト圧縮を有効化するか |
| token_threshold | INTEGER | | 圧縮を開始するトークン数の閾値（NULL=モデル推奨値を使用） |
| keep_recent_messages | INTEGER | NOT NULL DEFAULT 10 | 最新から保持するメッセージ数 |
| min_to_compress | INTEGER | NOT NULL DEFAULT 5 | 圧縮する最小メッセージ数 |
| min_compression_ratio | REAL | NOT NULL DEFAULT 0.8 | 圧縮率の最小値（0.8=20%削減） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 設定作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**外部キー制約**:
- `FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE` - ユーザー削除時に設定も削除

**インデックス**:
- `PRIMARY KEY (user_email)`
- `idx_user_configs_provider` ON (llm_provider) - プロバイダ別統計取得用

**備考**:
- api_key_encryptedは環境変数ENCRYPTION_KEYで暗号化される
- llm_providerの有効値: 'openai', 'ollama', 'lmstudio'
- base_urlはollama/lmstudioの場合のみ必須、openaiの場合はNULL許容
- temperatureは0.0〜2.0の範囲、max_tokensは1〜32000の範囲
- context_compression_enabled=falseの場合、ユーザーのタスクでコンテキスト圧縮処理をスキップ
- token_thresholdがNULLの場合、model_nameに基づくモデル推奨値を自動適用（例: gpt-4o→90,000、gpt-4→5,600）
- keep_recent_messages、min_to_compress、min_compression_ratioはコンテキスト圧縮の詳細パラメータでユーザーがカスタマイズ可能
- **圧縮設定の検証範囲**: token_threshold (1,000〜150,000)、keep_recent_messages (1〜50)、min_to_compress (1〜20)、min_compression_ratio (0.5〜0.95)
- keep_recent_messagesは1〜50の範囲に制限（検証時）
- min_to_compressは1〜20の範囲に制限（検証時）
- min_compression_ratioは0.5〜0.95の範囲に制限（検証時）

**プロンプトカスタマイズについて**:
ユーザーがプロンプトをカスタマイズしたい場合は、システムプリセット（standard_mr_processing等）をベースにユーザー独自のワークフロー定義を作成し、その`prompt_definition`（JSONB）内のプロンプトテキストを変更する。エージェント別の個別上書きテーブルは不要。

---

### 2.4 user_workflow_settingsテーブル

ユーザーが選択中のワークフロー定義を管理する。

**テーブル名**: `user_workflow_settings`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| user_email | TEXT | PRIMARY KEY | ユーザーメールアドレス（外部キー） |
| workflow_definition_id | INTEGER | NOT NULL | 選択中のワークフロー定義ID（外部キー） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 設定作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**外部キー制約**:
- `FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE`
- `FOREIGN KEY (workflow_definition_id) REFERENCES workflow_definitions(id) ON DELETE SET DEFAULT` - ワークフロー定義削除時はシステムデフォルトに戻す

**インデックス**:
- `PRIMARY KEY (user_email)`
- `idx_user_workflow_settings_definition` ON (workflow_definition_id) - ワークフロー定義使用状況確認用

**備考**:
- ユーザーがワークフロー定義を選択していない場合、システムデフォルト（standard_mr_processing）を使用する
- workflow_definition_idが削除された場合、システムデフォルトIDに自動更新する

---

## 3. ワークフロー定義テーブル

### 3.1 workflow_definitionsテーブル

グラフ定義・エージェント定義・プロンプト定義の3つをJSONBカラムで1セットとして管理する。

**テーブル名**: `workflow_definitions`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | ワークフロー定義ID |
| name | TEXT | NOT NULL UNIQUE | ワークフロー定義名（例: standard_mr_processing） |
| display_name | TEXT | NOT NULL | 表示用ワークフロー名 |
| description | TEXT | | ワークフロー説明 |
| is_preset | BOOLEAN | NOT NULL DEFAULT false | システムプリセットフラグ |
| created_by | TEXT | | 作成者メールアドレス（外部キー、プリセットの場合はNULL） |
| graph_definition | JSONB | NOT NULL | グラフ定義（ノード・エッジ・条件式） |
| agent_definition | JSONB | NOT NULL | エージェント定義（ロール・ツール・入出力キー） |
| prompt_definition | JSONB | NOT NULL | プロンプト定義（システムプロンプト・LLMパラメータ） |
| version | TEXT | NOT NULL DEFAULT '1.0.0' | 定義バージョン |
| is_active | BOOLEAN | NOT NULL DEFAULT true | 有効状態 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**外部キー制約**:
- `FOREIGN KEY (created_by) REFERENCES users(email) ON DELETE SET NULL` - 作成者削除時はNULLに設定

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_workflow_definitions_name` ON (name) - 名前検索用
- `idx_workflow_definitions_is_preset` ON (is_preset) - プリセット一覧取得用
- `idx_workflow_definitions_created_by` ON (created_by) - ユーザー別定義一覧取得用
- `idx_workflow_definitions_is_active` ON (is_active) - 有効定義フィルタリング用

**JSONB構造**:

#### graph_definition (JSONB)
```
{
  "version": "1.0.0",
  "name": "standard_mr_processing",
  "entry_node": "user_resolver",
  "nodes": [
    {
      "id": "user_resolver",
      "type": "executor",
      "executor_type": "UserResolverExecutor",
      "metadata": {}
    },
    {
      "id": "task_classifier",
      "type": "agent",
      "agent_definition_id": "task_classifier",
      "metadata": {}
    }
  ],
  "edges": [
    {
      "from": "user_resolver",
      "to": "task_classifier",
      "condition": null
    }
  ]
}
```

#### agent_definition (JSONB)
```
{
  "version": "1.0.0",
  "agents": [
    {
      "id": "task_classifier",
      "role": "planning",
      "input_keys": ["mr_description", "mr_comments"],
      "output_keys": ["task_type", "task_category"],
      "tools": [],
      "requires_environment": false,
      "prompt_id": "task_classifier_prompt"
    }
  ]
}
```

#### prompt_definition (JSONB)
```
{
  "version": "1.0.0",
  "prompts": [
    {
      "prompt_id": "task_classifier_prompt",
      "role": "planning",
      "content": "You are a task classifier...",
      "model_override": null,
      "temperature_override": null
    }
  ]
}
```

**備考**:
- is_preset=trueの定義は更新・削除をAPIで拒否する
- created_byがNULLの場合はシステムプリセット
- graph_definition、agent_definition、prompt_definitionのバージョンは独立して管理される
- JSONBインデックス作成（検索性能向上）: `CREATE INDEX idx_workflow_graph_def ON workflow_definitions USING gin (graph_definition);`

---

## 4. タスク管理テーブル

### 4.1 tasksテーブル

実行中・完了済みタスクの状態を管理する。

**テーブル名**: `tasks`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| uuid | TEXT | PRIMARY KEY | タスクUUID（一意識別子） |
| task_type | TEXT | NOT NULL | タスク種別（issue_to_mr/mr_processing） |
| task_identifier | TEXT | NOT NULL | GitLab Issue/MR識別子（例: project_id/123） |
| repository | TEXT | NOT NULL | リポジトリ名（例: owner/repo） |
| user_email | TEXT | NOT NULL | 処理ユーザーのメールアドレス（外部キー） |
| status | TEXT | NOT NULL DEFAULT 'running' | タスク状態（running/completed/paused/failed） |
| workflow_definition_id | INTEGER | | 使用したワークフロー定義ID（外部キー） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | タスク作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |
| completed_at | TIMESTAMP | | 完了日時 |
| total_messages | INTEGER | NOT NULL DEFAULT 0 | 総メッセージ数 |
| total_summaries | INTEGER | NOT NULL DEFAULT 0 | 総要約数 |
| total_tool_calls | INTEGER | NOT NULL DEFAULT 0 | 総ツール呼び出し数 |
| final_token_count | INTEGER | | 最終トークン数 |
| error_message | TEXT | | エラーメッセージ |
| metadata | JSONB | DEFAULT '{}' | タスクメタデータ（シリアル化されたセッション、継承データ等） |
| assigned_branches | JSONB | | 並列コード生成時のブランチ割り当て（例: {"fast": "feature/login-fast", "standard": "feature/login-standard", "creative": "feature/login-creative"}） |
| selected_branch | VARCHAR(255) | | レビュー後に選択されたブランチ名 |

**外部キー制約**:
- `FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE`
- `FOREIGN KEY (workflow_definition_id) REFERENCES workflow_definitions(id) ON DELETE SET NULL`

**インデックス**:
- `PRIMARY KEY (uuid)`
- `idx_tasks_status` ON (status) - 状態別タスク一覧取得用
- `idx_tasks_user_email` ON (user_email) - ユーザー別タスク一覧取得用
- `idx_tasks_repository` ON (repository) - リポジトリ別タスク一覧取得用
- `idx_tasks_task_identifier` ON (task_identifier) - Issue/MR別タスク検索用
- `idx_tasks_created_at` ON (created_at DESC) - 最新タスク取得用
- `idx_tasks_completed_at` ON (completed_at DESC) WHERE completed_at IS NOT NULL - 完了タスククリーンアップ用

**JSONB metadata構造例**:
```
{
  "serialized_session": {...},
  "gitlab_project_id": 12345,
  "gitlab_mr_iid": 67,
  "environment_ids": ["env-uuid-1", "env-uuid-2"],
  "retry_count": 0,
  "last_checkpoint": "code_generation",
  "inheritance_data": {
    "final_summary": "タスクの最終要約テキスト",
    "planning_history": [
      {
        "phase": "planning",
        "node_id": "code_planning",
        "plan": {"todos": [...], "actions": [...]},
        "created_at": "2026-03-08T10:00:00Z"
      }
    ],
    "implementation_patterns": [
      {
        "pattern_type": "file_structure",
        "description": "src/配下にcontrollers, models, viewsディレクトリを作成",
        "success": true
      }
    ],
    "key_decisions": [
      "FastAPIでREST API実装",
      "PostgreSQL 15使用"
    ]
  },
  "disable_inheritance": false
}
```

**JSONB assigned_branches構造例**（multi_codegen_mr_processingワークフロー使用時）:
```
{
  "fast": "feature/login-fast",
  "standard": "feature/login-standard",
  "creative": "feature/login-creative"
}
```

**備考**:
- statusの有効値: 'running', 'completed', 'paused', 'failed'
- task_typeの有効値: 'issue_to_mr', 'mr_processing'
- task_identifierフォーマット: '{project_id}/{resource_type}/{iid}' （例: '12345/issues/123', '12345/merge_requests/456'）
- metadataにはAgent FrameworkのSession情報、継承データ（inheritance_data）、設定（disable_inheritance等）を保存
- metadata["inheritance_data"]には過去タスクから継承するデータ（final_summary、planning_history、implementation_patterns、key_decisions）を格納
- metadata["disable_inheritance"]=trueを設定すると、TaskInheritanceContextProviderが過去タスク検索をスキップ
- assigned_branc hes は並列コード生成時の各戦略（fast/standard/creative）のブランチ名を記録
- selected_branchはレビュー完了後に選択されたブランチ名を記録
- completed_atはstatus='completed'の場合のみ設定される

---

## 4.5 ワークフロー実行管理テーブル群

### 4.5.1 workflow_execution_statesテーブル

ワークフロー実行の状態を記録し、停止・再開処理時に使用する。

**テーブル名**: `workflow_execution_states`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| execution_id | UUID | PRIMARY KEY | ワークフロー実行の一意識別子 |
| task_uuid | TEXT | NOT NULL | tasksテーブルへの外部キー |
| workflow_definition_id | INTEGER | | 使用中のワークフロー定義ID（外部キー） |
| current_node_id | TEXT | NOT NULL | 実行中または次に実行するノードID |
| completed_nodes | JSONB | NOT NULL DEFAULT '[]' | 完了したノードIDの配列 |
| workflow_status | TEXT | NOT NULL DEFAULT 'running' | 実行状態（running/suspended/completed/failed） |
| suspended_at | TIMESTAMP | | 停止日時 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | ワークフロー開始日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE` - タスク削除時にワークフロー状態も削除
- `FOREIGN KEY (workflow_definition_id) REFERENCES workflow_definitions(id) ON DELETE SET NULL`

**インデックス**:
- `PRIMARY KEY (execution_id)`
- `idx_wf_exec_states_task_uuid` ON (task_uuid) - タスク別実行状態検索用
- `idx_wf_exec_states_status` ON (workflow_status) - 状態別検索用（特にsuspended検索）
- `idx_wf_exec_states_suspended_at` ON (suspended_at DESC) WHERE suspended_at IS NOT NULL - 停止タスクの古い順検索用

**JSONB completed_nodes構造例**:
```json
["user_resolver", "task_classifier", "content_transfer", "environment_setup"]
```

**備考**:
- workflow_statusの有効値: 'running', 'suspended', 'completed', 'failed'
- suspended_atはworkflow_status='suspended'の場合のみ設定される
- completed_nodesはワークフローの進捗を追跡し、再開時にスキップするノードを識別する

---

### 4.5.2 docker_environment_mappingsテーブル

Docker環境とノードの対応関係を永続化し、再開時にコンテナを再利用する。

**テーブル名**: `docker_environment_mappings`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| mapping_id | UUID | PRIMARY KEY | マッピングの一意識別子 |
| execution_id | UUID | NOT NULL | workflow_execution_statesへの外部キー |
| node_id | TEXT | NOT NULL | ワークフローノードID |
| container_id | TEXT | NOT NULL | DockerコンテナID |
| container_name | TEXT | NOT NULL | Dockerコンテナ名 |
| environment_name | TEXT | NOT NULL | 環境名（python/miniforge/node/default） |
| status | TEXT | NOT NULL DEFAULT 'running' | コンテナ状態（running/stopped） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**外部キー制約**:
- `FOREIGN KEY (execution_id) REFERENCES workflow_execution_states(execution_id) ON DELETE CASCADE` - ワークフロー実行削除時にマッピングも削除

**ユニーク制約**:
- `UNIQUE (execution_id, node_id)` - 1実行・1ノードにつき1つのコンテナマッピング

**インデックス**:
- `PRIMARY KEY (mapping_id)`
- `idx_docker_env_map_exec_id` ON (execution_id) - 実行ID別マッピング検索用
- `idx_docker_env_map_container_id` ON (container_id) - コンテナID別検索用
- `idx_docker_env_map_status` ON (status) - 状態別検索用

**container_name命名規則**:
```
coding-agent-exec-{execution_id}-{node_id}
```

**備考**:
- statusの有効値: 'running', 'stopped'
- environment_nameの有効値: 'python', 'miniforge', 'node', 'default'
- container_nameは一意性を保証するため実行IDとノードIDを含む
- 再開時にはcontainer_idを使用してDockerコンテナを特定し、起動する

---

## 5. コンテキストストレージテーブル群

### 5.1 context_messagesテーブル

LLM会話履歴を時系列順に保存する。PostgreSqlChatHistoryProviderが使用する。

**テーブル名**: `context_messages`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | メッセージID |
| task_uuid | TEXT | NOT NULL | タスクUUID（外部キー） |
| seq | INTEGER | NOT NULL | シーケンス番号（0から開始） |
| role | TEXT | NOT NULL | ロール（system/user/assistant/tool） |
| content | TEXT | NOT NULL | メッセージ内容 |
| tool_call_id | TEXT | | ツール呼び出しID（roleがtoolの場合） |
| tool_name | TEXT | | ツール名（roleがtoolの場合） |
| tokens | INTEGER | | トークン数 |
| is_compressed_summary | BOOLEAN | DEFAULT false | この行が圧縮要約かどうか |
| compressed_range | JSONB | | 圧縮されたメッセージ範囲（例: {"start_seq": 10, "end_seq": 50}） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |

**ユニーク制約**:
- `UNIQUE (task_uuid, seq)` - タスクごとにシーケンス番号は一意

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_context_messages_task_seq` ON (task_uuid, seq) - 会話履歴取得用（時系列順）
- `idx_context_messages_role` ON (role) - ロール別メッセージ統計用

**備考**:
- roleの有効値: 'system', 'user', 'assistant', 'tool'
- seqは0から開始し、メッセージ追加ごとに1ずつ増加
- tokensは各メッセージのトークン数を記録（コンテキスト圧縮判定に使用）
- tool_call_idはLLMのfunction calling結果を識別するために使用
- is_compressed_summaryがtrueの場合、このメッセージは複数の古いメッセージを要約したもの
- compressed_rangeは圧縮されたメッセージのseq範囲を記録（圧縮履歴追跡用）
- 圧縮要約メッセージのroleは"user"とし、contentの先頭に"[Summary of previous conversation (messages X-Y)]: "を付ける

---

### 5.2 message_compressionsテーブル

メッセージ圧縮の実行履歴を記録する。ContextCompressionServiceが使用する。

**テーブル名**: `message_compressions`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | 圧縮ID |
| task_uuid | TEXT | NOT NULL | タスクUUID（外部キー） |
| start_seq | INTEGER | NOT NULL | 圧縮開始seq |
| end_seq | INTEGER | NOT NULL | 圧縮終了seq |
| summary_seq | INTEGER | NOT NULL | 要約メッセージのseq |
| original_token_count | INTEGER | NOT NULL | 圧縮前トークン数 |
| compressed_token_count | INTEGER | NOT NULL | 圧縮後トークン数 |
| compression_ratio | FLOAT | | 圧縮率（compressed/original） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 圧縮実行日時 |

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_message_compressions_task` ON (task_uuid, created_at DESC) - タスク別圧縮履歴取得用

**備考**:
- 圧縮処理の実行履歴を記録し、圧縮効果の監視やデバッグに使用
- compression_ratioは圧縮率（0.0～1.0）で、値が小さいほど圧縮効果が高い
- summary_seqは圧縮後に作成された要約メッセージのseq番号
- start_seq～end_seqの範囲のメッセージがsummary_seqの1メッセージに置き換えられたことを示す

---

### 5.3 context_planning_historyテーブル

プランニング履歴を保存する。PlanningContextProviderが使用する。

**テーブル名**: `context_planning_history`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | 履歴ID |
| task_uuid | TEXT | NOT NULL | タスクUUID（外部キー） |
| phase | TEXT | NOT NULL | フェーズ（planning/execution/reflection） |
| node_id | TEXT | NOT NULL | 実行ノードID |
| plan | JSONB | | 計画データ（Todoリスト、アクション一覧等） |
| action_id | TEXT | | アクションID（executionフェーズの場合） |
| result | TEXT | | 実行結果またはリフレクション結果 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_context_planning_task_phase` ON (task_uuid, phase, created_at) - フェーズ別履歴取得用
- `idx_context_planning_node` ON (node_id) - ノード別統計用

**JSONB plan構造例**:
```
{
  "todos": [
    {"id": 1, "title": "データベーススキーマ設計", "status": "completed"},
    {"id": 2, "title": "API実装", "status": "in-progress"}
  ],
  "actions": [
    {"id": "act-1", "type": "file_create", "path": "schema.sql"}
  ]
}
```

**備考**:
- phaseの有効値: 'planning', 'execution', 'reflection'
- planはJSON形式で柔軟に構造を保存可能
- action_idはexecutionフェーズの場合のみ設定される
- resultはテキスト形式で実行結果またはリフレクション結果を保存

---

### 5.4 context_metadataテーブル

タスクメタデータを保存する。各Providerが共通で使用する。

**テーブル名**: `context_metadata`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| task_uuid | TEXT | PRIMARY KEY | タスクUUID（外部キー） |
| task_type | TEXT | NOT NULL | タスク種別 |
| task_identifier | TEXT | NOT NULL | GitLab Issue/MR識別子 |
| repository | TEXT | NOT NULL | リポジトリ名 |
| user_email | TEXT | NOT NULL | ユーザーメールアドレス（外部キー） |
| workflow_name | TEXT | | 使用ワークフロー名 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`
- `FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE`

**インデックス**:
- `PRIMARY KEY (task_uuid)`
- `idx_context_metadata_user` ON (user_email) - ユーザー別コンテキスト検索用
- `idx_context_metadata_repository` ON (repository) - リポジトリ別コンテキスト検索用

**備考**:
- tasksテーブルと情報が重複するが、Providerが効率的にメタデータを取得するために独立して管理
- workflow_nameは実行時に使用したワークフロー定義名を記録

---

### 5.5 context_tool_results_metadataテーブル

ツール実行結果のメタデータを保存する。ToolResultContextProviderが使用する。実際の結果はファイルストレージに保存し、ここではメタデータのみを管理する。

**テーブル名**: `context_tool_results_metadata`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | メタデータID |
| task_uuid | TEXT | NOT NULL | タスクUUID（外部キー） |
| tool_name | TEXT | NOT NULL | ツール名（例: text_editor, command_executor） |
| tool_command | TEXT | | ツールコマンド（例: view, execute_command） |
| file_path | TEXT | NOT NULL | ファイルストレージパス |
| file_size | INTEGER | NOT NULL | ファイルサイズ（バイト） |
| success | BOOLEAN | NOT NULL DEFAULT true | 実行成功フラグ |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_context_tool_results_task_tool` ON (task_uuid, tool_name, created_at) - ツール別結果取得用
- `idx_context_tool_results_created` ON (created_at DESC) - 最新結果取得用

**備考**:
- file_pathは`tool_results/{task_uuid}/{timestamp}_{tool_name}.json`形式
- file_sizeはファイルストレージクリーンアップの判定に使用
- successフラグでツール実行の成否を記録
- tool_commandは実際に実行されたコマンド名を記録（例: view_file, execute_command）

---

## 6. Todo管理テーブル

### 6.1 todosテーブル

タスクごとのTodoリストを管理する。階層構造をサポートする。

**テーブル名**: `todos`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | TodoID |
| task_uuid | TEXT | NOT NULL | タスクUUID（外部キー） |
| parent_todo_id | INTEGER | | 親TodoID（外部キー、階層構造用） |
| title | TEXT | NOT NULL | Todoタイトル |
| description | TEXT | | Todo詳細説明 |
| status | TEXT | NOT NULL DEFAULT 'not-started' | 状態（not-started/in-progress/completed/failed） |
| order_index | INTEGER | NOT NULL | 表示順序（同一親内での順序） |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最終更新日時 |
| completed_at | TIMESTAMP | | 完了日時 |

**外部キー制約**:
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`
- `FOREIGN KEY (parent_todo_id) REFERENCES todos(id) ON DELETE CASCADE` - 親Todo削除時に子Todoも削除

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_todos_task_uuid` ON (task_uuid, order_index) - タスク別Todoリスト取得用（順序付き）
- `idx_todos_parent` ON (parent_todo_id) - 子Todo取得用
- `idx_todos_status` ON (status) - 状態別Todo統計用

**備考**:
- statusの有効値: 'not-started', 'in-progress', 'completed', 'failed'
- parent_todo_idがNULLの場合はルートレベルのTodo
- parent_todo_idが設定されている場合はサブTodo（階層構造）
- order_indexは同一parent_todo_id内で一意である必要はないが、表示順序を決定する
- 状態遷移: not-started → in-progress → completed/failed

---

## 7. メトリクステーブル

### 7.1 token_usageテーブル

ユーザー別・タスク別・ノード別のトークン使用量を記録する。TokenUsageMiddlewareが使用する。

**テーブル名**: `token_usage`

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| id | SERIAL | PRIMARY KEY | レコードID |
| user_email | TEXT | NOT NULL | ユーザーメールアドレス（外部キー） |
| task_uuid | TEXT | NOT NULL | タスクUUID（外部キー） |
| node_id | TEXT | NOT NULL | ワークフローノードID |
| model | TEXT | NOT NULL | 使用モデル名（例: gpt-4o） |
| prompt_tokens | INTEGER | NOT NULL | 入力プロンプトのトークン数 |
| completion_tokens | INTEGER | NOT NULL | 生成出力のトークン数 |
| total_tokens | INTEGER | NOT NULL | 合計トークン数 |
| created_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 記録日時 |

**外部キー制約**:
- `FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE`
- `FOREIGN KEY (task_uuid) REFERENCES tasks(uuid) ON DELETE CASCADE`

**インデックス**:
- `PRIMARY KEY (id)`
- `idx_token_usage_user_date` ON (user_email, created_at DESC) - ユーザー別使用量集計用
- `idx_token_usage_task` ON (task_uuid) - タスク別使用量集計用
- `idx_token_usage_model` ON (model) - モデル別統計用
- `idx_token_usage_node` ON (node_id) - ノード別統計用
- `idx_token_usage_created` ON (created_at DESC) - 時系列統計用

**備考**:
- prompt_tokens + completion_tokens = total_tokensの関係が常に成立
- node_idはワークフロー定義のノードIDと対応
- modelはLLMプロバイダのモデル名（例: gpt-4o, gpt-3.5-turbo, claude-3-sonnet）
- コスト計算はアプリケーション層で実施（モデル別料金表を使用）

---

## 8. データ保持期限とクリーンアップ

### 8.1 自動クリーンアップ対象テーブル

以下のテーブルは定期的にクリーンアップを実施する。

**tasksテーブル**:
- 対象: status='completed' かつ completed_at が設定期限（デフォルト30日）より古いレコード
- CASCADE削除により以下のテーブルも自動削除される:
  - context_messages
  - context_planning_history
  - context_metadata
  - context_tool_results_metadata
  - todos
  - token_usage

**ファイルストレージ**:
- 対象: tool_results/{task_uuid}/ディレクトリで、対応するtasksレコードが削除されたもの
- クリーンアップタイミング: tasksテーブルのクリーンアップ後

**保持期限設定**:
- 環境変数 `TASK_CLEANUP_DAYS` で設定（デフォルト: 30日）
- アーカイブ用途の場合は保持期限を延長可能（90日、180日等）

### 8.2 クリーンアップ実行方法

**スケジュール実行**:
- cron: 毎日午前2時に実行
- 実行SQL: `DELETE FROM tasks WHERE status = 'completed' AND completed_at < NOW() - INTERVAL '30 days';`
- ファイルストレージクリーンアップ: Pythonスクリプトで実行

---

## 9. データベース初期化SQL

データベース初期化時に以下の順序でテーブルを作成する。

**作成順序**:
1. usersテーブル
2. user_configsテーブル
3. workflow_definitionsテーブル
4. user_workflow_settingsテーブル
5. tasksテーブル
7. context_messagesテーブル
8. context_planning_historyテーブル
9. context_metadataテーブル
10. context_tool_results_metadataテーブル
11. todosテーブル
12. token_usageテーブル

**システムプリセットの初期データ**:
- workflow_definitionsテーブルに以下の2プリセットを登録:
  - standard_mr_processing（is_preset=true, created_by=NULL）
  - multi_codegen_mr_processing（is_preset=true, created_by=NULL）

**デフォルトユーザーの作成**:
- 開発・テスト環境用にsystem@example.comユーザーを作成
- user_configsにデフォルトLLM設定を登録

---

## 10. データベース設定

### 10.1 接続設定

**接続文字列**: `postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/coding_agent`

**コネクションプール設定**:
- pool_size: 10（同時接続数）
- max_overflow: 20（プール超過時の最大追加接続数）
- pool_timeout: 30秒（接続取得タイムアウト）
- pool_recycle: 3600秒（接続再利用期限）

### 10.2 パフォーマンスチューニング

**shared_buffers**: 256MB以上（メモリの25%推奨）
**work_mem**: 32MB以上（ソート・ハッシュ操作用）
**maintenance_work_mem**: 128MB以上（VACUUM用）
**effective_cache_size**: 1GB以上（クエリプランナー用）

**VACUUM設定**:
- autovacuum: on
- autovacuum_naptime: 1min
- autovacuum_vacuum_threshold: 50
- autovacuum_analyze_threshold: 50

### 10.3 バックアップ設定

**バックアップ方式**: pg_dump
**スケジュール**: 毎日午前2時
**保持期限**: 30日
**バックアップ先**: backups/database/ディレクトリ

---

## 11. セキュリティ設定

### 11.1 暗号化

**api_key_encrypted列の暗号化**:
- アルゴリズム: AES-256-GCM
- 暗号化キー: 環境変数 ENCRYPTION_KEY（32バイト）
- 暗号化・復号化: Pythonのcryptographyライブラリで実施

### 11.2 アクセス制御

**データベースユーザー**:
- agent: 通常操作用（SELECT, INSERT, UPDATE, DELETE権限）
- admin: 管理操作用（ALL権限）

**接続制限**:
- Docker内部ネットワークからのみ接続許可
- 外部からの直接接続は拒否

---

## 12. マイグレーション管理

### 12.1 スキーマバージョン管理

**schema_versionsテーブル**:

| カラム名 | 型 | 制約 | 説明 |
|---------|-----|------|------|
| version | TEXT | PRIMARY KEY | スキーマバージョン（例: 1.0.0） |
| applied_at | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP | 適用日時 |
| description | TEXT | | マイグレーション説明 |

**マイグレーション実行順序**:
1. schema_versionsテーブルで現在のバージョンを確認
2. 未適用のマイグレーションSQLを順次実行
3. 実行完了後、schema_versionsテーブルに新バージョンを記録

### 12.2 マイグレーションファイル命名規則

`migrations/{version}_{description}.sql`形式
- 例: `migrations/1.0.0_initial_schema.sql`
- 例: `migrations/1.1.0_add_token_usage_index.sql`

---

## 13. まとめ

本仕様書では、CODE_AGENT_ORCHESTRATORで使用する全データベーステーブルの完全な定義を記載した。

**主要なポイント**:
- ユーザー管理: メールアドレスベースの設定管理とAPIキー暗号化
- ワークフロー定義: JSONB形式での柔軟な定義管理
- コンテキストストレージ: PostgreSQL + ファイルストレージのハイブリッド設計
- メトリクス: トークン使用量の詳細記録
- 外部キー制約: CASCADE削除による整合性保証
- インデックス: 検索性能の最適化
- クリーンアップ: 自動的な古いデータ削除

実装時は本仕様書に基づいてinit.sqlファイルを作成し、データベース初期化とマイグレーション管理を実施する。
