/**
 * mapTypes — what the map editor reads from the server, nothing more.
 *
 * The shapes follow the contract (`docs/schnittstellen-3d.md` § A1.3 worldmap,
 * § A1.5 terrain, § A1.7 editor CRUD). The 3D metadata block is NOT re-declared
 * here — `Map3D` lives once, in `../world/worldTypes`, and both the location
 * editor and the map read the same declaration.
 */
import type { Map3D } from '../world/worldTypes'

export type { Map3D }

/**
 * A location as the map editor sees it. `GET /world/locations` returns the full
 * dicts (scale anchor included, even for unplaced ones); `GET /play/worldmap`
 * returns the same geometry fields plus `plan_width_m` pulled up from `map3d`.
 *
 * `pos_x`/`pos_z` are world METRES and `null` when the location is unplaced —
 * it then stands on no map at all. `yaw_deg` is the § A1.1 rotation and is
 * written through unchanged: NO sign conversion anywhere in the editor
 * (`map3d.rotation` is the OTHER, scene-side field — mixing them mirrors the
 * location).
 */
export interface MapLocation {
  id: string
  name: string
  pos_x?: number | null
  pos_z?: number | null
  yaw_deg?: number | null
  /** Edge length of the footprint square in metres. Pulled up from
   *  `map3d.plan_width_m` by the worldmap payload; `null` means unplaced OR
   *  no usable anchor — either way the location has no area. */
  plan_width_m?: number | null
  map3d?: Map3D
  passable?: boolean
  is_template?: boolean
  template_location_id?: string
  description?: string
  /** Present on worldmap rows whose rooms carry layouts (AV3D-2⁺). */
  layout_sig?: string
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
