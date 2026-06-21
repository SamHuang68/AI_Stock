// ============================================================
// Stock Terminal v2.0 — Info Tooltip System
// ------------------------------------------------------------
// 在指標、策略、劇本旁邊加 (i) 小圖示，點擊跳出浮動中文說明。
//
// 載入順序：position_v2.js → watch_v2.js → info_v2.js
// (需要 STRATEGIES / PRESETS / IND_DEFS / clearInd 已存在)
// ============================================================

// ── Knowledge base: indicator explanations ─────────────────
const INFO_CONTENT = {
  // ── 16 個技術指標 ──────────────────────────────────────
  'ind:rsi14': {
    title: 'RSI 14（相對強弱指標）',
    body:
      '【是什麼】\n' +
      '14 日內漲跌力道的比值，刻度 0~100。\n\n' +
      '【怎麼看】\n' +
      '• > 70：短線過熱（超買），可能回檔\n' +
      '• < 30：短線過冷（超賣），可能反彈\n' +
      '• 50：多空均勢\n\n' +
      '【實戰】\n' +
      '小白用法：跌到 < 30 觀察反彈、漲到 > 70 考慮減碼。\n' +
      '進階：強勢股 RSI 可長期 > 70 不必急著賣（叫做「強勢市場 walk-up」）。'
  },
  'ind:K': {
    title: 'KD-K（隨機指標 K 值）',
    body:
      '【是什麼】\n' +
      'KD 指標的「快線」，反應近期收盤價在週期內高低區間的位置。\n\n' +
      '【怎麼看】\n' +
      '• K > D：短線轉強（黃金交叉買進）\n' +
      '• K < D：短線轉弱（死亡交叉賣出）\n' +
      '• K > 80 過熱、K < 20 過冷\n\n' +
      '【實戰】\n' +
      'K 在 < 20 區突破 D（低檔黃金交叉）勝率最高。'
  },
  'ind:D': {
    title: 'KD-D（隨機指標 D 值）',
    body:
      '【是什麼】\n' +
      'KD 指標的「慢線」，是 K 的平滑均值，反應較慢但較穩。\n\n' +
      '【怎麼看】\n' +
      '與 K 搭配判斷交叉訊號。D 比 K 更接近「趨勢」，K 比較跳。'
  },
  'ind:macd': {
    title: 'MACD（指數平滑異同移動平均線）',
    body:
      '【是什麼】\n' +
      '12 日 EMA - 26 日 EMA 的差值，反映中期動能變化。\n\n' +
      '【怎麼看】\n' +
      '• MACD > 0：多頭動能（藍線在零軸上）\n' +
      '• MACD < 0：空頭動能\n' +
      '• MACD 上穿訊號線（Signal）：黃金交叉買進\n\n' +
      '【實戰】\n' +
      '搭配「MACD Hist 由負轉正」+ 價格突破前高，是強動能訊號。'
  },
  'ind:macdHist': {
    title: 'MACD Hist（MACD 柱狀圖）',
    body:
      '【是什麼】\n' +
      'MACD 線 - 訊號線（Signal）的差值，最敏感的動能指標。\n\n' +
      '【怎麼看】\n' +
      '• Hist > 0 且漸大：多頭動能加速\n' +
      '• Hist > 0 但漸小：多頭動能減弱\n' +
      '• Hist 由負轉正：動能由空轉多（買進訊號）\n' +
      '• Hist 由正轉負：動能由多轉空（賣出訊號）'
  },
  'ind:sma5': {
    title: 'SMA 5（5 日簡單移動平均）',
    body:
      '【是什麼】\n' +
      '最近 5 個交易日收盤價的平均，反映短線趨勢。\n\n' +
      '【怎麼看】\n' +
      '• 價 > SMA5：短線多頭\n' +
      '• 價 < SMA5：短線弱勢\n' +
      '• SMA5 朝上：上漲動能；朝下：下跌動能'
  },
  'ind:sma20': {
    title: 'SMA 20（20 日簡單移動平均）',
    body:
      '【是什麼】\n' +
      '近 20 個交易日（約一個月）收盤平均，俗稱「月線」。\n\n' +
      '【怎麼看】\n' +
      '• 價 > SMA20 朝上：短中期多頭\n' +
      '• 強勢股回檔常停在 SMA20 不破（這就是「回測 SMA20」策略）\n' +
      '• 跌破 SMA20 = 短線轉弱，要警覺'
  },
  'ind:sma60': {
    title: 'SMA 60（60 日簡單移動平均）',
    body:
      '【是什麼】\n' +
      '近 60 個交易日（約一季）收盤平均，俗稱「季線」。\n\n' +
      '【怎麼看】\n' +
      '• 價 > SMA60：中期趨勢偏多（多頭結構）\n' +
      '• 價 < SMA60：中期趨勢偏空（空頭結構）\n' +
      '• SMA60 是中線進出的關鍵分水嶺\n\n' +
      '【實戰】\n' +
      '專業投資人最重視 SMA60。多頭中跌回 SMA60 是經典加碼點；跌破 SMA60 太多通常該停損。'
  },
  'ind:bbU': {
    title: 'BB Upper（布林通道上軌）',
    body:
      '【是什麼】\n' +
      'SMA20 + 2 個標準差，統計上 97.5% 的價格落在此線下。\n\n' +
      '【怎麼看】\n' +
      '• 價觸碰或突破上軌：短線過熱\n' +
      '• 配合 RSI > 70：高機率回檔（停利訊號）\n' +
      '• 強勢突破上軌且帶量：突破訊號（少數狀況）'
  },
  'ind:bbL': {
    title: 'BB Lower（布林通道下軌）',
    body:
      '【是什麼】\n' +
      'SMA20 - 2 個標準差，統計上 97.5% 的價格落在此線上。\n\n' +
      '【怎麼看】\n' +
      '• 價觸碰或跌破下軌：短線超賣\n' +
      '• 配合 RSI < 30：高機率反彈（承接訊號）\n' +
      '• 強勢下跌可沿下軌長期下行（叫 "walk the band"，要小心）'
  },
  'ind:atr14': {
    title: 'ATR 14（14 日平均真實波幅）',
    body:
      '【是什麼】\n' +
      '近 14 日平均「真實波幅」，反映個股的「正常波動程度」。\n\n' +
      '【怎麼看】\n' +
      '• ATR 高：股性活潑，需設較寬停損\n' +
      '• ATR 低：股性穩定，可設較緊停損\n\n' +
      '【實戰】\n' +
      '常用設停損：「進場價 - 2× ATR」是專業投資人公式之一。'
  },
  'ind:annVol': {
    title: 'Ann Vol%（年化波動率）',
    body:
      '【是什麼】\n' +
      '把日波動度年化，是「風險」的量化指標。\n\n' +
      '【怎麼看】\n' +
      '• < 20%：穩定（如金融股、ETF）\n' +
      '• 20%~40%：正常（多數中大型股）\n' +
      '• > 40%：高波動（小型股、生技、加密）\n\n' +
      '【實戰】\n' +
      '波動越高，部位應越小。資金管理依波動度調整很重要。'
  },
  'ind:maxdd': {
    title: 'MaxDD%（最大回撤）',
    body:
      '【是什麼】\n' +
      '從觀察期內最高點到最低點的最大跌幅，反映「最壞情況」。\n\n' +
      '【怎麼看】\n' +
      '• MaxDD 5%：抗跌\n' +
      '• MaxDD 15%：正常\n' +
      '• MaxDD 30%+：高風險\n\n' +
      '【實戰】\n' +
      '配合自己心理可承受的回撤評估是否進場。'
  },
  'ind:volRatio': {
    title: 'Vol Ratio（量能比）',
    body:
      '【是什麼】\n' +
      '5 日均量 / 20 日均量。反映近期成交量是否異常。\n\n' +
      '【怎麼看】\n' +
      '• > 1.5：量能放大（有人積極進出）\n' +
      '• > 2.0：明顯異常（突破或主力出貨）\n' +
      '• < 0.7：量縮（觀望、整理）\n\n' +
      '【實戰】\n' +
      '量增價漲 = 突破確認；量增價跌 = 出貨警示。'
  },
  'ind:d2SMA20': {
    title: 'D2-SMA20%（距 SMA20 偏離 %）',
    body:
      '【是什麼】\n' +
      '當前價格距 20 日均線的偏離百分比。\n\n' +
      '【怎麼看】\n' +
      '• +5%~+10%：短線過熱可能回檔\n' +
      '• -5%~-10%：短線超賣可能反彈\n' +
      '• 0% 附近：剛好在均線\n\n' +
      '【實戰】\n' +
      '偏離過大（> 15%）往往就是均值回歸的時機。'
  },
  'ind:etfFlow': {
    title: 'ETF Flow（主動 ETF 買賣資金流）',
    body:
      '【是什麼】\n' +
      '台灣 10 檔主動式 ETF 對該股的進出變化（需先跑 etf_delta_tracker.py 累積資料）。\n\n' +
      '【怎麼看】\n' +
      '• +N：N 檔主動 ETF 新買進該股\n' +
      '• -N：N 檔主動 ETF 賣出該股\n' +
      '• 多檔同步買進 = 法人共識偏多\n\n' +
      '【實戰】\n' +
      '法人籌碼背書是強進場理由，但不代表絕對正確（法人也會看錯）。'
  },
};

