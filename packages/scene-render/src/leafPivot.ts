/**
 * The DOOR LEAF's hinge pivot — ruling R13 (2026-08-28), spec-picture-props.md § 6.
 *
 * A door prop that Blender has split carries its leaf as the glTF node `leaf`,
 * and the payload states that node's box (`door.leaf_bbox`) in RAW y-up model
 * metres. Only the leaf swings; a renderer hangs the node in a pivot group
 * and turns that group. THIS is the one place that says where the pivot goes
 * and which way its axis points — both renderers (client3d `hangLeafPivot`,
 * the admin viewer's test swing) call it, so the leaf cannot swing about two
 * different lines.
 *
 * THE FRAME THE RULE LIVES IN. `place()` seats a `fit` model on the −x edge
 * of its box AFTER the orientation fix (`bFix` is measured with `fix.rotation`
 * applied, `fix.position.x = −bFix.min.x`), and the server turns a
 * right-hinged door 180° about that very edge — so the hinge is always the
 * FIXED frame's min.x side, for both hinges (ruling R12). The pivot, however,
 * has to be inserted BELOW the fix, beside the leaf node, in raw model
 * coordinates. So the rule is stated in the fixed frame and mapped back:
 *
 *   1. rotate the 8 corners of `leaf_bbox` by the fix rotation R,
 *   2. in that frame take x = min, y = min, z = centre of the rotated box,
 *   3. map the point back with R⁻¹ — that is the pivot's raw position,
 *   4. the axis is R⁻¹ · (0, 1, 0) — the fixed frame's vertical, expressed
 *      in raw coordinates (a tilt fix makes it non-vertical in raw space).
 *
 * Fix 0 reproduces R12 exactly: (min.x, min.y, centre z), axis +y.
 *
 * R IS `place()`'s EULER, order 'YXZ': three's `makeRotationFromEuler` for
 * that order is R = Ry(y) · Rx(x) · Rz(z) (column vectors), degrees in, the
 * fine angles (the seating datum uses the real fix, not the 90° snap). The
 * inverse of a rotation is its transpose. Pure array maths — `three` is
 * never imported by this package.
 *
 * Why this cannot stay `min.x` of the raw box: a y-fix of 180° puts the
 * fixed −x edge on raw max.x (the FREE edge — the leaf would swing through
 * the frame), a 90° y-fix picks a z edge, and any x/z fix tilts the axis.
 */

/** `door.leaf_bbox` / the prop's `leaf_bbox`. */
export interface LeafBox {
  min: [number, number, number]
  max: [number, number, number]
}

/** The orientation fix in DEGREES, as `models[].fix_euler` carries it. */
export interface FixEuler {
  x?: number
  y?: number
  z?: number
}

export interface LeafPivotSpec {
  /** Pivot position in RAW model space (the leaf node's parent frame). */
  point: [number, number, number]
  /** Unit axis in RAW model space a positive swing turns about. */
  axis: [number, number, number]
}

type Mat3 = [[number, number, number], [number, number, number], [number, number, number]]

const deg = (v?: number) => ((v || 0) * Math.PI) / 180

/** R = Ry · Rx · Rz for `fix` (three.js Euler order 'YXZ', degrees). */
export function fixMatrix(fix?: FixEuler | null): Mat3 {
  const a = Math.cos(deg(fix?.x)), b = Math.sin(deg(fix?.x))
  const c = Math.cos(deg(fix?.y)), d = Math.sin(deg(fix?.y))
  const e = Math.cos(deg(fix?.z)), f = Math.sin(deg(fix?.z))
  // Exactly three's makeRotationFromEuler('YXZ'), written row-major.
  return [
    [c * e + d * f * b, d * e * b - c * f, a * d],
    [a * f, a * e, -b],
    [c * f * b - d * e, d * f + c * e * b, a * c],
  ]
}

function apply(m: Mat3, v: [number, number, number]): [number, number, number] {
  return [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
  ]
}

function transpose(m: Mat3): Mat3 {
  return [
    [m[0][0], m[1][0], m[2][0]],
    [m[0][1], m[1][1], m[2][1]],
    [m[0][2], m[1][2], m[2][2]],
  ]
}

/** `−0` is noise a payload or a test never wants to see. */
const clean = (v: number) => (Math.abs(v) < 1e-12 ? 0 : v)

/**
 * Where the leaf's pivot goes and which way it turns, in RAW model space —
 * see the module docstring for the rule and its reason.
 */
export function leafPivot(bbox: LeafBox, fix?: FixEuler | null): LeafPivotSpec {
  const R = fixMatrix(fix)
  const Rt = transpose(R)
  const corners: Array<[number, number, number]> = []
  for (const x of [bbox.min[0], bbox.max[0]]) {
    for (const y of [bbox.min[1], bbox.max[1]]) {
      for (const z of [bbox.min[2], bbox.max[2]]) corners.push(apply(R, [x, y, z]))
    }
  }
  let minX = Infinity, minY = Infinity, minZ = Infinity, maxZ = -Infinity
  for (const [x, y, z] of corners) {
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  const point = apply(Rt, [minX, minY, (minZ + maxZ) / 2])
  const axis = apply(Rt, [0, 1, 0])
  return {
    point: [clean(point[0]), clean(point[1]), clean(point[2])],
    axis: [clean(axis[0]), clean(axis[1]), clean(axis[2])],
  }
}
