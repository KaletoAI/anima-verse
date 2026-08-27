import type { SceneFloor, SurfaceMaterialSpec } from '@anima/scene-render'

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
  /** How wide THIS floor's transition to the layer under it is, in metres
   *  (server window 0…8, 2 decimals, `world_ops._sanitize_layout` →
   *  `terrain_layers.sanitize_edge_blend`). DEFAULT 0 — the hard cut, because
   *  a floor is drawn, not grown; 0 is a VALUE and has to survive a save. */
  edge_blend_m?: number
  // A ROOM HAS NO WATER FIELDS (W1, 2026-08-21). `water_level`,
  // `water_depth_m` and `shore_ramp_m` were the E5b per-room dials of the
  // zone-water carve; that whole bake stage is deleted and the server drops
  // the three keys on the way in, without a fallback reader. Water is painted
  // on the MAP now — one polygon owns its mirror, its bed and its flow — and a
  // room that lies on painted water carries the derived reference
  // `floor_plan[].map_water` instead (`readMapWater` below).
  /** Cut the room's diorama at its shell (§ B1): the renderer discards every
   *  fragment outside the room hull, so a model that overhangs its floor plan
   *  ends at the room. Ignored for outdoor rooms. */
  clip_model?: boolean
  /** No recipe walls for this room: the server emits no `walls` entries for
   *  it at all (open zone, pavilion, an area inside an area model). Plate
   *  and openings stay; the building outline is unaffected. Absent =
   *  walls, so the editor shows the inverse ("Render walls"). */
  no_walls?: boolean
  /** Height offset of the ROOM in REAL metres, relative to its storey.
   *  Everything in the room rides along: walls, props, markers and the
   *  diorama. A pure FINE TRIM since "Ein Boden" (§ A16.9) — it compensates
   *  no second ground (storey 0 is the terrain itself) and it is not a
   *  waterline (`water_level` is). */
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
  /** DEPTH CUT (§ B2 addendum 2026-08-23): the fraction of the prop's DEPTH
   *  that remains (0.05…1). Absent = uncut — half a table against a wall is
   *  this table with a clipping plane through it, not a second prop. The
   *  server turns it into the finished `cut_plane` of the scene spec. */
  cut_keep?: number
  /** Which half REMAINS: 'front' is the top of the footprint on the plan
   *  (local −z), 'back' the bottom (local +z). Turns with the yaw. */
  cut_side?: 'front' | 'back'
  /** WHAT FILLS THE PROP'S TEXTURE SLOTS (v5) — keyed by SLOT NAME, i.e. an
   *  entry of the prop's stored `slots` list (detected off the mesh material
   *  names, editable afterwards in the prop editor). An `image` slot takes
   *  a same-origin gallery URL (`/world/locations/{id}/gallery/{file}` or
   *  `/characters/{name}/images/{file}`), a `material` slot a preset
   *  (`glass`). A key the prop does not declare, or a value of the wrong shape
   *  for its kind, is dropped on save. Absent = the prop as it was modelled. */
  slot_values?: Record<string, SlotValue>
}

/** One filled slot: exactly one of the two fields is meaningful, chosen by the
 *  slot's own kind. */
