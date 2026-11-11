/**
 * FieldOutfitBody — the Outfit body tab (template tab `outfit_body_tab`,
 * special section `outfit_body`, right after Base body; plan
 * docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 4). The
 * mode switch `outfit_body_mode` is the template field above this panel.
 *
 * Mesh mode: every combination of painted pieces has its own meshed and
 * rigged outfit body. Layout like the Base body tab, three columns on one
 * screen: the bodies (one line each) and the selected body's dressed views
 * stacked small on the left (a click enlarges one), each with its server
 * freshness badge and its own Regenerate (ONE view rendered anew, image jobs
 * only — the back follows the front through its draft, so a new front leaves
 * the back "outdated: Made from an older dressed front" until its own
 * Regenerate; no cascade); its 3D preview with the step checklist and the
 * collision capsule toggle in the middle, the model's own Regenerate (mesh
 * again from the views shown) beside its title — it shows "outdated: Dressed
 * views changed" after a view was rendered anew; on the right its other
 * actions, the outfits standing on it, its dress text and the garments
 * fitted onto it (one line each, details on hover, Re-fit per garment).
 * Every disabled action shows its reason as a line under it (the server's
 * `blocked`, e.g. "Locked: a 3D model job is running for this body"), not
 * only as a tooltip. The worn outfit's body is always listed: before its
 * dressed views exist it is a pending entry ("Worn outfit — dressed views
 * missing") with Generate views (image jobs only, never chained to the
 * mesh); bodies that were never built and that no outfit stands on any more
 * are listed last, collapsed, as "Orphaned — no outfit stands on it".
 * Retexture mode: the painted bodies, the worn outfit's first and marked
 * "current" (before its dressed views exist a pending entry); the others
 * below with the outfits that use them ("used by"), never current. The
 * current one has Generate (pending) / Build outfit model (its model is
 * missing): the missing dressed views, then the outfit model, never forced —
 * a stored painted body is reused on the CPU; every painted body with an
 * outfit standing on it has Regenerate (dressed views anew + painted again).
 * Both queue like the mesh runs, with Cancel, and show why they are locked.
 * Every stored painted body says why it is kept (the artefact graph's
 * verdict `gc`: the live outfits that would be built on it now) or that no
 * outfit needs it any more (outdated after a piece, its text or its own-mesh
 * flag changed — the model built on it keeps working, it is a copy) with
 * Delete and the size it frees; Delete is disabled with the kept reason.
 *
 * Backend (app/routes/outfit_bodies.py, app/core/outfit_bodies.py):
 * GET /characters/{n}/outfit-bodies (polled while a run waits or works),
 * POST …/{body}/regenerate | rerig | refit {item_id?} and
 * POST …/{body}/views/{view}/regenerate — 202 with the queue place, a run
 * queues behind the character's running 3D run, never 409 for that (409 when
 * it has nothing to work on: a view's `blocked`); POST …/{body}/cancel
 * {view?} — takes the body's (that view's) waiting run out of the queue (409
 * once it has started, 404 when none waits); POST …/{body}/delete — the body
 * and its chain through the artefact graph (409 while a run is on it);
 * POST …/{body}/generate-views — the worn outfit's missing dressed views
 * (202 queued like the other runs, 404 for a body it does not stand on);
 * retexture mode: POST …/{key}/paint | repaint (202, same queue);
 * POST …/{tsig}/delete — the painted body through the artefact graph's
 * explicit collect (409 while an outfit would be built on it).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { formatBytes } from '../../lib/formatBytes'
import { FreshnessBadge } from './FreshnessBadge'
import { meshNotReadyText } from './garmentStyle'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { RefImage } from './RefImage'
import { ViewRenderTile } from './ViewRenderTile'
import { BODY_VIEWS, useOutfitBodies } from './useOutfitBodies'
import type {
  BodyAction, BodyFit, BodyView, BodyViewInfo, OutfitBody, PaintedAction, PaintedBody, RunKind,
} from './useOutfitBodies'

const TILE_HEIGHT = 112
/** The body's dressed views, stacked like the Base body tab's. */
const VIEW_TILE_HEIGHT = 128

const EMPTY_TILE: CSSProperties = {
  width: '100%',
  height: TILE_HEIGHT,
  borderRadius: 6,
  border: '1px dashed var(--border, #30363d)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  boxSizing: 'border-box',
}

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
const WARNING_STYLE: CSSProperties = { color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }
/** The visible reason under a disabled action. */
const REASON_STYLE: CSSProperties = { fontStyle: 'italic', overflowWrap: 'anywhere' }

const ACTION_LABELS: Record<BodyAction, string> = {
  regenerate: 'Regenerate', rerig: 'Re-rig', refit: 'Re-fit all', delete: 'Delete', views: 'Generate views',
}

const VIEW_LABELS: Record<BodyView, string> = {
  front: 'Front view', back: 'Back view', left: 'Left view', right: 'Right view',
}

