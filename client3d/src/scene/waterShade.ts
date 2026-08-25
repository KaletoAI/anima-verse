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
 * ── TWO NUMBERS SAY "HOW MUCH WATER", AND THEY ASK DIFFERENT QUESTIONS ──────
 * (finding H2, 2026-08-25 — "warum kann es nicht halbtransparent sein?")
 *
 * `twA`, the ABSORPTION, is the OLD shore alpha (`waterPlaneMath.
 * waterShoreAlpha`, ¾ of the water's own bed depth) and answers HOW MUCH OF
 * THE BED IS GONE. It drives the albedo, and only the albedo:
 * `mix(bed, tint, twA)` IS the semi-transparent look — a centimetre of water
 * shows its sand, a metre and a half of it does not.
 *
 * `twS`, the SURFACE share, answers IS THERE A WATER SURFACE OVER THIS PIXEL —
 * the rim ramp times the shore gate, with no depth in it at all. It drives
 * everything that belongs to the interface rather than to the water column:
 * the roughness, the metalness, the ripple's tilt and the fresnel share of sky.
 *
 * THEY USED TO BE ONE NUMBER, and that was the defect. Coupling the surface
 * terms to the depth curve made shallow water 100 % bed albedo AND 0 % water
 * signal at once: no sheen, no sky, no ripple, ground roughness — sand with a
 * blue-ish cast, i.e. land. It also swallowed the flow (finding H1): the drift
 * runs downstream correctly, but over a shore there was no water normal left
 * to carry a moving crest. Now the colour follows the depth and the surface is
 * a surface wherever the pixel is water.
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
   * that boundary a pixel is on. It does not have to: a pixel that reaches the
   * water shading was LIFTED and stands inside the painted outline — the water
   * raster's own signed distance said so, twice, once per shader stage — so the
   * water half of the pair is its kind. This flag is what picks that half, and
   * picking the half is ALL the id mask is asked for. Asking it whether there
   * is water at all is finding F-A: it names the topmost PAINTED kind, so a
   * lake whose bed is painted answers (sand, sand) over its whole interior.
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
 * HOW MUCH OF THIS PIXEL IS A WATER SURFACE, 0…1 — the CPU twin of the
 * shader's `twS`, and the SECOND of the two shares a water pixel carries
 * (finding H2, 2026-08-25).
 *
 * ── WHY TWO SHARES AND NOT ONE ──────────────────────────────────────────────
 * Until H2 every water term rode {@link waterAbsorb}: the colour, the
 * roughness, the metalness, the ripple normal and the fresnel share of sky
 * alike. That reading is right for exactly one of them. Absorption answers
 * "how much of the BED is gone", which is a question about DEPTH — and the
 * whole point of shallow water is that the bed is NOT gone. Every other term
 * answers "is there a water SURFACE over this pixel", which has nothing to do
 * with depth: a centimetre of water over sand is still a mirror-smooth film
 * that reflects the sky and carries ripples. Coupling the two made a
 * hand's-width of water 100 % bed albedo AND 0 % water signal — sand, with no
 * sheen, no sky and no ripple. That is the user's finding ("warum kann es
 * nicht halbtransparent sein?"): shallow water read as land.
 *
 * So the depth curve keeps the ALBEDO — `mix(bed, tint, twA)` IS the
 * semi-transparent look, the bed showing through in proportion to how little
 * water stands over it — and this number carries everything that belongs to
 * the surface itself.
 *
 * ── WHAT IT IS ──────────────────────────────────────────────────────────────
 * The shader's `rim`, and nothing else: the edge ramp that keeps the waterline
 * from stepping ({@link waterEdgeFade}, one pixel of depth) times the shore
 * gate that says the pixel is inside the authored outline
 * ({@link waterInside}). Both factors are 0 at the waterline and 1 a finger's
 * width in, so the surface fades in over the same band the geometry lifts over
 * (finding G1) — no line, no step, and no depth anywhere in it.
 *
 * Hand values for a rim ramp at its floor (`edgeM` = 0.05 m) well inside the
 * outline (`inside` = 1):
 *
 *     depth 0.025 -> 0.5   (half a floor-pixel: the ramp, not the depth)
 *     depth 0.05  -> 1
 *     depth 0.30  -> 1
 *     depth 1.50  -> 1
 *
 * — i.e. from 5 cm of water on, the pixel is a water surface in FULL, however
 * shallow it is. Compare {@link waterAbsorb} on the default lake at the same
 * three depths: 0.00325926, 0.104, 1.
 */
export function waterSurface(depthM: number, edgeM: number,
                             inside: number): number {
  if (!(depthM > 0)) return 0;
  const g = !Number.isFinite(inside) ? 0 : inside <= 0 ? 0 : inside >= 1 ? 1 : inside;
  return waterEdgeFade(depthM, edgeM) * g;
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
 * HOW FAR INSIDE THE AUTHORED OUTLINE the ground finishes turning into water,
 * in metres — the shore RAMP of the gate, and since finding G1/G3 a fixed
 * number of world metres rather than a screen-pixel width.
 *
 * ── WHY IT IS A WORLD CONSTANT AND NOT A PIXEL (finding G1, 2026-08-25) ─────
 * The gate is read TWICE per water pixel: the vertex stage scales its LIFT by
 * it (`terrainLod.tlodLift`) and the fragment stage scales its LOOK by it. The
 * two must be the SAME curve, or a strip of ground stands lifted onto the
 * mirror while it still shades as ground — a figure standing on the true height
 * there is drawn sunk into the surface, which is exactly the finding. A vertex
 * shader has no pixel footprint, so the one curve both stages can evaluate has
 * to be a function of the world position alone.
 *
 * ── AND THE PIXEL FLOOR WAS ALSO A SEAM (finding G3 point 2) ────────────────
 * The old rule was `max(pixelM, 0.5 m)`, i.e. one screen pixel measured in
 * world metres with a half-metre floor. That term GROWS without bound: one
 * pixel of a 45° camera over 900 rows is 8.727e-4 rad, so its ground footprint
 * at slant distance D and grazing angle θ is `D · 8.727e-4 / sin θ` —
 *
 *     D = 50 m,  θ = 40°  ->  0.068 m   (the floor wins, band 0.5 m)
 *     D = 150 m, θ = 40°  ->  0.204 m   (the floor wins, band 0.5 m)
 *     D = 400 m, θ = 40°  ->  0.543 m   (the pixel wins, band 0.543 m)
 *     D = 400 m, θ = 10°  ->  2.011 m   (band 2.0 m)
 *     D = 400 m, θ =  5°  ->  4.001 m   (band 4.0 m)
 *
 * — and a band metres wide is metres of shore painted as half-ground, i.e. the
 * fat sand seam the finding names, worst exactly where a shore is seen most
 * often: far away and nearly edge-on. Half a metre is half a metre at every
 * distance.
 *
 * WHAT THE PIXEL TERM WAS FOR is anti-aliasing a HARD material cut
 * (`layerWeight`). This cut is not hard any more: the same band now ramps the
 * SURFACE HEIGHT with it, so the waterline is a geometric ramp and not a step
 * in albedo alone, and the curve leaves 0 with zero slope. What is left is the
 * ordinary edge aliasing every distant silhouette in this world has.
 */
export const WATER_SD_BAND_M = 0.5;

/**
 * HOW MUCH WATER THIS POINT IS, 0…1 — the CPU twin of the shader's `twInside`,
 * read by the fragment stage as "how much of the water LOOK" and by the vertex
 * stage as "how much of the LIFT" (`terrainLod.tlodLift`). One curve, one band,
 * both stages: that identity is the whole of finding G1.
 *
 * Since finding F-A it reads the water raster's OWN signed distance rather than
 * the ground compositor's material mask.
 *
 * THE SEAM IT CLOSES. The water raster is DILATED: the server writes a level up
 * to `WATER_RASTER_DILATION_STEPS` (4 m) past the authored outline, so that
 * every point inside a water polygon reads four wet corners on the base lattice
 * (`waterRaster.waterBilinear`). Shading on the lift alone therefore painted a
 * band of cm-shallow water all round every shore — the grey wash, and the white
 * foam rim before its cover was restored.
 *
 * WHY IT IS NOT THE MATERIAL MASK ANY MORE (finding F-A). The first fix asked
 * the compositor's id pair: "which two KINDS meet here, and which side am I
 * on". That pair names the topmost PAINTED kind, and a lake whose bed is
 * painted — a sand shape inside the outline, which is what `bed_kind`
 * describes and what a generated map draws — reads (sand, sand) over its whole
 * interior. Both halves not water, so the gate answered 0 and the lake was
 * drawn as the sand it stands on: "the lake is only a sand surface". The
 * question is about the WATER's outline, and only the water field knows it.
 *
 * THE RULE, one line: `smoothstep(0, WATER_SD_BAND_M, sd)`.
 *
 * ONE-SIDED, AND THAT IS THE SECOND HALF OF G1. The band used to straddle the
 * outline (`smoothstep(−band/2, +band/2, sd)`), which said two things this
 * renderer does not mean: that water reaches a quarter of a metre PAST the line
 * the author drew, and that the line itself is half water. The outer half was
 * dead anyway — outside the outline the lift never fired, so the fragment
 * returned on `d <= 0` before the gate was reached — while the inner half is
 * where the sinking lived. Starting at 0 makes the authored outline exactly the
 * edge of the water, in the geometry and in the look alike, and the curve's
 * slope is 0 there, so nothing steps.
 *
 * Hand values (band 0.5 m), `t = sd/0.5`, `3t² − 2t³`:
 *
 *     sd = −0.25 -> 0                      (the dilation ring: ground)
 *     sd =  0    -> 0                      (the authored waterline)
 *     sd =  0.05 -> t=0.1  -> 0.028
 *     sd =  0.1  -> t=0.2  -> 0.104
 *     sd =  0.125-> t=0.25 -> 0.15625
 *     sd =  0.25 -> t=0.5  -> 0.5
 *     sd =  0.375-> t=0.75 -> 0.84375
 *     sd =  0.5  -> t=1    -> 1            (full water from here in)
 *     sd =  1    -> 1
 */
export function waterInside(sd: number): number {
  const t = Math.min(Math.max(sd / WATER_SD_BAND_M, 0), 1);
  return t * t * (3 - 2 * t);
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
 * THE SHADING NORMAL of a water pixel, in WORLD space — the CPU twin of the
 * shader's `tlodWaterNormal`, and the one term of finding H2 that needs both
 * shares at once.
 *
 * ── THE COMPOSITION, IN TWO HALVES ──────────────────────────────────────────
 * A MACRO normal and a PERTURBATION, and each rides its own share:
 *
 *   macro = mix(ground, up, absorb)      — the surface the water lies on
 *   n     = normalize(macro + (ripple − up) · surface)
 *
 * The MACRO half is a depth question, so it rides the absorption: where the
 * bed is fully gone the surface IS a flat mirror (`up`), and where it shows
 * through, the bank's own tilt is still the shape the light falls on. The
 * PERTURBATION — the ripple's tilt off flat, which is all `twRipple` ever
 * produces — is a surface question, so it rides the surface share and is there
 * in FULL over a centimetre of water.
 *
 * ── WHY NOT THE OLD `mix(ground, ripple, absorb)` ───────────────────────────
 * Because it made the ripple invisible exactly where it matters. On the
 * default lake at 5 cm of depth the absorption is 0.00325926, so the ripple got
 * 0.33 % of its say: the shading normal was the bank's, the specular lobe was
 * the ground's roughness, and NOTHING on that surface moved. That is the other
 * half of "the water does not flow" (finding H1) — the drift is correct, the
 * pattern travels downstream (see `twRipple`), but over most of a shore there
 * was no water normal left to carry it.
 *
 * ── THE TWO EARLY-OUTS SURVIVE UNCHANGED ────────────────────────────────────
 * `surface = 0` (dry, or outside the outline) gives `macro + 0 = ground`.
 * `absorb = 1` gives `macro = up` and `up + (ripple − up)·1 = ripple`, which is
 * the deep-water answer the shader returns without reading the bed's normal at
 * all — sixteen `texelFetch` still skipped, bit for bit the old picture below
 * the opaque depth.
 *
 * Hand check on a bank tilted 26.565° (`ground = normalize(0.5, 1, 0)` =
 * (0.4472136, 0.89442719, 0)) under a ripple tilted 16.699°
 * (`ripple = normalize(0.3, 1, 0)` = (0.28734789, 0.95782629, 0)), i.e.
 * `ripple − up` = (0.28734789, −0.04217371, 0):
 *
 *   absorb 0.00325926, surface 1 (5 cm of lake)
 *     macro = (0.44575601, 0.89477128, 0)
 *     sum   = (0.73310390, 0.85259757, 0), |sum| = 1.12443939
 *     n     = (0.65197280, 0.75824235, 0)  — 14.1255° off the bare bank
 *     (the OLD `mix(ground, ripple, absorb)` gave 0.031998° — the ripple had
 *      0.33 % of its say, which is why nothing on a shore ever moved)
 *   absorb 1, surface 1 (1.5 m of lake)
 *     n     = ripple, exactly
 *   surface 0
 *     n     = ground, exactly
 */
export function waterShadeNormal(ground: readonly [number, number, number],
                                 ripple: readonly [number, number, number],
                                 absorb: number, surface: number):
                                 [number, number, number] {
  const a = absorb <= 0 ? 0 : absorb >= 1 ? 1 : absorb;
  const s = surface <= 0 ? 0 : surface >= 1 ? 1 : surface;
  const x = ground[0] + (0 - ground[0]) * a + (ripple[0] - 0) * s;
  const y = ground[1] + (1 - ground[1]) * a + (ripple[1] - 1) * s;
  const z = ground[2] + (0 - ground[2]) * a + (ripple[2] - 0) * s;
  const len = Math.hypot(x, y, z);
  return len > 0 ? [x / len, y / len, z / len] : [0, 1, 0];
}

/**
 * THE SIGNED DISTANCE SAMPLER, as GLSL — ONE text, included by BOTH stages of
 * the water variant (finding F-A/F-B).
 *
 * The vertex stage gates its LIFT on it and the fragment stage gates its
 * SHADING on it, and the two must be the same field read the same way or a
 * pixel is lifted and painted as ground, or painted as water and left on the
 * bed. They cannot share a function through the shader (a vertex and a fragment
 * shader are two programs' worth of source), so they share this string.
 *
 * IT DECLARES ONLY THE SAMPLER. `uTlodWaterGeom` is the water pyramid's own
 * geometry `(originX, originZ, step, levelCount)` and is already declared by
 * whichever chunk includes this one — the vertex's `terrainLodWaterGlsl`, the
 * fragment's `terrainWaterFragmentGlsl` — because declaring it twice in one
 * shader is a compile error.
 *
 * THE LATTICE IS `uTlodWaterLevel[0]`'s and the window is the NEAR RECTANGLE,
 * both without being told: the sd field is built over the water pyramid's base
 * level (`buildSd`), which is built over the near pyramid's own geometry, so
 * `textureSize` IS `(cols, rows)` of that level and
 * `[origin, origin + (n − 1)·step]` IS `uTlodNearRect`. Asking the texture is
 * therefore the same test the level's `tlodWaterAt` makes against the rectangle
 * — one that also works in the fragment shader, where `uTlodNearRect` is not
 * declared.
 *
 * OUT THERE IT IS DRY AND NOT CLAMPED. The level clamps its lattice coordinate
 * and leans on the rectangle test beside it; here the test IS the clamp's
 * replacement, because an edge texel carried outward would paint a strip of
 * "inside the water" along the whole window rim.
 */
export function waterSdGlsl(): string {
  return `
uniform sampler2D uTlodWaterSd;

// What "outside every water" is worth. The TS twin is \`waterRaster.WATER_SD_DRY\`
// and the value is the same for the same reason: a plain bilinear mix of it
// with a real ring value stays far negative, and it is FINITE, so it cannot
// turn a mix into a NaN the way the level's dry sentinel would.
const float TW_SD_DRY = -1.0e4;

float twSdAt( vec2 p ) {
  if ( uTlodWaterGeom.w <= 0.0 ) return TW_SD_DRY;
  ivec2 sz = textureSize( uTlodWaterSd, 0 );
  float cols = float( sz.x );
  float rows = float( sz.y );
  float stepM = uTlodWaterGeom.z;
  if ( cols < 2.0 || rows < 2.0 || stepM <= 0.0 ) return TW_SD_DRY;
  float fx = ( p.x - uTlodWaterGeom.x ) / stepM;
  float fz = ( p.y - uTlodWaterGeom.y ) / stepM;
  if ( fx < 0.0 || fz < 0.0 || fx > cols - 1.0 || fz > rows - 1.0 ) return TW_SD_DRY;
  float fi = min( floor( fx ), cols - 2.0 );
  float fj = min( floor( fz ), rows - 2.0 );
  float tx = fx - fi;
  float tz = fz - fj;
  int i = int( fi );
  int j = int( fj );
  // PLAIN bilinear, all four corners read: the dry sentinel is a NUMBER here,
  // so a dry corner pulls the answer negative — which is the right direction —
  // instead of poisoning it the way the level's NaN would. It cannot pull a
  // point INSIDE an outline negative: the server's dilation guarantees all four
  // corners of such a point's cell carry a real distance (§ A16.5 point 3).
  float s00 = texelFetch( uTlodWaterSd, ivec2( i, j ), 0 ).r;
  float s10 = texelFetch( uTlodWaterSd, ivec2( i + 1, j ), 0 ).r;
  float s01 = texelFetch( uTlodWaterSd, ivec2( i, j + 1 ), 0 ).r;
  float s11 = texelFetch( uTlodWaterSd, ivec2( i + 1, j + 1 ), 0 ).r;
  return mix( mix( s00, s10, tx ), mix( s01, s11, tx ), tz );
}
`;
}

/**
 * THE GATE, as GLSL — the second text BOTH stages of the water variant include
 * (finding G1), beside {@link waterSdGlsl}.
 *
 * The vertex stage scales its LIFT by `twInside`, the fragment stage its LOOK.
 * They are two programs and cannot share a function through the shader, so —
 * exactly as with the sd sampler — they share this string. A curve that existed
 * twice would drift, and the drift is the finding: ground standing on the
 * mirror while it shades as ground.
 *
 * `twSmooth` lives here rather than in the fragment chunk for the same reason:
 * it is the curve, and the curve has one home.
 *
 * NO UNIFORM OF ITS OWN, and no derivative: the band is a world constant
 * ({@link WATER_SD_BAND_M}) precisely so a vertex shader can evaluate it.
 */
export function waterGateGlsl(): string {
  return `
float twSmooth( float t ) {
  float c = clamp( t, 0.0, 1.0 );
  return c * c * ( 3.0 - 2.0 * c );
}

// HOW MUCH WATER THIS POINT IS, 0…1 — the lift in the vertex stage, the look in
// the fragment stage. The TS twin and the whole argument are in \`waterInside\`.
float twInside( float sd ) {
  return twSmooth( sd / ${WATER_SD_BAND_M} );
}
`;
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
 *     in the five globals below.
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
uniform vec4 uTlodWaterGeom;
uniform vec3 uTlodSky;
uniform float uTlodTime;
${waterSdGlsl()}${waterGateGlsl()}

// What tlodWaterSurface() measures and the two stages after it read. Globals
// and not a struct passed along: the three insertion points are three separate
// chunks of three's own shader and cannot hand each other a value.
//
// TWO SHARES, NOT ONE (finding H2, 2026-08-25). \`twA\` is HOW MUCH OF THE BED
// IS GONE — the depth curve — and it drives the COLOUR alone. \`twS\` is HOW
// MUCH OF THIS PIXEL IS A WATER SURFACE — the rim ramp times the shore gate,
// with no depth in it at all — and it drives everything that belongs to the
// surface: the roughness, the metalness, the ripple's tilt and the fresnel
// share of sky. \`twS >= twA\` everywhere by construction (twA = shore · twS,
// shore in 0…1). The TS twins are \`waterAbsorb\` and \`waterSurface\`.
float twA;
float twS;
float twFoam;
float twSkyMix;
vec3 twN;

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
// THE FRAME ARRIVES SMOOTHED (finding F-C). \`vTlodFlow\` is the raster's flow,
// and the bake now runs that field through a separable box of the dilation's own
// radius before it ships (\`heightfield.WATER_FLOW_BLUR_M\`): the axis tangent
// JUMPS across a medial axis, and two neighbouring lattice points handing this
// function two very different frames is what broke the surface into
// triangle-sized patches. Measured on an authored meander the worst adjacent
// pair is 1.49 deg after the blur (1.80 before); on a hairpin drawn inside a
// lake-sized polygon, 66 deg after 146. Nothing here changed for it — the
// varying is simply continuous now.
//
// WHICH WAY THE PATTERN REALLY TRAVELS — the sign, derived rather than
// asserted (finding H1, 2026-08-25). Each sheet's sample coordinate is
//
//     uv(p, t) = F( p / lam + dir * ( t * sp * sgn / lam ) )
//
// with F the flow frame's linear squeeze (\`twFrame\`), which is invertible. A
// FIXED FEATURE of the normal map sits at a fixed uv0; the world point that
// shows it is found by solving uv(p, t) = uv0:
//
//     F(p) = lam * uv0 − F(dir) * t * sp * sgn
//     d F(p) / dt = −F(dir) * sp * sgn        and F is linear, so
//     dp / dt = −dir * sp * sgn.
//
// Adding the drift to a SAMPLE coordinate therefore slides the picture the
// OTHER way — the classic leftward scroll of \`uv + vec2(t, 0)\`, and the exact
// bug the mirror carried until commit 09f2b29f. With \`sgn = −1\` on flowing
// water the feature travels at \`+dir * sp\`, i.e. DOWNSTREAM at sp·|dir| m/s;
// with \`sgn = +1\` it would travel upstream. The identity the smoke pins is the
// sharpest form of the same statement:
//
//     uv( p0 + dir * sp * t, t ) == uv( p0, 0 )   for every t, exactly
//
// — the crest rides the world at velocity \`dir · sp\`. Still water keeps the
// +1 it always had (a lake has no reference direction, and its two sheets
// counter-scroll either way), which is the mirror's accepted convention.
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
  twS = 0.0;
  twFoam = 0.0;
  twSkyMix = 0.0;
  twN = vec3( 0.0, 1.0, 0.0 );
  float d = vTlodWet;
  float edge = max( fwidth( d ), ${WATER_EDGE_FADE_M} );
  vec2 gx = dFdx( vTlodXZ );
  vec2 gy = dFdy( vTlodXZ );
  if ( d <= 0.0 ) return;
  int rows = textureSize( uTlodWaterLook, 0 ).y;
  // HOW MUCH WATER THIS PIXEL IS — the water raster's own signed distance, the
  // SAME field through the same sampler (\`waterSdGlsl\`) and through the SAME
  // curve (\`waterGateGlsl\`) the vertex stage scaled its lift by. That the two
  // stages share both texts is what keeps the drawn surface and the drawn look
  // on the same shore ramp (finding G1).
  float inside = twInside( twSdAt( vTlodXZ ) );
  // WHICH KIND'S LOOK — and this is ALL the id mask is asked for now. It names
  // the topmost painted layer and the one under it, which is the right question
  // for "what does the water here look like" and the wrong one for "is there
  // water here" (finding F-A: a lake with a painted bed answers (sand, sand)).
  //
  // OUTSIDE THE MASK WINDOW the fallback row 0 stands, exactly as before: every
  // row of the look table carries a water look, the world's primary one where a
  // layer is not water at all, so the worst case out there is the wrong water
  // and never a ground-coloured lake.
  int layer = 0;
  float maskN = uTlodWaterMaskGeom.w;
  vec2 maskIdx = ( vTlodXZ - uTlodWaterMaskGeom.xy ) / uTlodWaterMaskGeom.z;
  if ( maskN > 1.5 && maskIdx.x >= 0.0 && maskIdx.y >= 0.0
       && maskIdx.x < maskN && maskIdx.y < maskN ) {
    uvec2 pair = texelFetch( uTlodWaterMask, ivec2( floor( maskIdx ) ), 0 ).rg;
    int a = clamp( int( pair.x ), 0, rows - 1 );
    int b = clamp( int( pair.y ), 0, rows - 1 );
    layer = twIsWater( a ) ? a : b;
  }
  // The rim ramp: 0 exactly where the water ends, 1 one pixel of depth in —
  // and 0 outside the authored outline, where the lift no longer fires either.
  float rim = clamp( d / edge, 0.0, 1.0 ) * inside;
  if ( rim <= 0.0 ) return;
  vec4 look0 = texelFetch( uTlodWaterLook, ivec2( 0, layer ), 0 );
  vec4 look1 = texelFetch( uTlodWaterLook, ivec2( 1, layer ), 0 );
  vec4 look2 = texelFetch( uTlodWaterLook, ivec2( 2, layer ), 0 );
  float shore = twSmooth( d / max( look1.w, 1e-3 ) );
  // THE SURFACE SHARE is the rim itself: a pixel inside the outline with water
  // over it IS a water surface, however thin the film (finding H2). The
  // ABSORPTION is that share narrowed by the depth curve — how much of the bed
  // has gone. Everything below picks one of the two on purpose.
  twS = rim;
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
  //
  // AND THE COLOUR IS THE ONE TERM THE DEPTH KEEPS. That mix IS the
  // semi-transparent look the finding asks for: over a centimetre of water the
  // bed shows through almost whole, over a metre and a half it is gone.
  diffuseColor.rgb = mix( diffuseColor.rgb, look0.rgb, twA );
  // …while the two MATERIAL constants ride the SURFACE share. A film of water
  // over sand is a smooth, faintly metallic surface at any depth; giving these
  // the depth curve is what left shallow water with the roughness of dry
  // ground (0.847 of 0.85 at 5 cm) and no sheen at all (finding H2).
  roughnessFactor = mix( roughnessFactor, look2.x, twS );
  metalnessFactor = mix( metalnessFactor, look2.y, twS );
}

// THE SHADING NORMAL of a water pixel — a MACRO normal and a PERTURBATION,
// each on its own share (finding H2), and the one place K-A gives GPU work
// back rather than taking it.
//
// MACRO = mix( ground, up, twA ). "What shape does the light fall on" is a
// DEPTH question: where the bed is fully absorbed the surface is a flat
// mirror, and where the bed shows through, its own tilt is still the shape.
//
// PERTURBATION = ( twN − up ) · twS. The ripple's tilt off flat is all
// \`twRipple\` ever makes, and whether a surface ripples is not a depth
// question at all. Riding it on twA is what left a shore with 0.33 % of its
// ripple at 5 cm of water — a mirror-still, ground-rough bank, which is the
// other half of "the water does not flow" (finding H1: the DRIFT is correct,
// there was simply no water normal left to carry it).
//
// BOTH EARLY-OUTS SURVIVE, arithmetically identical to before:
//  * twS == 0 (dry, or outside the outline) -> macro + 0 == ground.
//  * twA == 1 -> macro == up and up + ( twN − up ) == twN, so the bed's normal
//    is not computed at all: \`tlodNormalAt\` is four \`tlodHeight\` calls, i.e.
//    SIXTEEN texelFetch, still skipped for every pixel below the opaque depth.
// The TS twin of the whole composition is \`waterShadeNormal\`.
vec3 tlodWaterNormal() {
  if ( twS <= 0.0 ) {
    return normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
  }
  if ( twA >= 1.0 ) {
    return normalize( ( viewMatrix * vec4( twN, 0.0 ) ).xyz );
  }
  vec3 up = vec3( 0.0, 1.0, 0.0 );
  vec3 macro = mix( tlodNormalAt( vTlodXZ ), up, twA );
  vec3 nw = normalize( macro + ( twN - up ) * twS );
  return normalize( ( viewMatrix * vec4( nw, 0.0 ) ).xyz );
}

// The two things that are not albedo, written on the finished light: the
// fresnel share of sky (the reflection this renderer can afford, § 3.4) and
// the foam lace at the rim. Same order as the mirror's shader — the foam is
// broken water lying ON the reflection, not under it.
//
// THE SKY SHARE RIDES twS AND NOT twA (finding H2). A wet road mirrors the
// sky, and it is a millimetre deep; the reflection off a water surface is a
// property of the INTERFACE, not of what stands under it. On the default lake
// at 5 cm the old coupling gave a sky share of 0.00089630 against 0.275 — i.e.
// none, which is precisely how shallow water came to read as land.
void tlodWaterOut( inout vec3 outgoingLight, vec3 n, vec3 viewPos ) {
  if ( twS <= 0.0 && twFoam <= 0.0 ) return;
  float fres = pow( 1.0 - clamp( dot( normalize( viewPos ), n ), 0.0, 1.0 ), 3.0 );
  outgoingLight = mix( outgoingLight, uTlodSky,
                       clamp( fres * twSkyMix, 0.0, 1.0 ) * twS );
  outgoingLight = mix( outgoingLight, vec3( 1.0 ), twFoam * ${WATER_FOAM_STRENGTH} );
}
`;
}
