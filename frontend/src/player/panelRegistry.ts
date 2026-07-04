/**
 * Panel + layout registry for the /play surface — pure module-level data
 * extracted from PlayerApp.tsx (review section 8, part 3). No component state
 * here; single source of truth for panel ids, launcher metadata, default grid
 * layout and per-panel accents.
 */
import type { Layout } from 'react-grid-layout'
import type { IconName } from './icons'

// Square, browser-independent cells: fixed cell size in px. The column count
// is derived from the measured width so the column width == rowHeight (CELL).
// A wider browser = MORE columns, not wider ones.
export const CELL = 14
export const MARGIN = 4

// Default layout for new worlds + demo — taken from the locally saved state.
// The grid renders with compactType={null} + allowOverlap, i.e. positions stay
// exactly as set here.
export const DEFAULT_LAYOUT: Layout[] = [
  { i: 'scene', x: 13, y: 18, w: 49, h: 26, minW: 8, minH: 8 },
  { i: 'env', x: 13, y: 3, w: 49, h: 33, minW: 6, minH: 5 },
  { i: 'map', x: 75, y: 3, w: 16, h: 12, minW: 6, minH: 5 },
  { i: 'worldmap', x: 62, y: 3, w: 13, h: 12, minW: 6, minH: 5 },
  { i: 'self', x: 0, y: 3, w: 13, h: 20, minW: 6, minH: 8 },
  { i: 'others', x: 41, y: 20, w: 13, h: 18, minW: 8, minH: 8 },
  { i: 'belongings', x: 62, y: 19, w: 29, h: 25, minW: 10, minH: 8 },
  { i: 'journal', x: 20, y: 9, w: 50, h: 30, minW: 8, minH: 6 },
  { i: 'gallery', x: 0, y: 54, w: 20, h: 14, minW: 8, minH: 6 },
  { i: 'instagram', x: 20, y: 54, w: 21, h: 18, minW: 10, minH: 8 },
  { i: 'phone', x: 18, y: 7, w: 18, h: 30, minW: 10, minH: 12 },
  { i: 'tasks', x: 24, y: 27, w: 17, h: 10, minW: 6, minH: 4 },
  { i: 'news', x: 18, y: 6, w: 34, h: 33, minW: 8, minH: 8 },
  { i: 'layouts', x: 24, y: 37, w: 17, h: 14, minW: 6, minH: 6 },
  { i: 'settings', x: 11, y: 5, w: 59, h: 38, minW: 12, minH: 12 },
]

// Default box per panel id — source of truth for min/initial size.
export const DEFAULT_BY_ID: Record<string, Layout> = Object.fromEntries(
  DEFAULT_LAYOUT.map((d) => [d.i, d]))

// Launcher labels + kind. kind:'dialog' → centered overlay (comes/goes)
// instead of a grid tile; usable for "tool" windows in general.
export const PANEL_META: { id: string; label: string; icon: IconName; kind?: 'grid' | 'dialog' }[] = [
  { id: 'scene', label: 'Chat', icon: 'chat' },
  { id: 'env', label: 'Surroundings', icon: 'surroundings' },
  { id: 'map', label: 'Move', icon: 'move' },
  { id: 'worldmap', label: 'Map', icon: 'worldmap' },
  { id: 'self', label: 'Self', icon: 'self' },
  { id: 'others', label: 'Others', icon: 'others' },
  { id: 'belongings', label: 'Inventory', icon: 'backpack' },
  { id: 'journal', label: 'Mind', icon: 'brain' },
  { id: 'gallery', label: 'Gallery', icon: 'gallery' },
  { id: 'instagram', label: 'Instagram', icon: 'instagram' },
  { id: 'phone', label: 'Phone', icon: 'phone' },
  { id: 'tasks', label: 'Tasks', icon: 'tasks' },
  { id: 'news', label: 'News', icon: 'news' },
  { id: 'settings', label: 'Avatar', icon: 'avatar' },
  { id: 'layouts', label: 'Layouts', icon: 'layouts', kind: 'dialog' },
]
export const ALL_PANELS = PANEL_META.map((p) => p.id)
export const GRID_PANELS = PANEL_META.filter((p) => p.kind !== 'dialog').map((p) => p.id)
export const DIALOG_PANELS = PANEL_META.filter((p) => p.kind === 'dialog').map((p) => p.id)
// Grid panel, but NOT open by default (occasional, opened via button).
// Closed-by-default = all grid panels that were NOT open in the saved default
// (open: scene/env/map/worldmap/self/others/belongings/gallery/instagram/tasks).
// 'layouts' is a dialog and is never tiled anyway.
export const CLOSED_BY_DEFAULT = new Set(['journal', 'news', 'phone', 'settings'])
export const INITIAL_OPEN = GRID_PANELS.filter((id) => !CLOSED_BY_DEFAULT.has(id))
export const ICON_BY_ID: Record<string, IconName> = Object.fromEntries(
  PANEL_META.map((p) => [p.id, p.icon]))
export const LABEL_BY_ID: Record<string, string> = Object.fromEntries(
  PANEL_META.map((p) => [p.id, p.label]))
// One accent hue per panel (subtly saturated, dark-theme friendly) — makes the
// bar readable at a glance: the color tints the icon (active = full + tinted
// background, inactive = dimmed). Utility buttons stay neutral.
export const PANEL_COLOR: Record<string, string> = {
  scene: '#6aa9ff',      // Chat — blue
  env: '#4ec9a8',        // Surroundings — teal
  map: '#56c4dd',        // Move — cyan
  worldmap: '#e0a356',   // Map — amber
  self: '#b48ead',       // Self — violet
  others: '#e8995e',     // Others — orange
  belongings: '#d3a84a', // Inventory — gold
  journal: '#c98bdb',    // Mind — magenta
  gallery: '#5fb0e8',    // Gallery — sky blue
  instagram: '#e1567c',  // Instagram — pink
  phone: '#6cc24a',      // Phone — green
  news: '#e0675e',       // News — red
  settings: '#9aa4b2',   // Avatar — grey
}
// Panels that can show enlarged (view-only overlay). Extensible.
export const EXPANDABLE = new Set<string>(['worldmap'])