// ── CSS for i icons + popup ───────────────────────────────
const INFO_CSS = `
.info-i{display:inline-flex;align-items:center;justify-content:center;width:12px;height:12px;border-radius:50%;background:var(--bg3);color:var(--tlo);font-size:8px;font-weight:700;cursor:pointer;user-select:none;margin-left:4px;font-family:'JetBrains Mono',monospace;font-style:italic;transition:all .12s;vertical-align:middle;line-height:1}
.info-i:hover{background:var(--gold-s);color:var(--gold);transform:scale(1.15)}
.info-popup{position:fixed;z-index:10000;width:340px;max-width:90vw;max-height:70vh;overflow-y:auto;background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;padding:14px 16px 12px;box-shadow:0 12px 36px rgba(0,0,0,.6),0 0 0 1px rgba(245,197,24,.1)}
.info-popup-title{margin:0 24px 8px 0;font-family:'JetBrains Mono',monospace;font-size:12.5px;font-weight:700;color:var(--gold);letter-spacing:.5px;line-height:1.4}
.info-popup-body{margin:0;font-family:'Noto Serif TC','PingFang TC',sans-serif;font-size:11.5px;color:var(--text);line-height:1.85;white-space:pre-line}
.info-popup-body b,.info-popup-body strong{color:var(--gold)}
.info-popup-close{position:absolute;top:6px;right:10px;cursor:pointer;color:var(--tlo);font-size:18px;line-height:1;padding:2px 6px;border-radius:3px;font-family:sans-serif}
.info-popup-close:hover{color:var(--red);background:rgba(248,113,113,.1)}
.info-i-lg{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:var(--bg3);color:var(--tlo);font-size:9.5px;font-weight:700;cursor:pointer;font-style:italic;font-family:'JetBrains Mono',monospace;margin-left:6px;transition:all .12s;vertical-align:middle;line-height:1}
.info-i-lg:hover{background:var(--gold-s);color:var(--gold);transform:scale(1.15)}
`;

