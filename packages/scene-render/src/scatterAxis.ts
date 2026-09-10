/**
 * scatterAxis — placement RELATIVE TO THE OUTLINE of an area, for both
 * renderers (2026-09-10): the local surface axis a prop aligns to, the pole
 * of inaccessibility a single centred prop stands at, the evenly spaced
 * stations along a polygon's rim, and the two samplers built on them
 * (`place: "edge"` / `place: "center"` of `ScatterEntry`).
 *
 * `scatter.ts` fills a BOX and filters by the ring; everything in here walks
 * the ring's EDGES. It imports the ring primitives from there — and nothing
 * else, never `three` — which is why it is the one scatter module the smoke
 * has to bundle rather than transpile (`smoke_scatter_math.mjs loadBundled`).
 * The alternative, these samplers inside `scatter.ts`, would have cost that
 * file its no-import contract and made the two modules import each other.
 *
 * Conventions (§ A9): yaw is a rotation about +y with the facing vector
 * (sin yaw, cos yaw), 0 = +z, π/2 = +x. An AXIS is a yaw too, and it is
 * oriented so that `axis + 90°` faces INTO the area. A stroke area has no
 * inside to face: its axis is the plain walking direction of its centre line
 * (`lineAxis`), exactly as the `along` rows already read it. With that,
 * `yaw_deg` 0 is "parallel to the rim", 90 "looking into the area", 270
 * "looking out", on every edge and from every side.
 */
import { footprintBlocks, pointInRing, scatterOccupyR, scatterPinnedVariant, scatterVariantIndex,
  scatterYaw, seededRandom, SCATTER_MAX_PER_ENTRY } from './scatter'
import type { ScatterFootprint, ScatterInstance, ScatterOccupancy,
  ScatterPoint2 } from './scatter'

const TAU = Math.PI * 2

/** How far the midpoint of an edge is pushed to ask "which side is inside?"
 *  — 0.1 mm, far below the centimetre the server stores and far above the
 *  float noise of a coordinate in a world some kilometres across. */
const AXIS_INSIDE_EPS_M = 1e-4

/** Two ring points closer than this are the same point, not an edge. */
const RING_EPS = 1e-9

/** Cells the pole search may ever open — a guard, not a budget: a precision of
 *  0.5 m on any authored shape is done in hundreds, and a ring that somehow
 *  keeps the queue alive answers its best so far instead of a frozen frame. */
const POLYLABEL_MAX_CELLS = 100000

/** An angle brought into [0, 2π) — a yaw, an axis, both are compared by
 *  the smokes and read as bearings by the renderers. */
function normAngle(a: number): number {
  return ((a % TAU) + TAU) % TAU
}

/** Distance from `(x, z)` to the segment A -> B, clamped to its ends — the
 *  arithmetic of `footprintDistance`, on ONE segment. */
function segmentDistance(x: number, z: number, ax: number, az: number,
                         bx: number, bz: number): number {
  const dx = bx - ax
  const dz = bz - az
  const len2 = dx * dx + dz * dz
  let t = len2 < 1e-18 ? 0 : ((x - ax) * dx + (z - az) * dz) / len2
  t = t < 0 ? 0 : (t > 1 ? 1 : t)
  const ex = x - (ax + t * dx)
  const ez = z - (az + t * dz)
  return Math.sqrt(ex * ex + ez * ez)
}

/**
 * The axis of the ring edge A -> B, oriented by the convention above:
 *
 *     d = (B − A)/|B − A|,  heading = atan2(dx, dz)
 *     n = facing of (heading + 90°) = (cos heading, −sin heading) = (dz, −dx)
 *     axis = heading            when M + n·ε lies in the ring  (M = midpoint)
 *          = heading + π        otherwise                      (i.e. −d)
 *
 * The inside test is the even-odd cast of `pointInRing`, so the answer does
 * not depend on the winding an author happened to draw the shape in.
 */
function edgeAxis(ring: readonly ScatterPoint2[], ax: number, az: number,
                  bx: number, bz: number): number {
  const dx = bx - ax
  const dz = bz - az
  const len = Math.hypot(dx, dz)
  if (!(len > 0)) return 0
  const heading = Math.atan2(dx, dz)
  const mx = (ax + bx) / 2
  const mz = (az + bz) / 2
  const nx = dz / len
  const nz = -dx / len
  const inside = pointInRing(mx + nx * AXIS_INSIDE_EPS_M,
    mz + nz * AXIS_INSIDE_EPS_M, ring)
  return normAngle(inside ? heading : heading + Math.PI)
}

