# bezna — night routes with an honest lighting map (Timișoara)

**RO.** bezna găsește drumul pe jos, cu bicicleta sau cu transportul public prin Timișoara și arată, pentru fiecare porțiune de stradă, cât de bine știm că este iluminată și de unde știm. „Fără date” nu înseamnă „întuneric”, iar aplicația nu spune niciodată că un drum e „sigur”: avem date despre lumină, nu despre criminalitate. Zona acoperită: campusul universitar și centrul. Proiect UniHack 2026, secțiunea Green Mobility.

**EN.** bezna plans walking, cycling and walk + public transport routes in Timișoara and shows, for every stretch of street, how well we know it is lit and how we know. "No data" is never shown as "dark", and the app never calls a route "safe": we have lighting data, not crime data. Covered area: the university campus and the city centre. UniHack 2026, Green Mobility track.

## What it does

- Two routes for every trip: the fastest and a better-lit one, with the extra minutes and the reason (for example, it avoids 149 m reported as unlit). If the better-lit route costs too much, it is not offered as the main choice.
- Every stretch has one of four statuses, told apart by line pattern as well as tone: confirmed lit, likely lit, no data, reported as unlit. Tapping a stretch shows its sources and their dates.
- Signs of life along the way at the leaving time: open places (OpenStreetMap opening hours) and stops with departures (timetable). Evidence, not a score.
- Walk + public transport with the SMTT timetable and live vehicles from the city's API: where the vehicle is, its reported delay, how old the position is.
- A navigator that follows the phone's GPS and warns before a stretch reported as unlit.
- Typed or spoken requests in plain words (Gemini only fills in a form; places are found in our own index).
- Romanian first, then English and Russian. WCAG 2.1 AA as a target: status never by colour alone, 44 px touch targets.

## Run it

Python 3.12.

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt          # Windows: .venv\Scripts\pip
.venv/bin/uvicorn backend.app:app --port 8001
```

Open http://localhost:8001/m/ (phone layout, "bezna") or http://localhost:8001/ (the earlier desktop page). API docs: http://localhost:8001/docs. Active coverage is 9.61 km²: the university campus, centre, selected northeastern neighbourhoods, Circumvalațiunii–Dacia and Mircea cel Bătrân. Built data is in `data/out/city-northwest/`; no download is needed to run it. `LIGHTMAP_SEGMENTS` can select another dataset. Optional: `GEMINI_API_KEY` in `.env` turns on the plain-words box (see `.env.example`).

Tests: `.venv/bin/python -m pytest backend/tests -q`.

## Where things are

| Path | What |
|---|---|
| `backend/` | lighting status of every street segment, routing, timetable, live vehicles, place search, Gemini form filling; see `backend/README.md` |
| `web/m/` | the phone layout; `web/` the desktop page; see `web/README.md` |
| `android/` | the Android app: the phone layout in a WebView with a native navigator bridge; see `android/README.md` |
| `config/area-northwest.geojson` | active coverage boundary (9.61 km²) |
| `data/out/city-northwest/` | active network, search index, summary and timetable |
| `config/area-expanded.geojson`, `data/out/city-expanded/` | previous northeast extension (7.73 km²), kept for comparison |
| `config/area.geojson`, `data/out/city/` | previous 4.71 km² area, kept for comparison |
| `PLAN.md` | plan and status (in Russian) |
| `docs/` | research notes, design brief, bug reports |

## Data and their licences

| Source | Used for | Licence / terms |
|---|---|---|
| OpenStreetMap | streets, `lit` tags, places and opening hours, map tiles | © OpenStreetMap contributors, ODbL 1.0 |
| Mapillary | street lights detected in street-level images | CC BY-SA 4.0 |
| Primăria Timișoara, Sesizări | reports of public lighting out | the report text and photos are not republished; only position, date and state are used |
| SMTT GTFS timetable | walk + transit | published by SMTT Timișoara (smtt.ro) |
| Primăria Timișoara transit API | live vehicle positions and delays | public endpoint, queried at most every 15 s through one shared cache |
| Street-light icon | favicon | Magnific / Flaticon, free licence with attribution (credited on the map) |

Libraries: Leaflet (BSD-2-Clause, `web/vendor/leaflet/LICENSE`), FastAPI, osmnx, Shapely and others listed in `backend/requirements.txt`. Fonts: Inter, Inter Tight, JetBrains Mono (SIL Open Font License).

## Licence

Code: MIT, see `LICENSE`. Data keep their own licences above.
