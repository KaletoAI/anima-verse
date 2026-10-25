/** Shared polling state machine. The host owns the clock and visibility events. */
export type SyncTopic = 'presence' | 'scene' | 'notices' | 'self' | 'world';
export interface EndpointSpec {
  intervalMs: number;
  pushedIntervalMs?: number;
  minSpacingMs?: number;
  topics?: SyncTopic[];
  runHidden?: boolean;
}
export interface PollEnv {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(h: unknown): void;
  hidden(): boolean;
}
export interface HubLike {
  connected(): boolean;
  generation(): number;
  onTopics(topics: SyncTopic[], fn: () => void): () => void;
  onState(fn: () => void): () => void;
}
export interface PollCore {
  subscribe(key: string, fetcher: () => Promise<unknown>, spec: EndpointSpec,
    cb: (data: unknown, error: unknown) => void): () => void;
  /** Resolves void after completion, or when the last subscriber leaves. */
  refresh(key: string): Promise<void>;
  signal(key: string): void;
  tick(): void;
  visible(): void;
}
export const TICK_MS = 1000;
export const MAX_BACKOFF_MS = 60_000; // Bound retries while keeping slow endpoints slow.
/** Highest error multiplier: 1, 2, 4 … 64, doubled per failed request. */
export const MAX_ERROR_FACTOR = 64;

/**
 * The time between two polls of one entry, in ms: the base interval stretched
 * by the error factor, but never past `max(base, MAX_BACKOFF_MS)` (a slow
 * endpoint stays slow, a fast one backs off to a minute at most), and never
 * below the entry's minimum spacing. Pure, so the native client checks the
 * same schedule against `shared/test-vectors/poll_schedule.json`.
 */
export function pollIntervalMs(baseMs: number, minSpacingMs: number, errorFactor: number): number {
  return Math.max(minSpacingMs, Math.min(baseMs * errorFactor, Math.max(baseMs, MAX_BACKOFF_MS)));
}

/** The error factor after a request: back to 1 on success, doubled on a
 *  failure up to `MAX_ERROR_FACTOR`. */
