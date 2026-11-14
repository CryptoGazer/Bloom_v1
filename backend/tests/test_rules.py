"""The agreed lighting rules (spec section 7) as a table of cases, plus the build steps around them.

Run: .venv/bin/python -m pytest backend/tests -q
Every row is a decision taken in the design discussion; if a change breaks one, the test says which.
"""
import datetime as dt

import pytest

from backend import build_city
from backend.build_city import KX, KY
from backend.rules import classify, dark_by_complaints

PARAMS = dict(coverage_min=0.5, fresh_days=30, lamps_out_for_dark=3)

CASES = [
    # name, OSM lit tag, Mapillary coverage, complaint events (kind, age in days), indirect signs, inherited dark,
    # expected status, expected confidence (number of independent sources)
    ("no evidence", None, 0.0, [], [], False, "unknown", 0),
    ("osm tag only", "yes", 0.0, [], [], False, "lit_confirmed", 1),
    ("lamps only", None, 0.6, [], [], False, "lit_confirmed", 1),
    ("lamps exactly at the threshold", None, 0.5, [], [], False, "lit_confirmed", 1),
    ("complaint only", None, 0.0, [("fixed", None)], [], False, "lit_likely", 1),
    ("two families", "yes", 0.8, [], [], False, "lit_confirmed", 2),
    ("three families", "yes", 0.8, [("fixed", None)], [], False, "lit_confirmed", 3),
    ("lit=no beats lamps", "no", 0.9, [], [], False, "dark_reported", 1),
    ("mixed tag is ignored", "mixed", 0.0, [], [], False, "unknown", 0),
    ("fresh area outage", "yes", 0.9, [("open_area_outage", 30)], [], False, "dark_reported", 3),
    ("stale area outage", "yes", 0.0, [("open_area_outage", 31)], [], False, "lit_confirmed", 2),
    ("one fresh lamp out caps at likely", "yes", 0.9, [("open_lamp_out", 5)], [], False, "lit_likely", 3),
    ("two fresh lamps out are not dark", None, 0.9, [("open_lamp_out", 5), ("open_lamp_out", 9)], [], False, "lit_likely", 2),
    ("three fresh lamps out", "yes", 0.9, [("open_lamp_out", 1), ("open_lamp_out", 2), ("open_lamp_out", 3)], [], False, "dark_reported", 3),
    ("stale lamp out does not cap", "yes", 0.0, [("open_lamp_out", 45)], [], False, "lit_confirmed", 2),
    ("declined only", None, 0.0, [("declined", None)], [], False, "unknown", 0),
    ("indirect only", None, 0.2, [], ["partial_lamps"], False, "lit_likely", 0),
    ("inherited dark", None, 0.9, [], ["near_lit_street"], True, "dark_reported", 1),
]


@pytest.mark.parametrize("name, lit, coverage, events, indirect, inherited, status, confidence", CASES, ids=[c[0] for c in CASES])
def test_rules_table(name, lit, coverage, events, indirect, inherited, status, confidence):
    got_status, families = classify(lit, coverage, events, indirect, inherited, **PARAMS)
    assert (got_status, len(families)) == (status, confidence)


def test_families_keep_a_fixed_order():
    assert classify("yes", 0.9, [("fixed", None)], [], False, **PARAMS)[1] == ["osm", "mapillary", "sesizari"]


def test_dark_by_complaints():
    assert dark_by_complaints([("open_area_outage", 3)], 30, 3)
    assert not dark_by_complaints([("open_area_outage", 40), ("open_lamp_out", 2), ("open_lamp_out", 2)], 30, 3)
    assert dark_by_complaints([("open_lamp_out", 1)] * 3, 30, 3)


# ---------- complaint events (30 m / 14 days from the first report) ----------
LAT0, LON0 = 45.75, 21.23
AS_OF = dt.date(2026, 11, 14)
AREA_OUT = "Nu funcționează iluminatul public în zonă"


def lonlat(x, y):
    return [LON0 + x / KX, LAT0 + y / KY]


def complaint(nr, created, status="Finalizata", sub="Bec nefuncțional", x=0.0, y=0.0, closed=None):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": lonlat(x, y)},
            "properties": {"nr": nr, "created_at": created + "T18:00:00.1+00:00", "subcategory": sub, "status": status,
                           "closed_at": closed + "T08:00:00+00:00" if closed else None}}


