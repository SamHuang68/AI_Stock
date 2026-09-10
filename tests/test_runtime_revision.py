"""驗證啟動版本的來源與失敗邊界。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import runtime_revision as revision


class RuntimeRevisionTests(unittest.TestCase):
    def test_release_manifest_takes_precedence_and_bad_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            manifest = root / ".private_web_release.json"
            with patch.object(revision.subprocess, "run") as run:
                for value, expected in [({"commit": "a" * 40}, "a" * 40), ({"commit": "short"}, None), ([], None)]:
                    manifest.write_text(json.dumps(value), encoding="utf-8")
                    self.assertEqual(revision.read_revision(root), expected)
                run.assert_not_called()

    def test_checkout_reads_its_own_git_revision_and_handles_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            result = revision.subprocess.CompletedProcess([], 0, stdout="b" * 40 + "\n")
            with patch.object(revision.subprocess, "run", return_value=result) as run:
                self.assertEqual(revision.read_revision(root), "b" * 40)
                self.assertEqual(run.call_args.kwargs["cwd"], root)
            with patch.object(revision.subprocess, "run", side_effect=revision.subprocess.TimeoutExpired("git", 5)):
                self.assertIsNone(revision.read_revision(root))

    def test_archive_without_manifest_cannot_inherit_parent_repository_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(revision.subprocess, "run") as run:
                self.assertIsNone(revision.read_revision(Path(directory)))
                run.assert_not_called()
