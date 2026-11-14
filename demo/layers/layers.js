'use strict';
/* Extra map layers built by demo/layers/build_layers.py (data/out/layers/*.geojson).
   Usage: ExtraLayers.add(map, layerControl, '<url of data/out/layers/>', { on: ['bike'] })
   Every layer is optional: a missing file is skipped with a console warning. See README.md in this folder. */
(function () {
  const ST = {
    lit_confirmed: { c: '#009E73', d: null, t: 'освещение подтверждено' },
    lit_likely: { c: '#E69F00', d: '9 6', t: 'фонари только на части' },
    unknown: { c: '#7F7F7F', d: '1 7', t: 'нет данных' },
    dark_reported: { c: '#D55E00', d: '13 5 2 5', t: 'в OSM отмечено «не освещено»' },
  };
  const BIKE_CAT = { cycleway: 'отдельная велодорожка', lane: 'велополоса на улице', designated: 'тротуар или дорожка, велосипед разрешён' };
  const DOW = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const getJSON = url => fetch(url).then(r => { if (!r.ok) throw new Error(url + ': HTTP ' + r.status); return r.json(); });
  const localDate = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const dayLabel = iso => { const d = new Date(iso + 'T12:00:00'); return `${DOW[d.getDay()]} ${iso.slice(8, 10)}.${iso.slice(5, 7)}`; };

  function bikeLayer(fc) {
    const g = L.layerGroup();
    const order = ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported'];
    const feats = fc.features.slice().sort((a, b) => order.indexOf(a.properties.status) - order.indexOf(b.properties.status));
    for (const f of feats) {
      const p = f.properties, s = ST[p.status] || ST.unknown, ll = f.geometry.coordinates.map(c => [c[1], c[0]]);
      L.polyline(ll, { color: '#6a3d9a', weight: 9, opacity: 0.55, interactive: false }).addTo(g);
      L.polyline(ll, { color: s.c, weight: 4, dashArray: s.d, bubblingMouseEvents: false })
        .bindPopup(`<b>${esc(p.name || 'без названия')}</b> · ${BIKE_CAT[p.cat] || esc(p.cat)} · ${Math.round(p.len)} м<br>` +
          `<span style="color:${s.c}">&#9632;</span> ${s.t}<br>OSM lit: ${esc(p.lit || 'не указано')}; фонари Mapillary в 20 м на ${Math.round(100 * p.lamp_cov)}% длины` +
          `<br><small>way/${esc(p.osm_id)}</small>`)
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
        const last = n.last.slice(0, 6).map(([ln, t]) => `${esc(ln)} — ${esc(t)}`).join(', ');
        return `<li><b>${dayLabel(d)}${d === today ? ' (сегодня)' : ''}</b>: последние рейсы ${last || 'нет'}; после 22:00 отправлений: ${n.n22}</li>`;
      }).join('');
      L.circleMarker([lat, lon], { radius: 4, color: '#1d3f8f', weight: 2, fillColor: '#fff', fillOpacity: 1, bubblingMouseEvents: false })
        .bindPopup(`<b>${esc(p.name)}</b><br>Линии: ${p.lines.map(esc).join(', ') || '—'}<ul>${rows}</ul>` +
          '<small>По расписанию GTFS SMTT; 24:10 значит 00:10 следующей ночи.</small>', { maxWidth: 360 })
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
    { key: 'bike', file: 'bike_lanes.geojson', label: 'Велодорожки по городу: освещение (фиолетовая обводка)', build: bikeLayer },
    { key: 'stops', file: 'transit_stops.geojson', label: 'Остановки: последние рейсы ночью', build: stopsLayer },
    { key: 'routes', file: 'transit_routes.geojson', label: 'Линии транспорта', build: routesLayer },
    { key: 'zones', file: 'zones.geojson', label: 'Районы: доля улиц с данными об освещении (%)', build: zonesLayer },
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
      return Promise.all(LAYERS.map(def => getJSON(base + def.file)
        .then(fc => {
          const layer = def.build(fc, map);
          control.addOverlay(layer, def.label);
          if (on.has(def.key)) layer.addTo(map);
          return layer;
        })
        .catch(err => { console.warn('extra layer skipped:', err.message); return null; })));
    },
  };
})();
