#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ind_cache.py — 長歷史技術指標 tip 快取（增量維護）

設計：
  - 日線 bar 存在 market.db.bars（datastore）
  - 每檔只存「最新一根」的指標 tip（ind_tip），給雙軸卡／選股／預熱用
  - 增量規則：
      1) 無 bar → 回補 depth（預設 5y）
      2) 有 bar 但 tip 落後（tip_ts < last_bar_ts）→ 只抓 Yahoo 1mo 補 bar，再重算 tip
      3) tip 已跟上 → 略過（秒級）
  - 重算 tip 只需讀最近 WARMUP 根（SMA60/MACD 足夠），不必掃全表

與前端 runWorker / techScore 對齊：Wilder RSI、Stochastic KD、SMA 種子 EMA。
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import datastore as ds

WARMUP = 200  # tip 重算往回多取的 bar 數（涵蓋 SMA60 + MACD）

IND_SCHEMA = """
CREATE TABLE IF NOT EXISTS ind_tip(
  symbol TEXT PRIMARY KEY,
  market TEXT,
  tip_ts INTEGER,
  close REAL,
  sma5 REAL, sma20 REAL, sma60 REAL,
  rsi14 REAL,
  macd REAL, macd_sig REAL, macd_hist REAL,
  k REAL, d REAL,
  atr14 REAL, vol_ratio REAL,
  tech_score INTEGER,
  bar_count INTEGER,
  computed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ind_tip_computed ON ind_tip(computed_at);
"""


def ensure_schema() -> None:
    ds.init_db()
    with ds.closing(ds.get_conn()) as conn:
        with conn:
            conn.executescript(IND_SCHEMA)


# ── 指標計算（與 stock_terminal worker 對齊）────────────────
def _sma_last(closes: Sequence[float], p: int) -> Optional[float]:
    if len(closes) < p:
        return None
    return sum(closes[-p:]) / p


