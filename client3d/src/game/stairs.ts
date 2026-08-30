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

/** The RUN of a flight, world metres: `at` is the foot of the first tread (NOT
 *  the foot landing, which lies a pad's half plus a gap behind it), `dir` the
 *  climb direction in xz, `runM` the length of the run and `widthM` its width
 *  across. No heights — those are the flight's two landings, said once. */
export interface StairRun {
  at: { x: number; z: number };
  /** climb direction in world xz; normalised where it is used, so it need not
   *  be unit */
  dir: { x: number; z: number };
  runM: number;
  widthM: number;
}

/** ONE flight: the two landings it connects and the run between them.
 *  `foot.level + 1 === head.level` by construction — a flight never spans two
 *  storeys. */
export interface StairLink {
  foot: StairEndPoint;
  head: StairEndPoint;
  run: StairRun;
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
  /** Distance to the landing STOOD AT (world metres, XZ) — not to `dest`. The
   *  F key answers the nearest of all standing offers (`game/offers.ts`), and
   *  the reaches differ in size, so the measured metres travel with the
   *  offer instead of being measured a second time by the caller. */
  dist: number;
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
      best = { dir, dest: there, dist };
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
 * Height of a figure standing at `x`/`z` ON this flight — `null` when it is
 * not on it (more than half a width off the run's axis).
 *
 * A RAMP, not a stair-step function (ruling, plan-treppen-v2 § 7a): the figure
 * walks the flight with a walking clip, and quantising the height to the
 * treads would make it bounce fifteen times per storey for no gain. The price
 * is stated rather than hidden: the server's tread `i` covers the run from
 * `i·tread` to `(i+1)·tread` with its top face at `(i+1)·rise`, so the ramp
 * runs a FULL RISE under the tread at its near edge (0.205 m on the contract
 * flight), meets it at the far edge and lies about half a rise under it on
 * average. The sole cuts through the nosings, and that is accepted.
 *
 * ALONG the axis the projection is CLAMPED, and that is deliberate: the two
 * landings lie past the ends of the run (pad gap plus half a pad), so a figure
 * standing on one gets its landing height instead of an extrapolated one, and
 * the answer stays continuous with the floor it steps onto. ACROSS the axis
 * there is no clamp but a gate: half a step width to either side is the
 * flight, everything beyond is floor somebody else has to answer for.
 */
export function stairY(flight: StairLink, x: number, z: number): number | null {
  const run = flight.run;
  const len = Math.hypot(run.dir.x, run.dir.z);
  if (!(len > 0) || !(run.runM > 0)) return null;       // degenerate = no flight
  const dx = run.dir.x / len, dz = run.dir.z / len;
  const px = x - run.at.x, pz = z - run.at.z;
  // The axis normal in xz — the sign does not matter, only the distance.
  const across = px * -dz + pz * dx;
  if (Math.abs(across) > run.widthM / 2) return null;
  const t = Math.min(1, Math.max(0, (px * dx + pz * dz) / run.runM));
  return flight.foot.y + t * (flight.head.y - flight.foot.y);
}

// --- The RIDE: which flight, and from when on (review round 1) -------------
//
// A climb is not "somewhere on a staircase" but a SEQUENCE: the figure walks
// to a landing, climbs that flight to its far landing, and over two storeys
// does it again. Two things fall out of that and neither can be measured from
// xz alone, because a stairwell may stack two flights over the SAME footprint
// (same `at`, same direction, one storey apart — the server builds it and the
// plate holes are cut for it):
//
//   - WHICH flight answers: the leg being walked, never the nearest height.
//     Proximity in y cannot tell a stack apart at the moment of the change,
//     where both flights meet at the same landing height.
//   - FROM WHEN it answers: only once the figure has REACHED that leg's start
//     landing. The way to a flight regularly crosses its own footprint — the
//     walk from the first flight's head landing back to the second flight's
//     foot runs the whole length of the second run — and a ramp answering
//     there would lift the figure into the air under the stairs.

/** How close to a landing a figure has to be for the ride to count it as
 *  reached, world metres, measured in ALL THREE axes: over a stairwell the
 *  landings of two legs stand over each other and only the storey tells them
 *  apart. Smaller than the server's landing offset `STAIR_PAD_M/2 +
 *  STAIR_PAD_GAP_M` = 0.5 m by construction (pinned in the smoke), so the
 *  radius around a landing can never reach into the run itself. It is also
 *  the radius `scene/npcs.ts` retires waypoints at during a ride, which is
 *  what makes a chain's landings the points the figure really walks onto. */
export const RIDE_ARRIVE_M = 0.4;

/** ONE leg of a guided climb: the flight walked and the two landings it is
 *  walked between — `start` arms the ramp, `end` retires the leg. */
export interface StairLeg {
  flight: StairLink;
  start: StairEndPoint;
  end: StairEndPoint;
}

/**
 * A guided climb as the walking machine holds it. `leg` is the one being
 * walked and `armed` says the figure has reached that leg's start landing —
 * before that the ride answers nothing and the floor keeps the figure.
 *
 * The avatar's own ride starts ARMED: it accepted the offer while standing at
 * the landing (`stairsAt` only offers within reach of one). An NPC's chain
 * starts unarmed, because the figure is still a room away and walks to the
 * foot of the flight first.
 */
export interface StairRide {
  legs: StairLeg[];
  leg: number;
  armed: boolean;
}

/** Is this landing that landing? Storey FIRST — a stacked stairwell has two
 *  landings over the same xz — then the point, with a hair of tolerance
 *  because both sides are copies of the same payload numbers. */
function sameLanding(a: StairEndPoint, b: StairEndPoint): boolean {
  return a.level === b.level && Math.abs(a.x - b.x) < 1e-6
    && Math.abs(a.y - b.y) < 1e-6 && Math.abs(a.z - b.z) < 1e-6;
}

/**
 * What a ride answers for a figure at `x`/`y`/`z`: the leg it is on now,
 * whether that leg's ramp has taken over, the height (`null` = the floor
 * answers) and whether the ride is over.
 *
 * Pure — the caller writes `leg`/`armed` back and drops the ride on `done`.
 * The loop is a loop and not an `if` because a leg can be finished before it
 * begins: a chain whose next flight starts where the last one ended arms and
 * retires in the same frame, and the ride must not stall on it.
 */
export function rideStep(
  ride: StairRide,
  x: number,
  y: number,
  z: number,
): { leg: number; armed: boolean; y: number | null; done: boolean } {
  const at = (p: StairEndPoint) =>
    Math.hypot(p.x - x, p.y - y, p.z - z) < RIDE_ARRIVE_M;
  let leg = ride.leg;
  let armed = ride.armed;
  while (leg < ride.legs.length) {
    const cur = ride.legs[leg];
    if (!armed && at(cur.start)) armed = true;
    // Only an ARMED leg can end: the end landing of a stacked leg lies over
    // its own start, and a ride that ended there would skip the flight.
    if (armed && at(cur.end)) {
      leg += 1;
      armed = false;
      continue;
    }
    break;
  }
  if (leg >= ride.legs.length) return { leg, armed, y: null, done: true };
  return {
    leg,
    armed,
    y: armed ? stairY(ride.legs[leg].flight, x, z) : null,
    done: false,
  };
}

/**
 * The ONE leg that ends on this landing: the flight that HAS it, walked from
 * its other end. That is the avatar's climb — it stands at one landing and
 * rides to the other — and the search is by landing, not by storey, so a
 * stacked pair cannot hand back the wrong flight.
 */
export function stairLegTo(
  links: readonly StairLink[],
  dest: StairEndPoint,
): StairLeg | null {
  for (const flight of links) {
    if (sameLanding(flight.head, dest)) return { flight, start: flight.foot, end: dest };
    if (sameLanding(flight.foot, dest)) return { flight, start: flight.head, end: dest };
  }
  return null;
}

/**
 * The legs of a `stairChain`: the chain is landing PAIRS (near end, far end
 * per flight), so each pair names its own flight — matched on BOTH landings,
 * in either order, which is what keeps a climb over a stacked stairwell on
 * the flight it is actually walking. A pair no flight owns is skipped rather
 * than guessed at.
 */
export function stairLegs(
  links: readonly StairLink[],
  chain: readonly StairEndPoint[],
): StairLeg[] {
  const legs: StairLeg[] = [];
  for (let i = 0; i + 1 < chain.length; i += 2) {
    const [a, b] = [chain[i], chain[i + 1]];
    const flight = links.find((s) =>
      (sameLanding(s.foot, a) && sameLanding(s.head, b))
      || (sameLanding(s.head, a) && sameLanding(s.foot, b)));
    if (flight) legs.push({ flight, start: a, end: b });
  }
  return legs;
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
