/**
 * FieldBaseBody — the Base body tab (template tab `base_body_tab`, section `base_body`; Task UI1 of
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md). The plain (base) body every figure of the character
 * is built on: its four views, the skin detail step, the base model with its face and rig steps, and their
 * settings — what sat collapsed under the Figure tab's "Body:" line until Task UI1 (the Figure tab keeps the
 * figure and one line on the base body with "Open Base body tab").
 *
 * The rule of the character area (R1–R4):
 * - R1 "Run all" (POST …/base-body/run-all, `figure_build.start_base_run_all`): runs, in order, what is NOT
 *   current — the plain body's refresh as the Build plans it (`base_refresh_plan(missing=True)`: the stale or
 *   missing views, the skin step with the front, the model), else the face cleanup the stored base mesh misses,
 *   else its missing face retexture. Its label carries the job count ("Run all (7 hub jobs)"); nothing due →
 *   "Everything is current", disabled. The plan comes with the poll (`plain_body.run_all`).
 * - R2 single steps, each redoing its step even when it is current: a view's Regenerate, "Run skin step", the
 *   model's Regenerate, "Face retexture…", "Re-rig base body…" (ModelFaceActions) — each with its cost under it;
 *   a step whose input is missing is disabled with the reason under it.
 * - R3 settings saved on their own (Settings section): the face switches and the face retexture values
 *   (FaceSettings); the skin detail step is a world switch (Game-Admin → Setup) and is shown, not edited, here.
 *   Saving face values that differ from the ones the stored face retexture ran with makes the face step due (Task
 *   UI2: the record's settings fingerprint) — "Face values changed — not applied yet (N hub jobs)" under the values,
 *   and Run all redoes it; a saved tip setting (ExtensionTipPanel: Save, then Rebuild) makes the extension rebuild
 *   due the same way (local, no hub job).
 * - R4 only the current flow: no T-pose path, no outfit-body wording.
 *
 * Layout (Task UI5, the user's tab checklist): the flow head across the top — the light with its words (`baseHead`:
 * "Up to date", "N steps due", "A step failed", "Building now" — only for base-body work: an outfit model or garment
 * built meanwhile is one neutral line under it, `plain_body.activity.other`, Ruling A55), Run all with its count, the
 * link to the Figure tab and Run all's plan in one line (`runAllPlanLine`, what it does on mouse-over). Then two
 * columns: the base model's 3D preview ("Built <time>" in its corner, Full / Distance under it) on the left; on the
 * right one panel with sub-tabs instead of scrolling —
 * - Views (4): the four views two by two, small (a click enlarges one), each with its light and state in the label
 *   (`baseViewRow`), its Regenerate with the cost under it, the skin detail step under the front;
 * - Base model: its step row (`baseModelRow`) with "Regenerate the plain body's mesh — N hub jobs", the model's steps
 *   one line each, the base mesh repair (MeshRepairPanel, Ruling A34: status light, its settings saved on their own,
 *   "Repair again" — local), the tip smoothing (TipSmoothingPanel, Ruling A43) and the face/rig actions
 *   (ModelFaceActions) with their cost;
 * - Extension bones: one box per pair tip extension group (ExtensionTipPanel, Ruling A53: its light with the reason
 *   and "Built <time>", Enabled, position sliders, markers, mirror, colour disc, length and diameter factors, Save /
 *   Discard changes / Reset to default and its "Rebuild (local, no hub job)") and the base model's "Extension bones"
 *   box (ExtensionBonesBox, Ruling A45) for the groups WITHOUT a tip panel (`box_groups`), side by side in two equal
 *   columns — the box beside the first tip panel; without such groups there is no box, and a lone tip panel spans
 *   both columns;
 * - Collision capsules: the region sliders (live preview while dragging — the outfit models inherit the base body's
 *   set);
 * - Settings (rule R3).
 * The sliders that change the 3D model sit in the panel beside the viewer and act on it live.
 *
 * The viewer shows the extension bones (Ruling A45): it plays the base model's motion (`plain_body.extension.motion`,
 * no clothing — the base is bare) with the Bounce / Weight drafts of the box live, so dragging the figure tilts it
 * and the bones hang under gravity (Ruling A41); its toggles (Secondary motion, Extension bones, Collision capsules,
 * Extension collision) switch the overlays; the Extension bones grid starts off, like each tip panel's "Show markers"
 * (Ruling A62 — view switches of the open tab, never saved). A Full / Distance switch appears once the distance mesh
 * exists. Beside it the state preview (Ruling A66, moved here from the 3D tab): "Preview state" picks None (at rest) or a
 * state whose bone pose moves one of the base model's groups (`plain_body.extension.states`); the viewer then plays
 * that state's motion on the bare base (GET …/base-body/state-motion?state=…, a read — nothing is saved, nothing
 * runs), with the box's slider drafts on top. It moves the extension parts themselves, so it works with the
 * Extension bones grid off. Without groups (or without a state that moves them) a line says so instead. The
 * box's switches are saved for the base model (POST …/model3d/options {signature, extension_rig}) and make the
 * extension rebuild due — Run all or its Rebuild (POST …/model3d/extension-tip/apply, local) builds them; its
 * motion values are saved character-wide (POST …/model3d/extension-motion) and act at once.
 *
 * A new base model (Run all, Regenerate, a face or rig action) starts the automatic Build when "Build
 * automatically" is on (`garments.after_base_model` → body change), so those say "then Build runs
 * automatically". "Run skin step" changes the front's bytes: the base model is stale then, and Run all or the
 * next Build you start rebuilds it — written under the button with its cost. A temporary NPC (Ruling A13a) and
 * an animal have no base body: the tab says why.
 *
 * Backend (app/routes/characters.py, app/routes/figure.py, app/core/base_body.py):
 * GET /characters/{n}/figure?plain=1 (`plain_body`: views, model, face fields, collision, face cleanup,
 * run_all; the rest of the answer is the figure — `body.plain.jobs`, `auto_build`; polled while something runs —
 * useBaseBody), POST …/base-body/run-all, POST …/base-body/images {view, force} (409 without a profile picture
 * or, for a side view, the front), POST …/base-body/model {force} (409 while another 3D run of the character is
 * going), POST …/base-body/skin-step (the front's skin detail edit on the stored neutral front; GET
 * …/images/front?variant=neutral serves it), GET …/model3d (useModel3DStatus), POST …/model3d/options (the
 * settings).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { ViewRenderTile } from './ViewRenderTile'
import { RefImage } from './RefImage'
import { CollisionScales } from './CollisionScales'
import { ExtensionTipPanel } from './ExtensionTipPanel'
import { MeshRepairPanel } from './MeshRepairPanel'
import { TipSmoothingPanel } from './TipSmoothingPanel'
import { StatePreviewRow } from './StatePreviewRow'
import { ExtensionBonesBox } from './ExtensionBonesBox'
import { previewMotionSliders } from './motionFieldPreview'
import type { Physics } from '../../lib/motionDraft'
import { ModelFaceActions } from './ModelFaceActions'
import { FaceSettings } from './FaceSettings'
import { useModel3DStatus } from './useModel3DStatus'
import type { CollisionPayload, SecondaryMotionPayload } from '@anima/scene-render'
import { BASE_VIEWS, modelRunning, tipsRunning, useBaseBody, viewsRunning } from './useBaseBody'
import type { BaseActivity, BaseBodyInfo, BaseView, ExtensionTipPanelInfo } from './useBaseBody'
import { AUTO_BUILD_NOTE, BUILD_RUNNING_NOTE, ESTIMATE_NOTE, modelFollowup, singleAction, staleBaseNote } from './figureModel'
import type { ModelFollowup } from './figureModel'
import { EXT_DUE_GROUPS_NOTE, RUN_ALL_STATUS, TIP_DUE_NOTE, TIP_REBUILD_LABEL, baseHead, baseModelRow, baseViewRow, faceDueLine,
  runAllButton, runAllPlanLine, runAllWhat, stateMotionUrl, statePicker, viewerStateMotion } from './baseBodyModel'
import type { BaseLight, BaseRunAll, PickedStateMotion, TipDots } from './baseBodyModel'
import { BuildProblemView } from './BuildProblem'
import { StepLight, StepRowView, SubTabs } from './StepRows'
import { LIGHT_COLOR, PANEL } from './stepStyle'

const TILE_HEIGHT = 128

/** The right-hand panel's sub-tabs (Task UI5). */
type BaseTab = 'views' | 'model' | 'extensions' | 'collision' | 'settings'

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }

