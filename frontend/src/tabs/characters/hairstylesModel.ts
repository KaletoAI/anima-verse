/**
 * hairstylesModel — pure helpers of the Hairstyles tab (FieldHairstyles; Task UI4 of
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md, the user's checklist for every character tab).
 * No React, no fetch: checked by `scripts/check_hairstyles_ui.mjs`.
 *
 * - `hairStepRows`: one row per step of the selected hairstyle's mode — HairDeck (a hub job) and Fit (on the
 *   CPU; it also binds the spring chains) for HairDeck hair, HAAR strands (3 hub jobs, one per seed) and Fit (CPU,
 *   one per seed) for HAAR hair, one row for hair in the body (its flow is the Figure tab's Build). Each row has a
 *   traffic light, a short state, the reason in plain words (what changed, when, what fixes it) and its single
 *   button with the cost.
 * - `haarVariantRows` / `variantAction` / `haarRunCost`: the HAAR variants sub-tab (strand-hair spec § 6.3.4) — one
 *   tile per seed with its light, its reason and its numbers, "In use" or "Use this — no hub job, CPU refit" — and
 *   the cost line beside a HAAR Run all.
 * - `settingDue`: what a saved setting made due, written next to it.
 * - `placementMap` / `placementRuler`: the live placement preview — the fitted hair turned and moved by the
 *   difference between the dragged values and the ones the fit used, about the fit's own pivot — and the
 *   centimetre ruler with the forward shift drawn at the head.
 * - `strandPreviewState` / `previewRootPose`: the per-strand preview (strand-hair spec § 6.2.5, ruling H-R2) — whether
 *   the hair swings, the drag turn and the motion buttons' root motion (Sway, Walk, Turn).
 * - `colourTint`: the live colour preview — a multiplier of the hair's vertex colours.
 * - `wearButton`: the Wear button's label with what the Build after it costs.
 * - `standardHairText` / `newHairstyleText`: the "New hairstyle" dialog's description field (Ruling A54) — it opens
 *   with the standard text, offers "Reset to standard text" once edited, and says before Create when there is none.
 * - `deleteSummary` / `deleteCost` / `afterDeleteSelection`: the Delete confirmation (Ruling A59) — what goes, what
 *   the Build after it costs, and the selection after it (the worn hairstyle, else none).
 * Returned strings are English; the caller passes `t`.
 */
import { DRAG_TURN_DEG_PER_PX } from '../../lib/modelTurn'
import type { HaarCutPanel, HairCut } from './hairCut'

type Tr = (s: string) => string
const EN: Tr = (s) => s
/** Formats a SYSTEM stamp for the reason lines ("12 Nov 20:31"); the component passes the clock-aware one. */
export type When = (stamp: string | null | undefined) => string

export type Light = 'green' | 'yellow' | 'red' | 'grey' | 'blue'

/** One HAAR seed of the hair GET's `haar` panel (`garments.haar_panel`). */
export interface HaarSeedEntry {
  seed: number
  /** null until the seed is fitted. */
  passed: boolean | null
  /** The gate's words (plain English with the numbers). */
  reasons: string[]
  metrics: Record<string, unknown>
  /** The tile (front | back of the fitted cards on the bald head); null without one. */
  tile_url: string | null
  /** The seed a Re-fit serves (the fsig names it). */
  served: boolean
  /** The hairstyle's own pick (`haar_seed`). */
  picked: boolean
  /** The seed of the fit the preview shows. */
  in_use?: boolean
}

/** The hair GET's `haar` panel (`garments.haar_panel`; null for another mode). */
export interface HaarPanel {
  ssig: string
  status: 'missing' | 'unfitted' | 'passed' | 'no variant passed'
  seeds: HaarSeedEntry[]
  next_seeds: number[]
  jobs: number
  picked: number | null
  served: number | null
  in_use?: number | null
  /** The backend the hair_strands occasion is meant to run on; `routed` false = none (nothing can be spent). */
  route?: { routed: boolean; backend: string | null } | null
  /** The Cut control (Ruling A71, `garments.haar_cut_panel`). */
  cut?: HaarCutPanel | null
}

/** No backend for HAAR (stage H3's words); the tab links the settings page beside it. */
export const HAAR_NO_ROUTE = 'No backend for occasion hair_strands — /admin/settings → Media Generation → Routing'
/** Where the routing is edited (the settings page's section/page hash). */
export const ROUTING_URL = '/admin/settings#image_generation/routing'

/** The parts of GET /characters/{c}/hair a step row reads (`useGarment.HairInfo`). */
export interface StepInput {
  pipeline: boolean
  method: string
  plain?: boolean
  equipped?: boolean
  base_prompts?: { state: string; reason?: string } | null
  body_built_at?: string | null
  run?: { steps: string[]; hub_jobs: number | null; note: string; refit: boolean } | null
  step_jobs?: Record<string, number>
  garment: {
    running_step: string | null
    failed: { step: string; error: string } | null
    stale_reasons: string[]
    preview_built_at?: string | null
    steps: {
      fit?: { status: string; created_at: string | null }
      haar?: { status: string; seeds?: number[]; failed?: Record<string, string | null>; created_at: string | null }
    }
  } | null
  haar?: HaarPanel | null
  hairdeck: {
    status: 'accepted' | 'refused' | 'missing'
    created_at: string | null
    error: string | null
    seed: number | null
    backend: string | null
    attempt: number | null
    images: { input: unknown }
    input_source?: string
    chains?: { count: number | null; fitted: boolean; swing: boolean } | null
  } | null
}

export interface StepRow {
  id: 'hairdeck' | 'fit' | 'body' | 'haar'
  name: string
  light: Light
  state: string
  reason: string
  /** The row's mouse-over: numbers and sources. */
  detail: string
  /** The single step (rule: it redoes the step even when it is current); null = no button of its own. */
  button: { label: string; disabled: string | null } | null
}

