"""
GuidelineLearningAgentの単体テスト

_process()の正常フロー・コメントフィルタリング・
ガイドライン更新・エラー抑制（ワークフロー継続）を検証する。

IMPLEMENTATION_PLAN.md フェーズ6-5 に準拠する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.guideline_learning_agent import GuidelineLearningAgent, AgentResponse
from agents.configurable_agent import WorkflowContext


# ========================================
# テスト用ヘルパークラス
# ========================================


class _ConcreteWorkflowContext(WorkflowContext):
    """テスト用WorkflowContextの具象クラス"""

    def __init__(self) -> None:
        self._state: dict = {}

    async def get_state(self, key: str):
        """指定キーの状態値を返す"""
        return self._state.get(key)

    async def set_state(self, key: str, value) -> None:
        """指定キーに値を保存する"""
        self._state[key] = value


# ========================================
# フィクスチャ
# ========================================


@pytest.fixture
def mock_user_config_enabled() -> MagicMock:
    """学習機能有効なUserConfigモックを返す"""
    config = MagicMock()
    config.learning_enabled = True
    config.learning_llm_model = "gpt-4o"
    config.learning_llm_temperature = 0.3
    config.learning_llm_max_tokens = 8000
    config.learning_exclude_bot_comments = True
    config.learning_only_after_task_start = True
    return config


@pytest.fixture
def mock_user_config_disabled() -> MagicMock:
    """学習機能無効なUserConfigモックを返す"""
    config = MagicMock()
    config.learning_enabled = False
    return config


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    return MagicMock()


@pytest.fixture
def mock_ctx() -> _ConcreteWorkflowContext:
    """テスト用WorkflowContextを返す"""
    return _ConcreteWorkflowContext()


# ========================================
# TestGuidelineLearningAgentHandle
# ========================================


class TestGuidelineLearningAgentHandle:
    """handle()メソッドのテスト"""

    async def test_エラー発生時もAgentResponsesuccess_trueを返す(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """処理中にエラーが発生してもhandle()がAgentResponse(success=True)を返すことを確認する"""
        # _processで例外が発生するようにモック
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )

        # task_mr_iid=Noneで_processがwarningのみでreturnするケース
        response = await agent.handle(None, mock_ctx)

        assert isinstance(response, AgentResponse)
        assert response.success is True

    async def test_learning_enabledがfalseの場合スキップされる(
        self,
        mock_user_config_disabled: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """learning_enabled=falseの場合にhandle()がAgentResponse(success=True)を返してスキップすることを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_disabled,
            gitlab_client=mock_gitlab_client,
        )

        response = await agent.handle(None, mock_ctx)

        assert isinstance(response, AgentResponse)
        assert response.success is True
        # GitLabクライアントのメソッドが呼ばれていないことを確認
        mock_gitlab_client.get_mr_comments.assert_not_called()

    async def test_task_mr_iidがない場合スキップされる(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """task_mr_iidがコンテキストに設定されていない場合にスキップされることを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        # コンテキストにtask_mr_iidを設定しない

        response = await agent.handle(None, mock_ctx)

        assert response.success is True
        mock_gitlab_client.get_mr_comments.assert_not_called()

    async def test_コメントがある場合LLM呼び出しが実行される(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """対象コメントが存在する場合にLLM呼び出しが実行されることを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )

        # コンテキストを設定
        await mock_ctx.set_state("task_mr_iid", 10)
        await mock_ctx.set_state("task_project_id", 1)

        # MRコメントを返すモック
        mock_gitlab_client.get_mr_comments.return_value = [
            {"body": "コードレビューコメント", "author": {"bot": False}, "created_at": "2024-01-01T10:00:00Z"},
        ]
        # ガイドラインファイルのモック
        mock_gitlab_client.get_file_content.return_value = "## 既存ガイドライン"

        response = await agent.handle(None, mock_ctx)

        assert response.success is True
        # コメント取得が呼ばれていることを確認
        mock_gitlab_client.get_mr_comments.assert_called_once_with(
            project_id=1,
            mr_iid=10,
        )


# ========================================
# TestGetFilteredComments
# ========================================


