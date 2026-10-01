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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import macro_track as mt  # noqa: E402
from test_macro_api_contract import api_namespace  # noqa: E402

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
        mt._SEED_PARSE_CACHE.clear()

    def tearDown(self):
        self._today.stop()
        mt._SEED_PARSE_CACHE.clear()
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

    # ── 3b. 種子解析快取（/datasources 一次請求會讓 status_summary 解析所有種子 6 次）────
    def _write(self, name, text):
        with open(os.path.join(self._tmp.name, name), 'w', encoding='utf-8', newline='') as f:
            f.write(text)

    def test_parse_cache_returns_copies_and_follows_file_changes(self):
        self._write('a.csv', 'date,value\n2026-08-26,1.0\n2026-08-27,2.0\n')
        first = mt._load_seed_csv('a.csv')
        first[0]['value'] = 999.0                               # 呼叫端改動不可污染快取
        self.assertEqual(mt._load_seed_csv('a.csv')[0]['value'], 1.0)
        self.assertEqual(len(mt._SEED_PARSE_CACHE), 1)
        # 同樣大小、不同內容：以內容雜湊判斷，不靠 mtime／大小
        self._write('a.csv', 'date,value\n2026-08-26,7.0\n2026-08-27,8.0\n')
        self.assertEqual([p['value'] for p in mt._load_seed_csv('a.csv')], [7.0, 8.0])

    def test_rejected_file_is_not_cached_so_a_repair_takes_effect_immediately(self):
        self._write('b.csv', 'date,value\n2026-08-27,2.0\n2026-08-26,1.0\n')       # 日期倒序 → 拒收
        self.assertEqual(mt._load_seed_csv('b.csv'), [])
        self.assertEqual(len(mt._SEED_PARSE_CACHE), 0)
        self._write('b.csv', 'date,value\n2026-08-26,1.0\n2026-08-27,2.0\n')
        self.assertEqual(len(mt._load_seed_csv('b.csv')), 2)

    def test_future_date_check_is_not_served_stale_from_cache_after_the_day_changes(self):
        self._write('c.csv', 'date,value\n2026-08-27,1.0\n2026-08-28,2.0\n')
        self.assertEqual(len(mt._load_seed_csv('c.csv')), 2)                       # 台北日 = 8/28 時有效
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 8, 27)):
            self.assertEqual(mt._load_seed_csv('c.csv'), [], '日期往回時 8/28 變成未來日，不可吃舊快取')

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


