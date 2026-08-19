/**
 * Polygon primitives of a location's FOOTPRINT (contract v6 "Gebiete").
 *
 * Since v6 the footprint of a location is a drawn POLYGON, never a square:
 * `map3d.boundary` holds its outline in LOCAL METRES around the anchor pin
 * (`pos_x`/`pos_z`, turned by `yaw_deg`, § A1.1). A legacy square arrives from
 * the server as its four synthesized corners (`world_geometry.effective_
 * boundary`), so there is no square code path on this side at all — one
 * containment test, one area, one distance, for every location.
 *
 * THE CLIENT TWIN of `app/core/world_geometry`: same half-open ray cast, same
 * shoelace sign (with x east and z south a POSITIVE sum is CLOCKWISE in map
 * view — the winding the server stores), same "0 anywhere inside" distance.
 * Concave outlines are explicitly allowed (decision E1.1), so nothing here may
 * assume convexity; overlap stays legal and the SMALLEST AREA wins (E1.2).
 *
 * PURE like `walk.ts` and `enterLocation.ts`: no `three`, no DOM, no imports
 * and no module state — that is what lets
 * `client3d/scripts/smoke_polygon_containment.mjs` check every case by hand
 * against the server's own `scripts/smoke_world_polygon.py`.
 */

/** A point on the world or tile plane, in metres. */
export interface Point { x: number; z: number }

/** One outline point as the payload spells it: `[x, z]` in local metres. */
export type PolyPoint = readonly number[];
/** A boundary as it arrives — auto-closed, at least 3 points to enclose
 *  anything. */
export type Polygon = readonly PolyPoint[];

/**
 * Parse a raw boundary into finite `[x, z]` pairs, or `null`.
 *
 * `null` for anything that cannot enclose an area: a malformed or non-finite
 * entry, or fewer than three points (a line claims no area). An explicitly
 * closed ring is tolerated — the repeated last point is dropped, exactly as
 * `world_geometry._poly_points` does it.
 */
export function sanitizePolygon(points: Polygon | null | undefined
): [number, number][] | null {
  const pts: [number, number][] = [];
  for (const pt of points ?? []) {
    if (!pt || pt.length < 2) return null;
    const x = Number(pt[0]);
    const z = Number(pt[1]);
    if (!Number.isFinite(x) || !Number.isFinite(z)) return null;
    pts.push([x, z]);
  }
  if (pts.length >= 2
      && pts[0][0] === pts[pts.length - 1][0]
      && pts[0][1] === pts[pts.length - 1][1]) pts.pop();
  return pts.length >= 3 ? pts : null;
}

/**
 * Ray-casting point-in-polygon over `[[x, z], …]` — the client's twin of
 * `world_geometry.point_in_polygon`, down to the half-open comparison
 * (`(zi > z) !== (zj > z)` and a strict `x < crossX`), so a point exactly on a
 * vertex or an edge falls to the SAME side on both sides of the wire.
 *
 * Fewer than three valid points can never contain anything -> false.
 */
export function pointInPolygon(x: number, z: number,
                               points: Polygon | null | undefined): boolean {
  const pts = sanitizePolygon(points);
  if (!pts) return false;
  let inside = false;
  let j = pts.length - 1;
  for (let i = 0; i < pts.length; i++) {
    const [xi, zi] = pts[i];
    const [xj, zj] = pts[j];
    if ((zi > z) !== (zj > z)) {
      const crossX = ((xj - xi) * (z - zi)) / (zj - zi) + xi;
      if (x < crossX) inside = !inside;
    }
    j = i;
  }
  return inside;
}

/**
 * Shoelace sum — POSITIVE means CLOCKWISE in map view (x east, z south), which
 * is the winding the server stores.
 *
 * Hand-derived on the triangle (0,0) (1,0) (0,1): east, then south-west, then
 * north — clockwise on the map — and the sum is +0.5.
 */
export function polygonSignedArea(points: Polygon | null | undefined): number {
  const pts = sanitizePolygon(points);
  if (!pts) return 0;
  let total = 0;
  let j = pts.length - 1;
  for (let i = 0; i < pts.length; i++) {
    const [xi, zi] = pts[i];
    const [xj, zj] = pts[j];
    total += xj * zi - xi * zj;
    j = i;
  }
  return total / 2;
}

