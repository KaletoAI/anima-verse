/**
 * FieldFigure — the Figure tab (template tab `figure_tab`, section `figure`,
 * humanoid only; plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md
 * Task 10, spec "The UI" + "Rules for the buttons", ruling 8; laid out to the
 * user's tab checklist in Task UI5, the way the Hairstyles tab is).
 *
 * One flow, one Build:
 * - the flow head: the status light with its words (`statusLight` / `headerLine`: "Up to date", "2 changes",
 *   "1 change · a step failed", "Building · 2 changes"), the ONE primary button Build (POST …/figure/build) with
 *   its cost on it — "Everything is current", disabled, when nothing is due —, its disabled reason written under
 *   it (a running Build is no disable, a click queues the next one); "Build automatically" (POST
 *   …/figure/auto-build, saved at once, runs nothing, what it means beside it) and "Pause automatic generation"
 *   (Ruling A42, GenerationPausePanel: while paused the light with its reason, what runs and finishes, "Resume —
 *   N hub jobs start" (POST …/figure/generation-pause {paused}) and the waiting jobs, each with Cancel behind an
 *   in-app confirmation (POST …/figure/waiting/cancel {id})); the pending changes with their cost, a failure;
 *   the plain body's change whose front was made from another reference (Ruling A86, `FrontChangeRow`) as its own
 *   row under them: its light, the reason in plain words, the front's Regenerate with its cost on the button — the
 *   front's image jobs plus what the new front makes due at the next Build (`frontRegenerate`, the Base body tab's
 *   count; POST …/base-body/images {view: "front", force: true}, the front tile's own action, 409 while a Build
 *   runs), "Open Base body tab", and that Build covers it in one go with the plan step's count (`frontBuildCovers`);
 * - left: the figure DELIVERED now (`served_url`, the interim rule applied — never a half step), "Built <time>"
 *   in its corner; the mouse turns the figure; no extension-bone note (Ruling A73 — the 3D tab keeps it); over it
 *   what that figure is against the outfit worn now (Ruling A75, `served_state`): its light and reason, one line
 *   per piece it lacks — a figure without a piece is never shown as if it were the outfit;
 * - right: sub-tabs instead of scrolling —
 *   - "Worn now": the worn hairstyle first (name · mode, ↗ Hairstyles — where hairstyles are worn, made and set,
 *     Task 14), then every worn piece (name · mode, ↗ Wardrobe — the mode lives on the item, ruling P4), each a
 *     step row: its light, the state ("Ready", "Due: own mesh · 3 hub jobs", "Waits for the Build", "Building",
 *     "Failed", "Refused on the body shape" — Ruling A31 wording, the measured reasons and what each button does
 *     on mouse-over; "Ready — Accepted by you" when the fit it uses was refused by its checks and accepted by the
 *     user), the reason in plain words and its single steps with their cost: Retry (the Build, which retries a
 *     cached chain failure, ruling 7a), Re-fit — no hub job (POST …/figure/refit {item_id}: that piece's CPU fit
 *     and the CPU assembly only, hub steps stay due for the Build — Ruling FR-I2; 409 while a Build runs),
 *     Regenerate mesh (POST …/garments/{item}/run {step: "mesh", force, chain}, only when the refusal points at
 *     the piece itself — Ruling A23), Details (an own-mesh piece's chain dialog, GarmentPieceDialog — a WORN
 *     piece's only entry, opened without its "Run all", Ruling 10a; "Details — use a refused image" when every
 *     attempt of an image view was refused, Ruling A79: the dialog's "Refused images" takes one by hand); a closable piece has Closed / Open
 *     (PieceStateToggle, saved at once — Task 11b) with what the switch starts and costs beside it, and an
 *     own-mesh closable piece the single action that builds its OTHER state's mesh ("Build the open mesh — 6
 *     hub jobs", POST …/garments/{item}/run {state}; the Build only ever makes the worn state's);
 *   - "Build plan": what the Build runs, one row per step with its light and cost;
 *   - "Body": the plain body (its views, model, face and rig live in the Base body tab — one line and "Open Base
 *     body tab"), the body shape and the texture as step rows, and the stored bodies and textures (FigureStored,
 *     Delete behind an in-app confirmation);
 *   - "Dressed views" (Ruling A70, from the dissolved Pose tab): one line that the Build renders them, the worn
 *     outfit's "Full-body reference" step (Ruling A74b + A87, OutfitReferenceRow → FullBodyReferenceTile: Generate
 *     with its cost, pick from the gallery, upload, clear — saving only saves; while something is painted the dressed
 *     front is then an edit of that picture, due with its cost),
 *     then one step
 *     row per dressed view (FieldModelRefs `layout="steps"`): light, state, reason, small thumbnails that enlarge,
 *     where the view comes from — painted on the body's view, or a copy of the body shape's / plain body's view
 *     (↗ Body / ↗ Base body) — and its own button with its true cost: "Regenerate this view — 1 image job" for an
 *     edit, "Copy this view again from the body shape — no job" for a copy (`viewAction`); the face view's note
 *     with the link to the Base body tab. Kept mounted while hidden: it polls the views and counts them;
 *   - "Outfit model" (Ruling A70): the current outfit's model as a step row with the proof's numbers and its own
 *     steps (FigureOutfitModel).
 *
 * Nothing here starts a chain except Build and Retry (both POST …/figure/build — a manual Build) and the single
 * steps of a piece. Every humanoid is on the figure pipeline (Ruling A13); one without a plain body yet keeps the
 * model it has and the button reads "Build base body (N hub jobs)" with NO_BASE_BODY_NOTE under it. Polls GET
 * …/figure while a Build runs (useFigure); the tab re-reads on the push topic `generation`.
 */
