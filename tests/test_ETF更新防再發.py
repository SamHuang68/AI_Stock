"""ETF 更新 8D 防再發：休市、來源證據、失敗隔離及訊號可比性。"""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import uuid
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import etf_paths
import etf_delta_tracker as tracker
import etf_api
import ETF更新診斷 as diagnostics

DAY = dt.date(2026, 9, 29)
ROW = {'code': '2330', 'market': 'TW', 'name': '台積電', 'weight': 20, 'shares': 1000}


def snapshot(day, *, provider='2026-09-24', count=84, expected=130):
    codes = [f'{i:05d}' for i in range(expected)]
    data = {'date': day.isoformat()}
    for code in codes[:count]:
        data[code] = {'date': provider, 'source': 'moneydj-full', 'holdings': [dict(ROW)]}
    data['meta'] = {'expectedCodes': codes, 'expectedCount': expected,
                    'succeededCodes': codes[:count], 'succeededCount': count,
                    'failedCodes': codes[count:], 'successRatio': round(count / expected, 4),
                    'catalogFingerprint': etf_paths.catalog_fingerprint(codes)}
    return data


class CalendarRegression(unittest.TestCase):
    def test_holiday_case_and_genuinely_stale_remain_distinct(self):
        data = snapshot(DAY)
        for provider, fresh, accepted in [('2026-09-24', 1, True), ('2026-09-23', 2, True),
                                          ('2026-09-22', 3, False)]:
            with self.subTest(provider=provider):
                for code in data['meta']['succeededCodes']:
                    data[code]['date'] = provider
                self.assertEqual(etf_paths.business_day_age(dt.date.fromisoformat(provider), DAY), fresh)
                check = etf_paths.inspect_snapshot_payload(data, expected_date=DAY)
                result = etf_paths.snapshot_acceptance(check, today=DAY,
                    expected_codes=data['meta']['expectedCodes'], previous_etf_count=84)
                self.assertEqual(result['minimumEtfCount'], 78)
                self.assertEqual(result['accepted'], accepted)
                self.assertEqual(result['calendar']['basis'], 'twse_calendar')

    def test_temporary_closure_unknown_year_and_future_guard(self):
        self.assertEqual(etf_paths.business_day_age(dt.date(2026, 7, 9), dt.date(2026, 7, 13)), 1)
        info = etf_paths.freshness_calendar([dt.date(2025, 12, 31)], DAY)
        self.assertEqual(info['unknownYears'], [2025])
        self.assertIn('fallback', info['basis'])
        data = snapshot(DAY, provider='2026-09-30')
        result = etf_paths.snapshot_acceptance(
            etf_paths.inspect_snapshot_payload(data, expected_date=DAY), today=DAY)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['state'], 'future')

    def test_history_health_uses_same_holiday_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            for day in (dt.date(2026, 9, 24), dt.date(2026, 9, 28)):
                path = Path(temp) / f'top10_active_etf_holdings_{day}.json'
                path.write_text(json.dumps(snapshot(day)), encoding='utf-8')
            result = etf_paths.history_status(temp, today=DAY)
        self.assertTrue(result['healthy'])
        self.assertEqual(result['providerFreshCount'], 84)
        self.assertEqual(result['providerMaxBusinessDayAge'], 1)


