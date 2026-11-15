/**
 * The full-body reference step (Ruling A87, server `app/core/full_body_reference.py`): the picture the A-pose front is
 * an edit of — one for the plain body (Base body → Views) and one per outfit (Figure → Dressed views). Pure helpers of
 * `FullBodyReferenceTile`: the step row (light, state, reason in plain words) and the cost lines, the SAME wording in
 * both places. Optional: Run all and the Build never generate the plain body's — they only say there is none
 * (`fullBodyBuildNote`); the worn outfit's is generated automatically before its dressed front (Ruling A104).
 */
import type { Light } from './hairstylesModel'
import { frontRegenerate, imageJobsTr } from './figureModel'
import type { PlainJobs } from './figureModel'

type Tr = (s: string) => string
const EN: Tr = (s) => s

/** A recorded full-body reference (a gallery picture). */
export interface FullBodyRecord {
  image: string
  sha256: string
  set_at?: string
  /** generated · gallery · upload (absent on an A74b record — picked from the gallery). */
  origin?: string
  /** The prompt it was generated with ("" when picked or uploaded). */
  prompt?: string
  made_from?: { image: string; sha256: string; kind: 'profile' | 'full_body' }
  label?: string
}

/** The in-memory state of a Generate (`full_body_reference.run_state`). */
export interface FullBodyRun { running: boolean; started_at: string | null; error: string | null; failed_at: string | null }

/** What a Generate would do now (`generate`). */
export interface FullBodyGenerate {
  /** Image jobs of one Generate (one render). */
  jobs: number
  ready: boolean
  /** Why it cannot run ("" when it can). */
  blocked: string
  /** What it is an edit of: profile · full_body ("" = nothing). */
  source: string
  source_url: string
  /** The prompt it sends (before LoRA triggers) — shown before the click. */
  prompt: string
}

/** GET …/base-body/full-body-reference (`full_body_reference.base_tile`). */
export interface BaseFullBodyInfo {
  kind: 'base'
  record: FullBodyRecord | null
  url: string
  gone: boolean
  run: FullBodyRun
  generate: FullBodyGenerate
  /** False: generated from another profile image than the current one. */
  made_from_current: boolean
  note: string
  /** The stored base front against what it is made from now (`front_reference_state`). */
  front: { current?: boolean; reason?: string; stored?: boolean; source?: string }
}

/** The wording shared by both places. */
export const FULL_BODY = 'Full-body reference'
export const NONE_BASE = 'Optional. Without one the front is made from the profile image. Generate makes a full-body picture of the character from the profile image, with all of its attributes.'
export const NONE_OUTFIT = 'Optional. Without one it is generated automatically before the dressed front (if that fails, the front is an edit of the body’s front). Generate makes a full-body picture of the character wearing this outfit now.'
export const SAVES_ONLY = 'Saves only — nothing renders.'

function sourceWords(source: string, t: Tr): string {
  return source === 'full_body' ? t('from the plain body’s full-body reference')
    : source === 'profile' ? t('from the profile image') : ''
}

/**
 * The step row of a full-body reference: generating → blue; the last Generate failed → red with the error; none set
 * → grey "Not set" with what the front is made from instead; the picture gone from the gallery → red; then
 * - plain body: the front not made from this picture yet → yellow "Due" (only a click renders it); generated from
 *   another profile image → yellow; else green "Used";
 * - outfit: nothing painted on the figure → grey "Not used now" (the server's reason); the dressed views not made
 *   from it yet → yellow "Due"; else green "Used".
 */
