"""Timetable of the map area for "on foot + public transport" routes, from the SMTT GTFS feeds.

usage: .venv/bin/python -I backend/build_transit.py [--data unihack-data] [--start YYYY-MM-DD] [--days 3]
Output: data/out/city/transit.json.gz, read by backend/app.py through backend/transit.py.

For every day from --start, the first GTFS feed (newest first) that runs services that day is used: SMTT
publishes a new feed every few weeks and an old one may be the only one valid for the weekend (v4.31 for
14-15.11.2026, v4.32 from 16.11). Only trips that stop at least twice inside the area (plus a margin) are
kept, and only the part of each trip between its first and last stop there. Rebuild before the demo day.
A trip is [pattern, [departure seconds per stop], trip_id, GTFS stop_sequence of its first stop here].
"""
import argparse
import csv
import datetime as dt
import gzip
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString, Point, shape
from shapely.ops import substring

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script with -I: make "backend" importable
    sys.path.insert(0, str(ROOT))
from backend.build_city import KX, KY, log  # noqa: E402

PAD_DEG = 0.004  # ~300-450 m around the area: a stop just outside can still be walked to
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
STOP_OFF_LINE_M = 80     # a stop farther than this from its line: the shape is not trusted, stops are joined straight
SEARCH_AHEAD_M = 3000    # look for the next stop within this stretch of the line first (lines that pass a street twice)


def stop_positions(line_xy, stops_xy, max_off=STOP_OFF_LINE_M, window=SEARCH_AHEAD_M):
    """Distance along the line (metres) of every stop of a trip, each at or after the previous one, or None
    if a stop lies far off the line. GTFS SMTT has no shape_dist_traveled, so stops are placed in trip order."""
    line = LineString(line_xy)
    total, pos, start = line.length, [], 0.0
    for x, y in stops_xy:
        p, found = Point(x, y), None
        for end in (min(total, start + window), total):
            part = substring(line, start, end)
            d = start + (part.project(p) if part.geom_type == "LineString" else 0.0)
            if line.interpolate(d).distance(p) <= max_off:
                found = d
                break
        if found is None:
            return None
        pos.append(found)
        start = found
    return pos


def shape_between(shape_lonlat, stops_lonlat, first, last):
    """The line from stop `first` to stop `last` of a trip, as [[lon, lat], ...], with each stop's distance along it."""
    line_xy = [(lon * KX, lat * KY) for lon, lat in shape_lonlat]
    pos = stop_positions(line_xy, [(lon * KX, lat * KY) for lon, lat in stops_lonlat])
    if pos is None:
        return None, None
    part = substring(LineString(line_xy), pos[first], pos[last])
    if part.geom_type != "LineString":
        return None, None
    geom = [[round(x / KX, 6), round(y / KY, 6)] for x, y in part.coords]
    return geom, [round(pos[k] - pos[first], 1) for k in range(first, last + 1)]


def seconds(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


class Feed:
    def __init__(self, path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path)
        self.info = self.read("feed_info.txt")[0]
        self.calendar = self.read("calendar.txt")
        self.calendar_dates = self.read("calendar_dates.txt")

    def read(self, name):
        with self.zip.open(name) as f:
            return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))

    def services(self, day):
        ymd, weekday = day.strftime("%Y%m%d"), WEEKDAYS[day.weekday()]
        on = {c["service_id"] for c in self.calendar if c["start_date"] <= ymd <= c["end_date"] and c[weekday] == "1"}
        for x in self.calendar_dates:
            if x["date"] == ymd:
                (on.add if x["exception_type"] == "1" else on.discard)(x["service_id"])
        return on


