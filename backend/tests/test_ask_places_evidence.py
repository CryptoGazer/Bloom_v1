"""Regression cases from voice testing: independent endpoints, spelling and untrusted corrections."""
import pytest
from pathlib import Path
import gzip
import json
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ask import Asker, AskError, Gemini, clean, original_places
from backend.ask_places import AskPlaces
from backend.geocode import Places
from backend.tests.test_ask import FakeTransport, ROUTE, WAV
from backend.tests.test_ask_grounding import function, tool_answer
from backend.tests.test_routing import FEATURES


ENTRIES = [
    {"k": "place", "n": "Spitalul Clinic Căi Ferate", "lat": 45.749327, "lon": 21.218488, "c": "amenity=hospital"},
    {"k": "place", "n": "Spitalul Municipal Clinicile Noi", "lat": 45.759469, "lon": 21.226561, "c": "amenity=hospital"},
    {"k": "place", "n": "Pius Brînzeu", "lat": 45.751096, "lon": 21.221940, "c": "tourism=artwork"},
    {"k": "place", "n": "Parcul Botanic", "lat": 45.760166, "lon": 21.224805, "c": "leisure=park"},
    {"k": "place", "n": "Parcul Central Anton von Scudier", "lat": 45.751529, "lon": 21.220493, "c": "leisure=park"},
]
FORM = {**ROUTE, "from": "Spitalul Clinic Căi Ferate", "to": "Parcul Botanic", "mode": "walk", "time": None}


def asker(form):
    return Asker(Gemini("test", "single", transport=FakeTransport(form)), Places(ENTRIES))


def test_original_place_wins_over_a_hallucinated_hospital():
    result = asker({**FORM, "from": "Spitalul Clinic de Urgență Pius Brînzeu"}).ask(text="От Spitalul Clinic Căi Ferate до Parcul Botanic")
    assert result["kind"] == "route" and result["from"]["name"] == "Spitalul Clinic Căi Ferate"
    assert result["to"]["name"] == "Parcul Botanic"


def test_wrong_model_destination_cannot_replace_the_explicit_botanical_park():
    result = asker({**FORM, "to": "Parcul Central Anton von Scudier"}).ask(text="From Spitalul Clinic Căi Ferate to Botanical Park")
    assert result["kind"] == "route" and result["to"]["name"] == "Parcul Botanic"


def test_noisy_voice_suggests_real_hospitals_and_retains_destination():
    heard = "Сделай мне маршрут от больницы клиник Пьячерата до Ботанического парка"
    result = asker({**FORM, "from": "Spitalul Clinic de Urgență Pius Brînzeu", "heard": heard}).ask(audio=WAV)
    assert result["kind"] == "clarify" and result["ambiguity"] == ["from"]
    assert result["heard"] == heard and result["to"]["name"] == "Parcul Botanic"
    assert result["queries"]["from"] == "больницы клиник Пьячерата"
    assert "Spitalul Clinic Căi Ferate" in {p["name"] for p in result["candidates"]["from"]}
    assert all(p["name"] != "Pius Brînzeu" for p in result["candidates"]["from"])


@pytest.mark.parametrize("quote", [None, "больницы"])
def test_model_ambiguity_does_not_skip_local_spoken_name_suggestions(quote):
    form = {**FORM, "from": "больницы клиник Пьячерата", "from_query": quote, "ambiguity": ["from"]}
    result = asker(form).ask(text="Сделай маршрут от больницы клиник Пьячерата до Ботанического парка")
    assert result["kind"] == "clarify" and result["to"]["name"] == "Parcul Botanic"
    assert "Spitalul Clinic Căi Ferate" in [p["name"] for p in result["candidates"]["from"]]


@pytest.mark.parametrize("ambiguity", [[], ["from"]])
def test_inconsistent_missing_flag_cannot_hide_a_spoken_hospital(ambiguity):
    form = {**FORM, "from": "Пьячерата", "missing": ["from"], "ambiguity": ambiguity}
    result = asker(form).ask(text="от больницы Пьячерата до Ботанического парка")
    assert result["missing"] == [] and result["ambiguity"] == ["from"]
    assert result["to"]["name"] == "Parcul Botanic"
    assert "Spitalul Clinic Căi Ferate" in [p["name"] for p in result["candidates"]["from"]]


@pytest.mark.parametrize("name", ["Spitalul Clinic Căile Ferate", "Railway Hospital", "железнодорожная больница"])
def test_curated_aliases_resolve_without_inventing_coordinates(name):
    result = asker({**FORM, "from": name}).ask(text=f"От {name} до Parcul Botanic")
    assert result["kind"] == "route" and result["from"]["name"] == "Spitalul Clinic Căi Ferate"


