/**
 * GarmentMeshView — the Mesh row's 3D view of an own-mesh clothing piece (Ruling A48a).
 *
 * `GarmentMeshTiles`: the mesh in use as a small still tile (a click opens the viewer, the way a small image
 * enlarges), its gate light, "Built <time>" and its triangle count under it, and beside it one tile per KEPT mesh
 * (Ruling A58: a refused attempt, the mesh a run or a pick replaced, a result that finished while another mesh was
 * chosen — "not applied") with the same viewer and "Use this mesh" (0 hub jobs, then the fit on the CPU; usable
 * while a mesh job runs) — or, for an attempt that failed outright, a slim placeholder with the error.
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
import { StepLight } from './StepRows'
import type { GarmentMeshAttempt, GarmentMeshBodyView, GarmentMeshFile, GarmentMeshView } from './useGarment'

const TILE_W = 84
const TILE_H = 112

type Which = 'prepared' | 'raw'

/** One thing the viewer can show: the mesh in use or a kept mesh, each with its prepared and raw file. */
export interface MeshSource {
  id: string
  label: string
  prepared: GarmentMeshFile | null
  raw: GarmentMeshFile | null
  builtAt: string | null
  refused: boolean
  /** Why it was refused (plain words, the gate's reasons). */
  note: string
  /** Ruling A58: the kept mesh's slot (the `Use this` target); 0 for the mesh in use. */
  slot: number
  /** Ruling A58: what the kept mesh is (refused attempt / earlier mesh / a job's result). */
  origin: GarmentMeshAttempt['origin'] | 'in_use'
  /** Finished while another mesh was chosen — kept, not applied (Ruling A58). */
  notApplied: boolean
  /** Why "Use this" waits ("" when it can). */
  useBlock: string
}

/** The kept mesh's name in the tile and the viewer (Ruling A58). */
function keptLabel(a: GarmentMeshAttempt, t: (s: string) => string): string {
  if (a.origin === 'previous') return t('Earlier mesh')
  if (a.origin === 'job') return t('Result of the job')
  return `${t('Attempt')}${a.run_attempt ? ` ${a.run_attempt}` : ''} · ${a.ok ? t('Accepted') : t('Refused')}`
}

/** The sources of the Mesh row: the mesh in use first, then every kept mesh that kept a file. */
function meshSources(view: GarmentMeshView | undefined, builtAt: string | null, userAccepted: boolean,
  t: (s: string) => string): MeshSource[] {
  if (!view) return []
  const out: MeshSource[] = []
  if (view.prepared || view.raw) {
    out.push({ id: 'accepted', label: view.prepared ? (userAccepted ? t('Mesh in use · accepted by you') : t('Accepted mesh'))
      : t('Raw mesh'), prepared: view.prepared, raw: view.raw, builtAt, refused: !view.prepared, note: '', slot: 0,
    origin: 'in_use', notApplied: false, useBlock: '' })
  }
  for (const a of view.attempts) {
    if (!a.prepared && !a.raw) continue
    out.push({ id: `attempt-${a.attempt}`, label: keptLabel(a, t), prepared: a.prepared, raw: a.raw,
      builtAt: a.created_at ?? builtAt, refused: !a.ok, note: attemptNote(a, t), slot: a.attempt,
      origin: a.origin, notApplied: !!a.chosen_during_job, useBlock: a.use_block || '' })
  }
  return out
}

function attemptNote(a: GarmentMeshAttempt, t: (s: string) => string): string {
  return [
    a.chosen_during_job ? t(NOT_APPLIED) : '',
    a.largest_component_share != null
      ? `${t('Largest part')} ${(a.largest_component_share * 100).toFixed(1)} %` : '',
    ...(a.reasons || []),
    a.error && !(a.reasons || []).includes(a.error) ? a.error : '',
  ].filter(Boolean).join('\n')
}

/** The line under a result that finished while another mesh was chosen (Ruling A58). */
const NOT_APPLIED = 'Finished while another mesh was chosen — not applied'

function trisText(n: number | null | undefined): string {
  return n != null ? `${n.toLocaleString()} △` : ''
}

