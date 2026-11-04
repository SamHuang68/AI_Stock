#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情契約與新單行情政策（WD P0 第 2b 片）；完全離線。

裁量模式（TradingView／手動／AI 決策）原本只帶 price、沒有來源時間，exec.price 預設還是示範數字 45020。
規則模式的訊號由 策略契約 強制時間戳與新鮮度，不經過這道閘門。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import risk  # noqa: E402
from server.data_contract import (  # noqa: E402
    DEFAULT_QUOTE_MAX_AGE_SEC, FUTURE_TOLERANCE_SEC, assess_quote, normalize_quote, parse_as_of)

NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
NAN, INF = float("nan"), float("inf")


def at(seconds_ago, base=NOW):
    return (base - timedelta(seconds=seconds_ago)).isoformat()


def quote(seconds_ago=10, **fields):
    return {"symbol": "TXF", "price": 45010.0, "as_of": at(seconds_ago), "source": "tradingview", **fields}


class ParseAsOfTests(unittest.TestCase):
    def test_accepts_only_timezone_aware_iso_times(self):
        for good in ("2026-11-04T12:00:00Z", "2026-11-04T12:00:00+00:00", "2026-11-04T20:00:00+08:00",
                     "2026-11-04 12:00:00+00:00", "2026-11-04T12:00z"):
            with self.subTest(good=good):
                self.assertEqual(parse_as_of(good), NOW)
        for bad in ("2026-11-04T12:00:00", "2026-11-04", "12:00", "not a time", "", None, 1730721600, [], {}):
            with self.subTest(bad=repr(bad)):
                self.assertIsNone(parse_as_of(bad))


