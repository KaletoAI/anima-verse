/**
 * scatter — how scattered props are PLACED and how they STAND, for both
 * renderers.
 *
 * The 3D client plants them on the world map; the map editor draws the very
 * same points as a top-down preview. That only stays true if the maths lives
 * in ONE place, so it lives here.
 *
 * NO IMPORT AT ALL, not even a type one. Everything in this file is arithmetic
 * on numbers and number pairs, and that is what lets
 * `client3d/scripts/smoke_scatter_math.mjs` load it through the plain esbuild
 * transpile the other pure smokes use — no bundler, no stand-ins. If someone
 * ever adds a runtime import, that loader fails loudly, which is the intended
 * alarm.
 */

/** A world point on the ground plane: `[x, z]` in metres. The twin of
 *  `groundAreas.Point2` — spelled out again rather than imported, see the
 *  header: this module has no imports. */
export type ScatterPoint2 = [number, number]

/**
 * A placed location, as much of it as the scatter needs: the centre of its
 * footprint square, its turn and its edge length.
 *
 * The field NAMES are the payload's (`/play/worldmap → locations`, and the
 * editor's `/world/locations` rows), so both callers hand their rows straight
 * in — no adapter, and therefore no chance of the two sides describing the
 * same square differently. Anything unplaced or without a positive edge has no
 * area at all (§ A1.1/§ A1.3) and never blocks a point.
 */
export interface ScatterFootprint {
  pos_x?: number | null
  pos_z?: number | null
  yaw_deg?: number | null
  plan_width_m?: number | null
}

/** One authored scatter of an area — `terrain_areas.meta.scatter[]`, exactly
 *  the fields `app/models/terrain.py` whitelists. */
export interface ScatterEntry {
  /** instances per 100 m2 of the painted area; 0 = nothing is scattered */
  density_per_100m2: number
  /** URL of a prop mesh to instance; absent = the built-in tuft */
  model?: string
  /** TARGET height in metres: the placed prop is scaled uniformly until its
   *  bounding box is this tall. Absent = the model keeps its authored size
   *  (and the tuft its default). */
  height_m?: number
}

/** One placed instance: where it stands and which way it faces (radians). */
export interface ScatterInstance {
  x: number
  z: number
  yaw: number
}

/** Instances one entry may place on one area, whatever the density says. A
 *  hand-typed `density_per_100m2` on a lake-sized meadow would otherwise build
 *  a hundred thousand instances in one frame. */
export const SCATTER_MAX_PER_ENTRY = 2000

/** Rejection sampling gives up after this many misses per wanted instance — a
 *  very thin or very concave ring, or one mostly covered by footprints, can
 *  reject most of its bounding box. */
export const SCATTER_TRIES_PER_POINT = 12

/**
 * The seed of one scatter entry — AREA-stable and INDEX-stable.
 *
 * Stable per area, so the same meadow grows the same trees on every load and
 * in every client; per index, so the second entry of a list is not a copy of
 * the first standing in the same spots. Repainting the area's outline keeps
 * the seed (the id does not change) — the points move only because the ring
 * they are sampled in moved, which is what an author expects when they redraw
 * a shape.
 */
export function scatterSeed(areaId: string, index: number): string {
  return `terrain:scatter:${areaId}:${index}`
}

/**
 * Deterministic PRNG over a string seed: FNV-1a for the state, xorshift for
 * the stream. Moved here from `client3d/src/scene/textures.ts` — the editor
 * preview has to draw the very points the client plants, and that is only
 * possible if both sides pull the same numbers in the same order.
 */
export function seededRandom(seed: string): () => number {
  let h = 2166136261
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822519)
    h = Math.imul(h ^ (h >>> 13), 3266489917)
    return ((h ^= h >>> 16) >>> 0) / 4294967296
  }
}

/**
 * Even-odd ray crossing: is `(x, z)` inside the ring?
 *
 * The same rule the server answers point queries with
 * (`app/core/world_geometry.point_in_polygon`) and the same one the editor
 * paints with (`fillRule="evenodd"`), so a bow-tie polygon has ONE inside. A
 * point exactly on an edge may fall either way, which moves at most one prop
 * by a hair.
 */
