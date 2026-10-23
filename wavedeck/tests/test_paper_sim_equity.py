"""審查 WD-07：紙上模擬權益（成交帳本、權益、交易日起始權益）與券商切換。不連網、不寫正式資料。"""
import importlib
import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import paper_account
from server.state import TZ8

_spec = importlib.util.spec_from_file_location("_紙上權益基礎", Path(__file__).with_name("test_策略訊號整合.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
_base = _fixture.策略訊號整合測試

PV = 200
CFG = {"paper_account": {"starting_equity": 1_000_000, "point_value": PV}}


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ8)


class 成交帳本測試(unittest.TestCase):
    def test_加碼減碼反手平倉依序實現損益(self):
        ledger = paper_account.apply_fill(None, 2, 45000, PV)
        self.assertEqual((ledger["position"], ledger["avgPrice"], ledger["realized"]), (2, 45000, 0))
        ledger = paper_account.apply_fill(ledger, 4, 45100, PV)          # 加碼：平均成本加權
        self.assertEqual((ledger["position"], ledger["avgPrice"]), (4, 45050))
        ledger = paper_account.apply_fill(ledger, 1, 45150, PV)          # 減碼 3 口，成本不變
        self.assertEqual((ledger["position"], ledger["avgPrice"], ledger["realized"]), (1, 45050, 100 * 3 * PV))
        ledger = paper_account.apply_fill(ledger, -2, 45000, PV)         # 反手：先平 1 口再以成交價開空 2 口
        self.assertEqual((ledger["position"], ledger["avgPrice"], ledger["realized"]), (-2, 45000, 60000 - 50 * PV))
        ledger = paper_account.apply_fill(ledger, 0, 44900, PV)          # 空單平倉獲利
        self.assertEqual((ledger["position"], ledger["avgPrice"], ledger["realized"]), (0, None, 50000 + 100 * 2 * PV))
        self.assertFalse(ledger["priceUnknown"])

    def test_部位不變不動帳本(self):
        ledger = paper_account.apply_fill(None, 2, 45000, PV)
        self.assertEqual(paper_account.apply_fill(ledger, 2, 46000, PV), ledger)

    def test_缺成交價時權益未知直到部位歸零(self):
        ledger = paper_account.apply_fill(None, 2, None, PV)
        self.assertTrue(ledger["priceUnknown"])
        state = {"paper_ledger": ledger, "positions": {"account": 2}, "exec": {"price": 45000}}
        account = paper_account.refresh(state, CFG, at("2026-10-21T10:00"))["account"]
        self.assertIsNone(account["equity"])
        self.assertEqual(account["equity_status"], "price_unknown")
        ledger = paper_account.apply_fill(ledger, 0, 45000, PV)
        self.assertEqual((ledger["position"], ledger["priceUnknown"]), (0, False))


class 權益與交易日測試(unittest.TestCase):
    def test_權益含已實現與未實現且當日起始權益固定(self):
        ledger = paper_account.apply_fill(None, 2, 45000, PV)
        state = {"paper_ledger": ledger, "positions": {"account": 2}, "exec": {"price": 45000}}
        out = paper_account.refresh(state, CFG, at("2026-10-21T09:00"))
        self.assertEqual(out["account"]["equity"], 1_000_000)
        self.assertEqual(out["account"]["yesterday_balance"], 1_000_000)
        self.assertEqual(out["paper_ledger"]["day"], "2026-10-21")
        state = dict(state, paper_ledger=out["paper_ledger"], exec={"price": 44800})
        account = paper_account.refresh(state, CFG, at("2026-10-21T12:00"))["account"]
        self.assertEqual(account["unrealized"], -200 * 2 * PV)
        self.assertEqual(account["equity"], 1_000_000 - 80000)
        self.assertEqual(account["yesterday_balance"], 1_000_000)   # 同交易日不重設基準
        self.assertEqual(account["equity_change"], -80000)
        self.assertEqual(account["equity_status"], "measured")
        self.assertIs(account["reference"], False)

    def test_夜盤換日以新交易日第一筆權益為基準(self):
        state = {"paper_ledger": {"day": "2026-10-21", "dayStartEquity": 1_000_000, "realized": -30000},
                 "positions": {"account": 0}, "exec": {"price": 45000}}
        out = paper_account.refresh(state, CFG, at("2026-10-21T15:05"))
        self.assertEqual(out["paper_ledger"]["day"], "2026-10-22")
        self.assertEqual(out["account"]["yesterday_balance"], 970000)

    def test_交易日以十五點換日且週末順延週一(self):
        self.assertEqual(paper_account.trading_day(at("2026-10-21T14:59")), "2026-10-21")
        self.assertEqual(paper_account.trading_day(at("2026-10-21T15:00")), "2026-10-22")
        self.assertEqual(paper_account.trading_day(at("2026-10-23T15:00")), "2026-10-26")   # 週五夜盤
        self.assertEqual(paper_account.trading_day(at("2026-10-24T03:00")), "2026-10-26")   # 週六凌晨夜盤
        self.assertEqual(paper_account.trading_day(at("2026-10-26T08:45")), "2026-10-26")

    def test_帳本與部位不一致時權益未知且不建立基準(self):
        state = {"paper_ledger": {}, "positions": {"account": 1}, "exec": {"price": 45000}}
        out = paper_account.refresh(state, CFG, at("2026-10-21T09:00"))
        self.assertIsNone(out["account"]["equity"])
        self.assertIsNone(out["account"]["yesterday_balance"])
        self.assertEqual(out["account"]["equity_status"], "ledger_mismatch")
        self.assertNotIn("day", out["paper_ledger"])


class 引擎整合測試(unittest.TestCase):
    setUp = _base.setUp
    tearDown = _base.tearDown
    clear_modules = _base.clear_modules
    signal = _base.signal
    txt = _base.txt

    def test_txt_round_trip_restores_paper_positions_receipt_and_ledger(self):
        self.engine.handle_signal(self.signal())
        paper = self.runtime.snapshot()
        self.txt(account=5)
        self.engine.sync_broker_positions()
        self.assertEqual(self.runtime.snapshot()['positions']['account'], 5)
        self.runtime.patch(execution={'order_id': 'live-pending', 'status': 'sent', 'position_confirmed': False})
        restored = self.engine.set_exec_mode('paper')['state']
        self.assertEqual(restored['positions'], paper['positions'])
        self.assertEqual(restored['execution']['order_id'], paper['execution']['order_id'])
        self.assertEqual(restored['execution']['evidence_kind'], 'simulated')
        for key in ('position', 'avgPrice', 'realized', 'priceUnknown'):
            self.assertEqual(restored['paper_ledger'][key], paper['paper_ledger'][key])
        self.assertEqual(restored['account']['equity_status'], 'measured')
        self.assertIsNotNone(restored['account']['equity'])
        self.assertEqual(restored['fsm'], 'InPosition')

    def test_broker_switch_restores_existing_ledger_without_a_legacy_paper_snapshot(self):
        self.txt(account=5)
        self.runtime.patch(paper_runtime=None, paper_ledger={'position': 2, 'avgPrice': 45020, 'realized': 0, 'priceUnknown': False})
        restored = self.engine.set_broker('paper')['state']
        self.assertEqual(restored['positions']['account'], 2)
        self.assertEqual(restored['exec']['lots'], 2)
        self.assertIsNone(restored['execution'].get('order_id'))
        self.assertIsNone(restored['exec']['price'])
        self.assertIsNone(restored['account']['equity'])
        self.assertEqual(restored['account']['equity_status'], 'price_unknown')

    def test_legacy_paper_restore_does_not_value_ledger_with_txt_price(self):
        self.txt(account=5)
        self.runtime.patch(mode='live', paper_runtime=None, exec={'price': 200},
                           paper_ledger={'position': 1, 'avgPrice': 100, 'realized': 0, 'priceUnknown': False})
        restored = self.engine.set_exec_mode('paper')['state']
        self.assertEqual(restored['positions']['account'], 1)
        self.assertEqual(restored['paper_ledger']['position'], 1)
        self.assertEqual(restored['paper_ledger']['avgPrice'], 100)
        self.assertFalse(restored['paper_ledger']['priceUnknown'])
        self.assertIsNone(restored['exec']['price'])
        self.assertIsNone(restored['account']['mark_price'])
        self.assertIsNone(restored['account']['equity'])
        self.assertIsNone(restored['account']['unrealized'])
        self.assertEqual(restored['account']['equity_status'], 'price_unknown')

    def test_mode_round_trip_keeps_existing_ledger_mismatch_and_kill_protection(self):
        self.runtime.patch(positions={'account': 2}, paper_ledger={'position': 1, 'avgPrice': None, 'priceUnknown': True})
        self.engine.set_kill_switch(True)
        self.txt(account=5)
        restored = self.engine.set_broker('paper')['state']
        self.assertEqual(restored['positions']['account'], 2)
        self.assertEqual(restored['paper_ledger']['position'], 1)
        self.assertIsNone(restored['account']['equity'])
        self.assertEqual(restored['account']['equity_status'], 'ledger_mismatch')
        self.assertTrue(restored['kill_switch'])
        self.assertEqual(restored['fsm'], 'Halted')

    def test_紙上成交記帳且回撤可量測(self):
        self.engine.system_control("start")
        st = self.engine.refresh_account()
        self.assertEqual(st["account"]["source"], "paper_sim")
        self.assertEqual(st["account"]["equity"], 1_000_000)
        self.engine.handle_signal(self.signal())
        st = self.runtime.snapshot()
        self.assertEqual(st["paper_ledger"]["position"], st["positions"]["account"])
        self.assertEqual(st["paper_ledger"]["avgPrice"], 45020)
        self.runtime.patch(exec={"price": 45070})
        self.assertFalse(self.engine.enforce_daily_drawdown(True, False))
        account = self.runtime.snapshot()["account"]
        self.assertEqual(account["equity"], 1_000_000 + 50 * st["positions"]["account"] * PV)
        self.assertEqual(account["daily_dd_status"], "measured")
        self.assertEqual(account["daily_dd_pct"], 0)

    def test_切換到下單大師撤下模擬權益改回參考帳戶(self):
        self.engine.system_control("start")
        self.assertEqual(self.engine.refresh_account()["account"]["source"], "paper_sim")
        self.txt(account=0)
        self.assertFalse(self.engine.enforce_daily_drawdown(True, False))
        account = self.runtime.snapshot()["account"]
        self.assertTrue(account["reference"])
        self.assertNotEqual(account["source"], "paper_sim")
        self.assertEqual(account["daily_dd_status"], "unknown_reference")
        self.assertFalse(self.runtime.snapshot()["kill_switch"])


del _base

if __name__ == "__main__":
    unittest.main()
