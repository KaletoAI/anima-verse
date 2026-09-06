/**
 * PlanInspectorLevel — everything that belongs to the STOREY the editor is
 * standing on, plus the two settings that belong to the whole plan and had
 * nowhere better to live.
 *
 * WHAT MOVED HERE AND WHY. The floor and wall texture pickers used to sit in
 * the header row between the level buttons and the zoom, each behind a brown
 * or a brick emoji — two selects competing with the level switch for a line
 * that is supposed to say WHERE one is. The default door prop stood one row
 * higher still, alone, at the full width of the page, above a plan that had
 * none to spare. Both are settings OF this floor plan, so they belong in the
 * inspector, and the storey is where the floor and the walls are decided.
 *
 * THE FOOTPRINT PER STOREY (§ G) lives here for the same reason: "how wide is
 * the building on this floor" is a fact about the storey. The three buttons
 * are the whole vocabulary — draw one, copy the inherited one to edit it, or
 * drop it and inherit again — because a storey has exactly two states, its own
 * shape or somebody else's, and the middle button is the bridge between them.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { DoorPropSelect } from './DoorPropPicker'
import { SurfaceKindSelect } from './SurfaceKindSelect'
import { outlineSourceLevel } from './planGeometry'
import type { Map3D, SurfaceKind } from './worldTypes'

interface Props {
  level: number
  map3d?: Map3D
  /** Absent = this editor may not write map3d; then only the door default is
   *  offered, which lives on the location and not in the 3D block. */
  onMap3d?: (key: keyof Map3D, value: unknown) => void
  surfaceKinds: SurfaceKind[]
  defaultDoorPropId: string
  onDefaultDoorProp?: (id: string) => void
  /** The footprint tool is armed FOR THIS STOREY right now. */
  drawingOutline: boolean
  /** There IS an inherited shape to copy — without one the fork button would
   *  write an empty entry and mark the draft unsaved for nothing. */
  canForkOutline: boolean
  /** Arm the footprint tool — points land in this storey's own entry (or in
   *  `map3d.outline` on the ground floor, which IS the building's own). */
  onDrawOutline: () => void
  /** Copy the inherited footprint into this storey's own entry, so its
   *  corners can be dragged without redrawing the shape. */
  onForkOutline: () => void
  /** Drop this storey's own entry — it inherits again. */
  onDropOutline: () => void
}

