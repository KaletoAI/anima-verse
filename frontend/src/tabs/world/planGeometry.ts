/**
 * planGeometry — the pure geometry of the floor plan (no React, no DOM):
 * rectangle rooms, their edges, adjacency and the opening vocabulary that
 * sits on those edges. Extracted from RoomLayoutEditor so the editor, the
 * preview and anything else that reasons about a plan share ONE set of
 * helpers.
 *
 * Coordinate frame: everything is fractions of the plan's reference square
 * (x/y/w/d of a room layout), y pointing DOWN like the screen. Real metres
 * come from the plan width the caller passes in, so the thresholds below can
 * be stated in metres.
 */

export const MIN_FRAC = 0.05

// ── Openings layer (B3) ──
// Openings sit on a room's hull edges. The canonical edge vocabulary is the
// POLYGON EDGE INDEX over `outlineOf(lay)`; the legacy letters 'N'|'S'|'E'|'W'
// map onto the implicit unit square via `normalizeOpeningEdge` at READ time —
// the editor only ever writes indices. New openings default to a standard door.
export type EdgeLetter = 'N' | 'S' | 'E' | 'W'
export const OPENING_DEFAULT = { type: 'door' as const, width_m: 1.0, height_m: 2.1, sill_m: 0 }
export const OPENING_COLOR: Record<string, string> = {
  door: '#e0a356', window: '#79c0ff', passage: '#8b949e',
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
export const r4 = (v: number) => Math.round(v * 10000) / 10000

// ── Polygon hulls (plan-room-props.md) ──
// A room's hull is a polygon in ROOM-local fractions: the drawn `outline`
// (bbox-local, spanning [0,1]², clockwise in screen coordinates — the server
// sanitizer guarantees both), or the implicit unit square of a plain
// rectangle. Edges are directed a→b and auto-close to the first point;
// with clockwise winding the interior lies to the RIGHT of each edge.

export type Pt = [number, number]

/** The implicit unit square — edge indices 0=N, 1=E, 2=S, 3=W. */
export const rectToOutline = (): Pt[] => [[0, 0], [1, 0], [1, 1], [0, 1]]

/** A layout's hull polygon (room-local fractions). */
export const outlineOf = (lay: { outline?: Pt[] }): Pt[] =>
  (lay.outline && lay.outline.length >= 3 ? lay.outline : rectToOutline())

/** Directed edge i of an outline: a → b (auto-closing). */
export const edgeSegment = (outline: Pt[], i: number): { a: Pt; b: Pt } => ({
  a: outline[i], b: outline[(i + 1) % outline.length],
})

/** Point on edge `i` at fraction `at` along its direction (room-local). */
export const edgePointOnEdge = (outline: Pt[], i: number, at: number): { x: number; y: number } => {
  const { a, b } = edgeSegment(outline, i)
  return { x: a[0] + (b[0] - a[0]) * at, y: a[1] + (b[1] - a[1]) * at }
}

/** Nearest polygon edge + fraction along it for a room-local point. */
export function nearestPolygonEdge(outline: Pt[], p: Pt): { edge: number; at: number } {
  let best = { edge: 0, at: 0.5 }
  let bestD = Infinity
  for (let i = 0; i < outline.length; i++) {
    const { a, b } = edgeSegment(outline, i)
    const dx = b[0] - a[0]
    const dy = b[1] - a[1]
    const len2 = dx * dx + dy * dy
    const at = len2 > 0 ? clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2, 0, 1) : 0.5
    const qx = a[0] + dx * at
    const qy = a[1] + dy * at
    const dist = (p[0] - qx) ** 2 + (p[1] - qy) ** 2
    if (dist < bestD) {
      bestD = dist
      best = { edge: i, at: r4(at) }
    }
  }
  return best
}

/** ONE reading convention for both edge vocabularies: letters map onto the
 *  unit square's directed clockwise edges (0=N TL→TR, 1=E TR→BR, 2=S BR→BL,
 *  3=W BL→TL). Letter `at` runs left→right (N/S) / top→bottom (E/W), so S
 *  and W flip against their clockwise edge direction. */
