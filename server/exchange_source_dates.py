"""Official exchange dates; never substitute a request/fetch date."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
import math
import re

TAIPEI = timezone(timedelta(hours=8))
CLOCK_SKEW_TOLERANCE = timedelta(seconds=120)

def taipei_today():
    return datetime.now(TAIPEI).date()


def marketflow_cache_key(today):
    return f'marketflow:source-date-v1:{today.strftime("%Y%m%d")}'


def breadth_cache_key(today):
    """廣度快取鍵：寫入端（breadth_build）與讀取端（Pulse）必須共用，改版號只改這一處。"""
    return f'breadth:source-date-v1:{today.strftime("%Y%m%d")}'

def official_date(value):
    text = str(value or '').strip()
    match = re.fullmatch(r'(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', text)
    if match:
        year, month, day = map(int, match.groups())
        if year < 1911:
            year += 1911
    elif re.fullmatch(r'\d{8}', text):
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:])
    elif re.fullmatch(r'\d{7}', text):
        year, month, day = int(text[:3]) + 1911, int(text[3:5]), int(text[5:])
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None

def response_date(payload, requested, today):
    observed = official_date(payload.get('date'))
    return observed if observed == requested and observed <= today else None

# 夜盤 15:00 開盤、隔日 05:00 收盤。TAIFEX MIS 對「跨過午夜之後」的夜盤報價，CDate 仍是
# 場次「開始日」（實測：2026-10-06 01:50 的報價 CDate=20261005），直接 CDate+CTime 會比實際早 24 小時。
NIGHT_POST_MIDNIGHT_END = time(6, 0, 0)


def txf_timestamp_check(day, clock, now=None, session=None):
    """回 (ISO 時間戳 | None, 原因 | None)。原因：missing_date／bad_date／missing_time／bad_time／future。
    把「為什麼驗證失敗」留下來，才能在報價被標成「時間未核實」時看出是來源格式還是日期語意的問題。

    session='night' 且時間在 00:00–05:59 時，CDate 是場次開始日 → 日曆日要 +1。
    此規則推算出的時間若超前本機時鐘（例如 TAIFEX 日後改成直接給日曆日），仍會被 'future' 擋下
    並標成「時間未核實」，不會悄悄算出錯誤時間。"""
    if day is None or str(day).strip() == '':
        return None, 'missing_date'
    observed = official_date(day)
    if observed is None:
        return None, 'bad_date'
    text = str(clock or '').strip()
    if not text:
        return None, 'missing_time'
    if re.fullmatch(r'\d{6}', text):
        text = ':'.join((text[:2], text[2:4], text[4:]))
    if not re.fullmatch(r'\d{2}:\d{2}:\d{2}', text):
        return None, 'bad_time'
    try:
        tick = datetime.strptime(text, '%H:%M:%S').time()
    except ValueError:
        return None, 'bad_time'
    if session == 'night' and tick < NIGHT_POST_MIDNIGHT_END:
        observed += timedelta(days=1)
    stamp = datetime.combine(observed, tick, TAIPEI)
    # 容許本機時鐘比交易所慢一點：TAIFEX 的 CTime 可能就是「這一秒」，零容忍會讓有效報價時有時無。
    # 真正超前（日期錯、格式錯）仍然拒收。
    if stamp > (now or datetime.now(TAIPEI)) + CLOCK_SKEW_TOLERANCE:
        return None, 'future'
    return stamp.isoformat(), None


def txf_timestamp(day, clock, now=None, session=None):
    return txf_timestamp_check(day, clock, now, session)[0]

def _number(value):
    try:
        value = float(str(value).replace(',', ''))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def marketflow_payload(fetch, today):
    # date 一律是「實際觀察到的最新官方資料日」；全部抓不到就是 None，絕不退回請求／抓取日
    # （否則法人缺資料時畫面會把今天當成法人資料日）。
    out = {'date': None, 'turnover': [], 'inst': None, 'margin': None}

    def load_turnover():
        try:
            data = fetch('https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=' + today.strftime('%Y%m01') + '&response=json')
            if data.get('stat') in ('OK', 'ok'):
                fields = data.get('fields') or []
                positions = {name: next((i for i, f in enumerate(fields) if label in f), default) for name, label, default in [('date','日期',0), ('amount','成交金額',1), ('index','指數',None), ('chg','漲跌點數',None)]}
                for row in data.get('data') or []:
                    try:
                        observed = official_date(row[positions['date']])
                        amount = _number(row[positions['amount']])
                        if observed is None or observed > today or observed.replace(day=1) != today.replace(day=1) or amount is None:
                            continue
                        rec = {'date': str(row[positions['date']]).strip(), 'sourceDate': observed.isoformat(), 'amount': amount,
                               'source': 'TWSE FMTQIK'}
                        for name in ('index', 'chg'):
                            i = positions[name]
                            if i is not None and i < len(row):
                                value = _number(row[i])
                                if value is not None:
                                    rec[name] = value
                        out['turnover'].append(rec)
                    except (IndexError, TypeError):
                        continue
        except Exception as e:
            print('[marketflow] FMTQIK failed:', type(e).__name__, e)

    def load_inst():
        inst_error = None
        for back in range(7):
            requested = today - timedelta(days=back)
            try:
                data = fetch('https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=' + requested.strftime('%Y%m%d') + '&type=day&response=json')
                observed = response_date(data, requested, today)
                if data.get('stat') not in ('OK', 'ok') or observed is None:
                    continue
                fields = data.get('fields') or []
                name_i = next((i for i, f in enumerate(fields) if '單位名稱' in f or '買賣別' in f), 0)
                net_i = next((i for i, f in enumerate(fields) if '買賣差' in f or '買賣超' in f), len(fields)-1)
                inst = {'foreign': None, 'trust': None, 'dealer': None, 'date': observed.strftime('%Y%m%d'),
                        'sourceDate': observed.isoformat(), 'source': 'TWSE BFI82U'}
                for row in data.get('data') or []:
                    if not row or max(name_i, net_i) >= len(row):
                        continue
                    name, net = str(row[name_i]), _number(row[net_i])
                    if net is None:
                        continue
                    kind = 'foreign' if '外' in name else 'trust' if '投信' in name else 'dealer' if '自營' in name else None
                    if kind:
                        inst[kind] = (inst[kind] or 0) + net
                if any(inst[k] is not None for k in ('foreign','trust','dealer')):
                    out['inst'] = inst
                    return
            except Exception as e:
                inst_error = e
                continue
        if inst_error is not None:
            print('[marketflow] BFI82U failed:', type(inst_error).__name__, inst_error)

    def load_margin():
        try:
            data = fetch('https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=' + today.strftime('%Y%m%d') + '&selectType=ALL&response=json')
            observed = response_date(data, today, today)
            if data.get('stat') in ('OK', 'ok') and observed is not None:
                tables = data.get('tables') or []
                rows = tables[0].get('data') or [] if tables else []
                if rows:
                    out['margin'] = {'raw': rows[:6], 'date': observed.strftime('%Y%m%d'),
                                     'sourceDate': observed.isoformat(), 'source': 'TWSE MI_MARGN'}
        except Exception as e:
            print('[marketflow] MI_MARGN failed:', type(e).__name__, e)

    # 三組互不相依（各寫 out 的不同欄位）：並行抓，冷快取時總延遲取最慢一組而不是三組相加
    # （基本面與 Pulse 都在請求執行緒上同步等這份資料）。各自已處理例外，不會往外拋。
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in [pool.submit(task) for task in (load_turnover, load_inst, load_margin)]:
            future.result()

    observed_days = [r['sourceDate'] for r in out['turnover']]
    for section in (out['inst'], out['margin']):
        if section:
            observed_days.append(section['sourceDate'])
    out['date'] = max(observed_days) if observed_days else None
    return out
