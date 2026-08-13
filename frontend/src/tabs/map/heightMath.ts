/**
 * heightMath — the authoring arithmetic of the world relief (§ A16).
 *
 * One question, asked in two places (the layer draws a warning glyph, the chip
 * writes the sentence): is this ramp steeper than a walker can climb?
 *
 * The server judges every reported step with `game.max_slope_deg` (§ A15 Nr. 8)
 * and the number travels in the worldmap payload, so the editor can warn while
 * the shape is being drawn instead of leaving the author to discover a sealed
 * plateau by walking into it. A height area's ramp has a CONSTANT gradient:
 * `|height_m| / falloff_m` — it climbs the full height over exactly that
 * width. So it is walkable exactly while
 *
 *     atan(|height_m| / falloff_m) <= max_slope_deg
 *     i.e. falloff_m >= |height_m| / tan(max_slope_deg)
 *
 * A ramp of 0 (a wall at the outline) is infinitely steep and always warns —
 * unless the area is flat, which is no ramp at all.
 *
 * IT IS A WARNING, NEVER A REFUSAL. A cliff is a legitimate thing to build (a
 * plateau one reaches through an opening, a ravine one is meant to walk
 * around); what is not legitimate is building one by accident.
 */

/** The narrowest ramp this height may have and still be walkable, in metres.
 *  0 when nothing can be said (a flat area, or an unusable limit). */
export function minFalloffFor(heightM: number, maxSlopeDeg: number): number {
  const h = Math.abs(heightM)
  if (!Number.isFinite(h) || h <= 0) return 0
  if (!Number.isFinite(maxSlopeDeg) || maxSlopeDeg <= 0 || maxSlopeDeg >= 90) {
    return 0
  }
  const need = h / Math.tan((maxSlopeDeg * Math.PI) / 180)
  return Math.round(need * 100) / 100
}

/** Is this area's ramp steeper than `max_slope_deg`? */
export function tooSteep(heightM: number, falloffM: number,
  maxSlopeDeg: number): boolean {
  const need = minFalloffFor(heightM, maxSlopeDeg)
  if (!need) return false
  return !(falloffM >= need)
}
