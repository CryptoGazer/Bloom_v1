"""usage: python -I bundle_probe.py <bundle.js> -- keyword counts, URL literals, API path literals"""
import sys, re
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
low = t.lower()
print("len", len(t))
kw = ["arcgis", "esri", "geoserver", "qgis", "lizmap", "openlayers", "ol/", "leaflet", "mapbox", "maplibre", "deck.gl", "cesium", "wms", "wfs", "wmts", "mapserver", "featureserver", "pg_tileserv", "martin", "tegola", "mvt", "pbf", "geojson", "vector tile", "supabase", "firebase", "graphql", "hasura", "strapi", "directus", "urbis", "indeco", "iluminat", "stalp", "stâlp", "lighting", "street light", "streetlight", "lamp", "vue", "react", "pinia", "vuex", "angular", "swifter", "embed"]
print("keyword counts:", {k: low.count(k) for k in kw if low.count(k)})
urls = Counter(re.findall(r'https?://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+', t))
hosts = Counter(re.sub(r"^(https?://[^/]+).*", r"\1", u) for u in urls)
print("hosts:", hosts.most_common(60))
print("api-like path literals:", sorted(set(re.findall(r'["\'`](/?(?:api|v\d|embed|layers?|maps?|projects?|datasets?|tiles?|features?)[A-Za-z0-9_/\-${}.:]*)["\'`]', t)))[:150])
for k in ("iluminat", "lighting", "streetlight", "street light"):
    for m in list(re.finditer(k, low))[:5]:
        print("  ctx[%s]:" % k, t[max(0, m.start() - 100): m.end() + 100].replace("\n", " "))
for k in ("baseurl", "base_url", "apiurl", "api_url", "window.env"):
    for m in list(re.finditer(k, low))[:6]:
        print("  ctx[%s]:" % k, t[max(0, m.start() - 120): m.end() + 160].replace("\n", " "))
