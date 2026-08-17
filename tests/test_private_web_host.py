#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import private_web_host as host  # noqa: E402


class PrivateWebHostTests(unittest.TestCase):
    def test_port_probe_rejects_an_existing_listener(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        try:
            port = listener.getsockname()[1]
            self.assertFalse(host._port_available("127.0.0.1", port))
        finally:
            listener.close()

    def test_existing_gateway_blocks_before_any_child_is_spawned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token = Path(temp_dir) / "data" / "private_web_owner.token"
            token.parent.mkdir(parents=True)
            token.write_text("test-token\n", encoding="utf-8")
            log_dir = Path(temp_dir) / "logs"
            with (
                mock.patch.object(host, "ROOT", Path(temp_dir)),
                mock.patch.object(host, "LOGS", log_dir),
                mock.patch.object(
                    host,
                    "_health_payload",
                    return_value={
                        "ok": True,
                        "gateway": "private-web",
                        "mode": "dev-linked",
                    },
                ),
                mock.patch.object(host, "_spawn") as spawn,
            ):
                code = host.run(backend_port=18435, gateway_port=18434, max_restarts=1)
            self.assertEqual(code, 3)
            spawn.assert_not_called()
            record = json.loads((log_dir / "private_web_host.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["event"], "preflight_blocked")
            self.assertEqual(record["reason"], "gateway_already_running")
            self.assertTrue(record["runId"])


if __name__ == "__main__":
    unittest.main()
