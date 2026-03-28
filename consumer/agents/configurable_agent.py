"""
ConfigurableAgent モジュール

グラフ内のすべてのエージェントノードを実装する汎用エージェントクラスを提供する。
エージェント定義ファイルの AgentNodeConfig に基づいて動作し、
planning / reflection / execution / review の各ロールに対応する。

CLASS_IMPLEMENTATION_SPEC.md § 1（ConfigurableAgent）に準拠する。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent_framework import Executor, WorkflowContext, handler

from consumer.middleware.i_middleware import WorkflowNode
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
        middlewares: list[Any] | None = None,
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
            middlewares: ノード実行フェーズに介入する IMiddleware のリスト（省略時は空リスト）
        """
        self.config: AgentNodeConfig = config
        self.agent: Any = agent
        # §1.3 保持データ: mcp_serversの各サーバーを解決して生成したMCPStdioTool / FunctionToolの結合リスト
        self.tools: list[Any] = tools if tools is not None else []
        self.prompt_content: str = prompt_content
        self.progress_reporter: Any = progress_reporter
        self.environment_id: str | None = environment_id
        # ノード実行フェーズ（after_execution / on_error）に介入するミドルウェアリスト
        self.middlewares: list[Any] = middlewares if middlewares is not None else []
        super().__init__(id=config.node_id or config.id)

    @handler(input=Any, output=Any)
    async def handle(self, msg: Any, ctx: WorkflowContext[Any]) -> None:
        """
        エージェントノードのメインハンドラ。

        CLASS_IMPLEMENTATION_SPEC.md § 1.4 の処理フロー（12 ステップ）に準拠する。

        処理フロー:
            1. 入力データ取得
            2. 進捗報告（開始）
            3. プロンプト生成
            4. Agent.run() 呼び出し
            5. LLM 応答取得
            6. 進捗報告（LLM 応答）
            7. ツール呼び出し処理（Agent Framework が自動管理）
            8. ロール別後処理
            9. 進捗報告（完了）
            10. 出力データ保存
            11. output_data を後続ノードへ送信する

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
            # ステップ 1: 入力データ取得
            input_data: dict[str, Any] = {
                key: ctx.get_state(key) for key in self.config.input_keys
            }

            # ステップ 2: 進捗報告（開始）
            await self.report_progress(ctx=ctx, event="start", details={})

            # ステップ 3: プロンプト生成
            # input_data の各キーを {key} プレースホルダーとして置換する
            prompt: str = self.prompt_content
            for key, value in input_data.items():
                prompt = prompt.replace(
                    f"{{{key}}}", str(value) if value is not None else ""
                )

            # ステップ 4: Agent.run() 呼び出し
            response: Any
            if hasattr(self.agent, "run"):
                # Agent.run() には文字列を直接渡す（自動的にuserメッセージに変換される）
                # response_format: json_object を指定して最終応答を必ず JSON にする
                response = await self.agent.run(
                    prompt,
                    options={"response_format": {"type": "json_object"}},
                )
            else:
                response = None

            # ステップ 5: LLM 応答取得
            # AgentResponse.text で応答テキストを取得する
            response_text: str
            if response is not None and hasattr(response, "text"):
                response_text = response.text or ""
            elif isinstance(response, str):
                response_text = response
            else:
                response_text = ""

            # ステップ 5.1: トークン使用量を ctx に中間保存する
            # agent.run() 成功直後に保存することで、後続ステップでエラーが起きても
            # on_error フェーズの TokenUsageMiddleware が記録できるようにする。
            # （クォータエラーはここに到達しないため自然に除外される）
            if response is not None:
                model_name: str = getattr(
                    getattr(self.agent, "client", None), "model_id", "unknown"
                )
                ctx.set_state(
                    "_pending_token_usage",
                    {
                        "usage_details": getattr(response, "usage_details", None),
                        "prompt_text": prompt,
                        "response_text": response_text,
                        "model": model_name,
                    },
                )

            # ステップ 6: 進捗報告（LLM 応答）
            # JSON応答の "summary" フィールドを優先し、なければ先頭200文字にフォールバック
            _parsed_for_summary = self._try_parse_json(response_text)
            response_summary: str = (
                str(_parsed_for_summary.get("summary"))[:200]
                if _parsed_for_summary and _parsed_for_summary.get("summary")
                else response_text[:200]
            )
            await self.report_progress(
                ctx=ctx,
                event="llm_response",
                details={"summary": response_summary},
            )

            # ステップ 7: ツール呼び出し処理
            # Agent Framework が MCPStdioTool を自動的に呼び出すため、明示的な実装は不要。
            # tool_choice="auto" の設定により LLM がツール呼び出しを判断して自動実行し、
            # フィードバックループはフレームワークが管理する。

            # ステップ 8: ロール別後処理
            await self._handle_role_specific(self.config.role, response_text, ctx)

            # ステップ 9: 進捗報告（完了）
            await self.report_progress(ctx=ctx, event="complete", details=output_data)

            # ステップ 10: 出力データ保存
            # response_text から出力を抽出し、output_keys に対して ctx.set_state() を呼び出す。
            # LLM がJSON形式で応答した場合は辞書として保存し、条件式評価で参照できるようにする。
            for key in self.config.output_keys:
                parsed_value: Any = self._try_parse_json(response_text)
                value_to_store: Any = (
                    parsed_value if parsed_value is not None else response_text
                )
                output_data[key] = value_to_store
                ctx.set_state(key, value_to_store)

            # token_usage をミドルウェアが読み取れるよう output_data に格納する
            # usage_details が None の場合は token_usage_middleware 側で tiktoken 推定する
            if response is not None:
                model_name: str = getattr(
                    getattr(self.agent, "client", None), "model_id", "unknown"
                )
                output_data["token_usage"] = {
                    "usage_details": getattr(response, "usage_details", None),
                    "prompt_text": prompt,
                    "response_text": response_text,
                    "model": model_name,
                }

            # after_execution フェーズ: ミドルウェアに実行結果を渡す
            _node = WorkflowNode(
                node_id=self.config.node_id or self.config.id,
                node_type="agent",
            )
            for _mw in self.middlewares:
                try:
                    await _mw.intercept(
                        phase="after_execution",
                        node=_node,
                        context=ctx,
                        result=output_data,
                    )
                except Exception:
                    logger.exception(
                        "after_executionミドルウェア呼び出し中にエラーが発生しました: node_id=%s",
                        _node.node_id,
                    )

        except Exception as exc:
            # エラー発生時は progress_reporter に通知してから再送出する
            logger.exception(
                "エージェントノード '%s' の処理中にエラーが発生しました。",
                self.config.id,
            )
            try:
                await self.report_progress(
                    ctx=ctx,
                    event="error",
                    details={"error": str(exc)},
                )
            except Exception:
                logger.exception("エラー進捗報告中に追加エラーが発生しました。")

            # on_error フェーズ: _pending_token_usage が ctx にある場合にトークンを記録する
            _node = WorkflowNode(
                node_id=self.config.node_id or self.config.id,
                node_type="agent",
            )
            for _mw in self.middlewares:
                try:
                    await _mw.intercept(
                        phase="on_error",
                        node=_node,
                        context=ctx,
                        exception=exc,
                    )
                except Exception:
                    logger.exception(
                        "on_errorミドルウェア呼び出し中にエラーが発生しました: node_id=%s",
                        _node.node_id,
                    )
            raise

        # ステップ 11: output_data を後続ノードへ送信する
        await ctx.send_message(output_data)

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | None:
        """
        LLM応答テキストをJSONとしてパースし、辞書を返す。

        コードブロック（```json ... ```）で囲まれた JSON も対応する。
        パースに失敗した場合、または結果が辞書でない場合は None を返す。

        Args:
            text: LLM応答テキスト

        Returns:
            パースされた辞書。パース失敗/非辞書の場合は None。
        """
        stripped = (text or "").strip()
        # ```json ... ``` または ``` ... ``` ブロックを抽出する
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
        candidate = code_block_match.group(1) if code_block_match else stripped
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return None

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
            " Agent Framework では tool_call の直接呼び出しは不要です（Agent.run() が自動実行）。"
        )

    async def report_progress(
        self,
        ctx: WorkflowContext,
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
            ctx: ワークフローコンテキスト（ProgressReporter に渡す）
            event: イベント種別（start / llm_response / complete / error 等）
            details: イベントに付随する追加情報辞書（省略可能）
        """
        resolved_details: dict[str, Any] = details or {}

        # node_id はグラフ配置時に設定される。未設定の場合は agent_definition_id （id）で代替する
        resolved_node_id: str = self.config.node_id or self.config.id

        if hasattr(self.progress_reporter, "report_progress"):
            await self.progress_reporter.report_progress(
                context=ctx,
                event=event,
                node_id=resolved_node_id,
                details=resolved_details,
            )
        else:
            logger.info(
                "進捗報告: event=%s, node_id=%s, details=%s",
                event,
                resolved_node_id,
                resolved_details,
            )