/** "1 hub job" / "N hub jobs" / "no hub job" / "cost unknown". */
export function jobsLabel(n: number | null | undefined, t: Tr = EN): string {
  if (n === null || n === undefined) return t('cost unknown')
  if (n === 0) return t('no hub job')
  return n === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(n))
}

/** Why the served fit is not the current one (`garments.garment_info` stale reasons), in plain words. */
export const STALE_TEXT: Record<string, string> = {
  description_changed: 'The hairstyle text changed',
  base_changed: 'The base body changed',
  base_model_changed: 'The base model was rebuilt',
  fit_algorithm_updated: 'The fit was improved by an update',
  hairdeck_changed: 'The profile picture or the HairDeck settings changed',
  colour_changed: 'The hair colour setting changed',
  placement_changed: 'The placement setting changed',
  swing_changed: 'The Swing setting changed',
  haar_changed: 'The hairstyle text changed',
  seed_changed: 'Another variant was picked',
  cut_changed: 'The cut setting changed',
}

/** The stale reasons that only the fit applies (all but a new HairDeck result). */
const FIT_REASONS = ['description_changed', 'base_changed', 'base_model_changed', 'fit_algorithm_updated',
  'colour_changed', 'placement_changed', 'swing_changed']
/** The stale reasons a HAAR fit applies (a new text asks HAAR again: the strands row). */
const HAAR_FIT_REASONS = ['base_changed', 'base_model_changed', 'fit_algorithm_updated', 'colour_changed',
  'seed_changed', 'cut_changed']

/** "1 CPU fit" / "N CPU fits". */
export function cpuFitsLabel(n: number, t: Tr = EN): string {
  return n === 1 ? t('1 CPU fit') : t('{n} CPU fits').replace('{n}', String(n))
}

/** The cost line beside a HAAR Run all (rule: the cost before the click): "3 hub jobs (~30–55 s each) + 3 CPU fits
 *  (~25 s each)" when the strands are due, "2 CPU fits (~25 s each), no hub job" when only fits are, "" else. */
export function haarRunCost(run: { steps: string[]; hub_jobs: number | null; cpu_fits?: number } | null | undefined,
  t: Tr = EN): string {
  if (!run || !run.steps.length) return ''
  const fits = run.cpu_fits ?? run.hub_jobs ?? 1
  if (run.steps.includes('haar')) {
    return t('{jobs} (~30–55 s each) + {fits} (~25 s each)').replace('{jobs}', jobsLabel(run.hub_jobs, t))
      .replace('{fits}', cpuFitsLabel(fits, t))
  }
  return t('{fits} (~25 s each), no hub job').replace('{fits}', cpuFitsLabel(fits, t))
}

/** The HAAR rows (strand-hair spec § 6.3.4): "HAAR strands · 3 hub jobs" (redo = the next 3 seeds, then their CPU
 *  fits) and "Fit · no hub job" (every new seed fitted on the CPU, the best passing one or the pick served). No
 *  backend routed: the strands row says so and its button is off — nothing is spent. */
