"""以唯讀交易檢視每日帳本；不回填事件、不改寫價格、不晉升候選。"""
import hashlib
import json
import sqlite3
import statistics
from collections import defaultdict
from contextlib import closing
from pathlib import Path

import stock_signals as ss
import 每日個股留存 as daily
import 個股訊號研究 as research
from 個股還原研究 import COSTS, net_return, summary
import 前瞻成熟診斷 as diagnostics


def method_digest():
    root = Path(__file__).parent
    return research.digest({
        'policy': research.POLICY,
        'files': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                  for name in ('個股訊號研究.py', '個股還原研究.py', 'signal_stats_pool.py')},
    })


def _summarize(rows):
    result = summary([row['ret'] for row in rows])
    result['medianAdverse'] = statistics.median(row['adverse'] for row in rows) if result['gate'] == 'ok' else None
    result['costScenarios'] = [{'roundTripBps': cost, **summary([net_return(row['ret'], cost) for row in rows])}
                               for cost in COSTS]
    return result


# 保留既有內部呼叫名稱；價格重現驗證與唯讀診斷共用同一契約。
_outcome = diagnostics.validate_outcome


def _reference(frozen, horizon):
    """只用事件當時凍結的行情，沿用既有同股票、同大盤情境的過去對照。"""
    bars, benchmark = frozen['bars'], frozen['benchmark']
    origin = bars[-1]['date']
    if any(bar['date'] > origin for bar in benchmark):
        raise ValueError('凍結大盤含事件日之後資料')
    frame = ss.build_frame(bars)
    market = research.market_regimes(benchmark)
    positions = {day: i for i, day in enumerate(market)}
    gaps = [0]
    for i in range(1, len(bars)):
        previous, current = positions.get(bars[i - 1]['date']), positions.get(bars[i]['date'])
        gaps.append(gaps[-1] + int(previous is None or current is None or current != previous + 1))
    outcomes = ss.forward_outcomes(frame, range(64, len(bars)), horizon, 'bull', research.POLICY['entryLag'])
    aligned = [row for row in outcomes if gaps[row['t'] + research.POLICY['entryLag'] + horizon] == gaps[row['t']]]
    return research.Reference(frame, aligned, market).at(len(bars) - 1, horizon, market.get(origin, 'unknown'))


