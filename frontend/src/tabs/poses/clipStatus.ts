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

/** One request of a Save: the orient write (bake/shift/check), the heights PATCH, or a check alone. */
export type SaveWrite = 'orient' | 'heights' | 'check'

/** Runs a Save's requests in order and stops at the first failure. `applied` names every request that went
 *  through — the caller clears exactly those drafts, whatever failed after them: the orient write is a DELTA
 *  (the server adds the angles and shifts up), so a draft kept after it landed would be baked twice. */
export async function runSaveWrites(
  writes: ReadonlyArray<readonly [SaveWrite, () => Promise<unknown>]>,
): Promise<{ applied: SaveWrite[]; error: unknown }> {
  const applied: SaveWrite[] = []
  for (const [name, write] of writes) {
    try {
      await write()
    } catch (error) {
      return { applied, error: error ?? new Error('save failed') }
    }
    applied.push(name)
  }
  return { applied, error: null }
}

// ── Entries, Transitions, Import (Ruling A110 phase 5) ─────────────────────────────────────

/** A pose's clip coverage: green = a file in every base set (the instance's `clip_sets`), yellow =
 *  some base set falls back to the neutral file, red = no file at all, or a base set with neither its
 *  own nor a neutral file. `missing` names the base sets without their own file. */
export interface PoseLamp { lamp: 'green' | 'yellow' | 'red'; missing: string[]; neutral: boolean; files: number }

export function poseLamp(kind: string, clips: Pick<ApiClipRow, 'kind' | 'set'>[], baseSets: string[]): PoseLamp {
  const own = kind ? clips.filter((c) => c.kind === kind) : []
  const sets = new Set(own.map((c) => c.set || ''))
  const neutral = sets.has('')
  const missing = baseSets.filter((s) => s && !sets.has(s))
  if (!own.length) return { lamp: 'red', missing, neutral, files: 0 }
  if (!missing.length) return { lamp: 'green', missing, neutral, files: own.length }
  return { lamp: neutral ? 'yellow' : 'red', missing, neutral, files: own.length }
}

export interface AnimatablePose { key: string; animation?: string; participants?: number; group?: string }

/** The poses "Run all" animates: solo poses (the generator makes solo clips only) on a place type the
 *  generator supports, whose kind has no clip file at all and that have no job running already. A pose
 *  that has any clip is current and skipped — its single button still regenerates it. */
export function posesToAnimate(poses: AnimatablePose[], clips: Pick<ApiClipRow, 'kind'>[],
  animatableGroups: string[], busyKeys: Set<string>): string[] {
  const withFile = new Set(clips.map((c) => c.kind))
  return poses.filter((p) => (p.participants || 1) === 1 && animatableGroups.includes(p.group || '')
    && !busyKeys.has(p.key) && !(p.animation && withFile.has(p.animation))).map((p) => p.key)
}

/** A transition rule: red = it names a bridge clip that is not installed, yellow = it overlaps an
 *  earlier rule (the earlier one wins), green = every bridge clip is there. */
export function ruleLamp(bridgeKinds: string[], installed: Set<string>, conflict: boolean): 'green' | 'yellow' | 'red' {
  if (!bridgeKinds.length || bridgeKinds.some((k) => !installed.has(k))) return 'red'
  return conflict ? 'yellow' : 'green'
}

/** An inbox file: red = no bone map knows the rig (cannot be imported), yellow = a reference pose,
 *  not a motion (used as the bind pose of another import), green = convertible. */
export function inboxLamp(probe: { skeleton_family?: string | null; is_rest_candidate?: boolean }): 'green' | 'yellow' | 'red' {
  if (!probe.skeleton_family) return 'red'
  return probe.is_rest_candidate ? 'yellow' : 'green'
}

/** A CMU take: red = rejected, green = imported into the library, yellow = converted and previewable,
 *  grey = not converted yet (still importable from the original recording). */
export function takeLamp(take: { clip?: unknown; status: { rejected?: boolean; imported?: unknown[] | null } }):
  'green' | 'yellow' | 'red' | 'grey' {
  if (take.status.rejected) return 'red'
  if (take.status.imported?.length) return 'green'
  return take.clip ? 'yellow' : 'grey'
}
