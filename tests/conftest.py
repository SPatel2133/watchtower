from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from watchtower.config import DEFAULT_BBOX, DEFAULT_FIRMS_SOURCES, Settings
from watchtower.db import open_db
from watchtower.http import make_session

FIXTURES = Path(__file__).parent / "fixtures"
IMAGES = FIXTURES / "images"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        cameras_file=tmp_path / "cameras.yaml",
        firms_map_key="TESTKEY",
        bbox=DEFAULT_BBOX,
        firms_sources=DEFAULT_FIRMS_SOURCES,
        frame_retention_hours=72,
        stale_after=3,
        failing_after=2,
        http_timeout=5,
        http_retries=0,
    )


@pytest.fixture
def db(settings: Settings):
    database = open_db(settings.db_path)
    yield database
    database.close()


class ImageServer:
    """Mock camera HTTP server. Set `routes[path] = (status, content_type, body)`."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, str, bytes]] = {}
        self.user_agents: list[str] = []
        self.body_delay: dict[str, float] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                server.user_agents.append(self.headers.get("User-Agent", ""))
                status, ctype, body = server.routes.get(self.path, (404, "text/plain", b"not found"))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                if status in (301, 302, 307):
                    self.send_header("Location", body.decode())
                self.end_headers()
                if self.path in server.body_delay:
                    self.wfile.flush()
                    time.sleep(server.body_delay[self.path])
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def serve_image(self, path: str, name: str) -> None:
        ctype = "image/png" if name.endswith(".png") else "image/jpeg"
        self.routes[path] = (200, ctype, (IMAGES / name).read_bytes())


@pytest.fixture
def image_server():
    srv = ImageServer()
    srv.thread.start()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


@pytest.fixture
def session():
    return make_session(retries=0)
