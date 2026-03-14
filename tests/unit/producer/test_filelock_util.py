"""
filelock_util の単体テスト

FileLockクラスのロック取得・解放・競合時の排他制御動作を検証する。

IMPLEMENTATION_PLAN.md フェーズ7-3 に準拠する。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from producer.filelock_util import FileLock, try_acquire_lock


class TestFileLockAcquireRelease:
    """FileLockのロック取得・解放テスト"""

    def test_コンテキストマネージャでロックを取得して解放できる(self, tmp_path: Path) -> None:
        """withブロック内でロックを取得し、出た後に解放されることを確認する"""
        lock = FileLock("test_lock", lock_dir=str(tmp_path))
        with lock:
            # ロック中はfdがセットされていることを確認する
            assert lock._fd is not None

        # withブロック後はfdがNoneになっていることを確認する
        assert lock._fd is None

    def test_acquireとreleaseを手動で呼び出せる(self, tmp_path: Path) -> None:
        """acquire()/release()を明示的に呼び出してロック制御できることを確認する"""
        lock = FileLock("test_lock_manual", lock_dir=str(tmp_path))

        lock.acquire()
        assert lock._fd is not None

        lock.release()
        assert lock._fd is None

    def test_ロックファイルが作成される(self, tmp_path: Path) -> None:
        """ロック取得時にファイルが作成されることを確認する"""
        lock = FileLock("test_create", lock_dir=str(tmp_path))
        with lock:
            lock_file = Path(tmp_path) / "test_create.lock"
            assert lock_file.exists()

    def test_未取得状態でreleaseを呼んでも例外が発生しない(self, tmp_path: Path) -> None:
        """ロック未取得状態でrelease()を呼んでもエラーにならないことを確認する"""
        lock = FileLock("test_no_acquire", lock_dir=str(tmp_path))
        # 例外が発生しないことを確認する
        lock.release()
        assert lock._fd is None

    def test_例外発生時もロックが解放される(self, tmp_path: Path) -> None:
        """withブロック内で例外が発生してもロックが解放されることを確認する"""
        lock = FileLock("test_exception", lock_dir=str(tmp_path))

        with pytest.raises(ValueError):
            with lock:
                raise ValueError("テスト例外")

        assert lock._fd is None

    def test_ロックディレクトリが自動作成される(self, tmp_path: Path) -> None:
        """ロックディレクトリが存在しない場合に自動作成されることを確認する"""
        new_dir = str(tmp_path / "nested" / "lock_dir")
        lock = FileLock("test_dir_create", lock_dir=new_dir)
        with lock:
            assert Path(new_dir).exists()


class TestTryAcquireLock:
    """try_acquire_lock関数のテスト"""

    def test_ロックが取得できた場合はFileLockインスタンスを返す(self, tmp_path: Path) -> None:
        """ロック取得成功時にFileLockインスタンスが返されることを確認する"""
        result = try_acquire_lock("test_try", lock_dir=str(tmp_path))
        assert result is not None
        assert isinstance(result, FileLock)
        result.release()

    def test_取得したロックはコンテキストマネージャで使える(self, tmp_path: Path) -> None:
        """try_acquire_lockで取得したロックをwith文で使用できることを確認する"""
        lock = try_acquire_lock("test_try_ctx", lock_dir=str(tmp_path))
        assert lock is not None
        with lock:
            assert lock._fd is not None
        assert lock._fd is None

    def test_同一ロックは複数回取得できない(self, tmp_path: Path) -> None:
        """1つ目のロックが保持中は2つ目のtry_acquire_lockがNoneを返すことを確認する"""
        lock1 = try_acquire_lock("test_exclusive", lock_dir=str(tmp_path))
        assert lock1 is not None

        try:
            lock2 = try_acquire_lock("test_exclusive", lock_dir=str(tmp_path))
            # 競合時はNoneが返される
            assert lock2 is None
        finally:
            lock1.release()