const FIT_STATUS: Record<string, { dot: string; label: string }> = {
  accepted: { dot: 'green', label: 'Fitted' },
  stale: { dot: 'yellow', label: 'Outdated' },
  outdated: { dot: 'yellow', label: 'From an older base fit' },
  missing: { dot: 'grey', label: 'Not fitted yet' },
  failed: { dot: 'red', label: 'Refused' },
  no_base_fit: { dot: 'grey', label: 'No base fit' },
}

function dotOf(body: OutfitBody): string {
  if (body.status === 'failed') return 'red'
  if (body.status === 'running' || body.status === 'queued') return 'yellow'
  if (body.freshness?.state === 'stale') return 'yellow'
  return body.status === 'ready' ? 'green' : 'grey'
}

function useStatusText() {
  const { t } = useI18n()
  return (body: OutfitBody): string => {
    if (body.status === 'running') {
      return body.run_kind === 'rerig' ? t('Re-rigging…') : body.run_kind === 'refit' ? t('Re-fitting…')
        : body.run_kind === 'build' ? t('Building…') : body.run_kind === 'view' ? t('Rendering…')
          : body.run_kind === 'views' ? t('Rendering views…') : t('Meshing…')
    }
    if (body.status === 'queued') return `${t('Queued')} (#${body.queue_position ?? '?'})`
    if (body.status === 'failed') return t('Failed')
    if (body.orphaned) return t('Orphaned — no outfit stands on it')
    if (body.status === 'missing' && body.worn_outfit?.views_missing.length) {
      return t('Worn outfit — dressed views missing')
    }
    if (body.status === 'missing') return t('Not built')
    if (body.status === 'unrigged') return t('Static mesh without a rig')
    return t('Ready')
  }
}

/** Short label of a body: the outfits standing on it, else the worn outfit's name, else its id. */
function bodyLabel(body: OutfitBody): string {
  return body.outfits.map((o) => o.name || o.signature).join(' · ') || body.worn_outfit?.name || body.body_id
}

/** The worn outfit's body (server `current`) — a body another outfit uses is never shown as current. */
function isCurrent(body: OutfitBody): boolean {
  return !!body.current
}

/** The visible reasons under a row of disabled actions: one line when they share it (a lock), else one per action. */
function ActionReasons({ reasons }: { reasons: [BodyAction, string][] }) {
  const { t } = useI18n()
  const shown = reasons.filter(([, reason]) => !!reason)
  if (!shown.length) return null
  if (shown.length > 1 && shown.every(([, reason]) => reason === shown[0][1])) {
    return <div className="ga-hint" style={REASON_STYLE}>{t(shown[0][1])}</div>
  }
  return (
    <>
      {shown.map(([action, reason]) => (
        <div key={action} className="ga-hint" style={REASON_STYLE}>{t(ACTION_LABELS[action])}: {t(reason)}</div>
      ))}
    </>
  )
}

function ViewTiles({ views, meta, keyLabel }: {
  views: OutfitBody['views']
  meta: OutfitBody['image_meta']
  keyLabel: string
}) {
  const { t } = useI18n()
  // Only the views that exist (the side views are dressed only with the world switch).
  const shown = BODY_VIEWS.filter((view) => !!views?.[view])
  if (!shown.length) return <div className="ga-hint" style={EMPTY_TILE}>{t('No view images')}</div>
  return (
    <div className="ga-view-pair">
      {shown.map((view) => (
        <RefImage key={view} src={views[view] as string} height={TILE_HEIGHT}
          label={`${t(VIEW_LABELS[view])} · ${keyLabel}`} meta={meta?.[view]} compact />
      ))}
    </div>
  )
}

