/**
 * HairSubtract — the Hair tab's "Subtract" method (plan
 * docs/superpowers/plans/2026-11-10-hair-subtract-method.md, Task 2; spec
 * docs/superpowers/specs/2026-11-10-hair-subtract-method-design.md).
 *
 * The haired front + back views of Hair views → mesh (`edit_chain`; the input, small tiles — a click
 * enlarges) become ONE mesh of the haired character (`mesh_source`, the routed
 * occasion `hair_source_mesh`, one hub job), the hair is cut off it against
 * the bald base on the CPU (`cut`) and fitted like every garment (`fit`).
 * Each step is one status line with Regenerate (the same explicit-run queue
 * as the other steps: POST /characters/{n}/garments/{item}/run, useGarmentRun)
 * and its numbers as gate chips; the details sit in the hover.
 *
 * The shape (Auto from the hair length / Cut / Shell) and the shell thickness
 * (POST /characters/{n}/hair/subtract {shape, shell_mm}) sit beside the viewer
 * (SubtractSettings): a change re-cuts and re-fits on the CPU from the cached
 * source mesh — never a new hub job.
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { FitBlock, GateChips, RunBadge, RunButton, StepState } from './GarmentSteps'
import { EMPTY_TILE, ERROR_STYLE, ROW, WARN_STYLE, chipResults, num, recordLimits, shownRecord } from './garmentStyle'
import type { ChipSpec, GarmentLimits, GarmentRunBody } from './garmentStyle'
import { MeshJobFetch } from './MeshJobFetch'
import { RefImage } from './RefImage'
import { GARMENT_VIEWS, runMark, runSlot } from './useGarment'
import type {
  GarmentInfo, GarmentView, GateLimit, HairSubtractSettings, RecordLimits, RunFeedback,
} from './useGarment'

/** The subtract method's steps (`garment_store.SUBTRACT_STEPS`). */
export const SUBTRACT_ORDER = ['haired', 'mesh_source', 'cut', 'fit'] as const

/** The haired input tiles: small, a click enlarges. */
const INPUT_TILE = 120

/** The cut's gate numbers (`garment_cut.CUT_GATES`). */
const CUT_CHIPS: ChipSpec[] = [
  { key: 'registration_p95_cm', label: 'Registration p95', scale: 1, unit: 'cm', digits: 2 },
  { key: 'hairline_cm', label: 'Hairline error', scale: 1, unit: 'cm', digits: 2 },
  { key: 'label_holes', label: 'Holes left', scale: 1, unit: '', digits: 0 },
  { key: 'hair_area_cm2', label: 'Hair area', scale: 1, unit: 'cm²', digits: 0 },
]

const SOURCE_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  refused: 'Refused',
  missing: 'Not built yet',
}

const CUT_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  stale: 'Cut from another source mesh',
  refused: 'Refused',
  missing: 'Not cut yet',
}

const SHAPE_LABELS: Record<string, string> = {
  cut: 'Cut',
  shell: 'Shell',
}

const obj = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' ? v as Record<string, unknown> : {})
const fmt = (v: unknown, digits: number, unit = '') => {
  const n = num(v)
  return n === null ? '–' : `${n.toFixed(digits)}${unit ? ` ${unit}` : ''}`
}

/** The cut's hover: registration, hairline, holes, the closed part, the shell and the time. */
function cutDetails(report: Record<string, unknown>, metrics: Record<string, unknown>, reasons: string[],
  t: (s: string) => string): string {
  const reg = obj(report.registration)
  const line = obj(report.hairline)
  const label = obj(report.label)
  const closed = obj(report.closed)
  const shell = obj(report.shell)
  const rows = [
    `${t('Registration')}: p50 ${fmt(reg.outer_nonhair_p50_cm, 2, 'cm')} · p95 ${fmt(reg.outer_nonhair_p95_cm ?? metrics.registration_p95_cm, 2, 'cm')}`
      + (num(reg.n) !== null ? ` · ${reg.n} ${t('points')}` : '')
      + (num(reg.scale_h_to_b) !== null ? ` · ${t('Scale')} ${fmt(reg.scale_h_to_b, 3)}` : ''),
    `${t('Hairline')}: 2D ${fmt(line.y_2d_m, 3, 'm')} · 3D ${fmt(line.y_3d_m, 3, 'm')} · Δ ${fmt(line.delta_cm ?? metrics.hairline_cm, 2, 'cm')}`,
    `${t('Holes filled')}: ${fmt(label.holes_filled, 0)} · ${t('Holes left')}: ${fmt(metrics.label_holes, 0)}`,
    `${t('Hair')}: ${fmt(label.vertices, 0)} ${t('vertices')} · ${t('Thickness')} p50 ${fmt(label.thickness_p50_cm, 2, 'cm')}`,
    Object.keys(closed).length
      ? `${t('Closed')}: ${t('open edges')} ${fmt(closed.open_edges, 0)} · ${t('parts')} ${fmt(closed.components, 0)}`
      : '',
    Object.keys(shell).length
      ? `${t('Shell')}: ${fmt(shell.thickness_mm, 1, 'mm')} · ${t('snap')} p50 ${fmt(shell.snap_p50_cm, 2, 'cm')}`
      : '',
    num(report.seconds) !== null ? `${t('Time')}: ${fmt(report.seconds, 1, 's')}` : '',
    ...reasons,
  ]
  return rows.filter(Boolean).join('\n')
}

