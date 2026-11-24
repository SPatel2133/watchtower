/**
 * The Watchtower layer: hotspots and camera markers on the surface (shaders/hotspots.ts), plus screen-space
 * picking for the tooltip and click-to-fly. Points sit just above the cloud shell (1.007 R) so clouds never hide a
 * fire; the Earth's depth hides the far side. Picking projects every point and takes the nearest one facing the
 * camera within PICK_PX: a few thousand points cost well under a millisecond.
 */
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { AdditiveBlending, BufferAttribute, BufferGeometry, NormalBlending, ShaderMaterial, Vector3 } from 'three'
import { latLonToWorld } from '@/lib/geo'
import type { Camera, Hotspot } from '@/data/data'
import { lin } from './Earth'
import { camerasFragment, camerasVertex, hotspotsFragment, hotspotsVertex } from './shaders/hotspots'
import { FRAME, useRuntime } from './runtime'

export const MARKER_RADIUS = 1.007
const PICK_PX = 12
const RECENT_MS = 3 * 3_600_000
const CONF_ALPHA = { low: 0.35, nominal: 0.7, high: 1.0 } as const
const CAMERA_OK = '#e6eef7'
const CAMERA_BAD = '#ff4d4d'

export type Pick = { kind: 'hotspot' | 'camera'; index: number; x: number; y: number }

function useHover(geometry: BufferGeometry, n: number, hovered: number) {
  useEffect(() => {
    const a = geometry.getAttribute('aHover') as BufferAttribute | undefined
    if (!a) return
    for (let i = 0; i < n; i++) a.setX(i, i === hovered ? 1 : 0)
    a.needsUpdate = true
  }, [geometry, n, hovered])
}

