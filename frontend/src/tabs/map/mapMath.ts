/**
 * mapMath — the pure coordinate math of the free world map (no React, no DOM).
 *
 * The world is one continuous plane in METRES (contract § A1.1): `x` grows to
 * the EAST, `z` to the SOUTH. On screen east is right and south is down, so
 * the mapping is a plain scale + offset — no axis flip anywhere. A viewport is
 * described by a `View`: which world point sits in the middle of the canvas
 * (`cx`, `cz`) and how many pixels one metre is worth (`pxPerM`).
 *
 * A location is a drawn POLYGON (`boundary`) in LOCAL metres around
 * (`pos_x`, `pos_z`), turned by `yaw_deg`. The rotation is the contract's,
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
 *   boundaryScreenPoints: loc (pos 10/20, yaw 90), view {cx:10, cz:20,
 *     pxPerM:1}, 200×200: boundary point (+5,+5) -> world (10+5·cos90+5·sin90,
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
import {
  cleanRing, polygonArea, scatterCellCountInBox, scatterCellInstances,
  scatterCellSeed, scatterCellsInBox, scatterClearM, scatterInstances,
  scatterSeed, scatterWantedCount, seededRandom, worldToLocalXZ,
  SCATTER_CELL_M, SCATTER_CELLS_MAX, SCATTER_MAX_PER_CELL,
} from '@anima/scene-render'
import type { Point2, ScatterFootprint } from '@anima/scene-render'
import { readScatter } from './mapTypes'
import type { FlowAlong, TerrainArea, TerrainWaterKnot,
  TerrainWaterProfile } from './mapTypes'

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
export interface BoundarySource {
  pos_x?: number | null
  pos_z?: number | null
  yaw_deg?: number | null
  /** The location's outline in LOCAL metres around the pin (contract v6).
   *  The worldmap row carries it hoisted, the editor's full dict carries it
   *  in `map3d.boundary` — callers hand over whichever they hold, already
   *  checked; this function only projects. */
  boundary?: Array<[number, number]> | null
}