function haarStepRows(info: StepInput, t: Tr, when: When): StepRow[] {
  const g = info.garment
  const hp = info.haar ?? null
  const due = new Set(info.run?.steps || [])
  const running = g?.running_step || null
  const queued = running === 'queued'
  const jobs = info.step_jobs?.haar ?? hp?.jobs ?? 3
  const fitJobs = info.step_jobs?.fit ?? 0
  const noRoute = hp?.route && !hp.route.routed ? t(HAAR_NO_ROUTE) : null
  if (!info.pipeline) {
    const reason = t('A temporary NPC has no figure — its hairstyles are not built.')
    return [
      { id: 'haar', name: t('HAAR strands · hub'), light: 'grey', state: t('Not built'), reason, detail: '', button: null },
      { id: 'fit', name: t('Fit · CPU'), light: 'grey', state: t('Not built'), reason, detail: '', button: null },
    ]
  }
  const step = g?.steps.haar
  const seeds = hp?.seeds.length ?? step?.seeds?.length ?? 0
  const cost = jobsLabel(jobs, t)
  const haarRow: StepRow = {
    id: 'haar', name: t('HAAR strands · hub'), light: 'grey', state: '', reason: '',
    detail: [hp?.route?.backend ? `${t('Backend')} ${hp.route.backend}` : '',
      hp?.seeds.length ? `${t('Seeds')} ${hp.seeds.map((e) => e.seed).join(', ')}` : '',
      hp?.next_seeds.length ? `${t('Next seeds')} ${hp.next_seeds.join(', ')}` : '',
      t('HAAR is licensed CC BY-NC 4.0 (non-commercial).')].filter(Boolean).join(' · '),
    button: { label: t('HAAR strands · {cost}').replace('{cost}', cost), disabled: noRoute ? t('No backend routed') : null },
  }
  const failedSeeds = Object.entries(step?.failed || {}).filter(([, e]) => e).map(([s, e]) => `${t('seed')} ${s}: ${e}`)
  if (running === 'haar' || (queued && due.has('haar'))) {
    haarRow.light = 'blue'
    haarRow.state = queued ? t('Queued') : t('Running')
    haarRow.reason = t('HAAR makes {n} variants from the hairstyle text (~30–55 s each).').replace('{n}', String(jobs))
  } else if (g?.failed?.step === 'haar') {
    haarRow.light = 'red'
    haarRow.state = t('Failed')
    haarRow.reason = t('{error} — the button asks for the next {n} seeds ({cost}).').replace('{error}', g.failed.error)
      .replace('{n}', String(jobs)).replace('{cost}', cost)
  } else if (step?.status === 'accepted' && seeds) {
    haarRow.light = 'green'
    haarRow.state = t('Current')
    haarRow.reason = t('{n} variants made {when} from the hairstyle text.').replace('{n}', String(seeds))
      .replace('{when}', when(step.created_at) || t('earlier'))
  } else if (noRoute) {
    haarRow.light = 'red'
    haarRow.state = t('No backend')
    haarRow.reason = `${noRoute} — ${t('nothing is spent until one is set.')}`
  } else if (step?.status === 'refused') {
    haarRow.light = 'red'
    haarRow.state = t('Refused')
    haarRow.reason = t('HAAR delivered no strands ({errors}) — the button asks for the next {n} seeds ({cost}).')
      .replace('{errors}', failedSeeds.join('; ') || t('no reason given')).replace('{n}', String(jobs))
      .replace('{cost}', cost)
  } else if (g?.stale_reasons.includes('haar_changed')) {
    haarRow.light = 'yellow'
    haarRow.state = t('Due')
    haarRow.reason = t('{reason} after the hair in use was made ({when}) — Run all makes {n} new variants ({cost}).')
      .replace('{reason}', t(STALE_TEXT.haar_changed)).replace('{when}', when(g.preview_built_at) || t('earlier'))
      .replace('{n}', String(jobs)).replace('{cost}', cost)
  } else {
    haarRow.state = t('Not made yet')
    haarRow.reason = t('No variants yet — Run all makes {n} from the hairstyle text ({cost}, ~30–55 s each).')
      .replace('{n}', String(jobs)).replace('{cost}', cost)
  }

  const fit = g?.steps.fit
  const fitReasons = (g?.stale_reasons || []).filter((r) => HAAR_FIT_REASONS.includes(r))
  const inUse = hp?.in_use ?? null
  const fitRow: StepRow = {
    id: 'fit', name: t('Fit · CPU'), light: 'grey', state: '', reason: '',
    detail: t('Fits every new variant on the base model on the CPU (~25 s each), checks it and uses the best passing one — or the one you picked under HAAR variants.'),
    button: { label: t('Fit · {cost}').replace('{cost}', jobsLabel(fitJobs, t)),
      disabled: seeds ? null : t('Needs the HAAR strands first') },
  }
  if (running === 'fit' || (queued && !due.has('haar') && due.has('fit'))) {
    fitRow.light = 'blue'
    fitRow.state = queued ? t('Queued') : t('Running')
    fitRow.reason = t('Fitting the variants on the base model (~25 s each).')
  } else if (g?.failed?.step === 'fit') {
    fitRow.light = 'red'
    fitRow.state = t('Failed')
    fitRow.reason = t('{error} — pick a variant under HAAR variants (no hub job), or make new ones ({cost}).')
      .replace('{error}', g.failed.error).replace('{cost}', cost)
  } else if (seeds && fit?.status === 'accepted' && !due.has('fit')) {
    fitRow.light = 'green'
    fitRow.state = t('Current')
    fitRow.reason = t('Fitted {when} on the current base model.').replace('{when}', when(fit.created_at) || t('earlier'))
      + (inUse !== null ? ' ' + t('Variant {seed} in use.').replace('{seed}', String(inUse)) : '')
  } else if (fitReasons.length && g?.preview_built_at) {
    fitRow.light = 'yellow'
    fitRow.state = t('Due')
    fitRow.reason = t('{reasons} after the fit in use ({when}) — {fix}; that fit stays in use until then.')
      .replace('{reasons}', staleWords(fitReasons, t, when(info.body_built_at)))
      .replace('{when}', when(g.preview_built_at) || t('earlier'))
      .replace('{fix}', due.has('haar') ? t('Run all makes the strands first, then fits')
        : t('Re-fit applies it ({cost})').replace('{cost}', jobsLabel(fitJobs, t)))
  } else {
    fitRow.state = t('Not fitted yet')
    fitRow.reason = seeds ? t('Re-fit makes it ({cost}).').replace('{cost}', jobsLabel(fitJobs, t))
      : t('Waits for the HAAR strands.')
  }
  return [haarRow, fitRow]
}

/** A HAAR variant tile's light: passed · refused · not fitted yet. */
export type VariantLight = 'ok' | 'bad' | 'wait'

export interface VariantRow {
  seed: number
  light: VariantLight
  /** Plain words: passed, or the gate's reasons. */
  reason: string
  /** Its numbers (mouse-over), one per line. */
  numbers: string
  served: boolean
  picked: boolean
  inUse: boolean
  tileUrl: string
}

/** The numbers of a variant's mouse-over (the fit's metrics), in this order. */
const VARIANT_NUMBERS: Array<[string, string, (v: number) => string]> = [
  ['tip_p50_rel_shoulder_cm', 'Tips vs. shoulder (median)', (v) => `${v > 0 ? '+' : ''}${v.toFixed(1)} cm`],
  ['length_cm_p50', 'Length (median)', (v) => `${v.toFixed(1)} cm`],
  ['inside_head_3mm', 'Strands over 3 mm in the head', (v) => String(Math.round(v))],
  ['eye_cards', 'Cards over the eyes', (v) => String(Math.round(v))],
  ['face_cards', 'Cards beside the face', (v) => String(Math.round(v))],
  ['flyaway_tip_share', 'Flyaway tips', (v) => `${(v * 100).toFixed(1)} %`],
  ['cards', 'Cards', (v) => String(Math.round(v))],
  ['strands', 'Strands', (v) => String(Math.round(v))],
]

/** One tile per seed of the HAAR panel (module docstring), in the server's order. */
export function haarVariantRows(panel: HaarPanel | null | undefined, t: Tr = EN): VariantRow[] {
  return (panel?.seeds || []).map((e) => {
    const numbers = VARIANT_NUMBERS.filter(([k]) => typeof e.metrics?.[k] === 'number' && Number.isFinite(e.metrics[k]))
      .map(([k, label, fmt]) => `${t(label)}: ${fmt(e.metrics[k] as number)}`)
    return {
      seed: e.seed,
      light: e.passed === null ? 'wait' : e.passed ? 'ok' : 'bad',
      reason: e.passed === null ? t('Not fitted yet — the Fit step fits it (no hub job).')
        : e.passed ? t('Passed every check.') : (e.reasons.join(' · ') || t('Refused')),
      numbers: numbers.join('\n'),
      served: !!e.served,
      picked: !!e.picked,
      inUse: !!e.in_use,
      tileUrl: e.tile_url || '',
    }
  })
}

