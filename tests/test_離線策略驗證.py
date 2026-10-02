"""離線研究的經濟語意、未來資訊、輸入與外連邊界測試。"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'research/策略驗證/離線驗證.py'
if not SOURCE.is_file() and os.environ.get('ST_RESEARCH_REQUIRED') == '1':
    raise FileNotFoundError('研究 CI 缺少離線研究原始碼')
if SOURCE.is_file():
    SPEC = importlib.util.spec_from_file_location('offline_research', SOURCE)
    R = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(R)


@unittest.skipUnless(SOURCE.is_file(), '一般分享包不包含選用離線研究工具')
class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in ('numpy', 'pandas', 'matplotlib') if importlib.util.find_spec(name) is None]
        if missing:
            if os.environ.get('ST_RESEARCH_REQUIRED') == '1':
                raise RuntimeError('研究測試缺少必要依賴：' + ', '.join(missing))
            raise unittest.SkipTest('選用離線研究依賴未安裝；獨立研究 CI 另行完整驗證')
        (ROOT / 'scratch').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / 'scratch')
        cls.analysis, cls.scan, cls.wf, cls.validation = R.load_libraries(Path(cls.temp.name) / '快取')
        cls.raw_pnl = staticmethod(cls.analysis.precise_pnl)
        cls.raw_stats = staticmethod(cls.analysis.compute_stats)

    @classmethod
    def tearDownClass(cls):
        cls.analysis.precise_pnl = cls.raw_pnl
        cls.analysis.compute_stats = cls.raw_stats
        cls.temp.cleanup()

    def frame(self, n=1600):
        np, pd = R.np, R.pd
        t = np.arange(n)
        close = 100 * np.exp(.0002 * t + .12 * np.sin(t / 27))
        opening = close * np.exp(.004 * np.sin(t / 3))
        return pd.DataFrame({'Open':opening, 'High':np.maximum(opening, close) * 1.01,
            'Low':np.minimum(opening, close) * .99, 'Close':close, 'Volume':1000.},
            index=pd.bdate_range('2020-01-01', periods=n))

    def test_overnight_intraday_compound(self):
        np = R.np
        cl, op = np.array([100., 121.]), np.array([100., 110.])
        ones, zeros = np.ones(2), np.zeros(2, dtype=bool)
        original = self.raw_pnl(cl, op, ones, ones, zeros, 0)[0]
        corrected = R.exact_pnl(cl, op, ones, ones, zeros, 0, 0)[0]
        self.assertAlmostEqual(original[1], .20)
        self.assertAlmostEqual(corrected[1], .21)

    def test_first_loss_drawdown_includes_initial_capital(self):
        idx = R.pd.date_range('2020-01-01', periods=2)
        self.assertAlmostEqual(R.corrected_stats([-.1, 0], idx)[3], -.1)

    def test_next_open_gaps_and_asymmetric_costs(self):
        np = R.np
        frame = R.pd.DataFrame({'Open':[100, 120, 150], 'Close':[100, 132, 160]},
                               index=R.pd.date_range('2020-01-01', periods=3))
        pos = np.array([1., 0., 0.])
        cur, prev = R.weights(pos)
        ret = R.exact_pnl(frame.Close, frame.Open, cur, prev, np.zeros(3), .01, .02)[0]
        reference, rows, trades, _ = R.cash_ledger(frame, pos, .01, .02)
        np.testing.assert_allclose(ret, reference, atol=1e-14)
        self.assertAlmostEqual(rows[-1]['權益'], 150 * .98 / (120 * 1.01))
        self.assertEqual(trades[0]['進場價'], 120)
        self.assertEqual(trades[0]['出場價'], 150)

    def test_no_same_bar_fill_or_forced_terminal_exit(self):
        frame = self.frame(100)
        pos = R.np.zeros(100); pos[-1] = 1
        ret, rows, trades, holding = R.cash_ledger(frame, pos, .0025, .0055)
        self.assertTrue((ret == 0).all())
        self.assertEqual(trades, [])
        pos[-2] = 1
        ret, rows, trades, holding = R.cash_ledger(frame, pos, .0025, .0055)
        self.assertIsNotNone(holding)
        self.assertEqual(trades, [])

    def test_cost_monotonicity_and_random_cash_reconciliation(self):
        frame = self.frame()
        pos = R.np.random.default_rng(5).integers(0, 2, len(frame)).astype(float)
        cur, prev = R.weights(pos)
        final = []
        for buy, sell in [(0, 0), (.0025, .0055), (.005, .011)]:
            ret = R.exact_pnl(frame.Close, frame.Open, cur, prev, R.np.zeros(len(frame)), buy, sell)[0]
            reference, *_ = R.cash_ledger(frame, pos, buy, sell)
            R.np.testing.assert_allclose(ret, reference, atol=1e-12)
            final.append(float(R.np.prod(1 + ret)))
        self.assertGreater(final[0], final[1]); self.assertGreater(final[1], final[2])

    def test_causal_for_all_fixed_parameters(self):
        self.assertEqual(R.causal_check(self.frame()), 75)

    def test_rejects_invalid_data_and_unsupported_exposure(self):
        frame = self.frame(100)
        frame.iloc[4, frame.columns.get_loc('Open')] = float('nan')
        with self.assertRaises(ValueError): R.validate_frame(frame)
        zero_volume = self.frame(100)
        zero_volume.iloc[4, zero_volume.columns.get_loc('Volume')] = 0
        with self.assertRaises(ValueError): R.validate_frame(zero_volume)
        with self.assertRaises(ValueError): R.exact_pnl([100, 100], [100, 100], [0, -1], [0, 0], [0, 0], 0, 0)
        with self.assertRaises(ValueError): R.exact_pnl([100, 100], [100, 100], [0, 1], [0, 0], [0, 1], 0, 0)

    def test_network_and_subprocess_guard(self):
        for event in ['socket.connect', 'socket.getaddrinfo', 'socket.sendto', 'socket.bind', 'subprocess.Popen']:
            with self.assertRaises(PermissionError): R.offline_guard(event, ())

    def test_core_expectation_uses_next_open_costs_and_daily_drawdown(self):
        frame = R.pd.DataFrame({'Open':[100, 120, 150], 'Close':[100, 100, 160]},
                              index=R.pd.date_range('2020-01-01', periods=3))
        result = R.core_expected(frame, [1., 0., 0.], .01, .02)
        self.assertEqual(result['交易'][0]['entryBar'], 1)
        self.assertEqual(result['交易'][0]['exitBar'], 2)
        self.assertAlmostEqual(result['每日權益'][1], 100 / 121.2)
        self.assertAlmostEqual(result['每日權益'][2], 147 / 121.2)
        self.assertAlmostEqual(result['最大回撤百分比'], (1 - 100 / 121.2) * 100)
        self.assertFalse(result['未平倉'])

    def test_javascript_core_matches_independent_cash_ledger(self):
        node = shutil.which('node')
        if not node:
            if os.environ.get('ST_RESEARCH_REQUIRED') == '1':
                self.fail('研究 CI 需要 Node.js 執行獨立核心對照')
            self.skipTest('未安裝選用的 Node.js 核心對照工具')
        frame = self.frame(700)
        pos = R.signals(frame).to_numpy()
        output = Path(self.temp.name) / '核心核對'
        output.mkdir()
        rows = [{'時間戳': int(day.tz_localize('Asia/Taipei').timestamp()),
                 '開盤': float(row.Open), '最高': float(row.High), '最低': float(row.Low),
                 '收盤': float(row.Close), '成交量': float(row.Volume)}
                for day, row in frame.iterrows()]
        R.write_json(output / '輸入快照.json', {'日線': rows})
        R.write_json(output / '既有核心預期.json', {
            **R.core_expected(frame, pos, .0025, .0055), '訊號': pos.tolist(),
            '既有核心雜湊': R.digest(ROOT / 'src/screener/backtest_v3.js')})
        (output / '研究報告.html').write_text('<span id="legacy-status">尚未執行獨立核對</span>', encoding='utf-8')
        result = subprocess.run([node, str(SOURCE.parent / '核對既有核心.js'), str(output)],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        proof = json.loads((output / '既有核心核對.json').read_text(encoding='utf-8'))
        self.assertTrue(proof['通過'])
        self.assertEqual(proof['每日權益筆數'], 700)

    def test_full_cli_replay_report_and_invalid_input_diagnostic(self):
        frame = self.frame(1600)
        rows = [{'日期': str(day.date()), '時間戳': int(day.tz_localize('Asia/Taipei').timestamp()),
                 '開盤': float(row.Open), '最高': float(row.High), '最低': float(row.Low),
                 '收盤': float(row.Close), '成交量': float(row.Volume)}
                for day, row in frame.iterrows()]
        snapshot = Path(self.temp.name) / '合成驗收快照.json'
        data = {'標的': '合成驗收（非真實行情）', '市場': 'TW', '日線': rows,
                '查詢截止日': str(frame.index[-1].date()), '擷取時間': '2026-10-01T00:00:00+08:00'}
        R.write_json(snapshot, data)
        output = Path(self.temp.name) / '完整流程'
        command = [sys.executable, '-E', '-B', '-X', 'utf8', str(SOURCE),
                   '--快照', str(snapshot), '--輸出', str(output)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        report = json.loads((output / '研究結果.json').read_text(encoding='utf-8'))
        self.assertEqual(report['升級門檻']['verdict'], 'FAIL')
        self.assertGreaterEqual(report['樣本外驗證']['窗口數'], 3)
        self.assertIn('合成驗收', (output / '研究報告.html').read_text(encoding='utf-8'))
        rows[5]['成交量'] = 0
        R.write_json(snapshot, data)
        invalid = Path(self.temp.name) / '資料拒絕'
        command[-1] = str(invalid)
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 1)
        diagnostic = json.loads((invalid / '輸入診斷.json').read_text(encoding='utf-8'))
        self.assertEqual(diagnostic['status'], 'dataset_unusable')
        self.assertEqual(diagnostic['issues'], [{'date': rows[5]['日期'], 'code': 'zero_volume'}])
        self.assertFalse((invalid / '研究結果.json').exists())

    def test_empty_trade_file_still_exists(self):
        target = Path(self.temp.name) / '無交易.csv'
        R.csv_write(target, [])
        self.assertIn('無完成交易', target.read_text(encoding='utf-8-sig'))

    def test_zero_position_mcpt_is_unavailable_not_zero_pvalue(self):
        frame = self.frame(300)
        result = R.mcpt_diagnostic(self.validation, frame, R.np.zeros(len(frame)), .004)
        self.assertIsNone(result['p值'])
        self.assertIn('無有效檢驗', result['狀態'])

    def test_valid_mcpt_is_seeded_and_finite(self):
        frame = self.frame(300)
        first = R.mcpt_diagnostic(self.validation, frame, R.signals(frame).to_numpy(), .004)
        second = R.mcpt_diagnostic(self.validation, frame, R.signals(frame).to_numpy(), .004)
        self.assertEqual(first, second)
        self.assertIsNotNone(first['p值'])

    def test_database_readonly_cutoff_and_hash(self):
        target = Path(self.temp.name) / '行情.db'
        frame = self.frame(700)
        with R.contextlib.closing(sqlite3.connect(target)) as db, db:
            db.execute('CREATE TABLE bars(symbol,market,ts,open,high,low,close,volume)')
            db.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', [
                ('2330', 'TW', int(day.tz_localize('Asia/Taipei').timestamp()), row.Open, row.High,
                 row.Low, row.Close, row.Volume) for day, row in frame.iterrows()])
        before = R.digest(target)
        output = Path(self.temp.name) / '快照'; output.mkdir()
        data, info, sha = R.snapshot_database(target, '2330', str(frame.index[499].date()), output)
        self.assertEqual(len(data), 500)
        self.assertEqual(R.digest(target), before)
        self.assertEqual(sha, R.digest(output / '輸入快照.json'))
        replay = Path(self.temp.name) / '重播'; replay.mkdir()
        replay_data, _, replay_hash = R.replay_snapshot(output / '輸入快照.json', replay)
        self.assertEqual(sha, replay_hash)
        R.pd.testing.assert_frame_equal(data, replay_data)

    def test_walk_forward_train_before_test_and_stitched_returns(self):
        self.analysis.precise_pnl = lambda c, o, w, p, e, f: R.exact_pnl(c, o, w, p, e, .0025, .0055)
        self.analysis.compute_stats = R.corrected_stats
        out = Path(self.temp.name) / '樣本外'
        with R.contextlib.redirect_stdout(R.io.StringIO()):
            p = self.wf.run_walk_forward(self.frame(), R.signals, [15,20,25], [50,60,70],
                output_dir=str(out), row_param='fast', col_param='slow', row_kw='fast', col_kw='slow',
                lookback_days=730, step_days=180, warmup=80, valid_fn=lambda f,s:f<s)
        result = json.loads(Path(p).read_text())
        self.assertGreaterEqual(result['n_runs'], 3)
        for row in result['runs']:
            self.assertLess(row['train_end'], row['test_start'])
        product = R.np.prod([1 + r['test_return'] / 100 for r in result['runs']]) - 1
        # 上游窗口輸出四位小數，允許序列化四捨五入差。
        self.assertAlmostEqual(product * 100, result['oos']['cum'][-1], delta=.002)
        self.analysis.precise_pnl = self.raw_pnl
        self.analysis.compute_stats = self.raw_stats


if __name__ == '__main__':
    unittest.main()
