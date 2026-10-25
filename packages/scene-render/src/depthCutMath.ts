import type { SceneCutPlane } from './types'
/** Pure world plane. Matrix is column-major, matching the scene frame transform.
 * The payload normal is normalized before applying its unchanged constant. */
export function cutPlaneData(cut?: SceneCutPlane | null, matrix?: number[] | null):
    { normal: [number, number, number]; constant: number } | null {
  if (!cut?.normal) return null
  const length = Math.hypot(...cut.normal)
  if (length * length < 1e-9) return null
  const n = cut.normal.map(v => v / length)
  if (!matrix) return { normal: n as [number, number, number], constant: cut.constant }
  const m = matrix
  // Cofactors are det(A) times inverse-transpose(A).
  const c = [
    m[5]*m[10]-m[9]*m[6], m[9]*m[2]-m[1]*m[10], m[1]*m[6]-m[5]*m[2],
    m[8]*m[6]-m[4]*m[10], m[0]*m[10]-m[8]*m[2], m[4]*m[2]-m[0]*m[6],
    m[4]*m[9]-m[8]*m[5], m[8]*m[1]-m[0]*m[9], m[0]*m[5]-m[4]*m[1],
  ]
  const det = m[0]*c[0] + m[4]*c[1] + m[8]*c[2]
  if (det === 0) return { normal: [0, 0, 0], constant: 0 }
  const w = [0,1,2].map(i => (c[i*3]*n[0] + c[i*3+1]*n[1] + c[i*3+2]*n[2]) / det)
  const l = Math.hypot(...w)
  const normal = w.map(v => v/l) as [number,number,number]
  const p = n.map(v => -cut.constant*v)
  const world = [0,1,2].map(i => m[i]*p[0] + m[i+4]*p[1] + m[i+8]*p[2] + m[i+12])
  return { normal, constant: -(normal[0]*world[0] + normal[1]*world[1] + normal[2]*world[2]) }
}
