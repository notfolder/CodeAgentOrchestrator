# SPEC_CHECK.md — ドキュメント整合性チェックレポート

**チェック実施日**: 2025年7月  
**対象ブランチ**: main  
**チェック対象**: docs/ 配下の全ドキュメント（.md）および全JSONファイル

---

## 1. チェックサマリー

| 重大度 | 件数 | 内容 |
|--------|------|------|
| 🔴 高（実装に影響する矛盾） | 1件 | `execution_result` / `execution_results` のキー名不統一 |
| 🟡 中（仕様書の欠落・不整合） | 2件 | `metadata` フィールド未記載、節番号重複 |
| 🟢 低（情報整合性の改善余地） | 5件 | フロー図の簡略化による不一致、節番号誤り等 |
| ✅ 問題なし | — | 上記以外の全チェック項目 |

**矛盾・問題の合計**: 8件

---

## 2. ドキュメント章ごとの矛盾チェック表

### 2.1 AUTOMATA_CODEX_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 目的と範囲 | — | 問題なし |
| 2 | システムアーキテクチャ | CLASS_IMPLEMENTATION_SPEC.md 全章 | 問題なし |
| 3 | ユーザー管理システム | USER_MANAGEMENT_SPEC.md 全章, DATABASE_SCHEMA_SPEC.md §2 | 問題なし |
| 4 | エージェント構成 | AGENT_DEFINITION_SPEC.md 全章, CLASS_IMPLEMENTATION_SPEC.md §2 | 問題なし |
| 5 | ワークフロー（プランニングベース） | STANDARD_MR_PROCESSING_FLOW.md, MULTI_MR_PROCESSING_FLOW.md | 問題なし |
| 6 | 進捗報告機能 | CLASS_IMPLEMENTATION_SPEC.md §10.3–10.5 | 問題なし |
| 7 | GitLab API 操作設計 | CLASS_IMPLEMENTATION_SPEC.md §10.2 | 問題なし |
| 8 | 状態管理設計 | DATABASE_SCHEMA_SPEC.md §4.5, §5 | **矛盾あり** ※1: 節番号 8.3 が2箇所存在する |
| 9 | Tool管理設計 (MCP) | AGENT_DEFINITION_SPEC.md §3.2 (mcp_servers), CLASS_IMPLEMENTATION_SPEC.md §9 | **矛盾あり** ※1: 節番号 9.3 / 9.4 が2箇所存在する |
| 10 | エラー処理設計 | CLASS_IMPLEMENTATION_SPEC.md §5.4 | 問題なし（ただし節番号混乱の余波あり ※1） |
| 11 | 学習機能（Self-Learning System） | CLASS_IMPLEMENTATION_SPEC.md §11 | 問題なし |
| 12 | セキュリティ設計 | USER_MANAGEMENT_SPEC.md §4, DATABASE_SCHEMA_SPEC.md §11 | 問題なし |
| 13 | 運用設計 | — | 問題なし |
| 14 | 設定ファイル定義 | — | 問題なし |
| 15 | まとめ | — | 問題なし |
| 付録B | Agent Framework vs coding_agent 対応表 | CLASS_IMPLEMENTATION_SPEC.md 全章 | 問題なし |

### 2.2 AGENT_DEFINITION_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要 | AUTOMATA_CODEX_SPEC.md §4 | 問題なし |
| 2 | DBへの保存形式 | DATABASE_SCHEMA_SPEC.md §3.1 | 問題なし |
| 3.1 | トップレベル構造 | standard/multi_codegen _agents.json | 問題なし |
| 3.2 | エージェントノード定義（agents） | standard/multi_codegen _agents.json | **矛盾あり** ※2: `metadata` フィールドが仕様表に未記載 |
| 4.1 | 標準MR処理エージェント定義 | standard_mr_processing_agents.json | 問題なし |
| 4.2 | 複数コード生成並列エージェント定義 | multi_codegen_mr_processing_agents.json | **矛盾あり** ※7: 「継承」説明とJSON実態の乖離 |
| 5 | コンテキストキー一覧 | standard/multi_codegen _agents.json | **矛盾あり** ※3: `execution_results`（複数）と定義するが、JSON内で `execution_result`（単数）が混在 |
| 6.1–6.7 | 各エージェントノードの詳細説明 | standard/multi_codegen _agents.json, PROMPTS.md | 問題なし |

### 2.3 CLASS_IMPLEMENTATION_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | ConfigurableAgent | AUTOMATA_CODEX_SPEC.md §4, §8 | 問題なし |
| 2 | Factory群 | AUTOMATA_CODEX_SPEC.md §4.1 | 問題なし |
| 3 | Executor群 | AUTOMATA_CODEX_SPEC.md §4 | 問題なし |
| 4 | Custom Provider群 | AUTOMATA_CODEX_SPEC.md §8.3, §8.5, §8.6 | 問題なし |
| 5 | Middleware実装 | AUTOMATA_CODEX_SPEC.md §8.9 | 問題なし |
| 6 | ExecutionEnvironmentManager | AUTOMATA_CODEX_SPEC.md §8.8 | 問題なし |
| 7 | EnvironmentAnalyzer | AUTOMATA_CODEX_SPEC.md §8.8 | 問題なし |
| 8 | PrePlanningManager | STANDARD_MR_PROCESSING_FLOW.md §4.1 | 問題なし |
| 9 | MCPClient関連 | AUTOMATA_CODEX_SPEC.md §9 | 問題なし |
| 10 | その他の主要クラス | AUTOMATA_CODEX_SPEC.md §6, §7 | 問題なし |
| 11 | GuidelineLearningAgent | AUTOMATA_CODEX_SPEC.md §11 | **矛盾あり** ※6: 章番号 11 内の節番号が 10.1〜10.5 となっている |
| 12 | まとめ | — | 問題なし |

### 2.4 DATABASE_SCHEMA_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要・ER図 | AUTOMATA_CODEX_SPEC.md 全章 | 問題なし |
| 2 | ユーザー管理テーブル群 | USER_MANAGEMENT_SPEC.md §3, AUTOMATA_CODEX_SPEC.md §3 | 問題なし |
| 3 | ワークフロー定義テーブル | AGENT_DEFINITION_SPEC.md §2, GRAPH_DEFINITION_SPEC.md §2, PROMPT_DEFINITION_SPEC.md §2 | 問題なし |
| 4 | タスク管理テーブル | AUTOMATA_CODEX_SPEC.md §5 | 問題なし |
| 4.5 | ワークフロー実行管理テーブル群 | AUTOMATA_CODEX_SPEC.md §8.4 | 問題なし |
| 5 | コンテキストストレージテーブル群 | AUTOMATA_CODEX_SPEC.md §8.3–8.6 | 問題なし |
| 6 | Todo管理テーブル | AGENT_DEFINITION_SPEC.md §3.2 (todo_list) | 問題なし |
| 7 | メトリクステーブル | AUTOMATA_CODEX_SPEC.md §8.9 (TokenUsageMiddleware) | 問題なし |
| 8–13 | 運用・セキュリティ・マイグレーション | — | 問題なし |

