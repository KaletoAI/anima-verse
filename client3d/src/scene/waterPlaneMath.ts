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
 * The bake's own default bed depth, in metres — `heightfield.WATER_DEPTH_DEFAULT_M`.
 *
 * The ONE place this client repeats a server number, and it repeats it for one
 * job only: to stand in when a payload carries no `meta.water_depth_effective`
 * at all. Every area that really was baked ships its own.
 */
const WATER_DEPTH_DEFAULT_M = 2.0;

/**
 * How much of a water's own depth it has to reach before it is fully drawn.
 *
 * DERIVED FROM THE BAKE, not tasted. E1 (§ A16 addendum § 2) carves the bed of
 * an area with `water_depth_m` metres of depth, reached over `shore_ramp_m` of
 * ground, via `smoothstep`:
 *
 *     depth(d) = water_depth_m · smoothstep( d / shore_ramp_m )
 *
 * Asking for full opacity at ¾ of the depth therefore asks for it where
 * `smoothstep(t) = 0.75`, i.e. `3t² − 2t³ = 0.75`, i.e. t ≈ 0.6736 — AT THE
 * SAME FRACTION OF THE SHORE RAMP, whatever the depth is. The water fades in
 * over the first two thirds of the ramp the author drew and is fully drawn by
 * the time the bed levels off: for the default lake (2.0 m over 3.0 m) that is
 * 2.02 m inside the outline, for the seeded river (1.2 m over 1.0 m) 0.674 m.
 *
 * THAT IS THE WHOLE OF W4b. Until then the band was the CONSTANT 1.5 m below —
 * the ¾ of the default lake, frozen — and a 6 m wide river with two 1 m banks
 * never reached it, so it stayed see-through to its own middle while the lake
 * next to it looked right. The fraction is the law; the metres are the area's.
 */
const WATER_OPAQUE_FRACTION = 0.75;

/**
 * How deep THIS water has to be before it is fully drawn, in metres (W4b).
 *
 * `depthM` is the area's effective bed depth as the payload ships it
 * (`meta.water_depth_effective`, § A16.3 — the kind's default with the area's
 * override already applied, so this side never repeats that resolution). A
 * value that is not a positive finite number is not a depth: the default lake
 * answers instead, which is what every water looked like before W4b.
 */
export function waterOpaqueDepthM(depthM: unknown): number {
  const raw = Number(depthM);
  const depth = Number.isFinite(raw) && raw > 0 ? raw : WATER_DEPTH_DEFAULT_M;
  return depth * WATER_OPAQUE_FRACTION;
}

/**
 * The opaque depth of the DEFAULT lake, in metres — the stand-in, and nothing
 * else.
 *
 * It is `waterOpaqueDepthM(2.0)` and is DERIVED FROM IT, not typed out beside
 * it: since W4b the number the shader reads is the AREA's (the `aWaterOpaque`
 * attribute), and this is only what a mirror without a shipped depth falls back
 * to. 1.5 m, unchanged, so a world whose payload predates the field looks
 * exactly as it did.
 *
 * It is also, to the centimetre, the default transition width of every other
 * ground (`edge_blend_m = 1.5`, § A17 § 4) — a lake ends over the same metres
 * a meadow ends over. That is a coincidence of two defaults and not a
 * dependency; this one is measured in DEPTH, the other in ground distance.
 */
export const WATER_SHORE_BAND_M = waterOpaqueDepthM(WATER_DEPTH_DEFAULT_M);

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
 * How much of the water is drawn over a bed `depthM` under the mirror, 0…1,
 * for a water that is fully drawn at `opaqueDepthM` (W4b).
 *
 * `depthM ≤ 0` is not water at all — the bed is at or above the mirror, which
 * happens outside the carved outline and nowhere inside it (the E1 invariant).
 * The shader DISCARDS there rather than drawing a zero-alpha fragment: that is
 * the one band where the plane and the terrain are coplanar, and a fragment
 * that takes part in the depth test there flickers however small its alpha is.
 *
 * THE BAND IS A PARAMETER, not a constant any more: it is ¾ of the AREA's own
 * bed depth (`waterOpaqueDepthM`), handed to the shader per vertex. Hand values
 * for the default lake (depth 2.0 -> band 1.5), `t = depth / 1.5`, `3t² − 2t³`:
 *
 *     0.0   -> t = 0        -> 0            (discarded, see above)
 *     0.15  -> t = 0.1      -> 0.028
 *     0.30  -> t = 0.2      -> 0.104
 *     0.375 -> t = 0.25     -> 0.15625
 *     0.75  -> t = 0.5      -> 0.5
 *     1.125 -> t = 0.75     -> 0.84375
 *     1.5   -> t = 1        -> 1
 *     2.0   -> clamped      -> 1
 *
 * …and for the seeded river (depth 1.2 -> band 0.9), the same six fractions of
 * the band, i.e. the same six answers 0.6 times as deep:
 *
 *     0.09  -> t = 0.1      -> 0.028
 *     0.18  -> t = 0.2      -> 0.104
 *     0.225 -> t = 0.25     -> 0.15625
 *     0.45  -> t = 0.5      -> 0.5
 *     0.675 -> t = 0.75     -> 0.84375
 *     0.9   -> t = 1        -> 1
 */
