'use strict';
/* bezna, phone layout of the design "Tihij svet" (claude.ai design canvas "Traseu de noapte — redesign").
   One Leaflet map under bottom sheets; screens: home, search, results, details, transit, stop (live arrival), nav.
   Data: the same backend as the desktop page: /api/route, /api/geocode, /api/segments/{id}, /api/summary, /api/transit/live.
   Texts: ../i18n.js (t, LANG, I18N) and texts.js (I18N.*.m). The Gemini box is ../ask.js, unchanged: it needs the
   globals A, labels, setPoint, setTravel, setDeparture, pointsChanged, locate and $ that are defined here. */

// ---------- helpers ----------
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const dec = x => String(x).replace('.', t('decimal'));
const km = m => dec((m / 1000).toFixed(2)) + ' km';
const dist = m => (m >= 1000 ? km(m) : Math.round(m) + ' m');
const minN = m => Math.max(1, Math.round(m));
const pct = x => Math.round(100 * x) + '%';
const clamp = x => (x < 0 ? 0 : x > 1 ? 1 : x);
const easeDraw = x => -(Math.cos(Math.PI * x) - 1) / 2;
const easeMorph = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const easeOut = x => 1 - Math.pow(1 - x, 3);
const reduced = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } };
const getJSON = (url, opts) => fetch(url, opts).then(async r => {
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error((body.detail && body.detail.message) || 'HTTP ' + r.status);
    e.detail = typeof body.detail === 'object' && !Array.isArray(body.detail) ? body.detail : {};
    e.status = r.status;
    throw e;
  }
  return body;
});
const hm = s => { const [h, m] = String(s).split(':').map(Number); return h * 60 + m; };
const fmtHM = v => { const x = ((Math.round(v) % 1440) + 1440) % 1440; return String(Math.floor(x / 60)).padStart(2, '0') + ':' + String(x % 60).padStart(2, '0'); };
const clockFmt = new Intl.DateTimeFormat('ro-RO', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Europe/Bucharest' });
const clockOf = ts => clockFmt.format(new Date(ts * 1000));
const ago = s => (s == null ? '?' : s < 60 ? t('m.agoS', { s: Math.max(0, Math.round(s)) }) : t('m.agoMS', { m: Math.floor(s / 60), s: Math.round(s % 60) }));
const fold = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const ll = coords => coords.map(c => [c[1], c[0]]);
function meters(a, b) {
  const R = 6371000, k = Math.PI / 180, dLat = (b.lat - a.lat) * k, dLon = (b.lng - a.lng) * k;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * k) * Math.cos(b.lat * k) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

// ---------- icons (inline stroke SVG, never emoji) ----------
const SV = (d, size, sw = 1.8, extra = '') => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"${extra}>${d}</svg>`;
const I = {
  back: () => SV('<path d="M15 18l-6-6 6-6"/>', 22),
  recalc: () => SV('<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v4h-4"/>', 18),
  legend: () => SV('<path d="M4 7h16"/><path d="M4 12h3M10 12h3M16 12h4"/><path d="M4 17h.01M8 17h.01M12 17h.01M16 17h.01M20 17h.01" stroke-width="2.4"/>', 18, 1.6),
  close: () => SV('<path d="M6 6l12 12M18 6 6 18"/>', 14, 2.2),
  walk: (s = 18) => SV('<circle cx="13" cy="4" r="1.6"/><path d="M9 21l2-6 3 2v4M10 9l3-1 3 3 3 1M10 9l-2 5"/>', s),
  bike: (s = 18) => SV('<circle cx="5.5" cy="17" r="3.5"/><circle cx="18.5" cy="17" r="3.5"/><path d="M5.5 17 9 9h6l3.5 8M9 9 8 6H6M12 17l3-8"/>', s),
  bus: (s = 18) => SV('<rect x="5" y="4" width="14" height="13" rx="3"/><path d="M5 11h14M9 21l1.5-4M15 21l-1.5-4"/>', s),
  clock: (s = 16) => SV('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', s),
  down: () => SV('<path d="m6 9 6 6 6-6"/>', 12, 2.4),
  check: () => SV('<path d="m5 12 5 5 9-10"/>', 16, 2.2),
  chev: (s = 14, cls = '') => SV('<path d="m9 6 6 6-6 6"/>', s, 2.2, cls ? ` class="${cls}"` : ''),
  locate: () => SV('<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>', 18),
  swap: () => SV('<path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4"/>', 18),
  building: () => SV('<path d="M4 21V5l8-3 8 3v16M9 21v-5h6v5M8 8h2M14 8h2M8 12h2M14 12h2"/>', 18),
  street: () => SV('<path d="M4 20 10 4M20 20 14 4M12 6v2M12 11v2M12 16v2"/>', 18),
  pin: () => SV('<path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z"/><circle cx="12" cy="10" r="2"/>', 16),
  stopSq: () => '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"/></svg>',
  nav: () => '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 20 21 12 17 4 21z" fill="currentColor"/></svg>',
  sound: () => SV('<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>', 20),
  flag: () => SV('<path d="M6 21V4"/><rect x="6" y="3" width="12" height="9" rx="2"/><path d="M9 7.5h6"/>', 32),
  alight: () => SV('<path d="M12 3v14M6 11l6 6 6-6"/><path d="M5 21h14"/>', 20),
  wheel: () => '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="' + esc(t('m.wheelchair')) + '"><circle cx="11" cy="4" r="1.5"/><path d="M11 7v6h5l2 5"/><path d="M8 10a6 6 0 1 0 7 8"/></svg>',
  right: s => SV('<path d="M7 21V11a4 4 0 0 1 4-4h9"/><path d="m16 3 4 4-4 4"/>', s, 2),
  left: s => SV('<path d="M17 21V11a4 4 0 0 0-4-4H4"/><path d="m8 3-4 4 4 4"/>', s, 2),
  straight: s => SV('<path d="M12 21V4"/><path d="m6 9 6-6 6 6"/>', s, 2),
  arrive: s => SV('<path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z"/><rect x="9.5" y="7.5" width="5" height="5" rx="1"/>', s, 2),
  diamond: (s = 14) => `<svg width="${s}" height="${s}" viewBox="-7 -7 14 14" aria-hidden="true"><rect x="-4.6" y="-4.6" width="9.2" height="9.2" transform="rotate(45)" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.2"/><path d="M0 -2.4V.6M0 2.3v.1" stroke="#F2F2F2" stroke-width="1.3" stroke-linecap="round"/></svg>`,
  place: (s = 12) => `<svg width="${s}" height="${s}" viewBox="-6 -6 12 12" aria-hidden="true"><circle r="4.8" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.3"/><circle r="1.6" fill="#F2F2F2"/></svg>`,
  stopMk: (s = 12) => `<svg width="${s}" height="${s}" viewBox="-6 -6 12 12" aria-hidden="true"><rect x="-4.8" y="-4.8" width="9.6" height="9.6" rx="1.8" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.3"/><rect x="-1.8" y="-1.8" width="3.6" height="3.6" fill="#F2F2F2"/></svg>`,
};
const WORDMARK = `<svg width="88" height="25" viewBox="0 -1 92 26" role="img" aria-label="bezna"><defs><filter id="zglow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="1.3"/></filter></defs><g fill="none" stroke="#F2F2F2" stroke-width="3.2"><path d="M1.6 0V24"/><circle cx="8" cy="16" r="6.4"/><path d="M21.1 16H33.9"/><path d="M33.9 16A6.4 6.4 0 1 0 32.03 20.53"/><path d="M39 9.6H51.8"/><path d="M39 22.4H51.8"/><path d="M56.9 24V8"/><path d="M56.9 16A6.4 6.4 0 0 1 69.7 16V24"/><circle cx="82.8" cy="16" r="6.4"/><path d="M89.2 8V24"/></g><path d="M50.6 11.4L40.2 20.6" stroke="#FFFFFF" stroke-width="3.2" filter="url(#zglow)" opacity="0.75"/><path d="M50.6 11.4L40.2 20.6" stroke="#FFFFFF" stroke-width="1.3" stroke-linecap="round"/></svg>`;

// ---------- lighting status: tone + line pattern (colour is never the only cue) ----------
const ST = {
  lit_confirmed: { c: '#F2F2F2', d: null, cap: 'round', alt: null, net: null, bar: null, sample: null },
  lit_likely: { c: '#D4D4D4', d: '12 6', cap: 'butt', alt: '8 5', net: '8 5', bar: '7 3', sample: '12 6' },
  unknown: { c: '#8A8A8A', d: '0.1 11', cap: 'round', alt: '0.1 7', net: '0.1 6', bar: '0.1 7', sample: '0.1 9' },
  dark_reported: { c: '#A3A3A3', d: '9 10 0.1 10', cap: 'round', alt: '6 7 0.1 7', net: '7 5 0.1 5', bar: '4 8 0.1 8', sample: '8 8 0.1 8' },
};
const ORDER = ['lit_confirmed', 'lit_likely', 'unknown', 'dark_reported'];
const LIVE_S = 60;   // an observed position younger than this is "LIVE" (design: one of five bars fades every 12 s)

function sample(status, w = 48, sw = 5) {
  const s = ST[status] || ST.unknown;
  const line = `<path d="M3 5h${w - (status === 'dark_reported' ? 18 : 6)}" stroke="${s.c}" stroke-width="${sw}"${s.sample ? ` stroke-dasharray="${s.sample}"` : ''} stroke-linecap="${s.cap}"/>`;
  const warn = status === 'dark_reported' ? `<g transform="translate(${w - 7} 7)"><rect x="-5" y="-5" width="10" height="10" transform="rotate(45)" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.2"/><path d="M0 -2.6V.6M0 2.4v.1" stroke="#F2F2F2" stroke-width="1.4" stroke-linecap="round"/></g>` : '';
  return `<svg width="${w}" height="14" viewBox="0 -2 ${w} 14" aria-hidden="true">${line}${warn}</svg>`;
}

// consecutive features with the same status, with their distance along the route
function runsOf(r) {
  const runs = [];
  let at0 = 0;
  for (const f of r.geometry.features) {
    const p = f.properties, last = runs[runs.length - 1];
    if (last && last.status === p.status) { last.len += p.len; last.to += p.len; last.feats.push(f); } else runs.push({ status: p.status, len: p.len, from: at0, to: at0 + p.len, feats: [f] });
    at0 += p.len;
  }
  return runs;
}

function statusBar(r, h = 8, sw = 4, fromM = 0) {
  const runs = runsOf(r).filter(x => x.to > fromM), L = (r.length_m - fromM) || 1;
  let x = 0, out = '';
  for (const run of runs) {
    const len = run.to - Math.max(run.from, fromM), w = 100 * len / L, s = ST[run.status] || ST.unknown;
    const a = x + (x > 0 ? 0.6 : 0), b = x + w - 0.6;
    if (b > a) out += `<line x1="${a.toFixed(1)}%" x2="${b.toFixed(1)}%" y1="${h / 2}" y2="${h / 2}" stroke="${s.c}" stroke-width="${sw}"${s.bar ? ` stroke-dasharray="${s.bar}"` : ''}${s.cap === 'round' && s.bar ? ' stroke-linecap="round"' : ''}/>`;
    x += w;
  }
  return `<svg class="sbar" width="100%" height="${h}" aria-hidden="true">${out}</svg>`;
}

const shares = r => {
  const L = r.length_m || 1;
  return ORDER.filter(k => r.by_status_m[k] > 0).map(k => t('m.share.' + k, { p: pct(r.by_status_m[k] / L) })).join(' · ');
};

// ---------- state ----------
let A = null, B = null;                       // L.LatLng; globals for ../ask.js
const labels = { A: '', B: '' };
let mode = 'walk', at = '', plan = null, sel = 'better_lit', screen = 'home', summary = null;
let routeReq = 0, legendOpen = false, langOpen = false, timeOpen = false, pickMode = null, searchFor = 'B', part = null;
let live = null, liveAt = 0, liveOff = 0, liveTimer = null, liveReq = 0;
let anim = null, quietReveal = false, restoreTo = null;   // quietReveal: back from a language switch, no replay
const seen = new Set();
const prefs = { net: true, livenet: false };

// ---------- map ----------
const map = L.map('map', { zoomControl: false, attributionControl: true, zoomSnap: 0.25 }).setView([45.7500, 21.2270], 14);
map.attributionControl.setPrefix('');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'bz-tiles',
  attribution: '&copy; OpenStreetMap · Mapillary · Primăria Timișoara · ' +
    '<a href="https://www.flaticon.com/free-icons/street-light" title="street light icons" target="_blank" rel="noopener">Icon: Magnific – Flaticon</a>' }).addTo(map);
const svgR = L.svg({ padding: 0.5 });
const netR = L.canvas({ padding: 0.3, tolerance: 6 });
const areaLayer = L.layerGroup().addTo(map);
const netLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const fadeLayer = L.layerGroup().addTo(map);   // a drawing that is fading out, above the new one
const lifeLayer = L.layerGroup().addTo(map);
const markLayer = L.layerGroup().addTo(map);
const abLayer = L.layerGroup().addTo(map);
const vehLayer = L.layerGroup().addTo(map);
const meLayer = L.layerGroup().addTo(map);

