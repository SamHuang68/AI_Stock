#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow-only overnight versus cash-session structure research.

The module deliberately owns a stricter daily-bar contract than ``datastore``:
Yahoo ``adjclose`` is required, Open is adjusted with the same row factor, and
every accepted observation must satisfy close-to-close = overnight + intraday.
Nothing in this module is allowed to mutate DecisionContext or an Action Envelope.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from statistics import median
from threading import Lock
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request


SCHEMA_VERSION = "overnight-intraday.v1"
METHODOLOGY_VERSION = "oi-adjusted-session-structure/1.0"
IDENTITY_TOLERANCE = 1e-10
MIN_RETURNS = 80
CACHE_TTL_SECONDS = 15 * 60

UNIVERSES = {
    "TW": {
        "label": "台灣記憶體觀察籃子",
        "benchmark": {"symbol": "^TWII", "name": "加權指數"},
        "members": [
            {"symbol": "2344.TW", "name": "華邦電"},
            {"symbol": "2408.TW", "name": "南亞科"},
            {"symbol": "2337.TW", "name": "旺宏"},
            {"symbol": "3006.TW", "name": "晶豪科"},
            {"symbol": "8299.TWO", "name": "群聯"},
        ],
    },
    "US": {
        "label": "美國記憶體／儲存觀察籃子",
        "benchmark": {"symbol": "^SOX", "name": "費城半導體指數"},
        "members": [
            {"symbol": "MU", "name": "Micron"},
            {"symbol": "SNDK", "name": "Sandisk"},
            {"symbol": "WDC", "name": "Western Digital"},
            {"symbol": "STX", "name": "Seagate"},
        ],
    },
}

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = Lock()
_REFRESH_LOCK = Lock()


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits=4):
    number = _finite_number(value)
    return None if number is None else round(number, digits)


def _pct(log_return):
    number = _finite_number(log_return)
    return None if number is None else (math.exp(number) - 1.0) * 100.0


def _median(values):
    clean = [float(value) for value in values if _finite_number(value) is not None]
    return median(clean) if clean else None


def _rolling_sums(values, window):
    if window <= 0:
        return []
    out, running = [], 0.0
    for index, value in enumerate(values):
        running += float(value)
        if index >= window:
            running -= float(values[index - window])
        if index >= window - 1:
            out.append(running)
    return out


