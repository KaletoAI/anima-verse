/**
 * Who the avatar may address by walking up to them (plan-3d-game stage 3,
 * task 5).
 *
 * Pure like `walk.ts`: no Three.js, no DOM, no module state and no import at
 * all — that is what lets `client3d/scripts/smoke_walk_math.mjs` transpile and check it
 * with hand-derived numbers.
 *
 * The rule has three parts, and the middle one is the one worth explaining:
 *  1. Same LOCATION. The place next door is a different place, however close
 *     the two figures happen to be drawn — footprints touch in the metre
 *     world (§ A1.1), so "close" says nothing by itself.
 *  2. Same SHOWN room — the room the 3D view is currently DRAWING (main.ts
 *     `shownRoom`), not the room the worldmap reports. With an interior open
 *     you stand a metre away from someone through a wall you can see, and the
 *     prompt must not fire through it. Outdoors both sides are `null`, which
 *     matches; one side `null` and the other a room does not.
 *  3. Within `TALK_RANGE`, SCALED BY THE FIGURE'S SCALE. This dates from the
 *     double scale: interiors drew their figures at a room scale, so a world
 *     metre in there was not a human metre and at scale 0.3 the reach was
 *     0.75 world metres. SINCE E4 THE FACTOR IS 1 — one world metre is one
 *     real metre everywhere (k = 1, § B), and `npcs.scaleOf` reads a group
 *     that nothing scales any more. The parameter is kept because the rule
 *     survives it unchanged; it is on the cleanup list, not a live dial.
 *
 * Distance is the plain XZ distance (a height difference does not gate a
 * conversation), the comparison is inclusive so the range itself still counts,
 * and of several candidates the NEAREST wins.
 */

/** Talking distance in human metres — multiplied by the figure scale. */
export const TALK_RANGE = 2.5;

/** Where the avatar stands. The `name` is here so the avatar can never be its
 *  own target: it sits in the same character list at distance 0 and would beat
 *  everyone, and that guard belongs in the tested function rather than in the
 *  caller's glue code. */
export interface TalkSelf {
  name: string;
  pos: { x: number; z: number };
  locId: string;
  /** room the 3D view currently DRAWS the figure in, null = outdoors */
  room: string | null;
}

/** A candidate, with the scale its figure is currently drawn at. */
export interface TalkCandidate extends TalkSelf {
  scale: number;
}

/**
 * Nearest addressable character, or null. Ties are broken by name so a figure
 * cannot flicker between two equally distant neighbours from one 1 Hz tick to
 * the next.
 */
export function talkTargetNear(avatar: TalkSelf, others: TalkCandidate[]): string | null {
  let best: string | null = null;
  let bestDist = Infinity;
  for (const o of others) {
    if (o.name === avatar.name) continue;
    if (o.locId !== avatar.locId) continue;
    if ((o.room ?? null) !== (avatar.room ?? null)) continue;
    const dx = o.pos.x - avatar.pos.x;
    const dz = o.pos.z - avatar.pos.z;
    const dist = Math.hypot(dx, dz);
    if (dist > TALK_RANGE * o.scale) continue;
    if (dist < bestDist || (dist === bestDist && best !== null && o.name < best)) {
      best = o.name;
      bestDist = dist;
    }
  }
  return best;
}
