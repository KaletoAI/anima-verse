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
import { cpuProgressText, type CpuProgress } from '../../lib/cpuProgress'
import type { FootPose } from '@anima/scene-render'
import type { ModelStep } from './ModelSteps'
import type { ArmLight, FitSettingsInfo } from './fitSettingsModel'
import type { ShoeFrame } from './footwearAllowanceModel'
import { filesLabel, sizeLabel } from './hairstylesModel'
import type { Light } from './hairstylesModel'

/** How an outfit piece reaches the figure (`garment_set.MESH_MODES`). */
export type MeshMode = 'own_mesh' | 'shell' | 'in_body' | 'template' | 'accessory'
/** How the hair reaches the figure: HairDeck cards from the profile picture, HAAR strands from the text (H3), or
 *  in the body. */
export type HairMode = 'hairdeck' | 'haar' | 'body'

/** The select's order. */
export const MESH_MODES: MeshMode[] = ['own_mesh', 'shell', 'template', 'accessory', 'in_body']
export const HAIR_MODES: HairMode[] = ['hairdeck', 'haar', 'body']

export const MESH_MODE_LABELS: Record<MeshMode, string> = {
  own_mesh: 'Own mesh',
  shell: 'Shell from the body',
  in_body: 'In the body',
  template: 'Template (fabric)',
  accessory: 'Accessory',
}

export const HAIR_MODE_LABELS: Record<HairMode, string> = {
  hairdeck: 'HairDeck',
  haar: 'HAAR',
  body: 'In the body',
}

/** What each mode does, one line (the select's hint). */
export const MESH_MODE_HINTS: Record<MeshMode, string> = {
  own_mesh: 'A finished mesh of its own, fitted on top of the body.',
  shell: 'Made from the body’s own surface where the piece-only views show the piece, 4 mm over the skin, coloured from those views — no generated mesh and no cut-outs (0 hub jobs after the views), fitted on the CPU. For close-fitting pieces: underwear, tights.',
  in_body: 'Meshed as part of the body. Every combination of in-body pieces is its own body shape with its own mesh run.',
  template: 'A sewing pattern sized to the body and draped as cloth on the CPU (0 hub jobs); 1 LLM call suggests its parameters from the item picture. Skirts and dresses today.',
  accessory: 'A thin piece made on the CPU from the body (0 hub jobs): a chain or cord along the neck, optionally with a pendant from the item image (1 hub job per item). Its kind, drop, material and pendant are set in the Wardrobe.',
}

export const HAIR_MODE_HINTS: Record<HairMode, string> = {
  hairdeck: 'HairDeck makes hair cards from the profile picture in one step.',
  haar: 'HAAR grows hair strands from the hairstyle’s text: 3 variants (3 hub jobs, ~30–55 s each), each fitted on the CPU (~25 s); the best passing one is used, or the one you pick. HAAR is licensed CC BY-NC 4.0 (non-commercial).',
  body: 'The base body is rendered with the hair, so the hair is part of the body mesh — no hair mesh, no hair job.',
}

/** Why a hair mode cannot be chosen (written under the select), null = selectable: a mode the server does not
 *  list as built (GET …/hairstyles `built_modes`; every mode when it names none). */
export function hairModeDisabled(m: HairMode, built: readonly string[] = HAIR_MODES): string | null {
  return built.includes(m) ? null : 'not built yet'
}

export function isMeshMode(v: unknown): v is MeshMode {
  return v === 'own_mesh' || v === 'shell' || v === 'in_body' || v === 'template'
    || v === 'accessory'
}

/** Ruling A118 J6: the refusal text of an own-mesh piece too thin for its chain (`garments.THIN_PIECE_TEXT`). */
export const THIN_PIECE_TEXT = 'Too thin for its own mesh — use Accessory or In body'

/** Whether a row's failure is the J6 thin-piece refusal (its rows offer "Switch to Accessory" / "Switch to In body"). */
export function isThinPieceRefusal(failure: string | null | undefined): boolean {
  return !!failure && failure.includes(THIN_PIECE_TEXT)
}

/** The modes whose piece is a fitted mesh of its own and runs the own-mesh chain (`garment_set.OWN_MESH_MODES`):
 *  Own mesh, and Shell from the body (the same chain without the cut-outs and the hub mesh job). */
export function isOwnMeshMode(m: string | null | undefined): boolean {
  return m === 'own_mesh' || m === 'shell'
}

/** The default mode of a piece worn on `slots` (`garment_set.default_mesh_mode`): in the body for every slot
 *  set, footwear included (Ruling A10 — every other mode must be chosen). `slots` is unused today. */
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
  // Ruling A26 a: not beside a base-body step (a click: 409 with the step named; "Build for them" lists it).
  base_busy: 'Not started — a base-body step of the character is running',
  deferred: 'Waits for the running base-body step, then builds',
}

/** Ruling A26 a: an automatic Build that waits for a base-body step of the character (`build.deferred`). */
export const BUILD_DEFERRED_NOTE = 'An automatic Build waits for the running base-body step and starts when it is done'

// --- The Figure tab (Task 10; spec "The UI", rules for the buttons, ruling 8) ---------------------------

/** `t()` of the caller; the helpers default to English (the check reads that). */
type Tr = (s: string) => string
const EN: Tr = (s) => s

// --- Switching a piece off its own mesh (Ruling A63) ----------------------------------------------------

/** GET /inventory/items/{item}/own-mesh-files (`artefact_graph.own_mesh_files`): the stored own-mesh files the next
 *  cleanup removes once the piece is no own mesh, and what making them again costs (`hub_jobs` null = unknown,
 *  `note` says why). */
export interface OwnMeshFiles {
  item_id: string
  mode: string
  kind: string
  files: number
  bytes: number
  hub_jobs: number | null
  note: string
  characters: Array<{ name: string; files: number; bytes: number; hub_jobs: number | null; note: string }>
  world: { files: number; bytes: number }
}

/** The switch leaves Own mesh / Shell from the body for a mode without a mesh of its own — the only switch that can
 *  hand stored files to the cleanup (Own mesh ↔ Shell keeps the piece's views and fits; a switch between two modes
 *  without an own mesh drops no own-mesh file: the server counts 0 for a piece that is no own mesh). */
export function leavesOwnMesh(current: MeshMode, next: MeshMode): boolean {
  return isOwnMeshMode(current) && !isOwnMeshMode(next)
}

/** The in-app confirmation before switching `current` → `next` (Ruling A63), or null when there is nothing to
 *  confirm: the switch does not leave Own mesh, or the server counted no stored own-mesh file. `error`: the count
 *  could not be read — the confirmation then says so (never a silent switch). */
export function switchOffWarning(current: MeshMode, next: MeshMode, info: OwnMeshFiles | null, error = '',
  t: Tr = EN): { title: string; message: string } | null {
  if (!leavesOwnMesh(current, next)) return null
  const title = t('Switch to “{mode}”?').replace('{mode}', t(MESH_MODE_LABELS[next]))
  if (error || !info) {
    return {
      title,
      message: t('The stored files of its own mesh could not be counted ({error}). The next cleanup may remove them; switching back to Own mesh would then cost hub jobs again.')
        .replace('{error}', error || t('no answer')),
    }
  }
  if (info.files <= 0) return null
  const removed = t('This piece’s own mesh and its fits ({files}, {size}) will be removed by the next cleanup.')
    .replace('{files}', filesLabel(info.files, t)).replace('{size}', sizeLabel(info.bytes))
  const cost = info.hub_jobs === null
    ? t('Switching back to Own mesh later costs hub jobs again (count unknown: {note}) plus the fit on the CPU.')
      .replace('{note}', info.note)
    : info.hub_jobs === 1
      ? t('Switching back to Own mesh later costs up to 1 hub job (mesh) plus the fit on the CPU.')
      : t('Switching back to Own mesh later costs up to {n} hub jobs (mesh) plus the fit on the CPU.')
        .replace('{n}', String(info.hub_jobs))
  const names = info.characters.map((c) => c.name)
  const whose = names.length > 1 ? ' ' + t('Stored for {names}.').replace('{names}', names.join(', ')) : ''
  return { title, message: `${removed} ${cost}${whose}` }
}

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
  /** The cached failure as data (a template drape's, `garment_template.failure_info`); null otherwise. */
  failure?: StepFailure | null
}

/** A worn piece of the Figure tab (`figure_build._worn_rows`). */
export interface FigureWornRow {
  slot: string
  item_id: string
  name: string
  /** A216 review M2: the accessory kind this version builds for the piece (its "Switch to Accessory"), null: none. */
  accessory_kind?: string | null
  mode: MeshMode
  state: 'ready' | 'failed' | 'fit_refused' | 'building' | 'left_out' | 'pending'
  note: string
  /** Ruling A119: why the piece is left off the figure shown (not ready yet); "" when worn. */
  left_out: string
  failure: string
  /** Ruling A23 b: its fit on the body shape was refused (the reason; "" otherwise) — left off the figure (Ruling
   *  A119); the row offers Re-fit and Regenerate mesh. */
  fit_refused?: string
  /** Ruling A31: the measured reasons behind `fit_refused` (the tooltip). */
  fit_refused_detail?: string
  /** Ruling A31: what is in the body shape the fit was refused on ("t-shirt, underwear"; "" unknown). */
  refused_on?: string
  /** Ruling A31: the refusal points at the piece itself — only then a new mesh helps ("Regenerate mesh"). */
  piece_broken?: boolean
  /** Ruling A31: the fit the figure uses was refused by its checks and accepted by the user (`step` "fit", `on` the
   *  body); Ruling A69: else its mesh (`step` "mesh") or an image of its chain (`step` worn/ghost/cutout, `view`)
   *  taken with "Use this" although its gate refused it (`on` ""). */
  accepted_by_user?: {
    on: string; reason: string; detail: string; at: string | null; step?: string; view?: string
  } | null
  /** Hub jobs its chain step plans (0 = none planned, null = unknown). */
  jobs: number | null
  /** Open / closed of a closable piece; null = not closable (NOT the readiness above). */
  piece_state: PieceState | null
  /** Own mesh + closable only: hub jobs of the OTHER state's mesh (0 = built, null = unknown / n.a.). */
  other_state_jobs: number | null
  /** A piece whose fit was refused: hub jobs of its "Regenerate mesh" (the server's estimate; null = unknown
   *  or n.a.). */
  regenerate_jobs?: number | null
  /** Mode template only (Ruling A138, `figure_build._template_row`); null otherwise. */
  template?: TemplateInfo | null
}

