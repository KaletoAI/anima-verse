/**
 * Terrain relief of a detail scene (contract v5.2 § B1 Nr. 14) — the ONE
 * height sampler both renderers use.
 *
 * The server ships a 17 × 17 grid of support points over the location's
 * reference square and has ALREADY lifted everything that stands in a
 * non-flat room: prop `bottom_y`, diorama `bottom_y`, marker `y_world`,
 * exit points. A renderer must therefore never sample an object height
 * again — it would count the lift twice. What is left for the renderers is
 * exactly two things:
 *
 *   1. **drape the ground** — the tile's own plate and every scene plate
 *      flagged `relief: true` follow the field instead of lying flat, and
 *   2. **stand figures on it** — a figure walks on ground the payload never
 *      describes as a number, so its Y is sampled here.
 *
 * Between the support points the field is BILINEAR, and it has to be
 * bilinear the same way in Python (`scatter_curves.terrain_height`) and
 * here: a prop the server lifted by 0.30 m sitting on ground the client
 * drapes to 0.28 m is exactly the drift this shared module exists to
 * prevent. The formula is hand-checkable per § B5a.
 *
 * `three` is a PARAMETER here as everywhere in this package (see clip.ts /
 * cutouts.ts) — the admin loads the library lazily and must not pull it into
 * its main bundle.
 */
import type { BufferAttribute, BufferGeometry, Matrix4 } from 'three'
import type { SceneTerrain } from './types'

/** Cells per axis of the height field — 16 cells, 17 support points. The
 *  grid itself carries the number; this is only the fallback for a payload
 *  that arrives without one. */
export const TERRAIN_CELLS = 16

/**
 * Height of the relief at a point in payload coordinates (world metres
 * around the tile centre), in world metres.
 *
 * Plan fraction from world offset: `u = x / extent + 0.5`, `v = z / extent
 * + 0.5`, both clamped to [0, 1] — outside the reference square the border
 * value applies, and the border is pinned to 0 by the composer so that
 * neighbouring tiles meet seamlessly.
 *
 * Cell and fraction exactly as the contract states, with `n` taken from the
 * delivered grid (`grid.length − 1`, the default 16 only when the payload
 * says so): `i = min(floor(u·n), n − 1)`, `fx = u·n − i` (`j`/`v` likewise),
 * then the bilinear mix of `grid[j][i]`, `grid[j][i+1]`, `grid[j+1][i]`,
 * `grid[j+1][i+1]`.
 */
export function sampleTerrain(terrain: SceneTerrain | null | undefined,
                              x: number, z: number, extent: number): number {
  const grid = terrain?.grid
  if (!grid || grid.length < 2 || !extent) return 0
  const n = grid.length - 1
  const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)
  const fx = clamp01(x / extent + 0.5) * n
  const fz = clamp01(z / extent + 0.5) * n
  const i = Math.min(Math.floor(fx), n - 1)
  const j = Math.min(Math.floor(fz), n - 1)
  const tx = fx - i
  const tz = fz - j
  const rowN = grid[j] || []
  const rowS = grid[j + 1] || []
  const north = (rowN[i] || 0) * (1 - tx) + (rowN[i + 1] || 0) * tx
  const south = (rowS[i] || 0) * (1 - tx) + (rowS[i + 1] || 0) * tx
  return north * (1 - tz) + south * tz
}

/** One uniform 1 → 4 split of every triangle. Positions and UVs are
 *  interpolated linearly, which is exact for both geometries this is used on
 *  (a plane's UV and a shape's UV are affine in the position).
 *
 *  Non-indexed on purpose: two triangles sharing an edge compute the SAME
 *  midpoint from the same two endpoints — floating-point addition is
 *  commutative, so the seam stays watertight without a midpoint cache. */
function splitOnce(pos: number[], uv: number[] | null): [number[], number[] | null] {
  const outP: number[] = []
  const outU: number[] | null = uv ? [] : null
  const mid3 = (a: number, b: number) => [
    (pos[a] + pos[b]) / 2, (pos[a + 1] + pos[b + 1]) / 2, (pos[a + 2] + pos[b + 2]) / 2,
  ]
  const mid2 = (a: number, b: number) => [
    (uv![a] + uv![b]) / 2, (uv![a + 1] + uv![b + 1]) / 2,
  ]
  const pushP = (v: number[]) => outP.push(v[0], v[1], v[2])
  const at3 = (i: number) => [pos[i], pos[i + 1], pos[i + 2]]
  const at2 = (i: number) => [uv![i], uv![i + 1]]
  for (let t = 0, u = 0; t < pos.length - 8; t += 9, u += 6) {
    const a = t, b = t + 3, c = t + 6
    const ab = mid3(a, b), bc = mid3(b, c), ca = mid3(c, a)
    pushP(at3(a)); pushP(ab); pushP(ca)
    pushP(ab); pushP(at3(b)); pushP(bc)
    pushP(ca); pushP(bc); pushP(at3(c))
    pushP(ab); pushP(bc); pushP(ca)
    if (!outU) continue
    const ua = u, ub = u + 2, uc = u + 4
    const uab = mid2(ua, ub), ubc = mid2(ub, uc), uca = mid2(uc, ua)
    outU.push(...at2(ua), ...uab, ...uca)
    outU.push(...uab, ...at2(ub), ...ubc)
    outU.push(...uca, ...ubc, ...at2(uc))
    outU.push(...uab, ...ubc, ...uca)
  }
  return [outP, outU]
}