### 2.5 GRAPH_DEFINITION_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要 | AUTOMATA_CODEX_SPEC.md §4 | 問題なし |
| 2 | DBへの保存形式 | DATABASE_SCHEMA_SPEC.md §3.1 | 問題なし |
| 3.1 | トップレベル構造 | standard/multi_codegen _graph.json | 問題なし |
| 3.2 | ノード定義 | standard/multi_codegen _graph.json | 問題なし |
| 3.3 | エッジ定義 | standard/multi_codegen _graph.json | 問題なし |
| 4.1 | 標準MR処理グラフ | standard_mr_processing_graph.json, STANDARD_MR_PROCESSING_FLOW.md | 問題なし |
| 4.2 | 複数コード生成並列グラフ | multi_codegen_mr_processing_graph.json, MULTI_MR_PROCESSING_FLOW.md | 問題なし |
| 5 | バリデーション仕様 | — | 問題なし |
| 6 | 定義の取得・更新フロー | USER_MANAGEMENT_SPEC.md §6.2 | 問題なし |

### 2.6 MULTI_MR_PROCESSING_FLOW.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要 | AUTOMATA_CODEX_SPEC.md §4, §5 | 問題なし |
| 2 | エージェント構成 | multi_codegen_mr_processing_agents.json, AGENT_DEFINITION_SPEC.md §4.2 | 問題なし |
| 3 | MR処理の全体フロー | multi_codegen_mr_processing_graph.json | **矛盾あり** ※5: フロー図の replan終了パスの表現がJSONと不一致 |
| 4.1–4.8 | フェーズ詳細 | multi_codegen _agents.json, _graph.json | 問題なし |
| 5 | コード生成タスクの詳細フロー | multi_codegen _graph.json | 問題なし |
| 6 | ブランチ管理 | AUTOMATA_CODEX_SPEC.md §4.5 | 問題なし |
| 7 | まとめ | — | 問題なし |

### 2.7 PROMPTS.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | Task Classifier Agent | AGENT_DEFINITION_SPEC.md §6.1, standard/multi_codegen _agents.json | 問題なし |
| 2 | コード生成 Planning Agent | AGENT_DEFINITION_SPEC.md §6.2 | 問題なし |
| 3 | バグ修正 Planning Agent | AGENT_DEFINITION_SPEC.md §6.2 | 問題なし |
| 4 | テスト生成 Planning Agent | AGENT_DEFINITION_SPEC.md §6.2 | 問題なし |
| 5 | ドキュメント生成 Planning Agent | AGENT_DEFINITION_SPEC.md §6.2 | 問題なし |
| 6 | Plan Reflection Agent | AGENT_DEFINITION_SPEC.md §6.3 | 問題なし |
| 7 | Code Generation Agent | AGENT_DEFINITION_SPEC.md §6.4 | 問題なし |
| 8 | Bug Fix Agent | AGENT_DEFINITION_SPEC.md §6.4 | 問題なし |
| 9 | Documentation Agent | AGENT_DEFINITION_SPEC.md §6.4 | 問題なし |
| 10 | Test Creation Agent | AGENT_DEFINITION_SPEC.md §6.4 | 問題なし |
| 11 | Test Execution & Evaluation Agent | AGENT_DEFINITION_SPEC.md §6.5 | 問題なし |
| 12 | Code Review Agent | AGENT_DEFINITION_SPEC.md §6.6 | 問題なし |
| 13 | Documentation Review Agent | AGENT_DEFINITION_SPEC.md §6.6 | 問題なし |
| 14 | Code Generation Reflection Agent（標準フロー専用） | AGENT_DEFINITION_SPEC.md §6.7 | 問題なし |
| 15 | Test Creation Reflection Agent（標準フロー専用） | AGENT_DEFINITION_SPEC.md §6.7 | 問題なし |
| 16 | Documentation Reflection Agent（標準フロー専用） | AGENT_DEFINITION_SPEC.md §6.7 | 問題なし |
| 17 | Code Generation Agent（高速モード）multi_codegen専用 | AGENT_DEFINITION_SPEC.md §4.2 | 問題なし |
| 18 | Code Generation Agent（標準モード）multi_codegen専用 | AGENT_DEFINITION_SPEC.md §4.2 | 問題なし |
| 19 | Code Generation Agent（創造的モード）multi_codegen専用 | AGENT_DEFINITION_SPEC.md §4.2 | 問題なし |
| 20 | Code Review Agent（複数実装比較）multi_codegen専用 | AGENT_DEFINITION_SPEC.md §4.2 | 問題なし |

### 2.8 PROMPT_DEFINITION_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要 | AUTOMATA_CODEX_SPEC.md §4 | 問題なし |
| 2 | DBへの保存形式 | DATABASE_SCHEMA_SPEC.md §3.1 | 問題なし |
| 3.1 | トップレベル構造 | standard/multi_codegen _prompts.json | 問題なし |
| 3.2 | デフォルトLLMパラメータ | standard/multi_codegen _prompts.json | 問題なし |
| 3.3 | プロンプト定義 | standard/multi_codegen _prompts.json | 問題なし |
| 4.1 | 標準MR処理プロンプト定義 | standard_mr_processing_prompts.json, PROMPTS.md | 問題なし |
| 4.2 | 複数コード生成並列プロンプト定義 | multi_codegen_mr_processing_prompts.json, PROMPTS.md | 問題なし |
| 5 | バリデーション仕様 | — | 問題なし |
| 6 | プロンプト適用優先順位 | AGENT_DEFINITION_SPEC.md §3.2 | 問題なし |

### 2.9 STANDARD_MR_PROCESSING_FLOW.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要 | AUTOMATA_CODEX_SPEC.md §5 | 問題なし |
| 2 | エージェント構成 | standard_mr_processing_agents.json, AGENT_DEFINITION_SPEC.md §4.1 | 問題なし |
| 3 | MR処理の全体フロー | standard_mr_processing_graph.json | **矛盾あり** ※4: `Complete{完了?}` ノードがJSONに存在しない |
| 4.1–4.8 | フェーズ詳細 | standard _agents.json, _graph.json | 問題なし |
| 5.1–5.4 | タスク種別別詳細フロー | standard _agents.json, _graph.json | 問題なし |
| 6 | 仕様ファイル管理 | AUTOMATA_CODEX_SPEC.md §4 | 問題なし |
| 7 | まとめ | — | 問題なし |

### 2.10 USER_MANAGEMENT_SPEC.md

