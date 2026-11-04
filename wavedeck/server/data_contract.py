# -*- coding: utf-8 -*-
"""行情與數值的純資料契約：來源時間與傳輸時間分離，未知值不冒充零，非有限值不通過比較。

來源：codex/wavedeck-paper-p0（0bec06d）的 data_contract（WD P0 第 2a、2b 片），依 main 現行契約調整：
- 未來時間容忍 5 秒，與 策略契約.decision_from_signal 的訊號收 K 時間檢查一致（分支版為 0 秒）。
- 行情的 symbol 可省略（沿用所屬訊號的商品）；有給就必須相符。
- 規則模式（策略契約）自己已強制時間戳、新鮮度與價格，不經過這裡的閘門。
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

DEFAULT_QUOTE_MAX_AGE_SEC = 90.0
FUTURE_TOLERANCE_SEC = 5.0          # 同 策略契約 的 age < -5；容忍送件端與本機的時鐘小誤差
_ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")
_UNKNOWN_SOURCES = {"", "unknown", "none", "null", "—"}
_DEMO_SOURCES = {"demo", "reference", "wave_ai_ref", "legacy_demo", "heuristic"}


def finite_number(value: Any) -> float | None:
    """接受有限數值及數字字串；布林值、NaN、無限值、非數字與缺值均為未知（None）。

    NaN 的任何比較都是 False（`nan < 門檻` 不成立），所以直接拿來比較的閘門會把它放行；
    `max(0.0, nan)` 也會回 0.0，讓回撤看起來像 0%。先經過這裡再比較。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def parse_as_of(value: Any) -> datetime | None:
    """只接受附時區的 ISO 日期時間；不推測日期，也不替沒有時區的時間猜時區。"""
    if not isinstance(value, str) or not _ISO_TIME.match(value.strip()):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


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


def normalize_quote(raw: Any, symbol: str, now: Any = None, *,
                    max_age_sec: float = DEFAULT_QUOTE_MAX_AGE_SEC) -> dict[str, Any]:
    """驗證單一行情；不抓資料，也不信任輸入自帶的 quality、age_sec 或接收時間。

    quality：fresh／demo（可用）｜stale（過期）｜future（來源時間在未來）｜unknown（價格有效但來源時間未知）｜
    invalid（商品不符、價格非有限正值、格式不明）。價格只在非 invalid 時保留。"""
    raw = raw if isinstance(raw, dict) else {}
    expected = symbol.strip().upper() if isinstance(symbol, str) else ""
    raw_symbol = raw.get("symbol")
    actual = raw_symbol.strip().upper() if isinstance(raw_symbol, str) and raw_symbol.strip() else expected
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
    if raw_symbol is not None and not isinstance(raw_symbol, str):
        reasons.append("行情商品格式不明")
        invalid = True
    if raw_source is not None and not isinstance(raw_source, str):
        reasons.append("行情來源格式不明")
        invalid = True
    if not expected or actual != expected:
        reasons.append("行情商品缺漏或不一致")
        invalid = True
    if price is None or price <= 0:
        reasons.append("行情價格未知或非有限正值")
        invalid = True
    if raw.get("demo") is not None and not isinstance(raw.get("demo"), bool):
        reasons.append("行情演練標記格式不明")
        invalid = True
    if source.lower() in _UNKNOWN_SOURCES:
        reasons.append("行情來源未知")
    if stamp is None:
        reasons.append("行情來源時間未知或缺少時區")
    if clock is None:
        reasons.append("行情驗證時間無效")
    age = (clock - stamp).total_seconds() if clock is not None and stamp is not None else None
    if age is not None and age < -FUTURE_TOLERANCE_SEC:
        reasons.append("行情來源時間在未來")
    elif age is not None and age > limit:
        reasons.append("行情已過期")
    if invalid:
        price = None
        quality = "invalid"
    elif age is not None and age < -FUTURE_TOLERANCE_SEC:
        quality = "future"
    elif age is not None and age > limit:
        quality = "stale"
    elif reasons:
        quality = "unknown"
    else:
        quality = "demo" if demo else "fresh"
    return {"symbol": expected, "price": price, "as_of": stamp.isoformat() if stamp is not None else None,
            "source": source or "unknown", "demo": demo, "quality": quality, "age_sec": age, "reasons": reasons}


def assess_quote(quote: Any, symbol: str | None = None, now: Any = None, *, mode: str = "paper",
                 max_age_sec: float = DEFAULT_QUOTE_MAX_AGE_SEC) -> dict[str, Any]:
    """每次進場前重新計算新鮮度（不沿用存起來的 quality）；演練行情只適用紙上模式。"""
    raw = quote if isinstance(quote, dict) else {}
    result = normalize_quote(raw, symbol if symbol is not None else raw.get("symbol"), now, max_age_sec=max_age_sec)
    allowed = result["quality"] in {"fresh", "demo"}
    if mode not in {"paper", "live"}:
        result["reasons"].append("執行模式未知")
        allowed = False
    if result["demo"] and mode != "paper":
        result["reasons"].append("演練行情不得增加實帳風險")
        allowed = False
    result["entry_allowed"] = allowed
    return result
