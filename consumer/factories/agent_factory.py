"""
AgentFactory モジュール

ConfigurableAgentインスタンスを生成するファクトリクラスを提供する。
User Config APIからユーザーのLLM設定を取得してエージェントに適用する。

CLASS_IMPLEMENTATION_SPEC.md § 2.3（AgentFactory）に準拠する。
AUTOMATA_CODEX_SPEC.md § 4.2（AgentFactory）に準拠する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from consumer.agents.configurable_agent import ConfigurableAgent
    from consumer.user_config_client import UserConfigClient
    from shared.config.models import MCPServerConfig
    from shared.models.agent_definition import AgentNodeConfig
    from shared.models.prompt_definition import PromptConfig

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    エージェントファクトリクラス

    ConfigurableAgentインスタンスを生成する。エージェント定義とプロンプト定義を受け取り、
    user_email・env_idを設定した上でConfigurableAgentを生成する。
    User Config APIからユーザーのLLM設定を取得してエージェントに適用する。

    CLASS_IMPLEMENTATION_SPEC.md § 2.3 に準拠する。

    Attributes:
        mcp_server_configs: MCPサーバー設定辞書（サーバー名→MCPServerConfig）
        chat_history_provider: チャット履歴Providerインスタンス
        planning_context_provider: プランニングコンテキストProviderインスタンス
        tool_result_context_provider: ツール結果コンテキストProviderインスタンス
        user_config_client: ユーザー設定クライアント
    """

    def __init__(
        self,
        mcp_server_configs: dict[str, MCPServerConfig],
        chat_history_provider: Any,
        planning_context_provider: Any,
        tool_result_context_provider: Any,
        user_config_client: UserConfigClient,
    ) -> None:
        """
        AgentFactoryを初期化する。

        Args:
            mcp_server_configs: MCPサーバー設定辞書（サーバー名→MCPServerConfig）
            chat_history_provider: チャット履歴Providerインスタンス
            planning_context_provider: プランニングコンテキストProviderインスタンス
            tool_result_context_provider: ツール結果コンテキストProviderインスタンス
            user_config_client: ユーザー設定クライアント
        """
        self.mcp_server_configs = mcp_server_configs
        self.chat_history_provider = chat_history_provider
        self.planning_context_provider = planning_context_provider
        self.tool_result_context_provider = tool_result_context_provider
        self.user_config_client = user_config_client

    async def create_agent(
        self,
        agent_config: AgentNodeConfig,
        prompt_config: PromptConfig,
        user_email: str,
        progress_reporter: Any,
        env_id: str | None = None,
    ) -> ConfigurableAgent:
        """
        ConfigurableAgentインスタンスを生成して返す。

        CLASS_IMPLEMENTATION_SPEC.md § 2.3.3 に準拠する。

        処理フロー:
        1. ツールリスト構築とMCPClientFactory新規生成
        2. ツールリスト構築（todo_listは仮想MCPサーバーとして処理）
        3. User Config取得
        4. ChatClient生成
        5. システムプロンプト構築
        6. Agent生成
        7. ConfigurableAgentインスタンス生成
        8. ConfigurableAgent返却

        Args:
            agent_config: エージェントノード設定
            prompt_config: プロンプト設定
            user_email: ユーザーのメールアドレス
            progress_reporter: 進捗報告インスタンス
            env_id: 使用するDocker環境ID（省略可能）

        Returns:
            ConfigurableAgentインスタンス
        """
        from consumer.agents.configurable_agent import ConfigurableAgent
        from consumer.mcp.mcp_client_factory import MCPClientFactory

        # 1. MCPClientFactory新規生成（エージェント専用）
        # server_configsはMCPServerConfigオブジェクトのリストとして渡す
        mcp_client_factory = MCPClientFactory(
            server_configs=list(self.mcp_server_configs.values()),
        )

        # 2. ツールリスト構築
        tool_list: list[Any] = []
        for server_name in agent_config.mcp_servers:
            if server_name == "todo_list":
                # 仮想MCPサーバー: TodoManagementToolのFunctionTool群を追加
                todo_tools = self._create_todo_tools()
                tool_list.extend(todo_tools)
            else:
                # 実MCPサーバー: MCPStdioToolを生成して追加
                if env_id is not None:
                    mcp_tool = mcp_client_factory.create_mcp_tool(
                        server_name=server_name,
                        env_id=env_id,
                    )
                    tool_list.append(mcp_tool)
                else:
                    logger.warning(
                        "env_idが未設定のためMCPツール '%s' をスキップします: agent=%s",
                        server_name,
                        agent_config.id,
                    )

        # 3. User Config取得
        user_config = await self.user_config_client.get_user_config(user_email)

        # 4. ChatClient生成（スタブ: 実際のAgent Framework統合時に実装）
        chat_client = self._create_chat_client(user_config)

        # 5. システムプロンプト構築
        system_prompt = self._build_system_prompt(prompt_config.system_prompt)

        # 6. Agent生成（スタブ）
        agent = self._create_agent_instance(
            chat_client=chat_client,
            system_prompt=system_prompt,
            tool_list=tool_list,
        )

        # 7. ConfigurableAgentインスタンス生成
        configurable_agent = ConfigurableAgent(
            config=agent_config,
            agent=agent,
            prompt_content=system_prompt,
            progress_reporter=progress_reporter,
            environment_id=env_id,
            tools=tool_list,
        )

        logger.info(
            "ConfigurableAgentを生成しました: agent_id=%s, user_email=%s, env_id=%s",
            agent_config.id,
            user_email,
            env_id,
        )
        return configurable_agent

    def _create_todo_tools(self) -> list[Any]:
        """
        TodoManagementToolのFunctionTool群を生成して返す。

        Returns:
            FunctionToolのリスト
        """
        try:
            from consumer.tools.todo_management_tool import TodoManagementTool

            todo_tool = TodoManagementTool()
            # FunctionToolとして登録可能な関数群を返す
            return [
                todo_tool.create_todo_list,
                todo_tool.get_todo_list,
                todo_tool.update_todo_status,
            ]
        except Exception as exc:
            logger.warning(
                "TodoManagementToolの生成に失敗しました: %s", exc
            )
            return []

    def _create_chat_client(self, user_config: Any) -> Any:
        """
        ユーザー設定に基づいてChatClientを生成する（スタブ）。

        Agent Framework統合後に OpenAIChatClient/AzureOpenAIChatClient を
        適切に生成する実装に置き換える。

        Args:
            user_config: UserConfigインスタンス

        Returns:
            ChatClientインスタンス（スタブ）
        """
        logger.debug(
            "ChatClientを生成します: provider=%s, model=%s",
            getattr(user_config, "llm_provider", "openai"),
            getattr(user_config, "model_name", "gpt-4o"),
        )
        # スタブ実装: 将来的にAgent Framework統合で実際のChatClientを返す
        return None

    def _build_system_prompt(self, prompt_content: str) -> str:
        """
        システムプロンプトを構築する。

        プロンプト冒頭にAGENTS.mdとPROJECT_GUIDELINES.mdを含め、
        その後にprompt_config.contentを連結する。

        CLASS_IMPLEMENTATION_SPEC.md § 2.3.3 ステップ5 に準拠する。

        Args:
            prompt_content: プロンプト定義のシステムプロンプト

        Returns:
            構築されたシステムプロンプト文字列
        """
        parts: list[str] = []

        # AGENTS.md を読み込む（存在する場合）
        agents_md = self._read_repository_file("AGENTS.md")
        if agents_md:
            parts.append(agents_md)

        # PROJECT_GUIDELINES.md を読み込む（存在する場合）
        guidelines_md = self._read_repository_file("PROJECT_GUIDELINES.md")
        if guidelines_md:
            parts.append(guidelines_md)

        # プロンプト定義のシステムプロンプトを追加
        if prompt_content:
            parts.append(prompt_content)

        return "\n\n".join(parts)

    def _read_repository_file(self, filename: str) -> str | None:
        """
        リポジトリのルートからファイルを読み込む。

        Args:
            filename: ファイル名

        Returns:
            ファイル内容（存在しない場合はNone）
        """
        import os

        # ワークディレクトリからファイルを検索する
        for search_path in [".", "/workspace", os.getcwd()]:
            filepath = os.path.join(search_path, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, encoding="utf-8") as f:
                        content = f.read()
                    logger.debug("リポジトリファイルを読み込みました: %s", filepath)
                    return content
                except OSError as exc:
                    logger.warning(
                        "リポジトリファイルの読み込みに失敗しました: %s - %s",
                        filepath,
                        exc,
                    )

        return None

    def _create_agent_instance(
        self,
        chat_client: Any,
        system_prompt: str,
        tool_list: list[Any],
    ) -> Any:
        """
        Agent Frameworkのエージェントインスタンスを生成する（スタブ）。

        Agent Framework統合後に実際のAgentインスタンスを生成する実装に置き換える。

        Args:
            chat_client: ChatClientインスタンス
            system_prompt: システムプロンプト文字列
            tool_list: ツールリスト

        Returns:
            Agentインスタンス（スタブ）
        """
        # スタブ実装: 将来的にAgent Framework統合で実際のAgentを返す
        return None
