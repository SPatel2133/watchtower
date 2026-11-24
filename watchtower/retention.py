"""Frame retention: delete old frame files and their rows, skipping frames flagged keep."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watchtower.db import Database

log = logging.getLogger(__name__)


@dataclass
class RetentionResult:
    deleted_rows: int = 0
    deleted_files: int = 0
    missing_files: int = 0
    errors: int = 0


def prune_frames(
    db: Database, data_dir: Path, retention_hours: float, now: datetime | None = None, batch: int = 1000
) -> RetentionResult:
    """Delete frames captured more than retention_hours ago unless keep is set. retention_hours <= 0 disables."""
    result = RetentionResult()
    if retention_hours <= 0:
        return result
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=retention_hours)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    frames_root = (data_dir / "frames").resolve()
    failed: set[int] = set()
    while True:
        rows = [r for r in db.prunable_frames(cutoff, limit=batch + len(failed)) if r.id not in failed]
        if not rows:
            break
        deletable: list[int] = []
        for row in rows[:batch]:
            path = (data_dir / row.path).resolve()
            if not path.is_relative_to(frames_root):
                log.error("retention: refusing to delete %s outside %s", path, frames_root)
                failed.add(row.id)
                result.errors += 1
                continue
            try:
                path.unlink()
                result.deleted_files += 1
            except FileNotFoundError:
                result.missing_files += 1
            except OSError as exc:
                log.error("retention: could not delete %s: %s", path, exc)
                failed.add(row.id)
                result.errors += 1
                continue
            deletable.append(row.id)
        result.deleted_rows += db.delete_frames(deletable)
        if not deletable:
            break
    if result.deleted_rows or result.errors:
        log.info(
            "retention: removed %d frames older than %s (%d files already missing, %d errors)",
            result.deleted_rows, cutoff, result.missing_files, result.errors,
        )
    return result