class NormalizeQuoteTests(unittest.TestCase):
    def test_fresh_quote(self):
        result = normalize_quote(quote(10), "TXF", NOW)
        self.assertEqual((result["quality"], result["price"], result["age_sec"], result["reasons"]), ("fresh", 45010.0, 10.0, []))

    def test_age_boundaries_are_inclusive(self):
        self.assertEqual(normalize_quote(quote(DEFAULT_QUOTE_MAX_AGE_SEC), "TXF", NOW)["quality"], "fresh")
        stale = normalize_quote(quote(DEFAULT_QUOTE_MAX_AGE_SEC + 1), "TXF", NOW)
        self.assertEqual(stale["quality"], "stale")
        self.assertIn("行情已過期", stale["reasons"])
        # 未來容忍 5 秒（與 策略契約 的 age < -5 一致）：送件端與本機時鐘有小誤差是常態。
        # 這裡刻意寫死 5 與 6，不用常數：常數若被改掉，測試要跟著變紅，而不是一起變。
        self.assertEqual(FUTURE_TOLERANCE_SEC, 5.0)
        self.assertEqual(normalize_quote(quote(-5), "TXF", NOW)["quality"], "fresh")
        future = normalize_quote(quote(-6), "TXF", NOW)
        self.assertEqual(future["quality"], "future")
        self.assertIn("行情來源時間在未來", future["reasons"])

    def test_max_age_is_configurable_and_a_bad_limit_falls_back(self):
        self.assertEqual(normalize_quote(quote(200), "TXF", NOW, max_age_sec=300)["quality"], "fresh")
        for bad in (0, -5, NAN, "abc", None):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(normalize_quote(quote(200), "TXF", NOW, max_age_sec=bad)["quality"], "stale")

    def test_missing_or_naive_time_is_unknown_not_fresh(self):
        for fields in ({"as_of": None}, {"as_of": "2026-11-04T12:00:00"}, {"as_of": "garbage"}):
            with self.subTest(fields=fields):
                result = normalize_quote(quote(**fields), "TXF", NOW)
                self.assertEqual((result["quality"], result["price"], result["as_of"]), ("unknown", 45010.0, None))
                self.assertIn("行情來源時間未知或缺少時區", result["reasons"])

    def test_unknown_source_is_not_fresh(self):
        for source in (None, "", "unknown", "—"):
            with self.subTest(source=source):
                result = normalize_quote(quote(source=source), "TXF", NOW)
                self.assertEqual(result["quality"], "unknown")
                self.assertIn("行情來源未知", result["reasons"])
        self.assertEqual(normalize_quote(quote(source=None), "TXF", NOW)["source"], "unknown")      # 沒給來源才顯示 unknown

    def test_symbol_is_inherited_when_omitted_and_must_match_when_given(self):
        omitted = quote()
        del omitted["symbol"]
        self.assertEqual(normalize_quote(omitted, "TXF", NOW)["quality"], "fresh")
        self.assertEqual(normalize_quote(quote(symbol="txf"), "TXF", NOW)["quality"], "fresh")        # 大小寫不拘
        for bad in ("MXF", "TXF1!", 123, ["TXF"]):
            with self.subTest(bad=bad):
                result = normalize_quote(quote(symbol=bad), "TXF", NOW)
                self.assertEqual((result["quality"], result["price"]), ("invalid", None))
        self.assertEqual(normalize_quote(quote(), "", NOW)["quality"], "invalid")                      # 連預期商品都沒有

    def test_price_must_be_a_finite_positive_number(self):
        for bad in (NAN, INF, -INF, 0, -1, True, "abc", None, [], {}):
            with self.subTest(bad=repr(bad)):
                result = normalize_quote(quote(price=bad), "TXF", NOW)
                self.assertEqual((result["quality"], result["price"]), ("invalid", None))
        self.assertEqual(normalize_quote(quote(price="45010.5"), "TXF", NOW)["price"], 45010.5)

    def test_demo_flag_and_demo_sources(self):
        self.assertEqual(normalize_quote(quote(demo=True), "TXF", NOW)["quality"], "demo")
        self.assertEqual(normalize_quote(quote(source="heuristic"), "TXF", NOW)["quality"], "demo")
        self.assertEqual(normalize_quote(quote(demo="yes"), "TXF", NOW)["quality"], "invalid")

    def test_input_cannot_vouch_for_itself(self):
        forged = quote(120, quality="fresh", age_sec=0, entry_allowed=True, received_at=at(0))
        result = normalize_quote(forged, "TXF", NOW)
        self.assertEqual(result["quality"], "stale")
        self.assertNotIn("entry_allowed", result)

    def test_normalizing_a_stored_quote_again_is_stable(self):
        once = normalize_quote(quote(10), "TXF", NOW)
        self.assertEqual(normalize_quote(once, "TXF", NOW)["quality"], "fresh")
        invalid = normalize_quote(quote(price=NAN), "TXF", NOW)
        self.assertEqual(normalize_quote(invalid, "TXF", NOW)["quality"], "invalid")

    def test_non_object_input_and_bad_clock_do_not_raise(self):
        for raw in (None, [], "x", 5):
            self.assertEqual(normalize_quote(raw, "TXF", NOW)["quality"], "invalid")
        naive_clock = normalize_quote(quote(), "TXF", datetime(2026, 11, 4, 12, 0, 0))
        self.assertEqual(naive_clock["quality"], "unknown")
        self.assertIn("行情驗證時間無效", naive_clock["reasons"])


class AssessQuoteTests(unittest.TestCase):
    def test_fresh_is_allowed_in_both_modes(self):
        for mode in ("paper", "live"):
            self.assertTrue(assess_quote(quote(), "TXF", NOW, mode=mode)["entry_allowed"], mode)

    def test_demo_quote_is_paper_only(self):
        self.assertTrue(assess_quote(quote(demo=True), "TXF", NOW, mode="paper")["entry_allowed"])
        live = assess_quote(quote(demo=True), "TXF", NOW, mode="live")
        self.assertFalse(live["entry_allowed"])
        self.assertIn("演練行情不得增加實帳風險", live["reasons"])

    def test_unknown_mode_never_allows_entry(self):
        for mode in ("", "unknown", "LIVE", None):
            with self.subTest(mode=mode):
                self.assertFalse(assess_quote(quote(), "TXF", NOW, mode=mode)["entry_allowed"])

    def test_stale_future_unknown_and_invalid_are_never_allowed(self):
        for q in (quote(500), quote(-60), quote(as_of=None), quote(price=NAN), quote(symbol="MXF")):
            with self.subTest(q=q):
                self.assertFalse(assess_quote(q, "TXF", NOW, mode="paper")["entry_allowed"])

    def test_freshness_is_recomputed_every_time(self):
        q = quote(10)
        self.assertTrue(assess_quote(q, "TXF", NOW)["entry_allowed"])
        later = NOW + timedelta(seconds=300)
        self.assertFalse(assess_quote(q, "TXF", later)["entry_allowed"])        # 同一份行情，過了五分鐘就不能再用


