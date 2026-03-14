"""
producerテスト用のpytest設定

producerパッケージがsys.pathに追加されるよう設定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

# producerディレクトリをsys.pathへ追加する
_PRODUCER_DIR = str(Path(__file__).parents[3] / "producer")
if _PRODUCER_DIR not in sys.path:
    sys.path.insert(0, _PRODUCER_DIR)
