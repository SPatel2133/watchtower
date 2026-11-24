"""NASA FIRMS area API: fetch, validate, and normalize VIIRS/MODIS hotspots."""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from watchtower.config import Bbox, Settings
from watchtower.db import Database, Hotspot

log = logging.getLogger(__name__)

API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
REQUIRED_COLUMNS = frozenset({"latitude", "longitude", "acq_date", "acq_time", "confidence"})
VIIRS_CONFIDENCE = {"l": "low", "n": "nominal", "h": "high"}
SATELLITE_NAMES = {
    "N": "Suomi NPP",
    "N20": "NOAA-20",
    "1": "NOAA-20",
    "N21": "NOAA-21",
    "2": "NOAA-21",
    "A": "Aqua",
    "T": "Terra",
}
SOURCE_SATELLITES = {
    "VIIRS_SNPP_NRT": "Suomi NPP",
    "VIIRS_NOAA20_NRT": "NOAA-20",
    "VIIRS_NOAA21_NRT": "NOAA-21",
}


class FirmsError(Exception):
    """FIRMS returned something other than hotspot CSV (bad key, rate limit, outage text, ...)."""


def build_url(map_key: str, source: str, bbox: Bbox, days: int) -> str:
    if not 1 <= days <= 5:
        raise ValueError("FIRMS area API accepts a day range of 1..5")
    area = ",".join(f"{v:g}" for v in bbox)
    return f"{API_BASE}/{map_key}/{source}/{area}/{days}"


def parse_acq_datetime(acq_date: str, acq_time: str) -> str:
    """Combine acq_date (YYYY-MM-DD) and acq_time (HHMM, leading zeros possibly dropped) into UTC ISO."""
    hhmm = acq_time.strip().zfill(4)
    if len(hhmm) != 4 or not hhmm.isdigit():
        raise ValueError(f"bad acq_time {acq_time!r}")
    dt = datetime.strptime(f"{acq_date.strip()} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def confidence_label(raw: str, instrument: str) -> str:
    value = raw.strip().lower()
    if instrument.upper() == "MODIS" or value.isdigit():
        pct = int(float(value))
        if pct < 30:
            return "low"
        if pct < 80:
            return "nominal"
        return "high"
    if value in VIIRS_CONFIDENCE:
        return VIIRS_CONFIDENCE[value]
    if value in VIIRS_CONFIDENCE.values():
        return value
    raise ValueError(f"unknown confidence {raw!r}")


def hotspot_id(source: str, lat: float, lon: float, acq_datetime_utc: str) -> str:
    key = f"{source}|{lat:.5f}|{lon:.5f}|{acq_datetime_utc}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _float_or_none(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def validate_header(text: str) -> None:
    first_line = text.lstrip("\ufeff").splitlines()[0] if text.strip() else ""
    columns = {c.strip().lower() for c in first_line.split(",")}
    if not REQUIRED_COLUMNS <= columns:
        snippet = " ".join(text.split())[:200] or "<empty response>"
        raise FirmsError(f"FIRMS did not return hotspot CSV: {snippet}")


def parse_csv(text: str, source: str, fetched_at: str) -> list[Hotspot]:
    validate_header(text)
    instrument_default = "MODIS" if source.upper().startswith("MODIS") else "VIIRS"
    hotspots: list[Hotspot] = []
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    for line_no, row in enumerate(reader, start=2):
        try:
            instrument = (row.get("instrument") or instrument_default).strip()
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            acq = parse_acq_datetime(row["acq_date"], row["acq_time"])
            raw_conf = row["confidence"].strip()
            sat_raw = (row.get("satellite") or "").strip()
            satellite = SATELLITE_NAMES.get(sat_raw, sat_raw) or SOURCE_SATELLITES.get(source)
            hotspots.append(
                Hotspot(
                    id=hotspot_id(source, lat, lon, acq),
                    source=source,
                    satellite=satellite,
                    instrument=instrument,
                    lat=lat,
                    lon=lon,
                    acq_datetime_utc=acq,
                    confidence_label=confidence_label(raw_conf, instrument),
                    confidence_raw=raw_conf,
                    frp=_float_or_none(row.get("frp")),
                    daynight=(row.get("daynight") or "").strip() or None,
                    fetched_at=fetched_at,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("FIRMS %s: skipping malformed row %d: %s", source, line_no, exc)
    return hotspots


def fetch_source(
    session: requests.Session, settings: Settings, source: str, days: int, fetched_at: str | None = None
) -> list[Hotspot]:
    if not settings.firms_map_key:
        raise FirmsError("FIRMS_MAP_KEY is not set")
    url = build_url(settings.firms_map_key, source, settings.bbox, days)
    try:
        resp = session.get(url, timeout=settings.http_timeout)
    except requests.RequestException as exc:
        raise FirmsError(f"request failed: {type(exc).__name__}: {exc}".replace(settings.firms_map_key, "***")) from None
    text = resp.text
    if resp.status_code != 200:
        snippet = " ".join(text.split())[:200]
        raise FirmsError(f"HTTP {resp.status_code}: {snippet}")
    return parse_csv(text, source, fetched_at or utc_now_iso())


@dataclass
class HotspotRunResult:
    fetched: int = 0
    inserted: int = 0
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def fetch_hotspots(db: Database, session: requests.Session, settings: Settings, days: int = 1) -> HotspotRunResult:
    """Pull every configured source; a failing source is logged and does not stop the others."""
    result = HotspotRunResult()
    fetched_at = utc_now_iso()
    for source in settings.firms_sources:
        try:
            hotspots = fetch_source(session, settings, source, days, fetched_at)
            inserted = db.insert_hotspots(hotspots)
        except Exception as exc:  # noqa: BLE001 - one source must never break the run
            result.errors[source] = str(exc)
            log.error("FIRMS %s failed: %s", source, exc)
            continue
        result.fetched += len(hotspots)
        result.inserted += inserted
        log.info("FIRMS %s: %d rows, %d new", source, len(hotspots), inserted)
    return result


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
