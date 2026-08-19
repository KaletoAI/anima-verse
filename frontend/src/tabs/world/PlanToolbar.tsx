/**
 * PlanToolbar — the vertical 44 px icon strip left of the floor plan. Purely
 * presentational: every handler and all state live in RoomLayoutEditor, the
 * toolbar only decides which icon is armed, disabled or contextual. Three
 * groups top-down: building tools (only when the editor may write map3d),
 * room tools and the underlay view toggles; the marker tool lives in the
 * side panel next to the marker list. Tooltips carry the explanations that
 * used to sit as hint texts and checkbox labels next to the plan.
 */
import { useI18n } from '../../i18n/I18nProvider'

/** Click-to-place modes of the floor-plan editor ('' = plain selection). */
export type PlanMode = '' | 'marker' | 'marker-move' | 'outline'
  | 'elevator' | 'door' | 'window' | 'draw-room' | 'curve' | 'boundary-door'

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
  /** A room WITH a layout is selected — the room tools work on it. */
  hasSelection: boolean
  selectionRotation: number
  /** The building outline exists in the map3d draft. */
  hasOutline: boolean
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
  mode, hasSelection, selectionRotation, hasOutline,
  outlineDraftLen, hasElevator, building, canSuggest,
  canFitToModel, canCurve, onFitToModel,
  propsOpen, onMode, onRotate, onUnplace,
  onRemoveOutline, onRemoveElevator, onCommitOutline, onCommitRoom,
  onCancelDraw, onSuggest, onProps,
}: PlanToolbarProps) {
  const { t } = useI18n()
  // NO SCALE-ANCHOR LOCK since contract v6 Nr. 2: a room layout carries its
  // own metres, so no tool here waits for a plan width any more.
  const drawing = mode === 'draw-room'
  const outlining = mode === 'outline'

  return (
    <div className="ga-plan-toolbar">
      {building ? (
        <>
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
          disabled={!hasSelection}
          onClick={() => onMode('draw-room')}
          title={t('Redraw the room hull as a polygon — replaces the shape; openings are cleared, markers stay.')}
        />
      )}
      <Tool
        icon="↻"
        disabled={!hasSelection}
        onClick={onRotate}
        title={t('Rotate the room 90° clockwise — hull, markers and 3D model turn together. Now: {deg}°')
          .replace('{deg}', String(selectionRotation))}
      />
      <Tool
        icon="◡"
        active={mode === 'curve'}
        disabled={!canCurve}
        onClick={() => onMode('curve')}
        title={t('Curve — click a hull edge of the selected room to bend it (drag the control point; click the edge again to remove the curve). Needs a drawn hull. Openings cannot sit on curved edges.')}
      />
      <Tool
        icon="⇲"
        disabled={!canFitToModel}
        onClick={onFitToModel}
        title={t('Fit the floor plan to the 3D model: the room takes the size the model’s declared real width gives it. A DRAWN hull keeps its shape and is scaled as a whole; a plain rectangle also takes the model’s proportions.')}
      />
      <Tool
        icon="🚪"
        active={mode === 'door'}
        disabled={!hasSelection}
        onClick={() => onMode('door')}
        title={t('Door — then click a room edge; on a shared wall it opens BOTH rooms. Drag it along the edge, edit it below.')}
      />
      <Tool
        icon="🪟"
        active={mode === 'window'}
        disabled={!hasSelection}
        onClick={() => onMode('window')}
        title={t('Window — then click a room edge (sill 0.9 m, edit below). Exterior walls open to the outside.')}
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
      <Tool
        icon="✕"
        danger
        disabled={!hasSelection}
        onClick={onUnplace}
        title={t('Remove from the floor plan — the 3D client auto-grids this room again.')}
      />
    </div>
  )
}
