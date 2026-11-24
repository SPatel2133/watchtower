/**
 * Orbit camera: smooth damped OrbitControls (no pan, no bounce), zoom clamped above the surface, rotation slowed
 * as the camera gets close. A very slow auto-rotation runs until the first interaction (never under reduced
 * motion). flyTo() eases the camera along the great circle to a point, keeping or tightening the distance;
 * under reduced motion it cuts straight there.
 */
import { OrbitControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { forwardRef, useImperativeHandle, useRef } from 'react'
import { Vector3 } from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { latLonToWorld } from '@/lib/geo'
import { useRuntime } from './runtime'

export const MIN_DISTANCE = 1.22
export const MAX_DISTANCE = 9
const FLY_S = 1.6
const FLY_DISTANCE = 2.1

export interface CameraRigHandle {
  flyTo(lat: number, lon: number): void
}

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)

export const CameraRig = forwardRef<CameraRigHandle>(function CameraRig(_, ref) {
  const rt = useRuntime()
  const camera = useThree((s) => s.camera)
  const controls = useRef<OrbitControlsImpl>(null)
  const touched = useRef(false)
  const flight = useRef<{ from: Vector3; to: Vector3; d0: number; d1: number; t: number } | null>(null)

  useImperativeHandle(ref, () => ({
    flyTo(lat, lon) {
      touched.current = true
      const to = latLonToWorld(lat, lon)
      const d0 = camera.position.length()
      const d1 = Math.min(d0, FLY_DISTANCE)
      if (rt.reducedMotion) {
        camera.position.copy(to.multiplyScalar(d1))
        controls.current?.update()
        return
      }
      flight.current = { from: camera.position.clone().normalize(), to, d0, d1, t: 0 }
    },
  }))

  const dir = new Vector3()
  useFrame((_, dt) => {
    const c = controls.current
    if (!c) return
    const d = camera.position.length()
    c.rotateSpeed = Math.min(0.55, 0.12 + 0.45 * ((d - 1) / 3))
    c.autoRotate = !touched.current && !rt.reducedMotion
    const f = flight.current
    if (f) {
      f.t = Math.min(1, f.t + dt / FLY_S)
      const k = ease(f.t)
      const angle = f.from.angleTo(f.to)
      dir.copy(f.from)
      if (angle > 1e-5) {
        const axis = new Vector3().crossVectors(f.from, f.to).normalize()
        dir.applyAxisAngle(axis, angle * k)
      }
      camera.position.copy(dir.multiplyScalar(f.d0 + (f.d1 - f.d0) * k))
      camera.lookAt(0, 0, 0)
      if (f.t >= 1) flight.current = null
    }
    c.enabled = !flight.current
  })

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enablePan={false}
      enableDamping
      dampingFactor={0.06}
      zoomSpeed={0.6}
      minDistance={MIN_DISTANCE}
      maxDistance={MAX_DISTANCE}
      autoRotateSpeed={0.12}
      onStart={() => {
        touched.current = true
        flight.current = null
      }}
    />
  )
})
