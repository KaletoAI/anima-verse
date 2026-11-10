/**
 * WardrobeGarment — own-mesh outfit pieces in the Wardrobe (plan
 * docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md, Task 5).
 *
 * A piece with the item flag `outfit_piece.own_mesh` becomes a fitted 3D
 * mesh of its own on characters of the base-body pipeline instead of being
 * painted onto the body; the flag lives on the ITEM, so the toggle applies
 * to every wearer (2D images stay unchanged). Per row: the toggle, the
 * status chip (server: `garment_set.piece_status`) and "Mesh steps", which
 * opens the piece's dialog (GarmentPieceDialog): the clothing chain (worn →
 * piece-only → cut-outs → mesh → fit) as a compact grid — thumbnails, one
 * gate icon per image with the chips in its tooltip, Regenerate per view —
 * beside the fitted preview with its freshness badge, its fit numbers and
 * the step overview (ModelSteps).
 *
 * Backend: GET /characters/{n}/garments (overview: pipeline, row status
 * incl. the pieces it is fitted over, worn pieces over each other), GET
 * /characters/{n}/garments/{item} (the dialog, polled while a step runs —
 * useGarment), POST /characters/{n}/garments/{item}/run {step?, view?,
 * force?} (a run behind the character's other garment runs is queued; the
 * click answers on its button and tile — useGarmentRun), GET + PUT
 * /inventory/items/{item}
 * (the flag; the PUT replaces the whole outfit_piece, so it is read first).
 */
import { useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useClockSettings } from '../../lib/clockFormat'
import { GarmentFailure, GateChips, RefitNotice, RunButton, RunStatusLine } from './GarmentSteps'
import { GarmentStepGrid } from './GarmentStepGrid'
import type { ImageStepSpec } from './GarmentSteps'
import { FOOTWEAR_STEP_LABELS, ROW, WARN_STYLE, meshNotReadyText } from './garmentStyle'
import type { ChipSpec, GarmentRunBody } from './garmentStyle'
import { FootwearSteps } from './FootwearSteps'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import type { ModelStep } from './ModelSteps'
import { footwearOf, garmentRunning, useGarment, useGarmentRun } from './useGarment'
import type { GarmentItemInfo, PieceStatus } from './useGarment'

/** The item flag's explanation (also the hint of the item editor). */
const OWN_MESH_HINT = 'Characters on the base-body pipeline get this piece as a fitted 3D mesh of its own instead of painting it onto the body. Applies to every wearer; 2D images stay unchanged.'

/** A piece worn in slot feet alone is footwear (`garment_set.garment_kind_of`): a rigid shoe. */
const OWN_MESH_SHOE_HINT = "Made once per item from the item image; fitted onto each wearer's foot on the CPU. Boots and sandals are not supported yet; socks stay painted."

const STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  worn: 'Worn views',
  ghost: 'Piece-only views',
  cutout: 'Cut-outs',
  mesh: 'Mesh',
  fit: 'Fit',
  // Footwear (the row chip of a shoe while it runs).
  source: 'Item image',
  empty: 'Empty shoe',
  insole: 'Insole',
}

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Piece description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  fit_algorithm_updated: 'Fit algorithm updated',
  // Footwear (garment_footwear.info).
  item_image_changed: 'Item image changed',
  source_version_changed: 'Older source version',
  analysis_updated: 'Older analysis version',
}

const STATE_LABELS: Record<PieceStatus['state'], string> = {
  running: 'Generating…',
  fitted: 'Fitted',
  mesh: 'Mesh ready',
  images: 'Images ready',
  missing: 'Not made yet',
}

