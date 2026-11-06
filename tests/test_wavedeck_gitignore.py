"""WaveDeck 在 `wavedeck/data/` 底下寫的每一個執行期檔案，都必須被 git 忽略。

起因：`wavedeck.instance.lock` 沒被忽略，在 worktree 跑 WaveDeck 相關測試會留下未追蹤檔，驗證計畫執行器把它當成
「沒有對應案例的變更」而拒絕；`wavedeck_cost_budget.sqlite3`（#293 新增）同樣沒被忽略，只是執行中的 WaveDeck 還沒載入
#293，所以還沒長出來，一重啟就會變成第二個同類未追蹤檔。根因是每次新增執行期檔案時，沒人回頭補 `.gitignore`。

兩層檢查：
1. 明列的已知執行期檔案（建立它們的位置寫在註解裡，改檔名時一起改）。
2. 掃描 `wavedeck/server` 原始碼裡 `DATA / "<檔名>"` 的寫法：之後有人用同樣的寫法新增檔案卻沒補 `.gitignore`，會在這裡失敗。
另有反向檢查：被追蹤的 `.gitkeep` 不能被忽略（避免規則寫得太寬）。

判定用 `git check-ignore`，並清掉個人的全域忽略設定（`core.excludesFile`），免得開發者自己的全域規則掩蓋缺漏。
不在 git 工作樹裡（例如單機分享包）或沒有 git 時跳過，不當成通過也不當成失敗。
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = "wavedeck/data/"

# 不是 `DATA / "..."` 寫法建立、所以掃描看不到的檔案（括號內是建立它的位置）。
KNOWN_RUNTIME_FILES = (
    "wavedeck.instance.lock",   # server/程序單例.py：單一實例鎖
    "wavedeck.port",            # server/server.py：埠檔
    "wavedeck_audit.db",        # server/audit.py：稽核資料庫（SQLite，另有 -wal／-shm）
    "程式版本.json",             # server/版本身分.py：發布收據
)
# 掃描必須找得到的檔名；找不到代表掃描規則已經失效（空轉就會永遠通過）。
SCAN_MUST_FIND = (
    "runtime_state.json",
    "wavedeck_config.json",
    "wavedeck_secrets.json",
    "wavedeck_cost_budget.sqlite3",
)
SQLITE_SUFFIXES = (".db", ".sqlite3")
SQLITE_COMPANIONS = ("-wal", "-shm")
DATA_LITERAL = re.compile(r'\bDATA\s*/\s*"([^"/\\]+)"')


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.excludesFile=", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )


def _with_companions(names) -> set[str]:
    out = set(names)
    for name in names:
        if name.endswith(SQLITE_SUFFIXES):
            out.update(name + suffix for suffix in SQLITE_COMPANIONS)
    return out


def _scan_data_files() -> set[str]:
    """`wavedeck/server/*.py` 裡 `DATA / "<有副檔名的檔名>"` 的檔名（沒有副檔名的是資料夾，不在此列）。"""
    found: set[str] = set()
    for path in sorted((ROOT / "wavedeck" / "server").glob("*.py")):
        for match in DATA_LITERAL.finditer(path.read_text(encoding="utf-8")):
            if "." in match.group(1):
                found.add(match.group(1))
    return found


class WaveDeckGitignoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = _git("rev-parse", "--is-inside-work-tree")
        except (OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f"沒有可用的 git：{error}")
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            raise unittest.SkipTest("不在 git 工作樹內（例如單機分享包），無法判定忽略規則")

    def _ignored(self, relative: str) -> bool:
        # --no-index：預設 check-ignore 不判定已被追蹤的檔案，反向檢查（.gitkeep）會因此空轉通過
        result = _git("check-ignore", "-q", "--no-index", "--", relative)
        self.assertIn(result.returncode, (0, 1), f"git check-ignore 失敗：{result.stderr.strip()}")
        return result.returncode == 0

    def test_已知的執行期檔案都被忽略(self):
        for name in sorted(_with_companions(KNOWN_RUNTIME_FILES)):
            with self.subTest(file=name):
                self.assertTrue(self._ignored(DATA_DIR + name), f"{DATA_DIR}{name} 沒被 wavedeck/.gitignore 忽略")

    def test_掃描到的data檔案都被忽略(self):
        scanned = _scan_data_files()
        missing = [name for name in SCAN_MUST_FIND if name not in scanned]
        self.assertFalse(missing, f"掃描規則找不到既有的檔名，規則已失效：{missing}")
        for name in sorted(_with_companions(scanned)):
            with self.subTest(file=name):
                self.assertTrue(self._ignored(DATA_DIR + name), f"{DATA_DIR}{name} 沒被 wavedeck/.gitignore 忽略")

    def test_被追蹤的gitkeep沒被誤忽略(self):
        for relative in (DATA_DIR + ".gitkeep", DATA_DIR + "exec_md/.gitkeep"):
            with self.subTest(file=relative):
                tracked = _git("ls-files", "--error-unmatch", "--", relative)
                self.assertEqual(tracked.returncode, 0, f"{relative} 應被追蹤")
                self.assertFalse(self._ignored(relative), f"{relative} 被忽略規則誤傷")


if __name__ == "__main__":
    unittest.main()
