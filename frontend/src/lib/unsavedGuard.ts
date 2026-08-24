/**
 * "There is unsaved work in the open tab" — one question, asked by the shell.
 *
 * A tab switch UNMOUNTS the tab (`App` renders exactly one), so a local draft
 * dies with it silently. The map editor keeps such a draft since it saves in
 * one explicit batch (`tabs/map/pendingBuffer`), and it must not be possible
 * to lose twenty brush strokes by clicking the next tab.
 *
 * The shell cannot know what a tab considers unsaved, and the tab cannot know
 * when it is about to be replaced — so the tab registers a predicate here and
 * `App` asks it before switching. One registration at a time, which is all
 * there can be: only one tab is mounted.
 *
 * The predicate is called during an event handler, so it must be cheap and it
 * must not throw — a guard that raises would otherwise block every navigation.
 */

type Guard = () => boolean

let guard: Guard | null = null

/** Register (or, with null, clear) the mounted tab's unsaved-work predicate.
 *  Always clear it on unmount, or a dead tab keeps blocking navigation. */
export function setUnsavedGuard(fn: Guard | null): void {
  guard = fn
}

/** Does the mounted tab hold unsaved work? False when nothing registered —
 *  and false when the predicate throws: a broken guard must not trap the user
 *  in a tab. */
export function hasUnsavedWork(): boolean {
  try {
    return !!guard?.()
  } catch {
    return false
  }
}
