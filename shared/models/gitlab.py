"""
GitLab エンティティドメインモデル定義

GitLab REST APIのレスポンスをPydanticモデルに変換するためのデータクラスを定義する。
GitLabClientクラスがAPIレスポンスをこれらのデータクラスに変換して返す。

AUTOMATA_CODEX_SPEC.md § 7.2（GitlabClientクラスの責務）に準拠する。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GitLabUser(BaseModel):
    """GitLab ユーザー情報（Issue/MRのアサイニーや作者として使用）"""

    id: int = Field(description="ユーザーID")
    username: str = Field(description="ユーザー名")
    name: str = Field(description="表示名")
    email: str | None = Field(default=None, description="メールアドレス")
    avatar_url: str | None = Field(default=None, description="アバター画像URL")
    web_url: str | None = Field(default=None, description="プロフィールURL")


class GitLabLabel(BaseModel):
    """GitLab ラベル情報"""

    id: int | None = Field(default=None, description="ラベルID")
    name: str = Field(description="ラベル名")
    color: str | None = Field(default=None, description="ラベルカラー（例: '#FF0000'）")
    description: str | None = Field(default=None, description="ラベルの説明")


class GitLabNote(BaseModel):
    """
    GitLab Note（コメント）

    Issue または MR に投稿されたコメント1件を表す。
    """

    id: int = Field(description="Note ID（GitLab APIのノートID）")
    body: str = Field(description="コメント本文")
    author: GitLabUser | None = Field(default=None, description="コメント投稿者")
    created_at: datetime | None = Field(default=None, description="投稿日時（UTC）")
    updated_at: datetime | None = Field(default=None, description="更新日時（UTC）")
    system: bool = Field(default=False, description="システム生成コメントかどうか")


class GitLabIssue(BaseModel):
    """
    GitLab Issue

    GitLab REST APIの `/projects/:id/issues/:iid` レスポンスを変換したデータクラス。
    GitLabClientクラスが Issue 操作メソッドの返り値として使用する。
    """

    iid: int = Field(description="Issue IID（プロジェクト内の通し番号）")
    title: str = Field(description="Issueタイトル")
    description: str = Field(default="", description="Issue説明文")
    project_id: int = Field(description="GitLabプロジェクトID")
    state: str = Field(
        default="opened", description="Issueの状態（opened / closed）"
    )
    labels: list[str] = Field(
        default_factory=list, description="付与されたラベル名のリスト"
    )
    assignees: list[GitLabUser] = Field(
        default_factory=list, description="アサインされたユーザーのリスト"
    )
    author: GitLabUser | None = Field(default=None, description="Issue作成者")
    web_url: str | None = Field(default=None, description="IssueのWebURL")
    created_at: datetime | None = Field(default=None, description="作成日時（UTC）")
    updated_at: datetime | None = Field(default=None, description="更新日時（UTC）")
    closed_at: datetime | None = Field(default=None, description="クローズ日時（UTC）")


class GitLabMergeRequest(BaseModel):
    """
    GitLab Merge Request

    GitLab REST APIの `/projects/:id/merge_requests/:iid` レスポンスを変換したデータクラス。
    GitLabClientクラスが MR 操作メソッドの返り値として使用する。
    """

    iid: int = Field(description="MR IID（プロジェクト内の通し番号）")
    title: str = Field(description="MRタイトル")
    description: str = Field(default="", description="MR説明文")
    project_id: int = Field(description="GitLabプロジェクトID")
    source_branch: str = Field(description="ソースブランチ名")
    target_branch: str = Field(description="ターゲットブランチ名")
    state: str = Field(
        default="opened",
        description="MRの状態（opened / closed / merged / locked）",
    )
    labels: list[str] = Field(
        default_factory=list, description="付与されたラベル名のリスト"
    )
    assignees: list[GitLabUser] = Field(
        default_factory=list, description="アサインされたユーザーのリスト"
    )
    author: GitLabUser | None = Field(default=None, description="MR作成者")
    web_url: str | None = Field(default=None, description="MRのWebURL")
    draft: bool = Field(default=False, description="ドラフトMRかどうか")
    merge_status: str | None = Field(
        default=None, description="マージ可能状態（can_be_merged 等）"
    )
    sha: str | None = Field(default=None, description="最新コミットのSHA")
    created_at: datetime | None = Field(default=None, description="作成日時（UTC）")
    updated_at: datetime | None = Field(default=None, description="更新日時（UTC）")
    merged_at: datetime | None = Field(default=None, description="マージ日時（UTC）")
    closed_at: datetime | None = Field(default=None, description="クローズ日時（UTC）")


class GitLabBranch(BaseModel):
    """
    GitLab ブランチ

    GitLab REST APIの `/projects/:id/repository/branches/:branch` レスポンスを変換したデータクラス。
    """

    name: str = Field(description="ブランチ名")
    commit_sha: str | None = Field(default=None, description="最新コミットのSHA")
    protected: bool = Field(default=False, description="保護ブランチかどうか")
    web_url: str | None = Field(default=None, description="ブランチのWebURL")


class GitLabCommit(BaseModel):
    """
    GitLab コミット

    GitLab REST APIの `/projects/:id/repository/commits/:sha` レスポンスを変換したデータクラス。
    """

    id: str = Field(description="コミットSHA（フルハッシュ）")
    short_id: str | None = Field(default=None, description="コミットSHA（短縮）")
    title: str | None = Field(default=None, description="コミットタイトル（1行目）")
    message: str | None = Field(default=None, description="コミットメッセージ（全文）")
    author_name: str | None = Field(default=None, description="コミット作成者名")
    author_email: str | None = Field(default=None, description="コミット作成者メール")
    authored_date: datetime | None = Field(default=None, description="コミット作成日時")
    committed_date: datetime | None = Field(default=None, description="コミット日時")
    web_url: str | None = Field(default=None, description="コミットのWebURL")


class GitLabDiff(BaseModel):
    """
    GitLab ファイル差分

    MR の差分情報1ファイル分を表す。
    """

    old_path: str = Field(description="変更前のファイルパス")
    new_path: str = Field(description="変更後のファイルパス")
    a_mode: str | None = Field(default=None, description="変更前のファイルモード")
    b_mode: str | None = Field(default=None, description="変更後のファイルモード")
    diff: str = Field(default="", description="unified diff形式の差分テキスト")
    new_file: bool = Field(default=False, description="新規ファイルかどうか")
    renamed_file: bool = Field(default=False, description="リネームされたファイルかどうか")
    deleted_file: bool = Field(default=False, description="削除されたファイルかどうか")
