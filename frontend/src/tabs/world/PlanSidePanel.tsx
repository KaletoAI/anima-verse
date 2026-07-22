/**
 * PlanSidePanel — the context column right of the floor plan. Everything that
 * belongs to the SELECTED room and is not a click tool lives here: room info
 * (name, rotation, always-visible), the animation-marker vocabulary + the
 * room's marker list, and the room shell's surface kinds. The 🪑 tool opens
 * the prop palette below them. Purely presentational — RoomLayoutEditor owns
 * the state and hands in the callbacks.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { PropsPalette } from './PropsPalette'
import type { PropFull } from '../props/propTypes'
import type { Room } from './worldTypes'

/** The two shell surfaces a room may skin — mirrors layout.surfaces. */
const SURFACE_SLOTS: Array<{ key: 'floor' | 'wall'; label: string }> = [
  { key: 'floor', label: 'Floor' },
  { key: 'wall', label: 'Wall' },
]

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
  /** Surface-texture kinds (deduplicated); url = thumbnail when one exists. */
  surfaceKinds: Array<{ kind: string; url: string }>
  onSurface: (key: 'floor' | 'wall', kind: string) => void
  /** Prop palette open (🪑 tool) — independent of the room selection. */
  propsOpen: boolean
  onPickProp: (prop: PropFull) => void
  armedPropId: string
}

export function PlanSidePanel({
  room, clipKinds, markerKind, onMarkerKind, markerSel, onSelectMarker,
  onAlwaysVisible, surfaceKinds, onSurface, propsOpen, onPickProp, armedPropId,
}: PlanSidePanelProps) {
  const { t } = useI18n()
  const layout = room?.layout
  const markers = layout?.markers || []

  // Room-specific blocks — the palette below them is independent of the
  // selection (the 🪑 tool may be open with nothing selected).
  const roomBlock = !room || !layout ? (
    <span className="ga-hint">
      {t('Select a room on the plan — the tools work on it.')}
    </span>
  ) : (
    <>
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

      <div className="ga-plan-panel-title"
        title={t('Surface-texture kinds for this room shell — the client skins floor and walls with them. Default = the global kind / the client fallback.')}>
        {t('Surfaces')}
      </div>
      {surfaceKinds.length || layout.surfaces ? SURFACE_SLOTS.map(({ key, label }) => {
        const cur = layout.surfaces?.[key] || ''
        const thumb = surfaceKinds.find((s) => s.kind === cur)?.url
        return (
          <label key={key} style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}>
            <span style={{ width: 32, flex: '0 0 auto' }}>{t(label)}</span>
            {thumb ? (
              <img className="ga-list-thumb" alt="" src={thumb}
                style={{ width: 20, height: 20 }} />
            ) : null}
            <select
              className="ga-input"
              style={{ flex: 1, minWidth: 0 }}
              value={cur}
              onChange={(e) => onSurface(key, e.target.value)}
            >
              <option value="">{t('— default —')}</option>
              {surfaceKinds.map((s) => (
                <option key={s.kind} value={s.kind}>{s.kind}</option>
              ))}
              {/* A stored kind the library no longer offers stays selectable. */}
              {cur && !surfaceKinds.some((s) => s.kind === cur) ? (
                <option value={cur}>{cur}</option>
              ) : null}
            </select>
          </label>
        )
      }) : (
        <span className="ga-hint">
          {t('No surface textures yet — the Surface textures tab creates them.')}
        </span>
      )}

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
    </>
  )

  return (
    <div className="ga-plan-panel">
      {roomBlock}
      {propsOpen ? (
        <PropsPalette onPick={onPickProp} armedPropId={armedPropId} />
      ) : null}
    </div>
  )
}
