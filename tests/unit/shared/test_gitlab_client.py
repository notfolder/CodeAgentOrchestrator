"""
GitLabクライアントの単体テスト

python-gitlabライブラリをモックしてGitlabClientの各メソッドを検証する。
Issue取得・MR作成・コメント投稿・ブランチ操作・レート制限エラー時の自動リトライ動作を検証する。
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, call, patch

import gitlab
import gitlab.exceptions
import pytest

from gitlab_client.gitlab_client import (
    GitlabClient,
    _MAX_RETRIES,
    _exponential_backoff,
    _issue_from_obj,
    _mr_from_obj,
    _note_from_obj,
    _user_from_dict,
)
from models.gitlab import (
    GitLabBranch,
    GitLabCommit,
    GitLabIssue,
    GitLabMergeRequest,
    GitLabNote,
    GitLabUser,
)


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def mock_gitlab_instance() -> MagicMock:
    """モックgitlabインスタンスを返す"""
    return MagicMock()


@pytest.fixture
def client(mock_gitlab_instance: MagicMock) -> GitlabClient:
    """テスト用GitlabClientを返す（python-gitlabをモック）"""
    with patch("gitlab_client.gitlab_client.gitlab.Gitlab", return_value=mock_gitlab_instance):
        return GitlabClient(url="https://gitlab.example.com", pat="test-pat")


@pytest.fixture
def mock_project(mock_gitlab_instance: MagicMock) -> MagicMock:
    """モックプロジェクトオブジェクトを返す"""
    project = MagicMock()
    mock_gitlab_instance.projects.get.return_value = project
    return project


def _make_issue_obj(
    iid: int = 1,
    title: str = "テストIssue",
    description: str = "説明",
    project_id: int = 100,
    state: str = "opened",
    labels: list[str] | None = None,
    assignees: list[dict[str, Any]] | None = None,
    author: dict[str, Any] | None = None,
    web_url: str | None = "https://gitlab.example.com/group/project/-/issues/1",
) -> MagicMock:
    """モックIssueオブジェクトを生成する"""
    obj = MagicMock()
    obj.iid = iid
    obj.title = title
    obj.description = description
    obj.project_id = project_id
    obj.state = state
    obj.labels = labels or []
    obj.assignees = assignees or []
    obj.author = author or {"id": 1, "username": "author", "name": "Author"}
    obj.web_url = web_url
    obj.created_at = None
    obj.updated_at = None
    obj.closed_at = None
    return obj


def _make_mr_obj(
    iid: int = 1,
    title: str = "Draft: テストMR",
    description: str = "",
    project_id: int = 100,
    source_branch: str = "issue-1",
    target_branch: str = "main",
    state: str = "opened",
    labels: list[str] | None = None,
) -> MagicMock:
    """モックMergeRequestオブジェクトを生成する"""
    obj = MagicMock()
    obj.iid = iid
    obj.title = title
    obj.description = description
    obj.project_id = project_id
    obj.source_branch = source_branch
    obj.target_branch = target_branch
    obj.state = state
    obj.labels = labels or []
    obj.assignees = []
    obj.author = {"id": 1, "username": "author", "name": "Author"}
    obj.web_url = f"https://gitlab.example.com/group/project/-/merge_requests/{iid}"
    obj.draft = False
    obj.work_in_progress = False
    obj.merge_status = "can_be_merged"
    obj.sha = "abc123"
    obj.created_at = None
    obj.updated_at = None
    obj.merged_at = None
    obj.closed_at = None
    return obj


# ========================================
# 初期化テスト
# ========================================


class TestGitlabClientInit:
    """GitlabClient初期化のテスト"""

    def test_URLとPATを指定して初期化できる(self) -> None:
        """URLとPATを直接指定してGitlabClientを初期化できることを確認する"""
        with patch("gitlab_client.gitlab_client.gitlab.Gitlab") as mock_gitlab:
            client = GitlabClient(url="https://gitlab.example.com", pat="test-pat")
            mock_gitlab.assert_called_once_with(
                url="https://gitlab.example.com",
                private_token="test-pat",
                timeout=60,
            )

    def test_環境変数からPATを読み込める(self) -> None:
        """環境変数GITLAB_PATからPATを読み込めることを確認する"""
        with patch.dict(os.environ, {"GITLAB_PAT": "env-pat", "GITLAB_URL": "https://env.gitlab.com"}):
            with patch("gitlab_client.gitlab_client.gitlab.Gitlab") as mock_gitlab:
                client = GitlabClient()
                mock_gitlab.assert_called_once()
                call_args = mock_gitlab.call_args
                assert call_args.kwargs["private_token"] == "env-pat"
                assert call_args.kwargs["url"] == "https://env.gitlab.com"

    def test_PATが未設定の場合にValueErrorが発生する(self) -> None:
        """PATが設定されていない場合にValueErrorが発生することを確認する"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Personal Access Token"):
                GitlabClient(url="https://gitlab.example.com", pat="")

    def test_タイムアウトを指定して初期化できる(self) -> None:
        """タイムアウト値を指定して初期化できることを確認する"""
        with patch("gitlab_client.gitlab_client.gitlab.Gitlab") as mock_gitlab:
            client = GitlabClient(url="https://gitlab.example.com", pat="test", timeout=30)
            call_args = mock_gitlab.call_args
            assert call_args.kwargs["timeout"] == 30