// Record keys: garment_gates.worn_gate / ghost_clothing_gate, garment_fit.clothing_metrics.
// The clothing image records are fractions of the figure height, not pixels.
const WORN_CHIPS: ChipSpec[] = [
  { key: 'garment_share', label: 'Piece area', scale: 100, unit: '%', digits: 1 },
  { key: 'outside_dRGB', label: 'Colour change outside the piece', scale: 1, unit: '', digits: 2 },
  { key: 'outside_xor', label: 'Outline change outside the piece', scale: 100, unit: '%', digits: 2 },
  { key: 'head_garment', label: 'Head changed', scale: 100, unit: '%', digits: 1, gatedKey: 'head_gated' },
]

const GHOST_CHIPS: ChipSpec[] = [
  { key: 'top_dy', label: 'Top offset', scale: 100, unit: '%', digits: 2 },
  { key: 'centre_dx', label: 'Centre offset', scale: 100, unit: '%', digits: 2 },
  { key: 'w_ratio', label: 'Width ratio', scale: 1, unit: '', digits: 3 },
  { key: 'skin_left', label: 'Skin left', scale: 100, unit: '%', digits: 2 },
  { key: 'outside', label: 'Outside the worn piece', scale: 100, unit: '%', digits: 1 },
  { key: 'neck_fill', label: 'Neckline filled', scale: 100, unit: '%', digits: 0 },
  // The correction applied before the gate (garment_images._register); the offsets
  // above are its residual. Fractions of the figure height / a factor.
  { key: 'reg_shift', label: 'Registration shift', scale: 100, unit: '%', digits: 2 },
  { key: 'reg_scale', label: 'Registration scale', scale: 1, unit: '', digits: 3 },
]

const FIT_CHIPS: ChipSpec[] = [
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'deep_push_share', label: 'Pushed > 3 cm', scale: 100, unit: '%', digits: 1 },
  { key: 'largest_component_share', label: 'Largest part', scale: 100, unit: '%', digits: 1 },
  { key: 'rigged_inside_share', label: 'Inside the body', scale: 100, unit: '%', digits: 2 },
  // Reported, not gated.
  { key: 'rigged_clearance_p1_m', label: 'Clearance (p1)', scale: 1000, unit: 'mm', digits: 1 },
]

const IMAGE_STEPS: ImageStepSpec[] = [
  { step: 'worn', chips: WORN_CHIPS },
  { step: 'ghost', chips: GHOST_CHIPS },
  { step: 'cutout' },
]

const CHIP: CSSProperties = {
  display: 'inline-block', fontSize: '0.7em', padding: '1px 6px', borderRadius: 8,
  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%',
}

/** The row chip: running, painted on / missing (and why), or how far the chain got. */
export function PieceStatusChip({ status, name }: { status: PieceStatus; name: string }) {
  const { t } = useI18n()
  const progress = t(STATE_LABELS[status.state] || status.state)
  let text = progress
  let color = 'rgba(255,255,255,0.25)'
  if (status.state === 'running') {
    // Waiting behind the character's other garment runs: "Queued", not "Generating…".
    text = status.step === 'queued'
      ? t('Queued')
      : `${progress} ${t(STEP_LABELS[status.step || ''] || status.step || '')}`.trim()
    color = 'var(--accent, #6aa9ff)'
  } else if (status.painted) {
    text = `${t('Painted on')}: ${t(status.reason || '')}`
    color = 'var(--warning, #d29922)'
  } else if (status.missing) {
    // Mesh mode: not painted into the outfit body, so not shown until the mesh is accepted.
    text = meshNotReadyText(t, name, status.reason)
    color = 'var(--warning, #d29922)'
  } else if (status.state === 'fitted') {
    color = 'var(--success, #3fb950)'
    // Layered over the worn pieces under it (garment_layers); one without a fit is painted on.
    if (status.over?.length) text = t('Fitted over {items}').replace('{items}', status.over.join(', '))
    if (status.without?.length) text += ` · ${t('without {items}').replace('{items}', status.without.join(', '))}`
  }
  return (
    <span style={{ ...CHIP, border: `1px solid ${color}` }} title={`${text} · ${progress}`}>{text}</span>
  )
}

