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
AI 科技外溢：可選 apply_ai_tech_spillover()，只吃已抓到的 global（費半／那指／VIX），
無資料不改分、不強制 pending，避免風險頁畫空殼。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# ── 計分常數（與註解、單測共用）────────────────────────────────
EXPECTED_DATASETS = (
    'twindex', 'breadth', 'marketflow', 'health', 'margin', 'valuation',
    'txf', 'sectors', 'txOi', 'sbl', 'nhnl',
)
SECTOR_SKIP = ('加權', '櫃買', '寶島', '公司治理', '中型', '電子工業', '未含')
NHNL_MIN_SAMPLE = 12
OI_BUILD_CHG_PCT = 1.5
OI_UNWIND_CHG_PCT = -2.0
OI_PX_CONFIRM_PCT = 0.4
SBL_HEAVY_RATIO = 5.0
SBL_LIGHT_RATIO = 1.8
SBL_HEAVY_YI = 400.0
SBL_LIGHT_YI = 80.0


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
    """對齊 tw-pulse-terminal 狀態階梯（含「明顯偏強」）。"""
    if score is None:
        return '資料不足'
    if score >= 80:
        return '明顯偏強'
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


def _factor(
    fid: int,
    name: str,
    description: str,
    score: float,
    typ: str,
    mkt: str = 'TW',
) -> Dict[str, Any]:
    return {
        'id': fid,
        'name': name,
        'description': description,
        'score': round(float(score), 1),
        'type': typ,  # positive | risk | pending
        'mkt': mkt if mkt in ('TW', 'US', 'X') else 'TW',
    }


def filter_sectors(sectors: Optional[List[dict]]) -> List[dict]:
    """剔除大盤／綜合指數，僅留產業類股（供 /pulse sources 與計分對齊）。"""
    out = []
    for s in sectors or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get('name') or '')
        cp = _n(s.get('changePct'))
        if not name or cp is None:
            continue
        if any(k in name for k in SECTOR_SKIP):
            continue
        out.append({'name': name, 'changePct': cp, 'close': s.get('close')})
    return out


