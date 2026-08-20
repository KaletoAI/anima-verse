/**
 * roomShapes — the floor-plan ROOMS of a placed location, in WORLD metres.
 *
 * The map's third location view ("Rooms") draws what the floor plan drew: the
 * room shapes themselves, on the world map, over the painted ground. That is
 * the whole purpose — a lake location whose water and shore rooms have to line
 * up with the painted water is aligned by looking at both at once, and a roof
 * render says nothing about where the water room ends.
 *
 * NO GEOMETRY IS INVENTED HERE. A room hull is `planGeometry.absOutline` — the
 * very function the floor-plan editor draws with, so the room's own
 * `rotation` (contract v6 addendum, turned about the RECT CENTRE) is applied
 * exactly once and exactly as the plan applies it. The step from there into
 * the world is `mapMath.localToWorld`, the § A1.1 pin transform the location
 * boundary already rides — point by point, so no SVG rotation is involved and
 * the sign trap of a rotated square does not exist (see `PlacementLayer`).
 *
 * Two turns, two centres, in this order:
 *   1. the ROOM's `rotation` about its own rect centre  (room → location-local)
 *   2. the LOCATION's `yaw_deg` about the pin           (location-local → world)
 *
 * Hand-derived case (`scripts/smoke_map_room_shapes.mjs` runs it): a 4×2 room
 * at min corner (1,1) with `rotation` 90, in a location pinned at (100,50)
 * with `yaw_deg` 90.
 *   room-local hull [[0,0],[4,0],[4,2],[0,2]], min corner (1,1), centre (3,2)
 *   step 1, rotateAbout(·, (3,2), 90):  x' = 3 + lz,  z' = 2 − lx
 *     (1,1) -> (2,4)   (5,1) -> (2,0)   (5,3) -> (4,0)   (1,3) -> (4,4)
 *     i.e. 4 m wide × 2 m deep became 2 m × 4 m — the turn is real
 *   step 2, localToWorld(100, 50, 90, ·):  x = 100 + lz,  z = 50 − lx
 *     (2,4) -> (104,48)  (2,0) -> (100,48)  (4,0) -> (100,46)  (4,4) -> (104,46)
 *     i.e. 2 m × 4 m became 4 m × 2 m again — turned back by the pin
 *
 * THE PIN IS PASSED IN, never read off the location: while a footprint is
 * being dragged the outline follows the cursor, and the rooms have to follow
 * it in the same frame or the overlay would lag one gesture behind the shape
 * it belongs to.
 *
 * Only ONE storey is drawn (level 0 by default): the map is a top-down view of
 * the ground, and stacking a first floor over it would say two things about
 * the same square metre. The YARD (§ A13a) carries no rectangle at all — its
 * surface IS the boundary — so it has no shape here and is left out.
 */
import { absOutline, type Pt } from '../world/planGeometry'
import { hasRect, type RoomLayout } from '../world/worldTypes'
import { localToWorld } from './mapMath'

/** A room as far as this overlay cares — the shape of `Location.rooms[]`. */
export interface RoomEntry {
  id?: string
  name?: string
  layout?: RoomLayout
}

/** One room, ready to draw: its hull in WORLD metres plus what it is made of. */
export interface RoomShape {
  id: string
  name: string
  /** Hull in WORLD metres, in stored winding (clockwise in map view). */
  poly: Pt[]
  /** `surfaces.floor` — a kind of the surface-texture library, or '' when the
   *  room names none and the renderers fall back to their default ground. */
  floor: string
  /** `always_visible`: an OUTDOOR room that is never hidden by the interior
   *  view — a shore, a road, a clearing. It is drawn fainter, because it is
   *  ground rather than a closed room. */
  open: boolean
}

/**
 * The level-0 room hulls of a location, in WORLD metres.
 *
 * `cx`/`cz`/`yawDeg` are the location's placement — passed in, see the module
 * docstring. A room without a rectangle (the yard) and a room on another
 * storey are not shapes on this map and are dropped.
 */
