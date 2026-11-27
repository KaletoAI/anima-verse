/**
 * planTools — tool-to-panel model for the floor-plan editor's dynamic
 * inspector. One tool is active at a time, and the inspector shows only the
 * panel belonging to that tool.
 */
import type { PlanMode } from './PlanToolbar'

export type PlanPanel =
  | 'select'
  | 'plot'
  | 'storey'
  | 'elevator'
  | 'stairs'
  | 'room'
  | 'openings'
  | 'props'
  | 'markers'
  | 'findings'

export const PANEL_INFO: Record<PlanPanel, { icon: string; label: string }> = {
  select: { icon: '↖', label: 'Select' },
  plot: { icon: '🟩', label: 'Plot' },
  storey: { icon: '🏗', label: 'Storey' },
  elevator: { icon: '🛗', label: 'Elevator' },
  stairs: { icon: '🪜', label: 'Stairs' },
  room: { icon: '⬠', label: 'Room' },
  openings: { icon: '🚪', label: 'Doors & windows' },
  props: { icon: '🪑', label: 'Props' },
  markers: { icon: '🎯', label: 'Markers' },
  findings: { icon: '⚠', label: 'Findings' },
}

export function panelForMode(m: PlanMode): PlanPanel | null {
  switch (m) {
    case 'boundary':
    case 'boundary-door':
      return 'plot'
    case 'outline':
    case 'hull-door':
      return 'storey'
    case 'elevator':
      return 'elevator'
    case 'stairs':
      return 'stairs'
    case 'draw-room':
    case 'curve':
      return 'room'
    case 'door':
    case 'window':
      return 'openings'
    case 'marker':
    case 'marker-move':
      return 'markers'
    case '':
      return null
  }
}
