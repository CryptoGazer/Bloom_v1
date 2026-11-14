# Lighting Confidence Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Для каждого отрезка пешеходной и велосети модельного участка Тимишоары определить статус освещённости, записать его в `data/out/segments.geojson` и показать на статической карте с объяснением по нажатию.

**Architecture:** Пайплайн на Python: граф osmnx превращается в отрезки с устойчивыми идентификаторами; три источника (тег `lit` из OSM, фонари Mapillary, жалобы Sesizări) привязываются к отрезкам; чистая функция правил выдаёт статус. Результат — два файла в `data/out/`, которые читает статическая страница на Leaflet. Спецификация: `docs/superpowers/specs/2026-11-14-lighting-confidence-map-design.md`.

**Tech Stack:** Python 3.12, osmnx 2.1.1, shapely 2, pyproj, numpy, pytest; Leaflet 1.9.4 (лежит в репозитории), без бэкенда.

## Global Constraints

- Python не ниже 3.12; `osmnx==2.1.1` (от версии зависят идентификаторы отрезков).
- Статусы: `lit_confirmed`, `lit_likely`, `dark_reported`, `unknown`. Виды отрезков: `street`, `sidewalk`, `crossing`, `path`, `service`.
- Параметры берутся из `config/lightmap.json`: `lamp_radius_m` 20, `lamp_coverage_min` 0.5, `complaint_radius_m` 30, `inherit_radius_m` 15, `complaint_cluster_m` 30, `complaint_cluster_days` 14, `open_complaint_fresh_days` 30, `lamps_out_for_dark` 3, `max_unknown_share` 0.3333, `min_lamp_recall` 0.5.
- Участок: `south` 45.7405, `west` 21.2103, `north` 45.7512, `east` 21.2440.
- Расстояния считаются в EPSG:32634.
- Текст и фото жалоб не хранятся и не показываются. Слов «безопасно», «safe», «sigur» в интерфейсе нет.
- `data/raw/` и `data/cache/` в git не попадают; `data/out/` хранится в git.
- Интерфейс: сначала румынский, затем английский. Статусы различаются цветом и рисунком линии.
- Страница открывается только через HTTP-сервер.
- Тесты не ходят в сеть.
- Команды выполняются в Git Bash из корня репозитория `C:/Users/Timur/F1/Unihack`; интерпретатор — `.venv/Scripts/python`.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `pyproject.toml` | Пакет `lightmap`, зависимости, настройки pytest |
| `config/lightmap.json` | Участок, радиусы, пороги |
| `src/lightmap/config.py` | Чтение настроек в `Config` |
| `src/lightmap/geo.py` | Проекция в метры, проверка «точка в участке» |
| `src/lightmap/text.py` | Нормализация названий (`fold`) |
| `src/lightmap/graph.py` | Граф osmnx, кеш, `segment_id`, `kind`, список `Segment` |
| `src/lightmap/evidence.py` | Формат записи свидетельства |
| `src/lightmap/adapters/osm.py` | Вид тега `lit` |
| `src/lightmap/adapters/mapillary.py` | Чтение фонарей |
| `src/lightmap/adapters/sesizari.py` | Чтение жалоб, склейка в события, вид события |
| `src/lightmap/attach.py` | Покрытие фонарями, привязка событий, косвенные признаки |
| `src/lightmap/rules.py` | `classify()` — статус и уверенность |
| `src/lightmap/pipeline.py` | Сборка фактов по отрезкам в результаты |
| `src/lightmap/output.py` | `segments.geojson`, `summary.json`, метрики |
| `src/lightmap/build.py` | Команда `python -m lightmap.build` |
| `src/lightmap/validate.py` | Команда `python -m lightmap.validate`, проверки go/no-go |
| `web/index.html`, `web/app.js`, `web/style.css`, `web/i18n.js` | Карта |
| `web/vendor/leaflet/` | Leaflet 1.9.4 |
| `tests/` | Тесты; `helpers.py` и `builders.py` — заготовки геометрии и данных |

Порядок задач — снизу вверх: каждый файл пишется один раз в окончательном виде. Раннюю «карту на экране» закрывает черновик `handoff/preview/draft-map.html`; он же даёт ожидаемые числа для сверки в задачах 7 и 9.

---

### Task 1: Каркас проекта, настройки, проекция, нормализация текста

**Files:**
- Create: `pyproject.toml`, `config/lightmap.json`, `src/lightmap/__init__.py`, `src/lightmap/config.py`, `src/lightmap/geo.py`, `src/lightmap/text.py`
- Test: `tests/conftest.py`, `tests/test_config.py`, `tests/test_geo.py`, `tests/test_text.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `lightmap.config.Area(name, south, west, north, east)`, `lightmap.config.Config(area, lamp_radius_m, lamp_coverage_min, complaint_radius_m, inherit_radius_m, complaint_cluster_m, complaint_cluster_days, open_complaint_fresh_days, lamps_out_for_dark, max_unknown_share, min_lamp_recall)`, `load_config(path=DEFAULT_CONFIG_PATH) -> Config`
  - `lightmap.geo.to_metric(lon, lat) -> tuple[float, float]`, `line_to_metric(coords) -> LineString`, `in_area(lon, lat, area, pad_m) -> bool`
  - `lightmap.text.fold(text) -> str`
  - фикстура pytest `cfg` с параметрами из спецификации и тестовым участком 45.74–45.75 × 21.21–21.23

- [ ] **Step 1: Создать каркас и окружение**

Файл `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "lightmap"
version = "0.1.0"
description = "Street-lighting confidence map for night-time walking and cycling (UniHack 8, Timisoara)"
requires-python = ">=3.12"
license = {text = "MIT"}
dependencies = ["osmnx==2.1.1", "shapely>=2.0", "pyproj>=3.6", "numpy>=1.26"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
```

Файл `config/lightmap.json`:

```json
{
  "area": {"name": "university-district", "south": 45.7405, "west": 21.2103, "north": 45.7512, "east": 21.2440},
  "lamp_radius_m": 20,
  "lamp_coverage_min": 0.5,
  "complaint_radius_m": 30,
  "inherit_radius_m": 15,
  "complaint_cluster_m": 30,
  "complaint_cluster_days": 14,
  "open_complaint_fresh_days": 30,
  "lamps_out_for_dark": 3,
  "max_unknown_share": 0.3333,
  "min_lamp_recall": 0.5
}
```

Файл `src/lightmap/__init__.py`:

```python
"""Street-lighting confidence map for Timisoara (UniHack 8)."""

__version__ = "0.1.0"
```

Run:

```bash
python -m venv .venv && .venv/Scripts/python -m pip install --quiet --upgrade pip && .venv/Scripts/python -m pip install --quiet -e ".[dev]" && .venv/Scripts/python -c "import osmnx, shapely, pyproj; print(osmnx.__version__, shapely.__version__, pyproj.__version__)"
```

Expected: строка вида `2.1.1 2.x.x 3.x.x`. Установка занимает несколько минут.

- [ ] **Step 2: Написать падающие тесты**

Файл `tests/conftest.py`:

```python
import pytest

from lightmap.config import Area, Config


@pytest.fixture
def cfg() -> Config:
    return Config(
        area=Area(name="test", south=45.7400, west=21.2100, north=45.7500, east=21.2300),
        lamp_radius_m=20,
        lamp_coverage_min=0.5,
        complaint_radius_m=30,
        inherit_radius_m=15,
        complaint_cluster_m=30,
        complaint_cluster_days=14,
        open_complaint_fresh_days=30,
        lamps_out_for_dark=3,
        max_unknown_share=0.3333,
        min_lamp_recall=0.5,
    )
```

Файл `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from lightmap.config import load_config


def test_load_project_config():
    cfg = load_config(Path("config/lightmap.json"))
    assert cfg.area.name == "university-district"
    assert (cfg.area.south, cfg.area.west, cfg.area.north, cfg.area.east) == (45.7405, 21.2103, 45.7512, 21.2440)
    assert cfg.lamp_radius_m == 20 and cfg.lamp_coverage_min == 0.5
    assert cfg.complaint_radius_m == 30 and cfg.inherit_radius_m == 15
    assert cfg.lamps_out_for_dark == 3 and cfg.open_complaint_fresh_days == 30


def test_unknown_key_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"area": {"name": "x", "south": 1, "west": 2, "north": 3, "east": 4}, "surprise": 1}', encoding="utf-8")
    with pytest.raises(TypeError):
        load_config(bad)
```

Файл `tests/test_geo.py`:

```python
import math

from lightmap.config import Area
from lightmap.geo import in_area, line_to_metric, to_metric


def test_to_metric_distances_are_metres():
    a = to_metric(21.2200, 45.7450)
    b = to_metric(21.2210, 45.7450)
    assert 77.0 < math.dist(a, b) < 78.5


def test_line_to_metric_length():
    line = line_to_metric([(21.2200, 45.7450), (21.2200, 45.7460)])
    assert 110.0 < line.length < 112.5


def test_in_area_with_pad():
    area = Area("t", 45.74, 21.21, 45.75, 21.23)
    assert in_area(21.22, 45.745, area, 0)
    assert not in_area(21.2305, 45.745, area, 0)
    assert in_area(21.2303, 45.745, area, 30)
    assert not in_area(21.2305, 45.745, area, 30)
```

Файл `tests/test_text.py`:

```python
from lightmap.text import fold


def test_fold_strips_diacritics_case_dots_and_spaces():
    assert fold("Nu funcționează iluminatul public în zonă") == "nu functioneaza iluminatul public in zona"
    assert fold("Aleea  F. C. Ripensia") == fold("aleea f c ripensia") == "aleea f c ripensia"
    assert fold(None) == ""
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest -q`
Expected: ошибки сбора `ModuleNotFoundError: No module named 'lightmap.config'`.

- [ ] **Step 4: Написать реализацию**

Файл `src/lightmap/config.py`:

```python
"""Area and thresholds, read from config/lightmap.json."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config/lightmap.json")


@dataclass(frozen=True)
class Area:
    name: str
    south: float
    west: float
    north: float
    east: float


@dataclass(frozen=True)
class Config:
    area: Area
    lamp_radius_m: float
    lamp_coverage_min: float
    complaint_radius_m: float
    inherit_radius_m: float
    complaint_cluster_m: float
    complaint_cluster_days: int
    open_complaint_fresh_days: int
    lamps_out_for_dark: int
    max_unknown_share: float
    min_lamp_recall: float


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    area = Area(**raw.pop("area"))
    return Config(area=area, **raw)
```

Файл `src/lightmap/geo.py`:

```python
"""Metric projection (EPSG:32634) and the area test for input points."""
from __future__ import annotations

import math

import pyproj
from shapely.geometry import LineString

from lightmap.config import Area

_TO_METRIC = pyproj.Transformer.from_crs(4326, 32634, always_xy=True)


def to_metric(lon: float, lat: float) -> tuple[float, float]:
    x, y = _TO_METRIC.transform(lon, lat)
    return (x, y)


def line_to_metric(coords: list[tuple[float, float]]) -> LineString:
    xs, ys = _TO_METRIC.transform([c[0] for c in coords], [c[1] for c in coords])
    return LineString(list(zip(xs, ys)))


def in_area(lon: float, lat: float, area: Area, pad_m: float) -> bool:
    """True if the point is inside the area grown by pad_m metres on every side."""
    dlat = pad_m / 111_320.0
    dlon = pad_m / (111_320.0 * math.cos(math.radians(lat)))
    return (area.west - dlon <= lon <= area.east + dlon) and (area.south - dlat <= lat <= area.north + dlat)
```

Файл `src/lightmap/text.py`:

```python
"""Name normalisation shared by street matching and complaint sub-categories."""
from __future__ import annotations

import unicodedata


def fold(text: str | None) -> str:
    """Lower-case, strip diacritics and dots, collapse whitespace."""
    decomposed = unicodedata.normalize("NFD", text or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().replace(".", " ").split())
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml config/lightmap.json src/lightmap/__init__.py src/lightmap/config.py src/lightmap/geo.py src/lightmap/text.py tests/conftest.py tests/test_config.py tests/test_geo.py tests/test_text.py
git commit -m "feat: project skeleton, config, metric projection, name folding"
```

---

### Task 2: Граф и отрезки

**Files:**
- Create: `src/lightmap/graph.py`
- Test: `tests/helpers.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: `lightmap.config.Area`, `Config`; `lightmap.geo.line_to_metric`.
- Produces:
  - `lightmap.graph.Segment(segment_id: str, kind: str, name: str | None, osm_way_ids: list[int], lit_values: list[str], coords: list[tuple[float, float]], line: LineString)` со свойством `length_m`; `coords` — долгота и широта, `line` — в метрах
  - `as_list(value) -> list`, `segment_id(u, v, key) -> str`, `segment_kind(highway, footway) -> str`
  - `to_segment_graph(G: nx.MultiDiGraph) -> nx.MultiGraph` — рёбра получают атрибуты `segment_id` и `kind`
  - `segments_from_graph(Gu) -> list[Segment]`, отсортированы по `segment_id`
  - `download_graph(area) -> nx.MultiDiGraph`, `load_graph(cfg, cache_path=DEFAULT_CACHE_PATH) -> nx.MultiGraph`
  - тестовые заготовки `helpers.xy(dx_m, dy_m)`, `helpers.ll(dx_m, dy_m)`, `helpers.make_segment(segment_id, kind, points_m, name=None, lit=None)`, `helpers.make_graph()`

- [ ] **Step 1: Написать заготовки и падающие тесты**

Файл `tests/helpers.py`:

```python
"""Test helpers: a tiny hand-built OSM graph and segments placed by metric offsets."""
from __future__ import annotations

import networkx as nx
import pyproj
from shapely.geometry import LineString

from lightmap.geo import line_to_metric, to_metric
from lightmap.graph import Segment

_TO_LONLAT = pyproj.Transformer.from_crs(32634, 4326, always_xy=True)
ORIGIN_X, ORIGIN_Y = to_metric(21.2200, 45.7450)


def xy(dx_m: float, dy_m: float) -> tuple[float, float]:
    """Metric coordinates of the point dx_m east and dy_m north of the test origin."""
    return (ORIGIN_X + dx_m, ORIGIN_Y + dy_m)


def ll(dx_m: float, dy_m: float) -> tuple[float, float]:
    """Lon/lat of the same point."""
    lon, lat = _TO_LONLAT.transform(*xy(dx_m, dy_m))
    return (lon, lat)


def make_segment(segment_id: str, kind: str, points_m: list[tuple[float, float]], name: str | None = None, lit: list[str] | None = None) -> Segment:
    coords = [ll(x, y) for x, y in points_m]
    return Segment(segment_id=segment_id, kind=kind, name=name, osm_way_ids=[1], lit_values=lit or [], coords=coords, line=line_to_metric(coords))


def make_graph() -> nx.MultiDiGraph:
    """Two-way street 1-2 (way 100, lit=yes), one-way merged street 2-3 (ways 200+201), sidewalk 1-2 (way 300)."""
    G = nx.MultiDiGraph(crs="epsg:4326")
    G.add_node(1, x=21.2200, y=45.7450)
    G.add_node(2, x=21.2210, y=45.7450)
    G.add_node(3, x=21.2210, y=45.7460)
    G.add_edge(1, 2, osmid=100, highway="residential", name="Strada A", lit="yes", length=77.8, oneway=False, reversed=False)
    G.add_edge(2, 1, osmid=100, highway="residential", name="Strada A", lit="yes", length=77.8, oneway=False, reversed=True)
    G.add_edge(2, 3, osmid=[200, 201], highway=["tertiary", "residential"], name=["B", "C"], lit=["yes", "no"], length=111.0, oneway=True, reversed=False)
    side = [(21.2200, 45.7450), (21.2205, 45.7451), (21.2210, 45.7450)]
    G.add_edge(1, 2, osmid=300, highway="footway", footway="sidewalk", length=80.0, oneway=False, reversed=False, geometry=LineString(side))
    G.add_edge(2, 1, osmid=300, highway="footway", footway="sidewalk", length=80.0, oneway=False, reversed=True, geometry=LineString(side[::-1]))
    return G
```

Файл `tests/test_graph.py`:

```python
import pytest

from helpers import make_graph
from lightmap import graph
from lightmap.graph import load_graph, segment_id, segment_kind, segments_from_graph, to_segment_graph


def test_segment_id_orders_nodes():
    assert segment_id(2, 1, 0) == "1-2-0" == segment_id(1, 2, 0)


@pytest.mark.parametrize(
    "highway, footway, expected",
    [
        ("residential", None, "street"),
        (["tertiary", "footway"], None, "street"),
        ("primary_link", None, "street"),
        ("footway", "sidewalk", "sidewalk"),
        ("footway", "crossing", "crossing"),
        ("footway", None, "path"),
        ("cycleway", None, "path"),
        ("steps", None, "path"),
        ("service", None, "service"),
        (None, None, "service"),
    ],
)
def test_segment_kind(highway, footway, expected):
    assert segment_kind(highway, footway) == expected


def test_segments_from_hand_built_graph():
    by_id = {s.segment_id: s for s in segments_from_graph(to_segment_graph(make_graph()))}
    assert set(by_id) == {"1-2-0", "1-2-1", "2-3-0"}
    street, sidewalk, merged = by_id["1-2-0"], by_id["1-2-1"], by_id["2-3-0"]
    assert (street.kind, street.name, street.lit_values, street.osm_way_ids) == ("street", "Strada A", ["yes"], [100])
    assert (sidewalk.kind, sidewalk.name, sidewalk.osm_way_ids) == ("sidewalk", None, [300])
    assert (merged.kind, merged.name, merged.osm_way_ids, merged.lit_values) == ("street", "B", [200, 201], ["yes", "no"])
    assert 77.0 < street.length_m < 78.5


def test_ids_survive_the_graphml_cache(tmp_path, cfg, monkeypatch):
    cache = tmp_path / "cache" / "graph.graphml"
    monkeypatch.setattr(graph, "download_graph", lambda area: make_graph())
    first = segments_from_graph(load_graph(cfg, cache))
    assert cache.exists()

    def boom(area):
        raise AssertionError("must not download when the cache exists")

    monkeypatch.setattr(graph, "download_graph", boom)
    second = segments_from_graph(load_graph(cfg, cache))
    summary = lambda segs: [(s.segment_id, s.kind, s.osm_way_ids, s.lit_values) for s in segs]
    assert summary(first) == summary(second)


def test_failed_download_leaves_no_cache(tmp_path, cfg, monkeypatch):
    cache = tmp_path / "graph.graphml"

    def boom(area):
        raise ConnectionError("no network")

    monkeypatch.setattr(graph, "download_graph", boom)
    with pytest.raises(ConnectionError):
        load_graph(cfg, cache)
    assert not cache.exists()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_graph.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'lightmap.graph'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/graph.py`:

```python
"""Street graph of the area: download once, cache, and turn edges into segments.

