"""Routing and API on a small hand-made network. Run: .venv/bin/python -m pytest backend/tests -q

Layout in metres (x east, y north) around 45.75 N, 21.23 E:

    U(0,60) ---- lit, 200 m ---- V(200,60)
      | lit 60 m                   | lit 60 m
    S(0,0) --- reported dark, 200 m --- T(200,0) --- likely lit, 100 m --- W(300,0)

plus an island far from everything and a road closed to pedestrians from T.
"""
import gzip
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.routing import KX, KY, Network

LAT0, LON0 = 45.75, 21.23


def ll(x, y):
    return [round(LON0 + x / KX, 7), round(LAT0 + y / KY, 7)]


def seg(sid, u, v, pts, status, name=None, **tags):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [ll(*p) for p in pts]},
            "properties": {"id": sid, "u": u, "v": v, "kind": "street", "hw": "residential", "name": name, "len": 0,
                           "status": status, "conf": 1, "ev": [{"s": "osm", "k": "yes", "ways": [1]}], **tags}}


FEATURES = [
    seg("ST", 1, 2, [(0, 0), (200, 0)], "dark_reported", "Strada Directă"),
    seg("SU", 1, 3, [(0, 0), (0, 60)], "lit_confirmed", "Strada Vest"),
    seg("UV", 3, 4, [(0, 60), (100, 60), (200, 60)], "lit_confirmed", "Strada Luminată"),
    seg("TV", 2, 4, [(200, 0), (200, 60)], "lit_confirmed", "Strada Est"),
    seg("TW", 2, 5, [(200, 0), (300, 0)], "lit_likely", "Strada Lungă"),
    seg("island", 90, 91, [(140, -40), (160, -40)], "lit_confirmed", "Insula"),
    seg("nofoot", 2, 6, [(200, 0), (200, -200)], "lit_confirmed", "Drum Interzis", foot="no"),
]


@pytest.fixture(scope="module")
def net():
    return Network(FEATURES, {"as_of": "2026-11-14"})


def at(net, x, y):
    lon, lat = ll(x, y)
    return net.snap(lat, lon)


def test_fastest_takes_the_dark_shortcut_and_lit_route_goes_around(net):
    plan = net.plan(at(net, 0, 0), at(net, 200, 0))
    fastest, lit = plan["routes"]["fastest"], plan["routes"]["better_lit"]
    assert fastest["length_m"] == pytest.approx(200, abs=0.5)
    assert fastest["by_status_m"]["dark_reported"] == pytest.approx(200, abs=0.5)
    assert lit["length_m"] == pytest.approx(320, abs=0.5)
    assert lit["by_status_m"]["lit_confirmed"] == pytest.approx(320, abs=0.5)
    assert lit["streets"] == ["Strada Vest", "Strada Luminată", "Strada Est"]


def test_verdict_and_warning_follow_the_spec_thresholds(net):
    plan = net.plan(at(net, 0, 0), at(net, 200, 0))
    # 120 m extra, 60% longer than the fastest route: the lit route is still offered, however much longer
    assert plan["verdict"]["kind"] == "show"
    assert plan["verdict"]["extra_share"] == pytest.approx(0.6, abs=0.01)
    assert plan["routes"]["fastest"]["warn"] is True       # 200 m of "reported dark" in one stretch
    assert plan["routes"]["fastest"]["max_dark_run_m"] == pytest.approx(200, abs=0.5)
    assert plan["routes"]["better_lit"]["warn"] is False


def test_same_route_when_nothing_is_gained(net):
    plan = net.plan(at(net, 0, 60), at(net, 200, 60))
    assert plan["verdict"] == {"kind": "same"}
    assert plan["routes"]["fastest"]["length_m"] == pytest.approx(200, abs=0.5)


def detour_network(common_m, straight_m, straight_status, bump_m):
    """A long lit street, then a choice: straight on (straight_status) or a slightly longer lit detour."""
    end, mid = common_m + straight_m, common_m + straight_m / 2
    return Network([
        seg("C", 1, 2, [(0, 0), (common_m, 0)], "lit_confirmed", "Strada Comună"),
        seg("straight", 2, 3, [(common_m, 0), (end, 0)], straight_status, "Strada Dreaptă"),
        seg("d1", 2, 4, [(common_m, 0), (mid, bump_m)], "lit_confirmed", "Ocol"),
        seg("d2", 4, 3, [(mid, bump_m), (end, 0)], "lit_confirmed", "Ocol"),
    ], {"as_of": "2026-11-14"})


