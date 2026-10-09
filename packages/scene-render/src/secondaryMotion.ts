/** Secondary motion in metres and real seconds; three's world is Y-up.
 * Gravity is (0,-9.81,0). No runtime three import: consumers inject it.
 */
import type { Bone, Matrix4, Quaternion, Object3D, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from './clipRetarget'
type Three = typeof import('three')

export interface MotionGroup {
  bones: string[]
  freq_hz: number
  zeta: number
  spill: number
  translate: number
  flatten: number
  gravity_scale: number
  sag_max_deg: number
  gravity: number
  axis_gain: [number, number, number]
  gain: number
  max_deg: number
  squash: [number, number]
  rest_deg: number
  rest_max_deg: number
}
/** Package metadata profiles are multipliers; runtime groups are already resolved. */
export type MotionAttributeProfiles = Record<string, Record<string, Partial<Pick<MotionGroup,
  'freq_hz' | 'zeta' | 'gravity' | 'gain' | 'max_deg' | 'sag_max_deg' | 'flatten' | 'spill' | 'translate'>>>>
export interface ExtensionRigDeclaration extends Omit<MotionGroup, 'bones' | 'gravity_scale' | 'rest_deg'> {
  id: string
  op: string
  chains: { bone: string; parent: string }[][]
  params: Record<string, unknown>
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
  reset(): void
  dispose(): void
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
  centroidWorld: Vector3
  gravityRest: Vector3
  bodyFront: Vector3
  head: Vector3
  parentHead: Vector3
  worldRotation: Quaternion
  lateral: Vector3
  auto: boolean
  depth: number
  rotation: Quaternion
  localRotation: Quaternion
}
interface Particle {
  bind: Bind
  roots: Bind[]
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
}
const DEFAULT_AXIS_GAIN: [number, number, number] = [1, 1, 1]
const BLENDED_FIELDS = ['gravity', 'freq_hz', 'zeta', 'gain', 'flatten', 'spill', 'translate'] as const
/** Smooth numeric state changes over the same 1.5 seconds as the rest angle. */
export function blendMotionParams(from: MotionGroup, to: MotionGroup, elapsed: number, output?: MotionGroup): MotionGroup {
  const t = Math.max(0, Math.min(1, elapsed / 1.5))
  const weight = t * t * (3 - 2 * t)
  const result = output ?? { ...to }
  for (const field of BLENDED_FIELDS) result[field] = (from[field] ?? 0) + ((to[field] ?? 0) - (from[field] ?? 0)) * weight
  return result
}
const centroidCache = new WeakMap<Object3D, Vector3[]>()
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x))
/** Linear below half the limit, then C1 tanh saturation: monotonic and bounded. */
export const softMotionAngle = (angle: number, limit: number) => {
  if (limit <= 0) return 0
  const knee = limit / 2
  return angle <= knee ? angle : knee + knee * Math.tanh((angle - knee) / knee)
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
    return {
      configure(next) {
        if (stopped) return
        if (delegate) { delegate.configure(next); return }
        const requested = new Set(Object.values(next?.groups ?? {}).flatMap(g => g.bones.map(normBoneName)))
        let found = false
        if (requested.size) root.traverse(o => { if ((o as Bone).isBone && requested.has(normBoneName(o.name))) found = true })
        if (found) delegate = createSecondaryMotion(three, root, next, template)
      },
      update(dt, options) { delegate?.update(dt, options) },
      reset() { delegate?.reset() },
      dispose() { delegate?.dispose(); stopped = true },
    }
  }
  root.updateWorldMatrix(true, false)
  root.updateMatrixWorld(true)
  const gravity = new three.Vector3(0, -9.81, 0)
  const binds = new Map<Bone, Bind>()
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
    mesh.skeleton.bones.forEach(bone => {
      if (!binds.has(bone)) {
        const q = bone.getWorldQuaternion(new three.Quaternion()).invert()
        let depth = 0
        for (let parent = bone.parent; parent; parent = parent.parent) depth++
        binds.set(bone, { bone, local: bone.matrix.clone(), centroid: new three.Vector3(), centroidWorld: new three.Vector3(),
          gravityRest: gravity.clone().applyQuaternion(q), bodyFront: new three.Vector3(),
          head: bone.getWorldPosition(new three.Vector3()), parentHead: bone.parent!.getWorldPosition(new three.Vector3()), worldRotation: q.clone().invert(),
          lateral: new three.Vector3(), auto: bone.matrixAutoUpdate, depth, rotation: new three.Quaternion(), localRotation: bone.quaternion.clone() })
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
    if (acc.weight > 0) binds.get(bone)!.centroid.copy(acc.sum).divideScalar(acc.weight)
  }
  if (cached) [...binds.values()].forEach((b, i) => b.centroid.copy(cached[i]))
  else if (template) centroidCache.set(template, [...binds.values()].map(b => b.centroid.clone()))
  for (const b of binds.values()) b.centroidWorld.copy(b.centroid).applyMatrix4(b.bone.matrixWorld)
  const byName = new Map([...binds.values()].map(b => [normBoneName(b.bone.name), b]))
  let particles: Particle[] = []
  let far = false
  let disposed = false
  const restore = (b: Bind) => {
    b.bone.matrix.copy(b.local)
    b.bone.matrixAutoUpdate = b.auto
    b.bone.matrixWorldNeedsUpdate = true
  }
  const configure = (next?: SecondaryMotionPayload) => {
    if (disposed) return
    const previous = new Map(particles.map(p => [p.bind.bone, p]))
    const selected = new Set<Bone>()
    const nextParticles: Particle[] = []
    for (const params of Object.values(next?.groups ?? {})) {
      const chain = params.bones.map(name => byName.get(normBoneName(name)))
      // Absent/partial groups and vertices without influence are ordinary skips.
      if (chain.some(b => !b || b.centroid.lengthSq() < 1e-12)) continue
      const members = new Set((chain as Bind[]).map(b => b.bone))
      const roots = (chain as Bind[]).filter(b => !members.has(b.bone.parent as Bone))
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
      for (const b of chain as Bind[]) {
        b.bodyFront.copy(front)
        if (b.bodyFront.lengthSq() < 1e-10) b.bodyFront.set(0, 0, 1)
        b.bodyFront.applyQuaternion(b.worldRotation.clone().invert())
        b.lateral.set(0, 0, 0)
        if (!roots.includes(b)) continue
        const child = (chain as Bind[]).find(c => c.bone.parent === b.bone)
        const lever = child ? child.head.clone().sub(b.head) : b.centroidWorld.clone().sub(b.head)
        lever.normalize()
        const toward = front.clone().addScaledVector(lever, -front.dot(lever))
        if (toward.lengthSq() < 1e-10) toward.copy(bindUp).addScaledVector(lever, -bindUp.dot(lever))
        b.lateral.crossVectors(lever, toward).normalize().applyQuaternion(b.worldRotation.clone().invert())
      }
      for (const bind of chain as Bind[]) {
        if (selected.has(bind.bone)) continue
        selected.add(bind.bone)
        const to = restAngle(params)
        const old = previous.get(bind.bone)
        const particle: Particle = old ?? { bind, roots, params, paramsFrom: params, paramsTo: params, paramsBlend: 1.5, p: null, v: new three.Vector3(),
          target: null, rest: to, restFrom: to, restTo: to, blend: 1.5,
          staticFrequency: params.freq_hz, staticFrequencyFrom: params.freq_hz, staticFrequencyTo: params.freq_hz,
          staticWeight: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          staticWeightFrom: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1,
          staticWeightTo: (2 * Math.PI * params.freq_hz) ** 2 < 1e-12 ? 0 : 1 }
        if (particle.restTo !== to) {
          particle.restFrom = particle.rest
          particle.restTo = to
          particle.blend = 0
        }
        particle.roots = roots
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
    for (const old of particles) if (!selected.has(old.bind.bone)) {
      restore(old.bind)
      old.bind.bone.updateWorldMatrix(false, true)
    }
    particles = nextParticles.sort((a, b) => a.bind.depth - b.bind.depth)
  }
  const reset = () => {
    for (const st of particles) { st.p = null; st.target = null; st.v.set(0, 0, 0) }
  }
  const anchor = new three.Matrix4(), inverseAnchor = new three.Matrix4(), scale = new three.Matrix4(), rotationMatrix = new three.Matrix4()
  const anchorQ = new three.Quaternion(), restQ = new three.Quaternion(), dynamicQ = new three.Quaternion(), identityQ = new three.Quaternion(), inverseRestQ = new three.Quaternion()
  const restVector = new three.Vector3(), target = new three.Vector3(), head = new three.Vector3(), vTarget = new three.Vector3(), deltaG = new three.Vector3(), t = new three.Vector3(), base = new three.Vector3(), rendered = new three.Vector3(), localRendered = new three.Vector3(), u = new three.Vector3(), temp = new three.Vector3()
  const bodyVertical = new three.Vector3(), dynamicDelta = new three.Vector3()
  const headShift = new three.Vector3(), shiftPart = new three.Vector3(), originalLever = new three.Vector3()
  const translationMatrix = new three.Matrix4()
  const meanHead = new three.Vector3(), lateral = new three.Vector3(), localLateral = new three.Vector3(), staticVector = new three.Vector3(), equilibrium = new three.Vector3(), rootFrame = new three.Matrix4()
  const integration = { p: new three.Vector3(), v: new three.Vector3(), x: new three.Vector3(), w: new three.Vector3() }
  const driven = new Map<Bone, Particle>()
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
    update(realDelta, options = {}) {
      if (disposed || !particles.length) return
      const dt = Number.isFinite(realDelta) ? Math.max(0, realDelta) : 0
      if (!!options.far !== far) { far = !!options.far; reset() }
      root.updateWorldMatrix(true, false)
      root.updateMatrixWorld(true)
      driven.clear()
      for (const st of particles) {
        const b = st.bind
        anchor.copy(b.local)
        // Reuse the current driven ancestor world matrix without traversing its subtree.
        for (let n = b.bone.parent; n; n = n.parent) {
          if (driven.has(n as Bone)) { anchor.premultiply(n.matrixWorld); break }
          anchor.premultiply(n.matrix)
        }
        pureParent(b.bone.parent).multiply(b.localRotation)
        st.paramsBlend = Math.min(1.5, st.paramsBlend + dt)
        st.params = blendMotionParams(st.paramsFrom, st.paramsTo, st.paramsBlend, st.params)
        // Rest blending is real time, including far LOD. Freeze stops dynamics.
        st.blend = Math.min(1.5, st.blend + dt)
        const fraction = st.blend / 1.5
        const limit = st.params.rest_max_deg * Math.PI / 180
        st.rest = clamp(st.restFrom + (st.restTo - st.restFrom) * fraction * fraction * (3 - 2 * fraction), -limit, limit)
        if (st.roots.includes(b) && b.lateral.lengthSq() > 1e-12) restQ.setFromAxisAngle(b.lateral, st.rest)
        else restQ.identity()
        restVector.copy(b.centroid).applyQuaternion(restQ)
        target.copy(restVector).applyMatrix4(anchor)
        head.setFromMatrixPosition(anchor)
        // Static gravity acts against the baked bind gravity, before dynamics.
        u.copy(target).sub(head).normalize()
        lateral.set(0, 0, 0)
        if (st.roots.length >= 2) {
          meanHead.set(0, 0, 0)
          for (const link of st.roots) {
            rootFrame.copy(link.local)
            for (let n = link.bone.parent; n; n = n.parent) {
              if (driven.has(n as Bone)) { rootFrame.premultiply(n.matrixWorld); break }
              rootFrame.premultiply(n.matrix)
            }
            meanHead.add(temp.setFromMatrixPosition(rootFrame))
          }
          meanHead.divideScalar(st.roots.length)
          lateral.copy(head).sub(meanHead)
          lateral.addScaledVector(u, -lateral.dot(u)).normalize()
        }
        deltaG.copy(gravity).multiplyScalar(st.params.gravity_scale ?? 1)
          .sub(temp.copy(b.gravityRest).applyQuaternion(restQ).applyQuaternion(anchorQ)).multiplyScalar(st.params.gravity)
        const inward = clamp(-gravity.dot(u) / 9.81, 0, 1)
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
        dynamicQ.setFromUnitVectors(u, temp.copy(staticVector).normalize())
        const sagLimit = (st.params.sag_max_deg ?? st.params.max_deg) * Math.PI / 180
        const sagAngle = dynamicQ.angleTo(identityQ)
        if (sagAngle > sagLimit) dynamicQ.slerp(identityQ, 1 - sagLimit / sagAngle)
        dynamicQ.slerp(identityQ, 1 - st.staticWeight)
        const staticLength = restLength * clamp(1 - (st.params.flatten ?? 0) * (1 - st.params.squash[0]) * inward, st.params.squash[0], st.params.squash[1])
        staticVector.copy(u).applyQuaternion(dynamicQ)
        // Direct paired outward target in radians, independent of force/frequency.
        const spillAngle = (st.params.spill ?? 0) * sagLimit * inward
        if (lateral.lengthSq() > 1e-12) {
          temp.copy(u).cross(lateral).normalize()
          staticVector.applyAxisAngle(temp, spillAngle)
        }
        dynamicQ.setFromUnitVectors(u, staticVector.normalize())
        const combinedAngle = dynamicQ.angleTo(identityQ)
        if (combinedAngle > sagLimit) dynamicQ.slerp(identityQ, 1 - sagLimit / combinedAngle)
        staticVector.copy(u).applyQuaternion(dynamicQ).multiplyScalar(staticLength)
        target.copy(head).add(staticVector)
        localLateral.copy(lateral).transformDirection(inverseAnchor.copy(anchor).invert())
        // Express L before the rest rotation; scale is applied before that rotation.
        localLateral.applyQuaternion(inverseRestQ.copy(restQ).invert())
        temp.copy(b.centroid).normalize()
        localLateral.addScaledVector(temp, -localLateral.dot(temp)).normalize()
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
            const result = stepSecondaryParticle(st.p, st.v, t, vTarget, st.params, h, integration)
            st.p.copy(result.p); st.v.copy(result.v)
          }
        }
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
        const limited = softMotionAngle(angle, st.params.max_deg * Math.PI / 180)
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
        shiftPart.clampLength(0, base.length() * Math.max(0, Math.sin(st.params.max_deg * Math.PI / 180)))
        headShift.add(shiftPart).multiplyScalar(translate)
        const totalLength = rendered.length()
        rendered.sub(headShift).normalize().multiplyScalar(totalLength)
        localRendered.copy(rendered).add(head).applyMatrix4(inverseAnchor.copy(anchor).invert())
        dynamicQ.setFromUnitVectors(temp.copy(restVector).normalize(), u.copy(localRendered).normalize())
        const s = clamp(localRendered.length() / restVector.length(), st.params.squash[0], st.params.squash[1])
        const perpendicular = 1 / Math.sqrt(s)
        u.copy(b.centroid).normalize()
        scale.identity()
        const e = scale.elements
        // Paired shortening preserves volume only along L; the third axis stays 1.
        // S=I+(s-1)uu^T+(1/s-1)LL^T, otherwise symmetric transverse scaling.
        const pairedFlatten = s < 1 && st.roots.length >= 2 && localLateral.lengthSq() > 1e-12
        for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
          e[col * 4 + row] = pairedFlatten
            ? (row === col ? 1 : 0) + (s - 1) * u.getComponent(row) * u.getComponent(col)
              + (1 / s - 1) * localLateral.getComponent(row) * localLateral.getComponent(col)
            : (row === col ? perpendicular : 0) + (s - perpendicular) * u.getComponent(row) * u.getComponent(col)
        }
        shiftPart.copy(head).add(headShift).applyMatrix4(inverseAnchor)
        translationMatrix.makeTranslation(shiftPart.x, shiftPart.y, shiftPart.z)
        b.bone.matrix.copy(b.local)
          .multiply(translationMatrix)
          .multiply(rotationMatrix.makeRotationFromQuaternion(dynamicQ.multiply(restQ)))
          .multiply(scale)
        b.rotation.copy(anchorQ).multiply(dynamicQ)
        driven.set(b.bone, st)
        b.bone.matrixWorldNeedsUpdate = true
        b.bone.matrixWorld.copy(anchor).multiply(translationMatrix).multiply(rotationMatrix).multiply(scale)
      }
      // Publish all non-driven descendants once after the chain is complete.
      root.updateMatrixWorld(true)
    },
    dispose() {
      for (const st of particles) restore(st.bind)
      particles = []; binds.clear(); sums.clear(); byName.clear(); disposed = true
    },
  }
}
