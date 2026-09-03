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
  function request(path, options) {
    options = options || {};
    var method = String(options.method || 'GET').toUpperCase();
    var key = method === 'GET' ? method + ':' + path : null;
    if (key && inflight[key]) return inflight[key];
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeoutMs = Math.max(250, Number(options.timeoutMs || 15000));
    var headers = Object.assign({ 'X-ST-Trace-ID': traceId() }, options.headers || {});
    var timer = controller ? setTimeout(function () { controller.abort(); }, timeoutMs) : null;
    var fetchOptions = Object.assign({}, options, {
      method: method, headers: headers, cache: options.cache || 'no-store'
    });
    delete fetchOptions.timeoutMs;
    if (controller) fetchOptions.signal = controller.signal;
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
    return promise;
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