Subproject 2 must obtain the graph through load_graph(): edge keys of the undirected
graph are part of segment_id and are only reproducible for the same cache file and
the pinned osmnx version.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString

from lightmap.config import Area, Config
from lightmap.geo import line_to_metric

DEFAULT_CACHE_PATH = Path("data/cache/graph.graphml")
EXTRA_WAY_TAGS = ["lit", "footway", "foot", "bicycle", "cycleway", "sidewalk", "surface"]
_STREET_BASE = ("trunk", "primary", "secondary", "tertiary")
STREET_HIGHWAYS = frozenset(_STREET_BASE) | frozenset(f"{h}_link" for h in _STREET_BASE) | frozenset({"unclassified", "residential", "living_street"})
PATH_HIGHWAYS = frozenset({"footway", "path", "pedestrian", "cycleway", "steps", "track"})


def as_list(value) -> list:
    """Edge attributes are scalars, or lists after osmnx merged several ways."""
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def segment_id(u: int, v: int, key: int) -> str:
    a, b = (u, v) if u < v else (v, u)
    return f"{a}-{b}-{key}"


def segment_kind(highway, footway) -> str:
    hw, fw = set(as_list(highway)), set(as_list(footway))
    if hw & STREET_HIGHWAYS:
        return "street"
    if "footway" in hw and "sidewalk" in fw:
        return "sidewalk"
    if "footway" in hw and "crossing" in fw:
        return "crossing"
    if hw & PATH_HIGHWAYS:
        return "path"
    return "service"


@dataclass
class Segment:
    segment_id: str
    kind: str
    name: str | None
    osm_way_ids: list[int]
    lit_values: list[str]
    coords: list[tuple[float, float]]  # lon, lat
    line: LineString  # EPSG:32634

    @property
    def length_m(self) -> float:
        return self.line.length


def to_segment_graph(G: nx.MultiDiGraph) -> nx.MultiGraph:
    Gu = ox.convert.to_undirected(G)
    for u, v, key, data in Gu.edges(keys=True, data=True):
        data["segment_id"] = segment_id(u, v, key)
        data["kind"] = segment_kind(data.get("highway"), data.get("footway"))
    return Gu


def segments_from_graph(Gu: nx.MultiGraph) -> list[Segment]:
    segments = []
    for _, _, data in Gu.edges(data=True):
        coords = [(float(x), float(y)) for x, y in data["geometry"].coords]
        names = [n for n in as_list(data.get("name")) if isinstance(n, str)]
        segments.append(
            Segment(
                segment_id=data["segment_id"],
                kind=data["kind"],
                name=names[0] if names else None,
                osm_way_ids=[int(i) for i in as_list(data.get("osmid"))],
                lit_values=[str(x) for x in as_list(data.get("lit"))],
                coords=coords,
                line=line_to_metric(coords),
            )
        )
    segments.sort(key=lambda s: s.segment_id)
    return segments


def download_graph(area: Area) -> nx.MultiDiGraph:
    ox.settings.useful_tags_way = list(dict.fromkeys(list(ox.settings.useful_tags_way) + EXTRA_WAY_TAGS))
    return ox.graph_from_bbox(
        bbox=(area.west, area.south, area.east, area.north),
        network_type="all_public",
        simplify=True,
        retain_all=True,
        truncate_by_edge=True,
    )


def load_graph(cfg: Config, cache_path: Path = DEFAULT_CACHE_PATH) -> nx.MultiGraph:
    """Undirected graph whose edges carry segment_id and kind. Downloads only when the cache is missing."""
    cache_path = Path(cache_path)
    if not cache_path.exists():
        downloaded = download_graph(cfg.area)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        ox.save_graphml(downloaded, cache_path)
    return to_segment_graph(ox.load_graphml(cache_path))
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `20 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/lightmap/graph.py tests/helpers.py tests/test_graph.py
git commit -m "feat: street graph cache and segments with stable ids"
```

---

### Task 3: Вид тега `lit` и правила статуса

**Files:**
- Create: `src/lightmap/adapters/__init__.py`, `src/lightmap/adapters/osm.py`, `src/lightmap/rules.py`
- Test: `tests/test_osm_adapter.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `lightmap.adapters.osm.lit_kind(values: list[str]) -> str | None` — `"lit_yes"`, `"lit_no"`, `"lit_mixed"` или `None`; `other_values(values) -> list[str]`
  - `lightmap.rules.STATUSES = ("lit_confirmed", "lit_likely", "dark_reported", "unknown")`
  - `lightmap.rules.Verdict(status: str, confidence: int, families: tuple[str, ...])`
  - `fresh_lamps_out(events, fresh_days) -> int`, `dark_by_complaints(events, fresh_days, lamps_out_for_dark) -> bool`
  - `classify(osm_kind, lamp_coverage, events, indirect, inherited_dark, *, coverage_min, fresh_days, lamps_out_for_dark) -> Verdict`, где `events` — список пар `(kind, age_days)`

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/test_osm_adapter.py`:

```python
import pytest

from lightmap.adapters.osm import lit_kind, other_values


@pytest.mark.parametrize(
    "values, expected",
    [
        ([], None),
        (["yes"], "lit_yes"),
        (["24/7"], "lit_yes"),
        (["no"], "lit_no"),
        (["yes", "no"], "lit_mixed"),
        (["disused"], None),
        (["yes", "disused"], "lit_yes"),
    ],
)
def test_lit_kind(values, expected):
    assert lit_kind(values) == expected


def test_other_values_are_reported():
    assert other_values(["yes", "disused", "no"]) == ["disused"]
```

Файл `tests/test_rules.py`:

```python
import pytest

from lightmap.rules import classify, dark_by_complaints

PARAMS = dict(coverage_min=0.5, fresh_days=30, lamps_out_for_dark=3)

CASES = [
    # name, osm_kind, lamp_coverage, events, indirect, inherited_dark, status, confidence
    ("no evidence", None, 0.0, [], [], False, "unknown", 0),
    ("osm tag only", "lit_yes", 0.0, [], [], False, "lit_confirmed", 1),
    ("lamps only", None, 0.6, [], [], False, "lit_confirmed", 1),
    ("lamps exactly at the threshold", None, 0.5, [], [], False, "lit_confirmed", 1),
    ("complaint only", None, 0.0, [("fixed", None)], [], False, "lit_likely", 1),
    ("two families", "lit_yes", 0.8, [], [], False, "lit_confirmed", 2),
    ("three families", "lit_yes", 0.8, [("fixed", None)], [], False, "lit_confirmed", 3),
    ("lit_no beats lamps", "lit_no", 0.9, [], [], False, "dark_reported", 1),
    ("mixed tag is ignored", "lit_mixed", 0.0, [], [], False, "unknown", 0),
    ("fresh area outage", "lit_yes", 0.9, [("open_area_outage", 30)], [], False, "dark_reported", 3),
    ("stale area outage", "lit_yes", 0.0, [("open_area_outage", 31)], [], False, "lit_confirmed", 2),
    ("one fresh lamp out caps at likely", "lit_yes", 0.9, [("open_lamp_out", 5)], [], False, "lit_likely", 3),
    ("two fresh lamps out are not dark", None, 0.9, [("open_lamp_out", 5), ("open_lamp_out", 9)], [], False, "lit_likely", 2),
    ("three fresh lamps out", "lit_yes", 0.9, [("open_lamp_out", 1), ("open_lamp_out", 2), ("open_lamp_out", 3)], [], False, "dark_reported", 3),
    ("stale lamp out does not cap", "lit_yes", 0.0, [("open_lamp_out", 45)], [], False, "lit_confirmed", 2),
    ("declined only", None, 0.0, [("declined", None)], [], False, "unknown", 0),
    ("indirect only", None, 0.2, [], ["partial_lamps"], False, "lit_likely", 0),
    ("inherited dark", None, 0.9, [], ["near_lit_street"], True, "dark_reported", 1),
]


@pytest.mark.parametrize("name, osm_kind, coverage, events, indirect, inherited, status, confidence", CASES, ids=[c[0] for c in CASES])
def test_classify(name, osm_kind, coverage, events, indirect, inherited, status, confidence):
    verdict = classify(osm_kind, coverage, events, indirect, inherited, **PARAMS)
    assert (verdict.status, verdict.confidence) == (status, confidence)


def test_families_keep_a_fixed_order():
    verdict = classify("lit_yes", 0.9, [("fixed", None)], [], False, **PARAMS)
    assert verdict.families == ("osm", "mapillary", "sesizari")


def test_dark_by_complaints():
    assert dark_by_complaints([("open_area_outage", 3)], 30, 3)
    assert not dark_by_complaints([("open_area_outage", 40), ("open_lamp_out", 2), ("open_lamp_out", 2)], 30, 3)
    assert dark_by_complaints([("open_lamp_out", 1)] * 3, 30, 3)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_osm_adapter.py tests/test_rules.py -q`
Expected: ошибки сбора `ModuleNotFoundError: No module named 'lightmap.adapters'` и `No module named 'lightmap.rules'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/adapters/__init__.py`:

```python
"""One module per evidence source."""
```

Файл `src/lightmap/adapters/osm.py`:

```python
"""OSM source: the lit=* tag carried by the segment's own ways."""
from __future__ import annotations

YES_VALUES = frozenset({"yes", "24/7", "automatic", "limited", "interval", "sunset-sunrise", "dusk-dawn"})
NO_VALUE = "no"


def lit_kind(values: list[str]) -> str | None:
    present = set(values)
    has_yes, has_no = bool(present & YES_VALUES), NO_VALUE in present
    if has_yes and has_no:
        return "lit_mixed"
    if has_yes:
        return "lit_yes"
    if has_no:
        return "lit_no"
    return None


def other_values(values: list[str]) -> list[str]:
    """Values that are neither yes-like nor 'no'; they are ignored and counted in the summary."""
    return [v for v in values if v not in YES_VALUES and v != NO_VALUE]
```

Файл `src/lightmap/rules.py`:

