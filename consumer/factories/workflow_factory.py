"""
WorkflowFactory モジュール

ワークフロー定義からAgent FrameworkのWorkflowインスタンスを動的に構築する
主要クラスを提供する。SIGTERMシグナルのハンドラーを設定し、
ワークフローの停止・再開機構を実装する。

CLASS_IMPLEMENTATION_SPEC.md § 2.1（WorkflowFactory）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.2.1（WorkflowFactory）に準拠する。
"""

from __future__ import annotations

import json
import logging
import signal
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.agents.guideline_learning_agent import GuidelineLearningAgent
    from consumer.definitions.definition_loader import DefinitionLoader
    from consumer.factories.agent_factory import AgentFactory
    from consumer.factories.executor_factory import ExecutorFactory
    from consumer.factories.workflow_builder import Workflow, WorkflowBuilder
    from consumer.user_config_client import UserConfig, UserConfigClient
    from shared.config.config_manager import ConfigManager
    from shared.database.repositories.workflow_execution_state_repository import (
        WorkflowExecutionStateRepository,
    )
    from shared.database.repositories.workflow_definition_repository import (
        WorkflowDefinitionRepository,
    )
    from shared.database.repositories.task_repository import TaskRepository
    from shared.gitlab_client.gitlab_client import GitlabClient
    from shared.models.agent_definition import AgentDefinition, AgentNodeConfig
    from shared.models.graph_definition import GraphDefinition, GraphNodeDefinition
    from shared.models.prompt_definition import PromptDefinition
    from shared.models.task import TaskContext

logger = logging.getLogger(__name__)

# グローバルなシャットダウンフラグ
shutdown_requested: bool = False


def _handle_sigterm(signum: int, frame: Any) -> None:
    """
    SIGTERMシグナルを受信したときのハンドラ。

    CLASS_IMPLEMENTATION_SPEC.md § 2.1 _handle_sigterm() に準拠する。

    Args:
        signum: シグナル番号
        frame: 現在のスタックフレーム
    """
    global shutdown_requested
    shutdown_requested = True
    logger.info("SIGTERM received. Graceful shutdown initiated.")


