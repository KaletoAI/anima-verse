/**
 * The primitive builders of the scene contract (§ B1) — plate, wall segment,
 * typed extra box and the placeholder for a prop without a mesh.
 *
 * They lay twice before: `buildPlate`/`buildWall`/`buildPlaceholder` plus the
 * extras branch in the 3D client, and the same construction inline in the
 * admin floor-plan preview. Same numbers on both sides, kept in step only by
 * two verifies happening to check the same fields.
 *
 * THE CUT: geometry lives here, MATERIAL comes from the caller. The material
 * is where the two sides genuinely differ — the client tiles world-scale
 * surface textures with its own fallback chain, the admin paints preview
 * colours with room palette and selection highlight. `side`, `transparent`
 * and opacity are material decisions and are therefore NOT made here.
 *
 * And the trap that made this worth doing carefully: the client computes
 * around the TILE CENTRE, the admin around the ORIGIN. Every builder returns
 * geometry around its OWN origin — the payload's local coordinates — and
 * never places it in the world; that stays with the caller, exactly the way
 * `place()` solves it through its `origin` parameter.
 *
 * View state (shadow flags, culling registration, level solo) stays with the
 * caller too: it decides what its renderer does with the finished mesh.
 */
import type { BufferGeometry, Material, Mesh } from 'three'
import type { ScenePlate, SceneWall, SceneExtra } from './types'
import type { PrimitiveTarget } from './verify'

/** Length of a wall segment in world metres — the box's width, and with it
 *  the world scale of the uvs on its broad faces. */
export function wallLength(wall: SceneWall): number {
  return Math.hypot(wall.to[0] - wall.from[0], wall.to[1] - wall.from[1])
}

/**
 * Floor plate from a finished primitive: `thickness > 0` = a body extruded
 * DOWNWARD with its top face on `top_y`, `thickness` 0 = a bare texture
 * surface without a body (outdoor rooms, § A5).
 *
 * The shape plane maps to world XZ after the rotation. An extruded plate goes
 * in as (x, z) and turns +90° (the extrusion then runs downward), a flat one
 * as (x, −z) with −90°.
 *
 * `plate.holes` (contract addendum "Treppen v2") are taken OUT of the shape:
 * every ring becomes a `Path` in `shape.holes`, which both `ShapeGeometry` and
 * `ExtrudeGeometry` honour — the extrusion even caps the walls of the opening,
 * so a stairwell looks like a stairwell from below. THE SIGN OF THE SECOND
 * COORDINATE IS THE SAME AS THE OUTER RING'S: a hole written with the other
 * sign would land mirrored about z = 0, which on a plate that straddles the
 * anchor pin is a hole in the wrong half of the room rather than an obvious
 * error. Winding is NOT this function's business — three normalises the rings
 * against each other in both geometry classes.
 */
export function buildPlate(THREE: typeof import('three'),
                           plate: ScenePlate, material: Material): Mesh {
  const solid = plate.thickness > 0
  /** One closed ring into a shape or a hole path, in the plate's own plane. */
  const ring = (into: { moveTo(x: number, y: number): unknown
                        lineTo(x: number, y: number): unknown
                        closePath(): unknown },
                points: readonly [number, number][]) => {
    points.forEach(([px, pz], i) => {
      const sy = solid ? pz : -pz
      if (i === 0) into.moveTo(px, sy)
      else into.lineTo(px, sy)
    })
    into.closePath()
  }
  const shape = new THREE.Shape()
  ring(shape, plate.outline)
  for (const hole of plate.holes) {
    // Fewer than three points enclose nothing — the same rule the outline
    // itself is filtered by, and an empty `Path` would break the triangulation
    // of the ring around it.
    if (hole.length < 3) continue
    const path = new THREE.Path()
    ring(path, hole)
    shape.holes.push(path)
  }
  const mesh = new THREE.Mesh(
    solid
      ? new THREE.ExtrudeGeometry(shape, { depth: plate.thickness, bevelEnabled: false })
      : new THREE.ShapeGeometry(shape),
    material)
  mesh.rotation.x = solid ? Math.PI / 2 : -Math.PI / 2
  mesh.position.y = plate.top_y
  return mesh
}

