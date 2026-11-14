/**
 * The extension-group overlay of the model viewers (Ruling A56, replacing the bone lines of A45): for every
 * non-hair group of the motion payload, a wire grid over the part of the surface that group moves, in one colour
 * per group. The region is every vertex whose summed skin weight to the group's bones is above
 * `REGION_THRESHOLD`; the wire's alpha is that weight (capped at 1), so the falloff shows — strong where the
 * group moves the skin fully, faint near the threshold. An edge is drawn where both of its ends lie in the region.
 *
 * The wire deforms with the mesh on the GPU: each region is a `LineSegments` over its own compact copy of the
 * region's vertices (position, skin indices and weights, an RGBA colour) that is skinned by the SOURCE mesh's
 * skeleton — the object carries the skinned-mesh fields (`isSkinnedMesh`, `skeleton`, `bindMatrix`,
 * `bindMatrixInverse`, `bindMode`) so the renderer's basic shader skins it like the mesh. A gravity preview
 * (the drag tilt, Ruling A41), the solver and a playing clip therefore move the grid with the surface. The copied
 * positions are pushed `OFFSET_M` out along the vertex normal, so the wire sits just above the skin and is depth
 * tested against it (the far side of the figure hides it). Morph targets are not followed (base models carry none).
 *
 * A group whose own bones skin no vertex (a pure chain driving an attached part) takes the attached part as its
 * region: the vertices skinned to the bones below its bones, plus every plain mesh hanging under its bones
 * (alpha 1, carried rigidly by its bone).
 *
 * Ownership: the overlay lives in the scene root, owns ONLY the geometries and materials it created and frees
 * exactly those on `dispose` — never the source meshes, their geometry or the shared skeleton (and its bone
 * texture), which belong to the model.
 *
 * `swingDeg()` is the readout under the viewer: the largest angle by which a group bone points away from where it
 * points in the built (bind) pose, measured in its parent's frame — so turning the whole figure reads 0, and only
 * the solver's swing, gravity sag and rest offsets count.
 */
import type { Bone, BufferAttribute, BufferGeometry, InterleavedBufferAttribute, LineBasicMaterial, LineSegments,
  Matrix4, Mesh, Object3D, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from '@anima/scene-render'
import type { SecondaryMotionPayload } from '@anima/scene-render'

type Three = typeof import('three')
type Attr = BufferAttribute | InterleavedBufferAttribute

/** The smallest summed skin weight that puts a vertex into a group's region. */
export const REGION_THRESHOLD = 0.1
/** How far the wire sits above the skin, in metres of the shown model. */
export const OFFSET_M = 0.0015
/** The wire's opacity where a group moves the skin fully; the per-vertex weight scales it down from there (a dense
 *  mesh stacks several edges per pixel, so a full 1 would hide the falloff inside the region). */
export const WIRE_OPACITY = 0.7
/** One colour per group, in the payload's group order (repeats after six). */
export const GROUP_COLORS = [0x58a6ff, 0xf0883e, 0x3fb950, 0xd2a8ff, 0xff7b72, 0xe3b341]

export const groupColorCss = (index: number) =>
  `#${GROUP_COLORS[index % GROUP_COLORS.length].toString(16).padStart(6, '0')}`

/** The ids of the payload's non-hair groups that name bones, in payload order — the colour index is the position. */
export function extensionGroupIds(payload: SecondaryMotionPayload | null | undefined): string[] {
  return Object.entries(payload?.groups ?? {}).filter(([, g]) => !g.hair && (g.bones ?? []).length).map(([id]) => id)
}

/** A region of one source geometry: the source vertex indices, their wire alpha, and the drawn edges as pairs of
 *  positions in `vertices`. */
export interface WireRegion {
  vertices: number[]
  alpha: number[]
  edges: number[]
}

/** The triangle corners of `geometry` (its index, or 0..n-1 when it has none). */
function corners(geometry: BufferGeometry): ArrayLike<number> {
  const index = geometry.getIndex()
  if (index) return index.array
  const n = geometry.getAttribute('position')?.count ?? 0
  return Array.from({ length: n - (n % 3) }, (_, i) => i)
}

/** The edges of the triangles whose two ends both have a slot in `slot` (≥ 0), each once, as slot pairs. */
function regionEdges(geometry: BufferGeometry, slot: Int32Array): number[] {
  const tri = corners(geometry)
  const seen = new Set<number>()
  const edges: number[] = []
  const n = slot.length
  for (let i = 0; i + 2 < tri.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const a = tri[i + k], b = tri[i + ((k + 1) % 3)]
      const sa = slot[a], sb = slot[b]
      if (sa < 0 || sb < 0) continue
      const key = a < b ? a * n + b : b * n + a
      if (seen.has(key)) continue
      seen.add(key)
      edges.push(sa, sb)
    }
  }
  return edges
}

