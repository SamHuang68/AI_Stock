"""已核對的美股核心時段日曆；純本機參考，不下載或推算未涵蓋年度。"""
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    TZ = ZoneInfo('America/New_York')
except ZoneInfoNotFoundError:
    TZ = None  # 缺時區資料不能用固定 UTC-5 冒充全年美東時間。
SETTLE = timedelta(minutes=30)


@lru_cache(maxsize=1)
def references():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def session(day):
    day = date.fromisoformat(day) if isinstance(day, str) else day
    data = references()
    key = day.isoformat()
    metadata = {k: data[k] for k in ('version', 'verifiedAt', 'source', 'coverageStart', 'coverageEnd', 'scope')}
    if TZ is None:
        return {**metadata, 'status': 'unknown', 'reason': '美東時區資料未安裝，交易時段與新鮮度待確認',
                'open': None, 'close': None}
    if not data['coverageStart'] <= key <= data['coverageEnd']:
        return {**metadata, 'status': 'unknown', 'reason': '美股官方日曆未涵蓋此日期，交易時段與新鮮度待確認',
                'open': None, 'close': None}
    if key in data['closed'] or day.weekday() >= 5:
        return {**metadata, 'status': 'closed',
                'reason': '官方公告休市：' + data['closed'][key] if key in data['closed'] else '週末休市',
                'open': None, 'close': None}
    close = data['earlyClose'].get(key, data['close'])
    return {**metadata, 'status': 'scheduled', 'open': data['open'], 'close': close,
            'earlyClose': key in data['earlyClose'],
            'reason': '表定提早收盤 ' + close + '（美東）' if key in data['earlyClose'] else '表定核心交易時段；臨時變更仍以交易所公告為準'}


def final_time(local, calendar):
    if calendar['status'] != 'scheduled':
        return None
    hour, minute = map(int, calendar['close'].split(':'))
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0) + SETTLE


def session_state(last_bar_date, now):
    local = (now.astimezone(TZ) if now.tzinfo else now.replace(tzinfo=TZ)) if TZ is not None else now
    calendar = session(local.date())
    today = local.date().isoformat()
    if calendar['status'] == 'unknown':
        # 未核對時段時，當日來源列不能被當成最終日線寫回。
        return {'provisional': last_bar_date == today, 'expectedLastDate': None,
                'sessionOpen': False, 'calendar': calendar, 'localTime': local.isoformat()}
    open_t = None
    if calendar['status'] == 'scheduled':
        hour, minute = map(int, calendar['open'].split(':'))
        open_t = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    final_t = final_time(local, calendar)
    expected = local.date()
    if open_t is None or local < open_t:
        expected -= timedelta(days=1)
        while session(expected)['status'] == 'closed':
            expected -= timedelta(days=1)
    known = session(expected)['status'] == 'scheduled'
    return {'provisional': bool(open_t and last_bar_date == today and open_t <= local < final_t),
            'expectedLastDate': expected.isoformat() if known else None,
            # 既有欄位包含 30 分鐘收盤確認期，用於是否需要取得最終日線。
            'sessionOpen': bool(open_t and open_t <= local < final_t),
            'calendar': calendar, 'localTime': local.isoformat()}
