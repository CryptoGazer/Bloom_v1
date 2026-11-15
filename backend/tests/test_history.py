"""The transit history: what a ride is told about its line on a recent day. No database: a fake loader.
Run: .venv/bin/python -m pytest backend/tests -q

Line R1 towards "Spre V". The ride under test leaves at 22:00 on Saturday 14.11, so its half hour is 22:00-22:30
(slot 1320 minutes) and the days looked at are Friday 13.11 and earlier.
"""
import datetime as dt
import gzip
import json

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.history import HISTORY, LOCAL_TZ, History, build, hhmm, minute_of, norm, service_day
from backend.tests.test_routing import FEATURES, ll, point

SAT, FRI, THU = dt.date(2026, 11, 14), dt.date(2026, 11, 13), dt.date(2026, 11, 12)
SLOT = 22 * 60


def day_rows(day, route="R1", head="Spre V", slot=SLOT, trips=4, p10=-210.0, p50=-150.0, p90=-10.0, fixes=200, early=150, late=0,
             last_run=(23, 59), line="1", mode="tram"):
    """What the three queries return for one line and direction on one service day."""
    run = dt.datetime.combine(day, dt.time(*last_run), tzinfo=LOCAL_TZ) + (dt.timedelta(days=1) if last_run[0] < 4 else dt.timedelta())
    return {
        "stats": [{"day": day, "route_id": route, "headsign": head, "slot": slot, "fixes": fixes, "early": early, "late": late,
                   "p10": p10, "p50": p50, "p90": p90}],
        "trips": [{"day": day, "route_id": route, "headsign": head, "first_min": slot - 20 + 15 * i, "last_min": slot + 15 * i} for i in range(trips)],
        "lines": [{"day": day, "route_id": route, "headsign": head, "line": line, "mode": mode, "fixes": fixes + 40, "last_run": run}],
    }


class Tiger:
    """Fake database: answers with the rows of the days inside the asked range, or raises."""

    def __init__(self, *days):
        self.days, self.calls, self.down = list(days), [], False

    def __call__(self, first, last):
        self.calls.append((first, last))
        if self.down:
            raise OSError("connection refused")
        out = {"stats": [], "trips": [], "lines": []}
        for rows in self.days:
            for name in out:
                out[name] += [r for r in rows[name] if first <= r["day"] <= last]
        return out


def history(*days, now=dt.datetime(2026, 11, 14, 21, 40)):
    h = History(Tiger(*days), clock=lambda: now, log=lambda *_a, **_k: None)
    assert h.refresh() is True
    return h


def ride(hh=22, mm=0, day=SAT, route="R1", head="Spre V"):
    return {"type": "ride", "route_id": route, "headsign": head, "day": day.isoformat(), "dep_s": hh * 3600 + mm * 60}


def test_a_ride_is_told_how_its_line_ran_yesterday_around_the_same_hour():
    h = history(day_rows(FRI)).ride(ride())
    assert (h["day"], h["when"], h["trips"], h["fixes"]) == ("2026-11-13", "yesterday", 4, 200)
    assert (h["from"], h["to"]) == ("21:00", "23:30")          # the half hour 22:00-22:30 and an hour each side
    assert (h["median_min"], h["early_min"], h["late_min"]) == (-2.5, -3.5, -0.2)
    assert h["pattern"] == "early" and h["early_share"] == 0.75
    assert h["be_early_min"] == 4 and h["wait_up_to_min"] is None   # one fix in ten was 3.5 min ahead: be there 4 min before


def test_fewer_than_three_trips_say_nothing_and_an_older_day_with_enough_is_used():
    assert history(day_rows(FRI, trips=2)).ride(ride()) is None
    h = history(day_rows(FRI, trips=2), day_rows(THU, trips=5, p50=40.0, p10=-20.0, p90=90.0)).ride(ride())
    assert (h["day"], h["when"], h["trips"]) == ("2026-11-12", "date", 5)
    assert h["pattern"] == "on_time" and h["be_early_min"] is None and h["wait_up_to_min"] is None


def test_only_days_before_the_ride_count_and_no_further_back_than_a_week():
    assert history(day_rows(SAT)).ride(ride()) is None                       # the ride's own day is not history
    assert history(day_rows(dt.date(2026, 11, 6))).ride(ride()) is None      # 8 days back
    assert history(day_rows(dt.date(2026, 11, 7))).ride(ride())["day"] == "2026-11-07"


