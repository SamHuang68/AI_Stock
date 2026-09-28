"""已核對的公開交易參考；純本機讀取，不推論未收錄股票仍在交易。"""
import json
from datetime import date
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
        return {'status': 'closed', 'reason': '官方公告休市：' + holiday, 'source': calendar['source']}
    if day.weekday() >= 5:
        return {'status': 'closed', 'reason': '週末休市', 'source': calendar['source']}
    if str(day.year) == calendar['year']:
        return {'status': 'scheduled', 'reason': '表定交易日；仍以當日日線確認是否實際交易', 'source': calendar['source']}
    return {'status': 'unknown', 'reason': '尚無該年度官方日曆，不以平日推定已交易', 'source': None}


def instrument(symbol, as_of=None):
    item = references()['instruments'].get(symbol)
    if not item or (as_of and as_of < item['stopDate']):
        return None
    return {'symbol': symbol, **item}


def split_references(symbol):
    return references()['splits'].get(symbol, [])
