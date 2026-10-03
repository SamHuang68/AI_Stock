# -*- coding: utf-8 -*-
"""行情的純資料契約：來源時間與傳輸時間分離，未知值不冒充零。"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

DEFAULT_QUOTE_MAX_AGE_SEC = 90.0
_ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")
_UNKNOWN_SOURCES = {"", "unknown", "none", "null", "—"}
_DEMO_SOURCES = {"demo", "reference", "wave_ai_ref", "legacy_demo", "heuristic"}


def finite_number(value: Any) -> float | None:
    """接受有限數值及數字字串；布林值、NaN、無限值與缺值均為未知。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def parse_as_of(value: Any) -> datetime | None:
    """只接受附時區的 ISO 日期時間；不推測日期或無時區時間的時區。"""
    if not isinstance(value, str) or not _ISO_TIME.match(value.strip()):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _clock(now: Any) -> datetime | None:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            return None
        return now.astimezone(timezone.utc)
    epoch = finite_number(now)
    if epoch is not None:
        try:
            return datetime.fromtimestamp(epoch, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    return parse_as_of(now)


def normalize_quote(
    raw: Any, symbol: str, now: Any = None, *,
    max_age_sec: float = DEFAULT_QUOTE_MAX_AGE_SEC,
) -> dict[str, Any]:
    """驗證單一行情，不抓資料、不信任輸入的 quality 或接收時間。"""
    raw = raw if isinstance(raw, dict) else {}
    expected = symbol.strip().upper() if isinstance(symbol, str) else ""
    raw_symbol = raw.get("symbol")
    actual = raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
    raw_source = raw.get("source")
    source = raw_source.strip() if isinstance(raw_source, str) else ""
    price = finite_number(raw.get("price"))
    stamp = parse_as_of(raw.get("as_of"))
    clock = _clock(now)
    limit = finite_number(max_age_sec)
    if limit is None or limit <= 0:
        limit = DEFAULT_QUOTE_MAX_AGE_SEC
    demo = raw.get("demo") is True or source.lower() in _DEMO_SOURCES
    reasons: list[str] = []
    invalid = False
    if raw_source is not None and not isinstance(raw_source, str):
        reasons.append("行情來源格式不明")
        invalid = True
    if not actual or not expected or actual != expected:
        reasons.append("行情商品缺漏或不一致")
        price = None
        invalid = True
    if price is None or price <= 0:
        price = None
        reasons.append("行情價格未知或非有限正值")
        invalid = True
    if source.lower() in _UNKNOWN_SOURCES:
        reasons.append("行情來源未知")
    if raw.get("demo") is not None and not isinstance(raw.get("demo"), bool):
        reasons.append("行情演練標記格式不明")
        invalid = True
    if stamp is None:
        reasons.append("行情來源時間未知或缺少時區")
    if clock is None:
        reasons.append("行情驗證時間無效")
    age = (clock - stamp).total_seconds() if clock is not None and stamp is not None else None
    if age is not None and age < 0:
        reasons.append("行情來源時間在未來")
    elif age is not None and age > limit:
        reasons.append("行情已過期")
    if invalid:
        # 錯誤輸入經正規化再驗證時仍不可恢復為可交易價格。
        price = None
        quality = "invalid"
    elif age is not None and age < 0:
        quality = "future"
    elif age is not None and age > limit:
        quality = "stale"
    elif reasons:
        quality = "unknown"
    else:
        quality = "demo" if demo else "fresh"
    return {
        "symbol": expected,
        "price": price,
        "as_of": stamp.isoformat() if stamp is not None else None,
        "source": source or "unknown",
        "demo": demo,
        "quality": quality,
        "age_sec": age,
        "reasons": reasons,
    }


def assess_quote(
    quote: Any, symbol: str | None = None, now: Any = None, *,
    mode: str = "paper", max_age_sec: float = DEFAULT_QUOTE_MAX_AGE_SEC,
) -> dict[str, Any]:
    """每次進場前重新計算新鮮度；演練行情只適用紙上模式。"""
    raw = quote if isinstance(quote, dict) else {}
    result = normalize_quote(raw, symbol if symbol is not None else raw.get("symbol"), now,
                             max_age_sec=max_age_sec)
    allowed = result["quality"] in {"fresh", "demo"}
    if mode not in {"paper", "live"}:
        result["reasons"].append("執行模式未知")
        allowed = False
    if result["demo"] and mode != "paper":
        result["reasons"].append("演練行情不得增加實帳風險")
        allowed = False
    result["entry_allowed"] = allowed
    return result
