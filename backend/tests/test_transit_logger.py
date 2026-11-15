"""Scheduling rules of the live transit logger; no network calls."""
import datetime as dt

import pytest

from scripts.transit.logger import TZ, next_local_time
from scripts.transit.tiger_store import SCHEMA, TigerStore, poll_values, vehicle_values


def timestamp(year, month, day, hour, minute, second=0):
    return dt.datetime(year, month, day, hour, minute, second, tzinfo=TZ).timestamp()


def local_result(now):
    return dt.datetime.fromtimestamp(next_local_time("04:05", now), TZ)


def test_auto_stop_is_next_0405_bucharest():
    assert local_result(timestamp(2026, 11, 14, 21, 0)) == dt.datetime(2026, 11, 15, 4, 5, tzinfo=TZ)
    assert local_result(timestamp(2026, 11, 15, 4, 4, 59)) == dt.datetime(2026, 11, 15, 4, 5, tzinfo=TZ)


def test_starting_exactly_at_stop_time_schedules_the_next_day():
    assert local_result(timestamp(2026, 11, 15, 4, 5)) == dt.datetime(2026, 11, 16, 4, 5, tzinfo=TZ)


@pytest.mark.parametrize("value", ["", "4", "04:99", "tomorrow"])
def test_bad_stop_time_is_rejected(value):
    with pytest.raises(ValueError, match="HH:MM"):
        next_local_time(value, timestamp(2026, 11, 14, 21, 0))


VEHICLE = {
    "poll_utc": "2026-11-14T20:00:06Z", "service_date": "2026-11-14", "vehicle_id": "42",
    "mode": "tram", "line": "4", "route_id": "R_TV_4", "trip_id": "trip-1",
    "direction_id": "1", "headsign": "Torontalului", "lat": "45.75", "lon": "21.22",
    "bearing": "90", "speed": "8.5", "status": "IN_TRANSIT_TO", "stop_id": "stop-1",
    "stop_sequence": "8", "delay_sec": "120", "wheelchair": "1",
    "updated_at_utc": "2026-11-14T20:00:05Z", "fix_age_sec": "1",
}
POLL = {
    "poll_utc": "2026-11-14T20:00:06Z", "http_status": "200", "ok": "1", "duration_ms": "83",
    "realtime_age_sec": "2", "refresh_in_sec": "5", "vehicles_total": "73", "new_rows": "42", "error": "",
}


def test_tiger_rows_are_typed_and_nullable():
    vehicle = vehicle_values(VEHICLE)
    assert vehicle[0] == "2026-11-14T20:00:05Z"
    assert vehicle[3] == "42"
    assert vehicle[10:12] == (45.75, 21.22)
    assert vehicle[18] is True
    assert poll_values(POLL) == ("2026-11-14T20:00:06Z", 200, True, 83, 2.0, 5.0, 73, 42, None)


def test_tiger_poll_accepts_fractional_source_freshness():
    poll = {**POLL, "realtime_age_sec": "2.4", "refresh_in_sec": "5.9"}
    values = poll_values(poll)
    assert values[4:6] == (2.4, 5.9)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def executemany(self, query, rows):
        self.connection.batches.append((query, rows))


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class FakeConnection:
    def __init__(self):
        self.schema = []
        self.batches = []
        self.closed = False

    def transaction(self):
        return FakeTransaction()

    def execute(self, statement):
        self.schema.append(statement)

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def test_tiger_store_creates_schema_and_batches_both_logs():
    connection = FakeConnection()
    store = TigerStore("postgresql://example", connect=lambda: connection, log=lambda *_a, **_k: None)
    assert store.write([VEHICLE], [POLL]) is True
    assert connection.schema == list(SCHEMA)
    assert len(connection.batches) == 2
    assert len(connection.batches[0][1]) == 1


def test_tiger_failure_is_best_effort_and_retries_later():
    attempts = 0

    def fail():
        nonlocal attempts
        attempts += 1
        raise OSError("database is down")

    store = TigerStore("postgresql://example", connect=fail, retry_sec=30, clock=lambda: 10,
                       log=lambda *_a, **_k: None)
    assert store.write([VEHICLE], [POLL]) is False
    assert "database is down" in store.last_error
    assert store.write([VEHICLE], [POLL]) is False
    assert attempts == 1


class Denied(Exception):
    sqlstate = "42501"


class InsertOnlyConnection(FakeConnection):
    """A login that may insert but not create or alter: the first schema statement is refused."""

    def __init__(self, tables_exist=True):
        super().__init__()
        self.tables_exist = tables_exist

    def execute(self, statement):
        if statement in SCHEMA:
            raise Denied("permission denied for schema public")
        self.schema.append(statement)
        return type("Result", (), {"fetchone": lambda _self: (self.tables_exist,)})()


def test_an_insert_only_login_writes_when_the_owner_has_made_the_tables():
    connection = InsertOnlyConnection()
    store = TigerStore("postgresql://example", connect=lambda: connection, log=lambda *_a, **_k: None)
    assert store.write([VEHICLE], [POLL]) is True
    assert len(connection.batches) == 2


def test_an_insert_only_login_without_tables_is_an_error_not_a_silent_skip():
    connection = InsertOnlyConnection(tables_exist=False)
    store = TigerStore("postgresql://example", connect=lambda: connection, log=lambda *_a, **_k: None)
    assert store.write([VEHICLE], [POLL]) is False
    assert "permission denied" in store.last_error and connection.batches == []
