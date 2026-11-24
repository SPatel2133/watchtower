"""SQLite storage. All SQL lives here so the backend can later move to Postgres/PostGIS."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotspots (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    satellite TEXT,
    instrument TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    acq_datetime_utc TEXT NOT NULL,
    confidence_label TEXT NOT NULL,
    confidence_raw TEXT,
    frp REAL,
    daynight TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hotspots_acq ON hotspots (acq_datetime_utc);

CREATE TABLE IF NOT EXISTS camera_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    keep INTEGER
);
CREATE INDEX IF NOT EXISTS idx_frames_camera_time ON camera_frames (camera_id, captured_at_utc);
CREATE INDEX IF NOT EXISTS idx_frames_time ON camera_frames (captured_at_utc);

CREATE TABLE IF NOT EXISTS camera_health (
    camera_id TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_error TEXT,
    last_error_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_identical_frames INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'failing', 'stale')),
    last_sha256 TEXT
);
"""


@dataclass(frozen=True)
class Hotspot:
    id: str
    source: str
    satellite: str | None
    instrument: str | None
    lat: float
    lon: float
    acq_datetime_utc: str
    confidence_label: str
    confidence_raw: str | None
    frp: float | None
    daynight: str | None
    fetched_at: str


@dataclass
class CameraHealth:
    camera_id: str
    last_success_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    consecutive_failures: int = 0
    consecutive_identical_frames: int = 0
    status: str = "ok"
    last_sha256: str | None = None


@dataclass(frozen=True)
class FrameRow:
    id: int
    camera_id: str
    captured_at_utc: str
    path: str
    sha256: str
    size_bytes: int
    keep: int | None


_HOTSPOT_COLUMNS = tuple(Hotspot.__dataclass_fields__)
_HEALTH_COLUMNS = tuple(CameraHealth.__dataclass_fields__)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(camera_frames)")}
            if "keep" not in cols:
                self.conn.execute("ALTER TABLE camera_frames ADD COLUMN keep INTEGER")
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(camera_health)")}
            if "last_sha256" not in cols:
                self.conn.execute("ALTER TABLE camera_health ADD COLUMN last_sha256 TEXT")

    # hotspots
    def insert_hotspots(self, hotspots: Iterable[Hotspot]) -> int:
        rows = [tuple(getattr(h, c) for c in _HOTSPOT_COLUMNS) for h in hotspots]
        if not rows:
            return 0
        sql = (
            f"INSERT OR IGNORE INTO hotspots ({', '.join(_HOTSPOT_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _HOTSPOT_COLUMNS)})"
        )
        with self.conn:
            before = self.conn.total_changes
            self.conn.executemany(sql, rows)
            return self.conn.total_changes - before

    def count_hotspots(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM hotspots").fetchone()[0])

    def hotspots_since(self, since_utc: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM hotspots WHERE acq_datetime_utc >= ? ORDER BY acq_datetime_utc",
            (since_utc,),
        )
        return [dict(r) for r in cur]

    # camera frames
    def insert_frame(
        self,
        camera_id: str,
        captured_at_utc: str,
        path: str,
        sha256: str,
        size_bytes: int,
        keep: bool | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO camera_frames (camera_id, captured_at_utc, path, sha256, size_bytes, keep) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (camera_id, captured_at_utc, path, sha256, size_bytes, None if keep is None else int(keep)),
            )
            return int(cur.lastrowid)

    def set_frame_keep(self, frame_id: int, keep: bool | None = True) -> None:
        """Mark a frame to be kept by retention (e.g. when a later phase links it to a detection)."""
        with self.conn:
            self.conn.execute(
                "UPDATE camera_frames SET keep = ? WHERE id = ?",
                (None if keep is None else int(keep), frame_id),
            )

    def frames(self, camera_id: str | None = None) -> list[FrameRow]:
        sql = "SELECT * FROM camera_frames"
        args: tuple[Any, ...] = ()
        if camera_id is not None:
            sql += " WHERE camera_id = ?"
            args = (camera_id,)
        return [FrameRow(**dict(r)) for r in self.conn.execute(sql + " ORDER BY id", args)]

    def prunable_frames(self, cutoff_utc: str, limit: int = 1000) -> list[FrameRow]:
        cur = self.conn.execute(
            "SELECT * FROM camera_frames WHERE captured_at_utc < ? AND (keep IS NULL OR keep = 0) "
            "ORDER BY captured_at_utc LIMIT ?",
            (cutoff_utc, limit),
        )
        return [FrameRow(**dict(r)) for r in cur]

    def delete_frames(self, frame_ids: Sequence[int]) -> int:
        if not frame_ids:
            return 0
        with self.conn:
            before = self.conn.total_changes
            self.conn.executemany(
                "DELETE FROM camera_frames WHERE id = ? AND (keep IS NULL OR keep = 0)",
                [(i,) for i in frame_ids],
            )
            return self.conn.total_changes - before

    # camera health
    def get_health(self, camera_id: str) -> CameraHealth | None:
        row = self.conn.execute("SELECT * FROM camera_health WHERE camera_id = ?", (camera_id,)).fetchone()
        return CameraHealth(**dict(row)) if row else None

    def save_health(self, health: CameraHealth) -> None:
        values = asdict(health)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _HEALTH_COLUMNS if c != "camera_id")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO camera_health ({', '.join(_HEALTH_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _HEALTH_COLUMNS)}) "
                f"ON CONFLICT(camera_id) DO UPDATE SET {updates}",
                tuple(values[c] for c in _HEALTH_COLUMNS),
            )

    def all_health(self) -> dict[str, CameraHealth]:
        return {r["camera_id"]: CameraHealth(**dict(r)) for r in self.conn.execute("SELECT * FROM camera_health")}


def open_db(path: Path | str) -> Database:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    db.init_schema()
    return db
