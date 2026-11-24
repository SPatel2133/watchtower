from __future__ import annotations

import sqlite3

from tests.conftest import FIXTURES
from watchtower.db import Database, open_db
from watchtower.firms import parse_csv


def test_hotspot_insert_is_idempotent(db):
    rows = parse_csv((FIXTURES / "firms_modis.csv").read_text(), "MODIS_NRT", "2026-11-24T04:00:00Z")
    assert db.insert_hotspots(rows) == 6
    later = parse_csv((FIXTURES / "firms_modis.csv").read_text(), "MODIS_NRT", "2026-11-24T05:00:00Z")
    assert db.insert_hotspots(later) == 0
    assert db.count_hotspots() == 6
    assert db.insert_hotspots([]) == 0


def test_keep_column_is_nullable_and_settable(db):
    fid = db.insert_frame("cam", "2026-11-24T00:00:00Z", "frames/cam/a.jpg", "abc", 10)
    assert db.frames()[0].keep is None
    db.set_frame_keep(fid)
    assert db.frames()[0].keep == 1


def test_migrates_old_camera_frames_without_keep(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE camera_frames (id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL,"
        " captured_at_utc TEXT NOT NULL, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL);"
        "INSERT INTO camera_frames (camera_id, captured_at_utc, path, sha256, size_bytes)"
        " VALUES ('cam', '2026-01-01T00:00:00Z', 'frames/cam/x.jpg', 'h', 1);"
    )
    conn.commit()
    conn.close()
    with open_db(path) as db:
        assert db.frames()[0].keep is None
    with Database(path) as db:
        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(camera_frames)")}
    assert "keep" in cols
