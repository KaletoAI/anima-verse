/**
 * mapMath — the pure coordinate math of the free world map (no React, no DOM).
 *
 * The world is one continuous plane in METRES (contract § A1.1): `x` grows to
 * the EAST, `z` to the SOUTH. On screen east is right and south is down, so
 * the mapping is a plain scale + offset — no axis flip anywhere. A viewport is
 * described by a `View`: which world point sits in the middle of the canvas
 * (`cx`, `cz`) and how many pixels one metre is worth (`pxPerM`).
 *
 * A location is a SQUARE of edge length `plan_width_m`, centred on
 * (`pos_x`, `pos_z`) and turned by `yaw_deg`. The rotation is the contract's,
 * copied nowhere else and not re-interpreted here:
 *
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots):
 *
 *   view {cx: 100, cz: 50, pxPerM: 2}, viewport 800×600:
 *     worldToScreen(100, 50)  -> (400, 300)          (centre)
 *     worldToScreen(110, 50)  -> (420, 300)          (+10 m east = +20 px right)
 *     worldToScreen(100, 60)  -> (400, 320)          (+10 m south = +20 px down)
 *     screenToWorld(420, 320) -> (110, 60)           (inverse, exact)
 *   zoomAt(view, 2, 420, 300, 800, 600): pxPerM 4, and screenToWorld(420, 300)
 *     must still be (110, 50) -> cx becomes 105, cz stays 50.
 *   fitBounds({min_x: 0, min_z: 0, max_x: 100, max_z: 50}, 800, 600, 40):
 *     pxPerM = min(720/100, 520/50) = 7.2 -> view {cx: 50, cz: 25, pxPerM: 7.2}.
 *   footprintScreenCorners: loc (pos 10/20, width 10, yaw 90), view {cx:10, cz:20,
 *     pxPerM:1}, 200×200: local corner (+5,+5) -> world (10+5·cos90+5·sin90,
 *     20−5·sin90+5·cos90) = (15, 15) -> screen (105, 95).
 *
 * Two further cases this module decides on its own (§ A1.3 allows a degenerate
 * `world_bounds`, and the zoom is clamped):
 *
 *   fitBounds({min_x: 7, min_z: 7, max_x: 7, max_z: 7}, 800, 600, 40):
 *     no span on either axis -> pxPerM = FIT_FALLBACK_PX_PER_M (4),
 *     view {cx: 7, cz: 7, pxPerM: 4}.
 *   zoomAt({cx:0, cz:0, pxPerM: PX_PER_M_MAX}, 2, 0, 0, 800, 600) returns the
 *     SAME view object (clamped, nothing moves).
 *
 * `pointInPolygon` answers the SAME question as the server's
 * `world_geometry.point_in_polygon`, so it is pinned to the server smoke's
 * numbers (`scripts/smoke_world_geometry.py`) — the editor must not disagree
 * with the engine about which area a click hit. Triangle [(0,0), (10,0),
 * (0,10)]:
 *
 *   (2, 2)  -> true    (inside)
 *   (8, 8)  -> false   (past the hypotenuse x + z = 10)
 *   (20, 0) -> false   (far outside, on the horizontal edge's ray)
 *   pointInPolygon(0, 0, [[0,0], [1,1]]) -> false  (fewer than 3 points is
 *     not an area at all — the server fails closed the same way)
 */

/** Viewport state: world point at the canvas centre + zoom. */
export interface View {
  cx: number
  cz: number
  pxPerM: number
}

/** The `world_bounds` box of the worldmap payload (§ A1.3). */
export interface MapBounds {
  min_x: number
  min_z: number
  max_x: number
  max_z: number
}

export interface ScreenPt { x: number; y: number }
export interface WorldPt { x: number; z: number }

/** Zoom range: 0.05 px/m shows a 16 km world in one screen, 40 px/m puts a
 *  door width on 40 px. */
export const PX_PER_M_MIN = 0.05
export const PX_PER_M_MAX = 40

/** Zoom `fitBounds` falls back to when the bounds have no extent at all
 *  (a single unanchored location — § A1.3 permits `min == max`). */
export const FIT_FALLBACK_PX_PER_M = 4

export const clampZoom = (pxPerM: number): number =>
  Math.min(PX_PER_M_MAX, Math.max(PX_PER_M_MIN, pxPerM))

/** World metres -> canvas pixels. */
export function worldToScreen(x: number, z: number, view: View,
  w: number, h: number): ScreenPt {
  return {
    x: w / 2 + (x - view.cx) * view.pxPerM,
    y: h / 2 + (z - view.cz) * view.pxPerM,
  }
}

