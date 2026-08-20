/**
 * mapTypes — what the map editor reads from the server, nothing more.
 *
 * The shapes follow the contract (`docs/schnittstellen-3d.md` § A1.3 worldmap,
 * § A1.5 terrain, § A1.7 editor CRUD). The 3D metadata block is NOT re-declared
 * here — `Map3D` lives once, in `../world/worldTypes`, and both the location
 * editor and the map read the same declaration.
 *
 * ONE TYPE PER ENDPOINT. The two location sources look alike and are not:
 * `GET /play/worldmap` rows carry only the § A1.3 fields, `GET /world/locations`
 * dicts carry the full record. Blending them into one optional-everything
 * interface would let a filter on `template_location_id` compile against
 * worldmap rows and silently return nothing. They share their geometry through
 * `MapGeometry` and part ways after it.
 */
import type { MapBounds, StrokeStyle } from './mapMath'
import type { Map3D, RoomLayout } from '../world/worldTypes'

export type { Map3D }

/**
 * The map geometry every location carries, wherever it comes from.
 *
 * `pos_x`/`pos_z` are world METRES and `null` when the location is unplaced —
 * it then stands on no map at all. `yaw_deg` is the § A1.1 rotation and is
 * written through unchanged: NO sign conversion anywhere in the editor
 * (the scene-side `map3d.rotation` that used to sit next to it is gone with
 * v6 Nr. 10 — the pin is the only turn a location has).
 */
export interface MapGeometry {
  id: string
  name: string
  pos_x?: number | null
  pos_z?: number | null
  yaw_deg?: number | null
  /** Edge length of the footprint square in metres. `null` means unplaced OR
   *  no usable anchor — either way the location has no area. */
  plan_width_m?: number | null
  map3d?: Map3D
}

/**
 * A location row of `GET /play/worldmap` — EXACTLY the fields § A1.3 lists,
 * nothing else. The gameplay payload knows no templates and no descriptions;
 * a filter on them here would silently match nothing. Use `EditorLocation`
 * when you need them.
 */
export interface WorldmapLocationRow extends MapGeometry {
  /** The DRAWN footprint (contract v6 Nr. 1), hoisted out of `map3d`: the
   *  same LOCAL-metre points, `null` when the location has no area. A map
   *  client draws it through the § A1.1 pin transform; the editor reads the
   *  nested one, because it edits the record. */
  boundary?: Array<[number, number]> | null
  /** Present only when at least one room carries a layout (AV3D-2⁺). */
  layout_sig?: string
  /** A transit place (a road, a district) is walked THROUGH, never travelled
   *  TO (§ A1.9). The player map draws it differently, the destination list
   *  drops it — it is NOT the terrain passability, which lives on
   *  `TerrainType`. */
  passable?: boolean
}

/** The running journey of a character (§ A11) — the metre polyline plus how
 *  far along it the walker is. `waypoints` is `null` for EVERYONE but the
 *  avatar in a fogged payload (§ A12), so a client that has only the point
 *  draws only the point. */
export interface WorldmapTravel {
  target_id: string
  waypoints: Array<[number, number]> | null
  /** `null` under the fog (§ A12): the row stays (the `target_id` is opaque),
   *  but route, distance and timing are thinned out for foreign travellers. */
  progress_m: number | null
  total_m: number | null
  /** Arrival on the WORLD CALENDAR as the canonical stamp
   *  `Y0002-D109T14:00:00` — there is no world timezone any more, and no
   *  client parses this. `null` under the fog (§ A12). */
  eta_game: string | null
  /** The same arrival rendered by the SERVER: `eta_hhmm` is the clock time
   *  ("14:00"), `eta_label` the full calendar label ("Summer, day 17 · 14:00
   *  · Year 3"). `null` under the fog, like everything else in this block. */
  eta_hhmm: string | null
  eta_label: string | null
  speed_m_s_real: number | null
  pace_m_s_real: number | null
}

/**
 * A location dict of `GET /world/locations` — the editor's read side. It has
 * the full record, so it is the ONLY shape that may be asked about templates
 * or clone origins, and it carries the raw scale anchor of UNPLACED locations
 * too (in `map3d.plan_width_m`, which the worldmap row would report as null).
 *
 * `passable` here means "may be walked into as a place" — it is NOT the
 * terrain flag. Ground passability lives on `TerrainType` (§ A1.5) and nowhere
 * else.
 */
