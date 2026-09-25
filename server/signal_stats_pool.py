# -*- coding: utf-8 -*-
"""同市場合併統計（P2）：每個訊號在本機日線庫所有標的上的條件統計與「成績單」。

單一個股的歷史常常只有個位數樣本；合併同市場所有標的後才有足夠樣本判斷
「這個訊號出現後，接下來 5／20 日的表現是否和隨便挑一天不同」。

紀律
----
* 逐檔用 ``stock_signals`` 同一套偵測與前瞻計算（PIT、只收已完成 horizon、同訊號冷卻）。
* 基準 = 同一批標的「所有交易日」的 5／20 日報酬，讓使用者看到訊號相對基準的差距，
  而不是只看一個看起來很高的上漲比例。
* 合併樣本 < POOLED_MIN_SAMPLE（100）或貢獻標的 < MIN_SYMBOLS 不公開比例；
  另附 95% 誤差範圍，差距落在誤差內即標示「無明顯差異」。
* 另把事件依日期切成前後兩半，列出兩段的上漲比例，作為穩定度參考（非顯著性檢定）。
* 限制：標的清單是「目前在本機 DB 的代號」，已下市股票不在其中（存活者偏差）；
  價格未還原除權息。這兩點寫進輸出的 ``caveats``。

計算量約為「標的數 × 日 K 數 × 15 個訊號」，只在背景任務裡跑，結果快取到
``data/stock_signal_pooled_stats.json``，個股卡片只讀快取。
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from . import stock_signals as ss
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
except ImportError:
    import stock_signals as ss
    from atomic_store import StoreCorruptError, atomic_write_json, load_json

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(_BASE, 'data', 'stock_signal_pooled_stats.json')
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')
MIN_SYMBOLS = 5
# 合併樣本的門檻比單檔（20）嚴格：隨機漫步資料在 n≈20 時上漲比例誤差約 ±22 個百分點
POOLED_MIN_SAMPLE = 100
MIN_BARS_POOL = 250
BIN = 0.0005          # 基準中位數以 0.05% 分箱計算（全日樣本動輒數百萬筆）
BIN_LIMIT = 0.6
JOB_PREFIX = 'stock-signal-pooled-'
# 只收真實股票／ETF 代號；同一張 bars 表也存了指數（^TWII）與合成序列（__MARGIN_RATIO__）
_TICKER_RE = {'TW': re.compile(r'^\d{4,6}[A-Z]?$'), 'US': re.compile(r'^[A-Z][A-Z0-9.\-]{0,9}$')}

_mem: Dict[str, Dict[str, Any]] = {}
_mem_mtime: Dict[str, float] = {}


class _BinnedBase:
    """全交易日前瞻報酬：精確上漲比例 + 分箱中位數（避免把數百萬筆浮點數放進記憶體）。"""

    def __init__(self):
        self.n = 0
        self.up = 0
        self.bins: Dict[int, int] = {}

    def add(self, r: float) -> None:
        self.n += 1
        if r > 0:
            self.up += 1
        k = int(round(max(-BIN_LIMIT, min(BIN_LIMIT, r)) / BIN))
        self.bins[k] = self.bins.get(k, 0) + 1

    def median(self) -> Optional[float]:
        if not self.n:
            return None
        target, run = (self.n + 1) / 2.0, 0
        for k in sorted(self.bins):
            run += self.bins[k]
            if run >= target:
                return k * BIN
        return None


def _load_all_chips(chip_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """一次讀完所有 chip_history 檔 → {code: [由舊到新]}（合併統計需要完整期間）。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not chip_dir or not os.path.isdir(chip_dir):
        return out
    for fn in sorted(glob.glob(os.path.join(chip_dir, '*.json'))):
        stem = os.path.splitext(os.path.basename(fn))[0]
        if len(stem) != 8 or not stem.isdigit():
            continue
        try:
            with open(fn, encoding='utf-8') as f:
                day = json.load(f)
        except Exception:
            continue
        if not isinstance(day, dict):
            continue
        d = f'{stem[:4]}-{stem[4:6]}-{stem[6:]}'
        for code, rec in day.items():
            if isinstance(rec, dict):
                out.setdefault(code, []).append({
                    'date': d, 'foreign': ss._finite(rec.get('foreign')),
                    'trust': ss._finite(rec.get('trust'))})
    return out


