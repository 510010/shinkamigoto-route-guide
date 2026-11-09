/* 上五島航路案内 app.js（バニラJS） */
'use strict';

/* ============ ユーティリティ ============ */
const $ = (sel) => document.querySelector(sel);

function pad2(n) { return String(n).padStart(2, '0'); }
// "YYYY-MM-DD" をローカル日付としてパース（タイムゾーンずれ防止）
function parseDate(str) {
  const [y, m, d] = str.split('-').map(Number);
  return new Date(y, m - 1, d);
}
function fmtDate(dt) {
  return dt.getFullYear() + '-' + pad2(dt.getMonth() + 1) + '-' + pad2(dt.getDate());
}
function addDays(dt, n) {
  const d = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
  d.setDate(d.getDate() + n);
  return d;
}
function todayStr() { return fmtDate(new Date()); }
function mdOf(dt) { return pad2(dt.getMonth() + 1) + '-' + pad2(dt.getDate()); }
// 年跨ぎ対応の月日範囲判定（from > to の場合は年末年始をまたぐ）
function mdInRange(md, fromMd, toMd) {
  if (fromMd <= toMd) return md >= fromMd && md <= toMd;
  return md >= fromMd || md <= toMd;
}
function timeToMin(t) {
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}
function durText(min) {
  if (min == null || isNaN(min)) return '';
  const h = Math.floor(min / 60), m = min % 60;
  return h > 0 ? h + '時間' + (m ? m + '分' : '') : m + '分';
}
function yen(n) {
  return (n == null || n === '') ? '-' : Number(n).toLocaleString('ja-JP') + '円';
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
const WEEKDAYS_JA = ['日', '月', '火', '水', '木', '金', '土'];
function dateLabel(str) {
  const d = parseDate(str);
  return (d.getMonth() + 1) + '月' + d.getDate() + '日（' + WEEKDAYS_JA[d.getDay()] + '）';
}
// 運賃の船種表記ゆれ正規化（"フェリー2等"→"フェリー"、"高速船（TAIYO）"→"高速船"）
function normVessel(v) {
  return String(v || '').replace(/2等/g, '').replace(/（.*?）/g, '').replace(/\(.*?\)/g, '').trim();
}
// 日数オフセットのラベル
function offLabel(rel) {
  if (!rel) return '';
  if (rel === 1) return '<span class="day-badge">翌日</span>';
  if (rel === 2) return '<span class="day-badge">翌々日</span>';
  if (rel > 2) return '<span class="day-badge">' + rel + '日後</span>';
  if (rel === -1) return '<span class="day-badge">前日</span>';
  return '<span class="day-badge">' + (-rel) + '日前</span>';
}

/* ============ 状態 ============ */
let DB = null;
let portById = {}, operatorById = {}, routeById = {};

function portName(pid) {
  const p = portById[pid];
  return p ? p.name : pid;
}

/* ============ 港のグループ分け・到達可能性 ============ */
// municipality でグループ化（新上五島町を先頭に、他は ports 配列の初出順）
function portGroups() {
  const groups = [];
  const byMuni = new Map();
  for (const p of DB.ports) {
    const muni = p.municipality || 'その他';
    if (!byMuni.has(muni)) { byMuni.set(muni, []); groups.push({ muni, ports: byMuni.get(muni) }); }
    byMuni.get(muni).push(p);
  }
  groups.sort((a, b) => (a.muni === '新上五島町' ? 0 : 1) - (b.muni === '新上五島町' ? 0 : 1));
  return groups;
}
function groupLabel(muni) {
  return muni + (muni === '新上五島町' ? '（島内）' : '（島外）');
}
// select の選択肢HTML。allowed が Set の場合はその港だけに絞る
function portOptionsHtml(allowed) {
  let html = '<option value="">選択してください</option>';
  for (const g of portGroups()) {
    const ps = g.ports.filter((p) => !allowed || allowed.has(p.port_id));
    if (!ps.length) continue;
    html += '<optgroup label="' + esc(groupLabel(g.muni)) + '">' +
      ps.map((p) => `<option value="${esc(p.port_id)}">${esc(portName(p.port_id))}</option>`).join('') +
      '</optgroup>';
  }
  return html;
}
// trips から「同一便の stops に順序どおり両港が含まれる」ペアを到達可能として計算
let reachMap = new Map();
function buildReachability() {
  reachMap = new Map();
  for (const trip of DB.trips) {
    const stops = trip.stops;
    for (let i = 0; i < stops.length; i++) {
      if (!stops[i].dep) continue;
      for (let j = i + 1; j < stops.length; j++) {
        if (!stops[j].arr) continue;
        if (stops[j].port_id === stops[i].port_id) continue;
        if (!reachMap.has(stops[i].port_id)) reachMap.set(stops[i].port_id, new Set());
        reachMap.get(stops[i].port_id).add(stops[j].port_id);
      }
    }
  }
}
// 出発港に応じて到着港の選択肢を絞り込む。preferred があれば優先して残す
function refreshToOptions(preferred) {
  const from = $('#from-port').value;
  const cur = preferred !== undefined ? preferred : $('#to-port').value;
  const allowed = from ? (reachMap.get(from) || new Set()) : null;
  $('#to-port').innerHTML = portOptionsHtml(allowed);
  if (cur && cur !== from && (!allowed || allowed.has(cur))) {
    $('#to-port').value = cur;
  } else if (allowed && allowed.size === 1) {
    $('#to-port').value = [...allowed][0]; // 行ける港が1つだけなら自動選択
  } else {
    $('#to-port').value = '';
  }
}
// 出発・到着がそろっていれば即座に検索する
function autoSearch() {
  const from = $('#from-port').value, to = $('#to-port').value;
  if (from && to) doSearch();
}
// お気に入りチップから区間をセットして検索する
function setRoute(from, to) {
  $('#from-port').value = from;
  refreshToOptions(to);
  updateFavButton();
  autoSearch();
}

/* ============ 時刻表検索ロジック ============ */
// パターンが便の運行開始日 S に適用されるか
function patternApplies(pattern, S) {
  if (!pattern) return true;
  let has = false, ok = false;
  const sStr = fmtDate(S);
  if (pattern.valid_from || pattern.valid_to) {
    has = true;
    if ((!pattern.valid_from || sStr >= pattern.valid_from) &&
        (!pattern.valid_to || sStr <= pattern.valid_to)) ok = true;
  }
  if (pattern.recurs && pattern.recurs.from_md && pattern.recurs.to_md) {
    has = true;
    if (mdInRange(mdOf(S), pattern.recurs.from_md, pattern.recurs.to_md)) ok = true;
  }
  return has ? ok : true;
}
// 例外（運休）に該当すればその exception を返す
function exceptionHit(trip, S) {
  const sStr = fmtDate(S);
  for (const ex of DB.exceptions) {
    if (sStr < ex.date_from || sStr > ex.date_to) continue;
    let scopeOk = false;
    if (ex.scope_type === 'trip') scopeOk = (ex.scope === trip.id);
    else if (ex.scope_type === 'trip_prefix') scopeOk = trip.id.startsWith(ex.scope);
    else if (ex.scope_type === 'route') scopeOk = (ex.scope === trip.route_id);
    if (!scopeOk) continue;
    if (ex.kind === 'suspended') return ex;
    if (ex.kind === 'weekday_suspended') {
      const wds = String(ex.weekdays || '').split(',').map((s) => s.trim()).filter((s) => s !== '').map(Number);
      if (wds.includes(S.getDay())) return ex;
    }
  }
  return null;
}
// 検索本体：{results:[{trip, fromStop, toStop, S}], suspendedNotes:[...], anyCandidate:bool}
function searchTrips(fromId, toId, dateStr) {
  const D = parseDate(dateStr);
  const candidates = [];
  for (const trip of DB.trips) {
    // stops 内で 出発港（発あり）→到着港（着あり）が順序どおり現れる組を探す
    let pair = null;
    for (let i = 0; i < trip.stops.length && !pair; i++) {
      const s = trip.stops[i];
      if (s.port_id !== fromId || !s.dep) continue;
      for (let j = i + 1; j < trip.stops.length; j++) {
        const t = trip.stops[j];
        if (t.port_id === toId && t.arr) { pair = { fromStop: s, toStop: t }; break; }
      }
    }
    if (!pair) continue;
    // 便の運行開始日 S：出発港の出発日が選択日 D になるよう dep_off で逆算
    const depOff = pair.fromStop.dep_off || 0;
    const S = addDays(D, -depOff);
    if (!patternApplies(trip.pattern, S)) continue;
    candidates.push({ trip, fromStop: pair.fromStop, toStop: pair.toStop, S });
  }
  // 例外パターンの優先：同 route で「例外」kind の便が適用される場合、通常・季節の便を除外
  const exceptionRoutes = new Set(
    candidates.filter((c) => (c.trip.pattern.kind || '').startsWith('例外')).map((c) => c.trip.route_id)
  );
  const prioritized = candidates.filter((c) => {
    if (!exceptionRoutes.has(c.trip.route_id)) return true;
    const k = c.trip.pattern.kind || '';
    return !(k === '通常' || k === '季節');
  });
  const results = [], suspendedNotes = [];
  for (const c of prioritized) {
    const ex = exceptionHit(c.trip, c.S);
    if (ex) {
      if (ex.note && !suspendedNotes.includes(ex.note)) suspendedNotes.push(ex.note);
      continue;
    }
    results.push(c);
  }
  results.sort((a, b) => timeToMin(a.fromStop.dep) - timeToMin(b.fromStop.dep));
  return { results, suspendedNotes, anyCandidate: prioritized.length > 0 };
}

/* ============ 運賃の対応付け ============ */
// dateStr は乗船日（ユーザーが選んだ日付）。便の運行開始日 S ではなく選択日で照合する。
// 適用期間の優先順位：
//   1) 乗船日が valid_from〜valid_to に含まれるレコード（valid_to 空欄は無期限）
//   2) 無ければ、乗船日より前の期間のうち最も新しい月（蓄積済みの最新月）
//   3) それも無ければ（乗船日が全期間より前）最も古い期間
// 期間で候補を絞った後、従来どおり船種の一致度で選ぶ。
function farePeriodPool(cands, dateStr) {
  if (!dateStr) return cands;
  const inside = cands.filter((f) =>
    (!f.valid_from || f.valid_from <= dateStr) && (!f.valid_to || dateStr <= f.valid_to));
  if (inside.length) return inside;
  const past = cands.filter((f) => f.valid_to && f.valid_to < dateStr);
  if (past.length) {
    const latestTo = past.reduce((a, b) => (a.valid_to >= b.valid_to ? a : b)).valid_to;
    return past.filter((f) => f.valid_to === latestTo);
  }
  const earliestFrom = cands.reduce((a, b) =>
    ((a.valid_from || '') <= (b.valid_from || '') ? a : b)).valid_from;
  return cands.filter((f) => f.valid_from === earliestFrom);
}
function findFare(operatorId, fromId, toId, category, vesselType, dateStr) {
  const all = DB.fares.filter((f) =>
    f.operator_id === operatorId && f.from_port_id === fromId &&
    f.to_port_id === toId && f.category === category);
  if (!all.length) return null;
  const cands = farePeriodPool(all, dateStr);
  const nv = normVessel(vesselType);
  let best = null, bestScore = -1;
  for (const f of cands) {
    const fv = normVessel(f.vessel_type);
    let score = 0;
    if (fv && fv === nv) score = 3;
    else if (!fv) score = 1;
    else if (fv && nv && (fv.includes(nv) || nv.includes(fv))) score = 2;
    if (score > bestScore) { bestScore = score; best = f; }
  }
  return best;
}
function fareMonthNote(fare) {
  // 「（YYYY年M月分）」は、燃料調整金で月ごとに運賃が変わる九州商船だけに付ける。
  // 他社は valid_from が改定日であって月変動ではないため付けない。
  if (!fare || fare.operator_id !== 'kyushu' || !fare.valid_from) return '';
  const [y, m] = fare.valid_from.split('-');
  return '（' + y + '年' + Number(m) + '月分）';
}
// 九州商船の燃料油価格変動調整金を、区間・船種・乗船月から引く
function surchargeSegmentFor(vt, a, b) {
  const key = [a, b].sort().join('|');
  if (vt === 'ジェットフォイル') return key === 'fukue|narao' ? '福江〜奈良尾（島内間）' : '長崎〜福江・奈良尾（長崎〜離島）';
  if (vt === '高速船') {
    if (key === 'ojika|ukuhira') return '小値賀〜宇久平';
    if (key === 'arikawa|ojika') return '有川〜小値賀';
    if (key === 'arikawa|ukuhira') return '有川〜宇久平';
    return '佐世保〜有川・小値賀・宇久平（佐世保〜離島）';
  }
  if (vt === 'フェリー') {
    if (['sasebo', 'arikawa', 'ojika', 'ukuhira'].includes(a)) {
      return key === 'ojika|ukuhira' ? '小値賀〜宇久平（島内間）' : '佐世保〜有川・小値賀・宇久平（佐世保〜離島）';
    }
    if (['fukue|narao', 'fukue|naru', 'narao|naru'].includes(key)) return '島内間（福江〜奈良尾・福江〜奈留・奈留〜奈良尾）';
    return '長崎〜福江・奈留・奈良尾（長崎〜離島）';
  }
  return null;
}
function findSurcharge(operatorId, vesselType, fromId, toId, dateStr) {
  if (operatorId !== 'kyushu' || !DB.surcharges) return null;
  const seg = surchargeSegmentFor(normVessel(vesselType), fromId, toId);
  if (!seg) return null;
  const cands = DB.surcharges.filter((s) => s.segment === seg && normVessel(s.vessel_type) === normVessel(vesselType));
  if (!cands.length) return null;
  const ym = (dateStr || '').slice(0, 7);
  let s = cands.find((x) => x.year_month === ym);
  if (!s) {
    const past = cands.filter((x) => x.year_month <= ym).sort((x, y) => y.year_month.localeCompare(x.year_month));
    s = past[0] || cands.slice().sort((x, y) => x.year_month.localeCompare(y.year_month))[0];
  }
  return s;
}

/* ============ お気に入り（localStorage） ============ */
const LS_FAV = 'kamigoto.favorites';
function lsGet(key, fallback) {
  try { const v = JSON.parse(localStorage.getItem(key)); return v == null ? fallback : v; }
  catch (e) { return fallback; }
}
function lsSet(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* 保存不可でも動作継続 */ }
}
function getFavorites() { return lsGet(LS_FAV, []); }
function isFavorite(from, to) { return getFavorites().some((f) => f.from === from && f.to === to); }
function toggleFavorite(from, to) {
  let favs = getFavorites();
  if (isFavorite(from, to)) favs = favs.filter((f) => !(f.from === from && f.to === to));
  else favs.push({ from, to });
  lsSet(LS_FAV, favs);
}