export function PlanInspectorLevel({
  level, map3d, onMap3d, surfaceKinds, defaultDoorPropId, onDefaultDoorProp,
  drawingOutline, canForkOutline, onDrawOutline, onForkOutline, onDropOutline,
}: Props) {
  const { t } = useI18n()
  const own = (map3d?.level_outlines || {})[String(level)]
  const hasOwn = Array.isArray(own) && own.length >= 3
  // Where the shape comes from when this storey does not say. The ground
  // floor is never "inherited": `map3d.outline` IS its own footprint.
  const src = outlineSourceLevel(map3d?.level_outlines, level)
  const inheritedFrom = hasOwn || level === 0 ? null
    : src === null ? 'base' : src

  return (
    <div className="ga-form" style={{ gap: 8 }}>
      <div className="ga-plan-panel-title">
        {t('Storey {n}').replace('{n}', String(level))}
      </div>

      {onMap3d ? (
        <>
          <SurfaceKindSelect
            label="Floor"
            value={map3d?.level_floors?.[String(level)] || ''}
            kinds={surfaceKinds}
            emptyLabel="— global floor kind —"
            title={t('Floor texture of THIS storey: the client tiles the whole level plate with the kind; a room floor kind overrides only its own area. Empty = the global floor kind.')}
            onChange={(kind) => {
              const merged = { ...(map3d?.level_floors || {}) }
              if (kind) merged[String(level)] = kind
              else delete merged[String(level)]
              onMap3d('level_floors',
                Object.keys(merged).length ? merged : undefined)
            }}
          />
          <SurfaceKindSelect
            label="Wall"
            value={map3d?.level_walls?.[String(level)] || ''}
            kinds={surfaceKinds}
            emptyLabel={map3d?.wall_kind
              ? '— shell kind —' : '— plain shell colour —'}
            title={t('Wall texture of THIS storey’s shell: every contour wall of the storey tiles with the kind. A room wall keeps its own wall kind. Empty = the shell-wide kind below.')}
            onChange={(kind) => {
              const merged = { ...(map3d?.level_walls || {}) }
              if (kind) merged[String(level)] = kind
              else delete merged[String(level)]
              onMap3d('level_walls',
                Object.keys(merged).length ? merged : undefined)
            }}
          />
          <SurfaceKindSelect
            label="Shell"
            value={map3d?.wall_kind || ''}
            kinds={surfaceKinds}
            emptyLabel="— plain shell colour —"
            title={t('Wall texture of the whole building shell — what a storey without its own wall kind tiles with. Empty = the shell renders in its plain colour.')}
            onChange={(kind) => onMap3d('wall_kind', kind || undefined)}
          />

          {/* ── The storey's own footprint (§ G) ───────────────────── */}
          <div className="ga-plan-panel-title" style={{ marginTop: 4 }}>
            {t('Footprint')}
          </div>
          <span className="ga-hint" style={{ fontSize: '0.78em' }}>
            {level === 0
              ? t('The ground floor carries the building’s own footprint — the 🏗 tool draws it.')
              : hasOwn
                ? t('Own footprint ({n} points). Storeys above inherit it unless they draw their own.')
                  .replace('{n}', String(own.length))
                : inheritedFrom === 'base'
                  ? t('Inherited from the building footprint. Draw one here to make the building narrower from this storey up.')
                  : t('Inherited from storey {n}.')
                    .replace('{n}', String(inheritedFrom))}
          </span>
          {level !== 0 ? (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              <button
                type="button"
                className={`ga-btn ga-btn-sm${drawingOutline ? ' ga-btn-primary' : ''}`}
                title={t('Draw this storey’s own footprint: click points on the plan, click the first point again to close, Esc cancels.')}
                onClick={onDrawOutline}
              >
                {drawingOutline ? t('Drawing…') : t('Draw own')}
              </button>
              {!hasOwn ? (
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  disabled={!canForkOutline}
                  title={canForkOutline
                    ? t('Copy the inherited footprint into this storey, so its corners can be dragged instead of redrawn.')
                    : t('Nothing to copy — no storey below has a footprint yet.')}
                  onClick={onForkOutline}
                >
                  {t('Copy inherited')}
                </button>
              ) : (
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  title={t('Drop this storey’s own footprint — it inherits again.')}
                  onClick={onDropOutline}
                >
                  {t('Inherit again')}
                </button>
              )}
            </div>
          ) : null}

          {/* ── Whole-location switches ─────────────────────────────── */}
          <div className="ga-plan-panel-title" style={{ marginTop: 4 }}>
            {t('This location')}
          </div>
          <label className="ga-check-row" style={{ fontSize: '0.82em' }}
            title={t('For villages, lakes and other AREAS: the location model stays in the interior view and gets holes cut into it — the floor plan plus every indoor room placed outside it. Outdoor rooms outside the plan become walkable zones on the model surface. Off = single building, the model fades out.')}>
            <input type="checkbox" checked={!!map3d?.area_model}
              onChange={(e) => {
                onMap3d('area_model', e.target.checked || undefined)
                if (!e.target.checked) onMap3d('area_detail', undefined)
              }} />
            <span>{t('Area location (model stays in interior view)')}</span>
          </label>
          {map3d?.area_model ? (
            <label className="ga-check-row" style={{ fontSize: '0.82em' }}
              title={t('Detail scene: the area model becomes a fading shell — zooming in fades it out like a building and shows the drawn rooms (ground textures, scattered props) instead. No holes are cut into the model any more.')}>
              <input type="checkbox" checked={!!map3d?.area_detail}
                onChange={(e) => onMap3d('area_detail', e.target.checked || undefined)} />
              <span>{t('Detail scene (model fades on zoom-in)')}</span>
            </label>
          ) : null}
        </>
      ) : null}

      {/* THE PLACE'S OWN DOOR — the fallback every door opening on this plan
          inherits, and the first option the opening panel offers. */}
      {onDefaultDoorProp ? (
        <label style={{ display: 'flex', gap: 5, alignItems: 'center',
          fontSize: '0.82em' }}
          title={t('Fills every door opening that picks nothing of its own. An opening can override it with its own prop or opt out with “None”.')}>
          <span style={{ width: 38, flex: '0 0 auto' }}>{t('Door')}</span>
          <DoorPropSelect
            value={defaultDoorPropId}
            onChange={onDefaultDoorProp}
            emptyLabel={t('— no default door —')}
            width={190}
          />
        </label>
      ) : null}
    </div>
  )
}
