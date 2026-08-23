/**
 * heightMath — the authoring arithmetic of the world relief (§ A16).
 *
 * Two questions about one authored ramp. The first, asked in two places (the
 * layer draws a warning glyph, the chip writes the sentence): is this ramp
 * steeper than a walker can climb? The second, drawn by the layer alone: WHERE
 * DOES THE RAMP END — see `rampCrestRing` at the foot of this file, which is
 * the bake's own inward distance rule turned into a line.
 *
 * The steepness question first.
 *
 * The server judges every reported step with TWO limits (§ A15 Nr. 8,
 * `app/core/relief.slope_blocks`) and both travel in the worldmap payload:
 *
 *   * `max_slope_deg` — the SLOPE, over every distance;
 *   * `max_step_height_m` — the STEP, on top of it, below one metre of
 *     horizontal travel (`relief.STEP_DISTANCE_M`).
 *
 * A height area's ramp has a CONSTANT gradient — it climbs the full height
 * over exactly `falloff_m` metres — so both limits become one number here:
 *
 *     gradient = |height_m| / falloff_m
 *     walkable while gradient <= min(tan(max_slope_deg),
 *                                    max_step_height_m / 1 m)
 *
 * THE STEP LIMIT IS USUALLY THE BINDING ONE, and leaving it out was a real
 * hole (review 2026-08-13): at the defaults it allows 0.4 m per metre against
 * the slope limit's tan 40° = 0.84, so a 5 m rise over 8 m passed as "walkable"
 * here while the server refused every report shorter than a metre — a figure
 * snapping back intermittently on a ramp the editor called fine. Short reports
 * are not exotic: they are what a walker sends when it stops, slides along an
 * obstacle or turns.
 *
 * IT IS A WARNING, NEVER A REFUSAL. A cliff is a legitimate thing to build (a
 * plateau one reaches through an opening, a ravine one is meant to walk
 * around); what is not legitimate is building one by accident.
 */

/** Below this horizontal distance a height change counts as a STEP — the
 *  mirror of `app/core/relief.STEP_DISTANCE_M` (and of `walk.ts`). */
export const STEP_DISTANCE_M = 1

/** Fallbacks for the two walk limits (§ A1.3) — the server's own defaults
 *  (`app/core/relief.DEFAULT_MAX_SLOPE_DEG` / `DEFAULT_MAX_STEP_M`), used
 *  until the worldmap payload has answered and on a server too old to send
 *  them. BOTH are needed where a RAMP is judged: the step limit is the binding
 *  one at these numbers (0.4 m per metre against tan 40° = 0.84), so warning
 *  on the slope alone would call ramps walkable that the server refuses.
 *
 *  They live HERE, next to the arithmetic that reads them, because two places
 *  ask the same question: the map editor's ramps and the terrain tab's micro
 *  relief. A second copy of the fallback is a second opinion about a server
 *  default, and the one that is not touched is the one that goes stale. */
export const DEFAULT_MAX_SLOPE_DEG = 40
export const DEFAULT_MAX_STEP_M = 0.4

/** The steepest gradient (metres of rise per metre of ground) a walker takes,
 *  from the two limits together. 0 when neither says anything usable. */
export function maxGradient(maxSlopeDeg: number, maxStepM: number): number {
  const bySlope = (Number.isFinite(maxSlopeDeg) && maxSlopeDeg > 0
    && maxSlopeDeg < 90)
    ? Math.tan((maxSlopeDeg * Math.PI) / 180)
    : Infinity
  const byStep = (Number.isFinite(maxStepM) && maxStepM > 0)
    ? maxStepM / STEP_DISTANCE_M
    : Infinity
  const g = Math.min(bySlope, byStep)
  return Number.isFinite(g) ? g : 0
}

/** The narrowest ramp this height may have and still be walkable, in metres.
 *  0 when nothing can be said (a flat area, or unusable limits). */
export function minFalloffFor(heightM: number, maxSlopeDeg: number,
  maxStepM: number): number {
  const h = Math.abs(heightM)
  if (!Number.isFinite(h) || h <= 0) return 0
  const g = maxGradient(maxSlopeDeg, maxStepM)
  if (!g) return 0
  return Math.round((h / g) * 100) / 100
}

