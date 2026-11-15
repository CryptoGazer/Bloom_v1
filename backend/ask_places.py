"""Local, bounded place search for Gemini. Only public names and opaque IDs leave the server."""
import hashlib
import math
import re
import unicodedata
from difflib import SequenceMatcher

from backend.geocode import normalize


# A small curated vocabulary, not a second city database. Entries absent from our index are omitted.
LANDMARKS = (
    ("Piața Unirii", "Union Square; площадь Единства; площадь Унирий; northern old-town square"),
    ("Piața Victoriei", "Victory Square; Opera Square; площадь Победы; площадь Виктории"),
    ("Piața Libertății", "Liberty Square; площадь Свободы; between Victoriei and Unirii"),
    ("Piața 700", "Piata Sapte Sute; площадь 700"),
    ("Universitatea Politehnica Timișoara", "UPT; Politehnica; Polytechnic; Политех; Политехнический университет"),
    ("Rectoratul Universității Politehnica Timișoara", "UPT rectorate; ректорат Политеха"),
    ("Universitatea de Vest din Timișoara", "UVT; West University; Западный университет"),
    ("Căminul C12 UVT", "C12; camin 12; dorm C12; общежитие С12; общага C12"),
    ("Catedrala Mitropolitană", "Orthodox Cathedral; Metropolitan Cathedral; кафедральный собор"),
    ("Parcul Rozelor", "Rose Park; парк роз"),
    ("Complexul Studențesc", "student campus; campus; студгородок; кампус"),
    ("Spitalul Clinic Căi Ferate", "Spitalul Clinic Căile Ferate; Spitalul Clinic CF; Railway Hospital; железнодорожная больница; больница Кэй Ферате"),
    ("Parcul Botanic", "Botanical Park; Botanical Garden; Botanic Park; Ботанический парк; Ботанического парка; ботанический сад"),
)
CATEGORIES = {
    "square": lambda e: normalize(e["n"]).startswith("piata ") and e["k"] == "street",
    "university": lambda e: e.get("c") in {"amenity=university", "building=university", "amenity=college"},
    "dormitory": lambda e: e.get("c") == "building=dormitory",
    "pharmacy": lambda e: e.get("c") == "amenity=pharmacy",
    "supermarket": lambda e: e.get("c") in {"shop=supermarket", "shop=convenience"},
    "park": lambda e: e.get("c") == "leisure=park",
    "cafe": lambda e: e.get("c") == "amenity=cafe",
    "restaurant": lambda e: e.get("c") == "amenity=restaurant",
    "atm": lambda e: e.get("c") == "amenity=atm",
    "hospital": lambda e: e.get("c") == "amenity=hospital",
    "clinic": lambda e: e.get("c") in {"amenity=clinic", "amenity=hospital"},
    "stop": lambda e: e["k"] == "stop",
}
DIRECTIONS = {"north": (1, 0), "south": (-1, 0), "east": (0, 1), "west": (0, -1)}
CATEGORY_HINTS = {
    "hospital": r"больниц|спитал|spital|hospital",
    "clinic": r"клиник|clinica|clinic",
    "park": r"парк|parc|park|garden|сад\b",
    "pharmacy": r"аптек|farmaci|pharmacy",
    "dormitory": r"общаг|общежити|c[aă]min|dorm",
    "university": r"университет|факультет|universit|facultat|polytechnic|politehn",
    "square": r"площад|pia[tț]a|square",
}
CYRILLIC = str.maketrans(dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", (
    "a", "b", "v", "g", "d", "e", "e", "j", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "h", "ts", "c", "s", "s", "", "i", "", "e", "iu", "ia"))))
GENERIC_WORDS = {"spital", "spitalul", "clinic", "clinica", "clinicile", "hospital", "the", "de", "din", "la", "pentru", "parc", "parcul", "park", "garden"}


