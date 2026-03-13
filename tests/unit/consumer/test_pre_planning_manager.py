"""
PrePlanningManagerの単体テスト

LLMクライアントとMCPクライアントをモックして計画前情報収集フェーズの
タスク理解・環境情報収集・実行環境選択を検証する。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from planning.pre_planning_manager import PrePlanningManager


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """モックLLMクライアントを返す"""
    client = MagicMock()
    # generateメソッドをasyncで動作させる（デフォルトはpythonを選択）
    response = json.dumps(
        {"selected_environment": "python", "reasoning": "requirements.txtが存在するため"}
    )
    client.generate = AsyncMock(return_value=response)
    return client


@pytest.fixture
def mock_mcp_clients() -> dict[str, MagicMock]:
    """モックMCPクライアント辞書を返す"""
    text_editor = MagicMock()
    text_editor.call_tool.return_value = {"files": ["requirements.txt", "README.md"]}
    return {"text_editor": text_editor}


@pytest.fixture
def pre_planning_manager(
    mock_llm_client: MagicMock,
    mock_mcp_clients: dict[str, MagicMock],
) -> PrePlanningManager:
    """テスト用PrePlanningManagerを返す"""
    return PrePlanningManager(
        config={},
        llm_client=mock_llm_client,
        mcp_clients=mock_mcp_clients,
    )


# ========================================
# TestPrePlanningManagerExecute
# ========================================


class TestPrePlanningManagerExecute:
    """PrePlanningManager.execute()のテスト"""

    @pytest.mark.asyncio
    async def test_executeが全処理を実行して結果を返す(
        self,
        pre_planning_manager: PrePlanningManager,
    ) -> None:
        """モックされたllm_clientでexecute()が期待するキーを持つ辞書を返すことを確認する"""
        result = await pre_planning_manager.execute(
            task_uuid="test-uuid",
            task_description="Pythonでアプリを実装してください",
            plan_environment_id="plan-env-001",
        )

        # 期待するキーが全て含まれていることを確認する
        assert "understanding_result" in result
        assert "environment_info" in result
        assert "selected_environment" in result
        assert "selection_details" in result

    @pytest.mark.asyncio
    async def test_selected_environmentが有効な環境名を返す(
        self,
        pre_planning_manager: PrePlanningManager,
    ) -> None:
        """select_execution_environment()が有効な環境名を返すことを確認する"""
        valid_environments = {"python", "miniforge", "node", "default"}

        result = await pre_planning_manager.execute(
            task_uuid="test-uuid",
            task_description="環境選択テスト",
            plan_environment_id="plan-env-001",
        )

        assert result["selected_environment"] in valid_environments

    @pytest.mark.asyncio
    async def test_llm応答が無効な環境名の場合はdefaultを使用する(
        self,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """無効な環境名(例:"ruby")をLLMが返した場合に"default"が使用されることを確認する"""
        # LLMが無効な環境名を返すクライアントを作成する
        invalid_llm_client = MagicMock()
        # タスク理解用の呼び出しと環境選択用の呼び出しを分ける
        invalid_env_response = json.dumps(
            {"selected_environment": "ruby", "reasoning": "Rubyのプロジェクトのため"}
        )
        # generateが複数回呼ばれる場合、1回目はタスク理解、2回目は環境選択
        invalid_llm_client.generate = AsyncMock(
            side_effect=["タスク理解完了", invalid_env_response]
        )

        manager = PrePlanningManager(
            config={},
            llm_client=invalid_llm_client,
            mcp_clients=mock_mcp_clients,
        )

        result = await manager.execute(
            task_uuid="test-uuid",
            task_description="Rubyアプリを実装してください",
            plan_environment_id="plan-env-001",
        )

        # 無効な環境名が返された場合は"default"が使用されることを確認する
        assert result["selected_environment"] == "default"


# ========================================
# TestPrePlanningManagerProgressManager
# ========================================


class TestPrePlanningManagerProgressManager:
    """PrePlanningManager の task / progress_manager フィールドのテスト（§8.2・§8.3）"""

    def test_taskとprogress_managerフィールドが省略可能で設定される(
        self,
        mock_llm_client: MagicMock,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """task と progress_manager が省略可能であり、設定した値が保持されることを確認する"""
        mock_task = MagicMock(name="Task")
        mock_pm = MagicMock(name="ProgressManager")

        manager = PrePlanningManager(
            config={},
            llm_client=mock_llm_client,
            mcp_clients=mock_mcp_clients,
            task=mock_task,
            progress_manager=mock_pm,
        )
        assert manager.task is mock_task
        assert manager.progress_manager is mock_pm

    def test_taskとprogress_managerが省略時はNoneになる(
        self,
        mock_llm_client: MagicMock,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """省略時にtask / progress_managerがNoneになることを確認する"""
        manager = PrePlanningManager(
            config={},
            llm_client=mock_llm_client,
            mcp_clients=mock_mcp_clients,
        )
        assert manager.task is None
        assert manager.progress_manager is None

    @pytest.mark.asyncio
    async def test_executeがprogress_managerのadd_history_entryを2回呼び出す(
        self,
        mock_llm_client: MagicMock,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """
        execute()がprogress_manager.add_history_entry()を開始時と完了時の2回
        呼び出すことを確認する（CLASS_IMPLEMENTATION_SPEC.md § 8.3 手順1・5）。
        """
        mock_pm = MagicMock()
        mock_pm.add_history_entry = AsyncMock()

        manager = PrePlanningManager(
            config={},
            llm_client=mock_llm_client,
            mcp_clients=mock_mcp_clients,
            progress_manager=mock_pm,
        )

        await manager.execute(
            task_uuid="test-uuid",
            task_description="テストタスク",
            plan_environment_id="plan-env-001",
        )

        # 開始通知と完了通知の2回呼ばれることを確認する
        assert mock_pm.add_history_entry.call_count == 2
        # 最初の呼び出しはstatus="start"
        first_call_kwargs = mock_pm.add_history_entry.call_args_list[0].kwargs
        assert first_call_kwargs.get("status") == "start"
        # 2回目の呼び出しはstatus="complete"
        second_call_kwargs = mock_pm.add_history_entry.call_args_list[1].kwargs
        assert second_call_kwargs.get("status") == "complete"

    @pytest.mark.asyncio
    async def test_progress_managerなしでもexecuteは正常完了する(
        self,
        pre_planning_manager: PrePlanningManager,
    ) -> None:
        """progress_managerがNoneの場合でもexecute()が正常完了することを確認する"""
        # フィクスチャのmanagerはprogress_manager=Noneの状態
        assert pre_planning_manager.progress_manager is None

        # 例外が発生しないことを確認する
        result = await pre_planning_manager.execute(
            task_uuid="test-uuid",
            task_description="テストタスク",
            plan_environment_id="plan-env-001",
        )
        assert "selected_environment" in result


# ========================================
# TestPrePlanningManagerSubMethods
# ========================================


class TestPrePlanningManagerSubMethods:
    """PrePlanningManager サブメソッドの個別テスト"""

    @pytest.mark.asyncio
    async def test_execute_understandingがLLMを呼び出して要約を返す(
        self,
        mock_llm_client: MagicMock,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """execute_understanding()がLLMを呼び出し、summaryを含む辞書を返すことを確認する"""
        mock_llm_client.generate = AsyncMock(return_value="タスク要約テキスト")

        manager = PrePlanningManager(
            config={},
            llm_client=mock_llm_client,
            mcp_clients=mock_mcp_clients,
        )

        result = await manager.execute_understanding("テストタスクの説明")

        assert "summary" in result
        assert "key_points" in result
        assert "complexity" in result
        assert result["summary"] == "タスク要約テキスト"

    @pytest.mark.asyncio
    async def test_execute_understandingがLLMなしでタスク説明を返す(
        self,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """generate()を持たないllm_clientの場合にタスク説明の先頭200文字が返されることを確認する"""
        no_generate_client = MagicMock(spec=[])  # generateメソッドを持たないクライアント

        manager = PrePlanningManager(
            config={},
            llm_client=no_generate_client,
            mcp_clients=mock_mcp_clients,
        )

        long_description = "A" * 300
        result = await manager.execute_understanding(long_description)

        assert result["summary"] == long_description[:200]

    @pytest.mark.asyncio
    async def test_select_execution_environmentが有効な環境名とタプルを返す(
        self,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """select_execution_environment()が(str, dict)タプルを返すことを確認する"""
        import json as _json

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value=_json.dumps(
                {"selected_environment": "node", "reasoning": "package.jsonが存在するため"}
            )
        )

        manager = PrePlanningManager(
            config={},
            llm_client=llm_client,
            mcp_clients=mock_mcp_clients,
        )
        # environment_infoをセットしてからselectを呼ぶ
        manager.environment_info = {"detected_files": {"package.json": "node"}, "file_contents": {}}

        env_name, details = await manager.select_execution_environment()

        assert env_name == "node"
        assert isinstance(details, dict)
        assert "reasoning" in details

    @pytest.mark.asyncio
    async def test_collect_environment_infoが環境情報辞書を返す(
        self,
        mock_llm_client: MagicMock,
        mock_mcp_clients: dict[str, MagicMock],
    ) -> None:
        """collect_environment_info()がdetected_filesとfile_contentsキーを持つ辞書を返すことを確認する"""
        manager = PrePlanningManager(
            config={},
            llm_client=mock_llm_client,
            mcp_clients=mock_mcp_clients,
        )

        result = await manager.collect_environment_info("plan-env-001")

        assert "detected_files" in result
        assert "file_contents" in result
