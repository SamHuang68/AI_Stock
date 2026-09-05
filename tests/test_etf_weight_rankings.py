#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from etf_weight_rankings import (  # noqa: E402
    build_weight_rankings,
    build_weight_rankings_from_history,
)


def _etf(
    source_date: str,
    holdings: list[dict],
    *,
    name: str = "測試 ETF",
    source: str = "moneydj-full",
    coverage: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "date": source_date,
        "source": source,
        "total": len(holdings),
        "holdings": holdings,
    }
    if coverage is not None:
        payload["coverage"] = coverage
    return payload


def _holding(
    code: str,
    weight: float,
    *,
    market: str = "TW",
    name: str = "標的",
    shares: int = 100,
    rank: int = 1,
) -> dict:
    return {
        "code": code,
        "market": market,
        "name": name,
        "weight": weight,
        "shares": shares,
        "rank": rank,
    }


class EtfWeightRankingsTests(unittest.TestCase):
    def test_precise_small_weight_changes_are_ranked_by_delta_pp_not_shares(self):
        previous = {
            "date": "2026-08-27",
            "0050": _etf("2026-08-26", [
                _holding("2330", 10.0000, shares=1000),
                _holding("2454", 5.0000, shares=500),
                _holding("2317", 4.0000, shares=400),
            ]),
        }
        current = {
            "date": "2026-08-28",
            "0050": _etf("2026-08-27", [
                _holding("2330", 10.0001, shares=900),  # 權重增、股數減
                _holding("2454", 4.9998, shares=900),  # 權重減、股數增
                _holding("2317", 4.0000, shares=800),  # 僅股數變化，不列排名
            ]),
        }

        result = build_weight_rankings(current, previous)

        self.assertEqual(result["status"], "ok")
        self.assertEqual([row["code"] for row in result["rows"]], ["2330", "2454"])
        self.assertAlmostEqual(result["rows"][0]["delta_pp"], 0.0001)
        self.assertEqual(result["rows"][0]["status"], "increased")
        self.assertEqual(result["rows"][0]["shares_delta"], -100)
        self.assertAlmostEqual(result["rows"][1]["delta_pp"], -0.0002)
        self.assertEqual(result["rows"][1]["status"], "decreased")

    def test_comparable_etf_distinguishes_stock_add_remove_from_etf_missing(self):
        previous = {
            "date": "2026-08-27",
            "meta": {"expectedCodes": ["0050", "00999A"]},
            "0050": _etf("2026-08-26", [
                _holding("2330", 20, name="台積電"),
                _holding("2317", 8, name="鴻海", rank=2),
            ], name="元大台灣50"),
            "00999A": _etf("2026-08-26", [_holding("1101", 3)]),
        }
        current = {
            "date": "2026-08-28",
            "meta": {
                "expectedCodes": ["0050", "00981A", "00999A"],
                "failedCodes": ["00999A"],
            },
            "0050": _etf("2026-08-27", [
                _holding("2330", 20, name="台積電"),
                _holding("2454", 6, name="聯發科", rank=2),
            ], name="元大台灣50"),
            # 新 ETF 首日沒有前期基準，不得把整籃持股標為 added。
            "00981A": _etf("2026-08-27", [_holding("2303", 7)]),
        }

        result = build_weight_rankings(current, previous)

        rows = {(row["code"], row["status"]): row for row in result["rows"]}
        self.assertEqual(set(rows), {("2454", "added"), ("2317", "removed")})
        self.assertEqual(rows[("2454", "added")]["prev_weight"], 0.0)
        self.assertEqual(rows[("2317", "removed")]["weight"], 0.0)
        self.assertEqual(
            result["excluded_reasons"],
            {"current_etf_collection_failed": 1, "no_baseline": 1},
        )
        self.assertFalse(any(row["etf_code"] in {"00981A", "00999A"} for row in result["rows"]))

    def test_source_date_and_coverage_guards_exclude_unreliable_pairs(self):
        previous = {
            "date": "2026-08-27",
            "0050": _etf("2026-08-26", [_holding("2330", 10)]),
            "0056": _etf("2026-08-26", [_holding("2330", 10)]),
            "00878": _etf("2026-08-26", [_holding("2330", 10)], source="moneydj-top10"),
            "00919": _etf("2026-08-26", [_holding("2330", 10)]),
        }
        current = {
            "date": "2026-08-28",
            "0050": _etf("2026-08-27", [_holding("2330", 11)], source="twse"),
            "0056": _etf("2026-08-26", [_holding("2330", 11)]),
            "00878": _etf("2026-08-27", [_holding("2330", 11)], source="moneydj-top10"),
            "00919": _etf("2026-08-27", [_holding("2330", 11)], coverage="partial"),
        }

        result = build_weight_rankings(current, previous)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["status"], "no_comparable_etfs")
        self.assertEqual(result["excluded_reasons"], {
            "coverage_mismatch": 1,
            "partial_coverage": 1,
            "source_date_not_advanced": 1,
            "source_mismatch": 1,
        })

    def test_same_code_in_different_markets_is_never_merged(self):
        previous = {
            "date": "2026-08-27",
            "00988A": _etf("2026-08-26", [
                _holding("2330", 3.0, market="TW", name="台灣標的", rank=1),
                _holding("2330", 2.0, market="US", name="美國標的", rank=2),
            ]),
        }
        current = {
            "date": "2026-08-28",
            "00988A": _etf("2026-08-27", [
                _holding("2330", 3.2, market="TW", name="台灣標的", rank=1),
                _holding("2330", 1.9, market="US", name="美國標的", rank=2),
            ]),
        }

        result = build_weight_rankings(current, previous)

        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual({row["symbol_key"] for row in result["rows"]}, {"2330.TW", "2330.US"})
        self.assertEqual({row["market"] for row in result["rows"]}, {"TW", "US"})

    def test_missing_previous_snapshot_never_projects_current_holdings_from_zero(self):
        current = {
            "date": "2026-08-28",
            "0050": _etf("2026-08-27", [_holding("2330", 20)]),
        }

        result = build_weight_rankings(current, None)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded"][0]["etf_code"], "*")
        self.assertEqual(result["excluded"][0]["reason"], "previous_snapshot_missing")
        self.assertEqual(result["excluded"][0]["reason_label"], "前期快照缺漏，無法建立比較基準")
        self.assertEqual(result["excluded_reasons"], {"previous_snapshot_missing": 1})

    def test_result_exposes_required_ui_fields_and_comparable_source_dates(self):
        previous = {
            "date": "2026-08-27",
            "0050": _etf("2026-08-25", [_holding("2330", 10, name="台積電")], name="元大台灣50"),
        }
        current = {
            "date": "2026-08-28",
            "0050": _etf("2026-08-27", [_holding("2330", 10.1, name="台積電")], name="元大台灣50"),
        }

        result = build_weight_rankings(current, previous)
        row = result["rows"][0]

        required = {
            "etf_code", "etf_name", "code", "name", "market",
            "prev_weight", "weight", "delta_pp", "prev_date", "date",
            "source", "status",
        }
        self.assertTrue(required.issubset(row))
        self.assertEqual(result["source_dates"], {
            "current": ["2026-08-27"],
            "previous": ["2026-08-25"],
        })
        self.assertEqual(result["aggregation"], "none_per_etf_stock_row")

    def test_etf_scope_is_applied_before_rows_exclusions_and_counters(self):
        previous = {
            "date": "2026-08-27",
            "0050": _etf("2026-08-26", [_holding("2330", 10)]),
            "00999A": _etf("2026-08-26", [_holding("2454", 5)]),
        }
        current = {
            "date": "2026-08-28",
            "0050": _etf("2026-08-27", [_holding("2330", 10.2)]),
            # 未啟用 ETF 即使來源切換，也不應洩漏在 excluded 統計。
            "00999A": _etf("2026-08-27", [_holding("2454", 5.2)], source="twse"),
        }

        result = build_weight_rankings(current, previous, allowed_codes={"0050"})

        self.assertEqual([row["etf_code"] for row in result["rows"]], ["0050"])
        self.assertEqual(result["comparable_etf_count"], 1)
        self.assertEqual(result["excluded_etf_count"], 0)
        self.assertEqual(result["excluded_reasons"], {})

    def test_invalid_weight_and_misleading_source_names_never_enter_ranking(self):
        previous = {
            "date": "2026-08-27",
            "0050": _etf("2026-08-26", [_holding("2330", 10)]),
            "0056": _etf("2026-08-26", [_holding("2330", 10)], source="not-full"),
            "00878": _etf("2026-08-26", [_holding("2330", 10)], source="twse-preview"),
        }
        current = {
            "date": "2026-08-28",
            "0050": _etf("2026-08-27", [_holding("2330", 101)]),
            "0056": _etf("2026-08-27", [_holding("2330", 11)], source="not-full"),
            "00878": _etf("2026-08-27", [_holding("2330", 11)], source="twse-preview"),
        }

        result = build_weight_rankings(current, previous)

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded_reasons"], {
            "coverage_unknown": 2,
            "weight_invalid": 1,
        })

    def test_history_skips_weekend_duplicate_provider_date_only(self):
        current = {
            "date": "2026-09-05",
            "0050": _etf("2026-09-04", [_holding("2330", 10.2)]),
        }
        repeated = {
            "date": "2026-09-04",
            "0050": _etf("2026-09-04", [_holding("2330", 10.2)]),
        }
        baseline = {
            "date": "2026-09-03",
            "0050": _etf("2026-09-03", [_holding("2330", 10.0)]),
        }

        result = build_weight_rankings_from_history(
            current, [repeated, baseline], allowed_codes={"0050"}
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["rows"]), 1)
        self.assertAlmostEqual(result["rows"][0]["delta_pp"], 0.2)
        self.assertEqual(result["rows"][0]["prev_date"], "2026-09-03")
        self.assertEqual(result["rows"][0]["prev_snapshot_date"], "2026-09-03")
        self.assertEqual(result["baseline_snapshot_dates"], ["2026-09-03"])

    def test_history_preserves_a_different_nearest_baseline_for_each_etf(self):
        current = {
            "date": "2026-09-05",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
            "0056": _etf("2026-09-03", [_holding("2454", 5.2)]),
        }
        newest = {
            "date": "2026-09-04",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
            "0056": _etf("2026-09-02", [_holding("2454", 5.0)]),
        }
        older = {
            "date": "2026-09-03",
            "0050": _etf("2026-09-03", [_holding("2330", 10.0)]),
            "0056": _etf("2026-09-01", [_holding("2454", 4.9)]),
        }

        result = build_weight_rankings_from_history(
            current, [newest, older], allowed_codes={"0050", "0056"}
        )

        by_etf = {row["etf_code"]: row for row in result["rows"]}
        self.assertEqual(by_etf["0050"]["prev_snapshot_date"], "2026-09-03")
        self.assertEqual(by_etf["0050"]["prev_date"], "2026-09-03")
        self.assertEqual(by_etf["0056"]["prev_snapshot_date"], "2026-09-04")
        self.assertEqual(by_etf["0056"]["prev_date"], "2026-09-02")
        self.assertEqual(result["baseline_snapshot_dates"], ["2026-09-03", "2026-09-04"])

    def test_history_never_skips_source_mismatch_to_cherry_pick_older_baseline(self):
        current = {
            "date": "2026-09-05",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
        }
        mismatched = {
            "date": "2026-09-04",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)], source="twse"),
        }
        otherwise_usable = {
            "date": "2026-09-03",
            "0050": _etf("2026-09-03", [_holding("2330", 10.0)]),
        }

        result = build_weight_rankings_from_history(
            current, [mismatched, otherwise_usable], allowed_codes={"0050"}
        )

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded_reasons"], {"source_mismatch": 1})

    def test_history_never_skips_invalid_snapshot_to_cherry_pick_older_baseline(self):
        current = {
            "date": "2026-09-05",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
        }
        otherwise_usable = {
            "date": "2026-09-03",
            "0050": _etf("2026-09-03", [_holding("2330", 10.0)]),
        }

        result = build_weight_rankings_from_history(
            current, [None, otherwise_usable], allowed_codes={"0050"}
        )

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded_reasons"], {"previous_snapshot_invalid": 1})

    def test_history_first_etf_observation_has_no_ranked_rows(self):
        current = {
            "date": "2026-09-05",
            "00981A": _etf("2026-09-04", [_holding("2330", 10.3)]),
        }
        previous = {
            "date": "2026-09-04",
            "meta": {"expectedCodes": ["0050"]},
            "0050": _etf("2026-09-03", [_holding("2330", 10.0)]),
        }

        result = build_weight_rankings_from_history(
            current, [previous], allowed_codes={"00981A"}
        )

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded_reasons"], {"no_baseline": 1})

    def test_expected_but_absent_previous_etf_is_missing_not_first_observation(self):
        current = {
            "date": "2026-09-05",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
        }
        previous = {
            "date": "2026-09-04",
            "meta": {"expectedCodes": ["0050"]},
            "0056": _etf("2026-09-03", [_holding("2454", 5.0)]),
        }

        result = build_weight_rankings_from_history(
            current, [previous], allowed_codes={"0050"}
        )

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded_reasons"], {"previous_etf_missing": 1})

    def test_history_search_is_bounded_to_twenty_snapshots(self):
        current = {
            "date": "2026-09-05",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
        }
        repeated = {
            "date": "2026-09-04",
            "0050": _etf("2026-09-04", [_holding("2330", 10.3)]),
        }
        twenty_first = {
            "date": "2026-08-01",
            "0050": _etf("2026-08-01", [_holding("2330", 9.0)]),
        }

        result = build_weight_rankings_from_history(
            current, [repeated] * 20 + [twenty_first], allowed_codes={"0050"}
        )

        self.assertEqual(result["rows"], [])
        self.assertEqual(result["excluded_reasons"], {"no_distinct_source_date_baseline": 1})


if __name__ == "__main__":
    unittest.main()