/** Canvas pixels -> world metres. Exact inverse of `worldToScreen`. */
export function screenToWorld(sx: number, sy: number, view: View,
  w: number, h: number): WorldPt {
  return {
    x: view.cx + (sx - w / 2) / view.pxPerM,
    z: view.cz + (sy - h / 2) / view.pxPerM,
  }
}

/**
 * Zoom by `factor`, anchored at the screen point (`sx`, `sy`): the world point
 * under the cursor stays under the cursor. Returns the SAME view when the
 * clamp swallows the change, so a caller can skip the re-render.
 */
export function zoomAt(view: View, factor: number, sx: number, sy: number,
  w: number, h: number): View {
  const pxPerM = clampZoom(view.pxPerM * factor)
  if (pxPerM === view.pxPerM) return view
  const anchor = screenToWorld(sx, sy, view, w, h)
  return {
    cx: anchor.x - (sx - w / 2) / pxPerM,
    cz: anchor.z - (sy - h / 2) / pxPerM,
    pxPerM,
  }
}

/**
 * A view that shows the whole box with `marginPx` of air on every side. Axes
 * without extent are ignored (a degenerate box is legal, § A1.3); when NEITHER
 * axis has extent the zoom cannot be derived at all and the fallback applies.
 */
export function fitBounds(bounds: MapBounds, w: number, h: number,
  marginPx = 40): View {
  const usableW = Math.max(1, w - 2 * marginPx)
  const usableH = Math.max(1, h - 2 * marginPx)
  const spanX = bounds.max_x - bounds.min_x
  const spanZ = bounds.max_z - bounds.min_z
  const cands: number[] = []
  if (spanX > 0) cands.push(usableW / spanX)
  if (spanZ > 0) cands.push(usableH / spanZ)
  const pxPerM = cands.length ? Math.min(...cands) : FIT_FALLBACK_PX_PER_M
  return {
    cx: (bounds.min_x + bounds.max_x) / 2,
    cz: (bounds.min_z + bounds.max_z) / 2,
    pxPerM: clampZoom(pxPerM),
  }
}

/** The world rectangle the canvas currently shows (grid, culling). */
export function visibleWorldRect(view: View, w: number, h: number): MapBounds {
  const a = screenToWorld(0, 0, view, w, h)
  const b = screenToWorld(w, h, view, w, h)
  return { min_x: a.x, min_z: a.z, max_x: b.x, max_z: b.z }
}

/** What a footprint needs: a placed centre and a positive scale anchor. */
export interface FootprintSource {
  pos_x?: number | null
  pos_z?: number | null
  yaw_deg?: number | null
  plan_width_m?: number | null
}