/**
 * The AXIS of the ring edge nearest to `(x, z)` — what an `aligned` prop on a
 * painted polygon turns relative to (user decision 1, 2026-09-10: the nearest
 * edge per instance, not the longest edge of the shape).
 *
 * Nearest = least point-segment distance; a tie goes to the edge checked
 * FIRST (strict `<`) — and the loop opens with the CLOSING edge, from the
 * last point back to the first, then walks the ring in order (§ A9) — so a
 * prop standing exactly mid-way between two parallel edges reads one answer
 * on every renderer. Fewer than three points enclose
 * nothing and answer 0, the "angle alone" axis.
 */
export function ringEdgeAxis(ring: readonly ScatterPoint2[],
                             x: number, z: number): number {
  const n = ring?.length ?? 0
  if (n < 3) return 0
  let best = Infinity
  let bi = -1
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const d = segmentDistance(x, z, ring[j][0], ring[j][1], ring[i][0], ring[i][1])
    if (d < best) { best = d; bi = i }
  }
  if (bi < 0) return 0
  const j = bi === 0 ? n - 1 : bi - 1
  return edgeAxis(ring, ring[j][0], ring[j][1], ring[bi][0], ring[bi][1])
}

/**
 * The walking direction of the polyline segment nearest to `(x, z)` — the
 * axis of a STROKE area, whose decorated centre line (`strokeCentreLine`) is
 * what its props line up with. No inside test: a line has no inside, and the
 * `along` rows already read the same direction. Fewer than two points answer
 * 0. Ties go to the first segment, as in `ringEdgeAxis`.
 */
export function lineAxis(line: ReadonlyArray<readonly [number, number]>,
                         x: number, z: number): number {
  const n = line?.length ?? 0
  if (n < 2) return 0
  let best = Infinity
  let axis = 0
  for (let i = 1; i < n; i += 1) {
    const [ax, az] = line[i - 1]
    const [bx, bz] = line[i]
    const dx = bx - ax
    const dz = bz - az
    if (dx * dx + dz * dz < 1e-18) continue
    const d = segmentDistance(x, z, ax, az, bx, bz)
    if (d < best) { best = d; axis = normAngle(Math.atan2(dx, dz)) }
  }
  return axis
}

/**
 * THE AXIS OF AN AREA, as the function every sampler of that area is handed
 * (`axisAt`): a STROKE area aligns to its decorated centre line (`lineAxis`
 * over `strokeCentreLine`), a painted polygon to its own rim
 * (`ringEdgeAxis`). `line` is `null` on a polygon. Both renderers choose
 * through here, so neither can align a road's bushes to the ribbon's rim.
 */
export function areaAxis(line: ReadonlyArray<readonly [number, number]> | null,
                         ring: readonly ScatterPoint2[]
): (x: number, z: number) => number {
  return line
    ? (x, z) => lineAxis(line, x, z)
    : (x, z) => ringEdgeAxis(ring, x, z)
}

/** The answer of `polylabel`: the point and its distance to the ring. */
export interface PoleOfInaccessibility {
  x: number
  z: number
  /** metres to the nearest edge — the radius of the largest circle around
   *  the point that stays inside the ring */
  d: number
}

/** Signed distance to the ring: positive inside, negative outside, 0 on it. */
function signedRingDistance(ring: readonly ScatterPoint2[],
                            x: number, z: number): number {
  const n = ring.length
  let best = Infinity
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const d = segmentDistance(x, z, ring[j][0], ring[j][1], ring[i][0], ring[i][1])
    if (d < best) best = d
  }
  return pointInRing(x, z, ring) ? best : -best
}

/** One quadtree cell of the pole search. */
interface PoleCell {
  x: number
  z: number
  /** half the cell edge */
  h: number
  /** signed distance of the centre */
  d: number
  /** the farthest ANY point of the cell can be from the ring: d + h·√2 */
  max: number
}

function poleCell(ring: readonly ScatterPoint2[], x: number, z: number,
                  h: number): PoleCell {
  const d = signedRingDistance(ring, x, z)
  return { x, z, h, d, max: d + h * Math.SQRT2 }
}

/** A binary max-heap on `max` — the priority queue of the search, small
 *  enough to spell out rather than to depend on. */
function heapPush(heap: PoleCell[], cell: PoleCell): void {
  heap.push(cell)
  let i = heap.length - 1
  while (i > 0) {
    const parent = (i - 1) >> 1
    if (heap[parent].max >= heap[i].max) break
    const t = heap[parent]; heap[parent] = heap[i]; heap[i] = t
    i = parent
  }
}

