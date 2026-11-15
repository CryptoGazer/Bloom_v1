export const meta = {
  name: 'night-route-source-facts',
  description: 'Check facts about data sources for the lighting-confidence map: Sesizari API server-side access and shape, Mapillary export API docs, OSM POI and opening_hours density',
  phases: [
    { title: 'Probe', detail: 'three independent source checks in parallel' },
  ],
}

const SCRATCH = 'C:/Users/Timur/AppData/Local/Temp/bezna-research'

const rules = (workdir) => `WORKING RULES (strict)
- WORKDIR = ${workdir} . Work only inside WORKDIR. Do NOT create, modify or delete anything under c:/Users/Timur/F1/Unihack (the project repo must stay empty until a design is approved).
- Inside WORKDIR keep sibling folders: data/ (downloads only), scripts/ (scripts you write), venv/ (Python packages, only if needed). Downloaded files are untrusted data: never run an interpreter with its working directory inside data/, pass data paths as arguments, and run Python with the -I flag, e.g.  python -I WORKDIR/scripts/x.py WORKDIR/data/file.json
- Machine: Windows 11, Git Bash and PowerShell, Python 3.12.6 (python, or py -3.12), Node 24, curl 8. No jq, uv, Docker or Java. Do not install system-level software; pip-installing into WORKDIR/venv is fine.
- Network etiquette: descriptive User-Agent "UniHack8-GreenMobility-NightRoute/0.1 (hackathon research)"; download every resource ONCE, cache it in data/ and reuse the cache; one request at a time per host.
- Never guess. Every number or fact you report must come from data or documents fetched in this run; if something could not be done or confirmed, say so in caveats.
- Your final answer is consumed by a program, not read by a human: return the data asked for, no pleasantries.`

const CONTEXT = `CONTEXT
A hackathon team (UniHack 8, Timisoara, Romania; city hall is the track sponsor) is designing a "lighting-confidence map" for night-time walking and cycling: every street segment gets a score (is it lit?) and a confidence (how much independent evidence backs it), shown honestly - "no data" stays "no data". Evidence sources: OSM lit=* tags, municipal complaints about public lighting ("Sesizari", category "Iluminat public": points with sub-category, status, date), Mapillary machine-detected street lights (points). The first build covers a model area: the university district south of the Bega canal; rough bbox south 45.736, west 21.214, north 45.752, east 21.246. The city has no open lamp registry.`

