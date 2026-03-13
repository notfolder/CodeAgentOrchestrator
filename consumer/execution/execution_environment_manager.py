"""
実行環境マネージャー実装モジュール

DockerコンテナのライフサイクルをDocker Python SDKで管理するExecutionEnvironmentManagerクラスと、
DBへの環境マッピング永続化機能を提供する。

CLASS_IMPLEMENTATION_SPEC.md § 6（ExecutionEnvironmentManager）に準拠する。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import asyncpg
import docker
import docker.models.containers

logger = logging.getLogger(__name__)

# コンテナ作成時のデフォルト環境名
_DEFAULT_ENVIRONMENT_NAME = "default"


class ExecutionEnvironmentManager:
    """
    Docker実行環境のライフサイクルを管理するクラス。

    プロジェクト言語に応じた適切なDockerイメージでコンテナを作成し、
    環境プールとして管理する。ノードIDと環境IDのマッピングを保持し、
    各ノードへの環境割り当てと、DBへの永続化を担う。

    CLASS_IMPLEMENTATION_SPEC.md § 6 に準拠する。

    Attributes:
        docker_client: Dockerクライアント
        environment_name_mapping: 環境名とDockerイメージ名のマッピング
        environment_pool: 準備済み環境ID（コンテナ名）一覧
        node_to_env_map: ノードIDと環境IDのマッピング
        next_env_index: 次に割り当てる環境のインデックス
        selected_environment_name: 選択された環境名
        db_pool: asyncpg接続プール
    """

    def __init__(
        self,
        docker_client: docker.DockerClient,
        environment_name_mapping: dict[str, str],
        db_pool: asyncpg.Pool,
    ) -> None:
        """
        ExecutionEnvironmentManagerを初期化する。

        Args:
            docker_client: Dockerクライアント
            environment_name_mapping: 環境名→Dockerイメージ名マッピング
            db_pool: asyncpg接続プール
        """
        self.docker_client = docker_client
        self.environment_name_mapping = environment_name_mapping
        self.environment_pool: list[str] = []
        self.node_to_env_map: dict[str, str] = {}
        self.next_env_index: int = 0
        self.selected_environment_name: str = _DEFAULT_ENVIRONMENT_NAME
        self.db_pool = db_pool

    # ===========================
    # 環境作成・割り当て
    # ===========================

    def prepare_environments(
        self,
        count: int,
        environment_name: str,
        mr_iid: int,
        node_ids: list[str],
    ) -> list[str]:
        """
        指定数のDocker環境を作成し、環境プールに登録する。

        environment_name_mappingから対応するDockerイメージを取得し、
        node_idsの各要素に対応したコンテナを作成・起動する。
        環境名が無効またはNoneの場合は'default'を使用する。

        Args:
            count: 作成する環境数
            environment_name: 使用する環境名（python, miniforge, node, default等）
            mr_iid: GitLabのMR IID
            node_ids: ノードIDのリスト（countと同数であること）

        Returns:
            作成した環境ID一覧
        """
        # 環境名からDockerイメージを取得する。無効な場合はdefaultを使用する
        image = self.environment_name_mapping.get(environment_name)
        if not image:
            logger.warning(
                "環境名 '%s' のイメージが見つからないため'default'を使用します。",
                environment_name,
            )
            image = self.environment_name_mapping.get(_DEFAULT_ENVIRONMENT_NAME, "")

        environment_ids: list[str] = []

        for node_id in node_ids:
            # 人間可読な環境IDを生成する（例: codeagent-python-mr123-code_generation）
            env_id = f"codeagent-{environment_name}-mr{mr_iid}-{node_id}"

            logger.info(
                "Dockerコンテナを作成します: env_id=%s, image=%s",
                env_id,
                image,
            )

            # Dockerコンテナを作成・起動する
            container = self.docker_client.containers.create(
                image=image,
                name=env_id,
                nano_cpus=2_000_000_000,  # CPU制限（2CPU分をナノCPU単位で指定）
                mem_limit="4g",
                network="coding-agent-network",
                detach=True,
                tty=True,
            )
            container.start()
            logger.info("コンテナを起動しました: env_id=%s", env_id)

            environment_ids.append(env_id)

        # 環境プールと選択中の環境名を更新する
        self.environment_pool = environment_ids
        self.selected_environment_name = environment_name

        return environment_ids

    def prepare_plan_environment(self, environment_name: str, mr_iid: int) -> str:
        """
        プランニング用のDocker環境を1つ作成し、環境プールに追加する。

        Args:
            environment_name: 使用する環境名
            mr_iid: GitLabのMR IID

        Returns:
            作成した環境ID
        """
        # プランニング用の環境IDを生成する
        env_id = f"codeagent-plan-mr{mr_iid}"

        image = self.environment_name_mapping.get(environment_name)
        if not image:
            logger.warning(
                "環境名 '%s' のイメージが見つからないため'default'を使用します。",
                environment_name,
            )
            image = self.environment_name_mapping.get(_DEFAULT_ENVIRONMENT_NAME, "")

        logger.info(
            "プランニング用Dockerコンテナを作成します: env_id=%s, image=%s",
            env_id,
            image,
        )

        container = self.docker_client.containers.create(
            image=image,
            name=env_id,
            nano_cpus=2_000_000_000,  # CPU制限（2CPU分をナノCPU単位で指定）
            mem_limit="4g",
            network="coding-agent-network",
            detach=True,
            tty=True,
        )
        container.start()
        logger.info("プランニングコンテナを起動しました: env_id=%s", env_id)

        self.environment_pool.append(env_id)
        return env_id

    def get_environment(self, node_id: str) -> str:
        """
        ノードIDに対応する環境IDを返す。

        既にマッピングが存在する場合はそれを返す。
        存在しない場合は環境プールから次の未使用環境IDを割り当てる。
        プールを超えた場合はRuntimeErrorをスローする。

        Args:
            node_id: ノードID

        Returns:
            対応する環境ID

        Raises:
            RuntimeError: 環境プールの容量を超えた場合
        """
        # 既存マッピングが存在する場合はそのまま返す
        if node_id in self.node_to_env_map:
            return self.node_to_env_map[node_id]

        # 環境プールの容量を超えていないか確認する
        if self.next_env_index >= len(self.environment_pool):
            raise RuntimeError(
                f"環境プールの容量が不足しています: node_id={node_id}, "
                f"pool_size={len(self.environment_pool)}, "
                f"next_index={self.next_env_index}"
            )

        # プールから環境IDを割り当ててマッピングに登録する
        env_id = self.environment_pool[self.next_env_index]
        self.node_to_env_map[node_id] = env_id
        self.next_env_index += 1

        logger.debug(
            "環境を割り当てました: node_id=%s, env_id=%s",
            node_id,
            env_id,
        )
        return env_id

    def get_container(
        self, env_id: str
    ) -> docker.models.containers.Container:
        """
        環境IDに対応するDockerコンテナを取得する。

        Args:
            env_id: 環境ID（コンテナ名）

        Returns:
            Dockerコンテナオブジェクト
        """
        return self.docker_client.containers.get(env_id)

    # ===========================
    # コマンド実行・リポジトリクローン
    # ===========================

    def execute_command(
        self, node_id: str, command: str
    ) -> tuple[int, bytes]:
        """
        指定ノードの環境でコマンドを実行する。

        Args:
            node_id: ノードID
            command: 実行するシェルコマンド文字列

        Returns:
            (exit_code, output) のタプル
        """
        env_id = self.get_environment(node_id)
        container = self.docker_client.containers.get(env_id)
        exit_code, output = container.exec_run(command)
        logger.debug(
            "コマンド実行完了: node_id=%s, exit_code=%d",
            node_id,
            exit_code,
        )
        return exit_code, output

    def clone_repository(
        self, node_id: str, repo_url: str, branch: str
    ) -> None:
        """
        指定ノードの環境にGitリポジトリをクローンする。

        /workspace ディレクトリにクローンし、exit_code != 0の場合は
        RuntimeErrorをスローする。

        Args:
            node_id: ノードID
            repo_url: クローン対象リポジトリURL
            branch: チェックアウトするブランチ名

        Raises:
            RuntimeError: git cloneが失敗した場合
        """
        command = f"git clone -b {branch} {repo_url} /workspace"
        exit_code, output = self.execute_command(node_id, command)

        if exit_code != 0:
            raise RuntimeError(
                f"git cloneに失敗しました: node_id={node_id}, "
                f"repo_url={repo_url}, branch={branch}, "
                f"exit_code={exit_code}, output={output!r}"
            )
        logger.info(
            "リポジトリクローン完了: node_id=%s, repo_url=%s, branch=%s",
            node_id,
            repo_url,
            branch,
        )

    # ===========================
    # 環境クリーンアップ
    # ===========================

    def cleanup_environments(self) -> None:
        """
        環境プール内の全コンテナを停止・削除し、プールをリセットする。

        environment_poolの各コンテナをstop()してremove()した後、
        environment_pool・node_to_env_map・next_env_indexをリセットする。
        """
        for env_id in self.environment_pool:
            try:
                container = self.docker_client.containers.get(env_id)
                container.stop()
                container.remove()
                logger.info("コンテナを停止・削除しました: env_id=%s", env_id)
            except docker.errors.NotFound:
                logger.warning(
                    "クリーンアップ対象のコンテナが見つかりません: env_id=%s",
                    env_id,
                )
            except docker.errors.APIError as exc:
                logger.error(
                    "コンテナのクリーンアップ中にエラーが発生しました: env_id=%s, error=%s",
                    env_id,
                    exc,
                )

        # 各種状態をリセットする
        self.environment_pool = []
        self.node_to_env_map = {}
        self.next_env_index = 0
        logger.info("環境プールをリセットしました。")

    # ===========================
    # DB永続化・復元
    # ===========================

    async def save_environment_mapping(self, execution_id: str) -> None:
        """
        node_to_env_mapの内容をDBのdocker_environment_mappingsテーブルに保存する。

        各ノード・コンテナペアについてレコードをINSERTする。

        Args:
            execution_id: 実行ID
        """
        now = datetime.now(tz=timezone.utc)

        async with self.db_pool.acquire() as conn:
            for node_id, env_id in self.node_to_env_map.items():
                mapping_id = str(uuid.uuid4())
                container_name = f"coding-agent-exec-{execution_id}-{node_id}"

                await conn.execute(
                    """
                    INSERT INTO docker_environment_mappings (
                        mapping_id,
                        execution_id,
                        node_id,
                        container_id,
                        container_name,
                        environment_name,
                        status,
                        created_at,
                        updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    mapping_id,
                    execution_id,
                    node_id,
                    env_id,
                    container_name,
                    self.selected_environment_name,
                    "stopped",
                    now,
                    now,
                )
                logger.debug(
                    "環境マッピングを保存しました: execution_id=%s, node_id=%s, env_id=%s",
                    execution_id,
                    node_id,
                    env_id,
                )

        logger.info(
            "全環境マッピングをDBに保存しました: execution_id=%s, count=%d",
            execution_id,
            len(self.node_to_env_map),
        )

    async def load_environment_mapping(self, execution_id: str) -> None:
        """
        DBのdocker_environment_mappingsテーブルからマッピングを復元する。

        node_to_env_map・environment_pool・selected_environment_nameを復元する。

        Args:
            execution_id: 実行ID
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT node_id, container_id, environment_name
                FROM docker_environment_mappings
                WHERE execution_id = $1
                """,
                execution_id,
            )

        # マッピングと環境プールを復元する
        self.node_to_env_map = {}
        self.environment_pool = []
        environment_name_restored = False

        for row in rows:
            node_id: str = row["node_id"]
            container_id: str = row["container_id"]
            environment_name: str = row["environment_name"]

            self.node_to_env_map[node_id] = container_id
            self.environment_pool.append(container_id)
            # 最初のレコードから environment_name を設定する（全行で同一値のはず）
            if not environment_name_restored:
                self.selected_environment_name = environment_name
                environment_name_restored = True

        logger.info(
            "環境マッピングをDBから復元しました: execution_id=%s, count=%d",
            execution_id,
            len(self.node_to_env_map),
        )

    async def stop_all_containers(self, execution_id: str) -> None:
        """
        環境プール内の全コンテナを停止し、DBのstatusを'stopped'に更新する。

        Args:
            execution_id: 実行ID
        """
        for container_id in self.environment_pool:
            try:
                container = self.docker_client.containers.get(container_id)
                container.stop()
                logger.info("コンテナを停止しました: container_id=%s", container_id)
            except docker.errors.NotFound:
                logger.warning(
                    "停止対象のコンテナが見つかりません: container_id=%s",
                    container_id,
                )
            except docker.errors.APIError as exc:
                logger.error(
                    "コンテナ停止中にエラーが発生しました: container_id=%s, error=%s",
                    container_id,
                    exc,
                )

        # DBのstatusを'stopped'に更新する
        now = datetime.now(tz=timezone.utc)
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE docker_environment_mappings
                SET status = 'stopped', updated_at = $1
                WHERE execution_id = $2
                """,
                now,
                execution_id,
            )

        logger.info(
            "全コンテナを停止しDBを更新しました: execution_id=%s",
            execution_id,
        )

    async def start_all_containers(self, execution_id: str) -> None:
        """
        環境プール内の全コンテナを起動し、DBのstatusを'running'に更新する。

        Args:
            execution_id: 実行ID
        """
        for container_id in self.environment_pool:
            try:
                container = self.docker_client.containers.get(container_id)
                container.start()
                logger.info("コンテナを起動しました: container_id=%s", container_id)
            except docker.errors.NotFound:
                logger.warning(
                    "起動対象のコンテナが見つかりません: container_id=%s",
                    container_id,
                )
            except docker.errors.APIError as exc:
                logger.error(
                    "コンテナ起動中にエラーが発生しました: container_id=%s, error=%s",
                    container_id,
                    exc,
                )

        # DBのstatusを'running'に更新する
        now = datetime.now(tz=timezone.utc)
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE docker_environment_mappings
                SET status = 'running', updated_at = $1
                WHERE execution_id = $2
                """,
                now,
                execution_id,
            )

        logger.info(
            "全コンテナを起動しDBを更新しました: execution_id=%s",
            execution_id,
        )

    async def check_containers_exist(self, execution_id: str) -> bool:
        """
        execution_idに紐付く全コンテナがDockerホスト上に存在するか確認する。

        DBからcontainer_idリストを取得し、各コンテナの存在をdocker_clientで確認する。
        1つでも存在しない場合はFalseを返す。

        Args:
            execution_id: 実行ID

        Returns:
            全コンテナが存在する場合True、1つでも存在しない場合False
        """
        # DBからcontainer_idの一覧を取得する
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT container_id
                FROM docker_environment_mappings
                WHERE execution_id = $1
                """,
                execution_id,
            )

        if not rows:
            logger.warning(
                "execution_idに対応する環境マッピングが見つかりません: execution_id=%s",
                execution_id,
            )
            return False

        # 全コンテナの存在を確認する（停止中含む）
        # env_idはコンテナ名として保存されているため、コンテナ名でチェックする
        existing_containers = self.docker_client.containers.list(all=True)
        existing_names = {c.name for c in existing_containers}

        for row in rows:
            container_id: str = row["container_id"]
            if container_id not in existing_names:
                logger.warning(
                    "コンテナが存在しません: container_id=%s, execution_id=%s",
                    container_id,
                    execution_id,
                )
                return False

        logger.debug(
            "全コンテナの存在を確認しました: execution_id=%s, count=%d",
            execution_id,
            len(rows),
        )
        return True
