"""Prepare and inspect a separate northeast coverage dataset; never switches the API.

Run from the repository with --data <unihack-data> and one phase:
boundary, refine, places, audit, verify. Build streets/transit with the existing backend builders.
"""
import argparse
import gzip
import hashlib
import json
import math
import shutil
from pathlib import Path
import sys

import numpy as np
import shapely
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import build_city as bc
from backend.routing import Network, bike_access, walk_allowed

AREA = ROOT / 'config/area-expanded.geojson'
OUT = ROOT / 'data/out/city-expanded'
QA = ROOT / 'data/cache/expansion'
BASELINE_AREA = ROOT / 'config/area.geojson'
BASELINE_OUT = ROOT / 'data/out/city'
EXTRA_QUERIES = []
SLUGS = ['fabric', 'tipografilor', 'badea-cartan-kogalniceanu', 'telegrafului-dorobanti']


def read(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')


def metric(g):
    return shapely.transform(g, lambda a: a * [bc.KX, bc.KY])


def lonlat(g):
    return shapely.transform(g, lambda a: a / [bc.KX, bc.KY])


def sources(data):
    result = {}
    for name in ['city_zones', 'mapillary_street_lights', 'sesizari_iluminat',
                 'osm_highways', 'osm_pois', 'transit_stops', 'transit_routes']:
        path = data / 'geojson' / (name + '.geojson')
        fc = read(path)
        assert fc['features'], f'Empty input: {path}'
        result[name] = {'features': len(fc['features']), 'bytes': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    feeds = sorted((data / 'gtfs').glob('*.zip'))
    assert feeds, 'No GTFS zip files'
    result['gtfs'] = [p.name for p in feeds]
    return result


def boundary(data):
    inputs = sources(data)
    zones = {f['properties']['slug']: shape(f['geometry']) for f in read(data / 'geojson/city_zones.geojson')['features']}
    old = shape(read(BASELINE_AREA)['features'][0]['geometry'])
    modern = zones['modern-crisan-ghiroda-noua'].intersection(box(21, 45, 21.275, 46))
    selected = unary_union([metric(old), metric(modern)] + [metric(zones[s]) for s in SLUGS])
    # Close administrative seams, then fill internal holes. Keep the approved area
    # intact: rounding must not remove its corners or any selected neighbourhood.
    rounded = selected.buffer(150).buffer(-150)
    assert rounded.geom_type == 'Polygon', 'Expansion would have disconnected islands'
    final = unary_union([selected.buffer(.2), Polygon(rounded.exterior).buffer(.2)])
    assert final.geom_type == 'Polygon', 'Disconnected expansion after closing'
    final = Polygon(final.exterior)
    assert final.is_valid and not final.interiors
    assert final.covers(metric(old))
    geo = lonlat(final.simplify(5, preserve_topology=True).buffer(5))
    # Union again after simplification so existing coverage is preserved exactly.
    geo = unary_union([geo, old])
    geo = Polygon(geo.exterior)
    assert geo.is_valid and geo.covers(old)
    props = {'name': 'University district, centre and northeast neighbourhoods',
             'description': 'Candidate expansion: Fabric, Tipografilor, Badea Cartan/Kogalniceanu, '
                            'Telegrafului/Dorobanti and western Modern (east <= 21.275); '
                            'administrative gaps closed at 150 m and internal holes filled.',
             'area_km2': round(metric(geo).area / 1e6, 3), 'candidate': True}
    save(AREA, {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': props, 'geometry': mapping(geo)}]})
    save(QA / 'inputs.json', {'inputs': inputs, 'area_km2': props['area_km2'],
                            'selected_zones': SLUGS + ['western modern-crisan-ghiroda-noua'],
                            'area_sha256': hashlib.sha256(AREA.read_bytes()).hexdigest()})
    print(json.dumps({'area_km2': props['area_km2'], 'bounds': geo.bounds, 'polygon': str(AREA)}, ensure_ascii=True), flush=True)


def places(data):
    from backend import build_places as bp
    original = bp.overpass
    key = hashlib.sha256(AREA.read_bytes()).hexdigest()[:16]
    cache_path = QA / f'places-{key}.json'
    manifest = QA / 'inputs.json'
    broad_area = QA / 'broad-area.geojson'
    if manifest.exists() and broad_area.exists():
        broad_key = read(manifest)['area_sha256'][:16]
        broad_path = QA / f'places-{broad_key}.json'
        if broad_path.exists() and shape(read(broad_area)['features'][0]['geometry']).buffer(.00001).covers(shape(read(AREA)['features'][0]['geometry'])):
            cache_path = broad_path
    # The production builder's single cache otherwise silently reuses the old area.
    bp.overpass = lambda area, cache, refresh: original(area, cache_path, refresh)
    if not (OUT / 'segments.geojson.gz').exists():
        bp.overpass(shape(read(AREA)['features'][0]['geometry']), None, False)
        print('Expanded addresses/POIs cached; run places again after the street build.', flush=True)
        return
    sys.argv = ['build_places.py', '--data', str(data), '--area', AREA.relative_to(ROOT).as_posix(),
                '--segments', str(OUT / 'segments.geojson.gz'), '--out', str(OUT / 'places.json.gz')]
    bp.main()


def refine(data):
    """Remove failed fringe cells, preserving the current area and a single polygon.

    Reuse the freshly downloaded broad graph with complete OSM edges: the final
    graph is a spatial subset, not a second potentially inconsistent download.
    """
    result = read(QA / 'audit.json')
    prior = read(AREA)
    area = metric(shape(prior['features'][0]['geometry']))
    old = metric(shape(read(BASELINE_AREA)['features'][0]['geometry']))
    bad = [box(c['x'], c['y'], c['x'] + 600, c['y'] + 600)
           for c in result['grid_600m'] if not c['passes']]
    failed_modern = any(not r['passes'] and r['zone'] == 'modern-crisan-ghiroda-noua' for r in result['zones_added'])
    assert bad or failed_modern, 'No failed fringe cells or districts to remove'
    trimmed = area.difference(unary_union(bad).difference(old)) if bad else area
    if failed_modern and not bad:
        # The 21.265 cap was evaluated against the actual classified network;
        # farther eastern fringe still has >1/3 of streets without evidence.
        trimmed = unary_union([trimmed.intersection(metric(box(21, 45, 21.265, 46))), old])
    if trimmed.geom_type == 'MultiPolygon':
        trimmed = next(p for p in trimmed.geoms if p.buffer(.01).covers(old))
    assert trimmed.geom_type == 'Polygon' and not trimmed.interiors, 'Trimming would create an internal hole'
    # Round the new inward corners without reintroducing the excluded squares.
    rounded = trimmed.buffer(-25).buffer(25)
    final = unary_union([rounded, old])
    assert final.geom_type == 'Polygon' and not final.interiors and final.covers(old)
    if not (QA / 'broad-audit.json').exists():
        save(QA / 'broad-audit.json', result)
        save(QA / 'broad-area.geojson', prior)
    cache = ROOT / 'data/cache/city/network-area-expanded.json.gz'
    broad_cache = QA / 'network-broad.json.gz'
    if not broad_cache.exists():
        shutil.copyfile(cache, broad_cache)
    broad = read(broad_cache)
    # Keep whole edges touching a 20 m routing margin. No synthetic road or
    # connection is added; original u/v connectivity and access tags survive.
    border = final.buffer(20)
    selected = [s for s in broad['segments'] if metric(shapely.LineString(s['ll'])).intersects(border)]
    broad['segments'] = selected
    geo = lonlat(final.simplify(1, preserve_topology=True))
    geo = unary_union([geo, lonlat(old)])
    geo = Polygon(geo.exterior)
    props = {**prior['features'][0]['properties'], 'area_km2': round(metric(geo).area / 1e6, 3),
             'quality_refinement': 'Exclude 600 m fringe cells with >=50% unknown or reported-dark street length '
                                   '(also check pedestrian paths where >=1 km is mapped); '
                                   'round inward corners, preserve old area. Source date 2026-11-15.',
             'removed_fringe_cells': prior['features'][0]['properties'].get('removed_fringe_cells', 0) + len(bad)}
    if failed_modern and not bad:
        props['quality_refinement'] += ' Eastern limit tightened to 21.265 after district-level quality check.'
        props['eastern_limit'] = 21.265
    props['initial_candidate_area_km2'] = read(QA / 'inputs.json')['area_km2']
    props['description'] = 'Quality-filtered northeast candidate. Fabric, Tipografilor, Badea Cartan/Kogalniceanu, Telegrafului/Dorobanti and a western fragment of Modern; existing coverage preserved.'
    save(AREA, {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': props, 'geometry': mapping(geo)}]})
    broad['boundary_sha256'] = hashlib.sha256(AREA.read_bytes()).hexdigest()
    broad['subset_of'] = 'data/cache/expansion/network-broad.json.gz'
    with gzip.open(cache, 'wt', encoding='utf-8') as f:
        json.dump(broad, f, ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({'refined_km2': props['area_km2'], 'removed_cells': len(bad), 'segments_retained': len(selected)}, ensure_ascii=True), flush=True)
    sys.argv = ['build_city.py', '--data', str(data), '--area', 'config/area-expanded.geojson',
                '--out', str(OUT), '--as-of', '2026-11-15']
    bc.main()


def audit(data):
    fc = read(OUT / 'segments.geojson.gz')
    summary = read(OUT / 'summary.json')
    net = Network(fc['features'], fc['meta'])
    area = metric(shape(read(AREA)['features'][0]['geometry']))
    old = metric(shape(read(BASELINE_AREA)['features'][0]['geometry']))
    core = np.array([i for i, p in enumerate(net.props) if p['kind'] in bc.GROUPS['streets_and_sidewalks']], dtype=int)
    lines = net.lines[core]
    tree = shapely.STRtree(lines)
    walking = np.array([i for i, p in enumerate(net.props) if walk_allowed(p) and p['kind'] != 'service'], dtype=int)
    walking_lines = net.lines[walking]
    walking_tree = shapely.STRtree(walking_lines)

    def shares(poly, paths=False):
        selected, selected_lines, selected_tree = (walking, walking_lines, walking_tree) if paths else (core, lines, tree)
        ix = selected_tree.query(poly, predicate='intersects')
        lengths = shapely.length(shapely.intersection(selected_lines[ix], poly))
        total = float(sum(lengths))
        lengths_by_status = {s: float(sum(v for j, v in zip(ix, lengths) if net.props[selected[j]]['status'] == s)) for s in bc.STATUSES}
        return {'street_km': round(total / 1000, 3), **{s: round(100 * v / total, 2) if total else 0 for s, v in lengths_by_status.items()}}

    zones = []
    for f in read(data / 'geojson/city_zones.geojson')['features']:
        part = metric(shape(f['geometry'])).intersection(area).difference(old)
        if part.area < 1000:
            continue
        row = {'zone': f['properties']['slug'], 'added_km2': round(part.area / 1e6, 3), **shares(part)}
        if row['street_km'] > .1:
            row['passes'] = row['unknown'] <= 33.33 and row['dark_reported'] < 40
            zones.append(row)

    cells = []
    w, s, e, n = area.bounds
    for x in range(math.floor(w / 600) * 600, math.ceil(e / 600) * 600, 600):
        for y in range(math.floor(s / 600) * 600, math.ceil(n / 600) * 600, 600):
            tile = box(x, y, x + 600, y + 600).intersection(area).difference(old)
            row = {'x': x, 'y': y, **shares(tile)}
            walking_stats = shares(tile, paths=True)
            row['walking_with_paths'] = walking_stats
            if row['street_km'] >= .5 or walking_stats['street_km'] >= 1:
                row['passes'] = (row['street_km'] < .5 or (row['unknown'] < 50 and row['dark_reported'] < 50)) and (walking_stats['street_km'] < 1 or (walking_stats['unknown'] < 50 and walking_stats['dark_reported'] < 50))
                cells.append(row)

    connectivity = {}
    for mode, graph in net.graphs.items():
        flags = graph['routable']
        length = sum(net.len[i] for i, ok in enumerate(flags) if ok)
        connectivity[mode] = {'segments': sum(flags), 'km': round(length / 1000, 2)}
    # Independently verify that each added neighbourhood's road network is served
    # by the connected graph and routes to/from central Cetate in both modes.
    routes = []
    for row in zones:
        if row['street_km'] < .5:
            continue
        poly = metric(next(shape(f['geometry']) for f in read(data / 'geojson/city_zones.geojson')['features'] if f['properties']['slug'] == row['zone'])).intersection(area).difference(old)
        for mode in ['walk', 'bike']:
            ids = [i for i in core if poly.covers(net.lines[i].interpolate(.5, normalized=True))]
            served = [i for i in ids if net.graphs[mode]['routable'][i]]
            eligible = [i for i in ids if (walk_allowed(net.props[i]) if mode == 'walk' else bike_access(net.props[i]) is not None)]
            total = sum(net.len[i] for i in eligible) or 1
            served_pct = 100 * sum(net.len[i] for i in served) / total
            ok = False
            if served:
                point = net.lines[max(served, key=lambda i: net.len[i])].interpolate(.5, normalized=True)
                start = net.snap(45.7538, 21.2259, mode=mode)
                end = net.snap(point.y / bc.KY, point.x / bc.KX, mode=mode)
                ok = start is not None and end is not None and net.plan(start, end, mode=mode) is not None and net.plan(end, start, mode=mode) is not None
            routes.append({'zone': row['zone'], 'mode': mode, 'eligible_core_length_routable_pct': round(served_pct, 1), 'round_trip_to_centre': ok})
    result = {'as_of': summary['as_of'], 'area_km2': round(area.area / 1e6, 3),
              'single_polygon': area.geom_type == 'Polygon', 'holes': len(area.interiors),
              'existing_area_preserved': area.buffer(.01).covers(old),
              'all': shares(area), 'added': shares(area.difference(old)), 'zones_added': zones,
              'grid_600m': cells, 'connectivity': connectivity, 'route_checks': routes,
              'quality_passes': all(r['passes'] for r in zones + cells),
              'routing_passes': all(r['round_trip_to_centre'] for r in routes)}
    for name in ['places', 'transit']:
        path = OUT / f'{name}.json.gz'
        if path.exists():
            d = read(path)
            result[name] = d.get('meta', {}) if name == 'places' else {'stops': len(d['stops']), 'routes': len(d['routes']), 'days': {k: len(v) for k, v in d['days'].items()}}
    save(QA / 'audit.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ['grid_600m', 'zones_added', 'route_checks']}, ensure_ascii=True, indent=1), flush=True)
    print('district failures:', json.dumps([r for r in zones if not r['passes']]), flush=True)
    print('grid failures:', json.dumps([r for r in cells if not r['passes']]), flush=True)


def verify(data):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.history import History
    result = read(QA / 'audit.json')
    assert result['quality_passes'] and result['routing_passes']
    assert result['existing_area_preserved'] and result['single_polygon'] and not result['holes']
    area = shape(read(AREA)['features'][0]['geometry'])
    places_data = read(OUT / 'places.json.gz')
    assert all(area.covers(shapely.Point(e['lon'], e['lat'])) for e in places_data['entries'] if e['k'] in ['place', 'addr'])
    tt = read(OUT / 'transit.json.gz')
    assert all(tt['days'].get(day) for day in ['2026-11-15', '2026-11-16', '2026-11-17'])
    checks = []
    with TestClient(create_app(segments_path=OUT / 'segments.geojson.gz', live_fetch=lambda: {'vehicles': []}, history=History(lambda *_: {}))) as client:
        for url in ['/api/health', '/api/summary', '/api/transit/live']:
            response = client.get(url)
            assert response.status_code == 200, (url, response.text)
            checks.append({'url': url, 'http': response.status_code})
        summary = client.get('/api/summary').json()
        response = client.get('/api/segments', params={'bbox': ','.join(str(v) for v in summary['bounds_wsen']), 'limit': 20000})
        layer = response.json()
        assert response.status_code == 200 and not layer['truncated'] and len(layer['features']) == layer['count'] > 0
        checks.append({'url': '/api/segments', 'http': 200, 'count': layer['count'], 'limit': 20000, 'truncated': False})
        for query in ['Piata Traian', 'Badea Cartan', 'Telegrafului', 'Tipografilor', 'Matasarilor'] + EXTRA_QUERIES:
            response = client.get('/api/geocode', params={'q': query})
            found = response.json()['results']
            assert found, f'Expanded search has no result for {query}'
            dest = found[0]
            for mode in ['walk', 'bike', 'transit']:
                response = client.get('/api/route', params={'from': '45.7470,21.2395',
                                      'to': f"{dest['lat']},{dest['lon']}", 'mode': mode, 'at': '2026-11-15T21:00'})
                assert response.status_code == 200, (query, mode, response.text)
                checks.append({'destination': query, 'mode': mode, 'http': 200,
                               'transit_kind': response.json().get('transit', {}).get('kind'),
                               'transit_reason': response.json().get('transit', {}).get('reason')})
        for start, end, when in [('45.7470,21.2395', '45.7548,21.2254', '2026-11-15T21:00'),
                                 ('45.75937,21.22896', '45.76027,21.24061', '2026-11-15T12:03')]:
            response = client.get('/api/route', params={'from': start, 'to': end, 'mode': 'transit', 'at': when})
            transit_result = response.json().get('transit', {})
            assert response.status_code == 200 and transit_result.get('kind') == 'ok'
            checks.append({'from': start, 'to': end, 'at': when, 'mode': 'transit', 'http': 200,
                           'transit_kind': 'ok', 'line': transit_result['legs'][1]['line']})
    def red_lengths(path, poly):
        totals = {'all_dark_m': 0.0, 'core_dark_m': 0.0, 'direct_complaint_dark_m': 0.0}
        for feature in read(path)['features']:
            p = feature['properties']
            if p['status'] != 'dark_reported':
                continue
            length = metric(shape(feature['geometry']).intersection(poly)).length
            totals['all_dark_m'] += length
            if p['kind'] in bc.GROUPS['streets_and_sidewalks']:
                totals['core_dark_m'] += length
            if any(e.get('s') == 'sesizari' and e.get('k') in ['open_area_outage', 'open_lamp_out'] and e.get('age') is not None and e['age'] <= 30 for e in p.get('ev', [])):
                totals['direct_complaint_dark_m'] += length
        return {k: round(v) for k, v in totals.items()}
    old = shape(read(BASELINE_AREA)['features'][0]['geometry'])
    manifest = {'as_of': result['as_of'], 'area_km2': result['area_km2'],
                'area_sha256': hashlib.sha256(AREA.read_bytes()).hexdigest(),
                'quality_passes': True, 'routing_passes': True, 'api_checks': checks,
                'street_stats_clipped_to_polygon': result['all'], 'added_street_stats': result['added'],
                'grid_600m_cells_checked': len(result['grid_600m']),
                'max_grid_unknown_pct': max(r['unknown'] for r in result['grid_600m']),
                'max_grid_walking_unknown_pct': max(r['walking_with_paths']['unknown'] for r in result['grid_600m'] if r['walking_with_paths']['street_km'] >= 1),
                'red_comparison': {'current': red_lengths(BASELINE_OUT / 'segments.geojson.gz', old),
                                   'expanded': red_lengths(OUT / 'segments.geojson.gz', area)},
                'files': {name: {'bytes': (OUT / name).stat().st_size,
                                 'sha256': hashlib.sha256((OUT / name).read_bytes()).hexdigest()}
                          for name in ['segments.geojson.gz', 'summary.json', 'places.json.gz', 'transit.json.gz']}}
    save(OUT / 'preparation.json', manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k not in ['api_checks', 'files']}, ensure_ascii=True, indent=1), flush=True)
    print(f'API checks passed: {len(checks)}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('phase', choices=['boundary', 'refine', 'places', 'audit', 'verify'])
    args = parser.parse_args()
    {'boundary': boundary, 'refine': refine, 'places': places, 'audit': audit, 'verify': verify}[args.phase](args.data)
