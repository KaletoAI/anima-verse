// Floor-plan placement of a room inside its building (AV3D-2). x/y = top-left
// corner, w/d = width/depth — all fractions of the building footprint; level
// is the floor (0 = ground, negative = basement). Absent = client auto-grid.
export interface RoomLayout {
  level?: number
  x: number
  y: number
  w: number
  d: number
  rotation?: number
  /** Diorama-model anchor as fractions of the room rect (absent = centred)
   *  — the room's 3D model is positioned in the PLAN like a prop. */
  model_at?: [number, number]
  /** Diorama-model height offset in metres (replaces the room sidecar
   *  offset; buildings keep theirs). */
  model_offset_y?: number
  /** AV3D-12: show this room permanently, independent of the interior view
   *  — for outdoor rooms not covered by the building model. */
  always_visible?: boolean
  /** Terrain relief opt-out (v5.2 Nr. 14): this OUTDOOR room stays level
   *  while the rest of the location rolls — a road, a paved square, a
   *  clearing. Indoor rooms are flat anyway (walls need even ground), so the
   *  editor only offers it on always-visible rooms. */
  relief_flat?: boolean
  /** Cut the room's diorama at its shell (§ B1): the renderer discards every
   *  fragment outside the room hull, so a model that overhangs its floor plan
   *  ends at the room. Ignored for outdoor rooms. */
  clip_model?: boolean
  /** No recipe walls for this room: the server emits no `walls` entries for
   *  it at all (open zone, pavilion, an area inside an area model). Plate
   *  and openings stay; the building outline is unaffected. Absent =
   *  walls, so the editor shows the inverse ("Render walls"). */
  no_walls?: boolean
  /** Height offset of the ROOM in REAL metres, relative to its storey (± ,
   *  × k at render time). Everything in the room rides along: plate, walls,
   *  props, markers and the diorama. 0 inside a building; it is for
   *  rooms that cut a hole into a location model, where the terrain is not
   *  at storey level. */
  floor_offset_y?: number
  /** Animation markers: spots a figure with a matching active animation
   *  snaps to. at = fraction of the room rectangle; animation = a clip kind
   *  from the open animation-clip vocabulary; rotation = facing in degrees
   *  (0 south / 90 east / 180 north / 270 west, absent = client default);
   *  offset_y = metres, additive to the sampled seat height; tilt/roll =
   *  the two lean axes in degrees (±90, head up/down and sideways) for
   *  figures that are not upright — lying on a slope, leaning on something. */
  markers?: Array<{ at: [number, number]; animation: string
    rotation?: number; offset_y?: number; tilt?: number; roll?: number }>
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
  /** Curved hull edges (plan-area-detail-scenes.md): at most ONE quadratic
   *  bezier control point per edge, bbox-local like the outline points
   *  (server clamp [-1, 2]). The SERVER tessellates at compose time — the
   *  payload stays pure polygon. Openings on curved edges are rejected. */
  outline_curves?: Array<{ edge: number; c: [number, number] }>
}

