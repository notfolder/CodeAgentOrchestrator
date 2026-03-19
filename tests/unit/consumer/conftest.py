"""
consumerテスト用のpytest設定

consumer/mcp/ 配下のサブモジュールを `mcp.*` として sys.modules に登録することで、
テストコード内の `from mcp.mcp_client import ...` を consumer の実装に解決させる。

背景:
    consumerパッケージは consumer/mcp/ に独自のMCPクライアント実装を持つ。
    テストでは `from mcp.mcp_client import ...` という形式でインポートするが、
    sys.path の順序によっては PyPI の `mcp` パッケージが優先され、
    consumer の実装が見つからない問題が発生する。

    以前は consumer/ を sys.path[0] に移動して解決していたが、
    agent-framework-core が PyPI の `mcp` パッケージを必要とするため衝突が生じた。

    現在は consumer/mcp/のサブモジュールのみを sys.modules に事前登録する方式に変更し、
    PyPI の `mcp` パッケージ（mcp.types 等）は引き続き利用可能としている。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CONSUMER_DIR = Path(__file__).parents[3] / "consumer"
_CONSUMER_MCP_DIR = _CONSUMER_DIR / "mcp"

# consumer/mcp/*.py のサブモジュールを `mcp.{stem}` として sys.modules に登録する。
# PyPI の `mcp` パッケージ（mcp.types 等）は上書きしない。
# 依存順: mcp_client → mcp_client_factory → execution_environment_mcp_wrapper
_MCP_LOAD_ORDER = ["mcp_client", "mcp_client_factory", "execution_environment_mcp_wrapper"]

for _stem in _MCP_LOAD_ORDER:
    _module_file = _CONSUMER_MCP_DIR / f"{_stem}.py"
    if not _module_file.exists():
        continue
    _full_name = f"mcp.{_stem}"
    if _full_name not in sys.modules:
        _spec = importlib.util.spec_from_file_location(_full_name, _module_file)
        if _spec is not None and _spec.loader is not None:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules[_full_name] = _mod
            try:
                _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
            except Exception:
                # モジュールのロードに失敗した場合は登録を取り消す
                del sys.modules[_full_name]