export function roomShapesWorld(rooms: RoomEntry[] | undefined | null,
  cx: number, cz: number, yawDeg: number, level = 0): RoomShape[] {
  const out: RoomShape[] = []
  for (const room of rooms || []) {
    const lay = room.layout
    if (!hasRect(lay)) continue
    if ((lay.level || 0) !== level) continue
    const poly = absOutline(lay).map(([lx, lz]) => {
      const p = localToWorld(cx, cz, yawDeg, lx, lz)
      return [p.x, p.z] as Pt
    })
    out.push({
      id: room.id || '',
      name: room.name || room.id || '',
      poly,
      floor: (lay.surfaces?.floor || '').trim(),
      open: !!lay.always_visible,
    })
  }
  return out
}

/** Axis-aligned bounding box of a polygon, in the polygon's own units. */
export function polyBBox(poly: Pt[]): {
  minX: number; maxX: number; minZ: number; maxZ: number
} | null {
  if (!poly.length) return null
  let minX = Infinity
  let maxX = -Infinity
  let minZ = Infinity
  let maxZ = -Infinity
  for (const [x, z] of poly) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  return { minX, maxX, minZ, maxZ }
}

/**
 * WHAT A FLOOR KIND LOOKS LIKE, for the kinds the painted ground has no type
 * for — built floors, mostly. It is a small table and deliberately not a
 * guess: an unknown kind gets the fallback grey rather than a colour inferred
 * from its name.
 *
 * The kinds the terrain catalog DOES wear (water, grass, sand, …) are not
 * resolved from here at all — `floorColor` asks the catalog first, so a room
 * of painted-water floor comes out in the exact colour the painted water next
 * to it has. That identity is the point of the whole view: a shore room that
 * sits on the wrong ground shows as two colours, not as two shades.
 */
export const FLOOR_KIND_COLORS: Record<string, string> = {
  // Ground the shared terrain catalog also names — same values as
  // `shared/terrain/types.json`, so a world that removed those types still
  // draws its rooms in the colours the map has always used for them.
  water: '#4a90d9',
  deep_water: '#1d3f6e',
  grass: '#6a994e',
  forest: '#386641',
  deep_forest: '#2c5133',
  sand: '#e9c46a',
  // Built ground, which the terrain catalog has no kind for at all.
  coast: '#d9c9a3',
  city: '#8d8d8d',
  street: '#5a5a5a',
  dark_stone: '#4b5058',
  dark_stone_2: '#3a3f47',
  tiled_floor: '#b9c2cc',
  wooden_floor: '#b07d4a',
  dark_wooden_floor: '#6b4a2c',
  rubber_flooring: '#4a4a52',
}

/** A room that names no floor kind, and one that names an unknown one: the
 *  neutral grey every other placeholder on this canvas uses. */
export const FLOOR_FALLBACK_COLOR = '#8b949e'

/**
 * The colour of one floor kind.
 *
 * `surfaceColors` is the map's own terrain catalog, folded to
 * `surface kind -> #rrggbb` (a `TerrainType` says which surface material it
 * wears, and which colour the schematic map paints it in). It WINS: the whole
 * point of drawing rooms over the painted ground is comparing the two, and
 * two different blues for one material would be a difference the world does
 * not have.
 */
export function floorColor(kind: string,
  surfaceColors?: Record<string, string>): string {
  const k = (kind || '').trim()
  if (!k) return FLOOR_FALLBACK_COLOR
  return surfaceColors?.[k] || FLOOR_KIND_COLORS[k] || FLOOR_FALLBACK_COLOR
}

/**
 * `surface kind -> colour`, folded out of the effective terrain catalog.
 *
 * A type without a `surface` wears the renderers' default ground and names no
 * material, so it contributes nothing. Two types wearing the SAME material is
 * legal (that is why the match by name was dropped, 2026-08-16) — the first
 * one wins, because a material has one colour and the catalog order is the
 * catalog's own.
 */
export function surfaceColorMap(
  types: Array<{ surface?: string; color: string }>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const ty of types) {
    const s = (ty.surface || '').trim()
    if (!s || out[s] || !ty.color) continue
    out[s] = ty.color
  }
  return out
}
