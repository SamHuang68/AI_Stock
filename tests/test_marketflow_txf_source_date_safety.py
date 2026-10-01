import sys
from pathlib import Path
from datetime import date, datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from exchange_source_dates import official_date, response_date, txf_timestamp, TAIPEI, marketflow_payload, marketflow_cache_key
from market_contract import quote_contract


def test_official_dates_fail_closed():
    assert official_date('115/10/01') == date(2026,10,1)
    assert official_date('20261001') == date(2026,10,1)
    assert official_date('20260230') is None
    assert response_date({'date':'20260930'},date(2026,10,1),date(2026,10,1)) is None
    assert response_date({},date(2026,10,1),date(2026,10,1)) is None


def test_txf_preserves_official_calendar_day_and_timezone():
    now = datetime(2026,10,1,12,tzinfo=TAIPEI)
    assert txf_timestamp('20260930','230501',now) == '2026-09-30T23:05:01+08:00'
    assert txf_timestamp('20261001','02:30:00',now) == '2026-10-01T02:30:00+08:00'
    assert txf_timestamp(None,'02:30:00',now) is None
    assert txf_timestamp('20261001','25:30:00',now) is None
    assert txf_timestamp('20261002','02:30:00',now) is None
    assert quote_contract({'time':'02:30:00','asOf':None},symbol='__TXF__',market='TW')['asOf'] is None


def test_marketflow_requires_response_date_and_valid_row_dates():
    def fetch(url):
        if 'FMTQIK' in url:
            return {'stat':'OK','fields':['日期','成交金額'], 'data':[['115/10/01','100'],['115/10/02','200'],['bad','300'],['115/09/30','400']]}
        if 'BFI82U' in url:
            return {'stat':'OK','date':'20260930','fields':['單位名稱','買賣超'], 'data':[['外資','10']]}
        return {'stat':'OK','date':'20260930','tables':[{'data':[['融資','1']]}]}
    out = marketflow_payload(fetch,date(2026,10,1))
    assert len(out['turnover']) == 1
    assert out['turnover'][0]['sourceDate'] == '2026-10-01'
    assert out['inst']['date'] == '20260930'
    assert out['margin'] is None


def test_missing_official_date_never_uses_request_date():
    def fetch(url):
        return {'stat':'OK','fields':['單位名稱','買賣超'],'data':[['外資','10']], 'tables':[{'data':[['融資','1']]}]}
    out = marketflow_payload(fetch,date(2026,10,1))
    assert out['inst'] is None
    assert out['margin'] is None


def test_valid_margin_retains_source_date():
    def fetch(url):
        if 'MI_MARGN' in url:
            return {'stat':'OK','date':'20261001','tables':[{'data':[['融資','1']]}]}
        return {'stat':'no data'}
    assert marketflow_payload(fetch,date(2026,10,1))['margin']['sourceDate'] == '2026-10-01'


def _function_node(name, method=False):
    import ast
    source = (Path(__file__).resolve().parents[1] / 'server' / 'server.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.Module(body=[node], type_ignores=[])
    raise AssertionError(name)


def test_both_consumers_share_canonical_payload_and_cache():
    import ast
    import json
    from types import SimpleNamespace
    calls=[]
    class Cache:
        data={}
        def get(self,key): return self.data.get(key)
        def set(self,key,value,ttl): self.data[key]=value
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"stat":"no data"}'
    def open_url(req,timeout):
        calls.append(req)
        return Response()
    ns={'taipei_today':lambda:date(2026,10,1),'_cache':Cache(),'json':json,'marketflow_payload':marketflow_payload,
        'marketflow_cache_key':marketflow_cache_key,
        'urllib':SimpleNamespace(request=SimpleNamespace(Request=lambda url,headers:url,urlopen=open_url)),
        'YF_HEADERS':{},'_turnover_quant':lambda rows:None}
    exec(compile(_function_node('_canonical_marketflow'),'<canonical>','exec'),ns)
    assert ns['_canonical_marketflow']() == ns['_canonical_marketflow']()
    assert len(calls) == 9
    assert list(ns['_cache'].data) == ['marketflow:source-date-v1:20261001']
    for consumer in ('_handle_marketflow','_build_tw_market_fundamental'):
        assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_canonical_marketflow' for n in ast.walk(_function_node(consumer)))


