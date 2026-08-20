/**
 * planGeometry — the pure geometry of the floor plan (no React, no DOM):
 * rectangle rooms, their edges, adjacency and the opening vocabulary that
 * sits on those edges. Extracted from RoomLayoutEditor so the editor, the
 * preview and anything else that reasons about a plan share ONE set of
 * helpers.
 *
 * COORDINATE FRAME — METRES (contract v6 Nr. 2, "the metric wave"). The
 * `[0,1]²` fraction domain is deleted, here as on the server:
 *
 *   * a room's `x`/`y` is its MIN CORNER in LOCATION-LOCAL metres (origin =
 *     the anchor pin, axes as § A1.1 — the frame `map3d.boundary` lives in),
 *     so NEGATIVE VALUES ARE ORDINARY and nothing is clamped to a square;
 *   * `w`/`d` are metres;
 *   * a room's `outline` points, its curve control points, `markers[].at`,
 *     `props[].at` and `model_at` are metres relative to that min corner,
 *     i.e. they span 0…w / 0…d;
 *   * only an OPENING's `at` stays a fraction of its edge — a ratio along an
 *     edge is not a size in the world.
 *
 * y points DOWN like the screen (it is the local z of § A1.1), so a hull that
 * winds clockwise on screen has a positive shoelace sum and its interior lies
 * to the RIGHT of every directed edge.
 *
 * `layout.rotation` turns the WHOLE room about its rect centre on the way
 * from the room's frame into the location's (contract v6 addendum) — see
 * `roomToLocal` / `localToRoom` below. Everything STORED stays in the room's
 * straight frame; the turn is applied when a room-local metre is placed.
 */

/** Smallest room a drawing may commit, in metres — below this a hull is a
 *  slip of the hand, not a room. */
export const MIN_ROOM_M = 0.2

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
/** Rounding for a RATIO (an opening's `at`, a yaw fraction) — 4 decimals. */
export const r4 = (v: number) => Math.round(v * 10000) / 10000
/** Rounding for a LENGTH IN METRES: the centimetre, the same resolution the
 *  server stores every plan coordinate at (`world_ops._metre`). Storing more
 *  digits than the sanitizer keeps only makes the editor and the saved world
 *  disagree in the last place. */
export const rM = (v: number) => Math.round(v * 100) / 100
/** ±500 m — the server's plan clamp (`world_ops._PLAN_MAX_M`). The editor
 *  clamps to the SAME window, so nothing a user draws is silently dropped on
 *  save; inside it, negative coordinates are perfectly normal. */
export const PLAN_MAX_M = 500

// ── The drawing viewport (v6 metric wave) ──
// The plan canvas is SQUARE and shows a square window of the location's local
// metre frame: `size` metres wide, min corner (`x0`, `z0`). It is derived from
// the boundary's bounding box plus a margin — so the whole drawn plot is
// always inside the canvas — and it is the ONLY place a metre becomes a
// fraction of the canvas. Nothing is stored in this frame; it is view state.
export interface PlanView { x0: number; z0: number; size: number }

/** Canvas fraction (0…1 across the canvas) of a local-metre coordinate. */
export const viewFx = (v: PlanView, x: number) => (x - v.x0) / v.size
export const viewFz = (v: PlanView, z: number) => (z - v.z0) / v.size
/** Local metres of a canvas fraction — the inverse, used by every handler. */
export const viewMx = (v: PlanView, fx: number) => v.x0 + fx * v.size
export const viewMz = (v: PlanView, fz: number) => v.z0 + fz * v.size

/** The square viewport around a set of points: their bounding box, widened by
 *  `margin` on every side and then squared on the LARGER axis so the canvas
 *  (which is square) never distorts a metre. `fallback` is the edge used when
 *  there is nothing to frame at all — it is NOT a minimum size, or a small
 *  plot would be shown swimming in empty ground it does not own. */
