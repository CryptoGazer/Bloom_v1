'use strict';
/* Night-route page for the covered area (the university district and the centre). All data comes from the
   backend (backend/app.py) on the same origin: /api/summary, /api/segments?bbox=, /api/segments/{id}, /api/route.
   Texts are in web/i18n.js (t(), LANG). See web/README.md. */

const LAYERS_BASE = '/data/out/layers/';
const SEG_MIN_ZOOM = 13;          // closer than this: street segments; farther: the outline of the area
const SEG_LIMIT = 8000;

const ST = {
  lit_confirmed: { c: '#009E73', d: null, css: 'solid' },
  lit_likely: { c: '#E69F00', d: '9 6', css: 'dashed' },
  unknown: { c: '#7F7F7F', d: '1 7', css: 'dotted' },
  dark_reported: { c: '#D55E00', d: '13 5 2 5', css: 'dashed' },
};
const ORDER = ['lit_confirmed', 'lit_likely', 'unknown', 'dark_reported'];
const DRAW_ORDER = ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported'];
const LETTER = t('letters');

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const dec = x => String(x).replace('.', t('decimal'));
const fmtM = m => m >= 1000 ? dec((m / 1000).toFixed(2)) + ' ' + t('km') : Math.round(m) + ' ' + t('m');
const fmtMin = m => Math.max(1, Math.round(m)) + ' ' + t('min');
const pct = x => Math.round(100 * x) + '%';
const say = html => { $('hint').innerHTML = html; };
const getJSON = url => fetch(url).then(async r => {
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error((body.detail && body.detail.message) || 'HTTP ' + r.status); e.detail = body.detail; e.status = r.status; throw e; }
  return body;
});
const debounce = (fn, ms) => { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; };

// ---------- static texts ----------
function renderStatic() {
  document.documentElement.lang = t('htmlLang');
  document.title = `${t('title')} — Timișoara`;
  $('map').setAttribute('aria-label', t('mapLabel'));
  $('title').textContent = t('title');
  $('subtitle').textContent = t('subtitle');
  $('modes').setAttribute('aria-label', t('modesLabel'));
  $('modes-caption').textContent = t('modesLabel') + ':';
  $('travel').setAttribute('aria-label', t('travelLabel'));
  $('travel-walk').textContent = t('travelWalk');
  $('travel-bike').textContent = t('travelBike');
  $('travel-transit').textContent = t('travelTransit');
  $('at-label').textContent = t('atLabel');
  $('at-hint').textContent = t('atHint');
  $('label-a').textContent = LETTER.A;
  $('label-b').textContent = LETTER.B;
  for (const [id, key] of [['from', 'from'], ['to', 'to']]) {
    $(id).setAttribute('aria-label', t(key + 'Label'));
    $(id).placeholder = t(key + 'Placeholder');
  }
  $('locate').textContent = t('locate');
  $('swap').setAttribute('aria-label', t('swap'));
  $('swap').title = t('swap');
  $('mode-route').textContent = t('modeRoute');
  $('mode-inspect').textContent = t('modeInspect');
  $('reset').textContent = t('reset');
  $('net-label').textContent = t('showNet');
  $('legend-title').textContent = t('legendTitle');
  $('area-note').textContent = t('areaNote');
  $('legend').innerHTML = ['lit_confirmed', 'lit_likely', 'unknown', 'dark_reported']
    .map(k => `<li><span class="sw" style="border-top-color:${ST[k].c};border-top-style:${ST[k].css}"></span>${esc(t('legend.' + k))}</li>`).join('') +
    `<li><span class="sw" style="border-top-color:#2b4fb3;border-top-style:dashed"></span>${esc(t('legend.second'))}</li>`;
  const langs = $('langs');
  langs.setAttribute('aria-label', t('langLabel'));
  langs.innerHTML = LANGS.map(l => `<button type="button" lang="${l}" data-lang="${l}" aria-pressed="${l === LANG}">${l.toUpperCase()}</button>`).join('');
  for (const b of langs.querySelectorAll('button')) b.addEventListener('click', () => { if (b.dataset.lang !== LANG) switchLang(b.dataset.lang); });
  say(esc(t('loading')));
}
renderStatic();

