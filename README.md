# Watchtower

Early wildfire detection for Canada. Phase 1 reliably ingests and stores raw data: NASA FIRMS satellite hotspots and still frames from public wildfire cameras. It tracks camera health and draws a simple map. There is no ML and no alerting yet.

## Setup

Requires Python 3.11+.

```bash
git clone https://github.com/SPatel2133/watchtower.git && cd watchtower
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set FIRMS_MAP_KEY
python -m watchtower init
```

### FIRMS MAP_KEY

Request a free key at <https://firms.modaps.eosdis.nasa.gov/api/map_key/>. It arrives by email. Put it in `.env` as `FIRMS_MAP_KEY=...`, or export it. Never commit it. A key allows 5,000 transactions per 10 minutes. One `hotspots` run uses one transaction per source (4 by default).

## Commands

| Command | What it does |
|---|---|
| `python -m watchtower init` | Creates `data/watchtower.db` and `data/frames/`. Safe to re-run; it also migrates older databases. |
| `python -m watchtower hotspots [--days N]` | Pulls FIRMS hotspots (`VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`) for the bounding box. N is 1-5, default 1. Duplicates are ignored. |
| `python -m watchtower cameras` | Fetches one frame from every enabled camera, then updates camera health. |
| `python -m watchtower map [--hours H]` | Writes `data/map.html`, a standalone Leaflet map. It shows hotspots from the last H hours (default 24), colored by confidence, and cameras colored by health. |
| `python -m watchtower export [--hours H]` | Writes `web/globe/public/data/hotspots.geojson` (hotspots from the last H hours, default 24: source, satellite, acquisition time UTC, confidence label, FRP) and `cameras.geojson` (cameras with health status) for the [Global View](#global-view). Set `WATCHTOWER_GLOBE_DATA_DIR` to write elsewhere. |
| `python -m watchtower prune` | Applies frame retention once. |
| `python -m watchtower watch` | Runs continuously. Cameras run every 60 s, followed by frame retention. Hotspots run every 10 min, followed by a map rebuild and a Global View export. Options: `--camera-interval`, `--hotspot-interval`, `--days`, `--duration`. A failing camera or a FIRMS outage is logged, and the loop keeps running. |

All commands take `--log-level DEBUG|INFO|WARNING`.

## Configuration

Settings are read from environment variables or from `.env`. See `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `FIRMS_MAP_KEY` | none | Required for hotspot pulls. |
| `WATCHTOWER_BBOX` | `-141,41.7,-52.6,83.1` | Bounding box as west,south,east,north. The default covers Canada; because it is a rectangle, it also includes parts of the northern US. |
| `FIRMS_SOURCES` | the 4 sources above | Comma-separated list. |
| `FRAME_RETENTION_HOURS` | `72` | Frames older than this are deleted, file and row, on every watch cycle. Frames with `keep` set are never deleted. `0` disables retention. |
| `CAMERA_STALE_AFTER` | `10` | Identical frames in a row before a camera is marked `stale`. |
| `CAMERA_FAILING_AFTER` | `3` | Failures in a row before a camera is marked `failing`. |
| `HTTP_TIMEOUT_SECONDS` / `HTTP_RETRIES` | `20` / `3` | Retries use exponential backoff on connection errors, 429 and 5xx responses, and honor `Retry-After`. |
| `WATCHTOWER_DATA_DIR` / `WATCHTOWER_CAMERAS_FILE` | `data` / `config/cameras.yaml` | Paths. |

Every request sends `User-Agent: Watchtower/<version> (wildfire data ingestion; +https://github.com/SPatel2133/watchtower)`.

## Data

SQLite database at `data/watchtower.db`. All SQL lives in `watchtower/db.py`, so a later move to Postgres/PostGIS touches one module.

- **`hotspots`**: one row per detection. `id` is a hash of source, lat, lon, and acquisition time, so re-pulling the same day never duplicates rows. FIRMS sometimes drops leading zeros from `acq_time` (for example, `5` means 00:05 UTC); the parser zero-pads it. `confidence_label` is `low`, `nominal`, or `high`, and `confidence_raw` keeps the original value. VIIRS uses `l`/`n`/`h`. MODIS uses 0-100, mapped as <30 low, 30-79 nominal, and ≥80 high.
- **`camera_frames`**: one row per distinct frame, stored at `data/frames/{camera_id}/{UTC timestamp}.jpg`. Non-JPEG images are converted to JPEG. `sha256` is the hash of the downloaded bytes. `keep` is nullable. Set it to 1, using `Database.set_frame_keep(frame_id)`, for frames a later phase links to a detection; retention never deletes those frames.
- **`camera_health`**: one row per camera. It stores last success, last error and its time, consecutive failures, consecutive identical frames, the last hash, and `status`, which is `ok`, `stale`, or `failing`.

FIRMS sometimes returns HTTP 200 with a plain-text error body, such as `Invalid MAP_KEY.`. Each response is accepted only if its CSV header has the expected columns. Otherwise the source is logged as failed and the other sources still run.

## Cameras

Cameras are listed in `config/cameras.yaml`:

```yaml
cameras:
  - id: my-cam-01                # letters, digits, - and _ (used as the frame folder name)
    name: My Lookout North
    image_url: https://example.org/my-cam-01/latest.jpg
    lat: 50.0
    lon: -120.0
    bearing_deg: 270             # optional, direction the camera faces
    source_network: ExampleNet
    # optional:
    source_type: http            # which fetcher to use (see below)
    enabled: true
    min_interval_seconds: 600    # per-camera rate limit; the camera is skipped until this has elapsed
    license: CC BY 4.0
    attribution: Example Network
```

A frame is saved only if its SHA-256 differs from the camera's previous frame. A repeated hash increments `consecutive_identical_frames`. When that counter reaches `CAMERA_STALE_AFTER`, the camera becomes `stale`, which usually means the feed has frozen. A new hash resets the counter. Responses whose content type is not an image, or whose payload does not decode as an image, count as failures.

**Pluggable sources.** `source_type` selects a fetcher from `watchtower.cameras.SOURCE_TYPES`. Two fetchers are built in:

- `http`: fetches a plain "latest frame" URL.
- `file`: reads a `file:` path. A folder path cycles through its images, which is useful for demos and tests.

To add a network, for example one that needs an API key or must look up image URLs from an API, write a class with `fetch(camera) -> Frame` and register it:

```python
from watchtower.cameras import Frame, register_source

class Ontario511Source:
    def __init__(self, settings, session): ...
    def fetch(self, camera) -> Frame: ...

register_source("ontario511", Ontario511Source)
```

To try the pipeline offline, enable the `local-sample` camera in `config/cameras.yaml`. It cycles through `tests/fixtures/images/`.

### Camera sources checked

Rule: a source is used only if its terms explicitly allow automated or scheduled fetching, or if it is published as open data under a clear licence. If the terms are unclear, the source is not used.

| Source | Terms found | Rate limit | Used? |
|---|---|---|---|
| **ALERTCalifornia** (UC San Diego) | Public camera images are free to use if credited as **"ALERTCalifornia \| UC San Diego"**. Do not crop or remove the black information bar or partner logos. Data is licensed CC BY-NC-ND 4.0 (non-commercial; commercial use needs a separate agreement). The camera list is published as JSON at `cameras.alertcalifornia.org/public-camera-data/all_cameras-v3.json`. | No published limit. Images are served with `Cache-Control: max-age=10`; Watchtower polls each camera once per 60 s. | **Yes**, 5 cameras (California). Frames are stored unmodified, with credit in the config and on the map. |
| **DriveBC HighwayCams** (BC) | The camera *list* (IDs, names, locations, image links) is open data under the [Open Government Licence – British Columbia](https://catalogue.data.gov.bc.ca/dataset/bc-highwaycams). However, DriveBC's help page says reusing or rebroadcasting BC HighwayCam *images* requires a licence agreement. | None published. | **No.** It is unclear whether images can be reused, so they need a licence from DriveBC. |
| **Ontario 511** | The [developer API](https://511on.ca/help/endpoint/cameras) (`/api/v2/get/cameras`) returns camera locations and image view URLs. It requires a free developer key. The traffic camera data is published under the [Open Government Licence – Ontario](https://www.ontario.ca/page/open-government-licence-ontario), which allows reuse, including commercial reuse, with attribution: "Contains information licensed under the Open Government Licence – Ontario". | **10 calls per 60 s** per key. | **Not yet.** The licence is clear, but it needs a developer key, which we don't have. It would be added as an `ontario511` source; set `min_interval_seconds` so that metadata and image calls together stay under 10 per minute. |
| **Alberta 511** | Has the same style of [developer API](https://511.alberta.ca/help/endpoint/cameras), which requires a developer key. Alberta's website terms allow non-commercial copying with attribution and no modification, but they do not explicitly cover automated or scheduled fetching of camera images. No open-data licence was found for the images. | **10 calls per 60 s** per key. | **No.** The terms are unclear. |
| **HPWREN** (UC San Diego) | Automated or scheduled retrieval of real-time images requires a licence from UC San Diego. | n/a | **No.** It needs a licence, which has been requested separately. |

All configured cameras are in California because ALERTCalifornia was the only source that passed the rule. Canadian coverage depends on getting an Ontario 511 key, or on a licence from DriveBC or Alberta.

## Global View

`web/globe/` is a standalone Vite + React + three.js page: a full-screen photoreal globe with the real day/night
cycle, the last 24 h of hotspots and the camera locations. It's the overview and demo page; `data/map.html` stays the
detailed operational map.

```bash
cd web/globe && npm install && npm run dev          # opens with bundled sample data
python -m watchtower hotspots && python -m watchtower export   # from the repo root; refresh the page for real data
```

The page re-fetches both files every 5 minutes, so a running `watch` keeps it current. Until a first export exists it
shows `public/data/sample/` (synthetic, times shifted to look current) and says "sample data" in the status line.
`?lat=..&lon=..` centres the first view (default: Canada); clicking a hotspot flies to it. Production build:
`npm run build` (output in `web/globe/dist/`, static files only). Vite copies `public/data/` into `dist/` at build
time, so when serving `dist/`, point the export there instead: `WATCHTOWER_GLOBE_DATA_DIR=web/globe/dist/data`.

The globe code is adapted from [dev-Armaan/satellites](https://github.com/dev-Armaan/satellites) (MIT); the shaders
and their constants are copied unchanged. Licences and attribution: [web/globe/CREDITS.md](web/globe/CREDITS.md).

| Effect | Files (under `web/globe/src/`) |
|---|---|
| Sun position and GMST from UTC, every frame; cloud drift | `globe/SunClock.tsx`, `lib/geo.ts`, `lib/geoCore.ts` |
| Day side (12% desaturation, low-sun tint, glint, haze, hill shading), terminator, night ground, earthshine, city lights | `globe/shaders/earth.ts` (shared GLSL in `globe/shaders/chunks.ts`), wired in `globe/Earth.tsx` |
| Clouds (1.006 R, ground shadows) | `globe/shaders/clouds.ts`, `globe/Earth.tsx` |
| Atmosphere rim | `globe/shaders/atmosphere.ts`, `globe/Earth.tsx` |
| Stars (Hipparcos, magnitude classes, rotate with GMST) | `globe/Stars.tsx`, `globe/starData.ts`, `globe/shaders/points.ts` |
| HDR buffer, bloom, tone shoulder, grain, vignette | `globe/Post.tsx`, `globe/toneShoulder.ts` |
| 1k → 4k textures, decoded in a Web Worker | `globe/textures.ts`, `globe/textureDecode.worker.ts`, `public/textures/` |
| Camera: damped orbit, zoom limits, auto-rotate, fly-to | `globe/CameraRig.tsx` |
| **Hotspots** (FRP → size/brightness, confidence → opacity, < 3 h pulse) and **camera markers** | `globe/shaders/hotspots.ts`, `globe/Markers.tsx` (also picking for the tooltip and click) |
| Data loading, 5-minute refresh, sample fallback | `data/data.ts` |
| Tooltip, status line, credits, `?lat/lon`, reduced motion | `App.tsx`, `styles.css` |

`prefers-reduced-motion` stops cloud drift, hotspot pulsing and auto-rotation, and makes fly-to a cut. Device pixel
ratio is capped at 2.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Tests make no live network calls. FIRMS parsing uses saved real responses in `tests/fixtures/`. Camera tests run against a local mock HTTP server and a folder of sample images. GitHub Actions runs the tests on Python 3.11 and 3.12 on every push.

## Roadmap

1. **Phase 1 (this):** ingest and store FIRMS hotspots and camera frames, track camera health, draw a map, and apply frame retention.
2. **Smoke detection:** an ML model that runs on camera frames. Frames linked to a detection get `keep=1`.
3. **Fusion and triangulation:** combine camera bearings from 2 or more cameras with satellite hotspots to locate and confirm fires.
4. **Twilio SMS alerts** for confirmed detections.
5. **Dashboard**, replacing the static map.
6. **Remote sensor nodes**, such as low-cost cameras and air-quality sensors in areas without coverage.
