/**
 * FootwearSteps — the shoe source of a footwear piece (kind `footwear`,
 * method `shoe`) in the Wardrobe's Mesh steps dialog (WardrobeGarment),
 * rows 1–5 of spec § 9.2 (docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md):
 *
 *   1. Item image — the inventory item image, read-only (edited in the Items
 *      tab), and its upscaled copy; a Lanczos-only upscale is a visible hint;
 *   2. Empty shoe — one empty shoe in side view, always an image edit of
 *      the item image: thumbnail, gate icon, the refused attempts,
 *      Regenerate (1 image job, shared by every wearer);
 *   3. Cut-out — local;
 *   4. Mesh — a small 3D preview of the shoe alone with the insole (green)
 *      and topline (orange) overlay, Regenerate (1 mesh job, shared by every
 *      wearer);
 *   5. Insole — local: pitch, heel seat, heel rise, insole cover and the
 *      type gates.
 *
 * Everything comes from `garment_footwear.info` (GET
 * /characters/{n}/garments/{item}); every limit from the panel's `limits`
 * (`_garment_limits("footwear")`), every freshness from the server. The
 * shoe source belongs to the ITEM: a Regenerate posts `{step, force: true}`
 * to the existing run route and is shared by every wearer. The cell parts
 * (step label, gate icon, attempt thumbnails, run button and marks) are the
 * clothing grid's own (GarmentStepGrid / GarmentSteps).
 *
 * A step that is not accepted says why, distinctly: "Refused (gate)" — its
 * gates refused the result; "Failed (backend)" — the backend failed, with
 * the backend's own words; "Waiting — retry later" — the backend was busy or
 * media generation is off.
 */
import { Fragment } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { FreshnessBadge } from './FreshnessBadge'
import { GateChips, RunBadge, RunButton } from './GarmentSteps'
import { AttemptThumbs, GateIcon, StepLabel } from './GarmentStepGrid'
import { ERROR_STYLE, FOOTWEAR_STEP_LABELS, WARN_STYLE, num, upscaleText } from './garmentStyle'
import type { ChipSpec, GarmentLimits, GarmentRunBody } from './garmentStyle'
import { Model3DViewer } from './Model3DViewer'
import { RefImage } from './RefImage'
import { FOOTWEAR_STEPS, runMark, runSlot } from './useGarment'
import type { FootwearInfo, FootwearStepInfo, RunFeedback } from './useGarment'

const THUMB_H = 112
const THUMB_W = 112

/** Overlay colours of the mesh preview. */
const INSOLE_COLOR = '#3fb950'
const TOPLINE_COLOR = '#f0883e'

/** What each step makes and what a Regenerate costs (step name tooltips). */
const STEP_HELP: Record<string, string> = {
  source: 'Item image: the inventory item image, read-only here (it is edited in the Items tab), upscaled when it is small. One shoe source per item, shared by every wearer.',
  empty: 'Empty shoe: one empty shoe in side view, made by an image edit of the item image. Regenerate: 1 image job, shared by every wearer; the later steps run again.',
  cutout: 'Cut-out: the empty shoe cut out and squared as the mesh input — local, no hub job.',
  mesh: 'Mesh: a 3D mesh of the shoe alone, built from the cut-out. Regenerate: 1 mesh job, shared by every wearer; the insole is measured again.',
  insole: 'Insole: the shoe mesh measured on the CPU — pitch, heel seat, heel rise, insole cover and the type gates. Local, no hub job.',
}

const STATUS_TEXT: Record<FootwearStepInfo['status'], string> = {
  accepted: 'Accepted',
  refused: 'Refused (gate)',
  failed: 'Failed (backend)',
  waiting: 'Waiting — retry later',
  missing: 'Not made yet',
}

/** The pill of a step that is not accepted: its colour and tooltip. */
const PILL: Partial<Record<FootwearStepInfo['status'], { color: string; title: string }>> = {
  refused: { color: 'var(--danger, #f85149)', title: 'The gates refused the result' },
  failed: { color: 'var(--danger, #f85149)', title: 'The backend failed — not a verdict about the shoe' },
  waiting: { color: 'var(--warning, #d29922)', title: 'The backend was busy or media generation is off — the run is tried again later' },
}

// Record keys: footwear_gates.empty_gate / MESH_GATES, footwear_insole.INSOLE_GATES.
const EMPTY_CHIPS: ChipSpec[] = [
  { key: 'single_share', label: 'Largest part', scale: 100, unit: '%', digits: 1 },
  { key: 'aspect', label: 'Side-view aspect', scale: 1, unit: '', digits: 2 },
  { key: 'iou_below_topline', label: 'Match with the item image below the topline', scale: 100, unit: '%', digits: 1 },
]

