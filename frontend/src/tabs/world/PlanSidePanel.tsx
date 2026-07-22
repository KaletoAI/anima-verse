/**
 * PlanSidePanel — the context column right of the floor plan. Everything that
 * belongs to the SELECTED room and is not a click tool lives here: room info
 * (name, rotation, always-visible), the animation-marker vocabulary + the
 * room's marker list. Purely presentational — RoomLayoutEditor owns the state
 * and hands in the callbacks.
 */
import { useI18n } from '../../i18n/I18nProvider'
import type { Room } from './worldTypes'

interface PlanSidePanelProps {
  /** Selected room WITH a layout, or null. */
  room: Room | null
  /** Open animation-clip vocabulary — the marker tool drops this kind. */
  clipKinds: string[]
  markerKind: string
  onMarkerKind: (kind: string) => void
  markerSel: number | null
  onSelectMarker: (index: number | null) => void
  onAlwaysVisible: (value: boolean) => void
}

export function PlanSidePanel({
  room, clipKinds, markerKind, onMarkerKind, markerSel, onSelectMarker,
  onAlwaysVisible,
}: PlanSidePanelProps) {
  const { t } = useI18n()
  const layout = room?.layout

  if (!room || !layout) {
    return (
      <div className="ga-plan-panel">
        <span className="ga-hint">
          {t('Select a room on the plan — the tools work on it.')}
        </span>
      </div>
    )
  }

  const markers = layout.markers || []
  return (
    <div className="ga-plan-panel">
      <div className="ga-plan-panel-title">{room.name || room.id}</div>
      <span className="ga-hint">
        {t('Rotation')}: {layout.rotation || 0}°
        {layout.outline?.length ? ` · ⬠ ${layout.outline.length}` : ''}
      </span>
      <label className="ga-check-row" style={{ fontSize: '0.82em' }}
        title={t('Show this room permanently in the 3D client, independent of the interior view — for outdoor rooms the building model does not cover.')}>
        <input
          type="checkbox"
          checked={!!layout.always_visible}
          onChange={(e) => onAlwaysVisible(e.target.checked)}
        />
        <span>{t('Always visible')}</span>
      </label>

      {clipKinds.length ? (
        <>
          <div className="ga-plan-panel-title">{t('Markers')}</div>
          <select
            className="ga-input"
            style={{ width: '100%' }}
            value={markerKind}
            onChange={(e) => onMarkerKind(e.target.value)}
            title={t('Animation kind the 🎯 tool drops — the open clip vocabulary, nothing hardcoded.')}
          >
            {clipKinds.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </>
      ) : null}
      {markers.map((m, i) => (
        <button
          key={`${m.animation}-${i}`}
          type="button"
          className={`ga-btn ga-btn-sm${markerSel === i ? ' ga-btn-primary' : ''}`}
          style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          onClick={() => onSelectMarker(markerSel === i ? null : i)}
          title={t('Select this marker to adjust facing/height or remove it.')}
        >
          🎯 {i + 1} · {m.animation}
        </button>
      ))}
    </div>
  )
}
