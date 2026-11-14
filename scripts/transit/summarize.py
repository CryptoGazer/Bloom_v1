"""Summarise the transit logger output. Reads only; the raw logs are never changed.

usage: python3 -I scripts/transit/summarize.py [--dir data/transit] [--gtfs ~/Downloads/smtt-timisoara-ro]
Writes (overwrites, they are derived) into <dir>/summary/:
  coverage.csv            per service day: first/last request, ok/failed requests, longest gap
                          -> a "last seen 23:40" is only meaningful if the logger was running after it
  by_route_hour.csv       per service day, line and hour: vehicles, fixes, median/p90 delay, share >3 min late
  last_seen_by_route.csv  per service day and line: first/last GPS fix, last trip; with --gtfs also the
                          scheduled end of the last trip that day
Times are local (Europe/Bucharest). A service day runs 04:00-04:00, so 24:10 means 00:10 the next night.
"""
import argparse
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")
LATE_SEC = 180
NIGHT_FROM_MIN = 23 * 60


def minutes_in_service_day(ts, service_date):
    local = dt.datetime.fromtimestamp(ts, TZ).replace(tzinfo=None)
    return int((local - dt.datetime.combine(dt.date.fromisoformat(service_date), dt.time())).total_seconds() // 60)


def hhmm(minutes):
    return "" if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"


def pct(sorted_vals, q):
    return sorted_vals[int(q * (len(sorted_vals) - 1))] if sorted_vals else ""


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if None in row or None in row.values():  # cut line after a crash
                continue
            yield row


def gtfs_schedule(gtfs, dates):
    """(service_date, route_id) -> scheduled end (minutes) of the last trip; route_id -> short name."""
    def table(name):
        with (gtfs / name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    names = {r["route_id"]: r["route_short_name"] for r in table("routes.txt")}
    calendar, exceptions = table("calendar.txt"), table("calendar_dates.txt")
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    active = {}
    for d in dates:
        key = d.replace("-", "")
        wd = weekdays[dt.date.fromisoformat(d).weekday()]
        services = {c["service_id"] for c in calendar if c["start_date"] <= key <= c["end_date"] and c[wd] == "1"}
        for e in exceptions:
            if e["date"] == key:
                (services.add if e["exception_type"] == "1" else services.discard)(e["service_id"])
        active[d] = services
    trips = {t["trip_id"]: (t["route_id"], t["service_id"]) for t in table("trips.txt")}
    trip_end = defaultdict(int)
    with (gtfs / "stop_times.txt").open(encoding="utf-8-sig", newline="") as f:
        for st in csv.DictReader(f):
            h, m, _ = st["arrival_time"].split(":")
            trip_end[st["trip_id"]] = max(trip_end[st["trip_id"]], int(h) * 60 + int(m))
    last_end = {}
    for trip_id, (route_id, service_id) in trips.items():
        for d, services in active.items():
            if service_id in services:
                k = (d, route_id)
                last_end[k] = max(last_end.get(k, 0), trip_end.get(trip_id, 0))
    return last_end, names


def write(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parents[2] / "data" / "transit"))
    ap.add_argument("--gtfs", help="unpacked GTFS folder, e.g. ~/Downloads/smtt-timisoara-ro")
    args = ap.parse_args()
    src = Path(args.dir)
    out = src / "summary"
    out.mkdir(exist_ok=True)

    # coverage from polls.csv
    cov = defaultdict(lambda: {"first": None, "last": None, "ok": 0, "failed": 0, "gap": 0, "prev": None})
    for row in read_rows(src / "polls.csv"):
        ts = dt.datetime.fromisoformat(row["poll_utc"].replace("Z", "+00:00")).timestamp()
        local = dt.datetime.fromtimestamp(ts, TZ)
        sd = (local - dt.timedelta(hours=4)).date().isoformat()
        c = cov[sd]
        m = minutes_in_service_day(ts, sd)
        c["first"] = m if c["first"] is None else min(c["first"], m)
        c["last"] = m if c["last"] is None else max(c["last"], m)
        c["ok" if row["ok"] == "1" else "failed"] += 1
        if row["ok"] == "1":
            if c["prev"] is not None:
                c["gap"] = max(c["gap"], (ts - c["prev"]) / 60)
            c["prev"] = ts
    write(out / "coverage.csv", ["service_date", "first_request", "last_request", "requests_ok", "requests_failed", "longest_gap_min"],
          [[d, hhmm(c["first"]), hhmm(c["last"]), c["ok"], c["failed"], round(c["gap"], 1)] for d, c in sorted(cov.items())])

    # vehicles.csv
    hour = defaultdict(lambda: {"veh": set(), "fixes": 0, "delays": []})
    route = {}
    meta = {}
    for row in read_rows(src / "vehicles.csv"):
        try:
            upd = int(row["updated_at_unix"])
        except ValueError:
            continue
        sd, rid = row["service_date"], row["route_id"]
        m = minutes_in_service_day(upd, sd)
        meta[rid] = (row["mode"], row["line"])
        h = hour[(sd, rid, m // 60)]
        h["veh"].add(row["vehicle_id"])
        h["fixes"] += 1
        if row["delay_sec"] not in ("", None):
            h["delays"].append(int(float(row["delay_sec"])))
        r = route.setdefault((sd, rid), {"veh": set(), "fixes": 0, "first": m, "last": -1, "trip": "", "head": "", "delay": ""})
        r["veh"].add(row["vehicle_id"])
        r["fixes"] += 1
        r["first"] = min(r["first"], m)
        if m >= r["last"]:
            r.update(last=m, trip=row["trip_id"], head=row["headsign"], delay=row["delay_sec"])

    sched, names = ({}, {})
    if args.gtfs:
        sched, names = gtfs_schedule(Path(args.gtfs).expanduser(), sorted({sd for sd, _ in route}))
    line = lambda rid: names.get(rid, meta[rid][1])

    rows = []
    for (sd, rid, hr), h in sorted(hour.items(), key=lambda kv: (kv[0][0], line(kv[0][1]), kv[0][2])):
        d = sorted(h["delays"])
        late = round(sum(x > LATE_SEC for x in d) / len(d), 3) if d else ""
        rows.append([sd, hr, meta[rid][0], line(rid), rid, len(h["veh"]), h["fixes"], pct(d, 0.5), pct(d, 0.9), late])
    write(out / "by_route_hour.csv", ["service_date", "hour", "mode", "line", "route_id", "vehicles", "fixes",
                                      "delay_median_sec", "delay_p90_sec", "late_over_3min_share"], rows)

    rows = []
    for (sd, rid), r in sorted(route.items(), key=lambda kv: (kv[0][0], kv[1]["last"])):
        rows.append([sd, meta[rid][0], line(rid), rid, len(r["veh"]), r["fixes"], hhmm(r["first"]), hhmm(r["last"]),
                     r["trip"], r["head"], r["delay"], hhmm(sched.get((sd, rid)))])
    write(out / "last_seen_by_route.csv", ["service_date", "mode", "line", "route_id", "vehicles", "fixes", "first_seen",
                                           "last_seen", "last_trip_id", "last_headsign", "last_delay_sec",
                                           "scheduled_last_trip_end"], rows)

    print(f"written {out}/coverage.csv, by_route_hour.csv, last_seen_by_route.csv")
    for d, c in sorted(cov.items()):
        print(f"{d}: requests {hhmm(c['first'])}-{hhmm(c['last'])}, ok {c['ok']}, failed {c['failed']}, longest gap {c['gap']:.1f} min")
    night = [(sd, rid, r) for (sd, rid), r in route.items() if r["last"] >= NIGHT_FROM_MIN]
    if night:
        print("lines still seen after 23:00 (service day, line, last fix, scheduled end of last trip):")
        for sd, rid, r in sorted(night, key=lambda x: (x[0], x[2]["last"])):
            print(f"  {sd} {line(rid):>5}  {hhmm(r['last'])}  {hhmm(sched.get((sd, rid))) or '-'}")


if __name__ == "__main__":
    main()
