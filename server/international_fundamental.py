#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""International market/stock symbol contract and index fundamental proxies.

Non-Taiwan indices do not publish company financial statements.  Their market
fundamental score is therefore estimated from a disclosed basket of large-cap
constituents.  The payload always labels that limitation and never presents the
sample as full index constituent coverage.
"""
from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any, Mapping


INDEX_DEFINITIONS: dict[str, dict[str, Any]] = {
    "^GSPC": {
        "market": "US", "title": "美股大盤體質 · S&P 500",
        "members": ("MSFT", "AAPL", "NVDA", "AMZN", "META"),
    },
    "^DJI": {
        "market": "US", "title": "美股大盤體質 · 道瓊",
        "members": ("MSFT", "AAPL", "NVDA", "JPM", "WMT"),
    },
    "^IXIC": {
        "market": "US", "title": "美股科技體質 · NASDAQ",
        "members": ("MSFT", "NVDA", "AAPL", "AMZN", "GOOGL"),
    },
    "^NDX": {
        "market": "US", "title": "美股科技體質 · NASDAQ 100",
        "members": ("MSFT", "NVDA", "AAPL", "AMZN", "GOOGL"),
    },
    "^SOX": {
        "market": "US", "title": "半導體體質 · SOX",
        "members": ("NVDA", "AVGO", "AMD", "MU", "INTC"),
    },
    "^N225": {
        "market": "JP", "title": "日股大盤體質 · 日經 225",
        "members": ("7203.T", "6758.T", "9984.T", "8306.T", "8035.T"),
    },
}


def market_of_symbol(symbol: str) -> str:
    """Classify the supported quote contract without confusing Tokyo and TWSE."""
    s = str(symbol or "").strip().upper()
    if s == "^N225" or (s.endswith(".T") and not s.endswith((".TW", ".TWO"))):
        return "JP"
    if s.endswith((".TW", ".TWO")):
        return "TW"
    if s.startswith("^TW") or s in ("TWII", "TWOII", "TAIEX"):
        return "TW"
    if s and s[0].isdigit() and "." not in s and len(s) <= 6:
        return "TW"
    return "US"


def index_definition(symbol: str) -> dict[str, Any] | None:
    definition = INDEX_DEFINITIONS.get(str(symbol or "").strip().upper())
    return dict(definition) if definition else None


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _median(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for row in rows:
        value = None
        for key in keys:
            value = _number(row.get(key))
            if value is not None:
                break
        if value is not None:
            values.append(value)
    return round(median(values), 2) if values else None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _mean_available(weighted: list[tuple[float | None, float]]) -> int | None:
    present = [(value, weight) for value, weight in weighted if value is not None]
    if not present:
        return None
    total_weight = sum(weight for _, weight in present)
    return round(sum(float(value) * weight for value, weight in present) / total_weight)


def build_index_fundamental(
    symbol: str,
    member_stats: Mapping[str, Mapping[str, Any]],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Build a transparent large-cap proxy estimate for a supported index."""
    sym = str(symbol or "").strip().upper()
    definition = index_definition(sym)
    if not definition:
        raise ValueError(f"unsupported international index: {sym}")

    requested = list(definition["members"])
    usable = [dict(member_stats[ticker]) for ticker in requested
              if isinstance(member_stats.get(ticker), Mapping)
              and any(_number(member_stats[ticker].get(k)) is not None for k in (
                  "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
                  "opMargin", "netMargin", "roe", "forwardPE", "trailingPE",
              ))]
    used_members = [ticker for ticker in requested
                    if isinstance(member_stats.get(ticker), Mapping)
                    and any(_number(member_stats[ticker].get(k)) is not None for k in (
                        "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
                        "opMargin", "netMargin", "roe", "forwardPE", "trailingPE",
                    ))]

    revenue_growth = _median(usable, ("revenueGrowth",))
    earnings_growth = _median(usable, ("earningsGrowth", "earningsQuarterlyGrowth"))
    op_margin = _median(usable, ("opMargin",))
    net_margin = _median(usable, ("netMargin",))
    roe = _median(usable, ("roe",))
    pe = _median(usable, ("forwardPE", "trailingPE"))

    growth_score = _mean_available([
        (_clamp(50 + revenue_growth * 1.5) if revenue_growth is not None else None, 0.55),
        (_clamp(50 + earnings_growth) if earnings_growth is not None else None, 0.45),
    ])
    quality_score = _mean_available([
        (_clamp(op_margin * 2.5) if op_margin is not None else None, 0.45),
        (_clamp(net_margin * 3.0) if net_margin is not None else None, 0.35),
        (_clamp(roe * 1.5) if roe is not None else None, 0.20),
    ])
    valuation_score = round(_clamp(100 - (pe - 10) * 2.5)) if pe is not None else None
    score = _mean_available([
        (growth_score, 0.40), (quality_score, 0.35), (valuation_score, 0.25),
    ]) if len(usable) >= 2 else None

    def pct(value: float | None) -> str:
        return "--" if value is None else f"{value:+.1f}%"

    rows = [
        {"k": "營收成長中位數", "v": pct(revenue_growth), "score": growth_score},
        {"k": "盈餘成長中位數", "v": pct(earnings_growth), "score": growth_score},
        {"k": "營業利益率中位數", "v": pct(op_margin), "score": quality_score},
        {"k": "預估本益比中位數", "v": "--" if pe is None else f"{pe:.1f}x", "score": valuation_score},
        {"k": "代理樣本涵蓋", "v": f"{len(usable)}/{len(requested)} 檔大型權值股", "score": None},
    ]
    coverage = len(usable) / len(requested) if requested else 0
    # Confidence describes the proxy model, not full-index statistical coverage.
    # Keep it deliberately capped because five large caps cannot represent every constituent.
    confidence = round(min(70, 45 + coverage * 25))
    summary = (
        f"以 {len(usable)}/{len(requested)} 檔大型權值股代理估算；"
        f"營收成長中位數 {pct(revenue_growth)}、營益率中位數 {pct(op_margin)}、"
        f"預估本益比中位數 {'--' if pe is None else f'{pe:.1f} 倍'}。"
        "這是市場體質代理值，不是完整成分股加權財報。"
    )
    return {
        "symbol": sym,
        "code": sym,
        "date": as_of or date.today().isoformat(),
        "market": definition["market"],
        "kind": "market",
        "title": definition["title"],
        "score": score,
        "label": "代理樣本不足" if score is None else ("體質偏強" if score >= 70 else "體質中性" if score >= 50 else "體質偏弱"),
        "summary": summary,
        "plainSummary": summary,
        "marketRows": rows,
        "pillars": {
            "growth": growth_score,
            "quality": quality_score,
            "valuation": valuation_score,
        },
        "sampleMembers": used_members,
        "sampleRequested": requested,
        "confidence": confidence,
        "model": "LARGE_CAP_PROXY_V1",
        "revenue": None,
        "income": None,
        "_source": "Yahoo Finance · 大型權值股代理樣本",
        "_note": "非完整指數成分股加權；僅供市場體質比較。",
    }
