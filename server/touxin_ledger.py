#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append-only 投信 (trust) daily ledger with point-in-time (PIT) helpers.

Rows are never updated in place. See ``docs/ST_TOUXIN_5D_NETBUY.md``.

This module does **not** write DecisionContext or EvidencePack payloads.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEDGER_DIR = os.path.join(_BASE, 'data', 'touxin_ledger')
DB_PATH = os.path.join(LEDGER_DIR, 'touxin_ledger.db')
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')

SCHEMA_VERSION = 1
_WRITE_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS touxin_daily(
  symbol TEXT NOT NULL,
  session_date TEXT NOT NULL,
  trust_net_shares REAL NOT NULL,
  volume_shares REAL,
  source TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  PRIMARY KEY(symbol, session_date, source)
);
CREATE INDEX IF NOT EXISTS idx_touxin_symbol_session
  ON touxin_daily(symbol, session_date);
CREATE INDEX IF NOT EXISTS idx_touxin_ingested
  ON touxin_daily(ingested_at);
"""


@dataclass(frozen=True, slots=True)
class TouxinRow:
    symbol: str
    session_date: str
    trust_net_shares: float
    volume_shares: float | None
    source: str
    ingested_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            'symbol': self.symbol,
            'sessionDate': self.session_date,
            'trustNetShares': self.trust_net_shares,
            'volumeShares': self.volume_shares,
            'source': self.source,
            'ingestedAt': self.ingested_at,
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


def _finite_number(value: Any, field: str, *, allow_negative: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} must be a finite number') from exc
    if number != number or number in (float('inf'), float('-inf')):
        raise ValueError(f'{field} must be a finite number')
    if not allow_negative and number < 0:
        raise ValueError(f'{field} must be non-negative')
    return number


def _ledger_db_path(base_dir: str | os.PathLike[str] | None = None) -> str:
    if base_dir is None:
        return DB_PATH
    return os.path.join(os.fspath(base_dir), 'data', 'touxin_ledger', 'touxin_ledger.db')


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


def _row_to_record(row: sqlite3.Row | Mapping[str, Any]) -> TouxinRow:
    getter = row.__getitem__ if hasattr(row, '__getitem__') else row.get
    vol = getter('volume_shares')
    return TouxinRow(
        symbol=str(getter('symbol')),
        session_date=str(getter('session_date')),
        trust_net_shares=float(getter('trust_net_shares')),
        volume_shares=float(vol) if vol is not None else None,
        source=str(getter('source')),
        ingested_at=str(getter('ingested_at')),
    )


def normalize_row(
    row: Mapping[str, Any],
    *,
    default_ingested_at: str | None = None,
) -> TouxinRow:
    symbol = str(row.get('symbol') or '').strip().upper()
    if not symbol:
        raise ValueError('symbol is required')
    session_date = _parse_session_date(
        row.get('session_date') or row.get('sessionDate') or ''
    )
    trust = _finite_number(
        row.get('trust_net_shares') or row.get('trustNetShares'),
        'trust_net_shares',
        allow_negative=True,
    )
    vol_raw = row.get('volume_shares') if 'volume_shares' in row else row.get('volumeShares')
    volume = None
    if vol_raw is not None:
        volume = _finite_number(vol_raw, 'volume_shares', allow_negative=False)
    source = str(row.get('source') or '').strip()
    if not source:
        raise ValueError('source is required')
    ingested_at = str(
        row.get('ingested_at') or row.get('ingestedAt') or default_ingested_at or _utc_now_iso()
    )
    _parse_iso_datetime(ingested_at)
    return TouxinRow(
        symbol=symbol,
        session_date=session_date,
        trust_net_shares=trust,
        volume_shares=volume,
        source=source,
        ingested_at=ingested_at,
    )


def availability_predicate(
    row: TouxinRow | Mapping[str, Any],
    *,
    as_of: str,
    knowledge_cutoff: str,
) -> bool:
    record = _row_to_record(row) if isinstance(row, Mapping) else row
    as_of_date = _parse_session_date(as_of)
    cutoff = _parse_iso_datetime(knowledge_cutoff)
    ingested = _parse_iso_datetime(record.ingested_at)
    return record.session_date <= as_of_date and ingested <= cutoff


def filter_rows_pit(
    rows: Sequence[TouxinRow | Mapping[str, Any]],
    *,
    as_of: str,
    knowledge_cutoff: str,
) -> list[TouxinRow]:
    out: list[TouxinRow] = []
    for row in rows:
        record = _row_to_record(row) if isinstance(row, Mapping) else row
        if availability_predicate(record, as_of=as_of, knowledge_cutoff=knowledge_cutoff):
            out.append(record)
    out.sort(key=lambda r: (r.session_date, r.ingested_at, r.source))
    return out


def _dedupe_latest_source(rows: Sequence[TouxinRow]) -> list[TouxinRow]:
    latest: dict[tuple[str, str], TouxinRow] = {}
    for row in rows:
        key = (row.symbol, row.session_date)
        current = latest.get(key)
        if current is None:
            latest[key] = row
            continue
        if _parse_iso_datetime(row.ingested_at) >= _parse_iso_datetime(current.ingested_at):
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def append_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    base_dir: str | os.PathLike[str] | None = None,
    default_ingested_at: str | None = None,
) -> int:
    """Append ledger rows; duplicate primary keys are ignored."""
    init_db(base_dir)
    normalized = [
        normalize_row(row, default_ingested_at=default_ingested_at)
        for row in rows
    ]
    if not normalized:
        return 0
    inserted = 0
    with _WRITE_LOCK:
        with closing(get_conn(base_dir)) as conn:
            with conn:
                for row in normalized:
                    cur = conn.execute(
                        'INSERT OR IGNORE INTO touxin_daily '
                        '(symbol, session_date, trust_net_shares, volume_shares, source, ingested_at) '
                        'VALUES (?, ?, ?, ?, ?, ?)',
                        (
                            row.symbol,
                            row.session_date,
                            row.trust_net_shares,
                            row.volume_shares,
                            row.source,
                            row.ingested_at,
                        ),
                    )
                    inserted += cur.rowcount
    return inserted


def query_rows_pit(
    symbol: str | None = None,
    *,
    as_of: str,
    knowledge_cutoff: str,
    base_dir: str | os.PathLike[str] | None = None,
) -> list[TouxinRow]:
    """Return PIT-visible rows, optionally filtered by symbol."""
    init_db(base_dir)
    as_of_date = _parse_session_date(as_of)
    cutoff = _parse_iso_datetime(knowledge_cutoff)
    params: list[Any] = [as_of_date, cutoff.isoformat()]
    where = 'session_date <= ? AND ingested_at <= ?'
    if symbol:
        where += ' AND symbol = ?'
        params.append(str(symbol).strip().upper())
    with closing(get_conn(base_dir)) as conn:
        rows = conn.execute(
            f'SELECT symbol, session_date, trust_net_shares, volume_shares, source, ingested_at '
            f'FROM touxin_daily WHERE {where} ORDER BY symbol, session_date, ingested_at',
            params,
        ).fetchall()
    pit = filter_rows_pit(
        [_row_to_record(r) for r in rows],
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
    )
    return _dedupe_latest_source(pit)


def ingest_chip_history_file(
    path: str,
    *,
    source: str = 'chip_history/T86',
    ingested_at: str | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> int:
    """Adapter: append trust_net_shares from one chip_history daily snapshot."""
    base = os.path.basename(path)
    raw_day = base.replace('.json', '')
    if len(raw_day) == 8 and raw_day.isdigit():
        session_date = f'{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}'
    else:
        session_date = _parse_session_date(raw_day)
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return 0
    ingested = ingested_at or _utc_now_iso()
    rows: list[dict[str, Any]] = []
    for code, rec in payload.items():
        if not isinstance(rec, dict):
            continue
        trust = rec.get('trust')
        if trust is None:
            continue
        rows.append({
            'symbol': str(code).strip().upper(),
            'session_date': session_date,
            'trust_net_shares': float(trust),
            'volume_shares': rec.get('volume'),
            'source': source,
            'ingested_at': ingested,
        })
    return append_rows(rows, base_dir=base_dir, default_ingested_at=ingested)


def load_chip_history_fallback(
    symbol: str,
    *,
    as_of: str,
    window: int = 5,
    chip_history_path: str = CHIP_HISTORY_PATH,
) -> list[TouxinRow]:
    """Build in-memory rows from chip_history JSON snapshots (no PIT audit)."""
    code = str(symbol or '').strip().upper()
    if not os.path.isdir(chip_history_path):
        return []
    files = sorted(
        f for f in os.listdir(chip_history_path)
        if f.endswith('.json')
    )
    sessions: list[tuple[str, dict[str, Any]]] = []
    for fn in files:
        raw_day = fn.replace('.json', '')
        if len(raw_day) == 8 and raw_day.isdigit():
            day = f'{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}'
        else:
            day = raw_day[:10]
        if day > _parse_session_date(as_of):
            continue
        try:
            with open(os.path.join(chip_history_path, fn), encoding='utf-8') as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        rec = (payload or {}).get(code)
        if isinstance(rec, dict) and rec.get('trust') is not None:
            sessions.append((day, rec))
    sessions.sort(key=lambda pair: pair[0])
    tail = sessions[-window:]
    out: list[TouxinRow] = []
    for day, rec in tail:
        vol = rec.get('volume')
        out.append(TouxinRow(
            symbol=code,
            session_date=day,
            trust_net_shares=float(rec['trust']),
            volume_shares=float(vol) if vol is not None else None,
            source='chip_history/snapshot',
            ingested_at=f'{day}T13:30:00+08:00',
        ))
    return out
