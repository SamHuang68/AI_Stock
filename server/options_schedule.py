"""自動更新台指選擇權結構：只排入既有的 options 更新工作，不另建來源管線。

TAIFEX 官方檔把 D 日資料在 D+1 約 06:36（台北）才發布，收盤後同日抓不到當日資料。
因此在交易日開盤前（07:00–08:30，每 30 分鐘一個時段）更新，此時現貨基準仍是前一交易日收盤，
與選擇權資料日一致；快取資料日已是前一交易日即停止。
需擁有者在 data/options_daily_schedule.json 明確設定 enabled=true 才會外送；
時段收據先寫入再排隊，程序重啟不會重複外送。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import datastore
import options_exposure
import stock_signals as ss
from atomic_store import atomic_write_json, load_json
from 台股交易參考 import session

SLOTS = (7 * 60, 7 * 60 + 30, 8 * 60, 8 * 60 + 30)
OPEN_HOUR = 9
POLL_SECONDS = 600
_thread = None


def _data_dir():
    return Path(datastore.DB_PATH).parent


def enabled():
    config = load_json(str(_data_dir() / 'options_daily_schedule.json'), default={}, expected_type=dict)
    return config.get('enabled') is True


def _chain_date():
    observed = (options_exposure.latest_cached() or {}).get('observed') or {}
    return observed.get('tradeDate')


def previous_session(day):
    """前一個表定交易日（ISO 字串）；日曆未涵蓋時回傳 None，不以平日推定。"""
    cursor = date.fromisoformat(day)
    while True:
        cursor -= timedelta(days=1)
        status = session(cursor)['status']
        if status == 'unknown':
            return None
        if status == 'scheduled':
            return cursor.isoformat()


def tick(current, submit):
    """回傳是否在本次排入更新；submit(kind, params) 為統一更新中心的 submit。"""
    day = current.date().isoformat()
    if not enabled() or session(day)['status'] != 'scheduled' or current.hour >= OPEN_HOUR:
        return False
    minutes = current.hour * 60 + current.minute
    slots = [value for value in SLOTS if value <= minutes]
    expected = previous_session(day)
    if not slots or expected is None or (_chain_date() or '') >= expected:
        return False
    key = day + '/' + str(slots[-1])
    filename = _data_dir() / 'options_daily_attempts.json'
    attempts = load_json(str(filename), default={}, expected_type=dict)
    if key in attempts:
        return False
    # 先留下時段收據再排隊；排隊失敗也保留，同一時段不重試，下一時段再試。
    attempts[key] = {'queuedAt': current.isoformat(), 'status': 'reserved'}
    atomic_write_json(str(filename), attempts, backup=True)
    try:
        submit('options', {'force': True})
    except Exception as exc:
        attempts[key].update(status='rejected', error=type(exc).__name__)
        atomic_write_json(str(filename), attempts, backup=True)
        return False
    attempts[key]['status'] = 'queued'
    atomic_write_json(str(filename), attempts, backup=True)
    return True


def start_daemon(submit):
    global _thread
    if _thread and _thread.is_alive():
        return False

    def loop():
        while True:
            try:
                tick(datetime.now(ss._TZ['TW']), submit)
            except Exception:
                logging.getLogger(__name__).exception('選擇權每日更新排程檢查失敗')
            time.sleep(POLL_SECONDS)
    _thread = threading.Thread(target=loop, name='options-daily-refresh', daemon=True)
    _thread.start()
    return True
