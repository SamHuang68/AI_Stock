/* 每日研究的不可覆寫紀錄；私人內容只留在目前瀏覽器來源。 */
(function () {
  'use strict';
  var PREFIX = 'st.research.record.v1.';
  function copy(v) { return JSON.parse(JSON.stringify(v)); }
  function canonical(v) {
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map(function (k) {
      return JSON.stringify(k) + ':' + canonical(v[k]);
    }).join(',') + '}';
    return JSON.stringify(v);
  }
  async function hash(v) {
    if (!window.crypto || !window.crypto.subtle) throw new Error('瀏覽器不支援安全摘要，無法保存可核對紀錄');
    var bytes = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(v)));
    return Array.from(new Uint8Array(bytes)).map(function (n) { return n.toString(16).padStart(2, '0'); }).join('');
  }
  function id() {
    if (!window.crypto || !window.crypto.getRandomValues) throw new Error('瀏覽器無法產生研究紀錄識別');
    return Array.from(window.crypto.getRandomValues(new Uint8Array(16))).map(function (n) {
      return n.toString(16).padStart(2, '0');
    }).join('');
  }
  function body(record) { var v = copy(record); delete v.digest; return v; }
  function validate(record) {
    if (!record || record.schema !== 'research-record-v1' || !/^[a-f0-9]{32}$/.test(record.id || '') ||
      !/^[a-f0-9]{64}$/.test(record.digest || '') || !record.snapshot ||
      record.snapshot.persistence !== 'committed' || !record.snapshot.snapshotId ||
      typeof record.title !== 'string' || typeof record.note !== 'string' ||
      typeof record.createdAt !== 'string' || !Number.isFinite(Date.parse(record.createdAt))) {
      throw new Error('研究紀錄格式不完整，原有資料保留');
    }
    if (record.title.length > 240 || record.note.length > 20000) throw new Error('研究標題或筆記超過保存上限');
    if (typeof record.hypothesis !== 'string' || typeof record.invalidation !== 'string' ||
        record.hypothesis.length > 10000 || record.invalidation.length > 10000) throw new Error('假說或推翻條件格式不符或超過保存上限');
  }
  function Store(storage) { this.storage = storage; }
  Store.prototype.list = function () {
    var rows = [], errors = [];
    for (var n = 0; n < this.storage.length; n++) {
      var key = this.storage.key(n);
      if (!key || key.indexOf(PREFIX) !== 0) continue;
      try { var row = JSON.parse(this.storage.getItem(key)); validate(row); rows.push(row); }
      catch (_) { errors.push(key); }
    }
    rows.sort(function (a, b) { return b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id); });
    return { records: rows, damagedKeys: errors };
  };
  Store.prototype.verify = async function (record) { validate(record); return await hash(body(record)) === record.digest; };
  Store.prototype.save = async function (input) {
    if (!input.snapshot || input.snapshot.persistence !== 'committed') throw new Error('必須先選取已提交的市場快照');
    var record = { schema: 'research-record-v1', id: id(), createdAt: new Date().toISOString(),
      parentId: input.parentId || null, title: String(input.title || '').trim(), note: String(input.note || ''),
      symbol: input.symbol || null, snapshot: copy(input.snapshot), comparison: copy(input.comparison || null),
      subject: copy(input.subject || null), portfolio: copy(input.portfolio || null),
      hypothesis: String(input.hypothesis || ''), invalidation: String(input.invalidation || ''),
      reviewOf: input.reviewOf || null, outcome: copy(input.outcome || null) };
    if (!record.title) throw new Error('請填寫研究標題');
    record.digest = await hash(record); validate(record);
    var key = PREFIX + record.id;
    if (this.storage.getItem(key) !== null) throw new Error('研究紀錄識別重複，請重試');
    try { this.storage.setItem(key, JSON.stringify(record)); }
    catch (_) { throw new Error('瀏覽器儲存空間不足或禁止寫入；草稿保留，請先匯出備份'); }
    return record;
  };
  Store.prototype.exportAll = function () {
    var data = this.list();
    // 損毀資料也保留原字串供使用者備份；不靜默刪除。
    return { schema: 'research-backup-v1', exportedAt: new Date().toISOString(), records: data.records,
      damaged: data.damagedKeys.map(function (key) { return { key: key, raw: this.storage.getItem(key) }; }, this) };
  };
  Store.prototype.importAll = async function (data) {
    if (!data || data.schema !== 'research-backup-v1' || !Array.isArray(data.records)) throw new Error('不是有效的研究備份');
    if (data.damaged && data.damaged.length) throw new Error('備份含損毀資料，請先保存原檔並逐筆檢查；未變更現有紀錄');
    var pending = [], seen = new Set();
    for (var record of data.records) {
      validate(record);
      if (seen.has(record.id)) throw new Error('備份有重複識別，停止匯入');
      seen.add(record.id);
      if (!await this.verify(record)) throw new Error('研究紀錄摘要不符，停止匯入');
      var key = PREFIX + record.id, old = this.storage.getItem(key);
      if (old !== null) {
        if (canonical(JSON.parse(old)) !== canonical(record)) throw new Error('同一研究紀錄存在不同內容，原紀錄保留');
      } else pending.push([key, JSON.stringify(record)]);
    }
    var added = [];
    try {
      pending.forEach(function (row) {
        // 雜湊運算期間可能有另一分頁匯入；相同資料可略過，衝突不可覆寫。
        var old = this.storage.getItem(row[0]);
        if (old !== null && old !== row[1]) throw new Error('另一分頁已寫入不同紀錄');
        if (old === null) { this.storage.setItem(row[0], row[1]); added.push(row); }
      }, this);
    } catch (error) {
      added.forEach(function (row) { if (this.storage.getItem(row[0]) === row[1]) this.storage.removeItem(row[0]); }, this);
      throw new Error('匯入未完成，已回復本次新增資料：' + error.message);
    }
    return added.length;
  };
  function relevance(symbol, portfolio) {
    if (!portfolio) return { label: '未載入持倉模式', present: null };
    var premise = { kind: portfolio.kind, source: portfolio.source || '未知', sourceLabel: portfolio.sourceLabel, contractVersion: portfolio.contractVersion,
      inputVersion: portfolio.inputVersion, revision: portfolio.revision, coverage: copy(portfolio.coverage || null), issues: copy(portfolio.issues || []) };
    if (!portfolio.ready) return Object.assign(premise, { label: portfolio.label + '：輸入不足，無法確認曝險', present: null });
    var found = (portfolio.holdings || []).find(function (x) { return x.sym === symbol; });
    return Object.assign(premise, { label: portfolio.label + (found ? '中包含此標的' : '中沒有此標的'), present: !!found,
      kind: portfolio.kind, directWeight: found ? found.weight : null,
      note: (portfolio.kind === 'simulation' ? '模擬情境為自訂假設，不代表已成交或實際曝險。' : '') + '此處只核對直接標的；ETF 間接曝險請查看投組穿透研究。' });
  }
  var SUBJECT_DOMAINS = ['fundamentals', 'flows', 'supplyChainNews', 'peersThemes', 'etfResearch'];
  function publicFields(value, keys) {
    var out = {};
    keys.forEach(function (key) { if (value && value[key] !== undefined && (value[key] === null || ['string', 'number', 'boolean'].indexOf(typeof value[key]) >= 0)) out[key] = value[key]; });
    return out;
  }
  function publicEvidence(row) {
    var out = publicFields(row, ['evidenceId', 'digest', 'domain', 'kind', 'symbol', 'asOf', 'source']);
    var value = row.value || {}, keys = {
      revenue: ['period', 'periodLabel', 'expectedPeriod', 'monthRev', 'yoyPct', 'momPct', 'cumRev', 'cumYoyPct', 'unit', 'unitMultiplier', 'source', 'sourceName', 'sourceDate', 'priorPeriod'],
      income: ['period', 'year', 'quarter', 'industry', 'industryCode', 'source', 'sourceName', 'sourceDate', 'unit', 'unitMultiplier', 'epsUnit', 'sales', 'eps', 'netIncome', 'parentNetIncome', 'grossMargin', 'opMargin', 'netMargin', 'marginStatus', 'marginNote'],
      institutional: ['foreign', 'trust', 'dealer', 'total', 'sourceDate', 'source', 'unit'],
      company_news: ['time', 'ts', 'title', 'cat', 'code', 'name', 'mkt', 'url', 'source', 'clause'],
      same_industry: ['symbol', 'industry', 'market', 'currency', 'comparable', 'changePct', 'comparisonReason'],
      catalog_classification: ['code', 'name', 'market', 'category'],
      saved_holdings: ['name', 'sourceDate', 'source', 'holdingCount', 'collectedDate', 'premise'],
      curated_classification: ['stage', 'market', 'currency']
    };
    var allowed = { fundamentals: ['revenue', 'income'], flows: ['institutional'], supplyChainNews: ['company_news'],
      peersThemes: ['same_industry'], etfResearch: ['catalog_classification', 'saved_holdings'], supplyChainClassification: ['curated_classification'] };
    if (!keys[row.kind] || !allowed[row.domain] || allowed[row.domain].indexOf(row.kind) < 0) throw new Error('公開研究證據種類尚未核對，停止凍結：' + String(row.kind || '未知'));
    out.value = publicFields(value, keys[row.kind]);
    if (row.kind === 'same_industry') out.value.observations = (value.observations || []).map(function (p) {
      var point = publicFields(p, ['close', 'asOf', 'source', 'priceBasis']);
      point.issues = (p.issues || []).filter(function (x) { return typeof x === 'string'; }); return point;
    });
    // 只有明確 ETF 公開證據型別允許持股欄位，不接私人部位物件。
    if (row.kind === 'saved_holdings') out.value.holdings = (value.holdings || []).map(function (p) { return publicFields(p, ['code', 'name', 'shares', 'weight', 'market', 'value', 'weightPct', 'rank']); });
    if (row.kind === 'curated_classification') out.value.members = (value.members || []).map(function (p) { return publicFields(p, ['symbol', 'name']); });
    return out;
  }
  function publicDomain(value) {
    var out = publicFields(value, ['availability', 'asOf', 'reason', 'freshness', 'classificationAsOf', 'classificationNote']);
    out.source = (value.source || []).filter(function (x) { return typeof x === 'string'; });
    out.evidence = (value.evidence || []).map(publicEvidence); return out;
  }
  function publicSavedResearch(value) {
    var report = value && value.report;
    if (!report || report.version !== 'research-subject-v1' || report.readOnly !== true) throw new Error('公開標的研究契約尚未核對');
    var out = publicFields(report, ['ok', 'version', 'symbol', 'market', 'currency', 'asOf', 'readOnly', 'digest']);
    out.domains = {};
    SUBJECT_DOMAINS.forEach(function (name) { if (report.domains && report.domains[name]) out.domains[name] = publicDomain(report.domains[name]); });
    out.evidence = (report.evidence || []).map(publicEvidence);
    // report.notes 是公開 DTO 的限制；外層 notes/private/holdings 不屬於公開資料。
    out.notes = (report.notes || []).filter(function (x) { return typeof x === 'string'; });
    var result = { report: out };
    if (value.supplyChainClassification) result.supplyChainClassification = publicDomain(value.supplyChainClassification);
    return result;
  }
  function normalizeSymbol(value) {
    var symbol = String(value || '').trim().toUpperCase().replace(/\.(TW|TWO)$/, '');
    if (!/^\d{4,6}[A-Z]?$/.test(symbol)) throw new Error('請填寫有效台股或 ETF 代號');
    return symbol;
  }
  async function freezeSubject(symbol, dailyReport, savedReport, chains, technicalReason) {
    symbol = normalizeSymbol(symbol);
    // 在第一個非同步摘要前複製全部輸入；更新畫面或分類名單不回寫研究證據。
    var daily = copy(dailyReport || null), saved = copy(savedReport || null), classifications = copy(chains || []);
    if (!saved || saved.readOnly !== true || saved.version !== 'research-subject-v1' || normalizeSymbol(saved.symbol) !== symbol || !saved.domains) throw new Error('標的公開研究格式或歸屬不符，原研究保留');
    if (daily && daily.symbol && normalizeSymbol(daily.symbol) !== symbol) throw new Error('日線研究標的歸屬不符，原研究保留');
    SUBJECT_DOMAINS.forEach(function (name) {
      var domain = saved.domains[name];
      if (!domain) { saved.domains[name] = { availability: 'unknown', asOf: null, source: [], evidence: [], reason: '尚無此領域的已保存研究資料' }; return; }
      if (['available', 'partial', 'unknown', 'not_applicable'].indexOf(domain.availability) < 0 || !Array.isArray(domain.evidence) || !Array.isArray(domain.source)) throw new Error('標的領域研究格式不符，原研究保留');
      domain.evidence.forEach(function (row) {
        if (!row || !row.evidenceId || !row.digest || normalizeSymbol(row.symbol) !== symbol) throw new Error('標的證據識別或歸屬不符，原研究保留');
      });
    });
    var groups = classifications.filter(function (row) { return row && Array.isArray(row.stocks) && row.stocks.some(function (pair) { return pair[0] === symbol; }); });
    var classification = { availability: groups.length ? 'partial' : 'unknown', asOf: null, source: ['既有供應鏈研究分類 SC_CHAINS.TW'],
      reason: groups.length ? '既有研究分類，非供應關係證明；分類揭露日與生效日未知，不推算交易訊號' : '既有研究分類未列此標的，不能據此判定沒有供應鏈或主題關係', evidence: [] };
    for (var group of groups) {
      var value = { stage: group.stage, members: group.stocks.map(function (pair) { return { symbol: pair[0], name: pair[1] }; }), market: 'TW', currency: 'TWD' };
      classification.evidence.push({ evidenceId: 'curated-chain:' + symbol + ':' + group.stage, digest: await hash(value), domain: 'supplyChainClassification', kind: 'curated_classification',
        symbol: symbol, asOf: null, source: '既有供應鏈研究分類 SC_CHAINS.TW', value: value });
    }
    // 後端 digest 原樣保留；本機分類另列，不冒充後端原報告的一部分。
    var integrated = publicSavedResearch({ report: saved, supplyChainClassification: classification });
    var research = daily && daily.research || {}, adjusted = research.adjusted || {};
    return { symbol: symbol, market: saved.market || 'TW', currency: saved.currency || 'TWD', asOf: daily && daily.asOf || null,
      version: 'research-subject-integrated-v1', reportDigest: await hash({ daily: daily, savedResearch: integrated, originalSavedReport: saved }),
      dailyReportDigest: daily ? await hash(daily) : null, dailyVersion: research.version || null,
      stats: research.stats || [], latest: research.latest || null, shadow: research.shadow || null,
      adjusted: { version: adjusted.version, priceBasis: adjusted.priceBasis, stats: adjusted.stats, latest: adjusted.latest, shadow: adjusted.shadow },
      source: daily && daily.source || null, quality: daily && daily.quality || null, savedResearch: integrated, originalSavedReport: saved,
      technicalAvailability: daily ? 'available' : 'unknown',
      technicalReason: daily ? null : technicalReason || '既有日線研究入口尚未支援此代號格式',
      premise: '一年期日線研究摘要與全部已保存公開領域證據分別保留資料日及原報告摘要碼；非完整原始日線副本。後端摘要碼原樣保留，不代表已獨立驗證來源真偽。取得時間不等於公告時間，各領域不保證同日；未知日期保持未知。' +
        (daily ? '' : ' 技術研究未知：' + (technicalReason || '既有日線研究入口尚未支援此代號格式') + '。') };
  }
  window.ResearchWorkflow = { Store: Store, hash: hash, canonical: canonical, relevance: relevance, copy: copy,
    freezeSubject: freezeSubject, publicSavedResearch: publicSavedResearch, normalizeSymbol: normalizeSymbol, subjectDomains: SUBJECT_DOMAINS };
})();
