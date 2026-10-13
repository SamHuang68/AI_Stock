# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import benchmark_research as br  # noqa: E402


from tests.已核對資料 import 日曆資料, 交易日


def setUpModule():
    global _calendar_fixture
    _calendar_fixture = 日曆資料()
    _calendar_fixture.__enter__()


def tearDownModule():
    _calendar_fixture.__exit__(None, None, None)


class BenchmarkResearchTest(unittest.TestCase):
    def test_parses_official_openapi_roc_dates(self):
        rows = br.parse_tai50_payload([
            {'Date': '1150814', 'Taiwan50Index': '42,499.44',
             'Taiwan50TotalReturnIndex': '98,133.43'},
        ])
        self.assertEqual(rows, [{
            'date': '2026-08-14', 'priceIndex': 42499.44,
            'totalReturnIndex': 98133.43,
        }])

    def test_parses_historical_table_rows_and_rejects_invalid(self):
        rows = br.parse_tai50_payload({
            'tables': [{'data': [
                ['115/08/13', '42,785.23', '98,793.32'],
                ['bad-date', '0', '0'],
            ]}],
        })
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['date'], '2026-08-13')
        self.assertEqual(rows[0]['totalReturnIndex'], 98793.32)

    def test_atomic_cache_round_trip_and_ready_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'tai50_daily.csv')
            level = 10000.0
            rows = []
            start = date.today() - timedelta(days=1147)
            sessions = 交易日(start, 820)
            for index in range(820):
                level *= 1.003 if index % 2 else 0.998
                rows.append({
                    'date': sessions[index].isoformat(),
                    'priceIndex': level * 0.45,
                    'totalReturnIndex': level,
                })
            br._write_rows(rows, path)
            without_receipt = br.snapshot(allow_network=False, path=path)['FTSE_TAIWAN_50']
            self.assertEqual(without_receipt['quality'], 'partial_scope')
            br.atomic_write_json(str(path) + '.coverage.json', {
                'requestedStart': rows[0]['date'], 'failedMonths': {'2025-06': '合成來源失敗'}})
            failed_month = br.snapshot(allow_network=False, path=path)['FTSE_TAIWAN_50']
            self.assertEqual(failed_month['quality'], 'partial_scope')
            self.assertFalse(failed_month['coverage']['continuous'])
            br.atomic_write_json(str(path) + '.coverage.json', {'requestedStart': rows[0]['date'], 'failedMonths': {}})
            loaded = br._read_rows(path)
            self.assertEqual(len(loaded), 820)
            contract = br.snapshot(allow_network=False, path=path)['FTSE_TAIWAN_50']
            self.assertEqual(contract['quality'], 'ready')
            self.assertTrue(contract['pointInTimeAudited'])
            self.assertEqual(contract['sampleDays'], 820)

    def test_partial_cache_fails_closed_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'tai50_daily.csv')
            br._write_rows([{
                'date': date.today().isoformat(),
                'priceIndex': 100.0, 'totalReturnIndex': 200.0,
            }], path)
            contract = br.snapshot(allow_network=False, path=path)['FTSE_TAIWAN_50']
            self.assertEqual(contract['quality'], 'partial_scope')
            self.assertEqual(contract['sampleDays'], 1)


if __name__ == '__main__':
    unittest.main()
