"""Small market-route helpers kept outside the main HTTP handler."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from market_contract import attach_quote_contract


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and ('T' in value or ' ' in value):
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _snapshot_envelope(quotes: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    market_times: list[datetime] = []
    sessions: set[str] = set()
    sources: dict[str, dict[str, Any]] = {}
    for quote in quotes.values():
        market = quote.get('market') if isinstance(quote, dict) else None
        if not isinstance(market, dict):
            continue
        session = str(market.get('session') or 'unknown')
        source = str(market.get('source') or 'unknown')
        sessions.add(session)
        observed = _aware_datetime(market.get('asOf'))
        if observed is not None:
            market_times.append(observed)
        status = sources.setdefault(source, {
            'quoteCount': 0, 'sessions': set(), 'asOf': None,
        })
        status['quoteCount'] += 1
        status['sessions'].add(session)
        if observed is not None and (status['asOf'] is None or observed > status['asOf']):
            status['asOf'] = observed

    market_as_of = max(market_times) if market_times else None
    source_status: dict[str, Any] = {}
    for source, status in sources.items():
        observed = status['asOf']
        age = max(0.0, (generated_at - observed).total_seconds()) if observed else None
        freshness = ('unknown' if age is None else
                     'fresh' if age <= 120 else
                     'delayed' if age <= 900 else 'stale')
        source_status[source] = {
            'quoteCount': status['quoteCount'],
            'sessions': sorted(status['sessions']),
            'asOf': _iso_utc(observed) if observed else None,
            'ageSeconds': round(age, 1) if age is not None else None,
            'freshness': freshness,
        }
    return {
        'generatedAt': _iso_utc(generated_at),
        'marketAsOf': _iso_utc(market_as_of) if market_as_of else None,
        'sessionDate': market_as_of.date().isoformat() if market_as_of else None,
        'session': next(iter(sessions)) if len(sessions) == 1 else ('mixed' if sessions else 'unknown'),
        'sourceStatus': source_status,
    }


def market_snapshot(indices: dict[str, Any] | None, txf: dict[str, Any] | None,
                    *, generated_at: datetime | None = None) -> dict[str, Any]:
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
    generated = generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        raise ValueError('generated_at must be timezone-aware')
    envelope = _snapshot_envelope(quotes, generated.astimezone(timezone.utc))
    return {
        "ok": bool(quotes), "contractVersion": 2, "quotes": quotes,
        # ``updatedAt`` remains as a compatibility alias, but it can no longer
        # silently substitute server generation time for market observation time.
        "updatedAt": envelope['marketAsOf'], **envelope,
    }
