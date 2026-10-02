/* AI 副駕：明確完成、總期限、取消與有日期的唯讀快照。 */
(function () {
  'use strict';
  function context() {
    var s = typeof S === 'undefined' ? {} : S;
    var data = s.data || {}, bars = data.candles || [], last = bars[bars.length - 1];
    var owner = String((data.meta || {}).symbol || '').toUpperCase();
    var selected = String(s.sym || '').toUpperCase();
    var sameSymbol = owner && owner.replace(/\.TW(O)?$/, '') === selected.replace(/\.TW(O)?$/, '');
    var sameMarket = window.Market && window.Market.of(owner) === s.mkt;
    var parts = ['資料來源：Stock Terminal 畫面快照；未提供的行情、日期與新聞不可推測。'];
    var stamp = last && (last.time || last.date);
    if (typeof stamp === 'number' && Number.isFinite(stamp)) {
      stamp = new Date(stamp * 1000).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
    }
    if (last && sameSymbol && sameMarket && typeof last.close === 'number' && Number.isFinite(last.close)) {
      parts.push('個股：' + selected + ' ' + (data.name || '') + '；K 棒日期：' + (stamp || '未提供') + '；K 棒收盤：' + last.close);
    } else parts.push('個股 ' + selected + '：行情載入中或資料歸屬尚未確認，本次不引用價格。');
    var positions = s.positions || {};
    function value(v) { return v == null || v === '' ? '未提供' : String(v); }
    parts.push('持倉快照（價格時間未提供，不可稱為即時行情）：' + Object.keys(positions).slice(0, 80).map(function (code) {
      var p = positions[code] || {};
      return String(code).slice(0, 20) + '：股數 ' + value(p.shares) + '，成本 ' + value(p.entry) + '，快照價格 ' + value(p.lastPrice);
    }).join('；'));
    parts.push('觀察清單（僅代號，未提供訊號或行情）：' + Object.keys(s.watches || {}).slice(0, 120).map(function (code) { return String(code).slice(0, 20); }).join('、'));
    return parts.join('\n');
  }

  function request(options) {
    var controller = new AbortController(), reader, timer, ticker, rejectStop;
    var started = Date.now(), cancelled = false, timedOut = false, settled = false;
    var meta = {}, text = '', finished = false;
    var suppliedId = String(options.requestId || '');
    var traceId = /^[A-Za-z0-9_.-]{1,128}$/.test(suppliedId) ? suppliedId :
      'ai-' + started.toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    var endpoint = options.endpoint || '/ai/local';
    var routeFields = ['mode', 'host', 'provider', 'model', 'dataBoundary', 'destinationId'];
    // 建立副本；呼叫端在等待期間修改物件不能改變此次核對條件。
    var expectedRoute = options.expectedRoute === undefined ? undefined :
      (options.expectedRoute && typeof options.expectedRoute === 'object' ? Object.assign({}, options.expectedRoute) : null);
    var requestedTimeout = Number(options.timeoutMs);
    var timeoutMs = Number.isFinite(requestedTimeout) && requestedTimeout > 0 ?
      Math.min(requestedTimeout, 1800000) : (endpoint === '/ai/deep' ? 960000 : 660000);
    var stopped = new Promise(function (_, reject) { rejectStop = reject; });
    function stop(timeout) {
      if (settled || cancelled || timedOut) return;
      timedOut = !!timeout; cancelled = !timeout;
      controller.abort();
      var error = new Error(timeout ? 'AI 等待超過上限，已停止接收；模型可能仍在收尾，請稍後重試。' : '已取消接收；模型可能仍在收尾。');
      if (!timeout) error.name = 'AbortError';
      rejectStop(error);
    }
    function check() { if (cancelled || timedOut) throw new Error('請求已停止'); }
    function status() {
      if (!cancelled && !timedOut && !settled && options.onStatus) options.onStatus({ elapsedSeconds: Math.floor((Date.now() - started) / 1000),
        meta: meta, hasText: !!text, requestId: meta.requestId || traceId });
    }
    timer = setTimeout(function () { stop(true); }, timeoutMs);
    ticker = setInterval(status, 1000);
    function externalAbort() { stop(false); }
    if (options.signal) {
      options.signal.addEventListener('abort', externalAbort, { once: true });
      if (options.signal.aborted) externalAbort();
    }
    var run = (async function () {
      check();
      if (endpoint !== '/ai/local' && endpoint !== '/ai/deep') throw new Error('AI 請求端點不受支援');
      var body = { prompt: options.prompt, context: options.context || '' };
      if (expectedRoute !== undefined) {
        if (!expectedRoute || Object.keys(expectedRoute).length !== routeFields.length ||
            routeFields.some(function (key) { return typeof expectedRoute[key] !== 'string' || !expectedRoute[key]; }) ||
            expectedRoute.mode !== (endpoint === '/ai/deep' ? 'deep' : 'fast')) {
          throw new Error('研究 AI 路由契約不完整，尚未傳送研究內容');
        }
        body.expectedRoute = expectedRoute;
      }
      status();
      var response = await fetch((window.SERVER || '') + endpoint, {
        method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'X-ST-Trace-ID': traceId },
        body: JSON.stringify(body)
      });
      check();
      var serverRequestId = response.headers.get('X-ST-AI-Request-ID') || '';
      meta = { requestId: serverRequestId || traceId, serverRequestId: serverRequestId,
        mode: response.headers.get('X-ST-AI-Mode') || '',
        host: response.headers.get('X-ST-AI-Host') || '', provider: response.headers.get('X-ST-AI-Provider') || '',
        model: response.headers.get('X-ST-AI-Model') || '', dataBoundary: response.headers.get('X-ST-AI-Data-Boundary') || '',
        destinationId: response.headers.get('X-ST-AI-Destination-ID') || '' };
      status();
      if (!response.ok) {
        var detail = await response.text();
        check();
        try { detail = JSON.parse(detail).error || detail; } catch (_) {}
        var failure = new Error(String(detail || ('HTTP ' + response.status)).slice(0, 260));
        failure.status = response.status;
        throw failure;
      }
      if (expectedRoute && (!serverRequestId || routeFields.some(function (key) { return meta[key] !== expectedRoute[key]; }))) {
        throw new Error('研究 AI 實際路由或伺服器收據不符，本次結果不可採用');
      }
      if ((response.headers.get('Content-Type') || '').indexOf('text/event-stream') < 0) {
        throw new Error('AI 回應格式不符，無法確認完成；請重新整理後重試。');
      }
      var buffer = '';
      function consume(chunk) {
        check();
        buffer += chunk;
        // CRLF 可能跨網路區塊，保留未配對的 CR 到下次讀取。
        buffer = buffer.replace(/\r\n/g, '\n');
        var split;
        while ((split = buffer.indexOf('\n\n')) >= 0) {
          var frame = buffer.slice(0, split); buffer = buffer.slice(split + 2);
          var line = frame.split('\n').filter(function (l) { return l.indexOf('data:') === 0; }).map(function (l) { return l.slice(5).trim(); }).join('\n');
          if (!line) continue;
          var event = JSON.parse(line);
          if (!event || typeof event !== 'object' || finished) throw new Error('AI 完成訊號格式不符');
          if (event.type === 'error') throw new Error(event.message || 'AI 執行失敗');
          if (event.type === 'delta' && typeof event.text === 'string') {
            text += event.text;
            if (text.length > 1000000) throw new Error('AI 回覆超過接收上限');
            if (options.onText) options.onText(text);
          } else if (event.type === 'done') finished = true;
          else throw new Error('AI 回應事件格式不符');
        }
        if (buffer.length > 262144) throw new Error('AI 回應事件超過接收上限');
      }
      if (response.body && response.body.getReader) {
        reader = response.body.getReader();
        var decoder = new TextDecoder();
        while (!finished) {
          var part = await reader.read();
          check();
          if (part.done) break;
          consume(decoder.decode(part.value, { stream: true }));
        }
        consume(decoder.decode());
      } else consume(await response.text());
      check();
      if (!finished) throw new Error('AI 連線中斷，未收到完成確認；請重試。');
      if (!text.trim()) throw new Error('AI 未回傳可見內容；請重試。');
      return { text: text, meta: meta, elapsedSeconds: Math.round((Date.now() - started) / 1000) };
    })();
    var promise = Promise.race([stopped, run]).catch(function (error) {
      error.requestId = meta.requestId || traceId;
      error.serverRequestId = meta.serverRequestId || '';
      error.detail = error.message;
      throw error;
    }).finally(function () {
      settled = true;
      clearTimeout(timer); clearInterval(ticker);
      controller.abort();
      if (options.signal) options.signal.removeEventListener('abort', externalAbort);
      if (reader) { try { Promise.resolve(reader.cancel()).catch(function () {}); } catch (_) {} }
    });
    return { promise: promise, cancel: function () { stop(false); } };
  }
  window.STAI = { request: request, context: context };
})();