/* ============ 時刻表タブ ============ */
function renderNotices() {
  const today = new Date();
  const todayS = fmtDate(today);
  const limitS = fmtDate(addDays(today, 30));
  const items = DB.notices.filter((n) =>
    (n.date_from <= todayS && todayS <= n.date_to) ||
    (todayS < n.date_from && n.date_from <= limitS)
  ).sort((a, b) => (a.date_from < b.date_from ? -1 : 1));
  const box = $('#notices');
  if (!items.length) { box.innerHTML = ''; return; }
  // 折りたたみ式：初期表示は見出し＋タイトル1行のみ。本文はタップで展開
  box.innerHTML = `
    <div class="notices-box">
      <p class="notices-head">📢 お知らせ（${items.length}件）</p>
      ${items.map((n, i) => `
      <div class="notice-item">
        <button type="button" class="notice-toggle" data-i="${i}" aria-expanded="false">
          <span class="notice-item-title">${esc(n.title)}</span>
          <span class="notice-chevron" aria-hidden="true">▽</span>
        </button>
        <div class="notice-detail" hidden>
          <p class="notice-body">${esc(n.body)}</p>
          <p class="notice-period">${esc(dateLabel(n.date_from))}〜${esc(dateLabel(n.date_to))}${n.url ? ' ／ <a href="' + esc(n.url) + '" target="_blank" rel="noopener">公式情報</a>' : ''}</p>
        </div>
      </div>`).join('')}
    </div>`;
  box.querySelectorAll('.notice-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      const detail = btn.nextElementSibling;
      const open = detail.hidden;
      detail.hidden = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.querySelector('.notice-chevron').textContent = open ? '△' : '▽';
    });
  });
}

