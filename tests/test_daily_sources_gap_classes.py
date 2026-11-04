"""個股每日資料的缺口分類：官方明示停止交易、久未成交（推論）與真缺口；完全離線。

起因：2026-11-03 盤後 TWSE／TPEx 兩列日線仍是 partial，原因是 6 個不在官方當日檔的代號
（3 檔櫃買官方標示停止交易、3 檔已久未成交）；原設計把它們一律當缺口，狀態因此幾乎不帶訊號。"""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import chip_history_tracker as tracker
import datastore as ds
import http_client
import stock_signals as ss
import 個股還原研究 as adj
import 個股每日資料 as sources

DAY = '2026-09-29'      # 週二；09-25 中秋與 09-28 教師節休市
NOW = datetime(2026, 9, 29, 19, tzinfo=ss._TZ['TW'])


def stamp(day):
    return int(datetime.fromisoformat(day).replace(hour=9, tzinfo=ss._TZ['TW']).timestamp())


def twse_market(codes):
    return {'stat': 'OK', 'date': '20260929', 'tables': [{
        'fields': ['證券代號', '開盤價', '最高價', '最低價', '收盤價', '成交股數'],
        'data': [[code, '100', '101', '99', '100', '1000'] for code in codes]}]}


def tpex_quotes(codes):
    return [{'Date': '1150929', 'SecuritiesCompanyCode': code, 'Open': '100', 'High': '101', 'Low': '99',
             'Close': '100', 'TradingShares': '1000'} for code in codes]


def tpex_cmode(halted):
    return [{'Date': '1150929', 'SecuritiesCompanyCode': code, 'SuspensionOfTrading': 'Ｙ' if code in halted else ''}
            for code in ('2067', *sorted(halted))]


class ParseSuspensionTests(unittest.TestCase):
    def test_tpex_marks_only_rows_with_suspension_flag(self):
        self.assertEqual(sources.parse_suspensions(tpex_cmode({'4207', '5355'}), 'TPEx', DAY), {'4207', '5355'})

    def test_twse_halt_window_matches_resume_date_meaning(self):
        rows = [{'Code': '1218', 'TradingHaltDate': '1150813', 'TradingResumptionDate': '1150814'},
                {'Code': '2002', 'TradingHaltDate': '1150928', 'TradingResumptionDate': ''},
                {'Code': '2003', 'TradingHaltDate': '1150930', 'TradingResumptionDate': '1151001'}]
        parse = lambda day: sources.parse_suspensions(rows, 'TWSE', day)
        self.assertEqual(parse('2026-08-13'), {'1218'})
        self.assertEqual(parse('2026-08-14'), set())          # 恢復日當天已可交易
        self.assertEqual(parse(DAY), {'2002'})                 # 沒有恢復日＝尚未恢復；未來才暫停的不算

    def test_untrusted_shapes_are_rejected_not_guessed(self):
        with self.assertRaises(ValueError):
            sources.parse_suspensions({'rows': []}, 'TPEx', DAY)
        with self.assertRaises(ValueError):
            sources.parse_suspensions([{**row, 'Date': '1150928'} for row in tpex_cmode({'4207'})], 'TPEx', DAY)
        with self.assertRaises(ValueError):
            sources.parse_suspensions([{'Code': '1218', 'TradingResumptionDate': '1150814'}], 'TWSE', DAY)

    def test_one_failed_list_is_reported_and_the_other_still_counts(self):
        def respond(url, **kwargs):
            if 'TWTAWU' in url:
                raise http_client.HttpError('boom', url=url)
            return tpex_cmode({'4207'})
        with patch.object(sources.http_client, 'fetch_json', side_effect=respond):
            halted, lists = sources.official_suspensions(DAY)
        self.assertEqual(halted, {'4207'})
        self.assertEqual(lists['TWSE']['status'], 'failed')
        self.assertEqual(lists['TPEx'], {'status': 'ok', 'source': sources.SUSPENSION_SOURCES['TPEx'], 'halted': 1})

    def test_stale_tpex_list_is_not_trusted_as_todays(self):
        stale = [{**row, 'Date': '1150928'} for row in tpex_cmode({'4207'})]
        with patch.object(sources.http_client, 'fetch_json', side_effect=lambda url, **kw: [] if 'TWTAWU' in url else stale):
            halted, lists = sources.official_suspensions(DAY)
        self.assertEqual(halted, set())
        self.assertEqual(lists['TPEx']['status'], 'failed')


class BarsDbCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'market.db'
        patcher = patch.object(ds, 'DB_PATH', str(self.db))
        patcher.start()
        self.addCleanup(patcher.stop)
        ds.init_db()

    def add_bars(self, bars):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executemany('INSERT INTO bars(symbol,market,ts,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?,?)',
                             [(code, 'TW', stamp(day), 10, 10, 10, 10, volume) for code, day, volume in bars])


