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
 * Layout: the Run all header across the top; then two columns — the four views stacked and small on the left (a
 * click enlarges one), the base model's 3D preview with everything that acts on it on the right: its steps
 * beside the preview, the collision capsule sliders beside it too (live preview while dragging — the outfit
 * models inherit the base body's set), one panel per pair tip extension group (ExtensionTipPanel), and the
 * face/rig actions under it (ModelFaceActions); the Settings section closes the tab.
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
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { ViewRenderTile } from './ViewRenderTile'
import { RefImage } from './RefImage'
import { CollisionScales } from './CollisionScales'
import { ExtensionTipPanel } from './ExtensionTipPanel'
import type { TipDots } from './ExtensionTipPanel'
import { ModelFaceActions } from './ModelFaceActions'
import { FaceSettings } from './FaceSettings'
import { FieldSet } from './FieldSet'
import { useModel3DStatus } from './useModel3DStatus'
import type { CollisionPayload } from '@anima/scene-render'
import { BASE_VIEWS, modelRunning, tipsRunning, useBaseBody, viewsRunning } from './useBaseBody'
import type { BaseBodyInfo, BaseView } from './useBaseBody'
import { AUTO_BUILD_NOTE, BUILD_RUNNING_NOTE, ESTIMATE_NOTE, singleAction, staleBaseNote } from './figureModel'
import { RUN_ALL_STATUS, faceDueLine, runAllButton, runAllStep, runAllWhat } from './baseBodyModel'
import type { BaseRunAll } from './baseBodyModel'

const TILE_HEIGHT = 128

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }

/** What the single actions cost (GET …/figure `body.plain.jobs`). */
export interface PlainBodyJobs {
  view: number | null
  front: number | null
  model: number | null
  after_front: number | null
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
 *  button that runs it again on the stored neutral front (base_skin) — with
 *  what it makes stale under it. */
function SkinStepLine({ info, busy, staleJobs, onRun }: {
  info: BaseBodyInfo
  busy: boolean
  /** Hub jobs of the Build that then rebuilds the base (undefined = not known here). */
  staleJobs: number | null | undefined
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
            {t('Run skin step')}
          </button>
        ) : null}
      </div>
      {skin.enabled && staleJobs !== undefined ? <ActionLine text={staleBaseNote(staleJobs, t)} /> : null}
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
  return (
    <ViewRenderTile label={label} url={url} meta={info.image_meta?.[view]} height={TILE_HEIGHT}
      running={!!st?.running} failed={!!st?.failed} error={st?.error} warning={st?.warning}
      disabled={busy || needsFront} disabledReason={needsFront ? t('Render the front view first') : undefined}
      actionTitle={cost}
      status={(
        <>
          {cost && !needsFront ? <ActionLine text={cost} /> : null}
          {view === 'front' ? (
            <SkinStepLine info={info} busy={busy || viewsRunning(info)} staleJobs={jobs?.after_front}
              onRun={onSkinStep} />
          ) : null}
        </>
      )}
      onRender={() => onRender(view, !!url)} />
  )
}

