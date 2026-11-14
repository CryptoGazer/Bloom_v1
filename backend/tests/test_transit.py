"""On foot + public transport on a hand-made street and timetable. Run: .venv/bin/python -m pytest backend/tests -q

A lit street runs 2 km east from A (x=0) to B (x=2000). Stop S1 is 100 m from A, stop S2 100 m from B.
A tram goes S1 -> S2 in 5 minutes. Walking all the way takes about 25 minutes.
"""
import datetime as dt

import pytest

from backend.build_transit import stop_positions
from backend.routing import Network
from backend.tests.test_routing import ll, seg
from backend.transit import Timetable, Transit, cut

DAY = dt.date(2026, 11, 14)


def hms(h, m=0):
    return h * 3600 + m * 60


@pytest.fixture(scope="module")
def planner():
    net = Network([seg(f"s{i}", i, i + 1, [(i * 250, 0), ((i + 1) * 250, 0)], "lit_confirmed", "Strada Lungă") for i in range(8)],
                  {"as_of": "2026-11-14"})
    s1, s2 = ll(100, 5), ll(1900, 5)
    data = {
        "stops": {"S1": ["Stația Unu", s1[1], s1[0]], "S2": ["Stația Doi", s2[1], s2[0]]},
        "routes": {"R8": ["8", 0, "e3a900"]},
        "patterns": [["R8", "Spre Doi", ["S1", "S2"]], ["R8", "Spre Unu", ["S2", "S1"]]],
        "days": {
            "2026-11-14": [[0, [hms(22), hms(22, 5)]], [0, [hms(23, 30), hms(23, 35)]], [1, [hms(22, 10), hms(22, 15)]],
                           [0, [hms(24, 10), hms(24, 15)]]],
            "2026-11-15": [[0, [hms(6), hms(6, 5)]]],
        },
        "feed_of_day": {"2026-11-14": "4.31", "2026-11-15": "4.31"},
    }
    return Transit(net, Timetable(data))


def at(planner, x):
    lon, lat = ll(x, 0)
    return planner.net.snap(lat, lon)


def when(h, m=0, day=DAY):
    return dt.datetime.combine(day, dt.time(h % 24, m)) + (dt.timedelta(days=1) if h >= 24 else dt.timedelta())


def test_takes_the_next_tram_and_walks_lit_streets_to_and_from_the_stops(planner):
    r = planner.plan(at(planner, 0), at(planner, 2000), when(21, 50))
    assert r["kind"] == "ok"
    walk1, ride, walk2 = r["legs"]
    assert (walk1["type"], ride["type"], walk2["type"]) == ("walk", "ride", "walk")
    assert walk1["length_m"] == pytest.approx(100, abs=1) and walk2["length_m"] == pytest.approx(100, abs=1)
    assert (ride["line"], ride["from"]["name"], ride["to"]["name"], ride["dep"], ride["arr"]) == ("8", "Stația Unu", "Stația Doi", "22:00", "22:05")
    assert r["arrive_at"] == "22:06" and r["leave_at"] == "21:57"   # 74 s of walking + 1 min at the stop before 22:00
    assert r["last"] == {"line": "8", "stop": "Stația Unu", "time": "00:10", "missed": False}


def test_a_tram_that_leaves_before_you_reach_the_stop_is_not_offered(planner):
    # 100 m to the stop + 1 min margin: the 22:00 tram is gone; the next one, at 23:30, is more than 45 min away
    r = planner.plan(at(planner, 0), at(planner, 2000), when(21, 59))
    assert r["kind"] == "none" and r["reason"] == "no_trip_soon" and r["next"]["time"] == "23:30"
    assert planner.plan(at(planner, 0), at(planner, 2000), when(23, 0))["legs"][1]["dep"] == "23:30"


def test_after_midnight_trips_of_the_previous_service_day_count(planner):
    r = planner.plan(at(planner, 0), at(planner, 2000), when(24, 2))       # 00:02 on the 15th
    assert r["kind"] == "ok" and r["legs"][1]["dep"] == "00:10"


