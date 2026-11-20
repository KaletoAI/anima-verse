/**
 * modelLight.ts — HOW A FIGURE IS LIT. One daylight rig for the 3D client and
 * the Game-Admin model views (viewer, mesh tiles).
 *
 * The admin viewer used to carry a light rig of its own (ambient 2.0 +
 * hemisphere 3.0 + key 3.0 + fill 1.5 + back 1.5, no tone mapping). With
 * three's physical lights a Lambert surface reflects `albedo · E / π`, so that
 * rig put a front face at ≈ 2.26 × its albedo (finding 2026-11-20, Glut):
 * skin read as glaring orange in the admin and as skin in the game. The game
 * client's rig lives here now and both apps build it through
 * `createDaylightRig`, so the two pictures cannot drift again.
 *
 * THE GAME CLIENT'S RIG (client3d `engine.ts` + `skyLight.ts`, unchanged):
 * a hemisphere light (sky `0xdfeeff`, ground `0x8a9a78`), a sun (noon colour
 * `0xfff2d8`) at `sunOffset(angle)` from the target, and a cool back fill
 * from `(-30, 20, -25)`. Intensities follow the day factor
 * (`daylightIntensities`). No tone mapping (`NoToneMapping`, three's default)
 * and sRGB output — the renderer settings stay as they are in both apps.
 *
 * THE ALBEDO FACTOR OF A FRONT FACE AT NOON (day = 1; hand derivation, the
 * numbers `scripts/smoke_model_light.mjs` re-computes from these constants).
 * Front face = normal +z, the camera at +z, the rig as above:
 *   - hemisphere, normal horizontal: irradiance = ½ (sky + ground) · 1.55
 *     = ½ ((0.738,0.855,1.0) + (0.254,0.323,0.188)) · 1.55 (linear sRGB)
 *     = (0.769, 0.913, 0.921)
 *   - sun, offset (0, 80, 25): cos = 25 / √(80² + 25²) = 0.2983;
 *     2.25 · 0.2983 · (1.0, 0.888, 0.687) = (0.671, 0.596, 0.461)
 *   - fill from behind (z = −25): cos < 0 → 0
 *   - sum (1.440, 1.509, 1.381), Lambert ÷ π → (0.458, 0.480, 0.440) × albedo
 *     (linear). The old admin rig: (2+1.7+3·0.80+1.5·0.67)/π ≈ 2.26 × albedo.
 * So a front face shows ≈ 0.46 × its linear albedo — about 0.70 × in sRGB
 * code values — in the game AND now in the admin: a skin texel (135,67,30)
 * renders near (95,47,20). That is darker than the texture on purpose: the
 * sun stands overhead, the figure's top surfaces carry the light.
 *
 * Three is injected (`THREE` parameter), never imported.
 */
import type { DirectionalLight, HemisphereLight, Object3D, Texture, WebGLRenderer } from 'three'

/** Hemisphere sky colour of the game's daylight. */
export const DAYLIGHT_HEMI_SKY = 0xdfeeff
/** Hemisphere ground colour of the game's daylight. */
export const DAYLIGHT_HEMI_GROUND = 0x8a9a78
/** The sun's colour from mid-morning to mid-afternoon (`skyLight` lerps towards it from dawn red). */
export const DAYLIGHT_SUN_NOON = 0xfff2d8
/** The cool back fill that lifts the shadow sides. */
export const DAYLIGHT_FILL = 0xdde8ff
/** Where the fill stands, relative to the target (it shines towards the origin). */
export const DAYLIGHT_FILL_POSITION: readonly [number, number, number] = [-30, 20, -25]
/** The sun angle at noon (`sunAngle = ((h − 6) / 12) · π`, h = 12). */
export const NOON_SUN_ANGLE = Math.PI / 2
/** Blur of the neutral environment map (`PMREMGenerator.fromScene(room, sigma)`). */
export const MODEL_ENV_SIGMA = 0.04

/** Light intensities for a day factor 0 (night) .. 1 (noon), as the game's clock drives them. */
export function daylightIntensities(day: number): { sun: number; hemi: number; fill: number } {
  return { sun: 0.25 + day * 2, hemi: 0.35 + day * 1.2, fill: 0.15 + day * 0.4 }
}

/** The sun's position relative to the lit target for a sun angle (0 = east, π/2 = zenith, π = west);
 *  `out` lets a frame loop reuse one array. */
export function sunOffset(sunAngle: number,
                          out: [number, number, number] = [0, 0, 0]): [number, number, number] {
  out[0] = Math.cos(sunAngle) * 60
  out[1] = Math.max(0.08, Math.sin(sunAngle)) * 80
  out[2] = 25
  return out
}

export interface DaylightRig {
  hemi: HemisphereLight
  sun: DirectionalLight
  fill: DirectionalLight
}

/**
 * The daylight rig: hemisphere, sun and back fill in the game's colours, the
 * fill at its fixed position. Intensities start at noon; the game client
 * re-drives them (and the sun's position) from its clock, a model view keeps
 * them. The caller adds the three lights (and the sun's target) to its scene.
 */
export function createDaylightRig(THREE: typeof import('three')): DaylightRig {
  const noon = daylightIntensities(1)
  const hemi = new THREE.HemisphereLight(DAYLIGHT_HEMI_SKY, DAYLIGHT_HEMI_GROUND, noon.hemi)
  const sun = new THREE.DirectionalLight(DAYLIGHT_SUN_NOON, noon.sun)
  sun.position.set(...sunOffset(NOON_SUN_ANGLE))
  const fill = new THREE.DirectionalLight(DAYLIGHT_FILL, noon.fill)
  fill.position.set(...DAYLIGHT_FILL_POSITION)
  return { hemi, sun, fill }
}

/**
 * The neutral environment map figures reflect (glossy pieces, metal-textured
 * models): a PMREM of three's `RoomEnvironment`, which the caller constructs
 * and passes in (it lives in `three/addons`, and this package imports no
 * three). The room is baked once and disposed here; the caller disposes the
 * texture with its renderer.
 */
export function createModelEnvironment(THREE: typeof import('three'), renderer: WebGLRenderer,
                                       roomEnvironment: Object3D): Texture {
  const pmrem = new THREE.PMREMGenerator(renderer)
  try {
    return pmrem.fromScene(roomEnvironment as import('three').Scene, MODEL_ENV_SIGMA).texture
  } finally {
    pmrem.dispose()
    ;(roomEnvironment as Object3D & { dispose?: () => void }).dispose?.()
  }
}