class InactiveGapTests(BarsDbCase):
    def test_last_traded_ts_ignores_zero_volume_padding(self):
        self.add_bars([('8183', '2026-09-11', 1000), ('8183', '2026-09-23', 0), ('8183', '2026-09-24', 0), ('7777', '2026-09-24', 0)])
        self.assertEqual(ds.last_traded_ts('8183'), stamp('2026-09-11'))
        self.assertIsNone(ds.last_traded_ts('7777'))
        self.assertIsNone(ds.last_traded_ts('6666'))

    def test_session_count_skips_weekends_and_closed_days(self):
        self.assertEqual(sources.sessions_since('2026-09-11', DAY), 10)    # 09-25、09-28 休市不計
        self.assertEqual(sources.sessions_since('2026-09-14', DAY), 9)
        self.assertEqual(sources.sessions_since('2026-09-24', DAY), 1)

    def test_threshold_is_inclusive_and_missing_evidence_is_not_inferred(self):
        self.add_bars([('8183', '2026-09-11', 1000), ('8183', '2026-09-24', 0),     # 剛好 10 個交易日
                       ('1522A', '2026-09-14', 1000),                                # 9 個，差一天
                       ('7777', '2026-09-24', 0)])                                   # 只有零量列：沒有成交證據
        found = sources.inactive_gaps(['8183', '1522A', '7777', '6666'], DAY)
        self.assertEqual(found, [{'symbol': '8183', 'lastTradeDate': '2026-09-11', 'sessionsSince': 10}])

    def test_unreadable_database_infers_nothing(self):
        self.db.unlink()
        for suffix in ('-wal', '-shm'):
            Path(str(self.db) + suffix).unlink(missing_ok=True)
        self.assertEqual(sources.inactive_gaps(['8183'], DAY), [])


class RunClassificationTests(BarsDbCase):
    BARS = [('4207', '2026-09-24', 1000),                                           # 官方停止交易（最近才停）
            ('8183', '2026-09-11', 1000), ('8183', '2026-09-23', 0), ('8183', '2026-09-24', 0),   # 久未成交
            ('1522A', '2026-09-14', 1000)]                                          # 差一天，仍是缺口

    def run_sources(self, symbols, *, halted=(), lists_fail=False):
        self.add_bars(self.BARS)
        seen = []

        def respond(url, **kwargs):
            seen.append(url)
            if 'MI_INDEX' in url:
                return twse_market(['2330'])
            if 'tpex_mainboard' in url:
                return tpex_quotes(['6488'])
            if lists_fail:
                raise http_client.HttpError('boom', url=url)
            return [] if 'TWTAWU' in url else tpex_cmode(set(halted))
        with patch.object(sources, 'datetime') as clock, \
                patch.object(ds, 'list_symbols', return_value=symbols), \
                patch.object(ds, 'merge_source_bars', return_value={'inserted': 1, 'unchanged': 0, 'conflicts': 0, 'excluded': 0}), \
                patch.object(ds, 'update', return_value=1), patch.object(ds, 'last_ts', return_value=int(NOW.timestamp())), \
                patch.object(tracker, 'parse_and_save', return_value=2), patch.object(tracker, 'parse_and_save_tpex', return_value=1), \
                patch.object(adj, 'refresh_snapshots', return_value={'status': 'completed', 'pendingSymbols': [], 'results': {}}), \
                patch.object(sources.http_client, 'fetch_json', side_effect=respond):
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
            return sources.run(), seen

    def test_explained_gaps_no_longer_downgrade_the_quote_rows(self):
        state, _ = self.run_sources(['2330', '6488', '4207', '8183'], halted={'4207'})
        self.assertEqual(state['suspendedSymbols'], ['4207'])
        self.assertEqual(state['inactiveSymbols'], [{'symbol': '8183', 'lastTradeDate': '2026-09-11', 'sessionsSince': 10}])
        self.assertEqual(state['unconfirmedSymbols'], [])
        self.assertEqual([row['status'] for row in state['sources'][:2]], ['completed', 'completed'])
        self.assertEqual(state['status'], 'completed')
        self.assertEqual({k: v['status'] for k, v in state['suspensionLists'].items()}, {'TWSE': 'ok', 'TPEx': 'ok'})

    def test_unexplained_gaps_still_downgrade_and_stay_visible(self):
        # 1522A 只差一天、9999 沒有任何成交紀錄：都沒有理由說明為何不在官方檔，維持缺口。
        state, _ = self.run_sources(['2330', '6488', '4207', '8183', '1522A', '9999'], halted={'4207'})
        self.assertEqual(state['unconfirmedSymbols'], ['1522A', '9999'])
        self.assertEqual([row['status'] for row in state['sources'][:2]], ['partial', 'partial'])
        self.assertEqual(state['sources'][0]['result']['unconfirmedSymbols'], ['1522A', '9999'])
        self.assertEqual(state['suspendedSymbols'], ['4207'])
        self.assertEqual([item['symbol'] for item in state['inactiveSymbols']], ['8183'])

    def test_failed_suspension_lists_keep_the_original_partial_behavior(self):
        state, _ = self.run_sources(['2330', '6488', '4207', '8183'], lists_fail=True)
        self.assertEqual(state['suspendedSymbols'], [])
        self.assertEqual(state['unconfirmedSymbols'], ['4207'])          # 沒有官方清單佐證，不放寬
        self.assertEqual([item['symbol'] for item in state['inactiveSymbols']], ['8183'])   # 這一類不依賴清單
        self.assertEqual({v['status'] for v in state['suspensionLists'].values()}, {'failed'})
        self.assertEqual([row['status'] for row in state['sources'][:2]], ['partial', 'partial'])

    def test_healthy_day_makes_no_extra_requests(self):
        state, seen = self.run_sources(['2330', '6488'])
        self.assertEqual(len(seen), 2)
        self.assertEqual((state['suspendedSymbols'], state['inactiveSymbols'], state['unconfirmedSymbols']), ([], [], []))
        self.assertNotIn('suspensionLists', state)


if __name__ == '__main__':
    unittest.main()