/** The tab's head: "Run all" (rule R1) with its count, what it runs, the plan collapsed, its last error. */
function RunAllHeader({ runAll, busy, buildRunning, onRun, onOpenFigure }: {
  runAll: BaseRunAll | null | undefined
  busy: boolean
  /** A Build of the character runs: Run all waits for it (the server answers 409). */
  buildRunning: boolean
  onRun: () => void
  onOpenFigure?: () => void
}) {
  const { t } = useI18n()
  const button = runAllButton(runAll, t)
  const disabled = busy || button.disabled || buildRunning
  const what = runAll ? runAllWhat(runAll.kind, t, runAll.face_due) : ''
  const lastError = runAll && !runAll.running && runAll.last?.error ? runAll.last.error : ''
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
      <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-primary" disabled={disabled}
          title={runAll?.note || undefined} onClick={onRun}>
          {button.label}
        </button>
        {what ? <span className="ga-hint">{what}</span> : null}
        {onOpenFigure ? (
          <button type="button" className="ga-btn ga-btn-sm" style={{ marginLeft: 'auto' }} onClick={onOpenFigure}>
            {t('Open Figure tab')}
          </button>
        ) : null}
      </div>
      {buildRunning ? <div className="ga-hint">{t('A Build runs for this character — Run all waits until it has ended.')}</div>
        : button.reason ? <div className="ga-hint">{button.reason}</div>
        : runAll?.kind && runAll.hub_jobs ? <div className="ga-hint">{t(ESTIMATE_NOTE)}</div> : null}
      {runAll?.kind && runAll.steps.length ? (
        <details>
          <summary style={{ cursor: 'pointer' }} className="ga-hint">{t('What Run all runs')}</summary>
          <ol style={{ margin: '4px 0 0 18px', padding: 0 }} className="ga-hint">
            {runAll.steps.map((step, i) => (
              <li key={`${step.name}:${i}`}>
                {runAllStep(step.name, t)}
                {step.jobs === null ? ` — ${t('cost unknown')}` : step.jobs ? ` — ${step.jobs === 1 ? t('1 hub job')
                  : t('{n} hub jobs').replace('{n}', String(step.jobs))}` : ` — ${t('local')}`}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {lastError ? <div className="ga-hint" style={ERROR_STYLE}>{t('Run all')}: {lastError}</div> : null}
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
    <FieldSet title={t('Settings')}>
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
    </FieldSet>
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
  const modelBusy = posting || modelRunning(info) || !!st?.pending || tipsRunning(info)
  const ready = model?.status === 'ready'

  const collision = collisionPreview ?? model?.collision
  const tipPanels = model?.url && ready ? info.extension_tips ?? [] : []
  const asideTools = model?.url && ready && (model.collision !== undefined || tipPanels.length) ? (
    <>
      {model.collision !== undefined ? (
        <CollisionScales character={character} collision={model.collision}
          scales={info.collision_scales} disabled={modelBusy}
          onPreview={setCollisionPreview} onSaved={reloadAll} />
      ) : null}
      {/* Pair tip groups: position, mirror and colour disc; the dots on the
          model follow the sliders. */}
      {tipPanels.map((panel) => (
        <ExtensionTipPanel key={panel.id} character={character} signature={info.signature}
          panel={panel} disabled={modelBusy} onPreview={onTipPreview}
          onStarted={() => startPoll(800)} />
      ))}
    </>
  ) : undefined

  return (
    <div>
    <RunAllHeader runAll={info.run_all} busy={posting || viewsRunning(info) || modelBusy}
      buildRunning={!!figure?.build.running} onRun={() => { void runAll() }} onOpenFigure={onOpenFigure} />
    {figure?.build.running ? <div className="ga-hint">{t(BUILD_RUNNING_NOTE)}</div> : null}
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <div className="ga-view-stack">
          {BASE_VIEWS.map((view) => (
            <ViewTile key={view} info={info} view={view} label={viewLabel(view)} jobs={jobs}
              busy={posting} onRender={(v, force) => post('images', { view: v, force })}
              onSkinStep={() => post('skin-step', {})} />
          ))}
        </div>
        {jobs ? <div className="ga-hint">{t('A new view makes the base model stale — Run all or the next Build you start rebuilds it.')}</div> : null}
      </div>

      <div className="ga-split-col">
        <div className="ga-face-actions-row">
          <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Base model')}</span>
          <span className="ga-hint">
            {!model ? t('No base model yet')
              : model.status === 'running' ? t('Generating…')
              : model.status === 'failed' ? t('Failed')
              : model.status === 'unrigged' ? t('Static mesh without a rig')
              : t('Ready')}
            {model?.created_at && model.status !== 'running'
              ? ` · ${formatDateTime(model.created_at, clockSettings())}` : ''}
          </span>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={modelBusy || !info.images?.front}
            title={!info.images?.front ? t('Render the base body views first')
              : t('Builds the base model anew from the four views: mesher, then face cleanup, face retexture and rig as switched on below.')}
            onClick={() => post('model', { force: !!model })}
          >
            {model ? t('Regenerate') : t('Generate model')}
          </button>
        </div>
        {!info.images?.front ? (
          <div className="ga-hint">{t('Render the base body views first')}</div>
        ) : jobs ? (
          <ActionLine text={singleAction('model', jobs.model, t)} auto={autoBuild} />
        ) : null}
        {model?.status === 'failed' && model.error ? (
          <div className="ga-hint" style={ERROR_STYLE}>{model.error}</div>
        ) : null}
        {/* Left to right: the preview; the step checklist and tilt beside
            it; then a column with the collision sliders on top (the viewer
            shows the draft capsules while a slider moves) and the face and
            rig actions below. */}
        <div className="ga-basebody-model">
          {model?.url ? (
            <div className="ga-model3d-fit">
              <Model3DViewer key={model.url} url={model.url} format="glb" height={480} previewTilt
                freshness={model.freshness} builtAt={model.created_at}
                statusPanel={model.steps?.length ? <ModelSteps steps={model.steps} /> : undefined}
                collision={collision} showCollision={!!collisionPreview}
                surfacePoints={surfacePoints} />
            </div>
          ) : null}
          {asideTools || (st && model) ? (
            <div className="ga-basebody-side">
              {asideTools}
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
        </div>
      </div>
    </div>
    <BaseSettings character={character} info={info} st={st} pending={modelBusy} onReload={reloadAll} />
    </div>
  )
}
