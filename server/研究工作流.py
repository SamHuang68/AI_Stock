"""每日研究的唯讀快照與差異；不抓來源、不建立資料庫、不發布行情。"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from typing import Any

VERSION = 'research-workflow-v1'
PUBLIC_FIELDS = ('asOf', 'market', 'regime', 'dataQuality', 'marketState', 'keyLevels',
                 'scenario', 'sectorFlow', 'optionsStructure', 'earlyWarnings',
                 'divergences', 'confirmation', 'invalidation', 'breadthTrend', 'basisContext',
                 'snapshotId', 'revision', 'inputHash', 'rulesDigest', 'model',
                 'validUntil', 'expiresAt', 'publishedAt', 'persistence', 'contractVersion')

# 比較研究內容，而非每次發布的身分或來源時鐘；交易日與事件效期仍有語意。
STATE_FIELDS = (
    ('regime', '市場情境'), ('dataQuality', '資料品質'), ('keyLevels', '關鍵價位'),
    ('confirmation', '確認條件'), ('invalidation', '失效條件'), ('earlyWarnings', '預警狀態'),
    ('scenario', '情境依據'), ('marketState', '市場盤別狀態'), ('market', '市場觀測'),
    ('sectorFlow', '產業資金'), ('optionsStructure', '選擇權結構'),
    ('divergences', '分歧證據'), ('breadthTrend', '市場廣度'), ('basisContext', '期現基準'),
)
COMPARISON_METADATA = frozenset((
    'snapshotId', 'revision', 'inputHash', 'inputDigest', 'rulesDigest', 'digest', 'observationKey',
    'contractVersion', 'version', 'engineVersion', 'policyVersion',
    'asOf', 'sourceAsOf', 'updatedAt', 'builtAt', 'publishedAt', 'generatedAt',
    'fetchedAt', 'checkedAt', 'evaluatedAt', 'lastObservedAt', 'computedAt',
    'oldestSourceAsOf', 'newestSourceAsOf', 'ageSeconds',
))


def _meaningful(value: Any) -> Any:
    """只用於比較；回傳的前後證據仍完整保留，不能改寫快照。"""
    if isinstance(value, dict):
        return {key: _meaningful(item) for key, item in value.items()
                if key not in COMPARISON_METADATA and not (key == 'model' and isinstance(item, str))}
    if isinstance(value, list):
        return [_meaningful(item) for item in value]
    return value


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def _snapshot(row: tuple | None) -> dict | None:
    if not row:
        return None
    revision, identifier, raw = row
    value = json.loads(raw)
    if (value.get('snapshotId') != identifier or value.get('revision') != revision or
            value.get('persistence') != 'committed'):
        raise ValueError('快照識別與已提交內容不一致，停止研究讀取')
    result = {key: value[key] for key in PUBLIC_FIELDS if key in value}
    # 個人化投組與風險設定不屬於共用市場研究；原始資料不在此修改。
    evidence = []
    seen = set()
    for item in value.get('evidence') or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('id') or '')
        if not key or key in seen or key.startswith(('portfolio.', 'owner.', 'riskProfile.')):
            continue
        seen.add(key)
        safe = {k: item[k] for k in ('id', 'metric', 'value', 'comparison', 'source',
                'marketScope', 'session', 'asOf', 'reference', 'quality', 'authority') if k in item}
        safe['evidenceId'] = identifier + ':' + key
        safe['digest'] = digest(safe)
        evidence.append(safe)
    result['evidence'] = evidence
    result['digest'] = digest(result)
    return result


def differences(previous: dict | None, current: dict | None) -> list[dict]:
    if not previous or not current:
        return []
    changes = []
    for key, title in STATE_FIELDS:
        a, b = previous.get(key), current.get(key)
        if encode(_meaningful(a)) != encode(_meaningful(b)):
            changes.append({'key': key, 'title': title, 'kind': 'state', 'before': a, 'after': b,
                            'fromSnapshotId': previous['snapshotId'], 'toSnapshotId': current['snapshotId']})
    a = {x['id']: x for x in previous.get('evidence', [])}
    b = {x['id']: x for x in current.get('evidence', [])}
    for key in sorted(a.keys() | b.keys()):
        before, after = a.get(key), b.get(key)
        fields = ('metric', 'value', 'quality', 'source', 'comparison', 'marketScope', 'session', 'reference', 'authority')
        material = (encode(_meaningful({k: (before or {}).get(k) for k in fields})) !=
                    encode(_meaningful({k: (after or {}).get(k) for k in fields})))
        if not material and (before or {}).get('asOf') == (after or {}).get('asOf'):
            continue
        changes.append({'key': key, 'title': str((after or before).get('metric') or key),
                        'kind': 'evidence' if material else 'source_time',
                        'before': before, 'after': after,
                        'fromSnapshotId': previous['snapshotId'], 'toSnapshotId': current['snapshotId']})
    return changes


def workspace(path: str | Path, *, current_id: str = '', previous_id: str = '',
              before: int | None = None, limit: int = 30) -> dict:
    """兩個快照及歷史選單在同一個 SQLite 讀取交易內取得。"""
    for identifier in (current_id, previous_id):
        if identifier and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', identifier):
            raise ValueError('快照編號格式不正確')
    if before is not None and before < 1:
        raise ValueError('歷史游標格式不正確')
    if not 1 <= limit <= 100:
        raise ValueError('每頁快照數需介於 1 與 100')
    out = {'ok': True, 'version': VERSION, 'current': None, 'previous': None,
           'changes': [], 'history': [], 'nextBefore': None,
           'note': '唯讀已提交市場快照；研究筆記儲存在目前瀏覽器，不與其他來源自動同步。'}
    if not Path(path).is_file():
        out['note'] = '尚無已提交市場快照；請由更新工作中心更新。'
        return out
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        conn.execute('BEGIN')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_commits'").fetchone():
            return out
        query = 'SELECT revision,snapshot_id,context_json FROM decision_commits'
        row = conn.execute(query + (' WHERE snapshot_id=?' if current_id else '') +
                           ' ORDER BY revision DESC LIMIT 1', (current_id,) if current_id else ()).fetchone()
        if current_id and not row:
            raise LookupError('指定快照已不在伺服器保留範圍；可使用已保存的研究紀錄回顧')
        current = _snapshot(row)
        previous = None
        if current:
            previous_row = conn.execute(query + (' WHERE snapshot_id=?' if previous_id else ' WHERE revision<?') +
                ' ORDER BY revision DESC LIMIT 1', (previous_id,) if previous_id else (current['revision'],)).fetchone()
            if previous_id and not previous_row:
                raise LookupError('找不到指定比較快照')
            previous = _snapshot(previous_row)
            if previous and previous['revision'] >= current['revision']:
                raise ValueError('比較快照必須早於目前快照')
        rows = conn.execute(query + (' WHERE revision<?' if before else '') +
                            ' ORDER BY revision DESC LIMIT ?', ((before, limit + 1) if before else (limit + 1,))).fetchall()
        history = []
        for item in rows[:limit]:
            snap = _snapshot(item)
            history.append({key: snap.get(key) for key in ('snapshotId', 'revision', 'asOf', 'publishedAt', 'digest')})
    out.update(current=current, previous=previous, changes=differences(previous, current), history=history,
               nextBefore=history[-1]['revision'] if len(rows) > limit else None)
    return out


def subject_symbol(value: str) -> str:
    symbol = str(value or '').strip().upper()
    symbol = re.sub(r'\.(?:TW|TWO)$', '', symbol)
    if not re.fullmatch(r'\d{4,6}[A-Z]?', symbol):
        raise ValueError('請提供有效台股或 ETF 代號')
    return symbol


def _public_fields(value: Any, fields: tuple) -> dict:
    # 既有公開欄位都是純量；不可藉同名欄位夾入匯入紀錄或私人巢狀物件。
    return {key: value[key] for key in fields if isinstance(value, dict) and key in value
            and (value[key] is None or isinstance(value[key], (str, int, float, bool)))}


def _read_public_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else None
    except (OSError, ValueError):
        return None


def capture_subject_sources(runtime: Any, symbol: str) -> dict:
    """擷取已載入公開快取；不呼叫 get、更新器、抓網函式或載入完整 server。"""
    from copy import deepcopy
    from 台股基本面 import REVENUE_DATASETS, INCOME_DATASETS
    symbol = subject_symbol(symbol)
    allowed = set(REVENUE_DATASETS) | {item[0] for item in INCOME_DATASETS}
    saved = dict(getattr(runtime, '_openapi_ds', {}) or {})
    datasets = {}
    for name in allowed:
        entry = saved.get(name)
        if isinstance(entry, (list, tuple)) and len(entry) > 1 and isinstance(entry[1], dict):
            row = entry[1].get(symbol)
            if isinstance(row, dict):
                datasets[name] = deepcopy(row)
    revenues = []
    for key, entry in dict(getattr(runtime, '_mops_rev_cache', {}) or {}).items():
        if isinstance(entry, (list, tuple)) and len(entry) > 1 and isinstance(entry[1], dict):
            row = entry[1].get(symbol)
            if isinstance(row, dict):
                revenues.append({'market': str(key[0]) if isinstance(key, tuple) and key else '', 'row': deepcopy(row)})
    cached = []
    cache = getattr(runtime, '_cache', None)
    if cache is not None and hasattr(cache, '_lock') and hasattr(cache, '_d'):
        # LRU.get 會刪掉過期項目。此處只複製所需既有值，保持舊資料與順序。
        with cache._lock:
            cached = [(key, entry[0]) for key, entry in cache._d.items()
                      if str(key).startswith((f'fund:TW:{symbol}:', f'chip:{symbol}:'))]
    payloads = {}
    for key, raw in sorted(cached):
        try:
            value = json.loads(raw) if isinstance(raw, (bytes, str)) else deepcopy(raw)
            if isinstance(value, dict):
                payloads['fundamentals' if key.startswith('fund:') else 'flows'] = value
        except (ValueError, TypeError):
            continue
    sectors = deepcopy(getattr(runtime, '_TW_SECTORS', {}) or {})
    # 新聞僅採已載入模組，匯入或呼叫 build_flash 都不是唯讀快取擷取。
    import sys
    flash_module = sys.modules.get('market_flash')
    flash = getattr(flash_module, '_cache', {}) if flash_module else {}
    news = deepcopy((flash.get('payload') or {}).get('items') or [])
    return {'datasets': datasets, 'revenues': revenues, 'cached': payloads,
            'sectors': sectors, 'news': news}


def build_subject(symbol: str, database: str | Path, *, sources: dict | None = None,
                  chip_directory: str | Path | None = None, etf_directory: str | Path | None = None,
                  catalog_path: str | Path | None = None) -> dict:
    """將已保存公開資料整理為同一研究證據包；所有不足保持未知且完全不更新。"""
    from 台股基本面 import REVENUE_DATASETS, INCOME_DATASETS, revenue_record, income_record, source_date, number
    from etf_paths import list_snapshot_files
    symbol = subject_symbol(symbol)
    sources = sources or {}
    root = Path(database).parent
    domains = {name: {'availability': 'unknown', 'asOf': None, 'source': [], 'evidence': [],
                     'reason': '尚無可核對的已保存公開資料', 'freshness': 'historical_or_unknown'}
               for name in ('fundamentals', 'flows', 'supplyChainNews', 'peersThemes', 'etfResearch')}

    def evidence(domain: str, kind: str, value: Any, as_of=None, source=None):
        row = {'domain': domain, 'kind': kind, 'symbol': symbol, 'asOf': as_of,
               'source': source or '來源未記錄', 'value': value}
        row['digest'] = digest(row)
        row['evidenceId'] = 'subject:' + symbol + ':' + domain + ':' + row['digest']
        domains[domain]['evidence'].append(row)

    cached = sources.get('cached') or {}
    datasets = sources.get('datasets') or {}
    revenue = None
    for name in REVENUE_DATASETS:
        if isinstance(datasets.get(name), dict):
            revenue = revenue_record(datasets[name], name)
            if revenue:
                break
    if not revenue:
        candidates = [revenue_record(item.get('row'), 'MOPS:' + str(item.get('market') or ''))
                      for item in sources.get('revenues', []) if isinstance(item, dict)]
        candidates = [item for item in candidates if item]
        revenue = max(candidates, key=lambda item: item.get('periodLabel') or '') if candidates else None
    fund = cached.get('fundamentals') or {}
    if revenue is None and isinstance(fund.get('revenue'), dict):
        revenue = _public_fields(fund['revenue'], ('period', 'periodLabel', 'monthRev', 'yoyPct', 'momPct',
            'cumRev', 'cumYoyPct', 'unit', 'unitMultiplier', 'source', 'sourceName', 'sourceDate', 'expectedPeriod', 'priorPeriod'))
    income = None
    for name, kind, _ in INCOME_DATASETS:
        income = income_record(datasets.get(name), kind, name)
        if income:
            break
    if income is None and isinstance(fund.get('income'), dict):
        income = _public_fields(fund['income'], ('period', 'year', 'quarter', 'industry', 'industryCode',
            'source', 'sourceName', 'sourceDate', 'unit', 'unitMultiplier', 'epsUnit', 'sales', 'eps', 'netIncome',
            'parentNetIncome', 'grossMargin', 'opMargin', 'netMargin', 'marginStatus', 'marginNote'))
    for kind, value in (('revenue', revenue), ('income', income)):
        if value:
            evidence('fundamentals', kind, value, value.get('sourceDate'), value.get('source'))

    # 法人檔名只是保存位置，只有每股列的 sourceDate 才能作資料日。
    chips = []
    directory = Path(chip_directory) if chip_directory is not None else root / 'chip_history'
    for path in sorted(directory.glob('*.json')) if directory.is_dir() else []:
        if not re.fullmatch(r'\d{8}\.json', path.name):
            continue
        value = _read_public_json(path)
        row = value.get(symbol) if isinstance(value, dict) else None
        if isinstance(row, dict):
            chips.append(row)
    inst = (cached.get('flows') or {}).get('inst')
    if isinstance(inst, dict):
        chips.append(inst)
    seen = set()
    for raw in chips:
        row = {key: number(raw.get(key)) for key in ('foreign', 'trust', 'dealer', 'total')}
        if all(value is None for value in row.values()):
            continue
        row.update(sourceDate=source_date(raw.get('sourceDate')), source=raw.get('source'), unit=raw.get('unit'))
        marker = digest(row)
        if marker not in seen:
            seen.add(marker)
            evidence('flows', 'institutional', row, row['sourceDate'], row['source'])

    for raw in sources.get('news', []):
        if not isinstance(raw, dict) or str(raw.get('code') or '').removesuffix('.TW').removesuffix('.TWO') != symbol or raw.get('mkt', 'TW') != 'TW':
            continue
        row = _public_fields(raw, ('time', 'ts', 'title', 'cat', 'code', 'name', 'mkt', 'url', 'source', 'clause'))
        stamp = None
        try:
            if number(row.get('ts')) and number(row['ts']) > 0:
                stamp = datetime.fromtimestamp(float(row['ts']), timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
        evidence('supplyChainNews', 'company_news', row, stamp, row.get('source'))

    sectors = sources.get('sectors') or {}
    classification = {str(code): value for code, value in (sectors.get('map') or {}).items()
                      if re.fullmatch(r'\d{4,6}[A-Z]?', str(code)) and isinstance(value, str)}
    industry = classification.get(symbol)
    if industry:
        members = sorted(code for code, name in classification.items() if name == industry)
        peer_rows = []
        if Path(database).is_file():
            with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
                conn.execute('BEGIN')
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if {'bars', 'bar_quality'} <= tables:
                    for code in members:
                        prices = conn.execute('SELECT b.close,q.session_date,q.source,q.price_basis,q.issues '
                            'FROM bars b JOIN bar_quality q ON b.market=q.market AND b.symbol=q.symbol AND b.ts=q.ts '
                            "WHERE b.market='TW' AND b.symbol=? ORDER BY b.ts DESC LIMIT 2", (code,)).fetchall()
                        def issues(value):
                            try:
                                parsed = json.loads(value) if isinstance(value, str) else value
                                return parsed if isinstance(parsed, list) else ['品質註記未提供']
                            except ValueError:
                                return ['品質註記無法解析']
                        peer_rows.append({'symbol': code, 'industry': industry, 'market': 'TW', 'currency': 'TWD',
                                          'observations': [{'close': row[0], 'asOf': row[1], 'source': row[2], 'priceBasis': row[3], 'issues': issues(row[4])} for row in prices]})
        by_code = {row['symbol']: row for row in peer_rows}
        reference = (by_code.get(symbol) or {}).get('observations') or []
        for code in members:
            row = by_code.get(code) or {'symbol': code, 'industry': industry, 'market': 'TW', 'currency': 'TWD', 'observations': []}
            prices = row['observations']
            comparable = len(prices) == len(reference) == 2 and all(
                p['asOf'] and p['source'] and p['priceBasis'] and
                p['asOf'] == q['asOf'] and p['priceBasis'] == q['priceBasis'] and p['source'] == q['source'] and
                not p['issues'] and not q['issues'] and number(p['close']) is not None and p['close'] > 0 and
                number(q['close']) is not None and q['close'] > 0 for p, q in zip(prices, reference)) and prices[0]['asOf'] > prices[1]['asOf']
            row['comparable'] = comparable
            row['changePct'] = round((prices[0]['close'] / prices[1]['close'] - 1) * 100, 6) if comparable else None
            row['comparisonReason'] = ('同市場、幣別、來源、日期與價格基準的收盤價變化；未還原權息，不代表投資報酬' if comparable else '日期、來源、價格基準或品質不足，不列可比報酬')
            evidence('peersThemes', 'same_industry', row, prices[0]['asOf'] if prices else None,
                     prices[0]['source'] if prices else '既有官方產業分類快取')
        domains['peersThemes']['classificationAsOf'] = None
        domains['peersThemes']['classificationNote'] = '分類快取取得日不是來源揭露日；同產業不代表直接競爭或供應關係。'

    catalog = _read_public_json(Path(catalog_path) if catalog_path is not None else root / 'etf_catalog.json')
    catalog_row = None
    if isinstance(catalog, dict):
        for group in catalog.get('categories') or []:
            for row in group.get('etfs') or []:
                if isinstance(row, dict) and row.get('code') == symbol and row.get('market', 'TW') == 'TW':
                    catalog_row = {'code': symbol, 'name': row.get('name'), 'market': 'TW', 'category': group.get('name')}
    if catalog_row:
        evidence('etfResearch', 'catalog_classification', catalog_row, None, '既有 ETF 分類庫（分類維護日不是持股揭露日）')
    etf_found = False
    # 呼叫者提供既有共享資料目錄；缺少目錄時不自動建立或啟動追蹤器。
    files = list_snapshot_files(etf_directory) if etf_directory is not None else []
    for path in files:
        payload = _read_public_json(path)
        raw = payload.get(symbol) if isinstance(payload, dict) else None
        if not isinstance(raw, dict) or not isinstance(raw.get('holdings'), list):
            continue
        etf_found = True
        holdings = [_public_fields(item, ('rank', 'code', 'name', 'shares', 'weight', 'market', 'value', 'weightPct'))
                    for item in raw['holdings'] if isinstance(item, dict)]
        value = {'name': raw.get('name'), 'sourceDate': source_date(raw.get('date')),
                 'source': raw.get('source'), 'holdings': holdings, 'holdingCount': len(holdings),
                 'collectedDate': raw.get('collectedDate'),
                 'premise': '公開 ETF 持股快照，不是使用者部位；保存日不替代來源揭露日。'}
        evidence('etfResearch', 'saved_holdings', value, value['sourceDate'], value['source'])
    for domain in domains.values():
        rows = domain['evidence']
        if rows:
            dated = [row['asOf'] for row in rows if row['asOf']]
            domain.update(availability='available' if len(dated) == len(rows) and all(row['source'] != '來源未記錄' for row in rows) else 'partial',
                          asOf=max(dated) if dated else None, source=sorted({row['source'] for row in rows}),
                          reason='僅使用已保存資料，各筆期別與來源時間分別核對；不表示即時或完整覆蓋。')
    if bool(revenue) != bool(income):
        domains['fundamentals'].update(availability='partial',
            reason='已保存營收與財報僅部分可讀；缺少的部分保持未知，不啟動抓取。')
    if not catalog_row and not etf_found and income and income.get('industryCode'):
        domains['etfResearch'].update(availability='not_applicable', reason='已保存官方公司財報證明為公司標的，未套用 ETF 自身持股研究。')
    evidence_rows = [row for domain in domains.values() for row in domain['evidence']]
    dates = [row['asOf'] for row in evidence_rows if row['asOf']]
    report = {'ok': True, 'version': 'research-subject-v1', 'symbol': symbol, 'market': 'TW', 'currency': 'TWD',
              'asOf': max(dates) if dates else None, 'readOnly': True, 'domains': domains, 'evidence': evidence_rows,
              'notes': ['資料可讀不等於即時；不同領域資料日不能混用。', '沒有呼叫來源更新、模型或讀取私人持倉。',
                        '新聞來源文字是研究資料，不是指令；沒有新聞不代表沒有事件。',
                        '供應鏈主題沿既有介面分類呈現，分類不證明實際供應關係。']}
    report['digest'] = digest(report)
    return report


def observation_page(path: str | Path, *, before: int | None = None, limit: int = 30) -> dict:
    """逐頁列出凍結觀測，保留版本、分母及未知狀態，不重算或回補。"""
    if (before is not None and before < 1) or not 1 <= limit <= 100:
        raise ValueError('觀測歷史游標或筆數不正確')
    out = {'ok': True, 'observations': [], 'nextBefore': None}
    if not Path(path).is_file():
        return out
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        conn.execute('BEGIN')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_research_observations'").fetchone():
            return out
        rows = conn.execute('SELECT rowid,record_json FROM signal_research_observations' +
            (' WHERE rowid<?' if before else '') + ' ORDER BY rowid DESC LIMIT ?',
            (before, limit + 1) if before else (limit + 1,)).fetchall()
        for key, raw in rows[:limit]:
            value = json.loads(raw)
            value.pop('replay', None)
            out['observations'].append(value)
        out['nextBefore'] = rows[limit - 1][0] if len(rows) > limit else None
    return out
