/**
 * The planet: stars, Earth, clouds and atmosphere, the real-time sun (SunClock) and the post chain. The 1k
 * maps load first; each 4k map replaces its 1k version as soon as the worker has decoded it.
 */
import { useThree } from '@react-three/fiber'
import { useEffect, useState } from 'react'
import { Atmosphere, Clouds, Earth, useSphere } from './Earth'
import { Post } from './Post'
import { Stars } from './Stars'
import { SunClock } from './SunClock'
import { disposeTexture, load1k, load4k, MAPS, type EarthTextures } from './textures'

export function Globe() {
  const gl = useThree((s) => s.gl)
  const [textures, setTextures] = useState<EarthTextures | null>(null)
  const sphere = useSphere(160)

  useEffect(() => {
    let live = true
    const aniso = Math.min(8, gl.capabilities.getMaxAnisotropy())
    load1k(aniso).then(async (set) => {
      if (!live) return MAPS.forEach((m) => disposeTexture(set[m]))
      let current = set
      setTextures(current)
      for (const m of MAPS) {
        try {
          const tex = await load4k(m, aniso)
          if (!live) return disposeTexture(tex)
          const old = current[m]
          current = { ...current, [m]: tex }
          setTextures(current)
          // Let the next frame bind the new map before the old one goes.
          requestAnimationFrame(() => requestAnimationFrame(() => disposeTexture(old)))
        } catch (err) {
          console.warn(`4k ${m} map unavailable, keeping 1k`, err)
        }
      }
    })
    return () => {
      live = false
    }
  }, [gl])

  return (
    <>
      <SunClock />
      <Stars />
      {textures && (
        <>
          <Earth textures={textures} geometry={sphere} />
          <Clouds textures={textures} geometry={sphere} />
        </>
      )}
      <Atmosphere />
      <Post />
    </>
  )
}