export interface RoomPropPlacement {
  prop_id: string
  /** Room-local position: fractions of the room rectangle (0..1). */
  at: [number, number]
  /** Yaw in degrees, free values at 0.1° resolution. Absent = 0. */
  yaw?: number
  /** Vertical offset in metres (clamped ±5), additive to the floor. */
  offset_y?: number
  /** Scatter (plan-area-detail-scenes.md, v5.2 Nr. 12): this many COPIES of
   *  the prop are thrown over the room area at compose time; the placement
   *  itself stays as the manually positioned anchor. Σ ≤ 120 per room. */
  scatter_count?: number
  /** uint32 seed the copies derive from — reroll = new seed. */
  scatter_seed?: number
  /** Minimum centre distance between the copies in metres (0..5). 0 = they
   *  may overlap — the WHOLE density rule, there is no footprint minimum. */
  scatter_spacing_m?: number
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
  /** The MODEL's share of the location's reference square (]0, 1]; 1 = edge
   *  to edge). Absent = 1. A model can no longer be bigger than its
   *  location — for that, raise extent_m. */
  size?: number
  /** How wide the location is in WORLD metres: the reference square every
   *  plan fraction lives in AND the box the model fills. Absent = 10 =
   *  exactly one map tile; more overlaps the neighbours on purpose. */
  extent_m?: number
  /** Storey height in REAL metres — stacks the floor-plan levels (× k at
   *  render time). Absent = 3. Replaced the old pair "model height ÷ model
   *  storeys" and level_height (which counted in world metres). */
  storey_height_m?: number
  /** Real-world width the floor-plan reference square represents (m) —
   *  THE scale anchor: k = extent_m / plan_width_m derives room-rect sizes
   *  (from width_m), figure size (1.7 × k) and the storey height. Absent =
   *  no anchor; floor-plan geometry cannot be saved. */
  plan_width_m?: number
  /** Floor-texture KIND per storey ({"0": "parquet"}) — the client tiles the
   *  level plate with it; a room's surfaces.floor overrides its own area. */
  level_floors?: Record<string, string>
  /** Wall-texture KIND of the WHOLE building shell — every contour wall
   *  tiles with it (the wall counterpart of level_floors, deliberately not
   *  per level). A room wall keeps its own surfaces.wall. Absent = the shell
   *  renders in style.wall_color. */
  wall_kind?: string
  /** Area location: the location MODEL stays standing in the interior view
   *  and gets holes instead — the floor plan plus every indoor room placed
   *  outside it. Outdoor rooms outside the plan become zones on the model
   *  surface. Absent = today's behaviour (single building, model fades). */
  area_model?: boolean
  /** Detail scene ON TOP of area_model (plan-area-detail-scenes.md): the
   *  location model becomes a FADING shell (display "shell_area") and the
   *  rooms compose like a building interior — no cutouts, no overlay zones.
   *  Only meaningful together with area_model. */
  area_detail?: boolean
  /** Terrain relief of the detail scene (v5.2 Nr. 14): a deterministic
   *  height field over the reference square. `amplitude_m` is the swing in
   *  REAL metres (0.05..5, × k at compose time), `seed` picks the field and
   *  is mandatory — the editor always writes one. `wave_m` is the second
   *  axis: how WIDE one swell is, in REAL metres (1..200); the server turns
   *  it into the grid resolution, and without it the default 16 × 16 field
   *  applies. Only valid together with area_model + area_detail; the
   *  sanitizer drops it otherwise. Absent = the scene is dead flat. */
  relief?: { amplitude_m: number; seed: number; wave_m?: number }
  /** Pass-throughs at the LOCATION edge (a road crossing the cell east–west
   *  = two entries). Geometry + room link only — entry_room stays the
   *  gameplay gate. `at` follows the room-opening letter convention
   *  (left→right on N/S, top→bottom on E/W). */
  boundary_openings?: Array<{ edge: 'N' | 'E' | 'S' | 'W'; at: number
    width_m: number; type?: 'passage'; room?: string }>
  /** Drawn building outline (AV3D-12): polygon points as fractions of the
   *  location's reference square (extent_m), auto-closed — the client
   *  renders floor plates and walls per used level from it. Absent =
   *  rectangle as before. */
  outline?: Array<[number, number]>
  /** Elevator position (fractions of the reference square) — placed once,
   *  valid for all levels (client builds the shaft). */
  elevator?: [number, number]
}

// ── Scene recipe (shared/schnittstellen-3d.md part B) ──
// The server composes the WHOLE scene of a location; renderers only display
// it. Every number is already in WORLD metres around the tile centre — no
// fractions, no scale factors, no geometry decisions on this side.
// Source: GET /play/locations/{id}/scene, draft variant POST
// /play/scene-preview (app/core/scene_recipe.py).
//
// The types themselves live in @anima/scene-render: ONE definition for the
// admin preview and the 3D client. They used to be declared twice (here and
// in client3d/src/api.ts) and had already drifted — elevator_* was required
// here and optional there, and the two described `openings` differently.
// Re-exported so every existing importer keeps working unchanged.
export type {
  ScenePayload, ScenePlate, SceneWall, SceneExtra, SceneModelSpec, ModelTier,
  SceneMarker, SceneStyle, SceneOpening, SceneRoom, SceneTerrain,
  SceneProblem,
} from '@anima/scene-render'

/** What the preview POSTs to /play/scene-preview: the editor draft as it
 *  stands, including unsaved layouts. */
export interface SceneDraft {
  id: string
  map_rotation_2d?: number
  map3d?: Map3D
  rooms: Array<{ id: string; name?: string; layout?: RoomLayout }>
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
  template_location_id?: string
  /** World position in METRES, `null` when the location is unplaced. */
  pos_x?: number | null
  pos_z?: number | null
  /** § A1.1 rotation of the location itself — NOT `map_rotation_2d`, which
   *  only turns the flat icon artwork inside the footprint. */
  yaw_deg?: number
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
  /** Server verdict: does this location carry any boundary pass-through?
   *  Without one it cannot be entered — the editor warns, it does not judge. */
  has_entrance?: boolean
}

/** The reserved id of every location's GROUND room — the area no room takes
 *  up. Mirrors `app.models.world.GROUND_ROOM_ID`; the server creates the room,
 *  the editor only has to recognise it (an unnamed one is labelled, not left
 *  showing its raw id). */
export const GROUND_ROOM_ID = '__ground__'

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

/** One entry of the global surface-texture library as a picker needs it.
 *  `kind` is the ID and the value that gets STORED; `name` is what the user
 *  reads. Both come from /assets/surface-textures. */
export interface SurfaceKind {
  kind: string
  name: string
  url: string
}