/** What a variant tile offers: "In use" (the previewed fit's seed — it stays in use until the Re-fit of another
 *  pick), a pick or a better seed waiting for its Re-fit, else the button "Use this — no hub job, CPU refit" (saves
 *  the pick, runs nothing). */
export function variantAction(row: VariantRow, t: Tr = EN): { label: string; button: boolean } {
  if (row.inUse) return { label: t('In use'), button: false }
  if (row.picked) return { label: t('Picked — Re-fit applies it (no hub job)'), button: false }
  if (row.served) return { label: t('Best — Re-fit applies it (no hub job)'), button: false }
  return { label: t('Use this — no hub job, CPU refit'), button: true }
}

/** The base-body reasons: the line names when the base model was built. */
const BASE_REASONS = ['base_changed', 'base_model_changed']

function staleWords(reasons: readonly string[], t: Tr, baseBuilt = ''): string {
  return reasons.map((r) => t(STALE_TEXT[r] || r) + (baseBuilt && BASE_REASONS.includes(r) ? ` (${baseBuilt})` : ''))
    .join(' · ')
}

/** The rows of the selected hairstyle's steps (module docstring). */
export function hairStepRows(info: StepInput, t: Tr = EN, when: When = (s) => s || ''): StepRow[] {
  const mode = info.method
  if (mode === 'haar') return haarStepRows(info, t, when)
  if (mode === 'body') {
    const stale = info.base_prompts?.state === 'stale'
    const row: StepRow = { id: 'body', name: t('Hair in the plain body'), light: 'grey', state: '', reason: '',
      detail: t('The base body is rendered with this hair, so the hair is part of the body mesh — no hair job.'),
      button: null }
    if (!info.pipeline) {
      return [{ ...row, state: t('No figure'), reason: t('A temporary NPC has no figure — its hairstyles are not built.') }]
    }
    if (info.plain && !stale) {
      return [{ ...row, light: 'green', state: t('Current'),
        reason: t('The plain body was rendered with this hairstyle — built {when}.').replace('{when}',
          when(info.body_built_at) || t('earlier')) }]
    }
    if (info.plain && stale) {
      return [{ ...row, light: 'yellow', state: t('Due'),
        reason: t('{reason} — the Figure tab’s Build rebuilds the plain body.')
          .replace('{reason}', t(info.base_prompts?.reason || 'The base body prompts changed')) }]
    }
    return [{ ...row, state: t('Not in a body yet'),
      reason: info.equipped
        ? t('Worn — the Figure tab’s Build rebuilds the plain body with this hair.')
        : t('Not worn — wear it, then the Figure tab’s Build rebuilds the plain body with this hair.') }]
  }

  const g = info.garment
  const hd = info.hairdeck
  const due = new Set(info.run?.steps || [])
  const running = g?.running_step || null
  const queued = running === 'queued'
  const hubJobs = info.step_jobs?.hairdeck ?? null
  const fitJobs = info.step_jobs?.fit ?? 0
  if (!info.pipeline) {
    // A temporary NPC: no figure, so neither step ever runs — no buttons, one reason.
    const reason = t('A temporary NPC has no figure — its hairstyles are not built.')
    return [
      { id: 'hairdeck', name: t('HairDeck · hub'), light: 'grey', state: t('Not built'), reason, detail: '', button: null },
      { id: 'fit', name: t('Fit · CPU'), light: 'grey', state: t('Not built'), reason, detail: '', button: null },
    ]
  }

  // HairDeck: the hair cards from the profile picture (a hub job).
  const noInput = !hd?.images.input
  const hdRow: StepRow = {
    id: 'hairdeck', name: t('HairDeck · hub'), light: 'grey', state: '', reason: '',
    detail: hd ? [
      hd.seed !== null ? `${t('Seed')} ${hd.seed}` : '',
      hd.attempt ? `${t('Attempt')} ${hd.attempt}` : '',
      hd.backend || '',
      hd.input_source === 'beard_free' ? t('Input: the profile picture with the beard removed') : '',
    ].filter(Boolean).join(' · ') : '',
    button: {
      label: t('Regenerate — {cost}, then fit on the CPU').replace('{cost}', jobsLabel(hubJobs, t)),
      disabled: noInput ? t('Set a profile picture first') : null,
    },
  }
  if (running === 'hairdeck' || (queued && due.has('hairdeck'))) {
    hdRow.light = 'blue'
    hdRow.state = queued ? t('Queued') : t('Running')
    hdRow.reason = t('HairDeck makes the hair cards from the profile picture.')
  } else if (g?.failed?.step === 'hairdeck') {
    hdRow.light = 'red'
    hdRow.state = t('Failed')
    hdRow.reason = t('{error} — Regenerate tries again ({cost}).').replace('{error}', g.failed.error)
      .replace('{cost}', jobsLabel(hubJobs, t))
  } else if (hd?.status === 'refused') {
    hdRow.light = 'red'
    hdRow.state = t('Refused')
    hdRow.reason = t('{error} — Regenerate tries a new seed ({cost}).')
      .replace('{error}', hd.error || t('No hair found in the picture')).replace('{cost}', jobsLabel(hubJobs, t))
  } else if (hd?.status === 'accepted') {
    hdRow.light = 'green'
    hdRow.state = t('Current')
    hdRow.reason = t('Made {when} from the profile picture.').replace('{when}', when(hd.created_at) || t('earlier'))
  } else if (noInput) {
    hdRow.state = t('Not made yet')
    hdRow.reason = t('No profile picture — set one in the Profile tab, then Run all makes the hair.')
  } else if (g?.stale_reasons.includes('hairdeck_changed')) {
    hdRow.light = 'yellow'
    hdRow.state = t('Due')
    hdRow.reason = t('{reason} after the hair in use was made ({when}) — Run all or Regenerate makes it anew ({cost}).')
      .replace('{reason}', t(STALE_TEXT.hairdeck_changed)).replace('{when}', when(g.preview_built_at) || t('earlier'))
      .replace('{cost}', jobsLabel(hubJobs, t))
  } else {
    hdRow.state = t('Not made yet')
    hdRow.reason = t('No HairDeck result yet — Run all or Regenerate makes it ({cost}).')
      .replace('{cost}', jobsLabel(hubJobs, t))
  }

  // Fit: the hair cards on the base model, pushed out of its capsules, bound to the spring chains (CPU).
  const fit = g?.steps.fit
  const fitReasons = (g?.stale_reasons || []).filter((r) => FIT_REASONS.includes(r))
  const chains = hd?.chains
  const chainText = chains?.fitted
    ? (chains.count ? t('{n} spring chains').replace('{n}', String(chains.count)) : t('no spring chains'))
    : ''
  const fitRow: StepRow = {
    id: 'fit', name: t('Fit · CPU'), light: 'grey', state: '', reason: '',
    detail: [t('Fits the hair cards on the base model, keeps them out of the body and binds them to the spring chains.'),
      chainText].filter(Boolean).join(' · '),
    button: {
      label: t('Re-fit — {cost}').replace('{cost}', jobsLabel(fitJobs, t)),
      disabled: hd?.status !== 'accepted' ? t('Needs the HairDeck result first') : null,
    },
  }
  if (running === 'fit' || (queued && !due.has('hairdeck') && due.has('fit'))) {
    fitRow.light = 'blue'
    fitRow.state = queued ? t('Queued') : t('Running')
    fitRow.reason = t('Fitting the hair on the base model.')
  } else if (g?.failed?.step === 'fit') {
    fitRow.light = 'red'
    fitRow.state = t('Failed')
    fitRow.reason = t('{error} — change the placement, then Re-fit ({cost}).').replace('{error}', g.failed.error)
      .replace('{cost}', jobsLabel(fitJobs, t))
  } else if (fit?.status === 'accepted' && !due.has('fit')) {
    fitRow.light = 'green'
    fitRow.state = t('Current')
    fitRow.reason = t('Fitted {when} on the current base model.').replace('{when}', when(fit.created_at) || t('earlier'))
      + (chainText ? ` ${chainText}.` : '')
  } else if (fitReasons.length && g?.preview_built_at) {
    fitRow.light = 'yellow'
    fitRow.state = t('Due')
    fitRow.reason = t('{reasons} after the fit in use ({when}) — {fix}; that fit stays in use until then.')
      .replace('{reasons}', staleWords(fitReasons, t, when(info.body_built_at)))
      .replace('{when}', when(g.preview_built_at) || t('earlier'))
      .replace('{fix}', due.has('hairdeck') ? t('Run all makes HairDeck first, then fits')
        : t('Re-fit applies it ({cost})').replace('{cost}', jobsLabel(fitJobs, t)))
  } else {
    fitRow.state = t('Not fitted yet')
    fitRow.reason = hd?.status === 'accepted'
      ? t('Re-fit makes it ({cost}).').replace('{cost}', jobsLabel(fitJobs, t))
      : t('Waits for the HairDeck result.')
  }
  return [hdRow, fitRow]
}

