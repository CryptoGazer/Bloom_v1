"""Street network in memory: snap a point to it, route A -> B (fastest and better lit), list segments in a bbox.

Python port of demo/route/route.js; reads the file written by backend/build_city.py
(data/out/city/segments.geojson.gz). Pure functions, no web framework here.
"""
import bisect
import gzip
import heapq
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

KX, KY = 77811.0, 111147.0  # metres per degree of lon / lat at 45.748 N, same as build_city.py
STATUSES = ("lit_confirmed", "lit_likely", "unknown", "dark_reported")
UNKNOWN, DARK = STATUSES.index("unknown"), STATUSES.index("dark_reported")

# Spec section 12. All numbers are settings; check them with real walkers.
SETTINGS = {
    "walk_mps": 1.35,                       # ~4.9 km/h
    "factor_better_lit": {"lit_confirmed": 1.0, "lit_likely": 1.2, "unknown": 1.6, "dark_reported": 3.0},
    "hide_if_extra_min": 5.0,               # the lit route is not worth showing if it is longer by more than this
    "hide_if_extra_share": 0.30,            # ...or by more than this share
    "warn_dark_run_m": 100.0,               # warn: continuous "reported dark" stretch longer than this
    "warn_dark_unknown_share": 0.20,        # warn: "dark" + "no data" share above this
    "snap_max_m": 300.0,                    # a point farther than this from the network is outside coverage
                                            # (300 m still reaches the middle of a mall, a yard or a park lawn)
}
NO_WALK_HIGHWAYS = {"motorway", "motorway_link"}
FOOT_ALLOWED = {"yes", "designated", "permissive"}


@dataclass
class Snap:
    seg: int      # segment index
    t: float      # metres from the start of the segment
    d: float      # metres from the requested point to the network
    lat: float
    lon: float


def _values(props, key):
    return set(str(props.get(key) or "").split(";")) - {""}


def walk_allowed(props):
    if _values(props, "hw") & NO_WALK_HIGHWAYS:
        return False
    foot = _values(props, "foot")
    if foot and foot <= {"no"}:
        return False
    access = _values(props, "access")
    if access and access <= {"no"} and not (foot & FOOT_ALLOWED):
        return False
    return True