const divIcon = (html, w, h, cls = '') => L.divIcon({ className: 'bz-mk ' + cls, html, iconSize: [w, h], iconAnchor: [w / 2, h / 2] });
const MK = {
  A: () => divIcon('<svg width="28" height="28" viewBox="-14 -14 28 28"><circle r="11" fill="#F2F2F2" stroke="#0B0B0B" stroke-width="3"/><text y="4.5" text-anchor="middle" font-size="12.5" fill="#0B0B0B">A</text></svg>', 28, 28),
  B: () => divIcon('<svg width="28" height="28" viewBox="-14 -14 28 28"><rect x="-11" y="-11" width="22" height="22" rx="3" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="2"/><text y="4.5" text-anchor="middle" font-size="12.5" fill="#F2F2F2">B</text></svg>', 28, 28),
  me: heading => divIcon(`<svg width="64" height="64" viewBox="-32 -32 64 64">${heading != null ? `<path d="M0 4 L-12 -24 A 26 26 0 0 1 12 -24 Z" fill="url(#bzcone)" transform="rotate(${heading})"/>` : ''}<circle r="30" fill="url(#bzhalo)"/><circle r="10" fill="none" stroke="#F2F2F2" stroke-opacity="0.35"/><circle r="7" fill="#F2F2F2" stroke="#0B0B0B" stroke-width="2.5"/></svg>`, 64, 64),
  // the fade-in runs on an inner element: Leaflet positions the icon itself with a transform
  place: n => divIcon(`<span class="mk-in">${n ? `<svg width="22" height="22" viewBox="-11 -11 22 22"><circle r="8.5" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.5"/><text y="3.5" text-anchor="middle" font-size="10" fill="#F2F2F2">${n}</text></svg>` : I.place(14)}</span>`, n ? 22 : 14, n ? 22 : 14),
  stop: n => divIcon(`<span class="mk-in">${n ? `<svg width="22" height="22" viewBox="-11 -11 22 22"><rect x="-8.5" y="-8.5" width="17" height="17" rx="3" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.5"/><text y="3.5" text-anchor="middle" font-size="10" fill="#F2F2F2">${n}</text></svg>` : I.stopMk(14)}</span>`, n ? 22 : 14, n ? 22 : 14),
  warn: () => divIcon('<svg width="22" height="22" viewBox="-11 -11 22 22"><rect x="-7.5" y="-7.5" width="15" height="15" transform="rotate(45)" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="1.5"/><path d="M0 -4.2V1.2M0 3.6v.2" stroke="#F2F2F2" stroke-width="1.8" stroke-linecap="round"/></svg>', 22, 22),
  ring: () => divIcon('<svg width="36" height="36" viewBox="-18 -18 36 36"><circle r="16" fill="none" stroke="#F2F2F2" stroke-width="1.5" stroke-dasharray="3 3"/></svg>', 36, 36),
  head: () => divIcon('<svg width="34" height="34" viewBox="-17 -17 34 34"><circle r="16" fill="url(#bzhead)"/><circle r="4" fill="#FFFFFF"/></svg>', 34, 34),
  station: () => divIcon('<svg width="20" height="20" viewBox="-10 -10 20 20"><circle r="7.5" fill="#0B0B0B" stroke="#F2F2F2" stroke-width="2"/></svg>', 20, 20),
  vehicle: (v, mine, old) => {
    const w = Math.max(34, 12 + 9 * String(v.line).length), arrow = typeof v.bearing === 'number' && !old;
    const body = old
      ? `<rect x="${-w / 2}" y="-12" width="${w}" height="24" rx="6" fill="#0B0B0B" stroke="#A3A3A3" stroke-width="1.5" stroke-dasharray="3 2.5"/><text y="5" text-anchor="middle" font-size="14" fill="#A3A3A3">${esc(v.line)}</text>`
      : `${mine ? '<circle r="22" fill="none" stroke="#F2F2F2" stroke-width="1.2" class="bz-pulse"/>' : ''}<rect x="${-w / 2}" y="-12" width="${w}" height="24" rx="6" fill="#F2F2F2" stroke="#0B0B0B" stroke-width="2"/><text y="5" text-anchor="middle" font-size="14" fill="#0B0B0B">${esc(v.line)}</text>`;
    const tri = arrow ? `<path d="M0 -25 L-7 -15 L7 -15 Z" fill="#F2F2F2" stroke="#0B0B0B" stroke-width="1" transform="rotate(${v.bearing})"/>` : '';
    return divIcon(`<svg width="64" height="64" viewBox="-32 -32 64 64" style="opacity:${mine || old ? 1 : 0.85}">${tri}${body}</svg>`, 64, 64);
  },
};

function phoneRect() { return $('phone').getBoundingClientRect(); }
function fit(bounds, maxZoom = 17) {
  const P = phoneRect(), sheet = document.querySelector('#screen .sheet');
  const topEl = document.querySelector('#screen .top, #screen .stopcard, #screen .manoeuvre');
  let top = topEl ? topEl.getBoundingClientRect().bottom - P.top : 12;
  let bottom = sheet ? P.bottom - sheet.getBoundingClientRect().top : 0;
  if (top + bottom > P.height - 120) bottom = Math.max(0, P.height - 120 - top);
  map.invalidateSize();
  map.fitBounds(bounds, { paddingTopLeft: [28, top + 16], paddingBottomRight: [28, bottom + 16], maxZoom, animate: false });
}

// ---------- the area and the faint lighting network (start screen) ----------
let netReq = 0;
function refreshNet() {
  if (!summary || !prefs.net || screen !== 'home' || map.getZoom() < 13) { netReq++; netLayer.clearLayers(); return; }
  const b = map.getBounds().pad(0.15), req = ++netReq;
  getJSON(`/api/segments?bbox=${b.getWest().toFixed(5)},${b.getSouth().toFixed(5)},${b.getEast().toFixed(5)},${b.getNorth().toFixed(5)}&limit=8000`)
    .then(d => {
      if (req !== netReq) return;
      netLayer.clearLayers();
      if (d.truncated) return;
      for (const k of ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported']) {
        const s = ST[k], lines = d.features.filter(f => f.properties.status === k).map(f => ll(f.geometry.coordinates));
        if (lines.length) L.polyline(lines, { renderer: netR, color: s.c, weight: k === 'unknown' ? 3 : k === 'dark_reported' ? 2.5 : 2, opacity: 0.42, dashArray: s.net, lineCap: s.cap, interactive: false }).addTo(netLayer);
      }
    })
    .catch(() => {});
}

// ---------- points ----------
function setPoint(which, latlng, label) {
  const p = L.latLng(latlng);
  if (which === 'A') A = p; else B = p;
  labels[which] = label || t('m.pointOnMap');
  drawAB();
  if (screen === 'home') renderHome();
  syncSearchFields();
}
function drawAB() {
  abLayer.clearLayers();
  if (A && !(screen === 'nav')) L.marker(A, { icon: MK.A(), keyboard: false, interactive: false }).addTo(abLayer);
  if (B) L.marker(B, { icon: MK.B(), keyboard: false, interactive: false }).addTo(abLayer);
}
function setTravel(m) { mode = m; if (screen === 'home') renderHome(); }
function setDeparture(v) { at = v || ''; if (screen === 'home') renderHome(); }
function pointsChanged() { if (B) compute(); else openSearch('B'); }

let myPos = null;
function showMe(lat, lon, heading) {
  myPos = L.latLng(lat, lon);
  meLayer.clearLayers();
  L.marker(myPos, { icon: MK.me(heading), keyboard: false, interactive: false }).addTo(meLayer);
}
function locate(thenCompute = true) {
  if (!navigator.geolocation) { toast(t('m.noGeo')); openSearch('A'); return; }
  toast(t('locating'), 4000);
  navigator.geolocation.getCurrentPosition(pos => {
    hideToast();
    showMe(pos.coords.latitude, pos.coords.longitude);
    setPoint('A', [pos.coords.latitude, pos.coords.longitude], t('myLocation'));
    if (thenCompute && B) compute(); else if (screen === 'home') map.setView(A, Math.max(map.getZoom(), 16));
  }, err => {
    toast(t('geoError', { msg: err.message }));
    openSearch('A');
  }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
}

// ---------- link to this route (#a=…&b=…), so a reload or a language switch keeps it ----------
function saveHash() {
  const f = p => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`, h = new URLSearchParams();
  if (A) { h.set('a', f(A)); h.set('an', labels.A); }
  if (B) { h.set('b', f(B)); h.set('bn', labels.B); }
  h.set('m', mode);
  if (at) h.set('at', at);
  history.replaceState(history.state, '', location.pathname + location.search + '#' + h.toString().replace(/%2C/g, ',').replace(/%3A/g, ':'));
}
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  const point = v => { const m = /^(-?[\d.]+),(-?[\d.]+)$/.exec(v || ''); return m ? [+m[1], +m[2]] : null; };
  if (['walk', 'bike', 'transit'].includes(h.get('m'))) mode = h.get('m');
  if (h.get('at')) at = h.get('at');
  const a = point(h.get('a')), b = point(h.get('b'));
  if (a) setPoint('A', a, h.get('an'));
  if (b) setPoint('B', b, h.get('bn'));
  return !!(a && b);
}

// ---------- screens ----------
const SCREENS = {};
function go(name, push = true) {
  closeOverlays();
  if (screen === 'nav' && name !== 'nav') stopNav();
  if (name !== 'results') stopAnim();
  screen = name;
  $('scr-search').hidden = name !== 'search';
  $('screen').hidden = name === 'search';
  if (name !== 'search') SCREENS[name]();
  if (push) history.pushState({ screen: name }, '');
  drawAB();
  refreshNet();
  liveTick();
}
window.addEventListener('popstate', e => {
  const want = (e.state && e.state.screen) || 'home';
  go(want !== 'home' && !plan && want !== 'search' ? 'home' : want, false);
});

// actions: data-act on any element in the screen or the overlays
const ACT = {};
function onAct(e) {
  const el = e.target.closest('[data-act]');
  if (!el || !ACT[el.dataset.act]) return;
  e.preventDefault();
  ACT[el.dataset.act](el, e);
}
$('screen').addEventListener('click', onAct);
$('overlay').addEventListener('click', onAct);
document.addEventListener('click', e => {
  if (langOpen && !e.target.closest('.menu, #lang-btn')) { langOpen = false; renderOverlay(); }
}, true);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && (langOpen || legendOpen || tip || aboutOpen || $('tp'))) { closeOverlays(); }
});

ACT.home = () => { stopLive(); go('home'); };
ACT.lang = () => { langOpen = !langOpen; renderOverlay(); };
ACT.setLang = el => {
  const code = el.dataset.lang;
  langOpen = false;
  if (code === LANG) { renderOverlay(); return; }
  // the page reloads in the new language: come back to the same screen, without replaying the animation
  try { sessionStorage.setItem('bz.back', JSON.stringify({ screen: screen === 'search' ? 'home' : screen, sel })); } catch (e) { /* storage blocked */ }
  saveHash();
  switchLang(code);
};
ACT.legend = () => { legendOpen = !legendOpen; renderOverlay(); };
ACT.about = () => { openAbout(); };
ACT.closeOverlay = () => closeOverlays();
ACT.searchA = () => openSearch('A');
ACT.searchB = () => openSearch('B');
ACT.locate = () => locate(true);
ACT.swap = () => {
  const old = { A, B, la: labels.A, lb: labels.B };
  A = old.B; B = old.A; labels.A = old.lb; labels.B = old.la;
  drawAB();
  if (A && B && screen !== 'home') compute(); else renderHome();
};
ACT.mode = el => {
  mode = el.dataset.mode;
  if (screen === 'home') renderHome(); else if (A && B) compute();
};
ACT.time = () => openTimePicker();
ACT.tpNow = () => { at = ''; closeTimePicker(true); };
ACT.tpDone = () => { const v = tpValue(); at = `${pad2(v.h)}:${pad2(v.m)}`; closeTimePicker(true); };
ACT.tpCancel = () => closeTimePicker(false);
ACT.net = el => { prefs.net = el.checked; refreshNet(); };
ACT.livenet = el => { prefs.livenet = el.checked; liveTick(); };

// ---------- start screen ----------
SCREENS.home = renderHome;
function renderHome() {
  if (screen !== 'home') return;
  const aLabel = A ? labels.A : t('m.myLocation');
  const timeLabel = at ? (at.includes('T') ? at.slice(11, 16) : at) : t('m.now');
  $('screen').innerHTML = `
  <div class="top" style="justify-content: space-between">
    <div class="brand">${WORDMARK}<span class="sec">${esc(t('m.tagline'))}</span></div>
    <div style="display: flex; gap: 8px">
      <button type="button" class="pill mono" data-act="lang" id="lang-btn" aria-haspopup="menu" aria-expanded="${langOpen}" aria-label="${esc(t('m.langBtn'))}" style="font-size: 12px; letter-spacing: .04em; padding: 0 12px; gap: 6px">${LANG.toUpperCase()}${I.down()}</button>
      <button type="button" class="round" data-act="legend" aria-expanded="${legendOpen}" aria-label="${esc(t('m.legendLayers'))}">${I.legend()}</button>
    </div>
  </div>
  <div class="note-chip"><svg width="22" height="6" viewBox="0 0 22 6" aria-hidden="true"><path d="M1 3h20" stroke="#A3A3A3" stroke-width="1" stroke-dasharray="2 4"/></svg><span>${esc(t('m.coverage'))}</span></div>
  <section class="sheet" aria-labelledby="h-home">
    <div class="handle"></div>
    <div style="display: flex; flex-direction: column; gap: 4px"><h1 id="h-home" class="h-title">${esc(t('m.where'))}</h1><p class="h-sub">${esc(t('m.whereSub'))}</p></div>
    <div class="fields">
      <div class="fields-col">
        <div class="field"><span class="pin-a" aria-hidden="true">A</span>
          <button type="button" class="fbtn" data-act="searchA" aria-label="${esc(t('fromLabel') + ': ' + aLabel)}">${esc(aLabel)}</button>
          <button type="button" class="icon-in" data-act="locate" aria-label="${esc(t('locate'))}" style="color: var(--bz-ink-2)">${I.locate()}</button></div>
        <button type="button" class="field" data-act="searchB" aria-label="${esc(t('toLabel') + (B ? ': ' + labels.B : ''))}"><span class="pin-b" aria-hidden="true">B</span>
          <span class="${B ? 'val' : 'ph'}">${esc(B ? labels.B : t('toPlaceholder'))}</span></button>
      </div>
      <button type="button" class="swap" data-act="swap" aria-label="${esc(t('swap'))}">${I.swap()}</button>
    </div>
    ${modeSeg('')}
    <div class="row">
      <button type="button" class="chip-btn" data-act="time" aria-haspopup="dialog">${I.clock()}<span>${esc(t('m.leave'))}: <strong>${esc(timeLabel)}</strong></span>${I.down()}</button>
      <button type="button" class="link-btn" data-act="about">${esc(t('m.aboutData'))}</button>
    </div>
    <p class="small" style="margin-top: auto">${esc(t('m.footer', { date: summary ? summary.as_of.split('-').reverse().join('.') : '…' }))}</p>
  </section>`;
}

function modeSeg(cls) {
  const b = (m, icon, key) => `<button type="button" data-act="mode" data-mode="${m}" aria-pressed="${mode === m}">${icon}${esc(t(key))}</button>`;
  return `<div class="seg ${cls}" role="group" aria-label="${esc(t('travelLabel'))}">${b('walk', I.walk(cls ? 16 : 18), 'm.walk')}${b('bike', I.bike(cls ? 16 : 18), 'm.bike')}${b('transit', I.bus(cls ? 16 : 18), 'm.transit')}</div>`;
}

// ---------- search (built once: ../ask.js binds to its Gemini form) ----------
let sItems = [], sActive = 0, sReq = 0, sTimer = null;
function buildSearch() {
  $('scr-search').innerHTML = `
  <div class="s-head">
    <div class="s-title"><button type="button" class="back" id="s-back" aria-label="${esc(t('m.backMap'))}">${I.back()}</button><h1 id="s-h1"></h1></div>
    <label class="field"><span class="pin-a" aria-hidden="true">A</span><input id="from" type="text" autocomplete="off" spellcheck="false" enterkeyhint="search" aria-label="${esc(t('fromLabel'))}" aria-controls="s-list" aria-autocomplete="list"><button type="button" class="icon-in" data-clear="from" aria-label="${esc(t('m.clear'))}"><span class="clear-x">${I.close()}</span></button></label>
    <label class="field"><span class="pin-b" aria-hidden="true">B</span><input id="to" type="text" autocomplete="off" spellcheck="false" enterkeyhint="search" aria-label="${esc(t('toLabel'))}" aria-controls="s-list" aria-autocomplete="list"><button type="button" class="icon-in" data-clear="to" aria-label="${esc(t('m.clear'))}"><span class="clear-x">${I.close()}</span></button></label>
    <form class="ask" id="ask" hidden>
      <div class="ask-row"><input id="ask-text" type="text" maxlength="300" autocomplete="off" enterkeyhint="go"><button type="button" id="ask-mic" aria-pressed="false"></button><button type="submit" id="ask-go"></button></div>
      <p id="ask-note" aria-live="polite" hidden></p>
      <p class="small" id="ask-privacy"></p>
    </form>
  </div>
  <div class="s-meta"><span class="label" id="s-count"></span><span class="mono small" id="s-from"></span></div>
  <ul class="s-list" id="s-list" role="listbox" aria-label="${esc(t('m.suggestions'))}"></ul>
  <section class="help" aria-labelledby="s-help"><h2 id="s-help" style="font-size: 14px; font-weight: 600">${esc(t('m.helpTitle'))}</h2>
    <p class="sec">${esc(t('m.helpText'))}</p>
    <button type="button" class="link-btn" id="s-pick" style="gap: 8px; font-size: 14px">${I.pin()}<span id="s-pick-text"></span></button></section>
  <p class="small" style="margin: auto 16px 18px; padding-top: 16px">${esc(t('m.searchPrivacy'))}</p>`;
  $('s-back').addEventListener('click', () => history.length > 1 ? history.back() : go('home'));
  $('s-pick').addEventListener('click', () => { pickMode = searchFor; go('home'); toast(t('m.tapMap', { p: searchFor }), 0); });
  for (const id of ['from', 'to']) {
    const inp = $(id);
    inp.addEventListener('focus', () => { searchFor = id === 'from' ? 'A' : 'B'; $('s-h1').textContent = t(searchFor === 'A' ? 'm.chooseStart' : 'm.chooseDest'); $('s-pick-text').textContent = t('m.tapMapLink', { p: searchFor }); sQuery(); });
    inp.addEventListener('input', () => { clearTimeout(sTimer); sTimer = setTimeout(sQuery, 150); });
    inp.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (sItems.length) { sActive = (sActive + (e.key === 'ArrowDown' ? 1 : -1) + sItems.length) % sItems.length; sRender(); } }
      else if (e.key === 'Enter') { e.preventDefault(); if (sItems[sActive]) sPick(sItems[sActive]); }
      else if (e.key === 'Escape') { history.back(); }
    });
  }
  for (const b of $('scr-search').querySelectorAll('[data-clear]')) b.addEventListener('click', e => { e.preventDefault(); const inp = $(b.dataset.clear); inp.value = ''; inp.focus(); sQuery(); });
  $('s-list').addEventListener('mousedown', e => e.preventDefault());
  $('s-list').addEventListener('click', e => { const li = e.target.closest('li[data-i]'); if (li) sPick(sItems[+li.dataset.i]); });
}
function syncSearchFields() {
  if (!$('from')) return;
  if (document.activeElement !== $('from')) $('from').value = A ? labels.A : '';
  if (document.activeElement !== $('to')) $('to').value = B ? labels.B : '';
}
function openSearch(which) {
  searchFor = which;
  go('search');
  syncSearchFields();
  const inp = $(which === 'A' ? 'from' : 'to');
  inp.focus();
  inp.select();
}
function sDetail(r) {
  if (r.kind === 'gps') return t('m.gpsDetail');
  if (r.number_missing) return t('numberMissing', { n: r.number_missing });
  if (r.kind === 'stop') return r.detail ? t('stopLines', { lines: r.detail }) : t('kindLabel.stop');
  if (r.kind === 'place' && r.detail) { const c = t('cat.' + r.detail); return c === 'cat.' + r.detail ? t('kindLabel.place') : c; }
  return t('kindLabel.' + r.kind);
}
function sIcon(r) {
  if (r.kind === 'gps') return I.locate();
  if (r.kind === 'stop') return I.bus();
  if (r.kind === 'street') return I.street();
  return I.building();
}
// the typed words in bold: "camin c1" -> **Căminul C1**0 UPT (a word that only adds an ending is bold whole)
function boldMatch(name, q) {
  const tokens = fold(q).split(/[^a-z0-9]+/).filter(Boolean);
  return name.split(/(\s+)/).map(word => {
    const w = fold(word), tok = tokens.find(x => w.startsWith(x));
    if (!tok || w.length !== word.length) return esc(word);
    const n = w.length - tok.length <= 2 ? word.length : tok.length;
    return '<strong>' + esc(word.slice(0, n)) + '</strong>' + esc(word.slice(n));
  }).join('');
}
function sQuery() {
  const inp = $(searchFor === 'A' ? 'from' : 'to'), q = inp.value.trim(), mine = ++sReq;
  const gps = searchFor === 'A' ? [{ kind: 'gps', name: t('myLocation') }] : [];
  if (q.length < 2) { sItems = gps; sActive = 0; sRender(q); return; }
  fetch('/api/geocode?limit=8&q=' + encodeURIComponent(q))
    .then(r => (r.ok ? r.json() : { results: [] }))
    .then(d => { if (mine === sReq) { sItems = gps.concat(d.results || []); sActive = gps.length && sItems.length > 1 ? 1 : 0; sRender(q); } })
    .catch(() => {});
}
function sRender(q = '') {
  const real = sItems.filter(r => r.kind !== 'gps').length;
  $('s-count').textContent = q.length >= 2 ? t('m.results', { n: real }) : '';
  $('s-from').textContent = A && searchFor === 'B' && real ? t('m.distFromA') : '';
  $('s-list').innerHTML = sItems.map((r, i) => {
    const d = A && r.kind !== 'gps' && searchFor === 'B' ? dist(meters(A, L.latLng(r.lat, r.lon))) : '';
    return `<li role="option" id="s-opt-${i}" data-i="${i}" aria-selected="${i === sActive}"><span class="ic">${sIcon(r)}</span>` +
      `<span style="display: flex; flex-direction: column; gap: 2px; min-width: 0"><span class="nm">${r.kind === 'gps' ? esc(r.name) : boldMatch(r.name, q)}</span><span class="dt">${esc(sDetail(r))}</span></span>` +
      `<span class="km">${esc(d)}</span></li>`;
  }).join('') + (q.length >= 2 && !real ? `<li aria-disabled="true" style="cursor: default"><span class="ic">${I.pin()}</span><span class="dt">${esc(t('noResults'))}</span><span></span></li>` : '');
  const inp = $(searchFor === 'A' ? 'from' : 'to');
  if (sItems.length) inp.setAttribute('aria-activedescendant', 's-opt-' + sActive); else inp.removeAttribute('aria-activedescendant');
}
function sPick(r) {
  if (!r) return;
  if (r.kind === 'gps') { go(B ? 'home' : 'search', false); locate(true); if (!B) openSearch('B'); return; }
  setPoint(searchFor, [r.lat, r.lon], r.name);
  $(searchFor === 'A' ? 'from' : 'to').value = r.name;
  if (searchFor === 'A') { if (B) compute(); else openSearch('B'); return; }
  if (A) compute(); else locate(true);
}

// ---------- computing a route ----------
function compute() {
  if (!B) { openSearch('B'); return; }
  if (!A) { locate(true); return; }
  const f = p => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`, req = ++routeReq;
  saveHash();
  stopAnim(); stopLive();
  plan = null; part = null;
  routeLayer.clearLayers(); markLayer.clearLayers(); lifeLayer.clearLayers(); vehLayer.clearLayers();
  go(mode === 'transit' ? 'transit' : 'results');
  fit(L.latLngBounds([A, B]).pad(0.2));
  getJSON(`/api/route?from=${f(A)}&to=${f(B)}&mode=${mode}${at ? '&at=' + encodeURIComponent(at) : ''}`)
    .then(d => {
      if (req !== routeReq) return;
      plan = d; live = null;
      if (mode === 'transit' && d.transit && d.transit.kind === 'ok') { sel = 'transit'; go('transit', false); }
      else { if (screen !== 'results') go('results', false); reveal(false); }
      const rt = restoreTo;
      restoreTo = null;
      if (rt && ['details', 'stop'].includes(rt.screen)) {
        if (rt.sel && plan.routes[rt.sel]) sel = rt.sel;
        if (rt.screen === 'details' || ride()) go(rt.screen);
      } else if (rt && rt.screen === 'results' && rt.sel && plan.routes[rt.sel] && rt.sel !== sel) pick(rt.sel);
    })
    .catch(err => {
      if (req !== routeReq) return;
      const d = err.detail || {};
      let text;
      if (d.code === 'outside_coverage') {
        const near = d.nearest_m != null ? t('nearest', { d: dist(d.nearest_m) }) : '';
        text = t(mode === 'bike' ? 'outsideBike' : 'outside', { p: d.point === 'from' ? 'A' : 'B', near });
      } else {
        const key = 'err.' + (d.code === 'no_route' ? 'no_route_' + (mode === 'bike' ? 'bike' : 'walk') : d.code);
        text = d.code && t(key) !== key ? t(key) : t('err.other', { code: d.code || err.message });
      }
      go('home');
      toast(text);
    });
}
const leaveHM = () => (plan ? plan.at.slice(11, 16) : '');
// "+N min" between the two cards: the difference of the minutes the cards show, so 19 and 21 never read "+1"
const extraMin = () => Math.max(0, Math.round(plan.routes.better_lit.minutes) - Math.round(plan.routes.fastest.minutes));
const lifeText = sg => [t(sg.open_places.length === 1 ? 'm.lifeOpen1' : 'm.lifeOpen', { n: sg.open_places.length }),
  t(sg.stops.length === 1 ? 'm.lifeStops1' : 'm.lifeStops', { n: sg.stops.length })].join(' · ');
function fitPlan() {
  if (!plan) return;
  const all = plan.verdict.kind === 'same' ? pts(plan.routes[plan.verdict.pick || 'fastest']) : pts(plan.routes.fastest).concat(pts(plan.routes.better_lit));
  fit(L.latLngBounds(all).pad(0.08));
}
const arriveHM = r => fmtHM(hm(leaveHM()) + r.minutes);
const routeTitle = kind => (plan && plan.verdict.kind === 'same' ? t(plan.verdict.pick === 'better_lit' ? 'm.litSame' : 'm.fastestOne') : t(kind === 'fastest' ? 'm.fastest' : 'm.litter'));

// ---------- drawing routes ----------
function drawMain(r, kind, layer = routeLayer, hit = true) {  // eslint-disable-line no-unused-vars
  const lines = r.geometry.features.map(f => ll(f.geometry.coordinates));
  L.polyline(lines, { renderer: svgR, color: '#F2F2F2', weight: 10, opacity: 0.32, className: 'bz-glow', interactive: false, lineJoin: 'round', lineCap: 'round' }).addTo(layer);
  L.polyline(lines, { renderer: svgR, color: '#0B0B0B', weight: 12, opacity: 1, interactive: false, lineJoin: 'round', lineCap: 'round' }).addTo(layer);
  for (const f of r.geometry.features) {
    const s = ST[f.properties.status] || ST.unknown, pts = ll(f.geometry.coordinates);
    L.polyline(pts, { renderer: svgR, color: s.c, weight: 6, opacity: 1, dashArray: s.d, lineCap: s.cap, lineJoin: 'round', interactive: false }).addTo(layer);
    if (hit) L.polyline(pts, { renderer: svgR, weight: 24, opacity: 0, bubblingMouseEvents: false }).on('click', e => openTip(f, kind, e.latlng)).addTo(layer);
  }
}
function drawAlt(r, kind, layer = routeLayer, opacity = 0.8) {
  const lines = r.geometry.features.map(f => ll(f.geometry.coordinates)), out = [];
  out.push(L.polyline(lines, { renderer: svgR, color: '#0B0B0B', weight: 8, opacity: Math.min(1, opacity / 0.8), interactive: false, lineJoin: 'round', lineCap: 'round' }).addTo(layer));
  for (const f of r.geometry.features) {
    const s = ST[f.properties.status] || ST.unknown;
    out.push(L.polyline(ll(f.geometry.coordinates), { renderer: svgR, color: s.c, weight: 3, opacity, dashArray: s.alt, lineCap: s.cap, lineJoin: 'round', interactive: false }).addTo(layer));
  }
  L.polyline(lines, { renderer: svgR, weight: 22, opacity: 0, bubblingMouseEvents: false }).on('click', () => pick(kind)).addTo(layer);
  return out;
}
function midOf(f) {
  const c = f.geometry.coordinates;
  return L.latLng(c[Math.floor(c.length / 2)][1], c[Math.floor(c.length / 2)][0]);
}
function drawWarnings(routes) {
  for (const r of routes) for (const f of r.geometry.features) {
    if (f.properties.status === 'dark_reported') L.marker(midOf(f), { icon: MK.warn(), interactive: false, keyboard: false }).addTo(markLayer);
  }
}
function drawRoutes(keepOld) {
  if (!keepOld) routeLayer.clearLayers();
  markLayer.clearLayers();
  const v = plan.verdict, r = plan.routes[sel], otherKind = sel === 'fastest' ? 'better_lit' : 'fastest';
  const other = v.kind === 'same' ? null : plan.routes[otherKind];
  if (other) drawAlt(other, otherKind);
  drawMain(r, sel);
  drawWarnings([r, other].filter(Boolean));
  drawLife(r.signs, false);
}
function drawLife(sg, numbered) {
  lifeLayer.clearLayers();
  if (!sg) return;
  let n = 0;
  for (const p of sg.open_places) L.marker([p.lat, p.lon], { icon: MK.place(numbered ? ++n : 0), keyboard: false, title: p.name }).addTo(lifeLayer);
  for (const s of sg.stops) if (s.lat != null) L.marker([s.lat, s.lon], { icon: MK.stop(numbered ? ++n : 0), keyboard: false, title: s.name }).addTo(lifeLayer);
}

// ---------- the reveal: fastest draws itself, then bends into the better-lit route (once per new calculation) ----------
const MOTION = { draw: 900, pause: 250, morph: 800, spread: 80 };
const pts = r => {
  const out = [];
  for (const f of r.geometry.features) for (const c of f.geometry.coordinates) {
    const p = L.latLng(c[1], c[0]), last = out[out.length - 1];
    if (!last || last.lat !== p.lat || last.lng !== p.lng) out.push(p);
  }
  return out;
};
const lenOf = ps => { let s = 0; for (let i = 1; i < ps.length; i++) s += meters(ps[i - 1], ps[i]); return s; };
function cut(ps, len) {
  if (len <= 0 || !ps.length) return ps.slice(0, 1);
  const out = [ps[0]];
  let acc = 0;
  for (let i = 1; i < ps.length; i++) {
    const d = meters(ps[i - 1], ps[i]);
    if (acc + d >= len) { const k = d ? (len - acc) / d : 1; out.push(L.latLng(ps[i - 1].lat + (ps[i].lat - ps[i - 1].lat) * k, ps[i - 1].lng + (ps[i].lng - ps[i - 1].lng) * k)); return out; }
    out.push(ps[i]); acc += d;
  }
  return out;
}
function resample(ps, n) {
  const total = lenOf(ps), out = [];
  for (let i = 0; i < n; i++) { const c = cut(ps, total * i / (n - 1)); out.push(c[c.length - 1]); }
  return out;
}
function branches(fast, lit) {
  const same = (a, b) => Math.abs(a.lat - b.lat) < 1e-7 && Math.abs(a.lng - b.lng) < 1e-7;
  let i = 0;
  while (i < fast.length && i < lit.length && same(fast[i], lit[i])) i++;
  let j = 0;
  while (j < fast.length - i && j < lit.length - i && same(fast[fast.length - 1 - j], lit[lit.length - 1 - j])) j++;
  const s = Math.max(0, i - 1);
  return { head: fast.slice(0, i), tail: fast.slice(fast.length - j), fb: fast.slice(s, fast.length - j + (j ? 1 : 0)), lb: lit.slice(s, lit.length - j + (j ? 1 : 0)) };
}
const calcKey = () => [plan.from.lat, plan.from.lon, plan.to.lat, plan.to.lon, plan.mode, plan.at, plan.routes.fastest.length_m, plan.routes.better_lit.length_m].join('|');

// cumulative distance along a point list, so a frame cuts the line with a binary search instead of re-measuring it
function cumOf(ps) { const c = [0]; for (let i = 1; i < ps.length; i++) c.push(c[i - 1] + meters(ps[i - 1], ps[i])); return c; }
function cutC(ps, cum, len) {
  if (len <= 0) return ps.slice(0, 1);
  if (len >= cum[cum.length - 1]) return ps.slice();
  let lo = 0, hi = cum.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] <= len) lo = m; else hi = m; }
  const k = (len - cum[lo]) / ((cum[hi] - cum[lo]) || 1), a = ps[lo], b = ps[hi];
  return ps.slice(0, lo + 1).concat([L.latLng(a.lat + (b.lat - a.lat) * k, a.lng + (b.lng - a.lng) * k)]);
}
// a light trail while it moves: a wide translucent stroke instead of the blur filter, which is too slow to redraw every frame
const trail = () => ({
  glow: L.polyline([], { renderer: svgR, color: '#F2F2F2', weight: 16, opacity: 0.12, interactive: false, lineJoin: 'round', lineCap: 'round' }).addTo(routeLayer),
  cas: L.polyline([], { renderer: svgR, color: '#0B0B0B', weight: 12, interactive: false, lineJoin: 'round', lineCap: 'round' }).addTo(routeLayer),
  line: L.polyline([], { renderer: svgR, color: '#F2F2F2', weight: 6, interactive: false, lineJoin: 'round', lineCap: 'round' }).addTo(routeLayer),
});
const setTrail = (g, ll) => { g.glow.setLatLngs(ll); g.cas.setLatLngs(ll); g.line.setLatLngs(ll); };
// the old drawing fades away on top of the new one, so a stage change never flashes
function fadeOut(layers, ms = 300) {
  for (const l of layers) { routeLayer.removeLayer(l); l.addTo(fadeLayer); }
  requestAnimationFrame(() => requestAnimationFrame(() => {
    for (const l of layers) if (l._path) { l._path.style.transition = `opacity ${ms}ms cubic-bezier(.33,1,.68,1)`; l._path.style.opacity = '0'; }
  }));
  setTimeout(() => layers.forEach(l => fadeLayer.removeLayer(l)), ms + 80);
}