# ========================================
# Issue操作テスト
# ========================================


class TestGitlabClientIssueOperations:
    """Issue操作メソッドのテスト"""

    def test_list_issuesでIssue一覧を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """list_issues()がGitLabIssueのリストを返すことを確認する"""
        issue_obj = _make_issue_obj(iid=1, title="テストIssue1")
        mock_project.issues.list.return_value = [issue_obj]

        result = client.list_issues(project_id=100)

        mock_project.issues.list.assert_called_once_with(state="opened", all=True)
        assert len(result) == 1
        assert isinstance(result[0], GitLabIssue)
        assert result[0].iid == 1
        assert result[0].title == "テストIssue1"

    def test_list_issuesでラベルフィルターが適用される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """list_issues()にラベルを指定するとフィルターが適用されることを確認する"""
        mock_project.issues.list.return_value = []

        client.list_issues(project_id=100, labels=["coding agent"])

        call_kwargs = mock_project.issues.list.call_args.kwargs
        assert call_kwargs["labels"] == ["coding agent"]

    def test_list_issuesでstateフィルターが適用される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """list_issues()にstateを指定するとフィルターが適用されることを確認する"""
        mock_project.issues.list.return_value = []

        client.list_issues(project_id=100, state="closed")

        call_kwargs = mock_project.issues.list.call_args.kwargs
        assert call_kwargs["state"] == "closed"

    def test_get_issueでIssue詳細を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_issue()が正しいGitLabIssueを返すことを確認する"""
        issue_obj = _make_issue_obj(iid=42, title="詳細テストIssue")
        mock_project.issues.get.return_value = issue_obj

        result = client.get_issue(project_id=100, issue_iid=42)

        mock_project.issues.get.assert_called_once_with(42)
        assert isinstance(result, GitLabIssue)
        assert result.iid == 42
        assert result.title == "詳細テストIssue"

    def test_create_issue_noteでコメントが投稿される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """create_issue_note()がNote IDを返すことを確認する"""
        issue_obj = _make_issue_obj()
        mock_project.issues.get.return_value = issue_obj
        mock_note = MagicMock()
        mock_note.id = 999
        issue_obj.notes.create.return_value = mock_note

        note_id = client.create_issue_note(project_id=100, issue_iid=1, body="テストコメント")

        assert note_id == 999
        issue_obj.notes.create.assert_called_once_with({"body": "テストコメント"})

    def test_update_issue_labelsでラベルが更新される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """update_issue_labels()がIssueのラベルを更新することを確認する"""
        issue_obj = _make_issue_obj()
        mock_project.issues.get.return_value = issue_obj

        client.update_issue_labels(
            project_id=100,
            issue_iid=1,
            labels=["coding agent", "coding agent processing"],
        )

        assert issue_obj.labels == ["coding agent", "coding agent processing"]
        issue_obj.save.assert_called_once()


# ========================================
# MR操作テスト
# ========================================


class TestGitlabClientMROperations:
    """MR操作メソッドのテスト"""

    def test_list_merge_requestsでMR一覧を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """list_merge_requests()がGitLabMergeRequestのリストを返すことを確認する"""
        mr_obj = _make_mr_obj(iid=5, title="Draft: テストMR")
        mock_project.mergerequests.list.return_value = [mr_obj]

        result = client.list_merge_requests(project_id=100)

        assert len(result) == 1
        assert isinstance(result[0], GitLabMergeRequest)
        assert result[0].iid == 5

    def test_list_merge_requestsでsource_branchフィルターが適用される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """source_branchを指定するとフィルターが適用されることを確認する"""
        mock_project.mergerequests.list.return_value = []

        client.list_merge_requests(project_id=100, source_branch="issue-42")

        call_kwargs = mock_project.mergerequests.list.call_args.kwargs
        assert call_kwargs["source_branch"] == "issue-42"

    def test_create_merge_requestでMRが作成される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """create_merge_request()がGitLabMergeRequestを返すことを確認する"""
        mr_obj = _make_mr_obj(
            iid=10,
            title="Draft: 新機能",
            source_branch="issue-10",
            target_branch="main",
        )
        mock_project.mergerequests.create.return_value = mr_obj

        result = client.create_merge_request(
            project_id=100,
            source_branch="issue-10",
            target_branch="main",
            title="Draft: 新機能",
            description="テスト説明",
            labels=["coding agent"],
        )

        assert isinstance(result, GitLabMergeRequest)
        assert result.iid == 10
        assert result.source_branch == "issue-10"
        payload = mock_project.mergerequests.create.call_args[0][0]
        assert payload["source_branch"] == "issue-10"
        assert payload["title"] == "Draft: 新機能"

    def test_create_merge_request_noteでNoteが作成される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """create_merge_request_note()がNote IDを返すことを確認する"""
        mr_obj = _make_mr_obj()
        mock_project.mergerequests.get.return_value = mr_obj
        mock_note = MagicMock()
        mock_note.id = 777
        mr_obj.notes.create.return_value = mock_note

        note_id = client.create_merge_request_note(
            project_id=100,
            mr_iid=1,
            body="進捗コメント",
        )

        assert note_id == 777
        mr_obj.notes.create.assert_called_once_with({"body": "進捗コメント"})

    def test_update_merge_request_noteでNoteが更新される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """update_merge_request_note()がNoteを上書き更新することを確認する"""
        mr_obj = _make_mr_obj()
        mock_project.mergerequests.get.return_value = mr_obj
        mock_note = MagicMock()
        mr_obj.notes.get.return_value = mock_note

        client.update_merge_request_note(
            project_id=100,
            mr_iid=1,
            note_id=777,
            body="更新されたコメント",
        )

        mr_obj.notes.get.assert_called_once_with(777)
        assert mock_note.body == "更新されたコメント"
        mock_note.save.assert_called_once()

    def test_merge_merge_requestでMRがマージされる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """merge_merge_request()がMRをマージすることを確認する"""
        mr_obj = _make_mr_obj()
        mock_project.mergerequests.get.return_value = mr_obj

        client.merge_merge_request(project_id=100, mr_iid=1)

        mr_obj.merge.assert_called_once()

    def test_get_merge_requestでMR詳細を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_merge_request()がGitLabMergeRequestを返すことを確認する"""
        mr_obj = _make_mr_obj(iid=7, title="Draft: 詳細取得テスト")
        mock_project.mergerequests.get.return_value = mr_obj

        result = client.get_merge_request(project_id=100, mr_iid=7)

        assert isinstance(result, GitLabMergeRequest)
        assert result.iid == 7
        assert result.title == "Draft: 詳細取得テスト"
        mock_project.mergerequests.get.assert_called_once_with(7)

    def test_update_merge_requestでMRが更新される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """update_merge_request()が指定フィールドを更新してGitLabMergeRequestを返すことを確認する"""
        mr_obj = _make_mr_obj(iid=8, title="更新前タイトル")
        mock_project.mergerequests.get.return_value = mr_obj

        result = client.update_merge_request(
            project_id=100,
            mr_iid=8,
            title="更新後タイトル",
            labels=["bug", "coding agent"],
            assignee_ids=[42, 43],
        )

        assert isinstance(result, GitLabMergeRequest)
        # ラベルとアサイニーが設定されることを確認する
        assert mr_obj.title == "更新後タイトル"
        assert mr_obj.labels == ["bug", "coding agent"]
        assert mr_obj.assignee_ids == [42, 43]
        mr_obj.save.assert_called_once()

    def test_update_merge_requestでNoneフィールドは更新されない(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """update_merge_request()でNoneを指定したフィールドは更新されないことを確認する"""
        mr_obj = _make_mr_obj(iid=9, title="変更しないタイトル")
        mock_project.mergerequests.get.return_value = mr_obj

        # titleのみNoneにして更新する
        client.update_merge_request(
            project_id=100,
            mr_iid=9,
            title=None,
            labels=["feature"],
        )

        # titleは変更されないことを確認する
        assert mr_obj.title == "変更しないタイトル"
        # labelsは変更されることを確認する
        assert mr_obj.labels == ["feature"]
        mr_obj.save.assert_called_once()


# ========================================
# ブランチ操作テスト
# ========================================


class TestGitlabClientBranchOperations:
    """ブランチ操作メソッドのテスト"""

    def test_create_branchでブランチが作成される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """create_branch()がGitLabBranchを返すことを確認する"""
        branch_obj = MagicMock()
        branch_obj.name = "issue-42"
        branch_obj.commit = {"id": "abc123def456"}
        branch_obj.protected = False
        branch_obj.web_url = "https://gitlab.example.com/-/tree/issue-42"
        mock_project.branches.create.return_value = branch_obj

        result = client.create_branch(
            project_id=100,
            branch_name="issue-42",
            ref="main",
        )

        assert isinstance(result, GitLabBranch)
        assert result.name == "issue-42"
        assert result.commit_sha == "abc123def456"
        mock_project.branches.create.assert_called_once_with(
            {"branch": "issue-42", "ref": "main"}
        )

    def test_branch_existsで存在するブランチを確認できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """branch_exists()がTrue を返すことを確認する（ブランチが存在する場合）"""
        mock_project.branches.get.return_value = MagicMock()

        result = client.branch_exists(project_id=100, branch_name="issue-42")

        assert result is True

    def test_branch_existsで存在しないブランチを確認できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """branch_exists()がFalseを返すことを確認する（ブランチが存在しない場合）"""
        mock_project.branches.get.side_effect = gitlab.exceptions.GitlabGetError(
            "Branch Not Found", 404
        )

        result = client.branch_exists(project_id=100, branch_name="non-existent-branch")

        assert result is False

    def test_delete_branchでブランチが削除される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """delete_branch()がブランチを削除することを確認する"""
        branch_obj = MagicMock()
        mock_project.branches.get.return_value = branch_obj

        client.delete_branch(project_id=100, branch_name="feature/old-branch")

        mock_project.branches.get.assert_called_once_with("feature/old-branch")
        branch_obj.delete.assert_called_once()


# ========================================
# リポジトリ操作テスト
# ========================================


class TestGitlabClientRepositoryOperations:
    """リポジトリ操作メソッドのテスト"""

    def test_get_file_contentでファイル内容を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_file_content()がファイル内容の文字列を返すことを確認する"""
        file_obj = MagicMock()
        file_obj.decode.return_value = "# テストファイル\nprint('hello')\n".encode("utf-8")
        mock_project.files.get.return_value = file_obj

        result = client.get_file_content(
            project_id=100,
            file_path="src/main.py",
            ref="main",
        )

        assert result == "# テストファイル\nprint('hello')\n"
        mock_project.files.get.assert_called_once_with("src/main.py", "main")

    def test_get_file_treeでファイルツリーを取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_file_tree()がファイルツリーエントリのリストを返すことを確認する"""
        mock_project.repository_tree.return_value = [
            {"id": "abc", "name": "main.py", "type": "blob", "path": "src/main.py", "mode": "100644"},
            {"id": "def", "name": "src", "type": "tree", "path": "src", "mode": "040000"},
        ]

        result = client.get_file_tree(project_id=100, ref="main")

        assert len(result) == 2
        assert result[0]["name"] == "main.py"
        assert result[0]["type"] == "blob"
        assert result[1]["type"] == "tree"

    def test_create_commitでコミットが作成される(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """create_commit()がGitLabCommitを返すことを確認する"""
        commit_obj = MagicMock()
        commit_obj.id = "abc123def456abc123def456abc123def456abc1"
        commit_obj.short_id = "abc123de"
        commit_obj.title = "Fix bug"
        commit_obj.message = "Fix bug\n\nDetails..."
        commit_obj.author_name = "AutomataBot"
        commit_obj.author_email = "bot@example.com"
        commit_obj.authored_date = None
        commit_obj.committed_date = None
        commit_obj.web_url = "https://gitlab.example.com/-/commit/abc123"
        mock_project.commits.create.return_value = commit_obj

        actions = [
            {"action": "update", "file_path": "src/main.py", "content": "# fixed"}
        ]
        result = client.create_commit(
            project_id=100,
            branch="issue-42",
            commit_message="Fix bug",
            actions=actions,
        )

        assert isinstance(result, GitLabCommit)
        assert result.id == "abc123def456abc123def456abc123def456abc1"
        assert result.author_name == "AutomataBot"


# ========================================
# Note取得テスト
# ========================================


class TestGitlabClientNoteOperations:
    """Note取得メソッドのテスト"""

    def _make_note_obj(
        self,
        note_id: int = 1,
        body: str = "テストNote",
        system: bool = False,
    ) -> MagicMock:
        """モックNoteオブジェクトを生成する"""
        note = MagicMock()
        note.id = note_id
        note.body = body
        note.author = {"id": 1, "username": "author", "name": "Author"}
        note.created_at = None
        note.updated_at = None
        note.system = system
        return note

    def test_get_merge_request_notesでNote一覧を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_merge_request_notes()がGitLabNoteのリストを返すことを確認する"""
        mr_obj = _make_mr_obj()
        mock_project.mergerequests.get.return_value = mr_obj
        note1 = self._make_note_obj(note_id=1, body="最初のコメント")
        note2 = self._make_note_obj(note_id=2, body="2つ目のコメント")
        mr_obj.notes.list.return_value = [note1, note2]

        result = client.get_merge_request_notes(project_id=100, mr_iid=1)

        assert len(result) == 2
        assert isinstance(result[0], GitLabNote)
        assert result[0].id == 1
        assert result[0].body == "最初のコメント"
        assert result[1].id == 2
        mr_obj.notes.list.assert_called_once_with(all=True)

    def test_get_issue_notesでNote一覧を取得できる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_issue_notes()がGitLabNoteのリストを返すことを確認する"""
        issue_obj = _make_issue_obj()
        mock_project.issues.get.return_value = issue_obj
        note1 = self._make_note_obj(note_id=10, body="Issueコメント")
        issue_obj.notes.list.return_value = [note1]

        result = client.get_issue_notes(project_id=100, issue_iid=1)

        assert len(result) == 1
        assert isinstance(result[0], GitLabNote)
        assert result[0].id == 10
        assert result[0].body == "Issueコメント"
        issue_obj.notes.list.assert_called_once_with(all=True)

    def test_get_merge_request_notesでシステムNoteが含まれる(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_merge_request_notes()がシステムNoteも含めて返すことを確認する"""
        mr_obj = _make_mr_obj()
        mock_project.mergerequests.get.return_value = mr_obj
        system_note = self._make_note_obj(note_id=3, body="ブランチを作成しました", system=True)
        mr_obj.notes.list.return_value = [system_note]

        result = client.get_merge_request_notes(project_id=100, mr_iid=1)

        assert len(result) == 1
        assert result[0].system is True

    def test_get_merge_request_notesでNote一覧が空の場合は空リストを返す(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """get_merge_request_notes()がNoteがない場合は空リストを返すことを確認する"""
        mr_obj = _make_mr_obj()
        mock_project.mergerequests.get.return_value = mr_obj
        mr_obj.notes.list.return_value = []

        result = client.get_merge_request_notes(project_id=100, mr_iid=1)

        assert result == []


# ========================================
# エラーハンドリング・リトライテスト
# ========================================


class TestGitlabClientErrorHandling:
    """エラーハンドリングとリトライのテスト"""

    def test_レート制限429エラー時に自動リトライする(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """429エラー発生時に自動リトライして最終的に成功することを確認する"""
        issue_obj = _make_issue_obj()
        rate_limit_error = gitlab.exceptions.GitlabHttpError("Too Many Requests", 429)
        # 1回目は429、2回目は成功
        mock_project.issues.list.side_effect = [rate_limit_error, [issue_obj]]

        with patch("gitlab_client.gitlab_client._exponential_backoff"):
            result = client.list_issues(project_id=100)

        assert len(result) == 1
        assert mock_project.issues.list.call_count == 2

    def test_500エラー時に最大3回リトライする(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """500エラー発生時に最大3回リトライすることを確認する"""
        server_error = gitlab.exceptions.GitlabHttpError("Internal Server Error", 500)
        server_error.response_code = 500
        mock_project.issues.list.side_effect = server_error

        with patch("gitlab_client.gitlab_client._exponential_backoff"):
            with pytest.raises(gitlab.exceptions.GitlabHttpError):
                client.list_issues(project_id=100)

        # 最大3回試行することを確認する
        assert mock_project.issues.list.call_count == 3

    def test_401認証エラー時は即座に上位へ伝播する(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """401エラー発生時はリトライせずに例外を上位へ伝播することを確認する"""
        auth_error = gitlab.exceptions.GitlabAuthenticationError("Unauthorized", 401)
        mock_project.issues.list.side_effect = auth_error

        with pytest.raises(gitlab.exceptions.GitlabAuthenticationError):
            client.list_issues(project_id=100)

        # リトライしないことを確認する
        assert mock_project.issues.list.call_count == 1

    def test_404エラー時は即座に上位へ伝播する(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """404エラー発生時はリトライせずに例外を上位へ伝播することを確認する"""
        not_found_error = gitlab.exceptions.GitlabHttpError("Not Found", 404)
        not_found_error.response_code = 404
        mock_project.issues.get.side_effect = not_found_error

        with pytest.raises(gitlab.exceptions.GitlabHttpError):
            client.get_issue(project_id=100, issue_iid=999)

        # リトライしないことを確認する
        assert mock_project.issues.get.call_count == 1

    def test_502エラー時にリトライする(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """502エラー発生時にリトライすることを確認する"""
        gateway_error = gitlab.exceptions.GitlabHttpError("Bad Gateway", 502)
        gateway_error.response_code = 502
        issue_obj = _make_issue_obj()
        mock_project.issues.list.side_effect = [gateway_error, [issue_obj]]

        with patch("gitlab_client.gitlab_client._exponential_backoff"):
            result = client.list_issues(project_id=100)

        assert len(result) == 1
        assert mock_project.issues.list.call_count == 2

    def test_409競合エラー時にリトライする(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """409競合エラー発生時にリトライして最終的に成功することを確認する（AUTOMATA_CODEX_SPEC § 7.4）"""
        conflict_error = gitlab.exceptions.GitlabHttpError("Conflict", 409)
        conflict_error.response_code = 409
        issue_obj = _make_issue_obj()
        # 1回目は409、2回目は成功
        mock_project.issues.list.side_effect = [conflict_error, [issue_obj]]

        with patch("gitlab_client.gitlab_client._exponential_backoff"):
            result = client.list_issues(project_id=100)

        assert len(result) == 1
        assert mock_project.issues.list.call_count == 2

    def test_409競合エラーが最大試行回数を超えた場合に例外が発生する(
        self,
        client: GitlabClient,
        mock_project: MagicMock,
    ) -> None:
        """409エラーが最大試行回数を超えた場合に例外が伝播することを確認する"""
        conflict_error = gitlab.exceptions.GitlabHttpError("Conflict", 409)
        conflict_error.response_code = 409
        mock_project.issues.list.side_effect = conflict_error

        with patch("gitlab_client.gitlab_client._exponential_backoff"):
            with pytest.raises(gitlab.exceptions.GitlabHttpError):
                client.list_issues(project_id=100)

        # 最大3回試行することを確認する
        assert mock_project.issues.list.call_count == _MAX_RETRIES


# ========================================
# ヘルパー関数テスト
# ========================================


class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_user_from_dictでGitLabUserを生成できる(self) -> None:
        """_user_from_dict()がGitLabUserを正しく生成することを確認する"""
        data = {
            "id": 1,
            "username": "test-user",
            "name": "Test User",
            "email": "test@example.com",
        }
        user = _user_from_dict(data)
        assert user is not None
        assert user.id == 1
        assert user.username == "test-user"

    def test_user_from_dictでNoneを渡すとNoneが返る(self) -> None:
        """_user_from_dict()にNoneを渡すとNoneが返ることを確認する"""
        assert _user_from_dict(None) is None

    def test_exponential_backoffで待機する(self) -> None:
        """_exponential_backoff()がtime.sleepを呼び出すことを確認する"""
        with patch("gitlab_client.gitlab_client.time.sleep") as mock_sleep:
            _exponential_backoff(attempt=0, base_delay=1.0)
            mock_sleep.assert_called_once_with(1.0)

        with patch("gitlab_client.gitlab_client.time.sleep") as mock_sleep:
            _exponential_backoff(attempt=1, base_delay=1.0)
            mock_sleep.assert_called_once_with(2.0)

        with patch("gitlab_client.gitlab_client.time.sleep") as mock_sleep:
            _exponential_backoff(attempt=2, base_delay=1.0)
            mock_sleep.assert_called_once_with(4.0)
