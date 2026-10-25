/**
 * place() — THE placement routine of the contract (§ B2), once for both
 * renderers. It used to exist twice: `placeModelSpec` in the admin preview and
 * `placeSpec` in the 3D client, line for line the same arithmetic.
 *
 * Pure geometry: take the source, apply the orientation fix, measure, scale
 * UNIFORMLY to `max_m`, hang the object on its OWN centre, yaw as a PARENT
 * rotation about exactly that point (never combined into one Euler — an x/z
 * fix would tip along), then set it on `anchor` / `bottom_y` and, if the spec
 * asks for it, clip it against the room hull. No scene wiring, no verify —
 * that is the callers' business.
 *
 * `measure: 'fit'` (v5, door props) is the ONE spec that does not scale
 * uniformly and does not hang on its centre: it is fitted into an opening
 * (`size_m`) and hung on its HINGE edge, so the caller can swing the returned
 * group about its own origin. Everything else about the chain is unchanged.
 *
 * Returns: a wrapper around `source`. The caller hangs it into a group WITHOUT
 * a transform of its own (the grounding measures in the parent frame, and the
 * spec numbers are stated around the tile centre).
 *
 * THREE comes in as a parameter instead of an import: the admin page loads
 * three lazily, and a static import would pull the library into its main
 * bundle. The client simply passes its imported module through.
 */
import type { Group, Object3D } from 'three'
import { applyClipOutline } from './clip'
import type { SceneModelSpec } from './types'
import { placeTransform, type MeshBox } from './placeTransform'

export interface PlaceOptions {
  /** Clone the source before placing it. Default true — the admin preview
   *  places the same cached object several times over. The 3D client hands
   *  the object over for good and therefore passes false. */
  clone?: boolean
  /** Apply `spec.clip_outline` right away. Default true. The 3D client clips
   *  itself, after it has hung the model in, and passes false. */
  clip?: boolean
}

export function placeModelSpec(THREE: typeof import('three'),
                               source: Object3D,
                               spec: SceneModelSpec,
                               opts: PlaceOptions = {}): Group {
  const { clone = true, clip = true } = opts
  const fix = new THREE.Group()
  fix.add(clone ? source.clone(true) : source)
  fix.updateMatrixWorld(true)
  // Keep each geometry box and its matrix separate: rotating the combined
  // source hull would change the seating datum of asymmetric multi-mesh props.
  const meshBoxes: MeshBox[] = []
  fix.traverse((object) => {
    const o = object as Object3D & {
      boundingBox?: import('three').Box3 | null
      computeBoundingBox?: () => void
      geometry?: import('three').BufferGeometry
    }
    let box: import('three').Box3 | null | undefined
    if (o.boundingBox !== undefined) {
      if (o.boundingBox === null) o.computeBoundingBox?.()
      box = o.boundingBox
    } else if (o.geometry) {
      if (o.geometry.boundingBox === null) o.geometry.computeBoundingBox()
      box = o.geometry.boundingBox
    }
    if (box && !box.isEmpty()) meshBoxes.push({
      min: box.min.toArray(), max: box.max.toArray(),
      matrix: o.matrixWorld.elements.slice(),
    })
  })
  const transform = placeTransform(spec, meshBoxes)
  const deg = (v?: number) => ((v || 0) * Math.PI) / 180
  fix.rotation.order = 'YXZ'
  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y), deg(spec.fix_euler?.z))
  fix.position.fromArray(transform.fixPos)
  const fitG = new THREE.Group()
  fitG.add(fix)
  fitG.scale.fromArray(transform.fitScale)
  const yawG = new THREE.Group()
  yawG.add(fitG)
  yawG.rotation.y = deg(spec.yaw_deg)
  const outer = new THREE.Group()
  outer.add(yawG)
  outer.scale.setScalar(transform.outerScale)
  outer.updateMatrixWorld(true)
  outer.position.fromArray(transform.outerPos)
  // Hull clip LAST: the shader compares world positions, so the model has to
  // sit where it belongs first (§ B1).
  if (clip && spec.clip_outline?.length) {
    applyClipOutline(THREE, outer, spec.clip_outline)
  }
  return outer
}
