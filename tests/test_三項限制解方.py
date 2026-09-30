"""每日分階段留存與區段研究的真實失敗邊界；完全離線。"""
import json
import sqlite3
import sys
import tempfile
import unittest
import zlib
import io
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals as ss
import 台股交易參考 as ref
import 每日個股留存 as daily
import 個股還原研究 as adj
import datastore as ds
import 個股每日資料 as sources
import 個股研究維護 as maintenance
import chip_api
import chip_history_tracker as tracker


def series(n=200):
    end = datetime(2026, 9, 24, 15, tzinfo=ss._TZ['TW'])
    days, day = [], end
    while len(days) < n:
        if ref.session(day.date())['status'] != 'closed':
            days.append(day.date().isoformat())
        day -= timedelta(days=1)
    return [{'date': d, 'open': 100., 'high': 101., 'low': 99., 'close': 100., 'volume': 1000}
            for d in reversed(days)]


class SolutionTests(unittest.TestCase):
    def test_vendor_revision_preserves_original_and_deduplicates_by_date(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')):
            with closing(sqlite3.connect(ds.DB_PATH)) as c:
                c.executescript(ds.SCHEMA)
            stamp = int(datetime(2026, 9, 24, 9, tzinfo=ss._TZ['TW']).timestamp())
            original = (stamp, 100., 101., 99., 100., 1000.)
            ds.upsert_bars('2330', 'TW', [original])
            revised = (stamp + 3600, 90., 91., 89., 90., 1000.)
            result = ds.merge_source_bars('2330', 'TW', [revised], '本機測試來源')
            self.assertEqual(result['conflicts'], 1)
            self.assertEqual(ds.get_bars('2330'), [original])
            ds.merge_source_bars('2330', 'TW', [revised], '本機測試來源')
            self.assertEqual(ds.source_revision_status()['count'], 1)

    def test_official_batch_checks_own_date_ohlc_and_zero_volume(self):
        row = {'Date': '1150924', 'Code': '2330', 'OpeningPrice': '100', 'HighestPrice': '101',
               'LowestPrice': '99', 'ClosingPrice': '100', 'TradeVolume': '1,000'}
        values, absent = sources.parse_quotes([row], 'TWSE', '2026-09-24', {'2330'})
        self.assertEqual(values['2330'][-1], 1000)
        with self.assertRaises(ValueError):
            sources.parse_quotes([row], 'TWSE', '2026-09-29', {'2330'})
        self.assertEqual(sources.parse_quotes([{**row, 'TradeVolume': '0'}], 'TWSE', '2026-09-24', {'2330'})[1], ['2330'])

    def test_twse_all_market_includes_etf_and_rejects_wrong_or_ambiguous_payload(self):
        table = {'fields': ['證券代號', '成交股數', '開盤價', '最高價', '最低價', '收盤價'],
                 'data': [['00631L', '137,367,770', '39.10', '39.51', '38.94', '38.99']]}
        payload = {'stat': 'OK', 'date': '20260930', 'tables': [{'fields': ['指數'], 'data': []}, table]}
        values, absent = sources.parse_twse_market(payload, '2026-09-30', {'00631L'})
        self.assertEqual(values['00631L'][1:], (39.10, 39.51, 38.94, 38.99, 137367770))
        self.assertEqual(absent, [])
        for bad in ({**payload, 'date': '20260929'}, {**payload, 'stat': '尚無資料'},
                    {**payload, 'tables': [table, table]}, {**payload, 'tables': []}):
            with self.assertRaises(ValueError):
                sources.parse_twse_market(bad, '2026-09-30', {'00631L'})
        for data in ([table['data'][0], table['data'][0]], [['00631L']],
                     [['00631L', '100', '39', '38', '37', '39']]):
            with self.assertRaises(ValueError):
                sources.parse_twse_market({**payload, 'tables': [{**table, 'data': data}]}, '2026-09-30', {'00631L'})

    def test_confirmed_wiwynn_ratio_does_not_accept_obsolete_threefold_basis(self):
        import 個股還原研究 as adjusted
        from 台股交易參考 import split_references
        events = split_references('6669')
        official = 956
        row = {'rawClose': official / 2.9827946}
        self.assertIsNotNone(adjusted._basis_match({'date': '2021-06-22', 'close': official}, row, events)[0])
        self.assertIsNone(adjusted._basis_match({'date': '2021-06-22', 'close': official / 3}, row, events)[0])

    def test_tpex_chip_net_and_source_date_do_not_use_buy_quantity(self):
        row = {'Date': '1150924', 'SecuritiesCompanyCode': '6488',
               'ForeignInvestorsInclude MainlandAreaInvestors-Difference': '-4',
               'SecuritiesInvestmentTrustCompanies-TotalBuy': '999999',
               'SecuritiesInvestmentTrustCompanies-Difference': '0', 'Dealers-Difference': '1', 'TotalDifference': '-3'}
        got = chip_api.parse_tpex_inst([row], '20260924')['6488']
        self.assertEqual(got['trust'], 0)
        self.assertEqual(got['sourceDate'], '20260924')
        with self.assertRaises(ValueError):
            chip_api.parse_tpex_inst([row], '20260929')
        del row['SecuritiesInvestmentTrustCompanies-Difference']
        with self.assertRaises(ValueError):
            chip_api.parse_tpex_inst([row])

    def test_scheduled_sources_require_explicit_setting_and_have_bounded_slots(self):
        now = datetime(2026, 9, 29, 18, 35, tzinfo=ss._TZ['TW'])
        with tempfile.TemporaryDirectory() as tmp, patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                patch.object(maintenance.job_queue, 'submit', return_value={'queued': True}) as submit, \
                patch.object(maintenance, 'start_daemon'):
            self.assertFalse(maintenance.schedule_tick(now))
            submit.assert_not_called()
            maintenance.configure_schedule(True)
            self.assertTrue(maintenance.schedule_tick(now))
            self.assertFalse(maintenance.schedule_tick(now))
            self.assertTrue(maintenance.schedule_tick(now.replace(hour=19)))
            self.assertFalse(maintenance.schedule_tick(now.replace(hour=21)))
            maintenance.configure_schedule(False)
            self.assertFalse(maintenance.schedule_tick(now.replace(hour=20)))
    def test_suspension_has_explicit_end_and_does_not_mean_terminated(self):
        self.assertEqual(ref.trading_status('1441', '2026-09-24')['status'], 'suspended')
        self.assertIsNone(ref.trading_status('1441', '2026-09-29'))
        self.assertFalse(ref.eligible_bar('6550', '2026-09-18'))
        self.assertIsNone(ref.instrument('1441', '2026-09-29'))

    def test_partial_windows_keep_same_indices_and_do_not_bridge_source_gap(self):
        bars = series(220)
        snap = {'symbol': '2330', 'events': {}, 'rows': [
            {'date': b['date'], 'rawClose': b['close'], 'adjClose': 90} for i, b in enumerate(bars) if i != 110]}
        self.assertIsNone(adj.adjusted_bars(bars, snap))
        parts = adj.adjusted_segments(bars, snap, [b['date'] for b in bars])
        self.assertEqual([len(p['raw']) for p in parts], [110, 109])
        for part in parts:
            self.assertEqual([b['date'] for b in part['raw']], [b['date'] for b in part['adjusted']])
        self.assertEqual(bars[0]['close'], 100)
        # 即使基準也缺同一天，原始列的中斷證據仍不能被濾掉。
        parts = adj.adjusted_segments(bars, snap, [b['date'] for i, b in enumerate(bars) if i != 110])
        self.assertEqual([len(p['raw']) for p in parts], [110, 109])

    def test_chip_snapshot_concurrent_merges_preserve_every_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '20260924.json'
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda i: tracker._merge_snapshot(target, {str(i): {'trust': i}}), range(24)))
            self.assertEqual(len(json.loads(target.read_text(encoding='utf-8'))), 24)

    def test_daily_sources_retry_missing_rows_without_refetching_completed_sources(self):
        now = datetime(2026, 9, 29, 19, tzinfo=ss._TZ['TW'])
        twse = {'Date': '1150929', 'Code': '2330', 'OpeningPrice': '100', 'HighestPrice': '101',
                'LowestPrice': '99', 'ClosingPrice': '100', 'TradeVolume': '1000'}
        tpex = {'Date': '1150929', 'SecuritiesCompanyCode': '6488', 'Open': '100', 'High': '101',
                'Low': '99', 'Close': '100', 'TradingShares': '1000'}
        seen = []
        def respond(request, **kwargs):
            seen.append(request.full_url)
            rows = [twse, {**twse, 'Code': '2317', 'ClosingPrice': '--' if len(seen) < 3 else '100'}] if 'twse' in request.full_url else [tpex]
            if 'twse' in request.full_url:
                rows = {'stat': 'OK', 'date': '20260929', 'tables': [{
                    'fields': ['證券代號', '開盤價', '最高價', '最低價', '收盤價', '成交股數'],
                    'data': [[r[k] for k in ('Code', 'OpeningPrice', 'HighestPrice', 'LowestPrice', 'ClosingPrice', 'TradeVolume')] for r in rows]}]}
            return io.StringIO(json.dumps(rows))
        with tempfile.TemporaryDirectory() as tmp, patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                patch.object(sources, 'datetime') as clock, \
                patch.object(ds, 'list_symbols', return_value=['2330', '2317', '6488']), \
                patch.object(ds, 'merge_source_bars', return_value={'inserted': 1, 'unchanged': 0, 'conflicts': 0, 'excluded': 0}), \
                patch.object(ds, 'update', return_value=1), \
                patch.object(ds, 'last_ts', return_value=int(now.timestamp())), \
                patch.object(tracker, 'parse_and_save', return_value=2), \
                patch.object(tracker, 'parse_and_save_tpex', return_value=1), \
                patch.object(sources.urllib.request, 'urlopen', side_effect=respond):
            clock.now.return_value = now
            clock.fromisoformat.side_effect = datetime.fromisoformat
            first = sources.run()
            self.assertEqual(first['status'], 'partial')
            self.assertEqual(first['sources'][0]['result']['unavailableSymbols'], ['2317'])
            second = sources.run()
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(len(seen), 3)
            self.assertIn('reusedFromRun', second['sources'][1])

    def test_price_input_is_immutable_and_late_chips_have_separate_evidence(self):
        bars = series()
        now = datetime.fromisoformat(bars[-1]['date']).replace(hour=15, tzinfo=ss._TZ['TW'])
        price_event = {'signalId': 'mom_rsi_rebound', 'date': bars[-1]['date']}
        chip_event = {'signalId': 'chip_trust_buy3', 'date': bars[-1]['date']}
        def analyze(data, **kwargs):
            return {'events': [price_event] + ([chip_event] if kwargs.get('chips') else [])}
        with tempfile.TemporaryDirectory() as tmp, patch.object(ss, 'analyze', side_effect=analyze):
            ledger = Path(tmp) / '每日.sqlite3'
            daily.enable(ledger, now - timedelta(days=1))
            first = daily.capture(ledger, [('2330', bars)], bars, now=now)
            self.assertEqual(first['eventsAdded'], 1)
            self.assertEqual(first['status'], 'partial')
            with closing(sqlite3.connect(ledger)) as c:
                original = c.execute('SELECT payload FROM daily_inputs').fetchone()[0]
            chips = [{'date': b['date'], 'trust': 10 if i else 0, 'foreign': 0}
                     for i, b in enumerate(bars[-4:])]
            revised = [dict(b) for b in bars]
            revised[-1]['close'] = 200
            second = daily.capture(ledger, [('2330', revised)], bars, {'2330': chips}, now=now.replace(hour=19))
            self.assertEqual(second['eventsAdded'], 1)
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(second['chipChannelsComplete'], 2)
            self.assertEqual(daily.capture(ledger, [('2330', revised)], bars, {'2330': chips}, now=now.replace(hour=20))['eventsAdded'], 0)
            with closing(sqlite3.connect(ledger)) as c:
                self.assertEqual(c.execute('SELECT payload FROM daily_inputs').fetchone()[0], original)
                self.assertEqual(c.execute('SELECT count(*) FROM daily_chip_inputs').fetchone()[0], 2)
                self.assertEqual(json.loads(zlib.decompress(original))['bars'][-1]['close'], 100)

    def test_late_chips_cannot_backfill_previous_day_event(self):
        bars = series()
        now = datetime.fromisoformat(bars[-1]['date']).replace(hour=15, tzinfo=ss._TZ['TW'])
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / '每日.sqlite3'
            daily.enable(ledger, now - timedelta(days=1))
            daily.capture(ledger, [('2330', bars)], bars, now=now)
            chips = [{'date': b['date'], 'trust': 10 if i else 0, 'foreign': 0} for i, b in enumerate(bars[-4:])]
            with patch.object(ss, 'analyze') as analyze:
                daily.capture(ledger, [('2330', bars)], bars, {'2330': chips}, now=now + timedelta(days=1))
            analyze.assert_not_called()
            self.assertEqual(daily.status(ledger)['events'], 0)


if __name__ == '__main__':
    unittest.main()