function reveal(force) {
  stopAnim();
  const v = plan.verdict, final = v.kind === 'same' ? (v.pick || 'fastest') : v.kind === 'too_long' ? 'fastest' : 'better_lit', key = calcKey();
  if ((!force && (seen.has(key) || quietReveal)) || reduced()) { seen.add(key); quietReveal = false; sel = final; finishReveal(); fitPlan(); return; }
  seen.add(key);
  const fast = plan.routes.fastest, fastPts = pts(fast), morph = v.kind === 'show', cum = cumOf(fastPts);
  routeLayer.clearLayers(); markLayer.clearLayers(); lifeLayer.clearLayers(); fadeLayer.clearLayers();
  const g = trail();
  const head = L.marker(fastPts[0], { icon: MK.head(), interactive: false, keyboard: false }).addTo(markLayer);
  anim = { t0: performance.now(), raf: 0, final, morph, fastPts, cum, L: cum[cum.length - 1], g, head, stage: 0, end: morph ? MOTION.draw + MOTION.pause + MOTION.morph + MOTION.spread : MOTION.draw + 300 };
  if (morph) {
    const br = branches(fastPts, pts(plan.routes.better_lit)), N = 64;
    Object.assign(anim, { br, rf: resample(br.fb, N), rl: resample(br.lb, N), N, headPts: br.head.slice(0, -1), tailPts: br.tail.slice(1) });
  }
  sel = null;
  renderResults();
  fitPlan();
  const step = now => {
    if (!anim) return;
    const t = now - anim.t0;
    frame(t);
    if (t >= anim.end) { const fin = anim.final; stopAnim(); sel = fin; finishReveal(); return; }
    anim.raf = requestAnimationFrame(step);
  };
  anim.raf = requestAnimationFrame(step);
}
function frame(t) {
  const a = anim, fast = plan.routes.fastest, lit = plan.routes.better_lit;
  if (t < MOTION.draw) {
    const vis = cutC(a.fastPts, a.cum, easeDraw(clamp(t / MOTION.draw)) * a.L);
    setTrail(a.g, vis);
    a.head.setLatLng(vis[vis.length - 1]);
  } else if (a.stage === 0) {
    a.stage = 1;
    setTrail(a.g, a.fastPts);
    a.head.remove();
    const old = [a.g.glow, a.g.cas, a.g.line];
    drawMain(fast, 'fastest', routeLayer, false, true);
    drawWarnings([fast]);
    fadeOut(old, MOTION.pause);
  }
  if (a.morph && t >= MOTION.draw + MOTION.pause) {
    const tm = t - MOTION.draw - MOTION.pause, u = clamp(tm / MOTION.morph);
    if (a.stage === 1) {
      a.stage = 2;
      const old = [];
      routeLayer.eachLayer(l => old.push(l));
      a.alt = drawAlt(fast, 'fastest', routeLayer, 0);
      a.m = trail();
      setTrail(a.m, a.fastPts);
      fadeOut(old, 200);
    }
    const mid = a.rf.map((p, i) => {
      const k = easeMorph(clamp((tm - MOTION.spread * i / (a.N - 1)) / MOTION.morph)), q = a.rl[i];
      return L.latLng(p.lat + (q.lat - p.lat) * k, p.lng + (q.lng - p.lng) * k);
    });
    setTrail(a.m, a.headPts.concat(mid, a.tailPts));
    const altOp = 0.8 * easeOut(u);
    a.alt.forEach((p, i) => p.setStyle({ opacity: i === 0 ? altOp / 0.8 : altOp }));
    // the cards follow the line
    const q = easeMorph(clamp((u - 0.25) / 0.55));
    setOp('card-better_lit', easeOut(clamp(tm / 220)));
    const n = $('n-better_lit'); if (n) n.textContent = Math.round(fast.minutes + (lit.minutes - fast.minutes) * q);
    const d = $('d-better_lit'); if (d) d.textContent = `${km(fast.length_m + (lit.length_m - fast.length_m) * q)} · ${arriveHM(q < 0.5 ? fast : lit)}`;
    setOp('plus-better_lit', clamp((u - 0.7) / 0.25));
    setOp('why-better_lit', clamp((u - 0.75) / 0.25));
    setOp('lifelink', clamp((u - 0.6) / 0.3));
    setOp('plus-chip', clamp((u - 0.55) / 0.3));
  } else if (!a.morph && t >= MOTION.draw) {
    setOp('lifelink', clamp((t - MOTION.draw) / 300));
    setOp('card-better_lit', clamp((t - MOTION.draw) / 300));
  }
  const fq = easeOut(clamp((t - 500) / 400)), fc = $('card-fastest');
  if (fc) { fc.style.opacity = fq.toFixed(3); fc.style.transform = `translateY(${(8 * (1 - fq)).toFixed(1)}px)`; }
}
function setOp(id, x) { const el = $(id); if (el) { el.style.opacity = x.toFixed(3); el.style.visibility = x > 0 ? 'visible' : 'hidden'; } }
function stopAnim() { if (anim) { cancelAnimationFrame(anim.raf); anim = null; } }
function finishReveal() {
  const old = [];
  routeLayer.eachLayer(l => old.push(l));
  renderResults();
  drawRoutes(true);
  fadeOut(old, 260);
}
function pick(kind) {
  if (!plan || !plan.routes[kind]) return;
  stopAnim();
  sel = kind;
  finishReveal();
}

