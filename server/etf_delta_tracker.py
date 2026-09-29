#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前十台股主動式 ETF 每日持股爬蟲

資料來源（依優先序）：
  1) MoneyDJ ETF基智網 (Basic0007B 全部持股頁面)  ← 主來源
  2) MoneyDJ Basic0007 (前十大持股)               ← fallback
  3) 台灣證券交易所 TWSE ETFortfolio              ← 最終 fallback（被動 ETF 才有）

說明：MoneyDJ 只提供最新持股。檔名是收集日，每檔另存來源揭露日；
      不支援以最新資料製造歷史回補。每日排程與手動更新共用驗收及診斷。

執行方式：
  python etf_delta_tracker.py
  python etf_delta_tracker.py --date 2026-05-12
  python etf_delta_tracker.py --backfill 5
"""

import os
import re
import ssl
import sys
import json
import shutil
import time
import html
import gzip
import math
import threading
import datetime
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import etf_paths
from ETF更新診斷 import UpdateTrace
from atomic_store import atomic_write_json

# ── ETF 下載為 I/O 工作；並行度由環境與遠端限制共同決定 ────────────
MAX_WORKERS  = 32         # 10 檔 ETF × 多來源 fallback，給寬鬆並發
RETRY_TIMES  = 4
RETRY_DELAY  = 1.5
TIMEOUT      = 20

# ── SSL：Windows 憑證問題統一關閉 ────────────────────────────────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

# ── 路徑 ──────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_FILE = os.path.join(SCRIPT_DIR, 'data', 'etf_catalog.json')

# ── ETFS 觀測池：從 etf_catalog.json 動態載入 enabled=true 的 ETF ─
def load_catalog():
    """讀取 etf_catalog.json，回傳 dict {code: (display_code, name)}.
    若找不到 catalog 或讀取失敗，fallback 回原本 hardcoded 的 10 檔。"""
    if not os.path.isfile(CATALOG_FILE):
        print(f'[WARN] {CATALOG_FILE} 不存在，使用 fallback 10 檔主動 ETF')
        return _FALLBACK_ETFS
    try:
        with open(CATALOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'[ERR] 讀取 {CATALOG_FILE} 失敗：{e}，使用 fallback')
        return _FALLBACK_ETFS
    out = {}
    for cat in data.get('categories', []):
        for etf in cat.get('etfs', []):
            if (etf.get('enabled') and etf.get('code')
                    and str(etf.get('market') or 'TW').upper() == 'TW'):
                code = etf['code'].strip().upper()
                name = etf.get('name', code)
                out[code] = (code, name)
    if not out:
        print(f'[WARN] catalog 內無 enabled 的 ETF，使用 fallback')
        return _FALLBACK_ETFS
    return out

_FALLBACK_ETFS = {
    '00992A': ('00992A', '主動群益科技創新'),
    '00981A': ('00981A', '主動統一台股增長'),
    '00987A': ('00987A', '主動台新優勢成長'),
    '00994A': ('00994A', '主動第一金台股優'),
    '00982A': ('00982A', '主動群益台灣強棒'),
    '00995A': ('00995A', '主動中信台灣卓越'),
    '00980A': ('00980A', '主動野村臺灣優選'),
    '00991A': ('00991A', '主動復華未來50'),
    '00996A': ('00996A', '主動兆豐台灣豐收'),
    '00984A': ('00984A', '主動安聯台灣高息'),
}

ETFS = load_catalog()
_request_context = threading.local()


def _source_event(event, **fields):
    trace = getattr(_request_context, 'trace', None)
    if trace:
        trace.record(event, code=getattr(_request_context, 'code', None), **fields)

# ── HTTP 標頭：模擬瀏覽器，加 Accept-Encoding 自動處理 gzip ──────
HEADERS = {
    'User-Agent':      ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/126.0.0.0 Safari/537.36'),
    'Accept':          ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                        'image/webp,*/*;q=0.8'),
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Cache-Control':   'no-cache',
}


# ── 共用：抓網頁 HTML，自動處理 gzip / 編碼 ──────────────────────
def http_get(url: str, referer: str = '') -> str | None:
    headers = dict(HEADERS)
    if referer:
        headers['Referer'] = referer
    for attempt in range(RETRY_TIMES):
        started = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as resp:
                raw = resp.read()
                if resp.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
                _source_event('source_response', url=url, attempt=attempt + 1,
                              status=resp.status, bytes=len(raw),
                              elapsedMs=round((time.monotonic() - started) * 1000))
            # 嘗試多種編碼
            for enc in ('utf-8', 'big5', 'cp950', 'gbk'):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            _source_event('source_error', url=url, attempt=attempt + 1, status=e.code,
                          error=type(e).__name__)
            if e.code in (404, 410):
                return None
            time.sleep(RETRY_DELAY)
        except Exception as exc:
            _source_event('source_error', url=url, attempt=attempt + 1,
                          error=type(exc).__name__)
            time.sleep(RETRY_DELAY)
    return None


def clean_num(s: str) -> float:
    try:
        return float(re.sub(r'[,%\s]', '', str(s)))
    except Exception:
        return 0.0


# ── 來源 A：MoneyDJ Basic0007B（全部持股） ────────────────────────
# v3.7：原 regex 強制 code=\d{4,6} 且後綴=.TW，會把全球型 ETF 的外股
# (009150.KS / AMD.US / 7203.JP / 0700.HK 等) 全部過濾掉。00988A 主動
# 統一全球創新原本 46 檔持股只抓到 13 檔台股，外股 30+ 整段消失。
# 修法：code 接受英數混合 (含 ADR/港股代號可能帶 0 前綴)、後綴接受任何
# 2 字母 ISO 市場碼 (TW/US/JP/KS/SH/HK/DE/L 等)。
_MDJ_DATE_RE = re.compile(r'資料日期[：:]\s*(\d{4})/(\d{2})/(\d{2})')
_MDJ_ROW_RE  = re.compile(
    r'etfid=([0-9A-Za-z]{1,7})\.([A-Z]{2})(?:&|&amp;)back=[0-9A-Za-z]+\.TW[^>]*>'
    r'\s*([^<]+?)\(\1\.\2\)\s*</a>'
    r'\s*</td>\s*'
    r'<td[^>]*>\s*([+-]?[\d.]+)\s*</td>\s*'
    r'<td[^>]*>\s*([+-]?[\d,]+|N/A|--)\s*</td>',
    re.DOTALL
)

_MDJ_ASSET_RE = re.compile(
    r'<td[^>]*class=["\']col05["\'][^>]*>\s*((?:(?!</td>).)+?)\s*</td>\s*'
    r'<td[^>]*class=["\']col06["\'][^>]*>\s*([+-]?[\d.]+)\s*</td>\s*'
    r'<td[^>]*class=["\']col07["\'][^>]*>\s*([+-]?[\d,]+|N/A|--)\s*</td>', re.DOTALL)


def _quantity(raw):
    return None if str(raw).strip() in ('N/A', '--', '') else int(clean_num(raw))


def _append_named_assets(holdings, text):
    """保留來源無股票代號的部位；名稱識別碼不能冒充可載入 K 線的股票。"""
    seen = {item['code'] for item in holdings}
    for match in _MDJ_ASSET_RE.finditer(text):
        if _MDJ_ROW_RE.search(match.group(0)):
            continue
        name = html.unescape(re.sub(r'<[^>]*>', '', match.group(1))).strip()
        code = 'asset:' + name
        if code in seen or name in ('合計', '總計', '小計'):
            continue
        seen.add(code)
        holdings.append({'rank': len(holdings) + 1, 'code': code, 'name': name,
                         'market': 'ASSET', 'instrumentType': 'named_asset',
                         'weight': round(clean_num(match.group(2)), 4),
                         'shares': _quantity(match.group(3))})

def fetch_moneydj_full(etf_id: str) -> tuple[list | None, str | None]:
    """MoneyDJ 全部持股頁；回傳 (holdings, data_date 'YYYY-MM-DD')"""
    url = f'https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={etf_id}.TW'
    referer = f'https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={etf_id}.TW'
    html_txt = http_get(url, referer)
    if not html_txt:
        return None, None

    date_m = _MDJ_DATE_RE.search(html_txt)
    data_date = f'{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}' if date_m else None

    holdings = []
    seen = set()
    for rank, m in enumerate(_MDJ_ROW_RE.finditer(html_txt), 1):
        code   = m.group(1).strip()
        market = m.group(2).strip()
        name   = html.unescape(m.group(3)).strip()
        weight = clean_num(m.group(4))
        shares = _quantity(m.group(5))
        key = f'{code}.{market}'
        if key in seen:
            continue
        seen.add(key)
        holdings.append({
            'rank':   rank,
            'code':   code,
            'market': market,                # v3.7 new: TW / US / JP / KS / HK / ...
            'name':   name,
            'weight': round(weight, 4),
            'shares': shares,
        })
    _append_named_assets(holdings, html_txt)
    return (holdings if holdings else None), data_date


# ── 來源 B：MoneyDJ Basic0007（前十大，做為 fallback） ────────────
def fetch_moneydj_top(etf_id: str) -> tuple[list | None, str | None]:
    url = f'https://www.moneydj.com/etf/x/basic/basic0007.xdjhtm?etfid={etf_id.lower()}.tw'
    referer = 'https://www.moneydj.com/etf/'
    html_txt = http_get(url, referer)
    if not html_txt:
        return None, None
    # 取「持股明細」段落（避開「持股分佈(依產業)」表）
    seg = html_txt
    pivot = re.search(r'持股明細', html_txt)
    if pivot:
        seg = html_txt[pivot.start():]
    date_m = re.search(_MDJ_DATE_RE, seg)
    data_date = f'{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}' if date_m else None

    holdings = []
    seen = set()
    for rank, m in enumerate(_MDJ_ROW_RE.finditer(seg), 1):
        code   = m.group(1).strip()
        market = m.group(2).strip()
        key = f'{code}.{market}'
        if key in seen:
            continue
        seen.add(key)
        holdings.append({
            'rank':   rank,
            'code':   code,
            'market': market,
            'name':   html.unescape(m.group(3)).strip(),
            'weight': round(clean_num(m.group(4)), 4),
            'shares': _quantity(m.group(5)),
        })
    _append_named_assets(holdings, seg)
    return (holdings if holdings else None), data_date


# ── 來源 C：TWSE ETFortfolio（被動 ETF 才有資料；主動 ETF 通常無） ─
def fetch_twse(stock_no: str, date: datetime.date) -> tuple[list | None, str | None]:
    url = ('https://www.twse.com.tw/rwd/zh/fund/ETFortfolio'
           f'?response=json&date={date.year}{date.month:02d}{date.day:02d}'
           f'&stockNo={urllib.parse.quote(stock_no)}')
    txt = http_get(url, 'https://www.twse.com.tw/')
    if not txt:
        return None, None
    try:
        data = json.loads(txt)
    except Exception:
        return None, None
    if data.get('stat') not in ('OK', 'ok'):
        return None, None
    fields = data.get('fields', [])
    rows   = data.get('data',   [])
    if not rows:
        return None, None

    def fi(keys):
        for i, f in enumerate(fields):
            if any(k in f for k in keys):
                return i
        return None
    ic = fi(['代號', '股票代號'])
    inm = fi(['名稱', '股票名稱'])
    isr = fi(['股數', '持股數量'])
    iwt = fi(['比例', '佔基金', '權重', '比率'])

    holdings = []
    for rank, row in enumerate(rows, 1):
        cd = row[ic].strip()   if ic  is not None and ic  < len(row) else ''
        nm = row[inm].strip()  if inm is not None and inm < len(row) else ''
        sr = clean_num(row[isr]) if isr is not None and isr < len(row) else 0
        wt = clean_num(row[iwt]) if iwt is not None and iwt < len(row) else 0
        if not cd or cd in ('合計', '總計', '小計'):
            continue
        holdings.append({
            'rank':   rank,
            'code':   cd,
            'name':   nm,
            'weight': round(wt, 4),
            'shares': int(sr),
        })
    raw_date = str(data.get('date') or '')
    try:
        provider_date = datetime.datetime.strptime(raw_date, '%Y%m%d').date().isoformat()
    except ValueError:
        try:
            provider_date = datetime.date.fromisoformat(raw_date).isoformat()
        except ValueError:
            provider_date = None
    return (holdings if holdings else None), provider_date


# ── 多來源彙整：依優先序嘗試 ─────────────────────────────────────
def fetch_one(etf_id: str, target_date: datetime.date):
    first_available = (None, None, None)
    sources = [('moneydj-full', lambda: fetch_moneydj_full(etf_id)),
               ('moneydj-top10', lambda: fetch_moneydj_top(etf_id)),
               ('twse', lambda: fetch_twse(etf_id, target_date))]
    for source, fetch in sources:
        h, d = fetch()
        try:
            parsed = datetime.date.fromisoformat(d or '')
            fresh = parsed <= target_date and etf_paths.business_day_age(parsed, target_date) <= 2
        except ValueError:
            fresh = False
        _source_event('source_parsed', source=source, providerDate=d,
                      rows=len(h or []), fresh=fresh)
        if h and fresh:
            return h, d, source
        if h and not first_available[0]:
            first_available = (h, d, source)
    # 未找到新來源時保留原始日期，由統一驗收決定，不以收集日補造。
    return first_available


# ── 主流程：抓一個指定日期的所有 ETF 並輸出 JSON ─────────────────
def _previous_snapshot_etf_count(history_dir: str, out_file: str) -> int:
    for prior in reversed(etf_paths.list_snapshot_files(history_dir)):
        if etf_paths.snapshot_date(prior) >= etf_paths.snapshot_date(out_file):
            continue
        check = etf_paths.inspect_snapshot(prior)
        count = int(check.get('etfCount') or 0)
        if check.get('valid') and count:
            return count
    return 0


def run(target_date: datetime.date, *, run_id=None) -> bool:
    trace = UpdateTrace(run_id or os.environ.get('ST_ETF_RUN_ID'))
    trace.record('command_received', targetDate=target_date.isoformat(), expectedCount=len(ETFS))
    try:
        return _run(target_date, trace)
    except Exception as exc:
        trace.finish(accepted=False, state='error', targetDate=target_date.isoformat(),
                     message='更新發生例外，原快照保留。', error=type(exc).__name__)
        raise


def _run(target_date: datetime.date, trace) -> bool:
    history_dir = str(etf_paths.resolve_history_dir(create=True))
    date_str = target_date.strftime('%Y-%m-%d')
    out_file = os.path.join(history_dir, f'top10_active_etf_holdings_{date_str}.json')
    previous_count = _previous_snapshot_etf_count(history_dir, out_file)
    minimum_count = max(
        etf_paths.MIN_HEALTHY_ETF_COUNT,
        math.ceil(previous_count * 0.60) if previous_count else 0,
        math.ceil(len(ETFS) * 0.60) if ETFS else 0,
    )
    invalid_existing = False
    retained = {}
    pending_codes = set(ETFS)

    expected_codes = sorted(ETFS)
    if os.path.exists(out_file):
        # Immutable daily snapshots may be skipped only when the existing file
        # is complete and belongs to the date encoded in its filename.  A
        # partial/corrupt file must fail visibly so the scheduler cannot report
        # a false success forever.
        check = etf_paths.inspect_snapshot(out_file)
        acceptance = etf_paths.snapshot_acceptance(
            check,
            # 追蹤器建立的是指定交易日快照；新鮮度必須以該交易日
            # 為基準，否則歷史快照會隨牆鐘前進而從通過變成失敗。
            # 即時健康頁仍由 etf_paths.history_status() 以今日評估。
            today=target_date,
            expected_codes=expected_codes,
            previous_etf_count=previous_count,
        )
        if acceptance.get('accepted') and not check.get('failedCodes'):
            trace.finish(accepted=True, state='already_current', targetDate=date_str,
                         succeededCount=check['etfCount'], expectedCount=len(ETFS),
                         failedCodes=check.get('failedCodes', []), acceptance=acceptance,
                         message='當日快照已通過驗收。')
            print(f'[{date_str}] 已存在且驗證通過，跳過。')
            return True
        if acceptance.get('accepted'):
            # 同日已通過的部分快照只重試缺漏，避免整池重抓及永久跳過失敗項。
            with open(out_file, encoding='utf-8') as handle:
                existing = json.load(handle)
            retained = {code: existing[code] for code in check['succeededCodes']}
            pending_codes -= set(retained)
            trace.record('retry_missing', retainedCount=len(retained), pendingCodes=sorted(pending_codes))
        invalid_existing = True
        print(
            f'[{date_str}] 既有快照有待補資料，保留原檔並重試：'
            f'etfs={check.get("etfCount", 0)} '
            f'problems={list(check.get("problems", [])) + list(acceptance.get("problems", []))}'
        )

    print(f'[{date_str}] 開始抓取 {len(ETFS)} 檔台灣 ETF 持股...')
    collected_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result: dict = {'date': date_str, 'updated': collected_at}
    result.update(retained)

    def worker(item):
        etf_id, (display_code, name) = item
        _request_context.trace, _request_context.code = trace, display_code
        holdings, data_date, source = fetch_one(etf_id, target_date)
        trace.record('etf_result', code=display_code, providerDate=data_date, source=source,
                     rows=len(holdings or []), state='received' if holdings else 'no_parsed_holdings')
        if holdings:
            print(f'  ✓ {display_code} {name}: {len(holdings)} 筆  (來源:{source} 資料日:{data_date})')
            return display_code, {
                'name':     name,
                # Provider date is evidence and must never be fabricated from
                # the local collection date when a provider parser changes.
                'date':     data_date,
                'collectedDate': date_str,
                'collectedAt': collected_at,
                'source':   source,
                'holdingsSchema': 2,
                'total':    len(holdings),
                'holdings': holdings,
            }
        print(f'  ✗ {display_code} {name}: 既有來源未取得可解析部位，請查看逐筆診斷')
        return display_code, None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(worker, item): item for item in ETFS.items() if item[0] in pending_codes}
        for fut in as_completed(futures):
            code, data = fut.result()
            if data:
                result[code] = data

    succeeded_codes = sorted(
        key for key, value in result.items()
        if key != 'date' and isinstance(value, dict)
        and isinstance(value.get('holdings'), list) and value['holdings']
    )
    etf_count = len(succeeded_codes)
    expected_count = len(expected_codes)
    success_ratio = etf_count / expected_count if expected_count else 0.0
    result['meta'] = {
        'scope': 'catalog-enabled-tw-etf',
        'expectedCodes': expected_codes,
        'expectedCount': expected_count,
        'succeededCodes': succeeded_codes,
        'failedCodes': sorted(set(expected_codes) - set(succeeded_codes)),
        'succeededCount': etf_count,
        'successRatio': round(success_ratio, 4),
        'catalogFingerprint': etf_paths.catalog_fingerprint(expected_codes),
    }
    candidate_check = etf_paths.inspect_snapshot_payload(result, expected_date=target_date)
    candidate_acceptance = etf_paths.snapshot_acceptance(
        candidate_check,
        today=target_date,
        expected_codes=expected_codes,
        previous_etf_count=previous_count,
    )
    from collections import Counter
    diagnostics = {
        'targetDate': date_str, 'succeededCount': etf_count, 'expectedCount': expected_count,
        'failedCodes': result['meta']['failedCodes'], 'acceptance': candidate_acceptance,
        'providerDateCounts': dict(Counter(str(d) for d in candidate_check['providerDates'])),
        'etfs': {code: {'providerDate': result[code]['date'], 'source': result[code]['source'],
                        'rows': len(result[code]['holdings'])} for code in succeeded_codes},
    }
    trace.record('candidate_checked', **diagnostics)
    if not candidate_acceptance.get('accepted'):
        trace.finish(accepted=False, state=candidate_acceptance['state'],
                     message='快照未通過驗收，沿用原資料；請查看拒絕原因與來源日期。', **diagnostics)
        print(
            f'[{date_str}] 快照驗收未通過（{candidate_acceptance["state"]}）：成功 {etf_count} 檔，'
            f'最低需 {minimum_count} 檔（前期 {previous_count or "無"}）；'
            f'拒絕原因 {candidate_acceptance.get("problems", [])}'
        )
        return False

    if invalid_existing:
        quarantine = out_file + ('.previous-' if retained else '.invalid-') + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        shutil.copy2(out_file, quarantine)
        print(f'[{date_str}] 舊快照已保留：{quarantine}')
    atomic_write_json(out_file, result, backup=False)
    trace.finish(accepted=True, state='updated', message='快照已更新；來源缺漏另列，不代表全部成功。',
                 **diagnostics)
    print(f'\n[{date_str}] 完成！{etf_count}/{len(ETFS)} 檔 → {out_file}')
    return True


# ── 批次補抓 ──────────────────────────────────────────────────────
def backfill(days: int) -> bool:
    """最新持股來源不能回補歷史，避免把同一份資料寫成多日觀測。"""
    if days != 1:
        print('無法回補歷史：目前來源只提供最新持股；原歷史檔保留，請靠每日更新累積。')
        return False
    return run(datetime.date.today())


# ── 入口 ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='台股主動ETF持股爬蟲 (MoneyDJ)')
    parser.add_argument('--date', help='指定日期 YYYY-MM-DD (預設今天)')
    parser.add_argument('--backfill', type=int, metavar='N',
                        help='相容參數：僅 N=1 可更新當日；不支援歷史回補')
    args = parser.parse_args()

    if args.backfill:
        success = backfill(args.backfill)
    elif args.date:
        day = datetime.date.fromisoformat(args.date)
        if day != datetime.date.today():
            print('無法指定歷史或未來收集日：目前來源只提供最新持股，原歷史檔保留。')
            success = False
        else:
            success = run(day)
    else:
        success = run(datetime.date.today())
    raise SystemExit(0 if success else 2)
