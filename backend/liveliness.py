"""Signs of life along a route at a given time: evidence, not a score (spec: "liveliness", variant A).

- places open at that time within 50 m of the route (OSM opening_hours; places without hours are only counted);
- stops within 100 m with a departure within 10 minutes of that time (GTFS timetable of the area);
- share of the way on main roads (primary/secondary/tertiary, or a sidewalk within 15 m of one).
"No signs" means "no data", never "deserted" or "unsafe". Pure functions over Network, places and Timetable.
"""
import numpy as np
import opening_hours
import shapely
from shapely.geometry import LineString
from shapely.strtree import STRtree

from backend.routing import KX, KY
from backend.transit import clock

LIVELY = {"place_radius_m": 50, "stop_radius_m": 100, "departure_window_s": 600, "main_radius_m": 15, "max_places": 8}
# only places where people are when open; a gallery or a park "open 24/7" says nothing about the street
PEOPLE_AMENITIES = {"restaurant", "cafe", "bar", "pub", "fast_food", "nightclub", "biergarten", "ice_cream", "pharmacy", "fuel",
                    "cinema", "theatre", "casino", "hospital", "police"}


def people_place(category):
    key, _, value = (category or "").partition("=")
    return key == "shop" or (key == "amenity" and value in PEOPLE_AMENITIES) or (key == "tourism" and value in {"hotel", "hostel"})


MAIN_HIGHWAYS = {"trunk", "primary", "secondary", "tertiary", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}


def _xy(lon, lat):
    return (lon * KX, lat * KY)


class Signs:
    def __init__(self, net, places, timetable=None):
        self.tt = timetable
        self.places, self.unknown = [], []
        for e in places:
            if e.get("k") != "place" or not people_place(e.get("c")):
                continue
            if e.get("oh"):
                try:
                    hours = opening_hours.OpeningHours(e["oh"])
                except Exception:  # an unparsable string is the same as unknown hours
                    hours = None
            else:
                hours = None
            (self.places if hours else self.unknown).append((e, hours))
        self._place_tree = STRtree(shapely.points([_xy(e["lon"], e["lat"]) for e, _ in self.places])) if self.places else None
        self._unknown_tree = STRtree(shapely.points([_xy(e["lon"], e["lat"]) for e, _ in self.unknown])) if self.unknown else None
        main = [net.lines[i] for i, p in enumerate(net.props)
                if p.get("kind") == "street" and set(str(p.get("hw", "")).split(";")) & MAIN_HIGHWAYS]
        self._main_tree = STRtree(np.array(main, dtype=object)) if main else None
        self.stop_ids = list(timetable.stops) if timetable else []
        self._stop_tree = (STRtree(shapely.points([_xy(timetable.stops[s][2], timetable.stops[s][1]) for s in self.stop_ids]))
                           if self.stop_ids else None)

    @staticmethod
    def _line(route):
        coords = [c for f in route["geometry"]["features"] for c in f["geometry"]["coordinates"]]
        return LineString([_xy(*c) for c in coords]) if len(coords) >= 2 else None

    def along(self, route, when):
        line = self._line(route)
        out = {"open_places": [], "places_unknown_hours": 0, "stops": [], "main_share": 0.0}
        if line is None:
            return out
        if self._place_tree is not None:
            for i in sorted(self._place_tree.query(line, predicate="dwithin", distance=LIVELY["place_radius_m"])):
                e, hours = self.places[i]
                if hours.is_open(when):
                    out["open_places"].append({"name": e["n"], "category": e.get("c"), "lat": e["lat"], "lon": e["lon"],
                                               "always": e["oh"].strip() == "24/7"})
            out["open_places"] = out["open_places"][: LIVELY["max_places"]]
        if self._unknown_tree is not None:
            out["places_unknown_hours"] = len(self._unknown_tree.query(line, predicate="dwithin", distance=LIVELY["place_radius_m"]))
        if self._stop_tree is not None:
            near = {self.stop_ids[i] for i in self._stop_tree.query(line, predicate="dwithin", distance=LIVELY["stop_radius_m"])}
            t0 = when.hour * 3600 + when.minute * 60 + when.second
            found = {}
            for p, times, _ in self.tt.trips(when.date()):
                rid, _, stops = self.tt.patterns[p][:3]
                for sid, t in zip(stops, times):
                    if sid in near and abs(t - t0) <= LIVELY["departure_window_s"]:
                        found.setdefault(sid, set()).add((t, self.tt.routes[rid][0]))
            out["stops"] = [{"name": self.tt.stops[sid][0], "lat": self.tt.stops[sid][1], "lon": self.tt.stops[sid][2],
                             "departures": [{"line": line_no, "time": clock(t)} for t, line_no in sorted(deps)]}
                            for sid, deps in sorted(found.items(), key=lambda kv: min(kv[1]))]
        if self._main_tree is not None and line.length > 0:
            n = max(1, int(line.length // 10))
            samples = shapely.line_interpolate_point(line, (np.arange(n) + 0.5) * line.length / n)
            hit = self._main_tree.query_nearest(samples, max_distance=LIVELY["main_radius_m"], all_matches=False)[0]
            out["main_share"] = round(len(set(hit.tolist())) / n, 2)
        return out