/** The haired view's gate numbers as hover text. */
function chipText(specs: ChipSpec[], record: Record<string, unknown> | null, limits: Record<string, GateLimit> | undefined,
  view: string, t: (s: string) => string): string {
  return chipResults(specs, record, limits, view)
    .map((c) => `${c.ok === false ? '✗' : c.ok ? '✓' : '·'} ${t(c.label)} ${c.shown}${c.lim ? ` (${c.lim})` : ''}`)
    .join('\n')
}

/** One step's head line: the run mark, the status (details on hover) and Regenerate. */
function StepLine({ title, status, statusStyle, details, mark, slot, feedback, disabled, blockedTitle, buttonTitle,
  label, onRun }: {
  title: string
  status: string
  statusStyle?: CSSProperties
  details?: string
  mark: ReturnType<typeof runMark>
  slot: string
  feedback?: RunFeedback
  disabled: boolean
  blockedTitle?: string
  buttonTitle?: string
  label: string
  onRun: () => void
}) {
  return (
    <>
      <div className="ga-fieldset-title">{title}</div>
      <div style={ROW}>
        <RunBadge mark={mark} />
        <span className="ga-hint" style={{ ...statusStyle, cursor: details ? 'help' : undefined }} title={details}>
          {status}
        </span>
        <RunButton feedback={feedback} slot={slot} disabled={disabled || !!blockedTitle}
          title={blockedTitle || buttonTitle} onClick={onRun} label={label} />
      </div>
    </>
  )
}

