/**
 * waterShade — WATER AS A SHADING OF THE GROUND, not as a surface over it
 * (Wasser v2, K-A E4; `recherche-wasser-v2.md` § 3.3 "Single Layer Water",
 * § 4 K-A).
 *
 * E3 lifted the terrain's vertices onto the mirror (`terrainLod.tlodLift`), so
 * a water pixel already stands at the right height — it just looked like
 * ground. This file is the other half: given how DEEP the lift was at this
 * pixel, it turns the ground the terrain has just textured and lit into water.
 *
 * ── WHY ONE PASS ────────────────────────────────────────────────────────────
 * The old mirror was a second, transparent surface: the bed shader ran, then
 * the water shader ran on top of it, and the blend of the two was the picture
 * (≈ 41 texture reads per water pixel, § 4 K-A). Unreal's Single Layer Water
 * shows the other reading — the shader that draws the BED already knows how
 * much water stands over it, so it can mix the two ITSELF and skip the second
 * pass entirely. That is what happens here: `diffuseColor` arrives carrying the
 * bed the layer compositor painted, and the absorption blends it toward the
 * water's tint before the lighting model ever sees it.
 *
 * BEFORE THE LIGHTING, and that is not an implementation detail. Blending the
 * tint into the FINISHED `outgoingLight` would make deep water a flat, unlit
 * patch of blue that stays bright at midnight; blending it into the ALBEDO
 * hands the water to the same lighting model the ground uses, with the water's
 * own roughness and its own rippled normal — so a lake darkens with the world
 * and carries a real specular highlight. Only the two things that are NOT
 * albedo stay at the end of the shader: the fresnel share of sky and the foam.
 *
 * ── ONE NUMBER SAYS "HOW MUCH WATER" ────────────────────────────────────────
 * `twA`, the absorption, drives the albedo, the roughness, the metalness, the
 * normal and the sky share alike. It is the OLD shore alpha
 * (`waterPlaneMath.waterShoreAlpha`, ¾ of the water's own bed depth) — the
 * curve that already decided how see-through the mirror was, re-read as "how
 * much of this pixel is water rather than bed". One factor means the surface
 * cannot half-change: where the bed shows through, it is shaded as the wet
 * ground it is; where it is gone, the pixel is a mirror.
 *
 * ── THE RIM IS A RAMP, NOT AN EDGE ──────────────────────────────────────────
 * The old mirror `discard`ed at depth 0 and faded its alpha over the last
 * `WATER_EDGE_FADE_M` of DEPTH so the discard boundary would not crawl. There
 * is no discard here — the ground is drawn either way — but the FOAM would
 * step from full white to nothing across the waterline without the very same
 * ramp, so it is kept, verbatim, and multiplies both the absorption and the
 * foam (`waterEdgeFade`, floored at one pixel of depth via `fwidth`).
 *
 * NO THREE, NO STATE — arithmetic and one GLSL string, so
 * `client3d/scripts/smoke_water_shade.mjs` can transpile the file and derive
 * every number by hand (§ B5a).
 */
import { WATER_EDGE_FADE_M, WATER_FOAM_BAND_M, WATER_FOAM_STRENGTH,
  waterEdgeFade, waterFoam, waterOpaqueDepthM, waterShoreAlpha } from './waterPlaneMath';
import { WATER_FLOW_SPEED_DEFAULT_M_S } from '@anima/scene-render';
import type { SurfaceMaterialSpec } from '@anima/scene-render';

/**
 * How ONE water kind looks, as the terrain fragment reads it.
 *
 * Every field is the number `@anima/scene-render materials.applyWaterShader`
 * feeds its own uniforms — this is the same look, read by another program, and
 * the defaults below are that function's defaults. What is NOT here is the
 * water TEXTURE and its `map_strength`: under K-A the image under a water
 * pixel is the BED's (the compositor already painted it), so there is no
 * second picture to mix against.
 */
