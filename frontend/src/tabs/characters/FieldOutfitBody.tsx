/**
 * FieldOutfitBody — the Outfit body tab (template tab `outfit_body_tab`,
 * special section `outfit_body`, right after Base body; plan
 * docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 4). The
 * mode switch `outfit_body_mode` is the template field above this panel.
 *
 * Mesh mode: every combination of painted pieces has its own meshed and
 * rigged outfit body. Layout like the Base body tab, three columns on one
 * screen: the bodies (one line each) and the selected body's views stacked
 * small on the left (a click enlarges one); its 3D preview with the step
 * checklist and the collision capsule toggle in the middle; on the right its
 * actions, the outfits standing on it, its dress text and the garments
 * fitted onto it (one line each, details on hover, Re-fit per garment).
 * Retexture mode: one line saying so and the painted bodies read-only.
 *
 * Backend (app/routes/outfit_bodies.py, app/core/outfit_bodies.py):
 * GET /characters/{n}/outfit-bodies (polled while a run waits or works),
 * POST …/{body}/regenerate | rerig | refit {item_id?} — 202 with the queue
 * place, a run queues behind the character's running 3D run, never 409 for
 * that; POST …/{body}/cancel — takes the body's waiting run out of the queue
 * (409 once it has started); POST …/{body}/delete — the body and its chain
 * through the artefact graph (409 while a run is on it).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { FreshnessBadge } from './FreshnessBadge'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { RefImage } from './RefImage'
import { BODY_VIEWS, useOutfitBodies } from './useOutfitBodies'
import type { BodyFit, BodyView, OutfitBody, PaintedBody, RunKind } from './useOutfitBodies'

const TILE_HEIGHT = 112

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
        : body.run_kind === 'build' ? t('Building…') : t('Meshing…')
    }
    if (body.status === 'queued') return `${t('Queued')} (#${body.queue_position ?? '?'})`
    if (body.status === 'failed') return t('Failed')
    if (body.status === 'missing') return t('Not built')
    if (body.status === 'unrigged') return t('Static mesh without a rig')
    return t('Ready')
  }
}

/** Short label of a body: the outfits standing on it, else its id. */
function bodyLabel(body: OutfitBody): string {
  return body.outfits.map((o) => o.name || o.signature).join(' · ') || body.body_id
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

function PaintedBodies({ textures }: { textures: PaintedBody[] }) {
  const { t } = useI18n()
  const [selected, setSelected] = useState('')
  const tex = textures.find((x) => x.texture_signature === selected) ?? textures[0]
  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <div className="ga-obody-list">
          {textures.map((x) => (
            <button key={x.texture_signature} type="button"
              className={`ga-obody-row${x === tex ? ' ga-obody-row--sel' : ''}`}
              title={[x.texture_signature, x.dress_text].filter(Boolean).join('\n')}
              onClick={() => setSelected(x.texture_signature)}>
              <span className={`ga-model3d-status-dot ga-model3d-status-${x.painted ? 'green' : 'grey'}`} />
              <span className="ga-model3d-status-text">
                {x.outfits.map((o) => o.name || o.signature).join(' · ') || x.texture_signature}
                {x.outfits.some((o) => o.worn) ? ` · ${t('worn')}` : ''}
              </span>
            </button>
          ))}
        </div>
      </div>
      <div className="ga-split-col">
        {tex ? (
          <>
            <div className="ga-hint" title={tex.dress_text}>
              {tex.texture_signature} · {tex.painted ? t('Painted body stored') : t('No painted body stored')}
              {tex.dress_text ? ` · ${tex.dress_text}` : ''}
            </div>
            <div style={{ maxWidth: 420 }}>
              <ViewTiles views={tex.views} meta={tex.image_meta} keyLabel={tex.texture_signature} />
            </div>
          </>
        ) : null}
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
  // The clicked action until its request answered ("<body>:<kind>[:item]").
  const [posting, setPosting] = useState('')
  const [pendingDelete, setPendingDelete] = useState<OutfitBody | null>(null)

  const run = useCallback(
    async (body: OutfitBody, kind: RunKind, itemId = '') => {
      const key = `${body.body_id}:${kind}:${itemId}`
      if (posting) return
      setPosting(key)
      try {
        const d = await apiPost<{ started: boolean; position: number }>(
          `/characters/${enc}/outfit-bodies/${body.body_id}/${kind}`, itemId ? { item_id: itemId } : {})
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

  // The Cancel of a body's waiting run: its body id and the info on screen
  // when it answered — "Cancelled" shows until a newer info arrives.
  const [cancelled, setCancelled] = useState<{ bodyId: string; since: unknown } | null>(null)
  const infoRef = useRef(info)
  useEffect(() => { infoRef.current = info }, [info])
  const cancel = useCallback(
    async (body: OutfitBody) => {
      if (posting) return
      setPosting(`${body.body_id}:cancel:`)
      try {
        await apiPost(`/characters/${enc}/outfit-bodies/${body.body_id}/cancel`, {})
        setCancelled({ bodyId: body.body_id, since: infoRef.current })
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
        {info.textures.length ? <PaintedBodies textures={info.textures} />
          : <div className="ga-hint">{t('No painted body yet.')}</div>}
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
  const waiting = info.queue.waiting.length
  const fitsCount = body.fits.length
  const deleteMessage = t('Deletes the outfit body with its {f} fit(s) and the {o} outfit model(s) built on it — nothing of it stays. Its dressed views stay; the next build of such an outfit meshes and rigs the body again (hub jobs).')
    .replace('{f}', String(pendingDelete?.fits.length ?? 0)).replace('{o}', String(pendingDelete?.outfits.length ?? 0))

  return (
    <div className="ga-split ga-split-views">
      <div className="ga-split-col">
        <div className="ga-obody-list" role="listbox" aria-label={t('Outfit bodies')}>
          {info.bodies.map((b) => (
            <button key={b.body_id} type="button" role="option" aria-selected={b === body}
              className={`ga-obody-row${b === body ? ' ga-obody-row--sel' : ''}`}
              title={[b.body_id, statusText(b), b.freshness?.reason, b.dress_text].filter(Boolean).join('\n')}
              onClick={() => setSelected(b.body_id)}>
              <span className={`ga-model3d-status-dot ga-model3d-status-${dotOf(b)}`} />
              <span className="ga-model3d-status-text">
                {bodyLabel(b)}{b.outfits.some((o) => o.worn) ? ` · ${t('worn')}` : ''}
              </span>
            </button>
          ))}
        </div>
        <ViewTiles views={body.views} meta={body.image_meta} keyLabel={body.body_id} />
        {(body.view_warnings || []).map((w) => (
          <div key={w} className="ga-hint" style={WARNING_STYLE} title={w}>{w}</div>
        ))}
      </div>

      <div className="ga-split-col">
        <div className="ga-face-actions-row">
          <span className="ga-fieldset-title" style={{ margin: 0 }}>{t('Outfit body')} {body.body_id}</span>
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
          {body.freshness ? <FreshnessBadge freshness={body.freshness} compact /> : null}
          {info.generation_running && body.status === 'running' ? (
            <span className="ga-hint" title={t('Another 3D run of this character holds the generation slot; this run starts when it ends.')}>
              {t('waits for the running 3D run')}
            </span>
          ) : null}
        </div>
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
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !body.can_regenerate}
                title={body.can_regenerate
                  ? t('Meshes and rigs this body anew from its dressed views (mesh, face, rig, normalize, extension rig, capsules — hub jobs).')
                  : t('No outfit stands on this body\'s dressed views any more — nothing to mesh from.')}
                onClick={() => run(body, 'regenerate')}>{t('Regenerate')}</button>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !body.can_rerig}
                title={body.can_rerig ? t('Rigs the retained unrigged mesh anew (rig chain, hub job).')
                  : t('No retained unrigged mesh — regenerate the body.')}
                onClick={() => run(body, 'rerig')}>{t('Re-rig')}</button>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !body.url || !fitsCount}
                title={t('Fits every garment on this body anew from its base fit (CPU, no hub job).')}
                onClick={() => run(body, 'refit')}>{t('Re-fit all')}</button>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy}
                title={t('Delete the body with its fits and the outfit models built on it')}
                onClick={() => setPendingDelete(body)}>{t('Delete')}</button>
            </div>
            {body.last_run ? (
              <div className="ga-hint" style={body.last_run.ok ? undefined : ERROR_STYLE}
                title={[body.last_run.error, ...(body.last_run.detail?.failed || []).map((f) => `${f.name}: ${f.error}`)]
                  .filter(Boolean).join('\n')}>
                {t('Last run')}: {t(body.last_run.kind === 'rerig' ? 'Re-rig' : body.last_run.kind === 'refit' ? 'Re-fit' : 'Regenerate')}
                {' · '}{body.last_run.ok ? t('done') : t('failed')}
                {body.last_run.error ? ` · ${body.last_run.error}` : ''}
              </div>
            ) : null}
            {waiting ? (
              <div className="ga-hint">{t('Waiting runs')}: {waiting}</div>
            ) : null}

            <div>
              <div className="ga-fieldset-title" style={{ margin: '0 0 2px' }}>{t('Outfits on this body')}</div>
              {body.outfits.length ? body.outfits.map((o) => (
                <div key={o.signature} className="ga-model3d-status-row ga-obody-line"
                  title={[o.signature, o.stale_reason === 'outfit_body' ? t('Built on an older outfit body')
                    : o.stale_reason === 'body_mode' ? t('Built for the other outfit body mode') : ''].filter(Boolean).join('\n')}>
                  <span className={`ga-model3d-status-dot ga-model3d-status-${o.stale_reason ? 'yellow' : 'green'}`} />
                  <span className="ga-model3d-status-text">
                    {o.name || o.signature}{o.worn ? ` · ${t('worn')}` : ''}{o.stale_reason ? ` · ${t('outdated')}` : ''}
                  </span>
                </div>
              )) : <div className="ga-hint">{t('No outfit model stands on it')}</div>}
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
