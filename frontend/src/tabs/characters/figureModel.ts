/**
 * figureModel — pure helpers of the figure UI (plan
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md, Task 9; the
 * Figure tab of Task 10 adds its own). No React, no fetch: checked by
 * `scripts/check_figure_ui.mjs`.
 *
 * Every worn piece has ONE mode on its ITEM (`outfit_piece.mesh_mode`), the
 * hair a mode of its own (Phase 1: the character's `hair_method`). Changing a
 * mode never spends anything; it marks every wearer with "N changes", and a
 * Build (one per character) makes what is missing. Returned strings are
 * English; the components put them through `t()`.
 */

/** How an outfit piece reaches the figure (`garment_set.MESH_MODES`). */
export type MeshMode = 'own_mesh' | 'painted' | 'in_body'
/** How the hair reaches the figure; `haar` is listed but not built yet (ruling 6). */
export type HairMode = 'hairdeck' | 'haar' | 'body'

/** The select's order. */
export const MESH_MODES: MeshMode[] = ['own_mesh', 'painted', 'in_body']
export const HAIR_MODES: HairMode[] = ['hairdeck', 'haar', 'body']

export const MESH_MODE_LABELS: Record<MeshMode, string> = {
  own_mesh: 'Own mesh',
  painted: 'Painted',
  in_body: 'In the body',
}

export const HAIR_MODE_LABELS: Record<HairMode, string> = {
  hairdeck: 'HairDeck',
  haar: 'HAAR',
  body: 'In the body',
}

/** What each mode does, one line (the select's hint). */
export const MESH_MODE_HINTS: Record<MeshMode, string> = {
  own_mesh: 'A finished mesh of its own, fitted on top of the body.',
  painted: "Painted onto the body's texture.",
  in_body: 'Meshed as part of the body.',
}

export const HAIR_MODE_HINTS: Record<HairMode, string> = {
  hairdeck: 'HairDeck makes hair cards from the profile picture in one step.',
  haar: '',
  body: 'The base body is rendered with the hair, so the hair is part of the body mesh — no hair mesh, no hair job.',
}

/** Why a hair mode cannot be chosen (written under the select), null = selectable. */
export function hairModeDisabled(m: HairMode): string | null {
  return m === 'haar' ? 'not built yet' : null
}

export function isMeshMode(v: unknown): v is MeshMode {
  return v === 'own_mesh' || v === 'painted' || v === 'in_body'
}

/** The kind default of a piece worn on `slots` (`garment_set.default_mesh_mode`): exactly feet → own mesh;
 *  outer among them, or both top and bottom → in the body; everything else → painted. */
export function defaultMeshMode(slots: readonly string[]): MeshMode {
  const worn = new Set(slots.filter(Boolean))
  if (worn.size === 1 && worn.has('feet')) return 'own_mesh'
  if (worn.has('outer') || (worn.has('top') && worn.has('bottom'))) return 'in_body'
  return 'painted'
}

/** The mode in effect: the stored one when valid, else the kind default (`garment_set.mesh_mode_of`). */
export function meshModeOf(stored: string | null | undefined, slots: readonly string[]): MeshMode {
  return isMeshMode(stored) ? stored : defaultMeshMode(slots)
}

// --- Open / closed (Task 11b, spec Addendum A) ---------------------------------------------------------------

/** How a closable piece is worn (`outfit_options.PIECE_STATES`); a piece without the option is always closed. */
export type PieceState = 'open' | 'closed'

/** The toggle's order: Closed first (the default). */
export const PIECE_STATES: PieceState[] = ['closed', 'open']

export const PIECE_STATE_LABELS: Record<PieceState, string> = {
  open: 'Open',
  closed: 'Closed',
}

/** Why "Can be worn open" cannot be ticked (written under it), null = it can: footwear (exactly feet) has no
 *  open/closed state (spec D-A3). */
export function closableDisabled(slots: readonly string[]): string | null {
  const worn = new Set(slots.filter(Boolean))
  return worn.size === 1 && worn.has('feet') ? 'Footwear has no open/closed state' : null
}

/** The piece details' single action that builds the OTHER state's own mesh (never built automatically):
 *  "Build the open mesh — 6 hub jobs" / "… — cost unknown"; with nothing left to run "Open mesh built". */
export function stateMeshAction(state: PieceState, jobs: number | null, t: (s: string) => string = (s) => s): string {
  if (jobs === 0) return state === 'open' ? t('Open mesh built') : t('Closed mesh built')
  const what = state === 'open' ? t('Build the open mesh') : t('Build the closed mesh')
  const cost = jobs === null ? t('cost unknown')
    : jobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(jobs))
  return `${what} — ${cost}`
}

/** "7 hub jobs" / "1 hub job" / "cost unknown". */
export function jobsText(hubJobs: number | null): string {
  if (hubJobs === null) return 'cost unknown'
  return `${hubJobs} hub ${hubJobs === 1 ? 'job' : 'jobs'}`
}