/**
 * IS THE WORLD'S RELIEF GRID COARSER THAN NORMAL, and what does that cost?
 * (finding 14, 2026-08-13.)
 *
 * The step is nothing anybody sets: the server doubles it until the grid over
 * the whole painted extent fits inside its point budget
 * (`app/core/heightfield._step_for`). So ONE area drawn far out coarsens the
 * relief of the entire world — measured live, a 16 160 × 5 876 m union box
 * took the step from 4 m to 32 m — and the small hills of a 22 m patch, 8…12 m
 * wide, then have no support point left and vanish. Nothing said so.
 *
 * WHAT IT COSTS IS THE DISTANCE ALONE since v2 (§ A16.3). The relief is
 * delivered twice: this coarsenable grid as an OVERVIEW for the far view, and
 * 256 m tiles at the fine step for everything that decides — every walk rule
 * reads those, and so does the ground drawn around a character. The number
 * below is still worth saying, because a hill that vanishes from the picture is
 * a hill the author cannot see any more; it is no longer a hill the world
 * forgot. The wording carries that distinction.
 *
 * THE NUMBERS COME FROM THE SERVER, both of them (`GET /world/height-areas`
 * and the save answers carry `step_m` + `default_step_m`). This function does
 * not recompute the doubling — a second implementation of it is how a warning
 * starts naming a step the world does not have. All it does is the ONE piece
 * of arithmetic the sentence needs:
 *
 *     nothing under 2 × step survives      (NYQUIST — the same limit that
 *                                           clamps `relief_wave_m` at
 *                                           2 × the default step)
 *
 * `null` means "nothing to say": the finest grid, or numbers that say nothing.
 * An unusable `defaultStepM` is deliberately silent rather than alarming —
 * without it there is no "coarser than normal" to speak of.
 */
export function reliefStepNotice(stepM: number, defaultStepM: number
): { stepM: number; lostUnderM: number } | null {
  if (!Number.isFinite(stepM) || stepM <= 0) return null
  if (!Number.isFinite(defaultStepM) || defaultStepM <= 0) return null
  if (stepM <= defaultStepM) return null
  return { stepM, lostUnderM: stepM * 2 }
}

/**
 * FROM WHICH MICRO-RELIEF AMPLITUDE the random hills of a ground kind can get
 * steeper than a walker climbs, in metres (§ A16.2).
 *
 * The noise is bilinear between grid corners, so the steepest thing two
 * NEIGHBOURING support points can build out of it is the full swing of the
 * amplitude over one tile step:
 *
 *     worst-case flank = atan(2 · amplitude / tile_step_m)
 *
 * and it exceeds the walk gate as soon as
 *
 *     amplitude > tile_step_m · tan(max_slope_deg) / 2
 *
 * which is the number this returns — 0.84 m at the default 40° over the 2 m
 * tile step. It is a WORST CASE: it needs two adjacent noise corners at ±1, so
 * it is not what every patch of that ground does, it is what some patch of it
 * may do. Hence a warning and nothing more — the clamp stays at 2.0 m (user
 * decision 2026-08-14); a rocky ground that swallows a few impassable spots is
 * a legitimate thing to author, an accidental one is not.
 *
 * IT IS THE SLOPE LIMIT ALONE, deliberately. `max_step_height_m` judges
 * reports below one metre of travel (`STEP_DISTANCE_M`) and bites earlier on
 * any steep flank; what this line names is the point from which the ground
 * breaks the SLOPE rule at all, which is the threshold the field warns at.
 *
 * BOTH INPUTS COME FROM THE SERVER, never pinned here:
 * `max_slope_deg` from the worldmap payload, `tile_step_m` from
 * `GET /world/height-areas`. A step pinned here would have gone on promising
 * the 4 m grid after the tiles halved on 2026-08-14.
 *
 * `null` = nothing to say (no step answered yet, or an unusable angle).
 */
export function reliefWarnAmpM(maxSlopeDeg: number, tileStepM: number
): number | null {
  if (!Number.isFinite(tileStepM) || tileStepM <= 0) return null
  if (!Number.isFinite(maxSlopeDeg) || maxSlopeDeg <= 0 || maxSlopeDeg >= 90) {
    return null
  }
  const g = Math.tan((maxSlopeDeg * Math.PI) / 180)
  return Math.round((tileStepM * g / 2) * 100) / 100
}

/** Is this area's ramp steeper than a walker climbs? */
export function tooSteep(heightM: number, falloffM: number,
  maxSlopeDeg: number, maxStepM: number): boolean {
  const need = minFalloffFor(heightM, maxSlopeDeg, maxStepM)
  if (!need) return false
  return !(falloffM >= need)
}

/* ── Where the ramp ends ────────────────────────────────────────────────── */

