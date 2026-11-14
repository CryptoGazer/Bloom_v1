"""Lighting status for every segment of the walking and cycling network of an area.

Same rules as the spec (sections 5-7); the status rule itself is in backend/rules.py.

usage: .venv/bin/python -I backend/build_city.py [--data unihack-data] [--out data/out/city] [--area FILE.geojson]
                                                 [--bbox south,west,north,east] [--as-of YYYY-MM-DD] [--refresh-network]
Default area: config/area.geojson (the university district south of the Bega and the centre, Cetate).
The whole city: --area config/city_boundary.geojson --out data/out/city-full
Outputs: <out>/segments.geojson.gz  one LineString per segment with status and evidence
         <out>/summary.json         shares by status, checks, per-district table, sources
The street network is downloaded once with osmnx and kept in data/cache/city/; later runs work offline.
"""
import argparse
import datetime as dt
import gzip
import json
import math
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, box, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script with -I: make "backend" importable
    sys.path.insert(0, str(ROOT))
from backend import rules  # noqa: E402

KX, KY = 77811.0, 111147.0  # metres per degree of lon / lat at 45.748 N; error under 0.1% across the city
PAD_DEG = 0.001
PARAMS = {
    "lamp_radius_m": 20.0, "lamp_coverage_min": 0.5, "sample_step_m": 10.0,
    "complaint_radius_m": 30.0, "complaint_cluster_m": 30.0, "complaint_cluster_days": 14,
    "open_complaint_fresh_days": 30, "lamps_out_for_dark": 3, "inherit_radius_m": 15.0,
    "max_unknown_share": 33.33, "min_lamp_recall": 0.5,
}
STATUSES = ["lit_confirmed", "lit_likely", "dark_reported", "unknown"]
GROUPS = {"streets": {"street"}, "sidewalks": {"sidewalk", "crossing"}, "streets_and_sidewalks": {"street", "sidewalk", "crossing"},
          "paths": {"path"}, "service": {"service"}}
STREET = {"trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}
STREET |= {s + "_link" for s in ("trunk", "primary", "secondary", "tertiary")}
LIT_YES = {"yes", "24/7", "automatic", "limited", "interval", "sunset-sunrise", "dusk-dawn"}
CLOSED = {"Finalizata", "Rezolvata"}
EXTRA_WAY_TAGS = ["lit", "footway", "foot", "bicycle", "cycleway", "surface", "oneway:bicycle", "cycleway:left", "cycleway:right", "cycleway:both"]
# tags the router needs; "oneway" is osmnx's own flag (True/False): a one-way segment is stored in its driving direction
KEEP_TAGS = ("foot", "bicycle", "cycleway", "surface", "access", "oneway", "oneway:bicycle", "cycleway:left", "cycleway:right", "cycleway:both")
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]


