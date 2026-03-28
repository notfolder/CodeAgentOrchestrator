"""
Middleware クラス群の単体テスト

MiddlewareSignal・WorkflowNode・CommentCheckMiddleware・
InfiniteLoopDetectionMiddleware・TokenUsageMiddleware・
ErrorHandlingMiddleware の各メソッドを検証する。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.configurable_agent import WorkflowContext
from middleware.comment_check_middleware import CommentCheckMiddleware
from middleware.error_handling_middleware import ErrorHandlingMiddleware, RetryPolicy
from middleware.i_middleware import MiddlewareSignal, WorkflowNode
from middleware.infinite_loop_detection_middleware import (
    InfiniteLoopDetectionMiddleware,
)
from middleware.token_usage_middleware import TokenUsageMiddleware


# ========================================
# テスト用ヘルパー関数
# ========================================


def _assert_middleware_signal_action(result, expected_action: str) -> None:
    """
    MiddlewareSignalのactionを検証するヘルパー関数。

    sys.pathの二重ロードによりisinstanceが誤検知するため、
    属性チェックでMiddlewareSignalの検証を行う。

    Args:
        result: intercept()の戻り値
        expected_action: 期待するactionの値
    """
    assert result is not None
    assert result.action == expected_action


# ========================================
# テスト用ヘルパークラス
# ========================================


class _ConcreteWorkflowContext(WorkflowContext):
    """テスト用WorkflowContextの具象クラス"""

    def __init__(self) -> None:
        self._state: dict = {}

    def get_state(self, key: str, default=None):
        """指定キーの状態値を返す"""
        return self._state.get(key, default)

    def set_state(self, key: str, value) -> None:
        """指定キーに値を保存する"""
        self._state[key] = value


# ========================================
# フィクスチャ
# ========================================


@pytest.fixture
def mock_ctx() -> _ConcreteWorkflowContext:
    """テスト用WorkflowContextを返す"""
    ctx = _ConcreteWorkflowContext()
    ctx._state = {
        "project_id": 10,
        "mr_iid": 5,
        "task_uuid": "test-uuid-001",
        "username": "testuser",
    }
    return ctx


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    return MagicMock()


@pytest.fixture
def mock_context_storage_manager() -> MagicMock:
    """テスト用ContextStorageManagerモックを返す"""
    manager = MagicMock()
    manager.save_token_usage = AsyncMock()
    manager.save_error = AsyncMock()
    return manager


@pytest.fixture
def mock_metrics_collector() -> MagicMock:
    """テスト用MetricsCollectorモックを返す"""
    return MagicMock()


def _make_node(
    node_id: str = "test_node",
    node_type: str = "agent",
    check_comments_before: bool = False,
    comment_redirect_to: str | None = None,
) -> WorkflowNode:
    """テスト用WorkflowNodeを生成する"""
    metadata = MagicMock()
    metadata.check_comments_before = check_comments_before
    metadata.comment_redirect_to = comment_redirect_to
    return WorkflowNode(node_id=node_id, node_type=node_type, metadata=metadata)


# ========================================
# TestCommentCheckMiddleware
# ========================================


class TestCommentCheckMiddleware:
    """CommentCheckMiddleware.intercept() のテスト"""

    async def test_comment_check_middleware_non_before_execution_phase(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """phaseがbefore_executionでない場合はNoneを返すことを確認する"""
        middleware = CommentCheckMiddleware(gitlab_client=mock_gitlab_client)
        node = _make_node(check_comments_before=True)

        result = await middleware.intercept(
            phase="after_execution",
            node=node,
            context=mock_ctx,
        )

        assert result is None
        mock_gitlab_client.get_merge_request_notes.assert_not_called()

    async def test_comment_check_middleware_no_check_flag(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """check_comments_beforeがFalseの場合はNoneを返すことを確認する"""
        middleware = CommentCheckMiddleware(gitlab_client=mock_gitlab_client)
        # check_comments_before=False のノードを作成する
        node = _make_node(check_comments_before=False)

        result = await middleware.intercept(
            phase="before_execution",
            node=node,
            context=mock_ctx,
        )

        assert result is None
        mock_gitlab_client.get_merge_request_notes.assert_not_called()

    async def test_comment_check_middleware_no_new_comments(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """新着コメントがない場合はNoneを返すことを確認する"""
        # task_start_timeを過去の時刻に設定する
        past_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mock_ctx._state["task_start_time"] = past_time

        # 古いコメントのみ返すモックを設定する
        old_note = MagicMock()
        old_note.system = False
        old_note.created_at = datetime(2023, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
        mock_gitlab_client.get_merge_request_notes.return_value = [old_note]

        middleware = CommentCheckMiddleware(gitlab_client=mock_gitlab_client)
        node = _make_node(check_comments_before=True)

        result = await middleware.intercept(
            phase="before_execution",
            node=node,
            context=mock_ctx,
        )

        assert result is None

    async def test_comment_check_middleware_with_new_comments(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """新着コメントがある場合はMiddlewareSignalを返すことを確認する"""
        # task_start_timeを過去の時刻に設定する
        past_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mock_ctx._state["task_start_time"] = past_time

        # タスク開始後の新しいコメントのモックを作成する
        new_note = MagicMock()
        new_note.system = False
        new_note.created_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_gitlab_client.get_merge_request_notes.return_value = [new_note]

        middleware = CommentCheckMiddleware(gitlab_client=mock_gitlab_client)
        node = _make_node(
            check_comments_before=True,
            comment_redirect_to="comment_handler",
        )

        result = await middleware.intercept(
            phase="before_execution",
            node=node,
            context=mock_ctx,
        )

        # MiddlewareSignalが返されることを確認する
        assert result is not None
        # action属性でredirectシグナルであることを確認する（sys.pathの二重ロードによるisinstance問題を回避）
        _assert_middleware_signal_action(result, "redirect")
        assert result.redirect_to == "comment_handler"


# ========================================
# TestInfiniteLoopDetectionMiddleware
# ========================================


class TestInfiniteLoopDetectionMiddleware:
    """InfiniteLoopDetectionMiddleware.intercept() のテスト"""

    async def test_infinite_loop_detection_no_loop(
        self,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """訪問回数がmax_node_visits以下の場合はNoneを返すことを確認する"""
        middleware = InfiniteLoopDetectionMiddleware(max_node_visits=3)
        node = _make_node(node_id="node_a")

        # max_node_visits回まではNoneを返すことを確認する
        for _ in range(3):
            result = await middleware.intercept(
                phase="before_execution",
                node=node,
                context=mock_ctx,
            )
            assert result is None

    async def test_infinite_loop_detection_detects_loop(
        self,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """訪問回数がmax_node_visitsを超えた場合はabortシグナルを返すことを確認する"""
        middleware = InfiniteLoopDetectionMiddleware(max_node_visits=2)
        node = _make_node(node_id="loop_node")

        # max_node_visits回まではNoneが返ることを確認する
        for _ in range(2):
            result = await middleware.intercept(
                phase="before_execution",
                node=node,
                context=mock_ctx,
            )
            assert result is None

        # max_node_visitsを超えた1回目でabortシグナルが返ることを確認する
        result = await middleware.intercept(
            phase="before_execution",
            node=node,
            context=mock_ctx,
        )
        assert result is not None
        # action属性でabortシグナルであることを確認する（sys.pathの二重ロードによるisinstance問題を回避）
        _assert_middleware_signal_action(result, "abort")


# ========================================
# TestTokenUsageMiddleware
# ========================================


class TestTokenUsageMiddleware:
    """TokenUsageMiddleware.intercept() のテスト"""

    async def test_token_usage_middleware_non_after_phase(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """phaseがafter_execution/on_error以外の場合はNoneを返すことを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node(node_type="agent")

        result = await middleware.intercept(
            phase="before_execution",
            node=node,
            context=mock_ctx,
        )

        assert result is None
        mock_context_storage_manager.save_token_usage.assert_not_called()

    async def test_token_usage_middleware_non_agent_node(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """node_typeがagentでない場合はNoneを返すことを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        # executorノードを作成する
        node = _make_node(node_type="executor")

        result = await middleware.intercept(
            phase="after_execution",
            node=node,
            context=mock_ctx,
            result={"token_usage": {"total_tokens": 100, "prompt_tokens": 50}},
        )

        assert result is None
        mock_context_storage_manager.save_token_usage.assert_not_called()

    async def test_token_usage_middleware_saves_token_usage(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """正常系でsave_token_usageが呼ばれることを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node(node_id="planning_agent", node_type="agent")

        # トークン使用量を含む実行結果を作成する
        execution_result = {
            "token_usage": {
                "prompt_tokens": 150,
                "completion_tokens": 80,
                "total_tokens": 230,
                "model": "gpt-4",
            }
        }

        result = await middleware.intercept(
            phase="after_execution",
            node=node,
            context=mock_ctx,
            result=execution_result,
        )

        # Noneが返ることを確認する（フロー制御なし）
        assert result is None
        # save_token_usageが呼ばれることを確認する
        mock_context_storage_manager.save_token_usage.assert_called_once_with(
            username="testuser",
            task_uuid="test-uuid-001",
            node_id="planning_agent",
            model="gpt-4",
            prompt_tokens=150,
            completion_tokens=80,
            total_tokens=230,
        )
        # メトリクスが送信されることを確認する
        mock_metrics_collector.send_metric.assert_called_once()

    async def test_token_usage_middleware_new_format_with_usage_details(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """新フォーマット（usage_detailsキー）でsave_token_usageが正しく呼ばれることを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node(node_id="planning_agent", node_type="agent")

        # ConfigurableAgent が出力する新フォーマット
        execution_result = {
            "token_usage": {
                "usage_details": {
                    "input_token_count": 200,
                    "output_token_count": 100,
                    "total_token_count": 300,
                },
                "prompt_text": "テストプロンプト",
                "response_text": "テスト応答",
                "model": "gpt-4o",
            }
        }

        result = await middleware.intercept(
            phase="after_execution",
            node=node,
            context=mock_ctx,
            result=execution_result,
        )

        assert result is None
        mock_context_storage_manager.save_token_usage.assert_called_once_with(
            username="testuser",
            task_uuid="test-uuid-001",
            node_id="planning_agent",
            model="gpt-4o",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
        )

    async def test_token_usage_middleware_tiktoken_fallback(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """usage_detailsがNoneの場合にtiktokenでトークン推定してsave_token_usageが呼ばれることを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node(node_id="planning_agent", node_type="agent")

        # usage_details が None（非公式エンドポイント等の場合）
        execution_result = {
            "token_usage": {
                "usage_details": None,
                "prompt_text": "ブランチ名を生成してください。Issue: テストイシュー",
                "response_text": "feature/7-test-issue",
                "model": "gpt-4o",
            }
        }

        result = await middleware.intercept(
            phase="after_execution",
            node=node,
            context=mock_ctx,
            result=execution_result,
        )

        assert result is None
        # tiktoken 推定後に save_token_usage が呼ばれることを確認する
        mock_context_storage_manager.save_token_usage.assert_called_once()
        call_kwargs = mock_context_storage_manager.save_token_usage.call_args.kwargs
        # トークン数は 0 より大きいことを確認する（tiktoken 推定値）
        assert call_kwargs["prompt_tokens"] > 0
        assert call_kwargs["completion_tokens"] > 0

    async def test_token_usage_middleware_on_error_with_pending(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """on_errorフェーズで_pending_token_usageがある場合にsave_token_usageが呼ばれることを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node(node_id="code_generation", node_type="agent")

        # agent.run() 成功後に ctx へ中間保存されたトークン情報を設定する
        mock_ctx.set_state(
            "_pending_token_usage",
            {
                "usage_details": {
                    "input_token_count": 300,
                    "output_token_count": 150,
                    "total_token_count": 450,
                },
                "prompt_text": "コードを生成してください",
                "response_text": "def hello(): pass",
                "model": "gpt-4o",
            },
        )

        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=RuntimeError("GitLab進捗報告に失敗"),
        )

        assert result is None
        # save_token_usage が呼ばれることを確認する
        mock_context_storage_manager.save_token_usage.assert_called_once_with(
            username="testuser",
            task_uuid="test-uuid-001",
            node_id="code_generation",
            model="gpt-4o",
            prompt_tokens=300,
            completion_tokens=150,
            total_tokens=450,
        )
        # _pending_token_usage が消去されることを確認する（二重計上防止）
        assert mock_ctx.get_state("_pending_token_usage") is None

    async def test_token_usage_middleware_on_error_without_pending(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """on_errorフェーズで_pending_token_usageがない場合（クォータエラー等）はスキップされることを確認する"""
        middleware = TokenUsageMiddleware(
            context_storage_manager=mock_context_storage_manager,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node(node_id="task_classifier", node_type="agent")

        # _pending_token_usage をセットしない（agent.run() が失敗した場合を模擬する）

        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=RuntimeError("insufficient_quota"),
        )

        assert result is None
        mock_context_storage_manager.save_token_usage.assert_not_called()


# ========================================
# TestErrorHandlingMiddleware
# ========================================


class TestErrorHandlingMiddleware:
    """ErrorHandlingMiddleware.intercept() のテスト"""

    async def test_error_handling_middleware_non_error_phase(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """phaseがon_errorでない場合はNoneを返すことを確認する"""
        middleware = ErrorHandlingMiddleware(
            context_storage_manager=mock_context_storage_manager,
            gitlab_client=mock_gitlab_client,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node()

        result = await middleware.intercept(
            phase="before_execution",
            node=node,
            context=mock_ctx,
            exception=ValueError("テストエラー"),
        )

        assert result is None

    async def test_error_handling_middleware_retries_transient(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_metrics_collector: MagicMock,
        monkeypatch,
    ) -> None:
        """transientエラーでリトライ処理が行われることを確認する"""
        # asyncio.sleepをモック化してテストを高速化する
        import asyncio

        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        retry_policy = RetryPolicy(max_attempts=3, base_delay=0.0)
        middleware = ErrorHandlingMiddleware(
            context_storage_manager=mock_context_storage_manager,
            gitlab_client=mock_gitlab_client,
            metrics_collector=mock_metrics_collector,
            retry_policy=retry_policy,
        )
        node = _make_node()

        # TimeoutError（transient）を発生させる
        transient_error = TimeoutError("接続タイムアウト")

        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=transient_error,
        )

        # リトライ時はNoneが返ることを確認する（ワークフロー継続）
        assert result is None
        # retry_countがインクリメントされることを確認する
        assert mock_ctx._state.get("retry_count") == 1

    async def test_error_handling_middleware_aborts_on_max_retries(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_metrics_collector: MagicMock,
        monkeypatch,
    ) -> None:
        """リトライ上限到達でabortシグナルを返すことを確認する"""
        import asyncio

        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        retry_policy = RetryPolicy(max_attempts=2, base_delay=0.0)
        middleware = ErrorHandlingMiddleware(
            context_storage_manager=mock_context_storage_manager,
            gitlab_client=mock_gitlab_client,
            metrics_collector=mock_metrics_collector,
            retry_policy=retry_policy,
        )
        node = _make_node()
        # retry_countをmax_attemptsと同じにして上限到達状態にする
        mock_ctx._state["retry_count"] = 2

        transient_error = TimeoutError("接続タイムアウト")

        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=transient_error,
        )

        # abortシグナルが返ることを確認する
        # action属性でabortシグナルであることを確認する（sys.pathの二重ロードによるisinstance問題を回避）
        _assert_middleware_signal_action(result, "abort")
        # GitLabにエラーコメントが投稿されることを確認する
        mock_gitlab_client.create_merge_request_note.assert_called_once()
        # メトリクスが送信されることを確認する
        mock_metrics_collector.send_metric.assert_called_once()

    async def test_error_handling_middleware_aborts_configuration_error(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """configurationエラー（PermissionError）は即座にabortシグナルを返すことを確認する"""
        mock_ctx._state["project_id"] = 10
        mock_ctx._state["mr_iid"] = 5

        middleware = ErrorHandlingMiddleware(
            context_storage_manager=mock_context_storage_manager,
            gitlab_client=mock_gitlab_client,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node()

        exc = PermissionError("forbidden: insufficient permissions")
        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=exc,
        )

        # リトライせず即座にabortすることを確認する
        _assert_middleware_signal_action(result, "abort")
        # GitLabにエラーコメントが投稿されることを確認する
        mock_gitlab_client.create_merge_request_note.assert_called_once()

    async def test_error_handling_middleware_aborts_implementation_error(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """implementationエラー（ValueError）は即座にabortシグナルを返すことを確認する"""
        mock_ctx._state["project_id"] = 10
        mock_ctx._state["mr_iid"] = 5

        middleware = ErrorHandlingMiddleware(
            context_storage_manager=mock_context_storage_manager,
            gitlab_client=mock_gitlab_client,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node()

        exc = ValueError("unexpected value in implementation")
        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=exc,
        )

        # リトライせず即座にabortすることを確認する
        _assert_middleware_signal_action(result, "abort")
        mock_gitlab_client.create_merge_request_note.assert_called_once()

    async def test_error_handling_middleware_aborts_resource_error(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_context_storage_manager: MagicMock,
        mock_gitlab_client: MagicMock,
        mock_metrics_collector: MagicMock,
    ) -> None:
        """resourceエラー（MemoryError）は即座にabortシグナルを返すことを確認する"""
        mock_ctx._state["project_id"] = 10
        mock_ctx._state["mr_iid"] = 5

        middleware = ErrorHandlingMiddleware(
            context_storage_manager=mock_context_storage_manager,
            gitlab_client=mock_gitlab_client,
            metrics_collector=mock_metrics_collector,
        )
        node = _make_node()

        exc = MemoryError("out of memory")
        result = await middleware.intercept(
            phase="on_error",
            node=node,
            context=mock_ctx,
            exception=exc,
        )

        # リトライせず即座にabortすることを確認する
        _assert_middleware_signal_action(result, "abort")
        mock_gitlab_client.create_merge_request_note.assert_called_once()
