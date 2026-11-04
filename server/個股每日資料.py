"""既有行情庫的官方盤後批次更新；不以個別頁面是否開啟決定研究覆蓋。"""
import json
import sqlite3
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import datastore
import http_client
import stock_signals as ss
import chip_history_tracker as chips
from atomic_store import atomic_write_json, load_json
from log_once import log_once
from sector_flow import normalize_session_date
from 台股交易參考 import session, eligible_bar
from signal_stats_pool import _TICKER_RE

SOURCES = {
    'TWSE': 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={day}&type=ALL&response=json',
    'TPEx': 'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes',
}
# 官方明示當日停止交易的清單：TWSE 暫停交易證券（含暫停與恢復日）、TPEx 變更交易／停止交易資訊。
# 只在有「不在官方當日檔」的候選缺口時才查，健康的日子不多發任何請求。
SUSPENSION_SOURCES = {
    'TWSE': 'https://openapi.twse.com.tw/v1/exchangeReport/TWTAWU',
    'TPEx': 'https://www.tpex.org.tw/openapi/v1/tpex_cmode',
}
# 不在官方當日檔、官方也沒有明示停止交易，且距最後一次真實成交已滿這麼多個交易日：推論為已終止或到期，
# 不再讓兩列日線永遠停在 partial。這是推論，不是官方終止證明；名單與最後成交日完整留在 state['inactiveSymbols']，
# 每次執行重新計算，恢復成交的代號會自動回到官方檔而不再被推論。
INACTIVE_AFTER_SESSIONS = 10
_OFFICIAL_JSON_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Accept-Encoding': 'gzip'}


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


def parse_suspensions(payload, exchange, expected_day):
    """官方明示 expected_day 停止交易的代號。日期不是當日或格式不認得，整份拒絕，不猜。"""
    if not isinstance(payload, list):
        raise ValueError('官方停止交易清單格式不符')
    key = expected_day.replace('-', '')
    halted = set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError('官方停止交易清單資料列不完整')
        if exchange == 'TPEx':
            if normalize_session_date(row.get('Date')) != key:
                raise ValueError('櫃買停止交易清單日期不是當日，拒絕採用')
            code, stopped = row.get('SecuritiesCompanyCode'), bool(str(row.get('SuspensionOfTrading') or '').strip())
        else:
            begin = normalize_session_date(row.get('TradingHaltDate'))
            if begin is None:
                raise ValueError('證交所暫停交易清單缺少暫停日期，拒絕採用')
            # 恢復日當天已可交易（與 台股交易參考.json 的 resumeDate 同義）；沒有恢復日表示尚未恢復。
            resume = normalize_session_date(row.get('TradingResumptionDate'))
            code, stopped = row.get('Code'), begin <= key and (resume is None or key < resume)
        code = str(code or '').strip()
        if code and stopped:
            halted.add(code)
    return halted


def official_suspensions(day):
    """回傳（官方明示當日停止交易的代號, 各來源狀態）。單一來源讀不到只標記失敗，不放寬缺口判定。"""
    halted, lists = set(), {}
    for exchange, url in SUSPENSION_SOURCES.items():
        try:
            codes = parse_suspensions(
                http_client.fetch_json(url, headers=_OFFICIAL_JSON_HEADERS, timeout=30, retries=2), exchange, day)
        except (http_client.HttpError, OSError, ValueError, TypeError) as exc:
            lists[exchange] = {'status': 'failed', 'source': url, 'error': type(exc).__name__, 'reason': str(exc)[:200]}
            continue
        halted |= codes
        lists[exchange] = {'status': 'ok', 'source': url, 'halted': len(codes)}
    return halted, lists


def sessions_since(last_day, day):
    """last_day 之後（不含）到 day（含）之間的表定交易日數；休市日與日曆未涵蓋的日子不計。"""
    cursor, end, count = date.fromisoformat(last_day), date.fromisoformat(day), 0
    while cursor < end:
        cursor += timedelta(days=1)
        if session(cursor)['status'] == 'scheduled':
            count += 1
    return count


def inactive_gaps(codes, day):
    """codes 之中距最後一次真實成交已滿 INACTIVE_AFTER_SESSIONS 個交易日者。

    沒有任何有成交量的紀錄、或資料庫讀不到，就沒有證據，維持缺口，不推論。"""
    found = []
    try:
        with datastore.read_snapshot() as conn:
            for code in codes:
                latest = datastore.last_traded_ts(code, connection=conn)
                last_day = ss.bar_date(latest) if latest else None
                if not last_day:
                    continue
                gap = sessions_since(last_day, day)
                if gap >= INACTIVE_AFTER_SESSIONS:
                    found.append({'symbol': code, 'lastTradeDate': last_day, 'sessionsSince': gap})
    except (OSError, sqlite3.Error) as exc:
        log_once('daily-sources-last-trade', '無法讀取最後成交日，缺口不推論：', exc=exc)
        return []
    return found


