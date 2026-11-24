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
:root {
  --bg: #ffffff; --fg: #1f2933; --muted: #6b7785; --line: #e4e7eb;
  --high: #e03131; --nominal: #f76707; --low: #fab005;
  --ok: #2f9e44; --stale: #9c36b5; --failing: #495057; --unknown: #1c7ed6;
}
html, body, #map { height: 100%; margin: 0; }
body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--fg); }
.panel { background: var(--bg); border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.18); padding: 12px 14px; }
.brand { width: 270px; }
.brand h1 { margin: 0; font-size: 17px; letter-spacing: .2px; display: flex; align-items: center; gap: 8px; }
.brand h1 .logo { width: 22px; height: 22px; }
.brand .sub { color: var(--muted); font-size: 12px; margin: 2px 0 10px; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
.stat { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; }
.stat .n { font-size: 20px; font-weight: 650; line-height: 1.1; }
.stat .l { color: var(--muted); font-size: 10px; white-space: nowrap; text-transform: uppercase; letter-spacing: .4px; }
.section { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .4px; margin: 10px 0 4px; }
.seg { display: flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg button { flex: 1; border: 0; background: none; padding: 5px 0; font: inherit; cursor: pointer; color: var(--fg); }
.seg button + button { border-left: 1px solid var(--line); }
.seg button.on { background: var(--fg); color: #fff; }
.row { display: flex; align-items: center; gap: 7px; padding: 2px 0; }
.row label { display: flex; align-items: center; gap: 7px; cursor: pointer; flex: 1; }
.row .count { color: var(--muted); font-variant-numeric: tabular-nums; }
.dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; border: 1px solid rgba(0,0,0,.25); flex: none; }
.foot { color: var(--muted); font-size: 11px; margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
.cam-icon { display: flex; align-items: center; justify-content: center; border-radius: 50%; border: 2px solid #fff;
  box-shadow: 0 1px 5px rgba(0,0,0,.45); width: 26px; height: 26px; }
.cam-icon svg { width: 15px; height: 15px; fill: #fff; }
.leaflet-popup-content-wrapper { border-radius: 10px; }
.leaflet-popup-content { margin: 12px 14px; min-width: 220px; font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
.pop h3 { margin: 0 0 6px; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.badge { font-size: 11px; font-weight: 600; color: #fff; border-radius: 999px; padding: 1px 8px; text-transform: capitalize; }
.pop table { border-collapse: collapse; width: 100%; }
.pop td { padding: 2px 0; vertical-align: top; }
.pop td:first-child { color: var(--muted); padding-right: 10px; white-space: nowrap; }
.pop img { display: block; width: 100%; max-width: 320px; border-radius: 6px; margin: 4px 0 6px; }
.pop .credit { color: var(--muted); font-size: 11px; margin-top: 4px; }
.pop .err { color: var(--high); }
@media (max-width: 600px) { .brand { width: 210px; } .stats { display: none; } }
</style>
</head>
<body>
<div id="map"></div>
<script>
const DATA = __DATA__;
const css = getComputedStyle(document.documentElement);
const C = (k) => css.getPropertyValue("--" + k).trim();
const CONF = ["high", "nominal", "low"];
const STATUS = ["ok", "stale", "failing", "unknown"];
const NOW = Date.parse(DATA.generated_at);

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}
function ago(iso) {
  if (!iso) return "never";
  const m = Math.round((NOW - Date.parse(iso)) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return m + " min ago";
  const h = m / 60;
  return (h < 48 ? h.toFixed(h < 10 ? 1 : 0) + " h" : Math.round(h / 24) + " d") + " ago";
}
function fmtTime(iso) { return iso ? iso.replace("T", " ").replace(":00Z", " UTC").replace("Z", " UTC") : "n/a"; }
function table(rows) {
  const t = el("table");
  for (const [k, v] of rows) if (v !== null && v !== undefined && v !== "") t.append(el("tr", {}, el("td", {}, k), el("td", {}, v)));
  return t;
}
function badge(text, color) { return el("span", {class: "badge", style: "background:" + color}, text); }

const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
});
const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
  maxZoom: 17, subdomains: "abc",
  attribution: 'Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
});
const map = L.map("map", {preferCanvas: true, layers: [osm], zoomControl: false, worldCopyJump: true});
L.control.zoom({position: "bottomleft"}).addTo(map);
L.control.scale({position: "bottomleft", imperial: false}).addTo(map);

const b = DATA.bbox;
const pts = DATA.hotspots.map((h) => [h.lat, h.lon]).concat(DATA.cameras.map((c) => [c.lat, c.lon]));
const bounds = pts.length ? L.latLngBounds(pts) : L.latLngBounds([[b[1], b[0]], [b[3], b[2]]]);
map.fitBounds(bounds, {paddingTopLeft: [300, 30], paddingBottomRight: [30, 30], maxZoom: 9});

// Hotspots: color = confidence, size = fire radiative power, opacity fades with age.
const hotLayer = L.layerGroup().addTo(map);
const hotMarkers = DATA.hotspots.map((h) => {
  const ageH = (NOW - Date.parse(h.acq_datetime_utc)) / 3600000;
  const radius = Math.min(14, 4 + Math.sqrt(Math.max(0, h.frp || 0)) * 0.7);
  const color = C(h.confidence_label) || "#868e96";
  const marker = L.circleMarker([h.lat, h.lon], {
    radius, weight: 1, color: "rgba(0,0,0,.45)", fillColor: color,
    fillOpacity: Math.max(0.35, 0.95 - ageH / DATA.hours * 0.6)
  });
  marker.bindPopup(() => el("div", {class: "pop"},
    el("h3", {}, "Hotspot", badge(h.confidence_label, color)),
    table([
      ["Acquired", fmtTime(h.acq_datetime_utc) + " (" + ago(h.acq_datetime_utc) + ")"],
      ["Source", h.source],
      ["Satellite", [h.satellite, h.instrument].filter(Boolean).join(" / ")],
      ["Confidence", h.confidence_raw],
      ["FRP", h.frp === null ? null : h.frp + " MW"],
      ["Day/night", h.daynight === "D" ? "Day" : h.daynight === "N" ? "Night" : h.daynight],
      ["Location", h.lat.toFixed(4) + ", " + h.lon.toFixed(4)]
    ])
  ));
  marker.data = {conf: h.confidence_label, ageH};
  return marker;
});

// Cameras: status-colored icon plus a view cone toward bearing_deg.
const camLayer = L.layerGroup().addTo(map);
const CAM_SVG = '<svg viewBox="0 0 24 24"><path d="M9 4 7.2 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3.2L15 4H9Zm3 5a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z"/></svg>';
function cone(lat, lon, bearing, km, spread) {
  const pts = [[lat, lon]];
  for (let a = bearing - spread / 2; a <= bearing + spread / 2 + 0.01; a += spread / 8) {
    const r = a * Math.PI / 180;
    pts.push([lat + (km / 111.32) * Math.cos(r), lon + (km / (111.32 * Math.cos(lat * Math.PI / 180))) * Math.sin(r)]);
  }
  return pts;
}
for (const c of DATA.cameras) {
  const color = C(c.status) || C("unknown");
  if (c.bearing_deg !== null && c.bearing_deg !== undefined) {
    L.polygon(cone(c.lat, c.lon, c.bearing_deg, 25, 50), {
      color, weight: 1.5, opacity: 0.9, dashArray: "4 3", fillColor: color, fillOpacity: 0.25, interactive: false
    }).addTo(camLayer);
  }
  const icon = L.divIcon({className: "", html: '<div class="cam-icon" style="background:' + color + '">' + CAM_SVG + "</div>",
    iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -14]});
  L.marker([c.lat, c.lon], {icon, title: c.name, zIndexOffset: 1000}).bindPopup(() => {
    const kids = [el("h3", {}, c.name, badge(c.status, color))];
    if (c.latest_frame && /^frames\\//.test(c.latest_frame)) {
      kids.push(el("img", {src: c.latest_frame, alt: "Latest frame from " + c.name, loading: "lazy"}));
    }
    kids.push(table([
      ["Latest frame", c.latest_frame_at ? fmtTime(c.latest_frame_at) + " (" + ago(c.latest_frame_at) + ")" : null],
      ["Last success", c.last_success_at ? ago(c.last_success_at) : "never"],
      ["Network", c.source_network],
      ["Facing", c.bearing_deg === null || c.bearing_deg === undefined ? null : Math.round(c.bearing_deg) + "\\u00b0"],
      ["Camera ID", c.id]
    ]));
    if (c.last_error) kids.push(el("div", {class: "err"}, "Last error " + ago(c.last_error_at) + ": " + c.last_error));
    if (c.attribution) kids.push(el("div", {class: "credit"}, "Image credit: " + c.attribution));
    return el("div", {class: "pop"}, ...kids);
  }, {maxWidth: 340}).addTo(camLayer);
}

// Side panel: summary, time window, confidence filter, legend.
const state = {hours: DATA.hours, conf: new Set(CONF)};
const counts = {};
const confRows = {};
const totalEl = el("div", {class: "n"});
const highEl = el("div", {class: "n"});
function refresh() {
  for (const k of CONF) counts[k] = 0;
  let shown = 0;
  for (const m of hotMarkers) {
    const inWindow = m.data.ageH <= state.hours;
    if (inWindow) counts[m.data.conf] = (counts[m.data.conf] || 0) + 1;
    const visible = inWindow && state.conf.has(m.data.conf);
    if (visible) { shown++; if (!hotLayer.hasLayer(m)) hotLayer.addLayer(m); }
    else if (hotLayer.hasLayer(m)) hotLayer.removeLayer(m);
  }
  totalEl.textContent = shown.toLocaleString();
  highEl.textContent = (counts.high || 0).toLocaleString();
  for (const k of CONF) confRows[k].textContent = (counts[k] || 0).toLocaleString();
}

const panel = L.control({position: "topleft"});
panel.onAdd = function () {
  const logo = el("span", {class: "logo"});
  logo.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path fill="#e03131" d="M12 2s5 4.6 5 9.5a5 5 0 0 1-10 0C7 9 8.5 7 8.5 7S9 9.5 11 10c0-3 1-6 1-8Z"/><path fill="#fab005" d="M12 22a4 4 0 0 1-4-4c0-2.2 2-4 2-4s.5 1.6 2 2c0-1.7.8-3 .8-3S16 15 16 18a4 4 0 0 1-4 4Z"/></svg>';
  const camCounts = {};
  for (const c of DATA.cameras) camCounts[c.status] = (camCounts[c.status] || 0) + 1;
  const okCams = el("div", {class: "n"}, (camCounts.ok || 0) + "/" + DATA.cameras.length);

  const seg = el("div", {class: "seg"});
  const windows = [6, 12, 24, 48, 72].filter((h) => h < DATA.hours).concat([DATA.hours]);
  for (const h of windows) {
    const btn = el("button", {type: "button", class: h === state.hours ? "on" : ""}, h + "h");
    btn.onclick = () => { state.hours = h; for (const x of seg.children) x.classList.toggle("on", x === btn); refresh(); };
    seg.append(btn);
  }

  const confBox = el("div");
  for (const k of CONF) {
    const cb = el("input", {type: "checkbox"});
    cb.checked = true;
    cb.onchange = () => { cb.checked ? state.conf.add(k) : state.conf.delete(k); refresh(); };
    confRows[k] = el("span", {class: "count"});
    confBox.append(el("div", {class: "row"}, el("label", {}, cb, el("span", {class: "dot", style: "background:" + C(k)}), k), confRows[k]));
  }
  const sizeNote = el("div", {class: "row", style: "color:var(--muted);font-size:11px"}, "Larger dot = more fire radiative power");

  const camBox = el("div");
  for (const k of STATUS) {
    if (k === "unknown" && !camCounts.unknown) continue;
    camBox.append(el("div", {class: "row"}, el("span", {class: "dot", style: "background:" + C(k)}), el("span", {style: "flex:1"}, k),
      el("span", {class: "count"}, camCounts[k] || 0)));
  }

  const div = el("div", {class: "panel brand"},
    el("h1", {}, logo, "Watchtower"),
    el("div", {class: "sub"}, "Satellite hotspots & wildfire cameras"),
    el("div", {class: "stats"},
      el("div", {class: "stat"}, totalEl, el("div", {class: "l"}, "Hotspots shown")),
      el("div", {class: "stat"}, highEl, el("div", {class: "l"}, "High confidence")),
      el("div", {class: "stat", style: "grid-column: span 2"}, okCams, el("div", {class: "l"}, "Cameras healthy"))
    ),
    el("div", {class: "section"}, "Time window"), seg,
    el("div", {class: "section"}, "Hotspot confidence"), confBox, sizeNote,
    el("div", {class: "section"}, "Camera status"), camBox,
    el("div", {class: "foot"}, "Data: NASA FIRMS \\u00b7 Generated " + fmtTime(DATA.generated_at))
  );
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);
  return div;
};
panel.addTo(map);
L.control.layers({"Streets": osm, "Terrain": topo}, {"Hotspots": hotLayer, "Cameras": camLayer},
  {position: "topright"}).addTo(map);
refresh();
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
    latest = db.latest_frames()
    camera_data = []
    for cam in cameras:
        h = health.get(cam.id)
        frame = latest.get(cam.id)
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
                "last_error_at": h.last_error_at if h else None,
                "latest_frame": frame.path if frame else None,
                "latest_frame_at": frame.captured_at_utc if frame else None,
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
