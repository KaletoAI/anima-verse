/**
 * Collision capsules — WHERE the body's capsules are in the current frame
 * (`docs/schnittstellen-3d.md` "Collision capsules (`collision`)", server
 * `app/core/collision.py`). This is the ONE place the endpoint rule lives;
 * the admin viewer draws with it and the garment/hair push of both renderers
 * reads the same numbers.
 *
 * THE ENDPOINT RULE. A capsule names two joints `a`/`b` (as in the model,
 * matched through `normBoneName`) and a radius `r` in metres of the body's
 * bind space. An endpoint WITHOUT `a_pos`/`b_pos` is the joint's current
 * world position. An endpoint WITH one is a bind-space point (the space of
 * the body's POSITION accessor) fixed to that joint: it moves exactly like a
 * body vertex skinned 100 % to the joint. In three.js terms that vertex goes
 *
 *   world = meshWorld · bindMatrixInverse · boneWorld · boneInverse · bindMatrix · p_bind
 *
 * (`SkinnedMesh.applyBoneTransform` followed by the mesh's model matrix; in
 * the default `attached` bind mode `meshWorld · bindMatrixInverse` is the
 * identity, in `detached` mode it is not — both are covered). The spec's
 * short form `boneWorld · inverse(boneBindWorld) · p_bind` is the same thing
 * with the bind frame folded in. The radius scales with that matrix too (a
 * figure scaled ×0.5 in the scene gets half-size capsules).
 *
 * Matrices are column-major 16-number arrays — three's `Matrix4.elements`
 * layout — so the math here is pure and checkable without three
 * (`scripts/smoke_collision_endpoints.mjs`). `three` itself is injected,
 * never imported.
 */
import type { BufferGeometry, Group, LineBasicMaterial, LineSegments, Object3D, SkinnedMesh } from 'three'
import { normBoneName } from './clipRetarget'
import { inGarment } from './figure'

type Three = typeof import('three')

export type Vec3 = [number, number, number]
/** Column-major 4×4 (three's `Matrix4.elements`). */
export type Mat4 = ArrayLike<number>

/** One capsule of the payload. */
export interface CollisionCapsule {
  id: string
  a: string
  b: string
  r: number
  region: string
  a_pos?: Vec3
  b_pos?: Vec3
}

/** The `collision` payload (model meta / model3d info). */
export interface CollisionPayload {
  version: number
  capsules: CollisionCapsule[]
  skipped?: Array<{ id: string; a?: string; b?: string; reason: string }>
  scales?: Record<string, number>
  source?: 'own' | 'base' | 'body'
  base_signature?: string
  sha256?: string
  computed_at?: string
  error?: string
}

/**
 * The payload version this module understands; anything else is ignored.
 * 2: the extension capsules (regions `chest` / `attached_part`, one per
 * chain bone of an extension group, `app/core/collision.py`
 * `EXTENSION_CAPSULES`) — a stored set of version 1 lacks them and is
 * refitted by the server on its next read.
 * 3: the hair-only `chest_hair` capsules (`HAIR_ONLY_REGIONS`).
 */
export const COLLISION_VERSION = 3

/**
 * Regions whose capsules are for HAIR only (`garmentCollision.ts`
 * `HAIR_REGIONS`): `chest_hair` reaches out to the skin plus the hair fit's
 * clearance (`app/core/collision.py` `EXTENSION_CAPSULES`), so it would float
 * cloth and turn extension-bone tips that rest on the skin — neither cloth
 * nor `secondaryMotion.ts` uses it.
 */
export const HAIR_ONLY_REGIONS: readonly string[] = ['chest_hair']

/** A capsule in the current frame, world space. */
export interface CapsuleNow { a: Vec3; b: Vec3; r: number }

// --- pure math (column-major) ---------------------------------------------------------------------------------

/** a · b. */
export function mat4Multiply(a: Mat4, b: Mat4): number[] {
  const out = new Array<number>(16)
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0
      for (let k = 0; k < 4; k++) sum += a[k * 4 + row] * b[col * 4 + k]
      out[col * 4 + row] = sum
    }
  }
  return out
}

