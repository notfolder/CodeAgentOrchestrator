# エージェント定義ファイル 詳細設計書

## 1. 概要

エージェント定義ファイルはグラフ内の各エージェントノードの設定（ロール・ステップ間データキー・利用ツール・実行環境要否）をJSON形式で定義する。`workflow_definitions`テーブルの`agent_definition`カラム（JSONB型）に保存され、グラフ定義・プロンプト定義と1セットで管理される。

`AgentFactory`がこのJSONをパースし、各ノードの`ConfigurableAgent`インスタンス生成時に`AgentNodeConfig`として渡す。

## 2. DBへの保存形式

`workflow_definitions`テーブルの`agent_definition`カラムにJSONBとして保存する。

| カラム | 型 | 説明 |
|-------|------|------|
| agent_definition | JSONB NOT NULL | エージェント定義JSON（本仕様で定義する形式） |

グラフ定義・エージェント定義・プロンプト定義は同一テーブルの同一レコードに格納し、常に1セットで取得・更新する。

## 3. JSON形式の仕様

### 3.1 トップレベル構造

エージェント定義は以下のトップレベルフィールドを持つJSONオブジェクトである。

| フィールド | 型 | 必須 | 説明 |
|-----------|------|------|------|
| `version` | 文字列 | 必須 | 定義フォーマットバージョン（例: "1.0"） |
| `agents` | オブジェクト配列 | 必須 | 各エージェントノードの定義配列（後述） |

### 3.2 エージェントノード定義（agents）

`agents`は各エージェントノードを定義するオブジェクトの配列である。

| フィールド | 型 | 必須 | 説明 |
|-----------|------|------|------|
| `id` | 文字列 | 必須 | エージェントの一意識別子（グラフ定義の`agent_definition_id`と一致させる） |
| `role` | 文字列 | 必須 | エージェント役割（"planning" / "reflection" / "execution" / "review"） |
| `input_keys` | 文字列配列 | 必須 | ワークフローコンテキストから受け取るキー一覧 |
| `output_keys` | 文字列配列 | 必須 | ワークフローコンテキストへ書き込むキー一覧 |
| `tools` | 文字列配列 | 必須 | 利用するツール名一覧 |
| `prompt_id` | 文字列 | 必須 | プロンプト定義ファイル内の対応するプロンプトID |
| `max_iterations` | 整数 | 任意 | LLMとのターン数上限（デフォルト: 20） |
| `timeout_seconds` | 整数 | 任意 | タイムアウト秒数（デフォルト: 600） |
| `description` | 文字列 | 任意 | エージェントの説明文 |

**roleの値と処理内容**:

| role | 処理内容 |
|------|---------|
| `planning` | コンテキスト取得→LLM呼び出し（プランニング）→Todoリスト作成→GitLab投稿→コンテキスト保存 |
| `reflection` | プラン取得→LLM呼び出し（検証）→改善判定→GitLab投稿→コンテキスト保存 |
| `execution` | プラン取得→LLM呼び出し（実装/生成）→ファイル操作（MCPツール）→git操作→コンテキスト保存 |
| `review` | MR差分取得→LLM呼び出し（レビュー）→コメント生成→GitLab投稿→コンテキスト保存 |

**toolsに指定可能な値**:

| ツール名 | 説明 |
|---------|------|
| `text_editor` | ファイル読み書き操作（text-editor MCPサーバー） |
| `command_executor` | コマンド実行（command-executor MCPサーバー） |
| `create_todo_list` | Todoリスト作成（Agent Frameworkネイティブツール） |
| `get_todo_list` | Todoリスト取得（Agent Frameworkネイティブツール） |
| `update_todo_status` | Todo状態更新（Agent Frameworkネイティブツール） |
| `sync_to_gitlab` | GitLabへTodoリスト同期（Agent Frameworkネイティブツール） |

## 4. システムプリセット

### 4.1 標準MR処理エージェント定義（standard_mr_processing）

