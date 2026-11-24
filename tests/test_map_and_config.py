from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from tests.conftest import FIXTURES
from watchtower.config import ConfigError, load_cameras, parse_bbox
from watchtower.db import CameraHealth
from watchtower.firms import parse_csv
from watchtower.map import build_map

CAMS_YAML = """
cameras:
  - id: cam-a
    name: "Cam </script><b>A</b>"
    image_url: https://example.org/a.jpg
    lat: 50.1
    lon: -120.2
    bearing_deg: 90
    source_network: test
  - id: cam_b
    name: Cam B
    image_url: https://example.org/b.jpg
    lat: 51
    lon: -121
    source_network: test
    enabled: false
"""


def test_load_cameras(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(CAMS_YAML)
    cams = load_cameras(path)
    assert [c.id for c in cams] == ["cam-a"]
    assert cams[0].bearing_deg == 90.0 and cams[0].source_type == "http"
    assert len(load_cameras(path, include_disabled=True)) == 2


@pytest.mark.parametrize(
    "yaml_text",
    [
        "cameras:\n  - id: x\n    name: y\n",
        "cameras:\n  - {id: a, name: n, image_url: u, lat: 1, lon: 1, source_network: s}\n"
        "  - {id: a, name: n, image_url: u, lat: 1, lon: 1, source_network: s}\n",
        "cameras:\n  - {id: ../evil, name: n, image_url: u, lat: 1, lon: 1, source_network: s}\n",
        "nope: 1\n",
    ],
)
def test_bad_camera_config(tmp_path, yaml_text):
    path = tmp_path / "c.yaml"
    path.write_text(yaml_text)
    with pytest.raises(ConfigError):
        load_cameras(path)


def test_repo_camera_config_is_valid():
    cams = load_cameras(FIXTURES.parent.parent / "config" / "cameras.yaml", include_disabled=True)
    assert len({c.id for c in cams}) == len(cams)


def test_parse_bbox():
    assert parse_bbox("-141,41.7,-52.6,83.1") == (-141.0, 41.7, -52.6, 83.1)
    with pytest.raises(ConfigError):
        parse_bbox("1,2,3")
    with pytest.raises(ConfigError):
        parse_bbox("10,0,5,1")


def test_map_contains_recent_hotspots_and_camera_health(tmp_path, db, settings):
    path = tmp_path / "c.yaml"
    path.write_text(CAMS_YAML)
    cams = load_cameras(path)
    db.insert_hotspots(parse_csv((FIXTURES / "firms_modis.csv").read_text(), "MODIS_NRT", "x"))
    db.save_health(CameraHealth(camera_id="cam-a", status="stale"))
    out = build_map(db, settings, cams, hours=24, now=datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc))
    html = out.read_text()
    assert "leaflet@1.9.4" in html
    assert "</script><b>" not in html
    data = json.loads(re.search(r"const DATA = (.*);\n", html).group(1).replace("<\\/", "</"))
    assert len(data["hotspots"]) == 6
    assert data["cameras"][0]["status"] == "stale"
    old = build_map(db, settings, cams, hours=24, now=datetime(2026, 11, 25, tzinfo=timezone.utc)).read_text()
    assert '"hotspots":[]' in old


def test_map_links_latest_camera_frame(tmp_path, db, settings):
    path = tmp_path / "c.yaml"
    path.write_text(CAMS_YAML)
    db.insert_frame("cam-a", "2026-11-24T01:00:00Z", "frames/cam-a/old.jpg", "h1", 1)
    db.insert_frame("cam-a", "2026-11-24T02:00:00Z", "frames/cam-a/new.jpg", "h2", 1)
    html = build_map(db, settings, load_cameras(path), now=datetime(2026, 11, 24, 3, tzinfo=timezone.utc)).read_text()
    data = json.loads(re.search(r"const DATA = (.*);\n", html).group(1).replace("<\\/", "</"))
    assert data["cameras"][0]["latest_frame"] == "frames/cam-a/new.jpg"
    assert data["cameras"][0]["latest_frame_at"] == "2026-11-24T02:00:00Z"
