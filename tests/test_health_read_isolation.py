"""限定驗證：唯讀體檢不得重新建表或等待寫入鎖。"""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
import datastore as ds
import stock_signals_routes as routes

class HealthReadIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"market.db"
        self.patch=mock.patch.object(ds,"DB_PATH",str(self.path))
        self.patch.start(); self.addCleanup(self.patch.stop)
        ds.init_db()
        with closing(ds.get_conn()) as conn:
            conn.executemany("INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)",[
                ("SAME","TW",1,100,101,99,100,1000),
                ("SAME","TW",2,102,103,101,102,2000),
                ("SAME","US",1,10,11,9,10,100)])
            conn.commit()

    def test_cold_health_does_not_wait_for_global_writer(self):
        done=threading.Event(); result={}
        def read():
            try: result["rows"]=routes._datastore().get_bars("SAME",market="TW")
            except Exception as exc:result["error"]=repr(exc)
            finally:done.set()
        # 不依 25ms 級機器速度斷言；持鎖時完成本身即證明無相依。
        with mock.patch.object(ds,"init_db",side_effect=AssertionError("GET 不可初始化")), \
             mock.patch.object(ds,"get_conn",side_effect=AssertionError("GET 不可開寫入連線")):
            ds._db_write_lock.acquire()
            thread=threading.Thread(target=read)
            try:
                thread.start()
                completed=done.wait(3)
            finally:
                ds._db_write_lock.release()
                thread.join(3)
        self.assertTrue(completed,"唯讀體檢被無關寫入鎖擋住")
        self.assertNotIn("error",result)
        self.assertEqual([r[4] for r in result["rows"]],[100,102])

    def test_read_during_uncommitted_wal_writer_preserves_snapshot_market_and_limit(self):
        with closing(ds.get_conn()) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE bars SET close=999 WHERE market='TW' AND ts=2")
            self.assertEqual(ds.get_bars("SAME",limit=1,market="TW")[0][4],102)
            self.assertEqual(ds.get_bars("SAME",market="US")[0][4],10)
            writer.rollback()

    def test_missing_database_read_does_not_create_database(self):
        absent=Path(self.temp.name)/"absent"/"market.db"
        with mock.patch.object(ds,"DB_PATH",str(absent)):
            with self.assertRaises(sqlite3.OperationalError):
                ds.get_bars("SAME")
        self.assertFalse(absent.exists())
        self.assertFalse(absent.parent.exists())

    def test_route_reports_own_elapsed_time_without_mutating_cached_analysis(self):
        class Handler(routes.StockSignalsRoutesMixin):
            path="/stock-signals?sym=2330&market=TW&cacheOnly=1"
            def _ok(self,body):self.payload=json.loads(body)
            def _err(self,*args):raise AssertionError(args)
        cached={"ok":True,"symbol":"2330"}
        handler=Handler()
        with mock.patch.object(routes,"analyze_symbol",return_value=cached) as analyze, \
             mock.patch.object(routes.time,"perf_counter",side_effect=[10,10.125]):
            handler._handle_stock_signals()
        analyze.assert_called_once_with("2330","TW",allow_network=False)
        self.assertEqual(handler.payload["requestTiming"],{"serverElapsedMs":125.0,"scope":"handler-to-payload"})
        self.assertNotIn("requestTiming",cached)

if __name__=="__main__":unittest.main()
