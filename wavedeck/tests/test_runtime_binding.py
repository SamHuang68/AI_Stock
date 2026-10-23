"""Offline checks for WaveDeck's production storage adapters; no server starts."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RuntimeBindingTests(unittest.TestCase):
    def child(self, body):
        with tempfile.TemporaryDirectory(prefix="wd-runtime-offline-") as folder:
            env = {k: v for k, v in os.environ.items() if k not in {
                "ST_DATA_BINDING", "ST_DATA_ROOT", "ST_RUNTIME_ROLE", "ST_URL",
                "LLM_GATE_PATH", "ST_ETF_HISTORY_DIR", "ST_REPORTS_DIR", "ST_UPDATE_JOBS_DB",
                "OPENAI_API_KEY", "WAVEDECK_SECRET",
            }}
            env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
            prefix = f'''
import json, os, sys, uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
fixture = Path({folder!r})
(fixture / ".st-fixture.json").write_text(json.dumps({{
    "schemaVersion": 1, "kind": "fixture", "fixtureId": str(uuid.uuid4())
}}), encoding="utf-8")
os.environ["ST_DATA_ROOT"] = str(fixture)
os.environ["ST_RUNTIME_ROLE"] = "fixture"
sys.path.insert(0, str(Path({str(ROOT)!r}) / "wavedeck"))
import runtime_paths as paths
'''
            done = subprocess.run([sys.executable, "-B", "-c", textwrap.dedent(prefix) + textwrap.dedent(body)],
                                  env=env, cwd=folder, capture_output=True, text=True,
                                  encoding="utf-8", timeout=15)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_fixture_requires_lease_before_state_import(self):
        self.child('''
from runtime_storage import StorageOwnershipError
try:
    from server import state
except StorageOwnershipError:
    pass
else:
    raise AssertionError("state import granted its own writer permission")
assert not (fixture / "wavedeck").exists()
''')

    def test_state_config_audit_and_markdown_use_wavedeck_namespace(self):
        self.child('''
lease = paths.bootstrap()
from server import state, config, audit, exec_md
state.RUNTIME.patch(style=42)
config.save_config({"mode": "paper", "broker": {"kind": "paper"}})
audit.write("fixture", {"ok": True})
folder = exec_md._dir()
exec_md._update_index(folder, {"file": "fixture.md"})
assert state.STATE_PATH == fixture / "wavedeck/runtime_state.json"
assert config.CONFIG_PATH == fixture / "wavedeck/wavedeck_config.json"
assert (fixture / "wavedeck/wavedeck_audit.db").is_file()
assert (fixture / "wavedeck/exec_md/index.json").is_file()
assert config.SECRETS_PATH == paths.ROOT / "data/wavedeck_secrets.json"
with patch.object(config, "_read_json", side_effect=AssertionError("fixture must not read old secrets")):
    config.load_secrets()
assert paths.describe()["portFile"] == str(fixture / "wavedeck/wavedeck.port")
try:
    paths.guard_write(fixture / "llm_gate.json")
except RuntimeError:
    pass
else:
    raise AssertionError("WaveDeck could write the ST namespace")
lease.close()
try:
    state.RUNTIME.save()
except RuntimeError:
    pass
else:
    raise AssertionError("closed lease still allowed state writes")
''')

    def test_legacy_paths_and_release_identity_stay_code_local(self):
        self.child('''
from data_paths import resolve_binding
legacy = resolve_binding(code_root=paths.CODE_ROOT, environ={})
with patch.object(paths, "BINDING", legacy):
    assert paths.runtime_data("runtime_state.json") == paths.ROOT / "data/runtime_state.json"
    assert paths.runtime_logs() == paths.ROOT / "logs"
    assert paths.registered_txt_dir({}) == paths.ROOT / "data/master"
from server.版本身分 import read_release_identity
import hashlib
code = fixture / "code"
(code / "data").mkdir(parents=True)
files = {}
for relative in ("VERSION", "run.py", "runtime_paths.py", "web/index.html", "web/js/deck.js", "web/css/deck.css"):
    target = code / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture", encoding="utf-8")
    files[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
(code / "data/程式版本.json").write_text(json.dumps({"commit": "a" * 40, "files": files}), encoding="utf-8")
identity = read_release_identity(code)
assert identity["releaseVerified"] is True and identity["runtimeCommit"] == "a" * 40
files.pop("runtime_paths.py")
(code / "data/程式版本.json").write_text(json.dumps({"commit": "a" * 40, "files": files}), encoding="utf-8")
assert read_release_identity(code)["releaseVerified"] is False
''')

    def test_legacy_write_guard_still_rejects_a_marked_production_target(self):
        self.child('''
from data_paths import resolve_binding
legacy = resolve_binding(code_root=paths.CODE_ROOT, environ={})
protected = fixture / "marked-production"
protected.mkdir()
(protected / ".st-data-root.json").write_text(json.dumps({"kind": "production"}), encoding="utf-8")
with patch.object(paths, "BINDING", legacy):
    try:
        paths.guard_write(protected / "target_position.txt")
    except RuntimeError:
        pass
    else:
        raise AssertionError("legacy adapter bypassed the production marker guard")
assert not (protected / "target_position.txt").exists()
''')

    def test_standalone_research_refuses_before_importing_writable_consumers(self):
        self.child('''
import importlib.util
source = paths.CODE_ROOT / "scripts/個股研究資料更新.py"
spec = importlib.util.spec_from_file_location("research_update_fixture", source)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
for operation in (lambda: script.main([]),
                  lambda: script.run_update(["--start", "2026-10-10", "--end", "2026-10-10"])):
    try:
        operation()
    except RuntimeError:
        pass
    else:
        raise AssertionError("standalone research obtained writer ownership")
assert "datastore" not in sys.modules and "chip_history_tracker" not in sys.modules
assert not (fixture / "market.db").exists()
assert not (fixture / "stock_research_update.jsonl").exists()
''')

    def test_external_state_and_config_do_not_replace_missing_or_invalid_data(self):
        self.child('''
paths.bootstrap()
from server import state, config
target = fixture / "wavedeck/required.json"
for contents in (None, "broken json", "[]"):
    if contents is None:
        if target.exists():
            target.unlink()
    else:
        target.write_text(contents, encoding="utf-8")
    with patch.object(state, "BINDING", SimpleNamespace(mode="external")), patch.object(state, "STATE_PATH", target):
        for operation in (lambda: state.Runtime._load(object.__new__(state.Runtime)),
                          lambda: config._read_json(target, required=True)):
            try:
                operation()
            except (RuntimeError, ValueError):
                pass
            else:
                raise AssertionError("missing or corrupt external data became an empty default")
    assert (target.read_text(encoding="utf-8") if target.exists() else None) == contents
''')

    def test_external_boot_requires_registered_existing_state_and_config(self):
        self.child('''
from data_paths import binding_for
code = fixture / "installed-code"
data = fixture / "external-data"
recovery = fixture / "recovery"
code.mkdir()
data.mkdir()
recovery.mkdir()
root_id = str(uuid.uuid4())
installation = {"schemaVersion": 1, "storageMode": "external", "capabilityVersion": 1,
    "dataRoot": str(data), "dataRootId": root_id, "recoveryRoot": str(recovery),
    "allowedCodeRoots": [str(code)], "backendUrl": "http://127.0.0.1:18599", "publicUrl": "http://127.0.0.1:18598"}
(data / ".st-data-root.json").write_text(json.dumps({"schemaVersion": 1, "kind": "production", "dataRootId": root_id}), encoding="utf-8")
(data / "market.db").write_bytes(b"fixture")
receipt = {"schemaVersion": 1, "state": "ready", "dataRootId": root_id,
           "capabilityVersion": 1, "requiredPaths": ["market.db"]}
receipt_path = data / ".st-cutover.json"
receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
bound = binding_for(code_root=code, environ={"ST_RUNTIME_ROLE": "wavedeck"}, installation_binding=installation)
with patch.object(paths, "BINDING", bound), patch.object(paths, "bootstrap_runtime", side_effect=AssertionError("lease acquired before data check")):
    for operation in (paths.bootstrap, paths.describe):
        try:
            operation()
        except RuntimeError:
            pass
        else:
            raise AssertionError("external startup accepted absent WaveDeck data")
    assert not (data / "wavedeck").exists()
    (data / "wavedeck").mkdir()
    for relative in paths.REQUIRED_RUNTIME_PATHS:
        (data / relative).write_text("{}", encoding="utf-8")
    try:
        paths.describe()
    except RuntimeError:
        pass
    else:
        raise AssertionError("existing but unregistered WaveDeck data accepted")
    receipt["requiredPaths"].extend(paths.REQUIRED_RUNTIME_PATHS)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert paths.describe()["dataDir"] == str(data / "wavedeck")
''')

    def test_txt_requires_explicit_fixture_registration_and_stays_inside_namespace(self):
        self.child('''
paths.bootstrap()
from server import broker, config
target = fixture / "wavedeck/master"
target.mkdir(parents=True)
settings = {"mode": "paper", "broker": {"kind": "paper", "txt_fixture": True, "txt_dir": str(target)}}
config.save_config(settings)
broker.write_txt_target(2, "TEST")
assert (target / "target_position.txt").read_text() == "TEST 2\\n"
for value in ({}, {"txt_fixture": True, "txt_dir": str(fixture)},
              {"txt_fixture": True, "txt_dir": "relative"}):
    try:
        paths.registered_txt_dir(value)
    except RuntimeError:
        pass
    else:
        raise AssertionError("unregistered or cross-namespace TXT target accepted")
with patch.object(paths, "BINDING", SimpleNamespace(mode="external")):
    try:
        paths.registered_txt_dir(settings["broker"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("production TXT destination was implicitly enabled")
with patch.object(broker, "load_config", return_value={"broker": {**settings["broker"], "target_file": "../escape.txt"}}):
    try:
        broker.write_txt_target(1)
    except ValueError:
        pass
    else:
        raise AssertionError("TXT filename escaped its registered directory")
assert not (fixture / "escape.txt").exists()
with patch.object(config, "BINDING", SimpleNamespace(mode="external")), \
     patch.object(config, "_read_json", return_value={"mode": "live", "broker": {"kind": "txt_master"}}), \
     patch.object(config, "registered_txt_dir", side_effect=RuntimeError("unregistered live target")):
    try:
        config.load_config()
    except RuntimeError:
        pass
    else:
        raise AssertionError("existing live config bypassed target registration")
''')

    def test_gate_requires_identity_and_explicit_acquisition(self):
        self.child('''
from server import gate_bridge
bound = SimpleNamespace(mode="external", data_root_id="fixture-root-id", capability_version=1)
identity = {"dataRootId": bound.data_root_id, "storageMode": "external", "runtimeRole": "backend", "storageCapability": 1, "ok": True}
with patch.object(gate_bridge, "BINDING", bound):
    for response in ({**identity, "acquired": False, "owner": "wd", "held": True},
                     {**identity, "acquired": True, "owner": "st", "held": True},
                     {**identity, "acquired": True, "owner": "wd", "held": True, "dataRootId": "other"}):
        with patch.object(gate_bridge, "_request", side_effect=[identity, response]):
            try:
                gate_bridge.request_gate("acquire")
            except RuntimeError:
                pass
            else:
                raise AssertionError("unverified gate acquisition accepted")
    with patch.object(gate_bridge, "_request", side_effect=[identity, {**identity, "acquired": True, "owner": "wd", "held": True}]) as request:
        gate_bridge.request_gate("acquire")
        assert request.call_args.args[1]["expectedDataRootId"] == bound.data_root_id
    with patch.object(gate_bridge, "_request", side_effect=[{**identity, "dataRootId": "other"}]) as request:
        try:
            gate_bridge.request_gate("release")
        except RuntimeError:
            pass
        else:
            raise AssertionError("wrong backend identity accepted")
        assert request.call_count == 1
    with patch.object(gate_bridge, "_request", side_effect=[identity, {**identity, "released": False}]):
        try:
            gate_bridge.request_gate("release")
        except RuntimeError:
            pass
        else:
            raise AssertionError("unconfirmed gate release accepted")
with patch.object(gate_bridge, "_request", side_effect=AssertionError("fixture attempted HTTP")):
    try:
        gate_bridge.request_gate("acquire")
    except RuntimeError:
        pass
    else:
        raise AssertionError("fixture gained a production gate")
''')

    def test_gate_failure_never_calls_provider_or_releases_unowned_lock(self):
        self.child('''
paths.bootstrap()
from server import providers, st_link, st_push
primary = Mock(name="primary")
primary.name = "ollama"
fallback = {"process": {}, "summary": "fixture"}
with patch.object(providers, "resolve_provider", return_value=primary), \
     patch.object(providers, "_llm_gate_acquire", side_effect=RuntimeError("denied")), \
     patch.object(providers, "_llm_gate_release") as release, \
     patch.object(providers.HeuristicProvider, "infer", return_value=fallback):
    output, error = providers.infer_with_fallback({})
    assert error == "denied" and output["provider"] == "heuristic"
    primary.infer.assert_not_called()
    release.assert_not_called()
with patch.object(st_link.threading, "Thread", side_effect=AssertionError("fixture heartbeat started")):
    st_link.start()
    st_push.push_async()
    assert st_push.push_to_st(force=True) is False
assert st_link.ST_URL == st_push.ST_URL == ""
from server import exec_md
with patch.object(exec_md.urllib.request, "urlopen", side_effect=AssertionError("fixture requested a model")):
    assert exec_md._ollama_narrative({}, {}, 1) is None
''')

    def test_external_narrative_waits_for_gate_before_model_call(self):
        self.child('''
paths.bootstrap()
from server import exec_md, gate_bridge
with patch.object(exec_md, "BINDING", SimpleNamespace(mode="external")), \
     patch.object(exec_md, "load_config", return_value={}), \
     patch.object(gate_bridge, "request_gate", side_effect=RuntimeError("busy")) as gate, \
     patch.object(exec_md.urllib.request, "urlopen", side_effect=AssertionError("model started without gate")) as network:
    assert exec_md._ollama_narrative({}, {}, 1) is None
    network.assert_not_called()
    gate.assert_called_once_with("acquire")
''')


if __name__ == "__main__":
    unittest.main()