/** The sewing-pattern parameters of a template piece (`garment_template.PARAM_SPEC`). */
export interface TemplateParams {
  kind: string
  length_m: number
  flare: number
  waist_height: string
  slit: string
  slit_m: number
  /** Ruling A142: a dress's shoulders (strapless / straps / covered); a top any of them (A221); a jacket always
   *  covered. */
  shoulders: string
  sleeves: string
  sleeve_fit: number
  fit: number
  neckline: string
  neck_depth_m: number
  front: string
  collar: string
  fabric: string
  /** A204: sheer only — how much of the cloth's colour covers (0.2 … 1). */
  opacity: number
  /** A223 briefs: waistband height (low / mid / high), leg opening (0 boyshort … 1 high-cut), seat (0 string … 1
   *  full), the side panel's height and the waistband. */
  rise?: string
  leg_cut?: number
  back_coverage?: number
  side_width_m?: number
  /** Step 3a briefs: the crotch's full width (0.03 … 0.08 m; a thong's is narrow). `leg_cut` past 1 (to 1.5) is a
   *  high-leg front. */
  gusset_m?: number
  waistband?: string
  /** A232 briefs: 0 = a brief cut by `leg_cut`; > 0 = short legs this far down the thigh (trunks, boxer briefs,
   *  boxer shorts with `fit`). */
  leg_length_m?: number
  /** A235 briefs: side panels (`fabric`) or thin hip bands (`string`: string bikini, tanga, side-tie) this high. */
  sides?: string
  string_width_m?: number
  /** A223 bra: the cup shape and how much of the bust it covers, the lift, the band under it, the fabric between the
   *  cups, the closure and the straps (shared strap styles, `garment_template.STRAPS`). */
  cup_style?: string
  cup_coverage?: number
  push_up?: number
  underband_m?: number
  center_gore?: string
  closure?: string
  straps?: string
  /** A223 gloves: fingers (full / fingerless / none), how far up the arm, the cuff. */
  fingers?: string
  length?: string
  cuff?: string
  /** A223 tights: full tights, hold-ups, thigh-highs (garter tabs optional), knee socks; the foot. */
  tights_style?: string
  feet?: string
  garters?: string
  /** A233 trousers (with `rise`, `fit`, `fabric`): how far the leg reaches, the leg's shape, the waist finish, the
   *  fly (painted by the picture) and the hem. */
  trouser_length?: string
  leg_shape?: string
  /** Bug round 2026-11-20: how the trouser sits above the crotch — fitted (a second skin), regular, relaxed. */
  seat?: string
  trouser_waist?: string
  fly?: string
  hem?: string
  /** A229 off-shoulder (top / dress): the elastic band's height, how far it lies under the shoulder line, the front
   *  lacing and how deep it reaches. */
  band_m?: number
  band_drop_m?: number
  lacing?: string
  lace_depth_m?: number
  /** Plan 2026-11-20-template-cut-uv-texture (tops): where the texture comes from — the projection bake of the
   *  piece-only views, or the "texture from cut" atlas. A switch only re-assembles (CPU, no drape). */
  texture?: string
  /** User test 2026-11-21: the sleeves of the texture from cut — "plain" (the front panel's fabric, default) or
   *  "picture" (the model's answer). Set in the Texture tab (`…/cut/sleeves`), never a field of the Cut tab. */
  sleeve_print?: string
  /** Plan group B (B10): what closes a top's / dress's / jacket's front — painted by code along the cut's marks
   *  ("none" / "buttons" / "zip" / "lacing"); `buttons` 0 = automatic. Both TEXTURE_ONLY: a switch re-assembles. */
  placket?: string
  buttons?: number
}

/** A223: the close-fitting kinds cut from the body's surface (`garment_template.FITTED_KINDS`): no length, flare or
 *  bodice fields. */
export const FITTED_KINDS = ['briefs', 'bra', 'gloves']

/** Ruling A142: the kinds with a bodice over the shoulders (the length counts from the shoulder line). */
export const UPPER_KINDS = ['top', 'jacket']

/** A221: the top edges of a strapless top (`garment_template.STRAPLESS_NECKLINES`). */
export const STRAPLESS_NECKLINES = ['straight', 'sweetheart']

/** Whether the piece has a covered bodice (sleeves, neckline): a jacket, or a top / dress with covered shoulders. */
export function hasBodice(p: Pick<TemplateParams, 'kind' | 'shoulders'>): boolean {
  return p.kind === 'jacket' || ((p.kind === 'top' || p.kind === 'dress')
    && (p.shoulders === 'covered' || p.shoulders === 'off_shoulder'))
}

/** A229: a top or dress cut off the shoulders (`garment_template.off_shoulder`). */
export function offShoulder(p: Pick<TemplateParams, 'kind' | 'shoulders'>): boolean {
  return (p.kind === 'top' || p.kind === 'dress') && p.shoulders === 'off_shoulder'
}

/** A229: the sleeves an off-shoulder piece may have (`garment_template.OFF_SHOULDER_SLEEVES`). */
export const OFF_SHOULDER_SLEEVES = ['short', 'elbow', 'long']

/** A221: a top cut as a corset bodice — strapless or with straps (`garment_template.corset_top`). */
export function corsetTop(p: Pick<TemplateParams, 'kind' | 'shoulders'>): boolean {
  return p.kind === 'top' && (p.shoulders === 'strapless' || p.shoulders === 'straps')
}

/** Whether a choice is offered for the draft (A221: a corset top's neckline is straight or sweetheart, a covered
 *  bodice's never). */
export function choiceAllowed(key: keyof TemplateParams, choice: string, p: TemplateParams): boolean {
  if (key === 'neckline') return corsetTop(p) === STRAPLESS_NECKLINES.includes(choice)
  if (key === 'sleeves' && offShoulder(p)) return OFF_SHOULDER_SLEEVES.includes(choice)
  // A233: a stirrup only under a skinny full-length leg (`garment_template._validate_trousers`)
  if (key === 'hem' && choice === 'stirrup') return p.leg_shape === 'skinny' && p.trouser_length === 'full'
  // bug round 2026-11-20: a stirrup is pinned whole as a second skin — its seat is fitted (`_validate_trousers`)
  if (key === 'seat' && p.hem === 'stirrup') return choice === 'fitted'
  return true
}

/** Bug round 2026-11-20: the seat a leg shape starts with (`garment_template.default_seat`): fitted for a skinny leg. */
export function defaultSeat(p: TemplateParams): string {
  return p.leg_shape === 'skinny' ? 'fitted' : 'regular'
}

/** A template row's drape state and parameters (`figure_build._template_row`). */
export interface TemplateInfo {
  params: TemplateParams | null
  source: '' | 'llm' | 'user'
  updated_at: string
  /** The kinds draped today ("skirt", "dress"). */
  built: string[]
  state: 'ready' | 'missing' | 'failed' | 'blocked'
  reason: string
  built_at: string
  metrics: { wall_s: number | null; cpu_s: number | null; stretch_max: number | null; coverage: number | null;
    texture: string; /** Rulings A141 / A142: the poses draped again as corrective shapes ("sit", "arms_down", …). */
    pose_shapes?: string[]; /** Ruling A142: how many lower template drapes it was draped over. */
    layered_over?: number; /** Over the time budget: shown as "slow" — never a refusal. */ slow?: boolean
    /** Bug round 2026-11-20: a poor texture (`garment_template.texture_warning`) — warned, never a refusal. */
    texture_warning?: TextureWarning | null
    /** The "texture from cut" state of a ready drape (`garment_template.cut_info`); `texture` is "cut" while its
     *  atlas is in use. */
    cut?: TemplateCut | null } | null
  cost: { llm_calls: number; hub_jobs: number; cpu_s: number; /** The cut texture's image jobs the Build spends. */
    cut_jobs?: number }
  /** User test 2026-11-21: the Build's texture-from-cut step of a top whose texture is "cut"
   *  (`figure_build._cut_build_row`); null when the piece does not want it. */
  cut_build?: CutBuild | null
  /** The failed drape of the current key as data (`state` "failed"); null otherwise. */
  failure?: StepFailure | null
}

/** Bug round 2026-11-20: a drape whose texture is poor (`garment_template.texture_warning`, marks `TEXTURE_WARN`):
 *  under 60 % of it got a picture colour, or the views' outline matches the template's by under half. */
export interface TextureWarning {
  coverage: number | null
  iou: number | null
  low_coverage: boolean
  low_iou: boolean
  /** A wanted cut texture the figure cannot use (stale / rejected / failed) — said by `templateCutLine`. */
  cut?: { state: string; reason: string; text: string }
}

/** The Build's texture-from-cut step of a piece (`garment_cut_texture.build_state`, `running` while a flow runs). */
export interface CutBuild {
  state: 'done' | 'due' | 'compose' | 'failed' | 'running'
  reason: string
  jobs: number
  estimate: boolean
  /** What a manual Build re-runs of a failure (an automatic Build skips it): "cut" — the pattern is cut again, then
   *  the texture is made; "jobs" — only the image jobs that did not pass; "" — nothing (e.g. no item picture). */
  retry?: '' | 'cut' | 'jobs'
  /** Where a running flow is ("cut", "back_view", "upscale", "front", "back", "post", "apply"). */
  step: string
}

/** The words of a running flow's step (`garment_cut_texture._progress`). */
export const CUT_STEP_LABELS: Record<string, string> = {
  cut: 'cutting the pattern', back_view: 'back view', upscale: 'item picture', front: 'front job', back: 'back job',
  post: 'checking the answer', apply: 'putting it on',
}

/** The figure row's "texture from cut" state (`figure_build._template_row` → `metrics.cut`). */
export interface TemplateCut {
  state: 'ready' | 'off' | 'missing' | 'stale' | 'drape_behind' | 'drape_other' | 'rejected' | 'failed'
  reason: string
  iou: number | null
  de_after: number | null
  px_per_cm: number | null
  csig: string | null
}

/** A failed texture from cut, saying exactly what the next Build does with it (`CutBuild.retry`): an automatic Build
 *  skips a cached failure; a click on Build re-runs only what failed. */
export function cutBuildFailedLine(b: CutBuild, t: Tr = EN): string {
  const reason = t(b.reason || 'no reason')
  const n = String(b.jobs || 0)
  if (b.retry === 'cut') {
    return t('Texture from cut failed: {reason} — an automatic Build skips it; a click on Build cuts the pattern again, then makes the texture (+{n} image jobs)')
      .replace('{reason}', reason).replace('{n}', n)
  }
  if (b.retry === 'jobs') {
    return (b.jobs
      ? t('Texture from cut failed: {reason} — an automatic Build skips it; a click on Build renders only the jobs that did not pass (+{n} image jobs)')
      : t('Texture from cut failed: {reason} — an automatic Build skips it; a click on Build composes it again from the answers that passed (CPU, 0 image jobs)'))
      .replace('{reason}', reason).replace('{n}', n)
  }
  return t('Texture from cut failed: {reason}').replace('{reason}', reason)
}

/** "Texture: cut (IoU 0.94, ΔE 3.1)" / "Texture: projection — no cut texture yet" / "… — cut out of date" /
 *  "… — cut rejected: <reason>" — the figure row's line of a piece whose texture is wanted from the cut; "" when the
 *  piece does not want it (`off`). */
export function templateCutLine(info: TemplateInfo | null | undefined, t: Tr = EN): string {
  const b = info?.cut_build
  if (b?.state === 'running') {
    const step = CUT_STEP_LABELS[b.step]
    return step ? t('Texture from cut: being made ({step})').replace('{step}', t(step)) : t('Texture from cut: being made')
  }
  if (b?.state === 'due') {
    return t('Texture: projection — the next Build makes the cut texture (+{n} image jobs)').replace('{n}', String(b.jobs))
  }
  if (b?.state === 'compose') return t('Texture: projection — the next Build composes the cut texture again (CPU)')
  const c = info?.state === 'ready' ? info.metrics?.cut : null
  if ((!c || c.state === 'off') && b?.state === 'failed') return cutBuildFailedLine(b, t)
  if (!c || c.state === 'off') return ''
  if (c.state === 'ready') {
    return t('Texture: cut (IoU {iou}, ΔE {de})').replace('{iou}', (c.iou ?? 0).toFixed(2))
      .replace('{de}', c.de_after == null ? '–' : c.de_after.toFixed(1))
  }
  if (c.state === 'missing') return t('Texture: projection — no cut texture yet')
  if (c.state === 'stale') return t('Texture: projection — cut out of date')
  if (c.state === 'drape_behind') return t('Texture: projection — the drape is of an older cut; the next Build drapes the new one')
  if (c.state === 'drape_other') return t('Texture: projection — this drape was laid out of other layers than the cut; the cut texture does not fit it')
  return t(c.state === 'rejected' ? 'Texture: projection — cut rejected: {reason}' : 'Texture: projection — cut failed: {reason}')
    .replace('{reason}', t(c.reason || 'no reason'))
}

/** "Texture: the picture covers only 43 % of the piece · its outline matches the template's by 20 % — …" — the
 *  Figure row's warning of a poor texture; "" when there is none. */
export function templateTextureWarning(info: TemplateInfo | null | undefined, t: Tr = EN): string {
  const w = info?.state === 'ready' ? info.metrics?.texture_warning : null
  // a cut texture's state is the row's own line (`templateCutLine`): here only the projection bake's marks
  if (!w || !(w.low_coverage || w.low_iou)) return ''
  const pct = (v: number | null) => String(Math.round((v ?? 0) * 100))
  const parts: string[] = []
  if (w.low_coverage) parts.push(t('the picture covers only {n} % of the piece').replace('{n}', pct(w.coverage)))
  if (w.low_iou) parts.push(t('its outline matches the template’s by {n} %').replace('{n}', pct(w.iou)))
  const line = 'Texture: {what} — the rest is filled from the colours around it. New piece-only views or parameters that match the picture help.'
  return t(line).replace('{what}', parts.join(' · '))
}