/** What the single actions cost (GET …/figure `body.plain.jobs`). */
export interface PlainBodyJobs {
  view: number | null
  front: number | null
  model: number | null
  after_front: number | null
  /** Ruling UI3c: what a step that changes a base view in place makes stale (the stored base model's hub stages);
   *  null = no base model stored. */
  model_followup?: ModelFollowup | null
}

/** The cost line under a single action and, when its result starts the automatic Build, that note. */
function ActionLine({ text, auto }: { text: string; auto?: boolean }) {
  const { t } = useI18n()
  return (
    <div className="ga-hint" style={{ overflowWrap: 'anywhere' }}>
      {text}{auto ? ` — ${t(AUTO_BUILD_NOTE)}` : ''}
    </div>
  )
}

/** Under the front tile: the neutral render the skin detail step started
 *  from (small, click enlarges), one line on what the step did, and the
 *  button that runs it again on the stored neutral front (base_skin) — its
 *  follow-up cost ON it before the click (Ruling UI3c: the step edits the front in place, the other views stay
 *  current, the stored base model goes stale — "+3 hub jobs for the model (mesh, face, rig)") and what it makes
 *  stale under it. */
function SkinStepLine({ info, busy, followup, onRun }: {
  info: BaseBodyInfo
  busy: boolean
  /** The stored base model's rebuild the step makes due (null = no base model stored, undefined = not known). */
  followup: ModelFollowup | null | undefined
  onRun: () => void
}) {
  const { t } = useI18n()
  const skin = info.skin
  if (!skin || !info.images?.front || info.status?.front?.running) return null
  const step = skin.step
  const label = !step ? t('Rendered without the skin detail step')
    : step.applied ? t('Skin detail added — the neutral render on the left')
    : step.outcome === 'off' ? t('Skin detail step off — the neutral render is the front')
    : step.outcome === 'busy' ? t('Skin detail not added (backend busy) — the neutral render is the front')
    : t('Skin detail not added — the neutral render is the front')
  return (
    <div style={{ marginTop: 4 }}>
      <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 6 }}>
        {skin.neutral_url ? (
          <div style={{ width: 52, flex: '0 0 auto' }}>
            <RefImage key={skin.neutral_url} src={skin.neutral_url} height={72} label={t('Neutral front')}
              meta={skin.neutral_meta} compact />
          </div>
        ) : null}
        <span className="ga-hint" style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}
          title={step?.error || undefined}>{label}</span>
        {skin.enabled ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onRun}
            title={t('Runs the skin detail edit again on the stored neutral front (one image job); the front is not re-rendered.')}>
            {t('Run skin step')}{followup ? ` (${modelFollowup(followup, t)})` : ''}
          </button>
        ) : null}
      </div>
      {skin.enabled && followup ? <ActionLine text={staleBaseNote(followup.jobs, t)} /> : null}
    </div>
  )
}