def alias_key(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", "".join(c for c in value if not unicodedata.combining(c))).split())


def category_of(query):
    return next((category for category, pattern in CATEGORY_HINTS.items() if re.search(pattern, query, re.I)), "")


def sound_key(value):
    """Small RO/RU/EN spelling heuristic for ranking suggestions only, never automatic correction."""
    words = [w for w in alias_key(value).split() if w not in GENERIC_WORDS and not re.match(r"больниц|клиник|парк|ботаническ", w)]
    value = "".join(words).translate(CYRILLIC)
    for source, target in (("ph", "f"), ("qu", "k"), ("c", "k"), ("y", "i"), ("ei", "ai")):
        value = value.replace(source, target)
    return value


class AskPlaces:
    def __init__(self, places):
        self.places = places
        self.by_id, self.ids, self.aliases, self.catalog, self.categories, self.names = {}, {}, {}, [], {}, {}
        for item in places.items:
            e = item["e"]
            identity = (e["k"], normalize(e["n"]))
            pid = "p_" + hashlib.sha256(repr(identity).encode()).hexdigest()[:12]
            self.ids[identity] = pid
            self.by_id.setdefault(pid, {"id": pid, "kind": e["k"], "name": e["n"], "lat": e["lat"], "lon": e["lon"]})
            self.names.setdefault(alias_key(e["n"]), pid)
            self.categories.setdefault(pid, set()).update(k for k, check in CATEGORIES.items() if check(e))
        for name, aliases in LANDMARKS:
            found = [r for r in places.search(name, 4) if normalize(r["name"]) == normalize(name)]
            if not found:
                continue
            entry = self.identify(found[0])
            self.catalog.append({"id": entry["id"], "name": entry["name"], "aliases": aliases})
            for alias in [name, *aliases.split("; ")]:
                self.aliases[alias_key(alias)] = entry["id"]

    def identify(self, result):
        return {**result, "id": self.ids[(result["kind"], normalize(result["name"]))]}

    def get(self, pid):
        return self.by_id.get(pid)

    def named(self, query):
        """Exact names/curated aliases only; no ASR guesses become automatically selected points."""
        key = alias_key(query)
        alias = self.aliases.get(key)
        if alias:
            return self.get(alias)
        return self.get(self.names.get(key))

    def suggest(self, query, category="", limit=5):
        """Approximate names and category fallbacks are suggestions that require confirmation."""
        category = category or category_of(query)
        key = alias_key(query)
        if not key:
            return []
        pool = [p for pid, p in self.by_id.items() if (category in self.categories[pid] if category else p["kind"] in ("place", "street"))]
        phonetic = sound_key(query)
        def score(p):
            spelling = SequenceMatcher(None, key, alias_key(p["name"])).ratio()
            return max(spelling, SequenceMatcher(None, phonetic, sound_key(p["name"])).ratio() if phonetic else 0)
        scored = sorted(((score(p), p) for p in pool), key=lambda pair: (-pair[0], pair[1]["name"]))
        close = [p for score, p in scored if score >= .65]
        # A noisy medical name should still offer real hospitals, never an artwork with a doctor's name.
        return (close or ([p for _, p in scored] if category else []))[:limit]

    def search(self, query="", category="", reference_id="", direction="", limit=5):
        if not isinstance(query, str) or len(query) > 160 or category not in ("", *CATEGORIES):
            return []
        if direction not in ("", *DIRECTIONS) or (reference_id and reference_id not in self.by_id):
            return []
        if direction and not reference_id:
            return []  # "north" needs an explicit public reference, never the visitor's position
        limit = max(1, min(limit, 5)) if isinstance(limit, int) and not isinstance(limit, bool) else 5
        matches = [self.identify(r) for r in self.places.search(query, 20)] if query else []
        alias = self.aliases.get(alias_key(query))
        if alias:
            matches.insert(0, self.get(alias))
        if category:
            pool = {pid for pid, categories in self.categories.items() if category in categories}
            matches = [r for r in matches if r["id"] in pool]
            if not matches:
                matches = [r for pid, r in self.by_id.items() if pid in pool]
        reference = self.get(reference_id)
        if reference:
            def offset(r):
                return ((r["lat"] - reference["lat"]) * 111147, (r["lon"] - reference["lon"]) * 77811)
            if direction:
                dy, dx = DIRECTIONS[direction]
                matches = [r for r in matches if sum(a * b for a, b in zip(offset(r), (dy, dx))) > 25]
            matches.sort(key=lambda r: math.hypot(*offset(r)))
        unique = {}
        for result in matches:
            unique.setdefault(result["id"], result)
        return list(unique.values())[:limit]

    def tool(self, args):
        """Untrusted arguments, no dispatch to arbitrary code and no coordinates in tool results."""
        if not isinstance(args, dict) or set(args) - {"query", "category", "reference_id", "direction", "limit", "side"}:
            return {"error": "invalid_arguments"}
        if any(not isinstance(args.get(k, ""), str) for k in ("query", "category", "reference_id", "direction", "side")) or args.get("side", "from") not in ("from", "to"):
            return {"error": "invalid_arguments"}
        search_args = {k: v for k, v in args.items() if k != "side"}
        results = self.search(**search_args)
        query = args.get("query", "")
        exact = self.named(query)
        # A named query that fell back to a whole category is not evidence for any specific place.
        direct_ids = {p["id"] for p in self.search(query)} if query else set()
        confirmation = bool(query and not exact and (len(results) > 1 or not direct_ids or not {p["id"] for p in results} <= direct_ids))
        if not results and query and not args.get("direction") and not args.get("reference_id"):
            results = self.suggest(query, args.get("category", ""))
            confirmation = bool(results)
        return {"places": [{k: r[k] for k in ("id", "name", "kind")} for r in results], "requires_confirmation": confirmation}
