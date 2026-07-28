# -*- coding: utf-8 -*-
"""分享包不得含私人檔／大 regenerable DB。"""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestDistScrub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / 'scripts'))
        # build into temp
        cls.zip_path = Path(tempfile.gettempdir()) / 'st_scrub_test.zip'
        from build_dist import build  # noqa: E402
        build(cls.zip_path)

    def test_no_secrets_or_large_dbs(self):
        bad_names = (
            'ai_key.txt', 'alert_config.json', 'alert_rules.json',
            'watch_rules.json', 'watch_state.json', 'draw_store.json',
            'revision.md', 'tdcc_holders.db', 'margin_cycle.db',
        )
        with zipfile.ZipFile(self.zip_path, 'r') as zf:
            names = zf.namelist()
        for n in names:
            base = os.path.basename(n).lower()
            for bad in bad_names:
                self.assertNotEqual(base, bad.lower(), msg=f'found {n}')
            if 'chip_history' in n.replace('\\', '/') or 'etf_history' in n.replace('\\', '/'):
                if base != 'readme.txt' and base.endswith(('.json', '.csv')):
                    self.fail(f'personal history in zip: {n}')

    def test_has_core_files(self):
        with zipfile.ZipFile(self.zip_path, 'r') as zf:
            names = set(zf.namelist())
        joined = '\n'.join(names)
        self.assertIn('server/server.py', joined.replace('\\', '/'))
        self.assertIn('server/chart_registry.py', joined.replace('\\', '/'))
        self.assertIn('src/core/chart_registry_v3.js', joined.replace('\\', '/'))


if __name__ == '__main__':
    unittest.main()
