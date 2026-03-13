"""
EnvironmentAnalyzerの単体テスト

プロジェクト内の環境構築関連ファイル検出・解析機能を検証する。
MCPクライアントをモックしてファイル取得処理も確認する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from analysis.environment_analyzer import EnvironmentAnalyzer


# ========================================
# TestDetectEnvironmentFiles
# ========================================


class TestDetectEnvironmentFiles:
    """detect_environment_files()のテスト"""

    @pytest.fixture
    def analyzer(self) -> EnvironmentAnalyzer:
        """テスト用EnvironmentAnalyzerを返す（mcp_clientsなし）"""
        return EnvironmentAnalyzer()

    def test_pythonファイルが検出される(
        self, analyzer: EnvironmentAnalyzer
    ) -> None:
        """requirements.txtを含むfile_listで"python"タイプが検出されることを確認する"""
        file_list = ["requirements.txt", "README.md", "main.py"]

        result = analyzer.detect_environment_files(file_list)

        assert "python" in result
        assert "requirements.txt" in result["python"]

    def test_nodeファイルが検出される(
        self, analyzer: EnvironmentAnalyzer
    ) -> None:
        """package.jsonを含むfile_listで"node"タイプが検出されることを確認する"""
        file_list = ["package.json", "index.js"]

        result = analyzer.detect_environment_files(file_list)

        assert "node" in result
        assert "package.json" in result["node"]

    def test_サブディレクトリ内のファイルが検出される(
        self, analyzer: EnvironmentAnalyzer
    ) -> None:
        """"src/requirements.txt"が"python"タイプに含まれることを確認する"""
        file_list = ["src/requirements.txt", "src/main.py"]

        result = analyzer.detect_environment_files(file_list)

        assert "python" in result
        assert "src/requirements.txt" in result["python"]

    def test_環境ファイルがない場合は空dictを返す(
        self, analyzer: EnvironmentAnalyzer
    ) -> None:
        """環境ファイルが含まれないリストで空dictが返ることを確認する"""
        file_list = ["README.md", "LICENSE", "src/app.go"]

        result = analyzer.detect_environment_files(file_list)

        # go言語のファイルのみなのでどの環境タイプにもマッチしない
        assert result == {}

    def test_複数の環境タイプが同時に検出される(
        self, analyzer: EnvironmentAnalyzer
    ) -> None:
        """pythonとnodeのファイルが両方検出されることを確認する"""
        file_list = ["requirements.txt", "package.json", "README.md"]

        result = analyzer.detect_environment_files(file_list)

        assert "python" in result
        assert "node" in result
        assert "requirements.txt" in result["python"]
        assert "package.json" in result["node"]


# ========================================
# TestAnalyzeEnvironmentFiles
# ========================================


class TestAnalyzeEnvironmentFiles:
    """analyze_environment_files()のテスト"""

    @pytest.mark.asyncio
    async def test_mcp_clientsがない場合は空のfile_contentsを返す(self) -> None:
        """mcp_clientsなしでfile_contentsが空文字列であることを確認する"""
        analyzer = EnvironmentAnalyzer(mcp_clients=None)
        detected_files = {"python": ["requirements.txt"]}

        result = await analyzer.analyze_environment_files(detected_files)

        assert "detected_files" in result
        assert "file_contents" in result
        assert result["file_contents"]["requirements.txt"] == ""

    @pytest.mark.asyncio
    async def test_5000文字を超えるファイルは切り詰める(self) -> None:
        """5000文字超のファイル内容が切り詰められることを確認する"""
        # text_editor MCPクライアントをモックする
        mock_text_editor = MagicMock()
        long_content = "x" * 6000  # 5000文字を超えるコンテンツ
        mock_text_editor.call_tool.return_value = {"content": long_content}

        analyzer = EnvironmentAnalyzer(mcp_clients={"text_editor": mock_text_editor})
        detected_files = {"python": ["requirements.txt"]}

        result = await analyzer.analyze_environment_files(detected_files)

        # 5000文字に切り詰められていることを確認する
        assert len(result["file_contents"]["requirements.txt"]) == 5000

    @pytest.mark.asyncio
    async def test_mcp_clientが正常にファイル内容を返す(self) -> None:
        """text_editor MCPクライアントが正常にファイル内容を返す場合の動作を確認する"""
        mock_text_editor = MagicMock()
        file_content = "numpy==1.24.0\npandas==2.0.0"
        mock_text_editor.call_tool.return_value = {"content": file_content}

        analyzer = EnvironmentAnalyzer(mcp_clients={"text_editor": mock_text_editor})
        detected_files = {"python": ["requirements.txt"]}

        result = await analyzer.analyze_environment_files(detected_files)

        # ファイル内容が正しく取得されていることを確認する
        assert result["file_contents"]["requirements.txt"] == file_content
        # detected_filesに正しく記録されていることを確認する
        assert result["detected_files"]["requirements.txt"] == "python"
        # call_tool()がread_fileコマンドで呼ばれていることを確認する
        mock_text_editor.call_tool.assert_called_once_with(
            "read_file", {"path": "requirements.txt"}
        )

    @pytest.mark.asyncio
    async def test_mcp_clientがtext_editorを持たない場合は空文字列を返す(self) -> None:
        """mcp_clientsにtext_editorがない場合にfile_contentsが空文字列であることを確認する"""
        analyzer = EnvironmentAnalyzer(mcp_clients={"other_client": MagicMock()})
        detected_files = {"node": ["package.json"]}

        result = await analyzer.analyze_environment_files(detected_files)

        assert result["file_contents"]["package.json"] == ""
        assert result["detected_files"]["package.json"] == "node"

    @pytest.mark.asyncio
    async def test_mcp_clientが例外を発生させた場合は空文字列を返す(self) -> None:
        """call_tool()が例外をスローした場合にfile_contentsが空文字列であることを確認する"""
        mock_text_editor = MagicMock()
        mock_text_editor.call_tool.side_effect = RuntimeError("接続エラー")

        analyzer = EnvironmentAnalyzer(mcp_clients={"text_editor": mock_text_editor})
        detected_files = {"python": ["requirements.txt"]}

        # 例外が発生しても処理が継続することを確認する
        result = await analyzer.analyze_environment_files(detected_files)
        assert result["file_contents"]["requirements.txt"] == ""
