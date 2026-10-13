/**
 * How far the start has come — the data behind the loading screen (stage 4,
 * task 3).
 *
 * `startApp` in `main.ts` does a handful of things that take real time, and
 * until they are through there is nothing on screen but an empty canvas — or,
 * worse, a world the player may already walk in while the ground under their
 * avatar is still being loaded. This module is the channel between "the app is
 * loading X" and the title screen that draws it: `main.ts` calls
 * `reportBootStage` at the points it actually reaches, `TitleScreen`
 * subscribes and renders.
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

/** One measured checkpoint of `startApp`; completion may be out of order. */
export type BootStage = 'world' | 'scenes' | 'tiles' | 'visible' | 'figures' | 'arrival';

/** The stages in progress order: world, scenes, tiles, visible, figures, arrival.
 *  `visible` is the first frame after the arrival location mounts with ground
 *  and HUD present. Completion may occur out of this display order. The order is what the LABEL is derived from —
 *  the first one still missing is what the client is working on.
 *
 *  `arrival` is the LAST one and it is the one the avatar depends on: the
 *  scene of the location the player wakes up in is mounted, its interior is
 *  open, the figure stands on its room's floor and only then is the mode —
 *  and with it the steering — handed over. Before it existed the bar hit
 *  100 % at `tiles`, while every building model was still streaming in, and
 *  the avatar was placed against a tile that had no rooms yet: it stood on the
 *  plot instead of in its room, and walking in those seconds reported that
 *  wrong point to the server. */
export const BOOT_STAGES: readonly BootStage[] =
  ['world', 'scenes', 'tiles', 'visible', 'figures', 'arrival'];

export interface BootProgress {
  /** 0…100, one equal step per finished stage (`100 / BOOT_STAGES.length`). */
  percent: number;
  /** the first stage still missing, or `'ready'` when all of them are through */
  label: BootStage | 'ready';
}

/**
 * Turn the set of finished stages into what the loading screen draws.
 *
 * Counting and labelling are independent on purpose: `percent` counts how many
 * of the stages are through (anything that is not a stage counts for nothing,
 * so a typo can never push the bar past 100 %), while `label` names the first
 * stage of `BOOT_STAGES` that is still missing. A set of `{figures}` is
 * therefore one step done and still waiting for `world` — which is exactly
 * right, because the stages finish in their own time and only the first hole
 * says what is being waited FOR.
 *
 * The step is DERIVED from the stage count, never a written-out number: adding
 * a stage must not leave a bar that stops at 80 % or runs past 100 %. Rounded,
 * so the last stage lands on exactly 100 whatever the count is.
 */
export function bootProgress(done: ReadonlySet<string>): BootProgress {
  let count = 0;
  let label: BootStage | 'ready' = 'ready';
  for (const stage of BOOT_STAGES) {
    if (done.has(stage)) count += 1;
    else if (label === 'ready') label = stage;
  }
  return { percent: Math.round((count * 100) / BOOT_STAGES.length), label };
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
  stages: readonly BootStage[];
}

const done = new Set<BootStage>();
const listeners = new Set<() => void>();
let note: BootNote | null = null;
let snapshot: BootState = { ...bootProgress(done), note, stages: BOOT_STAGES.filter((s) => done.has(s)) };

