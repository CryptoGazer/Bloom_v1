"""HTTP API over the city lighting network.

run:  .venv/bin/uvicorn backend.app:app --port 8001      (or ./scripts/mac/lightmap.sh api)
docs: http://localhost:8001/docs
Data: data/out/city-northwest/segments.geojson.gz from backend/build_city.py; override with LIGHTMAP_SEGMENTS=<path>.
"""
import json
import math
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import datetime as dt
from zoneinfo import ZoneInfo

from backend.ask import ASK_VERSION, LIMITS as ASK_LIMITS, AskError, Asker, Gemini, load_env
from backend.geocode import Places
from backend.history import HISTORY, History
from backend.live import LIVE, Live, Vehicles, epoch, fetch_city
from backend.liveliness import LIVELY, Signs
from backend.loops import DEFAULT_RADIUS_M, MAX_RADIUS_M, MIN_RADIUS_M, around
from backend.routing import MODES, SETTINGS, Network
from backend.speak import SPEAK, SpeakError, Speaker
from backend.transit import TRANSIT, Timetable, Transit
from backend.web_assets import APINoStore, WebAssets

LOCAL_TZ = ZoneInfo("Europe/Bucharest")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEGMENTS = ROOT / "data/out/city-northwest/segments.geojson.gz"
SEGMENT_LIMIT_DEFAULT, SEGMENT_LIMIT_MAX = 4000, 20000

