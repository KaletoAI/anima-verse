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
  gravity: number
  gain: number
  max_deg: number
  squash: [number, number]
  rest_deg: number
  rest_max_deg: number
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

/** Exact propagation of the spec equation for a linearly moving T and
 * constant gravity during one <=1/240 s substep. In relative coordinates,
 * x=p-T-gravityDelta*gravity/omega², w=v-v_T, the equation is homogeneous:
 * x'' + 2*zeta*omega*x' + omega²*x = 0. Handle all damping regimes explicitly
 * so large frequencies/damping do not destabilize an explicit integrator.
 * Inputs are never mutated.
 */
export function stepSecondaryParticle(
  p: Vector3, v: Vector3, target: Vector3, targetVelocity: Vector3,
  gravityDelta: Vector3, params: MotionGroup, h: number,
  output?: { p: Vector3; v: Vector3; equilibrium: Vector3; x: Vector3; w: Vector3 },
): { p: Vector3; v: Vector3 } {
  const omega = 2 * Math.PI * params.freq_hz
  const equilibrium = (output?.equilibrium ?? gravityDelta.clone()).copy(gravityDelta).multiplyScalar(params.gravity / (omega * omega))
  const x = (output?.x ?? p.clone()).copy(p).sub(target).sub(equilibrium)
  const w = (output?.w ?? v.clone()).copy(v).sub(targetVelocity)
  const alpha = params.zeta * omega
  let xx: number, xw: number, wx: number, ww: number
  if (params.zeta > 1) {
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
  result.p.copy(target).addScaledVector(targetVelocity, h).add(equilibrium)
    .addScaledVector(x, xx).addScaledVector(w, xw)
  result.v.copy(targetVelocity).addScaledVector(x, wx).addScaledVector(w, ww)
  return result
}

interface Bind {
  bone: Bone
  local: Matrix4
  centroid: Vector3
  gravityRest: Vector3
  lateral: Vector3
  auto: boolean
  depth: number
  rotation: Quaternion
  localRotation: Quaternion
}
interface Particle {
  bind: Bind
  params: MotionGroup
  p: Vector3 | null
  v: Vector3
  target: Vector3 | null
  rest: number
  restFrom: number
  restTo: number
  blend: number
}
const centroidCache = new WeakMap<Object3D, Vector3[]>()
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x))
const restAngle = (g: MotionGroup) => clamp(g.rest_deg, -g.rest_max_deg, g.rest_max_deg) * Math.PI / 180

