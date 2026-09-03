#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import international_fundamental as intl  # noqa: E402


def stats(revenue, earnings, op_margin, net_margin, roe, forward_pe):
    return {
        "revenueGrowth": revenue,
        "earningsGrowth": earnings,
        "opMargin": op_margin,
        "netMargin": net_margin,
        "roe": roe,
        "forwardPE": forward_pe,
        "_source": "fixture",
    }


class InternationalFundamentalTest(unittest.TestCase):
    def test_market_contract_does_not_confuse_tokyo_with_twse(self):
        self.assertEqual(intl.market_of_symbol("2330"), "TW")
        self.assertEqual(intl.market_of_symbol("5347.TWO"), "TW")
        self.assertEqual(intl.market_of_symbol("7203.T"), "JP")
        self.assertEqual(intl.market_of_symbol("^N225"), "JP")
        self.assertEqual(intl.market_of_symbol("AAPL"), "US")
        self.assertEqual(intl.market_of_symbol("^GSPC"), "US")

    def test_us_index_proxy_is_renderable_and_discloses_scope(self):
        members = {
            "MSFT": stats(15, 18, 44, 36, 32, 30),
            "AAPL": stats(8, 12, 31, 25, 75, 27),
            "NVDA": stats(55, 60, 62, 55, 80, 35),
            "AMZN": stats(12, 22, 11, 10, 21, 32),
            "META": stats(20, 25, 42, 35, 34, 26),
        }
        out = intl.build_index_fundamental("^GSPC", members, as_of="2026-08-13")
        self.assertEqual(out["market"], "US")
        self.assertEqual(out["kind"], "market")
        self.assertEqual(out["model"], "LARGE_CAP_PROXY_V1")
        self.assertIsInstance(out["score"], int)
        self.assertEqual(len(out["sampleMembers"]), 5)
        self.assertIn("不是完整成分股加權財報", out["plainSummary"])
        self.assertIn("代理樣本", out["_source"])

    def test_japan_index_uses_jp_contract(self):
        members = {
            "7203.T": stats(6, 8, 12, 9, 14, 12),
            "6758.T": stats(9, 11, 18, 12, 16, 17),
        }
        out = intl.build_index_fundamental("^N225", members, as_of="2026-08-13")
        self.assertEqual(out["market"], "JP")
        self.assertIsNotNone(out["score"])
        self.assertEqual(out["confidence"], 55)

    def test_one_member_is_not_enough_to_publish_score(self):
        out = intl.build_index_fundamental(
            "^SOX", {"NVDA": stats(55, 60, 62, 55, 80, 35)}, as_of="2026-08-13"
        )
        self.assertIsNone(out["score"])
        self.assertEqual(out["label"], "代理樣本不足")


if __name__ == "__main__":
    unittest.main()
