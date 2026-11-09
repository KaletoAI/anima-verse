/**
 * WardrobeGarment — own-mesh outfit pieces in the Wardrobe (plan
 * docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md, Task 5).
 *
 * A piece with the item flag `outfit_piece.own_mesh` becomes a fitted 3D
 * mesh of its own on characters of the base-body pipeline instead of being
 * painted onto the body; the flag lives on the ITEM, so the toggle applies
 * to every wearer (2D images stay unchanged). Per row: the toggle, the
 * status chip (server: `garment_set.piece_status`) and an expandable panel
 * with the clothing chain (worn → piece-only → cut-outs → mesh → fit) —
 * every step with its gate chips (limits from the server) and Regenerate,
 * the preview with its freshness badge and the step overview (ModelSteps).
 *
 * Backend: GET /characters/{n}/garments (overview: pipeline, row status
 * incl. the pieces it is fitted over, worn pieces over each other), GET /characters/{n}/garments/{item} (the panel,
 * polled while a step runs — useGarment), POST
 * /characters/{n}/garments/{item}/run {step?, view?, force?} (409 while a
 * garment run of the character goes — shown beside the clicked button,
 * useGarmentRun), GET + PUT /inventory/items/{item}
 * (the flag; the PUT replaces the whole outfit_piece, so it is read first).
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useClockSettings } from '../../lib/clockFormat'
import { GarmentFailure, GarmentSteps, RunButton, RunStatusLine } from './GarmentSteps'
import type { ImageStepSpec } from './GarmentSteps'
import { ROW, WARN_STYLE } from './garmentStyle'
import type { ChipSpec, GarmentRunBody } from './garmentStyle'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import type { ModelStep } from './ModelSteps'
import { garmentRunning, useGarment, useGarmentRun } from './useGarment'
import type { GarmentItemInfo, PieceStatus } from './useGarment'

/** The item flag's explanation (also the hint of the item editor). */
const OWN_MESH_HINT = 'Characters on the base-body pipeline get this piece as a fitted 3D mesh of its own instead of painting it onto the body. Applies to every wearer; 2D images stay unchanged.'

const STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  worn: 'Worn views',
  ghost: 'Piece-only views',
  cutout: 'Cut-outs',
  mesh: 'Mesh',
  fit: 'Fit',
}

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Piece description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  fit_algorithm_updated: 'Fit algorithm updated',
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

/** The row chip: running, painted on (and why), or how far the chain got. */
export function PieceStatusChip({ status }: { status: PieceStatus }) {
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
export function OwnMeshToggle({ itemId, checked, disabled, onChanged }: {
  itemId: string
  checked: boolean
  disabled?: boolean
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
      title={t(OWN_MESH_HINT)}>
      <input type="checkbox" checked={checked} disabled={disabled || busy}
        onChange={(e) => { void flip(e.target.checked) }} />
      <span>{t('Own mesh (every wearer)')}</span>
    </label>
  )
}

/** The expanded panel of one own-mesh piece. */
export function GarmentPiecePanel({ character, itemId, onStatus }: {
  character: string
  itemId: string
  /** The row chip follows the panel's polls. */
  onStatus: (itemId: string, status: PieceStatus) => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const url = character && itemId ? `/characters/${enc}/garments/${encodeURIComponent(itemId)}` : null
  const { info, startPoll } = useGarment<GarmentItemInfo & { steps?: ModelStep[] }>(url)
  const onError = useCallback((message: string) => { toast(t('Error') + ': ' + message, 'error') }, [t, toast])
  const { feedback, start } = useGarmentRun(character, itemId, info, startPoll, onError)

  useEffect(() => { if (info?.status) onStatus(itemId, info.status) }, [info, itemId, onStatus])

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.pipeline) {
    return <div className="ga-hint">{t('Own meshes need the base body pipeline — switch it on in the Base body tab')}</div>
  }
  const garment = info.garment
  const busy = feedback.pending !== null || garmentRunning(info)
  const onRun = (body: GarmentRunBody, slot?: string) => { void start(body, slot) }
  return (
    <div className="ga-form" style={{ padding: 8, borderRadius: 6, background: 'rgba(0,0,0,0.18)' }}>
      <RunStatusLine garment={garment} feedback={feedback} stepLabels={STEP_LABELS} />
      <div style={ROW}>
        <PieceStatusChip status={info.status} />
        <RunButton
          feedback={feedback}
          slot="all"
          disabled={busy || !garment}
          title={t('Runs every step that is missing or out of date')}
          onClick={() => onRun({}, 'all')}
          label={garment?.running_step === 'queued' ? t('Queued')
            : garmentRunning(info) ? t('Generating…') : t('Run all')}
          stepLabels={STEP_LABELS}
        />
      </div>
      {info.status.painted && !garmentRunning(info) ? (
        <div className="ga-hint" style={WARN_STYLE}>
          {t('Until it has an accepted fit, the outfit model paints this piece onto the body.')}
        </div>
      ) : null}
      {garment && garment.stale_reasons.length ? (
        <div style={{ ...ROW, padding: 8, borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
          <span style={WARN_STYLE}>{garment.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}</span>
          <span className="ga-hint">{t('The previous mesh stays in use until the new one is fitted.')}</span>
          <RunButton feedback={feedback} slot="stale" disabled={busy} onClick={() => onRun({}, 'stale')}
            label={t('Regenerate')} stepLabels={STEP_LABELS} />
        </div>
      ) : null}
      <GarmentFailure garment={garment} stepLabels={STEP_LABELS} />

      <GarmentSteps
        garment={garment}
        imageSteps={IMAGE_STEPS}
        stepLabels={STEP_LABELS}
        limits={info.limits || {}}
        fitChips={FIT_CHIPS}
        busy={busy}
        onRun={onRun}
        lowFailedText="Distance tier failed — the full piece is used"
        compact
        feedback={feedback}
      />

      <div className="ga-fieldset-title">{t('Preview')}</div>
      {garment?.preview_url ? (
        <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={280}
          freshness={garment.preview_freshness}
          statusPanel={info.steps?.length ? <ModelSteps steps={info.steps} /> : undefined} />
      ) : (
        <>
          <div className="ga-hint">{t('No fitted mesh yet')}</div>
          {info.steps?.length ? <ModelSteps steps={info.steps} /> : null}
        </>
      )}
      <div className="ga-hint">
        {t('Clothing meshes have no collision yet — two own-mesh pieces worn over each other can intersect')}
      </div>
    </div>
  )
}
