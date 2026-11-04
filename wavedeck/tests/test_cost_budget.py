# -*- coding: utf-8 -*-
"""每日費用准入的純離線案例：帳本本身、供應者接線、engine 記帳，以及真實 HTTP 邊界（本機假供應者）。

帳本案例（CostBudgetTests）沿用 codex/wavedeck-paper-p0 的測試，測的是 cost_budget.py 本身；
供應者、engine 與 HTTP 邊界的案例針對 main 現行的 providers／engine 另寫。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import config as config_module  # noqa: E402
from server import cost_budget as budget_module  # noqa: E402
from server import providers  # noqa: E402

BudgetError = budget_module.BudgetError
BudgetExceeded = budget_module.BudgetExceeded
CostBudget = budget_module.CostBudget
ModelPricing = budget_module.ModelPricing
_REAL_HTTP_JSON = providers._http_json  # 在任何 mock 之前保存


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


FIXED_NOW = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)


class _ProviderFixture(unittest.TestCase):
    """供應者層共用：假金鑰、固定時鐘的臨時帳本、不連網、不碰共用推論閘門。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "budget.sqlite3"
        self.cfg = configuration()
        self.http = self.enterContext(mock.patch.object(providers, "_http_json", side_effect=AssertionError("不可連網")))
        self.key = self.enterContext(mock.patch.object(providers, "openai_api_key", return_value="fixture-not-a-secret"))
        self.enterContext(mock.patch.object(providers, "load_config", side_effect=lambda: deepcopy(self.cfg)))
        self.enterContext(mock.patch.object(providers, "COST_BUDGET_PATH", self.path))
        self.enterContext(mock.patch.object(providers, "_ledger", side_effect=self.ledger_for))
        self.enterContext(mock.patch.object(providers, "_llm_gate_acquire"))
        self.enterContext(mock.patch.object(providers, "_llm_gate_release"))

    def ledger_for(self, cfg):
        # 與供應者相同的建構方式，但用固定時鐘，測試不隨真實日界線變動。
        return CostBudget(self.path, cfg["cost_budget"]["daily_limit_usd"], clock=lambda: FIXED_NOW)

    def infer(self, name="openai"):
        return providers.infer_with_fallback({"event": "TIMED_MARKET_REVIEW"}, name)