// ---------- results ----------
SCREENS.results = renderResults;
ACT.pickFast = () => pick('fastest');
ACT.pickLit = () => pick('better_lit');
ACT.recalc = () => { if (plan && screen === 'results') reveal(true); else if (A && B) compute(); };
ACT.details = () => go('details');
ACT.start = () => startNav();
ACT.backResults = () => go(sel === 'transit' ? 'transit' : 'results');

function resultsTop() {
  return `<div class="top"><button type="button" class="round" data-act="home" aria-label="${esc(t('m.backSearch'))}">${I.back()}</button><span class="grow"></span>` +
    `<button type="button" class="round" data-act="recalc" aria-label="${esc(t('m.recalc'))}">${I.recalc()}</button>` +
    `<button type="button" class="pill" data-act="legend" aria-expanded="${legendOpen}">${I.legend()}${esc(t('m.legend'))}</button></div>`;
}
function routeSub() {
  const when = plan ? (at ? t('m.leaveAt', { time: leaveHM() }) : t('m.leaveNow', { time: leaveHM() })) : '';
  return `${t('m.mode.' + mode)}${when ? ' · ' + when : ''}`;
}
function renderResults() {
  if (screen !== 'results') return;
  const head = `<div class="handle"></div><div style="display: flex; flex-direction: column; gap: 2px"><h1 class="h-route">${esc(labels.A)} → ${esc(labels.B)}</h1><p class="sec">${esc(routeSub())}</p></div>${modeSeg('compact')}`;
  if (!plan) {
    $('screen').innerHTML = resultsTop() + `<section class="sheet" aria-busy="true">${head}<p class="loading">${esc(t('computing'))}</p></section>`;
    return;
  }
  const v = plan.verdict, { fastest, better_lit: lit } = plan.routes, animating = !!anim;
  let cards;
  if (v.kind === 'same') {
    const k = v.pick || 'fastest', r = plan.routes[k];
    cards = `<div class="rcard one" id="card-${k}"><span class="t">${esc(routeTitle(k))}</span>` +
      `<span class="big"><span class="n">${Math.round(r.minutes)}</span><span class="u">min</span><span class="sec" style="padding: 0 0 6px 6px">${esc(km(r.length_m))} · ${esc(t('m.arrival'))} ${arriveHM(r)}</span></span>` +
      `${statusBar(r)}<span style="font-size: 13px; line-height: 1.45">${esc(t(k === 'better_lit' ? 'm.litFreeText' : 'm.noBetter'))}</span><span class="small">${esc(shares(r))}</span></div>`;
  } else {
    cards = `<div class="cards">${card('fastest', fastest, animating)}${card('better_lit', lit, animating)}</div>`;
  }
  const r = plan.routes[sel || anim && anim.final || 'better_lit'], sg = r && r.signs;
  const lifeLabel = v.kind === 'same' ? t('m.onThisRoute') : (sel || (anim && anim.final)) === 'fastest' ? t('m.onFastRoute') : t('m.onLitRoute');
  const life = sg ? `<button type="button" class="lifelink" id="lifelink" data-act="details" style="${animating ? 'opacity: 0; visibility: hidden' : ''}">` +
    `<span aria-hidden="true" style="display: flex; gap: 3px">${I.place()}${I.stopMk()}</span><span class="grow" style="min-width: 0"><span class="muted">${esc(lifeLabel)}</span> ${esc(lifeText(sg))}</span>${I.chev()}</button>` : '';
  const transitNote = mode === 'transit' && plan.transit && plan.transit.kind !== 'ok' ? transitWhyNot() : '';
  const chip = v.kind === 'show' ? plusChip() : '';
  $('screen').innerHTML = resultsTop() + chip +
    `<section class="sheet" aria-label="${esc(t('m.variants'))}">${head}${transitNote}${cards}${life}` +
    `<div class="actions"><button type="button" class="primary" data-act="start">${I.nav()}${esc(t('m.start'))}</button>` +
    `<button type="button" class="secondary" data-act="details" style="width: 112px">${esc(t('m.details'))}</button></div></section>`;
  if (chip) placePlusChip();
}
function card(kind, r, animating) {
  const v = plan.verdict, pressed = sel === kind, fast = plan.routes.fastest, lit = plan.routes.better_lit;
  const isLit = kind === 'better_lit';
  const extra = extraMin();
  const hidden = animating ? (isLit ? 'opacity: 0; visibility: hidden;' : 'opacity: 0;') : '';
  let bottom = '';
  if (!isLit) {
    if (r.by_status_m.dark_reported > 0) bottom = `<span class="warnline">${I.diamond()}<span>${esc(t('m.darkM', { m: Math.round(r.by_status_m.dark_reported) }))}</span></span>`;
    else if (r.by_status_m.unknown > 0) bottom = `<span class="warnline">${sample('unknown', 20, 4)}<span>${esc(t('m.unknownM', { m: Math.round(r.by_status_m.unknown) }))}</span></span>`;
    else bottom = `<span class="warnline"><span>${esc(t('m.confirmedShare', { p: pct(r.by_status_m.lit_confirmed / (r.length_m || 1)) }))}</span></span>`;
  } else {
    const share = x => x.by_status_m.lit_confirmed / (x.length_m || 1);
    const why = v.kind === 'too_long' ? t('m.tooLong', { min: extra })
      : fast.by_status_m.dark_reported > lit.by_status_m.dark_reported ? t('m.avoidsDark')
        : fast.by_status_m.unknown > lit.by_status_m.unknown ? t('m.lessUnknown', { m: Math.round(fast.by_status_m.unknown - lit.by_status_m.unknown) })
          : t('m.moreLit', { lit: pct(share(lit)), fast: pct(share(fast)) });
    bottom = `<span id="why-better_lit" style="font-size: 12px; line-height: 1.4; ${animating ? 'opacity: 0' : ''}">${esc(why)}</span>`;
  }
  const label = t(isLit ? 'm.ariaLit' : 'm.ariaFast', { min: Math.round(r.minutes), km: km(r.length_m), arr: arriveHM(r), extra });
  return `<button type="button" class="rcard" id="card-${kind}" data-act="${isLit ? 'pickLit' : 'pickFast'}" aria-pressed="${pressed}" aria-label="${esc(label)}" style="${hidden}">` +
    `<span class="t"><span>${esc(routeTitle(kind))}</span><span class="ring" aria-hidden="true"></span></span>` +
    `<span class="big"><span class="n" id="n-${kind}">${Math.round(animating && isLit ? fast.minutes : r.minutes)}</span><span class="u">min</span>` +
    (isLit && extra > 0 ? `<span class="plus" id="plus-better_lit" style="${animating ? 'opacity: 0' : ''}">+${extra} min</span>` : '') + '</span>' +
    `<span class="sec" id="d-${kind}">${esc(km((animating && isLit ? fast : r).length_m))} · ${arriveHM(animating && isLit ? fast : r)}</span>` +
    `${statusBar(r)}${bottom}</button>`;
}
function plusChip() {
  const fast = plan.routes.fastest, lit = plan.routes.better_lit, extra = extraMin();
  const why = fast.by_status_m.dark_reported > lit.by_status_m.dark_reported ? t('m.chipDark', { m: Math.round(fast.by_status_m.dark_reported - lit.by_status_m.dark_reported) })
    : fast.by_status_m.unknown > lit.by_status_m.unknown ? t('m.chipUnknown', { m: Math.round(fast.by_status_m.unknown - lit.by_status_m.unknown) })
      : t('m.chipLit', { p: pct((lit.by_status_m.lit_confirmed / lit.length_m) - (fast.by_status_m.lit_confirmed / fast.length_m)) });
  const show = anim ? 'opacity: 0; visibility: hidden' : sel === 'better_lit' ? '' : 'display: none';
  return `<div class="plus-chip" id="plus-chip" aria-hidden="true" style="position: absolute; left: 16px; z-index: 1050; ${show}"><b>${extra > 0 ? '+' + extra + ' min' : t('m.sameTime')}</b><span>${esc(why)}</span></div>`;
}
function placePlusChip() {
  const chip = $('plus-chip'), sheet = document.querySelector('#screen .sheet');
  if (!chip || !sheet) return;
  chip.style.bottom = (phoneRect().bottom - sheet.getBoundingClientRect().top + 12) + 'px';
}
function transitWhyNot() {
  const tr = plan.transit, s = plan.settings.transit;
  const why = tr.reason === 'no_stop_near' ? t('noStopNear', { m: s.max_walk_m }) : tr.reason === 'no_line' ? t('noLine') : t('noTripSoon', { min: Math.round(s.max_wait_s / 60) });
  const more = [tr.last ? t(tr.last.missed ? 'lastMissed' : 'lastWas', tr.last) : '', tr.next ? t('nextIs', tr.next) : ''].filter(Boolean).join(' ');
  return `<div class="warnbox"><span style="font-size: 14px; font-weight: 600">${esc(t('m.noTransit'))}</span><span class="sec">${esc(why + (more ? ' ' + more : ''))}</span><span class="small">${esc(t('m.walkBelow'))}</span></div>`;
}

