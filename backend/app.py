"""HTTP API over the city lighting network.

run:  .venv/bin/uvicorn backend.app:app --port 8001      (or ./scripts/mac/lightmap.sh api)
docs: http://localhost:8001/docs
Data: data/out/city/segments.geojson.gz from backend/build_city.py; override with LIGHTMAP_SEGMENTS=<path>.
"""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.geocode import Places
from backend.routing import SETTINGS, Network

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEGMENTS = ROOT / "data/out/city/segments.geojson.gz"
SEGMENT_LIMIT_DEFAULT, SEGMENT_LIMIT_MAX = 4000, 20000

INDEX_HTML = """<!doctype html><html lang="ru"><meta charset="utf-8"><title>Night route API</title>
<body style="font:15px/1.5 system-ui;max-width:640px;margin:40px auto;padding:0 16px">
<h1>Ночной маршрут: API</h1>
<ul>
<li><a href="/">/</a> — карта города с маршрутами</li>
<li><a href="/docs">/docs</a> — попробовать запросы в браузере</li>
<li><a href="/api/summary">/api/summary</a> — сводка по городу</li>
<li><a href="/api/route?from=45.7470,21.2395&to=45.7415,21.2200">/api/route</a> — пример маршрута</li>
<li><a href="/api/segments?bbox=21.225,45.745,21.235,45.750">/api/segments</a> — отрезки в окне карты</li>
<li><a href="/api/geocode?q=camin%20c12">/api/geocode</a> — поиск адреса, места или остановки</li>
<li><a href="/demo/route/">/demo/route/</a> — демо маршрута в браузере</li>
<li><a href="/data/out/draft-map.html">/data/out/draft-map.html</a> — карта освещённости</li>
</ul></body></html>"""


def parse_point(value, name):
    try:
        lat, lon = (float(x) for x in value.split(","))
    except ValueError:
        raise HTTPException(422, detail={"code": "bad_point", "message": f"'{name}' must be 'lat,lon', e.g. 45.7470,21.2395"})
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(422, detail={"code": "bad_point", "message": f"'{name}' is not a valid lat,lon"})
    return lat, lon


def create_app(segments_path=None):
    segments_path = Path(segments_path or os.environ.get("LIGHTMAP_SEGMENTS") or DEFAULT_SEGMENTS)
    places_path = segments_path.parent / "places.json.gz"
    state = {"net": None, "places": None}

    @asynccontextmanager
    async def lifespan(_app):
        if segments_path.exists():
            state["net"] = Network.load(segments_path)
        if places_path.exists():
            state["places"] = Places.load(places_path)
        yield

    app = FastAPI(title="Night route: lighting map API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # a map window is ~250 KB of JSON, ~40 KB compressed

    def network():
        if state["net"] is None:
            raise HTTPException(503, detail={"code": "no_data", "message": f"{segments_path} not found. Build it: ./scripts/mac/lightmap.sh city"})
        return state["net"]

    @app.get("/links", response_class=HTMLResponse, include_in_schema=False)
    def links():
        return INDEX_HTML

    @app.get("/api/health")
    def health():
        net = state["net"]
        return {"ok": net is not None, "segments": len(net.props) if net else 0, "data_as_of": net.meta.get("as_of") if net else None}

    @app.get("/api/summary")
    def summary():
        """Shares of the network by lighting status, checks, per-district table, sources with dates."""
        network()
        path = segments_path.parent / "summary.json"
        if not path.exists():
            raise HTTPException(404, detail={"code": "no_summary", "message": "summary.json not found next to the segments file"})
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/geocode")
    def geocode(q: str = Query("", max_length=120, description="what the person typed: street and number, place or stop"),
                limit: int = Query(8, ge=1, le=20)):
        """Suggestions while typing, only inside the map area. No request leaves our server: no external geocoder,
        so typed addresses are not sent anywhere."""
        if state["places"] is None:
            raise HTTPException(503, detail={"code": "no_places", "message": f"{places_path} not found. Build it: backend/build_places.py"})
        return {"query": q, "results": state["places"].search(q, limit)}

    @app.get("/api/segments")
    def segments(bbox: str = Query(description="west,south,east,north in degrees"),
                 limit: int = Query(SEGMENT_LIMIT_DEFAULT, ge=1, le=SEGMENT_LIMIT_MAX)):
        """Segments whose bounding box touches the window. If there are more than `limit`,
        no features are returned and `truncated` is true: zoom in, or show districts from /api/summary."""
        try:
            west, south, east, north = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(422, detail={"code": "bad_bbox", "message": "bbox must be west,south,east,north"})
        if west >= east or south >= north:
            raise HTTPException(422, detail={"code": "bad_bbox", "message": "bbox must be west,south,east,north with west < east and south < north"})
        net = network()
        idx = net.segments_in_bbox(west, south, east, north)
        truncated = len(idx) > limit
        return {"type": "FeatureCollection", "count": len(idx), "limit": limit, "truncated": truncated,
                "data_as_of": net.meta.get("as_of"), "features": [] if truncated else [net.feature(i) for i in idx]}

    @app.get("/api/segments/{segment_id}")
    def segment(segment_id: str):
        """One segment with the evidence behind its status (OSM tag, Mapillary lamps, complaints, indirect signs)."""
        net = network()
        i = net.by_id.get(segment_id)
        if i is None:
            raise HTTPException(404, detail={"code": "no_segment", "message": "unknown segment id"})
        return net.feature(i, full=True)

    @app.get("/api/route")
    def route(from_: str = Query(alias="from", description="start as lat,lon"),
              to: str = Query(description="destination as lat,lon"),
              mode: str = Query("walk", description="only 'walk' for now")):
        """Fastest and better-lit walking routes. Darkness never blocks a route, it only makes it costlier."""
        if mode != "walk":
            raise HTTPException(422, detail={"code": "mode_not_supported", "message": "only mode=walk is available yet"})
        net = network()
        snapped = {}
        for name, value in (("from", from_), ("to", to)):
            lat, lon = parse_point(value, name)
            snap = net.snap(lat, lon)
            if snap is None:
                nearest = net.nearest_m(lat, lon)
                raise HTTPException(422, detail={"code": "outside_coverage", "point": name,
                                                 "nearest_m": None if nearest is None else round(nearest),
                                                 "message": f"'{name}' is farther than {SETTINGS['snap_max_m']:.0f} m from the mapped network"})
            snapped[name] = (lat, lon, snap)
        plan = net.plan(snapped["from"][2], snapped["to"][2])
        if plan is None:
            raise HTTPException(404, detail={"code": "no_route", "message": "no walking route between these points"})
        point = lambda lat, lon, s: {"lat": lat, "lon": lon, "snapped": [s.lat, s.lon], "snap_m": round(s.d, 1)}
        return {"mode": mode, "from": point(*snapped["from"]), "to": point(*snapped["to"]), **plan,
                "settings": SETTINGS, "data_as_of": net.meta.get("as_of")}

    # The city page (web/) at "/", the older demos under /demo and /data/out. Only these folders are exposed.
    # "/" must be mounted last: it catches every path the API routes above did not.
    for url, folder in (("/demo", ROOT / "demo"), ("/data/out", ROOT / "data/out"), ("/", ROOT / "web")):
        if folder.is_dir():
            app.mount(url, StaticFiles(directory=folder, html=True), name=url.strip("/").replace("/", "-") or "web")
    return app


app = create_app()