export const normalizeOpeningEdge = (
  op: { edge: EdgeLetter | number; at: number }): { edge: number; at: number } => {
  if (typeof op.edge !== 'string') return { edge: op.edge, at: op.at }
  switch (op.edge) {
    case 'N': return { edge: 0, at: op.at }
    case 'E': return { edge: 1, at: op.at }
    case 'S': return { edge: 2, at: r4(1 - op.at) }
    default: return { edge: 3, at: r4(1 - op.at) }
  }
}

/** Hull polygon mapped from room-local fractions to plan fractions. */
export const absOutline = (
  lay: { x: number; y: number; w: number; d: number; outline?: Pt[] }): Pt[] =>
  outlineOf(lay).map(([u, v]) => [lay.x + u * lay.w, lay.y + v * lay.d] as Pt)

/** Edge + position of an opening after rotating the room 90° clockwise
 *  ((x,y) -> (1-y,x)), so openings turn with the room like exit/markers. */
export const rotateOpeningCW = (edge: EdgeLetter, at: number): { edge: EdgeLetter; at: number } =>
  edge === 'N' ? { edge: 'E', at }
    : edge === 'E' ? { edge: 'S', at: r4(1 - at) }
      : edge === 'S' ? { edge: 'W', at }
        : { edge: 'N', at: r4(1 - at) }

// ── Adjacency geometry (B4) — pure functions over room hulls ──
// All coordinates are fractions of the 8 m reference square; real metres come
// from planW (the same plan_width_m the editor derives), so the thresholds are
// stated in metres. Collinearity tolerance ~0.15 m, a shared segment counts
// from 0.8 m, a window is suggested on exterior edges from 2.5 m.
export const SHARE_TOL_M = 0.15
export const MIN_SHARE_M = 0.8
export const MIN_WINDOW_EDGE_M = 2.5

export interface PolyRoom {
  id: string; x: number; y: number; w: number; d: number; outline?: Pt[]
}
export interface SharedEdge { edge: number; at: number; neighborId: string }

/** Shared edges of room A with the given others (same level only): edges of
 *  A's hull that run ANTIPARALLEL to a neighbour's edge (two rooms meeting at
 *  a wall face each other), within ~0.15 m sideways and overlapping ≥ 0.8 m.
 *  `edge` is A's edge index, `at` the centre of the overlap along that
 *  directed edge (fraction of the edge). */
export function sharedEdges(a: PolyRoom, others: PolyRoom[], planW: number): SharedEdge[] {
  const tol = planW > 0 ? SHARE_TOL_M / planW : 0.02
  const minOv = planW > 0 ? MIN_SHARE_M / planW : 0.1
  const oa = absOutline(a)
  const out: SharedEdge[] = []
  for (let i = 0; i < oa.length; i++) {
    const seg = edgeSegment(oa, i)
    const dx = seg.b[0] - seg.a[0]
    const dy = seg.b[1] - seg.a[1]
    const len = Math.hypot(dx, dy)
    if (len < 1e-6) continue
    const ux = dx / len
    const uy = dy / len
    for (const b of others) {
      const ob = absOutline(b)
      for (let j = 0; j < ob.length; j++) {
        const other = edgeSegment(ob, j)
        const ex = other.b[0] - other.a[0]
        const ey = other.b[1] - other.a[1]
        const elen = Math.hypot(ex, ey)
        if (elen < 1e-6) continue
        const vx = ex / elen
        const vy = ey / elen
        // Antiparallel within ~1° — parallel same-direction edges cannot face
        // each other across a wall (clockwise winding on both hulls).
        if (Math.abs(ux * vy - uy * vx) > 0.02 || ux * vx + uy * vy > -0.98) continue
        // Sideways offset of the neighbour edge from A's edge line.
        const off = Math.abs((other.a[0] - seg.a[0]) * uy - (other.a[1] - seg.a[1]) * ux)
        if (off > tol) continue
        // Overlap measured along A's edge direction.
        const t0 = (other.a[0] - seg.a[0]) * ux + (other.a[1] - seg.a[1]) * uy
        const t1 = (other.b[0] - seg.a[0]) * ux + (other.b[1] - seg.a[1]) * uy
        const s = Math.max(0, Math.min(t0, t1))
        const e = Math.min(len, Math.max(t0, t1))
        if (e - s < minOv) continue
        out.push({ edge: i, at: r4(clamp((s + e) / 2 / len, 0, 1)), neighborId: b.id })
      }
    }
  }
  return out
}

