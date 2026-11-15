"""Loop intent, local place trust, automatic street points and the full ask -> loop API contract."""
import gzip
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ask import Asker, Gemini, clean
from backend.geocode import Places
from backend.loops import around
from backend.routing import Network
from backend.tests.test_ask import ENTRIES, WAV, FakeTransport
from backend.tests.test_ask_grounding import EXTRA, function, tool_answer
from backend.tests.test_routing import LAT0, LON0, ll, seg

FORM = {"intent": "loop", "to": "Piața Libertății", "from_here": False,
        "mode": "unspecified", "heard": "", "radius_m": 400}


def build(form):
    transport = FakeTransport(form)
    return Asker(Gemini("test", "single", transport=transport), Places(ENTRIES + EXTRA)), transport


def test_loop_resolves_a_real_centre_and_caches_the_form_without_user_coordinates():
    asker, transport = build(FORM)
    a = asker.ask(text="Обойди центр", near=(LAT0, LON0))
    b = asker.ask(text="обойди центр", near=(LAT0 + .01, LON0))
    assert a == b and a["kind"] == "loop" and a["loop"] is True
    assert a["to"]["name"] == "Piața Libertății" and a["mode"] == "walk" and a["radius_m"] == 400
    assert a["from"] is None and len(transport.calls) == 1
    assert str(LAT0) not in json.dumps(transport.calls)


def test_loop_voice_preserves_transcript_and_explicit_start_date_bike_and_radius():
    asker, _ = build({**FORM, "from": "Căminul C12", "mode": "bike", "radius_m": 700,
                      "time": "2026-11-16T00:20", "heard": "с C12 по кругу вокруг центра завтра в 00:20"})
    r = asker.ask(audio=WAV)
    assert r["kind"] == "loop" and r["from"]["name"] == "Căminul C12 UVT"
    assert r["mode"] == "bike" and r["at"] == "2026-11-16T00:20" and r["radius_m"] == 700
    assert r["heard"] == "с C12 по кругу вокруг центра завтра в 00:20"


def test_returning_to_start_does_not_invent_geolocation_start_or_time_and_short_means_short():
    # A real voice response invented all three fields; the transcript contains none of them.
    asker, _ = build({**FORM, "from_here": True, "from": "Piața Libertății", "radius_m": 400,
                      "time": "2026-11-15T05:37", "heard": "Построй небольшую круговую прогулку вокруг центра с возвратом к началу"})
    r = asker.ask(audio=WAV)
    assert r["kind"] == "loop" and r["from_here"] is False and r["from"] is None
    assert r["at"] is None and r["radius_m"] == 200


@pytest.mark.parametrize("text", ["Прогулка вокруг меня, отсюда и обратно", "A short walk around me, from here and back", "Un circuit în jurul meu, de aici"])
def test_explicit_location_is_preserved_but_a_model_named_start_is_not(text):
    asker, _ = build({**FORM, "to": None, "from_here": True, "from": "Piața Libertății"})
    r = asker.ask(text=text)
    assert r["kind"] == "loop" and r["from_here"] and r["from"] is None


def test_loop_around_here_needs_browser_location_not_an_invented_centre():
    asker, _ = build({**FORM, "to": None, "from_here": True})
    r = asker.ask(text="Прогулка вокруг меня")
    assert r["kind"] == "loop" and r["to"] is None and r["from_here"] is True


def test_unknown_loop_centre_keeps_loop_intent_and_offers_only_verified_candidates():
    asker, _ = build({**FORM, "to": "Piața", "ambiguity": ["to"]})
    r = asker.ask(text="Обойди какую-нибудь площадь")
    assert r["kind"] == "clarify" and r["loop"] is True and r["radius_m"] == 400
    assert r["to"] is None and len(r["candidates"]["to"]) >= 2
    assert all(asker.lookup.get(p["id"]) for p in r["candidates"]["to"])


def test_fake_loop_centre_id_cannot_create_a_route():
    asker, _ = build({**FORM, "to_id": "p_invented"})
    assert asker.ask(text="Круг вокруг неизвестного здания")["kind"] != "loop"


