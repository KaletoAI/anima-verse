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
  return { clipT, phase: clipPhaseAt(clipT, loop, clipDurationS) };
}

/** The clip clock mapped onto the clip: a cycle replays, a one-shot holds its
 *  last frame. Without a length there is nothing to wrap in. */
function clipPhaseAt(clipT: number, loop: boolean, clipDurationS: number): number {
  if (!(clipDurationS > 0)) return clipT;
  return loop ? clipT % clipDurationS : Math.min(clipT, clipDurationS);
}