```python
"""Status rules (spec section 7). Pure functions: no I/O, no geometry."""
from __future__ import annotations

from dataclasses import dataclass

STATUSES = ("lit_confirmed", "lit_likely", "dark_reported", "unknown")
DIRECT_FAMILIES = frozenset({"osm", "mapillary"})

EventFact = tuple[str, int | None]  # (event kind, age in days for open events)


@dataclass(frozen=True)
class Verdict:
    status: str
    confidence: int
    families: tuple[str, ...]


def _fresh(age: int | None, fresh_days: int) -> bool:
    return age is not None and age <= fresh_days


def fresh_lamps_out(events: list[EventFact], fresh_days: int) -> int:
    return sum(1 for kind, age in events if kind == "open_lamp_out" and _fresh(age, fresh_days))


def dark_by_complaints(events: list[EventFact], fresh_days: int, lamps_out_for_dark: int) -> bool:
    fresh_area = any(kind == "open_area_outage" and _fresh(age, fresh_days) for kind, age in events)
    return fresh_area or fresh_lamps_out(events, fresh_days) >= lamps_out_for_dark


def classify(
    osm_kind: str | None,
    lamp_coverage: float,
    events: list[EventFact],
    indirect: list[str],
    inherited_dark: bool,
    *,
    coverage_min: float,
    fresh_days: int,
    lamps_out_for_dark: int,
) -> Verdict:
    families = []
    if osm_kind == "lit_yes":
        families.append("osm")
    if lamp_coverage >= coverage_min:
        families.append("mapillary")
    if any(kind != "declined" for kind, _ in events):
        families.append("sesizari")

    if osm_kind == "lit_no" or inherited_dark or dark_by_complaints(events, fresh_days, lamps_out_for_dark):
        status = "dark_reported"
    elif DIRECT_FAMILIES & set(families) and fresh_lamps_out(events, fresh_days) == 0:
        status = "lit_confirmed"
    elif families or indirect:
        status = "lit_likely"
    else:
        status = "unknown"
    return Verdict(status=status, confidence=len(families), families=tuple(families))
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `48 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/lightmap/adapters/__init__.py src/lightmap/adapters/osm.py src/lightmap/rules.py tests/test_osm_adapter.py tests/test_rules.py
git commit -m "feat: lit tag kinds and status rules"
```

---

### Task 4: Адаптеры Mapillary и Sesizări

**Files:**
- Create: `src/lightmap/evidence.py`, `src/lightmap/adapters/mapillary.py`, `src/lightmap/adapters/sesizari.py`
- Test: `tests/test_mapillary_adapter.py`, `tests/test_sesizari.py`

**Interfaces:**
- Consumes: `lightmap.config.Area`, `Config`; `lightmap.geo.in_area`, `to_metric`; `lightmap.text.fold`; `helpers.ll`.
- Produces:
  - `lightmap.evidence.Evidence(source: str, kind: str, ref: str, lon: float | None = None, lat: float | None = None, observed_at: date | None = None, extra: dict = {})`
  - `lightmap.adapters.mapillary.read_lamps(path, area, pad_m) -> list[Evidence] | None` — `None`, если файла нет
  - `lightmap.adapters.sesizari.Complaint(nr, created: date, status, subcategory, street, closed_at: date | None, lon, lat)`
  - `lightmap.adapters.sesizari.Event(kind: str, complaints: list[Complaint], age_days: int | None = None, closed_at: date | None = None)` со свойством `first`
  - `read_complaints(path, area, pad_m) -> list[Complaint] | None`, `cluster(complaints, max_m, max_days) -> list[list[Complaint]]`, `make_event(group, as_of) -> Event`, `build_events(complaints, cfg, as_of) -> list[Event]`, `count_unrecognised(complaints) -> int`
  - виды событий: `declined`, `open_area_outage`, `open_lamp_out`, `open_other`, `fixed`

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/test_mapillary_adapter.py`:

```python
import json
from datetime import date

from helpers import ll
from lightmap.adapters.mapillary import read_lamps


def test_read_lamps_keeps_points_in_area(tmp_path, cfg):
    lon, lat = ll(0, 0)

    def feature(x, y, mapillary_id, last_seen):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]}, "properties": {"mapillary_id": mapillary_id, "first_seen": "2018-05-02", "last_seen": last_seen}}

    path = tmp_path / "lamps.geojson"
    features = [feature(lon, lat, 11, "2026-03-11"), feature(21.5, 45.9, 12, "2024-01-01"), feature(lon, lat, 13, None)]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    lamps = read_lamps(path, cfg.area, 30)

    assert [(l.source, l.kind, l.ref) for l in lamps] == [("mapillary", "lamp", "11"), ("mapillary", "lamp", "13")]
    assert lamps[0].observed_at == date(2026, 3, 11) and lamps[1].observed_at is None
    assert (lamps[0].lon, lamps[0].lat) == (lon, lat)


def test_missing_file_means_source_not_connected(tmp_path, cfg):
    assert read_lamps(tmp_path / "nope.geojson", cfg.area, 30) is None
```

Файл `tests/test_sesizari.py`:

```python
import json
from datetime import date

import pytest

from helpers import ll
from lightmap.adapters.sesizari import Complaint, build_events, cluster, count_unrecognised, make_event, read_complaints

AS_OF = date(2026, 11, 14)
AREA_OUT = "Nu funcționează iluminatul public în zonă"


def complaint(nr, created, status="Finalizata", sub="Bec nefuncțional", dx=0.0, dy=0.0, closed=None, street=None):
    lon, lat = ll(dx, dy)
    return Complaint(nr=nr, created=date.fromisoformat(created), status=status, subcategory=sub, street=street, closed_at=date.fromisoformat(closed) if closed else None, lon=lon, lat=lat)


def test_read_complaints_parses_and_clips(tmp_path, cfg):
    inside = ll(0, 0)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": list(inside)},
            "properties": {"nr": "SZN2026-000001", "created_at": "2026-10-11T18:32:05.1+00:00", "subcategory": " Bec nefuncțional ", "status": "Finalizata ", "street": "Strada Cluj", "closed_at": "2026-10-13T06:05:00.123456+00:00"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [21.5, 45.9]},
            "properties": {"nr": "SZN2026-000002", "created_at": "2026-10-11T18:32:05+00:00", "subcategory": "Bec nefuncțional", "status": "In lucru", "street": None, "closed_at": None},
        },
    ]
    path = tmp_path / "sesizari.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")

    got = read_complaints(path, cfg.area, 30)

    assert [c.nr for c in got] == ["SZN2026-000001"]
    assert (got[0].status, got[0].subcategory, got[0].street) == ("Finalizata", "Bec nefuncțional", "Strada Cluj")
    assert got[0].created == date(2026, 10, 11) and got[0].closed_at == date(2026, 10, 13)


def test_missing_file_means_source_not_connected(tmp_path, cfg):
    assert read_complaints(tmp_path / "nope.geojson", cfg.area, 30) is None


def test_cluster_30m_14days_from_the_first_report():
    a = complaint("A", "2026-10-01")
    b = complaint("B", "2026-10-05", dx=20)
    c = complaint("C", "2026-10-15", dx=-25)
    d = complaint("D", "2026-10-16", dx=5)
    e = complaint("E", "2026-10-02", dx=40)
    groups = cluster([d, c, e, b, a], max_m=30, max_days=14)
    assert [[x.nr for x in g] for g in groups] == [["A", "B", "C"], ["E"], ["D"]]


@pytest.mark.parametrize(
    "members, kind, age",
    [
        ([("Declinata competenta", "Bec nefuncțional", "2026-11-01")], "declined", None),
        ([("Finalizata", "Bec nefuncțional", "2026-11-01")], "fixed", None),
        ([("In lucru", AREA_OUT, "2026-11-10")], "open_area_outage", 4),
        ([("In lucru", "Bec nefuncțional", "2026-11-01"), ("Inregistrata", "Aparat de iluminat nefuncțional", "2026-11-12")], "open_lamp_out", 2),
        ([("In lucru", "Probleme referitoare la cabluri", "2026-10-15")], "open_other", 30),
        ([("Finalizata", AREA_OUT, "2026-10-01"), ("In lucru", "Bec nefuncțional", "2026-10-05")], "open_lamp_out", 40),
        ([("", "", "2026-11-13")], "open_other", 1),
    ],
)
def test_make_event_kind_and_age(members, kind, age):
    group = [complaint(str(i), created, status=status, sub=sub) for i, (status, sub, created) in enumerate(members)]
    event = make_event(group, AS_OF)
    assert (event.kind, event.age_days) == (kind, age)


def test_fixed_event_keeps_the_latest_close_date():
    event = make_event([complaint("A", "2026-10-01", closed="2026-10-03"), complaint("B", "2026-10-02", closed="2026-10-09")], AS_OF)
    assert event.kind == "fixed" and event.closed_at == date(2026, 10, 9) and event.first.nr == "A"


def test_build_events_uses_the_config(cfg):
    events = build_events([complaint("A", "2026-10-01"), complaint("B", "2026-10-03", dx=10)], cfg, AS_OF)
    assert len(events) == 1 and len(events[0].complaints) == 2


def test_count_unrecognised():
    complaints = [complaint("A", "2026-10-01"), complaint("B", "2026-10-01", status="Ceva nou"), complaint("C", "2026-10-01", sub="Altceva")]
    assert count_unrecognised(complaints) == 2
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_mapillary_adapter.py tests/test_sesizari.py -q`
Expected: ошибки сбора `ModuleNotFoundError: No module named 'lightmap.adapters.mapillary'` и `No module named 'lightmap.adapters.sesizari'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/evidence.py`:

```python
"""Common record every source adapter returns (spec section 5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Evidence:
    source: str
    kind: str
    ref: str
    lon: float | None = None
    lat: float | None = None
    observed_at: date | None = None
    extra: dict = field(default_factory=dict, compare=False)
```

Файл `src/lightmap/adapters/mapillary.py`:

```python
"""Mapillary source: street lights detected on street-level imagery."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lightmap.config import Area
from lightmap.evidence import Evidence
from lightmap.geo import in_area


def read_lamps(path: Path, area: Area, pad_m: float) -> list[Evidence] | None:
    """Lamp points inside the area grown by pad_m; None if the export file is absent."""
    path = Path(path)
    if not path.exists():
        return None
    lamps = []
    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        lon, lat = feature["geometry"]["coordinates"][:2]
        if not in_area(lon, lat, area, pad_m):
            continue
        props = feature["properties"]
        last_seen = props.get("last_seen")
        lamps.append(
            Evidence(
                source="mapillary",
                kind="lamp",
                ref=str(props["mapillary_id"]),
                lon=lon,
                lat=lat,
                observed_at=date.fromisoformat(last_seen[:10]) if last_seen else None,
                extra={"first_seen": props.get("first_seen")},
            )
        )
    return lamps
```

Файл `src/lightmap/adapters/sesizari.py`:

```python
"""Sesizari source: residents' lighting complaints, merged into events.

Only coordinates, sub-category, status, dates, street and number are read.
Complaint text and photos are never loaded.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from lightmap.config import Area, Config
from lightmap.geo import in_area, to_metric
from lightmap.text import fold

CLOSED_STATUSES = frozenset({"Finalizata", "Rezolvata"})
OPEN_STATUSES = frozenset({"In lucru", "Inregistrata", "Asteapta clarificari"})
AREA_SUBCATEGORY = fold("Nu funcționează iluminatul public în zonă")
LAMP_SUBCATEGORIES = frozenset({fold("Bec nefuncțional"), fold("Aparat de iluminat nefuncțional")})
OTHER_SUBCATEGORIES = frozenset(
    {
        fold("Probleme privind stâlpii de iluminat"),
        fold("Probleme referitoare la cabluri"),
        fold("Funcționare a ilumintalului public stradal pe timp de zi"),
    }
)


@dataclass(frozen=True)
class Complaint:
    nr: str
    created: date
    status: str
    subcategory: str
    street: str | None
    closed_at: date | None
    lon: float
    lat: float


@dataclass
class Event:
    kind: str
    complaints: list[Complaint]
    age_days: int | None = None
    closed_at: date | None = None

    @property
    def first(self) -> Complaint:
        return self.complaints[0]


def _day(value: str | None) -> date | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date()


def is_declined(status: str) -> bool:
    return status.startswith("Declinat")


def read_complaints(path: Path, area: Area, pad_m: float) -> list[Complaint] | None:
    """Complaints inside the area grown by pad_m; None if the export file is absent."""
    path = Path(path)
    if not path.exists():
        return None
    complaints = []
    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        geometry = feature.get("geometry")
        if not geometry:
            continue
        lon, lat = geometry["coordinates"][:2]
        if not in_area(lon, lat, area, pad_m):
            continue
        props = feature["properties"]
        complaints.append(
            Complaint(
                nr=str(props["nr"]),
                created=_day(props["created_at"]),
                status=(props.get("status") or "").strip(),
                subcategory=(props.get("subcategory") or "").strip(),
                street=props.get("street") or None,
                closed_at=_day(props.get("closed_at")),
                lon=lon,
                lat=lat,
            )
        )
    return complaints


def cluster(complaints: list[Complaint], max_m: float, max_days: int) -> list[list[Complaint]]:
    """A report joins an event if it is within max_m and max_days of that event's first report."""
    groups: list[list[Complaint]] = []
    anchors: list[tuple[float, float]] = []
    for complaint in sorted(complaints, key=lambda c: (c.created, c.nr)):
        position = to_metric(complaint.lon, complaint.lat)
        for group, anchor in zip(groups, anchors):
            if (complaint.created - group[0].created).days <= max_days and math.dist(position, anchor) <= max_m:
                group.append(complaint)
                break
        else:
            groups.append([complaint])
            anchors.append(position)
    return groups


def make_event(group: list[Complaint], as_of: date) -> Event:
    considered = [c for c in group if not is_declined(c.status)]
    if not considered:
        return Event(kind="declined", complaints=list(group))
    opened = [c for c in considered if c.status not in CLOSED_STATUSES]
    if not opened:
        closed_dates = [c.closed_at for c in considered if c.closed_at]
        return Event(kind="fixed", complaints=list(group), closed_at=max(closed_dates) if closed_dates else None)
    subcategories = {fold(c.subcategory) for c in opened}
    if AREA_SUBCATEGORY in subcategories:
        kind = "open_area_outage"
    elif subcategories & LAMP_SUBCATEGORIES:
        kind = "open_lamp_out"
    else:
        kind = "open_other"
    return Event(kind=kind, complaints=list(group), age_days=(as_of - max(c.created for c in opened)).days)


def build_events(complaints: list[Complaint], cfg: Config, as_of: date) -> list[Event]:
    groups = cluster(complaints, cfg.complaint_cluster_m, cfg.complaint_cluster_days)
    return [make_event(group, as_of) for group in groups]


def count_unrecognised(complaints: list[Complaint]) -> int:
    """Complaints whose status or sub-category is not one the rules know; they count as 'open, other'."""
    known_subcategories = {AREA_SUBCATEGORY} | LAMP_SUBCATEGORIES | OTHER_SUBCATEGORIES

    def known_status(status: str) -> bool:
        return status in CLOSED_STATUSES or status in OPEN_STATUSES or is_declined(status)

    return sum(1 for c in complaints if not known_status(c.status) or fold(c.subcategory) not in known_subcategories)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `63 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/lightmap/evidence.py src/lightmap/adapters/mapillary.py src/lightmap/adapters/sesizari.py tests/test_mapillary_adapter.py tests/test_sesizari.py
