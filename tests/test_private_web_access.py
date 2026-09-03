#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from private_web_access import (  # noqa: E402
    AccessRequestStore,
    AccessValidationError,
)


class AccessRequestStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "access.json"
        self.store = AccessRequestStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_persists_private_request_and_returns_copy(self):
        row, created = self.store.create(
            display_name="王小明",
            contact_email="User@Example.com",
            tailscale_email="Tail@Example.com",
            platform="both",
            note="Chrome only",
        )
        self.assertTrue(created)
        self.assertRegex(row["id"], r"^ST-\d{8}-[A-F0-9]{6}$")
        self.assertEqual(row["contactEmail"], "user@example.com")
        self.assertEqual(row["status"], "pending")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["requests"][0]["tailscaleEmail"], "tail@example.com")

    def test_open_duplicate_is_idempotent(self):
        first, _ = self.store.create(
            display_name="Reader One",
            contact_email="reader@example.com",
            tailscale_email="tail@example.com",
            platform="iphone",
        )
        second, created = self.store.create(
            display_name="Reader Duplicate",
            contact_email="other@example.com",
            tailscale_email="TAIL@example.com",
            platform="windows",
        )
        self.assertFalse(created)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.store.list_requests()), 1)

    def test_update_status_keeps_bounded_history(self):
        row, _ = self.store.create(
            display_name="Reader Two",
            contact_email="reader2@example.com",
            tailscale_email="tail2@example.com",
            platform="windows",
        )
        updated = self.store.update_status(
            row["id"], status="tailscale_invited", admin_note="Verified"
        )
        self.assertEqual(updated["status"], "tailscale_invited")
        self.assertEqual(updated["adminNote"], "Verified")
        self.assertEqual(updated["history"][-1]["status"], "tailscale_invited")

    def test_rejects_invalid_or_oversized_fields(self):
        with self.assertRaises(AccessValidationError):
            self.store.create(
                display_name="A",
                contact_email="not-an-email",
                tailscale_email="also-invalid",
                platform="android",
            )
        with self.assertRaises(AccessValidationError):
            self.store.create(
                display_name="Valid Name",
                contact_email="valid@example.com",
                tailscale_email="valid@example.com",
                platform="iphone",
                note="x" * 501,
            )


if __name__ == "__main__":
    unittest.main()
