/**
 * Progressive Earth maps: the 1k set (~0.2 MB) loads first so the planet appears at once, then each map is
 * swapped for its 4k version, decoded in a Web Worker (textureDecode.worker.ts) so the main thread never blocks
 * on a 4k decode. Texture settings follow the source globe: colour maps are sRGB, the data map (elevation R,
 * ocean mask G) and clouds are raw; clouds wrap in longitude because they drift.
 */
import {
  ClampToEdgeWrapping,
  LinearFilter,
  LinearMipmapLinearFilter,
  NoColorSpace,
  RepeatWrapping,
  SRGBColorSpace,
  Texture,
  TextureLoader,
} from 'three'

export type EarthMap = 'day' | 'night' | 'clouds' | 'data'
export type EarthTextures = Record<EarthMap, Texture>
export const MAPS: EarthMap[] = ['day', 'night', 'clouds', 'data']

const url = (map: EarthMap, res: '1k' | '4k') => `${import.meta.env.BASE_URL}textures/earth-${map}-${res}.webp`

function configure(tex: Texture, map: EarthMap, anisotropy: number) {
  tex.colorSpace = map === 'day' || map === 'night' ? SRGBColorSpace : NoColorSpace
  // Clouds drift in longitude, so they wrap horizontally; the others clamp to avoid a seam bleed at the poles.
  tex.wrapS = map === 'clouds' ? RepeatWrapping : ClampToEdgeWrapping
  tex.wrapT = ClampToEdgeWrapping
  tex.minFilter = LinearMipmapLinearFilter
  tex.magFilter = LinearFilter
  tex.generateMipmaps = true
  tex.anisotropy = map === 'data' ? 1 : anisotropy
}

export async function load1k(anisotropy: number): Promise<EarthTextures> {
  const loader = new TextureLoader()
  const list = await Promise.all(MAPS.map((m) => loader.loadAsync(url(m, '1k'))))
  const out = {} as EarthTextures
  MAPS.forEach((m, i) => {
    configure(list[i], m, anisotropy)
    out[m] = list[i]
  })
  return out
}

let worker: Worker | null = null
let nextId = 0
const pending = new Map<number, { resolve: (b: ImageBitmap) => void; reject: (e: Error) => void }>()

function decoder(): Worker {
  if (worker) return worker
  worker = new Worker(new URL('./textureDecode.worker.ts', import.meta.url), { type: 'module', name: 'textures' })
  worker.onmessage = (ev: MessageEvent<{ id: number; bitmap?: ImageBitmap; error?: string }>) => {
    const p = pending.get(ev.data.id)
    pending.delete(ev.data.id)
    if (!p) return
    if (ev.data.bitmap) p.resolve(ev.data.bitmap)
    else p.reject(new Error(ev.data.error ?? 'decode failed'))
  }
  return worker
}

/** Fetch and decode one 4k map (off the main thread) into a texture ready to upload. */
export async function load4k(map: EarthMap, anisotropy: number): Promise<Texture> {
  const res = await fetch(url(map, '4k'))
  if (!res.ok) throw new Error(`${url(map, '4k')}: HTTP ${res.status}`)
  const blob = await res.blob()
  const id = nextId++
  const bitmap = await new Promise<ImageBitmap>((resolve, reject) => {
    pending.set(id, { resolve, reject })
    decoder().postMessage({ id, blob })
  })
  const tex = new Texture(bitmap)
  tex.flipY = false // already flipped by the worker
  configure(tex, map, anisotropy)
  tex.needsUpdate = true
  return tex
}

export function disposeTexture(tex: Texture) {
  const img = tex.image as { close?: () => void } | undefined
  tex.dispose()
  img?.close?.()
}
