"""Lighting status of one segment from its facts (spec section 7). Pure functions: no files, no geometry.

Used by backend/build_city.py. The agreed cases are in backend/tests/test_rules.py: change a rule only together
with that table.

Facts about a segment:
  lit            OSM lit tag of the segment's own ways: "yes", "no", "mixed" or None
  lamp_coverage  share of the length within the lamp radius of a Mapillary street light, 0..1
  events         complaint events attached to it, as (kind, age in days); age is None for closed events
  indirect       indirect signs: "partial_lamps", "same_name", "near_lit_street"
  inherited_dark the nearest street is reported dark by complaints
"""
STATUSES = ("lit_confirmed", "lit_likely", "dark_reported", "unknown")
DIRECT_FAMILIES = ("osm", "mapillary")  # a tag on the way itself, street lights seen on imagery


def families(lit, lamp_coverage, event_kinds, coverage_min):
    """Independent sources that say a street light is there, in a fixed order."""
    fam = []
    if lit == "yes":
        fam.append("osm")
    if lamp_coverage >= coverage_min:
        fam.append("mapillary")
    if any(kind != "declined" for kind in event_kinds):
        fam.append("sesizari")
    return fam


def _fresh(age, fresh_days):
    return age is not None and age <= fresh_days


def fresh_lamps_out(events, fresh_days):
    return sum(1 for kind, age in events if kind == "open_lamp_out" and _fresh(age, fresh_days))


def dark_by_complaints(events, fresh_days, lamps_out_for_dark):
    """A fresh "no lighting in the area" complaint, or several lamps reported out recently."""
    fresh_area = any(kind == "open_area_outage" and _fresh(age, fresh_days) for kind, age in events)
    return fresh_area or fresh_lamps_out(events, fresh_days) >= lamps_out_for_dark


def status(lit, fam, events, indirect, inherited_dark, fresh_days, lamps_out_for_dark):
    """Checked top to bottom: reported dark, lit (one direct source is enough), probably lit, no data."""
    if lit == "no" or inherited_dark or dark_by_complaints(events, fresh_days, lamps_out_for_dark):
        return "dark_reported"
    if set(DIRECT_FAMILIES) & set(fam) and fresh_lamps_out(events, fresh_days) == 0:
        return "lit_confirmed"
    if fam or indirect:
        return "lit_likely"
    return "unknown"


def classify(lit, lamp_coverage, events, indirect, inherited_dark, *, coverage_min, fresh_days, lamps_out_for_dark):
    """Status and families of one segment from all its facts at once."""
    fam = families(lit, lamp_coverage, [kind for kind, _ in events], coverage_min)
    return status(lit, fam, events, indirect, inherited_dark, fresh_days, lamps_out_for_dark), fam
