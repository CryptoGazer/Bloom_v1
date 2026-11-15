"""Append-only logger of live vehicle positions from Primăria Timișoara.

Polls GET https://cont.primariatm.ro/api/mobile/transit/vehicles every --interval seconds and appends to:
  <dir>/vehicles.csv  one row per NEW GPS fix (a vehicle whose updatedAt changed since it was last written)
  <dir>/polls.csv     one row per request, successful or not (shows gaps: logger stopped, API down)
If TIGER_DATABASE_URL is set in the environment or project .env, the same rows are also written to
Tiger Data. CSV is always flushed first and remains the catch-up spool if the database is unavailable.
Existing files are never truncated: rows are only appended, the header is written once, and after a
restart the logger reads the tail of vehicles.csv so it does not write the same fixes twice.

usage: python3 -I scripts/transit/logger.py [--dir data/transit] [--interval 15] [--stop-at 04:05] [--max-polls N]
The API reports its next refresh in each response; use about 6 s for full-resolution logging, or 15 s
for a lower request rate when every intermediate GPS fix is not needed.
By default it stops at the next 04:05 in Europe/Bucharest. Stop earlier with Ctrl+C or SIGTERM
(scripts/transit/logger.sh stop). Standard library only.
"""
import argparse
import csv
import datetime as dt
try:
    import fcntl
except ImportError:      # Windows: msvcrt locks the file instead
    fcntl = None
    import msvcrt
import gzip
import importlib.util
import json
import os
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__:
    from .tiger_store import TigerStore
else:  # ``python -I path/to/logger.py`` intentionally omits the script directory from sys.path
    _tiger_spec = importlib.util.spec_from_file_location("transit_tiger_store", Path(__file__).with_name("tiger_store.py"))
    _tiger_module = importlib.util.module_from_spec(_tiger_spec)
    _tiger_spec.loader.exec_module(_tiger_module)
    TigerStore = _tiger_module.TigerStore

URL = "https://cont.primariatm.ro/api/mobile/transit/vehicles"
DEFAULT_UA = "UniHack26-NightRoute-team/0.1 (UniHack 2026 hackathon prototype; transit logger)"
TZ = ZoneInfo("Europe/Bucharest")
SERVICE_DAY_START_HOUR = 4  # fixes before 04:00 local belong to the previous service day
DEFAULT_STOP_AT = "04:05"
MAX_BACKOFF_SEC = 300
TAIL_BYTES = 4_000_000
ROOT = Path(__file__).resolve().parents[2]

MODES = {"TV": "tram", "TB": "trolleybus", "AB": "bus"}
VEHICLE_COLUMNS = [
    "poll_utc", "poll_local", "service_date", "vehicle_id", "mode", "line", "route_id", "trip_id",
    "direction_id", "headsign", "lat", "lon", "bearing", "speed", "status", "stop_id", "stop_sequence",
    "delay_sec", "wheelchair", "updated_at_unix", "updated_at_utc", "fix_age_sec",
]
POLL_COLUMNS = [
    "poll_utc", "poll_local", "http_status", "ok", "duration_ms", "realtime_age_sec", "refresh_in_sec",
    "vehicles_total", "new_rows", "error",
]

stop_requested = False


