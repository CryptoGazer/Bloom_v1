"""Live public transport: where the vehicles are now and how late a planned trip runs.

Source: GET https://cont.primariatm.ro/api/mobile/transit/vehicles (Primăria Timișoara, no key). Checked on 14.11.2026
(docs/research/2026-11-14-live-transit.md): its tripId and stopSequence match the SMTT GTFS feed of the service day,
so a planned trip (backend/transit.py keeps trip_id and the boarding stop's stop_sequence) is found by its trip id,
never guessed from the line number.

One shared cache for every visitor: the city server is asked at most once per `refresh_s`, whatever our traffic.
Honesty rules:
- a position is live only while its GPS time (updatedAt) is younger than `stale_s`; reading an old point again
  does not make it fresh;
- delaySec null means "unknown", not "on time"; a value outside the plausible window gives no forecast;
- a vehicle missing from the answer is not a cancelled trip: the page shows the timetable and says why.
"""
import datetime as dt
import json
import threading
import time
import urllib.error
import urllib.request

from backend.transit import ROUTE_TYPES

# All numbers are settings, not promises of the city API.
LIVE = {
    "url": "https://cont.primariatm.ro/api/mobile/transit/vehicles",
    "refresh_s": 15,              # at most one request to the city server per this many seconds (longer if it asks)
    "max_backoff_s": 120,         # after failures: wait 15, 30, 60, 120 s
    "timeout_s": 8,
    "stale_s": 60,                # a GPS point older than this is shown as old, not live (the design's "LIVE" limit)
    "delay_min_s": -10 * 60,      # a reported delay outside [-10, +30] min is not used for a forecast
    "delay_max_s": 30 * 60,
    "track_before_s": 60 * 60,    # a planned trip is tracked from an hour before its departure
    "area_pad_deg": 0.01,         # vehicles shown within ~1 km around the stops of the map area
    "user_agent": "Bloom-UniHack-2026 (night route, Timisoara)",
}
SOURCE = "Primăria Timișoara · /api/mobile/transit/vehicles"


def fetch_city(url=LIVE["url"], timeout=LIVE["timeout_s"]):
    req = urllib.request.Request(url, headers={"User-Agent": LIVE["user_agent"], "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def epoch(day, sec, tz):
    """Unix time of `sec` seconds after midnight of local calendar day `day` ('YYYY-MM-DD'); sec may pass 86400."""
    return (dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), tzinfo=tz) + dt.timedelta(seconds=sec)).timestamp()


