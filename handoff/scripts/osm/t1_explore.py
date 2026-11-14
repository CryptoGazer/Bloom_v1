"""T1 b/c: landmarks and city zones. Usage: t1_explore.py highways.json landmarks.json zones.json"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import geopandas as gpd  # noqa: E402
from shapely.geometry import shape, box  # noqa: E402

hw_path, lm_path, zones_path = sys.argv[1:4]
ts, g = C.load_ways(hw_path)
print("timestamp", ts, "ways", len(g))
print("excluded reasons:", g["excl"].value_counts(dropna=False).to_dict())
g["name_ascii"] = g["name"].map(C.strip_diacritics)

pats = {
    "Bulevardul Vasile Parvan": r"vasile parvan",
    "Bulevardul Mihai Viteazu(l)": r"mihai viteazu",
    "Bulevardul 16 Decembrie 1989": r"16 decembrie",
    "Strada Cluj": r"^strada cluj$",
}
for label, pat in pats.items():
    m = g[g["name_ascii"].fillna("").str.lower().str.contains(pat, regex=True)]
    if len(m) == 0:
        print("LANDMARK", label, "NOT FOUND")
        continue
    w, s, e, n = m.total_bounds
    km = m.to_crs(C.CRS_M).length.sum() / 1000
    print("LANDMARK", label, "| names:", sorted(set(m["name"])), "| highway:", m["highway"].value_counts().to_dict(),
          "| n_ways", len(m), "| km(in generous bbox, unclipped ways)", round(km, 3),
          "| S W N E", round(s, 5), round(w, 5), round(n, 5), round(e, 5), "| lit:", m["lit_status"].value_counts().to_dict())

# all names containing 'cluj' for transparency
print("names containing cluj:", sorted(set(g[g["name_ascii"].fillna("").str.lower().str.contains("cluj")]["name"])))

with open(lm_path, encoding="utf-8") as f:
    lm = json.load(f)
print("landmarks timestamp", lm["osm3s"]["timestamp_osm_base"], "elements", len(lm["elements"]))


def ext(e):
    if "bounds" in e:
        b = e["bounds"]
        return b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]
    if "center" in e:
        c = e["center"]
        return c["lat"], c["lon"], c["lat"], c["lon"]
    if "lat" in e:
        return e["lat"], e["lon"], e["lat"], e["lon"]
    print("   (no geometry for", e["type"], e["id"], e.get("tags", {}).get("name"), ")")
    return None


def union_ext(es):
    xs = [x for x in (ext(e) for e in es) if x]
    return (min(x[0] for x in xs), min(x[1] for x in xs), max(x[2] for x in xs), max(x[3] for x in xs))


groups = {"bega": [], "complex": [], "dorm": [], "univ": []}
for e in lm["elements"]:
    t = e.get("tags", {})
    nm = C.strip_diacritics(t.get("name", "")) or ""
    if "waterway" in t and "bega" in nm.lower():
        groups["bega"].append(e)
    if re.search(r"complex(ul)? studen", nm, re.I):
        groups["complex"].append(e)
    if t.get("building") == "dormitory":
        groups["dorm"].append(e)
    if t.get("amenity") == "university":
        groups["univ"].append(e)

for k, es in groups.items():
    print("GROUP", k, "n", len(es), "extent S W N E", [round(v, 5) for v in union_ext(es)] if es else None)
    for e in es:
        t = e.get("tags", {})
        if k in ("bega", "complex") or (k == "univ"):
            print("   ", e["type"], e["id"], "|", t.get("name"), "|", {kk: t[kk] for kk in ("waterway", "place", "landuse", "amenity", "highway", "building", "boundary", "type") if kk in t},
                  "| ext", [round(v, 5) for v in (ext(e) or [])])
# Bega inside generous bbox: clip of bounds is not possible from bb only; report way bounds individually above.
# dormitory cluster: trimmed extent (5th..95th percentile of centres)
import numpy as np  # noqa: E402
if groups["dorm"]:
    cs = []
    for e in groups["dorm"]:
        if "center" in e:
            cs.append((e["center"]["lat"], e["center"]["lon"]))
        elif "lat" in e:
            cs.append((e["lat"], e["lon"]))
    cs = np.array(cs)
    print("dorm centres n", len(cs), "lat p5/p50/p95", np.percentile(cs[:, 0], [5, 50, 95]).round(5),
          "lon p5/p50/p95", np.percentile(cs[:, 1], [5, 50, 95]).round(5))
    # main cluster: centres within 600 m of median
    med = np.median(cs, axis=0)
    dlat = (cs[:, 0] - med[0]) * 111320
    dlon = (cs[:, 1] - med[1]) * 111320 * np.cos(np.radians(med[0]))
    dist = np.hypot(dlat, dlon)
    core = cs[dist < 600]
    print("dorm main cluster (within 600 m of median centre", med.round(5), ") n", len(core),
          "extent S W N E", core[:, 0].min().round(5), core[:, 1].min().round(5), core[:, 0].max().round(5), core[:, 1].max().round(5))

# zones
with open(zones_path, encoding="utf-8") as f:
    z = json.load(f)
feats = z["features"]
print("zones n", len(feats), "property keys", sorted({k for ft in feats for k in ft["properties"].keys()}))
zg = gpd.GeoDataFrame([{"name": ft["properties"].get("name"), "slug": ft["properties"].get("slug"),
                        "geometry": shape(ft["geometry"])} for ft in feats], crs="EPSG:4326")
zg["valid"] = zg.is_valid
zg["geometry"] = zg.geometry.buffer(0)
zm = zg.to_crs(C.CRS_M)
zg["area_km2"] = zm.area / 1e6
print("invalid zone geometries:", int((~zg["valid"]).sum()))
# rough district box for overlap test: campus + boulevards (from landmark extents printed above; passed later)
probe = box(21.205, 45.732, 21.250, 45.757)
pm = gpd.GeoSeries([probe], crs="EPSG:4326").to_crs(C.CRS_M).iloc[0]
print("probe box (S 45.732 W 21.205 N 45.757 E 21.250) area km2", round(pm.area / 1e6, 3))
for i, r in zm.iterrows():
    inter = r.geometry.intersection(pm).area / 1e6
    if inter > 0:
        w, s, e, n = zg.geometry.iloc[i].bounds
        print("ZONE", zg["name"].iloc[i], "| slug", zg["slug"].iloc[i], "| area km2", round(zg["area_km2"].iloc[i], 3),
              "| overlap with probe km2", round(inter, 3), "| bbox S W N E", round(s, 5), round(w, 5), round(n, 5), round(e, 5))
print("all zone names:", sorted(zg["name"]))
