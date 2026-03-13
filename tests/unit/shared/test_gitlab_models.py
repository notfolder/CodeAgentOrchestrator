"""
GitLab エンティティモデルの単体テスト

GitLabIssue・GitLabMergeRequest・GitLabNote・GitLabBranch・GitLabCommit・GitLabDiff等の
各Pydanticモデルについて、バリデーション成功・バリデーションエラー・シリアライズを検証する。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.gitlab import (
    GitLabBranch,
    GitLabCommit,
    GitLabDiff,
    GitLabIssue,
    GitLabLabel,
    GitLabMergeRequest,
    GitLabNote,
    GitLabUser,
)


# ========================================
# GitLabUser モデルのテスト
# ========================================


class TestGitLabUser:
    """GitLabUserモデルのテスト"""

    def test_正常なGitLabUserを作成できる(self) -> None:
        """正常なGitLabUserインスタンスを作成できることを確認する"""
        user = GitLabUser(
            id=1,
            username="john.doe",
            name="John Doe",
            email="john@example.com",
        )
        assert user.id == 1
        assert user.username == "john.doe"
        assert user.name == "John Doe"
        assert user.email == "john@example.com"

    def test_オプションフィールドを省略して作成できる(self) -> None:
        """省略可能なフィールドを指定せずにGitLabUserを作成できることを確認する"""
        user = GitLabUser(id=2, username="jane", name="Jane")
        assert user.email is None
        assert user.avatar_url is None
        assert user.web_url is None


# ========================================
# GitLabNote モデルのテスト
# ========================================


class TestGitLabNote:
    """GitLabNoteモデルのテスト"""

    def test_正常なGitLabNoteを作成できる(self) -> None:
        """正常なGitLabNoteインスタンスを作成できることを確認する"""
        note = GitLabNote(
            id=100,
            body="テストコメント",
        )
        assert note.id == 100
        assert note.body == "テストコメント"
        assert note.system is False

    def test_作者情報付きのGitLabNoteを作成できる(self) -> None:
        """作者情報を含むGitLabNoteを作成できることを確認する"""
        author = GitLabUser(id=1, username="author", name="Author")
        note = GitLabNote(
            id=200,
            body="レビューコメント",
            author=author,
            system=False,
        )
        assert note.author is not None
        assert note.author.username == "author"

    def test_システムコメントのGitLabNoteを作成できる(self) -> None:
        """システム生成コメントのGitLabNoteを作成できることを確認する"""
        note = GitLabNote(id=300, body="Branch was created", system=True)
        assert note.system is True


# ========================================
# GitLabIssue モデルのテスト
# ========================================


class TestGitLabIssue:
    """GitLabIssueモデルのテスト"""

    def test_正常なGitLabIssueを作成できる(self) -> None:
        """正常なGitLabIssueインスタンスを作成できることを確認する"""
        issue = GitLabIssue(
            iid=42,
            title="バグを修正してください",
            description="ログイン時にエラーが発生します",
            project_id=100,
        )
        assert issue.iid == 42
        assert issue.title == "バグを修正してください"
        assert issue.project_id == 100
        assert issue.state == "opened"
        assert issue.labels == []
        assert issue.assignees == []

    def test_ラベルとアサイニー付きのGitLabIssueを作成できる(self) -> None:
        """ラベルとアサイニーを含むGitLabIssueを作成できることを確認する"""
        assignee = GitLabUser(id=1, username="dev", name="Developer")
        issue = GitLabIssue(
            iid=1,
            title="新機能の実装",
            project_id=200,
            labels=["coding agent", "feature"],
            assignees=[assignee],
        )
        assert "coding agent" in issue.labels
        assert len(issue.assignees) == 1
        assert issue.assignees[0].username == "dev"

    def test_closedステータスのGitLabIssueを作成できる(self) -> None:
        """closedステータスのGitLabIssueを作成できることを確認する"""
        issue = GitLabIssue(
            iid=10,
            title="完了済みIssue",
            project_id=300,
            state="closed",
        )
        assert issue.state == "closed"

    def test_descriptionのデフォルトが空文字列(self) -> None:
        """descriptionのデフォルト値が空文字列であることを確認する"""
        issue = GitLabIssue(iid=5, title="タイトルのみ", project_id=100)
        assert issue.description == ""

    def test_GitLabIssueのシリアライズが正しく動作する(self) -> None:
        """model_dump()でGitLabIssueが正しくシリアライズされることを確認する"""
        issue = GitLabIssue(
            iid=42,
            title="テストIssue",
            project_id=100,
            labels=["bug"],
        )
        data = issue.model_dump()
        assert data["iid"] == 42
        assert data["title"] == "テストIssue"
        assert "bug" in data["labels"]

    def test_IssueToMRConverterで使用するフィールドが存在する(self) -> None:
        """IssueToMRConverterが必要とするフィールドがGitLabIssueに存在することを確認する"""
        issue = GitLabIssue(
            iid=99,
            title="テスト",
            description="テスト説明",
            project_id=1,
            labels=["coding agent"],
            assignees=[GitLabUser(id=1, username="user", name="User")],
        )
        # IssueToMRConverter.convert()が使用するフィールドを確認
        assert hasattr(issue, "iid")
        assert hasattr(issue, "title")
        assert hasattr(issue, "description")
        assert hasattr(issue, "project_id")
        assert hasattr(issue, "labels")
        assert hasattr(issue, "assignees")


# ========================================
# GitLabMergeRequest モデルのテスト
# ========================================


class TestGitLabMergeRequest:
    """GitLabMergeRequestモデルのテスト"""

    def test_正常なGitLabMergeRequestを作成できる(self) -> None:
        """正常なGitLabMergeRequestインスタンスを作成できることを確認する"""
        mr = GitLabMergeRequest(
            iid=5,
            title="Draft: バグ修正",
            description="Issue #42から自動生成",
            project_id=100,
            source_branch="issue-42",
            target_branch="main",
        )
        assert mr.iid == 5
        assert mr.title == "Draft: バグ修正"
        assert mr.source_branch == "issue-42"
        assert mr.target_branch == "main"
        assert mr.state == "opened"
        assert mr.draft is False

    def test_ドラフトMRを作成できる(self) -> None:
        """ドラフトMRを作成できることを確認する"""
        mr = GitLabMergeRequest(
            iid=10,
            title="Draft: 新機能",
            project_id=100,
            source_branch="feature-branch",
            target_branch="main",
            draft=True,
        )
        assert mr.draft is True

    def test_ラベルとアサイニー付きのMRを作成できる(self) -> None:
        """ラベルとアサイニーを含むMRを作成できることを確認する"""
        assignee = GitLabUser(id=1, username="reviewer", name="Reviewer")
        mr = GitLabMergeRequest(
            iid=20,
            title="機能追加",
            project_id=200,
            source_branch="feat/add-feature",
            target_branch="develop",
            labels=["coding agent", "enhancement"],
            assignees=[assignee],
        )
        assert len(mr.labels) == 2
        assert "coding agent" in mr.labels
        assert mr.assignees[0].username == "reviewer"

    def test_mergedステータスのMRを作成できる(self) -> None:
        """mergedステータスのMRを作成できることを確認する"""
        mr = GitLabMergeRequest(
            iid=30,
            title="マージ済みMR",
            project_id=100,
            source_branch="old-branch",
            target_branch="main",
            state="merged",
        )
        assert mr.state == "merged"

    def test_GitLabMergeRequestのシリアライズが正しく動作する(self) -> None:
        """model_dump()でGitLabMergeRequestが正しくシリアライズされることを確認する"""
        mr = GitLabMergeRequest(
            iid=5,
            title="テストMR",
            project_id=100,
            source_branch="issue-1",
            target_branch="main",
        )
        data = mr.model_dump()
        assert data["iid"] == 5
        assert data["source_branch"] == "issue-1"
        assert data["target_branch"] == "main"

    def test_IssueToMRConverterで使用するフィールドが存在する(self) -> None:
        """IssueToMRConverterが返り値として使用するフィールドがGitLabMergeRequestに存在することを確認する"""
        mr = GitLabMergeRequest(
            iid=99,
            title="Draft: テスト",
            project_id=1,
            source_branch="issue-99",
            target_branch="main",
        )
        # IssueToMRConverter.convert()の返り値として使用するフィールドを確認
        assert hasattr(mr, "iid")
        assert hasattr(mr, "title")
        assert hasattr(mr, "description")
        assert hasattr(mr, "project_id")
        assert hasattr(mr, "source_branch")
        assert hasattr(mr, "target_branch")
        assert hasattr(mr, "labels")
        assert hasattr(mr, "assignees")
        assert hasattr(mr, "state")


# ========================================
# GitLabBranch モデルのテスト
# ========================================


class TestGitLabBranch:
    """GitLabBranchモデルのテスト"""

    def test_正常なGitLabBranchを作成できる(self) -> None:
        """正常なGitLabBranchインスタンスを作成できることを確認する"""
        branch = GitLabBranch(
            name="issue-42",
            commit_sha="abc123def456",
        )
        assert branch.name == "issue-42"
        assert branch.commit_sha == "abc123def456"
        assert branch.protected is False

    def test_保護ブランチを作成できる(self) -> None:
        """保護ブランチのGitLabBranchを作成できることを確認する"""
        branch = GitLabBranch(name="main", protected=True)
        assert branch.protected is True

    def test_オプションフィールド省略で作成できる(self) -> None:
        """省略可能なフィールドを指定せずにGitLabBranchを作成できることを確認する"""
        branch = GitLabBranch(name="feature-branch")
        assert branch.commit_sha is None
        assert branch.web_url is None


# ========================================
# GitLabCommit モデルのテスト
# ========================================


class TestGitLabCommit:
    """GitLabCommitモデルのテスト"""

    def test_正常なGitLabCommitを作成できる(self) -> None:
        """正常なGitLabCommitインスタンスを作成できることを確認する"""
        commit = GitLabCommit(
            id="abc123def456abc123def456abc123def456abc1",
            short_id="abc123de",
            title="Initial commit for issue #42",
            message="Initial commit for issue #42\n\nAuto-generated by AutomataCodex",
            author_name="AutomataBot",
            author_email="bot@example.com",
        )
        assert commit.id == "abc123def456abc123def456abc123def456abc1"
        assert commit.short_id == "abc123de"
        assert commit.author_name == "AutomataBot"

    def test_最小フィールドでGitLabCommitを作成できる(self) -> None:
        """最小限のフィールドでGitLabCommitを作成できることを確認する"""
        commit = GitLabCommit(id="abc123")
        assert commit.id == "abc123"
        assert commit.title is None
        assert commit.message is None


# ========================================
# GitLabDiff モデルのテスト
# ========================================


class TestGitLabDiff:
    """GitLabDiffモデルのテスト"""

    def test_正常なGitLabDiffを作成できる(self) -> None:
        """正常なGitLabDiffインスタンスを作成できることを確認する"""
        diff = GitLabDiff(
            old_path="src/main.py",
            new_path="src/main.py",
            diff="@@ -1,3 +1,4 @@\n print('hello')\n+print('world')",
        )
        assert diff.old_path == "src/main.py"
        assert diff.new_path == "src/main.py"
        assert diff.new_file is False
        assert diff.deleted_file is False

    def test_新規ファイルのGitLabDiffを作成できる(self) -> None:
        """新規ファイルのGitLabDiffを作成できることを確認する"""
        diff = GitLabDiff(
            old_path="/dev/null",
            new_path="src/new_file.py",
            new_file=True,
            diff="@@ -0,0 +1,5 @@\n+# New file\n",
        )
        assert diff.new_file is True

    def test_削除ファイルのGitLabDiffを作成できる(self) -> None:
        """削除ファイルのGitLabDiffを作成できることを確認する"""
        diff = GitLabDiff(
            old_path="src/old_file.py",
            new_path="/dev/null",
            deleted_file=True,
            diff="@@ -1,5 +0,0 @@\n-# Deleted file\n",
        )
        assert diff.deleted_file is True


# ========================================
# GitLabLabel モデルのテスト
# ========================================


class TestGitLabLabel:
    """GitLabLabelモデルのテスト"""

    def test_正常なGitLabLabelを作成できる(self) -> None:
        """正常なGitLabLabelインスタンスを作成できることを確認する"""
        label = GitLabLabel(
            id=1,
            name="coding agent",
            color="#0075ca",
            description="コーディングエージェント対象ラベル",
        )
        assert label.id == 1
        assert label.name == "coding agent"
        assert label.color == "#0075ca"

    def test_IDなしのGitLabLabelを作成できる(self) -> None:
        """IDなしのGitLabLabelを作成できることを確認する（ラベル名のみの場合）"""
        label = GitLabLabel(name="bug")
        assert label.name == "bug"
        assert label.id is None
