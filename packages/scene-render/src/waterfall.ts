/**
 * WHERE A RIVER FALLS — the waterfalls of one water area, read out of the axis
 * the mirror is already built on ("Ein Wasser-Gesetz" W5).
 *
 * NO NEW AUTHORSHIP, and that is the whole design. A river drawn with the line
 * tool ships its own centre line as `meta.water_profile.axis` (W4a): knots
 * along that line, each carrying the arc coordinate `s` and the level of the
 * mirror there, already made monotonically falling downstream by the bake. A
 * waterfall is therefore not a thing an author places — it is a SEGMENT of that
 * line whose level falls faster than water runs, and it can be read off the
 * payload every renderer already has.
 *
 * THE KNOTS ARE NOT THE CLICKS (W5b). The bake samples the drawn line every
 * `WATER_AXIS_STEP_M` (2 m), measures a level at every sample and then
 * simplifies the level polyline back down, so a knot survives exactly where the
 * mirror BENDS. That is what puts knots on both sides of a cliff the author
 * drew straight across — before it, a two-click river over a 3 m step was one
 * 100 m ramp of slope 0.03 and no rule here could ever have seen a fall.
 *
 * BUT THE KNOTS ARE NOT THE FALL EITHER, and that is why the drop is measured
 * over a RUN of segments rather than over one: a click the author happened to
 * place halfway down the cliff survives the simplification (it is a bend of the
 * drawn LINE, never dropped), and it used to cut one 3 m drop into two 1.5 m
 * ones — neither past the metre a fall has to lose, so the waterfall vanished
 * where somebody had clicked in it. The rule therefore joins every maximal run
 * of consecutive STEEP segments first and asks about the drop of the run.
 *
 * IT IS A PURE FUNCTION and it lives here, beside `materials.ts`'s water dials,
 * for the reason the whole package exists: the 3D client draws the curtain
 * today and the admin map may want a marker tomorrow (W6), and "which segment
 * is a fall" must not be answered twice with two sets of thresholds. Nothing in
 * this file touches three — it is arithmetic on four numbers per knot.
 *
 * The 3D half is `client3d/src/scene/waterfall.ts`; the hand-derived numbers
 * are `client3d/scripts/smoke_waterfall.mjs`.
 */

/**
 * One knot of the flow axis: `[x, z, s, level]` — world position, arc length
 * from the FIRST knot, and the mirror height there.
 *
 * Structurally the `WaterKnot` of `client3d/src/scene/waterPlaneMath.ts` and
 * the `heightfield.WaterKnot` of the server; written out rather than imported
 * because this package must not depend on either app.
 */
export type WaterfallKnot = [number, number, number, number]

/** As much of `meta.water_profile` as a fall is read from: the knots. Every
 *  other field of the profile describes the tilted PLANE a flat consumer draws
 *  and says nothing about where the line is steep. */
export interface WaterfallAxis {
  axis: WaterfallKnot[]
}

/**
 * ONE FALL, in world metres — everything a renderer needs to hang a curtain,
 * and nothing about how it looks.
 *
 * `x`/`z` is the MIDPOINT of the falling run BY ARC LENGTH (the lip is one end
 * and the pool the other; the middle is the one point that is on the fall
 * whichever way the renderer leans its sheet) — by arc and not by chord,
 * because a run of several segments may bend and the chord's middle would then
 * hang beside the water rather than in it. `dirX`/`dirZ` is the unit DOWNSTREAM
 * direction of the run, its CHORD: over a bent fall no single segment's bearing
 * is the fall's, and the straight line from lip to pool is. `width` is the
 * river's own width, and `topY`/`bottomY` the mirror levels of the run's first
 * and last knot — the height the water leaves at and the height it arrives at.
 *
 * `chordM` IS THAT STRAIGHT LINE'S LENGTH, and it is what tells a renderer HOW
 * STEEP the fall stands on the ground. Under Wasser v2 K-A the water surface IS
 * the terrain (`client3d/src/scene/waterShade.ts`), so the mirror between lip
 * and pool is drawn as a steep, opaque, WET FACE running exactly `chordM`
 * metres from `x ∓ dir · chordM/2`. A curtain hung over a shorter run than that
 * is buried in its own waterfall for the whole lower half of its height — the
 * measured symptom of 2026-08-24, "the fall has the waterfall texture only at
 * the top". The renderer needs the number to lean the sheet clear of the face,
 * and it can be had for nothing here: the chord is already computed to get the
 * direction.
 */
export interface Waterfall {
  x: number
  z: number
  dirX: number
  dirZ: number
  width: number
  topY: number
  bottomY: number
  chordM: number
}