/** Edge indices of room A that share no segment with any neighbour
 *  (exterior walls). */
export function exteriorEdges(a: PolyRoom, others: PolyRoom[], planW: number): number[] {
  const shared = new Set(sharedEdges(a, others, planW).map((s) => s.edge))
  const n = outlineOf(a).length
  return Array.from({ length: n }, (_, i) => i).filter((i) => !shared.has(i))
}

// ── Snapping engine (drawing aid) ──
// Always on while drawing; the caller passes alt=true (Shift held) for
// free-hand. Priorities: close the polygon on its first vertex > snap to an
// existing vertex (closing small gaps beats everything) > the 45°-angle ray
// intersected with a target edge (right angles that also land on a wall) >
// plain edge projection > plain angle ray > free. All coordinates are plan
// fractions; tolerances are passed in plan fractions too (the caller derives
// them from pixels and metres).
export const SNAP_TOL_PX = 10
export const CLOSE_TOL_PX = 14

export interface SnapTargets { points: Pt[]; segments: Array<{ a: Pt; b: Pt }> }

/** Snap targets for a drawing session: the hulls of the placed rooms on the
 *  level, optionally the building outline (NOT when it is the thing being
 *  redrawn), plus loose extra points (the draft's own vertices). */
export function buildSnapTargets(hulls: PolyRoom[], opts?: {
  buildingOutline?: Pt[]; extraPoints?: Pt[] }): SnapTargets {
  const points: Pt[] = []
  const segments: Array<{ a: Pt; b: Pt }> = []
  const addPoly = (pts: Pt[]) => {
    for (let i = 0; i < pts.length; i++) {
      points.push(pts[i])
      segments.push({ a: pts[i], b: pts[(i + 1) % pts.length] })
    }
  }
  for (const h of hulls) addPoly(absOutline(h))
  const bo = opts?.buildingOutline
  if (bo && bo.length >= 3) addPoly(bo)
  for (const p of opts?.extraPoints || []) points.push(p)
  return { points, segments }
}

export interface SnapResult {
  p: Pt
  kind: 'free' | 'vertex' | 'edge' | 'angle' | 'angle+edge' | 'close'
  /** Constraint ray to visualize for the angle kinds. */
  guide?: { a: Pt; b: Pt }
  /** Target segment being snapped onto (edge kinds). */
  seg?: { a: Pt; b: Pt }
}

const _dist2 = (a: Pt, b: Pt) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
const _r4p = (p: Pt): Pt => [r4(p[0]), r4(p[1])]

