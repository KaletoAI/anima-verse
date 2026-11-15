/**
 * viewFacingModel — the pure helpers of a side view's facing line and its Mirror button (Ruling A91): the Base body
 * tab's left / right views and the Figure tab's dressed left / right views. The server measures which way the
 * figure faces (app/core/view_facing.py — the `left` view faces the LEFT edge of the image, the `right` view the
 * RIGHT edge) and what a mirror makes due; this file only words it. No React, no fetch — the check script
 * (scripts/check_view_facing_ui.mjs) bundles this file alone.
 *
 * In A90's compact tiles the facing shows as ONE line only when something needs a look (wrong, unsure, both sides
 * facing the same edge); the Mirror is a small "⇋" button beside the view's "↻ …" button, the whole sentence (no
 * image job, what becomes due with its hub jobs, one-sided details swap, a second click turns it back) on its
 * mouse-over.
 */
import type { Light } from './hairstylesModel'

type Tr = (s: string) => string
const EN: Tr = (s) => s

export type Side = 'left' | 'right'

/** The sidecar's `mirrored` record as the server shows it (without its hashes). */
export interface MirrorRecord {
  auto?: boolean
  reason?: string
  confidence?: number
  at?: string
}

/** What a Mirror click makes due besides the view itself (server `base_body.mirror_followup` /
 *  `model_refs.outfit_mirror_followup`). */
export interface MirrorFollowup {
  kind: string
  jobs: number | null
  /** Base views: dressed side views are composited onto this view. */
  dressed?: boolean
}

/** One side tile's facing (server `view_facing.tile_state`; a base view carries its `followup`). */
export interface FacingTile {
  expected: Side
  facing: Side | null
  confidence: number | null
  state: 'ok' | 'wrong' | 'unsure'
  mirrored: MirrorRecord | null
  restorable: boolean
  followup?: MirrorFollowup
}

/** Both side views measured facing the same edge (server `view_facing.pair_state`). */
export interface FacingPair {
  same: boolean
  facing: Side | null
}

export const FACING_WRONG = 'Wrong way'
export const FACING_WRONG_REASON = 'A {view} view faces the {view} edge of the image — this one faces the {side} '
  + 'edge. Mirror it (no image job).'
export const FACING_UNSURE = 'Facing unsure'
export const FACING_UNSURE_REASON = 'The facing check is not sure which way this view faces (it reads the feet). '
  + 'A {view} view faces the {view} edge of the image — check it and mirror it if needed.'
export const FACING_SAME = 'Same as other'
export const FACING_SAME_REASON = 'Both side views face the {side} edge of the image — one of them must be mirrored.'
export const MIRRORED_AUTO = 'Mirrored automatically: it faced the other way ({pct} % sure).'
export const MIRRORED_HAND = 'Mirrored by hand.'

export const SIDE_WORD: Record<Side, string> = { left: 'left', right: 'right' }

function fill(text: string, view: Side, side: Side | null, t: Tr): string {
  return text.split('{view}').join(t(SIDE_WORD[view])).split('{side}').join(t(SIDE_WORD[side || view]))
}

/**
 * The tile's facing line — only when something needs a look: a sure wrong view → red "Wrong way"; both
 * sides facing the same edge → yellow "Same as other"; an unsure view → yellow "Facing unsure". Short, the
 * tile is narrow: the whole reason (what is wrong, what fixes it — the Mirror, no image job) is the line's
 * mouse-over. Null for a view that faces the right way (or has no facing).
 */
export function facingLine(f: FacingTile | null | undefined, pair: FacingPair | null | undefined, view: Side,
  t: Tr = EN): { light: Light; text: string; title: string } | null {
  if (!f) return null
  if (f.state === 'wrong') {
    return { light: 'red', text: t(FACING_WRONG), title: fill(t(FACING_WRONG_REASON), view, f.facing, t) }
  }
  if (pair?.same) {
    return { light: 'yellow', text: t(FACING_SAME), title: fill(t(FACING_SAME_REASON), view, pair.facing, t) }
  }
  if (f.state === 'unsure') {
    return { light: 'yellow', text: t(FACING_UNSURE), title: fill(t(FACING_UNSURE_REASON), view, f.facing, t) }
  }
  return null
}

