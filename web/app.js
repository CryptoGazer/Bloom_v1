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
  if (!r.ok) { const e = new Error((body.detail && body.detail.message) || 'HTTP ' + r.status);
    e.detail = r.status === 404 && url.startsWith('/api/loop') && (!body.detail || !body.detail.code) ? { code: 'loop_api_missing' } : body.detail;
    e.status = r.status; throw e; }
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
  $('live-net-label').textContent = t('live.show');
  $('legend-title').textContent = t('legendTitle');
  $('area-note').textContent = t('areaNote');
  $('legend').innerHTML = ['lit_confirmed', 'lit_likely', 'unknown', 'dark_reported']
    .map(k => `<li><span class="sw" style="border-top-color:${ST[k].c};border-top-style:${ST[k].css}"></span>${esc(t('legend.' + k))}</li>`).join('') +
    `<li><span class="sw" style="border-top-color:#2b4fb3;border-top-style:dashed"></span>${esc(t('legend.second'))}</li>` +
    `<li><span class="veh-num" style="position:static;flex:0 0 22px;width:22px;height:22px;background:#6f2095;color:#fff">16</span>${esc(t('live.legend'))}</li>`;
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
  attribution: '&copy; OpenStreetMap contributors · Mapillary · Primăria Timișoara, Sesizări · ' +
    '<a href="https://www.flaticon.com/free-icons/street-light" title="street light icons" target="_blank" rel="noopener">Icon: Magnific – Flaticon</a>' }).addTo(map);
const areaLayer = L.layerGroup().addTo(map);
const areaLabel = L.layerGroup();
const segLayer = L.layerGroup().addTo(map);
const routeLayer = L.featureGroup().addTo(map);
const liveLayer = L.layerGroup().addTo(map);   // live vehicles: markers (DOM), always above the route lines
map.on('overlayadd', () => routeLayer.bringToFront());
let live = null, liveTimer = null, liveReq = 0;   // the last /api/transit/live answer, the next poll, the request in flight

let summary = null, A = null, B = null, plan = null, selected = 'better_lit', mode = 'route', segReq = 0, routeReq = 0;
let travel = 'walk';  // 'walk' | 'bike' | 'transit': how the person goes; "mode" above is what a map click does
let loopRequest = null, askPointChoice = null; // automatic/manual loop query; unresolved Gemini loop selection
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
        loopRequest = null;
        if (markers.B) markers.B.setOpacity(1);
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

// Shared with the mobile Gemini controller: discard stale results without resetting known points.
function clearAskRoute() {
  ++routeReq;
  loopRequest = null; askPointChoice = null;
  if (markers.B) markers.B.setOpacity(1);
  plan = null;
  liveTick();
  routeLayer.clearLayers();
  $('cards').replaceChildren();
  history.replaceState(null, '', location.pathname + location.search);
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
  if (askPointChoice && askPointChoice(which, r)) return;
  loopRequest = null;
  if (markers.B) markers.B.setOpacity(1);
  setPoint(which, [r.lat, r.lon], r.name);
  pointsChanged();
}

