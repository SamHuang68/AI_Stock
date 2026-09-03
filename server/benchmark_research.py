#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical research-only benchmark series not already present in market.db.

The first contract is the official TWSE Taiwan 50 price and total-return index.
Request paths only read the local cache.  A bounded daemon refresh may update
that cache in the background, so DecisionContext never waits on a multi-month
network backfill and no UI module creates its own data source.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

from atomic_store import atomic_write_text


if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TAI50_CSV = os.path.join(_BASE, 'data', 'tai50_daily.csv')
SOURCE = 'TWSE OpenAPI indicesReport/TAI50I'
CURRENT_URL = 'https://openapi.twse.com.tw/v1/indicesReport/TAI50I'
HISTORY_URL = 'https://www.twse.com.tw/indicesReport/TAI50I'
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/5.0; +local)',
    'Accept': 'application/json,text/plain,*/*',
}
_lock = threading.RLock()
_refresh_thread: threading.Thread | None = None
_status: dict[str, Any] = {
    'running': False, 'lastSuccess': None, 'lastError': None, 'rows': 0,
    'failedMonths': [],
}


def _number(value: Any) -> float | None:
    try:
        value = float(str(value).replace(',', '').strip())
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _date_to_iso(value: Any) -> str | None:
    raw = str(value or '').strip().replace('-', '/').replace('.', '/')
    try:
        if '/' in raw:
            parts = raw.split('/')
            if len(parts) != 3:
                return None
            year, month, day = map(int, parts)
            if year < 1911:
                year += 1911
            return date(year, month, day).isoformat()
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if len(digits) == 7:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])).isoformat()
        if len(digits) == 8:
            year = int(digits[:4])
            if year < 1911:
                year += 1911
            return date(year, int(digits[4:6]), int(digits[6:8])).isoformat()
    except (TypeError, ValueError):
        return None
    return None


def parse_tai50_payload(payload: Any) -> list[dict[str, Any]]:
    """Normalize current OpenAPI rows and historical TWSE report rows."""
    source_rows: list[Any] = []
    if isinstance(payload, list):
        source_rows = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get('data'), list):
            source_rows = payload.get('data') or []
        elif isinstance(payload.get('tables'), list):
            tables = payload.get('tables') or []
            source_rows = ((tables[0] or {}).get('data') if tables else []) or []
    out: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if isinstance(row, dict):
            iso = _date_to_iso(row.get('Date') or row.get('date') or row.get('日期'))
            price = _number(row.get('Taiwan50Index') or row.get('priceIndex') or row.get('臺灣50指數'))
            total = _number(row.get('Taiwan50TotalReturnIndex') or row.get('totalReturnIndex') or row.get('臺灣50報酬指數'))
        elif isinstance(row, (list, tuple)) and len(row) >= 3:
            iso = _date_to_iso(row[0])
            price = _number(row[1])
            total = _number(row[2])
        else:
            continue
        if iso and price is not None and total is not None:
            out[iso] = {'date': iso, 'priceIndex': price, 'totalReturnIndex': total}
    return [out[key] for key in sorted(out)]


def _read_rows(path: str = TAI50_CSV) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                iso = _date_to_iso(row.get('date'))
                price = _number(row.get('priceIndex'))
                total = _number(row.get('totalReturnIndex'))
                if iso and price is not None and total is not None:
                    rows.append({'date': iso, 'priceIndex': price, 'totalReturnIndex': total})
    except OSError:
        return []
    by_date = {row['date']: row for row in rows}
    return [by_date[key] for key in sorted(by_date)]


def _write_rows(rows: list[dict[str, Any]], path: str = TAI50_CSV) -> None:
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['date', 'priceIndex', 'totalReturnIndex'], lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({
            'date': row['date'],
            'priceIndex': f"{float(row['priceIndex']):.4f}",
            'totalReturnIndex': f"{float(row['totalReturnIndex']):.4f}",
        })
    atomic_write_text(path, stream.getvalue(), backup=True, private=False)


def _http_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8-sig', 'replace'))


def _fetch_current() -> list[dict[str, Any]]:
    return parse_tai50_payload(_http_json(CURRENT_URL))


