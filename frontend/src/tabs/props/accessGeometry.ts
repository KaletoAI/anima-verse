import { placeTransform } from '../../../../packages/scene-render/src/placeTransform'

export type AccessRole = 'actor' | 'partner'
export type AccessPoint = { x: number; z: number; yaw: number }
export type AccessFrame = { centreX: number; centreZ: number; groundY: number; unitsPerMetre: number }

/** Measure with the canonical snapped fix; the viewer still draws the exact rotation. */
export function propMetresPerUnit(bbox: [number, number, number],
  dims: { width_m: number; depth_m: number; height_m: number },
  rotation?: { x?: number; y?: number; z?: number }): number {
  return placeTransform({
    role: 'prop', id: '', variants: {}, level: 0,
    fix_euler: { x: rotation?.x ?? 0, y: rotation?.y ?? 0, z: rotation?.z ?? 0 },
    yaw_deg: 0, measure: 'xyz', max_m: Math.max(dims.width_m, dims.depth_m, dims.height_m),
    anchor: [0, 0], bottom_y: 0,
  }, [{ min: [0, 0, 0], max: bbox }]).outerScale
}

/** Access is already oriented: never apply the raw mesh fix a second time. */
export function accessWorldPoint(point: AccessPoint, frame: AccessFrame): [number, number, number] {
  return [frame.centreX + point.x * frame.unitsPerMetre, frame.groundY,
    frame.centreZ + point.z * frame.unitsPerMetre]
}
export function accessLocalPoint(point: [number, number, number], frame: AccessFrame) {
  return { x: (point[0] - frame.centreX) / frame.unitsPerMetre,
    z: (point[2] - frame.centreZ) / frame.unitsPerMetre }
}