git commit -m "feat: Mapillary lamp reader and Sesizari complaint events"
```

---

### Task 5: Привязка свидетельств к отрезкам

**Files:**
- Create: `src/lightmap/attach.py`
- Test: `tests/test_attach.py`

**Interfaces:**
- Consumes: `lightmap.graph.Segment`; `lightmap.text.fold`; `helpers.make_segment`, `helpers.xy`.
- Produces (все координаты точек — массив `numpy` формы `(n, 2)` в метрах EPSG:32634):
  - `lamp_coverage(segments, lamp_xy, radius_m, step_m=10.0) -> np.ndarray` — доля длины каждого отрезка в `radius_m` от фонаря
  - `lamps_near(segments, lamp_xy, radius_m) -> dict[int, list[tuple[int, float]]]` — индекс отрезка → список `(индекс фонаря, расстояние)`
  - `attach_events(segments, event_xy, event_streets, radius_m, tie_m=5.0) -> dict[int, list[tuple[int, float]]]` — индекс события → список `(индекс отрезка, расстояние)`; непривязанных событий в словаре нет
  - `same_name_flags(segments, osm_kinds) -> set[int]`
  - `nearest_street(segments, radius_m) -> dict[int, int]` — индекс не-улицы → индекс ближайшей улицы

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/test_attach.py`:

```python
import numpy as np
import pytest

from helpers import make_segment, xy
from lightmap.attach import attach_events, lamp_coverage, lamps_near, nearest_street, same_name_flags


def pts(*offsets):
    return np.array([xy(dx, dy) for dx, dy in offsets], dtype=float).reshape(-1, 2)


@pytest.fixture
def block():
    """Two parallel streets 40 m apart and a sidewalk 8 m from the first one."""
    return [
        make_segment("A", "street", [(0, 0), (100, 0)], name="Strada A"),
        make_segment("B", "street", [(0, 40), (100, 40)], name="Strada B"),
        make_segment("SA", "sidewalk", [(0, -8), (100, -8)]),
    ]


def crossing():
    return [
        make_segment("A", "street", [(0, 0), (100, 0)], name="Strada A"),
        make_segment("C", "street", [(100, 0), (100, 100)], name="Strada C"),
    ]


def test_lamps_cover_the_street_and_its_sidewalk_but_not_the_parallel_street(block):
    lamps = pts(*[(x, -10) for x in (10, 30, 50, 70, 90)])
    assert lamp_coverage(block, lamps, 20).tolist() == [1.0, 0.0, 1.0]


def test_one_lamp_at_the_end_of_a_long_segment_is_not_enough():
    long_street = make_segment("L", "street", [(0, 0), (200, 0)])
    assert lamp_coverage([long_street], pts((200, 5)), 20)[0] == pytest.approx(0.1)


def test_coverage_without_lamps_is_zero(block):
    assert lamp_coverage(block, pts(), 20).tolist() == [0.0, 0.0, 0.0]


def test_lamps_near_lists_lamps_with_distance(block):
    near = lamps_near(block, pts((50, -10), (50, 300)), 20)
    assert set(near) == {0, 2}
    assert near[0] == [(0, pytest.approx(10.0, abs=0.01))]
    assert near[2] == [(0, pytest.approx(2.0, abs=0.01))]


def test_complaint_goes_to_the_nearest_street_only(block):
    got = attach_events(block, pts((50, 12)), [None], 30)
    assert got == {0: [(0, pytest.approx(12.0, abs=0.01))]}


@pytest.mark.parametrize("street, expected", [("strada c", [1]), (None, [0, 1]), ("Strada Z", [0, 1])])
def test_tie_at_a_junction_is_settled_by_the_street_name(street, expected):
    got = attach_events(crossing(), pts((97, 3)), [street], 30)
    assert [segment for segment, _ in got[0]] == expected


def test_falls_back_to_any_segment_and_leaves_far_events_out(block):
    got = attach_events(block, pts((50, -35), (50, -60)), [None, None], 30)
    assert list(got) == [0]
    assert got[0] == [(2, pytest.approx(27.0, abs=0.01))]


def test_same_name_flags_only_untagged_streets_with_a_tagged_namesake():
    segments = [
        make_segment("A1", "street", [(0, 0), (100, 0)], name="Strada A"),
        make_segment("A2", "street", [(100, 0), (200, 0)], name="strada a"),
        make_segment("B", "street", [(0, 40), (100, 40)], name="Strada B"),
        make_segment("P", "path", [(0, 80), (100, 80)], name="Strada A"),
        make_segment("A3", "street", [(200, 0), (300, 0)], name="Strada A"),
    ]
    assert same_name_flags(segments, ["lit_yes", None, None, None, "lit_no"]) == {1}


def test_nearest_street_uses_the_midpoint_within_the_radius(block):
    far_path = make_segment("P", "path", [(0, 150), (100, 150)])
    assert nearest_street(block + [far_path], 15) == {2: 0}
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_attach.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'lightmap.attach'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/attach.py`:

```python
"""Attach point evidence to segments and derive indirect signs (spec section 6)."""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import shapely
from shapely.strtree import STRtree

from lightmap.graph import Segment
from lightmap.text import fold


def _lines(segments: list[Segment]) -> np.ndarray:
    return np.array([s.line for s in segments], dtype=object)


def sample_points(segment: Segment, step_m: float = 10.0) -> np.ndarray:
    """Midpoints of n equal parts of the segment, n = max(1, round(length / step))."""
    n = max(1, round(segment.length_m / step_m))
    distances = (np.arange(n) + 0.5) * segment.length_m / n
    return shapely.line_interpolate_point(segment.line, distances)


def lamp_coverage(segments: list[Segment], lamp_xy: np.ndarray, radius_m: float, step_m: float = 10.0) -> np.ndarray:
    coverage = np.zeros(len(segments))
    if len(lamp_xy) == 0 or not segments:
        return coverage
    tree = STRtree(shapely.points(lamp_xy))
    points, owner = [], []
    for index, segment in enumerate(segments):
        samples = sample_points(segment, step_m)
        points.extend(samples)
        owner.extend([index] * len(samples))
    owner = np.array(owner)
    hit = np.zeros(len(points))
    hit[tree.query_nearest(np.array(points, dtype=object), max_distance=radius_m, all_matches=False)[0]] = 1.0
    return np.bincount(owner, weights=hit, minlength=len(segments)) / np.bincount(owner, minlength=len(segments))


def lamps_near(segments: list[Segment], lamp_xy: np.ndarray, radius_m: float) -> dict[int, list[tuple[int, float]]]:
    if len(lamp_xy) == 0 or not segments:
        return {}
    lamp_points = shapely.points(lamp_xy)
    lines = _lines(segments)
    near: dict[int, list[tuple[int, float]]] = defaultdict(list)
    segment_index, lamp_index = STRtree(lamp_points).query(lines, predicate="dwithin", distance=radius_m)
    for s, l in zip(segment_index, lamp_index):
        near[int(s)].append((int(l), float(shapely.distance(lines[s], lamp_points[l]))))
    return {s: sorted(pairs) for s, pairs in near.items()}


def attach_events(
    segments: list[Segment],
    event_xy: np.ndarray,
    event_streets: list[str | None],
    radius_m: float,
    tie_m: float = 5.0,
) -> dict[int, list[tuple[int, float]]]:
    """Nearest street within radius_m; near-ties go to the street named in the complaint, else to all of them.

    Events with no street in range fall back to the nearest segment of any kind. Events with nothing in
    range are left out of the result.
    """
    attached: dict[int, list[tuple[int, float]]] = {}
    if len(event_xy) == 0 or not segments:
        return attached
    points = shapely.points(event_xy)
    lines = _lines(segments)
    street_index = np.array([i for i, s in enumerate(segments) if s.kind == "street"], dtype=int)

    candidates: dict[int, list[tuple[int, float]]] = defaultdict(list)
    if len(street_index):
        event_i, street_i = STRtree(lines[street_index]).query(points, predicate="dwithin", distance=radius_m)
        for e, s in zip(event_i, street_i):
            segment = int(street_index[s])
            candidates[int(e)].append((segment, float(shapely.distance(points[e], lines[segment]))))
    for e, found in candidates.items():
        nearest = min(distance for _, distance in found)
        close = [(segment, distance) for segment, distance in found if distance - nearest < tie_m]
        if len(close) > 1 and event_streets[e]:
            wanted = fold(event_streets[e])
            named = [(segment, distance) for segment, distance in close if segments[segment].name and fold(segments[segment].name) == wanted]
            if named:
                close = named
        attached[e] = sorted(close, key=lambda pair: (pair[1], pair[0]))

    rest = [e for e in range(len(points)) if e not in attached]
    if rest:
        (event_i, segment_i), distances = STRtree(lines).query_nearest(points[rest], max_distance=radius_m, return_distance=True, all_matches=False)
        for e, s, distance in zip(event_i, segment_i, distances):
            attached[rest[int(e)]] = [(int(s), float(distance))]
    return attached


def same_name_flags(segments: list[Segment], osm_kinds: list[str | None]) -> set[int]:
    """Untagged streets that share a name with a street tagged lit=yes somewhere in the area."""
    tagged = {fold(s.name) for s, kind in zip(segments, osm_kinds) if s.kind == "street" and kind == "lit_yes" and s.name}
    return {i for i, (s, kind) in enumerate(zip(segments, osm_kinds)) if s.kind == "street" and kind is None and s.name and fold(s.name) in tagged}


def nearest_street(segments: list[Segment], radius_m: float) -> dict[int, int]:
    """For every non-street segment whose midpoint is within radius_m of a street: its nearest street."""
    streets = [i for i, s in enumerate(segments) if s.kind == "street"]
    others = [i for i, s in enumerate(segments) if s.kind != "street"]
    if not streets or not others:
        return {}
    midpoints = np.array([segments[i].line.interpolate(0.5, normalized=True) for i in others], dtype=object)
    other_i, street_i = STRtree(_lines([segments[i] for i in streets])).query_nearest(midpoints, max_distance=radius_m, all_matches=False)
    return {others[int(o)]: streets[int(s)] for o, s in zip(other_i, street_i)}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `74 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/lightmap/attach.py tests/test_attach.py
git commit -m "feat: lamp coverage, complaint attachment and indirect signs"
```

---

### Task 6: Сборка фактов по отрезкам

**Files:**
- Create: `src/lightmap/pipeline.py`
- Test: `tests/builders.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Segment`; `lit_kind`, `other_values`; `Evidence`; `Event`; функции `attach`; `classify`, `dark_by_complaints`, `Verdict`; `to_metric`; `Config`.
- Produces:
  - `lightmap.pipeline.SegmentResult(segment: Segment, verdict: Verdict, osm_kind: str | None, lamp_coverage: float, lamps: list[tuple[Evidence, float]], events: list[tuple[Event, float]], indirect: list[str], near_street_id: str | None, inherited_dark: bool)`
  - `run(segments, lamps, events, cfg) -> tuple[list[SegmentResult], dict]`; `lamps` и `events` могут быть `None` (источник не подключён); словарь содержит `events_total`, `events_unattached`, `other_lit_values`; результаты идут в порядке `segments`
  - тестовые заготовки `builders.lamp(dx_m, dy_m, ref="1", last_seen="2024-05-01") -> Evidence` и `builders.event(kind, dx_m, dy_m, age_days=None, street=None) -> Event` (номер жалобы `SZN2026-000001`, подкатегория `x`, дата подачи 2026-11-01)

- [ ] **Step 1: Написать заготовки и падающие тесты**

Файл `tests/builders.py`:

```python
"""Test builders for source records placed by metric offsets from the test origin."""
from __future__ import annotations

from datetime import date

from helpers import ll
from lightmap.adapters.sesizari import Complaint, Event
from lightmap.evidence import Evidence


def lamp(dx_m: float, dy_m: float, ref: str = "1", last_seen: str = "2024-05-01") -> Evidence:
    lon, lat = ll(dx_m, dy_m)
    return Evidence(source="mapillary", kind="lamp", ref=ref, lon=lon, lat=lat, observed_at=date.fromisoformat(last_seen))


def event(kind: str, dx_m: float, dy_m: float, age_days: int | None = None, street: str | None = None) -> Event:
    lon, lat = ll(dx_m, dy_m)
    first = Complaint(nr="SZN2026-000001", created=date(2026, 11, 1), status="In lucru", subcategory="x", street=street, closed_at=None, lon=lon, lat=lat)
    return Event(kind=kind, complaints=[first], age_days=age_days)
```

Файл `tests/test_pipeline.py`:

```python
from builders import event, lamp
from helpers import make_segment
from lightmap.pipeline import run


def by_id(results):
    return {r.segment.segment_id: r for r in results}


def test_three_sources_on_a_synthetic_block(cfg):
    a = make_segment("A", "street", [(0, 0), (100, 0)], name="Strada A", lit=["yes"])
    b = make_segment("B", "street", [(0, 40), (100, 40)], name="Strada B")
    sa = make_segment("SA", "sidewalk", [(0, -8), (100, -8)])
    far = make_segment("P", "path", [(0, 150), (100, 150)])
    lamps = [lamp(x, -10, ref=str(x)) for x in (10, 30, 50, 70, 90)]

    results, stats = run([a, b, sa, far], lamps, [event("fixed", 50, 45)], cfg)
    got = by_id(results)

    assert got["A"].verdict.status == "lit_confirmed" and got["A"].verdict.families == ("osm", "mapillary")
    assert got["B"].verdict.status == "lit_likely" and got["B"].verdict.families == ("sesizari",)
    assert got["SA"].verdict.status == "lit_confirmed" and got["SA"].near_street_id == "A"
    assert got["P"].verdict.status == "unknown" and got["P"].near_street_id is None
    assert [r.segment.segment_id for r in results] == ["A", "B", "SA", "P"]
    assert stats == {"events_total": 1, "events_unattached": 0, "other_lit_values": 0}


