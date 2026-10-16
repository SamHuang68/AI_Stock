"""台指期／櫃買具名來源分鐘行情；共用解析與快取，永不寫入日線庫。"""
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
SOURCES = {
    '__TXF__': ('WTX&', 'TFE', URL, '台指期近一分時'),
    '^TWOII': ('^TWOII', 'TWO', 'https://tw.stock.yahoo.com/quote/%5ETWOII', '櫃買指數分時'),
}
_lock = threading.Lock()
_cached = None
_twoii_cached = None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_html(html, *, now=None, symbol='__TXF__'):
    """只接受指定標的具名節點，不從報價推造 K 棒或改動來源時間。"""
    current = time.time() if now is None else now
    source_symbol, exchange, url, name = SOURCES[symbol]
    marker = re.search(r'root\.App\.main\s*=\s*', html)
    if not marker:
        raise ValueError('來源缺少具名圖表資料')
    # JavaScript 物件僅將字串外的 undefined 正規化；絕不 eval 網頁程式。
    blob = re.sub(r'"(?:\\.|[^"\\])*"|\bundefined\b', lambda m: 'null' if m[0] == 'undefined' else m[0], html[marker.end():])
    data, _ = json.JSONDecoder().raw_decode(blob)
    try:
        chart = data['context']['dispatcher']['stores']['MarketChartStore']['libra'][source_symbol]
        meta = chart['meta']
        stamps = chart['timestamp']
        quotes = chart['indicators']['quote'][0]
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('來源指定標的分鐘圖表結構不足') from exc
    if (meta.get('symbol') != source_symbol or meta.get('exchange') != exchange
            or meta.get('exchangeTimezoneName') != 'Asia/Taipei'
            or meta.get('dataGranularity') != '1m' or meta.get('range') != '1d'):
        raise ValueError('來源標的、交易所、時區或分鐘粒度不符')
    as_of = meta.get('regularMarketTime')
    if not _number(as_of) or not 0 < as_of <= current + 120:
        raise ValueError('來源時間戳缺失或超前目前時間')
    intervals = []
    periods = meta.get('sourceTradingPeriods')
    # 櫃買來源只有 tradingPeriods；台指期必須使用分開列出的夜盤與日盤。
    if symbol == '^TWOII' and periods is None:
        periods = meta.get('tradingPeriods')
    for group in periods or []:
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
        # 來源以收盤分鐘標記最後撮合（台指期 05:00／13:45、櫃買 13:30）。
        session = next((j for j,p in enumerate(intervals) if p['start'] <= stamp <= p['end']), None)
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
    return {'ok': True,'version': VERSION,'symbol': symbol,'sourceSymbol':source_symbol,
            'name':name,'source':url,'asOf':datetime.fromtimestamp(as_of,timezone.utc).isoformat(),
            'sourceTimestamp':as_of,'exchangeTimezone':'Asia/Taipei','interval':'1m',
            'previousClose':previous_close,'sessions':intervals,'candles':candles,
            'missing': {'invalidPriceBars':missing,'unknownVolumeBars':sum(b['volume'] is None for b in candles)},
            'limitations':(['來源近一連續行情，非指定到期月份合約'] if symbol == '__TXF__' else []) +
                           ['分鐘行情不寫入日線或供回測使用',
                            '來源未提供價格或成交量時不補造；休盤與缺分鐘不連線','來源時間不等於即時保證']}


def _fetch(symbol='__TXF__'):
    with urlopen(Request(SOURCES[symbol][2],headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'}),timeout=15) as response:
        raw = response.read(2_000_001)
    if len(raw)>2_000_000:
        raise ValueError('來源頁面超出大小上限')
    return raw.decode('utf-8')


def get(*, fetch=None, now=None, symbol='__TXF__'):
    global _cached, _twoii_cached
    source_symbol, exchange, url, name = SOURCES[symbol]
    current = time.time() if now is None else now
    with _lock:
        cached = _cached if symbol == '__TXF__' else _twoii_cached
        if cached and 0 <= current-cached[0] < 60:
            result = copy.deepcopy(cached[1])
            result['cached'] = True
        else:
            try:
                result = parse_html(fetch() if fetch else _fetch(symbol),now=current,symbol=symbol)
                result.update(fetchedAt=datetime.fromtimestamp(current,timezone.utc).isoformat(),cached=False)
            except Exception as exc:
                result = {'ok':False,'version':VERSION,'source':url,'symbol':symbol,'candles':[],
                          'missing':['verified_minute_bars'],'error':str(exc)[:200],
                          'message':name+'來源目前無法核實；請稍後重新選取「1天」'}
            if symbol == '__TXF__':
                _cached = (current,copy.deepcopy(result))
            else:
                _twoii_cached = (current,copy.deepcopy(result))
    if result.get('ok'):
        age = max(0,int(current-result['sourceTimestamp']))
        result['freshness'] = {'ageSeconds':age,'stale':age>900,'policy':'來源時間距今超過15分鐘標示較舊；不推定市場正在交易'}
    return result


def chart_json(symbol, *, result=None):
    """將已驗證分鐘轉接既有 /yf 契約；錯誤明確回空，不另抓日線。"""
    result = get(symbol=symbol) if result is None else result
    if not result.get('ok'):
        return json.dumps({'chart': {'result': None, 'error': result}}, ensure_ascii=False).encode()
    rows = result['candles']
    meta = {
        'symbol': symbol, 'longName': result['name'], 'currency': 'TWD',
        'exchangeTimezoneName': 'Asia/Taipei', 'gmtoffset': 28800,
        'dataGranularity': '1m', 'range': '1d', '_verifiedIntraday': True,
        'regularMarketTime': result['sourceTimestamp'], 'regularMarketPrice': rows[-1]['close'],
        'chartPreviousClose': result['previousClose'], 'previousClose': result['previousClose'],
        '_source': result['source'], '_intraday': result,
        'sourceTradingPeriods': [result['sessions']],
    }
    chart = {'meta': meta, 'timestamp': [r['time'] for r in rows],
             'indicators': {'quote': [{key: [r[key] for r in rows] for key in ('open','high','low','close','volume')}]}}
    return json.dumps({'chart': {'result': [chart], 'error': None}}, ensure_ascii=False).encode()
