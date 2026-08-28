/**
 * ROUTING OVER STAIRS — the storey change on foot (plan-treppen task 4).
 *
 * A staircase in the payload spans exactly ONE storey: its `stair_pad` foot
 * stands on the floor of `from_level`, its head on the floor of
 * `from_level + 1`, so `foot.level + 1 === head.level` always holds. That is
 * the whole reason this module exists as a chain builder rather than a lookup:
 * a figure going from the basement to the first floor rides TWO flights, and
 * the route is the flights laid end to end.
 *
 * The chain says WHERE the climb goes; `stairY` at the bottom of this file
 * says how HIGH the figure stands on the way (task 3, plan-treppen-v2). The
 * waypoint machine in `scene/npcs.ts` walks the pair and asks the ramp for
 * every frame's height instead of blending towards the far landing — no
 * animation state and no per-step geometry either way. The stairs themselves
 * are the server's business (`app/core/scene_recipe.py`), and this module
 * never sees a single tread.
 *
 * The chain WINS over the lift: where stairs connect two storeys the figure
 * takes them, and `tile.elevatorStops` stays the fallback for everything they
 * do not connect (spec § 0, "Routing-Regel"). Hence the `null`: a chain with a
 * missing link is not a shorter chain, it is no stair route at all, and the
 * caller has to fall back rather than walk a figure into mid-air.
 *
 * Pure like `walk.ts`, `elevator.ts` and `roomwalk.ts`: plain numbers, no
 * Three, no DOM, no module state and no value import — that is what lets
 * `client3d/scripts/smoke_walk_math.mjs` check it with a bare transpile.
 */

/** One landing of a flight in WORLD metres: the storey it serves plus the
 *  point a figure stands on there — the pad's top face (= that storey's floor)
 *  plus the walk clearance, exactly like an elevator stop. */
export interface StairEndPoint {
  level: number;
  x: number;
  y: number;
  z: number;
}

/** ONE flight, reduced to the two landings it connects. `foot.level + 1 ===
 *  head.level` by construction — a flight never spans two storeys. */
export interface StairLink {
  foot: StairEndPoint;
  head: StairEndPoint;
}

/**
 * Waypoints for a storey change over stairs: per storey step the near end
 * then the far end of the connecting flight; null when any link is missing.
 *
 * `from === to` is not a missing route but an empty one — nothing to walk,
 * and the caller keeps its other waypoints. The search per step is EXACT on
 * the storey numbers (no nearest match, no tolerance), and where several
 * flights connect the same two storeys the FIRST one in the list wins: the
 * list is unordered payload, so any pick is arbitrary, and taking the first
 * makes it at least deterministic for the same payload.
 */
export function stairChain(
  stairs: readonly StairLink[],
  from: number,
  to: number,
): StairEndPoint[] | null {
  if (from === to) return [];
  const step = to > from ? 1 : -1;
  const chain: StairEndPoint[] = [];
  for (let cur = from; cur !== to; cur += step) {
    const next = cur + step;
    // Upwards the flight is the one whose foot is on `cur`; downwards the one
    // whose head is — the same flight read from the other end.
    const lower = step > 0 ? cur : next;
    const link = stairs.find((s) => s.foot.level === lower && s.head.level === lower + 1);
    if (!link) return null;
    if (step > 0) chain.push(link.foot, link.head);
    else chain.push(link.head, link.foot);
  }
  return chain;
}

// --- The player's way onto a flight (task 5) --------------------------------
//
// The avatar takes the stairs the way it takes the lift: an offer while it
// stands at a landing, and one guided ride when it accepts. Nothing about the
// climb itself is decided here — the ride hands the far landing to the same
// waypoint machine the NPC chain feeds, so the figure walks the flight exactly
// as an NPC does.

/** How close to a landing the avatar has to stand, in FIGURE metres —
 *  multiplied by the figure scale exactly like `ELEVATOR_RANGE` and the talk
 *  range. Indoors a world metre is not a figure metre: at scale 0.3 the reach
 *  is 0.45 world metres, and unscaled the offer would cover half the room. */
export const STAIR_RANGE = 1.5;

/** What the HUD needs to draw the stair offer: which way the flight leads from
 *  where the avatar stands, and the landing the ride ends on. */
export interface StairPrompt {
  dir: 'up' | 'down';
  dest: StairEndPoint;
}

/**
 * Is the avatar standing at a landing of ITS OWN storey? Returns what the HUD
 * shows, or null.
 *
 * A flight has two landings and both are offers — at the foot one goes up, at
 * the head one goes down, and the destination is always the other end. Only
 * landings of the storey the avatar is on count: a landing one floor up may be
 * within metres in XZ (a flight is barely 4 m long) and is not reachable at
 * all from here.
 *
 * With several landings in reach the NEAREST wins; a tie falls to the first
 * flight in the list, so the offer cannot flicker between two while the figure
 * stands still. The comparison is `dist < reach`, like `elevatorAt` — a figure
 * exactly on the range circle is not yet at the stairs.
 *
 * @param pos    where the figure is drawn, world metres (XZ)
 * @param level  storey the avatar is on (from its room)
 * @param scale  scale the figure is drawn at (`npcs.scaleOf`)
 */