export interface WaterLook {
  /** The tint, linear 0…1 per channel — `spec.tint`. */
  tint: [number, number, number];
  /** How much sky the fresnel share mixes in — `spec.sky_mix`. */
  skyMix: number;
  /** Ripple wavelength in metres — `spec.wave_m`. */
  waveM: number;
  /** Metres per second of STILL water — `spec.speed`. */
  speed: number;
  /** Metres per second of FLOWING water — `spec.flow_speed`. */
  flowSpeed: number;
  /** Metres of depth at which the bed is fully absorbed — ¾ of the water's own
   *  bed depth (`waterOpaqueDepthM`, W4b). */
  opaqueDepthM: number;
  roughness: number;
  metalness: number;
  /**
   * Whether the LAYER this row belongs to is itself a water layer.
   *
   * It is not part of the look — it is how the fragment reads the mask. The id
   * mask names a PAIR of layers per texel (the one painted on top at the
   * nearest boundary and the one under it) and says nothing about which side of
   * that boundary a pixel is on; only the signed distance does, and this
   * program does not read it. It does not have to: a pixel that reaches the
   * water shading was LIFTED, so it stands in water, so the water half of the
   * pair is its kind. This flag is what picks that half.
   *
   * Rows that merely carry the primary water's look as a fallback (a layer that
   * is not water at all) say `false`, or they would win the pick.
   */
  isWater: boolean;
}

/** How many RGBA texels one look occupies in the lookup texture. The layout is
 *  spelled out in `packWaterLook` and read back by `tlodWaterSurface`. */
export const WATER_LOOK_TEXELS = 3;

