/**
 * materials — how a surface KIND is painted, for BOTH renderers.
 *
 * The package header long said "geometry here, material from the caller". That
 * line still holds for primitives; the LOOK of a kind, however, is shared truth
 * — both renderers show the same lake. It used to exist twice (client3d
 * `sceneRecipe.plateMaterial/wallMaterial`, the admin preview inline in
 * `FloorPlanPreview`), with different defaults. Only view state (camera, LOD,
 * fades, culling, labels) stays per app.
 *
 * Class `water` (plan-water-rendering.md): water is not recognised by its
 * COLOUR but by what it REFLECTS and how it MOVES. A colormap at
 * `roughness 0.85` delivers neither. Instead of a ShaderMaterial of its own,
 * the standard material is patched (`onBeforeCompile`) — which leaves lights,
 * shadows, fog, tone mapping and the opacity steering of the tile fades
 * untouched.
 *
 * three is a PARAMETER everywhere, never an import.
 */
import type { Material, MeshStandardMaterial, Texture } from 'three'

type THREE = typeof import('three')

/** Declaration of a kind (library → /assets/surface-textures).
 *
 *  Only `water`/`ice` need the shader, and only for the motion resp. the
 *  fresnel reflection. `gloss` and `glow` are plain material values — the
 *  standard material can do both out of the box. */
export interface SurfaceMaterialSpec {
  class: 'matte' | 'water' | 'ice' | 'gloss' | 'glow'
  tint?: string
  map_strength?: number
  wave_m?: number
  speed?: number
  sky_mix?: number
  roughness?: number
  metalness?: number
  /** Emissive strength of class `glow` (0 = off). */
  glow?: number
}

export interface SurfaceMaterialOptions {
  /** Declaration of the kind; missing = matte, i.e. exactly as before. */
  material?: SurfaceMaterialSpec | null
  map?: Texture | null
  /** Mask for COMPOSED surfaces (a coast): red = 1 where the class applies,
   *  0 otherwise. A composition is ONE plate with ONE texture — without a mask
   *  the sand strip of a coast rippled along. Missing, the class applies
   *  everywhere. Read through the TILE UV, not through the world position: the
   *  mask belongs to the tile, the waves run across tile borders. */
  mask?: Texture | null
  /** Fallback colour without a texture (payload style): number 0xrrggbb,
   *  '#rrggbb' or a ready THREE.Color — the callers have all three. */
  color?: number | string | { r: number; g: number; b: number }
  transparent?: boolean
  opacity?: number
  side?: number
  /**
   * Whether the surface writes into the DEPTH buffer. Omitted = three's own
   * default (`true`), which is what every ground before the water mirror
   * wanted.
   *
   * IT IS HERE BECAUSE IT IS PART OF THE KIND'S LOOK, not of the app's view
   * state (E4, "Ein Boden" § G4): a sheet of water is drawn after the opaque
   * world, is occluded by everything in front of it and occludes nothing
   * itself — the bed shows through its shore ramp, and that is the whole
   * point. Writing depth would have the far half of a lake cull the near half
   * of the same lake, because two transparent fragments of one surface are
   * drawn in an order nobody controls.
   */
  depthWrite?: boolean
  /** World metres per texture tile — informative for the wavelength only. */
  roughnessOverride?: number
}

// ── Shared uniforms ─────────────────────────────────────────────────────
// ONE object for every water surface: `updateSurfaceMaterials` advances the
// time, and 50 tiles therefore cost as much as one.
/** THE clock of every animated surface, in seconds — exported because water is
 *  no longer the only thing that moves: the grass sway of the 3D client
 *  (client3d `scene/ground.ts`) hangs on the SAME object, so one tick per
 *  frame advances both and a swaying meadow costs no second uniform. Bind it
 *  under whatever name the shader wants; here it is `uTime`. */
export const surfaceTimeUniform = { value: 0 }
const uSky = { value: { r: 0.62, g: 0.78, b: 0.91 } }

/** Advance the time — once per frame, from the app's render loop. */
export function updateSurfaceMaterials(dt: number): void {
  surfaceTimeUniform.value = (surfaceTimeUniform.value + (dt || 0)) % 3600
}