def test_a_ride_after_midnight_belongs_to_the_evening_before():
    # 00:10 on calendar Sunday is 24:10 of Saturday's service; Friday's 24:00 slot answers
    h = history(day_rows(FRI, slot=1440)).ride(ride(0, 10, day=dt.date(2026, 11, 15)))
    assert (h["day"], h["from"], h["to"]) == ("2026-11-13", "23:00", "01:30")
    assert history(day_rows(FRI, slot=1440)).ride(ride(0, 10, day=SAT)) is None   # 00:10 on Saturday is Friday's service: its own day


def test_the_direction_is_found_by_headsign_and_another_line_or_direction_is_not_used():
    h = history(day_rows(FRI))
    assert h.ride(ride(head="  spre   V "))["trips"] == 4
    assert h.ride(ride(head="Spre U")) is None and h.ride(ride(route="R2")) is None
    assert h.ride({"type": "ride", "route_id": "R1", "headsign": "Spre V"}) is None   # a ride without its time
    assert h.ride(ride(22, 30)) is None                                             # the next half hour has no data


def test_a_late_line_is_said_to_be_late_and_nobody_is_told_to_leave_later():
    h = history(day_rows(FRI, p10=30.0, p50=200.0, p90=560.0, early=0, late=120)).ride(ride())
    assert (h["median_min"], h["late_share"], h["pattern"]) == (3.3, 0.6, "late")
    assert h["be_early_min"] is None and h["wait_up_to_min"] == 10
    assert not any("later" in key or "leave" in key for key in h)
    uneven = history(day_rows(FRI, p10=-150.0, p50=-20.0, p90=576.0)).ride(ride())
    assert (uneven["pattern"], uneven["be_early_min"], uneven["wait_up_to_min"]) == ("uneven", 3, 10)


def test_advice_has_limits():
    h = history(day_rows(FRI, p10=-599.0, p50=-500.0, p90=1790.0)).ride(ride())
    assert h["be_early_min"] == HISTORY["max_early_min"] and h["wait_up_to_min"] == HISTORY["max_late_min"]
    assert history(day_rows(FRI, p10=-60.0)).ride(ride())["be_early_min"] is None   # the boarding minute already covers it


def test_a_line_that_is_usually_on_time_but_sometimes_early_or_late_says_so():
    early = history(day_rows(FRI, p10=-200.0, p50=-20.0, p90=100.0)).ride(ride())
    assert (early["pattern"], early["be_early_min"], early["wait_up_to_min"]) == ("on_time_but_early", 4, None)
    late = history(day_rows(FRI, p10=-30.0, p50=20.0, p90=400.0)).ride(ride())
    assert (late["pattern"], late["be_early_min"], late["wait_up_to_min"]) == ("on_time_but_late", None, 7)


def test_the_days_last_sighting_is_given_near_the_end_of_service_only():
    assert history(day_rows(FRI, last_run=(23, 59))).ride(ride())["last_seen"] == "23:59"
    assert history(day_rows(FRI, last_run=(0, 20))).ride(ride())["last_seen"] is None          # 00:20 is over two hours after 22:00
    assert history(day_rows(FRI, last_run=(21, 30))).ride(ride())["last_seen"] == "21:30"      # the ride is later than anything seen


def test_when_is_said_by_the_calendar_not_by_the_service_day():
    night = dt.datetime(2026, 11, 14, 2, 0)   # Saturday 02:00: still Friday's service, but Friday is "yesterday"
    assert history(day_rows(FRI), now=night).ride(ride())["when"] == "yesterday"
    assert history(day_rows(FRI), now=dt.datetime(2026, 11, 13, 23, 0)).ride(ride())["when"] == "today"   # planning tomorrow's ride
    assert history(day_rows(THU), now=night).ride(ride())["when"] == "date"


def test_trips_are_counted_inside_the_window_of_each_half_hour():
    rows = day_rows(FRI, trips=0)
    rows["trips"] = [{"day": FRI, "route_id": "R1", "headsign": "Spre V", "first_min": a, "last_min": b}
                     for a, b in [(SLOT - 100, SLOT - 61), (SLOT - 100, SLOT - 60), (SLOT + 89, SLOT + 120), (SLOT + 90, SLOT + 120)]]
    assert build(rows, FRI, FRI)[FRI]["slots"][("R1", "spre v")][SLOT]["trips"] == 2   # the first ends before, the last starts after
    assert len(build(rows, FRI, FRI)[FRI]["trips"][("R1", "spre v")]) == 4


