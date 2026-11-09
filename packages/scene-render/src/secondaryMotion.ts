/** Secondary motion in metres and real seconds; three's world is Y-up.
 * Gravity is (0,-9.81,0). No runtime three import: consumers inject it.
 *
 * CONTACT WITH THE BODY'S COLLISION CAPSULES (`setCollision`, contract
 * `docs/schnittstellen-3d.md` "Collision capsules"). Every driven link that
 * has a swing budget (`max_deg` or `sag_max_deg` > 0) has a TIP in its bone
 * frame: the next joint of its chain, else its most protruding own vertex —
 * of the bind vertices skinned > 50 % to it, the one reaching farthest along
 * its centroid lever (none: twice the centroid lever). After the link's
 * dynamics have produced its rendered frame, the garment push itself
 * (`pushOutOfCapsules`) says whether the tip is inside a capsule and which way
 * is out; the link is then ROTATED about its own joint, in the plane of its
 * lever and that way out, by the smallest angle that puts the tip outside —
 * the tip keeps its lever length, children ride the corrected frame. The
 * turn is capped at the link's swing budget (max(`max_deg`, `sag_max_deg`) ×
 * its motion share): a capsule driven through the middle of the tissue leaves
 * the rest inside rather than folding the link away. The oscillator state is not touched —
 * the contact is a constraint on the rendered frame, so it can neither inject
 * energy nor stall the spring.
 *  - ANCESTOR CAPSULES are excluded per chain: a capsule whose start joint
 *    `a` is an ancestor of the chain root (or a bone in its `anchor_blend`)
 *    carries the chain itself — a chest chain hanging from Spine2 is never
 *    pushed out of the Hips/Spine/chest capsules it sits in, only out of the
 *    arms, legs and head (Review Focus 2 of the collision plan).
 *  - BIND RULE, as for garments: per tip and capsule the radius is capped at
 *    the tip's distance to that capsule in the bind pose (bind-pose tip from
 *    the bone's `boneInverse`, bind-pose capsule `BoundCapsule.bind`), so the
 *    contact moves nothing in the bind pose.
 *  - INERT: no driven link, no payload, or far LOD → no binding, no work.
 */
import type { Bone, Matrix4, Quaternion, Object3D, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from './clipRetarget'
import { bindCollision } from './collision'
import type { BoundCapsule, CollisionBinding, CollisionPayload, Vec3 } from './collision'
import { inGarment } from './figure'
import { pushOutOfCapsules } from './garmentCollision'
import type { CollideCapsule } from './garmentCollision'
type Three = typeof import('three')

export interface MotionGroup {
  bones: string[]
  freq_hz: number
  zeta: number
  spill: number
  translate: number
  flatten: number
  stretch: number
  spread: number
  flatten_floor: number
  length: number
  girth: number
  scale_axis?: 'centroid' | 'bone'
  /** The last N links of each chain ride rigidly on their parent: its rotation and
   * position, never its scale, and no rest, sag, stretch, swing or state extent. */
  rigid_tail?: number
  gravity_scale: number
  sag_max_deg: number
  spill_max_deg: number
  head_sag: number
  gravity: number
  axis_gain: [number, number, number]
  gain: number
  max_deg: number
  squash: [number, number]
  rest_deg: number
  rest_max_deg: number
  straighten_deg: number
  freetext_clothing_gain: number
}
/** Package metadata profiles are multipliers; runtime groups are already resolved. */
export type MotionAttributeProfiles = Record<string, Record<string, Partial<Pick<MotionGroup,
  'freq_hz' | 'zeta' | 'gravity' | 'gain' | 'max_deg' | 'sag_max_deg' | 'spill_max_deg' | 'head_sag' | 'flatten' | 'stretch' | 'spread' | 'flatten_floor' | 'spill' | 'translate'>>>>
export interface ExtensionRigDeclaration extends Omit<MotionGroup, 'bones' | 'gravity_scale' | 'rest_deg' | 'flatten_floor'> {
  controls?: string[] | null
  flatten_floor: number | null
  id: string
  op: string
  depends_on: string | null
  chains: { bone: string; parent: string }[][]
  params: Record<string, unknown>
  templates?: string[] | "*" | { feature: string } | null
  applies_to: Record<string, unknown[]>
  attribute_profiles?: MotionAttributeProfiles
}
export interface SecondaryMotionPayload {
  rev: string
  groups: Record<string, MotionGroup>
}
export interface SecondaryMotion {
  configure(payload?: SecondaryMotionPayload): void
  update(realDelta: number, options?: { frozen?: boolean; far?: boolean }): void
  /** The body's `collision` payload the extension tips are kept outside of (module docstring); null = off. */
  setCollision(payload?: CollisionPayload | null): void
  /** Inspection (checks, debug overlays): every link with contacts — its tip in world space as last
   *  rendered, its bone frame tip, and the ids of the capsules it is kept outside of. */
  contactTips(): { bone: string; tip: Vec3; tipLocal: Vec3; capsules: string[] }[]
  reset(): void
  dispose(): void
}

/** Scan steps over the swing budget, then refinement iterations, of a tip's contact turn. */
const CONTACT_SCAN = 12
const CONTACT_REFINE = 14
/** A tip moved less than this (metres) by the push counts as outside. */
const COLLIDE_SLACK = 1e-6

/**
 * Which capsules a chain may collide with: every bound capsule whose start
 * joint `a` is NOT one of `ancestors` (normalised names of the bones the
 * chain hangs from — its root's ancestors and `anchor_blend` bones). Pure;
 * payload order is kept.
 */
export function extensionCapsules<T extends { capsule: { a: string } }>(bound: readonly T[], ancestors: ReadonlySet<string>): T[] {
  return bound.filter(entry => !ancestors.has(normBoneName(entry.capsule.a)))
}

/**
 * The bind rule of one tip: per capsule the factor (0..1] its current radius
 * is multiplied by — `min(1, d0 / r_bind)`, `d0` the tip's distance to the
 * capsule's bind-pose axis. Pure; `tipBind` and the capsules in one frame.
 */
export function tipBindFactors(tipBind: Vec3, capsules: readonly { a: Vec3; b: Vec3; r: number }[]): number[] {
  return capsules.map(c => {
    if (!(c.r > 0)) return 1
    const abx = c.b[0] - c.a[0], aby = c.b[1] - c.a[1], abz = c.b[2] - c.a[2]
    const apx = tipBind[0] - c.a[0], apy = tipBind[1] - c.a[1], apz = tipBind[2] - c.a[2]
    const len2 = abx * abx + aby * aby + abz * abz
    const t = len2 > 1e-12 ? Math.min(1, Math.max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0
    return Math.min(1, Math.hypot(apx - abx * t, apy - aby * t, apz - abz * t) / c.r)
  })
}

/** Exact propagation around a linearly moving static-equilibrium target.
 * x=p-T', w=v-v_T' gives x''+2*zeta*omega*x'+omega²*x=0.
 * Handle every damping regime without explicit-integrator instability.
 * Inputs are never mutated; the caller has already resolved static gravity.
 */
export function stepSecondaryParticle(
  p: Vector3, v: Vector3, target: Vector3, targetVelocity: Vector3,
  params: MotionGroup, h: number,
  output?: { p: Vector3; v: Vector3; x: Vector3; w: Vector3 },
): { p: Vector3; v: Vector3 } {
  const omega = 2 * Math.PI * params.freq_hz
  const x = (output?.x ?? p.clone()).copy(p).sub(target)
  const w = (output?.w ?? v.clone()).copy(v).sub(targetVelocity)
  const alpha = params.zeta * omega
  let xx: number, xw: number, wx: number, ww: number
  if (omega * omega < 1e-12) {
    xx = ww = 1; xw = h; wx = 0
  } else if (params.zeta > 1) {
    const z = params.zeta + Math.sqrt(params.zeta * params.zeta - 1)
    // Rationalized slow root avoids cancellation for large damping.
    const slow = -omega / z
    const fast = -omega * z
    const eSlow = Math.exp(slow * h), eFast = Math.exp(fast * h)
    const denominator = slow - fast
    xx = (slow * eFast - fast * eSlow) / denominator
    xw = (eSlow - eFast) / denominator
    wx = omega * omega * (eFast - eSlow) / denominator
    ww = (slow * eSlow - fast * eFast) / denominator
  } else {
    const damped = omega * Math.sqrt(1 - params.zeta * params.zeta)
    const decay = Math.exp(-alpha * h)
    const c = Math.cos(damped * h)
    const sh = damped === 0 ? h : Math.sin(damped * h) / damped
    xx = decay * (c + alpha * sh)
    xw = decay * sh
    wx = -omega * omega * xw
    ww = decay * (c - alpha * sh)
  }
  const result = output ?? { p: target.clone(), v: targetVelocity.clone() }
  result.p.copy(target).addScaledVector(targetVelocity, h)
    .addScaledVector(x, xx).addScaledVector(w, xw)
  result.v.copy(targetVelocity).addScaledVector(x, wx).addScaledVector(w, ww)
  return result
}

interface Bind {
  bone: Bone
  local: Matrix4
  centroid: Vector3
  mass: number
  /** Bone-frame point of the bind vertex skinned > 50 % to the bone that reaches farthest along the
   *  centroid lever (the tissue's most protruding point); zero when no vertex qualifies. */
  reach: Vector3
  /** Bone-local axis the extension scale acts along: towards the next chain joint, else the centroid. */
  scaleAxis: Vector3
  centroidWorld: Vector3
  gravityRest: Vector3
  gravityProjection: number
  bodyFront: Vector3
  head: Vector3
  parentHead: Vector3
  worldRotation: Quaternion
  /** World matrix of the bone WITHOUT its own extension scale (set each update). */
  pureWorld: Matrix4
  lateral: Vector3
  singleLateral: Vector3
  centeringRotation: Quaternion
  pairedLateral: Vector3
  auto: boolean
  depth: number
  rotation: Quaternion
  straightenRotation: Quaternion
  localRotation: Quaternion
  /** Inverse bind world matrix, for the anchor blend of other bones. */
  bindWorldInverse: Matrix4
  /** Bones the bone's tissue followed before it was built, with their shares
   *  (glTF extras `anchor_blend`); the rest frame follows their blend instead of
   *  the one parent. Undefined = the parent alone. */
  anchorBlend?: { bind: Bind; share: number }[]
}
interface Particle {
  bind: Bind
  roots: Bind[]
  chain?: Particle[]
  /** Share of the root chain's dynamic swing budget, from immutable bind spans. */
  motionShare: number
  sag?: { frame: Matrix4; rotation: Quaternion; head: Vector3; centre: Vector3; force: Vector3; torque: Vector3; weight: number; q: Quaternion }
  params: MotionGroup
  paramsFrom: MotionGroup
  paramsTo: MotionGroup
  paramsBlend: number
  staticFrequency: number
  staticFrequencyFrom: number
  staticFrequencyTo: number
  staticWeight: number
  staticWeightFrom: number
  staticWeightTo: number
  p: Vector3 | null
  v: Vector3
  target: Vector3 | null
  rest: number
  restFrom: number
  restTo: number
  blend: number
  straighten: number
  straightenFrom: number
  straightenRestFrom: number
  straightenBlend: number
  straightenThreshold: number
  anchorRotation: Quaternion | null
  /** The link's tip in its bone frame: the next chain joint, else its most protruding own vertex. */
  tipLocal: Vector3
  /** Normalised names of the bones the chain hangs from (its ancestor capsules are excluded). */
  ancestors: Set<string>
  /** The capsules this tip is kept outside of, with the bind-rule radius factor; empty = no contact. */
  contacts: { bound: BoundCapsule; factor: number }[]
}
/** Maximum transverse compensation: strong flattening must not inflate the mesh. */
const SPREAD_CAP = 1.6
const DEFAULT_AXIS_GAIN: [number, number, number] = [1, 1, 1]
const BLENDED_FIELDS = ['gravity', 'freq_hz', 'zeta', 'gain', 'flatten', 'stretch', 'spread', 'flatten_floor', 'spill', 'translate', 'head_sag', 'length', 'girth'] as const
/** Smooth numeric state changes over the same 1.5 seconds as the rest angle. */
export function blendMotionParams(from: MotionGroup, to: MotionGroup, elapsed: number, output?: MotionGroup): MotionGroup {
  const t = Math.max(0, Math.min(1, elapsed / 1.5))
  const weight = t * t * (3 - 2 * t)
  const result = output ?? { ...to }
  for (const field of BLENDED_FIELDS) {
    const fallback = (field === 'head_sag' || field === 'length' || field === 'girth') ? 1 : field === 'flatten_floor' ? to.squash[0] : field === 'spread' ? 0.5 : 0
    result[field] = (from[field] ?? fallback) + ((to[field] ?? fallback) - (from[field] ?? fallback)) * weight
  }
  return result
}
const centroidCache = new WeakMap<Object3D, { centroid: Vector3; mass: number; reach: Vector3 }[]>()
/** Skin weight above which a vertex counts as the bone's own for its contact tip. */
const REACH_WEIGHT = 0.5
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x))
/** Linear below half the limit, then C1 tanh saturation: monotonic and bounded. */
export const softMotionAngle = (angle: number, limit: number) => {
  if (limit <= 0) return 0
  const knee = limit / 2
  return angle <= knee ? angle : knee + knee * Math.tanh((angle - knee) / knee)
}
const straighteningFraction = (rest: number, threshold: number) => {
  const f = threshold > 0 ? clamp(Math.abs(rest) * 180 / Math.PI / threshold, 0, 1) : 0
  return f * f * (3 - 2 * f)
}
const restAngle = (g: MotionGroup) => clamp(g.rest_deg, -g.rest_max_deg, g.rest_max_deg) * Math.PI / 180