function ViewTile({ info, view, label, busy, jobs, onRender, onSkinStep }: {
  info: BaseBodyInfo
  view: BaseView
  label: string
  busy: boolean
  jobs: PlainBodyJobs | undefined
  onRender: (view: BaseView, force: boolean) => void
  onSkinStep: () => void
}) {
  const { t } = useI18n()
  const url = info.images?.[view] || null
  const st = info.status?.[view]
  // A side/back view edits the front: it cannot render before the front exists.
  const needsFront = view !== 'front' && !info.images?.front
  const cost = jobs ? singleAction('view', view === 'front' ? jobs.front : jobs.view, t) : undefined
  // Ruling UI3c: a new view makes the stored base model stale (a new front the other views too) — said before the
  // click.
  const followup = !jobs?.model_followup ? '' : view === 'front' ? staleBaseNote(jobs.after_front, t)
    : modelFollowup(jobs.model_followup, t)
  const row = baseViewRow({ running: !!st?.running, failed: !!st?.failed, error: st?.error, warning: st?.warning,
    stored: !!url, freshness: info.image_meta?.[view]?.freshness }, t)
  return (
    <ViewRenderTile label={`${label} · ${row.state}`} url={url} meta={info.image_meta?.[view]} height={TILE_HEIGHT}
      lead={<StepLight light={row.light} title={row.detail || row.state} />}
      running={!!st?.running} failed={!!st?.failed} error={st?.error} warning={st?.warning}
      disabled={busy || needsFront} disabledReason={needsFront ? t('Render the front view first') : undefined}
      actionTitle={cost && followup ? `${cost} · ${followup}` : cost}
      status={(
        <>
          {cost && !needsFront ? <ActionLine text={followup ? `${cost} · ${followup}` : cost} /> : null}
          {view === 'front' ? (
            <SkinStepLine info={info} busy={busy || viewsRunning(info)} followup={jobs?.model_followup}
              onRun={onSkinStep} />
          ) : null}
        </>
      )}
      onRender={() => onRender(view, !!url)} />
  )
}

/** The tab's head (Task UI5): the light with its words, "Run all" (rule R1) with its count, its plan in one line,
 *  why it is disabled, its last error; the link to the Figure tab. */
