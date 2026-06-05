#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Stock Terminal v3.8 — ETF 共識報表 HTML 產生器
# ------------------------------------------------------------
# 對齊朋友版「前十台股主動式 ETF 每日 Delta」格式：
#   今日總覽 / 新增股總覽 / Executive Summary / 持股改變觀點 /
#   跨 ETF 共識新增 / 各 ETF 明細(新增·刪除·張數加減碼·分析)
# 輸入：/etf-delta 回傳的 dict；輸出：(subject, html)
# 供 etf_report_email.py(每日)與 server _etf_report_email(即時)共用。
# ============================================================


def _n(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return str(v)


# 高優先門檻：目前排名 <= 此值視為核心持股（可調）
HIGH_PRIORITY_RANK = 15


def _rank_key(x):
    try:
        return int(x.get('rank'))
    except Exception:
        return 99999


def _priority(rank):
    try:
        r = int(rank)
    except Exception:
        return '—'
    if r <= HIGH_PRIORITY_RANK:
        return '高優先'
    if r <= 30:
        return '中優先'
    return '低優先'


def _layout(weight):
    w = weight or 0
    if w < 1:
        return '試單布局'
    if w < 3:
        return '中型布局'
    return '核心布局'


def _signal(nnew, nrm, nchg):
    if nnew > 0 or nrm > 0:
        return '高'
    if nchg > 0:
        return '中'
    return '低'


def _consensus_map(etfs):
    """code -> 新增該股的 ETF 數，用於『共識』欄"""
    m = {}
    for e in etfs:
        for n in (e.get('new') or []):
            c = (n.get('code') or '').upper()
            m[c] = m.get(c, 0) + 1
    return m


def _top_event(e):
    """該 ETF 最重要事件一句"""
    news = e.get('new') or []
    chg = sorted(e.get('changed') or [], key=lambda x: abs(x.get('shares_delta') or 0), reverse=True)
    rm = e.get('removed') or []
    if news:
        n = news[0]
        return f"新增 {n.get('code')} {n.get('name','')}，排第 {n.get('rank')}、{_layout(n.get('weight'))}"
    if rm:
        r = rm[0]
        return f"刪除 {r.get('code')} {r.get('name','')}（前次 {r.get('prev_weight',0):.2f}%）"
    if chg:
        c = chg[0]
        sd = c.get('shares_delta') or 0
        act = '加碼' if sd >= 0 else '減碼'
        return f"{act} {c.get('code')} {c.get('name','')} {sd:+,} 股"
    return '今天無事件'


def _analysis(e):
    """持股改變分析（敘述）"""
    lines = []
    news = e.get('new') or []
    chg = sorted(e.get('changed') or [], key=lambda x: abs(x.get('shares_delta') or 0), reverse=True)
    if news:
        n = news[0]
        lines.append(f"新增股以 {n.get('code')} {n.get('name','')} 最值得留意，"
                     f"進場排名第 {n.get('rank')}、權重 {n.get('weight',0):.2f}%，屬於{_layout(n.get('weight'))}。")
    if chg:
        c = chg[0]
        sd = c.get('shares_delta') or 0
        act = '加碼' if sd >= 0 else '減碼'
        lines.append(f"張數變動最大的是 {c.get('code')} {c.get('name','')}，本次{act} {abs(sd):,} 股，"
                     f"權重由 {c.get('prev_weight',0):.2f}% 變為 {c.get('curr_weight',0):.2f}%。")
        adds = sum(1 for x in chg if (x.get('shares_delta') or 0) > 0)
        if adds >= max(1, len(chg) // 2 + 1):
            lines.append("前十大持股以加碼為主，代表經理人對核心部位的集中度正在上升。")
    if not news and not chg and not (e.get('removed')):
        lines.append("今天沒有觀察到新增、刪除或張數加減碼，整體配置延續前一版。")
    return lines


# ---- HTML helpers ----------------------------------------
_TH = 'padding:5px 8px;background:#1e293b;color:#94a3b8;font-size:11px;text-align:left;border-bottom:1px solid #334155'
_TD = 'padding:5px 8px;border-bottom:1px solid #1e293b;font-size:11px'


def _table(headers, rows, empty='今天沒有資料。'):
    if not rows:
        return f'<div style="padding:8px;color:#64748b;font-size:11px">{empty}</div>'
    h = '<table style="width:100%;border-collapse:collapse;margin:4px 0 10px">'
    h += '<tr>' + ''.join(f'<th style="{_TH}">{x}</th>' for x in headers) + '</tr>'
    for r in rows:
        h += '<tr>' + ''.join(f'<td style="{_TD}">{c}</td>' for c in r) + '</tr>'
    return h + '</table>'


def _chg(val, pct=False):
    """有號上色：正紅負綠（台股慣例）"""
    try:
        v = float(val)
    except Exception:
        return str(val)
    col = '#ef4444' if v > 0 else ('#22c55e' if v < 0 else '#94a3b8')
    s = (f"{v:+,.2f}%" if pct else f"{v:+,.0f}")
    return f'<span style="color:{col};font-weight:700">{s}</span>'


def build_report_html(delta, mode='full'):
    etfs = delta.get('etfs') or []
    date = delta.get('date') or ''
    prev = delta.get('prev_date') or ''
    cons = _consensus_map(etfs)

    tot_new = sum(len(e.get('new') or []) for e in etfs)
    tot_rm = sum(len(e.get('removed') or []) for e in etfs)
    tot_chg = sum(len(e.get('changed') or []) for e in etfs)

    css_wrap = 'font-family:-apple-system,"Microsoft JhengHei",sans-serif;background:#0b1220;color:#e2e8f0;padding:16px;max-width:860px;margin:auto'

    # ── 精簡版（投資判斷導向）：ETF 總綱 Index + 高優先加碼/減碼 + 新增 ──
    if mode == 'lite':
        def crow(x):
            sd = x.get('shares_delta') or 0
            return [x.get('rank'), x.get('code'), x.get('name', ''), x.get('_etf'),
                    _n(x.get('prev_shares')), _n(x.get('curr_shares')), _chg(sd), _chg(x.get('delta'), True)]
        CHEAD = ['排名', '代號', '名稱', 'ETF', '前次股數', '目前股數', '股數變化', '權重變化']
        allc = []
        for e in etfs:
            for x in (e.get('changed') or []):
                y = dict(x); y['_etf'] = e.get('name', e.get('code')); allc.append(y)
        hp = [x for x in allc if _rank_key(x) <= HIGH_PRIORITY_RANK]   # 高優先 = 核心持股
        add = sorted([x for x in hp if (x.get('shares_delta') or 0) > 0], key=lambda x: x.get('shares_delta') or 0, reverse=True)[:20]
        red = sorted([x for x in hp if (x.get('shares_delta') or 0) < 0], key=lambda x: x.get('shares_delta') or 0)[:20]
        add.sort(key=_rank_key); red.sort(key=_rank_key)

        L = [f'<div style="{css_wrap}">',
             f'<h2 style="color:#fbbf24;margin:0 0 4px">主動 ETF 重點摘要（精簡）</h2>',
             f'<div style="color:#94a3b8;font-size:12px;margin-bottom:12px">報告日 {date}｜觀測 {len(etfs)} 檔｜新增 {tot_new}／刪除 {tot_rm}／加減碼 {tot_chg}</div>']
        # ETF 總綱 Index
        L.append('<h3 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">ETF 總綱 Index</h3>')
        irows = []
        for e in etfs:
            nn, nr, nc = len(e.get('new') or []), len(e.get('removed') or []), len(e.get('changed') or [])
            irows.append([e.get('code'), e.get('name', ''), nn, nr, nc, _signal(nn, nr, nc), _top_event(e)])
        L.append(_table(['代號', 'ETF', '新增', '刪除', '加減碼', '訊號', '最重要事件'], irows))
        # 跨 ETF 共識（≥2 檔同方向）：買=新增或加碼、賣=刪除或減碼
        buy, sell = {}, {}
        for e in etfs:
            et = e.get('name', e.get('code'))
            for n in (e.get('new') or []):
                buy.setdefault((n.get('code') or '').upper(), {'name': n.get('name', ''), 'etfs': set()})['etfs'].add(et)
            for x in (e.get('changed') or []):
                sd = x.get('shares_delta') or 0
                (buy if sd > 0 else sell).setdefault((x.get('code') or '').upper(), {'name': x.get('name', ''), 'etfs': set()})['etfs'].add(et)
            for r in (e.get('removed') or []):
                sell.setdefault((r.get('code') or '').upper(), {'name': r.get('name', ''), 'etfs': set()})['etfs'].add(et)
        mkcon = lambda d: sorted([(k, v) for k, v in d.items() if len(v['etfs']) >= 2], key=lambda kv: -len(kv[1]['etfs']))
        buyc, sellc = mkcon(buy), mkcon(sell)
        L.append('<h3 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">跨 ETF 共識（≥2 檔同方向）</h3>')
        brows = [[k, v['name'], f"{len(v['etfs'])} 檔", '、'.join(sorted(v['etfs']))] for k, v in buyc]
        srows = [[k, v['name'], f"{len(v['etfs'])} 檔", '、'.join(sorted(v['etfs']))] for k, v in sellc]
        L.append('<div style="color:#ef4444;font-size:11px;margin-top:6px">🔺 買盤共識（新增/加碼）</div>')
        L.append(_table(['代號', '名稱', '共識', 'ETF'], brows, '無多檔同步買進。'))
        L.append('<div style="color:#22c55e;font-size:11px;margin-top:6px">🔻 賣盤共識（刪除/減碼）</div>')
        L.append(_table(['代號', '名稱', '共識', 'ETF'], srows, '無多檔同步賣出。'))
        # 高優先加碼/減碼（核心持股，最具投資意義）
        L.append(f'<h3 style="color:#ef4444;border-bottom:1px solid #334155;padding-bottom:4px">🔺 高優先加碼（核心持股排名≤{HIGH_PRIORITY_RANK}）</h3>')
        L.append(_table(CHEAD, [crow(x) for x in add], '無高優先加碼。'))
        L.append(f'<h3 style="color:#22c55e;border-bottom:1px solid #334155;padding-bottom:4px">🔻 高優先減碼（核心持股排名≤{HIGH_PRIORITY_RANK}）</h3>')
        L.append(_table(CHEAD, [crow(x) for x in red], '無高優先減碼。'))
        # 新增股（早期布局訊號）
        nrows = []
        for e in etfs:
            for n in sorted(e.get('new') or [], key=_rank_key):
                c = (n.get('code') or '').upper()
                con = f"{cons.get(c,1)} 檔" if cons.get(c, 1) > 1 else '單一'
                nrows.append([n.get('rank'), n.get('code'), n.get('name', ''), e.get('name', e.get('code')),
                              f"{n.get('weight',0):.2f}%", _n(n.get('shares')), _layout(n.get('weight')), con])
        L.append('<h3 style="color:#60a5fa;border-bottom:1px solid #334155;padding-bottom:4px">➕ 新增股（早期布局訊號）</h3>')
        L.append(_table(['排名', '代號', '名稱', 'ETF', '權重', '股數', '布局判讀', '共識'], nrows, '今日無新增股。'))
        L.append('<div style="margin-top:14px;color:#64748b;font-size:10px">⚠ 僅反映持股異動，非投資建議。</div></div>')
        return f'主動 ETF 重點摘要 {date}（加碼{len(add)}／減碼{len(red)}／新增{tot_new}）', ''.join(L)


    css_wrap = 'font-family:-apple-system,"Microsoft JhengHei",sans-serif;background:#0b1220;color:#e2e8f0;padding:16px;max-width:860px;margin:auto'
    H = [f'<div style="{css_wrap}">']
    H.append(f'<h2 style="color:#fbbf24;margin:0 0 4px">前十台股主動式 ETF 每日 Delta</h2>')
    H.append(f'<div style="color:#94a3b8;font-size:12px;margin-bottom:14px">報告日 {date}｜前次比對 {prev}｜觀測池 {len(etfs)} 檔｜以新增/刪除/張數加減碼為主、權重為輔</div>')

    # 1. 今日總覽
    def big(num, lbl, col):
        return (f'<td style="text-align:center;padding:10px"><div style="font-size:30px;font-weight:800;color:{col}">{num}</div>'
                f'<div style="font-size:11px;color:#94a3b8">{lbl}</div></td>')
    H.append('<h3 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">1. 今日總覽</h3>')
    H.append('<table style="width:100%;border-collapse:collapse;margin-bottom:12px"><tr>'
             + big(tot_new, '新增事件數', '#22c55e') + big(tot_rm, '刪除事件數', '#ef4444')
             + big(tot_chg, '張數加減碼事件數', '#60a5fa') + '</tr></table>')

    # 投資判斷導向排序：訊號強度高(有新增/刪除/大額加減碼)的 ETF 置前
    def _sigval(e):
        nn, nr, nc = len(e.get('new') or []), len(e.get('removed') or []), len(e.get('changed') or [])
        return ({'高': 3, '中': 2, '低': 1}.get(_signal(nn, nr, nc), 0), nn + nr + nc)
    order = sorted(etfs, key=_sigval, reverse=True)

    # 2. 新增股總覽
    H.append('<h3 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">2. 新增股總覽</h3>')
    rows = []
    for e in order:
        for n in sorted(e.get('new') or [], key=_rank_key):
            c = (n.get('code') or '').upper()
            con = f"{cons.get(c,1)} 檔 ETF" if cons.get(c, 1) > 1 else '單一 ETF'
            rows.append([e.get('name', e.get('code')), n.get('rank'), n.get('code'), n.get('name', ''),
                         f"{n.get('weight',0):.2f}%", _n(n.get('shares')),
                         _priority(n.get('rank')), _layout(n.get('weight')), con])
    H.append(_table(['ETF', '排名', '代號', '股票', '權重', '股數', '優先級', '布局判讀', '共識'], rows,
                    '今天沒有新增股。'))

    # 3. Executive Summary
    H.append('<h3 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">3. Executive Summary</h3>')
    rows = []
    for e in order:
        nn, nr, nc = len(e.get('new') or []), len(e.get('removed') or []), len(e.get('changed') or [])
        rows.append([e.get('name', e.get('code')), nn, nr, nc, _signal(nn, nr, nc), _top_event(e)])
    H.append(_table(['ETF', '新增', '刪除', '加減碼', '訊號強度', '最重要事件'], rows))

    # 4. 跨 ETF 共識新增
    H.append('<h3 style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">4. 跨 ETF 共識新增</h3>')
    multi = {c: n for c, n in cons.items() if n >= 2}
    if multi:
        names = {}
        for e in etfs:
            for x in (e.get('new') or []):
                names[(x.get('code') or '').upper()] = x.get('name', '')
        crows = [[c, names.get(c, ''), f"{n} 檔同步新增"] for c, n in sorted(multi.items(), key=lambda kv: -kv[1])]
        H.append(_table(['代號', '名稱', '共識'], crows))
    else:
        H.append('<div style="padding:8px;color:#64748b;font-size:11px">今天沒有出現多檔 ETF 同步新增同一檔股票。</div>')

    # 5. 各 ETF 明細（含索引，點擊跳到該 ETF）
    H.append('<h3 id="etf-index" style="color:#e2e8f0;border-bottom:1px solid #334155;padding-bottom:4px">5. 各 ETF 明細</h3>')
    # 索引列
    idx = []
    for e in order:
        nn, nr, nc = len(e.get('new') or []), len(e.get('removed') or []), len(e.get('changed') or [])
        tag = '🟢' if nn else ('🔵' if nc else '⚪')
        idx.append(f'<a href="#etf-{e.get("code")}" style="color:#60a5fa;text-decoration:none;font-size:11px;'
                   f'display:inline-block;padding:3px 8px;margin:2px;background:#1e293b;border-radius:5px">'
                   f'{tag} {e.get("code")} {e.get("name","")}</a>')
    H.append('<div style="margin:6px 0 10px;line-height:1.9">' + ''.join(idx) + '</div>')
    for e in order:
        nn, nr, nc = len(e.get('new') or []), len(e.get('removed') or []), len(e.get('changed') or [])
        H.append(f'<div id="etf-{e.get("code")}" style="margin:14px 0 4px;font-weight:700;color:#fbbf24">{e.get("code")} {e.get("name","")}'
                 f' <span style="color:#64748b;font-weight:400;font-size:11px">總持股 {e.get("total","-")}｜新增 {nn}｜刪除 {nr}｜加減碼 {nc}</span>'
                 f' <a href="#etf-index" style="color:#475569;font-weight:400;font-size:10px;text-decoration:none">↑索引</a></div>')
        # 新增
        nrows = [[x.get('rank'), x.get('code'), x.get('name', ''), f"{x.get('weight',0):.2f}%",
                  _n(x.get('shares')), _priority(x.get('rank')), _layout(x.get('weight'))]
                 for x in sorted(e.get('new') or [], key=_rank_key)]
        if nrows:
            H.append('<div style="font-size:11px;color:#22c55e;margin-top:6px">▲ 新增持股</div>')
            H.append(_table(['排名', '代號', '名稱', '權重', '股數', '優先級', '布局判讀'], nrows))
        # 刪除
        rrows = [[x.get('rank'), x.get('code'), x.get('name', ''), f"{x.get('prev_weight',0):.2f}%",
                  _n(x.get('prev_shares'))] for x in (e.get('removed') or [])]
        if rrows:
            H.append('<div style="font-size:11px;color:#ef4444;margin-top:6px">▼ 刪除/近乎清倉</div>')
            H.append(_table(['前次排名', '代號', '名稱', '前次權重', '前次股數'], rrows))
        # 加減碼
        crows = []
        for x in sorted(e.get('changed') or [], key=_rank_key):
            sd = x.get('shares_delta') or 0
            crows.append([x.get('rank'), x.get('code'), x.get('name', ''), x.get('prev_rank', '-'),
                          _n(x.get('prev_shares')), _n(x.get('curr_shares')), _chg(sd),
                          _chg(x.get('delta'), True),
                          ('加碼' if sd >= 0 else '減碼') + ' / ' + _priority(x.get('rank'))])
        if crows:
            H.append('<div style="font-size:11px;color:#60a5fa;margin-top:6px">↔ 張數加減碼</div>')
            H.append(_table(['排名', '代號', '名稱', '前次排名', '前次股數', '目前股數', '股數變化', '權重變化', '判讀'], crows))
        # 分析
        for ln in _analysis(e):
            H.append(f'<div style="font-size:11px;color:#cbd5e1;margin:3px 0 0">• {ln}</div>')

    H.append('<div style="margin-top:18px;color:#64748b;font-size:10px;border-top:1px solid #334155;padding-top:8px">'
             '⚠ 僅反映主動 ETF 當日持股異動，非投資建議。Stock Terminal v3.8 自動產生。</div>')
    H.append('</div>')
    subject = f'前十主動 ETF Delta 報表 {date}（新增 {tot_new}／刪除 {tot_rm}／加減碼 {tot_chg}）'
    return subject, ''.join(H)


def build_report_text(delta):
    """純文字後備（不支援 HTML 的信箱）"""
    etfs = delta.get('etfs') or []
    date = delta.get('date') or ''
    out = [f'前十主動 ETF Delta {date}（觀測 {len(etfs)} 檔）', '']
    for e in etfs:
        nn = len(e.get('new') or []); nr = len(e.get('removed') or []); nc = len(e.get('changed') or [])
        out.append(f"{e.get('code')} {e.get('name','')}｜新增{nn} 刪除{nr} 加減碼{nc}｜{_top_event(e)}")
    return '\n'.join(out)
