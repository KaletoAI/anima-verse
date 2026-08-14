/**
 * Pure display maths of the ground scatter: how tall its props stand, how far
 * they bend in the wind, and its level of detail.
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

/** Target height of a scattered GLB when NOBODY knows how tall it should be
 *  (metres) — no authored `height_m`, no prop record behind the URL.
 *
 *  A prop file carries whatever size its author chose, and "whatever the file
 *  says" is not a size in a world measured in metres — a tree exported in
 *  centimetres stood 2 cm tall next to the figure. So an unknown model is
 *  normalised to a shrub/small-tree height instead of being trusted. It is the
 *  LAST resort, not the default: a prop of this world brings its real height
 *  along (`prop_height_m`), and this number is what is left for the built-in
 *  tuft's model-less siblings and foreign URLs. */
export const SCATTER_MODEL_HEIGHT_M = 2.0;

/**
 * How tall ONE scattered prop is drawn, in metres (§ A9).
 *
 * The precedence, and the whole point of it: the height AUTHORED on the
 * scatter row wins, because someone typed it for this ground. Otherwise the
 * prop's own library height governs — a tree is 8 m tall because the Props tab
 * says so, and every area that scatters it gets a tree instead of a shrub.
 * Only when neither exists (a foreign URL, a prop this world has no record
 * for) does the flat fallback apply. Before finding 12 the fallback WAS the
 * default and every wood stood at avatar height.
 *
 * Both inputs are "> 0 or nothing": undefined, null, NaN, 0 and negatives all
 * read as "not given", written as `> 0` so NaN falls through instead of
 * scaling a mesh into a NaN matrix.
 */
export function scatterTargetH(entryH?: number, propH?: number): number {
  if (Number(entryH) > 0) return Number(entryH);
  if (Number(propH) > 0) return Number(propH);
  return SCATTER_MODEL_HEIGHT_M;
}

/** What a scatter entry bends by when it says nothing: the ground's FULL
 *  deflection. The server stores and ships the factor only when it differs
 *  (`props.SWAY_FACTOR_DEFAULT`), so an absent field is this. */
export const SCATTER_SWAY_FACTOR_DEFAULT = 1;

/**
 * How far ONE scatter entry really bends, in metres (§ A9).
 *
 * TWO AUTHORS, ONE NUMBER. The terrain KIND says how hard it blows over this
 * ground (`meta.sway_m`, already clamped by the caller); the PROP says how
 * much of that it takes part in (`sway_factor` on the entry, 0..1, from its
 * library record). A boulder scattered over a waving meadow gets 0 and stands
 * still while the ferns beside it bend fully — which is the whole point of the
 * factor, and it cannot be expressed on the kind, where the wind lives.
 *
 * The factor is "a finite NUMBER in 0..1, or nothing": absent, null, NaN and
 * non-numbers read as "not given" and leave the ground's own amplitude alone,
 * values outside the range are clamped exactly as the server clamps them.
 *
 * WHICH IS WHY `Number()` IS NOT ENOUGH HERE, unlike everywhere else in this
 * file: `Number(null)` is 0, and 0 is a legal factor in this one field — a
 * `null` on the wire would silently stop a whole meadow instead of falling
 * back to the default. The type is tested, not just the value.
 *
 * ROUNDED TO TWO DECIMALS, and that is not cosmetic: `applySway` bakes the
 * amplitude into the shader at that precision and refuses anything under
 * `SWAY_MIN_M`, while `ground.ts` clones a material for every entry whose
 * value is `> 0`. Rounding here is what keeps those two tests agreeing — a
 * product of 0.004 would otherwise buy a material clone that never moves.
 */
export function scatterSway(swayM: number, factor?: number): number {
  const base = Number(swayM);
  if (!(base > 0)) return 0;
  const clamped = typeof factor === 'number' && Number.isFinite(factor)
    ? Math.min(Math.max(factor, 0), 1)
    : SCATTER_SWAY_FACTOR_DEFAULT;
  return Math.round(base * clamped * 100) / 100;
}

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
