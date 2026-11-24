/**
 * The real sky, every frame: sun direction and GMST from the current UTC time (src/lib/geo.ts), the slow cloud
 * drift (frozen under prefers-reduced-motion) and the device pixel ratio the point shaders size their marks by.
 */
import { useFrame } from '@react-three/fiber'
import { gmst, sunDirectionWorld } from '@/lib/geo'
import { FRAME, useRuntime } from './runtime'

/** One full turn of the cloud map every 8 hours, as in the source globe. */
const CLOUD_DRIFT_PER_S = 1 / (8 * 3600)

export function SunClock() {
  const rt = useRuntime()
  useFrame((state, dt) => {
    const now = Date.now()
    sunDirectionWorld(now, rt.uniforms.uSunDir.value)
    rt.gmst = gmst(now)
    rt.uniforms.uTime.value = state.clock.elapsedTime
    if (!rt.reducedMotion)
      rt.uniforms.uCloudOffset.value = (rt.uniforms.uCloudOffset.value + 1 - Math.min(dt, 0.1) * CLOUD_DRIFT_PER_S) % 1
    rt.uniforms.uPx.value = state.gl.getPixelRatio()
  }, FRAME.clock)
  return null
}
