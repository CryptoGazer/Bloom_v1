# bezna — night routes in Timișoara

**RO.** bezna găsește trasee pe jos, cu bicicleta sau cu transportul public în Timișoara și arată ce știm despre iluminatul fiecărei porțiuni de stradă. Proiect UniHack 2026, Green Mobility.

**EN.** bezna plans walking, cycling and walk + public transport routes in Timișoara using street-lighting data. Built for UniHack 2026, Green Mobility.

[Open the app](https://bezna.xyz/m/) · [Desktop map](https://bezna.xyz/)

## Try the project

- **Browser:** open https://bezna.xyz/m/ on a phone or computer. No account, local setup or API keys are needed.
- **Android 8.0 or later:** install an `.apk` attached to a [GitHub release](https://github.com/CryptoGazer/Bloom_v1/releases). If no APK is attached, use the build instructions below. GitHub's source-code ZIP is not an installer.
- **Install the APK:** download it on an Android phone, open the file and complete Android's installation prompts. Allow location for navigation and microphone access for spoken input when requested. Voice output is optional.

The Android app uses the hosted backend at `https://bezna.xyz`; it does not run its own server. Both versions need network access to that backend. iPhone users can use the browser version.

## Features

- **Walking and cycling routes.** Compare the fastest route with a route that favours better-lit streets. When both are offered, the better-lit route is selected regardless of the extra travel time. Routes with practically equivalent lighting can appear as one suggestion.
- **Circular routes.** Walk or cycle through 2–10 points in order and return to the start, or generate a circuit around a place. Gemini can also extract an ordered list of places from a request.
- **Lighting evidence.** Four statuses: confirmed lit, likely lit, no data and reported unlit. Line patterns distinguish them; tapping a street shows sources and dates.
- **Text and voice input.** Gemini parses the request, uses local place-search tools and asks for clarification when needed. The backend validates places and calculates the route. Unrelated requests are rejected.
- **Public transport.** Combine walking with an SMTT service. Show live vehicle positions, reported delays and observation age, with timetable fallback when live data is unavailable. Optional Tiger Data history shows how the line ran on recent days.
- **Navigation.** GPS progress, turns, arrival and warnings before reported unlit stretches. Open places and nearby departures provide additional context along the route.
- **Optional spoken directions.** ElevenLabs provides Romanian and English voices. Voice output is off by default and remembers the user's choice. Browser or Android speech is used if the cloud voice is unavailable.
- **Web and Android.** Romanian and English interfaces on the desktop page, mobile page and Android app. Android packages the same mobile interface and adds native GPS, compass, speech fallback and screen-awake support.

Lighting status describes available observations. A street with no data is not classified as dark, and lighting does not establish that a route is safe.

## Coverage

The bundled dataset is dated **15 November 2026**: **9.61 km² and 9,151 segments**, covering the university campus, centre, selected northeastern neighbourhoods, Circumvalațiunii–Dacia and Mircea cel Bătrân. Coverage is shown on the map.

The backend uses `data/out/city-northwest/` by default. Streets, places and the transit timetable are already included; running the app does not require rebuilding them. `LIGHTMAP_SEGMENTS` can select another `segments.geojson.gz`; its sibling files provide the matching search index, summary and timetable.

Older datasets remain in `data/out/city-expanded/` (7.73 km²) and `data/out/city/` (4.71 km²).

## Local setup

Use Python 3.12. The frontend is plain HTML, CSS and JavaScript; it has no separate build step.

Clone the public repository, or extract a release's source archive:

```bash
git clone https://github.com/CryptoGazer/Bloom_v1.git
cd Bloom_v1
```

To reproduce a specific demo, check out its release tag before building. The APK and source tag should refer to the same version.

### macOS / Linux

Run from the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8001
```

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8001
```

| Address | Page |
|---|---|
| http://localhost:8001/m/ | Mobile interface |
| http://localhost:8001/ | Desktop interface |
| http://localhost:8001/docs | Interactive API documentation |
| http://localhost:8001/api/health | Dataset and feature configuration |

The same FastAPI process serves the pages and API. Manual route entry works without Gemini, ElevenLabs or Tiger Data. Live vehicles and map tiles need network access. Microphone and geolocation require localhost or HTTPS.

## Optional services

Create a `.env` file using [.env.example](.env.example) as a reference. The backend reads it at startup; restart after changing configuration. Keep real keys and database URLs out of Git.

This is only needed when running your own backend. People using the live website or the demo APK do not create `.env` files or supply API keys. For an independent deployment, configure your own provider credentials; `.env.example` contains variable names, not shared credentials. Without these credentials, manual routing still works, cloud request parsing is unavailable, voice uses the device's speech engine and transit history is omitted.

| Service | Variables | Behaviour |
|---|---|---|
| Gemini | `GEMINI_API_KEY`; optional `GEMINI_MODEL` | Enables typed and recorded route requests. Input language can differ from the interface language. |
| ElevenLabs | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID_RO`, `ELEVENLABS_VOICE_ID_EN` | Configures a voice for each interface language. Optional `ELEVENLABS_MODEL` defaults to `eleven_flash_v2_5`. Audio is cached by the backend. |
| Tiger Data | `TIGER_READ_URL`, falling back to `TIGER_DATABASE_URL` | Reads transit history in the background. `TIGER_HISTORY=off` disables it on the site. |

The transit logger runs separately. It keeps a local CSV spool and can write to Tiger Data; the web app uses a read-only connection when configured. See [transit history](docs/transit-history.md), [voice configuration](docs/voice.md) and the [Gemini integration contract](docs/gemini-ui-integration.ru.md).

## Android

Use Android SDK 34, Build Tools 34.0.0 and JDK 17 or 21. Configure `JAVA_HOME` and `ANDROID_HOME` for your machine; do not copy another developer's `local.properties`.

```bash
cd android
./gradlew assembleDebug
```

On Windows, run `.\gradlew.bat assembleDebug` from the same directory. The APK is written to `android/app/build/outputs/apk/debug/app-debug.apk`.

The default backend is `https://bezna.xyz`. Build against another HTTPS backend with `-PbaseUrl=https://your-domain.example`. The HTML and JavaScript are bundled in the APK, so changes to `web/` require rebuilding and reinstalling the app. Routing data comes from the backend. See [Android setup](android/README.md).

### Share an APK for judging

1. Push the final source commit and make the repository publicly accessible. The prepared release branch is `release/voice-guidance`; pushing it does not replace `main`.
2. Build with `assembleDebug`. This produces a signed demo APK that can be installed directly; it is not a Google Play release build.
3. In GitHub **Releases → Draft a new release**, create a tag such as `unihack-2026` and select the branch or commit matching the APK. Attach `app-debug.apk`, optionally renamed to `bezna-unihack-2026.apk`. The APK is a release asset, not a source file to commit.
4. Put the website, public repository and release-page links in the submission. Include a short demo video as a fallback for judges who cannot install an APK or reach the backend from their network.

For a later Google Play release, create a release build signed with your own signing key. Keep that key separate from the source repository. See [Android build types](https://developer.android.com/build/building-cmdline) and [GitHub release instructions](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Loaded segments, dataset date, `ui_version`, Gemini, loop, voice and history availability |
| `GET /api/route` | A → B routes; `from` and `to` are `lat,lon`, `mode` is `walk`, `bike` or `transit` |
| `GET /api/loop` | Closed walk or ride through `points`, or around `center` with `radius_m` |
| `GET /api/geocode` | Local place and address search using `q` |
| `GET /api/segments` | Lighting segments within `bbox=west,south,east,north` |
| `GET /api/summary` | Coverage, sources and lighting statistics |
| `GET /api/transit/live` | Vehicles and source freshness; optional line and trip filters |
| `POST /api/ask` | Parse a text or audio route request |
| `GET /api/speak` | Cached MP3 for a navigation phrase in RO or EN |

Departure times use `Europe/Bucharest`. Full parameters and response schemas are available at `/docs`.

## Deployment updates

FastAPI runs on `127.0.0.1:8001`, behind Caddy:

```caddyfile
bezna.xyz {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8001
}
```

On the existing Vultr installation, after merging and pushing a release to `main`:

```bash
sudo -u bloom git -C /home/bloom/Bloom_v1 pull --ff-only origin main
sudo -u bloom /home/bloom/Bloom_v1/.venv/bin/python -m pip install -r /home/bloom/Bloom_v1/backend/requirements.txt
sudo systemctl restart bloom.service
curl -fsS https://bezna.xyz/api/health
```

Check that `ok` is `true`, the dataset is loaded, and the expected features are enabled. `ui_version` identifies the served frontend; HTML references versioned assets to refresh browser caches. For backend startup errors, use `journalctl -u bloom.service -n 50 --no-pager`. Android updates require a new APK.

## Checks

```bash
.venv/bin/python -m pytest backend/tests -q
node --test web/m/nav.test.cjs web/voice.test.cjs
```

On Windows, use `.\.venv\Scripts\python.exe` for the Python command. JavaScript tests require Node.js. Provider tests use fake responses and do not spend Gemini or ElevenLabs credits. Browser checks and live-provider checks are documented separately in [docs/voice.md](docs/voice.md) and [docs/testing/](docs/testing/).

## Repository

| Path | Contents |
|---|---|
| [backend/](backend/) | FastAPI, lighting rules, routing, place search, Gemini, live transit, history and speech |
| [web/](web/) | Desktop interface and shared modules; [web/m/](web/m/) contains the mobile interface |
| [android/](android/) | Android WebView app and native navigation bridge |
| [config/](config/) | Coverage boundaries |
| [data/out/city-northwest/](data/out/city-northwest/) | Active street network, place index, summary and timetable |
| [scripts/transit/](scripts/transit/) | Transit logger, CSV import and Tiger Data setup |
| [docs/](docs/) | Integration guides, data research and test reports |

## Data and licences

| Source | Used for | Licence / terms |
|---|---|---|
| OpenStreetMap | Streets, `lit` tags, places, opening hours and map tiles | © OpenStreetMap contributors, ODbL 1.0 |
| Mapillary | Street lights detected in street-level images | CC BY-SA 4.0 |
| Primăria Timișoara, Sesizări | Reports of public lighting outages | Report text and photos are not republished; only position, date and state are used |
| SMTT GTFS timetable | Walk + transit routes | Published by SMTT Timișoara (smtt.ro) |
| Primăria Timișoara transit API | Live vehicle positions and reported delays | Public endpoint, queried at most every 15 seconds through one shared cache |
| Street-light icon | Favicon | Magnific / Flaticon, free licence with attribution on the map |

Leaflet: BSD-2-Clause, see [its licence](web/vendor/leaflet/LICENSE). Python dependencies are listed in [backend/requirements.txt](backend/requirements.txt). Fonts: Inter, Inter Tight and JetBrains Mono (SIL Open Font License).

Project code: [MIT](LICENSE). Data retain their respective licences.
