from __future__ import annotations

import pytest

from tests.conftest import FIXTURES
from watchtower.firms import (
    FirmsError,
    build_url,
    confidence_label,
    fetch_hotspots,
    fetch_source,
    hotspot_id,
    parse_acq_datetime,
    parse_csv,
)

FETCHED = "2026-11-24T04:00:00Z"


def test_parse_viirs_csv():
    rows = parse_csv((FIXTURES / "firms_viirs_noaa20.csv").read_text(), "VIIRS_NOAA20_NRT", FETCHED)
    assert len(rows) == 6
    first = rows[0]
    assert first.source == "VIIRS_NOAA20_NRT"
    assert first.satellite == "NOAA-20"
    assert first.instrument == "VIIRS"
    assert (first.lat, first.lon) == (19.40736, -155.28415)
    assert first.acq_datetime_utc == "2026-11-24T00:09:00Z"
    assert first.frp == 30.44
    assert first.daynight == "D"
    assert [r.confidence_label for r in rows] == ["low", "low", "nominal", "nominal", "high", "high"]
    assert [r.confidence_raw for r in rows] == ["l", "l", "n", "n", "h", "h"]


def test_parse_modis_csv():
    rows = parse_csv((FIXTURES / "firms_modis.csv").read_text(), "MODIS_NRT", FETCHED)
    assert len(rows) == 6
    assert {r.instrument for r in rows} == {"MODIS"}
    assert {r.satellite for r in rows} == {"Aqua", "Terra"}
    by_raw = {r.confidence_raw: r.confidence_label for r in rows}
    assert by_raw == {"64": "nominal", "88": "high", "82": "high", "100": "high", "28": "low"}
    assert rows[2].acq_datetime_utc == "2026-11-20T03:34:00Z"
    assert rows[3].acq_datetime_utc == "2026-11-20T17:09:00Z"


@pytest.mark.parametrize(
    ("acq_time", "expected"),
    [("5", "00:05"), ("05", "00:05"), ("59", "00:59"), ("334", "03:34"), ("0007", "00:07"), ("2324", "23:24")],
)
def test_leading_zero_acq_time(acq_time, expected):
    assert parse_acq_datetime("2026-11-20", acq_time) == f"2026-11-20T{expected}:00Z"


def test_modis_fixture_single_digit_time_is_minutes_after_midnight():
    rows = parse_csv((FIXTURES / "firms_modis.csv").read_text(), "MODIS_NRT", FETCHED)
    assert rows[0].acq_datetime_utc == "2026-11-20T00:05:00Z"


@pytest.mark.parametrize("body", ["Invalid MAP_KEY.", "Exceeding allowed transaction limit.", "", "<html>oops</html>"])
def test_plain_text_error_is_detected(body):
    with pytest.raises(FirmsError):
        parse_csv(body, "MODIS_NRT", FETCHED)


def test_header_only_response_is_empty_not_error():
    assert parse_csv((FIXTURES / "firms_viirs_empty.csv").read_text(), "VIIRS_SNPP_NRT", FETCHED) == []


def test_malformed_row_is_skipped():
    text = (FIXTURES / "firms_modis.csv").read_text() + "not,a,valid,row\n"
    assert len(parse_csv(text, "MODIS_NRT", FETCHED)) == 6


def test_confidence_thresholds():
    assert confidence_label("29", "MODIS") == "low"
    assert confidence_label("30", "MODIS") == "nominal"
    assert confidence_label("79", "MODIS") == "nominal"
    assert confidence_label("80", "MODIS") == "high"
    assert confidence_label("nominal", "VIIRS") == "nominal"
    with pytest.raises(ValueError):
        confidence_label("x", "VIIRS")


def test_build_url():
    assert build_url("K", "MODIS_NRT", (-141, 41.7, -52.6, 83.1), 2) == (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/K/MODIS_NRT/-141,41.7,-52.6,83.1/2"
    )
    with pytest.raises(ValueError):
        build_url("K", "MODIS_NRT", (-141, 41.7, -52.6, 83.1), 6)


def test_hotspot_id_is_deterministic():
    a = hotspot_id("MODIS_NRT", 43.0765, -124.01601, "2026-11-20T00:05:00Z")
    assert a == hotspot_id("MODIS_NRT", 43.0765, -124.01601, "2026-11-20T00:05:00Z")
    assert a != hotspot_id("MODIS_NRT", 43.0765, -124.01601, "2026-11-20T00:06:00Z")
    assert a != hotspot_id("VIIRS_SNPP_NRT", 43.0765, -124.01601, "2026-11-20T00:05:00Z")


class FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url, timeout):
        self.urls.append(url)
        for source, resp in self.responses.items():
            if f"/{source}/" in url:
                return resp
        raise AssertionError(url)


def test_fetch_source_http_200_error_text(settings):
    session = FakeSession({"MODIS_NRT": FakeResponse(200, (FIXTURES / "firms_error_invalid_key.txt").read_text())})
    with pytest.raises(FirmsError, match="Invalid MAP_KEY"):
        fetch_source(session, settings, "MODIS_NRT", 1)


def test_fetch_hotspots_dedups_and_survives_failing_source(settings, db):
    modis = (FIXTURES / "firms_modis.csv").read_text()
    viirs = (FIXTURES / "firms_viirs_noaa20.csv").read_text()
    session = FakeSession(
        {
            "VIIRS_SNPP_NRT": FakeResponse(503, "Service Unavailable"),
            "VIIRS_NOAA20_NRT": FakeResponse(200, viirs),
            "VIIRS_NOAA21_NRT": FakeResponse(200, "Invalid MAP_KEY."),
            "MODIS_NRT": FakeResponse(200, modis),
        }
    )
    first = fetch_hotspots(db, session, settings, days=1)
    assert first.inserted == 12
    assert set(first.errors) == {"VIIRS_SNPP_NRT", "VIIRS_NOAA21_NRT"}
    second = fetch_hotspots(db, session, settings, days=1)
    assert second.fetched == 12
    assert second.inserted == 0
    assert db.count_hotspots() == 12


def test_short_row_is_skipped_not_fatal():
    text = (FIXTURES / "firms_modis.csv").read_text() + "43.1,-124.0,306.7,2,1.38,2026-11-20\n"
    assert len(parse_csv(text, "MODIS_NRT", FETCHED)) == 6