const MESH_CHIPS: ChipSpec[] = [
  { key: 'component_share', label: 'Component share', scale: 100, unit: '%', digits: 1 },
  { key: 'mesh_iou', label: 'Side silhouette match', scale: 100, unit: '%', digits: 1 },
]

const INSOLE_CHIPS: ChipSpec[] = [
  { key: 'insole_cover', label: 'Insole cover', scale: 100, unit: '%', digits: 1 },
  { key: 'vamp_cover', label: 'Vamp cover (open shoe)', scale: 100, unit: '%', digits: 1 },
  { key: 'opening_share', label: 'Opening (solid mesh)', scale: 100, unit: '%', digits: 1 },
]

export function FootwearSteps({ info, limits, busy, feedback, onRun }: {
  info: FootwearInfo
  limits: GarmentLimits
  busy: boolean
  feedback?: RunFeedback
  onRun: (body: GarmentRunBody, slot?: string) => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const { steps } = info
  const order = FOOTWEAR_STEPS as readonly string[]
  const label = (step: string) => t(FOOTWEAR_STEP_LABELS[step] || step)
  const when = (s?: { created_at?: string | null }) => (s?.created_at ? formatDateTime(s.created_at, clockSettings()) : '')
  const stateLines = (step: string, s: FootwearStepInfo | undefined) => [
    label(step),
    t(STATUS_TEXT[s?.status || 'missing']),
    s?.backend || '',
    when(s),
    s?.error ? `${t('Error')}: ${s.error}` : '',
  ].filter(Boolean)
  /** The status word beside a step's numbers ('' when a pill says it). */
  const status = (s: FootwearStepInfo | undefined) => (s && PILL[s.status] ? '' : t(STATUS_TEXT[s?.status || 'missing']))
  const meta = (s: FootwearStepInfo | undefined) => ({ model: s?.backend || null, created_at: s?.created_at, freshness: s?.freshness })

  /** The status pills of a step: refused (gate) / failed (backend) / waiting, the run mark of this panel's own run. */
  const pills = (step: string, s: FootwearStepInfo | undefined): ReactNode => {
    const pill = s ? PILL[s.status] : undefined
    return (
      <>
        {s && pill ? (
          <span className="ga-run-badge" title={[t(pill.title), s.error || ''].filter(Boolean).join(' — ')}
            style={{ borderColor: pill.color, color: pill.color }}>
            {t(STATUS_TEXT[s.status])}
          </span>
        ) : null}
        <RunBadge mark={runMark(feedback, info, order, step)} />
      </>
    )
  }

  /** The cause of a failed or waiting step, visible (a refusal's reasons are in the gate icon). */
  const cause = (s: FootwearStepInfo | undefined): ReactNode => (
    s && (s.status === 'failed' || s.status === 'waiting') && s.error
      ? <span style={s.status === 'failed' ? ERROR_STYLE : WARN_STYLE}>{s.error}</span>
      : null
  )

  /** The outline of a step this panel's own run targets (queued / running / redone / starting). */
  const ring = (step: string): CSSProperties | undefined => {
    const mark = runMark(feedback, info, order, step)
    const color = mark === 'redo' ? 'var(--warning, #d29922)' : mark || feedback?.pending === runSlot({ step })
      ? 'var(--accent, #6aa9ff)' : null
    return color ? { outline: `2px solid ${color}`, outlineOffset: -1 } : undefined
  }

  const cell = (children: ReactNode, step: string) => (
    <div className="ga-step-grid-cell" style={ring(step)}>{children}</div>
  )

  const thumb = (url: string | null | undefined, alt: string, s?: FootwearStepInfo) => (url
    ? <RefImage key={url} src={url} width={THUMB_W} height={THUMB_H} label={alt} meta={s ? meta(s) : null} compact />
    : <div className="ga-step-grid-empty" title={t('No render yet')}>{t('No render yet')}</div>)

  // ── 1. Item image ──
  const source = steps.source
  const sm = source?.metrics || {}
  const upscale = source?.upscale
  const lanczos = String(upscale?.status || '') === 'lanczos'
  const sizes = num(sm.item_width) != null && num(sm.width) != null
    ? `${sm.item_width}×${sm.item_height} → ${sm.width}×${sm.height} px` : ''
  const sourceRow = cell(
    <>
      {thumb(info.item_image_url, `${label('source')} · ${t('Inventory')}`)}
      {source?.url ? thumb(source.url, `${label('source')} · ${t('Upscaled')}`, source) : null}
      <div className="ga-step-grid-side">
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          {pills('source', source)}
        </div>
        <span>{[status(source), sizes, when(source)].filter(Boolean).join(' · ')}</span>
        {upscale && !lanczos ? <span>{upscaleText(upscale, t)}</span> : null}
        {lanczos ? (
          <span style={WARN_STYLE} title={upscale?.reason ? String(upscale.reason) : undefined}>
            {t('No upscaler reachable — enlarged with Lanczos only')}
          </span>
        ) : null}
        <a href="#/items" className="ga-btn ga-btn-sm" title={t('The item image is part of the item — change it in the Items tab')}>
          {t('Edit in the Items tab')}
        </a>
      </div>
    </>, 'source')

  // ── 2. Empty shoe ──
  const empty = steps.empty
  const emptyBlocked = steps.source?.status !== 'accepted' ? t('Run the previous step first') : undefined
  const emptyAttempts = (empty?.attempts || [])
    .filter((a) => a.url)
    .map((a) => ({ attempt: a.attempt, url: a.url as string, gate: { ...a.gates, ok: a.ok ?? a.gates?.ok } }))
  const emptyErrors = (empty?.attempts || []).filter((a) => a.error)
    .map((a) => `${t('Attempt')} ${a.attempt}: ${a.error}`)
  const emptyRow = cell(
    <>
      {thumb(empty?.url, label('empty'), empty)}
      <div className="ga-step-grid-side">
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          {empty && empty.status !== 'missing' ? (
            <GateIcon specs={EMPTY_CHIPS} record={empty.gates} limits={limits.empty}
              extra={[...stateLines('empty', empty), ...emptyErrors]} />
          ) : null}
          {pills('empty', empty)}
        </div>
        {cause(empty)}
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'empty' })}
          disabled={busy || !!emptyBlocked}
          title={emptyBlocked || t('1 image job, shared by every wearer')}
          ariaLabel={`${empty?.url ? t('Regenerate') : t('Generate')} · ${label('empty')}`}
          label={empty?.url ? t('Regenerate') : t('Generate')}
          onClick={() => onRun({ step: 'empty', force: true })}
        />
        <AttemptThumbs attempts={emptyAttempts} label={label('empty')} chips={EMPTY_CHIPS} limits={limits.empty}
          view="side" />
      </div>
    </>, 'empty')

  // ── 3. Cut-out ──
  const cutout = steps.cutout
  const side = num(cutout?.metrics?.side)
  const cutoutRow = cell(
    <>
      {thumb(cutout?.url, label('cutout'), cutout)}
      <div className="ga-step-grid-side">
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          {pills('cutout', cutout)}
        </div>
        <span>{[status(cutout), side ? `${t('Square side')} ${side} px` : '',
          when(cutout)].filter(Boolean).join(' · ')}</span>
        <span>{t('Local, no hub job')}</span>
      </div>
    </>, 'cutout')

  // ── 4. Mesh ──
  const mesh = steps.mesh
  const meshBlocked = steps.cutout?.status !== 'accepted' ? t('Run the previous step first') : undefined
  const mm = mesh?.metrics || {}
  const meshText = [
    status(mesh),
    num(mm.tris_raw) != null && num(mm.tris_prepared) != null
      ? `${t('Triangles')} ${mm.tris_raw.toLocaleString()} → ${mm.tris_prepared.toLocaleString()}` : '',
    mesh?.backend || '',
    when(mesh),
  ].filter(Boolean).join(' · ')
  const meshAttempts = (mesh?.attempts || []).map((a, i) => `${t('Attempt')} ${num(a.attempt) ?? i + 1}: ${
    a.error || (a.gates?.reasons || []).join('; ') || (a.ok ? t('Accepted') : '–')}`)
  const overlay = info.insole?.overlay
  const polylines = [
    ...(overlay?.insole?.length ? [{ points: overlay.insole, color: INSOLE_COLOR }] : []),
    ...(overlay?.topline?.length ? [{ points: overlay.topline, color: TOPLINE_COLOR }] : []),
  ]
  const swatch = (color: string) => (
    <span aria-hidden style={{ display: 'inline-block', width: 14, height: 3, background: color, verticalAlign: 'middle', marginRight: 4 }} />
  )
  const meshRow = (
    <div className="ga-step-grid-row" style={{ flexDirection: 'column', alignItems: 'stretch', ...ring('mesh') }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {mesh && mesh.status !== 'missing' ? (
          <GateIcon specs={MESH_CHIPS} record={mesh.gates} limits={limits.mesh}
            extra={[meshText, ...meshAttempts]} />
        ) : null}
        {pills('mesh', mesh)}
        <span className="ga-hint" style={{ minWidth: 0 }}>{meshText}</span>
        {cause(mesh)}
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'mesh' })}
          disabled={busy || !!meshBlocked}
          title={meshBlocked || t('1 mesh job, shared by every wearer')}
          ariaLabel={`${mesh?.url ? t('Regenerate') : t('Generate')} · ${label('mesh')}`}
          label={mesh?.url ? t('Regenerate') : t('Generate')}
          onClick={() => onRun({ step: 'mesh', force: true })}
        />
      </div>
      {info.mesh_url ? (
        <>
          <Model3DViewer key={info.mesh_url} url={info.mesh_url} format="glb" height={260}
            freshness={mesh?.freshness} polylines={polylines} />
          {polylines.length ? (
            <div className="ga-hint" style={{ display: 'flex', gap: 12 }}>
              <span>{swatch(INSOLE_COLOR)}{t('Insole')}</span>
              <span>{swatch(TOPLINE_COLOR)}{t('Topline')}</span>
            </div>
          ) : null}
        </>
      ) : (
        <div className="ga-step-grid-empty" style={{ width: '100%', height: 60 }}>{t('No mesh yet')}</div>
      )}
    </div>
  )

  // ── 5. Insole ──
  const insoleStep = steps.insole
  const nominal = info.insole?.nominal
  const cm = (v: number | null | undefined) => (num(v) != null ? `${((v as number) * 100).toFixed(1)} cm` : '–')
  const deg = (v: number | null | undefined) => (num(v) != null ? `${(v as number).toFixed(1)}°` : '–')
  const insoleGates = insoleStep && insoleStep.status !== 'missing' ? insoleStep.gates : null
  const cover = num(insoleGates?.insole_cover)
  const refusal = insoleGates && typeof (insoleGates as { refusal?: unknown }).refusal === 'string'
    ? String((insoleGates as { refusal?: unknown }).refusal) : ''
  const insoleRow = cell(
    <div className="ga-step-grid-side" style={{ flex: '1 1 auto' }}>
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
        {insoleGates ? (
          <GateIcon specs={INSOLE_CHIPS} record={insoleGates} limits={limits.insole}
            extra={stateLines('insole', insoleStep)} />
        ) : null}
        {pills('insole', insoleStep)}
        {insoleStep && insoleStep.status !== 'missing' ? <FreshnessBadge freshness={insoleStep.freshness} compact /> : null}
        <span>{[status(insoleStep), when(insoleStep)].filter(Boolean).join(' · ')}</span>
      </div>
      {nominal ? (
        <span title={t('Per-item numbers at a nominal shoe length of 26 cm')}>
          {[
            `${t('Pitch')} ${deg(nominal.pitch_deg)}`,
            `${t('Heel seat')} ${cm(nominal.heel_seat_h_m)}`,
            `${t('Heel rise')} ${cm(nominal.heel_rise_m)}`,
            `${t('Insole cover')} ${cover != null ? `${(cover * 100).toFixed(1)} %` : '–'}`,
          ].join(' · ')}
        </span>
      ) : null}
      {insoleGates ? (
        <>
          <span>{t('Type gates')}:</span>
          <GateChips specs={INSOLE_CHIPS} record={insoleGates} limits={limits.insole} />
          <span>{t('Boot: judged at the fit (topline above the ankle)')}</span>
        </>
      ) : null}
      {refusal ? <span style={ERROR_STYLE}>{t(refusal)}</span> : null}
      <span>{t('Local, no hub job')}</span>
    </div>, 'insole')

  const rows: Array<[string, ReactNode]> = [
    ['source', sourceRow], ['empty', emptyRow], ['cutout', cutoutRow], ['mesh', meshRow], ['insole', insoleRow],
  ]
  return (
    <div className="ga-step-grid" style={{ gridTemplateColumns: 'minmax(110px, 140px) minmax(0, 1fr)' }}>
      {rows.map(([step, row]) => (
        <Fragment key={step}>
          <StepLabel garment={info} step={step} label={FOOTWEAR_STEP_LABELS[step]} help={STEP_HELP[step]} />
          {row}
        </Fragment>
      ))}
    </div>
  )
}
