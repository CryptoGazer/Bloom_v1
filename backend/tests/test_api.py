"""HTTP edges of backend/app.py that need no city data. Run: .venv/bin/python -m pytest backend/tests -q"""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def test_a_bbox_with_nan_is_a_422_not_a_500(tmp_path: Path):
    with TestClient(create_app(tmp_path / "missing.geojson.gz")) as client:
        r = client.get("/api/segments?bbox=21,nan,22,46")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_bbox"
