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
    "bike_mps": 4.2,                        # ~15 km/h in town; pushing the bike ("dismount") counts at walking speed
    "factor_better_lit": {"lit_confirmed": 1.0, "lit_likely": 1.2, "unknown": 1.6, "dark_reported": 3.0},
    "hide_if_extra_min": 5.0,               # the lit route is not worth showing if it is longer by more than this
    "hide_if_extra_share": 0.30,            # ...or by more than this share
    "lit_free_extra_min": 0.5,              # a better-lit route at most this much longer replaces the fastest one
    "same_if_gain_below": 0.05,             # the lit route counts as "the same" if it adds less than this share of
                                            # confirmed-lit length and removes less than this share of dark + no data,
                                            # unless it removes a long dark stretch (warn_dark_run_m)
    "warn_dark_run_m": 100.0,               # warn: continuous "reported dark" stretch longer than this
    "warn_dark_unknown_share": 0.20,        # warn: "dark" + "no data" share above this
    "snap_max_m": 300.0,                    # a point farther than this from the network is outside coverage
                                            # (300 m still reaches the middle of a mall, a yard or a park lawn)
}
MODES = ("walk", "bike")
NO_WALK_HIGHWAYS = {"motorway", "motorway_link"}
FOOT_ALLOWED = {"yes", "designated", "permissive"}
NO_BIKE_HIGHWAYS = {"motorway", "motorway_link", "steps", "corridor", "elevator", "platform", "bus_stop"}
BIKE_ALLOWED = {"yes", "designated", "permissive"}
FOOT_ONLY_HIGHWAYS = {"footway", "pedestrian"}  # a bike needs an explicit bicycle=yes/designated here


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


def bike_access(props):
    """'ride', 'push' (bicycle=dismount: walk the bike) or None (not for bikes), from OSM tags."""
    hw, bike = _values(props, "hw"), _values(props, "bicycle")
    if hw & NO_BIKE_HIGHWAYS:
        return None
    if bike & {"no", "use_sidepath"} and not (bike & BIKE_ALLOWED):
        return None
    access = _values(props, "access")
    if access and access <= {"no", "private"} and not (bike & BIKE_ALLOWED):
        return None
    if "dismount" in bike:
        return "push"
    if hw and hw <= FOOT_ONLY_HIGHWAYS and not (bike & BIKE_ALLOWED):
        return None
    return "ride"


def largest_scc(adj):
    """Nodes of the largest strongly connected part of a directed graph, adj[u] = [(v, segment), ...].
    Iterative Kosaraju, no dependencies (networkx is not installed on the server)."""
    n = len(adj)
    radj = [[] for _ in range(n)]
    for u, nbrs in enumerate(adj):
        for v, _ in nbrs:
            radj[v].append(u)
    order, seen = [], [False] * n
    for start in range(n):
        if seen[start] or not adj[start]:
            continue
        seen[start] = True
        stack = [(start, iter(adj[start]))]
        while stack:
            u, it = stack[-1]
            for v, _ in it:
                if not seen[v]:
                    seen[v] = True
                    stack.append((v, iter(adj[v])))
                    break
            else:
                stack.pop()
                order.append(u)
    comp, best = [-1] * n, set()
    for start in reversed(order):
        if comp[start] != -1:
            continue
        members, stack = [], [start]
        comp[start] = start
        while stack:
            u = stack.pop()
            members.append(u)
            for v in radj[u]:
                if comp[v] == -1:
                    comp[v] = start
                    stack.append(v)
        if len(members) > len(best):
            best = set(members)
    return best if len(best) > 1 else set()


