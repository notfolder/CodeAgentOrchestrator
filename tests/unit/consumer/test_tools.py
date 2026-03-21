"""
Tools クラス群の単体テスト

TodoManagementTool・IssueToMRConverter・IssueToMRConfig の
各メソッドを検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.issue_to_mr_converter import IssueToMRConfig, IssueToMRConverter
from tools.todo_management_tool import TodoManagementTool


# ========================================
# フィクスチャ
# ========================================


@pytest.fixture
def mock_db_connection() -> MagicMock:
    """テスト用DBコネクションモックを返す"""
    conn = MagicMock()
    # asyncpgのfetchrowとfetchはCoroutineを返すのでAsyncMockにする
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    return conn


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    return MagicMock()


@pytest.fixture
def mock_issue() -> MagicMock:
    """テスト用GitLabIssueモックを返す"""
    issue = MagicMock()
    issue.iid = 7
    issue.project_id = 10
    issue.title = "テスト Issue タイトル"
    issue.description = "テスト Issue の説明"
    issue.labels = ["backend", "bug"]
    issue.assignees = []
    return issue


@pytest.fixture
def mock_created_mr() -> MagicMock:
    """テスト用GitLabMergeRequestモックを返す"""
    mr = MagicMock()
    mr.iid = 55
    return mr


# ========================================
# TestTodoManagementTool
# ========================================


class TestTodoManagementTool:
    """TodoManagementTool のテスト"""

    async def test_todo_management_create_todo_list(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """create_todo_listがDBのINSERTを実行してtodo_idsを返すことを確認する"""
        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
        )

        # fetchrowが呼ばれるたびに異なるidを返すようにモックする
        mock_db_connection.fetchrow.side_effect = [
            {"id": 1},
            {"id": 2},
            {"id": 3},
        ]

        todos = [
            {"title": "Todoアイテム1", "description": "説明1"},
            {"title": "Todoアイテム2", "description": "説明2"},
            {"title": "Todoアイテム3", "description": "説明3"},
        ]

        result = await tool.create_todo_list(
            project_id=10,
            mr_iid=5,
            todos=todos,
        )

        # statusがsuccessで3件のtodo_idsが返ることを確認する
        assert result["status"] == "success"
        assert result["todo_ids"] == [1, 2, 3]
        # fetchrowが3回呼ばれることを確認する
        assert mock_db_connection.fetchrow.call_count == 3

    async def test_todo_management_sync_to_gitlab(
        self,
        mock_db_connection: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """sync_to_gitlabがMarkdownを生成してgitlab_clientのcreate_merge_request_noteを呼ぶことを確認する"""
        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=mock_gitlab_client,
            task_uuid="task-uuid-001",
        )

        # DBからTodoレコードが返るようにモックする
        mock_rows = [
            {
                "id": 1,
                "title": "Todoアイテム1",
                "status": "completed",
                "parent_todo_id": None,
            },
            {
                "id": 2,
                "title": "Todoアイテム2",
                "status": "not-started",
                "parent_todo_id": None,
            },
        ]
        mock_db_connection.fetch.return_value = mock_rows

        result = await tool.sync_to_gitlab(
            project_id=10,
            mr_iid=5,
        )

        # DBからTodoが取得されることを確認する
        mock_db_connection.fetch.assert_called_once()
        # Markdownが生成されてGitLabにコメント投稿されることを確認する
        mock_gitlab_client.create_merge_request_note.assert_called_once()
        call_args = mock_gitlab_client.create_merge_request_note.call_args
        posted_body: str = call_args.args[2]
        # Markdown にTodoタイトルが含まれることを確認する
        assert "Todoアイテム1" in posted_body
        assert "Todoアイテム2" in posted_body
        # completedのTodoはチェック済みマークになることを確認する
        assert "[x]" in posted_body
        assert "[ ]" in posted_body
        assert result["status"] == "success"

    async def test_todo_management_get_todo_list(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """get_todo_listがDBからTodoを取得して返すことを確認する"""
        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
        )

        mock_rows = [
            {
                "id": 1,
                "title": "タスク1",
                "description": "",
                "status": "completed",
                "parent_todo_id": None,
                "order_index": 0,
            },
            {
                "id": 2,
                "title": "タスク2",
                "description": "",
                "status": "not-started",
                "parent_todo_id": None,
                "order_index": 1,
            },
        ]
        mock_db_connection.fetch.return_value = mock_rows

        result = await tool.get_todo_list(project_id=10, mr_iid=5)

        assert result["status"] == "success"
        assert len(result["todos"]) == 2
        assert result["todos"][0]["title"] == "タスク1"
        mock_db_connection.fetch.assert_called_once()

    async def test_todo_management_update_todo_status(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """update_todo_statusがDBのUPDATEを実行して正しい結果を返すことを確認する"""
        mock_db_connection.execute = AsyncMock(return_value="UPDATE 1")
        mock_db_connection.fetch = AsyncMock(return_value=[])

        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
        )

        result = await tool.update_todo_status(todo_id=1, status="completed")

        assert result["status"] == "success"
        assert result["todo_id"] == 1
        assert result["new_status"] == "completed"
        mock_db_connection.execute.assert_called_once()

    async def test_todo_management_update_todo_status_emits_todo_changed(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """update_todo_statusにcontextを渡すとtodo_changedイベントが呈出されることを確認する"""
        mock_db_connection.execute = AsyncMock(return_value="UPDATE 1")
        # _get_todo_markdownで使われるfetchモック
        mock_db_connection.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "タスク1",
                    "status": "completed",
                    "parent_todo_id": None,
                },
            ]
        )

        mock_progress_reporter = MagicMock()
        mock_progress_reporter.report_progress = AsyncMock()

        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
            progress_reporter=mock_progress_reporter,
        )

        mock_ctx = MagicMock()
        result = await tool.update_todo_status(
            todo_id=1, status="completed", context=mock_ctx
        )

        assert result["status"] == "success"
        # todo_changed イベントが ProgressReporter に呈出されることを確認する
        mock_progress_reporter.report_progress.assert_called_once()
        call_kwargs = mock_progress_reporter.report_progress.call_args.kwargs
        assert call_kwargs["event"] == "todo_changed"
        assert "todo_markdown" in call_kwargs["details"]

    async def test_todo_management_add_todo(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """add_todoがDBにINSERTして新しいtodo_idを返すことを確認する"""
        mock_db_connection.fetchrow = AsyncMock(
            side_effect=[
                {"max_idx": 1},  # MAX(order_index) クエリ
                {"id": 10},  # INSERT クエリ
            ]
        )
        mock_db_connection.fetch = AsyncMock(return_value=[])

        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
        )

        result = await tool.add_todo(
            project_id=10,
            mr_iid=5,
            title="新しいTodo",
            description="説明",
        )

        assert result["status"] == "success"
        assert result["todo_id"] == 10
        # fetchrowが2回呼ばれる（MAX取得 + INSERT）
        assert mock_db_connection.fetchrow.call_count == 2

    async def test_todo_management_delete_todo(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """delete_todoがDBのDELETEを実行して正しい結果を返すことを確認する"""
        mock_db_connection.execute = AsyncMock(return_value="DELETE 1")
        mock_db_connection.fetch = AsyncMock(return_value=[])

        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
        )

        result = await tool.delete_todo(todo_id=5)

        assert result["status"] == "success"
        assert result["todo_id"] == 5
        mock_db_connection.execute.assert_called_once()

    async def test_todo_management_reorder_todos(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """reorder_todosがすべてのtodo_idのorder_indexを更新することを確認する"""
        mock_db_connection.execute = AsyncMock(return_value="UPDATE 1")
        mock_db_connection.fetch = AsyncMock(return_value=[])

        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
        )

        todo_ids = [3, 1, 2]
        result = await tool.reorder_todos(todo_ids=todo_ids)

        assert result["status"] == "success"
        assert result["reordered_count"] == 3
        # 3件のUPDATEが実行されることを確認する
        assert mock_db_connection.execute.call_count == 3

    async def test_todo_management_create_todo_list_emits_todo_changed(
        self,
        mock_db_connection: MagicMock,
    ) -> None:
        """create_todo_listにcontextを渡すとtodo_changedイベントが呈出されることを確認する"""
        mock_db_connection.fetchrow = AsyncMock(return_value={"id": 1})
        mock_db_connection.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "title": "タスク1",
                    "status": "not-started",
                    "parent_todo_id": None,
                },
            ]
        )

        mock_progress_reporter = MagicMock()
        mock_progress_reporter.report_progress = AsyncMock()

        tool = TodoManagementTool(
            db_connection=mock_db_connection,
            gitlab_client=MagicMock(),
            task_uuid="task-uuid-001",
            progress_reporter=mock_progress_reporter,
        )

        mock_ctx = MagicMock()
        result = await tool.create_todo_list(
            project_id=10,
            mr_iid=5,
            todos=[{"title": "タスク1"}],
            context=mock_ctx,
        )

        assert result["status"] == "success"
        # todo_changed イベントが呈出されることを確認する
        mock_progress_reporter.report_progress.assert_called_once()
        call_kwargs = mock_progress_reporter.report_progress.call_args.kwargs
        assert call_kwargs["event"] == "todo_changed"


class TestIssueToMRConverter:
    """IssueToMRConverter のテスト"""

    async def test_issue_to_mr_converter_convert(
        self,
        mock_gitlab_client: MagicMock,
        mock_issue: MagicMock,
        mock_created_mr: MagicMock,
    ) -> None:
        """convertが正しい順序でGitLabクライアントのメソッドを呼び、GitLabMergeRequestを返すことを確認する"""
        # create_merge_requestが作成したMRを返すようにモックする
        mock_gitlab_client.create_merge_request.return_value = mock_created_mr
        # update_merge_requestが更新後のMRを返すようにモックする
        mock_gitlab_client.update_merge_request.return_value = mock_created_mr
        # get_issueがmock_issueを返すようにモックする（ラベル再取得用）
        mock_gitlab_client.get_issue.return_value = mock_issue
        # list_branchesが空リストを返すようにモックする
        mock_gitlab_client.list_branches.return_value = []
        # Issue Notesのモックを作成する（ユーザーコメント1件）
        user_note = MagicMock()
        user_note.system = False
        user_note.body = "テストコメント"
        mock_gitlab_client.get_issue_notes.return_value = [user_note]

        config = IssueToMRConfig(
            branch_prefix="feature/",
            target_branch="main",
            mr_title_template="WIP: {issue_title}",
            done_label="Done",
        )
        # LLMクライアントはgenerateメソッドを持たないシンプルなモック
        mock_llm_client = MagicMock(spec=[])

        converter = IssueToMRConverter(
            gitlab_client=mock_gitlab_client,
            chat_client=mock_llm_client,
            config=config,
        )

        result = await converter.convert(mock_issue)

        # ① ブランチが作成されることを確認する
        mock_gitlab_client.create_branch.assert_called_once()
        create_branch_kwargs = mock_gitlab_client.create_branch.call_args.kwargs
        assert create_branch_kwargs["project_id"] == 10
        assert create_branch_kwargs["ref"] == "main"

        # ② MRが作成されることを確認する
        mock_gitlab_client.create_merge_request.assert_called_once()
        create_mr_kwargs = mock_gitlab_client.create_merge_request.call_args.kwargs
        assert create_mr_kwargs["project_id"] == 10
        assert create_mr_kwargs["target_branch"] == "main"
        assert "テスト Issue タイトル" in create_mr_kwargs["title"]

        # ③ Issueのコメントが転記されることを確認する
        mock_gitlab_client.create_merge_request_note.assert_called()

        # ④ update_merge_requestでIssueのラベル・アサイニーがMRにコピーされることを確認する
        mock_gitlab_client.update_merge_request.assert_called_once()
        update_mr_kwargs = mock_gitlab_client.update_merge_request.call_args.kwargs
        assert update_mr_kwargs["project_id"] == 10
        assert update_mr_kwargs["mr_iid"] == mock_created_mr.iid

        # ⑤ IssueにMRリンクのコメントが投稿されることを確認する
        # （LLMがモックのため失敗し、LLM警告コメントも投稿されるため2回以上の呼び出しが期待される）
        assert mock_gitlab_client.create_issue_note.call_count >= 1
        issue_note_bodies = [
            call.kwargs.get("body", "")
            for call in mock_gitlab_client.create_issue_note.call_args_list
        ]
        assert any("Created MR: !" in body for body in issue_note_bodies)

        # ⑥ IssueにDoneラベルが設定されることを確認する
        mock_gitlab_client.update_issue_labels.assert_called_once()
        update_labels_kwargs = mock_gitlab_client.update_issue_labels.call_args.kwargs
        assert "Done" in update_labels_kwargs["labels"]

        # GitLabMergeRequestが返されることを確認する
        assert result == mock_created_mr
        assert result.iid == 55