function locate() {
  const pick = askPointChoice;
  const req = ++routeReq;
  loopRequest = null;
  if (markers.B) markers.B.setOpacity(1);
  if (!navigator.geolocation) { say(`<span class="error">${esc(t('geoError', { msg: 'navigator.geolocation' }))}</span>`); return; }
  say(esc(t('locating')));
  navigator.geolocation.getCurrentPosition(
    pos => {
      if (req !== routeReq) return;
      const p = { lat: pos.coords.latitude, lon: pos.coords.longitude, name: t('myLocation') };
      if (pick && pick('A', p)) return;
      setPoint('A', [p.lat, p.lon], p.name); pointsChanged();
    },
    err => say(`<span class="error">${esc(t('geoError', { msg: err.message }))}</span>`),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
}

function swap() {
  loopRequest = null;
  if (markers.B) markers.B.setOpacity(1);
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
  $('at-wrap').hidden = false;  // the leaving time matters for every mode: signs of life, transit
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
  clearAskRoute();
  clearPoint('A');
  clearPoint('B');
  routeLayer.clearLayers();
  $('cards').innerHTML = '';
  history.replaceState(null, '', location.pathname + location.search);
  say(t('hintStart', LETTER));
}

function startAskLoop(r) {
  clearPoint('A'); clearPoint('B');
  const req = ++routeReq;
  say(esc(t('computing')));
  BzAsk.loopParams(r).then(params => {
    if (req !== routeReq) return;
    loopRequest = params;
    compute();
  }).catch(err => {
    if (req === routeReq) say(`<span class="error">${esc(t('geoError', { msg: err.message }))}</span>`);
  });
}

function compute() {
  if (loopRequest && travel === 'transit') {
    setTravel(plan && plan.loop ? plan.mode : 'walk');
    say(`<span class="error">${esc(t('ask.loopTransit'))}</span>`);
    return;
  }
  const req = ++routeReq;
  const f = ll => `${ll.lat.toFixed(5)},${ll.lng.toFixed(5)}`;
  const at = departure();
  const query = loopRequest ? new URLSearchParams(loopRequest) : new URLSearchParams({ from: f(A), to: f(B) });
  query.set('mode', travel);
  if (at) query.set('at', at);
  const save = points => {
    const hash = new URLSearchParams({ a: f(A), b: f(B), an: labels.A, bn: labels.B, m: travel });
    if (at) hash.set('at', at);
    if (points) hash.set('loop', points.map(p => `${p.lat},${p.lon}`).join(';'));
    history.replaceState(null, '', `${location.search}#${hash.toString().replace(/%2C/g, ',').replace(/%3A/g, ':')}`);
  };
  if (!loopRequest) save();
  say(esc(t('computing')));
  getJSON(`/api/${loopRequest ? 'loop' : 'route'}?${query}`)
    .then(d => {
      if (req !== routeReq) return;
      plan = d;
      if (d.loop) {
        setPoint('A', [d.points[0].lat, d.points[0].lon], t('ask.loopStart'));
        setPoint('B', [d.points[0].lat, d.points[0].lon], t('ask.loopStart'));
        markers.B.setOpacity(0);
        save(d.points);
      }
      selected = d.transit && d.transit.kind === 'ok' ? 'transit' : d.verdict.kind === 'same' ? (d.verdict.pick || 'fastest') : 'better_lit';
      say(esc(t('afterRoute')));
      live = null;   // the old answer was about another trip
      drawRoute();
      if (d.loop) map.fitBounds(routeLayer.getBounds().pad(0.2));
      renderCards();
      liveTick();
    })
    .catch(err => {
      if (req !== routeReq) return;
      plan = null;
      liveTick();
      routeLayer.clearLayers();
      $('cards').innerHTML = '';
      // texts come from i18n.js by error code; the server's English message is only a fallback detail
      const d = err.detail || {};
      let text;
      if (d.code === 'no_loop_area') {
        text = t('ask.loopUnavailable');
      } else if (d.code === 'loop_api_missing') {
        text = t('ask.loopApiMissing');
      } else if (d.code === 'outside_coverage') {
        const near = d.nearest_m != null ? t('nearest', { d: fmtM(d.nearest_m) }) : '';
        text = t(travel === 'bike' ? 'outsideBike' : 'outside', { p: LETTER[d.point === 'from' ? 'A' : 'B'], near });
      } else {
        const key = 'err.' + (d.code === 'no_route' ? 'no_route_' + (travel === 'bike' ? 'bike' : 'walk') : d.code);
        text = d.code && t(key) !== key ? t(key) : t('err.other', { code: d.code || err.message });
      }
      say(`<span class="error">${esc(text)}</span>`);
    });
}

function drawRoute() {
  routeLayer.clearLayers();
  if (!plan) return;
  if (plan.loop) for (const [i, p] of plan.points.entries()) {
    if (!i) continue;
    L.marker([p.lat, p.lon], { icon: L.divIcon({ className: 'pin', html: `<span>${i + 1}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] }),
      interactive: false }).bindTooltip(esc(t('ask.loopPoint', { n: i + 1 }))).addTo(routeLayer);
  }
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
  for (const p of (plan.routes[selected].signs || {}).open_places || []) {
    L.circleMarker([p.lat, p.lon], { radius: 6, color: '#6a3d9a', weight: 3, fillColor: '#fff', fillOpacity: 1 })
      .bindTooltip(esc(p.name + (p.always ? ' (' + t('signsAlways') + ')' : '')), { direction: 'top' }).addTo(routeLayer);
  }
  routeLayer.bringToFront();
}

// signs of life along a route at the leaving time: evidence, never a score (backend/liveliness.py)
function signsBlock(sg) {
  const items = [];
  const open = sg.open_places.map(p => p.name + (p.always ? ' (' + t('signsAlways') + ')' : '')).join(', ');
  let first = open ? t('signsOpen', { list: open }) : t('signsNoneOpen');
  if (sg.places_unknown_hours) first += ' · ' + t('signsUnknown', { n: sg.places_unknown_hours });
  items.push(first);
  if (sg.stops.length) {
    items.push(t('signsStops', { list: sg.stops.slice(0, 3).map(s => `${s.name} (${s.departures.slice(0, 3).map(d => d.line + ' ' + d.time).join(', ')})`).join('; ') }));
  }
  items.push(t('signsMain', { pct: pct(sg.main_share) }));
  return `<div class="signs"><span class="signs-title">${esc(t('signsTitle', { time: (plan.at || '').slice(11, 16) }))}</span>` +
    `<ul>${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p class="small">${esc(t('signsNote'))}</p></div>`;
}

// How this line ran around this hour on a recent day (hist.js): one sentence with the advice, where it comes from
// behind a tap. A block of its own under the live box: the trip card is a button and cannot hold a disclosure.
function historyBox() {
  const h = historyParts(ride());
  if (!h) return '';
  return `<details class="hist"><summary>${esc(h.sentence)}${h.advice ? ` <b>${esc(h.advice)}</b>` : ''}` +
    ` <span class="hist-more">${esc(t('hist.more'))}</span></summary><p>${esc(h.source)}</p></details>`;
}

// the "on foot + public transport" card: the trip, or why there is none (the walking cards follow)
function transitCard() {
  const tr = plan.transit, s = plan.settings.transit;
  if (!tr) return '';
  if (tr.kind !== 'ok') {
    const why = tr.reason === 'no_stop_near' ? t('noStopNear', { m: s.max_walk_m }) : tr.reason === 'no_line' ? t('noLine') : tr.reason === 'no_timetable' ? t('noTimetable') : tr.reason === 'too_close' ? t('tooClose') : t('noTripSoon', { min: Math.round(s.max_wait_s / 60) });
    const text = [why, tr.last ? t(tr.last.missed ? 'lastMissed' : 'lastWas', tr.last) : '', tr.next ? t('nextIs', tr.next) : ''].filter(Boolean).join(' ');
    return `<div class="card info"><span class="title">${esc(t('transitTitle'))}</span><p class="warn">${esc(text)}</p>` +
      `<p class="small">${esc(t('walkInstead'))}</p></div>`;
  }
  const [walk1, ride, walk2] = tr.legs;
  const lit = r => pct(r.length_m ? r.by_status_m.lit_confirmed / r.length_m : 1);
  // bar over the whole trip by time: the walks coloured by lighting, the ride in the line's colour
  const total = walk1.minutes + ride.minutes + walk2.minutes || 1;
  const walkPart = w => ORDER.filter(k => w.by_status_m[k] > 0).map(k =>
    `<span style="width:${(100 * w.minutes * w.by_status_m[k] / (w.length_m || 1) / total).toFixed(2)}%;background:${ST[k].c}" title="${esc(t('status.' + k))}"></span>`).join('');
  const bar = walkPart(walk1) + `<span style="width:${(100 * ride.minutes / total).toFixed(2)}%;background:${ride.color}" title="${esc(t('rt.' + ride.route_type) + ' ' + ride.line)}"></span>` + walkPart(walk2);
  const walkLen = walk1.length_m + walk2.length_m || 1;
  const rows = ORDER.map(k => {
    const m = walk1.by_status_m[k] + walk2.by_status_m[k];
    return `<li><span class="sw" style="border-top-color:${ST[k].c};border-top-style:${ST[k].css}"></span>${esc(t('status.' + k))}: ${fmtM(m)} (${pct(m / walkLen)})</li>`;
  }).join('') + `<li><span class="sw" style="border-top-color:${ride.color};border-top-style:solid"></span>${esc(t('rideRow', { min: fmtMin(ride.minutes) }))}</li>`;
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
  // No "walking is not slower" note here: it compared arrival times from the requested leaving time and showed on
  // 64% of trips, while the transit card counts from the later leaving time and still saves ~5 min of walking outside.
  return `<button type="button" class="card${selected === 'transit' ? ' selected' : ''}" data-kind="transit" aria-pressed="${selected === 'transit'}">` +
    `<span class="title">${esc(t('transitTitle'))}</span><span class="main">${fmtMin(tr.minutes)} · ${tr.leave_at} → ${tr.arrive_at}</span>` +
    `<span class="bar">${bar}</span><ul>${rows}</ul><p class="small">${esc(t('walkPartNote'))}</p>` +
    `<ul class="legs">${legs}</ul>${warn}` +
    `<p class="verdict ok">${esc(t('leaveIn', { min: fmtMin(Math.max(0, tr.wait_min)), time: tr.leave_at }))} ${tr.last ? esc(t('lastDep', tr.last)) : ''}</p>` +
    `<p class="small">${esc(t('transitSource', { feed: tr.feed || '?' }))}</p></button>`;
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
    `<span class="bar">${bar}</span><ul>${rows}</ul>${warn}${via}${r.signs ? signsBlock(r.signs) : ''}${note || ''}</button>`;
}

function renderCards() {
  const { fastest, better_lit: lit } = plan.routes, v = plan.verdict, s = plan.settings;
  const litShare = r => r.length_m ? r.by_status_m.lit_confirmed / r.length_m : 0;
  let html;
  if (v.kind === 'same') {
    const pick = v.pick || 'fastest';  // one card: nothing to choose between the two routes
    html = card(pick, plan.routes[pick], pick === 'better_lit' ? t('litFreeTitle') : t(v.near ? 'nearSameTitle' : 'sameTitle'));
  } else {
    const extra = t('extra', { min: dec(Math.max(0, v.extra_min)), share: pct(v.extra_share) });
    const note = v.kind === 'too_long'
      ? `<p class="verdict bad">${esc(t('tooLong', { extra, limit: s.hide_if_extra_min, limitShare: pct(s.hide_if_extra_share) }))}</p>`
      : `<p class="verdict ok">${esc(t('extraOk', { extra, lit: pct(litShare(lit)), fast: pct(litShare(fastest)) }))}</p>`;
    html = card('better_lit', lit, t('litTitle'), note) + card('fastest', fastest, t('fastTitle'));
  }
  html = transitCard() + liveBox() + historyBox() + html;
  const off = [['A', plan.from], ['B', plan.to]].filter(([, p]) => p.snap_m > 20).map(([n, p]) => `${LETTER[n]}: ${Math.round(p.snap_m)} ${t('m')}`);
  if (off.length) html += `<p class="small">${esc(t('snapNote', { list: off.join(', ') }))}</p>`;
  $('cards').innerHTML = html;
  for (const el of document.querySelectorAll('.card')) el.addEventListener('click', () => select(el.dataset.kind));
  const box = $('live-box');
  if (box) box.addEventListener('click', e => { if (e.target.id === 'live-recalc') compute(); });
  updateLiveBox();
}

// ---------- live public transport (backend/live.py through /api/transit/live) ----------
// Polled only while a "walk + transit" trip is shown or the "live transport on the map" box is ticked, and never
// in a hidden tab. Every number says how old it is; without a live forecast the page says it shows the timetable.
const clockFmt = new Intl.DateTimeFormat('ro-RO', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Bucharest' });
const clockOf = ts => clockFmt.format(new Date(ts * 1000));
const ago = s => s == null ? '?' : s < 60 ? t('live.ago.s', { n: Math.round(s) }) : t('live.ago.min', { n: Math.round(s / 60) });
const minOff = s => Math.max(1, Math.round(Math.abs(s) / 60)) + ' ' + t('min');
const safeColor = c => /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : '#555555';
const inkOn = hex => { const n = parseInt(hex.slice(1), 16); return 0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) > 150 ? '#111' : '#fff'; };

function ride() {
  const tr = plan && plan.transit;
  return tr && tr.kind === 'ok' ? tr.legs[1] : null;
}

function liveQuery() {
  const r = ride(), all = $('live-net').checked;
  if (!r && !all) return null;
  const q = {};
  if (r && !all) q.route = r.route_id;
  if (r && r.trip_id && r.dep_ts) {
    Object.assign(q, { trip: r.trip_id, dep: r.dep_ts, day: r.day });
    if (r.board_seq != null) q.seq = r.board_seq;
  }
  return q;
}

function liveTick() {
  clearTimeout(liveTimer);
  const q = liveQuery();
  if (!q) { live = null; liveReq++; liveLayer.clearLayers(); return; }
  if (document.hidden) return;   // visibilitychange starts it again
  const req = ++liveReq;
  getJSON('/api/transit/live?' + new URLSearchParams(q))
    .then(d => { if (req === liveReq) live = d; })
    .catch(err => { if (req === liveReq) live = { failed: err.message }; })
    .finally(() => {
      if (req !== liveReq) return;
      drawVehicles();
      updateLiveBox();
      // ask again just after the server's shared copy is due for a refresh
      const wait = live && live.refresh_s ? Math.max(5, live.refresh_s - ((live.source && live.source.age_s) || 0) + 1) : 30;
      liveTimer = setTimeout(liveTick, wait * 1000);
    });
}

function vehicleTip(v) {
  let s = t('live.tip', { type: t('rt.' + v.route_type), line: v.line, headsign: v.headsign || '?', age: ago(v.age_s) });
  if (!v.live) s += t('live.tipOld');
  else if (v.delay_s != null) s += Math.abs(v.delay_s) < 60 ? t('live.tipOnTime') : t(v.delay_s > 0 ? 'live.tipLate' : 'live.tipEarly', { d: minOff(v.delay_s) });
  if (v.wheelchair) s += t('live.wheelchair');
  return s;
}

function drawVehicles() {
  liveLayer.clearLayers();
  if (!live || !live.vehicles) return;
  const r = ride(), mineId = live.trip && live.trip.vehicle;
  for (const v of live.vehicles) {
    if (typeof v.lat !== 'number' || typeof v.lon !== 'number') continue;
    const mine = v.id === mineId, onLine = r && v.route_id === r.route_id, color = safeColor(v.color);
    const cls = 'veh' + (v.live ? '' : ' old') + (mine ? ' mine' : '') + (r && !onLine ? ' dim' : '');
    const arrow = typeof v.bearing === 'number' ? `<span class="veh-arrow" style="transform:rotate(${v.bearing}deg)"></span>` : '';
    const icon = L.divIcon({ className: cls, iconSize: [30, 30], iconAnchor: [15, 15],
      html: `${arrow}<span class="veh-num" style="background:${color};color:${inkOn(color)}">${esc(v.line)}</span>` });
    L.marker([v.lat, v.lon], { icon, keyboard: false, zIndexOffset: mine ? 1000 : onLine ? 500 : 0 })
      .bindTooltip(esc(vehicleTip(v)), { direction: 'top', offset: [0, -14] })
      .addTo(liveLayer);
  }
}

function liveBox() {
  return ride() ? '<div class="live-box" id="live-box"><span class="live-tag off" id="live-tag"></span>' +
    '<p class="live-main" id="live-main" role="status" aria-live="polite"></p><div id="live-more"></div><p class="small" id="live-src"></p></div>' : '';
}

function liveTexts(r) {
  const type = t('rt.' + r.route_type), stop = r.from.name, out = { on: false, main: '', more: [], src: '' };
  if (!live) { out.main = esc(t('live.loading')); return out; }
  if (live.failed) { out.main = esc(t('live.noData')); return out; }
  const T = live.trip || { status: 'no_vehicle' }, s = plan.settings;
  if (T.expected_ts != null) {   // a forecast: "live" on the trip, or "previous_trip" right before it
    out.on = true;
    out.main = esc(T.stops_away === 0 ? t('live.atStop', { type, line: r.line, stop })
      : t('live.arrives', { type, line: r.line, stop, min: fmtMin(Math.max(0, T.eta_s) / 60), time: clockOf(T.expected_ts) }));
    out.more.push(Math.abs(T.delay_s) < 60 ? t('live.onTime', { sched: r.dep })
      : t(T.delay_s > 0 ? 'live.late' : 'live.early', { min: minOff(T.delay_s), sched: r.dep }));
    if (T.stops_away > 1) out.more.push(t('live.stopsAway', { n: T.stops_away }));
    if (T.stops_away === 1) out.more.push(t('live.oneStop'));
    if (T.status === 'previous_trip') out.more.push(t('live.previous', { headsign: T.now_headsign || '?' }));
    const walk = plan.transit.legs[0].minutes * 60 + s.transit.board_margin_s, slack = T.eta_s - walk;
    if (T.stops_away !== 0 && slack < 0) out.more.push(t('live.tooLate', { walk: fmtMin(plan.transit.legs[0].minutes) }));
    else if (slack < 20 * 60) out.more.push(t('live.leaveBy', { time: clockOf(T.expected_ts - walk) }));
    out.more.push(t('live.estimate'));
    out.more = out.more.map(esc);
  } else {
    const why = {
      previous_trip: T.trips_before > 1 ? t('live.previousMany', { n: T.trips_before }) : t('live.previous', { headsign: T.now_headsign || '?' }),
      no_vehicle: t('live.noVehicle'), stale: t('live.stale', { age: ago(T.age_s) }), no_forecast: t('live.noForecast'),
      passed: t('live.passed', { stop }), later: t('live.later'), no_data: t('live.noData'),
    }[T.status] || t('live.noVehicle');
    out.main = esc(why);
    if (T.status === 'no_forecast' && T.stops_away > 1) out.more.push(esc(t('live.stopsAway', { n: T.stops_away })));
    if (T.status === 'passed') out.more.push(`<button type="button" id="live-recalc">${esc(t('live.recalc'))}</button>`);
  }
  const src = live.source || {};
  out.src = src.error && src.age_s > 2 * (live.refresh_s || 15) ? t('live.sourceDown', { age: ago(src.age_s) })
    : t('live.source', { age: ago(src.age_s), every: live.refresh_s });
  if (T.age_s != null) out.src += ' · ' + t('live.vehAge', { age: ago(T.age_s) });
  out.src = esc(out.src);
  return out;
}

function updateLiveBox() {
  const r = ride(), box = $('live-box');
  if (!r || !box) return;
  const x = liveTexts(r);
  // only touch what changed: the main line is a live region and must not be re-announced every poll
  const set = (el, html) => { if (el.dataset.v !== html) { el.dataset.v = html; el.innerHTML = html; } };
  const tag = $('live-tag');
  tag.className = 'live-tag ' + (x.on ? 'on' : 'off');
  set(tag, esc(t(x.on ? 'live.on' : 'live.off')));
  set($('live-main'), x.main);
  set($('live-more'), x.more.map(m => `<p>${m}</p>`).join(''));
  set($('live-src'), x.src);
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
  if (h.get('loop')) loopRequest = new URLSearchParams({ points: h.get('loop') });
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
      ses: (src.sesizari.created_range || []).join('…'), walk: dec('4.3'), bike: dec((3.6 * 4.2).toFixed(0)),
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
    $('at').addEventListener('change', () => { if (A && B) compute(); });
    $('net').addEventListener('change', refresh);
    $('live-net').addEventListener('change', liveTick);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) liveTick(); });
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