| 章 | 章タイトル | 関連ドキュメント/章 | 判定 |
|----|-----------|-------------------|------|
| 1 | 概要 | AUTOMATA_CODEX_SPEC.md §3 | 問題なし |
| 2 | ユーザー登録フロー | AUTOMATA_CODEX_SPEC.md §3 | 問題なし |
| 3 | データベース設計 | DATABASE_SCHEMA_SPEC.md §2 | 問題なし |
| 4 | APIキー暗号化 | DATABASE_SCHEMA_SPEC.md §11.1 | 問題なし |
| 5 | 初期管理者作成ツール | — | 問題なし |
| 6 | User Config API | AUTOMATA_CODEX_SPEC.md §3 | 問題なし |
| 7 | Web管理画面 | — | 問題なし |
| 8 | ユーザー別トークン統計処理 | DATABASE_SCHEMA_SPEC.md §7 | 問題なし |
| 9 | Web管理画面の詳細設計 | — | 問題なし |

---

## 3. JSONファイルとドキュメントの矛盾チェック表

### 3.1 standard_mr_processing_agents.json

| チェック項目 | 関連ドキュメント/章 | 判定 |
|------------|-------------------|------|
| トップレベル構造（version, agents） | AGENT_DEFINITION_SPEC.md §3.1 | 問題なし |
| 各エージェントのフィールド（id, role, input_keys, output_keys, mcp_servers, prompt_id, max_iterations, timeout_seconds, description） | AGENT_DEFINITION_SPEC.md §3.2 | 問題なし |
| `metadata` フィールド（code/bug/test/doc_planningエージェントに存在） | AGENT_DEFINITION_SPEC.md §3.2 | **矛盾あり** ※2: 仕様書に `metadata` フィールドの定義なし |
| role 値（planning/reflection/execution/review） | AGENT_DEFINITION_SPEC.md §3.2 | 問題なし |
| `code_generation`, `bug_fix`, `test_creation`, `documentation` の output_keys = `execution_results`（複数） | AGENT_DEFINITION_SPEC.md §5 | 問題なし |
| `code_generation_reflection`, `test_creation_reflection`, `documentation_reflection` の input_keys = `execution_result`（単数） | AGENT_DEFINITION_SPEC.md §5 | **矛盾あり** ※3: output が `execution_results`（複数）なのに input が `execution_result`（単数） |
| `plan_reflection` の input_keys に `execution_result`（単数）が含まれる | AGENT_DEFINITION_SPEC.md §5 | **矛盾あり** ※3: 同上、単数/複数の不一致 |
| mcp_servers の値（text_editor, command_executor, todo_list） | AGENT_DEFINITION_SPEC.md §3.2 | 問題なし |
| prompt_id が standard_mr_processing_prompts.json に存在する | PROMPT_DEFINITION_SPEC.md §4.1 | 問題なし |

### 3.2 standard_mr_processing_graph.json

| チェック項目 | 関連ドキュメント/章 | 判定 |
|------------|-------------------|------|
| トップレベル構造（version, nodes, edges） | GRAPH_DEFINITION_SPEC.md §3.1 | 問題なし |
| ノードフィールド（id, type, label, agent_definition_id, executor_class, env_ref, env_count, metadata） | GRAPH_DEFINITION_SPEC.md §3.2 | 問題なし |
| エッジフィールド（from, to, condition, label, metadata） | GRAPH_DEFINITION_SPEC.md §3.3 | 問題なし |
| 全ノードIDが AGENT_DEFINITION_SPEC.md §4.1 のエージェントIDと整合 | AGENT_DEFINITION_SPEC.md §4.1 | 問題なし |
| フロー図との一致（主要接続関係） | STANDARD_MR_PROCESSING_FLOW.md §3 | **矛盾あり** ※4: `Complete{完了?}` ノードがJSONに存在しない（概念的には同等だが図が簡略化） |

### 3.3 standard_mr_processing_prompts.json

| チェック項目 | 関連ドキュメント/章 | 判定 |
|------------|-------------------|------|
| トップレベル構造（version, default_llm_params, prompts） | PROMPT_DEFINITION_SPEC.md §3.1 | 問題なし |
| default_llm_params フィールド | PROMPT_DEFINITION_SPEC.md §3.2 | 問題なし |
| 各プロンプト要素フィールド（id, system_prompt, description, llm_params） | PROMPT_DEFINITION_SPEC.md §3.3 | 問題なし |
| プロンプトIDが PROMPTS.md の全プロンプトをカバーするか（標準フロー分） | PROMPTS.md | 問題なし |
| `code_generation_fast/standard/creative` および `code_review_multi` はmulti_codegen専用のため不在 | PROMPTS.md §17–20 | 問題なし（意図的） |

### 3.4 multi_codegen_mr_processing_agents.json

| チェック項目 | 関連ドキュメント/章 | 判定 |
|------------|-------------------|------|
| トップレベル構造（version, agents） | AGENT_DEFINITION_SPEC.md §3.1 | 問題なし |
| 各エージェントのフィールド | AGENT_DEFINITION_SPEC.md §3.2 | 問題なし |
| `metadata` フィールド（code/bug/test/doc_planningエージェントに存在） | AGENT_DEFINITION_SPEC.md §3.2 | **矛盾あり** ※2: 仕様書に `metadata` フィールドの定義なし |
| `bug_fix`, `test_creation`, `documentation` の output_keys = `execution_result`（単数） | AGENT_DEFINITION_SPEC.md §5 | **矛盾あり** ※3: 仕様書では `execution_results`（複数）と定義 |
| `code_generation_fast/standard/creative` の output_keys = `execution_results`（複数） | AGENT_DEFINITION_SPEC.md §5 | 問題なし（並列実行用） |
| `code_generation_reflection`, `test_creation_reflection`, `documentation_reflection` の input_keys = `execution_result`（単数） | AGENT_DEFINITION_SPEC.md §5 | bug/test/docとは整合するが仕様書定義と矛盾 ※3 |
| `documentation_review`, `test_execution_evaluation` の input_keys = `execution_result`（単数） | AGENT_DEFINITION_SPEC.md §5 | **矛盾あり** ※3: 仕様書では `execution_results`（複数）と定義 |
| `code_review` の prompt_id = `code_review_multi`（agent_idと不一致） | AGENT_DEFINITION_SPEC.md §4.2 | 問題なし（意図的。§4.2に明記） |
| prompt_id が multi_codegen_mr_processing_prompts.json に存在する | PROMPT_DEFINITION_SPEC.md §4.2 | 問題なし |

### 3.5 multi_codegen_mr_processing_graph.json