export function waterShoreAlpha(depthM: number, opaqueDepthM: number): number {
  if (!Number.isFinite(depthM) || depthM <= 0) return 0;
  return smoothstep01(depthM / opaqueDepthM);
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
 * With the default lake's band (1.5 m):
 *
 *     depth 0.0  -> 0     + 1·0.15      = 0.15
 *     depth 0.15 -> 0.028 + 0.84375·0.15 = 0.1546875
 *     depth 0.3  -> 0.104 + 0.5·0.15    = 0.179
 *     depth 0.6  -> 0.352 + 0           = 0.352
 *     depth 1.5  -> 1     + 0           = 1
 *
 * The FOAM does not scale with the band (W4b): it is half a metre of real
 * water at a real rim, the same half metre in a pond and in a lake.
 */
export function waterAlpha(depthM: number, opaqueDepthM: number): number {
  const a = waterShoreAlpha(depthM, opaqueDepthM)
    + waterFoam(depthM) * WATER_FOAM_ALPHA;
  return a <= 0 ? 0 : a >= 1 ? 1 : a;
}

/**
 * One knot of the flow axis: `[x, z, s, level]` — the world position, the arc
 * length from the FIRST knot, and the mirror height there
 * (`heightfield.WaterKnot`, § A16.3).
 */
export type WaterKnot = [number, number, number, number];

/**
 * THE MIRROR OF ONE WATER AREA AS A FUNCTION OF THE PLACE — `meta.water_profile`
 * (W1, polyline since W4a, § A16.3), read straight out of the payload.
 *
 * THE TRUTH IS `axis`, the knots. A lake is ONE knot, a straight river TWO, a
 * river drawn with the line tool one wherever its mirror BENDS (W5b: the bake
 * samples that line every 2 m and simplifies the levels back down, so the knots
 * are the ground's bends and not the author's clicks) — the old laws are the
 * degenerate cases of the new one and `waterLevelAt` is one code path for all
 * three. A meander is why: projected onto a single straight axis, the two ends
 * of a 180° loop land on the same axis point, so the mirror of a bend could not
 * fall at all.
 *
 * The nine numbers beside it are the same mirror as ONE TILTED PLANE — what a
 * reader that never heard of the polyline gets. THIS client is not one of them
 * any more (nothing below reads them), and they are kept in the type because
 * the type is the payload, verbatim.
 *
 * The field names are the server's, verbatim (`heightfield.WaterProfile`): a
 * renamed twin is how the two halves of one formula start to drift.
 */
export interface WaterProfile {
  /** the knots in FLOW order, at least one — the axis itself */
  axis: WaterKnot[];
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
 * The knots of `raw`, or `null` where they are not a usable axis (W4a).
 *
 * A list of at least one quadruple of finite numbers, and nothing else. The
 * axis is what the whole mirror is evaluated on since W4a, so a payload whose
 * axis is broken has NO mirror — the same rule the nine numbers already
 * followed, for the same reason: one NaN in a vertex position and the entire
 * plane leaves the frustum.
 */
function axisOf(raw: unknown): WaterKnot[] | null {
  if (!Array.isArray(raw) || raw.length < 1) return null;
  const out: WaterKnot[] = [];
  for (const knot of raw) {
    if (!Array.isArray(knot) || knot.length < 4) return null;
    const x = finite(knot[0]);
    const z = finite(knot[1]);
    const s = finite(knot[2]);
    const level = finite(knot[3]);
    if (x === null || z === null || s === null || level === null) return null;
    out.push([x, z, s, level]);
  }
  return out;
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
 * `null` there is the shape of still water — AND SO DOES EVERY KNOT of the
 * `axis` (W4a), which is the part this client actually evaluates. One NaN in a
 * vertex position and the whole plane leaves the frustum, so a broken profile
 * draws nothing.
 */
export function waterProfileOf(meta: Record<string, unknown> | null | undefined
): WaterProfile | null {
  const raw = meta?.water_profile;
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;
  const axis = axisOf(p.axis);
  const level_up = finite(p.level_up);
  const level_down = finite(p.level_down);
  const axis_x = finite(p.axis_x);
  const axis_z = finite(p.axis_z);
  const dir_x = finite(p.dir_x);
  const dir_z = finite(p.dir_z);
  const s_min = finite(p.s_min);
  const s_max = finite(p.s_max);
  if (axis === null || level_up === null || level_down === null
      || axis_x === null || axis_z === null || dir_x === null || dir_z === null
      || s_min === null || s_max === null) return null;
  // In the payload's own key order, so a smoke may compare the whole object
  // against the JSON it came from.
  return { level_up, level_down, flow_dir_deg: finite(p.flow_dir_deg),
    axis_x, axis_z, dir_x, dir_z, s_min, s_max, axis };
}

/**
 * The NEAREST POINT on the axis, as `[s, segment]` — the twin of
 * `heightfield._axis_s_at`, with the winning segment kept beside its arc
 * coordinate so the flow can be read off the same projection.
 *
 * Every segment is projected onto WITH A CLAMP to its own ends, and the
 * shortest distance wins; the answer is that segment's `s` interpolated by the
 * projection. The candidate the loop starts from is the FIRST KNOT — the whole
 * answer for a one-knot (still) axis, and dominated by the first segment for
 * every longer one.
 *
 * THE COMPARISON IS STRICT (`<`), exactly as on the server, and that decides
 * the ties: a point sitting ON a knot is at distance 0 from both of its legs,
 * and the earlier — the UPSTREAM — leg keeps it. The level is the same number
 * either way; the flow tangent is not, and this is where that choice is made.
 */
function nearestOnAxis(axis: WaterKnot[], x: number, z: number
): [number, number] {
  let bestS = axis[0][2];
  let bestD2 = (x - axis[0][0]) * (x - axis[0][0])
             + (z - axis[0][1]) * (z - axis[0][1]);
  let bestSeg = 0;
  for (let i = 1; i < axis.length; i += 1) {
    const [ax, az, aS] = axis[i - 1];
    const [bx, bz, bS] = axis[i];
    const dx = bx - ax;
    const dz = bz - az;
    const seg = dx * dx + dz * dz;
    let u = seg <= 1e-18 ? 0 : ((x - ax) * dx + (z - az) * dz) / seg;
    u = u < 0 ? 0 : u > 1 ? 1 : u;
    const px = ax + dx * u;
    const pz = az + dz * u;
    const d2 = (x - px) * (x - px) + (z - pz) * (z - pz);
    if (d2 < bestD2) {
      bestD2 = d2;
      bestS = aS + (bS - aS) * u;
      bestSeg = i - 1;
    }
  }
  return [bestS, bestSeg];
}

/**
 * The level of the axis at arc coordinate `s`, linear between the knots — the
 * twin of `heightfield._axis_level_at`.
 *
 * CLAMPED AT BOTH ENDS, and that matters: the knots sit where the levels were
 * measured, and a point past the last one must not read past the level that
 * measurement stands for. `s <= axis[0][2]` answers the first knot EXACTLY and
 * `s >= axis[last][2]` the last one EXACTLY — not a lerp with t = 0 or 1 — so
 * the ends of the mesh sit on the authored numbers to the last bit. A one-knot
 * axis answers its own level here, because its `s` is both the first and the
 * last.
 */
function axisLevelAt(axis: WaterKnot[], s: number): number {
  if (s <= axis[0][2]) return axis[0][3];
  const last = axis[axis.length - 1];
  if (s >= last[2]) return last[3];
  for (let i = 1; i < axis.length; i += 1) {
    const [, , aS, aLevel] = axis[i - 1];
    const [, , bS, bLevel] = axis[i];
    if (s <= bS) {
      const span = bS - aS;
      if (span <= 1e-12) return bLevel;
      return aLevel + (bLevel - aLevel) * ((s - aS) / span);
    }
  }
  return last[3];
}

/**
 * THE MIRROR AT ONE POINT — the pure TS twin of `heightfield.water_level_at`,
 * line for line, and ONE code path since W4a:
 *
 *     s     = arc coordinate of the NEAREST point on the polyline
 *             (each segment projected with a clamp, shortest distance wins)
 *     level = linear between the two knots s falls between, clamped at both
 *             ends of the line
 *
 * BOTH OLD LAWS FALL OUT OF IT, no branch beside them. Still water is ONE knot,
 * so the nearest point is that knot and the clamp answers its level everywhere.
 * A straight river is TWO knots at the axis extremes, so the projection onto
 * the single segment IS the `clamp((s − s_min)/(s_max − s_min), 0, 1)` of W1 —
 * which is why the nine numbers are no longer read here at all: they say the
 * same thing, less well.
 */
export function waterLevelAt(profile: WaterProfile, x: number, z: number
): number {
  return axisLevelAt(profile.axis, nearestOnAxis(profile.axis, x, z)[0]);
}

/**
 * The DOWNSTREAM unit vector AT ONE POINT — the tangent of the nearest segment,
 * or (0, 0) for still water. The one piece of the profile the SHADER needs.
 *
 * IT IS LOCAL SINCE W4a, and that is the whole of the finding: a river bends,
 * so its ripples have to bend with it. `waterFlowAt` is evaluated per VERTEX
 * (`waterPlane.buildWaterPlane`), the interpolator carries it across the
 * triangles, and the drift turns through the meander instead of pointing one
 * way over a whole hairpin.
 *
 * The knots are already in FLOW order — the server reverses them for
 * `flow_along: "reverse"` — so `b − a` is downstream and no bearing is read.
 * A ONE-KNOT axis has no segment and answers (0, 0), which the ripple shader
 * spells "no flow, keep the lake's own crossing drift": today's look for every
 * still water, unchanged. So does a zero-length segment, which cannot name a
 * direction at all.
 */
export function waterFlowAt(profile: WaterProfile | null | undefined,
                            x: number, z: number): [number, number] {
  const axis = profile?.axis;
  if (!axis || axis.length < 2) return [0, 0];
  const seg = nearestOnAxis(axis, x, z)[1];
  const dx = axis[seg + 1][0] - axis[seg][0];
  const dz = axis[seg + 1][1] - axis[seg][1];
  const len = Math.hypot(dx, dz);
  if (!(len > 1e-9)) return [0, 0];
  return [dx / len, dz / len];
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
 * NO SUBDIVISION IS DONE, and for a STRAIGHT axis none is needed: the profile
 * is LINEAR in the plane by construction (a clamped linear ramp along one
 * axis), and the clamped part is linear too — flat. A ruled surface through the
 * outline's vertices therefore reproduces it exactly wherever the polygon is
 * convex, and where it is not, the earcut's own interior edges are the ruling.
 * The only places the interpolation could deviate are inside a triangle that
 * spans the clamp KINK at `s_min`/`s_max`, and there is none: those are the
 * polygon's own extremes, so no interior point of the polygon lies past them.
 *
 * A DRAWN AXIS (W4a) is piecewise linear, and so is what this writes: exact at
 * every vertex, and exact between them ONLY where the outline itself is cut at
 * the knots — which since W5c IT IS. `subdivideRibbonByAxis` splits the outline
 * at every interior knot before the earcut runs, so the mesh HAS a vertex row
 * wherever the mirror bends and the ruled surface between two rows is the
 * profile's own straight piece. Until then a two-click ribbon over a cliff had
 * four corners over 100 m: `waterLevelAt` was exact (the carve, the shore alpha,
 * the swimmer's float height, the waterfall detection all read it) while the
 * DRAWN surface ramped straight across the step — floating before the lip,
 * diving after it, with only the fall's own curtain (`scene/waterfall.ts`)
 * covering the seam.
 *
 * WHAT REMAINS is the WIDTH, and it is a different question: the cuts are
 * perpendicular cross-lines through the knots, so along a BENT axis a strip is
 * still one flat piece across its width while `waterLevelAt` bows with the
 * bend. The error is second order in the width (the sagitta of the bend over
 * half a ribbon) where it used to be first order in the LENGTH, and no water
 * this client draws is wide enough for it to be visible; a mask so wide that it
 * is would want cuts along the width too.
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

/** A world point on the ground plane, `[x, z]` in metres — the shape of a
 *  painted outline (`@anima/scene-render` `Point2`, spelled out rather than
 *  imported: this file has no runtime import and its smoke transpiles it
 *  alone). */
export type WaterPoint2 = [number, number];

/** Below this a clipped piece encloses nothing worth an earcut (m²) — the same
 *  `AREA_EPS_M2` a painted area is measured against. A strip this small is a
 *  sliver the clip produced where the outline merely grazes a cross-line, not a
 *  piece of water. */
const STRIP_EPS_M2 = 1e-9;

/** Shoelace of a ring, SIGNED — the local twin of `@anima/scene-render`
 *  `signedArea`, for the same reason `WaterPoint2` is spelled out here. */
function ringSignedArea(ring: readonly WaterPoint2[]): number {
  const n = ring.length;
  if (n < 3) return 0;
  let sum = 0;
  for (let i = 0; i < n; i += 1) {
    const [x0, z0] = ring[i];
    const [x1, z1] = ring[(i + 1) % n];
    sum += x0 * z1 - x1 * z0;
  }
  return sum / 2;
}

/**
 * The UNIT NORMAL of the cross-line through knot `i` — the direction "further
 * downstream", perpendicular to the axis where the axis is straight and to the
 * ANGLE BISECTOR where it bends.
 *
 * The bisector is the honest choice and it is the cheap one: the exact set of
 * points whose nearest axis point is the knot itself is a WEDGE, not a line, so
 * no single line is the true boundary between two segments' territories. The
 * bisector is the wedge's own axis of symmetry — it splits the disputed corner
 * evenly instead of leaning the cut into one of the two legs — and where the
 * two legs are collinear (every ribbon of a straight river, and every knot the
 * W5b densification inserted ON a drawn segment) the wedge collapses and the
 * bisector IS the perpendicular, exactly.
 *
 * `null` where no direction can be named: a zero-length leg, or two legs that
 * cancel — an axis that doubles back on itself in a point. Such a knot is
 * skipped, which costs a cut and never a triangle.
 */
function crossNormalAt(axis: WaterKnot[], i: number): WaterPoint2 | null {
  const [px, pz] = axis[i - 1];
  const [cx, cz] = axis[i];
  const [qx, qz] = axis[i + 1];
  const inLen = Math.hypot(cx - px, cz - pz);
  const outLen = Math.hypot(qx - cx, qz - cz);
  let nx = 0;
  let nz = 0;
  if (inLen > 1e-9) { nx += (cx - px) / inLen; nz += (cz - pz) / inLen; }
  if (outLen > 1e-9) { nx += (qx - cx) / outLen; nz += (qz - cz) / outLen; }
  const len = Math.hypot(nx, nz);
  if (!(len > 1e-9)) return null;
  return [nx / len, nz / len];
}

/**
 * One Sutherland–Hodgman pass: the part of `ring` on the `sign` side of the
 * line through `(cx, cz)` with normal `n`.
 *
 * `f(p) = (p − c) · n` is the signed distance to the line, so `sign > 0` keeps
 * what is downstream of the cross-line and `sign < 0` what is upstream. A
 * vertex within `1e-9` of the line counts as ON it and is kept by BOTH sides —
 * that is what makes the two passes give back the whole polygon and not two
 * pieces with a hairline missing between them.
 *
 * The rule is the textbook one, per edge `a → b`: emit `a` if it is kept, and
 * emit the crossing point whenever the edge really changes side (strictly, so a
 * vertex lying on the line never produces a duplicate of itself).
 */
function clipHalfPlane(ring: readonly WaterPoint2[], n: WaterPoint2,
                       cx: number, cz: number, sign: number): WaterPoint2[] {
  const out: WaterPoint2[] = [];
  const at = (p: WaterPoint2): number => {
    const f = ((p[0] - cx) * n[0] + (p[1] - cz) * n[1]) * sign;
    return Math.abs(f) < 1e-9 ? 0 : f;
  };
  for (let i = 0; i < ring.length; i += 1) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    const fa = at(a);
    const fb = at(b);
    if (fa >= 0) out.push([a[0], a[1]]);
    if ((fa > 0 && fb < 0) || (fa < 0 && fb > 0)) {
      const t = fa / (fa - fb);
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
  }
  return out;
}

/**
 * THE OUTLINE, CUT INTO STRIPS AT THE AXIS KNOTS (W5c) — the mesh's answer to
 * the cliff.
 *
 * WHY. The mirror is a RULED surface: the earcut lifts the outline's OWN
 * vertices onto the profile and interpolates linearly between them. That is
 * exact while the profile is one straight ramp — the whole world before W4a —
 * and it is exact for a lake, which is one constant. It is NOT exact for a
 * drawn river since W5b: the bake keeps a knot wherever the mirror bends, so a
 * two-click ribbon over a 3 m step has FOUR corners over 100 m and its surface
 * ramps straight from one end to the other. `waterLevelAt` reads 3.0 ten metres
 * before the lip and the drawn mesh reads 2.07 there; ten metres after it the
 * reader says 0.0 and the mesh stands 1.47 m in the air.
 *
 * THE RULE, and it is a partition and not a set of overlapping clips: walk the
 * INTERIOR knots in flow order carrying a REMAINDER, which starts as the whole
 * outline. At each knot, split the remainder by that knot's cross-line
 * (`crossNormalAt`) into the piece upstream of it — emitted as a strip — and
 * the piece downstream, which becomes the new remainder. What is left after the
 * last interior knot is the last strip. Splitting one polygon by one line
 * always gives back exactly that polygon, so the strips tile the outline
 * whatever the lines do to each other: no gap on the outside of a bend, no
 * double-drawn wedge on the inside, and the areas sum.
 *
 * Empty and sliver pieces (< `STRIP_EPS_M2`) are dropped, so a cross-line that
 * misses the polygon altogether — an axis that runs on past its mask — costs a
 * comparison and nothing else.
 *
 * FEWER THAN THREE KNOTS RETURNS THE OUTLINE ITSELF, the very array that came
 * in. A lake (one knot) and a polygon river (two) are the cases the ruled
 * surface already reproduced exactly, and the caller reads a single strip as
 * "keep the geometry you already have" — so those two draw the identical
 * buffers they drew before this function existed, not merely equal ones.
 */
export function subdivideRibbonByAxis(ring: readonly WaterPoint2[],
                                      axis: readonly WaterKnot[] | null
                                        | undefined
): WaterPoint2[][] {
  const inRing = ring as WaterPoint2[];
  if (!Array.isArray(ring) || ring.length < 3) return [inRing];
  if (!Array.isArray(axis) || axis.length < 3) return [inRing];
  const knots = axis as WaterKnot[];
  const strips: WaterPoint2[][] = [];
  let rest: WaterPoint2[] = inRing as WaterPoint2[];
  for (let i = 1; i < knots.length - 1; i += 1) {
    const n = crossNormalAt(knots, i);
    if (!n) continue;
    const [cx, cz] = knots[i];
    const upstream = clipHalfPlane(rest, n, cx, cz, -1);
    const downstream = clipHalfPlane(rest, n, cx, cz, 1);
    if (Math.abs(ringSignedArea(upstream)) >= STRIP_EPS_M2) {
      strips.push(upstream);
    }
    if (Math.abs(ringSignedArea(downstream)) < STRIP_EPS_M2) {
      rest = [];
      break;
    }
    rest = downstream;
  }
  if (Math.abs(ringSignedArea(rest)) >= STRIP_EPS_M2) strips.push(rest);
  // Nothing survived the clips — a ring so thin that every piece is a sliver.
  // The untouched outline is what it drew before, and the caller's own earcut
  // is the one thing that gets to call it empty.
  return strips.length ? strips : [inRing];
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
 * `vWaterOpaque` IS THE SECOND THING THE GEOMETRY CARRIES (W4b): the metres of
 * depth at which THIS water is fully drawn, ¾ of its own bed depth
 * (`waterOpaqueDepthM`), written into every vertex as `aWaterOpaque`. It used
 * to be the uniform `uShoreBandM` holding the one constant 1.5 m — the ¾ of the
 * DEFAULT lake — which is why a 6 m river with two 1 m banks stayed
 * see-through to its middle: it never reached a depth the lake's number called
 * opaque. An attribute and not a uniform for the reason the flow already is
 * one: it belongs to the AREA while the material belongs to the KIND, and one
 * material has to serve every lake and river of that kind.
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
varying float vWaterOpaque;
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
    diffuseColor.a *= clamp( wsSmooth( wsDepth / vWaterOpaque )
                             + wsFoam * uFoamAlpha, 0.0, 1.0 )
                    * clamp( wsDepth / wsEdge, 0.0, 1.0 );
  }
`;
}
