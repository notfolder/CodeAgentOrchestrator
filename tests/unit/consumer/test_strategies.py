"""
TaskStrategy群の単体テスト

IssueToMRConversionStrategy・IssueOnlyStrategy・MergeRequestStrategy
の各execute()メソッドとステータス更新を検証する。

IMPLEMENTATION_PLAN.md フェーズ6-5 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from strategies.issue_to_mr_conversion_strategy import IssueToMRConversionStrategy
from strategies.issue_only_strategy import IssueOnlyStrategy
from strategies.merge_request_strategy import MergeRequestStrategy
from shared.models.task import Task


# ========================================
# フィクスチャ
# ========================================


@pytest.fixture
def issue_task() -> Task:
    """テスト用IssueタスクMockを返す"""
    return Task(
        task_uuid="test-uuid-issue",
        task_type="issue",
        project_id=1,
        issue_iid=42,
        username="testuser",
    )


@pytest.fixture
def mr_task() -> Task:
    """テスト用MRタスクMockを返す"""
    return Task(
        task_uuid="test-uuid-mr",
        task_type="merge_request",
        project_id=1,
        mr_iid=10,
        username="testuser",
    )


@pytest.fixture
def mock_task_repository() -> MagicMock:
    """テスト用TaskRepositoryモックを返す"""
    repo = MagicMock()
    repo.update_task_status = AsyncMock(return_value={"uuid": "test-uuid"})
    return repo


# ========================================
# TestIssueToMRConversionStrategy
# ========================================


class TestIssueToMRConversionStrategy:
    """IssueToMRConversionStrategyのテスト"""

    async def test_正常フローでIssueがMRに変換されタスクがcompleted(
        self,
        issue_task: Task,
        mock_task_repository: MagicMock,
    ) -> None:
        """execute()が変換→ステータス更新の順に実行されることを確認する"""
        mock_converter = MagicMock()
        mock_converter.convert = AsyncMock()

        strategy = IssueToMRConversionStrategy(
            issue_to_mr_converter=mock_converter,
            task_repository=mock_task_repository,
        )

        await strategy.execute(issue_task)

        # converterが呼ばれていることを確認
        mock_converter.convert.assert_called_once_with(issue_task)
        # ステータスがcompletedになっていることを確認
        mock_task_repository.update_task_status.assert_called_once_with(
            issue_task.task_uuid, "completed"
        )

    async def test_converterがNoneの場合スキップされステータスはcompletedになる(
        self,
        issue_task: Task,
        mock_task_repository: MagicMock,
    ) -> None:
        """issue_to_mr_converterがNoneの場合にスキップされてcompletedになることを確認する"""
        strategy = IssueToMRConversionStrategy(
            issue_to_mr_converter=None,
            task_repository=mock_task_repository,
        )

        await strategy.execute(issue_task)

        # ステータスがcompletedになっていることを確認
        mock_task_repository.update_task_status.assert_called_once_with(
            issue_task.task_uuid, "completed"
        )

    async def test_task_repositoryがNoneの場合もエラーが発生しない(
        self,
        issue_task: Task,
    ) -> None:
        """task_repositoryがNoneの場合もエラーなく処理が完了することを確認する"""
        mock_converter = MagicMock()
        mock_converter.convert = AsyncMock()

        strategy = IssueToMRConversionStrategy(
            issue_to_mr_converter=mock_converter,
            task_repository=None,
        )

        # エラーが発生しないことを確認
        await strategy.execute(issue_task)
        mock_converter.convert.assert_called_once_with(issue_task)


# ========================================
# TestIssueOnlyStrategy
# ========================================


class TestIssueOnlyStrategy:
    """IssueOnlyStrategyのテスト"""

    @pytest.fixture
    def mock_gitlab_client(self) -> MagicMock:
        """テスト用GitlabClientモックを返す"""
        client = MagicMock()
        client.get_issue.return_value = MagicMock(labels=["coding agent"])
        return client

    @pytest.fixture
    def mock_config_manager(self) -> MagicMock:
        """テスト用ConfigManagerモックを返す"""
        manager = MagicMock()
        manager.get_gitlab_config.return_value = MagicMock(
            done_label="coding agent done"
        )
        return manager

    async def test_正常フローでラベル付与コメント投稿ステータス更新が実行される(
        self,
        issue_task: Task,
        mock_task_repository: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """execute()が処理済みラベル付与→コメント投稿→ステータス更新の順に実行されることを確認する"""
        strategy = IssueOnlyStrategy(
            gitlab_client=mock_gitlab_client,
            config_manager=mock_config_manager,
            task_repository=mock_task_repository,
        )

        await strategy.execute(issue_task)

        # 処理済みラベル付与が呼ばれていることを確認
        mock_gitlab_client.add_label.assert_called_once()
        # 完了コメント投稿が呼ばれていることを確認
        mock_gitlab_client.create_issue_comment.assert_called_once()
        # ステータスがcompletedになっていることを確認
        mock_task_repository.update_task_status.assert_called_once_with(
            issue_task.task_uuid, "completed"
        )

    async def test_issue_iidがNoneの場合スキップされる(
        self,
        mock_task_repository: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """issue_iidがNoneの場合に処理がスキップされることを確認する"""
        task_without_iid = Task(
            task_uuid="test-uuid",
            task_type="issue",
            project_id=1,
            issue_iid=None,  # IIDなし
        )

        strategy = IssueOnlyStrategy(
            gitlab_client=mock_gitlab_client,
            config_manager=mock_config_manager,
            task_repository=mock_task_repository,
        )

        await strategy.execute(task_without_iid)

        mock_gitlab_client.add_label.assert_not_called()
        mock_gitlab_client.create_issue_comment.assert_not_called()
        mock_task_repository.update_task_status.assert_not_called()

    async def test_ラベル付与失敗時もステータス更新は実行される(
        self,
        issue_task: Task,
        mock_task_repository: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_config_manager: MagicMock,
    ) -> None:
        """ラベル付与に失敗してもステータス更新は正常に実行されることを確認する"""
        mock_gitlab_client.add_label.side_effect = Exception("ラベル付与エラー")

        strategy = IssueOnlyStrategy(
            gitlab_client=mock_gitlab_client,
            config_manager=mock_config_manager,
            task_repository=mock_task_repository,
        )

        await strategy.execute(issue_task)

        # ラベル付与失敗でもステータス更新は実行される
        mock_task_repository.update_task_status.assert_called_once_with(
            issue_task.task_uuid, "completed"
        )


# ========================================
# TestMergeRequestStrategy
# ========================================


class TestMergeRequestStrategy:
    """MergeRequestStrategyのテスト"""

    async def test_正常フローでステータスがin_progress_then_completedに更新される(
        self,
        mr_task: Task,
        mock_task_repository: MagicMock,
    ) -> None:
        """execute()がin_progress→completed の順にステータスを更新することを確認する"""
        mock_workflow = MagicMock()
        mock_workflow.run = AsyncMock()

        mock_workflow_factory = MagicMock()
        mock_workflow_factory.create_workflow_from_definition = AsyncMock(
            return_value=mock_workflow
        )

        mock_definition_loader = MagicMock()

        strategy = MergeRequestStrategy(
            workflow_factory=mock_workflow_factory,
            definition_loader=mock_definition_loader,
            task_repository=mock_task_repository,
        )

        await strategy.execute(mr_task)

        # update_task_status呼び出し回数を確認
        assert mock_task_repository.update_task_status.call_count == 2
        calls = mock_task_repository.update_task_status.call_args_list
        # 仕様書§2.10.3: 最初はin_progress、完了後はcompleted
        assert calls[0][0][1] == "in_progress"
        assert calls[1][0][1] == "completed"

    async def test_ワークフロー実行エラー時にステータスがfailedになる(
        self,
        mr_task: Task,
        mock_task_repository: MagicMock,
    ) -> None:
        """ワークフロー実行中にエラーが発生した場合にステータスがfailedになることを確認する"""
        mock_workflow_factory = MagicMock()
        mock_workflow_factory.create_workflow_from_definition = AsyncMock(
            side_effect=Exception("ワークフローエラー")
        )

        strategy = MergeRequestStrategy(
            workflow_factory=mock_workflow_factory,
            definition_loader=MagicMock(),
            task_repository=mock_task_repository,
        )

        with pytest.raises(Exception, match="ワークフローエラー"):
            await strategy.execute(mr_task)

        # 最終ステータスがfailedになっていることを確認
        last_call = mock_task_repository.update_task_status.call_args_list[-1]
        assert last_call[0][1] == "failed"

    async def test_workflow_factoryがNoneの場合スキップされステータスはcompleted(
        self,
        mr_task: Task,
        mock_task_repository: MagicMock,
    ) -> None:
        """workflow_factoryがNoneの場合にスキップされてcompletedになることを確認する"""
        strategy = MergeRequestStrategy(
            workflow_factory=None,
            definition_loader=MagicMock(),
            task_repository=mock_task_repository,
        )

        await strategy.execute(mr_task)

        # ステータスがcompletedになっていることを確認
        calls = mock_task_repository.update_task_status.call_args_list
        statuses = [c[0][1] for c in calls]
        assert "completed" in statuses