/** Longest triangle edge of a flat position list — decides how often the
 *  geometry has to be split before it can follow the field at all. A plate
 *  built as two big triangles would otherwise "drape" by moving four corners. */
function longestEdge(pos: number[]): number {
  let max = 0
  for (let t = 0; t < pos.length - 8; t += 9) {
    for (const [a, b] of [[t, t + 3], [t + 3, t + 6], [t + 6, t]] as const) {
      const d = Math.hypot(pos[a] - pos[b], pos[a + 1] - pos[b + 1],
                           pos[a + 2] - pos[b + 2])
      if (d > max) max = d
    }
  }
  return max
}

/** Ceiling on the split depth: 5 levels = 1024 triangles per original one.
 *  A plate is a handful of triangles, so this is generous; it exists so a
 *  pathological outline cannot melt the tab.
 *
 *  It also decides how FINE a height field may usefully be: a plate over the
 *  reference square starts at its diagonal e·√2, so the smallest edge this
 *  loop reaches is e·√2 / 2⁵ = e/22.63. That is why the server caps the
 *  relief at 22 cells (`RELIEF_CELLS_MAX`, app/core/scatter_curves.py) —
 *  raise one of the two and the other has to move with it. */
const MAX_SPLITS = 5

/**
 * Drape a HORIZONTAL geometry over the height field: subdivide it until no
 * edge is longer than one terrain cell, then raise every vertex by the
 * height sampled at ITS OWN world x/z.
 *
 * Returns a NEW geometry; the input is untouched and stays the caller's to
 * dispose (the tile ground plate keeps its flat original so unmounting the
 * scene can put it back).
 *
 * `transform` is the mesh's local → PAYLOAD-space matrix (`mesh.matrix`
 * after `updateMatrix()`), and it is the whole reason this takes a matrix
 * instead of two numbers: the primitives are built around their own origin
 * in a rotated frame — a plate is a shape in XY turned −90° about X, the
 * tile ground plate the same — so a vertex's local (x, y, z) is NOT its
 * world (x, z). Sampling happens after the transform, and the height is
 * added along the local direction that maps to world +Y. Omit it for a
 * geometry already lying in payload space.
 *
 * Rotation and translation only: a scaled transform would need the height
 * divided by that scale, and no caller here has one.
 */
export function drapeGeometry(THREE: typeof import('three'),
                              geometry: BufferGeometry,
                              terrain: SceneTerrain,
                              extent: number,
                              transform?: Matrix4 | null): BufferGeometry {
  const src = geometry.index ? geometry.toNonIndexed() : geometry
  let pos = Array.from(src.getAttribute('position').array as ArrayLike<number>)
  const uvSrc = src.getAttribute('uv')
  let uv = uvSrc ? Array.from(uvSrc.array as ArrayLike<number>) : null
  if (src !== geometry) src.dispose()

  const cell = terrain.step > 0 ? terrain.step : extent / TERRAIN_CELLS
  let edge = longestEdge(pos)
  for (let n = 0; n < MAX_SPLITS && edge > cell; n++) {
    ;[pos, uv] = splitOnce(pos, uv)
    edge /= 2
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  if (uv) geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))

  // The local direction that points to world +Y. For the −90° plate frame
  // that is local +Z, which is exactly the trap this resolves.
  const up = new THREE.Vector3(0, 1, 0)
  if (transform) {
    up.applyMatrix4(new THREE.Matrix4().extractRotation(transform).invert())
      .normalize()
  }
  const attr = geo.getAttribute('position') as BufferAttribute
  const p = new THREE.Vector3()
  const w = new THREE.Vector3()
  for (let i = 0; i < attr.count; i++) {
    p.fromBufferAttribute(attr, i)
    w.copy(p)
    if (transform) w.applyMatrix4(transform)
    const h = sampleTerrain(terrain, w.x, w.z, extent)
    if (h) attr.setXYZ(i, p.x + up.x * h, p.y + up.y * h, p.z + up.z * h)
  }
  attr.needsUpdate = true
  geo.computeVertexNormals()
  geo.computeBoundingSphere()
  return geo
}
