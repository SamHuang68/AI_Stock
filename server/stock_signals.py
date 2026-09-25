# -*- coding: utf-8 -*-
"""個股訊號引擎（st-stock-signals/v1）：事件、五燈體檢、失效條件與歷史統計。

設計原則
--------
* **單一計算者**：所有指標走 ``indicators.py``（Wilder RSI、母體σ布林、Wilder ATR），
  前端與推播只讀本模組輸出，不再各自重算。
* **事件而非水位**：訊號是「狀態轉換」（例如 RSI 由 <30 回升站上 30），
  每個事件都帶失效條件；水位型描述只出現在五燈體檢。
* **Point-in-time**：第 t 根的判斷只用 ≤ t 的資料；歷史統計只收已走完 horizon 的樣本，
  樣本數 < MIN_SAMPLE 時不公開比例（與 early_warning／conditional_expectation 同一紀律）。
* **不給買賣指令**：輸出是「偏多／偏空／留意」與失效價位，不是下單建議。

本模組是純計算層：不做網路、不讀寫檔案（chip_history 讀取工具除外），
由 ``stock_signals_routes`` 負責資料載入與快取。
"""
from __future__ import annotations

import glob
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from . import indicators as ind
except ImportError:  # server/ 在 sys.path（server.py、daemon、測試）
    import indicators as ind

try:
    from zoneinfo import ZoneInfo
    _TZ = {'TW': ZoneInfo('Asia/Taipei'), 'US': ZoneInfo('America/New_York')}
except Exception:  # pragma: no cover - Windows 無 tzdata 時的保守退路
    _TZ = {'TW': timezone(timedelta(hours=8)), 'US': timezone(timedelta(hours=-5))}

CONTRACT_VERSION = 1
ENGINE_ID = 'st-stock-signals/v1'
EPISTEMIC_EVENTS = 'FACT'
EPISTEMIC_STATS = 'CONDITIONAL'
MIN_SAMPLE = 20
STAT_HORIZONS = (5, 20)
STAT_COOLDOWN_BARS = 5
EVENT_LOOKBACK_BARS = 10
CONFIRM_BARS = 3
MIN_BARS = 70

DISCLAIMER = ('訊號是規則化的狀態轉換與歷史統計，不是買賣建議；'
              '歷史表現不代表未來，價格未還原除權息。')

FAMILY_LABEL = {
    'trend': '趨勢',
    'momentum': '動能',
    'volume': '量價',
    'volatility': '波動',
    'chip': '籌碼',
}
DIRECTION_LABEL = {'bull': '偏多', 'bear': '偏空', 'risk': '風險'}


# ── 資料正規化 ───────────────────────────────────────────────
def _finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def bar_date(ts: Any, market: str = 'TW') -> Optional[str]:
    """Yahoo／本機 DB 的 epoch 秒 → 交易所當地日期（YYYY-MM-DD）。"""
    if isinstance(ts, str) and len(ts) >= 10 and ts[4] == '-':
        return ts[:10]
    f = _finite(ts)
    if f is None:
        return None
    if f > 1e11:  # 毫秒
        f /= 1000.0
    tz = _TZ.get(market, _TZ['TW'])
    return datetime.fromtimestamp(f, tz).date().isoformat()


def normalize_bars(rows: Iterable[Any], market: str = 'TW') -> List[Dict[str, Any]]:
    """接受 datastore tuple (ts,o,h,l,c,v) 或 dict，回傳由舊到新、同日去重的日 K。"""
    by_day: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        if isinstance(r, Mapping):
            ts = r.get('time', r.get('ts', r.get('date')))
            o, h, lo, c, v = (r.get('open'), r.get('high'), r.get('low'),
                              r.get('close'), r.get('volume'))
        else:
            try:
                ts, o, h, lo, c, v = r[0], r[1], r[2], r[3], r[4], r[5]
            except (IndexError, TypeError):
                continue
        close = _finite(c)
        day = bar_date(ts, market)
        if close is None or close <= 0 or not day:
            continue
        high = _finite(h) or close
        low = _finite(lo) or close
        bar = {
            'date': day,
            'open': _finite(o) or close,
            'high': max(high, close),
            'low': min(low, close),
            'close': close,
            'volume': max(0.0, _finite(v) or 0.0),
        }
        # 同一交易日出現兩筆（盤中快照 + 收盤日 K 的時間戳不同）時，保留量較大的完整日 K；
        # 同量則以較晚者為準。
        prev = by_day.get(day)
        if prev is None or bar['volume'] >= prev['volume']:
            by_day[day] = bar
    return [by_day[k] for k in sorted(by_day)]


# ── 籌碼歷史（沿用 data/chip_history/<yyyymmdd>.json，與 server._chip_streak 同源）──
def load_chip_series(code: str, chip_dir: str, days: int = 60) -> List[Dict[str, Any]]:
    """由新到舊讀最近 ``days`` 個 chip_history 檔，回傳由舊到新的
    [{date, foreign, trust, dealer, total}]；該日沒有此代號就略過（不補 0）。"""
    if not code or not chip_dir or not os.path.isdir(chip_dir):
        return []
    files = sorted(glob.glob(os.path.join(chip_dir, '*.json')), reverse=True)[:days]
    out: List[Dict[str, Any]] = []
    for fn in files:
        stem = os.path.splitext(os.path.basename(fn))[0]
        if len(stem) != 8 or not stem.isdigit():
            continue
        try:
            with open(fn, encoding='utf-8') as f:
                day = json.load(f)
        except Exception:
            continue
        rec = day.get(code) if isinstance(day, dict) else None
        if not isinstance(rec, dict):
            continue
        out.append({
            'date': f'{stem[:4]}-{stem[4:6]}-{stem[6:]}',
            'foreign': _finite(rec.get('foreign')),
            'trust': _finite(rec.get('trust')),
            'dealer': _finite(rec.get('dealer')),
            'total': _finite(rec.get('total')),
        })
    out.reverse()
    return out


