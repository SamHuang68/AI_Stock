#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from server.secret_store import load_secret, load_secret_json, save_secret, save_secret_json


class SecretStoreTests(unittest.TestCase):
    def test_secret_and_bundle_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            secret = Path(td) / 'key.bin'
            bundle = Path(td) / 'bundle.bin'
            save_secret(secret, 'sk-example')
            save_secret_json(bundle, {'token': 'abc', 'password': 'def'})
            self.assertEqual(load_secret(secret), 'sk-example')
            self.assertEqual(load_secret_json(bundle), {'token': 'abc', 'password': 'def'})
            self.assertTrue(secret.read_bytes().startswith(
                (b'STDPAPI1\x00', b'STDPAPIM1\x00', b'STPLAIN1\x00')))

    def test_clear_does_not_resurrect_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'key.bin'
            save_secret(path, 'first')
            save_secret(path, '')
            self.assertEqual(load_secret(path), '')


if __name__ == '__main__':
    unittest.main()
