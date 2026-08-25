/**
 * THE WATER PROFILE AND THE SHORE, as arithmetic — the numbers every reader of
 * a painted water shares ("Ein Boden" E4, § G4; the polyline of W4a).
 *
 * WHO ASKS. Two kinds of reader, and they are not the same question:
 *   - THE RENDER asks the water RASTER (`waterRaster.ts`, K-A E1/E2), and the
 *     terrain shades its own water pixels with the shore curves below
 *     (`waterShade.ts`, K-A E4) — the alpha ramp, the foam band, the rim fade.
 *   - THE GAME asks the PROFILE, exactly (`waterLevelAt`): where a figure
 *     floats, wades or swims (`game/walk.ts`, `floatRootY`), which level a
 *     point of the world carries (`ground.typeAt`), and where a river's own
 *     line drops fast enough to be a waterfall (`@anima/scene-render`
 *     `waterfallsFrom`, over `profile.axis`).
 * The two agree by construction: the server's raster IS `water_level_at`
 * evaluated on the height lattice.
 *
 * Import-free on purpose, exactly like `naturalGroundMath.ts` next to
 * `naturalGround.ts` and `@anima/scene-render` `layerCut.ts` next to
 * `layerGround.ts`: `client3d/scripts/smoke_water_plane.mjs` transpiles this
 * file and checks every number below by hand.
 *
 * THE SHORE COMES OUT OF THE HEIGHT DATA, not out of a depth pass: the water
 * depth under a pixel is `level − h(x, z)`, a number in METRES, in our own
 * data, identical near and far. A screen-space depth texture would have been a
 * second render target, a second copy of the ground and a shore that changes
 * width with the camera's near/far planes; this one is a subtraction.
 *
 * WHAT LEFT WITH K-A E5. Until then a painted water also carried a MESH — a
 * ruled surface over its outline, cut at the axis knots, every vertex lifted to
 * `waterLevelAt` and a shader chunk of its own for the shore. The terrain
 * itself lifts and shades those pixels since E3/E4, so the mesh, its strip
 * subdivision (`subdivideRibbonByAxis`), its lift (`liftToWaterProfile`), its
 * per-vertex flow (`waterFlowAt` — the server bakes the flow into the raster
 * now) and its GLSL are deleted. What stayed is what has a reader above.
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
 *
 * SINCE 2026-08-25 THE FRACTION HAS A FLOOR UNDER IT
 * ({@link WATER_MIN_SEE_DEPTH_M}): the answer is `max(1 m, ¾ · depth)`, so a
 * water shallower than 4/3 m keeps a readable bed to the metre mark whatever
 * its own ramp does. The fraction still decides every water deeper than that.
 */
const WATER_OPAQUE_FRACTION = 0.75;

/**
 * HOW DEEP A WATER HAS TO BE BEFORE IT MAY HIDE ITS BED AT ALL, in metres —
 * the FLOOR under the fraction above (user rule, 2026-08-25: "the bed must stay
 * visible down to at least a metre of depth").
 *
 * ── WHY A FLOOR AND NOT A SMALLER FRACTION ──────────────────────────────────
 * The fraction is a statement about the SHORE RAMP: ¾ of the bed is reached at
 * the same fraction of whatever ramp the author drew, which is what makes a
 * pond and a lake fade in over the same share of their own bank (see
 * {@link WATER_OPAQUE_FRACTION}). Lowering it would move that ramp for EVERY
 * water, deep ones included, and the deep ones are not the complaint — a lake
 * that goes opaque at 1.5 m reads right. What is wrong is the SHALLOW end: a
 * river 1.2 m deep went opaque at 0.9 m, i.e. its bed was gone before a wading
 * figure's waist, and its whole navigable middle was flat tint. A floor fixes
 * exactly that case and leaves every water deeper than 4/3 m untouched.
 *
 * ── WHAT IT MOVES, AND WHAT IT DOES NOT ─────────────────────────────────────
 *     bed  1.2 m (the seeded river)  ->  ¾ = 0.9   -> FLOORED to 1.0
 *     bed  1.0 m                     ->  ¾ = 0.75  -> FLOORED to 1.0
 *     bed  0.6 m (a pond)            ->  ¾ = 0.45  -> FLOORED to 1.0
 *     bed  4/3 m (the break-even)    ->  ¾ = 1.0   -> 1.0, either rule
 *     bed  2.0 m (the default lake)  ->  ¾ = 1.5   -> unchanged
 *     bed  4.0 m                     ->  ¾ = 3.0   -> unchanged
 *
 * A water shallower than the floor therefore NEVER reaches full absorption: a
 * 0.6 m pond tops out at `smoothstep(0.6 / 1.0)` = 0.648, so 35.2 % of its bed
 * is still readable at its deepest point. That is the rule as decided — a
 * shallow water is one you can see the bottom of — and not an oversight.
 */
export const WATER_MIN_SEE_DEPTH_M = 1.0;

