import type { HubLike, SyncTopic } from './pollCore';
const DEADLINE_MS = 35_000; // Maximum wait for a delivered frame.
const LATE_MS = 10_000; // Tolerance for an overdue deadline.
export interface EventSourceLike {
  onopen: ((e: unknown) => void) | null;
  onerror: ((e: unknown) => void) | null;
  onmessage: ((e: { data: string }) => void) | null;
  addEventListener(type: 'bye' | 'ping', fn: () => void): void;
  close(): void;
  readonly readyState: number;
}
export interface SyncHub extends HubLike {
  start(): void;
  restart(): void;
  invalidateBinding(): void;
}
export function createSyncHub(deps: {
  open(url: string): EventSourceLike;
  setTimeout(fn: () => void, ms: number): unknown;
  now?: () => number;
  url?: string;
}): SyncHub {
  const now = deps.now ?? Date.now;
  const listeners = new Set<{ topics: SyncTopic[]; fn: () => void }>();
  const states = new Set<() => void>();
  let source: EventSourceLike | null = null;
  let connected = false, stopped = false, seenResync = false, gen = 0;
  let retryMs = 5000, retryToken = 0, retryPending = false;
  const state = () => { for (const fn of [...states]) fn(); };
  const setConnected = (v: boolean) => { if (v !== connected) { connected = v; state(); } };
  const invalidate = () => {
    gen++;
    state();
    for (const l of [...listeners]) l.fn();
  };
  let deliveryToken = 0;
  function armDeadline(s: EventSourceLike, late = false) {
    const token = ++deliveryToken;
    const armedAt = now();
    deps.setTimeout(() => {
      if (token !== deliveryToken || source !== s) return;
      if (!late && now() - armedAt > DEADLINE_MS + LATE_MS) {
        // Suspension prevented frame delivery; allow one fresh window after wake.
        armDeadline(s, true);
        return;
      }
      source = null;
      s.close();
      setConnected(false);
      scheduleRetry();
    }, DEADLINE_MS);
  }
  function start() {
    if (stopped || source || retryPending) return;
    let s: EventSourceLike;
    try { s = deps.open(deps.url ?? '/events/sync'); }
    catch { scheduleRetry(); return; }
    source = s;
    armDeadline(s);
    s.onmessage = e => {
      if (source !== s) return;
      let frame: { topics?: unknown; resync?: unknown };
      try { frame = JSON.parse(e.data); } catch { return; }
      if (!frame || typeof frame !== 'object') return;
      armDeadline(s);
      if (frame.resync === true) {
        if (seenResync) invalidate();
        else { seenResync = true; for (const l of [...listeners]) l.fn(); }
        retryMs = 5000;
        setConnected(true);
      } else if (Array.isArray(frame.topics)) {
        const topics = frame.topics;
        for (const l of [...listeners]) if (l.topics.some(t => topics.includes(t))) l.fn();
      }
    };
    s.onerror = () => {
      if (source !== s) return;
      setConnected(false);
      if (s.readyState === 2) {
        source = null;
        s.close();
        scheduleRetry();
      }
    };
    s.addEventListener('ping', () => {
      if (source === s) armDeadline(s);
    });
    s.addEventListener('bye', () => {
      if (source !== s) return;
      stopped = true; retryToken++; retryPending = false;
      source = null; s.close(); setConnected(false);
    });
  }
  function scheduleRetry() {
    if (stopped || retryPending) return;
    retryPending = true;
    const token = ++retryToken;
    const delay = retryMs;
    retryMs = Math.min(60_000, retryMs * 2); // Avoid a tight loop after a closed/401 stream.
    deps.setTimeout(() => {
      if (token !== retryToken || stopped) return;
      retryPending = false;
      start();
    }, delay);
  }
  return {
    connected: () => connected,
    generation: () => gen,
    onTopics(topics, fn) {
      const listener = { topics, fn };
      listeners.add(listener); start();
      return () => { listeners.delete(listener); };
    },
    onState(fn) { states.add(fn); return () => { states.delete(fn); }; },
    start,
    restart() {
      invalidate();
      stopped = false; retryToken++; retryPending = false; retryMs = 5000;
      const old = source; source = null; old?.close();
      setConnected(false); start();
    },
    invalidateBinding: invalidate,
  };
}
let singleton: SyncHub | null = null;
export function syncHub(): SyncHub {
  if (!singleton) {
    if (typeof EventSource === 'undefined') {
      // No transport in SSR/tests; local binding invalidation still works.
      singleton = createSyncHub({ open: () => { throw new Error('EventSource unavailable'); }, setTimeout: () => null });
    } else singleton = createSyncHub({
      open: url => {
        const native = new EventSource(url);
        // Bridge DOM event types to the transport-independent interface.
        const transport: EventSourceLike = {
          onopen: null, onerror: null, onmessage: null,
          addEventListener: (type, fn) => native.addEventListener(type, fn),
          close: () => native.close(),
          get readyState() { return native.readyState; },
        };
        native.onopen = e => transport.onopen?.(e);
        native.onerror = e => transport.onerror?.(e);
        native.onmessage = e => transport.onmessage?.(e);
        return transport;
      },
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    });
  }
  return singleton;
}
