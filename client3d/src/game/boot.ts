/**
 * How far the start has come — the data behind the loading screen (stage 4,
 * task 3).
 *
 * `startApp` in `main.ts` does four things that take real time, and until they
 * are through there is nothing on screen but an empty canvas. This module is
 * the channel between "the app is loading X" and the title screen that draws
 * it: `main.ts` calls `reportBootStage` at the four points it actually reaches,
 * `TitleScreen` subscribes and renders.
 *
 * DELIBERATELY NOT ON THE HUD BUS (`hud/bus.ts`): that bus carries GAME state
 * of a running world (selection, mode, elevator) and is written by three known
 * owners. Boot progress exists only before the game does and is gone once the
 * title fades — mixing it in would put a field into every HUD snapshot that is
 * dead for the whole session. Same shape though (snapshot + listeners), so the
 * React side reads it with `useSyncExternalStore` exactly like the other one.
 *
 * The arithmetic is pure and dependency-free; the hand-derived cases live in
 * `client3d/scripts/smoke_walk_math.mjs`.
 */

/** One thing `startApp` waits for, in the order it reaches them. */
export type BootStage = 'world' | 'figures' | 'scenes' | 'tiles';

/** The stages in progress order. The order is what the LABEL is derived from —
 *  the first one still missing is what the client is working on. */
export const BOOT_STAGES: readonly BootStage[] = ['world', 'figures', 'scenes', 'tiles'];

export interface BootProgress {
  /** 0…100, in steps of 25 — one step per finished stage. */
  percent: number;
  /** the first stage still missing, or `'ready'` when all four are through */
  label: BootStage | 'ready';
}

/**
 * Turn the set of finished stages into what the loading screen draws.
 *
 * Counting and labelling are independent on purpose: `percent` counts how many
 * of the four are through (anything that is not a stage counts for nothing, so
 * a typo can never push the bar past 100 %), while `label` names the first
 * stage of `BOOT_STAGES` that is still missing. A set of `{figures}` is
 * therefore 25 % done and still waiting for `world` — which is exactly right,
 * because the stages finish in their own time and only the first hole says
 * what is being waited FOR.
 */
export function bootProgress(done: ReadonlySet<string>): BootProgress {
  let count = 0;
  let label: BootStage | 'ready' = 'ready';
  for (const stage of BOOT_STAGES) {
    if (done.has(stage)) count += 1;
    else if (label === 'ready') label = stage;
  }
  return { percent: count * 25, label };
}

/**
 * Something is wrong and the screen has to say so. Carried as a VALUE and not
 * as a finished sentence: the vanilla side (`main.ts`) has no `t()`, so a
 * string set here would be the one untranslatable line on the screen.
 * `TitleScreen` turns it into words.
 */
export type BootNote =
  /** the server did not answer; the next attempt is in `seconds` */
  | { kind: 'retry'; seconds: number }
  /** `startApp` threw — the page has to be reloaded */
  | { kind: 'failed' };

export interface BootState extends BootProgress {
  /** what the screen shows below the bar, or `null` while all is well */
  note: BootNote | null;
}

const done = new Set<BootStage>();
const listeners = new Set<() => void>();
let note: BootNote | null = null;
let snapshot: BootState = { ...bootProgress(done), note };

function publish(): void {
  snapshot = { ...bootProgress(done), note };
  for (const fn of listeners) fn();
}

/** Two notes that say the same thing must not publish twice — the retry loop
 *  sets the same wait over and over once the backoff is capped. */
function sameNote(a: BootNote | null, b: BootNote | null): boolean {
  if (a === null || b === null) return a === b;
  if (a.kind !== b.kind) return false;
  return a.kind !== 'retry' || a.seconds === (b as { seconds: number }).seconds;
}

/**
 * `startApp` reports a finished stage. Idempotent: a stage that is already
 * through changes nothing and notifies nobody — stages only ever complete,
 * they are never taken back, so there is no "undo" argument to pass.
 */
export function reportBootStage(stage: BootStage): void {
  if (done.has(stage)) return;
  done.add(stage);
  publish();
}

/** Set (or with `null` clear) the line below the bar. */
export function setBootNote(next: BootNote | null): void {
  if (sameNote(note, next)) return;
  note = next;
  publish();
}

/** For React's `useSyncExternalStore`: a stable snapshot per change. */
export function getBootState(): BootState { return snapshot; }

export function subscribeBoot(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
