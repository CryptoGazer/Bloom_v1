"""Optional Tiger Data sink for the live transit logger.

The CSV files remain the durable local spool.  This module is deliberately
independent from FastAPI and imports psycopg only when a Tiger connection is
actually configured, so the logger can still run with the standard library.
"""
from __future__ import annotations

import time


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS transit_vehicle_fixes (
        fix_at         TIMESTAMPTZ NOT NULL,
        polled_at      TIMESTAMPTZ NOT NULL,
        service_date   DATE NOT NULL,
        vehicle_id     TEXT NOT NULL,
        mode           TEXT,
        line           TEXT,
        route_id       TEXT,
        trip_id        TEXT,
        direction_id   SMALLINT,
        headsign       TEXT,
        lat             DOUBLE PRECISION NOT NULL,
        lon             DOUBLE PRECISION NOT NULL,
        bearing         REAL,
        speed           REAL,
        status          TEXT,
        stop_id         TEXT,
        stop_sequence   INTEGER,
        delay_sec       INTEGER,
        wheelchair      BOOLEAN,
        fix_age_sec     INTEGER,
        PRIMARY KEY (vehicle_id, fix_at)
    )
    """,
    "SELECT create_hypertable('transit_vehicle_fixes', by_range('fix_at'), if_not_exists => TRUE)",
    "CREATE INDEX IF NOT EXISTS transit_fixes_route_time_idx ON transit_vehicle_fixes (route_id, fix_at DESC)",
    "CREATE INDEX IF NOT EXISTS transit_fixes_vehicle_time_idx ON transit_vehicle_fixes (vehicle_id, fix_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS transit_polls (
        polled_at          TIMESTAMPTZ NOT NULL PRIMARY KEY,
        http_status        SMALLINT,
        ok                 BOOLEAN NOT NULL,
        duration_ms        INTEGER,
        realtime_age_sec   DOUBLE PRECISION,
        refresh_in_sec     DOUBLE PRECISION,
        vehicles_total     INTEGER,
        new_rows           INTEGER NOT NULL,
        error              TEXT
    )
    """,
    # Early prototypes used INTEGER here, but the municipal API also returns values such as 1.1 and 5.9.
    "ALTER TABLE transit_polls ALTER COLUMN realtime_age_sec TYPE DOUBLE PRECISION USING realtime_age_sec::DOUBLE PRECISION",
    "ALTER TABLE transit_polls ALTER COLUMN refresh_in_sec TYPE DOUBLE PRECISION USING refresh_in_sec::DOUBLE PRECISION",
    "SELECT create_hypertable('transit_polls', by_range('polled_at'), if_not_exists => TRUE)",
)

VEHICLE_INSERT = """
    INSERT INTO transit_vehicle_fixes (
        fix_at, polled_at, service_date, vehicle_id, mode, line, route_id, trip_id,
        direction_id, headsign, lat, lon, bearing, speed, status, stop_id,
        stop_sequence, delay_sec, wheelchair, fix_age_sec
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (vehicle_id, fix_at) DO NOTHING
"""

POLL_INSERT = """
    INSERT INTO transit_polls (
        polled_at, http_status, ok, duration_ms, realtime_age_sec,
        refresh_in_sec, vehicles_total, new_rows, error
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (polled_at) DO NOTHING
"""


def _optional(row, key, cast=str):
    value = row.get(key)
    if value is None or value == "":
        return None
    return cast(value)


def _boolean(value, *, nullable=False):
    if value is None or value == "":
        return None if nullable else False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes"}


def vehicle_values(row):
    """Typed database values from one DictWriter/DictReader-shaped vehicle row."""
    return (
        row["updated_at_utc"], row["poll_utc"], row["service_date"], str(row["vehicle_id"]),
        _optional(row, "mode"), _optional(row, "line"), _optional(row, "route_id"),
        _optional(row, "trip_id"), _optional(row, "direction_id", int), _optional(row, "headsign"),
        float(row["lat"]), float(row["lon"]), _optional(row, "bearing", float),
        _optional(row, "speed", float), _optional(row, "status"), _optional(row, "stop_id"),
        _optional(row, "stop_sequence", int), _optional(row, "delay_sec", int),
        _boolean(row.get("wheelchair"), nullable=True), _optional(row, "fix_age_sec", int),
    )


def poll_values(row):
    """Typed database values from one DictWriter/DictReader-shaped poll row."""
    return (
        row["poll_utc"], _optional(row, "http_status", int), _boolean(row.get("ok")),
        _optional(row, "duration_ms", int), _optional(row, "realtime_age_sec", float),
        _optional(row, "refresh_in_sec", float), _optional(row, "vehicles_total", int),
        int(row.get("new_rows") or 0), _optional(row, "error"),
    )


class TigerStore:
    """Long-lived, retrying connection to Tiger Data.

    ``write`` is best-effort for the logger: on an error it closes the broken
    connection, schedules a reconnect and returns False. ``write_or_raise`` is
    used by the explicit CSV catch-up command, where a failure must be visible.
    """

    def __init__(self, dsn, retry_sec=30, connect=None, clock=time.monotonic, log=print):
        self.dsn = dsn.strip()
        self.retry_sec = max(1, retry_sec)
        self._connect = connect
        self._clock = clock
        self._log = log
        self._conn = None
        self._retry_at = 0.0
        self.last_error = ""

    @property
    def configured(self):
        return bool(self.dsn)

    def _default_connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is not installed; install backend/requirements.txt") from exc
        return psycopg.connect(self.dsn, connect_timeout=8, autocommit=True)

    def _ensure_connection(self):
        if self._conn is not None:
            return self._conn
        self._conn = self._connect() if self._connect else self._default_connect()
        with self._conn.transaction():
            for statement in SCHEMA:
                self._conn.execute(statement)
        self._log("tiger: connected; schema is ready", flush=True)
        return self._conn

    def _write(self, vehicles, polls):
        conn = self._ensure_connection()
        with conn.transaction():
            with conn.cursor() as cursor:
                if vehicles:
                    cursor.executemany(VEHICLE_INSERT, [vehicle_values(row) for row in vehicles])
                if polls:
                    cursor.executemany(POLL_INSERT, [poll_values(row) for row in polls])
        self.last_error = ""

    def write(self, vehicles=(), polls=()):
        if not self.configured:
            return False
        if self._clock() < self._retry_at:
            return False
        try:
            self._write(vehicles, polls)
            return True
        except Exception as exc:  # the CSV spool must survive any DB/driver/schema failure
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            self.close()
            self._retry_at = self._clock() + self.retry_sec
            self._log(f"tiger: write unavailable; CSV retained; retry in {self.retry_sec:g}s: {self.last_error}",
                      flush=True)
            return False

    def write_or_raise(self, vehicles=(), polls=()):
        """Write a catch-up batch and fail loudly instead of silently skipping it."""
        try:
            self._write(vehicles, polls)
        except Exception:
            self.close()
            raise

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