def _zscore_latest(values, window):
    sums = _rolling_sums(values, window)
    history = sums[-252:]
    if len(history) < max(24, window // 2):
        return None
    current = history[-1]
    baseline = history[:-1]
    center = median(baseline)
    mad = median(abs(value - center) for value in baseline)
    scale = 1.4826 * mad
    if scale <= 1e-12:
        mean = sum(baseline) / len(baseline)
        variance = sum((value - mean) ** 2 for value in baseline) / len(baseline)
        scale = math.sqrt(variance) if variance > 1e-16 else 0.0
        center = mean
    if scale <= 1e-12:
        return 0.0
    return (current - center) / scale


def _linear_slope(values, window=5):
    rows = list(values)[-window:]
    if len(rows) < 3:
        return None
    n = len(rows)
    x_mean = (n - 1) / 2.0
    y_mean = sum(rows) / n
    denominator = sum((index - x_mean) ** 2 for index in range(n))
    return sum((index - x_mean) * (value - y_mean) for index, value in enumerate(rows)) / denominator


def normalize_yahoo_chart(payload: dict, symbol: str) -> dict:
    """Return finalized, consistently adjusted daily Open/Close rows.

    Missing Open is rejected (never replaced with Close). A row factor of
    ``adjClose / rawClose`` is applied to Open and Close together. The most
    recent row is excluded when Yahoo marks the regular session as open.
    """
    chart = (payload or {}).get("chart") or {}
    error = chart.get("error")
    results = chart.get("result") or []
    if error or not results:
        raise ValueError(f"Yahoo chart unavailable for {symbol}")
    result = results[0] or {}
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_rows = indicators.get("quote") or []
    adjusted_rows = indicators.get("adjclose") or []
    if not quote_rows or not adjusted_rows:
        raise ValueError(f"adjusted OHLC contract unavailable for {symbol}")
    quote = quote_rows[0] or {}
    adjclose = (adjusted_rows[0] or {}).get("adjclose") or []
    required_arrays = [quote.get("open") or [], quote.get("close") or [], adjclose]
    if any(len(values) != len(timestamps) for values in required_arrays):
        raise ValueError(f"mismatched Yahoo chart arrays for {symbol}")
    meta = result.get("meta") or {}
    timezone_name = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        exchange_tz = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"exchange timezone unavailable for {symbol}: {timezone_name}") from exc
    session_open = str(meta.get("marketState") or "").upper() in {"REGULAR", "PRE", "PREPRE"}
    rows, rejected = [], []
    for index, timestamp in enumerate(timestamps):
        raw_open = _finite_number((quote.get("open") or [None] * len(timestamps))[index])
        raw_close = _finite_number((quote.get("close") or [None] * len(timestamps))[index])
        adjusted_close = _finite_number(adjclose[index] if index < len(adjclose) else None)
        if not raw_open or not raw_close or not adjusted_close or min(raw_open, raw_close, adjusted_close) <= 0:
            rejected.append({"index": index, "reason": "missing_or_nonpositive_adjusted_ohlc"})
            continue
        factor = adjusted_close / raw_close
        if not math.isfinite(factor) or factor <= 0:
            rejected.append({"index": index, "reason": "invalid_adjustment_factor"})
            continue
        day = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(exchange_tz).date().isoformat()
        rows.append({
            "date": day,
            "timestamp": int(timestamp),
            "open": raw_open * factor,
            "close": adjusted_close,
            "adjustmentFactor": factor,
        })
    rows.sort(key=lambda row: (row["date"], row["timestamp"]))
    deduped = {row["date"]: row for row in rows}
    rows = [deduped[day] for day in sorted(deduped)]
    exchange_today = datetime.now(timezone.utc).astimezone(exchange_tz).date().isoformat()
    if session_open and rows and rows[-1]["date"] == exchange_today:
        rejected.append({"date": rows[-1]["date"], "reason": "unfinished_regular_session"})
        rows = rows[:-1]
    if len(rows) < MIN_RETURNS + 1:
        raise ValueError(f"insufficient finalized adjusted rows for {symbol}: {len(rows)}")
    factors = [row["adjustmentFactor"] for row in rows]
    corporate_adjusted = any(abs(math.log(factors[index] / factors[index - 1])) > 0.05 for index in range(1, len(factors)))
    return {
        "symbol": symbol,
        "exchangeTimezone": timezone_name,
        "rows": rows,
        "rejected": rejected,
        "corporateActionAdjusted": corporate_adjusted,
    }


def derive_session_returns(rows: list[dict]) -> list[dict]:
    """Derive session returns and enforce the algebraic identity per row."""
    derived = []
    ordered = sorted(rows or [], key=lambda row: row.get("date") or "")
    for index in range(1, len(ordered)):
        previous, current = ordered[index - 1], ordered[index]
        previous_close = _finite_number(previous.get("close"))
        current_open = _finite_number(current.get("open"))
        current_close = _finite_number(current.get("close"))
        if not previous_close or not current_open or not current_close or min(previous_close, current_open, current_close) <= 0:
            continue
        overnight = math.log(current_open / previous_close)
        intraday = math.log(current_close / current_open)
        close_to_close = math.log(current_close / previous_close)
        identity_error = abs(close_to_close - overnight - intraday)
        if identity_error > IDENTITY_TOLERANCE:
            continue
        derived.append({
            "date": current.get("date"),
            "previousDate": previous.get("date"),
            "overnight": overnight,
            "intraday": intraday,
            "closeToClose": close_to_close,
            "identityError": identity_error,
        })
    if len(derived) < MIN_RETURNS:
        raise ValueError(f"insufficient valid session returns: {len(derived)}")
    return derived