def load_env(path):
    """KEY=VALUE lines into the environment; explicitly exported variables win."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def on_signal(signum, _frame):
    global stop_requested
    stop_requested = True


def utc_iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_iso(ts):
    return dt.datetime.fromtimestamp(ts, TZ).isoformat(timespec="seconds")


def service_date(ts):
    local = dt.datetime.fromtimestamp(ts, TZ)
    return (local - dt.timedelta(hours=SERVICE_DAY_START_HOUR)).date().isoformat()


def next_local_time(value, now_ts=None):
    """Unix timestamp of the next HH:MM in Europe/Bucharest, strictly after now."""
    try:
        hour, minute = (int(part) for part in value.split(":"))
        clock = dt.time(hour, minute)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("--stop-at must be local time as HH:MM, e.g. 04:05")
    now = dt.datetime.fromtimestamp(time.time() if now_ts is None else now_ts, TZ)
    target = dt.datetime.combine(now.date(), clock, TZ)
    if target <= now:
        target = dt.datetime.combine(now.date() + dt.timedelta(days=1), clock, TZ)
    return target.timestamp()


def split_route(route_id):
    parts = (route_id or "").split("_", 2)
    if len(parts) == 3 and parts[0] == "R":
        return MODES.get(parts[1], parts[1].lower()), parts[2]
    return "", route_id or ""


def bool01(v):
    return "" if v is None else ("1" if v else "0")


def open_append(path, columns):
    """Open a CSV for appending. Writes the header only into a new or empty file; refuses a file whose
    header differs (so a schema change never mixes columns); repairs a missing final newline."""
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
        if header != columns:
            sys.exit(f"{path}: header differs from the expected columns. Move the file away; it is left untouched.")
        with path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            last = f.read(1)
        fh = path.open("a", encoding="utf-8", newline="")
        if last != b"\n":
            fh.write("\n")
        return fh, csv.writer(fh)
    fh = path.open("a", encoding="utf-8", newline="")
    writer = csv.writer(fh)
    writer.writerow(columns)
    fh.flush()
    return fh, writer


def last_fixes(path):
    """vehicle_id -> updated_at_unix of the newest row already in vehicles.csv (reads only the tail)."""
    seen = {}
    if not path.exists() or path.stat().st_size == 0:
        return seen
    vid, upd = VEHICLE_COLUMNS.index("vehicle_id"), VEHICLE_COLUMNS.index("updated_at_unix")
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read().decode("utf-8", errors="replace")
    lines = chunk.splitlines()
    if size > TAIL_BYTES:
        lines = lines[1:]  # first line is probably cut
    for row in csv.reader(lines):
        if len(row) != len(VEHICLE_COLUMNS) or row[0] == "poll_utc":
            continue
        try:
            seen[row[vid]] = max(seen.get(row[vid], 0), int(row[upd]))
        except ValueError:
            continue
    return seen


CA_BUNDLES = ["/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem", "/usr/local/etc/ca-certificates/cert.pem"]


def make_ssl_context():
    """python.org builds on macOS ship without root certificates until 'Install Certificates.command' is run.
    Fall back to the system bundle (or certifi) so HTTPS works anyway; verification stays on."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) > 0:
        return ctx
    for path in CA_BUNDLES:
        if os.path.exists(path):
            ctx.load_verify_locations(cafile=path)
            return ctx
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except ImportError:
        print("no CA bundle found: HTTPS may fail (run 'Install Certificates.command' of your Python)", flush=True)
    return ctx


SSL_CONTEXT = make_ssl_context()


def fetch(user_agent, timeout):
    req = urllib.request.Request(URL, headers={
        "User-Agent": user_agent, "Accept": "application/json", "Accept-Encoding": "gzip"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            status = r.status
        payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get("vehicles"), list):
            return status, None, "unexpected JSON shape", time.monotonic() - t0
        return status, payload, "", time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}", time.monotonic() - t0
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", None, f"{type(e).__name__}: {getattr(e, 'reason', e)}"[:200], time.monotonic() - t0
    except ValueError as e:
        return "", None, f"bad JSON: {e}"[:200], time.monotonic() - t0


def vehicle_row(v, poll_ts):
    mode, line = split_route(v.get("routeId"))
    upd = v.get("updatedAt")
    return [
        utc_iso(poll_ts), local_iso(poll_ts), service_date(poll_ts), v.get("id"), mode, line, v.get("routeId"),
        v.get("tripId"), v.get("directionId"), v.get("headsign"), v.get("lat"), v.get("lon"), v.get("bearing"),
        v.get("speed"), v.get("status"), v.get("stopId"), v.get("stopSequence"), v.get("delaySec"),
        bool01(v.get("wheelchair")), upd, utc_iso(upd) if isinstance(upd, (int, float)) else "",
        int(poll_ts - upd) if isinstance(upd, (int, float)) else "",
    ]


def keep_mac_awake():
    if sys.platform == "darwin":
        try:  # caffeinate exits by itself when this process exits
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        except OSError:
            print("caffeinate not available: the Mac may sleep and stop the logger", flush=True)


