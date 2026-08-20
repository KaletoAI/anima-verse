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
  /**
   * WHICH model variant of the prop this instance shows (§ B2 addendum) —
   * present ONLY when the caller asked for a mix (`variantCount > 1`).
   *
   * The absence is the contract, not a shortcut: a prop with one variant has
   * nothing to choose, and an entry that is not asked about variants must come
   * out of the sampler as the very object it always did — same keys, same
   * values. That is what makes the mix a pure addition for every existing
   * consumer (the map editor's dot preview, the backdrop profile) instead of a
   * shape change every one of them has to be taught.
   */
  variant?: number
}

/** Instances one entry may place on one WHOLE area, whatever the density says.
 *
 *  ONLY THE WHOLE-AREA SAMPLER STILL HAS THIS CEILING, and since 2026-08-19 no
 *  authored scatter goes through it any more — see `scatterCellInstances` for
 *  why a fixed count over a painted shape of any size is the one thing this
 *  module must not do. It remains the default of `scatterInstances` for the
 *  callers that sample a BOUNDED ring (a cell, a room), where the number is a
 *  guard nothing can reach and not a budget anybody spends. */
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
 * FNV-1a 32-bit over a string — the STATE half of `seededRandom`, on its own.
 *
 *     h = 2166136261
 *     for each char c:  h = (h XOR c) · 16777619   (mod 2^32)
 *
 * It is spelled out as its own function because a seed is asked TWO questions
 * here: "give me a stream of numbers" (`seededRandom`) and "give me ONE number"
 * (`scatterVariantIndex` — which variant a copy shows). Both must come out of
 * the same seed by the same rule, and a second hash body would be a second
 * answer waiting to drift.
 *
 * Unsigned, so the caller can do plain arithmetic on it: `Math.imul` returns a
 * SIGNED int32, and `(-1) % 3` is `-1` in JavaScript — a negative hash would
 * hand a negative variant index to a renderer.
 */
