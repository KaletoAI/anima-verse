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
 * is a RULED surface over its outline — since W1 every vertex carries the level
 * of its own place (`waterLevelAt`) — and the fragment shader samples the SAME
 * R32F height pyramids the terrain's vertices are placed by
 * (`terrainLod.terrainLodSampleGlsl`), so the water depth under a pixel is
 * `plane y − h(x, z)` — a number in METRES, in our own data, identical near and
 * far. A screen-space depth texture would have been a second render target, a
 * second copy of the ground and a shore that changes width with the camera's
 * near/far planes; this one is a subtraction.
 *
 * THE LEVEL IS NEVER A UNIFORM. The shader reads `vWaterPlane.y`, i.e. the
 * GEOMETRY, which is what let two lakes at two heights share one material —
 * and it is also, unchanged, what lets a tilted river share it with them. W2
 * had nothing to change in the shore for the slope; it only had to stop
 * flattening the mesh.
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
 * THE MIRROR OF ONE WATER AREA AS A FUNCTION OF THE PLACE — the nine numbers
 * of `meta.water_profile` (W1, § A16.3), read straight out of the payload.
 *
 * A lake is one number; a river is a plane tilted along its own flow. Both are
 * this. Without a `flow_dir_deg` the two ends carry the SAME number, `s_min`
 * and `s_max` are both 0, and `waterLevelAt` answers that number everywhere —
 * the constant mirror of every round before W1, reached by the same arithmetic
 * instead of by a branch beside it.
 *
 * The field names are the server's, verbatim (`heightfield.WaterProfile`): a
 * renamed twin is how the two halves of one formula start to drift.
 */
export interface WaterProfile {
  /** world y at the UPSTREAM end of the axis span, in metres */
  level_up: number;
  /** world y at the DOWNSTREAM end */
  level_down: number;
  /** the authored flow bearing, `null` for still water */
  flow_dir_deg: number | null;
  /** the point the axis runs through — the polygon's area centroid */
  axis_x: number;
  axis_z: number;
  /** the DOWNSTREAM unit direction, `(sin θ, cos θ)`; (0, 0) for still water */
  dir_x: number;
  dir_z: number;
  /** the axis coordinates of the upstream and downstream extremes */
  s_min: number;
  s_max: number;
}

/** The one numeric reader: a value that is not a finite number is not a
 *  number at all. `Number(null)` IS 0 and `Number('')` IS 0, which is how a
 *  missing level becomes a mirror at world zero — never here. */
