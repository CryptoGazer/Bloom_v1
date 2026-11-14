'use strict';
/* City-wide night-route page. All data comes from the backend (backend/app.py) on the same origin:
   /api/summary, /api/segments?bbox=, /api/segments/{id}, /api/route. See web/README.md. */

const LAYERS_BASE = '/data/out/layers/';
const SEG_MIN_ZOOM = 15;          // closer than this: street segments; farther: districts
const SEG_LIMIT = 8000;

const ST = {
  lit_confirmed: { c: '#009E73', d: null, t: 'освещено' },
  lit_likely: { c: '#E69F00', d: '9 6', t: 'вероятно освещено' },
  unknown: { c: '#7F7F7F', d: '1 7', t: 'нет данных' },
  dark_reported: { c: '#D55E00', d: '13 5 2 5', t: 'сообщали, что темно' },
};
const ORDER = ['lit_confirmed', 'lit_likely', 'unknown', 'dark_reported'];
const DRAW_ORDER = ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported'];
const KIND = { street: 'улица', sidewalk: 'тротуар', crossing: 'переход', path: 'дорожка', service: 'проезд' };
const EV_STATE = { fixed: 'закрыта', open_area_outage: 'открыта: темно в районе', open_lamp_out: 'открыта: не горит лампа',
  open_other: 'открыта: прочее', declined: 'отклонена, не засчитана' };

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtM = m => m >= 1000 ? (m / 1000).toFixed(2).replace('.', ',') + ' км' : Math.round(m) + ' м';
const fmtMin = m => Math.max(1, Math.round(m)) + ' мин';
const pct = x => Math.round(100 * x) + '%';
const say = html => { $('hint').innerHTML = html; };
const getJSON = url => fetch(url).then(async r => {
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error((body.detail && body.detail.message) || 'HTTP ' + r.status); e.detail = body.detail; e.status = r.status; throw e; }
  return body;
});
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

// ---------- map ----------
const map = L.map('map', { preferCanvas: true, renderer: L.canvas({ tolerance: 6 }) }).setView([45.7537, 21.2257], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'gray-tiles',
  attribution: '&copy; OpenStreetMap contributors · Mapillary · Primăria Timișoara, Sesizări' }).addTo(map);
map.createPane('zonesPane').style.zIndex = 350;
const zonesLayer = L.layerGroup();
const segLayer = L.layerGroup().addTo(map);
const routeLayer = L.featureGroup().addTo(map);
map.on('overlayadd', () => routeLayer.bringToFront());

let summary = null, A = null, B = null, plan = null, selected = 'better_lit', mode = 'route', segReq = 0;
const markers = { A: null, B: null };

// ---------- districts (zoomed out) ----------
function buildZones(fc) {
  const known = new Map((summary.zones || []).map(z => [z.name, z]));
  for (const f of fc.features) {
    const z = known.get(f.properties.name);
    const share = z && z.known != null ? z.known : null;
    const poly = L.geoJSON(f, { pane: 'zonesPane', interactive: false,
      style: { color: '#1d3f8f', weight: 1, opacity: 0.6, fillColor: '#1d3f8f', fillOpacity: share == null ? 0 : 0.03 + 0.25 * share / 100 } }).addTo(zonesLayer);
    L.tooltip({ permanent: true, direction: 'center', className: 'zone-name', interactive: false })
      .setLatLng(poly.getBounds().getCenter())
      .setContent(`${esc(f.properties.name)}<br><b>${share == null ? '?' : Math.round(share) + '%'}</b>`)
      .addTo(zonesLayer);
  }
}

// ---------- street segments (zoomed in) ----------
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
    if (showNet) zonesLayer.addTo(map); else zonesLayer.remove();
    return;
  }
  const b = map.getBounds().pad(0.15), req = ++segReq;
  getJSON(`/api/segments?bbox=${b.getWest().toFixed(5)},${b.getSouth().toFixed(5)},${b.getEast().toFixed(5)},${b.getNorth().toFixed(5)}&limit=${SEG_LIMIT}`)
    .then(d => {
      if (req !== segReq) return; // a newer request is on its way
      if (d.truncated) { segLayer.clearLayers(); zonesLayer.addTo(map); return; }
      zonesLayer.remove();
      drawSegments(d.features);
      routeLayer.bringToFront();
    })
    .catch(err => console.warn('segments:', err.message));
}

