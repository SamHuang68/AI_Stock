#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import etf_snapshot_health  # noqa: E402


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int = -1) -> bytes:
        # 與真實回應一致：只回傳呼叫端要求的位元組數，截斷才會在測試中現形。
        return self._body if limit is None or limit < 0 else self._body[:limit]


class EtfSnapshotHealthTests(unittest.TestCase):
    def test_probe_reads_a_response_larger_than_one_mebibyte(self):
        expected = {"latestDate": "2026-10-07", "directory": "C:/etf", "latestSha256": "abc"}
        payload = {"date": "2026-10-07", "meta": {"history": dict(expected)},
                   "padding": "x" * (2 * 1024 * 1024)}
        with mock.patch.object(etf_snapshot_health.urllib.request, "urlopen",
                               return_value=_Response(payload)):
            result = etf_snapshot_health.probe_api("http://unit.test/etf-delta", expected)
        self.assertEqual(result["state"], "ok")

    def test_probe_rejects_a_runaway_response_instead_of_truncating_it(self):
        expected = {"latestDate": "2026-10-07", "directory": "C:/etf", "latestSha256": "abc"}
        payload = {"date": "2026-10-07", "padding": "x" * 4096}
        with mock.patch.object(etf_snapshot_health, "MAX_PROBE_BYTES", 1024), \
                mock.patch.object(etf_snapshot_health.urllib.request, "urlopen",
                                  return_value=_Response(payload)):
            result = etf_snapshot_health.probe_api("http://unit.test/etf-delta", expected)
        self.assertEqual(result["state"], "response_too_large")
        self.assertEqual(result["limitBytes"], 1024)

    def test_probe_requires_date_directory_and_hash_to_match(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = {
                "latestDate": "2026-08-28",
                "directory": str(Path(temp) / "shared-data" / "etf_history"),
                "latestSha256": "abc123",
            }
            payload = {
                "date": "2026-08-28",
                "meta": {"history": dict(expected)},
            }
            with mock.patch.object(
                etf_snapshot_health.urllib.request,
                "urlopen",
                return_value=_Response(payload),
            ):
                result = etf_snapshot_health.probe_api(
                    "http://127.0.0.1:18435/etf-delta", expected
                )
            self.assertEqual(result["state"], "ok")
            self.assertEqual(result["mismatches"], [])

    def test_same_date_from_another_history_is_a_contract_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = {
                "latestDate": "2026-08-28",
                "directory": str(Path(temp) / "canonical"),
                "latestSha256": "canonical-hash",
            }
            payload = {
                "date": "2026-08-28",
                "meta": {
                    "history": {
                        "latestDate": "2026-08-28",
                        "directory": str(Path(temp) / "old-release"),
                        "latestSha256": "old-hash",
                    }
                },
            }
            with mock.patch.object(
                etf_snapshot_health.urllib.request,
                "urlopen",
                return_value=_Response(payload),
            ):
                result = etf_snapshot_health.probe_api("http://unit.test/etf-delta", expected)
            self.assertEqual(result["state"], "contract_mismatch")
            self.assertEqual(set(result["mismatches"]), {"directory", "latestSha256"})


if __name__ == "__main__":
    unittest.main()
