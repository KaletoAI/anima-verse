/**
 * A STATUS PER CLIP (owner decision 2026-11-23): what Auto-align, "Align all" or a hand save left on each contact
 * relation of a pair or group clip, stored in the clip's sidecar (server `app/core/animation_clips.py`
 * `set_clip_align_status`, PATCH `align_status`) with the key numbers, shown as a badge in the clip list.
 *
 * States: not checked (no entry) · auto: improved · auto: aligned (green contact lamp) · auto: blocked (reason) ·
 * auto: geometry mismatch · not measurable (reason) · manual: adjusted · and the clip's own tick "manual: done", which
 * later auto runs never clear. The clip summary is its worst relation (`ALIGN_STATE_ORDER`).
 */
import { isPointTarget, keyWorstMm, type AlignDiscard } from '@anima/scene-render'
import type { RelationAlign } from './PlacePreview'

export type AlignState = 'auto_improved' | 'auto_aligned' | 'auto_blocked' | 'auto_mismatch' | 'not_measurable'
  | 'manual_adjusted'
export type AlignStateReason = 'overlap' | 'support' | 'range' | 'root_inside' | 'nothing_to_gain' | 'worse'
  | 'no_place' | 'no_part' | 'no_pair'
/** One relation's status as sent (the server stamps `at`). */
export interface AlignStatusEntry {
  state: AlignState; reason?: AlignStateReason
  depth_mm?: [number, number]; axis_mm?: [number, number]; root_mm?: number; support_mm?: number
  mover?: string; turn_deg?: [number, number, number]; at?: string
}
/** The listing's view of a clip's status. */
export interface ClipAlignStatus {
  relations: Record<string, AlignStatusEntry>; done: boolean; done_at: string | null
  summary: AlignState | 'not_checked'
}
/** Worst first (the server's `ALIGN_STATE_ORDER`). */
export const ALIGN_STATE_ORDER: (AlignState | 'not_checked')[] = ['auto_mismatch', 'auto_blocked', 'not_measurable',
  'not_checked', 'auto_improved', 'manual_adjusted', 'auto_aligned']

const r1 = (v: number) => Math.round(v * 10) / 10
const fin = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v)

/** The key numbers of one measured relation: depth at the deepest frame and axis error (before, after), the visible
 *  root (after, mm, + = inside), the moved role's support gap (the frame furthest from the surface, mm), the mover and
 *  the turn it carries. */
function numbersOf(r: RelationAlign): Omit<AlignStatusEntry, 'state' | 'reason'> {
  const inside = !isPointTarget(r.target)
  const kb = r.keys.before, ka = r.keys.after
  const out: Omit<AlignStatusEntry, 'state' | 'reason'> = { mover: r.moved, turn_deg: [r1(r.turnDeg[0]), r1(r.turnDeg[1]), r1(r.turnDeg[2])] }
  if (kb && ka && fin(kb.deep.depthMm) && fin(ka.deep.depthMm)) out.depth_mm = [r1(kb.deep.depthMm), r1(ka.deep.depthMm)]
  if (kb && ka) {
    const b = keyWorstMm(kb, inside), a = keyWorstMm(ka, inside)
    if (fin(b) && fin(a)) out.axis_mm = [r1(b), r1(a)]
  }
  if (r.rendered && fin(r.rendered.after.visMm)) out.root_mm = r1(r.rendered.after.visMm)
  const g = r.support.afterMm
  if (g) out.support_mm = r1(Math.abs(g[0]) > Math.abs(g[1]) ? g[0] : g[1])
  return out
}

const DISCARD_REASON: Record<AlignDiscard, AlignStateReason> = {
  overlap: 'overlap', worse: 'worse', root: 'root_inside', support: 'support', nothing: 'nothing_to_gain',
}
/** The status a measured relation earns: applied → improved, or aligned when its contact lamp is green; not applied
 *  with a green lamp from the start → aligned (nothing to do); a geometry mismatch; otherwise blocked with THE
 *  VERDICT's reason ('range' when nothing was gained and the mover's range stopped it). */
