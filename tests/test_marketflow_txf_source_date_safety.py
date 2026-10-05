import sys
from pathlib import Path
from datetime import date, datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from exchange_source_dates import official_date, response_date, txf_timestamp, txf_timestamp_check, TAIPEI, marketflow_payload, marketflow_cache_key
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


def test_txf_timestamp_tolerates_small_local_clock_lag_but_not_real_future():
    now = datetime(2026,10,1,12,0,0,tzinfo=TAIPEI)
    # 交易所時間比本機快 60 秒：本機時鐘慢，不是壞資料
    assert txf_timestamp('20261001','12:01:00',now) == '2026-10-01T12:01:00+08:00'
    # 快 10 分鐘：超過容忍度，仍視為不可信
    assert txf_timestamp('20261001','12:10:00',now) is None


def test_txf_night_session_after_midnight_uses_the_calendar_day_after_the_session_start_date():
    # 使用者機器上的實測：2026-10-06 01:50:45，TAIFEX MIS 回 CDate=20261005 CTime=015041。
    # CDate 是夜盤「開始日」；直接組合會得到 10-05 01:50（比實際早 24 小時 → 畫面「1 日前」）。
    now = datetime(2026,10,6,1,50,45,tzinfo=TAIPEI)
    assert txf_timestamp('20261005','015041',now) == '2026-10-05T01:50:41+08:00'          # 未指定場次：維持原行為
    assert txf_timestamp_check('20261005','015041',now,session='night') == ('2026-10-06T01:50:41+08:00', None)
    assert txf_timestamp_check('20261005','04:59:59',datetime(2026,10,6,5,0,3,tzinfo=TAIPEI),session='night')[0] == '2026-10-06T04:59:59+08:00'
    # 週五夜盤跨到週六凌晨：CDate 是週五，實際是週六
    assert txf_timestamp_check('20261009','02:00:00',datetime(2026,10,10,2,5,tzinfo=TAIPEI),session='night')[0] == '2026-10-10T02:00:00+08:00'
    # 跨月、跨年
    assert txf_timestamp_check('20261031','00:30:00',datetime(2026,11,1,0,40,tzinfo=TAIPEI),session='night')[0] == '2026-11-01T00:30:00+08:00'
    assert txf_timestamp_check('20261231','03:00:00',datetime(2027,1,1,3,5,tzinfo=TAIPEI),session='night')[0] == '2027-01-01T03:00:00+08:00'


def test_txf_date_rule_only_applies_to_night_ticks_before_the_morning_cutoff():
    now = datetime(2026,10,6,20,0,tzinfo=TAIPEI)
    # 午夜前的夜盤、日盤、06:00 之後：CDate 就是日曆日，不能多加一天
    assert txf_timestamp_check('20261006','19:59:50',now,session='night')[0] == '2026-10-06T19:59:50+08:00'
    assert txf_timestamp_check('20261006','13:44:58',now,session='day')[0] == '2026-10-06T13:44:58+08:00'
    assert txf_timestamp_check('20261006','02:00:00',now,session='day')[0] == '2026-10-06T02:00:00+08:00'
    assert txf_timestamp_check('20261006','06:00:00',now,session=None)[0] == '2026-10-06T06:00:00+08:00'
    assert txf_timestamp_check('20261005','05:59:59',now,session='night')[0] == '2026-10-06T05:59:59+08:00'
    assert txf_timestamp_check('20261005','06:00:00',now,session='night')[0] == '2026-10-05T06:00:00+08:00'


def test_txf_night_date_rule_never_silently_produces_a_wrong_time_if_the_source_changes_semantics():
    # 若 TAIFEX 日後改成直接給日曆日（01:50 的報價 CDate=20261006），+1 會超前 → 'future'，
    # 報價改標「時間未核實」，而不是悄悄把時間算成明天。
    now = datetime(2026,10,6,1,50,45,tzinfo=TAIPEI)
    assert txf_timestamp_check('20261006','015041',now,session='night') == (None, 'future')
    # 本機時鐘慢超過容忍度也一樣是「未核實」，不是把日期退回前一天
    slow = datetime(2026,10,6,1,40,0,tzinfo=TAIPEI)
    assert txf_timestamp_check('20261005','015041',slow,session='night') == (None, 'future')
    # 容忍度內仍然有效
    assert txf_timestamp_check('20261005','015041',datetime(2026,10,6,1,49,0,tzinfo=TAIPEI),session='night')[0] == '2026-10-06T01:50:41+08:00'


def test_txf_handler_night_quote_after_midnight_is_current_not_a_day_old():
    now = datetime(2026,10,6,1,50,45,tzinfo=TAIPEI)
    row={'CLastPrice':'50118','CRefPrice':'49934','CTotalVolume':'17409','CDate':'20261005','CTime':'015041'}
    session, handler, logged = _txf_session_namespace(row, now=now)
    result = session(handler, 1)                       # MarketType 1 = 夜盤
    assert result['asOf'] == '2026-10-06T01:50:41+08:00'
    assert result['sourceDate'] == '2026-10-06'
    assert result['timeUnverified'] is False
    assert result['timeCheck'] == {'verified': True, 'reason': None, 'CDate': '20261005', 'CTime': '015041'}
    assert logged == []
    # 同一筆資料若被當成日盤（MarketType 0）就不加一天：日盤不跨午夜
    day_session, day_handler, _ = _txf_session_namespace(row, now=now)
    assert day_session(day_handler, 0)['asOf'] == '2026-10-05T01:50:41+08:00'


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