function heapPop(heap: PoleCell[]): PoleCell | undefined {
  const top = heap[0]
  const last = heap.pop()
  if (heap.length === 0 || last === undefined) return top
  heap[0] = last
  let i = 0
  for (;;) {
    const l = i * 2 + 1
    const r = l + 1
    let m = i
    if (l < heap.length && heap[l].max > heap[m].max) m = l
    if (r < heap.length && heap[r].max > heap[m].max) m = r
    if (m === i) break
    const t = heap[m]; heap[m] = heap[i]; heap[i] = t
    i = m
  }
  return top
}

/**
 * The POLE OF INACCESSIBILITY of a ring — the point farthest from its edges,
 * where `place: "center"` puts its one instance (user decision 3,
 * 2026-09-10). The centroid will not do: for an L-shaped square it lies
 * 12 cm from the inner wall, and for a crescent outside the shape altogether.
 *
 * Mapbox's polylabel (2016), written out rather than depended on: the
 * bounding box is tiled with square cells, each scored by the signed
 * distance `d` of its centre and the bound `max = d + h·√2` no point in it
 * can exceed; a priority queue hands out the most promising cell, and a cell
 * is split into four only while `max − bestD > precision` — it could still
 * beat the best by more than the tolerance. The centroid cell seeds the best
 * (the bounding-box centre if that is better), and a cell replaces it only
 * with a strictly larger `d`, so a shape with one obvious answer — a
 * rectangle's midline — answers its centroid exactly. Distances are the
 * point-segment distance of `footprintDistance`, inside/outside the even-odd
 * cast of `pointInRing`.
 *
 * `precision` is in metres (default 0.5 — a prop, not a survey marker). A ring
 * of fewer than three points answers `{0, 0, 0}`; a ring with no extent (a
 * line) its bounding-box centre with `d` 0.
 */
export function polylabel(ring: readonly ScatterPoint2[],
                          precision: number = 0.5): PoleOfInaccessibility {
  const n = ring?.length ?? 0
  if (n < 3) return { x: 0, z: 0, d: 0 }
  let minX = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxZ = -Infinity
  for (const [x, z] of ring) {
    if (!Number.isFinite(x) || !Number.isFinite(z)) return { x: 0, z: 0, d: 0 }
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  const width = maxX - minX
  const height = maxZ - minZ
  const cellSize = Math.min(width, height)
  if (!(cellSize > 0)) return { x: minX + width / 2, z: minZ + height / 2, d: 0 }
  const tolerance = Number.isFinite(precision) && precision > 0 ? precision : 0.5
  const half = cellSize / 2

  // The centroid (shoelace), the bounding-box centre when the ring encloses
  // no signed area — the same two seeds Mapbox starts from.
  let area = 0
  let cx = 0
  let cz = 0
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const [xi, zi] = ring[i]
    const [xj, zj] = ring[j]
    const f = xi * zj - xj * zi
    area += f
    cx += (xi + xj) * f
    cz += (zi + zj) * f
  }
  let best = Math.abs(area) > 1e-12
    ? poleCell(ring, cx / (3 * area), cz / (3 * area), 0)
    : poleCell(ring, minX + width / 2, minZ + height / 2, 0)
  const boxCentre = poleCell(ring, minX + width / 2, minZ + height / 2, 0)
  if (boxCentre.d > best.d) best = boxCentre

  const heap: PoleCell[] = []
  for (let x = minX; x < maxX; x += cellSize) {
    for (let z = minZ; z < maxZ; z += cellSize) {
      heapPush(heap, poleCell(ring, x + half, z + half, half))
    }
  }
  let opened = heap.length
  while (heap.length > 0 && opened < POLYLABEL_MAX_CELLS) {
    const cell = heapPop(heap)
    if (!cell) break
    if (cell.d > best.d) best = cell
    if (cell.max - best.d <= tolerance) continue
    const h = cell.h / 2
    heapPush(heap, poleCell(ring, cell.x - h, cell.z - h, h))
    heapPush(heap, poleCell(ring, cell.x + h, cell.z - h, h))
    heapPush(heap, poleCell(ring, cell.x - h, cell.z + h, h))
    heapPush(heap, poleCell(ring, cell.x + h, cell.z + h, h))
    opened += 4
  }
  return { x: best.x, z: best.z, d: best.d }
}