// ---------- segment details (tap a piece of the route) ----------
function evidenceLine(e) {
  if (e.s === 'osm') return t('ev.osm_' + e.k) + ((e.ways || []).length ? t('ev.ways', { ways: e.ways.join(', ') }) : '');
  if (e.s === 'mapillary') {
    const years = e.y1 !== e.y0 ? `${e.y0}–${e.y1}` : String(e.y0);
    return t('ev.lamps', { n: e.n, near: dec(e.near), cov: Math.round(e.cov * 100), years }) + (e.cov < 0.5 ? t('ev.lampsBelow') : '');
  }
  if (e.s === 'sesizari') {
    return t('ev.complaint', { nr: e.nr + (e.n > 1 ? ` (+${e.n - 1})` : ''), sub: e.sub, state: t('ev.state.' + e.k), created: e.created }) +
      (e.closed ? t('ev.closedAt', { date: e.closed }) : '') + (e.age != null ? t('ev.age', { age: e.age }) : '') + t('ev.distance', { d: e.d });
  }
  if (['same_name', 'near_lit_street', 'partial_lamps', 'inherited_dark'].includes(e.k)) return t('ev.' + e.k, { ref: e.ref || '' });
  return JSON.stringify(e);
}
let tip = null;
function openTip(f, kind, latlng) {
  if (anim) return;
  legendOpen = false;
  tip = { f, kind, ev: null };
  markLayer.eachLayer(l => { if (l.options.ring) markLayer.removeLayer(l); });
  L.marker(latlng || midOf(f), { icon: MK.ring(), interactive: false, keyboard: false, ring: true }).addTo(markLayer);
  renderOverlay();
  const id = (f.properties.ids || [])[0];
  if (id) getJSON('/api/segments/' + encodeURIComponent(id)).then(d => { if (tip && tip.f === f) { tip.ev = d.properties.ev || []; renderOverlay(); } }).catch(() => { if (tip && tip.f === f) { tip.ev = []; renderOverlay(); } });
}

// ---------- overlays: legend, segment, about the data ----------
function closeOverlays() {
  langOpen = false;
  legendOpen = false; tip = null; aboutOpen = false;
  markLayer.eachLayer(l => { if (l.options.ring) markLayer.removeLayer(l); });
  $('overlay').innerHTML = '';
  for (const b of document.querySelectorAll('#screen [data-act="legend"]')) b.setAttribute('aria-expanded', 'false');
}
let aboutOpen = false;
function openAbout() { legendOpen = false; tip = null; aboutOpen = true; renderOverlay(); }
function renderOverlay() {
  for (const b of document.querySelectorAll('#screen [data-act="legend"]')) b.setAttribute('aria-expanded', String(legendOpen));
  const close = `<button type="button" class="close" data-act="closeOverlay" aria-label="${esc(t('m.close'))}">${I.close()}</button>`;
  const lb = $('lang-btn');
  if (lb) lb.setAttribute('aria-expanded', String(langOpen));
  if (langOpen) {
    const names = { ro: 'Română', en: 'English', ru: 'Русский' };
    $('overlay').innerHTML = `<div class="menu" role="menu" aria-label="${esc(t('langLabel'))}">` +
      LANGS.map(l => `<button type="button" role="menuitemradio" aria-checked="${l === LANG}" data-act="setLang" data-lang="${l}" lang="${l}"><span class="mono" style="width: 26px; font-size: 12px">${l.toUpperCase()}</span><span class="grow">${names[l]}</span>${l === LANG ? I.check() : ''}</button>`).join('') + '</div>';
    const first = $('overlay').querySelector('[aria-checked="true"]');
    if (first) first.focus();
    return;
  }
  if (legendOpen) {
    const row = k => `${sample(k)}<span>${esc(t('m.st.' + k))}</span>`;
    $('overlay').innerHTML = `<section class="panel" aria-label="${esc(t('m.legend'))}">${close}
      <span class="label">${esc(t('m.lightOnPart'))}</span>
      <div class="legend-grid">${ORDER.map(row).join('')}</div>
      <div class="divider"></div>
      <div class="legend-marks">
        <span><span class="pin-a" style="width: 16px; height: 16px; font-size: 9px">A</span>${esc(t('m.mkStart'))}</span>
        <span><span class="pin-b" style="width: 16px; height: 16px; font-size: 9px">B</span>${esc(t('m.mkDest'))}</span>
        <span>${I.place()}${esc(t('m.mkOpen'))}</span><span>${I.stopMk()}${esc(t('m.mkStop'))}</span>
        <span><svg width="28" height="10" viewBox="0 0 28 10" aria-hidden="true"><path d="M2 5h24" stroke="#F2F2F2" stroke-width="5" stroke-linecap="round"/></svg>${esc(t('m.mkChosen'))}</span>
        <span><svg width="28" height="10" viewBox="0 0 28 10" aria-hidden="true"><path d="M2 5h24" stroke="#F2F2F2" stroke-opacity="0.75" stroke-width="2.5" stroke-linecap="round"/></svg>${esc(t('m.mkAlt'))}</span>
        <span><svg width="40" height="24" viewBox="-20 -12 40 24" aria-hidden="true"><rect x="-17" y="-10" width="34" height="20" rx="5" fill="#F2F2F2"/><text y="4" text-anchor="middle" font-family="Inter Tight, Inter, sans-serif" font-weight="600" font-size="12" fill="#0B0B0B">16</text></svg>${esc(t('m.mkVehicle'))}</span>
      </div>
      <span class="small">${esc(t('m.tapPart'))}</span>
      <div class="divider"></div>
      <label class="toggle"><span>${esc(t('showNet'))}</span><input type="checkbox" data-act="net" ${prefs.net ? 'checked' : ''}></label>
      <label class="toggle"><span>${esc(t('live.show'))}</span><input type="checkbox" data-act="livenet" ${prefs.livenet ? 'checked' : ''}></label>
    </section>`;
    for (const c of $('overlay').querySelectorAll('input[type="checkbox"]')) c.addEventListener('change', () => ACT[c.dataset.act](c));
    return;
  }
  if (tip) {
    const p = tip.f.properties, st = p.status;
    const src = tip.ev == null ? `<li>${esc(t('m.loadingSrc'))}</li>` : tip.ev.length ? tip.ev.map(e => `<li>${esc(evidenceLine(e))}</li>`).join('') : `<li>${esc(t('noEvidence'))}</li>`;
    $('overlay').innerHTML = `<section class="panel" aria-label="${esc(t('m.partDetails'))}" style="top: 64px">${close}
      <div style="display: flex; align-items: center; gap: 10px; padding-right: 36px">${sample(st, 34)}<h2 style="font-size: 16px; font-weight: 600">${esc(t('m.st.' + st))}</h2></div>
      <span style="font-size: 13px">${esc([p.name || t('noName'), Math.round(p.len) + ' m', t(plan && plan.verdict.kind === 'same' && screen === 'results' ? 'm.onThis' : tip.kind === 'fastest' ? 'm.onFastest' : 'm.onLitter')].join(' · '))}</span>
      <ul class="src">${src}</ul>
      <span class="small">${esc(t('m.note.' + st) + (summary ? ' ' + t('dataAsOf', { date: summary.as_of }) : ''))}</span>
    </section>`;
    return;
  }
  if (aboutOpen) {
    $('overlay').innerHTML = `<section class="panel" aria-label="${esc(t('m.aboutData'))}">${close}
      <h2 style="font-size: 16px; font-weight: 600; padding-right: 36px">${esc(t('m.aboutData'))}</h2>
      <p class="sec">${esc($('meta-text') ? '' : metaText())}</p>
      <ul class="src">${ORDER.map(k => `<li>${esc(t('legend.' + k))}</li>`).join('')}</ul>
      <p class="small">${esc(t('m.aboutNote'))}</p>
    </section>`;
    return;
  }
  $('overlay').innerHTML = '';
}
function metaText() {
  if (!summary) return '';
  const g = summary.groups.streets_and_sidewalks, src = summary.sources;
  return t('meta', { km: dec(g.km), lit: dec(g.lit_confirmed), likely: dec(g.lit_likely), dark: dec(g.dark_reported), unknown: dec(g.unknown), asof: summary.as_of,
    osm: (summary.network.fetched_at || '').slice(0, 10), mly: (src.mapillary.last_seen_range || []).join('…'), ses: (src.sesizari.created_range || []).join('…'),
    walk: dec((3.6 * 1.35).toFixed(1)), bike: dec((3.6 * 4.2).toFixed(0)) });
}

// ---------- details ----------
SCREENS.details = renderDetails;
ACT.part = el => { part = +el.dataset.i; renderDetails(); };
function renderDetails() {
  if (!plan) { go('home', false); return; }
  const kind = sel === 'transit' || !sel ? 'better_lit' : sel, r = plan.routes[kind], runs = runsOf(r), sg = r.signs;
  if (part == null || part >= runs.length) {
    let best = -1;
    runs.forEach((x, i) => { if (x.status !== 'lit_confirmed' && (best < 0 || x.len > runs[best].len)) best = i; });
    part = best >= 0 ? best : 0;
  }
  const run = runs[part], f = run.feats.reduce((a, b) => (b.properties.len > a.properties.len ? b : a));
  const total = r.length_m || 1;
  const bar = runs.map((x, i) => {
    const s = ST[x.status], w = 100 * x.len / total;
    const label = t('m.partAria', { status: t('m.st.' + x.status), from: km(x.from), to: km(x.to) });
    return `<button type="button" data-act="part" data-i="${i}" aria-pressed="${i === part}" aria-label="${esc(label)}" style="width: ${w.toFixed(2)}%">` +
      `<svg aria-hidden="true"><line x1="${i ? 1 : 0}" x2="100%" y1="11" y2="11" stroke="${s.c}" stroke-width="8"${s.bar ? ` stroke-dasharray="${x.status === 'lit_likely' ? '10 4' : x.status === 'unknown' ? '0.1 9' : '6 8 0.1 8'}"` : ''}${s.cap === 'round' && s.bar ? ' stroke-linecap="round"' : ''}/></svg></button>`;
  }).join('');
  const step = total > 2500 ? 1000 : 500, ticks = ['0'];
  for (let m = step; m < total - step * 0.4; m += step) ticks.push(km(m).replace(',00', ''));
  ticks.push(km(total));
  let n = 0;
  const lifeItems = sg ? sg.open_places.map(p => `<li><span class="num" aria-hidden="true">${++n}</span><span>${esc(p.name)}</span><span class="sec">${esc(p.always ? t('signsAlways') : t('m.open'))}</span></li>`)
    .concat(sg.stops.map(s => `<li><span class="num sq" aria-hidden="true">${++n}</span><span>${esc(s.name)}</span><span class="sec">${esc(s.departures.slice(0, 3).map(d => d.line + ' ' + d.time).join(', '))}</span></li>`)) : [];
  const time = (plan.at || '').slice(11, 16);
  $('screen').innerHTML = `
  <section class="sheet tall" aria-labelledby="h-det" style="max-height: calc(100% - 190px)">
    <div class="handle"></div>
    <div style="display: flex; align-items: center; gap: 4px"><button type="button" class="back" data-act="backResults" aria-label="${esc(t('m.backVariants'))}">${I.back()}</button>
      <div style="display: flex; flex-direction: column; min-width: 0"><h1 id="h-det" style="font-size: 17px; line-height: 22px; font-weight: 600">${esc(routeTitle(kind))} · ${Math.round(r.minutes)} min</h1>
      <span class="sec">${esc(km(r.length_m))} · ${esc(t('m.leave').toLowerCase())} ${leaveHM()} · ${esc(t('m.arrival'))} ${arriveHM(r)}</span></div></div>
    <section aria-labelledby="h-prof" style="display: flex; flex-direction: column; gap: 6px">
      <div class="row"><h2 id="h-prof" class="label">${esc(t('m.lightAlong'))}</h2><span class="small" style="color: var(--bz-ink-2)">${esc(t('m.darkM', { m: Math.round(r.by_status_m.dark_reported) }))}</span></div>
      <div class="prof">${bar}</div>
      <div class="ticks">${ticks.map(x => `<span>${esc(x)}</span>`).join('')}</div>
      <span class="small" style="color: var(--bz-ink-2)">${esc(shares(r))}. ${esc(t('m.tapBar'))}</span>
    </section>
    <section class="box" aria-labelledby="h-why">
      <div style="display: flex; align-items: center; gap: 10px">${sample(run.status, 34)}<h2 id="h-why" style="font-size: 15px; font-weight: 600">${esc(t('m.whyTitle', { status: t('status.' + run.status) }))}</h2></div>
      <p style="font-size: 14px; line-height: 1.45" class="muted"><strong style="color: var(--bz-ink); font-weight: 600">${esc((f.properties.name || t('noName')) + ', ' + Math.round(run.len) + ' m')}</strong> ${esc(t('m.ringNote'))} ${esc(t('m.why.' + run.status))}</p>
      <details id="why-src"><summary>${I.chev(12, 'chev')}<span id="why-src-n">${esc(t('m.sources', { n: '…' }))}</span></summary><ul class="src" id="why-src-list" style="margin-top: 4px"></ul></details>
    </section>
    ${sg ? `<section aria-labelledby="h-life" style="display: flex; flex-direction: column; gap: 8px">
      <h2 id="h-life" class="label">${esc(t('m.onRouteAt', { time }))}</h2>
      ${lifeItems.length ? `<ul class="nlist">${lifeItems.join('')}</ul>` : `<p class="sec">${esc(t('signsNoneOpen'))}</p>`}
      <p class="small">${esc(t('m.lifeSummary', { n: sg.places_unknown_hours, p: pct(sg.main_share) }))}</p>
      <details><summary>${I.chev(12, 'chev')}${esc(t('m.sources', { n: 2 }))}</summary><p class="sec" style="margin-top: 4px">${esc(t('m.lifeSources', { feed: plan.transit && plan.transit.feed ? plan.transit.feed : (summary ? summary.as_of : '') }))}</p></details>
    </section>` : ''}
    <div class="actions" style="padding-top: 4px"><button type="button" class="primary" data-act="start">${I.nav()}${esc(t('m.start'))}</button></div>
  </section>`;
  routeLayer.clearLayers(); markLayer.clearLayers();
  drawMain(r, kind);
  drawWarnings([r]);
  drawLife(sg, true);
  L.marker(midOf(f), { icon: MK.ring(), interactive: false, keyboard: false }).addTo(markLayer);
  fit(L.latLngBounds(pts(r)).pad(0.05));
  const id = (f.properties.ids || [])[0];
  if (id) getJSON('/api/segments/' + encodeURIComponent(id)).then(d => {
    const ev = d.properties.ev || [], list = $('why-src-list');
    if (!list) return;
    $('why-src-n').textContent = t('m.sources', { n: ev.length });
    list.innerHTML = ev.length ? ev.map(e => `<li>${esc(evidenceLine(e))}</li>`).join('') : `<li>${esc(t('noEvidence'))}</li>`;
  }).catch(() => {});
}

