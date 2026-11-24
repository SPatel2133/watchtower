"""Command line: init, hotspots, cameras, map, export, prune, watch."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from collections import Counter

from watchtower.cameras import CameraIngestor
from watchtower.config import CameraConfig, ConfigError, Settings, load_cameras, load_settings, setup_logging
from watchtower.db import open_db
from watchtower.export import export_globe_data
from watchtower.firms import fetch_hotspots
from watchtower.http import make_session
from watchtower.map import build_map
from watchtower.retention import prune_frames

log = logging.getLogger("watchtower")


def _cameras(settings: Settings) -> list[CameraConfig]:
    if not settings.cameras_file.exists():
        log.warning("camera config %s not found; no cameras loaded", settings.cameras_file)
        return []
    return load_cameras(settings.cameras_file)


def cmd_init(settings: Settings, args: argparse.Namespace) -> int:
    settings.frames_dir.mkdir(parents=True, exist_ok=True)
    with open_db(settings.db_path):
        pass
    log.info("initialized %s and %s", settings.db_path, settings.frames_dir)
    return 0


def cmd_hotspots(settings: Settings, args: argparse.Namespace) -> int:
    if not settings.firms_map_key:
        log.error("FIRMS_MAP_KEY is not set (see .env.example)")
        return 2
    with open_db(settings.db_path) as db:
        result = fetch_hotspots(db, make_session(settings.http_retries), settings, args.days)
        log.info("hotspots: %d fetched, %d new, %d total stored", result.fetched, result.inserted, db.count_hotspots())
    return 0 if len(result.errors) < len(settings.firms_sources) else 1


def cmd_cameras(settings: Settings, args: argparse.Namespace) -> int:
    cameras = _cameras(settings)
    with open_db(settings.db_path) as db:
        results = CameraIngestor(db, settings, make_session(settings.http_retries)).run(cameras)
        counts = Counter(r.outcome for r in results)
        log.info("cameras: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none configured")
    return 0 if not cameras or counts["failed"] < len(cameras) else 1


def cmd_map(settings: Settings, args: argparse.Namespace) -> int:
    with open_db(settings.db_path) as db:
        path = build_map(db, settings, _cameras(settings), hours=args.hours)
    log.info("map written to %s", path.resolve())
    return 0


def cmd_export(settings: Settings, args: argparse.Namespace) -> int:
    with open_db(settings.db_path) as db:
        n_hot, n_cam = export_globe_data(db, settings, _cameras(settings), hours=args.hours)
    log.info("export: %d hotspots, %d cameras written to %s", n_hot, n_cam, settings.globe_data_dir.resolve())
    return 0


def cmd_prune(settings: Settings, args: argparse.Namespace) -> int:
    with open_db(settings.db_path) as db:
        r = prune_frames(db, settings.data_dir, settings.frame_retention_hours)
    log.info("prune: %d rows removed, %d files deleted, %d errors", r.deleted_rows, r.deleted_files, r.errors)
    return 0 if not r.errors else 1


def cmd_watch(settings: Settings, args: argparse.Namespace) -> int:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    session = make_session(settings.http_retries)
    cameras = _cameras(settings)
    if not settings.firms_map_key:
        log.warning("FIRMS_MAP_KEY is not set; hotspot pulls will be skipped")
    deadline = time.monotonic() + args.duration if args.duration else None
    with open_db(settings.db_path) as db:
        ingestor = CameraIngestor(db, settings, session)
        next_cam = next_hot = time.monotonic()
        log.info(
            "watching %d cameras every %ss, hotspots every %ss, frame retention %sh",
            len(cameras), args.camera_interval, args.hotspot_interval, settings.frame_retention_hours,
        )
        while not stop.is_set() and (deadline is None or time.monotonic() < deadline):
            now = time.monotonic()
            if now >= next_cam:
                next_cam = now + args.camera_interval
                try:
                    results = ingestor.run(cameras)
                    counts = Counter(r.outcome for r in results)
                    log.info("camera cycle: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no cameras")
                except Exception:
                    log.exception("camera cycle failed")
                try:
                    prune_frames(db, settings.data_dir, settings.frame_retention_hours)
                except Exception:
                    log.exception("frame retention failed")
            if now >= next_hot:
                next_hot = now + args.hotspot_interval
                if settings.firms_map_key:
                    try:
                        r = fetch_hotspots(db, session, settings, args.days)
                        log.info("hotspot pull: %d fetched, %d new", r.fetched, r.inserted)
                    except Exception:
                        log.exception("hotspot pull failed")
                try:
                    build_map(db, settings, cameras)
                except Exception:
                    log.exception("map generation failed")
                try:
                    export_globe_data(db, settings, cameras)
                except Exception:
                    log.exception("globe export failed")
            wake = min(next_cam, next_hot, deadline) if deadline is not None else min(next_cam, next_hot)
            stop.wait(max(0.0, wake - time.monotonic()))
    log.info("watch stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="watchtower", description="Watchtower Phase 1 data ingestion")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the database and data directories").set_defaults(func=cmd_init)
    h = sub.add_parser("hotspots", help="pull NASA FIRMS hotspots for the configured bbox")
    h.add_argument("--days", type=int, default=1, choices=range(1, 6), metavar="N", help="day range 1-5 (default 1)")
    h.set_defaults(func=cmd_hotspots)
    sub.add_parser("cameras", help="fetch one frame from every enabled camera").set_defaults(func=cmd_cameras)
    m = sub.add_parser("map", help="write data/map.html")
    m.add_argument("--hours", type=int, default=24, help="hotspot window in hours (default 24)")
    m.set_defaults(func=cmd_map)
    e = sub.add_parser("export", help="write hotspots/cameras GeoJSON for the Global View (web/globe)")
    e.add_argument("--hours", type=int, default=24, help="hotspot window in hours (default 24)")
    e.set_defaults(func=cmd_export)
    sub.add_parser("prune", help="apply FRAME_RETENTION_HOURS once").set_defaults(func=cmd_prune)
    w = sub.add_parser("watch", help="run cameras, hotspots, map and retention on a schedule")
    w.add_argument("--camera-interval", type=float, default=60, help="seconds (default 60)")
    w.add_argument("--hotspot-interval", type=float, default=600, help="seconds (default 600)")
    w.add_argument("--days", type=int, default=1, choices=range(1, 6), metavar="N", help="FIRMS day range (default 1)")
    w.add_argument("--duration", type=float, default=None, help="stop after this many seconds")
    w.set_defaults(func=cmd_watch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    try:
        settings = load_settings()
        return args.func(settings, args)
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        return 2
