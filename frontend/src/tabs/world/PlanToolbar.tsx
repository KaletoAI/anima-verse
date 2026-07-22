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
export type PlanMode = '' | 'exit' | 'marker' | 'marker-move' | 'outline'
  | 'elevator' | 'opening' | 'draw-room'

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
  hasExit: boolean
  /** The building outline exists in the map3d draft. */
  hasOutline: boolean
  /** Points collected in the running draft (room hull or building outline). */
  outlineDraftLen: number
  hasElevator: boolean
  /** Show the building group at all (the editor got an onMap3d writer). */
  building: boolean
  /** No scale anchor (plan width) — every tool that produces or consumes
   *  real-world size is locked until one is set. */
  noAnchor: boolean
  canSuggest: boolean
  showModels: boolean
  showBuilding: boolean
  propsOpen: boolean
  onMode: (m: PlanMode) => void
  onRotate: () => void
  onUnplace: () => void
  onRemoveExit: () => void
  onRemoveOutline: () => void
  onRemoveElevator: () => void
  onCommitOutline: () => void
  onCommitRoom: () => void
  onCancelDraw: () => void
  onSuggest: () => void
  onToggleModels: () => void
  onToggleBuilding: () => void
  onProps: () => void
}

export function PlanToolbar({
  mode, hasSelection, selectionRotation, hasExit, hasOutline,
  outlineDraftLen, hasElevator, building, noAnchor, canSuggest, showModels,
  showBuilding, propsOpen, onMode, onRotate, onUnplace, onRemoveExit,
  onRemoveOutline, onRemoveElevator, onCommitOutline, onCommitRoom,
  onCancelDraw, onSuggest, onToggleModels, onToggleBuilding, onProps,
}: PlanToolbarProps) {
  const { t } = useI18n()
  const drawing = mode === 'draw-room'
  const outlining = mode === 'outline'
  // One tooltip for every tool the missing scale anchor locks.
  const anchorTip = t('Set the plan width (m) first')

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
              disabled={noAnchor}
              onClick={() => onMode('outline')}
              title={noAnchor ? anchorTip
                : t('Draw the building outline as a polygon (fractions of the reference square) — the 3D client renders floor plates and walls from it.')}
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
          disabled={!hasSelection || noAnchor}
          onClick={() => onMode('draw-room')}
          title={noAnchor ? anchorTip
            : t('Redraw the room hull as a polygon — replaces the shape; openings are cleared, exit and markers stay.')}
        />
      )}
      <Tool
        icon="↻"
        disabled={!hasSelection}
        onClick={onRotate}
        title={t('Rotate the room 90° clockwise — hull, exit point and 3D model turn together. Now: {deg}°')
          .replace('{deg}', String(selectionRotation))}
      />
      <Tool
        icon="🚪"
        active={mode === 'exit'}
        disabled={!hasSelection}
        onClick={() => onMode('exit')}
        title={t('Exit point — then click inside the room to place the walk-in/out point.')}
      />
      {hasExit ? (
        <Tool
          icon="🗑"
          danger
          onClick={onRemoveExit}
          title={t('Remove the exit point — the client falls back to the edge facing the building centre.')}
        />
      ) : null}
      <Tool
        icon="▦"
        active={mode === 'opening'}
        disabled={!hasSelection}
        onClick={() => onMode('opening')}
        title={t('Opening — then click a room edge to place a door; drag it along the edge, edit it below.')}
      />
      <Tool
        icon="✨"
        disabled={!canSuggest || noAnchor}
        onClick={onSuggest}
        title={noAnchor ? anchorTip
          : t('Doors on shared walls, an entrance for otherwise closed rooms, windows on exterior walls ≥ 2.5 m — never overwrites existing openings.')}
      />
      <Tool
        icon="🪑"
        active={propsOpen}
        disabled={noAnchor}
        onClick={onProps}
        title={noAnchor ? anchorTip
          : t('Show the prop library in the panel next to the plan.')}
      />
      <Tool
        icon="✕"
        danger
        disabled={!hasSelection}
        onClick={onUnplace}
        title={t('Remove from the floor plan — the 3D client auto-grids this room again.')}
      />

      <span className="ga-plan-toolbar-group">{t('View')}</span>
      <Tool
        icon="🖼"
        active={showModels}
        onClick={onToggleModels}
        title={t('Lay the placed room models (top-down view) behind the plan — markers can be dropped on real furniture.')}
      />
      <Tool
        icon="🏢"
        active={showBuilding}
        onClick={onToggleBuilding}
        title={t('Lay the building model (roof view = real footprint) behind the plan — for tracing the outline polygon.')}
      />
    </div>
  )
}
