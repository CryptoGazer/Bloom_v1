'use strict';
/* Lit-route demo: click A, click B, compare the fastest walk with the better-lit one.
   Everything runs in the browser on data/out/segments_draft.geojson. See README.md in this folder. */

// ---------- settings (spec section 12; tune them here) ----------
const DATA_URL = '../../data/out/segments_draft.geojson';
const WALK_MPS = 1.35;                       // walking speed, ~4.9 km/h
const FACTOR_LIT = { lit_confirmed: 1.0, lit_likely: 1.2, unknown: 1.6, dark_reported: 3.0 };
const FACTOR_FAST = { lit_confirmed: 1, lit_likely: 1, unknown: 1, dark_reported: 1 };
const HIDE_IF_EXTRA_MIN = 5;                 // product would hide the lit route if it is longer by more than this
const HIDE_IF_EXTRA_SHARE = 0.30;            // ...or by more than this share
const WARN_DARK_RUN_M = 100;                 // warn: continuous "reported dark" stretch longer than this
const WARN_DARK_UNKNOWN_SHARE = 0.20;        // warn: "dark" + "no data" share above this
const SNAP_MAX_M = 150;                      // a click farther than this from any path is outside the demo area

const ST = {
  lit_confirmed: { c: '#009E73', d: null, t: 'освещено' },
  lit_likely: { c: '#E69F00', d: '9 6', t: 'вероятно освещено' },
  unknown: { c: '#7F7F7F', d: '1 7', t: 'нет данных' },
  dark_reported: { c: '#D55E00', d: '13 5 2 5', t: 'сообщали, что темно' },
};
const ORDER = ['lit_confirmed', 'lit_likely', 'unknown', 'dark_reported'];

// Local planar projection: metres per degree of lon / lat at 45.748 N, same constants as backend/routing.py.
const KX = 77811, KY = 111147;
const toXY = (lon, lat) => [lon * KX, lat * KY];
const toLL = (x, y) => [y / KY, x / KX]; // [lat, lon]

// ---------- graph ----------
function buildGraph(fc) {
  const key2id = new Map();
  let nodeCount = 0;
  const nodeOf = c => {
    const k = c[0] + ',' + c[1];
    let id = key2id.get(k);
    if (id === undefined) { id = nodeCount++; key2id.set(k, id); }
    return id;
  };
  const segs = [];
  for (const f of fc.features) {
    const c = f.geometry && f.geometry.coordinates;
    if (!c || c.length < 2) continue;
    const xy = c.map(p => toXY(p[0], p[1]));
    const cum = [0];
    for (let i = 1; i < xy.length; i++) cum.push(cum[i - 1] + Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]));
    const len = cum[cum.length - 1];
    const a = nodeOf(c[0]), b = nodeOf(c[c.length - 1]);
    if (len <= 0 || a === b) continue; // self-loops never shorten a route
    const p = f.properties || {};
    segs.push({ idx: segs.length, id: p.id, name: p.name || null, kind: p.kind, status: ST[p.status] ? p.status : 'unknown',
      ll: c.map(q => [q[1], q[0]]), xy, cum, len, a, b });
  }
  const adj = Array.from({ length: nodeCount }, () => []);
  for (const s of segs) { adj[s.a].push(s); adj[s.b].push(s); }

  // Keep routing on the largest connected part, so a click never lands on an island with no way out.
  const comp = new Int32Array(nodeCount).fill(-1);
  let best = -1, bestSize = 0;
  for (let n = 0, cid = 0; n < nodeCount; n++, cid++) {
    if (comp[n] !== -1) { cid--; continue; }
    let size = 0;
    const stack = [n];
    comp[n] = cid;
    while (stack.length) {
      const u = stack.pop();
      size++;
      for (const s of adj[u]) {
        const v = s.a === u ? s.b : s.a;
        if (comp[v] === -1) { comp[v] = cid; stack.push(v); }
      }
    }
    if (size > bestSize) { bestSize = size; best = cid; }
  }
  for (const s of segs) s.main = comp[s.a] === best;
  return { segs, adj, nodeCount };
}