import { useCallback, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from './Model3DViewer'
import { GarmentPieceDialog, PieceStateToggle } from './WardrobeGarment'
import { FigureStored } from './FigureStored'
import { FieldModelRefs } from './FieldModelRefs'
import { FigureOutfitModel } from './FigureOutfitModel'
import { OutfitReferenceRow } from './OutfitReferenceRow'
import { fullBodyBuildNote } from './fullBodyReferenceModel'
import { VIEWS_BY_BUILD } from './dressedViewsModel'
import { GenerationPausePanel, GenerationPauseSwitch } from './GenerationPausePanel'
import { BuildProblemView } from './BuildProblem'
import { StepLight, StepRowView, SubTabs } from './StepRows'
import { LIGHT_COLOR, PANEL } from './stepStyle'
import { useFigure } from './useFigure'
import { imageRefusal } from './refusedAttemptsModel'
import {
  BUILD_DEFERRED_NOTE, BUILD_RUNNING_NOTE, BUILD_STATUS, ESTIMATE_NOTE, HAIR_MODE_LABELS, MESH_MODE_LABELS,
  FRONT_WAITS_FOR_BUILD, NO_BASE_BODY_NOTE, REFIT_LABEL, autoBuildNote, baseBodyLine, bodyRows, buildButton,
  changeLine, frontBuildCovers, frontRegenerate, hairState, headerLine, noBaseBody, planRows, regenerateMeshLabel,
  retryLabel, servedLines, shortCost, stateMeshAction, stateToggleNote, statusLight, wornState,
} from './figureModel'
import type { FigurePayload, FigureWornRow, GenerationPause, HairMode, PieceState, WaitingJob } from './figureModel'
import type { Light } from './hairstylesModel'

const ERROR_STYLE: CSSProperties = { color: LIGHT_COLOR.red, overflowWrap: 'anywhere' }

/** The answers of POST …/figure/refit (Ruling FR-I2) besides the Build's own. */
const REFIT_STATUS: Record<string, string> = { started: 'Re-fit started (CPU only)' }
const BUTTONS: CSSProperties = { display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }

const noop = () => undefined

export type FigureSub = 'worn' | 'plan' | 'body' | 'views' | 'model'
type Sub = FigureSub

/** The dressed views are the T-pose kind's (a literal kept stable for FieldModelRefs' poll). */
const TPOSE: ('tpose')[] = ['tpose']

export function FieldFigure({ character, onOpenWardrobe, onOpenHairstyles, onOpenBaseBody, onOpenGallery,
  initialSub = 'worn' }: {
  character: string
  /** The sub-tab it opens on (a link into the Dressed views or the Outfit model; the check renders each). */
  initialSub?: Sub
  /** Opens the Wardrobe tab, where the modes are edited. */
  onOpenWardrobe?: () => void
  /** Opens the Hairstyles tab (Task 14), where the hairstyles and their modes are edited. */
  onOpenHairstyles?: () => void
  /** Opens the Base body tab (the plain body's views, model, face and rig, and their settings). */
  onOpenBaseBody?: () => void
  /** Opens the Gallery tab, where the profile image is chosen (Dressed views' references row). */
  onOpenGallery?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const { data, error, startPoll } = useFigure(character)
  const [posting, setPosting] = useState(false)
  const [openPiece, setOpenPiece] = useState<{ id: string; name: string } | null>(null)
  const [sub, setSub] = useState<Sub>(initialSub)
  const [autoSaved, setAutoSaved] = useState(false)
  // The dressed views' lights, comma-joined (FieldModelRefs `onLights`): the sub-tab names how many there are.
  const [viewLights, setViewLights] = useState('')
  const onViewLights = useCallback((l: string) => setViewLights(l), [])
  const openBody = useCallback(() => setSub('body'), [])
  const enc = encodeURIComponent(character)

  const post = useCallback(async (path: string, body: unknown, ok?: (d: Record<string, unknown>) => void) => {
    if (posting) return
    setPosting(true)
    try {
      const d = await apiPost<Record<string, unknown>>(`/characters/${enc}/${path}`, body)
      ok?.(d)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      startPoll(300)
    }
  }, [enc, posting, startPoll, t, toast])

  const build = useCallback(() => post('figure/build', {}, (d) => {
    const status = String(d.status || '')
    toast(t(BUILD_STATUS[status] || status), 'success')
  }), [post, t, toast])

  const reload = useCallback(() => startPoll(0), [startPoll])

  /** Ruling A86: the front's Regenerate on the plain body's change — the front tile's own action (Base body tab). */
  const regenerateFront = useCallback(() => post('base-body/images', { view: 'front', force: true }, () => {
    toast(t('Started — the front renders; the Base body tab shows it'), 'success')
  }), [post, t, toast])
  /** Bumped by a saved outfit reference (Ruling A74b): the dressed views read again and show as due. */
  const [refVersion, setRefVersion] = useState(0)

  /** Ruling A42: pause (no jobs) / resume (the held jobs start — the button names how many) / cancel one. */
  const setPaused = useCallback((paused: boolean) => post('figure/generation-pause', { paused }, () => {
    toast(paused ? t('Automatic generation paused') : t('Resumed — the held jobs start'), 'success')
  }), [post, t, toast])
  const cancelWaiting = useCallback((job: WaitingJob) => post('figure/waiting/cancel', { id: job.id }, () => {
    toast(t('Cancelled — it will not run'), 'success')
  }), [post, t, toast])

  /** Ruling A23 b: a piece whose fit on the body shape was refused — fit it again (CPU), or make its mesh anew.
   *  Re-fit (Ruling FR-I2) runs that piece's CPU fit and the CPU assembly only; while a Build runs it answers 409. */
  const refit = useCallback((row: FigureWornRow) => post('figure/refit', { item_id: row.item_id }, (d) => {
    const status = String(d.status || '')
    toast(t(REFIT_STATUS[status] || BUILD_STATUS[status] || status), 'success')
  }), [post, t, toast])
  const regenerateMesh = useCallback((row: FigureWornRow) => post(
    `garments/${encodeURIComponent(row.item_id)}/run`, { step: 'mesh', force: true, chain: true }, (d) => {
      toast(d.started ? t('Started') : t('Queued'), 'success')
    }), [post, t, toast])

  /** The other state's own mesh of a worn closable piece: its chain alone (queued behind the character's
   *  garment runs), never the Build. */
  const buildStateMesh = useCallback((row: FigureWornRow, state: PieceState) => post(
    `garments/${encodeURIComponent(row.item_id)}/run`, { state }, (d) => {
      toast(d.started ? t('Started') : t('Queued'), 'success')
    }), [post, t, toast])

  const setAutoBuild = useCallback((enabled: boolean) => post('figure/auto-build', { enabled }, () => {
    setAutoSaved(true)
  }), [post])

  if (!data) {
    return error ? <div className="ga-hint" style={ERROR_STYLE}>{error}</div>
      : <div className="ga-hint">{t('Loading…')}</div>
  }
  // Every humanoid is on the pipeline (Ruling A13) except a temporary NPC (A13a): its model comes from the T-pose.
  if (!data.humanoid) return <div className="ga-hint">{t('The figure is for humanoid characters only.')}</div>
  if (!data.pipeline) {
    return <div className="ga-hint">{t('A temporary NPC has no figure — its 3D model is made from its T-pose picture.')}</div>
  }

  const wornCount = data.worn.length + (data.hair ? 1 : 0)
  const tabs = [
    { id: 'worn' as const, label: `${t('Worn now')} (${wornCount})` },
    { id: 'plan' as const, label: `${t('Build plan')} (${data.cost.steps.length})`,
      title: t('What the Build runs') },
    { id: 'body' as const, label: t('Body') },
    { id: 'views' as const, label: viewLights ? `${t('Dressed views')} (${viewLights.split(',').length})`
      : t('Dressed views'),
    // Ruling A90: the line that the Build renders them is the sub-tab's mouse-over.
    title: `${t('The outfit’s views of the figure: the input of its texture and model')}\n${t(VIEWS_BY_BUILD)}` },
    { id: 'model' as const, label: t('Outfit model'), title: t('The current outfit’s model and its steps') },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, fontSize: 13 }}>
      {/* Ruling A90: ONE line above the viewer; everything else is a notice line in the right-hand panel. */}
      <FigureHeader data={data} posting={posting} autoSaved={autoSaved} onBuild={build}
        onAutoBuild={(enabled) => { void setAutoBuild(enabled) }}
        onPause={() => { void setPaused(true) }} />
      <div className="ga-split ga-split-views ga-split-figure">
        <div className="ga-split-col">
          {/* The figure gets the wider column and no tilt toolbar (user 2026-11-13): the canvas fills the column. */}
          {data.served_url ? (
            <Model3DViewer key={data.served_url} url={data.served_url} format="glb" height={600} subject="figure"
              builtAt={data.served_built_at} footPose={data.served_foot_pose ?? null}
              clipGroup={data.served_foot_pose ? 'ground' : undefined} />
          ) : (
            <div className="ga-hint" style={{ height: 200, display: 'flex', alignItems: 'center',
              justifyContent: 'center', border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
              {t('No figure yet — Build makes it')}
            </div>
          )}
        </div>
        <div className="ga-split-col" style={PANEL}>
          <FigureNotices data={data} posting={posting} onBuild={build} onRegenerateFront={() => { void regenerateFront() }}
            onOpenBaseBody={onOpenBaseBody}>
            {data.generation_pause ? (
              <GenerationPausePanel gp={data.generation_pause} busy={posting} onResume={() => { void setPaused(false) }}
                onCancel={(job) => { void cancelWaiting(job) }} />
            ) : null}
            <ServedStateNote state={data.served_state} />
          </FigureNotices>
          <SubTabs tabs={tabs} value={sub} onChange={setSub} />
          {sub === 'worn' ? (
            <WornRows data={data} character={character} busy={posting} onRetry={build} onOpenWardrobe={onOpenWardrobe}
              onOpenHairstyles={onOpenHairstyles}
              onOpenPiece={(id, name) => setOpenPiece({ id, name })} onStateMesh={buildStateMesh} onChanged={reload}
              onRefit={refit} onRegenerateMesh={regenerateMesh} />
          ) : sub === 'plan' ? (
            <PlanRows data={data} />
          ) : sub === 'body' ? (
            <BodySection data={data} character={character} onChanged={reload} onOpenBaseBody={onOpenBaseBody} />
          ) : sub === 'model' ? (
            <FigureOutfitModel character={character}
              refresh={`${data.build.running ? 'running' : 'idle'}:${data.served_built_at || ''}`} />
          ) : null}
          {/* Kept mounted while hidden: it polls the views and counts them for the sub-tab's label. */}
          <div style={sub === 'views' ? { display: 'flex', flexDirection: 'column', gap: 6 } : { display: 'none' }}>
            {/* Ruling A90: row 1 the references (source → the worn outfit's full-body reference, Ruling A74b/A87 — its
                dressed front is an edit of that picture), row 2 the dressed views in one row. */}
            <OutfitReferenceRow character={character} onChanged={() => { setRefVersion((n) => n + 1); reload() }}
              onOpenBaseBody={onOpenBaseBody} onOpenGallery={onOpenGallery}
              refreshKey={`${data.build.running ? 'running' : 'idle'}:${data.served_built_at || ''}:${data.outfit || ''}:${(data.worn || []).map((w) => w.item_id).join(',')}`} />
            <FieldModelRefs character={character} kinds={TPOSE} layout="steps" onOpenBaseBody={onOpenBaseBody}
              onOpenBody={openBody} onLights={onViewLights}
              refreshKey={`${data.build.running ? 'running' : 'idle'}:${data.served_built_at || ''}:${refVersion}`} />
          </div>
        </div>
      </div>
      {openPiece ? (
        <GarmentPieceDialog character={character} itemId={openPiece.id} name={openPiece.name} noRunAll
          onStatus={noop} onClose={() => { setOpenPiece(null); reload() }} />
      ) : null}
    </div>
  )
}

/** Ruling A75: what the shown figure is against the outfit worn now — its light and reason, one line per piece it
 *  lacks (the measured refusal on mouse-over). A figure without a piece is never shown as if it were the outfit.
 *  Ruling A90: notice lines in the right-hand panel, each in one line with the whole on mouse-over; a figure that
 *  shows the outfit worn now (green) is no notice. */
function ServedStateNote({ state }: { state: FigurePayload['served_state'] }) {
  const { t } = useI18n()
  if (!state || state.light === 'green' || !servedLines(state, t).length) return null
  return (
    <>
      {servedLines(state, t).map((line, i) => (
        <div key={i} className={`ga-notice${line.head ? '' : ' is-sub'}`} title={[line.text, line.title].filter(Boolean).join('\n')}>
          {line.light ? <StepLight light={line.light} /> : null}
          <span className={`ga-one-line ga-notice-text${line.head ? '' : ' ga-hint'}`}
            style={line.head ? { color: LIGHT_COLOR[state.light], fontWeight: 600 } : undefined}>{line.text}</span>
        </div>
      ))}
    </>
  )
}

/** Before the first poll with the field (an older server): not paused, nothing waits. */
const NOT_PAUSED: GenerationPause = { paused: false, since: null, waiting: [], running: [], resume_jobs: 0,
  resume_unknown: 0 }

/** The Figure tab's one line above the viewer (Ruling A90): the light, "N changes" (the due list on its mouse-over
 *  and behind its ▸ toggle), Build with its cost, "Build automatically" and "Pause automatic generation" — what each
 *  does on mouse-over. Everything else is a notice line in the right-hand panel (`FigureNotices`). */
function FigureHeader({ data, posting, autoSaved, onBuild, onAutoBuild, onPause }: {
  data: FigurePayload
  posting: boolean
  /** "Build automatically" was saved in this visit: its note says so. */
  autoSaved: boolean
  onBuild: () => void
  onAutoBuild: (enabled: boolean) => void
  /** Ruling A42: "Pause automatic generation" (no jobs). */
  onPause: () => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const button = buildButton(data, t)
  const light = statusLight(data.status)
  // Ruling A86: the plain body's front made from another reference is its own notice with its action, not a part of
  // the due list.
  const frontChange = data.changes.find((c) => c.key === 'body' && c.front)
  const listed = data.changes.filter((c) => c !== frontChange)
  const due = listed.map((c) => changeLine(c, t))
  const served = data.served_state && data.served_state.light === 'green' ? t(data.served_state.state) : ''
  const head = headerLine(data.status, data.changes.length, t)
  const autoNote = autoSaved ? autoBuildNote(data.auto_build, t)
    : data.auto_build ? t('Changes start the Build by themselves') : t('Changes wait for Build')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div className="ga-figure-head">
        <StepLight light={light} title={served || undefined} />
        {due.length ? (
          <button type="button" className="ga-due-toggle" style={{ color: LIGHT_COLOR[light] }} aria-expanded={open}
            title={`${t('Due')}:\n${due.join('\n')}`} onClick={() => setOpen((v) => !v)}>
            {head} {open ? '▾' : '▸'}
          </button>
        ) : <strong style={{ color: LIGHT_COLOR[light] }} title={served || undefined}>{head}</strong>}
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={posting || !!button.disabled}
          title={[t('Runs every step that is missing or out of date, in order, and skips what is current'),
            data.cost.hub_jobs ? t(ESTIMATE_NOTE) : ''].filter(Boolean).join(' — ')} onClick={onBuild}>
          {button.label}
        </button>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
          title={`${autoNote}\n${t('Outfit changes, a new body or a piece that became ready start the Build by themselves; such a Build never makes or refreshes the base body — only a Build you start does. Off: they only collect as changes until you click Build. Never stops a running Build.')}`}>
          <input type="checkbox" checked={data.auto_build} disabled={posting}
            onChange={(e) => onAutoBuild(e.target.checked)} />
          <span>{t('Build automatically')}</span>
          {autoSaved ? <span className="ga-hint" style={{ color: LIGHT_COLOR.yellow }}>{t('Saved')}</span> : null}
        </label>
        <GenerationPauseSwitch gp={data.generation_pause ?? NOT_PAUSED} busy={posting} onPause={onPause} />
      </div>
      {open && due.length ? (
        <div className="ga-hint" style={{ color: LIGHT_COLOR.yellow, display: 'flex', flexDirection: 'column' }}>
          {due.map((line, i) => <span key={i} className="ga-one-line" title={line}>{t('Due')}: {line}</span>)}
        </div>
      ) : null}
    </div>
  )
}

/** Ruling A90: the Figure tab's notices at the top of its right-hand panel, one line each — light, the reason in a few
 *  words (the whole on mouse-over), the button with its cost — never a box above the viewer: why Build waits, the
 *  running Build's step, a deferred or paused automatic Build, a failed step with its fix (Ruling A61), the other
 *  failed steps, the plain body's outdated front with its Regenerate (Ruling A86), the full-body reference
 *  information (Ruling A87), and the caller's (the generation pause, the served figure's lacks). Nothing to say → no
 *  list. */
function FigureNotices({ data, posting, onBuild, onRegenerateFront, onOpenBaseBody, children }: {
  data: FigurePayload
  posting: boolean
  onBuild: () => void
  /** Ruling A86: the front's Regenerate (POST …/base-body/images {view: "front", force: true}). */
  onRegenerateFront: () => void
  onOpenBaseBody?: () => void
  children?: ReactNode
}) {
  const { t } = useI18n()
  const button = buildButton(data, t)
  const running = data.build.running
  const step = data.build.step
  // A worn piece's failure is written in its own row; the notices name only the others (an assembly, a texture).
  const wornIds = new Set(data.worn.map((r) => r.item_id))
  const failed = Object.entries(data.build.failed || {}).filter(([, f]) => !f.item_id || !wornIds.has(f.item_id))
  // The step the problem line says in full is not repeated.
  const others = failed.filter(([name]) => name !== data.problem?.step)
  const frontChange = data.changes.find((c) => c.key === 'body' && c.front)
  const fullBody = data.full_body_reference && (!data.full_body_reference.base || !data.full_body_reference.outfit)
    ? [fullBodyBuildNote('base', data.full_body_reference.base, undefined, t),
      fullBodyBuildNote('outfit', data.full_body_reference.outfit, undefined, t)].filter(Boolean).join(' · ') : ''
  const runningText = running
    ? (step ? `${t('Running')}: ${step.index && step.count ? `${step.index}/${step.count} ` : ''}${step.label}` : t('Running')) : ''
  const lines: ReactNode[] = []
  const line = (key: string, light: Light | null, text: string, title?: string, actions?: ReactNode) => lines.push(
    <div key={key} className="ga-notice" title={title || text}>
      {light ? <StepLight light={light} /> : null}
      <span className="ga-one-line ga-notice-text ga-hint"
        style={light === 'red' || light === 'yellow' || light === 'blue' ? { color: LIGHT_COLOR[light] } : undefined}>{text}</span>
      {actions}
    </div>,
  )
  if (!running && data.problem) {
    lines.push(<BuildProblemView key="problem" problem={data.problem} busy={posting} onRun={onBuild} compact />)
  }
  if (!running) others.forEach(([name, f]) => line(`failed-${name}`, 'red', `${name}: ${f.error}`))
  if (frontChange) {
    const jobs = data.body?.plain.jobs
    const action = frontRegenerate(frontChange.front, jobs, t)
    const covers = frontBuildCovers(frontChange.jobs, t)
    line('front', 'yellow', `${t(frontChange.name)} · ${t('Outdated')}: ${t(frontChange.delivered)}`,
      [`${t(frontChange.name)} · ${t('Outdated')}: ${t(frontChange.delivered)}`, action.note, covers].filter(Boolean).join('\n'), (
        <>
          <button type="button" className="ga-btn ga-btn-sm" disabled={posting || running} onClick={onRegenerateFront}
            aria-label={action.label}
            title={[action.label, action.note, running ? t(FRONT_WAITS_FOR_BUILD) : '',
              t('Renders the plain body’s front again — the same as the front view’s Regenerate in the Base body tab')]
              .filter(Boolean).join('\n')}>
            ↻ {t('Front view')}{jobs ? ` · ${shortCost(jobs.front, jobs.model_followup ? jobs.after_front : undefined, t)}` : ''}
          </button>
          {onOpenBaseBody ? (
            <button type="button" className="ga-btn ga-btn-sm" title={t('Open Base body tab')}
              onClick={onOpenBaseBody}>↗ {t('Base body')}</button>
          ) : null}
        </>
      ))
  }
  if (runningText) line('running', 'blue', runningText, `${runningText} — ${t(BUILD_RUNNING_NOTE)}`)
  if (button.disabled && button.disabled !== button.label) line('disabled', 'grey', button.disabled)
  if (noBaseBody(data) && !running) line('nobase', 'grey', t(NO_BASE_BODY_NOTE))
  if (!running && data.build.deferred) line('deferred', 'grey', t(BUILD_DEFERRED_NOTE))
  if (!running && data.build.paused) {
    line('paused', 'grey', t('Paused before {step} — Resume builds the rest').replace('{step}', data.build.paused.label))
  }
  // Ruling A87: no full-body reference is information, never a due step — the Build never generates one.
  if (fullBody) {
    line('fullbody', 'grey', fullBody,
      `${fullBody}\n${t('Optional — the Build never generates it: Base body → Views, and Dressed views here.')}`)
  }
  // The caller's lines (the pause, the served figure's lacks) render nothing when they have nothing to say.
  const extra = !!data.generation_pause?.paused || (!!data.served_state && data.served_state.light !== 'green'
    && servedLines(data.served_state, (k) => k).length > 0)
  if (!lines.length && !extra) return null
  return (
    <div className="ga-notices" aria-label={t('Notices')}>
      {lines}
      {children}
    </div>
  )
}

function WornRows({ data, character, busy, onRetry, onOpenWardrobe, onOpenHairstyles, onOpenPiece, onStateMesh,
  onChanged, onRefit, onRegenerateMesh }: {
  data: FigurePayload
  character: string
  busy: boolean
  onRetry: () => void
  onOpenWardrobe?: () => void
  onOpenHairstyles?: () => void
  onOpenPiece: (itemId: string, name: string) => void
  /** Build the other open / closed state's own mesh of a piece. */
  onStateMesh: (row: FigureWornRow, state: PieceState) => void
  /** A piece was toggled open / closed: reload. */
  onChanged: () => void
  /** Ruling A23 b: the single steps of a piece whose fit on the body shape was refused. */
  onRefit: (row: FigureWornRow) => void
  onRegenerateMesh: (row: FigureWornRow) => void
}) {
  const { t } = useI18n()
  const wardrobe = onOpenWardrobe ? (
    <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenWardrobe}
      title={t('The mode is set in the Wardrobe')}>↗ {t('Wardrobe')}</button>
  ) : null
  const hairstyles = onOpenHairstyles ? (
    <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenHairstyles}
      title={t('Hairstyles are worn, made and set in the Hairstyles tab')}>↗ {t('Hairstyles')}</button>
  ) : null
  const retry = (
    <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onRetry}
      title={t('Runs the Build: the failed step again, then what depends on it')}>
      {retryLabel(data.cost.hub_jobs, t)}
    </button>
  )
  const hair = data.hair
  const hairCell = hair ? hairState(hair, t) : null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span className="ga-hint">
        {data.outfit ? t('Worn now (outfit “{name}”)').replace('{name}', data.outfit) : t('Worn now')}
      </span>
      {hair && hairCell ? (
        <StepRowView row={{ name: hair.name || t('Hair'), light: hairCell.light, state: hairCell.text,
          reason: hairCell.sub || '' }}
          aside={<span className="ga-hint">· {t(HAIR_MODE_LABELS[hair.mode as HairMode] || hair.mode)}</span>}>
          <div style={BUTTONS}>
            {hairstyles}
            {hair.state === 'failed' ? retry : null}
          </div>
        </StepRowView>
      ) : null}
      {data.worn.map((row) => {
        const cell = wornState(row, t)
        const note = row.note && !row.interim && !row.in_body_until && row.state !== 'left_out'
          && row.state !== 'failed' && row.state !== 'fit_refused' ? t(row.note) : ''
        const other: PieceState | null = row.piece_state ? (row.piece_state === 'open' ? 'closed' : 'open') : null
        return (
          <StepRowView key={row.item_id}
            row={{ name: row.name, light: cell.light, state: cell.text, detail: cell.detail,
              reason: [cell.sub, note].filter(Boolean).join(' · ') }}
            aside={<span className="ga-hint">· {t(MESH_MODE_LABELS[row.mode] || row.mode)}</span>}>
            <div style={BUTTONS}>
              {wardrobe}
              {row.mode === 'own_mesh' ? (
                <button type="button" className="ga-btn ga-btn-sm" aria-haspopup="dialog"
                  title={row.state === 'fit_refused'
                    ? t('Details shows the refused fit on each body, marked where it fails, and can accept it.')
                    : row.state === 'failed' && imageRefusal(row.failure)
                      ? t('Details shows each refused image with its reasons; “Use this attempt” takes one by hand (no hub job, Undo puts it back).')
                      : t('The piece’s mesh steps, each redone on its own, with their cost')}
                  onClick={() => onOpenPiece(row.item_id, row.name)}>
                  {row.state === 'failed' && imageRefusal(row.failure) ? t('Details — use a refused image')
                    : t('Details')}
                </button>
              ) : null}
              {row.state === 'failed' ? retry : null}
              {row.state === 'fit_refused' ? (
                <>
                  <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => onRefit(row)}
                    title={t('Fits this piece on the body shape again and assembles the figure — CPU only, no hub job; steps that need hub jobs stay due for the next Build')}>
                    {t(REFIT_LABEL)}
                  </button>
                  {row.piece_broken ? (
                    <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                      onClick={() => onRegenerateMesh(row)}
                      title={t('Makes the piece’s mesh anew, then fits it')}>
                      {regenerateMeshLabel(row.regenerate_jobs, t)}
                    </button>
                  ) : null}
                </>
              ) : null}
            </div>
            {row.piece_state ? (
              <div style={BUTTONS}>
                {/* Its own "then Build runs automatically" stays off: the note beside it names the cost too. */}
                <PieceStateToggle character={character} itemId={row.item_id} state={row.piece_state}
                  autoBuild={false} disabled={busy} onChanged={onChanged} />
                <span className="ga-hint">{stateToggleNote(row, data.auto_build, t)}</span>
              </div>
            ) : null}
            {row.mode === 'own_mesh' && other ? (
              row.other_state_jobs === 0 ? (
                <div className="ga-hint">{stateMeshAction(other, 0, t)}</div>
              ) : (
                <div>
                  <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                    title={t('Only this piece’s chain; the Build makes only the worn state’s mesh')}
                    onClick={() => onStateMesh(row, other)}>
                    {stateMeshAction(other, row.other_state_jobs, t)}
                  </button>
                </div>
              )
            ) : null}
          </StepRowView>
        )
      })}
      {!data.worn.length && !hair ? <div className="ga-hint">{t('Nothing worn')}</div> : null}
    </div>
  )
}

