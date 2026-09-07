#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only OHLC bar ledger with point-in-time (PIT) availability helpers.

Historical rows are never rewritten in place. Corporate-action / adjustment
restatements append a new ``generation_id`` while prior generations remain
queryable for audit and backtests.

This module does **not** write DecisionContext or EvidencePack payloads.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEDGER_DIR = os.path.join(_BASE, 'data', 'ohlc_ledger')
DB_PATH = os.path.join(LEDGER_DIR, 'ohlc_ledger.db')

SCHEMA_VERSION = 1
DEFAULT_GENERATION_ID = 'gen-initial'
PRICE_BASIS_VALUES = frozenset({'unadj_close', 'adj_close'})

_WRITE_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlc_bars(
  symbol TEXT NOT NULL,
  session_date TEXT NOT NULL,
  price_basis TEXT NOT NULL CHECK(price_basis IN ('unadj_close','adj_close')),
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  source TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  generation_id TEXT NOT NULL,
  PRIMARY KEY(symbol, session_date, price_basis, generation_id)
);
CREATE INDEX IF NOT EXISTS idx_ohlc_bars_symbol_session
  ON ohlc_bars(symbol, session_date);
CREATE INDEX IF NOT EXISTS idx_ohlc_bars_ingested
  ON ohlc_bars(ingested_at);
