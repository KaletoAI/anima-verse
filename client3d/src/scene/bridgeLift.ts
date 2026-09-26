/**
 * THE HEIGHT OF A BRIDGE — how far a figure's body is lifted over its root
 * while a HOLDING bridge clip (`get-up-bed`, `get-up-chair`) carries it out of
 * a bed or a chair. Pure arithmetic, no three.js, so
 * `client3d/scripts/smoke_bridge_lift.mjs` checks it by hand.
 *
 * The rule (Task C5 of plan-bruecken-feinschliff):
 *  - During a bridge the root belongs to its owner in X/Z only. The HEIGHT is
 *    set ONCE, when the bridge starts: the owner puts the root straight onto
 *    the new floor and hands the difference to the figure as `startLift`
 *    (`Figure.beginBridgeLift`, `npcs.NpcManager.tick`).
 *  - The figure holds the lying / sitting body on its surface with that lift
 *    and brings the feet onto the floor at their first ground contact: from
 *    then on the lift is `endLift`, the height that puts the lowest foot point
 *    of the clip's LAST frame onto the rig's rest floor (measured per rig,
 *    `footLockMeasure.relockRootPaths`).
 *  - A bed or a chair of another height than the one the clip was authored on
 *    leaves a difference between the two. The body moves by it over the last
 *    `LIFT_RAMP_S` before the feet touch down. A root alone cannot hold the
 *    seat AND the feet at once; the feet come first — that is the choice.
 *
 * Unit of every lift: metres in the frame of the figure root (the caller
 * scales `endLift` from template units, `× baseScale`, the same chain as the
 * clip ground offset and the bridge travel). Times are clip seconds.
 *
 * It also holds the one per-clip store of measured lifts (`clipBridgeLift` /
 * `setClipBridgeLift`), next to its type — the `bridgeTravel.clipRootPath`
 * pattern: `footLockMeasure.ts` writes it, `figures.ts` reads it, neither
 * imports the other for it.
 */

/** How long before the feet's first ground contact the body starts to move
 *  from its surface onto the height that lands the feet, s. */
export const LIFT_RAMP_S = 0.6;

/** What a bridge clip needs for its height, measured once per rig. */
export interface BridgeLift {
  /** Lift that puts the lowest foot point of the clip's LAST frame onto the
   *  rig's rest floor, TEMPLATE units (the figure scales it by `baseScale`). */
  endLift: number;
  /** Clip time of the first frame in which a foot point is in FULL ground
   *  contact, s — the clip's duration when no frame is. */
  firstContactS: number;
}

/** Keyed by the clip object (a `THREE.AnimationClip`); no three import is
 *  needed for that. */
const clipBridgeLifts = new WeakMap<object, BridgeLift>();

/** The measured lift of a clip, `undefined` when it carries none. */
export function clipBridgeLift(clip: object): BridgeLift | undefined {
  return clipBridgeLifts.get(clip);
}

/** Store (or replace) the measured lift of a clip; `null` removes it. */
export function setClipBridgeLift(clip: object, lift: BridgeLift | null): void {
  if (lift) clipBridgeLifts.set(clip, lift);
  else clipBridgeLifts.delete(clip);
}

/**
 * The lift at clip time `t`: `startLift` up to `max(0, firstContactS −
 * LIFT_RAMP_S)`, then a smoothstep onto `endLift` that arrives AT
 * `firstContactS`, and `endLift` from there on. A clip without contact passes
 * its duration as `firstContactS`, so the ramp ends with the clip.
 *
 * Never NaN: a non-finite `t`, `endLift` or `firstContactS` answers
 * `startLift`, and a non-finite `startLift` counts as 0 — one NaN in the
 * height and the figure hangs nowhere for the rest of the session.
 */
export function liftAt(t: number, startLift: number, endLift: number, firstContactS: number): number {
  const start = Number.isFinite(startLift) ? startLift : 0;
  if (!Number.isFinite(t) || !Number.isFinite(endLift) || !Number.isFinite(firstContactS)) {
    return start;
  }
  const from = Math.max(0, firstContactS - LIFT_RAMP_S);
  if (t >= firstContactS) return endLift;
  if (t <= from) return start;
  const x = (t - from) / (firstContactS - from);
  const s = x * x * (3 - 2 * x);
  return start + (endLift - start) * s;
}