// ---------- "why this colour" ----------
function evidenceLine(e) {
  if (e.s === 'osm') return `OpenStreetMap: lit=${esc(e.k)} (путь ${(e.ways || []).map(esc).join(', ')})`;
  if (e.s === 'mapillary') return `Mapillary: фонарей в 20 м — ${e.n}, ближайший в ${e.near} м, покрыто ${Math.round(e.cov * 100)}% длины, сняты в ${e.y0}${e.y1 !== e.y0 ? '–' + e.y1 : ''}` +
    (e.cov < 0.5 ? ' — меньше половины, источник не засчитан' : '');
  if (e.s === 'sesizari') return `Sesizări ${esc(e.nr)}${e.n > 1 ? ' (+' + (e.n - 1) + ')' : ''}: ${esc(e.sub)} — ${EV_STATE[e.k] || esc(e.k)}, подана ${esc(e.created)}` +
    (e.closed ? `, закрыта ${esc(e.closed)}` : '') + (e.age != null ? `, ${e.age} дн. назад` : '') + `, ${e.d} м от отрезка`;
  if (e.k === 'same_name') return `Косвенно: улица «${esc(e.ref)}» отмечена освещённой в другом месте`;
  if (e.k === 'near_lit_street') return 'Косвенно: рядом улица со свидетельствами освещения';
  if (e.k === 'partial_lamps') return 'Косвенно: фонари есть только на части отрезка';
  if (e.k === 'inherited_dark') return 'Соседняя улица отмечена тёмной по жалобам';
  return esc(JSON.stringify(e));
}

function showEvidence(id, latlng) {
  getJSON('/api/segments/' + encodeURIComponent(id)).then(f => {
    const p = f.properties, s = ST[p.status] || ST.unknown;
    const items = (p.ev || []).length ? p.ev.map(e => `<li>${evidenceLine(e)}</li>`).join('') : '<li>Свидетельств нет</li>';
    L.popup({ maxWidth: 380 }).setLatLng(latlng).setContent(
      `<b>${esc(p.name || 'без названия')}</b> · ${KIND[p.kind] || esc(p.kind)} · ${Math.round(p.len)} м<br>` +
      `<span style="color:${s.c}">&#9632;</span> <b>${s.t}</b>; независимых источников: ${p.conf}<ul>${items}</ul>` +
      `<small>Данные на ${esc(summary.as_of)}. ${esc(p.id)}</small>`).openOn(map);
  }).catch(err => say(`<span class="error">Не удалось загрузить отрезок: ${esc(err.message)}</span>`));
}

