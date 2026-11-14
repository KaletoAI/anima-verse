/**
 * GarmentMeshView — the Mesh row's 3D view of an own-mesh clothing piece (Ruling A48a).
 *
 * `GarmentMeshTiles`: the accepted mesh as a small still tile (a click opens the viewer, the way a small image
 * enlarges), "Built <time>" and its triangle count under it, and beside it one tile per refused attempt of the
 * step's last run — with the same viewer — or, for an attempt that failed outright, a slim placeholder with the
 * error (no mesh was kept).
 *
 * `GarmentMeshViewer`: the shared viewer (`Model3DViewer`; drag turns the model, Shift+drag moves the view,
 * `lib/modelTurn.ts`) in a dialog of its own, its switches compact beside it:
 * - Prepared / Raw: the decimated mesh the fit takes, or the generator's output.
 * - Body: the character's base body as a translucent ghost, placed as the fit places the piece.
 * - Inside the body: the faces whose centres lie inside that body, in red, and their share of the area as a
 *   number. The server computes it once per mesh and body (`GET …/mesh/{which}/body`) and caches it; the switches
 *   change only what is drawn.
 * Nothing here spends a job.
 */
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useClockSettings } from '../../lib/clockFormat'
import { Model3DViewer } from './Model3DViewer'
import type { ViewerCompanion } from './Model3DViewer'
import { stampLabel } from './freshnessText'
import { meshSnapshot } from './meshSnapshot'
import type { GarmentMeshAttempt, GarmentMeshBodyView, GarmentMeshFile, GarmentMeshView } from './useGarment'

const TILE_W = 84
const TILE_H = 112

type Which = 'prepared' | 'raw'

/** One thing the viewer can show: the accepted mesh or a refused attempt, each with its prepared and raw file. */
export interface MeshSource {
  id: string
  label: string
  prepared: GarmentMeshFile | null
  raw: GarmentMeshFile | null
  builtAt: string | null
  refused: boolean
  /** Why it was refused (plain words, the gate's reasons). */
  note: string
}

/** The sources of the Mesh row: the accepted mesh first, then every refused attempt that kept a file. */
function meshSources(view: GarmentMeshView | undefined, builtAt: string | null,
  t: (s: string) => string): MeshSource[] {
  if (!view) return []
  const out: MeshSource[] = []
  if (view.prepared || view.raw) {
    out.push({ id: 'accepted', label: view.prepared ? t('Accepted mesh') : t('Raw mesh'), prepared: view.prepared,
      raw: view.raw, builtAt, refused: !view.prepared, note: '' })
  }
  for (const a of view.attempts) {
    if (!a.prepared && !a.raw) continue
    out.push({ id: `attempt-${a.attempt}`, label: `${t('Attempt')} ${a.attempt} · ${t('Refused')}`,
      prepared: a.prepared, raw: a.raw, builtAt, refused: true, note: attemptNote(a, t) })
  }
  return out
}

function attemptNote(a: GarmentMeshAttempt, t: (s: string) => string): string {
  return [
    a.largest_component_share != null
      ? `${t('Largest part')} ${(a.largest_component_share * 100).toFixed(1)} %` : '',
    ...(a.reasons || []),
    a.error && !(a.reasons || []).includes(a.error) ? a.error : '',
  ].filter(Boolean).join('\n')
}

function trisText(n: number | null | undefined): string {
  return n != null ? `${n.toLocaleString()} △` : ''
}

/** A still picture of one mesh (meshSnapshot) — a click opens the viewer. */
function MeshTile({ source, onOpen }: { source: MeshSource; onOpen: () => void }) {
  const { t } = useI18n()
  useClockSettings()
  const file = source.prepared || source.raw
  const url = file?.url || ''
  const [shot, setShot] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!url) return
    let live = true
    setFailed(false)
    meshSnapshot(url, TILE_W, TILE_H).then((s) => { if (live) setShot(s) }).catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [url])
  if (!file) return null
  const built = stampLabel(source.builtAt)
  const colour = source.refused ? 'var(--danger, #f85149)' : 'var(--success, #3fb950)'
  const title = [source.label, source.note, `${t('Triangles')} ${file.tris?.toLocaleString() ?? '–'}`,
    built ? `${t('Built')} ${built}` : '', t('Click to open the 3D view')].filter(Boolean).join('\n')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, width: TILE_W }}>
      <button type="button" onClick={onOpen} title={title} aria-label={`${t('Open the 3D view')} · ${source.label}`}
        style={{ width: TILE_W, height: TILE_H, padding: 0, cursor: 'zoom-in', borderRadius: 4,
          border: `1px solid ${colour}`, background: 'rgba(255,255,255,0.04)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', overflow: 'hidden', position: 'relative' }}>
        {shot ? <img src={shot} alt={source.label} style={{ width: TILE_W, height: TILE_H, objectFit: 'contain' }} />
          : <span className="ga-hint" style={{ fontSize: '0.7em' }}>{failed ? t('No preview') : t('Loading…')}</span>}
        <span aria-hidden style={{ position: 'absolute', top: 2, right: 3, fontSize: 10, opacity: 0.8 }}>3D</span>
      </button>
      <span className="ga-hint" style={{ fontSize: '0.7em', textAlign: 'center', lineHeight: 1.2 }} title={title}>
        {source.refused && source.id !== 'accepted' ? `${t('Attempt')} ${source.id.split('-')[1]} · ${t('Refused')}`
          : built ? `${t('Built')} ${built}` : source.label}
        <br />{trisText(file.tris)}
      </span>
    </div>
  )
}

