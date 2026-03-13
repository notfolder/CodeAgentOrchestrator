"""
各カスタムProviderの単体テスト

PostgreSqlChatHistoryProvider・PlanningContextProvider・
ToolResultContextProvider・ContextCompressionService・
TaskInheritanceContextProvider・ContextStorageManagerの
DB操作・ファイル操作をモックして動作を検証する。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.chat_history_provider import PostgreSqlChatHistoryProvider
from providers.planning_context_provider import PlanningContextProvider
from providers.tool_result_context_provider import ToolResultContextProvider
from providers.context_compression_service import ContextCompressionService
from providers.task_inheritance_context_provider import TaskInheritanceContextProvider
from providers.context_storage_manager import ContextStorageManager


# ========================================
# テスト用ヘルパー
# ========================================


def _make_mock_pool(fetch_return=None, fetchval_return=None) -> MagicMock:
    """
    asyncpg接続プールのモックを生成する。

    Args:
        fetch_return: conn.fetch()の戻り値
        fetchval_return: conn.fetchval()の戻り値

    Returns:
        モックasyncpg接続プール
    """
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fetch_return or [])
    mock_conn.fetchval = AsyncMock(return_value=fetchval_return or 0)
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ========================================
# TestPostgreSqlChatHistoryProvider
# ========================================


class TestPostgreSqlChatHistoryProvider:
    """PostgreSqlChatHistoryProviderのテスト"""

    @pytest.mark.asyncio
    async def test_get_messagesがメッセージ一覧を返す(self) -> None:
        """asyncpgプールをモックしてget_messages()がメッセージリストを返すことを確認する"""
        # fetchが返すRowのモックを生成する
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "role": "user",
            "content": "テストメッセージ",
            "tokens": 10,
        }[key]
        pool = _make_mock_pool(fetch_return=[mock_row])

        provider = PostgreSqlChatHistoryProvider(db_pool=pool)
        result = await provider.get_messages("test-uuid")

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "テストメッセージ"

    @pytest.mark.asyncio
    async def test_save_messagesが新規メッセージのみINSERTする(self) -> None:
        """既存メッセージ数を考慮して差分のみINSERTすることを確認する"""
        # 既存メッセージが1件ある状態をモックする
        pool = _make_mock_pool(fetchval_return=1)
        mock_conn = pool.acquire.return_value.__aenter__.return_value

        provider = PostgreSqlChatHistoryProvider(db_pool=pool)
        messages = [
            {"role": "user", "content": "既存メッセージ"},
            {"role": "assistant", "content": "新規メッセージ"},
        ]
        await provider.save_messages("test-uuid", messages)

        # INSERTが実行されていることを確認する（新規1件分）
        assert mock_conn.execute.call_count >= 1
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "INSERT" in call_args_str

    @pytest.mark.asyncio
    async def test_save_messagesがcompression_serviceを呼び出す(self) -> None:
        """compression_serviceとuser_emailが設定されている場合にcheck_and_compress_asyncが呼ばれることを確認する"""
        pool = _make_mock_pool(fetchval_return=0)

        # 圧縮サービスのモックを作成する
        mock_compression = MagicMock()
        mock_compression.check_and_compress_async = AsyncMock(return_value=False)

        provider = PostgreSqlChatHistoryProvider(
            db_pool=pool, compression_service=mock_compression
        )
        messages = [{"role": "user", "content": "新規メッセージ"}]
        await provider.save_messages(
            "test-uuid", messages, user_email="user@example.com"
        )

        # check_and_compress_asyncが呼ばれていることを確認する
        mock_compression.check_and_compress_async.assert_called_once_with(
            "test-uuid", "user@example.com"
        )

    @pytest.mark.asyncio
    async def test_save_messagesがuser_emailなしの場合は圧縮を呼ばない(self) -> None:
        """user_emailが提供されない場合はcheck_and_compress_asyncを呼ばないことを確認する"""
        pool = _make_mock_pool(fetchval_return=0)

        mock_compression = MagicMock()
        mock_compression.check_and_compress_async = AsyncMock(return_value=False)

        provider = PostgreSqlChatHistoryProvider(
            db_pool=pool, compression_service=mock_compression
        )
        messages = [{"role": "user", "content": "新規メッセージ"}]
        # user_emailを渡さない
        await provider.save_messages("test-uuid", messages)

        # check_and_compress_asyncが呼ばれないことを確認する
        mock_compression.check_and_compress_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_messagesが全メッセージ既存の場合はINSERTしない(self) -> None:
        """existing_countがlen(messages)と等しい場合にINSERTが実行されないことを確認する"""
        # 既存メッセージが2件ある状態をモックする（messagesも2件）
        pool = _make_mock_pool(fetchval_return=2)
        mock_conn = pool.acquire.return_value.__aenter__.return_value

        provider = PostgreSqlChatHistoryProvider(db_pool=pool)
        messages = [
            {"role": "user", "content": "既存メッセージ1"},
            {"role": "assistant", "content": "既存メッセージ2"},
        ]
        await provider.save_messages("test-uuid", messages)

        # 新規メッセージなしのためINSERTは実行されない
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_messagesがcompression_serviceの例外を無視する(self) -> None:
        """check_and_compress_async()が例外を送出しても主処理が継続して例外が伝播しないことを確認する"""
        pool = _make_mock_pool(fetchval_return=0)

        mock_compression = MagicMock()
        # 例外をスローするように設定する
        mock_compression.check_and_compress_async = AsyncMock(
            side_effect=RuntimeError("圧縮処理失敗")
        )

        provider = PostgreSqlChatHistoryProvider(
            db_pool=pool, compression_service=mock_compression
        )
        messages = [{"role": "user", "content": "新規メッセージ"}]

        # 例外が外部に伝播しないことを確認する
        await provider.save_messages(
            "test-uuid", messages, user_email="user@example.com"
        )
        # compression_serviceは呼ばれていることを確認する
        mock_compression.check_and_compress_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_messagesにmodel_nameを渡した場合にtiktokenで計算する(
        self,
    ) -> None:
        """model_name='gpt-4o-mini'をkwargsで渡した場合にINSERTが実行されることを確認する"""
        pool = _make_mock_pool(fetchval_return=0)
        mock_conn = pool.acquire.return_value.__aenter__.return_value

        provider = PostgreSqlChatHistoryProvider(db_pool=pool)
        messages = [{"role": "user", "content": "Hello world"}]
        # model_nameを明示的に指定する
        await provider.save_messages("test-uuid", messages, model_name="gpt-4o-mini")

        # INSERTが実行されていることを確認する
        assert mock_conn.execute.call_count >= 1
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "INSERT" in call_args_str


# ========================================
# TestPlanningContextProvider
# ========================================


class TestPlanningContextProvider:
    """PlanningContextProviderのテスト"""

    @pytest.mark.asyncio
    async def test_before_runがプランニング履歴をMarkdown形式で返す(self) -> None:
        """asyncpgをモックしてMarkdown形式のテキストが返ることを確認する"""
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "phase": "planning",
            "node_id": "node1",
            "plan": "テスト計画",
            "action_id": "act-001",
            "result": "成功",
        }[key]
        pool = _make_mock_pool(fetch_return=[mock_row])

        provider = PlanningContextProvider(db_pool=pool)
        result = await provider.before_run(task_uuid="test-uuid")

        assert result is not None
        assert "## プランニング履歴" in result
        assert "planning" in result
        assert "node1" in result

    @pytest.mark.asyncio
    async def test_before_runでデータがない場合はNoneを返す(self) -> None:
        """データがない場合はNoneを返すことを確認する"""
        pool = _make_mock_pool(fetch_return=[])

        provider = PlanningContextProvider(db_pool=pool)
        result = await provider.before_run(task_uuid="test-uuid")

        assert result is None

    @pytest.mark.asyncio
    async def test_after_runがDBにプランニング履歴を保存する(self) -> None:
        """after_run()がINSERTを実行することを確認する"""
        pool = _make_mock_pool()
        mock_conn = pool.acquire.return_value.__aenter__.return_value

        provider = PlanningContextProvider(db_pool=pool)
        await provider.after_run(
            task_uuid="test-uuid",
            phase="planning",
            node_id="node1",
            plan={"key": "value"},
            action_id="act-001",
            result="成功",
        )

        assert mock_conn.execute.call_count == 1
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "INSERT" in call_args_str


# ========================================
# TestToolResultContextProvider
# ========================================


class TestToolResultContextProvider:
    """ToolResultContextProviderのテスト"""

    @pytest.mark.asyncio
    async def test_before_runがツール実行結果のサマリを返す(self) -> None:
        """asyncpgとファイルシステムをモックして結果を確認する"""
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "tool_name": "execute_command",
            "tool_command": "ls -la",
            "file_path": "/tmp/result.json",
            "created_at": "2024-01-01",
        }[key]
        pool = _make_mock_pool(fetch_return=[mock_row])

        provider = ToolResultContextProvider(db_pool=pool)
        # ファイル読み込みをモックする
        with patch("pathlib.Path.exists", return_value=False):
            result = await provider.before_run(task_uuid="test-uuid")

        # ファイルが存在しない場合でもNoneにはならない（メタデータは存在するため）
        assert result is not None

    @pytest.mark.asyncio
    async def test_after_runがメタデータをDBに保存する(self) -> None:
        """after_run()がファイル保存とDB保存を行うことを確認する"""
        pool = _make_mock_pool()
        mock_conn = pool.acquire.return_value.__aenter__.return_value

        provider = ToolResultContextProvider(
            db_pool=pool, file_storage_base_dir="/tmp/test"
        )
        tool_result = {"output": "コマンド実行結果", "exit_code": 0}

        # ファイルシステム操作をモックする
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.write_text"), patch(
            "pathlib.Path.stat"
        ) as mock_stat, patch("pathlib.Path.exists", return_value=False):
            mock_stat.return_value.st_size = 100
            await provider.after_run(
                task_uuid="test-uuid",
                tool_name="execute_command",
                tool_command="ls -la",
                arguments={"command": "ls -la"},
                result=tool_result,
            )

        # DBへのINSERTが呼ばれていることを確認する
        assert mock_conn.execute.call_count >= 1

    def test_update_metadata_jsonが新規ファイルを作成する(self) -> None:
        """metadata.jsonが存在しない場合に新規作成して集計値が初期化されることを確認する"""
        import tempfile

        pool = _make_mock_pool()
        provider = ToolResultContextProvider(db_pool=pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path

            file_dir = Path(tmpdir)
            # metadata.jsonが存在しない状態でexecute_commandツールを呼び出す
            provider._update_metadata_json(file_dir, "execute_command")

            metadata_path = file_dir / "metadata.json"
            assert metadata_path.exists()
            meta = json.loads(metadata_path.read_text())
            assert meta["total_tool_calls"] == 1
            assert meta["total_command_executions"] == 1
            assert meta["total_file_reads"] == 0

    def test_update_metadata_jsonがtext_editorのカウンターを更新する(self) -> None:
        """text_editor系ツールの場合はtotal_file_readsが増加することを確認する"""
        import tempfile

        pool = _make_mock_pool()
        provider = ToolResultContextProvider(db_pool=pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path

            file_dir = Path(tmpdir)
            provider._update_metadata_json(file_dir, "text_editor")

            meta = json.loads((file_dir / "metadata.json").read_text())
            assert meta["total_file_reads"] == 1
            assert meta["total_command_executions"] == 0

    def test_update_metadata_jsonが既存ファイルに加算する(self) -> None:
        """既存のmetadata.jsonが存在する場合に既存の値に加算されることを確認する"""
        import tempfile

        pool = _make_mock_pool()
        provider = ToolResultContextProvider(db_pool=pool)

        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path

            file_dir = Path(tmpdir)
            existing = {
                "total_tool_calls": 5,
                "total_file_reads": 3,
                "total_command_executions": 2,
            }
            (file_dir / "metadata.json").write_text(
                json.dumps(existing), encoding="utf-8"
            )

            provider._update_metadata_json(file_dir, "execute_command")

            meta = json.loads((file_dir / "metadata.json").read_text())
            assert meta["total_tool_calls"] == 6
            assert meta["total_command_executions"] == 3


# ========================================
# TestContextCompressionService
# ========================================


class TestContextCompressionService:
    """ContextCompressionServiceのテスト"""

    @pytest.mark.asyncio
    async def test_圧縮無効の場合はFalseを返す(self) -> None:
        """context_compression_enabled=Falseの場合にFalseを返すことを確認する"""
        # ユーザー設定でcontext_compression_enabled=Falseを返すモックを作成する
        user_config_row = MagicMock()
        user_config_row.__getitem__ = lambda self, key: {
            "context_compression_enabled": False,
            "token_threshold": 10000,
            "keep_recent_messages": 5,
            "min_to_compress": 3,
            "min_compression_ratio": 0.5,
            "model_name": "gpt-4o",
        }[key]
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=user_config_row)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        mock_config.default_token_threshold = 10000
        mock_config.model_recommendations = {}

        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )
        result = await service.check_and_compress_async(
            task_uuid="test-uuid", user_email="test@example.com"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_ユーザー設定が存在しない場合はFalseを返す(self) -> None:
        """user_configsテーブルにユーザーが存在しない場合にFalseを返すことを確認する"""
        pool = MagicMock()
        mock_conn = AsyncMock()
        # fetchrowがNoneを返すことでユーザー設定未登録状態を再現する
        mock_conn.fetchrow = AsyncMock(return_value=None)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )
        result = await service.check_and_compress_async(
            task_uuid="test-uuid", user_email="unknown@example.com"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_トークン数が閾値以下の場合は圧縮しない(self) -> None:
        """total_tokens <= token_thresholdの場合にFalseを返すことを確認する"""
        # 圧縮有効だがトークン数が少ない状態を作成する
        user_config_row = MagicMock()
        user_config_row.__getitem__ = lambda self, key: {
            "context_compression_enabled": True,
            "token_threshold": 100000,
            "keep_recent_messages": 5,
            "min_to_compress": 3,
            "min_compression_ratio": 0.5,
            "model_name": "gpt-4o",
        }[key]
        # 合計トークン数が少ない状態を返す
        token_row = MagicMock()
        token_row.__getitem__ = lambda self, key: {"total_tokens": 100}[key]

        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[user_config_row, token_row])
        mock_conn.fetch = AsyncMock(return_value=[])
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        mock_config.default_token_threshold = 100000
        mock_config.model_recommendations = {}

        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )
        result = await service.check_and_compress_async(
            task_uuid="test-uuid", user_email="test@example.com"
        )

        # トークン数が閾値以下なので圧縮しない
        assert result is False

    @pytest.mark.asyncio
    async def test_圧縮対象が最小件数未満はFalseを返す(self) -> None:
        """compress_seqsの件数がmin_to_compress未満の場合にFalseを返すことを確認する"""
        # 圧縮有効・閾値超過だが圧縮対象メッセージが2件でmin_to_compress=3の状態を作成する
        user_config_row = MagicMock()
        user_config_row.__getitem__ = lambda self, key: {
            "context_compression_enabled": True,
            "token_threshold": 10000,
            "keep_recent_messages": 5,
            "min_to_compress": 3,
            "min_compression_ratio": 0.5,
            "model_name": "gpt-4o",
        }[key]

        # 圧縮対象候補のseqRowを2件のみ用意する
        row1 = MagicMock()
        row1.__getitem__ = lambda self, key: {"seq": 1, "role": "user"}[key]
        row2 = MagicMock()
        row2.__getitem__ = lambda self, key: {"seq": 2, "role": "assistant"}[key]

        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=user_config_row)
        # total_tokens=50000(閾値超過)
        mock_conn.fetchval = AsyncMock(return_value=50000)
        # fetch呼び出し順: recent_rows=[], system_rows=[], candidate_rows=[row1, row2]
        mock_conn.fetch = AsyncMock(side_effect=[[], [], [row1, row2]])
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )
        result = await service.check_and_compress_async(
            task_uuid="test-uuid", user_email="test@example.com"
        )

        # 圧縮対象2件 < min_to_compress=3 のため圧縮しない
        assert result is False

    @pytest.mark.asyncio
    async def test_圧縮率不十分の場合はFalseを返す(self) -> None:
        """LLM要約後の圧縮率がmin_compression_ratio以上の場合は圧縮をスキップしてFalseを返すことを確認する"""
        user_config_row = MagicMock()
        user_config_row.__getitem__ = lambda self, key: {
            "context_compression_enabled": True,
            "token_threshold": 10000,
            "keep_recent_messages": 5,
            "min_to_compress": 2,
            "min_compression_ratio": 0.5,
            "model_name": "gpt-4o",
        }[key]

        # 圧縮対象候補のseqRowを3件用意する
        row1 = MagicMock()
        row1.__getitem__ = lambda self, key: {"seq": 1, "role": "user"}[key]
        row2 = MagicMock()
        row2.__getitem__ = lambda self, key: {"seq": 2, "role": "assistant"}[key]
        row3 = MagicMock()
        row3.__getitem__ = lambda self, key: {"seq": 3, "role": "user"}[key]

        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=user_config_row)
        # fetchval呼び出し順: total_tokens=50000, original_tokens=200
        mock_conn.fetchval = AsyncMock(side_effect=[50000, 200])
        # fetch呼び出し順: recent_rows=[], system_rows=[], candidate_rows=[row1, row2, row3]
        mock_conn.fetch = AsyncMock(side_effect=[[], [], [row1, row2, row3]])
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )

        # compress_messages_asyncをモック化し、圧縮後120トークン（ratio=120/200=0.6≥0.5）を返す
        with patch.object(
            service,
            "compress_messages_async",
            new=AsyncMock(return_value=("要約テキスト", 120)),
        ):
            result = await service.check_and_compress_async(
                task_uuid="test-uuid", user_email="test@example.com"
            )

        # 圧縮率0.6がmin_compression_ratio=0.5以上なので圧縮をスキップする
        assert result is False

    @pytest.mark.asyncio
    async def test_正常に圧縮が実行されTrueを返す(self) -> None:
        """トークン閾値超過かつ圧縮率が十分な場合にcompressが実行されTrueを返すことを確認する"""
        user_config_row = MagicMock()
        user_config_row.__getitem__ = lambda self, key: {
            "context_compression_enabled": True,
            "token_threshold": 10000,
            "keep_recent_messages": 5,
            "min_to_compress": 2,
            "min_compression_ratio": 0.5,
            "model_name": "gpt-4o",
        }[key]

        # 圧縮対象候補のseqRowを3件用意する
        row1 = MagicMock()
        row1.__getitem__ = lambda self, key: {"seq": 1, "role": "user"}[key]
        row2 = MagicMock()
        row2.__getitem__ = lambda self, key: {"seq": 2, "role": "assistant"}[key]
        row3 = MagicMock()
        row3.__getitem__ = lambda self, key: {"seq": 3, "role": "user"}[key]

        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=user_config_row)
        # fetchval呼び出し順: total_tokens=50000, original_tokens=200
        mock_conn.fetchval = AsyncMock(side_effect=[50000, 200])
        # fetch呼び出し順: recent_rows=[], system_rows=[], candidate_rows=[row1, row2, row3]
        mock_conn.fetch = AsyncMock(side_effect=[[], [], [row1, row2, row3]])
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )

        # compress_messages_asyncをモック化し、圧縮後80トークン（ratio=80/200=0.4<0.5）を返す
        # replace_with_summary_asyncもモック化して副作用不要にする
        with (
            patch.object(
                service,
                "compress_messages_async",
                new=AsyncMock(return_value=("要約テキスト", 80)),
            ),
            patch.object(
                service, "replace_with_summary_async", new=AsyncMock(return_value=None)
            ),
        ):
            result = await service.check_and_compress_async(
                task_uuid="test-uuid", user_email="test@example.com"
            )

        # 圧縮率0.4がmin_compression_ratio=0.5未満なので圧縮が実行されTrueを返す
        assert result is True

    @pytest.mark.asyncio
    async def test_token_thresholdがNullの場合にmodel_recommendationsを参照する(
        self,
    ) -> None:
        """user_configs.token_threshold=NULLの場合にconfig.model_recommendationsから
        閾値を取得してトークン数と比較することを確認する"""
        # token_threshold=NULLを返すユーザー設定を作成する
        user_config_row = MagicMock()
        user_config_row.__getitem__ = lambda self, key: {
            "context_compression_enabled": True,
            "token_threshold": None,  # NULLで model_recommendations 参照をトリガーする
            "keep_recent_messages": 5,
            "min_to_compress": 3,
            "min_compression_ratio": 0.5,
            "model_name": "gpt-4o",
        }[key]

        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=user_config_row)
        # total_tokens=500（model_recommendationsの80000よりずっと小さい値）
        mock_conn.fetchval = AsyncMock(return_value=500)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        # model_recommendations["gpt-4o"] = 80000 がthresholdとして使われることを検証する
        mock_config.model_recommendations = {"gpt-4o": 80000}
        mock_config.default_token_threshold = 50000

        service = ContextCompressionService(
            db_pool=pool, llm_client=MagicMock(), config=mock_config
        )
        result = await service.check_and_compress_async(
            task_uuid="test-uuid", user_email="test@example.com"
        )

        # total_tokens=500 <= threshold=80000 のため圧縮しない
        assert result is False


# ========================================
# TestContextStorageManager
# ========================================


class TestContextStorageManager:
    """ContextStorageManagerのテスト"""

    @pytest.mark.asyncio
    async def test_save_token_usageがリポジトリを呼び出す(self) -> None:
        """save_token_usage()がtoken_usage_repository.record_token_usage()を呼び出すことを確認する"""
        mock_token_repo = AsyncMock()
        mock_token_repo.record_token_usage = AsyncMock()

        manager = ContextStorageManager(
            chat_history_provider=MagicMock(),
            token_usage_repository=mock_token_repo,
            context_repository=MagicMock(),
            task_repository=MagicMock(),
        )

        await manager.save_token_usage(
            user_email="test@example.com",
            task_uuid="test-uuid",
            node_id="node1",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

        # record_token_usageが呼ばれていることを確認する
        mock_token_repo.record_token_usage.assert_called_once()


# ========================================
# TestTaskInheritanceContextProvider
# ========================================


class TestTaskInheritanceContextProvider:
    """TaskInheritanceContextProviderのテスト"""

    @pytest.mark.asyncio
    async def test_before_runがdisable_inheritanceの場合はNoneを返す(self) -> None:
        """disable_inheritance=Trueの場合にNoneを返すことを確認する"""
        metadata = json.dumps({"disable_inheritance": True})
        task_row = MagicMock()
        task_row.__getitem__ = lambda self, key: {"metadata": metadata}[key]
        pool = _make_mock_pool()
        mock_conn = pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchrow = AsyncMock(return_value=task_row)

        provider = TaskInheritanceContextProvider(db_pool=pool)
        result = await provider.before_run(task_uuid="test-uuid")

        assert result is None

    @pytest.mark.asyncio
    async def test_before_runがタスク未発見の場合はNoneを返す(self) -> None:
        """tasksテーブルにtask_uuidが存在しない場合にNoneを返すことを確認する"""
        pool = _make_mock_pool()
        mock_conn = pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchrow = AsyncMock(return_value=None)

        provider = TaskInheritanceContextProvider(db_pool=pool)
        result = await provider.before_run(task_uuid="nonexistent-uuid")

        assert result is None

    @pytest.mark.asyncio
    async def test_before_runが過去タスクない場合はNoneを返す(self) -> None:
        """過去の成功タスクが存在しない場合にNoneを返すことを確認する"""
        metadata = json.dumps(
            {
                "task_identifier": "issue-123",
                "repository": "owner/repo",
            }
        )
        task_row = MagicMock()
        task_row.__getitem__ = lambda self, key: {"metadata": metadata}[key]
        pool = _make_mock_pool(fetch_return=[])
        mock_conn = pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchrow = AsyncMock(return_value=task_row)

        provider = TaskInheritanceContextProvider(db_pool=pool)
        result = await provider.before_run(task_uuid="test-uuid")

        assert result is None

    @pytest.mark.asyncio
    async def test_before_runが過去タスクのMarkdownを返す(self) -> None:
        """過去タスクが存在する場合にMarkdown形式の継承データを返すことを確認する"""
        from unittest.mock import patch as mock_patch

        metadata = json.dumps(
            {
                "task_identifier": "issue-123",
                "repository": "owner/repo",
            }
        )
        past_metadata_str = json.dumps(
            {
                "inheritance_data": {
                    "final_summary": "実装完了",
                    "planning_history": [],
                    "implementation_patterns": [],
                    "key_decisions": ["pytestを使用"],
                }
            }
        )
        task_row = MagicMock()
        task_row.__getitem__ = lambda self, key: {"metadata": metadata}[key]

        pool = _make_mock_pool()
        mock_conn = pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetchrow = AsyncMock(return_value=task_row)

        # _get_past_tasks_asyncをパッチして期待する辞書を返す
        past_task_dict = {
            "task_uuid": "past-uuid",
            "metadata": past_metadata_str,
            "completed_at": "2024-01-01",
        }

        provider = TaskInheritanceContextProvider(db_pool=pool)
        with mock_patch.object(
            provider, "_get_past_tasks_async", AsyncMock(return_value=past_task_dict)
        ):
            result = await provider.before_run(task_uuid="test-uuid")

        assert result is not None
        assert "Previous Task Context" in result
        assert "pytestを使用" in result

    def test_format_inheritance_dataがMarkdownを生成する(self) -> None:
        """_format_inheritance_data()が期待するMarkdown形式を返すことを確認する"""
        provider = TaskInheritanceContextProvider(db_pool=MagicMock())
        inheritance_data = {
            "final_summary": "テスト完了",
            "planning_history": [
                {
                    "phase": "planning",
                    "node_id": "node1",
                    "plan": "計画",
                    "created_at": "2024-01-01",
                }
            ],
            "implementation_patterns": [
                {"pattern_type": "test", "description": "pytestを使用"}
            ],
            "key_decisions": ["決定1", "決定2"],
        }

        result = provider._format_inheritance_data(inheritance_data)

        assert "Previous Task Context" in result
        assert "テスト完了" in result
        assert "Planning History" in result
        assert "pytestを使用" in result
        assert "決定1" in result

    @pytest.mark.asyncio
    async def test_after_runが何もしない(self) -> None:
        """after_run()が例外なく完了することを確認する（本Providerは何もしない）"""
        pool = _make_mock_pool()
        provider = TaskInheritanceContextProvider(db_pool=pool)
        # 例外が発生しないことを確認する
        result = await provider.after_run(task_uuid="test-uuid")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_past_tasks_asyncがimplementation_patterns数が多いタスクを優先する(
        self,
    ) -> None:
        """
        _get_past_tasks_async()がimplementation_patternsの要素数が多いタスクを優先して
        返すことを確認する（CLASS_IMPLEMENTATION_SPEC.md § 4.5.4に準拠）。
        """
        # 2件のタスクを用意する（1件目はpatterns少、2件目はpatterns多）
        meta_few = json.dumps(
            {
                "inheritance_data": {
                    "implementation_patterns": [{"pattern_type": "p1"}],
                }
            }
        )
        meta_many = json.dumps(
            {
                "inheritance_data": {
                    "implementation_patterns": [
                        {"pattern_type": "p1"},
                        {"pattern_type": "p2"},
                        {"pattern_type": "p3"},
                    ],
                }
            }
        )

        # dict()変換が動作するようにMappingプロトコルをサポートするクラスを使用する
        class _FakeRow(dict):
            """asyncpg Recordのdict変換をサポートするフェイクRowクラス"""

            pass

        row_recent = _FakeRow(
            {
                "task_uuid": "uuid-recent",
                "metadata": meta_few,
                "completed_at": "2024-02-01",
            }
        )
        row_older_but_richer = _FakeRow(
            {
                "task_uuid": "uuid-older",
                "metadata": meta_many,
                "completed_at": "2024-01-01",
            }
        )

        pool = _make_mock_pool(fetch_return=[row_recent, row_older_but_richer])

        provider = TaskInheritanceContextProvider(db_pool=pool)
        result = await provider._get_past_tasks_async("issue-1", "owner/repo")

        # implementation_patternsが多いuuid-olderが選択されることを確認する
        assert result is not None
        assert result["task_uuid"] == "uuid-older"


# ========================================
# TestContextCompressionServiceMethods
# ========================================


class TestContextCompressionServiceMethods:
    """ContextCompressionServiceの詳細メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_compress_messages_asyncが要約テキストを返す(self) -> None:
        """compress_messages_async()がLLMを呼び出し(summary, token_count)タプルを返すことを確認する（generate()フォールバック）"""
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "role": "user",
            "content": "テストコンテンツ",
        }[key]
        pool = _make_mock_pool(fetch_return=[mock_row])

        # generate_completionを持たないLLMクライアント（フォールバック確認）
        mock_llm = MagicMock(spec=["generate"])
        mock_llm.generate = AsyncMock(return_value="要約テキスト")
        mock_config = MagicMock()

        service = ContextCompressionService(
            db_pool=pool,
            llm_client=mock_llm,
            config=mock_config,
        )

        summary, token_count = await service.compress_messages_async(
            task_uuid="test-uuid", start_seq=0, end_seq=5
        )

        assert summary == "要約テキスト"
        assert isinstance(token_count, int)
        assert token_count > 0
        mock_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_compress_messages_asyncがgenerate_completionを優先呼び出しする(
        self,
    ) -> None:
        """
        generate_completion()が存在する場合はmodel/temperatureを指定して呼び出すことを確認する。
        CLASS_IMPLEMENTATION_SPEC.md § 4.4.3 手順3に準拠。
        """
        from shared.config.models import ContextCompressionConfig

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "role": "user",
            "content": "テストコンテンツ",
        }[key]
        pool = _make_mock_pool(fetch_return=[mock_row])

        # generate_completionを持つLLMクライアント
        mock_llm = MagicMock()
        mock_llm.generate_completion = AsyncMock(return_value="generate_completion要約")

        config = (
            ContextCompressionConfig()
        )  # summary_llm_model="gpt-4o-mini", summary_llm_temperature=0.3

        service = ContextCompressionService(
            db_pool=pool,
            llm_client=mock_llm,
            config=config,
        )

        summary, token_count = await service.compress_messages_async(
            task_uuid="test-uuid", start_seq=0, end_seq=5
        )

        assert summary == "generate_completion要約"
        # generate_completion()がmodel/temperatureを指定して呼ばれることを確認する
        mock_llm.generate_completion.assert_called_once()
        call_kwargs = mock_llm.generate_completion.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o-mini"
        assert call_kwargs.get("temperature") == 0.3

    @pytest.mark.asyncio
    async def test_replace_with_summary_asyncがトランザクションを実行する(self) -> None:
        """replace_with_summary_async()がDELETE・INSERT・UPDATE・INSERTをトランザクション内で実行することを確認する"""
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        # conn.transaction()は同期メソッドとして非同期コンテキストマネージャを返す
        mock_txn_cm = MagicMock()
        mock_txn_cm.__aenter__ = AsyncMock(return_value=None)
        mock_txn_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn_cm)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_config = MagicMock()
        service = ContextCompressionService(
            db_pool=pool,
            llm_client=MagicMock(),
            config=mock_config,
        )

        await service.replace_with_summary_async(
            task_uuid="test-uuid",
            summary="要約テキスト",
            start_seq=0,
            end_seq=5,
            original_tokens=100,
            compressed_tokens=30,
        )

        # execute が複数回呼ばれていることを確認する（DELETE・INSERT・UPDATE・INSERT）
        assert mock_conn.execute.call_count >= 4
        call_args_str = str(mock_conn.execute.call_args_list)
        assert "DELETE" in call_args_str
        assert "INSERT" in call_args_str
        assert "UPDATE" in call_args_str


