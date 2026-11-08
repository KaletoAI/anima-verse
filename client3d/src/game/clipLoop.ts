/**
 * How the mixer plays a clip that the listing (§ A8) flags `loop` and
 * `loop_count` — the ONE place that turns the two fields into a Three.js
 * loop mode.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no imports — `client3d/scripts/smoke_clip_loop_count.mjs` transpiles
 * the file and checks it with hand-derived numbers, and drives a real
 * `AnimationMixer` with the answer.
 *
 * THE RULE. A one-shot plays once and holds its last frame. An endless loop
 * (`loop` without a count) repeats for as long as it plays. A counted loop
 * repeats `loop_count` times and then holds its last frame, exactly like a
 * one-shot after its single run — what follows it is the context's business
 * (the server changes the pose, a finale hands back to the action's clip).
 */

/** The largest count the server accepts (`animation_clips.LOOP_COUNT_MAX`). */
export const LOOP_COUNT_MAX = 99;

/** `raw` as a repeat count, or null (= endless): a whole number 1..99. */
export function validLoopCount(raw: unknown): number | null {
  return typeof raw === 'number' && Number.isInteger(raw) && raw >= 1 && raw <= LOOP_COUNT_MAX
    ? raw : null;
}

/** The mixer's settings for a clip: `repeat` = `LoopRepeat` (else
 *  `LoopOnce`), `repetitions` its count (`Infinity` = endless), `clamp` =
 *  `clampWhenFinished` — hold the last frame once the runs are used up. A
 *  count without `loop` changes nothing: a one-shot plays once. */
export function clipLoopMode(loop: boolean, loopCount: unknown):
  { repeat: boolean; repetitions: number; clamp: boolean } {
  if (!loop) return { repeat: false, repetitions: 1, clamp: true };
  const count = validLoopCount(loopCount);
  return count === null
    ? { repeat: true, repetitions: Infinity, clamp: false }
    : { repeat: true, repetitions: count, clamp: true };
}
