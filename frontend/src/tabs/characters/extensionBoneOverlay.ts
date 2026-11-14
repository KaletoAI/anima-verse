/**
 * The extension-bone overlay of the model viewers (Ruling A45): the bones the secondary motion drives — every
 * bone of a non-hair group of the motion payload — drawn on top of the model as a line from the bone's head to
 * its tip with a dot at each end. It is redrawn every frame after the solver, so a gravity preview (the drag
 * tilt, Ruling A41) and a playing clip move the lines with the bones.
 *
 * A bone's tip is the head of its first child bone; a leaf bone (the usual extension bone) has no stored tail
 * in a glTF file, so its tip lies `LEAF_LENGTH_M` along the bone's own +Y axis — the axis Blender's exporter
 * and the Mixamo rig point along the bone. The overlay lives in the scene root in world space, like the
 * collision overlay; it owns its geometry and materials and frees them on `dispose`.
 *
 * `swingDeg()` is the readout under the viewer: the largest angle by which a drawn bone points away from where it
 * points in the built (bind) pose, measured in its parent's frame — so turning the whole figure reads 0, and only
 * the solver's swing, gravity sag and rest offsets count.
 */
import type { Bone, BufferAttribute, LineBasicMaterial, LineSegments, Matrix4, Object3D, Points, PointsMaterial,
  SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from '@anima/scene-render'
import type { SecondaryMotionPayload } from '@anima/scene-render'

type Three = typeof import('three')

/** Length of a leaf bone's drawn tip in metres (the models are in metres). */
export const LEAF_LENGTH_M = 0.06

const COLOR = 0x58a6ff

export interface ExtensionBoneOverlay {
  group: Object3D
  /** How many bones are drawn. */
  count: number
  update(): void
  /** The largest swing of a drawn bone away from its bind pose, in whole degrees (parent frame). */
  swingDeg(): number
  dispose(): void
}

/** The bone names of the payload's non-hair groups, normalised (`normBoneName`). */
export function extensionBoneNames(payload: SecondaryMotionPayload | null | undefined): Set<string> {
  const names = new Set<string>()
  for (const group of Object.values(payload?.groups ?? {})) {
    if (group.hair) continue
    for (const bone of group.bones ?? []) names.add(normBoneName(bone))
  }
  return names
}

/** The overlay of `root`'s extension bones, or null when the payload names none the model carries. */
export function createExtensionBoneOverlay(three: Three, root: Object3D,
  payload: SecondaryMotionPayload | null | undefined): ExtensionBoneOverlay | null {
  const names = extensionBoneNames(payload)
  if (!names.size) return null
  const bones: Bone[] = []
  root.traverse((o) => { if ((o as Bone).isBone && names.has(normBoneName(o.name))) bones.push(o as Bone) })
  if (!bones.length) return null
  const childOf = new Map<Bone, Bone | null>(bones.map((bone) => [bone,
    (bone.children.find((c) => (c as Bone).isBone) as Bone | undefined) ?? null]))
  const group = new three.Group()
  group.name = 'extension-bones'
  group.matrixAutoUpdate = false
  group.renderOrder = 999
  const linePositions = new three.BufferAttribute(new Float32Array(bones.length * 6), 3)
  const lineGeometry = new three.BufferGeometry()
  lineGeometry.setAttribute('position', linePositions)
  const lineMaterial: LineBasicMaterial = new three.LineBasicMaterial({ color: COLOR, depthTest: false, transparent: true })
  const lines: LineSegments = new three.LineSegments(lineGeometry, lineMaterial)
  lines.renderOrder = 999
  lines.frustumCulled = false
  const pointPositions = new three.BufferAttribute(new Float32Array(bones.length * 6), 3)
  const pointGeometry = new three.BufferGeometry()
  pointGeometry.setAttribute('position', pointPositions)
  const pointMaterial: PointsMaterial = new three.PointsMaterial({ color: COLOR, size: 6, sizeAttenuation: false,
    depthTest: false, transparent: true })
  const points: Points = new three.Points(pointGeometry, pointMaterial)
  points.renderOrder = 1000
  points.frustumCulled = false
  group.add(lines, points)
  // Each bone's bind direction (+Y) in its parent's bind frame, from the skin's bone inverses.
  const bindWorld = new Map<Object3D, Matrix4>()
  root.traverse((o) => {
    const skin = o as SkinnedMesh
    if (!skin.isSkinnedMesh || !skin.skeleton) return
    skin.skeleton.bones.forEach((bone, i) => {
      if (!bindWorld.has(bone)) bindWorld.set(bone, skin.skeleton.boneInverses[i].clone().invert())
    })
  })
  const restDir = new Map<Bone, Vector3>()
  for (const bone of bones) {
    const own = bindWorld.get(bone)
    const parent = bone.parent ? bindWorld.get(bone.parent) : undefined
    if (!own || !parent) continue
    const local = parent.clone().invert().multiply(own)
    restDir.set(bone, new three.Vector3(0, 1, 0).transformDirection(local))
  }
  const nowDir = new three.Vector3()
  const nowLocal = new three.Matrix4()
  const head = new three.Vector3()
  const tip = new three.Vector3()
  const scale = new three.Vector3()
  const write = (attr: BufferAttribute, i: number) => {
    attr.setXYZ(2 * i, head.x, head.y, head.z)
    attr.setXYZ(2 * i + 1, tip.x, tip.y, tip.z)
  }
  return {
    group,
    count: bones.length,
    update() {
      // The leaf length in metres of the model, whatever scale the viewer puts the model at.
      const leaf = LEAF_LENGTH_M * root.getWorldScale(scale).x
      bones.forEach((bone, i) => {
        bone.getWorldPosition(head)
        const child = childOf.get(bone)
        if (child) child.getWorldPosition(tip)
        // A scaled bone (the girth/length factors) would stretch the leaf tip with it: only its direction counts.
        else tip.set(0, 1, 0).applyMatrix4(bone.matrixWorld).sub(head).setLength(leaf).add(head)
        write(linePositions, i)
        write(pointPositions, i)
      })
      linePositions.needsUpdate = true
      pointPositions.needsUpdate = true
    },
    swingDeg() {
      let worst = 0
      for (const [bone, rest] of restDir) {
        // The solver writes the bones' matrices, not their quaternions: read the local frame off the world matrices.
        if (!bone.parent) continue
        nowLocal.copy(bone.parent.matrixWorld).invert().multiply(bone.matrixWorld)
        nowDir.set(0, 1, 0).transformDirection(nowLocal)
        worst = Math.max(worst, nowDir.angleTo(rest))
      }
      return Math.round((worst * 180) / Math.PI)
    },
    dispose() {
      group.removeFromParent()
      lineGeometry.dispose()
      lineMaterial.dispose()
      pointGeometry.dispose()
      pointMaterial.dispose()
    },
  }
}
