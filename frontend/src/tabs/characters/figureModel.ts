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

/** The default mode of a piece worn on `slots` (`garment_set.default_mesh_mode`): in the body for every slot
 *  set, footwear included (Ruling A10 — own mesh and painted must be chosen). `slots` is unused today. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function defaultMeshMode(_slots: readonly string[]): MeshMode {
  return 'in_body'
}

/** The mode in effect: the stored one when valid, else the default (`garment_set.mesh_mode_of`). */
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
  off: 'No figure — humanoid characters that are not temporary NPCs only',
  failed: 'Build failed — the profile could not be read',
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
  state: 'ready' | 'failed' | 'fit_refused' | 'building' | 'left_out' | 'interim' | 'pending'
  note: string
  interim: boolean
  left_out: string
  failure: string
  /** Ruling A23 b: its fit on the body shape was refused (the reason; "" otherwise) — the figure built before stays
   *  served; the row offers Re-fit and Regenerate mesh. */
  fit_refused?: string
  /** Hub jobs its chain step plans (0 = none planned, null = unknown). */
  jobs: number | null
  /** Open / closed of a closable piece; null = not closable (NOT the readiness above). */
  piece_state: PieceState | null
  /** Own mesh + closable only: hub jobs of the OTHER state's mesh (0 = built, null = unknown / n.a.). */
  other_state_jobs: number | null
  /** An own-mesh piece in the body shape (ruling A11): until its own mesh is ready (`mesh`), or its mesh is
   *  ready and served and the next Build takes it out of the shape (`build`); null otherwise. */
  in_body_until?: 'mesh' | 'build' | null
}

export interface FigureHairRow {
  /** The worn hairstyle's name and id (Task 13); "" when none is worn. */
  name?: string
  item_id?: string
  mode: string
  state: 'ready' | 'failed' | 'building' | 'pending'
  note: string
  /** Hub jobs of its plan step — the plain body's rebuild when `rebuild` (0 = none planned, null = unknown). */
  jobs: number | null
  /** The hair is wanted in the body and only the plain body's rebuild puts it there (ruling F13 a). */
  rebuild?: boolean
}

