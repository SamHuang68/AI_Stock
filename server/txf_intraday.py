"""台指期近一來源分鐘行情；純解析與有界取得分離，永不寫入日線庫。"""
import copy
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

URL = 'https://tw.stock.yahoo.com/quote/WTX%26'
VERSION = 'txf-minute/1'
_lock = threading.Lock()
_cached = None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_html(html, *, now=None):
    """只接受具名 WTX& 節點，不從全頁第一個 timestamp 或報價推造 K 棒。"""
    current = time.time() if now is None else now
    marker = re.search(r'root\.App\.main\s*=\s*', html)
    if not marker:
        raise ValueError('來源缺少具名圖表資料')
    # JavaScript 物件僅將字串外的 undefined 正規化；絕不 eval 網頁程式。
    blob = re.sub(r'"(?:\\.|[^"\\])*"|\bundefined\b', lambda m: 'null' if m[0] == 'undefined' else m[0], html[marker.end():])
    data, _ = json.JSONDecoder().raw_decode(blob)
    try:
        chart = data['context']['dispatcher']['stores']['MarketChartStore']['libra']['WTX&']
        meta = chart['meta']
        stamps = chart['timestamp']
        quotes = chart['indicators']['quote'][0]
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('來源 WTX& 分鐘圖表結構不足') from exc
    if (meta.get('symbol') != 'WTX&' or meta.get('exchange') != 'TFE'
            or meta.get('exchangeTimezoneName') != 'Asia/Taipei'
            or meta.get('dataGranularity') != '1m' or meta.get('range') != '1d'):
        raise ValueError('來源標的、交易所、時區或分鐘粒度不符')
    as_of = meta.get('regularMarketTime')
    if not _number(as_of) or not 0 < as_of <= current + 120:
        raise ValueError('來源時間戳缺失或超前目前時間')
    intervals = []
    for group in meta.get('sourceTradingPeriods') or []:
        for item in group:
            start, end = item.get('start'), item.get('end')
            if item.get('timezone') != 'Asia/Taipei' or not all(_number(v) for v in (start,end)) or not 0 < end-start <= 24*3600:
                raise ValueError('來源盤別起訖不完整')
            intervals.append({'start': start, 'end': end, 'timezone': 'Asia/Taipei'})
    intervals.sort(key=lambda r:r['start'])
    if not intervals or any(a['end'] > b['start'] for a,b in zip(intervals,intervals[1:])):
        raise ValueError('來源盤別缺失或重疊')
    if not isinstance(stamps,list) or not 1 <= len(stamps) <= 2000:
        raise ValueError('分鐘筆數超出限制')
    keys = ('open','high','low','close','volume')
    if any(not isinstance(quotes.get(k),list) or len(quotes[k]) != len(stamps) for k in keys):
        raise ValueError('分鐘 OHLCV 長度不一致')
    candles, missing, previous = [], 0, None
    for i, stamp in enumerate(stamps):
        if not _number(stamp) or stamp != int(stamp) or stamp % 60 or (previous is not None and stamp <= previous):
            raise ValueError('分鐘時間戳無效、重複或倒序')
        previous = stamp
        values = [quotes[k][i] for k in keys]
        if stamp > as_of or all(v is None for v in values):
            continue
        session = next((j for j,p in enumerate(intervals) if p['start'] <= stamp < p['end']), None)
        if session is None:
            raise ValueError('分鐘資料超出來源明示盤別')
        o,h,lo,c,v = values
        if not all(_number(x) and x > 0 for x in (o,h,lo,c)) or not lo <= min(o,c) <= max(o,c) <= h:
            missing += 1
            continue
        if v is not None and (not _number(v) or v < 0):
            raise ValueError('分鐘成交量無效')
        candles.append(dict(time=int(stamp),open=o,high=h,low=lo,close=c,volume=v,session=session))
    if not candles:
        raise ValueError('來源未提供可驗證的分鐘 K 棒')
    previous_close = meta.get('chartPreviousClose')
    if not _number(previous_close) or previous_close <= 0:
        previous_close = None
    return {'ok': True,'version': VERSION,'symbol': '__TXF__','sourceSymbol':'WTX&',
            'name':'台指期近一分時','source':URL,'asOf':datetime.fromtimestamp(as_of,timezone.utc).isoformat(),
            'sourceTimestamp':as_of,'exchangeTimezone':'Asia/Taipei','interval':'1m',
            'previousClose':previous_close,'sessions':intervals,'candles':candles,
            'missing': {'invalidPriceBars':missing,'unknownVolumeBars':sum(b['volume'] is None for b in candles)},
            'limitations':['來源近一連續行情，非指定到期月份合約','分時行情獨立顯示，不寫入日線或供回測使用',
                            '來源未提供價格或成交量時不補造；休盤與缺分鐘不連線','來源時間不等於即時保證']}


def _fetch():
    with urlopen(Request(URL,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'}),timeout=15) as response:
        raw = response.read(2_000_001)
    if len(raw)>2_000_000:
        raise ValueError('來源頁面超出大小上限')
    return raw.decode('utf-8')


def get(*, fetch=None, now=None):
    global _cached
    current = time.time() if now is None else now
    with _lock:
        if _cached and 0 <= current-_cached[0] < 60:
            result = copy.deepcopy(_cached[1])
            result['cached'] = True
        else:
            try:
                result = parse_html((fetch or _fetch)(),now=current)
                result.update(fetchedAt=datetime.fromtimestamp(current,timezone.utc).isoformat(),cached=False)
            except Exception as exc:
                result = {'ok':False,'version':VERSION,'source':URL,'symbol':'__TXF__','candles':[],
                          'missing':['verified_minute_bars'],'error':str(exc)[:200],
                          'message':'台指期分鐘來源目前無法核實；未以日線、即時報價或夜盤覆寫替代'}
            _cached = (current,copy.deepcopy(result))
    if result.get('ok'):
        age = max(0,int(current-result['sourceTimestamp']))
        result['freshness'] = {'ageSeconds':age,'stale':age>900,'policy':'來源時間距今超過15分鐘標示較舊；不推定市場正在交易'}
    return result
