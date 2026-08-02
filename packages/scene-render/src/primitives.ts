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
import type { Material, Mesh } from 'three'
import type { ScenePlate, SceneWall, SceneExtra } from './types'
import type { PrimitiveTarget } from './verify'

/** Length of a wall segment in world metres — the one number both the
 *  geometry and the caller's texture repeat are built from. */
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
 */
export function buildPlate(THREE: typeof import('three'),
                           plate: ScenePlate, material: Material): Mesh {
  const solid = plate.thickness > 0
  const shape = new THREE.Shape()
  plate.outline.forEach(([px, pz], i) => {
    const sy = solid ? pz : -pz
    if (i === 0) shape.moveTo(px, sy)
    else shape.lineTo(px, sy)
  })
  shape.closePath()
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
 * Wall segment from a finished primitive: doors and passages are already
 * gaps, a window arrives as sill + head plus its own glass entry — one box
 * each, nothing is split here. Length and angle come from `from`/`to`, the
 * centre from their midpoint.
 *
 * Zero-length segments are the caller's business (it usually skips them
 * before building a material); a box of length 0 is what it would get here.
 */
export function buildWall(THREE: typeof import('three'),
                          wall: SceneWall, material: Material): Mesh {
  const len = wallLength(wall)
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(len, wall.height, wall.thickness), material)
  mesh.position.set((wall.from[0] + wall.to[0]) / 2,
                    wall.base_y + wall.height / 2,
                    (wall.from[1] + wall.to[1]) / 2)
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
 *  A `relief` plate has NO such target: the renderer deforms it over the
 *  height field (v5.2 Nr. 14), so its world box reaches from `top_y` minus
 *  the deepest dip to `top_y` plus the highest rise — a range the payload
 *  does not state as a number. The verifiable numbers of the relief are the
 *  ones the composer already applied (prop `bottom_y`, marker `y_world`) and
 *  the field itself, both checked in the server-side smoke test. */
export function plateTargets(plate: ScenePlate): PrimitiveTarget[] {
  if (plate.relief) return []
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
