/**
 * Central polling hub for the player UI (review section 8).
 *
 * Replaces the per-panel `setInterval` loops with ONE shared 1s base timer:
 *  - registrations fire when their own interval has elapsed
 *  - `document.visibilityState !== 'visible'` pauses all polling; returning
 *    to the tab refreshes every registration immediately
 *  - identical keys share a single in-flight fetch and its result (ref-count)
 *  - after a fetch error the effective interval doubles (max 60s) and resets
 *    on the next success
 *
 * Usage:
 *   const { data, error, refresh } = usePoll<MyPayload>(
 *     "queue-status", fetchQueueStatus, { intervalMs: 5000 });
 */
import { useCallback, useEffect, useRef, useState } from "react";

type Fetcher<T> = () => Promise<T>;

interface Entry {
  key: string;
  fetcher: Fetcher<unknown>;
  intervalMs: number;
  errorFactor: number; // 1, 2, 4, ... capped so interval*factor <= MAX_BACKOFF_MS
  lastRun: number; // epoch ms of last fetch start (0 = never)
  inFlight: boolean;
  subscribers: Set<(data: unknown, error: unknown) => void>;
  lastData: unknown;
  lastError: unknown;
}

const MAX_BACKOFF_MS = 60_000;
const TICK_MS = 1_000;

const entries = new Map<string, Entry>();
let timer: ReturnType<typeof setInterval> | null = null;
let visibilityHooked = false;

function effectiveInterval(e: Entry): number {
  return Math.min(e.intervalMs * e.errorFactor, MAX_BACKOFF_MS);
}

async function runEntry(e: Entry): Promise<void> {
  if (e.inFlight) return;
  e.inFlight = true;
  e.lastRun = Date.now();
  try {
    const data = await e.fetcher();
    e.lastData = data;
    e.lastError = null;
    e.errorFactor = 1;
  } catch (err) {
    e.lastError = err;
    // Double the effective interval up to the cap; keep factor bounded.
    if (e.intervalMs * e.errorFactor < MAX_BACKOFF_MS) e.errorFactor *= 2;
  } finally {
    e.inFlight = false;
  }
  for (const cb of e.subscribers) cb(e.lastData, e.lastError);
}

function tick(): void {
  if (typeof document !== "undefined" && document.visibilityState !== "visible") {
    return; // paused while the tab is hidden
  }
  const now = Date.now();
  for (const e of entries.values()) {
    if (e.subscribers.size === 0) continue;
    if (now - e.lastRun >= effectiveInterval(e)) void runEntry(e);
  }
}

function refreshAll(): void {
  for (const e of entries.values()) {
    if (e.subscribers.size === 0) continue;
    e.lastRun = 0; // due on next tick
  }
  tick();
}

function ensureInfra(): void {
  if (!timer) timer = setInterval(tick, TICK_MS);
  if (!visibilityHooked && typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") refreshAll();
    });
    visibilityHooked = true;
  }
}

export interface UsePollOptions {
  /** Poll interval in ms (per key; the smallest registered value wins). */
  intervalMs: number;
  /** Set false to unregister without unmounting (e.g. panel collapsed). */
  enabled?: boolean;
}

export interface UsePollResult<T> {
  data: T | null;
  error: unknown;
  /** Force an immediate fetch of this key (shared with all subscribers). */
  refresh: () => Promise<void>;
}

export function usePoll<T>(
  key: string,
  fetcher: Fetcher<T>,
  { intervalMs, enabled = true }: UsePollOptions,
): UsePollResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled) return;
    ensureInfra();
    let e = entries.get(key);
    if (!e) {
      e = {
        key,
        fetcher: () => fetcherRef.current(),
        intervalMs,
        errorFactor: 1,
        lastRun: 0,
        inFlight: false,
        subscribers: new Set(),
        lastData: null,
        lastError: null,
      };
      entries.set(key, e);
    } else if (intervalMs < e.intervalMs) {
      e.intervalMs = intervalMs; // fastest subscriber wins
    }
    const cb = (d: unknown, err: unknown) => {
      setData(d as T | null);
      setError(err);
    };
    e.subscribers.add(cb);
    // Replay the shared result so late subscribers render immediately.
    if (e.lastData !== null || e.lastError !== null) cb(e.lastData, e.lastError);
    // First subscriber: fetch right away instead of waiting a full interval.
    if (e.lastRun === 0) void runEntry(e);
    return () => {
      e.subscribers.delete(cb);
      // Entries stay registered (cheap) so the shared result survives
      // remounts; ticking skips subscriber-less entries.
    };
  }, [key, intervalMs, enabled]);

  const refresh = useCallback(async () => {
    const e = entries.get(key);
    if (e) {
      e.lastRun = 0;
      await runEntry(e);
    }
  }, [key]);

  return { data, error, refresh };
}