/** The Wardrobe line under a piece whose mode was changed (ruling 3): who wears the item now and ONE
 *  "Build for them" button with the summed cost; `reason` (written under it) when there is no button. */
export function wearersLine(n: number, hubJobs: number | null): {
  text: string; button: string | null; reason: string | null
} {
  const text = `worn by ${n} ${n === 1 ? 'character' : 'characters'} now`
  if (n <= 0) return { text, button: null, reason: 'Nobody wears it now' }
  return { text, button: `Build for them (${jobsText(hubJobs)})`, reason: null }
}

/** The line under the hair row after a hair mode change: the character's own pending changes and its
 *  Build (`GET /characters/{c}/figure` changes + cost). */
export function figureBuildLine(changes: number, hubJobs: number | null): {
  text: string; button: string | null; reason: string | null
} {
  if (changes <= 0) return { text: 'No changes', button: null, reason: 'Nothing to build' }
  return {
    text: `${changes} ${changes === 1 ? 'change' : 'changes'}`,
    button: `Build (${jobsText(hubJobs)})`,
    reason: null,
  }
}

/** The answers of POST …/build-wearers (per wearer) and POST …/figure/build. */
export const BUILD_STATUS: Record<string, string> = {
  started: 'Build started',
  queued: 'Build queued after the running one',
  current: 'Nothing to build',
  off: 'Off the figure pipeline',
}

// --- The Figure tab (Task 10; spec "The UI", rules for the buttons, ruling 8) ---------------------------

/** `t()` of the caller; the helpers default to English (the check reads that). */
type Tr = (s: string) => string
const EN: Tr = (s) => s

export type FigureStatus = 'up_to_date' | 'changes' | 'building' | 'failed'

/** One planned Build step (`figure_build.Step.as_dict`). */
export interface FigureStep {
  name: string
  label: string
  jobs: number | null
  item_id: string
  /** A chain that failed for its current input (ruling 7a): its error. */
  failed: string
  /** Base-body work only a manual Build runs (ruling 8a): why it is listed. */
  manual: string
}

/** A worn piece of the Figure tab (`figure_build._worn_rows`). */
export interface FigureWornRow {
  slot: string
  item_id: string
  name: string
  mode: MeshMode
  state: 'ready' | 'failed' | 'building' | 'left_out' | 'interim' | 'pending'
  note: string
  interim: boolean
  left_out: string
  failure: string
  /** Hub jobs its chain step plans (0 = none planned, null = unknown). */
  jobs: number | null
  /** Open / closed of a closable piece; null = not closable (NOT the readiness above). */
  piece_state: PieceState | null
  /** Own mesh + closable only: hub jobs of the OTHER state's mesh (0 = built, null = unknown / n.a.). */
  other_state_jobs: number | null
}

export interface FigureHairRow {
  mode: string
  state: 'ready' | 'failed' | 'building' | 'pending'
  note: string
  jobs: number | null
}

export interface FigureBodyPart {
  key: string
  state: string
  note?: string
}

/** GET /characters/{c}/figure (`figure_build.figure_info`). */
export interface FigurePayload {
  pipeline: boolean
  humanoid: boolean
  auto_build: boolean
  status: FigureStatus
  changes: Array<{ key: string; name: string; wanted: string; delivered: string; note?: string }>
  cost: { hub_jobs: number | null; note: string; steps: FigureStep[] }
  build: {
    running: boolean
    /** The step in flight; `index` counts from 1. */
    step: (FigureStep & { index?: number; count?: number }) | null
    queued: number
    failed: Record<string, { error: string; item_id?: string; items?: Record<string, string> }>
    skipped: string[]
    reason: string | null
    finished_at: string | null
  }
  served_url: string | null
  /** The saved outfit worn now, "" when none matches. */
  outfit: string
  worn: FigureWornRow[]
  hair: FigureHairRow | null
  body: {
    plain: FigureBodyPart & {
      jobs?: { view: number | null; front: number | null; model: number | null; after_front: number | null }
    }
    /** `state`: ready · missing · plain (nothing in the body). */
    shape: FigureBodyPart
    /** `state`: ready · missing · none (nothing painted). */
    texture: FigureBodyPart
  } | null
}

/** "1 change" / "N changes". */
export function changesText(n: number, t: Tr = EN): string {
  return n === 1 ? t('1 change') : t('{n} changes').replace('{n}', String(n))
}

function jobsTr(hubJobs: number | null, t: Tr): string {
  if (hubJobs === null) return t('cost unknown')
  return hubJobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(hubJobs))
}

function imageJobsTr(jobs: number | null, t: Tr): string {
  if (jobs === null) return t('cost unknown')
  return jobs === 1 ? t('1 image job') : t('{n} image jobs').replace('{n}', String(jobs))
}

