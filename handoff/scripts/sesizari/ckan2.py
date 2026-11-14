import json, sys, re, unicodedata
sys.stdout.reconfigure(encoding="utf-8")
j = json.load(open(sys.argv[1], encoding="utf-8"))
def fold(x): return "".join(ch for ch in unicodedata.normalize("NFD", x or "") if unicodedata.category(ch) != "Mn").lower()
raw = fold(json.dumps(j, ensure_ascii=False))
print({k: raw.count(k) for k in ("ilumin", "stalp", "lamp", "corpuri", "felinar", "lumin", "bec ")})
for d in j["result"]["results"]:
    if d["name"] in ("alimentare-cu-energie-electrica", "infrastructura-de-alimentare-cu-energie", "infrastructura-rutiera", "siguranta-si-ordine-publica"):
        print(d["title"], "| https://data.primariatm.ro/dataset/" + d["name"], "| created", (d.get("metadata_created") or "")[:10], "| modified", (d.get("metadata_modified") or "")[:10])
        print("   notes:", (d.get("notes") or "")[:300].replace("\n", " "))
        for r in d.get("resources", []):
            print("   -", r.get("name"), "|", r.get("format"), "|", (r.get("last_modified") or r.get("created") or "")[:10], "|", (r.get("description") or "")[:120].replace("\n", " "))
for k in ("ilumin", "lumin"):
    for m in list(re.finditer(k, raw))[:6]:
        print("ctx[%s]:" % k, raw[max(0, m.start()-150): m.end()+150])