function RunAllHeader({ runAll, lights, busy, buildRunning, activity, onRun, onOpenFigure }: {
  runAll: BaseRunAll | null | undefined
  /** The step rows' lights (the views, the model). */
  lights: BaseLight[]
  busy: boolean
  /** A Build of the character runs: Run all waits for it (the server answers 409). */
  buildRunning: boolean
  /** `plain_body.activity` (Ruling A55): only base-body work turns the head blue; an outfit build is one neutral
   *  line. */
  activity: BaseActivity | null | undefined
  onRun: () => void
  onOpenFigure?: () => void
}) {
  const { t } = useI18n()
  const button = runAllButton(runAll, t)
  const disabled = busy || button.disabled || buildRunning
  const head = baseHead(runAll, lights, !!activity?.base, t)
  const what = runAll ? runAllWhat(runAll.kind, t, runAll.face_due) : ''
  const plan = runAllPlanLine(runAll, t)
  const lastError = runAll && !runAll.running && runAll.last?.error ? runAll.last.error : ''
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <StepLight light={head.light} />
        <strong style={{ color: LIGHT_COLOR[head.light] }}>{head.words}</strong>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={disabled}
          title={[what, runAll?.kind && runAll.hub_jobs ? t(ESTIMATE_NOTE) : '', runAll?.note || ''].filter(Boolean)
            .join('\n') || undefined} onClick={onRun}>
          {button.label}
        </button>
        {onOpenFigure ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenFigure}>↗ {t('Figure')}</button>
        ) : null}
      </div>
      {plan ? <div className="ga-hint" style={{ fontSize: 12 }} title={what}>{t('Run all runs')}: {plan}</div> : null}
      {/* A running Build disables Run all; the line says so only when Run all has something to run. */}
      {buildRunning && !button.disabled ? <div className="ga-hint" style={{ fontSize: 12 }}>{t('A Build runs for this character — Run all waits until it has ended.')}</div>
        : button.reason ? <div className="ga-hint" style={{ fontSize: 12 }}>{button.reason}</div> : null}
      {!activity?.base && activity?.other ? (
        <div className="ga-hint" role="status" style={{ fontSize: 12 }}>{t(activity.other)}</div>
      ) : null}
      {lastError ? <div className="ga-hint" style={{ ...ERROR_STYLE, fontSize: 12 }}>{t('Run all')}: {lastError}</div> : null}
    </div>
  )
}

/** The Settings section (rule R3): saved on their own, nothing runs. */
function BaseSettings({ character, info, st, pending, onReload }: {
  character: string
  /** The plan of Run all says whether the saved face values are applied (`run_all.face_due`). */
  info: BaseBodyInfo
  st: ReturnType<typeof useModel3DStatus>['st']
  pending: boolean
  onReload: () => Promise<unknown> | void
}) {
  const { t } = useI18n()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="ga-hint">{t('Saved on their own — nothing runs. A setting that makes a step due shows in Run all.')}</div>
      {st ? <FaceSettings character={character} st={st} pending={pending} onReload={onReload}
        dueLine={faceDueLine(info.run_all, t)} />
        : <div className="ga-hint">{t('Loading…')}</div>}
      {info.skin ? (
        <div className="ga-hint">
          {info.skin.enabled ? t('Skin detail step: on') : t('Skin detail step: off')}
          {' — '}{t('a world setting (Game-Admin → Setup); it applies to the next front render')}
        </div>
      ) : null}
    </div>
  )
}