/** What `ringStations` needs to know. */
export interface RingStationOptions {
  /** distance between two stations along the rim, metres (> 0) */
  spacingM: number
  /** how far the row stands INSIDE the rim, metres (>= 0); absent = 0 */
  offsetM?: number
  /** arc length of the first station; absent = half a spacing, and an
   *  authored value is clamped to the spacing (as `strokeStations` clamps) */
  startM?: number
  /** a guard, not a budget; defaults to `SCATTER_MAX_PER_ENTRY` */
  maxPoints?: number
}

/** One station of `ringStations`: where it stands, which way the rim runs
 *  there, and which station it is. */
export interface RingStation {
  x: number
  z: number
  /** the axis of the edge the station sits on (`edgeAxis` convention) */
  axis: number
  /** k — counting the stations a caller later rejects, so the variant a
   *  survivor hangs on does not move when a neighbour is subtracted */
  ordinal: number
}

/** One edge of the closed ring with its arc-length span `[start, end)`. */
interface RingEdge {
  ax: number
  az: number
  bx: number
  bz: number
  len: number
  start: number
  end: number
}

/** The ring as CLOSED edges (the last one back to the first point), junk and
 *  zero-length edges dropped — a repeated closing point adds no edge. */
function ringEdges(ring: readonly ScatterPoint2[]): RingEdge[] {
  const pts: ScatterPoint2[] = []
  for (const p of ring ?? []) {
    if (!p || p.length < 2) return []
    const [x, z] = p
    if (!Number.isFinite(x) || !Number.isFinite(z)) return []
    const prev = pts[pts.length - 1]
    if (prev && Math.abs(prev[0] - x) < RING_EPS && Math.abs(prev[1] - z) < RING_EPS) continue
    pts.push([x, z])
  }
  const first = pts[0]
  const last = pts[pts.length - 1]
  if (pts.length > 1 && Math.abs(first[0] - last[0]) < RING_EPS
    && Math.abs(first[1] - last[1]) < RING_EPS) pts.pop()
  if (pts.length < 3) return []
  const edges: RingEdge[] = []
  let cum = 0
  for (let i = 0; i < pts.length; i += 1) {
    const [ax, az] = pts[i]
    const [bx, bz] = pts[(i + 1) % pts.length]
    const len = Math.hypot(bx - ax, bz - az)
    if (!(len > RING_EPS)) continue
    edges.push({ ax, az, bx, bz, len, start: cum, end: cum + len })
    cum += len
  }
  return edges
}

/**
 * EVENLY SPACED STATIONS ALONG A POLYGON'S RIM, pushed inward — the geometry
 * of `place: "edge"` (user decision 2, 2026-09-10: a row along the whole rim,
 * `min_spacing_m` apart, `offset_m` inside).
 *
 * Arc length is accumulated over the CLOSED ring; station k sits at
 *
 *     s_k = start + k · spacing,   s_k < L        (start = spacing/2 unless authored)
 *
 * on the edge whose half-open span [cum_i, cum_i+1) holds s_k, and it is
 * pushed along `n_in`, the facing vector of `axis + 90°` — INTO the area by
 * the axis convention — by `offsetM`:
 *
 *     P(s_k) + n_in · offsetM,   axis = the edge's `edgeAxis`
 *
 * `s = L` is `s = 0` again and is not a station. THE FUNCTION DROPS NOTHING:
 * a pushed point that lands outside the ring (a station on a sharp corner, an
 * offset wider than the shape) is handed back like any other, ordinal
 * included, and the caller subtracts it (`scatterEdgeInstances`) — geometry
 * here, verdicts there, exactly the split the box sampler has.
 */
