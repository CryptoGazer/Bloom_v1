"""Print the structural shape (names + types only, no free text) of a JSON array file."""
import json, sys, re
from collections import Counter, defaultdict

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)

print("top type:", type(data).__name__, "len:", len(data) if hasattr(data, "__len__") else "")
if isinstance(data, dict):
    print("top keys:", list(data.keys()))
    sys.exit(0)

shapes = defaultdict(Counter)


def walk(prefix, v):
    t = type(v).__name__
    if isinstance(v, dict):
        shapes[prefix]["dict"] += 1
        for k, vv in v.items():
            walk(prefix + "." + k, vv)
    elif isinstance(v, list):
        shapes[prefix]["list(len=%s)" % ("0" if not v else "1" if len(v) == 1 else "2" if len(v) == 2 else "3+")] += 1
        for vv in v:
            walk(prefix + "[]", vv)
    else:
        if isinstance(v, str) and v == "":
            t = "str(empty)"
        shapes[prefix][t] += 1


for it in data:
    walk("", it)

for k in sorted(shapes):
    print(k or "<item>", dict(shapes[k]))

# key-set variants
ks = Counter(tuple(sorted(it.keys())) for it in data)
print("key-set variants:", len(ks))
for k, c in ks.most_common(5):
    print(c, k)

# date patterns
def pat(s):
    return re.sub(r"\d", "9", s) if isinstance(s, str) else repr(type(s).__name__)

for fld in ("createdAt", "updatedAt", "webconInstanceNr", "id"):
    c = Counter(pat(it.get(fld)) for it in data)
    print(fld, "patterns:", c.most_common(6))

cr = sorted(it["createdAt"] for it in data if isinstance(it.get("createdAt"), str))
print("createdAt min/max:", cr[0], cr[-1])
# is list sorted by createdAt?
seq = [it.get("createdAt") for it in data]
print("sorted asc:", seq == sorted(seq), "sorted desc:", seq == sorted(seq, reverse=True))
# hour-of-day histogram of createdAt as given (to judge timezone)
hh = Counter(s[11:13] for s in cr)
print("hour histogram (as given):", sorted(hh.items()))
# locatie variants
lc = Counter()
for it in data:
    l = it.get("locatie")
    if l is None:
        lc["None"] += 1
    elif isinstance(l, dict):
        lc["dict keys=%s type=%s ncoord=%s" % (sorted(l.keys()), l.get("type"), len(l.get("coordinates") or []))] += 1
    else:
        lc[type(l).__name__ + ":" + ("empty" if not l else "nonempty")] += 1
print("locatie variants:", lc)
print("status:", Counter(it.get("status") for it in data))
cat = Counter()
for it in data:
    c = it.get("categorii")
    cat[c.get("nume") if isinstance(c, dict) else repr(c)] += 1
print("categories:", cat.most_common(60))
