"""以 State Street 官方每日持股辨識美股類股 ETF 成員，行情沿用既有來源。"""

from __future__ import annotations

import io
import math
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from datetime import date
from typing import Any


ETF_NAMES = {
    'XLE': '能源', 'XLF': '金融', 'XLK': '科技', 'XLV': '醫療',
    'XLY': '非必需消費', 'XLP': '必需消費', 'XLI': '工業',
    'XLB': '原物料', 'XLU': '公用事業', 'XLRE': '不動產', 'XLC': '通訊',
}
HOLDINGS_URLS = {
    symbol: 'https://www.ssga.com/library-content/products/fund-data/etfs/us/'
            f'holdings-daily-us-en-{symbol.lower()}.xlsx'
    for symbol in ETF_NAMES
}
_NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
_STOCK_SYMBOL = re.compile(r'[A-Z]{1,5}(?:[.-][A-Z])?\Z')
_MAX_BYTES = 2_000_000
_CACHE_SECONDS = 4 * 3600
_QUOTE_BATCH_SIZE = 12
_QUOTE_BUDGET_SECONDS = 25.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


class HoldingsError(ValueError):
    """持股來源的可診斷錯誤。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _holdings_date(value: str) -> str:
    months = {name: i for i, name in enumerate(
        ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
    match = re.fullmatch(r'As of\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})', value.strip(), re.I)
    if not match:
        raise HoldingsError('holdings_date_missing', '官方持股檔缺少可辨識的持股資料日。')
    try:
        return date(int(match[3]), months[match[2].lower()], int(match[1])).isoformat()
    except (KeyError, ValueError) as exc:
        raise HoldingsError('holdings_date_invalid', '官方持股檔的持股資料日無效。') from exc


def _parse_holdings(payload: bytes, symbol: str) -> dict[str, Any]:
    """只讀 XLSX 儲存格；不擷取檔案、不執行公式或巨集。"""
    if len(payload) > _MAX_BYTES:
        raise HoldingsError('holdings_too_large', '官方持股檔超過允許大小。')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(item.file_size for item in entries) > 8_000_000:
                raise HoldingsError('holdings_too_large', '官方持股檔解壓後超過允許大小。')
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
                strings = [''.join(part.text or '' for part in item.findall('.//s:t', _NS))
                           for item in root.findall('s:si', _NS)]
            root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            rows = []
            for row in root.findall('.//s:row', _NS):
                cells = {}
                for cell in row.findall('s:c', _NS):
                    column = re.sub(r'\d+', '', cell.attrib.get('r', ''))
                    value_node = cell.find('s:v', _NS)
                    value = (value_node.text or '') if value_node is not None else ''.join(
                        part.text or '' for part in cell.findall('.//s:t', _NS))
                    if cell.attrib.get('t') == 's' and value:
                        value = strings[int(value)]
                    cells[column] = value.strip()
                if any(cells.values()):
                    rows.append(cells)
    except HoldingsError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, IndexError, RuntimeError) as exc:
        raise HoldingsError('holdings_format_invalid', '官方持股檔格式無法解析。') from exc

    metadata = {row.get('A'): row.get('B', '') for row in rows}
    if metadata.get('Ticker Symbol:') != symbol:
        raise HoldingsError('holdings_symbol_mismatch', '官方持股檔的 ETF 代號與要求不一致。')
    as_of = _holdings_date(metadata.get('Holdings:', ''))
    required = {'Name', 'Ticker', 'Identifier', 'SEDOL', 'Weight', 'Local Currency'}
    header_index = next((i for i, row in enumerate(rows) if required <= set(row.values())), None)
    if header_index is None:
        raise HoldingsError('holdings_columns_missing', '官方持股檔缺少必要欄位。')
    columns = {value: column for column, value in rows[header_index].items()}
    members = []
    seen = set()
    excluded = 0
    for row in rows[header_index + 1:]:
        ticker = row.get(columns['Ticker'], '')
        if not ticker:
            continue
        name = row.get(columns['Name'], '')
        identifier = row.get(columns['Identifier'], '')
        sedol = row.get(columns['SEDOL'], '')
        weight = _number(row.get(columns['Weight']))
        # 現金／貨幣基金通常沒有股票代號；期貨代號含數字且沒有 SEDOL。
        if (not _STOCK_SYMBOL.fullmatch(ticker)
                or not re.fullmatch(r'[A-Z0-9]{9}', identifier)
                or not re.fullmatch(r'[A-Z0-9]{7}', sedol)
                or not name or weight is None or weight < 0):
            excluded += 1
            continue
        quote_symbol = ticker.replace('.', '-')
        if quote_symbol in seen:
            continue
        seen.add(quote_symbol)
        members.append({'code': quote_symbol, 'name': name, 'weightPct': weight,
                        'currency': row.get(columns['Local Currency'], '')})
    if not members or len(members) > 1000:
        raise HoldingsError('holdings_empty', '官方持股檔沒有可辨識的股票成員。')
    return {'holdingsAsOf': as_of, 'members': members, 'excludedNonStockCount': excluded}


def _download_holdings(symbol: str) -> dict[str, Any]:
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(symbol)
        if cached and now - cached[0] < _CACHE_SECONDS:
            return cached[1]
    request = urllib.request.Request(HOLDINGS_URLS[symbol], headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise HoldingsError('holdings_http_error', f'官方持股來源回傳 HTTP {response.status}。')
            if response.url != HOLDINGS_URLS[symbol]:
                raise HoldingsError('holdings_redirect', '官方持股來源網址已變更，暫停讀取。')
            result = _parse_holdings(response.read(_MAX_BYTES + 1), symbol)
    except HoldingsError:
        raise
    except urllib.error.HTTPError as exc:
        raise HoldingsError('holdings_http_error', f'官方持股來源回傳 HTTP {exc.code}。') from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        raise HoldingsError('holdings_unavailable', '官方每日持股暫時無法取得，請稍後重試。') from exc
    with _cache_lock:
        _cache[symbol] = (time.monotonic(), result)
    return result


def get_members(symbol: str, quote_fetcher: Callable[[list[str]], list[dict[str, Any]]]) -> dict[str, Any]:
    """回傳 ETF 股票持股與有界分批行情；缺少行情時仍保留股票名單。"""
    symbol = str(symbol or '').strip().upper()
    response: dict[str, Any] = {
        'ok': False, 'market': 'US', 'sector': ETF_NAMES.get(symbol, symbol),
        'sectorKey': symbol, 'scope': 'US_SECTOR_ETF_HOLDINGS',
        'scopeLabel': 'SPDR 產業 ETF 股票持股', 'date': None,
        'source': 'State Street 官方每日持股；Yahoo 既有行情',
        'classificationSource': 'State Street 官方每日持股',
        'holdingsSourceUrl': HOLDINGS_URLS.get(symbol),
        'holdingsAsOf': None, 'quoteAsOf': None, 'count': 0, 'rows': [],
        'unavailableReason': None, 'diagnostics': [],
    }
    if symbol not in HOLDINGS_URLS:
        response['unavailableReason'] = '僅支援畫面列出的 11 檔 SPDR 產業 ETF。'
        response['diagnostics'].append({'code': 'unsupported_sector', 'message': response['unavailableReason']})
        return response
    try:
        holdings = _download_holdings(symbol)
    except HoldingsError as exc:
        response['unavailableReason'] = str(exc)
        response['diagnostics'].append({'code': exc.code, 'message': str(exc)})
        return response

    members = holdings['members']
    codes = [row['code'] for row in members]
    quotes: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + _QUOTE_BUDGET_SECONDS
    for start in range(0, len(codes), _QUOTE_BATCH_SIZE):
        if time.monotonic() >= deadline:
            response['diagnostics'].append({'code': 'quote_deadline', 'message': '部分行情逾時，已保留完整股票名單。'})
            break
        batch = codes[start:start + _QUOTE_BATCH_SIZE]
        try:
            result = quote_fetcher(batch)
            for quote_row in result or []:
                if isinstance(quote_row, dict) and quote_row.get('symbol') in batch:
                    quotes[quote_row['symbol']] = quote_row
        except Exception:
            response['diagnostics'].append({'code': 'quote_batch_failed', 'message': '部分行情暫時無法取得，已保留完整股票名單。'})
    rows = []
    times = set()
    quoted_count = 0
    for member in members:
        quote_row = quotes.get(member['code'], {})
        price = _number(quote_row.get('price'))
        price = price if price is not None and price > 0 else None
        previous = _number(quote_row.get('prevClose'))
        change_pct = _number(quote_row.get('changePct')) if price is not None else None
        as_of = quote_row.get('asOf') or None
        if as_of and price is not None:
            times.add(str(as_of))
        if price is not None and change_pct is not None:
            quoted_count += 1
        rows.append({**member, 'price': price,
                     'change': price - previous if price is not None and previous is not None and previous > 0 else None,
                     'changePct': change_pct, 'industry': ETF_NAMES[symbol], 'ex': 'US',
                     'asOf': as_of if price is not None else None,
                     'source': quote_row.get('source') or None,
                     'referenceType': quote_row.get('referenceType') or None})
    if quoted_count < len(rows):
        response['diagnostics'].append({'code': 'quotes_partial', 'message': f'已取得 {quoted_count}／{len(rows)} 檔漲跌；空白數值表示行情尚未取得。'})
    response.update({
        'ok': True, 'date': holdings['holdingsAsOf'], 'holdingsAsOf': holdings['holdingsAsOf'],
        'quoteAsOf': next(iter(times)) if len(times) == 1 else None,
        'quoteAsOfFrom': min(times) if times else None, 'quoteAsOfTo': max(times) if times else None,
        'count': len(rows), 'rows': rows, 'quotedCount': quoted_count,
        'excludedNonStockCount': holdings['excludedNonStockCount'],
    })
    return response
