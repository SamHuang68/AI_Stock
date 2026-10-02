#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stock Terminal 離線研究原型：唯讀行情、固定策略、獨立損益核對。"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from datetime import date, datetime, timezone, timedelta

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UPSTREAM = 'eea03f1a50d034fff778a381bc2a91e61eaf1dd0'
TPE = timezone(timedelta(hours=8))
AXIS_FAST = [10, 15, 20, 25, 30]
AXIS_SLOW = [40, 50, 60, 70, 80]


class InputValidationError(ValueError):
    def __init__(self, message, issues):
        super().__init__(message)
        self.issues = issues


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding='utf-8')


def offline_guard(event, args):
    # 此限制是程式防誤觸措施，平台沙箱仍是權限邊界。
    if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'socket.sendto', 'socket.bind', 'subprocess.Popen', 'os.system'}:
        raise PermissionError('離線研究禁止網路連線及啟動外部程序。')


def load_libraries(cache):
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['MPLCONFIGDIR'] = str(cache)
    os.environ['MPLBACKEND'] = 'Agg'
    sys.dont_write_bytecode = True
    source = json.loads((HERE / '上游來源.json').read_text(encoding='utf-8-sig'))
    if source['commit'] != UPSTREAM:
        raise ValueError('上游版本與核准的固定版本不一致。')
    vendor = HERE / '第三方' / 'blave'
    for item in source['files']:
        if digest(vendor / item['path']) != item['sha256']:
            raise ValueError('上游檔案雜湊不一致：' + item['path'])
    sys.path.insert(0, str(vendor))
    global np, pd
    import numpy as np
    import pandas as pd
    from lib import analysis, param_scan, walk_forward, validation
    return analysis, param_scan, walk_forward, validation


def validate_frame(frame):
    if len(frame) < 2 or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError('日線至少需要兩筆，日期必須唯一且遞增。')
    vals = frame[['Open', 'High', 'Low', 'Close', 'Volume']].to_numpy(float)
    if not np.isfinite(vals).all() or (vals[:, :4] <= 0).any() or (vals[:, 4] < 0).any():
        raise ValueError('日線含缺值、非有限數或不合法價格／成交量。')
    if (vals[:, 4] == 0).any():
        issues = [{'date': str(day.date()), 'code': 'zero_volume'}
                  for day in frame.index[vals[:, 4] == 0]]
        raise InputValidationError('離線研究只支援可成交的連續日線；零成交量須另行核對，不模擬停牌成交。', issues)
    if ((frame.High < frame[['Open', 'Close', 'Low']].max(axis=1)) |
            (frame.Low > frame[['Open', 'Close', 'High']].min(axis=1))).any():
        raise ValueError('日線最高／最低價與開收盤不一致。')


