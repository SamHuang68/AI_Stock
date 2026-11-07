#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from daemon_lock import acquire_daemon_lock, release_daemon_lock  # noqa: E402


class DaemonLockTests(unittest.TestCase):
    def test_second_owner_is_blocked_and_release_allows_reacquire(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_dir = Path(temp_dir)
            first = acquire_daemon_lock("watch_daemon", lock_dir=lock_dir)
            self.assertIsNotNone(first)
            try:
                second = acquire_daemon_lock("watch_daemon", lock_dir=lock_dir)
                self.assertIsNone(second)
            finally:
                release_daemon_lock(first)
            third = acquire_daemon_lock("watch_daemon", lock_dir=lock_dir)
            self.assertIsNotNone(third)
            release_daemon_lock(third)

    def test_invalid_lock_name_is_rejected(self):
        with self.assertRaises(ValueError):
            acquire_daemon_lock("../outside")

    def test_release_helper_load_by_file_path_needs_only_the_standard_library(self):
        # scripts/private_web_release.py 以 runpy.run_path、scripts/local_release.py 以 spec_from_file_location
        # 按檔案路徑載入本檔：此時 __package__ 為空、server/ 不在 sys.path，旁邊只有標準函式庫。
        # 本檔是發布 helper（local_release 先驗雜湊再執行，sealed stage 的測試 fixture 也只複製兩個 helper 檔），
        # 所以不能在匯入時依賴 server/ 的其他模組（階段 3a 曾因 import data_paths 讓發布工具無法啟動）。
        # 發布 helper 一律明示 lock_dir；預設鎖目錄走 data_paths，必須延後到真的用到時才解析。
        code = (
            "import runpy, sys\n"
            "from pathlib import Path\n"
            "helpers = runpy.run_path(sys.argv[1])\n"
            "handle = helpers['acquire_daemon_lock']('private-web-release', lock_dir=Path(sys.argv[2]))\n"
            "assert handle is not None, 'lock not acquired'\n"
            "helpers['release_daemon_lock'](handle)\n"
            "assert 'data_paths' not in sys.modules, 'helper load imported data_paths'\n"
            "print('helper-load-ok')\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            # -I：不加入目前目錄與腳本目錄，也不吃 PYTHONPATH，與真實的 runpy 載入情境一樣看不到 server/。
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code, str(ROOT / "server" / "daemon_lock.py"), temp_dir],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("helper-load-ok", result.stdout)

    def test_acquire_without_lock_dir_uses_the_default_lock_dir(self):
        # 沒給 lock_dir 時鎖檔要建在 default_lock_dir() 給的目錄；換成暫存目錄，避免在倉庫的 data/ 留下鎖檔。
        import daemon_lock
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(daemon_lock, "default_lock_dir", return_value=Path(temp_dir)):
                handle = acquire_daemon_lock("default-dir-case")
            try:
                self.assertIsNotNone(handle)
                self.assertTrue((Path(temp_dir) / "default-dir-case.lock").is_file())
            finally:
                release_daemon_lock(handle)

    def test_default_lock_dir_attribute_is_kept_and_unknown_names_still_fail(self):
        # DEFAULT_LOCK_DIR 改為延後解析後，既有的模組屬性讀法（legacy 路徑契約測試、runtime_storage）必須照舊可用，
        # 且與函式給出同一個路徑；其他不存在的名稱仍要丟 AttributeError，不能被這個轉接吞掉。
        import daemon_lock
        self.assertEqual(daemon_lock.DEFAULT_LOCK_DIR, daemon_lock.default_lock_dir())
        self.assertEqual(daemon_lock.DEFAULT_LOCK_DIR.parts[-2:], ("data", "runtime_locks"))
        with self.assertRaises(AttributeError):
            daemon_lock.NO_SUCH_NAME


if __name__ == "__main__":
    unittest.main()
