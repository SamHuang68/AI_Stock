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
import datastore

ANN = math.sqrt(252)   # 日 → 年化


def _stats(r):
    n = len(r)
    if n < 2:
        return 0.0, 0.0
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / (n - 1)
    return mean, math.sqrt(var)


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / math.sqrt(va * vb)


def _rets_on(series, dates):
    return list(_dated_rets(series, dates).values())


def _dated_rets(series, dates):
    """保留原始相鄰日期；缺值兩側皆不產生單日報酬。"""
    out = {}
    for previous, current in zip(dates, dates[1:]):
        a, b = series.get(previous), series.get(current)
        if all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (a, b)):
            out[current] = b / a - 1
    return out


def compute(holdings, sectors_map=None, names_map=None, benchmark='^TWII'):
    """holdings: [{'sym':code,'weight':w}](weight 可不正規化,內部正規化)。"""
    wmap = {}
    for h in holdings:
        c = str(h.get('sym', '')).replace('.TW', '').replace('.TWO', '')
        if c:
            wmap[c] = wmap.get(c, 0) + float(h.get('weight') or 1)
    codes = list(wmap.keys())
    if not codes:
        return {'error': 'no holdings'}

    data = datastore.get_bars_bulk(codes + [benchmark])
    series = {c: {r[0]: r[4] for r in (data.get(c) or [])} for c in codes + [benchmark]}
    dates = sorted({t for values in series.values() for t in values})
    dated_returns = {c: _dated_rets(values, dates) for c, values in series.items()}
    vcodes = [c for c in codes if len(dated_returns[c]) > 60]
    if not vcodes:
        return {'error': 'no price data — 請先回補這些代號到 DB'}

    totw = sum(wmap[c] for c in vcodes) or 1
    weights = {c: wmap[c] / totw for c in vcodes}
    bench_returns = dated_returns[benchmark]

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
        per[c] = {'name': (names_map or {}).get(c) or c,
                  'weight': round(weights[c] * 100, 1),
                  'vol': round(sd * ANN * 100, 1),
                  'beta': round(beta, 2) if beta is not None else None}

    # 相關性(逐對共同交易日)
    corr = {}
    for i, c1 in enumerate(vcodes):
        for c2 in vcodes[i + 1:]:
            common = sorted(set(stock_ret[c1]) & set(stock_ret[c2]))
            if len(common) > 30:
                a = [stock_ret[c1][t] for t in common]
                b = [stock_ret[c2][t] for t in common]
                corr[f'{c1}|{c2}'] = round(_corr(a, b), 2)

    # 投組加總(全持倉共同交易日)
    inter = None
    for c in vcodes:
        ks = set(stock_ret[c])
        inter = ks if inter is None else (inter & ks)
    inter = sorted(inter or [])
    pvol = var95 = 0.0
    if len(inter) > 30:
        port = [sum(weights[c] * stock_ret[c][t] for c in vcodes) for t in inter]
        _, psd = _stats(port)
        pvol = psd * ANN * 100
        var95 = 1.645 * psd * 100   # 1日 95% 參數型 VaR(%)

    sect = {}
    if sectors_map:
        for c in vcodes:
            s = sectors_map.get(c) or '其他'
            sect[s] = round(sect.get(s, 0) + weights[c] * 100, 1)

    return {
        'stocks': per,
        'portfolio': {'vol': round(pvol, 1), 'var95': round(var95, 2), 'days': len(inter)},
        'corr': corr,
        'sector': sect,
        'benchmark': benchmark,
        'skipped': [c for c in codes if c not in vcodes],
    }