/**
 * THE SERVER RAMPS INWARD, and that decides everything below.
 *
 * `app/core/heightfield._area_value` (lines 1252–1266, the one place the rule
 * is spelled; documented on the public twin `area_height_at`, lines 294–313):
 *
 *     if not _inside_ring(x, z, ring): return None      # nothing OUTSIDE
 *     if falloff <= 0:                 return height
 *     return height * min(1.0, _ring_edge_distance(x, z, ring) / falloff)
 *
 * So an area writes NOTHING outside its outline, stands at exactly 0 ON the
 * outline, and reaches its full `height_m` at `falloff_m` metres INSIDE it.
 * The authored outline therefore already IS the foot line — the line where the
 * relief has fully blended into the surrounding ground — and the line the map
 * was missing is the other end: the CREST, where the ramp is done and the
 * ground stands at full height. Offsetting the outline outwards would draw a
 * reach the bake does not have.
 *
 * The rule is a pure DISTANCE rule (`_ring_edge_distance` = shortest distance
 * to the outline, any direction), so the crest is exactly the set
 *
 *     { p inside the polygon : distance(p, outline) >= falloff_m }
 *
 * i.e. the polygon eroded by a disc of radius `falloff_m` — a true buffer, not
 * a per-edge inset. Its boundary is exact and closed-form:
 *
 *   * along each edge: that edge, moved `falloff_m` inwards;
 *   * at a CONVEX corner: the two inset edge lines simply MEET — a sharp
 *     corner (the miter point), exact, no approximation;
 *   * at a REFLEX corner: a circular ARC of radius `falloff_m` around the
 *     vertex, because there the nearest outline point IS the vertex.
 *
 * THE ONLY APPROXIMATION is that arc, drawn as a polyline of at most
 * `RAMP_ARC_STEP_DEG` per segment. Its error is the sagitta of one chord,
 *
 *     e = r · (1 − cos(step/2)) = falloff_m · (1 − cos 5°) = 0.0038 · falloff_m
 *
 * — 11 mm on a 3 m ramp, 38 mm on a 10 m one, and always INSIDE the true arc
 * (a chord never bulges out), so the drawn line never claims more plateau than
 * the bake makes. Straight sections and convex corners — the whole of every
 * rectangular area, which is most of them — are exact to the metre.
 */
export const RAMP_ARC_STEP_DEG = 10

/** Below this |cross product| of two unit edge directions a corner counts as
 *  straight (≈ 0.006°): the two inset lines are parallel there and intersecting
 *  them would divide by ~0. */
const TURN_EPS = 1e-7

/** Shortest distance from a point to the OUTLINE of a polygon, in metres —
 *  the client twin of `heightfield.edge_distance` / `_ring_edge_distance`.
 *  The outline, not the interior: this is the number the server's ramp rule
 *  divides by, and the crest ring is where it equals `falloff_m`. */
export function outlineDistance(x: number, z: number,
  polygon: Array<[number, number]>): number {
  let best = Infinity
  const n = polygon.length
  for (let i = 0; i < n; i += 1) {
    const [ax, az] = polygon[i]
    const [bx, bz] = polygon[(i + 1) % n]
    const dx = bx - ax
    const dz = bz - az
    const l2 = dx * dx + dz * dz
    let t = l2 > 0 ? ((x - ax) * dx + (z - az) * dz) / l2 : 0
    t = t < 0 ? 0 : t > 1 ? 1 : t
    const d = Math.hypot(x - (ax + t * dx), z - (az + t * dz))
    if (d < best) best = d
  }
  return best
}

/** Ray casting, the even-odd rule — the same answer the server's
 *  `_inside_ring` (`world_geometry.point_in_polygon`) gives. */
function insideRing(x: number, z: number,
  polygon: Array<[number, number]>): boolean {
  let inside = false
  const n = polygon.length
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const [xi, zi] = polygon[i]
    const [xj, zj] = polygon[j]
    if ((zi > z) !== (zj > z)
      && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) {
      inside = !inside
    }
  }
  return inside
}

/** Twice the signed area — the orientation of the ring, whatever the frame:
 *  positive and negative rings both occur here (nothing normalises what the
 *  author draws), and the inward normal is the LEFT one only for the positive
 *  sense. */
function signedArea2(polygon: Array<[number, number]>): number {
  let a = 0
  const n = polygon.length
  for (let i = 0; i < n; i += 1) {
    const [x1, z1] = polygon[i]
    const [x2, z2] = polygon[(i + 1) % n]
    a += x1 * z2 - x2 * z1
  }
  return a
}

/** The ring without a repeated closing vertex and without duplicate points —
 *  a zero-length edge has no direction to offset along. */
function cleanRing(polygon: Array<[number, number]>): Array<[number, number]> {
  const out: Array<[number, number]> = []
  for (const p of polygon) {
    if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) return []
    const last = out[out.length - 1]
    if (last && Math.abs(last[0] - p[0]) < 1e-9
      && Math.abs(last[1] - p[1]) < 1e-9) continue
    out.push([p[0], p[1]])
  }
  while (out.length >= 2) {
    const a = out[0]
    const b = out[out.length - 1]
    if (Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9) out.pop()
    else break
  }
  return out
}

