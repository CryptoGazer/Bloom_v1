"""Signs of life along a route: places open at that time, stops with departures, main roads. Hand-made data."""
import datetime as dt

import pytest

from backend.liveliness import Signs
from backend.routing import Network
from backend.tests.test_routing import ll, seg
from backend.transit import Timetable

FRI_2230 = dt.datetime(2026, 11, 13, 22, 30)
SAT_0300 = dt.datetime(2026, 11, 14, 3, 0)


def place(name, x, y, oh=None, c="amenity=bar"):
    lon, lat = ll(x, y)
    e = {"k": "place", "n": name, "c": c, "lat": lat, "lon": lon}
    if oh:
        e["oh"] = oh
    return e


@pytest.fixture(scope="module")
def signs():
    # a main road (secondary) 0..300 m, then a residential street 300..600 m
    net = Network([seg("main", 1, 2, [(0, 0), (300, 0)], "lit_confirmed", "Bulevardul Mare", hw="secondary"),
                   seg("side", 2, 3, [(300, 0), (600, 0)], "lit_confirmed", "Strada Mică")], {"as_of": "2026-11-13"})
    places = [place("Bar Deschis", 100, 30, "Mo-Su 18:00-02:00"),
              place("Profi", 400, 20, "24/7", "shop=convenience"),
              place("Cafenea", 200, 20, "Mo-Fr 08:00-18:00", "amenity=cafe"),
              place("Bar Departe", 100, 90, "Mo-Su 18:00-02:00"),
              place("Fără orar", 150, 10),
              place("Galerie", 120, 10, "24/7", "tourism=gallery")]       # open, but not a place with people
    s = ll(500, 40)
    tt = Timetable({"stops": {"S": ["Stația Mică", s[1], s[0]]}, "routes": {"R": ["8", 0, "e3a900"]},
                    "patterns": [["R", "Spre Nord", ["S"]]],
                    "days": {"2026-11-13": [[0, [81000]], [0, [84600]]]}})   # 22:30 and 23:30
    return Signs(net, places, tt), net


def route(net, mode="walk"):
    a, b = ll(0, 0), ll(600, 0)
    return net.plan(net.snap(a[1], a[0]), net.snap(b[1], b[0]))["routes"]["fastest"]


def test_open_places_near_the_route_at_that_time(signs):
    s, net = signs
    got = s.along(route(net), FRI_2230)
    assert [p["name"] for p in got["open_places"]] == ["Bar Deschis", "Profi"]   # cafe closed, far bar and no-hours place left out
    assert got["open_places"][1]["always"] is True and got["places_unknown_hours"] == 1


def test_after_three_only_the_all_night_shop(signs):
    s, net = signs
    assert [p["name"] for p in s.along(route(net), SAT_0300)["open_places"]] == ["Profi"]


def test_stops_with_departures_within_ten_minutes(signs):
    s, net = signs
    got = s.along(route(net), FRI_2230)
    assert got["stops"] == [{"name": "Stația Mică", "departures": [{"line": "8", "time": "22:30"}]}]
    assert s.along(route(net), dt.datetime(2026, 11, 13, 23, 0))["stops"] == []


def test_share_of_the_way_on_main_roads(signs):
    s, net = signs
    assert s.along(route(net), FRI_2230)["main_share"] == pytest.approx(0.5, abs=0.03)
