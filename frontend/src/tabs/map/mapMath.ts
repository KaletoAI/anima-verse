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
import { seededRandom, worldToLocalXZ } from '@anima/scene-render'

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
 * The scatter preview's DOT BUDGET
 * ========================================================================== */

/**
 * How the preview's dot budget is split over the entries that want dots —
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
