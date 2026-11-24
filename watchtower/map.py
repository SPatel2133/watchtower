"""Standalone Leaflet map of recent hotspots and camera health."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watchtower.config import CameraConfig, Settings
from watchtower.db import Database

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watchtower map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>
html, body, #map { height: 100%; margin: 0; }
.legend { background: #fff; padding: 8px 10px; font: 13px/1.5 sans-serif; border-radius: 4px; box-shadow: 0 1px 4px #0004; }
.legend i { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.legend b { display: block; margin-top: 4px; }
</style>
</head>
<body>
<div id="map"></div>
<script>
const DATA = __DATA__;
const HOT = {high: "#d7191c", nominal: "#fd8d3c", low: "#fecc5c"};
const CAM = {ok: "#1a9641", stale: "#7b3294", failing: "#404040", unknown: "#2b83ba"};
const b = DATA.bbox;
const map = L.map("map").fitBounds([[b[1], b[0]], [b[3], b[2]]]);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18, attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

function popup(title, rows) {
  const el = document.createElement("div");
  const h = document.createElement("strong");
  h.textContent = title;
  el.appendChild(h);
  for (const [k, v] of rows) {
    const line = document.createElement("div");
    line.textContent = k + ": " + (v === null || v === undefined ? "n/a" : v);
    el.appendChild(line);
  }
  return el;
}

const hotLayer = L.layerGroup().addTo(map);
for (const h of DATA.hotspots) {
  L.circleMarker([h.lat, h.lon], {
    radius: 5, weight: 1, color: "#333", fillColor: HOT[h.confidence_label] || "#999", fillOpacity: 0.9
  }).bindPopup(popup("Hotspot", [
    ["Source", h.source], ["Satellite", h.satellite], ["Time (UTC)", h.acq_datetime_utc],
    ["Confidence", h.confidence_label + " (" + h.confidence_raw + ")"], ["FRP (MW)", h.frp], ["Day/night", h.daynight]
  ])).addTo(hotLayer);
}

const camLayer = L.layerGroup().addTo(map);
for (const c of DATA.cameras) {
  L.circleMarker([c.lat, c.lon], {
    radius: 8, weight: 2, color: "#fff", fillColor: CAM[c.status] || CAM.unknown, fillOpacity: 1
  }).bindPopup(popup(c.name, [
    ["Camera", c.id], ["Network", c.source_network], ["Status", c.status],
    ["Bearing", c.bearing_deg], ["Last success", c.last_success_at], ["Last error", c.last_error],
    ["Credit", c.attribution]
  ])).addTo(camLayer);
}
L.control.layers(null, {"Hotspots": hotLayer, "Cameras": camLayer}).addTo(map);

const legend = L.control({position: "bottomright"});
legend.onAdd = function () {
  const div = L.DomUtil.create("div", "legend");
  const add = (label, color) => {
    const row = document.createElement("div");
    const dot = document.createElement("i");
    dot.style.background = color;
    row.appendChild(dot);
    row.appendChild(document.createTextNode(label));
    div.appendChild(row);
  };
  const head = (t) => { const e = document.createElement("b"); e.textContent = t; div.appendChild(e); };
  head("Hotspots, last " + DATA.hours + " h (" + DATA.hotspots.length + ")");
  for (const k of ["high", "nominal", "low"]) add(k, HOT[k]);
  head("Cameras (" + DATA.cameras.length + ")");
  for (const k of ["ok", "stale", "failing", "unknown"]) add(k, CAM[k]);
  const gen = document.createElement("div");
  gen.textContent = "Generated " + DATA.generated_at;
  div.appendChild(gen);
  return div;
};
legend.addTo(map);
</script>
</body>
</html>
"""


def build_map(
    db: Database, settings: Settings, cameras: list[CameraConfig], hours: int = 24, now: datetime | None = None
) -> Path:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    health = db.all_health()
    camera_data = []
    for cam in cameras:
        h = health.get(cam.id)
        camera_data.append(
            {
                "id": cam.id,
                "name": cam.name,
                "lat": cam.lat,
                "lon": cam.lon,
                "bearing_deg": cam.bearing_deg,
                "source_network": cam.source_network,
                "attribution": cam.attribution,
                "status": h.status if h else "unknown",
                "last_success_at": h.last_success_at if h else None,
                "last_error": h.last_error if h else None,
            }
        )
    data = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hours": hours,
        "bbox": list(settings.bbox),
        "hotspots": db.hotspots_since(since),
        "cameras": camera_data,
    }
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    settings.map_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.map_path.with_suffix(".html.part")
    tmp.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    tmp.replace(settings.map_path)
    return settings.map_path
