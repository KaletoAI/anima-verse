/**
 * refusedAttemptsModel — the pure part of the "Refused images" panel of a piece's dialog (Ruling A79,
 * GarmentRefusedAttempts.tsx): which views of the image steps have refused attempts and nothing accepted, the
 * refusal reasons in plain words, the cost of "Use this attempt" and what Undo puts back.
 *
 * Server: `garment.steps[step][view]` (the images with their stored attempts and gate records), `use_runs`
 * (`garments.use_plans`: per attempt passing / in use / why not / the chain's estimate after the click) and
 * `use_undo` (`garments.use_undo_state`: what Undo of the last "Use this" takes back).
 */
import type { AttemptUsePlan, AttemptUsePlans, GarmentImageInfo, GarmentInfo, GarmentView, GateRecord } from './useGarment'
import type { Light } from './hairstylesModel'

type T = (s: string) => string

/** The image steps whose attempts can be taken by hand (`garment_images.EDIT_STEPS` of clothing). */
export const USE_STEPS = ['worn', 'ghost'] as const
export const USE_VIEWS: GarmentView[] = ['front', 'back']

/** A view named the way the step grid names it. */
export const VIEW_NAMES: Record<string, string> = {
  'worn:front': 'Worn view · front', 'worn:back': 'Worn view · back',
  'ghost:front': 'Piece-only view · front', 'ghost:back': 'Piece-only view · back',
  'cutout:front': 'Cut-out · front', 'cutout:back': 'Cut-out · back',
}

export const viewName = (step: string, view: string, t: T) => t(VIEW_NAMES[`${step}:${view}`] || `${step} ${view}`)

/** The steps after a click, as the grid names them (the estimate's step keys). */
export const FOLLOW_WORDS: Record<string, string> = {
  worn: 'worn views', ghost: 'piece-only views', cutout: 'cut-outs', mesh: 'mesh', fit: 'fit (CPU)',
}

/** A gate reason's first clause -> the plain words (the measured numbers stay on mouse-over). */
export const REASON_WORDS: Array<[string, string]> = [
  ['garment ends at another height than the worn piece', 'It ends at another height than the worn piece'],
  ['garment ends at another height than in the back view', 'It ends at another height than the back view'],
  ['skin left in the image', 'Skin of the body is left in the image'],
  ['more than the garment in the image', 'More than the piece is in the image (a body part or another garment)'],
  ['a part the worn piece does not have', 'It has a part the worn piece does not have (a strap, chain or band)'],
  ['garment width changed', 'Its width differs from the worn piece'],
  ['garment open where the worn piece is closed', 'It is open where the worn piece is closed'],
  ['garment closed where the worn piece is open', 'It is closed where the worn piece is open'],
  ['back shows the front opening', 'The back shows the front opening'],
  ['back puts on more than the front', 'The back puts on more than the front'],
  ['no garment in the ghost image', 'No piece in the image'],
  ['no garment found in the worn view', 'No piece found in the worn view'],
  ['nothing put on', 'Nothing was put on the body'],
  ['body outline outside the garment changed', 'The body changed outside the piece'],
  ['head changed', 'The head changed'],
  ['composite refused', 'The drafted back does not fit the body'],
  ['render failed', 'The render failed'],
]

/** `{text, detail}` of one gate reason: the plain words of its first clause (an unknown reason: that clause as it
 *  is) and the whole reason with its numbers for the mouse-over. */
export function reasonWords(reason: string, t: T): { text: string; detail: string } {
  const lower = reason.toLowerCase()
  const hit = REASON_WORDS.find(([head]) => lower.startsWith(head))
  if (hit) return { text: t(hit[1]), detail: reason }
  const head = reason.split(':')[0].trim()
  return { text: head ? head.charAt(0).toUpperCase() + head.slice(1) : reason, detail: reason }
}

export interface RefusedAttempt {
  attempt: number
  url: string
  /** When the attempt was rendered (its sidecar); null unknown. */
  created_at: string | null
  gate: GateRecord | null
  reasons: string[]
  plan: AttemptUsePlan | null
}

export interface RefusedView {
  step: string
  view: GarmentView
  attempts: RefusedAttempt[]
}

/** The views with stored REFUSED attempts and no accepted image — the ones a refusal holds up (a run refused
 *  every attempt), in chain order. Attempts that passed are not listed (the chain takes those itself). */
