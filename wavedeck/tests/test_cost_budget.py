# -*- coding: utf-8 -*-
"""每日費用准入、持久化與模型回傳的純離線案例。"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# 獨立套件只注入 state 介面，避免載入真實狀態、憑證、網路或 GPU 閘門。
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_wavedeck_cost_fixture"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "server")]
state = types.ModuleType(PACKAGE + ".state")
state.DATA = Path(tempfile.gettempdir()) / "wavedeck_cost_fixture_unused"
state.now_iso = lambda: "2026-10-03 12:00:00"
sys.modules[PACKAGE] = package
sys.modules[PACKAGE + ".state"] = state
providers = importlib.import_module(PACKAGE + ".providers")
budget_module = importlib.import_module(PACKAGE + ".cost_budget")
config_module = importlib.import_module(PACKAGE + ".config")
BudgetError = budget_module.BudgetError
BudgetExceeded = budget_module.BudgetExceeded
CostBudget = budget_module.CostBudget
ModelPricing = budget_module.ModelPricing


def configuration(limit=5):
    return {"provider": "openai", "cost_budget": {"daily_limit_usd": limit}, "openai": {
        "model": "fixture-model", "timeout_sec": 1, "pricing": {"fixture-model": {
            "input_usd_per_million": "1", "output_usd_per_million": "2",
            "context_window_tokens": 1000, "max_output_tokens": 100,
            "output_limit_parameter": "max_completion_tokens",
            "limits_source": "純離線案例：假設供應者強制執行指定 context 與全部輸出 token 上限"}}}}


def raw_decision():
    return {"action": "HOLD", "confidence": 0.6, "bias_long": 0.6, "bias_short": 0.4,
            "summary": "資料有限，維持觀望。", "next_watch": ["等待確認"],
            "invalidation": {"price": None, "side": None}, "chase_risk": "medium"}


def response(usage=None):
    result = {"choices": [{"message": {"content": json.dumps(raw_decision(), ensure_ascii=False)}}]}
    if usage is not None:
        result["usage"] = usage
    return result


class CostBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "budget.sqlite3"
        self.cfg = configuration()
        self.pricing = ModelPricing.from_config(self.cfg["openai"], "fixture-model")
        self.clock = lambda: datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)

    def ledger(self, limit=5):
        return CostBudget(self.path, limit, clock=self.clock)

    def test_exact_boundary_and_nanodollar_rounding(self):
        ledger = self.ledger("0.0012")
        request, status = ledger.reserve(self.pricing)
        self.assertEqual(status["committed_usd"], 0.0012)
        self.assertEqual(status["available_usd"], 0)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve(self.pricing)
        with self.assertRaises(BudgetExceeded):
            self.ledger("5").reserve(self.pricing)
        self.assertEqual(self.ledger().snapshot()["limit_usd"], 0.0012)
        tiny = configuration()
        tiny["openai"]["pricing"]["fixture-model"]["input_usd_per_million"] = "0.00000001"
        price = ModelPricing.from_config(tiny["openai"], "fixture-model")
        self.assertEqual(price.cost_nanos(1, 0), 1)

    def test_one_nanodollar_short_is_denied(self):
        with self.assertRaises(BudgetExceeded):
            self.ledger("0.001199999").reserve(self.pricing)
        self.assertEqual(self.ledger().snapshot()["committed_usd"], 0)

    def test_concurrent_connections_reserve_once_each_within_limit(self):
        self.ledger("0.006")
        def attempt(_):
            try:
                self.ledger("0.006").reserve(self.pricing)
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            admitted = list(pool.map(attempt, range(30)))
        self.assertEqual(sum(admitted), 5)
        self.assertEqual(self.ledger("0.006").snapshot()["committed_usd"], 0.006)

    def test_restart_keeps_unfinished_reservation(self):
        request, _ = self.ledger("0.0012").reserve(self.pricing)
        reloaded = self.ledger("0.0012")
        self.assertEqual(reloaded.snapshot()["pending_requests"], 1)
        with self.assertRaises(BudgetExceeded):
            reloaded.reserve(self.pricing)
        reloaded.retain_unknown(request)
        self.assertEqual(self.ledger().snapshot()["unknown_requests"], 1)
        self.assertEqual(self.ledger().snapshot()["reserved_usd"], 0.0012)

    def test_independent_processes_and_restart_share_the_same_cap(self):
        self.ledger("0.006")
        script = '''
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("isolated_cost_budget", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
pricing = module.ModelPricing.from_config(json.loads(sys.stdin.read())["openai"], "fixture-model")
ledger = module.CostBudget(Path(sys.argv[2]), "0.006", clock=lambda: module.datetime(2026, 10, 3, 8, tzinfo=module.timezone.utc))
accepted = 0
for _ in range(5):
    try:
        ledger.reserve(pricing)
        accepted += 1
    except module.BudgetExceeded:
        pass
print(accepted)
'''
        def process(_):
            completed = subprocess.run([sys.executable, "-B", "-c", script,
                                        str(ROOT / "server" / "cost_budget.py"), str(self.path)],
                                       input=json.dumps(self.cfg), capture_output=True, text=True, timeout=20, check=True)
            return int(completed.stdout.strip())
        with ThreadPoolExecutor(max_workers=3) as pool:
            accepted = list(pool.map(process, range(3)))
        self.assertEqual(sum(accepted), 5)
        self.assertEqual(process(0), 0)
        self.assertEqual(self.ledger("0.006").snapshot()["committed_usd"], 0.006)

    def test_day_rollover_uses_fixed_taiwan_admission_day(self):
        current = [datetime(2026, 10, 3, 15, 59, 59, tzinfo=timezone.utc)]
        ledger = CostBudget(self.path, "0.0012", clock=lambda: current[0])
        request, before = ledger.reserve(self.pricing)
        self.assertEqual(before["day"], "2026-10-03")
        current[0] = datetime(2026, 10, 3, 16, 0, 0, tzinfo=timezone.utc)
        _, after = ledger.reserve(self.pricing)
        self.assertEqual(after["day"], "2026-10-04")
        settled = ledger.settle(request, self.pricing, {"prompt_tokens": 10, "completion_tokens": 2})
        self.assertEqual(settled["day"], "2026-10-03")
        self.assertEqual(settled["spent_usd"], 0.000014)
        self.assertEqual(ledger.snapshot()["reserved_usd"], 0.0012)

    def test_valid_usage_settles_once_and_releases_only_known_difference(self):
        ledger = self.ledger()
        request, _ = ledger.reserve(self.pricing)
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        status = ledger.settle(request, self.pricing, usage)
        self.assertEqual(status["spent_usd"], 0.00014)
        self.assertEqual(status["reserved_usd"], 0)
        self.assertEqual(ledger.settle(request, self.pricing, usage)["spent_usd"], 0.00014)
        with self.assertRaises(BudgetError):
            ledger.settle(request, self.pricing, {"prompt_tokens": 1, "completion_tokens": 2})

    def test_missing_invalid_usage_does_not_refund(self):
        ledger = self.ledger()
        request, _ = ledger.reserve(self.pricing)
        for usage in (None, {}, {"prompt_tokens": 0}, {"prompt_tokens": -1, "completion_tokens": 2},
                      {"prompt_tokens": True, "completion_tokens": 2}, {"prompt_tokens": 1.5, "completion_tokens": 2},
                      {"prompt_tokens": float("nan"), "completion_tokens": 2},
                      {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 2}):
            with self.subTest(usage=usage), self.assertRaises(BudgetError):
                ledger.settle(request, self.pricing, usage)
        self.assertEqual(ledger.snapshot()["reserved_usd"], 0.0012)

    def test_token_bound_breach_stops_future_days(self):
        ledger = self.ledger()
        request, _ = ledger.reserve(self.pricing)
        with self.assertRaises(BudgetError) as caught:
            ledger.settle(request, self.pricing, {"prompt_tokens": 1001, "completion_tokens": 0})
        self.assertTrue(caught.exception.budget["limit_breached"])
        tomorrow = CostBudget(self.path, 5, clock=lambda: datetime(2026, 10, 5, tzinfo=timezone.utc))
        with self.assertRaises(BudgetExceeded):
            tomorrow.reserve(self.pricing)

    def test_pricing_requires_exact_model_rates_and_verified_limits(self):
        with self.assertRaises(BudgetError):
            ModelPricing.from_config(self.cfg["openai"], "fixture-model-alias")
        for field, value in (("input_usd_per_million", None), ("output_usd_per_million", "NaN"),
                             ("output_usd_per_million", "Infinity"), ("output_usd_per_million", -1),
                             ("max_output_tokens", 0), ("context_window_tokens", None),
                             ("limits_source", ""), ("output_limit_parameter", "max_tokens")):
            cfg = deepcopy(self.cfg["openai"])
            cfg["pricing"]["fixture-model"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(BudgetError):
                ModelPricing.from_config(cfg, "fixture-model")
        for limit in (None, True, "NaN", "Infinity", -1):
            with self.subTest(limit=limit), self.assertRaises(BudgetError):
                self.ledger(limit)

    def test_excessive_price_precision_is_rejected_before_rounding(self):
        cfg = deepcopy(self.cfg["openai"])
        cfg["pricing"]["fixture-model"]["input_usd_per_million"] = "1.000000000000000000000000000001"
        with self.assertRaises(BudgetError):
            ModelPricing.from_config(cfg, "fixture-model")


class ProviderCostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "budget.sqlite3"
        self.cfg = configuration()
        self.http = self.enterContext(mock.patch.object(providers, "_http_json", side_effect=AssertionError("不可連網")))
        self.key = self.enterContext(mock.patch.object(providers, "openai_api_key", return_value="fixture-not-a-secret"))
        self.enterContext(mock.patch.object(providers, "load_config", side_effect=lambda: deepcopy(self.cfg)))
        self.enterContext(mock.patch.object(providers, "COST_BUDGET_PATH", self.path))
        self.enterContext(mock.patch.object(providers, "_llm_gate_acquire"))
        self.enterContext(mock.patch.object(providers, "_llm_gate_release"))

    def infer(self):
        return providers.infer_with_fallback({"event": "TIMED_MARKET_REVIEW"}, "openai")

    def test_default_config_blocks_paid_call_without_reading_secret(self):
        self.cfg = deepcopy(config_module._DEFAULT)
        self.cfg["provider"] = "openai"
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertEqual(decision["action"], "HOLD")
        self.assertEqual(decision["cloud_calls"], 0)
        self.assertTrue(decision["budget"]["blocked"])
        self.assertFalse(decision["budget"]["pricing_configured"])
        self.http.assert_not_called()
        self.key.assert_not_called()

    def test_unknown_model_is_not_charged_at_another_models_rate(self):
        self.cfg["openai"]["model"] = "unknown-model"
        decision, _ = self.infer()
        self.assertTrue(decision["budget"]["blocked"])
        self.http.assert_not_called()
        self.key.assert_not_called()
        with self.assertRaises(BudgetError):
            providers.estimate_openai_usd({"prompt_tokens": 1, "completion_tokens": 1}, "unknown-model")

    def test_normal_mock_response_reserves_before_http_and_limits_output(self):
        def success(url, payload, headers, timeout):
            ledger = CostBudget(self.path)
            self.assertEqual(ledger.snapshot()["reserved_usd"], 0.0012)
            self.assertEqual(payload["max_completion_tokens"], 100)
            self.assertNotIn("max_tokens", payload)
            return response({"prompt_tokens": 100, "completion_tokens": 20})
        self.http.side_effect = success
        decision, error = self.infer()
        self.assertIsNone(error)
        self.assertEqual(decision["cost_usd"], 0.00014)
        self.assertEqual(decision["budget"]["reserved_usd"], 0)
        self.assertTrue(decision["budget"]["usage_known"])
        self.assertIsNone(decision["invalidation"]["price"])

    def test_timeout_preserves_reservation_and_blocks_next_call(self):
        self.cfg["cost_budget"]["daily_limit_usd"] = "0.0012"
        self.http.side_effect = TimeoutError("不應向使用者暴露這段細節")
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertIsNone(decision["cost_usd"])
        self.assertEqual(decision["cloud_calls"], 1)
        self.assertEqual(decision["budget"]["reserved_usd"], 0.0012)
        self.assertEqual(decision["budget"]["unknown_requests"], 1)
        self.assertNotIn("細節", decision["summary"])
        second, _ = self.infer()
        self.assertEqual(second["cloud_calls"], 0)
        self.assertEqual(self.http.call_count, 1)

    def test_missing_usage_keeps_unknown_in_successful_decision(self):
        self.http.side_effect = None
        self.http.return_value = response()
        decision, error = self.infer()
        self.assertIsNone(error)
        self.assertIsNone(decision["cost_usd"])
        self.assertFalse(decision["budget"]["usage_known"])
        self.assertEqual(decision["budget"]["reserved_usd"], 0.0012)

    def test_invalid_json_retains_known_usage_and_safe_fallback(self):
        self.http.side_effect = None
        out = response({"prompt_tokens": 100, "completion_tokens": 20})
        out["choices"][0]["message"]["content"] = "<script>無效回傳</script>"
        self.http.return_value = out
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertEqual(decision["cost_usd"], 0.00014)
        self.assertEqual(decision["budget"]["spent_usd"], 0.00014)
        self.assertEqual(decision["action"], "HOLD")
        self.assertIsNone(decision["invalidation"]["price"])
        self.assertNotIn("MA20", decision["summary"])
        self.assertNotIn("script", decision["summary"])

    def test_unwritable_ledger_blocks_before_http(self):
        with mock.patch.object(providers, "_ledger", side_effect=OSError("唯讀")):
            decision, _ = self.infer()
        self.assertEqual(decision["budget"]["status"], "unavailable")
        self.assertIsNone(decision["budget"]["committed_usd"])
        self.http.assert_not_called()


class ProviderValidationTests(unittest.TestCase):
    def test_missing_invalidation_stays_unknown(self):
        raw = raw_decision()
        raw.pop("invalidation")
        result = providers._normalize(raw, "事件", "ollama")
        self.assertEqual(result["invalidation"], {"price": None, "side": None})

    def test_rejects_nonfinite_action_side_and_shapes(self):
        changes = [("action", "BUY"), ("action", []), ("confidence", float("nan")),
                   ("bias_long", float("inf")), ("bias_short", -0.1), ("confidence", True),
                   ("summary", {"html": "文字"}), ("next_watch", [{}]), ("invalidation", []),
                   ("invalidation", {"price": float("-inf"), "side": "below"}),
                   ("invalidation", {"price": 100, "side": "sideways"}),
                   ("chase_risk", "arbitrary"), ("unknown", {"value": float("nan")})]
        for key, value in changes:
            raw = raw_decision()
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                providers._normalize(raw, "事件", "openai")
        for raw in ([], None, "文字"):
            with self.assertRaises(ValueError):
                providers._normalize(raw, "事件", "openai")

    def test_json_rejects_nonfinite_duplicates_and_wrong_root(self):
        for raw in ('{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"action":"HOLD","action":"EXIT"}',
                    '[]', '前言 {"action":"HOLD"}', '"文字"'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                providers._extract_json(raw)

    def test_bounded_text_and_lists_remain_untrusted_plain_text(self):
        raw = raw_decision()
        raw["summary"] = "<img src=x onerror=alert(1)>" + "字" * 1000
        raw["next_watch"] = ["字" * 100] * 10
        result = providers._normalize(raw, "事" * 100, "openai")
        self.assertEqual(len(result["summary"]), 800)
        self.assertEqual(len(result["event"]), 80)
        self.assertEqual(len(result["next_watch"]), 6)
        self.assertEqual(len(result["next_watch"][0]), 80)
        self.assertTrue(result["summary"].startswith("<img"))


if __name__ == "__main__":
    unittest.main()
