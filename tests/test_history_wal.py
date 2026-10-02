"""持續讀取歷史的 HTTP 請求不可阻擋新觀測提交；快照本身仍固定。"""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import decision_context
import early_warning


class HistoryWalTests(unittest.TestCase):
    def exercise(self,path,initialize=None):
        with closing(sqlite3.connect(path)) as conn,conn:
            conn.execute('CREATE TABLE sample(value INTEGER)')
            conn.execute('INSERT INTO sample VALUES(1)')
        if initialize:initialize(str(path))
        with closing(sqlite3.connect(path,timeout=.05)) as reader,closing(sqlite3.connect(path,timeout=.05)) as writer:
            reader.execute('BEGIN');self.assertEqual(reader.execute('SELECT count(*) FROM sample').fetchone()[0],1)
            try:
                writer.execute('INSERT INTO sample VALUES(2)');writer.commit()
                self.assertEqual(reader.execute('SELECT count(*) FROM sample').fetchone()[0],1)
                reader.rollback()
                self.assertEqual(reader.execute('SELECT count(*) FROM sample').fetchone()[0],2)
            finally:reader.rollback();writer.rollback()

    def test_prior_delete_journal_reproduces_reader_blocking_commit(self):
        with tempfile.TemporaryDirectory() as temp,self.assertRaisesRegex(sqlite3.OperationalError,'locked'):
            self.exercise(Path(temp)/'before.db')

    def test_both_history_databases_allow_commit_during_read_snapshot(self):
        for module in (decision_context,early_warning):
            with self.subTest(module=module.__name__),tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'after.db';self.exercise(path,module._init_db)
                with closing(sqlite3.connect(path)) as conn:self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0],'wal')


if __name__=='__main__':unittest.main()
