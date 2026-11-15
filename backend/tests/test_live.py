"""Live vehicles: shared cache, honest freshness, a planned trip found by its trip id.
Run: .venv/bin/python -m pytest backend/tests -q"""
import datetime as dt
import io
import urllib.error
from zoneinfo import ZoneInfo

import pytest

from backend.live import LIVE, Live, Vehicles, epoch
from backend.tests.test_transit import planner, at, when  # noqa: F401  (fixture)
from backend.transit import Timetable, Transit

NOW = 1_800_000_000.0
TZ = ZoneInfo("Europe/Bucharest")


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class Feed:
    """Fake city server: answers from a list, raising the exceptions in it."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self):
        self.calls += 1
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return a


def car(**kw):
    v = {"id": "GLJ", "routeId": "R16", "tripId": "16.1_T_01", "directionId": 1, "headsign": "Girație Sudului",
         "lat": 45.75, "lon": 21.23, "bearing": 180, "speed": 0, "stopId": "S1", "stopSequence": 3,
         "status": "IN_TRANSIT_TO", "delaySec": 120, "updatedAt": NOW - 10, "wheelchair": True}
    v.update(kw)
    return v


TT = Timetable({"stops": {"S1": ["Piața Huniade", 45.75, 21.23], "S2": ["Complexul Studențesc", 45.74, 21.24]},
                "routes": {"R16": ["16", 11, "6f2095"]},
                "patterns": [["R16", "Girație Sudului", ["S1", "S2"]]],
                "days": {"2026-11-14": [[0, [81300, 81720], "16.1_T_01", 4]]},
                "feed_of_day": {"2026-11-14": "4.31"},
                # one vehicle runs P_00, P_01, then our T_01 (starts 81000, 100 s after P_01 ends), then L_01
                "blocks": {"4.31": {"16.1_P_00": ["BL1", 75000, 77000], "16.1_P_01": ["BL1", 78000, 80900],
                                    "16.1_T_01": ["BL1", 81000, 82000], "16.1_L_01": ["BL1", 83000, 84000],
                                    "33.1_X": ["BL9", 80000, 81000]}}})


def live(*answers, clock=None):
    clock = clock or Clock()
    return Live(Vehicles(Feed(*answers), clock=clock), TT, clock=clock)


# ---------- the shared cache ----------

def test_the_city_server_is_asked_once_per_refresh_interval_whatever_the_traffic():
    clock, feed = Clock(), Feed({"vehicles": [car()], "refreshInSec": 3})
    v = Vehicles(feed, clock=clock)
    for _ in range(5):
        v.snapshot()
    assert feed.calls == 1
    clock.t += LIVE["refresh_s"] - 1
    v.snapshot()
    assert feed.calls == 1
    clock.t += 1
    v.snapshot()
    assert feed.calls == 2


def test_a_longer_interval_asked_by_the_server_is_respected():
    clock, feed = Clock(), Feed({"vehicles": [], "refreshInSec": 40})
    v = Vehicles(feed, clock=clock)
    v.snapshot()
    clock.t += 30
    v.snapshot()
    assert feed.calls == 1


def test_after_a_failure_the_old_copy_stays_as_old_as_it_is_and_retries_back_off():
    clock = Clock()
    feed = Feed({"vehicles": [car()]}, OSError("down"), OSError("down"), OSError("down"))
    v = Vehicles(feed, clock=clock)
    first = v.snapshot()
    clock.t += LIVE["refresh_s"]
    s = v.snapshot()
    assert s["error"] == "OSError" and s["fetched_at"] == first["fetched_at"] and len(s["vehicles"]) == 1
    clock.t += LIVE["refresh_s"]          # first back-off is refresh_s, the second twice that
    v.snapshot()
    calls = feed.calls
    clock.t += LIVE["refresh_s"]
    v.snapshot()
    assert feed.calls == calls            # still waiting
    clock.t += LIVE["refresh_s"]
    v.snapshot()
    assert feed.calls == calls + 1


def test_too_many_requests_waits_as_long_as_the_server_says():
    clock = Clock()
    busy = urllib.error.HTTPError(LIVE["url"], 429, "Too Many Requests", {"Retry-After": "100"}, io.BytesIO())
    feed = Feed(busy, {"vehicles": []})
    v = Vehicles(feed, clock=clock)
    assert v.snapshot()["error"] == "http_429"
    clock.t += 99
    v.snapshot()
    assert feed.calls == 1
    clock.t += 1
    assert v.snapshot()["error"] is None


def test_an_unexpected_answer_is_a_failure_not_an_empty_city():
    v = Vehicles(Feed({"message": "maintenance"}), clock=Clock())
    s = v.snapshot()
    assert s["error"] == "ValueError" and s["fetched_at"] is None


# ---------- vehicles ----------

def test_a_vehicle_carries_its_line_colour_and_the_age_of_its_own_gps_point():
    v = live({"vehicles": [car(updatedAt=NOW - 10)]}).answer()["vehicles"][0]
    assert (v["line"], v["route_type"], v["color"], v["stop"]) == ("16", "trolleybus", "#6f2095", "Piața Huniade")
    assert v["age_s"] == 10 and v["live"] is True and v["delay_s"] == 120 and v["wheelchair"] is True


def test_an_old_gps_point_is_not_live_even_in_a_fresh_answer():
    v = live({"vehicles": [car(updatedAt=NOW - LIVE["stale_s"] - 1)]}).answer()["vehicles"][0]
    assert v["live"] is False


def test_unknown_and_implausible_delays_are_not_shown_as_delays():
    vs = live({"vehicles": [car(id="a", delaySec=None), car(id="b", delaySec=6496), car(id="c", delaySec=-120)]}).answer()["vehicles"]
    assert [v["delay_s"] for v in vs] == [None, None, -120]


def test_a_line_missing_from_the_timetable_still_gets_a_number():
    v = live({"vehicles": [car(routeId="R_AB_5C")]}).answer()["vehicles"][0]
    assert v["line"] == "5C" and v["color"] == "#555555"


def test_only_vehicles_around_the_area_and_of_the_asked_line_are_listed():
    far = car(id="far", lat=45.90)
    other = car(id="other", routeId="R_AB_33", tripId="33.1")
    a = live({"vehicles": [car(), far, other]})
    assert [v["id"] for v in a.answer()["vehicles"]] == ["GLJ", "other"]
    assert [v["id"] for v in a.answer(route="R16")["vehicles"]] == ["GLJ"]


# ---------- a planned trip ----------

DEP = NOW + 6 * 60     # scheduled at the boarding stop in 6 minutes; boarding stop sequence 4


def trip(*vehicles, dep=DEP, seq=4):
    return live({"vehicles": list(vehicles)}).answer(trip="16.1_T_01", seq=seq, dep=dep)["trip"]


def test_live_forecast_is_the_timetable_plus_the_reported_delay():
    t = trip(car(delaySec=120, stopSequence=3, status="IN_TRANSIT_TO"))
    assert t["status"] == "live" and t["delay_s"] == 120
    assert t["expected_ts"] == DEP + 120 and t["eta_s"] == 8 * 60
    assert t["stops_away"] == 2    # heading to stop 3, yours is 4


def test_an_early_vehicle_gives_an_earlier_time():
    t = trip(car(delaySec=-90))
    assert t["status"] == "live" and t["eta_s"] == 6 * 60 - 90


def test_standing_at_your_stop_is_zero_stops_away():
    assert trip(car(stopSequence=4, status="STOPPED_AT"))["stops_away"] == 0
    assert trip(car(stopSequence=4, status="IN_TRANSIT_TO"))["stops_away"] == 1


def test_a_vehicle_past_your_stop_is_passed():
    assert trip(car(stopSequence=5))["status"] == "passed"


def test_no_vehicle_on_the_trip_or_its_block_keeps_the_timetable():
    assert trip(car(tripId="16.1_T_02"))["status"] == "no_vehicle"
    assert trip(car(tripId="33.1_X"))["status"] == "no_vehicle"


def test_the_vehicle_finishing_the_trip_before_ours_gives_a_forecast_when_its_delay_eats_the_layover():
    t = trip(car(tripId="16.1_P_01", headsign="T. Grozăvescu", delaySec=300))
    assert t["status"] == "previous_trip" and t["trips_before"] == 1 and t["now_headsign"] == "T. Grozăvescu"
    assert t["delay_s"] == 200 and t["expected_ts"] == DEP + 200      # 300 s late, 100 s of layover
    assert trip(car(tripId="16.1_P_01", delaySec=50))["delay_s"] == 0  # the layover absorbs it


def test_a_vehicle_two_trips_away_is_shown_without_a_forecast():
    t = trip(car(tripId="16.1_P_00", delaySec=300))
    assert t["status"] == "previous_trip" and t["trips_before"] == 2 and "delay_s" not in t


def test_the_block_vehicle_already_on_a_later_trip_means_ours_has_passed():
    assert trip(car(tripId="16.1_L_01"))["status"] == "passed"


def test_an_old_position_gives_no_forecast():
    t = trip(car(updatedAt=NOW - 300))
    assert t["status"] == "stale" and t["age_s"] == 300


def test_unknown_delay_gives_no_forecast_but_still_the_stops_away():
    t = trip(car(delaySec=None))
    assert t["status"] == "no_forecast" and t["stops_away"] == 2


def test_a_trip_more_than_an_hour_away_is_not_tracked():
    assert trip(car(), dep=NOW + LIVE["track_before_s"] + 60)["status"] == "later"


def test_the_trip_is_found_even_before_its_vehicle_enters_the_area():
    t = trip(car(lat=45.90))
    assert t["status"] == "live"


def test_before_the_first_answer_there_is_no_data():
    a = live(OSError("down"))
    assert a.answer(trip="16.1_T_01", seq=4, dep=DEP)["trip"] == {"status": "no_data"}


# ---------- timetable and planner ----------

def test_epoch_counts_local_time_and_trips_past_midnight():
    assert epoch("2026-11-14", 22 * 3600 + 35 * 60, TZ) == dt.datetime(2026, 11, 14, 22, 35, tzinfo=TZ).timestamp()
    assert epoch("2026-11-14", 24 * 3600 + 10 * 60, TZ) == dt.datetime(2026, 11, 15, 0, 10, tzinfo=TZ).timestamp()


def test_old_timetable_files_without_trip_ids_still_load():
    tt = Timetable({"stops": {}, "routes": {}, "patterns": [], "days": {"2026-11-14": [[0, [1, 2]]]}})
    assert tt.service(dt.date(2026, 11, 14)) == [(0, [1, 2], None)]


def test_the_planned_ride_names_its_trip_and_boarding_stop_sequence(planner):  # noqa: F811
    data = {"stops": planner.tt.stops, "routes": planner.tt.routes, "patterns": planner.tt.patterns,
            "days": {"2026-11-14": [[0, [22 * 3600, 22 * 3600 + 300], "8.1_A_07", 12]]}}
    tr = Transit(planner.net, Timetable(data))
    ride = tr.plan(at(planner, 0), at(planner, 2000), when(21, 50))["legs"][1]
    assert (ride["trip_id"], ride["board_seq"], ride["route_id"], ride["day"], ride["dep_s"]) == ("8.1_A_07", 12, "R8", "2026-11-14", 22 * 3600)


def test_a_trip_of_another_day_is_not_matched_to_todays_vehicle():
    # the same trip_id runs every day: yesterday's departure must not become "live" with a day-long negative ETA
    t = trip(car(), dep=NOW - 86400 + 6 * 60)
    assert t["status"] != "live" and "eta_s" not in t
