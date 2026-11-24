from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import IMAGES
from watchtower.cameras import CameraFetchError, CameraIngestor, Frame, register_source, to_jpeg
from watchtower.config import USER_AGENT, CameraConfig


def camera(url: str, cam_id: str = "cam1", **kw) -> CameraConfig:
    return CameraConfig(id=cam_id, name="Test cam", image_url=url, lat=49.0, lon=-120.0, source_network="test", **kw)


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 24, 4, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=60)
        return self.t


@pytest.fixture
def ingestor(db, settings, session):
    return CameraIngestor(db, settings, session, now=Clock())


def test_new_frame_is_saved_with_watchtower_user_agent(ingestor, image_server, db, settings):
    image_server.serve_image("/cam.jpg", "frame0.jpg")
    result = ingestor.process(camera(image_server.url("/cam.jpg")))
    assert result.outcome == "saved"
    frames = db.frames("cam1")
    assert len(frames) == 1
    assert frames[0].path == "frames/cam1/20261124T040100Z.jpg"
    assert (settings.data_dir / frames[0].path).read_bytes() == (IMAGES / "frame0.jpg").read_bytes()
    assert frames[0].keep is None
    health = db.get_health("cam1")
    assert (health.status, health.consecutive_failures, health.consecutive_identical_frames) == ("ok", 0, 0)
    assert image_server.user_agents == [USER_AGENT]
    assert USER_AGENT.startswith("Watchtower/")


def test_repeated_hash_marks_camera_stale(ingestor, image_server, db, settings):
    image_server.serve_image("/cam.jpg", "frame0.jpg")
    cam = camera(image_server.url("/cam.jpg"))
    outcomes = [ingestor.process(cam).outcome for _ in range(settings.stale_after + 1)]
    assert outcomes == ["saved"] + ["identical"] * settings.stale_after
    assert len(db.frames("cam1")) == 1
    health = db.get_health("cam1")
    assert health.consecutive_identical_frames == settings.stale_after
    assert health.status == "stale"


def test_new_hash_resets_stale(ingestor, image_server, db, settings):
    image_server.serve_image("/cam.jpg", "frame0.jpg")
    cam = camera(image_server.url("/cam.jpg"))
    for _ in range(settings.stale_after + 1):
        ingestor.process(cam)
    assert db.get_health("cam1").status == "stale"
    image_server.serve_image("/cam.jpg", "frame1.jpg")
    assert ingestor.process(cam).outcome == "saved"
    health = db.get_health("cam1")
    assert (health.status, health.consecutive_identical_frames) == ("ok", 0)
    assert len(db.frames("cam1")) == 2


@pytest.mark.parametrize(
    ("route", "error"),
    [
        ((404, "text/plain", b"nope"), "HTTP 404"),
        ((500, "text/plain", b"boom"), "HTTP 500"),
        ((200, "text/html", b"<html>login</html>"), "content type"),
        ((200, "image/jpeg", b"\xff\xd8\xffnot really a jpeg"), "not a decodable image"),
    ],
)
def test_failure_updates_health(ingestor, image_server, db, settings, route, error):
    image_server.routes["/cam.jpg"] = route
    cam = camera(image_server.url("/cam.jpg"))
    first = ingestor.process(cam)
    assert first.outcome == "failed"
    health = db.get_health("cam1")
    assert health.consecutive_failures == 1
    assert error in health.last_error
    assert health.last_error_at is not None
    assert health.status == "ok"
    for _ in range(settings.failing_after - 1):
        ingestor.process(cam)
    assert db.get_health("cam1").status == "failing"
    assert db.frames("cam1") == []

    image_server.serve_image("/cam.jpg", "frame2.jpg")
    assert ingestor.process(cam).outcome == "saved"
    health = db.get_health("cam1")
    assert (health.status, health.consecutive_failures) == ("ok", 0)
    assert health.last_error is not None


def test_unreachable_camera_does_not_break_cycle(ingestor, image_server, db):
    image_server.serve_image("/good.jpg", "frame0.jpg")
    results = ingestor.run(
        [camera("http://127.0.0.1:9/dead.jpg", "dead"), camera(image_server.url("/good.jpg"), "good")]
    )
    assert [r.outcome for r in results] == ["failed", "saved"]
    assert db.get_health("dead").consecutive_failures == 1