/** Build once while the skeleton is in bind pose, after its up-axis correction.
 * Centroids use ALL positive skin weights, aggregated over every skinned mesh.
 * bindMatrix maps each raw vertex into skeleton bind space; boneInverse maps
 * it into the bone's anchor frame. Imported joint axes are never geometry.
 * The lateral axis is model +X in the bind pose, expressed anchor-locally;
 * positive rest_deg follows the right-hand rule around that axis.
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
  const lateralWorld = new three.Vector3(1, 0, 0)
    .applyQuaternion(root.getWorldQuaternion(new three.Quaternion()))
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
        binds.set(bone, { bone, local: bone.matrix.clone(), centroid: new three.Vector3(),
          gravityRest: gravity.clone().applyQuaternion(q),
          lateral: lateralWorld.clone().applyQuaternion(q), auto: bone.matrixAutoUpdate, depth, rotation: new three.Quaternion(), localRotation: bone.quaternion.clone() })
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
      for (const bind of chain as Bind[]) {
        if (selected.has(bind.bone)) continue
        selected.add(bind.bone)
        const to = restAngle(params)
        const old = previous.get(bind.bone)
        const particle: Particle = old ?? { bind, params, p: null, v: new three.Vector3(),
          target: null, rest: to, restFrom: to, restTo: to, blend: 1.5 }
        if (particle.restTo !== to) {
          particle.restFrom = particle.rest
          particle.restTo = to
          particle.blend = 0
        }
        particle.params = { ...params, bones: [...params.bones], squash: [...params.squash] }
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
  const anchorQ = new three.Quaternion(), restQ = new three.Quaternion(), dynamicQ = new three.Quaternion(), identityQ = new three.Quaternion()
  const restVector = new three.Vector3(), target = new three.Vector3(), head = new three.Vector3(), vTarget = new three.Vector3(), deltaG = new three.Vector3(), t = new three.Vector3(), base = new three.Vector3(), rendered = new three.Vector3(), localRendered = new three.Vector3(), u = new three.Vector3(), temp = new three.Vector3()
  const integration = { p: new three.Vector3(), v: new three.Vector3(), equilibrium: new three.Vector3(), x: new three.Vector3(), w: new three.Vector3() }
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
        // Rest blending is real time, including far LOD. Freeze stops dynamics.
        st.blend = Math.min(1.5, st.blend + dt)
        const fraction = st.blend / 1.5
        const limit = st.params.rest_max_deg * Math.PI / 180
        st.rest = clamp(st.restFrom + (st.restTo - st.restFrom) * fraction * fraction * (3 - 2 * fraction), -limit, limit)
        restQ.setFromAxisAngle(b.lateral, st.rest)
        restVector.copy(b.centroid).applyQuaternion(restQ)
        target.copy(restVector).applyMatrix4(anchor)
        head.setFromMatrixPosition(anchor)
        if (far || !st.p || !st.target || (!options.frozen && dt > 0.25)) {
          (st.p ??= new three.Vector3()).copy(target); st.v.set(0, 0, 0)
        } else if (options.frozen) {
          // Preserve displacement while the owner moves the anchor or rest pose.
          st.p.add(temp.copy(target).sub(st.target))
        } else if (dt > 0) {
          vTarget.copy(target).sub(st.target).divideScalar(dt)
          deltaG.copy(gravity).sub(temp.copy(b.gravityRest).applyQuaternion(anchorQ))
          const steps = Math.ceil(dt / (1 / 240))
          const h = dt / steps
          for (let i = 0; i < steps; i++) {
            t.copy(st.target).lerp(target, i / steps)
            const result = stepSecondaryParticle(st.p, st.v, t, vTarget, deltaG, st.params, h, integration)
            st.p.copy(result.p); st.v.copy(result.v)
          }
        }
        (st.target ??= new three.Vector3()).copy(target)
        base.copy(target).sub(head)
        rendered.copy(base).addScaledVector(temp.copy(st.p!).sub(target), far ? 0 : st.params.gain)
        localRendered.copy(rendered).add(head).applyMatrix4(inverseAnchor.copy(anchor).invert())
        dynamicQ.identity()
        if (!far && st.params.gain !== 0) dynamicQ.setFromUnitVectors(
            temp.copy(restVector).normalize(), u.copy(localRendered).normalize())
        const maxAngle = st.params.max_deg * Math.PI / 180
        const angle = dynamicQ.angleTo(identityQ)
        if (angle > maxAngle) dynamicQ.slerp(identityQ, 1 - maxAngle / angle)
        // Gain zero must be exact identity scale, even if squash excludes 1.
        const s = far || st.params.gain === 0 ? 1
          : clamp(localRendered.length() / restVector.length(), st.params.squash[0], st.params.squash[1])
        const perpendicular = 1 / Math.sqrt(s)
        u.copy(b.centroid).normalize()
        // B diag(s,1/sqrt(s),1/sqrt(s)) B^-1 = c I + (s-c) u u^T.
        // Keep the full matrix (no TRS decomposition): arbitrary imported axes
        // require off-diagonal terms. Skinning and child FK read this matrix.
        scale.identity()
        const e = scale.elements
        const axis = u
        for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
          e[col * 4 + row] = (row === col ? perpendicular : 0) + (s - perpendicular) * axis.getComponent(row) * axis.getComponent(col)
        }
        b.bone.matrix.copy(b.local)
          .multiply(rotationMatrix.makeRotationFromQuaternion(dynamicQ.multiply(restQ)))
          .multiply(scale)
        b.rotation.copy(anchorQ).multiply(dynamicQ)
        driven.set(b.bone, st)
        b.bone.matrixWorldNeedsUpdate = true
        b.bone.matrixWorld.copy(anchor).multiply(rotationMatrix).multiply(scale)
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
