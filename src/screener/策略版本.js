// 策略定義以內容定址；凍結版本只追加，草稿仍沿用既有儲存。
(function () {
  'use strict';
  const SCHEMA = 'st.strategy/v1';
  const clone = value => JSON.parse(JSON.stringify(value));
  function canonical(value) {
    if (value === null || typeof value !== 'object') {
      if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('策略不可包含非有限數值');
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  }
  async function hash(value) {
    const text = typeof value === 'string' ? value : canonical(value);
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
  }
  function payload(m) { return { schema: m.schema, definition: m.definition, execution: m.execution, context: m.context }; }
  function validate(m) {
    if (m.schema !== SCHEMA || !m.definition || m.definition.kind !== 'builder') throw new Error('策略版本格式不支援');
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(m.strategy_id)) throw new Error('策略識別碼無效');
    if (!m.context || typeof m.context.symbol !== 'string' || !m.context.symbol.trim()
      || !['equity', 'etf'].includes(m.context.asset_type) || m.context.regime !== 'unspecified') throw new Error('策略標的或資產類別無效');
    if (!m.execution || m.execution.timeframe !== '1d') throw new Error('策略版本僅支援日線');
    for (const key of Object.keys(window.Backtest.DEFAULTS)) {
      if (!Object.hasOwn(m.execution, key)) throw new Error('策略執行設定缺少欄位：' + key);
    }
    if (typeof m.created_at !== 'string' || !Number.isFinite(Date.parse(m.created_at))) throw new Error('策略建立時間無效');
    window.Backtest.settings(m.execution);
    if (!window.StrategyBuilder || !window.StrategyBuilder.validateDefinition(m.definition)) throw new Error('策略條件無效');
  }
  async function verify(m) {
    validate(m);
    if (!/^[0-9a-f]{64}$/.test(m.version) || canonical(payload(m)) !== m.canonical_json
      || await hash(m.canonical_json) !== m.version) throw new Error('策略內容與版本雜湊不符');
    return true;
  }
  function deepFreeze(value) {
    if (value && typeof value === 'object') { Object.values(value).forEach(deepFreeze); Object.freeze(value); }
    return value;
  }
  async function freeze(definition, execution, context, strategyId) {
    const m = clone({ schema: SCHEMA, strategy_id: strategyId || crypto.randomUUID(), definition, execution,
      context, created_at: new Date().toISOString() });
    validate(m);
    m.canonical_json = canonical(payload(m));
    m.version = await hash(m.canonical_json);
    await verify(m);
    return deepFreeze(m);
  }
  function list(storage = localStorage) {
    const data = JSON.parse(storage.getItem('st.strategy.versions/v1') || '[]');
    if (!Array.isArray(data)) throw new Error('策略版本庫格式無效，請先保留原資料');
    return data;
  }
  async function save(manifest, storage = localStorage) {
    await verify(manifest);
    const all = list(storage);
    const found = all.find(m => m.strategy_id === manifest.strategy_id && m.version === manifest.version);
    if (found) { await verify(found); return found; }
    all.push(clone(manifest));
    storage.setItem('st.strategy.versions/v1', JSON.stringify(all));
    return manifest;
  }
  function download(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  window.StrategyVersion = { SCHEMA, canonical, hash, freeze, verify, save, list, download };
})();
