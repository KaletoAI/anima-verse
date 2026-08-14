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
 *
 * ONE STEP PER AREA IS TOO COARSE, which is why the second half of this file
 * exists (`instanceTier`/`instanceVisible`, 2026-08-15). An area is a wood,
 * not a point: with one tier for all of it the trees at the player's feet drop
 * to the cheap mesh because the far edge of the same wood is 100 m away, and a
 * 300 m meadow is either wholly drawn or wholly gone. The per-instance rules
 * ask the same three questions of ONE prop at ITS OWN distance, and they take
 * the distances as a `ScatterLodCfg` argument instead of reading the constants
 * — the numbers above are only their DEFAULTS now, because the player may set
 * them (`game/prefs.ts`, localStorage). The area-wide functions stay until
 * their callers are rewired.
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
 * AREA-WIDE, and that is the older half of this module: the per-instance rules
 * below answer the same question for ONE prop at its OWN distance.
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

/* ==========================================================================
 * PER-INSTANCE LOD — the same three questions, asked of ONE prop
 * ========================================================================== */

/**
 * The three distances as ONE value.
 *
 * They are an ARGUMENT and no longer a constant read from module scope,
 * because two callers need different numbers: the smoke check feeds hand-
 * derived thresholds to derive its expectations from, and the running client
 * feeds whatever the player set in the menu. A module-level `let` that the
 * menu writes would work exactly once — it would also make every function
 * here impure, which is the one thing this file is not allowed to be.
 */
export interface ScatterLodCfg {
  /** Nearer than this an instance stands at the full mesh (metres). */
  nearM: number;
  /** Farther than this at the low mesh. In between it keeps what it has. */
  farM: number;
  /** Beyond this it is not drawn at all (metres). */
  cullM: number;
}

/** What the constants above are: the DEFAULT distances, the ones a player who
 *  never opens the menu plays with. `prefs.ts` holds the same three numbers as
 *  its stored defaults (it must stay import-free, so it cannot read them from
 *  here) and the smoke check pins the two against each other. */
export const SCATTER_LOD_DEFAULTS: ScatterLodCfg = {
  nearM: SCATTER_TIER_NEAR,
  farM: SCATTER_TIER_FAR,
  cullM: SCATTER_CULL_FAR,
};

/** What ONE instance is drawn as: 0 = the full mesh, 1 = the low mesh,
 *  2 = not at all.
 *
 *  Numbers and not the `ScatterTier` strings, because this is what a
 *  `Uint8Array` per scatter entry holds — one byte per instance, read and
 *  written for every instance of every entry on every LOD tick. A string per
 *  instance would allocate on a path whose whole point is not to. */
export type InstanceTier = 0 | 1 | 2;

/** How far back inside the cull distance a hidden instance has to come before
 *  it is drawn again — 0.92 of it, i.e. 110.4 m at the default 120 m.
 *
 *  The cull edge needs the same treatment the 35…45 m band gives the mesh
 *  swap, and for a harsher reason: a tree that pops in and out with every
 *  centimetre of camera drift is far more visible than one that swaps mesh.
 *  A FACTOR rather than a second distance, so a player who sets the cull to
 *  400 m gets a band that scales with it instead of a 0.4 % sliver. */
export const SCATTER_UNHIDE_FACTOR = 0.92;

/**
 * Which of the three classes ONE instance belongs in, given how far away IT is
 * and what it was drawn as last tick.
 *
 * Two hystereses, both of them "the answer inside the band is whatever is
 * already there":
 *
 *   - `nearM`…`farM` between full and low, exclusive on both ends exactly as
 *     `scatterTierFor` has it — 35 m does not promote, 45 m does not demote.
 *   - `SCATTER_UNHIDE_FACTOR`·`cullM`…`cullM` between drawn and hidden. Note
 *     the asymmetry: hiding happens BEYOND the cull distance, showing again
 *     only well inside it, so the two thresholds cannot chase each other.
 *
 * A previously hidden instance that comes back re-enters as `low` and is then
 * judged by the band like everything else — it kept no memory of the tier it
 * had before it was culled, and at 0.92·cull it is in low territory anyway.
 * The one case where that matters is a hand-set cfg whose bands overlap; the
 * answer there is still a tier and not a crash.
 *
 * A NON-FINITE DISTANCE HIDES the instance, unlike `scatterTierFor`, which
 * keeps the tier and leaves the hiding to `scatterCountShare`. Here one
 * function answers both questions, so it has to give the answer that draws
 * nothing rather than the one that draws a NaN matrix.
 */
