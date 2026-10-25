/** Three-free primitive transforms. Coordinates remain in payload-local metres. */
import type { SceneExtra, ScenePlate, SceneWall } from './types'

export function wallTransform(wall: SceneWall): { size: [number, number, number]; position: [number, number, number]; yaw: number } {
  const dx = wall.to[0] - wall.from[0], dz = wall.to[1] - wall.from[1]
  return { size: [Math.hypot(dx, dz), wall.height, wall.thickness],
    position: [(wall.from[0] + wall.to[0]) / 2, wall.base_y + wall.height / 2,
      (wall.from[1] + wall.to[1]) / 2], yaw: -Math.atan2(dz, dx) }
}

/** Three BoxGeometry order: px, nx, py, ny, pz, nz. */
export function boxFaceExtents(width: number, height: number, depth: number): Array<[number, number]> {
  return [[depth, height], [depth, height], [width, depth], [width, depth], [width, height], [width, height]]
}
export function boxFaceUVs(width: number, height: number, depth: number, tileM: number): Array<[number, number]> {
  return boxFaceExtents(width, height, depth).map(([u, v]) => tileM > 0 ? [u / tileM, v / tileM] : [1, 1])
}

export function extraRotation(extra: Pick<SceneExtra, 'rotation'>): [number, number, number] {
  const d = Math.PI / 180
  return extra.rotation ? [extra.rotation[0] * d, extra.rotation[1] * d, extra.rotation[2] * d] : [0, 0, 0]
}

/** Three's intrinsic XYZ Euler is Rx * Ry * Rz: a point turns Z, then Y, then X. */
export function extraCorners(extra: Pick<SceneExtra, 'center' | 'size' | 'rotation'>,
                             points?: readonly (readonly number[])[]): number[][] {
  const [rx, ry, rz] = extraRotation(extra)
  const [a, b, c, d, e, f] = [Math.cos(rx), Math.sin(rx), Math.cos(ry), Math.sin(ry), Math.cos(rz), Math.sin(rz)]
  const local = points ?? [-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z =>
    [x * extra.size[0] / 2, y * extra.size[1] / 2, z * extra.size[2] / 2])))
  return local.map(([x, y, z]) => {
    const zx = e * x - f * y, zy = f * x + e * y
    const yx = c * zx + d * z, yz = -d * zx + c * z
    return [yx + extra.center[0], a * zy - b * yz + extra.center[1], b * zy + a * yz + extra.center[2]]
  })
}

/** Shape-plane coordinates and extrusion rotation, including the hole-sign rule. */
export function plateShape(plate: Pick<ScenePlate, 'outline' | 'holes' | 'thickness'>): {
  solid: boolean; rotationX: number; outline: number[][]; holes: number[][][];
} {
  const solid = plate.thickness > 0
  const ring = (points: readonly (readonly number[])[]) => points.map(([x, z]) => [x, solid ? z : -z])
  return { solid, rotationX: solid ? Math.PI / 2 : -Math.PI / 2,
    outline: ring(plate.outline), holes: (plate.holes ?? []).filter(h => h.length >= 3).map(ring) }
}

export function placeholderBox(dims: { w: number; d: number; h: number }): {
  size: [number, number, number]; offset: [number, number, number]; min: [number, number, number]; max: [number, number, number];
} {
  const w = Math.max(dims.w, 0.01), h = Math.max(dims.h, 0.01), d = Math.max(dims.d, 0.01)
  return { size: [w, h, d], offset: [0, h / 2, 0], min: [-w / 2, 0, -d / 2], max: [w / 2, h, d / 2] }
}