# ========================================
# TestContextStorageManagerSaveError
# ========================================


class TestContextStorageManagerSaveError:
    """ContextStorageManager.save_error()のテスト"""

    @pytest.mark.asyncio
    async def test_save_errorがtask_repositoryを呼び出す(self) -> None:
        """save_error()がtask_repository.update_task_status()とupdate_task_metadata()を呼び出すことを確認する"""
        mock_task_repo = AsyncMock()
        mock_task_repo.update_task_status = AsyncMock()
        mock_task_repo.update_task_metadata = AsyncMock()

        manager = ContextStorageManager(
            chat_history_provider=MagicMock(),
            token_usage_repository=MagicMock(),
            context_repository=MagicMock(),
            task_repository=mock_task_repo,
        )

        await manager.save_error(
            task_uuid="test-uuid",
            node_id="node1",
            error_category="transient",
            error_message="テストエラー",
            stack_trace="Traceback ...",
        )

        # update_task_status()がfailed状態でerror_messageを渡して呼ばれることを確認する
        mock_task_repo.update_task_status.assert_called_once_with(
            "test-uuid",
            "failed",
            error_message="テストエラー",
        )
        # update_task_metadata()がエラー詳細（category/message/stack_trace）を含んで呼ばれることを確認する
        mock_task_repo.update_task_metadata.assert_called_once()
        call_args = mock_task_repo.update_task_metadata.call_args
        metadata_arg = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("metadata", {})
        )
        assert "error" in metadata_arg
        assert metadata_arg["error"]["category"] == "transient"
        assert metadata_arg["error"]["message"] == "テストエラー"
        assert metadata_arg["error"]["stack_trace"] == "Traceback ..."
        assert metadata_arg["error"]["node_id"] == "node1"

    @pytest.mark.asyncio
    async def test_save_errorがtask_repositoryなしでも例外を出さない(self) -> None:
        """task_repositoryにupdate_task_statusがない場合でも例外なく完了することを確認する"""
        mock_task_repo = MagicMock(spec=[])  # specに空リストを渡してメソッドなしにする

        manager = ContextStorageManager(
            chat_history_provider=MagicMock(),
            token_usage_repository=MagicMock(),
            context_repository=MagicMock(),
            task_repository=mock_task_repo,
        )

        # 例外が発生しないことを確認する
        await manager.save_error(
            task_uuid="test-uuid",
            node_id="node1",
            error_category="implementation",
            error_message="テストエラー",
            stack_trace="",
        )
