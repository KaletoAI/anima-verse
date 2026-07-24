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
  /** Diorama-model anchor as fractions of the room rect (absent = centred)
   *  — the room's 3D model is positioned in the PLAN like a prop. */
  model_at?: [number, number]
  /** Diorama-model height offset in metres (replaces the room sidecar
   *  offset; buildings keep theirs). */
  model_offset_y?: number
  /** AV3D-12: show this room permanently, independent of the interior view
   *  — for outdoor rooms not covered by the building model. */
  always_visible?: boolean
  /** Animation markers: spots a figure with a matching active animation
   *  snaps to. at = fraction of the room rectangle; animation = a clip kind
   *  from the open animation-clip vocabulary; rotation = facing in degrees
   *  (0 south / 90 east / 180 north / 270 west, absent = client default);
   *  offset_y = metres, additive to the sampled seat height. */
  markers?: Array<{ at: [number, number]; animation: string
    rotation?: number; offset_y?: number }>
  /** Room shell (plan-room-props.md): per-room surface-texture kinds. The
   *  client derives walls/floor from the geometry × storey height and skins
   *  them with these kinds (fallback: global 'floor' kind / client default). */
  surfaces?: { floor?: string; wall?: string }
  /** Wall openings — doors / windows / passages. Deterministic + admin-edited;
   *  the client splits the wall edge into segments around them (no CSG). */
  openings?: RoomOpening[]
  /** Drawn room hull: polygon points as fractions of the room BBOX (x/y/w/d),
   *  auto-closed, winding clockwise in screen coords, bbox spans [0,1]².
   *  Absent = the rectangle itself (implicit unit square, edges 0=N 1=E 2=S
   *  3=W). x/y/w/d ALWAYS carry the derived bbox — legacy clients keep
   *  reading only those. */
  outline?: Array<[number, number]>
  /** Furnishing: placements from the prop library. A placement NEVER scales
   *  the prop — the client sizes it from the prop's own dims × the plan's
   *  scale factor. A dangling prop_id renders as a placeholder. */
  props?: RoomPropPlacement[]
}

export interface RoomPropPlacement {
  prop_id: string
  /** Room-local position: fractions of the room rectangle (0..1). */
  at: [number, number]
  /** Yaw in degrees, free values at 0.1° resolution. Absent = 0. */
  yaw?: number
  /** Vertical offset in metres (clamped ±5), additive to the floor. */
  offset_y?: number
}

export interface RoomOpening {
  /** 'N'|'S'|'E'|'W' on a rectangle, or a polygon edge index (int >= 0). */
  edge: 'N' | 'S' | 'E' | 'W' | number
  /** Centre of the opening along the edge (0..1). */
  at: number
  width_m: number
  height_m: number
  /** Sill height in metres — door = 0, window ≈ 0.9. */
  sill_m: number
  type: 'door' | 'window' | 'passage'
  /** Connectivity target: room id or 'outside' (door/passage). */
  to?: string
  /** Optional frame/leaf prop scaled onto the opening. */
  prop_id?: string
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
  /** Subject for the room's 3D-model source image (🧊 render, room_model
   *  use case). Falls back to the room description when empty. */
  image_prompt_building?: string
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
  /** Building base size as a fraction of the tile edge (]0, 2]; > 1
   *  overflows the tile on purpose — overlapping models).
   *  Absent = client default 0.92. */
  size?: number
  /** Storey height in WORLD metres — stacks the floor-plan levels AND
   *  derives the figure scale in rooms (level_height / 3). Absent =
   *  default 3 (figure scale 1/3). Fallback only — with plan_width_m +
   *  building anchors everything derives instead. */
  level_height?: number
  /** Real-world width the floor-plan reference square represents (m) —
   *  THE detail-view scale anchor: k = 8 / plan_width_m derives room-rect
   *  sizes (from width_m), figure size (1.7 × k), storey stacking and the
   *  shell height. Absent = legacy behavior. */
  plan_width_m?: number
  /** Floor-texture KIND per storey ({"0": "parquet"}) — the client tiles the
   *  level plate with it; a room's surfaces.floor overrides its own area. */
  level_floors?: Record<string, string>
  /** Drawn building outline (AV3D-12): polygon points as fractions of the
   *  8×8 reference square, auto-closed — the client renders floor plates
   *  and walls per used level from it. Absent = rectangle as before. */
  outline?: Array<[number, number]>
  /** Elevator position (fractions of the reference square) — placed once,
   *  valid for all levels (client builds the shaft). */
  elevator?: [number, number]
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
