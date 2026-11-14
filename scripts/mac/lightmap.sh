#!/usr/bin/env bash
# Build and view the lighting map and demos on macOS. <data dir> defaults to ./unihack-data (Timur's folder).
#   ./scripts/mac/lightmap.sh setup               create .venv (Python 3.12, osmnx 2.1.1)
#   ./scripts/mac/lightmap.sh draft  [data dir]   lighting map + extra layers + route-demo data -> data/out/
#   ./scripts/mac/lightmap.sh layers [data dir]   only the extra layers (bike lanes, stops, lines, districts)
#   ./scripts/mac/lightmap.sh dryrun [data dir]   whole-city rule dry run -> data/out/dryrun.txt
#   ./scripts/mac/lightmap.sh fallback            stand-in inputs from repo files (if unihack-data is missing)
#   ./scripts/mac/lightmap.sh serve               http://localhost:8000 (pages need http, not file://)
#   ./scripts/mac/lightmap.sh city   [data dir]   WHOLE CITY: lighting status of every segment -> data/out/city/
#   ./scripts/mac/lightmap.sh api                 backend on http://localhost:8001 (API + the demo pages)
#   ./scripts/mac/lightmap.sh test                backend tests
# Another area: LIGHTMAP_BBOX="south,west,north,east" ./scripts/mac/lightmap.sh draft
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
CACHE="$ROOT/data/cache/osmnx"
OUT="$ROOT/data/out"
FALLBACK="$ROOT/data/raw/fallback-data"
DEFAULT_DATA="$ROOT/unihack-data"

need_venv() {
  if [[ ! -x "$PY" ]]; then
    echo "Окружения нет. Сначала: $0 setup" >&2
    exit 1
  fi
}

need_files() {  # need_files <data dir> <file>...
  local dir="$1" missing=0 f
  shift
  for f in "$@"; do
    if [[ ! -f "$dir/geojson/$f" ]]; then
      echo "Нет файла: $dir/geojson/$f" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi
}

cmd="${1:-help}"
data="${2:-$DEFAULT_DATA}"

case "$cmd" in
  setup)
    PYBIN="$(command -v python3.12 || true)"
    if [[ -z "$PYBIN" ]]; then
      echo "Нужен Python 3.12: brew install python@3.12" >&2
      exit 1
    fi
    "$PYBIN" -m venv "$VENV"
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r "$ROOT/backend/requirements.txt"
    "$PY" -c "import osmnx, shapely, numpy, fastapi; print('ok: osmnx', osmnx.__version__, '| shapely', shapely.__version__, '| numpy', numpy.__version__, '| fastapi', fastapi.__version__)"
    ;;

  fallback)
    python3 -I "$ROOT/scripts/mac/make_fallback_inputs.py" "$ROOT" "$FALLBACK"
    echo "Дальше: $0 draft $FALLBACK"
    ;;

  draft)
    need_venv
    need_files "$data" mapillary_street_lights.geojson sesizari_iluminat.geojson
    mkdir -p "$CACHE" "$OUT"
    "$PY" -I "$ROOT/scripts/mac/run_osmnx.py" "$ROOT/handoff/scripts/draft_map.py" "$data" "$CACHE" "$OUT/draft-map.html"
    if [[ -f "$data/geojson/osm_highways.geojson" && -d "$data/gtfs" ]]; then
      "$PY" -I "$ROOT/demo/layers/build_layers.py" "$data" "$OUT/layers"
    else
      echo "Слои пропущены: в $data нет osm_highways.geojson или gtfs/"
    fi
    python3 -I "$ROOT/demo/route/extract_segments.py" "$OUT/draft-map.html" "$OUT/segments_draft.geojson"
    echo "Открыть: $0 serve, затем http://localhost:8000/data/out/draft-map.html и http://localhost:8000/demo/route/"
    ;;

  layers)
    need_venv
    "$PY" -I "$ROOT/demo/layers/build_layers.py" "$data" "$OUT/layers"
    ;;

  dryrun)
    need_venv
    need_files "$data" osm_highways.geojson city_zones.geojson mapillary_street_lights.geojson sesizari_iluminat.geojson
    mkdir -p "$CACHE" "$OUT"
    "$PY" -I "$ROOT/scripts/mac/run_osmnx.py" "$ROOT/handoff/scripts/dryrun.py" "$data" "$CACHE" | tee "$OUT/dryrun.txt"
    ;;

  city)
    need_venv
    need_files "$data" mapillary_street_lights.geojson sesizari_iluminat.geojson
    "$PY" -I "$ROOT/backend/build_city.py" --data "$data"
    echo "Дальше: $0 api"
    ;;

  api)
    need_venv
    if [[ ! -f "$OUT/city/segments.geojson.gz" ]]; then
      echo "Нет данных по городу. Сначала: $0 city" >&2
      exit 1
    fi
    echo "API: http://localhost:${PORT:-8001}/  (запросы руками: http://localhost:${PORT:-8001}/docs)"
    cd "$ROOT" && "$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port "${PORT:-8001}"
    ;;

  test)
    need_venv
    cd "$ROOT" && "$PY" -m pytest backend/tests -q
    ;;

  serve)
    echo "Карта освещённости: http://localhost:8000/data/out/draft-map.html"
    echo "Демо маршрута:      http://localhost:8000/demo/route/"
    cd "$ROOT" && python3 -m http.server 8000
    ;;

  *)
    sed -n '2,13p' "$0"
    ;;
esac