// Nearest point on the main network: {seg, t (metres from seg start), d (metres from click), ll}.
function snap(G, lat, lon) {
  const [px, py] = toXY(lon, lat);
  let best = null;
  for (const s of G.segs) {
    if (!s.main) continue;
    for (let i = 1; i < s.xy.length; i++) {
      const [x1, y1] = s.xy[i - 1], [x2, y2] = s.xy[i];
      const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
      const u = l2 ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2)) : 0;
      const qx = x1 + u * dx, qy = y1 + u * dy, d = Math.hypot(px - qx, py - qy);
      if (!best || d < best.d) best = { seg: s, t: s.cum[i - 1] + u * (s.cum[i] - s.cum[i - 1]), d, ll: toLL(qx, qy) };
    }
  }
  return best;
}

function pointAt(s, t) {
  let i = 1;
  while (i < s.cum.length - 1 && s.cum[i] < t) i++;
  const c0 = s.cum[i - 1], c1 = s.cum[i], u = c1 > c0 ? Math.max(0, Math.min(1, (t - c0) / (c1 - c0))) : 0;
  return toLL(s.xy[i - 1][0] + u * (s.xy[i][0] - s.xy[i - 1][0]), s.xy[i - 1][1] + u * (s.xy[i][1] - s.xy[i - 1][1]));
}

// Part of a segment from distance t0 to t1 (t1 < t0 walks it backwards).
function piece(s, t0, t1) {
  const lo = Math.min(t0, t1), hi = Math.max(t0, t1);
  const pts = [pointAt(s, lo)];
  for (let i = 1; i < s.cum.length - 1; i++) if (s.cum[i] > lo && s.cum[i] < hi) pts.push(s.ll[i]);
  pts.push(pointAt(s, hi));
  return { seg: s, ll: t0 <= t1 ? pts : pts.reverse(), len: hi - lo, status: s.status };
}

class Heap {
  constructor() { this.k = []; this.v = []; }
  get size() { return this.k.length; }
  push(key, val) {
    const K = this.k, V = this.v;
    let i = K.length;
    K.push(key); V.push(val);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (K[p] <= key) break;
      K[i] = K[p]; V[i] = V[p]; i = p;
    }
    K[i] = key; V[i] = val;
  }
  pop() {
    const K = this.k, V = this.v, rk = K[0], rv = V[0], lk = K.pop(), lv = V.pop();
    if (K.length) {
      let i = 0;
      const n = K.length;
      for (;;) {
        let c = 2 * i + 1;
        if (c >= n) break;
        if (c + 1 < n && K[c + 1] < K[c]) c++;
        if (K[c] >= lk) break;
        K[i] = K[c]; V[i] = V[c]; i = c;
      }
      K[i] = lk; V[i] = lv;
    }
    return [rk, rv];
  }
}

// Dijkstra from snapped point A to snapped point B; cost = length x factor[status].
function route(G, A, B, factor) {
  const f = s => factor[s.status] ?? factor.unknown;
  const dist = new Float64Array(G.nodeCount).fill(Infinity);
  const prev = new Array(G.nodeCount).fill(null);
  const heap = new Heap();
  const seed = (node, cost) => { if (cost < dist[node]) { dist[node] = cost; heap.push(cost, node); } };
  seed(A.seg.a, A.t * f(A.seg));
  seed(A.seg.b, (A.seg.len - A.t) * f(A.seg));
  while (heap.size) {
    const [d, u] = heap.pop();
    if (d > dist[u]) continue;
    for (const s of G.adj[u]) {
      const v = s.a === u ? s.b : s.a, nd = d + s.len * f(s);
      if (nd < dist[v]) { dist[v] = nd; prev[v] = { node: u, seg: s }; heap.push(nd, v); }
    }
  }
  const fb = f(B.seg);
  let end = { cost: dist[B.seg.a] + B.t * fb, node: B.seg.a, t: 0 };
  const viaB = dist[B.seg.b] + (B.seg.len - B.t) * fb;
  if (viaB < end.cost) end = { cost: viaB, node: B.seg.b, t: B.seg.len };
  if (A.seg === B.seg) {
    const direct = Math.abs(A.t - B.t) * fb;
    if (direct <= end.cost) return summarize([piece(A.seg, A.t, B.t)]);
  }
  if (!isFinite(end.cost)) return null;
  const chain = [];
  let u = end.node;
  while (prev[u]) { chain.push(prev[u]); u = prev[u].node; }
  chain.reverse();
  const pieces = [piece(A.seg, A.t, u === A.seg.a ? 0 : A.seg.len)];
  for (const step of chain) {
    const fwd = step.node === step.seg.a;
    pieces.push(piece(step.seg, fwd ? 0 : step.seg.len, fwd ? step.seg.len : 0));
  }
  pieces.push(piece(B.seg, end.t, B.t));
  return summarize(pieces.filter(p => p.len > 0.5));
}

