"""Small market-route helpers kept outside the main HTTP handler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any
from market_contract import attach_quote_contract, cumulative_volume_contract


TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


def quote_observation(epoch_ms: Any, now: datetime | None = None) -> dict[str, Any]:
    """成交時間與取得時間分開；缺值或跨交易日不可宣稱即時。"""
    observed = twse_mis_observation({'tlong': epoch_ms})
    current = (now or datetime.now(TAIPEI_TIMEZONE)).astimezone(TAIPEI_TIMEZONE)
    as_of = datetime.fromisoformat(observed['asOf']) if observed else None
    age = (current - as_of).total_seconds() if as_of else None
    return {**observed, 'timestampMs': int(as_of.timestamp() * 1000) if as_of else None,
            'ageSeconds': round(age, 1) if age is not None else None,
            'stale': as_of is None or as_of.date() != current.date() or age < -5}


def twse_mis_stock_quote(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    """讀取 MIS 真實成交；z 缺值時採 trade.z，絕不以委買賣推估。"""
    def number(value: Any) -> float | None:
        try:
            value = float(str(value).replace(',', ''))
            return value if math.isfinite(value) and value > 0 else None
        except (TypeError, ValueError):
            return None

    observation = twse_mis_observation(row)
    if not observation:
        return None
    snapshot = datetime.fromisoformat(observation['asOf'])
    field, price, traded = 'z', number(row.get('z')), snapshot
    if price is None:
        trade = row.get('trade') if isinstance(row.get('trade'), dict) else {}
        field, price = 'trade.z', number(trade.get('z'))
        # trade.t 是成交時間，tlong 則可能只是較晚的委託簿更新時間。
        try:
            traded = datetime.strptime(snapshot.strftime('%Y%m%d') + str(trade.get('t')), '%Y%m%d%H:%M:%S').replace(tzinfo=TAIPEI_TIMEZONE)
        except ValueError:
            return None
        if traded > snapshot:
            return None
    if price is None:
        return None
    previous = number(row.get('y'))
    out = {'ok': True, 'code': str(row.get('c') or ''), 'name': row.get('n'),
           'price': price, 'prevClose': previous,
           'changePct': (price - previous) / previous * 100 if previous else None,
           'open': number(row.get('o')), 'high': number(row.get('h')), 'low': number(row.get('l')),
           'source': 'twse-mis', 'priceField': field, 'time': traded.strftime('%H:%M:%S')}
    out.update(quote_observation(traded.timestamp() * 1000, now))
    out['priceRealtime'] = not out['stale']
    out.update(cumulative_volume_contract(row.get('v'), source_unit='lot', source='twse-mis', timestamp_ms=snapshot.timestamp() * 1000))
    return out


def guard_tw_quote(raw: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """盤中拒絕昨日或時間不明的價格，所有 HTTP 消費者共用此防線。"""
    out = dict(raw)
    current = (now or datetime.now(TAIPEI_TIMEZONE)).astimezone(TAIPEI_TIMEZONE)
    out.update(quote_observation(out.get('timestampMs'), current))
    regular = current.weekday() < 5 and 540 <= current.hour * 60 + current.minute <= 810
    if out['stale'] and regular:
        out.update(ok=False, lastKnownPrice=out.get('price') or out.get('lastKnownPrice'), price=None, change=None,
                   changePct=None, priceRealtime=False, quoteStatus='stale',
                   message='成交資料尚未更新，暫不提供今日價格與漲跌')
    else:
        out['quoteStatus'] = 'last_trade' if out.get('source') == 'twse-mis' else 'delayed'
    return out


def twse_mis_observation(row: dict[str, Any] | None) -> dict[str, str]:
    """保留 TWSE MIS 的市場時間；來源缺值時不可用抓取時間替代。"""
    row = row or {}
    observed: datetime | None = None
    raw_epoch = str(row.get('tlong') or '').strip()
    if raw_epoch:
        try:
            epoch = float(raw_epoch)
            if epoch > 10_000_000_000:
                epoch /= 1000.0
            candidate = datetime.fromtimestamp(epoch, timezone.utc)
            if 2000 <= candidate.year <= 2100:
                observed = candidate.astimezone(TAIPEI_TIMEZONE)
        except (OSError, OverflowError, TypeError, ValueError):
            observed = None
    if observed is None:
        raw_date = ''.join(ch for ch in str(row.get('d') or '') if ch.isdigit())
        raw_time = str(row.get('t') or '').strip()
        if len(raw_date) == 8 and raw_time:
            compact_time = ''.join(ch for ch in raw_time if ch.isdigit())
            if len(compact_time) >= 6:
                try:
                    observed = datetime.strptime(
                        raw_date + compact_time[:6], '%Y%m%d%H%M%S'
                    ).replace(tzinfo=TAIPEI_TIMEZONE)
                except ValueError:
                    observed = None
    if observed is None:
        return {}
    return {
        'asOf': observed.isoformat(),
        'tradeDate': observed.date().isoformat(),
    }


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
