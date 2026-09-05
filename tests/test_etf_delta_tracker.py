#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
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

import etf_delta_tracker  # noqa: E402
import etf_paths  # noqa: E402


def _universe(count: int = 10) -> dict[str, tuple[str, str]]:
    return {
        f"00{index:03d}": (f"00{index:03d}", f"ETF {index}")
        for index in range(count)
    }


def _holding(code: str) -> list[dict]:
    return [{"rank": 1, "code": "2330", "name": "台積電", "weight": 20, "shares": 1000}]


class EtfDeltaTrackerTests(unittest.TestCase):
    def test_tls_certificate_verification_stays_enabled(self):
        import ssl
        self.assertTrue(etf_delta_tracker._SSL_CTX.check_hostname)
        self.assertEqual(etf_delta_tracker._SSL_CTX.verify_mode, ssl.CERT_REQUIRED)

    def test_twse_preserves_active_etf_code_and_requires_provider_date(self):
        payload = {'stat': 'OK', 'fields': ['代號', '名稱', '權重'], 'data': [['2330', '台積電', '10']]}
        with mock.patch.object(etf_delta_tracker, 'http_get', return_value=json.dumps(payload)) as request:
            rows, day = etf_delta_tracker.fetch_twse('00410A', dt.date(2026, 9, 5))
            self.assertIsNone(rows)
            self.assertIsNone(day)
            self.assertIn('stockNo=00410A', request.call_args.args[0])
        payload['date'] = '20260904'
        with mock.patch.object(etf_delta_tracker, 'http_get', return_value=json.dumps(payload)):
            rows, day = etf_delta_tracker.fetch_twse('00410A', dt.date(2026, 9, 5))
            self.assertEqual(day, '2026-09-04')
            self.assertEqual(rows[0]['code'], '2330')

    def test_catalog_excludes_explicit_us_and_disabled_entries(self):
        catalog = {
            "categories": [
                {
                    "etfs": [
                        {"code": "0050", "name": "元大台灣50", "market": "TW", "enabled": True},
                        {"code": "SPY", "name": "SPDR S&P 500", "market": "US", "enabled": True},
                        {"code": "00631L", "name": "元大台灣50正2", "market": "TW", "enabled": False},
                    ]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with mock.patch.object(etf_delta_tracker, "CATALOG_FILE", str(path)):
                loaded = etf_delta_tracker.load_catalog()
        self.assertEqual(set(loaded), {"0050"})

    def test_first_snapshot_requires_catalog_coverage_and_writes_manifest(self):
        day = dt.date(2026, 8, 28)
        universe = _universe()

        def fetch_ok(code: str, _target: dt.date):
            return _holding(code), day.isoformat(), "fixture"

        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {etf_paths.ENV_HISTORY_DIR: str(Path(temp).resolve())}
        ), mock.patch.object(etf_delta_tracker, "ETFS", universe), mock.patch.object(
            etf_delta_tracker, "fetch_one", side_effect=fetch_ok
        ):
            self.assertTrue(etf_delta_tracker.run(day))
            path = Path(temp) / f"top10_active_etf_holdings_{day.isoformat()}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload["meta"]
        self.assertEqual(meta["expectedCount"], 10)
        self.assertEqual(meta["succeededCount"], 10)
        self.assertEqual(meta["failedCodes"], [])
        self.assertEqual(meta["successRatio"], 1.0)
        self.assertEqual(len(meta["catalogFingerprint"]), 16)

    def test_historical_snapshot_freshness_is_anchored_to_target_session(self):
        day = dt.date(2020, 1, 2)
        universe = _universe()

        def fetch_ok(code: str, _target: dt.date):
            return _holding(code), day.isoformat(), "fixture"

        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {etf_paths.ENV_HISTORY_DIR: str(Path(temp).resolve())}
        ), mock.patch.object(etf_delta_tracker, "ETFS", universe), mock.patch.object(
            etf_delta_tracker, "fetch_one", side_effect=fetch_ok
        ):
            self.assertTrue(etf_delta_tracker.run(day))
            # 指定交易日快照必須可重播；不能因測試牆鐘日期前進而腐化。
            self.assertTrue(
                (Path(temp) / f"top10_active_etf_holdings_{day.isoformat()}.json").is_file()
            )

    def test_low_coverage_does_not_create_or_poison_first_snapshot(self):
        day = dt.date(2026, 8, 28)
        universe = _universe()
        successful = set(list(universe)[:3])

        def fetch_partial(code: str, _target: dt.date):
            if code in successful:
                return _holding(code), day.isoformat(), "fixture"
            return None, None, None

        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {etf_paths.ENV_HISTORY_DIR: str(Path(temp).resolve())}
        ), mock.patch.object(etf_delta_tracker, "ETFS", universe), mock.patch.object(
            etf_delta_tracker, "fetch_one", side_effect=fetch_partial
        ):
            self.assertFalse(etf_delta_tracker.run(day))
            path = Path(temp) / f"top10_active_etf_holdings_{day.isoformat()}.json"
            self.assertFalse(path.exists())

    def test_unknown_provider_date_is_not_replaced_by_collection_date(self):
        day = dt.date(2026, 8, 28)
        universe = _universe()

        def fetch_without_provider_date(code: str, _target: dt.date):
            return _holding(code), None, "fixture"

        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ, {etf_paths.ENV_HISTORY_DIR: str(Path(temp).resolve())}
        ), mock.patch.object(etf_delta_tracker, "ETFS", universe), mock.patch.object(
            etf_delta_tracker, "fetch_one", side_effect=fetch_without_provider_date
        ):
            self.assertFalse(etf_delta_tracker.run(day))
            path = Path(temp) / f"top10_active_etf_holdings_{day.isoformat()}.json"
            self.assertFalse(path.exists())

    def test_stale_same_day_snapshot_is_refetched_instead_of_skipped(self):
        day = dt.date(2026, 8, 28)
        stale_day = dt.date(2026, 8, 20)
        universe = _universe()

        def fetch_ok(code: str, _target: dt.date):
            return _holding(code), day.isoformat(), "fixture"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / f"top10_active_etf_holdings_{day.isoformat()}.json"
            stale_payload: dict[str, object] = {"date": day.isoformat()}
            for code in universe:
                stale_payload[code] = {
                    "date": stale_day.isoformat(),
                    "source": "fixture-old",
                    "holdings": _holding(code),
                }
            path.write_text(json.dumps(stale_payload), encoding="utf-8")
            with mock.patch.dict(os.environ, {etf_paths.ENV_HISTORY_DIR: str(root)}), mock.patch.object(
                etf_delta_tracker, "ETFS", universe
            ), mock.patch.object(etf_delta_tracker, "fetch_one", side_effect=fetch_ok) as fetch:
                self.assertTrue(etf_delta_tracker.run(day))
                self.assertEqual(fetch.call_count, len(universe))
            refreshed = json.loads(path.read_text(encoding="utf-8"))
            quarantined = list(root.glob(path.name + ".invalid-*"))
        self.assertEqual(refreshed["meta"]["succeededCount"], len(universe))
        self.assertEqual(len(quarantined), 1)

    def test_same_day_legacy_snapshot_is_refetched_for_catalog_manifest(self):
        day = dt.date(2026, 8, 28)
        universe = _universe()

        def fetch_ok(code: str, _target: dt.date):
            return _holding(code), day.isoformat(), "fixture"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / f"top10_active_etf_holdings_{day.isoformat()}.json"
            legacy_payload: dict[str, object] = {"date": day.isoformat()}
            for code in universe:
                legacy_payload[code] = {
                    "date": day.isoformat(),
                    "source": "fixture-old",
                    "holdings": _holding(code),
                }
            path.write_text(json.dumps(legacy_payload), encoding="utf-8")
            with mock.patch.dict(os.environ, {etf_paths.ENV_HISTORY_DIR: str(root)}), mock.patch.object(
                etf_delta_tracker, "ETFS", universe
            ), mock.patch.object(etf_delta_tracker, "fetch_one", side_effect=fetch_ok) as fetch:
                self.assertTrue(etf_delta_tracker.run(day))
                self.assertEqual(fetch.call_count, len(universe))
            refreshed = json.loads(path.read_text(encoding="utf-8"))
            quarantined = list(root.glob(path.name + ".invalid-*"))
        self.assertEqual(refreshed["meta"]["expectedCodes"], sorted(universe))
        self.assertEqual(len(quarantined), 1)

    def test_incomplete_same_day_file_is_refetched_and_quarantined(self):
        day = dt.date(2026, 8, 28)
        universe = _universe()

        def fetch_ok(code: str, _target: dt.date):
            return _holding(code), day.isoformat(), "fixture"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / f"top10_active_etf_holdings_{day.isoformat()}.json"
            path.write_text(json.dumps({"date": day.isoformat()}), encoding="utf-8")
            with mock.patch.dict(os.environ, {etf_paths.ENV_HISTORY_DIR: str(root)}), mock.patch.object(
                etf_delta_tracker, "ETFS", universe
            ), mock.patch.object(etf_delta_tracker, "fetch_one", side_effect=fetch_ok):
                self.assertTrue(etf_delta_tracker.run(day))
            payload = json.loads(path.read_text(encoding="utf-8"))
            quarantined = list(root.glob(path.name + ".invalid-*"))
        self.assertEqual(payload["meta"]["succeededCount"], 10)
        self.assertEqual(len(quarantined), 1)


if __name__ == "__main__":
    unittest.main()