export function FieldBaseBody({ character, onOpenFigure }: {
  character: string
  /** Switches to the Figure tab (the figure and its Build). */
  onOpenFigure?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, figure, startPoll } = useBaseBody(character)
  // The single actions' costs and "Build automatically" come with the same answer (the figure's part).
  const jobs: PlainBodyJobs | undefined = figure?.body?.plain.jobs
  const autoBuild = !!figure?.auto_build
  // Options, backends and run results of the model actions (face, rig).
  const { st, load: loadStatus, startPoll: pollStatus } = useModel3DStatus(character)
  // The user's own click, until the request answered (the poll then shows
  // the server's running state).
  const [posting, setPosting] = useState(false)
  /** Slider preview of the collision scales — shown instead of the stored set. */
  const [collisionPreview, setCollisionPreview] = useState<CollisionPayload | null>(null)
  /** Tip dots per pair tip group (ExtensionTipPanel), drawn on the model. */
  const [tipDots, setTipDots] = useState<Record<string, TipDots>>({})
  const onTipPreview = useCallback((group: string, dots: TipDots | null) => {
    setTipDots((previous) => {
      if (!dots && !(group in previous)) return previous
      const next = { ...previous }
      if (dots) next[group] = dots
      else delete next[group]
      return next
    })
  }, [])
  const surfacePoints = useMemo(() => Object.values(tipDots).flat(), [tipDots])
  /** Which tier the viewer shows — a view state, never sent anywhere. */
  const [viewTier, setViewTier] = useState<'full' | 'low'>('full')
  /** The box's Bounce / Weight drafts per group while a slider moves, keyed to the base signature. */
  const [sliderDrafts, setSliderDrafts] = useState<{ signature: string; groups: Record<string, Physics> }>(
    { signature: '', groups: {} })
  const [extPosting, setExtPosting] = useState(false)
  const [sub, setSub] = useState<BaseTab>('views')
  /** The state preview (Ruling A66): the picked state ('' = none, at rest) and its motion once it arrived — view
   *  state of the open tab, never sent anywhere but the GET. */
  const [previewState, setPreviewState] = useState('')
  const [stateMotion, setStateMotion] = useState<PickedStateMotion<SecondaryMotionPayload> | null>(null)
  const [stateError, setStateError] = useState('')

  // A model run (face, rig) ended: re-read the base body (new model URL,
  // steps, face cleanup state).
  const wasPending = useRef(false)
  useEffect(() => {
    const pending = !!st?.pending
    if (wasPending.current && !pending) startPoll()
    wasPending.current = pending
  }, [st?.pending, startPoll])

  const post = useCallback(
    async (path: string, body: unknown) => {
      if (posting) return
      setPosting(true)
      try {
        await apiPost(`/characters/${enc}/base-body/${path}`, body)
        startPoll(500)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        startPoll()
      } finally {
        setPosting(false)
      }
    },
    [enc, posting, startPoll, t, toast],
  )

  // Run all (rule R1): the server runs what is not current; the poll follows the views, the model and the
  // face runs it starts.
  const runAll = useCallback(async () => {
    if (posting) return
    setPosting(true)
    try {
      const d = await apiPost<{ status?: string }>(`/characters/${enc}/base-body/run-all`, {})
      const status = String(d?.status || '')
      toast(t(RUN_ALL_STATUS[status] || status), 'success')
      startPoll(500)
      pollStatus(800)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      startPoll()
    } finally {
      setPosting(false)
    }
  }, [enc, pollStatus, posting, startPoll, t, toast])

  const reloadAll = useCallback(async () => {
    startPoll()
    await loadStatus()
  }, [loadStatus, startPoll])
  const onModelRunStarted = useCallback(() => {
    pollStatus(800)
    startPoll(800)
  }, [pollStatus, startPoll])

  // The Extension bones box (Ruling A45) on the base model.
  const extSignature = info?.signature || ''
  const extGroups = info?.extension?.groups
  const extSwitches = st?.options?.extension_rig_models?.[extSignature]
  const extMotion = st?.options?.extension_motion
  /** Save one switch of the base model (rule R3: nothing is rebuilt — the poll then reports the rebuild due). */
  const saveExtSwitch = useCallback(async (id: string, key: 'enabled' | 'flip', value: boolean) => {
    if (!extSignature || extPosting) return
    setExtPosting(true)
    try {
      await apiPost(`/characters/${enc}/model3d/options`, { signature: extSignature,
        extension_rig: { ...extSwitches, [id]: { ...extSwitches?.[id], [key]: value } } })
      toast(t('Saved'))
      await reloadAll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setExtPosting(false) }
  }, [enc, extPosting, extSignature, extSwitches, reloadAll, t, toast])
  /** Save a group's motion values character-wide; `slidersOnly` merges the Bounce / Weight pair into the rest. */
  const saveExtMotion = useCallback(async (id: string, values?: Physics, slidersOnly = false) => {
    setExtPosting(true)
    try {
      const overrides = structuredClone(extMotion ?? {})
      if (slidersOnly) overrides[id] = { ...overrides[id], ...values }
      else if (values === undefined || !Object.keys(values).length) delete overrides[id]
      else overrides[id] = values
      for (const group of extGroups ?? []) {
        if (group.controls != null && overrides[group.id]) {
          overrides[group.id] = Object.fromEntries(Object.entries(overrides[group.id])
            .filter(([key]) => group.controls!.includes(key)))
        }
      }
      await apiPost(`/characters/${enc}/model3d/extension-motion`, { extension_motion: overrides })
      toast(t('Saved'))
      await reloadAll()
      if (slidersOnly) setSliderDrafts((previous) => {
        const groups = { ...previous.groups }
        delete groups[id]
        return { ...previous, groups }
      })
      return true
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return false
    } finally { setExtPosting(false) }
  }, [enc, extGroups, extMotion, reloadAll, t, toast])
  /** Rebuild (rule R2, also when current): the base model's extension bones from the saved settings, on the CPU. */
  const rebuildExt = useCallback(async () => {
    if (!extSignature) return
    setExtPosting(true)
    try {
      await apiPost(`/characters/${enc}/model3d/extension-tip/apply`, { signature: extSignature })
      startPoll(800)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setExtPosting(false) }
  }, [enc, extSignature, startPoll, t, toast])
  // The viewer's motion: the base model's payload with the box's slider drafts on top (only the controls a
  // group declares count, as on the server).
  const extPayload = info?.extension?.motion
  const motionDefaults = st?.motion_defaults
  // The state preview (Ruling A66): a pick no longer offered (the state was deleted, the groups changed) counts as none.
  const picker = statePicker(extGroups?.length ?? 0, info?.extension?.states, t)
  const pickedState = picker.options.some((option) => option.value === previewState) ? previewState : ''
  // Fetch the picked state's motion; again when the base motion changes (a saved value, a rebuild) — a read only.
  const restRev = extPayload?.rev
  useEffect(() => {
    if (!pickedState || !extSignature) return
    let cancelled = false
    setStateError('')
    apiGet<{ state: string; motion: SecondaryMotionPayload }>(stateMotionUrl(character, pickedState))
      .then((data) => {
        if (!cancelled) setStateMotion({ state: pickedState, signature: extSignature, motion: data.motion })
      })
      .catch((e) => { if (!cancelled) setStateError((e as Error).message) })
    return () => { cancelled = true }
  }, [character, extSignature, pickedState, restRev])
  const restOrState = viewerStateMotion(extPayload, pickedState, stateMotion, extSignature)
  const stateLoading = !!pickedState && !stateError && restOrState === extPayload
  const previewMotion = useMemo(() => {
    const overrides = { ...extMotion }
    for (const group of extGroups ?? []) {
      if (group.controls != null && overrides[group.id]) {
        overrides[group.id] = Object.fromEntries(Object.entries(overrides[group.id])
          .filter(([key]) => group.controls!.includes(key)))
      }
    }
    return previewMotionSliders(restOrState, motionDefaults, overrides,
      sliderDrafts.signature === extSignature ? sliderDrafts.groups : {})
  }, [extGroups, extMotion, restOrState, extSignature, motionDefaults, sliderDrafts])

  const viewLabel = (view: BaseView) =>
    view === 'front' ? t('Front view') : view === 'back' ? t('Back view') : view === 'left' ? t('Left view') : t('Right view')

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) {
    return <div className="ga-hint">{t('An animal has no base body — its 3D model is made from its T-pose picture (3D tab).')}</div>
  }
  if (!info.pipeline) {
    return <div className="ga-hint">{t('A temporary NPC has no base body — its 3D model is made from its T-pose picture.')}</div>
  }

  const model = info.model
  const modelBusy = posting || modelRunning(info) || !!st?.pending || tipsRunning(info) || !!info.mesh_repair?.running
  const ready = model?.status === 'ready'

  const collision = collisionPreview ?? model?.collision
  const tipPanels = model?.url && ready ? info.extension_tips ?? [] : []
  const meshRepair = model?.url && ready ? info.mesh_repair ?? null : null
  const tipSmoothing = model?.url && ready ? info.tip_smoothing ?? null : null
  const extension = model?.url && ready ? info.extension ?? null : null
  const extBusy = modelBusy || extPosting || !!extension?.running
  // The Extension bones box (Ruling A45): the base model's own switches for the groups WITHOUT a tip panel — a tip
  // group's light, switch, factors and Rebuild sit in its own tip panel (Ruling A53). No such group → no box.
  const tipIds = new Set(tipPanels.map((panel) => panel.id))
  const boxGroups = (extension?.groups ?? []).filter((group) => extension?.box_groups
    ? extension.box_groups.includes(group.id) : !tipIds.has(group.id))
  const extensionBox = extension && boxGroups.length ? (
    <ExtensionBonesBox legend={t('Extension bones')} groups={boxGroups}
      result={extension.result?.per_tier?.[viewTier] || extension.result} tier={viewTier}
      signature={info.signature} switches={st?.options?.extension_rig_models?.[info.signature]}
      motionDefaults={st?.motion_defaults} motionOverrides={st?.options?.extension_motion}
      disabled={extBusy || !st} rigless={false} draftKey={`${character}:${info.signature}`}
      onSwitch={(id, key, value) => { void saveExtSwitch(id, key, value) }}
      onMotion={(id, values) => saveExtMotion(id, values)}
      sliders={{
        onPreview: (id, values) => setSliderDrafts((previous) => ({ signature: info.signature,
          groups: { ...(previous.signature === info.signature ? previous.groups : {}), [id]: values } })),
        onSave: (id, values) => saveExtMotion(id, values, true),
      }}
      lights={extension.lights}
      note={extension.running ? t('Rebuilding…')
        : extension.due ? t(extension.due_reason === 'groups' ? EXT_DUE_GROUPS_NOTE : TIP_DUE_NOTE) : undefined}
      rebuild={{
        label: t(TIP_REBUILD_LABEL), primary: extension.due, disabled: extBusy,
        title: t('Rebuilds the extension bones of the base model from the saved settings, also when they are built already.'),
        onClick: () => { void rebuildExt() },
      }} />
  ) : null
  // A tip group's box: its settings, its factors (motion values, saved character-wide, live in the viewer while a
  // slider moves) and its Rebuild.
  const lone = tipPanels.length === 1 && !extensionBox
  const tipPanel = (panel: ExtensionTipPanelInfo) => (
    <ExtensionTipPanel key={panel.id} character={character} signature={info.signature}
      panel={panel} disabled={modelBusy || extPosting} onPreview={onTipPreview} wide={lone}
      onStarted={() => startPoll(800)}
      motion={st?.motion_defaults?.[panel.id] ? {
        defaults: st.motion_defaults[panel.id] as unknown as Physics,
        overrides: st.options?.extension_motion?.[panel.id],
        onSave: (values) => saveExtMotion(panel.id, values, true),
        onReset: () => saveExtMotion(panel.id, undefined),
        onPreview: (values) => setSliderDrafts((previous) => {
          const groups = { ...(previous.signature === info.signature ? previous.groups : {}) }
          if (values) groups[panel.id] = values
          else delete groups[panel.id]
          return { signature: info.signature, groups }
        }),
      } : undefined} />
  )
  const viewRows = BASE_VIEWS.map((view) => baseViewRow({ running: !!info.status?.[view]?.running,
    failed: !!info.status?.[view]?.failed, error: info.status?.[view]?.error, warning: info.status?.[view]?.warning,
    stored: !!info.images?.[view], freshness: info.image_meta?.[view]?.freshness }, t))
  const modelRow = baseModelRow(model, t)
  const lights = [...viewRows.map((row) => row.light), modelRow.light]
  const noModelYet = <div className="ga-hint">{t('Comes with the base model — none built yet')}</div>
  const tabs: Array<{ id: BaseTab; label: string }> = [
    { id: 'views', label: `${t('Views')} (${BASE_VIEWS.length})` },
    { id: 'model', label: t('Base model') },
    { id: 'extensions', label: t('Extension bones') },
    { id: 'collision', label: t('Collision capsules') },
    { id: 'settings', label: t('Settings') },
  ]

  return (
    <div>
    <RunAllHeader runAll={info.run_all} lights={lights} busy={posting || viewsRunning(info) || modelBusy}
      buildRunning={!!figure?.build.running} activity={info.activity} onRun={() => { void runAll() }}
      onOpenFigure={onOpenFigure} />
    {figure?.build.running && info.activity?.base ? <div className="ga-hint">{t(BUILD_RUNNING_NOTE)}</div> : null}
    {/* Ruling A61: the base mesh does not match its own views — Run all makes it again (the plain body step). */}
    {figure?.problem?.kind === 'mesh_mismatch' && figure.problem.body === 'plain' && !figure.build.running ? (
      <div style={{ marginBottom: 8 }}>
        <BuildProblemView problem={figure.problem} busy={posting || viewsRunning(info) || modelBusy}
          onRun={() => { void runAll() }} />
      </div>
    ) : null}
    <div className="ga-split ga-split-views ga-split-figure">
      <div className="ga-split-col">
        {model?.url ? (
          <>
            <Model3DViewer key={model.url} url={viewTier === 'low' && extension?.tiers?.includes('low')
              ? `${model.url}${model.url.includes('?') ? '&' : '?'}tier=low` : model.url}
              format="glb" height={600} subject="figure"
              freshness={model.freshness} builtAt={model.created_at}
              collision={collision} showCollision={!!collisionPreview}
              motion={ready ? previewMotion : undefined}
              surfacePoints={surfacePoints} />
            {/* Full / Distance (Ruling A45): which stored mesh the viewer and the box show; only once the
                distance mesh exists — asking for it here would start its build. */}
            {extension?.tiers?.includes('low') ? (
              <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 6 }}>
                <span className="ga-hint">{t('Showing')}</span>
                <button type="button" className={`ga-btn ga-btn-sm${viewTier === 'full' ? ' ga-btn-primary' : ''}`}
                  aria-pressed={viewTier === 'full'} onClick={() => setViewTier('full')}>{t('Full')}</button>
                <button type="button" className={`ga-btn ga-btn-sm${viewTier === 'low' ? ' ga-btn-primary' : ''}`}
                  aria-pressed={viewTier === 'low'} onClick={() => setViewTier('low')}>
                  {t('Distance')}{extension.low_tris ? ` · ${extension.low_tris.toLocaleString()}` : ''}
                </button>
              </div>
            ) : null}
            {/* The state preview (Ruling A66): beside the viewer, live, nothing saved. */}
            {ready ? (
              <StatePreviewRow picker={picker} value={pickedState} loading={stateLoading} error={stateError}
                onChange={(state) => { setStateError(''); setPreviewState(state) }} />
            ) : null}
          </>
        ) : (
          <div className="ga-hint" style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1px solid var(--border, #30363d)', borderRadius: 6, padding: 12, textAlign: 'center' }}>
            {model?.status === 'running' ? t('Generating…') : t('No base model yet')}
          </div>
        )}
      </div>

      <div className="ga-split-col" style={PANEL}>
        <SubTabs tabs={tabs} value={sub} onChange={setSub} />
        {sub === 'views' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="ga-basebody-views">
              {BASE_VIEWS.map((view) => (
                <ViewTile key={view} info={info} view={view} label={viewLabel(view)} jobs={jobs}
                  busy={posting} onRender={(v, force) => post('images', { view: v, force })}
                  onSkinStep={() => post('skin-step', {})} />
              ))}
            </div>
            {jobs ? <div className="ga-hint">{t('A new view makes the base model stale — Run all or the next Build you start rebuilds it.')}</div> : null}
          </div>
        ) : null}
        {sub === 'model' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <StepRowView row={{ name: t('Base model'), ...modelRow,
              button: !info.images?.front ? { disabled: t('Render the base body views first') } : null }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <button type="button" className="ga-btn ga-btn-sm" disabled={modelBusy || !info.images?.front}
                  title={t('Builds the base model anew from the four views: mesher, then face cleanup, face retexture and rig as switched on below.')
                    + (autoBuild ? ` — ${t(AUTO_BUILD_NOTE)}` : '')}
                  onClick={() => post('model', { force: !!model })}>
                  {jobs ? singleAction('model', jobs.model, t) : model ? t('Regenerate') : t('Generate model')}
                </button>
                {model?.created_at && model.status !== 'running' ? (
                  <span className="ga-hint">{t('Built')} {formatDateTime(model.created_at, clockSettings())}</span>
                ) : null}
              </div>
            </StepRowView>
            {model?.steps?.length ? <ModelSteps steps={model.steps} /> : null}
            {/* The base mesh repair (Ruling A34): status light, settings saved on their own, Repair again (local). */}
            {meshRepair ? (
              <MeshRepairPanel character={character} state={meshRepair} disabled={modelBusy}
                onSaved={reloadAll} onStarted={() => startPoll(800)} />
            ) : null}
            {/* The tip smoothing (Ruling A43): status light with the reason, Built time, Smooth again (local). Hidden
                without a switched-on tip part. */}
            {tipSmoothing ? (
              <TipSmoothingPanel character={character} signature={info.signature} state={tipSmoothing}
                disabled={modelBusy} onStarted={() => startPoll(800)} />
            ) : null}
            {st && model ? (
              <>
                {jobs ? <ActionLine text={singleAction('face', 1, t)} auto={autoBuild} /> : null}
                <ModelFaceActions character={character} st={st} face={model}
                  signature={info.signature} cleanup={info.face_cleanup ?? st.face_cleanup}
                  hasModel={!!model.url} canRerig={!!st.pipeline?.rerig_source}
                  rerigBlocked={t('The base body has no retained unrigged mesh — regenerate the base model (Regenerate beside “Base model”).')}
                  onReload={reloadAll} onStarted={onModelRunStarted} settingsElsewhere />
              </>
            ) : null}
          </div>
        ) : null}
        {sub === 'extensions' ? (
          // One box per pair tip group (everything of the group; the dots on the model follow the sliders) and the
          // Extension bones box for the other groups in two equal columns, top-aligned (Rulings A45, A53): the box
          // beside the first tip panel, further tip panels below; a lone tip panel spans both columns; one column on
          // a narrow width.
          tipPanels.length || extensionBox ? (
            <div className="ga-basebody-ext">
              <div className="ga-ext-grid">
                {tipPanels.slice(0, 1).map(tipPanel)}
                {extensionBox}
                {tipPanels.slice(1).map(tipPanel)}
              </div>
            </div>
          ) : noModelYet
        ) : null}
        {sub === 'collision' ? (
          !(model?.url && ready) ? noModelYet
            : model.collision === undefined ? <div className="ga-hint">{t('No collision capsules on this model')}</div>
            : (
              <CollisionScales character={character} collision={model.collision}
                scales={info.collision_scales} disabled={modelBusy}
                onPreview={setCollisionPreview} onSaved={reloadAll} />
            )
        ) : null}
        {sub === 'settings' ? (
          <BaseSettings character={character} info={info} st={st} pending={modelBusy} onReload={reloadAll} />
        ) : null}
      </div>
    </div>
    </div>
  )
}