/** One field of the parameter dialog's schema (GET …/figure/template/{item}). */
export type TemplateFieldSpec = { type: 'choice'; choices: string[]; default: string }
  | { type: 'number'; min: number; max: number; default: number }

/** The words of the choice values (English; put through `t()`). */
export const TEMPLATE_CHOICE_LABELS: Record<string, string> = {
  skirt: 'Skirt', dress: 'Dress', top: 'Top', jacket: 'Jacket', trousers: 'Trousers', briefs: 'Briefs', bra: 'Bra',
  molded: 'Molded cups', triangle: 'Triangle', bandeau: 'Bandeau', balconette: 'Balconette', narrow: 'Narrow',
  tights: 'Tights (to the waist)', hold_up: 'Hold-up stockings', thigh_high: 'Thigh-high stockings',
  knee_high: 'Knee-high socks', footless: 'Footless', stirrup: 'Stirrup (under the arch)', tabs: 'Garter tabs',
  gloves: 'Gloves', full: 'Full fingers', fingerless: 'Fingerless', wrist: 'To the wrist', forearm: 'Mid forearm',
  opera: 'Opera (above the elbow)', flared: 'Flared', folded: 'Folded over',
  back_hook: 'Hooks at the back', halter: 'Halter (round the neck)', cross: 'Crossed on the back',
  mid: 'Mid', thin: 'Thin', wide: 'Wide',
  high: 'High', natural: 'Natural', low: 'Low',
  none: 'None', left: 'Left', right: 'Right', front: 'Front', back: 'Back',
  front_left: 'Front left', front_right: 'Front right',
  short: 'Short', long: 'Long', cap: 'Cap', elbow: 'Elbow',
  strapless: 'Strapless', straps: 'Straps', covered: 'Covered (with a bodice)',
  off_shoulder: 'Off the shoulders (Carmen)',
  crew: 'Crew', v: 'V-neck', scoop: 'Scoop', boat: 'Boat', straight: 'Straight', sweetheart: 'Sweetheart',
  closed: 'Closed', open: 'Open', stand: 'Stand collar', lapel: 'Lapels',
  stiff: 'Stiff (denim, wool)', medium: 'Medium (cotton, linen)', flowing: 'Flowing (silk, jersey)',
  sheer: 'Sheer (chiffon, voile)',
  leather_glossy: 'Leather (glossy)', leather_rough: 'Leather (rough)',
  fabric: 'Side panels', string: 'Thin bands (string, tanga)',
  shorts: 'Shorts', knee: 'To the knee', capri: 'Capri (mid-calf)', ankle: 'Ankle (cropped)',
  skinny: 'Skinny', cargo: 'Cargo (loose)', elastic: 'Elastic band', belt: 'Belt band', zip: 'Zip',
  buttons: 'Buttons', plain: 'Plain', cuffed: 'Cuffed (turn-up)',
  projection: 'Projection', cut: 'From cut',
}

/** A233: a choice whose word differs by field (`full` is a glove's full fingers and a trouser's full length). */
export const TEMPLATE_FIELD_CHOICE_LABELS: Partial<Record<keyof TemplateParams, Record<string, string>>> = {
  trouser_length: { full: 'Full length' },
  leg_shape: { straight: 'Straight leg', wide: 'Wide leg', flared: 'Flared (bootcut)' },
  seat: { fitted: 'Fitted (second skin)', regular: 'Regular', relaxed: 'Relaxed (roomy seat)' },
  placket: { lacing: 'Lacing' },
}

/** Bug round 2026-11-20: the dialog's presets (`presets` of the GET) — their button words and hints. */
export const TEMPLATE_PRESET_LABELS: Record<string, string> = { leggings: 'Leggings' }
export const TEMPLATE_PRESET_HINTS: Record<string, string> = {
  leggings: 'Skinny leg, fitted seat, tight fit, full length — a second skin from the waist to the ankle',
}

/** The word of a choice in a field. */
export function choiceLabel(key: keyof TemplateParams, choice: string): string {
  return TEMPLATE_FIELD_CHOICE_LABELS[key]?.[choice] || TEMPLATE_CHOICE_LABELS[choice] || choice
}

/** The parameter dialog's field labels. */
export const TEMPLATE_FIELD_LABELS: Record<keyof TemplateParams, string> = {
  kind: 'Garment kind', length_m: 'Length below the waist', flare: 'Flare (0 straight … 1 circle)',
  waist_height: 'Waist height', slit: 'Slit', slit_m: 'Slit height from the hem', sleeves: 'Sleeves', fabric: 'Fabric',
  shoulders: 'Shoulders', sleeve_fit: 'Sleeve fit (0 tight … 1 loose)', fit: 'Body fit (0 tight … 1 loose)',
  neckline: 'Neckline', neck_depth_m: 'Neckline depth (0 = usual)', front: 'Front', collar: 'Collar',
  opacity: 'Opacity (0.2 sheer … 1 opaque)',
  rise: 'Rise', leg_cut: 'Leg cut (0 boyshort … 1 high-cut … 1.5 high-leg)',
  gusset_m: 'Crotch width', back_coverage: 'Seat coverage (0 string … 1 full)',
  side_width_m: 'Side height', waistband: 'Waistband', leg_length_m: 'Leg length (0 = brief cut)',
  sides: 'Sides', string_width_m: 'Band height',
  cup_style: 'Cups', cup_coverage: 'Cup coverage (0.3 demi … 1 full)', push_up: 'Push-up (0 none … 1 strong)',
  underband_m: 'Underband (0 = the cup edge only)', center_gore: 'Between the cups', closure: 'Closure', straps: 'Straps',
  fingers: 'Fingers', length: 'Glove length', cuff: 'Cuff',
  tights_style: 'Style', feet: 'Foot', garters: 'Garters',
  band_m: 'Elastic band height', band_drop_m: 'Band below the shoulder line', lacing: 'Lacing',
  lace_depth_m: 'Lacing depth',
  trouser_length: 'Leg length', leg_shape: 'Leg shape', seat: 'Seat (above the crotch)', trouser_waist: 'Waist finish', fly: 'Fly (painted)',
  hem: 'Hem', texture: 'Texture', sleeve_print: 'Sleeves of the texture',
  placket: 'Placket (painted)', buttons: 'Buttons (0 = automatic)',
}

/**
 * Round 2026-11-25: one line under a field of the parameter dialog that says what the field controls (rendered for
 * any key that has one). "Fabric" is the cloth simulation, "Material" (the select under it) the surface only.
 */
export const TEMPLATE_FIELD_HINTS: Partial<Record<keyof TemplateParams, string>> = {
  fabric: 'Fabric = how the cloth falls (the cloth simulation: weight, stiffness, folds). Metal scales or chain: Stiff.',
}

/** Round 2026-11-25: the line under the material select of a template piece — the surface, never the drape. */
export const TEMPLATE_MATERIAL_HINT = 'Material = the surface only (shine, roughness, metal); it never changes the drape. Metal scales or chain: Metal.'

/** A204: one line per fabric under the select — what the cloth does and what a switch costs. */
export const TEMPLATE_FABRIC_NOTES: Record<string, string> = {
  stiff: 'Holds its shape: few, wide folds.',
  medium: 'Ordinary cotton: the usual drape.',
  flowing: 'Soft folds that follow the body.',
  sheer: 'Very light, fine folds that flutter; see-through — the body and what is worn under it show.',
  leather_glossy: 'Heavy and stiff: barely stretches, few wide folds; a smooth, glossy finished surface.',
  leather_rough: 'Heavy and stiff: barely stretches, few wide folds; a matte suede surface.',
}

/** A214: fabrics that share one drape — a switch between them only re-assembles (`garment_template.DRAPE_FABRIC`). */
export const TEMPLATE_DRAPE_FABRIC: Record<string, string> = { leather_glossy: 'leather', leather_rough: 'leather' }

/** The length field's label for a kind (Ruling A142: a top or jacket counts from the shoulder line). */
export function lengthLabel(kind: string): string {
  return UPPER_KINDS.includes(kind) ? 'Length from the shoulder' : 'Length below the waist'
}

/** "45 cm" of a length in metres. */
export function cm(m: number): string {
  return `${Math.round(m * 100)} cm`
}

/** A223: a fitted piece's summary: "Briefs · Low rise · leg cut 0.85 · seat 0.60 · Stiff (denim, wool)". */
export function fittedSummary(p: TemplateParams, t: Tr = EN): string {
  const parts = [t(TEMPLATE_CHOICE_LABELS[p.kind] || p.kind)]
  if (p.kind === 'briefs') {
    parts.push(t('{rise} rise').replace('{rise}', t(TEMPLATE_CHOICE_LABELS[p.rise || 'mid'] || p.rise || '')))
    if (Number(p.leg_length_m || 0) > 0) {
      parts.push(t('legs {cm}').replace('{cm}', cm(Number(p.leg_length_m))))
    } else {
      if (p.sides === 'string') parts.push(t('Thin bands (string, tanga)'))
      parts.push(t('leg cut {n}').replace('{n}', Number(p.leg_cut ?? 0.5).toFixed(2)))
      parts.push(t('seat {n}').replace('{n}', Number(p.back_coverage ?? 1).toFixed(2)))
    }
  }
  if (p.kind === 'bra') {
    parts.push(t(TEMPLATE_CHOICE_LABELS[p.cup_style || 'molded'] || p.cup_style || ''))
    parts.push(t('cover {n}').replace('{n}', Number(p.cup_coverage ?? 0.7).toFixed(2)))
    if (Number(p.push_up || 0) > 0) parts.push(t('push-up {n}').replace('{n}', Number(p.push_up).toFixed(2)))
    if (p.straps && p.straps !== 'none') parts.push(t(TEMPLATE_CHOICE_LABELS[p.straps] || p.straps))
  }
  if (p.kind === 'tights') {
    parts.push(t(TEMPLATE_CHOICE_LABELS[p.tights_style || 'tights'] || p.tights_style || ''))
    if (p.feet && p.feet !== 'closed') parts.push(t(TEMPLATE_CHOICE_LABELS[p.feet] || p.feet))
    if (p.tights_style === 'thigh_high' && p.garters === 'tabs') parts.push(t('Garter tabs'))
  }
  if (p.kind === 'trousers') {
    parts.push(t(choiceLabel('trouser_length', p.trouser_length || 'full')))
    parts.push(t(choiceLabel('leg_shape', p.leg_shape || 'straight')))
    if (p.seat && p.seat !== 'regular') parts.push(t(choiceLabel('seat', p.seat)))
    parts.push(t('{rise} rise').replace('{rise}', t(TEMPLATE_CHOICE_LABELS[p.rise || 'mid'] || p.rise || '')))
    if (p.hem && p.hem !== 'plain') parts.push(t(choiceLabel('hem', p.hem)))
  }
  if (p.kind === 'gloves') {
    parts.push(t(TEMPLATE_CHOICE_LABELS[p.fingers || 'full'] || p.fingers || ''))
    parts.push(t(TEMPLATE_CHOICE_LABELS[p.length || 'wrist'] || p.length || ''))
    if (p.cuff && p.cuff !== 'none') parts.push(t(TEMPLATE_CHOICE_LABELS[p.cuff] || p.cuff))
  }
  parts.push(t(TEMPLATE_CHOICE_LABELS[p.fabric] || p.fabric))
  return parts.join(' · ')
}

/** A template row's one-line summary: "Skirt · 45 cm · flare 0.4 · Medium (cotton, linen)" (+ slit), or "No
 *  parameters yet". */
