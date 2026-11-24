/**
 * Per-canvas mutable state shared by the globe's components, read and written every frame outside React.
 * Uniform objects are shared by reference, so one write (the sun, the cloud drift) reaches every material.
 * The painted-imagery uniforms of the source globe (shaders/chunks.ts PAINT) are kept, switched off: the Global
 * View paints no regional imagery, but the Earth and cloud shaders are used unchanged.
 */
import { createContext, useContext } from 'react'
import { Vector2, Vector3, Vector4, type Texture } from 'three'

/** useFrame priorities: the clock runs before everything that reads the sun or GMST. */
export const FRAME = { clock: -30, scene: -10 } as const

type U<T> = { value: T }

export interface GlobeRuntime {
  gmst: number
  reducedMotion: boolean
  uniforms: {
    uSunDir: U<Vector3>
    uCloudOffset: U<number>
    uCloudMap: U<Texture | null>
    uPx: U<number>
    uTime: U<number>
  }
  paint: {
    uCtxMap: U<Texture | null>
    uCtxUv: U<Vector4>
    uCtxOn: U<number>
    uCtxLod: U<number>
    uDecalMap: U<Texture | null>
    uDecalUv: U<Vector4>
    uDecalOn: U<number>
    uDecal2Map: U<Texture | null>
    uDecal2Uv: U<Vector4>
    uDecal2On: U<number>
    uDecalLit: U<number>
    uDecal2Lit: U<number>
    uScanT0: U<Vector3>
    uScanS: U<number>
    uFull: U<number>
    uFreshRad: U<number>
    uPanelHalf: U<number>
    uPanelTurn: U<Vector2>
    uDayLod: U<number>
    uCloudFade: U<number>
  }
}

export function createRuntime(reducedMotion: boolean): GlobeRuntime {
  return {
    gmst: 0,
    reducedMotion,
    uniforms: {
      uSunDir: { value: new Vector3(1, 0, 0) },
      uCloudOffset: { value: 0 },
      uCloudMap: { value: null },
      uPx: { value: 1 },
      uTime: { value: 0 },
    },
    paint: {
      uCtxMap: { value: null },
      uCtxUv: { value: new Vector4(0.5, 0.5, 1, 1) },
      uCtxOn: { value: 0 },
      uCtxLod: { value: 0 },
      uDecalMap: { value: null },
      uDecalUv: { value: new Vector4(0.5, 0.5, 1, 1) },
      uDecalOn: { value: 0 },
      uDecal2Map: { value: null },
      uDecal2Uv: { value: new Vector4(0.5, 0.5, 1, 1) },
      uDecal2On: { value: 0 },
      uDecalLit: { value: 0 },
      uDecal2Lit: { value: 0 },
      uScanT0: { value: new Vector3(1, 0, 0) },
      uScanS: { value: 0 },
      uFull: { value: 1 },
      uFreshRad: { value: 0 },
      uPanelHalf: { value: 0 },
      uPanelTurn: { value: new Vector2(1, 0) },
      uDayLod: { value: 0 },
      uCloudFade: { value: 1 },
    },
  }
}

export const RuntimeContext = createContext<GlobeRuntime | null>(null)

export function useRuntime(): GlobeRuntime {
  const rt = useContext(RuntimeContext)
  if (!rt) throw new Error('useRuntime outside <RuntimeContext>')
  return rt
}
