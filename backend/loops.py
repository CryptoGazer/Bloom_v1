"""Bounded automatic loops. The model chooses a public centre; this code chooses real street points."""
import math

from shapely.geometry import Point, Polygon

from backend.routing import KX, KY

DEFAULT_RADIUS_M = 400
MIN_RADIUS_M, MAX_RADIUS_M = 100, 1200


def around(net, center, radius_m=DEFAULT_RADIUS_M, mode="walk", start=None):
    """Return (snaps, plan, actual target radius), or None if no reasonable circuit fits the mapped network.

    Waypoints surround the centre in angular order and lie on the accessible connected graph of this mode.
    Near the edge try smaller rings; never move the centre, invent a place or use an external geocoder.
    A named/geolocated start may add a connector out and back. Radius/length are approximate.
    """
    lat, lon = center
    cx, cy = lon * KX, lat * KY
    for scale in (1, .8, .6):
        radius = max(MIN_RADIUS_M, radius_m * scale)
        for rotation in (0, math.pi / 8):
            points = []
            for i in range(8):
                angle = rotation + i * math.pi / 4
                target = ((cy + math.sin(angle) * radius) / KY, (cx + math.cos(angle) * radius) / KX)
                p = net.snap(*target, max_m=min(150, max(35, radius * .4)), mode=mode)
                if p is not None and all(math.hypot((p.lon - q.lon) * KX, (p.lat - q.lat) * KY) >= 35 for q in points):
                    points.append(p)
            if len(points) < 4:
                continue
            polygon = Polygon([(p.lon * KX, p.lat * KY) for p in points])
            if not polygon.is_valid or not polygon.covers(Point(cx, cy)) or polygon.area < radius ** 2:
                continue
            if start is not None:
                first = min(range(len(points)), key=lambda i: math.hypot((points[i].lon - start.lon) * KX, (points[i].lat - start.lat) * KY))
                points = points[first:] + points[:first]
                if math.hypot((points[0].lon - start.lon) * KX, (points[0].lat - start.lat) * KY) < 35:
                    points[0] = start
                else:
                    points.insert(0, start)
            plan = net.loop(points, mode=mode)
            if plan is None:
                continue
            # Do not turn a small stroll into a large detour over a bridge or around a graph barrier.
            connector = 0 if start is None else math.hypot(start.lon * KX - cx, start.lat * KY - cy)
            # A start at the centre still needs two radial legs; on a directed bike graph these may detour.
            limit = 4 * math.pi * radius + 3 * connector + (4 * radius if start is not None else 0)
            if any(r["length_m"] > limit for r in plan["routes"].values()):
                continue
            return points, plan, round(radius)
    return None