def test_function_search_cannot_erase_the_loop_or_its_radius():
    count = [0]
    def reply(model, body):
        if "tools" not in body:
            return {**FORM, "to": "somewhere", "radius_m": 700}
        count[0] += 1
        if count[0] == 1:
            return tool_answer(function("search_places", {"query": "Piața Libertății", "side": "to"}))
        return tool_answer(function("submit_route", {"intent": "route", "to": "Piața Libertății"}))
    asker, _ = build(reply)
    r = asker.ask(text="Замкнутая прогулка вокруг большой площади")
    assert r["kind"] == "loop" and r["radius_m"] == 700 and count[0] == 2


@pytest.mark.parametrize("radius", [True, False, "600", -1, 0, 99, 1201, float("inf"), float("nan"), {}])
def test_untrusted_radius_is_never_used_outside_bounds(radius):
    assert clean({**FORM, "radius_m": radius})["radius_m"] is None


def test_transit_loop_is_explicitly_unsupported_and_off_topic_stays_filtered():
    asker, _ = build({**FORM, "mode": "transit"})
    assert asker.ask(text="круг на трамвае") == {"kind": "unsupported", "reason": "loop_transit", "heard": ""}
    asker, _ = build({**FORM, "intent": "off_topic"})
    assert asker.ask(text="напиши пузырьковую сортировку") == {"kind": "off_topic", "heard": ""}


@pytest.mark.parametrize('intent', ['route', 'unclear', 'loop'])
def test_explicit_loop_cannot_collapse_to_two_random_endpoints(intent):
    asker, _ = build({**FORM, 'intent': intent, 'from': 'Căminul C12', 'to': 'Piața Victoriei'})
    r = asker.ask(text='Создай общий круговой маршрут для прогулки по Тимишоаре')
    assert r['kind'] == 'loop' and r['from'] is None and r['to']['name'] == 'Piața Libertății'


@pytest.mark.parametrize('intent', ['route', 'unclear', 'loop'])
def test_three_named_places_are_preserved_in_order_even_if_model_drops_them(intent):
    asker, _ = build({**FORM, 'intent': intent, 'from': 'Căminul C12', 'to': 'Piața Victoriei'})
    r = asker.ask(text='Сделай круговой маршрут через Piața Victoriei, Piața Unirii и Piața Libertății')
    assert r['kind'] == 'loop' and [p['name'] for p in r['points']] == ['Piața Victoriei', 'Piața Unirii', 'Piața Libertății']


def test_one_unknown_intermediate_point_does_not_drop_known_points():
    asker, _ = build({**FORM, 'waypoints': [
        {'query': 'Piața Victoriei', 'name': 'Piața Victoriei'},
        {'query': 'Несуществующее место', 'name': 'Несуществующее место'},
        {'query': 'Piața Unirii', 'name': 'Piața Unirii'}]})
    r = asker.ask(text='Круговой маршрут через Piața Victoriei, Несуществующее место и Piața Unirii')
    assert r['kind'] == 'clarify' and r['points'][0]['name'] == 'Piața Victoriei' and r['points'][2]['name'] == 'Piața Unirii'
    assert r['points'][1] is None and r['point_issues'][0]['index'] == 1


def test_invented_intermediate_point_and_excessive_lists_are_not_silently_routed():
    asker, _ = build({**FORM, 'waypoints': [{'query': 'Piața Victoriei', 'name': 'Piața Victoriei'}, {'query': 'Piața Unirii', 'name': 'Piața Unirii'}]})
    r = asker.ask(text='Круговой маршрут через Piața Victoriei и другое неизвестное место')
    assert r['kind'] == 'clarify' and r['points'][1] is None
    asker, _ = build({**FORM, 'waypoints': [{'query': 'Piața Victoriei', 'name': 'Piața Victoriei'}] * 11})
    # Explicitly distinct requested entries must be rejected, not truncated into a different loop.
    asker.gemini.transport.form['waypoints'][-1] = {'query': 'Căminul C12', 'name': 'Căminul C12'}
    assert asker.ask(text='Круговой маршрут: Piața Victoriei, Căminul C12')['reason'] == 'loop_points_limit'


