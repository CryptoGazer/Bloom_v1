"""How each line really ran on recent days: our own history of the city's live vehicles, kept in Tiger Data.

The logger (scripts/transit/logger.py) stores every GPS fix with the delay the city reports. Tiger keeps a
summary per line, direction and 15 minutes (the continuous aggregate transit_line_15m, made by
scripts/transit/tiger_setup.py). This module reads that summary in the background and answers from memory:
a route request never waits for the database, and without the database a ride simply has no history.

A ride gets the most recent service day before it on which the same line ran in the same direction around the
same hour at least `min_trips` times, and what the reported delay was then. It is an observation, not a
forecast, and the advice only ever says "come earlier" or "it may be late", never "you can leave later":
missing the last trip costs more than waiting for it.
"""
import datetime as dt
import math
import os
import threading
import time
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Bucharest")

# All numbers are settings. The delay limits and the early/late thresholds are also stored in the Tiger view
# (scripts/transit/tiger_setup.py): change them there too.
HISTORY = {
    "days_back": 7,               # how far back to look for a day with data
    "slot_min": 30,               # departures are grouped by half hour
    "window_min": 60,             # a group looks at the fixes from an hour before it to an hour after it
    "min_trips": 3,               # fewer observed trips say nothing: no history is shown
    "min_trip_fixes": 4,          # a trip seen in fewer fixes is not counted
    "on_time_s": 60,              # a median within a minute of the timetable reads as "on time"
    "early_advice_s": 60,         # "come earlier" if one fix in ten was further ahead than the boarding margin
    "late_advice_s": 300,         # "it may be late" if one fix in ten was at least 5 min behind
    "max_early_min": 10,
    "max_late_min": 30,
    "last_seen_within_min": 120,  # the day's last sighting is given for rides in the last two hours of service
    "day_starts_h": 4,            # a service day runs 04:00-04:00, as in the logger
    "delay_min_s": -10 * 60,      # as backend/live.py: a reported delay outside [-10, +30] min is not believed
    "delay_max_s": 30 * 60,
    "refresh_s": 15 * 60,         # how often the last two days are read again
    "retry_s": 2 * 60,            # after a failed read
    "connect_timeout_s": 6,
    "statement_timeout_s": 20,
}

_LOCAL = "bucket AT TIME ZONE 'Europe/Bucharest'"
_DAY = f"(({_LOCAL}) - make_interval(hours => %(day_h)s::int))::date"
_MINUTE = f"extract(epoch FROM ({_LOCAL}) - ({_DAY})::timestamp) / 60"   # minutes since the service day's midnight
_BELIEVED = "delay_sec BETWEEN %(delay_min)s::int AND %(delay_max)s::int"
QUERIES = {
    # the delay around every half hour of every service day: the 15-minute sketches of the view, merged
    "stats": f"""
        WITH a AS (
            SELECT {_DAY} AS day, {_MINUTE} AS minute, route_id, headsign, with_delay, delay, early, late
            FROM transit_line_15m
            WHERE bucket >= %(start)s AND bucket < %(end)s AND headsign IS NOT NULL AND with_delay > 0
        )
        SELECT a.day, a.route_id, a.headsign, s.slot,
               sum(a.with_delay)::int AS fixes, sum(a.early)::int AS early, sum(a.late)::int AS late,
               approx_percentile(0.1, rollup(a.delay)) AS p10, approx_percentile(0.5, rollup(a.delay)) AS p50,
               approx_percentile(0.9, rollup(a.delay)) AS p90
        FROM a
        JOIN generate_series(%(first_slot)s::int, %(last_slot)s::int, %(slot)s::int) AS s(slot)
          ON a.minute >= s.slot - %(window)s::int AND a.minute < s.slot + %(slot)s::int + %(window)s::int
        GROUP BY a.day, a.route_id, a.headsign, s.slot""",
    # when each trip was seen, in minutes since its service day's midnight: a trip cannot be counted from 15-minute rows
    "trips": f"""
        SELECT service_date AS day, route_id, headsign,
               (extract(epoch FROM (min(fix_at) AT TIME ZONE 'Europe/Bucharest') - service_date::timestamp) / 60)::int AS first_min,
               (extract(epoch FROM (max(fix_at) AT TIME ZONE 'Europe/Bucharest') - service_date::timestamp) / 60)::int AS last_min
        FROM transit_vehicle_fixes
        WHERE fix_at >= %(start)s AND fix_at < %(end)s AND route_id IS NOT NULL AND trip_id IS NOT NULL
          AND headsign IS NOT NULL AND {_BELIEVED}
        GROUP BY service_date, route_id, headsign, trip_id
        HAVING count(*) >= %(min_trip_fixes)s::int""",
    # each line and direction on each service day: its name and when it was last seen running
    "lines": f"""
        SELECT {_DAY} AS day, route_id, headsign, max(line) AS line, max(mode) AS mode,
               sum(fixes)::int AS fixes, max(last_run) AS last_run
        FROM transit_line_15m
        WHERE bucket >= %(start)s AND bucket < %(end)s AND headsign IS NOT NULL
        GROUP BY 1, route_id, headsign""",
}


