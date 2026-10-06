"""log_once：同 key 同例外型別限頻；新的例外型別一定立刻記錄。"""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import log_once as lo  # noqa: E402


class LogOnceTests(unittest.TestCase):
    def setUp(self):
        lo.reset_for_tests()

    def emit(self, key, exc=None, now=0.0, interval=600.0, message='msg'):
        out = io.StringIO()
        wrote = lo.log_once(key, message, exc=exc, interval=interval, now=now, out=out)
        return wrote, out.getvalue()

    def test_first_call_writes_one_line_with_key_message_and_exception(self):
        wrote, text = self.emit('quote-batch', RuntimeError('boom'), message='2330.TW failed')
        self.assertTrue(wrote)
        self.assertEqual(text, '[quote-batch] 2330.TW failed RuntimeError: boom\n')

    def test_same_key_and_exception_type_is_rate_limited_until_the_interval_passes(self):
        self.assertTrue(self.emit('k', ValueError('a'), now=0.0)[0])
        self.assertFalse(self.emit('k', ValueError('b'), now=599.0)[0])       # 限頻內：不寫
        self.assertTrue(self.emit('k', ValueError('c'), now=600.0)[0])        # 滿 interval：再寫一行

    def test_a_new_exception_type_under_the_same_key_is_logged_immediately(self):
        # 先前被連線逾時佔住的 key，遇到 NameError 這種新型別必須立刻看得見（本規則的重點）。
        self.assertTrue(self.emit('k', TimeoutError('slow'), now=0.0)[0])
        self.assertTrue(self.emit('k', NameError("name 'math' is not defined"), now=1.0)[0])
        self.assertFalse(self.emit('k', NameError('again'), now=2.0)[0])

    def test_different_keys_do_not_suppress_each_other(self):
        self.assertTrue(self.emit('a', ValueError('x'), now=0.0)[0])
        self.assertTrue(self.emit('b', ValueError('x'), now=0.0)[0])

    def test_without_an_exception_it_still_rate_limits_and_prints_the_message(self):
        wrote, text = self.emit('plain', None, now=0.0, message='degraded')
        self.assertTrue(wrote)
        self.assertEqual(text, '[plain] degraded\n')
        self.assertFalse(self.emit('plain', None, now=10.0)[0])

    def test_default_output_goes_to_stdout_like_the_rest_of_the_server_log(self):
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        try:
            self.assertTrue(lo.log_once('k', 'hello', now=0.0))
        finally:
            sys.stdout = old
        self.assertEqual(buf.getvalue(), '[k] hello\n')


if __name__ == '__main__':
    unittest.main()
