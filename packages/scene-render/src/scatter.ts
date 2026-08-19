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
 * The ground a placed location covers: its OUTLINE, in WORLD metres.
 *
 * Contract v6 "Gebiete": a location is a drawn POLYGON (`map3d.boundary`),
 * never a square, and concave outlines are explicitly allowed. The square this
 * interface used to carry (centre + yaw + edge) got both halves of a concave
 * place wrong at once — a lake with a bay excluded scatter from the bay, which
 * is water nobody painted a building on, and let scatter through the parts of
 * the drawn shape that reach past the bounding square's corner. A square is
 * now simply the special case of a polygon with four points.
 *
 * WORLD METRES, and that is the whole contract with the caller. The package
 * knows nothing about pins: `boundary` arrives in metres LOCAL to the anchor
 * (`pos_x`/`pos_z`, turned by `yaw_deg`, § A1.1), and whoever holds the row
 * turns it ONCE per location — not once per candidate point, which is what a
 * pin-aware footprint would have cost on every sample of every area.
 *
 * A location without a usable boundary contributes NO footprint at all. It has
 * no area (§ A1.1, v6 Nr. 1 — the old "no anchor, 10 m square" is gone) and
 * therefore blocks nothing; the caller drops it rather than handing in an
 * empty outline.
 */
export interface ScatterFootprint {
  /** the outline in WORLD metres, `[x, z]` per point. Fewer than three points
   *  enclose nothing and block nothing; a repeated closing point is harmless
   *  (its edge is degenerate and never crosses a ray). */
  points: readonly ScatterPoint2[]
}

/** One authored scatter of an area — `terrain_areas.meta.scatter[]`, exactly
 *  the fields `app/models/terrain.py` whitelists. */
export interface ScatterEntry {
  /** instances per 100 m2 of the painted area; 0 = nothing is scattered */
  density_per_100m2: number
  /** URL of a prop mesh to instance; absent = the built-in tuft */
  model?: string
  /** TARGET height in metres: the placed prop is scaled uniformly until its
   *  bounding box is this tall. Absent = the prop's own library height, which
   *  the server ships as `prop_height_m` (the 3D client's `scatterTargetH`
   *  resolves the precedence; a model with no prop record falls back to its
   *  flat default, the built-in tuft to its tuft height) — NEVER the model's
   *  authored size, which is no size at all in a world measured in metres. */
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
 * the stream.
 *
 * It LIVES here now — `client3d/src/scene/textures.ts` re-exports this one
 * rather than keeping a second body, so the client's textures, its figure
 * jitter and this sampler all pull the identical stream. The editor preview
 * has to draw the very points the client plants, and that is only possible if
 * both sides pull the same numbers in the same order.
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
 * World metres → the local frame of a pin turned by `yawRad`, i.e. a rotation
 * by −yaw about the anchor. The inverse of the contract's § A1.1 mapping
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
 * Does the point lie on a placed location's footprint (finding B18, contract
 * v6)?
 *
 * The very ray cast of `pointInRing`, spelled out again with a finiteness
 * guard, so the answer is the SERVER's
 * (`app/core/world_geometry.point_in_polygon`) and the walking client's
 * (`client3d/src/game/polygon.pointInPolygon`) down to the half-open
 * comparison: `(zi > z) !== (zj > z)` and a strict `x < crossX`. A point
 * exactly on an edge may fall either way, and on all three sides it falls the
 * SAME way — which is what keeps a prop from standing inside a wall the server
 * refuses to let anyone walk through.
 *
 * A junk coordinate anywhere in the outline makes the whole outline useless
 * (the same all-or-nothing `polygon.sanitizePolygon` applies), so it blocks
 * nothing rather than blocking a shape nobody can name. Fewer than three
 * points, likewise: a line encloses no ground.
 *
 * The guard is folded into the cast rather than run as a separate pass — this
 * is the innermost loop of the sampler (candidates × footprints), and a second
 * walk over the outline would be paid on every one of them.
 */
