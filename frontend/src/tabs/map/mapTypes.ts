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
 * interface would let a filter on `is_template` compile against worldmap rows
 * and silently return nothing. They share their geometry through `MapGeometry`
 * and part ways after it.
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
  is_template?: boolean
  template_location_id?: string
  description?: string
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
  travel: Record<string, unknown> | null
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
  fogged: boolean
}

/** One kind of ground in the effective catalog (§ A1.5). `passable` and
 *  `speed_factor` come from HERE and nowhere else — never from an area, never
 *  from a client table. */
export interface TerrainType {
  kind: string
  name: string
  /** `#rrggbb` — the colour of the 2D schematic map. */
  color: string
  passable: boolean
  speed_factor: number
  meta?: Record<string, unknown>
}

/** A painted polygon in world metres (§ A1.5). Points are `[x, z]`, 3–256 of
 *  them, auto-closed by the server. */
export interface TerrainArea {
  id: string
  kind: string
  polygon: Array<[number, number]>
  z_order: number
  meta?: Record<string, unknown>
}

/** `GET /play/terrain`. `areas` arrive BOTTOM to TOP — the last entry is on
 *  top, and the topmost area that contains a point owns it. */
export interface TerrainPayload {
  default_kind: string
  types: TerrainType[]
  areas: TerrainArea[]
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
