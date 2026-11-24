/**
 * Hotspot and camera data from Watchtower's `python -m watchtower export` (public/data/*.geojson), re-fetched
 * every 5 minutes. Until a first export exists, the bundled sample (public/data/sample/) is shown instead, its
 * times shifted so its newest export time is now (the sample always looks live).
 */
import { useEffect, useState } from 'react'

export type Confidence = 'low' | 'nominal' | 'high'

export interface Hotspot {
  lat: number
  lon: number
  source: string
  satellite: string | null
  time: number
  confidence: Confidence
  frp: number | null
}

export interface Camera {
  lat: number
  lon: number
  id: string
  name: string
  status: string
}

export interface GlobeData {
  hotspots: Hotspot[]
  cameras: Camera[]
  updatedAt: number | null
  sample: boolean
}

export const REFRESH_MS = 5 * 60_000
export const WINDOW_MS = 24 * 3_600_000

interface Feature {
  geometry: { coordinates: [number, number] }
  properties: Record<string, unknown>
}
interface Collection {
  type: 'FeatureCollection'
  generated_at?: string
  features: Feature[]
}

async function getCollection(path: string): Promise<Collection | null> {
  try {
    const res = await fetch(`${import.meta.env.BASE_URL}${path}`, { cache: 'no-store' })
    if (!res.ok) return null
    // The dev server answers a missing file with index.html: anything that isn't a FeatureCollection is "absent".
    const json = (await res.json()) as Collection
    return json?.type === 'FeatureCollection' && Array.isArray(json.features) ? json : null
  } catch {
    return null
  }
}

const asConfidence = (v: unknown): Confidence => (v === 'low' || v === 'high' ? v : 'nominal')
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export async function loadGlobeData(): Promise<GlobeData> {
  let hot = await getCollection('data/hotspots.geojson')
  let cams = await getCollection('data/cameras.geojson')
  const sample = !hot
  if (!hot) hot = await getCollection('data/sample/hotspots.geojson')
  if (!cams) cams = await getCollection('data/sample/cameras.geojson')
  const generated = hot?.generated_at ? Date.parse(hot.generated_at) : NaN
  const shift = sample && Number.isFinite(generated) ? Date.now() - generated : 0
  const hotspots: Hotspot[] = (hot?.features ?? [])
    .map((f) => ({
      lon: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
      source: String(f.properties.source ?? ''),
      satellite: f.properties.satellite ? String(f.properties.satellite) : null,
      time: Date.parse(String(f.properties.acq_datetime_utc)) + shift,
      confidence: asConfidence(f.properties.confidence_label),
      frp: num(f.properties.frp),
    }))
    .filter((h) => Number.isFinite(h.time) && Number.isFinite(h.lat) && Number.isFinite(h.lon))
  const cameras: Camera[] = (cams?.features ?? []).map((f) => ({
    lon: f.geometry.coordinates[0],
    lat: f.geometry.coordinates[1],
    id: String(f.properties.id ?? ''),
    name: String(f.properties.name ?? f.properties.id ?? ''),
    status: String(f.properties.status ?? 'unknown'),
  }))
  return { hotspots, cameras, updatedAt: Number.isFinite(generated) ? generated + shift : null, sample }
}

export function useGlobeData(): GlobeData | null {
  const [data, setData] = useState<GlobeData | null>(null)
  useEffect(() => {
    let live = true
    const load = () => loadGlobeData().then((d) => live && setData(d))
    load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      live = false
      window.clearInterval(id)
    }
  }, [])
  return data
}

/** "42 min ago", "3 h ago", "just now". */
export function relativeTime(ms: number, now = Date.now()): string {
  const min = Math.round((now - ms) / 60_000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const h = Math.floor(min / 60)
  return h < 48 ? `${h} h ${min % 60 ? `${min % 60} min ` : ''}ago` : `${Math.round(h / 24)} days ago`
}