export function snapDrawPoint(raw: Pt, opts: {
  prev?: Pt; prevDir?: Pt; first?: Pt; draftLen?: number
  targets: SnapTargets; tol: number; closeTol: number; alt?: boolean
}): SnapResult {
  const p: Pt = [clamp(raw[0], 0, 1), clamp(raw[1], 0, 1)]
  if (opts.alt) return { p: _r4p(p), kind: 'free' }
  const { targets, tol, closeTol } = opts

  // 1) Close the polygon on its first vertex.
  if (opts.first && (opts.draftLen || 0) >= 3
      && _dist2(p, opts.first) <= closeTol * closeTol)
    return { p: opts.first, kind: 'close' }

  // 2) Existing vertices — never the previous point itself (zero segments).
  let bestV: Pt | null = null
  let bestVD = tol * tol
  for (const v of targets.points) {
    if (opts.prev && _dist2(v, opts.prev) < 1e-12) continue
    const d = _dist2(p, v)
    if (d <= bestVD) {
      bestVD = d
      bestV = v
    }
  }
  if (bestV) return { p: _r4p(bestV), kind: 'vertex' }

  // The angle constraint: 45° raster relative to the previous segment's
  // direction (first segment: the plan's X axis).
  let dir: Pt | null = null
  if (opts.prev) {
    const ref = opts.prevDir && (opts.prevDir[0] || opts.prevDir[1])
      ? Math.atan2(opts.prevDir[1], opts.prevDir[0]) : 0
    const rawA = Math.atan2(p[1] - opts.prev[1], p[0] - opts.prev[0])
    const snapA = ref + Math.round((rawA - ref) / (Math.PI / 4)) * (Math.PI / 4)
    dir = [Math.cos(snapA), Math.sin(snapA)]
  }

  // 3) Constrained ray ∩ target edge — right angles that also close gaps.
  if (opts.prev && dir) {
    let bestX: { p: Pt; seg: { a: Pt; b: Pt } } | null = null
    let bestXD = tol * tol
    for (const s of targets.segments) {
      const ex = s.b[0] - s.a[0]
      const ey = s.b[1] - s.a[1]
      const denom = dir[0] * ey - dir[1] * ex
      if (Math.abs(denom) < 1e-9) continue
      const qx = s.a[0] - opts.prev[0]
      const qy = s.a[1] - opts.prev[1]
      const t = (qx * ey - qy * ex) / denom
      const u = (qx * dir[1] - qy * dir[0]) / denom
      if (t <= 0 || u < -0.02 || u > 1.02) continue
      const x: Pt = [opts.prev[0] + t * dir[0], opts.prev[1] + t * dir[1]]
      const d = _dist2(p, x)
      if (d <= bestXD) {
        bestXD = d
        bestX = { p: x, seg: s }
      }
    }
    if (bestX)
      return { p: _r4p(bestX.p), kind: 'angle+edge', seg: bestX.seg,
        guide: { a: opts.prev, b: bestX.p } }
  }

  // 4) Plain edge projection of the raw point (gap closing without angle).
  let bestE: { p: Pt; seg: { a: Pt; b: Pt } } | null = null
  let bestED = tol * tol
  for (const s of targets.segments) {
    const ex = s.b[0] - s.a[0]
    const ey = s.b[1] - s.a[1]
    const len2 = ex * ex + ey * ey
    if (len2 < 1e-12) continue
    const u = clamp(((p[0] - s.a[0]) * ex + (p[1] - s.a[1]) * ey) / len2, 0, 1)
    const x: Pt = [s.a[0] + ex * u, s.a[1] + ey * u]
    const d = _dist2(p, x)
    if (d <= bestED) {
      bestED = d
      bestE = { p: x, seg: s }
    }
  }
  if (bestE) return { p: _r4p(bestE.p), kind: 'edge', seg: bestE.seg }

  // 5) Plain angle projection onto the constrained ray.
  if (opts.prev && dir) {
    const dot = (p[0] - opts.prev[0]) * dir[0] + (p[1] - opts.prev[1]) * dir[1]
    const x: Pt = [clamp(opts.prev[0] + dot * dir[0], 0, 1),
                   clamp(opts.prev[1] + dot * dir[1], 0, 1)]
    return { p: _r4p(x), kind: 'angle', guide: { a: opts.prev, b: x } }
  }

  return { p: _r4p(p), kind: 'free' }
}

/** Smart-guide offset for MOVING a hull (Shift = free-hand, handled by the
 *  caller): aligns any vertex coordinate of the moved hull with any target
 *  vertex coordinate within `tol` — x and y snap independently, so a corner
 *  far away on the other axis still provides its guide line (typical
 *  gap-closing between rooms). Returns the [dx, dy] to ADD to the candidate
 *  position; 0 per axis when nothing is in range. */
export function snapMoveOffset(hull: Pt[], targets: SnapTargets, tol: number): Pt {
  let dx = 0
  let ax = tol
  let dy = 0
  let ay = tol
  for (const v of hull) {
    for (const p of targets.points) {
      const ddx = p[0] - v[0]
      if (Math.abs(ddx) <= ax) {
        ax = Math.abs(ddx)
        dx = ddx
      }
      const ddy = p[1] - v[1]
      if (Math.abs(ddy) <= ay) {
        ay = Math.abs(ddy)
        dy = ddy
      }
    }
  }
  return [dx, dy]
}
