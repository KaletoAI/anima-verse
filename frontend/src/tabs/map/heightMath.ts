/**
 * heightMath — the authoring arithmetic of the world relief (§ A16).
 *
 * One question, asked in two places (the layer draws a warning glyph, the chip
 * writes the sentence): is this ramp steeper than a walker can climb?
 *
 * The server judges every reported step with TWO limits (§ A15 Nr. 8,
 * `app/core/relief.slope_blocks`) and both travel in the worldmap payload:
 *
 *   * `max_slope_deg` — the SLOPE, over every distance;
 *   * `max_step_height_m` — the STEP, on top of it, below one metre of
 *     horizontal travel (`relief.STEP_DISTANCE_M`).
 *
 * A height area's ramp has a CONSTANT gradient — it climbs the full height
 * over exactly `falloff_m` metres — so both limits become one number here:
 *
 *     gradient = |height_m| / falloff_m
 *     walkable while gradient <= min(tan(max_slope_deg),
 *                                    max_step_height_m / 1 m)
 *
 * THE STEP LIMIT IS USUALLY THE BINDING ONE, and leaving it out was a real
 * hole (review 2026-08-13): at the defaults it allows 0.4 m per metre against
 * the slope limit's tan 40° = 0.84, so a 5 m rise over 8 m passed as "walkable"
 * here while the server refused every report shorter than a metre — a figure
 * snapping back intermittently on a ramp the editor called fine. Short reports
 * are not exotic: they are what a walker sends when it stops, slides along an
 * obstacle or turns.
 *
 * IT IS A WARNING, NEVER A REFUSAL. A cliff is a legitimate thing to build (a
 * plateau one reaches through an opening, a ravine one is meant to walk
 * around); what is not legitimate is building one by accident.
 */

/** Below this horizontal distance a height change counts as a STEP — the
 *  mirror of `app/core/relief.STEP_DISTANCE_M` (and of `walk.ts`). */
export const STEP_DISTANCE_M = 1

/** The steepest gradient (metres of rise per metre of ground) a walker takes,
 *  from the two limits together. 0 when neither says anything usable. */
export function maxGradient(maxSlopeDeg: number, maxStepM: number): number {
  const bySlope = (Number.isFinite(maxSlopeDeg) && maxSlopeDeg > 0
    && maxSlopeDeg < 90)
    ? Math.tan((maxSlopeDeg * Math.PI) / 180)
    : Infinity
  const byStep = (Number.isFinite(maxStepM) && maxStepM > 0)
    ? maxStepM / STEP_DISTANCE_M
    : Infinity
  const g = Math.min(bySlope, byStep)
  return Number.isFinite(g) ? g : 0
}

/** The narrowest ramp this height may have and still be walkable, in metres.
 *  0 when nothing can be said (a flat area, or unusable limits). */
export function minFalloffFor(heightM: number, maxSlopeDeg: number,
  maxStepM: number): number {
  const h = Math.abs(heightM)
  if (!Number.isFinite(h) || h <= 0) return 0
  const g = maxGradient(maxSlopeDeg, maxStepM)
  if (!g) return 0
  return Math.round((h / g) * 100) / 100
}

/**
 * IS THE WORLD'S RELIEF GRID COARSER THAN NORMAL, and what does that cost?
 * (finding 14, 2026-08-13.)
 *
 * The step is nothing anybody sets: the server doubles it until the grid over
 * the whole painted extent fits inside its point budget
 * (`app/core/heightfield._step_for`). So ONE area drawn far out coarsens the
 * relief of the entire world — measured live, a 16 160 × 5 876 m union box
 * took the step from 4 m to 32 m — and the small hills of a 22 m patch, 8…12 m
 * wide, then have no support point left and vanish. Nothing said so.
 *
 * THE NUMBERS COME FROM THE SERVER, both of them (`GET /world/height-areas`
 * and the save answers carry `step_m` + `default_step_m`). This function does
 * not recompute the doubling — a second implementation of it is how a warning
 * starts naming a step the world does not have. All it does is the ONE piece
 * of arithmetic the sentence needs:
 *
 *     nothing under 2 × step survives      (NYQUIST — the same limit that
 *                                           clamps `relief_wave_m` at
 *                                           2 × the default step)
 *
 * `null` means "nothing to say": the finest grid, or numbers that say nothing.
 * An unusable `defaultStepM` is deliberately silent rather than alarming —
 * without it there is no "coarser than normal" to speak of.
 */
export function reliefStepNotice(stepM: number, defaultStepM: number
): { stepM: number; lostUnderM: number } | null {
  if (!Number.isFinite(stepM) || stepM <= 0) return null
  if (!Number.isFinite(defaultStepM) || defaultStepM <= 0) return null
  if (stepM <= defaultStepM) return null
  return { stepM, lostUnderM: stepM * 2 }
}

/** Is this area's ramp steeper than a walker climbs? */
export function tooSteep(heightM: number, falloffM: number,
  maxSlopeDeg: number, maxStepM: number): boolean {
  const need = minFalloffFor(heightM, maxSlopeDeg, maxStepM)
  if (!need) return false
  return !(falloffM >= need)
}