export interface SlotValue {
  image?: string
  preset?: string
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
  /** Optional frame/leaf prop scaled onto the opening. Set = this opening
   *  brings its own door, whatever the location's default says. */
  prop_id?: string
  /** The explicit "no prop in this door" — the ONE value that keeps the
   *  location's `default_door_prop_id` out of this opening. Absent = nothing
   *  chosen, i.e. the default applies (`scene_recipe.door_prop_id`). */
  door_prop?: 'none'
  /** Which side the door prop turns about, read against the doorway's own
   *  direction. Absent = left. */
  hinge?: 'left' | 'right'
  /** What fills the DOOR PROP's texture slots (v5) — a glass pane is the
   *  stated case. Same field and same rules as on a placement; where the
   *  opening inherits the location's default door it names no prop, so only
   *  the value shape is checked on save and the recipe drops what the
   *  resolved prop does not declare. */
  slot_values?: Record<string, SlotValue>
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
  // `rotation` — the building yaw on the map tile — is GONE with contract
  // v6 Nr. 10: it turned the mesh around the same axis the model sidecar's
  // own orientation fix (`fix_euler` y) already turns, a second dial on one
  // axis and nothing but a source of arithmetic error. A location is turned
  // by its anchor pin (`yaw_deg`), a mesh by its sidecar fix, and
  // `map_rotation_2d` is strictly the flat ICON artwork rotation. The server
  // sanitizer drops a submitted value.
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
  // `relief` — the scene's OWN 17 × 17 height field — IS GONE ("Ein Boden"
  // E5a, decision 1 of the plan), and so is the `layout.relief_flat` opt-out
  // that went with it. There is no per-location relief left to roll: local
  // relief is authored through the map's HEIGHT AREAS, and the one ground
  // under everything is `h_final`. The server sanitizer drops a submitted
  // value, so there is no field left to write.
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
  /** Staircases, one entry per FLIGHT — per storey jump, so a climb from the
   *  ground floor to the second is two of them. `at` is the FOOT (where the
   *  first tread begins) in LOCAL METRES like `elevator`, `from_level` the
   *  storey it starts on (a cellar flight is −1, it always leads to
   *  `from_level + 1`) and `dir_deg` the climb direction, one of the four
   *  quarter turns: 0 = +z, 90 = +x, 180 = −z, 270 = −x. The server composes
   *  the steps and the two trigger pads from it (`stair_step`/`stair_pad`
   *  extras); at most 8 per location. */
  stairs?: Array<{ at: [number, number]; from_level: number; dir_deg: number }>
}

// ── Scene recipe (docs/schnittstellen-3d.md part B) ──
// The server composes the WHOLE scene of a location; renderers only display
// it. Every number is already in WORLD metres around the anchor pin — no
// fractions, no scale factors, no geometry decisions on this side.
//
// Since E5a ("Ein Boden") the payload carries NO storey-0 plate: `plates` are
// the declared storeys only (upper floors, basements), and the level-0 rooms
// travel as `floor_plan` — polygons plus their floor kind, no heights. The
// `terrain` block and `natural_floor` are gone with the scene's own relief.
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
  SceneMarker, SceneStyle, SceneOpening, SceneRoom, SceneFloor,
  SceneProblem,
} from '@anima/scene-render'

/** What the preview POSTs to /play/scene-preview: the editor draft as it
 *  stands, including unsaved layouts. */
