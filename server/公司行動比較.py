"""核對官方參考價並建立逐日比較基準；不改原始行情或持有損益。"""
from __future__ import annotations

import copy
import math
import re
from bisect import bisect_left
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

PARSER_VERSION = 'twse-reference-ratio-v1'
PRICE_BASIS = 'twse-reference-comparison'
ROUTES = ('TWT49U', 'TWTAUU', 'TWTB8U', 'TWTCAU')


def json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    return value


def decimal_price(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _official_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme == 'https' and bool(parsed.hostname) and (parsed.hostname == 'twse.com.tw' or parsed.hostname.endswith('.twse.com.tw'))
    except ValueError:
        return False


class Comparison:
    def __init__(self, rows: list[dict], adjustments: dict, action_days: set[str]):
        self.rows = rows
        self.dates = [row['date'] for row in rows]
        self.coverage = copy.deepcopy(adjustments.get('coverage'))
        self.symbol = adjustments.get('symbol')
        self.events: dict[str, list[dict]] = {}
        self.errors: dict[str, str] = {}
        self.factors: dict[str, Decimal] = {}
        self.global_reason = None
        if not isinstance(self.symbol, str) or not self.symbol:
            self.global_reason = '官方比較因子缺少標的身分'
        self.receipts = []
        sources = self.coverage.get('sources') if isinstance(self.coverage, dict) else None
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            try:
                valid_time = datetime.fromisoformat(source['retrievedAt']).tzinfo is not None
                begin, finish = date.fromisoformat(source['start']), date.fromisoformat(source['end'])
            except (KeyError, TypeError, ValueError):
                continue
            route = str(source.get('route', '')).rsplit('/', 1)[-1]
            url, digest = source.get('url'), source.get('sourceHash')
            if (not valid_time or begin > finish or not _official_url(url)
                    or not urlparse(url).path.rstrip('/').endswith('/' + route)
                    or not re.fullmatch(r'[0-9a-fA-F]{64}', str(digest or ''))
                    or source.get('stat') not in ('OK', '很抱歉，沒有符合條件的資料!')):
                continue
            self.receipts.append((route, begin, finish, url, digest))
        events = adjustments.get('events', [])
        if not isinstance(events, list):
            events = []
            self.global_reason = '公司行動因子清單格式無效'
        for event in events:
            try:
                event_day = date.fromisoformat(event['date']).isoformat()
            except (TypeError, KeyError, ValueError):
                self.global_reason = '公司行動因子日期無效'
                continue
            self.events.setdefault(event_day, []).append(copy.deepcopy(event))
        self.action_days = sorted(set(action_days) | set(self.events))
        for day, items in self.events.items():
            if len(items) != 1:
                self.errors[day] = '同日多個公司行動因子，無法確認單一比較基準'
                continue
            reason, factor = self._validate(day, items[0])
            if reason:
                self.errors[day] = reason
            else:
                self.factors[day] = factor

    def _validate(self, day: str, event: dict) -> tuple[str | None, Decimal | None]:
        if event.get('status') != 'supported':
            return event['reason'] if isinstance(event.get('reason'), str) and event['reason'] else '公司行動種類或因子尚未支援', None
        if event.get('version') != PARSER_VERSION or not _official_url(event.get('sourceUrl')):
            return '公司行動來源或解析版本尚未核對', None
        if not re.fullmatch(r'[0-9a-fA-F]{64}', str(event.get('sourceHash', ''))):
            return '公司行動缺少官方回應摘要', None
        try:
            retrieved = datetime.fromisoformat(event['retrievedAt'])
            if retrieved.tzinfo is None:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return '公司行動擷取時間尚未核對', None
        payload = event.get('payload')
        if not isinstance(payload, dict) or not isinstance(payload.get('fields'), list) or not isinstance(payload.get('row'), list):
            return '公司行動原始欄位證據缺漏', None
        fields, values = payload['fields'], payload['row']
        if not all(isinstance(field, str) for field in fields) or len(fields) != len(values) or len(set(fields)) != len(fields):
            return '公司行動原始欄位證據無效', None
        raw = dict(zip(fields, values))
        kind = event.get('kind')
        if kind == '除權息' and str(raw.get('權/息', '')).strip() == '息':
            before_key, after_key, day_key, route, symbol_key = '除權息前收盤價', '除權息參考價', '資料日期', 'TWT49U', '股票代號'
        elif kind == 'ETF分割' and str(raw.get('分割(反分割)', '')).strip() in ('分割', '反分割'):
            before_key, after_key, day_key, route, symbol_key = '停止買賣前收盤價格', '恢復買賣參考價', '恢復買賣日期', 'TWTCAU', 'ETF代號'
        else:
            return '僅支援原始欄位已核對的純除息與 ETF 分割', None
        if str(raw.get(symbol_key, '')).strip() != self.symbol:
            return '公司行動原始標的與研究標的不一致', None
        if not urlparse(event['sourceUrl']).path.rstrip('/').endswith('/' + route):
            return '公司行動來源路由與原始種類不符', None
        parts = re.findall(r'\d+', str(raw.get(day_key, '')))
        try:
            year, month, day_number = map(int, parts)
            effective = date(year + (1911 if year < 1911 else 0), month, day_number).isoformat()
        except (ValueError, TypeError):
            return '公司行動原始生效日期無法核對', None
        if effective != day:
            return '公司行動原始生效日期不一致', None
        event_date = date.fromisoformat(day)
        if not any(item[0] == route and item[1] <= event_date <= item[2] and item[3] == event['sourceUrl']
                   and item[4] == event['sourceHash'] for item in self.receipts):
            return '公司行動回應摘要或網址與涵蓋收據不一致', None
        request = payload.get('request')
        try:
            request_start, request_end = date.fromisoformat(request['start']), date.fromisoformat(request['end'])
        except (TypeError, KeyError, ValueError):
            return '公司行動查詢日期證據無效', None
        if not request_start <= event_date <= request_end:
            return '公司行動缺少涵蓋生效日的查詢證據', None
        before, after, supplied = (decimal_price(event.get(key)) for key in ('before', 'after', 'factor'))
        if before is None or after is None or supplied is None:
            return '公司行動前收、參考價或因子無效', None
        if before != decimal_price(raw.get(before_key)) or after != decimal_price(raw.get(after_key)):
            return '公司行動因子與官方原始參考價不一致', None
        factor = after / before
        if abs(supplied - factor) > abs(factor) * Decimal('1e-12'):
            return '公司行動因子不等於官方參考價比值', None
        at = bisect_left(self.dates, day)
        previous = next((row for row in reversed(self.rows[:at])
                         if row.get('source') in ('TWSE', 'TPEX') and row.get('priceBasis', row.get('price_basis')) == 'unadjusted'
                         and not row.get('issues', ['資料品質未核對']) and decimal_price(row.get('close')) is not None), None)
        if previous is None or decimal_price(previous['close']) != before:
            return '官方事件前收與本機最近有效官方原始收盤不一致', None
        if at >= len(self.rows) or self.dates[at] != day:
            return '公司行動生效日缺少市場交易日資料', None
        current_close = decimal_price(self.rows[at].get('close'))
        if current_close is not None and abs(current_close / after - 1) > Decimal('.15'):
            return '官方因子仍無法解釋調整後重大價格斷點', None
        return None, factor

    def reason(self, first: int, last: int) -> str | None:
        if self.global_reason:
            return self.global_reason
        start, end = self.dates[first], self.dates[last]
        coverage = self.coverage
        if not isinstance(coverage, dict) or coverage.get('version') != PARSER_VERSION:
            return '官方比較因子涵蓋或解析版本尚未核對'
        try:
            coverage_start, coverage_end = date.fromisoformat(coverage['start']), date.fromisoformat(coverage['end'])
        except (TypeError, KeyError, ValueError):
            return '官方比較因子涵蓋日期無效'
        if not coverage_start <= date.fromisoformat(start) <= date.fromisoformat(end) <= coverage_end:
            return '官方比較因子涵蓋區間尚未完整核對'
        sources = coverage.get('sources')
        if not isinstance(sources, list) or not sources or any(not isinstance(source, dict) for source in sources):
            return '官方比較因子涵蓋來源尚未核對'
        begin, end_day = date.fromisoformat(start), date.fromisoformat(end)
        for required in ROUTES:
            through = begin - timedelta(days=1)
            for _, lo, hi, _, _ in sorted((r for r in self.receipts if r[0] == required), key=lambda r: r[1]):
                if hi < begin or lo > end_day:
                    continue
                if lo > through + timedelta(days=1):
                    break
                through = max(through, hi)
            if through < end_day:
                return '官方比較因子缺少完整四類事件的涵蓋證據'
        for day in self.action_days:
            if start < day <= end:
                if day in self.errors:
                    return self.errors[day]
                if day not in self.factors:
                    return '公司行動或重大斷點缺少相符的官方比較因子'
        return None

    def prices(self, first: int, anchor: int) -> list[dict]:
        result = []
        end = self.dates[anchor]
        for row in self.rows[first:anchor]:
            factor = Decimal(1)
            for day, multiplier in self.factors.items():
                if row['date'] < day <= end:
                    factor *= multiplier
            result.append({key: Decimal(str(row[key])) * factor for key in ('open', 'high', 'low', 'close')})
        return result

    def evidence(self, first: int, last: int) -> dict:
        start, end = self.dates[first], self.dates[last]
        coverage = self.coverage
        clipped = None
        if isinstance(coverage, dict):
            lo, hi = max(str(coverage.get('start', '')), start), min(str(coverage.get('end', '')), end)
            if lo <= hi:
                clipped = {'start': lo, 'end': hi, 'version': coverage.get('version')}
        relevant = []
        for day in sorted(self.events):
            if start < day <= end:
                for event in self.events[day]:
                    relevant.append({**copy.deepcopy(event), 'verified': day in self.factors,
                                     'verificationReason': self.errors.get(day)})
        return json_safe({'anchorDate': end, 'windowStart': start, 'coverage': clipped, 'events': relevant})

    def digest_evidence(self, first: int, last: int) -> dict:
        evidence = self.evidence(first, last)
        # 同一經濟因子單純重抓，不得把新的擷取時刻當作價格資料修訂。
        fields = ('date', 'kind', 'before', 'after', 'factor', 'status', 'version', 'verified', 'verificationReason')
        evidence['events'] = [{key: event.get(key) for key in fields} for event in evidence['events']]
        evidence.update(symbol=self.symbol, coverageReason=self.reason(first, last))
        return evidence