| チェック項目 | 関連ドキュメント/章 | 判定 |
|------------|-------------------|------|
| トップレベル構造（version, nodes, edges） | GRAPH_DEFINITION_SPEC.md §3.1 | 問題なし |
| ノードフィールド | GRAPH_DEFINITION_SPEC.md §3.2 | 問題なし |
| エッジフィールド | GRAPH_DEFINITION_SPEC.md §3.3 | 問題なし |
| 全ノードIDが AGENT_DEFINITION_SPEC.md §4.2 のエージェントIDと整合 | AGENT_DEFINITION_SPEC.md §4.2 | 問題なし |
| フロー図との一致（主要接続関係） | MULTI_MR_PROCESSING_FLOW.md §3 | **矛盾あり** ※5: `proceed → 終了` が図では `execution_type_branch` 経由として描かれているが、JSONでは `replan_branch → null（終了）` と `revise_plan → execution_type_branch` の2パターンに分かれる |

### 3.6 multi_codegen_mr_processing_prompts.json

| チェック項目 | 関連ドキュメント/章 | 判定 |
|------------|-------------------|------|
| トップレベル構造（version, default_llm_params, prompts） | PROMPT_DEFINITION_SPEC.md §3.1 | 問題なし |
| 各プロンプト要素フィールド | PROMPT_DEFINITION_SPEC.md §3.3 | 問題なし |
| プロンプトIDが PROMPTS.md の全プロンプトをカバーするか（multi_codegen分） | PROMPTS.md | 問題なし |
| `code_generation` および `code_review` はstandard専用のため不在 | PROMPTS.md §7, §12 | 問題なし（意図的） |

---

## 4. クラス/メソッドの実装情報充足度チェック表

> **評価基準**: 引数・戻り値・処理フローが CLASS_IMPLEMENTATION_SPEC.md に日本語で具体的に記述されているか

| クラス名 | メソッド名 | 記載ドキュメント/章 | 実装情報充足度 |
|---------|----------|------------------|--------------|
| ConfigurableAgent | handle（メッセージ受信・処理） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | get_chat_history（会話履歴取得） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | get_context（コンテキスト取得） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | store_result（結果保存） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | invoke_mcp_tool（MCPツール呼び出し） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | save_workflow_state（状態保存） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | load_workflow_state（状態ロード） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| ConfigurableAgent | resume_workflow（ワークフロー再開） | CLASS_IMPLEMENTATION_SPEC.md §1.4 | ✅ 充足 |
| WorkflowFactory | create_workflow（ワークフロー生成） | CLASS_IMPLEMENTATION_SPEC.md §2.1 | ✅ 充足 |
| ExecutorFactory | create_user_resolver | CLASS_IMPLEMENTATION_SPEC.md §2.2 | ✅ 充足 |
| ExecutorFactory | create_content_transfer | CLASS_IMPLEMENTATION_SPEC.md §2.2 | ✅ 充足 |
| ExecutorFactory | create_plan_env_setup | CLASS_IMPLEMENTATION_SPEC.md §2.2 | ✅ 充足 |
| ExecutorFactory | create_branch_merge | CLASS_IMPLEMENTATION_SPEC.md §2.2 | ✅ 充足 |
| AgentFactory | create_agent（エージェント生成） | CLASS_IMPLEMENTATION_SPEC.md §2.3 | ✅ 充足 |
| MCPClientFactory | create_mcp_tool（MCPツール生成） | CLASS_IMPLEMENTATION_SPEC.md §2.4 | ✅ 充足 |
| MCPClientFactory | create_text_editor_tool | CLASS_IMPLEMENTATION_SPEC.md §2.4 | ✅ 充足 |
| MCPClientFactory | create_command_executor_tool | CLASS_IMPLEMENTATION_SPEC.md §2.4 | ✅ 充足 |
| TaskStrategyFactory | create_strategy（戦略生成） | CLASS_IMPLEMENTATION_SPEC.md §2.5 | ✅ 充足 |
| TaskStrategyFactory | should_convert_issue_to_mr | CLASS_IMPLEMENTATION_SPEC.md §2.5 | ✅ 充足 |
| BaseExecutor | handle（抽象メソッド） | CLASS_IMPLEMENTATION_SPEC.md §3.1 | ✅ 充足 |
| BaseExecutor | get_context_value（コンテキスト取得ヘルパー） | CLASS_IMPLEMENTATION_SPEC.md §3.1 | ✅ 充足 |
| BaseExecutor | set_context_value（コンテキスト設定ヘルパー） | CLASS_IMPLEMENTATION_SPEC.md §3.1 | ✅ 充足 |
| UserResolverExecutor | handle | CLASS_IMPLEMENTATION_SPEC.md §3.2 | ✅ 充足 |
| ContentTransferExecutor | handle | CLASS_IMPLEMENTATION_SPEC.md §3.3 | ✅ 充足 |
| PlanEnvSetupExecutor | handle | CLASS_IMPLEMENTATION_SPEC.md §3.4 | ✅ 充足 |
| ExecEnvSetupExecutor | handle | CLASS_IMPLEMENTATION_SPEC.md §3.5 | ✅ 充足 |
| BranchMergeExecutor | handle | CLASS_IMPLEMENTATION_SPEC.md §3.6 | ✅ 充足 |
| PostgreSqlChatHistoryProvider | get_messages（メッセージ取得） | CLASS_IMPLEMENTATION_SPEC.md §4.1 | ✅ 充足 |
| PostgreSqlChatHistoryProvider | save_messages（メッセージ保存） | CLASS_IMPLEMENTATION_SPEC.md §4.1 | ✅ 充足 |
| PlanningContextProvider | before_run（前処理） | CLASS_IMPLEMENTATION_SPEC.md §4.2 | ✅ 充足 |
| PlanningContextProvider | after_run（後処理） | CLASS_IMPLEMENTATION_SPEC.md §4.2 | ✅ 充足 |
| ToolResultContextProvider | before_run（前処理） | CLASS_IMPLEMENTATION_SPEC.md §4.3 | ✅ 充足 |
| ToolResultContextProvider | after_run（後処理） | CLASS_IMPLEMENTATION_SPEC.md §4.3 | ✅ 充足 |
| ContextCompressionService | check_and_compress_async（圧縮判定・実行） | CLASS_IMPLEMENTATION_SPEC.md §4.4 | ✅ 充足 |
| ContextCompressionService | compress_messages_async（メッセージ圧縮） | CLASS_IMPLEMENTATION_SPEC.md §4.4 | ✅ 充足 |
| ContextCompressionService | replace_with_summary_async（サマリ置換） | CLASS_IMPLEMENTATION_SPEC.md §4.4 | ✅ 充足 |
| TaskInheritanceContextProvider | before_run（前処理） | CLASS_IMPLEMENTATION_SPEC.md §4.5 | ✅ 充足 |
| TaskInheritanceContextProvider | _get_past_tasks_async（過去タスク取得） | CLASS_IMPLEMENTATION_SPEC.md §4.5 | ✅ 充足 |
| TaskInheritanceContextProvider | _format_inheritance_data（データ整形） | CLASS_IMPLEMENTATION_SPEC.md §4.5 | ✅ 充足 |
| IMiddleware | intercept（処理インターセプト） | CLASS_IMPLEMENTATION_SPEC.md §5.1 | ✅ 充足 |
| CommentCheckMiddleware | intercept | CLASS_IMPLEMENTATION_SPEC.md §5.2 | ✅ 充足 |
| TokenUsageMiddleware | intercept | CLASS_IMPLEMENTATION_SPEC.md §5.3 | ✅ 充足 |
| ErrorHandlingMiddleware | intercept | CLASS_IMPLEMENTATION_SPEC.md §5.4 | ✅ 充足 |
| ExecutionEnvironmentManager | prepare_environments（環境作成） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | get_environment（環境取得） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | execute_command（コマンド実行） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | clone_repository（リポジトリクローン） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | cleanup_environments（環境クリーンアップ） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | save_environment_mapping（マッピング保存） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | load_environment_mapping（マッピングロード） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | stop_all_containers（コンテナ停止） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | start_all_containers（コンテナ起動） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| ExecutionEnvironmentManager | check_containers_exist（コンテナ存在確認） | CLASS_IMPLEMENTATION_SPEC.md §6.3 | ✅ 充足 |
| EnvironmentAnalyzer | detect_environment_files（環境ファイル検出） | CLASS_IMPLEMENTATION_SPEC.md §7.3 | ✅ 充足 |
| EnvironmentAnalyzer | analyze_environment_files（環境ファイル分析） | CLASS_IMPLEMENTATION_SPEC.md §7.3 | ✅ 充足 |
| PrePlanningManager | execute（計画前処理実行） | CLASS_IMPLEMENTATION_SPEC.md §8.3 | ✅ 充足 |
| PrePlanningManager | select_execution_environment（実行環境選択） | CLASS_IMPLEMENTATION_SPEC.md §8.3 | ✅ 充足 |
| MCPClient | connect（MCP接続） | CLASS_IMPLEMENTATION_SPEC.md §9.1 | ✅ 充足 |
| MCPClient | list_tools（ツール一覧取得） | CLASS_IMPLEMENTATION_SPEC.md §9.1 | ✅ 充足 |
| MCPClient | call_tool（ツール呼び出し） | CLASS_IMPLEMENTATION_SPEC.md §9.1 | ✅ 充足 |
| MCPClient | disconnect（切断） | CLASS_IMPLEMENTATION_SPEC.md §9.1 | ✅ 充足 |
| EnvironmentAwareMCPClient | call_tool（環境ID自動付与） | CLASS_IMPLEMENTATION_SPEC.md §9.2 | ✅ 充足 |
| TodoManagementTool | create_todo_list（Todoリスト作成） | CLASS_IMPLEMENTATION_SPEC.md §10.1 | ✅ 充足 |
| TodoManagementTool | sync_to_gitlab（GitLab同期） | CLASS_IMPLEMENTATION_SPEC.md §10.1 | ✅ 充足 |
| IssueToMRConverter | convert（Issue→MR変換） | CLASS_IMPLEMENTATION_SPEC.md §10.2 | ✅ 充足 |
| ProgressReporter | initialize（初期化） | CLASS_IMPLEMENTATION_SPEC.md §10.3 | ✅ 充足 |
| ProgressReporter | report_progress（進捗報告） | CLASS_IMPLEMENTATION_SPEC.md §10.3 | ✅ 充足 |
| ProgressReporter | finalize（完了処理） | CLASS_IMPLEMENTATION_SPEC.md §10.3 | ✅ 充足 |
| MermaidGraphRenderer | render（グラフレンダリング） | CLASS_IMPLEMENTATION_SPEC.md §10.4 | ✅ 充足 |
| ProgressCommentManager | create_progress_comment（進捗コメント作成） | CLASS_IMPLEMENTATION_SPEC.md §10.5 | ✅ 充足 |
| ProgressCommentManager | update_progress_comment（進捗コメント更新） | CLASS_IMPLEMENTATION_SPEC.md §10.5 | ✅ 充足 |
| GuidelineLearningAgent | invoke_async（ガイドライン学習処理） | CLASS_IMPLEMENTATION_SPEC.md §11（内部節番号10.4） | ✅ 充足 |

