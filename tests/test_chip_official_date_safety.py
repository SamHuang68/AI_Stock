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
