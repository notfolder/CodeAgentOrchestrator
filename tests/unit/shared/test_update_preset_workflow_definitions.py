"""
update_preset_workflow_definitions の単体テスト

update_preset_workflow_definitions() の正常系・異常系を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.seeds.update_preset_workflow_definitions import (
    update_preset_workflow_definitions,
)
from database.seeds.seed_workflow_definitions import _PRESETS
from database.repositories.workflow_definition_repository import (
    WorkflowDefinitionRepository,
)


# ========================================
# テスト用ヘルパー
# ========================================


def _make_repo(
    existing_name: str | None = None,
    update_returns_none: bool = False,
) -> MagicMock:
    """
    WorkflowDefinitionRepositoryのモックを生成する。

    Args:
        existing_name: 既存扱いにするプリセット名。Noneの場合は全て未登録。
        update_returns_none: update_preset_workflow_definition がNoneを返すか否か。
    """
    repo = MagicMock(spec=WorkflowDefinitionRepository)

    async def _get_by_name(name: str) -> dict | None:
        if existing_name is not None and name == existing_name:
            return {"id": 1, "name": name}
        return None

    repo.get_workflow_definition_by_name = AsyncMock(side_effect=_get_by_name)
    repo.create_workflow_definition = AsyncMock(
        return_value={"id": 99, "name": "dummy"}
    )
    repo.update_preset_workflow_definition = AsyncMock(
        return_value=None if update_returns_none else {"id": 1, "name": "updated"}
    )
    return repo


# ========================================
# TestUpdatePresetWorkflowDefinitions
# ========================================


class TestUpdatePresetWorkflowDefinitions:
    """update_preset_workflow_definitions() の単体テスト"""

    async def test_既存プリセットが全て更新される(self) -> None:
        """
        全プリセットが登録済みの場合に、全て「updated」に入ることを確認する。
        """
        repo = MagicMock(spec=WorkflowDefinitionRepository)
        repo.get_workflow_definition_by_name = AsyncMock(
            return_value={"id": 1, "name": "existing"}
        )
        repo.update_preset_workflow_definition = AsyncMock(
            return_value={"id": 1, "name": "updated"}
        )
        repo.create_workflow_definition = AsyncMock()

        result = await update_preset_workflow_definitions(repo)

        assert len(result["updated"]) == len(_PRESETS)
        assert result["created"] == []
        assert result["failed"] == []
        # create は呼ばれない
        repo.create_workflow_definition.assert_not_awaited()

    async def test_未登録プリセットが全て新規登録される(self) -> None:
        """
        全プリセットが未登録の場合に、全て「created」に入ることを確認する。
        """
        repo = _make_repo(existing_name=None)

        result = await update_preset_workflow_definitions(repo)

        assert result["updated"] == []
        assert len(result["created"]) == len(_PRESETS)
        assert result["failed"] == []
        # update は呼ばれない
        repo.update_preset_workflow_definition.assert_not_awaited()

    async def test_既存プリセットは更新され未登録は新規登録される(self) -> None:
        """
        一部のプリセットが登録済みで一部が未登録の場合に、
        登録済みは更新・未登録は新規登録されることを確認する。
        """
        # standard_mr_processing のみ既存の状態
        repo = _make_repo(existing_name="standard_mr_processing")

        result = await update_preset_workflow_definitions(repo)

        assert "standard_mr_processing" in result["updated"]
        assert "multi_codegen_mr_processing" in result["created"]
        assert result["failed"] == []

    async def test_update_preset_workflow_definitionがis_preset制約なしで呼ばれる(
        self,
    ) -> None:
        """
        update_preset_workflow_definition() が呼ばれることを確認する
        （is_preset=falseの制約がない専用メソッドを使用している）。
        """
        repo = MagicMock(spec=WorkflowDefinitionRepository)
        repo.get_workflow_definition_by_name = AsyncMock(
            return_value={"id": 42, "name": "any"}
        )
        repo.update_preset_workflow_definition = AsyncMock(
            return_value={"id": 42, "name": "updated"}
        )

        await update_preset_workflow_definitions(repo)

        assert repo.update_preset_workflow_definition.await_count == len(_PRESETS)
        for call_args in repo.update_preset_workflow_definition.call_args_list:
            # 第1引数（workflow_id）が正しく渡されることを確認する
            assert call_args.args[0] == 42

    async def test_更新結果がNoneの場合はfailedに入る(self) -> None:
        """
        update_preset_workflow_definition() がNoneを返した場合に
        そのプリセットが「failed」に分類されることを確認する。
        """
        repo = MagicMock(spec=WorkflowDefinitionRepository)
        repo.get_workflow_definition_by_name = AsyncMock(
            return_value={"id": 1, "name": "existing"}
        )
        # Noneを返す（レコード消失を想定）
        repo.update_preset_workflow_definition = AsyncMock(return_value=None)

        result = await update_preset_workflow_definitions(repo)

        assert len(result["failed"]) == len(_PRESETS)
        assert result["updated"] == []

    async def test_新規登録時に例外が発生した場合はfailedに入る(self) -> None:
        """
        create_workflow_definition() で例外が発生した場合に
        「failed」に分類されることを確認する。
        """
        repo = _make_repo(existing_name=None)
        repo.create_workflow_definition = AsyncMock(
            side_effect=RuntimeError("DB挿入エラー")
        )

        result = await update_preset_workflow_definitions(repo)

        assert len(result["failed"]) == len(_PRESETS)
        assert result["created"] == []

    async def test_graph_definition辞書で渡される(self) -> None:
        """
        JSONファイルから読み込んだ定義が辞書型で update_preset_workflow_definition に渡されることを確認する。
        """
        repo = MagicMock(spec=WorkflowDefinitionRepository)
        repo.get_workflow_definition_by_name = AsyncMock(
            return_value={"id": 1, "name": "existing"}
        )
        repo.update_preset_workflow_definition = AsyncMock(
            return_value={"id": 1, "name": "updated"}
        )

        await update_preset_workflow_definitions(repo)

        for call_args in repo.update_preset_workflow_definition.call_args_list:
            assert isinstance(call_args.kwargs.get("graph_definition"), dict)
            assert isinstance(call_args.kwargs.get("agent_definition"), dict)
            assert isinstance(call_args.kwargs.get("prompt_definition"), dict)

    async def test_YAMLファイルが見つからない場合はfailedに入る(self) -> None:
        """
        定義YAMLファイルが存在しない場合にそのプリセットが「failed」に入ることを確認する。
        """
        repo = MagicMock(spec=WorkflowDefinitionRepository)
        repo.get_workflow_definition_by_name = AsyncMock(return_value=None)
        repo.create_workflow_definition = AsyncMock()

        with patch(
            "database.seeds.update_preset_workflow_definitions._load_definition_file",
            side_effect=FileNotFoundError("ファイルが見つかりません"),
        ):
            result = await update_preset_workflow_definitions(repo)

        assert len(result["failed"]) == len(_PRESETS)
        assert result["updated"] == []
        assert result["created"] == []

    async def test_返り値に全キーが含まれる(self) -> None:
        """
        戻り値の辞書に updated・created・failed の3キーが含まれることを確認する。
        """
        repo = _make_repo(existing_name=None)

        result = await update_preset_workflow_definitions(repo)

        assert "updated" in result
        assert "created" in result
        assert "failed" in result
