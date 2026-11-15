"""Tiger Data setup for the transit history: the summary the site reads, housekeeping, limited users.

Every command is safe to run again. It needs the owner's TIGER_DATABASE_URL (tsdbadmin) in .env or the environment.

  views    transit_line_15m: a continuous aggregate over transit_vehicle_fixes (line x direction x 15 minutes:
           fixes, a percentile sketch of the reported delay, early / late counts, first and last fix), refreshed
           by Tiger every 15 minutes; day-sized chunks, compression after 2 days, raw rows dropped after 30 days
           (the summary stays)
  roles    two logins for the server instead of the owner's password: bezna_web may only read, bezna_logger may
           only read and insert into the two raw tables. Their URLs are written to --env-out (mode 600) and are
           never printed. Running it again changes both passwords
  status   sizes, chunks, jobs, how fresh the summary is

usage: .venv/bin/python -I scripts/transit/tiger_setup.py views|roles|status [--env-out FILE]
"""
import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]

# The thresholds are stored inside the view: after changing them, drop the view and run `views` again.
# delay_min/max mirror backend/live.py (LIVE), early/late mirror backend/history.py (HISTORY).
VIEW = "transit_line_15m"
DELAY_MIN_S, DELAY_MAX_S = -600, 1800   # a reported delay outside [-10, +30] min is not believed
EARLY_S, LATE_S = -60, 180              # "early": over a minute ahead; "late": over three minutes behind

CREATE_VIEW = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {VIEW}
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '15 minutes', fix_at) AS bucket,
       route_id, direction_id, headsign,
       max(line) AS line, max(mode) AS mode,
       count(*) AS fixes,
       count(*) FILTER (WHERE delay_sec BETWEEN {DELAY_MIN_S} AND {DELAY_MAX_S}) AS with_delay,
       percentile_agg(delay_sec::double precision)
           FILTER (WHERE delay_sec BETWEEN {DELAY_MIN_S} AND {DELAY_MAX_S}) AS delay,
       count(*) FILTER (WHERE delay_sec >= {DELAY_MIN_S} AND delay_sec < {EARLY_S}) AS early,
       count(*) FILTER (WHERE delay_sec > {LATE_S} AND delay_sec <= {DELAY_MAX_S}) AS late,
       min(fix_at) AS first_seen, max(fix_at) AS last_seen,
       -- the last fix that still carried a delay: a vehicle parked after its trip keeps reporting without one
       max(fix_at) FILTER (WHERE delay_sec BETWEEN {DELAY_MIN_S} AND {DELAY_MAX_S}) AS last_run