def live_now(seconds_ago=10, **fields):
    """閘門用真實時鐘重新計算新鮮度，所以測試的行情也相對於真實現在。"""
    q = quote(seconds_ago)
    q["as_of"] = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    q.update(fields)
    return q


def gate_state(mode="paper", raw_quote="default", strategy="discretionary", **extra):
    state = {"kill_switch": False, "fsm": "Idle", "mode": mode, "symbol": "TXF",
             "account": {"yesterday_balance": 100.0, "equity": 100.0}, "no_overnight": {"enabled": False},
             "st_overlay": {}, "style": 50, "exec": {"lots": 1, "price": 45000.0},
             "strategy_execution": {"mode": strategy}}
    if raw_quote != "default":
        state["quote"] = raw_quote
    state.update(extra)
    return state


def entry(state, action="ENTER_LONG"):
    return risk.evaluate_gate(state, {"action": action, "confidence": 0.9, "process": {}})


class GatePolicyTests(unittest.TestCase):
    def reasons(self, result):
        return " ".join(result["reasons"])

    def test_live_requires_a_fresh_timestamped_quote(self):
        self.assertTrue(entry(gate_state("live", live_now(10)))["allow"])
        for label, q in (("尚未記錄行情", None), ("過期", live_now(500)), ("未來", live_now(-60)),
                         ("無效", live_now(10, symbol="MXF")), ("演練", live_now(10, demo=True)),
                         ("沒有時間", live_now(10, as_of=None))):
            with self.subTest(label=label):
                result = entry(gate_state("live", q))
                self.assertFalse(result["allow"], result)

    def test_live_price_only_signal_is_blocked_with_a_clear_reason(self):
        result = entry(gate_state("live", None))
        self.assertFalse(result["allow"])
        self.assertIn("行情來源時間未知", self.reasons(result))

    def test_paper_tolerates_price_only_signals_with_a_warning(self):
        flagged = {"symbol": "TXF", "price": 45000.0, "source": "signal.price", "as_of": None, "legacy_price_only": True}
        for q in (None, flagged):
            with self.subTest(q=q):
                result = entry(gate_state("paper", q))
                self.assertTrue(result["allow"], result)
                self.assertIn("紙上模式僅警示", self.reasons(result))

    def test_an_explicit_quote_with_a_broken_time_is_not_a_legacy_price_only_signal(self):
        # 送件端明確帶了 quote，卻因時間戳壞掉／沒有時區／缺漏而品質未知：這是壞行情，紙上模式也要擋。
        for label, fields in (("壞字串", {"as_of": "bad timestamp"}), ("沒有時區", {"as_of": "2026-11-04T12:00:00"}),
                              ("缺漏", {"as_of": None}),
                              ("自稱 signal.price 但沒有引擎旗標", {"as_of": None, "source": "signal.price"})):
            with self.subTest(label=label):
                result = entry(gate_state("paper", live_now(10, **fields)))
                self.assertFalse(result["allow"], result)
                self.assertNotIn("紙上模式僅警示", self.reasons(result))

    def test_the_legacy_flag_does_not_help_in_live(self):
        flagged = {"symbol": "TXF", "price": 45000.0, "source": "signal.price", "as_of": None, "legacy_price_only": True}
        self.assertFalse(entry(gate_state("live", flagged))["allow"])

    def test_paper_still_blocks_a_quote_that_was_sent_but_is_bad(self):
        for label, q in (("過期", live_now(500)), ("未來", live_now(-60)), ("商品不符", live_now(10, symbol="MXF")),
                         ("價格無效", live_now(10, price=NAN))):
            with self.subTest(label=label):
                self.assertFalse(entry(gate_state("paper", q))["allow"], label)

    def test_paper_with_a_fresh_quote_has_no_quote_warning(self):
        result = entry(gate_state("paper", live_now(10)))
        self.assertTrue(result["allow"])
        self.assertNotIn("行情", self.reasons(result))

    def test_paper_can_be_made_strict(self):
        with mock.patch.object(risk, "PAPER_REQUIRES_QUOTE", True):
            self.assertFalse(entry(gate_state("paper", None))["allow"])
            self.assertTrue(entry(gate_state("paper", live_now(10)))["allow"])

    def test_rules_mode_is_left_to_the_strategy_contract(self):
        for mode in ("paper", "live"):
            result = entry(gate_state(mode, None, strategy="rules"))
            self.assertTrue(result["allow"], result)
            self.assertNotIn("行情", self.reasons(result))

    def test_quote_policy_never_blocks_exits_reductions_or_holds(self):
        for action in ("EXIT", "REDUCE", "HOLD"):
            for q in (None, live_now(500)):
                with self.subTest(action=action, q=q):
                    self.assertTrue(entry(gate_state("live", q), action)["allow"])

    def test_missing_mode_means_paper_like_the_default_state(self):
        state = gate_state("paper", None)
        del state["mode"]
        self.assertTrue(entry(state)["allow"])

    def test_unrecognised_mode_is_strict(self):
        self.assertFalse(entry(gate_state("staging", live_now(10)))["allow"])

    def test_stored_quality_is_ignored_freshness_is_recomputed(self):
        stored = dict(live_now(500), quality="fresh", entry_allowed=True)
        self.assertFalse(entry(gate_state("live", stored))["allow"])


