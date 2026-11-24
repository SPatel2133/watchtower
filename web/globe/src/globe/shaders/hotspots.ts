/**
 * Fire hotspots and camera markers as point sprites on the surface (Watchtower's own layer, not from the source
 * globe). Sizes are CSS px × uPx, like the source's stars.
 *
 * Hotspots: hot orange-red (uHot), far redder than the sodium-amber city lights (#FFB070), with a white-hot core.
 * Size and brightness grow with log FRP; opacity follows confidence (aConf: low 0.35, nominal 0.7, high 1).
 * Points younger than 3 h (aRecent = 1) pulse gently (uPulse = 0 under reduced motion); older ones are static and
 * dimmer. Cores are written above 1.0 so the bloom picks them up, as it does city-light cores.
 */
import { glsl, OUTPUT } from './chunks'

export const hotspotsVertex = glsl`
  attribute float aFrp;
  attribute float aConf;
  attribute float aRecent;
  attribute float aPhase;
  attribute float aHover;
  uniform float uPx;
  uniform float uTime;
  uniform float uPulse;
  uniform float uCamDist;
  varying float vAlpha;
  varying float vGain;
  varying float vSize;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * viewMatrix * world;
    // Back of the planet: the Earth's depth hides it, but fade at the limb so points don't pile up there.
    vec3 n = normalize(world.xyz);
    float facing = dot(n, normalize(cameraPosition - world.xyz));
    float f = log(1.0 + max(aFrp, 0.0));                 // FRP 1 → 0.7, 10 → 2.4, 100 → 4.6, 1000 → 6.9
    float pulse = aRecent * uPulse * (0.5 + 0.5 * sin(uTime * 2.2 + aPhase));
    float zoom = clamp(3.2 / uCamDist, 0.85, 2.2);
    float size = (3.0 + 1.25 * f) * zoom * (1.0 + 0.22 * pulse) * (1.0 + 0.6 * aHover);
    vSize = max(size * uPx, 1.5);
    gl_PointSize = vSize + 1.0;
    vGain = (1.15 + 0.32 * f) * mix(0.72, 1.0, aRecent) * (1.0 + 0.25 * pulse) * (1.0 + 0.5 * aHover);
    vAlpha = aConf * smoothstep(-0.02, 0.12, facing);
  }
`

export const hotspotsFragment = glsl`
  uniform vec3 uHot;
  uniform vec3 uCore;
  varying float vAlpha;
  varying float vGain;
  varying float vSize;
  void main() {
    float r = length(gl_PointCoord - 0.5) * 2.0 * (vSize + 1.0) / vSize;   // 0 centre, 1 rim
    float core = 1.0 - smoothstep(0.0, 0.42, r);
    float glow = exp(-r * r * 4.5) * (1.0 - smoothstep(0.85, 1.0, r));
    float a = vAlpha * max(core, glow);
    if (a < 0.003) discard;
    vec3 col = mix(uHot * glow, uCore, core * core) * vGain;
    gl_FragColor = vec4(col, a);
    ${OUTPUT}
  }
`

/** Camera markers: a small cool-white ring with a dot, red (uniform per point colour) when failing or stale. */
export const camerasVertex = glsl`
  attribute vec3 aColor;
  attribute float aHover;
  uniform float uPx;
  uniform float uCamDist;
  varying vec3 vColor;
  varying float vAlpha;
  varying float vSize;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * viewMatrix * world;
    float facing = dot(normalize(world.xyz), normalize(cameraPosition - world.xyz));
    float zoom = clamp(3.2 / uCamDist, 0.9, 1.8);
    vSize = 7.0 * zoom * uPx * (1.0 + 0.4 * aHover);
    gl_PointSize = vSize + 1.0;
    vColor = aColor;
    vAlpha = 0.9 * smoothstep(-0.02, 0.12, facing);
  }
`

export const camerasFragment = glsl`
  varying vec3 vColor;
  varying float vAlpha;
  varying float vSize;
  void main() {
    float px = length(gl_PointCoord - 0.5) * (vSize + 1.0);   // distance from centre, device px
    float ring = 1.0 - smoothstep(0.6, 1.4, abs(px - vSize * 0.38));
    float dot_ = 1.0 - smoothstep(0.8, 1.6, px);
    float a = vAlpha * max(ring, dot_);
    if (a < 0.003) discard;
    gl_FragColor = vec4(vColor, a);
    ${OUTPUT}
  }
`
