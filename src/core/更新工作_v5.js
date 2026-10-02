/* 更新中心共用狀態：單一輪詢、唯讀訂閱，離頁停止瀏覽器等待。 */
(function () {
  'use strict';
  var state = { jobs: [], capabilities: { canSubmit: false, canRetry: false }, workers: {}, error: null, loading: false, writing: false };
  var listeners = new Set(), timer = null, inflight = null, controller = null, generation = 0;
  var started = false;
  function base() { return window.SERVER || location.origin; }
  function copy() { return JSON.parse(JSON.stringify(state)); }
  function emit() { listeners.forEach(function (fn) { try { fn(copy()); } catch (e) { /* 個別呈現器不阻止其他訂閱。 */ } }); }
  async function request(path, options, signal) {
    var response = await fetch(base() + path, Object.assign({ cache: 'no-store', signal: signal }, options || {}));
    var value = await response.json();
    if (!response.ok || !value || value.ok === false) throw new Error(value && value.error || '更新工作要求失敗（HTTP ' + response.status + '）');
    return value;
  }
  function refresh() {
    if (inflight) return inflight;
    var seq = ++generation, current = new AbortController(); controller = current;
    var timeout = setTimeout(function () { current.abort(); }, 12000);
    state.loading = true; emit();
    inflight = request('/updates', null, current.signal).then(function (value) {
      if (seq !== generation) return copy();
      if (!Array.isArray(value.jobs) || !value.capabilities) throw new Error('更新工作回應格式不正確');
      state.jobs = value.jobs; state.capabilities = value.capabilities; state.workers = value.workers || {};
      state.note = value.note || ''; state.error = null; state.updatedAt = new Date().toISOString();
      return copy();
    }).catch(function (error) {
      if (seq === generation) state.error = error.name === 'AbortError' ? '讀取更新工作逾時；保留前次清單' : error.message;
      return copy();
    }).finally(function () {
      clearTimeout(timeout);
      if (seq === generation) { state.loading = false; inflight = null; controller = null; emit(); }
    });
    return inflight;
  }
  function stopRead() {
    generation++;
    if (controller) controller.abort();
    controller = null; inflight = null; state.loading = false;
  }
  function polling() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!listeners.size || document.hidden) { stopRead(); return; }
    refresh().finally(function () {
      if (listeners.size && !document.hidden && !timer) timer = setTimeout(polling, 2000);
    });
  }
  function subscribe(fn) {
    listeners.add(fn); fn(copy());
    if (!started) { document.addEventListener('visibilitychange', polling); started = true; }
    if (listeners.size === 1) polling();
    return function () { listeners.delete(fn); if (!listeners.size) { if (timer) clearTimeout(timer); timer = null; stopRead(); } };
  }
  async function write(path, payload) {
    if (!state.capabilities.canSubmit) throw new Error('目前僅能讀取更新工作');
    if (state.writing) throw new Error('上一個提交要求仍在處理');
    state.writing = true; state.error = null; emit();
    var current = new AbortController(), timeout = setTimeout(function () { current.abort(); }, 12000);
    try {
      var result = await request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, current.signal);
      if (!result.job || !result.job.jobId) throw new Error('伺服器未提供工作識別；請重新讀取狀態');
      await refresh();
      return result;
    } catch (error) {
      state.error = error.name === 'AbortError' ? '提交等待逾時；伺服器可能已接受，請先讀取清單再決定重試' : error.message;
      throw new Error(state.error);
    } finally { clearTimeout(timeout); state.writing = false; emit(); }
  }
  function waitForJob(jobId, options) {
    options = options || {};
    if (typeof jobId !== 'string' || !jobId) return Promise.reject(new Error('缺少要等待的工作識別'));
    return new Promise(function (resolve, reject) {
      var target = jobId, off = null, finished = false, timer = null, signal = options.signal;
      var timeoutMs = Number(options.timeoutMs == null ? 90000 : options.timeoutMs);
      if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) { reject(new Error('等待期限必須是正數')); return; }
      function settle(error, job) {
        if (finished) return;
        finished = true;
        if (timer) clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', abort);
        if (off) off();
        if (error) reject(error); else resolve(job);
      }
      function abort() {
        var error = new Error('已停止瀏覽器等待；伺服器工作仍可能繼續'); error.name = 'AbortError'; settle(error);
      }
      if (signal && signal.aborted) { abort(); return; }
      if (signal) signal.addEventListener('abort', abort, { once: true });
      timer = setTimeout(function () {
        var error = new Error('等待更新工作逾時；伺服器仍可能繼續，請到更新工作中心查看'); error.name = 'TimeoutError'; settle(error);
      }, Math.min(timeoutMs, 900000));
      off = subscribe(function (current) {
        for (var hops = 0; hops < 2 && !finished; hops++) {
          var job = current.jobs.find(function (item) { return item.jobId === target; });
          if (!job) return;
          if (options.onProgress) { try { options.onProgress(JSON.parse(JSON.stringify(job))); } catch (e) { settle(e); return; } }
          if (job.status === 'queued' || job.status === 'running') return;
          if (job.status !== 'succeeded') {
            var error = new Error(job.error || '更新工作未成功完成'); error.job = job; settle(error); return;
          }
          var linked = job.result && job.result.marketJobId;
          if (options.followMarket !== false && linked && linked !== target) { target = linked; continue; }
          settle(null, job);
        }
      });
      // subscribe 立即通知既有狀態；若已完成，需清除剛加入的訂閱。
      if (finished && off) off();
    });
  }
  window.UpdateJobs = {
    subscribe: subscribe, refresh: refresh, snapshot: copy,
    submit: function (type, params) { return write('/updates', { type: type, params: params || {} }); },
    retry: function (jobId) { return write('/updates/retry', { jobId: jobId }); },
    wait: waitForJob,
    diagnostics: function () { return { subscribers: listeners.size, timers: timer ? 1 : 0, requests: inflight ? 1 : 0 }; }
  };
}());