def test_sidewalk_inherits_from_its_street(cfg):
    a = make_segment("A", "street", [(0, 0), (100, 0)], name="Strada A", lit=["yes"])
    sa = make_segment("SA", "sidewalk", [(0, -8), (100, -8)])

    lit = by_id(run([a, sa], [], [], cfg)[0])
    assert lit["SA"].verdict.status == "lit_likely" and lit["SA"].indirect == ["near_lit_street"] and lit["SA"].verdict.confidence == 0

    dark = by_id(run([a, sa], [], [event("open_area_outage", 50, 3, age_days=4)], cfg)[0])
    assert dark["A"].verdict.status == "dark_reported"
    assert dark["SA"].verdict.status == "dark_reported" and dark["SA"].inherited_dark


def test_sources_can_be_missing(cfg):
    a = make_segment("A", "street", [(0, 0), (100, 0)], lit=["yes", "disused"])
    results, stats = run([a], None, None, cfg)
    assert results[0].verdict.status == "lit_confirmed"
    assert stats == {"events_total": 0, "events_unattached": 0, "other_lit_values": 1}


def test_same_name_and_partial_lamps(cfg):
    a1 = make_segment("A1", "street", [(0, 0), (100, 0)], name="Strada A", lit=["yes"])
    a2 = make_segment("A2", "street", [(100, 0), (300, 0)], name="Strada A")
    got = by_id(run([a1, a2], [lamp(300, 5)], [], cfg)[0])
    assert got["A2"].indirect == ["partial_lamps", "same_name"]
    assert got["A2"].verdict.status == "lit_likely" and got["A2"].lamp_coverage == 0.1


def test_unattached_events_are_counted(cfg):
    a = make_segment("A", "street", [(0, 0), (100, 0)])
    _, stats = run([a], [], [event("fixed", 50, 500)], cfg)
    assert stats["events_total"] == 1 and stats["events_unattached"] == 1
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'lightmap.pipeline'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/pipeline.py`:

```python
"""Turn segments and source records into one result per segment."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from lightmap.adapters.osm import lit_kind, other_values
from lightmap.adapters.sesizari import Event
from lightmap.attach import attach_events, lamp_coverage, lamps_near, nearest_street, same_name_flags
from lightmap.config import Config
from lightmap.evidence import Evidence
from lightmap.geo import to_metric
from lightmap.graph import Segment
from lightmap.rules import Verdict, classify, dark_by_complaints


@dataclass
class SegmentResult:
    segment: Segment
    verdict: Verdict
    osm_kind: str | None
    lamp_coverage: float
    lamps: list[tuple[Evidence, float]]
    events: list[tuple[Event, float]]
    indirect: list[str]
    near_street_id: str | None
    inherited_dark: bool


def _metric(points: list[tuple[float, float]]) -> np.ndarray:
    return np.array([to_metric(lon, lat) for lon, lat in points], dtype=float).reshape(-1, 2)


def run(segments: list[Segment], lamps: list[Evidence] | None, events: list[Event] | None, cfg: Config) -> tuple[list[SegmentResult], dict]:
    lamps = lamps or []
    events = events or []
    osm_kinds = [lit_kind(s.lit_values) for s in segments]

    lamp_xy = _metric([(lamp.lon, lamp.lat) for lamp in lamps])
    coverage = lamp_coverage(segments, lamp_xy, cfg.lamp_radius_m)
    near_lamps = lamps_near(segments, lamp_xy, cfg.lamp_radius_m)

    event_xy = _metric([(e.first.lon, e.first.lat) for e in events])
    attached = attach_events(segments, event_xy, [e.first.street for e in events], cfg.complaint_radius_m)
    segment_events: dict[int, list[tuple[Event, float]]] = defaultdict(list)
    for event_index, pairs in attached.items():
        for segment_index, distance in pairs:
            segment_events[segment_index].append((events[event_index], distance))

    same_name = same_name_flags(segments, osm_kinds)
    street_of = nearest_street(segments, cfg.inherit_radius_m)
    params = dict(coverage_min=cfg.lamp_coverage_min, fresh_days=cfg.open_complaint_fresh_days, lamps_out_for_dark=cfg.lamps_out_for_dark)

    def facts(i: int) -> list[tuple[str, int | None]]:
        return [(event.kind, event.age_days) for event, _ in segment_events.get(i, [])]

    def own_signs(i: int) -> list[str]:
        signs = []
        if 0 < coverage[i] < cfg.lamp_coverage_min:
            signs.append("partial_lamps")
        if i in same_name:
            signs.append("same_name")
        return signs

    verdicts: dict[int, Verdict] = {}
    indirect: dict[int, list[str]] = {}
    inherited: dict[int, bool] = {}
    # Streets first: other segments inherit from their nearest street.
    for i, segment in enumerate(segments):
        if segment.kind != "street":
            continue
        indirect[i], inherited[i] = own_signs(i), False
        verdicts[i] = classify(osm_kinds[i], float(coverage[i]), facts(i), indirect[i], False, **params)
    for i, segment in enumerate(segments):
        if segment.kind == "street":
            continue
        signs, dark = own_signs(i), False
        street = street_of.get(i)
        if street is not None:
            if verdicts[street].families or street in same_name:
                signs.append("near_lit_street")
            dark = dark_by_complaints(facts(street), cfg.open_complaint_fresh_days, cfg.lamps_out_for_dark)
        indirect[i], inherited[i] = signs, dark
        verdicts[i] = classify(osm_kinds[i], float(coverage[i]), facts(i), signs, dark, **params)

    results = [
        SegmentResult(
            segment=segment,
            verdict=verdicts[i],
            osm_kind=osm_kinds[i],
            lamp_coverage=round(float(coverage[i]), 4),
            lamps=[(lamps[lamp_index], distance) for lamp_index, distance in near_lamps.get(i, [])],
            events=segment_events.get(i, []),
            indirect=indirect[i],
            near_street_id=segments[street_of[i]].segment_id if i in street_of else None,
            inherited_dark=inherited[i],
        )
        for i, segment in enumerate(segments)
    ]
    stats = {
        "events_total": len(events),
        "events_unattached": len(events) - len(attached),
        "other_lit_values": sum(len(other_values(s.lit_values)) for s in segments),
    }
    return results, stats
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `79 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/lightmap/pipeline.py tests/builders.py tests/test_pipeline.py
git commit -m "feat: pipeline that turns segments and sources into per-segment results"
```

---

### Task 7: Выходные файлы и команда сборки

**Files:**
- Create: `src/lightmap/output.py`, `src/lightmap/build.py`, `data/out/segments.geojson`, `data/out/summary.json`
- Test: `tests/test_output.py`, `tests/test_build.py`

**Interfaces:**
- Consumes: `SegmentResult`, `run`; `STATUSES`; `Config`, `load_config`, `DEFAULT_CONFIG_PATH`; `load_graph`, `segments_from_graph`, `to_segment_graph`, `DEFAULT_CACHE_PATH`; `read_lamps`; `read_complaints`, `build_events`, `count_unrecognised`; `builders.lamp`, `builders.event`; `helpers.make_graph`, `helpers.make_segment`.
- Produces:
  - `lightmap.output.GROUPS` — группы метрик `streets`, `sidewalks`, `streets_and_sidewalks`, `paths`, `service`
  - `evidence_list(result) -> list[dict]`, `to_feature(result) -> dict`, `write_segments(results, path)`, `metrics(results) -> dict`, `build_summary(results, cfg, stats, sources, as_of, built_at) -> dict`, `write_summary(summary, path)`
  - свойства объекта в `segments.geojson`: `segment_id`, `kind`, `name`, `osm_way_ids`, `length_m`, `status`, `confidence`, `families`, `indirect`, `lamp_coverage`, `evidence`
  - ключи `summary.json`: `built_at`, `as_of`, `area`, `params`, `sources`, `stats`, `metrics`, `known_share`; доли в `metrics` — числа от 0 до 1
  - `lightmap.build.build(cfg, as_of, raw_dir, out_dir, cache_path, graph) -> dict`, `lightmap.build.main(argv=None) -> int`

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/test_output.py`:

```python
import json
from datetime import date, datetime, timezone

import pytest

from builders import event, lamp
from helpers import make_segment
from lightmap.output import build_summary, metrics, to_feature, write_segments, write_summary
from lightmap.pipeline import run


def block_results(cfg):
    a = make_segment("A", "street", [(0, 0), (100, 0)], name="Strada A", lit=["yes"])
    b = make_segment("B", "street", [(0, 40), (100, 40)], name="Strada B")
    sa = make_segment("SA", "sidewalk", [(0, -8), (100, -8)])
    lamps = [lamp(x, -10, ref=str(x)) for x in (10, 30, 50, 70, 90)]
    return run([a, b, sa], lamps, [event("fixed", 50, 45)], cfg)


def test_feature_properties_follow_the_spec(cfg):
    results, _ = block_results(cfg)
    feature = to_feature(results[0])
    props = feature["properties"]
    assert feature["geometry"]["type"] == "LineString" and len(feature["geometry"]["coordinates"]) == 2
    assert (props["segment_id"], props["kind"], props["name"], props["osm_way_ids"]) == ("A", "street", "Strada A", [1])
    assert (props["status"], props["confidence"], props["families"]) == ("lit_confirmed", 2, ["osm", "mapillary"])
    assert props["length_m"] == pytest.approx(100.0, abs=0.1) and props["lamp_coverage"] == 1.0 and props["indirect"] == []
    assert props["evidence"] == [
        {"source": "osm", "kind": "lit_yes", "ref": "way/1", "ways": [1]},
        {"source": "mapillary", "kind": "lamp", "count": 5, "nearest_m": 10.0, "last_seen_min": "2024-05-01", "last_seen_max": "2024-05-01"},
    ]


def test_complaint_and_derived_evidence(cfg):
    results, _ = block_results(cfg)
    assert to_feature(results[1])["properties"]["evidence"] == [
        {"source": "sesizari", "kind": "fixed", "ref": "SZN2026-000001", "reports": 1, "subcategory": "x", "created_at": "2026-11-01", "closed_at": None, "age_days": None, "distance_m": 5.0}
    ]
    assert {"source": "derived", "kind": "near_lit_street", "ref": "A"} in to_feature(results[2])["properties"]["evidence"]


def test_metrics_shares_add_up(cfg):
    results, _ = block_results(cfg)
    got = metrics(results)
    assert set(got) == {"streets", "sidewalks", "streets_and_sidewalks", "paths", "service"}
    assert got["streets"] == {"km": 0.2, "segments": 2, "lit_confirmed": 0.5, "lit_likely": 0.5, "dark_reported": 0.0, "unknown": 0.0}
    assert got["paths"] == {"km": 0.0, "segments": 0, "lit_confirmed": 0.0, "lit_likely": 0.0, "dark_reported": 0.0, "unknown": 0.0}


def test_files_and_summary(tmp_path, cfg):
    results, stats = block_results(cfg)
    write_segments(results, tmp_path / "out" / "segments.geojson")
    collection = json.loads((tmp_path / "out" / "segments.geojson").read_text(encoding="utf-8"))
    assert collection["type"] == "FeatureCollection" and len(collection["features"]) == 3

    summary = build_summary(results, cfg, stats, {"osm": {"connected": True}}, date(2026, 11, 14), datetime(2026, 11, 14, 5, 0, tzinfo=timezone.utc))
    assert (summary["as_of"], summary["built_at"]) == ("2026-11-14", "2026-11-14T05:00:00+00:00")
    assert summary["params"]["lamp_radius_m"] == 20 and summary["area"]["name"] == "test" and "area" not in summary["params"]
    assert summary["known_share"] == 1.0 and summary["stats"] == stats

    write_summary(summary, tmp_path / "out" / "summary.json")
    assert json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))["metrics"]["streets"]["segments"] == 2
```

Файл `tests/test_build.py`:

```python
from datetime import date

from helpers import make_graph
from lightmap import build as build_module
from lightmap.graph import to_segment_graph


def test_build_writes_outputs_without_optional_sources(tmp_path, cfg):
    summary = build_module.build(cfg, date(2026, 11, 14), tmp_path / "raw", tmp_path / "out", tmp_path / "cache" / "graph.graphml", to_segment_graph(make_graph()))
    assert (tmp_path / "out" / "segments.geojson").exists() and (tmp_path / "out" / "summary.json").exists()
    assert summary["sources"]["mapillary"]["connected"] is False and summary["sources"]["sesizari"]["connected"] is False
    assert summary["sources"]["osm"] == {"connected": True, "snapshot": None, "records": 3}
    assert summary["metrics"]["streets"]["segments"] == 2


def test_main_reports_a_failed_graph_download(tmp_path, monkeypatch, capsys):
    def boom(cfg, cache_path):
        raise ConnectionError("no network")

    monkeypatch.setattr(build_module, "load_graph", boom)
    code = build_module.main(["--config", "config/lightmap.json", "--out-dir", str(tmp_path / "out"), "--cache", str(tmp_path / "graph.graphml")])
    assert code == 1
    assert "street graph" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_output.py tests/test_build.py -q`
Expected: ошибки сбора `ModuleNotFoundError: No module named 'lightmap.output'` и `cannot import name 'build' from 'lightmap'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/output.py`:

```python
"""Output files: data/out/segments.geojson and data/out/summary.json (spec section 8)."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from lightmap.config import Config
from lightmap.pipeline import SegmentResult
from lightmap.rules import STATUSES

