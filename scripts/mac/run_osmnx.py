"""Run a handoff osmnx script (draft_map.py, dryrun.py) with Overpass mirror fallback, without editing it.

usage: python -I run_osmnx.py <script.py> [script args...]
The public Overpass server often answers 502/504 when busy. This wrapper points osmnx at one mirror,
runs the script, and on an Overpass/network error tries the next mirror after a pause. The scripts
download the graph before they write anything, so a retry is safe. osmnx keeps the successful
response in the cache folder, so later runs work offline. Force one server with OVERPASS_URL=...
"""
import os
import runpy
import sys
import time

import osmnx as ox
import requests
from osmnx._errors import ResponseStatusCodeError

MIRRORS = [
    "https://overpass-api.de/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]
ROUNDS = 2
PAUSE_SEC = 20


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    script, args = sys.argv[1], sys.argv[2:]
    mirrors = [os.environ["OVERPASS_URL"]] if os.environ.get("OVERPASS_URL") else MIRRORS
    errors = (ResponseStatusCodeError, requests.exceptions.RequestException)
    attempt = 0
    for _ in range(ROUNDS):
        for url in mirrors:
            attempt += 1
            ox.settings.overpass_url = url
            ox.settings.overpass_rate_limit = url == MIRRORS[0]  # /status exists reliably only on the main server
            print(f"[run_osmnx] attempt {attempt}: Overpass {url}", flush=True)
            sys.argv = [script, *args]
            try:
                runpy.run_path(script, run_name="__main__")
                return
            except errors as e:
                print(f"[run_osmnx] Overpass failed: {str(e).splitlines()[0][:200]}", flush=True)
                time.sleep(PAUSE_SEC)
    sys.exit("[run_osmnx] all Overpass servers failed; try again later or ask Timur for his osmnx cache folder")


if __name__ == "__main__":
    main()
