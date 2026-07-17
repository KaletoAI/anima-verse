// Floor-plan placement of a room inside its building (AV3D-2). x/y = top-left
// corner, w/d = width/depth — all fractions of the building footprint; level
// is the floor (0 = ground, negative = basement); exit is the walk-in/out
// point as fractions of the ROOM rectangle. Absent = client auto-grid.
export interface RoomLayout {
  level?: number
  x: number
  y: number
  w: number
  d: number
  rotation?: number
  exit?: [number, number]
  /** Animation markers: spots a figure with a matching active animation
   *  snaps to. at = fraction of the room rectangle; animation = a clip kind
   *  from the open animation-clip vocabulary; rotation = facing in degrees
   *  (0 south / 90 east / 180 north / 270 west, absent = client default);
   *  offset_y = metres, additive to the sampled seat height. */
  markers?: Array<{ at: [number, number]; animation: string
    rotation?: number; offset_y?: number }>
}

export interface Room {
  id?: string
  name?: string
  description?: string
  // Indoor/outdoor override — the room's flag wins over the location's
  // (a pool room in an indoor house = outdoor). Empty = inherit location.
  indoor?: string
  // Decency (plan-outfit-system-rethink.md §1.1) — replaces the old outfit_type model
  decency?: '' | 'public' | 'private' | 'nude_ok'
  style_hint?: string
  swim_allowed?: boolean
  activity_hint?: string
  image_prompt_day?: string
  image_prompt_night?: string
  layout?: RoomLayout
}

// Optional 3D metadata for external 3D map clients (AV3D-1). The 2D UI
// stores/edits it but never renders it; absent fields mean "let the client
// decide" (procedural heuristics).
export interface Map3D {
  floors?: number
  footprint?: number[]
  style?: string
  color?: string
  /** Building yaw on the map tile in degrees (0..359). Absent = the 3D client
   *  falls back to map_rotation_2d (the model turns with the 2D icon). */
  rotation?: number
  /** Building base size as a fraction of the tile edge (0..1).
   *  Absent = client default 0.92. */
  size?: number
  /** Storey height in metres — stacks the floor-plan levels (preview +
   *  3D client). Absent = default 3. */
  level_height?: number
}

export interface EventSettings {
  event_probability?: number
  max_concurrent_events?: number
  event_cooldown_hours?: number
  allowed_categories?: string[]
  event_blacklist?: string[]
}

export interface Location {
  id: string
  name: string
  description?: string
  rooms?: Room[]
  entry_room?: string
  danger_level?: number
  indoor?: string
  decency?: '' | 'public' | 'private' | 'nude_ok'
  style_hint?: string
  swim_allowed?: boolean
  activity_hint?: string
  knowledge_item_id?: string
  passable?: boolean
  image_prompt_day?: string
  image_prompt_night?: string
  image_prompt_map_2d?: string
  image_prompt_building?: string
  image_count?: number
  is_template?: boolean
  template_location_id?: string
  grid_x?: number | null
  grid_y?: number | null
  map_image_2d?: string
  map_rotation_2d?: number
  /** Multi-tile patch anchored (centred) on this placed cell — gallery file
   *  of type map_3x3, drawn UNDER the per-cell tiles. */
  map_patch_2d?: string
  map_patch_span?: number
  /** True hides the cell's own 2D tile entirely (no first-image fallback) so
   *  an underlying patch shows through. */
  map_image_off?: boolean
  event_settings?: EventSettings
  terrain?: string
  map3d?: Map3D
}

// Suggested values only — both fields accept free text (the consuming map
// client decides what it can render; unknown values fall back to defaults).
export const TERRAIN_TYPES = ['grass', 'forest', 'road', 'water', 'sand', 'rock'] as const
export const MAP3D_STYLES = ['tower', 'house', 'shop', 'generic'] as const

export const EVENT_CATEGORIES = ['ambient', 'social', 'disruption', 'danger'] as const

// Danger level scale (0–5). Drives hourly stamina/stat drain (danger_system.py)
// and danger-based block rules. Labels describe what each step means.
export const DANGER_LEVELS: Array<{ value: number; label: string }> = [
  { value: 0, label: 'Safe' },
  { value: 1, label: 'Low' },
  { value: 2, label: 'Moderate' },
  { value: 3, label: 'High' },
  { value: 4, label: 'Severe' },
  { value: 5, label: 'Extreme' },
]

export interface GalleryResponse {
  images: string[]
  image_rooms?: Record<string, string>
  image_types?: Record<string, string>
  image_metas?: Record<string, { backend?: string; model?: string; loras?: string[] }>
}

export const IMAGE_TYPES = ['', 'day', 'night', 'map_2d', 'map_3x3', 'building'] as const

export type Selection =
  | { kind: 'location'; locationId: string }
  | { kind: 'room'; locationId: string; roomId: string }
  | null
