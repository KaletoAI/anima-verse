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
  /** True for the storey's CORRIDOR (§ A13b). The walk rule does not read it —
   *  a corridor holds no rectangle, so it is reached through `floorIdOf` —
   *  but the SAME room list feeds the lift and the stairs, where a corridor
   *  wins over every distance (`stairs.nearestRoomAt`). */
  floor?: boolean;
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

/** Everything the candidate rule below needs, so it can be stated once and
 *  checked without a scene. The two predicates and `floorIdOf` are the
 *  caller's window onto the mounted tile — geometry stays where it is
 *  measured, this module only decides. */
export interface CandidateInput {
  /** room the SERVER has the avatar in (null = none yet) */
  current: string | null;
  /** storey of THAT room, undefined while it is unknown */
  ownLevel: number | undefined;
  /** where the figure is drawn, world metres */
  pos: { x: number; z: number };
  /** rooms with a rectangle on the shown interior, already lock-filtered */
  rooms: RoomWalkRoom[];
  /** does a room's rectangle hold `pos` */
  insideRect: (id: string) => boolean;
  /** does the storey's building outline hold `pos` (false = no outline known) */
  insideLevelOutline: (level: number) => boolean;
  /** the ground room's id, '' when it is locked */
  groundId: string;
  /** the storey corridor's id, '' when the storey has none or it is locked */
  floorIdOf: (level: number) => string;
}

/**
 * The rooms the walk heuristic may switch between, given where the figure
 * stands (§ A13b).
 *
 * THE ROOMS OF A PLACE DO NOT COVER IT. Whoever steps out of a room stands
 * outside every rectangle, and that used to leave the avatar in the room it
 * had left — for the server, the prompt and the chat window alike. Two rooms
 * with an id and no geometry answer for that gap, and they cannot be found by
 * distance: the storey's CORRIDOR inside the building, the GROUND outside it.
 * Which of them it is, is a storey question and a containment question, in
 * that order:
 *
 * - a rectangle holds the figure -> those rooms, and nothing else; a corridor
 *   is never a candidate while the figure is in a real room;
 * - otherwise, on a storey that is not 0: its corridor. There is no ground to
 *   fall onto from a cellar or a first floor, so without a corridor (none
 *   stored, or locked) the old fall-through stands;
 * - on storey 0 the building's outline decides: inside it the hallway (which
 *   only exists on opt-in), outside it the ground.
 *
 * A storey nobody knows yet reads as 0, the same assumption the door gate and
 * the storey follow make about a figure without a room. Without rooms at all
 * (the scene has not arrived) nothing is proposed — adopting a room out of
 * nothing is how a figure drifts out of the room it just entered.
 */
export function roomWalkCandidates(i: CandidateInput): RoomWalkRoom[] {
  const inside = i.rooms.filter((r) => i.insideRect(r.id));
  if (inside.length) return inside;
  if (!i.rooms.length) return [];
  const level = i.ownLevel ?? 0;
  const here = { x: i.pos.x, z: i.pos.z };
  const floor = i.floorIdOf(level);
  if (level !== 0) return floor ? [{ id: floor, level, center: here }] : i.rooms;
  if (floor && i.insideLevelOutline(0)) return [{ id: floor, level: 0, center: here }];
  return i.groundId ? [{ id: i.groundId, level: 0, center: here }] : i.rooms;
}
