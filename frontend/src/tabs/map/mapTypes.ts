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
import type { MapBounds } from './mapMath'
import type { Map3D } from '../world/worldTypes'

export type { Map3D }

/**
 * The map geometry every location carries, wherever it comes from.
 *
 * `pos_x`/`pos_z` are world METRES and `null` when the location is unplaced —
 * it then stands on no map at all. `yaw_deg` is the § A1.1 rotation and is
 * written through unchanged: NO sign conversion anywhere in the editor
 * (`map3d.rotation` is the OTHER, scene-side field — mixing them mirrors the
 * location).
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
  /** ISO stamp on the GAME clock, in the world timezone — an HH:MM slice is
   *  game wall-clock time. `null` under the fog (§ A12). */
  eta_game: string | null
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
  /** Opt-in flattening (§ A16.1, `PUT /world/locations/{id}`): only a location
   *  with this flag levels the world relief under its footprint. Absent =
   *  `false` — the authored landscape then runs straight through the place.
   *  It belongs to the PLACEMENT, so a clone carries its own and never
   *  inherits the template's. */
  level_ground?: boolean
  template_location_id?: string
  description?: string
  /** Chosen gallery file for the flat map icon (`PATCH .../map-image`); empty
   *  falls back to the first `map_2d` image of the gallery owner. */
  map_image_2d?: string
  /** 90°-step display rotation of that ICON (`PATCH .../map-rotation`) — it
   *  turns the artwork inside the footprint and is NOT `yaw_deg`, which turns
   *  the location itself in the world. */
  map_rotation_2d?: number
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
  /** Free-form, with three contracted keys: `meta.move_anim`, the animation
   *  clip a MOVING figure plays on this ground instead of walk/run (§ A9 —
   *  "swim" on water), `meta.idle_anim`, the one a STANDING figure plays
   *  instead of its own ("treading-water"), and `meta.sink_m`, how deep the
   *  figure stands IN the ground while either runs. Absent = walk, run and
   *  idle as usual, on top of the ground; the server never stores an empty
   *  one. */
  meta?: Record<string, unknown>
}

/**
 * The RECIPE of an area drawn as a line: a centre line in world metres plus a
 * width. It lives in `meta.stroke` and is exactly that — a recipe. The polygon
 * stays the truth for the server, for point queries and for every renderer;
 * this only lets the editor put the handles back on the line the user drew.
 *
 * `meta` is free-form JSON the server passes through verbatim, so nothing
 * guarantees a stored `stroke` has this shape — read it through a check, never
 * by trusting the declaration.
 */
export interface TerrainStroke {
  points: Array<[number, number]>
  width_m: number
}

/** An area's `meta`. Free-form by contract — the known key is named, the rest
 *  stays open, and a foreign key written by anything else survives a round
 *  trip through the editor untouched. */
export type TerrainMeta = {
  stroke?: TerrainStroke
  scatter?: TerrainScatterEntry[]
} & Record<string, unknown>

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
