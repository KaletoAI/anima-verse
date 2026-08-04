/**
 * The two rules behind a speech bubble (stage 6): how much of a line is shown,
 * and how long it hangs over the head.
 *
 * Pure and import-free on purpose — no `three`, no DOM — so both rules are
 * checked with hand-derived cases in `scripts/smoke_walk_math.mjs` instead of
 * being judged by looking at the screen. `scene/npcs.ts` owns the element and
 * the clock; this module owns nothing but the arithmetic.
 */

/** A bubble is a glance, not a transcript — the chat panel keeps the full
 *  text. 140 characters is roughly two spoken sentences. */
export const BUBBLE_MAX_CHARS = 140;
/** Even "Yes." needs long enough to be noticed at all. */
export const BUBBLE_BASE_MS = 3500;
/** Reading pace: ~18 characters per second on top of the base. */
export const BUBBLE_MS_PER_CHAR = 55;
/** Nobody stares at one bubble longer than this, however long the line. */
export const BUBBLE_MAX_MS = 12000;

/**
 * What the bubble shows: whitespace collapsed to single spaces (a pasted line
 * break must not make the bubble three lines tall), cut to BUBBLE_MAX_CHARS
 * INCLUDING the ellipsis — so the rendered string never exceeds the cap.
 * Returns '' for anything that is only whitespace; the caller shows no bubble
 * at all then.
 */
export function bubbleText(text: string): string {
  const words = text.trim().replace(/\s+/g, ' ');
  if (words.length <= BUBBLE_MAX_CHARS) return words;
  return `${words.slice(0, BUBBLE_MAX_CHARS - 1).trimEnd()}…`;
}

/**
 * How long the bubble stays, in milliseconds. Measured on the UNCUT line:
 * what was said is what takes time to say, even though only part of it is
 * shown. Clamped into [BUBBLE_BASE_MS, BUBBLE_MAX_MS].
 */
export function bubbleMs(text: string): number {
  const n = text.trim().replace(/\s+/g, ' ').length;
  const ms = BUBBLE_BASE_MS + n * BUBBLE_MS_PER_CHAR;
  return Math.min(Math.max(ms, BUBBLE_BASE_MS), BUBBLE_MAX_MS);
}