# 向後相容別名
_filter_sectors = filter_sectors


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
    tx_oi: Optional[dict] = None,
    sbl: Optional[dict] = None,
    nhnl: Optional[dict] = None,
) -> Dict[str, Any]:
    """由已對齊之欄位組出脈動情報 payload（純函數，可單測）。

    延伸因子（專業金融口徑）：
      tx_oi — 近月台指 OI 變化 × 價格方向 → 增倉／平倉結構
      sbl   — 借券賣出金額相對成交 → 融券／借券賣壓
      nhnl  — 流動性樣本 250 日新高／新低（誠實標註樣本數）
    """
    pillars = pillars or {}
    stocks = stocks or {}
    indices = indices or {}
    inst = inst or {}
    sources_present = dict(sources_present or {})
    tx_oi = tx_oi or {}
    sbl = sbl or {}
    nhnl = nhnl or {}

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
        """score=0 表示有資料但訊號中性（不灌水分數，仍可顯示於正面欄）。"""
        nonlocal pid
        if score is None or score < 0:
            return
        pid += 1
        positive.append(_factor(pid, name, desc, score, 'positive'))

    def add_risk(name, desc, score):
        """score 傳入負值或正的風險點數；統一存成負分。"""
        nonlocal rid
        if score is None:
            return
        sc = -abs(float(score))
        if sc > -0.05:  # 含 0：風險欄不放中性項
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
    elif any(v is not None for v in (foreign, trust, dealer)):
        # 有分項但缺體質支柱：用分項加總，不靜默略過
        net = ((foreign or 0) + (trust or 0) + (dealer or 0)) / 1e8
        if net >= 0:
            add_pos('三大法人', f'法人合計 {net:+.1f} 億（分項加總；缺體質支柱分數）。', _clamp(net / 80.0 * 10.0, 0.0, 12.0))
        else:
            add_risk('三大法人偏向風險', f'法人合計 {net:+.1f} 億（分項加總）。', _clamp(abs(net) / 80.0 * 12.0, 0.0, 14.0))
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
    else:
        add_pending('估值', '全市場本益比中位尚未就緒。')

    if limit_up is not None and up is not None and up > 0:
        ratio = limit_up / up
        if limit_up >= 8:
            add_pos('漲停動能', f'漲停 {int(limit_up)} 家（佔上漲 {ratio * 100:.1f}%）。', _clamp(limit_up / 5.0, 0.0, 8.0))
        if limit_dn is not None and limit_dn >= 8 and (limit_up or 0) < limit_dn:
            add_risk('跌停壓力', f'跌停 {int(limit_dn)} 家多於漲停 {int(limit_up or 0)}，尾盤情緒偏防衛。', _clamp(limit_dn / 5.0, 0.0, 8.0))

    if sec_up_ratio is not None:
        if sec_up_ratio >= 0.55:
            names = '、'.join(s['name'] for s in sec_up[:3])
            add_pos(
                '類股參與度',
                f'{len(sec_up)}/{len(sec_list)} 類股上漲'
                + (f'（強：{names}）' if names else '')
                + '｜廣基上漲優於權值獨強。',
                _clamp((sec_up_ratio - 0.50) * 40.0, 0.0, 10.0),
            )
        elif sec_up_ratio <= 0.40:
            add_risk(
                '類股輪動失溫',
                f'僅 {len(sec_up)}/{len(sec_list)} 類股上漲，資金集中或退潮，追價勝率下降。',
                _clamp((0.50 - sec_up_ratio) * 30.0, 0.0, 10.0),
            )
        else:
            # 中性帶：有資料但不灌水分數
            add_pos(
                '類股參與度',
                f'{len(sec_up)}/{len(sec_list)} 類股上漲，參與度中性。',
                0.0,
            )
    else:
        add_pending('類股參與度', '類股漲跌尚未載入（MI_INDEX IND）。')

    if conc_gap is not None and conc_gap >= 3.0 and top_sec:
        add_risk(
            '產業集中度風險',
            f'最強「{top_sec["name"]}」{top_sec["changePct"]:+.2f}% 高出中位類股 {conc_gap:.2f}pct，漲勢集中度偏高。',
            _clamp((conc_gap - 3.0) * 2.5, 0.0, 14.0),
        )

    # 夜盤：有價則評；缺則 pending
    if txf_px is not None and txf_cp is not None:
        if t_cp is not None and ((t_cp >= 0 and txf_cp >= 0.3) or (t_cp <= 0 and txf_cp <= -0.3)):
            add_pos('夜盤確認', f'台指期夜盤 {txf_cp:+.2f}% 與現貨方向同向。', _clamp(abs(txf_cp) * 3.0, 0.0, 6.0))
        elif t_cp is not None and ((t_cp > 0.5 and txf_cp < -0.5) or (t_cp < -0.5 and txf_cp > 0.5)):
            add_risk('夜盤背離', f'現貨 {t_cp:+.2f}% vs 夜盤 {txf_cp:+.2f}%，隔日開盤需防缺口。', _clamp(abs(txf_cp - t_cp) * 2.0, 0.0, 10.0))
        elif abs(txf_cp) >= 1.0:
            if txf_cp > 0:
                add_pos('夜盤偏多', f'台指期夜盤 {txf_cp:+.2f}%。', _clamp(txf_cp * 2.5, 0.0, 5.0))
            else:
                add_risk('夜盤偏空', f'台指期夜盤 {txf_cp:+.2f}%。', _clamp(abs(txf_cp) * 2.5, 0.0, 5.0))
    else:
        add_pending('台指期夜盤', '夜盤報價尚未取得。')

    # ── 期貨未平倉：OI↑+價↑＝趨勢增倉；OI↑+價↓＝空頭增倉／多殺多；OI↓＝平倉 ──
    oi = _n(tx_oi.get('oi'))
    oi_chg_pct = _n(tx_oi.get('oiChgPct'))
    oi_px_chg = _n(tx_oi.get('priceChgPct'))
    if oi is not None and oi_chg_pct is not None:
        contract = tx_oi.get('contract') or '近月'
        base = f'TX{contract} OI {oi:,.0f}（{oi_chg_pct:+.2f}%）'
        if oi_px_chg is not None:
            base += f'｜期價 {oi_px_chg:+.2f}%'
        if oi_chg_pct >= OI_BUILD_CHG_PCT and (oi_px_chg is not None and oi_px_chg >= OI_PX_CONFIRM_PCT):
            add_pos(
                '期貨未平倉量',
                base + '｜價漲+OI增＝多方增倉，趨勢延續機率上升。',
                _clamp(oi_chg_pct * 1.6 + max(0.0, oi_px_chg) * 0.8, 0.0, 10.0),
            )
        elif oi_chg_pct >= OI_BUILD_CHG_PCT and (oi_px_chg is not None and oi_px_chg <= -OI_PX_CONFIRM_PCT):
            add_risk(
                '期貨未平倉量',
                base + '｜價跌+OI增＝空頭增倉或被迫停損，波動風險升高。',
                _clamp(oi_chg_pct * 1.8 + abs(min(0.0, oi_px_chg)) * 0.9, 0.0, 12.0),
            )
        elif oi_chg_pct <= OI_UNWIND_CHG_PCT and (oi_px_chg is not None and oi_px_chg <= -0.5):
            add_risk(
                '期貨未平倉量',
                base + '｜價跌+OI減＝多頭減倉／停損出場，動能走弱。',
                _clamp(abs(oi_chg_pct) * 1.2, 0.0, 9.0),
            )
        elif oi_chg_pct <= OI_UNWIND_CHG_PCT and (oi_px_chg is not None and oi_px_chg >= OI_PX_CONFIRM_PCT):
            add_pos(
                '期貨未平倉量',
                base + '｜價漲+OI減＝空頭回補，短線易有軋空彈。',
                _clamp(abs(oi_chg_pct) * 1.1, 0.0, 8.0),
            )
        else:
            # 有資料、訊號不明：顯示但不灌分
            note = 'OI 變化溫和，方向訊號不明顯。' if abs(oi_chg_pct) >= 0.8 else 'OI 持穩。'
            add_pos('期貨未平倉量', base + '｜' + note, 0.0)
    else:
        add_pending('期貨未平倉量', '大台近月同契約 OI 尚未取得（FinMind／日盤；換月週不強行對齊）。')

    # ── 借券賣出：相對成交的空方供給（TWTASU 全市場合計；非外資分項）──
    sbl_yi = _n(sbl.get('sblSellYi'))
    margin_yi = _n(sbl.get('marginSellYi'))
    if sbl_yi is not None:
        # 相對大盤成交：≥ SBL_HEAVY_RATIO% 或絕對額 ≥ SBL_HEAVY_YI 億 → 偏重
        ratio = None
        if turnover_yi and turnover_yi > 0:
            ratio = (sbl_yi / turnover_yi) * 100.0
        desc = f'借券賣出 {sbl_yi:.1f} 億'
        if margin_yi is not None:
            desc += f'｜融券賣出 {margin_yi:.1f} 億'
        if ratio is not None:
            desc += f'｜佔成交 {ratio:.2f}%'
        desc += '（TWSE TWTASU 全市場）。'
        if (ratio is not None and ratio >= SBL_HEAVY_RATIO) or sbl_yi >= SBL_HEAVY_YI:
            add_risk(
                '借券賣出壓力',
                desc + '借券賣壓偏重，權值股易見外資／避險放空。',
                _clamp((ratio or SBL_HEAVY_RATIO) * 1.4 + max(0.0, sbl_yi - 250) / 80.0, 0.0, 14.0),
            )
        elif (ratio is not None and ratio <= SBL_LIGHT_RATIO) or sbl_yi <= SBL_LIGHT_YI:
            add_pos(
                '借券賣出壓力',
                desc + '借券賣壓偏輕，空方供給壓力緩和。',
                _clamp(4.0 - (ratio or 1.5), 0.0, 6.0),
            )
        else:
            add_pos('借券賣出壓力', desc + '借券賣壓中性。', 0.0)
    else:
        add_pending('借券賣出壓力', 'TWTASU 借券賣出成交量值尚未載入。')

    # ── 250 日新高／新低：流動性樣本（誠實揭露 sampleN）──
    nh = _n(nhnl.get('newHighs'))
    nl = _n(nhnl.get('newLows'))
    sample_n = _n(nhnl.get('sampleN'))
    nhnl_ok = (
        nh is not None and nl is not None
        and sample_n is not None and sample_n >= NHNL_MIN_SAMPLE
    )
    if nhnl_ok:
        nh_i, nl_i = int(nh), int(nl)
        note = nhnl.get('note') or f'樣本 {int(sample_n)} 檔'
        net = nh_i - nl_i
        breadth = (nh_i / (nh_i + nl_i)) if (nh_i + nl_i) else None
        desc = f'250日新高 {nh_i}／新低 {nl_i}｜{note}'
        if breadth is not None:
            desc += f'｜新高佔比 {breadth * 100:.0f}%'
        if net >= 4 and nh_i >= 3:
            add_pos(
                '250日新高／新低家數',
                desc + '｜新高擴散，中期動能偏多（樣本非全市場）。',
                _clamp(net * 1.2 + nh_i * 0.4, 0.0, 10.0),
            )
        elif net <= -4 and nl_i >= 3:
            add_risk(
                '250日新高／新低家數',
                desc + '｜新低擴散，中期結構轉弱（樣本非全市場）。',
                _clamp(abs(net) * 1.3 + nl_i * 0.4, 0.0, 12.0),
            )
        else:
            add_pos('250日新高／新低家數', desc + '｜新高／新低糾結。', 0.0)
    else:
        add_pending(
            '250日新高／新低家數',
            f'流動性樣本掃描尚未完成（需 ≥{NHNL_MIN_SAMPLE} 檔有效 250 日序列；非全市場掃描）。',
        )

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

    # 資料完整度：EXPECTED_DATASETS（8 核心 + 3 延伸）
    auto = {
        'twindex': t00.get('price') is not None,
        'breadth': adv is not None,
        'marketflow': turnover_yi is not None or foreign is not None,
        'health': hs is not None,
        'margin': margin_ratio is not None,
        'valuation': median_pe is not None,
        'txf': txf_px is not None,
        'sectors': len(sec_list) > 0,
        'txOi': oi is not None and oi_chg_pct is not None,
        'sbl': sbl_yi is not None,
        'nhnl': nhnl_ok,
    }
    expected = [(k, bool(sources_present[k]) if k in sources_present else auto[k]) for k in EXPECTED_DATASETS]
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