INDEX_HTML = """<!doctype html><html lang="ru"><meta charset="utf-8"><title>Night route API</title>
<body style="font:15px/1.5 system-ui;max-width:640px;margin:40px auto;padding:0 16px">
<h1>Ночной маршрут: API</h1>
<ul>
<li><a href="/">/</a> — карта города с маршрутами</li>
<li><a href="/docs">/docs</a> — попробовать запросы в браузере</li>
<li><a href="/api/summary">/api/summary</a> — сводка по городу</li>
<li><a href="/api/route?from=45.7470,21.2395&to=45.7415,21.2200">/api/route</a> — пример маршрута</li>
<li><a href="/api/loop?points=45.7538,21.2259;45.7580,21.2290;45.7575,21.2335">/api/loop</a> — пример круговой прогулки</li>
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


def point_json(lat, lon, snap):
    """A requested point and where it lies on the network."""
    return {"lat": lat, "lon": lon, "snapped": [snap.lat, snap.lon], "snap_m": round(snap.d, 1)}


def settings_json():
    return {**SETTINGS, "transit": TRANSIT, "lively": LIVELY, "live": LIVE, "history": HISTORY}


LATE_GRACE = dt.timedelta(hours=1)   # 'HH:MM' more than this before now means the next day: at 23:59, "00:05" is tonight


def leaving_time(at, now=None):
    """Local wall-clock time in Timișoara: now, 'HH:MM' (today, or tomorrow if it is over an hour ago), or 'YYYY-MM-DDTHH:MM'."""
    now = now or dt.datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if not at:
        return now
    try:
        if "T" in at:
            when = dt.datetime.fromisoformat(at)
            # a time with a zone ("…+02:00", "…Z") is read as Timișoara wall-clock time, like every other time here
            return when.astimezone(LOCAL_TZ).replace(tzinfo=None) if when.tzinfo else when
        hour, minute = (int(x) for x in at.split(":"))
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return when + dt.timedelta(days=1) if when < now - LATE_GRACE else when
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


def create_app(segments_path=None, gemini=None, live_fetch=None, history=None, speaker=None):
    """gemini: a backend.ask.Gemini (tests pass a fake); by default built from GEMINI_API_KEY in .env or the environment.
    live_fetch: what reads the city's live vehicles (tests pass a fake); by default backend.live.fetch_city.
    history: a backend.history.History (tests pass one with a fake loader); by default read from Tiger Data in the
    background if TIGER_READ_URL or TIGER_DATABASE_URL is set.
    speaker: a backend.speak.Speaker (tests pass one with a fake provider); by default built from ELEVENLABS_API_KEY
    and the ELEVENLABS_VOICE_ID_* variables."""
    load_env(ROOT / ".env")
    segments_path = Path(segments_path or os.environ.get("LIGHTMAP_SEGMENTS") or DEFAULT_SEGMENTS)
    places_path = segments_path.parent / "places.json.gz"
    transit_path = segments_path.parent / "transit.json.gz"

    state = {"net": None, "places": None, "transit": None, "asker": None, "signs": None, "live": None, "history": history, "speaker": speaker}

    @asynccontextmanager
    async def lifespan(_app):
        if segments_path.exists():
            state["net"] = Network.load(segments_path)
        if places_path.exists():
            state["places"] = Places.load(places_path)
        if state["net"] is not None and transit_path.exists():
            state["transit"] = Transit(state["net"], Timetable.load(transit_path))
            state["live"] = Live(Vehicles(live_fetch or fetch_city), state["transit"].tt)
        ai = gemini or Gemini.from_env()
        if ai is not None and state["places"] is not None:
            state["asker"] = Asker(ai, state["places"])
        if state["net"] is not None and state["places"] is not None:
            state["signs"] = Signs(state["net"], [item["e"] for item in state["places"].items],
                                   state["transit"].tt if state["transit"] else None)
        if state["speaker"] is None:
            state["speaker"] = Speaker.from_env(ROOT / "data/cache/speak")   # None without a key or a voice
        if state["history"] is None and state["transit"] is not None:
            state["history"] = History.from_env()
            if state["history"] is not None:
                state["history"].start()  # reads Tiger Data in the background; the server does not wait for it
        yield

    app = FastAPI(title="Night route: lighting map API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # a map window is ~250 KB of JSON, ~40 KB compressed
    app.add_middleware(APINoStore)
    web = WebAssets(directory=ROOT / 'web', html=True)

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
                "ask": state["asker"] is not None, "ask_version": ASK_VERSION, "ui_version": web.version(),
                "features": {"loop": True, "gemini_loop": True, "gemini_loop_waypoints": True},
                "history": state["history"] is not None and state["history"].ready,
                # interface languages that have an ElevenLabs voice; the page speaks the others with the phone's own voice
                "speak": state["speaker"].languages() if state["speaker"] is not None else []}

    @app.post("/api/ask")
    def ask(body: AskIn, request: Request):
        """A route asked in plain words, typed or spoken (Romanian, English, Russian). Gemini only fills in a form
        (from, to, mode, time); the places are then found in our own index. Answers:
        kind "route" (points to route between), "loop" (centre and target radius for /api/loop),
        "unsupported" (a transit loop), "not_found" (a place is not in the map area), "unclear",
        "clarify" (ambiguous places, with missing/ambiguity and verified candidates),
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

    @app.get("/api/speak")
    def speak(request: Request,
              text: str = Query(max_length=2 * SPEAK["text_chars"], description="a short phrase of the navigator, e.g. '50 de metri. La dreapta pe Strada Cluj.'"),
              lang: str = Query("ro", max_length=5, description="interface language: ro or en; each has its own voice")):
        """The phrase read aloud by the ElevenLabs voice of that language, as MP3. Each phrase is generated once and then
        served from a cache. Only the phrase goes to ElevenLabs: no coordinates and nothing about who asked. Errors
        (no voice for the language, over the limits, the service down) are meant to be answered by the phone's own voice."""
        if lang not in SPEAK["languages"]:
            raise HTTPException(422, detail={"code": "bad_lang", "message": "lang must be ro or en"})
        if state["speaker"] is None:
            raise HTTPException(503, detail={"code": "voice_not_configured", "message": "ELEVENLABS_API_KEY or a voice id is not set"})
        client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "-")
        try:
            audio = state["speaker"].clip(text, lang, client)
        except SpeakError as e:
            if e.status >= 500:
                print(f"speak: {e.code}: {e}", flush=True)  # the reason stays in the server log, not in the answer
            raise HTTPException(e.status, detail={"code": e.code, "message": e.code if e.status >= 500 else str(e)})
        return Response(audio, media_type="audio/mpeg")

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
        if not all(math.isfinite(x) for x in (west, south, east, north)) or west >= east or south >= north:
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
        when = leaving_time(at)
        extra = {"at": when.strftime("%Y-%m-%d %H:%M")}
        if state["signs"] is not None:  # signs of life along each route at the leaving time (evidence, not a score)
            for r in plan["routes"].values():
                r["signs"] = state["signs"].along(r, when)
        if mode == "transit":
            if state["transit"] is None:
                raise HTTPException(503, detail={"code": "no_timetable", "message": f"{transit_path} not found. Build it: backend/build_transit.py"})
            extra["transit"] = state["transit"].plan(snapped["from"][2], snapped["to"][2], when)
            for leg in extra["transit"].get("legs", []):
                if leg["type"] == "ride":  # the scheduled departure as unix time: what /api/transit/live compares with
                    leg["dep_ts"] = round(epoch(leg["day"], leg["dep_s"], LOCAL_TZ))
                    # Historical observations remain optional when Tiger Data is not configured.
                    leg["history"] = state["history"].ride(leg) if state["history"] is not None else None
        return {"mode": mode, "from": point_json(*snapped["from"]), "to": point_json(*snapped["to"]), **plan, **extra,
                "settings": settings_json(), "data_as_of": net.meta.get("as_of")}

    @app.get("/api/loop")
    def loop(points: str = Query("", max_length=600, description="lat,lon;lat,lon;... in visiting order, 2 to 10 points; or use center"),
             mode: str = Query("walk", description="'walk' or 'bike'"),
             at: str = Query("", description="leaving time, as for /api/route"),
             center: str = Query("", max_length=80, description="lat,lon: automatically choose a circuit around this centre instead of supplying points"),
             radius_m: float = Query(DEFAULT_RADIUS_M, ge=MIN_RADIUS_M, le=MAX_RADIUS_M, description="approximate circuit radius, may shrink near the edge of coverage"),
             start: str = Query("", max_length=80, description="optional lat,lon start and finish for an automatic circuit")):
        """A closed walk or ride through the points in their order and back to the first: the fastest and the
        better-lit loop, judged like /api/route. Later legs avoid the streets the loop has already used."""
        if mode not in MODES:
            raise HTTPException(422, detail={"code": "mode_not_supported", "message": f"mode must be one of {', '.join(MODES)}"})
        if bool(points) == bool(center) or (start and not center):
            raise HTTPException(422, detail={"code": "bad_points", "message": "supply either points or center (with optional start)"})
        when = leaving_time(at)
        net = network()
        generated = {}
        if center:
            coords = parse_point(center, "center")
            start_coords = parse_point(start, "start") if start else None
            for name, p in (("center", coords), ("start", start_coords)):
                if p is not None and net.snap(*p, mode=mode) is None:
                    raise HTTPException(422, detail={"code": "outside_coverage", "point": name,
                                                     "message": f"{name} is outside the mapped {mode} network"})
            selection = around(net, coords, radius_m, mode, net.snap(*start_coords, mode=mode) if start_coords else None)
            if selection is None:
                raise HTTPException(422, detail={"code": "no_loop_area", "message": "no reasonable circuit around this centre fits the mapped network"})
            snaps, plan, actual_radius = selection
            snapped = [(p.lat, p.lon, replace(p, d=0)) for p in snaps]
            if start_coords:
                snapped[0] = (*start_coords, snaps[0])
            generated = {"generated": True, "center": {"lat": coords[0], "lon": coords[1]},
                         "radius_m": actual_radius, "requested_radius_m": radius_m}
        else:
            raw = [p for p in points.split(";") if p.strip()]
            if not 2 <= len(raw) <= SETTINGS["loop_max_points"]:
                raise HTTPException(422, detail={"code": "bad_points", "message": f"2 to {SETTINGS['loop_max_points']} points as lat,lon;lat,lon"})
            snapped = []
            for i, value in enumerate(raw, 1):
                lat, lon = parse_point(value, f"point {i}")
                snap = net.snap(lat, lon, mode=mode)
                if snap is None:
                    nearest = net.nearest_m(lat, lon, mode=mode)
                    raise HTTPException(422, detail={"code": "outside_coverage", "point": i,
                                                     "nearest_m": None if nearest is None else round(nearest),
                                                     "message": f"point {i} is farther than {SETTINGS['snap_max_m']:.0f} m from the mapped network"})
                snapped.append((lat, lon, snap))
            plan = net.loop([snap for _, _, snap in snapped], mode=mode)
        if plan is None:
            raise HTTPException(404, detail={"code": "no_route", "message": f"no {mode} loop through these points"})
        if state["signs"] is not None:
            for r in plan["routes"].values():
                r["signs"] = state["signs"].along(r, when)
        pts = [point_json(*p) for p in snapped]
        return {"mode": mode, "loop": True, "points": pts, "from": pts[0], "to": pts[0], **plan, **generated, "at": when.strftime("%Y-%m-%d %H:%M"),
                "settings": settings_json(), "data_as_of": net.meta.get("as_of")}

    @app.get("/api/transit/live")
    def transit_live(route: str = Query("", max_length=40, description="only this line, GTFS route_id such as R_AB_16; empty = every line in the area"),
                     trip: str = Query("", max_length=80, description="a planned trip to follow: its GTFS trip_id (from /api/route, mode=transit)"),
                     seq: int | None = Query(None, ge=0, description="GTFS stop_sequence of the boarding stop of that trip"),
                     dep: float | None = Query(None, description="scheduled departure at the boarding stop, unix seconds"),
                     day: str = Query("", max_length=10, description="the plan's day YYYY-MM-DD (ride.day), to pick the GTFS feed")):
        """Vehicles of the city's public transport now, inside the map area, and the live state of one planned trip.
        One shared copy of the city's answer, refreshed at most every LIVE.refresh_s. Each vehicle has the age of its
        GPS point; older than LIVE.stale_s is not live. trip.status: later, previous_trip (its vehicle still runs an
        earlier trip of its block), no_vehicle, stale, passed, no_forecast, live (expected = timetable + reported delay,
        an estimate), or no_data when the city server has not answered yet."""
        if state["live"] is None:
            raise HTTPException(503, detail={"code": "no_timetable", "message": f"{transit_path} not found. Build it: backend/build_transit.py"})
        return state["live"].answer(route=route, trip=trip, seq=seq, dep=dep, day=day or None)

    # The city page (web/) at "/", the older demos under /demo and /data/out. Only these folders are exposed.
    # "/" must be mounted last: it catches every path the API routes above did not.
    for url, folder in (("/demo", ROOT / "demo"), ("/data/out", ROOT / "data/out"), ("/", ROOT / "web")):
        if folder.is_dir():
            app.mount(url, web if url == '/' else StaticFiles(directory=folder, html=True), name=url.strip("/").replace("/", "-") or "web")
    return app


app = create_app()