def _retry_after(e):
    try:
        return float(e.headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        return 0.0


class Vehicles:
    """The shared, rate-limited copy of the city's vehicles answer. Thread-safe: FastAPI runs sync endpoints in threads."""

    def __init__(self, fetch=fetch_city, clock=time.time):
        self.fetch, self.clock = fetch, clock
        self.lock = threading.Lock()
        self.data = None          # last good answer
        self.fetched_at = None    # our clock when it came
        self.error = None         # what went wrong last time; None after a success
        self.next_at = 0.0
        self.failures = 0

    def snapshot(self):
        with self.lock:
            now = self.clock()
            if now >= self.next_at:
                try:
                    data = self.fetch()
                    if not isinstance(data, dict) or not isinstance(data.get("vehicles"), list):
                        raise ValueError("unexpected answer")
                    self.data, self.fetched_at, self.error, self.failures = data, now, None, 0
                    asked = data.get("refreshInSec")
                    wait = max(LIVE["refresh_s"], float(asked) if isinstance(asked, (int, float)) else 0.0)
                except Exception as e:  # network, HTTP, JSON: keep the old copy, it stays as old as it is
                    self.failures += 1
                    self.error = f"http_{e.code}" if isinstance(e, urllib.error.HTTPError) else type(e).__name__
                    wait = min(LIVE["max_backoff_s"], LIVE["refresh_s"] * 2 ** (self.failures - 1))
                    wait = max(wait, _retry_after(e))
                self.next_at = now + wait
            return {"vehicles": list((self.data or {}).get("vehicles") or []), "fetched_at": self.fetched_at,
                    "error": self.error, "next_in_s": round(max(0.0, self.next_at - now), 1)}


def plausible(delay):
    return isinstance(delay, (int, float)) and not isinstance(delay, bool) and LIVE["delay_min_s"] <= delay <= LIVE["delay_max_s"]


class Live:
    """Vehicles in the map area and the live state of one planned trip, over a Vehicles cache and the timetable."""

    def __init__(self, vehicles, timetable, clock=time.time):
        self.vehicles, self.tt, self.clock = vehicles, timetable, clock
        lats = [s[1] for s in timetable.stops.values()] or [0.0]
        lons = [s[2] for s in timetable.stops.values()] or [0.0]
        pad = LIVE["area_pad_deg"]
        self.bbox = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)  # west, south, east, north

    def _vehicle(self, v, now):
        rid = v.get("routeId")
        route = self.tt.routes.get(rid)
        upd, sid = v.get("updatedAt"), v.get("stopId")
        age = now - upd if isinstance(upd, (int, float)) else None
        delay = v.get("delaySec")
        return {
            "id": str(v.get("id")), "route_id": rid,
            "line": route[0] if route else str(rid or "?").rsplit("_", 1)[-1],
            "route_type": ROUTE_TYPES.get(route[1], "bus") if route else "bus",
            "color": "#" + (route[2] if route else "555555"),
            "trip_id": v.get("tripId"), "headsign": v.get("headsign"),
            "lat": v.get("lat"), "lon": v.get("lon"), "bearing": v.get("bearing"),
            "status": v.get("status"), "stop_seq": v.get("stopSequence"),
            "stop": self.tt.stops[sid][0] if sid in self.tt.stops else None,
            "delay_s": round(delay) if plausible(delay) else None,
            "age_s": None if age is None else max(0, round(age)),
            "live": age is not None and age <= LIVE["stale_s"],
            "wheelchair": bool(v.get("wheelchair")),
        }

    def _inside(self, v):
        w, s, e, n = self.bbox
        lat, lon = v["lat"], v["lon"]
        return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and w <= lon <= e and s <= lat <= n

    def _block(self, trip_id, day):
        """{trip_id: [block_id, first, last departure]} of the feed that has this trip, the feed of `day` first."""
        feeds = [self.tt.feed_of_day.get(day)] + sorted(self.tt.blocks, reverse=True)
        for f in feeds:
            trips = self.tt.blocks.get(f) or {}
            if trip_id in trips:
                return trips
        return {}

    def _previous(self, vehicles, trip_id, dep_ts, now, day):
        """The vehicle of the planned trip's block while it still runs an earlier trip, or None.
        Forecast only when that is the trip right before ours: our trip starts at its time, or when the vehicle
        gets there if its reported delay eats the layover: delay = max(0, previous end + delay - our start)."""
        trips = self._block(trip_id, day)
        if trip_id not in trips:
            return None
        block, start, _ = trips[trip_id]
        mine = [(trips[x["trip_id"]], x) for x in vehicles if x["trip_id"] != trip_id and trips.get(x["trip_id"], [None])[0] == block]
        if not mine:
            return None
        (_, v_start, v_end), v = max(mine, key=lambda m: (m[1]["live"], -(m[1]["age_s"] or 0)))
        out = {"vehicle": v["id"], "age_s": v["age_s"], "stop": v["stop"], "wheelchair": v["wheelchair"], "now_headsign": v["headsign"]}
        if v_start > start:
            return {**out, "status": "passed"}   # the vehicle is already on a later trip of its block
        between = sum(1 for b, s, _ in trips.values() if b == block and v_start < s < start)
        out["trips_before"] = between + 1
        if not v["live"] or v["delay_s"] is None or between:
            return {**out, "status": "previous_trip"}
        delay = max(0, round(v_end + v["delay_s"] - start))
        return {**out, "status": "previous_trip", "delay_s": delay, "expected_ts": round(dep_ts + delay), "eta_s": round(dep_ts + delay - now)}

    def trip(self, vehicles, trip_id, board_seq, dep_ts, now, day=None):
        """What the feed says about planned trip `trip_id` at its boarding stop (GTFS stop_sequence `board_seq`,
        scheduled at unix time `dep_ts`; `day` is the plan's day, to pick the feed). status:
          later         - departure more than track_before_s away: nothing to track yet;
          previous_trip - the vehicle that will run it is still on an earlier trip of its block (with a forecast
                          only when that is the trip right before);
          no_vehicle    - no vehicle runs this trip or its block now (or sends no position): the timetable stands;
          stale         - its last position is older than stale_s;
          passed        - it is already past the boarding stop;
          no_forecast   - live position, but no plausible delay;
          live          - expected at dep_ts + delay ("timetable + reported delay": an estimate, not the operator's ETA)."""
        if dep_ts - now > LIVE["track_before_s"]:
            return {"status": "later"}
        v = next((x for x in vehicles if trip_id and x["trip_id"] == trip_id), None)
        if v is None:
            return self._previous(vehicles, trip_id, dep_ts, now, day) or {"status": "no_vehicle"}
        out = {"vehicle": v["id"], "age_s": v["age_s"], "stop": v["stop"], "wheelchair": v["wheelchair"]}
        if not v["live"]:
            return {**out, "status": "stale"}
        seq = v["stop_seq"]
        if isinstance(board_seq, int) and isinstance(seq, int):
            if seq > board_seq:
                return {**out, "status": "passed"}
            # stops it still has to reach, yours included: heading to yours = 1, standing at yours = 0
            out["stops_away"] = board_seq - seq + (0 if v["status"] == "STOPPED_AT" else 1)
        if v["delay_s"] is None:
            return {**out, "status": "no_forecast"}
        expected = dep_ts + v["delay_s"]
        return {**out, "status": "live", "delay_s": v["delay_s"], "expected_ts": round(expected), "eta_s": round(expected - now)}

    def answer(self, route="", trip="", seq=None, dep=None, day=None):
        snap = self.vehicles.snapshot()
        now = self.clock()
        every = [self._vehicle(v, now) for v in snap["vehicles"] if isinstance(v, dict)]
        shown = [v for v in every if self._inside(v) and (not route or v["route_id"] == route)]
        out = {
            "source": {"name": SOURCE, "url": LIVE["url"], "fetched_at": snap["fetched_at"], "error": snap["error"],
                       "age_s": None if snap["fetched_at"] is None else round(now - snap["fetched_at"])},
            "now": round(now), "refresh_s": LIVE["refresh_s"], "stale_s": LIVE["stale_s"], "vehicles": shown,
        }
        if trip and dep is not None:
            out["trip"] = self.trip(every, trip, seq, dep, now, day) if snap["fetched_at"] is not None else {"status": "no_data"}
        return out