"""


@dataclass(frozen=True, slots=True)
class OhlcBar:
    symbol: str
    session_date: str
    price_basis: str
    open: float
    high: float
    low: float
    close: float
    source: str
    ingested_at: str
    generation_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            'symbol': self.symbol,
            'sessionDate': self.session_date,
            'priceBasis': self.price_basis,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'source': self.source,
            'ingestedAt': self.ingested_at,
            'generationId': self.generation_id,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str) -> datetime:
    raw = str(value or '').strip()
    if not raw:
        raise ValueError('timestamp is required')
    parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_session_date(value: str) -> str:
    raw = str(value or '').strip()
    if not raw:
        raise ValueError('session_date is required')
    if len(raw) == 10 and raw[4] == '-' and raw[7] == '-':
        date.fromisoformat(raw)
        return raw
    if raw.isdigit() and len(raw) == 8:
        return f'{raw[0:4]}-{raw[4:6]}-{raw[6:8]}'
    raise ValueError(f'invalid session_date: {value}')


def _finite_price(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} must be a finite number') from exc
    if number != number or number in (float('inf'), float('-inf')):
        raise ValueError(f'{field} must be a finite number')
    if number <= 0:
        raise ValueError(f'{field} must be positive')
    return number


def _normalize_price_basis(value: str) -> str:
    basis = str(value or '').strip()
    if basis not in PRICE_BASIS_VALUES:
        raise ValueError(f'price_basis must be one of {sorted(PRICE_BASIS_VALUES)}')
    return basis


def _ledger_db_path(base_dir: str | os.PathLike[str] | None = None) -> str:
    if base_dir is None:
        return DB_PATH
    return os.path.join(os.fspath(base_dir), 'data', 'ohlc_ledger', 'ohlc_ledger.db')


def get_conn(base_dir: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = _ledger_db_path(base_dir)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def init_db(base_dir: str | os.PathLike[str] | None = None) -> None:
    with _WRITE_LOCK:
        with closing(get_conn(base_dir)) as conn:
            with conn:
                conn.executescript(_SCHEMA)
                conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')


def _row_to_bar(row: sqlite3.Row | Mapping[str, Any]) -> OhlcBar:
    getter = row.__getitem__ if hasattr(row, '__getitem__') else row.get
    return OhlcBar(
        symbol=str(getter('symbol')),
        session_date=str(getter('session_date')),
        price_basis=str(getter('price_basis')),
        open=float(getter('open')),
        high=float(getter('high')),
        low=float(getter('low')),
        close=float(getter('close')),
        source=str(getter('source')),
        ingested_at=str(getter('ingested_at')),
        generation_id=str(getter('generation_id')),
    )


def _utc_iso(value: str) -> str:
    return _parse_iso_datetime(value).isoformat()


def normalize_bar(
    bar: Mapping[str, Any],
    *,
    default_generation_id: str = DEFAULT_GENERATION_ID,
    default_ingested_at: str | None = None,
) -> OhlcBar:
    """Validate and normalize one incoming bar record."""
    symbol = str(bar.get('symbol') or '').strip()
    if not symbol:
        raise ValueError('symbol is required')
    session_date = _parse_session_date(bar.get('session_date') or bar.get('sessionDate') or '')
    price_basis = _normalize_price_basis(bar.get('price_basis') or bar.get('priceBasis') or 'unadj_close')
    open_px = _finite_price(bar.get('open'), 'open')
    high_px = _finite_price(bar.get('high'), 'high')
    low_px = _finite_price(bar.get('low'), 'low')
    close_px = _finite_price(bar.get('close'), 'close')
    if low_px > min(open_px, close_px) or high_px < max(open_px, close_px):
        raise ValueError('high/low must bracket open and close')
    source = str(bar.get('source') or '').strip()
    if not source:
        raise ValueError('source is required')
    ingested_at = _utc_iso(str(bar.get('ingested_at') or bar.get('ingestedAt') or default_ingested_at or _utc_now_iso()))
    generation_id = str(bar.get('generation_id') or bar.get('generationId') or default_generation_id).strip()
    if not generation_id:
        raise ValueError('generation_id is required')
    return OhlcBar(
        symbol=symbol,
        session_date=session_date,
        price_basis=price_basis,
        open=open_px,
        high=high_px,
        low=low_px,
        close=close_px,
        source=source,
        ingested_at=ingested_at,
        generation_id=generation_id,
    )


def availability_predicate(
    bar: OhlcBar | Mapping[str, Any],
    *,
    as_of: str,
    knowledge_cutoff: str,
) -> bool:
    """Return True when the bar is knowable at ``knowledge_cutoff`` for ``as_of``.

    Availability foundation (st-peak-v0.1 §6):
      - ``session_date <= as_of``  (no future session bars)
      - ``ingested_at <= knowledge_cutoff``  (no lookahead ingestion)
    """
    record = _row_to_bar(bar) if isinstance(bar, Mapping) else bar
    as_of_date = _parse_session_date(as_of)
    cutoff = _parse_iso_datetime(knowledge_cutoff)
    ingested = _parse_iso_datetime(record.ingested_at)
    return record.session_date <= as_of_date and ingested <= cutoff


def filter_bars_pit(
    bars: Sequence[OhlcBar | Mapping[str, Any]],
    *,
    as_of: str,
    knowledge_cutoff: str,
) -> list[OhlcBar]:
    """Pure in-memory PIT filter over bar rows."""
    out: list[OhlcBar] = []
    for bar in bars:
        record = _row_to_bar(bar) if isinstance(bar, Mapping) else bar
        if availability_predicate(record, as_of=as_of, knowledge_cutoff=knowledge_cutoff):
            out.append(record)
    out.sort(key=lambda row: (row.session_date, row.ingested_at, row.generation_id))
    return out


def _dedupe_latest_generation(rows: Sequence[OhlcBar]) -> list[OhlcBar]:
    """Keep the latest ingested row per (symbol, session_date, price_basis)."""
    latest: dict[tuple[str, str, str], OhlcBar] = {}
    for row in rows:
        key = (row.symbol, row.session_date, row.price_basis)
        current = latest.get(key)
        if current is None:
            latest[key] = row
            continue
        current_ingested = _parse_iso_datetime(current.ingested_at)
        candidate_ingested = _parse_iso_datetime(row.ingested_at)
        if candidate_ingested > current_ingested:
            latest[key] = row
        elif candidate_ingested == current_ingested and row.generation_id > current.generation_id:
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def append_bars(
    bars: Iterable[Mapping[str, Any]],
    *,
    generation_id: str | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, int]:
    """Append bars to the ledger.

    Duplicate policy:
      - Primary key is ``(symbol, session_date, price_basis, generation_id)``.
      - Re-appending the same key is a no-op (``ignored`` counter increments).
      - Adjustment restatements must use a **new** ``generation_id``; old rows stay.
    """
    init_db(base_dir)
    gen = str(generation_id or DEFAULT_GENERATION_ID).strip() or DEFAULT_GENERATION_ID
    inserted = ignored = rejected = 0
    with _WRITE_LOCK:
        with closing(get_conn(base_dir)) as conn:
            with conn:
                for raw in bars:
                    try:
                        record = normalize_bar(raw, default_generation_id=gen)
                    except ValueError:
                        rejected += 1
                        continue
                    cursor = conn.execute(
                        '''INSERT OR IGNORE INTO ohlc_bars
                           (symbol,session_date,price_basis,open,high,low,close,source,ingested_at,generation_id)
                           VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (
                            record.symbol,
                            record.session_date,
                            record.price_basis,
                            record.open,
                            record.high,
                            record.low,
                            record.close,
                            record.source,
                            record.ingested_at,
                            record.generation_id,
                        ),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        ignored += 1
    return {'inserted': inserted, 'ignored': ignored, 'rejected': rejected}


def query_bars(
    symbol: str,
    *,
    price_basis: str = 'unadj_close',
    generation_id: str | None = None,
    session_from: str | None = None,
    session_to: str | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[OhlcBar]:
    """Load raw ledger rows without PIT filtering."""
    init_db(base_dir)
    basis = _normalize_price_basis(price_basis)
    clauses = ['symbol = ?', 'price_basis = ?']
    params: list[Any] = [symbol, basis]
    if generation_id is not None:
        clauses.append('generation_id = ?')
        params.append(str(generation_id))
    if session_from is not None:
        clauses.append('session_date >= ?')
        params.append(_parse_session_date(session_from))
    if session_to is not None:
        clauses.append('session_date <= ?')
        params.append(_parse_session_date(session_to))
    sql = (
        'SELECT symbol,session_date,price_basis,open,high,low,close,source,ingested_at,generation_id '
        f'FROM ohlc_bars WHERE {" AND ".join(clauses)} ORDER BY session_date ASC, ingested_at ASC'
    )
    with closing(get_conn(base_dir)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_bar(row) for row in rows]


def query_bars_pit(
    symbol: str,
    *,
    as_of: str,
    knowledge_cutoff: str,
    price_basis: str = 'unadj_close',
    generation_id: str | None = None,
    latest_generation: bool = True,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[OhlcBar]:
    """Query bars visible at a point in time.

    When ``generation_id`` is omitted and ``latest_generation`` is True, rows that
    share the same ``(symbol, session_date, price_basis)`` collapse to the latest
    ``ingested_at`` that is still ``<= knowledge_cutoff``.
    """
    init_db(base_dir)
    basis = _normalize_price_basis(price_basis)
    as_of_date = _parse_session_date(as_of)
    cutoff = _utc_iso(knowledge_cutoff)
    clauses = [
        'symbol = ?',
        'price_basis = ?',
        'session_date <= ?',
        'ingested_at <= ?',
    ]
    params: list[Any] = [symbol, basis, as_of_date, cutoff]
    if generation_id is not None:
        clauses.append('generation_id = ?')
        params.append(str(generation_id))
    sql = (
        'SELECT symbol,session_date,price_basis,open,high,low,close,source,ingested_at,generation_id '
        f'FROM ohlc_bars WHERE {" AND ".join(clauses)} ORDER BY session_date ASC, ingested_at ASC'
    )
    with closing(get_conn(base_dir)) as conn:
        rows = conn.execute(sql, params).fetchall()
    bars = [_row_to_bar(row) for row in rows]
    if generation_id is not None or not latest_generation:
        return bars
    return _dedupe_latest_generation(bars)


def new_generation_id(prefix: str = 'gen') -> str:
    """Allocate a fresh generation id for adjustment rewrites."""
    return f'{prefix}-{uuid.uuid4().hex}'


def bars_from_yahoo_chart(
    payload: Mapping[str, Any],
    symbol: str,
    *,
    price_basis: str = 'unadj_close',
    source: str = 'yahoo/v8-chart',
) -> list[dict[str, Any]]:
    """Convert a Yahoo v8 chart payload into ledger-ready bar dicts.

    ``unadj_close`` uses raw quote OHLC. ``adj_close`` scales open/high/low by
    ``adjClose / close`` and stores adjusted close from Yahoo adjclose series.
    """
    basis = _normalize_price_basis(price_basis)
    chart = (payload or {}).get('chart') or {}
    results = chart.get('result') or []
    if not results:
        raise ValueError(f'Yahoo chart unavailable for {symbol}')
    result = results[0] or {}
    timestamps = result.get('timestamp') or []
    indicators = result.get('indicators') or {}
    quote_rows = indicators.get('quote') or []
    if not quote_rows:
        raise ValueError(f'quote series unavailable for {symbol}')
    quote = quote_rows[0] or {}
    adj_rows = (indicators.get('adjclose') or [{}])[0] or {}
    adjclose = adj_rows.get('adjclose') or []
    opens = quote.get('open') or []
    highs = quote.get('high') or []
    lows = quote.get('low') or []
    closes = quote.get('close') or []
    meta = result.get('meta') or {}
    exchange_tz = meta.get('exchangeTimezoneName') or 'UTC'
    out: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        raw_close = closes[index] if index < len(closes) else None
        if raw_close is None or float(raw_close) <= 0:
            continue
        raw_open = opens[index] if index < len(opens) else raw_close
        raw_high = highs[index] if index < len(highs) else raw_close
        raw_low = lows[index] if index < len(lows) else raw_close
        if basis == 'adj_close':
            adjusted_close = adjclose[index] if index < len(adjclose) else None
            if adjusted_close is None or float(adjusted_close) <= 0:
                continue
            factor = float(adjusted_close) / float(raw_close)
            open_px = float(raw_open) * factor
            high_px = float(raw_high) * factor
            low_px = float(raw_low) * factor
            close_px = float(adjusted_close)
        else:
            open_px = float(raw_open)
            high_px = float(raw_high)
            low_px = float(raw_low)
            close_px = float(raw_close)
        session_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        try:
            from zoneinfo import ZoneInfo
            session_date = session_date.astimezone(ZoneInfo(str(exchange_tz)))
        except Exception:
            pass
        out.append({
            'symbol': symbol,
            'session_date': session_date.date().isoformat(),
            'price_basis': basis,
            'open': open_px,
            'high': high_px,
            'low': low_px,
            'close': close_px,
            'source': source,
        })
    return out


def ingest_yahoo_chart_payload(
    payload: Mapping[str, Any],
    symbol: str,
    *,
    price_basis: str = 'unadj_close',
    generation_id: str | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, int]:
    """Parse Yahoo chart JSON and append bars when the ledger write path is enabled."""
    from feature_settings import is_enabled

    if not is_enabled('ohlcLedger', base_dir):
        return {'inserted': 0, 'ignored': 0, 'rejected': 0, 'enabled': False}
    bars = bars_from_yahoo_chart(payload, symbol, price_basis=price_basis)
    result = append_bars(bars, generation_id=generation_id, base_dir=base_dir)
    result['enabled'] = True
    return result
