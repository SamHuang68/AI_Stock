// ============================================================
// Stock Terminal v3.9 — 台股結算日提醒 (Settlement Reminder)
// ------------------------------------------------------------
// 台股期貨/選擇權/個股期「月結算日」= 每月第三個星期三。
// 結算日前 3 天(含當日)用浮動 toast(window.notifyToast)提醒,每天最多一次。
// 開頁檢查 + 每小時複查(跨日也會觸發)。狀態存 localStorage 去重。
// ============================================================
(function () {
  'use strict';

  // 某年某月(month 0-indexed)的第三個星期三(回 Date,本地時)
  function thirdWednesday(y, m) {
    var first = new Date(y, m, 1);
    var dow = first.getDay();                 // 0=日..6=六
    var firstWedDate = 1 + ((3 - dow + 7) % 7);
    return new Date(y, m, firstWedDate + 14);
  }

  function nextSettlement() {
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var t = thirdWednesday(now.getFullYear(), now.getMonth());
    if (today > t) {                          // 本月結算已過 → 取下月
      var nm = new Date(now.getFullYear(), now.getMonth() + 1, 1);
      t = thirdWednesday(nm.getFullYear(), nm.getMonth());
    }
    return t;
  }

  function check() {
    if (typeof window.notifyToast !== 'function') return;
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var settle = nextSettlement();
    var days = Math.round((settle - today) / 86400000);
    if (days < 0 || days > 3) return;          // 只在結算日前 3 天內(含當日)

    var key = 'settle_reminded_' + today.toISOString().slice(0, 10);
    if (localStorage.getItem(key)) return;     // 今天已提醒過

    var md = (settle.getMonth() + 1) + '/' + settle.getDate();
    var msg = (days === 0)
      ? ('今日為台股結算日(' + md + ',第三個週三)— 期貨/選擇權/個股期月結算')
      : ('台股結算日 ' + md + '(第三個週三)還有 ' + days + ' 天 — 期貨/選擇權/個股期月結算');
    window.notifyToast('📅 結算日提醒', msg, { level: 'warn' });
    try { localStorage.setItem(key, '1'); } catch (e) {}
  }

  (function boot() {
    if (typeof window.notifyToast !== 'function') return setTimeout(boot, 500);
    setTimeout(check, 1500);                    // 開頁後檢查
    setInterval(check, 3600000);                // 每小時複查(跨日觸發)
  })();
})();
