/**
 * PlanSidePanel — the context column right of the floor plan. Everything that
 * belongs to the SELECTED shape and is not a click tool lives here: room info
 * (name, rotation, always-visible), how the room's FLOOR meets the ground
 * around it (edge transition, and the mirror of a water floor), the
 * animation-marker vocabulary + the marker list, and the room shell's surface
 * kinds. The 🪑 tool opens the prop palette below them. Purely presentational
 * — RoomLayoutEditor owns the state and hands in the callbacks.
 *
 * The YARD (§ A13a) is a shape here too, and the difference is what it does
 * NOT have: no shell block, no surfaces — it is the location surface, not a
 * built room. Furnish, markers and the palette work on it like anywhere else.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { PropsPalette } from './PropsPalette'
import { HEIGHT_MAX_M, SHORE_RAMP_DEFAULT_M, SHORE_RAMP_MAX_M,
  WATER_DEPTH_DEFAULT_M, WATER_DEPTH_MAX_M, WATER_DEPTH_MIN_M,
  WATER_LEVEL_SPAN_M } from '../map/TerrainTools'
import type { PropFull } from '../props/propTypes'
import type { Room, RoomLayout, SurfaceKind } from './worldTypes'
import { floorKindOf, isWaterSurface } from './worldTypes'

/** Widest transition a floor may be given, in metres — the server window of
 *  `layout.edge_blend_m` (`terrain_layers.sanitize_edge_blend`). */
const EDGE_BLEND_MAX_M = 8

/** The two shell surfaces a room may skin — mirrors layout.surfaces. */
const SURFACE_SLOTS: Array<{ key: 'floor' | 'wall'; label: string }> = [
  { key: 'floor', label: 'Floor' },
  { key: 'wall', label: 'Wall' },
]

