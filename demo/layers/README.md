# Дополнительные слои карты из `unihack-data`

Добавлено 14.11.2026. Четыре слоя по всему городу, которые включаются галочками в панели слоёв на обеих страницах: на карте освещённости (`data/out/draft-map.html`) и в демо маршрута (`demo/route/`).

| Слой | Что показывает | Откуда |
|---|---|---|
| Велодорожки по городу | отдельные велодорожки, велополосы и тротуары с разрешённым велосипедом (фиолетовая обводка). Цвет линии — освещение: тег OSM `lit` или фонари Mapillary в 20 м на половине длины | `osm_highways.geojson`, `mapillary_street_lights.geojson` |
| Остановки: последние рейсы ночью | 890 остановок; по нажатию — линии, последние отправления по каждой линии и число отправлений после 22:00 на сб 14.11, вс 15.11, пн 16.11 | GTFS: v4.31 на 14–15.11, v4.32 с 16.11 |
| Линии транспорта | геометрия 116 направлений в цветах линий | `transit_routes.geojson` (API мэрии) |
| Районы | 40 районов; подпись — доля улиц района, у которых есть хоть одно свидетельство освещения | `city_zones.geojson`, `coverage_by_zone.csv` |

Сводка по велодорожкам на срезе 14.11.2026:
- отдельные велодорожки — 37,8 км, освещение подтверждено у 20%, в OSM отмечено «не освещено» у 13%;
- тротуары и дорожки с разрешённым велосипедом — 101,3 км, подтверждено у 70%;
- велополосы на улицах — 2,7 км, подтверждено у 78%.

## Как собрать и открыть

```bash
./scripts/mac/lightmap.sh draft    # карта освещённости + эти слои + данные демо маршрута
./scripts/mac/lightmap.sh layers   # только слои
./scripts/mac/lightmap.sh serve
```

Адреса для проверки:
- карта освещённости: http://localhost:8000/data/out/draft-map.html
- демо маршрута: http://localhost:8000/demo/route/

Параметр `?layers=bike,stops,routes,zones` в адресе сразу включает нужные слои, например http://localhost:8000/demo/route/?layers=bike,stops

## Файлы

| Файл | Что это |
|---|---|
| `demo/layers/build_layers.py` | собирает `data/out/layers/*.geojson` и `meta.json` из `unihack-data` |
| `demo/layers/layers.js` | рисует слои; `ExtraLayers.add(map, layerControl, baseUrl)` |
| `handoff/scripts/draft_map_template.html` | три строки: подключение `layers.js`, переменная `layerCtl`, вызов `ExtraLayers.add` |
| `demo/route/index.html`, `route.js` | подключение `layers.js` и панели слоёв, маршрут поверх слоёв |

## Как удалить

1. Удалить `demo/layers/` и `data/out/layers/`.
2. Ничего больше трогать не обязательно: обе страницы проверяют `window.ExtraLayers` и без него работают как раньше.
3. Для чистоты можно убрать строку `<script src="../../demo/layers/layers.js">` из шаблона и `<script src="../layers/layers.js">` из `demo/route/index.html`.
