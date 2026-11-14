"""usage: python -I html_probe.py <file.html>  -- prints title, script/link URLs and tech keywords only"""
import sys, re
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
print("len", len(t))
print("title:", re.findall(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)[:2])
print("meta generator:", re.findall(r'<meta[^>]+generator[^>]*>', t, re.I)[:3])
print("scripts:", re.findall(r'<script[^>]+src=["\']([^"\']+)', t, re.I)[:40])
print("links:", re.findall(r'<link[^>]+href=["\']([^"\']+)', t, re.I)[:30])
print("iframes:", re.findall(r'<iframe[^>]+src=["\']([^"\']+)', t, re.I)[:10])
kw = ["arcgis", "esri", "geoserver", "qgis", "qwc", "lizmap", "openlayers", "leaflet", "mapbox", "maplibre", "wms", "wfs", "wmts", "mapserver", "FeatureServer", "MapServer", "portal", "webmap", "experience", "geoportal", "iluminat", "stalp", "stâlp", "corpuri", "layer", "strat", "config", "next", "nuxt", "angular", "react", "vite"]
low = t.lower()
print("keyword counts:", {k: low.count(k.lower()) for k in kw if low.count(k.lower())})
urls = Counter(re.findall(r'https?://[^\s"\'<>\)]+', t))
print("absolute URLs:", list(urls.items())[:60])
for k in ("iluminat", "stalp", "stâlp", "corpuri"):
    for m in re.finditer(k, low):
        print("  ctx[%s]:" % k, t[max(0, m.start() - 80): m.end() + 80].replace("\n", " "))
print("body text sample (tags stripped, 600 chars):", re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", t, flags=re.S | re.I))[:600])
