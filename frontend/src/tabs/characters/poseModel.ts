/**
 * poseModel — the pure helpers of the Pose tab (Task UI5, the tab checklist): the light, state and reason of each
 * dressed view and of the outfit model built from them, and the flow head's words. No React, no fetch — the check
 * script (scripts/check_pose_ui.mjs) bundles this file alone.
 */
import type { Light } from './hairstylesModel'
import type { Freshness } from './FreshnessBadge'

type Tr = (s: string) => string
const EN: Tr = (s) => s

/** What the server reports of one stored render (model-refs info). */
export interface PoseRender {
  filename?: string
  created_at?: string
  model?: string
  warning?: string
  freshness?: Freshness | null
}

/** One step row of the tab (rendered by StepRowView). */
export interface PoseRow {
  light: Light
  state: string
  reason: string
  detail: string
}

/** The views are rendered by the character's Build on the figure pipeline (said once under the flow head). */
export const VIEWS_BY_BUILD = 'The Figure tab’s Build renders these views and builds the outfit model from them.'
/** A back or side view is composited from its draft (the back row's mouse-over). */
export const DRAFT_NOTE = 'A back or side view is a draft rendered from the dressed front, composited onto the base '
  + 'view on the CPU — no second render.'
/** After a single view render: the follow-up, on the button's mouse-over (the texture is repainted on the CPU). */
export const VIEW_FOLLOWUP = 'Then the outfit model is due: the Build repaints it on the CPU — no hub job'
/** After the main view: the back view's draft is made from it. */
export const MAIN_FOLLOWUP = 'The back view is then due too — its draft is made from this view (1 image job)'

/**
 * One dressed view (and the draft it was composited from, if any) as a step: rendering now → blue "Rendering";
 * nothing stored → yellow "Not rendered yet"; the view or its draft outdated → yellow "Outdated" with the server's reason
 * (the view's first); kept although its fit check failed → yellow "Kept with a warning", the warning as reason;
 * else green "Current". The mouse-over names the reason in full and the action that resolves it.
 */
export function viewRow(info: PoseRender | null | undefined, draft: PoseRender | null | undefined, running: boolean,
  t: Tr = EN): PoseRow {
  if (running) return { light: 'blue', state: t('Rendering'), reason: '', detail: '' }
  if (!info) return { light: 'yellow', state: t('Not rendered yet'), reason: '', detail: '' }
  const stale = [info.freshness, draft?.freshness].find((f) => f?.state === 'stale')
  if (stale) {
    const reason = t(stale.reason || 'Made from older data')
    return { light: 'yellow', state: t('Outdated'), reason,
      detail: [reason, stale.action ? t(stale.action) : '', info.warning || ''].filter(Boolean).join('\n') }
  }
  if (info.warning) return { light: 'yellow', state: t('Kept with a warning'), reason: info.warning, detail: info.warning }
  return { light: 'green', state: t('Current'), reason: '', detail: '' }
}

/** The outfit model's status on the pipeline (`base_info.outfit`). */
export interface PoseOutfit {
  status: 'running' | 'failed' | 'stale' | 'ready' | 'missing'
  error: string
  warnings: string[]
}

/**
 * The outfit model as a step: running → blue "Building now"; failed → red "Failed", the error; stale → yellow
 * "Outdated", `staleText` (figureModel.staleModelText); missing → yellow "Not built yet", "The Build makes it";
 * ready → green "Ready", the proof's numbers (`proofLine`). Views the guard left out are warnings: the first is the
 * reason of a ready model (yellow then), all of them on mouse-over.
 */
export function outfitRow(o: PoseOutfit, staleText: string, proofLine: string, t: Tr = EN): PoseRow {
  const warnings = o.status === 'running' ? [] : (o.warnings || [])
  const detail = warnings.join('\n')
  if (o.status === 'running') return { light: 'blue', state: t('Building now'), reason: '', detail: '' }
  if (o.status === 'failed') return { light: 'red', state: t('Failed'), reason: o.error, detail: o.error }
  if (o.status === 'stale') return { light: 'yellow', state: t('Outdated'), reason: staleText, detail }
  if (o.status === 'missing') return { light: 'yellow', state: t('Not built yet'), reason: t('The Build makes it'), detail }
  if (warnings.length) return { light: 'yellow', state: t('Ready — with warnings'), reason: warnings[0], detail }
  return { light: 'green', state: t('Ready'), reason: proofLine, detail: proofLine }
}

/**
 * The flow head from the rows' lights: a Build running → blue "Building now"; a red row → red "A step failed";
 * yellow rows → yellow "1 step due" / "{n} steps due"; else green "Up to date". Grey rows count as nothing to do.
 */
export function poseHead(lights: readonly Light[], buildRunning: boolean, t: Tr = EN): { light: Light; words: string } {
  if (buildRunning || lights.includes('blue')) return { light: 'blue', words: t('Building now') }
  if (lights.includes('red')) return { light: 'red', words: t('A step failed') }
  const due = lights.filter((l) => l === 'yellow').length
  if (due === 1) return { light: 'yellow', words: t('1 step due') }
  if (due > 1) return { light: 'yellow', words: t('{n} steps due').replace('{n}', String(due)) }
  return { light: 'green', words: t('Up to date') }
}

/** Off the pipeline: what "Render all views" costs — the main view and every switched-on extra view. */
export function renderAllLabel(views: number, t: Tr = EN): string {
  const n = 1 + Math.max(0, views)
  return (n === 1 ? t('Render all views — 1 image job') : t('Render all views — {n} image jobs'))
    .replace('{n}', String(n))
}