/** Sky colour for the fresnel share (0xrrggbb). The 3D client hands its
 *  time-of-day colour through, the admin preview a fixed daylight value — water
 *  turns orange in the evening and dark at night without anybody building it. */
export function setSurfaceSky(hex: number): void {
  uSky.value = {
    r: ((hex >> 16) & 255) / 255,
    g: ((hex >> 8) & 255) / 255,
    b: (hex & 255) / 255,
  }
}

// ── Wave normal map ─────────────────────────────────────────────────────
// Procedural, seamless, deterministic: a sum of sine layers with INTEGER
// frequencies is guaranteed to tile. No asset, no download.
let waveNormal: Texture | null = null
/** 1×1 white: without a mask the class applies everywhere. A stand-in texture
 *  instead of a second shader branch — that keeps ONE program for all water. */
let fullMask: Texture | null = null

function makeFullMask(T: THREE): Texture {
  const c = document.createElement('canvas')
  c.width = c.height = 1
  const cx = c.getContext('2d')!
  cx.fillStyle = '#fff'
  cx.fillRect(0, 0, 1, 1)
  const tex = new T.CanvasTexture(c)
  tex.needsUpdate = true
  return tex
}

function makeWaveNormal(T: THREE): Texture {
  const N = 256
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = N
  const ctx = canvas.getContext('2d')!
  const img = ctx.createImageData(N, N)
  // fx, fy integer -> the height is periodic on the unit square.
  const layers: [number, number, number, number][] = [
    // fx, fy, amplitude, phase
    [1, 2, 1.0, 0.0],
    [2, -1, 0.7, 1.7],
    [3, 2, 0.4, 3.1],
    [-2, 3, 0.3, 5.0],
  ]
  const h = (u: number, v: number) => {
    let s = 0
    for (const [fx, fy, a, ph] of layers) {
      s += a * Math.sin(2 * Math.PI * (fx * u + fy * v) + ph)
    }
    return s
  }
  const d = 1 / N
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const u = x / N
      const v = y / N
      // Central differences -> gradient -> normal (tangent space, +z up).
      const dx = (h(u + d, v) - h(u - d, v)) / (2 * d)
      const dy = (h(u, v + d) - h(u, v - d)) / (2 * d)
      const sc = 0.02
      let nx = -dx * sc
      let ny = -dy * sc
      const nz = 1
      const len = Math.hypot(nx, ny, nz) || 1
      nx /= len
      ny /= len
      const i = (y * N + x) * 4
      img.data[i] = Math.round((nx * 0.5 + 0.5) * 255)
      img.data[i + 1] = Math.round((ny * 0.5 + 0.5) * 255)
      img.data[i + 2] = Math.round((nz / len * 0.5 + 0.5) * 255)
      img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
  const tex = new T.CanvasTexture(canvas)
  tex.wrapS = tex.wrapT = T.RepeatWrapping
  tex.needsUpdate = true
  return tex
}

// ── Shader patch ────────────────────────────────────────────────────────
// The anchors in the standard shader. If one is not found (a three upgrade),
// ONLY that part is skipped — matte beats broken.
//
// EVERY anchor is an `#include` LINE, and that is no accident: `onBeforeCompile`
// gets the shader BEFORE three resolves the includes. The anchor for the ripple
// was a line out of the chunk BODY at first — which is never there, so the
// water stayed mirroring but motionless while the other three patches worked
// (finding 2026-07-29). A search in the three sources finds both and therefore
// proves nothing.
const ANCHOR_VERT = '#include <begin_vertex>'
const ANCHOR_NORMAL = '#include <normal_fragment_maps>'
const ANCHOR_MAP = '#include <map_fragment>'
const ANCHOR_ROUGH = '#include <roughnessmap_fragment>'
const ANCHOR_OUT = '#include <opaque_fragment>'

let warned = false
function warnOnce(what: string): void {
  if (warned) return
  warned = true
  console.warn(`[scene-render] water shader: anchor "${what}" not found in this `
    + 'three version — the surface renders matte instead. One line to re-point.')
}

/** Whatever the caller has -> a THREE.Color. */
function toColor(T: THREE, c: number | string | { r: number; g: number; b: number } | undefined) {
  if (c === undefined || c === null) return new T.Color(0xffffff)
  if (typeof c === 'number') return new T.Color(c)
  if (typeof c === 'string') return new T.Color(c)
  return new T.Color(c.r, c.g, c.b)
}

