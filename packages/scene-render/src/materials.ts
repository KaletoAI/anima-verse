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
  /** Metres per second of STILL water — a lake, an ice sheet, any surface
   *  whose `aWaterFlow` attribute reads (0, 0). */
  speed?: number
  /** Metres per second of FLOWING water — used only where the flow attribute
   *  is non-zero (a river). One number could not serve both: a lake
   *  counter-scrolls its two ripple layers, so the net motion reads slow,
   *  while a river sends both downstream and the very same number reads
   *  fast (user finding 2026-08-23). A single AREA may run faster or slower
   *  than its kind — that override rides on the LENGTH of the flow attribute
   *  and multiplies this number (`waterFlowFactor`). */
  flow_speed?: number
  sky_mix?: number
  roughness?: number
  metalness?: number
  /** Emissive strength of class `glow` (0 = off). */
  glow?: number
}

/** What a water KIND flows at when it declares no `flow_speed`, in m/s — the
 *  mirror of `core.surface_textures._MATERIAL_RANGES['flow_speed']`. Raised
 *  from 0.08 to 0.15 on 2026-08-23 ("the river now moves too slowly"): once the
 *  ripple ran downstream instead of upstream, 0.08 read as a standing river. */
export const WATER_FLOW_SPEED_DEFAULT_M_S = 0.15

/** The fastest a water may be dialled to, in m/s — the same ceiling the kind's
 *  own dial has, so an AREA can ask for nothing a kind could not have asked
 *  for. */
export const WATER_FLOW_SPEED_MAX_M_S = 2

/**
 * The smallest factor a FLOWING water may carry, and it is a hard floor rather
 * than a rounding.
 *
 * The factor rides on the LENGTH of `aWaterFlow`, and the fragment reads a
 * length below `1e-4` as STILL — the state of a lake, which drifts at `uSpeed`
 * (0.25 m/s), i.e. FASTER. An authored 0 m/s therefore must not reach the
 * shader as a zero-length vector: it is floored to `1e-3`, ten times the still
 * threshold, which on the default kind is 0.15 mm/s — one wavelength in about
 * three hours, a river standing still while keeping every flowing trait
 * (streaks, anisotropy, the downstream sign) that "still" would drop.
 */
export const WATER_FLOW_FACTOR_MIN = 1e-3

/**
 * How much faster (or slower) ONE painted area runs than its kind — the number
 * the renderer multiplies `uFlowSpeed` by, encoded as the LENGTH of the
 * per-vertex flow attribute.
 *
 * `areaSpeedMs` is the area's own `meta.flow_speed_m_s` (free-form meta, so
 * anything may arrive); `kindSpeedMs` is the kind's `flow_speed` dial. The
 * answer is EXACTLY 1 wherever the area authors nothing readable, which is what
 * keeps every existing water bit-identical: the attribute stays the unit
 * tangent it has been since W4a.
 *
 * Why a RATIO and not the absolute speed: the shader's `uFlowSpeed` is the
 * kind's uniform and one material serves every area of that kind — the area may
 * only scale what the material already carries. A kind that does not flow at
 * all (`flow_speed` 0, e.g. ice) therefore cannot be made to flow by an area:
 * `0 × anything` is 0, and 1 is returned so nothing pretends otherwise.
 */
