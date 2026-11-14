"""Address and place search on a small hand-made list. Run: .venv/bin/python -m pytest backend/tests -q"""
import pytest

from backend.geocode import Places, normalize

ENTRIES = [
    {"k": "street", "n": "Strada Cluj", "lat": 45.746, "lon": 21.236},
    {"k": "street", "n": "Bulevardul 16 Decembrie 1989", "lat": 45.745, "lon": 21.215},
    {"k": "street", "n": "Piața Victoriei", "lat": 45.754, "lon": 21.226},
    {"k": "street", "n": "Strada Victor Hugo", "lat": 45.757, "lon": 21.231},
    {"k": "addr", "n": "Strada Cluj 5", "s": "Strada Cluj", "h": "5", "lat": 45.7461, "lon": 21.2361},
    {"k": "addr", "n": "Strada Cluj 50", "s": "Strada Cluj", "h": "50", "lat": 45.7462, "lon": 21.2362},
    {"k": "addr", "n": "Bulevardul 16 Decembrie 1989 10", "s": "Bulevardul 16 Decembrie 1989", "h": "10", "lat": 45.7451, "lon": 21.2151},
    {"k": "place", "n": "Căminul C12 UVT", "c": "building=dormitory", "lat": 45.748, "lon": 21.240},
    {"k": "place", "n": "Facultatea de Automatică și Calculatoare", "c": "amenity=university", "lat": 45.747, "lon": 21.227},
    {"k": "place", "n": "Complexul Studențesc", "c": "place=suburb", "lat": 45.748, "lon": 21.239},
    {"k": "stop", "n": "Complexul Studențesc", "c": "8, 33", "lat": 45.7481, "lon": 21.2353},
]


@pytest.fixture(scope="module")
def places():
    return Places(ENTRIES)


def names(results):
    return [(r["kind"], r["name"]) for r in results]


def test_normalize_drops_diacritics_case_and_punctuation():
    assert normalize("Piața  Victoriei, nr. 5") == "piata victoriei nr 5"


def test_a_street_comes_first_and_house_numbers_stay_hidden_without_a_number(places):
    got = names(places.search("cluj"))
    assert got[0] == ("street", "Strada Cluj")
    assert all(kind != "addr" for kind, _ in got)


def test_house_number_finds_the_exact_address(places):
    assert names(places.search("str. cluj nr 5"))[0] == ("addr", "Strada Cluj 5")
    assert names(places.search("cluj 50"))[0] == ("addr", "Strada Cluj 50")


def test_unknown_house_number_falls_back_to_the_street(places):
    first = places.search("cluj 7")[0]
    assert (first["kind"], first["name"], first["number_missing"]) == ("street", "Strada Cluj", "7")


def test_numbers_inside_a_street_name_are_not_house_numbers(places):
    assert names(places.search("16 decembrie"))[0] == ("street", "Bulevardul 16 Decembrie 1989")
    assert names(places.search("16 decembrie 1989 10"))[0] == ("addr", "Bulevardul 16 Decembrie 1989 10")


@pytest.mark.parametrize("query", ["camin c12", "camin 12", "C12", "căminul c12 uvt"])
def test_dormitories_by_short_names(places, query):
    assert names(places.search(query))[0] == ("place", "Căminul C12 UVT")


def test_search_without_diacritics_and_by_word_start(places):
    assert names(places.search("automatica"))[0] == ("place", "Facultatea de Automatică și Calculatoare")
    assert names(places.search("pta victor"))[0] == ("street", "Piața Victoriei")


def test_stop_and_place_with_the_same_name_are_both_offered(places):
    got = names(places.search("complexul"))
    assert ("stop", "Complexul Studențesc") in got and ("place", "Complexul Studențesc") in got


def test_a_place_is_found_by_what_it_is():
    found = Places(ENTRIES + [{"k": "place", "n": "Catena", "c": "amenity=pharmacy", "lat": 45.75, "lon": 21.23}]).search("farmacie")
    assert names(found) == [("place", "Catena")]


def test_name_matches_rank_above_category_matches_and_universities_rank_up():
    extra = [{"k": "place", "n": "Baza sportivă nr. 1 Politehnica", "c": "leisure=sports_centre", "lat": 45.75, "lon": 21.23},
             {"k": "place", "n": "Universitatea Politehnica Timișoara", "c": "amenity=university", "lat": 45.75, "lon": 21.23}]
    assert names(Places(ENTRIES + extra).search("politehnica"))[0] == ("place", "Universitatea Politehnica Timișoara")
    assert names(Places(ENTRIES).search("camin"))[0] == ("place", "Căminul C12 UVT")


def test_too_short_or_unknown_queries_give_nothing(places):
    assert places.search("") == [] and places.search("a") == []
    assert places.search("zzzz nowhere") == []


def test_results_carry_coordinates_and_details(places):
    stop = next(r for r in places.search("complexul") if r["kind"] == "stop")
    assert (stop["lat"], stop["lon"], stop["detail"]) == (45.7481, 21.2353, "8, 33")
    assert len(places.search("strada", limit=2)) == 2
