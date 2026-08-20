// Floor-plan placement of a room (AV3D-2). EVERYTHING IS METRES since
// contract v6 Nr. 2 ("the metric wave") — the [0,1] fraction domain is deleted
// on both sides, and there is no migration: an old fraction blob simply
// describes a room a few centimetres across.
//
//   * `x`/`y` — the room's MIN CORNER in LOCATION-LOCAL metres: origin = the
//     anchor pin (`pos_x`/`pos_z`), axes as § A1.1, i.e. the very frame
//     `map3d.boundary` is drawn in. NEGATIVE VALUES ARE ORDINARY.
//   * `w`/`d` — size in metres, both > 0.
//   * `outline`, `outline_curves[].c`, `markers[].at`, `props[].at`,
//     `model_at` — metres relative to the room's OWN min corner (0…w / 0…d;
//     a curve control point may leave that box).
//   * `openings[].at` — the ONE ratio left: a fraction of its edge.
//
// `level` is the floor (0 = ground, negative = basement). Absent layout =
// client auto-grid. Stored resolution: centimetres, clamped to ±500 m.
export interface RoomLayout {
  level?: number
  /** Min corner, LOCATION-LOCAL metres around the anchor pin (may be < 0).
   *  ABSENT ON THE YARD (§ A13a): the ground room has no rectangle — its
   *  surface is the location boundary — so its layout carries `props`/
   *  `markers` and nothing else. Use `hasRect` before doing geometry with a
   *  layout; everything that draws a room shape needs the narrowed
   *  `PlacedLayout`. */
  x?: number
  y?: number
  /** Size in metres (> 0). Absent on the yard, like `x`/`y`. */
  w?: number
  d?: number
  rotation?: number
  /** Diorama-model anchor in METRES from the room's min corner (absent =
   *  centred, i.e. [w/2, d/2]) — the room's 3D model is positioned in the
   *  PLAN like a prop. */
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
   *  snaps to. at = METRES from the room's min corner; animation = a clip kind
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
  /** Drawn room hull: polygon points in METRES relative to the room's min
   *  corner, spanning 0…w / 0…d, auto-closed, winding clockwise in screen
   *  coords. Absent = the rectangle itself (implicit box, edges 0=N 1=E 2=S
   *  3=W). x/y/w/d ALWAYS carry the derived bbox — a rectangle-only reader
   *  keeps working. The server folds a hull that does not start at the corner
   *  by TRANSLATING it (metres do not renormalize). */
  outline?: Array<[number, number]>
  /** Furnishing: placements from the prop library. A placement NEVER scales
   *  the prop — the client sizes it from the prop's own dims × the plan's
   *  scale factor. A dangling prop_id renders as a placeholder. */
  props?: RoomPropPlacement[]
  /** Curved hull edges (plan-area-detail-scenes.md): at most ONE quadratic
   *  bezier control point per edge, in the room's own METRES like the outline
   *  points and free to sit OUTSIDE the hull (a road bend does) — the server
   *  clamps it to the plain ±500 m plan window, not to the bbox. The SERVER
   *  tessellates at compose time — the payload stays pure polygon. Openings on
   *  curved edges are rejected. */
  outline_curves?: Array<{ edge: number; c: [number, number] }>
}