/** One traffic light per hairstyle in the list (GET …/hairstyles: its freshness and the steps its Run all would
 *  run now, `due`): a current fit with a step due (a saved setting) is yellow too. */
export function listLight(state: string | null | undefined, _mode: string, due: readonly string[] = []): Light {
  if (state === 'current') return due.length ? 'yellow' : 'green'
  return state === 'stale' ? 'yellow' : 'grey'
}

/** The list row's reason: the server's freshness reason, else "Due: Fit" for a current fit with a step due. */
export function listReason(freshness: { state: string; reason?: string | null } | null | undefined,
  due: readonly string[] = [], t: Tr = EN): string {
  if (freshness?.state === 'current') {
    return due.length ? t('Due: {steps}').replace('{steps}', due.map((s) => t(s === 'fit' ? 'Fit'
      : s === 'haar' ? 'HAAR strands' : 'HairDeck')).join(', '))
      : t('Current')
  }
  return freshness?.reason ? t(freshness.reason) : ''
}

/** What a saved setting made due — written next to it (rule: saving runs nothing). `kind` names the setting;
 *  null = nothing is due for it. */
export function settingDue(kind: 'placement' | 'colour' | 'swing' | 'stiffness' | 'cut', info: StepInput,
  t: Tr = EN): string | null {
  if (kind === 'stiffness') return null
  const reason = kind === 'placement' ? 'placement_changed' : kind === 'colour' ? 'colour_changed'
    : kind === 'cut' ? 'cut_changed' : 'swing_changed'
  if (!info.garment?.stale_reasons.includes(reason)) return null
  return t('Saved, not applied — Re-fit applies it ({cost})').replace('{cost}', jobsLabel(info.step_jobs?.fit ?? 0, t))
}

// --- The live previews ---------------------------------------------------------------------------------------

export type Vec3 = [number, number, number]

/** Placement values: forward shift (m), forward tilt (°), hair width (×). */
export interface PlacementValues { forward_m: number; tilt_deg: number; width_scale: number }

/** The vertex map of the live placement preview. The fit placed every hair point Q as
 *  `R(a0)(Q − p) + p + f0·z` (pitched forward by `a0` about the x axis through the pivot `p`, +z down-front:
 *  (0, 0, r) → (0, −r·sin a, r·cos a); then moved `f0` along +z — `garment_hairdeck.adjust_placement`), then
 *  scaled the sides' reach beyond the head half width `h` by `w0` about the mid plane `cx`
 *  (`narrow_sides`: |x − cx| = h + (a − h)·w0 beyond h). The preview undoes the fitted values and applies the
 *  dragged ones: y/z turn by `a1 − a0` about `p` after removing `f0` and gain `f1`; x beyond `h` scales by
 *  `w1 / w0`. The push-out of the fit is not redone (an approximation the reason line says). */