/**
 * The region of a skinned geometry that the skeleton bones `bones` (skeleton indices) move: every vertex whose
 * summed weight to them is above `threshold`, with alpha = that weight capped at 1. Null when no vertex qualifies.
 */
export function weightedRegion(geometry: BufferGeometry, bones: ReadonlySet<number>,
  threshold = REGION_THRESHOLD): WireRegion | null {
  const index = geometry.getAttribute('skinIndex') as Attr | undefined
  const weight = geometry.getAttribute('skinWeight') as Attr | undefined
  if (!index || !weight || !bones.size) return null
  const slot = new Int32Array(index.count).fill(-1)
  const vertices: number[] = []
  const alpha: number[] = []
  for (let v = 0; v < index.count; v++) {
    let sum = 0
    for (let k = 0; k < 4; k++) if (bones.has(Math.round(index.getComponent(v, k)))) sum += weight.getComponent(v, k)
    if (sum > threshold) {
      slot[v] = vertices.length
      vertices.push(v)
      alpha.push(Math.min(1, sum))
    }
  }
  if (!vertices.length) return null
  return { vertices, alpha, edges: regionEdges(geometry, slot) }
}

/** The whole of a plain (rigid) geometry as a region, alpha 1. */
export function rigidRegion(geometry: BufferGeometry): WireRegion | null {
  const count = geometry.getAttribute('position')?.count ?? 0
  if (!count) return null
  const slot = Int32Array.from({ length: count }, (_, i) => i)
  return { vertices: Array.from(slot), alpha: new Array(count).fill(1), edges: regionEdges(geometry, slot) }
}

export interface ExtensionGroupOverlay {
  group: Object3D
  /** How many wire regions are drawn (one per group and source mesh). */
  count: number
  /** The groups with a region on this model, in payload order, with their colour index. */
  groups: { id: string; color: number; vertices: number }[]
  update(): void
  /** The largest swing of a group bone away from its bind pose, in whole degrees (parent frame). */
  swingDeg(): number
  dispose(): void
}

interface Drawn {
  lines: LineSegments
  source: Mesh
  skinned: boolean
}