export interface EditorLocation extends MapGeometry {
  passable?: boolean
  template_location_id?: string
  description?: string
  /** Chosen gallery file for the flat map icon (`PATCH .../map-image`); empty
   *  falls back to the first `map_2d` image of the gallery owner. */
  map_image_2d?: string
  /** 90°-step display rotation of that ICON (`PATCH .../map-rotation`) — it
   *  turns the artwork inside the footprint and is NOT `yaw_deg`, which turns
   *  the location itself in the world. */
  map_rotation_2d?: number
  /** Server findings about the DRAWN boundary (contract v6 Nr. 1), today only
   *  `boundary_self_intersection`. Absent = nothing to report. The scene
   *  payload reports the same kinds in its `problems[]`, but a bare location
   *  (a pin with an outline and no rooms) composes no scene at all — this
   *  field is how the map editor hears about it anyway. */
  boundary_problems?: string[]
  /** The location's ROOMS with their floor-plan layouts, exactly as the full
   *  record carries them (`world_ops.build_locations_payload` returns
   *  `list_locations()` untouched, so nothing had to be added server-side for
   *  this). The map's "Rooms" view draws their hulls over the painted ground
   *  — see `roomShapes`. Only the two fields it needs are declared: this is
   *  the MAP's read of a location, and the room EDITOR reads the same records
   *  through `worldTypes.Location`, which has the rest. */
  rooms?: Array<{ id?: string; name?: string; layout?: RoomLayout }>
}

/** A character on the worldmap (§ A1.4). `pos` is the truth; `location_id` is
 *  derived from it, and an empty one plus a `pos` means WILDERNESS. */
export interface WorldmapCharacter {
  name: string
  location_id: string
  pos: { x: number; z: number } | null
  height_cm: number | null
  room_id: string
  activity: string
  activity_animation: string
  animation_set: string
  animation_sets: string[]
  mood: string
  movement_target_id: string
  movement_target_name: string
  travel: WorldmapTravel | null
  avatar_url: string
}

/** `GET /play/worldmap` (§ A1.3). `world_bounds` is computed BEFORE the fog
 *  filter, so the frame does not jump when the avatar discovers something —
 *  and it may be degenerate. Refetch `GET /play/terrain` when `terrain_sig`
 *  changes, never otherwise. */
export interface WorldmapPayload {
  avatar: string
  current_location_id: string
  locations: WorldmapLocationRow[]
  characters: WorldmapCharacter[]
  events_by_location: Record<string, Array<{ category: string; text: string }>>
  world_bounds: MapBounds | null
  terrain_sig: string
  /** Signature of the authored RELIEF (§ A16) — the refetch trigger for the
   *  heightfield, exactly as `terrain_sig` is for the painted ground. */
  height_sig?: string
  fogged: boolean
  /** The two walk limits the server judges every reported point with
   *  (§ A1.3, § A15 Nr. 8). The map editor needs `max_slope_deg` to say when a
   *  drawn ramp is steeper than anyone can climb. Optional: an older server
   *  does not send them, and then the same defaults apply that
   *  `app/core/relief.py` falls back to. */
  max_step_height_m?: number
  max_slope_deg?: number
}

/**
 * One entry of `meta.scatter` of a painted AREA — what this piece of ground
 * grows (finding B17; it used to hang on the terrain TYPE, which could only
 * ever say "all forest everywhere grows this one tree").
 *
 * The server whitelists exactly these three fields
 * (`app/models/terrain._sanitize_scatter_list`), the 3D ground instances them
 * and the map preview draws them — all three from the ONE shared sampler
 * (`@anima/scene-render` → `scatterInstances`). No list = nothing is
 * scattered; there is no default.
 */
