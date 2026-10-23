"""Explicit opt-in: real ST/WD processes, synthetic shared root, no external I/O."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('ST_RUNTIME_E2E') == '1',
                     'explicit isolated runtime process acceptance is required')
class RuntimeBackendProcessTests(unittest.TestCase):
    def test_real_services_share_fixture_root_and_reject_second_st_writer(self):
        with tempfile.TemporaryDirectory(prefix='st-runtime-e2e-') as directory:
            base = Path(directory)
            data = base / 'runtime'
            data.mkdir()
            (data / '.st-fixture.json').write_text(json.dumps({
                'schemaVersion': 1, 'kind': 'fixture', 'fixtureId': str(uuid.uuid4()),
            }), encoding='utf-8')
            for relative in ('market.db', 'update_jobs.sqlite3', 'decision_history.db',
                             'pulse_history.db', 'market_signals.db', 'sector_history.db',
                             'macro_track.db', 'margin_cycle.db', 'tdcc_holders.db',
                             'override_alpha.db', 'touxin_ledger/touxin_ledger.db',
                             'ohlc_ledger/ohlc_ledger.db', 'peak_approvals/peak_approvals.db'):
                target = data / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            (data / 'etf_catalog.json').write_text('{"categories": []}', encoding='utf-8')
            environment = {k: v for k, v in os.environ.items()
                           if k != 'LLM_GATE_PATH' and
                           not k.startswith(('ST_', 'WD_', 'WAVEDECK_', 'OPENAI_', 'ANTHROPIC_', 'TELEGRAM_', 'SMTP_', 'FINMIND_', 'TUSHARE_'))}
            # The checked-in fixture blocks outbound connections. The outer
            # verification harness additionally blocks reserved production ports.
            old_path = environment.get('PYTHONPATH', '')
            blocker = str(ROOT / 'tests/fixtures/launcher_loopback_only')
            environment.update(ST_RUNTIME_ROLE='fixture', ST_DATA_ROOT=str(data),
                               ST_HOST='127.0.0.1', WAVEDECK_HOST='127.0.0.1',
                               PYTHONPATH=os.pathsep.join(filter(None, (old_path, blocker))),
                               PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                               LOCALAPPDATA=str(base / 'LocalAppData'), APPDATA=str(base / 'AppData'))
            processes = []
            streams = []

            def port():
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    return sock.getsockname()[1]

            def start(script, env, name):
                log = base / (name + '.log')
                stream = log.open('wb')
                streams.append(stream)
                process = subprocess.Popen([sys.executable, '-B', '-u', str(ROOT / script)],
                                           cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                processes.append(process)
                return process, log

            def health(process, log, number, path):
                end = time.monotonic() + 35
                while time.monotonic() < end and process.poll() is None:
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{number}{path}', timeout=1) as response:
                            return json.load(response)
                    except (OSError, urllib.error.URLError):
                        time.sleep(.1)
                self.fail('fixture service did not start: ' + log.read_text(encoding='utf-8', errors='replace')[-8000:])

            try:
                st_port = port()
                st, st_log = start('server/server.py', dict(environment, ST_PORT=str(st_port)), 'st')
                live = health(st, st_log, st_port, '/health/live')
                self.assertIs(live['ok'], True)
                self.assertEqual((live['storageMode'], live['runtimeRole']), ('fixture', 'fixture'))
                second_port = port()
                second, second_log = start('server/server.py', dict(environment, ST_PORT=str(second_port)), 'second-st')
                self.assertNotEqual(second.wait(timeout=15), 0)
                self.assertIn('another process owns', second_log.read_text(encoding='utf-8', errors='replace'))
                self.assertIsNone(st.poll(), 'rejected contender must not stop the existing fixture writer')
                wd_port = port()
                wd, wd_log = start('wavedeck/run.py', dict(environment, WAVEDECK_PORT=str(wd_port)), 'wd')
                status = health(wd, wd_log, wd_port, '/health')
                self.assertIs(status['ok'], True)
                self.assertEqual(status['storageMode'], 'fixture')
                self.assertEqual(Path(status['dataDir']), data / 'wavedeck')
                self.assertEqual(status['pid'], wd.pid)
                self.assertEqual(status['port'], wd_port)
                self.assertTrue((data / 'wavedeck/wavedeck.port').is_file())
                self.assertTrue((data / 'runtime_locks/st-backend.writer.lock').is_file())
                self.assertTrue((data / 'runtime_locks/wavedeck-backend.writer.lock').is_file())
            finally:
                # Only terminate Popen handles created by this test. No PID/port
                # discovery or installed service control is used.
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)
                for stream in streams:
                    stream.close()
