"""
ConfigurableAgent モジュール

グラフ内のすべてのエージェントノードを実装する汎用エージェントクラスを提供する。
エージェント定義ファイルの AgentNodeConfig に基づいて動作し、
planning / reflection / execution / review の各ロールに対応する。

CLASS_IMPLEMENTATION_SPEC.md § 1（ConfigurableAgent）に準拠する。
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import Executor, WorkflowContext, handler

from shared.models.agent_definition import AgentNodeConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ConfigurableAgent 本体
# ---------------------------------------------------------------------------


class ConfigurableAgent(Executor):
    """
    汎用エージェントクラス

    AgentNodeConfig の設定に基づいて動作する単一クラス。
    グラフ内のすべてのエージェントノード（planning / reflection /
    execution / review）を本クラス一つで実装する。

    CLASS_IMPLEMENTATION_SPEC.md § 1 に準拠する。

    Attributes:
        config: エージェントノード設定
        agent: LLM エージェントインスタンス（Agent Framework 統合用）
        tools: エージェントが使用するツールリスト（MCPStdioTool / FunctionTool の結合リスト）
        prompt_content: プロンプト定義のシステムプロンプト文字列
        progress_reporter: 進捗報告インスタンス
        environment_id: ビルド時に確定した Docker 環境 ID（省略可能）
    """

    def __init__(
        self,
        config: AgentNodeConfig,
        agent: Any,
        prompt_content: str,
        progress_reporter: Any,
        environment_id: str | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        """
        ConfigurableAgent を初期化する。

        Args:
            config: AgentNodeConfig インスタンス
            agent: LLM エージェント（Any 型、将来の Agent Framework 統合用）
            prompt_content: プロンプト定義のシステムプロンプト文字列
            progress_reporter: ProgressReporter インスタンス（Any 型）
            environment_id: Docker 環境 ID（省略可能）
            tools: エージェントが使用するツールリスト（MCPStdioTool / FunctionTool 等、省略時は空リスト）
        """
        self.config: AgentNodeConfig = config
        self.agent: Any = agent
        # §1.3 保持データ: mcp_serversの各サーバーを解決して生成したMCPStdioTool / FunctionToolの結合リスト
        self.tools: list[Any] = tools if tools is not None else []
        self.prompt_content: str = prompt_content
        self.progress_reporter: Any = progress_reporter
        self.environment_id: str | None = environment_id
        super().__init__(id=config.node_id or config.id)

    @handler(input=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext) -> dict[str, Any]:
        """
        エージェントノードのメインハンドラ。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 の処理フロー（12 ステップ）に準拠する。

        処理フロー:
            1. タスク MR/Issue IID 取得
            2. 入力データ取得
            3. 進捗報告（開始）
            4. プロンプト生成
            5. Agent.run() 呼び出し
            6. LLM 応答取得
            7. 進捗報告（LLM 応答）
            8. ツール呼び出し処理（Agent Framework が自動管理）
            9. ロール別後処理
            10. 進捗報告（完了）
            11. 出力データ保存
            12. output_data を返す

        Args:
            msg: 受け取るメッセージ
            ctx: ワークフローコンテキスト

        Returns:
            output_keys に対応する出力データ辞書

        Raises:
            Exception: 処理中に発生した例外（progress_reporter に通知後に再送出）
        """
        output_data: dict[str, Any] = {}

        try:
            # ステップ 1: タスク MR/Issue IID 取得
            task_iid: Any = ctx.get_state("task_mr_iid") or ctx.get_state(
                "task_issue_iid"
            )

            # ステップ 2: 入力データ取得
            input_data: dict[str, Any] = {
                key: ctx.get_state(key) for key in self.config.input_keys
            }

            # ステップ 3: 進捗報告（開始）
            await self.report_progress(task_iid=task_iid, event="start", details={})

            # ステップ 4: プロンプト生成
            # input_data の各キーを {key} プレースホルダーとして置換する
            prompt: str = self.prompt_content
            for key, value in input_data.items():
                prompt = prompt.replace(
                    f"{{{key}}}", str(value) if value is not None else ""
                )

            # ステップ 5: Agent.run() 呼び出し
            response: Any
            if hasattr(self.agent, "run"):
                response = await self.agent.run([{"role": "user", "content": prompt}])
            else:
                response = None

            # ステップ 6: LLM 応答取得
            response_text: str
            if isinstance(response, str):
                response_text = response
            elif isinstance(response, dict):
                response_text = response.get("content", "")
            else:
                response_text = ""

            # ステップ 7: 進捗報告（LLM 応答）
            response_summary: str = response_text[:200]
            await self.report_progress(
                task_iid=task_iid,
                event="llm_response",
                details={"summary": response_summary},
            )

            # ステップ 8: ツール呼び出し処理
            # Agent Framework が MCPStdioTool を自動的に呼び出すため、明示的な実装は不要。
            # tool_choice="auto" の設定により LLM がツール呼び出しを判断して自動実行し、
            # フィードバックループはフレームワークが管理する。

            # ステップ 9: ロール別後処理
            await self._handle_role_specific(self.config.role, response_text, ctx)

            # ステップ 10: 進捗報告（完了）
            await self.report_progress(
                task_iid=task_iid, event="complete", details=output_data
            )

            # ステップ 11: 出力データ保存
            # response_text から出力を抽出し、output_keys に対して ctx.set_state() を呼び出す
            for key in self.config.output_keys:
                output_data[key] = response_text
                ctx.set_state(key, response_text)

        except Exception as exc:
            # エラー発生時は progress_reporter に通知してから再送出する
            logger.exception(
                "エージェントノード '%s' の処理中にエラーが発生しました。",
                self.config.id,
            )
            try:
                await self.report_progress(
                    task_iid=None,
                    event="error",
                    details={"error": str(exc)},
                )
            except Exception:
                logger.exception("エラー進捗報告中に追加エラーが発生しました。")
            raise

        # ステップ 12: output_data を返す
        return output_data

    async def _handle_role_specific(
        self, role: str, response_text: str, ctx: WorkflowContext
    ) -> None:
        """
        ロール別後処理を実行する。

        各ロールに応じたログを出力する。
        将来的には planning でのTodoリスト作成、reflection での改善判定、
        execution でのファイル操作確認・git操作、review でのレビューコメント生成
        を実装する。

        Args:
            role: エージェントロール（planning / reflection / execution / review）
            response_text: LLM の応答テキスト
            ctx: ワークフローコンテキスト
        """
        if role == "planning":
            logger.info("プランニング完了: ノード '%s'", self.config.id)
        elif role == "reflection":
            logger.info("リフレクション完了: ノード '%s'", self.config.id)
        elif role == "execution":
            logger.info("実行完了: ノード '%s'", self.config.id)
        elif role == "review":
            logger.info("レビュー完了: ノード '%s'", self.config.id)
        else:
            logger.warning(
                "未知のロール '%s' が指定されました: ノード '%s'",
                role,
                self.config.id,
            )

    async def get_chat_history(self, session_id: str) -> list[dict[str, Any]]:
        """
        チャット履歴を取得する。

        progress_reporter.chat_history_provider または agent.history_provider の
        get_messages() を呼び出してメッセージ一覧を返す。
        いずれも存在しない場合は空リストを返す。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 に準拠する。

        Args:
            session_id: チャットセッション ID

        Returns:
            メッセージ辞書のリスト。取得できない場合は空リスト。
        """
        # progress_reporter.chat_history_provider を優先して確認する
        history_provider: Any = getattr(
            self.progress_reporter, "chat_history_provider", None
        )

        # 存在しない場合は agent.history_provider を確認する
        if history_provider is None:
            history_provider = getattr(self.agent, "history_provider", None)

        if history_provider is not None and hasattr(history_provider, "get_messages"):
            messages: list[dict[str, Any]] = await history_provider.get_messages(
                session_id
            )
            return messages

        logger.debug(
            "チャット履歴プロバイダが見つかりません: session_id='%s'", session_id
        )
        return []

    async def get_context(
        self, keys: list[str], ctx: WorkflowContext
    ) -> dict[str, Any]:
        """
        指定キーのコンテキスト値を取得する。

        keys をループして ctx.get_state() を呼び出し、辞書にまとめて返す。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 に準拠する。

        Args:
            keys: 取得するキー名のリスト
            ctx: ワークフローコンテキスト

        Returns:
            キーと値のペアからなる辞書
        """
        return {key: ctx.get_state(key) for key in keys}

    async def store_result(
        self,
        output_keys: list[str],
        result: dict[str, Any],
        ctx: WorkflowContext,
    ) -> None:
        """
        処理結果をワークフローコンテキストに保存する。

        output_keys をループして result 辞書から値を取得し、
        ctx.set_state() を呼び出す。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 に準拠する。

        Args:
            output_keys: 保存するキー名のリスト
            result: キーと値のペアからなる結果辞書
            ctx: ワークフローコンテキスト
        """
        for key in output_keys:
            value: Any = result.get(key)
            ctx.set_state(key, value)

    async def invoke_mcp_tool(
        self, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        MCP ツールを呼び出す。

        config.mcp_servers に tool_name が含まれているか検証し、
        agent.tool_call() を使用してツールを呼び出す。
        agent に tool_call メソッドが存在しない場合は NotImplementedError をスローする。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 に準拠する。

        Args:
            tool_name: 呼び出すツール名
            params: ツールに渡すパラメータ辞書

        Returns:
            ツール実行結果の辞書

        Raises:
            ValueError: tool_name が config.mcp_servers に含まれていない場合
            NotImplementedError: agent に tool_call メソッドが存在しない場合
        """
        if tool_name not in self.config.mcp_servers:
            raise ValueError(
                f"ツール '{tool_name}' は config.mcp_servers に登録されていません。"
                f" 登録済み: {self.config.mcp_servers}"
            )

        if hasattr(self.agent, "tool_call"):
            result: dict[str, Any] = await self.agent.tool_call(tool_name, params)
            return result

        raise NotImplementedError(
            "agent に tool_call メソッドが存在しません。"
            " Agent Framework 統合後に実装されます。"
        )

    async def report_progress(
        self,
        task_iid: int | str,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        進捗状況を報告する。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 で定義された 3 つのタイミング
        （start / llm_response / complete）で呼び出される。
        progress_reporter に report_progress メソッドが存在する場合に呼び出し、
        存在しない場合はログ出力のみを行う。

        Args:
            task_iid: タスク MR または Issue の IID
            event: イベント種別（start / llm_response / complete / error 等）
            details: イベントに付随する追加情報辞書（省略可能）
        """
        resolved_details: dict[str, Any] = details or {}

        # node_id はグラフ配置時に設定される。未設定の場合は agent_definition_id （id）で代替する
        resolved_node_id: str = self.config.node_id or self.config.id

        if hasattr(self.progress_reporter, "report_progress"):
            await self.progress_reporter.report_progress(
                task_iid=task_iid,
                event=event,
                agent_definition_id=self.config.id,
                node_id=resolved_node_id,
                details=resolved_details,
            )
        else:
            logger.info(
                "進捗報告: task_iid=%s, event=%s, node_id=%s, details=%s",
                task_iid,
                event,
                resolved_node_id,
                resolved_details,
            )