export function viewportFor(points: Pt[], margin: number,
                            fallback: number): PlanView {
  if (!points.length) {
    return { x0: -fallback / 2, z0: -fallback / 2, size: fallback }
  }
  let minX = Infinity
  let maxX = -Infinity
  let minZ = Infinity
  let maxZ = -Infinity
  for (const [x, z] of points) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  // A degenerate box (one point, or a line) would give a zero-size window and
  // every fraction would divide by it — the margin is what saves it, so the
  // floor here only guards a caller that passes none.
  const edge = Math.max(maxX - minX, maxZ - minZ) + 2 * margin || 1
  return { x0: (minX + maxX) / 2 - edge / 2, z0: (minZ + maxZ) / 2 - edge / 2,
           size: edge }
}

/**
 * THE PLAN WINDOW, SAID IN THE MAP CANVAS' WORDS.
 *
 * The floor plan and the world map are two canvases over the same kind of
 * metre frame, and they state a viewport differently: the plan carries the min
 * corner plus an edge (`PlanView`), the map carries the centre plus a zoom
 * (`mapMath.View`). The ONE gesture that is mounted on both — `PolygonHandles`
 * on the location boundary — reads the map's form, so this is the translation,
 * and it is the only place the two vocabularies meet.
 *
 * The canvas is SQUARE (`aspectRatio: 1 / 1`), so one measured edge is both
 * width and height, and the result is exact rather than approximate:
 *
 *   worldToScreen(x) = w/2 + (x − cx)·pxPerM
 *                    = px/2 + (x − x0 − size/2)·(px/size)
 *                    = px·(x − x0)/size
 *                    = viewFx(v, x)·px
 *
 * i.e. a handle lands on the very pixel the plan's own `fx`/`fz` conversion
 * puts a metre on — which is what stops the boundary handles from sitting
 * anywhere but on the boundary. `scripts/smoke_plan_boundary_edit.mjs` runs
 * that identity on hand-derived numbers.
 *
 * A zero or negative edge would divide every conversion by nothing; both
 * inputs fall back to 1, which draws a useless but finite frame instead of
 * NaN handles.
 */
export interface PlanMapView {
  view: { cx: number; cz: number; pxPerM: number }
  /** Measured canvas size in CSS pixels — square, so w === h. */
  w: number
  h: number
}

export function planMapView(v: PlanView, canvasPx: number): PlanMapView {
  const size = v.size > 0 ? v.size : 1
  const px = canvasPx > 0 ? canvasPx : 1
  return {
    view: { cx: v.x0 + size / 2, cz: v.z0 + size / 2, pxPerM: px / size },
    w: px,
    h: px,
  }
}

/** Snap a length to the drawing raster (0 = off). Used for every drawn point
 *  and every dragged rectangle, so a plan comes out on whole half-metres
 *  unless the author says otherwise (Shift). */
export const snapToGrid = (v: number, step: number) =>
  (step > 0 ? Math.round(v / step) * step : v)

// ── Reference sizes (scale bar, metre grid) ──
/** Metre values a scale bar or a grid may use — no 3.7 m steps. */
const NICE_M = [0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500]

/** Largest nice value that still fits into `maxM`. */
export function niceDown(maxM: number): number {
  for (let i = NICE_M.length - 1; i >= 0; i--) {
    if (NICE_M[i] <= maxM) return NICE_M[i]
  }
  return NICE_M[0]
}

/** Smallest nice value that is at least `minM`. */
export function niceUp(minM: number): number {
  for (const v of NICE_M) if (v >= minM) return v
  return NICE_M[NICE_M.length - 1]
}

/** Metres for a label: coarse enough to read, fine enough to be true. */
export function fmtM(m: number): string {
  if (m >= 10) return m.toFixed(0)
  if (m >= 1) return m.toFixed(1)
  return m.toFixed(2)
}

