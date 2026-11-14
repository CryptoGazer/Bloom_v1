"""Throwaway draft map (NOT project code): applies the spec rules to the model area and writes one HTML file.
usage: python -I draft_map.py <unihack-data dir> <osmnx cache dir> <out html>"""
import json, os, sys, math, datetime as dt, unicodedata
from collections import defaultdict
import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.strtree import STRtree
import osmnx as ox

sys.stdout.reconfigure(encoding="utf-8")
D, CACHE, OUT = sys.argv[1:4]
AS_OF = dt.date(2026, 11, 14)
# Model area [south, west, north, east]; LIGHTMAP_BBOX="s,w,n,e" maps another or a bigger area.
S, W, N, E = (float(x) for x in os.environ.get("LIGHTMAP_BBOX", "45.7405,21.2103,45.7512,21.2440").split(","))
LAMP_R, COMPL_R, INHERIT_R, COVER_MIN, FRESH, LAMPS_DARK = 20.0, 30.0, 15.0, 0.5, 30, 3
KX, KY = 77811.0, 111147.0  # metres per degree at lat 45.748 (draft-grade projection)


def xy(lon, lat):
    return (lon * KX, lat * KY)


def load(n):
    return json.load(open(f"{D}/geojson/{n}", encoding="utf-8"))["features"]


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).casefold().replace(".", " ").split())


