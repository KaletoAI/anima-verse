/**
 * guardedPoll — timer helpers for the Game-Admin polls (plan 2026-11-24-figure-poll-caches Task 1). No React:
 * the hooks call them inside their effects, the smoke (scripts/smoke_guarded_poll.mjs) drives them with fake
 * timers.
 *
 * - `guardedInterval`: a tick that finds the previous `load` still pending is skipped, so a slow server never
 *   collects one more request per period. A rejected load releases the guard like a resolved one.
 * - `debounced`: trailing edge — a burst of calls becomes one run `ms` after the last call.
 * - `throttled`: leading edge — a call within `ms` of the last run is dropped.
 */

export interface Timers {
  setTimeout(fn: () => void, ms: number): unknown
  clearTimeout(id: unknown): void
  setInterval(fn: () => void, ms: number): unknown
  clearInterval(id: unknown): void
}

const realTimers: Timers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (id) => globalThis.clearTimeout(id as ReturnType<typeof globalThis.setTimeout>),
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (id) => globalThis.clearInterval(id as ReturnType<typeof globalThis.setInterval>),
}

/** Call `load` every `ms`, skipping a tick while the previous call has not settled. Returns the stop function. */
export function guardedInterval(load: () => Promise<unknown>, ms: number, timers: Timers = realTimers): () => void {
  let busy = false
  let stopped = false
  const tick = () => {
    if (busy || stopped) return
    busy = true
    let pending: Promise<unknown>
    try {
      pending = Promise.resolve(load())
    } catch {
      busy = false
      return
    }
    pending.then(() => { busy = false }, () => { busy = false })
  }
  const id = timers.setInterval(tick, ms)
  return () => {
    stopped = true
    timers.clearInterval(id)
  }
}

/** Trailing-edge debounce: runs `fn` once, `ms` after the last call; `cancel()` drops a pending run. */
export function debounced(fn: () => void, ms: number, timers: Timers = realTimers): (() => void) & { cancel(): void } {
  let id: unknown = null
  const run = (() => {
    if (id !== null) timers.clearTimeout(id)
    id = timers.setTimeout(() => {
      id = null
      fn()
    }, ms)
  }) as (() => void) & { cancel(): void }
  run.cancel = () => {
    if (id !== null) timers.clearTimeout(id)
    id = null
  }
  return run
}

/** Leading-edge throttle: runs `fn` at once unless it ran less than `ms` ago; such a call is dropped. */
export function throttled(fn: () => void, ms: number, now: () => number = () => Date.now()): () => void {
  let last: number | null = null
  return () => {
    const t = now()
    if (last !== null && t - last < ms) return
    last = t
    fn()
  }
}
