# -*- coding: utf-8 -*-
"""限定離線回歸：行情可信度、未知值、紙上規則及來源時間。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.data_contract import assess_quote, finite_number, normalize_quote, parse_as_of
from server.decision import HeuristicProvider
from server.risk import daily_dd_ratio, evaluate_gate
from server.state import Runtime, VALID_STATES
from server import st_link

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)


def fresh_quote(**changes):
    result = {"symbol": "TXF", "price": 100.0, "as_of": NOW.isoformat(),
              "source": "fixture", "demo": False}
    result.update(changes)
    return result


class DataContractTests(unittest.TestCase):
    def test_finite_numbers_preserve_zero_and_reject_boolean(self):
        self.assertEqual(finite_number(0), 0.0)
        self.assertEqual(finite_number("1.25"), 1.25)
        for value in (None, True, False, "", "NaN", "Infinity", float("nan"), float("inf"), {}, []):
            with self.subTest(value=repr(value)):
                self.assertIsNone(finite_number(value))

    def test_fresh_quote_carries_source_time(self):
        q = normalize_quote(fresh_quote(as_of="2026-10-03T16:00:00+08:00"), "TXF", NOW)
        self.assertEqual(q["quality"], "fresh")
        self.assertEqual(q["as_of"], NOW.isoformat())
        self.assertEqual(q["age_sec"], 0)
        self.assertTrue(assess_quote(q, "TXF", NOW, mode="live")["entry_allowed"])

    def test_price_must_be_finite_positive(self):
        for value in (None, 0, -1, True, "NaN", float("inf")):
            with self.subTest(value=repr(value)):
                q = normalize_quote(fresh_quote(price=value), "TXF", NOW)
                self.assertIsNone(q["price"])
                self.assertFalse(assess_quote(q, "TXF", NOW)["entry_allowed"])

    def test_missing_or_incompatible_symbol_never_uses_foreign_price(self):
        for value in (None, "MTX", {}, ["TXF"], 123):
            with self.subTest(symbol=value):
                q = normalize_quote(fresh_quote(symbol=value), "TXF", NOW)
                self.assertIsNone(q["price"])
                self.assertFalse(assess_quote(q, "TXF", NOW)["entry_allowed"])

    def test_missing_naive_or_date_only_timestamp_is_unknown(self):
        for value in (None, "2026-10-03", "2026-10-03T08:00:00", "bad", 123):
            with self.subTest(as_of=value):
                self.assertIsNone(parse_as_of(value))
                q = normalize_quote(fresh_quote(as_of=value), "TXF", NOW)
                self.assertIsNone(q["as_of"])
                self.assertEqual(q["quality"], "unknown")
                self.assertFalse(assess_quote(q, "TXF", NOW)["entry_allowed"])

    def test_future_and_stale_quotes_are_blocked(self):
        for seconds, quality in ((1, "future"), (-91, "stale")):
            with self.subTest(quality=quality):
                q = normalize_quote(fresh_quote(as_of=(NOW + timedelta(seconds=seconds)).isoformat()), "TXF", NOW)
                self.assertEqual(q["quality"], quality)
                self.assertFalse(assess_quote(q, "TXF", NOW)["entry_allowed"])

    def test_assess_rechecks_freshness_instead_of_trusting_cached_quality(self):
        q = normalize_quote(fresh_quote(), "TXF", NOW)
        q["entry_allowed"] = True
        result = assess_quote(q, "TXF", NOW + timedelta(seconds=91))
        self.assertEqual(result["quality"], "stale")
        self.assertFalse(result["entry_allowed"])

    def test_demo_is_allowed_only_for_paper(self):
        for quote in (fresh_quote(demo=True), fresh_quote(source="wave_ai_ref")):
            self.assertTrue(assess_quote(quote, "TXF", NOW, mode="paper")["entry_allowed"])
            self.assertFalse(assess_quote(quote, "TXF", NOW, mode="live")["entry_allowed"])

    def test_invalid_metadata_cannot_revive_after_normalization(self):
        for changes in ({"demo": "yes"}, {"demo": 0}, {"source": {}}, {"source": ["fixture"]}):
            with self.subTest(changes=changes):
                q = normalize_quote(fresh_quote(**changes), "TXF", NOW)
                self.assertEqual(q["quality"], "invalid")
                self.assertIsNone(q["price"])
                self.assertFalse(assess_quote(q, "TXF", NOW)["entry_allowed"])

    def test_unknown_source_or_mode_is_not_tradeable(self):
        for source in (None, "", "unknown"):
            q = normalize_quote(fresh_quote(source=source), "TXF", NOW)
            self.assertFalse(assess_quote(q, "TXF", NOW)["entry_allowed"])
        self.assertFalse(assess_quote(fresh_quote(), "TXF", NOW, mode="other")["entry_allowed"])


class RuntimeAndRiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime" / "state.json"
        self.runtime = Runtime(self.path)
        self.addCleanup(mock.patch.stopall)
        mock.patch("urllib.request.urlopen", side_effect=AssertionError("禁止網路呼叫")).start()
        mock.patch("server.audit.write").start()

    def gate(self, state, decision):
        def assessment(quote, symbol=None, **kwargs):
            return assess_quote(quote, symbol, NOW, **kwargs)
        with mock.patch("server.risk.assess_quote", side_effect=assessment):
            return evaluate_gate(state, decision)

    def test_default_is_known_flat_with_unknown_financial_data(self):
        s = self.runtime.snapshot()
        self.assertEqual(set(s["positions"].values()), {0})
        self.assertIsNone(s["exec"]["price"])
        self.assertIsNone(s["quote"]["price"])
        self.assertIsNone(s["account"]["equity"])
        self.assertIsNone(s["account"]["yesterday_balance"])
        self.assertIsNone(s["ai"]["confidence"])
        self.assertFalse(self.path.parent.exists())
        self.assertIn("AwaitingFill", VALID_STATES)
        self.assertIn("PartialFilled", VALID_STATES)

    def test_runtime_writes_only_injected_location(self):
        self.runtime.patch(style=65)
        self.assertTrue(self.path.is_file())
        self.assertEqual(Runtime(self.path).snapshot()["style"], 65)

    def test_legacy_reference_snapshot_is_not_real_equity_or_position(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            "mode": "paper", "account": {"source": "wave_ai_ref", "reference": True,
            "yesterday_balance": 72312, "equity": 59888}, "positions": {"account": 1},
            "exec": {"price": 45020}, "ai": {"confidence": 0.62}}), encoding="utf-8")
        s = Runtime(self.path).snapshot()
        self.assertIsNone(daily_dd_ratio(s))
        self.assertIsNone(s["exec"]["price"])
        self.assertEqual(set(s["positions"].values()), {0})
        self.assertIsNone(s["ai"]["confidence"])
        self.assertTrue(s["account"]["migrated_reference"])

    def test_legacy_overlay_receive_epoch_is_not_source_time(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"st_link": {"overlay_epoch": NOW.timestamp()}}), encoding="utf-8")
        self.assertIsNone(Runtime(self.path).snapshot()["st_link"]["overlay_epoch"])

    def test_unknown_drawdown_is_distinct_from_zero_equity(self):
        for account in ({}, {"yesterday_balance": 100}, {"yesterday_balance": 100, "equity": None},
                        {"yesterday_balance": 100, "equity": float("nan")},
                        {"yesterday_balance": True, "equity": 0},
                        {"yesterday_balance": 100, "equity": 0, "demo": True},
                        {"yesterday_balance": 100, "equity": 0, "reference": True}):
            with self.subTest(account=account):
                self.assertIsNone(daily_dd_ratio({"account": account}))
        self.assertEqual(daily_dd_ratio({"account": {"yesterday_balance": 100, "equity": 0}}), 1)
        self.assertEqual(daily_dd_ratio({"account": {"yesterday_balance": 100, "equity": 100}}), 0)

    def test_unknown_quote_blocks_new_risk_but_not_exits(self):
        state = self.runtime.snapshot()
        state["kill_switch"] = True
        state["fsm"] = "Halted"
        decision = {"action": "ENTER_LONG", "process": {"chase_risk": "high"}}
        self.assertFalse(self.gate(state, decision)["allow"])
        for action in ("REDUCE", "EXIT"):
            decision["action"] = action
            self.assertTrue(self.gate(state, decision)["allow"])

    def test_paper_rules_can_use_fresh_demo_without_fake_equity(self):
        state = self.runtime.snapshot()
        state.update(quote=fresh_quote(demo=True), no_overnight={"enabled": False})
        decision = HeuristicProvider().infer({"style": 65, "positions": {"account": 0}})
        gate = self.gate(state, decision)
        self.assertTrue(gate["allow"])
        self.assertIsNone(gate["daily_dd"])
        self.assertTrue(any("回撤未知" in reason for reason in gate["reasons"]))

    def test_live_rejects_demo_or_unknown_confidence(self):
        state = self.runtime.snapshot()
        state.update(mode="live", quote=fresh_quote(), no_overnight={"enabled": False},
                     account={"yesterday_balance": 100, "equity": 100})
        for decision in ({"action": "ENTER_LONG", "demo": True, "confidence": 0.9},
                         {"action": "ENTER_LONG", "provider": "heuristic", "confidence": 0.9},
                         {"action": "ENTER_LONG", "confidence": None},
                         {"action": "ENTER_LONG", "confidence": float("nan")}):
            with self.subTest(decision=decision):
                self.assertFalse(self.gate(state, decision)["allow"])
        decision = {"action": "ENTER_LONG", "confidence": 0.9}
        self.assertTrue(self.gate(state, decision)["allow"])
        state["account"]["equity"] = None
        self.assertFalse(self.gate(state, decision)["allow"])

    def test_heuristic_is_explicit_and_deterministic_without_invented_price(self):
        ctx = {"style": 65, "positions": {"account": 0}, "price": 45020}
        with mock.patch("server.decision.now_iso", return_value="fixed"):
            first = HeuristicProvider().infer(ctx)
            self.assertEqual(first, HeuristicProvider().infer(ctx))
        self.assertTrue(first["demo"])
        self.assertIsNone(first["confidence"])
        self.assertIsNone(first["bias_long"])
        self.assertIsNone(first["invalidation"]["price"])
        self.assertIn("紙上規則演練", first["summary"])
        self.assertIn("非勝率", first["summary"])
        supplied = HeuristicProvider().infer({**ctx, "decision_invalidation": {"price": 90, "side": "below"}})
        self.assertEqual(supplied["invalidation"], {"price": 90, "side": "below"})


class OverlayTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Runtime(Path(self.temp.name) / "state.json")
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(st_link, "RUNTIME", self.runtime).start()
        mock.patch.object(st_link, "_dd_locked", False).start()
        mock.patch.object(st_link, "_fail_count", 0).start()
        mock.patch.object(st_link, "push_async").start()
        mock.patch.object(st_link, "_write_inv_txt", side_effect=AssertionError("紙上模式不得寫實帳失效價")).start()
        mock.patch("server.audit.write").start()
        mock.patch("urllib.request.urlopen", side_effect=AssertionError("禁止網路呼叫")).start()
        mock.patch("server.st_link.time.time", return_value=NOW.timestamp()).start()

    def test_source_time_is_not_replaced_by_receive_time(self):
        stamp = NOW - timedelta(seconds=20)
        st_link.touch_overlay(stamp.isoformat())
        first = self.runtime.snapshot()["st_link"]
        with mock.patch("server.st_link.time.time", return_value=NOW.timestamp() + 10):
            st_link.touch_overlay(stamp.isoformat())
        link = self.runtime.snapshot()["st_link"]
        self.assertIsNotNone(link["overlay_at"])
        self.assertEqual(first["overlay_epoch"], stamp.timestamp())
        self.assertEqual(link["overlay_epoch"], first["overlay_epoch"])

    def test_missing_source_time_does_not_clear_fail_safe(self):
        self.runtime.patch(st_link={"fail_safe": True}, st_overlay={"fail_safe": True})
        for stamp in (None, "2026-10-03", "2026-10-03T08:00:00"):
            st_link.touch_overlay(stamp)
            link = self.runtime.snapshot()["st_link"]
            self.assertIsNone(link["overlay_epoch"])
            self.assertTrue(link["fail_safe"])
            self.assertLessEqual(self.runtime.snapshot()["style"], st_link.FAIL_SAFE_STYLE)

    def test_stale_future_and_nonfinite_source_epoch_fail_closed(self):
        for stamp in ((NOW - timedelta(seconds=100)).isoformat(), (NOW + timedelta(seconds=5)).isoformat()):
            st_link.touch_overlay(stamp)
            self.assertTrue(self.runtime.snapshot()["st_link"]["fail_safe"])
        for epoch in (float("nan"), float("inf"), True, None):
            self.assertIsNone(st_link._overlay_age_sec({"overlay_epoch": epoch}))

    def test_fresh_source_clears_fail_safe_but_does_not_fake_healthy_equity(self):
        self.runtime.patch(st_link={"fail_safe": True}, st_overlay={"fail_safe": True})
        st_link.touch_overlay(NOW.isoformat())
        snap = self.runtime.snapshot()
        self.assertFalse(snap["st_link"]["fail_safe"])
        self.assertFalse(snap["st_overlay"]["fail_safe"])
        self.assertEqual(snap["lights"]["risk_watchdog"], "warn")

    def test_tick_does_not_bypass_unknown_age_after_successful_pull(self):
        with mock.patch.object(st_link, "_ping_st", return_value=True), \
             mock.patch.object(st_link, "pull_st_macro", return_value=True), \
             mock.patch.object(st_link, "apply_fail_safe", side_effect=st_link.enforce_fail_safe) as apply:
            st_link._tick()
        apply.assert_called_once()
        self.assertTrue(self.runtime.snapshot()["st_link"]["fail_safe"])
        self.assertIsNone(self.runtime.snapshot()["account"]["daily_dd_pct"])

    def test_unknown_or_stale_quote_cannot_tighten_invalidation(self):
        self.runtime.patch(exec={"price": 100}, ai={"invalidation": {"price": 80, "side": "below"}})
        snap = st_link.enforce_fail_safe("宏觀覆寫來源時間未知", tighten=True)
        self.assertEqual(snap["ai"]["invalidation"]["price"], 80)
        self.runtime.patch(quote=fresh_quote(as_of=(NOW - timedelta(seconds=100)).isoformat()))
        snap = st_link.enforce_fail_safe("宏觀覆寫過期", tighten=True)
        self.assertEqual(snap["ai"]["invalidation"]["price"], 80)
        self.runtime.patch(quote=fresh_quote())
        snap = st_link.enforce_fail_safe("宏觀覆寫過期", tighten=True)
        self.assertGreater(snap["ai"]["invalidation"]["price"], 80)

    def test_unknown_equity_does_not_trigger_drawdown_lock(self):
        st_link._enforce_daily_dd()
        snap = self.runtime.snapshot()
        self.assertFalse(snap["kill_switch"])
        self.assertIsNone(snap["account"]["daily_dd_pct"])
        self.assertEqual(snap["lights"]["risk_watchdog"], "warn")


if __name__ == "__main__":
    unittest.main()