/** One dressed view of the selected body: freshness, its own Regenerate, queue place + Cancel. */
function BodyViewTile({ view, entry, posting, cancelling, onRender, onCancel }: {
  view: BodyView
  entry: BodyViewInfo
  posting: boolean
  cancelling: boolean
  onRender: () => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  const queued = entry.status === 'queued'
  return (
    <ViewRenderTile label={t(VIEW_LABELS[view])} url={entry.url} meta={entry.meta}
      height={VIEW_TILE_HEIGHT} running={entry.status === 'running'}
      failed={entry.status === 'failed'} error={entry.error} warning={entry.warning}
      disabled={posting || queued || !!entry.blocked} disabledReason={entry.blocked ? t(entry.blocked) : undefined}
      note={entry.pending_note ? t(entry.pending_note) : undefined}
      actionTitle={t('Renders only this dressed view anew (image jobs) — the model is meshed again only by its own Regenerate.')}
      onRender={onRender}
      status={queued ? (
        <div className="ga-face-actions-row">
          <span className="ga-hint">{t('Queued')} (#{entry.queue_position ?? '?'})</span>
          <button type="button" className="ga-btn ga-btn-sm" disabled={posting} aria-busy={cancelling || undefined}
            title={t('Removes this waiting run from the queue — nothing of it has started')}
            onClick={onCancel}>
            {cancelling ? t('Cancelling…') : t('Cancel')}
          </button>
        </div>
      ) : null} />
  )
}

function FitRow({ fit, busy, onRefit }: { fit: BodyFit; busy: boolean; onRefit: () => void }) {
  const { t } = useI18n()
  const st = FIT_STATUS[fit.status] || { dot: 'grey', label: fit.status }
  const tip = [fit.name, `${t(st.label)}${fit.error ? `: ${fit.error}` : ''}`,
    fit.fsig ? `fsig ${fit.fsig}` : '',
    fit.created_at ? formatDateTime(fit.created_at, clockSettings()) : ''].filter(Boolean).join('\n')
  return (
    <div className="ga-model3d-status-row ga-obody-line" title={tip}>
      <span className={`ga-model3d-status-dot ga-model3d-status-${st.dot}`} />
      <span className="ga-model3d-status-text">{fit.name} · {t(st.label)}</span>
      <button type="button" className="ga-btn ga-btn-sm ga-obody-mini" disabled={busy || fit.status === 'no_base_fit'}
        title={t('Fit this garment onto the outfit body anew (CPU, no hub job)')}
        onClick={onRefit}>{t('Re-fit')}</button>
    </div>
  )
}

const PAINTED_LABELS: Record<PaintedAction, string> = { generate: 'Generate', regenerate: 'Regenerate', delete: 'Delete' }

function paintedLabel(x: PaintedBody): string {
  return x.outfits.map((o) => o.name || o.signature).join(' · ') || x.worn_outfit?.name || x.texture_signature || x.key
}

function paintedDot(x: PaintedBody): string {
  if (x.status === 'failed') return 'red'
  if (x.status === 'running' || x.status === 'queued') return 'yellow'
  if (x.current && x.worn_outfit && !x.worn_outfit.model) return 'yellow'
  return x.painted ? 'green' : 'grey'
}

function PaintedBodies({ textures, posting, keptBodies, onRun, onCancel, onDelete }: {
  textures: PaintedBody[]
  posting: string
  keptBodies: number
  onRun: (key: string, kind: RunKind) => void
  onCancel: (key: string) => void
  onDelete: (tex: PaintedBody) => void
}) {
  const { t } = useI18n()
  const [selected, setSelected] = useState('')
  const [withGarments, setWithGarments] = useState(false)
  const tex = textures.find((x) => x.key === selected) ?? textures[0]
  const statusOf = (x: PaintedBody): string => {
    if (x.status === 'running') return x.run_kind === 'repaint' ? t('Painting…') : t('Building…')
    if (x.status === 'queued') return `${t('Queued')} (#${x.queue_position ?? '?'})`
    if (x.status === 'failed') return t('Failed')
    if (x.pending) return t('Worn outfit — dressed views missing')
    if (x.current && x.worn_outfit && !x.worn_outfit.model) return t('Outfit model not built yet')
    return x.painted ? t('Painted body stored') : t('No painted body stored')
  }
  if (!tex) return <div className="ga-hint">{t('No painted body yet.')}</div>
  const busy = tex.status === 'running' || tex.status === 'queued' || posting.startsWith(`${tex.key}:`)
  const blocked = tex.blocked || {}
  const reason = (action: PaintedAction): string => blocked[action] || ''
  // The artefact graph's verdict names the outfits it is kept for (server English with {outfits} / {size}).
  const gcText = (text: string): string => t(text)
    .replace('{outfits}', tex.gc?.outfits.join(', ') || t('an outfit'))
    .replace('{size}', formatBytes(tex.gc?.bytes) || '0 B')
  const worn = tex.worn_outfit
  const reasons = (['generate', 'regenerate', 'delete'] as PaintedAction[])
    .filter((a) => tex.current || a !== 'generate')
    // The kept reason of Delete is the verdict line below, not repeated here.
    .filter((a) => a !== 'delete' || (!!tex.gc && reason(a) !== tex.gc.reason))
    .map((a): [PaintedAction, string] => [a, reason(a)]).filter(([, r]) => !!r)
  const generateLabel = tex.pending || worn?.views_missing.length ? t('Generate') : t('Build outfit model')
  const generateTitle = reason('generate') ? t(reason('generate'))
    : worn?.views_missing.length
      ? t('Renders the worn outfit\'s missing dressed views ({views}, about {n} image job(s)), then builds its outfit model — a stored painted body of the same texture is reused (CPU, no hub job).')
        .replace('{views}', worn.views_missing.map((v) => t(VIEW_LABELS[v])).join(', '))
        .replace('{n}', String(worn.image_jobs))
      : t('Builds the worn outfit\'s model from its dressed views — the stored painted body is reused (CPU, no hub job).')
  const cancelling = posting === `${tex.key}:cancel:`
  // A failed run (a timeout included) offers Retry: the same run again.
  const retryKind: RunKind | null = tex.last_run && !tex.last_run.ok
    && (tex.last_run.kind === 'paint' || tex.last_run.kind === 'repaint') ? tex.last_run.kind : null
  const retryAction: PaintedAction = retryKind === 'paint' ? 'generate' : 'regenerate'
  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <div className="ga-obody-list" role="listbox" aria-label={t('Painted bodies')}>
          {textures.map((x) => (
            <button key={x.key} type="button" role="option" aria-selected={x === tex}
              className={`ga-obody-row${x === tex ? ' ga-obody-row--sel' : ''}`}
              title={[x.texture_signature || x.key, statusOf(x), x.dress_text].filter(Boolean).join('\n')}
              onClick={() => setSelected(x.key)}>
              <span className={`ga-model3d-status-dot ga-model3d-status-${paintedDot(x)}`} />
              <span className="ga-model3d-status-text">
                {x.current ? `${t('Current')} · ` : ''}{paintedLabel(x)}
                {x.pending ? ` · ${t('dressed views missing')}` : ''}
                {x.gc && !x.gc.kept ? ` · ${t('not needed any more')}` : ''}
              </span>
            </button>
          ))}
        </div>
        {keptBodies ? (
          <div className="ga-hint" title={t('Kept while their outfits can still be worn — switching back to the mesh mode reuses them without a hub job.')}>
            {t('Outfit bodies of the mesh mode kept: {n}').replace('{n}', String(keptBodies))}
          </div>
        ) : null}
      </div>
      <div className="ga-split-col">
        <div className="ga-face-actions-row">
          <span className="ga-fieldset-title" style={{ margin: 0 }}>
            {tex.current ? t('Current') : t('Painted body')} {tex.texture_signature || ''}
          </span>
          <span className="ga-hint">
            {statusOf(tex)}
            {tex.created_at && tex.status !== 'running' ? ` · ${formatDateTime(tex.created_at, clockSettings())}` : ''}
          </span>
          {tex.freshness ? <FreshnessBadge freshness={tex.freshness} compact /> : null}
          {tex.status === 'queued' ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={!!posting} aria-busy={cancelling || undefined}
              title={t('Removes this waiting run from the queue — nothing of it has started')}
              onClick={() => onCancel(tex.key)}>
              {cancelling ? t('Cancelling…') : t('Cancel')}
            </button>
          ) : null}
          {tex.current ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason('generate')}
              title={generateTitle} onClick={() => onRun(tex.key, 'paint')}>{generateLabel}</button>
          ) : null}
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason('regenerate')}
            title={reason('regenerate') ? t(reason('regenerate'))
              : t('Renders the dressed views anew (image jobs) for {outfit} and paints the body again (CPU, no hub job).')
                .replace('{outfit}', tex.outfits.find((o) => o.signature === tex.regenerate_from)?.name
                  || tex.regenerate_from || '')}
            onClick={() => onRun(tex.key, 'repaint')}>{t('Regenerate')}</button>
          {tex.gc ? (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy || !!reason('delete')}
              title={reason('delete') ? gcText(reason('delete'))
                : t('Deletes this painted body: its dressed views in the texture store and the painted model')}
              onClick={() => onDelete(tex)}>{t('Delete')}</button>
          ) : null}
        </div>
        {reasons.length ? (
          reasons.length > 1 && reasons.every(([, r]) => r === reasons[0][1])
            ? <div className="ga-hint" style={REASON_STYLE}>{t(reasons[0][1])}</div>
            : reasons.map(([a, r]) => (
              <div key={a} className="ga-hint" style={REASON_STYLE}>{t(PAINTED_LABELS[a])}: {t(r)}</div>
            ))
        ) : null}
        {tex.gc ? (
          <div className="ga-hint" style={tex.gc.kept ? REASON_STYLE : WARNING_STYLE}>
            {gcText(tex.gc.reason)}{tex.gc.free ? ` ${gcText(tex.gc.free)}` : ''}
          </div>
        ) : null}
        {tex.status === 'failed' && tex.error ? (
          <div className="ga-face-actions-row">
            <span className="ga-hint" style={ERROR_STYLE}>{t(tex.error)}</span>
            {retryKind ? (
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason(retryAction)}
                title={reason(retryAction) ? t(reason(retryAction)) : t('Starts the failed run again')}
                onClick={() => onRun(tex.key, retryKind)}>{t('Retry')}</button>
            ) : null}
          </div>
        ) : null}
        {tex.last_run && tex.status !== 'failed' ? (
          <div className="ga-hint" style={tex.last_run.ok ? undefined : ERROR_STYLE}>
            {t('Last run')}: {tex.last_run.kind === 'repaint' ? t('Regenerate') : t('Generate')}
            {' · '}{tex.last_run.ok ? t('done') : t('failed')}
          </div>
        ) : null}
        {tex.pending ? null : (() => {
          const shown = withGarments && tex.outfit_url ? tex.outfit_url : tex.url
          return (
            <>
              {tex.outfit_url ? (
                <label className="ga-hint" style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                  title={t('Shows the worn outfit\'s model with its own-mesh garments instead of the painted body alone')}>
                  <input type="checkbox" checked={withGarments} onChange={(e) => setWithGarments(e.target.checked)} />
                  {t('With garments')}
                </label>
              ) : null}
              {shown ? (
                <div className="ga-model3d-fit">
                  <Model3DViewer key={shown} url={shown} format="glb" height={460} previewTilt
                    freshness={shown === tex.url ? tex.freshness ?? undefined : undefined} />
                </div>
              ) : (
                <div className="ga-hint" style={{ ...EMPTY_TILE, height: 200, maxWidth: 440 }}>{t('No model stored')}</div>
              )}
            </>
          )
        })()}
        {tex.pending ? (
          <div className="ga-hint">
            {t('The worn outfit has no current dressed views yet — Generate renders them and builds its outfit model.')}
          </div>
        ) : (
          <div className="ga-hint" title={tex.dress_text}>
            {tex.texture_signature} · {tex.painted ? t('Painted body stored') : t('No painted body stored')}
            {tex.dress_text ? ` · ${tex.dress_text}` : ''}
          </div>
        )}
        <div style={{ maxWidth: 420 }}>
          {tex.pending ? null : <ViewTiles views={tex.views} meta={tex.image_meta} keyLabel={tex.texture_signature || tex.key} />}
        </div>
        <div>
          <div className="ga-fieldset-title" style={{ margin: '0 0 2px' }}>
            {tex.current ? t('Outfits on this body') : t('Used by')}
          </div>
          {tex.outfits.length ? tex.outfits.map((o) => (
            <div key={o.signature} className="ga-model3d-status-row ga-obody-line" title={o.signature}>
              <span className={`ga-model3d-status-dot ga-model3d-status-${o.has_model ? 'green' : 'grey'}`} />
              <span className="ga-model3d-status-text">
                {o.name || o.signature}{o.worn ? ` · ${t('worn')}` : ''}
                {o.has_model ? '' : ` · ${t('no outfit model yet')}`}
              </span>
            </div>
          )) : worn ? (
            <div className="ga-model3d-status-row ga-obody-line" title={worn.signature}>
              <span className="ga-model3d-status-dot ga-model3d-status-grey" />
              <span className="ga-model3d-status-text">
                {worn.name || worn.signature} · {t('worn')} · {t('no outfit model yet')}
              </span>
            </div>
          ) : <div className="ga-hint">{t('No outfit model stands on it')}</div>}
        </div>
      </div>
    </div>
  )
}