// ---------- walk + public transport ----------
SCREENS.transit = renderTransit;
ACT.openStop = () => go('stop');
ACT.walkInstead = () => { mode = 'walk'; compute(); };
ACT.nextTrip = () => compute();
const ride = () => (plan && plan.transit && plan.transit.kind === 'ok' ? plan.transit.legs[1] : null);

function legBar(w, width = 120) {
  const L0 = w.length_m || 1;
  let x = 0, out = '';
  for (const k of ORDER) {
    const m = w.by_status_m[k];
    if (!(m > 0)) continue;
    const a = x + (x ? 3 : 0), b = x + width * m / L0;
    if (b > a) out += `<line x1="${a.toFixed(1)}" x2="${b.toFixed(1)}" y1="3" y2="3" stroke="${ST[k].c}" stroke-width="4"${ST[k].bar ? ` stroke-dasharray="${ST[k].bar}"` : ''}${ST[k].bar && ST[k].cap === 'round' ? ' stroke-linecap="round"' : ''}/>`;
    x = b;
  }
  const shares = ORDER.filter(k => w.by_status_m[k] > 0).map(k => t('m.legShare.' + k, { p: pct(w.by_status_m[k] / L0) })).join(' · ');
  return `<span style="display: flex; align-items: center; gap: 8px"><svg width="${width}" height="6" aria-hidden="true" style="flex: none">${out}</svg><span class="small" style="color: var(--bz-ink-2)">${esc(shares)}</span></span>`;
}
function renderTransit() {
  const top = `<div class="top"><button type="button" class="round" data-act="home" aria-label="${esc(t('m.back'))}">${I.back()}</button><span class="grow"></span>` +
    `<button type="button" class="pill" data-act="legend" aria-expanded="${legendOpen}">${I.legend()}${esc(t('m.legend'))}</button></div>`;
  if (!plan) {
    $('screen').innerHTML = top + `<section class="sheet" aria-busy="true"><div class="handle"></div><div><h1 class="h-route">${esc(labels.A)} → ${esc(labels.B)}</h1><p class="sec">${esc(routeSub())}</p></div>${modeSeg('compact')}<p class="loading">${esc(t('computing'))}</p></section>`;
    return;
  }
  const tr = plan.transit, [w1, rd, w2] = tr.legs, type = t('rt.' + rd.route_type);
  const tl = `<div class="tl" role="img" aria-label="${esc(t('m.tlAria', { w1: minN(w1.minutes), type, line: rd.line, ride: minN(rd.minutes), w2: minN(w2.minutes) }))}" style="grid-template-columns: minmax(44px, ${Math.max(1, w1.minutes).toFixed(1)}fr) minmax(72px, ${Math.max(1, rd.minutes).toFixed(1)}fr) minmax(56px, ${Math.max(1, w2.minutes).toFixed(1)}fr)">
      <span><svg width="100%" height="6" style="display: block"><line x1="0" x2="100%" y1="3" y2="3" stroke="#F2F2F2" stroke-width="3"/></svg><small>${I.walk(13)}${minN(w1.minutes)}</small></span>
      <span><svg width="100%" height="6" style="display: block"><line x1="0" x2="100%" y1="3" y2="3" stroke="#6B6B6B" stroke-width="6"/></svg><small><span class="badge" style="font-size: 11px; line-height: 15px; padding: 0 4px">${esc(rd.line)}</span>${minN(rd.minutes)} min</small></span>
      <span><svg width="100%" height="6" style="display: block"><line x1="0" x2="100%" y1="3" y2="3" stroke="#F2F2F2" stroke-width="3"/></svg><small>${I.walk(13)}${minN(w2.minutes)} min</small></span>
    </div>`;
  const steps = `<ol class="steps" aria-label="${esc(t('m.steps'))}">
      <li><span class="tm">${esc(tr.leave_at)}</span><span style="display: flex; flex-direction: column; gap: 4px"><span style="font-size: 14px"><strong style="font-weight: 600">${esc(t('m.walkMin', { min: minN(w1.minutes) }))}</strong> · ${esc(t('m.toStop', { d: dist(w1.length_m), stop: rd.from.name }))}</span>${legBar(w1)}</span></li>
      <li><span class="tm" style="color: var(--bz-ink); font-weight: 600">${esc(rd.dep)}</span><span style="display: flex; flex-direction: column; gap: 2px"><span style="display: flex; align-items: center; gap: 6px; font-size: 14px"><span class="badge">${esc(rd.line)}</span><strong style="font-weight: 600">${esc(t(rd.stops === 1 ? 'm.rideStops1' : 'm.rideStops', { n: rd.stops, min: minN(rd.minutes) }))}</strong></span><span class="sec">${esc(t('m.getOff', { stop: rd.to.name, time: rd.arr }))}</span></span></li>
      <li><span class="tm">${esc(rd.arr)}</span><span style="display: flex; flex-direction: column; gap: 4px"><span style="font-size: 14px"><strong style="font-weight: 600">${esc(t('m.walkMin', { min: minN(w2.minutes) }))}</strong> · ${esc(t('m.toDest', { d: dist(w2.length_m) }))}</span>${legBar(w2)}</span></li>
    </ol>`;
  const last = tr.last ? `<p class="dashed"><span>${esc(t('m.lastToday', { line: tr.last.line, stop: tr.last.stop }))} <strong>${esc(tr.last.time)}</strong></span><span class="tag">${esc(t('m.orar'))}</span></p>` : '';
  // No "walking is not slower" note (as on the desktop page): it compared arrivals from the requested leaving time and
  // showed on 64% of trips, while the trip counts from the later leaving time and still saves ~5 min of walking outside.
  $('screen').innerHTML = top + `
  <section class="sheet" aria-labelledby="h-tr" style="max-height: calc(100% - 230px)">
    <div class="handle"></div>
    <div style="display: flex; flex-direction: column; gap: 2px"><h1 id="h-tr" style="display: flex; align-items: baseline; gap: 10px; font-weight: 600"><span style="font-family: var(--bz-display); font-size: 28px; line-height: 1.1">${minN(tr.minutes)} min</span><span style="font-size: 15px; color: var(--bz-ink-2); font-weight: 500">${esc(t('m.arrival'))} ${esc(tr.arrive_at)}</span></h1>
      <p class="sec">${esc(labels.A)} → ${esc(labels.B)}</p></div>
    ${modeSeg('compact')}
    ${tl}
    <button type="button" class="livecard" id="livecard" data-act="openStop"></button>
    ${steps}${last}
    <p class="small">${esc(t('transitSource', { feed: tr.feed || '?' }))}</p>
    <div class="actions"><button type="button" class="primary" data-act="start">${I.nav()}${esc(t('m.start'))}</button></div>
  </section>`;
  drawTransit();
  fit(L.latLngBounds(pts(w1).concat(pts(w2), ll(rd.coords).map(c => L.latLng(c)))).pad(0.05));
  updateLive();
}
function drawTransit() {
  routeLayer.clearLayers(); markLayer.clearLayers(); lifeLayer.clearLayers();
  const [w1, rd, w2] = plan.transit.legs, line = ll(rd.coords);
  L.polyline(line, { renderer: svgR, color: '#0B0B0B', weight: 12, interactive: false, lineCap: 'round', lineJoin: 'round' }).addTo(routeLayer);
  L.polyline(line, { renderer: svgR, color: '#6B6B6B', weight: 7, interactive: false, lineCap: 'round', lineJoin: 'round' }).addTo(routeLayer);
  for (const w of [w1, w2]) {
    L.polyline(w.geometry.features.map(f => ll(f.geometry.coordinates)), { renderer: svgR, color: '#0B0B0B', weight: 10, interactive: false, lineCap: 'round', lineJoin: 'round' }).addTo(routeLayer);
    for (const f of w.geometry.features) {
      const s = ST[f.properties.status] || ST.unknown;
      L.polyline(ll(f.geometry.coordinates), { renderer: svgR, color: s.c, weight: 5, dashArray: s.alt || null, lineCap: s.cap, lineJoin: 'round', interactive: false }).addTo(routeLayer);
      L.polyline(ll(f.geometry.coordinates), { renderer: svgR, weight: 22, opacity: 0, bubblingMouseEvents: false }).on('click', e => openTip(f, 'better_lit', e.latlng)).addTo(routeLayer);
    }
  }
  drawWarnings([w1, w2]);
  for (const s of [rd.from, rd.to]) L.marker([s.lat, s.lon], { icon: MK.station(), interactive: false, keyboard: false }).addTo(markLayer);
  L.marker([rd.from.lat, rd.from.lon], { icon: L.divIcon({ className: 'bz-mk', html: `<span class="map-chip dim">${esc(rd.from.name)}</span>`, iconSize: null, iconAnchor: [-14, 10] }), interactive: false, keyboard: false }).addTo(markLayer);
}

// ---------- live arrival: the state of the planned trip, as the design names it ----------
// live: forecast from a position observed ≤ 60 s ago; old: forecast or position older than that; orar: timetable only
function liveState() {
  const rd = ride();
  if (!rd) return null;
  const now = Date.now() / 1000 + liveOff;
  if (!live) return { kind: 'wait' };
  if (live.failed) return { kind: 'orar', why: t('m.liveDown') };
  const T = live.trip || { status: 'no_vehicle' };
  const age = T.age_s != null ? T.age_s + (now - live.now) : null;
  const fetchAge = (Date.now() - liveAt) / 1000;
  if (T.expected_ts != null && age != null && age <= LIVE_S) return { kind: 'live', T, age, fetchAge, eta: T.expected_ts - now };
  if (T.expected_ts != null || T.status === 'stale') return { kind: 'old', T, age, fetchAge, eta: T.expected_ts != null ? T.expected_ts - now : null };
  const why = {
    previous_trip: T.trips_before > 1 ? t('live.previousMany', { n: T.trips_before }) : t('live.previous', { headsign: T.now_headsign || '?' }),
    no_vehicle: t('m.noLivePos'), no_forecast: t('live.noForecast'), passed: t('live.passed', { stop: rd.from.name }),
    later: t('live.later'), no_data: t('m.liveDown'),
  }[T.status] || t('m.noLivePos');
  return { kind: 'orar', T, why, fetchAge, passed: T.status === 'passed' };
}
function liveChip(s) {
  if (s.kind === 'live') {
    const on = Math.max(1, 5 - Math.floor(s.age / 12));
    return `<span class="lchip live" role="status"><span class="bars" aria-hidden="true">${[0, 1, 2, 3, 4].map(i => `<i class="${i < on ? 'on' : ''}"></i>`).join('')}</span>${esc(t('m.chipLive', { age: ago(s.age) }))}</span>`;
  }
  if (s.kind === 'old') return `<span class="lchip old" role="status"><span class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>${esc(t('m.chipOld', { age: ago(s.age) }))}</span>`;
  if (s.kind === 'wait') return `<span class="lchip none">${esc(t('m.chipWait'))}</span>`;
  return `<span class="lchip orar" role="status">${I.clock(12)}${esc(t('m.orar'))}</span>`;
}
const delayText = (d, sched) => (Math.abs(d) < 60 ? t('m.onTime', { sched }) : t(d > 0 ? 'm.late' : 'm.early', { min: Math.round(Math.abs(d) / 60), sched }));
function updateLive() {
  const rd = ride(), s = liveState();
  if (!rd || !s) return;
  const type = t('rt.' + rd.route_type);
  const card = $('livecard');
  if (card) {
    let big, right = `${esc(rd.from.name)} · `, delay = '';
    if (s.kind === 'live') { big = s.T.stops_away === 0 || s.eta < 45 ? t('m.nowAtStop') : t('m.inMin', { min: Math.max(1, Math.round(s.eta / 60)) }); right += clockOf(s.T.expected_ts); delay = delayText(s.T.delay_s, rd.dep); }
    else if (s.kind === 'old' && s.eta != null) { big = '≈ ' + t('m.inMin', { min: Math.max(1, Math.round(s.eta / 60)) }); right += clockOf(s.T.expected_ts); delay = t('m.fromOld', { age: ago(s.age) }); }
    else { big = t('m.atTime', { time: rd.dep }); right = esc(rd.from.name); delay = s.why || ''; }
    const meta = s.kind === 'live' || s.kind === 'old' ? t('m.liveMeta', { age: ago(s.age), every: live && live.refresh_s ? live.refresh_s : 15 }) : t('m.orarMeta', { feed: plan.transit.feed || '?' });
    card.className = 'livecard' + (s.kind === 'old' ? ' old' : '');
    card.setAttribute('aria-label', t('m.liveCardAria', { line: rd.line, big, stop: rd.from.name }));
    card.innerHTML = `<span style="display: flex; align-items: center; gap: 8px"><span class="badge lg">${esc(rd.line)}</span><span class="grow sec" style="min-width: 0">${esc(t('m.towards', { type }))} <strong style="color: var(--bz-ink); font-weight: 600">${esc(rd.headsign)}</strong></span>${liveChip(s)}</span>` +
      `<span class="row" style="align-items: baseline"><span style="font-family: var(--bz-display); font-size: 30px; font-weight: 600; line-height: 1.1; color: ${s.kind === 'old' ? 'var(--bz-ink-2)' : 'var(--bz-ink)'}">${esc(big)}</span><span style="font-size: 14px">${right}</span></span>` +
      (delay ? `<span style="display: flex; align-items: center; gap: 7px; font-size: 13px">${I.clock(14)}<span>${esc(delay)}</span></span>` : '') +
      `<span class="row small" style="color: var(--bz-ink-2)"><span>${esc(meta)}</span>${I.chev(12)}</span>`;
  }
  if (screen === 'stop') updateStop(s);
}