def test_nearly_identical_routes_are_shown_as_one():
    # 1020 m; the lit route swaps 20 m of "probably lit" for a 0.4 m longer lit detour: 2% gain, not worth a second card
    near = detour_network(1000, 20, "lit_likely", 2)
    plan = near.plan(at(near, 0, 0), at(near, 1020, 0))
    assert plan["routes"]["fastest"]["streets"] != plan["routes"]["better_lit"]["streets"]
    assert plan["verdict"]["kind"] == "same" and plan["verdict"]["near"] is True
    assert plan["verdict"]["lit_gain"] == pytest.approx(0.02, abs=0.005)


def test_a_better_lit_route_that_costs_no_time_replaces_the_fastest():
    # 300 m "probably lit" straight on, or a lit detour 2 m longer: the lit one wins outright, one card
    free = detour_network(1000, 300, "lit_likely", 17)
    plan = free.plan(at(free, 0, 0), at(free, 1300, 0))
    assert plan["routes"]["fastest"]["by_status_m"]["lit_likely"] == pytest.approx(300, abs=1)
    assert plan["verdict"]["kind"] == "same" and plan["verdict"]["pick"] == "better_lit"


def test_removing_a_long_dark_stretch_is_always_worth_showing():
    # only 3.6% of 4150 m changes, but the fastest route has 150 m of "reported dark" in one stretch;
    # the lit detour costs 42 m (31 s): both routes are offered
    dark = detour_network(4000, 150, "dark_reported", 60)
    plan = dark.plan(at(dark, 0, 0), at(dark, 4150, 0))
    assert plan["routes"]["fastest"]["warn"] is True and plan["routes"]["better_lit"]["warn"] is False
    assert plan["verdict"]["kind"] == "show"
    # a detour of 1 m: only the lit route is offered
    cheap = detour_network(4000, 150, "dark_reported", 10)
    assert cheap.plan(at(cheap, 0, 0), at(cheap, 4150, 0))["verdict"]["pick"] == "better_lit"


def test_darkness_never_blocks_a_route(net):
    # the only way to the middle of the dark street is along it
    plan = net.plan(at(net, 0, 60), at(net, 100, 0))
    assert plan["routes"]["better_lit"]["by_status_m"]["dark_reported"] == pytest.approx(100, abs=0.5)


def test_points_on_one_segment(net):
    plan = net.plan(at(net, 220, 0), at(net, 290, 0))
    assert plan["routes"]["fastest"]["length_m"] == pytest.approx(70, abs=0.5)
    assert plan["routes"]["fastest"]["by_status_m"]["lit_likely"] == pytest.approx(70, abs=0.5)


def test_route_geometry_is_continuous_and_adds_up(net):
    route = net.plan(at(net, 30, 0), at(net, 250, 0))["routes"]["better_lit"]
    pieces = route["geometry"]["features"]
    for prev, cur in zip(pieces, pieces[1:]):
        assert prev["geometry"]["coordinates"][-1] == cur["geometry"]["coordinates"][0]
    assert sum(p["properties"]["len"] for p in pieces) == pytest.approx(route["length_m"], abs=0.5)
    assert sum(route["by_status_m"].values()) == pytest.approx(route["length_m"], abs=0.5)


def test_snap_projects_onto_the_network_and_rejects_far_points(net):
    snap = at(net, 100, 20)
    assert net.props[snap.seg]["id"] == "ST" and snap.d == pytest.approx(20, abs=0.5) and snap.t == pytest.approx(100, abs=0.5)
    assert at(net, 100, 1000) is None
    lon, lat = ll(100, 1000)
    assert net.nearest_m(lat, lon) == pytest.approx(940, abs=1)


def test_islands_and_no_foot_roads_are_not_used(net):
    assert net.props[at(net, 150, -38).seg]["id"] == "ST"      # the island is 2 m away, the main network 38 m
    assert net.props[at(net, 205, -100).seg]["id"] != "nofoot"
    assert net.routable[net.by_id["island"]] is False and net.routable[net.by_id["nofoot"]] is False


