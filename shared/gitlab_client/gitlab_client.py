"""
GitLab APIクライアントモジュール

python-gitlabライブラリをラップして、GitLab REST API操作を提供する。
Issue・MR・ブランチ・コミット・コメント等の操作をメソッドとして実装する。

AUTOMATA_CODEX_SPEC.md § 7（GitLab API操作設計）に準拠する。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import gitlab
import gitlab.exceptions

from models.gitlab import (
    GitLabBranch,
    GitLabCommit,
    GitLabIssue,
    GitLabMergeRequest,
    GitLabNote,
    GitLabUser,
)

logger = logging.getLogger(__name__)

# リトライ設定
_RETRY_STATUS_CODES = {500, 502, 503, 504}
_RATE_LIMIT_STATUS_CODE = 429
_CONFLICT_STATUS_CODE = 409
_MAX_RETRIES = 3
_MAX_RATE_LIMIT_RETRIES = 5
_BASE_DELAY_SECONDS = 1.0
_RATE_LIMIT_BASE_DELAY = 60.0


def _exponential_backoff(attempt: int, base_delay: float) -> None:
    """
    指数バックオフで待機する。

    Args:
        attempt: 現在のリトライ試行回数（0始まり）
        base_delay: ベース待機秒数
    """
    delay = base_delay * (2 ** attempt)
    logger.info("バックオフ待機: %.1f秒後にリトライします", delay)
    time.sleep(delay)


def _user_from_dict(data: dict[str, Any] | None) -> GitLabUser | None:
    """
    GitLab APIのユーザーデータ辞書からGitLabUserを生成する。

    Args:
        data: ユーザーデータ辞書

    Returns:
        GitLabUserインスタンス、またはNone
    """
    if data is None:
        return None
    return GitLabUser(
        id=data.get("id", 0),
        username=data.get("username", ""),
        name=data.get("name", ""),
        email=data.get("email"),
        avatar_url=data.get("avatar_url"),
        web_url=data.get("web_url"),
    )


def _issue_from_obj(issue_obj: Any) -> GitLabIssue:
    """
    python-gitlabのIssueオブジェクトからGitLabIssueを生成する。

    Args:
        issue_obj: python-gitlabのIssueオブジェクト

    Returns:
        GitLabIssueインスタンス
    """
    assignees_data = getattr(issue_obj, "assignees", []) or []
    return GitLabIssue(
        iid=issue_obj.iid,
        title=issue_obj.title,
        description=getattr(issue_obj, "description", "") or "",
        project_id=issue_obj.project_id,
        state=getattr(issue_obj, "state", "opened"),
        labels=list(getattr(issue_obj, "labels", []) or []),
        assignees=[_user_from_dict(a) for a in assignees_data if a],  # type: ignore[misc]
        author=_user_from_dict(getattr(issue_obj, "author", None)),
        web_url=getattr(issue_obj, "web_url", None),
        created_at=getattr(issue_obj, "created_at", None),
        updated_at=getattr(issue_obj, "updated_at", None),
        closed_at=getattr(issue_obj, "closed_at", None),
    )


def _mr_from_obj(mr_obj: Any) -> GitLabMergeRequest:
    """
    python-gitlabのMergeRequestオブジェクトからGitLabMergeRequestを生成する。

    Args:
        mr_obj: python-gitlabのMergeRequestオブジェクト

    Returns:
        GitLabMergeRequestインスタンス
    """
    assignees_data = getattr(mr_obj, "assignees", []) or []
    return GitLabMergeRequest(
        iid=mr_obj.iid,
        title=mr_obj.title,
        description=getattr(mr_obj, "description", "") or "",
        project_id=mr_obj.project_id,
        source_branch=mr_obj.source_branch,
        target_branch=mr_obj.target_branch,
        state=getattr(mr_obj, "state", "opened"),
        labels=list(getattr(mr_obj, "labels", []) or []),
        assignees=[_user_from_dict(a) for a in assignees_data if a],  # type: ignore[misc]
        author=_user_from_dict(getattr(mr_obj, "author", None)),
        web_url=getattr(mr_obj, "web_url", None),
        draft=getattr(mr_obj, "draft", False) or getattr(mr_obj, "work_in_progress", False),
        merge_status=getattr(mr_obj, "merge_status", None),
        sha=getattr(mr_obj, "sha", None),
        created_at=getattr(mr_obj, "created_at", None),
        updated_at=getattr(mr_obj, "updated_at", None),
        merged_at=getattr(mr_obj, "merged_at", None),
        closed_at=getattr(mr_obj, "closed_at", None),
    )


def _note_from_obj(note_obj: Any) -> GitLabNote:
    """
    python-gitlabのNoteオブジェクトからGitLabNoteを生成する。

    Args:
        note_obj: python-gitlabのNoteオブジェクト

    Returns:
        GitLabNoteインスタンス
    """
    return GitLabNote(
        id=note_obj.id,
        body=note_obj.body,
        author=_user_from_dict(getattr(note_obj, "author", None)),
        created_at=getattr(note_obj, "created_at", None),
        updated_at=getattr(note_obj, "updated_at", None),
        system=getattr(note_obj, "system", False),
    )


class GitlabClient:
    """
    GitLab REST APIラッパークライアント。

    python-gitlabライブラリを使用してGitLab APIへアクセスし、
    Issue・MR・ブランチ・コミット・コメントの各種操作を提供する。

    認証にはシステム全体で共有するbot用Personal Access Token（GITLAB_PAT環境変数）を使用する。
    429エラー（レート制限）は指数バックオフで自動リトライする。
    500/502/503/504エラーは最大3回リトライする。
    401/403/404エラーは上位に伝播させる。
    """

    def __init__(
        self,
        url: str | None = None,
        pat: str | None = None,
        timeout: int = 60,
    ) -> None:
        """
        GitlabClientを初期化する。

        Args:
            url: GitLabインスタンスのURL。Noneの場合はGITLAB_URL環境変数を使用する。
            pat: Personal Access Token。Noneの場合はGITLAB_PAT環境変数を使用する。
            timeout: APIリクエストタイムアウト秒数（デフォルト: 60）

        Raises:
            ValueError: GitLab URL または PAT が設定されていない場合
        """
        resolved_url = url or os.getenv("GITLAB_URL", "https://gitlab.com")
        resolved_pat = pat or os.getenv("GITLAB_PAT", "")

        if not resolved_pat:
            raise ValueError(
                "GitLab Personal Access Token が設定されていません。"
                "環境変数 GITLAB_PAT を設定するか、pat引数を指定してください。"
            )

        self._gl = gitlab.Gitlab(
            url=resolved_url,
            private_token=resolved_pat,
            timeout=timeout,
        )
        logger.info("GitlabClientを初期化しました: url=%s", resolved_url)

    # ========================================
    # 内部ヘルパー: リトライ付きAPIコール
    # ========================================

    def _call_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        レート制限・一時的エラーに対してリトライを行いながらGitLab API関数を呼び出す。

        Args:
            func: 呼び出す関数
            *args: 関数の位置引数
            **kwargs: 関数のキーワード引数

        Returns:
            関数の戻り値

        Raises:
            gitlab.exceptions.GitlabAuthenticationError: 401認証エラー時
            gitlab.exceptions.GitlabHttpError: 403/404/その他解決不能エラー時
        """
        last_exception: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except gitlab.exceptions.GitlabAuthenticationError:
                # 401: 認証エラーは即座に上位へ伝播
                logger.error("GitLab認証エラー（401）: トークンを確認してください")
                raise
            except gitlab.exceptions.GitlabHttpError as exc:
                status = getattr(exc, "response_code", None) or 0
                if status == _RATE_LIMIT_STATUS_CODE:
                    # 429: レート制限エラー、指数バックオフでリトライ
                    if attempt < _MAX_RATE_LIMIT_RETRIES - 1:
                        logger.warning(
                            "レート制限（429）: バックオフ後リトライします（試行 %d/%d）",
                            attempt + 1,
                            _MAX_RATE_LIMIT_RETRIES,
                        )
                        _exponential_backoff(attempt, _RATE_LIMIT_BASE_DELAY)
                        last_exception = exc
                        continue
                    raise
                elif status in _RETRY_STATUS_CODES:
                    # 500/502/503/504: 一時的エラー、リトライ
                    if attempt < _MAX_RETRIES - 1:
                        logger.warning(
                            "サーバーエラー（%d）: リトライします（試行 %d/%d）",
                            status,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        _exponential_backoff(attempt, _BASE_DELAY_SECONDS)
                        last_exception = exc
                        continue
                    raise
                elif status == _CONFLICT_STATUS_CODE:
                    # 409: 競合エラー、リトライ
                    if attempt < _MAX_RETRIES - 1:
                        logger.warning(
                            "競合エラー（409）: リトライします（試行 %d/%d）",
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        _exponential_backoff(attempt, _BASE_DELAY_SECONDS)
                        last_exception = exc
                        continue
                    raise
                else:
                    # 403/404などその他: 上位へ伝播
                    raise

        # ここには到達しないはずだが安全のため最後の例外をraiseする
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("予期しないリトライループ終了")  # pragma: no cover

    def _get_project(self, project_id: int) -> Any:
        """
        プロジェクトオブジェクトを取得する。

        Args:
            project_id: GitLabプロジェクトID

        Returns:
            python-gitlabのProjectオブジェクト
        """
        return self._call_with_retry(self._gl.projects.get, project_id)

    # ========================================
    # Issue操作
    # ========================================

    def list_issues(
        self,
        project_id: int,
        labels: list[str] | None = None,
        state: str = "opened",
    ) -> list[GitLabIssue]:
        """
        プロジェクトのIssue一覧を取得する。

        Args:
            project_id: GitLabプロジェクトID
            labels: フィルタリングするラベルリスト（Noneの場合はフィルタなし）
            state: Issueの状態（opened/closed/all）

        Returns:
            GitLabIssueのリスト
        """
        project = self._get_project(project_id)
        kwargs: dict[str, Any] = {"state": state, "all": True}
        if labels:
            kwargs["labels"] = labels

        raw_issues = self._call_with_retry(project.issues.list, **kwargs)
        result = [_issue_from_obj(i) for i in raw_issues]
        logger.debug("Issue一覧取得: project_id=%d, count=%d", project_id, len(result))
        return result

    def get_issue(self, project_id: int, issue_iid: int) -> GitLabIssue:
        """
        Issueの詳細を取得する。

        Args:
            project_id: GitLabプロジェクトID
            issue_iid: Issue IID（プロジェクト内通し番号）

        Returns:
            GitLabIssueインスタンス

        Raises:
            gitlab.exceptions.GitlabHttpError: Issueが存在しない場合（404）
        """
        project = self._get_project(project_id)
        issue_obj = self._call_with_retry(project.issues.get, issue_iid)
        return _issue_from_obj(issue_obj)

    def create_issue_note(self, project_id: int, issue_iid: int, body: str) -> int:
        """
        IssueにNoteを投稿する。

        Args:
            project_id: GitLabプロジェクトID
            issue_iid: Issue IID
            body: コメント本文

        Returns:
            作成されたNoteのID
        """
        project = self._get_project(project_id)
        issue_obj = self._call_with_retry(project.issues.get, issue_iid)
        note = self._call_with_retry(issue_obj.notes.create, {"body": body})
        logger.debug("IssueNote作成: issue_iid=%d, note_id=%d", issue_iid, note.id)
        return note.id

    def update_issue_labels(
        self,
        project_id: int,
        issue_iid: int,
        labels: list[str],
    ) -> None:
        """
        Issueのラベルを更新する。

        Args:
            project_id: GitLabプロジェクトID
            issue_iid: Issue IID
            labels: 新しいラベルリスト（既存ラベルをすべて置き換える）
        """
        project = self._get_project(project_id)
        issue_obj = self._call_with_retry(project.issues.get, issue_iid)
        issue_obj.labels = labels
        self._call_with_retry(issue_obj.save)
        logger.debug("Issueラベル更新: issue_iid=%d, labels=%s", issue_iid, labels)

    # ========================================
    # MR操作
    # ========================================

    def list_merge_requests(
        self,
        project_id: int,
        labels: list[str] | None = None,
        state: str = "opened",
        source_branch: str | None = None,
    ) -> list[GitLabMergeRequest]:
        """
        プロジェクトのMerge Request一覧を取得する。

        Args:
            project_id: GitLabプロジェクトID
            labels: フィルタリングするラベルリスト（Noneの場合はフィルタなし）
            state: MRの状態（opened/closed/merged/all）
            source_branch: ソースブランチ名でフィルタ（Noneの場合はフィルタなし）

        Returns:
            GitLabMergeRequestのリスト
        """
        project = self._get_project(project_id)
        kwargs: dict[str, Any] = {"state": state, "all": True}
        if labels:
            kwargs["labels"] = labels
        if source_branch:
            kwargs["source_branch"] = source_branch

        raw_mrs = self._call_with_retry(project.mergerequests.list, **kwargs)
        result = [_mr_from_obj(mr) for mr in raw_mrs]
        logger.debug("MR一覧取得: project_id=%d, count=%d", project_id, len(result))
        return result

    def create_merge_request(
        self,
        project_id: int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
        assignee_ids: list[int] | None = None,
    ) -> GitLabMergeRequest:
        """
        Merge Requestを作成する。

        Args:
            project_id: GitLabプロジェクトID
            source_branch: ソースブランチ名
            target_branch: ターゲットブランチ名
            title: MRタイトル
            description: MR説明文（デフォルト: ""）
            labels: ラベルリスト（Noneの場合はラベルなし）
            assignee_ids: アサイニーのユーザーIDリスト

        Returns:
            作成されたGitLabMergeRequestインスタンス
        """
        project = self._get_project(project_id)
        payload: dict[str, Any] = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
        }
        if labels:
            payload["labels"] = ",".join(labels)
        if assignee_ids:
            payload["assignee_ids"] = assignee_ids

        mr_obj = self._call_with_retry(project.mergerequests.create, payload)
        result = _mr_from_obj(mr_obj)
        logger.info(
            "MR作成: project_id=%d, iid=%d, source=%s, target=%s",
            project_id,
            result.iid,
            source_branch,
            target_branch,
        )
        return result

    def create_merge_request_note(
        self,
        project_id: int,
        mr_iid: int,
        body: str,
    ) -> int:
        """
        Merge RequestにNoteを投稿する。

        Args:
            project_id: GitLabプロジェクトID
            mr_iid: MR IID
            body: コメント本文

        Returns:
            作成されたNoteのGitLab Note ID
        """
        project = self._get_project(project_id)
        mr_obj = self._call_with_retry(project.mergerequests.get, mr_iid)
        note = self._call_with_retry(mr_obj.notes.create, {"body": body})
        logger.debug("MRNote作成: mr_iid=%d, note_id=%d", mr_iid, note.id)
        return note.id

    def update_merge_request_note(
        self,
        project_id: int,
        mr_iid: int,
        note_id: int,
        body: str,
    ) -> None:
        """
        Merge RequestのNoteを上書き更新する。

        GitLab PUT /projects/:id/merge_requests/:mr_iid/notes/:note_id APIを使用する。

        Args:
            project_id: GitLabプロジェクトID
            mr_iid: MR IID
            note_id: 更新対象のNote ID
            body: 新しいコメント本文
        """
        project = self._get_project(project_id)
        mr_obj = self._call_with_retry(project.mergerequests.get, mr_iid)
        note_obj = self._call_with_retry(mr_obj.notes.get, note_id)
        note_obj.body = body
        self._call_with_retry(note_obj.save)
        logger.debug("MRNote更新: mr_iid=%d, note_id=%d", mr_iid, note_id)

    def merge_merge_request(
        self,
        project_id: int,
        mr_iid: int,
        merge_commit_message: str | None = None,
    ) -> None:
        """
        Merge Requestをマージする。

        Args:
            project_id: GitLabプロジェクトID
            mr_iid: MR IID
            merge_commit_message: マージコミットメッセージ（Noneの場合はデフォルト）

        Raises:
            gitlab.exceptions.GitlabHttpError: マージ不可の場合
        """
        project = self._get_project(project_id)
        mr_obj = self._call_with_retry(project.mergerequests.get, mr_iid)
        kwargs: dict[str, Any] = {}
        if merge_commit_message:
            kwargs["merge_commit_message"] = merge_commit_message
        self._call_with_retry(mr_obj.merge, **kwargs)
        logger.info("MRマージ完了: project_id=%d, mr_iid=%d", project_id, mr_iid)

    # ========================================
    # ブランチ操作
    # ========================================

    def create_branch(
        self,
        project_id: int,
        branch_name: str,
        ref: str,
    ) -> GitLabBranch:
        """
        ブランチを作成する。

        Args:
            project_id: GitLabプロジェクトID
            branch_name: 作成するブランチ名
            ref: 参照元ブランチ名またはコミットSHA

        Returns:
            作成されたGitLabBranchインスタンス
        """
        project = self._get_project(project_id)
        branch_obj = self._call_with_retry(
            project.branches.create,
            {"branch": branch_name, "ref": ref},
        )
        result = GitLabBranch(
            name=branch_obj.name,
            commit_sha=branch_obj.commit.get("id") if branch_obj.commit else None,
            protected=getattr(branch_obj, "protected", False),
            web_url=getattr(branch_obj, "web_url", None),
        )
        logger.info(
            "ブランチ作成: project_id=%d, branch=%s, ref=%s",
            project_id,
            branch_name,
            ref,
        )
        return result

    def branch_exists(self, project_id: int, branch_name: str) -> bool:
        """
        ブランチが存在するか確認する。

        Args:
            project_id: GitLabプロジェクトID
            branch_name: 確認するブランチ名

        Returns:
            ブランチが存在する場合はTrue、存在しない場合はFalse
        """
        project = self._get_project(project_id)
        try:
            self._call_with_retry(project.branches.get, branch_name)
            return True
        except gitlab.exceptions.GitlabGetError:
            return False

    # ========================================
    # リポジトリ操作
    # ========================================

    def get_file_content(
        self,
        project_id: int,
        file_path: str,
        ref: str = "main",
    ) -> str:
        """
        リポジトリのファイル内容を取得する。

        Args:
            project_id: GitLabプロジェクトID
            file_path: ファイルのリポジトリ内パス
            ref: ブランチ名またはコミットSHA（デフォルト: "main"）

        Returns:
            ファイル内容の文字列

        Raises:
            gitlab.exceptions.GitlabHttpError: ファイルが存在しない場合（404）
        """
        project = self._get_project(project_id)
        file_obj = self._call_with_retry(project.files.get, file_path, ref)
        # python-gitlabはファイル内容をBase64エンコードで返す
        content: str = file_obj.decode().decode("utf-8")
        return content

    def get_file_tree(
        self,
        project_id: int,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
    ) -> list[dict[str, Any]]:
        """
        リポジトリのファイルツリーを取得する。

        Args:
            project_id: GitLabプロジェクトID
            path: 取得するディレクトリパス（デフォルト: ルート）
            ref: ブランチ名またはコミットSHA（デフォルト: "main"）
            recursive: サブディレクトリを再帰的に取得するか（デフォルト: False）

        Returns:
            ファイルツリーのエントリ辞書のリスト
            各エントリは {"id": str, "name": str, "type": str, "path": str, "mode": str} 形式
        """
        project = self._get_project(project_id)
        kwargs: dict[str, Any] = {"ref": ref, "all": True}
        if path:
            kwargs["path"] = path
        if recursive:
            kwargs["recursive"] = True

        items = self._call_with_retry(project.repository_tree, **kwargs)
        result: list[dict[str, Any]] = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "path": item.get("path", ""),
                "mode": item.get("mode", ""),
            }
            for item in (items or [])
        ]
        logger.debug(
            "ファイルツリー取得: project_id=%d, path=%s, count=%d",
            project_id,
            path,
            len(result),
        )
        return result

    def create_commit(
        self,
        project_id: int,
        branch: str,
        commit_message: str,
        actions: list[dict[str, Any]],
    ) -> GitLabCommit:
        """
        コミットを作成する（複数ファイル操作を1コミットで実行）。

        Args:
            project_id: GitLabプロジェクトID
            branch: コミット先ブランチ名
            commit_message: コミットメッセージ
            actions: ファイル操作アクションのリスト
                各アクション: {"action": "create"|"update"|"delete"|"move"|"chmod",
                               "file_path": str, "content": str, ...}

        Returns:
            作成されたGitLabCommitインスタンス
        """
        project = self._get_project(project_id)
        payload = {
            "branch": branch,
            "commit_message": commit_message,
            "actions": actions,
        }
        commit_obj = self._call_with_retry(project.commits.create, payload)
        result = GitLabCommit(
            id=commit_obj.id,
            short_id=getattr(commit_obj, "short_id", None),
            title=getattr(commit_obj, "title", None),
            message=getattr(commit_obj, "message", None),
            author_name=getattr(commit_obj, "author_name", None),
            author_email=getattr(commit_obj, "author_email", None),
            authored_date=getattr(commit_obj, "authored_date", None),
            committed_date=getattr(commit_obj, "committed_date", None),
            web_url=getattr(commit_obj, "web_url", None),
        )
        logger.info(
            "コミット作成: project_id=%d, branch=%s, sha=%s",
            project_id,
            branch,
            result.id,
        )
        return result

    # ========================================
    # コメント操作（Note）
    # ========================================

    def get_merge_request_notes(
        self,
        project_id: int,
        mr_iid: int,
    ) -> list[GitLabNote]:
        """
        Merge RequestのNote一覧を取得する。

        Args:
            project_id: GitLabプロジェクトID
            mr_iid: MR IID

        Returns:
            GitLabNoteのリスト
        """
        project = self._get_project(project_id)
        mr_obj = self._call_with_retry(project.mergerequests.get, mr_iid)
        notes = self._call_with_retry(mr_obj.notes.list, all=True)
        return [_note_from_obj(n) for n in notes]

    def get_issue_notes(
        self,
        project_id: int,
        issue_iid: int,
    ) -> list[GitLabNote]:
        """
        IssueのNote一覧を取得する。

        Args:
            project_id: GitLabプロジェクトID
            issue_iid: Issue IID

        Returns:
            GitLabNoteのリスト
        """
        project = self._get_project(project_id)
        issue_obj = self._call_with_retry(project.issues.get, issue_iid)
        notes = self._call_with_retry(issue_obj.notes.list, all=True)
        return [_note_from_obj(n) for n in notes]
