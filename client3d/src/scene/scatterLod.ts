/**
 * Pure display maths of the ground scatter's level of detail.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM — the same discipline as `game/walk.ts`, and what lets
 * `client3d/scripts/smoke_scatter_math.mjs` transpile this file and check it
 * with hand-derived numbers. It must stay IMPORT-FREE.
 *
 * WHY ITS OWN THRESHOLDS. The scatter used to borrow `BUILDING_TIER_FAR`
 * (60 m) for a binary on/off per area: everything nearer stood at the FULL
 * tier, everything farther was simply gone. That is the wrong shape twice
 * over — a wood does not stop existing 60 m away, and the trees that ARE
 * shown do not all have to be the expensive mesh. So the distance decides
 * three things separately, and none of them is the building rule:
 *
 *   0 … 35 m   full mesh, every instance
 *  35 … 45 m   the hysteresis band — whatever tier the area already shows
 *  45 …120 m   low mesh, and the visible count sinks linearly to a quarter
 *   > 120 m    nothing (the area's scatter is switched off)
 *
 * THE DISTANCE IS TO THE AREA, NOT TO ITS CENTRE. Every function here is fed
 * `distance(camera, area.centre) - area.radius` — a 200 m meadow under the
 * camera is 0 m away, not 100 m. Inside an area the distance goes negative,
 * which reads as "as near as it gets" everywhere below.
 *
 * WHAT IS NOT DECIDED HERE: where the instances stand. That is the shared
 * sampler (`@anima/scene-render/scatter.ts`), it is seed-stable, and this
 * module never reorders it — the budget caps the TAIL of a deterministic
 * list, so thinning out a distant wood removes trees but never moves one.
 */

/** Nearer than this, an area's props stand at the `full` tier (metres). */
export const SCATTER_TIER_NEAR = 35;
/** Farther than this, they stand at `low`. Between NEAR and FAR the tier in
 *  place stays — a camera hovering at the line would otherwise re-download
 *  and re-swap a mesh every second, which costs far more than the detail it
 *  saves. Same shape as `wantedBuildingTier` in `main.ts`, own numbers. */
export const SCATTER_TIER_FAR = 45;
/** Beyond this the scatter of an area is not drawn at all (metres). Twice the
 *  old borrowed 60 m: props stay visible far longer than before, but as the
 *  cheap mesh and in thinning numbers instead of all-or-nothing. */
export const SCATTER_CULL_FAR = 120;
/** The share of instances still drawn immediately before the cull distance.
 *  Not 0: an area that fades to nothing pops when it crosses the line, and a
 *  quarter of a wood still reads as a wood on the horizon. */
export const SCATTER_MIN_SHARE = 0.25;

/** The two resolution tiers a prop mesh can stand at (§ B1 `variants`). The
 *  string is the tier TOKEN the payload uses; resolving it to a URL is
 *  `pickVariant`'s job and nobody else's. */
export type ScatterTier = 'full' | 'low';

/**
 * Which tier an area's props should stand at, given how far away the area is
 * and which tier they stand at NOW.
 *
 * The hysteresis is the whole point of the second argument: the answer inside
 * the 35…45 m band is "whatever is already there". Both thresholds are
 * EXCLUSIVE, so exactly 35 m does not promote and exactly 45 m does not
 * demote — a camera parked on the number keeps what it has.
 *
 * A non-finite distance (a degenerate area, see `ringBounds`) compares false
 * both ways and keeps the current tier; it is `scatterCountShare` that hides
 * such an area, so the two answers cannot contradict each other.
 */
export function scatterTierFor(distM: number, current: ScatterTier): ScatterTier {
  if (current === 'low' && distM < SCATTER_TIER_NEAR) return 'full';
  if (current === 'full' && distM > SCATTER_TIER_FAR) return 'low';
  return current;
}

/**
 * What share of an area's instances is drawn at that distance — 1 near, 0
 * beyond the cull distance, and a straight line from 1 to `SCATTER_MIN_SHARE`
 * in between.
 *
 * The line starts at `SCATTER_TIER_FAR`, not at NEAR: as long as an area is
 * near enough to deserve the full mesh it is also near enough to be counted
 * out in full. So the two rules hand over at one distance instead of fighting
 * over the same metres.
 *
 * A non-finite distance yields 0 — a degenerate area draws nothing, which is
 * what the old binary switch did with its NaN comparison too.
 */
export function scatterCountShare(distM: number): number {
  // Written as a NEGATED comparison so NaN lands here rather than in the
  // linear part, where it would produce a NaN instance count.
  if (!(distM <= SCATTER_CULL_FAR)) return 0;
  if (distM <= SCATTER_TIER_FAR) return 1;
  const t = (distM - SCATTER_TIER_FAR) / (SCATTER_CULL_FAR - SCATTER_TIER_FAR);
  return 1 - t * (1 - SCATTER_MIN_SHARE);
}

/**
 * How many of `baseCount` instances to actually draw at that distance —
 * `InstancedMesh.count`, which is why it has to be a whole number.
 *
 * Rounded, with a floor of ONE as long as anything is drawn at all: a lone
 * landmark tree on a hill has a base count of 1, and multiplying it by the
 * share would delete it at 46 m while a hundred-tree wood beside it stays.
 * The budget is meant to thin dense scatter, not to erase sparse scatter.
 */
export function scatterVisibleCount(baseCount: number, distM: number): number {
  if (!(baseCount > 0)) return 0;   // nothing placed stays nothing, floor or no floor
  const share = scatterCountShare(distM);
  if (share <= 0) return 0;
  return Math.max(1, Math.min(baseCount, Math.round(baseCount * share)));
}
