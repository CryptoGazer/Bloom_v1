"""Dry run of the lighting-confidence rules on the user's data pack (analysis only, not project code).
usage: python -I dryrun.py <unihack-data dir> <osmnx cache dir>"""
import json, sys, math, datetime as dt
from collections import Counter
import numpy as np
import shapely
from shapely.geometry import LineString, shape, box
from shapely.strtree import STRtree

sys.stdout.reconfigure(encoding="utf-8")
D, CACHE = sys.argv[1], sys.argv[2]
NOW = dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc)
KX, KY = 77811.0, 111147.0  # metres per degree at lat 45.748


def load(n):
    return json.load(open(f"{D}/geojson/{n}", encoding="utf-8"))["features"]


STREET = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
          "unclassified", "residential", "living_street"}
OKV = ("yes", "designated", "permissive")


def klass(p):
    h = p.get("highway")
    if p.get("access") in ("private", "no") and p.get("foot") not in OKV and p.get("bicycle") not in OKV:
        return None
    if h in STREET:
        return "street"
    if h == "footway":
        f = p.get("footway")
        return "sidewalk" if f == "sidewalk" else ("crossing" if f == "crossing" else "path")
    if h in ("path", "pedestrian", "cycleway", "steps"):
        return "path"
    return None


xy, cls, lit, name, w = [], [], [], [], []
for f in load("osm_highways.geojson"):
    p = f["properties"]
    k = klass(p)
    if not k:
        continue
    line = LineString([(x * KX, y * KY) for x, y in f["geometry"]["coordinates"]])
    L = line.length
    if L <= 0:
        continue
    n = max(1, int(round(L / 10.0)))
    pts = shapely.line_interpolate_point(line, (np.arange(n) + 0.5) * L / n)
    for q in pts:
        xy.append((q.x, q.y))
    cls += [k] * n; lit += [p.get("lit") or ""] * n; name += [p.get("name") or ""] * n; w += [L / n] * n
xy = np.array(xy); cls = np.array(cls); lit = np.array(lit); name = np.array(name, dtype=object); w = np.array(w)
P = shapely.points(xy)
print(f"samples {len(xy)} | km by class:", {c: round(w[cls == c].sum() / 1000, 1) for c in ("street", "sidewalk", "crossing", "path")})

# areas
zone = None
for z in load("city_zones.geojson"):
    if z["properties"]["name"].startswith("Complex Stud"):
        zone = shapely.transform(shape(z["geometry"]), lambda a: a * [KX, KY])
def bb(s, wst, n, e):
    return box(wst * KX, s * KY, e * KX, n * KY)
AREAS = {"zone polygon Complex Studentesc": zone, "compact bbox": bb(45.7432, 21.2248, 45.7512, 21.2440),
         "extended bbox": bb(45.7405, 21.2103, 45.7512, 21.2440), "whole city": None}
inarea = {k: (np.ones(len(xy), bool) if g is None else shapely.contains_xy(g, xy[:, 0], xy[:, 1])) for k, g in AREAS.items()}

# evidence points
lamps = load("mapillary_street_lights.geojson")
LXY = np.array([[f["geometry"]["coordinates"][0] * KX, f["geometry"]["coordinates"][1] * KY] for f in lamps])
LYR = np.array([int((f["properties"]["last_seen"] or "0000")[:4]) for f in lamps])
comp = load("sesizari_iluminat.geojson")
CXY = np.array([[f["geometry"]["coordinates"][0] * KX, f["geometry"]["coordinates"][1] * KY] for f in comp])
cst = np.array([f["properties"]["status"] for f in comp]); csub = np.array([f["properties"]["subcategory"] for f in comp])
cage = np.array([(NOW - dt.datetime.fromisoformat(f["properties"]["created_at"])).days for f in comp])
declined = np.char.startswith(cst.astype(str), "Declinat")
opened = np.isin(cst, ["In lucru", "Inregistrata", "Asteapta clarificari"])
area_outage = np.char.startswith(csub.astype(str), "Nu func")
red_trigger = opened & area_outage & (cage <= 30)


def nearest(pts_xy, maxd=80.0):
    d = np.full(len(xy), np.inf)
    if len(pts_xy) == 0:
        return d
    t = STRtree(shapely.points(pts_xy))
    idx, dist = t.query_nearest(P, max_distance=maxd, return_distance=True, all_matches=False)
    d[idx[0]] = dist
    return d


dL = nearest(LXY); dL22 = nearest(LXY[LYR >= 2022]); dC = nearest(CXY[~declined]); dR = nearest(CXY[red_trigger])

# indirect: same-name propagation (streets) and inheritance from the nearest street (non-street within 15 m)
isst = cls == "street"
names_yes = set(name[isst & (lit == "yes") & (name != "")])
prop = isst & (lit == "") & np.isin(name, list(names_yes))
st_idx = np.where(isst)[0]
t_st = STRtree(P[st_idx])
ns_idx = np.where(~isst)[0]
qi, qd = t_st.query_nearest(P[ns_idx], max_distance=15.0, return_distance=True, all_matches=False)
inherit = np.zeros(len(xy), bool)
src = st_idx[qi[1]]
inherit[ns_idx[qi[0]]] = (lit[src] == "yes") | prop[src]
near_street = np.zeros(len(xy), bool); near_street[ns_idx[qi[0]]] = True


def pct(mask, sel):
    s = w[sel].sum()
    return 0.0 if s == 0 else round(100 * w[sel & mask].sum() / s, 1)


