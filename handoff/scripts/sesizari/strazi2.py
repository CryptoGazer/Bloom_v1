"""usage: python -I strazi2.py <nomenclator.json> <card.json>..."""
import json, sys, re, unicodedata
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
j = json.load(open(sys.argv[1], encoding="utf-8"))
s = j["strazi"]
print("activeCount", j["activeCount"], "rows", len(s))
def fold(x):
    return "".join(ch for ch in unicodedata.normalize("NFD", x) if unicodedata.category(ch) != "Mn").lower()
print("cartier values (%d):" % len(Counter(it["cartier"] for it in s)), Counter(it["cartier"] for it in s).most_common(80))
# structural checks
print("denumireCompleta == tipArtera + ' ' + numeActual:", sum(1 for it in s if it["denumireCompleta"] == (it["tipArtera"] + " " + it["numeActual"]).strip()), "/", len(s))
print("examples where not:", [(it["denumireCompleta"], it["tipArtera"], it["numeActual"]) for it in s if it["denumireCompleta"] != (it["tipArtera"] + " " + it["numeActual"]).strip()][:8])
print("FaraDiacritice == ascii-fold(denumireCompleta):", sum(1 for it in s if fold(it["denumireCompletaFaraDiacritice"]) == fold(it["denumireCompleta"]) and it["denumireCompletaFaraDiacritice"].isascii()), "/", len(s))
print("non-ascii FaraDiacritice examples:", [it["denumireCompletaFaraDiacritice"] for it in s if not it["denumireCompletaFaraDiacritice"].isascii()][:8])
chars = Counter(ch for it in s for ch in it["denumireCompleta"] if not ch.isascii())
print("non-ascii chars in denumireCompleta:", [(ch, "U+%04X" % ord(ch), n) for ch, n in chars.most_common()])
print("rows with numeAnterior != numeActual:", sum(1 for it in s if it["numeAnterior"] != it["numeActual"]), "examples:", [(it["denumireCompleta"], it["numeAnterior"]) for it in s if it["numeAnterior"] != it["numeActual"]][:6])
print("names with dots (abbreviations):", len([1 for it in s if "." in it["denumireCompleta"]]), [it["denumireCompleta"] for it in s if "." in it["denumireCompleta"]][:25])
low = Counter(w for it in s for w in it["denumireCompleta"].split()[1:] if w[:1].islower())
print("lower-case words inside names:", low.most_common(20))
print("names with digits:", [it["denumireCompleta"] for it in s if re.search(r"\d", it["denumireCompleta"])][:25])
print("names with titles/ranks:", Counter(w for it in s for w in it["denumireCompleta"].split()[1:3] if fold(w).rstrip(".") in ("dr","doctor","general","gen","g-ral","prof","profesor","ing","inginer","col","colonel","maior","mr","cpt","capitan","lt","locotenent","sf","sfantul","sfanta","episcop","ep","mitropolit","regele","regina","arh","pictor","poet","acad","academician","av","aviator","martir","erou","preot","pr")).most_common(40))
dup = Counter(fold(it["denumireCompleta"]) for it in s if it["stare"] == "Existenta")
print("duplicate full names (active):", [(k, v) for k, v in dup.items() if v > 1][:10])
dupn = Counter(fold(it["numeActual"]) for it in s if it["stare"] == "Existenta")
print("bare names shared by several artery types (active):", sum(1 for v in dupn.values() if v > 1), [(k, [x["tipArtera"] for x in s if fold(x["numeActual"]) == k]) for k, v in dupn.items() if v > 1][:8])
want = ["cluj", "vasile parvan", "mihai viteazu", "16 decembrie 1989", "eroilor de la tisa", "f. c. ripensia", "f.c. ripensia", "ripensia", "tudor vladimirescu", "liviu rebreanu", "daliei", "pestalozzi", "victor babes", "michelangelo", "paris", "traian lalescu", "corbului", "gheorghe lazar", "cozia", "aurelianus", "arhitect laszlo szekely", "ferdinand i", "victoriei"]
print("\nEXAMPLE ROWS")
for w in want:
    for it in s:
        if fold(it["numeActual"]) == w or (w in ("mihai viteazu", "victor babes", "ripensia", "ferdinand i", "16 decembrie 1989") and w in fold(it["denumireCompleta"])):
            print("  ", json.dumps({k: it[k] for k in ("denumireCompleta", "denumireCompletaFaraDiacritice", "numeActual", "numeAnterior", "tipArtera", "cartier", "stare", "codGis", "careuGhid", "nrImparMin", "nrImparMax", "nrParMin", "nrParMax")}, ensure_ascii=False))
print("\nCARD strada vs nomenclator")
full = {it["denumireCompleta"]: it for it in s}
fullf = {}
for it in s:
    fullf.setdefault(fold(it["denumireCompleta"]), []).append(it)
for p in sys.argv[2:]:
    c = json.load(open(p, encoding="utf-8"))
    st = c.get("strada")
    print("  %r nr=%r | exact denumireCompleta: %s | exact FaraDiacritice: %s | case+diacritic-fold: %s -> %s" % (st, c.get("nrStrada"), st in full, any(it["denumireCompletaFaraDiacritice"] == st for it in s), fold(st) in fullf, [(x["denumireCompleta"], x["cartier"]) for x in fullf.get(fold(st), [])]))
