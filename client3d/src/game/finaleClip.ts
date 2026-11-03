/**
 * The FINALE of a running action (schnittstellen-3d.md § A8c) as the renderer
 * plays it — one participant's closing clip, once, then back to the action's
 * own clip.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM, no imports — `client3d/scripts/smoke_finale_clip.mjs`
 * transpiles the file and checks it with hand-derived numbers.
 *
 * THE RULE. The clips last about a second, a bystander's worldmap poll comes
 * every 3 s: a client plays the clip ONCE PER `id`, FROM ITS START, the first
 * time it sees the block — not from the server's `elapsed_s`, which would
 * mostly show nothing. Its own clock runs on the frame time and stands while
 * the world is frozen, exactly like the pair clip next to it. At its length
 * the finale is over and the figure is back in the action's clip, whose own
 * phase never stopped counting. The action ending ends the finale too.
 */

/** A clip role of a pair or group (§ A8a): `a`..`e`. */
export type FinaleRole = 'a' | 'b' | 'c' | 'd' | 'e';
const FINALE_ROLES: readonly string[] = ['a', 'b', 'c', 'd', 'e'];

/** The worldmap row's `finale` block (§ A8c). */
export interface FinaleBlock {
  id: string;
  kind: string;
  role: FinaleRole | null;
  elapsed_s: number;
  duration_s: number;
}

/** A finale this figure is playing: `t` real seconds into a clip of `duration`. */
export interface FinalePlay {
  id: string;
  kind: string;
  role: FinaleRole | null;
  t: number;
  duration: number;
}

/** Take a poll's block. A NEW id (not `seen`) starts from 0 whatever its
 *  `elapsed_s`; the same id never restarts, even after it ended; a junk
 *  block (no id, no positive length) starts nothing but is still marked seen
 *  when it has an id. `inAction` false (no interaction, no place) ends any
 *  running finale. */
export function adoptFinale(current: FinalePlay | null, seen: string,
  block: FinaleBlock | null | undefined, inAction: boolean): { play: FinalePlay | null; seen: string } {
  let play = inAction ? current : null;
  if (!block || typeof block.id !== 'string' || !block.id || block.id === seen) return { play, seen };
  const duration = Number(block.duration_s);
  if (inAction && block.kind && Number.isFinite(duration) && duration > 0) {
    play = { id: block.id, kind: block.kind, role: block.role && FINALE_ROLES.includes(block.role) ? block.role : null,
      t: 0, duration };
  }
  return { play, seen: block.id };
}

/** One frame: advance by `dt` unless frozen and say which clip plays at which
 *  time — `<kind>__<role>` for a pair half, `<kind>` for a solo clip — or
 *  null once the finale is over (the figure is back in the action's clip).
 *  The time handed out stays a millisecond short of the end, like a one-shot
 *  seek in `playPair`. */
export function stepFinale(play: FinalePlay | null, dt: number, frozen: boolean):
  { play: FinalePlay | null; clip: string | null; t: number } {
  if (!play) return { play: null, clip: null, t: 0 };
  const t = play.t + (frozen || !(dt > 0) ? 0 : dt);
  if (t >= play.duration) return { play: null, clip: null, t: 0 };
  const next = { ...play, t };
  return { play: next, clip: play.role ? `${play.kind}__${play.role}` : play.kind,
    t: Math.min(t, play.duration - 1e-3) };
}