function renderChips() {
  // 統合・改称で存在しなくなった港を含むチップは表示しない
  const valid = (h) => portById[h.from] && portById[h.to];
  const favs = getFavorites().filter(valid);
  $('#fav-block').hidden = favs.length === 0;
  const chip = (h) => `<button type="button" class="chip" data-from="${esc(h.from)}" data-to="${esc(h.to)}">${esc(portName(h.from))} → ${esc(portName(h.to))}</button>`;
  $('#fav-chips').innerHTML = favs.map(chip).join('');
  document.querySelectorAll('#quick-chips .chip').forEach((el) => {
    el.addEventListener('click', () => setRoute(el.dataset.from, el.dataset.to));
  });
}

function updateFavButton() {
  const from = $('#from-port').value, to = $('#to-port').value;
  const on = isFavorite(from, to);
  const btn = $('#fav-toggle');
  btn.classList.toggle('on', on);
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  btn.textContent = on ? '★ お気に入り登録済み' : '☆ お気に入りに登録';
}

// 今日の検索でのみ、現在時刻より後で最も早い便の index を返す（なければ -1）。
// 結果は出発時刻順に並んでいる前提。運休便は結果に含まれないため対象にならない。
function findNextTripIndex(results, dateStr, now) {
  if (dateStr !== fmtDate(now)) return -1;
  const nowMin = now.getHours() * 60 + now.getMinutes();
  for (let i = 0; i < results.length; i++) {
    if (timeToMin(results[i].fromStop.dep) > nowMin) return i;
  }
  return -1;
}