**補足: AUTOMATA_CODEX_SPEC.md に言及があるが CLASS_IMPLEMENTATION_SPEC.md に実装詳細の記載がないクラス**

| クラス名 | 備考 |
|---------|------|
| TodoManager | Agent Framework組み込みクラスの可能性があり記載不要の可能性が高い |
| AzureOpenAIChatClient | Agent Framework組み込みクラス。利用側の記載のみで充足 |
| BaseContextProvider | Agent Framework基底クラス。継承関係の記述でカバー済み |
| BaseHistoryProvider | Agent Framework基底クラス。同上 |
| ConfigManager | 設定管理クラス。AUTOMATA_CODEX_SPEC.md §14.2 に別途詳細記載あり |
| ContextStorageManager | Agent Framework組み込みクラス |
| FunctionTool | Agent Framework組み込みクラス |
| GitClient | GitLab API ラッパー。AUTOMATA_CODEX_SPEC.md §7 に詳細記載あり |
| GitLabClient | 同上 |
| MCPStdioTool | Agent Framework組み込みクラス |
| OpenAIChatClient | Agent Framework組み込みクラス |
| UserConfigClient | USER_MANAGEMENT_SPEC.md §6 に詳細記載あり |

---

## 5. エッジ整合性チェック表（input_keys / output_keys）

> **分析方針**: ワークフローコンテキストは累積型であるため、ターゲットエージェントの `input_keys` が「それ以前の全エージェントの `output_keys` の合算 + 初期システムキー（`task_context`, `branch_envs`, `plan_environment_id`）」に含まれているかを確認する。
>
> **凡例**: ✅ 問題なし / ⚠️ 条件付き（replanサイクル2周目以降で利用可能、初回は問題なし） / ❌ キー不足

### 5.1 standard_mr_processing エッジ整合性