/** m · (p, 1), divided by w. */
export function transformPoint(m: Mat4, p: Vec3): Vec3 {
  const [x, y, z] = p
  const w = m[3] * x + m[7] * y + m[11] * z + m[15] || 1
  return [
    (m[0] * x + m[4] * y + m[8] * z + m[12]) / w,
    (m[1] * x + m[5] * y + m[9] * z + m[13]) / w,
    (m[2] * x + m[6] * y + m[10] * z + m[14]) / w,
  ]
}

/** The mean length of the three basis columns — the uniform scale a radius takes through `m`. */
export function linearScale(m: Mat4): number {
  let sum = 0
  for (let col = 0; col < 3; col++) sum += Math.hypot(m[col * 4], m[col * 4 + 1], m[col * 4 + 2])
  return sum / 3
}

/** One endpoint's joint in the current frame: its world position and its bind→world matrix. */
export interface JointNow { position: Vec3; bindToWorld: Mat4 }

/**
 * One joint of a skinned body in the current frame (module docstring):
 * `bindToWorld` is what a vertex skinned 100 % to the joint goes through,
 * `position` where the joint itself is drawn — `bindToWorld` applied to the
 * joint's own bind position, i.e. the origin of
 * `meshWorld · bindMatrixInverse · boneWorld` (= the bone's world position
 * in the attached bind mode).
 */
export function jointNowFrom(meshWorld: Mat4, bindMatrixInverse: Mat4, boneWorld: Mat4,
  boneInverse: Mat4, bindMatrix: Mat4): JointNow {
  const posed = mat4Multiply(mat4Multiply(meshWorld, bindMatrixInverse), boneWorld)
  return {
    position: [posed[12], posed[13], posed[14]],
    bindToWorld: mat4Multiply(mat4Multiply(posed, boneInverse), bindMatrix),
  }
}

/**
 * The ENDPOINT RULE: a capsule in the current frame. `a`/`b` are the joints
 * the capsule names; an endpoint with a bind position goes through its
 * joint's bind→world matrix, one without is the joint itself. The radius
 * scales with joint `a`'s matrix.
 */
export function capsuleNow(capsule: Pick<CollisionCapsule, 'r' | 'a_pos' | 'b_pos'>,
  a: JointNow, b: JointNow): CapsuleNow {
  return {
    a: capsule.a_pos ? transformPoint(a.bindToWorld, capsule.a_pos) : [...a.position] as Vec3,
    b: capsule.b_pos ? transformPoint(b.bindToWorld, capsule.b_pos) : [...b.position] as Vec3,
    r: capsule.r * linearScale(a.bindToWorld),
  }
}

/**
 * Line segments of a capsule wireframe along +y, centred on the origin:
 * `rings` circles along the cylinder part (both ends included), `meridians`
 * lines over the full length including both hemispherical caps, plus one
 * latitude circle per cap step. Flat `[x, y, z, …]` pairs.
 */
export function capsuleLineSegments(r: number, length: number, meridians = 8, capSteps = 4,
  segments = 24): number[] {
  const out: number[] = []
  const half = length / 2
  const circle = (y: number, radius: number) => {
    for (let i = 0; i < segments; i++) {
      const t0 = (i / segments) * Math.PI * 2
      const t1 = ((i + 1) / segments) * Math.PI * 2
      out.push(Math.cos(t0) * radius, y, Math.sin(t0) * radius, Math.cos(t1) * radius, y, Math.sin(t1) * radius)
    }
  }
  circle(half, r)
  circle(-half, r)
  for (let s = 1; s < capSteps; s++) {
    const phi = (s / capSteps) * (Math.PI / 2)
    circle(half + Math.sin(phi) * r, Math.cos(phi) * r)
    circle(-half - Math.sin(phi) * r, Math.cos(phi) * r)
  }
  for (let m = 0; m < meridians; m++) {
    const theta = (m / meridians) * Math.PI * 2
    const cx = Math.cos(theta)
    const cz = Math.sin(theta)
    out.push(cx * r, -half, cz * r, cx * r, half, cz * r)
    const steps = capSteps * 2
    for (let s = 0; s < steps; s++) {
      const p0 = (s / steps) * (Math.PI / 2)
      const p1 = ((s + 1) / steps) * (Math.PI / 2)
      for (const sign of [1, -1]) {
        out.push(cx * Math.cos(p0) * r, sign * (half + Math.sin(p0) * r), cz * Math.cos(p0) * r,
          cx * Math.cos(p1) * r, sign * (half + Math.sin(p1) * r), cz * Math.cos(p1) * r)
      }
    }
  }
  return out
}