def _ema_series(arr: Sequence[float], p: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(arr)
    if len(arr) < p:
        return out
    s = sum(arr[:p]) / p
    out[p - 1] = s
    k = 2.0 / (p + 1)
    for i in range(p, len(arr)):
        s = arr[i] * k + s * (1 - k)
        out[i] = s
    return out


def _rsi_wilder(closes: Sequence[float], period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None
    avg_g = avg_l = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            avg_g += d
        else:
            avg_l -= d
    avg_g /= period
    avg_l /= period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        lo = -d if d < 0 else 0.0
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + lo) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def _stoch_kd(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
              n: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> Tuple[float, float]:
    k = d = 50.0
    for i in range(len(closes)):
        fr = max(0, i - n + 1)
        hi = max(highs[fr:i + 1])
        lo = min(lows[fr:i + 1])
        rsv = 50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100.0
        k = ((k_smooth - 1) / k_smooth) * k + (1 / k_smooth) * rsv
        d = ((d_smooth - 1) / d_smooth) * d + (1 / d_smooth) * k
    return k, d


def _atr_wilder(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
                period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None
    atr = 0.0
    for i in range(1, period + 1):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        atr += tr
    atr /= period
    for i in range(period + 1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        atr = (atr * (period - 1) + tr) / period
    return atr


def tech_score_from_tip(tip: Dict[str, Any]) -> Optional[int]:
    """與 enhance_v3.techScore 同一公式（基底 50）。"""
    score = 50.0
    parts = 0
    rsi = tip.get('rsi14')
    if rsi is not None:
        score += max(-20.0, min(20.0, (float(rsi) - 50.0) * 0.8))
        parts += 1
    macd, sig = tip.get('macd'), tip.get('macd_sig')
    if macd is not None and sig is not None:
        score += 12.0 if float(macd) > float(sig) else -12.0
        parts += 1
    k, d = tip.get('k'), tip.get('d')
    if k is not None and d is not None:
        score += 8.0 if float(k) > float(d) else -8.0
        parts += 1
    cur, sma20 = tip.get('close'), tip.get('sma20')
    if cur is not None and sma20 is not None:
        score += 10.0 if float(cur) > float(sma20) else -10.0
        parts += 1
    sma60 = tip.get('sma60')
    if sma20 is not None and sma60 is not None:
        score += 10.0 if float(sma20) > float(sma60) else -10.0
        parts += 1
    if not parts:
        return None
    return int(max(0, min(100, round(score))))


def compute_tip_from_bars(rows: Sequence[Tuple]) -> Optional[Dict[str, Any]]:
    """rows: [(ts,o,h,l,c,v), ...] 升序。至少約 60 根才有意義。"""
    if not rows or len(rows) < 30:
        return None
    # 只用尾端 WARMUP 加速
    use = rows[-WARMUP:] if len(rows) > WARMUP else rows
    ts = [int(r[0]) for r in use]
    highs = [float(r[2]) for r in use]
    lows = [float(r[3]) for r in use]
    closes = [float(r[4]) for r in use]
    vols = [float(r[5] or 0) for r in use]

    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    macd_arr: List[Optional[float]] = [
        (a - b) if a is not None and b is not None else None
        for a, b in zip(ema12, ema26)
    ]
    first = next((i for i, v in enumerate(macd_arr) if v is not None), -1)
    macd = macd_sig = macd_hist = None
    if first >= 0:
        sub2 = [float(macd_arr[i]) for i in range(first, len(macd_arr)) if macd_arr[i] is not None]
        if len(sub2) >= 9:
            sig_s = _ema_series(sub2, 9)
            macd = sub2[-1]
            macd_sig = sig_s[-1]
            if macd is not None and macd_sig is not None:
                macd_hist = macd - float(macd_sig)

    k, d = _stoch_kd(highs, lows, closes)
    v5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0.0
    v20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else 0.0
    tip = {
        'tip_ts': ts[-1],
        'close': closes[-1],
        'sma5': _sma_last(closes, 5),
        'sma20': _sma_last(closes, 20),
        'sma60': _sma_last(closes, 60),
        'rsi14': _rsi_wilder(closes, 14),
        'macd': macd,
        'macd_sig': macd_sig,
        'macd_hist': macd_hist,
        'k': k,
        'd': d,
        'atr14': _atr_wilder(highs, lows, closes, 14),
        'vol_ratio': (v5 / v20) if v20 > 0 else None,
        'bar_count': len(rows),
    }
    tip['tech_score'] = tech_score_from_tip(tip)
    return tip


def save_tip(sym: str, market: str, tip: Dict[str, Any]) -> None:
    ensure_schema()
    with ds._db_write_lock:
        with ds.closing(ds.get_conn()) as conn:
            with conn:
                conn.execute(
                    '''INSERT OR REPLACE INTO ind_tip(
                         symbol,market,tip_ts,close,sma5,sma20,sma60,rsi14,
                         macd,macd_sig,macd_hist,k,d,atr14,vol_ratio,
                         tech_score,bar_count,computed_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (
                        sym, market, tip.get('tip_ts'), tip.get('close'),
                        tip.get('sma5'), tip.get('sma20'), tip.get('sma60'), tip.get('rsi14'),
                        tip.get('macd'), tip.get('macd_sig'), tip.get('macd_hist'),
                        tip.get('k'), tip.get('d'), tip.get('atr14'), tip.get('vol_ratio'),
                        tip.get('tech_score'), tip.get('bar_count'), int(time.time()),
                    ),
                )


def get_tip(sym: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with ds.closing(ds.get_conn()) as conn:
        row = conn.execute(
            '''SELECT symbol,market,tip_ts,close,sma5,sma20,sma60,rsi14,
                      macd,macd_sig,macd_hist,k,d,atr14,vol_ratio,
                      tech_score,bar_count,computed_at
               FROM ind_tip WHERE symbol=?''',
            (sym,),
        ).fetchone()
    if not row:
        return None
    keys = [
        'symbol', 'market', 'tip_ts', 'close', 'sma5', 'sma20', 'sma60', 'rsi14',
        'macd', 'macd_sig', 'macd_hist', 'k', 'd', 'atr14', 'vol_ratio',
        'tech_score', 'bar_count', 'computed_at',
    ]
    return dict(zip(keys, row))


def recompute_tip(sym: str, market: str = 'TW') -> Optional[Dict[str, Any]]:
    rows = ds.get_bars(sym)
    tip = compute_tip_from_bars(rows)
    if not tip:
        return None
    save_tip(sym, market, tip)
    out = dict(tip)
    out['symbol'] = sym
    out['market'] = market
    out['computed_at'] = int(time.time())
    out['source'] = 'recompute'
    return out


def tip_stale(sym: str) -> bool:
    """True = 需要重算（無 tip 或 tip 落後於最新 bar）。"""
    last = ds.last_ts(sym)
    if not last:
        return True
    tip = get_tip(sym)
    if not tip or not tip.get('tip_ts'):
        return True
    return int(tip['tip_ts']) < int(last)


def ensure_symbol(sym: str, market: str = 'TW', depth: str = '5y',
                  force: bool = False) -> Dict[str, Any]:
    """
    步進式維護單檔：
      - 無歷史 → Yahoo depth 全量回補
      - 有歷史 → 只抓 1mo 增量
      - tip 落後或 force → 重算 tip
    """
    ensure_schema()
    sym = str(sym).strip().upper().replace('.TW', '').replace('.TWO', '')
    market = 'TW' if market != 'US' else 'US'
    actions: List[str] = []
    bars_n = 0

    last = ds.last_ts(sym)
    try:
        if not last:
            bars_n = ds.backfill(sym, market, depth)
            actions.append(f'backfill:{depth}:{bars_n}')
        else:
            # 增量：近月（涵蓋假日／補洞）；便宜
            n = ds.update(sym, market)
            bars_n = n
            actions.append(f'update:1mo:{n}')
    except Exception as e:
        return {'ok': False, 'symbol': sym, 'market': market, 'error': str(e), 'actions': actions}

    if force or tip_stale(sym):
        tip = recompute_tip(sym, market)
        actions.append('recompute_tip' if tip else 'recompute_failed')
    else:
        tip = get_tip(sym)
        actions.append('tip_fresh')

    return {
        'ok': tip is not None,
        'symbol': sym,
        'market': market,
        'actions': actions,
        'barsAdded': bars_n,
        'tip': tip,
        'techScore': (tip or {}).get('tech_score'),
    }


def prefetch_many(items: List[Dict[str, str]], depth: str = '5y',
                  force: bool = False, workers: int = 4) -> Dict[str, Any]:
    """
    批次預熱：自選股／觀察清單。
    網路抓取可併發；寫 DB 走 datastore 鎖。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ensure_schema()
    results = []
    t0 = time.time()
    # 序列較穩（Yahoo 限流）；少量自選用小併發
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as ex:
        futs = {}
        for it in items:
            sym = str(it.get('t') or it.get('sym') or '').strip()
            if not sym:
                continue
            mkt = str(it.get('m') or it.get('market') or 'TW').upper()
            if mkt not in ('TW', 'US'):
                mkt = 'TW'
            futs[ex.submit(ensure_symbol, sym, mkt, depth, force)] = sym
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({'ok': False, 'symbol': futs[fut], 'error': str(e)})
    ok = sum(1 for r in results if r.get('ok'))
    return {
        'ok': True,
        'count': len(results),
        'okCount': ok,
        'elapsedMs': int((time.time() - t0) * 1000),
        'results': results,
    }


def status_summary() -> Dict[str, Any]:
    ensure_schema()
    with ds.closing(ds.get_conn()) as conn:
        n_tip = conn.execute('SELECT COUNT(*) FROM ind_tip').fetchone()[0]
        n_bars_sym = conn.execute('SELECT COUNT(DISTINCT symbol) FROM bars').fetchone()[0]
        latest = conn.execute('SELECT MAX(computed_at) FROM ind_tip').fetchone()[0]
    return {
        'tipCount': n_tip,
        'barSymbols': n_bars_sym,
        'updated': int(latest or 0),
        'count': n_tip,
    }


if __name__ == '__main__':
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['ensure', 'prefetch', 'recompute', 'status', 'init'])
    ap.add_argument('--sym', default='2330')
    ap.add_argument('--market', default='TW')
    ap.add_argument('--depth', default='5y')
    ap.add_argument('--syms', default='', help='comma codes for prefetch')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    if args.cmd == 'init':
        ensure_schema()
        print('ind_tip ready')
    elif args.cmd == 'ensure':
        print(json.dumps(ensure_symbol(args.sym, args.market, args.depth, args.force), ensure_ascii=False, indent=2))
    elif args.cmd == 'recompute':
        print(json.dumps(recompute_tip(args.sym, args.market), ensure_ascii=False, indent=2))
    elif args.cmd == 'prefetch':
        items = [{'t': s.strip(), 'm': args.market} for s in args.syms.split(',') if s.strip()]
        print(json.dumps(prefetch_many(items, depth=args.depth, force=args.force), ensure_ascii=False, indent=2))
    elif args.cmd == 'status':
        print(json.dumps(status_summary(), ensure_ascii=False, indent=2))