/**
 * How far the mirror has to drop over one steep RUN before that run is a fall,
 * in metres.
 *
 * 1.0 m is `swim_from_m`'s own default (W4c): the depth at which this world
 * stops walking a figure and starts swimming it, i.e. the smallest height of
 * water it already treats as more than a step. Below it a "fall" would be a
 * curtain shorter than the water it joins — the ruled mirror draws that as a
 * short steep ramp and the shore alpha covers it, which is what a rapid looks
 * like and what it should stay.
 *
 * IT IS ONE OF TWO CONDITIONS, never alone: a bed that loses 4 m over 200 m of
 * river passes this one and is a valley, not a fall. And it is asked of the
 * whole RUN, once — see `waterfallsFrom`.
 */
export const WATERFALL_MIN_DROP_M = 1.0

/**
 * How STEEP that drop has to be — metres of fall per metre of run along the
 * axis.
 *
 * IT IS THE PER-SEGMENT CONDITION, and the only one: a segment is steep or it
 * is not, and steepness is what joins neighbours into one fall.
 *
 * 0.5 is a 1-in-2 slope, 26.6°. A river bed the bake carves runs at a small
 * fraction of that (the seeded river loses 1.2 m of depth over its whole 6 m
 * width, and along its LENGTH a natural course is flatter again by orders of
 * magnitude), and 26.6° is already past where loose material stops lying still
 * — a bed that steep is scree, and water on it is falling rather than flowing.
 *
 * IT IS THE SECOND OF TWO CONDITIONS, never alone: a 20 cm step over 30 cm of
 * run is steeper than this and is a stone in the stream.
 */
export const WATERFALL_MIN_SLOPE = 0.5

/** The one numeric reader: a value that is not a finite number is not a number.
 *  `Number(null)` IS 0 and `Number('')` IS 0, which is how a missing width
 *  becomes a curtain of nothing — never here. */
function finite(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null
  const num = Number(raw)
  return Number.isFinite(num) ? num : null
}

/**
 * The ribbon width of an area drawn with the LINE tool, in metres, or `null`.
 *
 * `meta.stroke` is the recipe the editor regenerates the polygon from
 * (`app/models/terrain._sanitize_stroke`), and `width_m` is required in it, so
 * every drawn river has one. A polygon area has no recipe at all and answers
 * `null` — which is the same answer the fall detection gives it anyway, for the
 * same reason: it has no drawn line.
 */
export function strokeWidthM(meta: Record<string, unknown> | null | undefined
): number | null {
  const stroke = meta?.stroke
  if (!stroke || typeof stroke !== 'object') return null
  const width = finite((stroke as Record<string, unknown>).width_m)
  return width !== null && width > 0 ? width : null
}

/**
 * THE FALLS OF ONE WATER AREA — every stretch of axis that drops faster than
 * water runs, in flow order.
 *
 * TWO STEPS, and the order between them IS the rule. First, per consecutive
 * pair of knots `a -> b` (b is downstream, the knots are in flow order and the
 * bake has already made the levels non-increasing):
 *
 *     drop  = a.level − b.level          metres lost
 *     run   = b.s − a.s                  metres of axis spent
 *     steep <=>  run > 0  AND  drop / run > 0.5
 *
 * Then every MAXIMAL RUN of consecutive steep segments is one candidate, and
 * only the candidate is asked for its height:
 *
 *     fall  <=>  first.level − last.level > 1.0
 *
 * THE MINIMUM DROP BELONGS TO THE RUN, NOT TO THE SEGMENT, and that is the
 * whole reason for the two steps. A knot inside a cliff — an author's click
 * halfway down it, which the simplification keeps because it is a bend of the
 * LINE — splits one drop into two, and asking each half for a full metre made
 * a 3 m fall disappear the moment somebody clicked in the middle of it. The
 * slope survives that split (it is a ratio and does not care where the cut
 * is), so the slope is what runs are built from and the drop is measured once,
 * over the whole run. The merged run is steep by construction: a weighted mean
 * of slopes each past 0.5 is past 0.5.
 *
 * BOTH CONDITIONS STILL HOLD, and both STRICTLY — a value sitting exactly on a
 * threshold is not past it, so the two constants name the smallest thing that
 * is NOT a fall and the numbers in the smoke can be read straight off them.
 *
 * A RUN OF ONE SEGMENT IS THE OLD RULE, unchanged down to the arithmetic: its
 * drop is that segment's drop, its chord that segment, its arc midpoint the
 * mean of its two ends.
 *
 * THREE KNOTS AT LEAST. A polygon river's axis is the two extremes of one
 * straight ramp (`heightfield.water_profile_for`): its single segment IS the
 * whole river, so calling it a fall would drop a curtain across the entire
 * length of the water. Only a line-drawn river has interior knots — the bake
 * puts them where its mirror bends (W5b), which is exactly where "this stretch
 * is steeper than the rest" means anything. A drawn river whose level falls
 * evenly simplifies back to its two ends and is one ramp again, correctly: a
 * mirror with no bend in it has no fall in it. A lake is one knot and has no
 * segment at all.
 *
 * `widthM` is the river's ribbon width (`strokeWidthM`); a width that is not a
 * positive finite number gives NO falls — a curtain has to span the stream, and
 * a stream of unknown width has no curtain. In practice the two conditions meet
 * or neither does: the axes with interior knots are exactly the drawn ones, and
 * a drawn area always carries `width_m`.
 *
 * A zero-length segment is not steep and therefore ENDS a run (its `run` is 0,
 * so the slope test would divide by zero); so does a segment that RISES, which
 * the bake's monotonicity rules out but a hand-written fixture does not. A knot
 * that is not four finite numbers makes the whole axis unreadable and the
 * answer empty — half a river is worse than none.
 */