def _gap_retention(rows, lookback=60, minimum_gap=0.005):
    significant = [row for row in rows[-lookback:] if abs(row["overnight"]) >= minimum_gap]
    values = [row["closeToClose"] / row["overnight"] for row in significant if abs(row["overnight"]) > 1e-12]
    if len(values) < 3:
        return {"value": None, "sample": len(values), "thresholdPct": minimum_gap * 100.0}
    return {
        "value": _round(max(-3.0, min(3.0, median(values))), 3),
        "sample": len(values),
        "thresholdPct": minimum_gap * 100.0,
    }


def analyze_returns(rows: list[dict]) -> dict:
    overnight = [row["overnight"] for row in rows]
    intraday = [row["intraday"] for row in rows]
    close_to_close = [row["closeToClose"] for row in rows]
    return {
        "sampleSize": len(rows),
        "asOf": rows[-1]["date"],
        "overnight20Pct": _round(_pct(sum(overnight[-20:])), 2),
        "intraday20Pct": _round(_pct(sum(intraday[-20:])), 2),
        "close20Pct": _round(_pct(sum(close_to_close[-20:])), 2),
        "overnight60Pct": _round(_pct(sum(overnight[-60:])), 2),
        "intraday60Pct": _round(_pct(sum(intraday[-60:])), 2),
        "close60Pct": _round(_pct(sum(close_to_close[-60:])), 2),
        "overnightZ20": _round(_zscore_latest(overnight, 20), 2),
        "intradayZ20": _round(_zscore_latest(intraday, 20), 2),
        "overnightZ60": _round(_zscore_latest(overnight, 60), 2),
        "intradayZ60": _round(_zscore_latest(intraday, 60), 2),
        "intradayVelocity5PctPoint": _round((_linear_slope(intraday, 5) or 0.0) * 100.0, 3),
        "gapRetention": _gap_retention(rows),
        "identityMaxError": max(row["identityError"] for row in rows),
    }


def residualize(member_rows: list[dict], benchmark_rows: list[dict]) -> list[dict]:
    benchmark_by_date = {row["date"]: row for row in benchmark_rows}
    out = []
    for row in member_rows:
        benchmark = benchmark_by_date.get(row["date"])
        if not benchmark or row.get("previousDate") != benchmark.get("previousDate"):
            continue
        overnight = row["overnight"] - benchmark["overnight"]
        intraday = row["intraday"] - benchmark["intraday"]
        close_to_close = row["closeToClose"] - benchmark["closeToClose"]
        error = abs(close_to_close - overnight - intraday)
        if error <= IDENTITY_TOLERANCE:
            out.append({"date": row["date"], "previousDate": row.get("previousDate"), "overnight": overnight, "intraday": intraday,
                        "closeToClose": close_to_close, "identityError": error})
    if len(out) < MIN_RETURNS:
        raise ValueError(f"insufficient benchmark-aligned returns: {len(out)}")
    return out


