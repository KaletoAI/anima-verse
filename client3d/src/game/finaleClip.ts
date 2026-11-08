/**
 * The FINALE of a running action (schnittstellen-3d.md § A8c) as the renderer
 * plays it — one participant's closing clip, `loop_count` cycles (1 = once),
 * then back to the action's own clip.
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
 *
 * CYCLES. `duration_s` is the WHOLE finale; a counted loop (`loop_count` N)
 * plays N cycles of `duration_s / N` each. The time handed out is the time IN
 * the current cycle, with `loop` true while a further cycle follows — so the
 * mixer repeats — and false in the last one, which holds its end like a
 * one-shot instead of wrapping to frame 0 for a frame before the finale ends.
 */

/** A clip role of a pair or group (§ A8a): `a`..`e`. */
export type FinaleRole = 'a' | 'b' | 'c' | 'd' | 'e';
const FINALE_ROLES: readonly string[] = ['a', 'b', 'c', 'd', 'e'];
/** An alt name (§ A8a, G6): lowercase letters, digits, `-`. */
const ALT_RE = /^[a-z0-9][a-z0-9-]*$/;

/** The worldmap row's `finale` block (§ A8c). */
export interface FinaleBlock {
  id: string;
  kind: string;
  role: FinaleRole | null;
  /** the ALT half of `role` the finale closes in (G6); "" or missing = none */
  alt?: string;
  elapsed_s: number;
  /** the whole finale, every cycle */
  duration_s: number;
  /** cycles of the clip; missing or not a whole number >= 1 = one */
  loop_count?: number;
}

/** A finale this figure is playing: `t` real seconds into a finale of
 *  `duration` (all `loopCount` cycles). */
export interface FinalePlay {
  id: string;
  kind: string;
  role: FinaleRole | null;
  /** "" = the role's own half */
  alt: string;
  t: number;
  duration: number;
  /** cycles of the clip, >= 1 */
  loopCount: number;
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
    const role = block.role && FINALE_ROLES.includes(block.role) ? block.role : null;
    // an alt only names a half of a ROLE — a solo finale has none
    const alt = role && typeof block.alt === 'string' && ALT_RE.test(block.alt) ? block.alt : '';
    const n = block.loop_count;
    const loopCount = typeof n === 'number' && Number.isInteger(n) && n >= 1 ? n : 1;
    play = { id: block.id, kind: block.kind, role, alt, t: 0, duration, loopCount };
  }
  return { play, seen: block.id };
}

/** One frame: advance by `dt` unless frozen and say which clip plays at which
 *  time — `<kind>__<role>` for a pair half, `<kind>__<role>~<alt>` for an
 *  alt half, `<kind>` for a solo clip — or null once the finale is over (the
 *  figure is back in the action's clip). `base` is the role's own half: what
 *  a rig without the alt half plays instead (`clip` itself when there is no
 *  alt). `t` is the time IN the current cycle and stays a millisecond short
 *  of the cycle's end, like a one-shot seek in `playPair`; `loop` says
 *  whether another cycle follows (the mixer repeats) or this is the last
 *  (it holds). */
export function stepFinale(play: FinalePlay | null, dt: number, frozen: boolean):
  { play: FinalePlay | null; clip: string | null; base: string | null; t: number; loop: boolean } {
  if (!play) return { play: null, clip: null, base: null, t: 0, loop: false };
  const t = play.t + (frozen || !(dt > 0) ? 0 : dt);
  if (t >= play.duration) return { play: null, clip: null, base: null, t: 0, loop: false };
  const next = { ...play, t };
  const base = play.role ? `${play.kind}__${play.role}` : play.kind;
  const cycles = play.loopCount >= 1 ? Math.floor(play.loopCount) : 1;
  const cycle = play.duration / cycles;
  const index = Math.min(cycles - 1, Math.floor(t / cycle));
  return { play: next, clip: play.role && play.alt ? `${base}~${play.alt}` : base, base,
    t: Math.min(t - index * cycle, cycle - 1e-3), loop: index < cycles - 1 };
}
