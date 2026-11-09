/**
 * FieldBaseBody — the Base body tab (template tab `base_body_tab`, before
 * Pose; spec
 * docs/superpowers/specs/2026-11-08-base-body-outfits-design.md): the
 * per-character switch onto the base-body pipeline, the four bald A-pose
 * views of the base body, and the rigged base model built from them.
 *
 * Layout: two columns — the four views stacked and small on the left (a
 * click enlarges one), the base model's 3D preview with everything that
 * acts on it on the right: its steps beside the preview, the collision
 * capsule sliders beside it too (live preview while dragging — the outfit
 * models inherit the base body's set), and the face/rig actions under it
 * (ModelFaceActions: face cleanup switch + re-apply, face before rigging,
 * face retexture, re-rig) — on the pipeline they all act on the base body.
 *
 * Backend (app/routes/characters.py, app/core/base_body.py):
 * GET /characters/{n}/base-body (info + base model face fields, collision,
 * face cleanup state; polled while something runs),
 * POST .../base-body/pipeline {enabled} (400 for a non-humanoid),
 * POST .../base-body/images {view?, force?} (409 without a profile picture),
 * POST .../base-body/model {force?} (409 while another 3D run of the
 * character is going — base and outfit share one guard);
 * GET .../model3d (options, backends, run results — useModel3DStatus).
 *
 * The section is humanoid-only in the template (`visible_when`); should a
 * non-humanoid still reach it, it shows only a hint. The outfit model's
 * retexture status lives in the Pose tab (BaseBodyOutfitStatus).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { RefImage } from './RefImage'
import { CollisionScales } from './CollisionScales'
import { ModelFaceActions } from './ModelFaceActions'
import { useModel3DStatus } from './useModel3DStatus'
import type { CollisionPayload } from '@anima/scene-render'
import { BASE_VIEWS, modelRunning, useBaseBody, viewsRunning } from './useBaseBody'
import type { BaseBodyInfo, BaseView } from './useBaseBody'

const TILE_HEIGHT = 128

const EMPTY_TILE: CSSProperties = {
  width: '100%',
  height: TILE_HEIGHT,
  borderRadius: 6,
  border: '1px solid var(--border, #30363d)',
  background: 'rgba(255, 255, 255, 0.04)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: 6,
  boxSizing: 'border-box',
}

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
const WARNING_STYLE: CSSProperties = { color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }

function ViewTile({ info, view, label, busy, onRender }: {
  info: BaseBodyInfo
  view: BaseView
  label: string
  busy: boolean
  onRender: (view: BaseView, force: boolean) => void
}) {
  const { t } = useI18n()
  const url = info.images?.[view] || null
  const st = info.status?.[view]
  // A side/back view edits the front: it cannot render before the front exists.
  const needsFront = view !== 'front' && !info.images?.front
  return (
    <div style={{ minWidth: 0 }}>
      <div className="ga-face-actions-row" style={{ justifyContent: 'space-between', marginBottom: 2 }}>
        <span className="ga-hint">{label}</span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !!st?.running || needsFront}
          title={needsFront ? t('Render the front view first') : undefined}
          onClick={() => onRender(view, !!url)}
          aria-label={`${url ? t('Regenerate') : t('Generate')} · ${label}`}
        >
          {url ? t('Regenerate') : t('Generate')}
        </button>
      </div>
      {url ? (
        <RefImage key={url} src={url} height={TILE_HEIGHT} label={label} meta={info.image_meta?.[view]} compact />
      ) : (
        <div className="ga-hint" style={EMPTY_TILE}>
          {st?.running ? t('Generating…') : t('No render yet')}
        </div>
      )}
      {url && st?.running ? <div className="ga-hint">{t('Generating…')}</div> : null}
      {st?.failed && !st.running ? (
        <div className="ga-hint" style={ERROR_STYLE} title={st.error || ''}>
          {t('Failed')}{st.error ? `: ${st.error}` : ''}
        </div>
      ) : null}
      {url && st?.warning && !st.running ? (
        <div className="ga-hint" style={WARNING_STYLE} title={st.warning}>{st.warning}</div>
      ) : null}
    </div>
  )
}

export function FieldBaseBody({ character }: { character: string }) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, setInfo, startPoll } = useBaseBody(character)
  // Options, backends and run results of the model actions (face, rig).
  const { st, load: loadStatus, startPoll: pollStatus } = useModel3DStatus(character)
  // The user's own click, until the request answered (the poll then shows
  // the server's running state).
  const [posting, setPosting] = useState(false)
  /** Slider preview of the collision scales — shown instead of the stored set. */
  const [collisionPreview, setCollisionPreview] = useState<CollisionPayload | null>(null)

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

  const setPipeline = useCallback(
    async (enabled: boolean) => {
      if (posting) return
      setPosting(true)
      try {
        const d = await apiPost<{ pipeline: boolean }>(
          `/characters/${enc}/base-body/pipeline`, { enabled })
        setInfo((prev) => (prev ? { ...prev, pipeline: d.pipeline } : prev))
        startPoll()
        void loadStatus()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setPosting(false)
      }
    },
    [enc, loadStatus, posting, setInfo, startPoll, t, toast],
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

  const imagesBusy = posting || viewsRunning(info)
  const allPresent = BASE_VIEWS.every((v) => !!info.images?.[v])
  const model = info.model
  const modelBusy = posting || modelRunning(info) || !!st?.pending
  const ready = model?.status === 'ready'

  const pipelineSwitch = (
    <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
      title={t('A bald, neutral A-pose base body built from the profile picture. Outfits are rendered as edits of its views and painted onto its rigged model.')}>
      <input
        type="checkbox"
        checked={info.pipeline}
        disabled={posting}
        onChange={(e) => setPipeline(e.target.checked)}
      />
      <span>{t('Use base body pipeline')}</span>
    </label>
  )
  if (!info.pipeline) {
    return (
      <div className="ga-form">
        {pipelineSwitch}
        <div className="ga-hint">
          {t('A bald, neutral A-pose base body built from the profile picture. Outfits are rendered as edits of its views and painted onto its rigged model.')}
        </div>
      </div>
    )
  }

  const collision = collisionPreview ?? model?.collision
  const asideTools = model?.url && ready && model.collision !== undefined ? (
    <CollisionScales character={character} collision={model.collision}
      scales={info.collision_scales} disabled={modelBusy}
      onPreview={setCollisionPreview} onSaved={reloadAll} />
  ) : undefined

  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        {pipelineSwitch}
        <div className="ga-view-stack">
          {BASE_VIEWS.map((view) => (
            <ViewTile key={view} info={info} view={view} label={viewLabel(view)}
              busy={posting} onRender={(v, force) => post('images', { view: v, force })} />
          ))}
        </div>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={imagesBusy}
          // Missing views only — or every view anew once all four exist.
          onClick={() => post('images', { force: allPresent })}
        >
          {viewsRunning(info) ? t('Generating…') : allPresent ? t('Regenerate all') : t('Render all')}
        </button>
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
                collision={collision} showCollision={!!collisionPreview} />
            </div>
          ) : null}
          {asideTools || (st && model) ? (
            <div className="ga-basebody-side">
              {asideTools}
              {st && model ? (
                <ModelFaceActions character={character} st={st} face={model}
                  signature={info.signature} cleanup={info.face_cleanup ?? st.face_cleanup}
                  hasModel={!!model.url} canRerig={!!st.pipeline?.rerig_source}
                  rerigBlocked={t('The base body has no retained unrigged mesh — regenerate the base model (Regenerate beside “Base model”).')}
                  onReload={reloadAll} onStarted={onModelRunStarted} />
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