function hex3(hex?: string): { r: number; g: number; b: number } {
  const v = parseInt((hex || '#3f7fb8').slice(1), 16)
  return { r: ((v >> 16) & 255) / 255, g: ((v >> 8) & 255) / 255, b: (v & 255) / 255 }
}

function applyWaterShader(mat: MeshStandardMaterial, spec: SurfaceMaterialSpec,
                          mask: Texture): void {
  const uWave = { value: Math.max(spec.wave_m ?? 1.6, 0.05) }
  const uSpeed = { value: spec.speed ?? 0.05 }
  const uSkyMix = { value: spec.sky_mix ?? 0.55 }
  const uTint = { value: hex3(spec.tint) }
  const uMapStrength = { value: spec.map_strength ?? 0.75 }
  const uMask = { value: mask }

  // Kein Typ am Parameter: three leitet ihn aus `onBeforeCompile` her.
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = surfaceTimeUniform
    shader.uniforms.uSky = uSky
    shader.uniforms.uWaveM = uWave
    shader.uniforms.uSpeed = uSpeed
    shader.uniforms.uSkyMix = uSkyMix
    shader.uniforms.uTint = uTint
    shader.uniforms.uMapStrength = uMapStrength
    shader.uniforms.uMask = uMask

    // Two varyings of its own, because they are two different things:
    // vWaterWorld is the WORLD position (the ripple runs across tile borders;
    // plate UVs would give a visible seam), vWaterUv the TILE UV (the mask
    // belongs to this one tile).
    if (shader.vertexShader.includes(ANCHOR_VERT)) {
      shader.vertexShader = 'varying vec2 vWaterWorld;\nvarying vec2 vWaterUv;\n'
        + shader.vertexShader.replace(ANCHOR_VERT,
          `${ANCHOR_VERT}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;`
          + '\n  vWaterUv = uv;')
    } else {
      warnOnce(ANCHOR_VERT)
      return
    }

    shader.fragmentShader = 'varying vec2 vWaterWorld;\nvarying vec2 vWaterUv;\n'
      + 'uniform float uTime;\nuniform vec3 uSky;\nuniform float uWaveM;\n'
      + 'uniform float uSpeed;\nuniform float uSkyMix;\nuniform vec3 uTint;\n'
      + 'uniform float uMapStrength;\nuniform sampler2D uMask;\n'
      + shader.fragmentShader

    // 1) Two counter-scrolling layers of the same normal map — limited to the
    //    water share, or the sand of a coast ripples along. It REPLACES the
    //    standard chunk instead of standing behind it: that chunk's single,
    //    motionless lookup would otherwise run first and bend `normal` before
    //    the tangent frame is built from it.
    if (shader.fragmentShader.includes(ANCHOR_NORMAL)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_NORMAL, `
  // tbn comes from normal_fragment_begin and exists only with this define
  // — without the guard this would be a compile error instead of a matte
  // material.
  #ifdef USE_NORMALMAP_TANGENTSPACE
  {
    float wMask = texture2D( uMask, vWaterUv ).r;
    // The offset is divided by the wavelength of the RESPECTIVE layer —
    // which makes uSpeed real METRES PER SECOND, and both layers drift at the
    // same speed although their wavelengths differ. Without the division
    // uSpeed was "wavelengths per second": 0.05 meant one crest every 20
    // seconds, 1.7 cm/s on the map — present, but invisible.
    float wDriftA = uTime * uSpeed / uWaveM;
    float wDriftB = uTime * uSpeed / ( uWaveM * 0.63 );
    vec2 wUvA = vWaterWorld / uWaveM + vec2( wDriftA, wDriftA * 0.6 );
    vec2 wUvB = vWaterWorld / ( uWaveM * 0.63 ) - vec2( wDriftB * 0.8, wDriftB * 1.3 );
    vec3 wN = normalize( ( texture2D( normalMap, wUvA ).xyz * 2.0 - 1.0 )
                       + ( texture2D( normalMap, wUvB ).xyz * 2.0 - 1.0 ) );
    wN = mix( vec3( 0.0, 0.0, 1.0 ), wN, wMask );
    wN.xy *= normalScale;
    normal = normalize( tbn * wN );
  }
  #endif`)
    } else {
      warnOnce(ANCHOR_NORMAL)
    }

    // 2) Mix the texture against the base tint — a generated water texture
    //    with baked-in highlights must not compete with the shader. Outside
    //    the mask the texture stays untouched.
    if (shader.fragmentShader.includes(ANCHOR_MAP)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_MAP,
        `${ANCHOR_MAP}\n  diffuseColor.rgb = mix( uTint, diffuseColor.rgb,`
        + ' mix( 1.0, uMapStrength, texture2D( uMask, vWaterUv ).r ) );')
    } else {
      warnOnce(ANCHOR_MAP)
    }

    // 2b) Lower the roughness in the water share only — otherwise the sand
    //     strip shines like wet glass.
    if (shader.fragmentShader.includes(ANCHOR_ROUGH)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_ROUGH,
        `${ANCHOR_ROUGH}\n  roughnessFactor = mix( 0.85, roughnessFactor,`
        + ' texture2D( uMask, vWaterUv ).r );')
    } else {
      warnOnce(ANCHOR_ROUGH)
    }

    // 3) Fresnel towards the sky colour. The COLOUR only — alpha stays on the
    //    standard path, or the fade steering of the tiles would break.
    if (shader.fragmentShader.includes(ANCHOR_OUT)) {
      shader.fragmentShader = shader.fragmentShader.replace(ANCHOR_OUT, `
  {
    float wFres = pow( 1.0 - saturate( dot( normalize( vViewPosition ), normal ) ), 3.0 );
    outgoingLight = mix( outgoingLight, uSky,
                         clamp( wFres * uSkyMix, 0.0, 1.0 )
                         * texture2D( uMask, vWaterUv ).r );
  }
  ${ANCHOR_OUT}`)
    } else {
      warnOnce(ANCHOR_OUT)
    }
  }
  // Without the key three recompiles per material.
  mat.customProgramCacheKey = () => 'anima-water'
}

