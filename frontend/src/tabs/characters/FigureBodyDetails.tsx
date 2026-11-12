/**
 * FigureBodyDetails — the plain body's own views and model, collapsed under
 * the Figure tab's "Body:" line (plan 2026-11-12-unified-worn-pieces Task 10,
 * spec ruling 8: "the body's own views, Regenerate and face cleanup move into
 * the Figure tab's collapsed Body details, each a single action"). Moved
 * from the Base body tab (FieldBaseBody, which renders it under its
 * pipeline switch until that tab is removed).
 *
 * Layout: two columns — the four views stacked and small on the left (a
 * click enlarges one), the base model's 3D preview with everything that
 * acts on it on the right: its steps beside the preview, the collision
 * capsule sliders beside it too (live preview while dragging — the outfit
 * models inherit the base body's set), one panel per pair tip extension
 * group (ExtensionTipPanel), and the face/rig actions under it
 * (ModelFaceActions) — on the pipeline they all act on the base body.
 *
 * Every button does ONE thing and says what before the click (the spec's
 * rule 3): a view's Regenerate renders that view only, the model's
 * Regenerate meshes the plain body only — there is no "render all" chain
 * here; the Build plans what is missing. `jobs` (GET …/figure
 * `body.plain.jobs`) gives the cost lines: "Regenerate this view — 1 image
 * job", "Regenerate the plain body's mesh — 3 hub jobs". A new base model
 * (Regenerate, a face or rig action) starts the automatic Build when
 * "Build automatically" is on (`garments.after_base_model` → body change),
 * so those say "then Build runs automatically". "Run skin step" changes the
 * front's bytes: the base model is stale then, and only the next (manual)
 * Build rebuilds it (ruling 8a) — written under the button with its cost.
 *
 * Backend (app/routes/characters.py, app/core/base_body.py):
 * GET /characters/{n}/base-body (views, model, face fields, collision, face
 * cleanup; polled while something runs), POST .../base-body/images {view,
 * force} (409 without a profile picture or, for a side view, the front),
 * POST .../base-body/model {force} (409 while another 3D run of the
 * character is going), POST .../base-body/skin-step (the front's skin
 * detail edit on the stored neutral front; GET .../images/front?variant=
 * neutral serves it), GET .../model3d (useModel3DStatus).
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
import { useModel3DStatus } from './useModel3DStatus'
import type { CollisionPayload } from '@anima/scene-render'
import { BASE_VIEWS, modelRunning, tipsRunning, useBaseBody, viewsRunning } from './useBaseBody'
import type { BaseBodyInfo, BaseView } from './useBaseBody'
import { AUTO_BUILD_NOTE, singleAction, staleBaseNote } from './figureModel'

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

export function FigureBodyDetails({ character, jobs, autoBuild = false, onChanged }: {
  character: string
  /** The single actions' costs; without them (the old Base body tab) no cost lines are written. */
  jobs?: PlainBodyJobs
  /** "Build automatically" is on: a new base model starts the Build. */
  autoBuild?: boolean
  /** Something of the plain body changed (a run ended): the caller re-reads its own state. */
  onChanged?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, startPoll } = useBaseBody(character)
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

  // Anything of the plain body running → idle: the caller's figure state changed too.
  const wasActive = useRef(false)
  const active = !!info && (viewsRunning(info) || modelRunning(info) || tipsRunning(info) || !!st?.pending)
  useEffect(() => {
    if (wasActive.current && !active) onChanged?.()
    wasActive.current = active
  }, [active, onChanged])

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
    return <div className="ga-hint">{t('The base body is for humanoid characters only.')}</div>
  }
  if (!info.pipeline) return null

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
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <div className="ga-view-stack">
          {BASE_VIEWS.map((view) => (
            <ViewTile key={view} info={info} view={view} label={viewLabel(view)} jobs={jobs}
              busy={posting} onRender={(v, force) => post('images', { view: v, force })}
              onSkinStep={() => post('skin-step', {})} />
          ))}
        </div>
        {jobs ? <div className="ga-hint">{t('A new view makes the base model stale — the next Build rebuilds it.')}</div> : null}
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
                freshness={model.freshness}
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
                    onReload={reloadAll} onStarted={onModelRunStarted} />
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