def run(day=None, *, adjustment_budget_seconds=120):
    now = datetime.now(ss._TZ['TW'])
    day = day or now.date().isoformat()
    if day != now.date().isoformat() or now.hour < 14:
        raise ValueError('每日更新只在當日收盤後執行，不用現在資料補造過去觀察')
    trading_day = session(day)
    if trading_day['status'] == 'unknown':
        raise ValueError(trading_day['reason'])
    if trading_day['status'] == 'closed':
        return {'status': 'closed', 'reason': trading_day['reason'], 'sessionDate': day}
    data = Path(datastore.DB_PATH).parent
    state_path = data / 'stock_daily_sources.json'
    logfile = data / 'stock_daily_sources.jsonl'
    run_id = uuid.uuid4().hex
    previous = load_json(str(state_path), default={}, expected_type=dict)
    completed = {r['name']: r for r in previous.get('sources', []) if r.get('status') == 'completed'} if previous.get('sessionDate') == day else {}
    # 快照依賴必須依現在的日線重新核對，不能沿用「先前已完成」掩蓋新增行情。
    completed.pop('還原快照', None)
    completed.pop('官方研究續補', None)
    names = ['TWSE 日線', 'TPEx 日線', '大盤日線', '上市法人', '上櫃法人', '官方研究續補', '還原快照']
    state = {'runId': run_id, 'sessionDate': day, 'startedAt': now.isoformat(), 'status': 'running',
             'sources': [{**completed[name], 'reusedFromRun': previous.get('runId')} if name in completed
                         else {'name': name, 'status': 'pending'} for name in names],
             'externalCalls': '官方批次日線及法人、既有官方研究最近月份、Yahoo 大盤日線與單一還原快照'}
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
            # 官方當日檔列出、但開高低收為「--」的代號（無成交，unavailableSymbols）是官方的完整回答，
            # 只留在結果與 state['noPriceSymbols'] 供查閱，不降級；來源回報 partial、有衝突，或代號不在官方檔內
            # 且說不出原因（unconfirmedSymbols，分類見 run() 的缺口段）才是真正的缺口，維持 partial。
            row['status'] = 'partial' if (row['result'].get('status') == 'partial' or row['result'].get('conflicts')) else 'completed'
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
            payload = http_client.fetch_json(url, headers=_OFFICIAL_JSON_HEADERS, timeout=30, retries=2)
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
    # 不在官方當日檔、也不是官方列出無成交的代號，依序分三類（只有第三類是缺口，讓兩列維持 partial）：
    #   suspendedSymbols：官方清單明示當日停止交易，資訊用，恢復交易後自然回到官方檔。
    #   inactiveSymbols：官方沒說，但已久未真實成交（推論，見 INACTIVE_AFTER_SESSIONS），資訊用，附最後成交日。
    #   unconfirmedSymbols：其餘，沒有任何理由說明為何不在官方檔。
    # 清單讀不到、讀不到最後成交日時一律不放寬，原本的缺口照舊維持 partial。
    candidates = sorted(code for code in symbols - received - unavailable if eligible_bar(code, day))
    suspended, inactive, missing = [], [], candidates
    if candidates:
        halted, state['suspensionLists'] = official_suspensions(day)
        suspended = [code for code in candidates if code in halted]
        undecided = [code for code in candidates if code not in halted]
        inactive = inactive_gaps(undecided, day)
        retired = {item['symbol'] for item in inactive}
        missing = [code for code in undecided if code not in retired]
    state['unconfirmedSymbols'] = missing
    state['noPriceSymbols'] = sorted(unavailable)
    state['suspendedSymbols'] = suspended
    state['inactiveSymbols'] = inactive
    if suspended:
        trace('官方明示停止交易，不計入缺口', symbols=suspended)
    if inactive:
        trace('久未成交且不在官方檔，不計入缺口（推論）', symbols=inactive)
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
    def official_research():
        from 官方研究續補 import refresh
        prior = next((s.get('result') or {} for s in previous.get('sources', []) if s.get('name') == '官方研究續補'), {})
        return refresh(Path(datastore.DB_PATH), day, now=now,
                       previous_attempts=prior.get('attemptedAt'), previous_pending=prior.get('pendingSymbols'))
    step('官方研究續補', 'TWSE/STOCK_DAY/既有公司行動', official_research)
    def adjustments():
        from deadline import Deadline
        from 個股還原研究 import refresh_snapshots
        prior = next((s.get('result') or {} for s in previous.get('sources', []) if s.get('name') == '還原快照'), {})
        return refresh_snapshots(symbols, expected_day=day, deadline=Deadline(adjustment_budget_seconds),
                                 previous_attempts=prior.get('attemptedAt'), previous_results=prior.get('results'), workers=4)
    step('還原快照', 'Yahoo Finance/quote/adjclose', adjustments)
    state['status'] = 'partial' if any(s['status'] != 'completed' for s in state['sources']) else 'completed'
    trace('工作結束', status=state['status'])
    return state