export function FieldOutfitBody({ character, refreshKey = '' }: { character: string; refreshKey?: string }) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, startPoll } = useOutfitBodies(character, refreshKey)
  const statusText = useStatusText()
  const [selected, setSelected] = useState('')
  const [orphansOpen, setOrphansOpen] = useState(false)
  // The clicked action until its request answered ("<body>:<kind>[:item]").
  const [posting, setPosting] = useState('')
  const [pendingDelete, setPendingDelete] = useState<OutfitBody | null>(null)
  const [pendingPainted, setPendingPainted] = useState<PaintedBody | null>(null)

  const runKey = useCallback(
    async (bodyKey: string, kind: RunKind, itemId = '') => {
      const key = `${bodyKey}:${kind}:${itemId}`
      if (posting) return
      setPosting(key)
      try {
        const d = await apiPost<{ started: boolean; position: number }>(
          `/characters/${enc}/outfit-bodies/${bodyKey}/${kind === 'views' ? 'generate-views' : kind}`,
          itemId ? { item_id: itemId } : {})
        if (!d.started) toast(`${t('Queued')} (#${d.position})`, 'info')
        startPoll(300)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        startPoll()
      } finally {
        setPosting('')
      }
    },
    [enc, posting, startPoll, t, toast],
  )
  const run = useCallback(
    (body: OutfitBody, kind: RunKind, itemId = '') => runKey(body.body_id, kind, itemId),
    [runKey],
  )

  // ONE dressed view of the body rendered anew (image jobs only).
  const renderView = useCallback(
    async (body: OutfitBody, view: BodyView) => {
      if (posting) return
      setPosting(`${body.body_id}:view:${view}`)
      try {
        const d = await apiPost<{ started: boolean; position: number }>(
          `/characters/${enc}/outfit-bodies/${body.body_id}/views/${view}/regenerate`, {})
        if (!d.started) toast(`${t('Queued')} (#${d.position})`, 'info')
        startPoll(300)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        startPoll()
      } finally {
        setPosting('')
      }
    },
    [enc, posting, startPoll, t, toast],
  )

  // The Cancel of one view's waiting run.
  const cancelView = useCallback(
    async (body: OutfitBody, view: BodyView) => {
      if (posting) return
      setPosting(`${body.body_id}:cancel:${view}`)
      try {
        await apiPost(`/characters/${enc}/outfit-bodies/${body.body_id}/cancel`, { view })
        toast(t('Waiting run cancelled'), 'success')
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setPosting('')
        startPoll(0)
      }
    },
    [enc, posting, startPoll, t, toast],
  )

  // The Cancel of a body's waiting run: its body id and the info on screen
  // when it answered — "Cancelled" shows until a newer info arrives.
  const [cancelled, setCancelled] = useState<{ bodyId: string; since: unknown } | null>(null)
  const infoRef = useRef(info)
  useEffect(() => { infoRef.current = info }, [info])
  const cancel = useCallback(
    async (body: OutfitBody | string) => {
      if (posting) return
      const bodyKey = typeof body === 'string' ? body : body.body_id
      setPosting(`${bodyKey}:cancel:`)
      try {
        await apiPost(`/characters/${enc}/outfit-bodies/${bodyKey}/cancel`, {})
        setCancelled({ bodyId: bodyKey, since: infoRef.current })
        toast(t('Waiting run cancelled'), 'success')
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setPosting('')
        startPoll(0)
      }
    },
    [enc, posting, startPoll, t, toast],
  )

  const remove = useCallback(async () => {
    const body = pendingDelete
    setPendingDelete(null)
    if (!body) return
    setPosting(`${body.body_id}:delete:`)
    try {
      const d = await apiPost<{ deleted_files: number; skipped: { key: string; why: string }[] }>(
        `/characters/${enc}/outfit-bodies/${body.body_id}/delete`, {})
      toast(d.skipped.length
        ? t('Deleted {n} file(s); {m} part(s) skipped while running').replace('{n}', String(d.deleted_files))
          .replace('{m}', String(d.skipped.length))
        : t('Deleted {n} file(s)').replace('{n}', String(d.deleted_files)), d.skipped.length ? 'info' : 'success')
      setSelected('')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting('')
      startPoll()
    }
  }, [enc, pendingDelete, startPoll, t, toast])

  // Delete of a painted body no outfit needs any more (the artefact graph's explicit collect).
  const removePainted = useCallback(async () => {
    const tex = pendingPainted
    setPendingPainted(null)
    if (!tex?.texture_signature) return
    setPosting(`${tex.key}:delete:`)
    try {
      const d = await apiPost<{ deleted_files: number; freed_bytes: number }>(
        `/characters/${enc}/outfit-bodies/${tex.texture_signature}/delete`, {})
      toast(t('Deleted {n} file(s)').replace('{n}', String(d.deleted_files)), 'success')
    } catch (e) {
      toast(t('Error') + ': ' + t((e as Error).message), 'error')
    } finally {
      setPosting('')
      startPoll()
    }
  }, [enc, pendingPainted, startPoll, t, toast])

  if (!info) return <div className="ga-obody"><div className="ga-hint">{t('Loading…')}</div></div>
  if (!info.humanoid) {
    return <div className="ga-obody"><div className="ga-hint">{t('The base body is for humanoid characters only.')}</div></div>
  }
  if (!info.pipeline) {
    return (
      <div className="ga-obody">
        <div className="ga-hint">{t('Outfit bodies need the base-body pipeline — switch it on in the Base body tab.')}</div>
      </div>
    )
  }
  if (info.mode !== 'mesh') {
    return (
      <div className="ga-split-col ga-obody">
        <div className="ga-hint">
          {t('Retexture mode: own-mesh garments sit on the base body with the other pieces painted on — no outfit body is meshed. The painted bodies:')}
        </div>
        {info.textures.length ? (
          <PaintedBodies textures={info.textures} posting={posting}
            keptBodies={info.bodies.filter((b) => b.status !== 'missing').length}
            onRun={(key, kind) => { void runKey(key, kind) }} onCancel={(key) => { void cancel(key) }}
            onDelete={setPendingPainted} />
        ) : <div className="ga-hint">{t('No painted body yet.')}</div>}
        <ConfirmDialog
          open={!!pendingPainted}
          title={t('Delete painted body')}
          message={t('Deletes the painted body {tsig} ({size}): its dressed views in the texture store and the painted model. Outfit models built on it keep working; a later build of such an outfit paints a new one.')
            .replace('{tsig}', pendingPainted?.texture_signature || '')
            .replace('{size}', formatBytes(pendingPainted?.gc?.bytes) || '0 B')}
          confirmLabel={t('Delete')}
          danger
          onConfirm={() => { void removePainted() }}
          onClose={() => setPendingPainted(null)}
        />
      </div>
    )
  }
  if (!info.bodies.length) {
    return (
      <div className="ga-obody">
        <div className="ga-hint">
          {t('No outfit body yet — one is meshed and rigged when an outfit with painted pieces is built (Pose tab).')}
        </div>
      </div>
    )
  }

  const body = info.bodies.find((b) => b.body_id === selected) ?? info.bodies[0]
  const cancelling = posting === `${body.body_id}:cancel:`
  const shownCancelled = cancelled?.bodyId === body.body_id && cancelled.since === info
  const busy = body.status === 'running' || body.status === 'queued' || posting.startsWith(`${body.body_id}:`)
  // Why each action cannot start (the server's reasons, the lock of a running/queued run included).
  const blocked = body.blocked || {}
  const reason = (action: BodyAction): string => blocked[action] || ''
  const regular = info.bodies.filter((b) => !b.orphaned)
  const orphans = info.bodies.filter((b) => b.orphaned)
  const showOrphans = orphansOpen || !regular.length || !!body.orphaned
  const worn = body.worn_outfit
  const viewsPending = !!worn?.views_missing.length
  const waiting = info.queue.waiting.length
  const fitsCount = body.fits.length
  const deleteMessage = t('Deletes the outfit body with its {f} fit(s) and the {o} outfit model(s) built on it — nothing of it stays. Its dressed views stay; the next build of such an outfit meshes and rigs the body again (hub jobs).')
    .replace('{f}', String(pendingDelete?.fits.length ?? 0)).replace('{o}', String(pendingDelete?.outfits.length ?? 0))

  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <div className="ga-obody-list" role="listbox" aria-label={t('Outfit bodies')}>
          {[...regular, ...(showOrphans ? orphans : [])].map((b) => (
            <button key={b.body_id} type="button" role="option" aria-selected={b === body}
              className={`ga-obody-row${b === body ? ' ga-obody-row--sel' : ''}`}
              title={[b.body_id, statusText(b), b.freshness?.reason, b.dress_text].filter(Boolean).join('\n')}
              onClick={() => setSelected(b.body_id)}>
              <span className={`ga-model3d-status-dot ga-model3d-status-${dotOf(b)}`} />
              <span className="ga-model3d-status-text">
                {isCurrent(b) ? `${t('Current')} · ${bodyLabel(b)}`
                  : b.outfits.length ? `${t('Used by')}: ${bodyLabel(b)}` : bodyLabel(b)}
                {b.orphaned ? ` · ${t('orphaned')}` : b.status === 'missing' && b.worn_outfit?.views_missing.length
                  ? ` · ${t('dressed views missing')}` : ''}
              </span>
            </button>
          ))}
        </div>
        {orphans.length && regular.length ? (
          <button type="button" className="ga-btn ga-btn-sm" aria-expanded={showOrphans}
            title={t('Bodies never built that no outfit stands on any more — kept while an outfit names their texture; Delete removes one.')}
            onClick={() => setOrphansOpen((v) => !v)}>
            {showOrphans ? t('Hide orphaned bodies') : t('Show orphaned bodies')} ({orphans.length})
          </button>
        ) : null}
        {worn && viewsPending ? (
          <div>
            <div className="ga-face-actions-row">
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason('views')}
                title={reason('views') ? t(reason('views')) : t('Renders the worn outfit\'s missing dressed views ({views}) — about {n} image job(s): one edit for the front, a draft and a fit for each other view; a view the texture store holds is copied without a job. Own-mesh pieces run their garment chain first. The body is meshed only by its own Regenerate.')
                  .replace('{views}', worn.views_missing.map((v) => t(VIEW_LABELS[v])).join(', '))
                  .replace('{n}', String(worn.image_jobs))}
                onClick={() => run(body, 'views')}>{t('Generate views')}</button>
              <span className="ga-hint">{t('Worn outfit — dressed views missing')}</span>
            </div>
            <ActionReasons reasons={[['views', reason('views')]]} />
          </div>
        ) : null}
        {body.view_info ? (
          <div className="ga-view-stack">
            {BODY_VIEWS.filter((view) => !!body.view_info?.[view]).map((view) => (
              <BodyViewTile key={view} view={view} entry={body.view_info?.[view] as BodyViewInfo}
                posting={!!posting}
                cancelling={posting === `${body.body_id}:cancel:${view}`}
                onRender={() => { void renderView(body, view) }}
                onCancel={() => { void cancelView(body, view) }} />
            ))}
          </div>
        ) : <ViewTiles views={body.views} meta={body.image_meta} keyLabel={body.body_id} />}
        {(body.view_warnings || []).map((w) => (
          <div key={w} className="ga-hint" style={WARNING_STYLE} title={w}>{w}</div>
        ))}
      </div>

      <div className="ga-split-col">
        <div className="ga-face-actions-row">
          <span className="ga-fieldset-title" style={{ margin: 0 }}>
            {isCurrent(body) ? `${t('Current')} · ` : ''}{t('Outfit body')} {body.body_id}
          </span>
          <span className="ga-hint">
            {shownCancelled ? t('Cancelled') : statusText(body)}
            {body.created_at && body.status !== 'running' ? ` · ${formatDateTime(body.created_at, clockSettings())}` : ''}
          </span>
          {body.status === 'queued' && !shownCancelled ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={!!posting}
              aria-busy={cancelling || undefined}
              title={t('Removes this waiting run from the queue — nothing of it has started')}
              onClick={() => { void cancel(body) }}>
              {cancelling ? t('Cancelling…') : t('Cancel')}
            </button>
          ) : null}
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason('regenerate')}
            title={reason('regenerate') ? t(reason('regenerate'))
              : t('Meshes and rigs this body anew from its dressed views (mesh, face, rig, normalize, extension rig, capsules — hub jobs).')}
            onClick={() => run(body, 'regenerate')}>{t('Regenerate')}</button>
          {body.freshness ? <FreshnessBadge freshness={body.freshness} compact /> : null}
          {info.generation_running && body.status === 'running' ? (
            <span className="ga-hint" title={t('Another 3D run of this character holds the generation slot; this run starts when it ends.')}>
              {t('waits for the running 3D run')}
            </span>
          ) : null}
        </div>
        <ActionReasons reasons={[['regenerate', reason('regenerate')]]} />
        {body.orphaned ? (
          <div className="ga-hint" style={WARNING_STYLE}>
            {t('Orphaned — no outfit stands on it')}. {t('It was never built and no outfit stands on its dressed views any more; Delete removes it.')}
          </div>
        ) : null}
        {body.status === 'failed' && body.error ? <div className="ga-hint" style={ERROR_STYLE}>{body.error}</div> : null}
        <div className="ga-basebody-model">
          {body.url ? (
            <div className="ga-model3d-fit">
              <Model3DViewer key={body.url} url={body.url} format="glb" height={460} previewTilt
                freshness={body.freshness}
                statusPanel={body.steps.length ? <ModelSteps steps={body.steps} /> : undefined}
                collision={body.collision} />
            </div>
          ) : (
            <div className="ga-hint" style={{ ...EMPTY_TILE, height: 200, maxWidth: 440 }}>{t('No model stored')}</div>
          )}
          <div className="ga-basebody-side">
            <div className="ga-face-actions-row">
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason('rerig')}
                title={reason('rerig') ? t(reason('rerig')) : t('Rigs the retained unrigged mesh anew (rig chain, hub job).')}
                onClick={() => run(body, 'rerig')}>{t('Re-rig')}</button>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !!reason('refit')}
                title={reason('refit') ? t(reason('refit'))
                  : t('Fits every garment on this body anew from its base fit (CPU, no hub job).')}
                onClick={() => run(body, 'refit')}>{t('Re-fit all')}</button>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy || !!reason('delete')}
                title={reason('delete') ? t(reason('delete'))
                  : t('Delete the body with its fits and the outfit models built on it')}
                onClick={() => setPendingDelete(body)}>{t('Delete')}</button>
            </div>
            <ActionReasons reasons={[['rerig', reason('rerig')], ['refit', reason('refit')],
              ['delete', reason('delete')]]} />
            {body.last_run ? (
              <div className="ga-hint" style={body.last_run.ok ? undefined : ERROR_STYLE}
                title={[body.last_run.error, ...(body.last_run.detail?.failed || []).map((f) => `${f.name}: ${f.error}`)]
                  .filter(Boolean).join('\n')}>
                {t('Last run')}: {body.last_run.kind === 'view' && body.last_run.view
                  ? `${t(VIEW_LABELS[body.last_run.view])} · ${t('Regenerate')}`
                  : t(body.last_run.kind === 'rerig' ? 'Re-rig' : body.last_run.kind === 'refit' ? 'Re-fit'
                    : body.last_run.kind === 'views' ? 'Generate views' : 'Regenerate')}
                {' · '}{body.last_run.ok ? t('done') : t('failed')}
                {body.last_run.error ? ` · ${body.last_run.error}` : ''}
              </div>
            ) : null}
            {waiting ? (
              <div className="ga-hint">{t('Waiting runs')}: {waiting}</div>
            ) : null}

            <div>
              <div className="ga-fieldset-title" style={{ margin: '0 0 2px' }}>
                {isCurrent(body) ? t('Outfits on this body') : t('Used by')}
              </div>
              {body.outfits.length ? body.outfits.map((o) => (
                <div key={o.signature}>
                  <div className="ga-model3d-status-row ga-obody-line"
                    title={[o.signature, o.stale_reason === 'outfit_body' ? t('Built on an older outfit body')
                      : o.stale_reason === 'body_mode' ? t('Built for the other outfit body mode') : ''].filter(Boolean).join('\n')}>
                    <span className={`ga-model3d-status-dot ga-model3d-status-${o.stale_reason ? 'yellow' : 'green'}`} />
                    <span className="ga-model3d-status-text">
                      {o.name || o.signature}{o.worn ? ` · ${t('worn')}` : ''}{o.stale_reason ? ` · ${t('outdated')}` : ''}
                    </span>
                  </div>
                  {(o.missing_mesh_items || []).map((m) => (
                    <div key={m.item_id} className="ga-hint" style={WARNING_STYLE}>
                      {meshNotReadyText(t, m.name, m.reason)}
                    </div>
                  ))}
                </div>
              )) : worn ? (
                <div className="ga-model3d-status-row ga-obody-line" title={worn.signature}>
                  <span className="ga-model3d-status-dot ga-model3d-status-grey" />
                  <span className="ga-model3d-status-text">
                    {worn.name || worn.signature} · {t('worn')} · {t('no outfit model yet')}
                  </span>
                </div>
              ) : <div className="ga-hint">{t('No outfit model stands on it')}</div>}
            </div>

            {body.dress_text ? (
              <div>
                <div className="ga-fieldset-title" style={{ margin: '0 0 2px' }}>{t('Painted pieces')}</div>
                <div className="ga-hint ga-obody-clamp" title={body.dress_text}>{body.dress_text}</div>
              </div>
            ) : null}

            <div>
              <div className="ga-fieldset-title" style={{ margin: '0 0 2px' }}>{t('Garments on this body')}</div>
              {fitsCount ? body.fits.map((f) => (
                <FitRow key={f.item_id} fit={f} busy={busy || !body.url} onRefit={() => run(body, 'refit', f.item_id)} />
              )) : <div className="ga-hint">{t('No own-mesh garment or hair on it')}</div>}
            </div>
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={!!pendingDelete}
        title={t('Delete outfit body')}
        message={deleteMessage}
        confirmLabel={t('Delete')}
        danger
        onConfirm={() => { void remove() }}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  )
}
