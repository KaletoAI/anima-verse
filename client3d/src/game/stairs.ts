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
 * Whoever walks the chain needs nothing else. The waypoint machine in
 * `scene/npcs.ts` shifts to the next point at an XZ distance under 1.5 m and
 * blends the height exponentially towards the current one, so a foot point
 * followed by a head point already IS the climb — no ramp, no animation state,
 * no per-step geometry. The stairs themselves are the server's business
 * (`app/core/scene_recipe.py`), and this module never sees a step.
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
