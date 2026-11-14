'use strict';
/* Extra map layers built by demo/layers/build_layers.py (data/out/layers/*.geojson).
   Usage: ExtraLayers.add(map, layerControl, '<url of data/out/layers/>', { on: ['bike'], lang: 'ro', bounds: L.latLngBounds(...) })
   lang: 'ru' (default), 'ro' or 'en'. bounds: keep only features with a point inside (the page's covered area).
   Every layer is optional: a missing file is skipped with a console warning. See README.md in this folder. */
(function () {
  const COLORS = {
    lit_confirmed: { c: '#009E73', d: null },
    lit_likely: { c: '#E69F00', d: '9 6' },
    unknown: { c: '#7F7F7F', d: '1 7' },
    dark_reported: { c: '#D55E00', d: '13 5 2 5' },
  };
  const TEXT = {
    ru: {
      st: { lit_confirmed: 'освещение подтверждено', lit_likely: 'фонари только на части', unknown: 'нет данных', dark_reported: 'в OSM отмечено «не освещено»' },
      bike: { cycleway: 'отдельная велодорожка', lane: 'велополоса на улице', designated: 'тротуар или дорожка, велосипед разрешён' },
      dow: ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'], noName: 'без названия', m: 'м', notSet: 'не указано',
      bikeLamps: 'фонари Mapillary в 20 м на {cov}% длины', today: ' (сегодня)', none: 'нет',
      night: 'последние рейсы {last}; после 22:00 отправлений: {n}', lines: 'Линии: ',
      gtfs: 'По расписанию GTFS SMTT; 24:10 значит 00:10 следующей ночи.',
      labels: { bike: 'Велодорожки: освещение (фиолетовая обводка)', stops: 'Остановки: последние рейсы ночью', routes: 'Линии транспорта',
        zones: 'Районы: доля улиц с данными об освещении (%)' },
    },
    ro: {
      st: { lit_confirmed: 'iluminat confirmat', lit_likely: 'stâlpi doar pe o parte', unknown: 'fără date', dark_reported: 'marcat în OSM ca neiluminat' },
      bike: { cycleway: 'pistă de biciclete separată', lane: 'bandă de biciclete pe stradă', designated: 'trotuar sau alee, bicicleta permisă' },
      dow: ['du', 'lu', 'ma', 'mi', 'jo', 'vi', 'sâ'], noName: 'fără nume', m: 'm', notSet: 'nespecificat',
      bikeLamps: 'stâlpi Mapillary la cel mult 20 m pe {cov}% din lungime', today: ' (azi)', none: 'niciuna',
      night: 'ultimele curse {last}; plecări după 22:00: {n}', lines: 'Linii: ',
      gtfs: 'După orarul GTFS SMTT; 24:10 înseamnă 00:10 în noaptea următoare.',
      labels: { bike: 'Piste de biciclete: iluminat (contur violet)', stops: 'Stații: ultimele curse noaptea', routes: 'Linii de transport public',
        zones: 'Cartiere: ponderea străzilor cu date despre iluminat (%)' },
    },
    en: {
      st: { lit_confirmed: 'lighting confirmed', lit_likely: 'street lights on part of it only', unknown: 'no data', dark_reported: 'tagged in OSM as not lit' },
      bike: { cycleway: 'separate cycle track', lane: 'cycle lane on the street', designated: 'sidewalk or path, bicycles allowed' },
      dow: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], noName: 'unnamed', m: 'm', notSet: 'not set',
      bikeLamps: 'Mapillary street lights within 20 m on {cov}% of the length', today: ' (today)', none: 'none',
      night: 'last departures {last}; departures after 22:00: {n}', lines: 'Lines: ',
      gtfs: 'From the SMTT GTFS timetable; 24:10 means 00:10 the next night.',
      labels: { bike: 'Cycle lanes: lighting (purple outline)', stops: 'Stops: last departures at night', routes: 'Public transport lines',
        zones: 'Districts: share of streets with lighting data (%)' },
    },
  };
  let T = TEXT.ru;
  const fill = (s, vars) => Object.entries(vars).reduce((acc, [k, v]) => acc.split('{' + k + '}').join(String(v)), s);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const getJSON = url => fetch(url).then(r => { if (!r.ok) throw new Error(url + ': HTTP ' + r.status); return r.json(); });
  const localDate = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const dayLabel = iso => { const d = new Date(iso + 'T12:00:00'); return `${T.dow[d.getDay()]} ${iso.slice(8, 10)}.${iso.slice(5, 7)}`; };

  // keep a feature if one of its points lies inside the bounds (lines that only cross the edge stay whole)
  function within(fc, bounds) {
    if (!bounds) return fc;
    const points = g => g.type === 'Point' ? [g.coordinates] : g.type === 'LineString' ? g.coordinates
      : g.type === 'MultiLineString' ? g.coordinates.flat() : [];
    return { ...fc, features: fc.features.filter(f => f.geometry && points(f.geometry).some(c => bounds.contains([c[1], c[0]]))) };
  }

  function bikeLayer(fc) {
    const g = L.layerGroup();
    const order = ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported'];
    const feats = fc.features.slice().sort((a, b) => order.indexOf(a.properties.status) - order.indexOf(b.properties.status));
    for (const f of feats) {
      const p = f.properties, s = COLORS[p.status] || COLORS.unknown, ll = f.geometry.coordinates.map(c => [c[1], c[0]]);
      L.polyline(ll, { color: '#6a3d9a', weight: 9, opacity: 0.55, interactive: false }).addTo(g);
      L.polyline(ll, { color: s.c, weight: 4, dashArray: s.d, bubblingMouseEvents: false })
        .bindPopup(`<b>${esc(p.name || T.noName)}</b> · ${esc(T.bike[p.cat] || p.cat)} · ${Math.round(p.len)} ${T.m}<br>` +
          `<span style="color:${s.c}">&#9632;</span> ${esc(T.st[p.status] || T.st.unknown)}<br>OSM lit: ${esc(p.lit || T.notSet)}; ` +
          `${esc(fill(T.bikeLamps, { cov: Math.round(100 * p.lamp_cov) }))}<br><small>way/${esc(p.osm_id)}</small>`)
        .addTo(g);
    }
    return g;
  }

  function stopsLayer(fc) {
    const g = L.layerGroup(), today = localDate();
    for (const f of fc.features) {
      const p = f.properties, [lon, lat] = f.geometry.coordinates;
      const dates = Object.keys(p.night || {}).sort();
      const show = dates.includes(today) ? [today] : dates;
      const rows = show.map(d => {
        const n = p.night[d];
        const last = n.last.slice(0, 6).map(([ln, tm]) => `${esc(ln)} — ${esc(tm)}`).join(', ');
        return `<li><b>${dayLabel(d)}${d === today ? T.today : ''}</b>: ${fill(T.night, { last: last || T.none, n: n.n22 })}</li>`;
      }).join('');
      L.circleMarker([lat, lon], { radius: 4, color: '#1d3f8f', weight: 2, fillColor: '#fff', fillOpacity: 1, bubblingMouseEvents: false })
        .bindPopup(`<b>${esc(p.name)}</b><br>${T.lines}${p.lines.map(esc).join(', ') || '—'}<ul>${rows}</ul>` +
          `<small>${esc(T.gtfs)}</small>`, { maxWidth: 360 })
        .addTo(g);
    }
    return g;
  }

  function routesLayer(fc) {
    const g = L.layerGroup();
    for (const f of fc.features) {
      const p = f.properties;
      L.polyline(f.geometry.coordinates.map(c => [c[1], c[0]]), { color: '#' + (p.color || '555'), weight: 3, opacity: 0.75 })
        .bindTooltip(`${esc(p.short_name)}: ${esc(p.long_name)}`, { sticky: true })
        .addTo(g);
    }
    return g;
  }

  // Polygons sit in a pane below the lines and do not take clicks (they would block the segments above);
  // the share is shown as a permanent label in the middle of each district.
  function zonesLayer(fc, map) {
    if (!map.getPane('zonesPane')) map.createPane('zonesPane').style.zIndex = 350;
    const g = L.layerGroup();
    for (const f of fc.features) {
      const p = f.properties, pct = p.pct_any;
      const fillOpacity = pct == null ? 0 : 0.06 + 0.45 * pct / 100;
      const poly = L.geoJSON(f, { pane: 'zonesPane', interactive: false,
        style: { color: '#1d3f8f', weight: 1.5, fillColor: '#1d3f8f', fillOpacity } }).addTo(g);
      L.tooltip({ permanent: true, direction: 'center', className: 'zone-label', interactive: false })
        .setLatLng(poly.getBounds().getCenter())
        .setContent(`${esc(p.name)}<br><b>${pct == null ? '?' : Math.round(pct) + '%'}</b>`)
        .addTo(g);
    }
    return g;
  }

  const LAYERS = [
    { key: 'bike', file: 'bike_lanes.geojson', build: bikeLayer },
    { key: 'stops', file: 'transit_stops.geojson', build: stopsLayer },
    { key: 'routes', file: 'transit_routes.geojson', build: routesLayer },
    { key: 'zones', file: 'zones.geojson', build: zonesLayer },
  ];

  const style = document.createElement('style');
  style.textContent = '.leaflet-tooltip.zone-label{background:rgba(255,255,255,.85);border:1px solid #1d3f8f;' +
    'box-shadow:none;color:#10245a;font-size:11px;line-height:1.2;text-align:center;padding:2px 5px}' +
    '.leaflet-tooltip.zone-label:before{display:none}';
  document.head.appendChild(style);

  window.ExtraLayers = {
    add(map, control, base, opts = {}) {
      // ?layers=bike,stops,routes,zones in the page URL switches layers on, e.g. for a link sent to testers
      const fromUrl = (new URLSearchParams(location.search).get('layers') || '').split(',').filter(Boolean);
      const on = new Set([...(opts.on || []), ...fromUrl]);
      const skip = new Set(opts.skip || []);
      T = TEXT[opts.lang] || TEXT.ru;
      return Promise.all(LAYERS.filter(def => !skip.has(def.key)).map(def => getJSON(base + def.file)
        .then(fc => {
          const layer = def.build(def.key === 'zones' ? fc : within(fc, opts.bounds), map);
          control.addOverlay(layer, T.labels[def.key]);
          if (on.has(def.key)) layer.addTo(map);
          return layer;
        })
        .catch(err => { console.warn('extra layer skipped:', err.message); return null; })));
    },
  };
})();
