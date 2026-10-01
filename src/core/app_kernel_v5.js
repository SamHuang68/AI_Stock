/* Stock Terminal application boundary: API deadlines, request de-duplication and panel lifecycle. */
(function () {
  'use strict';
  var inflight = Object.create(null);
  var panels = Object.create(null);
  var activePanel = null;

  function base() { return window.SERVER || location.origin || 'http://localhost:18432'; }
  function traceId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID().replace(/-/g, '').slice(0, 20);
    }
    return 'st' + Date.now().toString(36) + Math.random().toString(36).slice(2, 9);
  }
  function copyResponse(response) {
    return typeof response.clone === 'function' ? response.clone() : response;
  }
  function request(path, options) {
    options = options || {};
    var method = String(options.method || 'GET').toUpperCase();
    var key = method === 'GET' ? method + ':' + path : null;
    if (key && inflight[key]) return inflight[key].then(copyResponse);
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeoutMs = Math.max(250, Number(options.timeoutMs || 15000));
    var headers = Object.assign({ 'X-ST-Trace-ID': traceId() }, options.headers || {});
    var callerSignal = options.signal;
    var requestSignal = controller ? controller.signal : callerSignal;
    if (controller && callerSignal) {
      if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
        requestSignal = AbortSignal.any([controller.signal, callerSignal]);
      } else {
        // Keep forwarding through response-body consumption; both signals are
        // request-scoped and collectable after their owners release them.
        var abortFromCaller = function () { controller.abort(); };
        if (callerSignal.aborted) abortFromCaller();
        else callerSignal.addEventListener('abort', abortFromCaller, { once: true });
      }
    }
    var timer = controller ? setTimeout(function () { controller.abort(); }, timeoutMs) : null;
    var fetchOptions = Object.assign({}, options, {
      method: method, headers: headers, cache: options.cache || 'no-store'
    });
    delete fetchOptions.timeoutMs;
    if (requestSignal) fetchOptions.signal = requestSignal;
    var promise = fetch(base() + path, fetchOptions).then(function (response) {
      if (!response.ok) {
        var error = new Error('HTTP ' + response.status + ' for ' + path);
        error.status = response.status;
        error.traceId = response.headers.get('X-ST-Trace-ID') || null;
        throw error;
      }
      return response;
    }).finally(function () {
      if (timer) clearTimeout(timer);
      if (key) delete inflight[key];
    });
    if (key) inflight[key] = promise;
    return promise.then(copyResponse);
  }
  function getJson(path, options) {
    return request(path, options).then(function (response) { return response.json(); });
  }
  function postJson(path, value, options) {
    options = options || {};
    options.method = 'POST';
    options.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    options.body = JSON.stringify(value == null ? {} : value);
    return request(path, options).then(function (response) { return response.json(); });
  }
  function registerPanel(id, lifecycle) {
    if (!id || !lifecycle) return;
    panels[id] = lifecycle;
  }
  function activatePanel(id, context) {
    if (activePanel && activePanel !== id && panels[activePanel] && panels[activePanel].deactivate) {
      panels[activePanel].deactivate();
    }
    activePanel = id;
    if (panels[id] && panels[id].activate) return panels[id].activate(context || {});
  }
  function disposePanel(id) {
    if (panels[id] && panels[id].dispose) panels[id].dispose();
    delete panels[id];
    if (activePanel === id) activePanel = null;
  }

  window.AppKernel = Object.freeze({
    api: Object.freeze({ request: request, getJson: getJson, postJson: postJson }),
    panels: Object.freeze({ register: registerPanel, activate: activatePanel, dispose: disposePanel }),
    status: function () { return { activePanel: activePanel, registeredPanels: Object.keys(panels).sort() }; }
  });
}());