/** The overlay of `root`'s extension groups, or null when the payload names no group with a region on the model. */
export function createExtensionGroupOverlay(three: Three, root: Object3D,
  payload: SecondaryMotionPayload | null | undefined): ExtensionGroupOverlay | null {
  const ids = extensionGroupIds(payload)
  if (!ids.length) return null
  const skins: SkinnedMesh[] = []
  root.traverse((o) => { if ((o as SkinnedMesh).isSkinnedMesh && (o as SkinnedMesh).skeleton) skins.push(o as SkinnedMesh) })
  const bonesByName = new Map<string, Bone[]>()
  root.traverse((o) => {
    if (!(o as Bone).isBone) return
    const key = normBoneName(o.name)
    bonesByName.set(key, [...(bonesByName.get(key) ?? []), o as Bone])
  })
  const group = new three.Group()
  group.name = 'extension-groups'
  group.matrixAutoUpdate = false
  const drawn: Drawn[] = []
  const owned: { geometry: BufferGeometry; material: LineBasicMaterial }[] = []
  const found: ExtensionGroupOverlay['groups'] = []
  const swingBones = new Set<Bone>()
  const scale = new three.Vector3()

  const build = (source: Mesh, region: WireRegion, color: number, skin: SkinnedMesh | null) => {
    const src = source.geometry
    const position = src.getAttribute('position') as Attr
    const normal = src.getAttribute('normal') as Attr | undefined
    const n = region.vertices.length
    // OFFSET_M in the source geometry's own units (the viewer scales the model to fit).
    const offset = OFFSET_M / (source.getWorldScale(scale).x || 1)
    const pos = new Float32Array(n * 3)
    const col = new Float32Array(n * 4)
    const skinIndex = skin ? new Uint16Array(n * 4) : null
    const skinWeight = skin ? new Float32Array(n * 4) : null
    const srcIndex = skin ? src.getAttribute('skinIndex') as Attr : null
    const srcWeight = skin ? src.getAttribute('skinWeight') as Attr : null
    region.vertices.forEach((v, i) => {
      for (let k = 0; k < 3; k++) {
        pos[i * 3 + k] = position.getComponent(v, k) + (normal ? normal.getComponent(v, k) * offset : 0)
      }
      col.set([1, 1, 1, region.alpha[i]], i * 4)
      if (skinIndex && skinWeight && srcIndex && srcWeight) {
        for (let k = 0; k < 4; k++) {
          skinIndex[i * 4 + k] = Math.round(srcIndex.getComponent(v, k))
          skinWeight[i * 4 + k] = srcWeight.getComponent(v, k)
        }
      }
    })
    const geometry = new three.BufferGeometry()
    geometry.setAttribute('position', new three.BufferAttribute(pos, 3))
    geometry.setAttribute('color', new three.BufferAttribute(col, 4))
    if (skinIndex && skinWeight) {
      geometry.setAttribute('skinIndex', new three.Uint16BufferAttribute(skinIndex, 4))
      geometry.setAttribute('skinWeight', new three.BufferAttribute(skinWeight, 4))
    }
    geometry.setIndex(region.edges)
    const material = new three.LineBasicMaterial({ color, vertexColors: true, transparent: true,
      opacity: WIRE_OPACITY, depthWrite: false })
    owned.push({ geometry, material })
    const lines = new three.LineSegments(geometry, material)
    lines.name = 'extension-group-wire'
    lines.matrixAutoUpdate = false
    lines.frustumCulled = false
    lines.renderOrder = 999
    if (skin) {
      // Skinned by the source's skeleton (see the module docstring): the renderer reads these fields.
      Object.assign(lines, { isSkinnedMesh: true, skeleton: skin.skeleton, bindMode: skin.bindMode,
        bindMatrix: skin.bindMatrix.clone(), bindMatrixInverse: skin.bindMatrixInverse.clone() })
    }
    group.add(lines)
    drawn.push({ lines, source, skinned: !!skin })
  }

  ids.forEach((id, index) => {
    const color = GROUP_COLORS[index % GROUP_COLORS.length]
    const own = new Set<Bone>()
    for (const name of payload!.groups[id].bones ?? []) for (const bone of bonesByName.get(normBoneName(name)) ?? []) own.add(bone)
    if (!own.size) return
    own.forEach((bone) => swingBones.add(bone))
    const before = drawn.length
    let vertices = 0
    const skinnedBy = (bones: Set<Bone>) => {
      for (const skin of skins) {
        const slots = new Set<number>()
        skin.skeleton.bones.forEach((bone, i) => { if (bones.has(bone)) slots.add(i) })
        const region = weightedRegion(skin.geometry, slots)
        if (!region) continue
        build(skin, region, color, skin)
        vertices += region.vertices.length
      }
    }
    skinnedBy(own)
    if (drawn.length === before) {
      // A pure chain: the attached part below its bones is the region.
      const below = new Set<Bone>()
      const rigid: Mesh[] = []
      for (const bone of own) {
        bone.traverse((o) => {
          if (o === bone) return
          if ((o as Bone).isBone && !own.has(o as Bone)) below.add(o as Bone)
          else if ((o as Mesh).isMesh && !(o as SkinnedMesh).isSkinnedMesh) rigid.push(o as Mesh)
        })
      }
      skinnedBy(below)
      for (const mesh of rigid) {
        const region = rigidRegion(mesh.geometry)
        if (!region) continue
        build(mesh, region, color, null)
        vertices += region.vertices.length
      }
    }
    if (drawn.length > before) found.push({ id, color: index, vertices })
  })
  if (!drawn.length) {
    for (const { geometry, material } of owned) { geometry.dispose(); material.dispose() }
    return null
  }

  // Each group bone's bind direction (+Y) in its parent's bind frame, from the skins' bone inverses.
  const bindWorld = new Map<Object3D, Matrix4>()
  for (const skin of skins) {
    skin.skeleton.bones.forEach((bone, i) => {
      if (!bindWorld.has(bone)) bindWorld.set(bone, skin.skeleton.boneInverses[i].clone().invert())
    })
  }
  const restDir = new Map<Bone, Vector3>()
  for (const bone of swingBones) {
    const own = bindWorld.get(bone)
    const parent = bone.parent ? bindWorld.get(bone.parent) : undefined
    if (!own || !parent) continue
    restDir.set(bone, new three.Vector3(0, 1, 0).transformDirection(parent.clone().invert().multiply(own)))
  }
  const nowDir = new three.Vector3()
  const nowLocal = new three.Matrix4()
  return {
    group,
    count: drawn.length,
    groups: found,
    update() {
      // The scene root is the world frame: the wire takes its source's world matrix (and bind matrices) as they
      // stand this frame, after the solver.
      for (const { lines, source, skinned } of drawn) {
        lines.matrix.copy(source.matrixWorld)
        lines.matrixWorldNeedsUpdate = true
        if (skinned) {
          const skin = source as SkinnedMesh
          const own = lines as unknown as SkinnedMesh
          own.bindMatrix.copy(skin.bindMatrix)
          own.bindMatrixInverse.copy(skin.bindMatrixInverse)
        }
      }
      group.updateMatrixWorld(true)
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
      for (const { lines } of drawn) lines.removeFromParent()
      for (const { geometry, material } of owned) {
        geometry.dispose()
        material.dispose()
      }
    },
  }
}
