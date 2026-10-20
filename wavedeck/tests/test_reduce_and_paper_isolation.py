"""審查 WD-05、WD-06：paper 不寫下單大師檔；減碼依現有部位降低而非全平。不連網、不寫正式資料。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import broker


class 減碼口數測試(unittest.TestCase):
    def test_減碼未指定口數時減半且不翻向(self):
        for current, expected in ((2, 1), (3, 1), (1, 0), (4, 2), (-2, -1), (-1, 0)):
            with self.subTest(current=current):
                self.assertEqual(broker._target("REDUCE", 2, current), expected)

    def test_減碼指定口數時依口數減且不超過現有部位(self):
        self.assertEqual(broker._target("REDUCE", 5, 3, requested=1), 2)
        self.assertEqual(broker._target("REDUCE", 5, -3, requested=2), -1)
        self.assertEqual(broker._target("REDUCE", 5, 2, requested=9), 0)

    def test_部位未知或為零時沿用平倉目標(self):
        self.assertEqual(broker._target("REDUCE", 2, None), 0)
        self.assertEqual(broker._target("REDUCE", 2, 0), 0)
        self.assertEqual(broker._target("EXIT", 2, 3), 0)
        self.assertEqual(broker._target("ENTER_LONG", 2, 0), 2)
        self.assertIsNone(broker._target("HOLD", 2, 1))

    def test_紙上減碼更新紙上部位(self):
        state = {"symbol": "TXF", "positions": {"account": 2, "strategy": 2, "txt_target": 2, "ai_suggested": 2}}
        out = broker.PaperBroker().apply_intent(state, {"action": "REDUCE"}, 2)
        self.assertEqual(out["positions"]["account"], 1)
        self.assertEqual(out["execution"]["target"], 1)


class 紙上隔離測試(unittest.TestCase):
    def test_只有_txt_master_可寫下單大師檔(self):
        with patch.object(broker, "get_broker", return_value=broker.PaperBroker()):
            self.assertFalse(broker.writes_master_files())
        with patch.object(broker, "get_broker", return_value=broker.TxtMasterBroker()):
            self.assertTrue(broker.writes_master_files())

    def test_紙上急停不產生任何下單大師檔(self):
        with tempfile.TemporaryDirectory() as td, \
                patch.object(broker, "_txt_dir", return_value=Path(td)), \
                patch.object(broker, "get_broker", return_value=broker.PaperBroker()):
            broker.panic_flatten({"symbol": "TXF", "exec": {"price": 1}, "positions": {"account": 1}})
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