// ---------- waiting at the stop ----------
SCREENS.stop = renderStop;
function renderStop() {
  const rd = ride();
  if (!rd) { go('home', false); return; }
  const tr = plan.transit, lit = plan.routes.better_lit;
  $('screen').innerHTML = `
  <section class="stopcard" aria-label="${esc(t('m.currentStep'))}">${I.flag()}<div style="display: flex; flex-direction: column; gap: 2px; min-width: 0"><span style="font-size: 17px; font-weight: 600; line-height: 22px">${esc(t('m.waitAt', { stop: rd.from.name }))}</span><span style="font-size: 14px" class="muted">${esc(t('m.platform', { headsign: rd.headsign }))}</span></div></section>
  <section class="sheet" style="max-height: calc(100% - 240px)">
    <div class="handle"></div>
    <section aria-label="${esc(t('m.arrivalOf', { line: rd.line }))}" id="stopbox" style="padding: 14px; border-radius: 16px; background: var(--bz-raised); border: 1px solid var(--bz-edge); display: flex; flex-direction: column; gap: 6px">
      <div class="row"><span style="display: flex; align-items: center; gap: 8px"><span class="badge lg">${esc(rd.line)}</span><span class="muted" style="font-size: 14px">${esc(t('rt.' + rd.route_type))}</span><span id="stop-wheel" class="muted"></span></span><span id="stop-chip"></span></div>
      <span class="sec" id="stop-label" style="margin-top: 2px"></span>
      <span class="huge" id="stop-big" role="status" aria-live="polite"></span>
      <span id="stop-sub" style="font-size: 14px; line-height: 1.45"></span>
      <span class="mono" id="stop-meta" style="font-size: 11px; line-height: 1.5; color: var(--bz-ink-3)"></span>
      <span id="stop-act"></span>
    </section>
    <section style="display: flex; align-items: flex-start; gap: 12px; padding: 0 2px">${I.alight()}<span style="font-size: 14px; line-height: 1.45">${esc(t(rd.stops === 1 ? 'm.getOffAfter1' : 'm.getOffAfter', { stop: rd.to.name, n: rd.stops, time: rd.arr }))}</span></section>
    ${tr.last ? `<ul class="dashed" style="list-style: none; margin: 0; padding: 4px 12px; flex-direction: column; align-items: stretch"><li class="row" style="min-height: 30px; font-size: 14px; color: var(--bz-ink)"><span>${esc(t('m.lastLine', { line: tr.last.line }))}</span><span style="display: flex; align-items: center; gap: 8px"><strong>${esc(tr.last.time)}</strong><span class="tag">${esc(t('m.orar'))}</span></span></li></ul>` : ''}
    <button type="button" class="lifelink" data-act="walkInstead" style="min-height: 52px; border-color: var(--bz-edge)"><span style="display: flex; align-items: center; gap: 10px; min-width: 0" class="grow">${I.walk()}<span style="display: flex; flex-direction: column; gap: 2px; text-align: left"><span style="font-size: 15px; font-weight: 600">${esc(t('m.walkAlt', { min: minN(lit.minutes), km: km(lit.length_m) }))}</span><span class="small" style="color: var(--bz-ink-2)">${esc(t('m.confirmedShare', { p: pct(lit.by_status_m.lit_confirmed / (lit.length_m || 1)) }))}</span></span></span>${I.chev()}</button>
    <div class="row" style="margin-top: auto"><span style="display: flex; flex-direction: column; gap: 2px"><span style="font-family: var(--bz-display); font-size: 20px; font-weight: 600">${esc(t('m.arrivalCap'))} ${esc(tr.arrive_at)}</span><span class="small">${esc(t('m.positionsEvery', { s: live && live.refresh_s ? live.refresh_s : 15 }))}</span></span>
      <button type="button" class="secondary sm" data-act="backResults">${I.stopSq()}${esc(t('m.stop'))}</button></div>
  </section>`;
  drawTransit();
  fit(L.latLngBounds([[rd.from.lat, rd.from.lon]]).pad(0.004), 16);
  updateLive();
}
function updateStop(s) {
  const rd = ride(), big = $('stop-big');
  if (!big) return;
  $('stop-chip').innerHTML = liveChip(s);
  $('stop-wheel').innerHTML = s.T && s.T.wheelchair ? I.wheel() : '';
  const box = $('stopbox');
  box.style.borderStyle = s.kind === 'old' ? 'dashed' : 'solid';
  box.style.borderColor = s.kind === 'live' ? 'var(--bz-edge)' : 'var(--bz-transit)';
  let label, value, sub, color = 'var(--bz-ink)';
  if (s.kind === 'live') {
    label = t('m.arrivesIn');
    value = s.T.stops_away === 0 || s.eta < 45 ? t('m.now') : `${Math.max(1, Math.round(s.eta / 60))} min`;
    const away = s.T.stops_away > 1 ? t('m.stopsAway', { n: s.T.stops_away }) : s.T.stops_away === 1 ? t('m.oneStopAway') : '';
    sub = [clockOf(s.T.expected_ts), delayText(s.T.delay_s, rd.dep), away].filter(Boolean).join(' · ');
    if (s.T.status === 'previous_trip') sub += '. ' + t('live.previous', { headsign: s.T.now_headsign || '?' });
  } else if (s.kind === 'old') {
    label = t('m.oldEstimate'); color = 'var(--bz-ink-2)';
    value = s.eta != null ? `≈ ${Math.max(1, Math.round(s.eta / 60))} min` : rd.dep;
    sub = t('m.oldSub', { age: ago(s.age) });
  } else if (s.kind === 'wait') {
    label = t('m.bySchedule'); value = rd.dep; sub = t('live.loading');
  } else {
    label = t('m.bySchedule'); value = rd.dep; sub = s.why;
  }
  $('stop-label').textContent = label;
  if (big.textContent !== value) big.textContent = value;
  big.style.color = color;
  $('stop-sub').textContent = sub;
  $('stop-sub').style.color = s.kind === 'live' ? 'var(--bz-ink)' : 'var(--bz-ink-2)';
  $('stop-meta').textContent = s.kind === 'live' || s.kind === 'old'
    ? t('m.stopMeta', { age: ago(s.age), fetch: ago(s.fetchAge) }) : s.kind === 'wait' ? '' : t('m.orarMeta', { feed: plan.transit.feed || '?' });
  $('stop-act').innerHTML = s.passed ? `<button type="button" class="secondary sm" data-act="nextTrip" style="margin-top: 6px">${esc(t('live.recalc'))}</button>` : '';
}

// ---------- live vehicles (backend/live.py through /api/transit/live) ----------
function liveQuery() {
  const rd = ride(), wantRide = rd && ['transit', 'stop', 'nav'].includes(screen);
  if (!wantRide && !prefs.livenet) return null;
  const q = {};
  if (wantRide && !prefs.livenet) q.route = rd.route_id;
  if (wantRide && rd.trip_id && rd.dep_ts) {
    Object.assign(q, { trip: rd.trip_id, dep: rd.dep_ts, day: rd.day });
    if (rd.board_seq != null) q.seq = rd.board_seq;
  }
  return q;
}
function stopLive() { clearTimeout(liveTimer); liveReq++; live = null; vehLayer.clearLayers(); }
function liveTick() {
  clearTimeout(liveTimer);
  const q = liveQuery();
  if (!q) { liveReq++; vehLayer.clearLayers(); return; }
  if (document.hidden) return;
  const req = ++liveReq;
  getJSON('/api/transit/live?' + new URLSearchParams(q))
    .then(d => { if (req === liveReq) { live = d; liveAt = Date.now(); liveOff = d.now - Date.now() / 1000; } })
    .catch(err => { if (req === liveReq) { live = { failed: err.message }; liveAt = Date.now(); } })
    .finally(() => {
      if (req !== liveReq) return;
      drawVehicles();
      updateLive();
      const wait = live && live.refresh_s ? Math.max(5, live.refresh_s - ((live.source && live.source.age_s) || 0) + 1) : 30;
      liveTimer = setTimeout(liveTick, wait * 1000);
    });
}
function drawVehicles() {
  vehLayer.clearLayers();
  if (!live || !live.vehicles) return;
  const rd = ride(), mineId = live.trip && live.trip.vehicle, onScreen = rd && ['transit', 'stop', 'nav'].includes(screen);
  for (const v of live.vehicles) {
    if (typeof v.lat !== 'number' || typeof v.lon !== 'number') continue;
    const mine = onScreen && v.id === mineId, onLine = onScreen && v.route_id === rd.route_id;
    if (onScreen && !onLine && !prefs.livenet) continue;
    const m = L.marker([v.lat, v.lon], { icon: MK.vehicle(v, mine, !v.live), keyboard: false, zIndexOffset: mine ? 1000 : onLine ? 500 : 0 })
      .bindTooltip(esc(vehicleTip(v)), { direction: 'top', offset: [0, -16] }).addTo(vehLayer);
    if (mine) {
      const away = live.trip.stops_away;
      const chip = !v.live ? t('m.vehOld', { line: v.line, age: ago(v.age_s) }) : away > 1 ? t('m.vehStops', { line: v.line, n: away }) : away === 1 ? t('m.vehOneStop', { line: v.line }) : v.line;
      L.marker([v.lat, v.lon], { icon: L.divIcon({ className: 'bz-mk', html: `<span class="map-chip${v.live ? '' : ' old'}">${esc(chip)}</span>`, iconSize: null, iconAnchor: [-26, 12] }), interactive: false, keyboard: false }).addTo(vehLayer);
    }
  }
}
function vehicleTip(v) {
  let s = t('live.tip', { type: t('rt.' + v.route_type), line: v.line, headsign: v.headsign || '?', age: ago(v.age_s) });
  if (!v.live) s += t('live.tipOld');
  else if (v.delay_s != null) s += Math.abs(v.delay_s) < 60 ? t('live.tipOnTime') : t(v.delay_s > 0 ? 'live.tipLate' : 'live.tipEarly', { d: Math.round(Math.abs(v.delay_s) / 60) + ' min' });
  if (v.wheelchair) s += t('live.wheelchair');
  return s;
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) liveTick(); });
setInterval(() => { if (['transit', 'stop'].includes(screen) && ride()) updateLive(); }, 1000);

