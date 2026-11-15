"""Build/check a conservative northwest extension of the approved northeast map.

Phases: boundary, streets, places, audit, refine, verify. Source inputs are local
unihack-data; street topology and search entries are downloaded by the builders.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

import shapely
from shapely.geometry import Polygon, box, shape, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_expansion as prep

prep.AREA = ROOT / 'config/area-northwest.geojson'
prep.OUT = ROOT / 'data/out/city-northwest'
prep.QA = ROOT / 'data/cache/northwest'
prep.BASELINE_AREA = ROOT / 'config/area-expanded.geojson'
prep.BASELINE_OUT = ROOT / 'data/out/city-expanded'
prep.EXTRA_QUERIES = ['Piata Dacia', 'Mircea cel Batran']
DAY = '2026-11-15'


def write_area(geometry, properties):
    prep.save(prep.AREA, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': properties, 'geometry': mapping(geometry)}]})


def boundary(data):
    inputs = prep.sources(data)
    zones = {f['properties']['slug']: shape(f['geometry'])
             for f in prep.read(data / 'geojson/city_zones.geojson')['features']}
    old = shape(prep.read(prep.BASELINE_AREA)['features'][0]['geometry'])
    selected = unary_union([prep.metric(old)] + [prep.metric(zones[s])
                           for s in ['circumvalatiunii-dacia', 'mircea-cel-batran']])
    rounded = selected.buffer(80).buffer(-80)
    assert rounded.geom_type == 'Polygon', 'Disconnected candidate'
    merged = unary_union([selected.buffer(.2), Polygon(rounded.exterior).buffer(.2)])
    assert merged.geom_type == 'Polygon'
    merged = Polygon(merged.exterior)
    geo = unary_union([prep.lonlat(merged.simplify(3).buffer(3)), old])
    geo = Polygon(geo.exterior)
    assert geo.is_valid and geo.covers(old) and not geo.interiors
    properties = {
        'name': 'Campus, centre, northeast and selected northwest neighbourhoods',
        'description': 'Approved northeast coverage plus Circumvalatiunii/Dacia and '
                       'Mircea cel Batran; administrative seams closed at 80 m. '
                       'Mehala, Bucovina and the distant Aradului fringe are not selected.',
        'area_km2': round(prep.metric(geo).area / 1e6, 3),
        'baseline': 'config/area-expanded.geojson',
        'selected_zones': ['circumvalatiunii-dacia', 'mircea-cel-batran'],
    }
    write_area(geo, properties)
    prep.save(prep.QA / 'inputs.json', {'inputs': inputs,
              'area_km2': properties['area_km2'],
              'area_sha256': hashlib.sha256(prep.AREA.read_bytes()).hexdigest()})
    print(json.dumps(properties), flush=True)


def streets(data):
    sys.argv = ['build_city.py', '--data', str(data), '--area', prep.AREA.relative_to(ROOT).as_posix(),
                '--out', str(prep.OUT), '--as-of', DAY]
    prep.bc.main()


def refine(data):
    result = prep.read(prep.QA / 'audit.json')
    prior = prep.read(prep.AREA)
    area = prep.metric(shape(prior['features'][0]['geometry']))
    old = prep.metric(shape(prep.read(prep.BASELINE_AREA)['features'][0]['geometry']))
    failed = [box(c['x'], c['y'], c['x'] + 600, c['y'] + 600)
              for c in result['grid_600m'] if not c['passes']]
    assert failed, 'No failed fringe cells; inspect district results instead'
    clipped = area.difference(unary_union(failed).difference(old))
    if clipped.geom_type == 'MultiPolygon':
        clipped = next(p for p in clipped.geoms if p.buffer(.01).covers(old))
    assert clipped.geom_type == 'Polygon' and not clipped.interiors, 'Trimming creates holes'
    final = unary_union([clipped.buffer(-20).buffer(20), old])
    assert final.geom_type == 'Polygon' and not final.interiors
    if not (prep.QA / 'broad-area.geojson').exists():
        prep.save(prep.QA / 'broad-area.geojson', prior)
        prep.save(prep.QA / 'broad-audit.json', result)
    cache = ROOT / 'data/cache/city/network-area-northwest.json.gz'
    broad_cache = prep.QA / 'network-broad.json.gz'
    if not broad_cache.exists():
        shutil.copyfile(cache, broad_cache)
    broad = prep.read(broad_cache)
    border = final.buffer(20)
    broad['segments'] = [s for s in broad['segments']
                         if prep.metric(shapely.LineString(s['ll'])).intersects(border)]
    geo = unary_union([prep.lonlat(final.simplify(1)), prep.lonlat(old)])
    geo = Polygon(geo.exterior)
    properties = {**prior['features'][0]['properties'],
                  'area_km2': round(prep.metric(geo).area / 1e6, 3),
                  'removed_fringe_cells': prior['features'][0]['properties'].get('removed_fringe_cells', 0) + len(failed)}
    write_area(geo, properties)
    with gzip.open(cache, 'wt', encoding='utf-8') as stream:
        json.dump(broad, stream, ensure_ascii=False, separators=(',', ':'))
    streets(data)


def verify(data):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.history import History
    prep.verify(data)
    checks = []
    with TestClient(create_app(segments_path=prep.OUT / 'segments.geojson.gz',
                              live_fetch=lambda: {'vehicles': []}, history=History(lambda *_: {}))) as client:
        points = []
        for query in prep.EXTRA_QUERIES:
            dest = client.get('/api/geocode', params={'q': query}).json()['results'][0]
            point = str(dest['lat']) + ',' + str(dest['lon'])
            points.append(point)
            response = client.get('/api/loop', params={'center': point, 'radius_m': 300, 'mode': 'walk'})
            result = response.json()
            assert response.status_code == 200 and result['loop'] and result['generated'], (query, result)
            checks.append({'url': '/api/loop', 'center_query': query, 'generated': True, 'http': 200})
        response = client.get('/api/loop', params={'points': ';'.join(points), 'mode': 'walk'})
        assert response.status_code == 200 and response.json()['loop']
        checks.append({'url': '/api/loop', 'through': prep.EXTRA_QUERIES, 'http': 200})
    manifest = prep.read(prep.OUT / 'preparation.json')
    manifest['api_checks'].extend(checks)
    prep.save(prep.OUT / 'preparation.json', manifest)
    print('Northwest API checks total:', len(manifest['api_checks']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('phase', choices=['boundary', 'streets', 'places', 'audit', 'refine', 'verify'])
    args = parser.parse_args()
    {'boundary': boundary, 'streets': streets, 'places': prep.places,
     'audit': prep.audit, 'refine': refine, 'verify': verify}[args.phase](args.data)
