import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import chip_api as chip
import chip_history_tracker as history
import tw_index_charts as twc


class TestChipOfficialDateSafety(unittest.TestCase):
    def test_no_official_t86_does_not_claim_today(self):
        with mock.patch.object(chip, 'snap_t86', return_value=None):
            self.assertEqual(chip.resolve_t86_date(2), (None, None))

    def test_lookup_uses_taipei_calendar_day(self):
        with mock.patch.object(chip, 'taipei_today', return_value=date(2026, 10, 1)), \
                mock.patch.object(chip, 'snap_t86', return_value={'2330': {}}) as fetch:
            self.assertEqual(chip.resolve_t86_date()[0], '20261001')
        fetch.assert_called_once_with('20261001')

    def test_tpex_rejects_future_and_invalid_source_dates(self):
        row = {'Date': '20261002', 'SecuritiesCompanyCode': '3529',
               'ForeignInvestorsInclude MainlandAreaInvestors-Difference': '1',
               'SecuritiesInvestmentTrustCompanies-Difference': '2',
               'Dealers-Difference': '3', 'TotalDifference': '6'}
        with mock.patch.object(chip, 'taipei_today', return_value=date(2026, 10, 1)):
            for day in ('20261002', '20260230', 'bad20261001'):
                with self.subTest(day=day), self.assertRaises(ValueError):
                    chip.parse_tpex_inst([{**row, 'Date': day}])

    def test_history_taipei_boundary_and_future_guard(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(history, 'taipei_today', return_value=date(2026, 10, 1)):
            payload = {'date': '20261001', '_verifiedChipDate': '20261001',
                       '_chipSource': 'TWSE', 'inst': {'total': 3, 'trust': 1}}
            self.assertTrue(history.record_snapshot('2330', payload, folder))
            self.assertTrue(os.path.isfile(os.path.join(folder, '20261001.json')))
            self.assertFalse(history.record_snapshot('2330', {
                **payload, 'date': '20261002', '_verifiedChipDate': '20261002'}, folder))

    def test_scheduler_rejects_future_before_network(self):
        with mock.patch.object(history, 'taipei_today', return_value=date(2026, 10, 1)), \
                mock.patch.object(history, 'fetch_t86') as fetch:
            with self.assertRaises(ValueError):
                history.parse_and_save('20261002')
        fetch.assert_not_called()

    def test_official_otc_quote_never_substitutes_today(self):
        with mock.patch.object(twc, 'taipei_today', return_value=date(2026, 10, 1)):
            for day in ('', 'bad20261001', '20260230', '20261002'):
                with self.subTest(day=day), mock.patch.object(twc, '_http_json', return_value={
                    'msgArray': [{'z': '100', 'y': '99', 'd': day}]}):
                    self.assertIsNone(twc._live_twoii_close())
            with mock.patch.object(twc, '_http_json', return_value={
                'msgArray': [{'z': '100', 'y': '99', 'd': '20260930'}]}):
                self.assertEqual(twc._live_twoii_close()[0], '2026-09-30')


class TestChipSideBlocksDateSafety(unittest.TestCase):
    def setUp(self):
        chip._SNAP.clear()

    def tearDown(self):
        chip._SNAP.clear()

    def _margn(self, date_field):
        body = {'stat': 'OK', 'tables': [{'fields': ['代號', '今日餘額', '今日餘額'], 'data': [['2330', '10', '2']]}]}
        if date_field is not None:
            body['date'] = date_field
        return body

    def test_margin_block_rejects_response_that_states_another_day(self):
        with mock.patch.object(chip, '_fetch_json', return_value=self._margn('20260930')):
            self.assertIsNone(chip.snap_margn('20261001'))

    def test_margin_block_accepts_matching_or_undated_response(self):
        # 只擋「明確說是另一天」的回應；上游少了 date 欄不能讓整塊籌碼消失。
        for body in (self._margn('20261001'), self._margn(None)):
            chip._SNAP.clear()
            with self.subTest(date=body.get('date')), mock.patch.object(chip, '_fetch_json', return_value=body):
                self.assertIn('2330', chip.snap_margn('20261001'))

    def test_short_lending_and_daytrade_reject_other_day(self):
        lend = {'stat': 'OK', 'date': '20260930', 'fields': ['證券代號', '本日借券餘額股'], 'data': [['2330', '5']]}
        with mock.patch.object(chip, '_fetch_json', return_value=lend):
            self.assertIsNone(chip.snap_twt72u('20261001'))
        rows = [[str(1000 + i), '1', '1'] for i in range(12)]
        dayt = {'stat': 'OK', 'date': '20260930',
                'fields': ['證券代號', '當日沖銷交易成交股數', '當日沖銷交易比率'], 'data': rows}
        with mock.patch.object(chip, '_fetch_json', return_value=dayt):
            self.assertIsNone(chip.snap_twtb4u('20261001'))

    def test_build_chip_without_official_date_does_not_query_side_blocks_for_today(self):
        # 過去：T86 與 TPEx 都找不到官方日時，仍以「今天」去查融資券／借券／當沖，
        # 掛在一份 date=None 的回應上，看起來像今天的資料。
        with mock.patch.object(chip, 'taipei_today', return_value=date(2026, 10, 1)), \
                mock.patch.object(chip, 'resolve_t86_date', return_value=(None, None)), \
                mock.patch.object(chip, '_tpex_inst', return_value=None), \
                mock.patch.object(chip, 'snap_margn') as margn, \
                mock.patch.object(chip, 'snap_twt72u') as lend, \
                mock.patch.object(chip, 'snap_twtb4u') as dayt:
            out = chip.build_chip('2330')
        self.assertIsNone(out['date'])
        for fetch in (margn, lend, dayt):
            fetch.assert_not_called()
        self.assertIsNone(out['margin'])
        self.assertNotIn('shortLend', out)
        self.assertNotIn('dayTrade', out)
