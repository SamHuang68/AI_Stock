/* 估值承接研究：只計算使用者假設，不讀寫行情、帳戶或儲存空間。 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ValuationResearch = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  var labels = { general: '一般獲利企業', ai_cycle: 'AI供應鏈／題材循環', ip: 'IP／不同估值基準' };
  var scopeLabels = { exclude_ip: '排除不同估值基準', pe_unknown: '本益比資料不足', pe_above: '超過本益比上緣', in_scope: '研究範圍內' };
  var stateLabels = { need_assumption: '等待估值假設', below_entry: '已達承接價', in_range: '尚未達承接價', above_range: '高於估值區間' };
  function number(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && !value.trim()) return null;
    var parsed = Number(value);
    return Number.isFinite(parsed) ? (parsed === 0 ? 0 : parsed) : null;
  }
  function missing(value) { return value == null || (typeof value === 'string' && !value.trim()); }
  function symbolKey(value) { return String(value == null ? '' : value).trim().toUpperCase().replace(/\.(TW|TWO)$/, ''); }
  function classify(symbol, category) {
    var selected = Object.prototype.hasOwnProperty.call(labels, category) ? category :
      (['3529', '6643'].indexOf(symbolKey(symbol)) >= 0 ? 'ip' : 'general');
    return { category: selected, categoryLabel: labels[selected] };
  }
  function calculatePosition(tranches, options, currentPrice, exitPrice) {
    options = options || {};
    var errors = [], budget = missing(options.budget) ? null : number(options.budget);
    var result = { shares: 0, principal: null, buyFees: null, totalCost: null, averageCost: null,
      breakEven: null, currentValue: null, currentPnl: null, currentPnlPct: null,
      exitPnl: null, exitPnlPct: null, budget: budget, remainingBudget: budget, errors: errors };
    var defaults = { buyFeePct: 0.1425, sellFeePct: 0.1425, sellTaxPct: 0.3, minFee: 20 };
    var fees = {};
    Object.keys(defaults).forEach(function (key) {
      fees[key] = number(options[key] === undefined ? defaults[key] : options[key]);
      if (fees[key] == null || fees[key] < 0 || (key !== 'minFee' && fees[key] > 10)) {
        errors.push(key === 'minFee' ? '最低手續費須為零或正數。' : '買賣手續費與證交稅率須為零至 10% 的有效數值。');
      }
    });
    if (fees.sellFeePct != null && fees.sellTaxPct != null && fees.sellFeePct + fees.sellTaxPct >= 100) errors.push('賣出費稅合計須小於 100%。');
    if (!missing(options.budget) && (budget == null || budget < 0)) {
      errors.push('資金上限須為零或正數。'); result.budget = result.remainingBudget = null;
    }
    if (!Array.isArray(tranches)) { errors.push('分批持倉須為批次清單。'); return result; }
    var parsed = tranches.map(function (batch, index) {
      var price = number(batch && batch.price), shares = number(batch && batch.shares);
      if (!(price > 0) || !Number.isSafeInteger(shares) || shares <= 0) errors.push('第 ' + (index + 1) + ' 批須填正數價格與正整數股數。');
      return { price: price, shares: shares };
    });
    if (errors.length || !parsed.length) return result;
    var principal = 0, buyFees = 0, shares = 0;
    parsed.forEach(function (batch) {
      var amount = batch.price * batch.shares;
      principal += amount; shares += batch.shares;
      buyFees += Math.max(amount * fees.buyFeePct / 100, fees.minFee);
    });
    var totalCost = principal + buyFees;
    if (!Number.isSafeInteger(shares) || !Number.isFinite(totalCost) || !(totalCost > 0)) {
      errors.push('持倉金額或股數超過可計算範圍。'); return result;
    }
    var sellRate = fees.sellFeePct / 100, taxRate = fees.sellTaxPct / 100;
    // 同時滿足比例費率與最低費，解出含費稅的損益兩平價。
    var breakEven = Math.max(totalCost / (shares * (1 - sellRate - taxRate)),
      (totalCost + fees.minFee) / (shares * (1 - taxRate)));
    if (!Number.isFinite(breakEven)) { errors.push('損益兩平價超過可計算範圍。'); return result; }
    result.shares = shares; result.principal = principal; result.buyFees = buyFees;
    result.totalCost = totalCost; result.averageCost = totalCost / shares; result.breakEven = breakEven;
    result.remainingBudget = budget == null ? null : budget - totalCost;
    if (result.remainingBudget != null && result.remainingBudget < 0) errors.push('累計投入已超過設定資金上限。');
    function profit(value, name) {
      if (missing(value)) return null;
      var price = number(value);
      if (!(price > 0) || !Number.isFinite(price * shares)) { errors.push(name + '須為可計算的正數價格。'); return null; }
      var gross = price * shares;
      return { gross: gross, pnl: gross - Math.max(gross * sellRate, fees.minFee) - gross * taxRate - totalCost };
    }
    var current = profit(currentPrice, '現價'), target = profit(exitPrice, '退出價');
    function percent(pnl) { var value = pnl / totalCost * 100; return Number.isFinite(value) ? value : null; }
    if (current) { result.currentValue = current.gross; result.currentPnl = current.pnl; result.currentPnlPct = percent(current.pnl); }
    if (target) { result.exitPnl = target.pnl; result.exitPnlPct = percent(target.pnl); }
    return result;
  }
  function evaluate(observation, profile, settings) {
    observation = observation || {}; profile = profile || {}; settings = settings || {};
    var category = classify(observation.symbol, profile.category), errors = [];
    var pe = number(observation.officialPe), price = number(observation.price);
    var peMax = number(settings.peMax === undefined ? 30 : settings.peMax);
    if (!(peMax > 0)) errors.push('研究範圍的本益比上緣須為正數。');
    var scope = category.category === 'ip' && settings.excludeIp !== false ? 'exclude_ip' :
      (!(pe > 0) || !(peMax > 0) ? 'pe_unknown' : (pe > peMax ? 'pe_above' : 'in_scope'));
    var eps = number(profile.eps), peLow = number(profile.peLow), peHigh = number(profile.peHigh);
    var low = null, high = null, entry = null, exit = null, status = 'need_assumption';
    if ([profile.eps, profile.peLow, profile.peHigh].some(function (value) { return !missing(value); }) &&
        (!(eps > 0) || !(peLow > 0) || !(peHigh > 0))) errors.push('請完整填寫正數的假設每股盈餘與本益比區間。');
    if (eps > 0 && peLow > 0 && peHigh > 0) {
      if (peLow > peHigh) errors.push('本益比區間下緣不得高於上緣。');
      else if (!(eps * peLow > 0) || !Number.isFinite(eps * peHigh)) errors.push('假設估值超過可計算範圍。');
      else { low = eps * peLow; high = eps * peHigh; }
    }
    function optionalPrice(value, fallback, name) {
      if (missing(value)) return fallback;
      var parsed = number(value);
      if (!(parsed > 0)) { errors.push(name + '須為正數。'); return null; }
      return parsed;
    }
    entry = optionalPrice(profile.entryPrice, low, '承接價');
    exit = optionalPrice(profile.exitPrice, high, '退出價');
    if (low > 0 && high > 0 && entry > 0 && exit > 0 && price > 0) {
      status = price <= entry ? 'below_entry' : (price > high ? 'above_range' : 'in_range');
    }
    var gap = price > 0 && entry > 0 ? (price / entry - 1) * 100 : null;
    var hypothesisPe = price > 0 && eps > 0 ? price / eps : null;
    var position = calculatePosition(profile.tranches === undefined ? [] : profile.tranches, profile, price, exit);
    return { errors: errors.concat(position.errors), category: category.category, categoryLabel: category.categoryLabel,
      scope: scope, valuationStatus: status, low: low, high: high, entry: entry, exit: exit,
      entryGapPct: Number.isFinite(gap) ? gap : null, hypothesisPe: Number.isFinite(hypothesisPe) ? hypothesisPe : null, position: position };
  }
  function day(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:$|T)/.test(value)) return null;
    var key = value.slice(0, 10), parsed = new Date(key + 'T00:00:00Z');
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === key ? key : null;
  }
  // 快照須帶行情日；可傳入 asOf，讓測試與歷史重播採用明確的臺北日期。
  function compareSnapshot(previous, current, asOf) {
    var today = day(asOf === undefined ? new Date(Date.now() + 8 * 3600000).toISOString() : asOf);
    if (!current || !symbolKey(current.symbol) || !today) return [];
    var currentDay = day(current.priceAsOf), valuationDay = missing(current.valuationDate) ? null : day(current.valuationDate);
    if (!currentDay || currentDay > today || (!missing(current.valuationDate) && (!valuationDay || valuationDay > today))) return [];
    if (!previous) return ['首次記錄'];
    if (symbolKey(previous.symbol) !== symbolKey(current.symbol)) return [];
    var previousDay = day(previous.priceAsOf), previousValuation = day(previous.valuationDate);
    if (!previousDay || currentDay < previousDay || (previousValuation && valuationDay && valuationDay < previousValuation)) return [];
    if (previous.profileRevision !== current.profileRevision) return ['估值假設已更新'];
    if (missing(current.profileRevision)) return [];
    var changes = [], previousState = previous.priceState || previous.valuationStatus, currentState = current.priceState || current.valuationStatus;
    if (scopeLabels[previous.scope] && scopeLabels[current.scope] && previous.scope !== current.scope) changes.push('研究範圍：' + scopeLabels[previous.scope] + ' → ' + scopeLabels[current.scope]);
    if (stateLabels[previousState] && stateLabels[currentState] && previousState !== currentState) changes.push('價格狀態：' + stateLabels[previousState] + ' → ' + stateLabels[currentState]);
    return changes;
  }
  return { number: number, classify: classify, evaluate: evaluate, calculatePosition: calculatePosition, compareSnapshot: compareSnapshot };
});