class SourceRegression(unittest.TestCase):
    def test_inverse_contract_and_undisclosed_bond_quantity(self):
        body = '''資料日期：2026/09/24
        <tr><td class="col05"><a href="/etf/ea/ETZCW.djhtm?c=1&etfid=FITXN*1.TF&back=00632R.TW">臺股期貨 202610(FITXN*1.TF)</a></td><td class="col06">99.10</td><td class="col07">-2,660</td></tr>
        <tr><td class="col05">US TREASURY 4.75% 05/15/2055</td><td class="col06">5.42</td><td class="col07">N/A</td></tr>'''
        with mock.patch.object(tracker, 'http_get', return_value=body):
            rows, day = tracker.fetch_moneydj_full('00632R')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['shares'], -2660)
        self.assertIsNone(rows[1]['shares'])
        self.assertTrue(all(r['market'] == 'ASSET' for r in rows))

    def test_linked_stock_is_not_duplicated_as_named_asset(self):
        body = '''資料日期：2026/09/24
        <tr><td class="col05"><a href="/etf/ea/ETZCW.djhtm?etfid=2330.TW&back=0050.TW">台積電(2330.TW)</a></td><td class="col06">20.0</td><td class="col07">1,000</td></tr>'''
        with mock.patch.object(tracker, 'http_get', return_value=body):
            rows, _ = tracker.fetch_moneydj_full('0050')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], '2330')

    def test_non_stock_holding_retains_name_date_quantity_without_fake_ticker(self):
        body = '''資料日期：2026/09/23
        <tr><td class="col05">202611 黃豆期貨</td><td class="col06">100.03</td>
        <td class="col07">732</td></tr>'''
        with mock.patch.object(tracker, 'http_get', return_value=body):
            for fetch in (tracker.fetch_moneydj_full, tracker.fetch_moneydj_top):
                rows, day = fetch('00693U')
                self.assertEqual(day, '2026-09-23')
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['code'], 'asset:202611 黃豆期貨')
                self.assertEqual(rows[0]['market'], 'ASSET')
                self.assertEqual(rows[0]['shares'], 732)
                self.assertEqual(rows[0]['weight'], 100.03)

    def test_unusable_primary_dates_try_fallback(self):
        for primary_date in (None, '日期未知', '2026-09-18', '2026-09-30'):
            with self.subTest(primary_date=primary_date), \
                 mock.patch.object(tracker, 'fetch_moneydj_full', return_value=([ROW], primary_date)), \
                 mock.patch.object(tracker, 'fetch_moneydj_top', return_value=([ROW], '2026-09-24')), \
                 mock.patch.object(tracker, 'fetch_twse') as last:
                rows, date, source = tracker.fetch_one('0050', DAY)
                self.assertEqual((date, source), ('2026-09-24', 'moneydj-top10'))
                last.assert_not_called()

    def test_twse_uses_response_date_and_complete_fund_code(self):
        for provider, expected in [('20260923', '2026-09-23'), ('2026-09-24', '2026-09-24'), ('', None)]:
            payload = {'stat': 'OK', 'date': provider, 'fields': ['代號', '名稱', '股數', '比例'],
                       'data': [['2330', '台積電', '1000', '20']]}
            with mock.patch.object(tracker, 'http_get', return_value=json.dumps(payload)) as fetch:
                rows, date = tracker.fetch_twse('00693U', DAY)
                self.assertEqual(date, expected)
                self.assertIn('stockNo=00693U', fetch.call_args.args[0])

    def test_latest_source_cannot_create_historical_backfill(self):
        with mock.patch.object(tracker, 'run') as run:
            self.assertFalse(tracker.backfill(5))
            run.assert_not_called()


class ComparisonRegression(unittest.TestCase):
    def compare(self, previous, current):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / f'top10_active_etf_holdings_{day}.json'
                     for day in ('2026-09-24', '2026-09-29')]
            for path, data in zip(paths, (previous, current)):
                path.write_text(json.dumps(data), encoding='utf-8')
            with mock.patch.object(etf_api, 'ETF_CATALOG_FILE', str(Path(temp) / 'missing')):
                return etf_api.compute_etf_delta([str(p) for p in paths])

    def entry(self, **kwargs):
        return {'date': '2026-09-24', 'source': 'moneydj-full', 'holdings': [dict(ROW)], **kwargs}

    def test_missing_fund_does_not_mean_entry_or_liquidation(self):
        for previous, current, reason in [({'0050': self.entry()}, {}, 'current_missing'),
                                           ({}, {'0050': self.entry()}, 'previous_missing')]:
            out = self.compare(previous, current)
            fund = out['etfs'][0]
            self.assertEqual(out['summary'], {'new': 0, 'removed': 0, 'changed': 0})
            self.assertEqual(fund['comparison']['state'], reason)
            if reason == 'current_missing':
                self.assertEqual(fund['previousTop10'][0]['code'], '2330')

    def test_scope_date_and_parser_changes_are_not_trading_signals(self):
        previous = {'0050': self.entry(date='2026-09-23')}
        cases = [(self.entry(source='moneydj-top10'), 'limited_scope'),
                 (self.entry(source='twse'), 'source_changed'),
                 (self.entry(date='2026-09-23'), 'same_source_date'),
                 (self.entry(date=None), 'unknown_source_date'),
                 (self.entry(date='2026-09-22'), 'invalid_source_order'),
                 (self.entry(holdingsSchema=2, holdings=[dict(ROW, code='asset:黃豆期貨',
                                      instrumentType='named_asset')]), 'schema_changed')]
        for current, reason in cases:
            with self.subTest(reason=reason):
                out = self.compare(previous, {'0050': current})
                self.assertEqual(out['etfs'][0]['comparison']['state'], reason)
                self.assertEqual(out['summary'], {'new': 0, 'removed': 0, 'changed': 0})

    def test_equal_ticker_in_different_markets_is_not_one_security(self):
        previous = {'0050': self.entry(date='2026-09-23')}
        current = {'0050': self.entry(holdings=[dict(ROW, market='US')])}
        fund = self.compare(previous, current)['etfs'][0]
        self.assertEqual(fund['new'][0]['market'], 'US')
        self.assertEqual(fund['removed'][0]['market'], 'TW')


