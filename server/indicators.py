#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
indicators.py — 統一技術指標庫（Python 端,與 src/core/indicators_v3.js 完全對齊）

鐵律：後端所有指標計算（server.py 選股 _calc_ind、watch_daemon、alert_daemon）
一律引用本模組,不得各自實作。演算法慣例（與 TradingView / TA-Lib 對齊）:

  • 序列進、序列出；暖身期（資料不足）一律 None。
  • SMA(p)  : i >= p-1 起有效。
  • EMA(p)  : 以「前 p 根 SMA」為種子,k=2/(p+1),i >= p-1 起有效。
  • RSI(p)  : Wilder 平滑。首值=前 p 根漲跌簡單平均（於 i=p）,之後遞迴
              avg=(prev*(p-1)+cur)/p。RSI=100*avgG/(avgG+avgL)；漲跌皆 0 → 50。
  • KD(n,sm): 台股慣例 9,3,3。RSV=(C-LLV)/(HHV-LLV)*100（區間死平 → 50）,
              K=K'*(2/3)+RSV*(1/3),D=D'*(2/3)+K*(1/3),K/D 種子 50。
  • MACD    : line=EMA(f)-EMA(s)（兩者皆有效才有值）；signal 只對「有效的
              line 段」做 EMA(sig)（不以 0 充填暖身期）。
  • BB(p,k) : mid=SMA(p),母體標準差（除以 N）,上下軌 = mid ± k*std。
  • ATR(p)  : Wilder。TR 自 i=1 起（需前收）,首值=前 p 個 TR 簡單平均
              （於 i=p）,之後 atr=(prev*(p-1)+TR)/p。

對齊驗證:
  python server/indicators.py        # 跑 selftest（fixture + 期望值）
  node tests/indicators_selftest.js  # JS 端跑「同一組 fixture、同一組期望值」
