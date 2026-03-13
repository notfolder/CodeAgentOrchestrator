"""
計画前情報収集管理モジュール

タスク実行前の計画フェーズを管理するPrePlanningManagerクラスを提供する。
タスク内容の理解、環境情報の収集、LLMによる実行環境選択を担当する。

CLASS_IMPLEMENTATION_SPEC.md § 8（PrePlanningManager）に準拠する。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from consumer.analysis.environment_analyzer import EnvironmentAnalyzer

logger = logging.getLogger(__name__)

# LLMが選択可能な有効な環境名一覧
_VALID_ENVIRONMENTS = {"python", "miniforge", "node", "default"}


class PrePlanningManager:
    """
    計画前情報収集フェーズを管理するクラス。

    タスク内容の理解、環境情報の収集、LLMによるプロジェクト言語判定と
    実行環境選択を担当する。

    CLASS_IMPLEMENTATION_SPEC.md § 8 に準拠する。

    Attributes:
        config: 計画前情報収集の設定辞書
        llm_client: LLMクライアント
        mcp_clients: MCPツールクライアントの辞書
        understanding_result: 依頼内容の理解結果
        environment_info: 収集した環境情報
        selected_environment: LLMが選択した実行環境名
        plan_environment_id: plan環境のID（コンテキストから取得）
        selection_details: 環境選択の詳細情報（LLMの判断理由等）
    """

    def __init__(
        self,
        config: dict[str, Any],
        llm_client: Any,
        mcp_clients: dict[str, Any],
    ) -> None:
        """
        PrePlanningManagerを初期化する。

        Args:
            config: 計画前情報収集の設定辞書
            llm_client: LLMクライアント
            mcp_clients: MCPツールクライアントの辞書
        """
        self.config = config
        self.llm_client = llm_client
        self.mcp_clients = mcp_clients

        # 各フェーズの実行結果を保持するフィールド
        self.understanding_result: dict[str, Any] | None = None
        self.environment_info: dict[str, Any] | None = None
        self.selected_environment: str | None = None
        self.plan_environment_id: str | None = None
        self.selection_details: dict[str, Any] | None = None

        # 環境ファイル検出・解析用のアナライザーを初期化する
        self._environment_analyzer = EnvironmentAnalyzer(mcp_clients=mcp_clients)

    async def execute(
        self,
        task_uuid: str,
        task_description: str,
        plan_environment_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        計画前情報収集フェーズ全体を実行する。

        タスク理解 → 環境情報収集 → 実行環境選択の順に処理を行い、
        全結果をまとめた辞書を返す。

        CLASS_IMPLEMENTATION_SPEC.md § 8.3 に準拠する。

        Args:
            task_uuid: タスクの一意識別子
            task_description: タスクの説明文
            plan_environment_id: plan環境のID
            context: 追加コンテキスト情報（省略可）

        Returns:
            以下のキーを持つ結果辞書:
            - understanding_result: タスク理解結果
            - environment_info: 環境情報
            - selected_environment: 選択された実行環境名
            - selection_details: 環境選択の詳細情報
        """
        logger.info(
            "計画前情報収集フェーズを開始します: task_uuid=%s", task_uuid
        )

        # plan環境IDを保存する
        self.plan_environment_id = plan_environment_id

        # 依頼内容の理解
        logger.info("タスク内容の理解を開始します")
        self.understanding_result = await self.execute_understanding(task_description)

        # 環境情報の収集
        logger.info("環境情報の収集を開始します")
        self.environment_info = await self.collect_environment_info(plan_environment_id)

        # プロジェクト言語判定と実行環境選択
        logger.info("実行環境の選択を開始します")
        self.selected_environment, self.selection_details = (
            await self.select_execution_environment()
        )

        logger.info(
            "計画前情報収集フェーズが完了しました: selected_environment=%s",
            self.selected_environment,
        )

        return {
            "understanding_result": self.understanding_result,
            "environment_info": self.environment_info,
            "selected_environment": self.selected_environment,
            "selection_details": self.selection_details,
        }

    async def execute_understanding(
        self, task_description: str
    ) -> dict[str, Any]:
        """
        タスク情報をLLMに渡してタスク内容を理解する。

        llm_clientがgenerateメソッドを持つ場合にLLMを呼び出し、
        タスクの要約・キーポイント・複雑度を含む辞書を返す。

        Args:
            task_description: タスクの説明文

        Returns:
            以下のキーを持つ理解結果辞書:
            - summary: タスクの要約（LLM応答またはタスク説明文の先頭200文字）
            - key_points: キーポイントのリスト
            - complexity: 複雑度の見積もり（固定値 "medium"）
        """
        summary: str = task_description[:200]

        # llm_clientがgenerateメソッドを持つ場合はLLMを呼び出す
        if hasattr(self.llm_client, "generate"):
            try:
                prompt = f"タスク内容を理解して要約してください:\n{task_description}"
                summary = await self.llm_client.generate(prompt)
                logger.debug("LLMによるタスク理解が完了しました")
            except Exception:
                logger.warning(
                    "LLMによるタスク理解に失敗しました。タスク説明をそのまま使用します"
                )
                summary = task_description[:200]

        return {
            "summary": summary,
            "key_points": [],
            "complexity": "medium",
        }

    async def collect_environment_info(
        self, plan_environment_id: str
    ) -> dict[str, Any]:
        """
        EnvironmentAnalyzerを使用してリポジトリの環境情報を収集する。

        text_editor MCPクライアントでplan環境のファイルリストを取得し、
        環境構築関連ファイルを検出・解析する。

        Args:
            plan_environment_id: plan環境のID

        Returns:
            EnvironmentAnalyzerが返す環境情報辞書
        """
        file_list: list[str] = []

        # text_editor MCPクライアントでリポジトリのファイルリストを取得する
        text_editor = self.mcp_clients.get("text_editor")
        if text_editor is not None:
            try:
                result = text_editor.call_tool(
                    "list_files",
                    {
                        "path": "/workspace",
                        "environment_id": plan_environment_id,
                    },
                )
                # レスポンスのfilesフィールドからファイルリストを取得する
                if isinstance(result, dict):
                    file_list = result.get("files", [])
                elif isinstance(result, list):
                    file_list = result
            except Exception:
                logger.warning(
                    "ファイルリストの取得に失敗しました。空リストを使用します"
                )
                file_list = []

        logger.debug("取得したファイル数: %d件", len(file_list))

        # 環境構築関連ファイルを検出する
        detected_files = self._environment_analyzer.detect_environment_files(file_list)

        # 検出したファイルの内容を取得する
        environment_info = await self._environment_analyzer.analyze_environment_files(
            detected_files
        )

        return environment_info

    async def select_execution_environment(self) -> tuple[str, dict[str, Any]]:
        """
        LLMを使用してプロジェクトの実行環境を選択する。

        収集した環境情報をもとにLLMにプロンプトを送信し、
        python / miniforge / node / default の中から適切な環境を選択させる。
        LLMが無効な環境名を返した場合は "default" を使用する。

        CLASS_IMPLEMENTATION_SPEC.md § 8.3 に準拠する。

        Returns:
            (選択環境名, 選択詳細辞書) のタプル。
            選択詳細辞書にはLLMの判断理由等が含まれる。
        """
        # 環境情報が収集済みであれば検出ファイル一覧を取得する
        detected_files_info: dict[str, str] = {}
        if self.environment_info is not None:
            detected_files_info = self.environment_info.get("detected_files", {})

        # 検出ファイル一覧をプロンプト用に整形する
        if detected_files_info:
            files_summary = "\n".join(
                f"  - {path} ({env_type})"
                for path, env_type in detected_files_info.items()
            )
        else:
            files_summary = "  （環境構築関連ファイルは検出されませんでした）"

        valid_env_list = ", ".join(sorted(_VALID_ENVIRONMENTS))
        prompt = (
            "以下のリポジトリ内の環境構築関連ファイルを参考に、"
            f"最適な実行環境を {valid_env_list} の中から1つ選んでください。\n\n"
            f"検出されたファイル:\n{files_summary}\n\n"
            "回答はJSON形式で返してください。\n"
            '例: {"selected_environment": "python", "reasoning": "requirements.txtが存在するため"}'
        )

        selected_environment = "default"
        selection_details: dict[str, Any] = {
            "reasoning": "LLMによる環境選択を実行しませんでした",
            "raw_response": None,
        }

        # LLMを呼び出して環境を選択する
        if hasattr(self.llm_client, "generate"):
            try:
                raw_response: str = await self.llm_client.generate(prompt)
                selection_details["raw_response"] = raw_response

                # LLM応答からJSON部分を抽出してパースする
                parsed = self._parse_json_response(raw_response)
                candidate = parsed.get("selected_environment", "default")
                reasoning = parsed.get("reasoning", "")

                # 有効な環境名かチェックし、無効な場合は "default" を使用する
                if candidate in _VALID_ENVIRONMENTS:
                    selected_environment = candidate
                else:
                    logger.warning(
                        "LLMが無効な環境名を返しました: '%s'。'default'を使用します",
                        candidate,
                    )
                    selected_environment = "default"

                selection_details["reasoning"] = reasoning

            except Exception:
                logger.warning(
                    "LLMによる環境選択に失敗しました。'default'を使用します"
                )
                selected_environment = "default"

        logger.info("実行環境を選択しました: %s", selected_environment)
        return selected_environment, selection_details

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """
        LLMの応答文字列からJSON部分を抽出してパースする。

        応答全体をJSONとしてパースを試み、失敗した場合は
        最初の '{' から最後の '}' までを切り出して再度パースを試みる。

        Args:
            response: LLMの応答文字列

        Returns:
            パース結果の辞書。パース失敗時は空辞書を返す。
        """
        # まず応答全体をそのままパースしてみる
        try:
            result: dict[str, Any] = json.loads(response)
            return result
        except json.JSONDecodeError:
            pass

        # JSONブロックを文字列から切り出して再パースを試みる
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                result = json.loads(response[start : end + 1])
                return result
            except json.JSONDecodeError:
                pass

        logger.warning("LLM応答のJSONパースに失敗しました: response=%r", response[:200])
        return {}
