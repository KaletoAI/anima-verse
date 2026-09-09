/**
 * The clock display settings, fetched once and shared by every surface.
 *
 * `GET /world/game-time` carries `time_format` and `timezone` (configured in
 * `/admin/settings → Server`). Dozens of panels render timestamps, so the
 * values live in a module singleton instead of a prop chain or a provider each
 * app would have to mount: the first reader triggers the one fetch, everyone
 * else reads the cached snapshot synchronously.
 *
 * Two ways to use it:
 *
 * - **`clockSettings()`** — synchronous read, for module-level formatting
 *   helpers that have no hooks available.
 * - **`useClockSettings()`** — the same value, plus a subscription so the
 *   component re-renders when the settings arrive after its first paint.
 *   A component that renders timestamps should call it even when it formats
 *   through module-level helpers; the return value may be ignored.
 *
 * Until the fetch resolves, readers see `DEFAULT_CLOCK` (24h/UTC).
 */

import { useEffect, useSyncExternalStore } from 'react'
import { apiGet } from './api'
import { DEFAULT_CLOCK, asTimeFormat, type ClockSettings } from './clockFormat'

let current: ClockSettings = DEFAULT_CLOCK
let inflight: Promise<ClockSettings> | null = null
let loaded = false

const listeners = new Set<() => void>()

/** Current snapshot — identity-stable until the settings actually change. */
export function clockSettings(): ClockSettings {
  return current
}

function publish(next: ClockSettings): void {
  if (next.format === current.format && next.timeZone === current.timeZone) return
  current = next
  listeners.forEach((fn) => fn())
}

/**
 * Fetch the settings once. Concurrent callers share the in-flight promise;
 * later callers get the cached value unless `force` is set (used after an
 * admin saved new settings).
 */
export function loadClockSettings(force = false): Promise<ClockSettings> {
  if (loaded && !force) return Promise.resolve(current)
  if (inflight && !force) return inflight
  inflight = apiGet<{ time_format?: unknown, timezone?: unknown }>('/world/game-time')
    .then((info) => {
      const tz = typeof info?.timezone === 'string' && info.timezone.trim()
        ? info.timezone.trim() : 'UTC'
      publish({ format: asTimeFormat(info?.time_format), timeZone: tz })
      loaded = true
      return current
    })
    .catch(() => current)   // keep the defaults; a clock is not worth a toast
    .finally(() => { inflight = null })
  return inflight
}

/**
 * Feed the singleton from a `/world/game-time` payload a caller already has
 * (the header clock polls it anyway) — saves the extra request and keeps every
 * panel in step with the header.
 */
export function applyClockSettings(info: { time_format?: unknown, timezone?: unknown }): void {
  const tz = typeof info?.timezone === 'string' && info.timezone.trim()
    ? info.timezone.trim() : 'UTC'
  publish({ format: asTimeFormat(info?.time_format), timeZone: tz })
  loaded = true
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** Subscribed read — see the module docstring. */
export function useClockSettings(): ClockSettings {
  const snapshot = useSyncExternalStore(subscribe, clockSettings, clockSettings)
  useEffect(() => { void loadClockSettings() }, [])
  return snapshot
}