export function templateSummary(p: TemplateParams | null, t: Tr = EN): string {
  if (!p) return t('No parameters yet')
  if (FITTED_KINDS.includes(p.kind) || p.kind === 'trousers') return fittedSummary(p, t)
  const parts = [t(TEMPLATE_CHOICE_LABELS[p.kind] || p.kind), cm(p.length_m)]
  if (!UPPER_KINDS.includes(p.kind)) parts.push(t('flare {n}').replace('{n}', String(p.flare)))
  if (hasBodice(p) && p.sleeves && p.sleeves !== 'none') {
    parts.push(t('{sleeves} sleeves').replace('{sleeves}', t(TEMPLATE_CHOICE_LABELS[p.sleeves] || p.sleeves)))
  }
  if ((p.kind === 'dress' || p.kind === 'top') && p.shoulders === 'straps') parts.push(t('Straps'))
  if (p.kind === 'top' && p.shoulders === 'strapless') parts.push(t('Strapless'))
  if (offShoulder(p)) {
    parts.push(t('Off the shoulders'))
    if (p.lacing === 'front') parts.push(t('front lacing {cm}').replace('{cm}', cm(Number(p.lace_depth_m ?? 0.15))))
  } else if (hasBodice(p) || corsetTop(p)) {
    parts.push(t(TEMPLATE_CHOICE_LABELS[p.neckline] || p.neckline))
  }
  if (p.kind === 'jacket' && p.front === 'open') parts.push(t('open front'))
  parts.push(t(TEMPLATE_CHOICE_LABELS[p.fabric] || p.fabric))
  if (p.fabric === 'sheer') parts.push(t('opacity {n}').replace('{n}', Number(p.opacity ?? 0.4).toFixed(2)))
  if (p.slit !== 'none') parts.push(t('slit {side} {cm}').replace('{side}', t(TEMPLATE_CHOICE_LABELS[p.slit] || p.slit))
    .replace('{cm}', cm(p.slit_m)))
  return parts.join(' · ')
}

/** The cost line of a template piece (checklist 9): what suggesting and draping spend. */
export function templateCost(c: TemplateInfo['cost'] | undefined, t: Tr = EN): string {
  const cost = c || { llm_calls: 1, hub_jobs: 0, cpu_s: 20 }
  const line = t('Suggest: {n} LLM call · Drape: {jobs} hub jobs, ~{s} s CPU')
    .replace('{n}', String(cost.llm_calls)).replace('{jobs}', String(cost.hub_jobs)).replace('{s}', String(cost.cpu_s))
  return cost.cut_jobs ? `${line} · ${t('Texture from cut: {n} image jobs').replace('{n}', String(cost.cut_jobs))}` : line
}

/** Rulings A141 / A142: the words of the poses a drape carries a corrective shape for. */
export const POSE_SHAPE_LABELS: Record<string, string> = {
  sit: 'Sit', kneel: 'Kneel', arms_down: 'Arms down', arms_forward: 'Arms forward', arms_up: 'Arms raised',
}

/** "Draped <time> · 14 s wall · stretch 1.10 · texture from the cut-out views · shaped for Sit, Kneel" — the built line
 *  (checklist 8). */
export function templateBuilt(info: TemplateInfo, t: Tr = EN): string {
  if (info.state !== 'ready' || !info.built_at) return ''
  const m = info.metrics
  const parts = [t('Draped {at}').replace('{at}', info.built_at.replace('T', ' ').slice(0, 16))]
  if (m?.wall_s != null) {
    parts.push((m.slow ? t('{s} s — slow (over the time budget, accepted)') : t('{s} s'))
      .replace('{s}', String(Math.round(m.wall_s))))
  }
  if (m?.stretch_max != null) parts.push(t('stretch {n}').replace('{n}', m.stretch_max.toFixed(2)))
  // a texture from cut is said by its own line (`templateCutLine`)
  if (m?.texture && m.texture !== 'cut') parts.push(m.texture === 'cutout' ? t('texture from the cut-out views')
    : t('texture from the item picture'))
  if (m?.pose_shapes?.length) parts.push(t('shaped for {poses}').replace('{poses}',
    m.pose_shapes.map(p => t(POSE_SHAPE_LABELS[p] || p)).join(', ')))
  if (m?.layered_over) parts.push(t('draped over {n} lower layer(s)').replace('{n}', String(m.layered_over)))
  return parts.join(' · ')
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
  /** Ruling A86: on the plain body's change whose front was made from another reference (`delivered` the reason) —
   *  what the front is made from now (`reference` = the profile image, `text`); absent otherwise. */
  front?: 'reference' | 'text'
}

/** One view of the worn body shape (`figure_build._shape_views`): `stamp` is the picture's cache key, `empty` an
 *  EMPTY composite (the base view unchanged), `lost_clothing` EMPTY although the dressed front wears clothing. */
export interface ShapeViewInfo {
  view: string
  exists: boolean
  stamp: string
  empty: boolean
  lost_clothing: boolean
  jobs: number
}

/** `base_body.shape_view_state`: the view a Regenerate renders now, and the last one's outcome. */
export interface ShapeViewRegenerateState {
  running: { shape: string; view: string } | null
  last: { shape: string; view: string; ok: boolean; error: string } | null
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
    step: (FigureStep & { index?: number; count?: number; label?: string; live?: CpuProgress | null }) | null
    queued: number
    /** Ruling A26 a: the reason of an automatic Build that waits for a base-body step, else null. */
    deferred?: string | null
    /** Ruling A42: the automatic run the character's pause stopped before `step`, else null. */
    paused?: { step: string; label: string; note: string } | null
    /** `failure`: the step's failure as data when it has one (a template drape's); `failures` the same per item
     *  when several items of the step failed. */
    failed: Record<string, { error: string; item_id?: string; items?: Record<string, string>
      failure?: StepFailure | null; failures?: Record<string, StepFailure> }>
    skipped: string[]
    reason: string | null
    finished_at: string | null
  }
  served_url: string | null
  /** The served model's fitted-shoe pose (`figure_build._served_foot_pose`, Ruling A52), null without a fitted
   *  shoe: the viewer turns the feet into the shoes with it and stands the figure on its heels. */
  served_foot_pose?: FootPose | null
  /** Ruling A42: the character's pause of automatic generation (`generation_pause.state`). */
  generation_pause?: GenerationPause
  /** When the served model was built (Ruling UI3 a: the preview's caption); null without one. */
  served_built_at?: string | null
  /** Ruling A75: what the served figure is against the outfit worn now (`figure_build._served_state`); null without
   *  a served model, absent from an older server. */
  served_state?: ServedState | null
  /** Ruling A131: a new base body / body shape is being built, or the newest body has no fits of pieces fitted on
   *  the earlier one — those pieces are left off with "Waiting for the new body". */
  new_body?: boolean
  /** The saved outfit worn now, "" when none matches. */
  outfit: string
  /** Ruling A87: whether the plain body has a full-body reference (`full_body_reference.build_note`) — information
   *  beside the Build, never a step; absent from an older server. */
  full_body_reference?: { base: boolean } | null
  worn: FigureWornRow[]
  hair: FigureHairRow | null
  /** Ruling A61: what failed and what fixes it (`figure_build._build_problem`); null when nothing failed or while a
   *  Build runs. Absent from an older server. */
  problem?: BuildProblem | null
  body: {
    plain: FigureBodyPart & {
      /** `front_full_body` (Ruling A92): the front's Regenerate when it is made from the full-body reference — no skin
       *  step there (what a new full-body reference makes due). */
      jobs?: { view: number | null; front: number | null; front_full_body?: number | null; model: number | null
        after_front: number | null
        model_followup?: ModelFollowup | null }
    }
    /** `state`: ready · missing · plain (nothing in the body). `views` / `regenerate` (round 2026-11-25) only when
     *  something is worn in the body. */
    shape: FigureBodyPart & { views?: ShapeViewInfo[]; regenerate?: ShapeViewRegenerateState }
  } | null
}

/** One job that waits while the character's automatic generation is paused (`generation_pause.waiting`). */
export interface WaitingJob {
  /** What Cancel names (`POST …/figure/waiting/cancel {id}`). */
  id: string
  source: 'trigger' | 'garment' | 'task' | 'improvement'
  /** The tab the job belongs to ("Wardrobe", "Hairstyles", "Footwear", "Improvements"), "" for none. */
  tab: string
  label: string
  /** What it would run ("worn 2 + ghost 2 + mesh 1", the Build's steps), "" when nothing is known. */
  detail: string
  /** First-attempt hub jobs; null = unknown. */
  jobs: number | null
}

/** `GET …/figure`'s `generation_pause` (Ruling A42). */
export interface GenerationPause {
  paused: boolean
  /** SYSTEM stamp the pause began, null when not paused. */
  since: string | null
  waiting: WaitingJob[]
  /** What runs now and finishes (plain labels). */
  running: string[]
  /** The known first-attempt hub jobs of the waiting jobs, and how many have no estimate. */
  resume_jobs: number
  resume_unknown: number
}

/** The status light's line (checklist 8): what holds and how much. */
export function pauseLine(gp: GenerationPause, t: Tr = EN): string {
  if (!gp.paused) return t('Automatic generation on')
  const n = gp.waiting.length
  return n === 1 ? t('Automatic generation paused — 1 job held')
    : t('Automatic generation paused — {n} jobs held').replace('{n}', String(n))
}

/** Why, written under the light. */
export const PAUSE_REASON = 'Nothing starts by itself for this character: outfit changes, a new body or a finished '
  + 'piece only collect. Buttons you press still run. A job that is already running finishes.'

/** The Resume button with its cost (checklist 9): the known hub jobs, plus how many jobs have no estimate. */
export function resumeLabel(gp: GenerationPause, t: Tr = EN): string {
  if (!gp.waiting.length) return t('Resume — nothing waits')
  const known = gp.resume_jobs === 1 ? t('Resume — 1 hub job starts')
    : t('Resume — {n} hub jobs start').replace('{n}', String(gp.resume_jobs))
  if (!gp.resume_unknown) return known
  return `${known} ${gp.resume_unknown === 1 ? t('(+1 job of unknown cost)')
    : t('(+{n} jobs of unknown cost)').replace('{n}', String(gp.resume_unknown))}`
}

/** One compact line of the waiting list: "Waiting: Wardrobe · Blazer · worn 2 + mesh 1 — 3 hub jobs" ("no hub job"
 *  for 0: a held Build whose pieces wait in their own lines). */
export function waitingLine(job: WaitingJob, t: Tr = EN): string {
  // The server's label leads with the owning tab ("Wardrobe · Blazer"): the tab name is translated, the item not.
  const lead = job.tab && job.label.startsWith(`${job.tab} · `)
  const label = lead ? `${t(job.tab)}${job.label.slice(job.tab.length)}` : job.label
  const head = `${t('Waiting')}: ${label}`
  const detail = job.detail ? ` · ${job.detail}` : ''
  return `${head}${detail} — ${job.jobs === 0 ? t('no hub job') : jobsTr(job.jobs, t)}`
}

/** "1 change" / "N changes". */
export function changesText(n: number, t: Tr = EN): string {
  return n === 1 ? t('1 change') : t('{n} changes').replace('{n}', String(n))
}

function jobsTr(hubJobs: number | null, t: Tr): string {
  if (hubJobs === null) return t('cost unknown')
  return hubJobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(hubJobs))
}

export function imageJobsTr(jobs: number | null, t: Tr): string {
  if (jobs === null) return t('cost unknown')
  return jobs === 1 ? t('1 image job') : t('{n} image jobs').replace('{n}', String(jobs))
}

/** Ruling A90: a button's cost in short form, the long sentence on its mouse-over — "1 image + 4 hub",
 *  "2 images", "no job"; null parts read "cost unknown" / "hub cost unknown"; `hub` 0 or absent adds nothing. */
