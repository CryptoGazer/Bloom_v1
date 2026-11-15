"""BEZNA written only with streets, like a GPS drawing: every stroke of every letter is a walk along the real network.

Each straight piece of a letter is one walk between the street corners nearest to its ends; on the way a street costs
its length times a penalty that grows with its distance from the letter's line, so the walk takes the streets that
run along the stroke. Each letter looks, near its place in the word, for the shift, size and slight turn where the
streets follow it most closely (street grids are rarely north-up). Writes web/pitch/bezna-streets.json (GeoJSON, one
MultiLineString per letter) for web/pitch/title-streets.html.

Run from Bloom_v1/: ../.venv/Scripts/python -m scripts.pitch.street_letters
"""
import gzip
import heapq
import json
import math
from collections import defaultdict
from pathlib import Path

from backend.routing import KX, KY

ROOT = Path(__file__).resolve().parents[2]
SEGMENTS = ROOT / "data/out/city-expanded/segments.geojson.gz"
OUT = ROOT / "web/pitch/bezna-streets.json"
KINDS = {"street", "service"}             # sidewalks, paths and crossings double the streets and make the lines wiggle

# Letters on a grid 2.2 wide and 4 high, strokes as polylines (x right, y up); blocky, as streets allow.
GLYPHS = {
    "B": [[(0, 0), (0, 4), (1.8, 4), (1.8, 2), (0, 2)], [(1.8, 2), (2.2, 2), (2.2, 0), (0, 0)]],
    "E": [[(2.2, 4), (0, 4), (0, 0), (2.2, 0)], [(0, 2), (1.7, 2)]],
    "Z": [[(0, 4), (2.2, 4), (0, 0), (2.2, 0)]],
    "N": [[(0, 0), (0, 4), (2.2, 0), (2.2, 4)]],
    "A": [[(0, 0), (0, 4), (2.2, 4), (2.2, 0)], [(0, 1.8), (2.2, 1.8)]],
}
WORD, ADVANCE = "BEZNA", 3.5