class EngineIntakeTests(unittest.TestCase):
    """handle_signal 把行情驗證後存進狀態；價格只有一個來源；閘門看到的就是存進去的那份。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        for target, value in (("server.state.DATA", home), ("server.state.STATE_PATH", home / "runtime_state.json"),
                              ("server.audit.DATA", home)):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        from server import engine
        from server.decision import HeuristicProvider
        from server.state import RUNTIME, _default_state
        patcher = mock.patch.object(RUNTIME, "_state", _default_state())
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("push_async", "notify_override_alpha"):
            patcher = mock.patch.object(engine, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        # 不留倉規則依真實時鐘（13:25 後擋新單），關掉才不隨時間變紅。
        RUNTIME.patch(no_overnight={"enabled": False})
        decision = HeuristicProvider().infer({"style": 50, "event": "X", "positions": {"account": 0}, "price": 45000})
        decision.update(action="ENTER_LONG", action_label="多單進場", confidence=0.95)
        self.engine, self.runtime, self.decision = engine, RUNTIME, decision
        patcher = mock.patch.object(engine, "infer_with_fallback", side_effect=lambda ctx, name=None: (dict(self.decision), None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, body, mode="paper"):
        self.runtime.patch(mode=mode)
        return self.engine.handle_signal({"symbol": "TXF", "event": "BREAKOUT", "provider": "heuristic", **body})

    def test_a_valid_quote_is_stored_and_supplies_the_price(self):
        result = self.send({"price": 1.0, "quote": live_now(10, price=45123.0)})
        state = self.runtime.snapshot()
        self.assertEqual((state["quote"]["quality"], state["quote"]["price"]), ("fresh", 45123.0))
        self.assertEqual(state["exec"]["price"], 45123.0)                 # quote 有效時，price 欄位被忽略
        self.assertTrue(result["gate"]["allow"], result["gate"])

    def test_price_only_signal_is_recorded_as_unknown_time(self):
        self.send({"price": 45050})
        state = self.runtime.snapshot()
        self.assertEqual((state["quote"]["quality"], state["quote"]["source"], state["quote"]["as_of"]), ("unknown", "signal.price", None))
        self.assertIs(state["quote"]["legacy_price_only"], True)
        self.assertEqual(state["exec"]["price"], 45050)

    def test_a_sender_cannot_forge_the_legacy_flag(self):
        forged = live_now(10, as_of="bad timestamp", legacy_price_only=True)
        result = self.send({"quote": forged})
        self.assertNotIn("legacy_price_only", self.runtime.snapshot()["quote"])
        self.assertFalse(result["gate"]["allow"], result["gate"])

    def test_a_timed_review_does_not_wash_a_stale_quote_into_a_legacy_one(self):
        blocked = self.send({"quote": live_now(500)})
        self.assertFalse(blocked["gate"]["allow"])
        stored = self.runtime.snapshot()["quote"]
        review = self.send({"event": "TIMED_MARKET_REVIEW"})            # 只有快取的 exec.price，沒有新行情
        self.assertEqual(self.runtime.snapshot()["quote"], stored)       # 已存的行情與時間戳原樣保留
        self.assertFalse(review["gate"]["allow"], review["gate"])
        self.assertIn("行情已過期", " ".join(review["gate"]["reasons"]))

    def test_a_timed_review_reuses_a_fresh_quote_and_its_original_timestamp_in_live(self):
        self.send({"quote": live_now(10)})
        stored = self.runtime.snapshot()["quote"]
        review = self.send({"event": "TIMED_MARKET_REVIEW"}, mode="live")
        self.assertEqual(self.runtime.snapshot()["quote"], stored)
        self.assertTrue(review["gate"]["allow"], review["gate"])        # 仍在 90 秒內：沿用，不被洗成「時間未知」

    def test_only_a_trustworthy_quote_price_replaces_the_signal_price(self):
        for label, q in (("過期", live_now(500, price=1.0)), ("未來", live_now(-60, price=1.0)),
                         ("時間未知", live_now(10, price=1.0, as_of=None))):
            with self.subTest(label=label):
                self.send({"price": 45050, "quote": q})
                self.assertEqual(self.runtime.snapshot()["exec"]["price"], 45050)
        self.send({"price": 45050, "quote": live_now(10, price=45123.0)})
        self.assertEqual(self.runtime.snapshot()["exec"]["price"], 45123.0)

    def test_a_bad_quote_does_not_replace_the_price_but_is_recorded(self):
        self.send({"price": 45050, "quote": live_now(10, symbol="MXF")})
        state = self.runtime.snapshot()
        self.assertEqual(state["quote"]["quality"], "invalid")
        self.assertEqual(state["exec"]["price"], 45050)                   # 沿用舊的價格規則，不因壞行情把價格清成 None

    def test_paper_entry_with_a_stale_quote_is_blocked_by_the_gate(self):
        result = self.send({"quote": live_now(500)})
        self.assertFalse(result["gate"]["allow"], result["gate"])
        self.assertIn("行情已過期", " ".join(result["gate"]["reasons"]))

    def test_paper_entry_with_price_only_still_passes_with_a_warning(self):
        result = self.send({"price": 45050})
        self.assertTrue(result["gate"]["allow"], result["gate"])
        self.assertIn("紙上模式僅警示", " ".join(result["gate"]["reasons"]))

    def test_live_entry_with_price_only_is_blocked(self):
        result = self.send({"price": 45050}, mode="live")
        self.assertFalse(result["gate"]["allow"], result["gate"])
        self.assertIn("行情來源時間未知", " ".join(result["gate"]["reasons"]))

    def test_exit_is_not_blocked_by_a_missing_quote_in_live(self):
        self.decision.update(action="EXIT", action_label="全部出場")
        result = self.send({"price": 45050}, mode="live")
        self.assertTrue(result["gate"]["allow"], result["gate"])


if __name__ == "__main__":
    unittest.main()