class ReceiptRegression(unittest.TestCase):
    def test_timeout_and_start_failure_survive_service_restart(self):
        import etf_routes
        class Handler(etf_routes.EtfRoutesMixin):
            def _ok(self, body):
                self.response = json.loads(body)
        for error, code in [(subprocess.TimeoutExpired('tracker', 300, output=b'partial'), -2),
                             (OSError('fixture'), -3)]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp, \
                 mock.patch.dict(os.environ, {etf_paths.ENV_HISTORY_DIR: temp}), \
                 mock.patch.object(etf_api, '_tracker_state', {'runId': uuid.uuid4().hex}), \
                 mock.patch.object(etf_api.subprocess, 'run', side_effect=error):
                diagnostics.UpdateTrace().finish(accepted=True, state='updated')
                etf_api._run_tracker_async()
                latest = diagnostics.latest_report()
                self.assertFalse(latest['accepted'])
                self.assertEqual(latest['errorCode'], code)
                self.assertEqual(etf_api._tracker_state['lastReturnCode'], code)
                etf_api._tracker_state = {'runId': None, 'running': False}
                handler = Handler()
                handler._handle_tracker_status()
                self.assertEqual(handler.response['lastReturnCode'], code)
                self.assertEqual(handler.response['runId'], latest['runId'])

    def test_accepted_partial_snapshot_retries_only_failed_funds(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {etf_paths.ENV_HISTORY_DIR: temp}), \
             mock.patch.object(tracker, 'ETFS', {f'{i:05d}': (f'{i:05d}', '測試') for i in range(12)}), \
             mock.patch.object(tracker, 'fetch_one', return_value=([ROW], '2026-09-24', 'fixture')) as fetch:
            path = Path(temp) / f'top10_active_etf_holdings_{DAY}.json'
            original = snapshot(DAY, count=10, expected=12)
            path.write_text(json.dumps(original), encoding='utf-8')
            self.assertTrue(tracker.run(DAY))
            self.assertEqual({call.args[0] for call in fetch.call_args_list}, {'00010', '00011'})
            current = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(current['00000'], original['00000'])
            self.assertEqual(current['meta']['succeededCount'], 12)
            self.assertTrue(list(Path(temp).glob('*.previous-*')))

    def test_rejection_persists_evidence_and_preserves_old_snapshot(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {etf_paths.ENV_HISTORY_DIR: temp}), \
             mock.patch.object(tracker, 'ETFS', {f'{i:05d}': (f'{i:05d}', '測試') for i in range(10)}), \
             mock.patch.object(tracker, 'fetch_one', return_value=([ROW], '2026-09-18', 'fixture')):
            path = Path(temp) / f'top10_active_etf_holdings_{DAY}.json'
            original = json.dumps(snapshot(DAY, provider='2026-09-18', count=10, expected=10))
            path.write_text(original, encoding='utf-8')
            self.assertFalse(tracker.run(DAY))
            self.assertEqual(path.read_text(encoding='utf-8'), original)
            report = diagnostics.latest_report()
            self.assertEqual(report['state'], 'stale')
            self.assertEqual(report['providerDateCounts'], {'2026-09-18': 10})
            self.assertEqual(report['acceptance']['providerFreshCount'], 0)
            trace = (diagnostics.run_directory() / (report['runId'] + '.jsonl')).read_text(encoding='utf-8')
            events = [json.loads(line)['event'] for line in trace.splitlines()]
            self.assertEqual(events.count('etf_result'), 10)
            self.assertIn('candidate_checked', events)
            self.assertEqual(events[-1], 'terminal_fail')


if __name__ == '__main__':
    unittest.main()
