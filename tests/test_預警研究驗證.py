"""前向預警研究使用獨立資料庫，不讀取正式帳本或外部資料。"""
from contextlib import closing
import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import early_warning as ew
import 預警研究驗證 as research


START = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
DAYS = ['2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04',
        '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10']


def calendar():
    return {'status': 'ready', 'market': 'TW', 'dates': DAYS, 'years': [2026],
            'version': research.digest(DAYS), 'source': 'TWSE開休市',
            'sourceAsOf': '2026-08-31T00:00:00+00:00'}


def fixture(at=START):
    stamp = at.isoformat()
    context = {'ok': True, 'asOf': stamp, 'dataQuality': {'freshness': 1, 'completeness': 1},
               'scenario': {'breadth': {'value': .9, 'raw': {}}, 'flow': {'value': .9, 'raw': {}},
                            'sector': {'value': .9, 'raw': {}}},
               'evidence': [{'id': key, 'asOf': stamp} for key in
                            ['breadth.stock_scope', 'breadth.velocity', 'flow.institutional', 'flow.tx_oi']]}
    pulse = {'ok': True, 'updatedAt': stamp,
             'marketSnapshot': {'quotes': {'^TWII': {'price': 100, 'tradeDate': stamp[:10],
                'changePct': 2, 'market': {'asOf': stamp, 'source': 'TWSE', 'session': 'regular'}},
                '__TXF__': {'changePct': 2, 'market': {'asOf': stamp, 'source': 'TAIFEX', 'session': 'regular'}}}},
             'global': [{'symbol': symbol, 'changePct': 2, 'asOf': stamp} for symbol in ['^SOX', '^IXIC', 'TSM']],
             'signalQuotes': [{'symbol': '2330.TW', 'changePct': 2, 'asOf': stamp}]}
    return context, pulse


def closes(days=DAYS[1:6], close=100):
    return [{'date': day, 'close': close, 'source': 'TWSE', 'asOf': day + 'T06:00:00+00:00',
             'observedAt': day + 'T06:01:00+00:00', 'issues': []} for day in days]


def pure_record(*, eligible=True, alert=False):
    context, pulse = fixture()
    evaluated = ew.evaluate_context(context, pulse, now=START)
    signal = {**evaluated['signals'][1], 'state': 'WATCH' if alert else 'OBSERVATION',
              'engineVersion': ew.ENGINE_VERSION, 'policyVersion': ew.POLICY_VERSION}
    if not eligible:
        context['dataQuality']['freshness'] = 0
    return research.freeze(context, pulse, None, evaluated, [signal], ew._market_reference(pulse, START.isoformat()),
                           calendar(), START.isoformat(), rules_digest=ew._research_rules_digest())[0]