| エッジ（from → to） | 条件 | ターゲットのinput_keys | 不足キー | 判定 |
|-------------------|----|---------------------|--------|------|
| user_resolve → task_classifier | なし | task_context | なし | ✅ |
| task_type_branch → code_generation_planning | task_type == 'code_generation' | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | previous_plan_result, replan_reason, user_new_comments, delta_requirements（2周目以降に利用可能） | ⚠️ |
| task_type_branch → bug_fix_planning | task_type == 'bug_fix' | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | 同上 | ⚠️ |
| task_type_branch → test_creation_planning | task_type == 'test_creation' | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | 同上 | ⚠️ |
| task_type_branch → documentation_planning | task_type == 'documentation' | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | previous_plan_result, replan_reason, user_new_comments, delta_requirements（2周目以降に利用可能） | ⚠️ |
| spec_check_branch → documentation_planning | spec_file_exists == false | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | 同上 | ⚠️ |
| exec_env_setup_code_gen → code_generation | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_bug_fix → bug_fix | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_test → test_creation | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_doc → documentation | なし | plan_result, task_context | なし | ✅ |
| code_generation → code_generation_reflection | なし | **execution_result**（単数）, plan_result, task_context, todo_list | **execution_result**（単数）※3: code_generationの出力は **execution_results**（複数） | ⚠️ ※3 |
| bug_fix → code_generation_reflection | なし | **execution_result**（単数）, plan_result, task_context, todo_list | 同上 ※3 | ⚠️ ※3 |
| code_gen_reflection_branch → code_generation | action == 're_execute' && task_type == 'code_generation' | plan_result, task_context | なし | ✅ |
| code_gen_reflection_branch → bug_fix | action == 're_execute' && task_type == 'bug_fix' | plan_result, task_context | なし | ✅ |
| test_creation → test_creation_reflection | なし | **execution_result**（単数）, plan_result, task_context, todo_list | **execution_result**（単数）※3: test_creationの出力は **execution_results**（複数） | ⚠️ ※3 |
| test_reflection_branch → test_creation | action == 're_execute' | plan_result, task_context | なし | ✅ |
| documentation → documentation_reflection | なし | **execution_result**（単数）, plan_result, task_context, todo_list | **execution_result**（単数）※3: documentationの出力は **execution_results**（複数） | ⚠️ ※3 |
| doc_reflection_branch → documentation | action == 're_execute' | plan_result, task_context | なし | ✅ |
| execution_type_branch → test_execution_evaluation | task_type in ['code_generation', 'bug_fix'] | execution_results（複数）, task_context | なし | ✅ |
| execution_type_branch → code_review | task_type == 'test_creation' | execution_results（複数）, task_context | なし | ✅ |
| execution_type_branch → documentation_review | task_type == 'documentation' | execution_results（複数）, task_context | なし | ✅ |
| test_execution_evaluation → code_review | なし | execution_results（複数）, task_context | なし | ✅ |
| code_review → plan_reflection | なし | **execution_result**（単数）, plan_result, review_result, task_context, todo_list, user_new_comments | **execution_result**（単数）※3（複数形が出力キー）、user_new_commentsは2周目以降 | ⚠️ ※3 |
| documentation_review → plan_reflection | なし | **execution_result**（単数）, plan_result, review_result, task_context, todo_list, user_new_comments | 同上 | ⚠️ ※3 |

### 5.2 multi_codegen_mr_processing エッジ整合性

| エッジ（from → to） | 条件 | ターゲットのinput_keys | 不足キー | 判定 |
|-------------------|----|---------------------|--------|------|
| user_resolve → task_classifier | なし | task_context | なし | ✅ |
| task_type_branch → code_generation_planning | task_type == 'code_generation' | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | previous_plan_result, replan_reason, user_new_comments, delta_requirements（2周目以降に利用可能） | ⚠️ |
| task_type_branch → bug_fix_planning | task_type == 'bug_fix' | 同上 | 同上 | ⚠️ |
| task_type_branch → test_creation_planning | task_type == 'test_creation' | 同上 | 同上 | ⚠️ |
| task_type_branch → documentation_planning | task_type == 'documentation' | 同上 | 同上 | ⚠️ |
| spec_check_branch → documentation_planning | spec_file_exists == false | task_context, classification_result, previous_plan_result, replan_reason, user_new_comments, delta_requirements | previous_plan_result, replan_reason, user_new_comments, delta_requirements（2周目以降） | ⚠️ |
| exec_env_setup_code_gen → code_generation_fast | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_code_gen → code_generation_standard | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_code_gen → code_generation_creative | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_bug_fix → bug_fix | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_test → test_creation | なし | plan_result, task_context | なし | ✅ |
| exec_env_setup_doc → documentation | なし | plan_result, task_context | なし | ✅ |
| code_generation_fast → code_review | なし | branch_envs, execution_results（複数）, task_context | なし | ✅ |
| code_generation_standard → code_review | なし | branch_envs, execution_results（複数）, task_context | なし | ✅ |
| code_generation_creative → code_review | なし | branch_envs, execution_results（複数）, task_context | なし | ✅ |
| bug_fix → code_generation_reflection | なし | execution_result（単数）, plan_result, task_context, todo_list | なし（bug_fixのoutputも単数で一致） | ✅ |
| code_gen_reflection_branch → bug_fix | action == 're_execute' | plan_result, task_context | なし | ✅ |
| test_creation → test_creation_reflection | なし | execution_result（単数）, plan_result, task_context, todo_list | なし（test_creationのoutputも単数で一致） | ✅ |
| test_reflection_branch → test_creation | action == 're_execute' | plan_result, task_context | なし | ✅ |
| documentation → documentation_reflection | なし | execution_result（単数）, plan_result, task_context, todo_list | なし（documentationのoutputも単数で一致） | ✅ |
| doc_reflection_branch → documentation | action == 're_execute' | plan_result, task_context | なし | ✅ |
| execution_type_branch → test_execution_evaluation | task_type == 'bug_fix' | execution_result（単数）, task_context | なし | ✅ |
| execution_type_branch → code_review | task_type in ['test_creation', 'code_generation'] | branch_envs, execution_results（複数）, task_context | なし | ✅ |
| execution_type_branch → documentation_review | task_type == 'documentation' | execution_result（単数）, task_context | なし | ✅ |
| test_execution_evaluation → code_review | なし | branch_envs, execution_results（複数）, task_context | なし | ✅ |
| branch_merge_executor → plan_reflection | なし | execution_result（単数）, plan_result, review_result, task_context, todo_list, user_new_comments | user_new_commentsは2周目以降 | ⚠️ |
| documentation_review → plan_reflection | なし | execution_result（単数）, plan_result, review_result, task_context, todo_list, user_new_comments | user_new_commentsは2周目以降 | ⚠️ |

---

## 6. プロンプトID整合性チェック表