class ProviderCostTests(_ProviderFixture):
    def test_default_config_blocks_paid_call_without_reading_secret(self):
        self.cfg = deepcopy(config_module._DEFAULT)
        self.cfg["provider"] = "openai"
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertEqual(decision["provider"], "heuristic")
        self.assertEqual(decision["cloud_calls"], 0)
        self.assertEqual(decision["cost_usd"], 0.0)  # 沒有送出任何請求，費用確定是零
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

    def test_missing_api_key_keeps_its_message_and_reserves_nothing(self):
        self.key.return_value = ""
        decision, error = self.infer()
        self.assertIn("缺少 OPENAI_API_KEY", error)
        self.assertIn("缺少 OPENAI_API_KEY", decision["summary"])
        self.assertEqual(decision["cloud_calls"], 0)
        self.assertEqual(self.ledger_for(self.cfg).snapshot()["committed_usd"], 0)
        self.http.assert_not_called()

    def test_normal_response_reserves_before_http_and_limits_output(self):
        def success(url, payload, headers, timeout):
            self.assertEqual(self.ledger_for(self.cfg).snapshot()["reserved_usd"], 0.0012)
            self.assertEqual(payload["max_completion_tokens"], 100)
            self.assertNotIn("max_tokens", payload)
            return response({"prompt_tokens": 100, "completion_tokens": 20})
        self.http.side_effect = success
        decision, error = self.infer()
        self.assertIsNone(error)
        self.assertEqual(decision["provider"], "openai")
        self.assertEqual(decision["cost_usd"], 0.00014)
        self.assertEqual(decision["cloud_calls"], 1)
        self.assertEqual(decision["budget"]["reserved_usd"], 0)
        self.assertEqual(decision["budget"]["committed_usd"], 0.00014)
        self.assertTrue(decision["budget"]["usage_known"])

    def test_timeout_preserves_reservation_and_blocks_next_call(self):
        self.cfg["cost_budget"]["daily_limit_usd"] = "0.0012"
        self.http.side_effect = TimeoutError("連線逾時")
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertEqual(decision["provider"], "heuristic")
        self.assertIsNone(decision["cost_usd"])  # 未知，不是 0
        self.assertEqual(decision["cloud_calls"], 1)
        self.assertEqual(decision["budget"]["reserved_usd"], 0.0012)
        self.assertEqual(decision["budget"]["unknown_requests"], 1)
        second, _ = self.infer()
        self.assertEqual(second["cloud_calls"], 0)
        self.assertEqual(self.http.call_count, 1)

    def test_missing_usage_keeps_unknown_in_an_otherwise_good_decision(self):
        self.http.side_effect = None
        self.http.return_value = response()
        decision, error = self.infer()
        self.assertIsNone(error)
        self.assertEqual(decision["provider"], "openai")
        self.assertIsNone(decision["cost_usd"])
        self.assertFalse(decision["budget"]["usage_known"])
        self.assertEqual(decision["budget"]["reserved_usd"], 0.0012)

    def test_unparseable_decision_still_charges_the_known_usage(self):
        out = response({"prompt_tokens": 100, "completion_tokens": 20})
        out["choices"][0]["message"]["content"] = "這不是 JSON"
        self.http.side_effect = None
        self.http.return_value = out
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertEqual(decision["provider"], "heuristic")
        self.assertEqual(decision["cost_usd"], 0.00014)
        self.assertEqual(decision["cloud_calls"], 1)
        self.assertEqual(decision["budget"]["spent_usd"], 0.00014)
        self.assertEqual(decision["budget"]["reserved_usd"], 0)

    def test_limit_breach_stops_the_following_paid_calls(self):
        self.http.side_effect = None
        self.http.return_value = response({"prompt_tokens": 1001, "completion_tokens": 0})
        decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertTrue(decision["budget"]["limit_breached"])
        calls = self.http.call_count
        later, _ = self.infer()
        self.assertEqual(self.http.call_count, calls)
        self.assertTrue(later["budget"]["blocked"])

    def test_unwritable_ledger_blocks_before_http(self):
        with mock.patch.object(providers, "_ledger", side_effect=OSError("唯讀")):
            decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertEqual(decision["budget"]["status"], "unavailable")
        self.assertIsNone(decision["budget"]["committed_usd"])
        self.http.assert_not_called()

    def test_local_provider_is_not_metered(self):
        self.http.side_effect = None
        self.http.return_value = {"response": json.dumps(raw_decision(), ensure_ascii=False)}
        decision, error = self.infer("ollama")
        self.assertIsNone(error)
        self.assertEqual((decision["cost_usd"], decision["local_calls"], decision["cloud_calls"]), (0.0, 1, 0))
        self.assertNotIn("budget", decision)
        self.assertFalse(self.path.exists())

    def test_estimate_uses_the_configured_price_only(self):
        usd = providers.estimate_openai_usd({"prompt_tokens": 100, "completion_tokens": 20}, "fixture-model")
        self.assertAlmostEqual(usd, 0.00014)
        with self.assertRaises(BudgetError):
            providers.estimate_openai_usd({"prompt_tokens": 100}, "fixture-model")  # usage 不完整，不補零

    def test_budget_status_reports_unconfigured_and_unavailable_as_blocked(self):
        configured = providers.budget_status(self.cfg)
        self.assertTrue(configured["pricing_configured"])
        self.assertFalse(configured["blocked"])
        self.assertEqual(configured["max_output_tokens"], 100)
        unconfigured = providers.budget_status(deepcopy(config_module._DEFAULT))
        self.assertTrue(unconfigured["blocked"])
        self.assertFalse(unconfigured["pricing_configured"])
        with mock.patch.object(providers, "_ledger", side_effect=OSError("唯讀")):
            unavailable = providers.budget_status(self.cfg)
        self.assertIsNone(unavailable["committed_usd"])  # 未知，不是 0
        self.assertTrue(unavailable["blocked"])


