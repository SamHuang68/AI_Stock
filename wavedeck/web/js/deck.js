/* WaveDeck — Wave AI bridge UI + ST (:18432) macro APIs */
(function () {
  'use strict';

  var ST = (typeof window.ST_URL === 'string' && window.ST_URL)
    ? String(window.ST_URL).replace(/\/?$/, '')
    : 'http://127.0.0.1:18432';

  var state = null;
  var stCtx = { styleHint: null, delever: false, note: '', score: null };
  var toastTimer = null;

  function $(id) { return document.getElementById(id); }

  function toast(msg) {
    var el = $('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('on'); }, 2400);
  }

  function fmtPct(x) {
    var n = Number(x);
    if (!isFinite(n)) return '—';
    return Math.round(n * 100) + '%';
  }

  function money(n) {
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return v.toLocaleString('en-US');
  }

  async function api(path, opts) {
    var r = await fetch(path, Object.assign({
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store'
    }, opts || {}));
    var j = await r.json();
    if (!r.ok || j.ok === false) throw new Error((j && j.error) || r.statusText);
    return j;
  }

  function jget(url) {
    return fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function lightClass(v) {
    if (v === 'ok' || v === 'run' || v === 'off' || v === 'idle') return '';
    if (v === 'warn' || v === 'stop') return 'warn';
    if (v === 'bad' || v === 'halt' || v === 'on') return 'bad';
    return '';
  }

  function lightLabel(v) {
    var map = {
      ok: '正常', run: '運行', off: '未啟用', on: '已啟用',
      idle: '待命', warn: '注意', bad: '異常', halt: '停止', stop: '停止'
    };
    return map[v] || String(v);
  }

  function styleFromScore(score, advRatio) {
    var s = Number(score);
    var adv = Number(advRatio);
    if (!isFinite(s)) s = 50;
    var hint = 50;
    if (s >= 70) hint = 65;
    else if (s >= 55) hint = 55;
    else if (s >= 45) hint = 50;
    else if (s >= 30) hint = 40;
    else hint = 35;
    if (isFinite(adv)) {
      if (adv < 0.35) hint = Math.min(hint, 40);
      if (adv > 0.65) hint = Math.max(hint, 55);
    }
    return Math.max(20, Math.min(90, Math.round(hint)));
  }

  function syncStylePresets(style) {
    var n = Number(style);
    document.querySelectorAll('.preset').forEach(function (btn) {
      btn.classList.toggle('on', Number(btn.getAttribute('data-style')) === n);
    });
  }

  function render(s) {
    state = s;
    $('clock').textContent = s.updated_at || '—';
    $('fsm').textContent = s.fsm || '—';
    $('mode').textContent = s.mode || 'paper';
    $('lastTv').textContent = (s.transport && s.transport.last_tv_event) || '—';
    $('webhookStatus').textContent = (s.transport && s.transport.last_webhook_status) || '待命';
    $('transport').textContent = ((s.transport && s.transport.tunnel) || 'local') + ' · ' + ((s.transport && s.transport.domain) || '');

    var L = s.lights || {};
    $('healthChips').innerHTML = [
      ['系統', L.system],
      ['券商 API', L.broker_api],
      ['部位同步', L.position_sync],
      ['緊急停止', L.kill_switch]
    ].map(function (pair) {
      var cls = 'chip ' + (pair[1] === 'ok' || pair[1] === 'run' || pair[1] === 'off' ? 'ok' : (pair[1] === 'on' || pair[1] === 'halt' ? 'bad' : 'warn'));
      return '<span class="' + cls + '"><i class="dot"></i>' + pair[0] + ' · ' + lightLabel(pair[1]) + '</span>';
    }).join('');

    $('stDelever').textContent = (s.st_overlay && s.st_overlay.delever) ? '是' : (stCtx.delever ? '建議是' : '否');
    $('stStyle').textContent = (s.st_overlay && s.st_overlay.aggressiveness != null)
      ? s.st_overlay.aggressiveness
      : (stCtx.styleHint != null ? ('建議 ' + stCtx.styleHint) : '—');
    if (s.st_overlay && s.st_overlay.note) {
      $('stNote').textContent = s.st_overlay.note;
    } else if (stCtx.note) {
      $('stNote').textContent = stCtx.note;
    }

    var p = s.positions || {};
    $('posKv').innerHTML = [
      ['AI 最近建議部位', p.ai_suggested],
      ['TXT 目前目標部位', p.txt_target],
      ['策略部位', p.strategy],
      ['帳戶實際部位', p.account]
    ].map(function (row) {
      return '<div class="kv-row"><span class="lab">' + row[0] + '</span><span class="val">' + row[1] + '</span></div>';
    }).join('');

    var style = Number(s.style || 50);
    $('styleRange').value = String(style);
    $('styleVal').textContent = String(style);
    syncStylePresets(style);

    var no = s.no_overnight || {};
    $('noOvernight').innerHTML =
      '<div class="box-hd">不留倉保護 · ' + (no.enabled ? '啟用' : '關閉') + '</div>' +
      '<p>收盤前 ' + (no.block_new_before_close_min || 15) + ' 分鐘禁新單；' +
      (no.force_flat_time || '13:40') + ' 強制平倉。' + (no.note ? ' ' + no.note : '') + '</p>';

    var ai = s.ai || {};
    $('aiLabel').textContent = ai.action_label || ai.action || '—';
    $('aiConf').textContent = fmtPct(ai.confidence);
    $('aiEvent').textContent = ai.event || '—';
    $('biasLong').textContent = fmtPct(ai.bias_long);
    $('biasShort').textContent = fmtPct(ai.bias_short);
    $('aiSummary').textContent = ai.summary || '—';

    var tags = [];
    if (ai.invalidation) {
      tags.push('<span class="tag warn">失效：' + (ai.invalidation.side === 'below' ? '跌破' : '突破') + ' ' + ai.invalidation.price + '</span>');
    }
    (ai.next_watch || []).forEach(function (t) {
      tags.push('<span class="tag">' + t + '</span>');
    });
    $('aiTags').innerHTML = tags.join('');

    var proc = ai.process || {};
    $('aiProcess').innerHTML =
      '<div>路由 <span>' + (proc.route || '—') + '</span></div>' +
      '<div>追價風險 <span>' + (proc.chase_risk || '—') + '</span></div>' +
      '<div>執行閘門 <span>' + (proc.gate || '—') + '</span></div>' +
      '<div>閘門原因 <span>' + ((proc.gate_reasons && proc.gate_reasons.length) ? proc.gate_reasons.join('／') : '—') + '</span></div>' +
      '<div>更新 <span>' + (ai.updated_at || '—') + '</span></div>' +
      '<div>提供者 <span>' + (ai.provider || (s.costs && s.costs.provider) || '—') + '</span></div>';

    var lightNames = {
      webhook: 'Webhook 接收',
      openai_or_local: '決策引擎',
      email_monitor: 'Email 監控',
      order_signal_file: '下單訊號檔',
      st_bridge: 'ST 橋接',
      risk_watchdog: '風控看門狗',
      audit_db: '稽核資料庫',
      ui_push: 'UI 推送',
      broker_api: '券商 API',
      position_sync: '部位同步',
      system: '系統核心',
      kill_switch: '緊急停止'
    };
    $('lights').innerHTML = Object.keys(lightNames).map(function (k) {
      var v = (s.lights || {})[k] || 'ok';
      return '<div class="light ' + lightClass(v) + '"><i></i><span class="name">' + lightNames[k] + '</span><span class="st">' + lightLabel(v) + '</span></div>';
    }).join('');

    var a = s.account || {};
    var chg = Number(a.equity_change || 0);
    $('acct').innerHTML =
      '<div class="a"><div class="k">昨日餘額</div><div class="v">' + money(a.yesterday_balance) + '</div></div>' +
      '<div class="a"><div class="k">當前權益</div><div class="v">' + money(a.equity) + '</div></div>' +
      '<div class="a"><div class="k">權益變動</div><div class="v ' + (chg < 0 ? 'down' : 'up') + '">' + money(chg) + '</div></div>' +
      '<div class="a"><div class="k">券商連線</div><div class="v">' + (a.broker_api || '—') + '</div></div>';

    var ex = s.exec || {};
    $('execKv').innerHTML = [
      ['最近 AI 動作', ex.last_ai_action],
      ['最近下單動作', ex.last_order_action],
      ['價格', ex.price],
      ['口數', ex.lots]
    ].map(function (row) {
      return '<div class="kv-row"><span class="lab">' + row[0] + '</span><span class="val">' + row[1] + '</span></div>';
    }).join('');

    var c = s.costs || {};
    $('costKv').innerHTML =
      '<div class="a"><div class="k">本次 USD</div><div class="v">' + c.session_usd + '</div></div>' +
      '<div class="a"><div class="k">今日 USD</div><div class="v">' + c.day_usd + '</div></div>' +
      '<div class="a"><div class="k">本月 USD</div><div class="v">' + c.month_usd + '</div></div>' +
      '<div class="a"><div class="k">提供者</div><div class="v">' + (c.provider || '—') + '</div></div>';

    var prov = (c.provider || 'heuristic').toLowerCase();
    if (prov !== 'heuristic' && prov !== 'ollama' && prov !== 'openai') prov = 'heuristic';
    if ($('providerSelect') && $('providerSelect').value !== prov) $('providerSelect').value = prov;

    var mode = (s.mode || 'paper').toLowerCase();
    $('btnModePaper').classList.toggle('cyan', mode === 'paper');
    $('btnModeLive').classList.toggle('cyan', mode === 'live');

    var t = s.transport || {};
    $('transportKv').innerHTML = [
      ['Webhook', t.webhook],
      ['Tunnel', t.tunnel],
      ['Domain', t.domain],
      ['解析錯誤', t.parse_errors]
    ].map(function (row) {
      return '<div class="kv-row"><span class="lab">' + row[0] + '</span><span class="val">' + row[1] + '</span></div>';
    }).join('');
  }

  async function setStyle(n) {
    var j = await api('/api/style', { method: 'POST', body: JSON.stringify({ style: Number(n) }) });
    render(j.state);
    toast('進場風格 → ' + n);
  }

  async function refreshWd() {
    var j = await api('/api/state');
    render(j.state);
    if ($('wdSyncTxt')) $('wdSyncTxt').textContent = 'OK';
  }

  async function refreshSt() {
    var health = await jget(ST + '/health');
    if (!health) {
      if ($('stSyncTxt')) $('stSyncTxt').textContent = 'ST OFF';
      if ($('stNote') && !(state && state.st_overlay && state.st_overlay.note)) {
        $('stNote').textContent = 'ST :18432 未連線（可先開 Stock Terminal）';
      }
      return;
    }
    if ($('stSyncTxt')) $('stSyncTxt').textContent = 'ST OK';

    var pack = await Promise.all([
      jget(ST + '/twindex'),
      jget(ST + '/breadth'),
      jget(ST + '/fundamental/^TWII')
    ]);
    var tw = pack[0] || {};
    var br = pack[1] || {};
    var fund = pack[2] || {};

    var t00 = (tw.indices && (tw.indices.t00 || tw.indices.T00)) || {};
    var px = t00.price;
    var chg = t00.changePct;
    var twEl = $('stTwii');
    if (twEl) {
      twEl.textContent = (px != null && isFinite(px)) ? Number(px).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
      twEl.classList.remove('up', 'dn');
      if (chg > 0) twEl.classList.add('up');
      if (chg < 0) twEl.classList.add('dn');
    }
    $('stTwiiPct').textContent = (chg == null || !isFinite(chg)) ? '—' : ((chg >= 0 ? '+' : '') + Number(chg).toFixed(2) + '%');

    var stocks = br.stocks || {};
    var adv = stocks.advRatio;
    $('stAdv').textContent = (adv != null && isFinite(adv)) ? (Math.round(adv * 100) + '%') : '—';
    $('stBreadth').textContent = (stocks.up != null || stocks.down != null)
      ? ('漲' + (stocks.up || 0) + '／跌' + (stocks.down || 0))
      : (br.date || '—');

    var score = fund.score != null ? fund.score : br.score;
    stCtx.score = score;
    $('stScore').textContent = (score != null && isFinite(score)) ? Math.round(Number(score)) : '—';
    $('stScoreLbl').textContent = fund.label || br.label || '—';

    var hint = styleFromScore(score, adv);
    stCtx.styleHint = hint;
    stCtx.delever = isFinite(score) && Number(score) < 35;
    var summary = fund.plainSummary || fund.summary || br.summary || '';
    stCtx.note = 'ST 體質 ' + (score != null ? Math.round(Number(score)) : '—') +
      ' · 建議風格 ' + hint +
      (stCtx.delever ? ' · 建議降載' : '') +
      (summary ? (' · ' + String(summary).slice(0, 72)) : '');

    if (!(state && state.st_overlay && state.st_overlay.note)) $('stNote').textContent = stCtx.note;
    if (!(state && state.st_overlay && state.st_overlay.aggressiveness != null)) {
      $('stStyle').textContent = '建議 ' + hint;
    }
    $('stDelever').textContent = (state && state.st_overlay && state.st_overlay.delever)
      ? '是' : (stCtx.delever ? '建議是' : '否');
  }

  async function applyStHint() {
    if (stCtx.styleHint == null) await refreshSt();
    if (stCtx.styleHint == null) throw new Error('尚無 ST 建議（確認 :18432）');
    var body = {
      style: stCtx.styleHint,
      delever: !!stCtx.delever,
      note: stCtx.note || ('ST 建議風格 ' + stCtx.styleHint)
    };
    await api('/bridge/st', { method: 'POST', body: JSON.stringify(body) });
    var j2 = await api('/api/style', { method: 'POST', body: JSON.stringify({ style: stCtx.styleHint }) });
    render(j2.state);
    toast('已套用 ST 建議風格 → ' + stCtx.styleHint);
  }

  async function boot() {
    try {
      await refreshWd();
    } catch (e) {
      if ($('wdSyncTxt')) $('wdSyncTxt').textContent = 'ERR';
      throw e;
    }
    refreshSt().catch(function () {});

    setInterval(function () {
      refreshWd().catch(function () { if ($('wdSyncTxt')) $('wdSyncTxt').textContent = 'ERR'; });
    }, 2000);
    setInterval(function () {
      refreshSt().catch(function () { if ($('stSyncTxt')) $('stSyncTxt').textContent = 'ST OFF'; });
    }, 15000);

    $('styleRange').addEventListener('input', function () {
      $('styleVal').textContent = this.value;
      syncStylePresets(this.value);
    });
    $('styleRange').addEventListener('change', function () {
      setStyle(this.value).catch(function (e) { toast(String(e.message || e)); });
    });
    document.querySelectorAll('.preset').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setStyle(btn.getAttribute('data-style')).catch(function (e) { toast(String(e.message || e)); });
      });
    });

    document.querySelectorAll('[data-cmd]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        try {
          var j = await api('/api/control', { method: 'POST', body: JSON.stringify({ cmd: btn.getAttribute('data-cmd') }) });
          render(j.state);
          toast('控制：' + btn.getAttribute('data-cmd'));
        } catch (e) { toast(String(e.message || e)); }
      });
    });

    $('btnDemo').addEventListener('click', async function () {
      try {
        var j = await api('/api/demo_tick', { method: 'POST', body: '{}' });
        render(j.state);
        toast('已模擬 TIMED_MARKET_REVIEW');
      } catch (e) { toast(String(e.message || e)); }
    });

    $('providerSelect').addEventListener('change', async function () {
      try {
        var j = await api('/api/provider', { method: 'POST', body: JSON.stringify({ provider: this.value }) });
        render(j.state);
        toast('決策源 → ' + j.provider);
      } catch (e) { toast(String(e.message || e)); }
    });

    $('btnModePaper').addEventListener('click', async function () {
      try {
        var j = await api('/api/mode', { method: 'POST', body: JSON.stringify({ mode: 'paper' }) });
        render(j.state);
        toast('模式 → paper');
      } catch (e) { toast(String(e.message || e)); }
    });
    $('btnModeLive').addEventListener('click', async function () {
      try {
        var j = await api('/api/mode', { method: 'POST', body: JSON.stringify({ mode: 'live' }) });
        render(j.state);
        toast('模式 → live／TXT');
      } catch (e) { toast(String(e.message || e)); }
    });
    $('btnSyncTxt').addEventListener('click', async function () {
      try {
        var j = await api('/api/sync_txt', { method: 'POST', body: '{}' });
        render(j.state);
        toast('已同步 TXT（' + (j.broker || '') + '）');
      } catch (e) { toast(String(e.message || e)); }
    });

    $('btnKill').addEventListener('click', async function () {
      var j = await api('/api/kill', { method: 'POST', body: JSON.stringify({ on: true }) });
      render(j.state);
      toast('緊急停止已啟用');
    });
    $('btnKillOff').addEventListener('click', async function () {
      var j = await api('/api/kill', { method: 'POST', body: JSON.stringify({ on: false }) });
      render(j.state);
      toast('緊急停止已解除');
    });

    $('btnAudit').addEventListener('click', async function () {
      var j = await api('/api/audit?limit=12');
      var lines = (j.items || []).map(function (it) { return '#' + it.id + ' ' + it.ts + ' ' + it.kind; });
      toast(lines[0] ? lines.slice(0, 3).join(' · ') : '尚無稽核');
      console.log('[WaveDeck audit]', j.items);
    });

    $('btnOpenST').addEventListener('click', function () {
      window.open(ST + '/#pulse', '_blank', 'noopener');
    });
    $('btnPullSt').addEventListener('click', async function () {
      try { await applyStHint(); } catch (e) { toast(String(e.message || e)); }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      boot().catch(function (e) { toast(String(e.message || e)); });
    });
  } else {
    boot().catch(function (e) { toast(String(e.message || e)); });
  }
})();
