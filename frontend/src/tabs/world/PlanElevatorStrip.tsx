/**
 * PlanElevatorStrip — the selected lift: move it by click, or nudge it on two
 * metre sliders.
 *
 * The lift is placed ONCE and serves every storey (the client builds the
 * shaft), so there is nothing per-level to edit here — only where it stands.
 * Its position is metres from the anchor pin (v6 Nr. 2), the same frame the
 * boundary is drawn in, which is why the sliders sweep the whole drawing
 * window rather than some normalized range.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { fmtM, rM } from './planGeometry'
import type { PlanView } from './planGeometry'
import type { PlanMode } from './PlanToolbar'

interface Props {
  /** Where the lift stands, in local metres around the pin. */
  at: [number, number]
  /** The drawing window — the sliders span exactly it. */
  view: PlanView
  /** The armed click mode; 'elevator' means the next plan click moves it. */
  mode: PlanMode
  onMode: (next: PlanMode) => void
  onMove: (at: [number, number]) => void
}

export function PlanElevatorStrip({ at, view, mode, onMode, onMove }: Props) {
  const { t } = useI18n()
  const arming = mode === 'elevator'
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>🛗 {t('Elevator')}:</span>
      <button
        type="button"
        className={`ga-btn ga-btn-sm${arming ? ' ga-btn-primary' : ''}`}
        onClick={() => onMode(arming ? '' : 'elevator')}
        title={t('Then click on the plan to move the elevator there.')}
      >
        ✥ {arming ? t('Click on the plan…') : t('Move')}
      </button>
      <SliderInput
        label="X"
        ariaLabel={t('Elevator position X (m)')}
        title={t('Fine-tune the elevator position: metres east of the anchor pin (negative = west).')}
        min={view.x0}
        max={view.x0 + view.size}
        step={0.05}
        fineStep={0.01}
        value={at[0]}
        onChange={(v) => onMove([rM(v), at[1]])}
        unit="m"
        sliderWidth={100}
        readback={<span style={{ minWidth: 56 }}>{fmtM(at[0])} m</span>}
      />
      <SliderInput
        label="Y"
        ariaLabel={t('Elevator position Y (m)')}
        title={t('Fine-tune the elevator position: metres south of the anchor pin (negative = north).')}
        min={view.z0}
        max={view.z0 + view.size}
        step={0.05}
        fineStep={0.01}
        value={at[1]}
        onChange={(v) => onMove([at[0], rM(v)])}
        unit="m"
        sliderWidth={100}
        readback={<span style={{ minWidth: 56 }}>{fmtM(at[1])} m</span>}
      />
    </div>
  )
}