def colours(rM, rC):
    A = lit == "yes"; M = dL <= rM; C = dC <= rC
    RED = (lit == "no") | (dR <= rC)
    nf = A.astype(int) + M.astype(int) + C.astype(int)
    green = ~RED & (nf >= 2)
    yellow = ~RED & ~green & ((nf == 1) | prop | inherit)
    gray = ~RED & ~green & ~yellow
    return green, yellow, RED, gray


print(f"\nlamps {len(LXY)} (last seen >=2022: {(LYR >= 2022).sum()}) | complaints {len(CXY)} | declined {declined.sum()} | open {opened.sum()} | red triggers (open area outage <=30 d) {red_trigger.sum()}")
for an, g in AREAS.items():
    if g is None:
        continue
    li = shapely.contains_xy(g, LXY[:, 0], LXY[:, 1]); ci = shapely.contains_xy(g, CXY[:, 0], CXY[:, 1])
    yrs = LYR[li]
    print(f"[{an}] lamps {li.sum()} (>=2024: {(yrs >= 2024).sum()}, 2020-23: {((yrs >= 2020) & (yrs < 2024)).sum()}, <=2019: {(yrs <= 2019).sum()}) | complaints {ci.sum()} status {dict(Counter(cst[ci]))} | red triggers {(ci & red_trigger).sum()}")

for an in AREAS:
    a = inarea[an]
    print(f"\n===== {an} =====")
    print("| class | km | lit yes | lit no | lamp<=10 | <=15 | <=20 | <=25 | <=35 | lamp22+<=25 | compl<=25 | <=35 | <=50 | name-prop / inherited |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for c in ("street", "sidewalk", "path"):
        s = a & (cls == c)
        row = [round(w[s].sum() / 1000, 1), pct(lit == "yes", s), pct(lit == "no", s)] + [pct(dL <= r, s) for r in (10, 15, 20, 25, 35)] + [pct(dL22 <= 25, s)] + [pct(dC <= r, s) for r in (25, 35, 50)] + [pct(prop | inherit, s)]
        print(f"| {c} | " + " | ".join(str(v) for v in row) + " |")
    for rM, rC in ((15, 30), (20, 35), (25, 50)):
        g_, y_, r_, n_ = colours(rM, rC)
        out = []
        for c in ("street", "sidewalk", "path"):
            s = a & (cls == c)
            out.append(f"{c}: green {pct(g_, s)} yellow {pct(y_, s)} red {pct(r_, s)} gray {pct(n_, s)}")
        s = a & np.isin(cls, ["street", "sidewalk"])
        out.append(f"street+sidewalk: green {pct(g_, s)} yellow {pct(y_, s)} red {pct(r_, s)} gray {pct(n_, s)}")
        print(f"rules lamp<={rM} m, complaint<={rC} m -> " + " | ".join(out))
    s = a & isst
    yes = s & (lit == "yes"); mis = s & (lit == "")
    print("calibration on streets: P(lamp<=r | lit=yes) r=10,15,20,25,35:", [pct(dL <= r, yes) for r in (10, 15, 20, 25, 35)],
          "| P(lamp<=r | lit missing):", [pct(dL <= r, mis) for r in (10, 15, 20, 25, 35)],
          "| P(compl<=r | lit=yes) r=25,35,50:", [pct(dC <= r, yes) for r in (25, 35, 50)])
    two = s & (dL <= 20) & (dC <= 35)
    print(f"hold-out: street km with lamp<=20 AND complaint<=35: {round(w[two].sum() / 1000, 2)} | of it lit=yes {pct(lit == 'yes', two)} lit=no {pct(lit == 'no', two)} untagged {pct(lit == '', two)}")

no = lit == "no"
print(f"\nlit=no anywhere in city (all classes): km {round(w[no].sum() / 1000, 2)} by class {({c: round(w[no & (cls == c)].sum() / 1000, 2) for c in ('street', 'sidewalk', 'crossing', 'path')})}")
print("P(lamp<=r | lit=no) r=10,15,25:", [pct(dL <= r, no) for r in (10, 15, 25)], "| P(complaint<=50 | lit=no):", pct(dC <= 50, no), "| lit=no within 15 m of a street:", pct(near_street, no))
print("lit values:", dict(Counter(lit[lit != ""])))

try:
    import osmnx as ox
    ox.settings.cache_folder = CACHE; ox.settings.use_cache = True; ox.settings.requests_timeout = 90
    ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["lit", "footway"]
    S, Wt, N, E = 45.7432, 21.2248, 45.7512, 21.2440
    flt = '["highway"~"^(primary|secondary|tertiary|unclassified|residential|living_street)(_link)?$"]'
    for label, kw in (("streets only", {"custom_filter": flt}), ("all walk/bike/drive", {"network_type": "all"})):
        G = ox.graph_from_bbox((Wt, S, E, N), simplify=True, retain_all=True, **kw)
        Gu = ox.convert.to_undirected(G)
        ed = [d for _, _, d in Gu.edges(data=True)]
        Ls = np.array([d["length"] for d in ed])
        print(f"\nosmnx {ox.__version__} compact bbox, {label}: segments {len(Ls)} | km {Ls.sum() / 1000:.1f} | p10/p50/p75/p90/p99 m {np.percentile(Ls, [10, 50, 75, 90, 99]).round(0).tolist()} | max {Ls.max():.0f} | <5 m: {(Ls < 5).sum()} | >200 m: {(Ls > 200).sum()} ({Ls[Ls > 200].sum() / 1000:.1f} km)"
              f" | osmid list: {sum(isinstance(d.get('osmid'), list) for d in ed)} | lit mixed: {sum(isinstance(d.get('lit'), list) for d in ed)} | name mixed: {sum(isinstance(d.get('name'), list) for d in ed)}")
except Exception as ex:
    print("\nosmnx segment check failed:", repr(ex)[:300])