function publish(): void {
  snapshot = { ...bootProgress(done), note, stages: BOOT_STAGES.filter((s) => done.has(s)) };
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
  const now = performance.now();
  performance.mark('boot:' + stage);
  stageTimes[stage] = now - bootStart;
  publishReport();
  publish();
  scheduleObserverEnd();
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


export type BootPhase = 'clip:download' | 'clip:parse' | 'clip:fit'
  | 'model:download' | 'model:build' | 'scene:fetch' | 'arrival:mount'
  | 'ground:fetch' | 'ground:build';
export interface PhaseInterval { phase: BootPhase; start: number; end: number }
interface TaskEntry { startTime: number; duration: number }
export interface LongTaskSummary {
  count: number; totalMs: number; maxMs: number; maxPhase: BootPhase | null;
}
export interface BootReport {
  stages: Record<BootStage, number | null>;
  /** Summed elapsed durations of possibly concurrent runs; not wall-clock boot time. */
  phases: Record<BootPhase, number>;
  longTasks: LongTaskSummary | null;
  afterVisible: LongTaskSummary | null;
}

/** Largest overlap wins; ties go to the interval that started first. */
export function attributeLongTask(intervals: readonly PhaseInterval[], entry: TaskEntry): BootPhase | null {
  let best: PhaseInterval | null = null;
  let overlap = 0;
  for (const interval of intervals) {
    const amount = Math.min(interval.end, entry.startTime + entry.duration)
      - Math.max(interval.start, entry.startTime);
    if (amount > 0 && (amount > overlap
      || (amount === overlap && best !== null && interval.start < best.start))) {
      best = interval;
      overlap = amount;
    }
  }
  return best?.phase ?? null;
}

const stageTimes: Record<BootStage, number | null> = {
  world: null, scenes: null, tiles: null, visible: null, figures: null, arrival: null,
};
const phaseSums: Record<BootPhase, number> = {
  'clip:download': 0, 'clip:parse': 0, 'clip:fit': 0,
  'model:download': 0, 'model:build': 0, 'scene:fetch': 0,
  'arrival:mount': 0, 'ground:fetch': 0, 'ground:build': 0,
};
// Five seconds match the shader warm-up comparison window in P2 § 4.7.
const AFTER_VISIBLE_MS = 5000;
const intervals: PhaseInterval[] = [];
const tasks: TaskEntry[] = [];
const reportListeners = new Set<() => void>();
let bootStart = 0;
let measuring = false;
let observer: PerformanceObserver | null = null;
let observerTimer: ReturnType<typeof setTimeout> | null = null;
let supportsLongTasks = false;
let reportSnapshot: BootReport = {
  stages: { ...stageTimes }, phases: { ...phaseSums }, longTasks: null, afterVisible: null,
};

function summarize(entries: TaskEntry[]): LongTaskSummary {
  const result: LongTaskSummary = { count: entries.length, totalMs: 0, maxMs: 0, maxPhase: null };
  for (const entry of entries) {
    result.totalMs += entry.duration;
    if (entry.duration > result.maxMs) {
      result.maxMs = entry.duration;
      result.maxPhase = attributeLongTask(intervals, entry);
    }
  }
  return result;
}

function publishReport(): void {
  if (!measuring) return;
  for (const phase of Object.keys(phaseSums) as BootPhase[]) phaseSums[phase] = 0;
  const end = measurementEnd();
  for (const interval of intervals) {
    phaseSums[interval.phase] += Math.max(0, Math.min(interval.end, end, performance.now()) - interval.start);
  }
  const arrival = stageTimes.arrival;
  const visible = stageTimes.visible;
  reportSnapshot = {
    stages: { ...stageTimes }, phases: { ...phaseSums },
    longTasks: supportsLongTasks ? summarize(tasks.filter((e) =>
      e.startTime >= bootStart && (arrival === null || e.startTime <= bootStart + arrival))) : null,
    afterVisible: supportsLongTasks ? summarize(tasks.filter((e) => visible !== null
      && e.startTime >= bootStart + visible
      && e.startTime <= bootStart + visible + AFTER_VISIBLE_MS)) : null,
  };
  for (const fn of reportListeners) fn();
}

function collectTasks(entries: readonly PerformanceEntry[]): void {
  if (!measuring || entries.length === 0) return;
  for (const entry of entries) {
    if (entry.startTime >= bootStart) tasks.push({ startTime: entry.startTime, duration: entry.duration });
  }
  publishReport();
}

function printReport(): void {
  const r = reportSnapshot;
  const summary = (v: LongTaskSummary | null) => v === null ? 'n/a'
    : `${v.count} (${Math.round(v.totalMs)} ms, max ${Math.round(v.maxMs)} @${v.maxPhase ?? 'n/a'})`;
  console.info(`[boot] ${BOOT_STAGES.map((s) => `${s} ${r.stages[s] === null ? 'n/a' : Math.round(r.stages[s]!)}`).join(' · ')} ms | ${Object.entries(r.phases).map(([p, ms]) => `${p} ${Math.round(ms)}`).join(' · ')} | longtasks ${summary(r.longTasks)} | after-visible ${summary(r.afterVisible)}`);
}

function measurementEnd(): number {
  return stageTimes.arrival === null || stageTimes.visible === null ? Infinity
    : bootStart + Math.max(stageTimes.arrival, stageTimes.visible + AFTER_VISIBLE_MS);
}

function scheduleObserverEnd(): void {
  if (!measuring || stageTimes.arrival === null || stageTimes.visible === null) return;
  if (observerTimer !== null) clearTimeout(observerTimer);
  const end = bootStart + Math.max(stageTimes.arrival, stageTimes.visible + AFTER_VISIBLE_MS);
  observerTimer = setTimeout(() => {
    for (const interval of intervals) interval.end = Math.min(interval.end, end);
    if (observer) collectTasks(observer.takeRecords());
    publishReport();
    printReport();
    observer?.disconnect();
    observer = null;
    observerTimer = null;
    measuring = false;
  }, Math.max(0, end - performance.now()));
}

/** Begin at Enter/resume. Unsupported browsers deliberately keep null reports. */
export function markBootStart(): void {
  observer?.disconnect();
  observer = null;
  if (observerTimer !== null) clearTimeout(observerTimer);
  observerTimer = null;
  bootStart = performance.now();
  measuring = true;
  done.clear();
  note = null;
  for (const stage of BOOT_STAGES) stageTimes[stage] = null;
  for (const phase of Object.keys(phaseSums) as BootPhase[]) phaseSums[phase] = 0;
  intervals.length = 0;
  tasks.length = 0;
  supportsLongTasks = false;
  try {
    if (typeof PerformanceObserver !== 'undefined'
      && PerformanceObserver.supportedEntryTypes?.includes('longtask')) {
      observer = new PerformanceObserver((list) => collectTasks(list.getEntries()));
      observer.observe({ type: 'longtask', buffered: true });
      supportsLongTasks = true;
    }
  } catch {
    observer?.disconnect();
    observer = null;
  }
  publishReport();
  publish();
}

/** Record an already measured run, including its interval for attribution. */
export function markPhase(name: BootPhase, ms: number): void {
  if (!measuring) return;
  const now = performance.now();
  const end = Math.min(now, measurementEnd());
  const start = Math.max(bootStart, now - ms);
  if (end <= start) return;
  intervals.push({ phase: name, start, end });
  publishReport();
}

/** Keep the exact run interval, even if the operation rejects. */
export async function withPhase<T>(name: BootPhase, fn: () => Promise<T>): Promise<T> {
  if (!measuring || performance.now() >= measurementEnd()) return await fn();
  const interval: PhaseInterval = { phase: name, start: performance.now(), end: Infinity };
  intervals.push(interval);
  try { return await fn(); }
  finally {
    if (measuring && intervals.includes(interval)) {
      interval.end = Math.min(performance.now(), measurementEnd());
      publishReport();
    }
  }
}

/** Stable between changes, for React's external-store subscription. */
export function bootReport(): BootReport { return reportSnapshot; }
export function subscribeBootReport(fn: () => void): () => void {
  reportListeners.add(fn);
  return () => { reportListeners.delete(fn); };
}