def snapshot_database(database, symbol, cutoff, out):
    if date.fromisoformat(cutoff) >= datetime.now(TPE).date():
        raise ValueError('研究截止日必須早於今天，避免納入尚未完成的日線。')
    database = Path(database).resolve(strict=True)
    # 不 import datastore：它的開啟流程會建表及切換 WAL。
    with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        rows = conn.execute('SELECT ts,open,high,low,close,volume FROM bars '
                            'WHERE market=? AND symbol=? ORDER BY ts', ('TW', symbol)).fetchall()
    selected = []
    for ts, op, hi, lo, cl, vol in rows:
        day = datetime.fromtimestamp(ts, TPE).date().isoformat()
        if day <= cutoff:
            selected.append({'日期': day, '時間戳': ts, '開盤': op, '最高': hi,
                             '最低': lo, '收盤': cl, '成交量': vol})
    if len(selected) < 400:
        raise ValueError('本機完整日線不足 400 筆，無法完成這份研究；不會自動連網回補。')
    frame = pd.DataFrame(selected).rename(columns={'開盤': 'Open', '最高': 'High',
        '最低': 'Low', '收盤': 'Close', '成交量': 'Volume'})
    frame.index = pd.to_datetime(frame.pop('日期'))
    frame = frame[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    validate_frame(frame)
    content = {'標的': symbol, '市場': 'TW', '資料庫': str(database), '查詢截止日': cutoff,
        '擷取時間': datetime.now(TPE).isoformat(), '來源': 'ST 本機日線庫；未逐列保存供應商',
        '價格基礎': '還原方式未經資料契約確認；不含股息現金流',
        '歷史可得性': '目前快照，沒有歷史逐日發布版本；不能當成完整時點資料', '日線': selected}
    path = out / '輸入快照.json'
    write_json(path, content)
    return frame, content, digest(path)


def replay_snapshot(path, out):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    content = json.loads(raw)
    rows = content['日線']
    frame = pd.DataFrame(rows).rename(columns={'開盤': 'Open', '最高': 'High',
        '最低': 'Low', '收盤': 'Close', '成交量': 'Volume'})
    frame.index = pd.to_datetime(frame.pop('日期'))
    frame = frame[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    validate_frame(frame)
    if len(frame) < 400 or str(frame.index[-1].date()) > content['查詢截止日']:
        raise ValueError('快照資料不足或超出快照的查詢截止日。')
    (out / '輸入快照.json').write_bytes(raw)
    return frame, content, digest(path)


def signals(frame, fast=20, slow=60):
    """收盤黃金交叉持有，死亡交叉退出；與既有策略條件器相同的均線條件。"""
    if not 1 <= int(fast) < int(slow):
        raise ValueError('短均線必須小於長均線。')
    short = frame.Close.rolling(int(fast)).mean()
    long = frame.Close.rolling(int(slow)).mean()
    return (short > long).astype(float)


def exact_pnl(close, opening, current, previous, at_close, buy_cost, sell_cost):
    """僅支援全額做多／空手、隔日開盤；使用現金與持股等價的複利損益。"""
    cl, op, cur, prev = [np.asarray(x, dtype=float) for x in (close, opening, current, previous)]
    if cl.ndim != 1 or not (cl.shape == op.shape == cur.shape == prev.shape) or not len(cl):
        raise ValueError('研究損益僅接受等長的一維資料。')
    if np.asarray(at_close).any() or not (np.isin(cur, [0., 1.]).all() and np.isin(prev, [0., 1.]).all()):
        raise ValueError('研究原型只支援隔日開盤、無槓桿做多／空手。')
    if not (0 <= buy_cost < 0.1 and 0 <= sell_cost < 0.1):
        raise ValueError('單邊成本必須介於 0 與 10% 之間。')
    prev_close = np.r_[cl[0], cl[:-1]]
    overnight = op / prev_close - 1
    entry = (cur == 1) & (prev == 0)
    leave = (cur == 0) & (prev == 1)
    hold = (cur == 1) & (prev == 1)
    ret = np.zeros(len(cl))
    ret[entry] = cl[entry] / (op[entry] * (1 + buy_cost)) - 1
    ret[leave] = op[leave] * (1 - sell_cost) / prev_close[leave] - 1
    ret[hold] = cl[hold] / prev_close[hold] - 1
    cost = np.zeros(len(cl))
    cost[entry] = buy_cost / (1 + buy_cost)
    cost[leave] = op[leave] / prev_close[leave] * sell_cost
    return ret, overnight, cur - prev, cost


def corrected_stats(returns, index):
    r = np.asarray(returns, dtype=float)
    if not len(r) or not np.isfinite(r).all() or (r <= -1).any():
        raise ValueError('損益序列無效，不能產生績效。')
    days = max((index[-1] - index[0]).days, 1)
    ppy = len(r) * 365.25 / days
    sd = r.std(ddof=1) if len(r) > 1 else 0
    sharpe = float(r.mean() / sd * math.sqrt(ppy)) if sd > 0 else 0.
    down = np.minimum(r, 0)
    downside = float(np.sqrt(np.mean(down ** 2)))
    sortino = float(r.mean() / downside * math.sqrt(ppy)) if downside > 0 else 0.
    loss = float(-r[r < 0].sum())
    omega = float(r[r > 0].sum() / loss) if loss > 0 else float('inf')
    eq = np.r_[1., np.cumprod(1 + r)]
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    annual = float(eq[-1] ** (365.25 / days) - 1)
    return sharpe, sortino, omega, mdd, annual


def weights(position):
    p = np.asarray(position, dtype=float)
    return np.r_[0., p[:-1]], np.r_[0., 0., p[:-2]][:len(p)]


def cash_ledger(frame, position, buy_cost, sell_cost):
    """獨立以現金／股數逐日估值，與向量損益交叉核對；最後持股按收盤估值。"""
    cash, shares, last_value = 1., 0., 1.
    rows, daily, trades = [], [], []
    entry = None
    for i, (day, bar) in enumerate(frame.iterrows()):
        target = position[i - 1] if i else 0.
        action = '持有' if shares else '空手'
        cost_amount = 0.
        if target and not shares:
            initial = cash
            shares = cash / (bar.Open * (1 + buy_cost))
            cost_amount = shares * bar.Open * buy_cost
            cash = 0.
            action = '買進'
            entry = {'進場日期': str(day.date()), '進場價': float(bar.Open), '進場前權益': initial}
        elif not target and shares:
            cost_amount = shares * bar.Open * sell_cost
            cash = shares * bar.Open - cost_amount
            shares = 0.
            action = '賣出'
            trades.append({**entry, '出場日期': str(day.date()), '出場價': float(bar.Open),
                           '淨報酬百分比': (cash / entry['進場前權益'] - 1) * 100})
            entry = None
        value = cash + shares * bar.Close
        daily.append(value / last_value - 1)
        rows.append({'日期': str(day.date()), '動作': action, '開盤': float(bar.Open),
                     '收盤': float(bar.Close), '現金': cash, '股數': shares,
                     '成本金額': cost_amount, '權益': value, '日報酬': daily[-1]})
        last_value = value
    return np.asarray(daily), rows, trades, entry


def metrics(ret, index):
    sharpe, _, _, mdd, annual = corrected_stats(ret, index)
    return {'累積報酬百分比': float((np.prod(1 + ret) - 1) * 100),
            '年化報酬百分比': annual * 100, '最大回撤百分比': mdd * 100, '年化夏普': sharpe}


def causal_check(frame):
    checks = 0
    for fast in AXIS_FAST:
        for slow in AXIS_SLOW:
            full = signals(frame, fast, slow)
            for cut in sorted({slow + 3, len(frame) // 2, len(frame) - 1}):
                if not np.array_equal(full.iloc[:cut], signals(frame.iloc[:cut], fast, slow)):
                    raise AssertionError('截短資料後歷史訊號改變，存在未來資料洩漏。')
                checks += 1
    return checks


def mcpt_diagnostic(validation, frame, position, cost):
    actual, pvalue, dist = validation.mcpt(frame.Close, position, n=2000,
        fee=cost, target_vol=1, max_lev=1, vol_window=1,
        periods_per_year=252, rng=np.random.default_rng(20260927))
    try:
        validation.mcpt_stats_fields(actual, pvalue, dist)
    except ValueError:
        return {'p值': None, '次數': len(dist), '種子': 20260927,
                '狀態': '無有效檢驗：零交易、報酬無變異或置換分布無效'}
    return {'p值': float(pvalue), '次數': len(dist), '種子': 20260927, '狀態': '附加診斷可用'}


def csv_write(path, rows):
    if not rows:
        Path(path).write_text('狀態\n無完成交易\n', encoding='utf-8-sig')
        return
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def core_expected(frame, position, buy_cost, sell_cost):
    """以獨立現金帳本對照 ST 4 的隔日開盤、相同成本及每日權益。"""
    _, ledger, completed, holding = cash_ledger(frame, position, buy_cost, sell_cost)
    dates = {str(day.date()): index for index, day in enumerate(frame.index)}
    equities = [row['權益'] for row in ledger]
    peak, drawdown = 1., 0.
    for equity in equities:
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    return {
        '交易': [{'entryBar': dates[row['進場日期']], 'exitBar': dates[row['出場日期']],
                  'entry': row['進場價'], 'exit': row['出場價'], 'ret': row['淨報酬百分比'] / 100}
                 for row in completed],
        '每日權益': equities, '未平倉': holding is not None, '最大回撤百分比': drawdown * 100,
        '成本基點': {'entryFeeBps': buy_cost * 10000, 'exitFeeBps': sell_cost * 10000, 'slippageBps': 0},
    }


def report_html(report, out):
    esc = html.escape
    def table(rows):
        if not rows:
            return '<p>沒有資料。</p>'
        return '<table><thead><tr>' + ''.join('<th>' + esc(str(k)) + '</th>' for k in rows[0]) + '</tr></thead><tbody>' + ''.join(
            '<tr>' + ''.join('<td>' + esc(f'{v:.4f}' if isinstance(v, float) else str(v)) + '</td>' for v in row.values()) + '</tr>' for row in rows) + '</tbody></table>'
    wf = report['樣本外驗證']
    data = report['資料']
    pvalue = report['置換檢驗']['p值']
    ptext = f'{pvalue:.4f}' if pvalue is not None else '無有效檢驗'
    comparison = [{'情境': k, **v} for k, v in report['績效比較'].items()]
    grid = report['參數掃描']
    content = f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:">
<title>Stock Terminal 離線策略驗證</title><style>
body{{font:16px/1.65 "Microsoft JhengHei",sans-serif;background:#f1f5f9;color:#182c40;margin:0}}main{{max-width:1080px;margin:auto;padding:32px 24px}}h1{{font-size:30px;margin:8px 0}}h2{{font-size:22px;margin-top:32px}}.tag{{color:#19658c;font-weight:bold}}.notice{{background:#fff4d8;border-left:5px solid #c88b20;padding:16px 20px}}.card{{background:white;padding:20px;border-radius:12px;margin-top:16px}}table{{border-collapse:collapse;min-width:620px;width:100%;font-size:14px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #dbe3ed}}th{{background:#e8f0f6}}.scroll{{overflow:auto}}code{{overflow-wrap:anywhere}}a{{color:#075e9b}}small{{color:#526477}}@media(max-width:600px){{main{{padding:18px 12px}}h1{{font-size:24px}}}}
</style><main><div class="tag">研究原型 · 本機離線 · 無自動交易</div><h1>策略有沒有經得起驗證？</h1>
<p>{esc(data['標的'])}｜20／60 日均線交叉｜{esc(data['起日'])} 至 {esc(data['迄日'])}｜{data['筆數']} 筆日線｜非即時行情</p>
<div class="notice"><strong>研究可重現；尚不能升級為決策依據。</strong><br>{esc('；'.join(report['限制']))}</div>
<section class="card"><h2>你可以怎麼用這份報告</h2><p>比較成本與成交時間對策略的影響，觀察參數稍改是否仍成立，再看後續樣本外表現。這些結果供人工研究，沒有券商連線、下單或持倉同步功能。</p>
<p>收盤計算訊號，下一交易日開盤模擬成交；無槓桿、只做多或空手、允許分數股。買進總成本假設 {report['成本']['買進基點']} 基點、賣出 {report['成本']['賣出基點']} 基點，包含費用與滑價壓力，並非你的已核實費率。最後未平倉部位以收盤估值。</p></section>
<h2>固定參數績效與成本敏感度</h2><div class="card scroll">{table(comparison)}</div>
<p>上表均為目前資料快照的歷史研究，沒有股息現金流。整段資料績效不得視為樣本外績效。買進持有比較也使用相同起點與成本。</p>
<h2>逐筆損益核對</h2><div class="card"><p>向量損益與獨立現金／股數帳本逐日比對：最大日報酬誤差 {report['核對']['最大日報酬誤差']:.3g}；完成交易 {report['核對']['完成交易數']} 筆；期末持股：{report['核對']['期末持股']}。</p>
<p>ST 4 JavaScript 隔日開盤、相同成本的逐筆交易／每日權益／回撤核對：<span id="legacy-status">尚未執行獨立核對</span>。成本視為每邊總額，對照時填入費用欄、額外滑價為零，不重複扣成本。研究夏普依實際日線密度年化，與 ST 固定 252 日口徑不同，不作夏普數值相等宣稱。</p>
<p><a href="逐日帳本.csv">逐日帳本</a> · <a href="完成交易.csv">完成交易</a> · <a href="研究結果.json">完整研究結果</a></p></div>
<h2>參數穩健性：25 組固定範圍</h2><p>固定短均線 10／15／20／25／30，長均線 40／50／60／70／80；沒有看到結果後擴大搜尋。表格數值為年化夏普，這是樣本內診斷。</p>
<div class="card scroll">{table(grid['表格'])}</div><p>上游鄰域平均方法選出的穩健區中心：{grid['中心短均線']}／{grid['中心長均線']} 日；不會自動改寫原策略。</p>
<h2>滾動樣本外驗證</h2><div class="card"><p>每次以前 {wf['訓練日數']} 個日曆日選參數，測試後續 {wf['測試日數']} 個日曆日，每個訓練窗口暖機 80 根；共 {wf['窗口數']} 個窗口、{wf['樣本外日數']} 筆日線。窗口樣本數是日線數，不能當成獨立交易樣本數。</p>
<p>樣本外期間：{wf['起日']} 至 {wf['迄日']}。以下比較使用相同期間、起始空手與相同成本。窗口換參數透過下一根開盤生效；不倒推到窗口第一根開盤。</p>
<div class="scroll">{table([{'方法': '滾動選參數', **wf['績效']}] + [{'方法': k, **v} for k,v in wf['同期間比較'].items()])}</div>
<img src="樣本外權益.png" alt="相同樣本外期間的滾動策略、固定參數與買進持有累積報酬比較" style="width:100%;height:auto;margin-top:20px">
<p>績效沿用同一條串接後的損益序列；有不足完整窗口的尾段 {wf['未涵蓋尾段日數']} 天，保留未使用。</p></div>
<details class="card"><summary>展開全部樣本外窗口</summary><div class="scroll">{table(wf['窗口'])}</div></details>
<h2>置換檢驗與升級門檻</h2><div class="card"><p>{esc(report['置換檢驗']['說明'])}</p><p>p 值：{ptext}；狀態：{esc(report['置換檢驗']['狀態'])}；置換 {report['置換檢驗']['次數']} 次，固定亂數種子。這不是未來獲利機率，也不是本報告隔日開盤損益的顯著性證明。</p>
<p>ST 研究升級門檻：<strong>{esc(report['升級門檻']['中文判定'])}</strong>。目前沒有失效監控，也未核實價格基礎與真實交易成本，不寫入 DecisionContext。</p></div>
<h2>版本與資料證據</h2><div class="card"><p>資料快照雜湊：<code>{esc(data['快照雜湊'])}</code></p><p>Blave 固定版本：<code>{UPSTREAM}</code>；只載入研究模組，Apache-2.0 授權與 NOTICE 保留於原始碼。</p><p>上游原始損益公式與轉接層差異：{esc(report['上游差異']['說明'])}</p><p><a href="輸入快照.json">固定輸入快照</a> · <a href="研究證據.json">執行環境與原始碼雜湊</a></p></div>
<p><small>本機產生：{esc(report['產生時間'])}。此頁不載入外部資源，也不連線更新行情。</small></p></main></html>'''
    (out / '研究報告.html').write_text(content, encoding='utf-8')


def run(args):
    out = Path(args.輸出).resolve()
    if out == Path(out.anchor) or not out.is_relative_to(ROOT / 'scratch'):
        raise ValueError('輸出必須位於本專案 scratch 子目錄，不能是磁碟根目錄。')
    if out.exists() and any(out.iterdir()):
        raise ValueError('輸出目錄已有檔案；請指定新的 scratch 子目錄，保留前次證據。')
    out.mkdir(parents=True, exist_ok=True)
    sys.addaudithook(offline_guard)
    analysis, scan, wf, validation = load_libraries(out / '快取')
    try:
        if args.快照:
            frame, source, snapshot_hash = replay_snapshot(args.快照, out)
            args.標的 = source['標的']
        else:
            frame, source, snapshot_hash = snapshot_database(args.資料庫, args.標的, args.截止日, out)
    except InputValidationError as exc:
        write_json(out / '輸入診斷.json', {'status': 'dataset_unusable', 'error': str(exc),
                   'issues': exc.issues, 'autoPromote': False, 'verdict': 'FAIL',
                   '說明': '保留原始資料；未刪列、補值或產生策略績效。'})
        raise
    buy, sell = args.買進基點 / 10000, args.賣出基點 / 10000
    # 保留上游原公式作差異證據；只有這個獨立研究程序內替換計算器。
    raw_pnl, raw_stats = analysis.precise_pnl, analysis.compute_stats
    analysis.precise_pnl = lambda cl, op, cur, prev, ea, fee: exact_pnl(cl, op, cur, prev, ea, buy, sell)
    analysis.compute_stats = corrected_stats
    position = signals(frame).to_numpy()
    cur, prev = weights(position)
    ret, _, _, costs = exact_pnl(frame.Close, frame.Open, cur, prev, np.zeros(len(frame)), buy, sell)
    ledger_ret, ledger, trades, open_trade = cash_ledger(frame, position, buy, sell)
    error = float(np.max(np.abs(ret - ledger_ret)))
    if error > 1e-12:
        raise AssertionError('向量損益與現金帳本不一致。')
    checks = causal_check(frame)
    write_json(out / '既有核心預期.json', {'研究方法': '隔日開盤、相同成本與每日權益',
        '訊號': position.tolist(), **core_expected(frame, position, buy, sell),
        '既有核心雜湊': digest(ROOT / 'src/screener/backtest_v3.js')})
    csv_write(out / '逐日帳本.csv', ledger)
    csv_write(out / '完成交易.csv', trades)
    scenarios = {}
    for name, b, s in [('零成本', 0., 0.), ('研究成本假設', buy, sell), ('兩倍成本壓力', buy * 2, sell * 2)]:
        r, *_ = exact_pnl(frame.Close, frame.Open, cur, prev, np.zeros(len(frame)), b, s)
        scenarios[name] = metrics(r, frame.index)
    hold_pos = np.ones(len(frame)); hold_pos[:59] = 0
    hc, hp = weights(hold_pos)
    hold_ret, *_ = exact_pnl(frame.Close, frame.Open, hc, hp, np.zeros(len(frame)), buy, sell)
    scenarios['同暖機起點買進持有'] = metrics(hold_ret, frame.index)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        grid = scan.scan_grid(frame, signals, AXIS_FAST, AXIS_SLOW, row_param='fast', col_param='slow',
                              fee=(buy + sell) / 2, valid_fn=lambda f, s: f < s, warmup=80)
        best, _, br, bc, _ = scan.find_plateau(grid, AXIS_FAST, AXIS_SLOW)
        wfpath = wf.run_walk_forward(frame, signals, AXIS_FAST, AXIS_SLOW,
            output_dir=str(out / '上游樣本外輸出'), row_param='fast', col_param='slow',
            row_kw='fast', col_kw='slow', fee=(buy + sell) / 2, lookback_days=1095,
            step_days=180, valid_fn=lambda f, s: f < s, warmup=80, current=(20, 60))
        mcpt = mcpt_diagnostic(validation, frame, position, (buy + sell) / 2)
    result = json.loads(Path(wfpath).read_text(encoding='utf-8'))
    # 上游 fee 是對稱介面參數；本次轉接實際使用不對稱買賣成本，避免檔案誤讀。
    result['研究轉接說明'] = 'fee 僅為介面佔位平均值；實際損益使用下列不對稱成本與複利公式。'
    result['實際買進成本'] = buy
    result['實際賣出成本'] = sell
    write_json(wfpath, result)
    dates = result['oos']['dates']
    oos_mask = (frame.index >= dates[0]) & (frame.index <= dates[-1])
    oos_frame = frame.loc[oos_mask]
    comparison_oos, comparison_curves = {}, {}
    for label, pos in [('固定20／60日均線', position[oos_mask]), ('買進持有', np.ones(len(oos_frame)))]:
        oc, op = weights(pos)
        rr, *_ = exact_pnl(oos_frame.Close, oos_frame.Open, oc, op, np.zeros(len(oos_frame)), buy, sell)
        comparison_oos[label] = metrics(rr, oos_frame.index)
        comparison_curves[label] = (np.cumprod(1 + rr) - 1) * 100
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = ['Microsoft JhengHei', 'DejaVu Sans']
    fig, ax = plt.subplots(figsize=(10.8, 3.8), layout='constrained')
    ax.plot(pd.to_datetime(dates), result['oos']['cum'], label='滾動選參數', color='#176e9a', linewidth=2)
    for (label, curve), color in zip(comparison_curves.items(), ['#a5652a', '#697b8e']):
        ax.plot(oos_frame.index, curve, label=label, color=color, linewidth=1.5)
    ax.set_ylabel('累積報酬（%）'); ax.set_xlabel('日期')
    ax.axhline(0, color='#8999a7', linewidth=.6); ax.grid(alpha=.15); ax.legend(loc='upper left')
    fig.savefig(out / '樣本外權益.png', dpi=150)
    plt.close(fig)
    windows = [{'窗口': r['k'], '訓練起日': r['train_start'], '訓練迄日': r['train_end'],
        '測試起日': r['test_start'], '測試迄日': r['test_end'], '短均線': r['params'][0],
        '長均線': r['params'][1], '測試報酬百分比': r['test_return'], '部位變動次數': r['trades']}
        for r in result['runs']]
    # 門檻依現有純計算器評估；不提供不存在的監控狀態。
    sys.path.insert(0, str(ROOT / 'server'))
    import promotion_gate
    gate = promotion_gate.evaluate({'oosReport': {'status': 'complete', 'reportId': snapshot_hash[:16],
        'asOf': source['擷取時間'], 'sampleSize': len(oos_frame), 'windows': result['runs']},
        'costTurnoverNotes': {'status': 'documented', 'costBps': (args.買進基點 + args.賣出基點) / 2,
        'turnoverBps': float(np.abs(cur - prev).sum() * 10000),
        'summary': '買賣不對稱成本為研究假設，未核實券商費率。'}, 'features': ['短均線', '長均線']})
    gate['中文判定'] = '不通過；保持研究用途'
    if gate['verdict'] != 'FAIL':
        raise AssertionError('缺失效監控的研究不應通過升級門檻。')
    raw, *_ = raw_pnl(frame.Close.to_numpy(), frame.Open.to_numpy(), cur, prev,
                      np.zeros(len(frame), dtype=bool), (buy + sell) / 2)
    demo, *_ = raw_pnl(np.array([100., 121.]), np.array([100., 110.]),
        np.array([1., 1.]), np.array([1., 1.]), np.zeros(2, dtype=bool), 0.)
    if not np.isclose(demo[1], .2):
        raise AssertionError('固定上游的損益診斷結果與預期不符。')
    report = {'產生時間': datetime.now(TPE).isoformat(), '用途': '人工研究；沒有自動交易功能',
        '資料': {'標的': args.標的, '起日': str(frame.index[0].date()), '迄日': str(frame.index[-1].date()),
                  '筆數': len(frame), '快照雜湊': snapshot_hash},
        '成本': {'買進基點': args.買進基點, '賣出基點': args.賣出基點, '性質': '未核實的研究壓力假設'},
        '限制': ['日線來源與還原方式未逐列記錄', '未計股息、整股限制及漲跌停成交限制',
                 '成本是假設，非本人券商費率', '目前快照不等於歷史時點資料', '無失效監控，升級門檻不通過'],
        '績效比較': scenarios,
        '核對': {'最大日報酬誤差': error, '完成交易數': len(trades), '期末持股': bool(open_trade),
                 '截短資料檢查數': checks},
        '參數掃描': {'中心短均線': int(br), '中心長均線': int(bc),
            '表格': [{'短均線／長均線': f, **{str(s): float(grid[i, j]) if np.isfinite(grid[i, j]) else '無有效交易'
                for j, s in enumerate(AXIS_SLOW)}} for i, f in enumerate(AXIS_FAST)]},
        '樣本外驗證': {'訓練日數': 1095, '測試日數': 180, '窗口數': result['n_runs'],
            '樣本外日數': len(oos_frame), '未涵蓋尾段日數': result['tail_days'], '窗口': windows,
            '起日': dates[0], '迄日': dates[-1], '同期間比較': comparison_oos,
            '績效': {'累積報酬百分比': result['oos']['cum'][-1],
                '年化報酬百分比': result['oos_stats']['Ann. Return [%]'],
                '最大回撤百分比': result['oos_stats']['Max Drawdown [%]'],
                '年化夏普': result['oos_stats']['Sharpe Ratio']}},
        '置換檢驗': {**mcpt,
            '說明': '上游 MCPT 使用固定部位與打亂的收盤至收盤報酬，採對稱平均成本、不作波動放大。其損益口徑與本報告不同，只列附加診斷；不作升級判定。'},
        '上游差異': {'說明': '上游將隔夜與日內報酬直接相加：100→110→121 得 20%，完整持股應為 21%。轉接層改用現金／股數等價複利；回撤另納入初始權益 1。上游檔案未改寫。',
            '原版同平均成本報酬百分比': float((np.prod(1 + raw) - 1) * 100)},
        '升級門檻': gate}
    write_json(out / '研究結果.json', report)
    report_html(report, out)
    evidence = {'Python': sys.version, 'NumPy': np.__version__, 'pandas': pd.__version__,
        '上游版本': UPSTREAM, '輸入快照雜湊': snapshot_hash, '研究程式雜湊': digest(__file__),
        '既有核心雜湊': digest(ROOT / 'src/screener/backtest_v3.js'),
        '網路': '已啟用程序稽核攔截；未呼叫行情或模型服務',
        '證據': {'逐日損益核對': error <= 1e-12, '截短資料檢查': checks}}
    write_json(out / '研究證據.json', evidence)
    print(json.dumps({'報告': str(out / '研究報告.html'), '資料': report['資料'],
                      '核對': report['核對'], '樣本外': report['樣本外驗證']['績效']}, ensure_ascii=False))


def parser():
    p = argparse.ArgumentParser(description='Stock Terminal 本機離線策略研究；不連線、不下單。')
    p.add_argument('--資料庫', default=str(ROOT / 'data/market.db'))
    p.add_argument('--快照', help='重播既有輸入快照，不開啟資料庫；標的與資料截止日沿用快照。')
    p.add_argument('--標的', default='2330')
    p.add_argument('--截止日', default=(datetime.now(TPE).date() - timedelta(days=1)).isoformat())
    p.add_argument('--買進基點', type=float, default=25.)
    p.add_argument('--賣出基點', type=float, default=55.)
    p.add_argument('--輸出', default=str(ROOT / 'scratch' / ('離線策略驗證-' + datetime.now(TPE).strftime('%Y%m%d-%H%M%S'))))
    return p


if __name__ == '__main__':
    try:
        run(parser().parse_args())
    except Exception as exc:
        print('離線研究未完成：' + str(exc), file=sys.stderr)
        sys.exit(1)