/**
 * The six faces of a `BoxGeometry(width, height, depth)` in three's own build
 * order, each as the extent its u and v axis span IN METRES.
 *
 * Read off `node_modules/three/src/geometries/BoxGeometry.js` (0.185), whose
 * `buildPlane(u, v, w, …, width, height, …)` calls are, in order:
 *
 *   px, nx  →  u = 'z' over `depth`,  v = 'y' over `height`
 *   py, ny  →  u = 'x' over `width`,  v = 'z' over `depth`
 *   pz, nz  →  u = 'x' over `width`,  v = 'y' over `height`
 *
 * At default segmentation every face contributes 4 vertices, in that order,
 * and its uvs run `ix / gridX`, `1 - iy / gridY` — i.e. 0..1 PER FACE,
 * regardless of how many metres the face actually measures. That
 * normalisation is the whole problem this table exists to undo.
 */
function boxFaceExtents(width: number, height: number, depth: number):
    Array<[number, number]> {
  return [
    [depth, height], [depth, height],   // px, nx
    [width, depth], [width, depth],     // py, ny
    [width, height], [width, height],   // pz, nz
  ]
}

/**
 * Rewrite a wall box's UVs to WORLD SCALE — the tiling belongs here, not on
 * `material.map.repeat`.
 *
 * WHY: a repeat set on the material applies to all six faces alike, but the
 * only face it is ever computed from is the broad wall face. Every narrow
 * face of the box — a door jamb, a window reveal, the underside of a lintel,
 * the top of a sill — is only `thickness` deep (~0.07 m) and gets the same
 * 0..1 uv range, so the same repeat squeezes the texture there by the ratio of
 * the extents: on a 10.2624 m segment the 0.07 m jamb was tiled 147x across
 * its width. That is what reads as "warped" frames around doors and windows.
 *
 * Scaling the uvs by the face's OWN extent divided by the tile size gives
 * every face the same metres-per-tile, and the caller's texture then keeps a
 * repeat of (1, 1). `RepeatWrapping` still has to be set on the texture — the
 * numbers here leave 0..1 as soon as a face is longer than one tile.
 *
 * A `tileM` of 0 (no texture, or a plain colour) leaves the geometry alone.
 */
export function applyWorldScaleWallUVs(geometry: BufferGeometry, len: number,
                                       height: number, thickness: number,
                                       tileM: number): void {
  if (!(tileM > 0)) return
  const uv = geometry.getAttribute('uv')
  // 6 faces x 4 vertices. Anything else is not the box `buildWall` builds, and
  // guessing at a segmented layout would be worse than leaving it untouched.
  if (!uv || uv.count !== 24) return
  const faces = boxFaceExtents(len, height, thickness)
  for (let f = 0; f < 6; f++) {
    const [su, sv] = faces[f]
    for (let i = f * 4; i < f * 4 + 4; i++) {
      uv.setXY(i, uv.getX(i) * (su / tileM), uv.getY(i) * (sv / tileM))
    }
  }
  uv.needsUpdate = true
}

/**
 * Wall segment from a finished primitive: doors and passages are already
 * gaps, a window arrives as sill + head plus its own glass entry, a door as
 * its cheeks + lintel plus its own LEAF entry — one box each, nothing is
 * split here. Length and angle come from `from`/`to`, the centre from their
 * midpoint.
 *
 * `tileM` is the world size of one texture tile in metres. Passing it moves
 * the tiling into the uvs (see `applyWorldScaleWallUVs`); the caller then
 * leaves its texture repeat at (1, 1). Omitting it (untextured wall, glass
 * band) leaves the box's default per-face 0..1 uvs.
 *
 * Zero-length segments are the caller's business (it usually skips them
 * before building a material); a box of length 0 is what it would get here.
 */
