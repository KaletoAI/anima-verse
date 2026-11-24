/**
 * A STATUS PER CLIP (owner decision 2026-11-23): what Auto-align, "Align all" or a hand save left on each contact
 * relation of a pair or group clip, stored in the clip's sidecar (server `app/core/animation_clips.py`
 * `set_clip_align_status`, PATCH `align_status`) with the key numbers, shown as a badge in the clip list.
 *
 * States: not checked (no entry) · auto: improved · auto: aligned (green contact lamp) · auto: unchanged (already fits —
 * nothing to gain, not a block) · auto: blocked (reason: overlap, support, worse, a cap hit with a condition unmet, or a
 * visible root that cannot be pulled out of the opening — the range cap, the person it would go into, or its support) ·
 * auto: geometry
 * mismatch · not measurable (reason) · manual: adjusted · and the clip's own tick "manual: done", which later auto runs
 * never clear. The clip summary is its worst relation (`ALIGN_STATE_ORDER`). NOTES (owner 2026-11-23 evening, notes
 * instead of blocks) ride along: little depth, shallower than the start, support corrected, no change needed, and THE
 * START OVERLAP's (owner 2026-11-24): the start overlap reduced (by how much, which pair and capsules), one that remains
 * (how deep, the worst capsule pair — a hand correction or another mover), the other role against a third person.
 */
import { isPointTarget, keyWorstMm, type AlignDiscard, type AlignNote } from '@anima/scene-render'
import type { RelationAlign } from './PlacePreview'

export type AlignState = 'auto_improved' | 'auto_aligned' | 'auto_unchanged' | 'auto_blocked' | 'auto_mismatch'
  | 'not_measurable' | 'manual_adjusted'
export type AlignStateReason = 'overlap' | 'support' | 'range' | 'root_range' | 'root_overlap' | 'root_support' | 'worse'
  | 'no_place' | 'no_part' | 'no_pair'
export type AlignNoteCode = AlignNote['code']
/** One relation's status as sent (the server stamps `at`): `with` = the place letter a 'root_overlap' would go into;
 *  the notes and their numbers (the stroke, how much shallower, the support correction, mm). */
export interface AlignStatusEntry {
  state: AlignState; reason?: AlignStateReason; with?: string
  depth_mm?: [number, number]; axis_mm?: [number, number]; root_mm?: number; support_mm?: number
  notes?: AlignNoteCode[]; stroke_mm?: number; shallower_mm?: number; support_fix_mm?: number; root_pulled?: boolean
  mover?: string; turn_deg?: [number, number, number]; at?: string
  /** THE START OVERLAP's notes: reduced by (mm, pair "X↔Y", capsules), left (mm, pair, capsules), a third person. */
  overlap_fix_mm?: number; overlap_pair?: string; overlap_worst?: string
  overlap_left_mm?: number; left_pair?: string; left_worst?: string
  third_mm?: number; third_pair?: string; third_worst?: string
}
/** The listing's view of a clip's status. */
export interface ClipAlignStatus {
  relations: Record<string, AlignStatusEntry>; done: boolean; done_at: string | null
  summary: AlignState | 'not_checked'
}
/** Worst first (the server's `ALIGN_STATE_ORDER`). */
export const ALIGN_STATE_ORDER: (AlignState | 'not_checked')[] = ['auto_mismatch', 'auto_blocked', 'not_measurable',
  'not_checked', 'auto_improved', 'manual_adjusted', 'auto_unchanged', 'auto_aligned']

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
  if (r.notes.length) out.notes = r.notes.map((n) => n.code)
  for (const n of r.notes) {
    if (n.code === 'little_depth') out.stroke_mm = r1(n.strokeMm)
    else if (n.code === 'shallower') { out.shallower_mm = r1(n.mm); out.root_pulled = n.rootPulled }
    else if (n.code === 'support_corrected') out.support_fix_mm = r1(n.mm)
    else if (n.code === 'overlap_reduced') { out.overlap_fix_mm = r1(n.mm); out.overlap_pair = n.pair; out.overlap_worst = n.worst }
    else if (n.code === 'overlap_remains') { out.overlap_left_mm = r1(n.mm); out.left_pair = n.pair; out.left_worst = n.worst }
    else if (n.code === 'overlap_third') { out.third_mm = r1(n.mm); out.third_pair = n.pair; out.third_worst = n.worst }
  }
  return out
}

