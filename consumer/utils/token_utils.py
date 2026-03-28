"""
token_utils モジュール

tiktoken を使ったトークン数推定ユーティリティを提供する。
usage_details が取得できない場合（非公式エンドポイント等）の
フォールバック推定に使用する。
"""

from __future__ import annotations

import logging

import tiktoken

logger = logging.getLogger(__name__)

# tiktoken が対応していないモデルのフォールバックエンコーディング
_FALLBACK_ENCODING = "cl100k_base"


def estimate_token_count(text: str, model: str) -> int:
    """
    テキストのトークン数を tiktoken を使って推定する。

    指定されたモデルに対応するエンコーディングを使用する。
    モデルが tiktoken に未登録の場合は cl100k_base にフォールバックする。

    Args:
        text: トークン数を推定するテキスト
        model: LLM モデル名（例: "gpt-4o", "gpt-3.5-turbo"）

    Returns:
        推定されたトークン数（整数）
    """
    if not text:
        return 0

    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        # tiktoken 未対応モデルは cl100k_base にフォールバックする
        logger.debug(
            "tiktoken 未対応モデル '%s' のため %s を使用してトークン数を推定します。",
            model,
            _FALLBACK_ENCODING,
        )
        enc = tiktoken.get_encoding(_FALLBACK_ENCODING)

    return len(enc.encode(text))
