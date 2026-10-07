"""既有行情庫的官方盤後批次更新；不以個別頁面是否開啟決定研究覆蓋。"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import datastore
import http_client
import stock_signals as ss
import chip_history_tracker as chips
from atomic_store import atomic_write_json, load_json
from sector_flow import normalize_session_date
from 台股交易參考 import session, eligible_bar
from signal_stats_pool import _TICKER_RE

SOURCES = {
    'TWSE': 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={day}&type=ALL&response=json',
    'TPEx': 'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes',
}


def parse_twse_market(payload, expected_day, symbols):
    """全部收盤行情包含 ETF；以欄名定位，仍共用日期與 OHLC 驗證。"""
    day = expected_day.replace('-', '')
    if not isinstance(payload, dict) or payload.get('stat') != 'OK' or payload.get('date') != day:
        raise ValueError('證交所全部收盤行情日期未到齊，拒絕寫入')
    mapping = {'證券代號': 'Code', '開盤價': 'OpeningPrice', '最高價': 'HighestPrice',
               '最低價': 'LowestPrice', '收盤價': 'ClosingPrice', '成交股數': 'TradeVolume'}
    tables = [table for table in payload.get('tables', []) if isinstance(table, dict)
              and set(mapping).issubset(table.get('fields') or [])]
    if len(tables) != 1:
        raise ValueError('證交所全部收盤行情欄位缺漏或資料表重複')
    table = tables[0]
    indexes = {name: table['fields'].index(name) for name in mapping}
    rows = []
    for values in table.get('data', []):
        if not isinstance(values, list) or len(values) <= max(indexes.values()):
            raise ValueError('證交所全部收盤行情資料列不完整')
        rows.append({'Date': day, **{key: values[indexes[name]] for name, key in mapping.items()}})
    return parse_quotes(rows, 'TWSE', expected_day, symbols)


def parse_quotes(payload, exchange, expected_day, symbols):
    if not isinstance(payload, list) or not payload:
        raise ValueError('官方日線沒有可辨識的資料列')
    key = expected_day.replace('-', '')
    keys = ('Code', 'OpeningPrice', 'HighestPrice', 'LowestPrice', 'ClosingPrice', 'TradeVolume') if exchange == 'TWSE' else (
        'SecuritiesCompanyCode', 'Open', 'High', 'Low', 'Close', 'TradingShares')
    stamp = int(datetime.fromisoformat(expected_day).replace(hour=9, tzinfo=ss._TZ['TW']).timestamp())
    output, unavailable = {}, []
    for row in payload:
        if normalize_session_date(row.get('Date')) != key:
            raise ValueError('官方日線日期尚未到齊或混合日期，拒絕寫入')
        code = str(row.get(keys[0]) or '').strip()
        if code not in symbols:
            continue
        if not eligible_bar(code, expected_day):
            continue
        values = [ss._finite(str(row.get(k, '')).replace(',', '')) for k in keys[1:]]
        if (any(v is None for v in values) or min(values[:4]) <= 0 or values[-1] <= 0
                ):
            unavailable.append(code)
            continue
        op, hi, lo, close, volume = values
        if hi < max(op, lo, close) or lo > min(op, hi, close):
            raise ValueError('官方 OHLC 欄位不一致，拒絕寫入')
        if code in output:
            raise ValueError('官方同日代號重複，拒絕任意選取')
        output[code] = (stamp, op, hi, lo, close, volume)
    return output, unavailable


def run(day=None):
    now = datetime.now(ss._TZ['TW'])
    day = day or now.date().isoformat()
    if day != now.date().isoformat() or now.hour < 14:
        raise ValueError('每日更新只在當日收盤後執行，不用現在資料補造過去觀察')
    if session(day)['status'] != 'scheduled':
        return {'status': 'closed', 'reason': session(day)['reason'], 'sessionDate': day}
    data = Path(datastore.DB_PATH).parent
    state_path = data / 'stock_daily_sources.json'
    logfile = data / 'stock_daily_sources.jsonl'
    run_id = uuid.uuid4().hex
    previous = load_json(str(state_path), default={}, expected_type=dict)
    completed = {r['name']: r for r in previous.get('sources', []) if r.get('status') == 'completed'} if previous.get('sessionDate') == day else {}
    names = ['TWSE 日線', 'TPEx 日線', '大盤日線', '上市法人', '上櫃法人']
    state = {'runId': run_id, 'sessionDate': day, 'startedAt': now.isoformat(), 'status': 'running',
             'sources': [{**completed[name], 'reusedFromRun': previous.get('runId')} if name in completed
                         else {'name': name, 'status': 'pending'} for name in names],
             'externalCalls': '官方批次日線及法人、既有 Yahoo 大盤日線'}
    def trace(event, **details):
        state['updatedAt'] = datetime.now(ss._TZ['TW']).isoformat()
        atomic_write_json(str(state_path), state, backup=True)
        with logfile.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at': state['updatedAt'], 'runId': run_id, 'event': event, **details}, ensure_ascii=False) + '\n')
    def step(name, url, action):
        if name in completed:
            trace('沿用當日已完成來源', source=url)
            return
        row = next(r for r in state['sources'] if r['name'] == name)
        row.update(source=url, status='running')
        trace('來源開始', source=url)
        started = time.monotonic()
        try:
            row['result'] = action()
            row['status'] = 'partial' if (row['result'].get('conflicts') or
                                         row['result'].get('unavailableSymbols')) else 'completed'
        except Exception as exc:
            row.update(status='failed', error=type(exc).__name__, reason=str(exc)[:300])
        row['elapsedSec'] = round(time.monotonic() - started, 3)
        trace('來源完成', **row)
    trace('工作開始')
    symbols = {code for code in datastore.list_symbols('TW', 1) if _TICKER_RE['TW'].fullmatch(code)}
    for exchange, url in SOURCES.items():
        url = url.format(day=day.replace('-', ''))
        def fetch_quotes(exchange=exchange, url=url):
            # 官方批次檔約 5 MB；裸 urlopen 一次連線被重設就整個來源失敗。沿用既有 http_client 的
            # 連線池、暫態重試（ConnectionReset／IncompleteRead／逾時）與 gzip，減少傳輸量與失敗機率。
            payload = http_client.fetch_json(
                url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Accept-Encoding': 'gzip'},
                timeout=30, retries=2)
            rows, absent = (parse_twse_market(payload, day, symbols) if exchange == 'TWSE'
                            else parse_quotes(payload, exchange, day, symbols))
            if not rows:
                raise ValueError('來源沒有目前觀察集合的有效成交資料')
            totals = {'inserted': 0, 'unchanged': 0, 'conflicts': 0, 'excluded': 0}
            for code, row in rows.items():
                result = datastore.merge_source_bars(code, 'TW', [row], url)
                for k in totals:
                    totals[k] += result[k]
            return {**totals, 'sourceDate': day, 'symbols': len(rows), 'unavailableSymbols': absent,
                    'receivedSymbols': sorted(rows), 'volumeUnit': '股'}
        step(exchange + ' 日線', url, fetch_quotes)
    # 本機只有 TW 市場，不能猜測交易所；以兩來源聯集查覆蓋，缺漏時兩邊均待確認。
    quote_sources = state['sources'][:2]
    received = {code for row in quote_sources for code in (row.get('result') or {}).get('receivedSymbols', [])}
    unavailable = {code for row in quote_sources for code in (row.get('result') or {}).get('unavailableSymbols', [])}
    missing = sorted(code for code in symbols - received - unavailable if eligible_bar(code, day))
    state['unconfirmedSymbols'] = missing
    if missing:
        for row in quote_sources:
            if row['status'] == 'completed':
                row['status'] = 'partial'
            row.setdefault('result', {})['unconfirmedSymbols'] = missing
        trace('日線覆蓋未齊', symbols=missing)
    def benchmark():
        count = datastore.update('^TWII')
        latest = datastore.last_ts('^TWII')
        if not latest or ss.bar_date(latest) != day:
            raise ValueError('大盤當日日線尚未到齊')
        return {'rows': count, 'sourceDate': day}
    step('大盤日線', 'Yahoo Finance/^TWII', benchmark)
    def twse_chips():
        n = chips.parse_and_save(day.replace('-', ''), directory=str(data / 'chip_history'))
        if not n:
            raise ValueError('上市法人當日資料尚未到齊')
        return {'rows': n, 'sourceDate': day}
    def tpex_chips():
        n = chips.parse_and_save_tpex(day.replace('-', ''), directory=str(data / 'chip_history'))
        if not n:
            raise ValueError('上櫃法人當日資料尚未到齊')
        return {'rows': n, 'sourceDate': day}
    step('上市法人', 'TWSE/T86', twse_chips)
    step('上櫃法人', 'TPEx/3insti', tpex_chips)
    state['status'] = 'partial' if any(s['status'] != 'completed' for s in state['sources']) else 'completed'
    trace('工作結束', status=state['status'])
    return state
