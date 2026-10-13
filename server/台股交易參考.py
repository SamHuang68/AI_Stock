"""已核對的公開交易參考；純本機讀取，不推論未收錄股票仍在交易。"""
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def references():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def session(day):
    day = date.fromisoformat(day) if isinstance(day, str) else day
    calendar = references()['calendar']
    holiday = calendar['closed'].get(day.isoformat())
    if holiday:
        source = calendar.get('closedSources', {}).get(day.isoformat(), calendar['source'])
        return {'status': 'closed', 'reason': '官方公告休市：' + holiday, 'source': source}
    if day.weekday() >= 5:
        return {'status': 'closed', 'reason': '週末休市', 'source': calendar['source']}
    if str(day.year) == calendar['year']:
        return {'status': 'scheduled', 'reason': '表定交易日；仍以當日日線確認是否實際交易', 'source': calendar['source']}
    return {'status': 'unknown', 'reason': '尚無該年度官方日曆，不以平日推定已交易', 'source': None}


def previous_session(day, *, session_lookup=None):
    """前一個已涵蓋的表定交易日；當日或回溯年度未知時停止。"""
    cursor = date.fromisoformat(day) if isinstance(day, str) else day
    lookup = session_lookup or session
    if str(cursor.year) != references()['calendar']['year'] or lookup(cursor)['status'] == 'unknown':
        return None
    while True:
        cursor -= timedelta(days=1)
        state = lookup(cursor)['status']
        if state == 'unknown':
            return None
        if state == 'scheduled':
            return cursor.isoformat()


def instrument(symbol, as_of=None):
    item = references()['instruments'].get(symbol)
    if not item or (as_of and as_of < item['stopDate']):
        return None
    return {'symbol': symbol, **item}


def split_references(symbol):
    return references()['splits'].get(symbol, [])


def trading_status(symbol, day):
    """已知個股停止交易區間；未知主檔不冒稱官方確認可交易。"""
    ended = instrument(symbol, day)
    if ended:
        return ended
    for item in references().get('suspensions', {}).get(symbol, []):
        if item['from'] <= day < item['resumeDate']:
            return {'symbol': symbol, 'status': 'suspended', **item}
    return None


def eligible_bar(symbol, day):
    return session(day)['status'] != 'closed' and trading_status(symbol, day) is None


def continuous_segments(symbol, bars, sessions):
    """以基準交易日切段；缺日、停牌、終止後價格都不能壓縮成相鄰 K 棒。"""
    from stock_signals import complete_bar
    positions = {day: i for i, day in enumerate(sessions)}
    part, result = [], []
    for bar in bars:
        day = bar['date']
        # 來源可能在全市場休市日留存平價零量列；略過該列，不中斷真實交易日。
        if session(day)['status'] == 'closed':
            continue
        valid = day in positions and eligible_bar(symbol, day) and complete_bar(bar)
        adjacent = not part or positions.get(day) == positions[part[-1]['date']] + 1
        if part and adjacent:
            between = date.fromisoformat(part[-1]['date']) + timedelta(days=1)
            end = date.fromisoformat(day)
            while between < end:
                if session(between)['status'] == 'scheduled':
                    adjacent = False
                    break
                between += timedelta(days=1)
        if not valid or not adjacent:
            if part:
                result.append(part)
            part = []
        if valid:
            part.append(bar)
    if part:
        result.append(part)
    return result


def continuous_frames(symbol, frame, sessions):
    """研究共用的有效連續指標；切段後重新暖機，不沿用缺口前的指標。"""
    import stock_signals as ss
    bars = [{k: frame[k][i] for k in ('date', 'open', 'high', 'low', 'close', 'volume')}
            for i in range(len(frame['date']))]
    parts = continuous_segments(symbol, bars, sessions)
    if len(parts) == 1 and len(parts[0]) == len(bars):
        return [frame]
    chips = [{k: frame[k][i] for k in ('date', 'trust', 'foreign')}
             for i in range(len(frame['date']))]
    return [ss.build_frame(part, chips) for part in parts if len(part) >= ss.MIN_BARS]
