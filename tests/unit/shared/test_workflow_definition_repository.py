"""
WorkflowDefinitionRepository の単体テスト

workflow_definitionsテーブルへのCRUD操作の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from database.repositories.workflow_definition_repository import WorkflowDefinitionRepository


def _make_pool() -> tuple[MagicMock, AsyncMock]:
    """asyncpg.Pool のモックを生成する"""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


# テスト用のワークフロー定義サンプル
_SAMPLE_GRAPH = {
    "version": "1.0.0",
    "name": "test_workflow",
    "entry_node": "user_resolve",
    "nodes": [{"id": "user_resolve", "type": "executor"}],
    "edges": [],
}
_SAMPLE_AGENT = {
    "version": "1.0.0",
    "agents": [
        {
            "id": "task_classifier",
            "role": "planning",
            "input_keys": ["task_context"],
            "output_keys": ["result"],
        }
    ],
}
_SAMPLE_PROMPT = {
    "version": "1.0.0",
    "prompts": [
        {
            "id": "task_classifier",
            "role": "planning",
            "content": "You are a classifier...",
        }
    ],
}


class TestCreateWorkflowDefinition:
    """create_workflow_definition のテスト"""

    async def test_create_definition_success(self):
        """ワークフロー定義を正常に作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {
            "id": 1,
            "name": "test_workflow",
            "display_name": "テストワークフロー",
            "is_preset": False,
        }
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.create_workflow_definition(
            "test_workflow",
            "テストワークフロー",
            _SAMPLE_GRAPH,
            _SAMPLE_AGENT,
            _SAMPLE_PROMPT,
        )

        assert result["id"] == 1
        assert result["name"] == "test_workflow"
        conn.fetchrow.assert_awaited_once()

    async def test_create_preset_definition(self):
        """プリセットワークフロー定義を作成できることを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "name": "standard_mr_processing", "is_preset": True}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.create_workflow_definition(
            "standard_mr_processing",
            "標準MR処理",
            _SAMPLE_GRAPH,
            _SAMPLE_AGENT,
            _SAMPLE_PROMPT,
            is_preset=True,
        )

        assert result["is_preset"] is True
        # is_preset=True が引数に含まれることを確認する
        call_args = conn.fetchrow.call_args[0]
        assert True in call_args

    async def test_jsonb_definitions_are_serialized(self):
        """graph/agent/prompt 定義がJSONシリアライズされることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 1})

        repo = WorkflowDefinitionRepository(pool)
        await repo.create_workflow_definition(
            "test",
            "Test",
            _SAMPLE_GRAPH,
            _SAMPLE_AGENT,
            _SAMPLE_PROMPT,
        )

        call_args = conn.fetchrow.call_args[0]
        # JSON文字列が引数に含まれることを確認する
        assert any("entry_node" in str(a) for a in call_args)


class TestGetWorkflowDefinition:
    """get_workflow_definition のテスト"""

    async def test_returns_definition_when_found(self):
        """ワークフロー定義が存在する場合にレコードを返すことを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "name": "test_workflow"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.get_workflow_definition(1)

        assert result is not None
        assert result["id"] == 1

    async def test_returns_none_when_not_found(self):
        """ワークフロー定義が存在しない場合にNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.get_workflow_definition(9999)

        assert result is None


class TestGetWorkflowDefinitionByName:
    """get_workflow_definition_by_name のテスト"""

    async def test_returns_definition_by_name(self):
        """名前でワークフロー定義を取得できることを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "name": "standard_mr_processing"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.get_workflow_definition_by_name("standard_mr_processing")

        assert result is not None
        assert result["name"] == "standard_mr_processing"

    async def test_returns_none_for_unknown_name(self):
        """存在しない名前でNoneを返すことを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.get_workflow_definition_by_name("unknown_workflow")

        assert result is None


