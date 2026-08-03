# -*- coding: utf-8 -*-
"""TW Pulse Intelligence — 市場脈動因子帳本（真實資料，非 mock）。

設計目標（對齊 tw-pulse-terminal UX，分數必須可覆核）：
  • healthScore  = 既有大盤體質 _score_tw_market（0~100）
  • riskScore    = 風險因子絕對分加總後軟封頂（0~100，越高越警戒）
  • totalScore   = 0.70×health + 0.30×(100−risk)
  • positive / risk / pending 三欄因子帳本（pending 不計分）
  • dataCompleteness = 可用資料集 / 預期資料集

鐵律：不得捏造 Fear&Greed／假 VIX／假 250 日新高家數。
缺資料 → pendingFactors，完整度下降，不灌水分數。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _n(v) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or math.isinf(x):  # NaN / inf
        return None
    return x


def _label_total(score: Optional[float]) -> str:
    if score is None:
        return '資料不足'
    if score >= 70:
        return '偏強'
    if score >= 55:
        return '中偏強'
    if score >= 45:
        return '中性'
    if score >= 30:
        return '偏弱'
    return '偏冷'


def _label_health(score: Optional[float]) -> str:
    if score is None:
        return '資料不足'
    if score >= 70:
        return '體質偏強'
    if score >= 55:
        return '體質中偏強'
    if score >= 45:
        return '體質中性'
    if score >= 30:
        return '體質偏弱'
    return '體質偏冷'


def _label_risk(score: Optional[float]) -> str:
    if score is None:
        return '資料不足'
    if score >= 70:
        return '風險偏高'
    if score >= 55:
        return '風險中偏高'
    if score >= 45:
        return '風險中性'
    if score >= 30:
        return '風險偏低'
    return '風險低檔'


def _factor(fid: int, name: str, description: str, score: float, typ: str) -> Dict[str, Any]:
    return {
        'id': fid,
        'name': name,
        'description': description,
        'score': round(float(score), 1),
        'type': typ,  # positive | risk | pending
    }


def _filter_sectors(sectors: Optional[List[dict]]) -> List[dict]:
    skip = ('加權', '櫃買', '寶島', '公司治理', '中型', '電子工業', '未含')
    out = []
    for s in sectors or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get('name') or '')
        cp = _n(s.get('changePct'))
        if not name or cp is None:
            continue
        if any(k in name for k in skip):
            continue
        out.append({'name': name, 'changePct': cp})
    return out


def build_pulse_intel(
    *,
    health_score: Optional[float],
    pillars: Optional[dict],
    market_rows: Optional[List[dict]],
    summary: Optional[str],
    stocks: Optional[dict],
    indices: Optional[dict],
    inst: Optional[dict],
    txf_night: Optional[dict],
    sectors: Optional[List[dict]],
    sources_present: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """由已對齊之欄位組出脈動情報 payload（純函數，可單測）。"""
    pillars = pillars or {}
    stocks = stocks or {}
    indices = indices or {}
    inst = inst or {}
    sources_present = dict(sources_present or {})

    t00 = indices.get('t00') or {}
    o00 = indices.get('o00') or {}
    t_cp = _n(t00.get('changePct'))
    o_cp = _n(o00.get('changePct'))

    adv = _n(stocks.get('advRatio'))
    up = _n(stocks.get('up'))
    dn = _n(stocks.get('down'))
    flat = _n(stocks.get('unchanged')) or 0.0
    limit_up = _n(stocks.get('limitUp'))
    limit_dn = _n(stocks.get('limitDown'))
    net_ad = _n(stocks.get('net'))

    vol_sc = _n(pillars.get('volumeScore'))
    inst_sc = _n(pillars.get('instScore'))
    m_sc = _n(pillars.get('marginScore'))
    pe_sc = _n(pillars.get('valuationScore'))
    turnover_yi = _n(pillars.get('turnoverYi'))
    inst_net_yi = _n(pillars.get('instNetYi'))
    margin_ratio = _n(pillars.get('marginRatio'))
    median_pe = _n(pillars.get('medianPE'))
    risk_zone = pillars.get('riskZone')

    foreign = _n(inst.get('foreign'))
    trust = _n(inst.get('trust'))
    dealer = _n(inst.get('dealer'))
    if inst_net_yi is None and any(v is not None for v in (foreign, trust, dealer)):
        inst_net_yi = ((foreign or 0) + (trust or 0) + (dealer or 0)) / 1e8

    txf_cp = _n((txf_night or {}).get('changePct'))
    txf_px = _n((txf_night or {}).get('price'))

    sec_list = _filter_sectors(sectors)
    sec_up = [s for s in sec_list if s['changePct'] > 0]
    sec_dn = [s for s in sec_list if s['changePct'] < 0]
    sec_up_ratio = (len(sec_up) / len(sec_list)) if sec_list else None
    top_sec = max(sec_list, key=lambda s: s['changePct']) if sec_list else None
    bot_sec = min(sec_list, key=lambda s: s['changePct']) if sec_list else None
    # 集中度代理：最強類股相對中位漲幅的超額（無成交金額時的誠實替代）
    conc_gap = None
    if len(sec_list) >= 4:
        cps = sorted(s['changePct'] for s in sec_list)
        mid = cps[len(cps) // 2]
        conc_gap = cps[-1] - mid

    positive: List[dict] = []
    risk: List[dict] = []
    pending: List[dict] = []
    pid = rid = nd = 0

    def add_pos(name, desc, score):
        nonlocal pid
        if score is None or score <= 0.05:
            return
        pid += 1
        positive.append(_factor(pid, name, desc, score, 'positive'))

    def add_risk(name, desc, score):
        """score 傳入負值或正的風險點數；統一存成負分。"""
        nonlocal rid
        if score is None:
            return
        sc = -abs(float(score))
        if sc >= -0.05:
            return
        rid += 1
        risk.append(_factor(rid, name, desc, sc, 'risk'))

    def add_pending(name, desc):
        nonlocal nd
        nd += 1
        pending.append(_factor(nd, name, desc, 0.0, 'pending'))

    # ── 正面因子 ──────────────────────────────────────────────
    if adv is not None:
        # advRatio 0.50→0、0.65→12、0.80→20
        sc = _clamp((adv - 0.50) * 80.0, 0.0, 20.0)
        add_pos(
            '市場廣度',
            f'上漲比 {(adv * 100):.1f}%｜上漲 {int(up) if up is not None else "—"} / 下跌 {int(dn) if dn is not None else "—"}'
            + (f'｜淨 {int(net_ad):+d}' if net_ad is not None else ''),
            sc,
        )
        if adv < 0.45:
            add_risk('市場廣度局限', f'上漲比僅 {(adv * 100):.1f}%，多空結構偏弱或糾結。', _clamp((0.45 - adv) * 50.0, 0.0, 12.0))
    else:
        add_pending('市場廣度', 'TWSE 漲跌家數尚未取得（休市或尚未公布）。')

    if inst_sc is not None and inst_net_yi is not None:
        if inst_net_yi >= 0:
            sc = _clamp((inst_sc - 50.0) / 50.0 * 20.0, 0.0, 20.0)
            add_pos('三大法人', f'法人合計 {inst_net_yi:+.1f} 億（外資/投信/自營合成）。', sc)
        else:
            add_risk('三大法人偏向風險', f'法人合計 {inst_net_yi:+.1f} 億，資金面偏防衛。', _clamp((50.0 - inst_sc) / 50.0 * 16.0, 0.0, 16.0))
    elif foreign is not None or trust is not None:
        # 有分項但缺合計分數
        pass
    else:
        add_pending('三大法人', '法人買賣超尚未載入。')

    if dealer is not None and dealer < -5e9 and (foreign or 0) > 0:
        # 自營大賣 + 外資買 → 結構分歧（常見避險）
        add_risk(
            '自營避險賣壓',
            f'自營 {(dealer / 1e8):+.1f} 億 vs 外資 {((foreign or 0) / 1e8):+.1f} 億，留意避險盤與現貨背離。',
            _clamp(abs(dealer) / 1e8 / 20.0 * 10.0, 0.0, 12.0),
        )

    if t_cp is not None:
        if t_cp > 0:
            add_pos('加權指數趨勢', f'加權當日 {t_cp:+.2f}%。', _clamp(t_cp * 2.2, 0.0, 8.0))
        elif t_cp <= -1.2:
            add_risk('加權指數趨勢', f'加權當日 {t_cp:+.2f}%，現貨動能偏弱。', _clamp(abs(t_cp) * 2.0, 0.0, 8.0))
        if abs(t_cp) >= 2.5:
            add_risk('指數乖離風險', f'單日波動 {t_cp:+.2f}%，短線乖離偏大，宜降槓桿節奏。', _clamp((abs(t_cp) - 2.5) * 4.0, 0.0, 12.0))
    else:
        add_pending('加權指數趨勢', '加權報價尚未取得。')

    if o_cp is not None:
        if o_cp > 0:
            add_pos('櫃買指數趨勢', f'櫃買當日 {o_cp:+.2f}%。', _clamp(o_cp * 1.8, 0.0, 6.0))
        elif o_cp <= -1.5:
            add_risk('櫃買指數趨勢', f'櫃買當日 {o_cp:+.2f}%，中小型相對弱勢。', _clamp(abs(o_cp) * 1.5, 0.0, 6.0))

    if vol_sc is not None and turnover_yi is not None:
        if vol_sc >= 50:
            add_pos('成交量能', f'成交約 {turnover_yi:.0f} 億，量能支撐評分 {vol_sc:.1f}。', _clamp((vol_sc - 50.0) / 50.0 * 12.0, 0.0, 12.0))
        else:
            add_risk('成交量能不足', f'成交約 {turnover_yi:.0f} 億，量能評分 {vol_sc:.1f}（低於中性）。', _clamp((50.0 - vol_sc) / 50.0 * 10.0, 0.0, 10.0))
    else:
        add_pending('成交量能', '大盤成交金額尚未載入。')

    if m_sc is not None and margin_ratio is not None:
        zone = f'（{risk_zone}）' if risk_zone else ''
        if m_sc >= 50:
            add_pos('融資維持率', f'維持率 {margin_ratio:.2f}%{zone}，信用風險可控。', _clamp((m_sc - 50.0) / 50.0 * 10.0, 0.0, 10.0))
        else:
            add_risk('融資警戒', f'維持率 {margin_ratio:.2f}%{zone}，接近／落入壓力區時宜降杠杆。', _clamp((50.0 - m_sc) / 50.0 * 14.0, 0.0, 14.0))
    else:
        add_pending('融資維持率', '融資維持率序列尚未就緒。')

    if pe_sc is not None and median_pe is not None:
        if pe_sc >= 50:
            add_pos('估值吸引力', f'全市場本益比中位 {median_pe:.1f}x，估值壓力較低。', _clamp((pe_sc - 50.0) / 50.0 * 10.0, 0.0, 10.0))
        else:
            add_risk('估值壓力', f'全市場本益比中位 {median_pe:.1f}x，評價偏貴時上檔遲疑。', _clamp((50.0 - pe_sc) / 50.0 * 10.0, 0.0, 10.0))

    if limit_up is not None and up is not None and up > 0:
        ratio = limit_up / up
        if limit_up >= 8:
            add_pos('漲停動能', f'漲停 {int(limit_up)} 家（佔上漲 {ratio * 100:.1f}%）。', _clamp(limit_up / 5.0, 0.0, 8.0))
        if limit_dn is not None and limit_dn >= 8 and (limit_up or 0) < limit_dn:
            add_risk('跌停壓力', f'跌停 {int(limit_dn)} 家多於漲停 {int(limit_up or 0)}，尾盤情緒偏防衛。', _clamp(limit_dn / 5.0, 0.0, 8.0))

    if sec_up_ratio is not None:
        if sec_up_ratio >= 0.55:
            names = '、'.join(s['name'] for s in sec_up[:3])
            add_pos('類股參與度', f'{len(sec_up)}/{len(sec_list)} 類股上漲' + (f'（強：{names}）' if names else ''), _clamp((sec_up_ratio - 0.50) * 40.0, 0.0, 10.0))
        elif sec_up_ratio <= 0.35:
            add_risk('類股輪動失溫', f'僅 {len(sec_up)}/{len(sec_list)} 類股上漲，資金集中或退潮。', _clamp((0.50 - sec_up_ratio) * 30.0, 0.0, 10.0))
    elif sources_present.get('sectors') is False:
        add_pending('類股參與度', '類股漲跌尚未載入。')

    if conc_gap is not None and conc_gap >= 3.0 and top_sec:
        add_risk(
            '產業集中度風險',
            f'最強「{top_sec["name"]}」{top_sec["changePct"]:+.2f}% 高出中位類股 {conc_gap:.2f}pct，漲勢集中度偏高。',
            _clamp((conc_gap - 3.0) * 2.5, 0.0, 14.0),
        )

    # 夜盤：有價則評；缺則 pending（OI 永遠 pending — 本系統尚未接未平倉）
    if txf_px is not None and txf_cp is not None:
        if t_cp is not None and ((t_cp >= 0 and txf_cp >= 0.3) or (t_cp <= 0 and txf_cp <= -0.3)):
            add_pos('夜盤確認', f'台指期夜盤 {txf_cp:+.2f}% 與現貨方向同向。', _clamp(abs(txf_cp) * 3.0, 0.0, 6.0))
        elif t_cp is not None and ((t_cp > 0.5 and txf_cp < -0.5) or (t_cp < -0.5 and txf_cp > 0.5)):
            add_risk('夜盤背離', f'現貨 {t_cp:+.2f}% vs 夜盤 {txf_cp:+.2f}%，隔日開盤需防缺口。', _clamp(abs(txf_cp - t_cp) * 2.0, 0.0, 10.0))
        elif abs(txf_cp) >= 1.0:
            # 無現貨對照時仍提示夜盤波動
            if txf_cp > 0:
                add_pos('夜盤偏多', f'台指期夜盤 {txf_cp:+.2f}%。', _clamp(txf_cp * 2.5, 0.0, 5.0))
            else:
                add_risk('夜盤偏空', f'台指期夜盤 {txf_cp:+.2f}%。', _clamp(abs(txf_cp) * 2.5, 0.0, 5.0))
    else:
        add_pending('台指期夜盤', '夜盤報價尚未取得。')

    add_pending('期貨未平倉量', '大台／小台 OI 尚未接入本系統；有資料前不計分。')
    add_pending('外資借券賣超', '借券賣超屬盤後清算欄位；目前端點未提供，不計分。')
    add_pending('250日新高／新低家數', '需全市場價量掃描；尚未納入廣度 API，不計分。')

    pos_sum = round(sum(f['score'] for f in positive), 1)
    risk_abs = round(sum(abs(f['score']) for f in risk), 1)
    hs = _n(health_score)
    # 風險分：以風險點數為主，健康度偏低時加重
    if risk_abs > 0 or hs is not None:
        base_risk = risk_abs * 1.15
        if hs is not None:
            base_risk = 0.65 * base_risk + 0.35 * max(0.0, 55.0 - hs)
        risk_score = round(_clamp(base_risk, 0.0, 100.0), 1)
    else:
        risk_score = None

    if hs is not None and risk_score is not None:
        total = round(_clamp(0.70 * hs + 0.30 * (100.0 - risk_score), 0.0, 100.0), 1)
    elif hs is not None:
        total = round(hs, 1)
    else:
        total = None

    # 資料完整度：預期 8 個核心集
    expected = [
        ('twindex', sources_present.get('twindex', t00.get('price') is not None)),
        ('breadth', sources_present.get('breadth', adv is not None)),
        ('marketflow', sources_present.get('marketflow', turnover_yi is not None or foreign is not None)),
        ('health', sources_present.get('health', hs is not None)),
        ('margin', sources_present.get('margin', margin_ratio is not None)),
        ('valuation', sources_present.get('valuation', median_pe is not None)),
        ('txf', sources_present.get('txf', txf_px is not None)),
        ('sectors', sources_present.get('sectors', len(sec_list) > 0)),
    ]
    have = sum(1 for _, ok in expected if ok)
    completeness = round(100.0 * have / len(expected), 1)

    tone_parts = []
    if txf_cp is not None:
        if txf_cp <= -1.5:
            tone_parts.append('夜盤偏空')
        elif txf_cp <= -0.5:
            tone_parts.append('夜盤偏弱')
        elif txf_cp >= 1.5:
            tone_parts.append('夜盤偏多')
        elif txf_cp >= 0.5:
            tone_parts.append('夜盤偏強')
        else:
            tone_parts.append('夜盤中性')
    if adv is not None:
        if adv >= 0.65:
            tone_parts.append('廣度偏多')
        elif adv <= 0.35:
            tone_parts.append('廣度偏空')
        else:
            tone_parts.append('廣度糾結')
    if hs is not None:
        tone_parts.append(f'體質 {hs:.0f}')

    return {
        'ok': True,
        'model': 'tw-pulse-intel/v1',
        'totalScore': total,
        'statusText': _label_total(total),
        'healthScore': hs,
        'healthLabel': _label_health(hs),
        'riskScore': risk_score,
        'riskLabel': _label_risk(risk_score),
        'positiveFactorScore': pos_sum,
        'riskFactorScore': -risk_abs,
        'dataCompleteness': completeness,
        'datasets': [{'key': k, 'ok': bool(ok)} for k, ok in expected],
        'datasetsOk': have,
        'datasetsTotal': len(expected),
        'positiveFactors': positive,
        'riskFactors': risk,
        'pendingFactors': pending,
        'summary': summary or (f"大盤體質 {hs}" if hs is not None else None),
        'tone': ' · '.join(tone_parts) if tone_parts else '資料彙整中',
        'pillars': pillars,
        'marketRows': market_rows or [],
        'snapshot': {
            't00': {'price': _n(t00.get('price')), 'changePct': t_cp},
            'o00': {'price': _n(o00.get('price')), 'changePct': o_cp},
            'txf': {'price': txf_px, 'changePct': txf_cp, 'ampRate': _n((txf_night or {}).get('ampRate'))},
            'stocks': {
                'up': int(up) if up is not None else None,
                'down': int(dn) if dn is not None else None,
                'unchanged': int(flat) if flat is not None else None,
                'limitUp': int(limit_up) if limit_up is not None else None,
                'limitDown': int(limit_dn) if limit_dn is not None else None,
                'advRatio': adv,
                'net': int(net_ad) if net_ad is not None else None,
            },
            'inst': {
                'foreign': foreign,
                'trust': trust,
                'dealer': dealer,
                'totalYi': inst_net_yi,
            },
            'sectorsHot': (sec_up[:6] if sec_up else []),
            'sectorsCold': (sec_dn[:6] if sec_dn else []),
            'topSector': top_sec,
            'bottomSector': bot_sec,
        },
    }