export function placementMap(pivot: Vec3, fitted: PlacementValues, draft: PlacementValues, cx: number,
  halfWidth: number): (p: Vec3) => Vec3 {
  const da = ((draft.tilt_deg - fitted.tilt_deg) * Math.PI) / 180
  const cos = Math.cos(da)
  const sin = Math.sin(da)
  const ratio = fitted.width_scale > 0 ? draft.width_scale / fitted.width_scale : 1
  return ([x, y, z]) => {
    const dy = y - pivot[1]
    const dz = z - fitted.forward_m - pivot[2]
    const off = x - cx
    const a = Math.abs(off)
    const nx = a > halfWidth ? cx + Math.sign(off) * (halfWidth + (a - halfWidth) * ratio) : x
    return [nx, pivot[1] + dy * cos - dz * sin, pivot[2] + dy * sin + dz * cos + draft.forward_m]
  }
}

/** The placement the fit used (its record) or, without a fit, what the next fit uses (GET …/hair
 *  `hairdeck.placement`: stored values, null = automatic). */
export function fittedPlacement(p: {
  forward_m: number | null; tilt_deg: number | null; width_scale: number | null; default_forward_m: number
  fitted?: { forward_m?: number | null; tilt_deg?: number | null; width_scale?: number | null } | null
}): PlacementValues {
  const f = p.fitted
  return {
    forward_m: f?.forward_m ?? p.forward_m ?? p.default_forward_m,
    tilt_deg: f?.tilt_deg ?? p.tilt_deg ?? 0,
    width_scale: f?.width_scale ?? p.width_scale ?? 1,
  }
}

/** True when the map changes nothing (the dragged values are the fitted ones). */
export function placementIdentity(fitted: PlacementValues, draft: PlacementValues): boolean {
  return Math.abs(fitted.forward_m - draft.forward_m) < 1e-6 && Math.abs(fitted.tilt_deg - draft.tilt_deg) < 1e-6
    && Math.abs(fitted.width_scale - draft.width_scale) < 1e-6
}

/** The metre reference of the forward shift (the user's rule: a value in metres is seen at its distance): a
 *  centimetre ruler along +z beside the head at height `y` and side `x` — from 5 cm behind the pivot to 10 cm
 *  in front, a tick per cm (6 mm, every 5 cm 12 mm) — and, 12 mm above it, the shift itself from the pivot's z
 *  to `z + forward` in cyan (it reads against any hair colour), drawn twice 2 mm apart so it is not a hairline,
 *  with a bar at each end. Model space, metres. */
export const SHIFT_COLOUR = '#00e5ff'

export function placementRuler(pivot: Vec3, x: number, y: number, forwardM: number): Array<{
  points: Vec3[]; color: string
}> {
  const z0 = pivot[2] - 0.05
  const z1 = pivot[2] + 0.10
  const lines: Array<{ points: Vec3[]; color: string }> = [{ points: [[x, y, z0], [x, y, z1]], color: '#c9d1d9' }]
  for (let cm = 0; cm <= 15; cm++) {
    const z = z0 + cm / 100
    const len = cm % 5 === 0 ? 0.012 : 0.006
    lines.push({ points: [[x, y, z], [x, y - len, z]], color: '#c9d1d9' })
  }
  if (Math.abs(forwardM) > 1e-5) {
    // The shift with a bar at each end, so its length reads against the ticks below.
    const ys = y + 0.012
    for (const dy of [0, 0.002]) {
      lines.push({ points: [[x, ys + dy, pivot[2]], [x, ys + dy, pivot[2] + forwardM]], color: SHIFT_COLOUR })
    }
    lines.push({ points: [[x, ys - 0.006, pivot[2]], [x, ys + 0.008, pivot[2]]], color: SHIFT_COLOUR })
    lines.push({ points: [[x, ys - 0.006, pivot[2] + forwardM], [x, ys + 0.008, pivot[2] + forwardM]],
      color: SHIFT_COLOUR })
  }
  return lines
}

/** What the preview's per-strand hair does (strand-hair spec § 6.2.5): `swings` — the previewed fit has a strand
 *  record (`preview_strands_url`) and Swing is on, the preview runs the game's sim; `swing_off` — Swing is off, the
 *  hair stays still; `no_preview` — no fitted hair to preview. */
export type StrandPreviewState = 'swings' | 'swing_off' | 'no_preview'

export function strandPreviewState(info: { preview_strands_url?: string | null }, swing: boolean): StrandPreviewState {
  if (!info.preview_strands_url) return 'no_preview'
  return swing ? 'swings' : 'swing_off'
}

/** The Motion group's hint per state (English; the caller passes `t`). */
export const STRAND_PREVIEW_HINTS: Record<StrandPreviewState, string> = {
  swings: 'Drag the figure above to turn and tilt it — every strand swings.',
  swing_off: 'Swing is off — the hair stays still.',
  no_preview: 'No fitted hair yet — nothing to preview.',
}

/** Ruling H-R2: a drag in the Hairstyles preview turns the FIGURE, this many degrees per pixel of drag (360 px = half
 *  a turn) — since T-U4 the one rate of every model viewer (`lib/modelTurn.ts`), which also tilts it. */
export { DRAG_TURN_DEG_PER_PX }
export const dragTurnDeg = (px: number): number => px * DRAG_TURN_DEG_PER_PX
export const dragTurnRad = (px: number): number => (dragTurnDeg(px) * Math.PI) / 180