def _classify(overnight20, intraday20, synchronization_pct, quality):
    overnight20 = float(overnight20 or 0.0)
    intraday20 = float(intraday20 or 0.0)
    if quality not in {"good", "mixed"}:
        regime = "INSUFFICIENT_DATA"
    elif overnight20 >= 1.0 and intraday20 >= -0.5:
        regime = "OVERNIGHT_CONFIRMED"
    elif overnight20 >= 1.0 and intraday20 <= -1.0:
        regime = "GAP_FADE_DISTRIBUTION"
    elif intraday20 >= 1.5 and overnight20 < 1.0:
        regime = "CASH_SESSION_ACCUMULATION"
    elif overnight20 <= -1.0 and intraday20 <= -1.0:
        regime = "BROAD_CORRECTION"
    else:
        regime = "MIXED_LOW_CONFIDENCE"
    labels = {
        "OVERNIGHT_CONFIRMED": "隔夜重估獲日間承接",
        "GAP_FADE_DISTRIBUTION": "隔夜重估、日內消化",
        "CASH_SESSION_ACCUMULATION": "日間承接主導",
        "BROAD_CORRECTION": "隔夜與日內同步修正",
        "MIXED_LOW_CONFIDENCE": "定價結構分歧",
        "INSUFFICIENT_DATA": "資料不足",
    }
    separation = min(1.0, (abs(overnight20) + abs(intraday20)) / 8.0)
    evidence_strength = min(0.82, 0.35 + 0.25 * separation + 0.22 * max(0.0, min(1.0, synchronization_pct / 100.0)))
    if regime in {"MIXED_LOW_CONFIDENCE", "INSUFFICIENT_DATA"}:
        evidence_strength = min(evidence_strength, 0.49 if regime.startswith("MIXED") else 0.2)
    return {"id": regime, "label": labels[regime], "evidenceStrength": round(evidence_strength, 2)}


def _fetch_yahoo_payload(symbol: str, range_name="2y", timeout=10):
    encoded = urllib.parse.quote(symbol, safe="")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
           f"?range={range_name}&interval=1d&events=div%7Csplits")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ST-Research/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _market_snapshot(market: str, fetcher) -> dict:
    universe = UNIVERSES[market]
    requested = [universe["benchmark"], *universe["members"]]
    normalized, errors = {}, []
    with ThreadPoolExecutor(max_workers=min(5, len(requested))) as executor:
        future_map = {executor.submit(fetcher, item["symbol"]): item for item in requested}
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                normalized[item["symbol"]] = normalize_yahoo_chart(future.result(), item["symbol"])
            except Exception as exc:
                errors.append({"symbol": item["symbol"], "error": str(exc)[:160]})
    benchmark_symbol = universe["benchmark"]["symbol"]
    if benchmark_symbol not in normalized:
        return {"market": market, "label": universe["label"], "status": "insufficient",
                "benchmark": universe["benchmark"], "members": [], "errors": errors,
                "quality": {"status": "insufficient", "warnings": ["benchmark_unavailable"]}}
    benchmark_returns = derive_session_returns(normalized[benchmark_symbol]["rows"])
    members = []
    for item in universe["members"]:
        series = normalized.get(item["symbol"])
        if not series:
            continue
        try:
            raw_returns = derive_session_returns(series["rows"])
            relative_returns = residualize(raw_returns, benchmark_returns)
            members.append({
                **item,
                "asOf": raw_returns[-1]["date"],
                "timezone": series["exchangeTimezone"],
                "raw": analyze_returns(raw_returns),
                "relative": analyze_returns(relative_returns),
                "quality": {
                    "status": "mixed" if series["rejected"] or series["corporateActionAdjusted"] else "good",
                    "rejectedRows": len(series["rejected"]),
                    "corporateActionAdjusted": series["corporateActionAdjusted"],
                },
            })
        except Exception as exc:
            errors.append({"symbol": item["symbol"], "error": str(exc)[:160]})
    required = max(2, math.ceil(len(universe["members"]) * 0.75))
    quality_status = "good" if len(members) == len(universe["members"]) and not errors else ("mixed" if len(members) >= required else "insufficient")
    raw_on20 = _median((member["raw"]["overnight20Pct"] for member in members))
    raw_id20 = _median((member["raw"]["intraday20Pct"] for member in members))
    relative_on20 = _median((member["relative"]["overnight20Pct"] for member in members))
    relative_id20 = _median((member["relative"]["intraday20Pct"] for member in members))
    positive_count = sum(1 for member in members if (member["raw"]["close20Pct"] or 0) > 0)
    negative_count = sum(1 for member in members if (member["raw"]["close20Pct"] or 0) < 0)
    directional_count = positive_count + negative_count
    sync_pct = (max(positive_count, negative_count) / directional_count * 100.0) if directional_count else 0.0
    breadth_pct = (positive_count / len(members) * 100.0) if members else 0.0
    summary = {
        "overnightRepricing20Pct": _round(raw_on20, 2),
        "cashSessionAcceptance20Pct": _round(raw_id20, 2),
        "benchmarkRelative": {"overnight20Pct": _round(relative_on20, 2), "intraday20Pct": _round(relative_id20, 2),
                              "status": "display_only"},
        "basketBreadthPct": _round(breadth_pct, 1),
        "synchronizationPct": _round(sync_pct, 1),
        "gapRetention": _round(_median(member["raw"]["gapRetention"]["value"] for member in members), 2),
        "memberCount": len(members),
        "expectedMemberCount": len(universe["members"]),
        "breadth": {"positive": positive_count, "eligible": len(members), "ratio": _round(breadth_pct / 100.0, 3)},
        "asOf": min((member["asOf"] for member in members), default=None),
    }
    summary["regime"] = _classify(raw_on20, raw_id20, sync_pct, quality_status)
    return {
        "market": market,
        "universe": {"id": f"{market}_MEMORY_WATCH_BASKET_V1", "weighting": "equal_weight",
                     "members": [item["symbol"] for item in universe["members"]]},
        "label": universe["label"],
        "status": "ready" if quality_status in {"good", "mixed"} else "insufficient",
        "benchmark": {**universe["benchmark"], "method": "same-market daily session residual"},
        "summary": summary,
        "members": members,
        "errors": errors,
        "quality": {
            "status": quality_status,
            "finalizedBarsOnly": True,
            "adjustmentMode": "adjclose_factor",
            "quorum": {"required": required, "eligible": len(members), "total": len(universe["members"])},
            "warnings": (["partial_basket"] if len(members) < len(universe["members"]) else []) +
                        (["row_rejections_or_adjustments"] if any(member["quality"]["status"] != "good" for member in members) else []),
        },
    }