```json
{
  "version": "1.0",
  "agents": [
    {
      "id": "task_classifier",
      "role": "planning",
      "input_keys": ["task_context"],
      "output_keys": ["classification_result"],
      "tools": ["text_editor"],
      "prompt_id": "task_classifier",
      "max_iterations": 5,
      "timeout_seconds": 120,
      "description": "Issue/MRの内容を分析してタスク種別を判定する"
    },
    {
      "id": "code_generation_planning",
      "role": "planning",
      "input_keys": ["task_context", "classification_result"],
      "output_keys": ["plan_result", "todo_list"],
      "tools": ["text_editor", "create_todo_list", "sync_to_gitlab"],
      "prompt_id": "code_generation_planning",
      "max_iterations": 15,
      "timeout_seconds": 300,
      "description": "コード生成タスクの実行計画を生成する"
    },
    {
      "id": "bug_fix_planning",
      "role": "planning",
      "input_keys": ["task_context", "classification_result"],
      "output_keys": ["plan_result", "todo_list"],
      "tools": ["text_editor", "create_todo_list", "sync_to_gitlab"],
      "prompt_id": "bug_fix_planning",
      "max_iterations": 15,
      "timeout_seconds": 300,
      "description": "バグ修正タスクの実行計画を生成する"
    },
    {
      "id": "test_creation_planning",
      "role": "planning",
      "input_keys": ["task_context", "classification_result"],
      "output_keys": ["plan_result", "todo_list"],
      "tools": ["text_editor", "create_todo_list", "sync_to_gitlab"],
      "prompt_id": "test_creation_planning",
      "max_iterations": 15,
      "timeout_seconds": 300,
      "description": "テスト作成タスクの実行計画を生成する"
    },
    {
      "id": "documentation_planning",
      "role": "planning",
      "input_keys": ["task_context", "classification_result"],
      "output_keys": ["plan_result", "todo_list"],
      "tools": ["text_editor", "create_todo_list", "sync_to_gitlab"],
      "prompt_id": "documentation_planning",
      "max_iterations": 15,
      "timeout_seconds": 300,
      "description": "ドキュメント生成タスクの実行計画を生成する"
    },
    {
      "id": "plan_reflection",
      "role": "reflection",
      "input_keys": ["plan_result", "todo_list", "task_context"],
      "output_keys": ["reflection_result"],
      "tools": ["text_editor", "get_todo_list", "sync_to_gitlab"],
      "prompt_id": "plan_reflection",
      "max_iterations": 10,
      "timeout_seconds": 180,
      "description": "プランを検証し、問題点と改善案を提示する"
    },
    {
      "id": "code_generation",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": [
        "text_editor",
        "command_executor",
        "update_todo_status",
        "sync_to_gitlab"
      ],
      "prompt_id": "code_generation",
      "max_iterations": 40,
      "timeout_seconds": 1800,
      "description": "新規コードを生成する"
    },
    {
      "id": "bug_fix",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": [
        "text_editor",
        "command_executor",
        "update_todo_status",
        "sync_to_gitlab"
      ],
      "prompt_id": "bug_fix",
      "max_iterations": 40,
      "timeout_seconds": 1800,
      "description": "バグ修正を実装する"
    },
    {
      "id": "test_creation",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": [
        "text_editor",
        "command_executor",
        "update_todo_status",
        "sync_to_gitlab"
      ],
      "prompt_id": "test_creation",
      "max_iterations": 30,
      "timeout_seconds": 1200,
      "description": "テストコードを作成する"
    },
    {
      "id": "documentation",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": ["text_editor", "update_todo_status", "sync_to_gitlab"],
      "prompt_id": "documentation",
      "max_iterations": 30,
      "timeout_seconds": 900,
      "description": "ドキュメントを作成する"
    },
    {
      "id": "code_review",
      "role": "review",
      "input_keys": ["execution_environments", "execution_results", "task_context"],
      "output_keys": ["review_result"],
      "tools": ["text_editor", "sync_to_gitlab"],
      "prompt_id": "code_review",
      "max_iterations": 10,
      "timeout_seconds": 300,
      "description": "コードレビューを実施する"
    },
    {
      "id": "documentation_review",
      "role": "review",
      "input_keys": ["execution_environments", "execution_results", "task_context"],
      "output_keys": ["review_result"],
      "tools": ["text_editor", "sync_to_gitlab"],
      "prompt_id": "documentation_review",
      "max_iterations": 10,
      "timeout_seconds": 300,
      "description": "ドキュメントレビューを実施する"
    },
    {
      "id": "test_execution_evaluation",
      "role": "review",
      "input_keys": ["execution_environments", "execution_results", "task_context"],
      "output_keys": ["review_result"],
      "tools": ["command_executor", "sync_to_gitlab"],
      "prompt_id": "test_execution_evaluation",
      "max_iterations": 15,
      "timeout_seconds": 600,
      "description": "テストを実行し結果を評価する"
    }
  ]
}
```

