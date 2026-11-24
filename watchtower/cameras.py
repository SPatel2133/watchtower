"""Camera still-frame ingestion with a pluggable source layer, SHA-256 dedup and health tracking."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

import requests
from PIL import Image, UnidentifiedImageError

from watchtower.config import CameraConfig, Settings
from watchtower.db import CameraHealth, Database

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class CameraFetchError(Exception):
    pass


@dataclass(frozen=True)
class Frame:
    content: bytes
    content_type: str


class CameraSource(Protocol):
    """A source returns the current still frame for a camera. Add new networks by registering one."""

    def fetch(self, camera: CameraConfig) -> Frame: ...


class HttpStillSource:
    """Plain HTTP(S) GET of a 'latest frame' URL."""

    def __init__(self, session: requests.Session, timeout: float) -> None:
        self.session = session
        self.timeout = timeout

    def fetch(self, camera: CameraConfig) -> Frame:
        try:
            resp = self.session.get(camera.image_url, timeout=self.timeout, stream=True)
        except requests.RequestException as exc:
            raise CameraFetchError(f"{type(exc).__name__}: {exc}") from None
        with resp:
            if resp.status_code != 200:
                raise CameraFetchError(f"HTTP {resp.status_code}")
            content = resp.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
        if len(content) > MAX_IMAGE_BYTES:
            raise CameraFetchError("image larger than 20 MB")
        return Frame(content, resp.headers.get("Content-Type", ""))


class LocalFileSource:
    """Reads file:// URLs. A directory URL cycles through its images, one per fetch (for demos/tests)."""

    def __init__(self) -> None:
        self._positions: dict[str, int] = {}

    def fetch(self, camera: CameraConfig) -> Frame:
        path = Path(unquote(urlparse(camera.image_url).path))
        if path.is_dir():
            images = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if not images:
                raise CameraFetchError(f"no images in {path}")
            pos = self._positions.get(camera.id, 0)
            self._positions[camera.id] = pos + 1
            path = images[pos % len(images)]
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise CameraFetchError(f"{type(exc).__name__}: {exc}") from None
        suffix = path.suffix.lower().lstrip(".")
        return Frame(content, f"image/{'jpeg' if suffix == 'jpg' else suffix}")


SourceFactory = Callable[[Settings, requests.Session], CameraSource]
SOURCE_TYPES: dict[str, SourceFactory] = {
    "http": lambda settings, session: HttpStillSource(session, settings.http_timeout),
    "file": lambda settings, session: LocalFileSource(),
}


def register_source(name: str, factory: SourceFactory) -> None:
    SOURCE_TYPES[name] = factory


def to_jpeg(frame: Frame) -> bytes:
    """Validate that the payload is a real image and return JPEG bytes (unchanged if already JPEG)."""
    if not frame.content_type.lower().startswith("image/"):
        raise CameraFetchError(f"unexpected content type {frame.content_type or '<none>'!r}")
    try:
        with Image.open(io.BytesIO(frame.content)) as img:
            img.verify()
        with Image.open(io.BytesIO(frame.content)) as img:
            img.load()
            if img.format == "JPEG":
                return frame.content
            out = io.BytesIO()
            img.convert("RGB").save(out, format="JPEG", quality=90)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise CameraFetchError(f"payload is not a decodable image: {exc}") from None


def compute_status(health: CameraHealth, settings: Settings) -> str:
    if health.consecutive_failures >= settings.failing_after:
        return "failing"
    if health.consecutive_identical_frames >= settings.stale_after:
        return "stale"
    return "ok"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CameraResult:
    camera_id: str
    outcome: str  # saved | identical | failed | skipped
    detail: str = ""


@dataclass
class CameraIngestor:
    db: Database
    settings: Settings
    session: requests.Session
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    _sources: dict[str, CameraSource] = field(default_factory=dict)
    _last_attempt: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def source_for(self, camera: CameraConfig) -> CameraSource:
        if camera.source_type not in self._sources:
            factory = SOURCE_TYPES.get(camera.source_type)
            if factory is None:
                raise CameraFetchError(f"unknown source_type {camera.source_type!r}")
            self._sources[camera.source_type] = factory(self.settings, self.session)
        return self._sources[camera.source_type]

    def process(self, camera: CameraConfig) -> CameraResult:
        last = self._last_attempt.get(camera.id)
        if last is not None and time.monotonic() - last < camera.min_interval_seconds:
            return CameraResult(camera.id, "skipped", "min_interval_seconds not elapsed")
        self._last_attempt[camera.id] = time.monotonic()

        health = self.db.get_health(camera.id) or CameraHealth(camera_id=camera.id)
        now = self.now()
        try:
            frame = self.source_for(camera).fetch(camera)
            jpeg = to_jpeg(frame)
        except CameraFetchError as exc:
            health.consecutive_failures += 1
            health.last_error = str(exc)[:500]
            health.last_error_at = _iso(now)
            health.status = compute_status(health, self.settings)
            self.db.save_health(health)
            log.warning("camera %s failed (%d in a row): %s", camera.id, health.consecutive_failures, exc)
            return CameraResult(camera.id, "failed", str(exc))

        digest = hashlib.sha256(frame.content).hexdigest()
        health.consecutive_failures = 0
        health.last_success_at = _iso(now)
        if digest == health.last_sha256:
            health.consecutive_identical_frames += 1
            outcome = "identical"
        else:
            self._save_frame(camera, now, jpeg, digest)
            health.consecutive_identical_frames = 0
            health.last_sha256 = digest
            outcome = "saved"
        previous = health.status
        health.status = compute_status(health, self.settings)
        self.db.save_health(health)
        if health.status != previous:
            log.info("camera %s status %s -> %s", camera.id, previous, health.status)
        log.debug("camera %s: %s (%s)", camera.id, outcome, digest[:12])
        return CameraResult(camera.id, outcome, digest)

    def _save_frame(self, camera: CameraConfig, now: datetime, jpeg: bytes, digest: str) -> None:
        stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cam_dir = self.settings.frames_dir / camera.id
        cam_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = cam_dir / f"{stamp}.jpg"
            n = 1
            while target.exists():
                target = cam_dir / f"{stamp}_{n}.jpg"
                n += 1
            tmp = target.with_suffix(".jpg.part")
            tmp.write_bytes(jpeg)
            os.replace(tmp, target)
        rel = target.relative_to(self.settings.data_dir).as_posix()
        try:
            self.db.insert_frame(camera.id, _iso(now), rel, digest, len(jpeg))
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def run(self, cameras: list[CameraConfig]) -> list[CameraResult]:
        results = []
        for camera in cameras:
            try:
                results.append(self.process(camera))
            except Exception as exc:  # noqa: BLE001 - one camera must never break the cycle
                log.exception("camera %s: unexpected error", camera.id)
                results.append(CameraResult(camera.id, "failed", str(exc)))
        return results
