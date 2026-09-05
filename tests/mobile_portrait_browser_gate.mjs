/**
 * 真實 Chromium 幾何閘門：驗證 ST 十六個功能頁在手機直立視窗可完整瀏覽。
 *
 * 用法：node tests/mobile_portrait_browser_gate.mjs
 * 可用 ST_TEST_URL / CHROME_PATH 覆寫本機網址與 Chrome 路徑。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { checkHeatViewport } from './heat_viewport_checks.mjs';

const testUrl = process.env.ST_TEST_URL || 'http://127.0.0.1:18432/#chart';
const chromeCandidates = [
  process.env.CHROME_PATH,
  process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe'),
  process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, 'Google', 'Chrome', 'Application', 'chrome.exe'),
  process.env['PROGRAMFILES(X86)'] && path.join(process.env['PROGRAMFILES(X86)'], 'Google', 'Chrome', 'Application', 'chrome.exe'),
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser'
].filter(Boolean);
const routes = [
  'pulse', 'decision', 'breadth', 'heat', 'institutional', 'international',
  'afterhours', 'signals', 'ai', 'watchlist', 'risk', 'factors', 'news',
  'scan', 'book', 'settings'
];
const viewports = [
  { width: 375, height: 667, label: '375x667' },
  { width: 390, height: 844, label: '390x844' },
  { width: 430, height: 932, label: '430x932' }
];
const evidenceDir = process.env.ST_EVIDENCE_DIR || path.resolve('logs/手機直式驗證');
const linksOnly = process.env.ST_LINKS_ONLY === '1';
const heatOnly = process.env.ST_HEAT_ONLY === '1';
const analysisKeys = ['stats', 'research', 'position', 'watch', 'plan', 'etf'];

async function tap(send, selector) {
  const point = await evaluate(send, `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el || el.disabled) throw new Error('點按目標不存在或已停用');
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (!el.contains(document.elementFromPoint(x,y))) throw new Error('點按目標被遮擋');
    return {x,y};
  })()`);
  await send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[point]});
  await send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
  await sleep(350);
}

async function screenshot(send, name) {
  const shot = await send('Page.captureScreenshot', {format:'png'});
  await fs.writeFile(path.join(evidenceDir, name + '.png'), Buffer.from(shot.data, 'base64'));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function resolveChromePath() {
  for (const candidate of chromeCandidates) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {}
  }
  throw new Error('找不到 Chrome／Chromium；請以 CHROME_PATH 指定瀏覽器執行檔。');
}

async function waitForFile(file, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const text = await fs.readFile(file, 'utf8');
      if (text.trim()) return text;
    } catch {}
    await sleep(80);
  }
  throw new Error(`逾時：找不到 Chrome DevTools 連線檔 ${file}`);
}

async function connect(wsUrl) {
  if (typeof WebSocket !== 'function') {
    throw new Error('目前 Node.js 未提供 WebSocket；請使用專案支援的新版 Node.js。');
  }
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error('無法連線 Chrome DevTools。')), { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data));
    if (!message.id || !pending.has(message.id)) return;
    const pair = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) pair.reject(new Error(`${pair.method}: ${message.error.message}`));
    else pair.resolve(message.result || {});
  });
  function send(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject, method });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }
  return { ws, send };
}

async function evaluate(send, expression) {
  const result = await send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: false
  });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
    throw new Error(`瀏覽器腳本失敗：${detail}`);
  }
  return result.result?.value;
}

async function waitForApp(send) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const ready = await evaluate(send,
      `document.readyState !== 'loading' && document.documentElement.classList.contains('st5-booted') &&
        !!window.ShellV5 && !!document.getElementById('shell-views')`);
    if (ready) return;
    await sleep(120);
  }
  throw new Error('ST 頁面或 ShellV5 在 15 秒內未就緒。');
}

async function waitForRouteContent(send, route, timeoutMs = 15000) {
  const selector = {
    pulse: '#pl-root', decision: '#dc-root', breadth: '#bd-root', heat: '#ht-root',
    afterhours: '#ah-root', ai: '#ai5-root', news: '#nw-root', scan: '#sc-root', book: '#bk-root'
  }[route] || '.hub-root';
  const loadingSelector = {
    pulse: '#pl-body.pl-loading', breadth: '#bd-body.bd-loading', heat: '#ht-body.ht-loading',
    afterhours: '#ah-body.ah-loading', ai: '#ai5-body.ai5-loading', news: '#nw-body.nw-loading',
    institutional: '.hub-body>.hub-loading', international: '.hub-body>.hub-loading',
    signals: '.hub-body>.hub-loading', watchlist: '.hub-body>.hub-loading',
    risk: '.hub-body>.hub-loading', factors: '.hub-body>.hub-loading', settings: '.hub-body>.hub-loading'
  }[route] || '';
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ready = await evaluate(send, `(function(){
      const panel = document.getElementById('view-${route}');
      const root = panel && panel.querySelector(${JSON.stringify(selector)});
      if (!panel || !panel.classList.contains('on') || !root || root.innerText.trim().length < 20) return false;
      if (${JSON.stringify(loadingSelector)} && root.querySelector(${JSON.stringify(loadingSelector)})) return false;
      if (${JSON.stringify(route)} === 'breadth' && root.querySelectorAll('.bd-sec').length < 4) return false;
      if (${JSON.stringify(route)} === 'heat' && !root.querySelector('.ht-grid-wrap')) return false;
      if (${JSON.stringify(route)} === 'news' && !root.querySelector('.nw-left')) return false;
      return true;
    })()`);
    if (ready) return true;
    await sleep(140);
  }
  return false;
}

function measureExpression(route) {
  return `(async function(){
    const route = ${JSON.stringify(route)};
    const views = document.getElementById('shell-views');
    const panel = document.getElementById('view-' + route);
    const initialScroll = views ? views.scrollTop : 0;
    if (views) views.scrollTop = 0;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const rootSelectors = {
      pulse:'#pl-root', decision:'#dc-root', breadth:'#bd-root', heat:'#ht-root',
      afterhours:'#ah-root', ai:'#ai5-root', news:'#nw-root', scan:'#sc-root', book:'#bk-root'
    };
    const root = panel && (panel.querySelector(rootSelectors[route] || '.hub-root') || panel.firstElementChild);
    const vvWidth = Math.round((window.visualViewport && visualViewport.width) || innerWidth);
    const vvHeight = Math.round((window.visualViewport && visualViewport.height) || innerHeight);
    const rect = panel && panel.getBoundingClientRect();
    const rootRect = root && root.getBoundingClientRect();
    const actionSelector = [
      '.pl-actions button','.dc-actions button','.bd-actions button','.ht-actions button',
      '.hub-actions button','.ah-actions button','.ai5-actions button','.nw-actions button',
      '.sc-actions button','.bk-actions button'
    ].join(',');
    const controlSelector = actionSelector + ',button,[role="button"],[role="tab"],a[href],input,select';
    const visibleButtons = panel ? [...new Set(panel.querySelectorAll(controlSelector))].filter(el => {
      const css = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return !el.hidden && css.display !== 'none' && css.visibility !== 'hidden' && r.width >= 1 && r.height >= 1;
    }) : [];
    const isInsideLocalHorizontalScroller = (el) => {
      if (el.matches(actionSelector)) return false;
      let ancestor = el.parentElement;
      while (ancestor && ancestor !== panel && ancestor !== views) {
        const css = getComputedStyle(ancestor);
        if ((css.overflowX === 'auto' || css.overflowX === 'scroll') && ancestor.scrollWidth > ancestor.clientWidth + 2) {
          return true;
        }
        ancestor = ancestor.parentElement;
      }
      return false;
    };
    const offscreenControlDetails = visibleButtons.filter(el => {
      const r = el.getBoundingClientRect();
      return (r.left < -1 || r.right > vvWidth + 1) && !isInsideLocalHorizontalScroller(el);
    }).slice(0, 12).map(el => {
      const r = el.getBoundingClientRect();
      return {
        element: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
          (el.className && typeof el.className === 'string' ? '.' + el.className.trim().replace(/\\s+/g,'.') : ''),
        text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 36),
        left: Math.round(r.left), right: Math.round(r.right)
      };
    });
    let maxScroll = views ? Math.max(0, views.scrollHeight - views.clientHeight) : 0;
    /* 確認頁尾能停留，不只量到瞬間 scrollTop；同時容納非同步內容晚到。 */
    for (let pass = 0; views && pass < 3; pass += 1) {
      maxScroll = Math.max(0, views.scrollHeight - views.clientHeight);
      views.scrollTop = views.scrollHeight;
      await new Promise(resolve => setTimeout(resolve, 260));
      const nextMax = Math.max(0, views.scrollHeight - views.clientHeight);
      if (nextMax <= maxScroll + 1) {
        maxScroll = nextMax;
        break;
      }
      maxScroll = nextMax;
    }
    const actualScroll = views ? views.scrollTop : 0;
    const last = root && root.lastElementChild;
    const lastRect = last && last.getBoundingClientRect();
    const viewsRect = views && views.getBoundingClientRect();
    const wideElements = root && viewsRect ? [...root.querySelectorAll('*')].filter(el => {
      const css = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (css.display === 'none' || css.visibility === 'hidden' || r.width < 1 || r.height < 1) return false;
      let ancestor = el.parentElement;
      while (ancestor && ancestor !== root && ancestor !== views) {
        const overflow = getComputedStyle(ancestor).overflowX;
        if (overflow === 'auto' || overflow === 'scroll') return false;
        ancestor = ancestor.parentElement;
      }
      return r.left < viewsRect.left - 2 || r.right > viewsRect.right + 2;
    }).slice(0, 8).map(el => {
      const r = el.getBoundingClientRect();
      return {
        element: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
          (el.className && typeof el.className === 'string' ? '.' + el.className.trim().replace(/\\s+/g,'.') : ''),
        left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width)
      };
    }) : [];
    const data = {
      route,
      initialScroll,
      active: !!panel && panel.classList.contains('on') && !panel.hidden && getComputedStyle(panel).display !== 'none',
      root: !!root,
      textLength: root ? root.innerText.trim().length : 0,
      stub: !!(root && root.innerText.includes('面板載入中或尚未掛接資料模組')),
      viewport: [vvWidth, vvHeight],
      panelWidth: rect ? Math.round(rect.width) : 0,
      panelLeft: rect ? Math.round(rect.left) : 0,
      panelRight: rect ? Math.round(rect.right) : 0,
      rootHeight: rootRect ? Math.round(rootRect.height) : 0,
      outerOverflowX: views ? Math.max(0, Math.round(views.scrollWidth - views.clientWidth)) : -1,
      overflowY: views ? getComputedStyle(views).overflowY : '',
      maxScroll: Math.round(maxScroll),
      actualScroll: Math.round(actualScroll),
      bottomReachable: maxScroll < 2 || actualScroll >= maxScroll - 2,
      lastReachable: !lastRect || (lastRect.top < vvHeight && lastRect.bottom > 0),
      offscreenButtons: offscreenControlDetails.length,
      offscreenControlDetails,
      actionButtons: visibleButtons.length,
      wideElements,
      breadth: null,
      heat: null,
      news: null
    };
    if (route === 'breadth') {
      const sections = [...document.querySelectorAll('#bd-root .bd-sec')];
      const rects = sections.map(el => el.getBoundingClientRect());
      const mover = document.querySelector('#bd-root .bd-mover-groups');
      data.breadth = {
        sectionCount: sections.length,
        vertical: rects.every((rect, i) => !i || rect.top >= rects[i - 1].bottom - 1),
        moverColumns: mover ? getComputedStyle(mover).gridTemplateColumns.trim().split(/\\s+/).length : 0
      };
    }
    if (route === 'heat') {
      const cells = [...document.querySelectorAll('#ht-root .ht-cell')];
      const grid = document.querySelector('#ht-root .ht-grid');
      const wrap = document.querySelector('#ht-root .ht-grid-wrap');
      data.heat = {
        cellCount: cells.length,
        minCellHeight: cells.length ? Math.round(Math.min(...cells.map(el => el.getBoundingClientRect().height))) : 0,
        gridColumns: grid ? getComputedStyle(grid).gridTemplateColumns.trim().split(/\\s+/).length : 0,
        wrapHeight: wrap ? Math.round(wrap.getBoundingClientRect().height) : 0
      };
    }
    if (route === 'news') {
      const left = document.querySelector('#nw-root .nw-left');
      data.news = { leftVisible: !!left && getComputedStyle(left).display !== 'none' };
    }
    if (views) views.scrollTop = 0;
    return data;
  })()`;
}

function findingsFor(item) {
  const issues = [];
  if (!item.active) issues.push('作用中面板不可見');
  if (item.initialScroll > 2) issues.push('功能頁切換後未回到頁首');
  if (!item.root) issues.push('找不到功能頁根節點');
  if (item.textLength < 20) issues.push(`內容過少（${item.textLength} 字）`);
  if (item.stub) issues.push('仍顯示未掛接占位內容');
  if (item.panelLeft < -1 || item.panelRight > item.viewport[0] + 1) issues.push('面板超出視窗寬度');
  if (item.outerOverflowX > 2) issues.push(`整頁水平溢位 ${item.outerOverflowX}px`);
  if (!['auto', 'scroll'].includes(item.overflowY)) issues.push(`外層垂直捲動為 ${item.overflowY || '未定義'}`);
  if (!item.bottomReachable) issues.push('無法停留在頁面底部');
  if (!item.lastReachable) issues.push('最後一個內容區塊不可達');
  if (item.offscreenButtons) issues.push(`${item.offscreenButtons} 個互動控制橫向超界`);
  if (item.wideElements.length) {
    issues.push(`${item.wideElements.length} 個非局部捲動元素橫向超界`);
  }
  if (item.breadth) {
    if (item.breadth.sectionCount < 4) issues.push(`大盤廣度只有 ${item.breadth.sectionCount} 個資訊區`);
    if (!item.breadth.vertical) issues.push('大盤廣度資訊區未依序上下排列');
    if (item.breadth.sectionCount >= 4 && item.breadth.moverColumns !== 1) issues.push('大盤廣度強弱榜仍為左右並排');
  }
  if (item.heat) {
    if (!item.heat.cellCount) issues.push('產業輪動沒有可見產業格');
    if (item.heat.gridColumns !== 2) issues.push(`產業熱力格為 ${item.heat.gridColumns} 欄，預期 2 欄`);
    if (item.heat.cellCount && item.heat.minCellHeight < 50) issues.push(`產業格最小高度只有 ${item.heat.minCellHeight}px`);
    if (item.heat.wrapHeight < 150) issues.push(`產業區高度只有 ${item.heat.wrapHeight}px`);
  }
  if (item.news && !item.news.leftVisible) issues.push('快訊左側事件區被隱藏');
  return issues;
}

function chartMeasureExpression(expectedPage, pageIndex = 0) {
  return `(async function(){
    const expectedPage = ${JSON.stringify(expectedPage)};
    const pageIndex = ${pageIndex};
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const vvWidth = Math.round((visualViewport && visualViewport.width) || innerWidth);
    const vvHeight = Math.round((visualViewport && visualViewport.height) || innerHeight);
    const body = document.getElementById('body');
    const left = document.getElementById('left');
    const right = document.getElementById('right');
    const chart = document.getElementById('chartarea');
    const panel = document.getElementById('rpanel');
    const pager = document.getElementById('rpanel-pager');
    const label = document.getElementById('rpage-label');
    const bodyRect = body && body.getBoundingClientRect();
    const chartRect = chart && chart.getBoundingClientRect();
    const panelRect = panel && panel.getBoundingClientRect();
    const pagerRect = pager && pager.getBoundingClientRect();
    const isVisible = el => !!el && getComputedStyle(el).display !== 'none' &&
      getComputedStyle(el).visibility !== 'hidden' && el.getBoundingClientRect().width > 0 &&
      el.getBoundingClientRect().height > 0;
    const controls = [...document.querySelectorAll('#rpanel-pager button')].filter(isVisible);
    const initialScroll = panel ? panel.scrollTop : 0;
    if (panel && expectedPage === 'analysis') {
      panel.scrollTop = panel.scrollHeight;
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    const bottomReachable = !panel || panel.scrollTop >= panel.scrollHeight - panel.clientHeight - 2;
    const panelOverflow = panel ? panel.scrollWidth - panel.clientWidth : 0;
    const wideElements = [...document.querySelectorAll('body *')].filter(el => {
      if (!isVisible(el)) return false;
      const r = el.getBoundingClientRect();
      return r.left < -2 || r.right > vvWidth + 2;
    }).slice(0, 12).map(el => {
      const r = el.getBoundingClientRect();
      return {
        element: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
          (el.className && typeof el.className === 'string' ? '.' + el.className.trim().replace(/\\s+/g,'.') : ''),
        left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width)
      };
    });
    return {
      expectedPage,
      pageIndex,
      workspaceKey: body && body.getAttribute('data-mobile-workspace-key'),
      tab: typeof S !== 'undefined' ? S.tab : null,
      contentLength: panel ? panel.innerText.trim().length : 0,
      initialScroll, bottomReachable, panelOverflow,
      smallTargets: controls.filter(el => {const r=el.getBoundingClientRect(); return r.width < 24 || r.height < 24;}).length,
      panelAbovePager: !panelRect || !pagerRect || panelRect.bottom <= pagerRect.top + 1,
      analysisInteractive: !!right && getComputedStyle(right).opacity !== '0' && getComputedStyle(right).pointerEvents !== 'none',
      collapseHandleVisible: isVisible(document.getElementById('right-collapse')),
      route: document.documentElement.getAttribute('data-st5-route'),
      workspacePage: body && body.getAttribute('data-mobile-workspace-page'),
      label: label ? label.textContent.trim() : '',
      leftVisible: isVisible(left), rightVisible: isVisible(right), pagerVisible: isVisible(pager),
      bodyBounds: bodyRect ? [Math.round(bodyRect.left), Math.round(bodyRect.right)] : null,
      chartHeight: chartRect ? Math.round(chartRect.height) : 0,
      panelHeight: panelRect ? Math.round(panelRect.height) : 0,
      pagerBounds: pagerRect ? [Math.round(pagerRect.top), Math.round(pagerRect.bottom)] : null,
      viewport: [vvWidth, vvHeight],
      outerOverflowX: Math.max(0, Math.round(Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - vvWidth)),
      wideElements,
      offscreenControls: controls.filter(el => {
        const r = el.getBoundingClientRect();
        return r.left < -1 || r.right > vvWidth + 1 || r.top < -1 || r.bottom > vvHeight + 1;
      }).length
    };
  })()`;
}

function chartFindings(item, portrait) {
  const issues = [];
  if (item.route !== 'chart') issues.push(`圖表路由狀態為 ${item.route || '空白'}`);
  if (!item.bodyBounds || item.bodyBounds[0] < -1 || item.bodyBounds[1] > item.viewport[0] + 1) {
    issues.push('圖表工作區超出視窗寬度');
  }
  if (item.outerOverflowX > 2) issues.push(`圖表整頁水平溢位 ${item.outerOverflowX}px`);
  if (item.offscreenControls) issues.push(`${item.offscreenControls} 個圖表分頁控制超出視窗`);
  if (portrait) {
    const analysis = item.expectedPage === 'analysis';
    if (item.workspacePage !== item.expectedPage) issues.push(`直立工作區頁面為 ${item.workspacePage || '空白'}`);
    if (analysis ? item.leftVisible || !item.rightVisible : !item.leftVisible || item.rightVisible) {
      issues.push(analysis ? '分析頁未獨立顯示' : '線型圖頁未獨立顯示');
    }
    if (!item.pagerVisible || !item.pagerBounds || item.pagerBounds[1] > item.viewport[1] + 1) {
      issues.push('底部分頁索引不可見或超出視窗');
    }
    if (!analysis && item.chartHeight < 240) issues.push(`線型圖可視高度只有 ${item.chartHeight}px`);
    if (analysis && item.panelHeight < 240) issues.push(`分析面板可視高度只有 ${item.panelHeight}px`);
    if (!item.label.includes(`${item.pageIndex + 1} / 7`)) issues.push(`底部分頁標籤不符：${item.label || '空白'}`);
    if (item.smallTargets) issues.push(`${item.smallTargets} 個分頁點按區小於 24px`);
    if (analysis && (item.workspaceKey !== analysisKeys[item.pageIndex - 1] || item.tab !== item.workspaceKey)) issues.push('分析內容與索引不一致');
    if (analysis && (!item.bottomReachable || !item.panelAbovePager)) issues.push('分析頁底部無法到達或被分頁列覆蓋');
    if (analysis && item.initialScroll > 2) issues.push('分析切頁未重設捲動位置');
    if (analysis && item.panelOverflow > 2) issues.push(`分析內容水平溢位 ${item.panelOverflow}px`);
    if (analysis && item.contentLength < 20) issues.push('分析內容未形成');
    if (analysis && !item.analysisInteractive) issues.push('桌機收合狀態使分析頁不可操作');
    if (item.collapseHandleVisible) issues.push('桌機收合把手覆蓋手機內容');
  } else {
    if (!item.leftVisible || !item.rightVisible) issues.push('橫式未同時顯示線型圖與分析面板');
    if (item.pagerVisible) issues.push('橫式不應顯示直立底部分頁索引');
    /* 橫式沿用既有 compact workstation 契約（圖表最小約 102px），不套直立 240px 門檻。 */
    if (item.chartHeight < 100 || item.panelHeight < 150) issues.push('橫式工作區有效高度不足');
  }
  return issues;
}

let chrome;
let socket;
let send;
let tempDir;
try {
  await fs.mkdir(evidenceDir, {recursive:true});
  const chromePath = await resolveChromePath();
  const tempRoot = await fs.realpath(os.tmpdir());
  tempDir = await fs.mkdtemp(path.join(tempRoot, 'st-mobile-gate-'));
  const resolvedTemp = path.resolve(tempDir);
  if (path.dirname(resolvedTemp).toLowerCase() !== tempRoot.toLowerCase()) {
    throw new Error(`拒絕使用非預期的暫存目錄：${resolvedTemp}`);
  }
  chrome = spawn(chromePath, [
    ...(process.env.ST_CHROME_NO_SANDBOX === '1' ? ['--no-sandbox'] : []),
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${resolvedTemp}`, '--window-size=430,932',
    '--force-device-scale-factor=1', 'about:blank'
  ], { stdio: 'ignore', windowsHide: true });
  const portFile = path.join(resolvedTemp, 'DevToolsActivePort');
  const [port] = (await waitForFile(portFile)).trim().split(/\r?\n/);
  const created = await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(testUrl)}`, { method: 'PUT' });
  if (!created.ok) throw new Error(`Chrome 建立測試頁失敗：HTTP ${created.status}`);
  const target = await created.json();
  ({ ws: socket, send } = await connect(target.webSocketDebuggerUrl));
  await send('Page.enable');
  await send('Runtime.enable');
  await waitForApp(send);
  await sleep(300);
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'Escape', code:'Escape', windowsVirtualKeyCode:27});
  await send('Input.dispatchKeyEvent', {type:'keyUp', key:'Escape', code:'Escape', windowsVirtualKeyCode:27});

  /* 先喚醒所有延遲載入模組與本機資料快取，避免首輪只量到空殼。 */
  console.log('預熱十六個功能路由…');
  for (const route of linksOnly || heatOnly ? [] : routes) {
    await evaluate(send, `window.ShellV5.go(${JSON.stringify(route)}); true`);
    await sleep(160);
  }
  await sleep(1800);

  const failures = [];
  const report = [];
  const browserVersion = await send('Browser.getVersion');
  await checkHeatViewport({send, evaluate, sleep, screenshot, report, failures});
  if (!heatOnly) {
  for (const viewport of linksOnly ? [] : viewports) {
    await send('Emulation.setDeviceMetricsOverride', {
      width: viewport.width,
      height: viewport.height,
      screenWidth: viewport.width,
      screenHeight: viewport.height,
      deviceScaleFactor: 3,
      mobile: true
    });
    await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
    await evaluate(send, `window.dispatchEvent(new Event('resize')); true`);
    await sleep(250);
    for (const route of routes) {
      await evaluate(send, `document.getElementById('shell-views').scrollTop = document.getElementById('shell-views').scrollHeight;
        window.ShellV5.go(${JSON.stringify(route)}); true`);
      const contentReady = await waitForRouteContent(send, route);
      if (!contentReady) throw new Error(`功能頁 ${route} 在期限內沒有形成可量測內容。`);
      await sleep(route === 'breadth' || route === 'heat' ? 500 : 220);
      const item = await evaluate(send, measureExpression(route));
      const issues = findingsFor(item);
      report.push({ viewport: viewport.label, ...item, issues });
      if (issues.length) failures.push(`${viewport.label} ${route}: ${issues.join('；')}`);
      console.log(`${issues.length ? 'FAIL' : 'OK  '} ${viewport.label} ${route}` +
        (issues.length ? ` — ${issues.join('；')} | ${JSON.stringify({
          maxScroll: item.maxScroll, actualScroll: item.actualScroll,
          panel: [item.panelLeft, item.panelRight, item.panelWidth],
          offscreenControls: item.offscreenControlDetails, wideElements: item.wideElements
        })}` : ''));
    }

    await evaluate(send, `window.ShellV5.go('chart'); window.goMobileWorkspacePage(0, 'browser-gate'); true`);
    await sleep(450);
    const chartPage = await evaluate(send, chartMeasureExpression('chart'));
    const chartIssues = chartFindings(chartPage, true);
    report.push({ viewport: viewport.label, route: 'chart-workspace', ...chartPage, issues: chartIssues });
    if (chartIssues.length) failures.push(`${viewport.label} chart-workspace: ${chartIssues.join('；')}`);
    console.log(`${chartIssues.length ? 'FAIL' : 'OK  '} ${viewport.label} chart-workspace` +
      (chartIssues.length ? ` — ${chartIssues.join('；')} | ${JSON.stringify(chartPage)}` : ''));

    await evaluate(send, `document.body.classList.add('right-collapsed'); true`);
    for (let pageIndex = 1; pageIndex <= 6; pageIndex += 1) {
    await tap(send, '#rpage-next');
    await sleep(450);
    const analysisPage = await evaluate(send, chartMeasureExpression('analysis', pageIndex));
    const analysisIssues = chartFindings(analysisPage, true);
    report.push({ viewport: viewport.label, route: 'chart-analysis', ...analysisPage, issues: analysisIssues });
    if (analysisIssues.length) failures.push(`${viewport.label} chart-analysis: ${analysisIssues.join('；')}`);
    console.log(`${analysisIssues.length ? 'FAIL' : 'OK  '} ${viewport.label} chart-analysis-${pageIndex}` +
      (analysisIssues.length ? ` — ${analysisIssues.join('；')} | ${JSON.stringify(analysisPage)}` : ''));
    await evaluate(send, `document.getElementById('rpanel').scrollTop=0; true`);
    await screenshot(send, `${viewport.label}-分析${pageIndex}`);
    /* 截圖後恢復非零捲動，確保下一次實際點按會測到切頁重設。 */
    const beforeNextScroll = await evaluate(send, `(() => {
      const panel=document.getElementById('rpanel'); panel.scrollTop=panel.scrollHeight;
      return panel.scrollTop;
    })()`);
    report[report.length - 1].beforeNextScroll = beforeNextScroll;
    }
    await tap(send, '#rpage-prev');
    if (await evaluate(send, `document.getElementById('body').getAttribute('data-mobile-workspace-key')`) !== 'plan') failures.push(`${viewport.label} 上一頁點按失敗`);
    await tap(send, '#rpage-dots button:first-child');
    if (await evaluate(send, `document.getElementById('body').getAttribute('data-mobile-workspace-key')`) !== 'chart') failures.push(`${viewport.label} 圓點點按失敗`);
    await screenshot(send, `${viewport.label}-圖表`);
    await evaluate(send, `document.body.classList.remove('right-collapsed'); true`);
  }

  await send('Emulation.setDeviceMetricsOverride', {
    width: 844, height: 390, screenWidth: 844, screenHeight: 390,
    deviceScaleFactor: 3, mobile: true
  });
  await evaluate(send, `window.ShellV5.go('chart'); window.dispatchEvent(new Event('resize'));
    window.syncMobileWorkspacePage('browser-gate-landscape'); true`);
  await sleep(500);
  const landscape = await evaluate(send, chartMeasureExpression('landscape'));
  const landscapeIssues = chartFindings(landscape, false);
  report.push({ viewport: '844x390', route: 'chart-landscape', ...landscape, issues: landscapeIssues });
  if (landscapeIssues.length) failures.push(`844x390 chart-landscape: ${landscapeIssues.join('；')}`);
  console.log(`${landscapeIssues.length ? 'FAIL' : 'OK  '} 844x390 chart-landscape` +
    (landscapeIssues.length ? ` — ${landscapeIssues.join('；')} | ${JSON.stringify(landscape)}` : ''));
  await send('Emulation.setDeviceMetricsOverride', {
    width:390,height:844,screenWidth:390,screenHeight:844,deviceScaleFactor:3,mobile:true
  });
  /* Chrome 的安全區模擬：驗證非零 inset，而非只檢查 CSS 字串。 */
  await send('Emulation.setSafeAreaInsetsOverride', {insets:{bottom:34}});
  await evaluate(send, `window.goMobileWorkspacePage(0, 'safe-area'); true`);
  await sleep(350);
  const safeArea = await evaluate(send, `(() => {
    const pager=document.getElementById('rpanel-pager'), r=pager.getBoundingClientRect();
    const next=document.getElementById('rpage-next').getBoundingClientRect();
    return {padding:parseFloat(getComputedStyle(pager).paddingBottom),bottom:r.bottom,controlBottom:next.bottom,height:innerHeight};
  })()`);
  const safeIssues = safeArea.padding !== 34 || safeArea.bottom > 845 || safeArea.controlBottom > 810 ? ['底部安全區未保留 34px'] : [];
  report.push({route:'safe-area',...safeArea,issues:safeIssues});
  failures.push(...safeIssues);
  await screenshot(send,'390x844-底部安全區');
  await send('Emulation.setSafeAreaInsetsOverride', {insets:{bottom:0}});
  /* 重新導覽驗證冷啟動；同頁 hashchange 驗證別名附帶的功能效果。 */
  for (const route of ['workspace','wavedeck','invalid-route','chart','breadth','news','index','trends']) {
    const url = new URL(testUrl); url.hash=route;
    /* 先離開文件，避免只改 hash 變成同文件導覽；也不依賴伺服器的查詢參數路由。 */
    await send('Page.navigate',{url:'about:blank'});
    await send('Page.navigate',{url:url.href});
    await waitForApp(send); await sleep(600);
    const actual=await evaluate(send, `({route:document.documentElement.getAttribute('data-st5-route'),hash:location.hash,symbol:typeof S !== 'undefined' ? S.sym : null})`);
    const expected = ['index','trends'].includes(route) ? 'chart' :
      ['workspace','wavedeck','invalid-route'].includes(route) ? 'pulse' : route;
    const issues = actual.route !== expected ? ['冷啟動路由不符'] : [];
    if (expected==='chart' && route!=='chart' && actual.symbol!=='^TWII') issues.push('冷啟動別名未切換加權指數');
    report.push({caseId:'deep-link-'+route,...actual,issues});
    console.log(`${issues.length ? 'FAIL' : 'OK  '} 冷啟動 ${route}: ${JSON.stringify(actual)}`);
    failures.push(...issues.map(issue=>route+': '+issue));
  }
  await evaluate(send, `(async () => { await loadSym('2330','TW'); location.hash='index'; return true; })()`);
  await sleep(800);
  const aliasSymbol=await evaluate(send, `S.sym`);
  const aliasIssues=aliasSymbol==='^TWII'?[]:['同圖表路由別名未執行股票切換'];
  report.push({route:'same-chart-alias',symbol:aliasSymbol,issues:aliasIssues});
  failures.push(...aliasIssues);
  console.log(`\n已驗證 ${report.length} 個「視窗 × 路由」組合。`);
  }
  await fs.writeFile(path.join(evidenceDir, '瀏覽器量測.json'), JSON.stringify({time:new Date().toISOString(),browserVersion,testUrl,report,failures},null,2));
  if (failures.length) {
    console.error(`手機直立瀏覽器閘門失敗（${failures.length}）：`);
    failures.forEach((failure) => console.error(`- ${failure}`));
    process.exitCode = 1;
  } else {
    console.log('mobile_portrait_browser_gate PASSED');
  }
} finally {
  try { if (send) await send('Browser.close'); } catch {}
  try { socket?.close(); } catch {}
  await sleep(350);
  if (chrome && chrome.exitCode == null) chrome.kill();
  if (tempDir) {
    const tempRoot = await fs.realpath(os.tmpdir());
    const resolvedTemp = path.resolve(tempDir);
    if (path.dirname(resolvedTemp).toLowerCase() === tempRoot.toLowerCase()) {
      for (let attempt = 0; attempt < 8; attempt += 1) {
        try {
          await fs.rm(resolvedTemp, { recursive: true, force: true });
          break;
        } catch (error) {
          if (error.code !== 'EBUSY' || attempt === 7) {
            console.warn(`暫存 Chrome 目錄稍後由系統清理：${resolvedTemp}`);
            break;
          }
          await sleep(180);
        }
      }
    }
  }
}
