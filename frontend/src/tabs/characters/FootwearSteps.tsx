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
 *      and topline (orange) overlay and, on a boot, the tube slabs' rings
 *      (blue, an open slab red), Regenerate (1 mesh job, shared by every
 *      wearer);
 *   5. Insole — local: pitch, heel seat, heel rise, insole cover, on a boot
 *      the shaft (class, collar height, shaft top, closed share, cap removed),
 *      and the type gates;
 *   6. Fit — per body (the base model, then in outfit body mode mesh every
 *      stored outfit body): scale, width applied / needed, extension and
 *      slimming needed per side, lift, the collar above the ankle, on a boot
 *      the split (height per side, band, the four nodes) and the shaft chips,
 *      the fit gate chips; Re-fit (local, no hub job) and the width cap slider
 *      1.00–1.10, which saves on release and re-fits.
 *
 * Boots: docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md § 15.
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
import { Fragment, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { FreshnessBadge } from './FreshnessBadge'
import { GateChips, RunBadge, RunButton } from './GarmentSteps'
import { AttemptThumbs, GateIcon, StepLabel } from './GarmentStepGrid'
import { ERROR_STYLE, FOOTWEAR_STEP_LABELS, WARN_STYLE, num, upscaleText } from './garmentStyle'
import type { ChipSpec, GarmentLimits, GarmentRunBody } from './garmentStyle'
import { MeshJobFetch } from './MeshJobFetch'
import { Model3DViewer } from './Model3DViewer'
import { RefImage } from './RefImage'
import { FOOTWEAR_STEPS, runMark, runSlot } from './useGarment'
import type { FootwearFitRow, FootwearInfo, FootwearStepInfo, RunFeedback } from './useGarment'

const THUMB_H = 112
const THUMB_W = 112

/** Overlay colours of the mesh preview. */
const INSOLE_COLOR = '#3fb950'
const TOPLINE_COLOR = '#f0883e'
/** The third overlay colour: a boot's tube slabs (their measured extent); a slab without a closed ring in red. */
const SLAB_COLOR = '#58a6ff'
const SLAB_OPEN_COLOR = '#f85149'

/** What each step makes and what a Regenerate costs (step name tooltips). */
const STEP_HELP: Record<string, string> = {
  source: 'Item image: the inventory item image, read-only here (it is edited in the Items tab), upscaled when it is small. One shoe source per item, shared by every wearer.',
  empty: 'Empty shoe: one empty shoe in side view, made by an image edit of the item image. Regenerate: 1 image job, shared by every wearer; the later steps run again.',
  cutout: 'Cut-out: the empty shoe cut out and squared as the mesh input — local, no hub job.',
  mesh: 'Mesh: a 3D mesh of the shoe alone, built from the cut-out. Regenerate: 1 mesh job, shared by every wearer; the insole is measured again.',
  insole: "Insole: the shoe mesh measured on the CPU — pitch, heel seat, heel rise, insole cover, a boot's shaft and the type gates. Local, no hub job.",
  fit: "Fit: the shoe source placed on this wearer's foot on the CPU — one scale per pair, the foot extended onto the insole, the root lifted by the heel; a boot is split at the wearer's ankle into a rigid foot part and a shaft that follows the shin. One fit per body. Local, no hub job.",
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

// Gate keys: footwear_fit.FIT_GATES, then the body-cut gates footwear_cut.CUT_GATES the fit step runs and
// records under the same `gates` (record gates {value, limit, ok, gating}).
const FIT_CHIPS: ChipSpec[] = [
  { key: 'ball_placement_mm', label: 'Ball placement', scale: 1, unit: 'mm', digits: 1 },
  { key: 'lift_asymmetry_mm', label: 'Lift asymmetry', scale: 1, unit: 'mm', digits: 1 },
  { key: 'stand_floor_mm', label: 'Sole above the floor (stand)', scale: 1, unit: 'mm', digits: 1 },
  { key: 'slim_needed', label: 'Slimming needed', scale: 100, unit: '%', digits: 1 },
  // A split fit (a boot) adds footwear_fit.SHAFT_GATES; the stretch is recorded, not gated (`gating` false).
  { key: 'shaft_push_p95_m', label: 'Shaft push off the shin (p95)', scale: 1000, unit: 'mm', digits: 1 },
  { key: 'shaft_push_max_m', label: 'Shaft push off the shin (max)', scale: 1000, unit: 'mm', digits: 1 },
  { key: 'shaft_inside_share', label: 'Shaft inside the leg', scale: 100, unit: '%', digits: 2 },
  { key: 'seam_gap_p95_mm', label: 'Seam gap at the ankle', scale: 1, unit: 'mm', digits: 2 },
  { key: 'seam_stretch_max', label: 'Seam stretch at ±25°', scale: 1, unit: '×', digits: 1 },
  { key: 'shaft_leg_follow_deg', label: 'Shaft follows the shin', scale: 1, unit: '°', digits: 2 },
  { key: 'deep_outside', label: 'Foot outside the shoe (cut)', scale: 100, unit: '%', digits: 2 },
  { key: 'visible_poke', label: 'Foot poking through (cut)', scale: 100, unit: '%', digits: 2 },
  { key: 'throat_ledge_p95_mm', label: 'Throat ledge (cut)', scale: 1, unit: 'mm', digits: 1 },
  { key: 'toe_conform_m', label: 'Toe conform (cut)', scale: 1000, unit: 'mm', digits: 1 },
]

const FIT_STATUS_TEXT: Record<FootwearFitRow['status'], string> = {
  accepted: 'Fitted',
  stale: 'Out of date',
  outdated: 'Out of date',
  refused: 'Refused (gate)',
  missing: 'Not fitted yet',
}

/** The width cap slider's range (`footwear_fit.WIDTH_CAP_MIN` .. `WIDTH_CAP`). */
const CAP_MIN = 1.0
const CAP_MAX = 1.1

const INSOLE_CHIPS: ChipSpec[] = [
  { key: 'insole_cover', label: 'Insole cover', scale: 100, unit: '%', digits: 1 },
  { key: 'vamp_cover', label: 'Vamp cover (open shoe)', scale: 100, unit: '%', digits: 1 },
  { key: 'opening_share', label: 'Opening (solid mesh)', scale: 100, unit: '%', digits: 1 },
  // footwear_insole.SHAFT_GATES — a boot only (a shoe carries neither value).
  { key: 'shaft_closed_share', label: 'Shaft closed share', scale: 100, unit: '%', digits: 1 },
  { key: 'overknee', label: 'Collar height (over-knee limit)', scale: 100, unit: 'cm', digits: 1 },
]

/** The shaft classes of footwear_insole.SHAFT_CLASS_M. */
const SHAFT_CLASS_TEXT: Record<string, string> = {
  ankle: 'Ankle boot',
  knee: 'Knee-high boot',
  overknee: 'Over-knee boot',
}

export function FootwearSteps({ info, limits, busy, feedback, onRun, onWidthCap, meshFetchUrl = null,
  onMeshFetched }: {
  info: FootwearInfo
  limits: GarmentLimits
  busy: boolean
  feedback?: RunFeedback
  onRun: (body: GarmentRunBody, slot?: string) => void
  /** Save the width cap (null = back to the default) and re-fit; the caller posts. */
  onWidthCap: (cap: number | null) => void
  /** "Fetch finished job…" on the mesh row (MeshJobFetch): its POST url, null hides it. */
  meshFetchUrl?: string | null
  /** The mesh record changed through a fetched job: reload the panel. */
  onMeshFetched?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  // The slider's draft while it is dragged; saved on release (one fit, not one per step).
  const [capDraft, setCapDraft] = useState(info.width_cap)
  useEffect(() => { setCapDraft(info.width_cap) }, [info.width_cap])
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
  const slabs = overlay?.slabs || []
  const openSlabs = slabs.some((r) => !r.closed)
  const polylines = [
    ...(overlay?.insole?.length ? [{ points: overlay.insole, color: INSOLE_COLOR }] : []),
    ...(overlay?.topline?.length ? [{ points: overlay.topline, color: TOPLINE_COLOR }] : []),
    ...slabs.map((r) => ({ points: r.points, color: r.closed ? SLAB_COLOR : SLAB_OPEN_COLOR })),
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
        <MeshJobFetch url={meshBlocked ? null : meshFetchUrl} disabled={busy} onDone={() => onMeshFetched?.()} />
      </div>
      {info.mesh_url ? (
        <>
          <Model3DViewer key={info.mesh_url} url={info.mesh_url} format="glb" height={260}
            freshness={mesh?.freshness} polylines={polylines} />
          {polylines.length ? (
            <div className="ga-hint" style={{ display: 'flex', gap: 12 }}>
              <span>{swatch(INSOLE_COLOR)}{t('Insole')}</span>
              <span>{swatch(TOPLINE_COLOR)}{t('Topline')}</span>
              {slabs.length ? <span>{swatch(SLAB_COLOR)}{t('Shaft slabs')}</span> : null}
              {openSlabs ? <span>{swatch(SLAB_OPEN_COLOR)}{t('Open slab')}</span> : null}
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
  // Signed: a shod root can DESCEND (a bare body standing heel-up in its rest pose put into a flat shoe) — the
  // minus is the typographic one, as the chips print it.
  const cm = (v: number | null | undefined) => (num(v) != null ? `${((v as number) * 100).toFixed(1).replace('-', '−')} cm` : '–')
  const deg = (v: number | null | undefined) => (num(v) != null ? `${(v as number).toFixed(1)}°` : '–')
  const insoleGates = insoleStep && insoleStep.status !== 'missing' ? insoleStep.gates : null
  const cover = num(insoleGates?.insole_cover)
  const refusal = insoleGates && typeof (insoleGates as { refusal?: unknown }).refusal === 'string'
    ? String((insoleGates as { refusal?: unknown }).refusal) : ''
  const shaft = info.insole?.shaft
  const share = (v: number | null | undefined) => (num(v) != null ? `${((v as number) * 100).toFixed(1)} %` : '–')
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
      {shaft ? (
        <span title={t('The boot shaft at a nominal shoe length of 26 cm: collar height above the heel seat, the top closed tube slab above the ground')}>
          {[
            t(SHAFT_CLASS_TEXT[shaft.class] || shaft.class),
            `${t('Collar height')} ${cm(shaft.collar_h_m)}`,
            `${t('Shaft top')} ${cm(shaft.top_m)}`,
            `${t('Closed share')} ${share(shaft.closed_share)} (${t('{n} of {m} slabs')
              .replace('{n}', String(shaft.slabs_closed)).replace('{m}', String(shaft.slabs))})`,
            `${t('Cap removed')} ${t('{n} faces').replace('{n}', String(num(shaft.cap_removed) ?? 0))}`,
          ].join(' · ')}
        </span>
      ) : null}
      {insoleGates ? (
        <>
          <span>{t('Type gates')}:</span>
          <GateChips specs={INSOLE_CHIPS} record={insoleGates} limits={limits.insole} />
        </>
      ) : null}
      {refusal ? <span style={ERROR_STYLE}>{t(refusal)}</span> : null}
      <span>{t('Local, no hub job')}</span>
    </div>, 'insole')

  // ── 6. Fit (per body) ──
  const sourceReady = steps.mesh?.status === 'accepted' && steps.insole?.status === 'accepted'
  const fitTitle = `${t('Re-fit')}: ${t('local, no hub job')}`
  const mmText = (v: number | null) => (v != null ? `${v.toFixed(0)} mm` : '–')
  const pair = (m: Record<string, number>, key: string, f: (v: number) => string) => {
    const l = num(m[`${key}_left`])
    const r = num(m[`${key}_right`])
    return l == null && r == null ? '' : `L ${l != null ? f(l) : '–'} · R ${r != null ? f(r) : '–'}`
  }
  /** The fit gates as the chips read them: the values flat, the limits of the gates that refuse a fit
   *  (a recorded-only gate shows as "Reported, not gated"). */
  const fitChips = (row: FootwearFitRow) => {
    const record = Object.fromEntries(Object.entries(row.gates || {}).map(([k, g]) => [k, g?.value ?? null]))
    const gating = Object.fromEntries(Object.entries(limits.fit || {})
      .filter(([k]) => row.gates?.[k]?.gating !== false))
    return { record, gating }
  }
  const fitBody = (row: FootwearFitRow) => {
    const m = row.metrics || {}
    const label = row.base ? t('Base model') : t('Outfit body {id}').replace('{id}', row.body_id || '')
    const fitted = row.status !== 'missing' && row.status !== 'refused'
    const numbers = fitted ? [
      num(m.k_m_per_unit) != null ? `${t('Scale')} ${m.k_m_per_unit.toFixed(3)} m/unit` : '',
      num(m.length_m) != null ? `${t('Shoe length')} ${cm(m.length_m)}` : '',
      num(m.width_factor) != null
        ? `${t('Width')} ×${m.width_factor.toFixed(2)} ${t('applied')} · ${t('needed')} ${
          pair(m, 'width_needed', (v) => `×${v.toFixed(2)}`)}` : '',
      `${t('Foot extension')} ${pair(m, 'extension_deg', (v) => `${v.toFixed(1).replace('-', '−')}°`)}`,
    ].filter((x) => x && !x.endsWith(' ')) : []
    const liftM = fitted ? num(m.root_lift_m) : null
    const toeRoom = fitted ? `${t('Toe room')} ${pair(m, 'toe_room_mm', (v) => mmText(v))}` : ''
    const parts: ReactNode[] = [
      ...numbers,
      liftM != null ? (
        <span key="lift"
          title={liftM < 0 ? t('The root descends: this body stands heel-up in its rest pose') : undefined}>
          {t('Lift')} {cm(liftM)}
        </span>
      ) : null,
      toeRoom.endsWith(' ') ? null : toeRoom,
    ].filter((x) => x !== null && x !== '')
    const slim = fitted ? pair(m, 'slim_needed', (v) => `${(v * 100).toFixed(1)} %`) : ''
    const split = fitted ? row.split : null
    const sideNum = (key: 'y_m' | 'collar_above_ankle_mm', f: (v: number) => string) => {
      const l = num(split?.sides?.left?.[key])
      const r = num(split?.sides?.right?.[key])
      return l == null && r == null ? '' : `L ${l != null ? f(l) : '–'} · R ${r != null ? f(r) : '–'}`
    }
    const collar = sideNum('collar_above_ankle_mm', (v) => `${v.toFixed(0).replace('-', '−')} mm`)
    const nodes = split?.is_boot
      ? (['left', 'right'] as const).map((s) => {
        const parts = split.sides?.[s]?.parts || {}
        return `${s === 'left' ? 'L' : 'R'} ${num(parts.foot) ?? '–'} + ${num(parts.shaft) ?? '–'}`
      }).join(' · ') : ''
    const chips = fitChips(row)
    const pill = row.status === 'refused' ? PILL.refused : undefined
    const blocked = !row.body_id ? t('No base model yet') : !sourceReady ? t('Run the previous step first') : undefined
    return (
      <div key={row.body_id || 'base'} style={{ display: 'flex', flexDirection: 'column', gap: 2,
        padding: '4px 6px', borderRadius: 6, border: '1px solid var(--border, #30363d)' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong title={row.body_id || undefined}>{label}</strong>
          {pill ? (
            <span className="ga-run-badge" title={[t(pill.title), row.error || ''].filter(Boolean).join(' — ')}
              style={{ borderColor: pill.color, color: pill.color }}>{t(FIT_STATUS_TEXT[row.status])}</span>
          ) : row.status === 'stale' || row.status === 'outdated'
            ? <FreshnessBadge freshness={row.freshness} compact />
            : <span>{t(FIT_STATUS_TEXT[row.status])}</span>}
          {row.base ? <RunBadge mark={runMark(feedback, info, order, 'fit')} /> : null}
          <span className="ga-hint">{when(row)}</span>
          {row.base ? (
            <RunButton
              feedback={feedback}
              slot={runSlot({ step: 'fit' })}
              disabled={busy || !!blocked}
              title={blocked || fitTitle}
              ariaLabel={`${t('Re-fit')} · ${label}`}
              label={t('Re-fit')}
              onClick={() => onRun({ step: 'fit', force: true })}
            />
          ) : null}
        </div>
        {parts.length ? (
          <span>{parts.map((part, i) => <Fragment key={i}>{i ? ' · ' : ''}{part}</Fragment>)}</span>
        ) : null}
        {slim ? (
          <span title={t('Share of the ball width the forefoot slimming must take off — not applied yet')}>
            {t('Slimming needed')} {slim}
          </span>
        ) : null}
        {collar ? (
          <span title={t("The shoe's topline above the wearer's ankle; more than {mm} mm makes it a boot, split at the ankle")
            .replace('{mm}', String(Math.round((num(split?.margin_m) ?? 0.01) * 1000)))}>
            {t('Collar above the ankle')} {collar}
          </span>
        ) : null}
        {split?.is_boot ? (
          <span title={t("Split at the wearer's ankle: a rigid foot part below the band, a shaft above it that follows the shin; the band blends the two")}>
            {[
              `${t('Split height')} ${sideNum('y_m', (v) => cm(v))}`,
              num(split.band_m) != null ? `${t('Band')} ±${cm(split.band_m)}` : '',
              row.shaft?.class ? t(SHAFT_CLASS_TEXT[row.shaft.class] || row.shaft.class) : '',
            ].filter(Boolean).join(' · ')}
          </span>
        ) : null}
        {nodes ? (
          <span title={t('Four nodes per pair: per side the foot part and the shaft (triangles each)')}>
            {t('Nodes foot + shaft')} {nodes}
          </span>
        ) : null}
        {row.status === 'refused' && row.error ? <span style={ERROR_STYLE}>{row.error}</span> : null}
        {!row.base && row.status === 'missing'
          ? <span className="ga-hint">{t('Fitted on this body when the outfit model is assembled')}</span> : null}
        {fitted ? <GateChips specs={FIT_CHIPS} record={chips.record} limits={chips.gating} /> : null}
      </div>
    )
  }
  const capChanged = Math.abs(capDraft - info.width_cap) > 1e-6
  const commitCap = () => { if (capChanged) onWidthCap(Math.round(capDraft * 100) / 100) }
  const fitRow = (
    <div className="ga-step-grid-row" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 6, ...ring('fit') }}>
      {(info.fits?.length ? info.fits : []).map(fitBody)}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
        title={t("How much wider than the shoe the foot may make it (1.00–1.10). Saved on release, then re-fitted — local, no hub job.")}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Width cap')}
          <input type="range" min={CAP_MIN} max={CAP_MAX} step={0.01} value={capDraft}
            disabled={busy} style={{ width: 140 }}
            onChange={(e) => setCapDraft(Number(e.target.value))}
            onPointerUp={commitCap} onKeyUp={commitCap} onBlur={commitCap} />
          <span>×{capDraft.toFixed(2)}</span>
        </label>
        {info.width_cap < CAP_MAX - 1e-6 ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => onWidthCap(null)}>{t('Default')}</button>
        ) : null}
      </div>
    </div>
  )

  const rows: Array<[string, ReactNode]> = [
    ['source', sourceRow], ['empty', emptyRow], ['cutout', cutoutRow], ['mesh', meshRow], ['insole', insoleRow],
    ['fit', fitRow],
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
