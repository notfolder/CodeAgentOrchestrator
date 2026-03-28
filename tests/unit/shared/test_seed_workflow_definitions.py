"""
seed_workflow_definitions の単体テスト

seed_workflow_definitions()・_load_definition_file()の正常系・異常系を検証する。

IMPLEMENTATION_PLAN.md フェーズ9-1 に準拠する。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from database.seeds.seed_workflow_definitions import (
    _DEFINITIONS_DIR,
    _PRESETS,
    _load_definition_file,
    seed_workflow_definitions,
)
from database.repositories.workflow_definition_repository import (
    WorkflowDefinitionRepository,
)


# ========================================
# テスト用ヘルパー
# ========================================


def _make_repo(existing_name: str | None = None) -> MagicMock:
    """
    WorkflowDefinitionRepositoryのモックを生成する。

    Args:
        existing_name: 既存プリセット名。None の場合は未登録とする。
    """
    repo = MagicMock(spec=WorkflowDefinitionRepository)

    async def _get_by_name(name: str) -> dict | None:
        if existing_name is not None and name == existing_name:
            return {"id": 1, "name": name}
        return None

    repo.get_workflow_definition_by_name = AsyncMock(side_effect=_get_by_name)
    repo.create_workflow_definition = AsyncMock(return_value={"id": 1, "name": "dummy"})
    return repo


# ========================================
# TestLoadJson
# ========================================


class TestLoadJson:
    """_load_definition_file() の単体テスト"""

    def test_正常なYAMLファイルを読み込める(self) -> None:
        """docs/definitions/ に存在する定義ファイルが正常に読み込めることを確認する"""
        # 標準MR処理グラフ定義ファイル（実際に存在するファイルを使用）
        data = _load_definition_file("standard_mr_processing_graph.yaml")

        assert isinstance(data, dict)
        assert "version" in data
        assert "nodes" in data

    def test_存在しないファイルはFileNotFoundErrorを発生させる(self) -> None:
        """存在しないファイル名を指定した場合にFileNotFoundErrorが発生することを確認する"""
        with pytest.raises(FileNotFoundError, match="定義ファイルが見つかりません"):
            _load_definition_file("nonexistent_file.json")

    def test_全プリセットの定義ファイルが読み込める(self) -> None:
        """
        _PARETSに定義された全ての定義ファイルが読み込めることを確認する。
        """
        for preset in _PRESETS:
            # グラフ・エージェント・プロンプト定義の各ファイルが読み込めることを確認する
            graph_def = _load_definition_file(preset["graph_file"])
            agent_def = _load_definition_file(preset["agent_file"])
            prompt_def = _load_definition_file(preset["prompt_file"])

            assert isinstance(
                graph_def, dict
            ), f"グラフ定義の読み込み失敗: {preset['graph_file']}"
            assert isinstance(
                agent_def, dict
            ), f"エージェント定義の読み込み失敗: {preset['agent_file']}"
            assert isinstance(
                prompt_def, dict
            ), f"プロンプト定義の読み込み失敗: {preset['prompt_file']}"


# ========================================
# TestSeedWorkflowDefinitions
# ========================================


class TestSeedWorkflowDefinitions:
    """seed_workflow_definitions() の単体テスト"""

    async def test_未登録プリセットが全て登録される(self) -> None:
        """
        どのプリセットも登録されていない場合に、全プリセットが登録されることを確認する。
        """
        repo = _make_repo(existing_name=None)

        result = await seed_workflow_definitions(repo)

        # 2プリセットが登録されることを確認する
        assert len(result) == 2
        assert "standard_mr_processing" in result
        assert "multi_codegen_mr_processing" in result

        # create_workflow_definitionが2回呼ばれることを確認する
        assert repo.create_workflow_definition.await_count == 2

    async def test_既存プリセットはスキップされる(self) -> None:
        """
        既に登録済みのプリセットがスキップされることを確認する（冪等性）。
        """
        # standard_mr_processing が既に登録済みの状態
        repo = _make_repo(existing_name="standard_mr_processing")

        result = await seed_workflow_definitions(repo)

        # multi_codegen_mr_processing のみ登録されることを確認する
        assert len(result) == 1
        assert "multi_codegen_mr_processing" in result
        assert "standard_mr_processing" not in result

        # create_workflow_definitionが1回のみ呼ばれることを確認する
        assert repo.create_workflow_definition.await_count == 1

    async def test_全プリセットが登録済みの場合は空リストを返す(self) -> None:
        """
        全プリセットが登録済みの場合に空リストが返されることを確認する（冪等性）。
        """
        repo = MagicMock(spec=WorkflowDefinitionRepository)
        # 全プリセットが登録済みを返す
        repo.get_workflow_definition_by_name = AsyncMock(
            return_value={"id": 1, "name": "already_registered"}
        )
        repo.create_workflow_definition = AsyncMock()

        result = await seed_workflow_definitions(repo)

        assert result == []
        repo.create_workflow_definition.assert_not_awaited()

    async def test_is_preset_Trueで登録される(self) -> None:
        """
        create_workflow_definitionがis_preset=Trueで呼ばれることを確認する。
        """
        repo = _make_repo(existing_name=None)

        await seed_workflow_definitions(repo)

        # 全ての登録呼び出しでis_preset=Trueが使用されていることを確認する
        for call_args in repo.create_workflow_definition.call_args_list:
            assert call_args.kwargs.get("is_preset") is True, (
                f"is_preset=Trueでないcreate_workflow_definition呼び出しがあります: "
                f"{call_args}"
            )

    async def test_登録順序が正しい(self) -> None:
        """
        standard_mr_processing → multi_codegen_mr_processing の順で登録されることを確認する。
        """
        repo = _make_repo(existing_name=None)

        result = await seed_workflow_definitions(repo)

        assert result[0] == "standard_mr_processing"
        assert result[1] == "multi_codegen_mr_processing"

    async def test_正しいnameとdisplay_nameで登録される(self) -> None:
        """
        各プリセットが正しいname・display_nameで登録されることを確認する。
        """
        repo = _make_repo(existing_name=None)

        await seed_workflow_definitions(repo)

        calls = repo.create_workflow_definition.call_args_list
        assert len(calls) == 2

        # 1件目: standard_mr_processing
        first_call = calls[0]
        assert first_call.kwargs.get("name") == "standard_mr_processing"
        assert first_call.kwargs.get("display_name") == "標準MR処理"

        # 2件目: multi_codegen_mr_processing
        second_call = calls[1]
        assert second_call.kwargs.get("name") == "multi_codegen_mr_processing"
        assert second_call.kwargs.get("display_name") == "複数コード生成並列処理"

    async def test_グラフ定義が辞書として登録される(self) -> None:
        """
        JSONから読み込んだグラフ定義が辞書型として登録されることを確認する。
        """
        repo = _make_repo(existing_name=None)

        await seed_workflow_definitions(repo)

        for call_args in repo.create_workflow_definition.call_args_list:
            graph_def = call_args.kwargs.get("graph_definition")
            agent_def = call_args.kwargs.get("agent_definition")
            prompt_def = call_args.kwargs.get("prompt_definition")

            assert isinstance(graph_def, dict), "graph_definitionが辞書型ではありません"
            assert isinstance(agent_def, dict), "agent_definitionが辞書型ではありません"
            assert isinstance(
                prompt_def, dict
            ), "prompt_definitionが辞書型ではありません"
