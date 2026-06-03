#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Stock Terminal v3.8 — ETF 共識報表每日 Email
# ------------------------------------------------------------
# 抓本機 server /etf-delta，彙總各主動 ETF 的新增/移除/加減碼，
# 算淨分數(新增/移除/加碼/減碼 皆 x2)，找潛在上漲/下跌標的，
# 用 alert_daemon 已設定好的 Email 寄出。
# 需要：server.py 跑著於 :18432、alert_config.json 設好 email。
# 用法： python etf_report_email.py
# 排程：install_etf_report_scheduler.bat（每交易日 18:30）
# ============================================================
import json, urllib.request, sys
from datetime import datetime

PORT = 18432
try:
    import alert_daemon
except Exception as e:
    print('[etf-report] alert_daemon import failed:', e); sys.exit(2)


def fetch_delta():
    url = f'http://localhost:{PORT}/etf-delta'
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def build_report(delta):
    etfs = delta.get('etfs') or []
    agg = {}

    def get(code, name):
        k = (code or '').upper()
        if k not in agg:
            agg[k] = {'code': code, 'name': name or '', 'add': [], 'inc': [], 'rm': [], 'dec': []}
        if name and not agg[k]['name']:
            agg[k]['name'] = name
        return agg[k]

    for e in etfs:
        etf = e.get('code')
        for n in (e.get('new') or []):
            get(n.get('code'), n.get('name'))['add'].append(etf)
        for c in (e.get('changed') or []):
            s = get(c.get('code'), c.get('name'))
            (s['inc'] if (c.get('delta') or 0) >= 0 else s['dec']).append(etf)
        for r in (e.get('removed') or []):
            get(r.get('code'), r.get('name'))['rm'].append(etf)

    rows = []
    for s in agg.values():
        bull = (len(s['add']) + len(s['inc'])) * 2
        bear = (len(s['rm']) + len(s['dec'])) * 2
        s['net'] = bull - bear
        rows.append(s)
    rows.sort(key=lambda s: s['net'], reverse=True)
    return rows, len(etfs)


def to_text(rows, etf_count, date):
    def line(s):
        return (f"{'+' if s['net'] >= 0 else ''}{s['net']}\t{s['code']} {s['name']}\t"
                f"(新增{len(s['add'])}/加碼{len(s['inc'])}/移除{len(s['rm'])}/減碼{len(s['dec'])})")
    up = [s for s in rows if s['net'] > 0][:20]
    dn = [s for s in rows if s['net'] < 0]
    dn = sorted(dn, key=lambda s: s['net'])[:20]
    return (f"ETF 操盤手共識報表 {date}\n彙總 {etf_count} 檔主動 ETF 當日新增/移除/加減碼\n\n"
            f"=== 潛在上漲（淨分數前 20）===\n" + ('\n'.join(map(line, up)) or '無') + "\n\n"
            f"=== 潛在下跌（淨分數後 20）===\n" + ('\n'.join(map(line, dn)) or '無') + "\n\n"
            "⚠ 僅反映主動 ETF 當日持股異動，非投資建議。")


def main():
    try:
        delta = fetch_delta()
    except Exception as e:
        print('[etf-report] fetch /etf-delta failed (server running?):', e); return 1
    if delta.get('error'):
        print('[etf-report] delta error:', delta.get('error')); return 1
    rows, n = build_report(delta)
    date = delta.get('date') or datetime.now().strftime('%Y-%m-%d')
    text = to_text(rows, n, date)
    cfg = alert_daemon.load_config()
    ok, msg = alert_daemon.push_email(cfg, f'ETF 共識報表 {date}', text)
    print(f'[etf-report] email ok={ok} msg={msg}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