const DISCARD_REASON: Record<AlignDiscard, AlignStateReason> = { overlap: 'overlap', worse: 'worse', support: 'support' }
/** The status a measured relation earns (owner rules of 2026-11-23 evening): a visible root that could not be pulled
 *  out of the opening → blocked, naming the range cap or the person; applied → improved, or aligned when its contact
 *  lamp is green; a geometry mismatch; discarded → blocked with THE VERDICT's reason; a cap hit with the deepest
 *  frame's conditions unmet → blocked 'range'; otherwise unchanged — or aligned when the start's lamp was green. */
export function relationStatus(r: RelationAlign): AlignStatusEntry {
  const nums = numbersOf(r)
  const st = r.rootPull?.stuck
  if (st) return { state: 'auto_blocked', reason: st.why === 'overlap' ? 'root_overlap' : st.why === 'support' ? 'root_support' : 'root_range',
    ...(st.with ? { with: st.with } : {}), ...nums }
  if (r.applied) return { state: r.lamp === 'green' ? 'auto_aligned' : 'auto_improved', ...nums }
  if (r.bucket === 'mismatch') return { state: 'auto_mismatch', ...nums }
  if (r.discard) return { state: 'auto_blocked', reason: DISCARD_REASON[r.discard], ...nums }
  if (r.bucket === 'blocked') return { state: 'auto_blocked', reason: 'range', ...nums }
  return { state: r.lampBefore === 'green' ? 'auto_aligned' : 'auto_unchanged', ...nums }
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
    case 'auto_unchanged': return t('auto: unchanged (already fits)')
    case 'auto_blocked': return t('auto: blocked')
    case 'auto_mismatch': return t('auto: geometry mismatch')
    case 'not_measurable': return t('not measurable')
    case 'manual_adjusted': return t('manual: adjusted')
    case 'done': return t('manual: done')
  }
}
export function reasonText(t: (s: string) => string, r: AlignStateReason, who?: string): string {
  switch (r) {
    case 'overlap': return t('overlap')
    case 'support': return t('support')
    case 'range': return t('range')
    case 'root_range': return t('root inside: the range cap is reached')
    case 'root_support': return t('root inside: pulling back would take it off its surface')
    case 'root_overlap': return who ? t('root inside: pulling back would go into place {who}').replace('{who}', who)
      : t('root inside: pulling back would go into another person')
    case 'worse': return t('worse')
    case 'no_place': return t('no place')
    case 'no_part': return t('no figure with the part')
    case 'no_pair': return t('no pair filled in')
  }
}
/** A note in words — from a measured result (`AlignNote`) or a stored status entry (its code and numbers). */
export function noteText(t: (s: string) => string, n: AlignNote): string {
  const f = (v: number) => (Math.round(v) || 0).toFixed(0)
  switch (n.code) {
    case 'little_depth': return t('little depth: the bodies move together (stroke {s} mm, deepest {d} mm)')
      .replace('{s}', f(n.strokeMm)).replace('{d}', f(n.deepMm))
    case 'shallower': return (n.rootPulled ? t('shallower than the start by {mm} mm (root pulled outside)')
      : t('shallower than the start by {mm} mm')).replace('{mm}', f(n.mm))
    case 'support_corrected': return t('support corrected by {mm} mm').replace('{mm}', f(n.mm))
    case 'no_change': return t('no change needed')
    case 'overlap_reduced': return t('start overlap reduced by {mm} mm ({pair}: {worst})').replace('{mm}', f(n.mm))
      .replace('{pair}', n.pair || '–').replace('{worst}', n.worst || '–')
    case 'overlap_remains': return t('start overlap remains {mm} mm ({pair}: {worst})').replace('{mm}', f(n.mm))
      .replace('{pair}', n.pair || '–').replace('{worst}', n.worst || '–')
    case 'overlap_third': return t('{pair} overlap {mm} mm by their own posture ({worst}) — not the aligned pair')
      .replace('{mm}', f(n.mm)).replace('{pair}', n.pair || '–').replace('{worst}', n.worst || '–')
  }
}
/** The notes of a stored status entry, rebuilt as `AlignNote`s (the numbers the entry keeps). */
export function entryNotes(e: AlignStatusEntry): AlignNote[] {
  return (e.notes ?? []).map((c): AlignNote => (c === 'little_depth' ? { code: c, strokeMm: e.stroke_mm ?? NaN, deepMm: e.depth_mm?.[1] ?? NaN }
    : c === 'shallower' ? { code: c, mm: e.shallower_mm ?? NaN, rootPulled: !!e.root_pulled }
      : c === 'support_corrected' ? { code: c, mm: e.support_fix_mm ?? NaN }
        : c === 'overlap_reduced' ? { code: c, mm: e.overlap_fix_mm ?? NaN, pair: e.overlap_pair ?? '', worst: e.overlap_worst ?? '' }
          : c === 'overlap_remains' ? { code: c, mm: e.overlap_left_mm ?? NaN, pair: e.left_pair ?? '', worst: e.left_worst ?? '' }
            : c === 'overlap_third' ? { code: c, mm: e.third_mm ?? NaN, pair: e.third_pair ?? '', worst: e.third_worst ?? '' }
              : { code: 'no_change' }))
}
export const STATE_COLOR: Record<AlignState | 'not_checked' | 'done', string> = {
  not_checked: 'var(--text-muted, #8b949e)', auto_improved: '#58a6ff', auto_aligned: '#3fb950', auto_unchanged: '#56d4dd',
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
  { key: AlignState | 'not_checked' | 'done' | ''; reasons: AlignStateReason[]; who: string[]; notes: AlignNoteCode[]
    overlap: AlignNote[] } {
  const own = clips.filter((c) => (c.role || '') === 'a' && c.align_status)
  if (!own.length) return { key: '', reasons: [], who: [], notes: [], overlap: [] }
  const notes = new Set<AlignNoteCode>()
  for (const c of own) for (const e of Object.values(c.align_status!.relations)) for (const n of e.notes ?? []) if (n !== 'no_change') notes.add(n)
  // THE START OVERLAP's notes in full on the badge (how much, which pair and capsules), deepest first.
  const overlap = own.flatMap((c) => Object.values(c.align_status!.relations).flatMap((e) => entryNotes(e)))
    .filter((n) => n.code === 'overlap_reduced' || n.code === 'overlap_remains' || n.code === 'overlap_third')
    .sort((a, b) => ('mm' in b ? b.mm : 0) - ('mm' in a ? a.mm : 0))
  if (own.every((c) => c.align_status!.done)) return { key: 'done', reasons: [], who: [], notes: [...notes], overlap }
  const key = worstState(own.map((c) => c.align_status!.summary))
  const reasons = new Set<AlignStateReason>(), who = new Set<string>()
  for (const c of own) for (const e of Object.values(c.align_status!.relations)) if (e.state === key && e.reason) {
    reasons.add(e.reason)
    if (e.with) who.add(e.with)
  }
  return { key, reasons: [...reasons], who: [...who], notes: [...notes], overlap }
}
/** A note code in a few words (the badge). */
export function noteWord(t: (s: string) => string, c: AlignNoteCode): string {
  switch (c) {
    case 'little_depth': return t('little depth')
    case 'shallower': return t('shallower')
    case 'support_corrected': return t('support corrected')
    case 'no_change': return t('no change needed')
    case 'overlap_reduced': return t('start overlap reduced')
    case 'overlap_remains': return t('start overlap remains')
    case 'overlap_third': return t('third-person overlap')
  }
}