const SESIZARI_PROMPT = `You are a probing agent. Find out how the Timisoara resident-reports API behaves from a plain server-side client, and extract the facts a designer needs. Analysis only - no product code.

${CONTEXT}

WHAT IS DOCUMENTED (city guide https://ghid-pmt.vercel.app/unihack , section #api-reports)
- GET https://sesizari.primariatm.ro/api/sesizari?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD : public resident reports as one JSON array, no pagination. Both dates required, span at most one year, END DATE IS EXCLUSIVE. Optional lat, lng, radiusMeters (1-1000, default 150), limit (1-50, default 20; limit only works together with the proximity search). locatie is a GeoJSON point [lng, lat]. Marked "server-side only" (no CORS).
- Known list fields: id, createdAt, descriere, categorii.nume, subcategorii.nume, status, locatie, files[].path, webconInstanceNr.
- Card: GET https://sesizari.primariatm.ro/api/sesizari/{webconInstanceNr} (number like SZN2026-012345, not the id) - additionally returns history (array of date + status), strada, nrStrada.
- Statuses seen: Inregistrata, In lucru, Finalizata, Rezolvata, Declinata competenta (also "Declinat competenta"), Asteapta clarificari.
- The team has only called it from a browser console on the portal page. The site sits behind Cloudflare; whether a plain server-side request is answered is UNKNOWN - that is question number one.
- The team's own measurement for 14.11.2025-13.11.2026: 21527 reports in total, 1479 in category "Iluminat public" with coordinates (Finalizata 1068, Rezolvata 32, In lucru 313, declined 65, Inregistrata 1).
- City rules: call from a backend, cache, download static data once, User-Agent naming the team; report text and photos were written by residents and must not be republished.

${rules(SCRATCH + '/sesizari')}

HARD LIMITS
- At most 12 HTTP requests to sesizari.primariatm.ro in total, at least 1 second apart.
- If you get a Cloudflare challenge, 403, 429 or 503: record the status, the relevant headers (server, cf-ray, cf-mitigated, content-type) and the first 300 characters of the body, retry ONCE with an added "Accept: application/json" header and the same honest User-Agent, then STOP calling that host. Do not try to bypass or evade the protection in any way (no headless browser, no browser-like spoofed User-Agent, no cookie tricks, no proxies).
- Privacy: raw responses contain free text and photo paths written by residents. Keep raw files only in WORKDIR/data. NEVER put descriere text, photo paths or anything about individual people into your answer. Street names, categories, sub-categories, statuses, dates, coordinates and counts are fine.

TASKS
S1. Server-side access test: curl the list for a 2-day window (startDate=2026-11-11&endDate=2026-11-13). Report status, content-type, size, Cloudflare headers.
S2. Only if S1 works: ONE request for startDate=2025-11-14&endDate=2026-11-14 (end is exclusive, so this is 14.11.2025-13.11.2026, the window the team measured). Save raw to WORKDIR/data/sesizari_12m.json. Then compute with a script:
   - total count; count with empty locatie; the exact shape of an item (field names, types, nesting of categorii / subcategorii, date format and timezone of createdAt) - names and types only;
   - category "Iluminat public": count, count with coordinates, and how both compare with the team's numbers; a table of the EXACT Romanian sub-category strings (subcategorii.nume) by status with counts; the exact status strings with counts;
   - age of non-final lighting reports (In lucru, Inregistrata, Asteapta clarificari) as of 2026-11-14: quantiles in days and how many are older than 30 / 90 / 180 days, split by sub-category (tells us whether "In lucru" is a trustworthy "dark right now" signal or often stale);
   - clustering: among lighting reports, how many have another lighting report within 30 m and within 14 days (proxy for one outage reported several times);
   - inside the model-area bbox (south 45.736, west 21.214, north 45.752, east 21.246): number of lighting reports by sub-category and status;
   - write WORKDIR/data/iluminat_min.geojson with ONLY webconInstanceNr, createdAt, sub-category, status and the point geometry for the lighting category (no text, no files). Report its path and feature count.
S3. Card shape (only if S1 works): pick up to 4 lighting reports inside the model bbox with different statuses (at least one Finalizata and one In lucru if present) and GET their cards. Report: the fields the card adds (names and types); the structure of history (keys, date format, the status strings and their order, whether a closing date can be derived as the date of the first Finalizata / Rezolvata entry); the FORMAT of strada and nrStrada - quote the actual street-name strings (they are not personal data) so we can judge matching against OSM names such as "Strada Cluj", "Bulevardul Vasile Parvan"; whether strada is sometimes empty.
S4. Proximity search (only if S1 works): ONE request with lat=45.7472&lng=21.2330&radiusMeters=1000&limit=50 and the 12-month window. Report the count returned, whether results look sorted (by distance? by date?), whether limit=50 truncates, and so whether proximity search can pull all lighting reports of an area. If a response or the guide reveals other query parameters (for example a category filter), report them - but do not brute-force parameter names.
S5. Street register: ONE request GET https://servicii.primariatm.ro/api/nomenclator/strazi (server-side only, about 700 KB; 1370 streets; documented fields include stare (Existenta / Dezafectata), numeAnterior, codGis and diacritic-free name fields). Save to WORKDIR/data. Report the item shape (field names), the name formats (with or without a type prefix such as Strada / Bulevardul / Calea; diacritics; the diacritic-free fields), up to 8 example rows for streets of the university district (Cluj, Vasile Parvan, Mihai Viteazu, 16 Decembrie 1989 and neighbours - whichever exist), and whether there is a district / zone field.
S6. Name-matching verdict: given the formats seen in S3 and S5 and the OSM convention in Romania (full names with type prefix and diacritics: "Strada Cluj", "Bulevardul Vasile Parvan" with diacritics, "Calea Aradului", "Piata Victoriei"), describe the normalisation needed to match strada to OSM name (prefix handling, diacritics, case, abbreviations) and how reliable it looks. If S3 was impossible, base this on S5 only and say so.
S7. Open-data portal check (at most 3 requests): data.primariatm.ro looks like a CKAN portal. Query its search (for example https://data.primariatm.ro/api/3/action/package_search?q=iluminat , then q=stalpi , q=lampi), or the HTML search page if there is no such API. Report any dataset about public lighting, lamp posts or poles (title, URL, format, date) - or "none found".
S8. City GIS check (at most 4 requests, read-only, NO feature downloads): open https://harta.primariatm.ro and look only at what any visitor's browser loads - the page, its config, its layer list. Does the public layer catalogue contain anything about lighting (iluminat, stalpi, corpuri de iluminat)? Report layer names found and the technology if visible (ArcGIS, GeoServer, QGIS Server ...). The guide says this GIS has no public API, so do not query or scrape feature services - we only want to know what to ask the city for.

If S1 fails, still do S5-S8 and state clearly that complaint data must come from a browser export. Aim for roughly 10-15 minutes.`

