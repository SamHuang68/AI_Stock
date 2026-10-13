"""明示合成交易日曆及單一還原快照；不替換產品品質判定。"""
import json
import sqlite3
import tempfile
from pathlib import Path
from contextlib import contextmanager, closing
from datetime import date, timedelta
from unittest.mock import patch


def 交易日(start, count):
    day = date.fromisoformat(start) if isinstance(start, str) else start
    days = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def 建立日曆(conn, years=range(2020, 2031)):
    # 合成市場明定週一至週五開市；與行情序列分開建立，缺列仍會被發現。
    conn.execute('CREATE TABLE IF NOT EXISTS calendar_years(year INTEGER PRIMARY KEY,closed TEXT,opened TEXT,refreshed_at TEXT)')
    conn.executemany('INSERT OR REPLACE INTO calendar_years VALUES(?,?,?,?)',
                     [(y, '[]', '[]', '合成日曆') for y in years])


def 建立價格快照(conn, data):
    import datastore
    from stock_signals import normalize_bars
    conn.executescript(datastore.SCHEMA)
    建立日曆(conn)
    conn.execute('CREATE TABLE IF NOT EXISTS stock_adjustment_snapshots(market TEXT,symbol TEXT,fetched_at INTEGER,payload TEXT)')
    for symbol, rows in data.items():
        conn.executemany('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?)',
                         [(symbol, 'TW', *row) for row in rows])
        payload = {'source': '合成單一來源', 'events': {}, 'rows': [
            {'date': b['date'], 'rawClose': b['close'], 'adjClose': b['close']}
            for b in normalize_bars(rows) if b['close'] is not None]}
        conn.execute('INSERT INTO stock_adjustment_snapshots VALUES(?,?,?,?)',
                     ('TW', symbol, 1, json.dumps(payload)))
    conn.commit()


@contextmanager
def 價格資料(data):
    import datastore
    # HTTP handler 與主測試執行緒各自取得唯讀連線，不共用 thread-bound connection。
    with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(Path(folder) / 'market.db')) as conn:
        path = Path(folder) / 'market.db'
        建立價格快照(conn, data)
        @contextmanager
        def snapshot(*args, **kwargs):
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as reader:
                reader.execute('PRAGMA query_only=ON')
                reader.execute('BEGIN')
                yield reader
        with patch.object(datastore, 'read_snapshot', side_effect=snapshot):
            yield conn


@contextmanager
def 日曆資料():
    with 價格資料({}) as conn:
        yield conn
