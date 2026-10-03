# -*- coding: utf-8 -*-
"""既有訊號與橋接資料的離線輸入檢查；不改授權或傳輸設定。"""
from __future__ import annotations

import json
import re
from typing import Any

_SYMBOL = re.compile(r"^[A-Za-z0-9.^_-]{1,32}$")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def bounded_object(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ValueError("輸入必須是 JSON 物件")
    try:
        wire = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("輸入含無效或非有限數值") from exc
    if len(wire) > 16384:
        raise ValueError("訊號內容超過 16 KiB")
    return body


def text_field(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} 必須是非空且長度不超過 {limit} 的文字")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field} 不可包含控制字元")
    return value.strip()


def validate_signal(body: Any, default_symbol: str) -> dict:
    result = dict(bounded_object(body))
    symbol = result.get("symbol", default_symbol)
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise ValueError("商品代碼格式無效")
    result["symbol"] = symbol.upper()
    for field, default in (("event", "MANUAL_REVIEW"), ("source", "manual")):
        result[field] = text_field(result.get(field, default), field, 128)
    if "provider" in result and (not isinstance(result["provider"], str) or
                                 result["provider"] not in {"heuristic", "ollama", "openai"}):
        raise ValueError("決策來源格式無效")
    if "signal_id" in result and (not isinstance(result["signal_id"], str) or
                                 not _ID.fullmatch(result["signal_id"])):
        raise ValueError("訊號識別碼格式無效")
    if "quote" in result and not isinstance(result["quote"], dict):
        raise ValueError("行情必須是物件")
    return result


def validate_bridge(body: Any) -> dict:
    body = bounded_object(body)
    if "meta" in body and not isinstance(body["meta"], dict):
        raise ValueError("橋接 meta 必須是物件")
    if "delever" in body and not isinstance(body["delever"], bool):
        raise ValueError("降載欄位必須是布林值")
    if "style" in body and (isinstance(body["style"], bool) or
        not isinstance(body["style"], (int, float)) or
        not float(body["style"]).is_integer() or not 1 <= body["style"] <= 99):
        raise ValueError("風格必須是 1 至 99 的整數")
    meta = body.get("meta") or {}
    for container in (body, meta):
        if "leaders" in container and (not isinstance(container["leaders"], list) or
            len(container["leaders"]) > 6 or
            any(not isinstance(value, str) or len(value) > 40 for value in container["leaders"])):
            raise ValueError("領先名單最多六個文字項目")
    return body