(function injectStyles() {
  const s = document.createElement('style');
  s.id = 'info-v2-styles';
  s.textContent = INFO_CSS;
  document.head.appendChild(s);
})();

// ── Tooltip rendering ──────────────────────────────────────
let _curPopup = null;

function showInfo(key, x, y) {
  hideInfo();
  const data = INFO_CONTENT[key];
  if (!data) {
    console.warn('[v2-info] unknown key:', key);
    return;
  }
  const popup = document.createElement('div');
  popup.className = 'info-popup';
  popup.innerHTML =
    `<span class="info-popup-close" data-info-close="1">×</span>` +
    `<div class="info-popup-title">${escI(data.title)}</div>` +
    `<div class="info-popup-body">${escI(data.body)}</div>`;
  document.body.appendChild(popup);

  // Smart positioning
  const W = 340, H = popup.offsetHeight;
  let left = x + 14;
  let top  = y + 14;
  if (left + W > window.innerWidth - 8) left = x - W - 14;
  if (top + H > window.innerHeight - 8) top = Math.max(8, window.innerHeight - H - 8);
  if (left < 8) left = 8;
  if (top < 8) top = 8;
  popup.style.left = left + 'px';
  popup.style.top = top + 'px';

  _curPopup = popup;

  // Close on outside click (deferred 1 tick so this click doesn't fire it)
  setTimeout(() => {
    document.addEventListener('mousedown', _outsideClose, { capture: true });
    document.addEventListener('keydown', _escClose);
  }, 0);
}