def bike_both_ways(props):
    """A one-way segment (stored in its driving direction) is two-way for bikes only with a contraflow sign."""
    if _values(props, "oneway") != {"True"}:
        return True
    if "no" in _values(props, "oneway:bicycle"):
        return True
    lanes = set().union(*(_values(props, k) for k in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")))
    return any(v.startswith("opposite") for v in lanes)


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

        self.graphs = {mode: self._build_graph(mode) for mode in MODES}
        self.routable, self.adj = self.graphs["walk"]["routable"], self.graphs["walk"]["adj"]  # walking, as before
        self._all_tree = STRtree(self.lines)
        self._cum = {}

    def _build_graph(self, mode):
        """Graph of one travel mode, limited to its largest connected part so a point never lands on an island.
        walk: every walkable segment, both ways. bike: segments open to bikes; one-way ones only in their
        stored direction unless bikes may ride against it; "dismount" segments cost walking time."""
        n = len(self.props)
        if mode == "walk":
            usable = [self.len[i] > 0 and self.a[i] != self.b[i] and walk_allowed(self.props[i]) for i in range(n)]
            both, slow = [True] * n, [1.0] * n
        else:
            access = [bike_access(p) for p in self.props]
            usable = [self.len[i] > 0 and self.a[i] != self.b[i] and access[i] is not None for i in range(n)]
            both = [bike_both_ways(p) for p in self.props]
            push = SETTINGS["bike_mps"] / SETTINGS["walk_mps"]
            slow = [push if access[i] == "push" else 1.0 for i in range(n)]
        und = [[] for _ in self.node_xy]
        for i, ok in enumerate(usable):
            if ok:
                und[self.a[i]].append(self.b[i])
                und[self.b[i]].append(self.a[i])
        comp, sizes = [-1] * len(und), []
        for start in range(len(und)):
            if comp[start] != -1 or not und[start]:
                continue
            cid, stack, size = len(sizes), [start], 0
            comp[start] = cid
            while stack:
                u = stack.pop()
                size += 1
                for v in und[u]:
                    if comp[v] == -1:
                        comp[v] = cid
                        stack.append(v)
            sizes.append(size)
        main = max(range(len(sizes)), key=sizes.__getitem__) if sizes else -1
        routable = [ok and comp[self.a[i]] == main for i, ok in enumerate(usable)]
        adj = [[] for _ in self.node_xy]
        for i, ok in enumerate(routable):
            if ok:
                adj[self.a[i]].append((self.b[i], i))
                if both[i]:
                    adj[self.b[i]].append((self.a[i], i))
        if mode == "bike":
            # one-way streets make the bike graph directed: keep only the part where every crossing can be
            # reached from every other one, so a snapped point never sits in a one-way dead end or trap
            main = largest_scc(adj)
            routable = [ok and self.a[i] in main and self.b[i] in main for i, ok in enumerate(routable)]
            adj = [[(v, s) for v, s in nbrs if routable[s]] for nbrs in adj]
        snap_idx = np.array([i for i, ok in enumerate(routable) if ok], dtype=int)
        return {"routable": routable, "adj": adj, "slow": slow, "both": both, "mps": SETTINGS[mode + "_mps"], "snap_idx": snap_idx,
                "snap_tree": STRtree(self.lines[snap_idx]) if len(snap_idx) else None}

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
    def nearest_m(self, lat, lon, mode="walk"):
        """Distance in metres from a point to the routable network of a mode (None if that network is empty)."""
        g = self.graphs[mode]
        if g["snap_tree"] is None:
            return None
        p = Point(lon * KX, lat * KY)
        return float(self.lines[g["snap_idx"][g["snap_tree"].nearest(p)]].distance(p))

    def snap(self, lat, lon, max_m=None, mode="walk"):
        g = self.graphs[mode]
        if g["snap_tree"] is None:
            return None
        max_m = SETTINGS["snap_max_m"] if max_m is None else max_m
        p = Point(lon * KX, lat * KY)
        hits = g["snap_tree"].query_nearest(p, max_distance=max_m, all_matches=False)
        if len(hits) == 0:
            return None
        i = int(g["snap_idx"][hits[0]])
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
    def _search(self, A, B, factor, mode="walk"):
        """A* from snapped point A to snapped point B; cost = length x factor[status] x slowness. Returns pieces or None."""
        g = self.graphs[mode]
        a, b, ln, st, adj, xy, slow, both = self.a, self.b, self.len, self.st, g["adj"], self.node_xy, g["slow"], g["both"]
        fa, fb = factor[st[A.seg]] * slow[A.seg], factor[st[B.seg]] * slow[B.seg]
        # a one-way segment (bike mode) may only be ridden from a to b, also on the first and the last piece
        remaining = {a[B.seg]: B.t * fb}
        if both[B.seg]:
            remaining[b[B.seg]] = min(remaining.get(b[B.seg], math.inf), (ln[B.seg] - B.t) * fb)
        direct = A.seg == B.seg and (B.t >= A.t or both[A.seg])
        best, best_end = (abs(A.t - B.t) * fb, "direct") if direct else (math.inf, None)
        bx, by, fmin = B.lon * KX, B.lat * KY, min(factor)
        dist, prev, heap = {}, {}, []

        def push(node, cost, came_from):
            if cost < dist.get(node, math.inf):
                dist[node], prev[node] = cost, came_from
                x, y = xy[node]
                heapq.heappush(heap, (cost + fmin * math.hypot(x - bx, y - by), cost, node))

        if both[A.seg]:
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
                push(v, d + ln[s] * factor[st[s]] * slow[s], (u, s))
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

    def tree(self, S, factors=None, max_cost=math.inf, mode="walk"):
        """Dijkstra from snapped point S: {node: (cost, metres)} for nodes within max_cost.
        cost = length x factor[status] x slowness, as in route(); used to find stops within walking distance."""
        g = self.graphs[mode]
        factor = [1.0] * len(STATUSES) if factors is None else [float(factors[s]) for s in STATUSES]
        a, b, ln, st, slow, both = self.a, self.b, self.len, self.st, g["slow"], g["both"]
        f = factor[st[S.seg]] * slow[S.seg]
        best, heap = {}, []

        def push(node, cost, metres):
            if cost <= max_cost and cost < best.get(node, (math.inf, 0))[0]:
                best[node] = (cost, metres)
                heapq.heappush(heap, (cost, metres, node))

        if both[S.seg]:
            push(a[S.seg], S.t * f, S.t)
        push(b[S.seg], (ln[S.seg] - S.t) * f, ln[S.seg] - S.t)
        while heap:
            cost, metres, u = heapq.heappop(heap)
            if cost > best[u][0]:
                continue
            for v, s in g["adj"][u]:
                push(v, cost + ln[s] * factor[st[s]] * slow[s], metres + ln[s])
        return best

    def reach(self, tree, T, factors=None, S=None, mode="walk"):
        """(cost, metres) from the source of tree() to snapped point T, or None if T is out of reach.
        Pass the source S to allow the direct way when both points lie on one segment."""
        g = self.graphs[mode]
        factor = [1.0] * len(STATUSES) if factors is None else [float(factors[s]) for s in STATUSES]
        a, b, ln, both = self.a, self.b, self.len, g["both"]
        f = factor[self.st[T.seg]] * g["slow"][T.seg]
        options = []
        if a[T.seg] in tree:
            cost, metres = tree[a[T.seg]]
            options.append((cost + T.t * f, metres + T.t))
        if both[T.seg] and b[T.seg] in tree:
            cost, metres = tree[b[T.seg]]
            options.append((cost + (ln[T.seg] - T.t) * f, metres + ln[T.seg] - T.t))
        if S is not None and S.seg == T.seg and (T.t >= S.t or both[S.seg]):
            options.append((abs(T.t - S.t) * f, abs(T.t - S.t)))
        return min(options) if options else None

    def route(self, A, B, factors=None, mode="walk"):
        """One route as a summary dict, or None. factors: {status: multiplier}; None means the fastest route."""
        factor = [1.0] * len(STATUSES) if factors is None else [float(factors[s]) for s in STATUSES]
        pieces = self._search(A, B, factor, mode)
        if pieces is None:
            return None
        kept = [p for p in pieces if p["len"] > 0.5] or pieces[:1]
        return self._summarize(kept, mode)

    def _summarize(self, pieces, mode="walk"):
        g = self.graphs[mode]
        by = [0.0] * len(STATUSES)
        total = run = max_dark_run = seconds = 0.0
        for p in pieces:
            by[p["st"]] += p["len"]
            total += p["len"]
            seconds += p["len"] * g["slow"][p["seg"]] / g["mps"]
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
            "length_m": round(total, 1), "minutes": round(seconds / 60, 1), "_sec": seconds,
            "by_status_m": {s: round(by[i], 1) for i, s in enumerate(STATUSES)},
            "max_dark_run_m": round(max_dark_run, 1), "dark_unknown_share": round(share, 3),
            "warn": max_dark_run > SETTINGS["warn_dark_run_m"] or share > SETTINGS["warn_dark_unknown_share"],
            "streets": streets, "geometry": {"type": "FeatureCollection", "features": merged},
            "_key": tuple(p["seg"] for p in pieces),
        }

    @staticmethod
    def lit_gain(fastest, lit):
        """How much lighting the lit route adds: the larger of the gain in confirmed-lit share
        and the drop in dark + no-data share, both as shares of each route's length."""
        def share(r, statuses):
            return sum(r["by_status_m"][s] for s in statuses) / r["length_m"] if r["length_m"] else 0.0
        confirmed = share(lit, ("lit_confirmed",)) - share(fastest, ("lit_confirmed",))
        bad = share(fastest, ("dark_reported", "unknown")) - share(lit, ("dark_reported", "unknown"))
        return max(confirmed, bad)

    def plan(self, A, B, mode="walk"):
        """Fastest and better-lit routes plus the verdict whether the lit one is worth showing (spec section 12).
        A and B must be snapped with the same mode."""
        fastest, lit = self.route(A, B, mode=mode), self.route(A, B, SETTINGS["factor_better_lit"], mode=mode)
        if fastest is None or lit is None:
            return None
        gain = self.lit_gain(fastest, lit)
        removes_dark_run = fastest["max_dark_run_m"] > SETTINGS["warn_dark_run_m"] >= lit["max_dark_run_m"]
        extra_min = (lit["_sec"] - fastest["_sec"]) / 60
        extra_share = (lit["_sec"] - fastest["_sec"]) / fastest["_sec"] if fastest["_sec"] else 0.0
        # one card when there is nothing to choose; "pick" says which route that card shows
        if fastest["_key"] == lit["_key"]:
            verdict = {"kind": "same"}
        elif gain < SETTINGS["same_if_gain_below"] and not removes_dark_run:
            # different streets, but practically the same lighting: the shorter route
            verdict = {"kind": "same", "near": True, "pick": "fastest", "lit_gain": round(gain, 3)}
        elif extra_min <= SETTINGS["lit_free_extra_min"]:
            # better lit and practically as fast: the fastest route has nothing to offer
            verdict = {"kind": "same", "near": True, "pick": "better_lit", "lit_gain": round(gain, 3), "extra_min": round(extra_min, 1)}
        else:
            too_long = extra_min > SETTINGS["hide_if_extra_min"] or extra_share > SETTINGS["hide_if_extra_share"]
            verdict = {"kind": "too_long" if too_long else "show", "extra_min": round(extra_min, 1), "extra_share": round(extra_share, 3)}
        for r in (fastest, lit):
            del r["_key"], r["_sec"]
        return {"routes": {"fastest": fastest, "better_lit": lit}, "verdict": verdict}