def aslist(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


STREET = {"trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}
STREET |= {s + "_link" for s in ("trunk", "primary", "secondary", "tertiary")}
YES = {"yes", "24/7", "automatic", "limited", "interval", "sunset-sunrise", "dusk-dawn"}


def kind_of(d):
    hw = set(aslist(d.get("highway"))); fw = set(aslist(d.get("footway")))
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
    y, n = vals & YES, vals & {"no"}
    return "mixed" if (y and n) else ("yes" if y else ("no" if n else None))


# ---- graph -> segments
ox.settings.cache_folder = CACHE; ox.settings.use_cache = True; ox.settings.requests_timeout = 120
ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["lit", "footway", "foot", "bicycle"]
G = ox.graph_from_bbox((W, S, E, N), network_type="all_public", simplify=True, retain_all=True, truncate_by_edge=True)
Gu = ox.convert.to_undirected(G)
segs = []
for u, v, k, d in Gu.edges(keys=True, data=True):
    g = d.get("geometry")
    if g is None:
        g = LineString([(Gu.nodes[u]["x"], Gu.nodes[u]["y"]), (Gu.nodes[v]["x"], Gu.nodes[v]["y"])])
    lm = LineString([xy(x, y) for x, y in g.coords])
    a, b = (u, v) if u < v else (v, u)
    nm = d.get("name"); nm = nm[0] if isinstance(nm, list) else nm
    segs.append(dict(id=f"{a}-{b}-{k}", ll=[[round(x, 6), round(y, 6)] for x, y in g.coords], lm=lm, kind=kind_of(d),
                     name=nm if isinstance(nm, str) else None, ways=[int(x) for x in aslist(d.get("osmid"))],
                     L=lm.length, lit=osm_lit(d), ind=[]))
lines = np.array([s["lm"] for s in segs], dtype=object)
print(f"osmnx {ox.__version__}: segments {len(segs)}, ids unique: {len({s['id'] for s in segs}) == len(segs)}")

# ---- lamps: coverage share per segment + lamps near each segment
PAD = 0.001
inbox = lambda lon, lat: (W - PAD <= lon <= E + PAD) and (S - PAD <= lat <= N + PAD)
lamps = [f for f in load("mapillary_street_lights.geojson") if inbox(*f["geometry"]["coordinates"])]
lamp_pts = shapely.points(np.array([xy(*f["geometry"]["coordinates"]) for f in lamps]))
lamp_yr = [int((f["properties"]["last_seen"] or "0000")[:4]) for f in lamps]
tl = STRtree(lamp_pts)
pts, owner = [], []
for i, s in enumerate(segs):
    n = max(1, round(s["L"] / 10))
    pts.extend(shapely.line_interpolate_point(s["lm"], (np.arange(n) + 0.5) * s["L"] / n)); owner.extend([i] * n)
pts = np.array(pts, dtype=object); owner = np.array(owner)
hit = np.zeros(len(pts)); hit[tl.query_nearest(pts, max_distance=LAMP_R, all_matches=False)[0]] = 1
cov = np.bincount(owner, weights=hit, minlength=len(segs)) / np.bincount(owner, minlength=len(segs))
near = defaultdict(list)
for si, li in zip(*tl.query(lines, predicate="dwithin", distance=LAMP_R)):
    near[si].append(li)

# ---- complaints -> events (30 m / 14 days from the first report) -> nearest street within 30 m
CLOSED = {"Finalizata", "Rezolvata"}
LAMP_SUBS = {fold("Bec nefuncțional"), fold("Aparat de iluminat nefuncțional")}
comps = []
for f in load("sesizari_iluminat.geojson"):
    lon, lat = f["geometry"]["coordinates"]
    if not inbox(lon, lat):
        continue
    p = f["properties"]
    comps.append(dict(xy=xy(lon, lat), ll=[round(lon, 6), round(lat, 6)], nr=p["nr"], sub=(p["subcategory"] or "").strip(),
                      st=(p["status"] or "").strip(), created=dt.datetime.fromisoformat(p["created_at"]).date(),
                      closed=(p.get("closed_at") or "")[:10] or None))
comps.sort(key=lambda c: c["created"])
events = []
for c in comps:
    for ev in events:
        f0 = ev["m"][0]
        if (c["created"] - f0["created"]).days <= 14 and math.dist(c["xy"], f0["xy"]) <= 30:
            ev["m"].append(c); break
    else:
        events.append({"m": [c]})
for ev in events:
    m = ev["m"]
    nondecl = [c for c in m if not c["st"].startswith("Declinat")]
    opened = [c for c in nondecl if c["st"] not in CLOSED]
    ev["age"] = None
    if not nondecl:
        ev["kind"] = "declined"
    elif opened:
        subs = {fold(c["sub"]) for c in opened}
        ev["kind"] = "open_area_outage" if any(x.startswith("nu functioneaza iluminatul") for x in subs) else ("open_lamp_out" if subs & LAMP_SUBS else "open_other")
        ev["age"] = (AS_OF - max(c["created"] for c in opened)).days
    else:
        ev["kind"] = "fixed"
    closed = [c["closed"] for c in m if c["closed"]]
    ev["closed"] = max(closed) if closed and ev["kind"] == "fixed" else None
st_idx = np.array([i for i, s in enumerate(segs) if s["kind"] == "street"])
t_st, t_all = STRtree(lines[st_idx]), STRtree(lines)
seg_events, attached = defaultdict(list), {}
if events:
    ev_pts = shapely.points(np.array([ev["m"][0]["xy"] for ev in events]))
    (ei, si), dist = t_st.query_nearest(ev_pts, max_distance=COMPL_R, return_distance=True, all_matches=False)
    for e, s_, dd in zip(ei, si, dist):
        attached[int(e)] = (int(st_idx[s_]), float(dd))
    rest = [e for e in range(len(events)) if e not in attached]
    if rest:
        (ei, si), dist = t_all.query_nearest(ev_pts[rest], max_distance=COMPL_R, return_distance=True, all_matches=False)
        for e, s_, dd in zip(ei, si, dist):
            attached[rest[int(e)]] = (int(s_), float(dd))
    for e, (s_, dd) in attached.items():
        seg_events[s_].append((events[e], dd))

# ---- facts, indirect flags, status
for i, s in enumerate(segs):
    evs = seg_events.get(i, [])
    s["fam"] = (["osm"] if s["lit"] == "yes" else []) + (["mapillary"] if cov[i] >= COVER_MIN else []) + (["sesizari"] if any(ev["kind"] != "declined" for ev, _ in evs) else [])
    s["fresh_lamps"] = sum(ev["kind"] == "open_lamp_out" and ev["age"] <= FRESH for ev, _ in evs)
    s["dark_compl"] = any(ev["kind"] == "open_area_outage" and ev["age"] <= FRESH for ev, _ in evs) or s["fresh_lamps"] >= LAMPS_DARK
    if 0 < cov[i] < COVER_MIN:
        s["ind"].append("partial_lamps")
names_yes = {fold(s["name"]) for s in segs if s["kind"] == "street" and s["lit"] == "yes" and s["name"]}
for s in segs:
    if s["kind"] == "street" and s["lit"] is None and s["name"] and fold(s["name"]) in names_yes:
        s["ind"].append("same_name")
ns = [i for i, s in enumerate(segs) if s["kind"] != "street"]
mids = np.array([segs[i]["lm"].interpolate(0.5, normalized=True) for i in ns], dtype=object)
for a_, b_ in zip(*t_st.query_nearest(mids, max_distance=INHERIT_R, all_matches=False)):
    me, st = segs[ns[a_]], segs[st_idx[b_]]
    me["near"] = st["id"]
    if st["fam"] or "same_name" in st["ind"]:
        me["ind"].append("near_lit_street")
    if st["dark_compl"]:
        me["inh_dark"] = True
for s in segs:
    if s["lit"] == "no" or s["dark_compl"] or s.get("inh_dark"):
        s["status"] = "dark_reported"
    elif ({"osm", "mapillary"} & set(s["fam"])) and s["fresh_lamps"] == 0:  # one direct source is enough (rule softened 2026-11-14)
        s["status"] = "lit_confirmed"
    elif s["fam"] or s["ind"]:
        s["status"] = "lit_likely"
    else:
        s["status"] = "unknown"

# ---- summary and checks
STAT = ["lit_confirmed", "lit_likely", "dark_reported", "unknown"]
GROUPS = {"streets": {"street"}, "sidewalks": {"sidewalk", "crossing"}, "streets_and_sidewalks": {"street", "sidewalk", "crossing"}, "paths": {"path"}, "service": {"service"}}
summary = {"as_of": str(AS_OF), "segments": len(segs), "lamps_in_area": len(lamps), "complaints_in_area": len(comps), "events": len(events), "events_unattached": len(events) - len(attached), "groups": {}}
for gname, kinds in GROUPS.items():
    sel = [s for s in segs if s["kind"] in kinds]
    tot = sum(s["L"] for s in sel) or 1.0
    summary["groups"][gname] = {"km": round(tot / 1000, 1), "n": len(sel), **{st: round(100 * sum(s["L"] for s in sel if s["status"] == st) / tot, 1) for st in STAT}}
yes_st = [(s, i) for i, s in enumerate(segs) if s["kind"] == "street" and s["lit"] == "yes"]
recall = sum(s["L"] for s, i in yes_st if "mapillary" in s["fam"]) / (sum(s["L"] for s, i in yes_st) or 1.0)
summary["checks"] = {"unknown_share_streets_sidewalks": summary["groups"]["streets_and_sidewalks"]["unknown"], "unknown_ok": summary["groups"]["streets_and_sidewalks"]["unknown"] <= 33.33,
                     "lit_no_but_confirmed": sum(1 for s in segs if s["lit"] == "no" and s["status"] == "lit_confirmed"), "lamp_recall_on_lit_yes": round(100 * recall, 1), "lamp_recall_ok": recall >= 0.5}
summary["event_kinds"] = {k: sum(1 for ev in events if ev["kind"] == k) for k in ("fixed", "open_area_outage", "open_lamp_out", "open_other", "declined")}
summary["dark_segments"] = {"lit_no": sum(1 for s in segs if s["lit"] == "no"), "by_complaints": sum(1 for s in segs if s["dark_compl"]), "inherited": sum(1 for s in segs if s.get("inh_dark"))}
print(json.dumps(summary, ensure_ascii=False, indent=1))

# ---- HTML
feats = []
for i, s in enumerate(segs):
    ev = []
    if s["lit"]:
        ev.append({"s": "osm", "k": s["lit"], "ways": s["ways"][:4]})
    if near.get(i):
        yrs = [lamp_yr[j] for j in near[i]]
        ev.append({"s": "mapillary", "n": len(near[i]), "near": round(float(min(shapely.distance(s["lm"], lamp_pts[j]) for j in near[i])), 1), "y0": min(yrs), "y1": max(yrs), "cov": round(float(cov[i]), 2)})
    for e, dd in seg_events.get(i, []):
        f0 = e["m"][0]
        ev.append({"s": "sesizari", "k": e["kind"], "nr": f0["nr"], "n": len(e["m"]), "sub": f0["sub"], "created": str(f0["created"]), "closed": e["closed"], "age": e["age"], "d": round(dd)})
    for flag in s["ind"]:
        ev.append({"s": "derived", "k": flag, "ref": s["name"] if flag == "same_name" else s.get("near")})
    if s.get("inh_dark"):
        ev.append({"s": "derived", "k": "inherited_dark", "ref": s.get("near")})
    feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": s["ll"]},
                  "properties": {"id": s["id"], "kind": s["kind"], "name": s["name"], "len": round(s["L"], 1), "status": s["status"], "conf": len(s["fam"]), "ev": ev}})
lamp_out = [[round(f["geometry"]["coordinates"][0], 6), round(f["geometry"]["coordinates"][1], 6), y] for f, y in zip(lamps, lamp_yr)]
ev_out = [{"ll": e["m"][0]["ll"], "k": e["kind"], "nr": e["m"][0]["nr"], "n": len(e["m"]), "sub": e["m"][0]["sub"], "created": str(e["m"][0]["created"]), "closed": e["closed"], "age": e["age"], "att": i in attached} for i, e in enumerate(events)]
dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = open(__file__.replace("draft_map.py", "draft_map_template.html"), encoding="utf-8").read()
html = html.replace("__DATA__", dump({"type": "FeatureCollection", "features": feats})).replace("__SUMMARY__", dump(summary)).replace("__LAMPS__", dump(lamp_out)).replace("__EVENTS__", dump(ev_out)).replace("__BBOX__", dump([S, W, N, E]))
open(OUT, "w", encoding="utf-8", newline="\n").write(html)
print("written", OUT, round(len(html) / 1e6, 2), "MB")
