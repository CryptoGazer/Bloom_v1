"""Scheduling rules of the live transit logger; no network calls."""
import datetime as dt

import pytest

from scripts.transit.logger import TZ, next_local_time


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
