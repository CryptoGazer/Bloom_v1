"""T1 d helper: numbers needed to place bbox edges. Usage: t1_edges.py highways.json landmarks_geom.json"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from shapely.geometry import LineString, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

ts, g = C.load_ways(sys.argv[1])
lm = json.load(open(sys.argv[2], encoding="utf-8"))
bega = unary_union([LineString([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in lm["elements"]
                    if e["type"] == "way" and "waterway" in e.get("tags", {})])
for (w, e) in [(21.2090, 21.2355), (21.2110, 21.2355), (21.2248, 21.2355), (21.2248, 21.2440), (21.2090, 21.2440)]:
    seg = bega.intersection(box(w, 45.70, e, 45.80))
    print("Bega centreline for lon %.4f..%.4f: lat min %.5f max %.5f ; +60 m north of max = %.5f" % (w, e, seg.bounds[1], seg.bounds[3], seg.bounds[3] + 60 / 111200))
# where does the canal cross lat 45.7510 / 45.7515 / 45.752
for lat in (45.7505, 45.7510, 45.7515, 45.7520):
    x = bega.intersection(LineString([(21.19, lat), (21.27, lat)]))
    print("Bega lon at lat", lat, [round(p.x, 5) for p in (x.geoms if hasattr(x, "geoms") else [x]) if p.geom_type == "Point"])
st = g[g["highway"].isin(C.STREETS) & g["name"].notna() & g["excl"].isna()]
for label, win in [("EAST strip lon 21.240..21.252 lat 45.741..45.752", box(21.240, 45.741, 21.252, 45.752)),
                   ("SOUTH strip lon 21.209..21.246 lat 45.736..45.7445", box(21.209, 45.736, 21.246, 45.7445)),
                   ("WEST strip lon 21.207..21.226 lat 45.741..45.752", box(21.207, 45.741, 21.226, 45.752))]:
    print(label)
    m = st[st.intersects(win)]
    for nm, grp in m.groupby("name"):
        w, s, e, n = grp.total_bounds
        km = grp.to_crs(C.CRS_M).length.sum() / 1000
        if km >= 0.25:
            print("   %-48s %-28s km %.2f  S %.5f W %.5f N %.5f E %.5f" % (nm, ",".join(sorted(set(grp["highway"]))), km, s, w, n, e))
