/* AI 面板共用請求：等待提示、取消、完成訊號與純文字邊界。 */
(function () {
  'use strict';
  function context() {
    var s = typeof S === 'undefined' ? {} : S;
    var bars = (s.data || {}).candles || [], last = bars[bars.length - 1];
    var parts = ['資料來源：Stock Terminal 畫面快照；未提供的行情與新聞不可推測。'];
    var owner = String(((s.data || {}).meta || {}).symbol || '').toUpperCase();
    var selected = String(s.sym || '').toUpperCase();
    var sameSymbol = owner && owner.replace(/\.TW(O)?$/, '') === selected.replace(/\.TW(O)?$/, '');
    var sameMarket = window.Market && window.Market.of(owner) === s.mkt;
    var stamp = last && (last.time || last.date);
    if (typeof stamp === 'number') stamp = new Date(stamp * 1000).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
    if (last && sameSymbol && sameMarket) parts.push('個股：' + selected + ' ' + ((s.data || {}).name || '') +
      '；K 棒日期：' + (stamp || '未提供') + '；K 棒收盤：' + last.close);
    else parts.push('個股 ' + selected + '：行情載入中或資料歸屬尚未確認，本次不引用價格。');
    var positions = s.positions || {};
    parts.push('持倉快照（價格時間未提供時不可稱為即時行情）：' + Object.keys(positions).slice(0, 80).map(function (code) {
      var p = positions[code] || {};
      return String(code).slice(0, 20) + '：股數 ' + p.shares + '，成本 ' + p.entry + '，快照價格 ' + p.lastPrice;
    }).join('；'));
    parts.push('觀察清單（僅代號，未提供訊號或行情）：' + Object.keys(s.watches || {}).slice(0, 120).map(function (code) { return String(code).slice(0, 20); }).join('、'));
    return parts.join('\n');
  }
  function request(options) {
    var controller = new AbortController(), reader, timer, ticker;
    var started = Date.now(), cancelled = false, timedOut = false;
    var meta = {}, text = '', finished = false;
    var traceId = 'ai-' + started.toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    var timeoutMs = options.timeoutMs || 660000;
    function status() {
      if (options.onStatus) options.onStatus({ elapsedSeconds: Math.floor((Date.now() - started) / 1000),
        meta: meta, hasText: !!text, requestId: meta.requestId || traceId });
    }
    function cancel() { cancelled = true; controller.abort(); }
    var promise = (async function () {
      timer = setTimeout(function () { timedOut = true; controller.abort(); }, timeoutMs);
      ticker = setInterval(status, 1000);
      status();
      try {
        var response = await fetch((window.SERVER || '') + (options.endpoint || '/ai/local'), {
          method: 'POST', signal: controller.signal,
          headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'X-ST-Trace-ID': traceId },
          body: JSON.stringify(options.body || { prompt: options.prompt, context: options.context || '' })
        });
        if (cancelled || timedOut) throw new Error('請求已停止');
        meta = { requestId: response.headers.get('X-ST-AI-Request-ID') || traceId,
          host: response.headers.get('X-ST-AI-Host') || '', provider: response.headers.get('X-ST-AI-Provider') || '',
          model: response.headers.get('X-ST-AI-Model') || '', dataBoundary: response.headers.get('X-ST-AI-Data-Boundary') || '' };
        status();
        if (!response.ok) {
          var detail = await response.text();
          try { detail = JSON.parse(detail).error || detail; } catch (_) {}
          throw new Error(String(detail || ('HTTP ' + response.status)).slice(0, 260));
        }
        var type = response.headers.get('Content-Type') || '';
        var cloud = options.endpoint === '/ai-report';
        if (!cloud && type.indexOf('text/event-stream') < 0) throw new Error('AI 回應格式不符，無法確認完成；請重新整理後重試。');
        if (cloud && type.indexOf('application/json') < 0) throw new Error('雲端報告回應格式不符；請重試。');
        function update(chunk) {
          if (cancelled || timedOut) throw new Error('請求已停止');
          text += chunk;
          if (options.onText) options.onText(text);
        }
        if (type.indexOf('application/json') >= 0) {
          var json = await response.json();
          if (!json.ok || !json.report) throw new Error(json.error || '報告未回傳內容');
          meta.provider = 'Anthropic'; meta.model = json.model || ''; meta.dataBoundary = 'external';
          update(json.report); finished = true;
        } else {
          var structured = type.indexOf('text/event-stream') >= 0, buffer = '';
          function consume(chunk) {
            if (!structured) { update(chunk); return; }
            buffer += chunk;
            buffer = buffer.replace(/\r\n/g, '\n');
            var split;
            while ((split = buffer.indexOf('\n\n')) >= 0) {
              var frame = buffer.slice(0, split); buffer = buffer.slice(split + 2);
              var line = frame.split('\n').filter(function (l) { return l.indexOf('data:') === 0; }).map(function (l) { return l.slice(5).trim(); }).join('\n');
              if (!line) continue;
              var event = JSON.parse(line);
              if (event.type === 'error') throw new Error(event.message || 'AI 執行失敗');
              if (event.type === 'delta') update(event.text || '');
              if (event.type === 'done') finished = true;
            }
          }
          if (response.body && response.body.getReader) {
            reader = response.body.getReader();
            var decoder = new TextDecoder();
            while (true) {
              var part = await reader.read();
              if (part.done) break;
              consume(decoder.decode(part.value, { stream: true }));
            }
            consume(decoder.decode());
          } else consume(await response.text());
          if (structured && !finished) throw new Error('AI 連線中斷，未收到完成確認；請重試。');
        }
        if (cancelled || timedOut) throw new Error('請求已停止');
        if (!text.trim()) throw new Error('AI 未回傳可見內容；請重試。');
        return { text: text, meta: meta, elapsedSeconds: Math.round((Date.now() - started) / 1000) };
      } catch (err) {
        if (timedOut) throw new Error('AI 等待超過上限，已停止接收；模型仍可能正在收尾，請稍後重試。');
        if (cancelled) { var aborted = new Error('已取消接收；模型仍可能正在收尾。'); aborted.name = 'AbortError'; throw aborted; }
        throw err;
      } finally {
        clearTimeout(timer); clearInterval(ticker);
        if (reader) { try { await reader.cancel(); } catch (_) {} }
      }
    })();
    return { promise: promise, cancel: cancel };
  }
  window.STAI = { request: request, context: context };
})();