function hideInfo() {
  if (_curPopup) { _curPopup.remove(); _curPopup = null; }
  document.removeEventListener('mousedown', _outsideClose, { capture: true });
  document.removeEventListener('keydown', _escClose);
}

function _outsideClose(ev) {
  if (_curPopup && !_curPopup.contains(ev.target) && !ev.target.closest('[data-info]')) {
    hideInfo();
  }
}
function _escClose(ev) { if (ev.key === 'Escape') hideInfo(); }

function escI(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// ── Global click delegation ────────────────────────────────
document.addEventListener('click', function (ev) {
  const closeBtn = ev.target.closest('[data-info-close]');
  if (closeBtn) { ev.preventDefault(); ev.stopPropagation(); hideInfo(); return; }
  const trigger = ev.target.closest('[data-info]');
  if (trigger) {
    ev.preventDefault();
    ev.stopPropagation();
    showInfo(trigger.dataset.info, ev.clientX, ev.clientY);
  }
});

// ── Auto-register strategies + presets from watch_v2.js ────
(function loadStrategyAndPresetInfo() {
  if (typeof STRATEGIES === 'undefined' || typeof PRESETS === 'undefined') {
    return setTimeout(loadStrategyAndPresetInfo, 100);
  }
  for (const s of STRATEGIES) {
    INFO_CONTENT['strat:' + s.key] = {
      title: `${s.icon} ${s.lbl}　${s.difficulty}`,
      body:
        '【說明】\n' + s.desc +
        '\n\n【原理】\n' + s.why +
        '\n\n【適用場景】\n' + s.when +
        '\n\n【觸發後行動】\n' + s.action,
    };
  }
  for (const p of PRESETS) {
    const sigList = (p.signals || []).map(sig => {
      const st = STRATEGIES.find(x => x.key === sig.strategy);
      const paramHint = sig.params?.tolerance ? ` ±${sig.params.tolerance}%`
                     : sig.params?.days ? ` ${sig.params.days}日`
                     : sig.params?.target === null ? ' (你填價格)' : '';
      return st ? `• ${st.icon} ${st.lbl}${paramHint}` : `• ${sig.strategy}`;
    }).join('\n');
    INFO_CONTENT['preset:' + p.key] = {
      title: `${p.icon} ${p.lbl}（劇本）`,
      body:
        '【說明】\n' + p.desc +
        '\n\n【適用】\n' + p.when +
        `\n\n【包含 ${p.signals.length} 個訊號】\n` + sigList +
        '\n\n【為何組合】\n' +
        '單一訊號勝率有限，多訊號共振 (Confluence) 可把勝率推到 70~80%。\n' +
        '這個劇本經過專業投資人常用組合篩選，互相補強不同維度。',
    };
  }
  console.log('[v2-info] loaded', Object.keys(INFO_CONTENT).length, 'info entries');
})();

// ── Patch v1's clearInd to add (i) icons next to indicator labels ──
(function patchClearInd() {
  if (typeof clearInd !== 'function' || typeof IND_DEFS === 'undefined') {
    return setTimeout(patchClearInd, 100);
  }
  window.clearInd = function () {
    const el = document.getElementById('ig-cells');
    if (!el) return;
    el.innerHTML = IND_DEFS.map(d =>
      `<div class="igcell">` +
        `<div class="ig-lbl">${d.lbl}<span class="info-i" data-info="ind:${d.k}">i</span></div>` +
        `<div class="ig-val" id="ig-${d.k}">--</div>` +
      `</div>`
    ).join('');
  };
  // Re-render with the new template
  if (typeof clearInd === 'function') clearInd();
  console.log('[v2-info] indicator (i) icons attached');
})();

// ── Expose helpers ─────────────────────────────────────────
window.INFO_CONTENT = INFO_CONTENT;
window.showInfo     = showInfo;
window.hideInfo     = hideInfo;