class TestGetFilteredComments:
    """_get_filtered_comments()のテスト"""

    def test_botコメントが除外される(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """learning_exclude_bot_comments=trueの場合にbotコメントが除外されることを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        mock_gitlab_client.get_mr_comments.return_value = [
            {"body": "通常コメント", "author": {"bot": False}},
            {"body": "ボットコメント", "author": {"bot": True}},  # 除外対象
        ]

        comments = agent._get_filtered_comments(
            project_id=1,
            mr_iid=10,
            task_start_time=None,
        )

        assert len(comments) == 1
        assert comments[0]["body"] == "通常コメント"

    def test_コメント取得エラー時は空リストを返す(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """GitLab APIエラー時に_get_filtered_comments()が空リストを返すことを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        mock_gitlab_client.get_mr_comments.side_effect = Exception("APIエラー")

        comments = agent._get_filtered_comments(
            project_id=1,
            mr_iid=10,
            task_start_time=None,
        )

        assert comments == []

    def test_task_start_time以前のコメントが除外される(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """learning_only_after_task_start=trueのとき、タスク開始前のコメントが除外されることを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        # タスク開始前と開始後のコメントを混在させる
        mock_gitlab_client.get_mr_comments.return_value = [
            {
                "body": "開始前コメント",
                "created_at": "2024-01-01T09:00:00Z",
                "author": {"bot": False},
            },
            {
                "body": "開始後コメント",
                "created_at": "2024-01-01T11:00:00Z",
                "author": {"bot": False},
            },
        ]

        comments = agent._get_filtered_comments(
            project_id=1,
            mr_iid=10,
            task_start_time="2024-01-01T10:00:00Z",  # 開始時刻
        )

        # 開始後のコメントのみ残る
        assert len(comments) == 1
        assert comments[0]["body"] == "開始後コメント"


# ========================================
# TestGetGuidelines
# ========================================


class TestGetGuidelines:
    """_get_guidelines()のテスト"""

    def test_ガイドラインファイルが存在する場合内容を返す(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """PROJECT_GUIDELINES.mdが存在する場合にその内容を返すことを確認する"""
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        expected_content = "# 既存ガイドライン"
        mock_gitlab_client.get_file_content.return_value = expected_content

        result = agent._get_guidelines(project_id=1, branch="main")

        assert result == expected_content

    def test_ガイドラインファイルが存在しない場合初期テンプレートを返す(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """PROJECT_GUIDELINES.mdが存在しない場合に初期テンプレートを返すことを確認する"""
        from agents.guideline_learning_agent import _INITIAL_GUIDELINES_TEMPLATE

        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        mock_gitlab_client.get_file_content.side_effect = Exception("ファイルなし")

        result = agent._get_guidelines(project_id=1, branch="main")

        assert result == _INITIAL_GUIDELINES_TEMPLATE


# ========================================
# TestUpdateGuidelines
# ========================================


class TestUpdateGuidelines:
    """_update_guidelines()のテスト"""

    async def test_ガイドライン更新時にupdate_fileとpost_mr_commentが呼ばれる(
        self,
        mock_user_config_enabled: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """_update_guidelines()がupdate_file()とpost_mr_comment()の両方を呼ぶことを確認する。

        CLASS_IMPLEMENTATION_SPEC.md § 11.4 ステップ6 に準拠する。
        """
        agent = GuidelineLearningAgent(
            user_config=mock_user_config_enabled,
            gitlab_client=mock_gitlab_client,
        )
        updated_content = "# 更新後ガイドライン"

        await agent._update_guidelines(
            project_id=1,
            mr_iid=10,
            updated_guidelines=updated_content,
            branch="main",
        )

        # update_file()が正しい引数で呼ばれていることを確認（§11.5: 例外的な直接git操作）
        mock_gitlab_client.update_file.assert_called_once_with(
            project_id=1,
            file_path="PROJECT_GUIDELINES.md",
            content=updated_content,
            commit_message="自動学習: ガイドライン更新",
            branch="main",
        )

        # post_mr_comment()が呼ばれていることを確認（MRに更新通知コメントを投稿する）
        mock_gitlab_client.post_mr_comment.assert_called_once_with(
            project_id=1,
            mr_iid=10,
            comment=mock_gitlab_client.post_mr_comment.call_args[1]["comment"],
        )