兩邊期望值常數相同,任何一邊演算法分岔立刻紅燈。純 stdlib,零 pip。
"""
import math


# ── 序列版指標 ────────────────────────────────────────────────

def sma(arr, p):
    n = len(arr)
    out = [None] * n
    if p < 1:
        return out
    s = 0.0
    for i in range(n):
        s += arr[i]
        if i >= p:
            s -= arr[i - p]
        if i >= p - 1:
            out[i] = s / p
    return out


def ema(arr, p):
    n = len(arr)
    out = [None] * n
    if p < 1 or n < p:
        return out
    prev = sum(arr[:p]) / p
    out[p - 1] = prev
    k = 2.0 / (p + 1)
    for i in range(p, n):
        prev = arr[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(close, p=14):
    n = len(close)
    out = [None] * n
    if n <= p:
        return out
    g = l = 0.0
    for i in range(1, p + 1):
        d = close[i] - close[i - 1]
        if d >= 0:
            g += d
        else:
            l -= d
    g /= p
    l /= p
    out[p] = 50.0 if (g + l) == 0 else 100.0 * g / (g + l)
    for i in range(p + 1, n):
        d = close[i] - close[i - 1]
        g = (g * (p - 1) + (d if d > 0 else 0.0)) / p
        l = (l * (p - 1) + (-d if d < 0 else 0.0)) / p
        out[i] = 50.0 if (g + l) == 0 else 100.0 * g / (g + l)
    return out


def kd(high, low, close, n=9, sm=3):
    length = len(close)
    k = [None] * length
    d = [None] * length
    pk = pd = 50.0
    for i in range(length):
        if i < n - 1:
            continue
        hh = max(high[i - n + 1:i + 1])
        ll = min(low[i - n + 1:i + 1])
        rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100.0
        pk = pk * (sm - 1) / sm + rsv / sm
        pd = pd * (sm - 1) / sm + pk / sm
        k[i] = pk
        d[i] = pd
    return {'k': k, 'd': d}


def macd(close, f=12, s=26, sig=9):
    n = len(close)
    ef = ema(close, f)
    es = ema(close, s)
    line = [None] * n
    signal = [None] * n
    hist = [None] * n
    for i in range(n):
        if ef[i] is not None and es[i] is not None:
            line[i] = ef[i] - es[i]
    start = next((i for i in range(n) if line[i] is not None), -1)
    if start >= 0 and n - start >= sig:
        prev = sum(line[start:start + sig]) / sig
        signal[start + sig - 1] = prev
        kk = 2.0 / (sig + 1)
        for i in range(start + sig, n):
            prev = line[i] * kk + prev * (1 - kk)
            signal[i] = prev
    for i in range(n):
        if line[i] is not None and signal[i] is not None:
            hist[i] = line[i] - signal[i]
    return {'macd': line, 'signal': signal, 'hist': hist}


def bb(close, p=20, k=2):
    n = len(close)
    mid = sma(close, p)
    upper = [None] * n
    lower = [None] * n
    for i in range(p - 1, n):
        m = mid[i]
        v = sum((close[j] - m) ** 2 for j in range(i - p + 1, i + 1))
        sd = math.sqrt(v / p)
        upper[i] = m + k * sd
        lower[i] = m - k * sd
    return {'mid': mid, 'upper': upper, 'lower': lower}


def atr(high, low, close, p=14):
    n = len(close)
    out = [None] * n
    if n <= p:
        return out
    tr_sum = 0.0
    for i in range(1, p + 1):
        tr_sum += max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    prev = tr_sum / p
    out[p] = prev
    for i in range(p + 1, n):
        tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        prev = (prev * (p - 1) + tr) / p
        out[i] = prev
    return out


# ── 末值便利函式（給 _calc_ind / daemon 等只要最後一筆的呼叫端）──

def _last(arr):
    return arr[-1] if arr and arr[-1] is not None else None


def sma_last(arr, p):
    return _last(sma(arr, p))


def rsi_last(close, p=14):
    return _last(rsi(close, p))


def kd_last(high, low, close, n=9, sm=3):
    r = kd(high, low, close, n, sm)
    return _last(r['k']), _last(r['d'])


def atr_last(high, low, close, p=14):
    return _last(atr(high, low, close, p))


def bb_last(close, p=20, k=2):
    r = bb(close, p, k)
    return _last(r['upper']), _last(r['mid']), _last(r['lower'])


# ── Fixture + selftest（與 tests/indicators_selftest.js 共用）────
# 決定性合成 OHLC:Lehmer LCG（純整數,JS/Python 完全一致）,不用 sin/random
# → 兩語言逐位元一致,可用 1e-9 容差比對。

FIXTURE_N = 120


def make_fixture(n=FIXTURE_N):
    x = 123456789
    def rnd():
        nonlocal x
        x = (x * 48271) % 2147483647
        return x / 2147483647.0
    close, high, low = [], [], []
    c = 100.0
    for _ in range(n):
        c = c * (1 + (rnd() - 0.5) * 0.04)
        h = c * (1 + rnd() * 0.015)
        l = c * (1 - rnd() * 0.015)
        close.append(c)
        high.append(h)
        low.append(l)
    return {'high': high, 'low': low, 'close': close}


# 期望值 = 本實作對 fixture 的輸出（一次生成後凍結）。JS 端用同一組常數。
# 任何演算法變動都會讓其中一邊（或兩邊）紅燈 → 強迫兩邊同步修改。
EXPECTED = {
    'sma20_last':     95.3597471947273,
    'ema20_last':     96.27041510701059,
    'rsi14_last':     47.92438952946284,
    'rsi14_at_20':    50.26179434600121,
    'kd_k_last':      58.860988441280284,
    'kd_d_last':      52.786881663166646,
    'macd_last':      -1.1387485913740676,
    'macd_sig_last':  -1.5599486772664723,
    'macd_hist_last': 0.42120008589240476,
    'bb_up_last':     97.49211772848977,
    'bb_lo_last':     93.22737666096484,
    'atr14_last':     1.889553061138027,
}
TOL = 1e-9


def selftest():
    fx = make_fixture()
    h, l, c = fx['high'], fx['low'], fx['close']
    got = {
        'sma20_last': sma(c, 20)[-1],
        'ema20_last': ema(c, 20)[-1],
        'rsi14_last': rsi(c, 14)[-1],
        'rsi14_at_20': rsi(c, 14)[20],
        'kd_k_last': kd(h, l, c)['k'][-1],
        'kd_d_last': kd(h, l, c)['d'][-1],
        'macd_last': macd(c)['macd'][-1],
        'macd_sig_last': macd(c)['signal'][-1],
        'macd_hist_last': macd(c)['hist'][-1],
        'bb_up_last': bb(c)['upper'][-1],
        'bb_lo_last': bb(c)['lower'][-1],
        'atr14_last': atr(h, l, c)[-1],
    }
    cases = []
    for k, exp in EXPECTED.items():
        v = got[k]
        ok = v is not None and abs(v - exp) < TOL
        cases.append({'name': 'ind:' + k, 'pass': ok, 'got': v, 'exp': exp})
    # 暖身期為 None 的邊界檢查
    cases.append({'name': 'ind:rsi_warmup_null', 'pass': rsi(c, 14)[13] is None, 'got': rsi(c, 14)[13], 'exp': None})
    cases.append({'name': 'ind:sma_warmup_null', 'pass': sma(c, 20)[18] is None, 'got': sma(c, 20)[18], 'exp': None})
    cases.append({'name': 'ind:atr_warmup_null', 'pass': atr(h, l, c)[13] is None, 'got': atr(h, l, c)[13], 'exp': None})
    passed = sum(1 for x in cases if x['pass'])
    return {'passed': passed, 'total': len(cases), 'allPass': passed == len(cases), 'cases': cases}


if __name__ == '__main__':
    import json as _json
    r = selftest()
    print(_json.dumps(r, ensure_ascii=False, indent=2, default=str))
    if not r['allPass']:
        raise SystemExit(1)
    print('[indicators] selftest ALL PASS ({}/{})'.format(r['passed'], r['total']))