FROM transit_vehicle_fixes
WHERE route_id IS NOT NULL
GROUP BY 1, route_id, direction_id, headsign
WITH NO DATA
"""

VIEWS = (
    ("summary view", CREATE_VIEW),
    # the newest, not yet materialised minutes are computed on the fly, so the view is never behind the raw table
    ("real-time tail", f"ALTER MATERIALIZED VIEW {VIEW} SET (timescaledb.materialized_only = false)"),
    ("first fill", f"CALL refresh_continuous_aggregate('{VIEW}', NULL, NULL)"),
    ("refresh every 15 min", f"""SELECT add_continuous_aggregate_policy('{VIEW}', start_offset => INTERVAL '3 days',
        end_offset => INTERVAL '15 minutes', schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE)"""),
    ("day-sized chunks", "SELECT set_chunk_time_interval('transit_vehicle_fixes', INTERVAL '1 day')"),
    ("compress after 2 days", "SELECT add_compression_policy('transit_vehicle_fixes', compress_after => INTERVAL '2 days', if_not_exists => TRUE)"),
    ("drop raw fixes after 30 days", "SELECT add_retention_policy('transit_vehicle_fixes', drop_after => INTERVAL '30 days', if_not_exists => TRUE)"),
    ("drop raw polls after 30 days", "SELECT add_retention_policy('transit_polls', drop_after => INTERVAL '30 days', if_not_exists => TRUE)"),
)
ENABLE_COMPRESSION = ("ALTER TABLE transit_vehicle_fixes SET (timescaledb.compress, "
                      "timescaledb.compress_segmentby = 'vehicle_id', timescaledb.compress_orderby = 'fix_at DESC')")

ROLES = {  # login -> (variable in the env file, what it may do)
    "bezna_web": ("TIGER_READ_URL", f"GRANT SELECT ON transit_vehicle_fixes, transit_polls, {VIEW} TO bezna_web"),
    "bezna_logger": ("TIGER_DATABASE_URL", "GRANT SELECT, INSERT ON transit_vehicle_fixes, transit_polls TO bezna_logger"),
}


def load_env(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def connect(dsn):
    import psycopg
    return psycopg.connect(dsn, connect_timeout=10, autocommit=True)  # the view and its refresh cannot run in a transaction


def views(conn):
    enabled = conn.execute("SELECT compression_enabled FROM timescaledb_information.hypertables "
                           "WHERE hypertable_name = 'transit_vehicle_fixes'").fetchone()
    if enabled is None:
        sys.exit("transit_vehicle_fixes is not there yet: run the logger once (it creates the raw tables)")
    if not enabled[0]:
        conn.execute(ENABLE_COMPRESSION)
        print("ok   compression settings")
    for name, statement in VIEWS:
        conn.execute(statement)
        print(f"ok   {name}")


def roles(conn, dsn, env_out):
    from psycopg import sql
    url = urlsplit(dsn)
    database = conn.execute("SELECT current_database()").fetchone()[0]
    lines = []
    for login, (variable, grant) in ROLES.items():
        password = secrets.token_urlsafe(24)
        # only the SCRAM verifier travels in the statement, so the password is in no server log
        verifier = conn.pgconn.encrypt_password(password.encode(), login.encode(), b"scram-sha-256").decode()
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
        conn.execute(sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            sql.SQL("ALTER" if exists else "CREATE"), sql.Identifier(login), sql.Literal(verifier)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(login)))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(login)))
        conn.execute(grant)
        netloc = f"{login}:{quote(password, safe='')}@{url.hostname}" + (f":{url.port}" if url.port else "")
        lines.append(f"{variable}={urlunsplit((url.scheme, netloc, url.path, url.query, ''))}")
        print(f"ok   {login}: {'password changed' if exists else 'created'} -> {variable}")
    out = Path(env_out)
    out.touch(mode=0o600, exist_ok=True)
    out.chmod(0o600)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"URLs written to {out} (not shown here). Put them into the server's .env and delete the file.")


def status(conn):
    rows = lambda q: conn.execute(q).fetchall()
    print("database:", rows("SELECT pg_size_pretty(pg_database_size(current_database()))")[0][0])
    for name, chunks, compressed, size in rows(
            "SELECT hypertable_name, num_chunks, compression_enabled, pg_size_pretty(hypertable_size(format('%I', hypertable_name)::regclass)) "
            "FROM timescaledb_information.hypertables WHERE hypertable_schema = 'public' ORDER BY 1"):
        print(f"  {name}: {size}, {chunks} chunk(s), compression {'on' if compressed else 'off'}")
    print("raw fixes:", rows("SELECT count(*), min(fix_at), max(fix_at) FROM transit_vehicle_fixes")[0])
    if rows(f"SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_name = '{VIEW}'"):
        print(f"{VIEW}:", rows(f"SELECT count(*), min(bucket), max(bucket), sum(fixes) FROM {VIEW}")[0])
    else:
        print(f"{VIEW}: not created (run `views`)")
    for job in rows("SELECT j.job_id, j.proc_name, coalesce(j.hypertable_name, ''), j.schedule_interval, s.last_run_status, s.last_successful_finish "
                    "FROM timescaledb_information.jobs j LEFT JOIN timescaledb_information.job_stats s USING (job_id) "
                    "WHERE j.proc_schema IN ('_timescaledb_functions', '_timescaledb_internal') AND j.hypertable_name IS NOT NULL ORDER BY 1"):
        print("  job", *job)
    print("logins:", [r[0] for r in rows("SELECT rolname FROM pg_roles WHERE rolname LIKE 'bezna_%' ORDER BY 1")])


def main():
    load_env(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("views", "roles", "status"))
    ap.add_argument("--env-out", help="roles: file that receives TIGER_READ_URL and the logger's TIGER_DATABASE_URL")
    args = ap.parse_args()
    dsn = os.environ.get("TIGER_DATABASE_URL", "").strip()
    if not dsn:
        sys.exit("TIGER_DATABASE_URL is not set (the owner's URL, in .env)")
    if args.command == "roles" and not args.env_out:
        ap.error("roles needs --env-out FILE")
    with connect(dsn) as conn:
        if args.command == "views":
            views(conn)
        elif args.command == "roles":
            roles(conn, dsn, args.env_out)
        status(conn)


if __name__ == "__main__":
    main()