GROUPS = {
    "streets": {"street"},
    "sidewalks": {"sidewalk", "crossing"},
    "streets_and_sidewalks": {"street", "sidewalk", "crossing"},
    "paths": {"path"},
    "service": {"service"},
}


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def evidence_list(result: SegmentResult) -> list[dict]:
    """One object per source or event. Never contains complaint text or photos."""
    segment = result.segment
    evidence: list[dict] = []
    if result.osm_kind:
        ref = f"way/{segment.osm_way_ids[0]}" if segment.osm_way_ids else None
        evidence.append({"source": "osm", "kind": result.osm_kind, "ref": ref, "ways": segment.osm_way_ids})
    if result.lamps:
        seen = sorted(lamp.observed_at for lamp, _ in result.lamps if lamp.observed_at)
        evidence.append(
            {
                "source": "mapillary",
                "kind": "lamp",
                "count": len(result.lamps),
                "nearest_m": round(min(distance for _, distance in result.lamps), 1),
                "last_seen_min": _iso(seen[0]) if seen else None,
                "last_seen_max": _iso(seen[-1]) if seen else None,
            }
        )
    for event, distance in result.events:
        evidence.append(
            {
                "source": "sesizari",
                "kind": event.kind,
                "ref": event.first.nr,
                "reports": len(event.complaints),
                "subcategory": event.first.subcategory,
                "created_at": _iso(event.first.created),
                "closed_at": _iso(event.closed_at),
                "age_days": event.age_days,
                "distance_m": round(distance, 1),
            }
        )
    for sign in result.indirect:
        ref = segment.name if sign == "same_name" else (result.near_street_id if sign == "near_lit_street" else None)
        evidence.append({"source": "derived", "kind": sign, "ref": ref})
    if result.inherited_dark:
        evidence.append({"source": "derived", "kind": "inherited_dark", "ref": result.near_street_id})
    return evidence


def to_feature(result: SegmentResult) -> dict:
    segment = result.segment
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in segment.coords]},
        "properties": {
            "segment_id": segment.segment_id,
            "kind": segment.kind,
            "name": segment.name,
            "osm_way_ids": segment.osm_way_ids,
            "length_m": round(segment.length_m, 1),
            "status": result.verdict.status,
            "confidence": result.verdict.confidence,
            "families": list(result.verdict.families),
            "indirect": list(result.indirect),
            "lamp_coverage": round(result.lamp_coverage, 2),
            "evidence": evidence_list(result),
        },
    }


def write_segments(results: list[SegmentResult], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "features": [to_feature(r) for r in results]}
    path.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def metrics(results: list[SegmentResult]) -> dict:
    """Per group: length in km, number of segments, share of length per status (0..1)."""
    table = {}
    for group, kinds in GROUPS.items():
        rows = [r for r in results if r.segment.kind in kinds]
        total = sum(r.segment.length_m for r in rows)
        entry = {"km": round(total / 1000, 2), "segments": len(rows)}
        for status in STATUSES:
            part = sum(r.segment.length_m for r in rows if r.verdict.status == status)
            entry[status] = round(part / total, 4) if total else 0.0
        table[group] = entry
    return table


def build_summary(results: list[SegmentResult], cfg: Config, stats: dict, sources: dict, as_of: date, built_at: datetime) -> dict:
    table = metrics(results)
    return {
        "built_at": built_at.isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "area": asdict(cfg.area),
        "params": {key: value for key, value in asdict(cfg).items() if key != "area"},
        "sources": sources,
        "stats": stats,
        "metrics": table,
        "known_share": round(1 - table["streets_and_sidewalks"]["unknown"], 4),
    }


def write_summary(summary: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
```

Файл `src/lightmap/build.py`:

```python
"""Build the lighting-confidence map: python -m lightmap.build [--as-of YYYY-MM-DD]"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import networkx as nx

from lightmap.adapters.mapillary import read_lamps
from lightmap.adapters.sesizari import build_events, count_unrecognised, read_complaints
from lightmap.config import DEFAULT_CONFIG_PATH, Config, load_config
from lightmap.graph import DEFAULT_CACHE_PATH, load_graph, segments_from_graph
from lightmap.output import build_summary, write_segments, write_summary
from lightmap.pipeline import run

RAW_LAMPS = "mapillary_street_lights.geojson"
RAW_COMPLAINTS = "sesizari_iluminat.geojson"


def _snapshot(path: Path) -> str | None:
    """Date of the file's last modification: the best 'data as of' we have for a raw export."""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()


def build(cfg: Config, as_of: date, raw_dir: Path, out_dir: Path, cache_path: Path, graph: nx.MultiGraph) -> dict:
    segments = segments_from_graph(graph)
    pad_m = max(cfg.lamp_radius_m, cfg.complaint_radius_m)
    lamps_path, complaints_path = Path(raw_dir) / RAW_LAMPS, Path(raw_dir) / RAW_COMPLAINTS
    lamps = read_lamps(lamps_path, cfg.area, pad_m)
    complaints = read_complaints(complaints_path, cfg.area, pad_m)
    events = build_events(complaints, cfg, as_of) if complaints is not None else None

    results, stats = run(segments, lamps, events, cfg)
    sources = {
        "osm": {"connected": True, "snapshot": _snapshot(Path(cache_path)), "records": len(segments)},
        "mapillary": {"connected": lamps is not None, "file": RAW_LAMPS, "snapshot": _snapshot(lamps_path), "records": len(lamps or [])},
        "sesizari": {
            "connected": complaints is not None,
            "file": RAW_COMPLAINTS,
            "snapshot": _snapshot(complaints_path),
            "records": len(complaints or []),
            "events": len(events or []),
            "unrecognised": count_unrecognised(complaints or []),
        },
    }
    write_segments(results, Path(out_dir) / "segments.geojson")
    summary = build_summary(results, cfg, stats, sources, as_of, datetime.now(timezone.utc))
    write_summary(summary, Path(out_dir) / "summary.json")
    return summary


def print_table(summary: dict) -> None:
    print(f"{'group':24}{'km':>8}{'confirmed':>11}{'likely':>9}{'dark':>7}{'unknown':>9}")
    for group, row in summary["metrics"].items():
        print(f"{group:24}{row['km']:>8.1f}{row['lit_confirmed']:>11.1%}{row['lit_likely']:>9.1%}{row['dark_reported']:>7.1%}{row['unknown']:>9.1%}")
    print(f"known share on streets and sidewalks: {summary['known_share']:.1%}")
    for name, source in summary["sources"].items():
        print(f"source {name}: {'connected' if source['connected'] else 'NOT connected'}, records {source['records']}")
    print(f"complaint events: {summary['stats']['events_total']}, unattached: {summary['stats']['events_unattached']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the lighting-confidence map for the configured area.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="date used to age open complaints (default: today, UTC)")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/out"))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    as_of = args.as_of or datetime.now(timezone.utc).date()
    try:
        graph = load_graph(cfg, args.cache)
    except Exception as exc:  # any download failure must end with a clear message, not a traceback
        print(f"Cannot get the street graph for area '{cfg.area.name}': {exc}. Check the network connection and run the command again.", file=sys.stderr)
        return 1
    summary = build(cfg, as_of, args.raw_dir, args.out_dir, args.cache, graph)
    print_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `85 passed`.

- [ ] **Step 5: Положить входные данные и собрать карту на реальных данных**

Run:

```bash
mkdir -p data/raw && cp "C:/Users/Timur/Downloads/unihack-data/geojson/mapillary_street_lights.geojson" "C:/Users/Timur/Downloads/unihack-data/geojson/sesizari_iluminat.geojson" data/raw/ && .venv/Scripts/python -m lightmap.build --as-of 2026-11-14
```

Expected: первая сборка скачивает граф (до минуты), затем печатает таблицу. Числа должны быть близки к черновой сборке (расхождение больше 3 процентных пунктов — искать ошибку):

| group | km | confirmed | likely | dark | unknown |
|---|---:|---:|---:|---:|---:|
| streets | 43.2 | 57.7% | 23.9% | 0.6% | 17.9% |
| sidewalks | 31.1 | 68.1% | 24.0% | 2.3% | 5.7% |
| streets_and_sidewalks | 74.3 | 62.0% | 23.9% | 1.3% | 12.8% |
| paths | 35.6 | 28.3% | 18.9% | 4.1% | 48.7% |
| service | 12.2 | 20.1% | 21.4% | 0.8% | 57.7% |

Все три источника должны быть `connected`; `records` у `osm` — около 3280.

- [ ] **Step 6: Проверить, что входные данные не попали в git**

Run: `git status --short`
Expected: в списке есть `data/out/`, `src/lightmap/output.py`, `src/lightmap/build.py`, тесты; строк с `data/raw` и `data/cache` нет.

- [ ] **Step 7: Commit**

```bash
git add src/lightmap/output.py src/lightmap/build.py tests/test_output.py tests/test_build.py data/out/segments.geojson data/out/summary.json
git commit -m "feat: output files, build command, first build of the model area"
```

---

### Task 8: Карта

**Files:**
- Create: `web/index.html`, `web/style.css`, `web/i18n.js`, `web/app.js`, `web/vendor/leaflet/leaflet.js`, `web/vendor/leaflet/leaflet.css`, `web/vendor/leaflet/images/*`

**Interfaces:**
- Consumes: `data/out/segments.geojson` и `data/out/summary.json` в формате из задачи 7.
- Produces: страница `http://127.0.0.1:8000/web/`.

- [ ] **Step 1: Положить Leaflet в репозиторий**

Run:

```bash
mkdir -p web/vendor/leaflet/images && base=https://unpkg.com/leaflet@1.9.4/dist && curl -sSfL -o web/vendor/leaflet/leaflet.js $base/leaflet.js && curl -sSfL -o web/vendor/leaflet/leaflet.css $base/leaflet.css && for f in layers.png layers-2x.png marker-icon.png marker-icon-2x.png marker-shadow.png; do curl -sSfL -o web/vendor/leaflet/images/$f $base/images/$f; done && ls -la web/vendor/leaflet web/vendor/leaflet/images
```

Expected: `leaflet.js` около 147 КБ, `leaflet.css` около 14 КБ, пять файлов в `images/`.

- [ ] **Step 2: Написать страницу**

Файл `web/index.html`:

```html
<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Încrederea în iluminatul stradal — Timișoara</title>
<link rel="stylesheet" href="vendor/leaflet/leaflet.css">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1 id="title"></h1>
  <button id="lang" type="button"></button>
</header>
<main>
  <div id="map" role="application"></div>
  <aside id="panel">
    <section id="legend"></section>
    <section id="summary" aria-live="polite"></section>
    <p id="hint"></p>
    <p id="attribution">
      © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> ·
      <a href="https://www.mapillary.com"><img src="vendor/mapillary-logo.svg" alt="" height="14" onerror="this.remove()"> Mapillary</a> ·
      <a href="https://sesizari.primariatm.ro">Primăria Timișoara — Sesizări</a>
    </p>
  </aside>
</main>
<script src="vendor/leaflet/leaflet.js"></script>
<script src="i18n.js"></script>
<script src="app.js"></script>
</body>
</html>
```

Файл `web/style.css`:

```css
:root { --ink: #111; --muted: #444; --line: #ddd; }
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { display: flex; flex-direction: column; font: 15px/1.45 system-ui, "Segoe UI", Arial, sans-serif; color: var(--ink); background: #fff; }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 14px; border-bottom: 1px solid var(--line); }
header h1 { font-size: 18px; margin: 0; }
#lang { font: inherit; padding: 6px 12px; border: 1px solid #555; border-radius: 6px; background: #fff; color: var(--ink); cursor: pointer; }
#lang:focus-visible, a:focus-visible { outline: 3px solid #0b57d0; outline-offset: 2px; }
main { flex: 1; display: flex; min-height: 0; }
#map { flex: 1; min-height: 320px; background: #f3f3f1; }
#panel { width: 370px; overflow: auto; padding: 12px 14px; border-left: 1px solid var(--line); }
.basemap { filter: grayscale(1) brightness(1.06) contrast(.9); }
.leg { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.sw { flex: 0 0 38px; height: 0; border-top: 4px solid; }
.dot { display: inline-block; width: 10px; height: 10px; margin-right: 6px; border: 1px solid #1b1b1b; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 13px; }
th, td { padding: 3px 4px; text-align: right; border-bottom: 1px solid #eee; font-weight: normal; }
th:first-child { text-align: left; }
tr:first-child th { font-weight: 600; }
#panel p { margin: 8px 0; font-size: 13px; color: var(--muted); }
#attribution img { vertical-align: middle; }
.leaflet-popup-content { font-size: 13px; }
.leaflet-popup-content ul { margin: 6px 0 4px 16px; padding: 0; }
@media (max-width: 800px) {
  main { flex-direction: column; }
  #panel { width: auto; max-height: 45vh; border-left: 0; border-top: 1px solid var(--line); }
}
```

Файл `web/i18n.js`:

