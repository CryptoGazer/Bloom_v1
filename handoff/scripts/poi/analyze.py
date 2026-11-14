import json, sys, math, os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import opening_hours as oh

D = sys.argv[1]
S, Wst, N, E = 45.736, 21.214, 45.752, 21.246
AMEN = {"bar","pub","restaurant","cafe","fast_food","nightclub","biergarten","pharmacy","fuel","cinema","theatre","casino","bank","atm","library","university","college"}
TOUR = {"hotel","hostel","guest_house"}

def load(n):
    p = os.path.join(D, n)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def pt(e):
    if e["type"] == "node":
        return e.get("lat"), e.get("lon")
    c = e.get("center")
    return (c["lat"], c["lon"]) if c else (None, None)

def vtype(t):
    if t.get("amenity") in AMEN: return "amenity=" + t["amenity"]
    if "shop" in t: return "shop=*"
    if t.get("tourism") in TOUR: return "tourism=" + t["tourism"]
    return None

def inb(la, lo):
    return la is not None and S <= la <= N and Wst <= lo <= E

T_TUE = datetime(2026, 11, 10, 22, 30)
T_FRI = datetime(2026, 11, 13, 22, 30)
T_SAT = datetime(2026, 11, 14, 0, 30)

def evalh(s):
    try:
        h = oh.OpeningHours(s)
    except Exception:
        return None
    try:
        r = {"tue": h.is_open(T_TUE), "fri": h.is_open(T_FRI), "sat": h.is_open(T_SAT)}
        t = datetime(2026, 11, 9, 0, 15); a = True
        for i in range(7 * 48):
            if not h.is_open(t + timedelta(minutes=30 * i)):
                a = False; break
        r["247"] = a
        return r
    except Exception:
        return None

def venues(doc, bbox_filter):
    out = []; excl = 0
    for e in doc["elements"]:
        if e["type"] == "relation" and e.get("tags", {}).get("boundary") == "administrative":
            continue
        t = e.get("tags", {})
        vt = vtype(t)
        if not vt: continue
        la, lo = pt(e)
        if bbox_filter and not inb(la, lo):
            excl += 1; continue
        out.append((vt, t, la, lo, e["type"]))
    return out, excl

def table(vs, title):
    c = Counter(); co = Counter()
    for vt, t, *_ in vs:
        c[vt] += 1
        if t.get("opening_hours"): co[vt] += 1
    print("##", title)
    print("| type | count | with opening_hours | share |")
    print("|---|---|---|---|")
    for k, n in sorted(c.items(), key=lambda x: -x[1]):
        print(f"| {k} | {n} | {co[k]} | {co[k]/n*100:.0f}% |")
    tn, to = sum(c.values()), sum(co.values())
    print(f"| TOTAL | {tn} | {to} | {to/tn*100:.1f}% |")
    return tn, to

def parse_stats(vs, title):
    print("##", title, "- opening_hours parsing")
    res = []; unp = []
    cnt = defaultdict(Counter)
    for v in vs:
        vt, t = v[0], v[1]
        s = t.get("opening_hours")
        if not s:
            res.append(None); continue
        r = evalh(s)
        res.append(r)
        if r is None:
            unp.append(s); cnt[vt]["unparsed"] += 1; continue
        cnt[vt]["parsed"] += 1
        for k in ("247", "tue", "fri", "sat"):
            if r[k]: cnt[vt][k] += 1
    nstr = sum(1 for v in vs if v[1].get("opening_hours"))
    print(f"strings: {nstr}, unparsable: {len(unp)} ({(len(unp)/nstr*100 if nstr else 0):.1f}%)")
    for u in unp[:25]: print("   UNPARSED:", repr(u))
    print("| type | parsed | 24/7 | open Tue 22:30 | open Fri 22:30 | open Sat 00:30 |")
    print("|---|---|---|---|---|---|")
    tot = Counter()
    for k, c in sorted(cnt.items(), key=lambda x: -x[1]["parsed"]):
        print(f"| {k} | {c['parsed']} | {c['247']} | {c['tue']} | {c['fri']} | {c['sat']} |")
        tot.update(c)
    print(f"| TOTAL | {tot['parsed']} | {tot['247']} | {tot['tue']} | {tot['fri']} | {tot['sat']} |")
    return res

