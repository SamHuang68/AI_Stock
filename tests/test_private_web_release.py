#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import private_web_release as release  # noqa: E402


def _write(path: Path, value: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fake_release(root: Path, release_id: str) -> Path:
    target = root / "releases" / release_id
    for relative in release.REQUIRED_RELEASE_FILES:
        _write(target / relative, "new")
    _write(target / "server" / "new_module.py", "new-code")
    _write(target / "data" / "public_seed.csv", "seed")
    manifest = {
        "releaseId": release_id,
        "commit": release_id.ljust(40, "0"),
        "tests": "passed",
        "managedTopLevel": ["server", "scripts", "stock_terminal_v2.html"],
    }
    _write(
        target / ".private_web_release.json",
        json.dumps(manifest),
    )
    return target


class PrivateWebReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.install_root = Path(self.temp.name) / "private" / "install"
        self.install_root.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_promotion_requires_explicit_approval(self):
        _fake_release(self.install_root, "abc123")
        with self.assertRaises(PermissionError):
            release.promote_release(
                self.install_root,
                release_id="abc123",
                approved=False,
            )

    def test_promote_replaces_code_but_preserves_runtime_data_and_logs(self):
        _fake_release(self.install_root, "abc123")
        current = self.install_root / "current"
        _write(current / "server" / "old_module.py", "old-code")
        _write(current / "data" / "private_web_owner.token", "secret")
        _write(current / "data" / "personal.db", "personal")
        _write(current / "logs" / "audit.jsonl", "audit")
        _write(
            current / ".private_web_release.json",
            json.dumps(
                {
                    "releaseId": "old000",
                    "tests": "passed",
                    "managedTopLevel": ["server", ".private_web_release.json"],
                }
            ),
        )

        promoted = release.promote_release(
            self.install_root,
            release_id="abc123",
            approved=True,
        )
        self.assertEqual(promoted, current)
        self.assertFalse((current / "server" / "old_module.py").exists())
        self.assertEqual((current / "server" / "new_module.py").read_text(), "new-code")
        self.assertEqual((current / "data" / "private_web_owner.token").read_text(), "secret")
        self.assertEqual((current / "data" / "personal.db").read_text(), "personal")
        self.assertEqual((current / "data" / "public_seed.csv").read_text(), "seed")
        self.assertEqual((current / "logs" / "audit.jsonl").read_text(), "audit")
        active = json.loads((current / ".private_web_release.json").read_text())
        self.assertEqual(active["releaseId"], "abc123")
        self.assertIn("promotedAt", active)

    def test_unverified_release_is_not_promoted(self):
        target = _fake_release(self.install_root, "def456")
        manifest_path = target / ".private_web_release.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["tests"] = "skipped"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "passed tests"):
            release.promote_release(
                self.install_root,
                release_id="def456",
                approved=True,
            )

    def test_private_release_omits_wavedeck_runtime(self):
        tree = self.install_root / "candidate"
        _write(tree / "wavedeck" / "run.py", "wd")
        _write(tree / "START_WAVEDECK.cmd", "wd")
        _write(tree / "server" / "server.py", "st")
        release._strip_private_release_extras(tree)
        self.assertFalse((tree / "wavedeck").exists())
        self.assertFalse((tree / "START_WAVEDECK.cmd").exists())
        self.assertTrue((tree / "server" / "server.py").is_file())


if __name__ == "__main__":
    unittest.main()