| プロンプトID | PROMPTS.md | standard_prompts.json | multi_prompts.json | PROMPT_DEFINITION_SPEC.md | 判定 |
|------------|-----------|---------------------|-----------------|--------------------------|------|
| task_classifier | ✅ §1 | ✅ | ✅ | ✅ | 問題なし |
| code_generation_planning | ✅ §2 | ✅ | ✅ | ✅ | 問題なし |
| bug_fix_planning | ✅ §3 | ✅ | ✅ | ✅ | 問題なし |
| test_creation_planning | ✅ §4 | ✅ | ✅ | ✅ | 問題なし |
| documentation_planning | ✅ §5 | ✅ | ✅ | ✅ | 問題なし |
| plan_reflection | ✅ §6 | ✅ | ✅ | ✅ | 問題なし |
| code_generation | ✅ §7 | ✅ | ❌（multi専用なし） | ✅ | 問題なし（意図的） |
| bug_fix | ✅ §8 | ✅ | ✅ | ✅ | 問題なし |
| documentation | ✅ §9 | ✅ | ✅ | ✅ | 問題なし |
| test_creation | ✅ §10 | ✅ | ✅ | ✅ | 問題なし |
| test_execution_evaluation | ✅ §11 | ✅ | ✅ | ✅ | 問題なし |
| code_review | ✅ §12 | ✅ | ❌（multi専用なし） | ✅ | 問題なし（意図的） |
| documentation_review | ✅ §13 | ✅ | ✅ | ✅ | 問題なし |
| code_generation_reflection | ✅ §14 | ✅ | ✅ | ✅ | 問題なし |
| test_creation_reflection | ✅ §15 | ✅ | ✅ | ✅ | 問題なし |
| documentation_reflection | ✅ §16 | ✅ | ✅ | ✅ | 問題なし |
| code_generation_fast | ✅ §17 | ❌（standard専用なし） | ✅ | ✅ | 問題なし（意図的） |
| code_generation_standard | ✅ §18 | ❌（standard専用なし） | ✅ | ✅ | 問題なし（意図的） |
| code_generation_creative | ✅ §19 | ❌（standard専用なし） | ✅ | ✅ | 問題なし（意図的） |
| code_review_multi | ✅ §20 | ❌（standard専用なし） | ✅ | ✅ | 問題なし（意図的） |

**補足**: `multi_codegen_mr_processing_agents.json` の `code_review` エージェントは `prompt_id = "code_review_multi"` を使用しており、`agent_id` と `prompt_id` が意図的に異なる設計。`AGENT_DEFINITION_SPEC.md §4.2` に明記されており問題なし。

---

## 7. 検出した矛盾・問題の詳細一覧

### ※1【重大度: 中】AUTOMATA_CODEX_SPEC.md の節番号重複

- **発生箇所**: `docs/AUTOMATA_CODEX_SPEC.md`
- **具体的な内容**:
  - 節 `8.3` が2つ存在する（「8.3 Agent Framework標準Providerのカスタム実装」と「8.3 会話履歴管理」）
  - 節 `9.3` が2つ存在する（「9.3 ツール一覧」と「9.3 エラーハンドリングフロー」）
  - 節 `9.4` が2つ存在する（「9.4 Tool実行フロー」と「9.4 エラー通知」）
  - 章 `10` の内部に、本来 `10.x` であるべき節番号が `9.x` として記述されている（「9.3 エラーハンドリングフロー」「9.4 エラー通知」は本来 `10.3` / `10.4` に相当）
- **影響**: 参照時の混乱。他ドキュメントから節番号を引用した際に誤った節を参照する可能性がある

---

### ※2【重大度: 中】AGENT_DEFINITION_SPEC.md の `metadata` フィールドが仕様表に未記載

- **発生箇所**:
  - 仕様書: `docs/AGENT_DEFINITION_SPEC.md §3.2`（エージェントノード定義フィールド表）
  - JSON: `docs/definitions/standard_mr_processing_agents.json`、`docs/definitions/multi_codegen_mr_processing_agents.json`
- **具体的な内容**:
  - `AGENT_DEFINITION_SPEC.md §3.2` のフィールド表には `id`, `role`, `input_keys`, `output_keys`, `mcp_servers`, `prompt_id`, `max_iterations`, `timeout_seconds`, `description` の9フィールドが記載されている
  - 実際のJSONファイルでは、`code_generation_planning`, `bug_fix_planning`, `test_creation_planning`, `documentation_planning` の各エージェントに `metadata` フィールドが存在し、`metadata.todo_list_strategy` などが定義されている
  - この `metadata` フィールドは仕様書のフィールド表に一切記載がない
- **影響**: 実装者が `metadata` フィールドの存在・意味・利用方法を仕様書から把握できない

---

### ※3【重大度: 高】`execution_result`（単数）vs `execution_results`（複数）のキー名不統一

- **発生箇所**:
  - 仕様書: `docs/AGENT_DEFINITION_SPEC.md §5`（コンテキストキー一覧）
  - JSON: `docs/definitions/standard_mr_processing_agents.json`、`docs/definitions/multi_codegen_mr_processing_agents.json`
- **具体的な内容**:

  **仕様書の定義**:
  `AGENT_DEFINITION_SPEC.md §5` では `execution_results`（複数・辞書型 `Dict[str, ExecutionResult]`）を全実行エージェントが出力するとして定義している

  **standardフローでの不一致**:
  | エージェントID | フィールド | キー名 | 仕様との整合 |
  |-------------|---------|-------|------------|
  | code_generation | output_keys | execution_results（複数）| ✅ 一致 |
  | bug_fix | output_keys | execution_results（複数）| ✅ 一致 |
  | test_creation | output_keys | execution_results（複数）| ✅ 一致 |
  | documentation | output_keys | execution_results（複数）| ✅ 一致 |
  | code_generation_reflection | input_keys | **execution_result（単数）**| ❌ 不一致（前段の出力は複数形） |
  | test_creation_reflection | input_keys | **execution_result（単数）**| ❌ 不一致（前段の出力は複数形） |
  | documentation_reflection | input_keys | **execution_result（単数）**| ❌ 不一致（前段の出力は複数形） |
  | plan_reflection | input_keys | **execution_result（単数）**| ❌ 不一致（前段の出力は複数形） |

  **multi_codegenフローでの不一致**:
  | エージェントID | フィールド | キー名 | 仕様との整合 |
  |-------------|---------|-------|------------|
  | code_generation_fast | output_keys | execution_results（複数）| ✅ 一致 |
  | code_generation_standard | output_keys | execution_results（複数）| ✅ 一致 |
  | code_generation_creative | output_keys | execution_results（複数）| ✅ 一致 |
  | bug_fix | output_keys | **execution_result（単数）**| ❌ 仕様書では複数形と定義 |
  | test_creation | output_keys | **execution_result（単数）**| ❌ 仕様書では複数形と定義 |
  | documentation | output_keys | **execution_result（単数）**| ❌ 仕様書では複数形と定義 |
  | documentation_review | input_keys | execution_result（単数）| bug/test/docの出力と一致するが仕様と矛盾 |
  | test_execution_evaluation | input_keys | execution_result（単数）| 同上 |
  | code_generation_reflection | input_keys | execution_result（単数）| bug_fixの出力と一致 |
  | test_creation_reflection | input_keys | execution_result（単数）| test_creationの出力と一致 |
  | documentation_reflection | input_keys | execution_result（単数）| documentationの出力と一致 |