def compute_pooled(series: Iterable[tuple], *, market: str = 'TW',
                   horizons: Sequence[int] = ss.STAT_HORIZONS,
                   min_sample: int = POOLED_MIN_SAMPLE,
                   chips: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
                   progress: Optional[Callable[[int], None]] = None) -> Dict[str, Any]:
    """series: 可疊代的 (code, bars)；bars 為 ``ss.normalize_bars`` 輸出。"""
    t0 = time.time()
    acc: Dict[str, Dict[int, List[Dict[str, Any]]]] = {s['id']: {h: [] for h in horizons} for s in ss.SIGNALS}
    contrib: Dict[str, set] = {s['id']: set() for s in ss.SIGNALS}
    base = {h: _BinnedBase() for h in horizons}
    n_symbols, last_date, first_date = 0, None, None
    for idx, (code, bars) in enumerate(series):
        if len(bars) < MIN_BARS_POOL:
            continue
        n_symbols += 1
        frame = ss.build_frame(bars, (chips or {}).get(code))
        dates, closes = frame['date'], frame['close']
        last_date = max(last_date or dates[-1], dates[-1])
        first_date = min(first_date or dates[0], dates[0])
        for hz in horizons:
            b = base[hz]
            for e in range(60, len(closes) - hz):
                b.add(closes[e + hz] / closes[e] - 1.0)
        for spec in ss.SIGNALS:
            starts = ss.event_indices(frame, spec)
            if not starts:
                continue
            lag = int(spec.get('entryLag', 0))
            for hz in horizons:
                outs = ss.forward_outcomes(frame, starts, hz, spec['direction'], lag)
                for o in outs:
                    acc[spec['id']][hz].append({'date': dates[o['t']], 'ret': o['ret'],
                                                'adverse': o['adverse']})
                if outs:
                    contrib[spec['id']].add(code)
        if progress and idx % 50 == 0:
            progress(idx)
    signals: Dict[str, Any] = {}
    for spec in ss.SIGNALS:
        rows = []
        for hz in horizons:
            outs = sorted(acc[spec['id']][hz], key=lambda o: o['date'])
            n, b = len(outs), base[hz]
            row: Dict[str, Any] = {'horizon': hz, 'n': n, 'baseN': b.n,
                                   'symbols': len(contrib[spec['id']])}
            if n >= min_sample and len(contrib[spec['id']]) >= MIN_SYMBOLS and b.n:
                rets = [o['ret'] for o in outs]
                up = sum(1 for r in rets if r > 0) / n
                base_up = b.up / b.n
                half = n // 2
                older, recent = rets[:half], rets[half:]
                row.update({
                    'gate': 'ok',
                    'upRatio': round(up, 4),
                    'medianRet': round(ss._median(rets), 5),
                    'medianAdverse': round(ss._median([o['adverse'] for o in outs]), 5),
                    'baseUpRatio': round(base_up, 4),
                    'baseMedianRet': round(b.median(), 5) if b.median() is not None else None,
                    'edgePts': round((up - base_up) * 100.0, 1),
                    'ci95Pts': ss.ci95_pts(up, n),
                    'edgeVerdict': ss.edge_verdict(round((up - base_up) * 100.0, 1), ss.ci95_pts(up, n)),
                    'stability': {
                        'olderUpRatio': round(sum(1 for r in older if r > 0) / len(older), 4)
                        if len(older) >= min_sample else None,
                        'recentUpRatio': round(sum(1 for r in recent if r > 0) / len(recent), 4)
                        if len(recent) >= min_sample else None,
                        'splitDate': outs[half]['date'] if n else None,
                    },
                })
            else:
                row.update({'gate': 'insufficient', 'upRatio': None, 'medianRet': None,
                            'medianAdverse': None, 'baseUpRatio': None, 'baseMedianRet': None,
                            'edgePts': None, 'ci95Pts': None, 'edgeVerdict': None, 'stability': None})
            rows.append(row)
        signals[spec['id']] = {'signalId': spec['id'], 'label': spec['label'],
                               'direction': spec['direction'], 'family': spec['family'],
                               'horizons': rows, 'symbols': len(contrib[spec['id']])}
    return {
        'contractVersion': ss.CONTRACT_VERSION, 'engine': ss.ENGINE_ID, 'market': market,
        'epistemic': ss.EPISTEMIC_STATS, 'generatedAt': datetime.now(ss._TZ['TW']).isoformat(timespec='seconds'),
        'symbols': n_symbols, 'window': {'from': first_date, 'to': last_date},
        'minSample': min_sample, 'minSymbols': MIN_SYMBOLS, 'elapsedSec': round(time.time() - t0, 1),
        'signals': signals,
        'method': ('逐檔以同一套規則偵測（只用當根以前資料），合併同市場所有標的；進場＝觸發日收盤'
                   '（籌碼訊號為次一交易日收盤）；只統計已走完天數的樣本；基準＝同批標的所有交易日。'),
        'caveats': ['標的為目前在本機日線庫的代號，已下市股票不在其中（存活者偏差）。',
                    '價格未還原除權息，除息日的跳空會被算進報酬。',
                    '穩定度只比較前後兩段的上漲比例，不是統計顯著性檢定。',
                    '同時比較 15 個訊號 × 2 種天數，即使全是雜訊，也常有 1～2 個因巧合落在誤差範圍外；'
                    '請同時看「前段→近段」是否一致。'],
    }


