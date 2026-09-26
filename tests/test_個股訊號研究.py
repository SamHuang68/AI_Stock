"""研究分段、群聚、未來資料與前瞻不可覆寫的回歸測試。"""
from __future__ import annotations

import json
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from contextlib import closing, redirect_stderr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import datastore
import stock_signals as ss
import signal_stats_pool as pool
import 個股訊號研究 as research
import 個股訊號帳本 as ledger


class CommandTests(unittest.TestCase):
    def load_command(self):
        spec = importlib.util.spec_from_file_location('stock_study_command', ROOT / 'scripts/個股訊號成績單.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_cache_cannot_overwrite_frozen_artifacts_before_any_output(self):
        command = self.load_command()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / '研究'
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as err:
                command.main(['--output', str(output), '--cache-file', str(output / '成績單.json')])
            self.assertEqual(err.exception.code, 2)
            self.assertFalse(output.exists())

    def test_engine_change_prevents_registration(self):
        command = self.load_command()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / '行情.sqlite3'
            with closing(sqlite3.connect(db)) as c, c:
                c.executescript(datastore.SCHEMA)
            output = Path(tmp) / '研究'
            with patch.object(command, 'engine_digest', side_effect=['before', 'after']), \
                    patch.object(pool, 'compute_snapshot', return_value={'research': {}}), \
                    self.assertRaisesRegex(RuntimeError, '快照變動'):
                command.main(['--output', str(output), '--db', str(db), '--chips', str(Path(tmp) / '無籌碼'),
                              '--frozen-source'])
            self.assertFalse((output / '個股訊號前瞻.sqlite3').exists())
            self.assertFalse((output / '執行紀錄.json').exists())


def bars(n=1100, start=date(2020, 1, 2)):
    import random
    rng = random.Random(72)
    out, px, day = [], 100, start
    for i in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        px *= 1 + rng.gauss(.0007, .021)
        out.append({'date': day.isoformat(), 'open': px, 'high': px * 1.01,
                    'low': px * .99, 'close': px, 'volume': 1000 + rng.random() * 5000})
        day += timedelta(days=1)
    return out


class ResearchTests(unittest.TestCase):
    def test_snapshot_without_matching_session_cannot_change_chip_light(self):
        series = bars(90)
        yesterday = series[-1]['date']
        chips = [{'date': yesterday, 'trust': -5, 'foreign': -4},
                 {'date': '2099-01-01', 'trust': 10, 'foreign': 10}]
        result = ss.analyze(series, symbol='2330', chips=chips)
        self.assertEqual(result['chip']['asOf'], yesterday)
        self.assertEqual(result['chip']['days'], 1)

    def test_rsi_context_is_separate_and_unknown_market_is_excluded(self):
        self.assertTrue(research.context_matches('other', 'down', research.RSI_POLICY['context']))
        self.assertFalse(research.context_matches('unknown', 'down', research.RSI_POLICY['context']))
        self.assertFalse(research.context_matches('down', 'down', research.RSI_POLICY['context']))
        self.assertFalse(research.context_matches('up', 'down', research.CONTEXT))
        st = research.Study([])
        rows = []
        for year in [2020, 2021, 2022, 2024, 2025]:
            for month in [1, 4, 7, 10]:
                for i in range(20):
                    chosen = i % 2 == 0
                    delta = (.03 if chosen else -.01) if year < 2024 else (-.03 if chosen else .01)
                    rows.append({**self.row(f'{year}-{month:02d}-15', symbol=str(i), delta=delta),
                                 'marketRegime': 'other', 'stockRegime': 'down' if chosen else 'up'})
        st.rows['mom_rsi_rebound'][5] = rows
        result = st.rsi_rebound()
        self.assertEqual(result['selection']['status'], 'temporal_check_failed')
        self.assertEqual(result['selection']['signalId'], 'mom_rsi_rebound')
        self.assertEqual(research.POLICY['context'], 'market_up_stock_up')

    def test_professional_distribution_gate_and_event_values(self):
        series = bars(1100)
        frame = ss.build_frame(series)
        spec = ss.SIGNAL_BY_ID['mom_macd_bull']
        result = ss.signal_stats(frame, spec, min_sample=9999)
        self.assertTrue(all(h['distribution'] is None for h in result['horizons']))
        result = ss.signal_stats(frame, spec)
        h = result['horizons'][0]
        self.assertEqual(h['gate'], 'ok')
        self.assertLessEqual(h['distribution']['p10'], h['distribution']['p50'])
        self.assertLessEqual(h['distribution']['p50'], h['distribution']['p90'])
        events = ss.recent_events(frame, lookback=1100, provisional_last=True)
        for e in events:
            t = frame['date'].index(e['date'])
            self.assertEqual(e['audit']['triggerValues']['rsi']['at'], frame['rsi'][t])
            self.assertEqual(e['audit']['triggerValues']['rsi']['before'], frame['rsi'][t - 1])
            self.assertTrue(e['audit']['statusProvisional'])

    def test_intraday_twentieth_outcome_does_not_open_distribution_gate(self):
        series = bars(90)
        with patch.object(ss, 'event_indices', return_value=list(range(65, 85))):
            closed = ss.analyze(series, symbol='2330')
            live = ss.analyze(series, symbol='2330', provisional_last=True)
        self.assertTrue(live['events'])
        for event in live['events']:
            if ss.SIGNAL_BY_ID[event['signalId']].get('entryLag', 0):
                continue
            h = event['stats']['horizons'][0]
            self.assertEqual(h['n'], 19)
            self.assertIsNone(h['distribution'])
            self.assertEqual(event['stats']['window']['to'], series[-2]['date'])
            previous = next(e for e in closed['events'] if e['signalId'] == event['signalId'])
            self.assertEqual(previous['stats']['horizons'][0]['n'], 20)

    def test_chip_source_date_and_deduplication_match_both_readers(self):
        with tempfile.TemporaryDirectory() as tmp:
            for day, value in [('20260924', 1), ('20260926', 2)]:
                (Path(tmp) / (day + '.json')).write_text(json.dumps({
                    '2330': {'sourceDate': '2026-09-24', 'trust': value, 'foreign': -value}}), encoding='utf-8')
            single = ss.load_chip_series('2330', tmp)
            pooled = pool._load_all_chips(tmp)['2330']
        self.assertEqual(single, pooled)
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]['date'], '2026-09-24')
        self.assertEqual(single[0]['trust'], 2)
        self.assertIsNone(ss.normalize_chip_record({'sourceDate': '2026-09-28'}, '2026-09-27'))
    def test_intraday_last_bar_is_excluded_at_snapshot_boundary(self):
        series = bars(300)
        current = datetime.fromisoformat(series[-1]['date'] + 'T11:00:00+08:00')
        captured = []
        def capture(values, **kwargs):
            captured.extend(values)
            return {}
        with patch.object(pool, 'iter_datastore', return_value=iter([('2330', series)])), \
                patch.object(datastore, 'get_bars_bulk', return_value={'^TWII': series}), \
                patch.object(pool, 'compute_pooled', side_effect=capture):
            out = pool.compute_snapshot(None, now=current)
        self.assertEqual(len(captured[0][1]), 299)
        self.assertEqual(out['research']['benchmarkCoverage']['bars'], 299)
        self.assertEqual(out['researchAsOf'], current.isoformat())

    def test_future_append_does_not_change_mature_observations(self):
        series = bars()
        short = research.Study(series[:800])
        full = research.Study(series)
        short.add('2330', ss.build_frame(series[:800]))
        full.add('2330', ss.build_frame(series))
        count = 0
        for sid, horizons in short.rows.items():
            for hz, records in horizons.items():
                expected = [r for r in full.rows[sid][hz] if r['endDate'] <= series[799]['date']]
                self.assertEqual(records, expected)
                for r in records:
                    self.assertLess(r['controlEndDate'], r['date'])
                count += len(records)
        self.assertGreater(count, 20)

    def test_unknown_market_keeps_all_fifteen_without_fabricated_statistics(self):
        st = research.Study([])
        st.add('2330', ss.build_frame(bars(500)))
        report = st.finish()
        self.assertEqual(len(report['signals']), 15)
        self.assertEqual(report['selection']['status'], 'no_candidate')
        self.assertTrue(all(h['all']['upRatio'] is None for s in report['signals'] for h in s['horizons']))

    def test_hundreds_of_correlated_stocks_do_not_create_time_blocks(self):
        records = [self.row('2020-03-01', symbol=str(i)) for i in range(300)]
        s = research.summarize(records)
        self.assertEqual(s['quarters'], 1)
        self.assertIsNone(s['deltaRetCI95'])

    @staticmethod
    def row(day, symbol='2330', context=True, delta=.02, end=None):
        return {'symbol': symbol, 'date': day, 'endDate': end or day,
                'ret': delta + .01, 'adverse': -.02, 'controlRet': .01, 'controlUp': .5,
                'deltaRet': delta, 'context': context}

    def test_cross_cutoff_outcome_is_not_training(self):
        st = research.Study([])
        st.rows['mom_macd_bull'][5] = [self.row('2023-12-28', end='2024-01-09')]
        h = next(s for s in st.finish()['signals'] if s['signalId'] == 'mom_macd_bull')['horizons'][0]
        self.assertEqual(h['all']['n'], 1)
        self.assertEqual(h['training']['unfiltered']['n'], 0)
        self.assertEqual(h['temporalCheck']['unfiltered']['n'], 0)

    def test_selection_is_training_only_and_does_not_switch_on_failed_check(self):
        st = research.Study([])
        for sid, advantage in [('mom_macd_bull', .03), ('vol_breakout_20d', .02)]:
            rows = []
            for year in [2020, 2021, 2022, 2024, 2025]:
                for month in [1, 4, 7, 10]:
                    for i in range(20):
                        selected = i % 2 == 0
                        delta = advantage if selected else -.01
                        if year >= 2024 and sid == 'mom_macd_bull':
                            delta = -.03 if selected else .01
                        rows.append(self.row(f'{year}-{month:02d}-15', symbol=str(i), context=selected, delta=delta))
            st.rows[sid][5] = rows
        choice = st.finish()['selection']
        self.assertEqual(choice['signalId'], 'mom_macd_bull')
        self.assertEqual(choice['status'], 'temporal_check_failed')

    def test_read_snapshot_is_query_only_and_uses_existing_datastore_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '行情.sqlite3'
            with closing(sqlite3.connect(path)) as c, c:
                c.executescript(datastore.SCHEMA)
                c.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', 1, 1, 1, 1, 1, 1))
            before = path.read_bytes()
            with datastore.read_snapshot(path) as c:
                self.assertEqual(datastore.list_symbols(connection=c), ['2330'])
                self.assertEqual(len(datastore.get_bars_bulk(['2330'], connection=c)['2330']), 1)
                with self.assertRaises(sqlite3.OperationalError):
                    c.execute('DELETE FROM bars')
            self.assertEqual(path.read_bytes(), before)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '帳本.sqlite3'
        self.series = bars(120)
        self.origin = self.series[-1]['date']
        self.report = {'policy': research.POLICY, 'selection': {'status': 'forward_only', 'signalId': 'mom_macd_bull'},
                       'signals': [], 'limitations': []}
        self.registered = datetime.fromisoformat(self.series[-2]['date'] + 'T16:00:00+08:00')
        self.pid = ledger.register(self.path, self.report, 'fixed', self.registered)
        self.sid = 'mom_macd_bull'

    def run_track(self, rows, when, engine='fixed', benchmark=None, chips=None):
        # 只替換事件是否成立；帳本、時間、結果與實際價格計算照常執行。
        original = ss.SIGNAL_BY_ID[self.sid]
        spec = {**original,
                'detect': lambda f, t: {'detail': '測試事件', 'level': f['close'][t]},
                'invalid': original['invalid'] if original['family'] == 'chip' else
                           lambda f, t, k, e: f['close'][k] < e['level']}
        with patch.dict(ss.SIGNAL_BY_ID, {self.sid: spec}), \
                patch.object(ss, 'event_indices', side_effect=lambda f, s: [len(f['date']) - 1]), \
                patch.object(research, 'regime', return_value='up'):
            return ledger.track(self.path, self.pid, [('2330', rows)], benchmark or rows, engine,
                                now=datetime.fromisoformat(when), chips=chips)

    def test_registration_day_past_day_and_intraday_cannot_become_forward_events(self):
        self.assertEqual(self.run_track(self.series[:-1], self.registered.isoformat())['observationsAdded'], 0)
        tomorrow = (date.fromisoformat(self.origin) + timedelta(days=1)).isoformat()
        self.assertEqual(self.run_track(self.series, tomorrow + 'T16:00:00+08:00')['observationsAdded'], 0)
        self.assertEqual(self.run_track(self.series, self.origin + 'T11:00:00+08:00')['observationsAdded'], 0)

    def test_replay_and_revision_cannot_rewrite_observation_or_outcome(self):
        first = self.run_track(self.series, self.origin + 'T16:00:00+08:00')
        self.assertEqual(first['observationsAdded'], 1)
        self.assertEqual(self.run_track(self.series, self.origin + 'T17:00:00+08:00')['observationsAdded'], 0)
        longer = bars(142)
        now = longer[-1]['date'] + 'T16:00:00+08:00'
        result = self.run_track(longer, now)
        self.assertEqual(result['outcomesAdded'], 2)
        with closing(sqlite3.connect(self.path)) as c:
            original = c.execute('SELECT payload FROM stock_outcomes ORDER BY trial_id,horizon').fetchall()
            observation = c.execute('SELECT payload FROM stock_trials WHERE origin_session=?', (self.origin,)).fetchone()
        revised = [{**b, 'close': b['close'] * 2} for b in longer]
        self.run_track(revised, now)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute('SELECT payload FROM stock_outcomes ORDER BY trial_id,horizon').fetchall(), original)
            self.assertEqual(c.execute('SELECT payload FROM stock_trials WHERE origin_session=?', (self.origin,)).fetchone(), observation)
        outcome = json.loads(original[0][0])
        self.assertEqual(outcome['entryDate'], longer[120]['date'])
        self.assertEqual(outcome['endDate'], longer[125]['date'])
        self.assertEqual(len(json.loads(observation[0])['benchmarkBars']), len(self.series))

    def test_known_missing_session_waits_for_original_entry_price(self):
        self.run_track(self.series, self.origin + 'T16:00:00+08:00')
        longer = bars(142)
        missing_entry = longer[:120] + longer[121:]
        now = longer[-1]['date'] + 'T16:00:00+08:00'
        r = self.run_track(missing_entry, now, benchmark=longer)
        self.assertEqual(r['outcomesAdded'], 0)
        r = self.run_track(longer, now)
        self.assertEqual(r['outcomesAdded'], 2)
        with closing(sqlite3.connect(self.path)) as c:
            values = [json.loads(r[0]) for r in c.execute('SELECT payload FROM stock_outcomes')]
        self.assertEqual(values[0]['entryDate'], longer[120]['date'])

    def test_engine_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '版本'):
            self.run_track(self.series, self.origin + 'T16:00:00+08:00', 'changed')

    def test_future_chip_reversal_and_missing_chip_do_not_confirm(self):
        self.sid = 'chip_trust_buy3'
        self.report['selection']['signalId'] = self.sid
        self.pid = ledger.register(self.path, self.report, 'fixed', self.registered)
        initial = [{'date': b['date'], 'trust': 1} for b in self.series]
        self.run_track(self.series, self.origin + 'T16:00:00+08:00', chips={'2330': initial})
        longer = bars(126)
        future = [{'date': b['date'], 'trust': -1} for b in longer[120:]]
        future[2]['trust'] = None  # 已知次日轉賣，不應被稍後缺值抹去失效證據。
        self.run_track(longer, longer[-1]['date'] + 'T16:00:00+08:00', chips={'2330': initial + future})
        with closing(sqlite3.connect(self.path)) as c:
            outcome = json.loads(c.execute('SELECT payload FROM stock_outcomes').fetchone()[0])
        self.assertEqual(outcome['lifecycle']['status'], 'invalidated')
        # 不同協定獨立驗證未來籌碼缺值。
        self.pid = ledger.register(self.path, self.report, 'fixed', self.registered + timedelta(minutes=1))
        self.run_track(self.series, self.origin + 'T16:00:00+08:00', chips={'2330': initial})
        self.run_track(longer, longer[-1]['date'] + 'T16:00:00+08:00', chips={'2330': initial})
        with closing(sqlite3.connect(self.path)) as c:
            payload = c.execute('SELECT o.payload FROM stock_outcomes o JOIN stock_trials t ON t.trial_id=o.trial_id '
                                'WHERE t.protocol_id=?', (self.pid,)).fetchone()[0]
        self.assertEqual(json.loads(payload)['lifecycle']['status'], 'unavailable')

    def test_no_candidate_registers_inactive_protocol(self):
        report = {**self.report, 'selection': {'status': 'no_candidate', 'reason': '資料不足'}}
        pid = ledger.register(self.path, report, 'fixed', self.registered)
        r = ledger.track(self.path, pid, [], {}, 'fixed')
        self.assertEqual(r['status'], 'inactive')
        self.assertEqual(r['observationsAdded'], 0)


if __name__ == '__main__':
    unittest.main()
