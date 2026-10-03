"""三項證據限制的本機驗證與不可覆寫報告；不取外部來源、不變更候選。"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, date, timedelta
from pathlib import Path

import stock_signals as ss
from 個股訊號研究 import POLICY, RSI_POLICY, digest
from 台股交易參考 import references, session, trading_status

VERSION = 'st-evidence-report/v1'
METRICS = {
    'researchThrough': '研究截止日', 'mainSelection': '主情境結果', 'rsiSelection': 'RSI結果',
    'events': '前瞻事件數', 'mature5': '5日成熟結果', 'mature20': '20日成熟結果',
    'due5': '5日已到期未結算', 'due20': '20日已到期未結算',
    'fullSymbols': '完整還原檔數', 'partialSymbols': '部分還原檔數',
    'partialBars': '部分還原日線數', 'missingPrices': '當期未對齊檔數',
    'missingSessions': '已知交易日缺口數', 'sourceConflicts': '來源修訂衝突數',
}


def forward_status(path, sessions):
    """使用即時唯讀診斷；到期、缺資料與無效證據分開，不改當次留存收據。"""
    from 前瞻成熟診斷 import read_diagnostics
    return read_diagnostics(path, sessions)


def build_report(cached, inventory, observations, sources, revisions, *, now=None, errors=None):
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('回報時間須含時區')
    now = now.astimezone(ss._TZ['TW'])
    cached = cached or {}
    research = cached.get('research') or {}
    rsi = research.get('rsiRebound') or {}
    sensitivity = cached.get('priceSensitivity') or {}
    partial = sensitivity.get('partial') or {}
    today = now.date().isoformat()
    checks = []
    def check(key, label, state, detail):
        checks.append({'id': key, 'label': label, 'state': state, 'detail': detail})
    policy_ok = research.get('policy') == POLICY and rsi.get('policy') == RSI_POLICY
    check('policy', '研究協定與固定門檻', 'passed' if policy_ok else ('waiting' if not research else 'failed'),
          '沿用既有研究協定，未調整門檻。' if policy_ok else '研究尚未計算或協定與目前版本不同，須重算核對。')
    through = (cached.get('window') or {}).get('to')
    benchmark = inventory.get('benchmarkAsOf')
    check('research_freshness', '研究與本機行情截止日',
          'passed' if through and through == benchmark else 'waiting',
          '研究至 ' + str(through or '未知') + '；本機大盤至 ' + str(benchmark or '未知') + '。')
    check('future_data', '資料日期不得超前',
          'failed' if any(d and d > today for d in (through, benchmark)) else 'passed',
          '對照回報當地日期，未來日期不得作為已完成證據。')
    main = (research.get('selection') or {}).get('status', 'unknown')
    rsi_state = (rsi.get('selection') or {}).get('status', 'unknown')
    allowed = {'no_candidate', 'forward_only', 'temporal_check_failed'}
    selection_state = 'failed' if any(s not in allowed | {'unknown'} for s in (main, rsi_state)) else (
        'waiting' if 'unknown' in (main, rsi_state) else 'passed')
    check('selection', '研究結果誠實呈現', selection_state,
          '主情境：' + main + '；固定RSI：' + rsi_state + '。通過歷史門檻也僅可前瞻觀察。')
    check('ledger', '前瞻帳本結果關聯', 'failed' if observations.get('orphans') else ('passed' if observations.get('enabled') else 'waiting'),
          '無效事件關聯或非5／20日期間：' + str(observations.get('orphans', 0)) + '筆。')
    unverified = sum(h.get('unverified', 0) for h in observations.get('horizons', []))
    check('forward_evidence', '前瞻凍結證據可核實', 'failed' if unverified else ('passed' if observations.get('enabled') else 'waiting'),
          '版本或證據無效：' + str(unverified) + '個事件／期間；無效結果不計入成熟統計。')
    calendar = session(now.date())
    from stock_signals_routes import session_state
    expected = session_state('TW', benchmark, now)['expectedLastDate']
    needs_today = calendar['status'] == 'scheduled' and now.hour >= 14
    fresh = bool(benchmark and expected and benchmark == expected)
    check('market_freshness', '當期大盤資料', 'passed' if fresh else 'waiting',
          ('尚未收盤，保留上一交易日資料。' if calendar['status'] == 'scheduled' and now.hour < 14 else
           '預期至 ' + str(expected or '未知') + '；本機至 ' + str(benchmark or '未知') + '。'))
    source_missing = [r['name'] for r in sources.get('sources', []) if r.get('status') != 'completed']
    if needs_today and (sources.get('sessionDate') != today or not sources.get('sources')):
        source_missing = ['當日來源執行收據']
    research_at, source_at = cached.get('researchAsOf') or cached.get('generatedAt'), sources.get('updatedAt')
    try:
        source_newer = bool(source_at and (not research_at or datetime.fromisoformat(source_at) > datetime.fromisoformat(research_at)))
    except (ValueError, TypeError):
        source_newer = True
    check('research_source_time', '研究是否涵蓋最近來源更新', 'waiting' if source_newer else ('passed' if research_at and source_at else 'waiting'),
          '研究計算時間：' + str(research_at or '尚無') + '；最近來源更新：' + str(source_at or '尚無收據') + '。')
    check('daily_sources', '每日來源完成收據', 'waiting' if source_missing or not sources.get('sources') else 'passed',
          '待確認：' + '、'.join(source_missing) if source_missing else (
              '可用來源收據已核對。' if sources.get('sources') else '尚無來源執行收據；等待既有排程，不視為已完成。'))
    check('calendar_scope', '交易日曆涵蓋範圍', 'limited', references()['scope'])
    check('lifecycle_scope', '證券生命週期涵蓋範圍', 'limited', '已知停止交易會排除；目前參考不是完整歷史證券主檔。')
    last_run = observations.get('lastRun') or {}
    check('observation_run', '每日留存實際執行',
          'passed' if observations.get('enabled') and last_run.get('status') in ('completed', 'closed')
          and last_run.get('sessionDate') == today else 'waiting',
          '最近留存：' + str(last_run.get('sessionDate') or '尚無') + '；' + str(last_run.get('reason') or '等待正式收盤觀察。'))
    for error in errors or []:
        check('execution_error', '檢查程序失敗', 'failed', error)
    hz = {h['horizon']: h for h in observations.get('horizons', [])}
    metrics = {'researchThrough': through, 'mainSelection': main, 'rsiSelection': rsi_state,
               'events': observations.get('events', 0),
               **{prefix + str(h): hz.get(h, {}).get(key, 0) for h in (5, 20)
                  for prefix, key in [('mature', 'mature'), ('due', 'due')]},
               'fullSymbols': sensitivity.get('coveredSymbols', 0),
               'partialSymbols': partial.get('coveredSymbols', 0), 'partialBars': partial.get('coveredBars', 0),
               'missingPrices': len(inventory.get('missingPrices', [])),
               'missingSessions': len(inventory.get('missingSessions', [])),
               'sourceConflicts': revisions.get('count', 0)}
    constraints = [
        {'id': 'advantage', 'label': '研究優勢', 'state': 'unproven',
         'summary': '主情境 ' + main + '；固定RSI ' + rsi_state + '。',
         'next': '維持既定門檻；新資料到齊後重算。歷史通過也不自動提升為可交易訊號。'},
        {'id': 'forward', 'label': '前瞻結果',
         'state': 'attention' if any(h.get('due') for h in hz.values()) else 'observing',
         'summary': '已留存 ' + str(metrics['events']) + '個事件；5日成熟 ' + str(metrics['mature5']) +
                    '筆、20日成熟 ' + str(metrics['mature20']) + '筆。',
         'next': '已到期未結算時核對行情缺日；未到期繼續等待真實交易日，不回填歷史事件。'},
        {'id': 'coverage', 'label': '資料與主檔覆蓋', 'state': 'limited',
         'summary': '完整還原 ' + str(metrics['fullSymbols']) + '／' + str(sensitivity.get('totalSymbols', 0)) +
                    '檔；部分還原 ' + str(metrics['partialSymbols']) + '檔。',
         'next': '依下列缺口核對來源；歷史主檔不完整持續揭露，不將局部覆蓋當成完整證據。'},
    ]
    return {'version': VERSION, 'checkedAt': now.isoformat(), 'sessionDate': today,
            'execution': 'failed' if any(c['state'] == 'failed' for c in checks) else 'completed',
            'checks': checks, 'constraints': constraints, 'metrics': metrics,
            'observations': observations, 'coverage': inventory,
            'missingAdjustedSymbols': sensitivity.get('missingSymbols', []), 'pendingSources': source_missing,
            'provenance': {'researchGeneratedAt': cached.get('generatedAt'),
                           'policyDigest': research.get('policyDigest'), 'rsiPolicyDigest': rsi.get('policyDigest'),
                           'statisticsVersion': cached.get('statisticsVersion'),
                           'referencesVerifiedAt': references()['verifiedAt']},
            'externalCalls': 0, 'candidatePromotion': False}


def collect_inventory(conn, now):
    import datastore
    import signal_stats_pool as pool
    benchmark = ss.normalize_bars(datastore.get_bars_bulk(['^TWII'], connection=conn).get('^TWII') or [])
    days = sorted({b['date'] for b in benchmark if ss.complete_bar(b) and session(b['date'])['status'] != 'closed'
                   and (b['date'] < now.date().isoformat() or (b['date'] == now.date().isoformat() and now.hour >= 14))})
    latest = days[-1] if days else None
    rows = conn.execute("SELECT symbol,max(ts) FROM bars WHERE market='TW' GROUP BY symbol").fetchall()
    missing, excluded = [], []
    for symbol, stamp in rows:
        if not pool._TICKER_RE['TW'].fullmatch(symbol):
            continue
        inactive = trading_status(symbol, now.date().isoformat())
        if inactive:
            excluded.append({'symbol': symbol, 'reason': inactive['label']})
        elif latest and ss.bar_date(stamp) != latest:
            missing.append({'symbol': symbol, 'asOf': ss.bar_date(stamp), 'expected': latest})
    gaps = []
    if days:
        known = set(days)
        day, end = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        while day <= end:
            if session(day)['status'] == 'scheduled' and day.isoformat() not in known:
                gaps.append(day.isoformat())
            day += timedelta(days=1)
    return {'benchmarkAsOf': latest, 'missingPrices': missing, 'excludedInstruments': excluded,
            'missingSessions': gaps, 'calendarYear': references()['calendar']['year']}, days


def save_report(path, report, *, nightly_day=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # 僅以可比較的證據去重；每次檢查時間另外保存，不覆寫既有報告。
    stable = {k: report.get(k) for k in ('version', 'sessionDate', 'scheduledDay', 'execution', 'checks', 'constraints',
                                    'metrics', 'observations', 'coverage', 'missingAdjustedSymbols', 'pendingSources', 'provenance')}
    if isinstance(stable.get('observations'), dict):
        stable['observations'] = {k: v for k, v in stable['observations'].items() if k != 'checkedAt'}
    fingerprint = digest(stable)
    with closing(sqlite3.connect(path, timeout=30)) as conn, conn:
        conn.executescript('''CREATE TABLE IF NOT EXISTS evidence_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,day TEXT,digest TEXT,payload TEXT);
          CREATE TABLE IF NOT EXISTS evidence_report_meta(key TEXT PRIMARY KEY,value TEXT);''')
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT payload,digest,id FROM evidence_reports ORDER BY id DESC LIMIT 1').fetchone()
        before = json.loads(previous[0]) if previous else {}
        report = {**report, 'changes': [{'label': label, 'before': before.get('metrics', {}).get(key), 'after': value}
                  for key, label in METRICS.items() for value in [report['metrics'].get(key)]
                  if not previous or before.get('metrics', {}).get(key) != value],
                  'comparisonNote': '指標變化是資料與研究狀態差異，不等於投資績效改善；資料期間及協定須一併核對。'}
        if not previous or previous[1] != fingerprint:
            report_id = conn.execute('INSERT INTO evidence_reports(day,digest,payload) VALUES(?,?,?)',
                         (report['sessionDate'], fingerprint, json.dumps(report, ensure_ascii=False, allow_nan=False))).lastrowid
        else:
            report_id = previous[2]
        conn.execute('INSERT OR REPLACE INTO evidence_report_meta VALUES(?,?)', ('lastCheckedAt', report['checkedAt']))
        if nightly_day:
            conn.execute('INSERT OR REPLACE INTO evidence_report_meta VALUES(?,?)', ('nightlyDay', nightly_day))
    return report_id


def read_reports(path, before=None):
    if not Path(path).is_file():
        return {'latest': None, 'history': [], 'nextBefore': None, 'total': 0, 'lastCheckedAt': None, 'nightlyDay': None}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        meta = dict(conn.execute('SELECT key,value FROM evidence_report_meta'))
        latest = conn.execute('SELECT id,payload FROM evidence_reports ORDER BY id DESC LIMIT 1').fetchone()
        total = conn.execute('SELECT count(*) FROM evidence_reports').fetchone()[0]
        rows = conn.execute('SELECT id,payload FROM evidence_reports WHERE id<? ORDER BY id DESC LIMIT 21',
                            (before if before is not None else 9223372036854775807,)).fetchall()
    def decoded(row):
        return {'id': row[0], **json.loads(row[1])}
    history = list(map(decoded, rows[:20]))
    return {'latest': decoded(latest) if latest else None, 'history': history, 'total': total,
            'nextBefore': rows[19][0] if len(rows) > 20 else None, **meta}
