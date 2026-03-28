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

# OpenAI Responses API (/v1/responses) 専用モデルのセット。
# これらのモデルは Chat Completions API (/v1/chat/completions) をサポートしないため、
# OpenAIResponsesClient を使用する必要がある。
# 参照: https://platform.openai.com/docs/models
_RESPONSES_ONLY_MODELS: frozenset[str] = frozenset(
    [
        "codex-mini-latest",
        "gpt-5-codex",
        "gpt-5.1-codex",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini",
    ]
)


class AgentFactory:
    """
    エージェントファクトリクラス

    ConfigurableAgentインスタンスを生成する。エージェント定義とプロンプト定義を受け取り、
    username・env_idを設定した上でConfigurableAgentを生成する。
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
        db_connection: Any = None,
        gitlab_client: Any = None,
        openai_base_url: str = "https://api.openai.com/v1",
    ) -> None:
        """
        AgentFactoryを初期化する。

        Args:
            mcp_server_configs: MCPサーバー設定辞書（サーバー名→MCPServerConfig）
            chat_history_provider: チャット履歴Providerインスタンス
            planning_context_provider: プランニングコンテキストProviderインスタンス
            tool_result_context_provider: ツール結果コンテキストProviderインスタンス
            user_config_client: ユーザー設定クライアント
            db_connection: データベース接続プール（TodoManagementTool用）
            gitlab_client: GitLabクライアント（TodoManagementTool用）
            openai_base_url: OpenAI APIのベースURL。OPENAI_BASE_URL環境変数で指定可能。
                             provider=openaiかつuser_config.base_urlがNoneの場合のフォールバック。
        """
        self.mcp_server_configs = mcp_server_configs
        self.chat_history_provider = chat_history_provider
        self.planning_context_provider = planning_context_provider
        self.tool_result_context_provider = tool_result_context_provider
        self.user_config_client = user_config_client
        self.db_connection = db_connection
        self.gitlab_client = gitlab_client
        self.openai_base_url = openai_base_url

    async def create_agent(
        self,
        agent_config: AgentNodeConfig,
        prompt_config: PromptConfig,
        username: str,
        progress_reporter: Any,
        env_id: str | None = None,
        user_config: Any | None = None,
        task_uuid: str = "",
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
            username: GitLabユーザー名
            progress_reporter: 進捗報告インスタンス
            env_id: 使用するDocker環境ID（省略可能）
            user_config: キャッシュ済みユーザー設定（省略時はHTTP取得）
            task_uuid: タスクUUID（TodoManagementTool用）

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
                todo_tools = self._create_todo_tools(
                    task_uuid=task_uuid,
                    progress_reporter=progress_reporter,
                )
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

        # 3. User Config取得（キャッシュがあれば再利用）
        if user_config is None:
            user_config = await self.user_config_client.get_user_config(username)

        # 4. ChatClient生成（Agent Framework の OpenAIChatClient / AzureOpenAIChatClient を使用）
        chat_client = self.create_chat_client(user_config)

        # 5. システムプロンプト構築
        system_prompt = self._build_system_prompt(prompt_config.system_prompt)

        # 6. Agent生成（Agent Framework の Agent を使用）
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
            "ConfigurableAgentを生成しました: agent_id=%s, username=%s, env_id=%s",
            agent_config.id,
            username,
            env_id,
        )
        return configurable_agent

    def _create_todo_tools(
        self,
        task_uuid: str = "",
        progress_reporter: Any = None,
    ) -> list[Any]:
        """
        TodoManagementToolのFunctionTool群を生成して返す。

        LLMが直接扱えるよう、project_id/mr_iid/contextをラップして隠蔽し、
        todos引数のスキーマをTodoItem TypedDictで明確に定義したクロージャ関数を
        FunctionToolとして登録する。

        Agent FrameworkのFunctionToolとしてラップして返す。

        Args:
            task_uuid: タスクUUID
            progress_reporter: 進捗報告インスタンス

        Returns:
            FunctionToolのリスト
        """
        try:
            from agent_framework import FunctionTool

            from consumer.tools.todo_management_tool import TodoItem, TodoManagementTool

            todo_tool = TodoManagementTool(
                db_connection=self.db_connection,
                gitlab_client=self.gitlab_client,
                task_uuid=task_uuid,
                progress_reporter=progress_reporter,
            )

            # --- LLM向けラッパー関数群 ---
            # project_id / mr_iid / context は LLM に渡させると問題が起きるため隠蔽する。
            # todos の型を TodoItem TypedDict にすることで JSON スキーマを明確にする。
            # 注意: from __future__ import annotations によりアノテーションが文字列化されるため、
            #       __annotations__ を直接型オブジェクトで上書きして解決回避する。

            async def create_todo_list(todos: Any) -> dict[str, Any]:
                """
                作業手順（Todoリスト）をデータベースに一括登録する。

                タスク開始時に全工程を一度にまとめて登録するために使う。

                Args:
                    todos: 登録するTodo項目のリスト。
                           各要素は以下のキーを持つオブジェクト:
                           - title (str, 必須): Todoのタイトル
                           - description (str, 省略可): Todoの説明
                           - status (str, 省略可): 初期ステータス
                             （not-started / in-progress / completed のいずれか。省略時は not-started）

                Returns:
                    {"status": "success", "todo_ids": [登録されたTodoのIDリスト]}
                """
                todos_dicts: list[dict[str, Any]] = [dict(t) for t in todos]
                return await todo_tool.create_todo_list(
                    project_id=0,
                    mr_iid=0,
                    todos=todos_dicts,
                    context=None,
                )

            # TodoItem を型オブジェクトとして直接セットし、文字列評価を回避する
            create_todo_list.__annotations__ = {
                "todos": list[TodoItem],
                "return": dict[str, Any],
            }

            async def get_todo_list() -> dict[str, Any]:
                """
                現在のTodoリストをデータベースから取得する。

                Returns:
                    {"status": "success", "todos": [Todoオブジェクトのリスト]}
                    各Todoオブジェクト: {id, title, description, status, parent_todo_id, order_index}
                """
                return await todo_tool.get_todo_list(project_id=0, mr_iid=0)

            get_todo_list.__annotations__ = {"return": dict[str, Any]}

            async def update_todo_status(todo_id: int, status: str) -> dict[str, Any]:
                """
                TodoのステータスをID指定で更新する。

                Args:
                    todo_id: 更新対象のTodo ID（get_todo_listで取得したid）
                    status: 新しいステータス
                            not-started / in-progress / completed / failed のいずれか

                Returns:
                    {"status": "success", "todo_id": todo_id, "new_status": status}
                """
                return await todo_tool.update_todo_status(
                    todo_id=todo_id,
                    status=status,
                    context=None,
                )

            update_todo_status.__annotations__ = {
                "todo_id": int,
                "status": str,
                "return": dict[str, Any],
            }

            tools: list[Any] = []
            for func in [create_todo_list, get_todo_list, update_todo_status]:
                ft = FunctionTool(
                    name=func.__name__,
                    description=func.__doc__ or func.__name__,
                    func=func,
                )
                tools.append(ft)
            return tools
        except Exception as exc:
            logger.warning("TodoManagementToolの生成に失敗しました: %s", exc)
            return []

    def create_chat_client(self, user_config: Any) -> Any:
        """
        ユーザー設定に基づいてChatClientを生成する。

        user_config.llm_provider が "azure" の場合は AzureOpenAIChatClient を、
        それ以外（openai/ollama/lmstudio）の場合はモデル名に応じて
        OpenAIChatClient または OpenAIResponsesClient を生成する。

        モデルが _RESPONSES_ONLY_MODELS に含まれる場合は OpenAIResponsesClient を使用する。
        これらのモデルは Chat Completions API をサポートせず、Responses API 専用である。
        それ以外のモデルは OpenAIChatClient（Chat Completions API）を使用する。

        ユーザーの api_key が空の場合、環境変数 OPENAI_API_KEY が使用される。

        Args:
            user_config: UserConfigインスタンス

        Returns:
            BaseChatClientインスタンス
        """
        provider: str = getattr(user_config, "llm_provider", "openai")
        model_name: str = getattr(user_config, "model_name", "gpt-4o")
        api_key: str = getattr(user_config, "api_key", "")
        base_url: str | None = getattr(user_config, "base_url", None)

        logger.debug(
            "ChatClientを生成します: provider=%s, model=%s",
            provider,
            model_name,
        )

        if provider == "azure":
            from agent_framework.azure import AzureOpenAIChatClient

            # Azure OpenAI: api_keyとbase_urlはUserConfigから取得する
            return AzureOpenAIChatClient(
                api_key=api_key or None,
                endpoint=base_url or None,
                deployment_name=model_name,
            )
        else:
            # OpenAI互換（openai/ollama/lmstudio）: base_urlにOpenAI互換エンドポイントを指定
            # provider=openaiかつuser_configにbase_urlが未設定の場合はシステム設定のopenai_base_urlをフォールバックとして使用する
            effective_base_url: str | None = base_url
            if effective_base_url is None and provider == "openai":
                effective_base_url = self.openai_base_url

            # Responses API 専用モデルの場合は OpenAIResponsesClient を使用する
            if model_name in _RESPONSES_ONLY_MODELS:
                from agent_framework.openai import OpenAIResponsesClient

                logger.info(
                    "Responses API 専用モデルのため OpenAIResponsesClient を使用します: model=%s",
                    model_name,
                )
                return OpenAIResponsesClient(
                    api_key=api_key or None,
                    model_id=model_name,
                    base_url=effective_base_url or None,
                )

            from agent_framework.openai import OpenAIChatClient

            return OpenAIChatClient(
                api_key=api_key or None,
                model_id=model_name,
                base_url=effective_base_url or None,
            )

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
        Agent Frameworkのエージェントインスタンスを生成する。

        chat_client に基づいて Agent を生成する。
        chat_client が None の場合はスキップして None を返す。

        Args:
            chat_client: BaseChatClientインスタンス
            system_prompt: システムプロンプト文字列
            tool_list: ツールリスト（MCPStdioTool / FunctionTool 等）

        Returns:
            Agent インスタンス。chat_client が None の場合は None。
        """
        if chat_client is None:
            logger.warning(
                "chat_clientが未設定のためAgentインスタンスをスキップします。"
                " LLM API キーが設定されているか確認してください。"
            )
            return None

        from agent_framework import Agent

        return Agent(
            client=chat_client,
            instructions=system_prompt or None,
            tools=tool_list or None,
        )