export function instanceTier(
  distM: number, prev: InstanceTier, cfg: ScatterLodCfg,
): InstanceTier {
  // Negated, so a NaN distance lands here instead of in the comparisons below.
  if (!(distM <= cfg.cullM)) return 2;
  let held: InstanceTier = prev;
  if (prev === 2) {
    if (!(distM < SCATTER_UNHIDE_FACTOR * cfg.cullM)) return 2;
    held = 1;
  }
  if (distM < cfg.nearM) return 0;
  if (distM > cfg.farM) return 1;
  return held;
}

/**
 * What share of the instances at that distance is drawn — `scatterCountShare`
 * measured at the instance's own distance and against a given cfg.
 *
 * The line is the same one: flat 1 up to `farM`, straight down to
 * `SCATTER_MIN_SHARE` at `cullM`, nothing beyond. `cullM > farM` need not be
 * checked before the division: the only branch that divides is the one where
 * `distM` is above `farM` and at most `cullM`, which cannot be reached unless
 * the two differ.
 */
export function instanceShare(distM: number, cfg: ScatterLodCfg): number {
  if (!(distM <= cfg.cullM)) return 0;
  if (distM <= cfg.farM) return 1;
  const t = (distM - cfg.farM) / (cfg.cullM - cfg.farM);
  return 1 - t * (1 - SCATTER_MIN_SHARE);
}

/**
 * A number in [0,1) that belongs to an instance INDEX and to nothing else.
 *
 * This is what makes thinning stable. The area-wide budget could cap the tail
 * of the list because one distance governed the whole area; per instance there
 * is no tail — every instance has its own share, and "the first n of them"
 * would mean a different n per tick and a different SET per tick, i.e. trees
 * blinking in and out while the player stands still. A hash of the index gives
 * each instance a fixed place in the queue, so walking towards a wood always
 * regrows the same trees in the same order.
 *
 * The mix is the murmur3 finaliser over the index times the golden-ratio
 * constant. The textbook `fract(sin(i·12.9898)·43758.5453)` was measured
 * first and is visibly biased in the low quarter — it drew 14 % too few at a
 * share of 0.25, exactly where the thinning is supposed to work — while this
 * one stays inside 3.5 % over the same 1000 indices.
 *
 * `hash(0) === 0` falls out of the multiplication and is kept deliberately:
 * instance 0 survives as long as anything of the entry is drawn at all, which
 * is the per-instance form of the "floor of ONE" in `scatterVisibleCount` — a
 * lone landmark tree is instance 0 of a one-instance entry.
 */
function instanceHash(index: number): number {
  let h = Math.imul(index | 0, 2654435761) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/**
 * Whether instance `index` is part of the thinned-out set at its distance.
 *
 * Pure and stateless on purpose: the set is not remembered anywhere, it is
 * recomputed from index and distance every tick and comes out the same. Which
 * also means the answer is MONOTONE in the distance — an instance that is
 * drawn 100 m away is drawn at 60 m too, because its hash did not move and
 * the share only grew. Nothing pops out while the player walks closer.
 *
 * Hiding by distance is `instanceTier`'s answer, not this one's; an instance
 * is drawn when its tier is not 2 AND it is visible here.
 */
export function instanceVisible(
  index: number, distM: number, cfg: ScatterLodCfg,
): boolean {
  const share = instanceShare(distM, cfg);
  if (share >= 1) return true;
  if (share <= 0) return false;
  return instanceHash(index) < share;
}