class MacroServerFixes(unittest.TestCase):
    """server.py 的 macro 端：快取失效、失敗更新不被快取、新鮮度窗口、匯入失敗不連坐。"""

    def setUp(self):
        self.api = api_namespace()

    def _bind(self, ns, *names):
        for name in names:
            fn = self.api[name]
            ns[name] = type(fn)(fn.__code__, ns, argdefs=fn.__defaults__)

    def test_forced_refresh_invalidates_only_that_series_cache(self):
        cache = {'baml_hy:10:20260901': b'old', 'baml_hy:5:20260901': b'old',
                 'fedfunds:10:20260901': b'keep'}
        ns = {**self.api, '_macro_cache': cache}
        ns['_macro_resolve_points'] = lambda *a, **k: ([{'date': '2026-08-28', 'value': 80}], 'Yahoo HYG adj')
        self._bind(ns, '_macro_payload', '_macro_cache_invalidate')
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 1)):
            ns['_macro_payload']('baml_hy', years=10, force_live=False)
            self.assertEqual(len(cache), 3, '一般讀取不清快取')
            ns['_macro_payload']('baml_hy', years=10, force_live=True)
        self.assertEqual(set(cache), {'fedfunds:10:20260901'})

    def _handler_ns(self, resolve):
        import ast
        import json
        from urllib.parse import parse_qs, urlparse
        with open(os.path.join(ROOT, 'server', 'server.py'), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_handle_macro')
        ns = {**self.api, 'json': json, 'parse_qs': parse_qs, 'urlparse': urlparse, '_macro_cache': {}}
        ns['_macro_resolve_points'] = resolve
        self._bind(ns, '_macro_payload', '_macro_cache_invalidate')
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'server/server.py', 'exec'), ns)
        return ns

    def test_failed_forced_refresh_is_not_cached_for_later_plain_reads(self):
        from types import SimpleNamespace
        import json
        ns = self._handler_ns(lambda *a, **k: ([{'date': '2026-08-28', 'value': 80}], 'refresh-save-failed:OSError'))
        seen = []
        request = SimpleNamespace(path='/macro/baml_hy?years=10&refresh=1', _ok=lambda body: seen.append(json.loads(body)))
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 1)):
            ns['_handle_macro'](request, 'baml_hy')
        self.assertIn('OSError', seen[0]['refreshError'])
        self.assertEqual(ns['_macro_cache'], {})

    def test_chart_level_refresh_clears_the_whole_macro_cache(self):
        from types import SimpleNamespace
        ns = self._handler_ns(lambda *a, **k: ([], 'empty'))
        ns['_macro_cache'].update({'fedfunds:10:20260901': b'x', 'us10y:10:20260901': b'y'})
        request = SimpleNamespace(path='/macro/refresh/__US_RATES_CREDIT__', _ok=lambda body: None)
        with mock.patch.object(mt, 'refresh_chart', return_value={'ok': True}):
            ns['_handle_macro'](request, 'refresh/__US_RATES_CREDIT__')
        self.assertEqual(ns['_macro_cache'], {})

    def test_policy_rate_and_ndc_signal_use_realistic_freshness_windows(self):
        specs = self.api['MACRO_SERIES']
        # 央行利率：階梯函數，抓取後第 3 個營業日不該就被標成過期
        for key in ('tw_discount', 'tw_secured_rate', 'tw_short_rate'):
            with self.subTest(key=key):
                self.assertEqual(mt.series_freshness('2026-08-07', specs[key], today=date(2026, 9, 26))['freshness'], 'fresh')   # 50 天
                self.assertEqual(mt.series_freshness('2026-05-01', specs[key], today=date(2026, 9, 26))['freshness'], 'stale')   # 148 天
        # 景氣燈號：標在當月 1 日、次月 27 日公布 → 公布前一天最新一列約 88 天
        light = specs['tw_light']
        self.assertEqual(mt.series_freshness('2026-07-01', light, today=date(2026, 9, 26))['freshness'], 'fresh')   # 87 天
        self.assertEqual(mt.series_freshness('2026-07-01', light, today=date(2026, 10, 12))['freshness'], 'stale')  # 103 天

    def test_macro_today_does_not_depend_on_importing_macro_track(self):
        ns = {**self.api, 'taipei_today': lambda: date(2026, 9, 1)}
        self._bind(ns, '_macro_today')
        with mock.patch.dict(sys.modules, {'macro_track': None}):       # import 會拋 ImportError
            self.assertEqual(ns['_macro_today'](), date(2026, 9, 1))

    def test_latest_reader_carries_freshness_so_the_ui_can_flag_stale_or_unverified_values(self):
        import json
        payload = {'label': '美10年債', 'unit': '%', 'source': 'seed:us10y.csv · unverified（來源未驗證）',
                   'points': [{'date': '2026-08-13', 'value': 4.2}],
                   'freshness': 'unknown', 'age': 12, 'ageUnit': 'business_day', 'maxAge': 2}
        ns = {**self.api, 'json': json, '_macro_cache': {'us10y:5:20260901': json.dumps(payload).encode()}}
        self._bind(ns, '_macro_latest')
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 1)):
            row = ns['_macro_latest']('us10y', years=5, allow_fetch=False)
        self.assertEqual((row['value'], row['date']), (4.2, '2026-08-13'))      # 原有欄位不變
        self.assertEqual((row['freshness'], row['age'], row['ageUnit'], row['maxAge']),
                         ('unknown', 12, 'business_day', 2))

    def test_market_risk_sources_no_longer_claim_fred_or_baml(self):
        import market_risk as risk
        with open(risk.__file__, encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('BAML IG/HY', src)
        self.assertNotIn("'FRED CPI/Fed", src)


if __name__ == '__main__':
    unittest.main()
