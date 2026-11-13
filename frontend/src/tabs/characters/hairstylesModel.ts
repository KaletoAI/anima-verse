/**
 * hairstylesModel — pure helpers of the Hairstyles tab (FieldHairstyles; Task UI4 of
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md, the user's checklist for every character tab).
 * No React, no fetch: checked by `scripts/check_hairstyles_ui.mjs`.
 *
 * - `hairStepRows`: one row per step of the selected hairstyle's mode — HairDeck (a hub job) and Fit (on the
 *   CPU; it also binds the spring chains) for HairDeck hair, one row for hair in the body (its flow is the
 *   Figure tab's Build) and one for HAAR (not built yet). Each row has a traffic light, a short state, the
 *   reason in plain words (what changed, when, what fixes it) and its single button with the cost.
 * - `settingDue`: what a saved setting made due, written next to it.
 * - `placementMap` / `placementRuler`: the live placement preview — the fitted hair turned and moved by the
 *   difference between the dragged values and the ones the fit used, about the fit's own pivot — and the
 *   centimetre ruler with the forward shift drawn at the head.
 * - `previewMotion`: the live Stiffness preview — the previewed fit's spring groups with the dragged factor.
 * - `colourTint`: the live colour preview — a multiplier of the hair's vertex colours.
 * - `wearButton`: the Wear button's label with what the Build after it costs.
 * Returned strings are English; the caller passes `t`.
 */
import type { SecondaryMotionPayload, MotionGroup } from '@anima/scene-render'

type Tr = (s: string) => string
const EN: Tr = (s) => s
/** Formats a SYSTEM stamp for the reason lines ("12 Nov 20:31"); the component passes the clock-aware one. */
export type When = (stamp: string | null | undefined) => string

export type Light = 'green' | 'yellow' | 'red' | 'grey' | 'blue'

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
    steps: { fit?: { status: string; created_at: string | null } }
  } | null
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
}

/** The stale reasons that only the fit applies (all but a new HairDeck result). */
const FIT_REASONS = ['description_changed', 'base_changed', 'base_model_changed', 'fit_algorithm_updated',
  'colour_changed', 'placement_changed', 'swing_changed']

/** The base-body reasons: the line names when the base model was built. */
const BASE_REASONS = ['base_changed', 'base_model_changed']

function staleWords(reasons: readonly string[], t: Tr, baseBuilt = ''): string {
  return reasons.map((r) => t(STALE_TEXT[r] || r) + (baseBuilt && BASE_REASONS.includes(r) ? ` (${baseBuilt})` : ''))
    .join(' · ')
}

/** The rows of the selected hairstyle's steps (module docstring). */
export function hairStepRows(info: StepInput, t: Tr = EN, when: When = (s) => s || ''): StepRow[] {
  const mode = info.method
  if (mode === 'haar') {
    return [{ id: 'haar', name: t('HAAR'), light: 'grey', state: t('Not built yet'),
      reason: t('HAAR hair is not built yet — choose HairDeck or In the body under Settings.'), detail: '',
      button: null }]
  }
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
export function listLight(state: string | null | undefined, mode: string, due: readonly string[] = []): Light {
  if (mode === 'haar') return 'grey'
  if (state === 'current') return due.length ? 'yellow' : 'green'
  return state === 'stale' ? 'yellow' : 'grey'
}

/** The list row's reason: the server's freshness reason, else "Due: Fit" for a current fit with a step due. */
export function listReason(freshness: { state: string; reason?: string | null } | null | undefined,
  due: readonly string[] = [], t: Tr = EN): string {
  if (freshness?.state === 'current') {
    return due.length ? t('Due: {steps}').replace('{steps}', due.map((s) => t(s === 'fit' ? 'Fit' : 'HairDeck')).join(', '))
      : t('Current')
  }
  return freshness?.reason ? t(freshness.reason) : ''
}

/** What a saved setting made due — written next to it (rule: saving runs nothing). `kind` names the setting;
 *  null = nothing is due for it. */
export function settingDue(kind: 'placement' | 'colour' | 'swing' | 'stiffness', info: StepInput,
  t: Tr = EN): string | null {
  if (kind === 'stiffness') return null
  const reason = kind === 'placement' ? 'placement_changed' : kind === 'colour' ? 'colour_changed' : 'swing_changed'
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

/** The live Stiffness preview (GET …/hair `preview_motion`): every group's frequency for the dragged factor —
 *  `clamp(per_stiffness × chain stiffness × factor, min_hz, max_hz)`, as `hair_motion.freq_zeta` computes it.
 *  undefined when the fit has no swinging cards (made with Swing off, or no chains). */
export interface PreviewMotionInput {
  groups: Record<string, MotionGroup & { freq_hz?: number }>
  chain_stiffness: Record<string, number>
  freq: { per_stiffness: number; min_hz: number; max_hz: number }
  fit_swing: boolean
}

export function previewMotion(pm: PreviewMotionInput | null | undefined, factor: number):
  SecondaryMotionPayload | undefined {
  if (!pm || !pm.fit_swing || !Object.keys(pm.groups).length) return undefined
  const groups: Record<string, MotionGroup> = {}
  for (const [id, group] of Object.entries(pm.groups)) {
    const s = pm.chain_stiffness[id]
    const freq = s === undefined ? group.freq_hz
      : Math.round(Math.max(pm.freq.min_hz, Math.min(pm.freq.max_hz, pm.freq.per_stiffness * s * factor)) * 1000) / 1000
    groups[id] = { ...group, freq_hz: freq } as MotionGroup
  }
  return { rev: `hair-preview:${factor.toFixed(2)}`, groups }
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