/** The header's status line (spec sketch): "Status: up to date" or "2 changes · Build (7 hub jobs)". */
export function headerLine(status: FigureStatus, changes: number, hubJobs: number | null, t: Tr = EN): string {
  if (status === 'up_to_date') return t('Status: up to date')
  if (status === 'building') {
    return changes > 0 ? `${t('Status: building')} · ${changesText(changes, t)}` : t('Status: building')
  }
  const build = t('Build ({cost})').replace('{cost}', jobsTr(hubJobs, t))
  const head = changes > 0 ? changesText(changes, t) : t('Out of date')
  return status === 'failed' ? `${head} · ${t('a step failed')} · ${build}` : `${head} · ${build}`
}

/** The ONE primary button (rule 2): its label with the cost, and why it is disabled — written under it.
 *  A running Build does NOT disable it: a click queues the next one (`BUILD_RUNNING_NOTE`). */
export function buildButton(f: Pick<FigurePayload, 'pipeline' | 'cost' | 'build'>, t: Tr = EN): {
  label: string; disabled: string | null
} {
  const label = t('Build ({cost})').replace('{cost}', jobsTr(f.cost.hub_jobs, t))
  if (!f.pipeline) return { label, disabled: t('Off the figure pipeline') }
  if (!f.cost.steps.length && !f.build.running) return { label, disabled: t('Nothing to build') }
  return { label, disabled: null }
}

/** Written under Build while one runs — not a disable. */
export const BUILD_RUNNING_NOTE = 'A Build is running — the next one is queued'
/** Written under a single action whose result starts the automatic Build (Build automatically on). */
export const AUTO_BUILD_NOTE = 'then Build runs automatically'

/** What a single action of the Body details does and costs (rule 3: one thing, said before the click). */
export function singleAction(kind: 'view' | 'model' | 'face', jobs: number | null, t: Tr = EN): string {
  if (kind === 'view') return t('Regenerate this view — {cost}').replace('{cost}', imageJobsTr(jobs, t))
  if (kind === 'model') return t("Regenerate the plain body's mesh — {cost}").replace('{cost}', jobsTr(jobs, t))
  return t("Redo the plain body's face — {cost}").replace('{cost}', jobsTr(jobs, t))
}

/** Under "Run skin step" (and a new front): the base model is stale then, and only the next Build
 *  (a manual one, ruling 8a) rebuilds it — what that costs. */
export function staleBaseNote(jobs: number | null, t: Tr = EN): string {
  return t('Makes the base model stale — the next Build rebuilds it ({cost})').replace('{cost}', jobsTr(jobs, t))
}

/** The state column of a worn row (spec sketch) and the line under it. */
export function wornState(row: Pick<FigureWornRow, 'state' | 'mode' | 'jobs' | 'failure' | 'left_out' | 'note' | 'interim'>,
  t: Tr = EN): { text: string; sub: string | null } {
  const sub = row.interim ? t('shown painted until ready') : null
  switch (row.state) {
    case 'ready': return { text: t('✓ ready'), sub: null }
    case 'failed': return { text: t('failed — {reason}').replace('{reason}', row.failure || row.note), sub: null }
    case 'left_out': return { text: t('left out: {reason}').replace('{reason}', row.left_out || row.note), sub: null }
    case 'building': return { text: t('⏳ building'), sub }
    default:
      return {
        text: row.mode === 'own_mesh'
          ? t('⏳ mesh · {cost}').replace('{cost}', jobsTr(row.jobs, t))
          : t('⏳ waiting for the Build'),
        sub,
      }
  }
}

/** The state column of the hair row. */
export function hairState(hair: FigureHairRow, t: Tr = EN): { text: string; sub: string | null } {
  const sub = hair.note && hair.state !== 'failed' ? t(hair.note) : null
  switch (hair.state) {
    case 'ready': return { text: t('✓ ready'), sub: null }
    case 'failed': return { text: t('failed — {reason}').replace('{reason}', hair.note), sub: null }
    case 'building': return { text: t('⏳ building'), sub }
    default: return { text: t('⏳ HairDeck · {cost}').replace('{cost}', jobsTr(hair.jobs, t)), sub }
  }
}

/** The "Body:" line — plain body · shape · texture (spec sketch), with the pieces' names. */
export function bodyLine(body: NonNullable<FigurePayload['body']>, shapeNames: string[], textureNames: string[],
  t: Tr = EN): string {
  const named = (what: string, names: string[]) => names.length ? `${what} "${names.join(', ')}"` : what
  const plain = body.plain.state === 'ready' ? t('plain body ✓')
    : body.plain.state === 'missing' ? t('plain body: none yet') : t('plain body: older prompts')
  const shape = body.shape.state === 'plain' ? t('no shape (nothing in the body)')
    : `${named(t('shape'), shapeNames)} ${body.shape.state === 'ready' ? '✓' : '⏳'}`
  const texture = body.texture.state === 'none' ? t('nothing painted')
    : `${named(t('texture'), textureNames)} ${body.texture.state === 'ready' ? '✓' : '⏳'}`
  return [plain, shape, texture].join(' · ')
}