export function pointInRing(x: number, z: number,
                            ring: readonly ScatterPoint2[]): boolean {
  let inside = false
  const n = ring?.length ?? 0
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const [xi, zi] = ring[i]
    const [xj, zj] = ring[j]
    if ((zi > z) !== (zj > z)
      && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside
  }
  return inside
}

/**
 * World metres → the local frame of a footprint turned by `yawRad`, i.e. a
 * rotation by −yaw about the centre. The inverse of the contract's § A1.1
 * mapping
 *
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * and THE one implementation of it: `scene/tiles.worldToTile` (3D client) and
 * `map/mapMath.worldToLocal` (editor) both call this now. There used to be two
 * copies of these four lines and this file was about to become a third.
 */
export function worldToLocalXZ(cx: number, cz: number, yawRad: number,
                               x: number, z: number): { x: number; z: number } {
  const c = Math.cos(yawRad)
  const s = Math.sin(yawRad)
  const dx = x - cx
  const dz = z - cz
  return { x: dx * c - dz * s, z: dx * s + dz * c }
}

/**
 * Does the point lie on a placed location's footprint square (finding B18)?
 *
 * The square is turned, so the point is turned into the square's own frame
 * first and compared against half the edge on both axes — the very test
 * `main.ts → tileAt` runs for walking. An unplaced location, one without a
 * positive edge, or a junk number is not a square and never blocks.
 */
export function pointInFootprint(fp: ScatterFootprint,
                                 x: number, z: number): boolean {
  const cx = fp?.pos_x
  const cz = fp?.pos_z
  const w = fp?.plan_width_m
  if (typeof cx !== 'number' || !Number.isFinite(cx)) return false
  if (typeof cz !== 'number' || !Number.isFinite(cz)) return false
  if (typeof w !== 'number' || !(w > 0)) return false
  const yawDeg = typeof fp.yaw_deg === 'number' && Number.isFinite(fp.yaw_deg)
    ? fp.yaw_deg : 0
  const p = worldToLocalXZ(cx, cz, (yawDeg * Math.PI) / 180, x, z)
  const half = w / 2
  return Math.abs(p.x) <= half && Math.abs(p.z) <= half
}

/** What `scatterInstances` needs to know. */
export interface ScatterSampleOptions {
  /** The CLEANED world ring the area is drawn from (`cleanRing`), `[x, z]` in
   *  metres — never the raw payload polygon: one non-finite corner makes every
   *  bound NaN, and NaN fails quietly (no point ever lands inside its own box). */
  ring: readonly ScatterPoint2[]
  /** Enclosed ground in square metres (`polygonArea` of that same ring). */
  areaM2: number
  /** Instances per 100 m2. */
  densityPer100m2: number
  /** `scatterSeed(area.id, index)` — see there. */
  seed: string
  /** Placed locations whose footprints are kept CLEAR (finding B18). */
  footprints?: readonly ScatterFootprint[]
  /** Hard ceiling; defaults to `SCATTER_MAX_PER_ENTRY`. */
  maxPoints?: number
  /** Misses allowed per wanted instance; defaults to
   *  `SCATTER_TRIES_PER_POINT`. */
  triesPerPoint?: number
  /**
   * The random stream, for the smoke check only. Production callers leave this
   * out and get `seededRandom(seed)`; the hand-derived cases feed a fixed list
   * of numbers so the expected points can be worked out with the formula
   * below instead of by simulating a PRNG on paper.
   */
  rng?: () => number
}