def _evidence(markets):
    rows = []
    for market in markets:
        summary = market.get("summary") or {}
        if not summary:
            continue
        reference = (f"20-session log returns; adjusted Open/Close; residual versus "
                     f"{(market.get('benchmark') or {}).get('symbol', 'benchmark')}; shadow research only")
        value = {
            "regime": (summary.get("regime") or {}).get("id"),
            "overnight20Pct": summary.get("overnightRepricing20Pct"),
            "intraday20Pct": summary.get("cashSessionAcceptance20Pct"),
            "synchronizationPct": summary.get("synchronizationPct"),
            "gapRetention": summary.get("gapRetention"),
            "members": summary.get("memberCount"),
        }
        rows.append({
            "id": f"shadow.overnight_intraday.{market['market'].lower()}",
            "metric": "隔夜定價 × 日間承接",
            "value": value,
            "comparison": "same-market benchmark residual",
            "source": "Yahoo Finance chart v8",
            "marketScope": market["market"],
            "session": "official_daily_finalized",
            "asOf": summary.get("asOf"),
            "reference": reference,
            "quality": (market.get("quality") or {}).get("status", "insufficient"),
            "authority": "shadow_observation",
        })
    return rows


def build_snapshot(markets=("TW", "US"), fetcher=_fetch_yahoo_payload) -> dict:
    selected = [market for market in markets if market in UNIVERSES]
    market_rows = [_market_snapshot(market, fetcher) for market in selected]
    quality = "good" if market_rows and all(row["quality"]["status"] == "good" for row in market_rows) else (
        "mixed" if any(row["status"] == "ready" for row in market_rows) else "insufficient")
    input_material = [(row.get("market"), (row.get("summary") or {}).get("asOf"),
                       [(member.get("symbol"), member.get("asOf"), (member.get("raw") or {}).get("sampleSize"))
                        for member in row.get("members") or []]) for row in market_rows]
    input_hash = hashlib.sha256(json.dumps(input_material, sort_keys=True).encode()).hexdigest()
    return {
        "ok": any(row["status"] == "ready" for row in market_rows),
        "contractVersion": 1,
        "model": "st-overnight-intraday/v1",
        "scopeId": "memory_v1",
        "universeVersion": "memory-theme/2026-08-v1",
        "schemaVersion": SCHEMA_VERSION,
        "methodologyVersion": METHODOLOGY_VERSION,
        "shadowOnly": True,
        "shadowMode": True,
        "decisionUse": "research_only",
        "actionAuthority": "none",
        "inputHash": input_hash,
        "authority": {
            "mode": "shadow_observation",
            "decisionUse": "research_only",
            "mutates": [],
            "prohibited": ["regime", "confidence", "keyLevels", "actionEnvelope", "leverage", "orders"],
        },
        "asOf": datetime.now(timezone.utc).isoformat(),
        "quality": {"status": quality},
        "markets": market_rows,
        "evidence": _evidence(market_rows),
        "methodology": {
            "returnIdentity": "ln(C_t/C_t-1) = ln(O_t/C_t-1) + ln(C_t/O_t)",
            "adjustment": "adjustedOpen = rawOpen * adjClose/rawClose; adjustedClose = adjClose",
            "windows": [20, 60],
            "gapRetention": "median(closeToClose/overnight) for |overnight| >= 0.5% in latest 60 sessions",
            "standardization": "rolling-sum robust z-score using past-only median/MAD baseline",
            "benchmark": "member session return minus same-market benchmark session return by exchange trading date",
            "claimBoundary": "Opening repricing is not identified institutional flow.",
        },
    }


