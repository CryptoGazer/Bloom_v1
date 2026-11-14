"""On foot + public transport: walk (better-lit route) to a stop, ride one line without changes, walk to the door.

Timetable: data/out/city/transit.json.gz from backend/build_transit.py (SMTT GTFS, only the map area).
Times are seconds since midnight of a service day; trips after midnight run past 86400 ("24:10").
Pure functions over Network and Timetable, no web framework here.
"""
import datetime as dt
import gzip
import json
from pathlib import Path

from backend.routing import SETTINGS

# All numbers are settings; check them with real people.
TRANSIT = {
    "max_walk_m": 800,           # to the stop and from the stop, each
    "board_margin_s": 60,        # be at the stop a minute before the departure
    "max_wait_s": 45 * 60,       # a longer wait is not offered: "no trip soon", with the next departure
    "stop_snap_m": 150,          # a stop farther than this from a walkable path is not used
    "night_ends_h": 4,           # before 04:00, "tonight" is the previous day's service
}
ROUTE_TYPES = {0: "tram", 3: "bus", 11: "trolleybus"}


def clock(sec):
    """Seconds since a service day's midnight -> 'HH:MM' on the wall clock (24:10 -> 00:10)."""
    sec = int(sec) % 86400
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


class Timetable:
    def __init__(self, data):
        self.stops = data["stops"]            # stop_id -> [name, lat, lon]
        self.routes = data["routes"]          # route_id -> [line number, GTFS route_type, colour]
        self.patterns = data["patterns"]      # [route_id, headsign, [stop_id, ...]]
        self.days = data["days"]              # "YYYY-MM-DD" -> [[pattern, [departure seconds per stop]], ...]
        self.feed_of_day = data.get("feed_of_day", {})
        self.meta = data.get("meta", {})

    @classmethod
    def load(cls, path):
        with gzip.open(Path(path), "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    def service(self, day):
        return self.days.get(day.isoformat(), [])

    def trips(self, day):
        """Trips running on calendar day `day`, in seconds since that day's midnight: the day's own service
        plus the after-midnight part of the previous day's service."""
        prev = self.service(day - dt.timedelta(days=1))
        return list(self.service(day)) + [(p, [t - 86400 for t in times]) for p, times in prev if times[-1] >= 86400]


class Transit:
    def __init__(self, net, timetable):
        self.net, self.tt = net, timetable
        self.stop_snap = {}
        for sid, (_, lat, lon) in timetable.stops.items():
            snap = net.snap(lat, lon, max_m=TRANSIT["stop_snap_m"])
            if snap is not None:
                self.stop_snap[sid] = snap

    def _near(self, P):
        """Stops within walking distance of snapped point P: {stop_id: (lit-weighted cost, metres)}."""
        factors = SETTINGS["factor_better_lit"]
        tree = self.net.tree(P, factors, max_cost=TRANSIT["max_walk_m"] * max(factors.values()))
        near = {}
        for sid, snap in self.stop_snap.items():
            r = self.net.reach(tree, snap, factors, S=P)
            if r is not None and r[1] <= TRANSIT["max_walk_m"]:
                near[sid] = r
        return near

    def _stop(self, sid):
        name, lat, lon = self.tt.stops[sid]
        return {"id": sid, "name": name, "lat": lat, "lon": lon}

    def _departure(self, p, i, t):
        rid, _, stops = self.tt.patterns[p]
        return {"line": self.tt.routes[rid][0], "stop": self.tt.stops[stops[i]][0], "time": clock(t)}

    def _last(self, pairs, day, when, route_id=None, stop=None):
        """The last departure of tonight's service for these stop pairs (optionally one line from one stop)."""
        service_day = day if when.hour >= TRANSIT["night_ends_h"] else day - dt.timedelta(days=1)
        last = None
        for p, times in self.tt.service(service_day):
            rid, _, stops = self.tt.patterns[p]
            if route_id is not None and rid != route_id:
                continue
            for i, _ in pairs.get(p, ()):
                if stop is not None and stops[i] != stop:
                    continue
                if last is None or times[i] > last[0]:
                    last = (times[i], p, i)
        return self._departure(last[1], last[2], last[0]) if last else None

    def plan(self, A, B, when):
        """Best trip leaving `when` (local wall-clock datetime) from snapped A to snapped B, or the reason there is none."""
        origin, dest = self._near(A), self._near(B)
        if not origin or not dest:
            return {"kind": "none", "reason": "no_stop_near", "last": None, "next": None}
        pairs = {}
        for p, (_, _, stops) in enumerate(self.tt.patterns):
            found = [(i, j) for i, o in enumerate(stops) if o in origin for j in range(i + 1, len(stops)) if stops[j] in dest and stops[j] != o]
            if found:
                pairs[p] = found
        if not pairs:
            return {"kind": "none", "reason": "no_line", "last": None, "next": None}

        walk = SETTINGS["walk_mps"]
        day, t0 = when.date(), when.hour * 3600 + when.minute * 60 + when.second
        tomorrow = [(p, [t + 86400 for t in times]) for p, times in self.tt.trips(day + dt.timedelta(days=1))]
        best = nxt = None
        for p, times in self.tt.trips(day) + tomorrow:
            stops = self.tt.patterns[p][2]
            for i, j in pairs.get(p, ()):
                o, d = stops[i], stops[j]
                ready = t0 + origin[o][1] / walk + TRANSIT["board_margin_s"]
                if times[i] < ready:
                    continue
                if nxt is None or times[i] < nxt[0]:
                    nxt = (times[i], p, i)
                if times[i] - ready > TRANSIT["max_wait_s"]:
                    continue
                key = (times[j] + dest[d][1] / walk, origin[o][0] + dest[d][0])  # arrival at B, then less unlit walking
                if best is None or key < best[0]:
                    best = (key, p, i, j, times)
        if best is None:
            return {"kind": "none", "reason": "no_trip_soon", "last": self._last(pairs, day, when),
                    "next": self._departure(nxt[1], nxt[2], nxt[0]) if nxt else None}

        _, p, i, j, times = best
        rid, headsign, stops = self.tt.patterns[p]
        o, d = stops[i], stops[j]
        factors = SETTINGS["factor_better_lit"]
        walks = [self.net.route(A, self.stop_snap[o], factors), self.net.route(self.stop_snap[d], B, factors)]
        if None in walks:
            return {"kind": "none", "reason": "no_stop_near", "last": None, "next": None}
        seconds = [w.pop("_sec") for w in walks]
        for w in walks:
            w.pop("_key", None)
        line, route_type, colour = self.tt.routes[rid]
        ride = {"type": "ride", "line": line, "route_type": ROUTE_TYPES.get(route_type, "bus"), "color": "#" + colour,
                "headsign": headsign, "from": self._stop(o), "to": self._stop(d), "dep": clock(times[i]), "arr": clock(times[j]),
                "stops": j - i, "minutes": round((times[j] - times[i]) / 60, 1),
                "coords": [[self.tt.stops[s][2], self.tt.stops[s][1]] for s in stops[i: j + 1]]}
        leave, arrive = times[i] - seconds[0], times[j] + seconds[1]
        return {
            "kind": "ok", "leave_at": clock(leave), "arrive_at": clock(arrive), "minutes": round((arrive - leave) / 60, 1),
            "wait_min": round((times[i] - t0 - seconds[0]) / 60, 1),
            "legs": [{"type": "walk", **walks[0]}, ride, {"type": "walk", **walks[1]}],
            "last": self._last(pairs, day, when, route_id=rid, stop=o),
            "feed": self.tt.feed_of_day.get(day.isoformat()),
        }