def iter_datastore(market: str, symbols: Optional[Sequence[str]] = None,
                   chunk: int = 200) -> Iterable[tuple]:
    """從本機 DB 分批讀日 K（沿用 datastore.get_bars_bulk，與選股同一讀取路徑）。"""
    import datastore
    datastore.init_db()
    codes = list(symbols) if symbols else datastore.list_symbols(market, MIN_BARS_POOL)
    pattern = _TICKER_RE.get(market)
    if pattern:
        codes = [c for c in codes if pattern.match(str(c))]
    for i in range(0, len(codes), chunk):
        bulk = datastore.get_bars_bulk(codes[i:i + chunk], market=market)
        for code in codes[i:i + chunk]:
            yield code, ss.normalize_bars(bulk.get(code) or [], market)


def refresh(market: str = 'TW', *, symbols: Optional[Sequence[str]] = None,
            chip_dir: Optional[str] = None, cache_file: Optional[str] = None) -> Dict[str, Any]:
    chips = _load_all_chips(chip_dir or CHIP_HISTORY_PATH) if market == 'TW' else {}
    result = compute_pooled(iter_datastore(market, symbols), market=market, chips=chips)
    path = cache_file or CACHE_FILE
    try:
        allc = load_json(path, default={}, expected_type=dict)
    except StoreCorruptError:
        allc = {}
    allc[market] = result
    atomic_write_json(path, allc, backup=True, indent=None)
    _mem.pop(path, None)
    return result


def load_cached(market: str, cache_file: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """讀快取（檔案 mtime 變了才重讀）。"""
    path = cache_file or CACHE_FILE
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if path not in _mem or _mem_mtime.get(path) != mtime:
        try:
            _mem[path] = load_json(path, default={}, expected_type=dict)
        except StoreCorruptError:
            return None
        _mem_mtime[path] = mtime
    return (_mem.get(path) or {}).get(market)


def attach(result: Dict[str, Any], pooled: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """把合併統計掛到個股體檢的每個事件（pooledStats），並加進證據表。"""
    if not pooled or not result.get('ok'):
        return result
    for e in result.get('events') or []:
        sig = (pooled.get('signals') or {}).get(e['signalId'])
        if not sig:
            continue
        e['pooledStats'] = {'symbols': pooled.get('symbols'), 'generatedAt': pooled.get('generatedAt'),
                            'window': pooled.get('window'), 'horizons': sig['horizons']}
        ev = result.setdefault('evidence', {})
        for row in sig['horizons']:
            ev[f"pooled.{e['signalId']}.h{row['horizon']}"] = {
                'label': f"{e['label']}：同市場 {pooled.get('symbols')} 檔合併後 {row['horizon']} 日統計",
                'value': row, 'asOf': pooled.get('generatedAt'), 'epistemic': ss.EPISTEMIC_STATS}
    result['pooled'] = {'available': True, 'symbols': pooled.get('symbols'),
                        'generatedAt': pooled.get('generatedAt'), 'window': pooled.get('window')}
    return result


def scoreboard(pooled: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """訊號成績單：依 5 日「相對基準差距」排序；樣本不足者排最後。"""
    if not pooled:
        return []
    rows = []
    for spec in ss.SIGNALS:
        sig = (pooled.get('signals') or {}).get(spec['id'])
        if not sig:
            continue
        h5 = next((r for r in sig['horizons'] if r['horizon'] == 5), None)
        rows.append({'signalId': spec['id'], 'label': spec['label'], 'family': spec['family'],
                     'familyLabel': ss.FAMILY_LABEL[spec['family']], 'direction': spec['direction'],
                     'directionLabel': ss.DIRECTION_LABEL[spec['direction']],
                     'horizons': sig['horizons'], 'sortEdge': h5.get('edgePts') if h5 else None})
    rows.sort(key=lambda r: (r['sortEdge'] is None, -(abs(r['sortEdge']) if r['sortEdge'] is not None else 0)))
    return rows
