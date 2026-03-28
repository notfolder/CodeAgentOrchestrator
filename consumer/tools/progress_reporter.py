"""
ProgressReporter モジュール

タスクの進捗状況を MR へ反映するファサードクラスを定義する。
ConfigurableAgent や各 Executor からイベントを受け取り、
MermaidGraphRenderer でコメント全体を再構築し、
ProgressCommentManager に渡して上書き更新を実行する。

CLASS_IMPLEMENTATION_SPEC.md § 10.3（ProgressReporter）に準拠する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_framework import WorkflowContext
    from consumer.tools.mermaid_graph_renderer import MermaidGraphRenderer
    from consumer.tools.progress_comment_manager import ProgressCommentManager

logger = logging.getLogger(__name__)

# ノード状態定数
_STATE_PENDING = "pending"
_STATE_RUNNING = "running"
_STATE_DONE = "done"
_STATE_ERROR = "error"
_STATE_SKIPPED = "skipped"


def _now_str() -> str:
    """現在時刻を UTC 文字列（YYYY-MM-DD HH:MM:SS UTC）で返す。"""
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S UTC")


class ProgressReporter:
    """
    タスク進捗報告ファサードクラス。

    各ノードイベント（start / complete / error / llm_response）を受け取り、
    ノード状態を更新して MR の進捗コメントを上書き更新する。
    1コメント上書き方式で Mermaid フローチャートを含むコメントを管理する。

    CLASS_IMPLEMENTATION_SPEC.md § 10.3 に準拠する。

    Attributes:
        graph_def: グラフ定義辞書（nodes / edges を含む）
        mermaid_renderer: Mermaid フローチャート生成クラス
        comment_manager: 進捗コメント管理クラス
        node_states: ノードID → 状態文字列の辞書
        latest_llm_response: 最後に受信した LLM 応答の先頭 200 文字
        latest_event_summary: 最新イベントのサマリ文字列
        error_detail: エラー詳細テキスト（エラー発生時のみ設定）
        current_todo_content: 現在の Todo リスト Markdown テキスト（Todo が存在しない場合は None）
    """

    def __init__(
        self,
        graph_def: dict[str, Any],
        mermaid_renderer: "MermaidGraphRenderer",
        comment_manager: "ProgressCommentManager",
    ) -> None:
        """
        初期化。

        Args:
            graph_def: グラフ定義辞書
            mermaid_renderer: Mermaid フローチャート生成クラス
            comment_manager: 進捗コメント管理クラス
        """
        self.graph_def = graph_def
        self.mermaid_renderer = mermaid_renderer
        self.comment_manager = comment_manager
        # ノード状態辞書（initialize 時に全ノードを pending で初期化する）
        self.node_states: dict[str, str] = {}
        self.latest_llm_response: str = ""
        self.latest_event_summary: str = ""
        self.error_detail: str | None = None
        # Todo リスト Markdown テキスト（None = Todo なし、セクション③.5を省略する）
        self.current_todo_content: str | None = None
        # initialize() の二重呼び出しを防ぐフラグ
        self._initialized: bool = False

    def _get_node_label(self, node_id: str) -> str:
        """
        グラフ定義からノードのラベルを取得する。

        Args:
            node_id: ノード識別子

        Returns:
            ノードのラベル文字列（定義がない場合は node_id を返す）
        """
        for node in self.graph_def.get("nodes", []):
            if node.get("id") == node_id:
                return node.get("label", node_id)
        return node_id

    async def initialize(self, context: "WorkflowContext", mr_iid: int) -> None:
        """
        タスク開始時に全ノードを pending 状態で初期化し、初期コメントを MR に作成する。

        二重呼び出しを行っても安全（2回目以降はスキップ）。

        Args:
            context: ワークフローコンテキスト
            mr_iid: MergeRequest の IID
        """
        # 二重初期化を防ぐ
        if self._initialized:
            return

        # 全ノードを pending で初期化する
        for node in self.graph_def.get("nodes", []):
            node_id = node.get("id")
            if node_id:
                self.node_states[node_id] = _STATE_PENDING

        logger.info(
            "ProgressReporter 初期化: mr_iid=%d, ノード数=%d",
            mr_iid,
            len(self.node_states),
        )

        # 初期コメントを MR に作成する
        await self.comment_manager.create_progress_comment(
            context, mr_iid, self.node_states
        )
        self._initialized = True

    async def report_progress(
        self,
        context: "WorkflowContext",
        event: str,
        node_id: str,
        details: dict[str, Any],
    ) -> None:
        """
        各イベント発生時に呼び出し、ノード状態を更新してコメントを上書き更新する。

        未初期化の場合は自動的に initialize() を呼び出す（auto-initialize）。

        対応イベント:
        - start: ノードを running 状態に更新する
        - complete: ノードを done 状態に更新する
        - error: ノードを error 状態に更新する
        - llm_response: ノード状態は変更せず LLM 応答を記録する

        Args:
            context: ワークフローコンテキスト
            event: イベント種別（start / complete / error / llm_response）
            node_id: 対象ノードの識別子
            details: イベント詳細情報
        """
        # 未初期化なら自動で initialize する（ConfigurableAgent に依存しない自己管理）
        if not self._initialized:
            mr_iid: int | None = context.get_state("task_mr_iid")
            if mr_iid is not None:
                try:
                    await self.initialize(context, mr_iid)
                except Exception:
                    logger.exception(
                        "ProgressReporter の自動初期化中にエラーが発生しました。"
                    )

        label = self._get_node_label(node_id)
        timestamp = _now_str()

        # ① ノード状態の更新とサマリ・応答の設定
        if event == "start":
            self.node_states[node_id] = _STATE_RUNNING
            self.latest_event_summary = f"⏳ [{label}] 処理を開始します ― {timestamp}"
            logger.debug("ノード開始: node_id=%s", node_id)

        elif event == "complete":
            self.node_states[node_id] = _STATE_DONE
            elapsed = details.get("elapsed", "")
            self.latest_event_summary = f"✅ [{label}] 完了しました ― {elapsed}秒"
            logger.debug("ノード完了: node_id=%s, elapsed=%s", node_id, elapsed)

        elif event == "error":
            self.node_states[node_id] = _STATE_ERROR
            self.latest_event_summary = f"❌ [{label}] エラーが発生しました"
            self.error_detail = str(details.get("error", ""))
            logger.warning(
                "ノードエラー: node_id=%s, error=%s", node_id, self.error_detail
            )

        elif event == "llm_response":
            # ノード状態は変更しない
            response_text = details.get("response", details.get("summary", ""))
            self.latest_llm_response = response_text[:200]
            logger.debug("LLM応答受信: node_id=%s", node_id)

        elif event == "todo_changed":
            # ノード状態は変更しない。TodoManagementTool が呈出するイベント。
            # details["todo_markdown"] に最新の Todo リスト Markdown が格納される。
            todo_markdown: str = details.get("todo_markdown", "")
            # Todo が空文字の場合はセクション③.5を省略する（None に設定）
            self.current_todo_content = todo_markdown if todo_markdown else None
            logger.debug("Todo変更イベント受信: node_id=%s", node_id)

        else:
            logger.warning("未知のイベント種別: event=%s, node_id=%s", event, node_id)

        # ② MR コメントを上書き更新する
        mr_iid: int = context.get_state("task_mr_iid")
        await self.comment_manager.update_progress_comment(
            context=context,
            mr_iid=mr_iid,
            node_states=self.node_states,
            event_summary=self.latest_event_summary,
            llm_response=self.latest_llm_response,
            error_detail=self.error_detail,
            todo_content=self.current_todo_content,
        )

    async def finalize(
        self,
        context: "WorkflowContext",
        mr_iid: int,
        summary: str,
    ) -> None:
        """
        タスク全体完了時に呼び出し、残存する pending/running ノードを done にして
        最終サマリを付記したコメントを上書き更新する。

        Args:
            context: ワークフローコンテキスト
            mr_iid: MergeRequest の IID
            summary: タスク完了サマリ文字列
        """
        # ① pending または running のノードをすべて done に更新する
        for node_id, state in self.node_states.items():
            if state in (_STATE_PENDING, _STATE_RUNNING):
                self.node_states[node_id] = _STATE_DONE

        # ② 最終サマリを設定する
        self.latest_event_summary = f"✨ タスク完了 ― {summary}"
        logger.info("タスク完了: mr_iid=%d, summary=%s", mr_iid, summary)

        # ③ 最終コメントを上書き更新する
        await self.comment_manager.update_progress_comment(
            context=context,
            mr_iid=mr_iid,
            node_states=self.node_states,
            event_summary=self.latest_event_summary,
            llm_response=self.latest_llm_response,
            error_detail=self.error_detail,
            todo_content=self.current_todo_content,
        )
