/**
 * Which room the avatar is standing in while it walks through an open
 * interior (plan-3d-game stage 3, task 6).
 *
 * Pure on purpose — no Three, no DOM, no clock: every input arrives as a
 * plain number and the caller hands in `nowMs`, so `client3d/scripts/smoke_walk_math.mjs`
 * can check the numbers without a browser.
 *
 * The rule is "the room whose centre is closest", and its whole difficulty is
 * that a centre distance flips the moment one crosses the halfway line
 * between two rooms: a player standing on that line would fire one
 * `/play/enter-room` per frame. So a new nearest room has to HOLD for
 * `holdSeconds` before it counts, and a tie never moves anybody.
 */

/** Running clock of the hysteresis. Belongs to the caller — this module keeps
 *  no state of its own. */
export interface RoomWalkState {
  /** room that is currently the closest one but has not been switched to yet */
  candidate: string | null;
  /** `nowMs` at which that candidate became the closest one */
  sinceMs: number;
}

/** One room of the open interior, already reduced to what the rule needs. */
export interface RoomWalkRoom {
  id: string;
  /** storey the room sits on — only the displayed one is walkable */
  level: number;
  /** room centre in world metres (XZ; the height plays no part) */
  center: { x: number; z: number };
}

/** A fresh, empty clock. A function and not a shared constant: the state is
 *  handed around by reference, and a shared object would be written by every
 *  caller at once. */
export function idleRoomWalk(): RoomWalkState {
  return { candidate: null, sinceMs: 0 };
}

/**
 * Distances closer together than this count as equal. Two rooms of the same
 * size are exactly the same distance away on their halfway line, and floating
 * point makes that comparison a coin toss — which is precisely the flicker the
 * hold is there to prevent.
 */
const TIE_EPS = 1e-9;

/**
 * The room the avatar should be in, given where it is drawn.
 *
 * @param current      room the SERVER has the avatar in (null = none yet)
 * @param pos          where the figure is drawn, world metres
 * @param rooms        rooms of the open interior (all storeys)
 * @param currentLevel displayed storey — rooms on other storeys drop out
 * @param state        the caller's clock, from `idleRoomWalk()`
 * @param nowMs        monotonic milliseconds (`performance.now()`)
 * @param holdSeconds  how long a new nearest room has to hold
 * @returns `next` = the room the avatar should be in. It equals `current`
 *          while nothing is due, so the caller fires exactly when
 *          `next !== current`. `state` is the clock to keep for the next call.
 */
export function nearestRoomSwitch(
  current: string | null,
  pos: { x: number; z: number },
  rooms: RoomWalkRoom[],
  currentLevel: number,
  state: RoomWalkState,
  nowMs: number,
  holdSeconds: number,
): { next: string | null; state: RoomWalkState } {
  // Only the displayed storey: the room one floor up is nearer in XZ than the
  // one across the hall, and walking cannot reach it — there is no vertical
  // movement on foot.
  const scored = rooms
    .filter((r) => r.level === currentLevel)
    .map((r) => ({ id: r.id, d: Math.hypot(r.center.x - pos.x, r.center.z - pos.z) }))
    .sort((a, b) => (a.d - b.d) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  // Nothing on this storey (no layout, or a storey without rooms): there is no
  // room to walk into, so the server's answer stands and no clock runs.
  if (!scored.length) return { next: current, state: idleRoomWalk() };

  let best = scored[0].id;
  // A tie must never move anybody: standing exactly between two rooms keeps
  // the one the avatar is already in. Without a current room the sort above
  // has already decided by id, which is deterministic across frames.
  const cur = current === null ? undefined : scored.find((s) => s.id === current);
  if (cur && cur.d - scored[0].d <= TIE_EPS) best = current as string;

  // Already there — no clock to run, and a candidate left over from earlier is
  // stale (the player turned back).
  if (best === current) return { next: current, state: idleRoomWalk() };
  // A different nearest room than last frame restarts the hold.
  if (state.candidate !== best) return { next: current, state: { candidate: best, sinceMs: nowMs } };
  // Held long enough: the switch is due. The clock re-arms instead of being
  // cleared, so an unconfirmed switch cannot repeat before another full hold.
  if (nowMs - state.sinceMs >= holdSeconds * 1000) {
    return { next: best, state: { candidate: best, sinceMs: nowMs } };
  }
  return { next: current, state };
}
