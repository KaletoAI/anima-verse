/** React adapter for the shared, framework-free polling core. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPollCore, TICK_MS } from './pollCore';
import type { EndpointSpec, PollCore } from './pollCore';
import { syncHub } from './syncHub';

let singleton: PollCore | null = null;
export function pollCore(): PollCore {
  if (!singleton) {
    const core = createPollCore({
      now: () => Date.now(),
      setTimeout: (fn, ms) => window.setTimeout(fn, ms),
      clearTimeout: h => window.clearTimeout(h as number),
      hidden: () => typeof document !== 'undefined' && document.visibilityState !== 'visible',
    }, syncHub());
    singleton = core;
    if (typeof window !== 'undefined') window.setInterval(() => core.tick(), TICK_MS);
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') core.visible();
    });
  }
  return singleton;
}
export interface UsePollOptions extends EndpointSpec { enabled?: boolean }
export interface UsePollResult<T> {
  data: T | null;
  error: unknown;
  refresh: () => Promise<void>;
}
export function usePoll<T>(key: string, fetcher: () => Promise<T>, opts: UsePollOptions): UsePollResult<T> {
  const { enabled = true, ...spec } = opts;
  const specKey = JSON.stringify(spec);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  // A new key addresses a DIFFERENT resource, so the payload of the old one is
  // not stale data — it is the wrong data. Without this reset the caller keeps
  // rendering (and acting on) the previous key's answer until the first fetch
  // of the new key returns; the gallery then deletes a file of gallery A under
  // the name of gallery B. Reset during render, not in an effect: an effect
  // would still let one committed frame pair the new key with the old data.
  // Guarded by a ref so that a changed `intervalMs`/`enabled` alone — the two
  // other deps of the effect below — does NOT blank the panel.
  const keyRef = useRef(key);
  if (keyRef.current !== key) {
    keyRef.current = key;
    setData(null);
    setError(null);
  }

  useEffect(() => {
    if (!enabled) return;
    return pollCore().subscribe(key, () => fetcherRef.current(), JSON.parse(specKey) as EndpointSpec, (d, err) => {
      if (keyRef.current !== key) return;
      setData(d as T | null);
      setError(err);
    });
  }, [key, enabled, specKey]);
  const refresh = useCallback(() => pollCore().refresh(key), [key]);
  return { data, error, refresh };
}