### 4.2 複数コード生成並列エージェント定義（multi_codegen_mr_processing）

コーディングエージェントを3種類の設定で並列実行する場合のエージェント定義。task_classifierからtest_execution_evaluationまで標準と共通の定義を継承し、以下を追加する。

**重要な実装方針**: 全ての実行エージェント（単一・並列問わず）は、共通の辞書型キー（`execution_environments`と`execution_results`）を使用する。各エージェントは自身のエージェント定義IDをキーとして辞書に書き込む。単一エージェントの場合は1要素の辞書、並列エージェントの場合は複数要素の辞書となる。この統一設計により、フレームワーク側の処理が簡素化され、エージェント定義も統一される。

```json
{
  "version": "1.0",
  "agents": [
    {
      "id": "code_generation_fast",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": [
        "text_editor",
        "command_executor",
        "update_todo_status",
        "sync_to_gitlab"
      ],
      "prompt_id": "code_generation_fast",
      "max_iterations": 30,
      "timeout_seconds": 900,
      "description": "高速モデルでコードを生成する"
    },
    {
      "id": "code_generation_standard",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": [
        "text_editor",
        "command_executor",
        "update_todo_status",
        "sync_to_gitlab"
      ],
      "prompt_id": "code_generation_standard",
      "max_iterations": 40,
      "timeout_seconds": 1800,
      "description": "標準モデルでコードを生成する"
    },
    {
      "id": "code_generation_creative",
      "role": "execution",
      "input_keys": ["plan_result", "task_context"],
      "output_keys": ["execution_environments", "execution_results"],
      "tools": [
        "text_editor",
        "command_executor",
        "update_todo_status",
        "sync_to_gitlab"
      ],
      "prompt_id": "code_generation_creative",
      "max_iterations": 40,
      "timeout_seconds": 1800,
      "description": "高温度設定で創造的なコードを生成する"
    },
    {
      "id": "code_review",
      "role": "review",
      "input_keys": [
        "execution_environments",
        "execution_results",
        "task_context"
      ],
      "output_keys": ["review_result", "selected_implementation"],
      "tools": ["text_editor", "sync_to_gitlab"],
      "prompt_id": "code_review_multi",
      "max_iterations": 15,
      "timeout_seconds": 600,
      "description": "複数の並列コード生成結果を比較レビューし、最良のものを自動選択する"
    },
    {
      "id": "plan_reflection",
      "role": "reflection",
      "input_keys": ["review_result", "task_context"],
      "output_keys": ["reflection_result"],
      "tools": ["text_editor", "sync_to_gitlab"],
      "prompt_id": "plan_reflection",
      "max_iterations": 10,
      "timeout_seconds": 180,
      "description": "レビュー結果を評価し再計画の要否を判断する"
    }
  ]
}
```

## 5. コンテキストキー一覧

ステップ間でワークフローコンテキストを通じてやり取りするキーの定義。

