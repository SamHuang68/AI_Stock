#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""總經種子審查後的修正：歷史不被截短、讀圖不改檔、還原收盤容錯、FRED 熔斷會恢復。"""
import glob
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import macro_track as mt  # noqa: E402

TODAY = date(2026, 8, 28)


def _monthly_points(start_year, end=TODAY):
    pts, d = [], date(start_year, 1, 3)
    while d <= end:
        pts.append({'date': d.isoformat(), 'value': 1.0 + (d.year - start_year) * 0.1})
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=3)
    return pts


class MacroReviewFixes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._seed_dir = mt.SEED_DIR
        mt.SEED_DIR = self._tmp.name
        self._today = mock.patch.object(mt, '_taipei_today', return_value=TODAY)
        self._today.start()

    def tearDown(self):
        self._today.stop()
        mt.SEED_DIR = self._seed_dir
        mt._FRED_CIRCUIT_OPEN = False
        mt._FRED_CIRCUIT_SEEN_AT = None
        self._tmp.cleanup()

    # ── 1. 更新鈕的 years 不可決定種子保留多少歷史 ─────────────────────────
    def test_refresh_of_unverified_seed_keeps_the_seed_span_not_the_callers_years(self):
        spec = {'seed': 'fedfunds.csv', 'seedSource': 'NY Fed EFFR', 'canonical': 'nyfed_effr', 'source': 'fred'}
        full = _monthly_points(2005)
        mt._save_seed_csv('fedfunds.csv', full)          # 沒有 .source.json → 未驗證
        asked = []

        def provider(years):                              # 與真實來源一樣：只回請求區間內的資料
            asked.append(years)
            cutoff = TODAY - timedelta(days=years * 366)
            return [p for p in full if date.fromisoformat(p['date']) >= cutoff]

        with mock.patch.object(mt, '_nyfed_effr', side_effect=provider):
            points, note = mt._resolve_series_points(spec, years=5, force_live=True)   # 經濟頁更新鈕是 5 年
        self.assertGreaterEqual(asked[0], 21, '至少要涵蓋現有種子的起點')
        self.assertEqual(points[0]['date'], '2005-01-03')
        self.assertEqual(mt._load_seed_csv('fedfunds.csv')[0]['date'], '2005-01-03')
        self.assertEqual(note, 'NY Fed EFFR')

    # ── 2. 讀圖不該改檔 ───────────────────────────────────────────────
    def test_plain_read_of_a_rejected_seed_does_not_fetch_or_rewrite(self):
        spec = {'seed': 'fedfunds.csv', 'seedSource': 'NY Fed EFFR', 'canonical': 'nyfed_effr', 'source': 'fred'}
        bad = 'date,value\n2005-01-03,1.0\n2999-01-01,2.0\n'           # 一列未來日 → 整檔拒收
        path = os.path.join(self._tmp.name, 'fedfunds.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(bad)
        with mock.patch.object(mt, '_nyfed_effr') as provider:
            points, note = mt._resolve_series_points(spec, years=1, force_live=False)
        provider.assert_not_called()
        self.assertEqual(points, [])
        self.assertTrue(note.startswith('seed-rejected:'))
        self.assertIn('unverified', note)                 # 下游以此判為「未知」而非「新鮮」
        with open(path, encoding='utf-8', newline='') as f:
            self.assertEqual(f.read(), bad)
        self.assertEqual(glob.glob(path + '*.bak'), [])

    def test_explicit_refresh_of_a_rejected_seed_backs_it_up_then_rebuilds(self):
        spec = {'seed': 'fedfunds.csv', 'seedSource': 'NY Fed EFFR', 'canonical': 'nyfed_effr', 'source': 'fred'}
        bad = 'date,value\n2005-01-03,1.0\n2999-01-01,2.0\n'
        path = os.path.join(self._tmp.name, 'fedfunds.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(bad)
        with mock.patch.object(mt, '_nyfed_effr', return_value=_monthly_points(2020)):
            points, _ = mt._resolve_series_points(spec, years=10, force_live=True)
        self.assertEqual(points[0]['date'], '2020-01-03')
        backups = glob.glob(path + '.unverified.*.bak')
        self.assertEqual(len(backups), 1)
        with open(backups[0], encoding='utf-8', newline='') as f:
            self.assertEqual(f.read(), bad, '壞檔原樣備份，不丟資料')

    def test_missing_seed_is_still_created_on_first_read(self):
        spec = {'seed': 'fedfunds.csv', 'seedSource': 'NY Fed EFFR', 'canonical': 'nyfed_effr', 'source': 'fred'}
        with mock.patch.object(mt, '_nyfed_effr', return_value=_monthly_points(2020)) as provider:
            points, _ = mt._resolve_series_points(spec, years=10, force_live=False)
        provider.assert_called_once()
        self.assertTrue(points)

    # ── 3. 還原收盤 ───────────────────────────────────────────────────
    def test_adj_optional_falls_back_to_raw_close_only_when_asked(self):
        payload = {'chart': {'result': [{'timestamp': [1787875200],
                                         'indicators': {'quote': [{'close': [18.5]}]}}]}}
        with mock.patch.object(mt, '_http_json', return_value=payload):
            self.assertEqual(mt._yahoo_closes('^VIX', 5, adj=True), [])                       # 預設嚴格
            self.assertEqual(mt._yahoo_closes('^VIX', 5, adj=True, adj_optional=True)[0]['value'], 18.5)

    def test_series_flag_reaches_the_provider_call(self):
        optional = {'seed': 'vix.csv', 'canonical': 'yahoo_adj', 'symbol': '^VIX', 'adjOptional': True}
        strict = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        with mock.patch.object(mt, '_yahoo_closes', return_value=[]) as yahoo:
            mt._resolve_series_points(optional, years=5, force_live=True)
            yahoo.assert_called_once_with('^VIX', years=5, adj=True, adj_optional=True)
            yahoo.reset_mock()
            mt._resolve_series_points(strict, years=5, force_live=True)
            yahoo.assert_called_once_with('HYG', years=5, adj=True)

    def test_non_etf_series_in_the_api_table_are_adj_optional_and_etfs_are_not(self):
        import ast
        with open(os.path.join(ROOT, 'server', 'server.py'), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        table = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                     and any(getattr(t, 'id', None) == 'MACRO_SERIES' for t in n.targets))
        specs = ast.literal_eval(table.value)
        for key, spec in specs.items():
            if spec.get('canonical') != 'yahoo_adj':
                continue
            etf = spec.get('symbol') in ('LQD', 'HYG', 'XLF')
            with self.subTest(key=key):
                self.assertEqual(bool(spec.get('adjOptional')), not etf)

    def test_adjusted_history_coverage_tolerates_a_few_missing_days_only(self):
        current = [{'date': (date(2010, 1, 4) + timedelta(days=i)).isoformat(), 'value': 1.0} for i in range(2000)]
        def live_without(n_missing, skip_start=0):
            return [p for i, p in enumerate(current) if not (skip_start <= i < skip_start + n_missing)]
        self.assertTrue(mt._adj_history_covered(current, live_without(3, 500)))
        self.assertFalse(mt._adj_history_covered(current, live_without(60, 500)))            # > 1%：不完整
        self.assertFalse(mt._adj_history_covered(current, current[40:]))                      # 起點晚了 40 天
        self.assertFalse(mt._adj_history_covered(current, []))
        self.assertTrue(mt._adj_history_covered([], current))

    def test_verified_adjusted_seed_refresh_survives_one_missing_day_and_uses_one_basis(self):
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        old = [{'date': (date(2026, 1, 5) + timedelta(days=i)).isoformat(), 'value': 80.0} for i in range(60)]
        mt._save_seed_csv(spec['seed'], old)
        mt._save_seed_source(spec)                                                          # 驗證過的種子
        # 這次 Yahoo 少了中間一天；配息使整段還原值重算（基準改變）
        live = [{'date': p['date'], 'value': 79.5} for i, p in enumerate(old) if i != 30]
        with mock.patch.object(mt, '_yahoo_closes', return_value=live):
            points, note = mt._resolve_series_points(spec, years=5, force_live=True)
        self.assertFalse(note.startswith('refresh-incomplete'))
        self.assertEqual({p['value'] for p in points}, {79.5}, '不可混入舊基準的值')
        self.assertEqual(len(points), 59)

    # ── 4. FRED 熔斷會恢復 ────────────────────────────────────────────
    def test_fred_circuit_closes_again_after_cooldown(self):
        mt._FRED_CIRCUIT_OPEN = True
        mt._FRED_CIRCUIT_SEEN_AT = None
        with mock.patch.dict(os.environ, {'MACRO_SKIP_FRED': ''}), \
                mock.patch.object(mt.time, 'monotonic', side_effect=[1000.0, 1599.0, 1601.0]):
            self.assertTrue(mt.fred_circuit_open())      # 第一次被查到起算
            self.assertTrue(mt.fred_circuit_open())      # 冷卻中
            self.assertFalse(mt.fred_circuit_open())     # 冷卻 600 秒後半開
        self.assertFalse(mt._FRED_CIRCUIT_OPEN)

    def test_explicit_skip_flag_is_permanent(self):
        mt._FRED_CIRCUIT_OPEN = False
        with mock.patch.dict(os.environ, {'MACRO_SKIP_FRED': '1'}):
            self.assertTrue(mt.fred_circuit_open())

    # ── 5. 清暫存檔失敗不可蓋掉真正的錯誤 ─────────────────────────────
    def test_cleanup_failure_does_not_raise(self):
        tmp = os.path.join(self._tmp.name, 'x.tmp')
        open(tmp, 'w').close()
        with mock.patch.object(os, 'remove', side_effect=PermissionError('locked')):
            mt._remove_quietly(tmp)                      # 不拋
        mt._remove_quietly(os.path.join(self._tmp.name, 'never-existed.tmp'))


if __name__ == '__main__':
    unittest.main()