def test_png_is_converted_to_jpeg(ingestor, image_server, db, settings):
    image_server.serve_image("/cam.png", "frame_png.png")
    assert ingestor.process(camera(image_server.url("/cam.png"))).outcome == "saved"
    saved = (settings.data_dir / db.frames("cam1")[0].path).read_bytes()
    assert saved[:3] == b"\xff\xd8\xff"


def test_local_folder_source_cycles_sample_images(ingestor, db):
    cam = camera(IMAGES.resolve().as_uri(), source_type="file")
    outcomes = [ingestor.process(cam).outcome for _ in range(5)]
    assert outcomes == ["saved"] * 5
    assert len({f.sha256 for f in db.frames("cam1")}) == 4


def test_min_interval_is_respected(ingestor, image_server):
    image_server.serve_image("/cam.jpg", "frame0.jpg")
    cam = camera(image_server.url("/cam.jpg"), min_interval_seconds=3600)
    assert ingestor.process(cam).outcome == "saved"
    assert ingestor.process(cam).outcome == "skipped"
    assert len(image_server.user_agents) == 1


def test_custom_source_can_be_registered(ingestor, db):
    payload = (IMAGES / "frame1.jpg").read_bytes()

    class StaticSource:
        def fetch(self, cam):
            return Frame(payload, "image/jpeg")

    register_source("static-test", lambda settings, session: StaticSource())
    assert ingestor.process(camera("static://x", source_type="static-test")).outcome == "saved"


def test_unknown_source_type_is_a_failure(ingestor, db):
    assert ingestor.process(camera("x://y", source_type="nope")).outcome == "failed"
    assert "unknown source_type" in db.get_health("cam1").last_error


def test_to_jpeg_rejects_missing_content_type():
    with pytest.raises(CameraFetchError):
        to_jpeg(Frame((IMAGES / "frame0.jpg").read_bytes(), ""))


def test_redirect_is_followed(ingestor, image_server):
    image_server.serve_image("/real.jpg", "frame0.jpg")
    image_server.routes["/cam.jpg"] = (302, "text/plain", b"/real.jpg")
    assert ingestor.process(camera(image_server.url("/cam.jpg"))).outcome == "saved"


def test_redirect_loop_is_a_failure(ingestor, image_server, db):
    image_server.routes["/loop.jpg"] = (302, "text/plain", b"/loop.jpg")
    assert ingestor.process(camera(image_server.url("/loop.jpg"))).outcome == "failed"
    assert "redirects" in db.get_health("cam1").last_error


def test_body_read_timeout_counts_as_failure(db, settings, session, image_server):
    from dataclasses import replace

    image_server.serve_image("/slow.jpg", "frame0.jpg")
    image_server.body_delay["/slow.jpg"] = 1.5
    ing = CameraIngestor(db, replace(settings, http_timeout=0.3), session, now=Clock())
    assert ing.process(camera(image_server.url("/slow.jpg"))).outcome == "failed"
    assert db.get_health("cam1").consecutive_failures == 1


def test_existing_file_at_frame_path_is_not_overwritten(ingestor, image_server, db, settings):
    taken = settings.frames_dir / "cam1" / "20261124T040100Z.jpg"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"other process")
    image_server.serve_image("/cam.jpg", "frame0.jpg")
    assert ingestor.process(camera(image_server.url("/cam.jpg"))).outcome == "saved"
    assert taken.read_bytes() == b"other process"
    assert db.frames("cam1")[0].path == "frames/cam1/20261124T040100Z_1.jpg"


def test_failed_frame_write_leaves_no_placeholder(ingestor, image_server, settings, monkeypatch):
    import watchtower.cameras as cameras_mod

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(cameras_mod.os, "replace", broken_replace)
    image_server.serve_image("/cam.jpg", "frame0.jpg")
    assert [r.outcome for r in ingestor.run([camera(image_server.url("/cam.jpg"))])] == ["failed"]
    assert list((settings.frames_dir / "cam1").iterdir()) == []
