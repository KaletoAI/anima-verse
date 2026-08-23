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
 * 100 m ramp of slope 0.03 and no rule here could ever have seen a fall — and
 * it is also what keeps one fall ONE fall: the simplification hands this
 * function one segment per bend rather than one per sample, so a drop is not
 * split into a stack of curtains each carrying a fraction of it.
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
 * `x`/`z` is the MIDPOINT of the falling segment (the lip is one end and the
 * pool the other; the middle is the one point that is on the fall whichever way
 * the renderer leans its sheet), `dirX`/`dirZ` the unit DOWNSTREAM direction of
 * that segment, `width` the river's own width, and `topY`/`bottomY` the mirror
 * levels of the two knots — the height the water leaves at and the height it
 * arrives at.
 */
export interface Waterfall {
  x: number
  z: number
  dirX: number
  dirZ: number
  width: number
  topY: number
  bottomY: number
}

/**
 * How far the mirror has to drop over ONE segment before that segment is a
 * fall, in metres.
 *
 * 1.0 m is `swim_from_m`'s own default (W4c): the depth at which this world
 * stops walking a figure and starts swimming it, i.e. the smallest height of
 * water it already treats as more than a step. Below it a "fall" would be a
 * curtain shorter than the water it joins — the ruled mirror draws that as a
 * short steep ramp and the shore alpha covers it, which is what a rapid looks
 * like and what it should stay.
 *
 * IT IS ONE OF TWO CONDITIONS, never alone: a bed that loses 4 m over 200 m of
 * river passes this one and is a valley, not a fall.
 */
export const WATERFALL_MIN_DROP_M = 1.0

/**
 * How STEEP that drop has to be — metres of fall per metre of run along the
 * axis.
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
 * THE FALLS OF ONE WATER AREA — every axis segment that drops faster than water
 * runs, in flow order.
 *
 * The rule, per consecutive pair of knots `a -> b` (b is downstream, the knots
 * are in flow order and the bake has already made the levels non-increasing):
 *
 *     drop  = a.level − b.level          metres lost
 *     run   = b.s − a.s                  metres of axis spent
 *     fall  <=>  drop > 1.0  AND  drop / run > 0.5
 *
 * BOTH, and both STRICTLY — a value sitting exactly on a threshold is not past
 * it, so the two constants name the smallest thing that is NOT a fall and the
 * numbers in the smoke can be read straight off them.
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
 * A zero-length segment names no direction and is skipped (its `run` is 0, so
 * the slope test would divide by zero); so is a segment that RISES, which the
 * bake's monotonicity rules out but a hand-written fixture does not.
 */
export function waterfallsFrom(profile: WaterfallAxis | null | undefined,
                               widthM: unknown): Waterfall[] {
  const axis = profile?.axis
  const width = finite(widthM)
  if (!Array.isArray(axis) || axis.length < 3) return []
  if (width === null || width <= 0) return []
  const falls: Waterfall[] = []
  for (let i = 1; i < axis.length; i += 1) {
    const a = axis[i - 1]
    const b = axis[i]
    if (!Array.isArray(a) || !Array.isArray(b)) return []
    const ax = finite(a[0])
    const az = finite(a[1])
    const aS = finite(a[2])
    const aLevel = finite(a[3])
    const bx = finite(b[0])
    const bz = finite(b[1])
    const bS = finite(b[2])
    const bLevel = finite(b[3])
    if (ax === null || az === null || aS === null || aLevel === null
        || bx === null || bz === null || bS === null || bLevel === null) {
      return []
    }
    const drop = aLevel - bLevel
    const run = bS - aS
    if (!(drop > WATERFALL_MIN_DROP_M)) continue
    if (!(run > 0)) continue
    if (!(drop / run > WATERFALL_MIN_SLOPE)) continue
    // The downstream direction of THIS segment, from the world positions and
    // not from the profile's area-wide `dir_x`/`dir_z`: a drawn river bends,
    // and a curtain across the wrong bearing is a curtain along the stream.
    const dx = bx - ax
    const dz = bz - az
    const len = Math.hypot(dx, dz)
    if (!(len > 1e-9)) continue
    falls.push({
      x: (ax + bx) * 0.5,
      z: (az + bz) * 0.5,
      dirX: dx / len,
      dirZ: dz / len,
      width,
      topY: aLevel,
      bottomY: bLevel,
    })
  }
  return falls
}
