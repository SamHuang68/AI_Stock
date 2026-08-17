#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_dist import make_zip

ROOT = Path(__file__).resolve().parents[1]


class BuildReproducibilityTests(unittest.TestCase):
    def test_html_build_is_byte_reproducible_and_does_not_mutate_input(self):
        source = ROOT / 'stock_terminal.html'
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / 'first.html'
            second = Path(temp) / 'second.html'
            for output in (first, second):
                subprocess.run(
                    [sys.executable, str(ROOT / 'build_v2.py'), '--out', str(output)],
                    cwd=ROOT, check=True, capture_output=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_zip_metadata_and_bytes_are_reproducible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / 'Stock_Terminal'
            stage.mkdir()
            (stage / 'a.txt').write_text('stable\n', encoding='utf-8')
            first = root / 'first.zip'
            second = root / 'second.zip'
            make_zip(stage, first)
            make_zip(stage, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == '__main__':
    unittest.main()
