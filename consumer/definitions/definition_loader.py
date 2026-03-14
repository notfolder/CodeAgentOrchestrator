"""
DefinitionLoader モジュール

workflow_definitionsテーブルからグラフ定義・エージェント定義・プロンプト定義をロードし、
それぞれを対応するPythonデータクラスに変換する。

AUTOMATA_CODEX_SPEC.md § 4.4.4（DefinitionLoader）に準拠する。
CLASS_IMPLEMENTATION_SPEC.md の参照ドキュメントに準拠する。
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING, Any

from shared.models.agent_definition import AgentDefinition
from shared.models.graph_definition import GraphDefinition, GraphNodeDefinition
from shared.models.prompt_definition import PromptDefinition

if TYPE_CHECKING:
    from shared.database.repositories.workflow_definition_repository import (
        WorkflowDefinitionRepository,
    )

logger = logging.getLogger(__name__)


class DefinitionValidationError(Exception):
    """ワークフロー定義のバリデーションエラー"""


class DefinitionLoader:
    """
    ワークフロー定義ローダークラス

    workflow_definitionsテーブルからグラフ定義・エージェント定義・プロンプト定義をロードし、
    それぞれを対応するPythonデータクラスに変換する。
    バリデーションメソッドで定義間の整合性を検証する。

    AUTOMATA_CODEX_SPEC.md § 4.4.4 に準拠する。

    Attributes:
        workflow_definition_repo: ワークフロー定義リポジトリ
    """

    def __init__(
        self,
        workflow_definition_repo: WorkflowDefinitionRepository,
    ) -> None:
        """
        DefinitionLoaderを初期化する。

        Args:
            workflow_definition_repo: ワークフロー定義リポジトリ
        """
        self.workflow_definition_repo = workflow_definition_repo

    async def load_workflow_definition(
        self,
        definition_id: int,
    ) -> tuple[GraphDefinition, AgentDefinition, PromptDefinition]:
        """
        指定IDのワークフロー定義をDBから取得し、グラフ・エージェント・プロンプト定義をパースして返す。

        Args:
            definition_id: ワークフロー定義ID

        Returns:
            (GraphDefinition, AgentDefinition, PromptDefinition) のタプル

        Raises:
            ValueError: 指定IDのワークフロー定義が存在しない場合
            DefinitionValidationError: 定義の整合性バリデーションに失敗した場合
        """
        row = await self.workflow_definition_repo.get_workflow_definition(definition_id)
        if row is None:
            raise ValueError(
                f"ワークフロー定義が見つかりません: definition_id={definition_id}"
            )

        graph_def = GraphDefinition.from_dict(row["graph_definition"])
        agent_def = AgentDefinition.from_dict(row["agent_definition"])
        prompt_def = PromptDefinition.from_dict(row["prompt_definition"])

        # バリデーション実行
        self.validate_graph_definition(graph_def)
        self.validate_agent_definition(agent_def, graph_def)
        self.validate_prompt_definition(prompt_def, agent_def)

        return graph_def, agent_def, prompt_def

    async def get_preset_definitions(self) -> list[dict[str, Any]]:
        """
        システムプリセットのワークフロー定義一覧を返す。

        Returns:
            システムプリセット（is_preset=true）のワークフロー定義レコード辞書のリスト
        """
        return await self.workflow_definition_repo.list_workflow_definitions(
            is_preset=True,
            is_active=True,
        )

    def validate_graph_definition(self, graph_def: GraphDefinition) -> bool:
        """
        グラフ定義の構造的整合性を検証する。

        以下のチェックを実施する:
        1. 必須フィールドの存在確認
        2. エントリノードの存在確認
        3. エッジの参照整合性チェック
        4. 孤立ノードのチェック（BFS）
        5. 終了ノード（to: null）の存在確認
        6. 条件式の構文チェック
        7. env_refバリデーション

        Args:
            graph_def: 検証対象のGraphDefinition

        Returns:
            検証成功時はTrue

        Raises:
            DefinitionValidationError: 検証失敗時
        """
        node_ids = {node.id for node in graph_def.nodes}

        # 1. エントリノードの存在確認
        if graph_def.entry_node not in node_ids:
            raise DefinitionValidationError(
                f"entry_node '{graph_def.entry_node}' がnodesに存在しません"
            )

        # 3. エッジの参照整合性チェック
        for edge in graph_def.edges:
            if edge.from_node not in node_ids:
                raise DefinitionValidationError(
                    f"エッジのfrom_node '{edge.from_node}' がnodesに存在しません"
                )
            if edge.to_node is not None and edge.to_node not in node_ids:
                raise DefinitionValidationError(
                    f"エッジのto_node '{edge.to_node}' がnodesに存在しません"
                )

        # 4. 孤立ノードのチェック（BFS）
        reachable: set[str] = set()
        queue: deque[str] = deque([graph_def.entry_node])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in graph_def.edges:
                if edge.from_node == current and edge.to_node is not None:
                    queue.append(edge.to_node)

        unreachable = node_ids - reachable
        if unreachable:
            raise DefinitionValidationError(
                f"到達不能なノードが存在します: {unreachable}"
            )

        # 5. 終了ノードの存在確認（to: null のエッジが少なくとも1つ必要）
        has_terminal_edge = any(edge.to_node is None for edge in graph_def.edges)
        if not has_terminal_edge:
            raise DefinitionValidationError(
                "グラフに終了エッジ（to: null）が存在しません。ワークフローが正常終了できません"
            )

        # 6. 条件式の構文チェック
        for edge in graph_def.edges:
            if edge.condition is not None:
                try:
                    compile(edge.condition, "<string>", "eval")
                except SyntaxError as exc:
                    raise DefinitionValidationError(
                        f"エッジの条件式 '{edge.condition}' の構文が不正です: {exc}"
                    ) from exc

        # 7. env_refバリデーション
        self._validate_env_refs(graph_def)

        return True

    def _validate_env_refs(self, graph_def: GraphDefinition) -> None:
        """
        グラフ定義内の env_ref と env_count の整合性を検証する。

        Args:
            graph_def: 検証対象のGraphDefinition

        Raises:
            DefinitionValidationError: env_refのバリデーション失敗時
        """
        for node in graph_def.nodes:
            env_ref = node.env_ref
            if env_ref is not None:
                # "plan" または正の整数文字列のみ許可
                if env_ref != "plan":
                    try:
                        num = int(env_ref)
                        if num < 1:
                            raise DefinitionValidationError(
                                f"ノード '{node.id}' のenv_ref '{env_ref}' は"
                                "1以上の整数文字列である必要があります"
                            )
                    except ValueError:
                        raise DefinitionValidationError(
                            f"ノード '{node.id}' のenv_ref '{env_ref}' は"
                            "'plan' または整数文字列である必要があります"
                        )

            # ExecEnvSetupExecutorはenv_countが必須
            if node.executor_class == "ExecEnvSetupExecutor":
                if node.env_count is None:
                    raise DefinitionValidationError(
                        f"ExecEnvSetupExecutorノード '{node.id}' はenv_countが必須です"
                    )

    def validate_agent_definition(
        self,
        agent_def: AgentDefinition,
        graph_def: GraphDefinition,
    ) -> bool:
        """
        エージェント定義がグラフ定義と整合しているか検証する。

        以下のチェックを実施する:
        1. 必須フィールドの存在確認
        2. グラフ定義との整合性（agent_definition_idが対応するエージェント定義が存在するか）
        3. roleの有効値チェック
        4. mcp_serversの有効値チェック
        5. input_keysとoutput_keysの一貫性
        6. mcp_serversとroleの整合性（env_refチェック）

        Args:
            agent_def: 検証対象のAgentDefinition
            graph_def: 整合性チェック先のGraphDefinition

        Returns:
            検証成功時はTrue

        Raises:
            DefinitionValidationError: 検証失敗時
        """
        valid_roles = {"planning", "reflection", "execution", "review"}
        agent_ids = {agent.id for agent in agent_def.agents}

        # 2. グラフ定義との整合性チェック
        for node in graph_def.nodes:
            if node.type == "agent":
                if node.agent_definition_id is None:
                    raise DefinitionValidationError(
                        f"agentノード '{node.id}' にagent_definition_idが指定されていません"
                    )
                if node.agent_definition_id not in agent_ids:
                    raise DefinitionValidationError(
                        f"ノード '{node.id}' が参照するagent_definition_id"
                        f" '{node.agent_definition_id}' がエージェント定義に存在しません"
                    )

        # 各エージェントのバリデーション
        for agent in agent_def.agents:
            # 3. roleの有効値チェック
            if agent.role not in valid_roles:
                raise DefinitionValidationError(
                    f"エージェント '{agent.id}' のrole '{agent.role}' が不正です。"
                    f"有効値: {valid_roles}"
                )

            # 5. input_keysとoutput_keysの一貫性チェック
            common_keys = set(agent.input_keys) & set(agent.output_keys)
            if common_keys:
                raise DefinitionValidationError(
                    f"エージェント '{agent.id}' のinput_keysとoutput_keysに"
                    f"重複するキーがあります: {common_keys}"
                )

            # 7. mcp_serversとroleの整合性（env_refチェック）
            env_ref = agent.env_ref
            if agent.role == "planning":
                # planningはenv_ref: "plan"または省略のみ許容
                if env_ref is not None and env_ref != "plan":
                    raise DefinitionValidationError(
                        f"planningエージェント '{agent.id}' のenv_refは"
                        f"'plan'または省略のみ許容されます（現在: '{env_ref}'）"
                    )
            elif agent.role in {"execution", "review"}:
                # execution/reviewはenv_ref: 1以上の整数文字列が必要
                if env_ref is not None:
                    try:
                        num = int(env_ref)
                        if num < 1:
                            raise DefinitionValidationError(
                                f"'{agent.role}'エージェント '{agent.id}' のenv_refは"
                                "1以上の整数文字列である必要があります"
                            )
                    except ValueError:
                        if env_ref != "plan":
                            raise DefinitionValidationError(
                                f"'{agent.role}'エージェント '{agent.id}' のenv_refが"
                                f"不正です: '{env_ref}'"
                            )

        return True

    def validate_prompt_definition(
        self,
        prompt_def: PromptDefinition,
        agent_def: AgentDefinition,
    ) -> bool:
        """
        プロンプト定義がエージェント定義と整合しているか検証する。

        以下のチェックを実施する:
        1. 必須フィールドの存在確認
        2. prompt_idの整合性（エージェントのprompt_idに対応するプロンプトが存在するか）
        3. roleの一致チェック
        4. プレースホルダーの妥当性チェック
        5. 未使用プロンプトの警告

        Args:
            prompt_def: 検証対象のPromptDefinition
            agent_def: 整合性チェック先のAgentDefinition

        Returns:
            検証成功時はTrue

        Raises:
            DefinitionValidationError: 検証失敗時
        """
        prompt_ids = {prompt.id for prompt in prompt_def.prompts}
        used_prompt_ids: set[str] = set()

        for agent in agent_def.agents:
            # 2. prompt_idの整合性チェック
            if agent.prompt_id not in prompt_ids:
                raise DefinitionValidationError(
                    f"エージェント '{agent.id}' が参照するprompt_id '{agent.prompt_id}'"
                    "がプロンプト定義に存在しません"
                )
            used_prompt_ids.add(agent.prompt_id)

            # 3. roleの一致チェック（プロンプト定義にはroleがない場合があるためスキップ）
            prompt_config = prompt_def.get_prompt(agent.prompt_id)
            if prompt_config is not None:
                # 4. プレースホルダーの妥当性チェック
                # system_prompt内の{key}形式のプレースホルダーを検出
                import re

                placeholders = set(re.findall(r"\{(\w+)\}", prompt_config.system_prompt))
                # input_keysにない未定義プレースホルダーを検出（警告のみ）
                undefined = placeholders - set(agent.input_keys)
                # 特殊プレースホルダーは除外（issue_title等のシステム組み込み変数）
                common_system_vars = {
                    "issue_title",
                    "mr_title",
                    "task_description",
                    "task_iid",
                }
                undefined -= common_system_vars
                if undefined:
                    logger.warning(
                        "エージェント '%s' のプロンプトに未定義のプレースホルダーがあります: %s",
                        agent.id,
                        undefined,
                    )

        # 5. 未使用プロンプトの警告
        unused = prompt_ids - used_prompt_ids
        if unused:
            logger.warning(
                "プロンプト定義に未使用のプロンプトがあります: %s",
                unused,
            )

        return True

    def load_graph_definition_from_dict(
        self, data: dict[str, Any]
    ) -> GraphDefinition:
        """
        辞書からGraphDefinitionを生成する。

        Args:
            data: グラフ定義の辞書

        Returns:
            GraphDefinitionインスタンス
        """
        return GraphDefinition.from_dict(data)

    def load_agent_definition_from_dict(
        self, data: dict[str, Any]
    ) -> AgentDefinition:
        """
        辞書からAgentDefinitionを生成する。

        Args:
            data: エージェント定義の辞書

        Returns:
            AgentDefinitionインスタンス
        """
        return AgentDefinition.from_dict(data)

    def load_prompt_definition_from_dict(
        self, data: dict[str, Any]
    ) -> PromptDefinition:
        """
        辞書からPromptDefinitionを生成する。

        Args:
            data: プロンプト定義の辞書

        Returns:
            PromptDefinitionインスタンス
        """
        return PromptDefinition.from_dict(data)