export function relationStatus(r: RelationAlign): AlignStatusEntry {
  const nums = numbersOf(r)
  if (r.applied) return { state: r.lamp === 'green' ? 'auto_aligned' : 'auto_improved', ...nums }
  if (r.lampBefore === 'green' && r.discard === 'nothing') return { state: 'auto_aligned', ...nums }
  if (r.bucket === 'mismatch') return { state: 'auto_mismatch', ...nums }
  const why = r.discard ?? 'nothing'
  const reason: AlignStateReason = why === 'nothing' && r.reasons.includes('caps') ? 'range' : DISCARD_REASON[why]
  return { state: 'auto_blocked', reason, ...nums }
}
/** The relation key a "not measurable" status is stored under (a clip that gave no relation to measure). */
export const UNMEASURED_KEY = '*'
/** A clip the run could not measure: no place fits it, no figure has the part, or the persons never filled in. */
export function unmeasuredStatus(reason: 'no_place' | 'no_part' | 'no_pair'): AlignStatusEntry {
  return { state: 'not_measurable', reason }
}

/** The badge words (English source strings for `t()`). */
export function stateWord(t: (s: string) => string, s: AlignState | 'not_checked' | 'done'): string {
  switch (s) {
    case 'not_checked': return t('not checked')
    case 'auto_improved': return t('auto: improved')
    case 'auto_aligned': return t('auto: aligned')
    case 'auto_blocked': return t('auto: blocked')
    case 'auto_mismatch': return t('auto: geometry mismatch')
    case 'not_measurable': return t('not measurable')
    case 'manual_adjusted': return t('manual: adjusted')
    case 'done': return t('manual: done')
  }
}
export function reasonText(t: (s: string) => string, r: AlignStateReason): string {
  switch (r) {
    case 'overlap': return t('overlap')
    case 'support': return t('support')
    case 'range': return t('range')
    case 'root_inside': return t('root inside')
    case 'nothing_to_gain': return t('nothing to gain')
    case 'worse': return t('worse')
    case 'no_place': return t('no place')
    case 'no_part': return t('no figure with the part')
    case 'no_pair': return t('no pair filled in')
  }
}
export const STATE_COLOR: Record<AlignState | 'not_checked' | 'done', string> = {
  not_checked: 'var(--text-muted, #8b949e)', auto_improved: '#58a6ff', auto_aligned: '#3fb950',
  auto_blocked: '#d29922', auto_mismatch: '#f85149', not_measurable: '#a371f7', manual_adjusted: '#db61a2',
  done: '#3fb950',
}
/** The worst of several summaries (a kind with several sets). */
export function worstState(states: readonly (AlignState | 'not_checked')[]): AlignState | 'not_checked' {
  return states.reduce<AlignState | 'not_checked'>((w, s) => (ALIGN_STATE_ORDER.indexOf(s) < ALIGN_STATE_ORDER.indexOf(w) ? s : w),
    states.length ? 'auto_aligned' : 'not_checked')
}

/** The status a kind shows in the clip list: its A files' summaries, the worst of them; 'done' when every A file is
 *  ticked "manual: done". `key` is what the filter compares. */
export function kindStatusOf(clips: readonly { role?: string | null; align_status?: ClipAlignStatus | null }[]):
  { key: AlignState | 'not_checked' | 'done' | ''; reasons: AlignStateReason[] } {
  const own = clips.filter((c) => (c.role || '') === 'a' && c.align_status)
  if (!own.length) return { key: '', reasons: [] }
  if (own.every((c) => c.align_status!.done)) return { key: 'done', reasons: [] }
  const key = worstState(own.map((c) => c.align_status!.summary))
  const reasons = new Set<AlignStateReason>()
  for (const c of own) for (const e of Object.values(c.align_status!.relations)) if (e.state === key && e.reason) reasons.add(e.reason)
  return { key, reasons: [...reasons] }
}