/** Build once while the skeleton is in bind pose, after its up-axis correction.
 * Centroids use ALL positive skin weights, aggregated over every skinned mesh.
 * bindMatrix maps each raw vertex into skeleton bind space; boneInverse maps
 * it into the bone's anchor frame. Imported joint axes are never geometry.
 * Rest axes follow bind-pose attachment geometry; only chain roots rotate.
 * This owns only CPU state and each driven bone's matrixAutoUpdate setting.
 */
export function createSecondaryMotion(
  three: Three, root: Object3D, payload?: SecondaryMotionPayload,
  template?: Object3D,
): SecondaryMotion {
  const names = new Set(Object.values(payload?.groups ?? {}).flatMap(g => g.bones.map(normBoneName)))
  let matching = false
  if (names.size) root.traverse(o => { if ((o as Bone).isBone && names.has(normBoneName(o.name))) matching = true })
  if (!matching) {
    let delegate: SecondaryMotion | undefined
    let stopped = false
    // Held, not bound: without a driven bone there is nothing to collide (inert).
    let collision: CollisionPayload | null | undefined
    return {
      configure(next) {
        if (stopped) return
        if (delegate) { delegate.configure(next); return }
        const requested = new Set(Object.values(next?.groups ?? {}).flatMap(g => g.bones.map(normBoneName)))
        let found = false
        if (requested.size) root.traverse(o => { if ((o as Bone).isBone && requested.has(normBoneName(o.name))) found = true })
        if (found) {
          delegate = createSecondaryMotion(three, root, next, template)
          if (collision) delegate.setCollision(collision)
        }
      },
      update(dt, options) { delegate?.update(dt, options) },
      setCollision(payload) {
        if (stopped) return
        collision = payload
        delegate?.setCollision(payload)
      },
      contactTips() { return delegate?.contactTips() ?? [] },
      reset() { delegate?.reset() },
      dispose() { delegate?.dispose(); stopped = true },
    }
  }
  root.updateWorldMatrix(true, false)
  root.updateMatrixWorld(true)
  const gravity = new three.Vector3(0, -9.81, 0)
  const binds = new Map<Bone, Bind>()
  /** Each bone's boneInverse from a BODY skin (bind frame of the collision capsules) — the bind rule's tip. */
  const boneInverses = new Map<Bone, Matrix4>()
  const sums = new Map<Bone, { sum: Vector3; weight: number }>()
  const bindUp = new three.Vector3(0, 1, 0)
  const cached = template && centroidCache.get(template)
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (!mesh.isSkinnedMesh) return
    const pos = mesh.geometry.getAttribute('position')
    const indices = mesh.geometry.getAttribute('skinIndex')
    const weights = mesh.geometry.getAttribute('skinWeight')
    if (!pos || !indices || !weights) return
    const body = !inGarment(mesh)
    mesh.skeleton.bones.forEach((bone, index) => {
      if (body && !boneInverses.has(bone) && mesh.skeleton.boneInverses[index]) boneInverses.set(bone, mesh.skeleton.boneInverses[index])
      if (!binds.has(bone)) {
        const q = bone.getWorldQuaternion(new three.Quaternion()).invert()
        let depth = 0
        for (let parent = bone.parent; parent; parent = parent.parent) depth++
        binds.set(bone, { bone, local: bone.matrix.clone(), centroid: new three.Vector3(), mass: 0, reach: new three.Vector3(), scaleAxis: new three.Vector3(), centroidWorld: new three.Vector3(),
          gravityRest: gravity.clone().applyQuaternion(q), gravityProjection: 0, bodyFront: new three.Vector3(),
          head: bone.getWorldPosition(new three.Vector3()), parentHead: bone.parent!.getWorldPosition(new three.Vector3()), worldRotation: q.clone().invert(), pureWorld: new three.Matrix4(),
          singleLateral: new three.Vector3(), centeringRotation: new three.Quaternion(), lateral: new three.Vector3(), pairedLateral: new three.Vector3(), auto: bone.matrixAutoUpdate, depth, rotation: new three.Quaternion(), straightenRotation: new three.Quaternion(), localRotation: bone.quaternion.clone(),
          bindWorldInverse: bone.matrixWorld.clone().invert() })
      }
    })
    // One pass over four influences per vertex, not one pass per skeleton bone.
    // Each primitive may have its own bind transform and skeleton indexing.
    if (cached) return
    const toBone = mesh.skeleton.boneInverses.map(inv => inv.clone().multiply(mesh.bindMatrix))
    const vertex = new three.Vector3()
    for (let i = 0; i < pos.count; i++) {
      for (let j = 0; j < 4; j++) {
        const weight = weights.getComponent(i, j)
        const index = indices.getComponent(i, j)
        const bone = mesh.skeleton.bones[index]
        if (weight <= 0 || !bone) continue
        const acc = sums.get(bone) ?? { sum: new three.Vector3(), weight: 0 }
        vertex.fromBufferAttribute(pos, i).applyMatrix4(toBone[index])
        acc.sum.addScaledVector(vertex, weight)
        acc.weight += weight
        sums.set(bone, acc)
      }
    }
  })
  for (const [bone, acc] of sums) {
    if (acc.weight > 0) {
      binds.get(bone)!.centroid.copy(acc.sum).divideScalar(acc.weight)
      binds.get(bone)!.mass = acc.weight
    }
  }
  if (!cached) {
    // Second pass, now that the centroids are known: each bone's most protruding own vertex (contact tip).
    const best = new Map<Bone, number>()
    root.traverse(o => {
      const mesh = o as SkinnedMesh
      if (!mesh.isSkinnedMesh) return
      const pos = mesh.geometry.getAttribute('position')
      const indices = mesh.geometry.getAttribute('skinIndex')
      const weights = mesh.geometry.getAttribute('skinWeight')
      if (!pos || !indices || !weights) return
      const toBone = mesh.skeleton.boneInverses.map(inv => inv.clone().multiply(mesh.bindMatrix))
      const vertex = new three.Vector3()
      for (let i = 0; i < pos.count; i++) {
        for (let j = 0; j < 4; j++) {
          if (weights.getComponent(i, j) <= REACH_WEIGHT) continue
          const index = indices.getComponent(i, j)
          const bind = binds.get(mesh.skeleton.bones[index])
          if (!bind || bind.mass <= 0) continue
          vertex.fromBufferAttribute(pos, i).applyMatrix4(toBone[index])
          const along = vertex.dot(bind.centroid)
          if (along > (best.get(bind.bone) ?? -Infinity)) { best.set(bind.bone, along); bind.reach.copy(vertex) }
        }
      }
    })
  }
  if (cached) [...binds.values()].forEach((b, i) => { b.centroid.copy(cached[i].centroid); b.mass = cached[i].mass; b.reach.copy(cached[i].reach) })
  else if (template) centroidCache.set(template, [...binds.values()].map(b => ({ centroid: b.centroid.clone(), mass: b.mass, reach: b.reach.clone() })))
  for (const b of binds.values()) {
    b.centroidWorld.copy(b.centroid).applyMatrix4(b.bone.matrixWorld)
    // Capture the actual bind lever, including non-uniform model scale.
    b.gravityProjection = gravity.dot(b.centroidWorld.clone().sub(b.head).normalize()) / 9.81
  }
  const bindHeads = new Map<Bone, Vector3>()
  root.traverse(o => { if ((o as Bone).isBone) bindHeads.set(o as Bone, o.getWorldPosition(new three.Vector3())) })
  const byName = new Map([...binds.values()].map(b => [normBoneName(b.bone.name), b]))
  // The rigger spread the tissue a built bone takes over across several bones
  // (breast tissue: 22-63 % Spine1, the rest Spine2). Following the one parent
  // alone made it sag with the upper chest in clips that bend it against the
  // lower one; the build measures the shares and stores them on the joint.
  for (const b of binds.values()) {
    const raw = (b.bone.userData as { anchor_blend?: Record<string, number> } | undefined)?.anchor_blend
    if (!raw || typeof raw !== 'object') continue
    const entries = Object.entries(raw)
      .map(([name, share]) => ({ bind: byName.get(normBoneName(name)), share: Number(share) }))
      .filter((e): e is { bind: Bind; share: number } => !!e.bind && e.bind !== b && Number.isFinite(e.share) && e.share > 0)
    const total = entries.reduce((sum, e) => sum + e.share, 0)
    if (total > 0) b.anchorBlend = entries.map(e => ({ bind: e.bind, share: e.share / total }))
  }
  let particles: Particle[] = []
  /** rigid_tail links, parent first: carried by their parent, never driven. */
  let rigids: Bind[] = []
  let far = false
  let disposed = false
  let collisionPayload: CollisionPayload | null | undefined
  let collision: CollisionBinding | null = null
  /** Bind the capsules (lazily — only with a driven link) and give each moving tip its contacts. */
  const prepareCollision = () => {
    if (!collisionPayload || !particles.length) {
      collision = null
      for (const st of particles) st.contacts = []
      return
    }
    collision ??= bindCollision(three, root, collisionPayload)
    const bindTip = new three.Vector3()
    for (const st of particles) {
      st.contacts = []
      const budget = Math.max(st.paramsTo.max_deg ?? 0, st.paramsTo.sag_max_deg ?? 0)
      if (!collision || !(budget > 0)) continue
      const bound = extensionCapsules(collision.capsules, st.ancestors)
      const inverse = boneInverses.get(st.bind.bone)
      let factors = bound.map(() => 1)
      if (inverse) {
        // The tip in the BIND frame of the capsules: bone frame → inverse(boneInverse).
        bindTip.copy(st.tipLocal).applyMatrix4(new three.Matrix4().copy(inverse).invert())
        factors = tipBindFactors([bindTip.x, bindTip.y, bindTip.z], bound.map(entry => entry.bind))
      }
      st.contacts = bound.map((entry, i) => ({ bound: entry, factor: factors[i] }))
    }
    if (!particles.some(st => st.contacts.length)) collision = null
  }
  const restore = (b: Bind) => {
    b.bone.matrix.copy(b.local)
    b.bone.matrixAutoUpdate = b.auto
    b.bone.matrixWorldNeedsUpdate = true
  }
  const configure = (next?: SecondaryMotionPayload) => {
    if (disposed) return
    const previous = new Map(particles.map(p => [p.bind.bone, p]))
    const selected = new Set<Bone>()
    const extensionNames = new Set(Object.values(next?.groups ?? {}).flatMap(group =>
      group.bones.map(normBoneName)))
    const nextParticles: Particle[] = []
    const nextRigids: Bind[] = []
    for (const params of Object.values(next?.groups ?? {})) {
      const chain = params.bones.map(name => byName.get(normBoneName(name)))
      // Absent/partial groups and vertices without influence are ordinary skips.
      if (chain.some(b => !b || b.centroid.lengthSq() < 1e-12)) continue
      const members = new Set((chain as Bind[]).map(b => b.bone))
      const roots = (chain as Bind[]).filter(b => !members.has(b.bone.parent as Bone))
      // A link with a successor scales along the axis to that joint, so girth
      // (perpendicular) never pushes the next link off its line; the last link
      // uses its declared bind-frame axis.
      for (const b of chain as Bind[]) {
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        if (child) b.scaleAxis.setFromMatrixPosition(child.local)
        else if (params.scale_axis === 'bone') b.scaleAxis.set(0, 1, 0)
        else b.scaleAxis.copy(b.centroid)
        if (b.scaleAxis.lengthSq() < 1e-12) b.scaleAxis.copy(b.centroid)
        b.scaleAxis.normalize()
      }
      // Derive front once from immutable bind geometry, never a model axis.
      const meanRoot = new three.Vector3(), meanParent = new three.Vector3(), meanTarget = new three.Vector3()
      for (const b of roots) {
        meanRoot.add(b.head)
        meanParent.add(b.parentHead)
      }
      meanRoot.divideScalar(roots.length); meanParent.divideScalar(roots.length)
      for (const b of chain as Bind[]) meanTarget.add(b.centroidWorld)
      meanTarget.divideScalar(chain.length)
      const front = meanRoot.clone().sub(meanParent)
      front.addScaledVector(bindUp, -front.dot(bindUp))
      if (front.lengthSq() < 1e-10) {
        front.copy(meanTarget).sub(meanRoot)
        front.addScaledVector(bindUp, -front.dot(bindUp))
      }
      front.normalize()
      if (roots.length === 1) {
        // The root may sit off the midline, so front comes from the widest
        // symmetric pair of the parent's other children, not the root offset.
        const parent = roots[0].bone.parent!
        const candidates = parent.children.filter(o => (o as Bone).isBone &&
          o !== roots[0].bone && !extensionNames.has(normBoneName(o.name))) as Bone[]
        const horizontal = (v: Vector3) => v.addScaledVector(bindUp, -v.dot(bindUp))
        let maxDistance = 0, maxSeparation = 0
        const widest = new three.Vector3()
        for (let i = 0; i < candidates.length; i++) {
          const head = bindHeads.get(candidates[i])!
          maxDistance = Math.max(maxDistance, horizontal(head.clone().sub(roots[0].parentHead)).length())
          for (let j = 0; j < i; j++) {
            const separation = horizontal(head.clone().sub(bindHeads.get(candidates[j])!))
            const length = separation.length()
            if (length > maxSeparation) { maxSeparation = length; widest.copy(separation) }
          }
        }
        if (maxSeparation > 1e-4 && maxSeparation >= .25 * maxDistance) {
          const corrected = bindUp.clone().cross(widest.normalize()).normalize()
          const centroidFront = horizontal(meanTarget.clone().sub(roots[0].parentHead))
          const signDirection = centroidFront.length() < 1e-6 ? front : centroidFront.normalize()
          const alignment = corrected.dot(signDirection)
          if (Math.abs(alignment) >= 1e-6) front.copy(alignment > 0 ? corrected : corrected.negate())
        }
      }
      for (const b of chain as Bind[]) {
        b.bodyFront.copy(front)
        if (b.bodyFront.lengthSq() < 1e-10) b.bodyFront.set(0, 0, 1)
        b.bodyFront.applyQuaternion(b.worldRotation.clone().invert())
        // Each link uses its chain root's horizontal bind-pose side direction.
        let chainRoot = b
        for (let n = b.bone.parent; n && members.has(n as Bone); n = n.parent) chainRoot = binds.get(n as Bone)!
        b.pairedLateral.set(0, 0, 0)
        if (roots.length >= 2) {
          b.pairedLateral.copy(chainRoot.head).sub(meanRoot)
          b.pairedLateral.addScaledVector(bindUp, -b.pairedLateral.dot(bindUp)).normalize()
          b.pairedLateral.applyQuaternion(b.worldRotation.clone().invert())
        }
        b.straightenRotation.identity()
        if (!roots.includes(b)) {
          const parent = binds.get(b.bone.parent as Bone)!
          const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
          const ownLever = child ? child.head.clone().sub(b.head) : b.centroidWorld.clone().sub(b.head)
          const parentLever = b.head.clone().sub(parent.head)
          if (ownLever.lengthSq() > 1e-12 && parentLever.lengthSq() > 1e-12) {
            const inverseBind = b.worldRotation.clone().invert()
            b.straightenRotation.setFromUnitVectors(ownLever.normalize().applyQuaternion(inverseBind),
              parentLever.normalize().applyQuaternion(inverseBind))
          }
        }
        b.lateral.set(0, 0, 0)
        if (!roots.includes(b)) continue
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        const lever = child ? child.head.clone().sub(b.head) : b.centroidWorld.clone().sub(b.head)
        lever.normalize()
        const toward = front.clone().addScaledVector(lever, -front.dot(lever))
        if (toward.lengthSq() < 1e-10) toward.copy(bindUp).addScaledVector(lever, -bindUp.dot(lever))
        b.lateral.crossVectors(lever, toward).normalize().applyQuaternion(b.worldRotation.clone().invert())
        if (roots.length === 1) {
          const inverseBind = b.worldRotation.clone().invert()
          const axis = front.clone().cross(bindUp).normalize()
          // Match the existing positive raise direction in the sagittal plane.
          if (axis.dot(lever.clone().cross(toward)) < 0) axis.negate()
          const sagittal = lever.clone().addScaledVector(axis, -lever.dot(axis))
          b.singleLateral.copy(axis).applyQuaternion(inverseBind)
          b.centeringRotation.identity()
          if (sagittal.lengthSq() > 1e-12) {
            b.centeringRotation.setFromUnitVectors(lever.clone().applyQuaternion(inverseBind),
              sagittal.normalize().applyQuaternion(inverseBind))
          }
        }
      }
      // Links within rigid_tail of a chain end are carried, not simulated.
      const tail = Math.max(0, Math.floor(params.rigid_tail ?? 0))
      const fromLeaf = (b: Bind): number => {
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        return child ? 1 + fromLeaf(child) : 0
      }
      for (const bind of chain as Bind[]) {
        if (selected.has(bind.bone)) continue
        if (tail > 0 && !roots.includes(bind) && fromLeaf(bind) < tail) {
          selected.add(bind.bone)
          bind.bone.matrixAutoUpdate = false
          nextRigids.push(bind)
          continue
        }
        selected.add(bind.bone)
        const to = restAngle(params)
        const old = previous.get(bind.bone)
        const particle: Particle = old ?? { bind, roots, motionShare: 1, params, paramsFrom: params, paramsTo: params, paramsBlend: 1.5, p: null, v: new three.Vector3(),
          target: null, anchorRotation: null, rest: to, restFrom: to, restTo: to, blend: 1.5,
          straighten: straighteningFraction(to, params.straighten_deg ?? 0),
          straightenFrom: straighteningFraction(to, params.straighten_deg ?? 0), straightenRestFrom: Math.abs(to),
          straightenBlend: 1.5, straightenThreshold: params.straighten_deg ?? 0,
          staticFrequency: params.freq_hz, staticFrequencyFrom: params.freq_hz, staticFrequencyTo: params.freq_hz,
          staticWeight: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          staticWeightFrom: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          staticWeightTo: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          tipLocal: new three.Vector3(), ancestors: new Set(), contacts: [] }
        if (particle.restTo !== to) {
          particle.restFrom = particle.rest
          particle.restTo = to
          particle.blend = 0
        }
        if (particle.straightenThreshold !== (params.straighten_deg ?? 0)) {
          particle.straightenFrom = particle.straighten
          particle.straightenRestFrom = Math.abs(particle.rest)
          particle.straightenThreshold = params.straighten_deg ?? 0
          particle.straightenBlend = 0
        }
        particle.roots = roots
        // Contact geometry (immutable bind data): the tip, and the bones the chain hangs from.
        const child = (chain as Bind[]).find(c => c.bone.parent === bind.bone)
        if (child) particle.tipLocal.setFromMatrixPosition(child.local)
        else if (bind.reach.lengthSq() > 1e-12) particle.tipLocal.copy(bind.reach)
        else particle.tipLocal.copy(bind.centroid).multiplyScalar(2)
        let chainRoot = bind
        for (let n = bind.bone.parent; n && members.has(n as Bone); n = n.parent) chainRoot = binds.get(n as Bone)!
        particle.ancestors.clear()
        for (let n = chainRoot.bone.parent; n; n = n.parent) if ((n as Bone).isBone) particle.ancestors.add(normBoneName(n.name))
        for (const blend of [chainRoot.anchorBlend, bind.anchorBlend]) {
          for (const e of blend ?? []) particle.ancestors.add(normBoneName(e.bind.bone.name))
        }
        if (BLENDED_FIELDS.some(field => particle.paramsTo[field] !== params[field])) {
          particle.paramsFrom = { ...particle.params }
          // Preserve an interrupted static transition's frequency and weight.
          const zero = (2 * Math.PI * params.freq_hz) ** 2 < 1e-12
          particle.staticFrequencyTo = zero ? particle.staticFrequency : params.freq_hz
          particle.staticFrequencyFrom = particle.staticWeight === 0
            ? particle.staticFrequencyTo : particle.staticFrequency
          particle.staticWeightFrom = particle.staticWeight
          particle.staticWeightTo = zero ? 0 : 1
          particle.paramsBlend = 0
        }
        particle.paramsTo = { ...params, bones: [...params.bones], squash: [...params.squash] }
        particle.params = blendMotionParams(particle.paramsFrom, particle.paramsTo, particle.paramsBlend)
        bind.bone.matrixAutoUpdate = false
        nextParticles.push(particle)
      }
    }
    for (const rootParticle of nextParticles.filter(p => p.roots.includes(p.bind))) {
      const chain = nextParticles.filter(p => {
        if (p.roots !== rootParticle.roots) return false
        for (let n: Object3D | null = p.bind.bone; n; n = n.parent) if (n === rootParticle.bind.bone) return true
        return false
      }).sort((a, b) => a.bind.depth - b.bind.depth)
      // The same span convention as sag: joint-to-joint, with twice the
      // centroid lever for the final link. Bind geometry keeps shares fixed
      // through rest, extent and dynamic changes; each root owns its budget.
      const spans = chain.map((st, j) => j + 1 < chain.length
        ? st.bind.head.distanceTo(chain[j + 1].bind.head)
        : 2 * st.bind.centroidWorld.distanceTo(st.bind.head))
      let remaining = 0, sum = 0
      for (let j = chain.length - 1; j >= 0; j--) {
        remaining += spans[j]
        chain[j].motionShare = remaining * remaining * spans[j]
        sum += chain[j].motionShare
      }
      for (const st of chain) {
        st.chain = chain
        st.motionShare = chain.length === 1 ? 1 : sum > 0 ? st.motionShare / sum : 1 / chain.length
        if (chain.length >= 2) st.sag ??= { frame: new three.Matrix4(), rotation: new three.Quaternion(),
          head: new three.Vector3(), centre: new three.Vector3(), force: new three.Vector3(), torque: new three.Vector3(), weight: 0, q: new three.Quaternion() }
      }
    }
    for (const old of [...particles.map(p => p.bind), ...rigids]) if (!selected.has(old.bone)) {
      restore(old)
      old.bone.updateWorldMatrix(false, true)
    }
    rigids = nextRigids.sort((a, b) => a.depth - b.depth)
    const drivenBones = new Set(nextParticles.map(st => st.bind.bone))
    const drivenDepth = (st: Particle) => {
      let depth = 0
      for (let parent = st.bind.bone.parent; parent; parent = parent.parent) if (drivenBones.has(parent as Bone)) depth++
      return depth
    }
    particles = nextParticles.sort((a, b) => drivenDepth(a) - drivenDepth(b))
    prepareCollision()
  }
  const reset = () => {
    for (const st of particles) { st.p = null; st.target = null; st.anchorRotation = null; st.v.set(0, 0, 0) }
  }
  const anchor = new three.Matrix4(), anchorFull = new three.Matrix4(), inverseAnchor = new three.Matrix4(), scale = new three.Matrix4(), rotationMatrix = new three.Matrix4()
  const anchorQ = new three.Quaternion(), restQ = new three.Quaternion(), dynamicQ = new three.Quaternion(), identityQ = new three.Quaternion()
  const restVector = new three.Vector3(), target = new three.Vector3(), head = new three.Vector3(), vTarget = new three.Vector3(), deltaG = new three.Vector3(), t = new three.Vector3(), base = new three.Vector3(), rendered = new three.Vector3(), localRendered = new three.Vector3(), u = new three.Vector3(), temp = new three.Vector3()
  const bodyVertical = new three.Vector3(), dynamicDelta = new three.Vector3(), previousDeviation = new three.Vector3(), nextDeviation = new three.Vector3()
  const headShift = new three.Vector3(), shiftPart = new three.Vector3(), originalLever = new three.Vector3()
  const translationMatrix = new three.Matrix4()
  const lateral = new three.Vector3(), localLateral = new three.Vector3(), staticVector = new three.Vector3(), equilibrium = new three.Vector3()
  const frameQ = new three.Quaternion(), frontLocal = new three.Vector3()
  const integration = { p: new three.Vector3(), v: new three.Vector3(), x: new three.Vector3(), w: new three.Vector3() }
  const centeringQ = new three.Quaternion()
  const chainCentre = new three.Vector3(), chainForce = new three.Vector3()
  const driven = new Map<Bone, Particle>()
  const delta = new three.Matrix4(), localBase = new three.Matrix4()
  const blendQ = new three.Quaternion(), deltaQ = new three.Quaternion(), firstQ = new three.Quaternion()
  const blendHead = new three.Vector3(), blendPos = new three.Vector3(), blendScale = new three.Vector3()
  const contactLocal = new three.Matrix4(), contactInverse = new three.Matrix4(), contactQ = new three.Quaternion()
  const tipAnchor = new three.Vector3(), tipWorld = new three.Vector3(), lever = new three.Vector3(), contactAxis = new three.Vector3()
  /**
   * Keep a link's tip outside its contact capsules (module docstring). The
   * link's frame `T·R(dynamicQ·restQ)·S` (anchor frame) is evaluated at the
   * tip; the garment push says how deep the tip is (`depthAt` = how far
   * `pushOutOfCapsules` moves it) and which way out. The link turns about its
   * joint (`T`'s origin) in the plane of its lever and that way out, by the
   * SMALLEST angle in (0, limit] that puts the tip outside — a scan of
   * `CONTACT_SCAN` steps, then bisection; when no angle gets it out (a capsule
   * through the tissue's middle) the angle with the shallowest tip. A turn
   * keeps the lever length, so a push along the lever turns nothing.
   */
  const keepTipOutside = (st: Particle, dynamic: Quaternion, rest: Quaternion, limit: number) => {
    if (!(limit > 0)) return
    const capsules: CollideCapsule[] = st.contacts.map(({ bound, factor }) =>
      ({ a: bound.now.a, b: bound.now.b, r: bound.now.r * factor }))
    contactLocal.makeRotationFromQuaternion(contactQ.copy(dynamic).multiply(rest))
      .premultiply(translationMatrix).multiply(scale)
    tipAnchor.copy(st.tipLocal).applyMatrix4(contactLocal)
    tipWorld.copy(tipAnchor).applyMatrix4(anchor)
    const pushed = pushOutOfCapsules([tipWorld.x, tipWorld.y, tipWorld.z], capsules)
    const depth0 = Math.hypot(pushed[0] - tipWorld.x, pushed[1] - tipWorld.y, pushed[2] - tipWorld.z)
    if (depth0 < COLLIDE_SLACK) return
    // The way out, in the anchor frame: the pushed point minus the tip.
    contactInverse.copy(anchor).invert()
    lever.copy(tipAnchor).sub(shiftPart)
    contactAxis.set(pushed[0], pushed[1], pushed[2]).applyMatrix4(contactInverse).sub(tipAnchor)
    contactAxis.crossVectors(lever, contactAxis)
    if (contactAxis.lengthSq() < 1e-20 || lever.lengthSq() < 1e-12) return
    contactAxis.normalize()
    const depthAt = (angle: number) => {
      tipWorld.copy(lever).applyAxisAngle(contactAxis, angle).add(shiftPart).applyMatrix4(anchor)
      const p = pushOutOfCapsules([tipWorld.x, tipWorld.y, tipWorld.z], capsules)
      return Math.hypot(p[0] - tipWorld.x, p[1] - tipWorld.y, p[2] - tipWorld.z)
    }
    const step = limit / CONTACT_SCAN
    let inside = 0, outside = -1, best = 0, bestDepth = depth0
    for (let k = 1; k <= CONTACT_SCAN; k++) {
      const depth = depthAt(k * step)
      if (depth < COLLIDE_SLACK) { outside = k * step; break }
      inside = k * step
      if (depth < bestDepth) { best = k * step; bestDepth = depth }
    }
    let angle: number
    if (outside > 0) {
      for (let i = 0; i < CONTACT_REFINE; i++) {
        const mid = (inside + outside) / 2
        if (depthAt(mid) < COLLIDE_SLACK) outside = mid; else inside = mid
      }
      angle = outside
    } else {
      // Shallowest tip: ternary search around the best scan sample.
      let lo = Math.max(0, best - step), hi = Math.min(limit, best + step)
      for (let i = 0; i < CONTACT_REFINE; i++) {
        const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3
        if (depthAt(m1) <= depthAt(m2)) hi = m2; else lo = m1
      }
      angle = (lo + hi) / 2
      const depth = depthAt(angle)
      if (!(depth < depth0)) return
      if (depth < COLLIDE_SLACK) {
        // An outside window the scan stepped over: its near edge, by bisection from below.
        let below = Math.max(0, best - step)
        for (let i = 0; i < CONTACT_REFINE; i++) {
          const mid = (below + angle) / 2
          if (depthAt(mid) < COLLIDE_SLACK) angle = mid; else below = mid
        }
      }
    }
    dynamic.premultiply(contactQ.setFromAxisAngle(contactAxis, angle))
  }
  /** Rest frame at the blend of the anchor bones' motions since bind: the bind
   *  head moved as linear skinning moved the tissue (sum of share x delta x head),
   *  the rotation is the normalised share-weighted sum of their delta rotations.
   *  At bind every delta is identity, so bind values are unchanged. */
  const blendAnchor = (b: Bind) => {
    blendQ.set(0, 0, 0, 0); blendHead.set(0, 0, 0)
    b.anchorBlend!.forEach(({ bind: x, share }, i) => {
      delta.copy(x.bone.matrixWorld).multiply(x.bindWorldInverse)
      blendHead.addScaledVector(temp.copy(b.head).applyMatrix4(delta), share)
      delta.decompose(blendPos, deltaQ, blendScale)
      if (i === 0) firstQ.copy(deltaQ)
      else if (firstQ.dot(deltaQ) < 0) deltaQ.set(-deltaQ.x, -deltaQ.y, -deltaQ.z, -deltaQ.w)
      blendQ.set(blendQ.x + share * deltaQ.x, blendQ.y + share * deltaQ.y, blendQ.z + share * deltaQ.z, blendQ.w + share * deltaQ.w)
    })
    blendQ.normalize()
    anchorQ.copy(blendQ).multiply(b.worldRotation)
    anchor.decompose(blendPos, deltaQ, blendScale)
    anchor.compose(blendHead, anchorQ, blendScale)
    anchorFull.copy(anchor)
  }
  const pureParent = (node: Object3D | null): Quaternion => {
    anchorQ.identity()
    // Multiply local rotations from leaf toward root, replacing driven transforms.
    for (let n = node; n; n = n.parent) {
      const parent = driven.get(n as Bone)
      if (parent) return anchorQ.premultiply(parent.bind.rotation)
      anchorQ.premultiply(n.quaternion)
    }
    return anchorQ
  }
  configure(payload)
  return {
    configure, reset,
    setCollision(next) {
      if (disposed) return
      collisionPayload = next
      collision = null
      prepareCollision()
    },
    contactTips() {
      const tip = new three.Vector3()
      return particles.filter(st => st.contacts.length).map(st => {
        tip.copy(st.tipLocal).applyMatrix4(st.bind.bone.matrixWorld)
        return { bone: st.bind.bone.name, tip: [tip.x, tip.y, tip.z] as Vec3,
          tipLocal: [st.tipLocal.x, st.tipLocal.y, st.tipLocal.z] as Vec3,
          capsules: st.contacts.map(c => c.bound.capsule.id) }
      })
    },
    update(realDelta, options = {}) {
      if (disposed || !particles.length) return
      const dt = Number.isFinite(realDelta) ? Math.max(0, realDelta) : 0
      if (!!options.far !== far) { far = !!options.far; reset() }
      root.updateWorldMatrix(true, false)
      root.updateMatrixWorld(true)
      // Capsules ride body joints no extension link drives: read them once, before the links.
      const colliding = !!collision && !far
      if (colliding) collision!.update()
      driven.clear()
      for (const st of particles) {
        st.paramsBlend = Math.min(1.5, st.paramsBlend + dt)
        st.params = blendMotionParams(st.paramsFrom, st.paramsTo, st.paramsBlend, st.params)
        // Rest blending is real time, including far LOD. Freeze stops dynamics.
        st.blend = Math.min(1.5, st.blend + dt)
        const fraction = st.blend / 1.5
        const limit = st.params.rest_max_deg * Math.PI / 180
        st.rest = clamp(st.restFrom + (st.restTo - st.restFrom) * fraction * fraction * (3 - 2 * fraction), -limit, limit)
        // Blend the derived amount: interpolating a threshold through zero
        // would snap raised chains fully straight on their first frame.
        st.straightenBlend = Math.min(1.5, st.straightenBlend + dt)
        const straightT = st.straightenBlend / 1.5
        const straightWeight = straightT * straightT * (3 - 2 * straightT)
        const straightTarget = straighteningFraction(st.rest, st.straightenThreshold)
        // The carried amount must also vanish smoothly when a simultaneous
        // rest transition passes through zero, including signed changes.
        const carried = st.straightenFrom * straighteningFraction(st.rest, st.straightenRestFrom * 180 / Math.PI)
        st.straighten = carried + (straightTarget - carried) * straightWeight
      }
      for (const st of particles) {
        const b = st.bind
        const motionLimit = st.params.max_deg * st.motionShare * Math.PI / 180
        anchor.copy(b.local)
        anchorFull.copy(b.local)
        // A driven ancestor contributes its frame WITHOUT its own extension
        // scale (otherwise girth/length/squash compound down a chain), while
        // the position follows the fully deformed ancestor so a lengthened
        // parent still carries its child outward.
        let drivenAncestor = false
        for (let n = b.bone.parent; n; n = n.parent) {
          const ancestor = driven.get(n as Bone)
          if (ancestor) { anchor.premultiply(ancestor.bind.pureWorld); anchorFull.premultiply(n.matrixWorld); drivenAncestor = true; break }
          anchor.premultiply(n.matrix); anchorFull.premultiply(n.matrix)
        }
        if (drivenAncestor) anchor.setPosition(temp.setFromMatrixPosition(anchorFull))
        pureParent(b.bone.parent).multiply(b.localRotation)
        const blended = !drivenAncestor && !!b.anchorBlend
        if (blended) blendAnchor(b)
        if (st.roots.length === 1 && st.roots[0] === b && b.singleLateral.lengthSq() > 1e-12) {
          centeringQ.identity().slerp(b.centeringRotation, st.straighten)
          restQ.setFromAxisAngle(b.singleLateral, st.rest).multiply(centeringQ)
        }
        else if (st.roots.includes(b) && b.lateral.lengthSq() > 1e-12) restQ.setFromAxisAngle(b.lateral, st.rest)
        else {
          restQ.identity().slerp(b.straightenRotation, st.straighten)
        }
        if (st.chain && st.chain.length >= 2 && st.chain[0] === st) {
          const chain = st.chain
          let mass = 0
          const centre = chainCentre.set(0, 0, 0), force = chainForce.set(0, 0, 0)
          for (const link of chain) {
            const data = link.sag!, bind = link.bind
            const parent = chain.find(p => p.bind.bone === bind.bone.parent)
            if (parent) {
              data.frame.copy(parent.sag!.frame).multiply(bind.local)
              data.rotation.copy(parent.sag!.rotation).multiply(bind.localRotation)
            } else { data.frame.copy(anchor); data.rotation.copy(anchorQ) }
            if (link === st) data.q.copy(restQ)
            else data.q.identity().slerp(bind.straightenRotation, link.straighten)
            data.head.setFromMatrixPosition(data.frame)
            data.centre.copy(bind.centroid).applyQuaternion(data.q).applyMatrix4(data.frame)
            u.copy(data.centre).sub(data.head).normalize()
            data.force.copy(gravity).multiplyScalar(link.params.gravity_scale ?? 1)
              .sub(temp.copy(bind.gravityRest).applyQuaternion(data.q).applyQuaternion(data.rotation)).multiplyScalar(link.params.gravity)
            const axial = data.force.dot(u)
            if (axial < 0) data.force.addScaledVector(u, -axial)
            centre.addScaledVector(data.centre, bind.mass); force.addScaledVector(data.force, bind.mass); mass += bind.mass
            rotationMatrix.makeRotationFromQuaternion(data.q)
            data.frame.multiply(rotationMatrix); data.rotation.multiply(data.q)
          }
          originalLever.copy(centre).divideScalar(mass).sub(head.setFromMatrixPosition(anchor))
          const staticT = clamp(st.paramsBlend / 1.5, 0, 1)
          const staticBlend = staticT * staticT * (3 - 2 * staticT)
          const frequency = st.staticFrequencyFrom + (st.staticFrequencyTo - st.staticFrequencyFrom) * staticBlend
          const omegaSquared = (2 * Math.PI * frequency) ** 2
          equilibrium.copy(force).divideScalar(mass).multiplyScalar(omegaSquared >= 1e-12 ? 1 / omegaSquared : 0)
          const total = Math.min(originalLever.angleTo(temp.copy(originalLever).add(equilibrium)),
            (st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180)
          let sum = 0
          // Torques are evaluated on the unsagged configuration (small-angle
          // approximation); this keeps total droop independent of link count
          // and puts the largest bend at the root.
          for (let j = 0; j < chain.length; j++) {
            const data = chain[j].sag!
            data.torque.set(0, 0, 0)
            for (let i = j; i < chain.length; i++) {
              const distal = chain[i]
              data.torque.addScaledVector(temp.copy(distal.sag!.centre).sub(data.head).cross(distal.sag!.force), distal.bind.mass)
            }
            const span = j + 1 < chain.length ? data.head.distanceTo(chain[j + 1].sag!.head) : 2 * data.centre.distanceTo(data.head)
            data.weight = data.torque.length() * span; sum += data.weight
          }
          for (const link of chain) {
            const data = link.sag!
            data.q.identity()
            if (sum > 1e-12) data.q.setFromAxisAngle(data.torque.normalize(), total * data.weight / sum)
          }
        }
        restVector.copy(b.centroid).applyQuaternion(restQ)
        target.copy(restVector).applyMatrix4(anchor)
        head.setFromMatrixPosition(anchor)
        // Static gravity acts against the baked bind gravity, before dynamics.
        u.copy(target).sub(head).normalize()
        lateral.set(0, 0, 0)
        if (st.roots.length >= 2) {
          lateral.copy(b.pairedLateral).applyQuaternion(anchorQ)
          lateral.addScaledVector(u, -lateral.dot(u)).normalize()
        }
        deltaG.copy(gravity).multiplyScalar(st.params.gravity_scale ?? 1)
          .sub(temp.copy(b.gravityRest).applyQuaternion(restQ).applyQuaternion(anchorQ)).multiplyScalar(st.params.gravity)
        const bindProjection = b.gravityProjection
        const projection = gravity.dot(u) / 9.81
        const inward = clamp(-projection - Math.max(0, -bindProjection), 0, 1)
        const outward = clamp(projection - Math.max(0, bindProjection), 0, 1)
        const axial = deltaG.dot(u)
        if (axial < 0) deltaG.addScaledVector(u, -axial)
        // When crossing zero, blend the bounded static result rather than
        // dividing by an interpolated frequency that approaches zero.
        const staticT = clamp(st.paramsBlend / 1.5, 0, 1)
        const staticBlend = staticT * staticT * (3 - 2 * staticT)
        st.staticFrequency = st.staticFrequencyFrom + (st.staticFrequencyTo - st.staticFrequencyFrom) * staticBlend
        st.staticWeight = st.staticWeightFrom + (st.staticWeightTo - st.staticWeightFrom) * staticBlend
        const omegaSquared = (2 * Math.PI * st.staticFrequency) ** 2
        equilibrium.copy(deltaG).multiplyScalar(omegaSquared >= 1e-12 ? 1 / omegaSquared : 0)
        originalLever.copy(target).sub(head)
        const restLength = originalLever.length()
        staticVector.copy(originalLever).add(equilibrium)
        // Static angle and length have their own limits, independent of swing.
        const sagLimit = (st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180
        if (st.chain && st.chain.length >= 2) dynamicQ.copy(st.sag!.q)
        else {
          dynamicQ.setFromUnitVectors(u, temp.copy(staticVector).normalize())
          const sagAngle = dynamicQ.angleTo(identityQ)
          if (sagAngle > sagLimit) dynamicQ.slerp(identityQ, 1 - sagLimit / sagAngle)
        }
        dynamicQ.slerp(identityQ, 1 - st.staticWeight)
        const staticLength = Math.max(1e-12, restLength * (1 - (st.params.flatten ?? 0) * (1 - (st.params.flatten_floor ?? st.params.squash[0])) * inward
          + (st.params.stretch ?? 0) * (st.params.squash[1] - 1) * outward))
        // Scale only the bounded force displacement along bind body up.
        staticVector.copy(u).applyQuaternion(dynamicQ).multiplyScalar(restLength).sub(originalLever)
        bodyVertical.copy(b.gravityRest).multiplyScalar(-1 / 9.81).applyQuaternion(anchorQ).normalize()
        staticVector.addScaledVector(bodyVertical, ((st.params.head_sag ?? 1) - 1) * staticVector.dot(bodyVertical))
        staticVector.add(originalLever)
        // Direct paired outward target in radians, independent of force/frequency.
        const spillAngle = (st.params.spill ?? 0) * (st.params.spill_max_deg ?? st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180 * inward
        if (lateral.lengthSq() > 1e-12) {
          temp.copy(u).cross(lateral).normalize()
          staticVector.applyAxisAngle(temp, spillAngle)
        }
        staticVector.multiplyScalar(restLength > 1e-12 ? staticLength / restLength : 1)
        target.copy(head).add(staticVector)
        const extremeAnchor = dt > 0 && st.anchorRotation !== null
          && st.anchorRotation.angleTo(anchorQ) / dt > 2 * Math.PI
        if (far || !st.p || !st.target || (!options.frozen && dt > 0.25)) {
          (st.p ??= new three.Vector3()).copy(target); st.v.set(0, 0, 0)
        } else if (options.frozen) {
          st.p.add(temp.copy(target).sub(st.target))
        } else if (dt > 0) {
          vTarget.copy(target).sub(st.target).divideScalar(dt)
          const steps = Math.ceil(dt / (1 / 240))
          const h = dt / steps
          for (let i = 0; i < steps; i++) {
            t.copy(st.target).lerp(target, i / steps)
            previousDeviation.copy(st.p).sub(t)
            const result = stepSecondaryParticle(st.p, st.v, t, vTarget, st.params, h, integration)
            if (extremeAnchor) {
              // Cap each deviation increment and its total displacement during
              // extreme anchor turns. Carry the bounded target velocity on hit
              // so stored momentum cannot inject another burst on the next step.
              const budget = staticVector.length() * Math.sin(Math.min(Math.PI / 2, motionLimit))
              nextDeviation.copy(result.p).sub(t).addScaledVector(vTarget, -h)
              temp.copy(nextDeviation).sub(previousDeviation).clampLength(0, budget * Math.min(1, h * 120))
              nextDeviation.copy(previousDeviation).add(temp).clampLength(0, budget)
              temp.copy(t).addScaledVector(vTarget, h).add(nextDeviation)
              if (temp.distanceToSquared(result.p) > 1e-20) result.v.copy(vTarget)
              result.p.copy(temp)
            }
            if (!Number.isFinite(result.p.lengthSq()) || !Number.isFinite(result.v.lengthSq())) {
              result.p.copy(t).addScaledVector(vTarget, h); result.v.set(0, 0, 0)
            }
            st.p.copy(result.p); st.v.copy(result.v)
          }
        }
        (st.anchorRotation ??= new three.Quaternion()).copy(anchorQ);
        (st.target ??= new three.Vector3()).copy(target)
        base.copy(target).sub(head)
        // Filter only p-T' in the current rest lever frame. Bind body up
        // follows the anchor, not the rest/sag rotation. Vertical levers use
        // projected bind body front instead of the degenerate up projection.
        u.copy(base).normalize()
        bodyVertical.copy(b.gravityRest).multiplyScalar(-1 / 9.81).applyQuaternion(anchorQ)
        bodyVertical.addScaledVector(u, -bodyVertical.dot(u))
        if (bodyVertical.lengthSq() < 1e-10) {
          bodyVertical.copy(b.bodyFront).applyQuaternion(anchorQ)
          bodyVertical.addScaledVector(u, -bodyVertical.dot(u))
        }
        bodyVertical.normalize()
        dynamicDelta.copy(st.p!).sub(target)
        const gains = st.params.axis_gain ?? DEFAULT_AXIS_GAIN
        const longitudinal = dynamicDelta.dot(u)
        const vertical = dynamicDelta.dot(bodyVertical)
        dynamicDelta.multiplyScalar(gains[0])
          .addScaledVector(bodyVertical, (gains[1] - gains[0]) * vertical)
          .addScaledVector(u, (gains[2] - gains[0]) * longitudinal)
        rendered.copy(base).add(dynamicDelta)
        // Compression cannot flip the lever and manufacture axial swing.
        rendered.addScaledVector(u, Math.max(0, 1e-12 - base.length() - gains[2] * longitudinal))
        // Saturate the swing angle around the static target, not around bind T.
        dynamicQ.setFromUnitVectors(temp.copy(base).normalize(), u.copy(rendered).normalize())
        const angle = dynamicQ.angleTo(identityQ)
        const limited = softMotionAngle(angle, motionLimit)
        if (angle > 0) dynamicQ.slerp(identityQ, 1 - limited / angle)
        // Only longitudinal dynamics change length; transverse displacement
        // supplies direction. Static length/flatten remain untouched.
        const renderedLength = Math.max(1e-12, base.length() + gains[2] * longitudinal)
        rendered.copy(base).applyQuaternion(dynamicQ).multiplyScalar(renderedLength / base.length())
        const gain = far ? 0 : st.params.gain
        rendered.sub(base).multiplyScalar(gain).add(base)
        rendered.normalize().multiplyScalar(Math.max(1e-12, base.length() + gain * gains[2] * longitudinal))
        // Split bounded transverse static and dynamic offsets; axial length is unchanged.
        const translate = st.params.translate ?? 0
        headShift.copy(base).sub(originalLever)
        temp.copy(originalLever).normalize()
        headShift.addScaledVector(temp, -headShift.dot(temp))
        headShift.clampLength(0, restLength * Math.max(0, Math.sin(sagLimit)))
        shiftPart.copy(rendered).sub(base)
        // Use the same rest lever projection for both components so full
        // translation leaves no residual rotation when neither cap is active.
        temp.copy(originalLever).normalize()
        shiftPart.addScaledVector(temp, -shiftPart.dot(temp))
        shiftPart.clampLength(0, base.length() * Math.max(0, Math.sin(motionLimit)))
        headShift.add(shiftPart).multiplyScalar(translate)
        const totalLength = rendered.length()
        rendered.sub(headShift).normalize().multiplyScalar(totalLength)
        localRendered.copy(rendered).add(head).applyMatrix4(inverseAnchor.copy(anchor).invert())
        dynamicQ.setFromUnitVectors(temp.copy(restVector).normalize(), u.copy(localRendered).normalize())
        // head_sag acts after force/length limits. Preserve that static target
        // even when it is shorter than squash_min; only dynamics hit the cap.
        const staticRatio = temp.copy(target).applyMatrix4(inverseAnchor).length() / restVector.length()
        const s = clamp(localRendered.length() / restVector.length(), Math.min(st.params.squash[0], staticRatio), st.params.squash[1])
        const spread = st.params.spread ?? 0.5
        const perpendicular = s < 1 ? Math.min(SPREAD_CAP, 1 + spread * (1 / Math.sqrt(s) - 1)) : 1 / Math.sqrt(s)
        u.copy(b.scaleAxis)
        scale.identity()
        const e = scale.elements
        // Gram-Schmidt gives the orthonormal frame (u, L, u cross L).
        // Its spectral scale has no shear; the third paired axis stays 1.
        const pairedWidth = Math.min(SPREAD_CAP, 1 + spread * (1 / s - 1))
        // Paired flattening presses along the BODY FRONT (where gravity acts
        // when lying) and widens along the body lateral axis, not along the
        // oblique lever: an outward-pointing lever would otherwise tilt the
        // width axis into the height. Both axes are expressed in the frame the
        // scale acts in (bind bone frame rotated by dynamic·rest), and the
        // frame (front, L, front×L) is orthonormal, so the scale has no shear.
        frameQ.copy(dynamicQ).multiply(restQ).invert()
        frontLocal.copy(b.bodyFront).applyQuaternion(frameQ).normalize()
        localLateral.copy(lateral).transformDirection(inverseAnchor.copy(anchor).invert()).applyQuaternion(frameQ)
        localLateral.addScaledVector(frontLocal, -localLateral.dot(frontLocal))
        if (localLateral.lengthSq() > 1e-12) localLateral.normalize(); else localLateral.set(0, 0, 0)
        const pairedFlatten = s < 1 && st.roots.length >= 2 && localLateral.lengthSq() > 1e-12
        for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
          e[col * 4 + row] = pairedFlatten
            ? (row === col ? 1 : 0) + (s - 1) * frontLocal.getComponent(row) * frontLocal.getComponent(col)
              + (pairedWidth - 1) * localLateral.getComponent(row) * localLateral.getComponent(col)
            : (row === col ? perpendicular : 0) + (s - perpendicular) * u.getComponent(row) * u.getComponent(col)
        }
        // State extent is applied after static/dynamic scaling, in the same
        // immutable lever frame; it does not alter volume compensation.
        const stateLength = st.params.length ?? 1, stateGirth = st.params.girth ?? 1
        for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
          e[col * 4 + row] = stateGirth * e[col * 4 + row]
            + (stateLength - stateGirth) * s * u.getComponent(row) * u.getComponent(col)
        }
        shiftPart.copy(head).add(headShift).applyMatrix4(inverseAnchor)
        translationMatrix.makeTranslation(shiftPart.x, shiftPart.y, shiftPart.z)
        if (colliding && st.contacts.length) {
          keepTipOutside(st, dynamicQ, restQ,
            Math.max(st.params.max_deg, st.params.sag_max_deg ?? 0) * st.motionShare * Math.PI / 180)
        }
        b.bone.matrix.copy(blended ? localBase.copy(b.bone.parent!.matrixWorld).invert().multiply(anchor) : b.local)
          .multiply(translationMatrix)
          .multiply(rotationMatrix.makeRotationFromQuaternion(dynamicQ.multiply(restQ)))
          .multiply(scale)
        b.rotation.copy(anchorQ).multiply(dynamicQ)
        driven.set(b.bone, st)
        b.bone.matrixWorldNeedsUpdate = true
        b.pureWorld.copy(anchor).multiply(translationMatrix).multiply(rotationMatrix)
        b.bone.matrixWorld.copy(b.pureWorld).multiply(scale)
        // Keep the local matrix consistent with that world matrix, so a later
        // updateMatrixWorld (parent.matrixWorld x matrix) does not re-apply the
        // parent's scale: parentFull = anchorFull x local^-1, hence
        // matrix = local x anchorFull^-1 x world.
        if (drivenAncestor) b.bone.matrix.copy(b.local).multiply(inverseAnchor.copy(anchorFull).invert()).multiply(b.bone.matrixWorld)
      }
      // A rigid tail link takes its parent's frame without the parent's own
      // extension scale, at the parent's fully deformed position — the same
      // rule as a driven child, minus every motion of its own.
      for (const b of rigids) {
        const parent = b.bone.parent!
        const owner = driven.get(parent as Bone)
        anchorFull.copy(parent.matrixWorld).multiply(b.local)
        anchor.copy(owner ? owner.bind.pureWorld : parent.matrixWorld).multiply(b.local)
        anchor.setPosition(temp.setFromMatrixPosition(anchorFull))
        b.bone.matrixWorld.copy(anchor)
        b.pureWorld.copy(anchor)
        // parent.matrixWorld x matrix must reproduce that world on the publish below.
        b.bone.matrix.copy(inverseAnchor.copy(parent.matrixWorld).invert()).multiply(anchor)
        b.bone.matrixWorldNeedsUpdate = true
      }
      // Publish all non-driven descendants once after the chain is complete.
      root.updateMatrixWorld(true)
    },
    dispose() {
      for (const st of particles) restore(st.bind)
      for (const b of rigids) restore(b)
      particles = []; rigids = []; binds.clear(); sums.clear(); byName.clear(); boneInverses.clear(); collision = null; disposed = true
    },
  }
}
