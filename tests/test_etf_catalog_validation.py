#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ETF 目錄載入：結構或型別不符的項目不得讓模組匯入失敗，也不得拖累其餘有效項目。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import etf_delta_tracker  # noqa: E402


def _etf(code, name="ETF", market="TW", enabled=True):
    return {"code": code, "name": name, "market": market, "enabled": enabled}


class EtfCatalogValidationTests(unittest.TestCase):
    def load(self, payload, *, raw: str | None = None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
            out = StringIO()
            with mock.patch.object(etf_delta_tracker, "CATALOG_FILE", str(path)), redirect_stdout(out):
                loaded = etf_delta_tracker.load_catalog()
        return loaded, out.getvalue()

    def assertFallback(self, loaded):
        self.assertIs(loaded, etf_delta_tracker._FALLBACK_ETFS)

    def test_non_string_code_is_skipped_and_valid_entries_are_kept(self):
        loaded, log = self.load({"categories": [{"etfs": [_etf(123), _etf("0050", "元大台灣50")]}]})
        self.assertEqual(set(loaded), {"0050"})
        self.assertIn("略過", log)

    def test_blank_or_missing_code_is_skipped(self):
        loaded, _ = self.load({"categories": [{"etfs": [_etf("  "), {"enabled": True}, _etf("0056")]}]})
        self.assertEqual(set(loaded), {"0056"})

    def test_non_string_name_falls_back_to_code(self):
        loaded, _ = self.load({"categories": [{"etfs": [_etf("0050", name=7)]}]})
        self.assertEqual(loaded["0050"], ("0050", "0050"))

    def test_malformed_containers_are_skipped_without_losing_other_categories(self):
        loaded, log = self.load({"categories": [
            "不是物件", {"etfs": "不是清單"}, {"etfs": ["不是物件", None, _etf("0050")]}, {"etfs": [_etf("0056")]},
        ]})
        self.assertEqual(set(loaded), {"0050", "0056"})
        self.assertIn("略過", log)

    def test_unusable_root_or_categories_fall_back_with_a_log_line(self):
        for payload in ([], "text", {"categories": "x"}, {"categories": None}, {}):
            with self.subTest(payload=payload):
                loaded, log = self.load(payload)
                self.assertFallback(loaded)
                self.assertTrue(log.strip(), "結構不符時必須留下記錄")

    def test_unreadable_json_still_falls_back(self):
        loaded, log = self.load(None, raw="{壞掉")
        self.assertFallback(loaded)
        self.assertIn("fallback", log)

    def test_only_invalid_entries_fall_back_rather_than_returning_empty(self):
        loaded, _ = self.load({"categories": [{"etfs": [_etf(123), _etf(None)]}]})
        self.assertFallback(loaded)

    def test_valid_catalog_behaviour_is_unchanged(self):
        loaded, log = self.load({"categories": [{"etfs": [
            _etf("00981a", "主動統一台股增長"), _etf("SPY", market="US"), _etf("0056", enabled=False),
        ]}]})
        self.assertEqual(loaded, {"00981A": ("00981A", "主動統一台股增長")})
        self.assertEqual(log, "")

    def test_shipped_catalog_loads_every_enabled_tw_entry(self):
        data = json.loads((ROOT / "data" / "etf_catalog.json").read_text(encoding="utf-8"))
        expected = {
            e["code"].strip().upper()
            for c in data["categories"] for e in c["etfs"]
            if e.get("enabled") and str(e.get("market") or "TW").upper() == "TW"
        }
        with redirect_stdout(StringIO()) as out:
            loaded = etf_delta_tracker.load_catalog()
        self.assertEqual(set(loaded), expected)
        self.assertGreater(len(expected), 10)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