| キー名 | 型 | 説明 | 設定エージェント定義ID |
|-------|------|------|------|
| `task_context` | TaskContext | タスク共通情報（UUID・MR情報・ユーザー情報） | UserResolverExecutor |
| `classification_result` | ClassificationResult | タスク種別・関連ファイル・仕様書情報 | task_classifier |
| `plan_result` | PlanResult | 実行計画・仕様書有無フラグ | *_planning |
| `todo_list` | TodoList | Todoリスト | *_planning |
| `execution_environments` | 辞書型（Dict[str, str]） | 実行エージェントの環境IDマッピング。キー：エージェント定義ID、値：環境ID。単一エージェントでも辞書型を使用（1要素の辞書） | code_generation / bug_fix / test_creation / documentation / code_generation_* 等 |
| `execution_results` | 辞書型（Dict[str, ExecutionResult]） | 実行エージェントの実行結果マッピング。キー：エージェント定義ID、値：ExecutionResult。単一エージェントでも辞書型を使用（1要素の辞書） | code_generation / bug_fix / test_creation / documentation / code_generation_* 等 |
| `selected_implementation` | SelectedImplementation | 自動選択された最良の実装情報（環境ID、ブランチ名、選択理由、評価スコア、評価詳細） | code_review（multi用） |
| `reflection_result` | ReflectionResult | プラン検証結果・再計画判断 | plan_reflection |
| `review_result` | ReviewResult | レビュー結果・指摘事項 | code_review / documentation_review / test_execution_evaluation |

**主要なデータ構造の詳細**:

- **ExecutionResult**: 実行結果を表す構造。フィールドは environment_id（使用した環境ID）、branch_name（作業したブランチ名）、changed_files（変更ファイルパスのリスト）、summary（実行内容のサマリ）、todo_status（Todo IDと状態のマッピング）、created_at（実行完了時刻）

- **SelectedImplementation**: 選択された実装情報を表す構造。フィールドは environment_id（選択された環境ID）、branch_name（選択されたブランチ名）、selection_reason（選択理由の詳細説明）、quality_score（品質スコア 0.0～1.0）、evaluation_details（評価の詳細情報、辞書型）

- **TaskContext**: タスク共通情報。フィールドは task_uuid、task_type、project_id、issue_iid、mr_iid、original_branch、assigned_branch、user_id、user_email、openai_api_key、workflow_definition_id

- **ClassificationResult**: タスク分類結果。フィールドは task_type、confidence、reasoning、related_files、spec_file_exists、spec_file_path

- **PlanResult**: 実行計画。フィールドは actions（アクションリスト）、spec_file_exists、estimated_duration_minutes、dependencies、risks

- **ReviewResult**: レビュー結果。フィールドは status、issues（指摘事項リスト）、summary、suggested_actions

- **ReflectionResult**: プラン検証結果。フィールドは action（"proceed" / "revise_plan" / "abort"）、issues、suggestions、confidence

**コンテキストキーの統一設計**:

全ての実行エージェント（単一・並列問わず）は、`execution_environments`と`execution_results`という共通の辞書型キーを使用する。各エージェントは自身のエージェント定義IDをキーとして辞書に書き込む。単一エージェントの場合は1要素の辞書（例: `{"code_generation": "env_123"}`）、並列エージェントの場合は複数要素の辞書（例: `{"code_generation_fast": "env_1", "code_generation_standard": "env_2", ...}`）となる。この統一設計により、フレームワーク側の処理が簡素化され、エージェント定義も統一される。

---

## 6. 各エージェントノードの詳細説明

本セクションでは、エージェント定義ファイルで定義可能な各エージェントノードの詳細な処理フロー、責務、設定を記載する。これらのエージェントは`ConfigurableAgent`クラスのインスタンスとして実行され、エージェント定義とプロンプト定義により動作が決定される。

**注**: 定義ファイルで定義されない固定実装のExecutor（User Resolver Executor、Environment Setup Executor等）については[CODE_AGENT_ORCHESTRATOR_SPEC.md](CODE_AGENT_ORCHESTRATOR_SPEC.md)のセクション4.3.2を参照。

### 6.1 Task Classifier Agent

**Agent Frameworkクラス**: `ConfigurableAgent`（`ChatCompletionAgent`を継承）

**責務**: Issue/MR内容を分析し、タスクを4つのカテゴリのいずれかに分類する。プロンプト詳細はPROMPTS.mdを参照。

**実装方法**:
- `ConfigurableAgent`として実装され、エージェント定義ファイルで設定される
- 分類結果を`ClassificationResult`データクラスで構造化する
- ワークフローコンテキストに分類結果を保存する

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

