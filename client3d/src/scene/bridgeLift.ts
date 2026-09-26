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
 *  - The move never ends before the bridge's own start crossfade
 *    (`BRIDGE_FADE_IN_S`): a chair whose feet stand from the first frame
 *    would otherwise drop the body by the whole difference within one frame
 *    (4.6 cm in 33 ms on Soldier). It is spread over the fade-in instead.
 *  - A floor that arrives only while the bridge already runs (the poll that
 *    brought the standing clip still carried the seat) is handed over the
 *    same way: the owner puts the root on it and the figure takes the
 *    difference (`Figure.shiftBridgeLift`). Once the ramp has begun, the part
 *    of it the formula would not carry fades out over `LIFT_RAMP_S`
 *    (`fadeCarry`) instead of jumping.
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

/** The crossfade a bridge clip starts with, s — `Figure.play` fades the
 *  bridge in (and the clip it leaves out) by exactly this, and the lift's
 *  ramp never ends before it. The one constant for both. */
export const BRIDGE_FADE_IN_S = 0.25;

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

/** The ramp of a bridge's lift, clip seconds: it ends at the feet's first
 *  contact but never before the start crossfade, and begins `LIFT_RAMP_S`
 *  earlier (not before 0). */
export function liftRamp(firstContactS: number): { from: number; to: number } {
  const to = Math.max(firstContactS, BRIDGE_FADE_IN_S);
  return { from: Math.max(0, to - LIFT_RAMP_S), to };
}

/**
 * The lift at clip time `t`: `startLift` up to the ramp's start, then a
 * smoothstep onto `endLift` that arrives at the ramp's end (`liftRamp`: the
 * feet's first contact, but not before `BRIDGE_FADE_IN_S`), and `endLift`
 * from there on. A clip without contact passes its duration as
 * `firstContactS`, so the ramp ends with the clip. The steepest step of the
 * smoothstep is 1.5 × |endLift − startLift| / (ramp length) per second.
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
  const { from, to } = liftRamp(firstContactS);
  if (t >= to) return endLift;
  if (t <= from) return start;
  const x = (t - from) / (to - from);
  const s = x * x * (3 - 2 * x);
  return start + (endLift - start) * s;
}

/**
 * What is left, `elapsedS` after a hand-over, of a lift difference `amount`
 * the ramp formula does not carry (`Figure.shiftBridgeLift`): `amount` at 0,
 * a smoothstep down to 0 at `LIFT_RAMP_S`, 0 after. Non-finite input → 0.
 */
export function fadeCarry(amount: number, elapsedS: number): number {
  if (!Number.isFinite(amount) || !Number.isFinite(elapsedS)) return 0;
  if (elapsedS <= 0) return amount;
  if (elapsedS >= LIFT_RAMP_S) return 0;
  const x = elapsedS / LIFT_RAMP_S;
  return amount * (1 - x * x * (3 - 2 * x));
}
