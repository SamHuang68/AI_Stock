#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest import mock
from contextlib import closing

from server import datastore


class DatastoreMarketIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, 'market.db')
        self.path_patch = mock.patch.object(datastore, 'DB_PATH', self.db_path)
        self.path_patch.start()
        datastore.init_db()

    def tearDown(self):
        self.path_patch.stop()
        self.temp.cleanup()

    def test_same_symbol_timestamp_can_exist_in_two_markets(self):
        row_tw = [(100, 1, 2, 0.5, 1.5, 10)]
        row_us = [(100, 10, 20, 5, 15, 100)]
        datastore.upsert_bars('SHARED', 'TW', row_tw)
        datastore.upsert_bars('SHARED', 'US', row_us)
        self.assertEqual(datastore.get_bars('SHARED', market='TW')[0][4], 1.5)
        self.assertEqual(datastore.get_bars('SHARED', market='US')[0][4], 15)

    def test_legacy_schema_migrates_and_keeps_recovery_backup(self):
        legacy = os.path.join(self.temp.name, 'legacy.db')
        with closing(sqlite3.connect(legacy)) as conn:
            conn.executescript('''
              CREATE TABLE bars(symbol TEXT NOT NULL, market TEXT NOT NULL, ts INTEGER NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol, ts));
              CREATE TABLE meta(symbol TEXT PRIMARY KEY, market TEXT, name TEXT, last_update INTEGER);
              INSERT INTO bars VALUES('2330','TW',100,1,2,0.5,1.5,10);
              INSERT INTO meta VALUES('2330','TW','台積電',100);
            ''')
        with mock.patch.object(datastore, 'DB_PATH', legacy):
            datastore.init_db()
            self.assertEqual(datastore.get_bars('2330', market='TW')[0][4], 1.5)
            self.assertTrue(os.path.exists(legacy + '.pre-market-key-v2.bak'))
            with closing(sqlite3.connect(legacy)) as conn:
                pk = [r[1] for r in sorted((r for r in conn.execute('PRAGMA table_info(bars)') if r[5]), key=lambda r: r[5])]
            self.assertEqual(pk, ['market', 'symbol', 'ts'])


if __name__ == '__main__':
    unittest.main()