export function Markers(props: {
  hotspots: Hotspot[]
  cameras: Camera[]
  hovered: Pick | null
  onHover: (p: Pick | null) => void
  onSelect: (p: Pick) => void
}) {
  const { hotspots, cameras, hovered, onHover, onSelect } = props
  const rt = useRuntime()
  const camera = useThree((s) => s.camera)
  const gl = useThree((s) => s.gl)

  const hotPos = useMemo(() => hotspots.map((h) => latLonToWorld(h.lat, h.lon, MARKER_RADIUS)), [hotspots])
  const camPos = useMemo(() => cameras.map((c) => latLonToWorld(c.lat, c.lon, MARKER_RADIUS)), [cameras])

  const hotGeo = useMemo(() => {
    const now = Date.now()
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(new Float32Array(hotPos.flatMap((p) => [p.x, p.y, p.z])), 3))
    g.setAttribute('aFrp', new BufferAttribute(new Float32Array(hotspots.map((h) => h.frp ?? 1)), 1))
    g.setAttribute('aConf', new BufferAttribute(new Float32Array(hotspots.map((h) => CONF_ALPHA[h.confidence])), 1))
    g.setAttribute('aRecent', new BufferAttribute(new Float32Array(hotspots.map((h) => (now - h.time < RECENT_MS ? 1 : 0))), 1))
    g.setAttribute('aPhase', new BufferAttribute(new Float32Array(hotspots.map((_, i) => (i * 2.399) % 6.283)), 1))
    g.setAttribute('aHover', new BufferAttribute(new Float32Array(hotspots.length), 1))
    return g
  }, [hotspots, hotPos])
  const camGeo = useMemo(() => {
    const g = new BufferGeometry()
    const ok = lin(CAMERA_OK)
    const bad = lin(CAMERA_BAD)
    g.setAttribute('position', new BufferAttribute(new Float32Array(camPos.flatMap((p) => [p.x, p.y, p.z])), 3))
    g.setAttribute(
      'aColor',
      new BufferAttribute(
        new Float32Array(cameras.flatMap((c) => (c.status === 'failing' || c.status === 'stale' ? bad : ok).toArray())),
        3,
      ),
    )
    g.setAttribute('aHover', new BufferAttribute(new Float32Array(cameras.length), 1))
    return g
  }, [cameras, camPos])
  useEffect(() => () => hotGeo.dispose(), [hotGeo])
  useEffect(() => () => camGeo.dispose(), [camGeo])
  useHover(hotGeo, hotspots.length, hovered?.kind === 'hotspot' ? hovered.index : -1)
  useHover(camGeo, cameras.length, hovered?.kind === 'camera' ? hovered.index : -1)

  const hotMat = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: hotspotsVertex,
        fragmentShader: hotspotsFragment,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        uniforms: {
          uPx: rt.uniforms.uPx,
          uTime: rt.uniforms.uTime,
          uPulse: { value: rt.reducedMotion ? 0 : 1 },
          uCamDist: { value: 4 },
          uHot: { value: lin('#ff3a12') },
          uCore: { value: lin('#ffd9b0') },
        },
      }),
    [rt],
  )
  const camMat = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: camerasVertex,
        fragmentShader: camerasFragment,
        transparent: true,
        depthWrite: false,
        blending: NormalBlending,
        uniforms: { uPx: rt.uniforms.uPx, uCamDist: { value: 4 } },
      }),
    [rt],
  )
  useEffect(() => () => hotMat.dispose(), [hotMat])
  useEffect(() => () => camMat.dispose(), [camMat])
  useFrame((state) => {
    const d = state.camera.position.length()
    hotMat.uniforms.uCamDist.value = d
    camMat.uniforms.uCamDist.value = d
    hotMat.uniforms.uPulse.value = rt.reducedMotion ? 0 : 1
  }, FRAME.scene)

  // Picking in CSS px against the projected points.
  const latest = useRef({ hotPos, camPos, onHover, onSelect })
  latest.current = { hotPos, camPos, onHover, onSelect }
  useEffect(() => {
    const el = gl.domElement
    const v = new Vector3()
    const toCam = new Vector3()
    const pick = (ev: PointerEvent): Pick | null => {
      const r = el.getBoundingClientRect()
      const x = ev.clientX - r.left
      const y = ev.clientY - r.top
      let best: Pick | null = null
      let bestD = (ev.pointerType === 'touch' ? PICK_PX * 1.8 : PICK_PX) ** 2
      const scan = (list: Vector3[], kind: Pick['kind']) => {
        list.forEach((p, index) => {
          if (toCam.copy(camera.position).sub(p).dot(p) <= 0) return // far side
          v.copy(p).project(camera)
          const sx = ((v.x + 1) / 2) * r.width
          const sy = ((1 - v.y) / 2) * r.height
          const d = (sx - x) ** 2 + (sy - y) ** 2
          if (d < bestD) {
            bestD = d
            best = { kind, index, x: ev.clientX, y: ev.clientY }
          }
        })
      }
      scan(latest.current.camPos, 'camera')
      scan(latest.current.hotPos, 'hotspot')
      return best
    }
    let down: { x: number; y: number } | null = null
    const onMove = (ev: PointerEvent) => {
      if (ev.pointerType === 'mouse' && !down) {
        const p = pick(ev)
        latest.current.onHover(p)
        el.style.cursor = p ? 'pointer' : ''
      }
    }
    const onDown = (ev: PointerEvent) => void (down = { x: ev.clientX, y: ev.clientY })
    const onUp = (ev: PointerEvent) => {
      const wasClick = down && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) < 5
      down = null
      if (!wasClick) return
      const p = pick(ev)
      latest.current.onHover(p)
      if (p) latest.current.onSelect(p)
    }
    const onLeave = () => latest.current.onHover(null)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointerleave', onLeave)
    return () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointerleave', onLeave)
    }
  }, [gl, camera])

  return (
    <>
      <points geometry={hotGeo} material={hotMat} renderOrder={3} frustumCulled={false} />
      <points geometry={camGeo} material={camMat} renderOrder={2} frustumCulled={false} />
    </>
  )
}
