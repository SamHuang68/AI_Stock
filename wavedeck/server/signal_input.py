# -*- coding: utf-8 -*-
"""外部訊號（TradingView／手動）與 ST 橋接資料的輸入檢查。

只檢查，不改寫、不補預設值：策略契約（策略契約.claim）用 body 做冪等判斷，補欄位會改變它的指紋。
沿用 main 既有的寬鬆語意：欄位缺漏、None 或空字串都視為「用預設」，不是錯誤。
會被拒絕的只有一定出問題的輸入：
- 非有限數值（NaN／Infinity）：Python 的 json.loads 預設放行，但寫進狀態與稽核後瀏覽器端 JSON.parse 會失敗。
- 過大的內容、型別不對的容器、帶控制字元或過長的識別欄位、不在名單內的決策來源。

來源：codex/wavedeck-paper-p0（0bec06d）的 signal_input，依 main 現行契約調整後移植（WD P0 第 1 片）。
"""
from __future__ import annotations

import json
import re
from typing import Any

MAX_BODY_BYTES = 16384          # 單一訊號／橋接內容上限；HTTP 層另有 256 KiB 總上限
MAX_LABEL_CHARS = 128
PROVIDERS = frozenset({"heuristic", "ollama", "openai"})     # providers.py 認得的決策來源（比對時不分大小寫）
_SYMBOL = re.compile(r"^[A-Za-z0-9.^_-]{1,32}$")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def _given(value: Any) -> bool:
    """與 main 的 `body.get(key) or 預設` 同義：None 與空字串不算有給。"""
    return value is not None and value != ""


def bounded_object(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ValueError("輸入必須是 JSON 物件")
    try:
        wire = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("輸入含無效或非有限數值") from exc
    if len(wire) > MAX_BODY_BYTES:
        raise ValueError("訊號內容超過 16 KiB")
    return body


def _label(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_LABEL_CHARS:
        raise ValueError(f"{field} 必須是非空且長度不超過 {MAX_LABEL_CHARS} 的文字")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field} 不可包含控制字元")


def check_signal(body: Any) -> None:
    body = bounded_object(body)
    if _given(body.get("symbol")):
        symbol = body["symbol"]
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise ValueError("商品代碼格式無效")
    for field in ("event", "source"):
        if _given(body.get(field)):
            _label(body[field], field)
    if _given(body.get("provider")):
        provider = body["provider"]
        if not isinstance(provider, str) or provider.lower() not in PROVIDERS:
            raise ValueError("決策來源格式無效")
    if _given(body.get("signal_id")):
        signal_id = body["signal_id"]
        if not isinstance(signal_id, str) or not _ID.fullmatch(signal_id):
            raise ValueError("訊號識別碼格式無效")


def check_bridge(body: Any) -> None:
    body = bounded_object(body)
    if "meta" in body and body["meta"] is not None and not isinstance(body["meta"], dict):
        raise ValueError("橋接 meta 必須是物件")
    if body.get("delever") is not None and not isinstance(body["delever"], bool):
        raise ValueError("降載欄位必須是布林值")
    style = body.get("style")
    # 先比範圍再比整數：超大整數轉 float 會 OverflowError，範圍判斷先短路。
    if style is not None and (isinstance(style, bool) or not isinstance(style, (int, float))
                              or not 1 <= style <= 99 or style != int(style)):
        raise ValueError("風格必須是 1 至 99 的整數")
    for container in (body, body.get("meta") or {}):
        leaders = container.get("leaders")
        if leaders is not None and (not isinstance(leaders, list) or len(leaders) > 6
                                    or any(not isinstance(item, str) or len(item) > 40 for item in leaders)):
            raise ValueError("領先名單最多六個文字項目")