// ── Polygon hulls (plan-room-props.md) ──
// A room's hull is a polygon in ROOM-local METRES: the drawn `outline`
// (relative to the room's own min corner, spanning 0…w / 0…d, clockwise in
// screen coordinates — the server sanitizer guarantees both), or the implicit
// rectangle of a plain room. Edges are directed a→b and auto-close to the
// first point; with clockwise winding the interior lies to the RIGHT of each
// edge.

export type Pt = [number, number]

/** The implicit room rectangle in room-local metres — edge indices
 *  0=N, 1=E, 2=S, 3=W. */
export const rectToOutline = (w: number, d: number): Pt[] =>
  [[0, 0], [w, 0], [w, d], [0, d]]

/** A layout's hull polygon (room-local metres). */
export const outlineOf = (lay: { w: number; d: number; outline?: Pt[] }): Pt[] =>
  (lay.outline && lay.outline.length >= 3 ? lay.outline : rectToOutline(lay.w, lay.d))

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
 *  rectangle's directed clockwise edges (0=N TL→TR, 1=E TR→BR, 2=S BR→BL,
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

// ── The room's own turn (contract v6 addendum, 2026-08-20) ──
// `layout.rotation` turns the WHOLE room about its rect centre — hull, walls,
// openings, markers, props and the 3D model alike. Storage stays in the
// room's own STRAIGHT frame: you draw straight, then turn. This is the
// editor's mirror of `room_recipe.room_transform` — change both or neither.

/** A room layout as far as the geometry cares. */
export interface RoomFrame {
  x: number; y: number; w: number; d: number
  outline?: Pt[]; rotation?: number
}

/** Rotate `p` about `c` by `deg`, in the ONE sense of § A1.1
 *  (`world_geometry.local_to_world`, three.js `rotation.y = +rad(θ)`):
 *      x' = cx + lx·cos θ + lz·sin θ
 *      z' = cz − lx·sin θ + lz·cos θ
 *  Positive degrees therefore turn COUNTER-CLOCKWISE on the y-down plan,
 *  which is why every CSS/SVG rendering of an angle here uses `-deg`. */
