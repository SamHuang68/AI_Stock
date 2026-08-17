"""Stable market-quote contract shared by HTTP routes and UI consumers."""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


def cumulative_volume_contract(value: Any, *, source_unit: str,
                               source: str,
                               timestamp_ms: Any = None) -> dict[str, Any]:
    """Normalize a provider's session-cumulative volume without losing shares.

    ``volume`` remains cumulative lots for compatibility with the legacy TW
    chart client.  ``volumeShares`` is the canonical, provider-independent
    value.  Missing/invalid inputs stay missing; an observed zero is valid.
    """
    try:
        raw = float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        raw = None
    if raw is not None and (not math.isfinite(raw) or raw < 0):
        raw = None

    unit = str(source_unit or '').strip().lower()
    if unit not in ('lot', 'share'):
        raise ValueError('source_unit must be lot or share')

    if raw is None:
        lots = shares = None
    elif unit == 'lot':
        lots = raw
        shares = raw * 1000.0
    else:
        shares = raw
        lots = raw / 1000.0

    if shares is not None and shares.is_integer():
        shares = int(shares)
    if lots is not None and lots.is_integer():
        lots = int(lots)

    try:
        ts = int(float(timestamp_ms)) if timestamp_ms is not None else None
    except (TypeError, ValueError, OverflowError):
        ts = None
    if ts is not None and ts <= 0:
        ts = None

    return {
        'volume': lots,
        'volumeShares': shares,
        'volumeUnit': 'lot',
        'volumeLotSize': 1000,
        'volumeKind': 'session_cumulative',
        'volumeSource': source or 'unknown',
        'volumeTimestampMs': ts,
        # Only official MIS observations are safe to difference into a live
        # minute. Yahoo's daily cumulative value is delayed and allocation-unsafe.
        'volumeRealtime': source == 'twse-mis',
    }


def quote_contract(raw: dict[str, Any] | None, *, symbol: str, market: str,
                   session: str | None = None, source: str | None = None,
                   as_of: str | None = None,
                   reference_type: str = "previous_close") -> dict[str, Any]:
    """Return a normalized, additive quote contract without mutating ``raw``."""
    raw = dict(raw or {})
    price = _number(raw.get("price", raw.get("close")))
    reference = _number(raw.get("prevClose", raw.get("referencePrice")))
    change = _number(raw.get("change"))
    change_pct = _number(raw.get("displayChangePct", raw.get("changePct")))
    if change is None and price is not None and reference is not None:
        change = price - reference
    if change_pct is None and change is not None and reference not in (None, 0):
        change_pct = change / reference * 100.0
    return {"symbol": symbol, "market": market, "price": price,
            "referencePrice": reference, "referenceType": reference_type,
            "displayChange": change,
            "displayChangePct": round(change_pct, 4) if change_pct is not None else None,
            "session": session or raw.get("session") or "regular",
            "source": source or raw.get("source") or "unknown",
            # A fetch timestamp is not a market timestamp.  Leave the field
            # unknown unless the upstream source actually supplied one.
            "asOf": as_of or raw.get("asOf") or raw.get("time") or None}


def attach_quote_contract(raw: dict[str, Any] | None, **kwargs: Any) -> dict[str, Any]:
    """Keep legacy fields while adding a canonical ``market`` representation."""
    out = dict(raw or {})
    contract = quote_contract(out, **kwargs)
    out["market"] = contract
    out["displayChange"] = contract["displayChange"]
    out["displayChangePct"] = contract["displayChangePct"]
    out["referencePrice"] = contract["referencePrice"]
    out["referenceType"] = contract["referenceType"]
    out["asOf"] = contract["asOf"]
    return out