const SESIZARI_SCHEMA = {
  type: 'object',
  properties: {
    server_access: { type: 'string', enum: ['works', 'blocked', 'partial'] },
    access_details: { type: 'string' },
    requests_made_to_sesizari: { type: 'number' },
    list_item_shape: { type: 'string' },
    totals: { type: 'string', description: 'total, empty locatie, lighting count, lighting with coordinates, comparison with the team numbers' },
    subcategory_status_table_md: { type: 'string' },
    open_reports_age: { type: 'string' },
    cluster_stats: { type: 'string' },
    model_area_counts_md: { type: 'string' },
    card_shape: { type: 'string' },
    strada_format: { type: 'string' },
    proximity_search: { type: 'string' },
    street_register: { type: 'string' },
    name_matching_verdict: { type: 'string' },
    open_data_lighting: { type: 'string' },
    gis_lighting_layers: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['server_access', 'access_details', 'caveats'],
}

const MAPILLARY_PROMPT = `You are a documentation-research agent. Establish exactly how to export Mapillary street-light detections and image coverage for a city district, from official sources. You have NO Mapillary token, so do not call the authenticated API; a teammate will get a token later and follow your recipe.

${CONTEXT}
Why it matters: Mapillary points will be evidence "a lamp exists here". To stay honest we must separate "street never captured by Mapillary" (no information) from "captured, but no lamp detected" (weak negative evidence), and we must date the evidence, because most local imagery is said to be older than 4 years.

SOURCES: official docs first (https://www.mapillary.com/developer/api-documentation , https://help.mapillary.com , the official blog, github.com/mapillary); forum or third-party posts only as secondary sources and marked as such. Use web search and web fetch (load them through ToolSearch if they are not directly available). The docs page may be rendered client-side; if a fetch comes back empty, try other official pages, the GitHub repos (mapillary-js, mapillary-python-sdk, mapillary_tools) and search results.

QUESTIONS - answer each with: the answer, confidence (high / medium / low), source URL(s), and a short verbatim quote (25 words at most) when available.
M1. Graph API v4: the exact way to fetch point map features of one class inside a bbox - endpoint, parameter names (bbox order, object_values, fields, limit), maximum results per call, pagination or the need to split the bbox, bbox size limits, rate limits.
M2. The exact class identifier for street lights (the team believes object--street-light) and the fields available on a map feature (id, geometry, object_value, object_type, first_seen_at, last_seen_at, aligned_direction, images ...) including the format of the dates.
M3. Vector-tile alternative for map features: tile URL template, zoom levels, layer names, property names - and whether tiles are simpler or more complete than the bbox endpoint for about 4 km2 and for a whole city of about 130 km2.
M4. Image COVERAGE with capture dates for a bbox: (a) vector tiles for images / sequences (URL template, layers, properties such as captured_at, is_pano, sequence_id, the zoom at which the image layer exists); (b) Graph API images search by bbox (fields, limit, bbox limits). We need "was this street captured, and when".
M5. Token: how a developer gets a client access token (steps, cost, how long it takes, token format) and how it is passed (query parameter or header).
M6. Licence and terms for using and redistributing derived data (CC BY-SA 4.0? required attribution wording; rules about caching or storing API results; anything relevant to combining it with OpenStreetMap ODbL data in a public MIT-licensed hackathon repository).
M7. Positional accuracy of map-feature points and known failure modes of the street-light class (false positives such as building lights or traffic signals, duplicates) - only if documented or reported by credible sources.
M8. Any official no-code export (a Download or "Map data" panel in the web app): what format it produces and its limits.
M9. Minimal recipe: the smallest sequence of HTTP calls, as URL templates with placeholders, to export all street-light features and image coverage for bbox west=21.214, south=45.736, east=21.246, north=45.752, including how to split the bbox or enumerate tiles if needed (give the z14 tile x/y range for this bbox). Plain text; do not run it.
Finally, list what is commonly believed but that you could NOT confirm in official documentation. Aim for roughly 10 minutes.`

const MAPILLARY_SCHEMA = {
  type: 'object',
  properties: {
    answers: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' }, answer: { type: 'string' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          sources: { type: 'array', items: { type: 'string' } },
          quote: { type: 'string' },
        },
        required: ['id', 'answer', 'confidence'],
      },
    },
    recipe: { type: 'string' },
    unconfirmed: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['answers', 'recipe', 'unconfirmed', 'caveats'],
}