class 預警研究驗證測試(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name) / 'market_signals.db')

    def publish(self, at=START, **kwargs):
        context, pulse = fixture(at)
        return ew.process_context(context, pulse, db_path=self.path, now=at,
                                  research_calendar=calendar(), **kwargs)

    def calendar_cache(self, *, imported=None, closed=None, opened=None, years=(2026,)):
        path = Path(self.folder.name) / 'market.db'
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute('CREATE TABLE calendar_years(year INTEGER PRIMARY KEY,closed TEXT,opened TEXT,refreshed_at TEXT)')
            conn.execute('CREATE TABLE market_sessions(session_date TEXT PRIMARY KEY,source TEXT)')
            for year in years:
                conn.execute('INSERT INTO calendar_years VALUES(?,?,?,?)',
                             (year, json.dumps(closed or []), json.dumps(opened or []), '2026-08-31T00:00:00+00:00'))
            conn.executemany('INSERT INTO market_sessions VALUES(?,?)',
                             [(day, 'TWSE實際成交日') for day in (imported or [])])
        return path

    def test_首次快照含未觸發分母且逐筆可重播(self):
        result = self.publish()
        page = ew.observation_page(path=self.path, now=START)
        self.assertEqual(result['researchValidation']['status'], 'collecting')
        self.assertEqual(page['totalObservations'], 4)
        self.assertGreater(page['researchValidation']['eligible'], 0)
        self.assertTrue(any(row['alert'] is False for row in page['observations']))
        for row in page['observations']:
            replay = ew.replay_observation(row['observationId'], self.path)
            self.assertTrue(replay['ok'], replay)
            self.assertEqual(replay['status'], 'matched')

    def test_同日凍結不被後續重算或呼叫端修改(self):
        self.publish()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            original = conn.execute('SELECT * FROM signal_research_observations ORDER BY observation_id').fetchall()
        context, pulse = fixture(START + timedelta(minutes=20))
        pulse['marketSnapshot']['quotes']['^TWII']['price'] = 999
        ew.process_context(context, pulse, db_path=self.path, now=START + timedelta(minutes=20), research_calendar=calendar())
        pulse['global'].clear()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(original, conn.execute('SELECT * FROM signal_research_observations ORDER BY observation_id').fetchall())

    def test_不同日與分頁不會縮小總分母(self):
        self.publish()
        self.publish(START + timedelta(days=1))
        page = ew.observation_page(1, self.path, now=START + timedelta(days=1))
        self.assertEqual(page['returnedObservations'], 1)
        self.assertEqual(page['totalObservations'], 8)
        self.assertEqual(page['nextOffset'], 1)
        next_page = ew.observation_page(1, self.path, offset=1, now=START + timedelta(days=1))
        self.assertNotEqual(page['observations'][0]['observationId'], next_page['observations'][0]['observationId'])
        self.assertEqual(page['researchValidation'], next_page['researchValidation'])
        for group in page['researchValidation']['strata']:
            for horizon in group['horizons']:
                self.assertEqual(horizon['denominator'], sum(horizon[key] for key in
                                 ('mature', 'immature', 'unknown', 'awaitingResolution')))

    def test_零報酬與未知未成熟等待分開(self):
        record = pure_record()
        early = research.resolve(record, [], START.isoformat())
        self.assertTrue(all(row['status'] == 'immature' for row in early))
        late = '2026-09-08T11:00:00+00:00'
        mature = research.resolve(record, closes(), late)
        self.assertTrue(all(row['status'] == 'mature' for row in mature))
        self.assertTrue(all(row['directionalReturnPct'] == 0 for row in mature))
        self.assertFalse(mature[0]['materialMoveHit'])
        unknown = research.resolve(record, [], late)
        self.assertTrue(all(row['status'] == 'unknown' for row in unknown))
        self.assertIsNone(unknown[0]['materialMoveHit'])
        summary = research.summarize([record], {}, late)
        self.assertTrue(all(row['awaitingResolution'] == 1 for row in summary['strata'][0]['horizons']))

    def test_指定交易日缺日停牌與共同缺日不壓縮(self):
        record = pure_record()
        for rows in (closes(DAYS[2:7]), [], closes() + [closes()[0]]):
            outcome = research.resolve(record, rows, '2026-09-10T11:00:00+00:00')
            self.assertEqual(outcome[0]['status'], 'unknown')
            self.assertEqual(outcome[0]['missingSessions'], [DAYS[1]])
        rows = closes()
        rows[0]['issues'] = ['停牌，沒有可信收盤']
        self.assertEqual(research.resolve(record, rows, '2026-09-10T11:00:00+00:00')[0]['status'], 'unknown')

    def test_未來資料不得成熟或列為合格(self):
        record = pure_record()
        rows = closes()
        rows[0]['observedAt'] = '2026-12-01T00:00:00+00:00'
        self.assertEqual(research.resolve(record, rows, '2026-09-10T11:00:00+00:00')[0]['status'], 'unknown')
        context, pulse = fixture()
        pulse['global'][0]['asOf'] = '2026-12-01T00:00:00+00:00'
        evaluated = ew.evaluate_context(context, pulse, now=START)
        frozen = research.freeze(context, pulse, None, evaluated, evaluated['signals'],
                                 ew._market_reference(pulse, START.isoformat()), calendar(), START.isoformat())
        self.assertTrue(all(not row['eligible'] for row in frozen))

    def test_舊起點不能回填前向觀測(self):
        context, pulse = fixture()
        observed = START + timedelta(days=1)
        evaluated = ew.evaluate_context(context, pulse, now=observed)
        frozen = research.freeze(context, pulse, None, evaluated, evaluated['signals'],
                                 ew._market_reference(pulse, START.isoformat()), calendar(), observed.isoformat())
        self.assertTrue(all(not row['eligible'] for row in frozen))
        self.assertIn('不能回填', frozen[0]['unknownReason'])

    def test_重複樣本與未觀測交易日明列(self):
        record = pure_record()
        later = copy.deepcopy(record)
        later.update(observationId='另一日', originSession=DAYS[3], observedAt='2026-09-04T06:00:00+00:00')
        summary = research.summarize([record, record, later], {}, START.isoformat())
        self.assertEqual(summary['observations'], 2)
        self.assertEqual(summary['duplicateObservations'], 1)
        self.assertEqual(summary['strata'][0]['unobservedDates'], DAYS[1:3])

    def test_首次到期缺資料凍結未知後補不改寫(self):
        self.publish()
        self.publish(START + timedelta(days=2), market_history=[])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            before = conn.execute('SELECT * FROM signal_research_outcomes ORDER BY observation_id,horizon_sessions').fetchall()
        self.publish(START + timedelta(days=2, minutes=20), market_history=closes())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            after = conn.execute('SELECT * FROM signal_research_outcomes ORDER BY observation_id,horizon_sessions').fetchall()
        self.assertEqual(before, after)
        self.assertTrue(any(json.loads(row[3])['status'] == 'unknown' for row in before))

    def test_版本差異與摘要不符都拒絕假重播(self):
        self.publish()
        identity = ew.observation_page(path=self.path)['observations'][0]['observationId']
        with patch.object(ew, 'ENGINE_VERSION', '歷史版本已不可用'):
            replay = ew.replay_observation(identity, self.path)
            self.assertEqual(replay['status'], 'version_unavailable')
            self.assertIn('evaluated', replay['record']['replay'])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            raw = json.loads(conn.execute('SELECT payload_json FROM signal_research_observations WHERE observation_id=?', (identity,)).fetchone()[0])
            raw['replay']['pulse']['ok'] = False
            conn.execute('UPDATE signal_research_observations SET payload_json=? WHERE observation_id=?', (json.dumps(raw), identity))
        self.assertEqual(ew.replay_observation(identity, self.path)['status'], 'digest_mismatch')

    def test_查詢不存在或舊資料庫完全唯讀(self):
        self.assertEqual(ew.observation_page(path=self.path)['status'], 'not_started')
        self.assertFalse(Path(self.path).exists())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE legacy(value TEXT)')
            conn.execute("INSERT INTO legacy VALUES('歷史資料')")
        before = Path(self.path).read_bytes()
        self.assertEqual(ew.observation_page(path=self.path)['status'], 'not_started')
        self.assertEqual(ew.replay_observation('缺少觀測', self.path)['status'], 'not_found')
        ew.performance(path=self.path)
        self.assertEqual(before, Path(self.path).read_bytes())
        with closing(research.readonly(self.path)) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('CREATE TABLE forbidden(x)')

    def test_舊資料安全註冊且所有列完整保留(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE legacy(value TEXT)')
            conn.execute("INSERT INTO legacy VALUES('既有資料')")
            research.initialize(conn)
            conn.execute("INSERT INTO signal_research_protocols VALUES('舊協定','{}','舊時間')")
            conn.execute("INSERT INTO signal_research_observations VALUES('舊觀測','舊協定','訊號','日期','時間','{}','{}')")
            conn.execute("INSERT INTO signal_research_outcomes VALUES('舊觀測',1,'時間','{}')")
            conn.execute('DROP TABLE signal_research_schema')
            conn.execute('PRAGMA user_version=7')
            tables = ['legacy', 'signal_research_protocols', 'signal_research_observations', 'signal_research_outcomes']
            before = {name: conn.execute('SELECT * FROM ' + name).fetchall() for name in tables}
            research.initialize(conn)
            research.initialize(conn)
            self.assertEqual(before, {name: conn.execute('SELECT * FROM ' + name).fetchall() for name in tables})
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 7)
            self.assertEqual(conn.execute('SELECT version FROM signal_research_schema').fetchall(), [(1,)])

    def test_不相容結構升級失敗回復原狀(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE signal_research_observations(original TEXT)')
            conn.execute("INSERT INTO signal_research_observations VALUES('保留')")
            before = list(conn.iterdump())
            with self.assertRaises(ValueError):
                research.initialize(conn)
            self.assertEqual(before, list(conn.iterdump()))

    def test_研究寫入失敗不更改確定性輸出(self):
        context, pulse = fixture()
        expected = ew.evaluate_context(context, pulse, now=START)
        with patch.object(research, 'write', side_effect=ValueError('測試寫入失敗')):
            result = self.publish()
        self.assertEqual(result['researchValidation']['status'], 'unavailable')
        self.assertEqual(result['familyScores'], expected['familyScores'])
        self.assertEqual(result['upside'], expected['upside'])
        self.assertTrue(result['signals'])

    def test_官方日曆快取查詢不建檔(self):
        path = Path(self.folder.name) / 'market.db'
        self.assertEqual(research.load_calendar(path)['status'], 'unknown')
        self.assertFalse(path.exists())
        self.calendar_cache(imported=DAYS, closed=['2026-01-01'])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(research.load_calendar(path)['status'], 'ready')
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_行情與已匯入日期共同缺日仍保留應有交易日(self):
        missing = DAYS[2]
        path = self.calendar_cache(imported=[day for day in DAYS if day != missing])
        loaded = research.load_calendar(path)
        self.assertEqual(loaded['status'], 'ready')
        self.assertIn(missing, loaded['dates'])
        context, pulse = fixture()
        ew.process_context(context, pulse, db_path=self.path, now=START)
        frozen = next(row for row in ew.observation_page(path=self.path, now=START)['observations']
                      if row['signalId'] == 'TW_ATTACK_BUILDUP')
        self.assertEqual(frozen['targetSessions'], DAYS[1:6])
        self.assertTrue(frozen['eligible'])
        at = datetime(2026, 9, 8, 11, tzinfo=timezone.utc)
        context, pulse = fixture(at)
        history = closes([day for day in DAYS[1:7] if day != missing])
        ew.process_context(context, pulse, db_path=self.path, now=at, market_history=history)
        original = next(row for row in ew.observation_page(path=self.path, now=at)['observations']
                        if row['observationId'] == frozen['observationId'])
        outcome = next(row for row in original['outcomes'] if row['horizonSessions'] == 3)
        self.assertEqual(outcome['targetSession'], DAYS[3])
        self.assertEqual(outcome['status'], 'unknown')
        self.assertEqual(outcome['missingSessions'], [missing])

    def test_只有觀測當日行情仍由年度收據凍結未來交易日(self):
        path = self.calendar_cache(imported=[DAYS[0]], closed=['2026-01-01'])
        loaded = research.load_calendar(path)
        self.assertEqual(loaded['status'], 'ready')
        self.assertFalse(loaded['priceDatesUsedAsCalendar'])
        self.assertIn(DAYS[5], loaded['dates'])
        context, pulse = fixture()
        result = ew.process_context(context, pulse, db_path=self.path, now=START, market_history=closes([DAYS[0]]))
        self.assertGreater(result['researchValidation']['eligible'], 0)
        original = next(row for row in ew.observation_page(path=self.path, now=START)['observations']
                        if row['signalId'] == 'TW_ATTACK_BUILDUP')
        self.assertEqual(original['targetSessions'], DAYS[1:6])
        self.assertEqual(original['outcomes'], [])

    def test_年度休市與週末補交易例外影響同一凍結時間軸(self):
        path = self.calendar_cache(closed=[DAYS[2]], opened=['2026-09-05'])
        loaded = research.load_calendar(path)
        self.assertNotIn(DAYS[2], loaded['dates'])
        self.assertIn('2026-09-05', loaded['dates'])
        context, pulse = fixture()
        evaluated = ew.evaluate_context(context, pulse, now=START)
        record = research.freeze(context, pulse, None, evaluated, evaluated['signals'],
                                 ew._market_reference(pulse, START.isoformat()), loaded, START.isoformat())[1]
        self.assertEqual(record['targetSessions'], [DAYS[1], DAYS[3], '2026-09-05', DAYS[4], DAYS[5]])
        outcomes = research.resolve(record, closes(record['targetSessions']), '2026-09-08T11:00:00+00:00')
        self.assertEqual(outcomes[1]['targetSession'], '2026-09-05')
        self.assertEqual(outcomes[1]['status'], 'mature')

    def test_只有已匯入日期沒有年度收據維持未知(self):
        path = self.calendar_cache(imported=DAYS, years=())
        loaded = research.load_calendar(path)
        self.assertEqual(loaded['status'], 'unknown')
        self.assertEqual(loaded['dates'], [])
        context, pulse = fixture()
        result = ew.process_context(context, pulse, db_path=self.path, now=START)
        self.assertEqual(result['researchValidation']['eligible'], 0)
        self.assertEqual(result['researchValidation']['ineligible'], 4)

    def test_缺少中間年度不得跳到隔年壓縮期間(self):
        path = self.calendar_cache(years=(2026, 2028))
        loaded = research.load_calendar(path)
        observed = datetime(2026, 12, 31, 6, tzinfo=timezone.utc)
        context, pulse = fixture(observed)
        evaluated = ew.evaluate_context(context, pulse, now=observed)
        rows = research.freeze(context, pulse, None, evaluated, evaluated['signals'],
                               ew._market_reference(pulse, observed.isoformat()), loaded, observed.isoformat())
        self.assertTrue(all(not row['eligible'] for row in rows))
        self.assertTrue(all('缺少完整官方' in row['unknownReason'] for row in rows))

    def test_日曆矛盾跨年或沒有取得時間均不冒充已核對(self):
        path = self.calendar_cache()
        for closed, opened, refreshed in (([DAYS[1]], [DAYS[1]], START.isoformat()),
                                          (['2027-01-01'], [], START.isoformat()), ([], [], None)):
            with self.subTest(closed=closed, opened=opened, refreshed=refreshed):
                with closing(sqlite3.connect(path)) as conn, conn:
                    conn.execute('UPDATE calendar_years SET closed=?,opened=?,refreshed_at=?',
                                 (json.dumps(closed), json.dumps(opened), refreshed))
                self.assertEqual(research.load_calendar(path)['status'], 'unknown')

    def test_歷史查詢不偷看後續觀測或成果(self):
        self.publish()
        self.publish(START + timedelta(days=2), market_history=closes())
        earlier = ew.observation_page(path=self.path, now=START)
        self.assertEqual(earlier['totalObservations'], 4)
        self.assertEqual(len(earlier['observations']), 4)
        self.assertEqual(earlier['researchValidation']['excludedFutureObservations'], 4)
        self.assertTrue(all(row['outcomes'] == [] for row in earlier['observations']))
        before_start = ew.observation_page(path=self.path, now=START - timedelta(minutes=1))
        self.assertEqual(before_start['totalObservations'], 0)

    def test_損壞資料庫不可當作零樣本(self):
        Path(self.path).write_text('這不是資料庫', encoding='utf-8')
        page = ew.observation_page(path=self.path)
        self.assertFalse(page['ok'])
        self.assertEqual(page['status'], 'unavailable')
        self.assertEqual(page['researchValidation']['status'], 'unavailable')
        self.assertEqual(ew.replay_observation('觀測', self.path)['status'], 'unavailable')

    def test_較新結構版本拒絕讀寫且不覆寫(self):
        self.publish()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE signal_research_schema SET version=999')
        page = ew.observation_page(path=self.path)
        self.assertFalse(page['ok'])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            before = list(conn.iterdump())
            with self.assertRaises(ValueError):
                research.initialize(conn)
            self.assertEqual(before, list(conn.iterdump()))

    def test_日曆未知與市場時間缺失不套用預設來源(self):
        context, pulse = fixture()
        pulse['marketSnapshot']['quotes']['^TWII']['market'].pop('asOf')
        result = ew.process_context(context, pulse, db_path=self.path, now=START, research_calendar=calendar())
        self.assertEqual(result['researchValidation']['eligible'], 0)
        self.assertEqual(result['researchValidation']['ineligible'], 4)
        self.assertTrue(all(row['alert'] is None for row in ew.observation_page(path=self.path)['observations']))

    def test_成果來源未來取得時間在整合流程仍被拒絕(self):
        self.publish()
        rows = closes()
        rows[0]['observedAt'] = '2027-01-01T00:00:00+00:00'
        self.publish(START + timedelta(days=2), market_history=rows)
        page = ew.observation_page(path=self.path)
        original = next(row for row in page['observations'] if row['signalId'] == 'TW_ATTACK_BUILDUP'
                        and row['originSession'] == DAYS[0])
        self.assertEqual(original['outcomes'][0]['status'], 'unknown')

    def test_少量樣本不提供命中率或宣稱可交易回測(self):
        record = pure_record(alert=True)
        outcomes = research.resolve(record, closes(close=103), '2026-09-10T11:00:00+00:00')
        result = research.summarize([record], {record['observationId']: outcomes}, '2026-09-10T11:00:00+00:00')
        for horizon in result['strata'][0]['horizons']:
            self.assertEqual(horizon['materialEvents'], 1)
            self.assertIsNone(horizon['falseAlertRatePct'])
            self.assertIsNone(horizon['populationMissRatePct'])
        self.assertFalse(result['tradableBacktest'])
        self.assertFalse(result['pointInTimeUniverseAvailable'])
        self.assertFalse(result['delistedUniverseAvailable'])


if __name__ == '__main__':
    unittest.main()