function summarize(pieces) {
  const by = { lit_confirmed: 0, lit_likely: 0, unknown: 0, dark_reported: 0 };
  let len = 0, run = 0, maxDarkRun = 0;
  for (const p of pieces) {
    by[p.status] += p.len;
    len += p.len;
    run = p.status === 'dark_reported' ? run + p.len : 0;
    maxDarkRun = Math.max(maxDarkRun, run);
  }
  const darkUnknownShare = len ? (by.dark_reported + by.unknown) / len : 0;
  const names = [];
  for (const p of pieces) if (p.seg.name && names[names.length - 1] !== p.seg.name) names.push(p.seg.name);
  return { pieces, by, len, minutes: len / WALK_MPS / 60, maxDarkRun, darkUnknownShare, names,
    warn: maxDarkRun > WARN_DARK_RUN_M || darkUnknownShare > WARN_DARK_UNKNOWN_SHARE,
    key: pieces.map(p => p.seg.idx).join(',') };
}

// Spec section 12: is the lit route worth showing next to the fastest one?
function verdict(fast, lit) {
  if (fast.key === lit.key) return { kind: 'same' };
  const extraMin = lit.minutes - fast.minutes, share = fast.minutes ? extraMin / fast.minutes : 0;
  return { kind: extraMin > HIDE_IF_EXTRA_MIN || share > HIDE_IF_EXTRA_SHARE ? 'too_long' : 'show', extraMin, share };
}

if (typeof module !== 'undefined') module.exports = { buildGraph, snap, route, verdict, FACTOR_LIT, FACTOR_FAST };

