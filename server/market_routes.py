"""Small market-route helpers kept outside the main HTTP handler."""
from __future__ import annotations

from typing import Any
from market_contract import attach_quote_contract


def market_snapshot(indices: dict[str, Any] | None, txf: dict[str, Any] | None) -> dict[str, Any]:
    """Canonical snapshot for all market surfaces; intentionally additive."""
    indices = indices or {}
    quotes: dict[str, Any] = {}
    for key, symbol, name in (("t00", "^TWII", "加權指數"), ("o00", "^TWOII", "櫃買指數")):
        raw = indices.get(key)
        if isinstance(raw, dict):
            q = attach_quote_contract(raw, symbol=symbol, market="TW", source=raw.get("source") or "twse-mis")
            q["name"] = q.get("name") or name
            quotes[symbol] = q
    if isinstance(txf, dict) and txf.get("price") is not None:
        q = attach_quote_contract(txf, symbol="__TXF__", market="TW", session=txf.get("session") or "night", source=txf.get("source") or "taifex-mis")
        q["name"] = q.get("name") or "台指期"
        quotes["__TXF__"] = q
    return {"ok": bool(quotes), "contractVersion": 1, "quotes": quotes}