/** One pending change (`figure.pending_changes` + `figure_build._with_jobs`). */
export interface FigureChange {
  key: string
  name: string
  wanted: string
  delivered: string
  note?: string
  /** Hub jobs of the plan step that builds it (0 = none planned, null = unknown). */
  jobs?: number | null
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
  changes: FigureChange[]
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

/** The note of the hair's change while the plain body must be rebuilt with the hair (`figure.HAIR_REBUILD`). */
export const HAIR_REBUILD_NOTE = 'in the body → plain body rebuild'
/** Written under the Build button: the cost is an estimate of first attempts (ruling F13 c). */
export const ESTIMATE_NOTE = 'Hub jobs are an estimate — retries extra'

/** One pending change as a line, its cost named (fix round T12-F1, F13 a/b):
 *  the hair's rebuild → "Hair · in the body → plain body rebuild, 9 hub jobs";
 *  an open / closed state → "Black jacket worn open — open mesh missing (6 hub jobs)";
 *  else "Name: note (N hub jobs)" — the cost only when something is planned. */
export function changeLine(c: FigureChange, t: Tr = EN): string {
  const cost = c.jobs === undefined || c.jobs === 0 ? '' : jobsTr(c.jobs, t)
  if (c.key === 'hair' && c.note === HAIR_REBUILD_NOTE) {
    return `${t(c.name)} · ${t(c.note)}${cost ? `, ${cost}` : ''}`
  }
  const head = c.note
    ? (c.key.endsWith(':state') ? `${c.name} ${t(c.note)}` : `${t(c.name)}: ${t(c.note)}`)
    : t(c.name)
  return cost ? `${head} (${cost})` : head
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
 *  A running Build does NOT disable it: a click queues the next one (`BUILD_RUNNING_NOTE`). Every humanoid is
 *  on the pipeline (Ruling A13); one without a plain body yet (`body.plain.state` missing) gets "Build base
 *  body (cost)" — the same Build, whose plan starts with the plain body (only a manual Build makes it, ruling
 *  8a), the cost the whole click. */
export function buildButton(f: Pick<FigurePayload, 'cost' | 'build' | 'body'>, t: Tr = EN): {
  label: string; disabled: string | null
} {
  const cost = jobsTr(f.cost.hub_jobs, t)
  const label = noBaseBody(f) ? t('Build base body ({cost})').replace('{cost}', cost)
    : t('Build ({cost})').replace('{cost}', cost)
  if (!f.cost.steps.length && !f.build.running) return { label, disabled: t('Nothing to build') }
  return { label, disabled: null }
}

/** The humanoid has no plain body yet: its figure starts with "Build base body" (Ruling A13). */
export function noBaseBody(f: Pick<FigurePayload, 'body'>): boolean {
  return f.body?.plain.state === 'missing'
}

/** Under "Build base body": what is on screen until then and what the click makes (Ruling A13 — nothing is
 *  rebuilt by itself). */
export const NO_BASE_BODY_NOTE = 'No base body yet — nothing is rebuilt by itself: the character keeps the model it '
  + 'has until you start this Build, which makes the base body from the profile picture first, then the figure on it.'

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

/** Under "Run skin step" (and a new front): the base model is stale then, and only the next Build you start
 *  (a manual one — an automatic Build never rebuilds the plain body, ruling 8a) rebuilds it — what that costs. */
export function staleBaseNote(jobs: number | null, t: Tr = EN): string {
  return t('Makes the base model stale — the next Build you start rebuilds it ({cost})')
    .replace('{cost}', jobsTr(jobs, t))
}

/** Under the state of an own-mesh piece in the body shape until its mesh is ready (ruling A11). */
export const IN_BODY_UNTIL_MESH = 'in the body until its own mesh is ready'
/** ... once its mesh is ready and served, until the next Build takes it out of the shape. */
export const IN_BODY_UNTIL_BUILD = 'own mesh ready — in the body until the next Build'

/** Under an in-body piece whose body shape is not built yet: nothing is painted in its place any more (Ruling C4,
 *  Task 11g fix round 2) — the Build meshes the shape first, the figure built before stays served meanwhile. */
export const IN_BODY_UNTIL_SHAPE = 'not in the 3D figure until its body shape is built'

/** Under a piece whose fit on the body shape was refused (Ruling A23): nothing lacking it is published. */
export const FIT_REFUSED_NOTE = 'the figure built before stays shown until it fits'

/** The state column of a worn row (spec sketch) and the line under it. */
export function wornState(row: Pick<FigureWornRow, 'state' | 'mode' | 'jobs' | 'failure' | 'left_out' | 'note' | 'interim'
  | 'in_body_until' | 'fit_refused'>, t: Tr = EN): { text: string; sub: string | null } {
  const sub = row.in_body_until === 'mesh' ? t(IN_BODY_UNTIL_MESH)
    : row.in_body_until === 'build' ? t(IN_BODY_UNTIL_BUILD)
      : row.interim ? t(IN_BODY_UNTIL_SHAPE) : null
  if (row.in_body_until === 'build' && row.state !== 'failed') {
    return { text: row.state === 'building' ? t('⏳ building') : t('⏳ waiting for the Build'), sub }
  }
  switch (row.state) {
    case 'ready': return { text: t('✓ ready'), sub: null }
    case 'failed': return { text: t('failed — {reason}').replace('{reason}', row.failure || row.note), sub: null }
    case 'fit_refused': return {
      text: t('Fit refused — {reason}').replace('{reason}', row.fit_refused || row.note),
      sub: t(FIT_REFUSED_NOTE),
    }
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
    default:
      return {
        text: hair.rebuild
          ? t('⏳ plain body rebuild · {cost}').replace('{cost}', jobsTr(hair.jobs, t))
          : t('⏳ HairDeck · {cost}').replace('{cost}', jobsTr(hair.jobs, t)),
        sub,
      }
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

/** The Figure tab's one line on the base body (Task UI1 — its steps live in the Base body tab). */
export function baseBodyLine(state: string, t: Tr = EN): string {
  if (state === 'ready') return t('Base body: up to date — its views, model, face and rig are in the Base body tab')
  if (state === 'missing') return t('Base body: none yet — the Build makes it, or Run all in the Base body tab')
  return t('Base body: outdated — the Build refreshes it, or Run all in the Base body tab')
}

/** Why a stored outfit model is stale (`base_body.outfit_info` / `model3d` info `stale_reason`). */
export type ModelStaleReason = 'older_base' | 'before_pipeline' | 'detail_changed' | 'figure' | 'outfit_body'

/** The line under a stale outfit model (Pose tab, 3D tab). `before_pipeline` is a model made without the base
 *  body — since Ruling A13 every humanoid's old model, until its first Build makes the base body. */
export function staleModelText(reason: string | null | undefined, t: Tr = EN): string {
  switch (reason) {
    case 'before_pipeline': return t('Made without the base body — the Figure tab’s Build replaces it')
    case 'detail_changed': return t('Built for another body detail under the clothing — rebuild it')
    case 'figure': return t('Built as another figure than the worn pieces show now — rebuild it')
    case 'outfit_body': return t('Built on an older body shape — rebuild it')
    default: return t('Built on an older base body — rebuild it')
  }
}

// --- The Hairstyles tab (Task 14, Rulings P2/P3; the user's rule R1–R4) ---------------------------------------

/** One hairstyle the character owns (GET /characters/{c}/hairstyles → `garment_hair.hairstyle_list`). */
export interface Hairstyle {
  id: string
  name: string
  description: string
  mode: HairMode
  worn: boolean
  /** The plain body is this hairstyle's body (its hair is in the plain body when the mode is `body`). */
  plain: boolean
  freshness: { state: string; reason?: string | null } | null
}

/** GET /characters/{c}/hairstyles. */
export interface HairstylesPayload {
  hairstyles: Hairstyle[]
  /** The mode a new hairstyle gets (the world's `base_body.hairstyle_default_mode`). */
  default_mode: HairMode
  modes: HairMode[]
  /** The modes that can be chosen today (`haar` is not built yet). */
  built_modes: HairMode[]
}

/** "<name> · <mode label>" — a hairstyle as the list and the outfit-set select name it. */
export function hairstyleLabel(h: { name: string; id: string; mode: string }, t: Tr = EN): string {
  const mode = HAIR_MODE_LABELS[h.mode as HairMode] || h.mode
  return `${h.name || h.id} · ${t(mode)}`
}

/** The Hairstyles tab's list: the worn hairstyle first, then the others in the server's order, each with its
 *  label. `wornId` is the worn hairstyle's id ("" = none worn) — it wins over a stale `worn` flag. */
export function hairstyleRows(owned: readonly Hairstyle[], wornId: string, t: Tr = EN): Array<Hairstyle & {
  label: string
}> {
  const rows = owned.map((h) => ({ ...h, worn: !!wornId && h.id === wornId, label: hairstyleLabel(h, t) }))
  return [...rows.filter((h) => h.worn), ...rows.filter((h) => !h.worn)]
}

/** Why the New hairstyle dialog's Create is disabled (written under it), null = it can be created:
 *  an empty description first, then a mode that is not built (HAAR). */
export function newHairstyleDisabled(description: string, mode: HairMode): string | null {
  if (!description.trim()) return 'Describe the hairstyle'
  return hairModeDisabled(mode)
}

/** `garments.run_estimate` of a hairstyle (GET …/hair?item_id= `run`). */
export interface HairstyleRun {
  steps: string[]
  hub_jobs: number | null
  note: string
  refit: boolean
}

/** The flow of the selected hairstyle as buttons (rules R1/R2):
 *  - HairDeck has two steps (HairDeck → fit), so it has a Run all — the steps from the first one not current,
 *    named with its cost: "Create + fit (1 hub job)" when HairDeck runs, "Re-fit (no hub job)" when only the fit
 *    is due, "Everything is current" disabled when nothing is; no estimate → plain "Run all" (the server decides);
 *  - its single steps re-run even when current: "Regenerate hair (HairDeck) — 1 hub job" (a new seed, then the
 *    fit) and "Re-fit — no hub job";
 *  - `body` (and HAAR) have no run of their own: the hair is part of the body, the Figure tab's Build makes it. */
export function hairstyleActions(mode: HairMode, run: HairstyleRun | null | undefined, t: Tr = EN): {
  runAll: { label: string; disabled: boolean } | null
  regenerate: string | null
  refit: string | null
} {
  if (mode !== 'hairdeck') return { runAll: null, regenerate: null, refit: null }
  const regenerate = t('Regenerate hair (HairDeck) — {cost}').replace('{cost}', jobsTr(1, t))
  const refit = t('Re-fit — no hub job')
  let runAll: { label: string; disabled: boolean }
  if (!run) runAll = { label: t('Run all'), disabled: false }
  else if (!run.steps.length) runAll = { label: t('Everything is current'), disabled: true }
  else if (run.refit) runAll = { label: t('Run all (refit on the CPU)'), disabled: false }
  else if (run.steps[0] === 'fit') runAll = { label: t('Run all: re-fit (no hub job)'), disabled: false }
  else runAll = { label: t('Run all: create + fit ({cost})').replace('{cost}', jobsTr(run.hub_jobs, t)), disabled: false }
  return { runAll, regenerate, refit }
}

/** Under a setting of the selected hairstyle after a save (rule R3): nothing ran. */
export const HAIRSTYLE_SAVED_NOTE = 'Saved — nothing runs. Run all or Re-fit applies it (no hub job).'
