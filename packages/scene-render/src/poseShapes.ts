/**
 * POSE SHAPES (Ruling A141) — the pose-space corrective shapes of a draped
 * template garment (`app/core/garment_template.py`, Blender
 * `garment_template_build.py`), blended by the figure's leg directions.
 *
 * A template skirt or dress is draped once on the body at rest and skinned; in
 * a pose that bends the legs far (sit, kneel) the skinned cloth lifts off the
 * thighs like a plate. The Build drapes the cloth again in each such pose and
 * stores the difference, taken back through the inverse skinning into the bind
 * pose, as a morph target (three applies morphs before skinning, so at the
 * sample pose the skinned result IS that pose's drape). No physics at runtime:
 * one small blend per figure and frame.
 *
 * THE PAYLOAD (garment node extras, `extras.garment.pose_shapes`):
 * `{version: 1, segments: [[from, to] x 4], sigma, targets: [name…],
 *   samples: [{pose, target | null, dirs: [[x, y, z] x 4]}]}` — `segments` are
 * joint pairs (thighs, then shins), `dirs` the unit direction from the first
 * joint to the second in the glTF model axes with the hips' rotation since the
 * bind pose taken out. A sample without a target is an anchor (rest, walk: the
 * skinned drape is kept there).
 *
 * THE RULE (`poseShapeInfluences`, the same as `blend` in the Blender script):
 * d_i² = Σ_k acos(f_k · s_ik)², g_i = exp(−d_i² / 2σ²), the influence of a
 * target = Σ g_i of its samples / Σ g_i of all samples.
 *
 * Called at the end of phase A (`FigureRuntime.poseStep`): the pose is final,
 * the bones' world matrices are brought up to date along the legs first.
 *
 * `three` is a parameter, never an import (package rule).
 */
import type { Bone, Matrix4, Object3D, Quaternion, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from './clipRetarget'

type Three = typeof import('three')

export interface PoseShapeSample { pose: string; target: string | null; dirs: number[][] }
export interface PoseShapesPayload {
  version: number
  segments: [string, string][]
  sigma: number
  targets: string[]
  samples: PoseShapeSample[]
}

/** The influence of every target for `features` (four unit directions) — see the module rule. */
export function poseShapeInfluences(features: readonly (readonly number[])[], samples: readonly PoseShapeSample[],
  sigma: number): Record<string, number> {
  const g: number[] = []
  for (const s of samples) {
    let d2 = 0
    for (let k = 0; k < features.length; k++) {
      const u = features[k], v = s.dirs[k]
      const c = Math.max(-1, Math.min(1, u[0] * v[0] + u[1] * v[1] + u[2] * v[2]))
      d2 += Math.acos(c) ** 2
    }
    g.push(Math.exp(-d2 / (2 * sigma * sigma)))
  }
  const total = g.reduce((a, b) => a + b, 0) || 1
  const out: Record<string, number> = {}
  samples.forEach((s, i) => {
    if (s.target) out[s.target] = (out[s.target] ?? 0) + g[i] / total
  })
  return out
}

/** A payload that can be blended: four segments, a positive sigma, every sample with four directions. */
export function validPoseShapes(p: unknown): p is PoseShapesPayload {
  const o = p as PoseShapesPayload
  return !!o && typeof o === 'object' && Array.isArray(o.segments) && o.segments.length > 0
    && typeof o.sigma === 'number' && o.sigma > 0 && Array.isArray(o.samples) && o.samples.length > 0
    && o.samples.every(s => Array.isArray(s.dirs) && s.dirs.length === o.segments.length)
}

interface Entry { mesh: SkinnedMesh; payload: PoseShapesPayload; slots: Map<string, number> }

export interface PoseShapes {
  /** Sets the morph influences of every pose-shaped garment from the current pose. */
  update(): void
  /** The last features and influences (inspection, checks). */
  readonly last: { features: number[][]; influences: Record<string, number> } | null
}

/**
 * Binds the pose shapes of `instance` (every garment mesh carrying `userData.garment.pose_shapes` and morph
 * targets). Null when there is none, or the legs or hips are missing.
 */
export function bindPoseShapes(three: Three, instance: Object3D): PoseShapes | null {
  const entries: Entry[] = []
  instance.traverse(o => {
    const m = o as SkinnedMesh
    const payload = (m.userData?.garment as { pose_shapes?: unknown } | undefined)?.pose_shapes
    if (!m.isSkinnedMesh || !m.morphTargetInfluences || !m.morphTargetDictionary || !validPoseShapes(payload)) return
    const slots = new Map<string, number>()
    for (const t of payload.targets) {
      const i = m.morphTargetDictionary[t]
      if (i !== undefined) slots.set(t, i)
    }
    if (slots.size) entries.push({ mesh: m, payload, slots })
  })
  if (!entries.length) return null
  // The joints, by normalised name, from the first entry's skeleton (all garments share the body's skin).
  const skeleton = entries[0].mesh.skeleton
  const byName = new Map<string, { bone: Bone; index: number }>()
  skeleton.bones.forEach((bone, index) => byName.set(normBoneName(bone.name), { bone, index }))
  const hips = byName.get('hips')
  if (!hips) return null
  const segments = entries[0].payload.segments.map(([a, b]) => [byName.get(normBoneName(a)), byName.get(normBoneName(b))])
  if (segments.some(([a, b]) => !a || !b)) return null
  // The hips' bind rotation in the model space (inverse of its inverse bind matrix).
  const bindHips: Quaternion = new three.Quaternion()
  const scratchM: Matrix4 = new three.Matrix4()
  const sv: Vector3 = new three.Vector3()
  scratchM.copy(skeleton.boneInverses[hips.index]).invert().decompose(sv, bindHips, new three.Vector3())
  const nowHips = new three.Quaternion()
  const undo = new three.Quaternion()
  const pa = new three.Vector3(), pb = new three.Vector3(), d = new three.Vector3()
  const ends = new Set<Bone>()
  for (const [, b] of segments) ends.add(b!.bone)
  let last: PoseShapes['last'] = null
  return {
    get last() { return last },
    update() {
      for (const bone of ends) bone.updateWorldMatrix(true, false)
      hips.bone.matrixWorld.decompose(sv, nowHips, pa)
      // model direction with the hips' rotation since bind removed: bind · now⁻¹ · world
      undo.copy(nowHips).invert().premultiply(bindHips)
      const features: number[][] = []
      for (const [a, b] of segments) {
        pa.setFromMatrixPosition(a!.bone.matrixWorld)
        pb.setFromMatrixPosition(b!.bone.matrixWorld)
        d.subVectors(pb, pa).applyQuaternion(undo).normalize()
        features.push([d.x, d.y, d.z])
      }
      let influences: Record<string, number> = {}
      for (const e of entries) {
        influences = poseShapeInfluences(features, e.payload.samples, e.payload.sigma)
        const inf = e.mesh.morphTargetInfluences!
        for (const [name, slot] of e.slots) inf[slot] = influences[name] ?? 0
      }
      last = { features, influences }
    },
  }
}