export function buildWall(THREE: typeof import('three'),
                          wall: SceneWall, material: Material,
                          tileM = 0): Mesh {
  const len = wallLength(wall)
  const geometry = new THREE.BoxGeometry(len, wall.height, wall.thickness)
  applyWorldScaleWallUVs(geometry, len, wall.height, wall.thickness, tileM)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.position.set((wall.from[0] + wall.to[0]) / 2,
                    wall.base_y + wall.height / 2,
                    (wall.from[1] + wall.to[1]) / 2)
  // THIS MINUS STAYS, and it is NOT the yaw sign of § A1.1.
  //
  // It is the inverse of the very rotation the yaw flip settled on. Under
  // `rotation.y = θ` three.js maps the box's own +x axis to the world direction
  // (cos θ, 0, −sin θ). The segment has to run along (dx, dz) = to − from, so
  //     cos θ = dx/len   and   −sin θ = dz/len   ⇒   θ = −atan2(dz, dx).
  // Nothing here reads a delivered ANGLE whose convention could be changed:
  // `from`/`to` are payload COORDINATES, unchanged by E4, and the angle is
  // derived from them. Flipping the sign would mirror every wall that is not
  // axis-parallel about the segment's midpoint (an axis-parallel one would look
  // unchanged — a box is symmetric under 180° — which is exactly why this had to
  // be derived and not eyeballed).
  mesh.rotation.y = -Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0])
  return mesh
}

/**
 * Typed extra box (the elevator's shaft, glass, pads and cabin) — centre plus
 * size, already in world metres. Each part is its OWN payload entry, so this
 * builds one box per entry; which part it is only decides the material, and
 * that is the caller's.
 */
export function buildExtra(THREE: typeof import('three'),
                           extra: SceneExtra, material: Material): Mesh {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(extra.size[0], extra.size[1], extra.size[2]), material)
  mesh.position.set(extra.center[0], extra.center[1], extra.center[2])
  return mesh
}

/**
 * Placeholder for a prop without a mesh: a box in the delivered dimensions
 * (already world metres), origin at the CENTRE OF ITS BOTTOM FACE — so the
 * caller seats it on `bottom_y` directly, the same anchor a placed mesh gets.
 * Degenerate dimensions are clamped to 1 cm; a placement is never dropped
 * (§ A2), so it must stay visible.
 */
export function buildPlaceholder(THREE: typeof import('three'),
                                 dims: { w: number; d: number; h: number },
                                 material: Material): Mesh {
  const w = Math.max(dims.w, 0.01)
  const h = Math.max(dims.h, 0.01)
  const d = Math.max(dims.d, 0.01)
  const geo = new THREE.BoxGeometry(w, h, d)
  geo.translate(0, h / 2, 0)
  return new THREE.Mesh(geo, material)
}

// ── The target fields of the verify (§ B5a) ──────────────────────────────
// The last numbers that were still written down twice. They belong to the
// primitive, not to the report: what a plate or a wall must measure follows
// from the payload alone, so it is settled here once for both renderers.

/** Plate: top face on `top_y`; a body additionally has its bottom face one
 *  thickness below it.
 *
 *  Every plate is verifiable now: the `relief` exception died with the scene's
 *  own height field ("Ein Boden" E5a, decision 1) — a plate that followed a
 *  lattice had no stated world box, and there is no such plate any more. What
 *  is left in `plates` is a declared storey, and a storey is flat.
 *
 *  A HOLE CHANGES NOTHING HERE (decision "Treppen v2"): the opening is taken
 *  out of the INSIDE of the outline, so the plate's bounding box is the
 *  outline's either way — the verify keeps measuring the same two numbers. */
export function plateTargets(plate: ScenePlate): PrimitiveTarget[] {
  const targets: PrimitiveTarget[] = [
    { field: 'top_y', actual: (b) => b.max.y, target: plate.top_y },
  ]
  if (plate.thickness > 0) {
    targets.push({ field: 'bottom_y', actual: (b) => b.min.y,
                   target: plate.top_y - plate.thickness })
  }
  return targets
}

/** Wall: foot and top edge from `base_y`/`height`, centre from the midpoint
 *  of `from`/`to`. */
export function wallTargets(wall: SceneWall): PrimitiveTarget[] {
  return [
    { field: 'base_y', actual: (b) => b.min.y, target: wall.base_y },
    { field: 'top_y', actual: (b) => b.max.y, target: wall.base_y + wall.height },
    { field: 'centre.x', actual: (b) => (b.min.x + b.max.x) / 2,
      target: (wall.from[0] + wall.to[0]) / 2 },
    { field: 'centre.z', actual: (b) => (b.min.z + b.max.z) / 2,
      target: (wall.from[1] + wall.to[1]) / 2 },
  ]
}
