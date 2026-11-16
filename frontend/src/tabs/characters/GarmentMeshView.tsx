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
 * - Ruling A48c: the wheel zooms, Shift+drag moves the view, a double-click stands the model up and frames it again;
 *   "Larger view" grows the SAME viewer to about 90 % of the window (Esc or × back — toggles, camera and pose stay).
 * - Ruling A48c: the fit allowance beside it (`AllowancePanel`): a slider previews every factor the allowance can
 *   apply, widening the shown mesh live with the fit's own rule (`fitWiden.ts`, a port of `garment_fit.widen`);
 *   the share inside, the red faces and the gap to the body over the trunk follow it (the server's table per
 *   factor). Ruling A68: a second slider previews the depth allowance (`garment_fit.depth_shift`, ported as
 *   `easeInPlace`) with the gap front / back. Save stores the settable choices: the fit becomes due, nothing runs.
 * Nothing here spends a job.
 */
import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useClockSettings } from '../../lib/clockFormat'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from './Model3DViewer'
import type { ViewerCompanion, ViewerDeform } from './Model3DViewer'
import { ALLOWANCE_CHOICES, ALLOWANCE_HINT, DEPTH_HINT, allowanceLabel } from './fitSettingsModel'
import type { AllowanceChoice, DepthChoice, FitSettingsInfo } from './fitSettingsModel'
import {
  autoFactor, choiceFactor, decodeMask, depthEase, depthGapsAt, depthText, easeInPlace, factorChoice, factorText,
  maskBit, mmText, stepAt, widenInPlace,
} from './fitWiden'
import type { AllowanceView } from './fitWiden'
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
  if (view.shell) {
    // Ruling A48d: the shell from the body the last shell fit made — shown as its Prepared mesh, beside the generated
    out.push({ id: 'shell', label: t('Shell from the body'), prepared: view.shell, raw: null, builtAt, refused: false,
      note: t('Made from the body\'s surface over the piece\'s region — local on the CPU, 0 hub jobs'), slot: 0,
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
function MeshTile({ source, onOpen, onUse, useDisabled, onDelete }: {
  source: MeshSource
  onOpen: () => void
  onUse?: (slot: number) => void
  useDisabled: boolean
  /** Ruling A128: delete this tile (the caller confirms first). Absent = no button. */
  onDelete?: (slot: number, label: string) => void
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
          {source.id === 'shell' ? source.label : source.origin === 'in_use' ? t('In use') : source.label}
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
      {onDelete && source.id !== 'shell' ? (
        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" style={{ fontSize: '0.72em', padding: '1px 6px' }}
          disabled={useDisabled}
          title={source.origin === 'in_use'
            ? t('Delete the mesh in use — the mesh step becomes due (asks first, names the hub jobs)')
            : t('Delete this kept mesh — 0 hub jobs, it cannot be brought back')}
          aria-label={`${t('Delete')} · ${source.label}`}
          onClick={() => onDelete(source.slot, source.label)}>
          {t('Delete')}
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
export function GarmentMeshTiles({ view, builtAt, pieceName, userAccepted = false, onUse, useDisabled = false,
  allowance = null, onDelete, onDeleteAll }: {
  view: GarmentMeshView | undefined
  builtAt: string | null
  pieceName: string
  /** The mesh in use was chosen against its gate (Ruling A58). */
  userAccepted?: boolean
  /** Ruling A58: "Use this" on kept mesh `slot` (0 hub jobs; the caller posts it and reloads). Absent = no button. */
  onUse?: (slot: number) => void
  useDisabled?: boolean
  /** Ruling A48c: the fit allowance beside the viewer (null: none — the piece has no fit settings). */
  allowance?: MeshAllowance | null
  /** Ruling A128: delete one tile (slot 0 = the mesh in use); the caller confirms first. */
  onDelete?: (slot: number, label: string) => void
  /** Ruling A128: "Delete all meshes of this piece…"; the caller confirms first. */
  onDeleteAll?: () => void
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
        <MeshTile key={s.id} source={s} onOpen={() => setOpen(s.id)} onUse={onUse} useDisabled={useDisabled}
          onDelete={onDelete} />
      ))}
      {failed.map((a, i) => (
        <div key={`failed-${i}`} className="ga-step-grid-empty" style={{ width: TILE_W, height: TILE_H }}
          title={[`${t('Attempt')} ${a.run_attempt ?? ''} · ${t('Failed')}`, attemptNote(a, t), t('No mesh was kept')]
            .filter(Boolean).join('\n')}>
          {`${t('Attempt')} ${a.run_attempt ?? ''} · ${t('Failed')}`}
        </div>
      ))}
      {onDeleteAll && sources.length ? (
        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" style={{ alignSelf: 'flex-end', fontSize: '0.72em' }}
          disabled={useDisabled} onClick={onDeleteAll}
          title={t('Delete every mesh, kept mesh and fit of this piece (asks first, names the hub jobs to make them again)')}>
          {t('Delete all meshes…')}
        </button>
      ) : null}
      {open ? (
        <GarmentMeshViewer sources={sources} initial={open} pieceName={pieceName} onClose={() => setOpen(null)}
          allowance={allowance} />
      ) : null}
    </div>
  )
}

const SWITCH_ROW = { display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' } as const

/** Ruling A48c: what the viewer needs for the fit allowance beside it — the plain body's fit settings and their
 *  save (POST …/fit-settings: saves only, the fit becomes due, nothing runs). */
export interface MeshAllowance {
  character: string
  itemId: string
  info: FitSettingsInfo
  busy: boolean
  /** After a save: poll the dialog again. */
  onSaved: () => void
}

/** The large view's viewer height: the window's 90 % less the header and the padding. */
function largeHeight(): number {
  return Math.max(320, Math.round(window.innerHeight * 0.9) - 92)
}

/** The fit allowance beside the viewer (Ruling A48c): a slider over every factor the allowance can apply (the
 *  settable choices and Auto's steps) previews the widening live, "Auto → ×1.0x" names what Auto took on the stored
 *  fit, the gap to the body over the trunk and the share inside follow the preview. Ruling A68: a second slider
 *  previews the depth allowance (room in front of and behind the trunk, the fit adds it after its push-out) with the
 *  gap front / back beside the trunk gap. Save stores the settable choices that changed (the fit becomes due, nothing
 *  runs). */
function AllowancePanel({ allowance, table, factor, onFactor, choice, onChoice, depth, onDepth, shown }: {
  allowance: MeshAllowance | null
  table: AllowanceView
  factor: number
  onFactor: (f: number) => void
  choice: AllowanceChoice | null
  onChoice: (c: AllowanceChoice | null) => void
  depth: DepthChoice
  onDepth: (d: DepthChoice) => void
  shown: Which
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [saving, setSaving] = useState(false)
  const [savedNote, setSavedNote] = useState('')
  const info = allowance?.info || null
  const saved = info?.settings.allowance ?? null
  const savedDepth: DepthChoice = info?.settings.depth ?? 0
  const auto = autoFactor(info)
  const step = stepAt(table, factor)
  const index = Math.max(0, table.factors.findIndex((f) => Math.abs(f - factor) < 1e-6))
  const choiceName = choice === null ? t('Auto step — not a setting') : allowanceLabel(choice, t)
  const depthChoices = (table.depth?.choices as DepthChoice[] | undefined) || []
  const depthIndex = Math.max(0, depthChoices.indexOf(depth))
  const easeMm = table.depth?.ease_mm?.[depthIndex] ?? null
  const gaps = depthGapsAt(table, factor, depth)
  const change: { allowance?: AllowanceChoice; depth?: DepthChoice } = {}
  if (choice !== null && choice !== saved) change.allowance = choice
  if (depthChoices.length && depth !== savedDepth) change.depth = depth
  const changed = Object.keys(change).length > 0
  const canSave = !!allowance && changed && !saving && !allowance.busy
  const saveLabel = [change.allowance != null ? allowanceLabel(change.allowance, t) : '',
    change.depth != null ? `${t('depth')} ${depthText(change.depth)}` : ''].filter(Boolean).join(' · ')
  const save = async () => {
    if (!allowance || !changed) return
    setSaving(true)
    try {
      const d = await apiPost<{ fit_settings: FitSettingsInfo }>(
        `/characters/${encodeURIComponent(allowance.character)}/garments/${encodeURIComponent(allowance.itemId)}/fit-settings`,
        change)
      const note = d.fit_settings.due ? t('Fit due — refits on the CPU, 0 hub jobs') : t('nothing becomes due')
      setSavedNote(note)
      toast(`${t('Saved')} · ${note}`, 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
      allowance.onSaved()
    }
  }
  return (
    <div role="group" aria-label={t('Fit allowance')}
      style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', borderRadius: 6,
        border: '1px solid var(--border, #30363d)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <strong>{t('Fit allowance')}</strong>
        <span style={{ marginLeft: 'auto', fontWeight: 600 }} data-allowance-factor={factor}
          data-allowance-depth={depth}>
          {depthChoices.length ? `${factorText(factor)} · ${depthText(depth)}` : factorText(factor)}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={t(ALLOWANCE_HINT)}>
        <span className="ga-hint" style={{ width: 44 }}>{t('Width')}</span>
        <input type="range" min={0} max={table.factors.length - 1} step={1} value={index} style={{ flex: '1 1 0', minWidth: 0 }}
          aria-label={t('Width allowance preview')} aria-valuetext={`${factorText(factor)} · ${choiceName}`}
          onChange={(e) => {
            const f = table.factors[Number(e.target.value)] ?? 1
            onFactor(f)
            onChoice(factorChoice(f, ALLOWANCE_CHOICES))
          }} />
      </div>
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className={`ga-btn ga-btn-sm${choice === 'auto' ? ' ga-btn-primary' : ''}`}
          aria-pressed={choice === 'auto'}
          title={t('Preview what Auto took on the stored fit')}
          onClick={() => { onChoice('auto'); onFactor(auto ?? 1) }}>
          {auto != null ? `${t('Auto')} → ${factorText(auto)}` : t('Auto')}
        </button>
        <span className="ga-hint" style={{ minWidth: 0 }}>{choiceName}</span>
      </div>
      {auto == null ? (
        <span className="ga-hint">{t('Auto: decided at the next fit')}</span>
      ) : null}
      {depthChoices.length ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={t(DEPTH_HINT)}>
            <span className="ga-hint" style={{ width: 44 }}>{t('Depth')}</span>
            <input type="range" min={0} max={depthChoices.length - 1} step={1} value={depthIndex}
              style={{ flex: '1 1 0', minWidth: 0 }}
              aria-label={t('Depth allowance preview')}
              aria-valuetext={`${depthText(depth)}${easeMm != null ? ` · ${easeMm.toFixed(1)} mm` : ''}`}
              onChange={(e) => onDepth(depthChoices[Number(e.target.value)] ?? 0)} />
          </div>
          <span className="ga-hint" title={t(DEPTH_HINT)}>
            {`${depthText(depth)} = ${easeMm != null ? easeMm.toFixed(1) : '–'} mm ${t('more room in front and behind')} · ${
              t('Auto never adds depth')}`}
          </span>
        </>
      ) : null}
      <div title={t('Gap between the widened piece and the body over its trunk (between hips and shoulders, within the width the allowance scales), before the fit pushes it out; negative = inside the body')}>
        <span className="ga-hint">{t('Gap to the body (trunk)')}</span>
        <div data-allowance-gap="" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {step && step.gap_p50_mm != null
            ? `${t('median')} ${mmText(step.gap_p50_mm)} · ${t('min')} ${mmText(step.gap_min_mm)}`
            : t('No trunk band on this piece')}
        </div>
      </div>
      {depthChoices.length ? (
        <div title={t('Median gap of the trunk straight in front and straight behind (within 35°), widened and with the depth added, before the fit pushes it out; the fit adds the depth after its push-out, so where the piece lies inside the body it ends this much further out than the clearance')}>
          <span className="ga-hint">{t('Gap front / back (mm)')}</span>
          <div data-allowance-depth-gap="" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {gaps ? `${mmText(gaps[0])} / ${mmText(gaps[1])}` : t('No trunk band on this piece')}
          </div>
        </div>
      ) : null}
      <span className="ga-hint">
        {shown === 'prepared' ? t('Preview on the prepared mesh — the fit applies it on the body')
          : t('Preview on the raw mesh — the fit applies it on the body')}
      </span>
      {allowance ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={!canSave} onClick={() => { void save() }}
            title={choice === null && !change.depth ? t('Only Auto reaches this step; settable: +0, +3, +6, +10 %')
              : t('Saves the allowance for this piece and runs nothing; the fit becomes due (0 hub jobs)')}>
            {changed ? `${t('Save')} · ${saveLabel}` : t('Save')}
          </button>
          <span className="ga-hint">{`${t('Saved')}: ${saved != null ? allowanceLabel(saved, t) : '–'}${
            depthChoices.length ? ` · ${t('depth')} ${depthText(savedDepth)}` : ''}`}</span>
        </div>
      ) : null}
      {info?.due || savedNote ? (
        <span className="ga-hint" data-allowance-due="" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <StepLight light="yellow" />{savedNote || t('Fit due — refits on the CPU, 0 hub jobs')}
        </span>
      ) : null}
    </div>
  )
}

/** The viewer (a dialog over the piece dialog) with its switches beside it; "Larger view" grows the same viewer
 *  to about 90 % of the window (Esc or × back), so the toggles, the camera and the pose stay as they are. */
export function GarmentMeshViewer({ sources, initial, pieceName, onClose, initialWhich = 'prepared',
  initialBody = false, initialInside = false, allowance = null }: {
  sources: MeshSource[]
  initial: string
  pieceName: string
  onClose: () => void
  initialWhich?: Which
  initialBody?: boolean
  initialInside?: boolean
  allowance?: MeshAllowance | null
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
  const [large, setLarge] = useState(false)
  const [bigHeight, setBigHeight] = useState(largeHeight)
  // The allowance preview: the factor shown and the choice it stands for (null: an Auto step, not settable).
  const savedChoice = allowance?.info.settings.allowance ?? 'auto'
  const [choice, setChoice] = useState<AllowanceChoice | null>(savedChoice)
  const [factor, setFactor] = useState<number>(() => (savedChoice === 'auto'
    ? autoFactor(allowance?.info) ?? 1 : choiceFactor(savedChoice) ?? 1))
  // Ruling A68: the depth allowance previewed (a settable choice; Auto never adds depth).
  const [depth, setDepth] = useState<DepthChoice>(allowance?.info.settings.depth ?? 0)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation(); e.preventDefault()
      if (large) setLarge(false)
      else onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose, large])
  useEffect(() => {
    if (!large) return
    const onResize = () => setBigHeight(largeHeight())
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [large])

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

  const table = view?.allowance && view.allowance.factors?.length ? view.allowance : null
  const bits = useMemo(() => (table ? decodeMask(table.mask) : null), [table])
  const bit = table ? maskBit(table.factors, factor) : -1
  const axis = table?.axis
  const ease = depthEase(axis, depth)
  const deform = useMemo<ViewerDeform | null>(() => (axis && (Math.abs(factor - 1) > 1e-9 || ease !== 0) ? {
    key: `${view?.key}:${factor}:${depth}`,
    map: (xyz: Float32Array) => { widenInPlace(xyz, factor, axis); easeInPlace(xyz, ease, axis) },
  } : null), [axis, factor, depth, ease, view?.key])
  const step = stepAt(table, factor)

  const companions: ViewerCompanion[] = []
  if (view) {
    companions.push({ key: `ghost:${view.key}`, url: view.ghost_url, style: 'ghost', visible: bodyOn })
    if (view.inside_url) {
      companions.push({ key: `inside:${view.key}`, url: view.inside_url, style: 'mark', visible: insideOn,
        follow: true, faceBits: bits && bit >= 0 ? { bits, bit } : null })
    }
  }
  const loadingBody = !view && !viewError
  const ghostState = view ? companionState[`ghost:${view.key}`] : ''
  const insideState = view?.inside_url ? companionState[`inside:${view.key}`] : ''
  const built = stampLabel(source?.builtAt)
  const pct = (v: number) => `${(v * 100).toFixed(1)} %`
  const share = step ? step.share : view?.share ?? 0
  const shareTitle = view ? [
    t('Share of the mesh area whose faces lie inside the base body, placed as the fit places the piece (before the fit pushes it out).'),
    `${(step ? step.inside_faces : view.inside_faces).toLocaleString()} / ${view.faces.toLocaleString()} ${t('faces')} (${
      pct(step ? step.face_share : view.face_share)})`,
  ].join('\n') : ''

  if (!source || !file) return null
  const dialogStyle: CSSProperties = large
    ? { position: 'fixed', left: '5vw', top: '5vh', width: '90vw', height: '90vh', maxWidth: 'none', maxHeight: 'none',
      margin: 0, display: 'flex', flexDirection: 'column' }
    : { width: 'min(1240px, 96vw)', maxWidth: 'none' }
  return createPortal(
    <div className="ga-modal-backdrop" style={{ zIndex: 1100 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) { if (large) setLarge(false); else onClose() } }}>
      <div className="ga-modal ga-garment-dialog" role="dialog" aria-modal="true" data-large={large ? '1' : '0'}
        aria-label={`${t('Mesh')} · ${pieceName}`} style={dialogStyle}>
        <div className="ga-modal-header ga-garment-dialog-head">
          <span className="ga-garment-dialog-title">{`${t('Mesh')} · ${pieceName} · ${source.label}`}</span>
          {large ? (
            <button type="button" className="ga-btn ga-btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setLarge(false)}
              aria-label={t('Back to the normal view')} title={`${t('Back to the normal view')} (Esc)`}>×</button>
          ) : (
            <>
              <button type="button" className="ga-btn ga-btn-sm" style={{ marginLeft: 'auto' }}
                onClick={() => setLarge(true)} title={t('Opens the same view at about 90 % of the window; Esc goes back')}>
                {t('Larger view')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}
                aria-label={t('Close')}>{t('Close')}</button>
            </>
          )}
        </div>
        <div className="ga-modal-body" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 260px', gap: 10,
          ...(large ? { flex: '1 1 auto', minHeight: 0, overflow: 'auto' } : {}) }}>
          <Model3DViewer key={file.url} url={file.url} format="glb" height={large ? bigHeight : 560}
            builtAt={source.builtAt} companions={companions} deform={deform} resetViewOnDoubleClick
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
                <div data-allowance-share="" style={{ fontSize: '1.6em', fontWeight: 600,
                  color: share > 0.1 ? 'var(--danger, #f85149)' : share > 0.02
                    ? 'var(--warning, #d29922)' : 'var(--success, #3fb950)' }}>
                  {pct(share)}
                </div>
                <div className="ga-hint">{table ? `${t('of the mesh area')} · ${factorText(factor)}` : t('of the mesh area')}</div>
              </div>
            ) : loadingBody ? (
              <div className="ga-hint">{t('Placing the mesh on the body…')}</div>
            ) : (
              <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>{viewError}</div>
            )}
            {table && allowance ? (
              <AllowancePanel allowance={allowance} table={table} factor={factor} onFactor={setFactor}
                choice={choice} onChoice={setChoice} depth={depth} onDepth={setDepth} shown={shown} />
            ) : null}
            <div className="ga-hint" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span>{`${t('Triangles')} ${file.tris?.toLocaleString() ?? '–'}`}</span>
              {built ? <span>{`${t('Built')} ${built}`}</span> : null}
              {source.note ? <span style={{ whiteSpace: 'pre-line', color: source.id === 'shell' ? 'inherit' : 'var(--danger, #f85149)' }}>{source.note}</span> : null}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
