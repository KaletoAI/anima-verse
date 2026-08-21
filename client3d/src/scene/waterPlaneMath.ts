/**
 * THE SHORE, as arithmetic and as one GLSL chunk — the numbers behind the
 * water mirror of "Ein Boden" E4 (§ G4).
 *
 * Import-free on purpose, exactly like `naturalGroundMath.ts` next to
 * `naturalGround.ts` and `@anima/scene-render` `layerCut.ts` next to
 * `layerGround.ts`: `client3d/scripts/smoke_water_plane.mjs` transpiles this
 * file and checks every number below by hand. The three.js half — building the
 * plane, chaining the shader patch — is `waterPlane.ts`.
 *
 * THE SHORE COMES OUT OF THE HEIGHT DATA, not out of a depth pass. The mirror
 * is a flat polygon at `water_level_effective`; the fragment shader samples the
 * SAME R32F height pyramids the terrain's vertices are placed by
 * (`terrainLod.terrainLodSampleGlsl`), so the water depth under a pixel is
 * `plane y − h(x, z)` — a number in METRES, in our own data, identical near and
 * far. A screen-space depth texture would have been a second render target, a
 * second copy of the ground and a shore that changes width with the camera's
 * near/far planes; this one is a subtraction.
 */

/**
 * How deep the water has to be before it is fully drawn, in metres.
 *
 * DERIVED FROM THE BAKE, not tasted. E1 (§ A16 addendum § 2) carves a bed with
 * `water_depth_m = 2.0` reached over `shore_ramp_m = 3.0` of ground, via
 * `smoothstep`:
 *
 *     depth(d) = 2.0 · smoothstep( d / 3.0 ),   d = metres inside the outline
 *
 * so 1.5 m of depth is `smoothstep(t) = 0.75`, i.e. `3t² − 2t³ = 0.75`, i.e.
 * t ≈ 0.6736 and d ≈ 2.02 m. In other words: with the DEFAULT lake the water
 * fades in over the first two thirds of its shore ramp and is fully drawn by
 * the time the bed levels off — the ramp the author draws IS the ramp one sees,
 * and a shallow pond authored with `water_depth_m = 0.6` never reaches full
 * opacity at all, which is what a shallow pond looks like.
 *
 * It is also, to the centimetre, the default transition width of every other
 * ground (`edge_blend_m = 1.5`, § A17 § 4) — a lake ends over the same metres
 * a meadow ends over. That is a coincidence of two defaults and not a
 * dependency; this one is measured in DEPTH, the other in ground distance.
 */
export const WATER_SHORE_BAND_M = 1.5;

/** How deep the foam reaches, in metres. Half a metre is roughly where a
 *  wading figure's shin is (`move_sink_m` of the water kinds is a knee), so the
 *  white lace ends where the ground stops being walked and starts being swum. */
export const WATER_FOAM_BAND_M = 0.6;

/** How far the foam whitens the outgoing light at the very rim (0…1). Read as
 *  a fraction of the way to white, and it is deliberately partial: foam is
 *  broken water, not paint. */
export const WATER_FOAM_STRENGTH = 0.6;

/**
 * How much alpha the foam adds back at the rim (0…1).
 *
 * Without it the shoreline fades to nothing and the last hand's width of water
 * is invisible — the alpha ramp is doing its job a little too well. 0.15 is a
 * lace one can see and not a line one can measure: at depth 0 the water is
 * 15 % opaque, at depth 0.3 m the ramp itself already carries 0.104 and the
 * foam another 0.053, and by 0.6 m the foam is gone and the ramp alone answers.
 */
export const WATER_FOAM_ALPHA = 0.15;

/** `smoothstep(0, 1, t)` on a clamped t — the one easing curve of this file,
 *  written out so the smoke can check the GLSL twin against it. */
function smoothstep01(t: number): number {
  const c = t <= 0 ? 0 : t >= 1 ? 1 : t;
  return c * c * (3 - 2 * c);
}

/**
 * How much of the water is drawn over a bed `depthM` under the mirror, 0…1.
 *
 * `depthM ≤ 0` is not water at all — the bed is at or above the mirror, which
 * happens outside the carved outline and nowhere inside it (the E1 invariant).
 * The shader DISCARDS there rather than drawing a zero-alpha fragment: that is
 * the one band where the plane and the terrain are coplanar, and a fragment
 * that takes part in the depth test there flickers however small its alpha is.
 *
 * Hand values with the 1.5 m band, `t = depth / 1.5`, `3t² − 2t³`:
 *
 *     0.0   -> t = 0        -> 0            (discarded, see above)
 *     0.15  -> t = 0.1      -> 0.028
 *     0.30  -> t = 0.2      -> 0.104
 *     0.375 -> t = 0.25     -> 0.15625
 *     0.75  -> t = 0.5      -> 0.5
 *     1.125 -> t = 0.75     -> 0.84375
 *     1.5   -> t = 1        -> 1
 *     2.0   -> clamped      -> 1
 */
