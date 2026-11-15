"""Loop walk through points (Network.loop and /api/loop) on the small network of test_routing.py:

    U(0,60) ------ UV ------ V(200,60)
      | SU                     | TV
    S(0,0) ------- ST ------- T(200,0)        P1 = (110, 0) on ST, P2 = (110, 60) on UV

Out from P1 the short way is by T (90 + 60 + 90 = 240 m); back, TV costs double, so the loop returns by S
(110 + 60 + 110 = 280 m): the whole rectangle, 520 m.
Run: .venv/bin/python -m pytest backend/tests -q
"""
import pytest

from backend.tests.test_routing import at, client, ll, net  # noqa: F401  (fixtures)


def ids(route):
    return [i for f in route["geometry"]["features"] for i in f["properties"]["ids"]]


def lat_lon(x, y):
    lon, lat = ll(x, y)
    return f"{lat},{lon}"


def test_the_loop_goes_out_one_side_and_comes_back_the_other(net):
    fast = net.loop([at(net, 110, 0), at(net, 110, 60)])["routes"]["fastest"]
    assert fast["length_m"] == pytest.approx(520, abs=1)
    assert {"TV", "SU"} <= set(ids(fast))


def test_the_loop_starts_and_ends_at_the_first_point_without_gaps(net):
    fast = net.loop([at(net, 110, 0), at(net, 110, 60)])["routes"]["fastest"]
    lines = [f["geometry"]["coordinates"] for f in fast["geometry"]["features"]]
    assert list(lines[0][0]) == pytest.approx(ll(110, 0), abs=1e-6)
    assert list(lines[-1][-1]) == pytest.approx(ll(110, 0), abs=1e-6)
    for before, after in zip(lines, lines[1:]):
        assert list(before[-1]) == pytest.approx(list(after[0]), abs=1e-6)


def test_the_same_point_twice_in_a_row_adds_nothing(net):
    once = net.loop([at(net, 110, 0), at(net, 110, 60)])["routes"]["fastest"]["length_m"]
    twice = net.loop([at(net, 110, 0), at(net, 110, 60), at(net, 110, 60)])["routes"]["fastest"]["length_m"]
    assert twice == pytest.approx(once, abs=0.5)


def test_a_loop_has_two_variants_and_a_verdict_like_a_route(net):
    plan = net.loop([at(net, 110, 0), at(net, 110, 60)])
    assert set(plan["routes"]) == {"fastest", "better_lit"}
    assert plan["verdict"]["kind"] in ("same", "show")
    for r in plan["routes"].values():
        assert "_key" not in r and "_sec" not in r


def test_api_loop_returns_the_loop_and_its_points(client):
    r = client.get("/api/loop", params={"points": f"{lat_lon(110, 0)};{lat_lon(110, 60)}", "mode": "walk"})
    assert r.status_code == 200
    body = r.json()
    assert body["loop"] is True and len(body["points"]) == 2
    assert body["from"] == body["to"] == body["points"][0]
    assert body["routes"]["fastest"]["length_m"] == pytest.approx(520, abs=1)


def test_api_loop_needs_2_to_10_points(client):
    one = lat_lon(110, 0)
    assert client.get("/api/loop", params={"points": one}).json()["detail"]["code"] == "bad_points"
    assert client.get("/api/loop", params={"points": ";".join([one] * 11)}).json()["detail"]["code"] == "bad_points"


def test_api_loop_names_the_point_outside_coverage(client):
    r = client.get("/api/loop", params={"points": f"{lat_lon(110, 0)};{lat_lon(5000, 5000)}"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "outside_coverage" and r.json()["detail"]["point"] == 2