function finite(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

/**
 * The PROFILE of a painted area, or `null` where there is none.
 *
 * `meta.water_profile` is the SERVER's own answer (W1 § 4): the very function
 * the bake carved the bed against, shipped as nine numbers so a renderer builds
 * the same tilted mirror without asking for a raster. Reading it is the WHOLE
 * water test — an area that has one is an area whose bed was carved, an area
 * without one has no mirror to draw. This is the ONE water source of the
 * client: the surface material CLASS says what water looks like, never whether
 * a thing is water (that book is the server's single `is_water_kind`).
 *
 * The authored `meta.water_level` is deliberately NOT read (it may be unset),
 * and neither is `meta.water_level_effective` any more: that field is the MID
 * level of the profile, i.e. what a FLAT consumer draws one plane at, and this
 * client stopped being one in W2. A river drawn at its mid level stands 2.4 m
 * over its own bed at one end and 2.4 m under it at the other.
 *
 * Every one of the nine has to be a finite number, `flow_dir_deg` excepted —
 * `null` there is the shape of still water. One NaN in a vertex position and
 * the whole plane leaves the frustum, so a broken profile draws nothing.
 */
export function waterProfileOf(meta: Record<string, unknown> | null | undefined
): WaterProfile | null {
  const raw = meta?.water_profile;
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;
  const level_up = finite(p.level_up);
  const level_down = finite(p.level_down);
  const axis_x = finite(p.axis_x);
  const axis_z = finite(p.axis_z);
  const dir_x = finite(p.dir_x);
  const dir_z = finite(p.dir_z);
  const s_min = finite(p.s_min);
  const s_max = finite(p.s_max);
  if (level_up === null || level_down === null || axis_x === null
      || axis_z === null || dir_x === null || dir_z === null
      || s_min === null || s_max === null) return null;
  return { level_up, level_down, flow_dir_deg: finite(p.flow_dir_deg),
    axis_x, axis_z, dir_x, dir_z, s_min, s_max };
}

/**
 * THE MIRROR AT ONE POINT — the pure TS twin of `heightfield.water_level_at`,
 * line for line:
 *
 *     s     = (x − axis_x)·dir_x + (z − axis_z)·dir_z
 *     t     = clamp((s − s_min) / (s_max − s_min), 0, 1)
 *     level = level_up + (level_down − level_up)·t
 *
 * STILL WATER FALLS OUT OF IT: with no flow direction the span is empty and
 * both ends are the same number, so the answer is that number everywhere.
 *
 * THE CLAMP IS LOAD-BEARING at the very ends. A polygon is only extreme at its
 * rim, and a point exactly on it must not read past the level the rim median
 * was taken for — `t <= 0` answers `level_up` and `t >= 1` answers
 * `level_down` EXACTLY, not `level_up + (level_down − level_up)·1`, so the two
 * ends of the mesh sit on the two authored numbers to the last bit.
 */
export function waterLevelAt(profile: WaterProfile, x: number, z: number
): number {
  const span = profile.s_max - profile.s_min;
  if (profile.flow_dir_deg === null || span <= 1e-9) return profile.level_up;
  const s = (x - profile.axis_x) * profile.dir_x
          + (z - profile.axis_z) * profile.dir_z;
  const t = (s - profile.s_min) / span;
  if (t <= 0) return profile.level_up;
  if (t >= 1) return profile.level_down;
  return profile.level_up + (profile.level_down - profile.level_up) * t;
}

/**
 * The DOWNSTREAM unit vector the ripple scrolls along, or (0, 0) for still
 * water — the one piece of the profile the SHADER needs.
 *
 * It is `(dir_x, dir_z)` and nothing derived: the server already spells the
 * bearing as `(sin θ, cos θ)` (§ A1.1) and a second `sin`/`cos` here would be
 * a second convention waiting to be spelled the other way round. What this
 * adds is the ZERO: for still water `flow_dir_deg` is `null` and the direction
 * is meaningless, and (0, 0) is what the shader reads as "no flow, keep the
 * lake's own crossing drift" — today's look, unchanged.
 */
export function waterFlowVector(profile: WaterProfile | null | undefined
): [number, number] {
  if (!profile || profile.flow_dir_deg === null) return [0, 0];
  const len = Math.hypot(profile.dir_x, profile.dir_z);
  if (!(len > 1e-9)) return [0, 0];
  return [profile.dir_x / len, profile.dir_z / len];
}

/**
 * Lift a FLAT earcut onto the profile, in place — the whole of "the mirror is
 * a ruled surface" (W2 no. 1).
 *
 * `positions` is a three.js position buffer: `(x, y, z)` triplets of the
 * outline triangulated in the XZ plane, with the `y` component meaningless (it
 * is whatever `rotateX(-π/2)` left of a zero). Each vertex is given the level
 * of ITS OWN place, so a river's mesh is the tilted plane its bed was carved
 * against and a lake's mesh comes out flat.
 *
 * NO SUBDIVISION IS NEEDED and none is done. The profile is LINEAR in the
 * plane by construction (a clamped linear ramp along one axis), and the
 * clamped part is linear too — flat. A ruled surface through the outline's
 * vertices therefore reproduces it exactly wherever the polygon is convex, and
 * where it is not, the earcut's own interior edges are the ruling. The only
 * places the interpolation could deviate are inside a triangle that spans the
 * clamp KINK at `s_min`/`s_max`, and there is none: those are the polygon's own
 * extremes, so no interior point of the polygon lies past them.
 *
 * FOR A LAKE THIS IS BIT-IDENTICAL TO THE FLAT PLANE OF BEFORE. A constant
 * profile answers `level_up` for every vertex, so the mesh is the same
 * horizontal polygon it always was — it just carries its height in the
 * vertices instead of in `mesh.position.y`, and `level + 0` and `0 + level`
 * are the same float.
 */
export function liftToWaterProfile(positions: { length: number;
                                                [index: number]: number },
                                   profile: WaterProfile): void {
  for (let i = 0; i + 2 < positions.length; i += 3) {
    positions[i + 1] = waterLevelAt(profile, positions[i], positions[i + 2]);
  }
}

/**
 * The shore, as the GLSL that rides on `terrainLodSampleGlsl()`.
 *
 * `vWaterPlane` is the fragment's WORLD position. Its `y` is the mirror height
 * itself — the mesh carries the profile in its vertices (`liftToWaterProfile`),
 * so the level is carried by the GEOMETRY and needs no uniform. That is what
 * lets every water of one kind share ONE material however many levels they
 * stand at: two lakes at two heights are two meshes at two heights, not two
 * shaders — AND it is why a tilted river needed no shore change at all in W2.
 * `vWaterPlane.y` interpolates across the ruled surface, so `wsDepth` is the
 * LOCAL level minus the ground, at every pixel, for free.
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

/**
 * How wide the last hand's width of water is, in metres of DEPTH — the band the
 * alpha is faded to nothing over so the rim is not a hard edge.
 *
 * IT IS DERIVED FROM THE FOAM, not tasted. `waterAlpha` answers 0.15 at depth 0
 * (the foam adds it back, deliberately: see `WATER_FOAM_ALPHA`) and the shader
 * discards at depth 0 — so the drawn rim used to STEP from 15 % opaque to
 * nothing across the boundary of a per-fragment `discard`. A step is a step
 * however small, and this one lies on a line whose sub-pixel position moves
 * with the camera: it crawls, and what crawls there is the brightest part of
 * the lake (foam whitens the outgoing light by 0.6 at that very depth). Fading
 * the alpha to 0 over the last 5 cm of depth makes the visible edge an alpha
 * ramp instead, and the ramp is anti-aliased by the blend itself.
 *
 * 5 cm of DEPTH is about 7.5 cm of ground on the default shore
 * (`water_depth_m` 2.0 over `shore_ramp_m` 3.0 is a slope of 2/3 at the rim),
 * i.e. a twentieth of the 1.5 m the shore ramp already spends — it moves the
 * waterline by less than the foam lace is wide.
 */
export const WATER_EDGE_FADE_M = 0.05;

/**
 * The rim fade a water fragment carries: `clamp(depth / edge, 0, 1)`, where
 * `edge` is one pixel measured in metres of DEPTH (`fwidth(wsDepth)` in the
 * shader), floored at `WATER_EDGE_FADE_M`.
 *
 * It is the ONE factor that reaches exactly 0 where the discard begins, which
 * is the whole job — `waterAlpha(0)` is 0.15 and would otherwise be a step.
 *
 *     depth 0        -> 0                (the discard, approached smoothly)
 *     depth ½·edge   -> 0.5
 *     depth ≥ edge   -> 1                (the shore ramp alone from here on)
 */
export function waterEdgeFade(depthM: number, edgeM: number): number {
  const e = Math.max(edgeM, WATER_EDGE_FADE_M);
  if (!Number.isFinite(depthM) || depthM <= 0) return 0;
  const t = depthM / e;
  return t >= 1 ? 1 : t;
}

/**
 * The fragment body, inserted right before `#include <opaque_fragment>`: it
 * is the last place `diffuseColor.a` and `outgoingLight` are both still
 * writable, so the whole shore is ONE insertion instead of three.
 *
 * THE RIM IS FADED, NOT MERELY DISCARDED (finding round 2026-08-21). The
 * discard has to stay — at depth ≤ 0 the mirror and the terrain are the same
 * surface and a fragment that took part in the depth test there would fight the
 * ground for it. But `waterAlpha(0)` is 0.15, not 0, so the drawn rim used to
 * STEP from a 15 %-opaque, 60 %-whitened foam lace to nothing across the
 * boundary of a per-fragment test. That boundary has no width: its sub-pixel
 * position moves as the camera moves, so the brightest line of the lake
 * crawled. Multiplying by `clamp(depth / edge, 0, 1)` puts a ramp there that
 * reaches 0 exactly where the discard begins, so nothing steps.
 *
 * `edge` IS ONE PIXEL, IN METRES OF DEPTH — `fwidth(wsDepth)`, floored at
 * `WATER_EDGE_FADE_M`. The `fwidth` warning of `@anima/scene-render`
 * `layerCut.ts` does not transfer: what explodes there is the derivative of a
 * QUANTISED mask whose neighbouring texels can name a different boundary
 * altogether, while `wsDepth` is a plane minus a bilinear interpolation — C0
 * everywhere, with a gradient that jumps between lattice cells but stays
 * bounded by the steepest cell of the bed. And the floor caps the damage
 * anyway: the worst a wrong `fwidth` can do here is make the last hand's width
 * of water a little softer, on a band the shore ramp is already fading over.
 */
export function waterShoreBody(): string {
  return `
  {
    float wsDepth = vWaterPlane.y - tlodHeight( vWaterPlane.xz, 0.0 );
    // Taken BEFORE the discard, at uniform control flow: a derivative asked for
    // inside a branch that differs across a quad is undefined in GLSL ES.
    float wsEdge = max( fwidth( wsDepth ), ${WATER_EDGE_FADE_M} );
    // The rim, where mirror and terrain are the same surface: not water, and
    // the one band in which a fragment of this plane would fight the ground
    // for the depth test.
    if ( wsDepth <= 0.0 ) discard;
    float wsFoam = 1.0 - wsSmooth( wsDepth / uFoamBandM );
    outgoingLight = mix( outgoingLight, vec3( 1.0 ), wsFoam * uFoamStrength );
    diffuseColor.a *= clamp( wsSmooth( wsDepth / uShoreBandM )
                             + wsFoam * uFoamAlpha, 0.0, 1.0 )
                    * clamp( wsDepth / wsEdge, 0.0, 1.0 );
  }
`;
}
