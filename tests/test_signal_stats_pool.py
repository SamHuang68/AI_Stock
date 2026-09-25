# -*- coding: utf-8 -*-
"""P2：同市場合併統計（門檻、基準、誤差範圍、穩定度、掛載與成績單）。"""
from __future__ import annotations

import os
import random
import statistics
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import signal_stats_pool as pool  # noqa: E402
import stock_signals as ss  # noqa: E402


def make_bars(seed, n=400):
    rnd = random.Random(seed)
    px, out, d = 50.0 + seed, [], date(2022, 1, 3)
    for _ in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        px *= 1 + rnd.gauss(0.0003, 0.02)
        out.append({'date': d.isoformat(), 'open': px, 'high': px * 1.012, 'low': px * 0.988,
                    'close': px, 'volume': 1000 + rnd.random() * 3000})
        d += timedelta(days=1)
    return out


class ConfidenceTests(unittest.TestCase):
    def test_ci95_and_verdict(self):
        self.assertAlmostEqual(ss.ci95_pts(0.5, 100), 9.8)
        self.assertIsNone(ss.ci95_pts(0.5, 0))
        self.assertEqual(ss.edge_verdict(3.0, 9.8), 'noise')
        self.assertEqual(ss.edge_verdict(12.0, 9.8), 'above')
        self.assertEqual(ss.edge_verdict(-12.0, 9.8), 'below')
        self.assertIsNone(ss.edge_verdict(None, 9.8))


class BinnedBaseTests(unittest.TestCase):
    def test_binned_median_close_to_exact(self):
        rnd = random.Random(1)
        vals = [rnd.gauss(0.001, 0.03) for _ in range(5001)]
        b = pool._BinnedBase()
        for v in vals:
            b.add(v)
        self.assertEqual(b.up, sum(1 for v in vals if v > 0))
        self.assertLessEqual(abs(b.median() - statistics.median(vals)), pool.BIN)


class PooledTests(unittest.TestCase):
    def setUp(self):
        self.series = [('%04d' % k, make_bars(k, 500)) for k in range(12)]

    def test_gates_and_fields(self):
        res = pool.compute_pooled(iter(self.series), market='TW')
        self.assertEqual(res['symbols'], 12)
        self.assertEqual(res['minSample'], pool.POOLED_MIN_SAMPLE)
        self.assertTrue(res['caveats'])
        for sid, sig in res['signals'].items():
            for row in sig['horizons']:
                if row['gate'] == 'ok':
                    self.assertGreaterEqual(row['n'], pool.POOLED_MIN_SAMPLE)
                    self.assertGreaterEqual(row['symbols'], pool.MIN_SYMBOLS)
                    self.assertIn(row['edgeVerdict'], ('above', 'below', 'noise'))
                    self.assertAlmostEqual(row['edgePts'], round((row['upRatio'] - row['baseUpRatio']) * 100, 1),
                                           places=1)
                else:
                    self.assertIsNone(row['upRatio'])
        # 至少有一個常見訊號（站上季線）在 12 檔隨機漫步上湊得到足夠樣本
        self.assertEqual(res['signals']['trend_reclaim_ma60']['horizons'][0]['gate'], 'ok')

    def test_counts_match_per_symbol_engine(self):
        res = pool.compute_pooled(iter(self.series), market='TW', min_sample=1)
        spec = ss.SIGNAL_BY_ID['mom_macd_bull']
        expected = 0
        for _, bars in self.series:
            f = ss.build_frame(bars)
            expected += len(ss.forward_outcomes(f, ss.event_indices(f, spec), 5, 'bull'))
        self.assertEqual(res['signals']['mom_macd_bull']['horizons'][0]['n'], expected)

    def test_short_series_are_skipped(self):
        res = pool.compute_pooled(iter([('X', make_bars(1, 100))]), market='TW')
        self.assertEqual(res['symbols'], 0)

    def test_attach_and_scoreboard(self):
        res = pool.compute_pooled(iter(self.series), market='TW')
        card = ss.analyze(make_bars(3, 400), symbol='0003', market='TW')
        pool.attach(card, res)
        self.assertTrue(card['pooled']['available'])
        for e in card['events']:
            self.assertIn('pooledStats', e)
            self.assertIn(f"pooled.{e['signalId']}.h5", card['evidence'])
        board = pool.scoreboard(res)
        self.assertEqual(len(board), len(ss.SIGNALS))
        known = [r['sortEdge'] for r in board if r['sortEdge'] is not None]
        self.assertEqual(known, sorted(known, key=lambda x: -abs(x)))

    def test_refresh_reads_datastore_and_caches(self):
        import datastore
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(datastore, 'DB_PATH', os.path.join(tmp, 'm.db')):
            datastore.init_db()
            for code, bars in self.series[:6]:
                # 01:00 UTC = 台北 09:00，與 Yahoo 日 K 時間戳同一天
                rows = [((date.fromisoformat(b['date']) - date(1970, 1, 1)).days * 86400 + 3600,
                         b['open'], b['high'], b['low'], b['close'], b['volume']) for b in bars]
                datastore.upsert_bars(code, 'TW', rows)
            macro = [((date(2022, 1, 3) - date(1970, 1, 1)).days * 86400 + 86400 * i, 1, 1, 1, 150.0 + i % 7, 0)
                     for i in range(400)]
            datastore.upsert_bars('__MARGIN_RATIO__', 'TW', macro)   # 合成序列不得進入個股統計
            datastore.upsert_bars('^TWII', 'TW', macro)
            cache = os.path.join(tmp, 'pooled.json')
            res = pool.refresh('TW', chip_dir=os.path.join(tmp, 'none'), cache_file=cache)
            self.assertEqual(res['symbols'], 6)
            self.assertEqual(pool.load_cached('TW', cache)['symbols'], 6)
            self.assertIsNone(pool.load_cached('US', cache))


if __name__ == '__main__':
    unittest.main()
