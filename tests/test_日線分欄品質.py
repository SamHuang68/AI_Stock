"""固定來源回應驗證分欄品質；不連網、不讀正式資料、不補造來源取得時間。"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import daily_quality as quality
import datastore
import 估值趨勢 as valuation
from source_receipts import JsonSourceResponse

NOW = datetime(2026, 10, 2, 20, tzinfo=quality.TAIPEI)
DAY = '2026-10-02'
STAMP = int(datetime(2026, 10, 2, 9, tzinfo=quality.TAIPEI).timestamp())
BASE = (STAMP, 100, 102, 98, 101, 1000)


def receipt_for(rows, **changes):
    data = {'stat': 'OK', 'date': '20261001', 'title': '115年10月 2330 台積電 各日成交資訊',
            'fields': quality.MONTH_FIELDS, 'notes': ['當日含一般、零股、盤後定價、鉅額交易。'],
            'data': [[datetime.fromtimestamp(r[0], quality.TAIPEI).strftime('115/%m/%d'),
                      r[5], '100000', *r[1:5]] for r in rows]}
    data.update(changes)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest(), {
        'url': 'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261001&stockNo=2330',
        'raw_text': raw, 'retrieved_at': '2026-10-02T12:00:00+00:00',
        'parser_version': quality.RECEIPT_PARSER_VERSION}


class ColumnQuality(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'market.db'
        datastore.init_db(self.db)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO market_sessions VALUES(?,?)', (DAY, 'TWSE開休市'))

    def tearDown(self):
        self.temp.cleanup()

    def seed_raw(self, row=BASE):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', *row))
            conn.execute('INSERT OR IGNORE INTO market_sessions VALUES(?,?)', (DAY, 'TWSE開休市'))

    def store(self, row=BASE, *, receipt=True, **kwargs):
        digest, evidence = receipt_for([row])
        return datastore.upsert_bars('2330', 'TW', [row], source='TWSE', source_hash=digest, path=self.db,
                                    source_receipt=evidence if receipt else None, **kwargs)

    def evidence(self):
        with datastore.read_snapshot(self.db) as conn:
            return quality.quality_evidence(conn, '2330', board='TWSE')[DAY]

    def test_volume_only_conflict_preserves_raw_and_selects_official_research_volume(self):
        self.seed_raw()
        official = (*BASE[:5], 1200)
        self.assertEqual(self.store(official), 0)
        item = self.evidence()
        self.assertTrue(item['priceVerified'])
        self.assertTrue(item['volumeConflict'])
        self.assertFalse(item['volumeVerified'])
        self.assertTrue(item['receiptComplete'])
        self.assertIsNone(item['rawSource'])
        with datastore.read_snapshot(self.db) as conn:
            self.assertEqual(tuple(conn.execute('SELECT ts,open,high,low,close,volume FROM bars').fetchone()), BASE)
            self.assertIn('原始值保留', conn.execute('SELECT issues FROM bar_quality').fetchone()[0])
            summary = quality.quality_summary(conn, '2330', [DAY, '2026-10-05'], board='TWSE')
        self.assertEqual({k: summary[k] for k in ('observed', 'accepted', 'conflicts', 'missing', 'priceVerified')},
                         {'observed': 1, 'accepted': 0, 'conflicts': 1, 'missing': 1, 'priceVerified': 1})
        bars, reasons = valuation.load_prices('2330', self.db, NOW, expected=DAY, board='TWSE')
        self.assertEqual(bars[-1]['close'], 101)
        self.assertEqual(bars[-1]['volume'], 1200)
        self.assertTrue(bars[-1]['qualityValid'])
        selected = bars[-1]['officialResearchVolume']
        self.assertEqual((selected['status'], selected['value'], selected['rawValue'], selected['numericDifference']),
                         ('selected', 1200, 1000, 200))
        self.assertIsNone(selected['rawUnit'])
        self.assertEqual(selected['source'], 'TWSE')
        self.assertEqual(selected['unit'], '股')
        self.assertEqual(selected['asOf'], DAY)
        self.assertTrue(any('成交量' in reason for reason in reasons))
        obs = valuation.price_observation(bars, expected=DAY)
        self.assertTrue(obs['priceFresh'])
        self.assertTrue(obs['priceVerified'])
        self.assertIsNone(obs['breakoutVolumeRatio'])
        self.assertIsNone(obs['rangePosition'])
        self.assertEqual(obs['volumeConflictDays'], [DAY])
        self.assertEqual(obs['volumeDifferences'], [selected])
        self.assertEqual(obs['volumeShares'], 1200)
        self.assertEqual(obs['volumeBasis'], 'official-receipt')

    def test_bare_old_observation_cannot_upgrade_to_complete_receipt(self):
        self.seed_raw()
        self.store((*BASE[:5], 1200), receipt=False)
        item = self.evidence()
        self.assertFalse(item['receiptComplete'])
        self.assertFalse(item['priceVerified'])
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertIsNone(bars[-1]['close'])
        with datastore.read_snapshot(self.db) as conn:
            self.assertEqual(quality.quality_summary(conn, '2330', [DAY])['receiptMissing'], 1)

    def test_new_original_receipt_is_distinct_from_old_matching_raw(self):
        self.store()
        self.assertEqual(self.evidence()['rawSource'], 'TWSE')
        self.assertTrue(self.evidence()['receipts'][0]['rawOrigin'])
        self.assertTrue(self.evidence()['volumeVerified'])

    def test_matching_old_raw_never_gets_invented_origin(self):
        self.seed_raw()
        self.store()
        self.assertTrue(self.evidence()['priceVerified'])
        self.assertIsNone(self.evidence()['rawSource'])

    def test_price_revision_blocks_price_and_later_original_does_not_erase_conflict(self):
        self.store()
        revision = (STAMP, 100, 102, 98, 102, 1000)
        self.store(revision)
        self.store()
        self.assertTrue(self.evidence()['priceConflict'])
        self.assertFalse(self.evidence()['priceVerified'])
        self.assertEqual(self.evidence()['observations'], 2)
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertIsNone(bars[-1]['close'])
        with datastore.read_snapshot(self.db) as conn:
            self.assertIn('原始值保留', conn.execute('SELECT issues FROM bar_quality').fetchone()[0])
            self.assertEqual(conn.execute('SELECT close FROM bars').fetchone()[0], 101)

    def test_source_exchange_conflict_cannot_be_hidden_by_board_filter(self):
        self.store()
        datastore.upsert_bars('2330', 'TW', [BASE], source='TPEX', source_hash='舊觀測', path=self.db)
        self.assertTrue(self.evidence()['sourceConflict'])
        self.assertFalse(self.evidence()['priceVerified'])

    def test_cancel_rolls_back_receipt_observation_and_quality_together(self):
        count = 0
        def cancel():
            nonlocal count
            count += 1
            if count == 4:
                raise RuntimeError('取消')
        with self.assertRaisesRegex(RuntimeError, '取消'):
            self.store(check=cancel)
        with datastore.read_snapshot(self.db) as conn:
            for table in ('bars', 'official_source_receipts', 'official_daily_receipt_links', 'official_daily_observations', 'bar_quality'):
                self.assertEqual(conn.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)

    def test_receipts_and_links_are_immutable(self):
        self.store()
        with closing(sqlite3.connect(self.db)) as conn:
            for table in ('official_source_receipts', 'official_daily_receipt_links'):
                for sql in ('DELETE FROM ' + table, 'UPDATE ' + table + " SET source='其他'"):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, '不可'):
                        conn.execute(sql)

    def test_replay_preserves_true_retrieved_time_and_first_written_time(self):
        self.store()
        first = self.evidence()['receipts'][0]
        self.store()
        second = self.evidence()['receipts'][0]
        self.assertEqual(first, second)
        self.assertEqual(first['retrievedAt'], '2026-10-02T12:00:00+00:00')
        self.assertGreaterEqual(first['writtenAt'], first['retrievedAt'])

    def test_raw_hash_url_parser_identity_and_future_receipts_rejected(self):
        digest, base = receipt_for([BASE])
        invalid = [{'url': base['url'].replace('www.twse.com.tw', 'example.invalid')},
                   {'url': base['url'].replace('2330', '2317')}, {'raw_text': base['raw_text'] + ' '},
                   {'parser_version': '不存在'}, {'retrieved_at': '2999-01-01T00:00:00+00:00'},
                   {'retrieved_at': '2026-10-01T00:00:00+00:00'}, {'retrieved_at': '2026-10-02T12:00:00'}]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                datastore.upsert_bars('2330', 'TW', [BASE], source='TWSE', source_hash=digest, path=self.db,
                                      source_receipt={**base, **change})
        for changes in ({'title': '115年10月 2317 鴻海 各日成交資訊'}, {'date': '20260901'},
                        {'fields': []}, {'notes': None}, {'data': [['115/10/02', 1000, 0, 100, 102, 98, 99]]},
                        {'data': [['115/10/03', 1000, 0, 100, 102, 98, 101]]}):
            bad_hash, bad_receipt = receipt_for([BASE], **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                datastore.upsert_bars('2330', 'TW', [BASE], source='TWSE', source_hash=bad_hash,
                                      path=self.db, source_receipt=bad_receipt)
        with datastore.read_snapshot(self.db) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bars').fetchone()[0], 0)

    def test_same_source_hash_different_payload_fails_without_overwriting(self):
        self.store(receipt=False)
        digest, _ = receipt_for([BASE])
        with self.assertRaisesRegex(ValueError, '相同來源雜湊'):
            datastore.upsert_bars('2330', 'TW', [(*BASE[:5], 1200)], source='TWSE', source_hash=digest, path=self.db)
        self.assertEqual(self.evidence()['observations'], 1)

    def test_duplicate_session_raw_never_verifies_prices(self):
        self.store()
        self.seed_raw((STAMP + 3600, *BASE[1:]))
        item = self.evidence()
        self.assertTrue(item['ambiguousSession'])
        self.assertFalse(item['priceVerified'])
        self.assertTrue(item['receiptComplete'])

    def test_zero_volume_is_not_null_and_null_does_not_verify(self):
        row = (*BASE[:5], 0)
        self.store(row)
        self.assertTrue(self.evidence()['volumeVerified'])
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertEqual(bars[-1]['volume'], 0)
        self.assertIsNone(valuation.price_observation(bars, expected=DAY)['rangePosition'])

    def test_null_official_volume_retains_verified_prices(self):
        self.store((*BASE[:5], None))
        self.assertTrue(self.evidence()['priceVerified'])
        self.assertFalse(self.evidence()['volumeVerified'])
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertEqual(bars[-1]['close'], 101)
        self.assertIsNone(bars[-1]['volume'])

    def test_price_read_is_pure_and_tuple_response_is_backwards_compatible(self):
        self.store()
        before = self.db.read_bytes()
        self.evidence()
        valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertEqual(self.db.read_bytes(), before)
        response = JsonSourceResponse({'stat': 'OK'}, '雜湊', {'來源': '收據'})
        value, digest = response
        self.assertEqual((value, digest), ({'stat': 'OK'}, '雜湊'))
        self.assertEqual(response.source_receipt, {'來源': '收據'})

    def test_one_share_difference_in_large_volume_is_still_a_conflict(self):
        self.seed_raw((*BASE[:5], 20_000_000))
        self.store((*BASE[:5], 20_000_001))
        self.assertTrue(self.evidence()['volumeConflict'])
        self.assertTrue(self.evidence()['priceVerified'])

    def test_invalid_link_cannot_fall_back_to_old_quality_record(self):
        self.store(receipt=False)
        digest, _ = receipt_for([BASE])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            payload = conn.execute('SELECT payload FROM official_daily_observations').fetchone()[0]
            conn.execute('INSERT INTO official_daily_receipt_links VALUES(?,?,?,?,?,?,?,?,?)',
                         ('TW', '2330', DAY, 'TWSE', digest, '不存在的收據', payload, NOW.isoformat(), 0))
        self.assertTrue(self.evidence()['invalidReceipt'])
        with datastore.read_snapshot(self.db) as conn:
            summary = quality.quality_summary(conn, '2330', [DAY])
        self.assertEqual(summary['receiptMissing'], 1)
        self.assertEqual(summary['receiptInvalid'], 1)
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertIsNone(bars[-1]['close'])

    def test_duplicate_raw_json_keys_and_duplicate_days_are_rejected(self):
        digest, receipt = receipt_for([BASE])
        raw = receipt['raw_text'].replace('"stat": "OK"', '"stat": "OK", "stat": "OK"')
        with self.assertRaises(ValueError):
            quality.validate_source_receipt({**receipt, 'raw_text': raw}, 'TWSE', hashlib.sha256(raw.encode()).hexdigest(), '2330', [BASE])
        digest, receipt = receipt_for([BASE, BASE])
        with self.assertRaisesRegex(ValueError, '交易日重複'):
            quality.validate_source_receipt(receipt, 'TWSE', digest, '2330', [BASE])

    def test_invalid_number_and_timestamp_are_rejected_before_writing(self):
        for row in (None, [], (True, *BASE[1:]), (STAMP, True, *BASE[2:]), (STAMP, float('nan'), *BASE[2:])):
            with self.subTest(row=row), self.assertRaises(ValueError):
                datastore.upsert_bars('2330', 'TW', [row], source='TWSE', path=self.db)

    def test_saved_raw_hash_corruption_does_not_count_as_complete_source(self):
        self.store(receipt=False)
        digest, receipt = receipt_for([BASE])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            payload = conn.execute('SELECT payload FROM official_daily_observations').fetchone()[0]
            conn.execute('INSERT INTO official_source_receipts VALUES(?,?,?,?,?,?,?,?)',
                         ('損壞收據', 'TWSE', digest, receipt['url'], receipt['raw_text'] + ' ',
                          receipt['retrieved_at'], NOW.isoformat(), receipt['parser_version']))
            conn.execute('INSERT INTO official_daily_receipt_links VALUES(?,?,?,?,?,?,?,?,?)',
                         ('TW', '2330', DAY, 'TWSE', digest, '損壞收據', payload, NOW.isoformat(), 0))
        self.assertFalse(self.evidence()['receiptComplete'])
        self.assertTrue(self.evidence()['invalidReceipt'])
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertIsNone(bars[-1]['close'])


    def test_official_volume_revisions_require_consensus_not_latest_wins(self):
        self.seed_raw()
        self.store((*BASE[:5], 1200))
        self.store((*BASE[:5], 1300))
        self.store((*BASE[:5], 1200))
        selected = self.evidence()['officialResearchVolume']
        self.assertEqual(selected['reason'], 'official_revision_conflict')
        self.assertIsNone(selected['value'])
        self.assertEqual(selected['rawValue'], 1000)
        bars, _ = valuation.load_prices('2330', self.db, NOW, expected=DAY)
        self.assertIsNone(bars[-1]['volume'])
        self.assertFalse(bars[-1]['qualityValid'])

    def test_unreceipted_observation_is_not_silently_promoted_by_another_receipt(self):
        self.store()
        digest, _ = receipt_for([BASE], notes=['另一份未留存的完整回應'])
        datastore.upsert_bars('2330', 'TW', [BASE], source='TWSE', source_hash=digest, path=self.db)
        self.assertEqual(self.evidence()['officialResearchVolume']['reason'], 'incomplete_receipts')

    def test_seven_known_volume_differences_use_official_shares_and_leave_raw_unchanged(self):
        cases = [
            ('0050', '2026-09-23', 55410585, 58059253, 2648668),
            ('0050', '2026-09-24', 66490792, 70487939, 3997147),
            ('2330', '2026-09-23', 20406553, 22817873, 2411320),
            ('2330', '2026-09-24', 13043734, 14557662, 1513928),
            ('2330', '2026-09-29', 25532143, 26893348, 1361205),
            ('2330', '2026-09-30', 32442982, 34282491, 1839509),
            ('2330', '2026-10-02', 15071494, 15792206, 720712)]
        for code, day, raw_volume, official, delta in cases:
            with self.subTest(code=code, day=day):
                date = datetime.fromisoformat(day).replace(tzinfo=quality.TAIPEI, hour=9)
                row = (int(date.timestamp()), *BASE[1:5], raw_volume)
                with closing(sqlite3.connect(self.db)) as conn, conn:
                    conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', (code, 'TW', *row))
                payload = {'stat': 'OK', 'date': date.strftime('%Y%m01'),
                           'title': f'115年{date.month:02}月 {code} 測試 各日成交資訊',
                           'fields': quality.MONTH_FIELDS,
                           'notes': ['含一般、零股、盤後定價、鉅額交易；不含拍賣及標購。'],
                           'data': [[date.strftime('115/%m/%d'), official, '100000', *row[1:5]]]}
                raw = json.dumps(payload, ensure_ascii=False)
                receipt = {'url': 'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=' +
                           date.strftime('%Y%m01') + '&stockNo=' + code, 'raw_text': raw,
                           'retrieved_at': '2026-10-03T00:00:00+00:00', 'parser_version': quality.RECEIPT_PARSER_VERSION}
                datastore.upsert_bars(code, 'TW', [(*row[:5], official)], source='TWSE',
                                     source_hash=hashlib.sha256(raw.encode()).hexdigest(), source_receipt=receipt, path=self.db)
                with datastore.read_snapshot(self.db) as conn:
                    item = quality.quality_evidence(conn, code, board='TWSE', start=day, end=day)[day]
                    self.assertEqual(conn.execute('SELECT volume FROM bars WHERE market=? AND symbol=? AND ts=?',
                                                 ('TW', code, row[0])).fetchone()[0], raw_volume)
                volume = item['officialResearchVolume']
                self.assertEqual((volume['status'], volume['value'], volume['numericDifference']), ('selected', official, delta))
                self.assertFalse(item['volumeVerified'])
                self.assertTrue(item['volumeConflict'])
                self.assertIsNone(volume['rawSource'])
                self.assertEqual(volume['receiptIds'], [item['receipts'][0]['receiptId']])
        result = valuation.get_research('0050', database=self.db, lookup=lambda *_: None, now=NOW)
        self.assertEqual(result['row']['research']['scopeReasonCode'], 'excludedNonStock')

    def test_official_zero_null_fractional_and_bad_price_stay_distinct(self):
        for value, selected in ((0, True), (None, False), (0.5, False)):
            with self.subTest(value=value):
                # 不同股票獨立留存，不把本案例誤變成來源修訂。
                path = Path(self.temp.name) / ('volume-' + str(value) + '.db')
                datastore.init_db(path)
                row = (*BASE[:5], value)
                digest, receipt = receipt_for([row])
                datastore.upsert_bars('2330', 'TW', [row], source='TWSE', source_hash=digest,
                                     source_receipt=receipt, path=path)
                with datastore.read_snapshot(path) as conn:
                    item = quality.quality_evidence(conn, '2330')[DAY]['officialResearchVolume']
                self.assertEqual(item['status'], 'selected' if selected else 'unavailable')
                self.assertEqual(item['value'], 0 if selected else None)
                bars, _ = valuation.load_prices('2330', path, NOW)
                self.assertEqual(bars[-1]['volume'], 0 if selected else None)
                self.assertEqual(bars[-1]['qualityValid'], selected)
                self.assertEqual(bars[-1]['volumeVerified'], selected)
        self.seed_raw()
        self.store((STAMP, 100, 102, 98, 102, 1200))
        self.assertEqual(self.evidence()['officialResearchVolume']['reason'], 'price_not_verified')


if __name__ == '__main__':
    unittest.main()
