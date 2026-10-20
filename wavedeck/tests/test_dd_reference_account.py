"""審查 WD-04：示範參考帳戶的權益不可觸發每日回撤鎖或自動全平。沿用隔離套件，不連網。"""
import importlib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location("_回撤參考帳戶基礎", Path(__file__).with_name("test_策略訊號整合.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
_base = _fixture.策略訊號整合測試

DEMO = {"source": "wave_ai_ref", "reference": True, "yesterday_balance": 72312, "equity": 59888}


class 回撤參考帳戶測試(unittest.TestCase):
    setUp = _base.setUp
    tearDown = _base.tearDown
    clear_modules = _base.clear_modules
    signal = _base.signal

    def risk(self):
        return importlib.import_module(self.package + ".risk")

    def test_示範帳戶回撤未知且不擋新單(self):
        risk = self.risk()
        state = {"account": dict(DEMO), "st_overlay": {}, "st_link": {"status": "ok"},
                 "no_overnight": {"enabled": False}, "style": 60, "exec": {"lots": 1}}
        self.assertFalse(risk.daily_dd_known(state))
        self.assertEqual(risk.daily_dd_ratio(state), 0.0)
        gate = risk.evaluate_gate(state, {"action": "ENTER_LONG", "confidence": 0.9, "process": {"chase_risk": "low"}})
        self.assertFalse(any("禁止新單" in r and "回撤" in r for r in gate["reasons"]), gate)
        self.assertTrue(any("回撤未知" in r for r in gate["reasons"]), gate)
        # 同樣數字但明確標示為實盤：照舊鎖定
        real = dict(state, account=dict(DEMO, reference=False))
        self.assertTrue(risk.daily_dd_known(real))
        self.assertFalse(risk.evaluate_gate(real, {"action": "ENTER_LONG", "confidence": 0.9, "process": {"chase_risk": "low"}})["allow"])

    def test_示範帳戶不鎖定也不全平_既有急停不解除(self):
        self.engine.system_control("start")
        self.engine.handle_signal(self.signal())
        held = self.runtime.snapshot()["positions"]["account"]
        self.assertNotEqual(held, 0)
        self.runtime.patch(account=dict(DEMO))
        with patch.object(self.engine, "panic", wraps=self.engine.panic) as panic:
            self.assertFalse(self.engine.enforce_daily_drawdown(True, False))
        panic.assert_not_called()
        st = self.runtime.snapshot()
        self.assertFalse(st["kill_switch"])
        self.assertEqual(st["positions"]["account"], held)
        self.assertEqual(st["account"]["daily_dd_status"], "unknown_reference")
        self.assertIsNone(st["account"]["daily_dd_pct"])
        # 已在急停中：維持急停，不因參考帳戶而解除
        self.runtime.set_kill(True)
        self.assertTrue(self.engine.enforce_daily_drawdown(True, True))
        self.assertTrue(self.runtime.snapshot()["kill_switch"])

    def test_實盤帳戶回撤超限仍鎖定並全平(self):
        self.engine.system_control("start")
        self.engine.handle_signal(self.signal())
        self.runtime.patch(account=dict(DEMO, reference=False, source="broker"))
        self.assertTrue(self.engine.enforce_daily_drawdown(True, False))
        st = self.runtime.snapshot()
        self.assertTrue(st["kill_switch"])
        self.assertEqual(st["positions"]["account"], 0)
        self.assertEqual(st["account"]["daily_dd_status"], "measured")


if __name__ == "__main__":
    unittest.main()
