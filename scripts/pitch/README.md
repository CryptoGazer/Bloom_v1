# Street-only title and icon

The original `web/pitch/title.html` and Claude's `title-streets.html` remain
available. The new version is `web/pitch/title-streets-v2.html` (`?icon=B` for
the square app-icon composition, `?clean=1` to hide the variant links).

The large lettering contains **only real OSM street/path segments**, including
pedestrian streets and crossings. There is no hidden font outline underneath.
Each letter is connected, and neighbouring letters must have a visible gap.
Street bends, unequal letter sizes, and shifts are deliberately retained.

The script compares the centre and surrounding districts, then exports the
chosen word as GeoJSON with source segment IDs and street names. Every bright
line segment is checked against consecutive points of the source network.

From `Bloom_v1` on Windows:

```powershell
..\.venv\Scripts\python.exe -m pip install -r scripts/pitch/requirements.txt
..\.venv\Scripts\python.exe -m scripts.pitch.street_word search
# Faster, centre-only search:
..\.venv\Scripts\python.exe -m scripts.pitch.street_word search --region centre
# Render an already computed candidate without searching again:
..\.venv\Scripts\python.exe -m scripts.pitch.street_word render --pick 0
```

Outputs:

- `docs/pitch/title-streets.png` — 1920 × 1080;
- `docs/pitch/app-icon-streets.png` — 1024 × 1024;
- `docs/pitch/app-icon-streets-192.png` — small-size check;
- `web/pitch/street-title-v2.svg`, `street-icon-v2.svg` — scalable, offline artwork;
- `web/pitch/bezna-streets-v2.json` — geographical provenance of the lettering.

The map is drawn from the same network as the application and uses its dark
palette. The static title works without external map tiles, fonts, or an API.
Preview: `http://localhost:8001/pitch/title-streets-v2.html`.