function PlanRows({ data }: { data: FigurePayload }) {
  const { t } = useI18n()
  const rows = planRows(data, t)
  if (!rows.length) return <div className="ga-hint">{t('Nothing to build — every step is current.')}</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span className="ga-hint">
        {t('The Build runs these in order and skips what is current; Build above starts them.')}
      </span>
      {rows.map((r) => <StepRowView key={r.key} row={r} />)}
    </div>
  )
}

function BodySection({ data, character, onChanged, onOpenBaseBody }: {
  data: FigurePayload
  character: string
  onChanged: () => void
  onOpenBaseBody?: () => void
}) {
  const { t } = useI18n()
  if (!data.body) return <div className="ga-hint">{t('No body yet — Build makes it')}</div>
  const names = (state: string) => data.worn.filter((r) => r.mode === state && r.state !== 'left_out').map((r) => r.name)
  const shapeNames = [...(data.hair?.mode === 'body' ? [t('hair')] : []), ...names('in_body')]
  const plainNote = data.changes.find((c) => c.key === 'body')?.note
  const rows = bodyRows(data.body, shapeNames, names('painted'), t, data.build.running ? data.build.step?.name ?? null : null)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {rows.map((r) => (
        <StepRowView key={r.key} row={{ ...r, reason: r.key === 'plain' && plainNote ? `${r.reason} · ${t(plainNote)}` : r.reason }}>
          {r.key === 'plain' && onOpenBaseBody ? (
            <div style={BUTTONS}>
              <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}
                title={baseBodyLine(data.body?.plain.state || 'ready', t)}>{t('Open Base body tab')}</button>
            </div>
          ) : null}
        </StepRowView>
      ))}
      <span className="ga-fieldset-title" style={{ margin: '6px 0 0' }}>{t('Stored bodies and textures')}</span>
      <FigureStored character={character} onDeleted={onChanged} />
    </div>
  )
}
