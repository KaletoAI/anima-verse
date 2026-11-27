/**
 * PlanMarkerList — place-type picker and marker list for the selected room or
 * yard, shown inside the inspector's Markers panel. The 🎯 arm button lives in
 * the vertical toolbar.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { groupKeys, groupLabel } from './placeTypes'
import type { PoseGroupSpec } from './placeTypes'
import type { RoomLayout } from './worldTypes'

type Marker = NonNullable<RoomLayout['markers']>[number]

interface PlanMarkerListProps {
  /** The pose catalog's PLACE TYPES (`GET /poses` → `groups`) — the 🎯
   *  tool drops a marker of `markerGroup`; the select shows the label and
   *  stores the key. */
  groups: Record<string, PoseGroupSpec>
  markerGroup: string
  onMarkerGroup: (group: string) => void
  markers: Marker[]
  markerSel: number | null
  onSelectMarker: (index: number | null) => void
}

export function PlanMarkerList({
  groups, markerGroup, onMarkerGroup, markers, markerSel, onSelectMarker,
}: PlanMarkerListProps) {
  const { t } = useI18n()
  const keys = groupKeys(groups)

  return (
    <div className="ga-plan-panel">
      {keys.length ? (
        <select
          className="ga-input"
          value={markerGroup}
          onChange={(e) => onMarkerGroup(e.target.value)}
          title={t('Place type the 🎯 tool drops — a group of the pose catalog; the server seats characters on it.')}
        >
          {keys.map((k) => (
            <option key={k} value={k}>{groupLabel(groups, k)}</option>
          ))}
        </select>
      ) : null}
      {markers.map((m, i) => (
        <button
          key={m.id || `${m.group}-${i}`}
          type="button"
          className={`ga-btn ga-btn-sm${markerSel === i ? ' ga-btn-primary' : ''}`}
          style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          onClick={() => onSelectMarker(markerSel === i ? null : i)}
          title={t('Select this marker to adjust capacity, facing, height or the preview pose, or to remove it.')}
        >
          🎯 {i + 1} · {groupLabel(groups, m.group)}{(m.capacity || 1) > 1 ? ` ×${m.capacity}` : ''}
        </button>
      ))}
    </div>
  )
}