export function waterFlowFactor(areaSpeedMs: unknown,
                                kindSpeedMs: number | undefined): number {
  // `Number(null)`, `Number('')` and `Number([])` are all 0 — a missing key
  // would otherwise read as "this river stands still".
  if (typeof areaSpeedMs !== 'number'
      && !(typeof areaSpeedMs === 'string' && areaSpeedMs.trim() !== '')) return 1
  const area = Number(areaSpeedMs)
  if (!Number.isFinite(area)) return 1
  const kind = typeof kindSpeedMs === 'number' && Number.isFinite(kindSpeedMs)
    ? kindSpeedMs
    : WATER_FLOW_SPEED_DEFAULT_M_S
  if (kind <= 0) return 1
  const speed = Math.min(Math.max(area, 0), WATER_FLOW_SPEED_MAX_M_S)
  return Math.max(speed / kind, WATER_FLOW_FACTOR_MIN)
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
  // Anisotropic filtering, because a lake is nearly always seen at a grazing
  // angle: an isotropic mip has to pick the WIDER of the two footprints, so it
  // either blurs the ripple away across the view direction or aliases it along
  // it. three clamps this to what the device offers, so 4 is a wish, not a
  // requirement.
  tex.anisotropy = 4
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
  const uFlowSpeed = { value: spec.flow_speed ?? WATER_FLOW_SPEED_DEFAULT_M_S }
  const uSkyMix = { value: spec.sky_mix ?? 0.55 }
  const uTint = { value: hex3(spec.tint) }
  const uMapStrength = { value: spec.map_strength ?? 0.75 }
  const uMask = { value: mask }

  // No type on the parameter: three infers it from `onBeforeCompile`.
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = surfaceTimeUniform
    shader.uniforms.uSky = uSky
    shader.uniforms.uWaveM = uWave
    shader.uniforms.uSpeed = uSpeed
    shader.uniforms.uFlowSpeed = uFlowSpeed
    shader.uniforms.uSkyMix = uSkyMix
    shader.uniforms.uTint = uTint
    shader.uniforms.uMapStrength = uMapStrength
    shader.uniforms.uMask = uMask

    // Three varyings of its own, because they are three different things:
    // vWaterWorld is the WORLD position (the ripple runs across tile borders;
    // plate UVs would give a visible seam), vWaterUv the TILE UV (the mask
    // belongs to this one tile), and vWaterFlow the DOWNSTREAM direction of
    // this one water area (W2 no. 2).
    //
    // THE FLOW IS AN ATTRIBUTE, NOT A UNIFORM, and that is the whole reason it
    // can exist at all: this material is shared by every area of one KIND
    // (client3d `ground.rebuildAreas` keeps exactly one per kind, so two lakes
    // at two heights cost two draw calls and one program), while the flow
    // belongs to the AREA. A uniform would have meant one material per area.
    // Two floats on a mesh of a dozen vertices is nothing by comparison.
    //
    // A GEOMETRY WITHOUT THE ATTRIBUTE READS (0, 0). WebGL leaves an unbound
    // attribute at its generic value, which three never writes and which starts
    // at (0, 0, 0, 1) — and (0, 0) is precisely what the fragment spells "still
    // water". So every water surface that is not a client3d mirror (the admin
    // preview's floors, above all) keeps exactly the look it had.
    if (shader.vertexShader.includes(ANCHOR_VERT)) {
      shader.vertexShader = 'attribute vec2 aWaterFlow;\n'
        + 'varying vec2 vWaterWorld;\nvarying vec2 vWaterUv;\n'
        + 'varying vec2 vWaterFlow;\n'
        + shader.vertexShader.replace(ANCHOR_VERT,
          `${ANCHOR_VERT}\n  vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;`
          + '\n  vWaterUv = uv;\n  vWaterFlow = aWaterFlow;')
    } else {
      warnOnce(ANCHOR_VERT)
      return
    }

    shader.fragmentShader = 'varying vec2 vWaterWorld;\nvarying vec2 vWaterUv;\n'
      + 'varying vec2 vWaterFlow;\n'
      + 'uniform float uTime;\nuniform vec3 uSky;\nuniform float uWaveM;\n'
      + 'uniform float uSpeed;\nuniform float uFlowSpeed;\n'
      + 'uniform float uSkyMix;\nuniform vec3 uTint;\n'
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
    // HOW MUCH OF THE RIPPLE THIS PIXEL CAN STILL RESOLVE (finding round
    // 2026-08-21). One pixel covers wPx metres of water; once that reaches a
    // whole wavelength the normal map carries no signal a pixel could show, and
    // what is left is sampling noise — which at roughness 0.08 lands in a
    // specular lobe narrow enough to turn every noisy texel into a spark. The
    // mip chain does not save it: averaging normals SHORTENS them instead of
    // widening the lobe, so the highlights stay as tight as they were. Fading
    // the perturbation back to flat over that same footprint is the cheap,
    // standard answer, and it is also the truthful picture — a lake a
    // kilometre off is a mirror, not a texture.
    //
    // MEASURED ON THE WORLD POSITION, never on the sampled normal: vWaterWorld
    // is continuous by construction (the mirror is a plane), while a derivative
    // of what comes back from a texture jumps wherever the texture does — the
    // very lesson scene-render layerCut.ts spells out.
    float wPx = max( length( dFdx( vWaterWorld ) ), length( dFdy( vWaterWorld ) ) );
    float wDetail = clamp( 1.0 - wPx / uWaveM, 0.0, 1.0 );
    // THE DIRECTION THE TWO LAYERS SCROLL IN (W2 no. 2). The frame is the
    // FLOW's: wAx points downstream, wAy across it. With no flow (vWaterFlow
    // == (0, 0), i.e. a lake, an ice sheet, or any surface that carries no
    // attribute at all) the frame is the world's own axes and every ternary
    // below takes its still branch — which reproduces, constant for constant,
    // the shader that stood here before.
    //
    // The division is by a FLOORED length, never by the raw one: a still
    // surface hands over (0, 0), and a normalize() of that is a NaN that the
    // ternary would not reliably keep out of the result.
    float wLen = length( vWaterFlow );
    bool wStill = wLen < 1e-4;
    vec2 wAx = wStill ? vec2( 1.0, 0.0 ) : vWaterFlow / max( wLen, 1e-4 );
    vec2 wAy = vec2( -wAx.y, wAx.x );
    // TWO SPEEDS, NOT ONE (user finding 2026-08-23: "the water flows too fast
    // and the direction is not clearly recognisable"). A lake counter-scrolls
    // its two layers, so they cancel and the net motion reads slow; a river
    // sends BOTH downstream, so the identical number reads several times
    // faster. One dial cannot serve both, and lowering it would freeze the
    // lakes. uSpeed stays the still-water number, uFlowSpeed is the river's.
    //
    // …AND THE LENGTH OF THE FLOW IS THE AREA'S OWN FACTOR (finding
    // 2026-08-23 no. 2, meta.flow_speed_m_s). The attribute has always been
    // a UNIT tangent, so wLen was 1.0 on every flowing water and this
    // multiplication changes not one existing pixel; an area that authors its
    // own speed sends the ratio (area m/s ÷ kind m/s) as that length instead,
    // and uFlowSpeed · wLen is the area's metres per second again. The
    // DIRECTION is untouched — wAx divides the very same vector by wLen — and
    // so is the still branch: the encoder floors the factor at 1e-3, ten times
    // the 1e-4 threshold below, so a river dialled to 0 never turns into a
    // lake drifting at uSpeed.
    float wSpeed = wStill ? uSpeed : uFlowSpeed * wLen;
    // The offset is divided by the wavelength of the RESPECTIVE layer —
    // which makes the speed real METRES PER SECOND, and both layers drift at
    // the same rate although their wavelengths differ. Without the division it
    // would be "wavelengths per second": 0.05 meant one crest every 20
    // seconds, 1.7 cm/s on the map — present, but invisible.
    //
    // AND THE SIGN. Adding v·t to a SAMPLE coordinate slides the picture the
    // OTHER way — uv + vec2( t, 0 ) is the classic leftward scroll. So the
    // offset that has stood here since the lake was written carries the crests
    // AGAINST wDirA, i.e. upstream on a river, which is the second half of
    // "the flow direction is not clearly recognisable": the ripple ran the
    // wrong way. Flowing water therefore drifts by −1, and the crests travel
    // along wDirA the way the vector says.
    //
    // Still water keeps the +1 it always had, deliberately: a lake has no
    // reference direction — its two sheets counter-scroll either way, and the
    // requirement is that it looks EXACTLY as it did, not that it agrees with
    // a river about a sign nobody can see on it.
    float wFlowSign = wStill ? 1.0 : -1.0;
    float wDriftA = uTime * wSpeed * wFlowSign / uWaveM;
    float wDriftB = uTime * wSpeed * wFlowSign / ( uWaveM * 0.63 );
    // THE CROSS COMPONENTS. Still water wants the two sheets to run across
    // each other — (1, 0.6) and −(0.8, 1.3) counter-scrolling is what a lake
    // looks like. A river must not: those cross components are 31° and 58° off
    // the flow, and 58° is not a stream, it is the diagonal shimmer the finding
    // names. Flowing water therefore keeps the ALONG components (1.0 and 0.8)
    // and shrinks the cross ones to 0.15 and 0.3 — 8.5° and 20.6° off the flow,
    // both plainly downstream, yet still of OPPOSITE SIGN and of different
    // magnitude, so the two sheets go on beating against each other instead of
    // sliding as one rigid photograph.
    //
    // Layer A's along component is exactly 1.0, so on flowing water uFlowSpeed
    // IS the downstream metres per second of the leading layer; B follows at
    // 0.8 of it. (On still water the old lengths √1.36 / √2.33 are untouched.)
    float wCrossA = wStill ? 0.6 : 0.15;
    float wCrossB = wStill ? 1.3 : 0.3;
    vec2 wDirA = wAx + wAy * wCrossA;
    vec2 wDirB = wStill ? -( wAx * 0.8 + wAy * wCrossB ) : wAx * 0.8 - wAy * wCrossB;
    vec2 wRawA = vWaterWorld / uWaveM + wDirA * wDriftA;
    vec2 wRawB = vWaterWorld / ( uWaveM * 0.63 ) + wDirB * wDriftB;
    // ANISOTROPY: a current does not ripple in circles, it draws STREAKS. The
    // wave normal map is isotropic, so the stretch happens in the lookup —
    // squeeze the ALONG-flow coordinate by 3, leave the cross one alone, and
    // every crest comes out three times as long as it is wide, pulled down the
    // stream. 3 is the smallest ratio that reads as a direction at a glance;
    // more and the map's own frequencies smear into bands.
    //
    // The squeeze is applied to the WHOLE sample coordinate, drift included,
    // and that is what keeps the metres per second honest: the map is linear,
    // so squeezing (world/λ + dir·drift) is the same field, stretched, sampled
    // at the same argument — the crests still travel at wSpeed · |dir| m/s.
    // Still water squeezes by 1 in the world's own frame, i.e. not at all.
    float wAniso = 3.0;
    vec2 wUvA = wStill ? wRawA
      : wAx * ( dot( wRawA, wAx ) / wAniso ) + wAy * dot( wRawA, wAy );
    vec2 wUvB = wStill ? wRawB
      : wAx * ( dot( wRawB, wAx ) / wAniso ) + wAy * dot( wRawB, wAy );
    // A THIRD, FAINT LAYER: the same map read as a long ribbon — 2 λ across
    // the flow, 8 × that along it — sliding downstream at the same speed. Its
    // crests are lines PARALLEL to the current, so the direction reads even in
    // flat light, where no highlight moves and the two ripple sheets say
    // nothing. Weight 0.35 against the two full-strength layers: visible as
    // texture, never as a second wave. Exactly 0 on still water, so the sum
    // below is bit for bit the lake it always was (the tap itself stays
    // unconditional — a texture fetch under non-uniform control flow has no
    // defined derivatives).
    float wStreak = wStill ? 0.0 : 0.35;
    vec2 wRawC = ( vWaterWorld + wAx * ( uTime * wSpeed * wFlowSign ) )
                 / ( uWaveM * 2.0 );
    vec2 wUvC = wAx * ( dot( wRawC, wAx ) / 8.0 ) + wAy * dot( wRawC, wAy );
    vec3 wN = normalize( ( texture2D( normalMap, wUvA ).xyz * 2.0 - 1.0 )
                       + ( texture2D( normalMap, wUvB ).xyz * 2.0 - 1.0 )
                       + ( texture2D( normalMap, wUvC ).xyz * 2.0 - 1.0 )
                         * wStreak );
    wN = mix( vec3( 0.0, 0.0, 1.0 ), wN, wMask * wDetail );
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