/**
 * How deep THIS water has to be before it is fully drawn, in metres (W4b, with
 * the see-through floor of 2026-08-25).
 *
 * `depthM` is the area's effective bed depth as the payload ships it
 * (`meta.water_depth_effective`, § A16.3 — the kind's default with the area's
 * override already applied, so this side never repeats that resolution). A
 * value that is not a positive finite number is not a depth: the default lake
 * answers instead, which is what every water looked like before W4b.
 *
 * `max(WATER_MIN_SEE_DEPTH_M, ¾ · depth)` — ONE home for the number, read by
 * the look table (`waterShade.waterLookFrom`, which packs it into the lookup
 * texture the fragment fetches) and by every smoke. Nothing else may spell the
 * fraction or the floor.
 */
export function waterOpaqueDepthM(depthM: unknown): number {
  const raw = Number(depthM);
  const depth = Number.isFinite(raw) && raw > 0 ? raw : WATER_DEPTH_DEFAULT_M;
  return Math.max(WATER_MIN_SEE_DEPTH_M, depth * WATER_OPAQUE_FRACTION);
}

/** How deep the foam reaches, in metres. Half a metre is roughly where a
 *  wading figure's shin is (`move_sink_m` of the water kinds is a knee), so the
 *  white lace ends where the ground stops being walked and starts being swum. */
export const WATER_FOAM_BAND_M = 0.6;

/** How far the foam whitens the outgoing light at the very rim (0…1). Read as
 *  a fraction of the way to white, and it is deliberately partial: foam is
 *  broken water, not paint. */
export const WATER_FOAM_STRENGTH = 0.6;

/** `smoothstep(0, 1, t)` on a clamped t — the one easing curve of this file,
 *  written out so the smoke can check the GLSL twin against it. */
function smoothstep01(t: number): number {
  const c = t <= 0 ? 0 : t >= 1 ? 1 : t;
  return c * c * (3 - 2 * c);
}

/**
 * How much of the water is drawn over a bed `depthM` under the water line,
 * 0…1, for a water that is fully drawn at `opaqueDepthM` (W4b).
 *
 * Read by the terrain's water shading as the ABSORPTION (K-A E4,
 * `waterShade.ts`): 0 is the bare bed, 1 is water one cannot see the bed
 * through. `depthM ≤ 0` is not water at all — the bed is at or above the water
 * line, which happens outside the carved outline and nowhere inside it (the E1
 * invariant), and there the pixel stays the dry ground it is.
 *
 * THE BAND IS A PARAMETER, not a constant any more: it is ¾ of the AREA's own
 * bed depth (`waterOpaqueDepthM`). Hand values
 * for the default lake (depth 2.0 -> band 1.5), `t = depth / 1.5`, `3t² − 2t³`:
 *
 *     0.0   -> t = 0        -> 0            (bare bed, see above)
 *     0.15  -> t = 0.1      -> 0.028
 *     0.30  -> t = 0.2      -> 0.104
 *     0.375 -> t = 0.25     -> 0.15625
 *     0.75  -> t = 0.5      -> 0.5
 *     1.125 -> t = 0.75     -> 0.84375
 *     1.5   -> t = 1        -> 1
 *     2.0   -> clamped      -> 1
 *
 * …and for the seeded river (depth 1.2 -> ¾ = 0.9, FLOORED to the 1.0 m of
 * {@link WATER_MIN_SEE_DEPTH_M}), the same six fractions of that band:
 *
 *     0.1   -> t = 0.1      -> 0.028
 *     0.2   -> t = 0.2      -> 0.104
 *     0.25  -> t = 0.25     -> 0.15625
 *     0.5   -> t = 0.5      -> 0.5
 *     0.75  -> t = 0.75     -> 0.84375
 *     1.0   -> t = 1        -> 1
 *
 * — the floor is worth 1/9 of a metre of readable bed at the deep end and, at
 * the 0.5 m a wading figure stands in, 0.5 against the 0.58299 the ¾ rule gave:
 * half the bed instead of 41.7 % of it.
 */
export function waterShoreAlpha(depthM: number, opaqueDepthM: number): number {
  if (!Number.isFinite(depthM) || depthM <= 0) return 0;
  return smoothstep01(depthM / opaqueDepthM);
}

/**
 * How much foam sits over a bed `depthM` under the water line, 0…1 — full at the
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
 * One knot of the flow axis: `[x, z, s, level]` — the world position, the arc
 * length from the FIRST knot, and the water level there
 * (`heightfield.WaterKnot`, § A16.3).
 */
export type WaterKnot = [number, number, number, number];

/**
 * THE LEVEL OF ONE WATER AREA AS A FUNCTION OF THE PLACE —
 * `meta.water_profile` (W1, polyline since W4a, § A16.3), read straight out of
 * the payload.
 *
 * THE TRUTH IS `axis`, the knots. A lake is ONE knot, a straight river TWO, a
 * river drawn with the line tool one wherever its level BENDS (W5b: the bake
 * samples that line every 2 m and simplifies the levels back down, so the knots
 * are the ground's bends and not the author's clicks) — the old laws are the
 * degenerate cases of the new one and `waterLevelAt` is one code path for all
 * three. A meander is why: projected onto a single straight axis, the two ends
 * of a 180° loop land on the same axis point, so the level of a bend could not
 * fall at all.
 *
 * The nine numbers beside it are the same water as ONE TILTED PLANE — what a
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
 *  missing level becomes a water line at world zero — never here. */
