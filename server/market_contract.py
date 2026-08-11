"""Stable market-quote contract shared by HTTP routes and UI consumers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value else None
    except (TypeError, ValueError):
        return None


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
            "asOf": as_of or raw.get("asOf") or raw.get("time") or datetime.now(timezone.utc).isoformat()}


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