export interface TerrainScatterEntry {
  /** Instances per 100 m² of the painted area. 0 = nothing is scattered. */
  density_per_100m2: number
  /** TARGET height in metres: a prop model is scaled uniformly until its
   *  bounding box is this tall, and the built-in tuft is built this high.
   *  Absent = the prop's OWN height from the library (the server ships it as
   *  `prop_height_m`), and only where there is no prop record the 3D client's
   *  flat 2 m (0.8 m for a tuft) — never the model's authored file size,
   *  which is no size at all in a world measured in metres. */
  height_m?: number
  /** URL of a prop mesh to instance — `/assets/props/<id>/model`, the same
   *  URL the prop library hands out. Absent = the built-in tuft. */
  model?: string
}

/** One kind of ground in the effective catalog (§ A1.5). `passable`,
 *  `speed_factor` and the two clip keys come from HERE and nowhere else —
 *  never from an area, never from a client table. `meta` is free-form apart
 *  from those keys; what grows on ground belongs to the AREA (finding B17). */
export interface TerrainType {
  kind: string
  name: string
  /** `#rrggbb` — the colour of the 2D schematic map. */
  color: string
  /** May one STAND here? The WILDERNESS answer: inside a placed footprint the
   *  footprint wins and this says nothing (§ A15). */
  passable: boolean
  /** Walking-pace multiplier, 0..2. Unlike `passable` it counts EVERYWHERE
   *  (finding 3, 2026-08-13) — a footprint only neutralises a factor of 0,
   *  which is a ground nobody meant to be walked rather than a slow one. */
  speed_factor: number
  /** WHICH GROUND MATERIAL this kind wears — the `kind` of the surface-texture
   *  library, said out loud (2026-08-16). It used to be matched by NAME, which
   *  meant a type could never wear a differently named texture and renaming a
   *  library entry undressed every ground using it. The name match is gone
   *  without a fallback: absent or empty = the default ground, exactly what a
   *  type without a same-named library entry rendered before. Nothing is
   *  validated against the library on save — the Terrain tab MARKS a value the
   *  library does not hold instead (§ A1.5). */
  surface?: string
  /** Free-form, with four contracted keys: `meta.move_anim`, the animation
   *  clip a MOVING figure plays on this ground instead of walk/run (§ A9 —
   *  "swim" on water), `meta.idle_anim`, the one a STANDING figure plays
   *  instead of its own ("treading-water"), and the two depths
   *  `meta.move_sink_m` / `meta.idle_sink_m`, how deep the figure stands IN
   *  the ground while it moves and while it waits (two numbers, because the
   *  two poses hang differently in the water). Absent = walk, run and idle as
   *  usual, on top of the ground; the server never stores an empty one. */
  meta?: Record<string, unknown>
}

/**
 * The RECIPE of an area drawn as a line: a centre line in world metres, the
 * width of the ribbon it becomes, and how the line is BENT on the way. It
 * lives in `meta.stroke` and is exactly that — a recipe. The polygon stays the
 * truth for the server, for point queries and for every renderer; this only
 * lets the editor put the handles back on the line the user drew and generate
 * the very same outline again.
 *
 * The three decoration fields are absent for a straight line, which is what
 * every stroke drawn before the styles existed is: `MapTab.readStroke` fills
 * them in for the editor, `MapTab.storedStroke` strips them again on the way
 * back, and the server whitelists all five (`app/models/terrain.py`).
 *
 * `meta` is free-form JSON the server passes through verbatim, so nothing
 * guarantees a stored `stroke` has this shape — read it through a check, never
 * by trusting the declaration.
 */
export interface TerrainStroke {
  points: Array<[number, number]>
  width_m: number
  /** absent = `straight`, the line as it was clicked */
  style?: StrokeStyle
  /** roughly how far apart the deflections sit, in metres */
  spacing_m?: number
  /** how far they swing to either side of the line, in metres */
  amplitude_m?: number
}

/** An area's `meta`. Free-form by contract — the known key is named, the rest
 *  stays open, and a foreign key written by anything else survives a round
 *  trip through the editor untouched. */
export type TerrainMeta = {
  stroke?: TerrainStroke
  scatter?: TerrainScatterEntry[]
} & TerrainWater & Record<string, unknown>

