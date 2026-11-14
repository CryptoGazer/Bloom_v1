"""Card shape + proximity-search behaviour. Prints structure, street strings, statuses, dates only.
usage: python -I cards_prox.py <list_12m.json> <prox.json> <card1.json> [...]
"""
import json, sys, math
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
lst = json.load(open(sys.argv[1], encoding="utf-8"))
prox = json.load(open(sys.argv[2], encoding="utf-8"))
by_nr = {it["webconInstanceNr"]: it for it in lst}
SAFE = {"strada", "nrStrada", "status", "createdAt", "webconInstanceNr", "id"}


def shape(v, depth=0):
    if isinstance(v, dict):
        return {k: shape(x, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        return ["len=%d" % len(v)] + ([shape(v[0], depth + 1)] if v else [])
    return type(v).__name__


for p in sys.argv[3:]:
    c = json.load(open(p, encoding="utf-8"))
    print("\nCARD", p.replace("\\", "/").split("/")[-1], "top type", type(c).__name__)
    if not isinstance(c, dict):
        continue
    print(" keys:", list(c.keys()))
    sh = shape(c)
    print(" shape:", json.dumps(sh, ensure_ascii=False))
    li = by_nr.get(c.get("webconInstanceNr"))
    if li:
        print(" keys added vs list item:", sorted(set(c) - set(li)), "| missing vs list:", sorted(set(li) - set(c)))
        print(" list status:", li["status"], "| card status:", c.get("status"), "| createdAt equal:", li["createdAt"] == c.get("createdAt"))
    for k in ("strada", "nrStrada", "status", "createdAt"):
        print("  %s = %r" % (k, c.get(k)))
    for k, v in c.items():
        if k in ("categorii", "subcategorii"):
            print("  %s = %r" % (k, v))
    h = c.get("history")
    if isinstance(h, list):
        print("  history len", len(h))
        for e in h:
            if isinstance(e, dict):
                # print keys and only date/status-like values
                print("   ", {k: (v if k.lower() in ("date", "status", "data", "createdat") else type(v).__name__) for k, v in e.items()})
            else:
                print("   ", type(e).__name__)

print("\nPROXIMITY: type", type(prox).__name__, "len", len(prox) if hasattr(prox, "__len__") else "")
if isinstance(prox, dict):
    print(" keys", list(prox.keys()))
    sys.exit(0)
print(" item keys:", Counter(tuple(it.keys()) for it in prox).most_common(3))
extra = [k for k in prox[0] if k not in ("descriere", "files")]
print(" shape of first item (non-text):", json.dumps({k: shape(prox[0][k]) for k in extra}, ensure_ascii=False))
C = (21.2330, 45.7472)


def hav(a, b):
    R = 6371008.8
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


d = [hav(C, it["locatie"]["coordinates"]) if it.get("locatie") else None for it in prox]
dates = [it["createdAt"] for it in prox]
print(" distances (m):", [None if x is None else round(x) for x in d])
dd = [x for x in d if x is not None]
print(" sorted by distance asc:", dd == sorted(dd), "| desc:", dd == sorted(dd, reverse=True))
print(" createdAt sorted asc:", dates == sorted(dates), "| desc:", dates == sorted(dates, reverse=True))
print(" createdAt first/last:", dates[0], dates[-1], "| min/max:", min(dates), max(dates))
print(" distance field present in item?:", [k for k in prox[0] if "dist" in k.lower()])
for k in prox[0]:
    if "dist" in k.lower():
        vals = [it[k] for it in prox]
        print("  ", k, "first/last", vals[0], vals[-1], "sorted asc", vals == sorted(vals))
print(" categories in result:", Counter(it["categorii"]["nume"] for it in prox).most_common())
print(" statuses in result:", Counter(it["status"] for it in prox).most_common())
# ground truth from the full list
full = [it for it in lst if it.get("locatie") and hav(C, it["locatie"]["coordinates"]) <= 1000]
fullL = [it for it in full if it["categorii"]["nume"].strip() == "Iluminat public"]
print(" full-list reports within 1000 m of the point:", len(full), "| lighting among them:", len(fullL))
print(" lighting in proximity result:", sum(1 for it in prox if it["categorii"]["nume"].strip() == "Iluminat public"))
ids = {it["id"] for it in prox}
print(" all proximity ids present in full list:", ids <= {it["id"] for it in lst})
# rank of returned items in full list ordered by distance / by date
fd = sorted(full, key=lambda it: hav(C, it["locatie"]["coordinates"]))
print(" result == 50 nearest of full list:", ids == {it["id"] for it in fd[:len(prox)]}, "| overlap:", len(ids & {it["id"] for it in fd[:len(prox)]}))
fdt = sorted(full, key=lambda it: it["createdAt"], reverse=True)
print(" result == 50 newest within radius:", ids == {it["id"] for it in fdt[:len(prox)]}, "| overlap:", len(ids & {it["id"] for it in fdt[:len(prox)]}))
fdo = sorted(full, key=lambda it: it["createdAt"])
print(" result == 50 oldest within radius:", ids == {it["id"] for it in fdo[:len(prox)]}, "| overlap:", len(ids & {it["id"] for it in fdo[:len(prox)]}))
print(" max distance in result:", round(max(dd)), "| 50th nearest distance in full list:", round(hav(C, fd[len(prox) - 1]["locatie"]["coordinates"])) if len(fd) >= len(prox) else None)

# team-number reconciliation: at which createdAt cutoff does the cumulative total equal 21527?
s = sorted(lst, key=lambda it: it["createdAt"])
if len(s) >= 21527:
    cut = s[21527 - 1]["createdAt"]
    sub = s[:21527]
    Lc = [it for it in sub if it["categorii"]["nume"].strip() == "Iluminat public" and it.get("locatie")]
    print("\nRECONCILE: createdAt of the 21527th report:", cut, "| lighting with coords among first 21527:", len(Lc), Counter(it["status"] for it in Lc).most_common())
wc = sum(1 for it in lst if it.get("locatie"))
print("reports with coords total:", wc)
per_day = Counter(it["createdAt"][:10] for it in lst)
print("reports per day, last 16 days:", sorted(per_day.items())[-16:])