class _FakeOpenAI:
    """本機假供應者：收到請求的當下，直接讀磁碟上的帳本，證明預留早於請求到達。"""

    def __init__(self, ledger_path, reply, *, delay=0.0, status=200):
        self.ledger_path, self.reply, self.delay, self.status = ledger_path, reply, delay, status
        self.seen = []

    def __enter__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                con = sqlite3.connect(str(outer.ledger_path))
                try:
                    reserved = con.execute("SELECT COALESCE(SUM(reserved_nanos), 0) FROM budget_requests "
                                           "WHERE spent_nanos IS NULL").fetchone()[0]
                finally:
                    con.close()
                outer.seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                   "payload": body, "reserved_nanos_on_disk": reserved})
                if outer.delay:
                    threading.Event().wait(outer.delay)
                try:
                    data = json.dumps(outer.reply).encode("utf-8")
                    self.send_response(outer.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # 客戶端已逾時離開

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class LoopbackProviderTests(_ProviderFixture):
    """走真正的 urllib 與 JSON 邊界（只連 127.0.0.1 的假供應者），不用 mock 取代 _http_json。"""

    def setUp(self):
        super().setUp()
        self.http.side_effect = _REAL_HTTP_JSON  # 還原真實的 _http_json

    def test_reservation_is_on_disk_before_the_request_arrives_and_usage_settles_it(self):
        with _FakeOpenAI(self.path, response({"prompt_tokens": 100, "completion_tokens": 20})) as fake:
            self.cfg["openai"]["base"] = fake.base
            decision, error = self.infer()
        self.assertIsNone(error)
        sent = fake.seen[0]
        self.assertEqual(sent["path"], "/chat/completions")
        self.assertEqual(sent["auth"], "Bearer fixture-not-a-secret")
        self.assertEqual(sent["payload"]["max_completion_tokens"], 100)
        self.assertEqual(sent["reserved_nanos_on_disk"], 1_200_000)  # 請求到達時，1000×$1/M + 100×$2/M 已寫入磁碟
        self.assertEqual(decision["cost_usd"], 0.00014)
        self.assertEqual(self.ledger_for(self.cfg).snapshot()["reserved_usd"], 0)

    def test_a_response_slower_than_the_timeout_keeps_the_reservation(self):
        with _FakeOpenAI(self.path, response({"prompt_tokens": 100, "completion_tokens": 20}), delay=3.0) as fake:
            self.cfg["openai"]["base"] = fake.base
            self.cfg["openai"]["timeout_sec"] = 0.3
            decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertIsNone(decision["cost_usd"])
        self.assertEqual(decision["budget"]["unknown_requests"], 1)
        self.assertEqual(self.ledger_for(self.cfg).snapshot()["reserved_usd"], 0.0012)

    def test_an_http_error_status_keeps_the_reservation(self):
        with _FakeOpenAI(self.path, {"error": {"message": "server busy"}}, status=500) as fake:
            self.cfg["openai"]["base"] = fake.base
            decision, error = self.infer()
        self.assertIsNotNone(error)
        self.assertIsNone(decision["cost_usd"])
        self.assertEqual(self.ledger_for(self.cfg).snapshot()["unknown_requests"], 1)


class EngineCostTests(unittest.TestCase):
    """完整路徑：handle_signal → providers → 費用帳本 → RUNTIME.costs。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        for target, value in (("server.state.DATA", home), ("server.state.STATE_PATH", home / "runtime_state.json"),
                              ("server.audit.DATA", home), ("server.config.DATA", home),
                              ("server.config.CONFIG_PATH", home / "wavedeck_config.json"),
                              ("server.config.SECRETS_PATH", home / "wavedeck_secrets.json"),
                              ("server.providers.COST_BUDGET_PATH", home / "budget.sqlite3")):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.path = home / "budget.sqlite3"
        cfg = configuration()
        cfg.update(mode="paper", broker={"kind": "paper"})
        (home / "wavedeck_config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        from server import engine
        from server.state import RUNTIME, _default_state
        patcher = mock.patch.object(RUNTIME, "_state", _default_state())
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("push_async", "notify_override_alpha"):
            patcher = mock.patch.object(engine, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        RUNTIME.patch(no_overnight={"enabled": False})  # 不留倉規則依真實時鐘，關掉才不隨時間變紅
        self.http = self.enterContext(mock.patch.object(providers, "_http_json", side_effect=AssertionError("不可連網")))
        self.enterContext(mock.patch.object(providers, "openai_api_key", return_value="fixture-not-a-secret"))
        self.enterContext(mock.patch.object(providers, "_ledger", side_effect=lambda c: CostBudget(
            self.path, c["cost_budget"]["daily_limit_usd"], clock=lambda: FIXED_NOW)))
        self.enterContext(mock.patch.object(providers, "_llm_gate_acquire"))
        self.enterContext(mock.patch.object(providers, "_llm_gate_release"))
        self.engine, self.runtime = engine, RUNTIME

    def send(self):
        return self.engine.handle_signal({"symbol": "TXF", "event": "BREAKOUT", "provider": "openai", "price": 45123})

    def test_known_usage_lands_in_costs_and_the_ledger_is_the_day_figure(self):
        self.http.side_effect = None
        self.http.return_value = response({"prompt_tokens": 100, "completion_tokens": 20})
        self.send()
        costs = self.runtime.snapshot()["costs"]
        self.assertEqual((costs["session_usd"], costs["day_usd"], costs["month_usd"]), (0.00014, 0.00014, 0.00014))
        self.assertEqual(costs["cloud_calls"], 1)
        self.assertEqual(costs["budget"]["spent_usd"], 0.00014)
        self.assertEqual(costs["budget"]["limit_usd"], 5)
        self.assertEqual(costs["provider"], "openai")

    def test_unknown_cost_is_not_zero_the_day_figure_keeps_the_reservation(self):
        self.http.side_effect = TimeoutError("連線逾時")
        self.send()
        costs = self.runtime.snapshot()["costs"]
        self.assertEqual(costs["day_usd"], 0.0012)       # 已用及預留：未知費用不會少報
        self.assertEqual(costs["session_usd"], 0)        # session／month 只累計已知費用
        self.assertEqual(costs["cloud_calls"], 1)
        self.assertEqual(costs["budget"]["unknown_requests"], 1)
        self.assertEqual(costs["provider"], "heuristic")

    def test_blocked_request_is_visible_and_costs_nothing(self):
        cfg = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
        cfg["openai"]["pricing"] = {}
        config_module.CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
        self.send()
        costs = self.runtime.snapshot()["costs"]
        self.assertEqual((costs["day_usd"], costs["cloud_calls"]), (0.0, 0))
        self.assertTrue(costs["budget"]["blocked"])
        self.assertFalse(costs["budget"]["pricing_configured"])
        self.http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