export function fullBodyRow(kind: 'base' | 'outfit', info: {
  record: FullBodyRecord | null; gone: boolean; run?: FullBodyRun; generate?: FullBodyGenerate
  front?: BaseFullBodyInfo['front']; made_from_current?: boolean; note?: string; applies?: boolean
  jobs?: number | null; label?: string
}, t: Tr = EN): { name: string; light: Light; state: string; reason: string; detail: string } {
  const name = kind === 'outfit' && info.label ? `${t(FULL_BODY)} · ${info.label}` : t(FULL_BODY)
  const detail = kind === 'outfit'
    ? t('An outfit here is the worn combination of clothing pieces (with the pieces worn open).')
    : t('The picture the A-pose front is an edit of.')
  if (info.run?.running) {
    return { name, light: 'blue', state: t('Generating'), detail,
      reason: `${t('Generating')} ${sourceWords(info.generate?.source || '', t)} — ${imageJobsTr(info.generate?.jobs ?? 1, t)}` }
  }
  if (info.run?.error) {
    return { name, light: 'red', state: t('Failed'), detail, reason: `${t('Generate failed')}: ${info.run.error}` }
  }
  if (!info.record) {
    return { name, light: 'grey', state: t('Not set'), detail, reason: t(kind === 'base' ? NONE_BASE : NONE_OUTFIT) }
  }
  if (info.gone) {
    return { name, light: 'red', state: t('Picture gone'), detail,
      reason: kind === 'base'
        ? t('The picture is not in the gallery any more — the front is made from the profile image. Generate, pick or upload another one, or clear it.')
        : t('The picture is not in the gallery any more — pick another one or clear it.') }
  }
  if (kind === 'base') {
    const front = info.front || {}
    if (front.stored && front.current === false && front.source === 'full_body') {
      return { name, light: 'yellow', state: t('Due'), detail,
        reason: t('The front is not made from this picture yet — regenerating the front makes it from it (beside the front below). Saving rendered nothing.') }
    }
    if (info.made_from_current === false) {
      return { name, light: 'yellow', state: t('Outdated'), detail, reason: t(info.note || '') }
    }
    return { name, light: 'green', state: t('Used'), detail, reason: t('The front is an edit of this picture.') }
  }
  if (!info.applies) return { name, light: 'grey', state: t('Not used now'), detail, reason: t(info.note || '') }
  if (info.jobs !== 0) {
    return { name, light: 'yellow', state: t('Due'), detail,
      reason: t('The dressed front is made from this picture with the next Build — saving rendered nothing.') }
  }
  return { name, light: 'green', state: t('Used'), detail, reason: t('The dressed front is an edit of this picture.') }
}

/** The Generate button with its cost before the click: "Generate — 1 image job" / "Regenerate — 1 image job". */
export function generateLabel(hasRecord: boolean, jobs: number, t: Tr = EN): string {
  return t(hasRecord ? 'Regenerate — {cost}' : 'Generate — {cost}').replace('{cost}', imageJobsTr(jobs, t))
}

/** Plain body: what a new full-body reference makes due — the front, with the front's Regenerate cost (Ruling A86's
 *  helper, so the number is the one on the front's button). */
export function baseFollowup(jobs: PlainJobs | undefined, t: Tr = EN): string {
  // Ruling A92: the front made from the full-body reference has no skin step — `front_full_body` image jobs.
  const action = frontRegenerate('full_body', jobs && jobs.front_full_body !== undefined
    ? { ...jobs, front: jobs.front_full_body } : jobs, t)
  return t('Then the front is due: {action}').replace('{action}', action.label)
}

/** Outfit: what a new full-body reference makes due — the dressed views at the next Build, or nothing while the
 *  picture would not be used (nothing painted). */
export function outfitFollowup(applies: boolean, jobs: number | null | undefined, t: Tr = EN): string {
  if (!applies) return t('Nothing becomes due now: nothing is painted on this figure, so the picture is not used')
  return t('Then the dressed views are due with the next Build — {cost}').replace('{cost}', imageJobsTr(jobs ?? null, t))
}

/** The information line beside Run all / the Build (never a due step — they never generate one). */
export function fullBodyBuildNote(kind: 'base' | 'outfit', set: boolean, method: string | undefined,
  t: Tr = EN, auto = false): string {
  if (set) return ''
  // Ruling A104: the worn outfit's reference is generated automatically right before its dressed front.
  if (kind === 'outfit' && auto) return t('Outfit full-body reference: none — generated automatically before the dressed front (+1 image job)')
  if (kind === 'outfit') return t('Outfit full-body reference: none — the dressed front is an edit of the body’s front')
  if (method === 'text') return t('Full-body reference: none — no profile image, the front is made from text')
  return t('Full-body reference: none — the front uses the profile image')
}