export interface SceneDraft {
  id: string
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

/** One NPC role a place wants staffed (plan-npc-auto-spawn.md § 1).
 *  The server fills it automatically when the avatar comes near: it counts the
 *  living NPCs tagged with this ROLE at this place and generates (or recycles)
 *  what is missing. `role` is the identity — it is the tag on the NPC and the
 *  key a recycled NPC is matched on, so a slot without one is dropped on save. */
export interface NpcSlot {
  role: string
  /** Character template of the generated NPC. Empty = `npc-temporary`. */
  template?: string
  count_min?: number
  count_max?: number
  /** Free text the generator gets — who this person is at this place. */
  briefing?: string
  /** Room the NPC is placed in. Empty = the location's arrival room.
   *  Ignored while `radius_m` is above 0 — a slot cannot be both indoors and
   *  out in the open. */
  room?: string
  /** Home area of the slot, in metres around the location (spec § E3).
   *  0 = the ordinary room placement. Above 0 the NPC stands at a free point
   *  within that radius and roams there instead of changing rooms. */
  radius_m?: number
  /** BINDS the slot to one existing temporary NPC — that sheet, and no other,
   *  staffs it. Empty = a new NPC is generated (or one recycled by role).
   *  A bound slot never generates anybody: it revives its NPC out of the pool
   *  or, if it is alive elsewhere, stamps and moves it here. */
  character?: string
  /** When this slot is staffed, in GAME time. Empty = always; `night`/`day`
   *  follow the season's sunrise/sunset; `HH:MM-HH:MM` is a literal span that
   *  may wrap over midnight. Outside its window nobody spawns and the NPCs
   *  standing in the slot go back into the pool. */
  when?: string
}

export interface Location {
  id: string
  name: string
  description?: string
  rooms?: Room[]
  entry_room?: string
  /** The place's own door: every door opening that names no prop of its own
   *  is filled with this one, unless it opts out with `door_prop: 'none'`.
   *  Empty = no default, i.e. the plain leaf as before. */
  default_door_prop_id?: string
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
  npc_slots?: NpcSlot[]
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

/**
 * THE display name of a location's ground room — one source, everywhere.
 *
 * The server creates the room with an EMPTY name (`world.ensure_ground_room`),
 * so the label a user reads is a CLIENT default, and it has to be the same
 * default in every surface: the room tree, the plan's "On the plan:" target
 * list, the plan side panel and the furnish dialog all name one and the same
 * room. The floor plan used to call it "Yard" while the tree called it
 * "Outside", which read as two rooms (user finding
 * 2026-08-20). An author who gives it a name of its own overrides both.
 */
export function groundRoomLabel(room: { name?: string } | null | undefined,
                                t: (s: string) => string): string {
  return room?.name?.trim() || t('Yard')
}

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
  /** HOW the kind is lit (§ A9) — the library's own declaration, verbatim.
   *  IT DOES NOT ANSWER "is this water?" any more (W1): that second book is
   *  deleted, and a library texture of class `water` without the terrain
   *  kind's own `meta.water` flag is a wet LOOK, not physics. The one
   *  predicate is `mapTypes.isWaterKind`. */
  material?: SurfaceMaterialSpec | null
}

/**
 * A ROOM STANDS ON PAINTED WATER — `floor_plan[].map_water` (W1 § 6).
 *
 * A REFERENCE and nothing more: the room owns no mirror, no depth and no bed,
 * it merely stands where the map says water is. It is DERIVED at compose time
 * by a majority-area containment test and never stored, so it cannot dangle —
 * delete the lake and the line is gone with it.
 */
export interface MapWaterRef {
  area_id: string
  kind: string
}

/**
 * That reference, read through a check.
 *
 * The field is additive on `SceneFloor`, which is declared once in
 * `@anima/scene-render` for the admin preview and the 3D client alike. It is
 * read defensively here for the same reason every other payload extra is: an
 * older server simply does not send it, and a room that then claims to be on
 * water would be worse than one that says nothing.
 */
export function readMapWater(floor: SceneFloor | undefined | null
                            ): MapWaterRef | null {
  const raw = (floor as unknown as Record<string, unknown> | undefined)
    ?.map_water
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const areaId = typeof r.area_id === 'string' ? r.area_id.trim() : ''
  const kind = typeof r.kind === 'string' ? r.kind.trim() : ''
  if (!areaId || !kind) return null
  return { area_id: areaId, kind }
}

/** The kind a closed room's floor wears when nobody named one — mirrors
 *  `app.core.terrain_layers.FLOOR_KIND_DEFAULT`. */
export const FLOOR_KIND_DEFAULT = 'floor'

/** WHAT THE GROUND WEARS in one room — the client's half of
 *  `terrain_layers.floor_kind_of`. Where the author named nothing: a CLOSED
 *  room gets the default floor (it has walls, so it has a floor, and it is
 *  not the meadow outside), an open ZONE gets the empty string, i.e. no layer
 *  at all and the terrain showing through. */
export function floorKindOf(layout: RoomLayout | undefined | null): string {
  const named = (layout?.surfaces?.floor || '').trim()
  if (named) return named
  return layout?.always_visible ? '' : FLOOR_KIND_DEFAULT
}