def _fetch_month(year: int, month: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({'date': f'{year:04d}{month:02d}01', 'response': 'json'})
    return parse_tai50_payload(_http_json(f'{HISTORY_URL}?{query}'))


def refresh(years: int = 6, *, today: date | None = None, path: str = TAI50_CSV) -> dict[str, Any]:
    """Refresh current month or bootstrap a bounded multi-year official cache."""
    today = today or date.today()
    with _lock:
        by_date = {row['date']: row for row in _read_rows(path)}
    failed_months: list[str] = []
    attempted_months = 0
    if years > 0:
        start = date(today.year - max(1, min(int(years), 12)), today.month, 1)
        cursor = start
        while cursor <= today:
            attempted_months += 1
            try:
                for row in _fetch_month(cursor.year, cursor.month):
                    by_date[row['date']] = row
            except Exception as exc:
                failed_months.append(
                    f'{cursor.year:04d}-{cursor.month:02d}:{type(exc).__name__}')
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)
            time.sleep(0.12)
    try:
        for row in _fetch_current():
            by_date[row['date']] = row
    except Exception:
        if not by_date:
            raise
    rows = [by_date[key] for key in sorted(by_date)]
    if years > 0 and len(rows) < 253:
        raise RuntimeError(
            f'Taiwan 50 bootstrap insufficient: {len(rows)} rows; '
            f'{len(failed_months)}/{attempted_months} month requests failed')
    with _lock:
        _write_rows(rows, path)
    return {
        'ok': bool(rows), 'rows': len(rows), 'asOf': rows[-1]['date'] if rows else None,
        'source': SOURCE, 'attemptedMonths': attempted_months,
        'failedMonths': failed_months,
    }


def _background_job(years: int) -> None:
    global _refresh_thread
    try:
        result = refresh(years=years)
        with _lock:
            _status.update({
                'running': False, 'lastSuccess': datetime.now().astimezone().isoformat(timespec='seconds'),
                'lastError': None, 'rows': result.get('rows', 0),
                'failedMonths': result.get('failedMonths') or [],
            })
    except Exception as exc:
        with _lock:
            _status.update({'running': False, 'lastError': f'{type(exc).__name__}: {str(exc)[:120]}'})
    finally:
        with _lock:
            _refresh_thread = None


def start_background_refresh(years: int = 6) -> bool:
    global _refresh_thread
    with _lock:
        if _refresh_thread and _refresh_thread.is_alive():
            return False
        _status['running'] = True
        _refresh_thread = threading.Thread(
            target=_background_job, args=(years,), name='st-tai50-refresh', daemon=True)
        _refresh_thread.start()
        return True


def _local_product_series() -> dict[str, Any]:
    """Reuse market.db; never fetch product history from this provider."""
    try:
        import datastore
    except Exception:
        return {}
    out = {}
    for symbol in ('0050', '00631L', '00685L'):
        rows = []
        try:
            raw_rows = datastore.get_bars(symbol, limit=900, market='TW')
        except Exception:
            raw_rows = []
        for raw in raw_rows or []:
            if not isinstance(raw, (list, tuple)) or len(raw) < 5:
                continue
            try:
                iso = datetime.fromtimestamp(int(raw[0]), tz=timezone.utc).date().isoformat()
                close = _number(raw[4])
            except (TypeError, ValueError, OSError):
                continue
            if close is not None:
                rows.append({'date': iso, 'close': close})
        if rows:
            out[symbol] = {
                'rows': rows, 'asOf': rows[-1]['date'], 'source': 'market.db',
                'quality': 'local_market_history', 'pointInTimeAudited': False,
                'returnBasis': 'price_close_unadjusted',
            }
    return out


def snapshot(*, allow_network: bool = False, path: str = TAI50_CSV) -> dict[str, Any]:
    """Return a bounded, auditable contract; network refresh never blocks caller."""
    rows = _read_rows(path)
    newest = rows[-1]['date'] if rows else None
    age_days = None
    if newest:
        try:
            age_days = max(0, (date.today() - date.fromisoformat(newest)).days)
        except ValueError:
            age_days = None
    enough_long_run = len(rows) >= 757
    stale = age_days is None or age_days > 10
    quality = 'ready' if enough_long_run and not stale else (
        'stale' if enough_long_run else ('partial_scope' if rows else 'insufficient'))
    if allow_network and (not enough_long_run or stale):
        start_background_refresh(6 if not enough_long_run else 0)
    with _lock:
        status = dict(_status)
    return {
        'FTSE_TAIWAN_50': {
            'rows': rows,
            'source': SOURCE,
            'asOf': newest,
            'quality': quality,
            'stale': stale,
            'pointInTimeAudited': True,
            'sampleDays': len(rows),
            'refresh': status,
            'reference': 'official Taiwan 50 price and total-return index; available since 2002-10-18',
        },
        'PRODUCTS': _local_product_series(),
    }


def status() -> dict[str, Any]:
    contract = snapshot(allow_network=False).get('FTSE_TAIWAN_50') or {}
    return {
        **dict(_status),
        'cachePath': TAI50_CSV,
        'sampleDays': contract.get('sampleDays'),
        'asOf': contract.get('asOf'),
        'quality': contract.get('quality'),
    }
