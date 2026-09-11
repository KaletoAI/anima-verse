/**
 * PlanPropList — the props PLACED in the selected shape, as a pick list in
 * the side panel (📋 tool). It exists because a placed prop is otherwise only
 * reachable by clicking its footprint on the plan, and a small piece under a
 * bigger one, or one whose footprint hides in a crowded corner, takes several
 * cycling clicks to land on (user request 2026-09-12). Purely presentational:
 * the editor owns the selection and closes the list once a row is picked.
 *
 * Rows read from the bottom of the stack up, in placement order — the same
 * order the plan cycles through, so the number in front of a row matches the
 * counter the prop strip shows for it.
 */
import { useI18n } from '../../i18n/I18nProvider'
import type { PropDims } from './PlanCanvas'
import type { RoomPropPlacement } from './worldTypes'

interface PlanPropListProps {
  /** Name of the shape whose placements are listed (room name or yard). */
  roomName: string
  placements: RoomPropPlacement[]
  /** Library names per prop id — a placement without a record shows its id. */
  dims: Record<string, PropDims>
  /** Currently selected placement index, or null. */
  selected: number | null
  onPick: (index: number) => void
  onClose: () => void
}

export function PlanPropList({
  roomName, placements, dims, selected, onPick, onClose,
}: PlanPropListProps) {
  const { t } = useI18n()
  const nameOf = (p: RoomPropPlacement) =>
    p.label || dims[p.prop_id]?.name || p.prop_id
  return (
    <>
      <div className="ga-plan-panel-title" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {t('Props in {room}').replace('{room}', roomName)}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          onClick={onClose}
          title={t('Close the list without changing the selection.')}
        >
          ✕
        </button>
      </div>
      {placements.length ? placements.map((p, i) => {
        // "on" is the support's placement id — name the piece it stands on,
        // so a candle and the table it sits on read as what they are.
        const support = p.on
          ? placements.find((q) => q.id === p.on) : undefined
        return (
          <button
            key={p.id || `${p.prop_id}-${i}`}
            type="button"
            className={`ga-btn ga-btn-sm${selected === i ? ' ga-btn-primary' : ''}`}
            style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                     textAlign: 'left' }}
            onClick={() => onPick(i)}
            title={t('Select this prop — its strip opens below the plan.')}
          >
            {i + 1} · {nameOf(p)}
            {support ? ` ↳ ${nameOf(support)}` : ''}
          </button>
        )
      }) : (
        <span className="ga-hint">
          {t('No props placed here yet — the 🪑 library or ✨ Furnish put some down.')}
        </span>
      )}
    </>
  )
}