function tripCard(c, idx, dateStr, isNext) {
  const { trip, fromStop, toStop } = c;
  const op = operatorById[trip.operator_id] || {};
  const route = routeById[trip.route_id] || {};
  const depMin = timeToMin(fromStop.dep) + (fromStop.dep_off || 0) * 1440;
  const arrMin = timeToMin(toStop.arr) + (toStop.arr_off || 0) * 1440;
  const relArr = (toStop.arr_off || 0) - (fromStop.dep_off || 0);
  const vesselType = trip.vessel_type || route.vessel_type;
  const fare = findFare(trip.operator_id, fromStop.port_id, toStop.port_id, 'general', vesselType, dateStr);
  const resFare = findFare(trip.operator_id, fromStop.port_id, toStop.port_id, 'resident', vesselType, dateStr);
  const hasResFare = !!(resFare && resFare.adult_oneway !== '' && resFare.adult_oneway != null);
  // カード面の運賃行：一般大人片道に島民割引大人片道を併記（島民運賃がある区間のみ）。
  // 月表記は九州商船の場合のみ、両区分共通で末尾に1回だけ付ける。
  let fareLine;
  if (fare || hasResFare) {
    const parts = [];
    if (fare) parts.push('<span class="fare-part">一般大人片道 ' + yen(fare.adult_oneway) + '</span>');
    if (hasResFare) parts.push('<span class="fare-part">島民割引 ' + yen(resFare.adult_oneway) + '</span>');
    const mn = fareMonthNote(fare) || (hasResFare ? fareMonthNote(resFare) : '');
    fareLine = parts.join(' ／ ') + (mn ? ' <span class="fare-note">' + esc(mn) + '</span>' : '');
  } else {
    fareLine = '<span class="fare-note">運賃は詳細・公式でご確認ください</span>';
  }
  // 船種と船名の表示組み立て（「高速船（高速船（シークイーン））」のような重複を避ける）
function vesselLabelOf(vesselType, vesselName) {
  const vt = vesselType || '', vn = vesselName || '';
  if (!vn || vn === vt) return vt;
  if (vn.startsWith(vt)) return vn;                    // 高速船 + 高速船（シークイーン）→ 後者だけ
  if (vt.indexOf('（' + vn + '）') >= 0) return vt;    // フェリー（OCEAN） + OCEAN → 前者だけ
  return vt + '（' + vn + '）';                        // フェリー + 太古 → フェリー（太古）
}
const vesselLabel = vesselLabelOf(trip.vessel_type || route.vessel_type || '', trip.vessel_name);
  return `
  <article class="trip-card${isNext ? ' next-trip' : ''}" data-idx="${idx}" tabindex="0" aria-label="便の詳細を開く">
    <div class="trip-top">
      <span class="trip-op">${esc(op.name || '')}</span>
      ${isNext ? '<span class="next-badge">次の便</span>' : ''}
      <span class="trip-vessel">${esc(vesselLabel)}${trip.direction ? ' ／ ' + esc(trip.direction) : ''}</span>
    </div>
    <div class="trip-times">
      <span class="trip-time-big">${esc(fromStop.dep)}</span>
      <span class="trip-arrow">→</span>
      <span class="trip-time-big">${esc(toStop.arr)}${offLabel(relArr)}</span>
      <span class="trip-dur">${esc(portName(fromStop.port_id))} 発 ／ ${esc(portName(toStop.port_id))} 着 ・ ${durText(arrMin - depMin)}</span>
    </div>
    <div class="trip-fare">${fareLine}</div>
    <div class="trip-detail" hidden></div>
  </article>`;
}

