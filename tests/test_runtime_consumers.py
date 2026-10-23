"""在新程序與合成資料根驗證 consumer 接線；不開啟既有資料庫或連網。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
PATH_ENV = ('ST_DATA_ROOT', 'ST_RUNTIME_ROLE', 'ST_DATA_BINDING', 'ST_UPDATE_JOBS_DB',
            'ST_ETF_HISTORY_DIR', 'ST_REPORTS_DIR', 'ST_AI_TRACE_PATH', 'LLM_GATE_PATH')


class RuntimeConsumerTests(unittest.TestCase):
    def run_consumer(self, body, *, fixture=True):
        with tempfile.TemporaryDirectory(prefix='st-consumers-') as directory:
            root = Path(directory) / 'runtime'
            root.mkdir()
            (root / '.st-fixture.json').write_text(json.dumps({
                'schemaVersion': 1, 'kind': 'fixture', 'fixtureId': str(uuid.uuid4()),
            }), encoding='utf-8')
            (root / 'etf_catalog.json').write_text(json.dumps({'categories': [{'etfs': [
                {'code': '00981A', 'name': '合成 ETF', 'enabled': True, 'market': 'TW'},
            ]}]}), encoding='utf-8')
            environment = {key: value for key, value in os.environ.items() if key not in PATH_ENV}
            environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                               ST_CONSUMER_FIXTURE=str(root), ST_CONSUMER_CODE=str(ROOT))
            if fixture:
                environment.update(ST_RUNTIME_ROLE='fixture', ST_DATA_ROOT=str(root))
            prefix = '''
import importlib, json, os, socket, sqlite3, sys
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch
ROOT = Path(os.environ['ST_CONSUMER_CODE'])
DATA = Path(os.environ['ST_CONSUMER_FIXTURE'])
sys.path.insert(0, str(ROOT / 'server'))
def no_network(*args, **kwargs):
    raise AssertionError('consumer fixture 禁止連網')
socket.create_connection = no_network
socket.getaddrinfo = no_network
'''
            result = subprocess.run([sys.executable, '-B', '-c', textwrap.dedent(prefix) + textwrap.dedent(body)],
                                    cwd=directory, env=environment, capture_output=True,
                                    text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_consumers_share_bound_data_and_keep_code_roots(self):
        self.run_consumer('''
expected = {
    'datastore': {'DB_PATH': 'market.db'},
    'decision_context': {'DB_PATH': 'decision_history.db', 'TRACE_PATH': 'logs/decision_trace.jsonl'},
    'early_warning': {'DB_PATH': 'market_signals.db'},
    'conditional_expectation': {'DECISION_DB_PATH': 'decision_history.db', 'CHIP_HISTORY_PATH': 'chip_history'},
    'sector_history': {'DB_PATH': 'sector_history.db'},
    'pulse_history': {'DB_PATH': 'pulse_history.db'},
    'macro_track': {'DB_PATH': 'macro_track.db', 'CBC_DAILY': 'cbc_policy_rates.csv',
                    'CBC_CHANGES': 'cbc_policy_rate_changes.csv', 'MARGIN_MIX_CSV': 'tw_margin_mix_daily.csv',
                    'SEED_DIR': 'macro_seeds'},
    'margin_cycle': {'DB_PATH': 'margin_cycle.db'},
    'tdcc_holders': {'DB_PATH': 'tdcc_holders.db'},
    'override_alpha': {'DB': 'override_alpha.db'},
    'touxin_ledger': {'DB_PATH': 'touxin_ledger/touxin_ledger.db', 'CHIP_HISTORY_PATH': 'chip_history'},
    'ohlc_ledger': {'DB_PATH': 'ohlc_ledger/ohlc_ledger.db'},
    'peak_approvals': {'DB_PATH': 'peak_approvals/peak_approvals.db'},
    'chip_history_tracker': {'CHIP_HISTORY_PATH': 'chip_history'},
    'stock_signals_routes': {'WATCHLIST_FILE': 'stock_signal_watchlist.json', 'CHIP_HISTORY_PATH': 'chip_history'},
    'signal_stats_pool': {'CACHE_FILE': 'stock_signal_pooled_stats.json', 'CHIP_HISTORY_PATH': 'chip_history'},
    'options_exposure': {'CACHE_PATH': 'options_structure_cache.json', 'HISTORY_PATH': 'options_structure_history.json'},
    'universe': {'CACHE': 'universe.json'},
    'datasources': {'DATA': '.'},
    'margin_ratio': {'SEED_CSV': 'margin_ratio_history.csv'},
    'tw_index_charts': {'TWOII_CSV': 'twoii_daily.csv', 'TXF_CSV': 'txf_daily.csv'},
    'wavedeck_bus': {'STORE': 'wavedeck_bus.json'},
    'benchmark_research': {'TAI50_CSV': 'tai50_daily.csv'},
    'etf_delta_tracker': {'CATALOG_FILE': 'etf_catalog.json'},
    'alert_daemon': {'CONFIG_FILE': 'alert_config.json', 'RULES_FILE': 'alert_rules.json',
                     'OUTBOX_FILE': 'alert_outbox.json', 'LOG_DIR': 'logs/alerts'},
    'watch_daemon': {'RULES_FILE': 'watch_rules.json', 'STATE_FILE': 'watch_state.json', 'LOG_DIR': 'logs/watch'},
    'signal_digest': {'STATE_FILE': 'stock_signal_push_state.json'},
    'llm_gate': {'GATE_PATH': 'llm_gate.json'},
    'ai_local': {'TRACE_PATH': 'logs/ai_runtime_trace.jsonl'},
}
for name, attributes in expected.items():
    module = importlib.import_module(name)
    for attribute, relative in attributes.items():
        assert Path(getattr(module, attribute)) == DATA / relative, (name, attribute)
import ai_local, alert_daemon, datasources, etf_paths, feature_settings, options_schedule
import postmarket_report, job_queue, pulse_updates, backup_data, etf_snapshot_health
from ETF更新診斷 import run_directory
from 研究整合路由 import ResearchIntegrationRoutesMixin
assert ai_local.ROOT == ROOT
assert Path(datasources._BASE) == ROOT
assert Path(alert_daemon.SECRETS_FILE) == ROOT / 'data/alert_secrets.bin'
assert etf_paths.resolve_history_dir() == DATA / 'etf_history'
assert run_directory() == DATA / 'etf_history/_runs'
assert etf_snapshot_health._trace_path() == DATA / 'logs/etf_snapshot_trace.jsonl'
assert feature_settings._local_override_path() == DATA / 'feature_flags.local.json'
assert options_schedule._data_dir() == DATA
assert postmarket_report.reports_dir() == DATA / 'reports/postmarket'
assert Path(job_queue.DurableJobQueue().db_path) == DATA / 'update_jobs.sqlite3'
pulse = pulse_updates.PulseUpdates()
assert Path(pulse.db_path) == DATA / 'update_jobs.sqlite3'
assert Path(pulse.trace_path) == DATA / 'logs/pulse_updates.jsonl'
handler = type('FixtureHandler', (ResearchIntegrationRoutesMixin,), {'_BASE': str(ROOT)})()
assert Path(handler._research_database()) == DATA / 'market.db'
assert dict(backup_data.source_dirs()) == {'chip_history': str(DATA / 'chip_history'),
                                         'etf_history': str(DATA / 'etf_history')}
assert datasources._st_db()['count'] == 0
assert datasources._st_margin_ratio()['count'] == 0
assert datasources._st_tdcc_holders()['count'] == 0
assert not list(DATA.rglob('*.db')), '唯讀路徑盤點不得建庫'
''')

    def test_database_consumers_refuse_unowned_or_missing_files(self):
        self.run_consumer('''
import datastore, decision_context, decision_store, early_warning, sector_history
import pulse_history, macro_track, margin_cycle, tdcc_holders, override_alpha
import touxin_ledger, ohlc_ledger, peak_approvals, job_queue, pulse_updates
from runtime_storage import bootstrap_runtime, StorageOwnershipError
writers = [datastore.get_conn, lambda: decision_store.connect(DATA / 'decision_history.db'),
           lambda: decision_context._connect(str(DATA / 'decision_history.db')),
           lambda: early_warning._connect(str(DATA / 'market_signals.db')),
           lambda: sector_history._init(str(DATA / 'sector_history.db')),
           pulse_history._conn, macro_track._db, margin_cycle._db, tdcc_holders._db,
           override_alpha._conn, touxin_ledger.get_conn, ohlc_ledger.get_conn,
           peak_approvals.get_conn, job_queue.DurableJobQueue()._connect,
           pulse_updates.PulseUpdates()._connect]
def all_refused():
    for writer in writers:
        try:
            writer()
        except StorageOwnershipError:
            continue
        raise AssertionError('未取得權限或缺庫仍進入寫入：' + repr(writer))
all_refused()
with bootstrap_runtime(code_root=ROOT):
    all_refused()
assert not list(DATA.rglob('*.db')) and not list(DATA.rglob('*.sqlite3'))
''')

    def test_existing_package_imports_keep_the_same_runtime_binding(self):
        self.run_consumer('''
sys.path.remove(str(ROOT / 'server'))
sys.path.insert(0, str(ROOT))
for name in ('datastore', 'alert_daemon', 'stock_signals_routes', 'feature_settings',
             'decision_store', 'touxin_ledger', 'ohlc_ledger', 'peak_approvals',
             'override_alpha', 'macro_track', 'ai_local', 'llm_gate'):
    module = importlib.import_module('server.' + name)
    if hasattr(module, 'data_paths'):
        assert module.data_paths.data_root() == DATA, name
assert not list(DATA.rglob('*.db'))
''')

    def test_override_import_never_connects_or_acquires_a_lease(self):
        self.run_consumer('''
sys.path.insert(0, str(ROOT))
before = {path.relative_to(DATA) for path in DATA.rglob('*')}
with patch.object(sqlite3, 'connect', side_effect=AssertionError('匯入不得開啟 SQLite')):
    for name in ('override_alpha', 'server.override_alpha'):
        module = importlib.import_module(name)
        assert module.DB == DATA / 'override_alpha.db'
assert not getattr(sys, '_st_runtime_leases', {})
assert {path.relative_to(DATA) for path in DATA.rglob('*')} == before
assert not (DATA / 'override_alpha.db').exists()
''')

    def test_override_business_calls_require_lease_and_existing_database(self):
        self.run_consumer('''
import override_alpha as alpha
from runtime_storage import bootstrap_runtime, StorageOwnershipError
calls = (alpha.init_db, lambda: alpha.log_event({'note': '拒絕'}),
         alpha.recent, alpha.summary_for_review)
def refused():
    for call in calls:
        try:
            call()
        except StorageOwnershipError:
            continue
        raise AssertionError('無 lease 或缺資料庫時仍允許業務呼叫')
refused()
assert not alpha.DB.exists()
with bootstrap_runtime(code_root=ROOT):
    refused()
    assert not alpha.DB.exists()
    alpha.DB.touch()  # 僅建立本案例自己的小型 SQLite fixture。
    result = alpha.log_event({'style': 2, 'delever': True, 'note': '合成覆寫',
                              'source': 'fixture', 'meta': {'score': 3.0}})
    assert result['ok'] and result['id'] == 1
    alpha.init_db()
    rows = alpha.recent()
    assert len(rows) == 1 and rows[0]['note'] == '合成覆寫'
    assert rows[0]['delever'] is True and rows[0]['score'] == 3.0
    assert '合成覆寫' in alpha.summary_for_review()
refused()
with closing(sqlite3.connect(alpha.DB.as_uri() + '?mode=ro', uri=True)) as connection:
    assert connection.execute('SELECT COUNT(*) FROM override_log').fetchone()[0] == 1
''')

    def test_override_first_read_initializes_only_with_lease(self):
        self.run_consumer('''
import override_alpha as alpha
from runtime_storage import bootstrap_runtime
alpha.DB.touch()
with bootstrap_runtime(code_root=ROOT):
    assert alpha.recent() == []
    assert alpha.summary_for_review() == '尚無覆寫紀錄。'
with closing(sqlite3.connect(alpha.DB.as_uri() + '?mode=ro', uri=True)) as connection:
    assert connection.execute("SELECT name FROM sqlite_master WHERE name='override_log'").fetchone()
''')

    def test_real_storage_roundtrip_and_chip_ledger_use_one_root(self):
        self.run_consumer('''
from runtime_storage import bootstrap_runtime
import datastore, chip_history_tracker, touxin_ledger, stock_signals_routes, tw_index_charts
for relative in ('market.db', 'touxin_ledger/touxin_ledger.db'):
    target = DATA / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
with bootstrap_runtime(code_root=ROOT):
    datastore.init_db()
    with closing(datastore.get_conn()) as connection, connection:
        connection.execute('INSERT INTO meta VALUES(?,?,?,?)', ('DEMO', 'TW', '合成行情', 1))
    with datastore.read_snapshot() as connection:
        assert connection.execute('SELECT name FROM meta').fetchone()[0] == '合成行情'
    stock_signals_routes.save_watchlist([{'sym': '2330', 'market': 'TW'}])
    assert stock_signals_routes.load_watchlist() == [{'sym': '2330', 'market': 'TW'}]
    tw_index_charts._write_csv(tw_index_charts.TWOII_CSV, [('2026-09-24', 1, 2, 1, 2, 100)])
    assert '2026-09-24' in (DATA / 'twoii_daily.csv').read_text(encoding='utf-8')
    payload = {'stat': 'OK', 'date': '20260924',
               'fields': ['證券代號', '投信買賣超股數', '三大法人買賣超股數',
                          '外陸資買賣超股數', '自營商買賣超股數'],
               'data': [['2330', '0', '100', '100', '0']]}
    with patch.object(chip_history_tracker, 'fetch_t86', return_value=payload), \
         patch.object(chip_history_tracker, 'taipei_today', return_value=date(2026, 9, 24)):
        assert chip_history_tracker.parse_and_save('20260924') == 1
    assert json.loads((DATA / 'chip_history/20260924.json').read_text(encoding='utf-8'))['2330']['trust'] == 0
    with closing(touxin_ledger.get_conn()) as connection:
        assert connection.execute('SELECT trust_net_shares FROM touxin_daily').fetchone()[0] == 0
assert not (DATA.parent / 'data/touxin_ledger').exists(), '不得反推程式根再追加 data'
''')

    def test_conflicting_overrides_and_unowned_direct_writes_fail(self):
        self.run_consumer('''
from data_paths import BindingError
from runtime_storage import StorageOwnershipError
import job_queue, pulse_updates, llm_gate, tw_index_charts, etf_paths, postmarket_report
import datasources, options_exposure, breadth_build, backup_data, alert_daemon
from 研究工作流 import build_subject
other = DATA.parent / 'other'
with patch.object(datasources.subprocess, 'Popen', side_effect=AssertionError('不得建立第二寫入程序')):
    refusal = datasources._spawn('chip_history_tracker.py')
    assert not refusal['ok'] and not refusal['started']
    assert refusal['reason'] == 'RUNTIME_WRITER_REQUIRED'
for factory in (lambda: job_queue.DurableJobQueue(other / 'jobs.db'),
                lambda: pulse_updates.PulseUpdates(trace_path=other / 'trace.jsonl'),
                lambda: build_subject('2330', other / 'market.db'),
                lambda: build_subject('2330', DATA / 'market.db', chip_directory=other)):
    try:
        factory()
    except BindingError:
        pass
    else:
        raise AssertionError('衝突覆寫未被拒絕')
for key, callback in (('ST_ETF_HISTORY_DIR', etf_paths.resolve_history_dir),
                      ('ST_REPORTS_DIR', postmarket_report.reports_dir)):
    with patch.dict(os.environ, {key: str(other)}):
        try:
            callback()
        except BindingError:
            pass
        else:
            raise AssertionError(key + ' 衝突未被拒絕')
for writer in (lambda: llm_gate._write({'owner': 'fixture'}),
               lambda: tw_index_charts._write_csv(tw_index_charts.TWOII_CSV, []),
               lambda: etf_paths.resolve_history_dir(create=True),
               lambda: options_exposure._write_disk_cache({}),
               lambda: options_exposure._write_history_rows([]),
               alert_daemon.start):
    try:
        writer()
    except StorageOwnershipError:
        pass
    else:
        raise AssertionError('無 writer lease 仍寫入')
assert not (DATA / 'llm_gate.json').exists()
assert not (DATA / 'twoii_daily.csv').exists()
assert not (DATA / 'etf_history').exists()
assert not (DATA / 'options_structure_cache.json').exists()
assert not (DATA / 'options_structure_history.json').exists()
breadth_build.breadth_trace(str(ROOT), 'fixture')
assert not (DATA / 'logs').exists(), '未持有 writer lease 不得先建立日誌目錄'
with patch.object(backup_data, 'BACKUP_DIR', str(other)), \
     patch.object(backup_data.zipfile, 'ZipFile', side_effect=AssertionError('不得建立備份')):
    try:
        backup_data.main()
    except RuntimeError as exc:
        assert '拒絕壓縮' in str(exc)
    else:
        raise AssertionError('fixture 備份入口未拒絕')
assert not other.exists()
''')

    def test_legacy_explicit_paths_and_relative_trace_remain_compatible(self):
        self.run_consumer('''
import data_paths, feature_settings, touxin_ledger, job_queue, pulse_updates, etf_paths
base = DATA.parent / 'legacy-fixture'
assert data_paths.binding_for().mode == 'legacy'
assert feature_settings._local_override_path(base) == base / 'data/feature_flags.local.json'
assert Path(touxin_ledger._ledger_db_path(base)) == base / 'data/touxin_ledger/touxin_ledger.db'
with patch.dict(os.environ, {'ST_UPDATE_JOBS_DB': str(base / 'environment.db')}):
    assert Path(job_queue.DurableJobQueue(base / 'explicit.db').db_path) == base / 'explicit.db'
    assert Path(pulse_updates.PulseUpdates(base / 'explicit.db').db_path) == base / 'explicit.db'
assert etf_paths.resolve_history_dir(environ={'LOCALAPPDATA': str(base)}) == base / 'StockTerminalPrivateWeb/shared-data/etf_history'
with patch.dict(os.environ, {'ST_AI_TRACE_PATH': 'logs/fixture-ai.jsonl'}):
    import ai_local
    assert ai_local.TRACE_PATH == ROOT / 'logs/fixture-ai.jsonl'
assert not base.exists(), '純路徑解析不得建立 legacy 目錄'
''', fixture=False)

    def test_standalone_reports_refuse_before_source_config_or_delivery(self):
        self.run_consumer('''
from contextlib import ExitStack
from data_paths import binding_for
sys.path.insert(0, str(ROOT))
import alert_daemon, etf_report_email, daily_morning_brief
assert binding_for().mode == 'fixture'
with ExitStack() as stack:
    guarded = [(etf_report_email, 'fetch_delta'), (daily_morning_brief, '_pct_daily'),
               (daily_morning_brief, '_txf'), (alert_daemon, 'load_config'),
               (alert_daemon, 'push_email')]
    calls = [stack.enter_context(patch.object(module, name, side_effect=AssertionError(name)))
             for module, name in guarded]
    assert etf_report_email.main() == 2
    assert daily_morning_brief.main() == 2
    assert all(call.call_count == 0 for call in calls)
assert not (DATA / 'alert_config.json').exists()
assert not (DATA / 'logs').exists()
''')

    def test_legacy_standalone_reports_keep_existing_flow_offline(self):
        self.run_consumer('''
from contextlib import ExitStack
from data_paths import binding_for
sys.path.insert(0, str(ROOT))
import alert_daemon, etf_report_email, daily_morning_brief
assert binding_for().mode == 'legacy'
with ExitStack() as stack:
    load = stack.enter_context(patch.object(alert_daemon, 'load_config', return_value={}))
    send = stack.enter_context(patch.object(alert_daemon, 'push_email', return_value=(True, 'fixture')))
    fetch = stack.enter_context(patch.object(etf_report_email, 'fetch_delta', return_value={'etfs': []}))
    stack.enter_context(patch.object(etf_report_email.etf_report, 'build_report_html', return_value=('合成', '<p>合成</p>')))
    stack.enter_context(patch.object(etf_report_email.etf_report, 'build_report_text', return_value='合成'))
    prices = stack.enter_context(patch.object(daily_morning_brief, '_pct_daily', return_value=(100.0, 1.0)))
    futures = stack.enter_context(patch.object(daily_morning_brief, '_txf', return_value=(20000.0, 1.0, 2.0)))
    assert etf_report_email.main() == 0
    assert daily_morning_brief.main() == 0
    assert fetch.call_count == 1 and prices.call_count == len(daily_morning_brief.DRIVERS) + 2
    assert futures.call_count == 1 and load.call_count == 2 and send.call_count == 2
''', fixture=False)

    def test_batch_preflight_precedes_file_side_effects(self):
        # 僅核對 BAT 入口契約，不啟動 BAT、排程、檔案清理或寄信。
        self.assertTrue((ROOT / 'scripts/assert_standalone_runtime.ps1').is_file())
        for name in ('daily_chip.bat', 'daily_morning_brief.bat'):
            with self.subTest(name=name):
                source = (ROOT / 'scripts' / name).read_text(encoding='utf-8')
                body, refused = source.split(':bound_runtime_refused', 1)
                first_effect = min(body.index('mkdir'), body.index('>>'), body.index('forfiles'))
                self.assertLess(body.index('assert_standalone_runtime.ps1'), first_effect)
                self.assertLess(body.index('if errorlevel 1 goto bound_runtime_refused'), first_effect)
                for variable in ('ST_DATA_BINDING', 'ST_DATA_ROOT', 'ST_RUNTIME_ROLE'):
                    self.assertLess(body.index(f'if defined {variable} goto bound_runtime_refused'), first_effect)
                self.assertTrue(body.rstrip().endswith('exit /b %RC%'))
                self.assertTrue(refused.rstrip().endswith('exit /b 2'))
                self.assertFalse(any(token in refused for token in ('mkdir', '>>', 'forfiles', 'python ')))


if __name__ == '__main__':
    unittest.main()
