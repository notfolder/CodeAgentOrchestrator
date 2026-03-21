"""
タスク関連ドメインモデル定義

Producer/ConsumerパターンでRabbitMQを経由するタスクデータ、
および各エージェントステップ間でやり取りするコンテキストデータのモデルを定義する。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class Task(BaseModel):
    """
    タスクモデル

    Producer がキューに投入し、Consumer が処理するタスクのデータ構造。
    GitLab の Issue または Merge Request を1タスクとして表す。
    """

    task_uuid: str = Field(description="タスクの一意識別子（UUID）")
    task_type: Literal["issue", "merge_request"] = Field(
        description="タスク種別（issue / merge_request）"
    )
    project_id: int = Field(description="GitLabプロジェクトID")
    issue_iid: int | None = Field(
        default=None, description="Issue IID（Issueタスクの場合）"
    )
    mr_iid: int | None = Field(default=None, description="MR IID（MRタスクの場合）")
    username: str | None = Field(
        default=None, description="タスク実行ユーザーのGitLabユーザー名"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="タスク作成日時（UTC）",
    )


class TaskContext(BaseModel):
    """
    タスクコンテキスト

    ワークフロー全体を通じて共有されるタスク共通情報。
    TaskContextInitExecutor がワークフローコンテキストへ転写し、各エージェントが参照する。
    """

    task_uuid: str = Field(description="タスクの一意識別子")
    task_type: Literal["issue", "merge_request"] = Field(description="タスク種別")
    project_id: int = Field(description="GitLabプロジェクトID")
    issue_iid: int | None = Field(default=None, description="Issue IID")
    mr_iid: int | None = Field(default=None, description="MR IID")
    original_branch: str | None = Field(default=None, description="元のブランチ名")
    assigned_branch: str | None = Field(
        default=None, description="割り当てられたブランチ名"
    )
    user_id: int | None = Field(default=None, description="GitLabユーザーID")
    username: str | None = Field(default=None, description="GitLabユーザー名")
    openai_api_key: str | None = Field(
        default=None, description="ユーザー固有のOpenAI APIキー"
    )
    workflow_definition_id: int | None = Field(
        default=None, description="使用するワークフロー定義ID"
    )
    cached_user_config: Any | None = Field(
        default=None,
        description="キャッシュ済みユーザー設定（重複HTTPフェッチ防止用）",
        exclude=True,
    )


class ClassificationResult(BaseModel):
    """
    タスク分類結果

    task_classifier エージェントが出力するタスク種別の分類結果。
    """

    task_type: Literal[
        "code_generation", "bug_fix", "test_creation", "documentation"
    ] = Field(description="タスク種別")
    confidence: float = Field(
        ge=0.0, le=1.0, description="分類の信頼度スコア（0.0〜1.0）"
    )
    reasoning: str = Field(description="分類の根拠説明")
    related_files: list[str] = Field(
        default_factory=list, description="関連する可能性のあるファイルパスリスト"
    )
    spec_file_exists: bool = Field(
        default=False, description="仕様書ファイルの存在フラグ"
    )
    spec_file_path: str | None = Field(default=None, description="仕様書ファイルのパス")


class PlanAction(BaseModel):
    """実行計画の個別アクション"""

    id: str = Field(description="アクションID")
    description: str = Field(description="アクションの説明")
    agent: str = Field(description="実行エージェント名")
    tool: str = Field(description="使用するツール名")
    target_file: str | None = Field(default=None, description="対象ファイルパス")
    acceptance_criteria: str | None = Field(default=None, description="受入基準")


class PlanResult(BaseModel):
    """
    実行計画結果

    planning エージェントが出力する実行計画。
    """

    plan_id: str = Field(description="計画ID（UUID）")
    task_summary: str | None = Field(default=None, description="タスクの簡潔な説明")
    bug_summary: str | None = Field(
        default=None, description="バグの簡潔な説明（バグ修正タスク）"
    )
    files_to_create: list[str] = Field(
        default_factory=list, description="新規作成するファイルパスリスト"
    )
    files_to_modify: list[str] = Field(
        default_factory=list, description="変更するファイルパスリスト"
    )
    actions: list[PlanAction] = Field(
        default_factory=list, description="実行アクションのリスト"
    )
    estimated_complexity: str | None = Field(
        default=None, description="複雑度の見積もり（low/medium/high）"
    )
    dependencies: list[str] = Field(default_factory=list, description="依存関係リスト")
    risks: list[str] = Field(default_factory=list, description="リスクリスト")
    spec_file_exists: bool = Field(
        default=False, description="仕様書ファイルの存在フラグ"
    )
    estimated_duration_minutes: int | None = Field(
        default=None, description="推定所要時間（分）"
    )


class ExecutionResult(BaseModel):
    """
    実行結果

    execution エージェントが出力する実行結果。
    execution_results 辞書のエージェント定義IDをキーとした値として格納する。
    """

    environment_id: str = Field(description="使用した実行環境ID")
    branch_name: str = Field(description="作業したブランチ名")
    changed_files: list[str] = Field(
        default_factory=list, description="変更したファイルパスのリスト"
    )
    summary: str = Field(description="実行内容のサマリー")
    todo_status: dict[str, str] = Field(
        default_factory=dict, description="Todo IDと状態のマッピング"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="実行完了時刻（UTC）",
    )


class SelectedImplementation(BaseModel):
    """
    選択された実装情報

    multi_codegen_mr_processing において code_review エージェントが
    最良の実装を選択した際の結果。
    """

    environment_id: str = Field(description="選択された実行環境ID")
    branch_name: str = Field(description="選択されたブランチ名")
    selection_reason: str = Field(description="選択理由の詳細説明")
    quality_score: float = Field(ge=0.0, le=1.0, description="品質スコア（0.0〜1.0）")
    evaluation_details: dict[str, Any] = Field(
        default_factory=dict, description="評価の詳細情報"
    )


class ReviewIssue(BaseModel):
    """レビュー指摘事項"""

    severity: Literal["critical", "major", "minor", "suggestion"] = Field(
        description="重要度"
    )
    file: str | None = Field(default=None, description="指摘対象ファイルパス")
    line: int | None = Field(default=None, description="指摘対象行番号")
    description: str = Field(description="指摘内容")
    suggestion: str | None = Field(default=None, description="改善提案")


class ReviewResult(BaseModel):
    """
    レビュー結果

    review エージェントが出力するレビュー結果。
    """

    status: Literal["approved", "changes_requested", "needs_work"] = Field(
        description="レビュー結果ステータス"
    )
    issues: list[ReviewIssue] = Field(
        default_factory=list, description="指摘事項リスト"
    )
    summary: str = Field(description="レビューのサマリー")
    suggested_actions: list[str] = Field(
        default_factory=list, description="推奨アクションリスト"
    )


class ReflectionResult(BaseModel):
    """
    プラン検証結果

    plan_reflection エージェントが出力する計画の検証結果。
    """

    action: Literal["proceed", "revise_plan", "abort"] = Field(
        description="次のアクション（proceed: 続行 / revise_plan: 計画修正 / abort: 中止）"
    )
    status: Literal["success", "needs_revision", "needs_replan"] = Field(
        description="検証ステータス"
    )
    issues: list[str] = Field(default_factory=list, description="検出された問題リスト")
    suggestions: list[str] = Field(default_factory=list, description="改善提案リスト")
    confidence: float = Field(
        ge=0.0, le=1.0, description="検証結果の信頼度スコア（0.0〜1.0）"
    )


class ExecutionReflectionResult(BaseModel):
    """
    実行リフレクション結果

    execution reflection エージェントが出力するコード生成・テスト・ドキュメント検証結果。
    """

    action: Literal["proceed", "revise", "abort"] = Field(
        description="次のアクション（proceed: 続行 / revise: 修正 / abort: 中止）"
    )
    status: Literal["success", "needs_revision", "failed"] = Field(
        description="検証ステータス"
    )
    issues: list[str] = Field(default_factory=list, description="検出された問題リスト")
    suggestions: list[str] = Field(default_factory=list, description="改善提案リスト")
    confidence: float = Field(
        ge=0.0, le=1.0, description="検証結果の信頼度スコア（0.0〜1.0）"
    )


class TodoItem(BaseModel):
    """Todoリストの1項目"""

    id: str = Field(description="Todo項目ID")
    description: str = Field(description="Todo項目の説明")
    status: Literal["pending", "in_progress", "completed", "skipped"] = Field(
        default="pending", description="ステータス"
    )
    acceptance_criteria: str | None = Field(default=None, description="受入基準")


class TodoList(BaseModel):
    """
    Todoリスト

    planning エージェントが作成し、execution エージェントが更新する進捗管理リスト。
    """

    items: list[TodoItem] = Field(default_factory=list, description="Todo項目リスト")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="作成日時（UTC）",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="更新日時（UTC）",
    )
