/**
 * POSE SHAPES (Rulings A141, A142) — the pose-space corrective shapes of a draped
 * template garment (`app/core/garment_template.py`, Blender
 * `garment_template_build.py`), blended by the figure's limb directions.
 *
 * A template garment is draped once on the body in its bind pose (the T-pose)
 * and skinned; in a pose far from that (sit, kneel; arms down, forward, up) the
 * skinned cloth is wrong — a skirt lifts off the thighs like a plate, a sleeve
 * and its armhole crush. The Build drapes the cloth again in each such pose and
 * stores the difference, taken back through the inverse skinning into the bind
 * pose, as a morph target (three applies morphs before skinning, so at the
 * sample pose the skinned result IS that pose's drape). No physics at runtime:
 * one small blend per figure and frame.
 *
 * THE PAYLOAD (garment node extras, `extras.garment.pose_shapes`):
 * `{version: 2, targets: [name…], groups: [{name, frame, segments: [[from, to]…],
 *   sigma, targets: [name…], samples: [{pose, target | null, dirs: [[x, y, z]…]}]}]}`.
 * Each group is blended on its own: `segments` are joint pairs (legs: thighs then
 * shins; an arm group: upper arm then forearm of ONE side, so one arm up and one
 * down mix correctly), `dirs` the unit direction from the first joint to the second
 * in the glTF model axes with the rotation of the group's `frame` joint since the
 * bind pose taken out (Hips for the legs, Spine2 for the arms). A sample without a
 * target is an anchor (the skinned drape is kept there).
 *
 * THE RULE (`poseShapeInfluences`, the same as `blend` in the Blender script):
 * d_i² = Σ_k acos(f_k · s_ik)², g_i = exp(−d_i² / 2σ²), the influence of a
 * target = Σ g_i of its samples / Σ g_i of all samples of its group.
 *
 * Called at the end of phase A (`FigureRuntime.poseStep`): the pose is final,
 * the bones' world matrices are brought up to date along the limbs first.
 *
 * `three` is a parameter, never an import (package rule).
 */
import type { Bone, Matrix4, Object3D, Quaternion, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from './clipRetarget'

type Three = typeof import('three')

export interface PoseShapeSample { pose: string; target: string | null; dirs: number[][] }
export interface PoseShapeGroup {
  name?: string
  /** The joint whose rotation since the bind pose is taken out of the directions. */
  frame: string
  segments: [string, string][]
  sigma: number
  targets: string[]
  samples: PoseShapeSample[]
}
export interface PoseShapesPayload {
  version: number
  targets: string[]
  groups: PoseShapeGroup[]
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

/** A group that can be blended: segments, a positive sigma, every sample with one direction per segment. */
export function validPoseShapeGroup(g: unknown): g is PoseShapeGroup {
  const o = g as PoseShapeGroup
  return !!o && typeof o === 'object' && typeof o.frame === 'string' && Array.isArray(o.segments)
    && o.segments.length > 0 && typeof o.sigma === 'number' && o.sigma > 0 && Array.isArray(o.samples)
    && o.samples.length > 0 && o.samples.every(s => Array.isArray(s.dirs) && s.dirs.length === o.segments.length)
}

/** A payload that can be blended: version 2 with at least one valid group. */
export function validPoseShapes(p: unknown): p is PoseShapesPayload {
  const o = p as PoseShapesPayload
  return !!o && typeof o === 'object' && o.version === 2 && Array.isArray(o.groups) && o.groups.length > 0
    && o.groups.every(validPoseShapeGroup)
}

interface BoundGroup {
  group: PoseShapeGroup
  frame: { bone: Bone; index: number }
  segments: { bone: Bone; index: number }[][]
  bindFrame: Quaternion
}
interface Entry { mesh: SkinnedMesh; groups: BoundGroup[]; slots: Map<string, number> }

export interface PoseShapes {
  /** Sets the morph influences of every pose-shaped garment from the current pose. */
  update(): void
  /** The last features (per group, in payload order of the first garment) and influences (inspection, checks). */
  readonly last: { features: number[][][]; influences: Record<string, number> } | null
}

/**
 * Binds the pose shapes of `instance` (every garment mesh carrying `userData.garment.pose_shapes` and morph
 * targets). Null when there is none; a group whose joints are missing is left out (its targets stay at 0).
 */
export function bindPoseShapes(three: Three, instance: Object3D): PoseShapes | null {
  const entries: Entry[] = []
  const scratchM: Matrix4 = new three.Matrix4()
  const sv: Vector3 = new three.Vector3()
  instance.traverse(o => {
    const m = o as SkinnedMesh
    const payload = (m.userData?.garment as { pose_shapes?: unknown } | undefined)?.pose_shapes
    if (!m.isSkinnedMesh || !m.morphTargetInfluences || !m.morphTargetDictionary || !validPoseShapes(payload)) return
    const byName = new Map<string, { bone: Bone; index: number }>()
    m.skeleton.bones.forEach((bone, index) => byName.set(normBoneName(bone.name), { bone, index }))
    const slots = new Map<string, number>()
    for (const t of payload.targets) {
      const i = m.morphTargetDictionary[t]
      if (i !== undefined) slots.set(t, i)
    }
    const groups: BoundGroup[] = []
    for (const group of payload.groups) {
      const frame = byName.get(normBoneName(group.frame))
      const segments = group.segments.map(([a, b]) => [byName.get(normBoneName(a)), byName.get(normBoneName(b))])
      if (!frame || segments.some(([a, b]) => !a || !b)) continue
      // the frame joint's bind rotation in the model space (inverse of its inverse bind matrix)
      const bindFrame: Quaternion = new three.Quaternion()
      scratchM.copy(m.skeleton.boneInverses[frame.index]).invert().decompose(sv, bindFrame, new three.Vector3())
      groups.push({ group, frame, segments: segments as { bone: Bone; index: number }[][], bindFrame })
    }
    if (slots.size && groups.length) entries.push({ mesh: m, groups, slots })
  })
  if (!entries.length) return null
  const now = new three.Quaternion()
  const undo = new three.Quaternion()
  const pa = new three.Vector3(), pb = new three.Vector3(), d = new three.Vector3(), sc = new three.Vector3()
  const ends = new Set<Bone>()
  for (const e of entries) for (const g of e.groups) for (const [, b] of g.segments) ends.add(b.bone)
  let last: PoseShapes['last'] = null
  return {
    get last() { return last },
    update() {
      for (const bone of ends) bone.updateWorldMatrix(true, false)
      let allFeatures: number[][][] = []
      const influences: Record<string, number> = {}
      entries.forEach((e, ei) => {
        const inf = e.mesh.morphTargetInfluences!
        const feats: number[][][] = []
        for (const g of e.groups) {
          g.frame.bone.matrixWorld.decompose(sv, now, sc)
          // model direction with the frame's rotation since bind removed: bind · now⁻¹ · world
          undo.copy(now).invert().premultiply(g.bindFrame)
          const features: number[][] = []
          for (const [a, b] of g.segments) {
            pa.setFromMatrixPosition(a.bone.matrixWorld)
            pb.setFromMatrixPosition(b.bone.matrixWorld)
            d.subVectors(pb, pa).applyQuaternion(undo).normalize()
            features.push([d.x, d.y, d.z])
          }
          feats.push(features)
          Object.assign(influences, poseShapeInfluences(features, g.group.samples, g.group.sigma))
        }
        for (const [name, slot] of e.slots) inf[slot] = influences[name] ?? 0
        if (ei === 0) allFeatures = feats
      })
      last = { features: allFeatures, influences }
    },
  }
}
