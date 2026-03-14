"""
TodoManagementTool モジュール

PostgreSQL を使った Todo リスト管理ツールクラスを定義する。
LLM エージェントが FunctionTool として呼び出せるインターフェースを提供し、
PostgreSQL への直接操作を担う。

AUTOMATA_CODEX_SPEC.md §9.3（Todo Managementツール）および
CLASS_IMPLEMENTATION_SPEC.md § 10.1（TodoManagementTool）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)

# Todo ステータス定数
_STATUS_COMPLETED = "completed"

# Markdown チェックボックスの文字列
_CHECK_DONE = "[x]"
_CHECK_TODO = "[ ]"


def _todo_to_checkbox(status: str) -> str:
    """
    Todo のステータスを Markdown チェックボックス文字列に変換する。

    Args:
        status: Todo のステータス文字列

    Returns:
        "[x]"（completed）または "[ ]"（その他）
    """
    return _CHECK_DONE if status == _STATUS_COMPLETED else _CHECK_TODO


class TodoManagementTool:
    """
    PostgreSQL Todo リスト管理ツール。

    LLM エージェントの FunctionTool として機能し、
    PostgreSQL の todos テーブルへの直接操作を担う。
    各 Todo 操作後に ProgressReporter に `todo_changed` イベントを呈出し、
    進捗報告コメントのセクション③.5（Todoリスト）を自動更新する。

    提供するメソッド（AUTOMATA_CODEX_SPEC.md §9.3）:
    - create_todo_list: Todoリスト一括作成
    - get_todo_list: Todoリスト取得
    - update_todo_status: Todo状態更新
    - add_todo: Todo追加
    - delete_todo: Todo削除
    - reorder_todos: Todo順序変更
    - sync_to_gitlab: GitLab MRへのMarkdown同期（内部用）

    CLASS_IMPLEMENTATION_SPEC.md § 10.1 に準拠する。

    Attributes:
        db_connection: asyncpg の Connection または Pool
        gitlab_client: GitLab API クライアント
        task_uuid: 現在のタスクを識別する UUID 文字列
        progress_reporter: 進捗報告インスタンス（None の場合は todo_changed を呈出しない）
    """

    def __init__(
        self,
        db_connection: Any,
        gitlab_client: "GitlabClient",
        task_uuid: str,
        progress_reporter: Any = None,
    ) -> None:
        """
        初期化。

        Args:
            db_connection: asyncpg.Connection または asyncpg.Pool
            gitlab_client: GitLab API クライアント
            task_uuid: 現在のタスク UUID（各タスク実行コンテキストで一意）
            progress_reporter: 進捗報告インスタンス（省略時は todo_changed を呈出しない）
        """
        self.db_connection = db_connection
        self.gitlab_client = gitlab_client
        self.task_uuid = task_uuid
        self.progress_reporter = progress_reporter

    async def _emit_todo_changed(self, context: Any, todo_markdown: str) -> None:
        """
        ProgressReporter に todo_changed イベントを呈出する。

        progress_reporter が設定されている場合のみ呼び出す。
        AUTOMATA_CODEX_SPEC.md §6.2・§9.3 の仕様に基づき、
        Todoツール呼び出し直後にセクション③.5（Todoリスト）を更新する。

        Args:
            context: ワークフローコンテキスト
            todo_markdown: 最新 Todo リストの Markdown テキスト
        """
        if self.progress_reporter is None:
            return
        try:
            await self.progress_reporter.report_progress(
                context=context,
                event="todo_changed",
                node_id="",
                details={"todo_markdown": todo_markdown},
            )
        except Exception as exc:
            logger.warning(
                "todo_changed イベントの呈出に失敗しました: %s", exc
            )

    async def _get_todo_markdown(self) -> str:
        """
        現在の Todo リストを Markdown 形式で取得する（内部ヘルパー）。

        Returns:
            Markdown 形式の Todo リスト文字列
        """
        rows = await self.db_connection.fetch(
            """
            SELECT id, title, status, parent_todo_id
            FROM todos
            WHERE task_uuid = $1
            ORDER BY order_index
            """,
            self.task_uuid,
        )

        todo_by_id: dict[int, dict[str, Any]] = {
            row["id"]: dict(row) for row in rows
        }
        children_map: dict[int | None, list[dict[str, Any]]] = {}
        for todo in todo_by_id.values():
            parent_id: int | None = todo.get("parent_todo_id")
            children_map.setdefault(parent_id, []).append(todo)

        lines: list[str] = []

        def _render(parent_id: int | None, indent: int) -> None:
            for todo in children_map.get(parent_id, []):
                checkbox = _todo_to_checkbox(todo["status"])
                lines.append(f"{'  ' * indent}- {checkbox} {todo['title']}")
                _render(todo["id"], indent + 1)

        _render(None, 0)
        return "\n".join(lines)

    async def create_todo_list(
        self,
        project_id: int,
        mr_iid: int,
        todos: list[dict[str, Any]],
        context: Any = None,
    ) -> dict[str, Any]:
        """
        Todo リストを PostgreSQL に一括登録する。

        todos の各要素を todos テーブルに INSERT し、
        生成された todo_id のリストを返す。
        登録後に ProgressReporter に todo_changed イベントを呈出する。

        Args:
            project_id: GitLab プロジェクト ID（将来の拡張用）
            mr_iid: MergeRequest IID（将来の拡張用）
            todos: 登録する Todo 情報のリスト
                各要素: {"title": str, "description": str (optional),
                          "status": str (optional), "parent_todo_id": int (optional)}
            context: ワークフローコンテキスト（todo_changed イベント呈出用。省略可）

        Returns:
            {"status": "success", "todo_ids": [id1, id2, ...]}
        """
        todo_ids: list[int] = []

        for order_index, todo in enumerate(todos):
            title: str = todo.get("title", "")
            description: str = todo.get("description", "")
            status: str = todo.get("status", "not-started")

            # todos テーブルに INSERT して生成された ID を取得する
            row = await self.db_connection.fetchrow(
                """
                INSERT INTO todos
                    (task_uuid, title, description, status, order_index)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                self.task_uuid,
                title,
                description,
                status,
                order_index,
            )
            todo_id: int = row["id"]
            todo_ids.append(todo_id)
            logger.debug(
                "Todo登録: task_uuid=%s, todo_id=%d, title=%s",
                self.task_uuid,
                todo_id,
                title,
            )

        logger.info(
            "Todoリスト登録完了: task_uuid=%s, 件数=%d",
            self.task_uuid,
            len(todo_ids),
        )

        # todo_changed イベントを ProgressReporter に呈出する
        if context is not None:
            todo_markdown = await self._get_todo_markdown()
            await self._emit_todo_changed(context, todo_markdown)

        return {"status": "success", "todo_ids": todo_ids}

    async def sync_to_gitlab(
        self,
        project_id: int,
        mr_iid: int,
        task_uuid: str | None = None,
    ) -> dict[str, Any]:
        """
        PostgreSQL の Todo リストを Markdown 形式に変換して GitLab MR にコメント投稿する。

        親子関係を考慮した階層構造の Markdown チェックリストを生成する。

        Args:
            project_id: GitLab プロジェクト ID
            mr_iid: MergeRequest IID
            task_uuid: 取得対象のタスク UUID（省略時は self.task_uuid を使用）

        Returns:
            {"status": "success"}
        """
        target_uuid = task_uuid if task_uuid is not None else self.task_uuid

        # ① PostgreSQL から Todo 一覧を取得する
        rows = await self.db_connection.fetch(
            """
            SELECT id, title, status, parent_todo_id
            FROM todos
            WHERE task_uuid = $1
            ORDER BY order_index
            """,
            target_uuid,
        )

        # ② 親子関係を考慮して Markdown 形式に変換する
        # まず全 todo を id でインデックス化する
        todo_by_id: dict[int, dict[str, Any]] = {
            row["id"]: dict(row) for row in rows
        }

        # 親ノードごとに子ノードをまとめる
        children_map: dict[int | None, list[dict[str, Any]]] = {}
        for todo in todo_by_id.values():
            parent_id: int | None = todo.get("parent_todo_id")
            children_map.setdefault(parent_id, []).append(todo)

        lines: list[str] = ["## 📋 Todo リスト", ""]

        def _render_todos(
            parent_id: int | None,
            indent_level: int,
        ) -> None:
            """再帰的に Todo を Markdown 形式で出力する。"""
            for todo in children_map.get(parent_id, []):
                checkbox = _todo_to_checkbox(todo["status"])
                indent = "  " * indent_level
                lines.append(f"{indent}- {checkbox} {todo['title']}")
                # 子 Todo を再帰的に処理する
                _render_todos(todo["id"], indent_level + 1)

        _render_todos(None, 0)

        markdown_content = "\n".join(lines)

        # ③ GitLab MR にコメントとして投稿する
        self.gitlab_client.create_merge_request_note(
            project_id, mr_iid, markdown_content
        )
        logger.info(
            "TodoリストをGitLabに同期: project_id=%d, mr_iid=%d, task_uuid=%s",
            project_id,
            mr_iid,
            target_uuid,
        )

        return {"status": "success"}

    async def get_todo_list(
        self,
        project_id: int,
        mr_iid: int,
    ) -> dict[str, Any]:
        """
        現在の Todo リストを PostgreSQL から取得して返す。

        AUTOMATA_CODEX_SPEC.md §9.3 の `get_todo_list` に準拠する。
        このメソッドは todo_changed イベントを呈出しない（読み取り専用）。

        Args:
            project_id: GitLab プロジェクト ID（将来の拡張用）
            mr_iid: MergeRequest IID（将来の拡張用）

        Returns:
            {"status": "success", "todos": [{id, title, status, parent_todo_id, order_index}, ...]}
        """
        rows = await self.db_connection.fetch(
            """
            SELECT id, title, description, status, parent_todo_id, order_index
            FROM todos
            WHERE task_uuid = $1
            ORDER BY order_index
            """,
            self.task_uuid,
        )
        todos = [dict(row) for row in rows]
        logger.info(
            "Todoリスト取得: task_uuid=%s, 件数=%d",
            self.task_uuid,
            len(todos),
        )
        return {"status": "success", "todos": todos}

    async def update_todo_status(
        self,
        todo_id: int,
        status: str,
        context: Any = None,
    ) -> dict[str, Any]:
        """
        指定した Todo のステータスを更新する。

        AUTOMATA_CODEX_SPEC.md §9.3 の `update_todo_status` に準拠する。
        更新後に ProgressReporter に todo_changed イベントを呈出する。

        状態遷移:
        - not-started → in-progress → completed
        - not-started → failed
        - in-progress → failed

        Args:
            todo_id: 更新対象の Todo ID
            status: 新しいステータス（not-started / in-progress / completed / failed）
            context: ワークフローコンテキスト（todo_changed イベント呈出用。省略可）

        Returns:
            {"status": "success", "todo_id": todo_id, "new_status": status}
        """
        result = await self.db_connection.execute(
            """
            UPDATE todos
            SET status = $1
            WHERE id = $2 AND task_uuid = $3
            """,
            status,
            todo_id,
            self.task_uuid,
        )
        logger.info(
            "Todo状態更新: task_uuid=%s, todo_id=%d, status=%s, result=%s",
            self.task_uuid,
            todo_id,
            status,
            result,
        )

        # todo_changed イベントを ProgressReporter に呈出する
        if context is not None:
            todo_markdown = await self._get_todo_markdown()
            await self._emit_todo_changed(context, todo_markdown)

        return {"status": "success", "todo_id": todo_id, "new_status": status}

    async def add_todo(
        self,
        project_id: int,
        mr_iid: int,
        title: str,
        description: str = "",
        parent_todo_id: int | None = None,
        context: Any = None,
    ) -> dict[str, Any]:
        """
        新しい Todo を追加する。

        AUTOMATA_CODEX_SPEC.md §9.3 の `add_todo` に準拠する。
        追加後に ProgressReporter に todo_changed イベントを呈出する。

        Args:
            project_id: GitLab プロジェクト ID（将来の拡張用）
            mr_iid: MergeRequest IID（将来の拡張用）
            title: Todo のタイトル
            description: Todo の説明（省略可）
            parent_todo_id: 親 Todo の ID（省略時はルートレベル）
            context: ワークフローコンテキスト（todo_changed イベント呈出用。省略可）

        Returns:
            {"status": "success", "todo_id": 追加された Todo の ID}
        """
        # 既存の Todo の最大 order_index を取得して末尾に追加する
        max_row = await self.db_connection.fetchrow(
            """
            SELECT COALESCE(MAX(order_index), -1) AS max_idx
            FROM todos
            WHERE task_uuid = $1 AND parent_todo_id IS NOT DISTINCT FROM $2
            """,
            self.task_uuid,
            parent_todo_id,
        )
        order_index: int = (max_row["max_idx"] if max_row["max_idx"] is not None else -1) + 1

        row = await self.db_connection.fetchrow(
            """
            INSERT INTO todos
                (task_uuid, title, description, status, order_index, parent_todo_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            self.task_uuid,
            title,
            description,
            "not-started",
            order_index,
            parent_todo_id,
        )
        todo_id: int = row["id"]
        logger.info(
            "Todo追加: task_uuid=%s, todo_id=%d, title=%s, parent_todo_id=%s",
            self.task_uuid,
            todo_id,
            title,
            parent_todo_id,
        )

        # todo_changed イベントを ProgressReporter に呈出する
        if context is not None:
            todo_markdown = await self._get_todo_markdown()
            await self._emit_todo_changed(context, todo_markdown)

        return {"status": "success", "todo_id": todo_id}

    async def delete_todo(
        self,
        todo_id: int,
        context: Any = None,
    ) -> dict[str, Any]:
        """
        指定した Todo を削除する。

        AUTOMATA_CODEX_SPEC.md §9.3 の `delete_todo` に準拠する。
        子 Todo は CASCADE で自動削除される（todos テーブルの外部キー制約による）。
        削除後に ProgressReporter に todo_changed イベントを呈出する。

        Args:
            todo_id: 削除対象の Todo ID
            context: ワークフローコンテキスト（todo_changed イベント呈出用。省略可）

        Returns:
            {"status": "success", "todo_id": todo_id}
        """
        await self.db_connection.execute(
            """
            DELETE FROM todos
            WHERE id = $1 AND task_uuid = $2
            """,
            todo_id,
            self.task_uuid,
        )
        logger.info(
            "Todo削除: task_uuid=%s, todo_id=%d",
            self.task_uuid,
            todo_id,
        )

        # todo_changed イベントを ProgressReporter に呈出する
        if context is not None:
            todo_markdown = await self._get_todo_markdown()
            await self._emit_todo_changed(context, todo_markdown)

        return {"status": "success", "todo_id": todo_id}

    async def reorder_todos(
        self,
        todo_ids: list[int],
        context: Any = None,
    ) -> dict[str, Any]:
        """
        Todo の表示順序を変更する。

        AUTOMATA_CODEX_SPEC.md §9.3 の `reorder_todos` に準拠する。
        todo_ids の順番で order_index を 0 から連番で更新する。
        変更後に ProgressReporter に todo_changed イベントを呈出する。

        Args:
            todo_ids: 新しい表示順で並べた Todo ID のリスト
            context: ワークフローコンテキスト（todo_changed イベント呈出用。省略可）

        Returns:
            {"status": "success", "reordered_count": 更新した件数}
        """
        for new_order, todo_id in enumerate(todo_ids):
            await self.db_connection.execute(
                """
                UPDATE todos
                SET order_index = $1
                WHERE id = $2 AND task_uuid = $3
                """,
                new_order,
                todo_id,
                self.task_uuid,
            )
            logger.debug(
                "Todo順序変更: task_uuid=%s, todo_id=%d, new_order=%d",
                self.task_uuid,
                todo_id,
                new_order,
            )

        logger.info(
            "Todo順序変更完了: task_uuid=%s, 件数=%d",
            self.task_uuid,
            len(todo_ids),
        )

        # todo_changed イベントを ProgressReporter に呈出する
        if context is not None:
            todo_markdown = await self._get_todo_markdown()
            await self._emit_todo_changed(context, todo_markdown)

        return {"status": "success", "reordered_count": len(todo_ids)}
