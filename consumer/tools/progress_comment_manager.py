"""
ProgressCommentManager モジュール

MR への進捗コメント（1コメント上書き方式）の新規作成と更新を管理するクラスを定義する。
スロットリング機能を持ち、1秒以内の連続更新を防止する。

CLASS_IMPLEMENTATION_SPEC.md § 10.5（ProgressCommentManager）に準拠する。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from consumer.agents.configurable_agent import WorkflowContext
    from consumer.tools.mermaid_graph_renderer import MermaidGraphRenderer
    from shared.gitlab_client.gitlab_client import GitlabClient

logger = logging.getLogger(__name__)

# スロットリング間隔（秒）: 連続更新を防ぐ最小インターバル
_THROTTLE_INTERVAL_SECONDS = 1.0


def _now_utc_str() -> str:
    """現在時刻を UTC 文字列（YYYY-MM-DD HH:MM:SS UTC）で返す。"""
    now_utc = datetime.now(tz=timezone.utc)
    return now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")


def _build_comment_body(
    mermaid_chart: str,
    event_summary: str,
    llm_response: str,
    error_detail: str | None,
) -> str:
    """
    コメント本文を 4 セクション構成で組み立てる。

    Args:
        mermaid_chart: Mermaid フローチャート文字列
        event_summary: 最新イベントのサマリ文字列
        llm_response: 最新 LLM 応答テキスト（空の場合は「（なし）」を表示）
        error_detail: エラー詳細テキスト（None の場合はセクションを省略）

    Returns:
        Markdown 形式のコメント本文
    """
    llm_display = llm_response if llm_response else "（なし）"

    sections = [
        "## 🤖 AutomataCodex 処理状況",
        "",
        "```mermaid",
        mermaid_chart,
        "```",
        "",
        "### 📊 最新状態",
        event_summary,
        "",
        "### 💬 最新LLM応答",
        llm_display,
    ]

    # エラー詳細がある場合は <details> セクションを追加する
    if error_detail is not None:
        sections += [
            "",
            "<details>",
            "<summary>⚠️ エラー詳細</summary>",
            "",
            error_detail,
            "",
            "</details>",
        ]

    return "\n".join(sections)


class ProgressCommentManager:
    """
    MR 進捗コメント管理クラス。

    タスク開始時に1度だけコメントを新規作成し、
    各イベント発生時に同一コメントを上書き更新する（1コメント上書き方式）。
    スロットリング機能により、1秒以内の連続更新を防止する。

    CLASS_IMPLEMENTATION_SPEC.md § 10.5 に準拠する。

    Attributes:
        gitlab_client: GitLab API クライアント
        mermaid_renderer: Mermaid フローチャート生成クラス
        last_update_time: 前回コメント更新時刻（Unix 時刻）
    """

    def __init__(
        self,
        gitlab_client: "GitlabClient",
        mermaid_renderer: "MermaidGraphRenderer",
    ) -> None:
        """
        初期化。

        Args:
            gitlab_client: GitLab API クライアント
            mermaid_renderer: Mermaid フローチャート生成クラス
        """
        self.gitlab_client = gitlab_client
        self.mermaid_renderer = mermaid_renderer
        # スロットリング用の最終更新時刻（初期値は0で即時更新可能）
        self.last_update_time: float = 0.0

    async def create_progress_comment(
        self,
        context: "WorkflowContext",
        mr_iid: int,
        node_states: dict[str, str],
    ) -> int:
        """
        タスク開始時に初期コメントを MR に新規作成する。

        初期コメントは全ノードが pending 状態で、LLM 応答欄は空欄となる。
        作成した Note ID を WorkflowContext に保存する。

        Args:
            context: ワークフローコンテキスト
            mr_iid: MergeRequest の IID
            node_states: ノードID → 状態文字列の辞書

        Returns:
            作成された GitLab Note ID
        """
        project_id: int = await context.get_state("project_id")

        # Mermaid チャートを生成する
        mermaid_chart = self.mermaid_renderer.render(node_states)

        # 初期コメント本文を組み立てる
        timestamp = _now_utc_str()
        event_summary = f"🚀 ワークフローを開始します ― {timestamp}"
        body = _build_comment_body(
            mermaid_chart=mermaid_chart,
            event_summary=event_summary,
            llm_response="",
            error_detail=None,
        )

        # GitLab にコメントを投稿する
        note_id = self.gitlab_client.create_merge_request_note(
            project_id, mr_iid, body
        )
        logger.info(
            "進捗コメント作成: project_id=%d, mr_iid=%d, note_id=%d",
            project_id,
            mr_iid,
            note_id,
        )

        # Note ID を WorkflowContext に保存する
        await context.set_state("progress_comment_id", note_id)

        return note_id

    async def update_progress_comment(
        self,
        context: "WorkflowContext",
        mr_iid: int,
        node_states: dict[str, str],
        event_summary: str,
        llm_response: str,
        error_detail: str | None,
    ) -> None:
        """
        既存の進捗コメントを上書き更新する。

        スロットリングにより前回更新から 1 秒未満の場合は待機してから更新する。
        progress_comment_id が未設定の場合はエラーログを出力して中断する。

        Args:
            context: ワークフローコンテキスト
            mr_iid: MergeRequest の IID
            node_states: ノードID → 状態文字列の辞書
            event_summary: 最新イベントのサマリ文字列
            llm_response: 最新 LLM 応答テキスト
            error_detail: エラー詳細テキスト（None の場合はセクション省略）
        """
        # ① スロットリング: 前回更新から 1 秒未満の場合は待機する
        elapsed = time.time() - self.last_update_time
        if elapsed < _THROTTLE_INTERVAL_SECONDS:
            wait_sec = _THROTTLE_INTERVAL_SECONDS - elapsed
            logger.debug("スロットリング待機: %.3f秒", wait_sec)
            await asyncio.sleep(wait_sec)

        # ② Note ID の取得
        note_id: int | None = await context.get_state("progress_comment_id")
        if note_id is None:
            logger.error(
                "progress_comment_id が未設定のためコメント更新をスキップします: mr_iid=%d",
                mr_iid,
            )
            return

        project_id: int = await context.get_state("project_id")

        # ③ Mermaid チャートを再生成してコメント本文を再構築する
        mermaid_chart = self.mermaid_renderer.render(node_states)
        body = _build_comment_body(
            mermaid_chart=mermaid_chart,
            event_summary=event_summary,
            llm_response=llm_response,
            error_detail=error_detail,
        )

        # ④ GitLab コメントを上書き更新する
        self.gitlab_client.update_merge_request_note(
            project_id, mr_iid, note_id, body
        )
        logger.info(
            "進捗コメント更新: project_id=%d, mr_iid=%d, note_id=%d",
            project_id,
            mr_iid,
            note_id,
        )

        # 更新時刻を記録する（スロットリング用）
        self.last_update_time = time.time()