def build(feeds, area, start, days):
    near = area.buffer(PAD_DEG)
    out = {"stops": {}, "routes": {}, "patterns": [], "days": {}, "feed_of_day": {}, "blocks": {}}
    pattern_index = {}
    cache = {}
    running = defaultdict(dict)   # feed version -> {trip_id: [block_id, first, last departure]} of every trip run on a built day
    kept_ids = defaultdict(set)   # feed version -> trip ids kept for the area
    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        feed = next((f for f in feeds if f.services(day)), None)
        if feed is None:
            log(f"transit: no feed runs services on {day}")
            continue
        if feed.path not in cache:
            stops = {s["stop_id"]: s for s in feed.read("stops.txt")}
            inside = {sid for sid, s in stops.items() if near.contains(Point(float(s["stop_lon"]), float(s["stop_lat"])))}
            times = defaultdict(list)
            for r in feed.read("stop_times.txt"):
                times[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"], seconds(r["departure_time"] or r["arrival_time"])))
            shapes = defaultdict(list)
            for r in feed.read("shapes.txt"):
                shapes[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
            shapes = {sid: [(lon, lat) for _, lon, lat in sorted(pts)] for sid, pts in shapes.items()}
            cache[feed.path] = (stops, inside, {r["route_id"]: r for r in feed.read("routes.txt")}, feed.read("trips.txt"), times, shapes)
        stops, inside, routes, trips, times, shapes = cache[feed.path]
        services = feed.services(day)
        kept = []
        version = feed.info["feed_version"]
        for trip in trips:
            if trip["service_id"] not in services:
                continue
            seq = [x for x in sorted(times[trip["trip_id"]])]
            if trip.get("block_id") and seq:
                running[version][trip["trip_id"]] = [trip["block_id"], seq[0][2], seq[-1][2]]
            idx = [i for i, (_, sid, _) in enumerate(seq) if sid in inside]
            if len(idx) < 2:
                continue
            part = seq[idx[0]: idx[-1] + 1]  # the trip between its first and last stop near the area
            key = (trip["route_id"], trip["trip_headsign"], tuple(sid for _, sid, _ in part))
            if key not in pattern_index:
                pattern_index[key] = len(out["patterns"])
                pattern = [trip["route_id"], trip["trip_headsign"], list(key[2])]
                if trip.get("shape_id") in shapes:
                    stops_lonlat = [(float(stops[sid]["stop_lon"]), float(stops[sid]["stop_lat"])) for _, sid, _ in seq]
                    geom, pos = shape_between(shapes[trip["shape_id"]], stops_lonlat, idx[0], idx[-1])
                    if geom:
                        pattern += [geom, pos]
                out["patterns"].append(pattern)
                route = routes[trip["route_id"]]
                out["routes"][trip["route_id"]] = [route["route_short_name"], int(route["route_type"]), route.get("route_color") or "555555"]
                for sid in key[2]:
                    s = stops[sid]
                    out["stops"][sid] = [s["stop_name"], round(float(s["stop_lat"]), 6), round(float(s["stop_lon"]), 6)]
            # trip_id and the GTFS stop_sequence of the first stop kept: the live vehicles feed names the trip
            # and the vehicle's next stop by these (backend/live.py)
            kept.append([pattern_index[key], [t for _, _, t in part], trip["trip_id"], part[0][0]])
            kept_ids[version].add(trip["trip_id"])
        kept.sort(key=lambda trip: trip[1][0])
        out["days"][day.isoformat()] = kept
        out["feed_of_day"][day.isoformat()] = version
        log(f"transit: {day} feed {version}: {len(kept)} trips through the area")
    # Vehicle blocks: the vehicle that will run a planned trip is often still on its previous trip of the same block
    # (backend/live.py). Only the blocks that include a trip through the area are kept.
    for version, trips in running.items():
        blocks = {trips[t][0] for t in kept_ids[version] if t in trips}
        out["blocks"][version] = {t: b for t, b in trips.items() if b[0] in blocks}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "unihack-data"))
    ap.add_argument("--area", default="config/area.geojson")
    ap.add_argument("--start", default=dt.date.today().isoformat())
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--out", default="data/out/city/transit.json.gz")
    args = ap.parse_args()

    paths = sorted((Path(args.data) / "gtfs").glob("*.zip"), reverse=True)  # newest feed version first
    if not paths:
        sys.exit(f"No GTFS zip in {Path(args.data) / 'gtfs'}")
    feeds = [Feed(p) for p in paths]
    feeds.sort(key=lambda f: [int(x) for x in f.info["feed_version"].split(".")], reverse=True)
    area = shape(json.loads((ROOT / args.area).read_text(encoding="utf-8"))["features"][0]["geometry"])
    data = build(feeds, area, dt.date.fromisoformat(args.start), args.days)
    data["meta"] = {"built_at": dt.datetime.now().isoformat(timespec="seconds"), "area": args.area,
                    "feeds": {f.info["feed_version"]: f.path.name for f in feeds},
                    "licence": "GTFS SMTT Timișoara (smtt.ro)"}
    out = ROOT / args.out
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    shaped = sum(1 for p in data["patterns"] if len(p) >= 5)
    log(f"written {out} ({out.stat().st_size / 1000:.0f} KB): {len(data['stops'])} stops, {len(data['patterns'])} patterns "
        f"({shaped} drawn along the line, {len(data['patterns']) - shaped} straight between stops), days {data['feed_of_day']}")


if __name__ == "__main__":
    main()
