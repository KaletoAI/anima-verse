/**
 * Prop dims geometry — the client half of the size model (plan-room-props.md).
 *
 * Kept in LOCKSTEP with `oriented_dims` in app/core/props.py: same Euler
 * order, same corner rotation, same rounding — change both or neither.
 */

/**
 * `[width(x), height(y), depth(z)]` = the AABB extents of the raw mesh box
 * AFTER the orientation fix: the 8 corners are rotated by Rx·Ry·Rz (degrees,
 * three.js 'XYZ' order) and re-measured.
 *
 * Rotating an AABB overestimates for non-90° fixes (it measures a box around
 * the box), which is fine and deterministic — these numbers are used as
 * PROPORTIONS, not as a hull.
 */
export function orientedDims(bbox: [number, number, number],
  rot?: { x?: number; y?: number; z?: number }): [number, number, number] {
  const b = bbox.map((v) => Math.abs(Number(v) || 0))
  const rad = (v?: number) => ((Number(v) || 0) * Math.PI) / 180
  const rx = rad(rot?.x)
  const ry = rad(rot?.y)
  const rz = rad(rot?.z)
  const cx = Math.cos(rx), sx = Math.sin(rx)
  const cy = Math.cos(ry), sy = Math.sin(ry)
  const cz = Math.cos(rz), sz = Math.sin(rz)
  // M = Rx · Ry · Rz
  const m = [
    [cy * cz, -cy * sz, sy],
    [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
    [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
  ]
  const half = b.map((v) => v / 2)
  const lo = [Infinity, Infinity, Infinity]
  const hi = [-Infinity, -Infinity, -Infinity]
  for (const i of [-1, 1]) {
    for (const j of [-1, 1]) {
      for (const k of [-1, 1]) {
        const p = [i * half[0], j * half[1], k * half[2]]
        for (let r = 0; r < 3; r++) {
          const v = m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2]
          if (v < lo[r]) lo[r] = v
          if (v > hi[r]) hi[r] = v
        }
      }
    }
  }
  const r5 = (v: number) => Math.round(v * 100000) / 100000
  return [r5(hi[0] - lo[0]), r5(hi[1] - lo[1]), r5(hi[2] - lo[2])]
}
