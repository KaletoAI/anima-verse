/**
 * Clip timing of a PAIR interaction (§ A8a) — the ONE place that turns the
 * server's clip clock into the time the mixer is seeked to.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM, and no imports either — that is what lets
 * `client3d/scripts/smoke_pair_realtime.mjs` and
 * `client3d/scripts/smoke_pair_clip_tempo.mjs` transpile the file and check
 * it with hand-derived numbers.
 *
 * THE RULE (plan-animationen-echtzeit-stehplatz.md E1, pair scene tempo).
 * Every animation runs in REAL time, whatever the game-speed factor is, at the
 * scene's TEMPO (0.2..1 clip seconds per real second; 1 = the clip's own
 * speed). The server keeps one clip clock per scene and states it as
 * `clip_s` (CLIP seconds since the clip began, every second already at the
 * tempo it ran at) plus the `tempo` it runs at now. Between polls the client
 * advances its own copy by `dt · tempo` — nothing in a frozen world — and a
 * genuinely new poll snaps it only beyond PAIR_SNAP_S. The game-speed factor
 * plays no part: `elapsed_s` / `rate` stay in the block for everything else
 * (a frozen world is `rate 0`).
 */

/** Drift (clip seconds) between the local clip clock and the position a fresh
 *  poll states beyond which the local clock is snapped to the server's. Below
 *  it the client keeps counting frames itself — a re-seek on every poll is
 *  what made the figure stutter once a second. */
export const PAIR_SNAP_S = 0.3;

/** The playback tempo of a scene: a finite number clamped to [0.2, 1]; 1 for
 *  anything else (a payload without one). */
export function clipTempo(tempo: unknown): number {
  return typeof tempo === 'number' && Number.isFinite(tempo) ? Math.min(1, Math.max(0.2, tempo)) : 1;
}

export interface PairClipInput {
  /** the server's clip clock `clip_s` (CLIP seconds since the clip began) as
   *  of the last poll — `null` BETWEEN polls, where nothing pulls the local
   *  clock. */
  clipS: number | null;
  /** clip seconds per real second (`tempo`; `clipTempo` clamps it) */
  tempo: number;
  /** a frozen world (`rate 0`): the local clock stands */
  frozen: boolean;
  /** REAL seconds this frame adds to the local clock (times the tempo);
   *  missing = 0 */
  dt?: number;
  /** does the clip repeat, or does it hold its last frame? */
  loop: boolean;
  /** how many cycles a loop plays before it holds its last frame;
   *  null/missing = endless. Ignored without `loop`. */
  loopCount?: number | null;
  /** the clip's own length in seconds (0/unknown = no wrap, no clamp) */
  clipDurationS: number;
  /** the clip clock this figure carries, in CLIP seconds. `undefined` adopts
   *  a fresh interaction: there is no local clock to keep yet. */
  localClipT?: number;
  /** drift threshold for the snap; defaults to `PAIR_SNAP_S` */
  snapS?: number;
}

export interface PairClipTime {
  /** the clip clock after the advance and the reconciliation — clip seconds
   *  since the start, to be carried into the next frame */
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
 *  on: the local clock advanced by `dt · tempo` (0 frozen), then the
 *  server's `clip_s` adopted (no local clock) or snapped to (drift more than
 *  `snapS`). See the module docstring for the rule and the two smokes for the
 *  hand-derived cases. */
export function pairClipPhase(input: PairClipInput): PairClipTime {
  const { clipS, loop, clipDurationS } = input;
  const snapS = input.snapS ?? PAIR_SNAP_S;
  const dt = input.dt ?? 0;
  const step = !input.frozen && dt > 0 ? dt * clipTempo(input.tempo) : 0;
  const serverT = clipS !== null && Number.isFinite(clipS) ? Math.max(0, clipS) : null;
  const local = input.localClipT;
  let clipT: number;
  if (local === undefined || !Number.isFinite(local)) clipT = serverT ?? 0;
  else {
    const advanced = local + step;
    clipT = serverT !== null && Math.abs(advanced - serverT) > snapS ? serverT : advanced;
  }
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