/** The Mesh row's tiles: the accepted mesh, then each refused attempt (a failed one as a slim placeholder). */
export function GarmentMeshTiles({ view, builtAt, pieceName }: {
  view: GarmentMeshView | undefined
  builtAt: string | null
  pieceName: string
}) {
  const { t } = useI18n()
  const sources = useMemo(() => meshSources(view, builtAt, t), [view, builtAt, t])
  const [open, setOpen] = useState<string | null>(null)
  if (!view) return null
  const failed = view.attempts.filter((a) => !a.prepared && !a.raw)
  if (!sources.length && !failed.length) return null
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start', flexBasis: '100%' }}>
      {sources.map((s) => <MeshTile key={s.id} source={s} onOpen={() => setOpen(s.id)} />)}
      {failed.map((a) => (
        <div key={`failed-${a.attempt}`} className="ga-step-grid-empty" style={{ width: TILE_W, height: TILE_H }}
          title={[`${t('Attempt')} ${a.attempt} · ${t('Failed')}`, attemptNote(a, t), t('No mesh was kept')]
            .filter(Boolean).join('\n')}>
          {`${t('Attempt')} ${a.attempt} · ${t('Failed')}`}
        </div>
      ))}
      {open ? (
        <GarmentMeshViewer sources={sources} initial={open} pieceName={pieceName} onClose={() => setOpen(null)} />
      ) : null}
    </div>
  )
}