def bias(vs, title):
    print("##", title, "- bias checks")
    def sh(sel, label):
        a = [v for v in vs if sel(v)]
        b = [v for v in a if v[1].get("opening_hours")]
        print(f"{label}: {len(b)}/{len(a)}" + (f" = {len(b)/len(a)*100:.0f}%" if a else ""))
    sh(lambda v: "brand" in v[1] or "brand:wikidata" in v[1], "with brand tag")
    sh(lambda v: not ("brand" in v[1] or "brand:wikidata" in v[1]), "without brand tag")
    night = {"amenity=bar", "amenity=pub", "amenity=nightclub", "amenity=restaurant", "amenity=cafe", "amenity=fast_food", "amenity=biergarten"}
    sh(lambda v: v[0] in night, "food/drink/nightlife (bar,pub,nightclub,restaurant,cafe,fast_food,biergarten)")
    sh(lambda v: v[0] in night and not ("brand" in v[1] or "brand:wikidata" in v[1]), "food/drink/nightlife without brand")
    sh(lambda v: v[0] == "shop=*", "shops")
    sc = Counter(v[1]["shop"] for v in vs if v[0] == "shop=*")
    print("top shop values:", sc.most_common(12))
    # brands among those with opening_hours
    bc = Counter(v[1].get("brand") or v[1].get("name") for v in vs if v[1].get("opening_hours"))
    print("most frequent brand/name among elements WITH opening_hours:", bc.most_common(15))
    nm = sum(1 for v in vs if "name" not in v[1] and "brand" not in v[1])
    print("venues without name and brand:", nm)
    print("element types:", Counter(v[4] for v in vs))

bv = load("bbox_venues.json")
print("bbox_venues osm_base:", bv["osm3s"].get("timestamp_osm_base"), "elements:", len(bv["elements"]))
vs, excl = venues(bv, True)
print("venues with centre outside bbox excluded:", excl)
area = (N - S) * 111.32 * (E - Wst) * 111.32 * math.cos(math.radians((S + N) / 2))
print(f"bbox area km2: {area:.2f}")
tn, to = table(vs, "BBOX venues")
res = parse_stats(vs, "BBOX")
bias(vs, "BBOX")
late = [(v[2], v[3]) for v, r in zip(vs, res) if r and r["fri"]]
late_tue = [(v[2], v[3]) for v, r in zip(vs, res) if r and r["tue"]]
late_sat = [(v[2], v[3]) for v, r in zip(vs, res) if r and r["sat"]]
print(f"late Fri 22:30 venues: {len(late)} -> {len(late)/area:.2f} per km2; Tue: {len(late_tue)} -> {len(late_tue)/area:.2f}; Sat 00:30: {len(late_sat)} -> {len(late_sat)/area:.2f}; all venues {tn/area:.1f} per km2")
print("late Fri venues list:")
for v, r in zip(vs, res):
    if r and r["fri"]:
        print("  ", v[0], "|", v[1].get("name") or v[1].get("brand") or v[1].get("operator"), "|", v[1]["opening_hours"], "|", round(v[2], 5), round(v[3], 5))

cv = load("city_venues.json")
if cv:
    print("city_venues osm_base:", cv["osm3s"].get("timestamp_osm_base"))
    for e in cv["elements"]:
        if e["type"] == "relation" and e.get("tags", {}).get("boundary") == "administrative":
            print("city boundary relation:", e["id"], {k: e["tags"].get(k) for k in ("name", "admin_level", "population", "place")})
    cvs, _ = venues(cv, False)
    table(cvs, "CITY venues")
    parse_stats(cvs, "CITY")
    bias(cvs, "CITY")
else:
    print("city_venues.json MISSING")