export function stairsAt(
  pos: { x: number; z: number },
  level: number,
  stairs: readonly StairLink[],
  scale: number,
): StairPrompt | null {
  const reach = STAIR_RANGE * scale;
  let best: StairPrompt | null = null;
  let bestDist = Infinity;
  for (const s of stairs) {
    const ends: [StairEndPoint, StairEndPoint, 'up' | 'down'][] = [
      [s.foot, s.head, 'up'],
      [s.head, s.foot, 'down'],
    ];
    for (const [here, there, dir] of ends) {
      if (here.level !== level) continue;
      const dist = Math.hypot(here.x - pos.x, here.z - pos.z);
      // `>= bestDist` and not `>`: a tie keeps what was found first.
      if (dist >= reach || dist >= bestDist) continue;
      best = { dir, dest: there };
      bestDist = dist;
    }
  }
  return best;
}

// --- The climb ITSELF: the height on the run (task 3, plan-treppen-v2) -----
//
// Until now the climb was a blend: one goal at the far landing and an
// exponential ease of the root height towards it (`scene/npcs.ts`). On the
// contract flight — 3.9 m of run for 3.08 m of climb — that ease is 86 % done
// after half a second while the walk has covered 35 % of the run, so the
// figure floats a metre and a half over the treads going up and hangs the same
// under them coming down. The fix is to stop blending and ASK THE FLIGHT: the
// height of a figure on a staircase is a function of WHERE IT STANDS, and the
// server ships the run that answers it (§ B1 `stairs`).

/**
 * ONE flight as the RUN it covers, in world metres — everything `stairY` needs
 * and nothing else. `at` is the foot of the first tread (NOT the foot landing,
 * which lies a pad's half plus a gap behind it), `dir` the climb direction in
 * xz, `runM` the length of the run and `widthM` its width across.
 *
 * The two landing heights are the ends of the ramp: at `at` the figure stands
 * at `footY`, `runM` metres along at `headY`. That is the same pair
 * `StairLink` carries, said in the run's frame.
 */
export interface StairRun {
  at: { x: number; z: number };
  /** climb direction in world xz; normalised here, so it need not be unit */
  dir: { x: number; z: number };
  runM: number;
  widthM: number;
  footY: number;
  headY: number;
}

/**
 * Height of a figure standing at `x`/`z` ON this flight — `null` when it is
 * not on it (more than half a width off the run's axis).
 *
 * A RAMP, not a stair-step function (ruling, plan-treppen-v2 § 7a): the figure
 * walks the flight with a walking clip, and quantising the height to the
 * treads would make it bounce fifteen times per storey for no gain — the
 * treads are 26 cm of run and 20 cm of rise, so the ramp never leaves a
 * tread by more than a centimetre of sole.
 *
 * ALONG the axis the projection is CLAMPED, and that is deliberate: the two
 * landings lie past the ends of the run (pad gap plus half a pad), so a figure
 * standing on one gets its landing height instead of an extrapolated one, and
 * the answer stays continuous with the floor it steps onto. ACROSS the axis
 * there is no clamp but a gate: half a step width to either side is the
 * flight, everything beyond is floor somebody else has to answer for.
 */
export function stairY(flight: StairRun, x: number, z: number): number | null {
  const len = Math.hypot(flight.dir.x, flight.dir.z);
  if (!(len > 0) || !(flight.runM > 0)) return null;    // degenerate = no flight
  const dx = flight.dir.x / len, dz = flight.dir.z / len;
  const px = x - flight.at.x, pz = z - flight.at.z;
  // The axis normal in xz — the sign does not matter, only the distance.
  const across = px * -dz + pz * dx;
  if (Math.abs(across) > flight.widthM / 2) return null;
  const t = Math.min(1, Math.max(0, (px * dx + pz * dz) / flight.runM));
  return flight.footY + t * (flight.headY - flight.footY);
}

/**
 * The height of a guided ride over a CHAIN of flights: the answer of the
 * flight the figure is on, or `null` when it is on none of them.
 *
 * A chain over two storeys walks two flights, and where a stairwell stacks
 * them the same xz lies on both — so the tie is broken by the height the
 * figure is at: the ramp whose answer is NEAREST to `y` is the one it is
 * climbing. Equal answers make the choice moot, and the first flight wins so
 * that the same list always answers the same way.
 */
export function stairRideY(
  runs: readonly StairRun[],
  x: number,
  z: number,
  y: number,
): number | null {
  let best: number | null = null;
  let bestGap = Infinity;
  for (const run of runs) {
    const at = stairY(run, x, z);
    if (at === null) continue;
    const gap = Math.abs(at - y);
    if (gap >= bestGap) continue;
    best = at;
    bestGap = gap;
  }
  return best;
}

/**
 * Room the climb ends in: the one of `level` whose centre lies NEAREST the
 * landing stepped off onto. The rule of `elevatorTargetRoom`, only measured
 * from a landing instead of a lift stop — including the tie to the LOWER id,
 * so the destination of a symmetric floor cannot flicker between two rooms.
 *
 * `null` means the storey has no room the server could be asked for, and the
 * caller must not offer the ride at all — the same reason `elevatorLevels`
 * drops a storey without rooms.
 */
export function nearestRoomAt(
  level: number,
  pos: { x: number; z: number },
  rooms: readonly { id: string; level: number; center: { x: number; z: number } }[],
): string | null {
  let best: string | null = null;
  let bestDist = Infinity;
  for (const r of rooms) {
    if (r.level !== level) continue;
    const dist = Math.hypot(r.center.x - pos.x, r.center.z - pos.z);
    if (dist < bestDist || (dist === bestDist && best !== null && r.id < best)) {
      best = r.id;
      bestDist = dist;
    }
  }
  return best;
}
