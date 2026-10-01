#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stock Terminal 本機 MCP 伺服器（stdio，唯讀，純標準函式庫）。

讓 Claude Desktop／Claude Code／Cowork（含 Claude for Financial Services 的
equity-research 技能，例如 /morning-note、/thesis、/catalysts）直接讀取本機 ST 的
規則化結果：個股體檢、自選股總表、訊號成績單、市場決策情境與關鍵價位。

* 只呼叫本機 ST HTTP API（預設 http://127.0.0.1:18432）；部分既有後端讀取會補抓並更新快取。
* 回傳的是規則產生的事實與歷史統計；工具說明明確要求模型引用證據編號、不得給買賣指令。

設定（擇一）
------------
Claude Code：
    claude mcp add stock-terminal -- python /path/to/AI_Stock/scripts/st_mcp_server.py
Claude Desktop（claude_desktop_config.json）：
    {"mcpServers": {"stock-terminal": {"command": "python",
      "args": ["C:\\\\path\\\\to\\\\AI_Stock\\\\scripts\\\\st_mcp_server.py"]}}}
環境變數：ST_MCP_BASE_URL（預設 http://127.0.0.1:$ST_PORT，ST_PORT 預設 18432）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

SERVER_NAME = 'stock-terminal'
SERVER_VERSION = '1.1.0'
RESULT_VERSION = 'st-mcp-result/1'
SUPPORTED_PROTOCOLS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
TIMEOUT = float(os.environ.get('ST_MCP_TIMEOUT', '60'))
_SYM_RE = re.compile(r'^[A-Za-z0-9^][A-Za-z0-9.\-^]{0,14}$')

INSTRUCTIONS = (
    'Stock Terminal 提供臺股與美股的規則化事實及歷史研究，並非投資建議。'
    '請引用證據編號或欄位名稱，精確保留數字與失效條件。gate 為 insufficient 時說明樣本不足；'
    'edgeVerdict 為 descriptive 時只能說明歷史差距，不能宣稱已有優勢。'
    '情境研究的季度區間屬探索結果，未校正多重比較；候選仍待前瞻驗證。'
    '一般歷史快照重建不能稱為當年實際留存的點時證據。不得產生買賣指令或目標價。臺灣以紅色表示上漲、綠色表示下跌。'
)


def base_url() -> str:
    env = os.environ.get('ST_MCP_BASE_URL')
    value = (env or f"http://127.0.0.1:{os.environ.get('ST_PORT', '18432')}").rstrip('/')
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('ST_MCP_BASE_URL 必須是無憑證與路徑的本機 HTTP 位址')
    parsed.port  # 驗證連接埠，不把設定中的敏感內容回傳給客戶端。
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, '不允許重新導向', headers, fp)


