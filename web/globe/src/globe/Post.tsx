/**
 * Post, with the source globe's settings (dev-Armaan/satellites src/globe/Post.tsx): a half-float HDR buffer, very
 * mild bloom that only values above 1.0 reach (city-light cores and hotspots), the hue-preserving shoulder tone
 * curve (toneShoulder.ts), film grain within ±3% and a gentle vignette. No chromatic aberration, no lens flare.
 */
import { useThree } from '@react-three/fiber'
import { Bloom, EffectComposer, Noise, Vignette } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'
import { useMemo } from 'react'
import { HalfFloatType } from 'three'
import { ToneShoulderEffect } from './toneShoulder'

export function Post() {
  const dpr = useThree((s) => s.viewport.dpr)
  const tone = useMemo(() => new ToneShoulderEffect(), [])
  return (
    // MSAA only where it pays (DPR < 1.5); points anti-alias in their shaders anyway.
    <EffectComposer frameBufferType={HalfFloatType} multisampling={dpr < 1.5 ? 4 : 0} stencilBuffer={false}>
      <Bloom mipmapBlur luminanceThreshold={1.0} luminanceSmoothing={0.15} intensity={0.45} radius={0.62} levels={6} />
      <primitive object={tone} />
      {/* premultiply: output = colour × noise; NORMAL at 5.5% → luminance-proportional grain within ±3%. */}
      <Noise premultiply blendFunction={BlendFunction.NORMAL} opacity={0.055} />
      <Vignette offset={0.3} darkness={0.42} eskil={false} />
    </EffectComposer>
  )
}