@pytest.fixture(scope="module")
def grid():
    features = []
    values = range(-600, 601, 200)
    for i, x in enumerate(values):
        for j, y in enumerate(values):
            for dx, dy in ((200, 0), (0, 200)):
                if x + dx <= 600 and y + dy <= 600:
                    u, v = i * 7 + j, (i + dx // 200) * 7 + j + dy // 200
                    features.append(seg(f"edge_{u}_{v}", u, v, [(x, y), (x + dx, y + dy)], "lit_confirmed"))
    features.append(seg("closed", 100, 101, [(-400, -400), (400, 400)], "lit_confirmed", foot="no", bicycle="no"))
    return features


@pytest.mark.parametrize("mode", ["walk", "bike"])
def test_generated_circuit_closes_surrounds_centre_and_stays_on_accessible_network(grid, mode):
    net = Network(grid)
    points, plan, radius = around(net, (LAT0, LON0), 400, mode)
    assert 4 <= len(points) <= 9 and radius == 400
    assert min(p.lat for p in points) < LAT0 < max(p.lat for p in points)
    assert min(p.lon for p in points) < LON0 < max(p.lon for p in points)
    for route in plan["routes"].values():
        features = route["geometry"]["features"]
        assert features[0]["geometry"]["coordinates"][0] == pytest.approx(features[-1]["geometry"]["coordinates"][-1], abs=1e-6)
        assert route["length_m"] > 1000 and route["minutes"] > 0
        assert all("closed" not in f["properties"]["ids"] for f in features)
        for a, b in zip(features, features[1:]):
            assert a["geometry"]["coordinates"][-1] == pytest.approx(b["geometry"]["coordinates"][0], abs=1e-6)


def test_a_corridor_or_an_edge_without_space_is_not_an_invented_circle():
    net = Network([seg("line", 1, 2, [(-600, 0), (600, 0)], "lit_confirmed")])
    assert around(net, (LAT0, LON0), 400) is None


@pytest.fixture()
def circuit_city(tmp_path, grid, monkeypatch):
    monkeypatch.setenv("TIGER_HISTORY", "off")
    for name, data in (("segments.geojson.gz", {"features": grid, "meta": {}}),
                       ("places.json.gz", {"entries": [{"k": "street", "n": "Piața Libertății", "lat": LAT0, "lon": LON0}]})):
        with gzip.open(tmp_path / name, "wt", encoding="utf-8") as out:
            json.dump(data, out)
    return tmp_path / "segments.geojson.gz"


def test_ask_to_generated_loop_api_and_explicit_start(circuit_city):
    with TestClient(create_app(circuit_city, gemini=Gemini("test", "single", transport=FakeTransport(FORM)))) as client:
        r = client.post("/api/ask", json={"text": "Обойди центр"}).json()
        assert r["kind"] == "loop"
        p = r["to"]
        lon, lat = ll(-500, -200)
        response = client.get("/api/loop", params={"center": f"{p['lat']},{p['lon']}", "radius_m": r["radius_m"],
                                                   "mode": r["mode"], "start": f"{lat},{lon}", "at": "2026-11-16T00:20"})
        assert response.status_code == 200
        body = response.json()
        assert body["generated"] and body["loop"] and body["from"] == body["to"]
        assert body["points"][0]["lat"] == lat and body["points"][0]["lon"] == lon
        assert body["at"] == "2026-11-16 00:20"
        assert all(p["snap_m"] == 0 for p in body["points"][1:])
        assert len(body["points"]) <= 10


def test_auto_loop_api_validates_bounds_and_conflicting_arguments(circuit_city):
    center = f"{LAT0},{LON0}"
    with TestClient(create_app(circuit_city)) as client:
        for args in ({"center": center, "radius_m": 0}, {"center": center, "radius_m": 999999},
                     {"center": center, "mode": "transit"}, {"center": center, "points": center + ";" + center},
                     {"center": "nan,0"}, {"center": center, "start": "0,0"}, {"start": center}):
            assert client.get("/api/loop", params=args).status_code == 422
        assert client.get("/api/loop", params={"center": "0,0"}).json()["detail"]["code"] == "outside_coverage"