```javascript
// Interface texts: Romanian first, English second. The word "safe" is never used: we only know about lighting.
const I18N = {
  ro: {
    title: 'Încrederea în iluminatul stradal — Timișoara',
    langButton: 'English',
    mapLabel: 'Hartă: segmente de stradă colorate după starea iluminatului',
    status: {
      lit_confirmed: 'Iluminat — dovadă directă',
      lit_likely: 'Probabil iluminat — doar indicii indirecte',
      dark_reported: 'Semnalat ca neiluminat',
      unknown: 'Fără date'
    },
    kind: { street: 'stradă', sidewalk: 'trotuar', crossing: 'trecere de pietoni', path: 'alee', service: 'drum de acces' },
    layers: { street: 'Străzi', sidewalk: 'Trotuare și treceri', path: 'Alei (parcuri, campus)', service: 'Drumuri de acces și curți' },
    groups: { streets: 'Străzi', sidewalks: 'Trotuare', streets_and_sidewalks: 'Străzi și trotuare', paths: 'Alei', service: 'Drumuri de acces' },
    table: { caption: 'Pondere din lungime, %', km: 'km', lit_confirmed: 'iluminat', lit_likely: 'probabil', dark_reported: 'neiluminat', unknown: 'fără date' },
    known: 'Stare cunoscută pe străzi și trotuare: {x}% din lungime.',
    sources: 'Date: OpenStreetMap ({osm}), Mapillary ({mapillary}), Sesizări – Primăria Timișoara ({sesizari}).',
    notConnected: 'sursă neconectată',
    hint: 'Apăsați pe un segment pentru a vedea dovezile.',
    noName: 'fără nume',
    sourcesCount: 'Surse independente: {n}',
    noEvidence: 'Nicio dovadă',
    metres: 'm',
    ev: {
      osm_lit_yes: 'OpenStreetMap: marcat ca iluminat (lit=yes)',
      osm_lit_no: 'OpenStreetMap: marcat ca neiluminat (lit=no)',
      osm_lit_mixed: 'OpenStreetMap: marcaje contradictorii (lit=yes și lit=no)',
      lamps: 'Mapillary: {n} stâlpi de iluminat la cel mult {r} m, acoperă {cov}% din lungime, văzuți în {years}',
      lampsBelow: ' — sub jumătate, sursa nu este luată în calcul',
      complaint: 'Sesizări {nr}: {sub} — {state}, depusă la {created}{closed}, la {d} m de segment',
      closedAt: ', închisă la {date}',
      reportsMore: ' (+{n})',
      state: {
        fixed: 'rezolvată',
        open_area_outage: 'deschisă: iluminatul nu funcționează în zonă',
        open_lamp_out: 'deschisă: bec nefuncțional',
        open_other: 'deschisă: altă problemă',
        declined: 'declinată, nu este luată în calcul'
      },
      same_name: 'Indirect: strada „{ref}” este marcată ca iluminată în altă parte a zonei',
      near_lit_street: 'Indirect: alături este o stradă cu dovezi de iluminat',
      partial_lamps: 'Indirect: stâlpi de iluminat doar pe o parte din segment',
      inherited_dark: 'Strada alăturată este semnalată ca neiluminată'
    },
    loadError: 'Datele nu au putut fi încărcate. Deschideți pagina printr-un server HTTP: python -m http.server 8000'
  },
  en: {
    title: 'Street-lighting confidence — Timișoara',
    langButton: 'Română',
    mapLabel: 'Map: street segments coloured by lighting status',
    status: {
      lit_confirmed: 'Lit — direct evidence',
      lit_likely: 'Probably lit — indirect signs only',
      dark_reported: 'Reported dark',
      unknown: 'No data'
    },
    kind: { street: 'street', sidewalk: 'sidewalk', crossing: 'crossing', path: 'path', service: 'service road' },
    layers: { street: 'Streets', sidewalk: 'Sidewalks and crossings', path: 'Paths (parks, campus)', service: 'Service roads and yards' },
    groups: { streets: 'Streets', sidewalks: 'Sidewalks', streets_and_sidewalks: 'Streets and sidewalks', paths: 'Paths', service: 'Service roads' },
    table: { caption: 'Share of length, %', km: 'km', lit_confirmed: 'lit', lit_likely: 'probably', dark_reported: 'dark', unknown: 'no data' },
    known: 'Known status on streets and sidewalks: {x}% of the length.',
    sources: 'Data: OpenStreetMap ({osm}), Mapillary ({mapillary}), Sesizări – Timișoara City Hall ({sesizari}).',
    notConnected: 'source not connected',
    hint: 'Click a segment to see the evidence.',
    noName: 'unnamed',
    sourcesCount: 'Independent sources: {n}',
    noEvidence: 'No evidence',
    metres: 'm',
    ev: {
      osm_lit_yes: 'OpenStreetMap: tagged as lit (lit=yes)',
      osm_lit_no: 'OpenStreetMap: tagged as not lit (lit=no)',
      osm_lit_mixed: 'OpenStreetMap: conflicting tags (lit=yes and lit=no)',
      lamps: 'Mapillary: {n} street lights within {r} m, covering {cov}% of the length, seen in {years}',
      lampsBelow: ' — below half, the source is not counted',
      complaint: 'Sesizări {nr}: {sub} — {state}, filed on {created}{closed}, {d} m from the segment',
      closedAt: ', closed on {date}',
      reportsMore: ' (+{n})',
      state: {
        fixed: 'resolved',
        open_area_outage: 'open: lighting does not work in the area',
        open_lamp_out: 'open: a lamp is out',
        open_other: 'open: other issue',
        declined: 'declined, not counted'
      },
      same_name: 'Indirect: the street “{ref}” is tagged as lit elsewhere in the area',
      near_lit_street: 'Indirect: next to a street with lighting evidence',
      partial_lamps: 'Indirect: street lights along only part of the segment',
      inherited_dark: 'The adjacent street is reported dark'
    },
    loadError: 'The data could not be loaded. Open the page through an HTTP server: python -m http.server 8000'
  }
};
```

Файл `web/app.js`:

```javascript
(async function () {
  'use strict';

  // Colour AND line pattern differ per status, so colour is never the only cue.
  const STYLE = {
    lit_confirmed: { color: '#009E73', dash: null, weight: 4, css: 'solid' },
    lit_likely: { color: '#E69F00', dash: '9 6', weight: 4, css: 'dashed' },
    dark_reported: { color: '#D55E00', dash: '13 5 2 5', weight: 5, css: 'double' },
    unknown: { color: '#7F7F7F', dash: '1 7', weight: 3, css: 'dotted' }
  };
  const DRAW_ORDER = ['unknown', 'lit_likely', 'lit_confirmed', 'dark_reported'];
  const LEGEND_ORDER = ['lit_confirmed', 'lit_likely', 'dark_reported', 'unknown'];
  const LAYER_OF = { street: 'street', sidewalk: 'sidewalk', crossing: 'sidewalk', path: 'path', service: 'service' };
  const LAYER_KEYS = ['street', 'sidewalk', 'path', 'service'];
  const TABLE_GROUPS = ['streets', 'sidewalks', 'streets_and_sidewalks', 'paths', 'service'];
  let lang = 'ro';

  const el = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function tr(path, vars) {
    let text = path.split('.').reduce((node, key) => (node == null ? undefined : node[key]), I18N[lang]);
    if (text == null) return path;
    for (const [key, value] of Object.entries(vars || {})) text = text.replaceAll('{' + key + '}', String(value));
    return text;
  }

  let data, summary;
  try {
    const [segments, info] = await Promise.all([fetch('../data/out/segments.geojson'), fetch('../data/out/summary.json')]);
    if (!segments.ok || !info.ok) throw new Error('HTTP ' + segments.status + ' / ' + info.status);
    data = await segments.json();
    summary = await info.json();
  } catch (err) {
    el('title').textContent = tr('title');
    el('summary').textContent = tr('loadError');
    console.error(err);
    return;
  }

  const area = summary.area;
  const bounds = [[area.south, area.west], [area.north, area.east]];
  const map = L.map('map', { preferCanvas: true, renderer: L.canvas({ tolerance: 6 }) }).fitBounds(bounds);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, className: 'basemap', attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
  L.rectangle(bounds, { color: '#333', weight: 1, dashArray: '4 4', fill: false, interactive: false }).addTo(map);

  const layers = { street: L.layerGroup(), sidewalk: L.layerGroup(), path: L.layerGroup(), service: L.layerGroup() };
  const features = data.features.slice().sort((a, b) => DRAW_ORDER.indexOf(a.properties.status) - DRAW_ORDER.indexOf(b.properties.status));
  for (const feature of features) {
    const p = feature.properties;
    const style = STYLE[p.status] || STYLE.unknown;
    const latlngs = feature.geometry.coordinates.map(c => [c[1], c[0]]);
    const layer = layers[LAYER_OF[p.kind] || 'service'];
    const thinner = p.kind === 'street' ? 0 : 1.5;
    // Dark casing under every line keeps contrast with the basemap at 3:1 or better.
    L.polyline(latlngs, { color: '#1b1b1b', weight: style.weight + 2 - thinner, opacity: 0.5, interactive: false }).addTo(layer);
    L.polyline(latlngs, { color: style.color, weight: style.weight - thinner, dashArray: style.dash, lineCap: p.status === 'unknown' ? 'round' : 'butt' })
      .bindPopup(() => popupHtml(p), { maxWidth: 380 })
      .addTo(layer);
  }
  layers.street.addTo(map);
  layers.sidewalk.addTo(map);
  layers.path.addTo(map);

  function evidenceLine(e, p) {
    if (e.source === 'osm') return esc(tr('ev.osm_' + e.kind));
    if (e.source === 'mapillary') {
      const years = [e.last_seen_min, e.last_seen_max].filter(Boolean).map(d => d.slice(0, 4));
      const span = years.length === 0 ? '?' : (years[0] === years[years.length - 1] ? years[0] : years[0] + '–' + years[years.length - 1]);
      const line = tr('ev.lamps', { n: e.count, r: summary.params.lamp_radius_m, cov: Math.round(p.lamp_coverage * 100), years: span });
      return esc(line + (p.lamp_coverage < summary.params.lamp_coverage_min ? tr('ev.lampsBelow') : ''));
    }
    if (e.source === 'sesizari') {
      const more = e.reports > 1 ? tr('ev.reportsMore', { n: e.reports - 1 }) : '';
      const closed = e.closed_at ? tr('ev.closedAt', { date: e.closed_at }) : '';
      return esc(tr('ev.complaint', { nr: e.ref + more, sub: e.subcategory, state: tr('ev.state.' + e.kind), created: e.created_at, closed: closed, d: Math.round(e.distance_m) }));
    }
    return esc(tr('ev.' + e.kind, { ref: e.ref || '' }));
  }

  function popupHtml(p) {
    const style = STYLE[p.status] || STYLE.unknown;
    const items = p.evidence.length ? p.evidence.map(e => '<li>' + evidenceLine(e, p) + '</li>').join('') : '<li>' + esc(tr('noEvidence')) + '</li>';
    return '<strong>' + esc(p.name || tr('noName')) + '</strong> · ' + esc(tr('kind.' + p.kind)) + ' · ' + Math.round(p.length_m) + ' ' + esc(tr('metres')) +
      '<br><span class="dot" style="background:' + style.color + '"></span><strong>' + esc(tr('status.' + p.status)) + '</strong>' +
      '<br>' + esc(tr('sourcesCount', { n: p.confidence })) + '<ul>' + items + '</ul><small>' + esc(p.segment_id) + '</small>';
  }

  let layerControl = null;
  function render() {
    document.documentElement.lang = lang;
    document.title = tr('title');
    el('title').textContent = tr('title');
    el('lang').textContent = tr('langButton');
    el('map').setAttribute('aria-label', tr('mapLabel'));
    el('hint').textContent = tr('hint');
    el('legend').innerHTML = LEGEND_ORDER.map(key =>
      '<div class="leg"><span class="sw" style="border-top-style:' + STYLE[key].css + ';border-top-color:' + STYLE[key].color + '"></span>' + esc(tr('status.' + key)) + '</div>').join('');

    const percent = x => (x * 100).toFixed(1);
    const head = '<tr><th scope="col">' + esc(tr('table.caption')) + '</th><th scope="col">' + esc(tr('table.km')) + '</th>' +
      LEGEND_ORDER.map(key => '<th scope="col">' + esc(tr('table.' + key)) + '</th>').join('') + '</tr>';
    const rows = TABLE_GROUPS.map(group => {
      const m = summary.metrics[group];
      return '<tr><th scope="row">' + esc(tr('groups.' + group)) + '</th><td>' + m.km.toFixed(1) + '</td>' + LEGEND_ORDER.map(key => '<td>' + percent(m[key]) + '</td>').join('') + '</tr>';
    }).join('');
    const snapshot = name => { const s = summary.sources[name]; return s && s.connected ? (s.snapshot || '?') : tr('notConnected'); };
    el('summary').innerHTML = '<table>' + head + rows + '</table>' +
      '<p>' + esc(tr('known', { x: percent(summary.known_share) })) + '</p>' +
      '<p>' + esc(tr('sources', { osm: snapshot('osm'), mapillary: snapshot('mapillary'), sesizari: snapshot('sesizari') })) + '</p>';

    if (layerControl) layerControl.remove();
    const overlays = {};
    for (const key of LAYER_KEYS) overlays[tr('layers.' + key)] = layers[key];
    layerControl = L.control.layers(null, overlays, { collapsed: false }).addTo(map);
    map.closePopup();
  }

  el('lang').addEventListener('click', () => { lang = lang === 'ro' ? 'en' : 'ro'; render(); });
  render();
})();
```

- [ ] **Step 3: Запустить сервер**

Run (в фоне, сервер должен работать до конца задачи):

```bash
.venv/Scripts/python -m http.server 8000 --bind 127.0.0.1
```

Затем в другом вызове: `curl -s -o /dev/null -w "%{http_code} %{size_download}\n" http://127.0.0.1:8000/web/ && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/data/out/segments.geojson`
Expected: `200` и размер страницы около 1 КБ; вторая строка `200`.

- [ ] **Step 4: Проверить синтаксис скриптов**

Run: `node --check web/app.js && node --check web/i18n.js && echo "JS syntax OK"`
Expected: `JS syntax OK`.

- [ ] **Step 5: Снять скриншот и посмотреть на него**

Run:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --hide-scrollbars --no-first-run --window-size=1500,900 --user-data-dir="$TEMP/lightmap-chrome" --virtual-time-budget=30000 --screenshot="$TEMP/lightmap-web.png" "http://127.0.0.1:8000/web/" 2>&1 | grep -i "written"
```

Expected: строка `… bytes written to file …lightmap-web.png`. Откройте PNG и убедитесь глазами:

- слева серая карта города, поверх неё раскрашенные отрезки: зелёные сплошные, жёлтые штриховые, серые точками;
- справа панель: заголовок на румынском, легенда из четырёх статусов, таблица из пяти строк с числами, строка с датами источников;
- вверху справа кнопка `English`.

Если карта пустая или панель показывает текст `Datele nu au putut fi încărcate…`, проверьте шаг 3.

- [ ] **Step 6: Commit**

```bash
git add web/index.html web/style.css web/i18n.js web/app.js web/vendor/leaflet
git commit -m "feat: static map viewer with evidence popups, Romanian and English"
```

---

### Task 9: Проверка go/no-go

**Files:**
- Create: `src/lightmap/validate.py`, `docs/validation.md` (создаётся командой)
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `load_config`, `DEFAULT_CONFIG_PATH`, `Config`; `data/out/segments.geojson`, `data/out/summary.json`.
- Produces:
  - `lightmap.validate.run_checks(features, cfg) -> dict` с ключами `unknown_share`, `unknown_share_ok`, `lit_no_confirmed`, `lit_no_confirmed_ok`, `lamp_recall`, `lamp_recall_ok`, `passed`
  - `pick_sample(features, seed=SAMPLE_SEED) -> list[dict]`, `validation_markdown(sample, as_of) -> str`, `main(argv=None) -> int`
  - ключ `checks` в `data/out/summary.json`

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/test_validate.py`:

