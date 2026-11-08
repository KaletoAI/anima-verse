/**
 * Clip timing of a PAIR interaction (§ A8a) — the ONE place that turns the
 * server's game-clock numbers into the time the mixer is seeked to.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM, and no imports either — that is what lets
 * `client3d/scripts/smoke_pair_realtime.mjs` transpile the file and check it
 * with hand-derived numbers.
 *
 * THE RULE (plan-animationen-echtzeit-stehplatz.md E1). Every animation runs
 * in REAL time, whatever the game-speed factor is. The server states
 * `elapsed_s` in GAME seconds and `rate` in game seconds per real second, so
 * the clip's own clock — real seconds since the interaction started — is
 * `elapsed_s / rate`, and the mixer runs at `timeScale 1`. The factor decides
 * only WHERE the clip stands when a poll arrives and whether it advances at
 * all (`rate = 0`, frozen world). Before this, `playPair` ran the mixer at
 * `timeScale = rate`: a world at factor 2 played the pair clips at double
 * speed next to solo clips at their authored speed.
 */

/** Drift (real seconds) between the local clip clock and the position a fresh
 *  poll states beyond which the local clock is snapped to the server's. Below
 *  it the client keeps counting frames itself — a re-seek on every poll is
 *  what made the figure stutter once a second. */
export const PAIR_SNAP_S = 0.3;

export interface PairClipInput {
  /** GAME seconds the server counted since the interaction began, as of the
   *  last poll — `null` BETWEEN polls, where nothing pulls the local clock. */
  elapsedGameS: number | null;
  /** game seconds per real second right now (0 = frozen world) */
  rate: number;
  /** does the clip repeat, or does it hold its last frame? */
  loop: boolean;
  /** how many cycles a loop plays before it holds its last frame;
   *  null/missing = endless. Ignored without `loop`. */
  loopCount?: number | null;
  /** the clip's own length in seconds (0/unknown = no wrap, no clamp) */
  clipDurationS: number;
  /** the clip clock this figure carries, in REAL seconds. `undefined` adopts
   *  a fresh interaction: there is no local clock to keep yet. */
  localClipT?: number;
  /** drift threshold for the snap; defaults to `PAIR_SNAP_S` */
  snapS?: number;
}

export interface PairClipTime {
  /** the clip clock after the reconciliation — real seconds since the start,
   *  to be carried into the next frame */
  clipT: number;
  /** the time to seek the clip half to: wrapped for a cycle, clamped for a
   *  one-shot */
  phase: number;
  /** does the mixer repeat the clip right now? An endless loop always; a
   *  counted loop (`loopCount` N) in its first N−1 cycles — the last one
   *  plays as a one-shot and holds, so the mixer never wraps to frame 0
   *  past the count; a one-shot never. */
  cycling: boolean;
}

/** Where in the clip a pair half stands right now, and the clock it carries
 *  on. See the module docstring for the rule and `smoke_pair_realtime.mjs`
 *  for the hand-derived cases. */
export function pairClipPhase(input: PairClipInput): PairClipTime {
  const { elapsedGameS, rate, loop, clipDurationS } = input;
  const snapS = input.snapS ?? PAIR_SNAP_S;
  // A frozen world has no clip position to divide out, and neither has a poll
  // that did not state one: the local clock is then the only truth there is.
  const serverT = elapsedGameS !== null && Number.isFinite(elapsedGameS) && rate > 0
    ? Math.max(0, elapsedGameS / rate)
    : null;
  const local = input.localClipT;
  let clipT: number;
  if (local === undefined || !Number.isFinite(local)) clipT = serverT ?? 0;
  else if (serverT !== null && Math.abs(local - serverT) > snapS) clipT = serverT;
  else clipT = local;
  clipT = Math.max(0, clipT);
  return { clipT, ...clipPhaseAt(clipT, loop, clipDurationS, input.loopCount) };
}

/** The clip clock mapped onto the clip: a cycle replays, a one-shot holds its
 *  last frame, a counted loop replays `loopCount` times and then holds its
 *  last frame. Without a length there is nothing to wrap in. */
function clipPhaseAt(clipT: number, loop: boolean, clipDurationS: number,
  loopCount: number | null | undefined): { phase: number; cycling: boolean } {
  if (!(clipDurationS > 0)) return { phase: clipT, cycling: loop };
  if (!loop) return { phase: Math.min(clipT, clipDurationS), cycling: false };
  const count = typeof loopCount === 'number' && Number.isInteger(loopCount) && loopCount >= 1
    ? loopCount : null;
  if (count === null) return { phase: clipT % clipDurationS, cycling: true };
  if (clipT >= count * clipDurationS) return { phase: clipDurationS, cycling: false };
  return { phase: clipT % clipDurationS, cycling: clipT < (count - 1) * clipDurationS };
}
