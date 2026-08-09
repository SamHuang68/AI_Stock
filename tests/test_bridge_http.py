#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP-level ST↔WD bridge smoke (stdlib only)."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "wavedeck"))

import wavedeck_bus as wdb  # noqa: E402


def _post_json(url: str, body: dict, origin: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw}


class BridgeHttpSmoke(unittest.TestCase):
    def test_wavedeck_bus_age_and_hot_stage(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "wavedeck_bus.json"
            with mock.patch.object(wdb, "DATA", Path(td)), mock.patch.object(wdb, "STORE", store):
                with wdb._lock:
                    wdb._state["report"] = None
                    wdb._state["report_at"] = None
                    wdb._state["report_epoch_ms"] = None
                    wdb._state["costs"] = {
                        "st_local_calls": 0,
                        "st_cloud_calls": 0,
                        "st_cloud_usd_est": 0.0,
                        "wd_session_usd": 0.0,
                        "wd_day_usd": 0.0,
                        "wd_month_usd": 0.0,
                        "wd_local_calls": 0,
                        "wd_cloud_calls": 0,
                        "wd_provider": None,
                        "updated_at": None,
                    }
                snap = wdb.accept_report(
                    {
                        "fsm": "InPosition",
                        "mode": "paper",
                        "style": 55,
                        "ai": {"action": "HOLD", "action_label": "維持續抱"},
                        "costs": {"day_usd": 0.01, "provider": "heuristic", "local_calls": 0},
                        "st_overlay": {
                            "aggressiveness": 55,
                            "spillover_prob": 0.71,
                            "hot_stage": "先進封裝",
                            "leaders": ["日月光"],
                            "rotation": "broad",
                        },
                    }
                )
                self.assertTrue(snap["ok"])
                self.assertTrue(snap["fresh"])
                self.assertIsNotNone(snap["age_sec"])
                self.assertLessEqual(snap["age_sec"], 5)
                self.assertEqual(snap["report"]["st_overlay"]["hot_stage"], "先進封裝")
                self.assertEqual(snap["wavedeck"]["hot_stage"], "先進封裝")
                self.assertAlmostEqual(float(snap["wavedeck"]["spillover_prob"]), 0.71)

    def test_wd_bridge_st_http_spillover(self):
        from server.engine import apply_st_bridge  # noqa: WPS433
        from server import server as wd_server  # noqa: WPS433
        from server.state import RUNTIME  # noqa: WPS433

        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "runtime_state.json"
            with mock.patch("server.state.DATA", Path(td)), mock.patch(
                "server.state.STATE_PATH", state_path
            ), mock.patch("server.audit.DATA", Path(td)):
                # Direct apply (same as POST /bridge/st handler body)
                snap = apply_st_bridge(
                    {
                        "style": 60,
                        "delever": False,
                        "note": "http-test",
                        "meta": {
                            "spillover_prob": 0.18,
                            "rotation": "narrow",
                            "hot_stage": "記憶體",
                            "source": "unit-http",
                        },
                    }
                )
                ov = snap["st_overlay"]
                self.assertTrue(ov["delever"])  # forced by low spillover
                self.assertAlmostEqual(float(ov["spillover_prob"]), 0.18)
                self.assertEqual(ov["hot_stage"], "記憶體")

                # Spin WD HTTP server briefly
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), wd_server.Handler)
                port = httpd.server_address[1]
                t = threading.Thread(target=httpd.serve_forever, daemon=True)
                t.start()
                try:
                    code, j = _post_json(
                        f"http://127.0.0.1:{port}/bridge/st",
                        {
                            "style": 50,
                            "delever": False,
                            "note": "via-http",
                            "meta": {"spillover_prob": 0.55, "rotation": "mixed", "hot_stage": "散熱"},
                        },
                    )
                    self.assertEqual(code, 200)
                    self.assertTrue(j.get("ok"))
                    ov2 = (j.get("state") or {}).get("st_overlay") or {}
                    self.assertAlmostEqual(float(ov2.get("spillover_prob")), 0.55)
                    self.assertEqual(ov2.get("hot_stage"), "散熱")
                finally:
                    httpd.shutdown()
                    httpd.server_close()

    def test_estimate_openai_usd(self):
        sys.path.insert(0, str(ROOT / "wavedeck"))
        from server.providers import estimate_openai_usd  # noqa: WPS433

        usd = estimate_openai_usd({"prompt_tokens": 1000, "completion_tokens": 500}, "gpt-4o-mini")
        # 1000*0.15 + 500*0.60 = 150+300 = 450 / 1e6 = 0.00045
        self.assertAlmostEqual(usd, 0.00045)


if __name__ == "__main__":
    unittest.main()