export const MIRROR_LABEL = '⇋'
export const MIRROR_TITLE = 'Mirror this view left-right on the CPU — no image job.'
export const TURN_BACK_TITLE = 'Turn this view back to the picture as it was rendered — no image job.'
export const MIRROR_SWAPS = 'Asymmetric details — a tattoo, a parting, an item worn on one side — swap sides.'
export const MIRROR_AGAIN = 'A second click turns it back.'
export const MIRROR_WAIT_MODEL = 'A 3D model of this character is being made — mirror when it is done'
export const MIRROR_DONE = 'Mirrored — no image job'
export const MIRROR_UNDONE = 'Turned back — no image job'
export const FOLLOWUP_TEXT: Record<string, string> = {
  no_model: 'No base model yet — no rebuild.',
  unused: 'The base model was built without this view — no rebuild.',
  restores: 'The base model was built from that picture — it is current again, no rebuild.',
  stale: 'Then the base model is out of date: the next Build rebuilds it — {jobs}.',
  already_stale: 'The base model is out of date already: the next Build rebuilds it — {jobs}.',
  repaint: 'Then the outfit model is due: the Build repaints it on the CPU — no hub job.',
  copy: 'This view is a copy of the body’s view — mirror the body’s view instead (Base body tab).',
  model: 'The outfit’s 3D model keeps the old view until it is made again — {jobs}.',
  outfit_no_model: 'No 3D model of this outfit yet — nothing else changes.',
}
export const DRESSED_FOLLOW = 'The dressed {view} views are composited onto it again.'

/** "N hub jobs" / "1 hub job" / "cost unknown". */
export function hubJobs(n: number | null | undefined, t: Tr = EN): string {
  if (n === null || n === undefined) return t('cost unknown')
  return (n === 1 ? t('1 hub job') : t('{n} hub jobs')).replace('{n}', String(n))
}

/**
 * The "⇋" button of a side tile: `on` while the view is mirrored (the button shows pressed), its whole `title`
 * (what it does and costs — no image job —, the follow-up before the click, the swap of one-sided details, that a
 * second click turns it back; a mirrored view says how it came to be mirrored) and `disabled` — why it cannot be
 * clicked (a copy of the body's view), "" otherwise. `outfit`: a dressed view (its `no_model` means the outfit's
 * 3D model).
 */
export function mirrorButton(f: FacingTile | null | undefined, followup: MirrorFollowup | null | undefined,
  view: Side, outfit: boolean, t: Tr = EN): { label: string; title: string; on: boolean; disabled: string } {
  const on = Boolean(f?.mirrored)
  const kind = followup?.kind || ''
  const key = outfit && kind === 'no_model' ? 'outfit_no_model' : kind
  const follow = FOLLOWUP_TEXT[key] ? t(FOLLOWUP_TEXT[key]).replace('{jobs}', hubJobs(followup?.jobs, t)) : ''
  const dressed = !outfit && followup?.dressed
    ? t(DRESSED_FOLLOW).replace('{view}', t(SIDE_WORD[view])) : ''
  const how = !f?.mirrored ? '' : f.mirrored.auto
    ? t(MIRRORED_AUTO).replace('{pct}', String(Math.round((f.mirrored.confidence ?? 0) * 100)))
    : t(MIRRORED_HAND)
  const lines = [how, t(on ? TURN_BACK_TITLE : MIRROR_TITLE), follow, dressed, on ? '' : t(MIRROR_SWAPS),
    on ? '' : t(MIRROR_AGAIN)].filter(Boolean)
  return { label: MIRROR_LABEL, title: lines.join('\n'), on, disabled: kind === 'copy' ? t(FOLLOWUP_TEXT.copy) : '' }
}