const SWITCH_ROW = { display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' } as const

/** The larger viewer (a dialog over the piece dialog) with its switches beside it. */
export function GarmentMeshViewer({ sources, initial, pieceName, onClose, initialWhich = 'prepared',
  initialBody = false, initialInside = false }: {
  sources: MeshSource[]
  initial: string
  pieceName: string
  onClose: () => void
  initialWhich?: Which
  initialBody?: boolean
  initialInside?: boolean
}) {
  const { t } = useI18n()
  useClockSettings()
  const [sourceId, setSourceId] = useState(initial)
  const source = sources.find((s) => s.id === sourceId) || sources[0]
  const [which, setWhich] = useState<Which>(initialWhich)
  const shown: Which = source?.[which] ? which : (which === 'prepared' ? 'raw' : 'prepared')
  const file = source?.[shown] || null
  const [bodyOn, setBodyOn] = useState(initialBody)
  const [insideOn, setInsideOn] = useState(initialInside)
  const [view, setView] = useState<GarmentMeshBodyView | null>(null)
  const [viewError, setViewError] = useState('')
  const [companionState, setCompanionState] = useState<Record<string, string>>({})

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); onClose() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const bodyUrl = file?.body_url || ''
  useEffect(() => {
    setView(null)
    setViewError('')
    setCompanionState({})
    if (!bodyUrl) return
    let live = true
    apiGet<GarmentMeshBodyView>(bodyUrl)
      .then((v) => { if (live) setView(v) })
      .catch((e: Error) => { if (live) setViewError(e.message || t('The body view failed')) })
    return () => { live = false }
  }, [bodyUrl, t])

  const companions: ViewerCompanion[] = []
  if (view) {
    companions.push({ key: `ghost:${view.key}`, url: view.ghost_url, style: 'ghost', visible: bodyOn })
    if (view.inside_url) companions.push({ key: `inside:${view.key}`, url: view.inside_url, style: 'mark', visible: insideOn })
  }
  const loadingBody = !view && !viewError
  const ghostState = view ? companionState[`ghost:${view.key}`] : ''
  const insideState = view?.inside_url ? companionState[`inside:${view.key}`] : ''
  const built = stampLabel(source?.builtAt)
  const pct = (v: number) => `${(v * 100).toFixed(1)} %`
  const shareTitle = view ? [
    t('Share of the mesh area whose faces lie inside the base body, placed as the fit places the piece (before the fit pushes it out).'),
    `${view.inside_faces.toLocaleString()} / ${view.faces.toLocaleString()} ${t('faces')} (${pct(view.face_share)})`,
  ].join('\n') : ''

  if (!source || !file) return null
  return createPortal(
    <div className="ga-modal-backdrop" style={{ zIndex: 1100 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal ga-garment-dialog" role="dialog" aria-modal="true"
        aria-label={`${t('Mesh')} · ${pieceName}`} style={{ maxWidth: 980 }}>
        <div className="ga-modal-header ga-garment-dialog-head">
          <span className="ga-garment-dialog-title">{`${t('Mesh')} · ${pieceName} · ${source.label}`}</span>
          <button type="button" className="ga-btn ga-btn-sm" style={{ marginLeft: 'auto' }} onClick={onClose}
            aria-label={t('Close')}>{t('Close')}</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 210px', gap: 10 }}>
          <Model3DViewer key={file.url} url={file.url} format="glb" height={520} builtAt={source.builtAt}
            companions={companions}
            onCompanionState={(key, state) => setCompanionState((prev) => ({ ...prev, [key]: state }))} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: '0.85em', minWidth: 0 }}>
            {sources.length > 1 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {sources.map((s) => (
                  <button key={s.id} type="button" title={s.note || undefined}
                    className={`ga-btn ga-btn-sm${s.id === source.id ? ' ga-btn-primary' : ''}`}
                    aria-pressed={s.id === source.id} onClick={() => setSourceId(s.id)}>
                    {s.label}
                  </button>
                ))}
              </div>
            ) : null}
            <div role="group" aria-label={t('Mesh file')} style={{ display: 'flex', gap: 3 }}>
              {(['prepared', 'raw'] as Which[]).map((w) => (
                <button key={w} type="button" disabled={!source[w]}
                  className={`ga-btn ga-btn-sm${shown === w ? ' ga-btn-primary' : ''}`} aria-pressed={shown === w}
                  title={w === 'prepared' ? t('The decimated mesh the fit takes') : t('The mesh as the generator delivered it')}
                  onClick={() => setWhich(w)}>
                  {w === 'prepared' ? t('Prepared') : t('Raw')}
                </button>
              ))}
            </div>
            <label style={SWITCH_ROW} title={t('The base body as a translucent ghost, placed as the fit places the piece')}>
              <input type="checkbox" checked={bodyOn} disabled={!view} onChange={(e) => setBodyOn(e.target.checked)} />
              {t('Body')}
              {bodyOn && ghostState === 'loading' ? <span className="ga-hint">{t('Loading…')}</span> : null}
            </label>
            <label style={SWITCH_ROW} title={t('Faces whose centres lie inside the base body, in red')}>
              <input type="checkbox" checked={insideOn} disabled={!view?.inside_url}
                onChange={(e) => setInsideOn(e.target.checked)} />
              <span style={{ color: 'var(--danger, #f85149)' }}>■</span>
              {t('Inside the body')}
              {insideOn && insideState === 'loading' ? <span className="ga-hint">{t('Loading…')}</span> : null}
            </label>
            {view ? (
              <div title={shareTitle}>
                <div className="ga-hint">{t('Share inside the body')}</div>
                <div style={{ fontSize: '1.6em', fontWeight: 600,
                  color: view.share > 0.1 ? 'var(--danger, #f85149)' : view.share > 0.02
                    ? 'var(--warning, #d29922)' : 'var(--success, #3fb950)' }}>
                  {pct(view.share)}
                </div>
                <div className="ga-hint">{t('of the mesh area')}</div>
              </div>
            ) : loadingBody ? (
              <div className="ga-hint">{t('Placing the mesh on the body…')}</div>
            ) : (
              <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>{viewError}</div>
            )}
            <div className="ga-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span>{`${t('Triangles')} ${file.tris?.toLocaleString() ?? '–'}`}</span>
              {built ? <span>{`${t('Built')} ${built}`}</span> : null}
              {source.note ? <span style={{ whiteSpace: 'pre-line', color: 'var(--danger, #f85149)' }}>{source.note}</span> : null}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
