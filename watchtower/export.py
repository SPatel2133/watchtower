"""GeoJSON export for the Global View (web/globe): recent hotspots and cameras with their health."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from watchtower.config import CameraConfig, Settings
from watchtower.db import Database

HOTSPOT_FIELDS = ("source", "satellite", "acq_datetime_utc", "confidence_label", "frp", "daynight")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)  # the globe may be fetching the file right now: never let it read half of one


def _point(lon: float, lat: float, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def export_globe_data(
    db: Database, settings: Settings, cameras: list[CameraConfig], hours: int = 24, now: datetime | None = None
) -> tuple[int, int]:
    """Write hotspots.geojson and cameras.geojson into settings.globe_data_dir. Returns (hotspots, cameras)."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hotspots = [
        _point(h["lon"], h["lat"], {k: h[k] for k in HOTSPOT_FIELDS}) for h in db.hotspots_since(since)
    ]
    health = db.all_health()
    cams = [
        _point(
            c.lon,
            c.lat,
            {
                "id": c.id,
                "name": c.name,
                "source_network": c.source_network,
                "status": health[c.id].status if c.id in health else "unknown",
            },
        )
        for c in cameras
    ]
    out = settings.globe_data_dir
    _write_json(out / "hotspots.geojson", {"type": "FeatureCollection", "generated_at": stamp, "hours": hours, "features": hotspots})
    _write_json(out / "cameras.geojson", {"type": "FeatureCollection", "generated_at": stamp, "features": cams})
    return len(hotspots), len(cams)