export interface RoomPropPlacement {
  prop_id: string
  /** Room-local position: METRES from the room's min corner (0…w / 0…d).
   *  ON THE YARD (§ A13a) the same field is LOCATION-LOCAL metres — the
   *  ground has no min corner, its frame IS the location frame. */
  at: [number, number]
  /** Yaw in degrees, free values at 0.1° resolution. Absent = 0. */
  yaw?: number
  /** Vertical offset in metres (clamped ±5), additive to the floor. */
  offset_y?: number
  /** WHICH model variant of the prop this placement shows (E2.3) — a POSITION
   *  in the prop's ACTIVE meshes, not a store index; out of range wraps, so a
   *  deleted mesh never makes a placement disappear. Absent = the primary one.
   *  Only a manual placement carries it: a scattered copy derives its variant
   *  from the seed at compose time. */
  variant?: number
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
  // `size` — the MODEL's share of the location's reference square — is GONE
  // with contract v6 Nr. 3: every model scales through a declared real width
  // in metres (`width_m` on the sidecar), and an undeclared building fills
  // the boundary's bounding box, which is what size = 1 produced. The server
  // sanitizer drops a submitted value.
  /** Storey height in REAL metres — stacks the floor-plan levels. Absent = 3.
   *  Replaced the old pair "model height ÷ model storeys" and level_height
   *  (which counted in world metres). */
  storey_height_m?: number
  /** How wide the location is in REAL metres. SINCE v6 Nr. 2 A DERIVED VALUE,
   *  not a dial and not an anchor: the wider side of `boundary`'s bounding
   *  box, which the server recomputes and overwrites on every save. Nothing
   *  scales by it any more (rooms, props, markers and the figure all carry
   *  their own metres) — it survives because consumer contracts do: loading
   *  radius, viewport, backdrop, `scene.extent_m`. A submitted value is kept
   *  only for a location with no boundary at all. */
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
  /** Terrain relief of the detail scene (§ B1 Nr. 14): a deterministic
   *  height field over the terrain frame — since v6 Nr. 2 a square of edge
   *  `plan_width_m` over the BOUNDARY's bounding box, whose min corner the
   *  scene payload names as `terrain.origin`. `amplitude_m` is the swing in
   *  REAL metres (0.05..5, × k at compose time), `seed` picks the field and
   *  is mandatory — the editor always writes one. `wave_m` is the second
   *  axis: how WIDE one swell is, in REAL metres (1..200); the server turns
   *  it into the grid resolution, and without it the default 16 × 16 field
   *  applies. Only valid together with area_model + area_detail; the
   *  sanitizer drops it otherwise. Absent = the scene is dead flat. */
  relief?: { amplitude_m: number; seed: number; wave_m?: number }
  /** The DRAWN footprint of the location (contract v6 Nr. 1 "Gebiete"): a
   *  closed point sequence in LOCAL METRES around the pin (`pos_x`/`pos_z`)
   *  and its `yaw_deg`, transformed with the ONE § A1.1 mapping. Stored open
   *  (no repeated closing point), at most 64 points, clockwise in map view,
   *  concave allowed — a self-intersection is a WARNING in `problems[]`, not
   *  a refusal. `plan_width_m` is DERIVED from its bounding box by the
   *  server, so nothing writes both. Absent = the location has only a pin
   *  and is drawn as a square (transition state). */
  boundary?: Array<[number, number]>
  /** Pass-throughs at the LOCATION edge (a road crossing the cell east–west
   *  = two entries). Geometry + room link only — entry_room stays the
   *  gameplay gate. SINCE v6 (Nr. 5) `edge` is the 0-based INDEX of a
   *  boundary edge (edge i = point i → i+1) and `at` runs along that edge;
   *  the letters N/E/S/W are deleted, and the server drops an entry that
   *  still carries one. */
  boundary_openings?: Array<{ edge: number; at: number
    width_m: number; type?: 'passage'; room?: string }>
  /** Drawn building outline (AV3D-12): the house's floor plan INSIDE the
   *  plot, as polygon points in LOCAL METRES around the anchor pin (v6 Nr. 2,
   *  same frame as `boundary`), auto-closed — the client renders floor plates
   *  and walls per used level from it. Absent = rectangle as before. */
  outline?: Array<[number, number]>
  /** Elevator position in LOCAL METRES around the pin (v6 Nr. 2) — placed
   *  once, valid for all levels (client builds the shaft). */
  elevator?: [number, number]
}

// ── Scene recipe (docs/schnittstellen-3d.md part B) ──
// The server composes the WHOLE scene of a location; renderers only display
// it. Every number is already in WORLD metres around the anchor pin — no
// fractions, no scale factors, no geometry decisions on this side. The metric
// wave (v6 Nr. 2) changed neither the shape nor the values of this payload;
// its ONE addition is `terrain.origin`, the min corner of the relief lattice,
// which `sampleTerrain` in @anima/scene-render now anchors on.
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
  event_settings?: EventSettings
  terrain?: string
  map3d?: Map3D
  /** Server verdict: does this location carry any boundary pass-through?
   *  Openings CHANNEL entry — they are the only ways in once a location draws
   *  any. Without one the boundary is FREE (E4 task 5): entry anywhere along
   *  the edge, rule gates unchanged. The editor displays the flag, it does not
   *  judge. */
  has_entrance?: boolean
  /** Server findings about the DRAWN boundary (contract v6 Nr. 1), e.g.
   *  `boundary_self_intersection`. Absent = nothing to report. The scene
   *  payload states the same thing in its `problems[]`, but a bare location
   *  (a pin with an outline and no rooms) composes no scene at all — this is
   *  how the map editor hears about it anyway. */
  boundary_problems?: string[]
}

/** The reserved id of every location's GROUND room — the area no room takes
 *  up. Mirrors `app.models.world.GROUND_ROOM_ID`; the server creates the room,
 *  the editor only has to recognise it (an unnamed one is labelled, not left
 *  showing its raw id). */
export const GROUND_ROOM_ID = '__ground__'

/** A layout whose ROOM SHAPE is resolved: the rectangle is there, so every
 *  geometry helper (`outlineOf`, `absOutline`, plates, walls, snapping) can
 *  read it. */
export type PlacedLayout = RoomLayout & {
  x: number; y: number; w: number; d: number
}

/** Whether a layout carries a room RECTANGLE — the one question that
 *  separates an ordinary room from the yard (§ A13a), whose layout is
 *  placements only. Everything that draws or measures a room shape filters
 *  on this instead of on the mere presence of a layout. */
export function hasRect(lay: RoomLayout | undefined | null): lay is PlacedLayout {
  return !!lay && typeof lay.x === 'number' && typeof lay.y === 'number'
    && typeof lay.w === 'number' && typeof lay.d === 'number'
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

export const IMAGE_TYPES = ['', 'day', 'night', 'map_2d', 'building'] as const

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