class TestUpdateWorkflowDefinition:
    """update_workflow_definition のテスト"""

    async def test_update_display_name(self):
        """表示名を更新できることを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "display_name": "新しい表示名"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.update_workflow_definition(1, display_name="新しい表示名")

        assert result is not None
        assert result["display_name"] == "新しい表示名"

    async def test_preset_definition_cannot_be_updated(self):
        """プリセット定義は更新できないことを検証する（is_preset=falseの条件付き）"""
        pool, conn = _make_pool()
        # is_preset=true の場合、UPDATE文の WHERE 条件により0件更新 → Noneを返す
        conn.fetchrow = AsyncMock(return_value=None)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.update_workflow_definition(1, display_name="不正更新")

        # プリセット定義の場合はNoneが返る
        assert result is None

    async def test_update_with_no_fields_returns_current(self):
        """更新フィールドが空の場合はget_workflow_definitionを呼ぶことを検証する"""
        pool, conn = _make_pool()
        expected = {"id": 1, "name": "test"}
        conn.fetchrow = AsyncMock(return_value=expected)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.update_workflow_definition(1)

        conn.fetchrow.assert_awaited_once()

    async def test_update_graph_definition_serializes_json(self):
        """グラフ定義がJSONシリアライズされて更新されることを検証する"""
        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value={"id": 1})

        repo = WorkflowDefinitionRepository(pool)
        new_graph = {"version": "2.0.0", "nodes": []}
        await repo.update_workflow_definition(1, graph_definition=new_graph)

        call_args = conn.fetchrow.call_args[0]
        assert any("2.0.0" in str(a) for a in call_args)


class TestDeleteWorkflowDefinition:
    """delete_workflow_definition のテスト"""

    async def test_delete_existing_definition(self):
        """存在するワークフロー定義を削除できることを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 1")

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.delete_workflow_definition(1)

        assert result is True

    async def test_delete_preset_returns_false(self):
        """プリセット定義は削除できないことを検証する（is_preset=falseの条件付き）"""
        pool, conn = _make_pool()
        # is_preset=true の定義はWHERE条件で除外されるため0件削除になる
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.delete_workflow_definition(1)

        assert result is False

    async def test_delete_nonexistent_returns_false(self):
        """存在しないIDを削除しようとした場合にFalseを返すことを検証する"""
        pool, conn = _make_pool()
        conn.execute = AsyncMock(return_value="DELETE 0")

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.delete_workflow_definition(9999)

        assert result is False


class TestListWorkflowDefinitions:
    """list_workflow_definitions のテスト"""

    async def test_list_all_definitions(self):
        """全ワークフロー定義一覧を取得できることを検証する"""
        pool, conn = _make_pool()
        expected_rows = [
            {"id": 1, "name": "standard_mr_processing", "is_preset": True},
            {"id": 2, "name": "custom_workflow", "is_preset": False},
        ]
        conn.fetch = AsyncMock(return_value=expected_rows)

        repo = WorkflowDefinitionRepository(pool)
        result = await repo.list_workflow_definitions()

        assert len(result) == 2

    async def test_filter_by_is_preset(self):
        """is_presetでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = WorkflowDefinitionRepository(pool)
        await repo.list_workflow_definitions(is_preset=True)

        call_args = conn.fetch.call_args[0]
        assert any("is_preset" in str(a) for a in call_args)

    async def test_filter_by_is_active(self):
        """is_activeでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = WorkflowDefinitionRepository(pool)
        await repo.list_workflow_definitions(is_active=True)

        call_args = conn.fetch.call_args[0]
        assert any("is_active" in str(a) for a in call_args)

    async def test_filter_by_created_by(self):
        """作成者メールアドレスでフィルタリングできることを検証する"""
        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        repo = WorkflowDefinitionRepository(pool)
        await repo.list_workflow_definitions(created_by="creator@example.com")

        call_args = conn.fetch.call_args[0]
        assert "creator@example.com" in call_args
