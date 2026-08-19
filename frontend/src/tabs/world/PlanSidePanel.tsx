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
import type { Room, SurfaceKind } from './worldTypes'

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
  /** The 🎯 place tool — armed state + toggle (it lives HERE, next to the
   *  marker list it feeds, not in the left toolbar). */
  markerMode: boolean
  onArmMarker: () => void
  onAlwaysVisible: (value: boolean) => void
  /** Terrain-relief opt-out of THIS room (only offered on outdoor rooms). */
  onReliefFlat: (value: boolean) => void
  /** Height offset of the ROOM in real metres (undefined = 0). */
  onFloorOffset: (value: number | undefined) => void
  /** Surface-texture kinds (deduplicated); url = thumbnail when one exists. */
  surfaceKinds: SurfaceKind[]
  onSurface: (key: 'floor' | 'wall', kind: string) => void
  /** "✨ Furnish" (plan-room-furnish.md): opens the job dialog. The state
   *  string ('' = no job) is shown as a badge so a running job is visible
   *  without opening it. */
  furnishState: string
  furnishDisabled: boolean
  furnishHint: string
  onFurnish: () => void
  /** Prop palette open (🪑 tool) — independent of the room selection. */
  propsOpen: boolean
  onPickProp: (prop: PropFull) => void
  armedPropId: string
}

/** Job state → the badge next to the Furnish button. */
const FURNISH_BADGE: Record<string, string> = {
  selecting: '…',
  proposal_ready: '!',
  generating: '⚙',
  placing: '⚙',
  review_ready: '✓',
  error: '⚠',
}

export function PlanSidePanel({
  room, clipKinds, markerKind, onMarkerKind, markerSel, onSelectMarker,
  markerMode, onArmMarker, onAlwaysVisible, onReliefFlat, onFloorOffset,
  surfaceKinds, onSurface,
  furnishState, furnishDisabled, furnishHint, onFurnish,
  propsOpen, onPickProp, armedPropId,
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
        title={t('Marks an OUTDOOR room (terrace, garden, pool): shown permanently in the 3D client independent of the interior view, and it gets NO shell walls — only its floor plate.')}>
        <input
          type="checkbox"
          checked={!!layout.always_visible}
          onChange={(e) => onAlwaysVisible(e.target.checked)}
        />
        <span>{t('Outdoor room (always visible)')}</span>
      </label>

      {/* Terrain-relief opt-out (v5.2 Nr. 14). Only outdoor rooms can be
          asked: an indoor room is level in any case, because walls need even
          ground. Without a relief on the location the checkbox is simply
          without effect, so it does not depend on it. */}
      {layout.always_visible ? (
        <label className="ga-check-row" style={{ fontSize: '0.82em' }}
          title={t('Keeps THIS outdoor room level while the terrain relief rolls the rest of the location — for a road, a paved square, a clearing. Indoor rooms are always flat anyway. Without a relief on the location it changes nothing.')}>
          <input
            type="checkbox"
            checked={!!layout.relief_flat}
            onChange={(e) => onReliefFlat(e.target.checked)}
          />
          <span>{t('Keep flat (road, clearing)')}</span>
        </label>
      ) : null}

      {/* Where the ROOM sits, as opposed to a model inside it. It belongs to
          the room, not to a diorama — it used to live in the model-placement
          strip and was therefore invisible until a room HAD a model, which is
          exactly backwards for an outdoor zone laid onto a location model. */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Height offset of the ROOM in real metres, relative to its storey. Everything in the room moves with it: floor, walls, props, markers, exit and any model. Inside a building leave it at 0 — it is for rooms lying on a location model, where the terrain is not at storey level.')}>
        <span style={{ flex: 1 }}>{t('Room height (m)')}</span>
        <input
          className="ga-input"
          type="number"
          step={0.05}
          style={{ width: 78 }}
          value={layout.floor_offset_y ?? 0}
          onChange={(e) => {
            const v = Number(e.target.value)
            onFloorOffset(Number.isFinite(v) && v !== 0 ? v : undefined)
          }}
        />
      </label>

      <button
        type="button"
        className={`ga-btn ga-btn-sm${furnishState ? ' ga-btn-primary' : ''}`}
        disabled={furnishDisabled}
        onClick={onFurnish}
        title={furnishHint}
      >
        ✨ {t('Furnish')}
        {furnishState ? ` ${FURNISH_BADGE[furnishState] || ''}` : ''}
      </button>

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
                <option key={s.kind} value={s.kind}>{s.name}</option>
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
          <div style={{ display: 'flex', gap: 4 }}>
            <select
              className="ga-input"
              style={{ flex: 1, minWidth: 0 }}
              value={markerKind}
              onChange={(e) => onMarkerKind(e.target.value)}
              title={t('Animation kind the 🎯 tool drops — the open clip vocabulary, nothing hardcoded.')}
            >
              {clipKinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${markerMode ? ' ga-btn-primary' : ''}`}
              onClick={onArmMarker}
              title={t('Place a marker — then click inside the room; figures with this animation snap to it.')}
            >
              🎯
            </button>
          </div>
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
