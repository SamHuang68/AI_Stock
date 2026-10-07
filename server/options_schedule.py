"""收盤後自動更新台指選擇權結構：只排入既有的 options 更新工作，不另建來源管線。

需擁有者在 data/options_daily_schedule.json 明確設定 enabled=true 才會外送；
每個交易日三個時段（18:30、19:30、20:30），當日官方資料已入快取即停止，
時段收據先寫入再排隊，程序重啟不會重複外送。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import datastore
import options_exposure
import stock_signals as ss
from atomic_store import atomic_write_json, load_json
from 台股交易參考 import session

SLOTS = (18 * 60 + 30, 19 * 60 + 30, 20 * 60 + 30)
LAST_HOUR = 21
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


def tick(current, submit):
    """回傳是否在本次排入更新；submit(kind, params) 為統一更新中心的 submit。"""
    day = current.date().isoformat()
    if not enabled() or session(day)['status'] != 'scheduled' or current.hour >= LAST_HOUR:
        return False
    minutes = current.hour * 60 + current.minute
    slots = [value for value in SLOTS if value <= minutes]
    if not slots or _chain_date() == day:
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
