"""T1 b/d helper: Bega centreline profile, boulevard positions, candidate boundary streets.
Usage: t1_geom.py highways.json landmarks_geom.json zones.json"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
from shapely.geometry import LineString, shape, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

ts, g = C.load_ways(sys.argv[1])
lm = json.load(open(sys.argv[2], encoding="utf-8"))
print("landmarks_geom timestamp", lm["osm3s"]["timestamp_osm_base"])
gen = C.bbox_poly(C.GENEROUS)
bega, dorm, cplx = [], [], []
for e in lm["elements"]:
    t = e.get("tags", {})
    ln = None
    if e["type"] == "way" and "geometry" in e:
        ln = LineString([(p["lon"], p["lat"]) for p in e["geometry"]])
    if "waterway" in t and ln is not None:
        bega.append((e["id"], t.get("name"), t.get("waterway"), ln))
    if t.get("building") == "dormitory":
        if ln is not None:
            dorm.append(ln)
        elif "bounds" in e:
            b = e["bounds"]
            dorm.append(box(b["minlon"], b["minlat"], b["maxlon"], b["maxlat"]))
    nm = (C.strip_diacritics(t.get("name", "")) or "").lower()
    if "complex" in nm and "studen" in nm:
        keys = ("place", "building", "landuse", "highway", "public_transport", "tourism")
        if ln is not None:
            cplx.append((e["type"], e["id"], t.get("name"), {k: t[k] for k in keys if k in t}, ln.bounds))
        elif "lat" in e:
            cplx.append((e["type"], e["id"], t.get("name"), {k: t[k] for k in keys if k in t}, (e["lon"], e["lat"], e["lon"], e["lat"])))
for c in cplx:
    w, s, e_, n = c[4]
    print("COMPLEX", c[0], c[1], c[2], c[3], "S W N E", round(s, 5), round(w, 5), round(n, 5), round(e_, 5))
bl = unary_union([b[3] for b in bega]).intersection(gen)
w, s, e_, n = bl.bounds
print("BEGA ways", [(b[0], b[1], b[2]) for b in bega], "clipped to generous bbox: S W N E", round(s, 5), round(w, 5), round(n, 5), round(e_, 5),
      "km", round(gpd.GeoSeries([bl], crs=4326).to_crs(C.CRS_M).length.iloc[0] / 1000, 3))


def pts(x):
    return [p for p in (x.geoms if hasattr(x, "geoms") else [x]) if p.geom_type == "Point"]


for lon in np.arange(21.205, 21.2581, 0.005):
    x = bl.intersection(LineString([(lon, 45.70), (lon, 45.80)]))
    if not x.is_empty:
        print("  bega lat at lon %.3f: %s" % (lon, [round(p.y, 5) for p in pts(x)]))
du = unary_union(dorm)
w, s, e_, n = du.bounds
print("DORM all n", len(dorm), "S W N E", round(s, 5), round(w, 5), round(n, 5), round(e_, 5))
core = [d for d in dorm if 21.2345 < d.centroid.x < 21.2440 and 45.7455 < d.centroid.y < 45.7520]
w, s, e_, n = unary_union(core).bounds
print("DORM core cluster (centroid lon 21.2345..21.2440, lat 45.7455..45.7520) n", len(core), "S W N E", round(s, 5), round(w, 5), round(n, 5), round(e_, 5))
print("DORM outside core centroids:", [(round(d.centroid.y, 5), round(d.centroid.x, 5)) for d in dorm if not any(d is c for c in core)])

g["na"] = g["name"].map(C.strip_diacritics)


def prof(pat, axis):
    m = g[g["na"].fillna("").str.lower().str.contains(pat) & g["highway"].isin(C.STREETS)]
    u = unary_union(list(m.geometry))
    if axis == "lon_at_lat":
        for lat in np.arange(45.730, 45.7581, 0.002):
            x = u.intersection(LineString([(21.15, lat), (21.30, lat)]))
            if not x.is_empty:
                print("   %s lon at lat %.3f: %s" % (pat, lat, sorted({round(p.x, 5) for p in pts(x)})))
    else:
        for lon in np.arange(21.205, 21.2581, 0.004):
            x = u.intersection(LineString([(lon, 45.70), (lon, 45.80)]))
            if not x.is_empty:
                print("   %s lat at lon %.3f: %s" % (pat, lon, sorted({round(p.y, 5) for p in pts(x)})))


prof("16 decembrie", "lon_at_lat")
prof("mihai viteazu", "lon_at_lat")
prof("strada cluj", "lon_at_lat")
prof("vasile parvan", "lat_at_lon")

win = box(21.205, 45.728, 21.258, 45.758)
m = g[g["highway"].isin(["primary", "secondary", "tertiary", "trunk"]) & g["name"].notna() & g.intersects(win)].copy()
m["km"] = m.to_crs(C.CRS_M).length / 1000
rows = []
for nm, grp in m.groupby("name"):
    w, s, e_, n = grp.total_bounds
    rows.append((nm, sorted(set(grp["highway"])), round(grp["km"].sum(), 2), round(s, 5), round(w, 5), round(n, 5), round(e_, 5)))
for r in sorted(rows, key=lambda r: -r[2]):
    print("MAJOR", r)

z = json.load(open(sys.argv[3], encoding="utf-8"))
zg = gpd.GeoDataFrame([{"name": f["properties"]["name"], "geometry": shape(f["geometry"])} for f in z["features"]], crs=4326)
bm = gpd.GeoSeries([bl], crs=4326).to_crs(C.CRS_M).iloc[0]
for nm in ["Complex Studențesc", "Elisabetin", "Odobescu", "Stadion", "Cetate"]:
    zz = zg[zg["name"] == nm].geometry.iloc[0]
    zm = gpd.GeoSeries([zz], crs=4326).to_crs(C.CRS_M).iloc[0]
    print("ZONE", nm, "n_polys", len(zz.geoms), "n_vertices", sum(len(p.exterior.coords) for p in zz.geoms),
          "| boundary-to-Bega min dist m", round(zm.boundary.distance(bm), 1), "| Bega km inside zone", round(zm.intersection(bm).length / 1000, 3),
          "| Bega km within 40 m of zone boundary", round(bm.intersection(zm.boundary.buffer(40)).length / 1000, 3))
    for pat in ["vasile parvan", "mihai viteazu", "16 decembrie", "strada cluj"]:
        mm = g[g["na"].fillna("").str.lower().str.contains(pat) & g["highway"].isin(C.STREETS)].to_crs(C.CRS_M)
        u = unary_union(list(mm.geometry))
        print("     ", pat, "km within 40 m of zone boundary", round(u.intersection(zm.boundary.buffer(40)).length / 1000, 3),
              "| km inside zone", round(u.intersection(zm).length / 1000, 3), "of", round(u.length / 1000, 3))
for combo in (["Complex Studențesc", "Odobescu"], ["Complex Studențesc", "Elisabetin"], ["Complex Studențesc", "Odobescu", "Elisabetin"],
              ["Complex Studențesc", "Odobescu", "Elisabetin", "Stadion"], ["Complex Studențesc", "Stadion"]):
    u3 = unary_union([zg[zg["name"] == n_].geometry.iloc[0].buffer(0.00005) for n_ in combo])
    print("UNION", combo, "bbox S W N E", round(u3.bounds[1], 5), round(u3.bounds[0], 5), round(u3.bounds[3], 5), round(u3.bounds[2], 5),
          "area km2", round(gpd.GeoSeries([u3], crs=4326).to_crs(C.CRS_M).area.iloc[0] / 1e6, 3), "parts", len(getattr(u3, "geoms", [u3])))
