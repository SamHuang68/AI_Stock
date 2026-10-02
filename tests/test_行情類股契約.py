import math
import ast
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import market_routes as routes
import pulse_extras
import sector_flow
import sector_history
import tdcc_holders
from market_contract import tw_symbol_code, quote_contract
from 類股成員 import build_tw_members

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 2, 10, 30, tzinfo=TZ)


def row(**changes):
    return {'c': '6488', 'n': '環球晶', 'd': '20261002', 't': '10:30:00',
            'tlong': NOW.timestamp() * 1000, 'z': '100', 'y': '100', 'v': '0', **changes}


def test_mis_last_trade_and_volume_keep_separate_timestamps():
    result = routes.twse_mis_stock_quote(row(z='-', trade={'z': '101', 't': '10:25:00'}), NOW)
    assert result['priceField'] == 'trade.z'
    assert result['price'] == 101
    assert result['changePct'] == 1
    assert result['asOf'] == '2026-10-02T10:25:00+08:00'
    assert result['volumeTimestampMs'] - result['timestampMs'] == 300000
    assert result['volumeShares'] == 0


def test_mis_never_uses_order_book_or_missing_trade_time():
    for value in (row(z='-', a='100', b='99'), row(z='-', trade={'z': '101'}),
                  row(z='-', trade={'z': '101', 't': '11:00:00'}), row(z='Infinity'), row(z=True)):
        assert routes.twse_mis_stock_quote(value, NOW) is None


def test_old_unknown_future_quote_rejected_during_session():
    for stamp in (None, (NOW - timedelta(days=1)).timestamp() * 1000,
                  (NOW + timedelta(hours=1)).timestamp() * 1000):
        result = routes.guard_tw_quote({'ok': True, 'price': 100, 'prevClose': 90, 'timestampMs': stamp}, NOW)
        assert result['ok'] is False
        assert result['price'] is None and result['changePct'] is None
    # 盤後保留真實最後成交；來源仍顯示過期，不改寫日期。
    result = routes.guard_tw_quote({'ok': True, 'price': 100, 'prevClose': 100,
        'timestampMs': NOW.timestamp() * 1000}, NOW + timedelta(days=1))
    assert result['price'] == 100 and result['stale']
    assert result['changePct'] == 0 and not result['priceRealtime']


def test_full_suffix_and_nonfinite_contract():
    assert tw_symbol_code(' 6488.two ') == '6488'
    assert tdcc_holders._norm_code('6488.TWO') == '6488'
    assert tw_symbol_code('US.TW.X') == 'US.TW.X'
    for value in (True, math.inf, math.nan):
        assert quote_contract({'price': value}, symbol='6488', market='TW')['price'] is None


def test_nhnl_rejects_invalid_tail_without_compressing_history():
    base = {str(i): list(range(1, 251)) for i in range(12)}
    assert pulse_extras.count_nhnl(base)['newHighs'] == 12
    assert pulse_extras.count_nhnl(base)['date'] is None
    for invalid in (None, True, 0, -1, math.inf, math.nan):
        with patch.dict(base, {'0': list(range(1, 251)) + [invalid]}):
            assert pulse_extras.count_nhnl(base) is None


def test_sector_members_include_zero_missing_and_tdr_without_limit():
    raw = [{'code': str(1000 + i), 'name': '成員', 'price': 100, 'change': 0,
            'changePct': 0, 'industry': '半導體業', 'ex': 'TWSE', 'asOf': '20261002'} for i in range(50)]
    raw += [{'code': '9105', 'name': '存託憑證', 'price': None, 'changePct': None,
             'industry': '半導體業', 'ex': 'TWSE', 'asOf': '20261002'}]
    raw += [{'code': '6488', 'industry': '半導體業', 'ex': 'TPEx'}]
    result = build_tw_members({'twseAvailable': True, 'classificationCount': 51,
        'classificationCoveragePct': 90, 'classificationComplete': False, 'rows': raw}, '半導體類指數')
    assert result['count'] == 51
    assert result['rows'][-1]['code'] == '9105'
    assert result['rows'][-1]['price'] is None
    assert result['rows'][0]['changePct'] == 0
    assert '存託憑證' in result['scopeLabel'] and '分類未完整' in result['scopeLabel']
    assert result['date'] == '2026-10-02'


def test_incomplete_classification_prevents_full_flow_claim():
    rows = sector_flow.attach_sector_metrics([{'name': '半導體', 'changePct': 0}], industry_turnover_yi={'半導體業': 60})
    result = sector_flow.build_sector_flow(rows, total_turnover_yi=100,
        classification_coverage_pct=90, classification_complete=False)
    assert result['rows'][0]['marketSharePct'] == 60
    assert result['classificationCoveragePct'] == 90
    assert result['hhi'] is None and not result['flowEligible']
    assert '存託憑證' in result['turnoverScopeLabel']


