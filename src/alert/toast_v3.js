// ============================================================
// Stock Terminal v3.9 Phase-1 — 桌面 / 頁內 Toast 通知 (Toast)
// ------------------------------------------------------------
// 提供統一 window.notifyToast(title, body, opts)：
//   - 頁內 toast 卡(右上角堆疊,自動消失,可點關閉)— 永遠顯示
//   - OS 桌面通知(Notification,需權限;alert_v3 原本就有,這裡補頁內卡)
//   - level: 'info'|'warn'|'error' 決定顏色;warn/error 可選嗶聲
// 工具列 🔔 通知 鈕:請求權限 + 開關 + 測試。設定存 localStorage。
// 其他模組(警示/源健檢)可直接呼叫 window.notifyToast。
// ============================================================
(function () {
  'use strict';
  var LS_CFG = 'stock_toast_cfg_v3';
  var cfg = { desktop: true, inpage: true, sound: true };
  try { Object.assign(cfg, JSON.parse(localStorage.getItem(LS_CFG) || '{}')); } catch (e) {}
  function saveCfg() { try { localStorage.setItem(LS_CFG, JSON.stringify(cfg)); } catch (e) {} }

  var LEVEL = {
    info:  { bar: '#3a86ff', icon: 'ℹ' },
    warn:  { bar: '#f1c40f', icon: '⚠' },
    error: { bar: '#e74c3c', icon: '⛔' },
  };

  function container() {
    var c = document.getElementById('toast-wrap');
    if (!c) {
      c = document.createElement('div');
      c.id = 'toast-wrap';
      c.style.cssText = 'position:fixed;top:48px;right:14px;z-index:99999;display:flex;' +
        'flex-direction:column;gap:8px;max-width:320px;pointer-events:none';
      document.body.appendChild(c);
    }
    return c;
  }

  function beep(level) {
    if (!cfg.sound || level === 'info') return;
    try {
      var Ac = window.AudioContext || window.webkitAudioContext;
      if (!Ac) return;
      var ac = new Ac();
      var o = ac.createOscillator(), g = ac.createGain();
      o.connect(g); g.connect(ac.destination);
      o.frequency.value = level === 'error' ? 880 : 660;
      g.gain.value = 0.05;
      o.start();
      setTimeout(function () { o.stop(); ac.close(); }, 180);
    } catch (e) {}
  }

  function inpageCard(title, body, level) {
    if (!cfg.inpage) return;
    var L = LEVEL[level] || LEVEL.info;
    var c = container();
    var card = document.createElement('div');
    card.style.cssText = 'pointer-events:auto;background:#1b1b1b;border:1px solid #333;' +
      'border-left:4px solid ' + L.bar + ';border-radius:6px;padding:9px 12px;' +
      'box-shadow:0 6px 20px rgba(0,0,0,.5);color:#eee;font-size:12px;cursor:pointer;' +
      'animation:toastIn .18s ease-out';
    card.innerHTML = '<div style="font-weight:700;margin-bottom:2px">' + L.icon + ' ' +
      String(title).replace(/</g, '&lt;') + '</div>' +
      '<div style="color:#bbb;line-height:1.4">' + String(body || '').replace(/</g, '&lt;') + '</div>';
    var kill = function () { if (card.parentNode) card.parentNode.removeChild(card); };
    card.onclick = kill;
    c.appendChild(card);
    setTimeout(kill, level === 'error' ? 12000 : 7000);
  }

  function osNotify(title, body, sym) {
    if (!cfg.desktop) return;
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    try {
      var n = new Notification(title, { body: body, icon: '/favicon.ico', tag: 'st-' + Date.now() });
      n.onclick = function () {
        window.focus();
        if (sym && typeof loadSym === 'function') { try { loadSym(sym); } catch (e) {} }
      };
    } catch (e) {}
  }

  // 對外統一入口
  window.notifyToast = function (title, body, opts) {
    opts = opts || {};
    var level = opts.level || 'info';
    inpageCard(title, body, level);
    if (!opts.skipDesktop) osNotify(title, body, opts.sym);   // alert_v3 自有 OS 通知時傳 skipDesktop 避免重複
    beep(level);
    console.log('[toast] ' + level + ': ' + title + ' — ' + (body || ''));
  };

  function requestPerm() {
    if (typeof Notification === 'undefined') return Promise.resolve('unavailable');
    if (Notification.permission === 'granted') return Promise.resolve('granted');
    return Notification.requestPermission();
  }

  function openMenu(anchor) {
    var old = document.getElementById('toast-menu');
    if (old) { old.remove(); return; }
    var m = document.createElement('div');
    m.id = 'toast-menu';
    m.style.cssText = 'position:absolute;top:100%;right:0;z-index:99999;margin-top:4px;' +
      'min-width:180px;background:#161616;border:1px solid #333;border-radius:6px;' +
      'box-shadow:0 6px 20px rgba(0,0,0,.5);padding:6px;font-size:12px';
    var perm = (typeof Notification !== 'undefined') ? Notification.permission : 'unavailable';
    function row(label, key) {
      return '<label style="display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer">' +
        '<input type="checkbox" data-k="' + key + '"' + (cfg[key] ? ' checked' : '') + '>' + label + '</label>';
    }
    m.innerHTML =
      '<div style="padding:4px 6px;color:#888">桌面通知權限：<b style="color:' +
        (perm === 'granted' ? '#3ecf6b' : (perm === 'denied' ? '#e74c3c' : '#f1c40f')) + '">' + perm + '</b></div>' +
      (perm !== 'granted' && perm !== 'unavailable'
        ? '<button id="tm-perm" style="width:100%;margin:2px 0 6px;padding:5px;cursor:pointer;border:1px solid #4a8;background:rgba(62,207,107,.12);color:#3ecf6b;border-radius:5px">啟用桌面通知</button>' : '') +
      row('桌面通知', 'desktop') + row('頁內 Toast', 'inpage') + row('提示音', 'sound') +
      '<button id="tm-test" style="width:100%;margin-top:6px;padding:5px;cursor:pointer;border:1px solid #333;background:#222;color:#ccc;border-radius:5px">測試通知</button>';
    anchor.appendChild(m);
    m.addEventListener('click', function (e) { e.stopPropagation(); });
    m.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
      cb.onchange = function () { cfg[cb.dataset.k] = cb.checked; saveCfg(); };
    });
    var pb = m.querySelector('#tm-perm');
    if (pb) pb.onclick = function () { requestPerm().then(function () { m.remove(); }); };
    m.querySelector('#tm-test').onclick = function () {
      window.notifyToast('測試通知', '這是一則測試 — 桌面+頁內 toast 正常運作', { level: 'warn' });
    };
  }

  (function inject() {
    if (!document.getElementById('pro-tools')) return setTimeout(inject, 150);
    if (document.getElementById('btn-toast')) return;
    var wrap = document.createElement('span');
    wrap.style.cssText = 'position:relative;display:inline-block';
    var b = document.createElement('button');
    b.id = 'btn-toast';
    b.className = 'probtn';
    b.title = '通知設定:桌面/頁內 toast/提示音 (v3.9 Phase-1)';
    b.textContent = '🔔 通知';
    b.onclick = function (e) { e.stopPropagation(); openMenu(wrap); };
    document.addEventListener('click', function () {
      var m = document.getElementById('toast-menu'); if (m) m.remove();
    });
    wrap.appendChild(b);
    document.getElementById('pro-tools').appendChild(wrap);
  })();

  // toast 進場動畫
  var st = document.createElement('style');
  st.textContent = '@keyframes toastIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}';
  document.head.appendChild(st);
})();
