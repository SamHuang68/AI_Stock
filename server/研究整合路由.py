"""將研究純計算接至既有本機資料；讀取路徑不下載、不建庫。"""
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from http_boundary import BodyReadError, read_json_body


def query_values(path, allowed):
    query = parse_qs(urlsplit(path).query, keep_blank_values=True)
    if set(query) - set(allowed) or any(len(v) != 1 or not v[0] for v in query.values()):
        raise ValueError('查詢參數不合法、重複或空白')
    return {key: values[0] for key, values in query.items()}


def stock_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4,6}(?:\.(?:TW|TWO))?', value):
        raise ValueError('請提供台股代號')
    return value.removesuffix('.TWO').removesuffix('.TW')


def breakout_options(values):
    if set(values) - {'sym', 'asOf', 'range', 'start', 'priceBasis'}:
        raise ValueError('突破研究含有未知參數')
    code = stock_code(values.get('sym', '2330'))
    if values.get('sym', '2330') != code:
        raise ValueError('突破研究請使用不含交易所尾碼的代號；交易所由已存來源核對')
    period = values.get('range', '3y')
    if period not in ('30d', '3m', '6m', '1y', '3y', '5y', '10y', 'all', 'custom'):
        raise ValueError('研究區間不合法')
    if period == 'custom' and not values.get('start'):
        raise ValueError('自訂區間必須指定起日')
    for key in ('asOf', 'start'):
        value = values.get(key)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('日期必須是 YYYY-MM-DD')
            date.fromisoformat(value)
    if values.get('start') and values.get('asOf') and values['start'] > values['asOf']:
        raise ValueError('起日不可晚於截止日')
    if values.get('priceBasis', 'raw') not in ('raw', 'official_reference'):
        raise ValueError('價格口徑不合法')
    return code, {'as_of': values.get('asOf'), 'period': period, 'start_date': values.get('start')}


class ResearchIntegrationRoutesMixin:
    def _research_json(self, payload):
        self._ok(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def _research_database(self):
        return str(Path(self._BASE) / 'data' / 'market.db')

    def _handle_valuation_research(self):
        try:
            from 估值趨勢 import cached_lookup, get_research
            values = query_values(self.path, {'peMax', 'excludeIp'})
            if 'peMax' in values:
                values['peMax'] = float(values['peMax'])
            if 'excludeIp' in values:
                if values['excludeIp'] not in ('true', 'false'):
                    raise ValueError('excludeIp 必須是 true 或 false')
                values['excludeIp'] = values['excludeIp'] == 'true'
            identity = unquote(urlsplit(self.path).path[len('/valuation-research/'):])
            code = stock_code(identity)
            saved = self._research_runtime()
            self._research_json(get_research(identity, database=self._research_database(),
                lookup=cached_lookup(saved['official']), settings=values,
                name=saved['names'].get(code), chip_history_path=saved['chipHistory']))
        except (TypeError, ValueError) as exc:
            self._err(str(exc), 400)
        except (OSError, sqlite3.Error):
            self._err('本機估值研究資料無法讀取', 503)

    def _handle_research_screen(self, body):
        try:
            import datastore
            from 估值趨勢 import cached_lookup, run_screen
            if not isinstance(body.get('research', {}).get('enabled'), bool):
                raise ValueError('研究啟用欄位必須是布林值')
            for key in ('tech', 'fund', 'chip'):
                if key in body and not isinstance(body[key], dict):
                    raise ValueError('篩選條件必須是物件')
            saved = self._research_runtime()
            supplied = body.get('symbols')
            if supplied is not None:
                if not isinstance(supplied, list) or not supplied or len(supplied) > 4000:
                    raise ValueError('代號清單須為 1 至 4000 檔')
                for code in supplied:
                    stock_code(code)
                symbols = sorted(set(supplied))
                source = '指定代號，僅查本機資料'
            else:
                with datastore.read_snapshot(self._research_database()) as connection:
                    symbols = [code for code in datastore.list_symbols(connection=connection)
                               if re.fullmatch(r'\d{4,6}', code)]
                source = '本機已存台股宇集，並非歷史全市場全集'
            sector = body.get('sector') or ''
            if not isinstance(sector, str):
                raise ValueError('產業條件必須是文字')
            if sector and sector not in ('全部', 'all'):
                if not saved['sectors']:
                    self._err('尚無已存產業分類，請先更新既有資料', 503)
                    return
                wanted = saved['technologySectors'] if sector == '__TECH__' else {sector}
                symbols = [code for code in symbols if saved['sectors'].get(stock_code(code)) in wanted]
            result = run_screen(body, symbols=symbols, database=self._research_database(),
                lookup=cached_lookup(saved['official']), names=saved['names'],
                settings=body['research'], universe_source=source,
                chip_history_path=saved['chipHistory'], calc_ind=self._calc_ind,
                tech_match=self._screen3_tech)
            self._research_json(result)
        except (TypeError, ValueError) as exc:
            self._err(str(exc), 400)
        except (OSError, sqlite3.Error):
            self._err('本機研究資料無法讀取', 503)

    def _handle_breakout_research(self):
        try:
            if urlsplit(self.path).path == '/breakout-shadow':
                from 突破影子紀錄 import list_records
                values = query_values(self.path, {'sym'})
                code = stock_code(values.get('sym', '2330'))
                self._research_json(list_records(self._research_database(), code))
            else:
                from 突破觀察 import report
                values = query_values(self.path, {'sym', 'asOf', 'range', 'start'})
                code, options = breakout_options(values)
                self._research_json(report(self._research_database(), code, **options))
        except (TypeError, ValueError) as exc:
            self._err(str(exc), 400)
        except (OSError, sqlite3.Error):
            self._err('本機突破研究資料無法讀取', 503)

    def _handle_breakout_freeze(self):
        try:
            from 突破觀察 import report
            from 突破影子紀錄 import freeze
            body = read_json_body(self, max_bytes=8192)
            if not isinstance(body, dict):
                raise ValueError('凍結條件必須是物件')
            code, options = breakout_options(body)
            result = report(self._research_database(), code, **options)
            self._research_json(freeze(self._research_database(), result,
                                      price_basis=body.get('priceBasis', 'raw')))
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
        except (TypeError, ValueError) as exc:
            self._err(str(exc), 400)
        except (OSError, sqlite3.Error):
            self._err('突破研究凍結失敗，原紀錄保留', 503)