export function rotateAbout(p: Pt, c: Pt, deg: number): Pt {
  if (!deg) return p
  const rad = (deg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  const lx = p[0] - c[0]
  const lz = p[1] - c[1]
  return [c[0] + lx * cos + lz * sin, c[1] - lx * sin + lz * cos]
}

/** The centre a room turns about: its rect centre in LOCATION-local metres. */
export const roomCentre = (lay: RoomFrame): Pt =>
  [lay.x + lay.w / 2, lay.y + lay.d / 2]

/** ROOM-local metres → LOCATION-local metres: translate by the min corner,
 *  then turn the whole room about its centre. The one conversion. */
export const roomToLocal = (lay: RoomFrame, p: Pt): Pt =>
  rotateAbout([lay.x + p[0], lay.y + p[1]], roomCentre(lay), lay.rotation || 0)

/** The inverse — LOCATION-local metres → ROOM-local metres. Every hit test
 *  and every drag goes through it, so the cursor lands where the room is
 *  DRAWN and not where its straight frame would be. */
export const localToRoom = (lay: RoomFrame, p: Pt): Pt => {
  const q = rotateAbout(p, roomCentre(lay), -(lay.rotation || 0))
  return [q[0] - lay.x, q[1] - lay.y]
}

/** Hull polygon lifted from room-local metres into LOCATION-local metres —
 *  translation plus the room's own turn (v6 Nr. 2 + the rotation addendum). */
export const absOutline = (lay: RoomFrame): Pt[] =>
  outlineOf(lay).map((p) => roomToLocal(lay, p))

// ── Adjacency geometry (B4) — pure functions over room hulls ──
// Coordinates ARE metres since v6 Nr. 2, so the thresholds apply directly and
// nothing has to be divided by a plan width any more: collinearity tolerance
// 0.15 m, a shared segment counts from 0.8 m, a window is suggested on
// exterior edges from 2.5 m.
export const SHARE_TOL_M = 0.15
export const MIN_SHARE_M = 0.8
export const MIN_WINDOW_EDGE_M = 2.5

export interface PolyRoom extends RoomFrame { id: string }
export interface SharedEdge { edge: number; at: number; neighborId: string }

/** Shared edges of room A with the given others (same level only): edges of
 *  A's hull that run ANTIPARALLEL to a neighbour's edge (two rooms meeting at
 *  a wall face each other), within ~0.15 m sideways and overlapping ≥ 0.8 m.
 *  `edge` is A's edge index, `at` the centre of the overlap along that
 *  directed edge (fraction of the edge). */
export function sharedEdges(a: PolyRoom, others: PolyRoom[]): SharedEdge[] {
  const tol = SHARE_TOL_M
  const minOv = MIN_SHARE_M
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
export function exteriorEdges(a: PolyRoom, others: PolyRoom[]): number[] {
  const shared = new Set(sharedEdges(a, others).map((s) => s.edge))
  const n = outlineOf(a).length
  return Array.from({ length: n }, (_, i) => i).filter((i) => !shared.has(i))
}

// Mirrored openings (one hole seen from both rooms) and the derived exit
// used to live here as hand-kept mirrors of the backend (room_recipe).
// Since v4 the scene payload carries both per room in plan fractions
// (contract § B1 `rooms`) — a geometry rule exists once, in the composer.

// ── Snapping engine (drawing aid) ──
// Always on while drawing; the caller passes alt=true (Shift held) for
// free-hand. Priorities: close the polygon on its first vertex > snap to an
// existing vertex (closing small gaps beats everything) > the 45°-angle ray
// intersected with a target edge (right angles that also land on a wall) >
// plain edge projection > plain angle ray > free. All coordinates are
// LOCATION-LOCAL METRES and so are the tolerances (the caller derives them
// from its pixel-per-metre scale).
//
// NOTHING IS CLAMPED TO A SQUARE HERE. Until v6 the entry point clamped every
// raw point into [0,1]², which since the drawn boundary left that square meant
// a click outside it silently landed on the frame instead of under the cursor
// — the reported "the room does not lock in". The only bound left is the
// server's own ±500 m plan window.
export const SNAP_TOL_PX = 10
export const CLOSE_TOL_PX = 14

export interface SnapTargets { points: Pt[]; segments: Array<{ a: Pt; b: Pt }> }

/** Snap targets for a drawing session: the hulls of the placed rooms on the
 *  level, optionally the building outline (NOT when it is the thing being
 *  redrawn), the location BOUNDARY (its corners, edge midpoints and the edges
 *  themselves — "the road ends at the east edge" is a real snap, and since v6
 *  the boundary polygon is that contract surface, where the reference square
 *  used to be), plus loose extra points (the draft's own vertices). */
export function buildSnapTargets(hulls: PolyRoom[], opts?: {
  buildingOutline?: Pt[]; extraPoints?: Pt[]; boundary?: Pt[] }): SnapTargets {
  const points: Pt[] = []
  const segments: Array<{ a: Pt; b: Pt }> = []
  const addPoly = (pts: Pt[], midpoints = false) => {
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i]
      const b = pts[(i + 1) % pts.length]
      points.push(a)
      if (midpoints) points.push([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])
      segments.push({ a, b })
    }
  }
  for (const h of hulls) addPoly(absOutline(h))
  const bo = opts?.buildingOutline
  if (bo && bo.length >= 3) addPoly(bo)
  const bd = opts?.boundary
  if (bd && bd.length >= 3) addPoly(bd, true)
  for (const p of opts?.extraPoints || []) points.push(p)
  return { points, segments }
}

export interface SnapResult {
  p: Pt
  kind: 'free' | 'vertex' | 'edge' | 'angle' | 'angle+edge' | 'length' | 'close'
  /** Constraint ray to visualize for the angle kinds. */
  guide?: { a: Pt; b: Pt }
  /** Target segment being snapped onto (edge kinds). */
  seg?: { a: Pt; b: Pt }
  /** 'length' only: the matched segment length in METRES — the editor labels
   *  it as it is ("= 4.0 m"). */
  matchLen?: number
}

