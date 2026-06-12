#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Stock Terminal v3.8 — 每日 TSMC 核心晨報 Email
# ------------------------------------------------------------
# 盤前自動寄出：美股夜盤(NQ/ES/SOX) + TSM ADR + 台指期夜盤 + 加權，
# 算「TSMC 核心連動(2330 隔日預估)」與「台股隔日預估」，HTML 寄到信箱。
# 純數據(無 LLM)，需 server.py 跑著 + alert_config.json email 設好。
# 用法：python daily_morning_brief.py
# 排程：install_morning_scheduler.bat（每交易日 07:30）
# ============================================================
import json, urllib.request, sys
from datetime import datetime

PORT = 18432
try:
    import alert_daemon
except Exception as e:
    print('[brief] alert_daemon import failed:', e); sys.exit(2)

# 夜盤領先指標（與夜盤面板同權重）
DRIVERS = [('NQ=F', '那斯達克期', 0.35), ('ES=F', '標普500期', 0.20),
           ('YM=F', '道瓊期', 0.10), ('^SOX', '費半', 0.35)]


def _pct_daily(sym):
    """用 /yf?range=5d&interval=1d 算 現價 vs 前一交易日收盤（與前端夜盤一致）"""
    try:
        url = f'http://localhost:{PORT}/yf/{urllib.parse.quote(sym)}?range=5d&interval=1d'
    except Exception:
        url = f'http://localhost:{PORT}/yf/{sym}?range=5d&interval=1d'
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            j = json.loads(r.read())
        res = j['chart']['result'][0]
        meta = res.get('meta', {})
        ts = res.get('timestamp') or []
        cl = (res.get('indicators', {}).get('quote') or [{}])[0].get('close') or []
        valid = [(ts[i], cl[i]) for i in range(min(len(ts), len(cl))) if cl[i] is not None and ts[i] is not None]
        if not valid:
            return None, None
        lt, lc = valid[-1]
        prevc = valid[-2][1] if len(valid) >= 2 else None
        rmt, rmp = meta.get('regularMarketTime'), meta.get('regularMarketPrice')
        if rmt and isinstance(rmp, (int, float)) and rmp > 0 and rmt - lt > 20 * 3600:
            cur, prev = rmp, lc
        else:
            cur, prev = lc, (prevc if prevc is not None else meta.get('chartPreviousClose') or meta.get('previousClose'))
        if cur is None or not prev:
            return cur, None
        return cur, (cur - prev) / prev * 100
    except Exception:
        return None, None


import urllib.parse  # noqa: E402


def _txf():
    try:
        with urllib.request.urlopen(f'http://localhost:{PORT}/txf', timeout=12) as r:
            d = json.loads(r.read())
        if d.get('ok'):
            return d.get('price'), d.get('changePct')
    except Exception:
        pass
    return None, None


def _c(p):
    if p is None:
        return '<span style="color:#94a3b8">—</span>'
    col = '#ef4444' if p > 0 else ('#22c55e' if p < 0 else '#94a3b8')   # 台股紅漲綠跌
    return f'<span style="color:{col};font-weight:700">{p:+.2f}%</span>'


def main():
    date = datetime.now().strftime('%Y-%m-%d')
    rows = []
    comp = wsum = 0.0
    for sym, name, w in DRIVERS:
        _, p = _pct_daily(sym)
        if p is not None:
            comp += p * w; wsum += w
        rows.append(f'<tr><td>{name} <span style="color:#64748b;font-size:10px">{sym}</span></td><td style="text-align:right">{_c(p)}</td></tr>')
    est = (comp / wsum) if wsum else None

    _, tsm_p = _pct_daily('TSM')        # 台積電 ADR → 2330 隔日先行
    txf_price, txf_p = _txf()           # 台指期夜盤
    _, twii_p = _pct_daily('^TWII')

    tone = ('資料不足' if est is None else
            '⚠ 強烈開低風險' if est <= -1.5 else '偏弱：開低機率高' if est <= -0.5 else
            '🔥 強烈開高' if est >= 1.5 else '偏強：開高機率高' if est >= 0.5 else '中性：波動有限')

    html = f"""<div style="font-family:-apple-system,'Microsoft JhengHei',sans-serif;background:#0b1220;color:#e2e8f0;padding:16px;max-width:640px;margin:auto">
      <h2 style="color:#fbbf24;margin:0 0 4px">🌅 TSMC 核心晨報 · {date}</h2>
      <div style="color:#94a3b8;font-size:12px;margin-bottom:12px">盤前美股夜盤 → 台股隔日預估（台股紅漲綠跌）</div>

      <div style="text-align:center;margin:10px 0">
        <div style="font-size:11px;color:#94a3b8">台股隔日預估</div>
        <div style="font-size:30px;font-weight:800">{_c(est)}</div>
        <div style="font-size:12px;color:#cbd5e1">{tone}</div>
      </div>

      <div style="border:1px solid #334155;border-radius:8px;padding:10px;background:rgba(251,191,36,.06);margin:10px 0">
        <div style="font-weight:700;color:#fbbf24;font-size:13px">🔱 TSMC 核心連動（2330）</div>
        <div style="font-size:13px;margin-top:4px">TSM ADR 夜盤 {_c(tsm_p)} → <b>2330 隔日預估 ≈ {_c(tsm_p)}</b>（主要看 TSM ADR）</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:3px">台指期夜盤 {('{:,.0f}'.format(txf_price)) if txf_price else '—'} {_c(txf_p)}　加權(前日收) {_c(twii_p)}</div>
        <div style="font-size:10px;color:#64748b;line-height:1.6;margin-top:5px">長線：TSMC＝AI 核心、先進製程獨佔；TSM/費半漲→2330 隔日多反映。4 大 CSP 投資集中台灣供應鏈(晶圓→3D封裝→CPO→AI伺服器)，台股量能 8000億→1.2兆＋ 結構多頭。</div>
      </div>

      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <tr><th style="text-align:left;color:#94a3b8;border-bottom:1px solid #334155;padding:4px">夜盤領先指標</th><th style="text-align:right;color:#94a3b8;border-bottom:1px solid #334155;padding:4px">夜盤漲跌</th></tr>
        {''.join(rows)}
      </table>
      <div style="margin-top:12px;color:#64748b;font-size:10px">⚠ 僅供參考、非投資建議。Stock Terminal v3.8 自動晨報。</div>
    </div>"""

    text = f"TSMC 核心晨報 {date}\n台股隔日預估 {est:+.2f}% ({tone})\nTSM ADR {tsm_p:+.2f}% → 2330 隔日預估≈{tsm_p:+.2f}%\n台指期夜盤 {txf_p}" if (est is not None and tsm_p is not None) else f"TSMC 核心晨報 {date}（資料不足）"

    cfg = alert_daemon.load_config()
    ok, msg = alert_daemon.push_email(cfg, f'🌅 TSMC 核心晨報 {date}', text, html=html)
    print(f'[brief] email ok={ok} msg={msg}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