export function refusedViews(garment: GarmentInfo | null | undefined,
  useRuns: AttemptUsePlans | null | undefined): RefusedView[] {
  const out: RefusedView[] = []
  if (!garment) return out
  for (const step of USE_STEPS) {
    for (const view of USE_VIEWS) {
      const img: GarmentImageInfo | undefined = garment.steps[step]?.[view]
      if (!img || img.accepted) continue
      const plans = useRuns?.[step]?.[view] || {}
      const attempts = (img.attempts || [])
        .filter((a) => a.gate?.ok === false)
        .map((a) => ({ attempt: a.attempt, url: a.url, created_at: a.created_at ?? null, gate: a.gate,
          reasons: Array.isArray(a.gate?.reasons) ? (a.gate?.reasons as string[]) : [],
          plan: plans[String(a.attempt)] || null }))
      if (attempts.length) out.push({ step, view, attempts })
    }
  }
  return out
}

/** The label of "Use this attempt" with its cost (checklist 9): the click itself spends no hub job, then the
 *  chain's estimate after it — `Use this attempt · 0 hub jobs now, then 3 hub jobs (cut-outs, mesh)`. A blocked
 *  plan: the plain label (the reason stands under it). */
export function attemptUseLabel(plan: AttemptUsePlan | null, t: T): string {
  const base = t('Use this attempt')
  if (!plan || plan.block || plan.in_use) return base
  const f = plan.follow_up
  const now = t('0 hub jobs now')
  if (!f) return `${base} · ${now}`
  const steps = (f.steps || []).filter((s) => s !== 'fit').map((s) => t(FOLLOW_WORDS[s] || s)).join(', ')
  const then = f.hub_jobs == null ? t('then cost unknown')
    : f.hub_jobs === 1 ? t('then 1 hub job') : t('then {n} hub jobs').replace('{n}', String(f.hub_jobs))
  return `${base} · ${now}, ${then}${steps ? ` (${steps})` : ''}`
}

/** The light of a refused view: red — nothing accepted, the refusal holds the piece up. */
export const REFUSED_LIGHT: Light = 'red'

/** `use_undo` of the panel (`garments.use_undo_state`). */
export interface UseUndoState {
  step: string
  view: GarmentView
  attempt: number | null
  at: string | null
  passing: boolean
  available: boolean
  why_not: string
  images: Array<{ step: string; view: string; before: boolean }>
  mesh_before: boolean
  refusal_before: boolean
}

/** The light of the last "Use this": yellow — taken by hand (the steps after it are due); grey when Undo is no
 *  longer possible. */
export const undoLight = (u: UseUndoState): Light => (u.available ? 'yellow' : 'grey')

/** The headline of the last "Use this": "Accepted by you: Piece-only view · front, attempt 1" (a passing attempt:
 *  "Used by you: …"). */
export function undoHeadline(u: UseUndoState, t: T): string {
  const what = `${viewName(u.step, u.view, t)}, ${t('attempt')} ${u.attempt ?? '?'}`
  return `${u.passing ? t('Used by you') : t('Accepted by you')}: ${what}`
}

/** What Undo puts back, one line each (the button's mouse-over and the list under it). */
export function undoLines(u: UseUndoState, t: T): string[] {
  const order = ['worn', 'ghost', 'cutout']
  const images = [...u.images].sort((a, b) => order.indexOf(a.step) - order.indexOf(b.step) || a.view.localeCompare(b.view))
  return [
    ...images.map((i) => `${viewName(i.step, i.view, t)}: ${i.before ? t('the image from before comes back')
      : t('none before — the one there now goes')}`),
    u.mesh_before ? t('Mesh: the mesh from before comes back') : t('Mesh: none before — a mesh made since goes'),
    u.refusal_before ? t('The refusal comes back (the Build shows the step as failed again)') : '',
  ].filter(Boolean)
}

/** The Undo button: "Undo — 0 hub jobs". */
export const undoLabel = (t: T) => `${t('Undo')} — ${t('0 hub jobs')}`

/** Whether a Figure-tab row failed because every attempt of an image view was refused — its failure names
 *  "<worn|ghost> <front|back> refused" (`garment_images.GateRefused`); Details then shows "Refused images". */
export const imageRefusal = (failure: string | null | undefined): boolean =>
  /\b(worn|ghost) (front|back) refused\b/.test(failure || '')