function tripDetailHtml(c, dateStr) {
  const { trip, fromStop } = c;
  const op = operatorById[trip.operator_id] || {};
  const route = routeById[trip.route_id] || {};
  const baseOff = fromStop.dep_off || 0;
  const stopsHtml = trip.stops.map((s) => {
    const aRel = (s.arr_off != null ? s.arr_off : (s.dep_off || 0)) - baseOff;
    const dRel = (s.dep_off != null ? s.dep_off : (s.arr_off || 0)) - baseOff;
    const parts = [];
    if (s.arr) parts.push('<span class="lbl">着</span>' + esc(s.arr) + offLabel(aRel));
    if (s.dep) parts.push('<span class="lbl">発</span>' + esc(s.dep) + offLabel(dRel));
    return `<li><span class="stop-name">${esc(portName(s.port_id))}</span><span class="stop-times">${parts.join('　')}</span></li>`;
  }).join('');
  // 区間運賃表（一般／島民）
  const rows = [];
  for (const [cat, label] of [['general', '一般'], ['resident', '島民割引']]) {
    const f = findFare(trip.operator_id, fromStop.port_id, c.toStop.port_id, cat, trip.vessel_type || route.vessel_type, dateStr);
    if (f) rows.push(`<tr><td>${label}${fareMonthNote(f) ? '<br><span class="fare-note">' + esc(fareMonthNote(f)) + '</span>' : ''}</td><td>${yen(f.adult_oneway)}</td><td>${yen(f.child_oneway)}</td><td>${yen(f.adult_roundtrip)}</td><td>${yen(f.child_roundtrip)}</td></tr>`);
  }
  const fareHtml = rows.length ? `
    <table class="fare-mini">
      <tr><th>区分</th><th>大人片道</th><th>小人片道</th><th>大人往復</th><th>小人往復</th></tr>
      ${rows.join('')}
    </table>` : '<p class="detail-note">この区間の運賃データはありません。公式情報でご確認ください。</p>';
  const notes = [];
  const sur = findSurcharge(trip.operator_id, trip.vessel_type || route.vessel_type, fromStop.port_id, c.toStop.port_id, dateStr);
  if (sur) {
    const ym = sur.year_month.split('-');
    notes.push('上記運賃には燃料油価格変動調整金 ' + yen(sur.adult) + '（片道・' + ym[0] + '年' + Number(ym[1]) + '月分）が含まれます。');
  }
  if (route.reservation_required === '1' || route.reservation_required === 1 || route.reservation_required === true) notes.push('乗船には予約が必要です。');
  if (route.checkin_deadline_min) notes.push('受付締切：出発の' + route.checkin_deadline_min + '分前');
  if (trip.note) notes.push(trip.note);
  if (trip.pattern && trip.pattern.name) notes.push('ダイヤ：' + trip.pattern.name);
  if (route.note) notes.push(route.note);
  const links = [];
  if (op.official_url) links.push('<a href="' + esc(op.official_url) + '" target="_blank" rel="noopener">公式サイト</a>');
  if (op.status_url) links.push('<a href="' + esc(op.status_url) + '" target="_blank" rel="noopener">運航状況</a>');
  if (op.reservation_url) links.push('<a href="' + esc(op.reservation_url) + '" target="_blank" rel="noopener">予約</a>');
  if (op.phone) links.push('<a href="tel:' + esc(op.phone) + '">📞 ' + esc(op.name) + ' ' + esc(op.phone) + '</a>');
  return `
    <h4 style="margin:0 0 6px">寄港地と発着時刻</h4>
    <ul class="stop-list">${stopsHtml}</ul>
    <h4 style="margin:10px 0 2px">この区間の運賃（${esc(portName(fromStop.port_id))} → ${esc(portName(c.toStop.port_id))}）</h4>
    ${fareHtml}
    ${notes.map((n) => '<p class="detail-note">※ ' + esc(n) + '</p>').join('')}
    <div class="detail-links">${links.join('')}</div>`;
}

function doSearch() {
  const from = $('#from-port').value;
  const to = $('#to-port').value;
  const dateStr = $('#date-input').value || todayStr();
  const box = $('#results');
  if (from === to) {
    box.innerHTML = '<div class="empty-box"><span class="big">出発港と到着港が同じです</span>異なる港を選んでください。</div>';
    return;
  }
  const { results, suspendedNotes, anyCandidate } = searchTrips(from, to, dateStr);
  const head = `<p class="result-head">${esc(portName(from))} → ${esc(portName(to))} ／ ${esc(dateLabel(dateStr))} の便</p>`;
  if (results.length) {
    const nextIdx = findNextTripIndex(results, dateStr, new Date());
    box.innerHTML = head + results.map((c, i) => tripCard(c, i, dateStr, i === nextIdx)).join('');
    box.querySelectorAll('.trip-card').forEach((card) => {
      const toggle = () => {
        const detail = card.querySelector('.trip-detail');
        if (detail.hidden) {
          detail.innerHTML = tripDetailHtml(results[Number(card.dataset.idx)], dateStr);
          detail.hidden = false;
        } else detail.hidden = true;
      };
      card.addEventListener('click', (e) => { if (!e.target.closest('a')) toggle(); });
      card.addEventListener('keydown', (e) => { if (e.key === 'Enter') toggle(); });
    });
  } else if (anyCandidate) {
    box.innerHTML = head + `<div class="empty-box"><span class="big">この日は運休です</span>${suspendedNotes.map(esc).join('／')}<br>別の日付でお試しください。</div>`;
  } else {
    box.innerHTML = head + `<div class="empty-box"><span class="big">この日に利用できる便がありません</span>直行便がない区間、またはデータ収集範囲外の期間の可能性があります。<br>各事業者の公式情報もご確認ください。</div>`;
  }
}

