"""既有資料更新的缺口、來源日期、零值與保留契約。"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore as ds
import chip_api as ca
import chip_history_tracker as ct
import touxin_ledger as tl


class UpdateTests(unittest.TestCase):
    def test_live_lookup_saves_source_date_and_preserves_known_value(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / '20260924.json'
            p.write_text('{"2330":{"trust":1000,"custom":7}}', encoding='utf-8')
            payload = {'date': '20260924', '_chipSource': 'TWSE', '_verifiedChipDate': '20260924',
                       'inst': {'foreign': 20, 'trust': None, 'dealer': 0, 'total': 20}}
            self.assertTrue(ct.record_snapshot('2330', payload, root))
            saved = json.loads(p.read_text(encoding='utf-8'))['2330']
            self.assertEqual(saved['sourceDate'], '2026-09-24')
            self.assertEqual(saved['trust'], 1000)
            self.assertEqual(saved['custom'], 7)
            self.assertFalse(ct.record_snapshot('6488', {**payload, '_chipSource': 'TPEx', '_verifiedChipDate': None}, root))
            self.assertFalse(ct.record_snapshot('2330', {**payload, 'date': '20260926'}, root))
            self.assertEqual(len(list(Path(root).glob('*.json'))), 1)

    def test_stale_benchmark_fetches_enough_history(self):
        row = (int(time.time()) - 86400, 10, 11, 9, 10, 100)
        with patch.object(ds, 'last_ts', return_value=time.time() - 95 * 86400), \
                patch.object(ds, 'fetch_yahoo_daily', return_value=[row]) as fetch, \
                patch.object(ds, 'upsert_bars', return_value=1):
            self.assertEqual(ds.update('^TWII'), 1)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args, ('^TWII', 'TW', '6mo'))
        # 之後可稽核每一筆新增的 Yahoo 日線：必須要求收據字典，並與寫入共用同一份。
        self.assertIsInstance(fetch.call_args.kwargs.get('receipt_out'), dict)
        self.assertEqual(set(fetch.call_args.kwargs), {'receipt_out'})

    def test_full_benchmark_rebuild_writes_with_the_receipt_of_its_own_fetch(self):
        import importlib.util
        root_dir = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('research_update_script', root_dir / 'scripts' / '個股研究資料更新.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        row = (int(time.time()) - 5 * 86400, 10, 11, 9, 10, 100)
        written = {}

        def fetch(symbol, market, period, **kwargs):
            kwargs['receipt_out'].update({'receiptId': 'a' * 32})
            return [row]

        def write(symbol, market, rows, **kwargs):
            written.update(kwargs)
            return len(rows)

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ds, 'DB_PATH', ds.DB_PATH), patch.object(ct, 'CHIP_HISTORY_PATH', ct.CHIP_HISTORY_PATH), \
                patch.object(ds, 'fetch_yahoo_daily', side_effect=fetch) as fetched, \
                patch.object(ds, 'upsert_bars', side_effect=write), patch.object(ds, 'last_ts', return_value=0):
            data = Path(folder) / 'data'
            data.mkdir()
            (data / 'market.db').write_bytes(b'')
            # 2026-10-10 是週六：不會進入籌碼逐日更新迴圈。
            script.main(['--start', '2026-10-10', '--end', '2026-10-10', '--benchmark-range', '10y',
                         '--data-dir', str(data)])
        receipt = fetched.call_args.kwargs['receipt_out']
        self.assertEqual(receipt['receiptId'], 'a' * 32)
        self.assertIs(written['ingest_receipt'], receipt)
        self.assertEqual(written['source'], 'Yahoo Finance')

    def test_snapshot_merges_fields_and_zero_reaches_ledger(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'data' / 'chip_history'
            folder.mkdir(parents=True)
            fn = folder / '20260924.json'
            fn.write_text(json.dumps({'2330': {'custom': 7}, '6488': {'trust': 12}}), encoding='utf-8')
            body = {'stat': 'OK', 'date': '20260924',
                    'fields': ['證券代號', '投信買賣超股數', '三大法人買賣超股數',
                               '外陸資買賣超股數', '自營商買賣超股數'],
                    'data': [['2330', '0', '100', '100', '0']]}
            with patch.object(ct, 'CHIP_HISTORY_PATH', str(folder)), patch.object(ct, 'fetch_t86', return_value=body):
                self.assertEqual(ct.parse_and_save('20260924'), 1)
            got = json.loads(fn.read_text(encoding='utf-8'))
            self.assertEqual(got['2330']['trust'], 0)
            self.assertEqual(got['2330']['custom'], 7)
            self.assertEqual(got['2330']['sourceDate'], '2026-09-24')
            self.assertEqual(got['6488']['trust'], 12)
            import sqlite3
            with closing(sqlite3.connect(Path(root) / 'data/touxin_ledger/touxin_ledger.db')) as conn:
                self.assertEqual(conn.execute("SELECT trust_net_shares FROM touxin_daily WHERE symbol='2330'").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM touxin_daily WHERE symbol='6488'").fetchone()[0], 0)

    def test_wrong_source_day_refuses_before_write(self):
        with tempfile.TemporaryDirectory() as root, patch.object(ct, 'CHIP_HISTORY_PATH', root), \
                patch.object(ct, 'fetch_t86', return_value={'stat': 'OK', 'date': '20260923', 'data': [['2330', 1]]}):
            with self.assertRaises(ValueError):
                ct.parse_and_save('20260924')
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_nonfinite_source_is_missing(self):
        self.assertIsNone(ca._num('NaN'))
        self.assertIsNone(ca._num('inf'))
        self.assertEqual(ca._num('0'), 0)
        self.assertIsNone(ca._t86_dealer(['自營商買賣超股數(自行買賣)'], ['100']))

    def test_incomplete_response_preserves_existing_snapshot(self):
        for source_day in ['', '20260924']:
            with tempfile.TemporaryDirectory() as root:
                fn = Path(root) / '20260924.json'
                original = '{"2330":{"trust":1000}}'
                fn.write_text(original, encoding='utf-8')
                body = {'stat': 'OK', 'date': source_day, 'fields': ['證券代號', '投信買賣超股數'],
                        'data': [['2330', '無資料']]}
                with patch.object(ct, 'CHIP_HISTORY_PATH', root), patch.object(ct, 'fetch_t86', return_value=body):
                    with self.assertRaises(ValueError):
                        ct.parse_and_save('20260924')
                self.assertEqual(fn.read_text(encoding='utf-8'), original)


if __name__ == '__main__':
    unittest.main()
