#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherSafetyTests(unittest.TestCase):
    def test_canonical_windows_launcher_never_discards_work(self):
        script = (ROOT / 'scripts' / 'go.ps1').read_text(encoding='utf-8')
        lowered = script.lower()
        for destructive in ('reset --hard', 'checkout -f', 'git stash', 'clean -fd'):
            self.assertNotIn(destructive, lowered)
        self.assertIn('git status --porcelain', script)
        self.assertIn('git merge --ff-only', script)
        self.assertIn('Resolve-StockPython', script)

    def test_batch_files_are_ascii_shims_and_only_stop_the_owned_port(self):
        go = (ROOT / 'scripts' / 'go.bat').read_bytes()
        start = (ROOT / 'START_TIP.cmd').read_bytes()
        go.decode('ascii')
        start.decode('ascii')
        go_text = go.decode('ascii').lower()
        start_text = start.decode('ascii').lower()
        self.assertIn('go.ps1', go_text)
        self.assertNotRegex(go_text, r'(?m)^\s*git\s+')
        self.assertIn(':18432', start_text)
        self.assertNotIn('taskkill /im python', start_text)


if __name__ == '__main__':
    unittest.main()
