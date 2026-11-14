"""Shared helpers: load the cached Overpass extract, classify ways, clip, measure."""
import json
import unicodedata

import geopandas as gpd
from shapely.geometry import LineString, box

CRS_M = "EPSG:32634"
GENEROUS = (45.728, 21.200, 45.758, 21.258)  # south, west, north, east

EXCL_HW = {"construction", "proposed", "platform", "bus_stop", "rest_area", "services", "elevator",
           "corridor", "abandoned", "razed", "planned", "no", "bridleway", "raceway", "bus_guideway",
           "busway", "motorway", "motorway_link"}
STREETS = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
           "unclassified", "residential", "living_street"}
OK_ACCESS = {"yes", "designated", "permissive"}
CLASS_ORDER = ["streets", "trunk", "pedestrian", "footway_sidewalk", "footway_crossing", "footway_other",
               "cycleway", "path", "steps", "service", "track", "other"]
NONSTREET_WALK = ["pedestrian", "footway_sidewalk", "footway_crossing", "footway_other", "cycleway", "path", "steps"]


def strip_diacritics(s):
    if not isinstance(s, str):
        return None
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def excluded(tags):
    hw = tags.get("highway")
    if hw in EXCL_HW:
        return "highway=" + str(hw)
    if tags.get("area") == "yes":
        return "area=yes"
    if tags.get("access") in ("private", "no"):
        if tags.get("foot") in OK_ACCESS or tags.get("bicycle") in OK_ACCESS:
            return None
        return "access=" + tags.get("access")
    return None


def classify(tags):
    hw = tags.get("highway")
    if hw in STREETS:
        return "streets"
    if hw in ("trunk", "trunk_link"):
        return "trunk"
    if hw == "pedestrian":
        return "pedestrian"
    if hw == "footway":
        f = tags.get("footway")
        if f == "sidewalk":
            return "footway_sidewalk"
        if f == "crossing":
            return "footway_crossing"
        return "footway_other"
    if hw in ("cycleway", "path", "steps", "service", "track"):
        return hw
    return "other"


def lit_status(v):
    if v is None:
        return "missing"
    if v == "yes":
        return "yes"
    if v == "no":
        return "no"
    if v == "disused":
        return "disused"
    return "yeslike:" + v


def load_ways(path):
    """Return (timestamp, GeoDataFrame in EPSG:4326 with all highway ways, not yet filtered)."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    for e in d["elements"]:
        if e.get("type") != "way" or "geometry" not in e:
            continue
        coords = [(p["lon"], p["lat"]) for p in e["geometry"] if p is not None]
        if len(coords) < 2:
            continue
        t = e.get("tags", {})
        rows.append({
            "id": e["id"], "highway": t.get("highway"), "name": t.get("name"), "lit": t.get("lit"),
            "cls": classify(t), "excl": excluded(t), "tags": t, "lit_status": lit_status(t.get("lit")),
            "n_nodes": len(e.get("nodes", [])), "geometry": LineString(coords),
        })
    g = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return d["osm3s"]["timestamp_osm_base"], g


def bbox_poly(b):
    s, w, n, e = b
    return box(w, s, e, n)


def bbox_poly_m(b):
    return gpd.GeoSeries([bbox_poly(b)], crs="EPSG:4326").to_crs(CRS_M).iloc[0]


def clip_to_bbox(g, b):
    """Clip in lon/lat (bbox edges are lon/lat aligned), then project to metres. Adds km column."""
    p = bbox_poly(b)
    sub = g[g.intersects(p)].copy()
    sub["geometry"] = sub.geometry.intersection(p)
    sub = sub[~sub.geometry.is_empty]
    sub = sub.to_crs(CRS_M)
    sub["km"] = sub.geometry.length / 1000.0
    return sub


def area_km2(b):
    return bbox_poly_m(b).area / 1e6
