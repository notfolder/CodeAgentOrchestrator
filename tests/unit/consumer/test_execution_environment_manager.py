"""
ExecutionEnvironmentManagerの単体テスト

DockerコンテナのライフサイクルをモックしてExecutionEnvironmentManagerの
環境作成・割り当て・クリーンアップ・DB永続化機能を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.execution_environment_manager import ExecutionEnvironmentManager


# ========================================
# テスト用フィクスチャ
# ========================================


@pytest.fixture
def mock_docker_client() -> MagicMock:
    """モックDockerクライアントを返す"""
    client = MagicMock()
    mock_container = MagicMock()
    client.containers.create.return_value = mock_container
    client.containers.get.return_value = mock_container
    return client


@pytest.fixture
def mock_db_pool() -> MagicMock:
    """モックasyncpg接続プールを返す"""
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    # async context managerとして動作させる
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.fixture
def env_name_mapping() -> dict[str, str]:
    """テスト用環境名→Dockerイメージマッピングを返す"""
    return {
        "python": "python:3.11-slim",
        "miniforge": "condaforge/miniforge3:latest",
        "node": "node:20-slim",
        "default": "ubuntu:22.04",
    }


@pytest.fixture
def env_manager(
    mock_docker_client: MagicMock,
    env_name_mapping: dict[str, str],
    mock_db_pool: MagicMock,
) -> ExecutionEnvironmentManager:
    """テスト用ExecutionEnvironmentManagerを返す"""
    return ExecutionEnvironmentManager(
        docker_client=mock_docker_client,
        environment_name_mapping=env_name_mapping,
        db_pool=mock_db_pool,
    )


# ========================================
# TestPrepareEnvironments
# ========================================


class TestPrepareEnvironments:
    """prepare_environments()のテスト"""

    def test_正常に環境を作成できる(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
    ) -> None:
        """docker_clientをモックし、prepare_environments(count=2)が2つのenv_idを返すことを確認する"""
        node_ids = ["node1", "node2"]
        result = env_manager.prepare_environments(
            count=2,
            environment_name="python",
            mr_iid=123,
            node_ids=node_ids,
        )

        assert len(result) == 2
        # コンテナが2つ作成されていることを確認する
        assert mock_docker_client.containers.create.call_count == 2
        # 各env_idが正しいフォーマットであることを確認する
        assert result[0] == "codeagent-python-mr123-node1"
        assert result[1] == "codeagent-python-mr123-node2"
        # 環境プールに登録されていることを確認する
        assert env_manager.environment_pool == result

    def test_無効な環境名の場合defaultイメージを使用する(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
        env_name_mapping: dict[str, str],
    ) -> None:
        """不正な環境名でdefaultイメージが使用されることを確認する"""
        env_manager.prepare_environments(
            count=1,
            environment_name="ruby",  # 無効な環境名
            mr_iid=456,
            node_ids=["node1"],
        )

        # containers.createがdefaultイメージで呼び出されることを確認する
        call_kwargs = mock_docker_client.containers.create.call_args
        assert call_kwargs[1]["image"] == env_name_mapping["default"]


# ========================================
# TestGetEnvironment
# ========================================


class TestGetEnvironment:
    """get_environment()のテスト"""

    def test_割り当て済みノードに対してenv_idを返す(
        self,
        env_manager: ExecutionEnvironmentManager,
    ) -> None:
        """既存マッピングから正しくenv_idを返すことを確認する"""
        env_manager.node_to_env_map["node1"] = "codeagent-python-mr1-node1"

        result = env_manager.get_environment("node1")

        assert result == "codeagent-python-mr1-node1"

    def test_未割り当てノードに環境プールから割り当てる(
        self,
        env_manager: ExecutionEnvironmentManager,
    ) -> None:
        """environment_poolから次のenv_idを割り当てることを確認する"""
        env_manager.environment_pool = ["env-001", "env-002"]
        env_manager.next_env_index = 0

        result = env_manager.get_environment("node-new")

        assert result == "env-001"
        assert env_manager.node_to_env_map["node-new"] == "env-001"
        assert env_manager.next_env_index == 1

    def test_プール不足時にRuntimeErrorが発生する(
        self,
        env_manager: ExecutionEnvironmentManager,
    ) -> None:
        """プール超過時にRuntimeErrorをスローすることを確認する"""
        env_manager.environment_pool = ["env-001"]
        env_manager.next_env_index = 1  # すでにプール上限に達している

        with pytest.raises(RuntimeError, match="容量が不足"):
            env_manager.get_environment("node-overflow")


# ========================================
# TestCleanupEnvironments
# ========================================


class TestCleanupEnvironments:
    """cleanup_environments()のテスト"""

    def test_全コンテナが停止_削除される(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
    ) -> None:
        """cleanup_environments()が全コンテナをstopとremoveすることを確認する"""
        env_manager.environment_pool = ["env-001", "env-002"]
        mock_container = mock_docker_client.containers.get.return_value

        env_manager.cleanup_environments()

        # 各コンテナがstopとremoveされていることを確認する
        assert mock_container.stop.call_count == 2
        assert mock_container.remove.call_count == 2

    def test_クリーンアップ後に環境プールが空になる(
        self,
        env_manager: ExecutionEnvironmentManager,
    ) -> None:
        """クリーンアップ後にenvironment_poolが空であることを確認する"""
        env_manager.environment_pool = ["env-001", "env-002"]
        env_manager.node_to_env_map = {"node1": "env-001"}
        env_manager.next_env_index = 1

        env_manager.cleanup_environments()

        assert env_manager.environment_pool == []
        assert env_manager.node_to_env_map == {}
        assert env_manager.next_env_index == 0


# ========================================
# TestSaveLoadEnvironmentMapping
# ========================================


class TestSaveLoadEnvironmentMapping:
    """save_environment_mapping() / load_environment_mapping()のテスト"""

    @pytest.mark.asyncio
    async def test_環境マッピングをDBに保存できる(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_db_pool: MagicMock,
    ) -> None:
        """save_environment_mapping()がINSERTを実行することを確認する"""
        env_manager.node_to_env_map = {"node1": "env-001"}
        env_manager.selected_environment_name = "python"

        # acquireのコンテキストマネージャからasyncpg接続を取得する
        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value

        await env_manager.save_environment_mapping("exec-uuid-001")

        # execute (INSERT) が1回呼び出されていることを確認する
        assert mock_conn.execute.call_count >= 1
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "INSERT" in call_args_str

    @pytest.mark.asyncio
    async def test_DBから環境マッピングを復元できる(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_db_pool: MagicMock,
    ) -> None:
        """load_environment_mapping()でnode_to_env_mapが復元されることを確認する"""
        # fetchが返すRowのモックを作成する
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "node_id": "node1",
            "container_id": "env-001",
            "environment_name": "python",
        }[key]

        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch = AsyncMock(return_value=[mock_row])

        await env_manager.load_environment_mapping("exec-uuid-001")

        assert env_manager.node_to_env_map == {"node1": "env-001"}
        assert "env-001" in env_manager.environment_pool
        assert env_manager.selected_environment_name == "python"


# ========================================
# TestExecuteCommand
# ========================================


class TestExecuteCommand:
    """execute_command()のテスト"""

    def test_コマンドを実行してexit_codeとoutputを返す(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
    ) -> None:
        """execute_command()がコンテナ内でコマンドを実行し(exit_code, output)を返すことを確認する"""
        env_manager.environment_pool = ["codeagent-python-mr1-node1"]
        env_manager.node_to_env_map["node1"] = "codeagent-python-mr1-node1"
        mock_container = mock_docker_client.containers.get.return_value
        mock_container.exec_run.return_value = (0, b"hello world")

        exit_code, output = env_manager.execute_command("node1", "echo hello world")

        assert exit_code == 0
        assert output == b"hello world"
        mock_container.exec_run.assert_called_once_with("echo hello world")

    def test_clone_repositoryが成功する(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
    ) -> None:
        """clone_repository()がgit cloneコマンドを実行することを確認する"""
        env_manager.environment_pool = ["codeagent-python-mr1-node1"]
        env_manager.node_to_env_map["node1"] = "codeagent-python-mr1-node1"
        mock_container = mock_docker_client.containers.get.return_value
        mock_container.exec_run.return_value = (0, b"Cloning into '/workspace'...")

        # 例外が発生しないことを確認する
        env_manager.clone_repository("node1", "https://example.com/repo.git", "main")

        call_args = mock_container.exec_run.call_args[0][0]
        assert "git clone" in call_args
        assert "main" in call_args
        assert "/workspace" in call_args

    def test_clone_repositoryが失敗時にRuntimeErrorをスローする(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
    ) -> None:
        """git cloneが失敗した場合にRuntimeErrorが発生することを確認する"""
        env_manager.environment_pool = ["codeagent-python-mr1-node1"]
        env_manager.node_to_env_map["node1"] = "codeagent-python-mr1-node1"
        mock_container = mock_docker_client.containers.get.return_value
        mock_container.exec_run.return_value = (1, b"fatal: repository not found")

        with pytest.raises(RuntimeError, match="git cloneに失敗"):
            env_manager.clone_repository(
                "node1", "https://example.com/invalid.git", "main"
            )


# ========================================
# TestContainerLifecycle
# ========================================


class TestContainerLifecycle:
    """stop_all_containers / start_all_containers / check_containers_existのテスト"""

    @pytest.mark.asyncio
    async def test_stop_all_containersが全コンテナを停止しDBを更新する(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
        mock_db_pool: MagicMock,
    ) -> None:
        """stop_all_containers()がcontainer.stop()を呼び出しDBを'stopped'に更新することを確認する"""
        env_manager.environment_pool = ["env-001", "env-002"]
        mock_container = mock_docker_client.containers.get.return_value
        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value

        await env_manager.stop_all_containers("exec-uuid-001")

        # 各コンテナのstop()が呼ばれていることを確認する
        assert mock_container.stop.call_count == 2
        # DBのUPDATEが呼ばれていることを確認する
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "UPDATE" in call_args_str
        assert "stopped" in call_args_str

    @pytest.mark.asyncio
    async def test_start_all_containersが全コンテナを起動しDBを更新する(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
        mock_db_pool: MagicMock,
    ) -> None:
        """start_all_containers()がcontainer.start()を呼び出しDBを'running'に更新することを確認する"""
        env_manager.environment_pool = ["env-001"]
        mock_container = mock_docker_client.containers.get.return_value
        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value

        await env_manager.start_all_containers("exec-uuid-001")

        mock_container.start.assert_called_once()
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "UPDATE" in call_args_str
        assert "running" in call_args_str

    @pytest.mark.asyncio
    async def test_check_containers_existが全コンテナ存在時にTrueを返す(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
        mock_db_pool: MagicMock,
    ) -> None:
        """全コンテナがDockerに存在する場合にTrueを返すことを確認する"""
        # DBから "env-001" を返す
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {"container_id": "env-001"}[key]
        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch = AsyncMock(return_value=[mock_row])

        # containers.list(all=True) が "env-001" を持つコンテナを返す
        mock_container = MagicMock()
        mock_container.name = "env-001"
        mock_docker_client.containers.list.return_value = [mock_container]

        result = await env_manager.check_containers_exist("exec-uuid-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_containers_existがコンテナ不存在時にFalseを返す(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_docker_client: MagicMock,
        mock_db_pool: MagicMock,
    ) -> None:
        """コンテナが1つでも存在しない場合にFalseを返すことを確認する"""
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {"container_id": "env-missing"}[key]
        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch = AsyncMock(return_value=[mock_row])

        # containers.list が空を返す（コンテナが存在しない）
        mock_docker_client.containers.list.return_value = []

        result = await env_manager.check_containers_exist("exec-uuid-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_containers_existがDBにレコードなしの場合にFalseを返す(
        self,
        env_manager: ExecutionEnvironmentManager,
        mock_db_pool: MagicMock,
    ) -> None:
        """execution_idに対応するDBレコードがない場合にFalseを返すことを確認する"""
        mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch = AsyncMock(return_value=[])

        result = await env_manager.check_containers_exist("nonexistent-exec-id")

        assert result is False
