"""Build extra map layers from Timur's unihack-data folder into data/out/layers/.

usage: .venv/bin/python -I demo/layers/build_layers.py [unihack-data dir] [out dir]
Layers (all city-wide, GeoJSON [lon, lat]):
  bike_lanes.geojson      bike infrastructure from OSM with lighting evidence (OSM lit tag, Mapillary lamps)
  transit_stops.geojson   GTFS stops with lines and the last departures on the night of each date in DATES
  transit_routes.geojson  route shapes from the city API (copied)
  zones.geojson           40 districts with the share of streets that have any lighting evidence
  meta.json               build time, sources, km summary of bike lanes
"""
import csv
import datetime as dt
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
DATES = ["2026-11-14", "2026-11-15", "2026-11-16"]  # hackathon Saturday, Sunday, and the Monday after
NIGHT_FROM = 22 * 3600
LAMP_R, COVER_MIN, STEP = 20.0, 0.5, 10.0
KX, KY = 77811.0, 111147.0  # metres per degree at lat 45.748, same as draft_map.py
YES = {"yes", "24/7", "automatic", "limited", "interval", "sunset-sunrise", "dusk-dawn"}
MODES = {"0": "tramvai", "3": "autobuz", "11": "troleibuz"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def bike_category(t):
    if t.get("highway") == "cycleway":
        return "cycleway"
    if any(k.startswith("cycleway") and str(v) in ("lane", "track", "shared_lane") for k, v in t.items()):
        return "lane"
    if t.get("bicycle") == "designated":
        return "designated"
    return None


def bike_lanes(data):
    lamps = load(data / "geojson/mapillary_street_lights.geojson")["features"]
    tree = STRtree(shapely.points(np.array([[f["geometry"]["coordinates"][0] * KX, f["geometry"]["coordinates"][1] * KY] for f in lamps])))
    feats, summary = [], defaultdict(lambda: defaultdict(float))
    for f in load(data / "geojson/osm_highways.geojson")["features"]:
        t = f["properties"]
        cat = bike_category(t)
        if not cat or f["geometry"]["type"] != "LineString":
            continue
        coords = f["geometry"]["coordinates"]
        line = LineString([(x * KX, y * KY) for x, y in coords])
        length = line.length
        if length <= 0:
            continue
        n = max(1, round(length / STEP))
        pts = shapely.line_interpolate_point(line, (np.arange(n) + 0.5) * length / n)
        cov = len(set(tree.query_nearest(pts, max_distance=LAMP_R, all_matches=False)[0])) / n
        lit = str(t.get("lit") or "")
        if lit == "no":
            status = "dark_reported"
        elif lit in YES or cov >= COVER_MIN:
            status = "lit_confirmed"
        elif cov > 0:
            status = "lit_likely"
        else:
            status = "unknown"
        summary[cat][status] += length
        summary[cat]["total"] += length
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[round(x, 6), round(y, 6)] for x, y in coords]},
                      "properties": {"osm_id": t.get("osm_id"), "name": t.get("name"), "cat": cat, "lit": lit or None,
                                     "lamp_cov": round(cov, 2), "status": status, "len": round(length, 1)}})
    km = {c: {k: round(v / 1000, 2) for k, v in s.items()} for c, s in summary.items()}
    return {"type": "FeatureCollection", "features": feats}, km


def read_gtfs(zpath):
    z = zipfile.ZipFile(zpath)
    def table(name):
        return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))
    return table, z


def service_ids(table, date):
    key = date.replace("-", "")
    wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][dt.date.fromisoformat(date).weekday()]
    active = {c["service_id"] for c in table("calendar.txt") if c["start_date"] <= key <= c["end_date"] and c[wd] == "1"}
    for e in table("calendar_dates.txt"):
        if e["date"] == key:
            (active.add if e["exception_type"] == "1" else active.discard)(e["service_id"])
    return active


def feed_window(zpath):
    table, _ = read_gtfs(zpath)
    info = table("feed_info.txt")[0]
    return info["feed_start_date"], info["feed_end_date"], info.get("feed_version", "")


def hhmm(sec):
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


