/**
 * The words of the stored-body Delete (Ruling A64): the refusal next to a stored body shape or texture body, and
 * the confirmation's lines — what is removed (files, MB, the outfit models built on a shape) and what becomes due.
 * Server: GET /characters/{c}/figure/stored/{key}/preview (`figure.delete_preview`), the stored list's `refusal`.
 */
import type { Light } from './hairstylesModel'

type Tr = (s: string) => string
const EN: Tr = (s) => s

export type StoredRefusal = '' | 'running' | 'current' | 'needed'

export interface StoredDeletePreview {
  key: string
  kind: 'shape' | 'texture'
  built_for_name: string
  deletable: boolean
  refusal: StoredRefusal
  /** The artefact graph's verdict (server English). */
  reason: string
  /** A shape kept only because an outfit model was built on it. */
  history: boolean
  /** Paths relative to the character folder. */
  files: string[]
  bytes: number
  /** Names of the outfit models deleted with a shape. */
  outfit_models: string[]
  /** Keys a run protects — skipped by the delete. */
  running: string[]
}

export function megabytes(bytes: number): string {
  return `${(bytes / 1e6).toFixed(1)} MB`
}

/** Why a stored entry cannot be deleted, in plain words — written next to its disabled Delete. "" when it can. */
export function refusalText(refusal: StoredRefusal | undefined, reason: string, t: Tr = EN): string {
  switch (refusal) {
    case 'running': return t('A run works on it now — delete it after the run.')
    case 'current': return t('The figure stands on it now — take off what is worn in the body, then delete it.')
    case 'needed': return t('An outfit would be built on it now ({reason}).').replace('{reason}', t(reason))
    default: return ''
  }
}

/** The bulk Delete's sum (round 2026-11-25): the deletable previews as one — files, bytes, outfit models and
 *  running parts added up; deletable when one of them is. */
export function sumPreviews(list: StoredDeletePreview[]): StoredDeletePreview {
  const ok = list.filter((p) => p.deletable)
  const kinds = new Set(ok.map((p) => p.kind))
  return {
    key: ok.map((p) => p.key).join(', '),
    kind: kinds.size === 1 && kinds.has('texture') ? 'texture' : 'shape',
    built_for_name: '',
    deletable: ok.length > 0,
    refusal: ok.length ? '' : (list[0]?.refusal ?? 'needed'),
    reason: ok.length ? '' : (list[0]?.reason ?? ''),
    history: ok.some((p) => p.history),
    files: ok.flatMap((p) => p.files),
    bytes: ok.reduce((sum, p) => sum + p.bytes, 0),
    outfit_models: ok.flatMap((p) => p.outfit_models),
    running: ok.flatMap((p) => p.running),
  }
}

/** The confirmation's lines: what goes (files · MB, the outfit models with a shape) and what becomes due. */
export function deleteLines(p: StoredDeletePreview, t: Tr = EN): { removed: string[]; due: string[] } {
  const removed = [t('{n} files · {size}').replace('{n}', String(p.files.length)).replace('{size}', megabytes(p.bytes))]
  if (p.outfit_models.length) {
    removed.push(t('The outfit models built on it: {names}').replace('{names}', p.outfit_models.join(', ')))
  }
  const due = [t('Nothing becomes due now: no outfit would be built on it.')]
  due.push(p.kind === 'shape'
    ? t('An outfit that needs this body shape again meshes it anew (hub jobs).')
    : t('An outfit that needs this texture body again makes it anew (CPU, no hub job).'))
  if (p.outfit_models.length) due.push(t('Wearing one of those outfits again builds its model anew.'))
  if (p.running.length) {
    due.push(t('A run works on {n} of its parts — those stay.').replace('{n}', String(p.running.length)))
  }
  return { removed, due }
}

/** A stored row's light and state words (checklist point 8): blue a run works on it, green in use or needed by an
 *  outfit now (kept), grey stored and deletable — "stored, not needed now", kept only by an outfit model built on
 *  it (Ruling A64), a shape never meshed or one neither worn nor in a saved outfit set (round 2026-11-25). */
export function storedState(e: { running: boolean; current: boolean; deletable: boolean;
  refusal?: StoredRefusal; history?: boolean; spare?: boolean; meshed?: boolean; kind?: string },
t: Tr = EN): { light: Light; text: string } {
  if (e.running || e.refusal === 'running') return { light: 'blue', text: t('a run works on it') }
  if (e.current) return { light: 'green', text: t('in use now') }
  if (!e.deletable) return { light: 'green', text: t('needed by an outfit now') }
  if (e.history) return { light: 'grey', text: t('kept only by an outfit model built on it') }
  // Round 2026-11-25: a shape with views only (its run was superseded) and one neither worn nor in a saved set.
  if (e.kind === 'shape' && e.meshed === false) return { light: 'grey', text: t('superseded, not meshed') }
  if (e.spare) return { light: 'grey', text: t('neither worn nor in a saved outfit set') }
  return { light: 'grey', text: t('stored, not needed now') }
}