/**
 * THE THREE NUMBERS A WATER AREA CARRIES (plan "Ein Boden" § 2 G4).
 *
 * Water is the one surface that is FLAT: the bake presses the ground under a
 * water polygon down to `water_level − depth` and runs a shore ramp back up to
 * the untouched land, so no relief can poke through the mirror at any distance
 * or in any level of detail. All three are optional — an unset field means
 * "let the server decide", and the server's own default for the level is the
 * median height along the rim of the polygon.
 *
 * They live in the area's free-form `meta`, which is a FULL REPLACE on every
 * write, so an unset field is an absent key and never a stored zero.
 */
export interface TerrainWater {
  /** The mirror, as a world-y height in metres. Absent = the rim median. */
  water_level?: number
  /** How deep the bed is carved under the mirror, in metres (0.2…20). */
  water_depth_m?: number
  /** Over how many metres the bed climbs back to the untouched land at the
   *  shore, in metres (0…20). 0 = a wall at the water's edge. */
  shore_ramp_m?: number
}

/** A painted polygon in world metres (§ A1.5). Points are `[x, z]`, 3–256 of
 *  them, auto-closed by the server. */
export interface TerrainArea {
  id: string
  kind: string
  polygon: Array<[number, number]>
  z_order: number
  meta?: TerrainMeta
}

/**
 * The scatter list of an area, read through a check.
 *
 * `meta` is free-form JSON the server passes through, so nothing in the type
 * system guarantees a stored `scatter` has the declared shape — and most areas
 * carry none at all. The server whitelists what it STORES
 * (`app/models/terrain._sanitize_scatter_list`); this is the reader's half of
 * the same contract, and it is the ONE place the editor reads it, so the chip
 * and the preview always see the same list.
 *
 * Every field is coerced, never trusted: a junk density is 0 (scatter nothing,
 * exactly how both renderers read it) and a height that is not a height loses
 * the key, so a model keeps its own size.
 */
export function readScatter(meta: TerrainMeta | undefined): TerrainScatterEntry[] {
  const raw = meta?.scatter
  if (!Array.isArray(raw)) return []
  const out: TerrainScatterEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const e = item as unknown as Record<string, unknown>
    const density = Number(e.density_per_100m2)
    const height = Number(e.height_m)
    const entry: TerrainScatterEntry = {
      density_per_100m2: Number.isFinite(density) && density > 0 ? density : 0,
    }
    if (Number.isFinite(height) && height > 0) entry.height_m = height
    if (typeof e.model === 'string' && e.model) entry.model = e.model
    out.push(entry)
  }
  return out
}

/**
 * The water numbers of an area, read through a check — the reader's half of
 * `TerrainWater`, exactly as `readScatter` is for the scatter list.
 *
 * `meta` is free-form JSON the server passes through, so nothing in the type
 * system guarantees a stored number IS a number. A value that is not finite
 * loses its key rather than becoming 0: "0 m deep" and "the server decides"
 * are different answers, and only one of them may be inferred from junk.
 */
export function readWater(meta: TerrainMeta | undefined): TerrainWater {
  const out: TerrainWater = {}
  const num = (v: unknown): number | undefined => {
    // `null` and `''` both coerce to 0, which would invent a stored number
    // where the key says nothing — only a real number counts.
    if (typeof v !== 'number' && typeof v !== 'string') return undefined
    if (typeof v === 'string' && v.trim() === '') return undefined
    const n = Number(v)
    return Number.isFinite(n) ? n : undefined
  }
  const level = num(meta?.water_level)
  const depth = num(meta?.water_depth_m)
  const ramp = num(meta?.shore_ramp_m)
  if (level !== undefined) out.water_level = level
  if (depth !== undefined) out.water_depth_m = depth
  if (ramp !== undefined) out.shore_ramp_m = ramp
  return out
}

/** `GET /play/terrain`. `areas` arrive BOTTOM to TOP — the last entry is on
 *  top, and the topmost area that contains a point owns it. */
export interface TerrainPayload {
  default_kind: string
  types: TerrainType[]
  areas: TerrainArea[]
  sig: string
}

