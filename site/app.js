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
// お気に入り・履歴チップから区間をセットして検索する
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
function findFare(operatorId, fromId, toId, category, vesselType) {
  const cands = DB.fares.filter((f) =>
    f.operator_id === operatorId && f.from_port_id === fromId &&
    f.to_port_id === toId && f.category === category);
  if (!cands.length) return null;
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

/* ============ お気に入り・履歴（localStorage） ============ */
const LS_FAV = 'kamigoto.favorites';
const LS_HIST = 'kamigoto.history';
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
function pushHistory(from, to) {
  let hist = lsGet(LS_HIST, []).filter((h) => !(h.from === from && h.to === to));
  hist.unshift({ from, to });
  lsSet(LS_HIST, hist.slice(0, 8));
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
  const hist = lsGet(LS_HIST, []).filter(valid);
  $('#fav-block').hidden = favs.length === 0;
  $('#hist-block').hidden = hist.length === 0;
  const chip = (h) => `<button type="button" class="chip" data-from="${esc(h.from)}" data-to="${esc(h.to)}">${esc(portName(h.from))} → ${esc(portName(h.to))}</button>`;
  $('#fav-chips').innerHTML = favs.map(chip).join('');
  $('#hist-chips').innerHTML = hist.map(chip).join('');
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

function tripCard(c, idx) {
  const { trip, fromStop, toStop } = c;
  const op = operatorById[trip.operator_id] || {};
  const route = routeById[trip.route_id] || {};
  const depMin = timeToMin(fromStop.dep) + (fromStop.dep_off || 0) * 1440;
  const arrMin = timeToMin(toStop.arr) + (toStop.arr_off || 0) * 1440;
  const relArr = (toStop.arr_off || 0) - (fromStop.dep_off || 0);
  const vesselType = trip.vessel_type || route.vessel_type;
  const fare = findFare(trip.operator_id, fromStop.port_id, toStop.port_id, 'general', vesselType);
  const resFare = findFare(trip.operator_id, fromStop.port_id, toStop.port_id, 'resident', vesselType);
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
  const vesselLabel = (trip.vessel_type || route.vessel_type || '') + (trip.vessel_name && trip.vessel_name !== trip.vessel_type ? '（' + trip.vessel_name + '）' : '');
  return `
  <article class="trip-card" data-idx="${idx}" tabindex="0" aria-label="便の詳細を開く">
    <div class="trip-top">
      <span class="trip-op">${esc(op.name || '')}</span>
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

function tripDetailHtml(c) {
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
    const f = findFare(trip.operator_id, fromStop.port_id, c.toStop.port_id, cat, trip.vessel_type || route.vessel_type);
    if (f) rows.push(`<tr><td>${label}${fareMonthNote(f) ? '<br><span class="fare-note">' + esc(fareMonthNote(f)) + '</span>' : ''}</td><td>${yen(f.adult_oneway)}</td><td>${yen(f.child_oneway)}</td><td>${yen(f.adult_roundtrip)}</td><td>${yen(f.child_roundtrip)}</td></tr>`);
  }
  const fareHtml = rows.length ? `
    <table class="fare-mini">
      <tr><th>区分</th><th>大人片道</th><th>小人片道</th><th>大人往復</th><th>小人往復</th></tr>
      ${rows.join('')}
    </table>` : '<p class="detail-note">この区間の運賃データはありません。公式情報でご確認ください。</p>';
  const notes = [];
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
  pushHistory(from, to);
  renderChips();
  const { results, suspendedNotes, anyCandidate } = searchTrips(from, to, dateStr);
  const head = `<p class="result-head">${esc(portName(from))} → ${esc(portName(to))} ／ ${esc(dateLabel(dateStr))} の便</p>`;
  if (results.length) {
    box.innerHTML = head + results.map((c, i) => tripCard(c, i)).join('');
    box.querySelectorAll('.trip-card').forEach((card) => {
      const toggle = () => {
        const detail = card.querySelector('.trip-detail');
        if (detail.hidden) {
          detail.innerHTML = tripDetailHtml(results[Number(card.dataset.idx)]);
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
  const list = DB.fares.filter((f) => f.operator_id === opId);
  const portOrder = (pid) => DB.ports.findIndex((p) => p.port_id === pid);
  const groups = new Map();
  for (const f of list) {
    const key = f.from_port_id + '|' + f.to_port_id + '|' + (f.vessel_type || '');
    if (!groups.has(key)) groups.set(key, { from: f.from_port_id, to: f.to_port_id, vessel: f.vessel_type || '', rows: {} });
    groups.get(key).rows[f.category] = f;
  }
  const sorted = [...groups.values()].sort((a, b) =>
    portOrder(a.from) - portOrder(b.from) || portOrder(a.to) - portOrder(b.to) || a.vessel.localeCompare(b.vessel, 'ja'));
  let html = sorted.map((g) => {
    const rowFor = (cat, label) => {
      const f = g.rows[cat];
      if (!f) return '';
      const period = (f.valid_from || '') + (f.valid_to ? '〜' + f.valid_to : '');
      return `<tr class="${cat === 'resident' ? 'cat-resident' : ''}">
        <td>${label}</td><td>${yen(f.adult_oneway)}</td><td>${yen(f.child_oneway)}</td>
        <td>${yen(f.adult_roundtrip)}</td><td>${yen(f.child_roundtrip)}</td>
        <td>${esc(period)}</td><td class="fare-note-cell">${esc(f.note || '')}</td></tr>`;
    };
    return `<div class="fare-group">
      <h3>${esc(portName(g.from))} → ${esc(portName(g.to))}${g.vessel ? '（' + esc(g.vessel) + '）' : ''}</h3>
      <div class="table-wrap"><table class="fare-table">
        <tr><th>区分</th><th>大人片道</th><th>小人片道</th><th>大人往復</th><th>小人往復</th><th>適用期間</th><th>備考</th></tr>
        ${rowFor('general', '一般')}${rowFor('resident', '島民割引')}
      </table></div>
    </div>`;
  }).join('');
  if (!html) html = '<div class="empty-box">この事業者の運賃データはありません。</div>';
  // 九州商船は燃料油価格変動調整金を別表表示
  if (opId === 'kyushu' && DB.surcharges.length) {
    html += `<div class="fare-group"><h3>燃料油価格変動調整金（九州商船）</h3>
      <div class="table-wrap"><table class="fare-table">
      <tr><th>航路</th><th>船種</th><th>区間</th><th>対象月</th><th>ゾーン</th><th>大人</th><th>小人</th><th>備考</th></tr>
      ${DB.surcharges.map((s) => `<tr><td>${esc(s.route_name)}</td><td>${esc(s.vessel_type)}</td><td>${esc(s.segment)}</td><td>${esc(s.year_month)}</td><td>${esc(s.zone)}</td><td>${yen(s.adult)}</td><td>${yen(s.child)}</td><td class="fare-note-cell">${esc(s.note || '')}</td></tr>`).join('')}
      </table></div>
      <p class="small">※ 運賃表の金額は、収集時点の調整金込み表示です。月により調整金が変わります。</p></div>`;
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
  $('#about-sources').innerHTML = DB.operators.map((op) =>
    '<li>' + esc(op.name) + (op.official_url ? '：<a href="' + esc(op.official_url) + '" target="_blank" rel="noopener">' + esc(op.official_url) + '</a>' : '（公式サイトなし。自治体・協会の公開情報を参照）') + '</li>'
  ).join('');
  const seen = new Map();
  for (const t of DB.trips) {
    const p = t.pattern || {};
    let period = '';
    if (p.valid_from || p.valid_to) period = (p.valid_from || '') + '〜' + (p.valid_to || '');
    else if (p.recurs) period = '毎年 ' + p.recurs.from_md + '〜' + p.recurs.to_md;
    else period = '期間指定なし';
    const key = (p.name || '') + '|' + period;
    if (!seen.has(key)) seen.set(key, { name: p.name || '通常', kind: p.kind || '', period });
  }
  $('#about-validity').innerHTML = '<div class="table-wrap"><table class="fare-table"><tr><th>ダイヤ名</th><th>種別</th><th>期間</th></tr>' +
    [...seen.values()].map((v) => `<tr><td>${esc(v.name)}</td><td>${esc(v.kind)}</td><td>${esc(v.period)}</td></tr>`).join('') +
    '</table></div>';
  if (DB.meta) $('#data-meta').textContent = 'データ生成日：' + (DB.meta.generated_at || '-') + '（' + (DB.meta.title || '') + '）';
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
  $('#clear-cache').addEventListener('click', async () => {
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
    location.reload();
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
