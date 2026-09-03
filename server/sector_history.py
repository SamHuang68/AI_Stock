#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent TWSE sector-index history for auditable RS20 calculations."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import sector_flow


_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, 'data', 'sector_history.db')
_URLS = (
    'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date}&type=IND&response=json',
    'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={date}&type=IND&response=json',
)
_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}


def _date_key(value: Any) -> str | None:
    text = str(value or '').strip().replace('-', '').replace('/', '')
    return text if len(text) == 8 and text.isdigit() else None


def _init(path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS sector_daily('
                         'date TEXT NOT NULL, sector TEXT NOT NULL, close REAL NOT NULL, '
                         'source TEXT, fetched_at INTEGER, PRIMARY KEY(date,sector))')


def store_snapshot(as_of: Any, sectors: Iterable[dict[str, Any]] | None, path: str = DB_PATH) -> int:
    day = _date_key(as_of)
    if not day:
        return 0
    rows = []
    for raw in sectors or []:
        if not isinstance(raw, dict):
            continue
        key = sector_flow.normalize_sector_name(raw.get('sector') or raw.get('name'))
        close = sector_flow._number(raw.get('close'))
        if key and close is not None and close > 0:
            rows.append((day, key, close, raw.get('source') or 'TWSE MI_INDEX IND', int(time.time())))
    if not rows:
        return 0
    _init(path)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        with conn:
            conn.executemany('INSERT OR REPLACE INTO sector_daily(date,sector,close,source,fetched_at) '
                             'VALUES(?,?,?,?,?)', rows)
    return len(rows)


def available_dates(path: str = DB_PATH) -> list[str]:
    if not os.path.exists(path):
        return []
    _init(path)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        return [str(row[0]) for row in conn.execute(
            'SELECT DISTINCT date FROM sector_daily ORDER BY date DESC').fetchall()]


def return20_by_sector(path: str = DB_PATH) -> dict[str, float]:
    dates = available_dates(path)[:21]
    if len(dates) < 21:
        return {}
    latest, oldest = dates[0], dates[-1]
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        cur = conn.execute('SELECT date,sector,close FROM sector_daily WHERE date IN (?,?)', (latest, oldest))
        values: dict[str, dict[str, float]] = {}
        for day, sector, close in cur.fetchall():
            values.setdefault(str(sector), {})[str(day)] = float(close)
    out = {}
    for sector, pair in values.items():
        start, end = pair.get(oldest), pair.get(latest)
        if start and end:
            out[sector] = round((end / start - 1.0) * 100.0, 4)
    return out


def benchmark_return20(bars: Iterable[dict[str, Any]] | None) -> float | None:
    closes = []
    for row in bars or []:
        if not isinstance(row, dict):
            continue
        close = sector_flow._number(row.get('close', row.get('Close')))
        if close is not None and close > 0:
            closes.append(close)
    if len(closes) < 21:
        return None
    closes = closes[-21:]
    return (closes[-1] / closes[0] - 1.0) * 100.0


def _fetch_snapshot(day: str, path: str, timeout: float = 5.0) -> int:
    from pulse_extras import parse_sector_tables
    for template in _URLS:
        try:
            req = urllib.request.Request(template.format(date=day), headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read())
            rows = parse_sector_tables(payload)
            if rows:
                return store_snapshot(day, rows, path)
        except Exception:
            continue
    return 0


def bootstrap_history(
    as_of: Any,
    *,
    path: str = DB_PATH,
    budget_seconds: float = 4.0,
    max_workers: int = 10,
) -> dict[str, Any]:
    """One-time bounded bootstrap; successful dates persist and later refreshes are cache-only."""
    day = _date_key(as_of)
    if not day:
        return {'attempted': 0, 'completed': 0, 'dates': len(available_dates(path))}
    base = datetime.strptime(day, '%Y%m%d').date()
    existing = set(available_dates(path))
    if len([d for d in existing if d <= day]) >= 21:
        return {'attempted': 0, 'completed': 0, 'dates': len(existing)}
    candidates = []
    for offset in range(1, 50):
        d = base - timedelta(days=offset)
        key = d.strftime('%Y%m%d')
        if d.weekday() < 5 and key not in existing:
            candidates.append(key)
        if len(candidates) >= 32:
            break
    executor = ThreadPoolExecutor(max_workers=max(2, min(max_workers, 12)), thread_name_prefix='sector-rs20')
    futures = [executor.submit(_fetch_snapshot, key, path) for key in candidates]
    done, _ = wait(futures, timeout=max(0.5, float(budget_seconds)))
    completed = sum(1 for future in done if not future.exception() and (future.result() or 0) > 0)
    executor.shutdown(wait=False, cancel_futures=True)
    return {'attempted': len(candidates), 'completed': completed, 'dates': len(available_dates(path))}


def enrich_sector_rows(
    sectors: Iterable[dict[str, Any]] | None,
    *,
    as_of: Any,
    benchmark_bars: Iterable[dict[str, Any]] | None = None,
    industry_turnover_yi: dict[str, Any] | None = None,
    path: str = DB_PATH,
    bootstrap: bool = True,
    budget_seconds: float = 4.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [dict(row) for row in (sectors or []) if isinstance(row, dict)]
    stored = store_snapshot(as_of, rows, path)
    before = len(available_dates(path))
    boot = {'attempted': 0, 'completed': 0, 'dates': before}
    if bootstrap and before < 21:
        boot = bootstrap_history(as_of, path=path, budget_seconds=budget_seconds)
    returns = return20_by_sector(path)
    # Prefer the TAIEX close carried in the very same MI_INDEX snapshots.  This keeps
    # sector return and benchmark on identical sessions/source; local ^TWII bars are
    # only a labelled fallback when the official history cache is still incomplete.
    benchmark_key = sector_flow.normalize_sector_name('發行量加權股價指數')
    benchmark = returns.get(benchmark_key)
    benchmark_source = 'TWSE MI_INDEX IND 發行量加權股價 daily close'
    if benchmark is None:
        benchmark = benchmark_return20(benchmark_bars)
        benchmark_source = 'local ^TWII daily bars fallback' if benchmark is not None else None
    enriched = sector_flow.attach_sector_metrics(
        rows, industry_turnover_yi=industry_turnover_yi, return20_by_sector=returns)
    status = {
        'storedRows': stored,
        'historyDates': len(available_dates(path)),
        'rs20Available': bool(returns) and benchmark is not None,
        'benchmarkReturn20Pct': round(benchmark, 4) if benchmark is not None else None,
        'benchmarkSource': benchmark_source,
        'bootstrap': boot,
        'source': 'TWSE MI_INDEX IND daily close',
    }
    return enriched, status