/** The item flag. The PUT replaces the whole outfit_piece, so the stored
 *  one is read first and only `own_mesh` changes. */
export function OwnMeshToggle({ itemId, checked, disabled, feet = false, onChanged }: {
  itemId: string
  checked: boolean
  disabled?: boolean
  /** A piece worn in slot feet alone: a rigid shoe (own label and hint). */
  feet?: boolean
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const flip = async (own: boolean) => {
    if (busy) return
    setBusy(true)
    try {
      const url = `/inventory/items/${encodeURIComponent(itemId)}`
      const { item } = await apiGet<{ item: { outfit_piece?: Record<string, unknown> } }>(url)
      await apiPut(url, { outfit_piece: { ...(item.outfit_piece || {}), own_mesh: own } })
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: '0.75em' }}
      title={t(feet ? OWN_MESH_SHOE_HINT : OWN_MESH_HINT)}>
      <input type="checkbox" checked={checked} disabled={disabled || busy}
        onChange={(e) => { void flip(e.target.checked) }} />
      <span>{feet ? t('Own mesh — shoe (rigid)') : t('Own mesh (every wearer)')}</span>
    </label>
  )
}

/** The steps dialog of one own-mesh piece: a wide modal (portal to
 *  document.body) — top bar with the piece, its ONE status (state, queue
 *  place or running step), Run all and close; left the chain as a compact
 *  grid (GarmentStepGrid), right the fitted preview with its fit numbers,
 *  the failure and the hints. Escape or a click beside it closes it; a run
 *  goes on without it (the row chip keeps showing it). */