def empty_snapshot(reason="NOT_REFRESHED") -> dict:
    return {
        "ok": False,
        "schemaVersion": SCHEMA_VERSION,
        "methodologyVersion": METHODOLOGY_VERSION,
        "shadowOnly": True,
        "authority": {"mode": "shadow_observation", "decisionUse": "research_only", "mutates": []},
        "status": "insufficient",
        "quality": {"status": "insufficient", "warnings": [reason]},
        "markets": [],
        "evidence": [],
    }


def latest_cached(market="all") -> dict:
    key = str(market or "all").strip().upper()
    if key == "ALL":
        markets = ("TW", "US")
    elif key in UNIVERSES:
        markets = (key,)
    else:
        raise ValueError("market must be all, TW or US")
    cache_key = ",".join(markets)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        return cached[1] if cached else empty_snapshot()


def get_snapshot(market="all", force=False, fetcher=None) -> dict:
    key = str(market or "all").strip().upper()
    if key == "ALL":
        markets = ("TW", "US")
    elif key in UNIVERSES:
        markets = (key,)
    else:
        raise ValueError("market must be all, TW or US")
    injected = fetcher is not None
    fetcher = fetcher or _fetch_yahoo_payload
    cache_key = ",".join(markets)
    if not force and not injected:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
                return cached[1]
    with _REFRESH_LOCK:
        if not force and not injected:
            with _CACHE_LOCK:
                cached = _CACHE.get(cache_key)
                if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
                    return cached[1]
        snapshot = build_snapshot(markets, fetcher=fetcher)
    if not injected:
        with _CACHE_LOCK:
            previous = _CACHE.get(cache_key)
            if snapshot.get("ok"):
                _CACHE[cache_key] = (time.time(), snapshot)
            elif previous:
                stale = json.loads(json.dumps(previous[1]))
                stale["quality"] = {"status": "stale", "warnings": ["REFRESH_FAILED_LAST_VALID_PRESERVED"]}
                stale["cache"] = {"stale": True, "refreshFailedAt": datetime.now(timezone.utc).isoformat()}
                return stale
    return snapshot