def transit_stops(data):
    zips = sorted((data / "gtfs").glob("*.zip"))
    windows = {z: feed_window(z) for z in zips}
    stops, night, used = {}, defaultdict(dict), {}
    for date in DATES:
        key = date.replace("-", "")
        cands = [z for z, (s, e, _) in windows.items() if s <= key <= e]
        if not cands:
            continue
        zpath = max(cands, key=lambda z: windows[z][0])  # newest feed that covers the date
        used[date] = f"{zpath.name} (v{windows[zpath][2]})"
        table, _ = read_gtfs(zpath)
        routes = {r["route_id"]: r for r in table("routes.txt")}
        if not stops:
            for s in table("stops.txt"):
                stops[s["stop_id"]] = s
        active = service_ids(table, date)
        trips = {t["trip_id"]: t["route_id"] for t in table("trips.txt") if t["service_id"] in active}
        rows = [r for r in table("stop_times.txt") if r["trip_id"] in trips]
        last_seq = defaultdict(int)
        for r in rows:
            last_seq[r["trip_id"]] = max(last_seq[r["trip_id"]], int(r["stop_sequence"]))
        per_stop = defaultdict(lambda: {"n22": 0, "last": {}, "lines": set()})
        for r in rows:
            if int(r["stop_sequence"]) == last_seq[r["trip_id"]]:
                continue  # terminus: nobody boards there
            h, m, s = map(int, r["departure_time"].split(":"))
            sec = h * 3600 + m * 60 + s
            line = routes[trips[r["trip_id"]]]["route_short_name"]
            ps = per_stop[r["stop_id"]]
            ps["lines"].add(line)
            ps["last"][line] = max(ps["last"].get(line, 0), sec)
            if sec >= NIGHT_FROM:
                ps["n22"] += 1
        for sid, ps in per_stop.items():
            last = sorted(ps["last"].items(), key=lambda kv: -kv[1])
            night[sid][date] = {"n22": ps["n22"], "last": [[ln, hhmm(sec)] for ln, sec in last]}
    feats = []
    for sid, s in stops.items():
        lines = sorted({ln for d in night.get(sid, {}).values() for ln, _ in d["last"]}, key=lambda x: (len(x), x))
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(s["stop_lon"]), float(s["stop_lat"])]},
                      "properties": {"stop_id": sid, "name": s["stop_name"], "lines": lines, "night": night.get(sid, {})}})
    return {"type": "FeatureCollection", "features": feats}, used


def zones(data):
    cov = {}
    with (data / "coverage_by_zone.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cov[r["zone"]] = r
    feats, missing = [], []
    for f in load(data / "geojson/city_zones.geojson")["features"]:
        name = f["properties"]["name"]
        c = cov.get(name)
        if c is None:
            missing.append(name)
        props = {"name": name}
        if c:
            props.update(street_km=float(c["street_km"]), pct_any=float(c["pct_any_evidence"]), pct_mapillary=float(c["pct_mapillary_light_25m"]),
                         pct_osm_lit=float(c["pct_osm_lit_yes"]), pct_open_complaint=float(c["pct_open_complaint_50m"]))
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
    return {"type": "FeatureCollection", "features": feats}, missing


def main():
    data = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "unihack-data"
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT / "data/out/layers"
    if not (data / "geojson").is_dir():
        sys.exit(f"No geojson/ folder in {data}")
    out.mkdir(parents=True, exist_ok=True)

    bike, bike_km = bike_lanes(data)
    write(out / "bike_lanes.geojson", bike)
    stops, gtfs_used = transit_stops(data)
    write(out / "transit_stops.geojson", stops)
    routes = load(data / "geojson/transit_routes.geojson")
    write(out / "transit_routes.geojson", routes)
    zn, missing = zones(data)
    write(out / "zones.geojson", zn)
    meta = {"built_at": dt.datetime.now().isoformat(timespec="seconds"), "data_dir": data.name, "gtfs_by_date": gtfs_used,
            "bike_km": bike_km, "lamp_radius_m": LAMP_R, "lamp_coverage_min": COVER_MIN, "zones_without_coverage": missing}
    write(out / "meta.json", meta)
    print(f"written {out}: bike lanes {len(bike['features'])}, stops {len(stops['features'])}, routes {len(routes['features'])}, zones {len(zn['features'])}")
    print("GTFS by date:", gtfs_used)
    for cat, s in sorted(bike_km.items()):
        tot = s["total"]
        print(f"  bike {cat}: {tot:.1f} km | " + " | ".join(f"{k} {100 * s.get(k, 0) / tot:.0f}%" for k in ("lit_confirmed", "lit_likely", "unknown", "dark_reported")))
    if missing:
        print("zones without coverage row:", missing)


if __name__ == "__main__":
    main()
