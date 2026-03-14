"""
ファイルロックユーティリティモジュール

複数のProducerプロセスが並行実行される場合の排他制御を提供する。
fcntl.flock を使用してファイルベースのロック機構を実装する。

AUTOMATA_CODEX_SPEC.md § 2.3.1（FileLock コンポーネント一覧）に準拠する。
"""

from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from types import TracebackType
from typing import Self

logger = logging.getLogger(__name__)

# デフォルトのロックファイルディレクトリ
_DEFAULT_LOCK_DIR = "/tmp/automata_locks"


class FileLock:
    """
    ファイルロッククラス

    fcntl.flock を使用してファイルベースの排他ロックを提供する。
    コンテキストマネージャとして使用することで、ロックの取得・解放を
    確実に行うことができる。

    複数のProducerプロセスが同一のGitLab APIを並行してポーリングする際に
    重複タスク検出の排他制御として使用する。

    Attributes:
        lock_file: ロックファイルのパス
    """

    def __init__(self, lock_name: str, lock_dir: str = _DEFAULT_LOCK_DIR) -> None:
        """
        FileLockを初期化する。

        Args:
            lock_name: ロックの識別名（ファイル名として使用する）
            lock_dir: ロックファイルを配置するディレクトリパス
        """
        lock_path = Path(lock_dir)
        lock_path.mkdir(parents=True, exist_ok=True)
        self.lock_file = str(lock_path / f"{lock_name}.lock")
        self._fd: int | None = None

    def acquire(self) -> None:
        """
        ファイルロックを取得する。

        既にロックを取得済みの場合（_fdがNoneでない場合）は何もしない。
        ロックが既に他のプロセスに取得されている場合は、
        解放されるまでブロックする（LOCK_EX: 排他ロック）。

        Raises:
            OSError: ロックファイルのオープンや操作に失敗した場合
        """
        if self._fd is not None:
            # 既にロック取得済みのため再取得しない
            return
        logger.debug("ファイルロックを取得します: %s", self.lock_file)
        self._fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        logger.debug("ファイルロックを取得しました: %s", self.lock_file)

    def release(self) -> None:
        """
        ファイルロックを解放する。

        ロックを解放しファイルディスクリプタを閉じる。
        ロックが取得されていない場合は何もしない。
        """
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
                logger.debug("ファイルロックを解放しました: %s", self.lock_file)
            except OSError as exc:
                logger.warning(
                    "ファイルロック解放時にエラーが発生しました: %s, error=%s",
                    self.lock_file,
                    exc,
                )
            finally:
                self._fd = None

    def __enter__(self) -> Self:
        """コンテキストマネージャエントリー: ロックを取得する"""
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """コンテキストマネージャエグジット: ロックを解放する"""
        self.release()


def try_acquire_lock(lock_name: str, lock_dir: str = _DEFAULT_LOCK_DIR) -> FileLock | None:
    """
    ノンブロッキングでファイルロックの取得を試みる。

    ロックが取得できた場合はFileLockインスタンスを返す。
    既に他のプロセスがロックを保持している場合はNoneを返す。

    Args:
        lock_name: ロックの識別名
        lock_dir: ロックファイルを配置するディレクトリパス

    Returns:
        ロック取得成功時はFileLockインスタンス、失敗時はNone
    """
    lock_path = Path(lock_dir)
    lock_path.mkdir(parents=True, exist_ok=True)
    lock_file = str(lock_path / f"{lock_name}.lock")

    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # ロック取得成功: FileLockインスタンスを生成して返す
        file_lock = FileLock(lock_name, lock_dir)
        file_lock._fd = fd
        logger.debug("ノンブロッキングロック取得成功: %s", lock_file)
        return file_lock
    except BlockingIOError:
        logger.debug("ロックは既に取得されています: %s", lock_file)
        if "fd" in locals():
            os.close(fd)
        return None
    except OSError as exc:
        logger.warning("ロック取得試行中にエラーが発生しました: %s, error=%s", lock_file, exc)
        return None