def test_txf_handler_rejects_missing_date_and_preserves_official_timestamp():
    import json
    from types import SimpleNamespace
    row={'CLastPrice':'100','CRefPrice':'99','CTotalVolume':'50','CDate':'20260930','CTime':'23:01:02'}
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps({'RtData':{'QuoteList':[row]}}).encode()
    ns={'json':json,'txf_timestamp':lambda day,clock:txf_timestamp(day,clock,datetime(2026,10,1,12,tzinfo=TAIPEI)),
        'urllib':SimpleNamespace(request=SimpleNamespace(Request=lambda *a,**k:None,urlopen=lambda *a,**k:Response()))}
    exec(compile(_function_node('_txf_mis_session'),'<txf>','exec'),ns)
    def number(raw,*keys):
        for key in keys:
            if raw.get(key) is not None: return float(raw[key])
        return None
    handler=SimpleNamespace(_txf_fnum=number)
    result=ns['_txf_mis_session'](handler,1)
    assert result['asOf']=='2026-09-30T23:01:02+08:00'
    assert result['sourceDate']=='2026-09-30'
    del row['CDate']
    assert ns['_txf_mis_session'](handler,1) is None


def test_partial_institution_payload_keeps_missing_values_explicit():
    def fetch(url):
        if 'BFI82U' in url:
            return {'stat':'OK','date':'20261001','fields':['單位名稱','買賣超'],'data':[['外資','0'],['投信','--']]}
        return {'stat':'no data'}
    inst = marketflow_payload(fetch,date(2026,10,1))['inst']
    assert inst['foreign'] == 0
    assert inst['trust'] is None
    assert inst['dealer'] is None


def test_marketflow_date_is_latest_observed_official_date_never_request_day():
    # 過去 date 一律填請求日：法人抓不到時，盤後頁會把「今天」當成法人資料日。
    nothing = marketflow_payload(lambda url: {'stat': 'no data'}, date(2026, 10, 1))
    assert nothing['date'] is None

    def only_inst(url):
        if 'BFI82U' in url and 'dayDate=20260930' in url:
            return {'stat': 'OK', 'date': '20260930', 'fields': ['單位名稱', '買賣超'], 'data': [['外資', '10']]}
        return {'stat': 'no data'}
    out = marketflow_payload(only_inst, date(2026, 10, 1))
    assert out['inst']['date'] == '20260930'
    assert out['date'] == '2026-09-30'


def _marketflow_cache_ttl(fetch_json):
    """用與 test_canonical_marketflow 相同的方式載入 _canonical_marketflow，回傳寫入快取時的 ttl。"""
    import json
    from types import SimpleNamespace
    ttls = []
    class Cache:
        data = {}
        def get(self, key): return self.data.get(key)
        def set(self, key, value, ttl):
            self.data[key] = value
            ttls.append(ttl)
    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return self.body
    ns = {'taipei_today': lambda: date(2026, 10, 1), '_cache': Cache(), 'json': json,
          'marketflow_payload': marketflow_payload, 'marketflow_cache_key': marketflow_cache_key,
          'urllib': SimpleNamespace(request=SimpleNamespace(
              Request=lambda url, headers: url,
              urlopen=lambda url, timeout: Response(json.dumps(fetch_json(url)).encode()))),
          'YF_HEADERS': {}, '_turnover_quant': lambda rows: None}
    exec(compile(_function_node('_canonical_marketflow'), '<canonical>', 'exec'), ns)
    ns['_canonical_marketflow']()
    return ttls


def test_canonical_marketflow_short_caches_total_failure_but_long_caches_real_data():
    # 四個畫面共用這一份；整批失敗若快取 30 分鐘，TWSE 恢復後仍整整半小時沒資料。
    assert _marketflow_cache_ttl(lambda url: {'stat': 'no data'}) == [60]

    def with_turnover(url):
        if 'FMTQIK' in url:
            return {'stat': 'OK', 'fields': ['日期', '成交金額'], 'data': [['115/10/01', '100']]}
        return {'stat': 'no data'}
    assert _marketflow_cache_ttl(with_turnover) == [1800]


def load_tests(loader, tests, pattern):
    import unittest
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith('test_') and callable(function):
            suite.addTest(unittest.FunctionTestCase(function))
    return suite
