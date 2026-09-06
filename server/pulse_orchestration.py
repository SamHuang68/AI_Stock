#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pulse /pulse orchestration — builds the canonical market pulse payload."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from deadline import collect_named
from market_routes import market_snapshot


@dataclass
class PulseDeps:
    cache: Any = None
    pulse_extras_pool: Any = None
    pulse_side_pool: Any = None
    build_breadth_payload: Callable[..., dict] | None = None
    build_tw_market_fundamental: Callable[..., dict] | None = None
    twse_mis_index: Callable[..., dict] | None = None
    yf_batch_quotes: Callable[..., list] | None = None
    macro_latest: Callable[..., Any] | None = None
    fetch_day_movers: Callable[..., dict] | None = None
    fmtqik_turnover: Callable[..., list] | None = None
    fmtqik_index_closes: Callable[..., list] | None = None
    marketflow_payload: Callable[..., dict] | None = None
    tw_index_closes: Callable[..., list] | None = None
    turnover_quant: Callable[..., dict] | None = None
    price_series_quant: Callable[..., dict] | None = None
    fetch_one: Callable[..., Any] | None = None


_deps = PulseDeps()


def configure(**kwargs: Any) -> None:
    for key, value in kwargs.items():
        setattr(_deps, key, value)


def build_pulse_payload(handler, path: str) -> bytes:
    """Build GET /pulse response body (bytes JSON). Caller handles HTTP."""
    from datetime import date as _date
    qs = parse_qs(urlparse(path).query)
    force = (qs.get('refresh', ['0'])[0] or '0') in ('1', 'true', 'yes')
    key = f'pulse:v2:{_date.today().strftime("%Y%m%d")}:{int(time.time() // 45)}'
    if not force:
        c = _deps.cache.get(key)
        if c is not None:
            return c

    def _loads(raw):
        if raw is None:
            return None
        try:
            return json.loads(raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw)
        except Exception:
            return None

    def _cache_first(keys):
        for k in keys:
            d = _loads(_deps.cache.get(k))
            if d is not None:
                return d
        return None

    today = _date.today()
    ymd = today.strftime('%Y%m%d')
    y_m_d = today.strftime('%Y-%m-%d')

    # 延伸因子與體質並行：OI／借券／NHNL／類股（專用 pool，不佔用全域 _pool）
    extras_fut = None
    try:
        import pulse_extras as _pulse_extras
        extras_budget = 7.5 if force else 5.5
        extras_fut = _deps.pulse_extras_pool.submit(
            lambda b=extras_budget: _pulse_extras.fetch_all(budget=b)
        )
    except Exception as e:
        print('[pulse] extras submit', e)

    # 1) 體質（權威來源）
    fund = {}
    try:
        fund = _deps.build_tw_market_fundamental('^TWII') or {}
    except Exception as e:
        print('[pulse] fundamental', e)
        fund = {}

    # 2) 廣度／指數／法人 — 優先快取；miss 時內聯建置（不經 _handle_*，避免弄亂 HTTP）
    bd = _cache_first([f'breadth:v1:{ymd}'])
    if not (isinstance(bd, dict) and bd.get('ok')):
        try:
            bd = _deps.build_breadth_payload(force=False)
        except Exception as e:
            print('[pulse] breadth hydrate', e)
            bd = bd if isinstance(bd, dict) else None
    mf = _cache_first([f'marketflow:{ymd}', f'marketflow:{y_m_d}'])
    if mf is None and _deps.marketflow_payload is not None:
        try:
            mf = _deps.marketflow_payload()
        except Exception as e:
            print('[pulse] marketflow hydrate', e)
            mf = None
    sec = _cache_first([
        f'sectors:{ymd}',
        f'sectors:TW:yahoo:{ymd}',
        f'sectors:TW:{ymd}',
    ])
    txf = _cache_first([f'txf:{int(time.time() // 20)}', f'txf:{int(time.time() // 20) - 1}'])

    # 指數可直取 MIS；台指期可直取既有解析（不經 _handle_txf）。
    indices = (bd or {}).get('indices') or {}
    if not (indices.get('t00') or {}).get('price'):
        try:
            indices = _deps.twse_mis_index('tse_t00.tw|otc_o00.tw') or {}
        except Exception as e:
            print('[pulse] twindex', e)
            indices = indices or {}

    stocks = (bd or {}).get('stocks') if bd else None
    inst = (mf or {}).get('inst') if mf else None
    if inst is None and bd:
        inst = bd.get('inst')

    # 夜盤：快取未命中則輕量直取（與 _handle_txf 同源 helper）
    txf_night = None
    if txf and txf.get('ok'):
        n = txf.get('night')
        if n and n.get('price') is not None:
            txf_night = n
        elif txf.get('price') is not None and (
            txf.get('session') == 'night' or txf.get('ampRate') is not None
        ):
            txf_night = txf
    if txf_night is None:
        try:
            n = handler._txf_mis_session(1)
            if n and n.get('price') is not None:
                txf_night = n
        except Exception as e:
            print('[pulse] txf night', e)

    sectors = []
    if isinstance(sec, dict):
        sectors = sec.get('sectors') or sec.get('list') or []
    elif isinstance(sec, list):
        sectors = sec

    # 延伸因子（類股／OI／借券賣出／250日 NHNL）— 與體質並行，失敗進 pending
    extras = {'sectors': None, 'txOi': None, 'sbl': None, 'nhnl': None}
    extras_outcomes = {}
    if extras_fut is not None:
        values, parent_outcomes = collect_named(
            {'extras': extras_fut}, timeout=8.0, executor=_deps.pulse_extras_pool)
        candidate = values.get('extras')
        if isinstance(candidate, dict):
            extras.update(candidate)
            extras_outcomes = candidate.get('_outcomes') or {}
        if parent_outcomes.get('extras') != 'ok':
            extras_outcomes['aggregate'] = parent_outcomes.get('extras')
    else:
        extras_outcomes['aggregate'] = 'saturated'

    if not sectors:
        ex_sec = extras.get('sectors') if isinstance(extras, dict) else None
        if isinstance(ex_sec, dict) and ex_sec.get('sectors'):
            sectors = ex_sec.get('sectors') or []
            try:
                _deps.cache.set(
                    f'sectors:{ymd}',
                    json.dumps({'ok': True, 'sectors': sectors, 'source': ex_sec.get('source')},
                               ensure_ascii=False).encode(),
                    ttl=300,
                )
            except Exception:
                pass

    tx_oi = extras.get('txOi') if isinstance(extras, dict) else None
    sbl = extras.get('sbl') if isinstance(extras, dict) else None
    nhnl = extras.get('nhnl') if isinstance(extras, dict) else None

    import pulse_intel as pi
    # sources.sectors 必須用過濾後類股，與因子帳本／完整度對齊
    sectors_scored = pi.filter_sectors(sectors)
    nhnl_ok = bool(
        isinstance(nhnl, dict)
        and nhnl.get('newHighs') is not None
        and nhnl.get('newLows') is not None
        and (nhnl.get('sampleN') or 0) >= pi.NHNL_MIN_SAMPLE
    )
    sources = {
        'twindex': bool((indices.get('t00') or {}).get('price') is not None),
        'breadth': bool(stocks and stocks.get('advRatio') is not None),
        'marketflow': bool(mf and (mf.get('turnover') or mf.get('inst'))),
        'health': fund.get('score') is not None,
        'margin': (fund.get('pillars') or {}).get('marginRatio') is not None,
        'valuation': (fund.get('pillars') or {}).get('medianPE') is not None,
        'txf': bool(txf_night and txf_night.get('price') is not None),
        'sectors': bool(sectors_scored),
        'txOi': bool(isinstance(tx_oi, dict) and tx_oi.get('oi') is not None
                     and tx_oi.get('oiChgPct') is not None),
        'sbl': bool(isinstance(sbl, dict) and sbl.get('sblSellYi') is not None),
        'nhnl': nhnl_ok,
    }

    try:
        out = pi.build_pulse_intel(
            health_score=fund.get('score'),
            pillars=fund.get('pillars'),
            market_rows=fund.get('marketRows'),
            summary=fund.get('summary'),
            stocks=stocks,
            indices=indices,
            inst=inst or {},
            txf_night=txf_night,
            sectors=sectors,
            sources_present=sources,
            tx_oi=tx_oi if isinstance(tx_oi, dict) else None,
            sbl=sbl if isinstance(sbl, dict) else None,
            nhnl=nhnl if isinstance(nhnl, dict) else None,
        )
    except Exception as e:
        print('[pulse] build', e)
        out = {'ok': False, 'error': f'pulse build failed: {e}'}

    # 附帶列表資料供前端一次渲染（減少 round-trip）
    out['date'] = (bd or {}).get('date')
    out['breadthOk'] = bool(bd and bd.get('ok'))
    out['breadthSource'] = (bd or {}).get('source') or 'TWSE MI_INDEX MS'
    out['breadthScope'] = 'TWSE_STOCKS'
    out['indices'] = indices
    out['stocks'] = stocks
    out['inst'] = inst
    out['txf'] = txf_night
    # Canonical snapshot: headline renderers must not recompute a live
    # change from a daily-series close.
    market_snap = market_snapshot(indices, txf_night)
    out['marketSnapshot'] = market_snap
    out['marketflow'] = {
        'turnover': (mf or {}).get('turnover'),
        'inst': inst,
    } if mf else None
    out['sectors'] = sectors
    out['extras'] = {
        'txOi': tx_oi if isinstance(tx_oi, dict) else None,
        'sbl': sbl if isinstance(sbl, dict) else None,
        'nhnl': nhnl if isinstance(nhnl, dict) else None,
        'sectorsSource': (extras.get('sectors') or {}).get('source')
        if isinstance(extras.get('sectors'), dict) else None,
    }
    # Headline freshness must follow per-quote market observation time,
    # not a whole-page server generation stamp.
    out['updatedAt'] = market_snap.get('marketAsOf') or market_snap.get('generatedAt')

    # ── Overview 儀表板擴充（對齊 tw-pulse 參考圖）──────────────
    # movers / global / macro / flash 並行；總預算 ~8s（FRED 在此環境常逾時，必須 fail-fast）
    PULSE_SIDE_BUDGET = 8.0

    def _job_movers():
        _sector_day = ((sec or {}).get('date') if isinstance(sec, dict) else None) or out.get('date')
        m = _cache_first([f'movers:v5:{_sector_day or ymd}'])
        if m is not None:
            return m
        try:
            m = _deps.fetch_day_movers(8, target_date=_sector_day)
            if m and m.get('ok'):
                _deps.cache.set(f'movers:v5:{_sector_day or ymd}', json.dumps(m, ensure_ascii=False).encode(), ttl=300)
            return m
        except Exception as e:
            print('[pulse] movers', e)
            return {'ok': False, 'gainers': [], 'losers': []}

    def _job_flash():
        try:
            import market_flash as _mf
            return _mf.build_flash(n=20, force=False)
        except Exception as e:
            print('[pulse] flash', e)
            return {'ok': False, 'items': []}

    def _job_global():
        # v8：同批補 2330／0050 作去重錨點；前端全球面板仍只收到國際列。
        gkey = f'pulse-global:v8:{int(time.time() // 120)}'
        g = _cache_first([gkey])
        if g is not None:
            return g
        try:
            # 指數列優先吃市場 tab 同源標的（SOX/美股/日韓）；
            # 另補 VIX／匯率／美元／黃金／銅／原油；AI 鏈代理個股
            g = _deps.yf_batch_quotes([
                '^DJI', '^GSPC', '^IXIC', '^SOX', '^N225', '^KS11',
                '^VIX', 'TWD=X', 'DX-Y.NYB', 'GC=F', 'HG=F', 'CL=F',
                'NVDA', 'AVGO', 'TSM', '2330.TW', '0050.TW',
            ])
            if not any(x.get('symbol') == 'DX-Y.NYB' for x in (g or [])):
                # 僅在缺美元指數時補一槍，不重抓整批
                extra = _deps.yf_batch_quotes(['DX=F'])
                if extra:
                    g = list(g or []) + list(extra)
            _deps.cache.set(gkey, json.dumps(g, ensure_ascii=False).encode(), ttl=120)
            return g
        except Exception as e:
            print('[pulse] global', e)
            return []

    def _job_macro():
        """快取優先；未命中才短逾時抓 FRED（timeout=3, retries=1）。"""
        u10 = None
        eco_rows = []
        try:
            u10 = _deps.macro_latest('us10y', years=5, timeout=3, retries=1)
        except Exception as e:
            print('[pulse] us10y', e)
        for mk in ('unrate', 'us_cpi_yoy', 'tw_cpi'):
            try:
                # 先只讀快取；沒有再短抓（tw_cpi 走政府源，允許稍長）
                row = _deps.macro_latest(mk, years=10, timeout=3, retries=1,
                                    allow_fetch=(mk == 'tw_cpi'))
                if row is None and mk != 'tw_cpi':
                    row = _deps.macro_latest(mk, years=10, timeout=3, retries=1, allow_fetch=True)
                if row:
                    eco_rows.append(row)
            except Exception as e:
                print('[pulse] macro', mk, e)
        return u10, eco_rows

    movers = {'ok': False, 'gainers': [], 'losers': []}
    global_q = []
    us10y = None
    eco = []
    flash_pack = {'ok': False, 'items': []}
    side_jobs = {
        'movers': _deps.pulse_side_pool.submit(_job_movers),
        'global': _deps.pulse_side_pool.submit(_job_global),
        'macro': _deps.pulse_side_pool.submit(_job_macro),
        'flash': _deps.pulse_side_pool.submit(_job_flash),
    }
    side_values, side_outcomes = collect_named(
        side_jobs, timeout=PULSE_SIDE_BUDGET, executor=_deps.pulse_side_pool)
    if isinstance(side_values.get('movers'), dict):
        movers = side_values['movers'] or movers
    if isinstance(side_values.get('global'), list):
        global_q = side_values['global'] or []
    if side_outcomes.get('macro') == 'ok':
        try:
            us10y, eco = side_values['macro']
            eco = eco or []
        except Exception as exc:
            side_outcomes['macro'] = f'error:{type(exc).__name__}'
    else:
        # Timeout/saturation: cache-only fallback, never another network call.
        try:
            us10y = _deps.macro_latest('us10y', years=5, allow_fetch=False)
            for mk in ('unrate', 'us_cpi_yoy', 'tw_cpi'):
                row = _deps.macro_latest(mk, years=10, allow_fetch=False)
                if row:
                    eco.append(row)
        except Exception:
            pass
    if isinstance(side_values.get('flash'), dict):
        flash_pack = side_values['flash'] or flash_pack
    out['sourceOutcomes'] = {
        'extras': extras_outcomes,
        'overview': side_outcomes,
    }

    # 市場快訊：台／美公司重大訊息（market_flash）；行事曆事件僅作少量補充
    flash = list((flash_pack or {}).get('items') or [])
    try:
        ev = _cache_first([f'events:{ymd}:', f'events:{ymd}'])
        if isinstance(ev, dict):
            rev = ev.get('revenue') or {}
            if rev.get('nextPublishBy') and len(flash) < 18:
                flash.append({
                    'time': str(rev.get('nextPublishBy')),
                    'title': f"月營收時程 {rev.get('forMonth') or ''}（尚餘 {rev.get('daysAway')} 天）"
                             if rev.get('daysAway') is not None
                             else f"月營收時程 {rev.get('nextPublishBy')}",
                    'cat': '總經',
                    'mkt': 'TW',
                    'source': 'events',
                })
    except Exception:
        pass
    if not flash:
        flash.append({
            'time': out.get('updatedAt') or '',
            'title': '重大訊息載入中（上市／櫃買重訊＋美股）— 可稍後重試',
            'cat': '系統',
        })

    # 成交金額（億）— breadth.turnover 優先；序列用 marketflow／FMTQIK 量化趨勢
    turnover_yi = None
    to_bd = (bd or {}).get('turnover') or {}
    for k in ('stockAmt', 'totalAmt'):
        if to_bd.get(k) is not None:
            try:
                turnover_yi = float(to_bd[k]) / 1e8
                break
            except Exception:
                pass
    turns = (mf or {}).get('turnover') if mf else None
    if not turns:
        try:
            turns = _deps.fmtqik_turnover()
        except Exception as e:
            print('[pulse] fmtqik', e)
            turns = []
    if turnover_yi is None and turns:
        try:
            turnover_yi = float(turns[-1]['amount']) / 1e8
        except Exception:
            pass
    tq = _deps.turnover_quant(turns or [], latest_yi=turnover_yi)
    if turnover_yi is None and tq.get('yi') is not None:
        turnover_yi = tq['yi']
    turnover_chg = tq.get('chgPct')

    t00 = indices.get('t00') or {}
    o00 = indices.get('o00') or {}
    # 加權／櫃買／台指期：與成交金額同構的趨勢量化（vs5／Z／連漲跌／動能分）
    try:
        t00_closes = _deps.fmtqik_index_closes(turns)
        t00_trend = _deps.price_series_quant(
            t00_closes, latest=t00.get('price'), quote_change_pct=t00.get('changePct'))
    except Exception as e:
        print('[pulse] t00 trend', e)
        t00_trend = _deps.price_series_quant(
            [], latest=t00.get('price'), quote_change_pct=t00.get('changePct'))
    try:
        o00_closes = _deps.tw_index_closes('^TWOII', n=30)
        o00_trend = _deps.price_series_quant(
            o00_closes, latest=o00.get('price'), quote_change_pct=o00.get('changePct'))
    except Exception as e:
        print('[pulse] o00 trend', e)
        o00_trend = _deps.price_series_quant(
            [], latest=o00.get('price'), quote_change_pct=o00.get('changePct'))
    txf_live = None
    try:
        # strip 顯示的台指期價（夜盤優先）覆寫連續日線末端
        if isinstance(txf_night, dict):
            txf_live = txf_night.get('price')
        if txf_live is None and isinstance(txf, dict):
            txf_live = txf.get('price')
        txf_closes = _deps.tw_index_closes('__TXF__', n=30)
        # 頂列台指期使用與 p.txf 完全相同的 TAIFEX 即時 session。
        # 日線只提供 vs5／Z／趨勢；漲跌幅不可從跨日／換月快取反推。
        txf_trend = _deps.price_series_quant(
            txf_closes, latest=txf_live,
            quote_change_pct=(txf_night or {}).get('changePct'))
    except Exception as e:
        print('[pulse] txf trend', e)
        txf_trend = _deps.price_series_quant([])
    # 台指期 − 加權現貨＝Basis（正價差／逆價差）；與前端 strip.basisPts／basisPct 對齊
    basis_pts = None
    basis_pct = None
    try:
        t00_px = t00.get('price')
        if txf_live is not None and t00_px is not None:
            t00_f = float(t00_px)
            txf_f = float(txf_live)
            basis_pts = round(txf_f - t00_f, 2)
            if t00_f > 0:
                basis_pct = round(basis_pts / t00_f * 100.0, 3)
    except Exception as e:
        print('[pulse] basis', e)
        basis_pts = None
        basis_pct = None
    st = stocks or {}
    up, dn, flat = st.get('up'), st.get('down'), st.get('unchanged')
    ls_ratio = None
    if up is not None and dn not in (None, 0):
        try:
            ls_ratio = round(float(up) / float(dn), 2)
        except Exception:
            ls_ratio = None

    try:
        import pulse_intel as _pi_ov
        sec_ranked = list(_pi_ov.filter_sectors(sectors))
    except Exception:
        sec_ranked = list(sectors_scored) if sectors_scored else []
    sec_ranked.sort(key=lambda x: x['changePct'], reverse=True)

    foreign = (inst or {}).get('foreign')
    trust = (inst or {}).get('trust')
    dealer = (inst or {}).get('dealer')
    total_yi = None
    if any(v is not None for v in (foreign, trust, dealer)):
        total_yi = ((foreign or 0) + (trust or 0) + (dealer or 0)) / 1e8

    out['movers'] = movers
    _signal_symbols = {'2330.TW', '0050.TW'}
    out['signalQuotes'] = [row for row in global_q if row.get('symbol') in _signal_symbols]
    global_q = [row for row in global_q if row.get('symbol') not in _signal_symbols]
    out['global'] = global_q
    # AI／科技外溢：只吃已抓到的 global（費半／那指／VIX／NVDA…），無資料不改分、不畫空殼
    try:
        import pulse_intel as _pi_spill
        out = _pi_spill.apply_ai_tech_spillover(out, global_q, sectors)
    except Exception as e:
        print('[pulse] ai spillover', e)
        try:
            out['aiSpill'] = {'ok': False, 'reason': 'apply_failed'}
        except Exception:
            pass
    out['us10y'] = us10y
    out['economy'] = eco
    out['flash'] = flash
    out['overview'] = {
        'strip': {
            't00': t00,
            'o00': o00,
            't00Trend': t00_trend,
            'o00Trend': o00_trend,
            'txfTrend': txf_trend,
            'basisPts': basis_pts,
            'basisPct': basis_pct,
            'turnoverYi': round(turnover_yi, 1) if turnover_yi is not None else None,
            'turnoverChgPct': round(turnover_chg, 2) if turnover_chg is not None else None,
            'turnoverMa5Yi': tq.get('ma5Yi'),
            'turnoverVsMa5Pct': tq.get('vsMa5Pct'),
            'turnoverZ20': tq.get('z20'),
            'volumeScore': tq.get('volumeScore'),
            'turnoverStreak': tq.get('streak'),
            'turnoverTrend': tq.get('trend'),
            'turnoverLevel': tq.get('level'),
            'turnoverN': tq.get('n'),
            'up': up, 'down': dn, 'flat': flat,
            'limitUp': st.get('limitUp'),
            'limitDown': st.get('limitDown'),
            'advRatio': st.get('advRatio'),
            'lsRatio': ls_ratio,
            'dataLabel': '官方盤後／即時混成' if out.get('breadthOk') else '部分資料可用',
        },
        'ohlc': {
            'open': t00.get('open'), 'high': t00.get('high'), 'low': t00.get('low'),
            'prevClose': t00.get('prevClose'), 'price': t00.get('price'),
            'changePct': t00.get('changePct'), 'name': t00.get('name') or '加權指數',
            'otcChangePct': o00.get('changePct'),
            'otcPrice': o00.get('price'),
        },
        'institutional': {
            'foreign': foreign, 'trust': trust, 'dealer': dealer,
            'totalYi': round(total_yi, 1) if total_yi is not None else None,
            'date': (inst or {}).get('date'),
            'source': (inst or {}).get('source'),
        },
        'sectorsRanked': sec_ranked[:12],
        'lsRatio': ls_ratio,
    }

    # Yahoo 補齊加權 OHLC（MIS 若缺 h/l）— 最多等 3s，不拖垮整包
    ohlc = out['overview']['ohlc']
    if ohlc.get('high') is None or ohlc.get('low') is None or ohlc.get('open') is None:
        _ohlc_box = {'data': None, 'err': None}

        def _ohlc_job():
            try:
                _, data, _ = _deps.fetch_one('^TWII', '5d', '1d', False)
                _ohlc_box['data'] = data
            except Exception as e:
                _ohlc_box['err'] = e

        th = threading.Thread(target=_ohlc_job, daemon=True)
        th.start()
        th.join(3.0)
        if _ohlc_box['data']:
            try:
                res = (json.loads(_ohlc_box['data']).get('chart') or {}).get('result') or []
                if res:
                    q = ((res[0].get('indicators') or {}).get('quote') or [{}])[0]

                    def _last(arr):
                        for x in reversed(arr or []):
                            if x is not None:
                                return x
                        return None

                    if ohlc.get('open') is None:
                        ohlc['open'] = _last(q.get('open'))
                    if ohlc.get('high') is None:
                        ohlc['high'] = _last(q.get('high'))
                    if ohlc.get('low') is None:
                        ohlc['low'] = _last(q.get('low'))
                    ohlc['source'] = (ohlc.get('source') or '') + '+yahoo'
            except Exception as e:
                print('[pulse] twii ohlc', e)
        elif _ohlc_box['err']:
            print('[pulse] twii ohlc', _ohlc_box['err'])

    # Deterministic DecisionContext：重用本包 canonical quote／廣度／因子；
    # AI 不參與 regime、confidence、levels 或 position range。
    try:
        import datastore as _decision_store
        import benchmark_research as _benchmark_research
        import decision_context as _decision
        import key_levels as _key_levels
        import margin_cycle as _margin_cycle
        import sector_flow as _sector_flow
        import sector_history as _sector_history

        _bars = _decision_store.get_bars('^TWII', limit=80)
        if not _bars:
            try:
                import pulse_history as _ph_levels
                _bars = ((_ph_levels.history(kind='index', n=80) or {}).get('rows') or [])
            except Exception:
                _bars = []
        _levels = _key_levels.calculate_key_levels(
            _bars, symbol='^TWII', session='regular', source='market.db/pulse-history',
            as_of=out.get('updatedAt'))
        try:
            import pulse_history as _ph_decision
            _breadth_hist = ((_ph_decision.history(kind='breadth', n=20) or {}).get('rows') or [])
            _index_hist = ((_ph_decision.history(kind='index', n=80) or {}).get('rows') or [])
        except Exception:
            _breadth_hist = []
            _index_hist = []
        try:
            import tw_index_charts as _tw_charts_decision
            _futures_hist = _tw_charts_decision.recent_rows('__TXF__', n=80, allow_network=False)
        except Exception:
            _futures_hist = []
        try:
            _margin_state = _margin_cycle.margin_balance_state()
        except Exception as _margin_exc:
            _margin_state = {
                'available': False, 'reason': str(_margin_exc)[:120],
                'source': 'TWSE MI_MARGN MS', 'role': 'risk_brake_only',
            }
        # Official Taiwan 50 history is owned by one canonical research
        # provider.  The request reads cache only; a missing/stale cache is
        # refreshed in a bounded daemon and remains fail-closed meanwhile.
        _benchmark_data = _benchmark_research.snapshot(allow_network=True)
        _sec_source = None
        if isinstance(extras.get('sectors'), dict):
            _sec_source = extras.get('sectors', {}).get('source')
        if not _sec_source and isinstance(sec, dict):
            _sec_source = sec.get('source') or sec.get('_source')
        _sec_source = _sec_source or 'TWSE MI_INDEX IND'
        _sector_session = _sector_flow.normalize_session_date(
            (sec or {}).get('date') if isinstance(sec, dict) else out.get('date'))
        _turnover_session = _sector_flow.normalize_session_date(
            movers.get('industryTurnoverDate') if isinstance(movers, dict) else None)
        _same_turnover_session = bool(_sector_session and _turnover_session == _sector_session)
        _industry_turnover = (movers.get('industryTurnoverYi') if
                              isinstance(movers, dict) and _same_turnover_session else None)
        _industry_turnover_total = (movers.get('industryTurnoverTotalYi') if
                                    isinstance(movers, dict) and _same_turnover_session else None)
        _sector_rows, _sec_hist_status = _sector_history.enrich_sector_rows(
            sectors,
            as_of=(sec or {}).get('date') if isinstance(sec, dict) else out.get('date'),
            benchmark_bars=_bars,
            industry_turnover_yi=_industry_turnover,
            bootstrap=('proxy' not in str(_sec_source).lower()),
            budget_seconds=4.0,
        )
        _turnover_source = (movers.get('industryTurnoverSource') if
                            isinstance(movers, dict) and _same_turnover_session else None)
        _sec_flow = _sector_flow.build_sector_flow(
            _sector_rows, market_scope='TWSE',
            source=_sec_source + ((' + ' + _turnover_source) if _turnover_source else ''),
            as_of=(sec or {}).get('date') if isinstance(sec, dict) else out.get('date'),
            total_turnover_yi=_industry_turnover_total,
            benchmark_return20_pct=_sec_hist_status.get('benchmarkReturn20Pct'),
            proxy_basket=('proxy' in str(_sec_source).lower()),
        )
        _sec_flow['historyStatus'] = _sec_hist_status
        _sec_flow['turnoverSource'] = _turnover_source
        _sec_flow['turnoverDate'] = _turnover_session
        _sec_flow['turnoverSessionMatched'] = _same_turnover_session
        try:
            import options_exposure as _options_exposure
            _options_structure = _options_exposure.latest_cached()
        except Exception:
            _options_structure = None
        _ctx = _decision.build_and_publish(
            out, key_levels=_levels, breadth_history=_breadth_hist,
            index_history=_index_hist, futures_history=_futures_hist,
            sector_flow=_sec_flow, margin_state=_margin_state,
            benchmark_data=_benchmark_data,
            options_structure=_options_structure)
        out['decisionSummary'] = _decision.compact_context(_ctx)
    except Exception as e:
        print('[pulse] decision context', e)
        try:
            import decision_context as _decision_fallback
            out['decisionSummary'] = _decision_fallback.compact_context(
                _decision_fallback.empty_context('decision_build_failed'))
        except Exception:
            out['decisionSummary'] = None

    body = json.dumps(out, ensure_ascii=False).encode()
    if out.get('ok'):
        _deps.cache.set(key, body, ttl=45)
        # 寫入脈動歷史庫（增量 merge；失敗不擋回應）
        try:
            import pulse_history as ph
            ph.save_pulse_score(out)
        except Exception as e:
            print('[pulse] history save', e)
    return body