/* ============ 運賃表タブ ============ */
function renderFares() {
  const opId = $('#fare-operator').value;
  const op = operatorById[opId] || {};
  const isKyushu = opId === 'kyushu';
  const portOrder = (pid) => DB.ports.findIndex((p) => p.port_id === pid);
  // 九州商船は乗船月で絞る（月セレクタは九州商船のときだけ表示）
  let selMonth = '';
  $('#fare-month-field').hidden = !isKyushu;
  if (isKyushu) {
    const months = [...new Set(DB.fares.filter((f) => f.operator_id === 'kyushu').map((f) => (f.valid_from || '').slice(0, 7)).filter(Boolean))].sort();
    const mSel = $('#fare-month');
    const prev = mSel.value;
    mSel.innerHTML = months.map((m) => {
      const [y, mo] = m.split('-');
      return `<option value="${m}">${y}年${Number(mo)}月分</option>`;
    }).join('');
    const nowYm = todayStr().slice(0, 7);
    selMonth = months.includes(prev) ? prev : (months.includes(nowYm) ? nowYm : months[months.length - 1]);
    mSel.value = selMonth;
  }
  let list = DB.fares.filter((f) => f.operator_id === opId);
  if (isKyushu) list = list.filter((f) => (f.valid_from || '').slice(0, 7) === selMonth);
  // 方向違いは金額が同じため、区間（無方向）でまとめて表示を半分にする
  const groups = new Map();
  for (const f of list) {
    const lo = portOrder(f.from_port_id) <= portOrder(f.to_port_id) ? f.from_port_id : f.to_port_id;
    const hi = lo === f.from_port_id ? f.to_port_id : f.from_port_id;
    const key = lo + '|' + hi + '|' + (f.vessel_type || '') + '|' + (isKyushu ? '' : (f.valid_from || ''));
    if (!groups.has(key)) groups.set(key, { from: lo, to: hi, vessel: f.vessel_type || '', validFrom: f.valid_from || '', rows: {} });
    const g = groups.get(key);
    if (!g.rows[f.category]) g.rows[f.category] = f;
  }
  const sorted = [...groups.values()].sort((a, b) =>
    portOrder(a.from) - portOrder(b.from) || portOrder(a.to) - portOrder(b.to) || a.vessel.localeCompare(b.vessel, 'ja') ||
    (a.validFrom < b.validFrom ? -1 : a.validFrom > b.validFrom ? 1 : 0));
  let html = '';
  if (isKyushu && selMonth) {
    const [y, mo] = selMonth.split('-');
    html += `<p class="fare-month-head">${y}年${Number(mo)}月分の運賃を表示しています（燃料油価格変動調整金込み）。他の月は上の「乗船月」で切り替えてください。</p>`;
  }
  html += sorted.map((g) => {
    const rowFor = (cat, label) => {
      const f = g.rows[cat];
      if (!f) return '';
      const period = (f.valid_from || '') + (f.valid_to ? '〜' + f.valid_to : '');
      const periodCell = isKyushu ? '' : `<td>${esc(period)}</td>`;
      return `<tr class="${cat === 'resident' ? 'cat-resident' : ''}">
        <td>${label}</td><td>${yen(f.adult_oneway)}</td><td>${yen(f.child_oneway)}</td>
        <td>${yen(f.adult_roundtrip)}</td><td>${yen(f.child_roundtrip)}</td>
        ${periodCell}<td class="fare-note-cell">${esc(f.note || '')}</td></tr>`;
    };
    return `<div class="fare-group">
      <h3>${esc(portName(g.from))} ⇄ ${esc(portName(g.to))}${g.vessel ? '（' + esc(g.vessel) + '）' : ''}</h3>
      <div class="table-wrap"><table class="fare-table">
        <tr><th>区分</th><th>大人片道</th><th>小人片道</th><th>大人往復</th><th>小人往復</th>${isKyushu ? '' : '<th>適用期間</th>'}<th>備考</th></tr>
        ${rowFor('general', '一般')}${rowFor('resident', '島民割引')}
      </table></div>
    </div>`;
  }).join('');
  if (!sorted.length) html = '<div class="empty-box">この事業者の運賃データはありません。</div>';
  // 九州商船は燃料油価格変動調整金を別表表示（選択中の月のみ）
  if (isKyushu && DB.surcharges.length) {
    const sur = DB.surcharges.filter((s) => s.year_month === selMonth);
    if (sur.length) {
      html += `<div class="fare-group"><h3>燃料油価格変動調整金（九州商船・${esc(selMonth.replace('-', '年'))}月分）</h3>
      <div class="table-wrap"><table class="fare-table">
      <tr><th>航路</th><th>船種</th><th>区間</th><th>ゾーン</th><th>大人</th><th>小人</th><th>備考</th></tr>
      ${sur.map((s) => `<tr><td>${esc(s.route_name)}</td><td>${esc(s.vessel_type)}</td><td>${esc(s.segment)}</td><td>${esc(s.zone)}</td><td>${yen(s.adult)}</td><td>${yen(s.child)}</td><td class="fare-note-cell">${esc(s.note || '')}</td></tr>`).join('')}
      </table></div>
      <p class="small">※ 上の運賃表の金額は、この調整金を含んだ合計です。</p></div>`;
    }
  }
  $('#fare-results').innerHTML = html;
}

/* ============ 地図・港タブ ============ */
let mapObj = null, markerByPort = {};
function portRoutes(pid) {
  const names = new Map();
  for (const t of DB.trips) {
    if (t.stops.some((s) => s.port_id === pid)) {
      const r = routeById[t.route_id];
      if (r) names.set(r.route_id, r.name + '（' + (operatorById[r.operator_id] || {}).name + '）');
    }
  }
  return [...names.values()];
}
function showPortDetail(pid) {
  const p = portById[pid];
  if (!p) return;
  const routes = portRoutes(pid);
  const aliases = (p.aliases || []).flatMap((a) => String(a).split(';')).map((s) => s.trim()).filter(Boolean);
  $('#port-detail').innerHTML = `
    <div class="port-card">
      <h3>${esc(portName(pid))}${p.name_kana ? '（' + esc(p.name_kana) + '）' : ''}</h3>
      ${aliases.length ? '<p class="small">別名：' + esc(aliases.join('、')) + '</p>' : ''}
      ${p.address ? '<p>📍 ' + esc(p.address) + '</p>' : ''}
      ${p.terminal_phone ? '<p>📞 <a href="tel:' + esc(p.terminal_phone) + '">' + esc(p.terminal_phone) + '</a></p>' : ''}
      ${routes.length ? '<p>発着する航路：' + esc(routes.join('、')) + '</p>' : ''}
      ${p.note ? '<p class="small">' + esc(p.note) + '</p>' : ''}
      ${p.source_url ? '<div class="detail-links"><a href="' + esc(p.source_url) + '" target="_blank" rel="noopener">公式リンク</a></div>' : ''}
    </div>`;
  $('#port-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function initMap() {
  let listHtml = '';
  for (const g of portGroups()) {
    listHtml += `<h3 class="port-group-title">${esc(groupLabel(g.muni))}</h3>`;
    listHtml += g.ports.map((p) => {
      const routes = portRoutes(p.port_id);
      return `<button type="button" class="port-list-item" data-port="${esc(p.port_id)}">${esc(portName(p.port_id))}<br><span class="sub">${esc(routes.join('、') || '航路情報なし')}</span></button>`;
    }).join('');
  }
  $('#port-list').innerHTML = listHtml;
  $('#port-list').querySelectorAll('.port-list-item').forEach((el) => {
    el.addEventListener('click', () => {
      const pid = el.dataset.port;
      showPortDetail(pid);
      const p = portById[pid];
      if (mapObj && p && p.lat != null && markerByPort[pid]) {
        mapObj.setView([p.lat, p.lon], 12);
        markerByPort[pid].openPopup();
      }
    });
  });
  if (window.L && !mapObj) {
    mapObj = L.map('map').setView([32.92, 129.08], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors', maxZoom: 18
    }).addTo(mapObj);
    for (const p of DB.ports) {
      if (p.lat == null || p.lon == null) continue;
      const m = L.marker([p.lat, p.lon]).addTo(mapObj).bindPopup('<strong>' + esc(portName(p.port_id)) + '</strong>');
      m.on('click', () => showPortDetail(p.port_id));
      markerByPort[p.port_id] = m;
    }
  } else if (mapObj) {
    setTimeout(() => mapObj.invalidateSize(), 50);
  }
}