export function waterfallsFrom(profile: WaterfallAxis | null | undefined,
                               widthM: unknown): Waterfall[] {
  const axis = profile?.axis
  const width = finite(widthM)
  if (!Array.isArray(axis) || axis.length < 3) return []
  if (width === null || width <= 0) return []
  // The whole axis is read FIRST, because a run spans several knots and a rule
  // that groups them cannot re-read a pair at a time.
  const knots: AxisKnot[] = []
  for (const raw of axis) {
    if (!Array.isArray(raw)) return []
    const x = finite(raw[0])
    const z = finite(raw[1])
    const s = finite(raw[2])
    const level = finite(raw[3])
    if (x === null || z === null || s === null || level === null) return []
    knots.push({ x, z, s, level })
  }
  const falls: Waterfall[] = []
  const close = (lo: number, hi: number): void => {
    const fall = runToFall(knots, lo, hi, width)
    if (fall !== null) falls.push(fall)
  }
  // Maximal runs of consecutive steep segments, in flow order. `start` is the
  // first KNOT of the open run, or −1 while none is open.
  let start = -1
  for (let i = 1; i < knots.length; i += 1) {
    if (isSteep(knots[i - 1], knots[i])) {
      if (start < 0) start = i - 1
      continue
    }
    if (start >= 0) close(start, i - 1)
    start = -1
  }
  if (start >= 0) close(start, knots.length - 1)
  return falls
}

/** One knot, read out of the payload's four numbers once. */
interface AxisKnot {
  x: number
  z: number
  s: number
  level: number
}

/** Does the water FALL over this one segment rather than run down it —
 *  `WATERFALL_MIN_SLOPE`, and nothing about how far it falls. */
function isSteep(a: AxisKnot, b: AxisKnot): boolean {
  const run = b.s - a.s
  if (!(run > 0)) return false
  return (a.level - b.level) / run > WATERFALL_MIN_SLOPE
}

/** One maximal steep run `lo -> hi` (knot indices) as a fall, or `null` when
 *  it does not lose enough height to be one. */
function runToFall(knots: AxisKnot[], lo: number, hi: number,
                   width: number): Waterfall | null {
  const top = knots[lo]
  const bottom = knots[hi]
  if (!(top.level - bottom.level > WATERFALL_MIN_DROP_M)) return null
  // The downstream direction of THIS run, from the world positions and not
  // from the profile's area-wide `dir_x`/`dir_z`: a drawn river bends, and a
  // curtain across the wrong bearing is a curtain along the stream.
  const dx = bottom.x - top.x
  const dz = bottom.z - top.z
  const len = Math.hypot(dx, dz)
  if (!(len > 1e-9)) return null
  const [x, z] = arcMidpoint(knots, lo, hi)
  return { x, z, dirX: dx / len, dirZ: dz / len, width,
    topY: top.level, bottomY: bottom.level, chordM: len }
}

/**
 * The point halfway along the run BY ARC LENGTH — on the axis, never beside it.
 *
 * A single segment answers the plain mean of its two ends, which is what this
 * rule has always shipped and what the smoke's numbers are written against; a
 * longer run walks its own `s` to the half and interpolates inside the segment
 * that contains it. `s` grows strictly along a steep run (every one of its
 * segments has `run > 0`), so that segment always exists.
 */
function arcMidpoint(knots: AxisKnot[], lo: number,
                     hi: number): [number, number] {
  const a0 = knots[lo]
  const b0 = knots[hi]
  if (hi - lo === 1) return [(a0.x + b0.x) * 0.5, (a0.z + b0.z) * 0.5]
  const sMid = (a0.s + b0.s) * 0.5
  let i = lo + 1
  while (i < hi && knots[i].s < sMid) i += 1
  const a = knots[i - 1]
  const b = knots[i]
  const span = b.s - a.s
  const u = span > 1e-9 ? (sMid - a.s) / span : 0
  return [a.x + (b.x - a.x) * u, a.z + (b.z - a.z) * u]
}
