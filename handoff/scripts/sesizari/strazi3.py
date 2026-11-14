import json, sys, re, unicodedata
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
s = json.load(open(sys.argv[1], encoding="utf-8"))["strazi"]
def fold(x): return "".join(ch for ch in unicodedata.normalize("NFD", x) if unicodedata.category(ch) != "Mn")
na = [it for it in s if not it["denumireCompletaFaraDiacritice"].isascii()]
print("FaraDiacritice non-ascii rows:", len(na), [it["denumireCompletaFaraDiacritice"] for it in na])
ne = [it for it in s if fold(it["denumireCompleta"]) != it["denumireCompletaFaraDiacritice"]]
print("FaraDiacritice != NFD-fold(denumireCompleta):", len(ne), [(it["denumireCompleta"], it["denumireCompletaFaraDiacritice"]) for it in ne][:12])
part = Counter(w for it in s for w in it["denumireCompleta"].split()[2:] if w in ("De", "La", "Din", "Cel", "Și", "Si", "Cu", "Pe", "Lui", "Sub", "Al", "A", "Cea", "Lângă", "Către", "Spre", "În"))
print("title-cased particles:", part.most_common())
print("examples:", [it["denumireCompleta"] for it in s if re.search(r" (De|Din|Cel|Și|Cu|Pe|Lui|La) ", it["denumireCompleta"])][:14])
print("whitespace irregularities:", [repr(it["denumireCompleta"]) for it in s if it["denumireCompleta"] != " ".join(it["denumireCompleta"].split())][:10])
print("parentheses/other punctuation:", [it["denumireCompleta"] for it in s if re.search(r"[()\[\],;/\"]", it["denumireCompleta"])][:12])
print("hyphenated:", len([1 for it in s if "-" in it["denumireCompleta"]]), [it["denumireCompleta"] for it in s if "-" in it["denumireCompleta"]][:8])
print("provizorie:", [it["denumireCompleta"] for it in s if "provizorie" in it["denumireCompleta"].lower()][:4])
print("Dezafectata rows:", [(it["denumireCompleta"], it["codGis"]) for it in s if it["stare"] == "Dezafectata"])
print("empty tipArtera:", [it["denumireCompleta"] for it in s if not it["tipArtera"]])
print("codGis unique:", len({it["codGis"] for it in s if it["codGis"]}), "of", sum(1 for it in s if it["codGis"]))
camp = [it for it in s if "campus" in it["cartier"].lower()]
print("rows whose cartier mentions Campus:", len(camp), Counter(it["cartier"] for it in camp).most_common(30))
print("campus street names:", sorted(it["denumireCompleta"] for it in camp))