/* ============ 運航状況・リンクタブ ============ */
// 崎戸商船は公式サイトがないため、公開情報の出典リンクをここで定義する
const SAKITO_SOURCES = [
  { label: '西海市（航路・時刻表）', url: 'https://www.city.saikai.nagasaki.jp/soshiki/koutsu/1/1_1/2/1675.html', note: '' },
  { label: '佐世保旅客船協会（崎戸商船）', url: 'https://www.saryokyo.com/member/member-02.html', note: '' },
  { label: '九州のりものinfo（崎戸商船）', url: 'http://www.norimono-info.com/sakitosyousen/', note: '現在メンテナンス中' },
];
function sakitoSourceLinks() {
  return SAKITO_SOURCES.map((s) => '<a href="' + s.url + '" target="_blank" rel="noopener">' + esc(s.label) + '</a>' + (s.note ? '（' + esc(s.note) + '）' : '')).join(' ');
}
function renderStatus() {
  $('#operator-cards').innerHTML = DB.operators.map((op) => `
    <div class="op-card">
      <h3>${esc(op.name)}</h3>
      ${op.note ? '<p>' + esc(op.note) + '</p>' : ''}
      ${op.phone ? '<p>📞 <a href="tel:' + esc(op.phone) + '">' + esc(op.phone) + '</a></p>' : ''}
      <div class="detail-links">
        ${op.official_url ? '<a href="' + esc(op.official_url) + '" target="_blank" rel="noopener">公式サイト</a>' : ''}
        ${op.status_url ? '<a href="' + esc(op.status_url) + '" target="_blank" rel="noopener">運航状況</a>' : ''}
        ${op.reservation_url ? '<a href="' + esc(op.reservation_url) + '" target="_blank" rel="noopener">予約</a>' : ''}
        ${op.operator_id === 'sakito' ? sakitoSourceLinks() : ''}
      </div>
    </div>`).join('');
  const suspended = DB.routes.filter((r) => r.suspended);
  $('#suspended-routes').innerHTML = suspended.length ? suspended.map((r) => `
    <div class="op-card">
      <h3>${esc(r.name)}<span class="badge-suspended">運休中</span></h3>
      <p>${esc((operatorById[r.operator_id] || {}).name || '')} ／ ${esc(r.vessel_type || '')}</p>
      ${r.note ? '<p>' + esc(r.note) + '</p>' : ''}
      ${(operatorById[r.operator_id] || {}).official_url ? '<div class="detail-links"><a href="' + esc(operatorById[r.operator_id].official_url) + '" target="_blank" rel="noopener">公式サイトで確認</a></div>' : ''}
    </div>`).join('') : '<p>現在、運休中の航路はありません。</p>';
}

/* ============ このサイトについて ============ */
function renderAbout() {
  $('#about-sources').innerHTML = DB.operators.map((op) => {
    if (op.operator_id === 'sakito') {
      return '<li>' + esc(op.name) + '（公式サイトなし）：' + SAKITO_SOURCES.map((s) => '<a href="' + s.url + '" target="_blank" rel="noopener">' + esc(s.label) + '</a>' + (s.note ? '（' + esc(s.note) + '）' : '')).join('、') + '</li>';
    }
    return '<li>' + esc(op.name) + (op.official_url ? '：<a href="' + esc(op.official_url) + '" target="_blank" rel="noopener">' + esc(op.official_url) + '</a>' : '（公式サイトなし。自治体・協会の公開情報を参照）') + '</li>';
  }).join('');
  const seen = new Map();
  for (const t of DB.trips) {
    const p = t.pattern || {};
    let period = '';
    if (p.recurs && p.recurs.from_md && p.recurs.to_md) {
      // 繰り返しダイヤは、収録時の単年の適用期間ではなく毎年の適用期間を表示する
      const md = (s) => { const [mm, dd] = s.split('-'); return Number(mm) + '月' + Number(dd) + '日'; };
      period = '毎年 ' + md(p.recurs.from_md) + '〜' + md(p.recurs.to_md);
    }
    else if (p.valid_from || p.valid_to) period = (p.valid_from || '') + '〜' + (p.valid_to || '');
    else period = '期間指定なし';
    const opName = (operatorById[t.operator_id] || {}).name || '';
    const routeName = (routeById[t.route_id] || {}).name || '';
    const key = opName + '|' + routeName + '|' + (p.name || '') + '|' + period;
    if (!seen.has(key)) seen.set(key, { op: opName, route: routeName, name: p.name || '通常', kind: p.kind || '', period });
  }
  $('#about-validity').innerHTML = '<div class="table-wrap"><table class="fare-table"><tr><th>事業者</th><th>航路</th><th>ダイヤ名</th><th>種別</th><th>期間</th></tr>' +
    [...seen.values()].map((v) => `<tr><td>${esc(v.op)}</td><td>${esc(v.route)}</td><td>${esc(v.name)}</td><td>${esc(v.kind)}</td><td>${esc(v.period)}</td></tr>`).join('') +
    '</table></div>';
  if (DB.meta) $('#data-meta').textContent = 'データ生成日：' + (DB.meta.generated_at || '-') + '（' + (DB.meta.title || '') + '）';
}