- **実装への影響**:
  - standardフロー: `code_generation` / `bug_fix` / `test_creation` / `documentation` が `execution_results`（複数）を出力するが、後続の `code_generation_reflection` / `test_creation_reflection` / `documentation_reflection` は `execution_result`（単数）を入力として期待しているため、実行時にキー解決エラーが発生する危険がある
  - AGENT_DEFINITION_SPEC.md §5 の定義（全実行エージェントが複数形を使う）と、multi_codegenのbug_fix等の実装（単数形を出力）が矛盾している

---

### ※4【重大度: 低】STANDARD_MR_PROCESSING_FLOW.md のフロー図に `Complete{完了?}` ノードが存在するが JSON には対応ノードがない

- **発生箇所**:
  - フロー図: `docs/STANDARD_MR_PROCESSING_FLOW.md §3`（MermaidフローのCompleteノード）
  - JSON: `docs/definitions/standard_mr_processing_graph.json`
- **具体的な内容**:
  - STANDARD_MR_PROCESSING_FLOW.md のMermaidフロー図に `Complete{完了?}` ノードが描かれているが、`standard_mr_processing_graph.json` にはこのIDのノードが存在しない
  - JSONでは `replan_branch` が直接「proceed → null（終了）」の分岐を担っており、概念的には同等の処理をしている
- **影響**: フロー図とJSONの厳密な対応が取れておらず、フロー図がやや簡略化された説明になっている

---

### ※5【重大度: 低】MULTI_MR_PROCESSING_FLOW.md のフロー図で replan終了パスの表現がJSONと不一致

- **発生箇所**:
  - フロー図: `docs/MULTI_MR_PROCESSING_FLOW.md §3`（MermaidフローのReplanCheck周辺）
  - JSON: `docs/definitions/multi_codegen_mr_processing_graph.json`
- **具体的な内容**:
  - MULTI_MR_PROCESSING_FLOW.md のフロー図では「No 問題なし/軽微」のエッジが `execution_type_branch` へのエッジとしてまとめて描かれている
  - `multi_codegen_mr_processing_graph.json` では「proceed → null（終了）」と「revise_plan && severity != critical → execution_type_branch」の2パターンに分かれている
  - 図の行163に "ExecTypeBranch -->|完了| End" があり、概念的には整合するが厳密には図の説明が不完全
- **影響**: フロー理解の際にJSONを別途参照しなければ正確な分岐条件が把握できない

---

### ※6【重大度: 低】CLASS_IMPLEMENTATION_SPEC.md §11 内の節番号が 10.x 番台になっている

- **発生箇所**: `docs/CLASS_IMPLEMENTATION_SPEC.md §11`（GuidelineLearningAgent）
- **具体的な内容**:
  - 章番号は `11. GuidelineLearningAgent` であるにもかかわらず、内部の節番号が `10.1 概要`、`10.2 継承関係`、`10.3 保持データ`、`10.4 invoke_async の処理フロー`、`10.5 例外的なgit操作の許可` となっている
  - 正しくは `11.1〜11.5` であるべき
- **影響**: 他ドキュメントから節番号を参照した際に誤った節を参照する可能性がある

---

### ※7【重大度: 低】AGENT_DEFINITION_SPEC.md §4.2 の「継承」説明とJSONファイルの実態の乖離

- **発生箇所**:
  - 仕様書: `docs/AGENT_DEFINITION_SPEC.md §4.2`
  - JSON: `docs/definitions/multi_codegen_mr_processing_agents.json`
- **具体的な内容**:
  - `AGENT_DEFINITION_SPEC.md §4.2` には「task_classifierからtest_execution_evaluationまで標準と共通の定義を継承し、以下を追加する」と記述されており、セクション4.2のJSON例には追加エージェント（code_generation_fast/standard/creative、code_review、plan_reflection）のみが掲載されている
  - しかし実際の `multi_codegen_mr_processing_agents.json` には全18エージェントの定義が含まれている（「継承」ではなく全定義を記述するフォーマット）
  - 「継承」が「論理的な意味での継承」なのか「実装上の継承機構」なのか明記されていない
- **影響**: 実装者が「継承」の実装方法を誤解する可能性がある

---

### ※8【重大度: 低】`TodoManager` が AUTOMATA_CODEX_SPEC.md に言及されているが CLASS_IMPLEMENTATION_SPEC.md に実装詳細がない

- **発生箇所**:
  - `docs/AUTOMATA_CODEX_SPEC.md`（TodoManagerへの言及）
  - `docs/CLASS_IMPLEMENTATION_SPEC.md`（TodoManagerの記載なし）
- **具体的な内容**:
  - `AUTOMATA_CODEX_SPEC.md` では `TodoManager` クラスが言及されているが、`CLASS_IMPLEMENTATION_SPEC.md` には `TodoManagementTool` クラスは定義されているが `TodoManager` の定義がない
  - `TodoManager` がAgent Framework組み込みクラスであれば記載不要だが、その旨が明記されていない
- **影響**: `TodoManager` の実装方法が不明確

---

## 8. 問題なし確認済み項目

| チェック項目 | 判定 |
|------------|------|
| 全エージェント（standard/multi共通16エージェント + multi専用2エージェント）のprompt_idがPROMPTS.mdに存在する | ✅ 問題なし |
| GRAPH_DEFINITION_SPEC.md のフィールド仕様と standard/multi_codegen _graph.json の実際フィールドが一致 | ✅ 問題なし |
| PROMPT_DEFINITION_SPEC.md のフィールド仕様と standard/multi_codegen _prompts.json の実際フィールドが一致 | ✅ 問題なし |
| CLASS_IMPLEMENTATION_SPEC.md の全クラス（32クラス）・全主要メソッドに実装情報（引数・戻り値・処理フロー）が記載されている | ✅ 問題なし |
| standard/multi_codegenフロー図の主要接続関係がそれぞれのJSONと整合している | ✅ 問題なし |
| DATABASE_SCHEMA_SPEC.md の主要14テーブルがAUTOMATA_CODEX_SPEC.md と整合している | ✅ 問題なし |
| USER_MANAGEMENT_SPEC.md のAPIエンドポイント定義とAUTOMATA_CODEX_SPEC.md §3の記述が整合している | ✅ 問題なし |
| AUTOMATA_CODEX_SPEC.md §4のエージェントノード一覧とAGENT_DEFINITION_SPEC.md §6の詳細説明が整合 | ✅ 問題なし |
| multi_codegen の code_review エージェントのprompt_id（code_review_multi）が意図的な設計であることがAGENT_DEFINITION_SPEC.md §4.2に明記されている | ✅ 問題なし |
| standard/multi_codegen の各フローにおいてreplanサイクル2周目以降のキー供給はplan_reflectionのoutput_keysが担保しており設計として整合している | ✅ 問題なし |