export function nextErrorFactor(factor: number, ok: boolean): number {
  return ok ? 1 : Math.min(factor * 2, MAX_ERROR_FACTOR);
}
interface Sub {
  fetcher: () => Promise<unknown>;
  spec: EndpointSpec;
  cb: (data: unknown, error: unknown) => void;
}
interface Entry {
  subs: Set<Sub>;
  lastStart: number;
  inFlight: Promise<void> | null;
  dirty: boolean;
  trailing: unknown;
  errorFactor: number;
  lastData: unknown;
  lastError: unknown;
  hasData: boolean;
  dataGen: number;
  offTopics: (() => void) | null;
  refreshPending: boolean;
  waiters: Array<() => void>;
  runningWaiters: Array<() => void>;
}
export function createPollCore(env: PollEnv, hub: HubLike | null): PollCore {
  const entries = new Map<string, Entry>();
  const generation = () => hub?.generation() ?? 0;
  let gen = generation();
  const spacing = (e: Entry) => Math.max(0, ...[...e.subs].map(s => s.spec.minSpacingMs ?? 0));
  const interval = (e: Entry) => {
    const base = Math.min(...[...e.subs].map(s => hub?.connected()
      ? (s.spec.pushedIntervalMs ?? s.spec.intervalMs) : s.spec.intervalMs));
    return pollIntervalMs(base, spacing(e), e.errorFactor);
  };
  const hidden = (e: Entry) => env.hidden() && ![...e.subs].some(s => s.spec.runHidden);
  function cancelTrailing(e: Entry) {
    if (e.trailing != null) env.clearTimeout(e.trailing);
    e.trailing = null;
  }
  function notify(s: Sub, e: Entry) {
    try { s.cb(e.lastData, e.lastError); }
    catch (error) { console.error("Polling subscriber failed", error); }
  }
  function signal(e: Entry): void {
    e.dirty = true;
    if (!e.subs.size) return;
    if (hidden(e) || e.inFlight) { e.dirty = true; return; }
    const delay = e.lastStart + spacing(e) - env.now();
    if (delay <= 0) { void run(e); return; }
    if (e.trailing == null) e.trailing = env.setTimeout(() => {
      e.trailing = null;
      signal(e);
    }, delay);
  }
  function run(e: Entry): Promise<void> {
    if (e.inFlight) return e.inFlight;
    const subs = [...e.subs];
    const sub = subs[subs.length - 1];
    if (!sub) return Promise.resolve();
    cancelTrailing(e);
    e.dirty = false;
    e.lastStart = env.now();
    const startedGen = generation();
    // Capture refresh waiters at start: callers arriving during this request
    // must wait for the following request, rather than this one's completion.
    const waiters = e.waiters.splice(0);
    e.runningWaiters = waiters;
    e.refreshPending = false;
    let fetched: Promise<unknown>;
    try { fetched = Promise.resolve(sub.fetcher()); }
    catch (error) { fetched = Promise.reject(error); }
    e.inFlight = fetched.then(data => {
      if (generation() !== startedGen) return;
      e.lastData = data; e.lastError = null; e.hasData = true;
      e.dataGen = startedGen; e.errorFactor = nextErrorFactor(e.errorFactor, true);
    }, error => {
      if (generation() !== startedGen) return;
      e.lastError = error; e.dataGen = startedGen; e.errorFactor = nextErrorFactor(e.errorFactor, false);
    }).then(() => {
      e.inFlight = null;
      e.runningWaiters = [];
      if (generation() !== startedGen) {
        e.dirty = true;
        if (e.subs.size) e.waiters.unshift(...waiters.splice(0));
        else for (const resolve of waiters.splice(0)) resolve();
      } else {
        for (const s of [...e.subs]) if (e.subs.has(s)) notify(s, e);
        for (const resolve of waiters.splice(0)) resolve();
      }
      if (e.refreshPending && e.subs.size) void run(e);
      else if (e.dirty) signal(e);
    });
    return e.inFlight;
  }
  function bind(e: Entry) {
    e.offTopics?.();
    const topics = [...new Set([...e.subs].flatMap(s => s.spec.topics ?? []))];
    e.offTopics = topics.length && hub ? hub.onTopics(topics, () => signal(e)) : null;
  }
  hub?.onState(() => {
    const next = generation();
    if (next === gen) return; // Intervals are computed from live hub state.
    gen = next;
    for (const e of entries.values()) {
      e.lastData = null; e.lastError = null; e.hasData = false; e.dirty = true;
      if (![...e.subs].some(s => s.spec.topics?.length)) signal(e);
    }
  });
  return {
    subscribe(key, fetcher, spec, cb) {
      let e = entries.get(key);
      if (!e) {
        e = { subs: new Set(), lastStart: -Infinity, inFlight: null, dirty: false,
          trailing: null, errorFactor: 1, lastData: null, lastError: null,
          hasData: false, dataGen: gen, offTopics: null, refreshPending: false, waiters: [], runningWaiters: [] };
        entries.set(key, e);
      }
      const sub = { fetcher, spec, cb };
      e.subs.add(sub);
      bind(e);
      if (e.dataGen === generation() && (e.hasData || e.lastError !== null)) notify(sub, e);
      if (!e.inFlight && (e.dirty || !e.hasData || e.dataGen !== generation())) signal(e);
      return () => {
        e.subs.delete(sub);
        bind(e);
        if (!e.subs.size) {
          if (e.trailing != null) e.dirty = true;
          cancelTrailing(e);
          e.refreshPending = false;
          for (const resolve of [...e.waiters.splice(0), ...e.runningWaiters.splice(0)]) resolve();
        }
      };
    },
    refresh(key) {
      const e = entries.get(key);
      if (!e?.subs.size) return Promise.resolve();
      const done = new Promise<void>(resolve => e.waiters.push(resolve));
      if (e.inFlight) { e.dirty = true; e.refreshPending = true; }
      else void run(e);
      return done;
    },
    signal(key) { const e = entries.get(key); if (e) signal(e); },
    tick() {
      for (const e of entries.values()) {
        if (!e.subs.size || e.inFlight || env.now() - e.lastStart < interval(e)) continue;
        if (hidden(e)) e.dirty = true;
        else void run(e);
      }
    },
    visible() {
      for (const e of entries.values()) {
        if (e.subs.size && (e.dirty || env.now() - e.lastStart >= interval(e))) signal(e);
      }
    },
  };
}
