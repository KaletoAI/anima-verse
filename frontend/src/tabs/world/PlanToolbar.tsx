/**
 * PlanToolbar — the vertical 44 px icon strip left of the floor plan. Purely
 * presentational: every handler and all state live in RoomLayoutEditor, the
 * toolbar only decides which icon is armed, disabled or contextual. The groups
 * run top-down from the outermost shape inwards: the LOCATION BOUNDARY (the
 * plot), the BUILDING tools (the house on it) — both only when the editor may
 * write map3d — and the ROOM tools; the marker tool lives in the
 * side panel next to the marker list. Tooltips carry the explanations that
 * used to sit as hint texts and checkbox labels next to the plan.
 *
 * With the YARD selected (§ A13a) every ROOM tool is disabled and says why in
 * its tooltip: the location surface has no rectangle, no hull and no walls to
 * work on. The building tools and the prop palette are unaffected.
 */
import { useI18n } from '../../i18n/I18nProvider'

/** Click-to-place modes of the floor-plan editor ('' = plain selection). */
export type PlanMode = '' | 'marker' | 'marker-move' | 'outline'
  | 'elevator' | 'door' | 'window' | 'draw-room' | 'curve' | 'boundary-door'
  | 'boundary'

function Tool({ icon, title, onClick, active = false, danger = false,
  disabled = false, small = false }: {
  icon: string
  title: string
  onClick: () => void
  active?: boolean
  danger?: boolean
  disabled?: boolean
  /** Text label instead of a single glyph (the ✓ (n) commit buttons). */
  small?: boolean
}) {
  return (
    <button
      type="button"
      className={`ga-btn ga-btn-sm${active ? ' ga-btn-primary' : ''}${danger ? ' ga-btn-danger' : ''}`}
      style={small ? { fontSize: 11 } : undefined}
      disabled={disabled}
      title={title}
      onClick={onClick}
    >
      {icon}
    </button>
  )
}

interface PlanToolbarProps {
  mode: PlanMode
  /** A shape is selected on the plan. Together with `ground` it decides the
   *  room tools: they need a selection that is not the yard. */
  hasSelection: boolean
  selectionRotation: number
  /** The building outline exists in the map3d draft. */
  hasOutline: boolean
  /** The LOCATION BOUNDARY exists (`map3d.boundary`, ≥ 3 points). Without one
   *  there are no vertices to drag — the seed button in the banner above the
   *  plan is the way in, and the tool says so instead of arming a gesture on
   *  the pin square that stands in for a boundary nobody drew. */
  hasBoundary: boolean
  /** Points collected in the running draft (room hull or building outline). */
  outlineDraftLen: number
  hasElevator: boolean
  /** Show the building group at all (the editor got an onMap3d writer). */
  building: boolean
  canSuggest: boolean
  /** The selected room has a 3D model with a declared real width — only then
   *  can the floor plan be fitted to it. */
  canFitToModel: boolean
  /** The selected room has a DRAWN hull — curves bend hull edges only. */
  canCurve: boolean
  /** The YARD is selected (§ A13a): it has no room geometry at all, so every
   *  shape tool is off and says why. Props and markers stay — they are the
   *  point of selecting it. */
  ground: boolean
  /** The one sentence that explains the refusal above. */
  groundHint: string
  /** The other refusal: NOTHING is selected, so there is no shape to work on.
   *  Without it a greyed-out tool still showed its normal tooltip and named no
   *  reason at all — the state a location whose rooms are all unplaced starts
   *  in (user finding 2026-08-20). */
  noSelectionHint: string
  propsOpen: boolean
  onMode: (m: PlanMode) => void
  onRotate: () => void
  onFitToModel: () => void
  onUnplace: () => void
  onRemoveOutline: () => void
  onRemoveElevator: () => void
  onCommitOutline: () => void
  onCommitRoom: () => void
  onCancelDraw: () => void
  onSuggest: () => void
  onProps: () => void
}