/**
 * The instances of ONE scatter entry on ONE area — deterministic, so the
 * editor preview and the planted world are the same points by construction.
 *
 * Seeded rejection sampling over the ring's bounding box:
 *
 *   wanted = min( round(areaM2 / 100 * density), maxPoints )
 *   x   = minX + r · (maxX − minX)
 *   z   = minZ + r · (maxZ − minZ)
 *   yaw = r · 2π
 *   reject when the point is outside the ring or inside any footprint
 *
 * THREE NUMBERS PER CANDIDATE, ALWAYS — the yaw is drawn before the test even
 * though a rejected candidate never uses it. That one wasted number is what
 * makes the footprint exclusion (B18) a SUBTRACTION: every candidate keeps its
 * place in the stream, so dropping a building onto a meadow removes exactly
 * the props it covers and leaves every other tree exactly where it stood.
 * Drawing the yaw only on acceptance would save the number and shift the whole
 * stream at the first rejection, which rearranges the entire wood behind the
 * new building — deterministic, but for the author indistinguishable from
 * random.
 */
export function scatterInstances(opts: ScatterSampleOptions): ScatterInstance[] {
  const ring = opts.ring ?? []
  const density = Number(opts.densityPer100m2)
  const areaM2 = Number(opts.areaM2)
  if (ring.length < 3) return []
  if (!Number.isFinite(density) || density <= 0) return []
  if (!Number.isFinite(areaM2) || areaM2 <= 0) return []
  const max = opts.maxPoints ?? SCATTER_MAX_PER_ENTRY
  const wanted = Math.min(Math.round((areaM2 / 100) * density), max)
  if (wanted < 1) return []

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
  if (!Number.isFinite(minX) || !Number.isFinite(minZ)) return []

  const rnd = opts.rng ?? seededRandom(opts.seed)
  const footprints = opts.footprints ?? []
  const out: ScatterInstance[] = []
  let tries = wanted * (opts.triesPerPoint ?? SCATTER_TRIES_PER_POINT)
  while (out.length < wanted && tries > 0) {
    tries -= 1
    const x = minX + rnd() * (maxX - minX)
    const z = minZ + rnd() * (maxZ - minZ)
    const yaw = rnd() * Math.PI * 2
    if (!pointInRing(x, z, ring)) continue
    let covered = false
    for (const fp of footprints) {
      if (pointInFootprint(fp, x, z)) { covered = true; break }
    }
    if (covered) continue
    out.push({ x, z, yaw })
  }
  return out
}

/** How a loaded prop mesh has to be transformed to STAND on the ground. */
export interface PropGroundFit {
  /** uniform scale factor; 1 when no target height was asked for */
  scale: number
  /** metres to add to y AFTER scaling, so the lowest point sits at 0 */
  offsetY: number
}

/**
 * Put a prop ON the ground instead of THROUGH it (finding B16).
 *
 * A GLB carries whatever origin its author chose — for a tree that is
 * typically the middle of the trunk, so half of it stood below y = 0 while the
 * placeholder cone next to it (built at base = 0) stood correctly. The fix is
 * pure arithmetic on the mesh's bounding box in its own frame:
 *
 *   scale   = targetH / (maxY − minY)   when a target height is asked for
 *   offsetY = −minY · scale             the lowest point after scaling
 *
 * so the bounding box afterwards runs from y = 0 to y = targetH. Worked
 * example, the one from the finding: a 2 m tree modelled around its centre has
 * minY = −1, maxY = +1. Without a target height that is scale 1, offsetY +1 —
 * the metre it used to sink. With `height_m = 4` it is scale 2 (a 4 m tree)
 * and offsetY +2, because after scaling the lowest point is at −2.
 *
 * A degenerate box (a flat plane, a single point) has no height to scale, so
 * the scale stays 1 and only the lift applies — a flat prop lies on the
 * ground rather than vanishing into an infinite scale.
 */
export function propGroundFit(minY: number, maxY: number,
                              targetH?: number | null): PropGroundFit {
  const lo = Number(minY)
  const hi = Number(maxY)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { scale: 1, offsetY: 0 }
  const height = hi - lo
  const target = Number(targetH)
  const scale = Number.isFinite(target) && target > 0 && height > 1e-6
    ? target / height
    : 1
  return { scale, offsetY: -lo * scale }
}