def test_sector_historical_cutoff_does_not_read_future_cache(tmp_path):
    path = str(tmp_path / 'sectors.db')
    for day in range(1, 23):
        sector_history.store_snapshot(f'202601{day:02}', [{'name': '半導體', 'close': 99 + day}], path)
    assert sector_history.return20_by_sector(path, as_of='20260121')['半導體'] == 20
    assert sector_history.return20_by_sector(path, as_of='20260120') == {}
    assert sector_history.return20_by_sector(path, as_of='20260230') == {}
    rows, status = sector_history.enrich_sector_rows(
        [{'name': '半導體', 'close': 120}], as_of='20260121', path=path, bootstrap=False,
        benchmark_bars=[{'date': '2026-01-01', 'close': 100}, {'date': '2026-01-21', 'close': 110},
                        {'date': '2026-01-22', 'close': 200}])
    assert rows[0]['return20Pct'] == 20
    assert status['benchmarkReturn20Pct'] == 10
    assert sector_history.benchmark_return20([{'close': 100}] * 21,
        session_dates=[f'202601{day:02}' for day in range(21, 0, -1)]) is None


def load_server_function(name, namespace):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'server/server.py').read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<正式類股入口>', 'exec'), namespace)
    return namespace[name]


def test_day_movers_denominator_keeps_unclassified_and_no_trade_members():
    raw = [
        {'Code': '2330', 'Name': '台積電', 'ClosingPrice': '100', 'Change': '0', 'TradeValue': '6000000000', 'Date': '20261002'},
        {'Code': '9105', 'Name': '存託憑證', 'ClosingPrice': '--', 'Change': '--', 'TradeValue': '4000000000', 'Date': '20261002'},
        {'Code': '1101', 'Name': '台泥', 'ClosingPrice': '--', 'Change': '--', 'TradeValue': '0', 'Date': '20261002'},
        {'Code': '0050', 'Name': 'ETF', 'ClosingPrice': '100', 'Change': '1', 'TradeValue': '9000000000', 'Date': '20261002'},
    ]
    class Thread:
        def __init__(self, target, **kwargs): self.target = target
        def start(self): self.target()
        def join(self, *args): pass
    def fetch(url, **kwargs):
        return io.BytesIO(json.dumps(raw if 'STOCK_DAY_ALL' in url else []).encode())
    ns = {'math': math, 'json': json, '_CODE4': re.compile(r'^[1-9]\d{3}$'),
          '_get_tw_sectors': lambda: {'2330': '半導體業', '1101': '水泥工業'},
          'threading': SimpleNamespace(Thread=Thread),
          'urllib': SimpleNamespace(request=SimpleNamespace(Request=lambda url, **kwargs: url, urlopen=fetch))}
    result = load_server_function('_fetch_day_movers', ns)(include_rows=True)
    assert len(result['rows']) == 3
    assert result['industryTurnoverTotalYi'] == 100
    assert result['industryTurnoverYi']['半導體'] == 60
    assert result['industryTurnoverYi']['水泥'] == 0
    assert result['classificationTotal'] == 3 and result['classificationCount'] == 2
    assert result['classificationCoveragePct'] == 66.67
    assert result['classificationComplete'] is False


def test_members_route_uses_full_snapshot_and_unavailable_us_without_fetch():
    calls, stored = [], {}
    class Cache:
        def get(self, key): return stored.get(key)
        def set(self, key, value, ttl=None):
            assert ttl == 300
            stored[key] = value
    snapshot = {'twseAvailable': True, 'classificationCount': 1, 'rows': [
        {'code': '2330', 'name': '台積電', 'industry': '半導體業', 'ex': 'TWSE',
         'price': 100, 'changePct': 0, 'asOf': '20261002'}]}
    def fetch(**kwargs):
        calls.append(kwargs)
        return snapshot
    ns = {'json': json, 'parse_qs': parse_qs, 'urlparse': urlparse,
          '_cache': Cache(), '_fetch_day_movers': fetch}
    method = load_server_function('_handle_sector_members', ns)
    class Handler:
        def _ok(self, data): self.result = json.loads(data)
        def _err(self, message, status): self.error = (message, status)
    handler = Handler()
    handler.path = '/sector-members?market=TW&sector=半導體'
    method(handler)
    assert handler.result['count'] == 1
    assert handler.result['date'] == '2026-10-02'
    method(handler)
    assert calls == [{'include_rows': True}]
    handler.path = '/sector-members?market=US&sector=Technology'
    method(handler)
    assert handler.result['scope'] == 'UNAVAILABLE' and handler.result['rows'] == []
    assert calls == [{'include_rows': True}]
