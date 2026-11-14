"""usage: python -I ckan_strazi.py <ckan_or.json> <ckan_all.json> <nomenclator.json>"""
import json, sys, re, unicodedata
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
for p in sys.argv[1:3]:
    j = json.load(open(p, encoding="utf-8"))
    r = j["result"]
    print("\nCKAN", p.replace("\\", "/").split("/")[-1], "success", j.get("success"), "count", r["count"], "returned", len(r["results"]))
    for d in r["results"]:
        fm = sorted({(x.get("format") or "?") for x in d.get("resources", [])})
        print("  - %s | name=%s | org=%s | modified=%s | formats=%s | groups=%s" % (d.get("title"), d.get("name"), (d.get("organization") or {}).get("title"), (d.get("metadata_modified") or "")[:10], fm, [g.get("title") for g in d.get("groups", [])]))
s = json.load(open(sys.argv[3], encoding="utf-8"))
print("\nNOMENCLATOR top type", type(s).__name__, "len", len(s) if hasattr(s, "__len__") else "")
if isinstance(s, dict):
    print(" keys", list(s.keys())[:20])
    for k, v in s.items():
        if isinstance(v, list):
            s = v; print(" using list under", k, len(v)); break
print(" key-sets:", Counter(tuple(it.keys()) for it in s).most_common(3))
types = {}
for it in s:
    for k, v in it.items():
        types.setdefault(k, Counter())[type(v).__name__ if v != "" else "str(empty)"] += 1
for k, c in types.items():
    print("  ", k, dict(c))
for k in s[0]:
    vals = [it.get(k) for it in s]
    if all(isinstance(v, (str, type(None), bool, int)) for v in vals):
        c = Counter(vals)
        if len(c) <= 40:
            print("  values of", k, ":", c.most_common(40))
print(" first 3 rows:")
for it in s[:3]:
    print("  ", json.dumps(it, ensure_ascii=False))
def fold(x):
    return "".join(ch for ch in unicodedata.normalize("NFD", x) if unicodedata.category(ch) != "Mn").lower()
pat = re.compile(r"\b(cluj|parvan|mihai viteazu|16 decembrie|eroilor|ripensia|tudor vladimirescu|rebreanu|daliei|pestalozzi|victor babes|corbului|michelangelo|paris|traian lalescu|aurelianus|gheorghe lazar|cozia|carpati|romulus|memorandului|circumvalatiunii|aradului|victoriei)\b")
print(" matching rows:")
for it in s:
    txt = " | ".join(str(v) for v in it.values() if isinstance(v, str))
    if pat.search(fold(txt)):
        print("  ", json.dumps(it, ensure_ascii=False))
