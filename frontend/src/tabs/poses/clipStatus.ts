/**
 * The Library's status rules (Ruling A110 phase 4), pure so a smoke can pin them:
 * the lamp of a clip file and of a kind, the set letter of the list, the finale
 * clips a save edits too, and the steps one Save will run — shown before the click.
 */
import type { ApiClipRow } from './clipSets'

/** green = checked on a place (D3 `orientation.checked`), yellow = sidecar without a check,
 *  grey = no sidecar (nothing can be stored). */
export type Lamp = 'green' | 'yellow' | 'grey'

export function clipLamp(c: Pick<ApiClipRow, 'has_sidecar' | 'orientation'>): Lamp {
  if (c.has_sidecar === false) return 'grey'
  return c.orientation?.checked ? 'green' : 'yellow'
}

/** A kind reads as its weakest file; B halves follow their A half (the dials act on A). */
export function kindLamp(files: Pick<ApiClipRow, 'role' | 'has_sidecar' | 'orientation'>[]): Lamp {
  const own = files.filter((c) => (c.role || '') !== 'b')
  if (!own.length || own.some((c) => clipLamp(c) === 'grey')) return 'grey'
  return own.every((c) => clipLamp(c) === 'green') ? 'green' : 'yellow'
}

/** The set's one-letter mark in the list: n = neutral, else its first letter. */
export function setLetter(s: string): string {
  return s ? s[0] : 'n'
}

export interface FinalePose { animation?: string; finale_animation?: string; finale_auto?: string }

/** The finale kinds a save of ``kind`` edits too — the server's `finale_kinds_of` (a pose's own
 *  finale, else the derived one, never the kind itself) narrowed to files lying in the same set and
 *  library as the edited clip (`_finale_files`). */
export function finaleKinds(poses: FinalePose[], kind: string, target: Pick<ApiClipRow, 'set' | 'library'>,
  clips: Pick<ApiClipRow, 'kind' | 'set' | 'library'>[]): string[] {
  const kinds: string[] = []
  for (const p of poses) {
    if ((p.animation || '').trim() !== kind) continue
    const f = (p.finale_animation || p.finale_auto || '').trim().toLowerCase()
    if (f && f !== kind && !kinds.includes(f)) kinds.push(f)
  }
  const lib = target.library || 'free'
  return kinds.filter((k) => clips.some((c) => c.kind === k && (c.set || '') === (target.set || '')
    && (c.library || 'free') === lib))
}

/** What one Save will do, in order. */
export type SaveStep = 'bake' | 'shift' | 'heights' | 'finales' | 'check' | 'clear-check'

export function saveSteps(s: { bake: boolean; shift: boolean; heights: boolean; finales: number;
  greenCheck: boolean; savedCheck: boolean }): SaveStep[] {
  const out: SaveStep[] = []
  if (s.bake) out.push('bake')
  if (s.shift) out.push('shift')
  if (s.heights) out.push('heights')
  if ((s.bake || s.shift || s.heights) && s.finales) out.push('finales')
  if (s.greenCheck) out.push('check')
  // The server clears the old check on every orient write that does not carry a new one (D3).
  else if ((s.bake || s.shift) && s.savedCheck) out.push('clear-check')
  return out
}