function num(v: unknown, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

/** '#rrggbb' -> 0…1 per channel. The default is the one `materials.hex3`
 *  carries, so a kind that names no tint is the same blue in both renderers. */
export function waterTintRgb(hex: unknown): [number, number, number] {
  const text = typeof hex === 'string' && /^#[0-9a-fA-F]{6}$/.test(hex.trim())
    ? hex.trim() : '#3f7fb8';
  const v = parseInt(text.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

/**
 * The look of ONE water kind out of its surface-material spec and the bed
 * depth of the area painted with it.
 *
 * `depthM` is the AREA's effective bed depth (`meta.water_depth_effective`),
 * the same number the mirror mesh turned into its `aWaterOpaque` attribute —
 * the kind's default with the area's override already applied. Under K-A it
 * is carried per KIND (the fragment learns which kind it stands in from the
 * layer mask, which speaks kinds), so a kind painted twice with two different
 * depth overrides collapses to one of them.
 *
 * THAT IS THE STANDING RULE, decided in K-A E6 and not a gap waiting to be
 * closed. Every other field of `WaterLook` comes from the kind's surface
 * material and could not be per area anyway; carrying this one per texel would
 * need the level's MASKED mix (a plain channel mixes toward 0 at a dry corner,
 * which drives `opaqueDepthM` to 0 and the absorption to 1 exactly at the
 * waterline), i.e. a fourth channel on the level pyramid or four more
 * `texelFetch` per vertex, plus about a third more payload on every wet tile.
 * A world that wants two visibly different opacities paints two KINDS.
 */
export function waterLookFrom(spec: SurfaceMaterialSpec | null | undefined,
                              depthM: unknown): WaterLook {
  return {
    tint: waterTintRgb(spec?.tint),
    skyMix: num(spec?.sky_mix, 0.55),
    waveM: Math.max(num(spec?.wave_m, 1.6), 0.05),
    speed: num(spec?.speed, 0.05),
    flowSpeed: num(spec?.flow_speed, WATER_FLOW_SPEED_DEFAULT_M_S),
    opaqueDepthM: waterOpaqueDepthM(depthM),
    roughness: num(spec?.roughness, 0.08),
    metalness: num(spec?.metalness, 0.15),
    isWater: true,
  };
}

/** The look a world without a single water layer would read — the library's
 *  own `water` defaults. Nothing draws it (no water, no lift, no shading); it
 *  exists so the lookup texture is never empty and no fetch is ever out of
 *  range. */
export const WATER_LOOK_DEFAULT: WaterLook = waterLookFrom(null, null);

/**
 * The lookup texture's payload: `WATER_LOOK_TEXELS` RGBA texels per look, one
 * ROW per layer index.
 *
 *   texel 0 — tint.r, tint.g, tint.b, sky_mix
 *   texel 1 — wave_m, speed, flow_speed, opaque_depth_m
 *   texel 2 — roughness, metalness, is_water, 0     (one spare, reserved)
 *
 * A TEXTURE AND NOT A UNIFORM ARRAY. The fragment indexes it by the LAYER the
 * mask names, and a `vec4[64]` array per component would spend most of a
 * GLES3 implementation's guaranteed fragment uniform budget (224 vectors) on a
 * table of at most a handful of distinct waters. Three `texelFetch` out of a
 * 3 × n float texture are always in cache and cost nothing next to that.
 */
export function packWaterLook(looks: readonly WaterLook[]): Float32Array {
  const rows = Math.max(1, looks.length);
  const out = new Float32Array(rows * WATER_LOOK_TEXELS * 4);
  for (let j = 0; j < rows; j += 1) {
    const l = looks[j] ?? WATER_LOOK_DEFAULT;
    const base = j * WATER_LOOK_TEXELS * 4;
    out[base] = l.tint[0];
    out[base + 1] = l.tint[1];
    out[base + 2] = l.tint[2];
    out[base + 3] = l.skyMix;
    out[base + 4] = l.waveM;
    out[base + 5] = l.speed;
    out[base + 6] = l.flowSpeed;
    out[base + 7] = l.opaqueDepthM;
    out[base + 8] = l.roughness;
    out[base + 9] = l.metalness;
    out[base + 10] = l.isWater ? 1 : 0;
  }
  return out;
}

/**
 * HOW MUCH WATER stands over the bed at a pixel, 0…1 — the absorption.
 *
 * `depthM` is the lift the vertex stage measured (`w_level − h`, the varying
 * `vTlodWet`), `opaqueDepthM` the water's own ¾ depth, `edgeM` one pixel
 * measured in metres of DEPTH (`fwidth` of the varying).
 *
 * It is `waterShoreAlpha × waterEdgeFade`, both unchanged from the mirror: the
 * first is the W4b curve (`3t² − 2t³` over the water's own band), the second
 * the rim ramp that keeps the waterline from stepping. Hand values for the
 * default lake (band 1.5 m) at a pixel far wider than the rim, i.e. edge fade
 * 1 from 0.05 m of depth on:
 *
 *     0.0   -> 0                     (dry: the ground look, untouched)
 *     0.15  -> 0.028
 *     0.30  -> 0.104
 *     0.75  -> 0.5
 *     1.125 -> 0.84375
 *     1.5   -> 1                     (the bed is gone; its normal is not read)
 */
export function waterAbsorb(depthM: number, opaqueDepthM: number,
                            edgeM: number): number {
  if (!(depthM > 0)) return 0;
  return waterShoreAlpha(depthM, Math.max(opaqueDepthM, 1e-3))
    * waterEdgeFade(depthM, edgeM);
}

/**
 * How much of a pixel the foam may whiten where the WATER itself covers almost
 * nothing (0…1) — the lace at the very waterline.
 *
 * It is the mesh mirror's own rim number, carried over: there the foam did not
 * only tint the light, it also ADDED this much alpha back, "without it the
 * shoreline fades to nothing and the last hand's width of water is invisible".
 * Under K-A there is no alpha to add to — the ground is opaque — so the same
 * 0.15 appears here, as the floor of the cover the whitening is multiplied by.
 */
export const WATER_FOAM_MIN_COVER = 0.15;

/**
 * HOW MUCH FOAM whitens the pixel, 0…1 — full at the waterline, gone at
 * `WATER_FOAM_BAND_M` (0.6 m), times the rim ramp AND times how much water
 * really stands over the pixel.
 *
 * The band does NOT scale with the water's depth (W4b): half a metre of real
 * water at a real rim is the same half metre in a pond and in a lake.
 *
 * ── THE COVER, AND WHY IT IS NOT OPTIONAL (finding 2026-08-24) ───────────────
 * The mirror was a TRANSPARENT surface: it whitened its own outgoing light by
 * `foam · WATER_FOAM_STRENGTH` and then handed the whole fragment to the blend
 * at `alpha = clamp(shoreAlpha + foam · 0.15, 0, 1) · rim`. So the white that
 * ever reached the screen was `foam · strength · alpha` — three small factors
 * at the rim, i.e. a lace. K-A E4 kept the first two and dropped the third,
 * because the terrain is opaque and there is no alpha left to drop it into:
 * measured on a river (bed 1.0 m, opaque band 0.75 m), a pixel with 5 cm of
 * water over it went from 0.094 white to 0.588 — 6.26× — and one with 30 cm
 * from 0.128 to 0.300. That is the "white edges and corners at the waterline",
 * and it is loudest exactly where the water is thinnest: the flooded bank
 * inside the raster's dilation ring, and the lattice staircase the ring ends on.
 *
 * The cover is therefore multiplied back in, constant for constant, so the
 * shipped white is the mirror's again. Hand values for a river (opaque band
 * 0.75 m) with the rim ramp saturated, `foam · min(shoreAlpha + foam·0.15, 1)`:
 *
 *     0.05 -> 0.9803241 · (0.0127407 + 0.1470486) = 0.1566349
 *     0.30 -> 0.5       · (0.352     + 0.075    ) = 0.2135
 *     0.60 -> 0                                   = 0
 *
 * times `WATER_FOAM_STRENGTH` (0.6) that is 0.0939809 / 0.1281 / 0 of the way
 * to white — the mirror's own three numbers.
 */
export function waterFoamAt(depthM: number, opaqueDepthM: number,
                            edgeM: number): number {
  if (!(depthM > 0)) return 0;
  const foam = waterFoam(depthM);
  const cover = Math.min(
    waterShoreAlpha(depthM, Math.max(opaqueDepthM, 1e-3))
      + foam * WATER_FOAM_MIN_COVER, 1);
  return foam * cover * waterEdgeFade(depthM, edgeM);
}

/**
 * IS THIS PIXEL INSIDE THE AUTHORED WATER? — the gate that closes the grey rim
 * seam (finding 2026-08-24), and the CPU twin of the shader's `twInside`.
 *
 * THE SEAM. The water raster is DILATED: the server writes a level up to
 * `WATER_RASTER_DILATION_STEPS` (4 m) past the authored outline, so that every
 * point inside a water polygon reads four wet corners on the base lattice
 * (`waterRaster.waterBilinear`). Where the bank there lies below the mirror the
 * terrain is lifted on it too — a few centimetres of water standing on dry land
 * — and until now the shading keyed on that lift alone: a band of cm-shallow
 * water all round every shore, i.e. the grey wash the user saw (and, before the
 * cover fix of the same day, the white foam rim).
 *
 * THE FIX IS NOT TO MOVE THE LIFT. A few centimetres of lifted ground drawn as
 * GROUND is invisible, and taking the lift back would mean a second, narrower
 * water raster and a vertex path that no longer matches the one the gameplay
 * profile answers. What moves is the SHADING GATE: from "this pixel was lifted"
 * to "this pixel was lifted AND stands inside the painted water", and the
 * second half is a question the compositor's own mask pair already answers
 * exactly, sub-texel, with the same signed distance every other material
 * boundary in this world is cut on (`@anima/scene-render` `layerWeight`).
 *
 * THE RULE. `a` and `b` are the layer pair of the fragment's id texel, `sd` the
 * signed distance to the boundary between them, positive on A's side:
 *   both water          -> 1 (two waters meet; the pixel is in one of them)
 *   neither water       -> 0 (the pair names no mirror at all — the ring)
 *   otherwise           -> smoothstep(−band/2, +band/2, ±sd)
 * with the sign taken so that the WATER half wins, and `band` the wider of one
 * screen pixel and one sd texel. One pixel is the anti-aliasing width every
 * hard cut in this world uses (`layerWeight`'s hard branch); one texel is the
 * floor under it, because the distance itself is only written per half metre
 * and a band narrower than its own quantisation would draw the staircase of
 * the byte rather than the line.
 */
export function waterInside(sd: number, aIsWater: boolean, bIsWater: boolean,
                            pixelM: number, texelM: number): number {
  if (aIsWater && bIsWater) return 1;
  if (!aIsWater && !bIsWater) return 0;
  const band = Math.max(pixelM, texelM, 1e-6);
  const t = Math.min(Math.max(sd / band + 0.5, 0), 1);
  const w = t * t * (3 - 2 * t);
  return aIsWater ? w : 1 - w;
}

/** The albedo a water pixel carries: the bed blended toward the tint by the
 *  absorption. `mix(bed, tint, a)` — the one line the fragment writes into
 *  `diffuseColor`, spelled here so the smoke can check it. */
export function waterTintBlend(bed: readonly [number, number, number],
                               tint: readonly [number, number, number],
                               absorb: number): [number, number, number] {
  const a = absorb <= 0 ? 0 : absorb >= 1 ? 1 : absorb;
  return [bed[0] + (tint[0] - bed[0]) * a,
          bed[1] + (tint[1] - bed[1]) * a,
          bed[2] + (tint[2] - bed[2]) * a];
}

/**
 * THE FRAGMENT SIDE, as GLSL — declared ONLY in the water variant's program
 * (`terrainLod.patchTerrainLod(mat, true)`), so a dry ground pixel does not
 * gain a single instruction from this stage.
 *
 * It rides on `terrainLodSampleGlsl()` and `terrainLodNormalGlsl()` (it calls
 * `tlodNormalAt` and reads `vTlodXZ`) and on the two varyings the water
 * variant's vertex stage writes: `vTlodWet` — the metres of water over the bed,
 * 0 where the vertex was not lifted — and `vTlodFlow`, the downstream vector of
 * the water raster, whose LENGTH is the area's own speed factor exactly as the
 * mirror's `aWaterFlow` attribute carried it.
 *
 * THE ISOLATION SWITCH NEEDS NO PATH OF ITS OWN. Toggle 22 sets
 * `uTlodNoWater = 1`, which makes `tlodLift` hand its height back unchanged —
 * so `vTlodWet` is 0 for every vertex and every function below takes its dry
 * branch. "Water lift off" and "water shading off" are the same uniform,
 * because a pixel with no water over it is not a water pixel.
 *
 * THREE INSERTION POINTS, in shader order:
 *  1. after `#include <metalnessmap_fragment>` — the last chunk before the
 *     shading normal and the lighting, and the first one at which the albedo
 *     (`map_fragment` + the compositor + the natural-ground stages), the
 *     roughness and the metalness are all written and all still writable.
 *     `tlodWaterSurface` does the whole measurement here and leaves its answer
 *     in the four globals below.
 *  2. inside `#include <normal_fragment_begin>` — `tlodWaterNormal` replaces
 *     the ground normal the dry variant takes.
 *  3. before `#include <opaque_fragment>` — the two things that are not albedo:
 *     the fresnel share of sky and the foam.
 */
export function terrainWaterFragmentGlsl(): string {
  return `
varying float vTlodWet;
varying vec2 vTlodFlow;
uniform sampler2D uTlodWave;
uniform sampler2D uTlodWaterLook;
uniform highp usampler2D uTlodWaterMask;
uniform vec4 uTlodWaterMaskGeom;
uniform sampler2D uTlodWaterSd;
uniform vec4 uTlodWaterSdGeom;
uniform vec2 uTlodWaterSdCode;
uniform vec3 uTlodSky;
uniform float uTlodTime;

// What tlodWaterSurface() measures and the two stages after it read. Globals
// and not a struct passed along: the three insertion points are three separate
// chunks of three's own shader and cannot hand each other a value.
float twA;
float twFoam;
float twSkyMix;
vec3 twN;

float twSmooth( float t ) {
  float c = clamp( t, 0.0, 1.0 );
  return c * c * ( 3.0 - 2.0 * c );
}

// WHICH TWO GROUND KINDS meet under this pixel is the layer index PAIR the
// compositor's id mask names (\`scene/layerGround.ts\`), and WHICH SIDE of them
// the pixel is on is the sign of the signed distance beside it. Both textures
// are the SAME ones \`lcCompose\` reads, bound a second time under names of this
// program's own, because that chunk is declared BELOW this one in the final
// shader and its uniforms cannot be reached from here.
//
// Only the NEAR window is asked: water is lifted only inside the height
// pyramid's near rectangle (\`tlodWaterAt\`), and the two windows cover the same
// loaded tiles.
//
// IS THIS LAYER A WATER? — \`is_water\`, the third component of the look's last
// texel. It is false on the rows that only carry the primary water's look as a
// fallback, which is what makes the flag usable as a gate and not merely as a
// tie-break: two waters meeting take the upper one, which is the rule the mask
// itself follows for the ground.
bool twIsWater( int layer ) {
  return texelFetch( uTlodWaterLook, ivec2( 2, layer ), 0 ).z > 0.5;
}

// ONE sd TEXEL of the near window, in metres — the byte the server wrote,
// decoded by the payload's own quantisation. A TEXEL FETCH and never a filtered
// read: the four sd texels under one id texel are the ones the bake signed
// against ONE pair, and a sampler that blended across the id texel's rim would
// mix in a neighbour's sign. Same statement as \`layerCut.lcSdTexel\`, under this
// program's own names — that chunk is declared BELOW this one in the finished
// shader and its uniforms cannot be reached from here.
float twSdTexel( ivec2 t ) {
  int last = int( uTlodWaterSdGeom.w ) - 1;
  return ( texelFetch( uTlodWaterSd, clamp( t, ivec2( 0 ), ivec2( last ) ), 0 ).r * 255.0
           - uTlodWaterSdCode.x ) / uTlodWaterSdCode.y;
}

// THE SIGNED DISTANCE, reconstructed from the sd texels of the fragment's OWN
// id texel — bilinear and EXTRAPOLATED past their centres rather than clamped,
// exactly as \`lcSdAt\` does it, so the shading edge of the water and the
// material edge of the ground under it are the same line and not two lines a
// quarter of a metre apart.
float twSdAt( vec2 p, vec2 idIdx ) {
  float ratio = max( floor( uTlodWaterMaskGeom.z / uTlodWaterSdGeom.z + 0.5 ), 1.0 );
  vec2 t0 = idIdx * ratio;
  vec2 t1 = t0 + ( ratio - 1.0 );
  vec2 c0 = uTlodWaterSdGeom.xy + ( t0 + 0.5 ) * uTlodWaterSdGeom.z;
  float spanM = ( ratio - 1.0 ) * uTlodWaterSdGeom.z;
  vec2 f = spanM > 0.0 ? ( p - c0 ) / spanM : vec2( 0.0 );
  float s00 = twSdTexel( ivec2( t0 ) );
  float s10 = twSdTexel( ivec2( t1.x, t0.y ) );
  float s01 = twSdTexel( ivec2( t0.x, t1.y ) );
  float s11 = twSdTexel( ivec2( t1 ) );
  return mix( mix( s00, s10, f.x ), mix( s01, s11, f.x ), f.y );
}

// HOW MUCH OF THE PAINTED WATER STANDS UNDER THIS PIXEL — the gate that closes
// the grey rim seam (2026-08-24). The TS twin and the whole argument are in
// \`waterInside\`; here it is the same three cases and the same band.
float twInside( float sd, bool aw, bool bw, float pixelM ) {
  if ( aw && bw ) return 1.0;
  if ( !aw && !bw ) return 0.0;
  float band = max( max( pixelM, uTlodWaterSdGeom.z ), 1e-6 );
  float w = twSmooth( sd / band + 0.5 );
  return aw ? w : 1.0 - w;
}

// The FLOW FRAME, and the one place the anisotropy lives: squeeze the
// along-flow component of a vector, leave the cross one. Still water hands in
// the world's own axes and \`aniso\` 1, which makes this the identity — that is
// how the two branches of the mirror's shader (\`materials.applyWaterShader\`)
// become one expression here without changing either.
vec2 twFrame( vec2 v, vec2 ax, vec2 ay, float aniso ) {
  return ax * ( dot( v, ax ) / aniso ) + ay * dot( v, ay );
}

// THE RIPPLE, constant for constant the mirror's (\`materials.ts\`): two
// counter-scrolling sheets of the shared wave normal map plus a faint third
// one drawn as a long ribbon along the current, the speed in real metres per
// second (the drift is divided by each layer's own wavelength), the crests
// running DOWNSTREAM (the sign is negative on flowing water) and a 3:1 squeeze
// along the flow so a current draws streaks instead of circles.
//
// TEXTUREGRAD AND NOT TEXTURE. Every fetch here sits under \`if ( d > 0.0 )\`,
// which differs across a quad at every shoreline, so an implicit derivative
// would be undefined. The gradients are taken from the WORLD POSITION at
// uniform control flow and pushed through the very same linear map the sample
// coordinate goes through — which is exact, because that map is linear.
vec3 twRipple( vec2 p, vec2 gx, vec2 gy, float waveM, float speed, float flowSpeed ) {
  // HOW MUCH OF THE RIPPLE THIS PIXEL CAN STILL RESOLVE: once one pixel covers
  // a whole wavelength the map carries no signal, and what is left is sampling
  // noise in a specular lobe narrow enough to turn every texel into a spark.
  float px = max( length( gx ), length( gy ) );
  float detail = clamp( 1.0 - px / waveM, 0.0, 1.0 );
  // The area's speed factor rides on the LENGTH of the flow vector (the server
  // bakes it there, \`heightfield.water_flow_factor\`), and a length below 1e-4
  // is STILL — a lake, which drifts at \`speed\` and counter-scrolls its sheets.
  float len = length( vTlodFlow );
  bool still = len < 1e-4;
  vec2 ax = still ? vec2( 1.0, 0.0 ) : vTlodFlow / max( len, 1e-4 );
  vec2 ay = vec2( -ax.y, ax.x );
  float sp = still ? speed : flowSpeed * len;
  float sgn = still ? 1.0 : -1.0;
  float aniso = still ? 1.0 : 3.0;
  float crossA = still ? 0.6 : 0.15;
  float crossB = still ? 1.3 : 0.3;
  vec2 dirA = ax + ay * crossA;
  vec2 dirB = still ? -( ax * 0.8 + ay * crossB ) : ax * 0.8 - ay * crossB;
  float lamA = waveM;
  float lamB = waveM * 0.63;
  float lamC = waveM * 2.0;
  vec2 uvA = twFrame( p / lamA + dirA * ( uTlodTime * sp * sgn / lamA ), ax, ay, aniso );
  vec2 uvB = twFrame( p / lamB + dirB * ( uTlodTime * sp * sgn / lamB ), ax, ay, aniso );
  vec2 uvC = twFrame( ( p + ax * ( uTlodTime * sp * sgn ) ) / lamC, ax, ay, 8.0 );
  vec3 nA = textureGrad( uTlodWave, uvA, twFrame( gx, ax, ay, aniso ) / lamA,
                                         twFrame( gy, ax, ay, aniso ) / lamA ).xyz * 2.0 - 1.0;
  vec3 nB = textureGrad( uTlodWave, uvB, twFrame( gx, ax, ay, aniso ) / lamB,
                                         twFrame( gy, ax, ay, aniso ) / lamB ).xyz * 2.0 - 1.0;
  vec3 nC = textureGrad( uTlodWave, uvC, twFrame( gx, ax, ay, 8.0 ) / lamC,
                                         twFrame( gy, ax, ay, 8.0 ) / lamC ).xyz * 2.0 - 1.0;
  vec3 n = normalize( nA + nB + nC * ( still ? 0.0 : 0.35 ) );
  n = mix( vec3( 0.0, 0.0, 1.0 ), n, detail );
  // Tangent space (+z up) over a horizontal mirror whose uv IS the world xz:
  // tangent -> +x, bitangent -> +z, normal -> +y. That is the \`tbn\` of the
  // mirror mesh, written out, because this surface has no tangent attribute.
  return normalize( vec3( n.x, n.z, n.y ) );
}

// THE MEASUREMENT, once per fragment of the water variant. Everything that
// needs a derivative is taken BEFORE the dry branch returns, at uniform control
// flow: a dry pixel of a wet piece then pays two derivatives and one compare
// and keeps the ground it always had.
void tlodWaterSurface( inout vec4 diffuseColor, inout float roughnessFactor,
                       inout float metalnessFactor ) {
  twA = 0.0;
  twFoam = 0.0;
  twSkyMix = 0.0;
  twN = vec3( 0.0, 1.0, 0.0 );
  float d = vTlodWet;
  float edge = max( fwidth( d ), ${WATER_EDGE_FADE_M} );
  vec2 gx = dFdx( vTlodXZ );
  vec2 gy = dFdy( vTlodXZ );
  if ( d <= 0.0 ) return;
  int rows = textureSize( uTlodWaterLook, 0 ).y;
  // WHICH KIND, AND WHETHER THIS IS THE PAINTED WATER AT ALL. Both come out of
  // the one id texel, so the pair is fetched HERE rather than through
  // twPairAt — the signed distance has to be reconstructed from that same
  // texel's own sd block (twSdAt) and cannot be handed an index it did not see.
  //
  // OUTSIDE THE MASK WINDOW THERE IS NO GATE, and that is deliberate: the water
  // is lifted only inside the height pyramid's near rectangle, the two windows
  // cover the same loaded tiles, and a pixel the mask cannot speak about keeps
  // the fallback water look it has had since K-A E4 rather than turning to
  // ground on the strength of a texel nobody read.
  int layer = 0;
  float inside = 1.0;
  float maskN = uTlodWaterMaskGeom.w;
  vec2 maskIdx = ( vTlodXZ - uTlodWaterMaskGeom.xy ) / uTlodWaterMaskGeom.z;
  if ( maskN > 1.5 && maskIdx.x >= 0.0 && maskIdx.y >= 0.0
       && maskIdx.x < maskN && maskIdx.y < maskN ) {
    vec2 idIdx = floor( maskIdx );
    uvec2 pair = texelFetch( uTlodWaterMask, ivec2( idIdx ), 0 ).rg;
    int a = clamp( int( pair.x ), 0, rows - 1 );
    int b = clamp( int( pair.y ), 0, rows - 1 );
    bool aw = twIsWater( a );
    bool bw = twIsWater( b );
    layer = aw ? a : b;
    // ONE PIXEL IN WORLD METRES, from the world position's own derivatives and
    // never from fwidth of the sampled distance — see \`layerWeight\`.
    inside = twInside( twSdAt( vTlodXZ, idIdx ), aw, bw,
                       max( length( gx ), length( gy ) ) );
  }
  // The rim ramp: 0 exactly where the water ends, 1 one pixel of depth in —
  // and 0 on the flooded dilation ring, where the lift is real and the water is
  // not. A ring pixel therefore leaves here having paid two derivatives, one
  // mask fetch and four sd fetches, and keeps the ground the compositor painted.
  float rim = clamp( d / edge, 0.0, 1.0 ) * inside;
  if ( rim <= 0.0 ) return;
  vec4 look0 = texelFetch( uTlodWaterLook, ivec2( 0, layer ), 0 );
  vec4 look1 = texelFetch( uTlodWaterLook, ivec2( 1, layer ), 0 );
  vec4 look2 = texelFetch( uTlodWaterLook, ivec2( 2, layer ), 0 );
  float shore = twSmooth( d / max( look1.w, 1e-3 ) );
  twA = shore * rim;
  // THE FOAM, and the COVER it is multiplied by — the mirror's own alpha, which
  // an opaque ground has nowhere else to put. See waterFoamAt: without it a
  // hand's width of water at the rim is painted 6.26× as white as the surface
  // this replaced, which is the white edge and the white lattice corner.
  float rawFoam = 1.0 - twSmooth( d / ${WATER_FOAM_BAND_M} );
  twFoam = rawFoam * min( shore + rawFoam * ${WATER_FOAM_MIN_COVER}, 1.0 ) * rim;
  twSkyMix = look0.w;
  twN = twRipple( vTlodXZ, gx, gy, max( look1.x, 0.05 ), look1.y, look1.z );
  // THE ABSORPTION, on the ALBEDO and not on the finished light: the bed the
  // compositor painted is blended toward the water's tint here, so the lighting
  // model shades the water itself — with the water's roughness and the water's
  // normal — instead of a flat patch of colour laid over a lit ground.
  diffuseColor.rgb = mix( diffuseColor.rgb, look0.rgb, twA );
  roughnessFactor = mix( roughnessFactor, look2.x, twA );
  metalnessFactor = mix( metalnessFactor, look2.y, twA );
}

// THE SHADING NORMAL of a water pixel — and the one place K-A gives GPU work
// back rather than taking it.
//
// Where the bed is fully absorbed (twA == 1, i.e. from the water's own opaque
// depth down) the ground normal is INVISIBLE, so it is not computed:
// \`tlodNormalAt\` is four \`tlodHeight\` calls, i.e. SIXTEEN texelFetch, and they
// are simply skipped. Under the opaque depth the two normals are blended by
// the same absorption the albedo used, so the swing from the bank's tilt to
// the flat mirror is spread over the whole shore ramp instead of standing as a
// line at the waterline.
vec3 tlodWaterNormal() {
  if ( twA <= 0.0 ) {
    return normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
  }
  vec3 wn = normalize( ( viewMatrix * vec4( twN, 0.0 ) ).xyz );
  if ( twA >= 1.0 ) return wn;
  vec3 gn = normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
  return normalize( mix( gn, wn, twA ) );
}

// The two things that are not albedo, written on the finished light: the
// fresnel share of sky (the reflection this renderer can afford, § 3.4) and
// the foam lace at the rim. Same order as the mirror's shader — the foam is
// broken water lying ON the reflection, not under it.
void tlodWaterOut( inout vec3 outgoingLight, vec3 n, vec3 viewPos ) {
  if ( twA <= 0.0 && twFoam <= 0.0 ) return;
  float fres = pow( 1.0 - clamp( dot( normalize( viewPos ), n ), 0.0, 1.0 ), 3.0 );
  outgoingLight = mix( outgoingLight, uTlodSky,
                       clamp( fres * twSkyMix, 0.0, 1.0 ) * twA );
  outgoingLight = mix( outgoingLight, vec3( 1.0 ), twFoam * ${WATER_FOAM_STRENGTH} );
}
`;
}
