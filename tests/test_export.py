from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from tests.conftest import FIXTURES
from watchtower.config import CameraConfig
from watchtower.db import CameraHealth
from watchtower.export import export_globe_data
from watchtower.firms import parse_csv

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def test_export_writes_recent_hotspots_and_camera_health(db, settings, tmp_path):
    settings = replace(settings, globe_data_dir=tmp_path / "globe")
    hotspots = parse_csv((FIXTURES / "firms_viirs_noaa20.csv").read_text(), "VIIRS_NOAA20_NRT", "2026-11-21T00:00:00Z")
    db.insert_hotspots(hotspots)
    cams = [
        CameraConfig(id="a", name="A", image_url="http://x/a.jpg", lat=50.0, lon=-120.0, source_network="t"),
        CameraConfig(id="b", name="B", image_url="http://x/b.jpg", lat=51.0, lon=-121.0, source_network="t"),
    ]
    db.save_health(CameraHealth(camera_id="a", status="failing", consecutive_failures=3))

    n_hot, n_cam = export_globe_data(db, settings, cams, hours=24 * 30, now=NOW)

    hot = json.loads((settings.globe_data_dir / "hotspots.geojson").read_text())
    assert hot["type"] == "FeatureCollection" and hot["generated_at"] == "2026-11-21T12:00:00Z"
    assert n_hot == len(hot["features"]) == len(hotspots)
    f = hot["features"][0]
    assert f["geometry"]["type"] == "Point" and len(f["geometry"]["coordinates"]) == 2
    assert set(f["properties"]) == {"source", "satellite", "acq_datetime_utc", "confidence_label", "frp", "daynight"}
    cam = json.loads((settings.globe_data_dir / "cameras.geojson").read_text())
    assert n_cam == 2
    assert {c["properties"]["id"]: c["properties"]["status"] for c in cam["features"]} == {"a": "failing", "b": "unknown"}
    assert cam["features"][0]["geometry"]["coordinates"] == [-120.0, 50.0]


def test_export_window_excludes_old_hotspots(db, settings, tmp_path):
    settings = replace(settings, globe_data_dir=tmp_path / "globe")
    db.insert_hotspots(parse_csv((FIXTURES / "firms_viirs_noaa20.csv").read_text(), "VIIRS_NOAA20_NRT", "2026-11-21T00:00:00Z"))
    n_hot, _ = export_globe_data(db, settings, [], hours=24, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert n_hot == 0
    assert json.loads((settings.globe_data_dir / "hotspots.geojson").read_text())["features"] == []