export function pointInFootprint(fp: ScatterFootprint,
                                 x: number, z: number): boolean {
  const pts = fp?.points
  const n = pts?.length ?? 0
  if (n < 3) return false
  if (!Number.isFinite(x) || !Number.isFinite(z)) return false
  let inside = false
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const a = pts[i]
    const b = pts[j]
    if (!a || !b || a.length < 2 || b.length < 2) return false
    const xi = a[0]
    const zi = a[1]
    const xj = b[0]
    const zj = b[1]
    if (!Number.isFinite(xi) || !Number.isFinite(zi)
      || !Number.isFinite(xj) || !Number.isFinite(zj)) return false
    if ((zi > z) !== (zj > z)
      && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside
  }
  return inside
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
  /** Placed locations whose footprints are kept CLEAR (finding B18) — their
   *  drawn outlines in WORLD metres, see `ScatterFootprint`. A location with
   *  no boundary has no area and simply does not appear in this list. */
  footprints?: readonly ScatterFootprint[]
  /**
   * The CLEANED rings of every area that lies ABOVE this one in the stack —
   * only the ground an area actually SHOWS is scattered.
   *
   * The server delivers the areas bottom to top (`z_order` ASC, `created_at`
   * ASC), so the list order IS the stacking order and this is the slice after
   * the sampled area's own index. A river painted over a wood covers the
   * wood's surface, and until this existed the wood's trees kept growing
   * through the water — the area below is simply not visible there.
   *
   * Tested with the same even-odd rule as the area's own ring
   * (`pointInRing`), so a hole polygon has the same inside on both sides and
   * on the server (`point_in_polygon`).
   */
  occluders?: readonly (readonly ScatterPoint2[])[]
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
 * HOW MANY instances one entry plants on one area — the count half of the
 * sampler, on its own and without drawing a single random number.
 *
 *     wanted = min( round(areaM2 / 100 · density), maxPoints )
 *
 * It is spelled out here because the count is asked for in places that must
 * NOT sample: the map editor's preview budgets its dots over every entry of
 * every area before it places any of them (`mapMath.scatterPreviewShares`),
 * and sampling first only to throw most of it away is exactly the cost that
 * budget exists to avoid. `scatterInstances` calls this too — one formula, so
 * a preview that says "this entry plants n" cannot disagree with the n the
 * world plants.
 *
 * A count below one is 0: an entry that wants a third of a prop plants none.
 */
export function scatterWantedCount(areaM2: number, densityPer100m2: number,
                                   maxPoints?: number): number {
  const density = Number(densityPer100m2)
  const area = Number(areaM2)
  if (!Number.isFinite(density) || density <= 0) return 0
  if (!Number.isFinite(area) || area <= 0) return 0
  const max = maxPoints ?? SCATTER_MAX_PER_ENTRY
  const wanted = Math.min(Math.round((area / 100) * density), max)
  return wanted >= 1 ? wanted : 0
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
 *   reject when the point is outside the ring, inside a covering area
 *     (`occluders`) or inside any footprint
 *
 * THREE NUMBERS PER CANDIDATE, ALWAYS — the yaw is drawn before the test even
 * though a rejected candidate never uses it. That one wasted number is what
 * makes the footprint exclusion (B18) and the occluder exclusion a
 * SUBTRACTION: every candidate keeps its place in the stream, so dropping a
 * building onto a meadow removes exactly the props it covers and leaves every
 * other tree exactly where it stood. Drawing the yaw only on acceptance would
 * save the number and shift the whole stream at the first rejection, which
 * rearranges the entire wood behind the new building — deterministic, but for
 * the author indistinguishable from random.
 */
export function scatterInstances(opts: ScatterSampleOptions): ScatterInstance[] {
  const ring = opts.ring ?? []
  const density = Number(opts.densityPer100m2)
  const areaM2 = Number(opts.areaM2)
  if (ring.length < 3) return []
  if (!Number.isFinite(density) || density <= 0) return []
  if (!Number.isFinite(areaM2) || areaM2 <= 0) return []
  // ONE count formula, and it lives in `scatterWantedCount` — the editor's
  // preview budget has to know this number before it samples anything.
  //
  // A SMALLER `maxPoints` gives exactly the PREFIX of the fuller run: the
  // candidate stream depends on the seed alone, so the first n accepted
  // candidates are the same n points whatever the ceiling is. That is what
  // lets the preview draw a thinned SUBSET of the very props the world plants
  // instead of a second, unrelated sample.
  const wanted = scatterWantedCount(areaM2, density, opts.maxPoints)
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
  const occluders = opts.occluders ?? []
  const out: ScatterInstance[] = []
  let tries = wanted * (opts.triesPerPoint ?? SCATTER_TRIES_PER_POINT)
  while (out.length < wanted && tries > 0) {
    tries -= 1
    const x = minX + rnd() * (maxX - minX)
    const z = minZ + rnd() * (maxZ - minZ)
    const yaw = rnd() * Math.PI * 2
    if (!pointInRing(x, z, ring)) continue
    // Covered by an area painted OVER this one: that ground is not visible,
    // so nothing grows on it. Same shape of rejection as the footprint below —
    // all three numbers are already drawn, so this only ever subtracts.
    let hidden = false
    for (const occ of occluders) {
      if ((occ?.length ?? 0) >= 3 && pointInRing(x, z, occ)) { hidden = true; break }
    }
    if (hidden) continue
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