/** Location-local metres -> world metres (§ A1.1, sign convention included). */
export function localToWorld(cx: number, cz: number, yawDeg: number,
  lx: number, lz: number): WorldPt {
  const rad = (yawDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  return { x: cx + lx * cos + lz * sin, z: cz - lx * sin + lz * cos }
}

/** World metres -> location-local metres (rotation by −yaw). */
export function worldToLocal(cx: number, cz: number, yawDeg: number,
  x: number, z: number): WorldPt {
  const rad = (yawDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  const dx = x - cx
  const dz = z - cz
  return { x: dx * cos - dz * sin, z: dx * sin + dz * cos }
}

/**
 * The four screen corners of a location's footprint square, in local order
 * NW → NE → SE → SW (local −x/−z first, then clockwise on the local axes).
 * `null` when the location is unplaced or has no positive scale anchor — it
 * then has no area at all (§ A1.1/§ A1.3), and drawing one would be a lie.
 */
export function footprintScreenCorners(loc: FootprintSource, view: View,
  w: number, h: number): ScreenPt[] | null {
  const { pos_x: px, pos_z: pz, plan_width_m: pw } = loc
  if (typeof px !== 'number' || !Number.isFinite(px)) return null
  if (typeof pz !== 'number' || !Number.isFinite(pz)) return null
  if (typeof pw !== 'number' || !(pw > 0)) return null
  const yaw = typeof loc.yaw_deg === 'number' && Number.isFinite(loc.yaw_deg)
    ? loc.yaw_deg : 0
  const r = pw / 2
  const local: Array<[number, number]> = [[-r, -r], [r, -r], [r, r], [-r, r]]
  return local.map(([lx, lz]) => {
    const p = localToWorld(px, pz, yaw, lx, lz)
    return worldToScreen(p.x, p.z, view, w, h)
  })
}

/** An SVG path over world points (terrain polygons, journey lines). */
export function worldPolyToPath(points: Array<[number, number]>, view: View,
  w: number, h: number, close = true): string {
  if (!points.length) return ''
  const parts = points.map(([x, z], i) => {
    const p = worldToScreen(x, z, view, w, h)
    return `${i ? 'L' : 'M'}${p.x.toFixed(2)} ${p.y.toFixed(2)}`
  })
  return parts.join(' ') + (close ? ' Z' : '')
}

/**
 * Point-in-polygon in WORLD metres (ray casting) — which painted area a click
 * hit. The topmost hit wins; that ordering is the caller's (§ A1.5).
 *
 * The algorithm is the server's (`app/core/world_geometry.point_in_polygon`),
 * INCLUDING its fail-closed guard: fewer than three points enclose nothing, so
 * a half-drawn draft can never swallow a click. The ray-casting loop alone
 * would already return false for a two-point "polygon" (it walks the single
 * edge twice and toggles twice), but relying on that coincidence would leave
 * the two implementations agreeing by accident instead of by rule.
 */
export function pointInPolygon(x: number, z: number,
  poly: Array<[number, number]>): boolean {
  if (poly.length < 3) return false
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i]
    const [xj, zj] = poly[j]
    if ((zi > z) !== (zj > z)
      && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside
  }
  return inside
}

/** A join is bevelled once the miter would stick out further than this many
 *  stroke widths — 2 widths means only a near-hairpin (turn > 151°) bevels. */
export const STROKE_MITER_LIMIT_WIDTHS = 2

/** Two stroke points closer than this are the same click, not a segment. */
const STROKE_EPS = 1e-9

/** Metres are stored with 2 decimals (server side), so the ribbon rounds too. */
const round2 = (v: number): number => Math.round(v * 100) / 100 + 0

/**
 * A centre LINE plus a width becomes the AREA polygon the world actually
 * stores (`meta.stroke` is only the recipe; `terrain_areas.polygon` stays the
 * truth). Offset by `widthM / 2` to both sides, walk side A forward and side B
 * backward, and the ring closes itself — the result is an ordinary painted
 * area that nothing downstream has to know was drawn as a line.
 *
 * Conventions, all decided here and nowhere else:
 *   - a segment direction `d = (dx, dz)` has side normals `A = (dz, −dx)` and
 *     `B = (−dz, dx)`. With x east / z south (§ A1.1) side A is the northern
 *     side of a west→east line.
 *   - joins use the miter: the averaged unit normal `m̂ = normalize(n1 + n2)`
 *     and `cos(θ/2) = m̂·n1`, so the corner sits at `p + m̂ · offset/cos(θ/2)`.
 *     Once that length passes `STROKE_MITER_LIMIT_WIDTHS × widthM` the spike is
 *     cut off by a BEVEL: the two segment-end offset points instead of one.
 *   - caps are flat (endpoint ± normal, no round/square extension), so a stroke
 *     never covers ground the user did not click over.
 *   - consecutive duplicate clicks are dropped BEFORE any direction is taken.
 *
 * Point count: `2n` with every join mitered, `+2` per bevelled join (both sides
 * bevel together — the limit is symmetric), i.e. `2n + 2b`. Callers must size
 * the centre line against the server's 256-point polygon limit, not against
 * their own click count.
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots):
 *
 *   straight [(0,0),(10,0)], width 4: offset 2, nA = (0,−1), nB = (0,1)
 *     -> [(0,−2),(10,−2),(10,2),(0,2)]
 *   90° bend [(0,0),(10,0),(10,10)], width 4: at (10,0) side A joins
 *     n1 = (0,−1) with n2 = (1,0), m̂ = (0.7071,−0.7071),
 *     cos(θ/2) = 0.7071, miter len = 2/0.7071 = 2.8284 <= 2×4 = 8
 *     -> (10,0) + (2,−2) = (12,−2); side B mirrors to (8,2)
 *     -> [(0,−2),(12,−2),(12,10),(8,10),(8,2),(0,2)]
 *   collinear [(0,0),(5,0),(10,0)], width 4: cos(θ/2) = 1, miter len = offset
 *     -> [(0,−2),(5,−2),(10,−2),(10,2),(5,2),(0,2)]   (2n = 6 points)
 *   hairpin [(0,0),(10,0),(0.4,2.8)], width 4: d2 = (−0.96,0.28) is a unit
 *     vector (0.9216+0.0784 = 1), cos θ = −0.96, cos(θ/2) = sqrt(0.02)
 *     = 0.141421, miter len = 2/0.141421 = 14.142 > 8 -> bevel:
 *     A gets (10,0)+2(0,−1) = (10,−2) and (10,0)+2(0.28,0.96) = (10.56,1.92),
 *     B gets (10,2) and (9.44,−1.92); end caps (0.4,2.8) ± 2·n2
 *     -> [(0,−2),(10,−2),(10.56,1.92),(0.96,4.72),
 *         (−0.16,0.88),(9.44,−1.92),(10,2),(0,2)]     (2n+2 = 8 points)
 *   [(0,0),(0,0),(10,0),(10,0)] width 4 -> the straight case (dupes dropped)
 *   [(0,0),(3.14159,0)] width 1.111 -> [(0,−0.56),(3.14,−0.56),(3.14,0.56),
 *     (0,0.56)]                                        (2 decimals, always)
 *
 * `null` — never a half-polygon — for: fewer than 2 distinct points, a width
 * that is not positive, a non-finite coordinate, and the one case rounding
 * creates on its own: a line shorter than the 2-decimal grid
 * ([(0,0),(0.001,0)], width 4) collapses to 2 distinct points and would be a
 * zero-area "area", so it is refused like any other degenerate input.
 */
export function strokeToPolygon(points: Array<[number, number]>,
  widthM: number): Array<[number, number]> | null {
  if (!Number.isFinite(widthM) || widthM <= 0) return null

  // 1. clean the centre line: finite coordinates, no repeated click.
  const line: Array<[number, number]> = []
  for (const p of points) {
    if (!p || p.length < 2) return null
    const [x, z] = p
    if (!Number.isFinite(x) || !Number.isFinite(z)) return null
    const prev = line[line.length - 1]
    if (prev && Math.abs(prev[0] - x) < STROKE_EPS
      && Math.abs(prev[1] - z) < STROKE_EPS) continue
    line.push([x, z])
  }
  if (line.length < 2) return null

  // 2. per-segment unit direction and side-A normal (dz, −dx).
  const dir: Array<[number, number]> = []
  const nrm: Array<[number, number]> = []
  for (let i = 1; i < line.length; i++) {
    const dx = line[i][0] - line[i - 1][0]
    const dz = line[i][1] - line[i - 1][1]
    const len = Math.hypot(dx, dz)
    dir.push([dx / len, dz / len])
    nrm.push([dz / len, -dx / len])
  }

  const off = widthM / 2
  const miterMax = STROKE_MITER_LIMIT_WIDTHS * widthM

  /** One offset side; `s` is +1 for side A and −1 for side B. */
  const buildSide = (s: number): Array<[number, number]> => {
    const out: Array<[number, number]> = []
    const push = (px: number, pz: number, nx: number, nz: number) =>
      out.push([px + s * off * nx, pz + s * off * nz])

    push(line[0][0], line[0][1], nrm[0][0], nrm[0][1])           // flat start cap
    for (let i = 1; i < line.length - 1; i++) {
      const [px, pz] = line[i]
      const [n1x, n1z] = nrm[i - 1]
      const [n2x, n2z] = nrm[i]
      const mx = n1x + n2x
      const mz = n1z + n2z
      const mlen = Math.hypot(mx, mz)
      let mitered = false
      if (mlen > STROKE_EPS) {
        const cosHalf = (mx / mlen) * n1x + (mz / mlen) * n1z
        const miterLen = off / cosHalf
        if (cosHalf > STROKE_EPS && miterLen <= miterMax) {
          out.push([px + s * (mx / mlen) * miterLen,
            pz + s * (mz / mlen) * miterLen])
          mitered = true
        }
      }
      if (!mitered) {                                            // bevel: 2 points
        push(px, pz, n1x, n1z)
        push(px, pz, n2x, n2z)
      }
    }
    const last = nrm[nrm.length - 1]
    push(line[line.length - 1][0], line[line.length - 1][1], last[0], last[1])
    return out
  }

  // 3. side A forward + side B backward, rounded, without repeated points.
  const ring = [...buildSide(1), ...buildSide(-1).reverse()]
    .map(([x, z]): [number, number] => [round2(x), round2(z)])
  const poly: Array<[number, number]> = []
  for (const [x, z] of ring) {
    const prev = poly[poly.length - 1]
    if (prev && prev[0] === x && prev[1] === z) continue
    poly.push([x, z])
  }
  const first = poly[0]
  const tail = poly[poly.length - 1]
  if (poly.length > 1 && first[0] === tail[0] && first[1] === tail[1]) poly.pop()
  return poly.length >= 3 ? poly : null
}