def test_segments_in_bbox(net):
    west, south = ll(-10, 50)
    east, north = ll(210, 70)
    ids = {net.props[i]["id"] for i in net.segments_in_bbox(west, south, east, north)}
    assert ids == {"SU", "UV", "TV"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("city") / "segments.geojson.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "meta": {"as_of": "2026-11-14"}, "features": FEATURES}, f)
    lon, lat = ll(0, 60)
    with gzip.open(path.parent / "places.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"meta": {}, "entries": [{"k": "street", "n": "Strada Vest", "lat": lat, "lon": lon}]}, f)
    (x1_lon, x1_lat), (x2_lon, x2_lat) = ll(0, 62), ll(200, 62)
    with gzip.open(path.parent / "transit.json.gz", "wt", encoding="utf-8") as f:   # a tram from U to V at 22:00
        json.dump({"stops": {"X1": ["Stația U", x1_lat, x1_lon], "X2": ["Stația V", x2_lat, x2_lon]},
                   "routes": {"R1": ["1", 0, "e3a900"]}, "patterns": [["R1", "Spre V", ["X1", "X2"]]],
                   "days": {"2026-11-14": [[0, [79200, 79320]]]}, "feed_of_day": {"2026-11-14": "4.31"}}, f)
    with TestClient(create_app(path)) as c:
        yield c


def test_api_geocode(client):
    body = client.get("/api/geocode", params={"q": "str vest"}).json()
    assert [r["name"] for r in body["results"]] == ["Strada Vest"]
    assert client.get("/api/geocode", params={"q": "x"}).json()["results"] == []


def point(x, y):
    lon, lat = ll(x, y)
    return f"{lat},{lon}"


def test_api_route(client):
    r = client.get("/api/route", params={"from": point(0, 0), "to": point(200, 0)})
    assert r.status_code == 200
    body = r.json()
    assert body["routes"]["better_lit"]["length_m"] == pytest.approx(320, abs=0.5)
    assert body["verdict"]["kind"] == "show" and body["data_as_of"] == "2026-11-14"
    assert body["from"]["snap_m"] == pytest.approx(0, abs=0.5)


def test_api_route_by_bike_and_unknown_modes(client):
    body = client.get("/api/route", params={"from": point(0, 0), "to": point(200, 0), "mode": "bike"}).json()
    assert body["mode"] == "bike" and body["routes"]["fastest"]["minutes"] == pytest.approx(200 / 4.2 / 60, abs=0.1)
    r = client.get("/api/route", params={"from": point(0, 0), "to": point(200, 0), "mode": "car"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "mode_not_supported"


def test_api_route_on_foot_plus_transit(client):
    body = client.get("/api/route", params={"from": point(0, 0), "to": point(200, 0), "mode": "transit", "at": "2026-11-14T21:55"}).json()
    assert body["mode"] == "transit" and body["at"] == "2026-11-14 21:55"
    assert "fastest" in body["routes"] and body["transit"]["kind"] == "ok"
    ride = body["transit"]["legs"][1]
    assert (ride["line"], ride["dep"], ride["arr"], ride["from"]["name"]) == ("1", "22:00", "22:02", "Stația U")
    assert client.get("/api/route", params={"from": point(0, 0), "to": point(200, 0), "mode": "transit", "at": "nonsense"}).status_code == 422


def test_api_route_outside_coverage(client):
    r = client.get("/api/route", params={"from": point(0, 0), "to": point(100, 1000)})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "outside_coverage" and r.json()["detail"]["point"] == "to"
    assert client.get("/api/route", params={"from": "abc", "to": point(0, 0)}).json()["detail"]["code"] == "bad_point"


def test_api_segments(client):
    west, south = ll(-10, 50)
    east, north = ll(210, 70)
    r = client.get("/api/segments", params={"bbox": f"{west},{south},{east},{north}"}).json()
    assert r["count"] == 3 and r["truncated"] is False
    assert "ev" not in r["features"][0]["properties"]            # the list is lean; evidence comes by id
    r = client.get("/api/segments", params={"bbox": f"{west},{south},{east},{north}", "limit": 2}).json()
    assert r["count"] == 3 and r["truncated"] is True and r["features"] == []
    assert client.get("/api/segments/UV").json()["properties"]["ev"][0]["s"] == "osm"
    assert client.get("/api/segments/nope").status_code == 404