/* ============ オフライン表示バナー ============ */
// オフラインのときだけ、保存済みデータであることとデータ生成日を知らせる。
function updateOfflineBanner() {
  const b = $('#offline-banner');
  if (!b) return;
  const off = !navigator.onLine;
  b.hidden = !off;
  if (off && DB && DB.meta) $('#offline-data-date').textContent = DB.meta.generated_at || '-';
}
// 'online' イベントだけでは復帰を確定できないため、実在しないパスへの取得で
// 通信の回復を実際に確認する（オンラインなら応答が返り、オフラインなら失敗する。
// Service Worker がキャッシュを返す対象ではないため判別できる）。
// 復帰が確認できたら、データが新しいものに差し替わった場合だけ再描画してからバナーを消す。
async function verifyOnlineAndRefresh() {
  try {
    await fetch('__online_check__', { cache: 'no-store' });
  } catch (e) {
    return; // まだ通信できていないのでバナーを残す
  }
  try {
    const res = await fetch('data.json', { cache: 'no-store' });
    if (res.ok) {
      const fresh = await res.json();
      if (fresh && fresh.meta && DB && fresh.meta.generated_at !== DB.meta.generated_at) {
        DB = fresh;
        for (const p of DB.ports) portById[p.port_id] = p;
        for (const o of DB.operators) operatorById[o.operator_id] = o;
        for (const r of DB.routes) routeById[r.route_id] = r;
        buildReachability();
        renderNotices();
        renderChips();
        updateFavButton();
        renderFares();
        renderStatus();
        renderAbout();
        autoSearch();
      }
    }
  } catch (e) { /* データ再取得に失敗した場合は現在の表示を維持する */ }
  updateOfflineBanner();
}

/* ============ タブ切替・初期化 ============ */
let mapInited = false;
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
  if (name === 'map') {
    if (!mapInited) { initMap(); mapInited = true; }
    else if (mapObj) setTimeout(() => mapObj.invalidateSize(), 50);
  }
  window.scrollTo({ top: 0 });
}

async function init() {
  try {
    const res = await fetch('data.json');
    DB = await res.json();
  } catch (e) {
    document.querySelector('main').innerHTML = '<div class="empty-box"><span class="big">データを読み込めませんでした</span>通信状態を確認して、再読み込みしてください。</div>';
    return;
  }
  for (const p of DB.ports) portById[p.port_id] = p;
  for (const o of DB.operators) operatorById[o.operator_id] = o;
  for (const r of DB.routes) routeById[r.route_id] = r;
  buildReachability();

  $('#from-port').innerHTML = portOptionsHtml(null);
  $('#from-port').value = 'arikawa';
  refreshToOptions();
  if (!$('#to-port').value) $('#to-port').value = 'sasebo';
  $('#date-input').value = todayStr();

  $('#fare-operator').innerHTML = DB.operators.map((o) => `<option value="${esc(o.operator_id)}">${esc(o.name)}</option>`).join('');

  renderNotices();
  renderChips();
  updateFavButton();
  renderFares();
  renderStatus();
  renderAbout();
  autoSearch();
  updateOfflineBanner();
  window.addEventListener('offline', updateOfflineBanner);
  window.addEventListener('online', verifyOnlineAndRefresh);

  // イベント（港・日付が変われば自動で検索する）
  document.querySelectorAll('.tab-btn').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  $('#search-form').addEventListener('submit', (e) => { e.preventDefault(); autoSearch(); });
  $('#swap-btn').addEventListener('click', () => {
    const f = $('#from-port').value;
    const t = $('#to-port').value;
    $('#from-port').value = t;
    refreshToOptions(f); // 入れ替え後の到着港を優先しつつ絞り込みを再適用
    updateFavButton();
    autoSearch();
  });
  $('#from-port').addEventListener('change', () => {
    refreshToOptions();
    updateFavButton();
    autoSearch();
  });
  $('#to-port').addEventListener('change', () => {
    updateFavButton();
    autoSearch();
  });
  $('#fav-toggle').addEventListener('click', () => {
    const from = $('#from-port').value, to = $('#to-port').value;
    if (!from || !to) return;
    toggleFavorite(from, to);
    updateFavButton();
    renderChips();
  });
  const shiftDate = (n) => {
    const cur = $('#date-input').value || todayStr();
    $('#date-input').value = fmtDate(addDays(parseDate(cur), n));
    autoSearch();
  };
  $('#prev-day').addEventListener('click', () => shiftDate(-1));
  $('#next-day').addEventListener('click', () => shiftDate(1));
  $('#today-btn').addEventListener('click', () => { $('#date-input').value = todayStr(); autoSearch(); });
  $('#date-input').addEventListener('change', autoSearch);
  $('#fare-operator').addEventListener('change', renderFares);
  $('#fare-month').addEventListener('change', renderFares);
  $('#clear-cache').addEventListener('click', async () => {
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
    location.reload();
  });
  // Android Chrome のインストールプロンプトが出せる場合だけボタンを表示する
  let deferredInstallPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    const btn = $('#install-app');
    if (btn) btn.hidden = false;
  });
  const installBtn = $('#install-app');
  if (installBtn) installBtn.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installBtn.hidden = true;
  });

  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    // 新しい SW に切り替わったら一度だけ自動リロードして最新の画面にする。
    // 初回登録時（controller がまだ無い）はリロードしない。多重リロード防止のガード付き
    const hadController = !!navigator.serviceWorker.controller;
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!hadController || refreshing) return;
      refreshing = true;
      location.reload();
    });
    navigator.serviceWorker.register('sw.js').catch(() => { /* 登録失敗時も通常動作 */ });
  }
}

document.addEventListener('DOMContentLoaded', init);
