"""
環境解析モジュール

プロジェクトリポジトリ内の環境構築関連ファイルを検出し、
その内容をMCPクライアント経由で取得するEnvironmentAnalyzerクラスを提供する。

CLASS_IMPLEMENTATION_SPEC.md § 7（EnvironmentAnalyzer）に準拠する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ファイル内容の最大文字数（これを超えた場合は切り詰める）
_MAX_FILE_CONTENT_LENGTH = 5000


class EnvironmentAnalyzer:
    """
    プロジェクト内の環境構築関連ファイルを検出・解析するクラス。

    requirements.txt、package.json、environment.yml等の存在を確認し、
    プロジェクト言語の判定材料を提供する。

    CLASS_IMPLEMENTATION_SPEC.md § 7 に準拠する。

    Attributes:
        mcp_clients: MCPツールクライアントの辞書
        environment_file_patterns: 環境タイプ別のファイルパターン定義
    """

    def __init__(self, mcp_clients: dict[str, Any] | None = None) -> None:
        """
        EnvironmentAnalyzerを初期化する。

        Args:
            mcp_clients: MCPツールクライアントの辞書。Noneの場合は空辞書を使用する。
        """
        self.mcp_clients: dict[str, Any] = mcp_clients or {}

        # 環境タイプ別の検出対象ファイルパターン定義
        self.environment_file_patterns: dict[str, list[str]] = {
            "python": [
                "requirements.txt",
                "pyproject.toml",
                "setup.py",
                "Pipfile",
                "poetry.lock",
            ],
            "conda": [
                "environment.yml",
                "condaenv.yaml",
            ],
            "node": [
                "package.json",
                "package-lock.json",
                "yarn.lock",
                "pnpm-lock.yaml",
            ],
            "common": [
                "Dockerfile",
                "docker-compose.yml",
                "Makefile",
            ],
        }

    def detect_environment_files(
        self, file_list: list[str]
    ) -> dict[str, list[str]]:
        """
        ファイルリストから環境構築関連ファイルを検出する。

        environment_file_patternsの各タイプをループし、file_listの中から
        ファイル名末尾がパターンに一致するものを収集する。

        CLASS_IMPLEMENTATION_SPEC.md § 7.3 に準拠する。

        Args:
            file_list: リポジトリ内のファイルパス一覧

        Returns:
            環境タイプをキー、検出されたファイルパスのリストを値とする辞書。
            例: {"python": ["requirements.txt", "src/pyproject.toml"]}
        """
        detected_files: dict[str, list[str]] = {}

        for env_type, patterns in self.environment_file_patterns.items():
            matched: list[str] = []
            for pattern in patterns:
                for file_path in file_list:
                    # ファイル名末尾でパターンと一致するか判定する
                    if Path(file_path).name == pattern:
                        matched.append(file_path)
            if matched:
                detected_files[env_type] = matched

        logger.debug("環境ファイル検出完了: %s", detected_files)
        return detected_files

    async def analyze_environment_files(
        self, detected_files: dict[str, list[str]]
    ) -> dict[str, Any]:
        """
        検出された環境ファイルの内容をMCPクライアント経由で取得する。

        mcp_clientsが空の場合はファイル内容の取得をスキップする。
        ファイル内容が5000文字を超える場合は切り詰める。

        CLASS_IMPLEMENTATION_SPEC.md § 7.3 に準拠する。

        Args:
            detected_files: detect_environment_files()が返した検出済みファイル辞書

        Returns:
            以下のキーを持つ環境情報辞書:
            - detected_files: {ファイルパス: 環境タイプ} の辞書
            - file_contents: {ファイルパス: ファイル内容文字列} の辞書
        """
        environment_info: dict[str, Any] = {
            "detected_files": {},
            "file_contents": {},
        }

        for env_type, file_paths in detected_files.items():
            for file_path in file_paths:
                # 検出ファイルとその環境タイプを記録する
                environment_info["detected_files"][file_path] = env_type

                # mcp_clientsが存在しない場合はファイル内容の取得をスキップする
                if not self.mcp_clients:
                    environment_info["file_contents"][file_path] = ""
                    continue

                # text_editor MCPクライアント経由でファイル内容を読み込む
                text_editor = self.mcp_clients.get("text_editor")
                if text_editor is None:
                    environment_info["file_contents"][file_path] = ""
                    continue

                try:
                    result = text_editor.call_tool(
                        "read_file", {"path": file_path}
                    )
                    # レスポンスのcontentフィールドを文字列として取得する
                    content: str = result.get("content", "") if isinstance(result, dict) else ""
                except Exception:
                    logger.warning(
                        "ファイル読み込みに失敗しました: path=%s", file_path
                    )
                    content = ""

                # 内容が上限を超える場合は切り詰める
                if len(content) > _MAX_FILE_CONTENT_LENGTH:
                    logger.debug(
                        "ファイル内容を切り詰めます: path=%s, length=%d",
                        file_path,
                        len(content),
                    )
                    content = content[:_MAX_FILE_CONTENT_LENGTH]

                environment_info["file_contents"][file_path] = content

        logger.debug(
            "環境ファイル解析完了: detected=%d件",
            len(environment_info["detected_files"]),
        )
        return environment_info
