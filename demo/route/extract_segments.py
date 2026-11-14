"""Export the road segments embedded in a draft lighting map into a GeoJSON file for the route demo.

usage: python3 -I demo/route/extract_segments.py [draft-map.html] [out.geojson]
Defaults: data/out/draft-map.html (rebuilt on this Mac), else handoff/preview/draft-map.html (Timur's);
output data/out/segments_draft.geojson. Re-run after every rebuild of the draft map.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEEP = ("id", "kind", "name", "len", "status", "conf")


def embedded(html, name):
    marker = f"const {name} = "
    start = html.index(marker) + len(marker)
    return json.JSONDecoder().raw_decode(html, start)[0]


def main():
    if len(sys.argv) > 1:
        src = Path(sys.argv[1]).resolve()
    else:
        candidates = [ROOT / "data/out/draft-map.html", ROOT / "handoff/preview/draft-map.html"]
        src = next((p for p in candidates if p.exists()), None)
        if src is None:
            sys.exit("No draft map found. Build one: ./scripts/mac/lightmap.sh draft <data dir>")
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT / "data/out/segments_draft.geojson"

    html = src.read_text(encoding="utf-8")
    data, summary, bbox = embedded(html, "DATA"), embedded(html, "SUMMARY"), embedded(html, "BBOX")
    features = [
        {"type": "Feature", "geometry": f["geometry"], "properties": {k: f["properties"].get(k) for k in KEEP}}
        for f in data["features"]
    ]
    try:
        source = str(src.relative_to(ROOT))
    except ValueError:
        source = str(src)
    meta = {"as_of": summary.get("as_of"), "bbox_swne": bbox, "source": source, "segments": len(features)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "meta": meta, "features": features},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"written {out} ({len(features)} segments, as of {meta['as_of']}, from {source})")


if __name__ == "__main__":
    main()