def chip_streaks(series: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """連買(+)／連賣(-)天數；最新一筆為 0 或缺值則為 0。缺值日跳過而非中斷，
    與既有 server._chip_streak 語意一致。"""
    out: Dict[str, int] = {}
    for key in ('foreign', 'trust', 'dealer'):
        vals = [r.get(key) for r in reversed(list(series)) if r.get(key) is not None]
        if not vals or vals[0] == 0:
            out[key] = 0
            continue
        sign = 1 if vals[0] > 0 else -1
        n = 0
        for v in vals:
            if (v > 0 and sign > 0) or (v < 0 and sign < 0):
                n += 1
            else:
                break
        out[key] = n * sign
    return out


# ── 指標序列 ─────────────────────────────────────────────────
def build_frame(bars: Sequence[Mapping[str, Any]],
                chips: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, List[Any]]:
    """一次算好所有逐根序列；每個值都只依賴 ≤ 該根的資料。"""
    c = [float(b['close']) for b in bars]
    h = [float(b['high']) for b in bars]
    lo = [float(b['low']) for b in bars]
    v = [float(b['volume']) for b in bars]
    d = [b['date'] for b in bars]
    macd = ind.macd_series(c)
    bb = ind.bollinger_series(c, 20, 2.0)
    atr = ind.atr_wilders_series(h, lo, c, 14)
    volx: List[Optional[float]] = []
    for i in range(len(v)):
        base = ind.sma(v, 20, i - 1) if i >= 20 else None
        volx.append((v[i] / base) if base else None)
    v5 = ind.sma_series(v, 5)
    v20 = ind.sma_series(v, 20)
    chip_by_date = {r['date']: r for r in (chips or [])}
    return {
        'date': d, 'open': [float(b['open']) for b in bars], 'high': h, 'low': lo,
        'close': c, 'volume': v,
        'sma5': ind.sma_series(c, 5), 'sma20': ind.sma_series(c, 20),
        'sma60': ind.sma_series(c, 60),
        'rsi': ind.rsi_wilders_series(c, 14),
        'macd': macd['macd'], 'macd_sig': macd['signal'], 'macd_hist': macd['hist'],
        'bb_u': bb['upper'], 'bb_l': bb['lower'], 'bb_mid': bb['mid'], 'bb_w': bb['width'],
        'atr': atr, 'volx': volx,
        'vr': [(a / b) if a is not None and b else None for a, b in zip(v5, v20)],
        'foreign': [(chip_by_date.get(x) or {}).get('foreign') for x in d],
        'trust': [(chip_by_date.get(x) or {}).get('trust') for x in d],
    }


def _g(f: Mapping[str, List[Any]], key: str, i: int) -> Optional[float]:
    if i < 0:
        return None
    arr = f[key]
    return arr[i] if i < len(arr) else None


def _all(*vals: Any) -> bool:
    return all(x is not None for x in vals)


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or not b:
        return None
    return (a / b - 1.0) * 100.0


def _fmt(x: Optional[float], nd: int = 2) -> str:
    return '—' if x is None else f'{x:,.{nd}f}'


def _percentile_rank(window: Sequence[float], value: float) -> float:
    """value 在 window 中的百分位（0~100，含等值一半）。"""
    if not window:
        return 50.0
    below = sum(1 for x in window if x < value)
    equal = sum(1 for x in window if x == value)
    return 100.0 * (below + 0.5 * equal) / len(window)


# ── 訊號目錄 ─────────────────────────────────────────────────
# detect(f, i) → None 或 {'detail': str, 'level': float|None}
# invalid(f, t, k, ev) → True 表示第 k 根（k > t）已觸發失效條件
def _det_cross_price_ma(up: bool) -> Callable:
    def det(f, i):
        c0, c1, m0, m1 = _g(f, 'close', i), _g(f, 'close', i - 1), _g(f, 'sma60', i), _g(f, 'sma60', i - 1)
        if not _all(c0, c1, m0, m1):
            return None
        hit = (c0 > m0 and c1 <= m1) if up else (c0 < m0 and c1 >= m1)
        if not hit:
            return None
        verb = '站上' if up else '跌破'
        return {'detail': f'收盤 {_fmt(c0)} {verb}季線（60 日均線）{_fmt(m0)}', 'level': m0}
    return det


def _inv_price_vs_ma(up: bool) -> Callable:
    def inv(f, t, k, ev):
        c, m = _g(f, 'close', k), _g(f, 'sma60', k)
        if not _all(c, m):
            return False
        return c < m if up else c > m
    return inv


def _det_ma_cross(up: bool) -> Callable:
    def det(f, i):
        a0, a1, b0, b1 = _g(f, 'sma20', i), _g(f, 'sma20', i - 1), _g(f, 'sma60', i), _g(f, 'sma60', i - 1)
        if not _all(a0, a1, b0, b1):
            return None
        hit = (a0 > b0 and a1 <= b1) if up else (a0 < b0 and a1 >= b1)
        if not hit:
            return None
        verb = '向上穿越' if up else '向下跌破'
        return {'detail': f'20 日均線 {_fmt(a0)} {verb} 60 日均線 {_fmt(b0)}', 'level': None}
    return det


def _inv_ma_cross(up: bool) -> Callable:
    def inv(f, t, k, ev):
        a, b = _g(f, 'sma20', k), _g(f, 'sma60', k)
        if not _all(a, b):
            return False
        return a < b if up else a > b
    return inv


def _det_rsi_rebound(f, i):
    r0, r1 = _g(f, 'rsi', i), _g(f, 'rsi', i - 1)
    if not _all(r0, r1) or not (r1 < 30 <= r0):
        return None
    swing_low = min(f['low'][max(0, i - 10): i + 1])
    return {'detail': f'RSI 由 {r1:.1f} 回升站上 30（{r0:.1f}）', 'level': swing_low}


def _inv_below_level(f, t, k, ev):
    c, lvl = _g(f, 'close', k), ev.get('level')
    return _all(c, lvl) and c < lvl


def _inv_above_level(f, t, k, ev):
    c, lvl = _g(f, 'close', k), ev.get('level')
    return _all(c, lvl) and c > lvl


def _det_rsi_fade(f, i):
    r0, r1 = _g(f, 'rsi', i), _g(f, 'rsi', i - 1)
    if not _all(r0, r1) or not (r1 >= 70 > r0):
        return None
    swing_high = max(f['high'][max(0, i - 10): i + 1])
    return {'detail': f'RSI 由 {r1:.1f} 跌回 70 以下（{r0:.1f}）', 'level': swing_high}


def _det_macd(up: bool) -> Callable:
    def det(f, i):
        h0, h1 = _g(f, 'macd_hist', i), _g(f, 'macd_hist', i - 1)
        if not _all(h0, h1):
            return None
        hit = (h1 <= 0 < h0) if up else (h1 >= 0 > h0)
        if not hit:
            return None
        m, s = _g(f, 'macd', i), _g(f, 'macd_sig', i)
        verb = '向上穿越' if up else '向下跌破'
        return {'detail': f'MACD {_fmt(m, 3)} {verb}訊號線 {_fmt(s, 3)}', 'level': None}
    return det


def _inv_macd(up: bool) -> Callable:
    def inv(f, t, k, ev):
        h = _g(f, 'macd_hist', k)
        if h is None:
            return False
        return h < 0 if up else h > 0
    return inv


def _det_range_break(up: bool) -> Callable:
    def det(f, i):
        c0, c1 = _g(f, 'close', i), _g(f, 'close', i - 1)
        vx = _g(f, 'volx', i)
        key = 'high' if up else 'low'
        lvl0 = ind.prior_extreme(f[key], 20, i, highest=up)
        lvl1 = ind.prior_extreme(f[key], 20, i - 1, highest=up)
        if not _all(c0, c1, vx, lvl0, lvl1) or vx < 1.5:
            return None
        hit = (c0 > lvl0 and c1 <= lvl1) if up else (c0 < lvl0 and c1 >= lvl1)
        if not hit:
            return None
        verb = '突破' if up else '跌破'
        noun = '高點' if up else '低點'
        return {'detail': f'收盤 {_fmt(c0)} {verb}前 20 日{noun} {_fmt(lvl0)}，量 {vx:.1f} 倍', 'level': lvl0}
    return det


def _det_squeeze_break(up: bool) -> Callable:
    def det(f, i):
        w_prev = _g(f, 'bb_w', i - 1)
        c0, c1 = _g(f, 'close', i), _g(f, 'close', i - 1)
        band0 = _g(f, 'bb_u' if up else 'bb_l', i)
        band1 = _g(f, 'bb_u' if up else 'bb_l', i - 1)
        if not _all(w_prev, c0, c1, band0, band1):
            return None
        hist = [x for x in f['bb_w'][max(0, i - 121): i - 1] if x is not None]
        if len(hist) < 60 or _percentile_rank(hist, w_prev) > 20.0:
            return None
        hit = (c0 > band0 and c1 <= band1) if up else (c0 < band0 and c1 >= band1)
        if not hit:
            return None
        verb = '向上突破上軌' if up else '向下跌破下軌'
        return {'detail': f'布林帶寬處於近半年低檔後，收盤 {_fmt(c0)} {verb} {_fmt(band0)}',
                'level': _g(f, 'bb_mid', i)}
    return det


def _inv_vs_mid(up: bool) -> Callable:
    def inv(f, t, k, ev):
        c, m = _g(f, 'close', k), _g(f, 'bb_mid', k)
        if not _all(c, m):
            return False
        return c < m if up else c > m
    return inv


def _atr_ratio(f, i: int) -> Optional[float]:
    a0, a1 = _g(f, 'atr', i), _g(f, 'atr', i - 10)
    return (a0 / a1) if _all(a0, a1) and a1 > 0 else None


def _det_atr_expansion(f, i):
    r0, r1 = _atr_ratio(f, i), _atr_ratio(f, i - 1)
    if not _all(r0, r1) or not (r0 >= 1.5 > r1):
        return None
    return {'detail': f'ATR 在 10 日內放大為 {r0:.2f} 倍（單日波動變大）', 'level': None}


def _inv_atr_normal(f, t, k, ev):
    r = _atr_ratio(f, k)
    return r is not None and r < 1.2


def _det_chip_streak(key: str, up: bool) -> Callable:
    def det(f, i):
        if i < 3:
            return None
        vals = [_g(f, key, i - j) for j in range(4)]
        if not _all(vals[0], vals[1], vals[2]):
            return None
        same = (lambda x: x > 0) if up else (lambda x: x < 0)
        if not all(same(x) for x in vals[:3]):
            return None
        # 必須看得到第 4 天前的資料且方向不同，才能確定「今天剛好第 3 天」；
        # chip_history 剛開始累積時缺值，不能把第 N 天誤報成新成形。
        if vals[3] is None or same(vals[3]):
            return None
        who = '投信' if key == 'trust' else '外資'
        verb = '連續 3 日買超' if up else '連續 3 日賣超'
        total = sum(vals[:3]) / 1000.0
        return {'detail': f'{who}{verb}（合計 {total:+,.0f} 張）', 'level': None}
    return det


def _inv_chip(key: str, up: bool) -> Callable:
    def inv(f, t, k, ev):
        x = _g(f, key, k)
        if x is None:
            return False
        return x < 0 if up else x > 0
    return inv


SIGNALS: List[Dict[str, Any]] = [
    {'id': 'trend_reclaim_ma60', 'family': 'trend', 'direction': 'bull', 'label': '站上季線',
     'plain': '股價回到 60 日均線之上，中期買方重新取得優勢。',
     'rule': 'close[t] > SMA60[t] 且 close[t-1] ≤ SMA60[t-1]',
     'invalidText': '收盤跌回季線之下', 'detect': _det_cross_price_ma(True),
     'invalid': _inv_price_vs_ma(True)},
    {'id': 'trend_lose_ma60', 'family': 'trend', 'direction': 'bear', 'label': '跌破季線',
     'plain': '股價跌到 60 日均線之下，中期趨勢轉弱的第一個警訊。',
     'rule': 'close[t] < SMA60[t] 且 close[t-1] ≥ SMA60[t-1]',
     'invalidText': '收盤站回季線之上', 'detect': _det_cross_price_ma(False),
     'invalid': _inv_price_vs_ma(False)},
    {'id': 'trend_golden_cross', 'family': 'trend', 'direction': 'bull', 'label': '20/60 黃金交叉',
     'plain': '短期均線由下往上穿過中期均線，代表近期漲勢開始帶動中期趨勢。',
     'rule': 'SMA20 由下往上穿越 SMA60',
     'invalidText': '20 日均線再跌回 60 日均線之下', 'detect': _det_ma_cross(True),
     'invalid': _inv_ma_cross(True)},
    {'id': 'trend_death_cross', 'family': 'trend', 'direction': 'bear', 'label': '20/60 死亡交叉',
     'plain': '短期均線由上往下跌破中期均線，代表近期跌勢開始拖累中期趨勢。',
     'rule': 'SMA20 由上往下跌破 SMA60',
     'invalidText': '20 日均線再站回 60 日均線之上', 'detect': _det_ma_cross(False),
     'invalid': _inv_ma_cross(False)},
    {'id': 'mom_rsi_rebound', 'family': 'momentum', 'direction': 'bull', 'label': 'RSI 超賣回升',
     'plain': '賣壓過度（RSI < 30）後開始回升；跌勢可能放緩，但不代表已經止跌。',
     'rule': 'RSI14[t-1] < 30 ≤ RSI14[t]（Wilder）',
     'invalidText': '收盤跌破近 10 日最低點', 'detect': _det_rsi_rebound,
     'invalid': _inv_below_level},
    {'id': 'mom_rsi_fade', 'family': 'momentum', 'direction': 'bear', 'label': 'RSI 過熱回落',
     'plain': '買氣過熱（RSI ≥ 70）後開始降溫，短線漲勢可能休息。',
     'rule': 'RSI14[t-1] ≥ 70 > RSI14[t]（Wilder）',
     'invalidText': '收盤再創近 10 日新高', 'detect': _det_rsi_fade,
     'invalid': _inv_above_level},
    {'id': 'mom_macd_bull', 'family': 'momentum', 'direction': 'bull', 'label': 'MACD 翻多',
     'plain': 'MACD 由負轉正（穿越訊號線），短中期動能轉向上。',
     'rule': 'MACD(12,26,9) 柱狀體由 ≤0 轉 >0',
     'invalidText': 'MACD 柱狀體再轉負', 'detect': _det_macd(True), 'invalid': _inv_macd(True)},
    {'id': 'mom_macd_bear', 'family': 'momentum', 'direction': 'bear', 'label': 'MACD 翻空',
     'plain': 'MACD 由正轉負（跌破訊號線），短中期動能轉向下。',
     'rule': 'MACD(12,26,9) 柱狀體由 ≥0 轉 <0',
     'invalidText': 'MACD 柱狀體再轉正', 'detect': _det_macd(False), 'invalid': _inv_macd(False)},
    {'id': 'vol_breakout_20d', 'family': 'volume', 'direction': 'bull', 'label': '帶量突破 20 日高',
     'plain': '價格突破近一個月的高點，而且成交量明顯放大，有買盤推動。',
     'rule': 'close[t] > 前 20 日最高 且 當日量 ≥ 前 20 日均量 × 1.5',
     'invalidText': '收盤跌回突破點之下（假突破）', 'detect': _det_range_break(True),
     'invalid': _inv_below_level},
    {'id': 'vol_breakdown_20d', 'family': 'volume', 'direction': 'bear', 'label': '帶量跌破 20 日低',
     'plain': '價格跌破近一個月的低點，而且成交量放大，賣壓沉重。',
     'rule': 'close[t] < 前 20 日最低 且 當日量 ≥ 前 20 日均量 × 1.5',
     'invalidText': '收盤站回跌破點之上', 'detect': _det_range_break(False),
     'invalid': _inv_above_level},
    {'id': 'volat_squeeze_up', 'family': 'volatility', 'direction': 'bull', 'label': '盤整後向上噴出',
     'plain': '股價先窄幅整理（布林帶收窄），接著向上突破，常是新一段走勢的開始。',
     'rule': '前一日布林帶寬 ≤ 近 120 日第 20 百分位，且收盤向上穿越上軌',
     'invalidText': '收盤跌回布林中軌（20 日均線）之下', 'detect': _det_squeeze_break(True),
     'invalid': _inv_vs_mid(True)},
    {'id': 'volat_squeeze_down', 'family': 'volatility', 'direction': 'bear', 'label': '盤整後向下破底',
     'plain': '股價先窄幅整理，接著向下跌破，常是新一段跌勢的開始。',
     'rule': '前一日布林帶寬 ≤ 近 120 日第 20 百分位，且收盤向下穿越下軌',
     'invalidText': '收盤站回布林中軌（20 日均線）之上', 'detect': _det_squeeze_break(False),
     'invalid': _inv_vs_mid(False)},
    {'id': 'volat_atr_expansion', 'family': 'volatility', 'direction': 'risk', 'label': '波動急升',
     'plain': '每日漲跌幅度突然變大，方向不一定，但部位風險明顯增加。',
     'rule': 'ATR14[t] / ATR14[t-10] 首次 ≥ 1.5（Wilder ATR）',
     'invalidText': 'ATR 比值回落到 1.2 以下（波動恢復正常）', 'detect': _det_atr_expansion,
     'invalid': _inv_atr_normal},
    {'id': 'chip_trust_buy3', 'family': 'chip', 'direction': 'bull', 'label': '投信連 3 買',
     'plain': '投信連續 3 個交易日買超；法人資金持續流入。',
     'rule': '投信買賣超連續 3 日 > 0（第 3 日成形；資料為盤後公布）',
     'invalidText': '投信轉為賣超', 'detect': _det_chip_streak('trust', True),
     'invalid': _inv_chip('trust', True), 'entryLag': 1},
    {'id': 'chip_foreign_sell3', 'family': 'chip', 'direction': 'bear', 'label': '外資連 3 賣',
     'plain': '外資連續 3 個交易日賣超；大型資金持續流出。',
     'rule': '外資買賣超連續 3 日 < 0（第 3 日成形；資料為盤後公布）',
     'invalidText': '外資轉為買超', 'detect': _det_chip_streak('foreign', False),
     'invalid': _inv_chip('foreign', False), 'entryLag': 1},
]
SIGNAL_BY_ID = {s['id']: s for s in SIGNALS}


def catalog() -> List[Dict[str, Any]]:
    """公開目錄（不含函式），供 UI 說明與 AI 名詞表使用。"""
    return [{
        'id': s['id'], 'family': s['family'], 'familyLabel': FAMILY_LABEL[s['family']],
        'direction': s['direction'], 'directionLabel': DIRECTION_LABEL[s['direction']],
        'label': s['label'], 'plain': s['plain'], 'rule': s['rule'],
        'invalidText': s['invalidText'], 'entryLag': s.get('entryLag', 0),
    } for s in SIGNALS]


# ── 事件掃描與生命週期 ───────────────────────────────────────
def detect_at(frame: Mapping[str, List[Any]], i: int,
              signals: Sequence[Mapping[str, Any]] = SIGNALS) -> List[Dict[str, Any]]:
    out = []
    if i < 1:
        return out
    for spec in signals:
        hit = spec['detect'](frame, i)
        if hit:
            out.append({'signalId': spec['id'], 'index': i, **hit})
    return out


def _lifecycle(frame, spec, ev, last: int) -> Dict[str, Any]:
    t = ev['index']
    for k in range(t + 1, last + 1):
        if spec['invalid'](frame, t, k, ev):
            return {'status': 'invalidated', 'statusDate': frame['date'][k]}
    if t == last:
        return {'status': 'new', 'statusDate': frame['date'][t]}
    if last - t >= CONFIRM_BARS:
        return {'status': 'confirmed', 'statusDate': frame['date'][t + CONFIRM_BARS]}
    return {'status': 'active', 'statusDate': frame['date'][last]}


STATUS_LABEL = {
    'new': '今日新訊號', 'active': '觀察中', 'confirmed': '已站穩 3 日',
    'invalidated': '已失效',
}


def recent_events(frame: Mapping[str, List[Any]], lookback: int = EVENT_LOOKBACK_BARS,
                  provisional_last: bool = False) -> List[Dict[str, Any]]:
    """近 lookback 根內的事件；同一訊號只保留最近一次，並附生命週期狀態。"""
    n = len(frame['close'])
    if n < 2:
        return []
    last = n - 1
    latest: Dict[str, Dict[str, Any]] = {}
    for i in range(max(1, last - lookback), last + 1):
        for ev in detect_at(frame, i):
            latest[ev['signalId']] = ev
    out = []
    for sid, ev in latest.items():
        spec = SIGNAL_BY_ID[sid]
        life = _lifecycle(frame, spec, ev, last)
        status = life['status']
        if spec['direction'] == 'risk' and status == 'invalidated':
            status_label = '波動已回落'
        else:
            status_label = STATUS_LABEL[status]
        lvl = ev.get('level')
        out.append({
            'signalId': sid, 'label': spec['label'], 'family': spec['family'],
            'familyLabel': FAMILY_LABEL[spec['family']],
            'direction': spec['direction'], 'directionLabel': DIRECTION_LABEL[spec['direction']],
            'date': frame['date'][ev['index']], 'barsAgo': last - ev['index'],
            'status': status, 'statusLabel': status_label, 'statusDate': life['statusDate'],
            'provisional': bool(provisional_last and ev['index'] == last),
            'detail': ev['detail'], 'plain': spec['plain'],
            'invalidation': {
                'text': spec['invalidText'],
                'level': round(lvl, 4) if lvl is not None else None,
            },
            'evidenceId': f'event.{sid}',
        })
    rank = {'new': 0, 'active': 1, 'confirmed': 2, 'invalidated': 3}
    out.sort(key=lambda e: (e['barsAgo'], rank[e['status']], e['signalId']))
    return out


# ── 歷史統計（P2）─────────────────────────────────────────────
def ci95_pts(p: float, n: int) -> Optional[float]:
    """上漲比例的 95% 常態近似誤差半寬（百分點）；讓 UI 能說「差距小於誤差，視為無明顯差異」。"""
    if n <= 0:
        return None
    return round(1.96 * math.sqrt(max(0.0, p * (1.0 - p)) / n) * 100.0, 1)


def edge_verdict(edge_pts: Optional[float], ci_pts: Optional[float]) -> Optional[str]:
    if edge_pts is None or ci_pts is None:
        return None
    if abs(edge_pts) <= ci_pts:
        return 'noise'
    return 'above' if edge_pts > 0 else 'below'


def _median(vals: Sequence[float]) -> Optional[float]:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def event_indices(frame: Mapping[str, List[Any]], spec: Mapping[str, Any],
                  cooldown: int = STAT_COOLDOWN_BARS) -> List[int]:
    """整段歷史中此訊號的觸發根；同一訊號兩次觸發至少相隔 cooldown 根，避免同一波段重複計數。"""
    out: List[int] = []
    last_hit = -10 ** 9
    for i in range(1, len(frame['close'])):
        if i - last_hit < cooldown:
            continue
        if spec['detect'](frame, i):
            out.append(i)
            last_hit = i
    return out


def forward_outcomes(frame: Mapping[str, List[Any]], starts: Sequence[int], horizon: int,
                     direction: str, entry_lag: int = 0) -> List[Dict[str, float]]:
    """每個觸發根的前瞻結果：entry = t + entry_lag 的收盤；只收 entry+horizon 已存在的樣本。"""
    c, h, lo = frame['close'], frame['high'], frame['low']
    last = len(c) - 1
    out = []
    for t in starts:
        e = t + entry_lag
        x = e + horizon
        if x > last:
            continue
        ret = c[x] / c[e] - 1.0
        if direction == 'bear':
            adverse = max(h[e + 1: x + 1]) / c[e] - 1.0
        else:
            adverse = min(lo[e + 1: x + 1]) / c[e] - 1.0
        out.append({'t': t, 'ret': ret, 'adverse': adverse})
    return out


def signal_stats(frame: Mapping[str, List[Any]], spec: Mapping[str, Any],
                 horizons: Sequence[int] = STAT_HORIZONS,
                 min_sample: int = MIN_SAMPLE) -> Dict[str, Any]:
    """單一訊號在本檔歷史上的條件統計（PIT、已完成 horizon、樣本閘門）。"""
    starts = event_indices(frame, spec)
    lag = int(spec.get('entryLag', 0))
    n_bars = len(frame['close'])
    base_start = 60  # SMA60 成形後才有可比較的基準期間
    rows = []
    for hz in horizons:
        outs = forward_outcomes(frame, starts, hz, spec['direction'], lag)
        base = [frame['close'][e + hz] / frame['close'][e] - 1.0
                for e in range(base_start, n_bars - hz)]
        n = len(outs)
        row: Dict[str, Any] = {'horizon': hz, 'n': n, 'baseN': len(base)}
        if n >= min_sample and base:
            rets = [o['ret'] for o in outs]
            up = sum(1 for r in rets if r > 0) / n
            base_up = sum(1 for r in base if r > 0) / len(base)
            row.update({
                'gate': 'ok',
                'upRatio': round(up, 4),
                'medianRet': round(_median(rets), 5),
                'medianAdverse': round(_median([o['adverse'] for o in outs]), 5),
                'baseUpRatio': round(base_up, 4),
                'baseMedianRet': round(_median(base), 5),
                'edgePts': round((up - base_up) * 100.0, 1),
                'ci95Pts': ci95_pts(up, n),
            })
            row['edgeVerdict'] = edge_verdict(row['edgePts'], row['ci95Pts'])
        else:
            row.update({'gate': 'insufficient', 'upRatio': None, 'medianRet': None,
                        'medianAdverse': None, 'baseUpRatio': None, 'baseMedianRet': None,
                        'edgePts': None, 'ci95Pts': None, 'edgeVerdict': None})
        rows.append(row)
    return {
        'signalId': spec['id'], 'epistemic': EPISTEMIC_STATS,
        'events': len(starts), 'minSample': min_sample, 'horizons': rows,
        'window': {'from': frame['date'][0] if n_bars else None,
                   'to': frame['date'][-1] if n_bars else None, 'bars': n_bars},
        'method': ('本檔歷史逐根判斷（只用當根以前資料）；進場價 = 觸發日'
                   + ('次一交易日' if lag else '') + '收盤；只統計已走完天數的樣本；'
                   f'同訊號觸發間隔至少 {STAT_COOLDOWN_BARS} 根；樣本 < {min_sample} 不公開比例。'),
    }


# ── 五燈體檢 ─────────────────────────────────────────────────
def _light(key: str, label: str, state: str, tag: str, plain: str,
           values: Dict[str, Any]) -> Dict[str, Any]:
    return {'key': key, 'label': label, 'state': state, 'tag': tag, 'plain': plain,
            'values': values, 'evidenceId': f'light.{key}'}


def _trend_light(f, i):
    c, s20, s60, s60p = _g(f, 'close', i), _g(f, 'sma20', i), _g(f, 'sma60', i), _g(f, 'sma60', i - 5)
    vals = {'close': c, 'sma20': s20, 'sma60': s60,
            'sma60Slope5dPct': round(_pct(s60, s60p), 2) if _all(s60, s60p) else None}
    if not _all(c, s20, s60, s60p):
        return _light('trend', '趨勢', 'unknown', '資料不足', '歷史不足 65 根，無法判斷中期趨勢。', vals)
    if c > s60 and s20 > s60 and s60 > s60p:
        return _light('trend', '趨勢', 'bull', '上升', '股價在季線之上、季線往上，中期處於上升趨勢。', vals)
    if c < s60 and s20 < s60 and s60 < s60p:
        return _light('trend', '趨勢', 'bear', '下降', '股價在季線之下、季線往下，中期處於下降趨勢。', vals)
    side = '之上' if c >= s60 else '之下'
    return _light('trend', '趨勢', 'neutral', '盤整',
                  f'股價在季線{side}，但均線方向不一致，中期趨勢尚未明朗。', vals)


def _momentum_light(f, i):
    r, hst = _g(f, 'rsi', i), _g(f, 'macd_hist', i)
    vals = {'rsi14': round(r, 2) if r is not None else None,
            'macdHist': round(hst, 4) if hst is not None else None}
    if r is None:
        return _light('momentum', '動能', 'unknown', '資料不足', 'RSI 尚無資料。', vals)
    if r >= 70:
        return _light('momentum', '動能', 'caution', '過熱',
                      f'RSI {r:.0f}，短線漲多、買氣過熱，追價風險偏高。', vals)
    if r <= 30:
        return _light('momentum', '動能', 'caution', '超賣',
                      f'RSI {r:.0f}，短線跌深；超賣可以更超賣，等回升站上 30 再看。', vals)
    if hst is not None and hst > 0 and r >= 50:
        return _light('momentum', '動能', 'bull', '轉強', f'RSI {r:.0f} 且 MACD 在零軸上方，動能向上。', vals)
    if hst is not None and hst < 0 and r < 50:
        return _light('momentum', '動能', 'bear', '轉弱', f'RSI {r:.0f} 且 MACD 在零軸下方，動能向下。', vals)
    return _light('momentum', '動能', 'neutral', '持平', f'RSI {r:.0f}，動能方向不明顯。', vals)


def _volume_light(f, i):
    vx, vr = _g(f, 'volx', i), _g(f, 'vr', i)
    c, cp = _g(f, 'close', i), _g(f, 'close', i - 1)
    vals = {'volVs20d': round(vx, 2) if vx is not None else None,
            'vol5vs20': round(vr, 2) if vr is not None else None}
    if vx is None:
        return _light('volume', '量能', 'unknown', '資料不足', '成交量歷史不足 21 根。', vals)
    up = _all(c, cp) and c > cp
    down = _all(c, cp) and c < cp
    if vx >= 2.0 and up:
        return _light('volume', '量能', 'bull', '放量上漲', f'成交量是 20 日均量的 {vx:.1f} 倍且收漲，買盤積極。', vals)
    if vx >= 2.0 and down:
        return _light('volume', '量能', 'bear', '放量下跌', f'成交量是 20 日均量的 {vx:.1f} 倍且收跌，賣壓沉重。', vals)
    if vr is not None and vr < 0.6:
        return _light('volume', '量能', 'neutral', '量縮', '近 5 日成交量明顯低於月均量，交投清淡。', vals)
    return _light('volume', '量能', 'neutral', '正常', f'成交量為 20 日均量的 {vx:.1f} 倍，屬正常範圍。', vals)


def _chip_light(market: str, chips: Sequence[Mapping[str, Any]]):
    if market != 'TW':
        return _light('chip', '籌碼', 'unknown', '不適用', '美股沒有台灣三大法人買賣超資料。', {})
    if not chips:
        return _light('chip', '籌碼', 'unknown', '無資料',
                      '本機尚無此檔的法人歷史（chip_history 需每日盤後累積）。', {})
    st = chip_streaks(chips)
    recent = list(chips)[-5:]

    def s5(key):
        vals = [r.get(key) for r in recent if r.get(key) is not None]
        return round(sum(vals) / 1000.0) if vals else None
    vals = {'foreignStreak': st['foreign'], 'trustStreak': st['trust'],
            'foreign5dLots': s5('foreign'), 'trust5dLots': s5('trust'),
            'asOf': chips[-1]['date']}
    fo, tr = st['foreign'], st['trust']
    if (fo >= 3 or tr >= 3) and fo > -3 and tr > -3:
        who = '、'.join(x for x, s in (('外資', fo), ('投信', tr)) if s >= 3)
        return _light('chip', '籌碼', 'bull', '法人買', f'{who}連續買超，法人資金流入。', vals)
    if (fo <= -3 or tr <= -3) and fo < 3 and tr < 3:
        who = '、'.join(x for x, s in (('外資', fo), ('投信', tr)) if s <= -3)
        return _light('chip', '籌碼', 'bear', '法人賣', f'{who}連續賣超，法人資金流出。', vals)
    if (fo >= 3 and tr <= -3) or (fo <= -3 and tr >= 3):
        return _light('chip', '籌碼', 'caution', '分歧', '外資與投信方向相反，籌碼看法分歧。', vals)
    return _light('chip', '籌碼', 'neutral', '中性', '法人近期沒有連續性的買賣方向。', vals)


def _risk_light(f, i):
    c, a = _g(f, 'close', i), _g(f, 'atr', i)
    vals: Dict[str, Any] = {'atr14': round(a, 4) if a is not None else None}
    if not _all(c, a) or c <= 0:
        return _light('risk', '風險', 'unknown', '資料不足', 'ATR 尚無資料。', vals)
    atr_pct = a / c * 100.0
    hist = [f['atr'][k] / f['close'][k] * 100.0 for k in range(max(0, i - 250), i)
            if f['atr'][k] is not None and f['close'][k]]
    pr = _percentile_rank(hist, atr_pct) if len(hist) >= 60 else None
    peak = max(f['high'][max(0, i - 59): i + 1])
    dd = (c / peak - 1.0) * 100.0
    vals.update({'atrPct': round(atr_pct, 2), 'atrPctRank1y': round(pr, 1) if pr is not None else None,
                 'drawdownFrom60dHighPct': round(dd, 2)})
    if pr is not None and pr >= 80:
        return _light('risk', '風險', 'caution', '波動升高',
                      f'每日平均波動約 {atr_pct:.1f}%，高於過去一年 {pr:.0f}% 的日子，部位風險變大。', vals)
    if dd <= -15:
        return _light('risk', '風險', 'caution', '回檔較深', f'距近 60 日高點已回落 {abs(dd):.1f}%。', vals)
    return _light('risk', '風險', 'neutral', '平穩', f'每日平均波動約 {atr_pct:.1f}%，在正常範圍。', vals)


_TREND_PHRASE = {'bull': '中期上升趨勢', 'bear': '中期下降趨勢',
                 'neutral': '中期趨勢尚未明朗（盤整）', 'unknown': '資料不足以判斷中期趨勢'}
_CLAUSE = {
    ('momentum', '過熱'): (-1, '短線漲多過熱'), ('momentum', '超賣'): (0, '短線跌深超賣'),
    ('momentum', '轉強'): (1, '動能轉強'), ('momentum', '轉弱'): (-1, '動能轉弱'),
    ('volume', '放量上漲'): (1, '放量上漲'), ('volume', '放量下跌'): (-1, '放量下跌'),
    ('chip', '法人買'): (1, '法人連續買超'), ('chip', '法人賣'): (-1, '法人連續賣超'),
    ('chip', '分歧'): (0, '法人看法分歧'),
    ('risk', '波動升高'): (0, '波動升高'), ('risk', '回檔較深'): (0, '距高點回落較深'),
}


def summarize(lights: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """確定性白話摘要（不經 LLM）：趨勢為主句，其餘燈號依是否同向接「且／但」。"""
    by = {l['key']: l for l in lights}
    trend = by.get('trend', {}).get('state', 'unknown')
    supports, contrasts = [], []
    for key in ('momentum', 'volume', 'chip', 'risk'):
        l = by.get(key)
        if not l:
            continue
        pol_phrase = _CLAUSE.get((key, l['tag']))
        if not pol_phrase:
            continue
        pol, phrase = pol_phrase
        if trend == 'bull':
            (supports if pol > 0 else contrasts).append(phrase)
        elif trend == 'bear':
            (supports if pol < 0 else contrasts).append(phrase)
        else:
            (contrasts if pol <= 0 else supports).append(phrase)
    s = _TREND_PHRASE[trend]
    if trend in ('bull', 'bear') and contrasts:
        s += '未變，但' + '、'.join(contrasts[:2])
    elif trend in ('bull', 'bear') and supports:
        s += '，且' + '、'.join(supports[:2])
    elif trend not in ('bull', 'bear') and (supports or contrasts):
        s += '；目前' + '、'.join((supports + contrasts)[:2])
    s += '。'
    if trend == 'bull' and any(p in contrasts for p in ('短線漲多過熱', '波動升高')):
        s += '追價風險偏高，先看失效價位再決定。'
    elif trend == 'bear' and contrasts:
        s += '反彈未必是回升，確認站回季線前宜保守。'
    bull = sum(1 for l in lights if l['state'] == 'bull')
    bear = sum(1 for l in lights if l['state'] == 'bear')
    overall = 'bull' if bull > bear and bull >= 2 else 'bear' if bear > bull and bear >= 2 else (
        'mixed' if bull and bear else 'neutral')
    return {'sentence': s, 'overall': overall, 'bullLights': bull, 'bearLights': bear}


def invalidation_hint(frame: Mapping[str, List[Any]], trend_state: str) -> Optional[Dict[str, Any]]:
    """卡片層級「什麼情況代表判斷錯了」。"""
    i = len(frame['close']) - 1
    c, s60 = _g(frame, 'close', i), _g(frame, 'sma60', i)
    if trend_state in ('bull', 'bear') and _all(c, s60):
        dist = _pct(s60, c)
        if trend_state == 'bull':
            text = f'收盤跌破季線 {_fmt(s60)}（距今 {dist:+.1f}%）代表中期上升趨勢轉弱'
        else:
            text = f'收盤站回季線 {_fmt(s60)}（距今 {dist:+.1f}%）才代表下跌趨勢可能結束'
        return {'kind': 'ma60', 'level': round(s60, 4), 'distancePct': round(dist, 2), 'text': text,
                'evidenceId': 'ind.sma60'}
    hi = ind.prior_extreme(frame['high'], 20, i, highest=True)
    lo = ind.prior_extreme(frame['low'], 20, i, highest=False)
    if _all(hi, lo, c):
        return {'kind': 'range20', 'upper': round(hi, 4), 'lower': round(lo, 4),
                'text': f'收盤突破 {_fmt(hi)} 或跌破 {_fmt(lo)}（前 20 日高低點）之前，視為區間整理',
                'evidenceId': 'ind.range20'}
    return None


# ── 對外主函式 ───────────────────────────────────────────────
def analyze(bars: Sequence[Mapping[str, Any]], *, symbol: str, market: str = 'TW',
            chips: Optional[Sequence[Mapping[str, Any]]] = None,
            provisional_last: bool = False, with_stats: bool = True,
            as_of_note: Optional[str] = None) -> Dict[str, Any]:
    """bars 為 ``normalize_bars`` 輸出（由舊到新）。回傳完整個股體檢契約。"""
    chips = list(chips or [])
    base = {
        'contractVersion': CONTRACT_VERSION, 'engine': ENGINE_ID, 'symbol': symbol,
        'market': market, 'epistemic': {'events': EPISTEMIC_EVENTS, 'stats': EPISTEMIC_STATS},
        'disclaimer': DISCLAIMER,
    }
    if len(bars) < MIN_BARS:
        base.update({'ok': False, 'reason': 'INSUFFICIENT_BARS', 'bars': len(bars),
                     'message': f'日線不足 {MIN_BARS} 根，無法產生可靠的體檢。'})
        return base
    frame = build_frame(bars, chips)
    i = len(bars) - 1
    lights = [_trend_light(frame, i), _momentum_light(frame, i), _volume_light(frame, i),
              _chip_light(market, chips), _risk_light(frame, i)]
    summary = summarize(lights)
    events = recent_events(frame, provisional_last=provisional_last)
    stats: Dict[str, Any] = {}
    if with_stats:
        wanted = {e['signalId'] for e in events}
        for spec in SIGNALS:
            if spec['id'] in wanted:
                stats[spec['id']] = signal_stats(frame, spec)
        for e in events:
            e['stats'] = stats.get(e['signalId'])
    c, cp = frame['close'][i], frame['close'][i - 1]
    macd_h = frame['macd_hist'][i]
    indicators_out = {
        'close': c, 'chgPct': round(_pct(c, cp), 2) if cp else None,
        'sma5': frame['sma5'][i], 'sma20': frame['sma20'][i], 'sma60': frame['sma60'][i],
        'rsi14': frame['rsi'][i], 'macd': frame['macd'][i], 'macdSignal': frame['macd_sig'][i],
        'macdHist': macd_h, 'bbUpper': frame['bb_u'][i], 'bbLower': frame['bb_l'][i],
        'atr14': frame['atr'][i], 'volVs20d': frame['volx'][i], 'vol5vs20': frame['vr'][i],
        'high20': ind.prior_extreme(frame['high'], 20, i, highest=True),
        'low20': ind.prior_extreme(frame['low'], 20, i, highest=False),
    }
    indicators_out = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in indicators_out.items()}
    inval = invalidation_hint(frame, lights[0]['state'])
    base.update({
        'ok': True,
        'asOf': frame['date'][i],
        'bars': len(bars),
        'session': {'provisional': bool(provisional_last),
                    'note': as_of_note or ('盤中暫定：最後一根 K 尚未收盤，今日事件以收盤確認為準'
                                           if provisional_last else '最後一根為已收盤日 K')},
        'health': {'lights': lights, 'summary': summary, 'invalidation': inval},
        'events': events,
        'indicators': indicators_out,
        'chip': {'asOf': chips[-1]['date'], 'days': len(chips)} if chips else None,
    })
    base['evidence'] = build_evidence(base)
    return base


def build_evidence(result: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """把體檢結果攤平成可引用的證據表（AI 敘事只能引用這些 id）。"""
    ev: Dict[str, Dict[str, Any]] = {}
    as_of = result.get('asOf')
    labels = {'close': '收盤價', 'chgPct': '日漲跌%', 'sma20': '20 日均線', 'sma60': '季線（60 日均線）',
              'rsi14': 'RSI14', 'macdHist': 'MACD 柱狀體', 'atr14': 'ATR14',
              'volVs20d': '量 / 20 日均量', 'high20': '前 20 日高點', 'low20': '前 20 日低點'}
    for k, lab in labels.items():
        v = (result.get('indicators') or {}).get(k)
        if v is not None:
            ev[f'ind.{k}'] = {'label': lab, 'value': v, 'asOf': as_of}
    for l in (result.get('health') or {}).get('lights') or []:
        ev[l['evidenceId']] = {'label': f"{l['label']}燈：{l['tag']}", 'value': l['values'],
                               'text': l['plain'], 'asOf': as_of}
    inval = (result.get('health') or {}).get('invalidation')
    if inval:
        ev['health.invalidation'] = {'label': '失效條件', 'value': inval, 'text': inval['text'],
                                     'asOf': as_of}
        if inval.get('kind') == 'range20':
            ev['ind.range20'] = {'label': '前 20 日區間', 'value':
                                 {'upper': inval['upper'], 'lower': inval['lower']}, 'asOf': as_of}
    summ = (result.get('health') or {}).get('summary')
    if summ:
        ev['health.summary'] = {'label': '規則摘要', 'text': summ['sentence'], 'value': summ['overall'],
                                'asOf': as_of}
    for e in result.get('events') or []:
        ev[e['evidenceId']] = {'label': e['label'], 'value': {
            'date': e['date'], 'status': e['status'], 'statusLabel': e['statusLabel'],
            'direction': e['directionLabel'], 'level': e['invalidation']['level'],
            'invalidation': e['invalidation']['text'], 'meaning': e['plain']},
            'text': e['detail'], 'asOf': e['date']}
        st = e.get('stats') or {}
        for row in st.get('horizons') or []:
            ev[f"stats.{e['signalId']}.h{row['horizon']}"] = {
                'label': f"{e['label']}：之後 {row['horizon']} 日統計", 'value': row,
                'asOf': as_of, 'epistemic': EPISTEMIC_STATS}
    return ev


def compact(result: Mapping[str, Any]) -> Dict[str, Any]:
    """自選股總表用的精簡版（燈號、摘要、今日／近期事件數）。"""
    if not result.get('ok'):
        return {'symbol': result.get('symbol'), 'market': result.get('market'), 'ok': False,
                'reason': result.get('reason'), 'message': result.get('message')}
    events = result.get('events') or []
    return {
        'symbol': result['symbol'], 'market': result['market'], 'ok': True,
        'asOf': result['asOf'], 'provisional': result['session']['provisional'],
        'close': result['indicators']['close'], 'chgPct': result['indicators']['chgPct'],
        'lights': [{'key': l['key'], 'label': l['label'], 'state': l['state'], 'tag': l['tag']}
                   for l in result['health']['lights']],
        'summary': result['health']['summary'],
        'invalidation': result['health']['invalidation'],
        'events': [{'signalId': e['signalId'], 'label': e['label'], 'direction': e['direction'],
                    'date': e['date'], 'barsAgo': e['barsAgo'], 'status': e['status'],
                    'statusLabel': e['statusLabel'], 'provisional': e['provisional']}
                   for e in events if e['status'] != 'invalidated'],
    }
