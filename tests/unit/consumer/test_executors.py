"""
Executor クラス群の単体テスト

BaseExecutor・UserResolverExecutor・ContentTransferExecutor・
PlanEnvSetupExecutor・ExecEnvSetupExecutor・BranchMergeExecutor の
各メソッドを検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.configurable_agent import WorkflowContext
from executors.base_executor import BaseExecutor
from executors.branch_merge_executor import BranchMergeExecutor
from executors.content_transfer_executor import ContentTransferExecutor
from executors.exec_env_setup_executor import ExecEnvSetupExecutor
from executors.plan_env_setup_executor import PlanEnvSetupExecutor
from executors.user_resolver_executor import UserResolverExecutor


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


class _ConcreteBaseExecutor(BaseExecutor):
    """BaseExecutorのテスト用具象クラス"""

    async def handle(self, msg, ctx):
        """テスト用のハンドル実装（何もしない）"""
        return None


# ========================================
# フィクスチャ
# ========================================


@pytest.fixture
def mock_ctx() -> _ConcreteWorkflowContext:
    """テスト用WorkflowContextを返す"""
    return _ConcreteWorkflowContext()


@pytest.fixture
def mock_gitlab_client() -> MagicMock:
    """テスト用GitlabClientモックを返す"""
    return MagicMock()


@pytest.fixture
def mock_env_manager() -> MagicMock:
    """テスト用ExecutionEnvironmentManagerモックを返す"""
    return MagicMock()


# ========================================
# TestBaseExecutor
# ========================================


class TestBaseExecutor:
    """BaseExecutor のヘルパーメソッドのテスト"""

    async def test_base_executor_get_context_value(
        self,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """get_context_valueがctx.get_stateを呼び正しい値を返すことを確認する"""
        executor = _ConcreteBaseExecutor()
        mock_ctx._state["some_key"] = "some_value"

        # get_stateをspy化してget_context_value経由で呼ばれることを確認する
        original_get_state = mock_ctx.get_state
        mock_ctx.get_state = AsyncMock(side_effect=original_get_state)

        result = await executor.get_context_value(mock_ctx, "some_key")

        mock_ctx.get_state.assert_called_once_with("some_key")
        assert result == "some_value"

    async def test_base_executor_set_context_value(
        self,
        mock_ctx: _ConcreteWorkflowContext,
    ) -> None:
        """set_context_valueがctx.set_stateを呼び値が保存されることを確認する"""
        executor = _ConcreteBaseExecutor()

        # set_stateをspy化してset_context_value経由で呼ばれることを確認する
        original_set_state = mock_ctx.set_state
        mock_ctx.set_state = AsyncMock(side_effect=original_set_state)

        await executor.set_context_value(mock_ctx, "new_key", 42)

        mock_ctx.set_state.assert_called_once_with("new_key", 42)
        assert mock_ctx._state["new_key"] == 42


# ========================================
# TestUserResolverExecutor
# ========================================


class TestUserResolverExecutor:
    """UserResolverExecutor.handle() のテスト"""

    async def test_user_resolver_executor_handle_success(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """GitLabClientとUserConfigClientをモックして、user_emailとuser_configがコンテキストに保存されることを確認する"""
        # コンテキストにtask_identifierを設定する
        mock_ctx._state["task_identifier"] = {"project_id": 10, "mr_iid": 5}

        # MR authorのemailを持つモックMRを作成する
        mock_author = MagicMock()
        mock_author.email = "user@example.com"
        mock_mr = MagicMock()
        mock_mr.iid = 5
        mock_mr.author = mock_author
        mock_gitlab_client.get_merge_request.return_value = mock_mr

        # UserConfigClientのモックを作成する
        mock_user_config = {"language": "ja", "model": "gpt-4"}
        mock_user_config_client = MagicMock()
        mock_user_config_client.get_user_config = AsyncMock(
            return_value=mock_user_config
        )

        executor = UserResolverExecutor(
            gitlab_client=mock_gitlab_client,
            user_config_client=mock_user_config_client,
        )

        await executor.handle(msg={}, ctx=mock_ctx)

        # user_emailとuser_configがコンテキストに保存されることを確認する
        assert mock_ctx._state["user_email"] == "user@example.com"
        assert mock_ctx._state["user_config"] == mock_user_config
        mock_gitlab_client.get_merge_request.assert_called_once_with(
            project_id=10, mr_iid=5
        )
        mock_user_config_client.get_user_config.assert_called_once_with(
            "user@example.com"
        )

    async def test_user_resolver_executor_author_email_none(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """author.email が None の場合に空文字列が user_email として保存されることを確認する"""
        mock_ctx._state["task_identifier"] = {"project_id": 10, "mr_iid": 5}

        # author が存在するが email が None の MR モックを作成する
        mock_author = MagicMock()
        mock_author.email = None
        mock_mr = MagicMock()
        mock_mr.author = mock_author
        mock_gitlab_client.get_merge_request.return_value = mock_mr

        mock_user_config_client = MagicMock()
        mock_user_config_client.get_user_config = AsyncMock(return_value={})

        executor = UserResolverExecutor(
            gitlab_client=mock_gitlab_client,
            user_config_client=mock_user_config_client,
        )
        await executor.handle(msg={}, ctx=mock_ctx)

        # author.email=None の場合は空文字列が設定されることを確認する
        assert mock_ctx._state["user_email"] == ""
        # email が空でも get_user_config が呼ばれることを確認する
        mock_user_config_client.get_user_config.assert_called_once_with("")


# ========================================
# TestContentTransferExecutor
# ========================================


class TestContentTransferExecutor:
    """ContentTransferExecutor.handle() のテスト"""

    async def test_content_transfer_executor_handle_success(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """issue notesをMRに転記してtransferred_comments_countが保存されることを確認する"""
        # コンテキストにIssue情報を設定する
        mock_ctx._state["issue_iid"] = 3
        mock_ctx._state["project_id"] = 10
        mock_ctx._state["mr_iid"] = 7

        # ユーザーコメント2件とシステムコメント1件のモックを作成する
        note_user1 = MagicMock()
        note_user1.system = False
        note_user1.body = "ユーザーコメント1"
        note_user1.id = 101

        note_user2 = MagicMock()
        note_user2.system = False
        note_user2.body = "ユーザーコメント2"
        note_user2.id = 102

        note_system = MagicMock()
        note_system.system = True
        note_system.body = "システムコメント"
        note_system.id = 103

        mock_gitlab_client.get_issue_notes.return_value = [
            note_user1,
            note_user2,
            note_system,
        ]

        executor = ContentTransferExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle(msg={}, ctx=mock_ctx)

        # ユーザーコメント2件が転記されることを確認する
        assert mock_ctx._state["transferred_comments_count"] == 2
        assert mock_gitlab_client.create_merge_request_note.call_count == 2

    async def test_content_transfer_executor_partial_failure(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """一部コメントの転記が失敗した場合、failed_transfer_note_idsに失敗した note_id が記録されることを確認する"""
        mock_ctx._state["issue_iid"] = 3
        mock_ctx._state["project_id"] = 10
        mock_ctx._state["mr_iid"] = 7

        # 2件のコメントを設定する（2件目は転記失敗にする）
        note_ok = MagicMock()
        note_ok.system = False
        note_ok.body = "転記成功コメント"
        note_ok.id = 201

        note_fail = MagicMock()
        note_fail.system = False
        note_fail.body = "転記失敗コメント"
        note_fail.id = 202

        mock_gitlab_client.get_issue_notes.return_value = [note_ok, note_fail]

        # 2件目でエラーを発生させる
        call_count: list[int] = [0]

        def create_note_side_effect(**kwargs: object) -> None:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("GitLab API error")

        mock_gitlab_client.create_merge_request_note.side_effect = (
            create_note_side_effect
        )

        executor = ContentTransferExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle(msg={}, ctx=mock_ctx)

        # 成功1件、失敗1件が記録されることを確認する
        assert mock_ctx._state["transferred_comments_count"] == 1
        assert mock_ctx._state["failed_transfer_note_ids"] == [202]


# ========================================
# TestPlanEnvSetupExecutor
# ========================================


class TestPlanEnvSetupExecutor:
    """PlanEnvSetupExecutor.handle() のテスト"""

    async def test_plan_env_setup_executor_handle_success(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_env_manager: MagicMock,
    ) -> None:
        """env_managerのメソッドが呼ばれてplan_environment_idが保存されることを確認する"""
        # コンテキストに必要な値を設定する
        mock_ctx._state["task_mr_iid"] = 42
        mock_ctx._state["repo_url"] = "https://gitlab.example.com/repo.git"
        mock_ctx._state["original_branch"] = "main"

        # env_managerのモックを設定する
        mock_env_manager.prepare_plan_environment.return_value = "plan-env-001"

        executor = PlanEnvSetupExecutor(
            env_manager=mock_env_manager,
            config={"plan_environment_name": "python"},
        )

        await executor.handle(msg={}, ctx=mock_ctx)

        # plan_environment_idがコンテキストに保存されることを確認する
        assert mock_ctx._state["plan_environment_id"] == "plan-env-001"
        mock_env_manager.prepare_plan_environment.assert_called_once_with(
            environment_name="python",
            mr_iid=42,
        )
        mock_env_manager.clone_repository.assert_called_once_with(
            node_id="plan",
            repo_url="https://gitlab.example.com/repo.git",
            branch="main",
        )


# ========================================
# TestExecEnvSetupExecutor
# ========================================


class TestExecEnvSetupExecutor:
    """ExecEnvSetupExecutor.handle() のテスト"""

    def _make_graph_definition(self, node_id: str, env_count: int) -> dict:
        """テスト用のグラフ定義を生成する"""
        return {
            "nodes": [
                {
                    "id": node_id,
                    "type": "executor",
                    "config": {"env_count": env_count},
                }
            ]
        }

    async def test_exec_env_setup_executor_handle_single_env(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_env_manager: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """env_count=1の場合、サブブランチが作成されずbranch_envsがoriginal_branchを含むことを確認する"""
        node_id = "exec_env_setup_impl"
        mock_ctx._state["task_mr_iid"] = 42
        mock_ctx._state["selected_environment"] = "python"
        mock_ctx._state["original_branch"] = "feature/test"
        mock_ctx._state["project_id"] = 10

        mock_env_manager.prepare_environments.return_value = ["exec-env-001"]

        graph_def = self._make_graph_definition(node_id, env_count=1)
        executor = ExecEnvSetupExecutor(
            node_id=node_id,
            env_manager=mock_env_manager,
            gitlab_client=mock_gitlab_client,
            graph_definition=graph_def,
        )

        await executor.handle(msg={}, ctx=mock_ctx)

        branch_envs = mock_ctx._state["branch_envs"]
        # env_count=1なのでサブブランチは作成されない
        mock_gitlab_client.create_branch.assert_not_called()
        # branch_envsにoriginal_branchが含まれることを確認する
        assert 1 in branch_envs
        assert branch_envs[1]["branch"] == "feature/test"
        assert branch_envs[1]["env_id"] == "exec-env-001"

    async def test_exec_env_setup_executor_handle_multi_env(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_env_manager: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """env_count=2の場合、サブブランチが2本作成されることを確認する"""
        node_id = "exec_env_setup_impl"
        mock_ctx._state["task_mr_iid"] = 42
        mock_ctx._state["selected_environment"] = "python"
        mock_ctx._state["original_branch"] = "feature/test"
        mock_ctx._state["project_id"] = 10

        mock_env_manager.prepare_environments.return_value = [
            "exec-env-001",
            "exec-env-002",
        ]

        graph_def = self._make_graph_definition(node_id, env_count=2)
        executor = ExecEnvSetupExecutor(
            node_id=node_id,
            env_manager=mock_env_manager,
            gitlab_client=mock_gitlab_client,
            graph_definition=graph_def,
        )

        await executor.handle(msg={}, ctx=mock_ctx)

        branch_envs = mock_ctx._state["branch_envs"]
        # サブブランチが2本作成されることを確認する
        assert mock_gitlab_client.create_branch.call_count == 2
        assert 1 in branch_envs
        assert 2 in branch_envs
        # ブランチ名にサフィックスが付いていることを確認する
        assert branch_envs[1]["branch"] == "feature/test-impl-1"
        assert branch_envs[2]["branch"] == "feature/test-impl-2"

    async def test_exec_env_setup_executor_rollback_on_branch_failure(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_env_manager: MagicMock,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """サブブランチ作成失敗時に作成済みブランチがdelete_branchでロールバックされることを確認する"""
        node_id = "exec_env_setup_impl"
        mock_ctx._state["task_mr_iid"] = 42
        mock_ctx._state["selected_environment"] = "python"
        mock_ctx._state["original_branch"] = "feature/test"
        mock_ctx._state["project_id"] = 10

        mock_env_manager.prepare_environments.return_value = ["env-001", "env-002"]

        # 1本目は成功、2本目で失敗するようにモックする
        call_count: list[int] = [0]

        def branch_create_side_effect(**kwargs: object) -> None:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("GitLab branch creation failed")

        mock_gitlab_client.create_branch.side_effect = branch_create_side_effect

        graph_def = self._make_graph_definition(node_id, env_count=2)
        executor = ExecEnvSetupExecutor(
            node_id=node_id,
            env_manager=mock_env_manager,
            gitlab_client=mock_gitlab_client,
            graph_definition=graph_def,
        )

        with pytest.raises(RuntimeError):
            await executor.handle(msg={}, ctx=mock_ctx)

        # 1本目に作成したブランチがロールバックで削除されることを確認する
        mock_gitlab_client.delete_branch.assert_called_once_with(
            project_id=10,
            branch_name="feature/test-impl-1",
        )


# ========================================
# TestBranchMergeExecutor
# ========================================


class TestBranchMergeExecutor:
    """BranchMergeExecutor.handle() のテスト"""

    async def test_branch_merge_executor_handle_success(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """selected_implementationに対応するブランチが直接マージされ、非選択ブランチが削除されることを確認する"""
        mock_ctx._state["selected_implementation"] = 2
        mock_ctx._state["branch_envs"] = {
            1: {"env_id": "env-001", "branch": "feature/test-impl-1"},
            2: {"env_id": "env-002", "branch": "feature/test-impl-2"},
        }
        mock_ctx._state["original_branch"] = "feature/test"
        mock_ctx._state["project_id"] = 10

        mock_gitlab_client.branch_exists.return_value = True

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle(msg={}, ctx=mock_ctx)

        # selected_implementation=2のブランチが直接マージされることを確認する
        mock_gitlab_client.merge_branch.assert_called_once_with(
            project_id=10,
            source_branch="feature/test-impl-2",
            target_branch="feature/test",
        )

        # MRは作成されないことを確認する
        mock_gitlab_client.create_merge_request.assert_not_called()
        mock_gitlab_client.merge_merge_request.assert_not_called()

        # 非選択ブランチ（impl-1）が削除されることを確認する
        mock_gitlab_client.delete_branch.assert_called_once_with(
            project_id=10,
            branch_name="feature/test-impl-1",
        )

        # merged_branchがコンテキストに保存されることを確認する
        assert mock_ctx._state["merged_branch"] == "feature/test-impl-2"

    async def test_branch_merge_executor_skip_mr_when_same_branch(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """selected_branchとoriginal_branchが同一の場合は直接マージをスキップすることを確認する"""
        mock_ctx._state["selected_implementation"] = 1
        mock_ctx._state["branch_envs"] = {
            1: {"env_id": "env-001", "branch": "feature/test"},
        }
        mock_ctx._state["original_branch"] = "feature/test"  # 同一ブランチ
        mock_ctx._state["project_id"] = 10

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle(msg={}, ctx=mock_ctx)

        # マージが呼ばれないことを確認する（同一ブランチのためスキップ）
        mock_gitlab_client.merge_branch.assert_not_called()
        mock_gitlab_client.create_merge_request.assert_not_called()
        mock_gitlab_client.merge_merge_request.assert_not_called()

        # 非選択ブランチが存在しないため delete_branch も呼ばれないことを確認する
        mock_gitlab_client.delete_branch.assert_not_called()

        # merged_branchがコンテキストに保存されることを確認する
        assert mock_ctx._state["merged_branch"] == "feature/test"

    async def test_branch_merge_executor_skip_when_no_selected_implementation(
        self,
        mock_ctx: _ConcreteWorkflowContext,
        mock_gitlab_client: MagicMock,
    ) -> None:
        """
        selected_implementationがNoneの場合（バグ修正・テスト作成・ドキュメントタスク）に
        マージ処理をスキップすることを確認する。
        MULTI_MR_PROCESSING_FLOW.md § 4.6（ブランチマージフェーズ）に準拠する。
        """
        # selected_implementationを設定しない（コンテキストに存在しない）
        mock_ctx._state["original_branch"] = "feature/bug-fix"
        mock_ctx._state["project_id"] = 10

        executor = BranchMergeExecutor(gitlab_client=mock_gitlab_client)
        await executor.handle(msg={}, ctx=mock_ctx)

        # マージが呼ばれないことを確認する（ノーオペレーション）
        mock_gitlab_client.merge_branch.assert_not_called()
        mock_gitlab_client.create_merge_request.assert_not_called()
        mock_gitlab_client.merge_merge_request.assert_not_called()
        mock_gitlab_client.delete_branch.assert_not_called()