const _dist2 = (a: Pt, b: Pt) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
/** Every snapped point leaves here at the storage resolution — centimetres. */
const _rMp = (p: Pt): Pt => [rM(p[0]), rM(p[1])]

export function snapDrawPoint(raw: Pt, opts: {
  prev?: Pt; prevDir?: Pt; first?: Pt; draftLen?: number
  /** The full draft polyline — the equal-length snap matches the current
   *  segment against the draft's PARALLEL segments (drawing a square: the
   *  third side snaps to the first side's length). */
  draft?: Pt[]
  targets: SnapTargets; tol: number; closeTol: number; alt?: boolean
  /** Metre raster the FREE point falls onto (0 = off). Real geometry —
   *  vertices, edges, the angle ray — always wins over the raster: a wall you
   *  can see is a better anchor than an invisible line. */
  grid?: number
}): SnapResult {
  // The ONLY bound: the server's plan window. A drawn point may sit anywhere
  // around the pin, negative included — that is what a boundary polygon means.
  const p: Pt = [clamp(raw[0], -PLAN_MAX_M, PLAN_MAX_M),
                 clamp(raw[1], -PLAN_MAX_M, PLAN_MAX_M)]
  if (opts.alt) return { p: _rMp(p), kind: 'free' }
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
  if (bestV) return { p: _rMp(bestV), kind: 'vertex' }

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
      return { p: _rMp(bestX.p), kind: 'angle+edge', seg: bestX.seg,
        guide: { a: opts.prev, b: bestX.p } }
  }

  // 3b) Equal length: on the constrained ray, the segment length snaps to
  // the length of PARALLEL draft segments (±) — a square's third side gets
  // the first side's length without pixel-hunting.
  if (opts.prev && dir && opts.draft && opts.draft.length >= 2) {
    let bestL: { p: Pt; len: number } | null = null
    let bestLD = tol * tol
    for (let i = 0; i + 1 < opts.draft.length; i++) {
      const sx = opts.draft[i + 1][0] - opts.draft[i][0]
      const sy = opts.draft[i + 1][1] - opts.draft[i][1]
      const slen = Math.hypot(sx, sy)
      if (slen < 1e-9) continue
      // Parallel either way within ~1°.
      if (Math.abs((sx / slen) * dir[1] - (sy / slen) * dir[0]) > 0.02) continue
      const x: Pt = [opts.prev[0] + dir[0] * slen, opts.prev[1] + dir[1] * slen]
      const d = _dist2(p, x)
      if (d <= bestLD) {
        bestLD = d
        bestL = { p: x, len: slen }
      }
    }
    if (bestL)
      return { p: _rMp(bestL.p), kind: 'length', matchLen: bestL.len,
        guide: { a: opts.prev, b: bestL.p } }
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
  if (bestE) return { p: _rMp(bestE.p), kind: 'edge', seg: bestE.seg }

  // 5) Plain angle projection onto the constrained ray — the run along the
  // ray falls onto the metre raster, so a free-drawn wall comes out a whole
  // number of grid steps long instead of 4.37 m.
  if (opts.prev && dir) {
    const dot = snapToGrid(
      (p[0] - opts.prev[0]) * dir[0] + (p[1] - opts.prev[1]) * dir[1],
      opts.grid || 0)
    const x: Pt = [clamp(opts.prev[0] + dot * dir[0], -PLAN_MAX_M, PLAN_MAX_M),
                   clamp(opts.prev[1] + dot * dir[1], -PLAN_MAX_M, PLAN_MAX_M)]
    return { p: _rMp(x), kind: 'angle', guide: { a: opts.prev, b: x } }
  }

  // 6) Nothing to hold on to — the metre raster catches the point.
  const g = opts.grid || 0
  return { p: _rMp([snapToGrid(p[0], g), snapToGrid(p[1], g)]), kind: 'free' }
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