def _quote_map(global_quotes: Optional[List[dict]]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for row in global_quotes or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get('symbol') or '').strip()
        if sym:
            out[sym] = row
    return out


def _tw_semi_change(sectors: Optional[List[dict]]) -> Optional[float]:
    """台股半導體／電子相關類股當日漲跌（有則回傳中位或最強代表）。"""
    keys = ('半導體', '電子', '光電', '電腦', '通信', '資訊')
    vals = []
    for s in filter_sectors(sectors):
        name = str(s.get('name') or '')
        cp = _n(s.get('changePct'))
        if cp is None:
            continue
        if any(k in name for k in keys):
            vals.append(cp)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def apply_ai_tech_spillover(
    payload: Dict[str, Any],
    global_quotes: Optional[List[dict]] = None,
    sectors: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """用 /pulse 既有 global 報價補強「AI／科技外溢」因子（台股供應鏈連動）。

    設計原則：
      • 主訊號 = 費半 ^SOX（半導體鏈 ↔ 台積電／權值電子）
      • 確認 = NASDAQ ^IXIC；放大器 = VIX
      • 可選對照 = 台股半導體類股；個股代理 NVDA／AVGO／TSM（有才顯示）
      • 缺資料 → 不改分數、不加假 pending、回傳 spillover.ok=False（前端隱藏區塊）
      • 權重封頂偏軟（風險 ≤10、正面 ≤8），不壓過台股主帳本
    """
    if not isinstance(payload, dict) or not payload.get('ok'):
        return payload

    qm = _quote_map(global_quotes)
    sox = _n((qm.get('^SOX') or {}).get('changePct'))
    ixic = _n((qm.get('^IXIC') or {}).get('changePct'))
    gspc = _n((qm.get('^GSPC') or {}).get('changePct'))
    vix_lv = _n((qm.get('^VIX') or {}).get('price'))
    vix_cp = _n((qm.get('^VIX') or {}).get('changePct'))
    nvda = _n((qm.get('NVDA') or {}).get('changePct'))
    avgo = _n((qm.get('AVGO') or {}).get('changePct'))
    tsm = _n((qm.get('TSM') or {}).get('changePct'))
    tw_semi = _tw_semi_change(sectors)

    # 至少要有費半或那指，才算有可用外溢訊號
    if sox is None and ixic is None:
        snap = dict(payload.get('snapshot') or {})
        snap['aiSpill'] = {
            'ok': False,
            'reason': 'no_sox_ixic',
        }
        payload['snapshot'] = snap
        payload['aiSpill'] = snap['aiSpill']
        return payload

    lead = sox if sox is not None else ixic
    bits = []
    if sox is not None:
        bits.append(f'費半 {sox:+.2f}%')
    if ixic is not None:
        bits.append(f'NASDAQ {ixic:+.2f}%')
    if gspc is not None:
        bits.append(f'S&P500 {gspc:+.2f}%')
    if vix_lv is not None:
        bits.append(f'VIX {vix_lv:.1f}' + (f'（{vix_cp:+.1f}%）' if vix_cp is not None else ''))
    proxy_bits = []
    if nvda is not None:
        proxy_bits.append(f'NVDA {nvda:+.2f}%')
    if avgo is not None:
        proxy_bits.append(f'AVGO {avgo:+.2f}%')
    if tsm is not None:
        proxy_bits.append(f'TSM {tsm:+.2f}%')
    if tw_semi is not None:
        bits.append(f'台半導類 {tw_semi:+.2f}%')
    desc_core = '｜'.join(bits)

    risk = list(payload.get('riskFactors') or [])
    positive = list(payload.get('positiveFactors') or [])
    next_rid = max([f.get('id') or 0 for f in risk] + [0]) + 1
    next_pid = max([f.get('id') or 0 for f in positive] + [0]) + 1

    direction = 'flat'
    factor = None

    # 背離：美科技弱、台半導仍強 → 外溢警戒（隔日缺口風險）
    diverge = (
        sox is not None and tw_semi is not None
        and sox <= -1.2 and tw_semi >= 0.8
    )

    if lead is not None and lead <= -1.2:
        pts = _clamp(abs(lead) * 2.2, 0.0, 10.0)
        if vix_lv is not None and vix_lv >= 25.0:
            pts = _clamp(pts + min(4.0, (vix_lv - 22.0) * 0.5), 0.0, 12.0)
        if diverge:
            pts = _clamp(pts + 2.0, 0.0, 12.0)
        note = desc_core + '｜半導體鏈偏弱，台股 AI／權值電子隔日外溢風險升高。'
        if proxy_bits:
            note += '｜' + '、'.join(proxy_bits)
        if diverge:
            note += '｜台半導仍強、美科技轉弱，留意缺口與外資調節。'
        factor = _factor(next_rid, 'AI科技外溢偏空', note, -abs(pts), 'risk', mkt='US')
        risk.append(factor)
        direction = 'risk'
    elif lead is not None and lead >= 1.2:
        pts = _clamp(lead * 1.8, 0.0, 8.0)
        note = desc_core + '｜美科技偏多，有助台股半導體／AI 鏈風險偏好。'
        if proxy_bits:
            note += '｜' + '、'.join(proxy_bits)
        factor = _factor(next_pid, 'AI科技外溢偏多', note, pts, 'positive', mkt='US')
        positive.append(factor)
        direction = 'pos'
    elif diverge:
        pts = _clamp(abs(sox) * 1.5 + 1.0, 0.0, 8.0)
        note = desc_core + '｜美科技轉弱但台半導仍強，外溢背離警戒。'
        factor = _factor(next_rid, 'AI科技外溢背離', note, -abs(pts), 'risk', mkt='US')
        risk.append(factor)
        direction = 'risk'
    else:
        # 中性：不灌水，僅記錄可讀快照
        direction = 'flat'

    # 重算風險／總分（與 build_pulse_intel 同一公式）
    pos_sum = round(sum(float(f.get('score') or 0) for f in positive), 1)
    risk_abs = round(sum(abs(float(f.get('score') or 0)) for f in risk), 1)
    hs = _n(payload.get('healthScore'))
    if risk_abs > 0 or hs is not None:
        base_risk = risk_abs * 1.15
        if hs is not None:
            base_risk = 0.65 * base_risk + 0.35 * max(0.0, 55.0 - hs)
        risk_score = round(_clamp(base_risk, 0.0, 100.0), 1)
    else:
        risk_score = payload.get('riskScore')

    if hs is not None and risk_score is not None:
        total = round(_clamp(0.70 * hs + 0.30 * (100.0 - risk_score), 0.0, 100.0), 1)
    else:
        total = payload.get('totalScore')

    payload['positiveFactors'] = positive
    payload['riskFactors'] = risk
    payload['positiveFactorScore'] = pos_sum
    payload['riskFactorScore'] = -risk_abs
    payload['riskScore'] = risk_score
    payload['riskLabel'] = _label_risk(risk_score if isinstance(risk_score, (int, float)) else None)
    payload['totalScore'] = total
    payload['statusText'] = _label_total(total if isinstance(total, (int, float)) else None)

    tone = str(payload.get('tone') or '')
    if direction == 'risk' and 'AI外溢偏空' not in tone:
        payload['tone'] = (tone + ' · ' if tone else '') + 'AI外溢偏空'
    elif direction == 'pos' and 'AI外溢偏多' not in tone:
        payload['tone'] = (tone + ' · ' if tone else '') + 'AI外溢偏多'

    spill = {
        'ok': True,
        'direction': direction,
        'soxChangePct': sox,
        'ixicChangePct': ixic,
        'gspcChangePct': gspc,
        'vixLevel': vix_lv,
        'vixChangePct': vix_cp,
        'nvdaChangePct': nvda,
        'avgoChangePct': avgo,
        'tsmChangePct': tsm,
        'twSemiChangePct': tw_semi,
        'factorName': (factor or {}).get('name'),
        'factorScore': (factor or {}).get('score'),
    }
    snap = dict(payload.get('snapshot') or {})
    snap['aiSpill'] = spill
    payload['snapshot'] = snap
    payload['aiSpill'] = spill
    # 模型標記：台股主帳本 + 可選 AI 外溢
    if payload.get('model') == 'tw-pulse-intel/v1':
        payload['model'] = 'tw-pulse-intel/v1+ai-spill'
    return payload