def test_no_more_trams_tonight_says_when_the_last_one_left_and_when_the_next_one_goes(planner):
    r = planner.plan(at(planner, 0), at(planner, 2000), when(24, 30))      # 00:30 on the 15th
    assert r["kind"] == "none" and r["reason"] == "no_trip_soon"
    assert r["last"]["time"] == "00:10" and r["next"]["time"] == "06:00"
    assert r["last"]["missed"] is True


def test_the_last_trip_you_can_no_longer_reach_is_marked_missed(planner):
    r = planner.plan(at(planner, 0), at(planner, 2000), when(24, 9))       # 00:09: the 00:10 tram leaves before you get there
    assert r["kind"] == "none" and r["last"] == {"line": "8", "stop": "Stația Unu", "time": "00:10", "missed": True}


def test_no_stop_within_walking_distance(planner):
    r = planner.plan(at(planner, 1000), at(planner, 1050), when(21, 50))   # both points 850-900 m from any stop
    assert r["kind"] == "none" and r["reason"] == "no_stop_near"


def test_cut_takes_the_line_between_two_distances():
    line = [ll(0, 0), ll(100, 0), ll(100, 100), ll(300, 100)]
    got = cut(line, 50, 250)
    assert got[0] == pytest.approx(ll(50, 0), abs=1e-6) and got[-1] == pytest.approx(ll(150, 100), abs=1e-6)
    assert ll(100, 0) in [pytest.approx(p, abs=1e-9) for p in got[1:-1]] and len(got) == 4


def test_stops_are_placed_along_the_line_in_trip_order():
    # the line goes east and comes back 20 m further north: the two stops at x=200 are on different legs
    line = [(0, 0), (1000, 0), (1000, 20), (0, 20)]
    assert stop_positions(line, [(200, 5), (800, 3), (800, 18), (200, 22)]) == pytest.approx([200, 800, 1220, 1820], abs=0.5)
    assert stop_positions(line, [(200, 5), (500, 300)]) is None                 # a stop far off the line: no shape


def test_the_ride_follows_the_line_shape(planner):
    s1, s2 = ll(100, 5), ll(1900, 5)
    shaped = Transit(planner.net, Timetable({
        "stops": {"S1": ["Stația Unu", s1[1], s1[0]], "S2": ["Stația Doi", s2[1], s2[0]]},
        "routes": {"R8": ["8", 0, "e3a900"]},
        "patterns": [["R8", "Spre Doi", ["S1", "S2"], [ll(100, 0), ll(1000, 300), ll(1900, 0)], [0, 1897.4]]],
        "days": {"2026-11-14": [[0, [hms(22), hms(22, 5)]]]},
    }))
    ride = shaped.plan(at(planner, 0), at(planner, 2000), when(21, 50))["legs"][1]
    assert len(ride["coords"]) == 3 and ride["coords"][1] == pytest.approx(ll(1000, 300), abs=1e-6)


def test_the_direction_of_travel_matters(planner):
    r = planner.plan(at(planner, 2000), at(planner, 0), when(22, 0))
    assert r["kind"] == "ok" and (r["legs"][1]["dep"], r["legs"][1]["headsign"]) == ("22:10", "Spre Unu")


def test_a_clock_time_well_before_now_means_tomorrow():
    from backend.app import leaving_time
    late = dt.datetime(2026, 11, 14, 23, 59)
    assert leaving_time("00:05", now=late) == dt.datetime(2026, 11, 15, 0, 5)      # after midnight, not this morning
    assert leaving_time("23:30", now=late) == dt.datetime(2026, 11, 14, 23, 30)    # half an hour ago: still today
    assert leaving_time("08:00", now=dt.datetime(2026, 11, 14, 7, 0)) == dt.datetime(2026, 11, 14, 8, 0)