// ---------- page ----------
if (typeof window !== 'undefined' && window.L) {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtM = m => m >= 1000 ? (m / 1000).toFixed(2).replace('.', ',') + ' км' : Math.round(m) + ' м';
  const fmtMin = m => Math.max(1, Math.round(m)) + ' мин';
  const pct = x => Math.round(100 * x) + '%';

  const map = L.map('map', { preferCanvas: true, renderer: L.canvas({ tolerance: 5 }) });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'gray-tiles',
    attribution: '&copy; OpenStreetMap contributors · Mapillary · Primăria Timișoara, Sesizări' }).addTo(map);
  const netLayer = L.layerGroup().addTo(map);
  const routeLayer = L.featureGroup().addTo(map);
  map.on('overlayadd', () => routeLayer.bringToFront()); // the route stays above any layer switched on later
  let G = null, A = null, B = null, routes = null, selected = 'lit';
  const markers = { A: null, B: null };

  const say = html => { $('hint').innerHTML = html; };

  fetch(DATA_URL)
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(init)
    .catch(err => say(`Не удалось загрузить <code>${esc(DATA_URL)}</code> (${esc(err.message)}).<br>` +
      'Выполните <code>python3 demo/route/extract_segments.py</code> и откройте страницу через ' +
      '<code>./scripts/mac/lightmap.sh serve</code>.'));

  function init(fc) {
    G = buildGraph(fc);
    const m = fc.meta || {};
    if (m.bbox_swne) {
      const [s, w, n, e] = m.bbox_swne;
      L.rectangle([[s, w], [n, e]], { color: '#333', weight: 1, dashArray: '4 4', fill: false, interactive: false }).addTo(map);
      map.fitBounds([[s, w], [n, e]]);
    } else {
      map.fitBounds(L.latLngBounds(G.segs.flatMap(s => s.ll)));
    }
    drawNetwork();
    if (window.ExtraLayers) { // city-wide layers from demo/layers/, optional
      const ctl = L.control.layers(null, {}, { collapsed: false, position: 'topright' }).addTo(map);
      ExtraLayers.add(map, ctl, '../../data/out/layers/').then(() => routeLayer.bringToFront());
    }
    $('meta').innerHTML = `Данные: ${G.segs.length} отрезков, срез ${esc(m.as_of || '?')}, из <code>${esc(m.source || '?')}</code>. ` +
      `Скорость пешком ${(WALK_MPS * 3.6).toFixed(1).replace('.', ',')} км/ч. Коэффициенты «более освещённого»: ` +
      ORDER.map(k => `${ST[k].t} ×${String(FACTOR_LIT[k]).replace('.', ',')}`).join(', ') + '.';
    map.on('click', e => onClick(e.latlng));
    $('reset').addEventListener('click', reset);
    $('net').addEventListener('change', e => (e.target.checked ? netLayer.addTo(map) : netLayer.remove()));
    if (!readHash()) say('Кликните на карте точку <b>А</b> внутри пунктирной рамки.');
  }

  function drawNetwork() {
    for (const k of ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported']) {
      for (const s of G.segs) {
        if (s.status !== k) continue;
        L.polyline(s.ll, { color: ST[k].c, weight: 2.5, opacity: 0.45, dashArray: ST[k].d, interactive: false }).addTo(netLayer);
      }
    }
  }

  function letterIcon(letter) {
    return L.divIcon({ className: 'pin', html: `<span>${letter}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
  }

  function setPoint(which, latlng) {
    const sn = snap(G, latlng.lat, latlng.lng);
    if (!sn || sn.d > SNAP_MAX_M) {
      say(`Эта точка вне зоны демо: ближайшая дорожка в ${sn ? Math.round(sn.d) : '?'} м. ` +
        'Демо покрывает только университетский район (пунктирная рамка).');
      return false;
    }
    const pt = { ...sn, click: latlng };
    if (which === 'A') A = pt; else B = pt;
    if (!markers[which]) {
      markers[which] = L.marker(latlng, { icon: letterIcon(which), draggable: true, keyboard: true, title: 'Точка ' + which })
        .addTo(map)
        .on('dragend', ev => {
          const old = which === 'A' ? A : B;
          if (setPoint(which, ev.target.getLatLng())) { if (A && B) compute(); else drawRoutes(); }
          else ev.target.setLatLng(old.click);
        });
    } else {
      markers[which].setLatLng(latlng);
    }
    return true;
  }

  function onClick(latlng) {
    if (!G) return;
    if (A && B) reset();
    if (!A) {
      if (setPoint('A', latlng)) { drawRoutes(); say('Теперь кликните точку <b>Б</b>. Маркеры можно перетаскивать.'); }
    } else if (setPoint('B', latlng)) {
      compute();
    }
  }

  function reset() {
    A = B = routes = null;
    for (const k of ['A', 'B']) if (markers[k]) { markers[k].remove(); markers[k] = null; }
    routeLayer.clearLayers();
    $('cards').innerHTML = '';
    history.replaceState(null, '', location.pathname + location.search);
    say('Кликните на карте точку <b>А</b> внутри пунктирной рамки.');
  }

  function compute() {
    const fast = route(G, A, B, FACTOR_FAST), lit = route(G, A, B, FACTOR_LIT);
    if (!fast || !lit) { say('Маршрут не найден.'); return; }
    routes = { fast, lit, verdict: verdict(fast, lit) };
    selected = routes.verdict.kind === 'same' ? 'fast' : 'lit';
    const f = n => n.toFixed(5);
    history.replaceState(null, '', `#a=${f(A.click.lat)},${f(A.click.lng)}&b=${f(B.click.lat)},${f(B.click.lng)}`);
    say('Нажмите на карточку, чтобы показать маршрут; маркеры можно перетаскивать. ' +
      'Ссылку из адресной строки можно отправить — она откроет тот же маршрут.');
    drawRoutes();
    renderCards();
  }

  function drawRoutes() {
    routeLayer.clearLayers();
    for (const p of [A, B]) {
      if (p && p.d > 3) L.polyline([[p.click.lat, p.click.lng], p.ll], { color: '#111', weight: 2, dashArray: '2 5', interactive: false }).addTo(routeLayer);
    }
    if (!routes) return;
    const other = selected === 'lit' ? routes.fast : routes.lit;
    if (routes.verdict.kind !== 'same') {
      const ghost = other.pieces.map(p => p.ll);
      L.polyline(ghost, { color: '#fff', weight: 7, opacity: 0.9 }).addTo(routeLayer);
      L.polyline(ghost, { color: '#2b4fb3', weight: 4, dashArray: '8 6' })
        .on('click', ev => { L.DomEvent.stop(ev); select(selected === 'lit' ? 'fast' : 'lit'); })
        .addTo(routeLayer);
    }
    const cur = routes[selected];
    L.polyline(cur.pieces.map(p => p.ll), { color: '#111', weight: 11, opacity: 0.75, interactive: false }).addTo(routeLayer);
    for (const p of cur.pieces) {
      L.polyline(p.ll, { color: ST[p.status].c, weight: 7, dashArray: ST[p.status].d, lineCap: 'butt', interactive: true })
        .bindTooltip(`${esc(p.seg.name || 'без названия')}: ${ST[p.status].t}, ${fmtM(p.len)}`, { sticky: true })
        .addTo(routeLayer);
    }
  }

  function card(kind, r, title, note) {
    const bar = ORDER.filter(k => r.by[k] > 0)
      .map(k => `<span style="width:${(100 * r.by[k] / r.len).toFixed(2)}%;background:${ST[k].c}" title="${ST[k].t}"></span>`).join('');
    const rows = ORDER.map(k => `<li><span class="sw" style="border-top-color:${ST[k].c};border-top-style:${ST[k].d ? (k === 'unknown' ? 'dotted' : 'dashed') : 'solid'}"></span>` +
      `${ST[k].t}: ${fmtM(r.by[k])} (${pct(r.len ? r.by[k] / r.len : 0)})</li>`).join('');
    const warn = r.warn
      ? `<p class="warn">Внимание: нет данных или сообщали о темноте на ${fmtM(r.by.unknown + r.by.dark_reported)} из ${fmtM(r.len)} (${pct(r.darkUnknownShare)})` +
        (r.maxDarkRun > 0 ? `; самый длинный участок «сообщали, что темно» — ${fmtM(r.maxDarkRun)}` : '') + '.</p>'
      : '';
    const via = r.names.length ? `<p class="via">Через: ${r.names.slice(0, 4).map(esc).join(' → ')}${r.names.length > 4 ? ' → …' : ''}</p>` : '';
    return `<button type="button" class="card${selected === kind ? ' selected' : ''}" data-kind="${kind}" aria-pressed="${selected === kind}">` +
      `<span class="title">${title}</span><span class="main">${fmtMin(r.minutes)} · ${fmtM(r.len)}</span>` +
      `<span class="bar">${bar}</span><ul>${rows}</ul>${warn}${via}${note || ''}</button>`;
  }

  function renderCards() {
    const { fast, lit, verdict: v } = routes;
    const litShare = r => r.len ? r.by.lit_confirmed / r.len : 0;
    let html;
    if (v.kind === 'same') {
      html = card('fast', fast, 'Быстрый — он же самый освещённый');
    } else {
      const extra = `+${Math.max(0, Math.round(v.extraMin * 10) / 10).toString().replace('.', ',')} мин (${pct(v.share)})`;
      const note = v.kind === 'too_long'
        ? `<p class="verdict bad">В продукте этот вариант скрыли бы: дольше на ${extra}, порог ${HIDE_IF_EXTRA_MIN} мин или ${pct(HIDE_IF_EXTRA_SHARE)}.</p>`
        : `<p class="verdict ok">${extra} к быстрому; подтверждённо освещено ${pct(litShare(lit))} пути против ${pct(litShare(fast))}.</p>`;
      html = card('lit', lit, 'Более освещённый', note) + card('fast', fast, 'Быстрый');
    }
    const extraWalk = [A, B].filter(p => p.d > 20).map((p, i) => `${p === A ? 'А' : 'Б'}: ${Math.round(p.d)} м`);
    if (extraWalk.length) html += `<p class="small">От точки до ближайшей дорожки по прямой (не входит в расчёт): ${extraWalk.join(', ')}.</p>`;
    $('cards').innerHTML = html;
    for (const el of document.querySelectorAll('.card')) el.addEventListener('click', () => select(el.dataset.kind));
  }

  function select(kind) {
    if (!routes || !routes[kind]) return;
    selected = kind;
    drawRoutes();
    renderCards();
  }

  function readHash() {
    const m = /a=(-?[\d.]+),(-?[\d.]+)&b=(-?[\d.]+),(-?[\d.]+)/.exec(location.hash);
    if (!m) return false;
    if (setPoint('A', L.latLng(+m[1], +m[2])) && setPoint('B', L.latLng(+m[3], +m[4]))) { compute(); return true; }
    return false;
  }
}
