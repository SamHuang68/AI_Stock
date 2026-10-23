# -*- coding: utf-8 -*-
"""JSONL trace lock: concurrent append + compaction stays parseable."""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import jsonl_trace  # noqa: E402


class TestJsonlTrace(unittest.TestCase):
    def test_truncated_utf8_tail_cannot_absorb_next_valid_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'trace.jsonl')
            with open(path, 'wb') as fh:
                fh.write(b'{"event":"old"}\n{"broken":"\xe4\xb8')
            with patch.object(jsonl_trace, 'log_once') as warning:
                jsonl_trace.append_jsonl(path, {'event': 'new'}, max_bytes=1, tail_lines=2)
            with open(path, encoding='utf-8') as fh:
                self.assertEqual([json.loads(line) for line in fh], [{'event': 'old'}, {'event': 'new'}])
            warning.assert_called_once()

    def test_repeated_oversized_compaction_normalizes_crlf_and_truncated_utf8(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'trace.jsonl')
            original = {'event': 'old', 'padding': 'x' * (256 * 1024)}
            with open(path, 'wb') as fh:
                fh.write(json.dumps(original).encode('utf-8') + b'\r\n{"broken":"\xe4\xb8')
            expected = [original]
            with patch.object(jsonl_trace, 'log_once') as warning:
                for number in range(3):
                    row = {'event': 'new', 'number': number, 'message': '完整紀錄'}
                    jsonl_trace.append_jsonl(path, row, max_bytes=256 * 1024, tail_lines=10)
                    expected.append(row)
                    self.assertGreater(os.path.getsize(path), 256 * 1024, '每次追加都必須觸發壓縮')
                    with open(path, 'rb') as fh:
                        raw = fh.read()
                    self.assertNotIn(b'\r', raw, '壓縮輸出僅使用 LF，不累加 CR')
                    self.assertTrue(raw.endswith(b'\n'))
                    self.assertEqual(raw.count(b'\n'), len(expected))
                    with open(path, encoding='utf-8') as fh:
                        self.assertEqual([json.loads(line) for line in fh.read().splitlines()], expected)
            warning.assert_called_once()

    def test_concurrent_append_and_compact_keeps_json_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'trace.jsonl')

            errors = []
            def writer(n):
                try:
                    for i in range(40):
                        jsonl_trace.append_jsonl(
                            path, {'n': n, 'i': i, 'pad': 'x' * 80},
                            max_bytes=2500, tail_lines=20)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(k,)) for k in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            with open(path, encoding='utf-8') as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
            self.assertGreater(len(lines), 0)
            self.assertLess(len(lines), 80)
            for ln in lines:
                row = json.loads(ln)
                self.assertIn('n', row)
                self.assertIn('i', row)


if __name__ == '__main__':
    unittest.main()