/**
 * One authored HEIGHT AREA of the world relief (§ A16, `GET /world/height-areas`).
 *
 * The ground inside `polygon` stands at `height_m` and ramps there linearly
 * over the last `falloff_m` metres before the outline, so the area meets the
 * world at 0 exactly ON its own outline. A negative height is a hollow, not a
 * mistake; `falloff_m` 0 is a wall at the edge (legal, and warned about when
 * it is steeper than a walker can climb).
 *
 * It carries NO kind and NO layer: heights are not terrain (the ground under a
 * painted meadow may well rise), and overlaps are resolved by the server
 * arithmetically — the strongest deflection from the flat world wins.
 */
export interface HeightArea {
  id: string
  polygon: Array<[number, number]>
  height_m: number
  falloff_m: number
  meta?: Record<string, unknown>
}

/** `GET /world/height-areas` — the editor's read side of the relief. `sig` is
 *  the same signature the worldmap payload carries as `height_sig`. */
export interface HeightAreasResp {
  areas: HeightArea[]
  sig: string
  /** The grid step the world relief is rastered at RIGHT NOW, in metres
   *  (finding 14). Nobody sets it: the server doubles it until the grid over
   *  the whole painted extent fits its point budget, so an area drawn far out
   *  coarsens the relief everywhere. The editor shows it and warns when a save
   *  moves it — see `heightMath.reliefStepNotice`. */
  step_m?: number
  /** The finest step the OVERVIEW gets (`heightfield.DEFAULT_STEP_M`) — what
   *  "coarser than normal" is measured against, so the editor holds no
   *  constant of its own. */
  default_step_m?: number
  /** The step of the fine height TILES (`heightfield.TILE_STEP_M`), a
   *  different number since 2026-08-14. The micro-relief warning of the
   *  terrain tab is measured against it (`heightMath.reliefWarnAmpM`). It
   *  comes from the server for the same reason the two above do: the number
   *  halved the day the tiles did. */
  tile_step_m?: number
  /** The walk gate: steepest slope a figure climbs (`game.max_slope_deg`) and
   *  the highest single step it takes (`game.max_step_height_m`). The same two
   *  numbers `/play/worldmap` carries — here so an editor that shows a relief
   *  amplitude can say when it becomes unwalkable without pulling the whole
   *  map for two floats. */
  max_slope_deg?: number
  max_step_height_m?: number
}

/** What `POST`/`PUT /world/height-areas` answer. The step is the one the world
 *  has AFTERWARDS (the write re-rasters synchronously), which is what makes
 *  the coarsening warning a fact rather than a forecast. */
export interface HeightAreaWriteResp {
  area?: HeightArea
  step_m?: number
}

/** ONE authored prop on the world plane (§ A9a) as the EDITOR reads it —
 *  `GET /world/world-props`, not the worldmap block.
 *
 *  `x`/`z`/`offset_y` are world metres, `yaw_deg` the § A1.1 rotation written
 *  through unchanged. `variant` is `null` for "the placement id decides"
 *  (`world_props.variant_index`) and a number for "this mesh, always".
 *  `missing` marks a placement whose prop was deleted: it renders nothing and
 *  can only be removed. */
export interface WorldProp {
  id: string
  prop_id: string
  x: number
  z: number
  yaw_deg: number
  offset_y: number
  variant: number | null
  /** Library display name; '' together with `missing` when the prop is gone. */
  name?: string
  /** How many ACTIVE variants WITH a mesh the prop has — the editor offers
   *  exactly that many indices instead of holding a ceiling of its own
   *  (`image_generation.prop_variant_max` is configurable). */
  variant_count?: number
  missing?: boolean
}

/** `GET /world/world-props` — the placements plus the two cap numbers, so the
 *  editor holds no ceiling of its own (§ A9a: refuse at `max`, warn from
 *  `warn_at`). */
export interface WorldPropsResp {
  world_props: WorldProp[]
  count: number
  max: number
  warn_at: number
  sig: string
}

/** `GET /world/terrain-types` — the admin view: the catalog plus where each
 *  entry comes from. */
export interface TerrainTypesResp {
  types: TerrainType[]
  sources: Record<string, 'shared' | 'world'>
}

/** Extent of the world in metres (§ A1.3), the `world_bounds` root field. May
 *  be degenerate (`min == max`); anyone dividing by it must cope. Declared
 *  once, in `mapMath` — the math and the payload mean the same box. */
export type { MapBounds } from './mapMath'