export function ringStations(ring: readonly ScatterPoint2[],
                             opts: RingStationOptions): RingStation[] {
  const spacing = Number(opts?.spacingM)
  if (!Number.isFinite(spacing) || spacing <= 0) return []
  const offset = opts?.offsetM === undefined ? 0 : Number(opts.offsetM)
  if (!Number.isFinite(offset) || offset < 0) return []
  const edges = ringEdges(ring)
  if (edges.length < 3) return []
  const total = edges[edges.length - 1].end
  const start = (typeof opts.startM === 'number' && Number.isFinite(opts.startM)
    && opts.startM >= 0) ? Math.min(opts.startM, spacing) : spacing / 2
  const max = opts.maxPoints ?? SCATTER_MAX_PER_ENTRY
  const axes: number[] = new Array<number>(edges.length).fill(NaN)
  const out: RingStation[] = []
  let e = 0
  for (let k = 0; ; k += 1) {
    const s = start + k * spacing
    if (!(s < total - RING_EPS)) break
    if (out.length >= max) break
    while (e < edges.length - 1 && s >= edges[e].end) e += 1
    const edge = edges[e]
    let t = (s - edge.start) / edge.len
    t = t < 0 ? 0 : (t > 1 ? 1 : t)
    const px = edge.ax + t * (edge.bx - edge.ax)
    const pz = edge.az + t * (edge.bz - edge.az)
    // The inside test of an edge costs a walk over the ring, so every edge
    // is asked once, when its first station arrives.
    if (Number.isNaN(axes[e])) axes[e] = edgeAxis(ring, edge.ax, edge.az, edge.bx, edge.bz)
    const axis = axes[e]
    const inward = axis + Math.PI / 2
    out.push({
      x: px + Math.sin(inward) * offset,
      z: pz + Math.cos(inward) * offset,
      axis,
      ordinal: k,
    })
  }
  return out
}

/** What the two outline samplers share with the box sampler: the verdicts
 *  and the mix — see `ScatterSampleOptions` for each field. */
interface OutlineSampleOptions {
  /** `scatterSeed(area.id, index, epoch)` — the stream of the yaw draw and
   *  the offset of the variant formula */
  seed: string
  /** the entry's turn mode and angle — `scatterYaw`; absent = random */
  yawMode?: string
  yawDeg?: number
  footprints?: readonly ScatterFootprint[]
  clearM?: number
  occluders?: readonly (readonly ScatterPoint2[])[]
  occupied?: ScatterOccupancy
  occupyR?: number
  /** the row's identity in the occupancy — see `ScatterSampleOptions`;
   *  absent = `seed` */
  occupyTag?: string
  variantCount?: number
  /** the variant the row pins, clamped to `[0, n − 1]`
   *  (`scatterPinnedVariant`); absent = the variant formula — over the
   *  station's ordinal on the rim, over ordinal 0 at the centre */
  variant?: number
  /** the random stream, for the smoke check only */
  rng?: () => number
}

/** What `scatterEdgeInstances` needs to know. */
export interface ScatterEdgeOptions extends OutlineSampleOptions, RingStationOptions {}

/** What `scatterCenterInstance` needs to know. */
export interface ScatterCenterOptions extends OutlineSampleOptions {
  /** the local axis at a point, when the area's axis is not its own rim's —
   *  a stroke area hands in `lineAxis` over its centre line; absent =
   *  `ringEdgeAxis` of `ring` */
  axisAt?: (x: number, z: number) => number
}

/** Covered by an area painted OVER this one? */
function hiddenBy(occluders: readonly (readonly ScatterPoint2[])[],
                  x: number, z: number): boolean {
  for (const occ of occluders) {
    if ((occ?.length ?? 0) >= 3 && pointInRing(x, z, occ)) return true
  }
  return false
}

/** Kept out by a placed location or prop box? */
function coveredBy(footprints: readonly ScatterFootprint[], x: number, z: number,
                   clearM: number | undefined): boolean {
  for (const fp of footprints) {
    if (footprintBlocks(fp, x, z, clearM)) return true
  }
  return false
}

/**
 * THE ROW ALONG THE RIM — `place: "edge"`: the stations of `ringStations`,
 * judged and turned.
 *
 * ONE DRAW PER STATION, ALWAYS, from the row's seeded stream (`seed`), taken
 * before any verdict — the rule of the box sampler (`scatterInstances`) for
 * the same reason: a station a building covers must SUBTRACT and leave every
 * other station where it stood and how it turned. The yaw is
 *
 *     aligned    axis of the station's edge + yaw_deg      (`scatterYaw`)
 *     random     r · 2π
 *
 * Verdicts, in order, on the PUSHED point: inside the ring, then the
 * occluders, the footprints with `clearM`, and what earlier rows planted
 * (`occupied`, judged by `occupyR`); a survivor is filed there in turn. The
 * ring verdict tests the point NUDGED INWARD by `AXIS_INSIDE_EPS_M` along
 * `n_in`: at offset 0 a station lies ON the rim, and the even-odd cast counts
 * a boundary point as inside on some edges and outside on others — half a
 * row would vanish for no visible reason (review finding, 2026-09-10). A
 * station is on the rim by construction, so "inside" means its inward side;
 * a station pushed clear out of the shape (an offset wider than a narrow
 * arm, a sharp corner at a large offset) still lands outside and is
 * subtracted, ordinal kept. Variant: the pinned `variant` clamped to the
 * count when the row names one (`scatterPinnedVariant`), else
 * `(FNV-1a(seed) + ordinal) mod n`, the shared formula over the station's
 * ordinal, so the survivors of a partly covered rim keep the variants they
 * had. The camera window is the caller's filter, as it is for the `along`
 * rows: the row is computed ONCE for the whole rim.
 */