/** Enclosed area in m² regardless of winding; 0 when degenerate.
 *
 *  THE tie-breaker of v6 Nr. 6: where several footprints cover one point, the
 *  smallest AREA is the most specific answer (successor of the smallest-width
 *  rule, and identical to it wherever both shapes are squares — width orders
 *  exactly like width²). */
export function polygonArea(points: Polygon | null | undefined): number {
  return Math.abs(polygonSignedArea(points));
}

/** Axis-aligned bounds of an outline, or `null` when it encloses nothing. */
export function polygonBounds(points: Polygon | null | undefined
): { minX: number; minZ: number; maxX: number; maxZ: number } | null {
  const pts = sanitizePolygon(points);
  if (!pts) return null;
  let minX = Infinity; let minZ = Infinity;
  let maxX = -Infinity; let maxZ = -Infinity;
  for (const [x, z] of pts) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  return { minX, minZ, maxX, maxZ };
}

/** Distance from a point to the closed segment a→b, in metres. */
function pointSegmentDistance(px: number, pz: number, ax: number, az: number,
                              bx: number, bz: number): number {
  const dx = bx - ax;
  const dz = bz - az;
  const len2 = dx * dx + dz * dz;
  if (len2 < 1e-18) return Math.hypot(px - ax, pz - az);
  let t = ((px - ax) * dx + (pz - az) * dz) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), pz - (az + t * dz));
}

/**
 * Shortest distance to the polygon — **0 anywhere inside**, edges inclusive;
 * `Infinity` for a degenerate outline (nothing can reach it).
 *
 * The twin of `world_geometry.polygon_distance`. Hand-derived on the L-shape
 * (0,0) (4,0) (4,2) (2,2) (2,4) (0,4):
 *   (1, 1)   → 0   inside the wide arm
 *   (5, 1)   → 1   1 m east of the x=4 edge
 *   (3, 3)   → 1   in the notch; both notch edges are 1 m away
 *   (−3, −4) → 5   past the (0,0) corner, hypot(3, 4)
 */
export function polygonDistance(x: number, z: number,
                                points: Polygon | null | undefined): number {
  const pts = sanitizePolygon(points);
  if (!pts) return Infinity;
  if (pointInPolygon(x, z, pts)) return 0;
  let best = Infinity;
  let j = pts.length - 1;
  for (let i = 0; i < pts.length; i++) {
    const [xi, zi] = pts[i];
    const [xj, zj] = pts[j];
    best = Math.min(best, pointSegmentDistance(x, z, xj, zj, xi, zi));
    j = i;
  }
  return best;
}

/** The point on the RIM nearest to (x, z), with the INWARD unit normal of the
 *  edge it sits on and the distance to it — `null` for a degenerate outline.
 *
 *  Where a location has no authored opening its whole rim is the way in (the
 *  free boundary of E4 task 5), so the offer needs a point to walk to and a
 *  direction to walk in. The inward normal follows from the STORED WINDING: on
 *  a clockwise outline (positive shoelace, x east / z south) the interior lies
 *  to the left of an edge a→b, which is `(−dz, dx)` normalised. Checked on the
 *  L-shape edge (0,0)→(4,0): `(−0, 4)/4 = (0, 1)`, and +z is indeed where the
 *  wide arm is. */
export function nearestRimPoint(x: number, z: number,
                                points: Polygon | null | undefined
): { x: number; z: number; inward: Point; dist: number } | null {
  const pts = sanitizePolygon(points);
  if (!pts) return null;
  let best: { x: number; z: number; inward: Point; dist: number } | null = null;
  let j = pts.length - 1;
  for (let i = 0; i < pts.length; i++) {
    const [bx, bz] = pts[i];
    const [ax, az] = pts[j];
    j = i;
    const dx = bx - ax;
    const dz = bz - az;
    const len2 = dx * dx + dz * dz;
    if (len2 < 1e-18) continue;
    let t = ((x - ax) * dx + (z - az) * dz) / len2;
    t = Math.max(0, Math.min(1, t));
    const cx = ax + t * dx;
    const cz = az + t * dz;
    const dist = Math.hypot(x - cx, z - cz);
    if (best && dist >= best.dist) continue;
    const len = Math.sqrt(len2);
    best = { x: cx, z: cz, inward: { x: -dz / len, z: dx / len }, dist };
  }
  return best;
}
