'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../stock_terminal.html'), 'utf8');
const body = source.slice(source.indexOf('function bindChartSizeLifecycle('), source.indexOf('\nfunction formatVol('));

for (const symbol of ['2330', '__MARGIN_RATIO__']) {
  const observers = [], frames = new Map(), charts = [];
  let sequence = 0;
  const wrap = { clientWidth: 390, clientHeight: 600, isConnected: true };
  const scope = { console, Map, Date, Intl, S: { sym: symbol, mkt: 'TW', range: 'max' },
    document: { getElementById: id => id === 'chart-wrap' ? wrap : null },
    calcPriceScaleMargins: () => ({ top: .1, bottom: .1 }), makeHighHeadroomAutoscale: () => () => null,
    currentRangeDef: () => ({ range: 'max' }), fetchYF: async () => null, parseYF: () => null,
    requestAnimationFrame: callback => { const id = ++sequence; frames.set(id, callback); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; this.active = false; observers.push(this); }
      observe() { this.active = true; }
      disconnect() { this.active = false; }
    },
    LightweightCharts: { CrosshairMode: { Magnet: 1 }, createChart() {
      const chart = { disposed: false, calls: 0, removals: 0 };
      const guard = () => { if (chart.disposed) throw new Error('Object is disposed'); chart.calls++; };
      chart.remove = function () { assert.equal(this, chart); guard(); chart.disposed = true; chart.removals++; };
      chart.timeScale = () => { guard(); return { fitContent: guard }; };
      chart.applyOptions = guard;
      chart.priceScale = () => ({ applyOptions: guard });
      chart.subscribeCrosshairMove = guard;
      for (const name of ['addCandlestickSeries', 'addLineSeries', 'addHistogramSeries', 'addAreaSeries']) chart[name] = () => ({ setData: guard });
      charts.push(chart); return chart;
    } }
  };
  scope.window = scope;
  vm.createContext(scope); vm.runInContext(body, scope);
  const candles = [{ time: 1700000000, open: 100, high: 102, low: 99, close: 101, volume: 0 }];
  scope.renderChart(candles);
  const old = charts[0], queuedFrame = [...frames.values()][0], queuedResize = observers[0].callback;
  scope.renderChart(candles);
  assert.equal(old.removals, 1, '替換時只釋放一次');
  assert.equal(observers[0].active, false, '釋放時停止舊尺寸觀察器');
  assert.equal(frames.size, 1, '釋放時取消舊動畫回呼');
  const oldCalls = old.calls;
  queuedFrame(); queuedResize();
  assert.equal(old.calls, oldCalls, '已進入佇列的舊回呼不再操作已釋放圖表');
  const current = scope.S.chart, currentCalls = current.calls;
  observers[1].callback(); [...frames.values()][0]();
  assert.ok(current.calls > currentCalls, '新圖表仍可調整尺寸與視野');
  wrap.isConnected = false;
  const detachedCalls = current.calls;
  observers[1].callback();
  assert.equal(current.calls, detachedCalls, '已離開文件的容器不執行尺寸操作');
  wrap.isConnected = true;
  for (let i = 0; i < 25; i++) scope.renderChart(candles);
  assert.equal(observers.filter(value => value.active).length, 1, '連續切換不累積尺寸觀察器');
  assert.equal(frames.size, 1, '連續切換不累積待執行動畫');
  const latest = scope.S.chart;
  latest.remove(); latest.remove();
  assert.equal(latest.removals, 1, '其他圖表路徑也可安全釋放');
  assert.equal(observers.filter(value => value.active).length, 0);
  assert.equal(frames.size, 0);
  observers.forEach(value => value.callback());
  console.log('通過：' + symbol + ' 的切換、尺寸、動畫與釋放生命週期。');
}
