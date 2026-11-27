/**
 * PlanSidePanel — the Room panel inside the inspector dock. Everything that
 * belongs to the SELECTED room shell and is not a click tool lives here: room
 * info (name, rotation, always-visible), how the room's FLOOR meets the ground
 * around it, walls, room height, and the room shell's surface kinds. Markers,
 * props and Furnish live in their own panels. Purely presentational —
 * RoomLayoutEditor owns the state and hands in the callbacks.
 *
 * WATER IS NOT EDITED HERE ANY MORE (W1, 2026-08-21). The three per-room dials
 * (level, depth, shore ramp) drove a second, weaker water with its own bake
 * stage; that stage is deleted and the server drops the three keys on the way
 * in, so a dial here would have written into nothing. What is left is the
 * honest half of the same statement: a room whose hull lies on painted water
 * shows a REFERENCE to that area — derived at compose time, never stored — and
 * its floor-kind picker no longer offers a water kind, because the sanitizer
 * strips exactly those. Water is painted on the MAP, where one polygon owns
 * its mirror, its bed and its flow.
 *
 * The YARD (§ A13a) is a shape here too, and the difference is what it does
 * NOT have: no shell block, no surfaces — it is the location surface, not a
 * built room. Furnish, markers and the palette work on it in their own panels.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { SliderInput } from '../../components/SliderInput'
import { SurfaceKindSelect } from './SurfaceKindSelect'
import type { MapWaterRef, Room, RoomLayout, SurfaceKind } from './worldTypes'

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
  onAlwaysVisible: (value: boolean) => void
  /** The room's own turn in degrees (contract v6 addendum): it turns the
   *  WHOLE room about its rect centre. The toolbar's ↻ steps 90°, this is
   *  the free angle — same field, and it is written where it has always
   *  been read. */
  onRotation: (deg: number) => void
  /** Patch of THIS room's layout — the generic write for the floor dials
   *  (today only `edge_blend_m`). A field set to `undefined` is REMOVED; 0 is
   *  an ordinary value and travels as 0. */
  onLayout: (patch: Partial<RoomLayout>) => void
  /** Walls opt-out of THIS room. Stored negative (`no_walls`), shown positive
   *  — it is a property of the room SHELL, not of any model it may carry. */
  onNoWalls: (value: boolean) => void
  /** Height offset of the ROOM in real metres (undefined = 0). */
  onFloorOffset: (value: number | undefined) => void
  /** Surface-texture kinds (deduplicated); url = thumbnail when one exists. */
  surfaceKinds: SurfaceKind[]
  /** The ids of every WATER terrain kind (`meta.water`), as the catalog
   *  answers them. The floor picker does not OFFER them: the server strips a
   *  water floor kind at the one write path, so a UI that let it be picked
   *  would only produce a selection that silently disappears on save. Empty
   *  while the catalog has not answered — and then nothing is filtered, the
   *  same rule the surface library follows about "not in the list". */
  waterKinds: Set<string>
  onSurface: (key: 'floor' | 'wall', kind: string) => void
  /** THIS room stands on painted water — the derived reference of the scene
   *  payload (`floor_plan[].map_water`), or null. Read-only: it names the
   *  area, it does not edit it. */
  mapWater: MapWaterRef | null
}

export function PlanSidePanel({
  room, ground, groundName,
  onAlwaysVisible, onRotation, onLayout, onNoWalls, onFloorOffset,
  surfaceKinds, waterKinds, onSurface, mapWater,
}: PlanSidePanelProps) {
  const { t } = useI18n()
  const layout = room?.layout

  if (!room || (!layout && !ground)) {
    return (
      <div className="ga-plan-panel">
        <span className="ga-hint">
          {t('Select a room on the plan — the tools work on it.')}
        </span>
      </div>
    )
  }

  return (
    <div className="ga-plan-panel">
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

          {/* THE ROOM STANDS ON PAINTED WATER (W1 § 6) — a READ-ONLY reference,
              not a dial. The room owns no mirror, no depth and no bed; it merely
              lies on an area that does, and the line says which one so the author
              knows where to go and edit it. Derived at compose time by containment
              and never stored, so it cannot outlive the lake. */}
          {mapWater ? (
            <span className="ga-hint">
              {t('Map ground: water — area {area} ({kind}). This room lies on painted water: the mirror, the depth, the shore ramp and the flow belong to that area on the map, not to the room. The room keeps its own walls, props and markers.')
                .replace('{area}', mapWater.area_id)
                .replace('{kind}', mapWater.kind)}
            </span>
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

          <div className="ga-plan-panel-title"
            title={t('Surface-texture kinds for this room shell — the client skins floor and walls with them. Default = the global kind / the client fallback.')}>
            {t('Surfaces')}
          </div>
          {surfaceKinds.length || layout.surfaces ? SURFACE_SLOTS.map(({ key, label }) => {
            // A FLOOR MAY NOT BE WATER (W1 § 6). The server strips such a pick at
            // the one write path, so offering it would mean watching a selection
            // vanish on the next save with nothing said. Only the FLOOR is
            // filtered — a wall may wear a wet-looking texture all it likes; what
            // is forbidden is a room claiming to BE water.
            const options = key === 'floor'
              ? surfaceKinds.filter((s) => !waterKinds.has(s.kind))
              : surfaceKinds
            return (
              <SurfaceKindSelect
                key={key}
                label={label}
                labelWidth={32}
                value={layout.surfaces?.[key] || ''}
                kinds={options}
                emptyLabel="— default —"
                onChange={(kind) => onSurface(key, kind)}
              />
            )
          }) : (
            <span className="ga-hint">
              {t('No surface textures yet — the Surface textures tab creates them.')}
            </span>
          )}
        </>
      ) : null}
    </div>
  )
}
