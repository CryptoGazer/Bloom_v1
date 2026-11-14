"""Search streets, addresses, places and transit stops of the map area. Pure Python, no network.

The list of entries comes from backend/build_places.py (data/out/city/places.json.gz). Each entry:
  {"k": "street" | "addr" | "place" | "stop", "n": display name, "lat": .., "lon": ..,
   "s": street (addr only), "h": house number (addr only), "c": category (place) or lines (stop)}

Matching: every word of the query must start a word of the name, without diacritics or case.
A trailing number after a street name is a house number: the exact address wins; if the address is not
mapped, the street itself is offered with "number_missing". Type words (str., bd., pța ...) are optional
and only steer the ranking.
"""
import gzip
import json
import re
import unicodedata
from pathlib import Path

TYPE_ALIASES = {
    "strada": "strada", "str": "strada",
    "bulevardul": "bulevardul", "bulevard": "bulevardul", "bdul": "bulevardul", "bd": "bulevardul", "blvd": "bulevardul",
    "piata": "piata", "pta": "piata", "pt": "piata",
    "calea": "calea", "cal": "calea",
    "aleea": "aleea", "al": "aleea",
    "intrarea": "intrarea", "intr": "intrarea",
    "splaiul": "splaiul", "splai": "splaiul", "spl": "splaiul",
    "soseaua": "soseaua", "sos": "soseaua",
    "podul": "podul", "pod": "podul",
    "pasajul": "pasajul", "pasaj": "pasajul",
}
NOISE = {"nr", "numar", "numarul", "no"}
NUMBER = re.compile(r"^\d+[a-z]?$")
KIND_WEIGHT = {"street": 40, "place": 35, "stop": 30, "addr": 20}
# places students look for at night rank a little higher among equal name matches
STUDENT_CATEGORIES = {"amenity=university", "building=university", "amenity=college", "building=dormitory"}
# words that find a place by what it is, when its name is a brand ("farmacie" finds "Catena")
CATEGORY_WORDS = {
    "amenity=pharmacy": "farmacie farmacia pharmacy",
    "shop=supermarket": "supermarket magazin alimentara",
    "shop=convenience": "magazin alimentara convenience",
    "amenity=university": "universitate universitatea facultate facultatea university",
    "building=university": "universitate universitatea facultate facultatea university",
    "amenity=college": "colegiu college",
    "building=dormitory": "camin caminul dormitory",
    "amenity=restaurant": "restaurant",
    "amenity=cafe": "cafenea cafe",
    "amenity=bar": "bar",
    "amenity=pub": "pub bar",
    "amenity=fast_food": "fast food",
    "amenity=bank": "banca bank",
    "amenity=atm": "bancomat atm",
    "amenity=hospital": "spital hospital",
    "amenity=clinic": "clinica clinic",
    "leisure=park": "parc parcul park",
    "tourism=hotel": "hotel",
    "amenity=place_of_worship": "biserica church",
    "amenity=police": "politie politia police",
    "amenity=bicycle_rental": "biciclete bicicleta bike rental",
    "amenity=library": "biblioteca library",
}


def normalize(text):
    """Lower case, no diacritics, punctuation to spaces; 'b-dul' and 'p-ța' kept as one word."""
    s = unicodedata.normalize("NFD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = s.replace("b-dul", "bdul").replace("p-ta", "pta")
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())


def tokens(text):
    """Words of a name; a mixed word like 'c12' also yields 'c' and '12'."""
    out = []
    for word in normalize(text).split():
        out.append(word)
        parts = re.findall(r"[a-z]+|\d+", word)
        if len(parts) > 1:
            out.extend(parts)
    return out


def _starts_all(words, toks):
    return all(any(t.startswith(w) for t in toks) for w in words)


class Places:
    def __init__(self, entries, meta=None):
        self.meta = meta or {}
        self.items = []
        for e in entries:
            toks = tokens(e["n"])
            plain = [w for w in normalize(e["n"]).split() if w not in TYPE_ALIASES]
            self.items.append({
                "e": e, "tokens": toks, "set": set(toks), "core": " ".join(plain),
                "type": TYPE_ALIASES.get(toks[0]) if toks else None,
                "street": tokens(e.get("s", "")) if e["k"] == "addr" else None,
                "street_key": normalize(e.get("s", "")) if e["k"] == "addr" else normalize(e["n"]),
                "h": normalize(e.get("h", "")).replace(" ", ""),
                "cat_tokens": tokens(CATEGORY_WORDS.get(e.get("c") or "", "")) if e["k"] == "place" else [],
                "bonus": 8 if e.get("c") in STUDENT_CATEGORIES else 0,
            })

    @classmethod
    def load(cls, path):
        with gzip.open(Path(path), "rt", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data["entries"], data.get("meta"))

    @staticmethod
    def _result(item, score, **extra):
        e = item["e"]
        out = {"kind": e["k"], "name": e["n"], "lat": e["lat"], "lon": e["lon"], "detail": e.get("c")}
        out.update(extra)
        return score, out

    def search(self, query, limit=8):
        words = [w for w in normalize(query).split() if w not in NOISE]
        if sum(len(w) for w in words) < 2:
            return []
        qtype = next((TYPE_ALIASES[w] for w in words if w in TYPE_ALIASES), None)
        name_words = [w for w in words if w not in TYPE_ALIASES] or words
        number = name_words[-1] if len(name_words) >= 2 and NUMBER.match(name_words[-1]) else None
        street_words = name_words[:-1] if number else name_words
        phrase = " ".join(name_words)

        def type_bonus(item):
            if not qtype or not item["type"]:
                return 0
            return 20 if item["type"] == qtype else -10

        scored, exact_streets = [], set()
        if number:
            for item in self.items:
                if item["e"]["k"] != "addr" or not _starts_all(street_words, item["street"]):
                    continue
                if item["h"] == number:
                    exact_streets.add(item["street_key"])
                    scored.append(self._result(item, 100 + type_bonus(item) + 5 * sum(w in item["street"] for w in street_words)))
                elif item["h"].startswith(number):
                    scored.append(self._result(item, 15 + type_bonus(item)))
        for item in self.items:
            if item["e"]["k"] == "addr":
                continue
            if _starts_all(name_words, item["tokens"]):
                exact = sum(w in item["set"] for w in name_words)
                start = 15 if item["core"].startswith(phrase) else 0
                # the earlier the first query word appears in the name, the better ("Universitatea Politehnica"
                # before "Baza sportivă nr. 1 Politehnica")
                position = next(i for i, t in enumerate(item["tokens"]) if t.startswith(name_words[0]))
                score = (KIND_WEIGHT[item["e"]["k"]] + 5 * exact + start + type_bonus(item) + item["bonus"]
                         - min(2 * position, 10) - len(item["e"]["n"]) / 20)
                scored.append(self._result(item, score))
            elif number and item["e"]["k"] == "street" and item["street_key"] not in exact_streets and _starts_all(street_words, item["tokens"]):
                scored.append(self._result(item, 45 + type_bonus(item) - len(item["e"]["n"]) / 20, number_missing=number))
            elif item["cat_tokens"] and _starts_all(name_words, item["cat_tokens"]):
                scored.append(self._result(item, 12 - len(item["e"]["n"]) / 20))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        results, seen = [], set()
        for _, result in scored:  # the same name twice (a faculty as a point and as a building) is shown once
            key = (result["kind"], normalize(result["name"]))
            if key not in seen:
                seen.add(key)
                results.append(result)
            if len(results) == limit:
                break
        return results