/**
 * The material of ONE surface. `matte` (the default) is exactly the standard
 * material as before — the function is then only the ONE place the defaults
 * live instead of three places in two apps.
 */
export function surfaceMaterial(T: THREE, opts: SurfaceMaterialOptions): Material {
  const spec = opts.material || null
  const cls = spec?.class || 'matte'
  // Water and ice are the same surface — ice merely stands still (speed 0).
  // That is not convenience: a frozen surface reflects and carries surface
  // structure, it just does not flow.
  const rippled = cls === 'water' || cls === 'ice'
  const params: Record<string, unknown> = {
    roughness: spec?.roughness ?? (rippled ? 0.08 : cls === 'gloss' ? 0.25 : 0.85),
    metalness: spec?.metalness ?? (rippled ? 0.15 : 0.02),
  }
  if (opts.map) params.map = opts.map
  else params.color = toColor(T, opts.color ?? (rippled ? spec?.tint : 0xffffff))
  if (opts.transparent) params.transparent = true
  if (opts.opacity !== undefined) params.opacity = opts.opacity
  if (opts.side !== undefined) params.side = opts.side
  if (opts.depthWrite !== undefined) params.depthWrite = opts.depthWrite

  const mat = new T.MeshStandardMaterial(params as never)

  if (cls === 'glow') {
    // The texture glows BY ITSELF: the same image as emissiveMap, the tint as
    // colour. Without it neon is merely painted bright and stays as dark in a
    // night scene as the ground next to it.
    const c = toColor(T, spec?.tint ?? 0xffffff)
    mat.emissive = c
    mat.emissiveIntensity = spec?.glow ?? 1
    if (opts.map) mat.emissiveMap = opts.map
  }

  if (rippled) {
    if (!waveNormal) waveNormal = makeWaveNormal(T)
    mat.normalMap = waveNormal as Texture
    mat.normalScale = new T.Vector2(1, 1)
    if (!fullMask) fullMask = makeFullMask(T)
    applyWaterShader(mat, spec as SurfaceMaterialSpec,
                     (opts.mask || fullMask) as Texture)
  }
  return mat
}

/** Release the shared helper textures (app teardown). */
export function disposeSurfaceMaterials(): void {
  waveNormal?.dispose()
  waveNormal = null
  fullMask?.dispose()
  fullMask = null
}
