"""
consumerテスト用のpytest設定

consumer/mcp/ ディレクトリがPyPIの `mcp` パッケージより優先されるよう
sys.pathを調整する。

背景:
  consumerパッケージは `packages = ["."]` でインストールされるため、
  consumer/ ディレクトリがsys.pathに追加される。ただし、pip等で
  インストールされたsite-packagesより後に追加されるため、
  `from mcp.mcp_client import ...` でPyPIの `mcp` パッケージが
  優先されてしまう競合が発生する。
  consumerのmcp/モジュールはPyPIの `mcp` とは別物であるため、
  ここで順序を調整して consumer/mcp/ を優先する。
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
