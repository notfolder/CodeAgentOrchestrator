"""
ワークフロー定義シードスクリプト

docs/definitions/配下のJSONファイルをworkflow_definitionsテーブルに
システムプリセットとして登録する。既に登録済みの場合はスキップする冪等な処理。

AUTOMATA_CODEX_SPEC.md § 4.4.2（システムプリセットの初期登録）に準拠する。
IMPLEMENTATION_PLAN.md フェーズ9-1 に準拠する。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg
    from shared.database.repositories.workflow_definition_repository import (
        WorkflowDefinitionRepository,
    )

logger = logging.getLogger(__name__)

# docs/definitions/ ディレクトリのパス（本ファイルから3階層上のdocs/definitions/）
_DEFINITIONS_DIR = Path(__file__).parents[3] / "docs" / "definitions"

# 登録するシステムプリセット定義の設定
# 順序はワークフロー定義の優先度に基づく（標準→複数コード生成並列）
_PRESETS: list[dict[str, str]] = [
    {
        "name": "standard_mr_processing",
        "display_name": "標準MR処理",
        "description": (
            "コード生成・バグ修正・テスト作成・ドキュメント生成の"
            "4タスクに対応する標準フロー"
        ),
        "graph_file": "standard_mr_processing_graph.json",
        "agent_file": "standard_mr_processing_agents.json",
        "prompt_file": "standard_mr_processing_prompts.json",
    },
    {
        "name": "multi_codegen_mr_processing",
        "display_name": "複数コード生成並列処理",
        "description": (
            "3種類のエージェントが並列でコードを生成し、"
            "コードレビューで最良の実装を自動選択するフロー"
        ),
        "graph_file": "multi_codegen_mr_processing_graph.json",
        "agent_file": "multi_codegen_mr_processing_agents.json",
        "prompt_file": "multi_codegen_mr_processing_prompts.json",
    },
]


def _load_json(filename: str) -> dict[str, Any]:
    """
    docs/definitions/配下のJSONファイルを読み込む。

    Args:
        filename: JSONファイル名（ディレクトリパスなし）

    Returns:
        JSONデータの辞書

    Raises:
        FileNotFoundError: JSONファイルが見つからない場合
        json.JSONDecodeError: JSONのパースに失敗した場合
    """
    filepath = _DEFINITIONS_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"定義JSONファイルが見つかりません: {filepath}")
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


async def seed_workflow_definitions(
    repo: WorkflowDefinitionRepository,
) -> list[str]:
    """
    ワークフロー定義をデータベースに登録する。

    docs/definitions/配下のJSONファイルから2つのシステムプリセットを
    workflow_definitionsテーブルに登録する。
    既に登録済みの定義はスキップし、冪等に動作する。

    Args:
        repo: WorkflowDefinitionRepositoryインスタンス

    Returns:
        新規登録したプリセット名のリスト（スキップ分は含まない）

    Raises:
        FileNotFoundError: 定義JSONファイルが見つからない場合
        json.JSONDecodeError: JSONのパースに失敗した場合
    """
    registered_names: list[str] = []

    for preset in _PRESETS:
        name = preset["name"]

        # 既に登録済みかチェック（冪等性保証）
        existing = await repo.get_workflow_definition_by_name(name)
        if existing is not None:
            logger.info("プリセット '%s' は既に登録済みです。スキップします。", name)
            continue

        # 定義JSONファイルを読み込む
        graph_def = _load_json(preset["graph_file"])
        agent_def = _load_json(preset["agent_file"])
        prompt_def = _load_json(preset["prompt_file"])

        # ワークフロー定義をシステムプリセットとして登録する
        # backend と consumer が同時起動した場合の INSERT 競合を UniqueViolationError でキャッチする
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
        except Exception as exc:
            # asyncpg.exceptions.UniqueViolationError の場合は同時起動による二重投入なのでスキップ
            if "UniqueViolation" in type(exc).__name__ or "unique" in str(exc).lower():
                logger.info(
                    "プリセット '%s' は同時起動により既に登録済みです。スキップします。",
                    name,
                )
                continue
            raise

        logger.info("プリセット '%s' を登録しました。", name)
        registered_names.append(name)

    logger.info(
        "ワークフロー定義のシード処理が完了しました。"
        "登録件数: %d / スキップ件数: %d",
        len(registered_names),
        len(_PRESETS) - len(registered_names),
    )
    return registered_names


async def run(dsn: str | None = None) -> None:
    """
    シードスクリプトのエントリポイント。

    DB接続プールを作成してseed_workflow_definitions()を実行する。
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
        await seed_workflow_definitions(repo)
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run())