export function scatterEdgeInstances(ring: readonly ScatterPoint2[],
                                     opts: ScatterEdgeOptions): ScatterInstance[] {
  const stations = ringStations(ring, opts)
  if (stations.length === 0) return []
  const rnd = opts.rng ?? seededRandom(opts.seed)
  const footprints = opts.footprints ?? []
  const occluders = opts.occluders ?? []
  const occupied = opts.occupied
  const occupyR = scatterOccupyR(opts.occupyR, opts.clearM)
  const occupyTag = opts.occupyTag ?? opts.seed
  const variants = Math.floor(Number(opts.variantCount))
  const mixing = Number.isFinite(variants) && variants > 1
  const pinned = mixing ? scatterPinnedVariant(opts.variant, variants) : -1
  const out: ScatterInstance[] = []
  for (const station of stations) {
    const turn = rnd()
    const { x, z } = station
    const inward = station.axis + Math.PI / 2
    if (!pointInRing(x + Math.sin(inward) * AXIS_INSIDE_EPS_M,
      z + Math.cos(inward) * AXIS_INSIDE_EPS_M, ring)) continue
    if (hiddenBy(occluders, x, z)) continue
    if (coveredBy(footprints, x, z, opts.clearM)) continue
    if (occupied && occupied.blocks(x, z, occupyR, occupyTag)) continue
    if (occupied) occupied.add(x, z, occupyR, occupyTag)
    const yaw = scatterYaw(turn, opts.yawMode, opts.yawDeg, station.axis)
    out.push(mixing
      ? { x, z, yaw, variant: pinned >= 0 ? pinned : scatterVariantIndex(opts.seed, station.ordinal, variants) }
      : { x, z, yaw })
  }
  return out
}

/**
 * THE ONE INSTANCE AT THE CENTRE — `place: "center"`: the pole of
 * inaccessibility (`polylabel`), judged and turned.
 *
 * One draw from the row's stream (so a row switched between modes keeps its
 * random turn), the yaw under `aligned` relative to `axisAt(x, z)` when the
 * caller hands an axis in (a stroke area's centre line) and to
 * `ringEdgeAxis` of the ring otherwise — the nearest edge of the pole, with a
 * tie going to the closing edge. Verdicts: the occluders, the footprints with
 * `clearM`, what OTHER rows planted; the survivor is filed under the row's
 * tag. The variant is
 * the pinned `variant` clamped to the count when the row names one, else the
 * formula with ordinal 0. A ring that encloses nothing (fewer than three
 * points, or a pole with no distance to the rim) centres nothing.
 */
export function scatterCenterInstance(ring: readonly ScatterPoint2[],
                                      opts: ScatterCenterOptions): ScatterInstance[] {
  if ((ring?.length ?? 0) < 3) return []
  const pole = polylabel(ring)
  if (!(pole.d > 0)) return []
  const rnd = opts.rng ?? seededRandom(opts.seed)
  const turn = rnd()
  const { x, z } = pole
  if (hiddenBy(opts.occluders ?? [], x, z)) return []
  if (coveredBy(opts.footprints ?? [], x, z, opts.clearM)) return []
  const occupyR = scatterOccupyR(opts.occupyR, opts.clearM)
  const occupyTag = opts.occupyTag ?? opts.seed
  if (opts.occupied && opts.occupied.blocks(x, z, occupyR, occupyTag)) return []
  if (opts.occupied) opts.occupied.add(x, z, occupyR, occupyTag)
  const axis = opts.yawMode === 'aligned'
    ? (opts.axisAt ? opts.axisAt(x, z) : ringEdgeAxis(ring, x, z))
    : 0
  const yaw = scatterYaw(turn, opts.yawMode, opts.yawDeg, axis)
  const variants = Math.floor(Number(opts.variantCount))
  if (!Number.isFinite(variants) || variants <= 1) return [{ x, z, yaw }]
  const pinned = scatterPinnedVariant(opts.variant, variants)
  return [{
    x, z, yaw,
    variant: pinned >= 0 ? pinned : scatterVariantIndex(opts.seed, 0, variants),
  }]
}