def main():
    load_env(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(ROOT / "data" / "transit"))
    ap.add_argument("--interval", type=float, default=15.0, help="seconds between requests (min 5, default 15)")
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--user-agent", default=os.environ.get("TRANSIT_LOGGER_UA", DEFAULT_UA))
    ap.add_argument("--stop-at", default=DEFAULT_STOP_AT,
                    help=f"stop at the next local HH:MM in Europe/Bucharest (default {DEFAULT_STOP_AT})")
    ap.add_argument("--max-polls", type=int, default=0, help="stop after N requests (0 = run until stopped)")
    ap.add_argument("--no-caffeinate", action="store_true")
    ap.add_argument("--no-tiger", action="store_true", help="ignore TIGER_DATABASE_URL and write CSV only")
    ap.add_argument("--tiger-retry", type=float, default=30.0,
                    help="seconds between Tiger reconnect attempts after an error (default 30)")
    args = ap.parse_args()
    interval = max(5.0, args.interval)
    try:
        stop_ts = next_local_time(args.stop_at)
    except ValueError as e:
        ap.error(str(e))

    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / ".logger.lock").open("w")
    try:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except (BlockingIOError, OSError):
        sys.exit(f"Another logger is already writing to {out}. Stop it first (scripts/transit/logger.sh stop).")
    pid_path = out / "logger.pid"
    pid_path.write_text(str(os.getpid()))
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if not args.no_caffeinate:
        keep_mac_awake()

    seen = last_fixes(out / "vehicles.csv")
    vfh, vw = open_append(out / "vehicles.csv", VEHICLE_COLUMNS)
    pfh, pw = open_append(out / "polls.csv", POLL_COLUMNS)
    tiger_dsn = "" if args.no_tiger else os.environ.get("TIGER_DATABASE_URL", "")
    tiger = TigerStore(tiger_dsn, retry_sec=args.tiger_retry)
    print(f"{local_iso(time.time())} start pid={os.getpid()} interval={interval:g}s dir={out} "
          f"known vehicles={len(seen)} auto_stop={local_iso(stop_ts)} "
          f"tiger={'configured' if tiger.configured else 'off'}", flush=True)

    polls = failures = 0
    try:
        while not stop_requested and time.time() < stop_ts:
            started = time.monotonic()
            poll_ts = time.time()
            status, payload, error, took = fetch(args.user_agent, args.timeout)
            new_rows = 0
            tiger_vehicles = []
            if payload is not None:
                failures = 0
                for v in payload["vehicles"]:
                    vid, upd = v.get("id"), v.get("updatedAt")
                    if vid is None or upd is None or seen.get(str(vid)) == upd:
                        continue
                    seen[str(vid)] = upd
                    row = vehicle_row(v, poll_ts)
                    vw.writerow(row)
                    tiger_vehicles.append(dict(zip(VEHICLE_COLUMNS, row)))
                    new_rows += 1
            else:
                failures += 1
            poll_row = [
                utc_iso(poll_ts), local_iso(poll_ts), status, "1" if payload is not None else "0", int(took * 1000),
                (payload or {}).get("realtimeAgeSec", ""), (payload or {}).get("refreshInSec", ""),
                len(payload["vehicles"]) if payload else "", new_rows, error,
            ]
            pw.writerow(poll_row)
            for fh in (vfh, pfh):
                fh.flush()
                os.fsync(fh.fileno())
            tiger_ok = tiger.write(tiger_vehicles, [dict(zip(POLL_COLUMNS, poll_row))]) if tiger.configured else False
            polls += 1
            total = len(payload["vehicles"]) if payload else 0
            print(f"{local_iso(poll_ts)} {'ok ' if payload else 'ERR'} vehicles={total} new_rows={new_rows}"
                  + (" tiger=ok" if tiger_ok else (" tiger=pending" if tiger.configured else ""))
                  + (f" error={error}" if error else ""), flush=True)
            if args.max_polls and polls >= args.max_polls:
                break
            wait = interval if failures == 0 else min(MAX_BACKOFF_SEC, interval * 2 ** min(failures, 6))
            deadline = started + wait
            while not stop_requested and time.time() < stop_ts and time.monotonic() < deadline:
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
    finally:
        tiger.close()
        vfh.close()
        pfh.close()
        if pid_path.exists() and pid_path.read_text().strip() == str(os.getpid()):
            pid_path.unlink()
        reason = "auto-stop" if time.time() >= stop_ts else "requested"
        print(f"{local_iso(time.time())} stop after {polls} polls reason={reason}", flush=True)


if __name__ == "__main__":
    main()