// ---------- map ----------
const map = L.map('map', { preferCanvas: true, renderer: L.canvas({ tolerance: 6 }) }).setView([45.7500, 21.2270], 14);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'gray-tiles',
  attribution: '&copy; OpenStreetMap contributors · Mapillary · Primăria Timișoara, Sesizări' }).addTo(map);
const areaLayer = L.layerGroup().addTo(map);
const areaLabel = L.layerGroup();
const segLayer = L.layerGroup().addTo(map);
const routeLayer = L.featureGroup().addTo(map);
map.on('overlayadd', () => routeLayer.bringToFront());

let summary = null, A = null, B = null, plan = null, selected = 'better_lit', mode = 'route', segReq = 0;
let travel = 'walk';  // 'walk' | 'bike' | 'transit': how the person goes; "mode" above is what a map click does
const markers = { A: null, B: null };
const labels = { A: '', B: '' };
const box = {
  A: AddressBox($('from'), $('from-list'), r => choose('A', r)),
  B: AddressBox($('to'), $('to-list'), r => choose('B', r)),
};

// ---------- the covered area (outline; the share of known status when zoomed out) ----------
function buildArea(s) {
  if (!s.area_geometry) return null;
  const outline = L.geoJSON(s.area_geometry, { interactive: false, style: { color: '#1d3f8f', weight: 2, dashArray: '6 5', fill: false } }).addTo(areaLayer);
  L.tooltip({ permanent: true, direction: 'center', className: 'zone-name', interactive: false })
    .setLatLng(outline.getBounds().getCenter())
    .setContent(esc(t('areaKnown', { x: dec(s.known_share) })))
    .addTo(areaLabel);
  return outline.getBounds();
}

// ---------- street segments ----------
function drawSegments(features) {
  segLayer.clearLayers();
  const interactive = mode === 'inspect';
  for (const k of DRAW_ORDER) {
    for (const f of features) {
      const p = f.properties;
      if (p.status !== k) continue;
      const ll = f.geometry.coordinates.map(c => [c[1], c[0]]);
      const line = L.polyline(ll, { color: ST[k].c, weight: p.kind === 'street' ? 4 : 2.5, opacity: mode === 'inspect' ? 0.95 : 0.55,
        dashArray: ST[k].d, interactive, bubblingMouseEvents: false });
      if (interactive) line.on('click', e => showEvidence(p.id, e.latlng));
      line.addTo(segLayer);
    }
  }
}

function refresh() {
  if (!summary) return;
  const showNet = $('net').checked;
  if (map.getZoom() < SEG_MIN_ZOOM || !showNet) {
    segReq++;
    segLayer.clearLayers();
    if (showNet) areaLabel.addTo(map); else areaLabel.remove();
    return;
  }
  const b = map.getBounds().pad(0.15), req = ++segReq;
  getJSON(`/api/segments?bbox=${b.getWest().toFixed(5)},${b.getSouth().toFixed(5)},${b.getEast().toFixed(5)},${b.getNorth().toFixed(5)}&limit=${SEG_LIMIT}`)
    .then(d => {
      if (req !== segReq) return; // a newer request is on its way
      if (d.truncated) { segLayer.clearLayers(); areaLabel.addTo(map); return; }
      areaLabel.remove();
      drawSegments(d.features);
      routeLayer.bringToFront();
    })
    .catch(err => console.warn('segments:', err.message));
}