/** The middle column: the haired input views, source mesh, cut and fit. */
export function SubtractSteps({ garment, limits, hairedChips, fitChips, busy, onRun, feedback, meshFetchUrl = null,
  onMeshFetched }: {
  garment: GarmentInfo | null
  limits: GarmentLimits
  /** The haired views' gate chips (FieldHair's HAIRED_CHIPS). */
  hairedChips: ChipSpec[]
  fitChips: ChipSpec[]
  busy: boolean
  onRun: (body: GarmentRunBody) => void
  feedback?: RunFeedback
  /** "Fetch finished job…" on the mesh row (MeshJobFetch): its POST url, null hides it. */
  meshFetchUrl?: string | null
  /** The mesh record changed through a fetched job: reload the panel. */
  onMeshFetched?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const steps = garment?.steps ?? {}
  const viewLabel = (view: GarmentView) => (view === 'front' ? t('Front view') : t('Back view'))
  const hairedReady = GARMENT_VIEWS.every((v) => !!steps.haired?.[v]?.accepted)
  const source = steps.mesh_source
  const cut = steps.cut
  const fit = steps.fit
  const stamp = (at: string | null | undefined) => (at ? ` · ${formatDateTime(at, clockSettings())}` : '')

  // The cut's numbers: its record, else a refusal the run reported (the in-memory failure carries them).
  const failedCut = garment?.failed?.step === 'cut' ? obj(garment.failed.gates) : null
  const cutMetrics: Record<string, unknown> | null = cut && cut.status !== 'missing'
    ? cut.metrics
    : failedCut?.metrics ? obj(failedCut.metrics) : null
  const cutLimits = recordLimits(cut?.gates?.limits) ?? recordLimits(failedCut?.limits as RecordLimits | undefined)
  const cutReasons = cut?.gates?.reasons ?? []
  const shape = cut?.shape ? t(SHAPE_LABELS[cut.shape] || cut.shape) : ''
  const failedFit = garment?.failed?.step === 'fit' ? obj(garment.failed.gates) : null
  const fitLimits = recordLimits(fit?.gates?.limits) ?? recordLimits(failedFit?.limits as RecordLimits | undefined)
    ?? limits.fit

  const routing = source?.routing ? obj(source.routing) : null
  const sourceDetails = [
    source?.ssig ? `ssig ${source.ssig}` : '',
    routing?.fallback_from ? `${t('Fallback from')} ${String(routing.fallback_from)}` : '',
    source?.error || '',
  ].filter(Boolean).join('\n')

  return (
    <>
      <div className="ga-fieldset-title">{t('Haired views (input)')}</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {GARMENT_VIEWS.map((view) => {
          const img = steps.haired?.[view]
          const label = viewLabel(view)
          const numbers = chipText(hairedChips, shownRecord(img), limits.haired, view, t)
          return (
            <div key={view} style={{ width: INPUT_TILE * 0.75 + 20, minWidth: 0 }}>
              <div className="ga-hint" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <span>{label}</span>
                <RunBadge mark={runMark(feedback, garment, SUBTRACT_ORDER, 'haired', view)} />
              </div>
              {img?.url ? (
                <RefImage key={img.url} src={img.url} height={INPUT_TILE} label={label} meta={img} compact />
              ) : (
                <div className="ga-hint" style={{ ...EMPTY_TILE, height: INPUT_TILE }}>{t('No render yet')}</div>
              )}
              <div className="ga-hint" title={numbers || undefined}
                style={{ ...(img?.url && !img.accepted ? WARN_STYLE : {}), cursor: numbers ? 'help' : undefined }}>
                {!img?.url ? t('Missing') : img.accepted ? t('Accepted') : t('Not accepted')}
              </div>
              <RunButton feedback={feedback} slot={runSlot({ step: 'haired', view })} style={{ marginTop: 2 }}
                disabled={busy || !garment} ariaLabel={`${t('Regenerate')} · ${label}`}
                onClick={() => onRun({ step: 'haired', view, force: true })}
                label={img?.url ? t('Regenerate') : t('Generate')} />
            </div>
          )
        })}
        <div className="ga-hint" style={{ flex: '1 1 160px', minWidth: 0 }}>
          {t('The haired views of Hair views → mesh — both methods share them.')}
        </div>
      </div>
      {garment ? <StepState garment={garment} step="haired" /> : null}

      <StepLine
        title={t('Source mesh')}
        status={`${t(SOURCE_STATUS[source?.status || 'missing'])}`
          + (source?.tris ? ` · ${t('Triangles')} ${source.tris.toLocaleString()}` : '')
          + (source?.backend ? ` · ${source.backend}` : '')
          + stamp(source?.created_at)}
        statusStyle={source?.status === 'refused' ? ERROR_STYLE : undefined}
        details={sourceDetails || undefined}
        mark={runMark(feedback, garment, SUBTRACT_ORDER, 'mesh_source')}
        slot={runSlot({ step: 'mesh_source' })}
        feedback={feedback}
        disabled={busy || !garment}
        blockedTitle={garment && !hairedReady ? t('Run the previous step first') : undefined}
        buttonTitle={t('One mesh job of the haired character (hair_source_mesh)')}
        label={source && source.status !== 'missing' ? t('Regenerate') : t('Generate')}
        onRun={() => onRun({ step: 'mesh_source', force: true })}
      />
      {source?.status === 'refused' && source.error ? (
        <div className="ga-hint" style={{ ...ERROR_STYLE, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
          title={source.error}>{source.error}</div>
      ) : null}
      <MeshJobFetch url={garment && hairedReady ? meshFetchUrl : null} disabled={busy}
        onDone={() => onMeshFetched?.()} />
      {garment ? <StepState garment={garment} step="mesh_source" /> : null}

      <StepLine
        title={t('Cut')}
        status={`${t(CUT_STATUS[cut?.status || 'missing'])}`
          + (shape ? ` · ${shape}` : '')
          + (cut?.shape === 'shell' && cut.shell_mm != null ? ` ${cut.shell_mm} mm` : '')
          + stamp(cut?.created_at)}
        statusStyle={cut?.status === 'refused' ? ERROR_STYLE : cut?.status === 'stale' ? WARN_STYLE : undefined}
        details={cut && cut.status !== 'missing' ? cutDetails(cut.report || {}, cut.metrics || {}, cutReasons, t) : undefined}
        mark={runMark(feedback, garment, SUBTRACT_ORDER, 'cut')}
        slot={runSlot({ step: 'cut' })}
        feedback={feedback}
        disabled={busy || !garment}
        blockedTitle={garment && source?.status !== 'accepted' ? t('Run the previous step first') : undefined}
        buttonTitle={t('CPU only — no mesh job')}
        label={cut && cut.status !== 'missing' ? t('Regenerate') : t('Generate')}
        onRun={() => onRun({ step: 'cut', force: true })}
      />
      <GateChips specs={CUT_CHIPS} record={cutMetrics} limits={cutLimits} />
      {garment ? <StepState garment={garment} step="cut" /> : null}

      <FitBlock garment={garment} chips={fitChips} limits={fitLimits} ready={cut?.status === 'accepted'}
        busy={busy} onRun={onRun} lowFailedText="Distance tier failed — the full hair is used"
        feedback={feedback} order={SUBTRACT_ORDER} />
    </>
  )
}

/** A thickness draft as mm; null = default (empty), NaN = invalid. */
function draftMm(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const n = Number(trimmed.replace(',', '.'))
  return Number.isFinite(n) ? n : NaN
}

/** The shape (Auto from the hair length / Cut / Shell) and the shell thickness,
 *  beside the viewer. Keyed by the server values, so the drafts restart from
 *  them after a save. */
export function SubtractSettings({ settings, busy, running, sourceReady, onApply }: {
  settings: HairSubtractSettings
  busy: boolean
  /** A hair run is active: the settings wait for it. */
  running: boolean
  /** The source mesh is there: Apply re-cuts and re-fits at once (CPU only). */
  sourceReady: boolean
  onApply: (shape: '' | 'cut' | 'shell', shellMm: number | null) => void
}) {
  const { t } = useI18n()
  const storedMm = settings.shell_mm === settings.shell_mm_default ? '' : String(settings.shell_mm)
  const [shape, setShape] = useState<'' | 'cut' | 'shell'>(settings.shape_override)
  const [mm, setMm] = useState(storedMm)
  const value = draftMm(mm)
  const valid = value === null || (!Number.isNaN(value) && value >= settings.shell_mm_min && value <= settings.shell_mm_max)
  // What "Auto" resolves to is known only while no override is stored (the server's shape then IS the auto one).
  const autoShape = settings.shape_source === 'length' ? settings.shape : null
  const effective = shape || autoShape
  const storedValue = settings.shell_mm === settings.shell_mm_default ? null : settings.shell_mm
  const same = shape === settings.shape_override && value === storedValue
  const manual = settings.shape_override !== '' || storedValue !== null
  // The length class is the server's word (garment_hair.LENGTH_CLASSES), shown as is.
  const length = settings.length_class || t('unknown length')
  const autoLabel = `${t('Auto — from hair length')} (${length}${autoShape ? `: ${t(SHAPE_LABELS[autoShape])}` : ''})`
  return (
    <>
      <div className="ga-fieldset-title">{t('Hair shape')}</div>
      <div style={ROW}>
        <select className="ga-input" style={{ width: 'auto', maxWidth: '100%' }} value={shape} disabled={busy}
          aria-label={t('Hair shape')} onChange={(e) => setShape(e.target.value as '' | 'cut' | 'shell')}>
          <option value="">{autoLabel}</option>
          <option value="cut">{t('Cut')}</option>
          <option value="shell">{t('Shell — narrow scalp layer')}</option>
        </select>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}
          title={`${settings.shell_mm_min}–${settings.shell_mm_max} mm · ${t('5 mm ≈ short crop')}`}>
          {t('Shell (mm)')}
          <input className="ga-input" type="number" step="0.5" min={settings.shell_mm_min} max={settings.shell_mm_max}
            style={{ width: 70 }} value={mm} placeholder={String(settings.shell_mm_default)}
            disabled={busy || effective === 'cut'} aria-label={t('Shell thickness (mm)')}
            onChange={(e) => setMm(e.target.value)} />
        </label>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !valid || same}
          title={!valid ? t('Value out of range') : undefined} onClick={() => onApply(shape, value)}>
          {t('Apply')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !manual} onClick={() => onApply('', null)}>
          {t('Reset to automatic')}
        </button>
        {running ? <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span> : null}
      </div>
      <div className="ga-hint">
        {`${settings.shell_mm_min}–${settings.shell_mm_max} mm · ${t('5 mm ≈ short crop')}`}
        {' · '}
        {sourceReady
          ? t('A change re-cuts and re-fits on the CPU from the stored source mesh — no new mesh job.')
          : t('Takes effect with the next run (no source mesh yet).')}
      </div>
    </>
  )
}
