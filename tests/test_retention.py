from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from watchtower.retention import prune_frames

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def make_frame(db, settings, name: str, age_hours: float, keep=None) -> tuple[int, object]:
    captured = (NOW - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rel = f"frames/cam1/{name}.jpg"
    path = settings.data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"jpeg")
    fid = db.insert_frame("cam1", captured, rel, name, 4, keep=keep)
    return fid, path


def test_retention_deletes_old_frames_and_rows_but_skips_keep(db, settings):
    _, old = make_frame(db, settings, "old", 73)
    _, very_old = make_frame(db, settings, "very_old", 500)
    kept_id, kept = make_frame(db, settings, "kept", 500, keep=True)
    late_kept_id, late_kept = make_frame(db, settings, "late_kept", 100)
    db.set_frame_keep(late_kept_id)
    _, explicit_false = make_frame(db, settings, "explicit_false", 100, keep=False)
    _, recent = make_frame(db, settings, "recent", 71)

    result = prune_frames(db, settings.data_dir, settings.frame_retention_hours, now=NOW)

    assert result.deleted_rows == 3
    assert result.deleted_files == 3
    assert not old.exists() and not very_old.exists() and not explicit_false.exists()
    assert kept.exists() and late_kept.exists() and recent.exists()
    remaining = {f.sha256: f.keep for f in db.frames()}
    assert remaining == {"kept": 1, "late_kept": 1, "recent": None}
    assert kept_id in {f.id for f in db.frames()}

    again = prune_frames(db, settings.data_dir, settings.frame_retention_hours, now=NOW)
    assert again.deleted_rows == 0


def test_retention_default_is_72_hours(monkeypatch):
    from watchtower.config import load_settings

    assert load_settings({}).frame_retention_hours == 72
    assert load_settings({"FRAME_RETENTION_HOURS": "6"}).frame_retention_hours == 6


def test_retention_removes_row_when_file_already_missing(db, settings):
    _, path = make_frame(db, settings, "gone", 80)
    path.unlink()
    result = prune_frames(db, settings.data_dir, 72, now=NOW)
    assert (result.deleted_rows, result.missing_files) == (1, 1)
    assert db.frames() == []


def test_retention_keeps_row_when_file_cannot_be_deleted(db, settings, monkeypatch):
    _, path = make_frame(db, settings, "locked", 80)
    real_unlink = type(path).unlink

    def failing_unlink(self, *a, **kw):
        if self.name == "locked.jpg":
            raise PermissionError("busy")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(type(path), "unlink", failing_unlink)
    result = prune_frames(db, settings.data_dir, 72, now=NOW)
    assert (result.deleted_rows, result.errors) == (0, 1)
    assert len(db.frames()) == 1


def test_retention_refuses_paths_outside_frames_dir(db, settings):
    outside = settings.data_dir / "watchtower_backup.txt"
    outside.write_text("x")
    db.insert_frame("cam1", "2020-01-01T00:00:00Z", "../" + os.path.relpath(outside, settings.data_dir.parent), "h", 1)
    result = prune_frames(db, settings.data_dir, 72, now=NOW)
    assert result.errors == 1
    assert outside.exists()


def test_retention_disabled_with_zero(db, settings):
    _, path = make_frame(db, settings, "old", 1000)
    assert prune_frames(db, settings.data_dir, 0, now=NOW).deleted_rows == 0
    assert path.exists()


def test_retention_continues_past_undeletable_batch(db, settings, monkeypatch):
    for i in range(3):
        make_frame(db, settings, f"stuck{i}", 200)
    _, deletable = make_frame(db, settings, "ok", 100)
    real_unlink = type(deletable).unlink

    def failing_unlink(self, *a, **kw):
        if self.name.startswith("stuck"):
            raise PermissionError("busy")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(type(deletable), "unlink", failing_unlink)
    result = prune_frames(db, settings.data_dir, 72, now=NOW, batch=2)
    assert (result.deleted_rows, result.errors) == (1, 3)
    assert not deletable.exists()