function finite(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

/**
 * The knots of `raw`, or `null` where they are not a usable axis (W4a).
 *
 * A list of at least one quadruple of finite numbers, and nothing else. The
 * axis is what the whole water level is evaluated on since W4a, so a payload
 * whose axis is broken has NO water — the same rule the nine numbers already
 * followed, for the same reason: one NaN and every reader of that area, the
 * terrain's own lift included, is poisoned.
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
 * the bake carved the bed against, shipped as nine numbers so a reader answers
 * the same level without asking for a raster. Reading it is the WHOLE water
 * test — an area that has one is an area whose bed was carved, an area without
 * one holds no water. This is the ONE water source of the client: the surface
 * material CLASS says what water looks like, never whether a thing is water
 * (that book is the server's single `is_water_kind`).
 *
 * The authored `meta.water_level` is deliberately NOT read (it may be unset),
 * and neither is `meta.water_level_effective` any more: that field is the MID
 * level of the profile, i.e. what a FLAT consumer draws one plane at, and this
 * client stopped being one in W2. A river read at its mid level stands 2.4 m
 * over its own bed at one end and 2.4 m under it at the other.
 *
 * Every one of the nine has to be a finite number, `flow_dir_deg` excepted —
 * `null` there is the shape of still water — AND SO DOES EVERY KNOT of the
 * `axis` (W4a), which is the part this client actually evaluates. One NaN
 * spreads through every height it touches, so a broken profile is no water at
 * all.
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
 * The ARC COORDINATE of the nearest point on the axis — the twin of
 * `heightfield._axis_s_at`.
 *
 * Every segment is projected onto WITH A CLAMP to its own ends, and the
 * shortest distance wins; the answer is that segment's `s` interpolated by the
 * projection. The candidate the loop starts from is the FIRST KNOT — the whole
 * answer for a one-knot (still) axis, and dominated by the first segment for
 * every longer one.
 *
 * THE COMPARISON IS STRICT (`<`), exactly as on the server, and that decides
 * the ties: a point sitting ON a knot is at distance 0 from both of its legs,
 * and the earlier — the UPSTREAM — leg keeps it, which answers that knot's own
 * arc coordinate either way.
 */
function nearestOnAxis(axis: WaterKnot[], x: number, z: number): number {
  let bestS = axis[0][2];
  let bestD2 = (x - axis[0][0]) * (x - axis[0][0])
             + (z - axis[0][1]) * (z - axis[0][1]);
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
    }
  }
  return bestS;
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
 * THE WATER LEVEL AT ONE POINT — the pure TS twin of
 * `heightfield.water_level_at`,
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
  return axisLevelAt(profile.axis, nearestOnAxis(profile.axis, x, z));
}

/**
 * How wide the last hand's width of water is, in metres of DEPTH — the band the
 * alpha is faded to nothing over so the rim is not a hard edge.
 *
 * IT IS DERIVED FROM THE FOAM, not tasted. The foam is full at depth 0 and
 * whitens the light by 0.6 there, so without a ramp the rim would STEP from
 * that white lace to dry ground across a boundary with no width — and a
 * boundary with no width crawls sub-pixel as the camera moves. It was the
 * mirror's `discard` edge until K-A E5 and it is the waterline of the terrain's
 * own shading now; the same 5 cm of depth ramps both of them to nothing, and
 * the ramp is anti-aliased by the raster itself.
 *
 * 5 cm of DEPTH is about 7.5 cm of ground on the default shore
 * (`water_depth_m` 2.0 over `shore_ramp_m` 3.0 is a slope of 2/3 at the rim),
 * i.e. a twentieth of the 1.5 m the shore ramp already spends — it moves the
 * waterline by less than the foam lace is wide.
 */
export const WATER_EDGE_FADE_M = 0.05;

/**
 * The rim fade a water fragment carries: `clamp(depth / edge, 0, 1)`, where
 * `edge` is one pixel measured in metres of DEPTH (`fwidth` of the depth in the
 * shader), floored at `WATER_EDGE_FADE_M`.
 *
 * It is the ONE factor that reaches exactly 0 at the waterline, which is the
 * whole job — the foam alone would otherwise be a step there.
 *
 *     depth 0        -> 0                (dry ground, approached smoothly)
 *     depth ½·edge   -> 0.5
 *     depth ≥ edge   -> 1                (the shore ramp alone from here on)
 */
export function waterEdgeFade(depthM: number, edgeM: number): number {
  const e = Math.max(edgeM, WATER_EDGE_FADE_M);
  if (!Number.isFinite(depthM) || depthM <= 0) return 0;
  const t = depthM / e;
  return t >= 1 ? 1 : t;
}
