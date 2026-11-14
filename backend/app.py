"""HTTP API over the city lighting network.

run:  .venv/bin/uvicorn backend.app:app --port 8001      (or ./scripts/mac/lightmap.sh api)
docs: http://localhost:8001/docs
Data: data/out/city/segments.geojson.gz from backend/build_city.py; override with LIGHTMAP_SEGMENTS=<path>.
"""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import datetime as dt
from zoneinfo import ZoneInfo

from backend.ask import LIMITS as ASK_LIMITS, AskError, Asker, Gemini, load_env
from backend.geocode import Places
from backend.liveliness import LIVELY, Signs
from backend.routing import MODES, SETTINGS, Network
from backend.transit import TRANSIT, Timetable, Transit

LOCAL_TZ = ZoneInfo("Europe/Bucharest")

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


def leaving_time(at):
    """Local wall-clock time in Timișoara: now, 'HH:MM' today, or 'YYYY-MM-DDTHH:MM'."""
    now = dt.datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if not at:
        return now
    try:
        if "T" in at:
            return dt.datetime.fromisoformat(at)
        hour, minute = (int(x) for x in at.split(":"))
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(422, detail={"code": "bad_time", "message": "at must be 'HH:MM' or 'YYYY-MM-DDTHH:MM'"})


class AskIn(BaseModel):
    """A request in plain words: typed text, or a short voice recording as base64."""
    text: str = Field("", max_length=ASK_LIMITS["text_chars"], description="what the person typed, e.g. 'de la căminul C12 la Piața Victoriei cu bicicleta'")
    audio: str = Field("", max_length=ASK_LIMITS["audio_b64_chars"], description="voice recording, base64 (the page sends 16 kHz mono WAV, at most 10 s)")
    mime: str = Field("audio/wav", max_length=40)
    lang: str = Field("ro", max_length=5, description="interface language: ro, en or ru")
    near: str = Field("", max_length=40, description="current start point as lat,lon, if any: 'the nearest pharmacy' is "
                                                      "picked next to it. Stays on this server, never goes to Gemini")


def create_app(segments_path=None, gemini=None):
    """gemini: a backend.ask.Gemini (tests pass a fake); by default built from GEMINI_API_KEY in .env or the environment."""
    load_env(ROOT / ".env")
    segments_path = Path(segments_path or os.environ.get("LIGHTMAP_SEGMENTS") or DEFAULT_SEGMENTS)
    places_path = segments_path.parent / "places.json.gz"
    transit_path = segments_path.parent / "transit.json.gz"

    state = {"net": None, "places": None, "transit": None, "asker": None, "signs": None}

    @asynccontextmanager
    async def lifespan(_app):
        if segments_path.exists():
            state["net"] = Network.load(segments_path)
        if places_path.exists():
            state["places"] = Places.load(places_path)
        if state["net"] is not None and transit_path.exists():
            state["transit"] = Transit(state["net"], Timetable.load(transit_path))
        ai = gemini or Gemini.from_env()
        if ai is not None and state["places"] is not None:
            state["asker"] = Asker(ai, state["places"])
        if state["net"] is not None and state["places"] is not None:
            state["signs"] = Signs(state["net"], [item["e"] for item in state["places"].items],
                                   state["transit"].tt if state["transit"] else None)
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
        return {"ok": net is not None, "segments": len(net.props) if net else 0, "data_as_of": net.meta.get("as_of") if net else None,
                "ask": state["asker"] is not None}

    @app.post("/api/ask")
    def ask(body: AskIn, request: Request):
        """A route asked in plain words, typed or spoken (Romanian, English, Russian). Gemini only fills in a form
        (from, to, mode, time); the places are then found in our own index. Answers:
        kind "route" (points to route between), "not_found" (a place is not in the map area), "unclear",
        or "off_topic" for anything that is not a route request: the assistant does not answer other questions.
        The text or recording is sent to Google and is not stored here; no coordinates are sent."""
        if state["asker"] is None:
            raise HTTPException(503, detail={"code": "ai_not_configured", "message": "GEMINI_API_KEY is not set or the place index is missing"})
        client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "-")
        near = parse_point(body.near, "near") if body.near else None
        try:
            return state["asker"].ask(text=body.text, audio=body.audio, mime=body.mime, lang=body.lang, client=client, near=near)
        except AskError as e:
            if e.status >= 500:
                print(f"ask: {e.code}: {e}", flush=True)  # the reason stays in the server log, not in the answer
            raise HTTPException(e.status, detail={"code": e.code, "message": e.code if e.status >= 500 else str(e)})

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
              mode: str = Query("walk", description="'walk', 'bike' or 'transit' (on foot + public transport)"),
              at: str = Query("", description="leaving time 'HH:MM' today or 'YYYY-MM-DDTHH:MM'; empty = now")):
        """Fastest and better-lit routes on foot or by bike. Darkness never blocks a route, it only makes it costlier.
        By bike: only segments open to bikes, one-way streets in their direction, "dismount" at walking speed.
        transit: the walking routes plus "transit": walk (better lit) to a stop, one line, walk to the door."""
        if mode not in MODES + ("transit",):
            raise HTTPException(422, detail={"code": "mode_not_supported", "message": f"mode must be one of {', '.join(MODES + ('transit',))}"})
        net = network()
        net_mode = "walk" if mode == "transit" else mode
        snapped = {}
        for name, value in (("from", from_), ("to", to)):
            lat, lon = parse_point(value, name)
            snap = net.snap(lat, lon, mode=net_mode)
            if snap is None:
                nearest = net.nearest_m(lat, lon, mode=net_mode)
                raise HTTPException(422, detail={"code": "outside_coverage", "point": name,
                                                 "nearest_m": None if nearest is None else round(nearest),
                                                 "message": f"'{name}' is farther than {SETTINGS['snap_max_m']:.0f} m from the mapped network"})
            snapped[name] = (lat, lon, snap)
        plan = net.plan(snapped["from"][2], snapped["to"][2], mode=net_mode)
        if plan is None:
            raise HTTPException(404, detail={"code": "no_route", "message": f"no {net_mode} route between these points"})
        point = lambda lat, lon, s: {"lat": lat, "lon": lon, "snapped": [s.lat, s.lon], "snap_m": round(s.d, 1)}
        when = leaving_time(at)
        extra = {"at": when.strftime("%Y-%m-%d %H:%M")}
        if state["signs"] is not None:  # signs of life along each route at the leaving time (evidence, not a score)
            for r in plan["routes"].values():
                r["signs"] = state["signs"].along(r, when)
        if mode == "transit":
            if state["transit"] is None:
                raise HTTPException(503, detail={"code": "no_timetable", "message": f"{transit_path} not found. Build it: backend/build_transit.py"})
            extra["transit"] = state["transit"].plan(snapped["from"][2], snapped["to"][2], when)
        return {"mode": mode, "from": point(*snapped["from"]), "to": point(*snapped["to"]), **plan, **extra,
                "settings": {**SETTINGS, "transit": TRANSIT, "lively": LIVELY}, "data_as_of": net.meta.get("as_of")}

    # The city page (web/) at "/", the older demos under /demo and /data/out. Only these folders are exposed.
    # "/" must be mounted last: it catches every path the API routes above did not.
    for url, folder in (("/demo", ROOT / "demo"), ("/data/out", ROOT / "data/out"), ("/", ROOT / "web")):
        if folder.is_dir():
            app.mount(url, StaticFiles(directory=folder, html=True), name=url.strip("/").replace("/", "-") or "web")
    return app


app = create_app()
