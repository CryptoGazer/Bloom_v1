"""Build stand-in inputs for handoff/scripts/draft_map.py from files already in the repo,
until Timur's unihack-data folder arrives. Model area only; dryrun.py still needs the real folder.

usage: python3 -I make_fallback_inputs.py <repo root> <out dir>

What is real and what is missing:
- lamps: coordinates and last-seen YEAR of the Mapillary lamps in the model area, taken from the
  LAMPS array embedded in handoff/preview/draft-map.html. mapillary_id and exact dates are lost.
- complaints: all 1550 lighting complaints from handoff/data/sesizari/iluminat_min.geojson.
  street and closed_at are missing (they came from per-complaint cards).
draft_map.py reads only the year of last_seen and does not read street, so the colours it
computes match the original run; only the closing dates in the popups are empty.
"""
import json
import sys
from pathlib import Path

root, out = Path(sys.argv[1]), Path(sys.argv[2])
html = (root / "handoff/preview/draft-map.html").read_text(encoding="utf-8")
marker = "const LAMPS = "
start = html.index(marker) + len(marker)
lamps, _ = json.JSONDecoder().raw_decode(html, start)

lamp_features = [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
     "properties": {"mapillary_id": None, "first_seen": None, "last_seen": str(year), "fallback": True}}
    for lon, lat, year in lamps
]

src = json.loads((root / "handoff/data/sesizari/iluminat_min.geojson").read_text(encoding="utf-8"))
complaint_features = []
for f in src["features"]:
    p = f["properties"]
    complaint_features.append({
        "type": "Feature", "geometry": f["geometry"],
        "properties": {"nr": p["webconInstanceNr"], "created_at": p["createdAt"], "subcategory": p["subcategorie"],
                       "status": p["status"], "street": None, "closed_at": None, "fallback": True},
    })

(out / "geojson").mkdir(parents=True, exist_ok=True)
for name, feats in (("mapillary_street_lights.geojson", lamp_features), ("sesizari_iluminat.geojson", complaint_features)):
    path = out / "geojson" / name
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    print(f"written {path} ({len(feats)} features)")
(out / "README.txt").write_text(
    "Stand-in inputs built by scripts/mac/make_fallback_inputs.py. Replace with Timur's unihack-data folder.\n"
    "Lamps: model area only, last_seen is a year. Complaints: no street, no closed_at.\n", encoding="utf-8")