def test_complaints_glue_into_events_from_the_first_report():
    reports = [complaint("D", "2026-10-16", x=5), complaint("C", "2026-10-15", x=-25), complaint("E", "2026-10-02", x=40),
               complaint("B", "2026-10-05", x=20), complaint("A", "2026-10-01")]
    _, events = build_city.build_events(reports, AS_OF)
    assert [[c["nr"] for c in ev["m"]] for ev in events] == [["A", "B", "C"], ["E"], ["D"]]


@pytest.mark.parametrize(
    "members, kind, age",
    [
        ([("Declinata competenta", "Bec nefuncțional", "2026-11-01")], "declined", None),
        ([("Finalizata", "Bec nefuncțional", "2026-11-01")], "fixed", None),
        ([("In lucru", AREA_OUT, "2026-11-10")], "open_area_outage", 4),
        ([("In lucru", "Bec nefuncțional", "2026-11-01"), ("Inregistrata", "Aparat de iluminat nefuncțional", "2026-11-12")], "open_lamp_out", 2),
        ([("In lucru", "Probleme referitoare la cabluri", "2026-10-15")], "open_other", 30),
        ([("Finalizata", AREA_OUT, "2026-10-01"), ("In lucru", "Bec nefuncțional", "2026-10-05")], "open_lamp_out", 40),
        ([("", "", "2026-11-13")], "open_other", 1),
    ],
)
def test_event_kind_and_age(members, kind, age):
    reports = [complaint(str(i), created, status=status, sub=sub) for i, (status, sub, created) in enumerate(members)]
    _, events = build_city.build_events(reports, AS_OF)
    assert len(events) == 1 and (events[0]["kind"], events[0]["age"]) == (kind, age)


# ---------- the whole classification on a hand-made block ----------
def street(sid, pts, kind="street", name=None, lit=None):
    return {"id": sid, "ll": [lonlat(*p) for p in pts], "kind": kind, "name": name, "lit": lit, "ways": [1]}


def lamp(x, y, year="2024-05-01"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": lonlat(x, y)}, "properties": {"last_seen": year}}


def run(segs, lamps, complaints):
    build_city.classify(segs, lamps, complaints, AS_OF)
    return {s["id"]: s for s in segs}


def test_three_sources_on_a_block():
    got = run([street("A", [(0, 0), (100, 0)], name="Strada A", lit="yes"),
               street("B", [(0, 40), (100, 40)], name="Strada B"),
               street("SA", [(0, -8), (100, -8)], kind="sidewalk"),
               street("P", [(0, 150), (100, 150)], kind="path")],
              [lamp(x, -10) for x in (10, 30, 50, 70, 90)],
              [complaint("Z", "2026-09-01", x=50, y=45)])
    assert (got["A"]["status"], got["A"]["fam"]) == ("lit_confirmed", ["osm", "mapillary"])
    assert (got["B"]["status"], got["B"]["fam"]) == ("lit_likely", ["sesizari"])    # the complaint goes to the nearest street only
    assert got["SA"]["status"] == "lit_confirmed" and "near_lit_street" in got["SA"]["ind"]
    assert got["P"]["status"] == "unknown"


def test_one_lamp_at_the_end_of_a_long_segment_is_not_enough():
    got = run([street("L", [(0, 0), (200, 0)])], [lamp(200, 5)], [])
    assert got["L"]["status"] == "lit_likely" and got["L"]["ind"] == ["partial_lamps"]


def test_sidewalk_inherits_darkness_reported_on_its_street():
    got = run([street("A", [(0, 0), (100, 0)], name="Strada A", lit="yes"), street("SA", [(0, -8), (100, -8)], kind="sidewalk")],
              [], [complaint("Z", "2026-11-10", status="In lucru", sub=AREA_OUT, x=50, y=3)])
    assert got["A"]["status"] == "dark_reported"
    assert got["SA"]["status"] == "dark_reported" and got["SA"].get("inh_dark") is True


def test_same_name_marks_untagged_parts_of_a_tagged_street():
    got = run([street("A1", [(0, 0), (100, 0)], name="Strada A", lit="yes"), street("A2", [(100, 0), (200, 0)], name="strada a"),
               street("B", [(0, 300), (100, 300)], name="Strada B")], [], [])
    assert got["A2"]["status"] == "lit_likely" and got["A2"]["ind"] == ["same_name"]
    assert got["B"]["status"] == "unknown"