/** A still picture of one mesh (meshSnapshot) — a click opens the viewer; its gate light beside the caption and,
 *  for a kept mesh, "Use this" under it (0 hub jobs, then the fit on the CPU — Ruling A58). */
function MeshTile({ source, onOpen, onUse, useDisabled }: {
  source: MeshSource
  onOpen: () => void
  onUse?: (slot: number) => void
  useDisabled: boolean
}) {
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
  const gate = source.refused ? t('Gate: refused') : t('Gate: passed')
  const title = [source.label, gate, source.note, `${t('Triangles')} ${file.tris?.toLocaleString() ?? '–'}`,
    built ? `${t('Built')} ${built}` : '', t('Click to open the 3D view')].filter(Boolean).join('\n')
  const useTitle = source.useBlock ? t(source.useBlock) : [t('Use this mesh — 0 hub jobs, then the fit on the CPU'),
    source.refused ? t('Its gate refused it: using it counts as your acceptance.') : '',
    t('While a mesh job runs, its result then stays a kept mesh.')].filter(Boolean).join('\n')
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
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
          <StepLight light={source.refused ? 'red' : 'green'} title={gate} />
          {source.origin === 'in_use' ? t('In use') : source.label}
        </span>
        <br />{built ? `${t('Built')} ${built}` : ''}
        <br />{trisText(file.tris)}
      </span>
      {source.notApplied ? (
        <span className="ga-hint" style={{ fontSize: '0.68em', textAlign: 'center', lineHeight: 1.2,
          color: 'var(--warning, #d29922)' }} title={t(NOT_APPLIED)}>
          {t(NOT_APPLIED)}
        </span>
      ) : null}
      {onUse && source.slot > 0 ? (
        <button type="button" className="ga-btn ga-btn-sm" style={{ fontSize: '0.72em', padding: '1px 6px' }}
          disabled={useDisabled || !!source.useBlock} title={useTitle}
          aria-label={`${t('Use this mesh')} · ${source.label} · ${t('0 hub jobs')}`}
          onClick={() => onUse(source.slot)}>
          {t('Use this mesh')}
        </button>
      ) : null}
      {onUse && source.slot > 0 && source.useBlock ? (
        <span className="ga-hint" style={{ fontSize: '0.68em', textAlign: 'center', lineHeight: 1.2 }}>
          {t(source.useBlock)}
        </span>
      ) : null}
    </div>
  )
}

/** The Mesh row's tiles: the mesh in use, then each kept mesh (a failed attempt as a slim placeholder). */
export function GarmentMeshTiles({ view, builtAt, pieceName, userAccepted = false, onUse, useDisabled = false }: {
  view: GarmentMeshView | undefined
  builtAt: string | null
  pieceName: string
  /** The mesh in use was chosen against its gate (Ruling A58). */
  userAccepted?: boolean
  /** Ruling A58: "Use this" on kept mesh `slot` (0 hub jobs; the caller posts it and reloads). Absent = no button. */
  onUse?: (slot: number) => void
  useDisabled?: boolean
}) {
  const { t } = useI18n()
  const sources = useMemo(() => meshSources(view, builtAt, userAccepted, t), [view, builtAt, userAccepted, t])
  const [open, setOpen] = useState<string | null>(null)
  if (!view) return null
  const failed = view.attempts.filter((a) => !a.prepared && !a.raw)
  if (!sources.length && !failed.length) return null
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start', flexBasis: '100%' }}>
      {sources.map((s) => (
        <MeshTile key={s.id} source={s} onOpen={() => setOpen(s.id)} onUse={onUse} useDisabled={useDisabled} />
      ))}
      {failed.map((a, i) => (
        <div key={`failed-${i}`} className="ga-step-grid-empty" style={{ width: TILE_W, height: TILE_H }}
          title={[`${t('Attempt')} ${a.run_attempt ?? ''} · ${t('Failed')}`, attemptNote(a, t), t('No mesh was kept')]
            .filter(Boolean).join('\n')}>
          {`${t('Attempt')} ${a.run_attempt ?? ''} · ${t('Failed')}`}
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
