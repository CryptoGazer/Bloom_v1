"""Search index for the address box: streets, house addresses, named places and transit stops inside the map area.

usage: .venv/bin/python -I backend/build_places.py [--data unihack-data] [--area config/area.geojson]
                                                   [--segments data/out/city/segments.geojson.gz] [--refresh]
Output: data/out/city/places.json.gz, read by backend/app.py (/api/geocode) through backend/geocode.py.
Sources: street names from the lighting build (OSM), addresses and places from Overpass (cached in
data/cache/places/, ODbL), stops from the City Hall transit API export (unihack-data/geojson/transit_stops.geojson).
"""
import argparse
import datetime as dt
import gzip
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import shapely
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script with -I: make "backend" importable
    sys.path.insert(0, str(ROOT))
from backend.build_city import KX, KY, OVERPASS_MIRRORS, log  # noqa: E402
from backend.geocode import normalize  # noqa: E402

USER_AGENT = "UniHack8-GreenMobility-NightRoute/0.1 (hackathon; Bloom_v1)"
# order = which category wins when one place is drawn twice
PLACE_KEYS = ("leisure", "amenity", "shop", "tourism", "historic", "office", "place", "building")
# named things nobody looks for as a destination; they only crowd the suggestions
SKIP_CATEGORIES = {f"amenity={v}" for v in ("parking", "parking_entrance", "parking_space", "taxi", "bench", "waste_basket",
                                              "waste_disposal", "recycling", "bicycle_parking", "motorcycle_parking",
                                              "vending_machine", "post_box", "telephone", "clock", "shelter", "charging_station")}
SKIP_CATEGORIES |= {"tourism=information", "building=yes", "building=garages", "building=garage"}


def overpass(area, cache, refresh):
    """Addresses and named places inside the area polygon; downloaded once, then read from the cache."""
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    ring = area.exterior.coords if area.geom_type == "Polygon" else max(area.geoms, key=lambda g: g.area).exterior.coords
    poly = " ".join(f"{lat:.6f} {lon:.6f}" for lon, lat in ring)
    selectors = ['["addr:housenumber"]'] + [f'["name"]["{k}"]' for k in PLACE_KEYS]
    query = "[out:json][timeout:120];(" + "".join(f'nwr{s}(poly:"{poly}");' for s in selectors) + ");out center tags;"
    for attempt, url in enumerate(OVERPASS_MIRRORS * 2, 1):
        log(f"places: attempt {attempt}, Overpass {url}")
        try:
            req = urllib.request.Request(url + "/interpreter", data=urllib.parse.urlencode({"data": query}).encode(),
                                         headers={"User-Agent": USER_AGENT})
            raw = urllib.request.urlopen(req, timeout=180).read()
            data = json.loads(raw)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
            return data
        except Exception as e:  # any mirror failure: try the next one
            log(f"places: Overpass failed: {str(e)[:160]}")
            time.sleep(10)
    sys.exit("All Overpass servers failed. Try again later, or copy data/cache/places/ from a teammate.")