def log(msg):
    print(f"[build_city {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).casefold().replace(".", " ").split())


def aslist(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def kind_of(d):
    hw, fw = set(aslist(d.get("highway"))), set(aslist(d.get("footway")))
    if hw & STREET:
        return "street"
    if "footway" in hw and "sidewalk" in fw:
        return "sidewalk"
    if "footway" in hw and "crossing" in fw:
        return "crossing"
    if hw & {"footway", "path", "pedestrian", "cycleway", "steps", "track"}:
        return "path"
    return "service"


def osm_lit(d):
    vals = set(aslist(d.get("lit")))
    yes, no = vals & LIT_YES, vals & {"no"}
    return "mixed" if (yes and no) else ("yes" if yes else ("no" if no else None))


# ---------- network ----------
def download_graph(area):
    """Undirected osmnx graph of the area; tries Overpass mirrors because the main server is often busy."""
    import osmnx as ox
    import requests
    from osmnx._errors import ResponseStatusCodeError

    cache = ROOT / "data/cache/osmnx"
    cache.mkdir(parents=True, exist_ok=True)
    ox.settings.cache_folder = str(cache)
    ox.settings.use_cache = True
    ox.settings.requests_timeout = 300
    ox.settings.useful_tags_way = list(dict.fromkeys(list(ox.settings.useful_tags_way) + EXTRA_WAY_TAGS))
    for attempt, url in enumerate(OVERPASS_MIRRORS * 2, 1):
        ox.settings.overpass_url = url
        ox.settings.overpass_rate_limit = url == OVERPASS_MIRRORS[0]
        log(f"network: attempt {attempt}, Overpass {url}")
        try:
            G = ox.graph_from_polygon(area, network_type="all_public", simplify=True, retain_all=True, truncate_by_edge=True)
            return ox.convert.to_undirected(G), ox.__version__
        except (ResponseStatusCodeError, requests.exceptions.RequestException) as e:
            log(f"network: Overpass failed: {str(e).splitlines()[0][:160]}")
            time.sleep(20)
    sys.exit("All Overpass servers failed. Try again later, or copy data/cache/city/ from a teammate.")


def segments_from_graph(Gu):
    segs = []
    for u, v, k, d in Gu.edges(keys=True, data=True):
        ux, uy, vx, vy = Gu.nodes[u]["x"], Gu.nodes[u]["y"], Gu.nodes[v]["x"], Gu.nodes[v]["y"]
        g = d.get("geometry")
        coords = list(g.coords) if g is not None else [(ux, uy), (vx, vy)]
        x0, y0 = coords[0]
        # u/v are stored in the direction of the geometry, so the router knows which end is which
        a, b = (v, u) if u != v and (x0 - ux) ** 2 + (y0 - uy) ** 2 > (x0 - vx) ** 2 + (y0 - vy) ** 2 else (u, v)
        lo, hi = (u, v) if u < v else (v, u)
        name = d.get("name")
        name = name[0] if isinstance(name, list) else name
        seg = {"id": f"{lo}-{hi}-{k}", "u": int(a), "v": int(b), "ll": [[round(x, 6), round(y, 6)] for x, y in coords],
               "kind": kind_of(d), "hw": ";".join(sorted({str(x) for x in aslist(d.get("highway"))})),
               "name": name if isinstance(name, str) else None, "ways": [int(x) for x in aslist(d.get("osmid"))], "lit": osm_lit(d)}
        for tag in KEEP_TAGS:
            vals = aslist(d.get(tag))
            if vals:
                seg[tag] = ";".join(sorted({str(x) for x in vals}))
        segs.append(seg)
    return segs


def load_network(area, key, refresh):
    path = ROOT / "data/cache/city" / f"network-{key}.json.gz"
    if path.exists() and not refresh:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            net = json.load(f)
        log(f"network: {len(net['segments'])} segments from cache {path.name} (fetched {net['fetched_at']})")
        return net
    Gu, version = download_graph(area)
    net = {"fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "osmnx": version,
           "area": key, "segments": segments_from_graph(Gu)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(net, f, ensure_ascii=False, separators=(",", ":"))
    log(f"network: {len(net['segments'])} segments downloaded, cached in {path.name}")
    return net


# ---------- evidence ----------
def load_points(path, bounds):
    if not path.exists():
        return None
    w, s, e, n = bounds
    feats = json.loads(path.read_text(encoding="utf-8"))["features"]
    return [f for f in feats if f.get("geometry") and w - PAD_DEG <= f["geometry"]["coordinates"][0] <= e + PAD_DEG
            and s - PAD_DEG <= f["geometry"]["coordinates"][1] <= n + PAD_DEG]


def build_events(complaints, as_of):
    """Glue complaints into events (30 m / 14 days from the first report) and give each event a kind."""
    lamp_subs = {fold("Bec nefuncțional"), fold("Aparat de iluminat nefuncțional")}
    comps = []
    for f in complaints:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        comps.append({"xy": (lon * KX, lat * KY), "ll": [round(lon, 6), round(lat, 6)], "nr": p["nr"],
                      "sub": (p.get("subcategory") or "").strip(), "st": (p.get("status") or "").strip(),
                      "created": dt.datetime.fromisoformat(p["created_at"]).date(), "closed": (p.get("closed_at") or "")[:10] or None})
    comps.sort(key=lambda c: c["created"])
    events = []
    for c in comps:
        for ev in events:
            first = ev["m"][0]
            if (c["created"] - first["created"]).days <= PARAMS["complaint_cluster_days"] and math.dist(c["xy"], first["xy"]) <= PARAMS["complaint_cluster_m"]:
                ev["m"].append(c)
                break
        else:
            events.append({"m": [c]})
    for ev in events:
        members = ev["m"]
        counted = [c for c in members if not c["st"].startswith("Declinat")]
        opened = [c for c in counted if c["st"] not in CLOSED]
        ev["age"] = None
        if not counted:
            ev["kind"] = "declined"
        elif opened:
            subs = {fold(c["sub"]) for c in opened}
            ev["kind"] = ("open_area_outage" if any(x.startswith("nu functioneaza iluminatul") for x in subs)
                          else ("open_lamp_out" if subs & lamp_subs else "open_other"))
            ev["age"] = (as_of - max(c["created"] for c in opened)).days
        else:
            ev["kind"] = "fixed"
        closed = [c["closed"] for c in members if c["closed"]]
        ev["closed"] = max(closed) if closed and ev["kind"] == "fixed" else None
    return comps, events


def classify(segs, lamps, complaints, as_of):
    """Adds status, families, evidence to every segment. Returns counters for the summary."""
    P = PARAMS
    lines = np.array([LineString([(x * KX, y * KY) for x, y in s["ll"]]) for s in segs], dtype=object)
    length = shapely.length(lines)
    for s, L in zip(segs, length):
        s["L"], s["ind"] = float(L), []

    # lamps: share of each segment within lamp_radius of a lamp, and the lamps near it
    cov = np.zeros(len(segs))
    near = defaultdict(list)
    lamp_yr = []
    if lamps:
        lamp_pts = shapely.points(np.array([[f["geometry"]["coordinates"][0] * KX, f["geometry"]["coordinates"][1] * KY] for f in lamps]))
        lamp_yr = [int((f["properties"].get("last_seen") or "0000")[:4]) for f in lamps]
        tree = STRtree(lamp_pts)
        n = np.maximum(1, np.round(length / P["sample_step_m"])).astype(int)
        owner = np.repeat(np.arange(len(segs)), n)
        offsets = np.concatenate([(np.arange(k) + 0.5) * (L / k) for k, L in zip(n, length)])
        samples = shapely.line_interpolate_point(lines[owner], offsets)
        hit = np.zeros(len(samples))
        hit[tree.query_nearest(samples, max_distance=P["lamp_radius_m"], all_matches=False)[0]] = 1
        cov = np.bincount(owner, weights=hit, minlength=len(segs)) / n
        si, li = tree.query(lines, predicate="dwithin", distance=P["lamp_radius_m"])
        for s_, l_, d_ in zip(si, li, shapely.distance(lines[si], lamp_pts[li])):
            near[int(s_)].append((int(l_), float(d_)))

    # complaints -> events -> nearest street within complaint_radius, else nearest segment of any kind
    comps, events = build_events(complaints or [], as_of)
    st_idx = np.array([i for i, s in enumerate(segs) if s["kind"] == "street"], dtype=int)
    t_street = STRtree(lines[st_idx]) if len(st_idx) else None
    t_all = STRtree(lines)
    seg_events, attached = defaultdict(list), {}
    if events:
        ev_pts = shapely.points(np.array([ev["m"][0]["xy"] for ev in events]))
        if t_street is not None:
            (ei, si), dist = t_street.query_nearest(ev_pts, max_distance=P["complaint_radius_m"], return_distance=True, all_matches=False)
            for e, s_, d_ in zip(ei, si, dist):
                attached[int(e)] = (int(st_idx[s_]), float(d_))
        rest = [e for e in range(len(events)) if e not in attached]
        if rest:
            (ei, si), dist = t_all.query_nearest(ev_pts[rest], max_distance=P["complaint_radius_m"], return_distance=True, all_matches=False)
            for e, s_, d_ in zip(ei, si, dist):
                attached[rest[int(e)]] = (int(s_), float(d_))
        for e, (s_, d_) in attached.items():
            seg_events[s_].append((events[e], d_))

    # facts and indirect signs
    fresh = P["open_complaint_fresh_days"]
    for i, s in enumerate(segs):
        s["facts"] = [(ev["kind"], ev["age"]) for ev, _ in seg_events.get(i, [])]
        s["fam"] = rules.families(s["lit"], cov[i], [kind for kind, _ in s["facts"]], P["lamp_coverage_min"])
        s["dark_compl"] = rules.dark_by_complaints(s["facts"], fresh, P["lamps_out_for_dark"])
        if 0 < cov[i] < P["lamp_coverage_min"]:
            s["ind"].append("partial_lamps")
    names_yes = {fold(s["name"]) for s in segs if s["kind"] == "street" and s["lit"] == "yes" and s["name"]}
    for s in segs:
        if s["kind"] == "street" and s["lit"] is None and s["name"] and fold(s["name"]) in names_yes:
            s["ind"].append("same_name")
    others = np.array([i for i, s in enumerate(segs) if s["kind"] != "street"], dtype=int)
    if t_street is not None and len(others):
        mids = shapely.line_interpolate_point(lines[others], 0.5, normalized=True)
        for a_, b_ in zip(*t_street.query_nearest(mids, max_distance=P["inherit_radius_m"], all_matches=False)):
            me, street = segs[others[a_]], segs[st_idx[b_]]
            me["near"] = street["id"]
            if street["fam"] or "same_name" in street["ind"]:
                me["ind"].append("near_lit_street")
            if street["dark_compl"]:
                me["inh_dark"] = True

    # status (backend/rules.py) and evidence for the "why" card
    for i, s in enumerate(segs):
        s["status"] = rules.status(s["lit"], s["fam"], s["facts"], s["ind"], bool(s.get("inh_dark")), fresh, P["lamps_out_for_dark"])
        ev = []
        if s["lit"]:
            ev.append({"s": "osm", "k": s["lit"], "ways": s["ways"][:4]})
        if near.get(i):
            years = [lamp_yr[j] for j, _ in near[i]]
            ev.append({"s": "mapillary", "n": len(near[i]), "near": round(min(d for _, d in near[i]), 1), "y0": min(years), "y1": max(years), "cov": round(float(cov[i]), 2)})
        for e, d_ in seg_events.get(i, []):
            first = e["m"][0]
            ev.append({"s": "sesizari", "k": e["kind"], "nr": first["nr"], "n": len(e["m"]), "sub": first["sub"], "created": str(first["created"]),
                       "closed": e["closed"], "age": e["age"], "d": round(d_)})
        for flag in s["ind"]:
            ev.append({"s": "derived", "k": flag, "ref": s["name"] if flag == "same_name" else s.get("near")})
        if s.get("inh_dark"):
            ev.append({"s": "derived", "k": "inherited_dark", "ref": s.get("near")})
        s["ev"] = ev

    counters = {"complaints_in_area": len(comps), "events": len(events), "events_unattached": len(events) - len(attached),
                "event_kinds": {k: sum(1 for ev in events if ev["kind"] == k) for k in ("fixed", "open_area_outage", "open_lamp_out", "open_other", "declined")},
                "dark_segments": {"lit_no": sum(1 for s in segs if s["lit"] == "no"), "by_complaints": sum(1 for s in segs if s["dark_compl"]),
                                  "inherited": sum(1 for s in segs if s.get("inh_dark"))}}
    return lines, counters


# ---------- summary ----------
def shares(sel):
    total = sum(s["L"] for s in sel)
    out = {"km": round(total / 1000, 1), "n": len(sel)}
    for st in STATUSES:
        out[st] = round(100 * sum(s["L"] for s in sel if s["status"] == st) / total, 1) if total else 0.0
    return out


def zone_table(segs, lines, zones_path, area):
    """Shares per city district. "inside" is the share of the district's surface inside the built area:
    for a district only partly inside, the shares describe that part only."""
    if not zones_path.exists():
        return []
    zones = json.loads(zones_path.read_text(encoding="utf-8"))["features"]
    polys = np.array([shapely.transform(shape(z["geometry"]), lambda a: a * [KX, KY]) for z in zones], dtype=object)
    core = np.array([i for i, s in enumerate(segs) if s["kind"] in GROUPS["streets_and_sidewalks"]], dtype=int)
    mids = shapely.line_interpolate_point(lines[core], 0.5, normalized=True)
    pi, zi = STRtree(polys).query(mids, predicate="within")
    by_zone, seen = defaultdict(list), set()
    for p_, z_ in zip(pi, zi):
        if p_ not in seen:  # a point on a shared border counts once
            seen.add(p_)
            by_zone[int(z_)].append(segs[core[p_]])
    table = []
    for z_, zone in enumerate(zones):
        row = shares(by_zone.get(z_, []))
        row["name"] = zone["properties"]["name"]
        row["known"] = round(100 - row["unknown"], 1) if row["n"] else None
        polygon = shape(zone["geometry"])
        row["inside"] = round(polygon.intersection(area).area / polygon.area, 3) if polygon.area else 0.0
        table.append(row)
    return sorted(table, key=lambda r: r["name"])


def date_range(values):
    values = sorted(v for v in values if v)
    return [values[0], values[-1]] if values else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "unihack-data"))
    ap.add_argument("--out", help="default data/out/city (required with --bbox or another --area)")
    ap.add_argument("--area", default="config/area.geojson", help="polygon of the area (GeoJSON, first feature); default config/area.geojson")
    ap.add_argument("--bbox", help="south,west,north,east instead of an area polygon")
    ap.add_argument("--as-of", default=dt.date.today().isoformat(), help="date used for the age of open complaints")
    ap.add_argument("--refresh-network", action="store_true", help="download the street network again")
    args = ap.parse_args()
    data, as_of = Path(args.data), dt.date.fromisoformat(args.as_of)

    if args.bbox:
        if not args.out:
            sys.exit("--bbox needs --out, so that the city files are not overwritten")
        s, w, n, e = (float(x) for x in args.bbox.split(","))
        area, key, area_meta = box(w, s, e, n), f"bbox-{s}_{w}_{n}_{e}", {"type": "bbox", "south": s, "west": w, "north": n, "east": e}
    else:
        default_area = ap.get_default("area")
        if args.area != default_area and not args.out:
            sys.exit("--area other than the default needs --out, so that data/out/city is not overwritten")
        boundary = ROOT / args.area
        feature = json.loads(boundary.read_text(encoding="utf-8"))["features"][0]
        area, key, area_meta = shape(feature["geometry"]), boundary.stem, {"type": "polygon", "file": args.area, **feature["properties"]}
    out = Path(args.out) if args.out else ROOT / "data/out/city"
    bounds = area.bounds  # west, south, east, north

    net = load_network(area, key, args.refresh_network)
    segs = net["segments"]
    lamps = load_points(data / "geojson/mapillary_street_lights.geojson", bounds)
    complaints = load_points(data / "geojson/sesizari_iluminat.geojson", bounds)
    log(f"evidence: lamps {'not connected' if lamps is None else len(lamps)}, complaints {'not connected' if complaints is None else len(complaints)}")
    lines, counters = classify(segs, lamps, complaints, as_of)

    groups = {name: shares([s for s in segs if s["kind"] in kinds]) for name, kinds in GROUPS.items()}
    lit_streets = [s for s in segs if s["kind"] == "street" and s["lit"] == "yes"]
    recall = sum(s["L"] for s in lit_streets if "mapillary" in s["fam"]) / (sum(s["L"] for s in lit_streets) or 1.0)
    unknown_core = groups["streets_and_sidewalks"]["unknown"]
    summary = {
        "built_at": dt.datetime.now().isoformat(timespec="seconds"), "as_of": str(as_of), "area": area_meta,
        "area_geometry": shapely.geometry.mapping(area.simplify(0.0001, preserve_topology=True)),  # outline for the page, ~10 m
        "bounds_wsen": [round(x, 6) for x in bounds], "params": PARAMS, "segments": len(segs),
        "network": {"source": "OpenStreetMap via osmnx " + net["osmnx"], "fetched_at": net["fetched_at"], "licence": "ODbL, © OpenStreetMap contributors"},
        "sources": {
            "osm_lit": {"connected": True, "segments_with_tag": sum(1 for s in segs if s["lit"])},
            "mapillary": {"connected": lamps is not None, "file": "mapillary_street_lights.geojson", "lamps_in_area": len(lamps or []),
                          "last_seen_range": date_range([f["properties"].get("last_seen") for f in lamps or []])},
            "sesizari": {"connected": complaints is not None, "file": "sesizari_iluminat.geojson", **counters,
                         "created_range": date_range([(f["properties"].get("created_at") or "")[:10] for f in complaints or []])},
        },
        "groups": groups,
        "known_share": round(100 - unknown_core, 1),
        "checks": {"unknown_share_streets_sidewalks": unknown_core, "unknown_ok": unknown_core <= PARAMS["max_unknown_share"],
                   "lit_no_but_confirmed": sum(1 for s in segs if s["lit"] == "no" and s["status"] == "lit_confirmed"),
                   "lamp_recall_on_lit_yes": round(100 * recall, 1), "lamp_recall_ok": recall >= PARAMS["min_lamp_recall"]},
        "zones": zone_table(segs, lines, data / "geojson/city_zones.geojson", area),
    }
    if lamps:
        lon = [f["geometry"]["coordinates"][0] for f in lamps]
        lat = [f["geometry"]["coordinates"][1] for f in lamps]
        window = box(min(lon) * KX, min(lat) * KY, max(lon) * KX, max(lat) * KY)
        mids = shapely.line_interpolate_point(lines, 0.5, normalized=True)
        outside = ~shapely.contains(window, mids)
        core = [s["kind"] in GROUPS["streets_and_sidewalks"] for s in segs]
        total = sum(s["L"] for s, c in zip(segs, core) if c) or 1.0
        summary["sources"]["mapillary"]["download_window_wsen"] = [round(min(lon), 4), round(min(lat), 4), round(max(lon), 4), round(max(lat), 4)]
        summary["sources"]["mapillary"]["streets_sidewalks_outside_window_pct"] = round(100 * sum(s["L"] for s, c, o in zip(segs, core, outside) if c and o) / total, 1)

    features = []
    for s in segs:
        props = {"id": s["id"], "u": s["u"], "v": s["v"], "kind": s["kind"], "hw": s["hw"], "name": s["name"], "len": round(s["L"], 1),
                 "status": s["status"], "conf": len(s["fam"]), "ev": s["ev"]}
        props.update({t: s[t] for t in KEEP_TAGS if t in s})
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": s["ll"]}, "properties": props})
    out.mkdir(parents=True, exist_ok=True)
    meta = {"as_of": summary["as_of"], "built_at": summary["built_at"], "bounds_wsen": summary["bounds_wsen"], "area": area_meta, "segments": len(segs)}
    with gzip.open(out / "segments.geojson.gz", "wt", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "meta": meta, "features": features}, f, ensure_ascii=False, separators=(",", ":"))
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    size = (out / "segments.geojson.gz").stat().st_size / 1e6
    log(f"written {out}/segments.geojson.gz ({len(segs)} segments, {size:.1f} MB) and summary.json")
    for name, g in groups.items():
        log(f"  {name}: {g['km']} km | " + " | ".join(f"{st} {g[st]}%" for st in STATUSES))
    log(f"  checks: {summary['checks']}")


if __name__ == "__main__":
    main()