class Network:
    def __init__(self, features, meta=None):
        self.meta = meta or {}
        feats = [f for f in features if f.get("geometry") and len(f["geometry"]["coordinates"]) >= 2]
        self.props = [f["properties"] for f in feats]
        self.ll = [f["geometry"]["coordinates"] for f in feats]  # [[lon, lat], ...]
        self.lines = np.array([LineString([(x * KX, y * KY) for x, y in c]) for c in self.ll], dtype=object)
        self.len = [float(x) for x in shapely.length(self.lines)]
        self.st = [STATUSES.index(p["status"]) if p.get("status") in STATUSES else UNKNOWN for p in self.props]
        self.by_id = {p.get("id"): i for i, p in enumerate(self.props)}

        # nodes: explicit u/v from build_city.py, else (older draft files) identical end coordinates
        node_of, self.node_xy = {}, []
        def node(key, lonlat):
            idx = node_of.get(key)
            if idx is None:
                idx = node_of[key] = len(self.node_xy)
                self.node_xy.append((lonlat[0] * KX, lonlat[1] * KY))
            return idx
        self.a, self.b = [], []
        for p, c in zip(self.props, self.ll):
            if "u" in p and "v" in p:
                self.a.append(node(p["u"], c[0]))
                self.b.append(node(p["v"], c[-1]))
            else:
                self.a.append(node(tuple(c[0]), c[0]))
                self.b.append(node(tuple(c[-1]), c[-1]))

        # walking graph; routing is limited to its largest connected part, so a point never lands on an island
        usable = [self.len[i] > 0 and self.a[i] != self.b[i] and walk_allowed(self.props[i]) for i in range(len(self.props))]
        adj = [[] for _ in self.node_xy]
        for i, ok in enumerate(usable):
            if ok:
                adj[self.a[i]].append((self.b[i], i))
                adj[self.b[i]].append((self.a[i], i))
        comp, sizes = [-1] * len(adj), []
        for start in range(len(adj)):
            if comp[start] != -1 or not adj[start]:
                continue
            cid, stack, size = len(sizes), [start], 0
            comp[start] = cid
            while stack:
                u = stack.pop()
                size += 1
                for v, _ in adj[u]:
                    if comp[v] == -1:
                        comp[v] = cid
                        stack.append(v)
            sizes.append(size)
        main = max(range(len(sizes)), key=sizes.__getitem__) if sizes else -1
        self.routable = [ok and comp[self.a[i]] == main for i, ok in enumerate(usable)]
        self.adj = [[(v, s) for v, s in nbrs if self.routable[s]] for nbrs in adj]

        self._snap_idx = np.array([i for i, ok in enumerate(self.routable) if ok], dtype=int)
        self._snap_tree = STRtree(self.lines[self._snap_idx]) if len(self._snap_idx) else None
        self._all_tree = STRtree(self.lines)
        self._cum = {}

    @classmethod
    def load(cls, path):
        path = Path(path)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            fc = json.load(f)
        return cls(fc["features"], fc.get("meta"))

    # ---------- geometry helpers ----------
    def _cumulative(self, i):
        cum = self._cum.get(i)
        if cum is None:
            cum, total = [0.0], 0.0
            pts = self.ll[i]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                total += math.hypot((x2 - x1) * KX, (y2 - y1) * KY)
                cum.append(total)
            self._cum[i] = cum
        return cum

    def _point_at(self, i, t):
        cum, pts = self._cumulative(i), self.ll[i]
        j = min(max(bisect.bisect_left(cum, t), 1), len(cum) - 1)
        c0, c1 = cum[j - 1], cum[j]
        u = min(1.0, max(0.0, (t - c0) / (c1 - c0))) if c1 > c0 else 0.0
        return [round(pts[j - 1][0] + u * (pts[j][0] - pts[j - 1][0]), 6), round(pts[j - 1][1] + u * (pts[j][1] - pts[j - 1][1]), 6)]

    def _piece(self, i, t0, t1):
        """Part of segment i from distance t0 to t1 along it (t1 < t0 walks it backwards)."""
        lo, hi = min(t0, t1), max(t0, t1)
        cum, pts = self._cumulative(i), self.ll[i]
        coords = [self._point_at(i, lo)] + [pts[j] for j in range(1, len(cum) - 1) if lo < cum[j] < hi] + [self._point_at(i, hi)]
        return {"seg": i, "coords": coords if t0 <= t1 else coords[::-1], "len": hi - lo, "st": self.st[i]}

    # ---------- snapping and bbox ----------
    def nearest_m(self, lat, lon):
        """Distance in metres from a point to the routable network (None if the network is empty)."""
        if self._snap_tree is None:
            return None
        p = Point(lon * KX, lat * KY)
        return float(self.lines[self._snap_idx[self._snap_tree.nearest(p)]].distance(p))

    def snap(self, lat, lon, max_m=None):
        if self._snap_tree is None:
            return None
        max_m = SETTINGS["snap_max_m"] if max_m is None else max_m
        p = Point(lon * KX, lat * KY)
        hits = self._snap_tree.query_nearest(p, max_distance=max_m, all_matches=False)
        if len(hits) == 0:
            return None
        i = int(self._snap_idx[hits[0]])
        line = self.lines[i]
        t = min(max(float(line.project(p)), 0.0), self.len[i])
        q = line.interpolate(t)
        return Snap(seg=i, t=t, d=float(p.distance(q)), lat=round(q.y / KY, 6), lon=round(q.x / KX, 6))

    def segments_in_bbox(self, west, south, east, north):
        return sorted(int(i) for i in self._all_tree.query(box(west * KX, south * KY, east * KX, north * KY)))

    def feature(self, i, full=False):
        p = self.props[i]
        props = dict(p) if full else {k: p.get(k) for k in ("id", "kind", "name", "len", "status", "conf")}
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": self.ll[i]}, "properties": props}

    # ---------- routing ----------
    def _search(self, A, B, factor):
        """A* from snapped point A to snapped point B; cost = length x factor[status]. Returns pieces or None."""
        a, b, ln, st, adj, xy = self.a, self.b, self.len, self.st, self.adj, self.node_xy
        fa, fb = factor[st[A.seg]], factor[st[B.seg]]
        remaining = {a[B.seg]: B.t * fb}
        remaining[b[B.seg]] = min(remaining.get(b[B.seg], math.inf), (ln[B.seg] - B.t) * fb)
        best, best_end = (abs(A.t - B.t) * fb, "direct") if A.seg == B.seg else (math.inf, None)
        bx, by, fmin = B.lon * KX, B.lat * KY, min(factor)
        dist, prev, heap = {}, {}, []

        def push(node, cost, came_from):
            if cost < dist.get(node, math.inf):
                dist[node], prev[node] = cost, came_from
                x, y = xy[node]
                heapq.heappush(heap, (cost + fmin * math.hypot(x - bx, y - by), cost, node))

        push(a[A.seg], A.t * fa, None)
        push(b[A.seg], (ln[A.seg] - A.t) * fa, None)
        while heap:
            estimate, d, u = heapq.heappop(heap)
            if estimate >= best:
                break
            if d > dist[u]:
                continue
            if u in remaining and d + remaining[u] < best:
                best, best_end = d + remaining[u], u
            for v, s in adj[u]:
                push(v, d + ln[s] * factor[st[s]], (u, s))
        if best_end is None:
            return None
        if best_end == "direct":
            return [self._piece(A.seg, A.t, B.t)]
        chain, u = [], best_end
        while prev[u] is not None:
            chain.append(prev[u])
            u = prev[u][0]
        pieces = [self._piece(A.seg, A.t, 0.0 if u == a[A.seg] else ln[A.seg])]
        for node, s in reversed(chain):
            forward = node == a[s]
            pieces.append(self._piece(s, 0.0 if forward else ln[s], ln[s] if forward else 0.0))
        pieces.append(self._piece(B.seg, 0.0 if best_end == a[B.seg] else ln[B.seg], B.t))
        return pieces

    def route(self, A, B, factors=None):
        """One route as a summary dict, or None. factors: {status: multiplier}; None means the fastest route."""
        factor = [1.0] * len(STATUSES) if factors is None else [float(factors[s]) for s in STATUSES]
        pieces = self._search(A, B, factor)
        if pieces is None:
            return None
        kept = [p for p in pieces if p["len"] > 0.5] or pieces[:1]
        return self._summarize(kept)

    def _summarize(self, pieces):
        by = [0.0] * len(STATUSES)
        total = run = max_dark_run = 0.0
        for p in pieces:
            by[p["st"]] += p["len"]
            total += p["len"]
            run = run + p["len"] if p["st"] == DARK else 0.0
            max_dark_run = max(max_dark_run, run)
        share = (by[DARK] + by[UNKNOWN]) / total if total else 0.0
        streets, merged = [], []
        for p in pieces:
            name = self.props[p["seg"]].get("name")
            if name and (not streets or streets[-1] != name):
                streets.append(name)
            last = merged[-1] if merged else None
            if last and last["properties"]["status"] == STATUSES[p["st"]] and last["properties"]["name"] == name:
                last["geometry"]["coordinates"].extend(p["coords"][1:])
                last["properties"]["len"] = round(last["properties"]["len"] + p["len"], 1)
                last["properties"]["ids"].append(self.props[p["seg"]].get("id"))
            else:
                merged.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": list(p["coords"])},
                               "properties": {"status": STATUSES[p["st"]], "name": name, "len": round(p["len"], 1), "ids": [self.props[p["seg"]].get("id")]}})
        return {
            "length_m": round(total, 1), "minutes": round(total / SETTINGS["walk_mps"] / 60, 1),
            "by_status_m": {s: round(by[i], 1) for i, s in enumerate(STATUSES)},
            "max_dark_run_m": round(max_dark_run, 1), "dark_unknown_share": round(share, 3),
            "warn": max_dark_run > SETTINGS["warn_dark_run_m"] or share > SETTINGS["warn_dark_unknown_share"],
            "streets": streets, "geometry": {"type": "FeatureCollection", "features": merged},
            "_key": tuple(p["seg"] for p in pieces),
        }

    def plan(self, A, B):
        """Fastest and better-lit routes plus the verdict whether the lit one is worth showing (spec section 12)."""
        fastest, lit = self.route(A, B), self.route(A, B, SETTINGS["factor_better_lit"])
        if fastest is None or lit is None:
            return None
        if fastest["_key"] == lit["_key"]:
            verdict = {"kind": "same"}
        else:
            extra_min = (lit["length_m"] - fastest["length_m"]) / SETTINGS["walk_mps"] / 60
            extra_share = (lit["length_m"] - fastest["length_m"]) / fastest["length_m"] if fastest["length_m"] else 0.0
            too_long = extra_min > SETTINGS["hide_if_extra_min"] or extra_share > SETTINGS["hide_if_extra_share"]
            verdict = {"kind": "too_long" if too_long else "show", "extra_min": round(extra_min, 1), "extra_share": round(extra_share, 3)}
        for r in (fastest, lit):
            del r["_key"]
        return {"routes": {"fastest": fastest, "better_lit": lit}, "verdict": verdict}
