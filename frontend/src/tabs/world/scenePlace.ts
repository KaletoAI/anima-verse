/**
 * scenePlace — the ONE place() routine of contract § B2, shared by the 3D
 * floor-plan preview and the 2D top-down underlay so a model lands at
 * IDENTICAL world coordinates in both (finding 2026-07-25: the underlay
 * still ran the legacy fit chain and drifted from the preview).
 *
 * Pure geometry: clone the source, apply the orientation fix, measure,
 * scale per scale_mode, yaw as the PARENT rotation (never combined into one
 * Euler — an x/z fix would tilt with it), then seat the result's BBox on
 * bottom_y / anchor. No scene wiring, no verify — the callers do that.
 */
import type { Object3D } from 'three'
import type { SceneModelSpec } from './worldTypes'

/** The ONE geometry number that stays client-side: contract § B2 puts the
 *  0.96 fit margin into the consumer's place() routine (fit_box fallback). */
export const FIT_BOX_MARGIN = 0.96

export function placeModelSpec(THREE: typeof import('three'),
                               source: Object3D,
                               spec: SceneModelSpec): Object3D {
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180
  const fix = new THREE.Group()
  fix.add(source.clone(true))
  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y),
                   deg(spec.fix_euler?.z))
  fix.updateMatrixWorld(true)
  const sFix = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3())

  const yawG = new THREE.Group()
  yawG.add(fix)
  yawG.rotation.y = -deg(spec.yaw_deg)
  yawG.updateMatrixWorld(true)
  const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3())

  const outer = new THREE.Group()
  outer.add(yawG)
  if (spec.scale_axes) {
    // Server-measured mesh: the factors come ready (contract § B4).
    outer.scale.set(spec.scale_axes.xz, spec.scale_axes.y, spec.scale_axes.xz)
  } else if (spec.scale_mode === 'tile_fit') {
    // Buildings fill their tile per AXIS, measured on the ROTATED box:
    // the footprint follows the plan, the height its declared metres.
    const kxz = (spec.box?.xz || 1) / (Math.max(sYaw.x, sYaw.z) || 1)
    const ky = spec.box?.y ? spec.box.y / (sYaw.y || 1) : kxz
    outer.scale.set(kxz, ky, kxz)
  } else if (spec.scale_mode === 'real_size') {
    // ONE law of scale: real metres over the largest measured extent.
    // measure_axes 'xz' ignores the height (dioramas, § B2a).
    const maxExtent = (spec.measure_axes === 'xz'
      ? Math.max(sFix.x, sFix.z)
      : Math.max(sFix.x, sFix.y, sFix.z)) || 1
    outer.scale.setScalar((spec.max_m || 1) / maxExtent)
  } else {
    // fit_box fallback: fit the UNROTATED footprint into the target box.
    outer.scale.setScalar(Math.min((spec.box?.w || 1) / (sFix.x || 1),
                                   (spec.box?.d || 1) / (sFix.z || 1))
                          * FIT_BOX_MARGIN)
  }
  outer.updateMatrixWorld(true)
  const bOut = new THREE.Box3().setFromObject(outer)
  const cOut = bOut.getCenter(new THREE.Vector3())
  outer.position.set(spec.anchor[0] - cOut.x,
                     spec.bottom_y - bOut.min.y,
                     spec.anchor[1] - cOut.z)
  return outer
}