/**
 * THE CREST RING of a height area: where its ramp has finished, in world
 * metres — the outline offset INWARDS by `rampM`, joined the way the bake's
 * distance rule joins it (see the block comment above).
 *
 * `null` when there is nothing honest to draw: fewer than three points, no
 * ramp (`falloff_m` 0 — the area is a wall, its crest IS its outline), or a
 * ramp so wide that it swallows the area (nothing left standing at full
 * height, e.g. 6 m of ramp on a 10 m square). The last case is checked, never
 * assumed: every point of the result must really lie inside the polygon at
 * `rampM` from its outline, and the ring must keep the sense it started with —
 * an inset that folds through itself fails both.
 */
export function rampCrestRing(polygon: Array<[number, number]>, rampM: number
): Array<[number, number]> | null {
  if (!Array.isArray(polygon) || polygon.length < 3) return null
  if (!Number.isFinite(rampM) || rampM <= 0) return null
  const ring = cleanRing(polygon)
  const n = ring.length
  if (n < 3) return null
  const a2 = signedArea2(ring)
  if (!a2) return null
  const sense = a2 > 0 ? 1 : -1

  // The inward normal of an edge: the LEFT one on a positively oriented ring,
  // the right one on the other — measured in the SAME (x, z) frame the signed
  // area was measured in, so the map's z-down screen sense never enters.
  const dirs: Array<[number, number]> = []
  for (let i = 0; i < n; i += 1) {
    const [ax, az] = ring[i]
    const [bx, bz] = ring[(i + 1) % n]
    const len = Math.hypot(bx - ax, bz - az)
    if (!len) return null
    dirs.push([(bx - ax) / len, (bz - az) / len])
  }
  const normal = (d: [number, number]): [number, number] =>
    [-d[1] * sense, d[0] * sense]

  const out: Array<[number, number]> = []
  const step = (RAMP_ARC_STEP_DEG * Math.PI) / 180
  for (let i = 0; i < n; i += 1) {
    const [cx, cz] = ring[i]
    const din = dirs[(i - 1 + n) % n]
    const dout = dirs[i]
    const nin = normal(din)
    const nout = normal(dout)
    const pin: [number, number] = [cx + nin[0] * rampM, cz + nin[1] * rampM]
    const pout: [number, number] = [cx + nout[0] * rampM, cz + nout[1] * rampM]
    // Positive = the ring turns towards its own inside here (convex corner),
    // negative = away from it (reflex corner).
    const turn = (din[0] * dout[1] - din[1] * dout[0]) * sense
    if (turn > TURN_EPS) {
      // Convex: the two inset lines meet. EXACT — one point, no arc.
      const denom = din[0] * dout[1] - din[1] * dout[0]
      const t = ((pout[0] - pin[0]) * dout[1] - (pout[1] - pin[1]) * dout[0])
        / denom
      out.push([pin[0] + din[0] * t, pin[1] + din[1] * t])
    } else if (turn < -TURN_EPS) {
      // Reflex: the nearest outline point is the vertex itself, so the crest
      // runs around it on a circle of radius `rampM`. The sweep is the short
      // way — a corner turns by less than 180° or it is not a corner.
      const a0 = Math.atan2(pin[1] - cz, pin[0] - cx)
      const a1 = Math.atan2(pout[1] - cz, pout[0] - cx)
      let sweep = a1 - a0
      while (sweep > Math.PI) sweep -= 2 * Math.PI
      while (sweep < -Math.PI) sweep += 2 * Math.PI
      const parts = Math.max(1, Math.ceil(Math.abs(sweep) / step))
      for (let k = 0; k <= parts; k += 1) {
        const ang = a0 + (sweep * k) / parts
        out.push([cx + Math.cos(ang) * rampM, cz + Math.sin(ang) * rampM])
      }
    } else {
      // Straight through: one point on the single inset line.
      out.push(pin)
    }
  }
  if (out.length < 3) return null

  // Does what came out actually stand at full height? The ramp is a distance
  // rule, so the test is the distance rule — measured, not trusted.
  const eps = 1e-6 * Math.max(1, rampM)
  for (const [x, z] of out) {
    if (!Number.isFinite(x) || !Number.isFinite(z)) return null
    if (!insideRing(x, z, ring)) return null
    if (outlineDistance(x, z, ring) < rampM - eps) return null
  }
  // A ring that lost its sense (or its area) folded through itself: the ramps
  // of opposite edges met, and there is no plateau left to outline.
  if (signedArea2(out) * sense <= 0) return null
  return out
}
