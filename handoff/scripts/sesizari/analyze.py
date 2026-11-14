"""Lighting-category analysis of the 12-month reports file. No free text is printed.
usage: python -I analyze.py <sesizari_12m.json> <out_geojson>
"""
import json, sys, math
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
path, out_geo = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)

AS_OF = datetime(2026, 11, 14, tzinfo=timezone.utc)
BBOX = dict(s=45.736, w=21.214, n=45.752, e=21.246)

print("TOTAL", len(data))
print("empty locatie", sum(1 for it in data if not it.get("locatie")))
print("unique id", len({it["id"] for it in data}), "unique webcon", len({it["webconInstanceNr"] for it in data}))
print("crs names", Counter((it["locatie"]["crs"]["type"], it["locatie"]["crs"]["properties"]["name"]) for it in data if it.get("locatie")))
xs = [it["locatie"]["coordinates"][0] for it in data if it.get("locatie")]
ys = [it["locatie"]["coordinates"][1] for it in data if it.get("locatie")]
print("coord[0] range", min(xs), max(xs), "coord[1] range", min(ys), max(ys))
sx, sy = sorted(xs), sorted(ys)
print("coord[0] p1/p50/p99", sx[len(sx)//100], sx[len(sx)//2], sx[len(sx)*99//100], "coord[1] p1/p50/p99", sy[len(sy)//100], sy[len(sy)//2], sy[len(sy)*99//100])

cat = Counter(it["categorii"]["nume"] for it in data)
print("\nCATEGORIES (%d)" % len(cat))
for k, c in cat.most_common():
    print("  %6d  %r" % (c, k))

light_names = [k for k in cat if "lumin" in k.lower()]
print("lighting-like category names:", light_names)
L = [it for it in data if it["categorii"]["nume"].strip() == "Iluminat public"]
TM = lambda it: 45.68 <= it["locatie"]["coordinates"][1] <= 45.83 and 21.10 <= it["locatie"]["coordinates"][0] <= 21.33
print("all reports with coords outside rough Timisoara box (45.68-45.83, 21.10-21.33):", sum(1 for it in data if it.get("locatie") and not TM(it)), "| lighting:", sum(1 for it in L if it.get("locatie") and not TM(it)))
print("names with leading/trailing whitespace: categories", [repr(k) for k in cat if k != k.strip()], "subcategories", sorted({repr(it["subcategorii"]["nume"]) for it in data if it["subcategorii"]["nume"] != it["subcategorii"]["nume"].strip()}), "statuses", sorted({repr(it["status"]) for it in data if it["status"] != it["status"].strip()}))
print("\nLIGHTING count", len(L))
Lc = [it for it in L if it.get("locatie")]
print("LIGHTING with coords", len(Lc), "without", len(L) - len(Lc))
print("status (all lighting):", Counter(it["status"] for it in L).most_common())
print("status (lighting with coords):", Counter(it["status"] for it in Lc).most_common())

# where do lighting sub-categories appear in other categories?
subs_all = defaultdict(Counter)
for it in data:
    subs_all[it["subcategorii"]["nume"]][it["categorii"]["nume"]] += 1

statuses = [s for s, _ in Counter(it["status"] for it in data).most_common()]
tab = defaultdict(Counter)
for it in L:
    tab[it["subcategorii"]["nume"]][it["status"]] += 1
print("\nSUBCATEGORY x STATUS (all lighting, incl. no-coords)")
print("| subcategorii.nume | " + " | ".join(statuses) + " | total |")
print("|---|" + "---|" * (len(statuses) + 1))
for sub, c in sorted(tab.items(), key=lambda kv: -sum(kv[1].values())):
    print("| %s | " % sub + " | ".join(str(c.get(s, 0)) for s in statuses) + " | %d |" % sum(c.values()))
print("repr of sub-category strings:", [repr(s) for s in tab])
print("sub-categories that look lighting-related in OTHER categories:")
for sub, cc in subs_all.items():
    if any(w in sub.lower() for w in ("ilumin", "lamp", "stalp", "stâlp", "bec", "lumin")):
        print("  ", repr(sub), dict(cc))


def parse(s):
    return datetime.fromisoformat(s)


def q(v, p):
    v = sorted(v)
    if not v:
        return None
    i = (len(v) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 1)


NONFINAL = ("In lucru", "Inregistrata", "Asteapta clarificari")
print("\nAGE OF NON-FINAL LIGHTING REPORTS as of 2026-11-14 (days)")


def agerow(label, items):
    ages = [(AS_OF - parse(it["createdAt"])).total_seconds() / 86400 for it in items]
    if not ages:
        print("| %s | 0 | | | | | | | | | | |" % label)
        return
    print("| %s | %d | %s | %s | %s | %s | %s | %s | %s | %d | %d | %d |" % (
        label, len(ages), round(min(ages), 1), q(ages, .1), q(ages, .25), q(ages, .5), q(ages, .75), q(ages, .9), round(max(ages), 1),
        sum(a > 30 for a in ages), sum(a > 90 for a in ages), sum(a > 180 for a in ages)))


print("| group | n | min | p10 | p25 | p50 | p75 | p90 | max | >30d | >90d | >180d |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
agerow("ALL non-final", [it for it in L if it["status"] in NONFINAL])
for st in NONFINAL:
    agerow("status=" + st, [it for it in L if it["status"] == st])
for sub in sorted(tab, key=lambda s: -sum(tab[s].values())):
    agerow("sub=" + sub + " (In lucru)", [it for it in L if it["status"] == "In lucru" and it["subcategorii"]["nume"] == sub])
    agerow("sub=" + sub + " (all non-final)", [it for it in L if it["status"] in NONFINAL and it["subcategorii"]["nume"] == sub])

# share of status by creation month (shows whether "In lucru" piles up in old months)
print("\nLIGHTING by creation month x status")
mon = defaultdict(Counter)
for it in L:
    mon[it["createdAt"][:7]][it["status"]] += 1
print("| month | " + " | ".join(statuses) + " | total | nonfinal% |")
print("|---|" + "---|" * (len(statuses) + 2))
for m in sorted(mon):
    c = mon[m]
    t = sum(c.values())
    nf = sum(c.get(s, 0) for s in NONFINAL)
    print("| %s | " % m + " | ".join(str(c.get(s, 0)) for s in statuses) + " | %d | %.0f%% |" % (t, 100 * nf / t))


def hav(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    R = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def clusters(items, dist_m, days):
    pts = [(it["locatie"]["coordinates"], parse(it["createdAt"])) for it in items]
    cell = 0.0005  # ~39 m in lon, ~56 m in lat at 45.75N; both > 30 m... check neighbours +-2 for larger radii
    reach = max(1, int(math.ceil(dist_m / 38.0)))
    grid = defaultdict(list)
    for i, (c, t) in enumerate(pts):
        grid[(int(c[0] // cell), int(c[1] // cell))].append(i)
    parent = list(range(len(pts)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    has = [False] * len(pts)
    has_space_only = [False] * len(pts)
    exact_dup = [False] * len(pts)
    for i, (c, t) in enumerate(pts):
        gx, gy = int(c[0] // cell), int(c[1] // cell)
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j <= i:
                        continue
                    d = hav(c, pts[j][0])
                    if d <= dist_m:
                        has_space_only[i] = has_space_only[j] = True
                        if abs((t - pts[j][1]).total_seconds()) <= days * 86400:
                            has[i] = has[j] = True
                            parent[find(i)] = find(j)
                            if d == 0:
                                exact_dup[i] = exact_dup[j] = True
    comp = Counter(find(i) for i in range(len(pts)))
    sizes = Counter(comp.values())
    return dict(n=len(pts), with_neighbour=sum(has), share=round(100 * sum(has) / len(pts), 1),
                with_neighbour_any_time=sum(has_space_only),
                identical_coords_within_window=sum(exact_dup),
                components=len(comp), multi_components=sum(1 for v in comp.values() if v > 1),
                size_hist=sorted(sizes.items()))


print("\nCLUSTERING (lighting with coords)")
for d, dd in ((30, 14), (30, 30), (50, 14), (15, 14), (30, 3)):
    print("dist<=%dm, dt<=%dd:" % (d, dd), clusters(Lc, d, dd))
print("duplicate exact coordinates among lighting (any time):", sum(c for c in Counter(tuple(it["locatie"]["coordinates"]) for it in Lc).values() if c > 1))
# coordinate precision
print("decimal places lon:", Counter(len(repr(it["locatie"]["coordinates"][0]).split(".")[1]) for it in Lc).most_common(6))


def inbox(it):
    lon, lat = it["locatie"]["coordinates"]
    return BBOX["s"] <= lat <= BBOX["n"] and BBOX["w"] <= lon <= BBOX["e"]


M = [it for it in Lc if inbox(it)]
print("\nMODEL AREA lighting count", len(M), "| all-category reports with coords in bbox", sum(1 for it in data if it.get("locatie") and inbox(it)))
mt = defaultdict(Counter)
for it in M:
    mt[it["subcategorii"]["nume"]][it["status"]] += 1
print("| subcategorii.nume | " + " | ".join(statuses) + " | total |")
print("|---|" + "---|" * (len(statuses) + 1))
for sub, c in sorted(mt.items(), key=lambda kv: -sum(kv[1].values())):
    print("| %s | " % sub + " | ".join(str(c.get(s, 0)) for s in statuses) + " | %d |" % sum(c.values()))
print("| TOTAL | " + " | ".join(str(sum(1 for it in M if it["status"] == s)) for s in statuses) + " | %d |" % len(M))
print("model-area non-final age:")
agerow("model area non-final", [it for it in M if it["status"] in NONFINAL])
print("model-area clustering 30m/14d:", clusters(M, 30, 14) if M else None)

feats = [{"type": "Feature",
          "properties": {"webconInstanceNr": it["webconInstanceNr"], "createdAt": it["createdAt"],
                         "subcategorie": it["subcategorii"]["nume"], "status": it["status"]},
          "geometry": {"type": "Point", "coordinates": it["locatie"]["coordinates"]}} for it in Lc]
with open(out_geo, "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
print("\nGEOJSON written", out_geo, "features", len(feats))

print("\nCARD CANDIDATES in model bbox (number, status, sub, createdAt, lon, lat)")
seen = Counter()
for it in sorted(M, key=lambda x: x["createdAt"], reverse=True):
    if seen[it["status"]] < 3:
        seen[it["status"]] += 1
        print(it["webconInstanceNr"], "|", it["status"], "|", it["subcategorii"]["nume"], "|", it["createdAt"], "|", it["locatie"]["coordinates"])
