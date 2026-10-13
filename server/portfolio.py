#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio.py — v4.0 投組風險引擎(純 stdlib)

讀本機時序 DB(datastore)的多檔日線,算投組層級風險:
  - 每檔:年化波動%、Beta(對 ^TWII)、權重
  - 投組:加權年化波動%、1日 95% VaR%、有效樣本天數
  - 相關性矩陣(逐對以共同交易日對齊)
  - 產業曝險(由 server 傳入 sectors_map)
供應鏈曝險不在這裡算 — 沿用前端 supplychain_v3.js 的 CHAIN_TW(你 curated 的對照),
避免在後端重編一份而分歧。
"""
import math
import json
import sqlite3
import datastore
from stock_signals import bar_date, normalize_bars


def _risk_series(connection, code, rows, *, benchmark=False):
    """沿用來源品質及單一還原快照；未核對的原價不能推導投組風險。"""
    from daily_quality import quality_evidence
    from 個股還原研究 import load_snapshot, adjusted_bars
    from 台股交易參考 import split_references
    bars = normalize_bars(rows, 'TW')
    if not bars:
        return {}, '缺少歷史'
    first, last = bars[0]['date'], bars[-1]['date']
    evidence = quality_evidence(connection, code, start=first, end=last)
    conflicts = ('priceConflict', 'sourceConflict', 'ambiguousSession', 'invalidObservation', 'invalidReceipt')
    if any(any(item.get(k) for k in conflicts) for item in evidence.values()):
        return {}, '日線品質或來源存在衝突'
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'bar_quality' in tables:
        issues = connection.execute('SELECT session_date,issues FROM bar_quality WHERE market=? AND symbol=? AND session_date BETWEEN ? AND ?',
                                    ('TW', code, first, last)).fetchall()
        # 官方量價差異共用舊標籤；價格已有分欄核對時，純成交量差異不能否決收盤風險。
        if any(json.loads(raw) and not (
                json.loads(raw) == ['官方來源與原始日線不同；原始值保留']
                and evidence.get(day, {}).get('priceVerified')) for day, raw in issues):
            return {}, '日線品質紀錄尚有未解問題'
    # 指數本身不適用個股公司行動；來源衝突仍會在上方擋下。
    if benchmark and code.startswith('^'):
        return {b['date']: b['close'] for b in bars}, None
    # 缺收盤的日期留給 _dated_rets 阻擋兩側報酬；不因此丟棄其他已核對價格。
    priced = [b for b in bars if b.get('close') is not None and math.isfinite(b['close']) and b['close'] > 0]
    adjusted = adjusted_bars(priced, load_snapshot(connection, code)) if priced else None
    if adjusted:
        return {b['date']: b['close'] for b in adjusted}, None
    coverage = connection.execute('SELECT start_date,end_date FROM action_coverage WHERE market=? AND symbol=?', ('TW', code)).fetchone() if 'action_coverage' in tables else None
    actions = connection.execute('SELECT session_date FROM corporate_actions WHERE market=? AND symbol=? AND session_date>? AND session_date<=?',
                                 ('TW', code, first, last)).fetchall() if 'corporate_actions' in tables else []
    known_split = any(first < item['date'] <= last for item in split_references(code))
    if actions or known_split:
        return {}, '涵蓋公司行動但缺少可比還原價格'
    if not coverage or not coverage[0] <= first <= last <= coverage[1]:
        return {}, '公司行動涵蓋不足，原價基準未核對'
    if any(not evidence.get(b['date'], {}).get('priceVerified') for b in bars):
        return {}, '原價品質尚未核對'
    return {b['date']: b['close'] for b in bars}, None

ANN = math.sqrt(252)   # 日 → 年化


def _stats(r):
    n = len(r)
    if n < 2:
        return 0.0, 0.0
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / (n - 1)
    return mean, math.sqrt(var)


def _corr(a, b):
    """回傳皮爾森相關；樣本不足或任一側方差為 0 時回 None，不冒用 0。"""
    n = min(len(a), len(b))
    if n < 2:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


def _rets_on(series, dates):
    return list(_dated_rets(series, dates).values())


def _dated_rets(series, dates):
    """保留原始相鄰日期；缺值兩側皆不產生單日報酬。"""
    out = {}
    for previous, current in zip(dates, dates[1:]):
        a, b = series.get(previous), series.get(current)
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and v > 0 for v in (a, b)):
            value = b / a - 1
            if math.isfinite(value):
                out[current] = value
    return out


def _norm_code(sym):
    """正規化 .TW/.TWO 後綴；必須先比對較長後綴避免 6488.TWO 被截成 6488O。"""
    from market_contract import tw_symbol_code
    return tw_symbol_code(sym)


def _coerce_weight(raw):
    """解析明示權重；空值、布林、非數值、負數及非有限數均拒絕。"""
    if raw is None:
        raise ValueError('明示空白權重無法計算')
    if isinstance(raw, bool):
        raise ValueError('權重不可為布林')
    if isinstance(raw, (int, float)):
        w = float(raw)
    else:
        try:
            w = float(raw)
        except (TypeError, ValueError):
            raise ValueError('權重需為數值')
    if not math.isfinite(w):
        raise ValueError('權重不可為 NaN 或 Infinity')
    if w < 0:
        raise ValueError('權重不可為負')
    return w


def compute(holdings, sectors_map=None, names_map=None, benchmark='^TWII'):
    """holdings: [{'sym':code,'weight':w}]。

    權重處理原則：
      - 缺 weight 預設為 1；weight=0 視為無效倉位（不會被改寫為 1）。
      - 非法權重（布林、非數值、負數、NaN、Infinity）被拒絕並記入 rejected。
      - 分母以使用者完整有效正權重合計；缺歷史的持股不會被重新分配權重。
    """
    wmap = {}
    rejected = []
    for h in holdings or []:
        if not isinstance(h, dict):
            rejected.append({'sym': None, 'reason': '持倉需為物件'})
            continue
        sym_raw = h.get('sym', '')
        try:
            c = _norm_code(sym_raw)
            if not c:
                continue
            w = _coerce_weight(h.get('weight', 1))
        except (ValueError, OverflowError) as exc:
            rejected.append({'sym': sym_raw, 'reason': str(exc)})
            continue
        if w == 0:
            # 權重 0 的部位不視為有效持股；但明確保留「0 不會變成 1」的語意。
            continue
        wmap[c] = wmap.get(c, 0.0) + w

    codes = list(wmap.keys())
    # 非法權重使完整分母未知；不能略過後把其餘持股當成完整投組。
    if rejected or not math.isfinite(sum(wmap.values())):
        return {'error': '持倉權重無效，請修正後重新分析', 'rejected': rejected,
                'stocks': {}, 'portfolio': {'vol': None, 'var95': None, 'days': 0},
                'corr': {}, 'sector': {}, 'benchmark': benchmark, 'skipped': codes,
                'quality': {'available': False, 'holdingCoveragePct': None,
                            'betaCoveragePct': None, 'commonSampleDays': 0,
                            'reasons': ['持倉權重無效，完整投組分母未知']}}
    if not codes:
        return {'error': 'no holdings', 'rejected': rejected}

    series, price_issues = {}, {}
    try:
        with datastore.read_snapshot() as connection:
            data = datastore.get_bars_bulk(codes + [benchmark], connection=connection)
            for code in codes + [benchmark]:
                values, issue = _risk_series(connection, code, data.get(code) or [], benchmark=code == benchmark)
                series[code] = values
                if issue:
                    price_issues[code] = issue
            observed = sorted({t for values in series.values() for t in values})
            from 台股交易參考 import verified_sessions
            dates = verified_sessions(observed[0], observed[-1], connection=connection, allow_partial=True) if observed else []
            if dates is None:
                dates = []
                price_issues['calendar'] = '交易日曆涵蓋不足'
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
        from log_once import log_once
        log_once('portfolio-price-quality', '投組價格品質核對失敗', exc=exc)
        dates = []
        price_issues['source'] = '價格品質或公司行動資料無法核對'
    dated_returns = {c: _dated_rets(values, dates) for c, values in series.items()}
    vcodes = [c for c in codes if len(dated_returns.get(c, {})) > 60]

    # 分母採用使用者完整有效正權重合計；缺歷史部位不會被重新分配到其餘持股。
    total_weight = sum(wmap.values()) or 1.0
    weights = {c: wmap[c] / total_weight for c in vcodes}
    bench_returns = dated_returns.get(benchmark, {})

    per = {}
    stock_ret = {}   # c -> {ts: ret}
    for c in vcodes:
        stock_ret[c] = dated_returns[c]
        rets = list(stock_ret[c].values())
        _, sd = _stats(rets)
        beta = None
        common = sorted(set(stock_ret[c]) & set(bench_returns))
        if len(common) > 30:
            sr = [stock_ret[c][t] for t in common]
            br = [bench_returns[t] for t in common]
            n = min(len(sr), len(br)); sr, br = sr[-n:], br[-n:]
            mb = sum(br) / n; vb = sum((x - mb) ** 2 for x in br)
            if vb > 0:
                ma = sum(sr) / n
                cov = sum((sr[i] - ma) * (br[i] - mb) for i in range(n))
                beta = cov / vb
        # 真實零波動仍視為有效 0；僅在運算無法成立時標 None。
        per[c] = {'name': (names_map or {}).get(c) or c,
                  'weight': round(weights[c] * 100, 1),
                  'vol': round(sd * ANN * 100, 1),
                  'beta': round(beta, 2) if beta is not None else None}

    # 相關性(逐對共同交易日)：零方差或樣本不足時以 None 表示，避免冒用 0。
    corr = {}
    for i, c1 in enumerate(vcodes):
        for c2 in vcodes[i + 1:]:
            common = sorted(set(stock_ret[c1]) & set(stock_ret[c2]))
            key = f'{c1}|{c2}'
            if len(common) <= 30:
                corr[key] = None
                continue
            a = [stock_ret[c1][t] for t in common]
            b = [stock_ret[c2][t] for t in common]
            cv = _corr(a, b)
            corr[key] = round(cv, 2) if cv is not None else None

    # 投組加總(全持倉共同交易日)
    inter = None
    for c in vcodes:
        ks = set(stock_ret[c])
        inter = ks if inter is None else (inter & ks)
    inter = sorted(inter or [])

    skipped = [c for c in codes if c not in vcodes]
    coverage_pct = sum(weights.values()) * 100.0
    beta_coverage_pct = sum(weights[c] for c in vcodes if per[c]['beta'] is not None) * 100.0

    reasons = [f'{code}：{issue}' for code, issue in price_issues.items()]
    if skipped:
        reasons.append('部分持倉缺少足夠歷史')
    if len(inter) <= 30:
        reasons.append('共同有效報酬不足 31 筆')
    if beta_coverage_pct < 100.0 - 1e-8:
        reasons.append('部分持倉缺少可驗證的基準 Beta')
    if rejected:
        reasons.append('部分持倉權重不合法已被拒絕')

    pvol = var95 = None
    # 共同報酬少於 31 筆或存在缺歷史持倉時，投組 vol/var95 標 None 不臆測。
    if len(inter) > 30 and not skipped:
        port = [sum(weights[c] * stock_ret[c][t] for c in vcodes) for t in inter]
        _, psd = _stats(port)
        pvol = psd * ANN * 100           # 真實零波動 → 0.0 仍為有效答案
        var95 = 1.645 * psd * 100        # 1日 95% 參數型 VaR(%)，公式不變

    sect = {}
    if sectors_map:
        for c in vcodes:
            s = sectors_map.get(c) or '其他'
            sect[s] = round(sect.get(s, 0) + weights[c] * 100, 1)

    return {
        'stocks': per,
        'portfolio': {
            'vol': round(pvol, 1) if pvol is not None else None,
            'var95': round(var95, 2) if var95 is not None else None,
            'days': len(inter),
        },
        'corr': corr,
        'sector': sect,
        'benchmark': benchmark,
        'skipped': skipped,
        'rejected': rejected,
        'quality': {
            'available': not reasons,
            'holdingCoveragePct': round(coverage_pct, 4),
            'betaCoveragePct': round(beta_coverage_pct, 4),
            'commonSampleDays': len(inter),
            'reasons': reasons,
            'priceIssues': price_issues,
        },
    }