def dist_to(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    u = 0.0 if not L2 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(a[0] + u * dx - p[0], a[1] + u * dy - p[1])


class Streets:
    """The street graph in metres: corners, and edges with their points."""

    def __init__(self):
        with gzip.open(SEGMENTS, "rt", encoding="utf-8") as f:
            feats = [x for x in json.load(f)["features"] if x["properties"].get("kind") in KINDS]
        self.adj, self.xy, self.edges = defaultdict(list), {}, []
        for ft in feats:
            pts = [(c[0] * KX, c[1] * KY) for c in ft["geometry"]["coordinates"]]
            u, v = ft["properties"]["u"], ft["properties"]["v"]
            length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
            e = len(self.edges)
            self.edges.append((pts, length, pts[len(pts) // 2]))
            self.xy[u], self.xy[v] = pts[0], pts[-1]
            self.adj[u].append((v, e))
            self.adj[v].append((u, e))
        self.cells = defaultdict(list)            # a coarse grid of the corners, for "the nearest corner"
        for n, (x, y) in self.xy.items():
            self.cells[(int(x // 100), int(y // 100))].append(n)

    def nearest(self, p, limit):
        best = (limit, None)
        cx, cy = int(p[0] // 100), int(p[1] // 100)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for n in self.cells.get((cx + i, cy + j), ()):
                    d = math.hypot(self.xy[n][0] - p[0], self.xy[n][1] - p[1])
                    if d < best[0]:
                        best = (d, n)
        return best

    def along(self, s, t, a, b, d0):
        """The walk from corner s to corner t that keeps closest to the line a-b: its points and its penalised length."""
        cost, prev, heap = {s: 0.0}, {s: None}, [(0.0, s)]
        while heap:
            c, n = heapq.heappop(heap)
            if n == t:
                break
            if c > cost[n]:
                continue
            for m, e in self.adj[n]:
                _, length, mid = self.edges[e]
                far = max(dist_to(self.xy[m], a, b), dist_to(mid, a, b))
                if far > 5 * d0:
                    continue                                    # far from the stroke: never part of it
                nc = c + length * (1 + (far / d0) ** 2)
                if nc < cost.get(m, math.inf):
                    cost[m], prev[m] = nc, (n, e)
                    heapq.heappush(heap, (nc, m))
        if t not in prev:
            return None, math.inf
        chain, n = [], t
        while prev[n] is not None:
            n0, e = prev[n]
            pts = self.edges[e][0]
            chain.append(pts if self.xy[n0] == pts[0] else pts[::-1])
            n = n0
        line = []
        for pts in reversed(chain):
            line += pts if not line else pts[1:]
        return line, cost[t]


def letter(st, ch, cx, cy, u, turn):
    """The letter centred at (cx, cy), unit u metres, turned by `turn` radians: its walks and its misfit (lower is better)."""
    d0, co, si = 0.14 * u, math.cos(turn), math.sin(turn)
    place = lambda x, y: (cx + ((x - 1.1) * co - (y - 2) * si) * u, cy + ((x - 1.1) * si + (y - 2) * co) * u)
    lines, bad = [], 0.0
    for stroke in GLYPHS[ch]:
        pts = [place(x, y) for x, y in stroke]
        corners = [st.nearest(p, 3 * d0) for p in pts]
        if any(n is None for _, n in corners):
            return None, math.inf
        bad += sum((d / d0) ** 2 for d, _ in corners) * 0.5
        line = []
        for (a, b), ((_, s), (_, t)) in zip(zip(pts, pts[1:]), zip(corners, corners[1:])):
            if s == t:
                return None, math.inf                           # two ends of a stroke at one corner: the stroke is lost
            part, cost = st.along(s, t, a, b, d0)
            if part is None:
                return None, math.inf
            line += part if not line else part[1:]
            bad += (cost - math.hypot(b[0] - a[0], b[1] - a[1])) / u
        lines.append(line)
    return lines, bad


def main():
    st = Streets()
    print(f"{len(st.xy)} corners, {len(st.edges)} streets")
    best = None
    for unit in (150.0, 180.0):
        for lon0, lat0 in ((21.2335, 45.7535), (21.2300, 45.7520), (21.2370, 45.7560)):
            width = 4 * ADVANCE * unit + 2.2 * unit
            x0, yc = lon0 * KX - width / 2 + 1.1 * unit, lat0 * KY
            letters, total, notes = [], 0.0, []
            for i, ch in enumerate(WORD):
                pick = None
                for scale in (0.85, 1.0, 1.15):
                    for deg in (-24, -16, -8, 0, 8, 16, 24):
                        for di in (-0.5, -0.25, 0, 0.25, 0.5):
                            for dj in range(-8, 9):
                                lines, bad = letter(st, ch, x0 + (i * ADVANCE + di) * unit, yc + dj * unit / 4, unit * scale, math.radians(deg))
                                if lines is not None and (pick is None or bad < pick[0]):
                                    pick = (bad, lines, scale, deg, di, dj)
                if pick is None:
                    total = math.inf
                    break
                letters.append(pick[1])
                total += pick[0]
                notes.append(f"{ch} {pick[0]:.1f} (x{pick[2]}, {pick[3]:+d} deg)")
            print(f"unit {unit:.0f} m at {lon0}, {lat0}: misfit {total:.1f}  " + ", ".join(notes), flush=True)
            if total < math.inf and (best is None or total < best[0]):
                best = (total, unit, letters)
    total, unit, letters = best
    to_ll = lambda p: [round(p[0] / KX, 6), round(p[1] / KY, 6)]
    out = {"type": "FeatureCollection", "meta": {"word": WORD, "unit_m": unit, "misfit": round(total, 1), "source": SEGMENTS.name},
           "features": [{"type": "Feature", "properties": {"letter": ch},
                         "geometry": {"type": "MultiLineString", "coordinates": [[to_ll(p) for p in ln] for ln in lines]}}
                        for ch, lines in zip(WORD, letters)]}
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"best: unit {unit:.0f} m, misfit {total:.1f} -> {OUT}")


if __name__ == "__main__":
    main()