def test_first_read_takes_the_week_later_reads_two_days_and_an_outage_keeps_the_copy():
    tiger = Tiger(day_rows(FRI))
    h = History(tiger, clock=lambda: dt.datetime(2026, 11, 14, 21, 40), log=lambda *_a, **_k: None)
    assert h.ready is False and h.ride(ride()) is None
    assert h.refresh() and tiger.calls == [(dt.date(2026, 11, 7), SAT)] and h.ready
    assert h.refresh() and tiger.calls[-1] == (FRI, SAT)
    tiger.down = True
    assert h.refresh() is False and h.error == "OSError"
    assert h.ride(ride())["trips"] == 4 and h.ready


def test_the_week_moves_with_the_calendar():
    now = [dt.datetime(2026, 11, 14, 21, 40)]
    tiger = Tiger(day_rows(FRI), day_rows(dt.date(2026, 11, 7)))
    h = History(tiger, clock=lambda: now[0], log=lambda *_a, **_k: None)
    h.refresh()
    now[0] = dt.datetime(2026, 11, 16, 9, 0)
    h.refresh()
    assert tiger.calls[-1] == (dt.date(2026, 11, 9), dt.date(2026, 11, 16))   # two new days: the whole range again
    assert dt.date(2026, 11, 7) not in h._days and FRI in h._days


def test_small_helpers():
    assert norm("  Gara   de NORD ") == "gara de nord"
    assert (hhmm(1320), hhmm(1450), hhmm(240)) == ("22:00", "00:10", "04:00")
    assert service_day(dt.datetime(2026, 11, 15, 3, 59)) == SAT and service_day(dt.datetime(2026, 11, 15, 4, 0)) == dt.date(2026, 11, 15)
    assert minute_of(dt.datetime(2026, 11, 15, 0, 10), SAT) == 1450


def test_from_env_needs_a_database_url_and_can_be_switched_off(monkeypatch):
    for name in ("TIGER_READ_URL", "TIGER_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TIGER_HISTORY", "on")
    assert History.from_env() is None
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://owner@example/db")
    assert isinstance(History.from_env(), History)
    monkeypatch.setenv("TIGER_HISTORY", "off")
    assert History.from_env() is None


# ---------- through the API ----------

def city(tmp_path):
    """The street of test_routing with a tram from U to V at 22:00 on 14.11 (line R1 towards "Spre V")."""
    path = tmp_path / "segments.geojson.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "meta": {"as_of": "2026-11-14"}, "features": FEATURES}, f)
    (x1_lon, x1_lat), (x2_lon, x2_lat) = ll(0, 62), ll(200, 62)
    with gzip.open(path.parent / "transit.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"stops": {"X1": ["Stația U", x1_lat, x1_lon], "X2": ["Stația V", x2_lat, x2_lon]},
                   "routes": {"R1": ["1", 0, "e3a900"]}, "patterns": [["R1", "Spre V", ["X1", "X2"]]],
                   "days": {"2026-11-14": [[0, [79200, 79320]]]}, "feed_of_day": {"2026-11-14": "4.31"}}, f)
    return path


TRIP = {"from": point(0, 0), "to": point(200, 0), "mode": "transit", "at": "2026-11-14T21:55"}


def test_api_ride_carries_the_history_and_health_says_it_is_ready(tmp_path):
    with TestClient(create_app(city(tmp_path), history=history(day_rows(FRI)))) as client:
        assert client.get("/api/health").json()["history"] is True
        body = client.get("/api/route", params=TRIP).json()
        ride_leg = body["transit"]["legs"][1]
        assert (ride_leg["dep"], ride_leg["history"]["day"], ride_leg["history"]["be_early_min"]) == ("22:00", "2026-11-13", 4)
        assert body["settings"]["history"]["min_trips"] == 3
        assert body["transit"]["leave_at"] == "21:58"   # the plan itself is not changed by the history


def test_api_works_the_same_without_tiger(tmp_path):
    with TestClient(create_app(city(tmp_path))) as client:                     # no database configured
        assert client.get("/api/health").json()["history"] is False
        assert client.get("/api/route", params=TRIP).json()["transit"]["legs"][1]["history"] is None
    down = History(Tiger(), clock=lambda: dt.datetime(2026, 11, 14, 21, 40), log=lambda *_a, **_k: None)
    down._load.down = True
    assert down.refresh() is False
    with TestClient(create_app(city(tmp_path), history=down)) as client:       # configured, but the database is down
        body = client.get("/api/route", params=TRIP).json()
        assert body["transit"]["kind"] == "ok" and body["transit"]["legs"][1]["history"] is None
        assert client.get("/api/health").json()["history"] is False