export function GarmentPieceDialog({ character, itemId, name, onStatus, onClose }: {
  character: string
  itemId: string
  /** The piece's display name. */
  name: string
  /** The row chip follows the dialog's polls. */
  onStatus: (itemId: string, status: PieceStatus) => void
  onClose: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const enc = encodeURIComponent(character)
  const url = character && itemId ? `/characters/${enc}/garments/${encodeURIComponent(itemId)}` : null
  const { info, startPoll } = useGarment<GarmentItemInfo & { steps?: ModelStep[] }>(url)
  const { feedback, start, cancel } = useGarmentRun(character, itemId, info, startPoll)

  useEffect(() => { if (info?.status) onStatus(itemId, info.status) }, [info, itemId, onStatus])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const garment = info?.garment ?? null
  // Kind footwear: the shoe source steps of the item (garment_footwear.info), not the clothing chain.
  const footwear = footwearOf(info)
  const runState = footwear ?? garment
  const stepLabels = footwear ? FOOTWEAR_STEP_LABELS : STEP_LABELS
  const running = garmentRunning(info)
  const busy = feedback.pending !== null || running
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  const fit = garment?.steps.fit
  const fitRecord = fit && fit.status !== 'missing' ? fit.metrics : null

  let body: ReactNode
  if (!info) {
    body = <div className="ga-hint">{t('Loading…')}</div>
  } else if (!info.pipeline) {
    body = <div className="ga-hint">{t('Own meshes need the base body pipeline — switch it on in the Base body tab')}</div>
  } else if (footwear) {
    body = (
      <div className="ga-garment-dialog-body">
        <div className="ga-garment-dialog-col">
          {footwear.stale_reasons.length ? (
            <div style={{ ...ROW, gap: 8, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE} title={t('The shown shoe stays in use until the new one is made.')}>
                {footwear.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              </span>
              <RunButton feedback={feedback} slot="stale" disabled={busy} onClick={() => onRun({}, 'stale')}
                title={t('The shown shoe stays in use until the new one is made.')}
                label={t('Regenerate')} />
            </div>
          ) : null}
          <FootwearSteps info={footwear} limits={info.limits || {}} busy={busy} feedback={feedback} onRun={onRun} />
        </div>
        <div className="ga-garment-dialog-col">
          <div className="ga-step-grid-empty" style={{ width: '100%', height: 120 }}>{t('No fitted mesh yet')}</div>
          {info.steps?.length ? <ModelSteps steps={info.steps} /> : null}
          <GarmentFailure garment={footwear} stepLabels={FOOTWEAR_STEP_LABELS} />
          {info.status.missing && !running ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {meshNotReadyText(t, info.name || name, info.status.reason)}
            </div>
          ) : null}
          <div className="ga-hint">{t(OWN_MESH_SHOE_HINT)}</div>
        </div>
      </div>
    )
  } else {
    body = (
      <div className="ga-garment-dialog-body">
        <div className="ga-garment-dialog-col">
          {garment && garment.stale_reasons.length ? (
            <div style={{ ...ROW, gap: 8, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE} title={t('The previous mesh stays in use until the new one is fitted.')}>
                {garment.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              </span>
              <RunButton feedback={feedback} slot="stale" disabled={busy} onClick={() => onRun({}, 'stale')}
                title={t('The previous mesh stays in use until the new one is fitted.')}
                label={t('Regenerate')} />
            </div>
          ) : null}
          <RefitNotice garment={garment} feedback={feedback} busy={busy} onRun={onRun} />
          <GarmentStepGrid
            garment={garment}
            imageSteps={IMAGE_STEPS}
            stepLabels={STEP_LABELS}
            limits={info.limits || {}}
            fitChips={FIT_CHIPS}
            busy={busy}
            onRun={onRun}
            feedback={feedback}
          />
        </div>
        <div className="ga-garment-dialog-col">
          {garment?.preview_url ? (
            <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={430}
              freshness={garment.preview_freshness}
              statusPanel={info.steps?.length ? <ModelSteps steps={info.steps} /> : undefined} />
          ) : (
            <>
              <div className="ga-step-grid-empty" style={{ width: '100%', height: 120 }}>{t('No fitted mesh yet')}</div>
              {info.steps?.length ? <ModelSteps steps={info.steps} /> : null}
            </>
          )}
          <GateChips specs={FIT_CHIPS} record={fitRecord} limits={info.limits?.fit} />
          {fit?.low && fit.low.ok === false ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {t('Distance tier failed — the full piece is used')}: {fit.low.error}
            </div>
          ) : null}
          <GarmentFailure garment={garment} stepLabels={STEP_LABELS} />
          {info.status.painted && !running ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {t('Until it has an accepted fit, the outfit model paints this piece onto the body.')}
            </div>
          ) : null}
          {info.status.missing && !running ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {meshNotReadyText(t, info.name || name, info.status.reason)}
            </div>
          ) : null}
          <div className="ga-hint">
            {t('Pushed out of the body\'s collision capsules when moving (viewer: “Garment collision”); worn over another own-mesh piece, it is fitted over it.')}
          </div>
        </div>
      </div>
    )
  }

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal ga-garment-dialog" role="dialog" aria-modal="true"
        aria-label={`${t('Mesh steps')} · ${name}`}>
        <div className="ga-modal-header ga-garment-dialog-head">
          <span className="ga-garment-dialog-title" title={name}>{name}</span>
          <div style={{ flex: '1 1 auto', minWidth: 0, fontWeight: 400 }}>
            {running || feedback.pending !== null
              ? <RunStatusLine garment={runState} feedback={feedback} stepLabels={stepLabels} bare
                onCancel={() => { void cancel() }} />
              : info?.status ? <PieceStatusChip status={info.status} name={info.name || name} /> : null}
          </div>
          {info?.pipeline ? (
            <RunButton
              feedback={feedback}
              slot="all"
              primary
              disabled={busy || !garment}
              title={t('Runs every step that is missing or out of date')}
              onClick={() => onRun({}, 'all')}
              label={t('Run all')}
            />
          ) : null}
          <button type="button" className="ga-modal-close" aria-label={t('Close')} onClick={onClose}>×</button>
        </div>
        {body}
      </div>
    </div>,
    document.body,
  )
}