def norm(headsign):
    """Headsigns of the timetable and of the live feed are compared without case and extra spaces."""
    return " ".join(str(headsign).split()).casefold()


def hhmm(minute):
    """Minutes since a service day's midnight -> 'HH:MM' on the wall clock (1450 -> 00:10)."""
    return f"{minute // 60 % 24:02d}:{minute % 60:02d}"


def service_day(moment, day_starts_h=HISTORY["day_starts_h"]):
    """The service day of a local wall-clock datetime: before 04:00 it is still yesterday's."""
    return (moment - dt.timedelta(hours=day_starts_h)).date()


def minute_of(moment, day):
    """Minutes from the midnight of service day `day` to a local wall-clock datetime; past 1440 after midnight."""
    return int((moment.replace(tzinfo=None) - dt.datetime.combine(day, dt.time())).total_seconds() // 60)


def local(moment):
    """A timestamp from the database as local wall-clock time."""
    return moment.astimezone(LOCAL_TZ).replace(tzinfo=None)


def tiger_loader(dsn, settings=HISTORY):
    """load(first_day, last_day) -> {query name: rows} read from Tiger Data with a read-only transaction."""
    def load(first_day, last_day):
        import psycopg  # needed only when a database is configured
        from psycopg.rows import dict_row
        starts = dt.time(settings["day_starts_h"])
        params = {
            "start": dt.datetime.combine(first_day, starts, tzinfo=LOCAL_TZ),
            "end": dt.datetime.combine(last_day + dt.timedelta(days=1), starts, tzinfo=LOCAL_TZ),
            "day_h": settings["day_starts_h"], "slot": settings["slot_min"], "window": settings["window_min"],
            "first_slot": settings["day_starts_h"] * 60, "last_slot": settings["day_starts_h"] * 60 + 1440 - settings["slot_min"],
            "delay_min": settings["delay_min_s"], "delay_max": settings["delay_max_s"], "min_trip_fixes": settings["min_trip_fixes"],
        }
        with psycopg.connect(dsn, connect_timeout=settings["connect_timeout_s"], row_factory=dict_row) as conn:
            conn.read_only = True
            conn.execute(f"SET LOCAL statement_timeout = {int(settings['statement_timeout_s'] * 1000)}")
            return {name: conn.execute(query, params).fetchall() for name, query in QUERIES.items()}
    return load


def build(rows, first_day, last_day, settings=HISTORY):
    """Rows of the queries -> {day: {...}} with an entry for every day of the range, also for a day without data:
    slots {(route, headsign): {slot: stat}}, lines {(route, headsign): ...}, trips {(route, headsign): [(first, last)]}."""
    slot_min, window = settings["slot_min"], settings["window_min"]
    days = {first_day + dt.timedelta(days=i): {"slots": {}, "lines": {}, "trips": {}}
            for i in range((last_day - first_day).days + 1)}
    stat = lambda r: {"fixes": r["fixes"], "early": r["early"] or 0, "late": r["late"] or 0, "p10": r["p10"], "p50": r["p50"], "p90": r["p90"]}
    for r in rows.get("trips", ()):
        if r["day"] in days:
            days[r["day"]]["trips"].setdefault((r["route_id"], norm(r["headsign"])), []).append((r["first_min"], r["last_min"]))
    for r in rows.get("stats", ()):
        if r["day"] not in days or not r["fixes"] or r["p50"] is None:
            continue
        key, slot = (r["route_id"], norm(r["headsign"])), r["slot"]
        seen = sum(1 for first, last in days[r["day"]]["trips"].get(key, ()) if first < slot + slot_min + window and last >= slot - window)
        days[r["day"]]["slots"].setdefault(key, {})[slot] = {**stat(r), "trips": seen}
    for r in rows.get("lines", ()):
        if r["day"] in days:
            days[r["day"]]["lines"][(r["route_id"], norm(r["headsign"]))] = {
                "route_id": r["route_id"], "headsign": r["headsign"], "line": r["line"], "mode": r["mode"], "fixes": r["fixes"],
                "last_run_min": minute_of(local(r["last_run"]), r["day"]) if r.get("last_run") else None}
    return days


def reading(stat, settings=HISTORY):
    """One delay sketch in words a page can show: the usual delay, how early and how late one fix in ten was,
    what kind of running that is, and the only two kinds of advice we give."""
    S = settings
    be_early = min(S["max_early_min"], math.ceil(-stat["p10"] / 60)) if stat["p10"] < -S["early_advice_s"] else None
    may_wait = min(S["max_late_min"], math.ceil(stat["p90"] / 60)) if stat["p90"] >= S["late_advice_s"] else None
    if be_early and may_wait:
        pattern = "uneven"                      # both far ahead and far behind
    elif abs(stat["p50"]) >= S["on_time_s"]:
        pattern = "early" if stat["p50"] < 0 else "late"
    else:                                       # usually on time; the advice, if any, comes from the one fix in ten
        pattern = "on_time_but_early" if be_early else "on_time_but_late" if may_wait else "on_time"
    return {
        "fixes": stat["fixes"],
        "median_min": round(stat["p50"] / 60, 1), "early_min": round(stat["p10"] / 60, 1), "late_min": round(stat["p90"] / 60, 1),
        "early_share": round(stat["early"] / stat["fixes"], 2), "late_share": round(stat["late"] / stat["fixes"], 2),
        "pattern": pattern, "be_early_min": be_early, "wait_up_to_min": may_wait,
    }


class History:
    def __init__(self, load, settings=HISTORY, clock=None, log=print):
        self._load, self.settings, self._log = load, settings, log
        self._clock = clock or (lambda: dt.datetime.now(LOCAL_TZ).replace(tzinfo=None))  # local wall clock
        self._days = None        # replaced as a whole by refresh(): readers never see a half-built index
        self.loaded_at = None
        self.error = ""

    @classmethod
    def from_env(cls):
        """From TIGER_READ_URL (a read-only login) or TIGER_DATABASE_URL; None if neither is set or TIGER_HISTORY=off."""
        if os.environ.get("TIGER_HISTORY", "").strip().lower() in ("off", "0", "no"):
            return None
        dsn = (os.environ.get("TIGER_READ_URL") or os.environ.get("TIGER_DATABASE_URL") or "").strip()
        return cls(tiger_loader(dsn)) if dsn else None

    @property
    def ready(self):
        return self._days is not None

    def today(self):
        return service_day(self._clock(), self.settings["day_starts_h"])

    def _when(self, day):
        """"yesterday" as a person says it, by the calendar: at 02:00 on Sunday, Saturday evening was yesterday."""
        today = self._clock().date()
        return "today" if day == today else "yesterday" if day == today - dt.timedelta(days=1) else "date"

    def refresh(self):
        """Read what is missing or can still change (today and yesterday). True if the database answered."""
        today = self.today()
        first = today - dt.timedelta(days=self.settings["days_back"])
        have = self._days or {}
        whole = any(first + dt.timedelta(days=i) not in have for i in range(self.settings["days_back"] + 1))
        start = first if whole else today - dt.timedelta(days=1)
        try:
            fresh = build(self._load(start, today), start, today, self.settings)
        except Exception as e:  # the site works without the history; the reason stays in the server log
            self.error = type(e).__name__
            self._log(f"history: Tiger Data did not answer ({self.error}: {str(e)[:160]}); the previous copy stays", flush=True)
            return False
        self._days = {day: data for day, data in {**have, **fresh}.items() if day >= first}
        self.loaded_at, self.error = self._clock(), ""
        return True

    def start(self):
        """Keep the copy fresh from a background thread; the first read does not delay the server's start."""
        def loop():
            while True:
                ok = self.refresh()
                time.sleep(self.settings["refresh_s"] if ok else self.settings["retry_s"])
        threading.Thread(target=loop, name="transit-history", daemon=True).start()
        return self

    def ride(self, leg):
        """What we saw of this ride's line, in its direction, around its hour, on the most recent day with enough
        trips; None without such a day. `leg` is a ride of backend/transit.py: route_id, headsign, day, dep_s."""
        days, S = self._days, self.settings
        if not days or not leg.get("route_id") or not leg.get("headsign"):
            return None
        try:
            dep = dt.datetime.combine(dt.date.fromisoformat(leg["day"]), dt.time()) + dt.timedelta(seconds=leg["dep_s"])
        except (KeyError, TypeError, ValueError):
            return None
        service = service_day(dep, S["day_starts_h"])
        minute = minute_of(dep, service)
        slot = minute // S["slot_min"] * S["slot_min"]
        key = (leg["route_id"], norm(leg["headsign"]))
        for back in range(1, S["days_back"] + 1):
            day = service - dt.timedelta(days=back)
            data = days.get(day)
            stat = data["slots"].get(key, {}).get(slot) if data else None
            if not stat or stat["trips"] < S["min_trips"]:
                continue
            last = (data["lines"].get(key) or {}).get("last_run_min")
            return {
                "day": day.isoformat(), "when": self._when(day),
                "from": hhmm(slot - S["window_min"]), "to": hhmm(slot + S["slot_min"] + S["window_min"]),
                "trips": stat["trips"], **reading(stat, S),
                "last_seen": hhmm(last) if last is not None and minute >= last - S["last_seen_within_min"] else None,
            }
        return None