// ---------- "why this colour" ----------
function evidenceLine(e) {
  if (e.s === 'osm') return esc(t('ev.osm_' + e.k) + ((e.ways || []).length ? t('ev.ways', { ways: e.ways.join(', ') }) : ''));
  if (e.s === 'mapillary') {
    const years = e.y1 !== e.y0 ? `${e.y0}–${e.y1}` : String(e.y0);
    return esc(t('ev.lamps', { n: e.n, near: dec(e.near), cov: Math.round(e.cov * 100), years }) + (e.cov < 0.5 ? t('ev.lampsBelow') : ''));
  }
  if (e.s === 'sesizari') {
    return esc(t('ev.complaint', { nr: e.nr + (e.n > 1 ? ` (+${e.n - 1})` : ''), sub: e.sub, state: t('ev.state.' + e.k), created: e.created }) +
      (e.closed ? t('ev.closedAt', { date: e.closed }) : '') + (e.age != null ? t('ev.age', { age: e.age }) : '') + t('ev.distance', { d: e.d }));
  }
  if (['same_name', 'near_lit_street', 'partial_lamps', 'inherited_dark'].includes(e.k)) return esc(t('ev.' + e.k, { ref: e.ref || '' }));
  return esc(JSON.stringify(e));
}

function showEvidence(id, latlng) {
  getJSON('/api/segments/' + encodeURIComponent(id)).then(f => {
    const p = f.properties, s = ST[p.status] || ST.unknown;
    const items = (p.ev || []).length ? p.ev.map(e => `<li>${evidenceLine(e)}</li>`).join('') : `<li>${esc(t('noEvidence'))}</li>`;
    L.popup({ maxWidth: 380 }).setLatLng(latlng).setContent(
      `<b>${esc(p.name || t('noName'))}</b> · ${esc(t('kind.' + p.kind))} · ${Math.round(p.len)} ${t('m')}<br>` +
      `<span style="color:${s.c}">&#9632;</span> <b>${esc(t('status.' + p.status))}</b>; ${esc(t('sourcesCount', { n: p.conf }))}<ul>${items}</ul>` +
      `<small>${esc(t('dataAsOf', { date: summary.as_of }))} ${esc(p.id)}</small>`).openOn(map);
  }).catch(err => say(`<span class="error">${esc(t('segmentError', { msg: err.message }))}</span>`));
}

