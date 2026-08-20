/**
 * boundaryApi — the ONE write path of a location's drawn boundary
 * (contract v6 Nr. 1, "Gebiete").
 *
 * TWO EDITORS RESHAPE THE SAME POLYGON. The map tab drags its vertices in
 * WORLD metres and converts them back through the § A1.1 pin transform; the
 * floor-plan editor drags them in the plan's own LOCAL metres, which is the
 * frame the field is stored in, so it converts nothing at all. What they must
 * NOT do twice is the write: the point caps, the distance bound and the
 * read-back of what the server actually stored are the same three rules for
 * both, and two copies of them drift (the map tab would learn about a cap the
 * floor plan still lets through, or the other way round).
 *
 * The write is `PUT /world/locations/{id}` with the WHOLE `map3d` object:
 * `world_ops._sanitize_map3d` REPLACES the field, never merges it, so dropping
 * the rest would take the building's storey height, its outline and its
 * pass-throughs with it. `plan_width_m` is deliberately not sent — since v6
 * Nr. 2 it is derived from the boundary's bounding box and the server
 * overwrites whatever a client submits.
 *
 * THE ANSWER IS THE TRUTH, not what was sent: the server rounds to the
 * centimetre, drops a repeated closing point, turns the ring into ONE winding
 * (clockwise in map view = positive shoelace) and derives the width. Both
 * editors read the stored `map3d` back, which is what keeps their vertex
 * handles sitting on the points that really exist.
 */
import { apiPut } from '../../lib/api'
import type { Map3D } from './worldTypes'

/** How many points a boundary may hold (`world_ops._sanitize_map3d` slices at
 *  64) and the fewest that still enclose an area. Mirrored so an editor says
 *  why instead of losing vertices to a silent truncation. */
export const BOUNDARY_MAX_POINTS = 64
export const BOUNDARY_MIN_POINTS = 3

/** Sanity bound on a boundary point's distance from the pin, in metres — the
 *  same range the world itself is measured in (`MAX_COORD` of the map tab's
 *  terrain tools, the server's own coordinate window). A point beyond it is a
 *  slip, not a plot. */
export const BOUNDARY_MAX_COORD_M = 100000

/** Edge of the square a boundary is SEEDED as when the location has no width
 *  to derive one from — a first shape to drag vertices out of, never a claim
 *  about ground. Same number as the map tray's anchor-less ghost. */
export const BOUNDARY_SEED_M = 10

/**
 * A centred square as a boundary, in LOCAL metres: the seed every location
 * starts from (a square is only the special case of the polygon). Clockwise in
 * map view, which with x east and z south is the POSITIVE shoelace direction
 * the server stores — (−h,−h) → (h,−h) → (h,h) → (−h,h) sums to +4h² > 0 — so
 * the sanitizer keeps the order and the vertices stay where the hand grabbed
 * them. Rounded to the centimetre, like everything the sanitizer keeps.
 */
export function seedSquare(widthM: number): Array<[number, number]> {
  const h = Math.round((widthM / 2) * 100) / 100
  return [[-h, -h], [h, -h], [h, h], [-h, h]]
}

/** What is wrong with a proposed boundary — `message` is the ENGLISH source
 *  string the caller runs through `t()`, `n` the number it names. Null means
 *  the write may go ahead. */
export interface BoundaryComplaint {
  message: string
  n: number
}

/** The three rules a boundary write has to pass, in one place. Stated as a
 *  complaint rather than a toast, because only the calling editor knows how it
 *  talks to its user. */
export function boundaryComplaint(
  points: Array<[number, number]>): BoundaryComplaint | null {
  if (points.length < BOUNDARY_MIN_POINTS) {
    return { message: 'A boundary needs at least {n} points',
             n: BOUNDARY_MIN_POINTS }
  }
  if (points.length > BOUNDARY_MAX_POINTS) {
    return { message: 'A boundary holds at most {n} points',
             n: BOUNDARY_MAX_POINTS }
  }
  const inRange = points.every(([x, z]) =>
    Number.isFinite(x) && Number.isFinite(z)
    && Math.abs(x) <= BOUNDARY_MAX_COORD_M
    && Math.abs(z) <= BOUNDARY_MAX_COORD_M)
  if (!inRange) {
    return { message: 'A boundary point may not lie further than {n} m from the pin',
             n: BOUNDARY_MAX_COORD_M }
  }
  return null
}

/**
 * Write the boundary and answer with the map3d the server STORED — or `null`
 * when the answer carried none (an older route, a stripped response). The
 * caller keeps its optimistic patch in that case; it never invents a shape.
 *
 * Throws whatever `apiPut` throws: the two editors both toast the message and
 * put the truth back their own way (the map tab refetches, the floor plan
 * keeps its draft).
 */
export async function putLocationBoundary(locationId: string,
  map3d: Map3D | undefined,
  points: Array<[number, number]>): Promise<Map3D | null> {
  const body: Map3D = { ...(map3d || {}), boundary: points }
  const r = await apiPut<{ location?: { map3d?: Map3D } }>(
    `/world/locations/${encodeURIComponent(locationId)}`, { map3d: body })
  return r?.location?.map3d || null
}