// --- three binding ----------------------------------------------------------------------------------------------

interface JointRef { mesh: SkinnedMesh; index: number }

/**
 * A capsule bound to a figure; `now` is refreshed by `update()`. `bind` = the
 * same capsule in the BIND pose, in the world frame the body was bound in
 * (its `bindMatrix`) — fixed; the garment push's bind rule reads it.
 */
export interface BoundCapsule {
  capsule: CollisionCapsule
  now: CapsuleNow
  bind: CapsuleNow
}

export interface CollisionBinding {
  /** The capsules whose joints the figure has, in payload order. */
  readonly capsules: BoundCapsule[]
  /** Ids of payload capsules whose joints the figure lacks (not drawn, not applied). */
  readonly missing: string[]
  /** Recompute every capsule from the CURRENT bone matrices (call after `updateMatrixWorld`). */
  update(): void
}

/**
 * Bind a `collision` payload to a loaded figure: each capsule joint is looked
 * up (by `normBoneName`) in the skeleton of a BODY skinned mesh — never a
 * garment's (`inGarment`), since a bind position lives in the body's
 * POSITION space. Null for a payload of another version or without capsules.
 */
export function bindCollision(three: Three, root: Object3D, payload: CollisionPayload | null | undefined): CollisionBinding | null {
  if (!payload || payload.version !== COLLISION_VERSION || !payload.capsules?.length) return null
  const joints = new Map<string, JointRef>()
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (!mesh.isSkinnedMesh || !mesh.skeleton || inGarment(mesh)) return
    mesh.skeleton.bones.forEach((bone, index) => {
      const key = normBoneName(bone.name)
      if (!joints.has(key)) joints.set(key, { mesh, index })
    })
  })
  // A joint in the bind pose: the bone's world matrix IS inverse(boneInverse) and the mesh's world matrix its
  // bindMatrix, so a vertex fixed to it goes through `bindMatrix` (the endpoint rule with the bind matrices).
  const jointAtBind = (ref: JointRef): JointNow => jointNowFrom(ref.mesh.bindMatrix.elements,
    ref.mesh.bindMatrixInverse.elements, new three.Matrix4().copy(ref.mesh.skeleton.boneInverses[ref.index]).invert().elements,
    ref.mesh.skeleton.boneInverses[ref.index].elements, ref.mesh.bindMatrix.elements)
  const bound: Array<BoundCapsule & { ja: JointRef; jb: JointRef }> = []
  const missing: string[] = []
  for (const capsule of payload.capsules) {
    const ja = joints.get(normBoneName(capsule.a))
    const jb = joints.get(normBoneName(capsule.b))
    if (!ja || !jb || !(capsule.r > 0)) { missing.push(capsule.id); continue }
    bound.push({ capsule, ja, jb, now: { a: [0, 0, 0], b: [0, 0, 0], r: capsule.r },
      bind: capsuleNow(capsule, jointAtBind(ja), jointAtBind(jb)) })
  }
  const jointNow = (ref: JointRef): JointNow => jointNowFrom(ref.mesh.matrixWorld.elements,
    ref.mesh.bindMatrixInverse.elements, ref.mesh.skeleton.bones[ref.index].matrixWorld.elements,
    ref.mesh.skeleton.boneInverses[ref.index].elements, ref.mesh.bindMatrix.elements)
  const update = () => {
    for (const entry of bound) entry.now = capsuleNow(entry.capsule, jointNow(entry.ja), jointNow(entry.jb))
  }
  update()
  return { capsules: bound, missing, update }
}

