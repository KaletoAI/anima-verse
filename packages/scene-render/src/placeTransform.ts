/** Three-free placement arithmetic. Matrices are column-major, like glTF. */
import type { SceneModelSpec } from './types'
export type Point3 = [number, number, number]
export interface MeshBox { min: number[]; max: number[]; matrix?: number[] }
export interface PlaceTransform {
  fixPos: Point3; fitScale: Point3; outerScale: number; outerPos: Point3
}
const rad = (v = 0) => v * Math.PI / 180
function rotate(p: Point3, x: number, y: number, z: number): Point3 {
  // Euler YXZ: R_y R_x R_z, so roll acts first.
  const a = p[0] * Math.cos(z) - p[1] * Math.sin(z)
  const b = p[0] * Math.sin(z) + p[1] * Math.cos(z)
  const c = b * Math.sin(x) + p[2] * Math.cos(x)
  return [a * Math.cos(y) + c * Math.sin(y),
    b * Math.cos(x) - p[2] * Math.sin(x), -a * Math.sin(y) + c * Math.cos(y)]
}
export function placeTransform(spec: SceneModelSpec, meshBoxes: MeshBox[]): PlaceTransform {
  const points: Point3[] = []
  for (const box of meshBoxes) for (const x of [box.min[0], box.max[0]])
    for (const y of [box.min[1], box.max[1]]) for (const z of [box.min[2], box.max[2]]) {
      const m = box.matrix
      if (!m) points.push([x, y, z])
      else {
        const w = 1 / (m[3] * x + m[7] * y + m[11] * z + m[15])
        points.push([(m[0]*x+m[4]*y+m[8]*z+m[12])*w,
          (m[1]*x+m[5]*y+m[9]*z+m[13])*w, (m[2]*x+m[6]*y+m[10]*z+m[14])*w])
      }
    }
  const f = spec.fix_euler
  const snapped = [f?.x, f?.y, f?.z].map(v => rad(Math.round((v || 0)/90)*90))
  const actual = [rad(f?.x), rad(f?.y), rad(f?.z)]
  const bounds = (ps: Point3[]) => {
    const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity]
    for (const p of ps) for (let i=0;i<3;i++) { min[i]=Math.min(min[i],p[i]); max[i]=Math.max(max[i],p[i]) }
    return { min, max, size: min.map((v,i) => ps.length ? max[i]-v : 0),
      centre: min.map((v,i) => ps.length ? (max[i]+v)/2 : 0) }
  }
  const sObj = bounds(points.map(p => rotate(p, snapped[0], snapped[1], snapped[2]))).size
  const yaw = rad(spec.yaw_deg)
  const sYaw = bounds(points.map(p => rotate(rotate(p, snapped[0], snapped[1], snapped[2]),0,yaw,0))).size
  const fixed = points.map(p => rotate(p, actual[0], actual[1], actual[2]))
  const b = bounds(fixed), fit = spec.measure === 'fit'
  const fixPos: Point3 = [fit ? -b.min[0] : -b.centre[0], fit ? -b.min[1] : -b.centre[1], -b.centre[2]]
  const sx = (spec.size_m?.[0] || 1)/(sObj[0] || 1)
  const fitScale: Point3 = fit ? [sx,(spec.size_m?.[1] || 1)/(sObj[1] || 1),sx] : [1,1,1]
  const extent = (spec.measure === 'yawed_xz' ? Math.max(sYaw[0],sYaw[2]) : spec.measure === 'xz' ? Math.max(sObj[0],sObj[2]) : Math.max(...sObj)) || 1
  const outerScale = fit ? 1 : (spec.max_m || 1)/extent
  const bottom = bounds(fixed.map(p => rotate(p.map((v,i)=>(v+fixPos[i])*fitScale[i]) as Point3,0,yaw,0).map(v=>v*outerScale) as Point3)).min[1]
  return { fixPos, fitScale, outerScale, outerPos: [spec.anchor[0],spec.bottom_y-bottom,spec.anchor[1]] }
}
