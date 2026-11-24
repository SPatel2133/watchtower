"""Settings from environment variables (optionally a .env file) and the camera list from YAML."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from watchtower import __version__

USER_AGENT = f"Watchtower/{__version__} (wildfire data ingestion; +https://github.com/SPatel2133/watchtower)"

Bbox = tuple[float, float, float, float]

DEFAULT_BBOX: Bbox = (-141.0, 41.7, -52.6, 83.1)
DEFAULT_FIRMS_SOURCES: tuple[str, ...] = (
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CameraConfig:
    id: str
    name: str
    image_url: str
    lat: float
    lon: float
    source_network: str
    bearing_deg: float | None = None
    source_type: str = "http"
    enabled: bool = True
    min_interval_seconds: int = 0
    license: str | None = None
    attribution: str | None = None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cameras_file: Path
    firms_map_key: str | None
    bbox: Bbox
    firms_sources: tuple[str, ...]
    frame_retention_hours: float
    stale_after: int
    failing_after: int
    http_timeout: float
    http_retries: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "watchtower.db"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    @property
    def map_path(self) -> Path:
        return self.data_dir / "map.html"


def parse_bbox(value: str) -> Bbox:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise ConfigError(f"bbox must be 'west,south,east,north', got {value!r}")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as exc:
        raise ConfigError(f"bbox values must be numbers, got {value!r}") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ConfigError(f"bbox out of range or inverted: {value!r}")
    return (west, south, east, north)


def _env_number(env: Mapping[str, str], name: str, default: float, cast: type = float) -> Any:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return cast(default)
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        load_dotenv()
        env = os.environ
    sources = env.get("FIRMS_SOURCES")
    firms_sources = (
        tuple(s.strip() for s in sources.split(",") if s.strip()) if sources else DEFAULT_FIRMS_SOURCES
    )
    bbox_raw = env.get("WATCHTOWER_BBOX")
    return Settings(
        data_dir=Path(env.get("WATCHTOWER_DATA_DIR", "data")),
        cameras_file=Path(env.get("WATCHTOWER_CAMERAS_FILE", "config/cameras.yaml")),
        firms_map_key=(env.get("FIRMS_MAP_KEY") or "").strip() or None,
        bbox=parse_bbox(bbox_raw) if bbox_raw else DEFAULT_BBOX,
        firms_sources=firms_sources,
        frame_retention_hours=_env_number(env, "FRAME_RETENTION_HOURS", 72),
        stale_after=_env_number(env, "CAMERA_STALE_AFTER", 10, int),
        failing_after=_env_number(env, "CAMERA_FAILING_AFTER", 3, int),
        http_timeout=_env_number(env, "HTTP_TIMEOUT_SECONDS", 20),
        http_retries=_env_number(env, "HTTP_RETRIES", 3, int),
    )


_REQUIRED_CAMERA_FIELDS = ("id", "name", "image_url", "lat", "lon", "source_network")


def load_cameras(path: Path, include_disabled: bool = False) -> list[CameraConfig]:
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    entries = doc.get("cameras") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: expected a top-level 'cameras' list")
    cameras: list[CameraConfig] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: camera #{i} is not a mapping")
        missing = [f for f in _REQUIRED_CAMERA_FIELDS if entry.get(f) in (None, "")]
        if missing:
            raise ConfigError(f"{path}: camera #{i} missing {', '.join(missing)}")
        cam_id = str(entry["id"])
        if not cam_id.replace("-", "").replace("_", "").isalnum():
            raise ConfigError(f"{path}: camera id {cam_id!r} must be letters, digits, '-' or '_'")
        if cam_id in seen:
            raise ConfigError(f"{path}: duplicate camera id {cam_id!r}")
        seen.add(cam_id)
        bearing = entry.get("bearing_deg")
        camera = CameraConfig(
            id=cam_id,
            name=str(entry["name"]),
            image_url=str(entry["image_url"]),
            lat=float(entry["lat"]),
            lon=float(entry["lon"]),
            source_network=str(entry["source_network"]),
            bearing_deg=float(bearing) if bearing is not None else None,
            source_type=str(entry.get("source_type", "http")),
            enabled=bool(entry.get("enabled", True)),
            min_interval_seconds=int(entry.get("min_interval_seconds", 0)),
            license=entry.get("license"),
            attribution=entry.get("attribution"),
        )
        if camera.enabled or include_disabled:
            cameras.append(camera)
    return cameras


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    # urllib3 debug logs include full request URLs, and FIRMS URLs embed the MAP_KEY.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
