"""Semantic retries, private tool search, ambiguity and bounded untrusted model actions."""
import json

import pytest

from backend.ask import DEFAULT_MODELS, LIMITS, AskError, Asker, Gemini, Limiter, clean
from backend.ask_places import AskPlaces
from backend.geocode import Places
from backend.tests.test_ask import ENTRIES, ROUTE, WAV, FakeTransport, answer


EXTRA = [
    {"k": "street", "n": "Piața Unirii", "lat": 45.7578, "lon": 21.2289},
    {"k": "street", "n": "Piața Libertății", "lat": 45.7555, "lon": 21.2273},
]


def build(transport, models="lite,flash"):
    return Asker(Gemini("test", models, transport=transport), Places(ENTRIES + EXTRA))


def function(name, args, **extra):
    return {"functionCall": {"name": name, "args": args}, **extra}


def tool_answer(*parts):
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}


def test_models_are_pinned_even_with_legacy_env_aliases(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-lite-latest,gemini-flash-latest")
    assert Gemini.from_env().models == DEFAULT_MODELS.split(",")
    assert all("latest" not in model for model in Gemini("test").models)


def test_semantic_failure_retries_full_flash_using_voice_transcript():
    def reply(model, body):
        if model == "lite":
            return {**ROUTE, "intent": "unclear", "to": None, "heard": "от C12 до площади Виктории"}
        assert "inlineData" not in json.dumps(body)
        assert "от C12 до площади Виктории" in body["contents"][0]["parts"][0]["text"]
        return ROUTE
    transport = FakeTransport(reply)
    result = build(transport).ask(audio=WAV)
    assert result["kind"] == "route" and result["heard"] == "от C12 до площади Виктории"
    assert [m for m, _ in transport.calls] == ["lite", "flash"]


def test_both_names_missing_stays_travel_clarification_not_random_invention():
    transport = FakeTransport({"intent": "unclear", "missing": ["from", "to"]})
    result = build(transport).ask(text="выбери случайные точки")
    assert result["kind"] == "unclear" and result["missing"] == ["from", "to"]
    assert result["from"] is None and result["to"] is None


def test_function_search_and_submit_preserve_signatures_and_hide_coordinates():
    lookup = AskPlaces(Places(ENTRIES + EXTRA))
    start_id = lookup.search("C12")[0]["id"]
    state = {"tools": 0}
    def reply(model, body):
        if "tools" not in body:
            return {**ROUTE, "to": "площадь севернее", "ambiguity": ["to"]}
        state["tools"] += 1
        if state["tools"] == 1:
            return tool_answer(function("search_places", {"category": "square", "reference_id": lookup.search("Piața Victoriei")[0]["id"], "direction": "north"}, thoughtSignature="keep-me"))
        assert body["contents"][-2]["parts"][0]["thoughtSignature"] == "keep-me"
        tool_result = body["contents"][-1]["parts"][0]["functionResponse"]["response"]
        assert "lat" not in json.dumps(tool_result) and "lon" not in json.dumps(tool_result)
        ids = [p["id"] for p in tool_result["places"]]
        return tool_answer(function("submit_route", {**ROUTE, "from_id": start_id, "to": "площадь севернее", "ambiguity": ["to"], "to_candidates": ids}))
    result = build(FakeTransport(reply)).ask(text="от C12 к площади севернее центра", near=(45.7498, 21.2403))
    assert result["kind"] == "clarify" and result["ambiguity"] == ["to"]
    assert result["from"]["name"] == "Căminul C12 UVT"
    assert {p["name"] for p in result["candidates"]["to"]} == {"Piața Libertății", "Piața Unirii"}


def test_named_search_cannot_silently_pick_the_first_of_several_squares():
    asker = build(FakeTransport({**ROUTE, "to": "Piața"}))
    result = asker.ask(text="от C12 до площади")
    assert result["kind"] == "clarify" and len(result["candidates"]["to"]) == 3


def test_unknown_tool_cannot_execute_arbitrary_code():
    def reply(model, body):
        if "tools" in body:
            return tool_answer(function("execute_shell", {"cmd": "do something"}))
        return {**ROUTE, "to": None, "intent": "unclear"}
    result = build(FakeTransport(reply)).ask(text="от C12 куда-нибудь")
    assert result["kind"] == "unclear" and result["from"]["name"] == "Căminul C12 UVT"


def test_fabricated_ids_never_produce_routes():
    def reply(model, body):
        if "tools" in body:
            return tool_answer(function("submit_route", {**ROUTE, "to_id": "made_up"}))
        return {**ROUTE, "to_id": "made_up"}
    assert build(FakeTransport(reply)).ask(text="от C12 до площади")["kind"] != "route"


def test_fabricated_start_id_does_not_fall_back_to_current_location():
    form = {**ROUTE, "from": None, "from_id": "made_up"}
    a = build(FakeTransport(form))
    result = a.ask(text="от неизвестной точки до площади")
    assert result["kind"] != "route" and result["missing"] == ["from"]


def test_provider_failure_during_rescue_keeps_partial_result():
    def reply(model, body):
        if "tools" in body:
            raise AskError("ai_busy", 503)
        return {**ROUTE, "to": "Missing Place"}
    result = build(FakeTransport(reply)).ask(text="от C12 до неизвестного места")
    assert result["kind"] == "not_found" and result["from"]["name"] == "Căminul C12 UVT"


def test_empty_retry_cannot_erase_a_known_start_mode_and_time():
    def reply(model, body):
        if model == "lite":
            return {**ROUTE, "to": None, "intent": "unclear"}
        return {"intent": "unclear"}
    result = build(FakeTransport(reply)).ask(text="с C12 на велосипеде в 23:30 куда-нибудь")
    assert result["from"]["name"] == "Căminul C12 UVT" and result["mode"] == "bike"
    assert result["at"] == ROUTE["time"] and result["missing"] == ["to"]


def test_tool_turns_and_actual_provider_calls_are_bounded():
    def reply(model, body):
        if "tools" in body:
            return tool_answer(function("search_places", {"category": "square"}))
        return {**ROUTE, "to": None, "intent": "unclear"}
    transport = FakeTransport(reply)
    asker = build(transport)
    asker.provider_limiter = Limiter(5, 5)
    result = asker.ask(text="хочу куда-то", client="ip")
    assert result["kind"] == "clarify" and result["candidates"]["to"]
    assert len(transport.calls) == 2 + LIMITS["tool_rounds"]
    assert transport.calls[-1][1]["toolConfig"]["functionCallingConfig"]["allowedFunctionNames"] == ["submit_route"]
    # All five provider turns were charged, although this was just one submitted user request.
    with pytest.raises(AskError, match="too many"):
        asker.ask(text="другой запрос", client="ip")
    assert len(transport.calls) == 5


def test_off_topic_never_triggers_search_or_semantic_retry():
    transport = FakeTransport({**ROUTE, "intent": "off_topic"})
    assert build(transport).ask(text="рецепт печенья") == {"kind": "off_topic", "heard": ""}
    assert len(transport.calls) == 1


def test_unclear_forms_are_not_cached():
    transport = FakeTransport({**ROUTE, "to": None, "intent": "unclear", "time": None})
    asker = build(transport, models="single")
    asker.ask(text="куда-нибудь", client="first")
    before = len(transport.calls)
    asker.ask(text="куда-нибудь", client="second")
    assert len(transport.calls) > before


def test_local_search_aliases_directions_limits_and_invalid_arguments():
    lookup = AskPlaces(Places(ENTRIES + EXTRA))
    assert lookup.search("площадь Победы")[0]["name"] == "Piața Victoriei"
    reference = lookup.search("Piața Libertății")[0]["id"]
    assert [p["name"] for p in lookup.search(category="square", reference_id=reference, direction="north")] == ["Piața Unirii"]
    assert lookup.search(category="square", direction="north") == []
    assert len(lookup.search(category="square", limit=100)) <= 5
    assert lookup.tool({"query": [], "category": "square"}) == {"error": "invalid_arguments"}
    assert lookup.tool({"query": "C12", "cmd": "evil"}) == {"error": "invalid_arguments"}
    assert all("lat" not in entry for entry in lookup.catalog)


def test_clean_untrusted_clarification_fields():
    form = clean({"missing": ["to", "password"], "ambiguity": "from", "to_candidates": [123, "p_ok", {}]})
    assert form["missing"] == ["to"] and form["ambiguity"] == [] and form["to_candidates"] == ["p_ok"]


def test_spatial_constraint_cannot_be_dropped_to_a_generic_nearest_place():
    def reply(model, body):
        # Emulate a model losing "north of". Without verified search this must not become a route.
        if "tools" in body:
            return tool_answer(function("submit_route", {**ROUTE, "to": "Piața Victoriei"}))
        return {**ROUTE, "to": "Piața Victoriei"}
    result = build(FakeTransport(reply)).ask(text="от C12 до площади north of the university")
    assert result["kind"] == "clarify" and result["ambiguity"] == ["to"]


def test_upt_central_building_requires_confirmation_between_campus_and_rectorate():
    entries = ENTRIES + [
        {"k": "place", "n": "Universitatea Politehnica Timișoara", "lat": 45.746, "lon": 21.2276},
        {"k": "place", "n": "Rectoratul Universității Politehnica Timișoara", "lat": 45.7535, "lon": 21.2249},
    ]
    form = {**ROUTE, "from": "Universitatea Politehnica Timișoara"}
    a = Asker(Gemini("test", "single", transport=FakeTransport(form)), Places(entries))
    result = a.ask(text="от центрального корпуса Политеха до площади Виктории")
    assert result["kind"] == "clarify" and result["ambiguity"] == ["from"]
    assert len(result["candidates"]["from"]) == 2 and result["to"]["name"] == "Piața Victoriei"