// ---------- route ----------
function letterIcon(letter) {
  return L.divIcon({ className: 'pin', html: `<span>${letter}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
}

function setPoint(which, latlng) {
  const pt = L.latLng(latlng);
  if (which === 'A') A = pt; else B = pt;
  if (!markers[which]) {
    markers[which] = L.marker(pt, { icon: letterIcon(which), draggable: true, keyboard: true, title: 'Точка ' + which })
      .addTo(map)
      .on('dragend', ev => {
        if (which === 'A') A = ev.target.getLatLng(); else B = ev.target.getLatLng();
        if (A && B) compute();
      });
  } else {
    markers[which].setLatLng(pt);
  }
}

function onMapClick(e) {
  if (mode !== 'route' || !summary) return;
  if (A && B) reset();
  if (!A) { setPoint('A', e.latlng); say('Теперь кликните точку <b>Б</b>. Маркеры можно перетаскивать.'); }
  else { setPoint('B', e.latlng); compute(); }
}

function reset() {
  A = B = plan = null;
  for (const k of ['A', 'B']) if (markers[k]) { markers[k].remove(); markers[k] = null; }
  routeLayer.clearLayers();
  $('cards').innerHTML = '';
  history.replaceState(null, '', location.pathname + location.search);
  say('Кликните на карте точку <b>А</b>, затем точку <b>Б</b>.');
}

function compute() {
  const f = ll => `${ll.lat.toFixed(5)},${ll.lng.toFixed(5)}`;
  history.replaceState(null, '', `#a=${f(A)}&b=${f(B)}`);
  say('Считаю маршрут…');
  getJSON(`/api/route?from=${f(A)}&to=${f(B)}`)
    .then(d => {
      plan = d;
      selected = d.verdict.kind === 'same' ? 'fastest' : 'better_lit';
      say('Нажмите на карточку, чтобы показать маршрут; маркеры можно перетаскивать. Ссылку из адресной строки можно отправить — она откроет тот же маршрут.');
      drawRoute();
      renderCards();
    })
    .catch(err => {
      plan = null;
      routeLayer.clearLayers();
      $('cards').innerHTML = '';
      const d = err.detail || {};
      if (d.code === 'outside_coverage') {
        say(`<span class="error">Точка ${d.point === 'from' ? 'А' : 'Б'} вне города или слишком далеко от дорожек` +
          (d.nearest_m != null ? ` (ближайшая в ${fmtM(d.nearest_m)})` : '') + '. Передвиньте маркер.</span>');
      } else {
        say(`<span class="error">Маршрут не построен: ${esc(err.message)}</span>`);
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
  if (plan.verdict.kind !== 'same') {
    const other = plan.routes[selected === 'better_lit' ? 'fastest' : 'better_lit'];
    L.polyline(lines(other), { color: '#fff', weight: 7, opacity: 0.9, interactive: false }).addTo(routeLayer);
    L.polyline(lines(other), { color: '#2b4fb3', weight: 4, dashArray: '8 6', bubblingMouseEvents: false })
      .on('click', () => select(selected === 'better_lit' ? 'fastest' : 'better_lit'))
      .addTo(routeLayer);
  }
  const cur = plan.routes[selected];
  L.polyline(lines(cur), { color: '#111', weight: 11, opacity: 0.75, interactive: false }).addTo(routeLayer);
  for (const f of cur.geometry.features) {
    const p = f.properties, s = ST[p.status] || ST.unknown;
    L.polyline(f.geometry.coordinates.map(c => [c[1], c[0]]), { color: s.c, weight: 7, dashArray: s.d, lineCap: 'butt' })
      .bindTooltip(`${esc(p.name || 'без названия')}: ${s.t}, ${fmtM(p.len)}`, { sticky: true })
      .addTo(routeLayer);
  }
  routeLayer.bringToFront();
}

function card(kind, r, title, note) {
  const by = r.by_status_m, len = r.length_m || 1;
  const bar = ORDER.filter(k => by[k] > 0).map(k => `<span style="width:${(100 * by[k] / len).toFixed(2)}%;background:${ST[k].c}" title="${ST[k].t}"></span>`).join('');
  const rows = ORDER.map(k => `<li><span class="sw" style="border-top-color:${ST[k].c};border-top-style:${ST[k].d ? (k === 'unknown' ? 'dotted' : 'dashed') : 'solid'}"></span>` +
    `${ST[k].t}: ${fmtM(by[k])} (${pct(by[k] / len)})</li>`).join('');
  const warn = r.warn
    ? `<p class="warn">Внимание: нет данных или сообщали о темноте на ${fmtM(by.unknown + by.dark_reported)} из ${fmtM(r.length_m)} (${pct(r.dark_unknown_share)})` +
      (r.max_dark_run_m > 0 ? `; самый длинный участок «сообщали, что темно» — ${fmtM(r.max_dark_run_m)}` : '') + '.</p>'
    : '';
  const via = r.streets.length ? `<p class="via">Через: ${r.streets.slice(0, 4).map(esc).join(' → ')}${r.streets.length > 4 ? ' → …' : ''}</p>` : '';
  return `<button type="button" class="card${selected === kind ? ' selected' : ''}" data-kind="${kind}" aria-pressed="${selected === kind}">` +
    `<span class="title">${title}</span><span class="main">${fmtMin(r.minutes)} · ${fmtM(r.length_m)}</span>` +
    `<span class="bar">${bar}</span><ul>${rows}</ul>${warn}${via}${note || ''}</button>`;
}

function renderCards() {
  const { fastest, better_lit: lit } = plan.routes, v = plan.verdict, s = plan.settings;
  const litShare = r => r.length_m ? r.by_status_m.lit_confirmed / r.length_m : 0;
  let html;
  if (v.kind === 'same') {
    html = card('fastest', fastest, 'Быстрый — он же самый освещённый');
  } else {
    const extra = `+${Math.max(0, v.extra_min).toString().replace('.', ',')} мин (${pct(v.extra_share)})`;
    const note = v.kind === 'too_long'
      ? `<p class="verdict bad">В продукте этот вариант скрыли бы: дольше на ${extra}, порог ${s.hide_if_extra_min} мин или ${pct(s.hide_if_extra_share)}.</p>`
      : `<p class="verdict ok">${extra} к быстрому; подтверждённо освещено ${pct(litShare(lit))} пути против ${pct(litShare(fastest))}.</p>`;
    html = card('better_lit', lit, 'Более освещённый', note) + card('fastest', fastest, 'Быстрый');
  }
  const off = [['А', plan.from], ['Б', plan.to]].filter(([, p]) => p.snap_m > 20).map(([n, p]) => `${n}: ${Math.round(p.snap_m)} м`);
  if (off.length) html += `<p class="small">От точки до ближайшей дорожки по прямой (не входит в расчёт): ${off.join(', ')}.</p>`;
  $('cards').innerHTML = html;
  for (const el of document.querySelectorAll('.card')) el.addEventListener('click', () => select(el.dataset.kind));
}

function select(kind) {
  if (!plan || !plan.routes[kind]) return;
  selected = kind;
  drawRoute();
  renderCards();
}

function readHash() {
  const m = /a=(-?[\d.]+),(-?[\d.]+)&b=(-?[\d.]+),(-?[\d.]+)/.exec(location.hash);
  if (!m) return false;
  setPoint('A', [+m[1], +m[2]]);
  setPoint('B', [+m[3], +m[4]]);
  map.fitBounds(L.latLngBounds([A, B]).pad(0.3));
  compute();
  return true;
}

// ---------- start ----------
Promise.all([getJSON('/api/summary'), getJSON(LAYERS_BASE + 'zones.geojson').catch(() => null)])
  .then(([s, zones]) => {
    summary = s;
    const [w, so, e, n] = s.bounds_wsen;
    if (!location.hash) map.fitBounds([[so, w], [n, e]]);
    if (zones) buildZones(zones);
    const g = s.groups.streets_and_sidewalks, src = s.sources;
    $('meta').innerHTML = `Улицы и тротуары города: ${g.km} км; освещено ${g.lit_confirmed}%, вероятно ${g.lit_likely}%, ` +
      `сообщали о темноте ${g.dark_reported}%, нет данных ${g.unknown}%. Данные на ${esc(s.as_of)}: OpenStreetMap ${esc((s.network.fetched_at || '').slice(0, 10))}, ` +
      `фонари Mapillary (снимки ${esc((src.mapillary.last_seen_range || []).join('…'))}), жалобы Sesizări (${esc((src.sesizari.created_range || []).join('…'))}). ` +
      `Скорость пешком ${(3.6 * (plan ? plan.settings.walk_mps : 1.35)).toFixed(1).replace('.', ',')} км/ч.`;
    if (window.ExtraLayers) {
      const ctl = L.control.layers(null, {}, { collapsed: window.innerWidth < 800, position: 'topright' }).addTo(map);
      ExtraLayers.add(map, ctl, LAYERS_BASE, { skip: ['zones'] }).then(() => routeLayer.bringToFront());
    }
    map.on('moveend', debounce(refresh, 200));
    map.on('click', onMapClick);
    $('reset').addEventListener('click', reset);
    $('net').addEventListener('change', refresh);
    for (const r of document.querySelectorAll('input[name="mode"]')) {
      r.addEventListener('change', () => {
        mode = r.value;
        map.closePopup();
        say(mode === 'route' ? (A && B ? 'Клик по карте начнёт новый маршрут.' : 'Кликните на карте точку <b>А</b>, затем точку <b>Б</b>.')
          : 'Приблизьте карту и кликните по улице: покажу, из чего сложен её цвет.');
        refresh();
      });
    }
    if (!readHash()) say('Кликните на карте точку <b>А</b>, затем точку <b>Б</b>. Приблизьте карту, чтобы увидеть освещённость улиц.');
    refresh();
  })
  .catch(err => say(`<span class="error">Сервер недоступен (${esc(err.message)}). Запустите <code>./scripts/mac/lightmap.sh api</code> и откройте эту страницу с адреса сервера.</span>`));
