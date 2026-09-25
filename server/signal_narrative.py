# -*- coding: utf-8 -*-
"""個股體檢的白話解讀（P3）：AI 只能引用證據，後端逐句驗證。

分權（沿用 DecisionContext 紀律）
--------------------------------
* 燈號、事件、失效價位與統計全部由 ``stock_signals`` 規則產生；AI 不得新增或改寫。
* Claude 以結構化輸出（JSON schema）回傳 ``sentences[{text, evidenceIds}]``。
* 後端逐句驗證：引用的證據編號必須存在、句中數字必須能在所引證據中找到、
  不得出現買賣／目標價／保證等字眼。不合格的句子刪除並回報；剩不到 2 句就改用規則模板。
* 沒有 API Key、呼叫失敗、拒答或截斷時，一律回規則模板（source='template'），
  介面永遠有可讀的白話說明。

呼叫形式
--------
* 單檔即時：``explain(result, api_key)``（同步 /v1/messages，系統提示含訊號名詞表並設快取）。
* 收盤摘要：``batch_request(...)`` 產生 Message Batches 請求（非即時、費用約一半），
  ``from_batch_result(...)`` 用同一套驗證收回結果。
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from . import stock_signals as ss
except ImportError:
    import stock_signals as ss

NARRATIVE_VERSION = 'st-signal-narrative/v1'
MIN_SENTENCES = 2
MAX_TOKENS = 4000
EFFORT = 'medium'
BANNED = ('買進', '買入', '賣出', '加碼', '減碼', '目標價', '保證', '穩賺', '必漲', '必跌',
          '一定會', '全力', 'buy', 'sell', 'target price')

SCHEMA = {
    'type': 'object',
    'properties': {
        'sentences': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string'},
                    'evidenceIds': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['text', 'evidenceIds'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['sentences'],
    'additionalProperties': False,
}

_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str, str, str], Tuple[float, Dict[str, Any]]] = {}
CACHE_SEC = 1800


def system_prompt() -> str:
    """固定前綴（名詞表 + 規則）：同一版本逐字相同，才能命中提示快取。"""
    glossary = '\n'.join(
        f"- {s['label']}（{s['familyLabel']}／{s['directionLabel']}）：{s['plain']} 規則：{s['rule']}；"
        f"失效：{s['invalidText']}"
        for s in ss.catalog())
    return (
        '你是台股／美股的投資教育講師，任務是把「規則化的個股體檢卡」翻成新手看得懂的白話。\n'
        '你不是投資顧問，不做預測，不給交易指令。\n\n'
        '【硬性規則】\n'
        '1. 只能使用使用者訊息中 EVIDENCE 提供的事實；不得引用外部知識、新聞或你記得的股價。\n'
        '2. 每一句都必須在 evidenceIds 列出支撐它的證據編號（EVIDENCE 的 key），可以列多個。\n'
        '3. 句中出現的每個數字，都必須原樣出現在所引用證據的內容裡（百分比可寫成 41% 對應 0.41）。'
        '不要自行計算新的數字，不要四捨五入到證據沒有的位數。\n'
        '4. 禁止出現：買進、買入、賣出、加碼、減碼、目標價、保證、穩賺、必漲、必跌、一定會、全力。'
        '可以說「偏多」「偏空」「留意」「條件成立」「條件失效」。\n'
        '5. 燈號、事件與失效條件由規則決定，你只能解釋，不能改判或加上自己的結論。\n'
        '6. 若統計的 gate 為 insufficient，要說明「樣本不足，歷史不能說明什麼」；'
        '若 edgeVerdict 為 noise，要說明「和隨便挑一天差不多，參考價值有限」。\n'
        '7. 一定要提到「什麼情況代表判斷錯了」（health.invalidation 或事件的失效條件）。\n'
        '8. 使用繁體中文，4 到 7 句，每句不超過 60 字，先講整體，再講今日新訊號，最後講失效條件。\n\n'
        '【訊號名詞表】\n' + glossary + '\n\n'
        '【燈號狀態】bull=偏多、bear=偏空、caution=留意、neutral=中性、unknown=資料不足。\n'
        '輸出只能是符合 schema 的 JSON。'
    )


# ── 證據包 ───────────────────────────────────────────────────
def build_pack(result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """從體檢結果挑出 AI 可引用的證據（編號即 result['evidence'] 的 key）。"""
    ev = result.get('evidence') or {}
    keep_prefix = ('health.', 'light.', 'event.', 'stats.', 'pooled.')
    keep_exact = {'ind.close', 'ind.chgPct', 'ind.sma60', 'ind.sma20', 'ind.rsi14', 'ind.high20',
                  'ind.low20', 'ind.volVs20d', 'ind.range20'}
    pack = {}
    for k in sorted(ev):
        if k.startswith(keep_prefix) or k in keep_exact:
            item = ev[k]
            pack[k] = {x: item[x] for x in ('label', 'value', 'text', 'asOf') if x in item}
    return pack


def user_message(result: Dict[str, Any], pack: Dict[str, Dict[str, Any]]) -> str:
    head = {
        'symbol': result.get('symbol'), 'market': result.get('market'), 'asOf': result.get('asOf'),
        'provisional': (result.get('session') or {}).get('provisional'),
    }
    return ('請解讀這張個股體檢卡。\n'
            f'CARD = {json.dumps(head, ensure_ascii=False)}\n'
            f'EVIDENCE = {json.dumps(pack, ensure_ascii=False, sort_keys=True)}')


# ── 驗證 ─────────────────────────────────────────────────────
_NUM_RE = re.compile(r'[-+]?\d[\d,]*(?:\.\d+)?%?')


def _numbers_in(obj: Any) -> List[float]:
    out: List[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            try:
                out.append(float(tok.rstrip('%').replace(',', '')))
            except ValueError:
                pass
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numbers_in(v))
        return out
    if isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_numbers_in(v))
    return out


def _number_supported(token: str, values: Sequence[float]) -> bool:
    is_pct = token.endswith('%')
    raw = token.rstrip('%').replace(',', '')
    try:
        x = float(raw)
    except ValueError:
        return True
    decimals = len(raw.split('.')[1]) if '.' in raw else 0
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    for v in values:
        cands = (v, abs(v), v * 100.0, abs(v) * 100.0) if is_pct else (v, abs(v))
        if any(abs(c - abs(x)) <= tol or abs(c - x) <= tol for c in cands):
            return True
    return False


def validate(parsed: Any, pack: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """回 (通過的句子, 刪除的句子與原因)。"""
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    rows = (parsed or {}).get('sentences') if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        return kept, [{'text': '', 'reason': 'schema'}]
    for row in rows:
        text = str((row or {}).get('text') or '').strip()
        ids = [str(i) for i in ((row or {}).get('evidenceIds') or []) if str(i).strip()]
        if not text:
            continue
        reason = None
        if not ids:
            reason = 'no-evidence'
        elif any(i not in pack for i in ids):
            reason = 'unknown-evidence:' + ','.join(i for i in ids if i not in pack)
        else:
            low = text.lower()
            hit = next((b for b in BANNED if b in low), None)
            if hit:
                reason = 'banned:' + hit
            else:
                values = _numbers_in([pack[i] for i in ids])
                bad = [t for t in _NUM_RE.findall(text) if not _number_supported(t, values)]
                if bad:
                    reason = 'unsupported-number:' + ','.join(bad[:3])
        if reason:
            dropped.append({'text': text, 'evidenceIds': ids, 'reason': reason})
        else:
            kept.append({'text': text, 'evidenceIds': ids})
    return kept, dropped


# ── 規則模板（沒有 AI 或 AI 未通過驗證）────────────────────────
def template(result: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get('ok'):
        return {'version': NARRATIVE_VERSION, 'source': 'template', 'sentences': [
            {'text': result.get('message') or '資料不足，無法解讀。', 'evidenceIds': []}], 'dropped': []}
    sentences = [{'text': result['health']['summary']['sentence'], 'evidenceIds': ['health.summary']}]
    for l in result['health']['lights']:
        if l['state'] in ('bull', 'bear', 'caution'):
            sentences.append({'text': f"{l['label']}：{l['plain']}", 'evidenceIds': [l['evidenceId']]})
    for e in (result.get('events') or [])[:3]:
        if e['status'] == 'invalidated':
            continue
        line = f"{e['label']}（{e['statusLabel']}）：{e['plain']}"
        ids = [e['evidenceId']]
        row = next((r for r in ((e.get('stats') or {}).get('horizons') or []) if r['horizon'] == 5), None)
        if row and row.get('gate') == 'ok' and row.get('edgeVerdict') == 'noise':
            line += '本檔歷史上這個訊號出現後 5 日的表現和平常差不多，參考價值有限。'
            ids.append(f"stats.{e['signalId']}.h5")
        elif row and row.get('gate') != 'ok':
            line += '本檔歷史樣本不足，無法用過去表現判斷。'
            ids.append(f"stats.{e['signalId']}.h5")
        sentences.append({'text': line, 'evidenceIds': ids})
    inval = result['health'].get('invalidation')
    if inval:
        sentences.append({'text': '判斷錯誤的條件：' + inval['text'] + '。', 'evidenceIds': ['health.invalidation']})
    return {'version': NARRATIVE_VERSION, 'source': 'template', 'sentences': sentences, 'dropped': []}


# ── Claude 呼叫 ──────────────────────────────────────────────
def request_payload(result: Dict[str, Any], model: str, *, structured: bool = True) -> Dict[str, Any]:
    import ai_api
    pack = build_pack(result)
    output_config: Dict[str, Any] = {'effort': EFFORT}
    if structured:
        output_config['format'] = {'type': 'json_schema', 'schema': SCHEMA}
    return ai_api.build_messages_payload(
        [{'role': 'user', 'content': user_message(result, pack)}], MAX_TOKENS,
        model=model, system=system_prompt(), output_config=output_config, cache_system=True)


def _parse(text: str) -> Optional[Dict[str, Any]]:
    try:
        from postmarket_report import parse_llm_json
    except ImportError:  # pragma: no cover
        parse_llm_json = None
    if parse_llm_json:
        return parse_llm_json(text)
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


def from_message(result: Dict[str, Any], data: Dict[str, Any], model: str) -> Dict[str, Any]:
    """把一則 Claude message（同步或批次）轉成已驗證的敘事；不合格回模板並附原因。"""
    import ai_api
    pack = build_pack(result)
    stop = (data or {}).get('stop_reason')
    usage = (data or {}).get('usage') or {}
    meta = {'model': (data or {}).get('model') or model, 'stopReason': stop,
            'usage': {k: usage.get(k) for k in ('input_tokens', 'output_tokens',
                                                 'cache_read_input_tokens', 'cache_creation_input_tokens')}}
    if stop in ('refusal', 'max_tokens'):
        out = template(result)
        out.update(meta, note=f'AI 未完成（{stop}），改用規則模板')
        return out
    kept, dropped = validate(_parse(ai_api.message_text(data)), pack)
    if len(kept) < MIN_SENTENCES:
        out = template(result)
        out.update(meta, dropped=dropped, note='AI 輸出未通過證據驗證，改用規則模板')
        return out
    return {'version': NARRATIVE_VERSION, 'source': 'claude', 'sentences': kept, 'dropped': dropped, **meta}


def explain(result: Dict[str, Any], api_key: Optional[str], *, model: Optional[str] = None,
            call: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """單檔即時解讀；call 可注入（測試用），預設走 ai_api 的 /v1/messages。"""
    base = {'symbol': result.get('symbol'), 'asOf': result.get('asOf')}
    if not result.get('ok') or not api_key:
        out = template(result)
        if result.get('ok') and not api_key:
            out['note'] = '尚未設定 AI Key，顯示規則模板'
        return {**base, **out}
    import ai_api
    model = model or ai_api.resolve_model(api_key)
    key = (str(result.get('symbol')), str(result.get('asOf')), model, str(result.get('generatedAt')))
    with _cache_lock:
        hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    send = call or (lambda payload: ai_api.post_messages(api_key, payload, timeout=90))
    try:
        try:
            data = send(request_payload(result, model, structured=True))
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            # 不支援結構化輸出的舊模型：退回提示詞 JSON，再用同一套驗證
            data = send(request_payload(result, model, structured=False))
        out = {**base, **from_message(result, data, model)}
    except urllib.error.HTTPError as exc:
        out = {**base, **template(result), 'note': f'AI 呼叫失敗（HTTP {exc.code}），改用規則模板'}
        return out
    except Exception as exc:
        out = {**base, **template(result), 'note': f'AI 呼叫失敗（{type(exc).__name__}），改用規則模板'}
        return out
    with _cache_lock:
        _cache[key] = (time.time() + CACHE_SEC, out)
    return out


# ── Message Batches（收盤摘要用）────────────────────────────────
def batch_request(result: Dict[str, Any], model: str, custom_id: str) -> Dict[str, Any]:
    return {'custom_id': custom_id, 'params': request_payload(result, model, structured=True)}


def from_batch_result(result: Dict[str, Any], batch_row: Dict[str, Any], model: str) -> Dict[str, Any]:
    if (batch_row or {}).get('type') != 'succeeded':
        out = template(result)
        out['note'] = f"批次結果 {(batch_row or {}).get('type') or 'missing'}，改用規則模板"
        return out
    return from_message(result, batch_row.get('message') or {}, model)


def as_text(narr: Dict[str, Any]) -> str:
    return ''.join(s['text'] if s['text'].endswith(('。', '！', '？', '.')) else s['text'] + '。'
                   for s in narr.get('sentences') or [])