export function waterShoreAlpha(depthM: number): number {
  if (!Number.isFinite(depthM) || depthM <= 0) return 0;
  return smoothstep01(depthM / WATER_SHORE_BAND_M);
}

/**
 * How much foam sits over a bed `depthM` under the mirror, 0…1 — full at the
 * rim, gone at `WATER_FOAM_BAND_M`.
 *
 * Hand values, `1 − smoothstep(depth / 0.6)`:
 *
 *     0.0  -> 1 − 0     = 1
 *     0.15 -> 1 − 0.156 = 0.84375
 *     0.3  -> 1 − 0.5   = 0.5
 *     0.45 -> 1 − 0.844 = 0.15625
 *     0.6  -> 1 − 1     = 0
 */
export function waterFoam(depthM: number): number {
  if (!Number.isFinite(depthM) || depthM <= 0) return 1;
  return 1 - smoothstep01(depthM / WATER_FOAM_BAND_M);
}

/**
 * The alpha a water fragment really carries: the shore ramp plus what the foam
 * adds back at the rim, clamped.
 *
 *     depth 0.0  -> 0     + 1·0.15      = 0.15
 *     depth 0.15 -> 0.028 + 0.84375·0.15 = 0.1546875
 *     depth 0.3  -> 0.104 + 0.5·0.15    = 0.179
 *     depth 0.6  -> 0.352 + 0           = 0.352
 *     depth 1.5  -> 1     + 0           = 1
 */
export function waterAlpha(depthM: number): number {
  const a = waterShoreAlpha(depthM) + waterFoam(depthM) * WATER_FOAM_ALPHA;
  return a <= 0 ? 0 : a >= 1 ? 1 : a;
}

/**
 * The mirror height of a painted area, or `null` where there is none.
 *
 * `meta.water_level_effective` is the SERVER's own answer (§ A16 addendum § 2,
 * `heightfield.with_effective_water_level`): the level the bake really carved
 * the bed with, derived from the rim median where the author left the level on
 * "auto". Reading it is the whole water test — an area that has one is an area
 * whose bed was carved, and an area without one has no mirror to draw. The
 * authored `meta.water_level` is deliberately NOT read: it may be unset, and a
 * client that fell back to it would draw a mirror at a height the ground was
 * never carved to.
 */
export function waterLevelOf(meta: Record<string, unknown> | null | undefined
): number | null {
  const raw = meta?.water_level_effective;
  if (raw === null || raw === undefined) return null;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

/**
 * The shore, as the GLSL that rides on `terrainLodSampleGlsl()`.
 *
 * `vWaterPlane` is the fragment's WORLD position. Its `y` is the mirror height
 * itself — the plane is flat and sits at `water_level_effective`, so the level
 * is carried by the GEOMETRY and needs no uniform. That is what lets every lake
 * of one kind share ONE material however many levels they stand at: two lakes
 * at two heights are two meshes at two heights, not two shaders.
 *
 * `tlodHeight(p, 0.0)` asks for the FINEST level: `tlodLevel` clamps
 * `nodeStep / baseStep` at 1, so 0 selects mip 0. The drawn bed under a distant
 * lake is coarser than that, and the difference is deliberately ignored — the
 * E1 invariant holds in EVERY mip (`h ≤ level − ε`), so no bed pokes through
 * whichever level is drawn, and the shore band merely measures its metres
 * against the data rather than against the picture.
 */
export function waterShoreGlsl(): string {
  return `
varying vec3 vWaterPlane;
uniform float uShoreBandM;
uniform float uFoamBandM;
uniform float uFoamStrength;
uniform float uFoamAlpha;

float wsSmooth( float t ) {
  float c = clamp( t, 0.0, 1.0 );
  return c * c * ( 3.0 - 2.0 * c );
}
`;
}

/** The fragment body, inserted right before `#include <opaque_fragment>`: it
 *  is the last place `diffuseColor.a` and `outgoingLight` are both still
 *  writable, so the whole shore is ONE insertion instead of three. */
export function waterShoreBody(): string {
  return `
  {
    float wsDepth = vWaterPlane.y - tlodHeight( vWaterPlane.xz, 0.0 );
    // The rim, where mirror and terrain are the same surface: not water, and
    // the one band in which a fragment of this plane would fight the ground
    // for the depth test.
    if ( wsDepth <= 0.0 ) discard;
    float wsFoam = 1.0 - wsSmooth( wsDepth / uFoamBandM );
    outgoingLight = mix( outgoingLight, vec3( 1.0 ), wsFoam * uFoamStrength );
    diffuseColor.a *= clamp( wsSmooth( wsDepth / uShoreBandM )
                             + wsFoam * uFoamAlpha, 0.0, 1.0 );
  }
`;
}
