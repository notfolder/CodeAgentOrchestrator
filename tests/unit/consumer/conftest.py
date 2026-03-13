"""
consumerテスト用のpytest設定

consumer/mcp/ ディレクトリがPyPIの `mcp` パッケージより優先されるよう
sys.pathを調整する。
"""

from __future__ import annotations

import sys
from pathlib import Path

# consumerディレクトリをsite-packagesより前にsys.pathへ追加することで、
# consumer/mcp/ がPyPIの `mcp` パッケージより優先してインポートされるようにする。
_CONSUMER_DIR = str(Path(__file__).parents[3] / "consumer")
if _CONSUMER_DIR in sys.path:
    sys.path.remove(_CONSUMER_DIR)
sys.path.insert(0, _CONSUMER_DIR)
