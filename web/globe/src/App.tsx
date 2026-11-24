/**
 * The Global View: a full-screen globe with Watchtower's hotspots and cameras, a hover / tap tooltip, one status
 * line and the credits. The canvas stays linear (`flat`); tone mapping happens in the post chain (globe/Post.tsx).
 */
import { Canvas } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Color } from 'three'
import { latLonToWorld } from '@/lib/geo'
import { palette } from '@/ui/system/palette'
import { relativeTime, useGlobeData, WINDOW_MS, type Camera, type Hotspot } from '@/data/data'
import { CameraRig, type CameraRigHandle } from './globe/CameraRig'
import { Globe } from './globe/Globe'
import { Markers, type Pick } from './globe/Markers'
import { createRuntime, RuntimeContext } from './globe/runtime'

const CANADA = { lat: 57, lon: -100 }
const START_DISTANCE = 4.4

function startView() {
  const q = new URLSearchParams(window.location.search)
  const lat = Number.parseFloat(q.get('lat') ?? '')
  const lon = Number.parseFloat(q.get('lon') ?? '')
  if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90) return { lat, lon }
  return CANADA
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mql.matches)
    mql.addEventListener('change', on)
    return () => mql.removeEventListener('change', on)
  }, [])
  return reduced
}

function useNow(everyMs: number): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(id)
  }, [everyMs])
  return now
}

export function App() {
  const reduced = useReducedMotion()
  const runtime = useMemo(() => createRuntime(reduced), []) // eslint-disable-line react-hooks/exhaustive-deps
  runtime.reducedMotion = reduced
  const data = useGlobeData()
  const now = useNow(30_000)
  const hotspots = useMemo(() => (data?.hotspots ?? []).filter((h) => now - h.time <= WINDOW_MS), [data, now])
  const cameras = data?.cameras ?? []
  const [hovered, setHovered] = useState<Pick | null>(null)
  const rig = useRef<CameraRigHandle>(null)
  const start = useMemo(() => latLonToWorld(startView().lat, startView().lon, START_DISTANCE).toArray(), [])

  const tip = hovered ? tooltip(hovered, hotspots, cameras, now) : null

  return (
    <RuntimeContext.Provider value={runtime}>
      <Canvas
        className="globe"
        dpr={[1, 2]}
        flat
        gl={{ antialias: false, powerPreference: 'high-performance' }}
        camera={{ fov: 30, near: 0.01, far: 400, position: start }}
        onCreated={({ gl }) => gl.setClearColor(new Color(palette.ink0), 1)}
      >
        <Globe />
        <Markers
          hotspots={hotspots}
          cameras={cameras}
          hovered={hovered}
          onHover={setHovered}
          onSelect={(p) => {
            const t = p.kind === 'hotspot' ? hotspots[p.index] : cameras[p.index]
            if (t) rig.current?.flyTo(t.lat, t.lon)
          }}
        />
        <CameraRig ref={rig} />
      </Canvas>
      {tip && (
        <div className="tooltip" style={{ left: hovered!.x, top: hovered!.y }} role="tooltip">
          {tip.map((line, i) => (
            <div key={i} className={i === 0 ? 'tooltip-title' : undefined}>
              {line}
            </div>
          ))}
        </div>
      )}
      <div className="status">
        {data
          ? `${hotspots.length} hotspots · last 24h · updated ${data.updatedAt ? relativeTime(data.updatedAt, now) : 'never'}${data.sample ? ' · sample data' : ''}`
          : 'loading…'}
      </div>
      <footer className="credits">
        Globe adapted from <a href="https://github.com/dev-Armaan/satellites">dev-Armaan/satellites</a> (MIT, © 2026 Armaan
        Gupta) · Textures © <a href="https://www.solarsystemscope.com/textures/">Solar System Scope</a> (CC BY 4.0), from
        NASA Blue Marble &amp; Black Marble · Fire data: <a href="https://firms.modaps.eosdis.nasa.gov/">NASA FIRMS</a>
      </footer>
    </RuntimeContext.Provider>
  )
}

function tooltip(p: Pick, hotspots: Hotspot[], cameras: Camera[], now: number): string[] | null {
  if (p.kind === 'hotspot') {
    const h = hotspots[p.index]
    if (!h) return null
    return [
      h.satellite ? `${h.satellite} · ${h.source}` : h.source,
      relativeTime(h.time, now),
      `confidence: ${h.confidence}`,
      `FRP: ${h.frp == null ? 'n/a' : `${h.frp.toFixed(1)} MW`}`,
    ]
  }
  const c = cameras[p.index]
  return c ? [c.name, `camera · ${c.status}`] : null
}
