"""Way-level analysis: T1d, T1e, T2, T5, T6, T7.
Usage: ways_analysis.py highways.json landmarks_geom.json zones.json street_lamps.json OUT_DIR"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
from variants import VARIANTS  # noqa: E402
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, Point, box, shape  # noqa: E402
from shapely.ops import split, unary_union  # noqa: E402

hw_path, lm_path, zones_path, lamps_path, out_dir = sys.argv[1:6]
os.makedirs(out_dir, exist_ok=True)
R = {}  # machine-readable results

ts, g_all = C.load_ways(hw_path)
R["timestamp_osm_base"] = ts
print("# OSM timestamp", ts, "| highway ways in generous extract:", len(g_all))
print("excluded by rule:", g_all["excl"].value_counts().to_dict())
# street-class ways lost to the access rule (matters for the osmnx custom filter)
sx = g_all[g_all["highway"].isin(C.STREETS)]
print("street-class ways: total", len(sx), "| excluded", sx["excl"].value_counts().to_dict(),
      "| access private/no but kept through foot/bicycle:", int(((sx["tags"].map(lambda t: t.get("access") in ("private", "no"))) & sx["excl"].isna()).sum()))
g = g_all[g_all["excl"].isna()].copy()
g["named"] = g["name"].notna()
print("lit values, all highway ways of the generous extract (before exclusions):", g_all["lit"].fillna("(missing)").value_counts().to_dict())


def fmt(x, nd=2):
    return ("%." + str(nd) + "f") % x


def pct(a, b):
    return "n/a" if b == 0 else "%.1f%%" % (100.0 * a / b)


# ---------------------------------------------------------------- T1d
print("\n## T1d variants")
z = json.load(open(zones_path, encoding="utf-8"))
zg = gpd.GeoDataFrame([{"name": f["properties"]["name"], "geometry": shape(f["geometry"])} for f in z["features"]], crs=4326).to_crs(C.CRS_M)
R["variants"] = {}
for vid, b in VARIANTS.items():
    a = C.area_km2(b)
    pm = C.bbox_poly_m(b)
    R["variants"][vid] = {"bbox_swne": list(b), "area_km2": round(a, 3)}
    ov = []
    for _, r in zg.iterrows():
        inter = r.geometry.intersection(pm).area / 1e6
        if inter > 0.01:
            ov.append((r["name"], round(inter, 3), round(100 * inter / a, 1), round(100 * inter / (r.geometry.area / 1e6), 1)))
    ov.sort(key=lambda t: -t[1])
    R["variants"][vid]["zone_overlap"] = ov
    print(vid, list(b), "area km2 %.3f" % a, "| width m %.0f height m %.0f" % (pm.bounds[2] - pm.bounds[0], pm.bounds[3] - pm.bounds[1]))
    print("   zone overlap (zone, km2 inside bbox, % of bbox, % of zone):", ov)

# ---------------------------------------------------------------- T2
print("\n## T2 composition")


def comp_table(sub):
    rows = []
    for cls in C.CLASS_ORDER + ["allnet"]:
        s = sub if cls == "allnet" else sub[sub["cls"] == cls]
        if len(s) == 0:
            continue
        km = s["km"].sum()
        yes = s.loc[s["lit_status"] == "yes", "km"].sum()
        no = s.loc[s["lit_status"] == "no", "km"].sum()
        mis = s.loc[s["lit_status"] == "missing", "km"].sum()
        oth = km - yes - no - mis
        rows.append({"class": cls, "n_ways": len(s), "km": km, "lit_yes_km": yes, "lit_no_km": no, "lit_missing_km": mis,
                     "lit_other_km": oth, "lit_tagged_share": (km - mis) / km if km else np.nan,
                     "named_share": s.loc[s["named"], "km"].sum() / km if km else np.nan})
    return pd.DataFrame(rows)


clipped = {}
for vid, b in VARIANTS.items():
    sub = C.clip_to_bbox(g, b)
    clipped[vid] = sub
    t = comp_table(sub)
    R["variants"][vid]["composition"] = json.loads(t.round(4).to_json(orient="records"))
    print("\n### T2 -", vid, list(b))
    print("| class | n_ways | km | lit yes km | lit no km | lit missing km | lit other km | lit-tagged share | named share of km |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in t.iterrows():
        print("| %s | %d | %s | %s | %s | %s | %s | %.1f%% | %.1f%% |" % (r["class"], r["n_ways"], fmt(r["km"]), fmt(r["lit_yes_km"]), fmt(r["lit_no_km"]),
                                                                   fmt(r["lit_missing_km"]), fmt(r["lit_other_km"]), 100 * r["lit_tagged_share"], 100 * r["named_share"]))
    st = t[t["class"] == "streets"].iloc[0]
    al = t[t["class"] == "allnet"].iloc[0]
    litvals = sub["lit"].fillna("(missing)").value_counts().to_dict()
    litvals_st = sub[sub["cls"] == "streets"]["lit"].fillna("(missing)").value_counts().to_dict()
    R["variants"][vid]["lit_values_allnet_ways"] = litvals
    R["variants"][vid]["lit_values_streets_ways"] = litvals_st
    print("headline: lit-tagged share of streets km = %.1f%% ; of allnet km = %.1f%%" % (100 * st["lit_tagged_share"], 100 * al["lit_tagged_share"]))
    print("streets ways with a lit tag: %d of %d (%.1f%% of ways)" % (int((sub[sub["cls"] == "streets"]["lit_status"] != "missing").sum()), int(st["n_ways"]),
                                                              100 * (sub[sub["cls"] == "streets"]["lit_status"] != "missing").mean()))
    print("distinct street NAMES in variant:", sub[sub["cls"] == "streets"]["name"].nunique(), "| names with any lit-tagged way:",
          sub[(sub["cls"] == "streets") & (sub["lit_status"] != "missing")]["name"].nunique())
    print("lit values (allnet ways):", litvals)
    print("lit values (streets ways):", litvals_st)
    oth = sub[sub["cls"] == "other"]["highway"].value_counts().to_dict()
    if oth:
        print("highway values in class other:", oth)
    # whole-way length quantiles for streets (clipped lengths), for comparison with segments (T3)
    L = sub[sub["cls"] == "streets"]["km"].values * 1000
    q = np.percentile(L, [10, 50, 75, 90, 99])
    R["variants"][vid]["street_way_len_m"] = {"n": int(len(L)), "p10": q[0], "p50": q[1], "p75": q[2], "p90": q[3], "p99": q[4], "max": float(L.max()),
                                              "n_gt200": int((L > 200).sum()), "km_gt200": float(L[L > 200].sum() / 1000),
                                              "n_gt400": int((L > 400).sum()), "km_gt400": float(L[L > 400].sum() / 1000)}
    print("street WAY lengths m (clipped): n %d p10 %.1f p50 %.1f p75 %.1f p90 %.1f p99 %.1f max %.1f | >200 m: %d ways %.2f km | >400 m: %d ways %.2f km" % (
        len(L), q[0], q[1], q[2], q[3], q[4], L.max(), (L > 200).sum(), L[L > 200].sum() / 1000, (L > 400).sum(), L[L > 400].sum() / 1000))
    La = sub["km"].values * 1000
    qa = np.percentile(La, [10, 50, 75, 90, 99])
    print("allnet WAY lengths m (clipped): n %d p10 %.1f p50 %.1f p75 %.1f p90 %.1f p99 %.1f max %.1f" % (len(La), qa[0], qa[1], qa[2], qa[3], qa[4], La.max()))

# generous bbox reference
subg = C.clip_to_bbox(g, C.GENEROUS)
tg = comp_table(subg)
print("\n### reference: generous bbox", list(C.GENEROUS), "area km2 %.2f" % C.area_km2(C.GENEROUS))
for _, r in tg.iterrows():
    print("| %s | %d | %s | %s | %s | %s | %s | %.1f%% | %.1f%% |" % (r["class"], r["n_ways"], fmt(r["km"]), fmt(r["lit_yes_km"]), fmt(r["lit_no_km"]),
                                                               fmt(r["lit_missing_km"]), fmt(r["lit_other_km"]), 100 * r["lit_tagged_share"], 100 * r["named_share"]))

# ---------------------------------------------------------------- T1e grid
print("\n## T1e 250 m grid")
streets_g = subg[subg["cls"] == "streets"].copy()
minx, miny, maxx, maxy = C.bbox_poly_m(C.GENEROUS).bounds
x0, y0 = np.floor(minx / 250) * 250, np.floor(miny / 250) * 250
nx_, ny_ = int(np.ceil((maxx - x0) / 250)), int(np.ceil((maxy - y0) / 250))
geoms = streets_g.geometry.values
tree = shapely.STRtree(geoms)
tagged = (streets_g["lit_status"] != "missing").values
yes = (streets_g["lit_status"] == "yes").values
no = (streets_g["lit_status"] == "no").values
to_ll = gpd.GeoSeries
rows = []
for i in range(nx_):
    for j in range(ny_):
        cell = box(x0 + i * 250, y0 + j * 250, x0 + (i + 1) * 250, y0 + (j + 1) * 250)
        idx = tree.query(cell, predicate="intersects")
        if len(idx):
            ln = shapely.length(shapely.intersection(geoms[idx], cell)) / 1000
            km, tk, yk, nk = ln.sum(), ln[tagged[idx]].sum(), ln[yes[idx]].sum(), ln[no[idx]].sum()
        else:
            km = tk = yk = nk = 0.0
        rows.append({"col": i, "row": j, "x_min_utm34n": x0 + i * 250, "y_min_utm34n": y0 + j * 250, "street_km": km, "lit_tagged_km": tk,
                     "lit_yes_km": yk, "lit_no_km": nk, "lit_missing_km": km - tk, "lit_tagged_share": (tk / km) if km > 0 else np.nan})
grid = pd.DataFrame(rows)
cent = gpd.GeoSeries([Point(r.x_min_utm34n + 125, r.y_min_utm34n + 125) for r in grid.itertuples()], crs=C.CRS_M).to_crs(4326)
grid["lon_centre"], grid["lat_centre"] = cent.x.round(6), cent.y.round(6)
for vid, b in VARIANTS.items():
    grid["centre_in_" + vid] = ((grid["lat_centre"] >= b[0]) & (grid["lat_centre"] <= b[2]) & (grid["lon_centre"] >= b[1]) & (grid["lon_centre"] <= b[3])).astype(int)
grid_path = os.path.join(out_dir, "grid250_streets_lit.csv")
grid.round(5).to_csv(grid_path, index=False)
print("grid cells", len(grid), "(", nx_, "x", ny_, ") with streets:", int((grid["street_km"] > 0).sum()), "-> saved", grid_path)
print("grid total street km %.2f (generous clipped streets km %.2f)" % (grid["street_km"].sum(), streets_g["km"].sum()))
ge = grid[(grid["centre_in_extended"] == 1) & (grid["street_km"] > 0.02)]
print("cells with centre in extended and >20 m of street:", len(ge), "| share >=90%% tagged: %d | 50-90%%: %d | 10-50%%: %d | <10%%: %d" % (
    (ge["lit_tagged_share"] >= 0.9).sum(), ((ge["lit_tagged_share"] < 0.9) & (ge["lit_tagged_share"] >= 0.5)).sum(),
    ((ge["lit_tagged_share"] < 0.5) & (ge["lit_tagged_share"] >= 0.1)).sum(), (ge["lit_tagged_share"] < 0.1).sum()))
gg = grid[grid["street_km"] > 0.02]
print("same over the generous bbox: cells %d | >=90%%: %d | 50-90%%: %d | 10-50%%: %d | <10%%: %d" % (
    len(gg), (gg["lit_tagged_share"] >= 0.9).sum(), ((gg["lit_tagged_share"] < 0.9) & (gg["lit_tagged_share"] >= 0.5)).sum(),
    ((gg["lit_tagged_share"] < 0.5) & (gg["lit_tagged_share"] >= 0.1)).sum(), (gg["lit_tagged_share"] < 0.1).sum()))
# ascii map of tagged share over the extended area (rows north -> south)
print("grid map, cells with centre in extended; rows north->south, cols west->east; value = lit-tagged share in tenths (., = no street), u = untagged km*10")
for j in sorted(ge["row"].unique(), reverse=True):
    line, line2 = [], []
    for i in sorted(ge["col"].unique()):
        r = ge[(ge["col"] == i) & (ge["row"] == j)]
        if len(r) == 0:
            line.append(" .")
            line2.append("  .")
        else:
            line.append("%2d" % int(round(10 * r["lit_tagged_share"].iloc[0])))
            line2.append("%3d" % int(round(10 * r["lit_missing_km"].iloc[0])))
    lat = ge[ge["row"] == j]["lat_centre"].mean()
    print("  lat %.4f | %s |   untagged km x10: %s" % (lat, " ".join(line), " ".join(line2)))
print("  lon centres:", [round(ge[ge["col"] == i]["lon_centre"].mean(), 4) for i in sorted(ge["col"].unique())])

# sub-areas of the extended variant
lm = json.load(open(lm_path, encoding="utf-8"))
bega = unary_union([LineString([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in lm["elements"]
                    if e["type"] == "way" and "waterway" in e.get("tags", {})])
bega = shapely.line_merge(bega)
ext_b = VARIANTS["extended"]
ext_poly = C.bbox_poly(ext_b)
parts = list(split(ext_poly, bega).geoms)
print("extended bbox split by Bega centreline into", len(parts), "parts; areas km2:",
      [round(a, 3) for a in gpd.GeoSeries(parts, crs=4326).to_crs(C.CRS_M).area / 1e6])
north = max(parts, key=lambda p: p.centroid.y) if len(parts) > 1 else None
regions = {}
if north is not None:
    regions["north bank (between Bega centreline and north edge)"] = north
south_all = unary_union([p for p in parts if p is not north])
LON1, LON2, LAT1 = 21.2255, 21.2355, 45.7444
bands = [("west: 16 Decembrie..Mihai Viteazu", ext_b[1], LON1), ("middle: Mihai Viteazu..Strada Cluj", LON1, LON2), ("east: Strada Cluj..Aleea F.C. Ripensia", LON2, ext_b[3])]
for nm, w, e in bands:
    regions[nm + " / north of Bd. V. Babes line (lat 45.7444), south of Bega"] = south_all.intersection(box(w, LAT1, e, ext_b[2]))
    regions[nm + " / south of lat 45.7444"] = south_all.intersection(box(w, ext_b[0], e, LAT1))
st_ext_ll = g[(g["cls"] == "streets") & g.intersects(ext_poly)].copy()
print("| sub-area of extended | area km2 | streets km | untagged km | lit-tagged share | share of all untagged street km |")
print("|---|---:|---:|---:|---:|---:|")
tot_untag = clipped["extended"][(clipped["extended"]["cls"] == "streets") & (clipped["extended"]["lit_status"] == "missing")]["km"].sum()
R["subareas_extended"] = []
for nm, poly in regions.items():
    if poly.is_empty:
        continue
    s = st_ext_ll[st_ext_ll.intersects(poly)].copy()
    s["geometry"] = s.geometry.intersection(poly)
    s = s.to_crs(C.CRS_M)
    km = s.length.sum() / 1000
    un = s[s["lit_status"] == "missing"].length.sum() / 1000
    a = gpd.GeoSeries([poly], crs=4326).to_crs(C.CRS_M).area.iloc[0] / 1e6
    R["subareas_extended"].append({"name": nm, "area_km2": a, "streets_km": km, "untagged_km": un})
    print("| %s | %.3f | %.2f | %.2f | %s | %s |" % (nm, a, km, un, pct(km - un, km), pct(un, tot_untag)))
se = clipped["extended"][clipped["extended"]["cls"] == "streets"]
un = se[se["lit_status"] == "missing"].copy()
un["nm"] = un["name"].fillna("(unnamed)")
top = un.groupby("nm").agg(km=("km", "sum"), n_ways=("id", "count"), hw=("highway", lambda x: ",".join(sorted(set(x))))).sort_values("km", ascending=False)
print("untagged street names in extended:", len(top), "| total untagged km %.2f" % un["km"].sum())
print("| # | untagged street (extended) | untagged km | n ways | highway | km of same name tagged in extended |")
print("|---:|---|---:|---:|---|---:|")
R["top_untagged_extended"] = []
for k, (nm, r) in enumerate(top.head(15).iterrows(), 1):
    tk = se[(se["name"] == nm) & (se["lit_status"] != "missing")]["km"].sum() if nm != "(unnamed)" else se[se["name"].isna() & (se["lit_status"] != "missing")]["km"].sum()
    R["top_untagged_extended"].append({"name": nm, "km": round(float(r["km"]), 3)})
    print("| %d | %s | %.3f | %d | %s | %.3f |" % (k, nm, r["km"], r["n_ways"], r["hw"], tk))
# untagged km by highway value in extended
print("untagged streets km by highway value (extended):", un.groupby("highway")["km"].sum().round(2).to_dict(),
      "| all streets km by highway:", se.groupby("highway")["km"].sum().round(2).to_dict())

# ---------------------------------------------------------------- T5
print("\n## T5 sidewalks and non-street paths (extended)")
ext = clipped["extended"]
st = ext[ext["cls"] == "streets"]
st_km = st["km"].sum()
all_km = ext["km"].sum()
print("footway_sidewalk km: %.2f (n ways %d)" % (ext[ext["cls"] == "footway_sidewalk"]["km"].sum(), (ext["cls"] == "footway_sidewalk").sum()))
keys = ["sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both"]
anyk = st["tags"].map(lambda t: any(k in t for k in keys))
print("| sidewalk tag on streets | n ways | km | share of streets km |")
print("|---|---:|---:|---:|")
for k in keys:
    m = st["tags"].map(lambda t, k=k: k in t)
    print("| %s | %d | %.2f | %s |" % (k, m.sum(), st[m]["km"].sum(), pct(st[m]["km"].sum(), st_km)))
print("| any of the four | %d | %.2f | %s |" % (anyk.sum(), st[anyk]["km"].sum(), pct(st[anyk]["km"].sum(), st_km)))
R["t5"] = {"footway_sidewalk_km": float(ext[ext["cls"] == "footway_sidewalk"]["km"].sum()), "streets_any_sidewalk_tag_share": float(st[anyk]["km"].sum() / st_km)}
vals = Counter()
kmvals = defaultdict(float)
for t, km in zip(st["tags"], st["km"]):
    for k in keys:
        if k in t:
            vals[k + "=" + t[k]] += 1
            kmvals[k + "=" + t[k]] += km
print("sidewalk tag values on streets (ways, km):", {k: (v, round(kmvals[k], 2)) for k, v in vals.most_common()})
ns = ext[ext["cls"] != "streets"]
print("non-street share of allnet km: %s (%.2f of %.2f km) ; lit-tagged share of non-street km: %s" % (
    pct(ns["km"].sum(), all_km), ns["km"].sum(), all_km, pct(ns[ns["lit_status"] != "missing"]["km"].sum(), ns["km"].sum())))
R["t5"]["nonstreet_share_allnet"] = float(ns["km"].sum() / all_km)
R["t5"]["nonstreet_lit_tagged_share"] = float(ns[ns["lit_status"] != "missing"]["km"].sum() / ns["km"].sum())
walk = ext[ext["cls"].isin(C.NONSTREET_WALK)].copy()
wk = walk["km"].sum()
print("non-street walk/bike classes (pedestrian, footway_*, cycleway, path, steps): %.2f km, lit-tagged %s" % (wk, pct(walk[walk["lit_status"] != "missing"]["km"].sum(), wk)))
# street centrelines: every street-class way of the generous extract (so streets just outside the bbox still count)
cl = unary_union(list(g[g["cls"].isin(["streets", "trunk"])].to_crs(C.CRS_M).geometry.values))
print("| group | km | share of non-street walk/bike km | lit-tagged share | lit=yes share | lit=no share |")
print("|---|---:|---:|---:|---:|---:|")
tag_m = (walk["lit_status"] != "missing").values
yes_m = (walk["lit_status"] == "yes").values
no_m = (walk["lit_status"] == "no").values
wgeom = walk.geometry.values
prev = np.zeros(len(walk))
R["t5"]["proximity"] = {}
for r in (15, 25):
    buf = cl.buffer(r)
    shapely.prepare(buf)
    inside = shapely.length(shapely.intersection(wgeom, buf)) / 1000
    R["t5"]["proximity"][str(r)] = {"km": float(inside.sum()), "share": float(inside.sum() / wk), "lit_tagged_share": float(inside[tag_m].sum() / inside.sum())}
    print("| within %d m of a street centreline | %.2f | %s | %s | %s | %s |" % (r, inside.sum(), pct(inside.sum(), wk), pct(inside[tag_m].sum(), inside.sum()),
                                                                      pct(inside[yes_m].sum(), inside.sum()), pct(inside[no_m].sum(), inside.sum())))
    rest = walk["km"].values - inside
    print("| farther than %d m (park/campus/embankment paths) | %.2f | %s | %s | %s | %s |" % (r, rest.sum(), pct(rest.sum(), wk), pct(rest[tag_m].sum(), rest.sum()),
                                                                                   pct(rest[yes_m].sum(), rest.sum()), pct(rest[no_m].sum(), rest.sum())))
    R["t5"]["proximity"][str(r)]["rest_km"] = float(rest.sum())
    R["t5"]["proximity"][str(r)]["rest_lit_tagged_share"] = float(rest[tag_m].sum() / rest.sum())
    walk["in%d" % r] = inside
print("per class (km, km within 15 m, km within 25 m, lit-tagged share):")
print("| class | km | within 15 m | within 25 m | lit-tagged share |")
print("|---|---:|---:|---:|---:|")
for cls in C.NONSTREET_WALK:
    s = walk[walk["cls"] == cls]
    if len(s):
        print("| %s | %.2f | %s | %s | %s |" % (cls, s["km"].sum(), pct(s["in15"].sum(), s["km"].sum()), pct(s["in25"].sum(), s["km"].sum()),
                                           pct(s[s["lit_status"] != "missing"]["km"].sum(), s["km"].sum())))
sv = ext[ext["cls"] == "service"]
print("service: %.2f km; service=* values (km):" % sv["km"].sum(), sv.assign(sv=sv["tags"].map(lambda t: t.get("service", "(none)"))).groupby("sv")["km"].sum().round(2).to_dict())

# ---------------------------------------------------------------- T6
print("\n## T6 same-name propagation (extended, streets)")


def propagation(st, label):
    named = st[st["name"].notna()]
    unn = st[st["name"].isna()]
    tot = st["km"].sum()
    un0 = st[st["lit_status"] == "missing"]["km"].sum()
    print("[%s] streets km %.2f | ways %d | named km %.2f | unnamed km %.2f (untagged %.2f)" % (
        label, tot, len(st), named["km"].sum(), unn["km"].sum(), unn[unn["lit_status"] == "missing"]["km"].sum()))
    grp = named.groupby("name")
    info = []
    for nm, s in grp:
        info.append({"name": nm, "km": s["km"].sum(), "n": len(s), "yes_km": s[s["lit_status"] == "yes"]["km"].sum(), "no_km": s[s["lit_status"] == "no"]["km"].sum(),
                     "mis_km": s[s["lit_status"] == "missing"]["km"].sum(), "n_yes": (s["lit_status"] == "yes").sum(), "n_no": (s["lit_status"] == "no").sum(),
                     "n_mis": (s["lit_status"] == "missing").sum(), "oth_km": s[~s["lit_status"].isin(["yes", "no", "missing"])]["km"].sum()})
    d = pd.DataFrame(info)
    hy, hn = d[d["n_yes"] > 0], d[d["n_no"] > 0]
    both = d[(d["n_yes"] > 0) & (d["n_no"] > 0)]
    print("names: %d | names with >=1 lit=yes way: %d | of those also having missing ways: %d (%.2f km missing) | fully tagged names: %d | names with no tagged way: %d (%.2f km)" % (
        len(d), len(hy), (hy["n_mis"] > 0).sum(), hy["mis_km"].sum(), ((d["n_mis"] == 0)).sum(), ((d["n_yes"] + d["n_no"] == 0) & (d["oth_km"] == 0)).sum(),
        d[(d["n_yes"] + d["n_no"] == 0) & (d["oth_km"] == 0)]["km"].sum()))
    print("names with >=1 lit=no way: %d | of those also having missing ways: %d (%.2f km missing)" % (len(hn), (hn["n_mis"] > 0).sum(), hn["mis_km"].sum()))
    print("names with BOTH yes and no: %d" % len(both))
    for _, r in both.iterrows():
        print("   %s: yes %.3f km (%d ways), no %.3f km (%d ways), missing %.3f km (%d ways)" % (r["name"], r["yes_km"], r["n_yes"], r["no_km"], r["n_no"], r["mis_km"], r["n_mis"]))
    hy_only = d[(d["n_yes"] > 0) & (d["n_no"] == 0)]
    hn_only = d[(d["n_no"] > 0) & (d["n_yes"] == 0)]
    a_yes = un0 - hy["mis_km"].sum()
    a_yes_nc = un0 - hy_only["mis_km"].sum()
    a_no = un0 - hn["mis_km"].sum()
    a_both_nc = un0 - hy_only["mis_km"].sum() - hn_only["mis_km"].sum()
    print("untagged streets km now: %.2f (%s of streets km)" % (un0, pct(un0, tot)))
    print("  after propagating lit=yes along same name: %.2f km (%s) ; excluding yes/no-conflict names: %.2f km (%s)" % (a_yes, pct(a_yes, tot), a_yes_nc, pct(a_yes_nc, tot)))
    print("  after propagating lit=no along same name: %.2f km (%s)" % (a_no, pct(a_no, tot)))
    print("  after propagating both (non-conflicting names only): %.2f km (%s)" % (a_both_nc, pct(a_both_nc, tot)))
    # leave-one-out agreement among tagged ways: would the other tagged ways of the same name predict this way's value?
    tg_ = named[named["lit_status"].isin(["yes", "no"])]
    n_test = n_ok = 0
    km_test = km_ok = 0.0
    n_no_test = n_no_ok = 0
    for nm, s in tg_.groupby("name"):
        if len(s) < 2:
            continue
        for i in range(len(s)):
            others = s.drop(s.index[i])
            yk = others[others["lit_status"] == "yes"]["km"].sum()
            nk = others[others["lit_status"] == "no"]["km"].sum()
            pred = "yes" if yk >= nk else "no"
            actual = s["lit_status"].iloc[i]
            n_test += 1
            km_test += s["km"].iloc[i]
            if pred == actual:
                n_ok += 1
                km_ok += s["km"].iloc[i]
            if actual == "no":
                n_no_test += 1
                n_no_ok += int(pred == "no")
    print("  leave-one-out check on tagged ways (names with >=2 tagged ways): %d ways tested, %d agree (%s); km %.2f of %.2f (%s); lit=no ways tested %d, predicted no %d" % (
        n_test, n_ok, pct(n_ok, n_test), km_ok, km_test, pct(km_ok, km_test), n_no_test, n_no_ok))
    # how far apart are the propagated-to ways from the nearest tagged way of the same name
    dists = []
    for nm, s in named.groupby("name"):
        t_ = s[s["lit_status"] == "yes"]
        m_ = s[s["lit_status"] == "missing"]
        if len(t_) and len(m_):
            u = unary_union(list(t_.geometry.values))
            for geom, km in zip(m_.geometry.values, m_["km"].values):
                dists.append((geom.distance(u), km))
    if dists:
        dd = np.array(dists)
        print("  gap between an untagged way and the nearest lit=yes way of the same name: n %d | touching (0 m): %d (%.2f km) | <=50 m: %d (%.2f km) | >50 m: %d (%.2f km) | max %.0f m" % (
            len(dd), (dd[:, 0] < 0.5).sum(), dd[dd[:, 0] < 0.5, 1].sum(), (dd[:, 0] <= 50).sum(), dd[dd[:, 0] <= 50, 1].sum(), (dd[:, 0] > 50).sum(), dd[dd[:, 0] > 50, 1].sum(), dd[:, 0].max()))
    return {"names": int(len(d)), "names_with_yes": int(len(hy)), "names_with_yes_and_missing": int((hy["n_mis"] > 0).sum()), "missing_km_on_yes_names": float(hy["mis_km"].sum()),
            "names_both": both[["name", "yes_km", "no_km", "mis_km"]].round(3).to_dict("records"), "untagged_now_km": float(un0), "untagged_after_yes_km": float(a_yes),
            "untagged_after_no_km": float(a_no), "untagged_after_both_nonconflict_km": float(a_both_nc), "streets_km": float(tot),
            "loo_n": n_test, "loo_ok": n_ok}


R["t6_extended"] = propagation(clipped["extended"][clipped["extended"]["cls"] == "streets"], "extended")
R["t6_compact"] = propagation(clipped["compact"][clipped["compact"]["cls"] == "streets"], "compact")
R["t6_generous"] = propagation(subg[subg["cls"] == "streets"], "generous bbox (reference)")

# ---------------------------------------------------------------- T7
print("\n## T7 street lamps")
lamps = json.load(open(lamps_path, encoding="utf-8"))
pts = [(e["lat"], e["lon"]) for e in lamps["elements"] if e["type"] == "node"]
print("lamps timestamp", lamps["osm3s"]["timestamp_osm_base"], "| highway=street_lamp nodes in generous bbox:", len(pts))
R["lamps"] = {"generous": len(pts)}
for vid, b in VARIANTS.items():
    n = sum(1 for la, lo in pts if b[0] <= la <= b[2] and b[1] <= lo <= b[3])
    R["lamps"][vid] = n
    print("   ", vid, n)
print("lamp nodes (lat, lon):", [(round(a, 5), round(b_, 5)) for a, b_ in pts])

json.dump(R, open(os.path.join(out_dir, "ways_results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