// ---------- navigation: follow the chosen route with the phone's position ----------
SCREENS.nav = renderNav;
let nav = null;
function navRoute() {
  if (sel === 'transit' && ride()) return { r: plan.transit.legs[0], kind: 'better_lit', toStop: true };
  const kind = sel === 'fastest' ? 'fastest' : 'better_lit';
  return { r: plan.routes[kind], kind, toStop: false };
}
function buildPath(r) {
  // the route as points with distance along it, and the manoeuvres where the street name changes
  const P = [], feats = r.geometry.features;
  let acc = 0;
  feats.forEach((f, fi) => {
    for (const c of f.geometry.coordinates) {
      const p = L.latLng(c[1], c[0]), last = P[P.length - 1];
      if (last && last.p.lat === p.lat && last.p.lng === p.lng) continue;
      if (last) acc += meters(last.p, p);
      P.push({ p, d: acc, fi });
    }
  });
  const bearing = (a, b) => (Math.atan2((b.lng - a.lng) * Math.cos(a.lat * Math.PI / 180), b.lat - a.lat) * 180 / Math.PI + 360) % 360;
  const man = [];
  let name = feats.length ? feats[0].properties.name : null;
  for (let i = 1; i < P.length - 1; i++) {
    const f = feats[P[i].fi], nm = f.properties.name;
    if (P[i].fi !== P[i - 1].fi && nm && nm !== name) {
      let j = i - 1; while (j > 0 && meters(P[j].p, P[i].p) < 8) j--;
      let k = i + 1; while (k < P.length - 1 && meters(P[i].p, P[k].p) < 8) k++;
      let turn = bearing(P[i].p, P[k].p) - bearing(P[j].p, P[i].p);
      turn = ((turn + 540) % 360) - 180;
      man.push({ d: P[i].d, type: Math.abs(turn) < 35 ? 'straight' : turn > 0 ? 'right' : 'left', street: nm });
    }
    if (nm) name = nm;
  }
  man.push({ d: acc, type: 'arrive', street: '' });
  return { P, man, total: acc };
}
function project(path, pos) {
  let best = null;
  const k = Math.cos(pos.lat * Math.PI / 180) * 111320, kl = 110540;
  for (let i = 1; i < path.P.length; i++) {
    const a = path.P[i - 1], b = path.P[i];
    const ax = (a.p.lng - pos.lng) * k, ay = (a.p.lat - pos.lat) * kl, bx = (b.p.lng - pos.lng) * k, by = (b.p.lat - pos.lat) * kl;
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const u = L2 ? clamp(-(ax * dx + ay * dy) / L2) : 0;
    const x = ax + u * dx, y = ay + u * dy, off = Math.hypot(x, y);
    if (!best || off < best.off) best = { off, d: a.d + u * (b.d - a.d), i };
  }
  return best;
}
function startNav() {
  if (!plan) return;
  const { r, kind, toStop } = navRoute();
  const sim = /[?&]sim=1/.test(location.search) || !navigator.geolocation;
  nav = { r, kind, toStop, path: buildPath(r), progress: 0, off: 0, watch: null, sim, simT: null, voice: false, spoken: -1, dismissed: new Set(), heading: null, last: null, acc: null };
  go('nav');
  if (sim) startSim();
  else {
    nav.watch = navigator.geolocation.watchPosition(onPos, () => { toast(t('m.simNote'), 6000); startSim(); }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 });
  }
}
function startSim() {
  if (!nav) return;
  if (nav.watch != null) { navigator.geolocation.clearWatch(nav.watch); nav.watch = null; }
  nav.sim = true;
  const speed = (mode === 'bike' && !nav.toStop ? 4.2 : 1.35) * 6;   // six times faster than walking, for a demo
  let d = nav.progress;
  clearInterval(nav.simT);
  nav.simT = setInterval(() => {
    d = Math.min(nav.path.total, d + speed / 2);
    const P = nav.path.P;
    let i = 1; while (i < P.length - 1 && P[i].d < d) i++;
    const a = P[i - 1], b = P[i], k = b.d > a.d ? (d - a.d) / (b.d - a.d) : 1;
    onPos({ coords: { latitude: a.p.lat + (b.p.lat - a.p.lat) * k, longitude: a.p.lng + (b.p.lng - a.p.lng) * k, accuracy: 5, heading: null } });
  }, 500);
}
function stopNav() {
  if (!nav) return;
  if (nav.watch != null) navigator.geolocation.clearWatch(nav.watch);
  clearInterval(nav.simT);
  if (window.speechSynthesis) speechSynthesis.cancel();
  nav = null;
  meLayer.clearLayers();
}
function onPos(pos) {
  if (!nav) return;
  const p = L.latLng(pos.coords.latitude, pos.coords.longitude);
  let heading = pos.coords.heading;
  if ((heading == null || isNaN(heading)) && nav.last && meters(nav.last, p) > 3) {
    heading = (Math.atan2((p.lng - nav.last.lng) * Math.cos(p.lat * Math.PI / 180), p.lat - nav.last.lat) * 180 / Math.PI + 360) % 360;
  }
  if (heading != null && !isNaN(heading)) nav.heading = heading;
  nav.last = p;
  nav.acc = pos.coords.accuracy;
  const pr = project(nav.path, p);
  nav.progress = Math.max(nav.progress, pr.d);
  nav.off = pr.off;
  showMe(p.lat, p.lng, nav.heading);
  map.setView(p, Math.max(map.getZoom(), 17), { animate: true });
  if (nav.path.total - nav.progress < 20) {
    const toStop = nav.toStop;
    stopNav();
    toast(t(toStop ? 'm.atStopNow' : 'm.arrived'), 5000);
    go(toStop ? 'stop' : 'results');
    return;
  }
  updateNav();
}
ACT.navVoice = el => { if (!nav) return; nav.voice = !nav.voice; el.setAttribute('aria-pressed', String(nav.voice)); el.setAttribute('aria-label', t(nav.voice ? 'm.voiceOn' : 'm.voiceOff')); };
ACT.navCenter = () => { if (myPos) map.setView(myPos, 17); };
ACT.navStop = () => { const back = nav && nav.toStop ? 'transit' : 'results'; stopNav(); go(back); };
ACT.detour = () => { if (!nav) return; sel = 'better_lit'; stopNav(); startNav(); };
ACT.keep = el => { if (nav) { nav.dismissed.add(+el.dataset.d); updateNav(); } };
ACT.recalcHere = () => { if (!myPos) return; stopNav(); setPoint('A', myPos, t('myLocation')); compute(); };
function renderNav() {
  if (!nav) { go('home', false); return; }
  $('screen').innerHTML = `
  <section class="manoeuvre" aria-label="${esc(t('m.nextMove'))}"><div class="main"><span id="nav-icon"></span><div role="status" aria-live="polite" style="display: flex; flex-direction: column; gap: 4px; min-width: 0"><span class="dist" id="nav-dist"></span><span id="nav-text" style="font-size: 17px; font-weight: 600; line-height: 1.3"></span></div></div><div class="then" id="nav-then"></div></section>
  <div class="side" style="bottom: 300px">
    <button type="button" class="round" data-act="navVoice" aria-pressed="false" aria-label="${esc(t('m.voiceOff'))}">${I.sound()}</button>
    <button type="button" class="round" data-act="navCenter" aria-label="${esc(t('m.centerMe'))}">${I.locate()}</button>
  </div>
  <section class="sheet" style="gap: 12px">
    <div id="nav-warn"></div>
    <div class="row"><div style="display: flex; flex-direction: column; gap: 2px; min-width: 0"><span id="nav-eta" style="font-family: var(--bz-display); font-size: 26px; font-weight: 600; line-height: 1.1"></span><span id="nav-left" class="sec"></span></div>
      <button type="button" class="secondary sm" data-act="navStop" style="flex: none">${I.stopSq()}${esc(t('m.stop'))}</button></div>
    <div style="display: flex; flex-direction: column; gap: 6px"><span id="nav-bar"></span><span class="small" id="nav-foot"></span></div>
  </section>`;
  routeLayer.clearLayers(); markLayer.clearLayers(); lifeLayer.clearLayers();
  if (nav.toStop) drawTransit(); else { drawMain(nav.r, nav.kind); drawWarnings([nav.r]); }
  nav.done = L.polyline([], { renderer: svgR, color: '#333333', weight: 6, interactive: false, lineCap: 'round', lineJoin: 'round' }).addTo(routeLayer);
  map.setView(nav.path.P[0].p, 17);
  updateNav();
}
function placeSide() {
  const side = document.querySelector('#screen .side'), sheet = document.querySelector('#screen .sheet');
  if (side && sheet) side.style.bottom = (phoneRect().bottom - sheet.getBoundingClientRect().top + 12) + 'px';
}
function updateNav() {
  if (!nav || screen !== 'nav' || !$('nav-dist')) return;
  const path = nav.path, pr = nav.progress, man = path.man.find(m => m.d > pr + 5) || path.man[path.man.length - 1];
  const nextI = path.man.indexOf(man), after = path.man[nextI + 1];
  const left = man.d - pr;
  const round = x => (x >= 1000 ? km(x) : (x > 100 ? Math.round(x / 10) * 10 : Math.max(0, Math.round(x / 5) * 5)) + ' m');
  $('nav-icon').innerHTML = (I[man.type] || I.straight)(52);
  $('nav-dist').textContent = round(left);
  $('nav-text').textContent = t('m.turn.' + man.type, { street: man.street });
  $('nav-then').innerHTML = after ? `${(I[after.type] || I.straight)(16)}<span>${esc(t('m.then', { what: t('m.turn.' + after.type, { street: after.street }) }))}</span>` : `<span>${esc(t('m.lastStretch'))}</span>`;
  if (nav.voice && window.speechSynthesis && left < 60 && nav.spoken !== nextI) {
    nav.spoken = nextI;
    const u = new SpeechSynthesisUtterance(`${round(left)}. ${t('m.turn.' + man.type, { street: man.street })}`);
    u.lang = { ro: 'ro-RO', en: 'en-GB', ru: 'ru-RU' }[LANG] || 'ro-RO';
    speechSynthesis.speak(u);
  }
  // the next stretch reported as dark within 500 m: warn, offer the better-lit route if there is one
  const runs = runsOf(nav.r), dark = runs.find(x => x.status === 'dark_reported' && x.to > pr && x.from - pr < 500 && !nav.dismissed.has(Math.round(x.from)));
  const canDetour = !nav.toStop && nav.kind === 'fastest' && plan.verdict.kind !== 'same';
  $('nav-warn').innerHTML = nav.off > 40
    ? `<section class="warnbox"><span style="font-size: 15px; font-weight: 600">${esc(t('m.offRoute', { m: Math.round(nav.off) }))}</span><button type="button" class="primary" data-act="recalcHere" style="height: 44px; font-size: 15px">${esc(t('m.recalcHere'))}</button></section>`
    : dark ? `<section class="warnbox" aria-label="${esc(t('m.ahead'))}"><div style="display: flex; align-items: flex-start; gap: 12px">${I.diamond(22)}<div style="display: flex; flex-direction: column; gap: 3px; min-width: 0"><span style="font-size: 15px; font-weight: 600; line-height: 1.35">${esc(t('m.darkAhead', { d: round(Math.max(0, dark.from - pr)), m: Math.round(dark.len) }))}</span><span class="sec" style="display: flex; align-items: center; gap: 8px">${sample('dark_reported', 30, 3.5)}${esc(t('m.darkSource'))}</span></div></div>` +
      `<div style="display: flex; gap: 8px">${canDetour ? `<button type="button" class="primary" data-act="detour" style="height: 44px; font-size: 15px">${esc(t('m.detour', { min: Math.max(1, extraMin()) }))}</button>` : ''}<button type="button" class="secondary sm" data-act="keep" data-d="${Math.round(dark.from)}">${esc(t('m.keepGoing'))}</button></div></section>`
      : '';
  const remain = path.total - pr, speed = mode === 'bike' && !nav.toStop ? 4.2 : 1.35, minLeft = remain / speed / 60;
  const now = new Date(), arr = fmtHM(now.getHours() * 60 + now.getMinutes() + minLeft);
  $('nav-eta').textContent = `${minN(minLeft)} min · ${arr}`;
  $('nav-left').textContent = t(nav.toStop ? 'm.leftToStop' : 'm.leftToDest', { d: dist(remain), place: nav.toStop ? ride().from.name : labels.B, route: routeTitle(nav.kind).toLowerCase() });
  $('nav-bar').innerHTML = statusBar(nav.r, 8, 5, pr);
  $('nav-foot').innerHTML = `${esc(t('m.lightLeft'))} · <span class="mono" style="font-size: 11px">${nav.sim ? esc(t('m.simTag')) : 'GPS ±' + Math.round(nav.acc || 0) + ' m'}</span> · ${esc(t('m.locStays'))}`;
  const P = path.P, done = [];
  for (const q of P) { if (q.d > pr) break; done.push(q.p); }
  if (myPos) done.push(myPos);
  nav.done.setLatLngs(done);
  placeSide();
}

// ---------- leaving time: two drums that spin with inertia, as on a phone ----------
// Touch scrolls natively (momentum + scroll snap); a mouse can drag and throw the drum too; arrows and Page keys step it.
const ROW = 44, COPIES = 9;                       // the 24 hours and 60 minutes repeat, so the drum turns round
const pad2 = n => String(n).padStart(2, '0');
let tpPrevFocus = null;
function openTimePicker() {
  closeOverlays();
  tpPrevFocus = document.activeElement;
  const now = new Date();
  let h = now.getHours(), m = now.getMinutes();
  if (at) { const v = at.includes('T') ? at.slice(11, 16) : at; [h, m] = v.split(':').map(Number); }
  const drum = (id, n, label) => `<div class="tp-col" id="tp-${id}" tabindex="0" role="spinbutton" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="${n - 1}">` +
    Array.from({ length: n * COPIES }, (_, k) => `<div class="tp-i" data-k="${k}">${pad2(k % n)}</div>`).join('') + '</div>';
  $('overlay').innerHTML = `<div class="tp-back" data-act="tpCancel"></div>
    <section class="tp" id="tp" role="dialog" aria-modal="true" aria-labelledby="tp-title">
      <div class="handle"></div>
      <div class="row"><h2 id="tp-title" style="font-size: 17px; font-weight: 600">${esc(t('m.leaveTime'))}</h2><span class="label" id="tp-day" aria-live="polite"></span></div>
      <div class="tp-wheels"><div class="tp-band" aria-hidden="true"></div>${drum('h', 24, t('m.hours'))}<span class="tp-colon" aria-hidden="true">:</span>${drum('m', 60, t('m.minutes'))}</div>
      <div class="actions"><button type="button" class="secondary" data-act="tpNow" style="width: 112px">${esc(t('m.nowBtn'))}</button><button type="button" class="primary" data-act="tpDone">${esc(t('m.done'))}</button></div>
    </section>`;
  setupDrum($('tp-h'), 24, h);
  setupDrum($('tp-m'), 60, m);
  tpDay();
  $('tp-h').focus({ preventScroll: true });
}
function tpValue() {
  const v = el => Math.round(el.scrollTop / ROW) % el._n;
  return { h: v($('tp-h')), m: v($('tp-m')) };
}
// the server reads a clock time more than an hour ago as tomorrow (backend/app.py, leaving_time): say so here
function tpDay() {
  const el = $('tp-day');
  if (!el || !$('tp-h')._n || !$('tp-m')._n) return;
  const { h, m } = tpValue(), now = new Date(), mins = now.getHours() * 60 + now.getMinutes();
  el.textContent = h * 60 + m < mins - 60 ? t('m.tomorrow') : t('m.today');
}
function closeTimePicker(changed) {
  closeOverlays();
  if (tpPrevFocus && tpPrevFocus.focus) tpPrevFocus.focus({ preventScroll: true });
  if (!changed) return;
  if (screen === 'home') renderHome();
  if (A && B) { saveHash(); if (screen !== 'home') compute(); }
}
function setupDrum(el, n, value) {
  const total = n * COPIES, middle = Math.floor(COPIES / 2) * n;
  el._n = n;
  el.scrollTop = (middle + value) * ROW;
  let raf = 0, idle = 0, on = null;
  const index = () => Math.round(el.scrollTop / ROW);
  const mark = () => {
    raf = 0;
    const k = index(), item = el.children[k];
    if (on !== item) { if (on) on.classList.remove('on'); if (item) item.classList.add('on'); on = item; }
    el.setAttribute('aria-valuenow', k % n);
    el.setAttribute('aria-valuetext', pad2(k % n));
    tpDay();
  };
  // keep the drum near its middle copy, so it never reaches an end
  const recentre = () => { const k = index(); if (k < n || k >= total - n) el.scrollTop = (middle + (k % n)) * ROW; };
  el.addEventListener('scroll', () => {
    if (!raf) raf = requestAnimationFrame(mark);
    clearTimeout(idle);
    idle = setTimeout(recentre, 160);
  }, { passive: true });
  mark();
  el.addEventListener('keydown', e => {
    const step = { ArrowUp: -1, ArrowDown: 1, PageUp: -5, PageDown: 5 }[e.key];
    if (step) { e.preventDefault(); el.scrollTo({ top: (index() + step) * ROW, behavior: reduced() ? 'auto' : 'smooth' }); }
    else if (e.key === 'Enter') { e.preventDefault(); ACT.tpDone(); }
  });
  // a mouse: drag and throw, with the speed decaying as on a phone, then settle on a row
  let drag = null, glide = 0;
  el.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    cancelAnimationFrame(glide);
    el.setPointerCapture(e.pointerId);
    el.style.scrollSnapType = 'none';
    drag = { y: e.clientY, t: performance.now(), v: 0, moved: 0 };
  });
  el.addEventListener('pointermove', e => {
    if (!drag) return;
    const now = performance.now(), dy = e.clientY - drag.y, dt = Math.max(1, now - drag.t);
    el.scrollTop -= dy;
    drag.v = 0.8 * (-dy / dt) + 0.2 * drag.v;        // px per ms, smoothed
    drag.moved += Math.abs(dy);
    drag.y = e.clientY; drag.t = now;
  });
  const settle = () => { el.style.scrollSnapType = ''; el.scrollTo({ top: index() * ROW, behavior: 'smooth' }); };
  el.addEventListener('pointerup', e => {
    if (!drag) return;
    const d = drag;
    drag = null;
    if (d.moved < 4) {                                  // a click on a number: bring it to the centre
      const item = document.elementFromPoint(e.clientX, e.clientY);
      el.style.scrollSnapType = '';
      if (item && item.dataset.k != null) el.scrollTo({ top: +item.dataset.k * ROW, behavior: 'smooth' });
      return;
    }
    let v = d.v, last = performance.now();
    const fly = now => {
      const dt = now - last; last = now;
      el.scrollTop += v * dt;
      v *= Math.pow(0.994, dt);                         // friction
      if (Math.abs(v) > 0.03) glide = requestAnimationFrame(fly); else settle();
    };
    glide = requestAnimationFrame(fly);
  });
  el.addEventListener('pointercancel', () => { drag = null; settle(); });
}
// ---------- toast ----------
let toastTimer = null;
function toast(text, ms = 7000) {
  const el = $('toast');
  el.innerHTML = `<span>${esc(text)}</span><button type="button" class="round" style="width: 32px; height: 32px; border: 0; background: transparent" aria-label="${esc(t('m.close'))}">${I.close()}</button>`;
  el.hidden = false;
  el.querySelector('button').onclick = hideToast;
  clearTimeout(toastTimer);
  if (ms) toastTimer = setTimeout(hideToast, ms);
}
function hideToast() { $('toast').hidden = true; }

// ---------- map clicks: put B (or A) after "tap the map" ----------
map.on('click', e => {
  if (pickMode) {
    const which = pickMode;
    pickMode = null;
    hideToast();
    setPoint(which, e.latlng, t('m.pointOnMap'));
    if (A && B) compute(); else if (which === 'B') locate(true); else openSearch('B');
    return;
  }
  if (tip || legendOpen || aboutOpen) closeOverlays();
});
map.on('moveend', () => { clearTimeout(map._netT); map._netT = setTimeout(refreshNet, 200); });
// the phone's height changes when the browser hides its address bar (100dvh), or the tab was laid out while hidden
const onResize = () => { map.invalidateSize(); placePlusChip(); refreshNet(); };
if (window.ResizeObserver) new ResizeObserver(onResize).observe($('phone')); else window.addEventListener('resize', onResize);

// ---------- start ----------
document.documentElement.lang = t('htmlLang');
$('map').setAttribute('aria-label', t('mapLabel'));
buildSearch();
history.replaceState({ screen: 'home' }, '');
renderHome();
getJSON('/api/summary').then(s => {
  summary = s;
  if (s.area_geometry) L.geoJSON(s.area_geometry, { interactive: false, style: { color: '#6B6B6B', weight: 1, dashArray: '2 5', fill: false } }).addTo(areaLayer);
  const [w, so, e, n] = s.bounds_wsen;
  if (screen === 'home' && !location.hash) fit(L.latLngBounds([[so, w], [n, e]]), 15);
  if (screen === 'home') renderHome();
  refreshNet();
}).catch(err => toast(t('serverDown', { msg: err.message })));
let back = null;
try { back = JSON.parse(sessionStorage.getItem('bz.back') || 'null'); sessionStorage.removeItem('bz.back'); } catch (e) { back = null; }
if (readHash()) {
  if (back && back.screen === 'home') { fit(L.latLngBounds([A, B]).pad(0.3)); }
  else {
    if (back) { quietReveal = true; restoreTo = back; }
    compute();
  }
}
