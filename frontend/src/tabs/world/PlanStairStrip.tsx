/**
 * PlanStairStrip — the selected staircase.
 *
 * A flight has exactly four things one does to it: turn it, move its foot,
 * pick its texture, take it away — and the two numbers that decide whether it FITS (its step
 * count and the metres of floor it eats) are stated here rather than left to
 * be measured on the plan.
 *
 * THOSE TWO NUMBERS ARE THE SERVER'S (§ B1 ``stairs``), never a formula
 * repeated on this side. `flight` absent means no composed block matches THIS
 * flight — the preview has not answered for the draft yet, or its answer still
 * describes the list as it was before the last delete or reorder. Either way
 * the row states no steps and no run rather than another flight's.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { fmtM, rM } from './planGeometry'
import type { PlanView } from './planGeometry'
import type { PlanMode } from './PlanToolbar'
import { SurfaceKindSelect } from './SurfaceKindSelect'
import type { SceneStairs, SurfaceKind } from './worldTypes'

/** One authored flight — `map3d.stairs[i]`. */
export interface StairFlight {
  at: [number, number]
  from_level: number
  dir_deg: number
  /** Surface-texture kind of every piece of the flight (v13); unset = the
   *  payload's stair colour. */
  texture_kind?: string
}

interface Props {
  /** Index in `map3d.stairs`, for the human-readable number. */
  index: number
  flight: StairFlight
  /** The COMPOSED block for this flight, or null while it is unknown. */
  composed: SceneStairs | null
  view: PlanView
  mode: PlanMode
  onMode: (next: PlanMode) => void
  /** The surface-texture library, for the flight's own kind. */
  surfaceKinds: SurfaceKind[]
  /** Replace this flight, or remove it when null is passed. */
  onPatch: (next: StairFlight | null) => void
}

export function PlanStairStrip({
  index, flight, composed, view, mode, onMode, surfaceKinds, onPatch,
}: Props) {
  const { t } = useI18n()
  const arming = mode === 'stairs'
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>
        🪜 {t('Staircase')} {index + 1}:
      </span>
      <span className="ga-hint">
        {(composed
          ? t('Level {a} → {b} · {n} steps · {run} m of floor · {deg}°')
            .replace('{n}', String(composed.steps))
            .replace('{run}', fmtM(composed.run_m))
          : t('Level {a} → {b} · {deg}° · measuring the flight…'))
          .replace('{a}', String(flight.from_level))
          .replace('{b}', String(flight.from_level + 1))
          .replace('{deg}', String(flight.dir_deg))}
      </span>
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        onClick={() => onPatch({ ...flight, dir_deg: (flight.dir_deg + 90) % 360 })}
        title={t('Turn the climb direction by a quarter — 0° climbs south (+y), 90° east (+x), 180° north (−y), 270° west (−x). The foot stays where it is.')}
      >
        ↻ {t('Rotate 90°')}
      </button>
      <button
        type="button"
        className={`ga-btn ga-btn-sm${arming ? ' ga-btn-primary' : ''}`}
        onClick={() => onMode(arming ? '' : 'stairs')}
        title={t('Then click on the plan to place ANOTHER flight on this level.')}
      >
        + {arming ? t('Click on the plan…') : t('Add')}
      </button>
      {/* Metres from the anchor pin, the frame the whole plan is drawn in —
          the foot is what the flight is anchored by. */}
      <SliderInput
        label="X"
        ariaLabel={t('Staircase foot X (m)')}
        title={t('Fine-tune the foot of the flight: metres east of the anchor pin (negative = west).')}
        min={view.x0}
        max={view.x0 + view.size}
        step={0.05}
        fineStep={0.01}
        value={flight.at[0]}
        onChange={(v) => onPatch({ ...flight, at: [rM(v), flight.at[1]] })}
        unit="m"
        sliderWidth={100}
        readback={<span style={{ minWidth: 56 }}>{fmtM(flight.at[0])} m</span>}
      />
      <SliderInput
        label="Y"
        ariaLabel={t('Staircase foot Y (m)')}
        title={t('Fine-tune the foot of the flight: metres south of the anchor pin (negative = north).')}
        min={view.z0}
        max={view.z0 + view.size}
        step={0.05}
        fineStep={0.01}
        value={flight.at[1]}
        onChange={(v) => onPatch({ ...flight, at: [flight.at[0], rM(v)] })}
        unit="m"
        sliderWidth={100}
        readback={<span style={{ minWidth: 56 }}>{fmtM(flight.at[1])} m</span>}
      />
      <SurfaceKindSelect
        label="Texture"
        labelWidth={52}
        value={flight.texture_kind || ''}
        kinds={surfaceKinds}
        emptyLabel={t('Stair colour')}
        title={t('Surface texture of this flight — treads, risers, stringers and both landing pads tile with it. Nothing chosen keeps the plain stair colour.')}
        onChange={(kind) => {
          const next = { ...flight, texture_kind: kind || undefined }
          if (!kind) delete next.texture_kind
          onPatch(next)
        }}
      />
      <button
        type="button"
        className="ga-btn ga-btn-sm ga-btn-danger"
        onClick={() => onPatch(null)}
        title={t('Remove this staircase — the storeys it connected fall back to the elevator, if there is one.')}
      >
        × {t('Remove')}
      </button>
    </div>
  )
}