/** The preview's motion buttons (Ruling H-R2), ported from the spike viewer's `rootMotion` plus a turn. */
export type PreviewMotionKind = 'sway' | 'walk' | 'turn'
/** The turn: 180° out over `TURN_OUT_S`, held `TURN_HOLD_S`, back over `TURN_OUT_S` (cosine ease, zero speed at
 *  both ends). Its peak angular acceleration (π/2)·(π/2.5)² = 2.48 rad/s² stays under the strands' felt limit
 *  (`STRAND_ROOT_LIMITS.angAccel` 2.58 rad/s²), so the whole turn is felt by the hair. */
export const TURN_OUT_S = 2.5
export const TURN_HOLD_S = 1
export const TURN_S = 2 * TURN_OUT_S + TURN_HOLD_S
/** How fast a motion eases in and out (s, the spike's ramp). */
const AMP_RAMP_S = 0.5
const DEG = Math.PI / 180

/** The figure root's motion at time `t` (s) and amplitude `amp` (0..1): a yaw and a pitch about the head (rad) and
 *  an offset (m, x/y/z). Sway: yaw ±15° and pitch ±5° at 0.5 Hz; walk: ±25 cm along z at 0.5 Hz with a 3 cm bob at
 *  1 Hz (the spike's `rootMotion`); turn: 180° and back over `TURN_S`. amp 0 is the rest pose. */
export function previewRootPose(kind: PreviewMotionKind, t: number, amp: number): { yaw: number; pitch: number;
  offset: Vec3 } {
  if (kind === 'sway') {
    return { yaw: amp * 15 * DEG * Math.sin(2 * Math.PI * 0.5 * t),
      pitch: amp * 5 * DEG * Math.sin(2 * Math.PI * 0.5 * t + Math.PI / 2), offset: [0, 0, 0] }
  }
  if (kind === 'walk') {
    return { yaw: 0, pitch: 0,
      offset: [0, amp * 0.015 * (1 - Math.cos(2 * Math.PI * 1.0 * t)), amp * 0.25 * Math.sin(2 * Math.PI * 0.5 * t)] }
  }
  let yaw = 0
  if (t <= 0 || t >= TURN_S) yaw = 0
  else if (t < TURN_OUT_S) yaw = (Math.PI / 2) * (1 - Math.cos((Math.PI * t) / TURN_OUT_S))
  else if (t <= TURN_OUT_S + TURN_HOLD_S) yaw = Math.PI
  else yaw = (Math.PI / 2) * (1 + Math.cos((Math.PI * (t - TURN_OUT_S - TURN_HOLD_S)) / TURN_OUT_S))
  return { yaw: amp * yaw, pitch: 0, offset: [0, 0, 0] }
}

/** The amplitude after `dt` seconds easing towards `target` (the spike's ramp; never past the target). */
export function previewMotionAmp(amp: number, target: number, dt: number): number {
  return amp + (target - amp) * Math.min(1, Math.max(0, dt) / AMP_RAMP_S)
}

/** sRGB `#rrggbb` → linear [r, g, b] (0..1); null for anything else. */
export function hexToLinear(hex: string | null | undefined): Vec3 | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex || '')
  if (!m) return null
  const n = parseInt(m[1], 16)
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return [lin((n >> 16) & 255), lin((n >> 8) & 255), lin(n & 255)]
}

/** The live colour preview: the factor per channel (linear) that turns the hair's colour in use (`shown`) into
 *  the dragged one (`draft`), clamped to 0..4; null when either is unknown or they are the same. */
export function colourTint(shown: string | null | undefined, draft: string | null | undefined): Vec3 | null {
  const a = hexToLinear(shown)
  const b = hexToLinear(draft)
  if (!a || !b || (shown || '').toLowerCase() === (draft || '').toLowerCase()) return null
  return [0, 1, 2].map((i) => Math.max(0, Math.min(4, b[i] / Math.max(a[i], 1e-4)))) as Vec3
}

/** The Wear button (GET …/hairstyles `wear`): its label with what the Build after it costs, and the line under
 *  it. "Build automatically" on → the Build starts by itself: "Wear · Build 9 hub jobs"; off → nothing runs on
 *  the click: "Wear · no job now", the line names the Build the user starts later. */
export function wearButton(wear: { hub_jobs: number | null; automatic: boolean } | null | undefined,
  t: Tr = EN): { label: string; title: string } {
  if (!wear) return { label: t('Wear'), title: t('Wearing it is an outfit change') }
  if (wear.automatic && wear.hub_jobs === 0) {
    return { label: t('Wear · no hub job'), title: t('Build automatically is on: the Build after the click needs no hub job') }
  }
  if (wear.automatic) {
    return { label: t('Wear · Build {cost}').replace('{cost}', jobsLabel(wear.hub_jobs, t)),
      title: t('Build automatically is on: the Build starts after the click ({cost})')
        .replace('{cost}', jobsLabel(wear.hub_jobs, t)) }
  }
  return { label: t('Wear · no job now'),
    title: t('Nothing runs on the click; the Build you start then costs {cost}').replace('{cost}', jobsLabel(wear.hub_jobs, t)) }
}


/** The server's message for a new hairstyle without any text (`garment_hair.create_hairstyle`): the dialog shows it
 *  as a hint BEFORE Create when there is no standard text (Ruling A54), instead of the 400 after it. */
export const NO_HAIR_TEXT = 'No hair set — describe the hairstyle, or fill in the hair in Appearance'

/** The standard text a new hairstyle starts from (GET …/hairstyles `appearance_hair_text`: the Appearance's hair
 *  text, what the server uses for an empty description), whitespace collapsed like the server does; "" without
 *  one (a bald character, or a payload from before Ruling A54). The dialog's field opens with it. */
export function standardHairText(payload: { appearance_hair_text?: string | null } | null | undefined): string {
  return String(payload?.appearance_hair_text || '').split(/\s+/).filter(Boolean).join(' ')
}