export function PlanToolbar({
  mode, hasSelection, selectionRotation, hasOutline, hasBoundary,
  outlineDraftLen, hasElevator, building, canSuggest,
  canFitToModel, canCurve, ground, groundHint, noSelectionHint, onFitToModel,
  propsOpen, onMode, onRotate, onUnplace,
  onRemoveOutline, onRemoveElevator, onCommitOutline, onCommitRoom,
  onCancelDraw, onSuggest, onProps,
}: PlanToolbarProps) {
  const { t } = useI18n()
  // NO SCALE-ANCHOR LOCK since contract v6 Nr. 2: a room layout carries its
  // own metres, so no tool here waits for a plan width any more.
  const drawing = mode === 'draw-room'
  const outlining = mode === 'outline'
  // A room tool is available when a room is selected — never on the yard,
  // which has no rectangle, no hull and no walls (§ A13a).
  const shape = hasSelection && !ground
  /** Tooltip of a shape tool: its own text, or the reason it is off — the
   *  yard first (it IS a selection, just one without geometry), otherwise the
   *  empty selection. A disabled tool always names its reason. */
  const shapeHint = (title: string) => {
    if (ground) return groundHint
    if (!hasSelection) return noSelectionHint
    return title
  }

  return (
    <div className="ga-plan-toolbar">
      {building ? (
        <>
          <span className="ga-plan-toolbar-group">{t('Plot')}</span>
          {/* The LOCATION BOUNDARY — the plot itself, not the house on it.
              It is edited with the very gesture the map tab uses, and it is
              first in the strip because it is the outermost of the three
              shapes on this plan. */}
          <Tool
            icon="🟩"
            active={mode === 'boundary'}
            disabled={!hasBoundary}
            onClick={() => onMode('boundary')}
            title={hasBoundary
              ? t('Edit the location boundary — the green outline of the plot itself. Drag a vertex to move it, click an edge to insert one, double-click a vertex to remove it. Saved immediately, like on the map tab.')
              : t('No boundary drawn yet — use “Draw boundary” in the banner above the plan to lay down a first square, then reshape it here.')}
          />
          <span className="ga-plan-toolbar-group">{t('Build')}</span>
          {outlining ? (
            <>
              <Tool
                icon={`✓ (${outlineDraftLen})`}
                small
                active
                disabled={outlineDraftLen < 3}
                onClick={onCommitOutline}
                title={t('Finish outline — clicking the first vertex closes too')}
              />
              <Tool icon="✕" onClick={onCancelDraw} title={t('Cancel drawing (Esc)')} />
            </>
          ) : (
            <Tool
              icon="🏗"
              onClick={() => onMode('outline')}
              title={t('Draw the building outline as a polygon in local metres — the 3D client renders floor plates and walls from it.')}
            />
          )}
          {hasOutline && !outlining ? (
            <Tool
              icon="🗑"
              danger
              onClick={onRemoveOutline}
              title={t('Remove the outline — the client falls back to the rectangle.')}
            />
          ) : null}
          <Tool
            icon="🛗"
            active={mode === 'elevator'}
            onClick={() => onMode('elevator')}
            title={t('Place the elevator with one click — it serves ALL levels (the client builds the shaft).')}
          />
          {hasElevator && mode !== 'elevator' ? (
            <Tool icon="🗑" danger onClick={onRemoveElevator}
              title={t('Remove the elevator')} />
          ) : null}
          <Tool
            icon="⇥"
            active={mode === 'boundary-door'}
            onClick={() => onMode('boundary-door')}
            title={t('Entry/exit at the location edge — click near a boundary edge; a road crossing the cell gets one on each side. Edit edge, width and linked room below the plan.')}
          />
        </>
      ) : null}

      <span className="ga-plan-toolbar-group">{t('Room')}</span>
      {drawing ? (
        <>
          <Tool
            icon={`✓ (${outlineDraftLen})`}
            small
            active
            disabled={outlineDraftLen < 3}
            onClick={onCommitRoom}
            title={t('Finish the room hull — clicking the first vertex closes too')}
          />
          <Tool icon="✕" onClick={onCancelDraw} title={t('Cancel drawing (Esc)')} />
        </>
      ) : (
        <Tool
          icon="⬠"
          disabled={!shape}
          onClick={() => onMode('draw-room')}
          title={shapeHint(t('Redraw the room hull as a polygon — replaces the shape; openings are cleared, markers stay.'))}
        />
      )}
      <Tool
        icon="↻"
        disabled={!shape}
        onClick={onRotate}
        title={shapeHint(t('Turn the room 90° — hull, walls, openings, markers, props and the 3D model turn together about the room’s centre. You draw straight and turn afterwards: new geometry is always drawn in the room’s own unturned frame. Free angles in the room panel. Now: {deg}°')
          .replace('{deg}', String(selectionRotation)))}
      />
      <Tool
        icon="◡"
        active={mode === 'curve'}
        disabled={!canCurve}
        onClick={() => onMode('curve')}
        title={shapeHint(t('Curve — click a hull edge of the selected room to bend it (drag the control point; click the edge again to remove the curve). Needs a drawn hull. Openings cannot sit on curved edges.'))}
      />
      <Tool
        icon="⇲"
        disabled={!canFitToModel}
        onClick={onFitToModel}
        title={shapeHint(t('Fit the floor plan to the 3D model: the room takes the size the model’s declared real width gives it. A DRAWN hull keeps its shape and is scaled as a whole; a plain rectangle also takes the model’s proportions.'))}
      />
      <Tool
        icon="🚪"
        active={mode === 'door'}
        disabled={!shape}
        onClick={() => onMode('door')}
        title={shapeHint(t('Door — then click a room edge; on a shared wall it opens BOTH rooms. Drag it along the edge, edit it below.'))}
      />
      <Tool
        icon="🪟"
        active={mode === 'window'}
        disabled={!shape}
        onClick={() => onMode('window')}
        title={shapeHint(t('Window — then click a room edge (sill 0.9 m, edit below). Exterior walls open to the outside.'))}
      />
      <Tool
        icon="✨"
        disabled={!canSuggest}
        onClick={onSuggest}
        title={t('Doors on shared walls, an entrance for otherwise closed rooms, windows on exterior walls ≥ 2.5 m — never overwrites existing openings.')}
      />
      <Tool
        icon="🪑"
        active={propsOpen}
        onClick={onProps}
        title={t('Show the prop library in the panel next to the plan.')}
      />
      {/* The yard cannot be taken off the plan — it IS the plan's ground
          (§ A13a). Clearing its placements is what the prop strip's ✕ and
          the Furnish dialog's "empty the room" do. */}
      <Tool
        icon="✕"
        danger
        disabled={!shape}
        onClick={onUnplace}
        title={shapeHint(t('Remove from the floor plan — the 3D client auto-grids this room again.'))}
      />
    </div>
  )
}
