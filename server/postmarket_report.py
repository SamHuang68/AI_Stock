# -*- coding: utf-8 -*-
"""自選股盤後敘事日報（postmarket-daily）— EvidencePack builder + Claude 敘事 orchestration。

紅線（v1，見 docs/POSTMARKET_DAILY.md）：
- LLM 只負責整理敘事／假說／明日觀察；regime、支撐壓力、信心分數、曝險區間
  一律沿用 DecisionContext／規則層既有數值（唯讀快照），禁止請模型重算。
- 不 mutate ST 狀態：不加倉、不改 feature flags、不動 DecisionContext 公式。
- 雲端 Claude only（ai_api）；WaveDeck 持有 llm_gate 時回 503 + Retry-After，
  絕不自動改打本機 deep（避免 ST + WaveDeck stampede）。
- 每個數字主張必須能對上 server 端組好的 EvidencePack；證據過期要在
  narrative.risks 首條標「資料可能過期」（盤後 >6h、盤中 >1h）。
- 預設禁止輸出買賣建議與目標價；違規內容由 guardrail 直接移除。

資料來源全部沿用既有 ST 管線（datastore 日K、chip_api、market_flash、
decision_context、universe），缺資料以空陣列／省略 + notes 說明，不新開爬蟲。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover - tzdata missing
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))

ROOT = Path(__file__).resolve().parents[1]

GATE_OWNER = 'st'
GATE_PURPOSE = 'postmarket-daily'
GATE_TTL_SEC = 120.0
GATE_WAIT_SEC = 2.0

MAX_SYMBOLS = 20
MAX_NEWS_PER_SYMBOL = 10
DEFAULT_NEWS_PER_SYMBOL = 5
MAX_EVIDENCE_CHARS = 200_000          # 413 防護：單一請求 context 上限（序列化字元數）
STALE_POSTCLOSE_HOURS = 6.0
STALE_INTRADAY_HOURS = 1.0
STALE_RISK_PREFIX = '資料可能過期'
PER_SYMBOL_MAX_TOKENS = 1200
BLURB_MAX_TOKENS = 200
BARS_LOOKBACK = 90

# 預設禁止的喊單／目標價語彙（驗收 §9-4；guardrail 直接移除命中片段）
FORBIDDEN_PATTERNS = (
    '目標價', '建議買進', '建議買入', '建議賣出', '建議加碼', '建議減碼',
    '買進建議', '賣出建議', '保證獲利', '穩賺', '全力買進', '全力做多',
    'target price', 'buy recommendation', 'sell recommendation',
)

NARRATIVE_LIST_KEYS = ('drivers', 'hypotheses', 'risks', 'watchTomorrow')
CITATION_TYPES = {'quote', 'chip', 'tech', 'news', 'decision'}

# Anthropic 每百萬 token 粗估價（USD）：(model substring, input, output)
_PRICES = (('opus', 15.0, 75.0), ('sonnet', 3.0, 15.0), ('haiku', 0.8, 4.0))

_lock = threading.RLock()
_aborts: set[str] = set()

# 可注入存取器（server.py 開機 configure；測試亦由此替身）。
# 全部為「沿用既有資料管線」的薄轉接，禁止在此新開資料來源。
_accessors: Dict[str, Optional[Callable[..., Any]]] = {
    'bars_fn': None,        # (code) -> [(ts, o, h, l, c, v), ...]
    'chip_fn': None,        # (code) -> chip_api.build_chip 輸出
    'news_fn': None,        # () -> market_flash.build_flash 輸出（items 內含 code）
    'decision_fn': None,    # () -> decision_context.latest_context() 唯讀快照
    'universe_fn': None,    # () -> universe.load() 輸出
    'sectors_fn': None,     # () -> {code: 產業別}
    'anthropic_fn': None,   # (messages, *, system, model, max_tokens) -> (text, raw)
}


def configure(**kwargs: Optional[Callable[..., Any]]) -> None:
    for key, value in kwargs.items():
        if key in _accessors:
            _accessors[key] = value


# ── 中止註冊表（abortSignalClientId） ────────────────────────────────────────

def signal_abort(client_id: str) -> None:
    cid = str(client_id or '').strip()
    if not cid:
        return
    with _lock:
        _aborts.add(cid[:80])


def is_aborted(client_id: Optional[str]) -> bool:
    cid = str(client_id or '').strip()
    if not cid:
        return False
    with _lock:
        return cid[:80] in _aborts


def clear_abort(client_id: Optional[str]) -> None:
    cid = str(client_id or '').strip()
    if not cid:
        return
    with _lock:
        _aborts.discard(cid[:80])


# ── 預設存取器（沿用既有模組；失敗回 None／空） ─────────────────────────────

def _default_bars(code: str):
    import datastore
    return datastore.get_bars(code, limit=BARS_LOOKBACK, market='TW')


def _default_chip(code: str):
    import chip_api
    return chip_api.build_chip(code)


def _default_news():
    import market_flash
    return market_flash.build_flash(60)


def _default_decision():
    import decision_context
    return decision_context.latest_context()


def _default_universe():
    import universe
    return universe.load()


def _default_anthropic(api_key: str):
    import ai_api

    def call(messages, *, system=None, model=None, max_tokens=1024):
        return ai_api.anthropic_messages(
            api_key, messages, max_tokens=max_tokens, system=system, model=model,
        )
    return call


def _get(name: str, fallback: Callable[..., Any]) -> Callable[..., Any]:
    fn = _accessors.get(name)
    return fn if callable(fn) else fallback


# ── EvidencePack builder（無 LLM） ──────────────────────────────────────────

def _tw_close_iso(ts: float) -> str:
    """日K bar 的 asOf 定為該交易日 13:30 Asia/Taipei（台股現貨收盤）。"""
    day = datetime.fromtimestamp(float(ts), TZ_TPE).date()
    return datetime.combine(day, dtime(13, 30), tzinfo=TZ_TPE).isoformat()


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def quote_from_bars(bars) -> Optional[Dict[str, Any]]:
    """既有 datastore 日K → 盤後報價證據。無資料回 None。"""
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if not rows:
        return None
    ts, _o, _h, _l, close, volume = rows[-1][:6]
    prev = rows[-2][4] if len(rows) >= 2 else None
    change_pct = None
    if prev not in (None, 0):
        change_pct = _round((close - prev) / prev * 100)
    return {
        'last': _round(close),
        'prevClose': _round(prev),
        'changePct': change_pct,
        'volume': int(volume) if volume is not None else None,
        'volumeUnit': 'shares',
        'asOf': _tw_close_iso(ts),
        'session': 'closed',
        'source': 'datastore-daily',
    }


def tech_summary_from_bars(bars) -> Optional[Dict[str, Any]]:
    """既有 indicators（精準 Wilder RSI／完整 SMA）→ 數字摘要，非 LLM 解讀。"""
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if len(rows) < 2:
        return None
    import indicators as ind
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows if r[2] is not None]
    lows = [float(r[3]) for r in rows if r[3] is not None]
    vols = [float(r[5] or 0) for r in rows]
    n = len(closes)
    v5 = sum(vols[-5:]) / 5 if n >= 5 else None
    v20 = sum(vols[-20:]) / 20 if n >= 20 else None
    return {
        'close': _round(closes[-1]),
        'sma5': _round(ind.sma(closes, 5)),
        'sma20': _round(ind.sma(closes, 20)),
        'sma60': _round(ind.sma(closes, 60)),
        'rsi14': _round(ind.rsi_wilders(closes, 14)),
        'volRatio': _round(v5 / v20) if v5 and v20 else None,
        'high20': _round(max(highs[-21:-1])) if len(highs) >= 21 else None,
        'low20': _round(min(lows[-21:-1])) if len(lows) >= 21 else None,
        'bars': n,
        'asOf': _tw_close_iso(rows[-1][0]),
    }


def _chip_as_of(chip: Optional[Dict[str, Any]]) -> Optional[str]:
    raw = str((chip or {}).get('date') or '').strip()
    if len(raw) == 8 and raw.isdigit():
        return f'{raw[:4]}-{raw[4:6]}-{raw[6:]}'
    return raw or None


def _chip_evidence(chip: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(chip, dict):
        return None
    out: Dict[str, Any] = {'asOf': _chip_as_of(chip)}
    for key in ('inst', 'margin', 'shortLend', 'dayTrade', 'streak'):
        if chip.get(key):
            out[key] = chip[key]
    holders = chip.get('holders')
    if isinstance(holders, dict) and holders.get('ok'):
        out['holders'] = {'last': holders.get('last'), 'risk': holders.get('risk')}
    if len(out) <= 1:
        return None
    return out


def decision_snapshot(context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """DecisionContext 唯讀快照（市場層級，作為證據；禁止請模型重算）。"""
    if not isinstance(context, dict) or not context:
        return None
    regime = context.get('regime') or {}
    env = context.get('actionEnvelope') or {}
    levels = ((context.get('keyLevels') or {}).get('levels') or {})
    quality = context.get('dataQuality') or {}
    return {
        'asOf': context.get('asOf'),
        'market': context.get('market'),
        'regime': {k: regime.get(k) for k in ('id', 'label', 'score', 'confidence')},
        'posture': env.get('posture'),
        'levels': {k: levels.get(k) for k in ('r1', 'pivot', 's1')},
        'dataQuality': {k: quality.get(k) for k in ('completeness', 'freshness')},
        'readOnly': True,
    }


def _news_for_symbol(flash: Optional[Dict[str, Any]], code: str, limit: int) -> List[Dict[str, Any]]:
    items = (flash or {}).get('items') or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if str(item.get('code') or '').strip() != code:
            continue
        out.append({
            'title': item.get('title'),
            'source': item.get('source'),
            'time': item.get('time'),
            'url': item.get('url'),
        })
        if len(out) >= limit:
            break
    return out


def _universe_meta(code: str, uni: Optional[Dict[str, Any]],
                   sectors: Optional[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    tw = (uni or {}).get('tw') or {}
    twmeta = (uni or {}).get('twmeta') or {}
    name = tw.get(code) or (twmeta.get(code) or {}).get('zh')
    if name:
        meta['name'] = name
    board = (twmeta.get(code) or {}).get('board')
    if board:
        meta['board'] = board
    industry = (sectors or {}).get(code)
    if industry:
        meta['industry'] = industry
    return meta or None


def staleness(quote: Optional[Dict[str, Any]], now: datetime) -> List[str]:
    """quote asOf 早於報告時間逾閾值 → 過期理由清單（盤後 6h／盤中 1h）。"""
    if not quote or not quote.get('asOf'):
        return ['quote 無 asOf（資料不足）']
    try:
        as_of = datetime.fromisoformat(str(quote['asOf']))
    except ValueError:
        return [f"quote asOf 無法解析（{quote['asOf']}）"]
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=TZ_TPE)
    session = str(quote.get('session') or 'closed').lower()
    limit_hours = STALE_INTRADAY_HOURS if session in ('regular', 'intraday') else STALE_POSTCLOSE_HOURS
    age_hours = (now - as_of).total_seconds() / 3600.0
    if age_hours > limit_hours:
        return [f"quote asOf {quote['asOf']} 距報告時間 {age_hours:.1f}h，逾 {limit_hours:g}h 門檻"]
    return []


# ── Slice 3：規則異常 + 明日驗證點（無 LLM 數字）────────────────────────────

MAX_VALIDATION_POINTS = 3
VOL_SPIKE_RATIO = 1.5
VOL_SHRINK_RATIO = 0.65
MA_DEVIATION_PCT = 2.0
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
INST_SIGNIFICANT_SHARES = 1_000_000  # ≈1000 張
MARGIN_CHANGE_SIGNIFICANT = 500.0


def _next_tw_session_date(now: datetime) -> str:
    """盤後 workflow 的「明日」= 下一個台股現貨交易日（ISO date）。"""
    local = now.astimezone(TZ_TPE)
    candidate = local.date() + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _anomaly(
    anomaly_id: str,
    *,
    metric: str,
    value: Any,
    threshold: Any,
    direction: str,
    label: str,
    as_of: Optional[str],
    severity: str = 'watch',
) -> Dict[str, Any]:
    return {
        'id': anomaly_id,
        'metric': metric,
        'value': value,
        'threshold': threshold,
        'direction': direction,
        'label': label,
        'epistemic': 'FACT',
        'severity': severity,
        'asOf': as_of,
    }


def detect_anomalies(
    quote: Optional[Dict[str, Any]],
    tech: Optional[Dict[str, Any]],
    chips: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """從 ST 已算好的 quote／tech／chips 產出規則異常清單（無 LLM）。"""
    anomalies: List[Dict[str, Any]] = []
    tech = tech or {}
    quote = quote or {}
    as_of = tech.get('asOf') or quote.get('asOf')

    vol_ratio = tech.get('volRatio')
    if vol_ratio is not None:
        if float(vol_ratio) >= VOL_SPIKE_RATIO:
            anomalies.append(_anomaly(
                'volume_spike', metric='techSummary.volRatio', value=_round(vol_ratio),
                threshold=VOL_SPIKE_RATIO, direction='above',
                label=f'量能放大（5日/20日均 {float(vol_ratio):.2f}）',
                as_of=as_of, severity='watch',
            ))
        elif float(vol_ratio) <= VOL_SHRINK_RATIO:
            anomalies.append(_anomaly(
                'volume_shrink', metric='techSummary.volRatio', value=_round(vol_ratio),
                threshold=VOL_SHRINK_RATIO, direction='below',
                label=f'量能萎縮（5日/20日均 {float(vol_ratio):.2f}）',
                as_of=as_of, severity='watch',
            ))

    rsi = tech.get('rsi14')
    if rsi is not None:
        if float(rsi) <= RSI_OVERSOLD:
            anomalies.append(_anomaly(
                'rsi_oversold', metric='techSummary.rsi14', value=_round(rsi),
                threshold=RSI_OVERSOLD, direction='below',
                label=f'RSI14 超賣（{float(rsi):.1f}）',
                as_of=as_of, severity='watch',
            ))
        elif float(rsi) >= RSI_OVERBOUGHT:
            anomalies.append(_anomaly(
                'rsi_overbought', metric='techSummary.rsi14', value=_round(rsi),
                threshold=RSI_OVERBOUGHT, direction='above',
                label=f'RSI14 超買（{float(rsi):.1f}）',
                as_of=as_of, severity='watch',
            ))

    close = tech.get('close')
    sma20 = tech.get('sma20')
    if close is not None and sma20 not in (None, 0):
        dev_pct = (float(close) - float(sma20)) / float(sma20) * 100.0
        if dev_pct >= MA_DEVIATION_PCT:
            anomalies.append(_anomaly(
                'price_above_sma20', metric='techSummary.close_vs_sma20_pct',
                value=_round(dev_pct), threshold=MA_DEVIATION_PCT, direction='above',
                label=f'收盤偏離 SMA20 上方 {dev_pct:.1f}%（SMA20={float(sma20):.2f}）',
                as_of=as_of, severity='info',
            ))
        elif dev_pct <= -MA_DEVIATION_PCT:
            anomalies.append(_anomaly(
                'price_below_sma20', metric='techSummary.close_vs_sma20_pct',
                value=_round(dev_pct), threshold=-MA_DEVIATION_PCT, direction='below',
                label=f'收盤偏離 SMA20 下方 {abs(dev_pct):.1f}%（SMA20={float(sma20):.2f}）',
                as_of=as_of, severity='watch',
            ))

    inst = (chips or {}).get('inst') or {}
    foreign = inst.get('foreign')
    if foreign is not None:
        foreign_f = float(foreign)
        if foreign_f >= INST_SIGNIFICANT_SHARES:
            anomalies.append(_anomaly(
                'foreign_net_buy', metric='chips.inst.foreign', value=int(foreign_f),
                threshold=INST_SIGNIFICANT_SHARES, direction='above',
                label=f'外資大買超 {foreign_f / 1000:.0f} 千股',
                as_of=(chips or {}).get('asOf') or as_of, severity='info',
            ))
        elif foreign_f <= -INST_SIGNIFICANT_SHARES:
            anomalies.append(_anomaly(
                'foreign_net_sell', metric='chips.inst.foreign', value=int(foreign_f),
                threshold=-INST_SIGNIFICANT_SHARES, direction='below',
                label=f'外資大賣超 {abs(foreign_f) / 1000:.0f} 千股',
                as_of=(chips or {}).get('asOf') or as_of, severity='watch',
            ))

    margin = (chips or {}).get('margin') or {}
    margin_chg = margin.get('marginChange')
    if margin_chg is not None:
        margin_chg_f = float(margin_chg)
        if margin_chg_f >= MARGIN_CHANGE_SIGNIFICANT:
            anomalies.append(_anomaly(
                'margin_expanding', metric='chips.margin.marginChange',
                value=_round(margin_chg_f), threshold=MARGIN_CHANGE_SIGNIFICANT,
                direction='above', label=f'融資餘額增加 {margin_chg_f:.0f}',
                as_of=(chips or {}).get('asOf') or as_of, severity='watch',
            ))
        elif margin_chg_f <= -MARGIN_CHANGE_SIGNIFICANT:
            anomalies.append(_anomaly(
                'margin_contracting', metric='chips.margin.marginChange',
                value=_round(margin_chg_f), threshold=-MARGIN_CHANGE_SIGNIFICANT,
                direction='below', label=f'融資餘額減少 {abs(margin_chg_f):.0f}',
                as_of=(chips or {}).get('asOf') or as_of, severity='info',
            ))

    return anomalies


def _validation_point(
    point_id: str,
    *,
    anomaly_id: Optional[str],
    kind: str,
    metric: str,
    threshold: Any,
    threshold_ref: str,
    label: str,
    as_of: Optional[str],
    resolve_session: str,
    priority: int,
) -> Dict[str, Any]:
    return {
        'id': point_id,
        'anomalyId': anomaly_id,
        'kind': kind,
        'metric': metric,
        'threshold': threshold,
        'thresholdRef': threshold_ref,
        'label': label,
        'epistemic': 'FACT',
        'resolveSession': resolve_session,
        'asOf': as_of,
        'priority': priority,
    }


def build_validation_points(
    anomalies: List[Dict[str, Any]],
    quote: Optional[Dict[str, Any]],
    tech: Optional[Dict[str, Any]],
    chips: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    max_points: int = MAX_VALIDATION_POINTS,
) -> List[Dict[str, Any]]:
    """由 anomalies 衍生最多 max_points 個明日可勾選驗證點（規則閾值，非 LLM）。"""
    now = now or datetime.now(TZ_TPE)
    resolve_session = _next_tw_session_date(now)
    tech = tech or {}
    quote = quote or {}
    as_of = tech.get('asOf') or quote.get('asOf')
    by_id = {str(a.get('id')): a for a in (anomalies or []) if a.get('id')}
    candidates: List[Dict[str, Any]] = []

    sma20 = tech.get('sma20')
    if sma20 is not None and 'price_below_sma20' in by_id:
        candidates.append(_validation_point(
            'vp_close_above_sma20', anomaly_id='price_below_sma20',
            kind='close_above', metric='quote.last', threshold=_round(sma20),
            threshold_ref='techSummary.sma20',
            label=f'明日收盤價需站穩 SMA20（{_round(sma20)}）',
            as_of=as_of, resolve_session=resolve_session, priority=10,
        ))
    elif sma20 is not None and 'price_above_sma20' in by_id:
        candidates.append(_validation_point(
            'vp_close_hold_above_sma20', anomaly_id='price_above_sma20',
            kind='close_above', metric='quote.last', threshold=_round(sma20),
            threshold_ref='techSummary.sma20',
            label=f'明日收盤價需維持在 SMA20 上方（{_round(sma20)}）',
            as_of=as_of, resolve_session=resolve_session, priority=12,
        ))

    vol_ratio = tech.get('volRatio')
    if vol_ratio is not None and 'volume_spike' in by_id:
        shrink_target = _round(float(vol_ratio) * 0.85)
        candidates.append(_validation_point(
            'vp_volume_cool', anomaly_id='volume_spike',
            kind='vol_ratio_below', metric='techSummary.volRatio',
            threshold=shrink_target, threshold_ref='techSummary.volRatio',
            label=f'明日量能需回落至 volRatio < {shrink_target}（今日 {float(vol_ratio):.2f}）',
            as_of=as_of, resolve_session=resolve_session, priority=20,
        ))
    elif vol_ratio is not None and 'volume_shrink' in by_id:
        candidates.append(_validation_point(
            'vp_volume_expand', anomaly_id='volume_shrink',
            kind='vol_ratio_above', metric='techSummary.volRatio',
            threshold=_round(VOL_SHRINK_RATIO), threshold_ref='techSummary.volRatio',
            label=f'明日量能需回升至 volRatio ≥ {VOL_SHRINK_RATIO}（今日 {float(vol_ratio):.2f}）',
            as_of=as_of, resolve_session=resolve_session, priority=22,
        ))

    foreign = ((chips or {}).get('inst') or {}).get('foreign')
    if foreign is not None and 'foreign_net_sell' in by_id:
        candidates.append(_validation_point(
            'vp_foreign_flip_buy', anomaly_id='foreign_net_sell',
            kind='inst_foreign_above', metric='chips.inst.foreign',
            threshold=0, threshold_ref='chips.inst.foreign',
            label='明日外資需轉為淨買超（>0）',
            as_of=(chips or {}).get('asOf') or as_of,
            resolve_session=resolve_session, priority=30,
        ))
    elif foreign is not None and 'foreign_net_buy' in by_id:
        candidates.append(_validation_point(
            'vp_foreign_hold_buy', anomaly_id='foreign_net_buy',
            kind='inst_foreign_above', metric='chips.inst.foreign',
            threshold=0, threshold_ref='chips.inst.foreign',
            label='明日外資需維持淨買超（>0）',
            as_of=(chips or {}).get('asOf') or as_of,
            resolve_session=resolve_session, priority=32,
        ))

    if 'rsi_oversold' in by_id and tech.get('rsi14') is not None:
        candidates.append(_validation_point(
            'vp_rsi_recover', anomaly_id='rsi_oversold',
            kind='rsi_above', metric='techSummary.rsi14',
            threshold=RSI_OVERSOLD, threshold_ref='techSummary.rsi14',
            label=f'明日 RSI14 需回升至 > {RSI_OVERSOLD:.0f}',
            as_of=as_of, resolve_session=resolve_session, priority=40,
        ))
    elif 'rsi_overbought' in by_id and tech.get('rsi14') is not None:
        candidates.append(_validation_point(
            'vp_rsi_cool', anomaly_id='rsi_overbought',
            kind='rsi_below', metric='techSummary.rsi14',
            threshold=RSI_OVERBOUGHT, threshold_ref='techSummary.rsi14',
            label=f'明日 RSI14 需回落至 < {RSI_OVERBOUGHT:.0f}',
            as_of=as_of, resolve_session=resolve_session, priority=42,
        ))

    if not candidates and sma20 is not None and quote.get('last') is not None:
        candidates.append(_validation_point(
            'vp_close_above_sma20_default', anomaly_id=None,
            kind='close_above', metric='quote.last', threshold=_round(sma20),
            threshold_ref='techSummary.sma20',
            label=f'明日收盤價是否站穩 SMA20（{_round(sma20)}）',
            as_of=as_of, resolve_session=resolve_session, priority=90,
        ))

    candidates.sort(key=lambda row: int(row.get('priority') or 99))
    return candidates[:max(0, int(max_points or MAX_VALIDATION_POINTS))]


def _pack_numeric_corpus(pack: Dict[str, Any]) -> set:
    """EvidencePack 內所有可稽核數字（字串集合，供敘事紅線比對）。"""
    corpus: set = set()

    def add_num(value: Any) -> None:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return
        corpus.add(str(int(num)) if num == int(num) else str(round(num, 4)))
        corpus.add(str(round(num, 2)))
        if abs(num) >= 10:
            corpus.add(str(int(round(num))))

    def walk(obj: Any) -> None:
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, (int, float)):
            add_num(obj)
        elif isinstance(obj, dict):
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for val in obj:
                walk(val)
        elif isinstance(obj, str):
            for match in re.finditer(r'\d+\.?\d*', obj):
                add_num(match.group())

    walk(pack)
    for vp in pack.get('validationPoints') or []:
        if vp.get('threshold') is not None:
            add_num(vp['threshold'])
    return corpus


def audit_narrative_numerics(
    narrative: Dict[str, Any],
    pack: Dict[str, Any],
) -> List[str]:
    """紅線：敘事中的數字必須能對上 EvidencePack；禁止自創 regime／信心分數。"""
    flags: List[str] = []
    corpus = _pack_numeric_corpus(pack)
    decision = pack.get('decisionSummary') or {}
    regime = decision.get('regime') or {}
    if regime.get('score') is not None:
        try:
            score = float(regime['score'])
            corpus.add(str(round(score, 2)))
            corpus.add(str(int(score)) if score == int(score) else str(round(score, 4)))
        except (TypeError, ValueError):
            pass
    if regime.get('confidence') is not None:
        try:
            conf = float(regime['confidence'])
            corpus.add(str(round(conf, 2)))
        except (TypeError, ValueError):
            pass

    texts: List[str] = []
    for key in ('conclusion', *NARRATIVE_LIST_KEYS):
        val = narrative.get(key)
        if isinstance(val, str):
            texts.append(val)
        elif isinstance(val, list):
            texts.extend(str(x) for x in val if isinstance(x, str))

    invented: List[str] = []
    for text in texts:
        for match in re.finditer(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d{2,})(?!\d)', text):
            raw = match.group().replace(',', '')
            try:
                num = float(raw)
            except ValueError:
                continue
            if num < 10 and '.' not in raw:
                continue
            variants = {raw, str(round(num, 2)), str(int(num)) if num == int(num) else None}
            variants = {v for v in variants if v}
            if not any(v in corpus for v in variants):
                invented.append(raw)

    if invented:
        flags.append('敘事含 EvidencePack 未出現的數字：' + '、'.join(sorted(set(invented))[:6]))

    joined = ' '.join(texts).lower()
    if re.search(r'信心(?:分數|指標|水準)?\s*[:：]?\s*\d', joined) and regime.get('score') is None:
        flags.append('敘事自創信心分數（decisionSummary 無 score）')
    if re.search(r'regime\s*score\s*[:=]?\s*\d', joined) and regime.get('score') is None:
        flags.append('敘事自創 regime score')
    return flags


def build_evidence_pack(symbol: str, *, include: Dict[str, bool],
                        max_news: int = DEFAULT_NEWS_PER_SYMBOL,
                        decision: Optional[Dict[str, Any]] = None,
                        flash: Optional[Dict[str, Any]] = None,
                        uni: Optional[Dict[str, Any]] = None,
                        sectors: Optional[Dict[str, str]] = None,
                        now: Optional[datetime] = None) -> Dict[str, Any]:
    """對單一台股代號組 EvidencePack（全由 ST 既有管線算好，無 LLM）。"""
    now = now or datetime.now(TZ_TPE)
    code = str(symbol).strip().upper()
    pack: Dict[str, Any] = {'symbol': code}
    notes: List[str] = []
    as_of: Dict[str, Any] = {}

    bars = None
    if include.get('quotes', True) or include.get('techSummary', True):
        try:
            bars = _get('bars_fn', _default_bars)(code)
        except Exception:
            bars = None

    if include.get('quotes', True):
        quote = quote_from_bars(bars)
        if quote:
            pack['quote'] = quote
            as_of['quote'] = quote['asOf']
        else:
            notes.append('quote 資料不足（本機日K無資料）')

    if include.get('techSummary', True):
        tech = tech_summary_from_bars(bars)
        if tech:
            pack['techSummary'] = tech
            as_of['tech'] = tech['asOf']

    if include.get('chips', True):
        chip = None
        try:
            chip = _chip_evidence(_get('chip_fn', _default_chip)(code))
        except Exception:
            chip = None
        if chip:
            pack['chips'] = chip
            as_of['chips'] = chip.get('asOf')
        else:
            notes.append('chips 資料不足（法人／融資券快照不可用）')

    if include.get('news', True):
        news = _news_for_symbol(flash, code, max(1, min(int(max_news or DEFAULT_NEWS_PER_SYMBOL),
                                                        MAX_NEWS_PER_SYMBOL)))
        pack['news'] = news
        if news:
            as_of['news'] = news[0].get('time')
        else:
            notes.append('news 無本檔重大訊息')

    if include.get('decisionSummary', True) and decision:
        pack['decisionSummary'] = decision
        as_of['decision'] = decision.get('asOf')

    meta = _universe_meta(code, uni, sectors)
    if meta:
        pack['universeMeta'] = meta

    stale_reasons = staleness(pack.get('quote'), now) if include.get('quotes', True) else []
    pack['evidenceAsOf'] = as_of
    pack['stale'] = bool(stale_reasons)
    if stale_reasons:
        pack['staleReasons'] = stale_reasons
    if notes:
        pack['notes'] = notes

    if include.get('validationPoints', True):
        pack['anomalies'] = detect_anomalies(
            pack.get('quote'), pack.get('techSummary'), pack.get('chips'),
        )
        pack['validationPoints'] = build_validation_points(
            pack['anomalies'], pack.get('quote'), pack.get('techSummary'),
            pack.get('chips'), now=now,
        )
        if pack['validationPoints']:
            as_of['validation'] = pack['validationPoints'][0].get('resolveSession')

    try:
        from feature_settings import is_enabled as _flag_enabled
        if _flag_enabled('shadowChipPathState') and bars:
            import chip_path_state
            chip_path = chip_path_state.evaluate_chip_path_state(
                code,
                bars=bars,
                chips=pack.get('chips'),
                now=now,
            )
            pack['chipPathState'] = chip_path
            as_of['chipPathState'] = chip_path.get('asOfDate')
    except Exception:
        pass

    try:
        from feature_settings import is_enabled as _flag_enabled
        if _flag_enabled('shadowPeakObservation'):
            import peak_observation
            peak_obs = peak_observation.build_for_evidence_pack(
                code,
                bars=bars,
                now=now,
            )
            if peak_obs:
                pack['peakObservation'] = peak_obs
                as_of['peakObservation'] = peak_obs.get('asOf')
    except Exception:
        pass

    try:
        from feature_settings import is_enabled as _flag_enabled
        if _flag_enabled('shadowPeak100d'):
            import peak_observation_100d
            peak_100d = peak_observation_100d.build_for_evidence_pack(
                code,
                bars=bars,
                now=now,
            )
            if peak_100d:
                pack['peakObservation100d'] = peak_100d
                as_of['peakObservation100d'] = peak_100d.get('asOf')
    except Exception:
        pass

    return pack


# ── narrative JSON 驗證與 guardrail ─────────────────────────────────────────

def parse_llm_json(text: str) -> Optional[Dict[str, Any]]:
    """容忍 code fence／前後雜訊，抽出第一個完整 JSON object。"""
    raw = str(text or '').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```[a-zA-Z]*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    start = raw.find('{')
    end = raw.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def validate_narrative(obj: Any) -> Tuple[bool, List[str]]:
    """嚴格 schema：conclusion(str) + drivers/hypotheses/risks/watchTomorrow(list[str])。"""
    errors: List[str] = []
    if not isinstance(obj, dict):
        return False, ['narrative 必須是 JSON object']
    conclusion = obj.get('conclusion')
    if not isinstance(conclusion, str) or not conclusion.strip():
        errors.append('conclusion 必須是非空字串')
    for key in NARRATIVE_LIST_KEYS:
        value = obj.get(key)
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            errors.append(f'{key} 必須是字串陣列')
    return not errors, errors


def normalize_citations(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        ctype = str(item.get('type') or '').strip().lower()
        ref = str(item.get('ref') or '').strip()
        if ctype in CITATION_TYPES and ref:
            out.append({'type': ctype, 'ref': ref[:200]})
        if len(out) >= 12:
            break
    return out


def contains_forbidden_advice(text: str) -> bool:
    low = str(text or '').lower()
    return any(pattern.lower() in low for pattern in FORBIDDEN_PATTERNS)


def scrub_advice(narrative: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """預設關閉喊單：清掉含買賣建議／目標價的片段，並回報 guardrail 命中。"""
    flags: List[str] = []
    out = dict(narrative)
    conclusion = str(out.get('conclusion') or '')
    if contains_forbidden_advice(conclusion):
        kept = [s for s in re.split(r'(?<=[。；;.!?！？])', conclusion)
                if s.strip() and not contains_forbidden_advice(s)]
        out['conclusion'] = (''.join(kept).strip()
                             or '（原結論含不符規範的投資建議內容，已自動移除）')
        flags.append('conclusion 命中禁止語彙，已移除')
    for key in NARRATIVE_LIST_KEYS:
        items = out.get(key) or []
        kept_items = [x for x in items if not contains_forbidden_advice(x)]
        if len(kept_items) != len(items):
            flags.append(f'{key} 移除 {len(items) - len(kept_items)} 條含買賣建議／目標價內容')
        out[key] = kept_items
    return out, flags


def apply_staleness(narrative: Dict[str, Any], stale_reasons: List[str]) -> Dict[str, Any]:
    """證據過期 → narrative.risks 首條保證以「資料可能過期」開頭（決定性，不靠模型）。"""
    if not stale_reasons:
        return narrative
    out = dict(narrative)
    risks = [str(x) for x in (out.get('risks') or [])]
    risks = [x for x in risks if not x.startswith(STALE_RISK_PREFIX)]
    risks.insert(0, f"{STALE_RISK_PREFIX}：{'；'.join(stale_reasons)}")
    out['risks'] = risks
    return out


# ── Prompt（system 邊界） ───────────────────────────────────────────────────

def system_prompt(locale: str = 'zh-Hant-TW') -> str:
    return (
        '你是台股研究助理，為使用者撰寫「盤後敘事日報」。\n'
        '規則（必須全部遵守）：\n'
        '1. 只能使用 user message 內的 EvidencePack 佐證資料；缺資料就明說「資料不足」，'
        '禁止補造價格、籌碼、新聞或任何數字。\n'
        '2. 每句涉及數字的主張，都必須對得上 EvidencePack 的欄位值。\n'
        '3. 禁止下單指令、禁止建議買進、禁止建議賣出、禁止目標價喊單、禁止保證獲利。\n'
        '4. regime、支撐壓力、信心分數、曝險區間一律以 decisionSummary 既有數值為唯讀證據，'
        '禁止自行推算、改寫或給出新的等級。\n'
        '5. 若 EvidencePack 的 stale 為 true，risks 第一條必須以「資料可能過期」開頭。\n'
        '6. EvidencePack 內 validationPoints[] 為規則產生的明日驗證點（FACT）；'
        'watchTomorrow／hypotheses 只能改寫其語意，禁止自創新閾值、分數或 Decision 數字。\n'
        '7. 輸出「嚴格 JSON」（單一 object、無 markdown 圍欄、無多餘文字）：\n'
        '{"conclusion": "一段結論", "drivers": ["…"], "hypotheses": ["…"], '
        '"risks": ["…"], "watchTomorrow": ["…"], '
        '"citations": [{"type": "quote|chip|tech|news|decision", "ref": "對應欄位或標題"}]}\n'
        f'語言：{locale or "zh-Hant-TW"}（台灣正體中文）。'
    )


def _user_message(pack: Dict[str, Any], as_of: str, locale: str) -> str:
    return json.dumps(
        {'reportAsOf': as_of, 'locale': locale, 'evidencePack': pack},
        ensure_ascii=False, separators=(',', ':'),
    )


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    name = str(model or '').lower()
    rate_in, rate_out = 3.0, 15.0
    for key, r_in, r_out in _PRICES:
        if key in name:
            rate_in, rate_out = r_in, r_out
            break
    usd = (max(0, int(input_tokens)) * rate_in + max(0, int(output_tokens)) * rate_out) / 1_000_000
    return round(usd, 6)


# ── 本機報告存檔（data/reports/postmarket/YYYY-MM-DD.json，gitignored） ──────

def reports_dir() -> Path:
    override = os.environ.get('ST_REPORTS_DIR')
    if override:
        return Path(override)
    return ROOT / 'data' / 'reports' / 'postmarket'


def save_report(payload: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """存當日檔並累計當日 estUsd；回 {'date','runs','usdToday','path'}。"""
    from atomic_store import atomic_write_json, load_json
    now = now or datetime.now(TZ_TPE)
    day_key = now.strftime('%Y-%m-%d')
    path = reports_dir() / f'{day_key}.json'
    try:
        existing = load_json(str(path), default={}, expected_type=dict)
    except Exception:
        existing = {}
    if existing.get('date') != day_key:
        existing = {}
    runs = int(existing.get('runs') or 0) + 1
    usd_today = round(float(existing.get('usdToday') or 0.0)
                      + float(((payload.get('usage') or {}).get('estUsd')) or 0.0), 6)
    day = {'date': day_key, 'runs': runs, 'usdToday': usd_today, 'latest': payload}
    atomic_write_json(str(path), day)
    return {'date': day_key, 'runs': runs, 'usdToday': usd_today, 'path': str(path)}


def load_latest_report() -> Optional[Dict[str, Any]]:
    from atomic_store import load_json
    base = reports_dir()
    try:
        files = sorted(base.glob('*.json'))
    except OSError:
        return None
    for path in reversed(files):
        if path.name.endswith('.bak'):
            continue
        try:
            day = load_json(str(path), default=None, expected_type=dict)
        except Exception:
            continue
        if day:
            return day
    return None


# ── Orchestration（唯一會呼叫 LLM 的入口） ──────────────────────────────────

def _result(status: int, payload: Dict[str, Any],
            headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {'status': int(status), 'payload': payload, 'headers': headers or {}}


def _normalize_symbols(raw: Any) -> List[str]:
    out: List[str] = []
    for item in raw if isinstance(raw, list) else []:
        code = str(item or '').strip().upper()
        if code and re.fullmatch(r'[0-9A-Z]{2,10}', code) and code not in out:
            out.append(code)
    return out


def _gate_module():
    import llm_gate
    return llm_gate


def _retry_after(gate) -> str:
    try:
        remaining = float((gate.status() or {}).get('remaining_sec') or 0)
    except Exception:
        remaining = 0.0
    return str(max(5, int(remaining) + 1))


def generate_report(body: Dict[str, Any], *, api_key: str,
                    anthropic_call: Optional[Callable[..., Tuple[str, Dict[str, Any]]]] = None,
                    gate=None, now: Optional[datetime] = None,
                    save: bool = True) -> Dict[str, Any]:
    """POST /api/ai/postmarket-daily 的核心；回 {'status','payload','headers'}。

    無 HTTP 依賴，anthropic_call／gate 可注入以利測試；預設走 ai_api（雲端
    Claude only）與 llm_gate（WD 優先，忙碌回 503 + Retry-After，不 fallback 本機）。
    """
    import urllib.error

    now = now or datetime.now(TZ_TPE)
    gate = gate or _gate_module()
    body = body if isinstance(body, dict) else {}

    symbols = _normalize_symbols(body.get('symbols'))
    if not symbols:
        return _result(400, {'error': 'symbols required（台股代號陣列）'})
    if len(symbols) > MAX_SYMBOLS:
        return _result(413, {'error': f'symbols 超過上限 {MAX_SYMBOLS} 檔'})

    include_raw = body.get('include') if isinstance(body.get('include'), dict) else {}
    include = {
        'quotes': bool(include_raw.get('quotes', True)),
        'chips': bool(include_raw.get('chips', True)),
        'techSummary': bool(include_raw.get('techSummary', True)),
        'news': bool(include_raw.get('news', True)),
        'decisionSummary': bool(include_raw.get('decisionSummary', True)),
        'macro': bool(include_raw.get('macro', False)),
        'validationPoints': bool(include_raw.get('validationPoints', True)),
    }
    try:
        max_news = int(body.get('maxNewsPerSymbol') or DEFAULT_NEWS_PER_SYMBOL)
    except (TypeError, ValueError):
        max_news = DEFAULT_NEWS_PER_SYMBOL
    max_news = max(1, min(max_news, MAX_NEWS_PER_SYMBOL))
    locale = str(body.get('locale') or 'zh-Hant-TW')
    model_hint = str(body.get('modelHint') or 'sonnet').strip().lower()
    client_id = str(body.get('abortSignalClientId') or '').strip() or None
    as_of = str(body.get('asOf') or now.isoformat())

    # llm_gate：WD 持有 → 503 + Retry-After；取得後標記用途 postmarket-daily。
    if gate.wd_busy():
        return _result(503, {'error': 'WaveDeck 推論優先中，盤後日報稍後再試',
                             'gate': gate.status()},
                       {'Retry-After': _retry_after(gate)})
    if not gate.wait_or_defer(GATE_OWNER, wait_sec=GATE_WAIT_SEC, ttl_sec=GATE_TTL_SEC,
                              purpose=GATE_PURPOSE):
        return _result(503, {'error': 'LLM gate busy', 'gate': gate.status()},
                       {'Retry-After': _retry_after(gate)})

    try:
        # 共用證據（一次取，避免逐檔重抓）
        decision = None
        if include['decisionSummary'] or include['macro']:
            try:
                decision = decision_snapshot(_get('decision_fn', _default_decision)())
            except Exception:
                decision = None
        flash = None
        if include['news']:
            try:
                flash = _get('news_fn', _default_news)()
            except Exception:
                flash = None
        uni = None
        try:
            uni = _get('universe_fn', _default_universe)()
        except Exception:
            uni = None
        sectors = None
        sectors_fn = _accessors.get('sectors_fn')
        if callable(sectors_fn):
            try:
                sectors = sectors_fn()
            except Exception:
                sectors = None

        packs = [
            build_evidence_pack(sym, include=include, max_news=max_news,
                                decision=decision if include['decisionSummary'] else None,
                                flash=flash, uni=uni, sectors=sectors, now=now)
            for sym in symbols
        ]
        evidence_chars = len(json.dumps(packs, ensure_ascii=False))
        if evidence_chars > MAX_EVIDENCE_CHARS:
            return _result(413, {'error': f'EvidencePack 過大（{evidence_chars} chars），'
                                          f'請減少 symbols 或關閉部分 include'})

        import ai_api
        model = ai_api.resolve_model_hint(api_key, model_hint)
        call = anthropic_call or _accessors.get('anthropic_fn') or _default_anthropic(api_key)
        sys_prompt = system_prompt(locale)

        report_symbols: List[Dict[str, Any]] = []
        total_in = total_out = 0
        calls = 0
        partial = False
        aborted = False
        upstream_error: Optional[Tuple[int, str]] = None

        # 批次 concurrency = 1（規格允許 1–2；序列最可預測、避免額度暴衝）
        for index, pack in enumerate(packs):
            entry: Dict[str, Any] = {
                'symbol': pack['symbol'],
                'evidenceAsOf': pack.get('evidenceAsOf') or {},
                'stale': bool(pack.get('stale')),
            }
            if pack.get('anomalies'):
                entry['anomalies'] = pack['anomalies']
            if pack.get('validationPoints'):
                entry['validationPoints'] = pack['validationPoints']
            if client_id and is_aborted(client_id):
                aborted = True
                entry['error'] = 'aborted'
                report_symbols.append(entry)
                continue
            if index > 0 and not gate.acquire(GATE_OWNER, ttl_sec=GATE_TTL_SEC,
                                              purpose=GATE_PURPOSE):
                # WD 中途 preempt：不搶、不 fallback 本機 deep，剩餘標記後結束。
                partial = True
                entry['error'] = 'gate_preempted_by_wavedeck'
                report_symbols.append(entry)
                for rest in packs[index + 1:]:
                    report_symbols.append({
                        'symbol': rest['symbol'],
                        'evidenceAsOf': rest.get('evidenceAsOf') or {},
                        'stale': bool(rest.get('stale')),
                        'error': 'gate_preempted_by_wavedeck',
                    })
                break
            try:
                text, raw = call(
                    [{'role': 'user', 'content': _user_message(pack, as_of, locale)}],
                    system=sys_prompt, model=model, max_tokens=PER_SYMBOL_MAX_TOKENS,
                )
                calls += 1
                usage = (raw or {}).get('usage') or {}
                total_in += int(usage.get('input_tokens') or 0)
                total_out += int(usage.get('output_tokens') or 0)
            except urllib.error.HTTPError as exc:
                detail = ''
                try:
                    detail = exc.read().decode('utf-8', 'replace')[:300]
                except Exception:
                    pass
                upstream_error = (int(exc.code), detail)
                entry['error'] = f'anthropic HTTP {exc.code}'
                report_symbols.append(entry)
                partial = True
                break  # 上游限流／失敗即停，避免整批硬打
            except Exception as exc:
                upstream_error = (0, type(exc).__name__)
                entry['error'] = 'anthropic call failed: ' + type(exc).__name__
                report_symbols.append(entry)
                partial = True
                break

            parsed = parse_llm_json(text)
            ok, errors = validate_narrative(parsed)
            if not ok:
                entry['error'] = 'narrative JSON 驗證失敗: ' + '; '.join(errors)
                report_symbols.append(entry)
                continue
            narrative = {k: parsed[k] for k in ('conclusion', *NARRATIVE_LIST_KEYS)}
            narrative, guard_flags = scrub_advice(narrative)
            narrative = apply_staleness(narrative, pack.get('staleReasons') or [])
            numeric_flags = audit_narrative_numerics(narrative, pack)
            if numeric_flags:
                guard_flags = list(guard_flags) + numeric_flags
            entry['narrative'] = narrative
            entry['citations'] = normalize_citations(parsed.get('citations'))
            if guard_flags:
                entry['guardrail'] = guard_flags
            if pack.get('notes'):
                entry['notes'] = pack['notes']
            report_symbols.append(entry)

        market_blurb = None
        if include['macro'] and decision and not partial and not aborted:
            try:
                text, raw = call(
                    [{'role': 'user', 'content': json.dumps(
                        {'reportAsOf': as_of, 'locale': locale,
                         'marketDecision': decision,
                         'task': '僅根據 marketDecision 唯讀證據，用一句話描述大盤現況，'
                                 '輸出嚴格 JSON {"marketBlurb": "…"}'},
                        ensure_ascii=False, separators=(',', ':'))}],
                    system=sys_prompt, model=model, max_tokens=BLURB_MAX_TOKENS,
                )
                calls += 1
                usage = (raw or {}).get('usage') or {}
                total_in += int(usage.get('input_tokens') or 0)
                total_out += int(usage.get('output_tokens') or 0)
                parsed = parse_llm_json(text) or {}
                blurb = parsed.get('marketBlurb')
                if isinstance(blurb, str) and blurb.strip() \
                        and not contains_forbidden_advice(blurb):
                    market_blurb = blurb.strip()
            except Exception:
                market_blurb = None
    finally:
        gate.release(GATE_OWNER)
        if client_id:
            clear_abort(client_id)

    succeeded = [s for s in report_symbols if 'narrative' in s]
    if not succeeded and upstream_error is not None:
        code, detail = upstream_error
        if code == 429:
            return _result(429, {'error': 'Anthropic 限流（429）', 'detail': detail},
                           {'Retry-After': '30'})
        return _result(502, {'error': f'Anthropic 上游失敗（{code or "exception"}）',
                             'detail': detail})

    est_usd = estimate_cost_usd(model, total_in, total_out)
    payload: Dict[str, Any] = {
        'ok': True,
        'reportId': 'pmd-' + now.strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:8],
        'generatedAt': now.isoformat(),
        'asOf': as_of,
        'model': model,
        'usage': {'inputTokens': total_in, 'outputTokens': total_out, 'estUsd': est_usd},
        'symbols': report_symbols,
    }
    if market_blurb:
        payload['marketBlurb'] = market_blurb
    if partial:
        payload['partial'] = True
    if aborted:
        payload['aborted'] = True

    if calls:
        try:
            import wavedeck_bus as wdb
            wdb.record_st_cloud(usd=est_usd, calls=calls)
        except Exception:
            pass

    if save and succeeded:
        try:
            saved = save_report(payload, now=now)
            payload['usageToday'] = {'estUsd': saved['usdToday'], 'runs': saved['runs']}
            payload['savedTo'] = saved['path']
        except Exception as exc:
            payload['saveError'] = type(exc).__name__

    return _result(200, payload)
