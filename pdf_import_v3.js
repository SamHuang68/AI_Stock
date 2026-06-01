// ============================================================
// Stock Terminal v3.4 — PDF Plan Importer
// ------------------------------------------------------------
// 解析「下周執行總表」格式的 PDF，自動填入 plan_v3 的 S.plans。
//
// 支援格式範例（PDF 一行通常被拆成多個 text item）：
//   智原 3035 ⾼本益比轉機 站穩 211，突破 216.5～220 205～211 守住可試 216.5～220 破 205 減碼；破 190～200 轉弱
//
// 解析策略：
//   1. 從文字流找出 (中文名 + 4位數字代號) 的 anchor 點
//   2. 每個 anchor 取到下個 anchor 為止 = 該股的整段描述
//   3. 用 regex 提取：
//        - 第一組 "X～X" 範圍 → buyZone
//        - "突破 X" → resistance
//        - "破 X 減碼" → stopLoss
//        - "破 X 走弱/出場/反彈失敗/轉弱" → weakBreak
//   4. 從「倉位⾓⾊」或「定位」欄推 role
//
// pdf.js 從 CDN 延遲載入（首次用時抓）
// ============================================================

(function (global) {
  'use strict';

  const PDFJS_URL = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
  const PDFJS_WORKER_URL = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  // ── Common TW name → code map (helps when PDF text reorders the chars) ──
  // 這份內建表只是為了 cross-check；主要 anchor 還是用 4 位數字代號定位。
  const TW_NAMES = {
    '智原': '3035', '微星': '2377', '技嘉': '2376', '力成': '6239', '⼒成': '6239',
    '台積電': '2330', '聯發科': '2454', '聯電': '2303', '日月光投控': '3711',
    '鴻海': '2317', '廣達': '2382', '緯創': '3231', '英業達': '2356',
    '台達電': '2308', '中華電': '2412', '富邦金': '2881', '國泰金': '2882',
    '玉山金': '2884', '兆豐金': '2886', '元大金': '2885', '第一金': '2892',
    '統一': '1216', '台塑': '1301', '南亞': '1303', '長榮': '2603', '陽明': '2609',
    '萬海': '2615', '華航': '2610', '長榮航': '2618', '世芯-KY': '3661',
    '創意': '3443', '貿聯-KY': '3665', '緯穎': '6669', '群創': '3481',
    '友達': '2409', '可成': '2474', '大立光': '3008', '台光電': '2383',
  };

  // ─── PDF.js loader (lazy) ────────────────────────────────────
  let _pdfjsLoadPromise = null;
  function loadPdfJs() {
    if (global.pdfjsLib) {
      return Promise.resolve(global.pdfjsLib);
    }
    if (_pdfjsLoadPromise) return _pdfjsLoadPromise;
    _pdfjsLoadPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = PDFJS_URL;
      s.onload = () => {
        if (!global.pdfjsLib) return reject(new Error('pdf.js loaded but pdfjsLib missing'));
        try {
          global.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
        } catch (e) { console.warn('[v3-pdf] worker setup:', e); }
        resolve(global.pdfjsLib);
      };
      s.onerror = () => reject(new Error('pdf.js CDN 載入失敗（網路問題？）'));
      document.head.appendChild(s);
    });
    return _pdfjsLoadPromise;
  }

  // ─── Extract raw text from PDF File object ────────────────────
  async function extractText(file) {
    const pdfjsLib = await loadPdfJs();
    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    let allText = '';
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const tc = await page.getTextContent();
      const lineMap = new Map();   // y → array of {x, str}
      for (const it of tc.items) {
        const y = Math.round(it.transform[5]);
        const x = it.transform[4];
        if (!lineMap.has(y)) lineMap.set(y, []);
        lineMap.get(y).push({ x, str: it.str });
      }
      // sort lines top→bottom (PDF y increases upward; we want descending)
      const sortedY = [...lineMap.keys()].sort((a, b) => b - a);
      for (const y of sortedY) {
        const items = lineMap.get(y).sort((a, b) => a.x - b.x);
        allText += items.map(it => it.str).join(' ') + '\n';
      }
      allText += '\n--- PAGE ' + i + ' END ---\n';
    }
    return allText;
  }

  // ─── Helpers ──────────────────────────────────────────────────
  function normNum(s) {
    if (!s) return null;
    const f = parseFloat(String(s).replace(/[, ]/g, ''));
    return Number.isFinite(f) ? f : null;
  }

  // Normalize all 3 tilde variants (~ ～ 〜) to ASCII ~
  function normTilde(s) {
    return s.replace(/[～〜]/g, '~');
  }

  // ─── Parse ONE stock block ───────────────────────────────────
  // Returns { buyZoneLow, buyZoneHigh, resistance, stopLoss, weakBreak, longCondition, ... }
  function parseStockBlock(text) {
    const t = normTilde(text);
    const out = {};

    // 1) "突破 X" 或 "突破 X~Y" 或 "放量過 X" → 壓力 (取較大值)
    const breakUp = t.match(/(?:突破|放量過|放量站上)\s*(\d+(?:\.\d+)?)(?:\s*~\s*(\d+(?:\.\d+)?))?/);
    if (breakUp) {
      const a = normNum(breakUp[1]);
      const b = normNum(breakUp[2]);
      out.resistance = (b != null) ? Math.max(a, b) : a;
    }

    // 2) 可買區 = 第一組 "X~X" 範圍 — 但要排除位於「突破/放量過/破」附近的 range
    //    (那些是 resistance / weakBreak，不是 buyZone)
    //    策略：先把所有 range 連同前文 6 字提取出來，排除前文含「突破/放量過/破」的
    const allRanges = [...t.matchAll(/(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)/g)];
    for (const m of allRanges) {
      // 取緊鄰前綴 5 chars，檢查是否 "突破/放量過/放量站上/破" 直接前置
      const before = t.slice(Math.max(0, m.index - 5), m.index);
      if (/(?:突破|放量過|放量站上|破)\s*$/.test(before)) continue;
      const lo = normNum(m[1]), hi = normNum(m[2]);
      if (lo != null && hi != null) {
        out.buyZoneLow = Math.min(lo, hi);
        out.buyZoneHigh = Math.max(lo, hi);
        break;
      }
    }

    // 3) stopLoss = 破 X (減碼/減倉/轉弱/走弱/反彈失敗) — 第一道警報
    //    weakBreak = 破 X (出場) — 最終出場線
    //    注意：「轉弱」是中等警告，當沒有單獨「出場」級別時也可當 weakBreak
    const stopMatch = t.match(/破\s*(\d+(?:\.\d+)?)\s*(?:減碼|減倉|轉弱|走弱|⾛弱|反彈失敗)/);
    if (stopMatch) out.stopLoss = normNum(stopMatch[1]);

    // weakBreak — 優先找「出場」級別；如無，退而求其次用「轉弱」次低值
    const exitMatches = [...t.matchAll(/破\s*(\d+(?:\.\d+)?)\s*(?:~\s*(\d+(?:\.\d+)?))?\s*出場/g)];
    if (exitMatches.length) {
      const vals = [];
      for (const m of exitMatches) {
        const a = normNum(m[1]);
        const b = normNum(m[2]);
        if (a != null) vals.push(a);
        if (b != null) vals.push(b);
      }
      if (vals.length) out.weakBreak = Math.min(...vals);
    } else {
      // 沒有「出場」就用「轉弱/走弱/反彈失敗」的範圍下緣
      const weakMatches = [...t.matchAll(/破\s*(\d+(?:\.\d+)?)\s*(?:~\s*(\d+(?:\.\d+)?))?\s*(?:走弱|⾛弱|反彈失敗|轉弱)/g)];
      if (weakMatches.length) {
        const vals = [];
        for (const m of weakMatches) {
          const a = normNum(m[1]);
          const b = normNum(m[2]);
          if (a != null) vals.push(a);
          if (b != null) vals.push(b);
        }
        // Pick a value lower than stopLoss to avoid duplication
        const min = Math.min(...vals);
        if (out.stopLoss == null || min < out.stopLoss) out.weakBreak = min;
      }
    }

    // 4) 多方條件文字：抓「站穩 X(，)? 突破 Y」或「站上 X」或「守住 X」整句
    //    (允許全形/半形逗號)
    const cond = t.match(/((?:站穩|站上|守住)\s*\d+(?:\.\d+)?[^；。\n]{0,30}?(?:突破|放量過|放量站上)\s*\d+(?:\.\d+)?(?:\s*~\s*\d+(?:\.\d+)?)?)/);
    if (cond) {
      // 清理多餘空白與重複字
      out.longCondition = cond[1].replace(/\s+/g, ' ').trim();
    } else {
      const simple = t.match(/(站穩|站上|守住)\s*(\d+(?:\.\d+)?)/);
      if (simple) out.longCondition = `${simple[1]} ${simple[2]}`;
    }

    return out;
  }

  // ─── Extract per-stock blocks from full text ──────────────────
  // 找所有 (中文 + 4位數字) 的 anchor，取到下一個 anchor 為止 = 該股段落
  function extractBlocks(fullText) {
    // anchor pattern：1+ 個非空白非數字 chars + 空白 + 4 digits
    // 但中文可能含 〇 之類，用更寬鬆的 [^\s\d] 抓
    const blocks = [];
    const re = /([^\s\d]{2,8})\s+(\d{4})\b/g;
    const matches = [...fullText.matchAll(re)];
    // Filter out false positives: 4-digit non-stock numbers e.g. years 2026
    const filtered = matches.filter(m => {
      const code = m[2];
      // TW codes are 1000-9999 but exclude obvious years (2020-2099)
      const n = parseInt(code, 10);
      if (n >= 2020 && n <= 2099) {
        // Could be a year OR a real stock (2330, 2317 etc) — disambiguate by context
        // If preceded by Chinese stock name and followed by Chinese description, likely stock
        const name = m[1];
        // exclude common false anchors like "交易日" "資料基準" etc
        if (/[日年月期準源計畫表料下]/.test(name)) return false;
      }
      return true;
    });

    // De-dup: same code may appear in 總表 + 個股展望 section — keep BOTH, merge later
    for (let i = 0; i < filtered.length; i++) {
      const m = filtered[i];
      const startIdx = m.index;
      const endIdx = (i + 1 < filtered.length) ? filtered[i + 1].index : fullText.length;
      const block = fullText.slice(startIdx, endIdx);
      // Skip blocks too short to be useful
      if (block.length < 20) continue;
      blocks.push({
        name: m[1],
        code: m[2],
        text: block,
      });
    }
    return blocks;
  }

  // ─── Merge multiple blocks for same code (總表 + 個股細節) ──
  function mergeByCode(blocks) {
    const map = {};   // code → { name, text(combined) }
    for (const b of blocks) {
      if (!map[b.code]) {
        map[b.code] = { name: b.name, code: b.code, text: b.text };
      } else {
        map[b.code].text += '\n' + b.text;
        // Prefer pure-Chinese name (no garbled chars)
        if (b.name.length === 2 && !/[A-Za-z]/.test(b.name)) {
          map[b.code].name = b.name;
        }
      }
    }
    return map;
  }

  // ─── Extract role from 倉位⾓⾊ section (optional) ─────────────
  function extractRoles(fullText) {
    // 範例：
    //   倉位⾓⾊
    //   技嘉：主倉。
    //   ⼒成：短線動能倉。
    //   微星：攻擊倉。
    //   智原：觀察倉，不重倉追⾼。
    const roles = {};   // stockName → role
    const sectionMatch = fullText.match(/倉位[⾓角]?[⾊色]([\s\S]{0,500})/);
    const section = sectionMatch ? sectionMatch[1] : fullText;
    const lines = section.split(/[\n。；]/);
    for (const line of lines) {
      const m = line.match(/([^\s：:，,。0-9]{2,4})\s*[：:]\s*([^，,。\s]{2,8})/);
      if (m) {
        const name = m[1].trim();
        const desc = m[2].trim();
        let role = null;
        if (/動能/.test(desc)) role = '動能倉';
        else if (/攻擊/.test(desc)) role = '攻擊倉';
        else if (/觀察/.test(desc)) role = '觀察倉';
        else if (/主倉|主持/.test(desc)) role = '主倉';
        if (role) roles[name] = role;
      }
    }
    return roles;
  }

  // ─── Main parse pipeline ──────────────────────────────────────
  async function parseFile(file) {
    if (!file) throw new Error('沒有檔案');
    if (!/\.pdf$/i.test(file.name)) throw new Error('需要 PDF 檔');

    const fullText = await extractText(file);
    console.log('[v3-pdf] extracted', fullText.length, 'chars from', file.name);

    const blocks = extractBlocks(fullText);
    console.log('[v3-pdf] found', blocks.length, 'stock block anchors');

    const merged = mergeByCode(blocks);
    const roles = extractRoles(fullText);

    let imported = 0;
    const symbols = [];
    const failed = [];

    for (const code of Object.keys(merged)) {
      const block = merged[code];
      // Skip if code doesn't look like a real TW stock (1000-9999)
      const n = parseInt(code, 10);
      if (!Number.isFinite(n) || n < 1000 || n > 9999) continue;
      // Skip years 2020-2030 unless cross-ref'd by name
      if (n >= 2020 && n <= 2030 && !TW_NAMES[block.name]) continue;

      const parsed = parseStockBlock(block.text);
      // 必須至少有 1 個價位才算成功
      const hasPrice = Number.isFinite(parsed.buyZoneLow) || Number.isFinite(parsed.buyZoneHigh) ||
                       Number.isFinite(parsed.resistance) || Number.isFinite(parsed.stopLoss) ||
                       Number.isFinite(parsed.weakBreak);
      if (!hasPrice) {
        failed.push(`${block.name} ${code} — 找不到價位`);
        continue;
      }
      const role = roles[block.name] || '觀察倉';
      const outlook = '';   // could extract from individual section, omit for now

      if (typeof global.setPlan === 'function') {
        global.setPlan(code, 'TW', {
          ...parsed,
          role,
          outlook,
        });
        imported++;
        symbols.push(`${block.name} ${code}`);
      } else {
        failed.push(`${block.name} ${code} — setPlan 函數未載入`);
      }
    }

    console.log('[v3-pdf] imported', imported, 'plans:', symbols);
    if (failed.length) console.warn('[v3-pdf] failed:', failed);

    return { imported, symbols, failed, totalBlocks: blocks.length };
  }

  // ─── Expose ────────────────────────────────────────────────────
  global.PlanPdfImport = {
    parseFile,
    extractText,
    extractBlocks,
    parseStockBlock,
    loadPdfJs,
    _names: TW_NAMES,
  };

  console.log('[v3-pdf] PlanPdfImport module loaded (pdf.js lazy-loaded on first use)');

})(typeof window !== 'undefined' ? window : globalThis);
