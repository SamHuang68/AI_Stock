#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stock Terminal 本機 MCP 伺服器（stdio，唯讀，純標準函式庫）。

讓 Claude Desktop／Claude Code／Cowork（含 Claude for Financial Services 的
equity-research 技能，例如 /morning-note、/thesis、/catalysts）直接讀取本機 ST 的
規則化結果：個股體檢、自選股總表、訊號成績單、市場決策情境與關鍵價位。

* 只呼叫本機 ST HTTP API（預設 http://127.0.0.1:18432），不連外、不寫入任何狀態。
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
SERVER_VERSION = '1.0.0'
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
    if env:
        return env.rstrip('/')
    return f"http://127.0.0.1:{os.environ.get('ST_PORT', '18432')}"


def http_json(path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    url = base_url() + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode('utf-8'))


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
    q = urllib.parse.urlencode({'sym': sym, 'market': _market_arg(args, sym)})
    return compact_health(http_json('/stock-signals?' + q))


def tool_stock_evidence(args):
    sym = _symbol_arg(args)
    q = urllib.parse.urlencode({'sym': sym, 'market': _market_arg(args, sym)})
    d = http_json('/stock-signals?' + q)
    return {'symbol': d.get('symbol'), 'asOf': d.get('asOf'), 'ok': d.get('ok'),
            'evidence': d.get('evidence') or {},
            'citationRule': 'Every sentence you write must cite one or more of these evidence ids; '
                            'numbers must appear in the cited evidence.'}


def tool_watchlist_health(args):
    raw = str(args.get('symbols') or '').strip()
    if not raw:
        raise ValueError('symbols is required, e.g. "2330,2454,AAPL:US"')
    d = http_json('/stock-signals/batch?' + urllib.parse.urlencode({'syms': raw}))
    return {'items': d.get('items') or [], 'disclaimer': d.get('disclaimer')}


def tool_signal_scoreboard(args):
    market = 'US' if str(args.get('market') or '').strip().upper() == 'US' else 'TW'
    d = http_json('/stock-signals/pooled?' + urllib.parse.urlencode({'market': market}))
    if not d.get('available'):
        return {'market': market, 'available': False,
                'hint': 'Pooled statistics not computed yet; open ST 體檢 tab → 訊號成績單 → 開始計算.'}
    rows = [{'signalId': r['signalId'], 'label': r['label'], 'direction': r['direction'],
             'horizons': _stats_brief({'horizons': r['horizons']}),
             'research5d': next((h.get('all') for h in (r.get('research') or {}).get('horizons', [])
                                if h.get('horizon') == 5), None)} for r in d.get('scoreboard') or []]
    out = {k: d.get(k) for k in ('market', 'symbols', 'window', 'generatedAt', 'minSample', 'caveats', 'research')}
    out['scoreboard'] = rows
    return out


def tool_signal_catalog(args):
    return http_json('/stock-signals/catalog')


def tool_market_decision(args):
    return compact_decision(http_json('/decision/context?' + urllib.parse.urlencode(
        {'market': str(args.get('market') or 'TW').upper()})))


def tool_key_levels(args):
    sym = str(args.get('symbol') or '^TWII').strip()
    if not _SYM_RE.match(sym):
        raise ValueError('invalid symbol')
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
     'description': 'Classic pivot, confirmed swing points, ATR and realised volatility for an index '
                    'or stock (default ^TWII).',
     'inputSchema': {'type': 'object', 'properties': {'symbol': _SYMBOL_SCHEMA},
                     'additionalProperties': False}},
]
_TOOL_BY_NAME = {t['name']: t for t in TOOLS}


def tools_list_payload() -> Dict[str, Any]:
    return {'tools': [{
        'name': t['name'], 'title': t['title'], 'description': t['description'],
        'inputSchema': t['inputSchema'],
        'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False},
    } for t in TOOLS]}


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    tool = _TOOL_BY_NAME.get(name)
    if not tool:
        return {'content': [{'type': 'text', 'text': f'Unknown tool: {name}'}], 'isError': True}
    try:
        data = tool['handler'](args or {})
    except urllib.error.URLError as exc:
        msg = (f'Cannot reach Stock Terminal at {base_url()} ({getattr(exc, "reason", exc)}). '
               'Start it with START_TIP.cmd / scripts/go.sh, or set ST_MCP_BASE_URL.')
        return {'content': [{'type': 'text', 'text': msg}], 'isError': True}
    except Exception as exc:
        return {'content': [{'type': 'text', 'text': f'{type(exc).__name__}: {exc}'}], 'isError': True}
    return {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}], 'isError': False}


# ── JSON-RPC ────────────────────────────────────────────────
def handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """處理一則 JSON-RPC 訊息；notification（無 id）回 None。"""
    method = msg.get('method')
    mid = msg.get('id')
    params = msg.get('params') or {}
    if mid is None:
        return None   # notifications/initialized 等

    def ok(result):
        return {'jsonrpc': '2.0', 'id': mid, 'result': result}

    def err(code, message):
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}

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
        return ok(tools_list_payload())
    if method == 'tools/call':
        name = params.get('name')
        if not isinstance(name, str):
            return err(-32602, 'params.name is required')
        args = params.get('arguments') or {}
        if not isinstance(args, dict):
            return err(-32602, 'params.arguments must be an object')
        return ok(call_tool(name, args))
    return err(-32601, f'Method not found: {method}')


def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
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
                replies = [r for r in (handle(m) for m in msg if isinstance(m, dict)) if r]
                reply = replies or None
            elif isinstance(msg, dict):
                reply = handle(msg)
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
