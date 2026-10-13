"""PR198 後續：分欄品質、日期缺口與已核對區間，不降低拒絕條件。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from datetime import date
from unittest.mock import patch
from tests.test_日線分欄品質 import BASE, DAY, receipt_for
from tests.已核對資料 import 價格資料, 交易日
import datastore
import portfolio
import daily_quality
from 台股日線 import stamp


class 投組價格契約(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'market.db'
        datastore.init_db(self.db)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330','TW',*BASE))
            conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', ('TW','2330',DAY,DAY,'合成已核對涵蓋'))

    def store(self, official):
        digest, receipt = receipt_for([official])
        datastore.upsert_bars('2330','TW',[official],source='TWSE',source_hash=digest,
                             path=self.db,source_receipt=receipt)

    def result(self):
        with datastore.read_snapshot(self.db) as conn:
            evidence = daily_quality.quality_evidence(conn,'2330')[DAY]
            values, issue = portfolio._risk_series(conn,'2330',[BASE])
        return evidence, values, issue

    def test_成交量差異不否決已核對價格(self):
        self.store((*BASE[:5],1200))
        evidence, values, issue = self.result()
        self.assertTrue(evidence['priceVerified'])
        self.assertTrue(evidence['volumeConflict'])
        self.assertEqual(values,{DAY:101})
        self.assertIsNone(issue)

    def test_價格衝突仍拒絕(self):
        self.store((*BASE[:4],100,1200))
        evidence, values, issue = self.result()
        self.assertTrue(evidence['priceConflict'])
        self.assertEqual(values,{})
        self.assertIn('衝突',issue)

    def test_未知品質問題仍拒絕(self):
        self.store(BASE)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE bar_quality SET issues=?',(json.dumps(['未知品質問題']),))
        self.assertEqual(self.result()[1],{})
        self.assertIn('未解問題',self.result()[2])

    def test_沒有收據仍拒絕原價(self):
        _, values, issue = self.result()
        self.assertEqual(values,{})
        self.assertIn('尚未核對',issue)

    def test_舊年日曆未知不抹除後續已核對區間(self):
        days = 交易日('2025-01-02',80)
        rows = [(stamp(d),100+i,101+i,99+i,100+i,1000) for i,d in enumerate(days)]
        old = (stamp(date(2016,1,4)),90,91,89,90,1000)
        with 價格資料({'2330':[old]+rows,'^TWII':[old]+rows}):
            out = portfolio.compute([{'sym':'2330','weight':1}])
        self.assertEqual(out['portfolio']['days'],79)
        self.assertTrue(out['quality']['available'])

    def test_日曆全未知不能變成可用風險(self):
        days = 交易日('2016-01-04',80)
        rows = [(stamp(d),100+i,101+i,99+i,100+i,1000) for i,d in enumerate(days)]
        with 價格資料({'2330':rows,'^TWII':rows}):
            out = portfolio.compute([{'sym':'2330','weight':1}])
        self.assertEqual(out['portfolio']['days'],0)
        self.assertFalse(out['quality']['available'])
