"""
プリセットワークフロー定義更新スクリプト

docs/definitions/配下のJSONファイルで、DB上の既存システムプリセットを上書き更新する。
定義ファイルを修正した後に手動実行して DB へ反映する。

起動時の自動実行（seed_workflow_definitions）は既存レコードをスキップする冪等な処理
のままを維持する。本スクリプトはそれとは別に手動で実行する。

実行方法:
    docker compose exec backend \\
        python -m shared.database.seeds.update_preset_workflow_definitions

AUTOMATA_CODEX_SPEC.md § 4.4.2（システムプリセットの初期登録）に準拠する。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.database.repositories.workflow_definition_repository import (
        WorkflowDefinitionRepository,
    )

# _PRESETS と _load_json を seed スクリプトから再利用する
from shared.database.seeds.seed_workflow_definitions import _PRESETS, _load_json

logger = logging.getLogger(__name__)


async def update_preset_workflow_definitions(
    repo: WorkflowDefinitionRepository,
) -> dict[str, list[str]]:
    """
    既存のシステムプリセットワークフロー定義を最新のJSONで上書き更新する。

    docs/definitions/配下のJSONを読み込み、DB上のプリセットを更新する。
    存在しないプリセットは新規登録する。

    Args:
        repo: WorkflowDefinitionRepositoryインスタンス

    Returns:
        処理結果の辞書。キーは "updated"（更新）・"created"（新規登録）・
        "failed"（失敗）。それぞれの値は対象プリセット名のリスト。

    Raises:
        FileNotFoundError: 定義JSONファイルが見つからない場合
        json.JSONDecodeError: JSONのパースに失敗した場合
    """
    result: dict[str, list[str]] = {"updated": [], "created": [], "failed": []}

    for preset in _PRESETS:
        name = preset["name"]
        try:
            # 定義JSONファイルを読み込む
            graph_def = _load_json(preset["graph_file"])
            agent_def = _load_json(preset["agent_file"])
            prompt_def = _load_json(preset["prompt_file"])
        except (FileNotFoundError, Exception) as exc:
            logger.error(
                "プリセット '%s' の定義ファイル読み込みに失敗しました: %s", name, exc
            )
            result["failed"].append(name)
            continue

        # 既存レコードの有無を確認する
        existing = await repo.get_workflow_definition_by_name(name)

        if existing is not None:
            # 既存プリセットを上書き更新する
            updated = await repo.update_preset_workflow_definition(
                existing["id"],
                graph_definition=graph_def,
                agent_definition=agent_def,
                prompt_definition=prompt_def,
                version="1.0.0",
            )
            if updated is not None:
                logger.info(
                    "プリセット '%s' (id=%d) を更新しました。", name, existing["id"]
                )
                result["updated"].append(name)
            else:
                logger.warning(
                    "プリセット '%s' の更新が失敗しました（レコードが見つかりません）。",
                    name,
                )
                result["failed"].append(name)
        else:
            # 未登録の場合は新規登録する
            try:
                await repo.create_workflow_definition(
                    name=name,
                    display_name=preset["display_name"],
                    graph_definition=graph_def,
                    agent_definition=agent_def,
                    prompt_definition=prompt_def,
                    description=preset["description"],
                    is_preset=True,
                    version="1.0.0",
                )
                logger.info("プリセット '%s' を新規登録しました。", name)
                result["created"].append(name)
            except Exception as exc:
                logger.error("プリセット '%s' の新規登録に失敗しました: %s", name, exc)
                result["failed"].append(name)

    logger.info(
        "プリセット更新完了。更新: %d件 / 新規登録: %d件 / 失敗: %d件",
        len(result["updated"]),
        len(result["created"]),
        len(result["failed"]),
    )
    return result


async def run(dsn: str | None = None) -> None:
    """
    更新スクリプトのエントリポイント。

    DB接続プールを作成してupdate_preset_workflow_definitions()を実行する。
    スクリプト単体実行時（python -m ...）に使用する。

    Args:
        dsn: 接続DSN文字列。Noneの場合は環境変数から構築する。
    """
    from shared.database.connection import close_pool, create_pool
    from shared.database.repositories.workflow_definition_repository import (
        WorkflowDefinitionRepository,
    )

    pool = await create_pool(dsn)
    try:
        repo = WorkflowDefinitionRepository(pool)
        result = await update_preset_workflow_definitions(repo)
        if result["failed"]:
            raise SystemExit(f"一部のプリセット更新が失敗しました: {result['failed']}")
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run())
