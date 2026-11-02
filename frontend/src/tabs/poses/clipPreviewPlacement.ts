import { clipShiftM } from '@anima/scene-render'

/** Renderer-only calibration in world axes, shared by pair and transition previews. */
export function previewCalibration(shift: [number, number] | null | undefined, heightM: number, yaw = 0) {
  const horizontal = clipShiftM(shift, yaw)
  return { x: horizontal.x, y: heightM, z: horizontal.z }
}

/** Preserve all halves in one clip frame, anchored on the selected target half. */
export function relativeTargetRoot(root: { x: number; z: number }, target: { x: number; z: number },
  ownCalibration: { x: number; z: number }, targetCalibration: { x: number; z: number }, yaw: number) {
  const x = root.x - target.x + ownCalibration.x - targetCalibration.x
  const z = root.z - target.z + ownCalibration.z - targetCalibration.z
  return { x: x * Math.cos(yaw) + z * Math.sin(yaw), z: -x * Math.sin(yaw) + z * Math.cos(yaw) }
}