// --- wireframes -------------------------------------------------------------------------------------------------

/** Region colours of the debug wireframe. */
export const CAPSULE_REGION_COLORS: Record<string, number> = {
  leg: 0xff9f1c, arm: 0x2ec4b6, torso: 0x7bd389, head: 0xe0aaff,
  chest: 0xff6b9a, chest_hair: 0xffc94d, attached_part: 0x5ab0ff,
}

interface WireState { r: number; length: number }

/**
 * A wireframe of one capsule in the current frame (world space) — a
 * `LineSegments` drawn on top of the figure (`depthTest` off). Move it with
 * `placeCapsuleWireframe` every frame; it owns its geometry and material.
 */
export function capsuleWireframe(three: Three, capsule: CapsuleNow, color = 0xffd166): LineSegments {
  const material = new three.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.85 })
  const line = new three.LineSegments(new three.BufferGeometry(), material)
  line.renderOrder = 999
  line.userData.collisionWire = { r: -1, length: -1 } as WireState
  placeCapsuleWireframe(three, line, capsule)
  return line
}

/** Put a capsule wireframe onto `capsule` (rebuilding its lines when the radius or length changed). */
export function placeCapsuleWireframe(three: Three, line: LineSegments, capsule: CapsuleNow): void {
  const [ax, ay, az] = capsule.a
  const [bx, by, bz] = capsule.b
  const dx = bx - ax, dy = by - ay, dz = bz - az
  const length = Math.hypot(dx, dy, dz)
  const state = line.userData.collisionWire as WireState
  const tol = Math.max(1e-5, capsule.r * 1e-3)
  if (Math.abs(state.r - capsule.r) > tol || Math.abs(state.length - length) > tol) {
    const geometry = line.geometry as BufferGeometry
    geometry.setAttribute('position', new three.Float32BufferAttribute(capsuleLineSegments(capsule.r, length), 3))
    geometry.computeBoundingSphere()
    state.r = capsule.r
    state.length = length
  }
  line.position.set((ax + bx) / 2, (ay + by) / 2, (az + bz) / 2)
  if (length > 1e-9) line.quaternion.setFromUnitVectors(new three.Vector3(0, 1, 0), new three.Vector3(dx / length, dy / length, dz / length))
  else line.quaternion.identity()
  line.updateMatrix()
  line.updateMatrixWorld()
}

/** Debug overlay: the bound capsules of a figure as wireframes in one group (world space). */
export interface CollisionOverlay {
  /** Add to the SCENE root (identity transform) — the lines are in world space. */
  readonly group: Group
  readonly binding: CollisionBinding
  update(): void
  dispose(): void
}

export function createCollisionOverlay(three: Three, root: Object3D,
  payload: CollisionPayload | null | undefined): CollisionOverlay | null {
  const binding = bindCollision(three, root, payload)
  if (!binding) return null
  const group = new three.Group()
  group.name = 'collision-capsules'
  group.matrixAutoUpdate = false
  const lines = binding.capsules.map(entry => {
    const line = capsuleWireframe(three, entry.now, CAPSULE_REGION_COLORS[entry.capsule.region])
    line.matrixAutoUpdate = false
    line.name = `capsule:${entry.capsule.id}`
    group.add(line)
    return line
  })
  return {
    group, binding,
    update() {
      binding.update()
      binding.capsules.forEach((entry, i) => placeCapsuleWireframe(three, lines[i], entry.now))
    },
    dispose() {
      group.removeFromParent()
      for (const line of lines) {
        line.geometry.dispose()
        ;(line.material as LineBasicMaterial).dispose()
      }
    },
  }
}