export function shortCost(images: number | null, hub?: number | null, t: Tr = EN): string {
  const parts: string[] = []
  if (images === null) parts.push(t('cost unknown'))
  else if (images > 0) parts.push(images === 1 ? t('1 image') : t('{n} images').replace('{n}', String(images)))
  if (hub === null) parts.push(t('hub cost unknown'))
  else if (hub) parts.push(t('{n} hub').replace('{n}', String(hub)))
  return parts.length ? parts.join(' + ') : t('no job')
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

/** The flow head's status words beside its light (Task UI5): what holds — the Build button beside it names the cost,
 *  so the line does not repeat it. "Up to date" · "2 changes" · "Out of date" (steps without a change of a piece) ·
 *  "1 change · a step failed" (with `failedStep`: "1 change · Assemble the figure failed") · "Building · 2 changes". */
export function headerLine(status: FigureStatus, changes: number, t: Tr = EN, failedStep?: string): string {
  if (status === 'up_to_date') return t('Up to date')
  if (status === 'building') return changes > 0 ? `${t('Building now')} · ${changesText(changes, t)}` : t('Building now')
  const head = changes > 0 ? changesText(changes, t) : t('Out of date')
  if (status !== 'failed') return head
  // A166: the failed step by name ("Out of date · Assemble the figure failed"), the generic words only without one.
  return failedStep ? `${head} · ${t('{step} failed').replace('{step}', t(failedStep))}` : `${head} · ${t('a step failed')}`
}

/** The flow head's light (checklist 8): green up to date · yellow changes · red a step failed · blue building. */
/** One piece the served figure lacks (Ruling A75): `reason` an English key, `detail` the measured refusal. */
export interface ServedMissing { item_id: string; name: string; reason: string; detail?: string; pending?: boolean }

/** `figure_build._served_state`: `reason` may hold `{pieces}`; `notes` are further sentences. */
export interface ServedState {
  light: Light
  state: string
  reason: string
  pieces?: string
  notes?: string[]
  missing: ServedMissing[]
}

/** The viewer's status lines of the served figure (Ruling A75; checklist point 8): the head line (light, state and
 *  reason, the notes on mouse-over), then one line per missing piece — "<name>: <reason>", its measured refusal on
 *  mouse-over. [] without a state. */
export function servedLines(s: ServedState | null | undefined, t: (k: string) => string):
  { light: Light | null; text: string; title: string; head: boolean }[] {
  if (!s) return []
  const reason = s.reason ? t(s.reason).replace('{pieces}', s.pieces || '') : ''
  const head = { light: s.light, text: reason ? `${t(s.state)} — ${reason}` : t(s.state),
    title: (s.notes || []).map((n) => t(n)).join(' '), head: true }
  return [head, ...s.missing.map((m) => ({ light: null, text: `${m.name}: ${t(m.reason)}`, title: m.detail || '',
    head: false }))]
}

export function statusLight(status: FigureStatus): Light {
  return status === 'up_to_date' ? 'green' : status === 'building' ? 'blue' : status === 'failed' ? 'red' : 'yellow'
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
  // Checklist 1: nothing due → the flow's button says so ("Everything is current", disabled).
  if (!f.cost.steps.length && !f.build.running) return { label: t(EVERYTHING_CURRENT), disabled: t(EVERYTHING_CURRENT) }
  return { label, disabled: null }
}

/** The Build's label when nothing is due (checklist 1). */
export const EVERYTHING_CURRENT = 'Everything is current'

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

/** Ruling UI3c: what a base step that changes a view in place makes stale — the stored base model, rebuilt by the
 *  next Build (server `figure_build._plain_jobs` `model_followup`: its hub stages, null = no base model stored). */
export interface ModelFollowup { jobs: number; stages: string[] }

/** On a base step's button, before the click (Ruling UI3c): "+3 hub jobs for the model (mesh, face, rig)"; "" when
 *  nothing goes stale. */
export function modelFollowup(f: ModelFollowup | null | undefined, t: Tr = EN): string {
  if (!f) return ''
  return t('+{cost} for the model ({stages})').replace('{cost}', jobsTr(f.jobs, t))
    .replace('{stages}', f.stages.join(', '))
}

/** The Figure tab's "Regenerate mesh" of a refused piece with its cost (the server's estimate). */
export function regenerateMeshLabel(jobs: number | null | undefined, t: Tr = EN): string {
  return jobs === undefined || jobs === null ? t('Regenerate mesh')
    : t('Regenerate mesh ({cost})').replace('{cost}', jobsTr(jobs, t))
}

/** Under "Run skin step" (and a new front): the base model is stale then, and only the next Build you start
 *  (a manual one — an automatic Build never rebuilds the plain body, ruling 8a) rebuilds it — what that costs. */
export function staleBaseNote(jobs: number | null, t: Tr = EN): string {
  return t('Makes the base model stale — the next Build you start rebuilds it ({cost})')
    .replace('{cost}', jobsTr(jobs, t))
}

/** The single actions' costs of the plain body (`figure_build._plain_jobs`, GET …/figure `body.plain.jobs`). */
export type PlainJobs = NonNullable<NonNullable<FigurePayload['body']>['plain']['jobs']>

/** Ruling A86: the front's Regenerate where its outdated reason is written — the Base body tab's reference row and
 *  the Figure tab's plain-body change. The same action as the front tile's Regenerate (POST …/base-body/images
 *  {view: "front", force: true}). `method` is what the front is made from now (`reference` = the profile image,
 *  `full_body` = the full-body reference — Ruling A87, `text`).
 *  The cost is on the button before the click: the front's image jobs, plus — while a base model is stored
 *  (`model_followup`) — what the new front makes due, the other three views and the base model, which the next
 *  Build you start rebuilds (`after_front`, the same count as the front tile's). `note` says that in a sentence
 *  (`staleBaseNote`), "" when nothing goes stale. */
export function frontRegenerate(method: string | undefined, jobs: PlainJobs | undefined, t: Tr = EN): {
  label: string; note: string
} {
  // Ruling A87: `full_body` — the front is an edit of the full-body reference.
  const action = method === 'text' ? t('Regenerate front from text')
    : method === 'full_body' ? t('Regenerate front from the full-body reference')
    : t('Regenerate front from the profile image')
  if (!jobs) return { label: action, note: '' }
  const now = imageJobsTr(jobs.front, t)
  if (!jobs.model_followup) return { label: `${action} — ${now}`, note: '' }
  return {
    label: t('{action} — {now} + {later} at the next Build').replace('{action}', action).replace('{now}', now)
      .replace('{later}', jobsTr(jobs.after_front, t)),
    note: staleBaseNote(jobs.after_front, t),
  }
}

/** Ruling A86: beside the front's Regenerate on the Figure tab — the Build covers the change too, in one go, its
 *  count the plan's plain-body step (`FigureChange.jobs`); "" when the plan has no such step. */
export function frontBuildCovers(jobs: number | null | undefined, t: Tr = EN): string {
  if (jobs === 0 || jobs === undefined) return ''
  return t('Or Build: it renders the front, the other views and the base model in one go — {cost}')
    .replace('{cost}', jobsTr(jobs, t))
}

/** Ruling A86: the front's Regenerate refused while a Build of the character runs (the server answers 409). */
export const FRONT_WAITS_FOR_BUILD = 'A Build runs for this character — regenerating the front waits until it has ended'

/** Under a piece whose fit on the body shape was refused (Ruling A23, A31 wording): it is left off the figure
 *  (Ruling A119); what each button does. */
export const FIT_REFUSED_NOTE = 'Left off the figure. Re-fit tries again on the CPU (no hub job). A new mesh only helps when the piece itself is broken.'
/** The status light's words of a fit the user accepted although its checks refused it (Ruling A31). */
export const ACCEPTED_BY_YOU = 'Accepted by you'

/** The image steps of a clothing chain in the words of the garment window's step grid (Ruling A69's marker). */
const IMAGE_STEP_WORDS: Record<string, string> = { worn: 'Worn views', ghost: 'Piece-only views', cutout: 'Cut-outs' }

/** Ruling A69: what the user accepted against its checks and why it was refused, in one line — the fit ("Plain
 *  body: its checks refused it — <reason>", Ruling A31's words), the mesh ("Mesh: its gate refused it — <reason>")
 *  or an image ("Piece-only views · Back view: its gate refused it — <reason>"). */
export function acceptedWhat(a: { step?: string; view?: string; on?: string; reason: string }, t: Tr = EN): string {
  const step = a.step || 'fit'
  if (step === 'fit') {
    return a.on
      ? t('{body}: its checks refused it — {reason}').replace('{body}', bodyWords(a.on, t)).replace('{reason}', a.reason)
      : t('Fit: its checks refused it — {reason}').replace('{reason}', a.reason)
  }
  const what = step === 'mesh' ? t('Mesh')
    : `${t(IMAGE_STEP_WORDS[step] || step)} · ${a.view === 'back' ? t('Back view') : t('Front view')}`
  return a.reason
    ? t('{what}: its gate refused it — {reason}').replace('{what}', what).replace('{reason}', a.reason)
    : t('{what}: its gate refused it').replace('{what}', what)
}

/** A worn row as a step (checklist 8): its light, the state on the right, the reason in plain words under it and
 *  the mouse-over. Green ready (or accepted by you) · yellow due (waits for the Build, its own mesh missing) ·
 *  blue building · red failed or refused · grey left out. */
export function wornState(row: Pick<FigureWornRow, 'state' | 'mode' | 'jobs' | 'failure' | 'left_out' | 'note'
  | 'fit_refused' | 'refused_on' | 'accepted_by_user' | 'fit_refused_detail'>, t: Tr = EN): {
  light: Light; text: string; sub: string | null; detail: string
} {
  switch (row.state) {
    case 'ready': return row.accepted_by_user
      ? {
        light: 'green',
        text: t('Ready — {accepted}').replace('{accepted}', t(ACCEPTED_BY_YOU)),
        sub: acceptedWhat(row.accepted_by_user, t),
        detail: row.accepted_by_user.detail || '',
      }
      : { light: 'green', text: t('Ready'), sub: null, detail: '' }
    case 'failed': return { light: 'red', text: t('Failed'), sub: row.failure || row.note, detail: '' }
    case 'fit_refused': return {
      light: 'red',
      text: t('Refused on the body shape'),
      sub: (row.refused_on
        ? t('Fits the plain body — refused on the body shape ({pieces}): {reason}').replace('{pieces}', row.refused_on)
        : t('Fits the plain body — refused on the body shape: {reason}'))
        .replace('{reason}', row.fit_refused || row.note),
      detail: [t(FIT_REFUSED_NOTE), row.fit_refused_detail || ''].filter(Boolean).join('\n'),
    }
    case 'left_out': return { light: 'grey', text: t('Left out'), sub: t(row.left_out || row.note), detail: '' }
    case 'building': return { light: 'blue', text: t('Building now'), sub: null, detail: '' }
    default:
      if (row.mode === 'template') {
        return { light: 'yellow', text: t('Due: template drape · CPU, 0 hub jobs'), sub: null, detail: '' }
      }
      return isOwnMeshMode(row.mode)
        ? { light: 'yellow', text: t('Due: own mesh · {cost}').replace('{cost}', jobsTr(row.jobs, t)), sub: null, detail: '' }
        : { light: 'yellow', text: t('Waits for the Build'), sub: null, detail: '' }
  }
}

/** A body's words from the server ("Plain body", "Body shape (t-shirt)", "Body shape ob12345678"), translated
 *  around the piece names (Ruling A31). */
export function bodyWords(label: string, t: Tr = EN): string {
  if (label === 'Plain body') return t('Plain body')
  const named = /^Body shape \((.*)\)$/.exec(label)
  if (named) return t('Body shape ({pieces})').replace('{pieces}', named[1])
  const id = /^Body shape (\S+)$/.exec(label)
  return id ? t('Body shape {id}').replace('{id}', id[1]) : label
}

/** Ruling A67: a dialog body's short name — "Base body" or "Current body" (the derived shoe's entry included). */
export function fitBodyName(b: Pick<FitBody, 'role'>, t: Tr = EN): string {
  return b.role === 'current' ? t('Current body') : t('Base body')
}

/** Ruling A67: a dialog body's name with what is in the current body shape — "Current body (t-shirt, jeans)"; the
 *  base body and a shape without piece names keep the short name. */
export function fitBodyLongName(b: Pick<FitBody, 'role' | 'label'>, t: Tr = EN): string {
  const named = b.role === 'current' ? /^Body shape \((.*)\)$/.exec(b.label) : null
  return named ? t('Current body ({pieces})').replace('{pieces}', named[1]) : fitBodyName(b, t)
}

/** One body of the piece dialog's body switch (Ruling A31; Ruling A67: the base body and the current body only,
 *  `fit_attempts.bodies`). */
export interface FitBody {
  /** "" = the plain body, else the outfit body id. */
  body: string
  /** "plain" or the body id — the route's path segment. */
  key: string
  label: string
  status: 'accepted' | 'user_accepted' | 'refused' | 'stale' | 'missing'
  /** The verdict in plain words ("" when accepted). */
  reason: string
  /** The measured reasons (tooltip). */
  reason_detail: string
  piece_broken: boolean
  /** The model to show (versioned), null: nothing to show. */
  url: string | null
  built_at: string | null
  marks: Array<{ kind: string; count: number; colour: string; label: string }>
  foot_pose: unknown
  can_accept: boolean
  /** Why it cannot be accepted ("" when it can). */
  accept_block: string
  accepted_at: string | null
  /** How a body shape's shoe was fitted (Ruling A40, `fit_attempts.FIT_METHOD_NOTES`): "" or a fixed phrase. */
  method_note?: string
  /** "derived": a body shape's refused derived shoe, kept beside the fresh fit that followed it (Ruling A40). */
  variant?: '' | 'derived'
  /** Ruling A67: "base" = the plain base body, "current" = the body shape the worn outfit calls for. */
  role: 'base' | 'current'
  /** Why Re-fit cannot run on this body ("" when it can) — the current body shape is not built yet. */
  refit_block?: string
  /** Ruling A47: skin seen inside the sleeves of what is shown (`garment_fit.arm_light`), null before it existed. */
  arm_light?: ArmLight | null
  /** Ruling A50: this body's own numbers (`fit_attempts.body_numbers` of what is shown), {} when nothing is. */
  numbers?: FitBodyNumbers
  /** Ruling A50b: this body's fit as the dialog's fit row, chips and settings box show it (`body_fit_view`);
   *  null when the body shows nothing. */
  fit?: FitBodyFit | null
  /** Ruling A82: a shoe's allowance preview frame of what is shown (`garment_footwear.preview_frame`). */
  shoe_frame?: ShoeFrame | null
}

/** One body's fit for the piece dialog (Ruling A50b, `fit_attempts.body_fit_view`). */
export interface FitBodyFit {
  metrics: Record<string, unknown>
  tris: number | null
  created_at: string | null
  gates_ok: boolean
  /** The refusing gate's reasons ([] when accepted). */
  reasons: string[]
  /** The fit settings box of this body's fit (footwear: null). */
  fit_settings: FitSettingsInfo | null
}

/** A body's own fit numbers (Ruling A50): the sleeve skin per side, the push / tightness shares, the trunk
 *  coverage per side against the source (the outfit-body gate's shares). */
export interface FitBodyNumbers {
  sleeve_skin_left_cm2?: number | null
  sleeve_skin_right_cm2?: number | null
  deep_push_share?: number | null
  torso_tight_share?: number | null
  scale_retry?: number | null
  torso?: Partial<Record<'front' | 'side' | 'back', { fit: number; source: number }>> | null
}

/** The slot of a body shape's Re-fit button (its run feedback, Ruling A50). */
export const refitSlot = (body: string) => `fit|body:${body}`

/** The body switch is worth showing when there is more than the base body's accepted fit to see. */
export function showBodySwitch(bodies: FitBody[] | undefined): boolean {
  return !!bodies && (bodies.length > 1 || bodies.some((b) => b.status !== 'accepted'))
}

/** Ruling A67: the body the dialog opens on — the current body shape (its main entry, not a derived shoe), else
 *  the base body. */
export function defaultBodyKey(bodies: FitBody[] | undefined): string {
  return (bodies || []).find((b) => b.role === 'current' && b.variant !== 'derived')?.key || 'plain'
}

/** The hair row as a step (checklist 8): light, state, the line under it. */
export function hairState(hair: FigureHairRow, t: Tr = EN): { light: Light; text: string; sub: string | null } {
  const sub = hair.note && hair.state !== 'failed' ? t(hair.note) : null
  switch (hair.state) {
    case 'ready': return { light: 'green', text: t('Ready'), sub: null }
    case 'failed': return { light: 'red', text: t('Failed'), sub: hair.note }
    case 'building': return { light: 'blue', text: t('Building now'), sub }
    default:
      return {
        light: 'yellow',
        text: hair.rebuild
          ? t('Due: plain body rebuild · {cost}').replace('{cost}', jobsTr(hair.jobs, t))
          : t('Due: {mode} · {cost}').replace('{mode}', t(HAIR_MODE_LABELS[hair.mode as HairMode] || hair.mode))
            .replace('{cost}', jobsTr(hair.jobs, t)),
        sub,
      }
  }
}

/** Which body row a running Build's step builds (Ruling A55, the reverse check: a row never reads "Current" while
 *  the Build works on it). The other steps are the worn pieces' rows. */
export const BUILD_STEP_BODY_ROW: Record<string, 'plain' | 'shape'> = {
  plain_body: 'plain', base_repair: 'plain', tip_smoothing: 'plain', shape: 'shape',
}

/** The body the pieces are worn on as two steps (checklist 8): the plain body (its flow is the Base body tab) and
 *  the body shape (what is in the body, meshed by the Build). `buildStep` = the running Build's step name (`build.step.name`, null when none runs): the row it builds
 *  reads blue "Building now" (`BUILD_STEP_BODY_ROW`). */
export function bodyRows(body: NonNullable<FigurePayload['body']>, shapeNames: string[],
  t: Tr = EN, buildStep: string | null = null): Array<{ key: 'plain' | 'shape'; name: string; light: Light;
    state: string; reason: string }> {
  const building = buildStep ? BUILD_STEP_BODY_ROW[buildStep] : undefined
  return bodyRowsAtRest(body, shapeNames, t)
    .map((row) => row.key === building ? { ...row, light: 'blue' as Light, state: t('Building now') } : row)
}

function bodyRowsAtRest(body: NonNullable<FigurePayload['body']>, shapeNames: string[],
  t: Tr): Array<{ key: 'plain' | 'shape'; name: string; light: Light; state: string; reason: string }> {
  const plain = body.plain.state
  const names = (list: string[]) => list.join(', ')
  return [
    {
      key: 'plain', name: t('Plain body'),
      light: plain === 'ready' ? 'green' : 'yellow',
      state: plain === 'ready' ? t('Current') : plain === 'missing' ? t('None yet') : t('Outdated'),
      reason: baseBodyLine(plain, t),
    },
    body.shape.state === 'plain'
      ? { key: 'shape', name: t('Body shape'), light: 'grey', state: t('Not needed'), reason: t('Nothing is worn in the body') }
      : {
        key: 'shape', name: t('Body shape'),
        light: body.shape.state === 'ready' ? 'green' : 'yellow',
        state: body.shape.state === 'ready' ? t('Current') : t('Due'),
        reason: (body.shape.state === 'ready' ? t('In the body: {names}') : t('In the body: {names} — the Build meshes it'))
          .replace('{names}', names(shapeNames) || '–'),
      },
  ]
}

/** The Build's planned steps as rows (checklist 8): red a chain that failed for its input (a manual Build retries
 *  it), blue the step in flight, yellow due; the cost on the right. */
/** The reason of the Build's collision step (cross-person collision Task 15): a channel setting saved since. */
export const COLLISION_STEP_REASON = 'Channel settings were saved and are not applied yet — recomputes the capsules of every stored model'

export function planRows(f: Pick<FigurePayload, 'cost' | 'build'>, t: Tr = EN): Array<{
  key: string; name: string; light: Light; state: string; reason: string
}> {
  const running = f.build.running ? f.build.step : null
  return f.cost.steps.map((s, i) => ({
    key: `${s.name}:${s.item_id}:${i}`,
    // The collision step's label is a fixed phrase (`figure_build.COLLISION_LABEL`): translated, with its reason.
    name: s.name === 'collision' ? t(s.label) : s.label,
    light: running && running.name === s.name && running.item_id === s.item_id ? 'blue' : s.failed ? 'red' : 'yellow',
    state: s.jobs === null ? t('cost unknown') : s.jobs ? jobsTr(s.jobs, t) : t('no hub job'),
    reason: [s.failed ? `${t('Failed')}: ${s.failure?.lines.length ? failureLines(s.failure, t).join(' ') : s.failed}` : '',
      s.manual ? t(s.manual) : '',
      s.name === 'collision' ? t(COLLISION_STEP_REASON) : ''].filter(Boolean).join(' · '),
  }))
}

/** Beside a closable piece's Closed / Open (checklist 2, 9): the switch is saved at once; what it starts and costs —
 *  with Build automatically on the Build follows by itself, its cost the other state's mesh of an own-mesh piece
 *  (`other_state_jobs`, 0 = built); else it only becomes due. */
export function stateToggleNote(row: Pick<FigureWornRow, 'mode' | 'other_state_jobs'>, autoBuild: boolean,
  t: Tr = EN): string {
  if (!autoBuild) return t('Saved at once — nothing runs; the change waits for Build')
  if (isOwnMeshMode(row.mode) && row.other_state_jobs !== null) {
    return row.other_state_jobs === 0 ? t('Switching starts the Build — no hub job (that mesh is built)')
      : t('Switching starts the Build — {cost} for that mesh').replace('{cost}', jobsTr(row.other_state_jobs, t))
  }
  return t('Switching starts the Build — cost unknown')
}

/** "Build automatically" beside its checkbox (checklist 2): saved at once, never runs anything itself. */
export function autoBuildNote(on: boolean, t: Tr = EN): string {
  return on ? t('Saved — changes start the Build by themselves')
    : t('Saved — changes wait for Build')
}

/** A piece's single steps on the Figure tab with their cost (checklist 9). */
export const REFIT_LABEL = 'Re-fit — no hub job'
export function retryLabel(hubJobs: number | null, t: Tr = EN): string {
  return t('Retry — {cost}').replace('{cost}', jobsTr(hubJobs, t))
}

/** The Figure tab's one line on the base body (Task UI1 — its steps live in the Base body tab). */
export function baseBodyLine(state: string, t: Tr = EN): string {
  if (state === 'ready') return t('Base body: up to date — its views, model, face and rig are in the Base body tab')
  if (state === 'missing') return t('Base body: none yet — the Build makes it, or Run all in the Base body tab')
  return t('Base body: outdated — the Build refreshes it, or Run all in the Base body tab')
}

/** Why a stored outfit model is stale (`base_body.outfit_info` / `model3d` info `stale_reason`). */
export type ModelStaleReason = 'older_base' | 'before_pipeline' | 'detail_changed' | 'figure' | 'outfit_body'

/** The line under a stale outfit model (the Figure tab's Outfit model, the 3D tab). `before_pipeline` is a model made without the base
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
  /** The modes that can be chosen today (`garment_hair.BUILT_MODES`). */
  built_modes: HairMode[]
  /** Ruling A54: the standard text a new hairstyle starts from (the Appearance's hair text; "" without hair). */
  appearance_hair_text?: string
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
 *  an empty description first, then a mode the server does not list as built (`built`). */
export function newHairstyleDisabled(description: string, mode: HairMode,
  built: readonly string[] = HAIR_MODES): string | null {
  if (!description.trim()) return 'Describe the hairstyle'
  return hairModeDisabled(mode, built)
}

/** `garments.run_estimate` of a hairstyle (GET …/hair?item_id= `run`). */
export interface HairstyleRun {
  steps: string[]
  hub_jobs: number | null
  note: string
  refit: boolean
  /** HAAR only: the CPU fits the run makes (one per seed it fits). */
  cpu_fits?: number
}

/** The flow of the selected hairstyle as buttons (rules R1/R2):
 *  - HairDeck has two steps (HairDeck → fit), so it has a Run all — the steps from the first one not current,
 *    named with its cost: "Create + fit (1 hub job)" when HairDeck runs, "Re-fit (no hub job)" when only the fit
 *    is due, "Everything is current" disabled when nothing is; no estimate → plain "Run all" (the server decides);
 *  - its single steps re-run even when current: "Regenerate hair (HairDeck) — 1 hub job" (a new seed, then the
 *    fit) and "Re-fit — no hub job";
 *  - HAAR has two steps too (strands → fit): "Run all · 3 hub jobs" when the strands are due, "Run all · no hub job"
 *    when only the CPU fits are, "Everything is current" at 0 (strand-hair spec § 6.3.4); its cost line is
 *    `haarRunCost`;
 *  - `body` has no run of its own: the hair is part of the body, the Figure tab's Build makes it. */
export function hairstyleActions(mode: HairMode, run: HairstyleRun | null | undefined, t: Tr = EN): {
  runAll: { label: string; disabled: boolean } | null
  regenerate: string | null
  refit: string | null
} {
  if (mode === 'haar') {
    let haarAll: { label: string; disabled: boolean }
    if (!run) haarAll = { label: t('Run all'), disabled: false }
    else if (!run.steps.length) haarAll = { label: t('Everything is current'), disabled: true }
    else if (run.hub_jobs === 0) haarAll = { label: t('Run all · no hub job'), disabled: false }
    else haarAll = { label: t('Run all · {cost}').replace('{cost}', jobsTr(run.hub_jobs, t)), disabled: false }
    return { runAll: haarAll, regenerate: null, refit: null }
  }
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

/**
 * A failed step of the Build as the tabs that run it say it (Ruling A61, checklist point 8: the step, the reason in
 * plain words, the view, the action that fixes it with its cost). `kind` failed: a failed step, `detail` its error,
 * `action` retry (a manual Build), `jobs` what the Build spends. `held`: automatic Builds do not repeat it until its inputs change.
 */
/** A166: a failed step's words when only its key is known (`figure_build.STEP_LABELS`). */
export const STEP_NAMES: Record<string, string> = { plain_body: 'Plain body', shape: 'Body shape', pieces: 'Own mesh',
  template: 'Template drape', hair: 'Hair', views: 'Views', fits: 'Fits on the CPU', assemble: 'Assemble the figure',
  collision: 'Collision capsules', build: 'Build' }

export interface BuildProblem {
  kind: 'failed'
  step: string
  step_label: string
  view: string
  body: 'plain' | 'shape' | ''
  detail: string
  action: 'retry'
  jobs: number | null
  held: boolean
  /** The structured failure of a step that has one (today the template drape, `garment_template.failure_info`);
   *  null / absent otherwise. */
  failure?: StepFailure | null
}

/** How a Blender run ended (`app/blender/outcome.py`). */
export type RunOutcome = 'ok' | 'rejected' | 'timeout' | 'interrupted' | 'cancelled' | 'unavailable' | 'crashed'

/** One check of a drape (`garment_template.judge_build`): `gate` false = reported only (the work time, CPU,
 *  texture coverage) — over its limit it never refuses the drape. */
export interface FailureRow { check: string; value: number | null; limit: number | null; ok: boolean; gate: boolean }

/** A step's failure as data (`garment_template.failure_info`): `lines` the plain sentences (English with
 *  `{placeholders}`, put through `t()` and filled from `values`), `rows` every check of the run, `log_tail` the end
 *  of Blender's output ("" when there is none), `error` the raw message. */
export interface StepFailure {
  outcome: RunOutcome
  lines: { text: string; values: Record<string, string> }[]
  rows: FailureRow[]
  log_tail: string
  error: string
}

/** A run that ended without a verdict: nothing was judged, the work stays due — a note, never a red failure. */
export function isLeftDue(f: Pick<StepFailure, 'outcome'> | null | undefined): boolean {
  return !!f && (f.outcome === 'timeout' || f.outcome === 'interrupted' || f.outcome === 'unavailable')
}

/** The failure's plain sentences, translated and filled. */
export function failureLines(f: StepFailure, t: Tr = EN): string[] {
  return f.lines.map((l) => Object.entries(l.values || {})
    .reduce((s, [k, v]) => s.split(`{${k}}`).join(v), t(l.text)))
}

/** A drape check's words in the Details table (`check` names of `judge_build`; `poke_share[<pose>]` per pose). */
export const CHECK_LABELS: Record<string, string> = {
  build_wall_s: 'Work time (s)', drape_cpu_s: 'Cloth CPU time (s)', pin_drift_mm: 'Top edge moved (mm)',
  stretch_max: 'Largest stretch (×)', poke_share: 'Body through the fabric (share)',
  bake_coverage: 'Texture coverage (share)', bake_iou: 'Texture outline match (IoU)',
}
/** The pose a per-pose check was measured in (`MEASURED_POSES` / `MEASURED_UPPER_POSES`). */
export const POSE_WORDS: Record<string, string> = {
  rest: 'rest pose', walk: 'walk pose', sit: 'sit pose', kneel: 'kneel pose', arms_down: 'arms down',
  arms_forward: 'arms forward', arms_up: 'arms raised',
}

/** One row of the Details table: the check's words, the value against its limit, what it did — "passed", "failed"
 *  (a gate), "slow" (the work time over its budget) or "over the limit" (reported only) — and its effect (a gate can
 *  refuse the drape, the others are reported only). */
export function failureRowText(r: FailureRow, t: Tr = EN): {
  check: string; value: string; limit: string; result: string; effect: string
} {
  const m = /^([a-z_]+)\[([a-z_]+)\]$/.exec(r.check)
  const base = m ? m[1] : r.check
  const check = m ? `${t(CHECK_LABELS[base] || base)} — ${t(POSE_WORDS[m[2]] || m[2])}` : t(CHECK_LABELS[base] || base)
  const result = r.ok ? t('passed') : r.gate ? t('failed') : base === 'build_wall_s' ? t('slow') : t('over the limit')
  return { check, value: r.value == null ? '—' : String(r.value), limit: r.limit == null ? '—' : String(r.limit),
    result, effect: r.gate ? t('can refuse the drape') : t('reported only') }
}

/** The attempts of a gate refusal joined by `garment_gates.gate_summary` ("… refused — attempt 1: … | attempt 2:
 *  …"), one per line; a message without that seam is one line. */
export function attemptLines(detail: string): string[] {
  return detail.split(' | ').map((s) => s.trim()).filter(Boolean)
}

const VIEW_WORDS: Record<string, string> = { front: 'Front view', back: 'Back view', left: 'Left view',
  right: 'Right view' }
/** The same inside a sentence. */
const VIEW_PHRASES: Record<string, string> = { front: 'front view', back: 'back view', left: 'left view',
  right: 'right view' }
export const HELD_NOTE = 'Automatic Builds do not repeat this step until its inputs change — the button runs it once '
  + 'more.'
/** The reason of any other failed step: the worker's own message stays on mouse-over (it is not translated). */
export const FAILED_AT_VIEW = 'The step stopped at the {view} — the message is on mouse-over.'
export const FAILED_PLAIN = 'The step stopped with an error — the message is on mouse-over.'
/** A step's reason when its message lists several attempts (`attemptLines`): each is a line of its own below. */
export const FAILED_ATTEMPTS = 'The step was refused on every attempt — each attempt’s reasons are below.'
/** The title of a step whose run ended without a verdict (`isLeftDue`): a note, not a failure. */
export const LEFT_DUE_TITLE = '{step} — left due'

/** The lines of a `BuildProblem`: `title` "<step> failed — <view>", `reason` in plain words, `action` the button
 *  with its cost, `note` why nothing repeats it by itself, `detail` the raw message (mouse-over). */
export function problemText(p: BuildProblem, t: Tr = EN): {
  title: string; reason: string; action: string; note: string; detail: string
} {
  const view = VIEW_WORDS[p.view] ? t(VIEW_WORDS[p.view]) : ''
  const step = t(p.step_label)
  const title = view ? t('{step} failed — {view}').replace('{step}', step).replace('{view}', view)
    : t('{step} failed').replace('{step}', step)
  const cost = p.jobs === 0 ? t('no hub job') : jobsTr(p.jobs, t)
  const viewPhrase = VIEW_PHRASES[p.view] ? t(VIEW_PHRASES[p.view]) : ''
  if (p.failure && p.failure.lines.length) {
    // The structured failure says what is wrong in plain words; the raw message goes behind "Details".
    const leftDue = isLeftDue(p.failure)
    return {
      title: leftDue ? t(LEFT_DUE_TITLE).replace('{step}', step) : title,
      reason: failureLines(p.failure, t).join(' '),
      action: t('Retry this step — {cost}').replace('{cost}', cost),
      note: p.held && !leftDue ? t(HELD_NOTE) : '',
      detail: p.detail,
    }
  }
  return {
    title,
    reason: viewPhrase ? t(FAILED_AT_VIEW).replace('{view}', viewPhrase)
      : attemptLines(p.detail).length > 1 ? t(FAILED_ATTEMPTS) : t(FAILED_PLAIN),
    action: t('Retry this step — {cost}').replace('{cost}', cost),
    note: p.held ? t(HELD_NOTE) : '',
    detail: p.detail,
  }
}

/** A168: `garment_template.piece_progress` — this character's drape of the piece. */
export interface TemplateProgress {
  state: 'ready' | 'missing' | 'failed' | 'blocked' | 'running'
  reason: string
  built_at: string
  error: string
  /** The character wears the piece now (only a worn piece is draped by the Build). */
  worn: boolean
  steps: ModelStep[]
  /** A172: what the drape in flight does now (`garment_template.live_progress`); null when it is not draping. */
  live?: TemplateLive | null
  /** A200: how the own-mesh pieces under it took part in the ready drape (`full` / `shrunk` / `dropped`) and the
   *  attempts that failed a stretch / poke gate first; absent without own-mesh pieces under it. */
  inner_collider?: { mode: 'full' | 'shrunk' | 'dropped'; failed: { mode: string; error: string }[] } | null
  /** The failed drape as data (`state` "failed"); null otherwise. */
  failure?: StepFailure | null
  /** Bug round 2026-11-20: the drape shown moved the hem off the underbust fold (`garment_template._clear_underbust`):
   *  the length asked and the length draped, in metres; null when the hem stayed where it was asked. */
  hem_moved?: { length_m: number; draped_length_m: number; under_y: number } | null
}

/** A172: the live step of a drape in flight. `label` is the stage (a translatable key); frame / pose / index are
 *  null where the stage has none. */
export interface TemplateLive {
  stage: string
  label: string
  frame: number | null
  frames: number | null
  pose: string | null
  index: number | null
  count: number | null
  attempt: number
  elapsed_s: number
  stage_s: number
  /** A194: the shared live line of the drape (`cpu_progress`), null when it reports nothing. */
  cpu?: CpuProgress | null
}

/** A172: one line of a drape in flight — "Draping the pose shapes 2/4 (sit) · frame 8/16 · retry · 34 s". */
export function templateLiveText(live: TemplateLive, t: (s: string) => string): string {
  // A194: the shared line ("Stage · i/n · 42 s") wherever the server has one; the A172 record otherwise.
  if (live.cpu) return cpuProgressText(live.cpu, t) + (live.attempt > 1 ? ` · ${t('retry with finer cloth')}` : '')
  const parts = [t(live.label)]
  if (live.index && live.count) {
    parts[0] += ` ${live.index}/${live.count}${live.pose ? ` (${live.pose.replace(/_/g, ' ')})` : ''}`
  }
  if (live.frame && live.frames) {
    parts.push(t('frame {n}/{m}').replace('{n}', String(live.frame)).replace('{m}', String(live.frames)))
  }
  if (live.attempt > 1) parts.push(t('retry with finer cloth'))
  parts.push(`${Math.round(live.elapsed_s)} s`)
  return parts.join(' · ')
}

export const TEMPLATE_STATE_LABELS: Record<TemplateProgress['state'], string> = {
  ready: 'Draped', missing: 'Not draped yet', failed: 'Drape failed', blocked: 'Cannot drape yet',
  running: 'Draping…',
}
export const TEMPLATE_STATE_COLOR: Record<TemplateProgress['state'], string> = {
  ready: 'var(--success, #3fb950)', missing: 'var(--warning, #d29922)', failed: 'var(--danger, #f85149)',
  blocked: 'var(--warning, #d29922)', running: 'var(--accent, #6aa9ff)',
}

// --- Accessories (Ruling A118, A216) ---------------------------------------------------------------------------

/** An accessory's item-wide description (`accessory_spec.normalize`); only the fields the dialog edits are typed. */
export interface Jewellery {
  kind: string
  chain?: { drop_cm?: number; thickness_mm?: number; style?: string }
  metal?: string
  /** A225: the pendant from the item image, null: none. */
  pendant?: { from_image?: boolean; size_mm?: number } | null
  /** A234: a band (belt / choker / strap) and the height of any ring-shaped kind. */
  band?: { height_cm?: number; width_cm?: number; layer?: string; material?: string; at?: string }
  /** A234: a belt's buckle from the item image, null: none. */
  buckle?: { from_image?: boolean; size_mm?: number } | null
  side?: string
  finger?: string
  /** A238: where on the finger's proximal bone the ring sits (share from the knuckle). */
  ring?: { along?: number }
  /** A234: earrings — stud / hoop (CPU) or drop (from the item image). */
  earring?: { style?: string; size_mm?: number }
  /** An acetate glasses frame's colour (and `metal: custom`'s). */
  color?: string
  /** Glasses (`accessory_spec.normalize_glasses`). */
  glasses?: GlassesSpec
  [key: string]: unknown
}

/** Glasses: the frame outline, size step, rim thickness, frame material, temple ends and the lenses. */
export interface GlassesSpec {
  shape?: string
  size?: string
  rim_mm?: number
  frame?: string
  temple?: string
  lens?: { tint?: string; opacity?: number; mirror?: boolean; color?: string }
}

/** GET …/accessory: the glasses' choices and defaults (`accessory_spec`). */
export interface GlassesOptions {
  shapes: string[]
  sizes: string[]
  frames: string[]
  temples: string[]
  tints: string[]
  rim_mm: Record<string, number>
  clear_opacity: number
  sun_opacity: number
  tint_colors: Record<string, string>
  acetate_color: string
}

/** The glasses' sizes from the face (the stored build's metrics, or the live preview's). */
export interface GlassesNumbers {
  frame_mm?: number
  lens_mm?: [number, number]
  bridge_mm?: number
  arms_mm?: Record<string, number>
  forward_mm?: number
  ear_used?: Record<string, boolean>
  ear_note?: Record<string, string>
  ear_above_mm?: Record<string, number | null>
  ear_range_mm?: [number, number]
  temple_ends?: Record<string, string>
  pad_gap_mm?: number | null
}

/** A225: the pendant line of an accessory (`accessory_build.pendant_row`). */
export interface AccessoryPendant {
  state: 'ready' | 'running' | 'missing' | 'refused' | 'failed' | 'no_image' | string
  reason: string
  size_mm: number
  on_figure: boolean
  metrics: { size_mm?: number; gap_mm?: number; tilt_deg?: number;
    poses?: Record<string, { gap_min_mm: number; inside_share: number }> } | null
  cost: { hub_jobs: number }
}

/** GET /characters/{c}/figure/accessory/{item}. */
export interface AccessoryInfo {
  item_id: string
  name: string
  mode: string
  jewellery: Jewellery | null
  suggested: string | null
  kinds: string[]
  built_kinds: string[]
  drop_presets: Record<string, number>
  metals: string[]
  cords: string[]
  cord_thickness_mm: number
  pendant_defaults: { from_image: boolean; size_mm: number }
  pendant: AccessoryPendant | null
  ranges: Record<string, [number, number]>
  /** A234 */
  strap_at: string[]
  earring_styles: string[]
  band_materials: string[]
  fingers: string[]
  sides: string[]
  /** A238: a ring is on one hand. */
  ring_sides: string[]
  kind_widths: Record<string, number>
  kind_thickness: Record<string, number>
  glasses?: GlassesOptions
  part_name: string
  state: 'current' | 'due' | 'blocked' | 'failed' | string
  reason: string
  metrics: { gap_mm?: { min?: number; p50?: number; p95?: number }; inside_share?: number; triangles?: number;
    on_clothing_share?: number; length_m?: Record<string, number>;
    poses?: Record<string, { gap_min_mm: number; inside_share: number }>;
    /** A238: the ring's size from the skeleton. */
    inner_radius_mm?: number; hand_width_mm?: number; bone_length_mm?: number; clamped?: boolean } & GlassesNumbers | null
  built_at: string
  cost: { hub_jobs: number }
  glb_url: string
}

export const ACCESSORY_KIND_LABELS: Record<string, string> = {
  necklace: 'Necklace', choker: 'Choker', earrings: 'Earrings', bracelet: 'Bracelet', ring: 'Ring',
  anklet: 'Anklet', belt: 'Belt', strap: 'Strap', glasses: 'Glasses',
}

/** A234: the kinds that are a flat band, the ones that are a round tube round a limb (A238: the ring is sized from
 *  the skeleton and has its own fields). */
export const BAND_KINDS = ['belt', 'choker', 'strap']
export const TUBE_KINDS = ['anklet', 'bracelet']
/** A234: what the item-image part of a kind is called (`accessory_spec.PART_NAMES`). */
export const ACCESSORY_PART_NAMES: Record<string, string> = { necklace: 'Pendant', belt: 'Buckle', earrings: 'Earring drop' }
export const ACCESSORY_BAND_MATERIAL_LABELS: Record<string, string> = {
  leather: 'Leather', metal: 'Metal', fabric: 'Fabric', from_image: 'Colour from the item image',
}
export const ACCESSORY_STRAP_AT_LABELS: Record<string, string> = { thigh: 'Thigh', upper_arm: 'Upper arm', chest: 'Under the chest' }
export const ACCESSORY_EARRING_LABELS: Record<string, string> = { stud: 'Stud', hoop: 'Hoop', drop: 'Drop from the item image' }
/** A234: the CPU test poses of the gates. */
export const ACCESSORY_POSE_LABELS: Record<string, string> = { rest: 'Rest pose', walk: 'Walk pose', sit: 'Sit pose', run: 'Run pose' }
export const ACCESSORY_SIDE_LABELS: Record<string, string> = { left: 'Left', right: 'Right', both: 'Both' }
export const ACCESSORY_FINGER_LABELS: Record<string, string> = {
  thumb: 'Thumb', index: 'Index finger', middle: 'Middle finger', ring: 'Ring finger', little: 'Little finger',
}
/** A234: how close the dialog's 3D view frames a small piece (metres round its preview points; 0: the whole body). */
export const ACCESSORY_FOCUS_M: Record<string, number> = {
  ring: 0.07, earrings: 0.14, bracelet: 0.14, anklet: 0.2, glasses: 0.16,
}
export const GLASSES_SHAPE_LABELS: Record<string, string> = {
  round: 'Round', rectangular: 'Rectangular', cat_eye: 'Cat-eye', aviator: 'Aviator',
}
export const GLASSES_SIZE_LABELS: Record<string, string> = { narrow: 'Narrow', regular: 'Regular', wide: 'Wide' }
export const GLASSES_FRAME_LABELS: Record<string, string> = { metal: 'Metal', acetate: 'Acetate' }
export const GLASSES_TEMPLE_LABELS: Record<string, string> = { straight: 'Straight', hook: 'Hooked behind the ear' }
export const LENS_TINT_LABELS: Record<string, string> = {
  clear: 'Clear lenses', grey: 'Grey', brown: 'Brown', green: 'Green', custom: 'Custom colour',
}

/** The glasses' metrics line: "Frame 144 mm · lenses 56×36 mm · bridge 22 mm · arms 140 mm" (`t` translates the
 *  words). Arms: the longer of the two. */
export function glassesLine(m: GlassesNumbers, t: (s: string) => string): string {
  const parts: string[] = []
  if (m.frame_mm !== undefined) parts.push(`${t('Frame')} ${Math.round(m.frame_mm)} mm`)
  if (m.lens_mm) parts.push(`${t('lenses')} ${Math.round(m.lens_mm[0])}×${Math.round(m.lens_mm[1])} mm`)
  if (m.bridge_mm !== undefined) parts.push(`${t('bridge')} ${Math.round(m.bridge_mm)} mm`)
  const arms = Object.values(m.arms_mm || {})
  if (arms.length) parts.push(`${t('arms')} ${Math.round(Math.max(...arms))} mm`)
  return parts.join(' · ')
}

/** Why an ear was not used for a temple, translated: its top's distance from the eye line against the accepted
 *  range, or "no ear found" when the side has none (`ear_above_mm` null). */
export function earReason(m: GlassesNumbers, t: (s: string) => string): string {
  const side = Object.keys(m.ear_above_mm || {})[0]
  const above = side ? m.ear_above_mm?.[side] : null
  if (above == null) return t('no ear found on that side')
  const [lo, hi] = m.ear_range_mm || [-5, 30]
  return t("the ear's top lies {mm} mm from the eye line, expected {lo} to {hi} mm")
    .replace('{mm}', String(Math.round(above))).replace('{lo}', String(lo)).replace('{hi}', String(hi))
}

export const ACCESSORY_METAL_LABELS: Record<string, string> = {
  gold: 'Gold', silver: 'Silver', rose_gold: 'Rose gold', black: 'Black metal', custom: 'Custom colour',
  leather: 'Leather cord', string: 'String', fabric: 'Fabric cord',
}

export const PENDANT_STATE_LABELS: Record<string, string> = {
  ready: 'Pendant built', running: 'Pendant building', missing: 'Pendant not built', refused: 'Pendant refused',
  failed: 'Pendant failed', no_image: 'No item image',
}

export const PENDANT_STATE_COLOR: Record<string, string> = {
  ready: '#3fb950', running: '#58a6ff', missing: '#d29922', refused: '#f85149', failed: '#f85149', no_image: '#8b949e',
}

/** A225: the dots of the placeholder box (`sizeMm` wide and tall, 4 mm deep) hung at `anchor`, its front toward the
 *  horizontal part of `outward` — what the dialog shows until the pendant is built. */
export function pendantBoxPoints(anchor: [number, number, number], outward: [number, number, number],
  sizeMm: number): Array<[number, number, number]> {
  const s = sizeMm / 1000
  const d = 0.004
  let fx = outward[0]
  let fz = outward[2]
  const len = Math.hypot(fx, fz) || 1
  fx /= len; fz /= len
  // right = up × front
  const rx = fz
  const rz = -fx
  const out: Array<[number, number, number]> = []
  const corner = (u: number, v: number, w: number): [number, number, number] =>
    [anchor[0] + rx * u + fx * w, anchor[1] - v, anchor[2] + rz * u + fz * w]
  const steps = 6
  for (const w of [0, d]) {
    for (let i = 0; i <= steps; i++) {
      const t = i / steps
      out.push(corner(-s / 2 + s * t, 0, w), corner(-s / 2 + s * t, s, w))
      out.push(corner(-s / 2, s * t, w), corner(s / 2, s * t, w))
    }
  }
  return out
}

export const ACCESSORY_STATE_LABELS: Record<string, string> = {
  current: 'Built', due: 'Due', blocked: 'Cannot build yet', failed: 'Build failed',
}

export const ACCESSORY_STATE_COLOR: Record<string, string> = {
  current: '#3fb950', due: '#d29922', blocked: '#8b949e', failed: '#f85149',
}

/** The named length a drop matches (`accessory_spec.DROP_PRESETS`, within 0.25 cm), '' when none. */
export function dropPresetOf(dropCm: number, presets: Record<string, number>): string {
  const hit = Object.entries(presets).find(([, cm]) => Math.abs(cm - dropCm) <= 0.25)
  return hit ? hit[0] : ''
}