```python
import json

from lightmap.validate import main, pick_sample, run_checks, validation_markdown

OSM_YES = {"source": "osm", "kind": "lit_yes", "ref": "way/1"}
OSM_NO = {"source": "osm", "kind": "lit_no", "ref": "way/2"}


def feat(segment_id, kind, status, length, families=(), evidence=(), name=None):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[21.22, 45.745], [21.221, 45.745], [21.222, 45.745]]},
        "properties": {"segment_id": segment_id, "kind": kind, "name": name, "length_m": length, "status": status, "families": list(families), "evidence": list(evidence)},
    }


def test_checks_pass_on_a_healthy_set(cfg):
    features = [
        feat("a", "street", "lit_confirmed", 100, ["osm", "mapillary"], [OSM_YES]),
        feat("b", "street", "lit_confirmed", 60, ["osm"], [OSM_YES]),
        feat("c", "sidewalk", "unknown", 40),
        feat("d", "path", "unknown", 500),
    ]
    checks = run_checks(features, cfg)
    assert checks["unknown_share"] == 0.2 and checks["unknown_share_ok"]
    assert checks["lamp_recall"] == 0.625 and checks["lamp_recall_ok"]
    assert checks["lit_no_confirmed"] == 0 and checks["lit_no_confirmed_ok"] and checks["passed"]


def test_checks_fail_on_unknown_share_contradiction_and_recall(cfg):
    features = [feat("a", "street", "unknown", 100), feat("b", "street", "lit_confirmed", 100, ["mapillary"], [OSM_NO])]
    checks = run_checks(features, cfg)
    assert not checks["unknown_share_ok"] and checks["lit_no_confirmed"] == 1 and not checks["lamp_recall_ok"] and not checks["passed"]


def test_sample_is_deterministic_and_follows_the_quota():
    statuses = ["lit_confirmed"] * 6 + ["lit_likely"] * 5 + ["unknown"] * 4 + ["dark_reported"] * 2
    features = [feat(f"s{i:02d}", "street", status, 50, name=f"Strada {i}") for i, status in enumerate(statuses)]
    features += [feat("short", "street", "lit_confirmed", 5), feat("p", "path", "unknown", 50)]
    first, second = pick_sample(features), pick_sample(list(reversed(features)))
    ids = lambda sample: [f["properties"]["segment_id"] for f in sample]
    assert ids(first) == ids(second)
    assert [f["properties"]["status"] for f in first] == ["lit_confirmed"] * 4 + ["lit_likely"] * 3 + ["unknown"] * 2 + ["dark_reported"]
    assert not {"short", "p"} & set(ids(first))


def test_validation_markdown_has_a_row_with_a_mapillary_link():
    text = validation_markdown([feat("a", "street", "lit_confirmed", 100, name="Strada A")], "2026-11-14")
    assert "| 1 | `a` | Strada A | `lit_confirmed` | [открыть](https://www.mapillary.com/app/?lat=45.745000&lng=21.221000&z=18) |" in text


def test_main_updates_the_summary_and_keeps_a_filled_sheet(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    features = [feat("a", "street", "lit_confirmed", 100, ["osm", "mapillary"], [OSM_YES], name="Strada A")]
    (out / "segments.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"as_of": "2026-11-14"}), encoding="utf-8")
    sheet = tmp_path / "validation.md"
    args = ["--config", "config/lightmap.json", "--out-dir", str(out), "--doc", str(sheet)]

    assert main(args) == 0
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["checks"]["passed"] is True
    assert "`a`" in sheet.read_text(encoding="utf-8")

    sheet.write_text("filled in by a human", encoding="utf-8")
    main(args)
    assert sheet.read_text(encoding="utf-8") == "filled in by a human"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_validate.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'lightmap.validate'`.

- [ ] **Step 3: Написать реализацию**

Файл `src/lightmap/validate.py`:

```python
"""Go/no-go checks for the built map (spec section 10): python -m lightmap.validate"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from lightmap.config import DEFAULT_CONFIG_PATH, Config, load_config

SAMPLE_SEED = 20261114
SAMPLE_QUOTA = (("lit_confirmed", 4), ("lit_likely", 3), ("unknown", 2), ("dark_reported", 1))
SAMPLE_MIN_LENGTH_M = 30
WALK_KINDS = ("street", "sidewalk", "crossing")


def _length(features: list[dict], keep) -> float:
    return sum(f["properties"]["length_m"] for f in features if keep(f["properties"]))


def _has(props: dict, source: str, kind: str) -> bool:
    return any(e["source"] == source and e["kind"] == kind for e in props["evidence"])


def run_checks(features: list[dict], cfg: Config) -> dict:
    walk_total = _length(features, lambda p: p["kind"] in WALK_KINDS)
    walk_unknown = _length(features, lambda p: p["kind"] in WALK_KINDS and p["status"] == "unknown")
    unknown_share = walk_unknown / walk_total if walk_total else 1.0

    contradictions = sum(1 for f in features if _has(f["properties"], "osm", "lit_no") and f["properties"]["status"] == "lit_confirmed")

    def lit_yes_street(p: dict) -> bool:
        return p["kind"] == "street" and _has(p, "osm", "lit_yes")

    tagged = _length(features, lit_yes_street)
    with_lamps = _length(features, lambda p: lit_yes_street(p) and "mapillary" in p["families"])
    recall = with_lamps / tagged if tagged else 0.0

    checks = {
        "unknown_share": round(unknown_share, 4),
        "unknown_share_ok": unknown_share <= cfg.max_unknown_share,
        "lit_no_confirmed": contradictions,
        "lit_no_confirmed_ok": contradictions == 0,
        "lamp_recall": round(recall, 4),
        "lamp_recall_ok": recall >= cfg.min_lamp_recall,
    }
    checks["passed"] = checks["unknown_share_ok"] and checks["lit_no_confirmed_ok"] and checks["lamp_recall_ok"]
    return checks


def pick_sample(features: list[dict], seed: int = SAMPLE_SEED) -> list[dict]:
    """Ten segments for the manual check: fixed seed, fixed quota per status, streets and sidewalks only."""
    rng = random.Random(seed)
    pool = [f for f in features if f["properties"]["kind"] in ("street", "sidewalk") and f["properties"]["length_m"] >= SAMPLE_MIN_LENGTH_M]
    sample = []
    for status, quota in SAMPLE_QUOTA:
        group = sorted((f for f in pool if f["properties"]["status"] == status), key=lambda f: f["properties"]["segment_id"])
        sample += rng.sample(group, min(quota, len(group)))
    return sample


def validation_markdown(sample: list[dict], as_of: str) -> str:
    lines = [
        "# Ручная проверка отрезков по панорамам Mapillary",
        "",
        f"Выборка от {as_of}, зерно {SAMPLE_SEED}. Откройте панораму в середине отрезка и запишите, видны ли фонари.",
        "Проверка пройдена, если нет отрезка со статусом `lit_confirmed`, где на панораме фонарей не видно.",
        "",
        "| № | segment_id | Улица | Статус | Панорама | Что видно | Вердикт |",
        "|---|---|---|---|---|---|---|",
    ]
    for number, feature in enumerate(sample, 1):
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]
        lon, lat = coords[len(coords) // 2]
        url = f"https://www.mapillary.com/app/?lat={lat:.6f}&lng={lon:.6f}&z=18"
        lines.append(f"| {number} | `{props['segment_id']}` | {props['name'] or '—'} | `{props['status']}` | [открыть]({url}) |  |  |")
    return "\n".join(lines) + "\n"


def print_checks(checks: dict, cfg: Config) -> None:
    rows = [
        ("unknown share on streets and sidewalks", f"{checks['unknown_share']:.1%}", f"at most {cfg.max_unknown_share:.1%}", checks["unknown_share_ok"]),
        ("segments tagged lit=no but lit_confirmed", str(checks["lit_no_confirmed"]), "0", checks["lit_no_confirmed_ok"]),
        ("Mapillary lamps on streets tagged lit=yes", f"{checks['lamp_recall']:.1%}", f"at least {cfg.min_lamp_recall:.1%}", checks["lamp_recall_ok"]),
    ]
    for name, value, limit, ok in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {value} (threshold: {limit})")
    print("GO" if checks["passed"] else "NO-GO")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the go/no-go checks on the built map.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--out-dir", type=Path, default=Path("data/out"))
    parser.add_argument("--doc", type=Path, default=Path("docs/validation.md"))
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    features = json.loads((args.out_dir / "segments.geojson").read_text(encoding="utf-8"))["features"]
    summary_path = args.out_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    checks = run_checks(features, cfg)
    summary["checks"] = checks
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print_checks(checks, cfg)

    if not args.doc.exists():  # never overwrite a sheet a person has started to fill in
        args.doc.parent.mkdir(parents=True, exist_ok=True)
        args.doc.write_text(validation_markdown(pick_sample(features), summary.get("as_of", "")), encoding="utf-8")
        print(f"manual check sheet written to {args.doc}")
    return 0 if checks["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `90 passed`.

- [ ] **Step 5: Запустить проверку на реальной сборке**

Run: `.venv/Scripts/python -m lightmap.validate; echo "exit code $?"`
Expected: три строки `PASS`, строка `GO`, строка `manual check sheet written to docs/validation.md`, `exit code 0`. Значения должны быть близки к черновой сборке: доля `unknown` около 12,8%, фонари у улиц с `lit=yes` около 62%.

- [ ] **Step 6: Commit**

```bash
git add src/lightmap/validate.py tests/test_validate.py data/out/summary.json docs/validation.md
git commit -m "feat: go/no-go checks and the manual check sheet"
```

---

### Task 10: README, лицензия, итоговая проверка

**Files:**
- Create: `README.md`, `LICENSE`

**Interfaces:**
- Consumes: команды из задач 7–9.
- Produces: репозиторий, который можно запустить по README.

- [ ] **Step 1: Написать README и лицензию**

Файл `README.md`:

````markdown
# lightmap — street-lighting confidence map (Timișoara)

Part of a UniHack 8 project (Green Mobility track): a night-time walking and cycling route planner that shows, for every street segment, how confident we are that it is lit — and says "no data" when we do not know. We never call a route "safe": we only have evidence about lighting.

This repository contains subproject 1: the confidence map for a model area, the university district south of the Bega (3.1 km²).

## Quick start

Requires Python 3.12 or newer.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # on Linux or macOS: .venv/bin/python
.venv/Scripts/python -m pytest -q                   # tests need no network
```

Put the two input files into `data/raw/` (they are not kept in git):

| File | What it is |
|---|---|
| `mapillary_street_lights.geojson` | Street lights detected by Mapillary; point features with `mapillary_id`, `first_seen`, `last_seen` |
| `sesizari_iluminat.geojson` | Lighting complaints from the Timișoara Sesizări portal; point features with `nr`, `created_at`, `subcategory`, `status`, `street`, `closed_at` |

Either file may be missing: the source is then reported as not connected and the build still runs.

```bash
.venv/Scripts/python -m lightmap.build       # downloads the street graph once, writes data/out/
.venv/Scripts/python -m lightmap.validate    # go/no-go checks, writes docs/validation.md on the first run
.venv/Scripts/python -m http.server 8000     # then open http://localhost:8000/web/
```

The page must be opened through an HTTP server. Opened as a file, it cannot load the data, and the basemap tile server refuses requests without a Referer.

## How a status is decided

Three independent sources are attached to every segment: the OSM `lit` tag of the segment itself, Mapillary street lights within 20 m, and lighting complaints snapped to the nearest street within 30 m.

| Status | Meaning |
|---|---|
| `lit_confirmed` | Direct evidence: the OSM tag `lit=yes`, or Mapillary street lights along at least half of the length |
| `lit_likely` | Only a complaint or an indirect sign: the same street is tagged elsewhere, a lit street runs alongside, or lights cover part of the segment |
| `dark_reported` | `lit=no`, an open "no lighting in the area" complaint not older than 30 days, or three or more lamps reported out |
| `unknown` | No evidence at all |

One or two lamps reported out never turn a segment dark. All radii and thresholds live in `config/lightmap.json`. The full design is in `docs/superpowers/specs/2026-11-14-lighting-confidence-map-design.md`.

## Another area, another source

- Another district or the whole city: change `area` in `config/lightmap.json`, delete `data/cache/graph.graphml` and build again.
- A city lamp registry: add a module in `src/lightmap/adapters/` that returns `Evidence` records and feed its points to the pipeline next to the Mapillary lamps. The rules do not change.

## Output

- `data/out/segments.geojson` — one line per segment with `segment_id`, `status`, `confidence` and the list of evidence behind it.
- `data/out/summary.json` — shares of length per status, source snapshot dates, and the go/no-go checks.

The router of subproject 2 must obtain the graph through `lightmap.graph.load_graph()`, so that segment ids match.

## Data sources and licences

- Code: MIT, see `LICENSE`.
- Street network: © OpenStreetMap contributors, ODbL.
- Street lights: Mapillary. Show the Mapillary logo and a link wherever the derived data is displayed: put the official logo at `web/vendor/mapillary-logo.svg` before publishing the page. Do not commit the raw export.
- Complaints: Primăria Timișoara, Sesizări. Complaint text and photos are never stored or shown; only coordinates, sub-category, status, dates, street and number are used.
- Map library: Leaflet 1.9.4 (BSD-2-Clause), bundled in `web/vendor/leaflet/`.
- Basemap tiles: openstreetmap.org. Fine for a demo; a permanent service needs its own tile source.

## Known limits

- An empty Mapillary area means "not captured", not "no lights". Image coverage is not used yet.
- A light seen on imagery or a closed complaint proves the lamp exists, not that it works tonight.
- Park and campus paths are mostly `unknown`. That is shown as it is.
````

Файл `LICENSE`:

```text
MIT License

Copyright (c) 2026 The lightmap authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Прогнать всё с нуля по README**

Run:

```bash
.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m lightmap.build --as-of 2026-11-14 && .venv/Scripts/python -m lightmap.validate; echo "exit code $?"
```

Expected: `90 passed`; таблица сборки; три строки `PASS`, `GO`, `exit code 0`. Строки `manual check sheet written` нет: лист уже существует.

- [ ] **Step 3: Проверить, что в интерфейсе нет запрещённых слов и текста жалоб**

Run:

```bash
grep -n -i -E "\b(safe|sigur|безопас)" web/app.js web/index.html web/style.css; grep -c "descriere" data/out/segments.geojson; git status --short
```

Expected: первая команда ничего не печатает (слово `safe` встречается только в комментарии `web/i18n.js`, этот файл в проверку не входит); вторая печатает `0`; `git status` показывает только `README.md`, `LICENSE` и изменённый `data/out/summary.json`, если менялось время сборки.

- [ ] **Step 4: Commit**

```bash
git add README.md LICENSE data/out/segments.geojson data/out/summary.json
git commit -m "docs: README and MIT licence; final build of the model area"
```

- [ ] **Step 5: Передать человеку ручную проверку**

Откройте `docs/validation.md` и попросите человека из команды заполнить колонки «Что видно» и «Вердикт» по ссылкам на панорамы. Это проверка 4 из спецификации; без неё решение go/no-go не окончательное. Заодно попросите носителя румынского проверить тексты в `web/i18n.js` и положить логотип Mapillary в `web/vendor/mapillary-logo.svg`.
