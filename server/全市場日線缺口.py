"""全市場日線缺口偵測與追補。

每日收盤後排程只處理「當天」，而且只在平日 14:00～21:00 的窗口內觸發；服務在窗口內沒跑，當天的全市場日線
就永遠缺（官方更新器預設只取最近一個完整交易日，不會自動追補）。本模組偵測最近 31 日內「日曆認定為交易日、
但全市場日線筆數明顯偏低」的日期，逐日沿用 台股日線.run_update（官方 TWSE／TPEX 指定日期）補回，不另建抓取管線。
"""
from __future__ import annotations

import sqlite3
import statistics
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WINDOW_DAYS = 31      # 與 run_update「起日最多回推 31 日」的限制一致
MIN_RATIO = 0.5       # 低於同期中位數的一半視為缺口
MIN_MARKET_SIZE = 500  # 中位數低於此值代表本機不是全市場資料庫（只存自選股），不判定缺口
MAX_PER_RUN = 5       # 每次最多補幾個交易日，避免一次對官方來源送出過多請求


def missing_sessions(db: Path, today: date, *, window_days: int = WINDOW_DAYS, min_ratio: float = MIN_RATIO) -> list[str]:
    """今天以前、window 內，日曆認定為交易日但全市場日線筆數低於同期中位數 min_ratio 的日期（由舊到新）。

    日曆無法核對、或資料庫不像全市場資料庫時回空清單：不能在沒有依據時判定缺口。"""
    try:
        from 台股交易參考 import verified_sessions
    except ImportError:  # 套件形式載入
        from .台股交易參考 import verified_sessions
    begin, end = today - timedelta(days=window_days), today - timedelta(days=1)
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as conn:
        sessions = verified_sessions(begin.isoformat(), end.isoformat(), connection=conn, allow_partial=True)
        if not sessions:
            return []
        low = int(datetime.combine(begin, time(0), TZ).timestamp())
        high = int(datetime.combine(today, time(0), TZ).timestamp())
        counts: dict[str, int] = {}
        for ts, n in conn.execute("SELECT ts, COUNT(*) FROM bars WHERE market='TW' AND ts>=? AND ts<? GROUP BY ts", (low, high)):
            day = datetime.fromtimestamp(ts, TZ).date().isoformat()
            counts[day] = counts.get(day, 0) + n
    values = [counts.get(day, 0) for day in sessions]
    median = statistics.median(values)
    if median < MIN_MARKET_SIZE:
        return []
    return [day for day in sessions if counts.get(day, 0) < median * min_ratio]


def catch_up(db: Path, now: datetime, *, limit: int = MAX_PER_RUN, run=None, check=lambda: None) -> dict:
    """逐日補回缺口日；任何一天失敗就停止，留待下一個日曆日再試。"""
    if run is None:
        try:
            from 台股日線 import run_update as run
        except ImportError:
            from .台股日線 import run_update as run
    days = missing_sessions(db, now.astimezone(TZ).date())
    attempted = []
    for day in days[:max(limit, 0)]:
        check()
        at = datetime.combine(date.fromisoformat(day), time(23, 0), TZ)
        state = run(Path(db), start=date.fromisoformat(day), now=at, check=check, historical=True)
        ok = bool(state.get('ok'))
        attempted.append({'date': day, 'ok': ok, 'status': state.get('status'), 'failures': list(state.get('failures', []))[:2]})
        if not ok:
            break
    return {'checkedAt': now.isoformat(), 'missing': days, 'attempted': attempted,
            'remaining': len(days) - sum(1 for item in attempted if item['ok'])}