// ---------- route ----------
function letterIcon(which) {
  return L.divIcon({ className: 'pin', html: `<span>${LETTER[which]}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
}

function setPoint(which, latlng, label) {
  const pt = L.latLng(latlng);
  if (which === 'A') A = pt; else B = pt;
  labels[which] = label || t('pointOnMap');
  box[which].set(labels[which]);
  if (!markers[which]) {
    markers[which] = L.marker(pt, { icon: letterIcon(which), draggable: true, keyboard: true, title: t('point', { p: LETTER[which] }) })
      .addTo(map)
      .on('dragend', ev => {
        if (which === 'A') A = ev.target.getLatLng(); else B = ev.target.getLatLng();
        labels[which] = t('pointOnMap');
        box[which].set(labels[which]);
        if (A && B) compute();
      });
  } else {
    markers[which].setLatLng(pt);
  }
}

function clearPoint(which) {
  if (which === 'A') A = null; else B = null;
  if (markers[which]) { markers[which].remove(); markers[which] = null; }
  labels[which] = '';
  box[which].clear();
}

// both points known: show them and compute; one point: show it and ask for the other
function pointsChanged() {
  if (A && B) {
    map.fitBounds(L.latLngBounds([A, B]).pad(0.3));
    compute();
  } else {
    const p = A || B;
    if (p) map.setView(p, Math.max(map.getZoom(), 16));
    say(A ? t('hintB', LETTER) : t('hintStart', LETTER));
  }
}

// a suggestion was picked in the "from" (A) or "to" (B) box
function choose(which, r) {
  setPoint(which, [r.lat, r.lon], r.name);
  pointsChanged();
}

function locate() {
  if (!navigator.geolocation) { say(`<span class="error">${esc(t('geoError', { msg: 'navigator.geolocation' }))}</span>`); return; }
  say(esc(t('locating')));
  navigator.geolocation.getCurrentPosition(
    pos => { setPoint('A', [pos.coords.latitude, pos.coords.longitude], t('myLocation')); pointsChanged(); },
    err => say(`<span class="error">${esc(t('geoError', { msg: err.message }))}</span>`),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
}

function swap() {
  if (!A && !B) return;
  const old = { A, B, la: labels.A, lb: labels.B };
  clearPoint('A');
  clearPoint('B');
  if (old.B) setPoint('A', old.B, old.lb);
  if (old.A) setPoint('B', old.A, old.la);
  if (A && B) compute(); else { routeLayer.clearLayers(); $('cards').innerHTML = ''; }
}

function setTravel(value) {
  travel = value;
  for (const r of document.querySelectorAll('input[name="travel"]')) r.checked = r.value === value;
  $('at-wrap').hidden = value !== 'transit';
}

// A time typed in the control is just HH:MM. Gemini can also give an exact local date so that a relative
// request such as "in 20 minutes" keeps the correct day when it crosses midnight. The control shows the
// clock part; the complete value stays with it until the person edits the field.
function setDeparture(value) {
  const input = $('at');
  const exact = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value || '');
  input.value = exact ? value.slice(11) : (value || '');
  if (exact) input.dataset.datetime = value; else delete input.dataset.datetime;
}

function departure() {
  return $('at').dataset.datetime || $('at').value;
}

function onMapClick(e) {
  if (mode !== 'route' || !summary) return;
  if (A && B) reset();
  if (!A) setPoint('A', e.latlng); else setPoint('B', e.latlng);
  if (A && B) compute(); else say(A ? t('hintB', LETTER) : t('hintStart', LETTER));
}

function reset() {
  plan = null;
  clearPoint('A');
  clearPoint('B');
  routeLayer.clearLayers();
  $('cards').innerHTML = '';
  history.replaceState(null, '', location.pathname + location.search);
  say(t('hintStart', LETTER));
}

function compute() {
  const f = ll => `${ll.lat.toFixed(5)},${ll.lng.toFixed(5)}`;
  const at = travel === 'transit' ? departure() : '';
  const hash = new URLSearchParams({ a: f(A), b: f(B), an: labels.A, bn: labels.B, m: travel });
  if (at) hash.set('at', at);
  history.replaceState(null, '', `${location.search}#${hash.toString().replace(/%2C/g, ',').replace(/%3A/g, ':')}`);
  say(esc(t('computing')));
  getJSON(`/api/route?from=${f(A)}&to=${f(B)}&mode=${travel}${at ? '&at=' + encodeURIComponent(at) : ''}`)
    .then(d => {
      plan = d;
      selected = d.transit && d.transit.kind === 'ok' ? 'transit' : d.verdict.kind === 'same' ? 'fastest' : 'better_lit';
      say(esc(t('afterRoute')));
      drawRoute();
      renderCards();
    })
    .catch(err => {
      plan = null;
      routeLayer.clearLayers();
      $('cards').innerHTML = '';
      const d = err.detail || {};
      if (d.code === 'outside_coverage') {
        const near = d.nearest_m != null ? t('nearest', { d: fmtM(d.nearest_m) }) : '';
        say(`<span class="error">${esc(t('outside', { p: LETTER[d.point === 'from' ? 'A' : 'B'], near }))}</span>`);
      } else {
        say(`<span class="error">${esc(t('routeFailed', { msg: err.message }))}</span>`);
      }
    });
}

function drawRoute() {
  routeLayer.clearLayers();
  if (!plan) return;
  for (const [p, end] of [[A, plan.from], [B, plan.to]]) {
    if (end.snap_m > 3) L.polyline([[p.lat, p.lng], end.snapped], { color: '#111', weight: 2, dashArray: '2 5', interactive: false }).addTo(routeLayer);
  }
  const lines = r => r.geometry.features.map(f => f.geometry.coordinates.map(c => [c[1], c[0]]));
  const pieces = r => {
    L.polyline(lines(r), { color: '#111', weight: 11, opacity: 0.75, interactive: false }).addTo(routeLayer);
    for (const f of r.geometry.features) {
      const p = f.properties, s = ST[p.status] || ST.unknown;
      L.polyline(f.geometry.coordinates.map(c => [c[1], c[0]]), { color: s.c, weight: 7, dashArray: s.d, lineCap: 'butt' })
        .bindTooltip(`${esc(p.name || t('noName'))}: ${esc(t('status.' + p.status))}, ${fmtM(p.len)}`, { sticky: true })
        .addTo(routeLayer);
    }
  };
  if (selected === 'transit' && plan.transit && plan.transit.kind === 'ok') {
    const [walk1, ride, walk2] = plan.transit.legs;
    const ll = ride.coords.map(c => [c[1], c[0]]);
    L.polyline(ll, { color: '#111', weight: 10, opacity: 0.7, interactive: false }).addTo(routeLayer);
    L.polyline(ll, { color: ride.color, weight: 6 }).bindTooltip(esc(`${t('rt.' + ride.route_type)} ${ride.line}: ${ride.from.name} ${ride.dep} → ${ride.to.name} ${ride.arr}`), { sticky: true }).addTo(routeLayer);
    pieces(walk1);
    pieces(walk2);
    for (const s of [ride.from, ride.to]) {
      L.circleMarker([s.lat, s.lon], { radius: 7, color: '#111', weight: 3, fillColor: '#fff', fillOpacity: 1 }).bindTooltip(esc(s.name)).addTo(routeLayer);
    }
    routeLayer.bringToFront();
    return;
  }
  if (plan.verdict.kind !== 'same') {
    const other = plan.routes[selected === 'better_lit' ? 'fastest' : 'better_lit'];
    L.polyline(lines(other), { color: '#fff', weight: 7, opacity: 0.9, interactive: false }).addTo(routeLayer);
    L.polyline(lines(other), { color: '#2b4fb3', weight: 4, dashArray: '8 6', bubblingMouseEvents: false })
      .on('click', () => select(selected === 'better_lit' ? 'fastest' : 'better_lit'))
      .addTo(routeLayer);
  }
  pieces(plan.routes[selected]);
  routeLayer.bringToFront();
}

// the "on foot + public transport" card: the trip, or why there is none (the walking cards follow)
function transitCard() {
  const tr = plan.transit, s = plan.settings.transit;
  if (!tr) return '';
  if (tr.kind !== 'ok') {
    const why = tr.reason === 'no_stop_near' ? t('noStopNear', { m: s.max_walk_m })
      : tr.reason === 'no_line' ? t('noLine') : t('noTripSoon', { min: Math.round(s.max_wait_s / 60) });
    const text = [why, tr.last ? t('lastWas', tr.last) : '', tr.next ? t('nextIs', tr.next) : ''].filter(Boolean).join(' ');
    return `<div class="card info"><span class="title">${esc(t('transitTitle'))}</span><p class="warn">${esc(text)}</p>` +
      `<p class="small">${esc(t('walkInstead'))}</p></div>`;
  }
  const [walk1, ride, walk2] = tr.legs;
  const lit = r => pct(r.length_m ? r.by_status_m.lit_confirmed / r.length_m : 1);
  const legs = [
    t('legWalkTo', { min: fmtMin(walk1.minutes), dist: fmtM(walk1.length_m), stop: ride.from.name, lit: lit(walk1) }),
    t('legRide', { type: t('rt.' + ride.route_type), line: ride.line, headsign: ride.headsign, from: ride.from.name, dep: ride.dep,
      to: ride.to.name, arr: ride.arr, stops: ride.stops }),
    t('legWalkFrom', { min: fmtMin(walk2.minutes), dist: fmtM(walk2.length_m), stop: ride.to.name, lit: lit(walk2) }),
  ].map(x => `<li>${esc(x)}</li>`).join('');
  const warn = [walk1, walk2].filter(w => w.warn).length
    ? `<p class="warn">${esc(t('warn', { bad: fmtM(walk1.by_status_m.unknown + walk1.by_status_m.dark_reported + walk2.by_status_m.unknown + walk2.by_status_m.dark_reported),
      total: fmtM(walk1.length_m + walk2.length_m), share: pct((walk1.dark_unknown_share * walk1.length_m + walk2.dark_unknown_share * walk2.length_m) / Math.max(1, walk1.length_m + walk2.length_m)) }))}.</p>`
    : '';
  const slower = plan.routes.fastest.minutes <= tr.wait_min + tr.minutes ? `<p class="verdict bad">${esc(t('walkFaster'))}</p>` : '';
  return `<button type="button" class="card${selected === 'transit' ? ' selected' : ''}" data-kind="transit" aria-pressed="${selected === 'transit'}">` +
    `<span class="title">${esc(t('transitTitle'))}</span><span class="main">${fmtMin(tr.minutes)} · ${tr.leave_at} → ${tr.arrive_at}</span>` +
    `<ul class="legs">${legs}</ul>${warn}` +
    `<p class="verdict ok">${esc(t('leaveIn', { min: fmtMin(Math.max(0, tr.wait_min)), time: tr.leave_at }))} ${tr.last ? esc(t('lastDep', tr.last)) : ''}</p>` +
    `${slower}<p class="small">${esc(t('transitSource', { feed: tr.feed || '?' }))}</p></button>`;
}

function card(kind, r, title, note) {
  const by = r.by_status_m, len = r.length_m || 1;
  const bar = ORDER.filter(k => by[k] > 0).map(k => `<span style="width:${(100 * by[k] / len).toFixed(2)}%;background:${ST[k].c}" title="${esc(t('status.' + k))}"></span>`).join('');
  const rows = ORDER.map(k => `<li><span class="sw" style="border-top-color:${ST[k].c};border-top-style:${ST[k].css}"></span>` +
    `${esc(t('status.' + k))}: ${fmtM(by[k])} (${pct(by[k] / len)})</li>`).join('');
  const warn = r.warn
    ? `<p class="warn">${esc(t('warn', { bad: fmtM(by.unknown + by.dark_reported), total: fmtM(r.length_m), share: pct(r.dark_unknown_share) }) +
      (r.max_dark_run_m > 0 ? t('warnRun', { run: fmtM(r.max_dark_run_m) }) : ''))}.</p>`
    : '';
  const via = r.streets.length ? `<p class="via">${esc(t('via'))}${r.streets.slice(0, 4).map(esc).join(' → ')}${r.streets.length > 4 ? ' → …' : ''}</p>` : '';
  return `<button type="button" class="card${selected === kind ? ' selected' : ''}" data-kind="${kind}" aria-pressed="${selected === kind}">` +
    `<span class="title">${esc(title)}</span><span class="main">${fmtMin(r.minutes)} · ${fmtM(r.length_m)}</span>` +
    `<span class="bar">${bar}</span><ul>${rows}</ul>${warn}${via}${note || ''}</button>`;
}

function renderCards() {
  const { fastest, better_lit: lit } = plan.routes, v = plan.verdict, s = plan.settings;
  const litShare = r => r.length_m ? r.by_status_m.lit_confirmed / r.length_m : 0;
  let html;
  if (v.kind === 'same') {
    html = card('fastest', fastest, t(v.near ? 'nearSameTitle' : 'sameTitle'));
  } else {
    const extra = t('extra', { min: dec(Math.max(0, v.extra_min)), share: pct(v.extra_share) });
    const note = v.kind === 'too_long'
      ? `<p class="verdict bad">${esc(t('tooLong', { extra, limit: s.hide_if_extra_min, limitShare: pct(s.hide_if_extra_share) }))}</p>`
      : `<p class="verdict ok">${esc(t('extraOk', { extra, lit: pct(litShare(lit)), fast: pct(litShare(fastest)) }))}</p>`;
    html = card('better_lit', lit, t('litTitle'), note) + card('fastest', fastest, t('fastTitle'));
  }
  html = transitCard() + html;
  const off = [['A', plan.from], ['B', plan.to]].filter(([, p]) => p.snap_m > 20).map(([n, p]) => `${LETTER[n]}: ${Math.round(p.snap_m)} ${t('m')}`);
  if (off.length) html += `<p class="small">${esc(t('snapNote', { list: off.join(', ') }))}</p>`;
  $('cards').innerHTML = html;
  for (const el of document.querySelectorAll('.card')) el.addEventListener('click', () => select(el.dataset.kind));
}

function select(kind) {
  const ok = kind === 'transit' ? plan && plan.transit && plan.transit.kind === 'ok' : plan && plan.routes[kind];
  if (!ok) return;
  selected = kind;
  drawRoute();
  renderCards();
}

function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  const point = v => { const m = /^(-?[\d.]+),(-?[\d.]+)$/.exec(v || ''); return m ? [+m[1], +m[2]] : null; };
  const a = point(h.get('a')), b = point(h.get('b'));
  if (!a || !b) return false;
  if (['bike', 'transit'].includes(h.get('m'))) setTravel(h.get('m'));
  if (h.get('at')) setDeparture(h.get('at'));
  setPoint('A', a, h.get('an'));
  setPoint('B', b, h.get('bn'));
  map.fitBounds(L.latLngBounds([A, B]).pad(0.3));
  compute();
  return true;
}

// ---------- start ----------
getJSON('/api/summary')
  .then(s => {
    summary = s;
    const [w, so, e, n] = s.bounds_wsen;
    const bounds = buildArea(s) || L.latLngBounds([[so, w], [n, e]]);
    if (!location.hash) map.fitBounds(bounds);
    const g = s.groups.streets_and_sidewalks, src = s.sources;
    $('meta').textContent = t('meta', {
      km: dec(g.km), lit: dec(g.lit_confirmed), likely: dec(g.lit_likely), dark: dec(g.dark_reported), unknown: dec(g.unknown), asof: s.as_of,
      osm: (s.network.fetched_at || '').slice(0, 10), mly: (src.mapillary.last_seen_range || []).join('…'),
      ses: (src.sesizari.created_range || []).join('…'), walk: dec((3.6 * 1.35).toFixed(1)), bike: dec((3.6 * 4.2).toFixed(0)),
    });
    if (window.ExtraLayers) {
      const ctl = L.control.layers(null, {}, { collapsed: window.innerWidth < 800, position: 'topright' }).addTo(map);
      ExtraLayers.add(map, ctl, LAYERS_BASE, { skip: ['zones'], lang: LANG, bounds: bounds.pad(0.05) }).then(() => routeLayer.bringToFront());
    }
    map.on('moveend', debounce(refresh, 200));
    map.on('click', onMapClick);
    $('reset').addEventListener('click', reset);
    $('locate').addEventListener('click', locate);
    $('swap').addEventListener('click', swap);
    for (const r of document.querySelectorAll('input[name="travel"]')) {
      r.addEventListener('change', () => { setTravel(r.value); if (A && B) compute(); });
    }
    $('at').addEventListener('input', () => { delete $('at').dataset.datetime; });
    $('at').addEventListener('change', () => { if (A && B && travel === 'transit') compute(); });
    $('net').addEventListener('change', refresh);
    for (const r of document.querySelectorAll('input[name="mode"]')) {
      r.addEventListener('change', () => {
        mode = r.value;
        map.closePopup();
        say(mode === 'route' ? (A && B ? esc(t('newRoute')) : t('hintStart', LETTER)) : esc(t('inspect')));
        refresh();
      });
    }
    if (!readHash()) say(t('hintStart', LETTER));
    refresh();
  })
  .catch(err => say(`<span class="error">${t('serverDown', { msg: esc(err.message) })}</span>`));