# streets
st = load("bbox_streets.json")
if st:
    print("bbox_streets osm_base:", st["osm3s"].get("timestamp_osm_base"), "ways:", len(st["elements"]))
    lat0 = (S + N) / 2; kx = 111320 * math.cos(math.radians(lat0)); ky = 111320
    def xy(la, lo): return ((lo - Wst) * kx, (la - S) * ky)
    def grid(pts, cell=50):
        g = defaultdict(list)
        for la, lo in pts:
            x, y = xy(la, lo); g[(int(x // cell), int(y // cell))].append((x, y))
        return g
    def near(g, x, y, r, cell=50):
        cx, cy = int(x // cell), int(y // cell)
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for px, py in g.get((i, j), ()):
                    if (px - x) ** 2 + (py - y) ** 2 <= r * r: return True
        return False
    g_all = grid([(v[2], v[3]) for v in vs]); g_fri = grid(late); g_tue = grid(late_tue); g_sat = grid(late_sat)
    g_any_oh = grid([(v[2], v[3]) for v in vs if v[1].get("opening_hours")])
    tot = 0; acc = Counter(); byclass = Counter(); litlen = Counter()
    for w in st["elements"]:
        geom = w.get("geometry") or []
        hw = w["tags"]["highway"]; lit = w["tags"].get("lit", "(no lit tag)")
        for a, b in zip(geom, geom[1:]):
            x1, y1 = xy(a["lat"], a["lon"]); x2, y2 = xy(b["lat"], b["lon"])
            L = math.hypot(x2 - x1, y2 - y1)
            n = max(1, int(math.ceil(L / 5)))
            for i in range(n):
                f = (i + 0.5) / n
                x, y = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
                if not (0 <= x <= (E - Wst) * kx and 0 <= y <= (N - S) * ky): continue
                d = L / n; tot += d; byclass[hw] += d; litlen[lit] += d
                if near(g_all, x, y, 30): acc["any30"] += d
                if near(g_all, x, y, 50): acc["any50"] += d
                if near(g_any_oh, x, y, 30): acc["oh30"] += d
                if near(g_fri, x, y, 30): acc["fri30"] += d
                if near(g_fri, x, y, 50): acc["fri50"] += d
                if near(g_fri, x, y, 100): acc["fri100"] += d
                if near(g_tue, x, y, 30): acc["tue30"] += d
                if near(g_tue, x, y, 50): acc["tue50"] += d
                if near(g_sat, x, y, 50): acc["sat50"] += d
    print(f"street length in bbox km: {tot/1000:.2f}")
    print("by class km:", {k: round(v / 1000, 2) for k, v in byclass.most_common()})
    print("street length by lit value km (share):", {k: (round(v / 1000, 2), f"{v/tot*100:.1f}%") for k, v in litlen.most_common()})
    for k in ("any30", "any50", "oh30", "fri30", "fri50", "fri100", "tue30", "tue50", "sat50"):
        print(f"share {k}: {acc[k]/tot*100:.1f}% ({acc[k]/1000:.2f} km)")
else:
    print("bbox_streets.json MISSING")

def lighting(doc, title, bbox_filter):
    print("##", title, "lighting tags; osm_base", doc["osm3s"].get("timestamp_osm_base"))
    lamps = 0; waylit = Counter(); waylit_hw = Counter(); stops = defaultdict(Counter); parks = defaultdict(Counter)
    extra = defaultdict(Counter); lamp_extra = Counter()
    for e in doc["elements"]:
        t = e.get("tags", {})
        if e["type"] == "relation" and t.get("boundary") == "administrative": continue
        la, lo = pt(e)
        if bbox_filter and not inb(la, lo): continue
        if e["type"] == "node" and t.get("highway") == "street_lamp":
            lamps += 1
            for k in t:
                if k != "highway": lamp_extra[k] += 1
        if e["type"] == "way" and "lit" in t:
            waylit[t["lit"]] += 1
            waylit_hw[(t.get("highway") or ("leisure=" + t["leisure"] if "leisure" in t else "other"), t["lit"])] += 1
        for key, val, lab in (("highway", "bus_stop", "highway=bus_stop"), ("railway", "tram_stop", "railway=tram_stop"), ("public_transport", "platform", "public_transport=platform")):
            if t.get(key) == val: stops[lab][t.get("lit", "(none)")] += 1
        if t.get("leisure") in ("park", "pitch"): parks["leisure=" + t["leisure"]][t.get("lit", "(none)")] += 1
        for k in ("light_source", "lamp_type", "lamp_mount", "light:count", "light:method"):
            if k in t: extra[k][t[k]] += 1
    print("highway=street_lamp nodes:", lamps, "| other keys on lamps:", dict(lamp_extra.most_common(10)))
    print("ways with lit=* by value:", dict(waylit.most_common()), "total", sum(waylit.values()))
    print("ways with lit by (highway, value):", {f"{a}/{b}": n for (a, b), n in waylit_hw.most_common(30)})
    for k, c in stops.items(): print(k, "lit:", dict(c), "total", sum(c.values()))
    for k, c in parks.items(): print(k, "lit:", dict(c), "total", sum(c.values()))
    print("light_source/lamp_type/lamp_mount/light:* usage:", {k: dict(c) for k, c in extra.items()} or "none")

for n, ttl, bf in (("bbox_lit.json", "BBOX", True), ("city_lit.json", "CITY", False)):
    d = load(n)
    if d: lighting(d, ttl, bf)
    else: print(n, "MISSING")