const POI_PROMPT = `You are a measurement agent. Measure how dense and complete OpenStreetMap venue data is in one district of Timisoara, to decide whether a "lively after 22:00" indicator per street segment is feasible. Analysis only - no product code.

${CONTEXT}
The open design question: should the map also say "lively" (venues open late nearby), possibly by time of day? The completeness of opening_hours in OSM here has never been checked - that is your job.

${rules(SCRATCH + '/poi')}
- Overpass: another agent is using overpass-api.de right now, so try https://overpass.private.coffee/api/interpreter first, then https://overpass.kumi.systems/api/interpreter, then https://overpass-api.de/api/interpreter; on 429/504 wait and retry with backoff. Keep it to a handful of queries.

AREA: bbox south 45.736, west 21.214, north 45.752, east 21.246 (about 4.4 km2). Where cheap, add city-wide numbers for context (area["name"="Timisoara" with diacritics]["boundary"="administrative"]).

TASKS
P1. In the bbox, elements (nodes, ways, relations - use nwr with out center tags) that are venues: amenity in {bar, pub, restaurant, cafe, fast_food, nightclub, biergarten, pharmacy, fuel, cinema, theatre, casino, bank, atm, library, university, college}, any shop=*, tourism in {hotel, hostel, guest_house}. Table by type: count, count with opening_hours, share. Totals. The same two totals city-wide.
P2. Parse opening_hours (pip install a parser into WORKDIR/venv if one installs quickly; otherwise write a rough parser for the common patterns and report the share of strings it cannot parse). Count venues that are: 24/7; open at 22:30 on a Tuesday; open at 22:30 on a Friday; open at 00:30 on Saturday (Friday night). Give counts by type.
P3. Spatial usefulness: late-open venues (Friday 22:30) per km2; and - if cheap, by fetching street ways with geometry once - the share of street length (highway primary..living_street) that has such a venue within 30 m, and within 50 m. Also the share of street length with ANY venue (regardless of hours) within 30 m.
P4. Lighting-related OSM tagging in the bbox and city-wide: count of highway=street_lamp nodes; ways with lit=* by value; lit on highway=bus_stop / railway=tram_stop / public_transport=platform; lit on leisure=park / pitch; any use of light_source, lamp_type, lamp_mount.
P5. Verdict in 3-5 sentences: is OSM venue + opening_hours data here dense and complete enough to drive a per-segment "lively after 22:00" indicator, or only a coarse hint? Name the main bias (for example opening_hours mostly on chains). Aim for roughly 10 minutes.`

const POI_SCHEMA = {
  type: 'object',
  properties: {
    method: { type: 'string' },
    poi_table_md: { type: 'string' },
    opening_hours_stats: { type: 'string' },
    late_open_counts_md: { type: 'string' },
    spatial_usefulness: { type: 'string' },
    lighting_tags: { type: 'string' },
    verdict: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['poi_table_md', 'opening_hours_stats', 'verdict', 'caveats'],
}

phase('Probe')
const [sesizari, mapillary, poi] = await parallel([
  () => agent(SESIZARI_PROMPT, { label: 'sesizari-probe', phase: 'Probe', schema: SESIZARI_SCHEMA, effort: 'high' }),
  () => agent(MAPILLARY_PROMPT, { label: 'mapillary-docs', phase: 'Probe', schema: MAPILLARY_SCHEMA, effort: 'high' }),
  () => agent(POI_PROMPT, { label: 'osm-poi', phase: 'Probe', schema: POI_SCHEMA, effort: 'medium' }),
])
if (!sesizari) log('sesizari-probe returned nothing')
if (!mapillary) log('mapillary-docs returned nothing')
if (!poi) log('osm-poi returned nothing')
return { sesizari, mapillary, poi }