def http_json(path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    if body is not None:
        raise ValueError('MCP 僅允許讀取')
    url = base_url() + path
    req = urllib.request.Request(url, method='GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode('utf-8'))


class BackendResult:
    """保留原始後端中繼資料；精簡文字輸出不改形狀。"""
    def __init__(self, data, backend):
        self.data, self.backend = data, backend


class UnknownToolError(Exception):
    pass


def _stock_query(args, sym):
    query = {'sym': sym, 'market': _market_arg(args, sym)}
    if args.get('cacheOnly'):
        query['cacheOnly'] = '1'
    return urllib.parse.urlencode(query)


# ── 精簡輸出（控制回傳給模型的 token 量）─────────────────────────
def _stats_brief(stats: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in (stats or {}).get('horizons') or []:
        row = {'horizon': r.get('horizon'), 'n': r.get('n'), 'gate': r.get('gate')}
        if r.get('gate') == 'ok':
            row.update({k: r.get(k) for k in ('upRatio', 'baseUpRatio', 'ci95Pts', 'edgePts',
                                              'edgeVerdict', 'medianRet', 'medianAdverse')})
        out.append(row)
    return out


def compact_health(d: Dict[str, Any]) -> Dict[str, Any]:
    if not d.get('ok'):
        return {k: d.get(k) for k in ('symbol', 'market', 'ok', 'reason', 'message', 'dataWarning')}
    h = d.get('health') or {}
    return {
        'symbol': d.get('symbol'), 'market': d.get('market'), 'asOf': d.get('asOf'),
        'provisional': (d.get('session') or {}).get('provisional'),
        'staleDays': d.get('staleDays'), 'dataWarning': d.get('dataWarning'),
        'summary': (h.get('summary') or {}).get('sentence'),
        'overall': (h.get('summary') or {}).get('overall'),
        'lights': [{'key': l['key'], 'label': l['label'], 'state': l['state'], 'tag': l['tag'],
                    'plain': l['plain'], 'evidenceId': l['evidenceId']} for l in h.get('lights') or []],
        'invalidation': h.get('invalidation'),
        'events': [{
            'signalId': e['signalId'], 'label': e['label'], 'direction': e['direction'],
            'date': e['date'], 'status': e['status'], 'statusLabel': e['statusLabel'],
            'provisional': e.get('provisional'), 'detail': e['detail'], 'meaning': e['plain'],
            'invalidation': e.get('invalidation'), 'evidenceId': e['evidenceId'],
            'stockStats': _stats_brief(e.get('stats')),
            'marketStats': _stats_brief(e.get('pooledStats')),
        } for e in d.get('events') or []],
        'indicators': d.get('indicators'),
        'engine': d.get('engine'), 'disclaimer': d.get('disclaimer'),
    }


def compact_decision(d: Dict[str, Any]) -> Dict[str, Any]:
    env = d.get('actionEnvelope') or {}
    levels = ((d.get('keyLevels') or {}).get('levels') or {})
    return {
        'asOf': d.get('asOf'), 'regime': d.get('regime'), 'posture': env.get('posture'),
        'allowed': list(env.get('allowed') or [])[:4], 'restricted': list(env.get('restricted') or [])[:4],
        'prohibited': list(env.get('prohibited') or [])[:4],
        'confirmation': list(d.get('confirmation') or [])[:3],
        'invalidation': list(d.get('invalidation') or [])[:3],
        'levels': {k: levels.get(k) for k in ('r1', 'pivot', 's1') if k in levels},
        'dataQuality': d.get('dataQuality'),
    }


# ── 工具 ─────────────────────────────────────────────────────
def _symbol_arg(args: Dict[str, Any], key: str = 'symbol') -> str:
    sym = str(args.get(key) or '').strip().upper()
    if not _SYM_RE.match(sym):
        raise ValueError(f'invalid {key}: use a ticker such as 2330, 00631L or AAPL')
    return sym


def _market_arg(args: Dict[str, Any], sym: str = '') -> str:
    m = str(args.get('market') or '').strip().upper()
    if m in ('TW', 'US'):
        return m
    return 'TW' if sym[:1].isdigit() or sym.startswith('^TW') else 'US'


def tool_stock_health(args):
    sym = _symbol_arg(args)
    d = http_json('/stock-signals?' + _stock_query(args, sym))
    return BackendResult(compact_health(d), d)


def tool_stock_evidence(args):
    sym = _symbol_arg(args)
    d = http_json('/stock-signals?' + _stock_query(args, sym))
    return BackendResult({'symbol': d.get('symbol'), 'asOf': d.get('asOf'), 'ok': d.get('ok'),
            'evidence': d.get('evidence') or {},
            'citationRule': 'Every sentence you write must cite one or more of these evidence ids; '
                            'numbers must appear in the cited evidence.'}, d)


def tool_watchlist_health(args):
    raw = str(args.get('symbols') or '').strip()
    if not raw:
        raise ValueError('symbols is required, e.g. "2330,2454,AAPL:US"')
    parts = raw.split(',')
    if len(parts) > 40:
        raise ValueError('自選股最多 40 檔')
    for part in parts:
        ticker, sep, market = part.strip().partition(':')
        _symbol_arg({'symbol': ticker})
        if sep and market.upper() not in ('TW', 'US'):
            raise ValueError('市場僅支援 TW 或 US')
    query = {'syms': raw}
    if args.get('cacheOnly'):
        query['cacheOnly'] = '1'
    d = http_json('/stock-signals/batch?' + urllib.parse.urlencode(query))
    return BackendResult({'items': d.get('items') or [], 'disclaimer': d.get('disclaimer')}, d)


def tool_signal_scoreboard(args):
    market = 'US' if str(args.get('market') or '').strip().upper() == 'US' else 'TW'
    d = http_json('/stock-signals/pooled?' + urllib.parse.urlencode({'market': market}))
    if not d.get('available'):
        return BackendResult({'market': market, 'available': False,
                'hint': 'Pooled statistics not computed yet; open ST 體檢 tab → 訊號成績單 → 開始計算.'}, d)
    rows = [{'signalId': r['signalId'], 'label': r['label'], 'direction': r['direction'],
             'horizons': _stats_brief({'horizons': r['horizons']}),
             'research5d': next((h.get('all') for h in (r.get('research') or {}).get('horizons', [])
                                if h.get('horizon') == 5), None)} for r in d.get('scoreboard') or []]
    out = {k: d.get(k) for k in ('market', 'symbols', 'window', 'generatedAt', 'minSample', 'caveats', 'research')}
    out['scoreboard'] = rows
    return BackendResult(out, d)


def tool_signal_catalog(args):
    return http_json('/stock-signals/catalog')


def tool_market_decision(args):
    d = http_json('/decision/context?' + urllib.parse.urlencode(
        {'market': str(args.get('market') or 'TW').upper()}))
    return BackendResult(compact_decision(d), d)


def tool_key_levels(args):
    sym = str(args.get('symbol') or '^TWII').strip()
    if sym not in ('^TWII', '^TWOII', '__TXF__'):
        raise ValueError('關鍵價位僅支援 ^TWII、^TWOII、__TXF__')
    return http_json('/key-levels?' + urllib.parse.urlencode({'symbol': sym}))


_SYMBOL_SCHEMA = {'type': 'string', 'description': 'Ticker, e.g. 2330, 00631L, AAPL'}
_MARKET_SCHEMA = {'type': 'string', 'enum': ['TW', 'US'],
                  'description': 'Optional; inferred from the ticker (digits → TW)'}

TOOLS: List[Dict[str, Any]] = [
    {'name': 'st_stock_health', 'handler': tool_stock_health,
     'title': 'Stock health check (Stock Terminal)',
     'description': 'Rule-based health card for one stock: five lights (trend, momentum, volume, '
                    'chip/institutional flow, risk), a plain-language summary, the invalidation level, '
                    'and signal events from the last 10 sessions with per-stock and same-market '
                    'historical statistics (gated by sample size).',
     'inputSchema': {'type': 'object', 'properties': {'symbol': _SYMBOL_SCHEMA, 'market': _MARKET_SCHEMA},
                     'required': ['symbol'], 'additionalProperties': False}},
    {'name': 'st_stock_evidence', 'handler': tool_stock_evidence,
     'title': 'Citable evidence map for one stock',
     'description': 'The flat evidence map behind the health card (ids → label/value/text/asOf). '
                    'Use it when writing a note or thesis so every claim can cite an evidence id.',
     'inputSchema': {'type': 'object', 'properties': {'symbol': _SYMBOL_SCHEMA, 'market': _MARKET_SCHEMA},
                     'required': ['symbol'], 'additionalProperties': False}},
    {'name': 'st_watchlist_health', 'handler': tool_watchlist_health,
     'title': 'Watchlist health board',
     'description': 'Compact health lights, summary and today\'s new signals for up to 40 tickers. '
                    'Pass a comma-separated list; append :US for US tickers.',
     'inputSchema': {'type': 'object', 'properties': {
         'symbols': {'type': 'string', 'description': 'e.g. "2330,2454,AAPL:US"'}},
         'required': ['symbols'], 'additionalProperties': False}},
    {'name': 'st_signal_scoreboard', 'handler': tool_signal_scoreboard,
     'title': 'Signal scoreboard (same-market base rates)',
     'description': 'For each of the 15 signals: pooled 5/20-day outcomes across the local universe, '
                    'the all-days base rate, 95% margin, verdict (above/below/noise) and stability.',
     'inputSchema': {'type': 'object', 'properties': {'market': _MARKET_SCHEMA},
                     'additionalProperties': False}},
    {'name': 'st_signal_catalog', 'handler': tool_signal_catalog,
     'title': 'Signal catalog',
     'description': 'Definitions of every signal: rule, plain-language meaning and invalidation.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'st_market_decision', 'handler': tool_market_decision,
     'title': 'Market regime and action envelope',
     'description': 'Deterministic DecisionContext summary for the Taiwan market: regime, posture, '
                    'allowed/restricted/prohibited actions, confirmation and invalidation, key levels.',
     'inputSchema': {'type': 'object', 'properties': {'market': {'type': 'string', 'enum': ['TW']}},
                     'additionalProperties': False}},
    {'name': 'st_key_levels', 'handler': tool_key_levels,
     'title': 'Key price levels',
     'description': '臺灣指數本機日線的樞紐點、已確認轉折、ATR 與實現波動；預設 ^TWII。',
     'inputSchema': {'type': 'object', 'properties': {'symbol': {
         'type': 'string', 'enum': ['^TWII', '^TWOII', '__TXF__']}},
                     'additionalProperties': False}},
]
_TOOL_BY_NAME = {t['name']: t for t in TOOLS}
_REFRESH_TOOLS = {'st_stock_health', 'st_stock_evidence', 'st_watchlist_health'}
_CACHE_OPTION_TOOLS = {'st_stock_health', 'st_stock_evidence', 'st_watchlist_health'}
for _tool in TOOLS:
    if _tool['name'] in _CACHE_OPTION_TOOLS:
        _tool['inputSchema']['properties']['cacheOnly'] = {
            'type': 'boolean', 'default': False,
            'description': '只用既有後端資料，不觸發網路補抓；預設保留既有補抓行為。'}

OUTPUT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['contractVersion', 'tool', 'status', 'data', 'metadata', 'error'],
    'properties': {
        'contractVersion': {'const': RESULT_VERSION}, 'tool': {'type': 'string'},
        'status': {'enum': ['ok', 'partial', 'unavailable', 'error']},
        'data': {'type': ['object', 'null']},
        'metadata': {
            'type': 'object', 'additionalProperties': False,
            'required': ['source', 'asOf', 'generatedAt', 'freshness', 'calculationVersion',
                         'backendContractVersion', 'missing', 'backendMissing', 'access'],
            'properties': {
                'source': {}, 'asOf': {}, 'generatedAt': {},
                'freshness': {'type': 'object'}, 'calculationVersion': {},
                'backendContractVersion': {},
                'missing': {'type': 'array', 'items': {'type': 'string'}},
                'backendMissing': {}, 'access': {'type': 'object'},
            },
        },
        'error': {'type': ['object', 'null'], 'properties': {
            'code': {'type': 'string'}, 'message': {'type': 'string'},
            'retryable': {'type': 'boolean'}}, 'required': ['code', 'message', 'retryable'],
            'additionalProperties': False},
    },
}


def _structured(protocol_version):
    return protocol_version in ('2025-06-18', '2025-11-25')


def access_policy(name, args):
    network = name in _REFRESH_TOOLS and not (name in _CACHE_OPTION_TOOLS and args.get('cacheOnly'))
    return {'transport': 'loopback-http', 'mode': 'backend-may-refresh' if network else 'cache-only',
            'backendMayAccessNetwork': bool(network), 'backendMayUpdateCache': bool(network)}


def result_metadata(backend, name, args):
    # 不把 generatedAt 視為市場資料截止日，也不從目前時間推測新鮮度。
    freshness = {key: backend[key] for key in ('staleDays', 'dataWarning', 'dataQuality') if key in backend}
    session = backend.get('session')
    if isinstance(session, dict) and 'provisional' in session:
        freshness['provisional'] = session['provisional']
    result = {
        'source': backend.get('dataSource', backend.get('source')),
        'asOf': backend.get('asOf'), 'generatedAt': backend.get('generatedAt'),
        'freshness': freshness,
        'calculationVersion': backend.get('engine', backend.get('model')),
        'backendContractVersion': backend.get('contractVersion'),
        'backendMissing': backend.get('missing'),
        'access': access_policy(name, args),
    }
    result['missing'] = [key for key in ('source', 'asOf', 'generatedAt', 'calculationVersion',
                                        'backendContractVersion') if result[key] is None]
    if not freshness:
        result['missing'].append('freshness')
    return result


def _validate_args(tool, args):
    schema = tool['inputSchema']
    for key in schema.get('required', []):
        if key not in args:
            raise ValueError(f'缺少必要參數：{key}')
    for key, value in args.items():
        prop = schema['properties'].get(key)
        if prop is None:
            raise ValueError(f'未知參數：{key}')
        expected = str if prop['type'] == 'string' else bool
        if not isinstance(value, expected):
            raise ValueError(f'參數型別不符：{key}')
        if 'enum' in prop and value not in prop['enum']:
            raise ValueError(f'參數值不支援：{key}')


def tools_list_payload(protocol_version=SUPPORTED_PROTOCOLS[0]) -> Dict[str, Any]:
    return {'tools': [{
        'name': t['name'], 'title': t['title'], 'description': t['description'] + (
            ' 後端可能補抓公開資料並更新本機快取；cacheOnly=true 可禁止補抓。'
            if t['name'] in _REFRESH_TOOLS else ' 僅讀取既有本機資料／定義，不觸發網路補抓。'),
        'inputSchema': t['inputSchema'],
        **({'outputSchema': OUTPUT_SCHEMA} if _structured(protocol_version) else {}),
        'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                        'openWorldHint': t['name'] in _REFRESH_TOOLS},
        '_meta': {'st/access': access_policy(t['name'], {})},
    } for t in TOOLS]}


def call_tool(name: str, args: Dict[str, Any], protocol_version=SUPPORTED_PROTOCOLS[0]) -> Dict[str, Any]:
    tool = _TOOL_BY_NAME.get(name)
    data, backend, error, text_error = None, {}, None, None
    validated = False
    try:
        if not tool:
            raise UnknownToolError(f'Unknown tool: {name}')
        _validate_args(tool, args)
        validated = True
        result = tool['handler'](args)
        data, backend = (result.data, result.backend) if isinstance(result, BackendResult) else (result, result)
        if not isinstance(data, dict) or not isinstance(backend, dict):
            raise TypeError('後端結果必須為物件')
        json.dumps(data, allow_nan=False)
        json.dumps(backend, allow_nan=False)
    except urllib.error.HTTPError as exc:
        error = {'code': 'backend_http_error', 'message': f'本機 ST 回傳 HTTP {exc.code}',
                 'retryable': exc.code >= 500}
    except urllib.error.URLError as exc:
        error = {'code': 'backend_unreachable', 'message':
                 '無法連線本機 Stock Terminal；請用 START_TIP.cmd / scripts/go.sh 啟動並檢查 ST_MCP_BASE_URL。',
                 'retryable': True}
    except (TimeoutError, OSError):
        error = {'code': 'backend_unreachable', 'message': '本機 ST 連線失敗或逾時，請檢查 START_TIP.cmd。',
                 'retryable': True}
    except UnknownToolError as exc:
        error = {'code': 'unknown_tool', 'message': str(exc), 'retryable': False}
    except ValueError as exc:
        # JSON 解碼／非有限數字屬後端契約錯誤；參數錯誤不得觸發 HTTP。
        error = {'code': 'invalid_backend_result' if validated and isinstance(exc, json.JSONDecodeError)
                 or data is not None else 'invalid_arguments', 'message': str(exc), 'retryable': False}
    except Exception as exc:
        error = {'code': 'invalid_backend_result', 'message': f'後端結果無法解析（{type(exc).__name__}）',
                 'retryable': False}
    if error:
        text_error = error['message']
        data, backend = None, {}
    unavailable = backend.get('ok') is False or backend.get('available') is False
    regime = backend.get('regime')
    partial = (any(item.get('ok') is False for item in (backend.get('items') or []) if isinstance(item, dict))
               or isinstance(regime, dict) and regime.get('id') == 'INSUFFICIENT_DATA')
    if unavailable:
        error = {'code': 'backend_unavailable', 'message': str(backend.get('message') or backend.get('reason')
                 or '尚無可用的後端研究資料'), 'retryable': False}
    envelope = {'contractVersion': RESULT_VERSION, 'tool': name,
                'status': 'error' if text_error else 'unavailable' if unavailable else 'partial' if partial else 'ok',
                'data': data, 'metadata': result_metadata(backend, name, args), 'error': error}
    content = [{'type': 'text', 'text': text_error or json.dumps(data, ensure_ascii=False, allow_nan=False)}]
    if _structured(protocol_version):
        # 第一段保留舊客戶端讀取的原始 JSON；第二段符合 MCP 的結構化 JSON 文字副本建議。
        content.append({'type': 'text', 'text': json.dumps(envelope, ensure_ascii=False, allow_nan=False)})
    return {'content': content, 'isError': error is not None,
            **({'structuredContent': envelope} if _structured(protocol_version) else {})}


# ── JSON-RPC ────────────────────────────────────────────────
def handle(msg: Dict[str, Any], protocol_version=SUPPORTED_PROTOCOLS[0]) -> Optional[Dict[str, Any]]:
    """處理一則 JSON-RPC 訊息；notification（無 id）回 None。"""
    method = msg.get('method')
    mid = msg.get('id')
    params = msg.get('params', {})
    if mid is None:
        return None   # notifications/initialized 等

    def ok(result):
        return {'jsonrpc': '2.0', 'id': mid, 'result': result}

    def err(code, message):
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}

    if not isinstance(params, dict):
        return err(-32602, 'params must be an object')

    if method == 'initialize':
        requested = str(params.get('protocolVersion') or '')
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return ok({'protocolVersion': version,
                   'capabilities': {'tools': {'listChanged': False}},
                   'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
                   'instructions': INSTRUCTIONS})
    if method == 'ping':
        return ok({})
    if method == 'tools/list':
        return ok(tools_list_payload(protocol_version))
    if method == 'tools/call':
        name = params.get('name')
        if not isinstance(name, str):
            return err(-32602, 'params.name is required')
        args = params.get('arguments', {})
        if not isinstance(args, dict):
            return err(-32602, 'params.arguments must be an object')
        return ok(call_tool(name, args, protocol_version))
    return err(-32601, f'Method not found: {method}')


def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    protocol_version = SUPPORTED_PROTOCOLS[0]
    def dispatch(msg):
        nonlocal protocol_version
        reply = handle(msg, protocol_version)
        if msg.get('method') == 'initialize' and reply and 'result' in reply:
            protocol_version = reply['result']['protocolVersion']
        return reply
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        else:
            if isinstance(msg, list):   # 舊版協定的 batch
                replies = [r for r in (dispatch(m) for m in msg if isinstance(m, dict)) if r]
                reply = replies or None
            elif isinstance(msg, dict):
                reply = dispatch(msg)
            else:
                reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + '\n')
            stdout.flush()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')
    serve()
