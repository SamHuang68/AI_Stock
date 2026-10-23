#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run an isolated production ST backend and its private Web gateway.

Development ST remains on 18432.  The promoted private copy uses an isolated
backend on 18435 and exposes only the authenticated gateway on 18434.
"""
from __future__ import annotations

import argparse
import json
import os
import runpy
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"


def _port(value: str, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 1024 <= port <= 65535 else default


def _health_payload(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read(16 * 1024).decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _health(url: str, timeout: float = 2.0) -> bool:
    payload = _health_payload(url, timeout)
    return bool(payload and payload.get("ok"))


def _port_available(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _append_host_event(event: str, **details: object) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": "private_web_host",
        "event": event,
        **details,
    }
    with (LOGS / "private_web_host.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _spawn(log_name: str, argv: list[str], env: dict[str, str]) -> tuple[subprocess.Popen, object]:
    LOGS.mkdir(parents=True, exist_ok=True)
    stream = (LOGS / log_name).open("a", encoding="utf-8", buffering=1)
    process = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return process, stream


def _runtime_environment(backend_port: int, gateway_port: int):
    env = dict(os.environ)
    binding_path = ROOT.parent / 'runtime_binding.json'
    explicit = binding_path.exists() or any(name in env for name in
                                           ('ST_DATA_BINDING', 'ST_DATA_ROOT', 'ST_RUNTIME_ROLE'))
    if not explicit:
        manifest_path = ROOT / '.private_web_release.json'
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            if manifest.get('storageBinding', {}).get('storageMode') == 'external':
                raise RuntimeError('external host binding is missing; legacy fallback refused')
        return None, env
    helpers = runpy.run_path(str(ROOT / 'server' / 'data_paths.py'))
    if env.get('ST_RUNTIME_ROLE') not in (None, '', 'backend'):
        raise RuntimeError('host requires the backend runtime role')
    if binding_path.exists():
        env.setdefault('ST_RUNTIME_ROLE', 'backend')
    binding = helpers['validate_binding'](helpers['resolve_binding'](code_root=ROOT, environ=env,
        installation_binding=binding_path if binding_path.exists() else None), expected_role='backend')
    if binding.mode != 'external':
        raise RuntimeError('private host requires an external managed binding when runtime options are set')
    if not binding_path.is_file():
        raise RuntimeError('private host requires its managed runtime_binding.json for the authenticated gateway')
    helpers['validate_release_capability'](ROOT, binding)
    if (binding.backend_url != f'http://127.0.0.1:{backend_port}'
            or binding.public_url != f'http://127.0.0.1:{gateway_port}'):
        raise RuntimeError('host ports conflict with the installation binding')
    env['ST_DATA_ROOT'] = str(binding.data_root)
    env['ST_RUNTIME_ROLE'] = 'backend'
    if binding_path.exists():
        env['ST_DATA_BINDING'] = str(binding_path)
    return binding, env


def _child_environments(runtime_env, backend_port, gateway_port, instance_id):
    backend_env = dict(runtime_env, ST_HOST='127.0.0.1', ST_PORT=str(backend_port))
    # The authenticated proxy owns only its existing local auth adjuncts. It
    # never opens the business database and must not inherit a writer binding.
    gateway_env = {key: value for key, value in runtime_env.items()
                   if key not in {'ST_DATA_ROOT', 'ST_DATA_BINDING', 'ST_RUNTIME_ROLE'}}
    gateway_env.update(ST_WEB_UPSTREAM=f'http://127.0.0.1:{backend_port}',
                       ST_WEB_LISTEN_HOST='127.0.0.1', ST_WEB_LISTEN_PORT=str(gateway_port),
                       ST_WEB_INSTANCE_ID=instance_id, ST_WEB_MODE='isolated-host')
    return backend_env, gateway_env


def _host_output_paths() -> tuple[Path, ...]:
    return (LOGS / "private_web_host.jsonl", LOGS / "private_web_backend.log",
            LOGS / "private_web_gateway.log", ROOT / "data" / "private_web_host.pid")


def _assert_host_outputs(binding) -> None:
    """外部資料根模式下，host 的日誌與 PID 檔不得碰到受保護的資料根／復原根，也不得是硬連結別名。

    這些檔案都以 append 或覆寫方式寫入；路徑若被誤指到正式資料或與正式檔案互為硬連結，會改到不屬於 host 的資料。
    必須在探測埠、建立目錄或啟動子程序之前檢查（審查 ST-R2）。"""
    helpers = runpy.run_path(str(ROOT / 'server' / 'data_paths.py'))
    protected = tuple(Path(os.path.realpath(root)) for root in helpers['protected_roots'](binding))
    for output in _host_output_paths():
        path = Path(output).absolute()
        real = Path(os.path.realpath(path))
        for root in protected:
            if real == root or root in real.parents or real in root.parents:
                raise RuntimeError('host output overlaps a protected runtime/recovery root')
        helpers['assert_no_links'](path)


def run(*, backend_port: int, gateway_port: int, max_restarts: int) -> int:
    binding, runtime_env = _runtime_environment(backend_port, gateway_port)
    if binding is not None:
        _assert_host_outputs(binding)
    owner_token = ROOT / "data" / "private_web_owner.token"
    if not owner_token.is_file():
        print(f"Missing {owner_token}; run: {sys.executable} scripts/setup_private_web.py", file=sys.stderr)
        return 2

    run_id = uuid4().hex
    gateway_url = f"http://127.0.0.1:{gateway_port}/gateway/health"
    existing_gateway = _health_payload(gateway_url)
    if existing_gateway and existing_gateway.get("gateway") == "private-web":
        _append_host_event(
            "preflight_blocked",
            runId=run_id,
            reason="gateway_already_running",
            port=gateway_port,
            existingMode=existing_gateway.get("mode", "unknown"),
        )
        print(
            f"[FAIL] Private Web ST is already running on 127.0.0.1:{gateway_port}.\n"
            "Run STOP_PRIVATE_WEB.cmd first, then start isolated host mode.",
            file=sys.stderr,
        )
        return 3
    if not _port_available("127.0.0.1", gateway_port):
        _append_host_event(
            "preflight_blocked",
            runId=run_id,
            reason="gateway_port_in_use",
            port=gateway_port,
        )
        print(
            f"[FAIL] Gateway port 127.0.0.1:{gateway_port} is used by another process.",
            file=sys.stderr,
        )
        return 3
    if not _port_available("127.0.0.1", backend_port):
        _append_host_event(
            "preflight_blocked",
            runId=run_id,
            reason="backend_port_in_use",
            port=backend_port,
        )
        print(
            f"[FAIL] Backend port 127.0.0.1:{backend_port} is used by another process.",
            file=sys.stderr,
        )
        return 3

    stopping = False

    def request_stop(_signum=None, _frame=None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    attempts: list[float] = []
    while not stopping:
        now = time.monotonic()
        attempts = [stamp for stamp in attempts if now - stamp < 300]
        if len(attempts) >= max_restarts:
            _append_host_event(
                "restart_budget_exhausted", runId=run_id, attempts=len(attempts)
            )
            print("Private Web ST stopped after repeated startup failures.", file=sys.stderr)
            return 1
        attempts.append(now)
        attempt = len(attempts)
        instance_id = f"{run_id}-{attempt}"

        backend_env, gateway_env = _child_environments(runtime_env, backend_port, gateway_port, instance_id)

        backend = gateway = None
        backend_log = gateway_log = None
        try:
            _append_host_event(
                "backend_start", runId=run_id, attempt=attempt, port=backend_port
            )
            backend, backend_log = _spawn(
                "private_web_backend.log",
                [sys.executable, "-u", str(ROOT / "server" / "server.py")],
                backend_env,
            )
            _append_host_event(
                "backend_spawned", runId=run_id, attempt=attempt, pid=backend.pid
            )
            backend_probe_started = time.monotonic()
            backend_ready = False
            for _ in range(60):
                if stopping or backend.poll() is not None:
                    break
                live = _health_payload(f"http://127.0.0.1:{backend_port}/health/live") if binding is not None else None
                if ((binding is None and _health(f"http://127.0.0.1:{backend_port}/health/live"))
                    or (binding is not None and live and live.get('ok') is True
                        and live.get('dataRootId') == binding.data_root_id
                        and live.get('runtimeRole') == 'backend'
                        and live.get('storageMode') == 'external'
                        and live.get('capabilityVersion') == binding.capability_version)):
                    backend_ready = True
                    break
                time.sleep(0.5)
            if stopping:
                break
            if backend.poll() is not None:
                raise RuntimeError(f"backend exited with {backend.returncode}")
            if not backend_ready:
                raise RuntimeError("backend liveness timeout")
            _append_host_event(
                "backend_ready",
                runId=run_id,
                attempt=attempt,
                pid=backend.pid,
                elapsedMs=round((time.monotonic() - backend_probe_started) * 1000),
                probe="/health/live",
            )

            _append_host_event(
                "gateway_start", runId=run_id, attempt=attempt, port=gateway_port
            )
            gateway, gateway_log = _spawn(
                "private_web_gateway.log",
                [sys.executable, "-u", str(ROOT / "server" / "private_web_gateway.py")],
                gateway_env,
            )
            _append_host_event(
                "gateway_spawned",
                runId=run_id,
                attempt=attempt,
                pid=gateway.pid,
                instance=instance_id,
            )
            gateway_ready = False
            for _ in range(30):
                if stopping:
                    break
                if gateway.poll() is not None:
                    break
                payload = _health_payload(gateway_url)
                if (
                    payload
                    and payload.get("gateway") == "private-web"
                    and payload.get("instance") == instance_id
                    and payload.get("upstream") is True
                ):
                    gateway_ready = True
                    break
                time.sleep(0.5)
            if stopping:
                break
            if gateway.poll() is not None:
                raise RuntimeError(f"gateway exited with {gateway.returncode}")
            if not gateway_ready:
                raise RuntimeError("gateway identity/health timeout")

            _append_host_event(
                "ready",
                runId=run_id,
                attempt=attempt,
                backendPort=backend_port,
                gatewayPort=gateway_port,
                instance=instance_id,
            )
            print(f"Private Web ST ready: http://127.0.0.1:{gateway_port}/")
            while not stopping and backend.poll() is None and gateway.poll() is None:
                time.sleep(1)
            if not stopping:
                _append_host_event(
                    "child_exit",
                    runId=run_id,
                    attempt=attempt,
                    backendExit=backend.poll(),
                    gatewayExit=gateway.poll(),
                )
        except Exception as exc:
            _append_host_event(
                "startup_failure",
                runId=run_id,
                attempt=attempt,
                errorType=type(exc).__name__,
                error=str(exc),
            )
        finally:
            _stop(gateway)
            _stop(backend)
            if gateway_log:
                gateway_log.close()
            if backend_log:
                backend_log.close()
        if not stopping:
            time.sleep(2)
    _append_host_event("stopped", runId=run_id)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated Private Web ST")
    parser.add_argument("--backend-port", type=int, default=_port(os.environ.get("ST_WEB_BACKEND_PORT", "18435"), 18435))
    parser.add_argument("--gateway-port", type=int, default=_port(os.environ.get("ST_WEB_LISTEN_PORT", "18434"), 18434))
    parser.add_argument("--max-restarts", type=int, default=5)
    args = parser.parse_args()
    _runtime_environment(_port(str(args.backend_port), 18435), _port(str(args.gateway_port), 18434))
    pid_path = _host_output_paths()[3]
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()) + "\n", encoding="ascii")
    try:
        code = run(
            backend_port=_port(str(args.backend_port), 18435),
            gateway_port=_port(str(args.gateway_port), 18434),
            max_restarts=max(1, min(20, args.max_restarts)),
        )
    finally:
        pid_path.unlink(missing_ok=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