interface PlanSidePanelProps {
  /** The selected shape, or null: a room with a layout, or the yard — which
   *  may have none yet (§ A13a). */
  room: Room | null
  /** The selected shape is the YARD (§ A13a): placements only. Everything
   *  about a room SHELL — surfaces, outdoor flag, floor transition, height
   *  offset — is absent there, because the yard is the location surface and
   *  has no shell to describe. */
  ground: boolean
  /** Display name of the yard — `worldTypes.groundRoomLabel`, i.e. the
   *  author's own name or the ONE shared default. Never a second word for
   *  the same room. */
  groundName: string
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
  /** The room's own turn in degrees (contract v6 addendum): it turns the
   *  WHOLE room about its rect centre. The toolbar's ↻ steps 90°, this is
   *  the free angle — same field, and it is written where it has always
   *  been read. */
  onRotation: (deg: number) => void
  /** Patch of THIS room's layout — the generic write for the floor dials
   *  (`edge_blend_m`, and the three water numbers of a water floor). A field
   *  set to `undefined` is REMOVED, which is how a water level goes back to
   *  "the bake decides"; 0 is an ordinary value and travels as 0. */
  onLayout: (patch: Partial<RoomLayout>) => void
  /** Walls opt-out of THIS room. Stored negative (`no_walls`), shown positive
   *  — it is a property of the room SHELL, not of any model it may carry. */
  onNoWalls: (value: boolean) => void
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
  room, ground, groundName,
  clipKinds, markerKind, onMarkerKind, markerSel, onSelectMarker,
  markerMode, onArmMarker, onAlwaysVisible, onRotation, onLayout, onNoWalls,
  onFloorOffset,
  surfaceKinds, onSurface,
  furnishState, furnishDisabled, furnishHint, onFurnish,
  propsOpen, onPickProp, armedPropId,
}: PlanSidePanelProps) {
  const { t } = useI18n()
  const layout = room?.layout
  const markers = layout?.markers || []

  // Room-specific blocks — the palette below them is independent of the
  // selection (the 🪑 tool may be open with nothing selected).
  const roomBlock = !room || (!layout && !ground) ? (
    <span className="ga-hint">
      {t('Select a room on the plan — the tools work on it.')}
    </span>
  ) : (
    <>
      <div className="ga-plan-panel-title">{ground ? groundName : (room.name || room.id)}</div>
      {ground ? (
        <span className="ga-hint">
          {t('The location surface: the area no room takes up. Props and markers stand on the terrain here; it has no walls, no floor plan and no size of its own.')}
        </span>
      ) : (
        <span className="ga-hint" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {t('Rotation')}
          <input
            type="number"
            min={0}
            max={359}
            step={5}
            value={layout?.rotation || 0}
            disabled={!layout}
            onChange={(e) => onRotation(parseInt(e.target.value, 10) || 0)}
            title={t('Turns the WHOLE room about its centre — hull, walls, openings, markers, props and the 3D model. Drawing stays straight: new geometry is drawn in the room’s own unturned frame and turned afterwards.')}
            style={{ width: 58 }}
          />
          °
          {layout?.outline?.length ? ` · ⬠ ${layout.outline.length}` : ''}
        </span>
      )}
      {/* THE SHELL BLOCK — a room's own description of its walls, its floor
          and where it sits. The yard has none of it (§ A13a): it is not a
          built thing, it is the ground the built things stand on, and its
          surface comes from the location's terrain instead. */}
      {!ground && layout ? (
      <>
      <label className="ga-check-row" style={{ fontSize: '0.82em' }}
        title={t('Marks an OUTDOOR room (terrace, garden, pool): shown permanently in the 3D client independent of the interior view, and it gets NO shell walls — only its floor plate.')}>
        <input
          type="checkbox"
          checked={!!layout.always_visible}
          onChange={(e) => onAlwaysVisible(e.target.checked)}
        />
        <span>{t('Outdoor room (always visible)')}</span>
      </label>

      {/* THE FLOOR AS A LAYER OF THE GROUND ("Ein Boden" E5a, § G3). A
          level-0 room floor is no longer a plate laid over the terrain — it
          is the topmost layer OF the terrain, and these dials say how it
          meets the layers under it. The relief opt-out that used to stand
          here is gone with the scene's own height field: there is nothing
          left for a room to stay level against.

          Only offered on storey 0: an upper floor or a basement still gets a
          plate, and a plate has no transition to anything. */}
      {(layout.level || 0) === 0 ? (
        <SliderInput
          label={t('Edge transition (m)')}
          title={t('How far this floor fades into the ground around it. 0 draws a clean edge — parquet stops where the room stops. Turn it up and the floor washes out over that many metres, the way a sandy path runs into grass. Behind it: the floor is the topmost layer of the terrain, and this is the width the layer under it takes over in.')}
          value={layout.edge_blend_m ?? 0}
          min={0} max={EDGE_BLEND_MAX_M} step={0.1} fineStep="any"
          sliderWidth={72} inputWidth={62}
          style={{ display: 'flex' }} sliderStyle={{ flex: 1 }}
          // 0 IS A VALUE — it is the default and the hard cut, and it has to
          // reach the server as 0 rather than as a missing field.
          onChange={(v) => onLayout({ edge_blend_m: v })}
        />
      ) : null}

      {/* WATER FLOORS (§ A19 no. 4). A room whose floor kind is a water
          surface is a lake with a room's outline: the bake carves its bed out
          of the world height field with the very three numbers a painted lake
          uses. Which kinds count is asked of the LIBRARY's material class —
          never of the kind's name and never of its colour, the same book the
          server asks. */}
      {(layout.level || 0) === 0
        && isWaterSurface(floorKindOf(layout), surfaceKinds) ? (
        <>
          <SliderInput
            label={t('Water level (m)')}
            title={t('The height the water surface stands at, as a world height in metres. Empty = the server decides: on a built plot the level of the ground the building stands on, out in the open the median height along this room’s own rim.')}
            value={layout.water_level}
            fallback={0}
            min={layout.water_level === undefined
              ? -HEIGHT_MAX_M
              : Math.max(-HEIGHT_MAX_M, layout.water_level - WATER_LEVEL_SPAN_M)}
            max={layout.water_level === undefined
              ? HEIGHT_MAX_M
              : Math.min(HEIGHT_MAX_M, layout.water_level + WATER_LEVEL_SPAN_M)}
            step={0.05} fineStep="any"
            clearable placeholder={t('auto')}
            sliderWidth={72} inputWidth={62}
            style={{ display: 'flex' }} sliderStyle={{ flex: 1 }}
            onChange={(v) => onLayout({ water_level: v })}
            onClear={() => onLayout({ water_level: undefined })}
          />
          <SliderInput
            label={t('Depth (m)')}
            title={t('How far the bed is carved below the water surface. Empty = the bake’s own default.')}
            value={layout.water_depth_m}
            fallback={WATER_DEPTH_DEFAULT_M}
            min={WATER_DEPTH_MIN_M} max={WATER_DEPTH_MAX_M} step={0.1}
            fineStep="any"
            clearable placeholder={String(WATER_DEPTH_DEFAULT_M)}
            sliderWidth={72} inputWidth={62}
            style={{ display: 'flex' }} sliderStyle={{ flex: 1 }}
            onChange={(v) => onLayout({ water_depth_m: v })}
            onClear={() => onLayout({ water_depth_m: undefined })}
          />
          <SliderInput
            label={t('Shore ramp (m)')}
            title={t('Over how many metres the bed climbs back to the untouched land at the water’s edge. 0 = a wall at the shore.')}
            value={layout.shore_ramp_m}
            fallback={SHORE_RAMP_DEFAULT_M}
            min={0} max={SHORE_RAMP_MAX_M} step={0.5} fineStep="any"
            clearable placeholder={String(SHORE_RAMP_DEFAULT_M)}
            sliderWidth={72} inputWidth={62}
            style={{ display: 'flex' }} sliderStyle={{ flex: 1 }}
            onChange={(v) => onLayout({ shore_ramp_m: v })}
            onClear={() => onLayout({ shore_ramp_m: undefined })}
          />
          <span className="ga-hint">
            {t('This room’s floor is water: the ground under it is dug out to the level minus the depth and ramped back to the land over the shore width, so no terrain pokes through the surface at any distance. Leave a field empty to let the server decide.')}
          </span>
        </>
      ) : null}

      {/* Walls opt-out: open zones, pavilions, areas inside an area model.
          The UI is positive ("render walls"), the stored field is negative —
          so the default (no field) means walls. It describes the room SHELL,
          which is why it stands here and not in the model strip: a wall-less
          zone usually has no diorama at all, and there it stayed invisible
          (E5 inventory 1a). Outdoor rooms are asked too — an open zone with
          window openings in the plan should still be able to render
          wall-less. */}
      <label className="ga-check-row" style={{ fontSize: '0.82em' }}
        title={t('Off: this room gets no walls at all — no segments, no window sill or head, no glass. Its floor and openings stay (the plan keeps drawing them), and the building outline is unaffected.')}>
        <input
          type="checkbox"
          checked={!layout.no_walls}
          onChange={(e) => onNoWalls(!e.target.checked)}
        />
        <span>{t('Render walls')}</span>
      </label>

      {/* Where the ROOM sits, as opposed to a model inside it. It belongs to
          the room, not to a diorama — it used to live in the model-placement
          strip and was therefore invisible until a room HAD a model, which is
          exactly backwards for an outdoor zone laid onto a location model. */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Fine trim of the ROOM in real metres, relative to its storey. Everything in the room moves with it: walls, props, markers, exit and any model. Leave it at 0 unless a room really needs to sit above or below the ground — it does not set a water level, that is the water field below.')}>
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
      </>
      ) : null}

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

      {!ground && layout ? (
      <>
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
      </>
      ) : null}

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
