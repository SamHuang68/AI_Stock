const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8');
const start = source.indexOf('const RPANEL_PAGES =');
const end = source.indexOf('function renderRpanel()', start);
if (start < 0 || end < 0) throw new Error('找不到手機工作區分頁程式');

function element() {
  const attrs = {};
  return {
    dataset: {}, innerHTML: '', textContent: '', disabled: false, scrollTop: 0, scrollLeft: 0,
    classList: { toggle() {} },
    setAttribute(k, v) {
      attrs[k] = String(v);
      if (this.afterAttribute) this.afterAttribute(k, v);
    },
    removeAttribute(k) { delete attrs[k]; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    addEventListener() {}
  };
}

const ids = {
  body: element(), left: element(), right: element(), rpanel: element(), 'shell-main': element(),
  'rpage-label': element(), 'rpage-dots': element(),
  'rpage-prev': element(), 'rpage-next': element()
};
let dispatchCount = 0;
let renderCount = 0;
let nextFrameId = 0;
const frames = new Map();
const pageBody = element();
const rootElement = element();
const scrollSurfaces = [ids['shell-main'], ids.rpanel, pageBody, rootElement];
const sandbox = {
  S: { tab: 'stats' },
  document: {
    body: pageBody, documentElement: rootElement,
    getElementById(id) { return ids[id] || null; },
    querySelectorAll() { return []; }
  },
  window: {
    innerWidth: 375, innerHeight: 667,
    matchMedia(query) {
      const width = this.innerWidth;
      const height = this.innerHeight;
      const orientation = width > height ? 'landscape' : 'portrait';
      const matches = query.split(',').some(part => {
        for (const match of part.matchAll(/\((max|min)-(width|height):\s*(\d+)px\)/g)) {
          const size = match[2] === 'width' ? width : height;
          if (match[1] === 'max' ? size > Number(match[3]) : size < Number(match[3])) return false;
        }
        const wantedOrientation = part.match(/orientation:\s*(portrait|landscape)/);
        return !wantedOrientation || wantedOrientation[1] === orientation;
      });
      return { matches };
    },
    dispatchEvent() { dispatchCount += 1; },
    requestAnimationFrame(callback) {
      const id = ++nextFrameId;
      frames.set(id, callback);
      return id;
    }
  },
  fetch() { return Promise.resolve({ ok: true }); },
  Event: function Event(name) { this.type = name; },
  setTimeout(fn) { fn(); return 1; },
  clearTimeout() {},
  renderRpanel() { renderCount += 1; },
  console
};

vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);

function flushFrames() {
  const callbacks = [...frames.values()];
  frames.clear();
  callbacks.forEach(callback => callback());
}

function setScroll(top, left) {
  scrollSurfaces.forEach(surface => { surface.scrollTop = top; surface.scrollLeft = left; });
}

function allScrollEquals(top, left) {
  return scrollSurfaces.every(surface => surface.scrollTop === top && surface.scrollLeft === left);
}

function viewport(width, height) {
  sandbox.window.innerWidth = width;
  sandbox.window.innerHeight = height;
  sandbox.syncMobileWorkspacePage();
  flushFrames();
}

function pageKey() {
  return ids.body.getAttribute('data-mobile-workspace-key');
}

function ok(value, message) {
  if (!value) throw new Error('未通過：' + message);
  console.log('通過：', message);
}

sandbox.syncMobileWorkspacePage();
sandbox.syncMobileWorkspacePage();
ok(dispatchCount === 1, '圖表顯示只送出一次尺寸更新，避免自身觸發迴圈');
sandbox.shiftRtab(1);
flushFrames();
ok(ids.body.getAttribute('data-mobile-workspace-page') === 'analysis', '直式下一頁切換整個工作區到分析');
ok(pageKey() === 'stats', '第一個分析頁為技術統計');
ok(ids['rpage-label'].textContent === '技術統計 · 2 / 7', '底部頁碼包含第一頁線型圖');
ok((ids['rpage-dots'].innerHTML.match(/rpage-dot/g) || []).length === 7, '底部提供七個工作區頁面');

viewport(852, 330);
ok(pageKey() === 'stats', '旋轉為短橫式後保留目前分析頁');
setScroll(165, 13);
sandbox.syncMobileWorkspacePage();
ok(allScrollEquals(165, 13) && frames.size === 0, '相同短橫式同步保留閱讀位置且不排入捲動重設');
const pageKeys = ['chart', 'stats', 'research', 'position', 'watch', 'plan', 'etf'];
ids.body.afterAttribute = function (key) {
  if (key === 'data-mobile-workspace-key') setScroll(26.333, 8);
};
pageKeys.forEach((key, index) => {
  ids.rpanel.scrollTop = 123;
  ids['shell-main'].scrollTop = 456;
  sandbox.goRpanelPage(index);
  ok(pageKey() === key && ids['rpage-label'].textContent.endsWith((index + 1) + ' / 7'),
    '短橫式可切換第' + (index + 1) + '頁且頁碼一致');
  ok(allScrollEquals(0, 0), '第' + (index + 1) + '頁完成重排後清除內外容器位移');
  setScroll(26.333, 8);
  const previousResizeCount = dispatchCount;
  flushFrames();
  ok(allScrollEquals(0, 0) && frames.size === 0 && dispatchCount === previousResizeCount,
    '第' + (index + 1) + '頁下一幀清除焦點位移且不觸發更新迴圈');
  ok(ids['rpage-prev'].disabled === (index === 0) && ids['rpage-next'].disabled === (index === 6),
    '第' + (index + 1) + '頁的前後按鈕邊界正確');
});
ids.body.afterAttribute = null;
ok(renderCount === 5, '切換不同分析頁時實際更新分析內容');
sandbox.shiftRtab(1);
flushFrames();
ok(pageKey() === 'etf', '末頁向後操作不超出頁面範圍');
setScroll(165, 13);
viewport(393, 682);
ok(pageKey() === 'etf', '回到直式後保留目前工作頁');
ok(allScrollEquals(0, 0), '離開短橫式回直式時清除主畫面及外層頁面位移');
setScroll(78, 9);
sandbox.syncMobileWorkspacePage();
ok(allScrollEquals(78, 9) && frames.size === 0, '相同直式同步保留閱讀位置');
viewport(852, 330);
ok(allScrollEquals(0, 0), '進入短橫式時清除前一模式位移');
setScroll(165, 13);
viewport(852, 600);
ok(pageKey() == null && ids.body.getAttribute('data-mobile-workspace-page') == null,
  '較高橫式還原原本分割工作區');
ok(allScrollEquals(0, 0), '短橫式轉為較高橫式時清除內外容器位移');
viewport(852, 330);
setScroll(26.333, 8);
viewport(1440, 900);
ok(pageKey() == null && ids.body.getAttribute('data-mobile-workspace-page') == null,
  '桌面工作區移除手機分頁狀態');
ok(allScrollEquals(0, 0), '短橫式轉桌面時清除26像素外層位移');
console.log('\n手機工作區分頁自測全部通過');