def read_report(path, historical=None, *, sessions=None, now=None):
    rules, method = daily.engine_digest(), method_digest()
    now = diagnostics._clock(now)
    historical = historical or {}
    study = historical.get('research') or {}
    verified_history = bool(study.get('rulesDigest') == rules and study.get('methodDigest') == method
                            and study.get('policyDigest') == research.digest(research.POLICY))
    history_rows = {(row['signalId'], horizon['horizon']): horizon.get('all', {})
                    for row in study.get('signals', []) for horizon in row.get('horizons', [])}
    # 所有版本各自累積；不以最新引擎重算既有事件，也不合併不同版本的樣本數。
    groups = defaultdict(lambda: defaultdict(lambda: {'observed': 0, 'mature': [], 'waiting': 0, 'unverified': 0, 'references': [], 'pendingReasons': defaultdict(int)}))
    groups[rules]
    activation = None
    event_count = 0
    enabled = Path(path).is_file()
    diagnosis = diagnostics.read_diagnostics(path, sessions, now=now) if not enabled else None
    if enabled:
        source = {'status': 'available', 'source': '呼叫端本機大盤唯讀快照'}
        if sessions is None:
            sessions, source = diagnostics.load_sessions(Path(path).parent / 'market.db', now)
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.execute('BEGIN')
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'daily_inputs', 'daily_events', 'daily_outcomes', 'daily_config'} <= tables:
                raise ValueError('每日帳本結構不完整')
            diagnosis, states = diagnostics.inspect_ledger(conn, sessions, now=now, rules=rules, benchmark_source=source)
            cfg = conn.execute("SELECT payload FROM daily_config WHERE key='activation'").fetchone()
            activation = json.loads(cfg[0]).get('activatedAt') if cfg else None
            records = conn.execute('SELECT e.id,e.signal_id,e.symbol,e.session_date,e.input_id,i.engine,'
                                   'i.payload,e.payload FROM daily_events e LEFT JOIN daily_inputs i ON i.id=e.input_id '
                                   'ORDER BY e.input_id,e.signal_id').fetchall()
            outcomes = {(row[0], row[1]): row[2] for row in conn.execute('SELECT event_id,horizon,payload FROM daily_outcomes')}
            last_input, frozen, references = None, None, {}
            for event_id, signal, symbol, day, input_id, version, compressed, event_payload in records:
                event_count += 1
                if input_id != last_input:
                    last_input, references = input_id, {}
                frozen, _ = diagnostics.validate_event(event_id, input_id, signal, symbol, day, version,
                                                       compressed, event_payload)
                for horizon in (5, 20):
                    bucket = groups[version or 'unknown'][(signal, horizon)]
                    bucket['observed'] += 1
                    state = states[(event_id, horizon)]
                    if state != 'mature':
                        bucket['pendingReasons'][state] += 1
                        if state in ('invalid_evidence', 'invalid_version'):
                            bucket['unverified'] += 1
                        else:
                            bucket['waiting'] += 1
                        continue
                    outcome = _outcome(outcomes[(event_id, horizon)], horizon, day)
                    bucket['mature'].append(outcome)
                    if version == rules and verified_history:
                        if horizon not in references:
                            try:
                                references[horizon] = _reference(frozen, horizon)
                            except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
                                references[horizon] = None
                        control = references[horizon]
                        if control:
                            bucket['references'].append({**outcome, 'controlRet': control['ret'],
                                                         'deltaRet': outcome['ret'] - control['ret']})
    output = []
    for version, signals in sorted(groups.items(), key=lambda pair: pair[0] != rules):
        ids = list(dict.fromkeys([spec['id'] for spec in ss.SIGNALS] + [key[0] for key in signals]))
        rows = []
        for signal in ids:
            horizons = []
            for horizon in (5, 20):
                bucket = signals[(signal, horizon)]
                forward = _summarize(bucket['mature'])
                ref_rows = bucket['references']
                reference = _summarize(ref_rows)
                reference.update(missing=len(bucket['mature']) - len(ref_rows),
                                 meanControlRet=statistics.fmean(row['controlRet'] for row in ref_rows) if len(ref_rows) >= ss.MIN_SAMPLE else None,
                                 meanDeltaRet=statistics.fmean(row['deltaRet'] for row in ref_rows) if len(ref_rows) >= ss.MIN_SAMPLE else None)
                source = history_rows.get((signal, horizon), {}) if version == rules else {}
                history_ok = version == rules and verified_history
                historical_row = {key: source.get(key) for key in ('n', 'symbols', 'window')}
                historical_row['gate'] = 'ok' if history_ok and (source.get('n') or 0) >= ss.MIN_SAMPLE else 'insufficient' if history_ok else 'unverified_version'
                for key in ('upRatio', 'medianRet', 'medianAdverse', 'meanControlRet', 'meanDeltaRet', 'costScenarios'):
                    historical_row[key] = source.get(key) if historical_row['gate'] == 'ok' else None
                horizons.append({'horizon': horizon, 'observed': bucket['observed'], 'mature': len(bucket['mature']),
                                 'waiting': bucket['waiting'], 'unverified': bucket['unverified'],
                                 'pendingReasons': dict(sorted(bucket['pendingReasons'].items())),
                                 'forward': forward, 'reference': reference, 'historical': historical_row})
            rows.append({'signalId': signal, 'label': ss.SIGNAL_BY_ID.get(signal, {}).get('label', signal), 'horizons': horizons})
        output.append({'rulesDigest': version, 'currentRules': version == rules, 'signals': rows})
    return {'version': 'st-forward-comparison/v1', 'enabled': enabled, 'activatedAt': activation,
            'observedEvents': event_count, 'minSample': ss.MIN_SAMPLE, 'currentRulesDigest': rules,
            'currentMethodDigest': method, 'historicalVerified': verified_history,
            'historicalGeneratedAt': historical.get('generatedAt'), 'groups': output, 'diagnostics': diagnosis,
            'candidatePromotion': False, 'externalCalls': 0,
            'limitations': [
                '前瞻為啟用後首次留存事件；沒有成熟結果就等待，不回填過去事件。',
                '各引擎版本分開呈現；歷史研究需規則與方法指紋相符才能在此展示比率。',
                '歷史研究同訊號至少相隔 5 根；每日帳本保留全部當日事件。樣本集合不同，不能將兩欄差值解讀為績效改善。',
                '相對基準為同股票、同大盤情境、事件日前已成熟的過去報酬，不是持有期間的大盤超額報酬。',
                '前瞻對照從事件當時凍結資料重建，至少 20 筆具足夠對照的成熟事件才展示差距。',
                '均採次一交易日收盤進入、持有 5／20 個交易日；偏空及風險事件亦以持有現股的報酬與下跌幅度描述。',
                '價格未還原；成本 0／20／50／100 基點為往返假設，不代表實際費用。滿 20 筆僅開始展示描述統計，不判定優勢或自動晉升。',
            ]}