def point_of(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else (None, None)


def street_entries(segments_path):
    """One entry per street name: the middle of the segment closest to the centre of all its segments."""
    with gzip.open(segments_path, "rt", encoding="utf-8") as f:
        feats = json.load(f)["features"]
    by_name = defaultdict(list)
    for feat in feats:
        name = feat["properties"].get("name")
        if name:
            coords = feat["geometry"]["coordinates"]
            line = shapely.LineString([(x * KX, y * KY) for x, y in coords])
            mid = line.interpolate(0.5, normalized=True)
            by_name[normalize(name)].append((name, mid.x, mid.y, feat["properties"].get("kind")))
    entries = []
    for parts in by_name.values():
        # the spelling used on most street segments, e.g. with diacritics
        spellings = defaultdict(int)
        for name, _, _, kind in parts:
            spellings[name] += 2 if kind == "street" else 1
        name = max(spellings, key=spellings.get)
        cx, cy = sum(p[1] for p in parts) / len(parts), sum(p[2] for p in parts) / len(parts)
        _, x, y, _ = min(parts, key=lambda p: (p[1] - cx) ** 2 + (p[2] - cy) ** 2)
        entries.append({"k": "street", "n": name, "lat": round(y / KY, 6), "lon": round(x / KX, 6)})
    return entries


def osm_entries(data, area):
    addresses, places, seen = [], [], set()
    for el in data["elements"]:
        tags = el.get("tags", {})
        lat, lon = point_of(el)
        if lat is None or not area.contains(Point(lon, lat)):
            continue
        number, street = tags.get("addr:housenumber"), tags.get("addr:street") or tags.get("addr:place")
        if number and street:
            for one in number.replace(",", ";").split(";"):  # "3;5" or "3,5" are two addresses at one point
                one = one.strip()
                key = ("addr", normalize(street), normalize(one))
                if one and key not in seen:
                    seen.add(key)
                    addresses.append({"k": "addr", "n": f"{street} {one}", "s": street, "h": one, "lat": round(lat, 6), "lon": round(lon, 6)})
        name = tags.get("name")
        category = next((f"{k}={tags[k]}" for k in PLACE_KEYS if k in tags and f"{k}={tags[k]}" not in SKIP_CATEGORIES), None)
        if name and category:
            # the same place drawn as a node and as a building counts once (same name and category within 60 m)
            key = ("place", normalize(name), category, round(lat * 600), round(lon * 420))
            if key not in seen:
                seen.add(key)
                entry = {"k": "place", "n": name, "c": category, "lat": round(lat, 6), "lon": round(lon, 6)}
                if tags.get("opening_hours"):
                    entry["oh"] = tags["opening_hours"]  # for "open now" along a route (backend/liveliness.py)
                places.append(entry)
    return addresses, places


def dedupe_places(places, streets):
    """One place per name nearby: a faculty drawn as a node and as a building, a square that is also a street."""
    def dist_m(a, b):
        return math.hypot((a["lon"] - b["lon"]) * KX, (a["lat"] - b["lat"]) * KY)
    street_at = {normalize(s["n"]): s for s in streets}
    rank = {k: i for i, k in enumerate(PLACE_KEYS)}
    kept, by_name = [], defaultdict(list)
    for p in sorted(places, key=lambda p: rank.get(p["c"].split("=")[0], len(rank))):
        key = normalize(p["n"])
        street = street_at.get(key)
        if street and dist_m(street, p) < 300:
            continue
        if any(dist_m(other, p) < 200 for other in by_name[key]):
            continue
        by_name[key].append(p)
        kept.append(p)
    return kept


def stop_entries(stops_path, routes_path, area):
    if not stops_path.exists():
        log(f"stops: {stops_path} not found, skipped")
        return []
    line_of = {}  # route id (R_AB_E2) -> line number shown to people (E2)
    if routes_path.exists():
        for feat in json.loads(routes_path.read_text(encoding="utf-8"))["features"]:
            line_of[feat["properties"]["route_id"]] = feat["properties"].get("short_name") or feat["properties"]["route_id"]
    by_name = defaultdict(list)
    for feat in json.loads(stops_path.read_text(encoding="utf-8"))["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        if area.contains(Point(lon, lat)):
            by_name[feat["properties"]["name"]].append((lat, lon, feat["properties"].get("route_ids") or ""))
    entries = []
    for name, platforms in by_name.items():
        # platforms on both sides of a street share a name: one entry, the lines of all of them
        lat = sum(p[0] for p in platforms) / len(platforms)
        lon = sum(p[1] for p in platforms) / len(platforms)
        lines = sorted({line_of.get(r, r) for p in platforms for r in p[2].split(",") if r}, key=lambda r: (len(r), r))
        entries.append({"k": "stop", "n": name, "c": ", ".join(lines), "lat": round(lat, 6), "lon": round(lon, 6)})
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "unihack-data"))
    ap.add_argument("--area", default="config/area.geojson")
    ap.add_argument("--segments", default="data/out/city/segments.geojson.gz")
    ap.add_argument("--out", default="data/out/city/places.json.gz")
    ap.add_argument("--refresh", action="store_true", help="download addresses and places from Overpass again")
    args = ap.parse_args()

    area = shape(json.loads((ROOT / args.area).read_text(encoding="utf-8"))["features"][0]["geometry"])
    data = overpass(area, ROOT / "data/cache/places/overpass.json", args.refresh)
    streets = street_entries(ROOT / args.segments)
    addresses, places = osm_entries(data, area)
    places = dedupe_places(places, streets)
    stops = stop_entries(Path(args.data) / "geojson/transit_stops.geojson", Path(args.data) / "geojson/transit_routes.geojson", area)
    entries = streets + addresses + places + stops
    meta = {"built_at": dt.datetime.now().isoformat(timespec="seconds"), "area": args.area,
            "osm_base": data.get("osm3s", {}).get("timestamp_osm_base"),
            "counts": {"street": len(streets), "addr": len(addresses), "place": len(places), "stop": len(stops)},
            "licence": "OpenStreetMap ODbL; stops: Primăria Timișoara transit API"}
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"meta": meta, "entries": entries}, f, ensure_ascii=False, separators=(",", ":"))
    log(f"written {out} ({out.stat().st_size / 1000:.0f} KB): {meta['counts']}, OSM {meta['osm_base']}")


if __name__ == "__main__":
    main()