def test_typo_is_a_candidate_not_an_automatic_route():
    result = asker({**FORM, "to": "Parcul Botanik"}).ask(text="От Spitalul Clinic Căi Ferate до Parcul Botanik")
    assert result["kind"] == "clarify" and result["candidates"]["to"][0]["name"] == "Parcul Botanic"


def test_tool_timeout_keeps_the_candidates_found_in_previous_turn():
    def reply(model, body):
        if "tools" not in body:
            return {**FORM, "from": "Unknown Clinic"}
        if len(body["contents"]) == 1:
            return tool_answer(function("search_places", {"side": "from", "category": "hospital"}))
        raise AskError("ai_unavailable", 502)
    result = asker(reply).ask(text="от неизвестного места до Parcul Botanic")
    assert result["kind"] == "clarify" and result["candidates"]["from"]
    assert result["to"]["name"] == "Parcul Botanic"


@pytest.mark.parametrize("use_id", [True, False])
def test_model_cannot_silently_select_a_category_fallback(use_id):
    lookup = AskPlaces(Places(ENTRIES))
    chosen = lookup.search("Spitalul Clinic Căi Ferate")[0]
    def reply(model, body):
        if "tools" not in body:
            return {**FORM, "from": "Missing Hospital"}
        if len(body["contents"]) == 1:
            return tool_answer(function("search_places", {"side": "from", "query": "Missing Hospital", "category": "hospital"}))
        form = {**FORM, "from": chosen["name"]}
        if use_id:
            form["from_id"] = chosen["id"]
        return tool_answer(function("submit_route", form))
    result = asker(reply).ask(text="От неизвестного места до Parcul Botanic")
    assert result["kind"] == "clarify" and result["ambiguity"] == ["from"]


def test_model_quotes_are_verified_against_the_input():
    form = original_places(clean({**FORM, "from_query": "Pius Brînzeu"}), "От клиники Пьячерата до Ботанического парка")
    assert form["from_query"] == "клиники Пьячерата"


def test_function_returns_no_coordinates_and_marks_approximate_results():
    result = AskPlaces(Places(ENTRIES)).tool({"query": "Parcul Botanik", "side": "to"})
    assert result["requires_confirmation"] is True
    assert result["places"][0]["name"] == "Parcul Botanic"
    assert all(set(p) == {"id", "name", "kind"} for p in result["places"])


def test_local_choices_do_not_spend_more_model_calls_on_an_already_uncertain_name():
    transport = FakeTransport({**FORM, "from": "Missing Hospital"})
    a = Asker(Gemini("test", "single", transport=transport), Places(ENTRIES))
    result = a.ask(text="от больницы Пьячерата до Parcul Botanic")
    assert result["kind"] == "clarify" and len(transport.calls) == 1


@pytest.mark.parametrize("spoken", ["больницы с петаллу клиник кэй ферате", "больницы клиник Пьячерата", "клиники кэй ферате"])
def test_spoken_hospital_is_among_suggestions_in_the_actual_city_index(spoken):
    lookup = AskPlaces(Places.load(Path(__file__).resolve().parents[2] / 'data/out/city/places.json.gz'))
    assert "Spitalul Clinic Căi Ferate" in [p["name"] for p in lookup.suggest(spoken)]


def test_http_contract_keeps_both_endpoints_and_reports_backend_version(tmp_path, monkeypatch):
    monkeypatch.setenv("TIGER_HISTORY", "off")
    for filename, data in (("places.json.gz", {"entries": ENTRIES}), ("segments.geojson.gz", {"features": FEATURES, "meta": {}})):
        with gzip.open(tmp_path / filename, "wt", encoding="utf-8") as f:
            json.dump(data, f)
    form = {**FORM, "from": "Spitalul Clinic de Urgență Pius Brînzeu", "heard": "От больницы Пьячерата до Ботанического парка"}
    app = create_app(tmp_path / 'segments.geojson.gz', gemini=Gemini("test", "single", transport=FakeTransport(form)))
    with TestClient(app) as client:
        assert client.get('/api/health').json()['ask_version'] == 4
        result = client.post('/api/ask', json={'audio': WAV, 'mime': 'audio/wav', 'lang': 'ru'}).json()
    assert result['kind'] == 'clarify' and result['to']['name'] == 'Parcul Botanic'
    assert result['ambiguity'] == ['from'] and result['candidates']['from']
    assert result['queries']['from'] == 'больницы Пьячерата'
