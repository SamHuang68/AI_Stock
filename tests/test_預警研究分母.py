"""以隔離 SQLite 與固定日曆證明前向分母、版本與重播，不使用網路。"""
from __future__ import annotations

import copy
import json
import socket
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.test_early_warning import ew, fixture, memory

r = ew.warning_research
START = datetime(2026, 8, 26, 1, 10, tzinfo=timezone.utc)
DATES = ['2026-08-26', '2026-08-27', '2026-08-28', '2026-08-31', '2026-09-01', '2026-09-02',
         '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10']


def calendar():
    return {'status': 'ready', 'market': 'TW', 'dates': list(DATES), 'version': '固定日曆版本',
            'source': 'TWSE 測試收據', 'sourceAsOf': '2026-01-01T00:00:00+00:00', 'years': [2026]}


class WarningResearchTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='預警研究-')
        self.addCleanup(self.folder.cleanup)
        self.db = str(Path(self.folder.name) / 'signals.db')
        network = patch.object(socket, 'create_connection', side_effect=AssertionError('測試禁止連外'))
        network.start()
        self.addCleanup(network.stop)

    def publish(self, at=START, history=None, cal=None, publication_id=None):
        context, pulse = fixture(as_of=at.isoformat())
        return ew.process_context(context, pulse, memory_snapshot=memory(), market_history=history or [],
                                  research_calendar=calendar() if cal is None else cal, db_path=self.db,
                                  now=at, publication_id=publication_id)

    def records(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return [json.loads(row[0]) for row in conn.execute('SELECT payload_json FROM signal_research_observations')]

    def frozen(self, direction='upside', alert=False):
        context, pulse = fixture(as_of=START.isoformat())
        evaluated = ew.evaluate_context(context, pulse, memory_snapshot=memory(), now=START)
        signal = dict(evaluated['signals'][1], direction=direction, state='WATCH' if alert else 'OBSERVATION')
        return r.freeze(context, pulse, memory(), evaluated, [signal], ew._market_reference(pulse, START.isoformat()),
                        calendar(), START.isoformat())[0]

    def path(self, prices=None):
        return [{'date': day, 'close': price, 'source': '凍結市場歷史', 'asOf': day}
                for day, price in zip(DATES[1:6], prices or [102, 101, 103, 100, 105])]

    def test_denominator_includes_no_alert_and_survives_restart_without_replacement(self):
        result = self.publish()
        self.assertEqual(result['researchValidation']['observations'], 4)
        records = self.records()
        self.assertTrue(any(row['alert'] is False and row['eligible'] for row in records))
        self.assertTrue(any(row['alert'] is True for row in records))
        with patch.object(ew, '_db_ready', set()):
            self.publish(at=START + timedelta(minutes=1))
        self.assertEqual(self.records(), records)

    def test_missing_calendar_is_unknown_and_never_repaired_into_past_negative(self):
        self.publish(cal={})
        original = self.records()
        self.assertTrue(all(row['alert'] is None for row in original))
        self.publish()
        self.assertEqual(self.records(), original)
        perf = ew.performance(path=self.db)['researchValidation']
        self.assertTrue(all(group['horizons'][0]['unknown'] == 1 for group in perf['strata']))

    def test_old_origin_cannot_be_enrolled_after_next_session_opens(self):
        record = self.frozen()
        source = record['replay']
        late = r.freeze(source['context'], source['pulse'], source['memory'], source['evaluated'], [source['signal']],
                        source['marketReference'], calendar(), '2026-08-27T02:00:00+00:00')[0]
        self.assertFalse(late['eligible'])
        self.assertIn('已開始', late['unknownReason'])

    def test_calendar_future_receipt_and_insufficient_evidence_do_not_become_negative(self):
        record = self.frozen()
        source = record['replay']
        source['evaluated']['dataQuality']['availableDomains'] = 0
        params = (source['context'], source['pulse'], source['memory'], source['evaluated'], [source['signal']], source['marketReference'])
        self.assertIsNone(r.freeze(*params, calendar(), START.isoformat())[0]['alert'])
        future = dict(calendar(), sourceAsOf='2026-09-01T00:00:00+00:00')
        self.assertIn('晚於', r.freeze(*params, future, START.isoformat())[0]['unknownReason'])

    def test_horizon_uses_exact_frozen_sessions_and_never_skips_missing_day(self):
        record = self.frozen()
        path = self.path()[1:] + [{'date': '2026-09-03', 'close': 120, 'source': '市場歷史'}]
        outcomes = r.resolve(record, path, '2026-09-04T12:00:00+00:00')
        self.assertTrue(all(outcome['status'] == 'unknown' for outcome in outcomes))
        self.assertTrue(all(outcome['materialMoveHit'] is None for outcome in outcomes))

    def test_immature_no_lookahead_exact_boundary_and_close_path(self):
        record = self.frozen(direction='downside')
        path = self.path([98, 101, 99, 97, 100])
        early = r.resolve(record, path, '2026-08-27T02:00:00+00:00')
        self.assertTrue(all(outcome['status'] == 'immature' for outcome in early))
        final = r.resolve(record, path, '2026-09-03T12:00:00+00:00')
        self.assertTrue(final[0]['materialMoveHit'])
        self.assertEqual(final[0]['eventArrivalSessions'], 1)
        self.assertIsNone(final[0]['relativeLeadSessions'])
        self.assertEqual(final[1]['closePathMaxAdversePct'], 1)
        future = copy.deepcopy(path)
        future[0]['asOf'] = '2027-01-01T00:00:00+00:00'
        self.assertEqual(r.resolve(record, future, '2026-09-03T12:00:00+00:00')[0]['status'], 'unknown')

    def test_replay_input_is_deeply_frozen_and_round_trips_pure_evaluation(self):
        self.publish()
        record = self.records()[0]
        replay = ew.replay_observation(record['observationId'], self.db)
        self.assertTrue(replay['ok'], replay.get('status'))
        self.assertEqual(replay['record']['inputDigest'], r.digest(replay['record']['replay']))
        self.assertIn(record['observationId'], {row['observationId'] for row in ew.performance(path=self.db)['researchObservations']})
        with patch.object(ew, 'ENGINE_VERSION', '未保留的新版'):
            self.assertEqual(ew.replay_observation(record['observationId'], self.db)['status'], 'version_unavailable')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            record['replay']['context']['ok'] = False
            conn.execute('UPDATE signal_research_observations SET payload_json=? WHERE observation_id=?',
                         (json.dumps(record), record['observationId']))
        self.assertEqual(ew.replay_observation(record['observationId'], self.db)['status'], 'digest_mismatch')
        record['inputDigest'] = r.digest(record['replay'])
        record['protocol']['minimumSample'] = 100
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE signal_research_observations SET payload_json=? WHERE observation_id=?',
                         (json.dumps(record), record['observationId']))
        self.assertEqual(ew.replay_observation(record['observationId'], self.db)['status'], 'protocol_mismatch')

    def test_intraday_or_date_only_current_close_cannot_mature_as_final_close(self):
        record = self.frozen()
        history = self.path()
        clock = '2026-08-27T12:00:00+00:00'
        self.assertEqual(r.resolve(record, history, clock)[0]['status'], 'unknown')
        history[0]['asOf'] = '2026-08-27T01:00:00+00:00'
        self.assertEqual(r.resolve(record, history, clock)[0]['status'], 'unknown')
        history[0]['asOf'] = '2026-08-27T05:30:00+00:00'
        self.assertEqual(r.resolve(record, history, clock)[0]['status'], 'mature')

    def test_freeze_does_not_retain_mutable_caller_input_or_global_protocol_lists(self):
        context, pulse = fixture(as_of=START.isoformat())
        evaluated = ew.evaluate_context(context, pulse, memory_snapshot=memory(), now=START)
        signal = dict(evaluated['signals'][1], state='WATCH')
        record = r.freeze(context, pulse, memory(), evaluated, [signal], ew._market_reference(pulse, START.isoformat()),
                          calendar(), START.isoformat())[0]
        fingerprint = record['inputDigest']
        context['scenario']['breadth']['value'] = -100
        signal['state'] = 'EXPIRED'
        self.assertEqual(r.digest(record['replay']), fingerprint)
        record['protocol']['horizons'].append(99)
        self.assertEqual(r.PROTOCOL['horizons'], [1, 3, 5])

    def test_outcomes_are_append_only_after_history_correction(self):
        self.publish()
        self.publish(at=datetime(2026, 9, 3, 12, tzinfo=timezone.utc), history=self.path())
        with closing(sqlite3.connect(self.db)) as conn:
            before = conn.execute('SELECT * FROM signal_research_outcomes ORDER BY rowid').fetchall()
        self.publish(at=datetime(2026, 9, 3, 12, 1, tzinfo=timezone.utc), history=self.path([50] * 5))
        with closing(sqlite3.connect(self.db)) as conn:
            after = conn.execute('SELECT * FROM signal_research_outcomes ORDER BY rowid').fetchall()
        self.assertEqual(before, after)

    def test_writer_preserves_source_quality_and_invalid_correction_cannot_reuse_old_close(self):
        self.publish(history=self.path())
        invalid = self.path()
        invalid[0]['issues'] = ['官方日線尚未核對']
        invalid[1]['close'] = None
        self.publish(at=datetime(2026, 9, 3, 12, tzinfo=timezone.utc), history=invalid)
        records = self.records()
        origin_ids = {record['observationId'] for record in records if record['originSession'] == DATES[0]}
        with closing(sqlite3.connect(self.db)) as conn:
            outcomes = [json.loads(payload) for identity, payload in conn.execute('SELECT observation_id,payload_json FROM signal_research_outcomes') if identity in origin_ids]
            source = conn.execute('SELECT close,issues_json FROM signal_market_sessions WHERE session_date=?', (DATES[2],)).fetchone()
        self.assertTrue(outcomes)
        self.assertTrue(all(outcome['status'] == 'unknown' for outcome in outcomes))
        self.assertEqual(source[0], 0)
        self.assertIn('不能沿用', source[1])

    def test_engine_versions_split_denominators_and_legacy_rates(self):
        self.publish()
        with patch.object(ew, 'ENGINE_VERSION', '另一個規則版本'):
            self.publish(at=START + timedelta(minutes=1))
        self.assertEqual(len(self.records()), 8)
        perf = ew.performance(path=self.db)
        self.assertTrue(perf['mixedVersions'])
        self.assertEqual(len(perf['versionStrata']), 2)
        self.assertTrue(all(row.get('materialMoveHitRatePct') is None for row in perf['horizons']))
        self.assertEqual(len({row['protocolId'] for row in self.records()}), 2)

    def test_summary_missing_days_pending_maturity_and_paired_denominator(self):
        a = self.frozen()
        b = copy.deepcopy(a)
        b.update(observationId='第二個觀測', originSession=DATES[3], observedAt='2026-08-31T01:10:00+00:00', targetSessions=DATES[4:9], benchmarkAlert=None)
        outcomes = {a['observationId']: r.resolve(a, self.path(), '2026-09-03T12:00:00+00:00')}
        summary = r.summarize([a, b], outcomes, '2026-09-03T12:00:00+00:00')['strata'][0]
        self.assertEqual(summary['unobservedDates'], DATES[1:3])
        first = summary['horizons'][0]
        self.assertEqual(first['mature'], 1)
        self.assertEqual(first['awaitingResolution'], 1)
        self.assertEqual(first['benchmarkPairedEvents'], 1)
        self.assertEqual(first['missedEvents'], 1)
        self.assertIsNone(first['observedMissRatePct'])
        self.assertEqual(summary['horizons'][2]['immature'], 1)

    def test_nonoverlap_and_minimum_samples_do_not_pool_versions(self):
        records, outcomes = [], {}
        start = datetime(2026, 1, 1)
        for index in range(20):
            record = self.frozen(alert=index % 2 == 0)
            days = [(start + timedelta(days=index + offset)).date().isoformat() for offset in range(6)]
            record.update(observationId=str(index), originSession=days[0], targetSessions=days[1:], benchmarkAlert=index % 4 == 0)
            records.append(record)
            outcomes[str(index)] = [{'horizonSessions': h, 'status': 'mature', 'targetSession': days[h], 'materialMoveHit': True} for h in (1, 3, 5)]
        horizons = r.summarize(records, outcomes, '2026-09-03T12:00:00+00:00')['strata'][0]['horizons']
        self.assertEqual(horizons[0]['observedMissRatePct'], 50)
        self.assertEqual(horizons[0]['signalCapturePct'], 50)
        self.assertEqual(horizons[0]['benchmarkCapturePct'], 25)
        self.assertEqual(horizons[0]['nonOverlapping'], 10)
        self.assertEqual(horizons[2]['nonOverlapping'], 4)
        for record in records:
            record['protocol'].update(minimumSample=100, horizons=[1, 5])
        frozen = r.summarize(records, outcomes, '2026-09-03T12:00:00+00:00')['strata'][0]['horizons']
        self.assertEqual([h['sessions'] for h in frozen], [1, 5])
        self.assertIsNone(frozen[0]['observedMissRatePct'])

    def test_read_only_performance_calendar_and_missing_files_create_nothing(self):
        missing = str(Path(self.folder.name) / '不存在.db')
        self.assertEqual(r.load_calendar(missing)['status'], 'unknown')
        self.assertFalse(ew.performance(path=missing)['ok'])
        self.assertFalse(Path(missing).exists())
        market = Path(self.folder.name) / 'market.db'
        with closing(sqlite3.connect(market)) as conn, conn:
            conn.executescript('CREATE TABLE calendar_years(year,refreshed_at); CREATE TABLE market_sessions(session_date,source);')
            conn.execute('INSERT INTO calendar_years VALUES(2026,?)', ('2026-01-01T00:00:00+00:00',))
            conn.executemany('INSERT INTO market_sessions VALUES(?,?)', [(day, 'TWSE開休市') for day in DATES])
        before = market.read_bytes()
        self.assertEqual(r.load_calendar(market)['dates'], DATES)
        self.assertEqual(market.read_bytes(), before)
        self.publish()
        with closing(sqlite3.connect(self.db)) as conn:
            before = list(conn.iterdump())
        ew.performance(path=self.db)
        ew.replay_observation(self.records()[0]['observationId'], self.db)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(list(conn.iterdump()), before)

    def test_publication_rollback_covers_new_denominator_and_outcomes(self):
        self.publish(publication_id='已提交')
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TRIGGER 拒絕新收據 BEFORE INSERT ON signal_publication_receipts BEGIN SELECT RAISE(FAIL,'測試'); END")
            before = list(conn.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            self.publish(at=START + timedelta(days=1), publication_id='應回滾')
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(list(conn.iterdump()), before)


if __name__ == '__main__':
    unittest.main()