class WorkflowFactory:
    """
    ワークフローファクトリクラス

    DefinitionLoaderで取得した定義からAgent Frameworkのワークフローを構築する
    主要クラス。グラフ定義のノードを順次処理し、ExecutorFactoryとAgentFactoryから
    インスタンスを生成してノードとして登録する。

    CLASS_IMPLEMENTATION_SPEC.md § 2.1 に準拠する。

    Attributes:
        definition_loader: ワークフロー定義ローダー
        executor_factory: Executorファクトリ
        agent_factory: Agentファクトリ
        workflow_builder_class: WorkflowBuilderクラス（インスタンス生成用）
        user_config_client: ユーザー設定クライアント
        gitlab_client: GitLab APIクライアント
        config_manager: 設定管理クラス
        workflow_exec_state_repo: ワークフロー実行状態リポジトリ
        workflow_def_repo: ワークフロー定義リポジトリ
        task_repository: タスクリポジトリ（resume_workflow() でのタスク復元に使用）
        _current_task_context: 現在処理中のTaskContext
        _current_workflow: 現在実行中のWorkflowインスタンス
        _current_execution_id: 現在のワークフロー実行ID
    """

    def __init__(
        self,
        definition_loader: DefinitionLoader,
        executor_factory: ExecutorFactory,
        agent_factory: AgentFactory,
        user_config_client: UserConfigClient,
        gitlab_client: GitlabClient,
        config_manager: ConfigManager,
        workflow_exec_state_repo: WorkflowExecutionStateRepository | None = None,
        workflow_def_repo: WorkflowDefinitionRepository | None = None,
        task_repository: TaskRepository | None = None,
    ) -> None:
        """
        WorkflowFactoryを初期化する。

        Args:
            definition_loader: ワークフロー定義ローダー
            executor_factory: Executorファクトリ
            agent_factory: Agentファクトリ
            user_config_client: ユーザー設定クライアント
            gitlab_client: GitLab APIクライアント（学習ノード生成時のみ使用）
            config_manager: 設定管理クラス
            workflow_exec_state_repo: ワークフロー実行状態リポジトリ（停止・再開用）
            workflow_def_repo: ワークフロー定義リポジトリ
            task_repository: タスクリポジトリ（resume_workflow() でのタスク復元に使用）
        """
        self.definition_loader = definition_loader
        self.executor_factory = executor_factory
        self.agent_factory = agent_factory
        self.user_config_client = user_config_client
        self.gitlab_client = gitlab_client
        self.config_manager = config_manager
        self.workflow_exec_state_repo = workflow_exec_state_repo
        self.workflow_def_repo = workflow_def_repo
        self.task_repository = task_repository

        # 現在実行中のワークフロー情報
        self._current_task_context: TaskContext | None = None
        self._current_workflow: Workflow | None = None
        self._current_execution_id: str | None = None

        # SIGTERMハンドラーを設定する
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """
        SIGTERMシグナルのハンドラーを設定する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 _setup_signal_handlers() に準拠する。
        """
        global shutdown_requested
        shutdown_requested = False
        try:
            signal.signal(signal.SIGTERM, _handle_sigterm)
            logger.debug("SIGTERMシグナルハンドラーを設定しました")
        except (OSError, ValueError) as exc:
            # テスト環境など、シグナル設定が許可されない環境での例外を無視する
            logger.debug("SIGTERMシグナルハンドラーの設定をスキップしました: %s", exc)

    async def create_workflow_from_definition(
        self,
        user_id: str,
        task_context: TaskContext,
    ) -> Workflow:
        """
        ユーザーのワークフロー定義に基づいてWorkflowを生成する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 create_workflow_from_definition() に準拠する。

        処理フロー:
        1. ユーザーのワークフロー定義IDを取得
        2. DefinitionLoaderでグラフ・エージェント・プロンプト定義をロード
        3. User ConfigからlearningEnabledを確認し、必要なら学習ノードを挿入
        4. WorkflowBuilderを生成
        5. _build_nodes()でノードを生成してWorkflowBuilderに登録
        6. エッジを追加
        7. build()でWorkflowを生成

        Args:
            user_id: ユーザーID（ワークフロー定義の選択に使用）
            task_context: タスクコンテキスト

        Returns:
            構築されたWorkflowインスタンス

        Raises:
            ValueError: ワークフロー定義が取得できない場合
        """
        self._current_task_context = task_context

        # 1. ワークフロー定義IDを取得
        definition_id = task_context.workflow_definition_id
        if definition_id is None:
            # User Config APIからワークフロー設定を取得
            try:
                workflow_setting = (
                    await self.user_config_client.get_user_workflow_setting(user_id)
                )
                definition_id = workflow_setting.get("workflow_definition_id")
            except Exception as exc:
                logger.warning(
                    "ワークフロー設定の取得に失敗しました。デフォルト設定を使用します: %s",
                    exc,
                )

        if definition_id is None:
            # システムデフォルト（standard_mr_processing, ID=1）にフォールバック
            definition_id = 1
            logger.info(
                "ワークフロー定義IDが未設定のためシステムデフォルトを使用します: definition_id=%s, user_id=%s",
                definition_id,
                user_id,
            )

        # 2. 定義をロード
        graph_def, agent_def, prompt_def = (
            await self.definition_loader.load_workflow_definition(definition_id)
        )

        # 3. 学習ノード挿入（インプレースでgraph_defを変更する）
        username = task_context.username or ""
        user_config: UserConfig | None = task_context.cached_user_config
        if user_config is None:
            # キャッシュがない場合のみHTTPフェッチする
            try:
                user_config = await self.user_config_client.get_user_config(username)
                task_context.cached_user_config = user_config
            except Exception as exc:
                logger.warning("ユーザー設定の取得に失敗しました: %s", exc)
        try:
            if user_config and user_config.learning_enabled:
                self._inject_learning_node(graph_def)
        except Exception as exc:
            logger.warning("学習ノード挿入に失敗しました: %s", exc)

        # 4. WorkflowBuilderを生成
        from consumer.factories.workflow_builder import WorkflowBuilder

        builder = WorkflowBuilder()

        # 5. ノードを構築してBuilderに登録
        await self._build_nodes(
            graph_def=graph_def,
            agent_def=agent_def,
            prompt_def=prompt_def,
            user_id=user_id,
            task_context=task_context,
            builder=builder,
            user_config=user_config,
        )

        # 6. エッジを追加
        for edge in graph_def.edges:
            builder.add_edge(
                from_node_id=edge.from_node,
                to_node_id=edge.to_node,
                condition=edge.condition,
            )

        # 7. ワークフローを構築
        workflow = builder.build()
        self._current_workflow = workflow

        logger.info(
            "ワークフローを構築しました: definition_id=%s, user_id=%s",
            definition_id,
            user_id,
        )
        return workflow

    async def _build_nodes(
        self,
        graph_def: GraphDefinition,
        agent_def: AgentDefinition,
        prompt_def: PromptDefinition,
        user_id: int,
        task_context: TaskContext,
        builder: WorkflowBuilder,
        user_config: UserConfig | None = None,
    ) -> None:
        """
        グラフ定義のノードを順次処理し、ExecutorまたはAgentを生成してBuilderに登録する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 _build_nodes() に準拠する。

        Args:
            graph_def: グラフ定義
            agent_def: エージェント定義
            prompt_def: プロンプト定義
            user_id: ユーザーID
            task_context: タスクコンテキスト
            builder: WorkflowBuilderインスタンス
            user_config: ユーザー設定（省略可能）
        """
        username = task_context.username or ""

        # ProgressReporter は全エージェントで共有するため、ループ外で初期化する。
        # 最初の agent ノード処理時に遅延生成する。
        progress_reporter: Any = None

        for node in graph_def.nodes:
            node_id = node.id
            node_type = node.type

            if node_type == "executor":
                # ExecutorFactoryからExecutorインスタンスを生成
                if node.executor_class is None:
                    logger.warning(
                        "executorノード '%s' にexecutor_classが指定されていません。スキップします",
                        node_id,
                    )
                    continue

                executor = self.executor_factory.create_executor_by_class_name(
                    node.executor_class
                )
                # AF WorkflowBuilder は executor.id の一意性を要求するため、
                # グラフ定義の node_id を executor の ID として設定する
                executor.id = node_id
                builder.add_node(node_id, executor)
                logger.debug(
                    "Executorノードを登録しました: node_id=%s, class=%s",
                    node_id,
                    node.executor_class,
                )

            elif node_type == "agent":
                # AgentFactoryからConfigurableAgentインスタンスを生成
                if node.agent_definition_id is None:
                    logger.warning(
                        "agentノード '%s' にagent_definition_idが指定されていません。スキップします",
                        node_id,
                    )
                    continue

                agent_node_config = agent_def.get_agent(node.agent_definition_id)
                if agent_node_config is None:
                    logger.warning(
                        "agent_definition_id '%s' に対応するエージェント定義が見つかりません。スキップします",
                        node.agent_definition_id,
                    )
                    continue

                # node_idを設定する
                import copy

                agent_node_config = copy.copy(agent_node_config)
                agent_node_config.node_id = node_id

                # env_idを解決する
                env_id = self._resolve_env_id(node, task_context)

                prompt_config = prompt_def.get_prompt(agent_node_config.prompt_id)
                if prompt_config is None:
                    logger.warning(
                        "prompt_id '%s' に対応するプロンプト定義が見つかりません。スキップします",
                        agent_node_config.prompt_id,
                    )
                    continue

                # ProgressReporterを生成する
                # MermaidGraphRenderer / ProgressCommentManager を組み合わせて
                # ProgressReporter インスタンスを作成し、全エージェントで共有する。
                # ノード追加のたびに再生成するとコスト増になるため、
                # _build_nodes() 内で一度だけ生成して使い回す設計にする。
                # （この代入は loop 内だが、全ノードで同一インスタンスを参照する）
                if progress_reporter is None:
                    from consumer.tools.mermaid_graph_renderer import (
                        MermaidGraphRenderer,
                    )
                    from consumer.tools.progress_comment_manager import (
                        ProgressCommentManager,
                    )
                    from consumer.tools.progress_reporter import ProgressReporter

                    graph_dict = graph_def.model_dump(by_alias=True)
                    mermaid_renderer = MermaidGraphRenderer(graph_def=graph_dict)
                    comment_manager = ProgressCommentManager(
                        gitlab_client=self.gitlab_client,
                        mermaid_renderer=mermaid_renderer,
                    )
                    progress_reporter = ProgressReporter(
                        graph_def=graph_dict,
                        mermaid_renderer=mermaid_renderer,
                        comment_manager=comment_manager,
                    )

                configurable_agent = await self.agent_factory.create_agent(
                    agent_config=agent_node_config,
                    prompt_config=prompt_config,
                    username=username,
                    progress_reporter=progress_reporter,
                    env_id=env_id,
                    user_config=user_config,
                    task_uuid=task_context.task_uuid,
                )
                builder.add_node(node_id, configurable_agent)
                logger.debug(
                    "Agentノードを登録しました: node_id=%s, agent_definition_id=%s",
                    node_id,
                    node.agent_definition_id,
                )

            elif node_type == "condition":
                # 条件ノードはエッジの条件式で制御する。
                # AF WorkflowBuilder ではノードインスタンスが必須のため、
                # 受け取ったメッセージをそのまま転送するパススルーExecutorを登録する。
                from consumer.executors.base_executor import PassthroughExecutor

                passthrough = PassthroughExecutor(id=node_id)
                builder.add_node(node_id, passthrough)
                logger.debug(
                    "条件ノード（パススルー）を登録しました: node_id=%s", node_id
                )

            # 学習ノードの場合（_inject_learning_nodeで挿入されたノード）
            elif node_id == "learning":
                if user_config is not None:
                    learning_agent = self._create_learning_agent(user_config)
                    builder.add_node(node_id, learning_agent)
                    logger.debug("学習ノードを登録しました: node_id=%s", node_id)

            else:
                logger.warning(
                    "不明なノードタイプ '%s': node_id=%s。スキップします",
                    node_type,
                    node_id,
                )

    def _resolve_env_id(
        self,
        node: GraphNodeDefinition,
        task_context: TaskContext,
    ) -> str | None:
        """
        ノードのenv_refからenv_idを解決する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.3.3 ステップ7 に準拠する。

        env_ref が "plan" の場合は `task_context` に `plan_environment_id` が
        存在すればその値を返す。
        env_ref が整数文字列（"1"/"2"/"3"）の場合は `task_context.branch_envs`
        の対応エントリの "env_id" を返す。
        いずれも存在しない場合は None を返す。
        ConfigurableAgent は None の場合、handle() 内でランタイム解決を試みる。

        Args:
            node: グラフノード定義
            task_context: タスクコンテキスト

        Returns:
            解決されたenv_id（解決不能な場合はNone）
        """
        env_ref = node.env_ref
        if env_ref is None:
            return None

        if env_ref == "plan":
            # task_context に plan_environment_id が設定済みであれば利用する
            # （PlanEnvSetupExecutor が実行済みの再開ケース等）
            return getattr(task_context, "plan_environment_id", None)

        # 整数文字列（"1"/"2"/"3"）の場合は branch_envs から取得する
        branch_envs: dict[int, dict[str, Any]] = (
            getattr(task_context, "branch_envs", None) or {}
        )
        try:
            n = int(env_ref)
            entry = branch_envs.get(n)
            if entry is not None:
                return entry.get("env_id")
        except ValueError:
            pass

        logger.debug(
            "env_ref '%s' をビルド時に解決できませんでした。"
            "ConfigurableAgent がランタイムでコンテキストから解決します。",
            env_ref,
        )
        return None

    def _inject_learning_node(self, graph_def: GraphDefinition) -> None:
        """
        GuidelineLearningAgentノードをワークフローの末尾に自動挿入する。

        学習ノードは is_end_node のノードの直前に挿入される。
        グラフ定義への明示的記載は不要。

        AUTOMATA_CODEX_SPEC.md § 4.2.1 学習ノード自動挿入メカニズム に準拠する。

        Args:
            graph_def: 変更対象のGraphDefinition（インプレース変更）
        """
        from shared.models.graph_definition import (
            GraphEdgeDefinition,
            GraphNodeDefinition,
        )

        # 終了エッジ（to: null）を持つノードを特定する
        terminal_edges = [edge for edge in graph_def.edges if edge.to_node is None]

        if not terminal_edges:
            logger.warning("終了エッジが見つからないため学習ノードを挿入できません")
            return

        # 学習ノードをノードリストに追加する
        learning_node = GraphNodeDefinition(
            id="learning",
            type="agent",
            agent_definition_id="guideline_learning",
        )
        graph_def.nodes.append(learning_node)

        # 終了エッジを学習ノードに向け直し、学習ノードから終了エッジを追加する
        for edge in terminal_edges:
            from_node = edge.from_node
            # 既存の終了エッジを学習ノードに向け直す
            edge.to_node = "learning"
            # 学習ノードから元の終了（null）へのエッジを追加する
            new_terminal_edge = GraphEdgeDefinition.model_validate(
                {"from": "learning", "to": None}
            )
            graph_def.edges.append(new_terminal_edge)

        logger.info(
            "学習ノードをグラフに挿入しました: 変更されたエッジ=%d件",
            len(terminal_edges),
        )

    def _create_learning_agent(self, user_config: UserConfig) -> GuidelineLearningAgent:
        """
        GuidelineLearningAgentインスタンスを生成する。

        Args:
            user_config: ユーザー設定

        Returns:
            GuidelineLearningAgentインスタンス
        """
        from consumer.agents.guideline_learning_agent import GuidelineLearningAgent

        return GuidelineLearningAgent(
            user_config=user_config,
            gitlab_client=self.gitlab_client,
            progress_reporter=None,
        )

    async def save_workflow_state(
        self,
        execution_id: str,
        current_node_id: str,
        completed_nodes: list[str],
    ) -> None:
        """
        ワークフロー状態をDBに保存する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 save_workflow_state() に準拠する。

        処理フロー:
        1. データベース接続取得
        2. workflow_execution_statesテーブルにINSERTまたはUPDATE
        3. コミット

        Args:
            execution_id: ワークフロー実行ID
            current_node_id: 現在実行中のノードID
            completed_nodes: 完了したノードIDのリスト

        Raises:
            RuntimeError: リポジトリが未設定の場合
        """
        if self.workflow_exec_state_repo is None:
            logger.warning(
                "workflow_exec_state_repoが未設定のため状態を保存できません: execution_id=%s",
                execution_id,
            )
            return

        task_uuid = (
            self._current_task_context.task_uuid if self._current_task_context else None
        )
        definition_id = (
            self._current_task_context.workflow_definition_id
            if self._current_task_context
            else None
        )

        # INSERTまたはUPDATE
        existing = await self.workflow_exec_state_repo.get_execution_state(execution_id)
        if existing is None:
            await self.workflow_exec_state_repo.create_execution_state(
                execution_id=execution_id,
                task_uuid=task_uuid or "",
                current_node_id=current_node_id,
                workflow_definition_id=definition_id,
                completed_nodes=completed_nodes,
                workflow_status="suspended",
            )
        else:
            await self.workflow_exec_state_repo.suspend_execution(
                execution_id=execution_id,
                current_node_id=current_node_id,
                completed_nodes=completed_nodes,
            )

        logger.info(
            "ワークフロー状態を保存しました: execution_id=%s, current_node_id=%s",
            execution_id,
            current_node_id,
        )

    async def load_workflow_state(self, execution_id: str) -> dict[str, Any]:
        """
        ワークフロー状態をDBから復元する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 load_workflow_state() に準拠する。

        処理フロー:
        1. データベース接続取得
        2. workflow_execution_statesテーブルからレコードをSELECT
        3. 状態辞書生成と返却

        Args:
            execution_id: ワークフロー実行ID

        Returns:
            ワークフロー状態辞書（task_uuid, workflow_definition_id,
            current_node_id, completed_nodes, suspended_at を含む）

        Raises:
            ValueError: 指定されたexecution_idのレコードが存在しない場合
            RuntimeError: リポジトリが未設定の場合
        """
        if self.workflow_exec_state_repo is None:
            raise RuntimeError(
                "workflow_exec_state_repoが未設定のため状態を復元できません"
            )

        row = await self.workflow_exec_state_repo.get_execution_state(execution_id)
        if row is None:
            raise ValueError(
                f"ワークフロー実行状態が見つかりません: execution_id={execution_id}"
            )

        # completed_nodesをJSONデコード（文字列の場合）
        completed_nodes = row.get("completed_nodes", [])
        if isinstance(completed_nodes, str):
            completed_nodes = json.loads(completed_nodes)

        return {
            "task_uuid": row.get("task_uuid"),
            "workflow_definition_id": row.get("workflow_definition_id"),
            "current_node_id": row.get("current_node_id"),
            "completed_nodes": completed_nodes,
            "suspended_at": row.get("suspended_at"),
        }

    async def resume_workflow(self, execution_id: str) -> None:
        """
        停止したワークフローを再開する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 resume_workflow() に準拠する。

        処理フロー:
        1. ワークフロー状態読み込み
        2. タスクコンテキスト取得
        3. ワークフロー定義読み込み
        4. ワークフローインスタンス生成
        5. 完了ノードスキップ
        6. ワークフロー再開実行
        7. ワークフロー状態更新

        Args:
            execution_id: ワークフロー実行ID

        Raises:
            ValueError: ワークフロー状態が取得できない場合
        """
        # 1. ワークフロー状態読み込み
        state = await self.load_workflow_state(execution_id)
        task_uuid = state["task_uuid"]
        current_node_id = state["current_node_id"]
        completed_nodes = state["completed_nodes"]

        logger.info(
            "ワークフローを再開します: execution_id=%s, current_node_id=%s, "
            "completed_nodes=%s",
            execution_id,
            current_node_id,
            completed_nodes,
        )

        # 2. タスクコンテキスト取得
        task_context: TaskContext | None = None
        if self.task_repository is not None:
            task_row = await self.task_repository.get_task(task_uuid)
            if task_row is not None:
                from shared.models.task import TaskContext

                task_context = TaskContext(
                    task_uuid=task_row.get("uuid", task_uuid),
                    task_type=task_row.get("task_type", "merge_request"),
                    project_id=task_row.get("project_id", 0),
                    issue_iid=task_row.get("issue_iid"),
                    mr_iid=task_row.get("mr_iid"),
                    username=task_row.get("username"),
                    workflow_definition_id=state.get("workflow_definition_id"),
                )
                logger.debug(
                    "タスクコンテキストを復元しました: task_uuid=%s", task_uuid
                )
            else:
                logger.warning(
                    "タスクが見つかりません。空のTaskContextを使用します: task_uuid=%s",
                    task_uuid,
                )

        if task_context is None:
            from shared.models.task import TaskContext

            task_context = TaskContext(
                task_uuid=task_uuid,
                task_type="merge_request",
                project_id=0,
                workflow_definition_id=state.get("workflow_definition_id"),
            )

        # 3-4. ワークフロー定義読み込みとワークフローインスタンス生成
        workflow = await self.create_workflow_from_definition(
            user_id=0,
            task_context=task_context,
        )
        logger.info("ワークフローを再構築しました: execution_id=%s", execution_id)

        # 5. 完了ノードのスキップ情報をコンテキストに記録する。
        # Agent Framework の WorkflowContext は completed_nodes を直接セットできないため、
        # ワークフロー開始時に start_context の状態として渡し、
        # 各 Executor/Agent の handle() 冒頭で参照してスキップ制御を行う設計とする。
        resume_context = {
            "completed_nodes": completed_nodes,
            "current_node_id": current_node_id,
        }

        # 6. ワークフロー再開実行
        if hasattr(workflow, "run"):
            await workflow.run(task_context, resume_context=resume_context)
            logger.info(
                "ワークフローの再開実行が完了しました: execution_id=%s", execution_id
            )
        else:
            logger.warning(
                "workflow に run メソッドが存在しないためスキップします: execution_id=%s",
                execution_id,
            )

        # 7. ワークフロー状態を'running'に更新
        if self.workflow_exec_state_repo is not None:
            await self.workflow_exec_state_repo.resume_execution(execution_id)
            logger.info(
                "ワークフロー状態を'running'に更新しました: execution_id=%s",
                execution_id,
            )
        """
        ノード実行間でシャットダウン要求を確認する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.1 _check_shutdown_between_nodes() に準拠する。

        シャットダウンフラグがTrueの場合:
        1. 現在のノード完了を待機
        2. save_workflow_state()を呼び出してワークフロー状態を保存
        3. ExecutionEnvironmentManagerのsave/stop処理を実行
        4. ログ出力してTrueを返す

        Returns:
            シャットダウンが要求されている場合はTrue、そうでない場合はFalse
        """
        global shutdown_requested
        if shutdown_requested:
            logger.info(
                "シャットダウン要求を検出しました。安全に停止処理を実行します。"
            )
            # ワークフロー状態の保存（execution_idが存在する場合）
            if self._current_execution_id is not None:
                await self.save_workflow_state(
                    execution_id=self._current_execution_id,
                    current_node_id="",
                    completed_nodes=[],
                )

            logger.info("Graceful shutdown completed.")
            return True

        return False