def _txf_session_namespace(row, now=None):
    """以 AST 載入 server.py 的 _txf_mis_session（不啟動 HTTP 伺服器），餵入假的 MIS 回應。"""
    import json
    from types import SimpleNamespace
    now = now or datetime(2026,10,1,12,tzinfo=TAIPEI)
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps({'RtData':{'QuoteList':[row]}}).encode()
    logged=[]
    ns={'json':json,'time':__import__('time'),
        'txf_timestamp_check':lambda day,clock,session=None:txf_timestamp_check(day,clock,now,session),
        '_txf_note_unverified_stamp':lambda session,stamp,reason:logged.append((session,reason,dict(stamp))),
        'urllib':SimpleNamespace(request=SimpleNamespace(Request=lambda *a,**k:None,urlopen=lambda *a,**k:Response()))}
    exec(compile(_function_node('_txf_mis_session'),'<txf>','exec'),ns)
    def number(raw,*keys):
        for key in keys:
            if raw.get(key) is not None: return float(raw[key])
        return None
    return ns['_txf_mis_session'], SimpleNamespace(_txf_fnum=number), logged


def test_txf_handler_preserves_official_timestamp():
    row={'CLastPrice':'100','CRefPrice':'99','CTotalVolume':'50','CDate':'20260930','CTime':'23:01:02'}
    session, handler, logged = _txf_session_namespace(row)
    result = session(handler, 1)
    assert result['asOf']=='2026-09-30T23:01:02+08:00'
    assert result['sourceDate']=='2026-09-30'
    assert result['timeUnverified'] is False
    assert result['timeCheck']['verified'] is True
    assert logged == []


def test_txf_handler_keeps_price_when_stamp_fails_validation_but_never_invents_a_time():
    # 過去：CDate 缺漏／語意不符（例如夜盤盤前標成下一個交易日）→ 整筆報價回 None，
    # Pulse 與決策中心完全看不到夜盤台指期，且沒有任何記錄。
    cases = {
        'missing_date': {'CTime': '23:01:02'},
        'future': {'CDate': '20261002', 'CTime': '23:01:02'},      # 夜盤標成下一個交易日
        'bad_time': {'CDate': '20260930', 'CTime': '99:99:99'},
    }
    for reason, stamp in cases.items():
        row={'CLastPrice':'50000','CRefPrice':'48025','CTotalVolume':'50',**stamp}
        session, handler, logged = _txf_session_namespace(row)
        result = session(handler, 1)
        assert result is not None, reason
        assert result['price'] == 50000.0
        assert result['asOf'] is None, '不可用本機時間或請求日冒充市場時間'
        assert result['sourceDate'] is None
        assert result['timeUnverified'] is True
        assert result['timeCheck']['reason'] == reason
        assert result['timeCheck']['CTime'] == stamp.get('CTime')
        assert logged and logged[0][1] == reason and logged[0][0] == 'night'


def test_txf_handler_still_returns_none_when_there_is_no_price_and_no_stamp():
    session, handler, logged = _txf_session_namespace({'CTotalVolume':'50'})
    result = session(handler, 1)
    assert result is None or result['price'] is None


def test_txf_unverified_stamp_logging_is_rate_limited():
    import io, contextlib
    ns={'time':__import__('time'),'_TXF_STAMP_LOG':{}}
    exec(compile(_function_node('_txf_note_unverified_stamp'),'<log>','exec'),ns)
    note=ns['_txf_note_unverified_stamp']
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        first=note('night',{'CDate':'20261002','CTime':'200000'},'future',now=1000.0)
        again=note('night',{'CDate':'20261002','CTime':'200001'},'future',now=1100.0)
        other=note('night',{'CDate':None,'CTime':'200001'},'missing_date',now=1100.0)
        later=note('night',{'CDate':'20261002','CTime':'201000'},'future',now=1700.0)
    assert (first, again, other, later) == (True, False, True, True)
    out=buf.getvalue()
    assert out.count('[txf]')==3 and "CDate='20261002'" in out and 'asOf left unknown' in out


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


def test_marketflow_fetches_the_three_sections_concurrently():
    # 基本面與 Pulse 都在請求執行緒上同步等這份資料；三組串行，冷快取最壞要等 FMTQIK＋7 次 BFI82U＋MI_MARGN。
    # 三組的第一次請求都停在 barrier 上：必須同時在飛才放行，串行執行會逾時（被各組吞掉 → 該組沒資料 → 斷言失敗）。
    import threading
    barrier = threading.Barrier(3, timeout=3)
    today = date(2026, 10, 1)
    def fetch(url):
        barrier.wait()
        if 'FMTQIK' in url:
            return {'stat': 'OK', 'fields': ['日期', '成交金額'], 'data': [['115/10/01', '100']]}
        if 'BFI82U' in url:
            return {'stat': 'OK', 'date': '20261001', 'fields': ['單位名稱', '買賣超'], 'data': [['外資', '10']]}
        return {'stat': 'OK', 'date': '20261001', 'tables': [{'data': [['融資', '1']]}]}
    out = marketflow_payload(fetch, today)
    assert len(out['turnover']) == 1
    assert out['inst']['foreign'] == 10
    assert out['margin']['sourceDate'] == '2026-10-01'
    assert out['date'] == '2026-10-01'


def load_tests(loader, tests, pattern):
    import unittest
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith('test_') and callable(function):
            suite.addTest(unittest.FunctionTestCase(function))
    return suite