**利用可能なツール**（エージェント定義の`tools`フィールドで指定）:
- `text_editor`: リポジトリ内のファイルをリスト表示・読み込み・検索（text-editor MCPサーバー）

**出力形式**:
`ClassificationResult`データクラス（CODE_AGENT_ORCHESTRATOR_SPECセクション5.5.6で定義）：
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

---

### 6.2 Planning Agent群（code_generation_planning / bug_fix_planning / test_creation_planning / documentation_planning）

各Planning AgentはすべてConfigurableAgentとして実装され、エージェント定義とプロンプト定義により動作が決定される。

#### 6.2.1 コード生成 Planning Agent ノード

**エージェント定義ID**: `code_generation_planning`

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
3. 仕様ファイルが存在しない場合はドキュメント生成ワークフローにリダイレクト
4. 仕様ファイルが存在する場合、コード生成のためのアクションプランを生成
5. Todoリストの作成（`create_todo_list`ツールで永続化）
6. GitLabへのTodoリスト投稿（`sync_to_gitlab`ツール）

#### 6.2.2 バグ修正 Planning Agent ノード

**エージェント定義ID**: `bug_fix_planning`

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
3. 仕様ファイルが存在しない場合はドキュメント生成ワークフローにリダイレクト
4. 仕様ファイルが存在する場合、バグ修正のためのアクションプランを生成
5. 修正対象ファイルと変更箇所の特定
6. Todoリストの作成と投稿

#### 6.2.3 テスト生成 Planning Agent ノード

**エージェント定義ID**: `test_creation_planning`

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
3. 仕様ファイルが存在しない場合はドキュメント生成ワークフローにリダイレクト
4. テスト戦略の決定（ユニット/統合/E2Eテストの選択）
5. テストケースの設計（正常系・異常系・境界値）
6. Todoリストの作成と投稿

#### 6.2.4 ドキュメント生成 Planning Agent ノード

**エージェント定義ID**: `documentation_planning`

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

---

### 6.3 Plan Reflection Agent ノード

**エージェント定義ID**: `plan_reflection`

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

---

### 6.4 Execution Agent群（code_generation / bug_fix / test_creation / documentation）

各Execution AgentはすべてConfigurableAgentとして実装され、エージェント定義とプロンプト定義により動作が決定される。

#### 6.4.1 Code Generation Agent ノード

**エージェント定義ID**: `code_generation`

**責務**: 新規コードを生成する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_environments", "execution_results"]
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

#### 6.4.2 Bug Fix Agent ノード

**エージェント定義ID**: `bug_fix`

**責務**: バグ修正を実装する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_environments", "execution_results"]
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

#### 6.4.3 Documentation Agent ノード

**エージェント定義ID**: `documentation`

**責務**: ドキュメントを作成する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_environments", "execution_results"]
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

#### 6.4.4 Test Creation Agent ノード

**エージェント定義ID**: `test_creation`

**責務**: テストコードを作成する

**エージェント定義の主要設定**:
- `role`: "execution"
- `input_keys`: ["plan_result", "task_context"]
- `output_keys`: ["execution_environments", "execution_results"]
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

---

### 6.5 Test Execution & Evaluation Agent ノード

**エージェント定義ID**: `test_execution_evaluation`

**責務**: テストコードを実行し、結果を評価する

**エージェント定義の主要設定**:
- `role`: "review"
- `input_keys`: ["execution_environments", "execution_results", "task_context"]
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

---

### 6.6 Review Agent群（code_review / documentation_review）

各Review AgentはすべてConfigurableAgentとして実装され、エージェント定義とプロンプト定義により動作が決定される。

#### 6.6.1 Code Review Agent ノード

**エージェント定義ID**: `code_review`

**責務**: コードレビューを実施する

**エージェント定義の主要設定**:
- `role`: "review"
- `input_keys`: ["execution_environments", "execution_results", "task_context"]
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

#### 6.6.2 Documentation Review Agent ノード

**エージェント定義ID**: `documentation_review`

**責務**: ドキュメントレビューを実施する

**エージェント定義の主要設定**:
- `role`: "review"
- `input_keys`: ["execution_environments", "execution_results", "task_context"]
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