export function scatterSeedHash(seed: string): number {
  let h = 2166136261
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/**
 * WHICH active model variant one scattered copy shows (§ B2 addendum):
 *
 *     variant = ( scatterSeedHash(seed) + instance ) mod count
 *
 * THE SAME FORMULA THE SERVER RUNS for the scattered copies of a room
 * placement (`app/core/props.py scatter_variant_index`) — the one difference
 * is what the seed IS. There it is a stored uint32 on the placement; here it
 * is the CELL's own seed string (`scatterCellSeed`), because the painted
 * terrain scatter has no stored per-copy row to hang a number on: its
 * instances are sampled client-side in a camera window whose cell set changes
 * as the player walks. Hashing the cell seed gives every cell its own offset
 * into the variant ring, and since that seed is a pure function of area, row
 * and cell index, the same cell of the same world answers the same mix on
 * every client, every reload and from every direction of approach.
 *
 * `instance` is the CANDIDATE ordinal in the cell's stream, not the position
 * in the returned list — see `scatterInstances`, where the same choice makes
 * the footprint and occluder tests a pure SUBTRACTION. A building dropped on a
 * meadow must remove the props it covers without re-species-ing the wood
 * behind it, and the clearance of an entry is refined the moment its mesh
 * lands (`ground.ts noteSpread`), so a list position would re-roll every tree
 * of a cell a second after it came into view.
 *
 * `count` 0 or 1 has nothing to choose from and answers 0.
 */
export function scatterVariantIndex(seed: string, instance: number,
                                    count: number): number {
  const n = Math.floor(Number(count))
  if (!Number.isFinite(n) || n <= 1) return 0
  const i = Math.floor(Number(instance))
  if (!Number.isFinite(i)) return 0
  return (((scatterSeedHash(seed) + i) % n) + n) % n
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
  let h = scatterSeedHash(seed) | 0
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

/**
 * Distance from `(x, z)` to a placed location's outline — **0 anywhere
 * inside**, edges inclusive, `Infinity` for an outline that encloses nothing.
 *
 * The same answer as the server's `world_geometry.polygon_distance` and the
 * walking client's `game/polygon.polygonDistance`, and it shares BOTH halves
 * with `pointInFootprint` above: the identical half-open ray cast decides
 * inside/outside, and the identical all-or-nothing junk rule applies — a
 * non-finite coordinate anywhere makes the whole outline useless, so it blocks
 * nothing rather than blocking a shape nobody can name.
 *
 * ONE PASS over the edges, not two: the ray cast and the nearest-segment
 * search walk the same list, and this runs in the innermost loop of the
 * sampler (candidates × footprints). Walking the outline twice would be paid
 * on every candidate of every cell.
 */
export function footprintDistance(fp: ScatterFootprint,
                                  x: number, z: number): number {
  const pts = fp?.points
  const n = pts?.length ?? 0
  if (n < 3) return Infinity
  if (!Number.isFinite(x) || !Number.isFinite(z)) return Infinity
  let inside = false
  let best = Infinity
  for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
    const a = pts[i]
    const b = pts[j]
    if (!a || !b || a.length < 2 || b.length < 2) return Infinity
    const xi = a[0]
    const zi = a[1]
    const xj = b[0]
    const zj = b[1]
    if (!Number.isFinite(xi) || !Number.isFinite(zi)
      || !Number.isFinite(xj) || !Number.isFinite(zj)) return Infinity
    if ((zi > z) !== (zj > z)
      && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside
    // …and the distance to that very edge, b -> a, clamped to the segment.
    const dx = xi - xj
    const dz = zi - zj
    const len2 = dx * dx + dz * dz
    let t = len2 < 1e-18 ? 0 : ((x - xj) * dx + (z - zj) * dz) / len2
    t = t < 0 ? 0 : (t > 1 ? 1 : t)
    const ex = x - (xj + t * dx)
    const ez = z - (zj + t * dz)
    const d = Math.sqrt(ex * ex + ez * ez)
    if (d < best) best = d
  }
  return inside ? 0 : best
}

/**
 * Does a placed location keep this instance out — the CLEARANCE test that
 * replaced "is its centre inside?" (user finding 2026-08-20).
 *
 * A scattered prop is not a point: an 8 m tree whose trunk stands 40 cm
 * OUTSIDE a boundary still hangs metres of canopy over the courtyard behind
 * it, and the centre test let every one of them through. So the outline is
 * kept clear by the instance's own horizontal half-extent (`clearM`,
 * `scatterClearM`): the prop is excluded while its footprint circle reaches
 * into the drawn shape.
 *
 *     excluded  <=>  footprintDistance(x, z) < clearM
 *
 * `clearM` 0 (or junk, or nothing) is the plain containment test of before,
 * spelled out as such rather than as `distance < 0`: a point INSIDE has
 * distance 0, and `0 < 0` would let every prop stand in the middle of the
 * building. It is the answer for a layer whose props are too small for their
 * own overhang to matter — the automatic undergrowth passes no clearance.
 */
export function footprintBlocks(fp: ScatterFootprint, x: number, z: number,
                                clearM?: number): boolean {
  const clear = Number(clearM)
  if (!(clear > 0)) return pointInFootprint(fp, x, z)
  return footprintDistance(fp, x, z) < clear
}

/** How wide a scattered prop is assumed to be when nobody has MEASURED it:
 *  as wide as it is tall. Half of that is its clearance — see
 *  `scatterClearM`. */
export const SCATTER_CLEAR_HEIGHT_RATIO = 0.5

/**
 * The clearance ONE instance keeps from a location's outline, in metres:
 * HALF its horizontal extent at the scale it is planted at.
 *
 *     clearM = extentM / 2          measured: max of the scaled bbox x/z
 *     clearM = heightM · 0.5        estimated: nothing has been measured yet
 *
 * The measured branch is the 3D client's, which holds the loaded mesh and
 * scales it uniformly to the target height, so `max(bboxX, bboxZ) · scale` is
 * exactly the width the player sees. The estimated branch is for everyone who
 * draws the scatter WITHOUT the meshes — the map editor's preview draws dots,
 * and the client itself before the GLB of an entry has landed. Treating a prop
 * as being as wide as it is tall is deliberately generous for a tree (a 8 m
 * pine is nowhere near 8 m across) and honest for a bush; the cost of being
 * wrong is a prop too few at a border, never a canopy hanging over a
 * courtyard.
 */
export function scatterClearM(heightM: number,
                              extentM?: number | null): number {
  const extent = Number(extentM)
  if (Number.isFinite(extent) && extent > 0) return extent / 2
  const h = Number(heightM)
  if (!Number.isFinite(h) || h <= 0) return 0
  return h * SCATTER_CLEAR_HEIGHT_RATIO
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
  /** The horizontal HALF-EXTENT of the instance this entry plants, in metres
   *  (`scatterClearM`): a footprint is kept clear by this much instead of just
   *  by its outline, so a prop centred just outside stops hanging over it.
   *  Absent or 0 = the plain containment test — see `footprintBlocks`. */
  clearM?: number
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
  /**
   * How many ACTIVE model variants the prop of this entry has (§ B2 addendum).
   *
   * Absent, 0 or 1 = nothing to mix: the instances come out exactly as they
   * always did, without a `variant` key. From 2 on every accepted instance
   * carries the variant it shows, chosen by `scatterVariantIndex` from this
   * entry's seed and the candidate's ordinal.
   *
   * It is an INPUT of the sampler rather than something the caller works out
   * afterwards, because the ordinal the formula needs is the candidate's, and
   * that number exists only in here — see `scatterVariantIndex`.
   */
  variantCount?: number
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
 *     (`occluders`) or within `clearM` of any footprint (`footprintBlocks` —
 *     the plain "inside" test when no clearance is given)
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
  // The clearance is read ONCE, outside the loop: it is one number for the
  // whole entry (every instance of a row is the same prop at the same scale),
  // and it never touches the candidate stream — only the verdict on a
  // candidate that has already drawn its three numbers.
  const clearM = opts.clearM
  const occluders = opts.occluders ?? []
  // How many meshes this entry's prop has to choose between, and therefore
  // whether the instances say anything about it at all (see `variantCount`).
  const variants = Math.floor(Number(opts.variantCount))
  const mixing = Number.isFinite(variants) && variants > 1
  const out: ScatterInstance[] = []
  let tries = wanted * (opts.triesPerPoint ?? SCATTER_TRIES_PER_POINT)
  // THE CANDIDATE ORDINAL, counted over every point the stream draws — the
  // rejected ones included. It is what the variant hangs on, for exactly the
  // reason the yaw is drawn before the test: a rejection must SUBTRACT, and a
  // number counted over the survivors instead would re-species every prop
  // behind a newly placed building.
  let candidate = 0
  while (out.length < wanted && tries > 0) {
    tries -= 1
    const index = candidate
    candidate += 1
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
      if (footprintBlocks(fp, x, z, clearM)) { covered = true; break }
    }
    if (covered) continue
    out.push(mixing
      ? { x, z, yaw, variant: scatterVariantIndex(opts.seed, index, variants) }
      : { x, z, yaw })
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

/* ==========================================================================
 * THE CELL RASTER — the authored scatter, sampled per 64 m square
 *
 * WHY THIS EXISTS (reported 2026-08-19, the second defect). `scatterInstances`
 * spends a FIXED ceiling of instances (`SCATTER_MAX_PER_ENTRY`) over a painted
 * shape of ANY size, so the effective density of a capped area is
 *
 *     2000 / (areaM2 / 100)   instances per 100 m2,   i.e. proportional to 1/A
 *
 * Two woods of one kind and one authored density are therefore drawn at
 * DIFFERENT densities the moment both are big enough to be capped. Measured on
 * the reporting world: 13.71 km2 at 43.1 per 100 m2 came out at 0.1021, the
 * 0.84 km2 wood beside it at 1.4261 — a factor of 13.97 from settings that are
 * identical, and 46 against 645 trees inside the player's 120 m cull radius.
 *
 * THE RESCUE IS THE ONE THE AUTOMATIC UNDERGROWTH ALREADY GOT (2026-08-16,
 * `client3d/src/scene/undergrowth.ts`): sample a CELL, not a shape. Each 64 m
 * square is filled at the authored density from its own seed, and the area's
 * ring is the FILTER behind it — so the density is the density of the ground,
 * whatever the shape it was painted in, and the cost hangs on the WINDOW a
 * camera holds rather than on the size of the world.
 *
 * The ring is its own bounding box, so nothing is ever re-rolled for missing
 * it (`triesPerPoint: 1`): footprints and covering areas SUBTRACT their props
 * instead of squeezing a whole cell's worth into what is left of it.
 * ========================================================================== */

/** Edge of one scatter cell, in world metres.
 *
 *  THE SAME 64 m THE UNDERGROWTH USES (`UNDERGROWTH_CELL_M`) — one raster in
 *  the world, so a wood and the ferns under it are cut along the same lines
 *  and a seam can only ever be the painted border. Big enough that a camera
 *  window is a couple of dozen cells, small enough that the window hugs the
 *  cull circle instead of carrying corners nobody can see. */
export const SCATTER_CELL_M = 64

/** Instances one entry may place in ONE cell — a guard, not a budget.
 *
 *  A cell is 4096 m2, so this ceiling is reached at
 *  4000 / 40.96 = 97.66 instances per 100 m2, i.e. roughly ONE PROP PER SQUARE
 *  METRE of ground. No authored density comes near it (the densest row of the
 *  reporting world is 50 per 100 m2, a lawn of grass blades); a hand-edited
 *  density that crosses the JSON boundary costs a thicker cell instead of a
 *  million instances built in one frame.
 *
 *  UNLIKE THE OLD PER-AREA CEILING this one is scale-free: it bites at the
 *  same density on every cell of every area, so two woods of one authoring can
 *  never come out at two densities. That is the property, not the number. */
export const SCATTER_MAX_PER_CELL = 4000

/** How many cells `scatterCellsInBox` will ever hand back — the guard that
 *  keeps a box the size of a world from becoming a list of a million cells
 *  before anybody looks at its length. */
export const SCATTER_CELLS_MAX = 4096

/** The cell a world coordinate falls in — `Math.floor`, so a cell owns its
 *  lower edge. THE one mapping from a place to a cell index. */
export function scatterCellAt(v: number): number {
  return Math.floor(v / SCATTER_CELL_M)
}

/**
 * The seed of ONE entry in ONE cell — its own stream, per area, per row, per
 * place.
 *
 * The area id and the row index keep two woods and two rows of one wood apart
 * (as `scatterSeed` always did); the CELL keeps neighbouring cells apart. A
 * seed without the cell would draw the identical sequence of numbers in every
 * cell, and since each cell maps those numbers onto its OWN box the whole wood
 * would be one pattern stamped out every 64 m — the grid artefact the
 * undergrowth's own seed comment describes, visible the moment anyone looks
 * along it.
 *
 * SAME WORLD, SAME CELL, SAME TREES — wherever the camera stands and whenever
 * it comes back. That is what makes a windowed sampler a picture of a world
 * rather than a picture of a walk.
 */
export function scatterCellSeed(areaId: string, index: number,
                                cx: number, cz: number): string {
  return `terrain:scatter:${areaId}:${index}:${cx},${cz}`
}

/** The ring of one cell — its own box, in world metres. */
export function scatterCellRing(cx: number, cz: number): ScatterPoint2[] {
  const x0 = cx * SCATTER_CELL_M
  const z0 = cz * SCATTER_CELL_M
  const x1 = x0 + SCATTER_CELL_M
  const z1 = z0 + SCATTER_CELL_M
  return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]
}

/**
 * Every cell whose square meets the world box `minX..maxX` × `minZ..maxZ`,
 * row-major (z outer, x inner) — a stable order a smoke can name.
 *
 * The box is inclusive on both ends: a rectangle that ends exactly on a cell
 * border still meets the cell behind it, which is the harmless half of the
 * choice (one row of cells too many is props nobody sees; one row too few is a
 * bare strip at the edge of the picture).
 */
export function scatterCellsInBox(minX: number, minZ: number,
                                  maxX: number, maxZ: number,
                                  maxCells: number = SCATTER_CELLS_MAX
): [number, number][] {
  if (![minX, minZ, maxX, maxZ].every((v) => Number.isFinite(v))) return []
  if (maxX < minX || maxZ < minZ) return []
  const firstX = scatterCellAt(minX)
  const lastX = scatterCellAt(maxX)
  const firstZ = scatterCellAt(minZ)
  const lastZ = scatterCellAt(maxZ)
  const cols = lastX - firstX + 1
  const rows = lastZ - firstZ + 1
  if (!(cols > 0) || !(rows > 0) || cols * rows > maxCells) return []
  const out: [number, number][] = []
  for (let cz = firstZ; cz <= lastZ; cz += 1) {
    for (let cx = firstX; cx <= lastX; cx += 1) out.push([cx, cz])
  }
  return out
}

/** Cells per side of a camera window, from the distance beyond which nothing
 *  of the scatter is drawn: `k = ceil(cullM / 64)`, at least one.
 *
 *  The window is the SQUARE of cells `k` to each side of the anchor's OWN
 *  cell, which is what makes it change only when the anchor crosses a cell
 *  border — a set derived from a circle would gain and lose corner cells every
 *  few metres and rebuild the world's props with them. From anywhere inside
 *  its own cell the anchor is at least `k · 64` m from the far edge of that
 *  square, so everything within `cullM` is covered whatever corner of the cell
 *  it stands in. */
export function scatterCellSpan(cullM: number): number {
  const cull = Number(cullM)
  if (!Number.isFinite(cull) || cull <= 0) return 1
  return Math.max(1, Math.min(Math.ceil(cull / SCATTER_CELL_M),
                              Math.floor(Math.sqrt(SCATTER_CELLS_MAX) / 2)))
}

/** The window of cells a camera at (x, z) needs, given its cull distance —
 *  `(2k+1)^2` cells around the anchor's own cell, row-major like
 *  `scatterCellsInBox`. */
export function wantedScatterCells(x: number, z: number,
                                   cullM: number): [number, number][] {
  if (!Number.isFinite(x) || !Number.isFinite(z)) return []
  const k = scatterCellSpan(cullM)
  const cx = scatterCellAt(x)
  const cz = scatterCellAt(z)
  const out: [number, number][] = []
  for (let dz = -k; dz <= k; dz += 1) {
    for (let dx = -k; dx <= k; dx += 1) out.push([cx + dx, cz + dz])
  }
  return out
}

/** What `scatterCellInstances` needs to know. */
export interface ScatterCellOptions {
  /** the CLEANED world ring of the painted area — the FILTER, not the sampled
   *  box: a point belongs to this area when it lies inside it. */
  ring: readonly ScatterPoint2[]
  /** the cell, as index pair */
  cx: number
  cz: number
  /** instances per 100 m2 of ground — the authored number, unscaled */
  densityPer100m2: number
  /** `scatterCellSeed(area.id, index, cx, cz)` */
  seed: string
  /** kept clear, exactly as in `scatterInstances` (finding B18) */
  footprints?: readonly ScatterFootprint[]
  /** the instance's horizontal half-extent, exactly as in
   *  `scatterInstances` — see `scatterClearM` */
  clearM?: number
  /** the cleaned rings of the areas painted ABOVE this one */
  occluders?: readonly (readonly ScatterPoint2[])[]
  /** the per-cell guard; defaults to `SCATTER_MAX_PER_CELL` */
  maxPoints?: number
  /** active model variants of this entry's prop — see
   *  `ScatterSampleOptions.variantCount`. The seed the mix is drawn from is
   *  this CELL's (`seed` above), so every cell of a wood mixes its own way. */
  variantCount?: number
  /** the random stream, for the smoke check only — see `ScatterSampleOptions` */
  rng?: () => number
}

/**
 * The instances of ONE entry in ONE cell — the authored scatter's placement
 * since 2026-08-19.
 *
 *     wanted = min( round(4096 / 100 · density), SCATTER_MAX_PER_CELL )
 *
 * over the CELL's own box, one try per wanted instance, and then only the
 * points that lie inside the painted area are kept. A cell that is half wood
 * and half meadow therefore carries two entries' worth of props, each at its
 * own full density over its own half, and the seam is the painted border and
 * nothing else.
 *
 * The density no longer depends on how big the shape is — which is the whole
 * defect this replaces — and the count of a camera window depends on the
 * window alone: `(2k+1)^2 · 40.96 · density` for one entry.
 */
export function scatterCellInstances(opts: ScatterCellOptions): ScatterInstance[] {
  const ring = opts.ring ?? []
  if (ring.length < 3) return []
  const points = scatterInstances({
    ring: scatterCellRing(opts.cx, opts.cz),
    areaM2: SCATTER_CELL_M * SCATTER_CELL_M,
    densityPer100m2: opts.densityPer100m2,
    seed: opts.seed,
    footprints: opts.footprints,
    clearM: opts.clearM,
    occluders: opts.occluders,
    maxPoints: opts.maxPoints ?? SCATTER_MAX_PER_CELL,
    // ONE TRY PER WANTED INSTANCE, and that is the difference between sampling
    // a CELL and sampling a shape: the ring IS the box, so nothing is ever
    // re-rolled for missing it, and the only rejections left are the ones that
    // must SUBTRACT — a building's footprint, ground painted over this area.
    // Re-rolling those would squeeze a whole cell's props into the part of it
    // that is still visible, i.e. double the density against the wall of a
    // house.
    triesPerPoint: 1,
    variantCount: opts.variantCount,
    rng: opts.rng,
  })
  // …and the painted shape decides which of them are ITS props. The filter
  // runs AFTER the sampling, never as a smaller box: the stream of a cell must
  // not depend on which areas happen to reach into it.
  return points.filter((p) => pointInRing(p.x, p.z, ring))
}
