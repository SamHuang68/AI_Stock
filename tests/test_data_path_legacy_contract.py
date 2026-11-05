"""legacy 路徑契約（單一資料根階段 2）：各模組解析出的資料／日誌路徑必須與改接 `data_paths` 之前逐項一致。

做法：把 `server/` 複製到暫存目錄（匯入模組的副作用不會落在 repo），每個情境用獨立子行程匯入模組，
再比對常數、函式層級路徑與環境變數覆寫。期望值不是從 `data_paths` 算出來的，而是下面這份獨立寫死的
契約表（由改接前的快照產生），所以解析器本身出錯時這裡一定會紅，不會互相抵銷。

之後階段 3～6 若動到 legacy 解析（寫入守衛、綁定、切換），這份契約要仍然成立，直到 Sam 明確決定改契約。
路徑以 realpath + normcase 比對，避免 Windows 8.3 短檔名或大小寫造成誤判。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 33 個模組、62 個屬性：{模組: {屬性: 相對於程式目錄的路徑}}
CONTRACT = {
    'ai_api': {'_AI_KEY_FILE': 'data/ai_key.bin', '_AI_KEY_LEGACY_FILE': 'data/ai_key.txt'},
    'ai_local': {'TRACE_PATH': 'logs/ai_runtime_trace.jsonl'},
    'alert_daemon': {'CONFIG_FILE': 'data/alert_config.json', 'LOG_DIR': 'logs/alerts', 'OUTBOX_FILE': 'data/alert_outbox.json', 'RULES_FILE': 'data/alert_rules.json', 'SECRETS_FILE': 'data/alert_secrets.bin'},
    'benchmark_research': {'TAI50_CSV': 'data/tai50_daily.csv'},
    'chip_history_tracker': {'CHIP_HISTORY_PATH': 'data/chip_history'},
    'conditional_expectation': {'CHIP_HISTORY_PATH': 'data/chip_history', 'DECISION_DB_PATH': 'data/decision_history.db'},
    'daemon_lock': {'DEFAULT_LOCK_DIR': 'data/runtime_locks'},
    'datasources': {'DATA': 'data'},
    'datastore': {'DB_PATH': 'data/market.db'},
    'decision_context': {'DB_PATH': 'data/decision_history.db', 'TRACE_PATH': 'logs/decision_trace.jsonl'},
    'early_warning': {'DB_PATH': 'data/market_signals.db'},
    'etf_api': {'ETF_CATALOG_FILE': 'data/etf_catalog.json'},
    'etf_delta_tracker': {'CATALOG_FILE': 'data/etf_catalog.json'},
    'llm_gate': {'GATE_PATH': 'data/llm_gate.json'},
    'macro_track': {'CBC_CHANGES': 'data/cbc_policy_rate_changes.csv', 'CBC_DAILY': 'data/cbc_policy_rates.csv', 'DATA': 'data', 'DB_PATH': 'data/macro_track.db', 'MARGIN_MIX_CSV': 'data/tw_margin_mix_daily.csv', 'SEED_DIR': 'data/macro_seeds'},
    'margin_cycle': {'DATA': 'data', 'DB_PATH': 'data/margin_cycle.db'},
    'margin_ratio': {'DATA_DIR': 'data', 'SEED_CSV': 'data/margin_ratio_history.csv'},
    'ohlc_ledger': {'DB_PATH': 'data/ohlc_ledger/ohlc_ledger.db', 'LEDGER_DIR': 'data/ohlc_ledger'},
    'options_exposure': {'CACHE_PATH': 'data/options_structure_cache.json', 'HISTORY_PATH': 'data/options_structure_history.json'},
    'override_alpha': {'DATA': 'data', 'DB': 'data/override_alpha.db'},
    'peak_approvals': {'APPROVALS_DIR': 'data/peak_approvals', 'DB_PATH': 'data/peak_approvals/peak_approvals.db'},
    'pulse_history': {'DB_PATH': 'data/pulse_history.db'},
    'sector_history': {'DB_PATH': 'data/sector_history.db'},
    'server': {'CHIP_HISTORY_PATH': 'data/chip_history', 'DRAW_STORE_FILE': 'data/draw_store.json'},
    'signal_digest': {'STATE_FILE': 'data/stock_signal_push_state.json'},
    'signal_stats_pool': {'CACHE_FILE': 'data/stock_signal_pooled_stats.json', 'CHIP_HISTORY_PATH': 'data/chip_history'},
    'stock_signals_routes': {'CHIP_HISTORY_PATH': 'data/chip_history', 'WATCHLIST_FILE': 'data/stock_signal_watchlist.json'},
    'tdcc_holders': {'DATA': 'data', 'DB_PATH': 'data/tdcc_holders.db'},
    'touxin_ledger': {'CHIP_HISTORY_PATH': 'data/chip_history', 'DB_PATH': 'data/touxin_ledger/touxin_ledger.db', 'LEDGER_DIR': 'data/touxin_ledger'},
    'tw_index_charts': {'DATA_DIR': 'data', 'TWOII_CSV': 'data/twoii_daily.csv', 'TXF_CSV': 'data/txf_daily.csv'},
    'universe': {'CACHE': 'data/universe.json'},
    'watch_daemon': {'LOG_DIR': 'logs/watch', 'RULES_FILE': 'data/watch_rules.json', 'STATE_FILE': 'data/watch_state.json'},
    'wavedeck_bus': {'DATA': 'data', 'STORE': 'data/wavedeck_bus.json'},
}

# 函式層級：key -> 在子行程執行的程式（結果放進 result）。BASE 是另一個暫存目錄，用來測 base_dir 掛鉤。
PROBES = {
    'feature_default': "result = str(load('feature_settings')._local_override_path())",
    'feature_base': "result = str(load('feature_settings')._local_override_path(BASE))",
    'reports_dir': "result = str(load('postmarket_report').reports_dir())",
    'ohlc_base': "result = load('ohlc_ledger')._ledger_db_path(BASE)",
    'peak_base': "result = load('peak_approvals')._approvals_db_path(BASE)",
    'touxin_base': "result = load('touxin_ledger')._ledger_db_path(BASE)",
    'jobs_db': "result = load('job_queue').DurableJobQueue().db_path",
    'pulse_db': "result = load('pulse_updates').PulseUpdates().db_path",
    'pulse_trace': "result = load('pulse_updates').PulseUpdates().trace_path",
    'research_db': "result = type('X', (load('研究整合路由').ResearchIntegrationRoutesMixin,), {'_BASE': BASE})()._research_database()",
    'backup_chip': ("import unittest.mock as um\n"
                    "m = load('backup_data')\n"
                    "with um.patch.object(m.etf_paths, 'resolve_history_dir', return_value='ETF'):\n"
                    "    result = m.source_dirs()[0][1]"),
    # 這兩組在原程式裡被 ``except Exception: pass`` 包住：參數寫錯會讓日誌靜默消失，所以要攔截實際路徑。
    'slog_paths': ("import unittest.mock as um\n"
                   "m = load('slog')\n"
                   "m._CONFIGURED = False          # 同一行程裡別的模組早已呼叫過 setup()，重置才會再走一次檔案日誌設定\n"
                   "with um.patch.object(m.logging, 'FileHandler') as fh, um.patch.object(m.os, 'makedirs') as mk:\n"
                   "    m.setup()\n"
                   "result = json.dumps({'handler': [str(c.args[0]) for c in fh.call_args_list],\n"
                   "                     'mkdir': [str(c.args[0]) for c in mk.call_args_list]})"),
    'server_trace_paths': ("import unittest.mock as um, jsonl_trace\n"
                           "m = load('server')\n"
                           "seen = []\n"
                           "def fake_open(path, *a, **k):\n"
                           "    seen.append(['open', str(path)])\n"
                           "    raise OSError('probe')\n"
                           "with um.patch('builtins.open', fake_open), \\\n"
                           "     um.patch.object(m.os, 'makedirs', lambda p, *a, **k: seen.append(['mkdir', str(p)])), \\\n"
                           "     um.patch.object(jsonl_trace, 'append_jsonl', lambda p, *a, **k: seen.append(['append', str(p)])):\n"
                           "    for call in (lambda: m._keystats_trace('x'), lambda: m._fundamental_trace('x'),\n"
                           "                 lambda: m._ui_route_trace({'route': 'x'}), lambda: m._boot_trace('x'),\n"
                           "                 m._universe_median_pe):\n"
                           "        try:\n"
                           "            call()\n"
                           "        except BaseException as exc:\n"
                           "            seen.append(['exc', type(exc).__name__])\n"
                           "        seen.append(['--', ''])\n"
                           "result = json.dumps(seen)"),
}

CHILD = r'''
import importlib, json, os, sys
root, base, spec_path = sys.argv[1], sys.argv[2], sys.argv[3]
spec = json.load(open(spec_path, encoding='utf-8'))
sys.path.insert(0, os.path.join(root, 'server'))
sys.path.insert(1, root)
os.chdir(base)
mods, out = {}, {'attrs': {}, 'errors': {}, 'probes': {}}

def load(name):
    if name not in mods:
        try:
            mods[name] = importlib.import_module(name)
        except BaseException as exc:
            mods[name] = None
            out['errors'][name] = type(exc).__name__ + ': ' + str(exc)[:200]
    if mods[name] is None:
        raise ImportError(name)
    return mods[name]

for name, attrs in spec['attrs'].items():
    try:
        m = load(name)
    except ImportError:
        continue
    out['attrs'][name] = {a: str(getattr(m, a)) for a in attrs}
for key, code in spec['probes'].items():
    try:
        g = {'load': load, 'BASE': base, 'os': os, 'json': json}
        exec(code, g)
        out['probes'][key] = str(g['result'])
    except BaseException as exc:
        out['probes'][key] = 'EXC ' + type(exc).__name__ + ': ' + str(exc)[:200]
print('@@CONTRACT@@' + json.dumps(out, ensure_ascii=False))
'''


def same(a: str, b: str) -> bool:
    norm = lambda p: os.path.normcase(os.path.realpath(p))   # noqa: E731
    return norm(a) == norm(b)


class LegacyPathContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='st-contract-', ignore_cleanup_errors=True)
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.root = os.path.join(cls._tmp.name, 'root')
        shutil.copytree(ROOT / 'server', os.path.join(cls.root, 'server'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        os.makedirs(os.path.join(cls.root, 'data'))
        cls.base = os.path.join(cls._tmp.name, 'base')
        os.makedirs(cls.base)
        cls.overrides = {
            'LLM_GATE_PATH': os.path.join(cls._tmp.name, 'o', 'gate.json'),
            'ST_AI_TRACE_PATH': os.path.join(cls._tmp.name, 'o', 'ai.jsonl'),
            'ST_REPORTS_DIR': os.path.join(cls._tmp.name, 'o', 'reports'),
            'ST_UPDATE_JOBS_DB': os.path.join(cls._tmp.name, 'o', 'jobs.db'),
        }
        os.makedirs(os.path.join(cls._tmp.name, 'o'))
        cls.clean = cls._run({})
        cls.overridden = cls._run(cls.overrides)

    @classmethod
    def _run(cls, extra_env):
        spec = {'attrs': {m: sorted(a) for m, a in CONTRACT.items()}, 'probes': PROBES}
        spec_path = os.path.join(cls._tmp.name, f'spec-{len(extra_env)}.json')
        Path(spec_path).write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('ST_') and k not in {'LLM_GATE_PATH', 'PYTHONPATH', 'PYTHONHOME'}}
        env.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}, **extra_env)
        # -I 會忽略 PYTHONIOENCODING／PYTHONUTF8；CI 的 Windows 預設是 cp1252，有的模組匯入時會印中文
        # （etf_delta_tracker 找不到目錄時），所以要明確用 -X utf8，不能靠環境變數。
        proc = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', CHILD, cls.root, cls.base, spec_path],
                              capture_output=True, text=True, encoding='utf-8', errors='replace',
                              env=env, cwd=cls.base, timeout=240)
        for line in reversed(proc.stdout.splitlines()):
            if line.startswith('@@CONTRACT@@'):
                return json.loads(line[len('@@CONTRACT@@'):])
        raise AssertionError(f'子行程沒有回報結果 rc={proc.returncode}\n{proc.stderr[-1500:]}')

    def _unavailable_modules(self):
        """只容許「缺少未安裝的第三方套件」造成的匯入失敗；專案內模組匯入失敗一律算錯。"""
        unavailable = {}
        for module, error in self.clean['errors'].items():
            missing = error.split("'")[1] if error.startswith('ModuleNotFoundError') and "'" in error else None
            if missing and not (Path(self.root) / 'server' / f'{missing}.py').exists():
                unavailable[module] = missing
            else:
                self.fail(f'{module} 匯入失敗：{error}')
        return unavailable

    def test_module_constants_keep_the_legacy_layout(self):
        unavailable = self._unavailable_modules()
        checked = 0
        for module, attrs in CONTRACT.items():
            if module in unavailable:
                continue
            for attr, relative in attrs.items():
                with self.subTest(module=module, attr=attr):
                    expected = os.path.join(self.root, *relative.split('/'))
                    actual = self.clean['attrs'][module][attr]
                    self.assertTrue(same(actual, expected), f'{module}.{attr}: {actual!r} != {expected!r}')
                    checked += 1
        # 防止整批被悄悄略過：實際核對的屬性數必須等於契約表扣掉缺套件模組後的總數，且要有相當的數量。
        self.assertEqual(checked, sum(len(a) for m, a in CONTRACT.items() if m not in unavailable))
        self.assertGreaterEqual(checked, 50, f'缺套件而略過的模組：{unavailable}')

    def test_function_level_paths_keep_the_legacy_layout(self):
        p = self.clean['probes']
        expected = {
            'feature_default': os.path.join(self.root, 'data', 'feature_flags.local.json'),
            'feature_base': os.path.join(self.base, 'data', 'feature_flags.local.json'),
            'reports_dir': os.path.join(self.root, 'data', 'reports', 'postmarket'),
            'ohlc_base': os.path.join(self.base, 'data', 'ohlc_ledger', 'ohlc_ledger.db'),
            'peak_base': os.path.join(self.base, 'data', 'peak_approvals', 'peak_approvals.db'),
            'touxin_base': os.path.join(self.base, 'data', 'touxin_ledger', 'touxin_ledger.db'),
            'jobs_db': os.path.join(self.root, 'data', 'update_jobs.sqlite3'),
            'pulse_db': os.path.join(self.root, 'data', 'update_jobs.sqlite3'),
            'pulse_trace': os.path.join(self.root, 'logs', 'pulse_updates.jsonl'),
            'research_db': os.path.join(self.base, 'data', 'market.db'),
            'backup_chip': os.path.join(self.root, 'data', 'chip_history'),
        }
        structured = {'slog_paths', 'server_trace_paths'}          # 另外逐項核對
        self.assertEqual(sorted(expected), sorted(set(PROBES) - structured))
        for key, path in expected.items():
            with self.subTest(probe=key):
                self.assertFalse(p[key].startswith('EXC '), p[key])
                self.assertTrue(same(p[key], path), f'{key}: {p[key]!r} != {path!r}')

    def test_silently_swallowed_log_helpers_write_to_the_legacy_locations(self):
        p = self.clean['probes']
        for key in ('slog_paths', 'server_trace_paths'):
            self.assertFalse(p[key].startswith('EXC '), p[key])
        slog = json.loads(p['slog_paths'])
        with self.subTest('slog.setup'):
            self.assertEqual(len(slog['handler']), 1)
            self.assertTrue(same(slog['handler'][0], os.path.join(self.root, 'data', 'logs', 'server.log')))
            self.assertEqual(len(slog['mkdir']), 1)
            self.assertTrue(same(slog['mkdir'][0], os.path.join(self.root, 'data', 'logs')))
        logs, data = os.path.join(self.root, 'logs'), os.path.join(self.root, 'data')
        expected = [
            ('mkdir', logs), ('append', os.path.join(logs, 'keystats_trace.jsonl')), ('--', ''),
            ('mkdir', logs), ('append', os.path.join(logs, 'fundamental_trace.jsonl')), ('--', ''),
            ('mkdir', logs), ('append', os.path.join(logs, 'ui_route_trace.jsonl')), ('--', ''),
            ('mkdir', logs), ('open', os.path.join(logs, 'SERVER_BOOT.txt')), ('--', ''),
            ('open', os.path.join(data, 'universe.json')), ('--', ''),
        ]
        seen = json.loads(p['server_trace_paths'])
        with self.subTest('server.py 的日誌與資料函式'):
            self.assertEqual([verb for verb, _ in seen], [verb for verb, _ in expected], seen)
            for (verb, actual), (_, want) in zip(seen, expected):
                if want:
                    self.assertTrue(same(actual, want), f'{verb}: {actual!r} != {want!r}')

    def test_environment_overrides_keep_their_precedence(self):
        o = self.overrides
        got = {
            'LLM_GATE_PATH': self.overridden['attrs']['llm_gate']['GATE_PATH'],
            'ST_AI_TRACE_PATH': self.overridden['attrs']['ai_local']['TRACE_PATH'],
            'ST_REPORTS_DIR': self.overridden['probes']['reports_dir'],
            'ST_UPDATE_JOBS_DB': self.overridden['probes']['jobs_db'],
        }
        for name, value in got.items():
            with self.subTest(env=name):
                self.assertTrue(same(value, o[name]), f'{name}: {value!r} != {o[name]!r}')
        with self.subTest(env='ST_UPDATE_JOBS_DB (PulseUpdates)'):
            self.assertTrue(same(self.overridden['probes']['pulse_db'], o['ST_UPDATE_JOBS_DB']))
        with self.subTest('覆寫只影響各自的路徑'):
            self.assertTrue(same(self.overridden['probes']['pulse_trace'], os.path.join(self.root, 'logs', 'pulse_updates.jsonl')))
            self.assertTrue(same(self.overridden['attrs']['datastore']['DB_PATH'], os.path.join(self.root, 'data', 'market.db')))


if __name__ == '__main__':
    unittest.main()