/** Location-local metres -> world metres (§ A1.1, sign convention included). */
export function localToWorld(cx: number, cz: number, yawDeg: number,
  lx: number, lz: number): WorldPt {
  const rad = (yawDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  return { x: cx + lx * cos + lz * sin, z: cz - lx * sin + lz * cos }
}

/** World metres -> location-local metres (rotation by −yaw).
 *
 *  The arithmetic lives in `@anima/scene-render` (`worldToLocalXZ`, which takes
 *  RADIANS): the 3D client turns tiles with it and the editor turns pointer
 *  positions with it. One mapping, one home. */
export function worldToLocal(cx: number, cz: number, yawDeg: number,
  x: number, z: number): WorldPt {
  return worldToLocalXZ(cx, cz, (yawDeg * Math.PI) / 180, x, z)
}

/**
 * The location's DRAWN outline in screen points, in stored order.
 *
 * `null` when the location is unplaced or carries no outline — it then has no
 * area at all (contract v6; the transition square that used to stand in for a
 * missing outline ended 2026-08-19), and drawing one would be a lie.
 *
 * Pinned to the § B5a case, hand-checked: location (pos 10/20, yaw 90), view
 * {cx:10, cz:20, pxPerM:1} on 200×200, boundary point (+5,+5) → § A1.1 →
 * world (15, 15) → screen (105, 95).
 */
export function boundaryScreenPoints(loc: BoundarySource, view: View,
  w: number, h: number): ScreenPt[] | null {
  const { pos_x: px, pos_z: pz, boundary } = loc
  if (typeof px !== 'number' || !Number.isFinite(px)) return null
  if (typeof pz !== 'number' || !Number.isFinite(pz)) return null
  if (!Array.isArray(boundary) || boundary.length < 3) return null
  const yaw = typeof loc.yaw_deg === 'number' && Number.isFinite(loc.yaw_deg)
    ? loc.yaw_deg : 0
  return boundary.map(([lx, lz]) => {
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
 * THE AREA CENTROID of a polygon in world metres — the point the flow axis of
 * a water area runs through (`heightfield.WaterProfile.axis_x/axis_z`, W1 § 2).
 *
 * The real centroid formula, NOT the mean of the vertices: a river drawn with
 * ten points along one bank and two along the other has its vertex mean pulled
 * onto the dense bank, and an arrow drawn there would sit outside the water it
 * describes. The two agree on a rectangle and disagree on everything else,
 * which is why the server picked this one and why the preview must use the
 * same one.
 *
 * A DEGENERATE ring (zero signed area — all points collinear, or a bow tie
 * whose lobes cancel) has no centroid to compute: the vertex mean answers
 * then, because a marker in roughly the right place beats no marker at all.
 */
export function polygonCentroid(points: Array<[number, number]>
                               ): [number, number] {
  const n = points.length
  if (!n) return [0, 0]
  let a2 = 0
  let cx = 0
  let cz = 0
  for (let i = 0; i < n; i += 1) {
    const [x0, z0] = points[i]
    const [x1, z1] = points[(i + 1) % n]
    const cross = x0 * z1 - x1 * z0
    a2 += cross
    cx += (x0 + x1) * cross
    cz += (z0 + z1) * cross
  }
  if (Math.abs(a2) < 1e-9) {
    let mx = 0
    let mz = 0
    for (const [x, z] of points) { mx += x; mz += z }
    return [mx / n, mz / n]
  }
  return [cx / (3 * a2), cz / (3 * a2)]
}

/**
 * HOW MUCH GROUND A PAINTED AREA COVERS, in square metres.
 *
 * The shoelace, taken by absolute value, so a ring painted clockwise measures
 * the same as one painted the other way — and it is the SHARED one
 * (`@anima/scene-render.polygonArea`), the very routine the scatter budget and
 * both renderers already measure areas with. A second shoelace here would be a
 * second opinion about a number the editor shows the author.
 *
 * The ring is cleaned first (`cleanRing`), which is what makes this the area of
 * the shape that is really DRAWN: a repeated closing corner (the editor may or
 * may not store one) is not an edge, and a non-finite corner is DROPPED rather
 * than turning the whole measurement into `NaN` — the renderers mesh that same
 * cleaned ring, so the number beside the shape is the number of the shape.
 * Fewer than three surviving points enclose nothing and measure 0.
 *
 * A STROKE AREA IS MEASURED BY ITS POLYGON like every other area, because that
 * polygon IS the ground it covers: the centre line has no area, and the ribbon
 * generated from it is what the bake paints and what a walker stands on.
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots):
 *
 *   [(0,0),(10,0),(10,20),(0,20)]  -> 200      (a 10 × 20 m rectangle)
 *   the same ring drawn backwards  -> 200      (winding-blind)
 *   [(0,0),(30,0),(0,40)]          -> 600      (½ · 30 · 40)
 *   [(0,0),(10,0)]                 -> 0        (two points enclose nothing)
 *   [(0,0),(10,NaN),(10,20),(0,20)]-> 100      (the broken corner is dropped;
 *                                               the triangle that is left)
 */
export function polygonAreaM2(polygon: Array<[number, number]> | null | undefined
                             ): number {
  return polygonArea(cleanRing(polygon))
}

/** At and above this an area is easier to read in hectares as well — one
 *  hectare is 10 000 m², so the second reading starts where it first says
 *  "1.00 ha" instead of a fraction. */
export const AREA_HECTARE_M2 = 10000

/**
 * An area as the panel prints it: `"1 234 m²"`, and from a hectare up the same
 * number in hectares beside it — `"12 300 m² (1.23 ha)"`.
 *
 * SQUARE METRES STAY THE LEAD NUMBER at every size. They are the unit
 * everything else in this editor is in (widths, ramps, depths, the grid), so a
 * reader can hold an area against a room's footprint without converting
 * anything; the hectares are the second reading that makes a landscape-sized
 * number graspable, not a replacement for the first.
 *
 * The digit grouping is done here and NOT by `toLocaleString`: the separator
 * that call picks depends on the machine's locale, which would make the same
 * world read differently on two computers and this check unrepeatable. The
 * space is a NARROW NO-BREAK SPACE (U+202F) — the thousands separator of the
 * SI convention, and unbreakable so a number never wraps in the middle.
 *
 * Verification cases (hand-derived): 0 -> `0 m²`, 999.4 -> `999 m²`,
 * 1234 -> `1 234 m²`, 9999.5 -> `10 000 m²` (rounded, and the hectare reading
 * follows the ROUNDED number the reader sees), 12300 -> `12 300 m² (1.23 ha)`,
 * 1234567 -> `1 234 567 m² (123.46 ha)`.
 */
export function formatAreaM2(m2: number): string {
  const rounded = Number.isFinite(m2) ? Math.round(m2) : 0
  const grouped = String(rounded).replace(/\B(?=(\d{3})+(?!\d))/g, '\u202f')
  const base = `${grouped} m²`
  if (rounded < AREA_HECTARE_M2) return base
  return `${base} (${(rounded / AREA_HECTARE_M2).toFixed(2)} ha)`
}

/**
 * THE DOWNSTREAM UNIT VECTOR of a flow bearing — `(sin θ, cos θ)`.
 *
 * The contract's ONE yaw mapping (§ A1.1), the same one
 * `heightfield.flow_direction` uses: 0° runs toward +z, 90° toward +x. Writing
 * it any other way here would draw an arrow pointing where the water does not
 * go, which is the single thing this preview exists to rule out.
 *
 * The components are rounded to twelve decimals for the same reason the server
 * rounds them: `cos(270°)` is −1.8e−16 in binary floating point, and a cardinal
 * arrow must come out exactly axis-aligned.
 */
export function flowDirection(deg: number): [number, number] {
  const rad = (deg * Math.PI) / 180
  const round12 = (v: number) => {
    const r = Math.round(v * 1e12) / 1e12
    // −0 is equal to 0 everywhere except where it is rendered.
    return r === 0 ? 0 : r
  }
  return [round12(Math.sin(rad)), round12(Math.cos(rad))]
}

/** The eight-point compass, CLOCKWISE from north — the order a compass rose
 *  is read in. */
const COMPASS_LETTERS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']

/**
 * THE COMPASS LETTER of a flow bearing, by the contract's own yaw convention
 * (§ A1.1): `dir = (sin θ, cos θ)`, so 0° runs toward +z and 90° toward +x. On
 * this map +z is SOUTH and +x is EAST (`worldToScreen` above), so 0° is S,
 * 90° is E, 180° is N and 270° is W — spelled out deliberately, because
 * guessing "0 = north" from a compass habit is exactly how a river ends up
 * flowing backwards on the picture.
 *
 * THE TWO SCALES RUN OPPOSITE WAYS, and that is the whole arithmetic: the
 * compass rose above steps CLOCKWISE from north, while a rising bearing steps
 * from south toward east, i.e. ANTICLOCKWISE on that same rose. So the index
 * is subtracted from the four eighth-turns that separate S from N, not added
 * to them — `(4 − step) mod 8`, which sends 0° to S, 45° to SE, 90° to E and
 * 270° to W.
 */
export function flowCompass(deg: number): string {
  const step = Math.round((((deg % 360) + 360) % 360) / 45) % 8
  return COMPASS_LETTERS[(4 - step + 8) % 8]
}

/** A flow arrow in WORLD metres: where it starts, where its tip is and the two
 *  barbs of the head. Everything a renderer needs, and no pixels — the caller
 *  projects it with `worldToScreen` like every other world shape. */
export interface FlowArrow {
  from: [number, number]
  to: [number, number]
  barbs: [[number, number], [number, number]]
}

/** One arrow of a given length, centred on (`cx`, `cz`) and pointing along the
 *  UNIT vector (`dx`, `dz`). The head is two barbs a quarter of the length back
 *  from the tip, swung out to either side by the perpendicular (−dz, dx). One
 *  routine for both arrow makers below, so a straight river and a drawn one
 *  cannot end up with differently shaped heads. */
function arrowAt(cx: number, cz: number, dx: number, dz: number,
  len: number): FlowArrow {
  const half = len / 2
  const from: [number, number] = [cx - dx * half, cz - dz * half]
  const to: [number, number] = [cx + dx * half, cz + dz * half]
  const back = len * 0.25
  const side = len * 0.15
  const barb = (sign: number): [number, number] => [
    to[0] - dx * back + sign * -dz * side,
    to[1] - dz * back + sign * dx * side,
  ]
  return { from, to, barbs: [barb(1), barb(-1)] }
}

/**
 * THE ARROW THAT SHOWS WHICH WAY A POLYGON WATER AREA FLOWS, in world metres.
 *
 * It sits on the area's own flow axis, centred on the centroid the profile is
 * built around, and it points DOWNSTREAM — the direction `flow_dir_deg` names.
 * Its length is a fraction of the polygon's extent ALONG that axis, so a
 * kilometre of river and a ten-metre brook both get an arrow that reads as one
 * inside its own shape, clamped so neither degenerates: too short and it is a
 * dot, too long and it leaves the water at the bends.
 *
 * ONE STRAIGHT AXIS IS ALL A POLYGON HAS, and that is the whole of what this
 * draws. An area drawn with the LINE tool carries its own bent axis and is
 * drawn by `flowArrowsAlong` instead (W4a) — where both exist the line wins,
 * exactly as it does in the bake (`heightfield.is_flowing`).
 *
 * `null` for still water — a lake has no downstream, and drawing an arrow of
 * some default bearing would be an invention. Pure: no view, no pixels, no
 * DOM, so the numbers are checkable by hand (`scripts/smoke_water_meta.mjs`).
 */
export function flowArrow(polygon: Array<[number, number]>,
  flowDirDeg: number | undefined,
  opts: { minM?: number; maxM?: number; share?: number } = {}
): FlowArrow | null {
  if (flowDirDeg === undefined || polygon.length < 3) return null
  const minM = opts.minM ?? 4
  const maxM = opts.maxM ?? 60
  const share = opts.share ?? 0.5
  const [cx, cz] = polygonCentroid(polygon)
  const [dx, dz] = flowDirection(flowDirDeg)
  // The polygon's extent along the flow axis — the very span the server's
  // profile interpolates over (`s_min`…`s_max`), measured from the centroid.
  let sMin = Infinity
  let sMax = -Infinity
  for (const [x, z] of polygon) {
    const s = (x - cx) * dx + (z - cz) * dz
    if (s < sMin) sMin = s
    if (s > sMax) sMax = s
  }
  const span = sMax - sMin
  if (!Number.isFinite(span) || span <= 0) return null
  const len = Math.min(maxM, Math.max(minM, span * share))
  return arrowAt(cx, cz, dx, dz, len)
}

/**
 * THE AXIS AN AREA DRAWN AS A LINE FLOWS ALONG, in flow order — or `null` when
 * it does not flow (W4a).
 *
 * `meta.flow_along` is the whole authoring: `forward` is the order the points
 * were clicked, `reverse` is that line read from the far end, and an absent
 * word is still water. Reversing the POINTS instead of carrying a sign is what
 * keeps everything downstream of here — arrows, tangents, levels — a single
 * unsigned walk from `axis[0]` to `axis[n−1]`, which is exactly how the server
 * builds its knots.
 *
 * Two points are the bar, not the editor's own minimum: one point is not a
 * direction (`heightfield.is_flowing`).
 */
export function flowAxisPoints(points: Array<[number, number]> | null | undefined,
  along: FlowAlong | undefined): Array<[number, number]> | null {
  if (!points || points.length < 2) return null
  if (along !== 'forward' && along !== 'reverse') return null
  return along === 'forward' ? points.slice() : points.slice().reverse()
}

/**
 * THE ARROWS OF A RIVER THAT FOLLOWS ITS OWN LINE — one per SEGMENT of the
 * axis, in world metres (W4a).
 *
 * A river bends, and one arrow through the centroid says nothing about where a
 * meander runs: on a hairpin it points straight across the two legs. One arrow
 * per segment, centred on that segment's midpoint and pointing along it, says
 * the one thing the author needs to check — that the water runs down the line
 * the way they meant it to, around every bend.
 *
 * Each arrow is a share of ITS OWN segment, clamped the way the polygon arrow
 * is and then capped by the segment length, so a long straight reach gets a
 * readable arrow while a short kink gets one that still fits between its two
 * knots instead of sticking out over the neighbours.
 *
 * The axis is taken as GIVEN — in flow order, from `flowAxisPoints` or from a
 * profile's knots. Zero-length segments are skipped rather than repaired: they
 * have no direction, and inventing one would point somewhere nobody drew.
 */
export function flowArrowsAlong(axis: Array<[number, number]>,
  opts: { minM?: number; maxM?: number; share?: number } = {}
): FlowArrow[] {
  const minM = opts.minM ?? 4
  const maxM = opts.maxM ?? 60
  const share = opts.share ?? 0.5
  const out: FlowArrow[] = []
  for (let i = 0; i + 1 < axis.length; i++) {
    const [ax, az] = axis[i]
    const [bx, bz] = axis[i + 1]
    const dx = bx - ax
    const dz = bz - az
    const segLen = Math.hypot(dx, dz)
    if (!Number.isFinite(segLen) || segLen <= 0) continue
    const len = Math.min(segLen, Math.min(maxM, Math.max(minM, segLen * share)))
    out.push(arrowAt((ax + bx) / 2, (az + bz) / 2,
      dx / segLen, dz / segLen, len))
  }
  return out
}

/** Where a point sits on a polyline: the closest point ON the line, the
 *  segment that carries it and how far the query point is away. */
export interface NearestOnPolyline {
  /** Index of the segment's FIRST point (0 on a one-point line). */
  index: number
  /** Position along that segment, 0…1. */
  t: number
  /** The foot point in world metres. */
  x: number
  z: number
  /** Distance from the queried point to the foot, in metres. */
  distM: number
}

/**
 * The point on a polyline closest to (`x`, `z`) — the FOOT of the query point.
 *
 * A journey (§ A11) is a polyline plus the walked distance, and the server
 * already reports where the walker IS (`characters[].pos`). A map that only
 * wants to draw the REST of the route therefore needs no arc-length walk of
 * its own: it asks which segment the position sits on and draws from the foot
 * point onwards. The projection is the ordinary one — the query point minus
 * the segment start, projected onto the segment direction and clamped to the
 * segment, so a point beside or beyond the line lands on its end.
 *
 * Ties go to the EARLIER segment (`<`, never `<=`): where a route touches
 * itself the walker is on the part already being walked, and taking the later
 * one would jump the drawn rest across the loop.
 *
 * The search is GLOBAL, and that is a limit worth naming: it knows nothing
 * about how far the walker has come, so on a route that comes back NEAR (not
 * exactly onto) an earlier passage the nearest segment can be the wrong one,
 * and a drawn "rest" would then include a stretch already walked. The exact
 * touch is covered by the tie rule, the near miss is not. Whoever needs the
 * true position on a self-approaching route feeds `progress_m` through an
 * arc-length walk (`client3d/src/scene/travelPath.ts`) instead of this
 * projection.
 *
 * `null` for an empty line or a non-finite query point — never a foot point
 * that is not on the line.
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots), all
 * on the polyline [(0,0), (10,0), (10,10)]:
 *
 *   (4, 1):  seg 0 d = (10,0), |d|² = 100, t = (4·10 + 1·0)/100 = 0.4
 *            -> foot (4,0), dist |(0,1)| = 1
 *            seg 1 a = (10,0), d = (0,10), t = (−6·0 + 1·10)/100 = 0.1
 *            -> foot (10,1), dist |(−6,0)| = 6
 *            => {index: 0, t: 0.4, x: 4, z: 0, distM: 1}
 *   (12, 12): both t clamp to 1; seg 1 foot (10,10), dist √(2²+2²) = 2.8284;
 *            seg 0 foot (10,0), dist √(2²+12²) = 12.166
 *            => {index: 1, t: 1, x: 10, z: 10, distM: 2.8284…}
 *   (5, 5):  seg 0 foot (5,0) dist 5, seg 1 foot (10,5) dist 5 — a tie, and
 *            the earlier segment keeps it => {index: 0, t: 0.5, x: 5, z: 0}
 *   [(5,5)] alone, query (5,7): no segment at all, so the single point IS the
 *            foot => {index: 0, t: 0, x: 5, z: 5, distM: 2}
 */
export function nearestOnPolyline(points: Array<[number, number]>,
  x: number, z: number): NearestOnPolyline | null {
  if (!points.length) return null
  if (!Number.isFinite(x) || !Number.isFinite(z)) return null
  const [x0, z0] = points[0]
  let best: NearestOnPolyline = {
    index: 0, t: 0, x: x0, z: z0, distM: Math.hypot(x0 - x, z0 - z),
  }
  for (let i = 0; i < points.length - 1; i++) {
    const [ax, az] = points[i]
    const dx = points[i + 1][0] - ax
    const dz = points[i + 1][1] - az
    const len2 = dx * dx + dz * dz
    // A collapsed segment has no direction; its start point answers for it.
    const t = len2 > 0
      ? Math.min(1, Math.max(0, ((x - ax) * dx + (z - az) * dz) / len2))
      : 0
    const fx = ax + t * dx
    const fz = az + t * dz
    const d = Math.hypot(fx - x, fz - z)
    if (d < best.distM) best = { index: i, t, x: fx, z: fz, distM: d }
  }
  return best
}

/**
 * THE MIRROR OF ONE WATER AREA AT ONE POINT — the editor's twin of
 * `heightfield.water_level_at` and of `client3d`'s
 * `waterPlaneMath.waterLevelAt` (W4a, § A16.3 nr. 2).
 *
 * THREE IMPLEMENTATIONS OF ONE FUNCTION, and this is the third; they answer
 * the same number or the admin preview draws a river the bake did not carve.
 * The rule is two lines:
 *
 *     s     = arc coordinate of the NEAREST point on the axis polyline
 *             (every segment projected with a clamp, shortest distance wins)
 *     level = linear between the two knots s falls between, CLAMPED at both
 *             ends of the line
 *
 * The projection is `nearestOnPolyline` above — the same routine the journey
 * overlay uses, not a second copy of it, down to the tie rule (an exact tie
 * goes to the EARLIER segment, `<` and never `<=`, which is what the server's
 * loop does too).
 *
 * BOTH OLDER LAWS ARE SPECIAL CASES, not branches beside it: still water is
 * ONE knot, so the nearest point is that knot and the clamp answers its level
 * everywhere; a straight river is TWO knots at the axis extremes, so the
 * projection onto that single segment IS W1's `clamp((s − s_min)/span, 0, 1)`.
 *
 * THE CLAMP IS LOAD-BEARING at both ends: the knots sit where the levels were
 * MEASURED (a cross-section median of the natural ground), and a point past
 * the last knot must not read past the level that measurement stands for.
 *
 * Hand-derived (§ B5a), the hairpin of `scripts/smoke_height_bake.py` [8k]:
 * knots A(150, 300) s = 0 level 10, B(249, 280) s = 101 level 8,
 * C(201, 260) s = 153 level 6.
 *
 *   (249, 280)   -> the middle knot itself, s = 101       -> 8.0
 *                   (the straight W1 chord A→C would answer 6.0: the bend
 *                   projects PAST its own downstream end)
 *   (199.5, 290) -> midpoint of the first leg, s = 50.5   -> 9.0
 *   (225, 270)   -> midpoint of the second leg, s = 127   -> 7.0
 *   (100, 300)   -> 50 m upstream of A, foot clamps to A  -> 10.0
 */
export function waterLevelAt(profile: TerrainWaterProfile,
  x: number, z: number): number {
  const axis = profile.axis
  if (!axis.length) return profile.level_up
  if (axis.length < 2) return axis[0][3]
  const foot = nearestOnPolyline(axis.map((k) => [k[0], k[1]]), x, z)
  if (!foot) return axis[0][3]
  const a = axis[foot.index]
  const b = axis[Math.min(foot.index + 1, axis.length - 1)]
  const s = a[2] + (b[2] - a[2]) * foot.t
  return axisLevelAt(axis, s)
}

/** The level of an axis at arc coordinate `s`, linear between the knots and
 *  clamped at both ends — the inner half of `waterLevelAt`, split out because
 *  it is the half the server states as its own rule. A one-knot axis answers
 *  its own level: its `s` is both the first and the last. */
function axisLevelAt(axis: readonly TerrainWaterKnot[], s: number): number {
  if (s <= axis[0][2]) return axis[0][3]
  const last = axis[axis.length - 1]
  if (s >= last[2]) return last[3]
  for (let i = 1; i < axis.length; i++) {
    const [, , aS, aLevel] = axis[i - 1]
    const [, , bS, bLevel] = axis[i]
    if (s <= bS) {
      const span = bS - aS
      if (span <= 1e-12) return bLevel
      return aLevel + (bLevel - aLevel) * ((s - aS) / span)
    }
  }
  return last[3]
}

/**
 * WHICH WAY THE WATER RUNS AT ONE POINT — the unit tangent of the axis segment
 * nearest to it, `[0, 0]` where there is no flow (W4a).
 *
 * The counterpart of `waterLevelAt` and the same walk: the nearest segment
 * decides, so a point beside a bend reads the leg it is beside, not the chord
 * of the whole river. It is what the ripples scroll along in the 3D client
 * (`aWaterFlow`, per vertex) and what the map preview's arrows point at —
 * derived from the SAME knots, so the picture and the water agree.
 *
 * Still water is `[0, 0]` and not some default bearing: a lake has no
 * downstream, and a zero is what every consumer already reads as "no flow".
 *
 * Hand-derived on the hairpin above: at (199.5, 290) the first leg carries it,
 * (99, −20)/101 = (0.980198, −0.198020); at (225, 270) the second,
 * (−48, −20)/52 = (−0.923077, −0.384615). Exactly ON the middle knot both legs
 * are equally near and the EARLIER one wins, so the answer there is the first
 * leg's tangent — the tie rule of `nearestOnPolyline`, which is the server's.
 */
export function waterFlowAt(profile: TerrainWaterProfile | null | undefined,
  x: number, z: number): [number, number] {
  const axis = profile?.axis
  if (!axis || axis.length < 2) return [0, 0]
  const foot = nearestOnPolyline(axis.map((k) => [k[0], k[1]]), x, z)
  if (!foot) return [0, 0]
  const i = Math.min(foot.index, axis.length - 2)
  const dx = axis[i + 1][0] - axis[i][0]
  const dz = axis[i + 1][1] - axis[i][1]
  const len = Math.hypot(dx, dz)
  if (!(len > 1e-9)) return [0, 0]
  return [dx / len, dz / len]
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

/**
 * Does a polygon's bounding box touch a world rectangle?
 *
 * The cheap half of a visibility test, and deliberately only that: it feeds a
 * LIST filter (which painted areas are worth offering for the part of the
 * world on screen), never a hit test. An AABB that overlaps while the shape
 * itself misses costs one extra row; a true polygon-rectangle intersection
 * would cost a clip per area on every pan and buy nothing a reader notices.
 * Which area a CLICK hit stays `pointInPolygon`'s question.
 *
 * Touching counts as overlap (`>=` / `<=`): an area whose edge sits exactly on
 * the screen border is drawn on that border and belongs in the list with it.
 * An empty polygon encloses nothing and is never in view — and because the
 * extent is built by comparison, a non-finite coordinate leaves it inverted
 * and fails closed the same way.
 *
 * The rectangle is taken as given: `visibleWorldRect` always returns
 * `min <= max`, and a box handed in the other way round matches nothing rather
 * than being quietly repaired.
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots), all
 * against rect {min_x: 0, min_z: 0, max_x: 100, max_z: 50}:
 *
 *   [(10,10),(20,10),(20,20)]            -> true   bbox x 10…20, z 10…20: inside
 *   [(-50,-50),(-40,-50),(-40,-40)]      -> false  bbox max_x −40 < 0
 *   [(-10,-10),(110,-10),(110,60),(-10,60)]
 *                                        -> true   encloses the rect entirely
 *   [(100,50),(120,50),(120,70)]         -> true   corner touches at (100,50)
 *   [(100.01,50),(120,50),(120,70)]      -> false  min_x 100.01 > max_x 100
 *   [(-20,20),(120,20),(120,30),(-20,30)]-> true   crosses the rect west→east
 *   [(40,-30),(60,-30),(60,-10),(40,-10)]-> false  bbox max_z −10 < 0
 *   []                                   -> false  no points, no extent
 */
export function areaInRect(polygon: Array<[number, number]>,
  rect: MapBounds): boolean {
  if (!polygon.length) return false
  let minX = Infinity
  let maxX = -Infinity
  let minZ = Infinity
  let maxZ = -Infinity
  for (const [x, z] of polygon) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  return maxX >= rect.min_x && minX <= rect.max_x
    && maxZ >= rect.min_z && minZ <= rect.max_z
}

/** A join is bevelled once the miter would stick out further than this many
 *  stroke widths — 2 widths means only a near-hairpin (turn > 151°) bevels. */
export const STROKE_MITER_LIMIT_WIDTHS = 2

/** Two stroke points closer than this are the same click, not a segment. */
const STROKE_EPS = 1e-9

/** Metres are stored with 2 decimals (server side), so the ribbon rounds too.
 *  The `+ 0` normalizes −0 to 0 — otherwise a mirrored side produces "-0",
 *  which `===` calls equal but JSON writes out as a different number. */
const round2 = (v: number): number => Math.round(v * 100) / 100 + 0

/** How a centre line is BENT before it is widened. `straight` is the line as
 *  clicked; the other two hang deflections off it, so a river bank or a forest
 *  edge stops looking like a ruler. */
export type StrokeStyle = 'straight' | 'jagged' | 'wavy'

/** The styles in the order the toolbar offers them — straight first, because
 *  that is what the tool did before and still does by default. */
export const STROKE_STYLES: readonly StrokeStyle[] = ['straight', 'jagged', 'wavy']

/** Is this one of the three? Anything else — a foreign `meta.stroke`, a client
 *  that knows a style this one does not — is read as the straight line the
 *  polygon was generated from, never guessed at. */
export function isStrokeStyle(value: unknown): value is StrokeStyle {
  return typeof value === 'string'
    && (STROKE_STYLES as readonly string[]).includes(value)
}

/** What a line's decoration is set to: the toolbar's setting for the next
 *  line, the stored recipe's for one that already exists. */
export interface StrokeDeco {
  style: StrokeStyle
  spacingM: number
  amplitudeM: number
}

/**
 * Points a DECORATED centre line may end up with.
 *
 * The budget is the server's 256-point polygon limit, counted where it is
 * actually spent: a mitred ribbon is `2n` points wide (`strokeToPolygon`), so
 * 120 centre points make a 240-point outline — the safety distance under 256
 * the plan asks for. Cap the centre line at 240 instead and every dense line
 * would generate a 480-point polygon and be refused on save, which is not a
 * cap but a wall.
 *
 * It is a bound on the MITRED case, and deliberately only that: deflections
 * sharp enough to bevel add two points per join, and such a line overruns 256
 * the way any hairpin chain already does — `MapTab.strokePolygon` refuses it
 * with the count in the message.
 */
export const MAX_DECORATED_POINTS = 120

/** The smallest deflection, as a fraction of the amplitude. Deflections have
 *  random size (that is what keeps them from reading as a pattern), but one of
 *  nearly zero is a kink nobody drew — the field says how far the line swings,
 *  not how far its biggest swing goes. */
const DEFLECTION_MIN_FACTOR = 0.4

/** Deflections per full wave of the `wavy` style. Four samples per period is
 *  the coarsest a sine still reads as a curve rather than as a zigzag, and it
 *  keeps ONE spacing field meaning the same thing in both styles: how far
 *  apart the deflections sit. */
const WAVE_SPACINGS_PER_PERIOD = 4

/** The seed of one decoration — the clicked line itself, so the same stroke
 *  drawn twice gets the same spikes, and no two lines share a pattern. Fed to
 *  `seededRandom` (@anima/scene-render), the ONE PRNG of this repo. */
export function strokeSeed(points: Array<[number, number]>): string {
  let s = 'terrain:stroke'
  for (const p of points) s += `:${p?.[0]},${p?.[1]}`
  return s
}

/** A decorated centre line, plus what had to be given up to fit the budget. */
export interface DecoratedStroke {
  /** The line as `strokeToPolygon` should read it: the clicked points with the
   *  deflections woven in, in walking order. */
  points: Array<[number, number]>
  /** The spacing actually used — larger than the one asked for when the cap
   *  below thinned the deflections out. */
  spacingM: number
  /** `MAX_DECORATED_POINTS` raised the spacing. The toolbar says so; silently
   *  drawing something coarser than the field claims would be a lie. */
  capped: boolean
}

/**
 * Bend a clicked centre line — the step BEFORE `strokeToPolygon`.
 *
 * A pure function of its arguments: the same line, style and numbers give the
 * same points, always, in every client. The randomness is seeded from the
 * clicked points themselves (`strokeSeed`), so redrawing the same line gives
 * the same river and dragging one of its points reshapes the whole pattern —
 * which is what dragging a point of a hand-drawn line looks like anyway.
 *
 * The deflections sit at arc length `spacing/2`, `3·spacing/2`, … along the
 * line, each one pushed sideways along the local unit normal `(dz, −dx)` —
 * side A of `strokeToPolygon`, the same convention, so nothing here invents a
 * second idea of "sideways". How far, and to which side:
 *
 *   jagged — alternating sides, so the deflections form a triangle wave, with
 *            each spike's height drawn at random from
 *            `[0.4·amplitude, amplitude]`.
 *   wavy   — a sine of random phase over the same random heights: the same
 *            deflections, following a curve instead of a zigzag.
 *
 * The phase is drawn FIRST and in both styles, so switching between them
 * leaves the heights alone and only changes the shape they are hung on.
 *
 * The clicked points all survive, in order — the decoration is woven between
 * them, never instead of them.
 *
 * Left unchanged, and returned as the very array it was given: the `straight`
 * style, a style this build does not know, a spacing or amplitude that is not
 * a positive number, a line with fewer than two distinct points or a
 * non-finite coordinate, and a line of zero length. A decoration that cannot
 * be computed is no decoration, never half of one.
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots),
 * `A` = amplitude, `m_i` = the random height of the i-th deflection:
 *
 *   [(0,0),(100,0)], jagged, spacing 10, A 2: length 100, deflections at
 *     5, 15, …, 95 -> 10 of them, 12 points in all. Segment direction (1,0)
 *     has normal (0,−1), so side A is NEGATIVE z and the sides alternate from
 *     there:
 *     [(0,0),(5,−m0),(15,m1),(25,−m2),…,(95,m9),(100,0)] with 0.8 <= m_i <= 2
 *   the same line, wavy: the same 10 positions and the same heights, the side
 *     given by sin(phase + i·π/2) instead — |z| <= 2 throughout, and NOT the
 *     alternating sequence above (which is what tells the two styles apart).
 *   [(0,0),(10,0),(10,10)], jagged, spacing 10, A 2: length 20, deflections at
 *     5 (on the first segment, normal (0,−1)) and 15 (on the second, direction
 *     (0,1), normal (1,0)) -> [(0,0),(5,−m0),(10,0),(10−m1,5),(10,10)]: the
 *     clicked corner (10,0) is still in there, between the two.
 *   [(0,0),(1000,0)], jagged, spacing 2, A 2: 500 deflections would be 502
 *     points, so the cap bites — room is 120 − 2 = 118 deflections, spacing
 *     becomes 1000/118 = 8.4745…, and 118 of them fit (the last at
 *     117.5 · 8.4745… = 995.76 < 1000): 120 points, `capped` true, and the
 *     240-point outline they generate is exactly the budget.
 *   [(0,0),(100,0)], jagged, spacing 10, A 0 -> the input array itself, since
 *     a deflection of no height is no deflection.
 *   [(0,0),(100,0)], straight, spacing 10, A 2 -> the input array itself.
 */
export function decorateStroke(points: Array<[number, number]>,
  style: StrokeStyle, spacingM: number, amplitudeM: number,
  seed: string = strokeSeed(points)): DecoratedStroke {
  const plain: DecoratedStroke = { points, spacingM, capped: false }
  if (style !== 'jagged' && style !== 'wavy') return plain
  if (!Number.isFinite(spacingM) || spacingM <= 0) return plain
  if (!Number.isFinite(amplitudeM) || amplitudeM <= 0) return plain

  // 1. the line as the ribbon builder will read it: finite, no repeated click.
  const line: Array<[number, number]> = []
  for (const p of points) {
    if (!p || p.length < 2) return plain
    const [x, z] = p
    if (!Number.isFinite(x) || !Number.isFinite(z)) return plain
    const prev = line[line.length - 1]
    if (prev && Math.abs(prev[0] - x) < STROKE_EPS
      && Math.abs(prev[1] - z) < STROKE_EPS) continue
    line.push([x, z])
  }
  if (line.length < 2) return plain

  // 2. where each clicked point sits along the line, and how long it is.
  const cum = [0]
  for (let i = 1; i < line.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(line[i][0] - line[i - 1][0],
      line[i][1] - line[i - 1][1]))
  }
  const total = cum[cum.length - 1]
  if (!(total > 0)) return plain

  // 3. the budget (see MAX_DECORATED_POINTS): the clicked points are already
  //    spent, the rest is what the deflections may take. Asking for more
  //    thins them out — the line still gets its style, at the density that
  //    fits, and `capped` says the field's number is not the one drawn.
  const room = MAX_DECORATED_POINTS - line.length
  if (room <= 0) return { points: line, spacingM, capped: true }
  let spacing = spacingM
  let capped = false
  if (spacing < total / room) {
    spacing = total / room
    capped = true
  }

  // 4. walk the line and weave the two lists together.
  const rnd = seededRandom(seed)
  const phase = rnd() * Math.PI * 2
  const out: Array<[number, number]> = [line[0]]
  let seg = 1
  let i = 0
  for (let d = spacing / 2; d < total - STROKE_EPS; d += spacing, i++) {
    // Every clicked point the walk has passed goes in before the deflection.
    while (seg < line.length - 1 && cum[seg] <= d) {
      out.push(line[seg])
      seg++
    }
    const [ax, az] = line[seg - 1]
    const [bx, bz] = line[seg]
    const len = cum[seg] - cum[seg - 1]
    const f = (d - cum[seg - 1]) / len
    const nx = (bz - az) / len
    const nz = -(bx - ax) / len
    const height = amplitudeM
      * (DEFLECTION_MIN_FACTOR + (1 - DEFLECTION_MIN_FACTOR) * rnd())
    const side = style === 'jagged'
      ? (i % 2 === 0 ? 1 : -1)
      : Math.sin(phase + (i * 2 * Math.PI) / WAVE_SPACINGS_PER_PERIOD)
    const off = height * side
    out.push([round2(ax + f * (bx - ax) + off * nx),
      round2(az + f * (bz - az) + off * nz)])
  }
  while (seg < line.length) {
    out.push(line[seg])
    seg++
  }
  return { points: out, spacingM: spacing, capped }
}

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
 *     ENDS at the last click instead of running past it. Sideways it does
 *     reach further: the ribbon is half a width wide on either side, and a
 *     miter join sticks out up to `STROKE_MITER_LIMIT_WIDTHS × widthM` beyond
 *     the corner it rounds. A stroke covers ground the user did not click on —
 *     that is the point of a width.
 *   - consecutive duplicate clicks are dropped BEFORE any direction is taken.
 *
 * Point count: `2n` with every join mitered, `+2` per bevelled join (both sides
 * bevel together — the limit is symmetric), i.e. `2n + 2b`, worst case `4n − 4`
 * when EVERY join bevels. Callers must size the RESULT against the server's
 * 256-point polygon limit — the click count alone does not bound it.
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

  // 2. per-segment side-A normal (dz, −dx), unit length. The direction itself
  //    is never needed on its own — the normal carries it.
  const nrm: Array<[number, number]> = []
  for (let i = 1; i < line.length; i++) {
    const dx = line[i][0] - line[i - 1][0]
    const dz = line[i][1] - line[i - 1][1]
    const len = Math.hypot(dx, dz)
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

/* ==========================================================================
 * THE SCATTER PREVIEW — true density in the window, a thinned overview beyond
 *
 * WHAT WENT WRONG (reported 2026-08-20). "The preview and the 3D client
 * disagree hard — the client shows far more." True by construction: since the
 * world's scatter became a camera window of 64 m cells the CLIENT plants the
 * AUTHORED density (`scatterCellInstances`, uncapped per area), while this
 * preview drew a budget-thinned sample of the WHOLE painted shape. The RATIO
 * between two areas was right; the absolute density was silently a fraction of
 * the world's, with nothing on screen saying so.
 *
 * THE ANSWER IS THE CELL RASTER, WHERE THE USER LOOKS. When an area's TRUE
 * instance count fits a frame budget, the preview enumerates the covered CELLS
 * and draws the very instances the client plants — same cell seeds, same ring,
 * same footprints, same occluders, so the two pictures are one picture
 * (§ B5a: pinned numerically in `scripts/smoke_scatter_preview.mjs`, never by
 * comparing screenshots).
 *
 * Beyond that budget the thinned whole-area sample stays — a world of dense
 * meadows is millions of props and no browser draws them — but it now SAYS
 * what it is, with the percentage of the authored density it managed to show.
 * A preview that lies quietly is the defect; a preview that says "this is
 * 0.06 % of what grows, zoom in" is a scale, which is the same doctrine the
 * canvas' metre grid and its 1.70 m figure follow.
 *
 * THE MODE IS AN AREA'S OWN (reported 2026-08-20, and this is the second half
 * of the same defect). "The map draws 17 dots in my forest; the 3D client puts
 * well over two hundred trees there." Both were right. The wood is 89 646 m2
 * with two rows at 5 per 100 m2, i.e. 8 964 authored trees, and the client
 * plants 8 576 of them (the ring filter and the areas painted over it take the
 * rest) — one tree per 10 m2, which is what the author asked for. The preview
 * drew 16 of those 8 964, because the mode was decided ONCE for the whole
 * screen and the same viewport also held a 14.2 km2 deep forest of 2 005 260
 * props. That sum is over any frame budget from any zoom, so the wood was
 * thinned at EVERY zoom — its share of a 4 000-dot budget is 2·8 = 16 dots,
 * 0.18 % — and true density was unreachable for it at every scale that still
 * showed it whole.
 *
 * So the decision moved onto the AREA (`scatterAreaCosts`, `scatterAreaPlan`).
 * An area whose own bound fits `SCATTER_AREA_TRUE_MAX` draws every instance
 * exactly, whatever monsters share its viewport; the ones over it are thinned
 * and say so on their own ground (`scatterThinnedByArea` badges). A sum guard
 * (`SCATTER_TRUE_TOTAL`) still protects the frame, by demoting the LARGEST
 * areas first — the order that leaves the most areas exact.
 * ========================================================================== */

/**
 * How the OVERVIEW's dot budget is split over the entries that want dots —
 * PROPORTIONALLY, never first-come-first-served.
 *
 * THE BUG THIS REPLACES (reported 2026-08-19). The preview used to sample area
 * after area and simply stop once it had drawn its ceiling of dots. On a world
 * whose first painted wood is large enough, that ceiling is reached inside
 * that ONE area and every area behind it is drawn with no scatter at all —
 * which looks exactly like "the second forest grows nothing". Measured on the
 * reporting world: a 13.71 km2 deep forest with 7 entries plants 14 000 props,
 * so its first two entries (2 000 each, the sampler's per-entry ceiling)
 * exhausted a 4 000-dot budget and the SECOND deep forest, the meadow and the
 * grass patch behind it got 0 dots between them.
 *
 * THE SPLIT. `wanted[i]` is what entry i really plants
 * (`scatterWantedCount`, the sampler's own count). While the sum fits in
 * `budget`, everything is drawn as it stands. Above it every entry keeps its
 * SHARE of the budget,
 *
 *     share_i = max(1, floor(wanted_i · budget / Σ wanted))
 *
 * so the dots stay proportional to what actually grows — a wood with ten times
 * the props of the meadow next to it still draws ten times the dots — and the
 * `max(1, …)` is the promise that no scattering area is left blank: an entry
 * whose proportional share rounds below one dot still gets one, which is what
 * makes "does this area scatter at all?" answerable by looking.
 *
 * The total may therefore exceed `budget` by at most one dot per such starved
 * entry (8 entries per area is the server's ceiling), which is a handful of
 * SVG nodes against a limit that exists to stop tens of thousands.
 *
 * The shares go into `scatterInstances` as `maxPoints`, where a lower ceiling
 * yields the PREFIX of the same stream — so every previewed dot is a prop the
 * world really plants, not a second sample that happens to look similar.
 *
 * Hand-derived cases live in `scripts/smoke_scatter_preview.mjs`.
 */
export function scatterPreviewShares(wanted: readonly number[],
  budget: number): number[] {
  const counts = wanted.map((n) => (Number.isFinite(n) && n > 0 ? Math.floor(n) : 0))
  const cap = Number.isFinite(budget) && budget > 0 ? Math.floor(budget) : 0
  const total = counts.reduce((sum, n) => sum + n, 0)
  if (cap <= 0) return counts.map(() => 0)
  if (total <= cap) return counts
  return counts.map((n) => (n > 0 ? Math.max(1, Math.floor((n * cap) / total)) : 0))
}

/** Dots the THINNED overview draws at most, over all areas together — the
 *  ceiling `scatterPreviewShares` spends. It caps SVG NODES, not props: the
 *  points are the world's own either way. */
export const SCATTER_PREVIEW_MAX = 4000

/** Dots ONE AREA may draw at true density — the budget its own mode switch is
 *  measured against.
 *
 *  Higher than the overview's ceiling because these dots are the point: in
 *  this mode every one of them is an instance the 3D client really plants, so
 *  the number is what one AREA is allowed to cost, not what a sample may
 *  spend. Twelve thousand circles is a browser's comfortable frame, and it is
 *  deliberately above the ~9 000 props of a 9-hectare wood at ten per 100 m2 —
 *  a hand-painted forest is exactly the thing an author needs to see whole. */
export const SCATTER_AREA_TRUE_MAX = 12000

/** …and what EVERY true-density area may draw together. The per-area cap alone
 *  says nothing about a screen with five woods on it, so the sum is guarded
 *  too — by demoting the LARGEST areas to the thinned sample first, which is
 *  the order that keeps the most areas exact. */
export const SCATTER_TRUE_TOTAL = 16000

/** HYSTERESIS around those budgets, so a pan or a wheel notch at the boundary
 *  cannot flap an area between its two pictures frame after frame: true
 *  density switches ON below `cap · 0.8` and back OFF only above `cap · 1.2`.
 *  In between whatever mode that area is running stays running. */
export const SCATTER_TRUE_ON = 0.8
export const SCATTER_TRUE_OFF = 1.2

/**
 * One entry of one area, with everything BOTH preview modes need — collected
 * once per data change, because neither mode may re-clean a ring or re-measure
 * an area on a pan.
 *
 * `wanted` is the entry's TRUE prop count over the whole painted shape
 * (`A · d / 100`, no ceiling); `perCell` is what one full 64 m cell of it
 * carries. The first is what the overview's share budget is split by, the
 * second what the window's cost is counted in — and both come from the ONE
 * shared count rule (`scatterWantedCount`), so no mode can disagree with the
 * world about how thick the ground is.
 */
export interface ScatterPreviewJob {
  /** the area this row belongs to — half of every cell seed */
  areaId: string
  /** the row's index in `meta.scatter` — the other half, and the dot colour */
  index: number
  /** the CLEANED world ring of the area */
  ring: Point2[]
  /** its bounding box in world metres, `[minX, minZ, maxX, maxZ]` */
  box: [number, number, number, number]
  /** enclosed ground, m2 */
  areaM2: number
  /** the cleaned rings of every area painted ABOVE this one */
  occluders: Point2[][]
  /** instances per 100 m2, as authored */
  density: number
  /** the instance's horizontal half-extent (`scatterClearM`) — the ESTIMATE,
   *  see `scatterPreviewJobs` */
  clearM: number
  /** true props over the whole area, uncapped */
  wanted: number
  /** …and over one full cell (`SCATTER_MAX_PER_CELL` guarded) */
  perCell: number
}

/**
 * Every scattering row of every area, ready to draw — the shared half of the
 * two modes.
 *
 * `areas` arrives BOTTOM TO TOP (the server's `z_order` order), so an area's
 * occluders are the rings after its own index: only the ground an area
 * actually SHOWS is scattered, on the map exactly as in the world.
 *
 * THE ONE APPROXIMATION IN HERE, and it is the one this preview has always
 * made: the dots have no mesh to measure, so a prop is assumed to be as wide
 * as it is tall (`scatterClearM` with no measured extent) when it is kept
 * clear of a placed location. The 3D client measures the loaded geometry and
 * clears a little differently for very slim or very wide props — a handful of
 * instances at the rim of a footprint, never a different density.
 */
export function scatterPreviewJobs(areas: readonly TerrainArea[]
): ScatterPreviewJob[] {
  const rings = areas.map((a) => cleanRing(a.polygon))
  const jobs: ScatterPreviewJob[] = []
  areas.forEach((a, ai) => {
    const entries = readScatter(a.meta)
    if (!entries.length) return
    const ring = rings[ai]
    if (ring.length < 3) return
    const areaM2 = polygonArea(ring)
    const occluders = rings.slice(ai + 1).filter((r) => r.length >= 3)
    let minX = Infinity
    let minZ = Infinity
    let maxX = -Infinity
    let maxZ = -Infinity
    for (const [x, z] of ring) {
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (z < minZ) minZ = z
      if (z > maxZ) maxZ = z
    }
    entries.forEach((e, i) => {
      // Arithmetic, not a sample: what this row plants follows from the area
      // and the density alone, and both modes have to know it before the first
      // point is drawn. NO CEILING on the area count — `SCATTER_MAX_PER_ENTRY`
      // would flatten every large area to the same 2 000, which is the very
      // defect that made a 13.7 km2 wood and a 0.84 km2 wood look 14 times
      // apart.
      const wanted = scatterWantedCount(areaM2, e.density_per_100m2, Infinity)
      if (wanted < 1) return
      jobs.push({
        areaId: a.id,
        index: i,
        ring,
        box: [minX, minZ, maxX, maxZ],
        areaM2,
        occluders,
        density: e.density_per_100m2,
        clearM: scatterClearM(Number(e.height_m) > 0 ? Number(e.height_m)
          : (e.model ? 2 : 0.8)),
        wanted,
        // The window's unit of cost — the count the CELL sampler asks for,
        // from the same rule and with the same per-cell guard it applies.
        perCell: scatterWantedCount(SCATTER_CELL_M * SCATTER_CELL_M,
          e.density_per_100m2, SCATTER_MAX_PER_CELL),
      })
    })
  })
  return jobs
}

/** What one screen of TRUE density would cost: the instances the cell sampler
 *  would draw, and the cells it would have to walk to draw them. */
/** What true density would cost for ONE area, and the number its mode is
 *  judged by. */
export interface ScatterAreaCost {
  areaId: string
  /** candidate instances over every row of this area inside the window — an
   *  UPPER bound on the dots, since the ring filter, the occluders and the
   *  footprints only ever subtract from it. It is a LOOSE bound: partial cells
   *  are counted at their FULL density, so an area whose polygon fills half of
   *  its own bounding box is estimated at roughly twice what it draws. */
  windowDots: number
  /** cells enumerated, summed over the rows (two rows of one area walk the
   *  same cells twice, and pay for them twice) */
  cells: number
  /** what this area really plants on its WHOLE painted shape, Σ over its rows
   *  (`A · d / 100`, exact arithmetic, no window and no estimate) */
  wanted: number
  /**
   * THE NUMBER THE MODE HANGS ON: `min(wanted, windowDots)`.
   *
   * Both halves are needed and each is wrong alone. `windowDots` alone tells
   * an author looking at a whole 9-hectare wood that it costs 25 830 dots when
   * it draws 8 576 — the bounding box of a concave polygon is mostly not the
   * polygon, and every rim cell is charged in full. `wanted` alone tells
   * someone zoomed into four cells of a 14 km2 deep forest that it costs two
   * million, when the window they are looking at holds 2 312.
   *
   * The smaller of the two is a bound on both counts at once, and it is tight
   * exactly where each of them is: the whole area in view, and a small window
   * of a huge one.
   */
  bound: number
  /** the arithmetic mean of the area's ring — where its badge hangs */
  cx: number
  cz: number
}

/**
 * What true density would cost PER AREA for the world rectangle `rect` —
 * WITHOUT sampling a single point.
 *
 * Per row: the visible rectangle is clipped against the area's own bounding
 * box, the cells of what is left are COUNTED (`scatterCellCountInBox`, index
 * arithmetic — no list is built), and each of them carries `perCell`
 * candidates. That is the same product the sampler will actually run, so the
 * mode switch below is measured in the currency it spends.
 *
 * PER AREA AND NOT PER SCREEN, which is the whole of the 2026-08-20 round.
 * A single global sum is decided by whatever the biggest painted shape in the
 * viewport happens to be: on the reporting world a 14 km2 deep forest costs
 * two million candidates from any zoom that shows a useful amount of map, so
 * the 9-hectare wood beside it was drawn thinned to 16 dots of its 8 964 trees
 * — 0.18 % — at EVERY zoom, with no way to reach the true picture. An area's
 * own cost cannot be pushed over a budget by its neighbours.
 *
 * The rows are grouped by `areaId` and the result keeps the AREAS' order of
 * first appearance, which is the server's bottom-to-top paint order.
 *
 * An area the rectangle does not reach costs nothing at all (and is left in
 * the list with `bound` 0, so a caller can still see it): true density over an
 * empty window enumerates nothing and draws nothing, which is the correct
 * picture of ground nobody is looking at.
 */
export function scatterAreaCosts(jobs: readonly ScatterPreviewJob[],
  rect: MapBounds): ScatterAreaCost[] {
  const order: string[] = []
  const by = new Map<string, ScatterAreaCost>()
  for (const job of jobs) {
    let cost = by.get(job.areaId)
    if (!cost) {
      let x = 0
      let z = 0
      for (const [px, pz] of job.ring) { x += px; z += pz }
      const n = job.ring.length || 1
      cost = {
        areaId: job.areaId,
        windowDots: 0,
        cells: 0,
        wanted: 0,
        bound: 0,
        cx: x / n,
        cz: z / n,
      }
      by.set(job.areaId, cost)
      order.push(job.areaId)
    }
    cost.wanted += job.wanted
    const [bMinX, bMinZ, bMaxX, bMaxZ] = job.box
    const minX = Math.max(rect.min_x, bMinX)
    const minZ = Math.max(rect.min_z, bMinZ)
    const maxX = Math.min(rect.max_x, bMaxX)
    const maxZ = Math.min(rect.max_z, bMaxZ)
    if (maxX < minX || maxZ < minZ) continue
    const n = scatterCellCountInBox(minX, minZ, maxX, maxZ)
    if (n <= 0) continue
    cost.cells += n
    cost.windowDots += n * job.perCell
  }
  const out = order.map((id) => by.get(id) as ScatterAreaCost)
  for (const cost of out) cost.bound = Math.min(cost.wanted, cost.windowDots)
  return out
}

/** Which areas the next frame draws at true density and which it thins — both
 *  in the areas' own (paint) order, so a caller can split its rows by a
 *  lookup and keep the list order it was handed. */
export interface ScatterAreaPlan {
  trueIds: string[]
  thinnedIds: string[]
}

/**
 * THE MODE, PER AREA — the rule on its own, with its hysteresis.
 *
 * THREE LIMITS, and they are limits of different kinds.
 *
 * The per-area DOT budget (`SCATTER_AREA_TRUE_MAX`) is a comfort limit and
 * therefore hysteretic (`SCATTER_TRUE_ON` / `SCATTER_TRUE_OFF`): drawing a few
 * thousand circles more for one wheel notch costs a slower frame and nothing
 * else, but flapping between two pictures at the boundary is unreadable.
 *
 * The CELL count is a hard one: past `SCATTER_CELLS_MAX` the shared enumerator
 * answers an empty list, so an area over it would be drawn as NOTHING. It gets
 * a one-sided band instead — entered only well under the cap, left the moment
 * the cap itself is reached.
 *
 * The TOTAL (`SCATTER_TRUE_TOTAL`) is the guard the per-area cap cannot give:
 * five woods that each fit may not fit together. It demotes the LARGEST
 * bound first and stops as soon as the sum fits, which keeps the most areas
 * exact — and it is the big one that has the least to lose, since a thinned
 * sample of 12 000 props still shows its shape while a thinned sample of 300
 * is a handful of dots. Ties fall to the area that comes later in the paint
 * order, so the answer never depends on `Array.prototype.sort` being stable.
 *
 * `wasTrue` is which areas the LAST frame drew truly — the only state, and it
 * is read, never written, here.
 */
export function scatterAreaPlan(costs: readonly ScatterAreaCost[],
  wasTrue: ReadonlySet<string>): ScatterAreaPlan {
  const candidates: ScatterAreaCost[] = []
  const thinned = new Set<string>()
  for (const cost of costs) {
    const on = wasTrue.has(cost.areaId)
    if (!Number.isFinite(cost.bound) || !Number.isFinite(cost.cells)) {
      thinned.add(cost.areaId)
      continue
    }
    if (cost.cells > SCATTER_CELLS_MAX * (on ? 1 : SCATTER_TRUE_ON)) {
      thinned.add(cost.areaId)
      continue
    }
    if (cost.bound > SCATTER_AREA_TRUE_MAX * (on ? SCATTER_TRUE_OFF : SCATTER_TRUE_ON)) {
      thinned.add(cost.areaId)
      continue
    }
    candidates.push(cost)
  }
  // The sum guard — largest bound first, later paint order first on a tie.
  let sum = candidates.reduce((s, c) => s + c.bound, 0)
  if (sum > SCATTER_TRUE_TOTAL) {
    const pos = new Map(costs.map((c, i) => [c.areaId, i]))
    const biggest = [...candidates].sort((a, b) => (b.bound - a.bound)
      || ((pos.get(b.areaId) as number) - (pos.get(a.areaId) as number)))
    for (const cost of biggest) {
      if (sum <= SCATTER_TRUE_TOTAL) break
      thinned.add(cost.areaId)
      sum -= cost.bound
    }
  }
  return {
    trueIds: costs.filter((c) => !thinned.has(c.areaId)).map((c) => c.areaId),
    thinnedIds: costs.filter((c) => thinned.has(c.areaId)).map((c) => c.areaId),
  }
}

/** One previewed prop: where it stands and WHICH ROW of its area grew it (the
 *  dot's colour, `TerrainLayer.scatterColor`). */
export interface ScatterDot {
  x: number
  z: number
  /** the row's index in `meta.scatter` */
  entry: number
}

/**
 * THE TRUE-DENSITY PREVIEW: the very instances the 3D client plants, over the
 * cells the rectangle covers.
 *
 * Every point in here comes out of `scatterCellInstances` with the CELL seed
 * (`scatterCellSeed(areaId, row, cx, cz)`), the area's cleaned ring as the
 * filter, the occluders above it and the same footprint clearance — i.e. the
 * identical call `client3d/src/scene/ground.ts buildScatter` makes for the
 * same cell. The two windows differ (a camera square there, a viewport here);
 * the CELLS do not, and a cell is the whole unit of the raster, so wherever
 * the two overlap they are the same props to the metre.
 *
 * Cells are enumerated per area and only inside its own bounding box, so a
 * viewport over empty ground walks nothing.
 */
export function scatterWindowDots(jobs: readonly ScatterPreviewJob[],
  rect: MapBounds, footprints: readonly ScatterFootprint[]): ScatterDot[] {
  const out: ScatterDot[] = []
  for (const job of jobs) {
    const [bMinX, bMinZ, bMaxX, bMaxZ] = job.box
    const minX = Math.max(rect.min_x, bMinX)
    const minZ = Math.max(rect.min_z, bMinZ)
    const maxX = Math.min(rect.max_x, bMaxX)
    const maxZ = Math.min(rect.max_z, bMaxZ)
    if (maxX < minX || maxZ < minZ) continue
    for (const [cx, cz] of scatterCellsInBox(minX, minZ, maxX, maxZ)) {
      for (const p of scatterCellInstances({
        ring: job.ring,
        cx,
        cz,
        densityPer100m2: job.density,
        seed: scatterCellSeed(job.areaId, job.index, cx, cz),
        footprints,
        clearM: job.clearM,
        occluders: job.occluders,
      })) out.push({ x: p.x, z: p.z, entry: job.index })
    }
  }
  return out
}

/** An APPROXIMATED area, as its own badge: where to hang it, how many dots it
 *  got and how many props those stand for. The text is
 *  `scatterThinnedPercentText(drawn, wanted)` — the layer writes it, this is
 *  the arithmetic behind it. */
export interface ScatterAreaBadge {
  areaId: string
  /** the arithmetic mean of the area's ring, in world metres */
  x: number
  z: number
  /** dots this area really got */
  drawn: number
  /** …of the props it really plants */
  wanted: number
}

/** The thinned half of a mixed picture: its dots, and one badge per area that
 *  had to be approximated. */
export interface ScatterThinnedDraw {
  dots: ScatterDot[]
  badges: ScatterAreaBadge[]
}

/**
 * THE OVERVIEW PREVIEW: the given areas' scatter, thinned to `budget` dots
 * proportionally (`scatterPreviewShares`), with ONE BADGE PER AREA saying what
 * fraction of it that is.
 *
 * Every dot is still a prop the sampler really places — a lower `maxPoints`
 * yields the PREFIX of the same stream — and the ratio between two areas is
 * the ratio of what grows on them. What it is NOT is the world's density.
 *
 * THE BADGE IS PER AREA AND NOT PER SCREEN (2026-08-20). One label in the
 * corner could only ever report the whole picture, and since the modes became
 * an area's own business a picture is routinely MIXED: an exact wood beside an
 * approximated deep forest. A single "~0.2 %" over both is then wrong about
 * one of them and unattributable for the other, so the number moved onto the
 * ground it is about. An area drawn exactly carries no badge at all — nothing
 * was approximated, so there is nothing to say.
 *
 * The badge counts the dots that were really PLACED, not the share that was
 * asked for: the footprints and the covering areas subtract, and a preview
 * that reports the request would overstate itself against a building.
 */
export function scatterThinnedByArea(jobs: readonly ScatterPreviewJob[],
  footprints: readonly ScatterFootprint[],
  budget: number = SCATTER_PREVIEW_MAX): ScatterThinnedDraw {
  const shares = scatterPreviewShares(jobs.map((j) => j.wanted), budget)
  const dots: ScatterDot[] = []
  const order: string[] = []
  const by = new Map<string, ScatterAreaBadge>()
  jobs.forEach((job, i) => {
    let badge = by.get(job.areaId)
    if (!badge) {
      let x = 0
      let z = 0
      for (const [px, pz] of job.ring) { x += px; z += pz }
      const n = job.ring.length || 1
      badge = { areaId: job.areaId, x: x / n, z: z / n, drawn: 0, wanted: 0 }
      by.set(job.areaId, badge)
      order.push(job.areaId)
    }
    badge.wanted += job.wanted
    const share = shares[i]
    if (share < 1) return
    for (const p of scatterInstances({
      ring: job.ring,
      areaM2: job.areaM2,
      densityPer100m2: job.density,
      seed: scatterSeed(job.areaId, job.index),
      footprints,
      occluders: job.occluders,
      clearM: job.clearM,
      maxPoints: share,
    })) {
      dots.push({ x: p.x, z: p.z, entry: job.index })
      badge.drawn += 1
    }
  })
  return { dots, badges: order.map((id) => by.get(id) as ScatterAreaBadge) }
}

/** The dots of `scatterThinnedByArea` without its badges — the plain overview,
 *  kept because "what does this world thin to?" is a question about the dots
 *  alone (and the shape of `ScatterDot` is what the two modes share). */
export function scatterThinnedDots(jobs: readonly ScatterPreviewJob[],
  footprints: readonly ScatterFootprint[],
  budget: number = SCATTER_PREVIEW_MAX): ScatterDot[] {
  return scatterThinnedByArea(jobs, footprints, budget).dots
}

/**
 * WHAT FRACTION OF THE AUTHORED DENSITY the overview managed to draw, as the
 * text of the layer's label: `drawn / Σ wanted`, in percent.
 *
 * The scale of the number is the point, not its digits — on the reporting
 * world it is 3 995 dots against 6 282 498 props, i.e. 0.06 %, and "0.06"
 * says something "0" never could. So the precision follows the size: whole
 * percent from 10 up, one decimal from 1, two below that, and anything under a
 * hundredth of a percent is `<0.01` rather than a row of zeroes.
 *
 * `0` when nothing grows or nothing is drawn — a world without scatter has no
 * density to be a fraction of.
 */
export function scatterThinnedPercentText(drawn: number, wanted: number): string {
  const d = Number(drawn)
  const w = Number(wanted)
  if (!Number.isFinite(d) || !Number.isFinite(w) || d <= 0 || w <= 0) return '0'
  const p = (d / w) * 100
  if (p >= 10) return String(Math.round(p))
  if (p >= 1) return p.toFixed(1)
  if (p < 0.01) return '<0.01'
  return p.toFixed(2)
}
