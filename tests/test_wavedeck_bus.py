#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ST wavedeck_bus reverse bus + cost meter smoke tests."""
from __future__ import annotations

import sys
import json
import threading
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import wavedeck_bus as wdb  # noqa: E402


class WaveDeckBusSmoke(unittest.TestCase):
    def test_saves_serialize_snapshot_and_commit_without_old_report_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / 'wavedeck_bus.json'
            entered, release, second_started, second_done = [threading.Event() for _ in range(4)]
            saved_state = deepcopy(wdb._state)
            writer = wdb.atomic_write_json
            failures = []
            def paused_write(path, value, **kwargs):
                if value['report']['symbol'] == 'OLD':
                    entered.set()
                    if not release.wait(3):
                        raise AssertionError('舊寫入未收到放行通知')
                writer(path, value, **kwargs)
            def report(symbol):
                try:
                    if symbol == 'NEW':
                        second_started.set()
                    wdb.accept_report({'symbol': symbol, 'positions': {'account': 1}})
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    if symbol == 'NEW':
                        second_done.set()
            try:
                with mock.patch.object(wdb, 'STORE', store), mock.patch.object(wdb, 'atomic_write_json', side_effect=paused_write):
                    first = threading.Thread(target=report, args=('OLD',))
                    second = threading.Thread(target=report, args=('NEW',))
                    first.start()
                    try:
                        self.assertTrue(entered.wait(2))
                        second.start()
                        self.assertTrue(second_started.wait(2))
                        self.assertFalse(second_done.wait(0.1), '新回報不得越過尚未提交的舊快照')
                    finally:
                        release.set()
                        first.join(3)
                        if second.ident is not None:
                            second.join(3)
                    self.assertFalse(first.is_alive() or second.is_alive())
                    self.assertEqual(failures, [])
                    self.assertEqual(json.loads(store.read_text(encoding='utf-8'))['report']['symbol'], 'NEW')
                    self.assertEqual(wdb.snapshot()['report']['symbol'], 'NEW')
            finally:
                wdb._state = saved_state

    def test_save_failure_is_observable_and_keeps_previous_disk_snapshot(self):
        self.addCleanup(setattr, wdb, '_state', deepcopy(wdb._state))
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / 'wavedeck_bus.json'
            with mock.patch.object(wdb, 'STORE', store):
                wdb.accept_report({'symbol': 'SAVED'})
                before = store.read_bytes()
                with mock.patch.object(wdb, 'atomic_write_json', side_effect=OSError('磁碟不可寫')), mock.patch.object(wdb, 'log_once') as warning:
                    wdb.accept_report({'symbol': 'NEW'})
                self.assertEqual(store.read_bytes(), before)
                warning.assert_called_once()

    def test_origin_allows_wd_ports(self):
        self.assertTrue(wdb.is_wavedeck_origin("http://127.0.0.1:18433/"))
        self.assertTrue(wdb.is_wavedeck_origin("http://localhost:18765"))
        self.assertFalse(wdb.is_wavedeck_origin("http://127.0.0.1:18432/"))
        self.assertFalse(wdb.is_wavedeck_origin("http://127.0.0.1:18434/"))
        self.assertFalse(wdb.is_wavedeck_origin("http://127.0.0.1:18435/"))
        self.assertFalse(wdb.is_wavedeck_origin("https://evil.example/"))

    def test_accept_report_and_costs(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "wavedeck_bus.json"
            with mock.patch.object(wdb, "DATA", Path(td)), mock.patch.object(wdb, "STORE", store):
                with wdb._lock:
                    wdb._state["report"] = None
                    wdb._state["costs"] = {
                        "st_local_calls": 0,
                        "st_cloud_calls": 0,
                        "st_cloud_usd_est": 0.0,
                        "wd_session_usd": 0.0,
                        "wd_day_usd": 0.0,
                        "wd_month_usd": 0.0,
                        "wd_provider": None,
                        "updated_at": None,
                    }
                snap = wdb.accept_report(
                    {
                        "fsm": "InPosition",
                        "mode": "paper",
                        "style": 55,
                        "symbol": "TXF",
                        "ai": {"action": "HOLD", "action_label": "維持續抱", "confidence": 0.6},
                        "positions": {"account": 1},
                        "costs": {"session_usd": 0.2, "day_usd": 1.5, "provider": "heuristic"},
                        "st_overlay": {"aggressiveness": 55, "delever": False, "spillover_prob": 0.5},
                        "source": "unit",
                    }
                )
                self.assertTrue(snap["ok"])
                self.assertEqual(snap["report"]["fsm"], "InPosition")
                self.assertEqual(snap["costs"]["wd_day_usd"], 1.5)
                wdb.record_st_local(2)
                wdb.record_st_cloud(0.03, 1)
                snap2 = wdb.snapshot()
                self.assertEqual(snap2["costs"]["st_local_calls"], 2)
                self.assertEqual(snap2["costs"]["st_cloud_calls"], 1)
                self.assertAlmostEqual(snap2["costs"]["combined_usd_est"], 1.53)
                chip = snap["report"].get("chip") or snap.get("chip")
                self.assertIsNotNone(chip)
                self.assertEqual(chip["symbol"], "TXF")
                self.assertEqual(chip["direction"], "LONG")
                self.assertEqual(chip["position_size"], 1)

    def test_chip_payload_and_sse_broadcast(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "wavedeck_bus.json"
            with mock.patch.object(wdb, "DATA", Path(td)), mock.patch.object(wdb, "STORE", store):
                with wdb._lock:
                    wdb._state["report"] = None
                    wdb._subscribers.clear()
                q = wdb.subscribe()
                try:
                    wdb.accept_report(
                        {
                            "fsm": "InPosition",
                            "mode": "live",
                            "symbol": "2330",
                            "ai": {
                                "action": "HOLD",
                                "confidence": 0.65,
                                "invalidation": {"side": "below", "price": 935.0},
                            },
                            "positions": {"account": 2},
                            "st_overlay": {"aggressiveness": 40, "delever": True},
                        }
                    )
                    evt = q.get(timeout=1.0)
                    self.assertEqual(evt["event_type"], "POSITION_STATE_CHANGE")
                    d = evt["data"]
                    self.assertEqual(d["symbol"], "2330")
                    self.assertEqual(d["market"], "TW")
                    self.assertEqual(d["direction"], "LONG")
                    self.assertEqual(d["position_size"], 2)
                    self.assertAlmostEqual(float(d["invalidation_price"]), 935.0)
                    self.assertEqual(d["wd_mode"], "REAL")
                    sync = wdb.full_sync_event()
                    self.assertEqual(sync["event_type"], "FULL_SYNC")
                    self.assertEqual(len(sync["data"]["positions"]), 1)
                finally:
                    wdb.unsubscribe(q)


if __name__ == "__main__":
    unittest.main()
