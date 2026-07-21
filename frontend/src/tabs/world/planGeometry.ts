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
// Openings sit on a room's rectangle edges ('N'|'S'|'E'|'W'); the schematic
// symbol is drawn in a small fixed-size SVG, rotated so the interior side
// faces into the room (N up, then clockwise). New openings default to a
// standard door.
export type EdgeLetter = 'N' | 'S' | 'E' | 'W'
export const EDGE_ROT: Record<EdgeLetter, number> = { N: 0, S: 180, E: 270, W: 90 }
export const OPENING_DEFAULT = { type: 'door' as const, width_m: 1.0, height_m: 2.1, sill_m: 0 }
export const OPENING_COLOR: Record<string, string> = {
  door: '#e0a356', window: '#79c0ff', passage: '#8b949e',
}

/** Nearest rectangle edge + position along it for a click inside a room
 *  (px/py = fractions of the room rectangle). */
export const nearestEdge = (px: number, py: number): { edge: EdgeLetter; at: number } => {
  const d: Record<EdgeLetter, number> = { N: py, S: 1 - py, W: px, E: 1 - px }
  const edge = (Object.keys(d) as EdgeLetter[]).reduce((a, b) => (d[a] <= d[b] ? a : b))
  return { edge, at: edge === 'N' || edge === 'S' ? px : py }
}

/** Point on the room rectangle (fractions) for an opening on an edge. */
export const edgePoint = (edge: EdgeLetter, at: number): { x: number; y: number } =>
  edge === 'N' ? { x: at, y: 0 }
    : edge === 'S' ? { x: at, y: 1 }
      : edge === 'W' ? { x: 0, y: at }
        : { x: 1, y: at }

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
export const r4 = (v: number) => Math.round(v * 10000) / 10000

/** Edge + position of an opening after rotating the room 90° clockwise
 *  ((x,y) -> (1-y,x)), so openings turn with the room like exit/markers. */
export const rotateOpeningCW = (edge: EdgeLetter, at: number): { edge: EdgeLetter; at: number } =>
  edge === 'N' ? { edge: 'E', at }
    : edge === 'E' ? { edge: 'S', at: r4(1 - at) }
      : edge === 'S' ? { edge: 'W', at }
        : { edge: 'N', at: r4(1 - at) }

// ── Adjacency geometry (B4) — pure functions over rectangle rooms ──
// All coordinates are fractions of the 8 m reference square; real metres come
// from planW (the same plan_width_m the editor derives), so the thresholds are
// stated in metres. Collinearity tolerance ~0.15 m, a shared segment counts
// from 0.8 m, a window is suggested on exterior edges from 2.5 m.
export const SHARE_TOL_M = 0.15
export const MIN_SHARE_M = 0.8
export const MIN_WINDOW_EDGE_M = 2.5

export interface RectRoom { id: string; x: number; y: number; w: number; d: number }
export interface SharedEdge { edge: EdgeLetter; at: number; neighborId: string }

const _overlap = (a0: number, a1: number, b0: number, b1: number): [number, number] | null => {
  const s = Math.max(a0, b0)
  const e = Math.min(a1, b1)
  return e > s ? [s, e] : null
}

/** Shared edges of room A with the given others (same level only): edges that
 *  are collinear with an opposite edge of a neighbour and overlap by ≥ 0.8 m.
 *  `at` is the centre of the overlap along A's edge (fraction of A's edge). */
export function sharedEdges(a: RectRoom, others: RectRoom[], planW: number): SharedEdge[] {
  const tol = planW > 0 ? SHARE_TOL_M / planW : 0.02
  const minOv = planW > 0 ? MIN_SHARE_M / planW : 0.1
  const ax1 = a.x + a.w
  const ay1 = a.y + a.d
  const out: SharedEdge[] = []
  for (const b of others) {
    const bx1 = b.x + b.w
    const by1 = b.y + b.d
    const centerAlong = (ov: [number, number], lo: number, len: number) =>
      clamp(((ov[0] + ov[1]) / 2 - lo) / (len || 1), 0, 1)
    // A.E vs B.W / A.W vs B.E — vertical edges, overlap in y.
    let ov = _overlap(a.y, ay1, b.y, by1)
    if (ov && ov[1] - ov[0] >= minOv) {
      if (Math.abs(ax1 - b.x) <= tol) out.push({ edge: 'E', at: centerAlong(ov, a.y, a.d), neighborId: b.id })
      if (Math.abs(a.x - bx1) <= tol) out.push({ edge: 'W', at: centerAlong(ov, a.y, a.d), neighborId: b.id })
    }
    // A.S vs B.N / A.N vs B.S — horizontal edges, overlap in x.
    ov = _overlap(a.x, ax1, b.x, bx1)
    if (ov && ov[1] - ov[0] >= minOv) {
      if (Math.abs(ay1 - b.y) <= tol) out.push({ edge: 'S', at: centerAlong(ov, a.x, a.w), neighborId: b.id })
      if (Math.abs(a.y - by1) <= tol) out.push({ edge: 'N', at: centerAlong(ov, a.x, a.w), neighborId: b.id })
    }
  }
  return out
}

/** Edges of room A that share no segment with any neighbour (exterior walls). */
export function exteriorEdges(a: RectRoom, others: RectRoom[], planW: number): EdgeLetter[] {
  const shared = new Set(sharedEdges(a, others, planW).map((s) => s.edge))
  return (['N', 'S', 'E', 'W'] as EdgeLetter[]).filter((e) => !shared.has(e))
}