/** The state of the dialog's description field against the standard text (Ruling A54):
 *  - `reset`: "Reset to standard text" is offered — there is a standard text and the field differs from it
 *    (blank-insensitive at the ends);
 *  - `fromStandard`: the field holds the standard text unchanged (the line under it names where it comes from);
 *  - `hint`: `NO_HAIR_TEXT` while there is no standard text and the field is blank — said before Create. */
export function newHairstyleText(standard: string, description: string):
  { reset: boolean; fromStandard: boolean; hint: string | null } {
  const std = standard.trim()
  const text = description.trim()
  return {
    reset: !!std && text !== std,
    fromStandard: !!std && text === std,
    hint: !std && !text ? NO_HAIR_TEXT : null,
  }
}

/** GET …/hairstyles/{id}/delete-preview (Ruling A59, `hairstyle_delete.delete_preview`): what deleting it removes. */
export interface DeletePreview {
  item_id: string
  name: string
  worn: boolean
  plain: boolean
  last: boolean
  files: Array<{ label: string; files: number; bytes: number }>
  total_files: number
  total_bytes: number
  item_files: number
  assembled: number
  shapes: Array<{ key: string; deletable: boolean; why: string }>
  outfit_sets: string[]
  /** What the Build after the delete costs; `steps` its step labels (shown on mouse-over). */
  estimate: { hub_jobs: number | null; automatic: boolean; note: string; steps?: string[] } | null
}

/** Bytes as "12 B", "340 KB", "1.2 MB". */
export function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function filesLabel(n: number, t: Tr): string {
  return n === 1 ? t('1 file') : t('{n} files').replace('{n}', String(n))
}

/** What the Build after the delete costs (the preview's `estimate`, like the Wear button's): "Build automatically"
 *  on → the Build starts by itself; off → nothing runs on the click. 0 hub jobs = local, on the CPU. */
export function deleteCost(estimate: DeletePreview['estimate'], t: Tr = EN): string {
  if (!estimate) return t('no figure — nothing is built')
  if (estimate.hub_jobs === 0) {
    return estimate.automatic ? t('the Build starts by itself — local, no hub job')
      : t('nothing runs now; the Build you start then is local, no hub job')
  }
  return (estimate.automatic ? t('the Build starts by itself — {cost}')
    : t('nothing runs now; the Build you start then costs {cost}')).replace('{cost}', jobsLabel(estimate.hub_jobs, t))
}

/** The Delete confirmation's content (Ruling A59): `removed` — one line per thing that goes (the item, each group
 *  of generated files with its count and size, the assembled models, the body shapes); `notes` — what follows
 *  (the worn note with the Build's real cost, the plain body, the last hairstyle, the outfit sets, the shapes that
 *  stay), always ending with "This cannot be undone.". */
export function deleteSummary(p: DeletePreview, t: Tr = EN): { removed: string[]; notes: string[] } {
  const removed = [p.item_files ? t('The hairstyle item and its picture') : t('The hairstyle item')]
  for (const f of p.files) removed.push(`${t(f.label)}: ${filesLabel(f.files, t)} (${sizeLabel(f.bytes)})`)
  if (!p.files.length) removed.push(t('No generated files are stored for it.'))
  if (p.assembled) {
    removed.push(t('Assembled models with this hair: {files} — re-assembled without it on the CPU')
      .replace('{files}', filesLabel(p.assembled, t)))
  }
  const gone = p.shapes.filter((s) => s.deletable).length
  if (gone) removed.push(t('Body shapes with only this hair: {n}').replace('{n}', String(gone)))
  const notes: string[] = []
  const cost = deleteCost(p.estimate, t)
  if (p.worn) notes.push(t('This hairstyle is worn — the figure will be rebuilt without hair ({cost}).').replace('{cost}', cost))
  else if (p.plain) notes.push(t('The plain body was made with this hairstyle — the figure will be rebuilt ({cost}).').replace('{cost}', cost))
  if (p.last) notes.push(t('It is the last hairstyle — the character then has none.'))
  if (p.outfit_sets.length) {
    notes.push(t('Outfit sets that wear it then leave the hair as it is: {sets}.').replace('{sets}', p.outfit_sets.join(', ')))
  }
  const kept = p.shapes.length - gone
  if (kept) {
    notes.push(t('Body shapes kept for now: {n} — the Figure tab offers them once nothing stands on them.')
      .replace('{n}', String(kept)))
  }
  notes.push(t('This cannot be undone.'))
  return { removed, notes }
}

/** The selection after a delete: no hairstyle selected. */
export const NONE_SELECTED = '\u0000none'

/** The selection after a delete (Ruling A59): the worn hairstyle of the reloaded list, else none. */
export function afterDeleteSelection(list: { hairstyles: Array<{ id: string; worn: boolean }> } | null | undefined): string {
  return list?.hairstyles.find((h) => h.worn)?.id || NONE_SELECTED
}

// --- The HAAR Cut (Ruling A71) --------------------------------------------------------------------------------

/** The landmark names of "Ends at", in plain words (`hair_cut.LANDMARKS`). */
export const CUT_AT_LABELS: Record<string, string> = {
  chin: 'Chin', shoulder: 'Shoulder', shoulder_blades: 'Shoulder blades', mid_back: 'Mid back', waist: 'Waist',
}

/** One line of what a cut does: "Full length · ends Auto (3 cm)", "Max 30 cm · ends 1.5 cm", "At the shoulder · …". */
export function cutLabel(cut: HairCut | null | undefined, autoEndsCm: number, t: Tr = EN): string {
  const c = cut ?? {}
  const length = c.at ? t('Ends at {where}').replace('{where}', t(CUT_AT_LABELS[c.at] ?? c.at))
    : c.max_cm != null ? t('Max {n} cm').replace('{n}', String(c.max_cm)) : t('Full length')
  const ends = c.ends_cm != null ? t('soft tip {n} cm').replace('{n}', String(c.ends_cm))
    : t('soft tip Auto ({n} cm)').replace('{n}', String(autoEndsCm))
  return `${length} · ${ends}`
}
