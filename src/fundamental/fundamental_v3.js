// ============================================================
// Stock Terminal v3.8 — 基本面面板 (Fundamental)  PR102
// ------------------------------------------------------------
// 核心規範：
//   • 台股 revenue: {period:'YYYMM', periodLabel:'YYYY-MM', monthRev(千元),
//     unit, unitMultiplier(1000), sourceName, sourceDate, expectedPeriod,
//     priorPeriod, yoyPct, momPct, cumRev, cumYoyPct}
//   • 台股 income:  {period:'YYYY年第N季財報', periodBasis, periodNote, industry, industryCode,
//     marginStatus:'available'|'not_applicable', marginNote, epsUnit, eps,
//     netIncome, parentNetIncome, unitMultiplier(1000), sourceName, sourceDate,
//     grossMargin, opMargin, netMargin}
//   • scoreNote 用於標示「金融業不適用一般業評分」或「財報暫缺」。
//   • 金額統一以 unitMultiplier 轉元後，再丟 fmtMoney（避免少一次 1000 倍
//     或重複乘 1000 倍）。
//   • monthRev 缺值仍走臺股月營收欄位，不可誤顯示為 Yahoo 盈餘成長。
//   • 金融業顯示 EPS + 稅後淨利 + 母公司業主淨利，三率明示「不適用」。
//   • 顯示實際期別 / 來源出表日 / 較舊期備註，不聲稱 PIT。
//   • 全部外部字串經 escapeHTML。
//   • 快取：完整 300s、缺值/部分 60s，若 server cacheTtlSeconds 更短則採
//     用；同 sym/market inFlight 共用；過期允許重試。
//   • renderStats 的非同步寫 DOM 須同時符合「同 sym/mkt」與「最新請求代
//     次」才動作，避免 A→B→A 的舊 call 覆蓋。
// ============================================================
(function () {
  const SRV = (typeof window !== 'undefined' && window.SERVER) || 'http://localhost:18432';

  // ---- 快取與 inFlight ----
  const _fCache = {};        // key -> { data, expireAt }
  const _fInflight = {};     // key -> { promise }
  const CACHE_FULL_MS = 300 * 1000;
  const CACHE_PARTIAL_MS = 60 * 1000;

  // ---- 請求代次（防 A→B→A 舊 call 覆蓋）----
  let _fReqSeq = 0;
  let _fLastReq = { sym: '', mkt: '', seq: 0 };

  function currentState() {
    // 主程式的 S 是頂層 let；瀏覽器不會自動把它掛到 window。
    return typeof S !== 'undefined' && S ? S : (typeof window !== 'undefined' ? window.S : null);
  }

  function escapeHTML(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function cacheKey(sym, mkt) {
    return String(sym || '').toUpperCase() + '|' + String(mkt || 'TW').toUpperCase();
  }

  // 判斷是否屬於「缺值 / partial」，決定要用 60s 還是 300s
  function isPartial(d) {
    if (!d) return true;
    if (d._note || d._partial || d.scoreNote) return true;
    const r = d.revenue, inc = d.income;
    if (d.kind === 'market' || d.kind === 'market_risk' ||
        d.kind === 'margin_cycle' || d.kind === 'holders') return false;
    if (!r && !inc) return true;
    if (r && r.monthRev == null && r.yoyPct == null && r.cumYoyPct == null &&
        (!inc || (inc.eps == null && inc.netIncome == null))) return true;
    return false;
  }

  function readCache(key, now) {
    const e = _fCache[key];
    if (!e) return null;
    if (e.expireAt <= now) return null;
    return e.data;
  }

  function writeCache(key, data, now, serverTtlSec) {
    let ttl = isPartial(data) ? CACHE_PARTIAL_MS : CACHE_FULL_MS;
    // 伺服器要求「更短」才採用（避免被要求延長超過上限）
    if (typeof serverTtlSec === 'number' && isFinite(serverTtlSec) && serverTtlSec >= 0) {
      const srvMs = serverTtlSec * 1000;
      if (srvMs < ttl) ttl = srvMs;
    }
    _fCache[key] = { data: data, expireAt: now + ttl };
  }

  async function fetchFund(sym, mkt) {
    if (!sym) return null;
    mkt = (mkt || 'TW').toUpperCase();
    const key = cacheKey(sym, mkt);
    const now = Date.now();

    // 市場風險／大盤體質／融資週期可能隨視窗重算 → 優先用主圖最新 payload（須同代號）
    if (typeof window !== 'undefined' && currentState() && currentState()._fundPanelPayload &&
        String(currentState().sym || '').toUpperCase() === String(sym).toUpperCase()) {
      const live = currentState()._fundPanelPayload;
      const liveSym = String((live && (live.symbol || live.code)) ||
        (currentState() && currentState()._marketChartId) || '').toUpperCase();
      const want = String(sym).toUpperCase();
      if (live && (live.kind === 'market' || live.kind === 'market_risk' ||
          live.kind === 'margin_cycle' || live.kind === 'holders') &&
          (!liveSym || liveSym === want ||
           liveSym.replace(/^\^/, '') === want.replace(/^\^/, ''))) {
        return live;
      }
    }

    const cached = readCache(key, now);
    if (cached) return cached;

    if (_fInflight[key]) return _fInflight[key].promise;

    const promise = (async function () {
      try {
        const traceId = 'fund-ui-' + Date.now() + '-' +
          String(sym).replace(/[^A-Z0-9.^_=:-]/gi, '').slice(0, 24);
        // Correlation id 放 query string，避免觸發 CORS preflight
        const r = await fetch(`${SRV}/fundamental/${encodeURIComponent(sym)}?traceId=${encodeURIComponent(traceId)}`, {
          cache: 'no-store'
        });
        if (!r.ok) {
          // 錯誤不寫快取，允許過期後重試
          return null;
        }
        const d = await r.json();
        const ttlSec = (d && d.cacheTtlSeconds != null) ? Number(d.cacheTtlSeconds) : null;
        writeCache(key, d, Date.now(), ttlSec);
        return d;
      } catch (e) {
        if (typeof console !== 'undefined') console.warn('[fundamental]', e);
        return null;
      } finally {
        delete _fInflight[key];
      }
    })();
    _fInflight[key] = { promise: promise };
    return promise;
  }

  // ---- 金額：將「以 unit 計」的數字轉為「元」。只在此處乘一次。----
  function toYuan(v, mult) {
    if (v == null || !isFinite(Number(v))) return null;
    const m = (typeof mult === 'number' && isFinite(mult) && mult > 0) ? mult : 1;
    return Number(v) * m;
  }

  // fmtMoney 以「元」為輸入單位。0 顯示 '0'，null 顯示 '—'。
  const fmtMoney = v => {
    if (v == null || !isFinite(v)) return '—';
    const av = Math.abs(v);
    if (av >= 1e8) return (v / 1e8).toFixed(1) + ' 億';
    if (av >= 1e4) return (v / 1e4).toFixed(0) + ' 萬';
    return Math.round(v).toLocaleString();
  };

  // 方向性成長(YoY/MoM/累計) → 顏色（台股正=紅/負=綠）
  const pctCol = v => (typeof window !== 'undefined' && window.Colors)
    ? window.Colors.growth(currentState() && currentState().sym, v)
    : (v == null ? 'var(--tlo)' : v > 0 ? 'var(--red)' : v < 0 ? 'var(--green)' : 'var(--tlo)');
  const pctStr = v => (v == null || !isFinite(Number(v))) ? '—'
    : ((Number(v) >= 0 ? '+' : '') + Number(v).toFixed(1) + '%');
  const marginCol = v => (typeof window !== 'undefined' && window.Colors)
    ? window.Colors.warn(v, { lo: 8 })
    : (v == null ? 'var(--tlo)' : v < 8 ? 'var(--orange)' : 'var(--thi)');
  const pillarCol = s => (typeof window !== 'undefined' && window.Colors)
    ? window.Colors.quality(s, 70, 50)
    : (s == null ? 'var(--tlo)' : s >= 70 ? 'var(--red)' : s >= 50 ? 'var(--orange)' : 'var(--green)');
  const riskCol = s => {
    if (s == null) return 'var(--tlo)';
    if (s >= 70) return '#f87171';
    if (s >= 55) return '#fb923c';
    if (s >= 45) return '#94a3b8';
    return '#4ade80';
  };

  function scoreBadge(s, kind) {
    if (s == null) return '';
    if (kind === 'market_risk') {
      const col = riskCol(s);
      const lbl = s >= 70 ? '風險偏高' : s >= 55 ? '風險中偏高' : s >= 45 ? '風險中性' : '風險偏低';
      return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
    }
    if (kind === 'margin_cycle') {
      const col = s >= 75 ? '#f87171' : s >= 55 ? '#fb923c' : s >= 30 ? '#94a3b8' : '#4ade80';
      const lbl = s >= 75 ? '擁擠高潮' : s >= 55 ? '偏熱' : s >= 30 ? '修復／中性' : '清算區';
      return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
    }
    if (kind === 'holders') {
      const col = s >= 70 ? '#f87171' : s >= 55 ? '#fb923c' : s >= 45 ? '#94a3b8' : '#4ade80';
      const lbl = s >= 70 ? '高度集中' : s >= 55 ? '集中中' : s >= 45 ? '中性' : s >= 30 ? '偏發散' : '發散';
      return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
    }
    const col = (typeof window !== 'undefined' && window.Colors)
      ? window.Colors.quality(s, 70, 50)
      : (s >= 70 ? 'var(--red)' : s >= 50 ? 'var(--orange)' : 'var(--green)');
    const lbl = kind === 'market'
      ? (s >= 70 ? '偏熱／偏強' : s >= 50 ? '中性' : '偏弱／偏冷')
      : (s >= 70 ? '體質佳' : s >= 50 ? '中性' : '偏弱');
    return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
  }

  /** STATS：大盤／風險／融資／籌碼白話摘要 */
  function renderPlainMarket(f) {
    const title = escapeHTML(f.title || (f.kind === 'market_risk' ? '市場風險' :
      (f.kind === 'margin_cycle' ? '融資週期' :
        (f.kind === 'holders' ? '籌碼集中度' : '大盤體質'))));
    const kind = f.kind === 'market_risk' ? 'market_risk' :
      (f.kind === 'margin_cycle' ? 'margin_cycle' :
        (f.kind === 'holders' ? 'holders' : 'market'));
    let h = '';
    const V = (typeof window !== 'undefined') ? window.Viz : null;
    if (f.score != null) {
      h += `<div class="stat-row" style="font-weight:700"><span class="stat-k">${title}</span><span class="stat-v">${scoreBadge(f.score, kind)}</span></div>`;
      if (V) h += `<div style="padding:0 12px 4px">${V.scoreMeter(f.score)}</div>`;
    }
    const plain = f.plainSummary || f.summary || '';
    if (plain) {
      h += `<div style="padding:10px 12px;color:var(--text);font-family:monospace;font-size:10.5px;line-height:1.65">${escapeHTML(plain)}</div>`;
    }
    const rows = f.marketRows || [];
    if (rows.length) {
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">支柱一覽</span><span class="stat-v">點主圖 ? 看完整算法</span></div>`;
      rows.forEach(row => {
        const sc = row.score;
        const col = (kind === 'market_risk' || kind === 'margin_cycle' || kind === 'holders')
          ? (sc == null ? 'var(--tlo)' : sc >= 70 ? '#f87171' : sc >= 55 ? '#fb923c' : sc >= 45 ? '#94a3b8' : '#4ade80')
          : pillarCol(sc);
        h += `<div class="stat-row"><span class="stat-k">${escapeHTML(row.k)}</span>` +
          `<span class="stat-v">${escapeHTML(row.v)}` +
          (sc != null ? ` <span style="color:${col};font-size:9px">(${Math.round(sc)})</span>` : '') +
          `</span></div>`;
        if (V && sc != null) h += `<div style="padding:0 12px 2px">${V.scoreMeter(sc, { color: col })}</div>`;
      });
    } else if (!plain) {
      h += `<div style="padding:10px 12px;color:var(--tlo);font-family:monospace;font-size:10px">資料暫缺</div>`;
    }
    h += `<div style="padding:6px 12px 0;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5">` +
      `資料：${escapeHTML(f._source || '—')} · 詳細公式請點主圖資訊列「?」` +
      `</div>`;
    return h;
  }

  function renderEmpty(f) {
    const note = (f && (f._note || f.scoreNote)) || '';
    const isIntl = f && (f.market === 'US' || f.market === 'JP' ||
      (typeof window !== 'undefined' && currentState() && currentState().mkt && currentState().mkt !== 'TW'));
    const kind = f && f.kind;
    let hint;
    if (kind === 'macro' || kind === 'index')
      hint = note || (kind === 'macro' ? '總經序列無個股基本面' : '指數無公司財報評分');
    else if (isIntl)
      hint = note || 'Yahoo 成長／三率暫無資料（可檢查本機是否可連 Yahoo / 已裝 yfinance）';
    else
      hint = note || 'TWSE OpenAPI 僅上市櫃普通股；金融/ETF 部分欄位缺';
    return `<div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px;line-height:1.7">無基本面資料<br><span style="font-size:9px;color:var(--tf)">${escapeHTML(hint)}</span></div>`;
  }

  function render(f) {
    if (f && (f.kind === 'market' || f.kind === 'market_risk' ||
              f.kind === 'margin_cycle' || f.kind === 'holders')) return renderPlainMarket(f);
    const isIntl = f && (f.market === 'US' || f.market === 'JP' ||
      (typeof window !== 'undefined' && currentState() && currentState().mkt && currentState().mkt !== 'TW' &&
       f.market !== 'TW'));
    if (!f || (!f.revenue && !f.income)) return renderEmpty(f);

    let h = '';
    const V = (typeof window !== 'undefined') ? window.Viz : null;
    if (f.score != null) {
      h += `<div class="stat-row" style="font-weight:700"><span class="stat-k">基本面評分</span><span class="stat-v">${scoreBadge(f.score)}</span></div>`;
      if (V) h += `<div style="padding:0 12px 4px">${V.scoreMeter(f.score)}</div>`;
    }
    if (f.scoreNote) {
      h += `<div style="padding:4px 12px 2px;color:var(--tf);font-family:monospace;font-size:9.5px;line-height:1.5">${escapeHTML(f.scoreNote)}</div>`;
    }

    const r = f.revenue;
    if (r) {
      if (isIntl) {
        // 美／日股：顯示 Yahoo 成長（沒有月營收金額）
        const periodDisp = escapeHTML(r.period || '');
        const labelDisp = escapeHTML(r.label || 'Yahoo');
        h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">成長 ${periodDisp}</span><span class="stat-v">${labelDisp}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">營收成長 YoY</span><span class="stat-v" style="color:${pctCol(r.yoyPct)}">${pctStr(r.yoyPct)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">盈餘成長</span><span class="stat-v" style="color:${pctCol(r.cumYoyPct)}">${pctStr(r.cumYoyPct)}</span></div>`;
      } else {
        // 台股月營收：periodLabel 給人看、monthRev 轉元後 fmtMoney
        const periodDisp = escapeHTML(r.periodLabel || r.period || '');
        const mult = r.unitMultiplier;
        const monthYuan = (r.monthRev == null) ? null : toYuan(r.monthRev, mult);
        const monthStr = (r.monthRev == null) ? '—' : fmtMoney(monthYuan);
        h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">臺股月營收 ${periodDisp}</span><span class="stat-v">${monthStr}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">YoY 年增</span><span class="stat-v" style="color:${pctCol(r.yoyPct)}">${pctStr(r.yoyPct)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">MoM 月增</span><span class="stat-v" style="color:${pctCol(r.momPct)}">${pctStr(r.momPct)}</span></div>`;
        if (r.cumRev != null) {
          const cumYuan = toYuan(r.cumRev, mult);
          h += `<div class="stat-row"><span class="stat-k">累計營收</span><span class="stat-v">${fmtMoney(cumYuan)}</span></div>`;
        }
        h += `<div class="stat-row"><span class="stat-k">累計營收 YoY</span><span class="stat-v" style="color:${pctCol(r.cumYoyPct)}">${pctStr(r.cumYoyPct)}</span></div>`;
        // 期別備註（不聲稱 PIT；僅說明顯示的是較舊期）
        if (r.expectedPeriod && r.priorPeriod) {
          h += `<div style="padding:2px 12px;color:var(--tf);font-family:monospace;font-size:9px">目前取得較舊期 ${periodDisp}；最近完整月份為 ${escapeHTML(String(r.expectedPeriod))}，可能尚未申報或來源暫缺。</div>`;
        }
        if (r.sourceName || r.sourceDate) {
          h += `<div style="padding:2px 12px;color:var(--tf);font-family:monospace;font-size:9px">來源：${escapeHTML(r.sourceName || '')}${r.sourceDate ? '｜出表日 ' + escapeHTML(String(r.sourceDate)) : ''}</div>`;
        }
      }
    }

    const inc = f.income;
    if (inc) {
      const isFin = inc.marginStatus === 'not_applicable';
      const epsStr = (inc.eps != null && isFinite(Number(inc.eps))) ? Number(inc.eps).toFixed(2) : '—';
      const epsUnit = inc.epsUnit ? ' ' + escapeHTML(inc.epsUnit) : '';
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">財報 ${escapeHTML(inc.period || '')}</span><span class="stat-v">EPS ${epsStr}${epsUnit}</span></div>`;
      if (inc.periodNote) h += `<div style="padding:2px 12px;color:var(--tf);font-size:9px">${escapeHTML(inc.periodNote)}</div>`;
      if (inc.industry) {
        const codeDisp = inc.industryCode ? ' (' + escapeHTML(String(inc.industryCode)) + ')' : '';
        h += `<div class="stat-row"><span class="stat-k">產業</span><span class="stat-v">${escapeHTML(inc.industry)}${codeDisp}</span></div>`;
      }
      if (isFin) {
        // 金融業：顯示 EPS + 稅後／母公司業主淨利；三率明示不適用
        const niYuan = toYuan(inc.netIncome, inc.unitMultiplier);
        const pniYuan = toYuan(inc.parentNetIncome, inc.unitMultiplier);
        h += `<div class="stat-row"><span class="stat-k">稅後淨利</span><span class="stat-v">${inc.netIncome == null ? '—' : fmtMoney(niYuan)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">母公司業主淨利</span><span class="stat-v">${inc.parentNetIncome == null ? '—' : fmtMoney(pniYuan)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">毛利率</span><span class="stat-v" style="color:var(--tlo)">不適用</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">營益率</span><span class="stat-v" style="color:var(--tlo)">不適用</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">淨利率</span><span class="stat-v" style="color:var(--tlo)">不適用</span></div>`;
        if (inc.marginNote) {
          h += `<div style="padding:2px 12px;color:var(--tf);font-family:monospace;font-size:9px">${escapeHTML(inc.marginNote)}</div>`;
        }
      } else {
        // 一般業：三率；空白(null) 顯示 '—'，0 清楚顯示為 0.0%
        const mFmt = v => (v == null || !isFinite(Number(v))) ? '—' : (Number(v).toFixed(1) + '%');
        h += `<div class="stat-row"><span class="stat-k">毛利率</span><span class="stat-v" style="color:${marginCol(inc.grossMargin)}">${mFmt(inc.grossMargin)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">營益率</span><span class="stat-v" style="color:${marginCol(inc.opMargin)}">${mFmt(inc.opMargin)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">淨利率</span><span class="stat-v" style="color:${marginCol(inc.netMargin)}">${mFmt(inc.netMargin)}</span></div>`;
        if (inc.roe != null)
          h += `<div class="stat-row"><span class="stat-k">ROE</span><span class="stat-v" style="color:${marginCol(inc.roe)}">${Number(inc.roe).toFixed(1)}%</span></div>`;
        if (inc.netIncome != null) {
          const niYuan = toYuan(inc.netIncome, inc.unitMultiplier);
          h += `<div class="stat-row"><span class="stat-k">稅後淨利</span><span class="stat-v">${fmtMoney(niYuan)}</span></div>`;
        }
      }
      if (inc.sourceName || inc.sourceDate) {
        h += `<div style="padding:2px 12px;color:var(--tf);font-family:monospace;font-size:9px">來源：${escapeHTML(inc.sourceName || '')}${inc.sourceDate ? '｜出表日 ' + escapeHTML(String(inc.sourceDate)) : ''}</div>`;
      }
    }

    const src = isIntl
      ? `資料：Yahoo Finance（${escapeHTML(f._source || 'keystats')}）成長 + 三率`
      : '資料：證交所／櫃買中心／公開資訊觀測站。最新公開資料，不能還原歷史當時可取得的財報。';
    h += `<div style="padding:6px 12px 0;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5">${src}</div>`;
    return h;
  }

  (function patch() {
    if (typeof renderStats !== 'function') return setTimeout(patch, 120);
    if (typeof window !== 'undefined' && window._fundPatched) return;
    if (typeof window !== 'undefined') window._fundPatched = true;
    const orig = (typeof window !== 'undefined') ? window.renderStats : renderStats;
    const target = (typeof window !== 'undefined') ? window : (void 0);
    const wrapper = function () {
      const h = orig.apply(this, arguments);
      const S = (typeof window !== 'undefined') ? currentState() : null;
      if (!S || !S.sym) return h;

      const callSym = String(S.sym);
      const callMkt = String(S.mkt || 'TW');
      _fReqSeq += 1;
      const mySeq = _fReqSeq;
      _fLastReq = { sym: callSym.toUpperCase(), mkt: callMkt.toUpperCase(), seq: mySeq };

      fetchFund(callSym, callMkt).then(f => {
        // 僅在仍是「同 sym / 同 mkt」且是「最新代次」時才寫 DOM
        const curS = (typeof window !== 'undefined') ? currentState() : null;
        if (!curS) return;
        const curSym = curS.sym ? String(curS.sym).toUpperCase() : '';
        const curMkt = curS.mkt ? String(curS.mkt).toUpperCase() : 'TW';
        if (curSym !== callSym.toUpperCase() || curMkt !== callMkt.toUpperCase()) return;
        if (_fLastReq.seq !== mySeq) return;
        if (curS.tab !== 'stats') return;
        const stats = (typeof document !== 'undefined') ? document.getElementById('rpanel') : null;
        if (!stats) return;
        const ex = (typeof document !== 'undefined') ? document.getElementById('fund-sect') : null;
        const sectTitle = (f && (f.kind === 'market' || f.kind === 'market_risk' ||
            f.kind === 'margin_cycle' || f.kind === 'holders'))
          ? escapeHTML(f.title || (f.kind === 'market_risk' ? '市場風險' :
              (f.kind === 'margin_cycle' ? '融資週期' :
                (f.kind === 'holders' ? '籌碼集中度' : '大盤體質'))))
          : '基本面';
        const html = `<div id="fund-sect" data-sym="${escapeHTML(callSym)}" data-mkt="${escapeHTML(callMkt)}"><div class="stat-sect">${sectTitle} · ${escapeHTML(callSym)}</div>${render(f)}</div>`;
        if (ex) {
          // 若 null 結果但現有區塊屬於其它 symbol，避免抹掉
          const exSym = (ex.getAttribute ? ex.getAttribute('data-sym') : '') || '';
          if (f == null && exSym && exSym.toUpperCase() !== callSym.toUpperCase()) return;
          ex.outerHTML = html;
        } else {
          stats.insertAdjacentHTML('beforeend', html);
        }
      }).catch(() => { /* 吞錯：不覆蓋既有其它 symbol 的區塊 */ });

      return h + `<div id="fund-sect" data-sym="${escapeHTML(callSym)}" data-mkt="${escapeHTML(callMkt)}"><div class="stat-sect">基本面 · ${escapeHTML(callSym)}</div><div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px">載入基本面中...</div></div>`;
    };
    if (target) target.renderStats = wrapper;
  })();

  if (typeof window !== 'undefined') {
    window.fetchFund = fetchFund;

  }
})();
