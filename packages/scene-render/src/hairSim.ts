/**
 * Per-strand hair on a figure (strand-hair spec `docs/superpowers/specs/2026-11-13-strand-hair-design.md`
 * § 6.2.2 / § 6.2.4): the three half of the sim. `hairSimMath.ts` is the pure sim; this file binds it to the hair
 * mesh of ONE figure and runs it.
 *
 * WHAT IT DOES. `createStrandHair(three, root, record)` finds the skinned mesh under `root` that carries the
 * record's per-vertex binding (`_STRAND_CARD` / `_STRAND_U`, three: `_strand_card` / `_strand_u`), binds it
 * (`bindStrands`) and builds the sim. Nothing changes on the mesh until `setEnabled(true)`:
 *  - ON: the mesh gets a geometry CLONE owned by this handle (figures are `SkeletonUtils.clone`s sharing their
 *    template's geometry), its card vertices skinned to the Head alone (index Head, weight (1, 0, 0, 0)) — the
 *    rebuild writes them in head-bind space — and the sim reset to the current targets, so the switch is
 *    invisible at rest. The scalp cap (card 0) keeps its skin.
 *  - OFF: the template's geometry object goes back (its skin attributes were never touched) and the clone is
 *    freed. `dispose()` is OFF; it frees exactly what this handle created (CLAUDE.md, the ownership ledger).
 *
 * THE FRAME. Every matrix is the endpoint rule's bind→world of a joint of the HAIR mesh's skeleton
 * (`collision.ts` `jointNowFrom`: `meshWorld · bindMatrixInverse · boneWorld · boneInverse · bindMatrix`), i.e.
 * what a vertex of the hair primitive skinned 100 % to that joint goes through: the follow matrices of the
 * targets (`strandTargets`) and the head frame of the SDF / box / rebuild. Call `update` after the pose of the
 * frame is final and `updateMatrixWorld` has run (the client: after the mixer, before the secondary motion).
 *
 * COLLIDERS (Ruling H-R7). The record's capsules (`strandCapsules`, the fit body's `HAIR_REGIONS`) WITHOUT the
 * head region: the head SDF covers the head, and the coarser head capsule under the bind rule slid nape rows
 * sideways — measured on Lirien's walk +3.29 pp scalp exposure with it, ≤ +2 pp without (task-7 report).
 * The capsules are bound to the figure's body skeleton by `bindCollision`; their bind-pose ends are taken into
 * the hair primitive's geometry space once (the bind-rule reference, kept as the same objects every frame —
 * `StrandSim` caches its per-row factors on them).
 *
 * THE CLOCK (spec § 6.2.2, Ruling H-R11). The sim steps at a fixed 60 Hz whatever the frame rate: a frame of
 * `realDelta` seconds takes the 1/60 s steps that fit into it plus the remainder the last frame carried over (1–4 at
 * 15–60 fps), the new remainder waits for the next frame. Every step sees the figure AT ITS OWN TIME: the follow
 * matrices and the head frame between the last frame's pose and this one's (`lerpFrame`: slerped, so a turning head
 * keeps its size), the capsule ends linear, the targets rebuilt from those matrices. Holding them at the frame's end
 * pose (before H-R11) gave a 20 fps frame one step with the whole frame's target motion and two with none: the rows
 * took three steps' velocity in one, and a walk threw up to 69 cards out (60 fps: none) and left 140 mm after Stop.
 *  - A frame longer than `STRAND_MAX_STEPS` steps (below 15 fps) takes 4 steps over its LAST 4/60 s; what the head
 *    did before that is carried rigidly (`StrandSim.carry`, the head's motion from the last frame to the first
 *    step's start), and no remainder is kept: the hair keeps its shape on the head, never a swing the sim did not
 *    see.
 *  - A delta > 0.25 s (a stalled tab) or a head jump > 0.5 m (teleport, rebuild) resets the sim to the targets.
 *  - `frozen` holds it still (nothing is written).
 * The rebuild runs once per frame that stepped, after its last step, through the head frame OF that step (the rows
 * and the head of one moment; the remainder never shows as a lag behind the head); a frame without a step leaves
 * the hair where the last one put it, carried by the head.
 *
 * THE ROOT'S MOTION (Ruling H-R10). Before the steps of a frame the simulated rows are carried by the part of the
 * root's (`root`, the figure instance) motion the strands do not feel (`RootInertia`, `STRAND_ROOT_LIMITS`): the
 * game's 10/s turn ease, its snaps and its walk starts at full speed in one frame flung the free rows out
 * horizontally; within the spike's tuning motions everything is felt as before. The last frame's pose the steps
 * start from is carried with them.
 *
 * COST. `costMs` is an EMA of the measured milliseconds of a whole stepping frame's `update` (the pose, every
 * step, the rebuild) — what the figure budget (`pickStrandFigures`) adds up, so a slow client paying 3–4 steps a
 * frame admits fewer figures by itself. Before the first run it is an estimate from the card count
 * (`STRAND_MS_PER_CARD`, one step a frame).
 *
 * `three` is injected, never imported.
 */
import type { BufferAttribute, BufferGeometry, Object3D, SkinnedMesh } from 'three'
import { normBoneName } from './clipRetarget'
import { bindCollision, jointNowFrom } from './collision'
import type { CollisionBinding, Mat4, Vec3 } from './collision'
import { capsuleInFrame } from './garmentCollision'
import type { CollideCapsule } from './garmentCollision'
import { bindStrands, invertAffine, lerpFrame, RootInertia, StrandMismatch, strandCapsules, strandParams, StrandSim,
  strandTargets } from './hairSimMath'
import type { HairStrandRecord, StrandParams } from './hairSimMath'

type Three = typeof import('three')

/** The fixed step (s). */
export const STRAND_DT = 1 / 60
/** Steps one frame may take at most (a longer frame: its last 4/60 s; module docstring). */
export const STRAND_MAX_STEPS = 4
/** A frame delta above this (s) resets the sim. */
export const STRAND_RESET_DELTA_S = 0.25
/** A head move above this in one frame (m) resets the sim. */
export const STRAND_RESET_JUMP_M = 0.5
/** The cost estimate per card before a figure has run (ms per frame): the task-7 measurements, step + rebuild —
 *  Kira 416 cards (4.3–4.6) + (1.8–1.9) ≈ 6.3 ms → 0.0152; Lirien 320 cards 3.4 + 1.2 = 4.6 ms → 0.0144. */
export const STRAND_MS_PER_CARD = 0.015
/** Weight of the newest frame in `costMs`. */
const COST_EMA = 0.1
/** The capsule region the strand sim leaves out (Ruling H-R7; module docstring). */
const SKIPPED_REGION = 'head'

/** Per-strand hair of one figure (module docstring). */
export interface StrandHair {
  /** The hair mesh it drives. */
  readonly mesh: SkinnedMesh
  /** The pure sim (inspection: checks, debug). */
  readonly sim: StrandSim
  /** The targets of the last step (world, cards · 17 · 3; carried with the rows by a later frame's root carry). */
  readonly targets: Float32Array
  /** The ids of the capsules the sim collides with (the record's hair capsules without the head, Ruling H-R7). */
  readonly capsuleIds: readonly string[]
  /** Running per strand now. */
  readonly enabled: boolean
  /** EMA of a stepping frame's whole `update` in ms, every step included (an estimate before the first run). */
  readonly costMs: number
  /** On: owned geometry clone, Head-only skin on the card vertices, reset to the targets. Off: the template's
   *  geometry object back, the clone freed. */
  setEnabled(on: boolean): void
  /** The Stiffness slider: × the record's `params.stiffness`. */
  setStiffness(factor: number): void
  /** Step the frame (fixed 1/60 s with the remainder carried, ≤ 4 steps over the pose interpolated from the last
   *  frame; resets on a delta > 0.25 s or a head jump; `frozen` holds still). */
  update(realDelta: number, opts?: { frozen?: boolean }): void
  /** Off, and nothing of this handle left. */
  dispose(): void
}

/** The skinned mesh under `root` that carries the record's per-vertex binding (first found), or null. */
function strandMesh(root: Object3D, record: HairStrandRecord): SkinnedMesh | null {
  const card = (record.vertex_attributes?.card ?? '_STRAND_CARD').toLowerCase()
  const u = (record.vertex_attributes?.u ?? '_STRAND_U').toLowerCase()
  let found: SkinnedMesh | null = null
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (found || !mesh.isSkinnedMesh || !mesh.geometry) return
    if (mesh.geometry.getAttribute(card) && mesh.geometry.getAttribute(u)) found = mesh
  })
  return found
}

/** An attribute's first `itemSize` components as a plain array (interleaved or not). */
function plain<T extends Float32Array | Uint16Array>(attr: { count: number; itemSize: number; getX(i: number): number;
  getY(i: number): number; getZ(i: number): number }, make: new (n: number) => T, size = attr.itemSize): T {
  const out = new make(attr.count * size)
  for (let i = 0; i < attr.count; i++) {
    out[i * size] = attr.getX(i)
    if (size > 1) out[i * size + 1] = attr.getY(i)
    if (size > 2) out[i * size + 2] = attr.getZ(i)
  }
  return out
}

/**
 * Bind the strand record to the hair mesh under `root` (module docstring). Null — nothing touched — when no mesh
 * carries the binding attributes, the record's head or follow bones are not in that mesh's skeleton, or the record
 * and the mesh do not belong together (`StrandMismatch`: card count, attribute lengths, SDF size).
 */
export function createStrandHair(three: Three, root: Object3D, record: HairStrandRecord): StrandHair | null {
  const mesh = strandMesh(root, record)
  if (!mesh) return null
  const template = mesh.geometry
  const bones = mesh.skeleton.bones
  const boneIndex = (name: string) => {
    const key = normBoneName(name)
    return bones.findIndex(b => normBoneName(b.name) === key)
  }
  const head = boneIndex(record.head_bone)
  const follow = (record.follow?.bones ?? []).map(boneIndex)
  if (head < 0 || !follow.length || follow.some(i => i < 0)) return null
  const vattr = record.vertex_attributes ?? { card: '_STRAND_CARD', u: '_STRAND_U' }
  const posAttr = template.getAttribute('position')
  const nrmAttr = template.getAttribute('normal')
  if (!posAttr || !nrmAttr) return null
  const pos0 = plain(posAttr, Float32Array, 3)
  const nrm0 = plain(nrmAttr, Float32Array, 3)
  let sim: StrandSim
  try {
    const binding = bindStrands(record, pos0, nrm0, plain(template.getAttribute(vattr.card.toLowerCase()), Uint16Array, 1),
      plain(template.getAttribute(vattr.u.toLowerCase()), Float32Array, 1))
    sim = new StrandSim(binding, record)
  } catch (e) {
    if (e instanceof StrandMismatch) return null
    throw e
  }
  const base = strandParams(record.params)
  const params: StrandParams = { ...base }

  // Colliders (Ruling H-R7): the record's hair capsules without the head region, bound to the body skeleton; the
  // bind-pose ends in the hair primitive's geometry space, once — through inverse(bindMatrix), never the attached
  // mode's `bindMatrixInverse` (inverse(matrixWorld) NOW: the bind-rule factors would follow where the figure
  // stands; a card of a centred preview hung 128 mm off its rest, strand-hair Task 10).
  const capsules = strandCapsules(record).filter(c => c.region !== SKIPPED_REGION)
  const collision: CollisionBinding | null = capsules.length
    ? bindCollision(three, root, { version: record.capsules.version, capsules }) : null
  const geometryFromBind = new three.Matrix4().copy(mesh.bindMatrix).invert().elements
  const binds = (collision?.capsules ?? []).map(c => {
    const l = capsuleInFrame(c.bind, geometryFromBind)
    return { a: l.a, b: l.b }
  })
  const frameCaps: CollideCapsule[] = binds.map(bind => ({ a: [0, 0, 0] as Vec3, b: [0, 0, 0] as Vec3, r: 0, bind }))

  // The pose of this frame (`now*`), of the last one (`from*`, carried by the root carry) and of the step (`step*`,
  // `targets`, `frameCaps`) — Ruling H-R11, module docstring "THE CLOCK".
  const mat = (): number[] => new Array<number>(16).fill(0)
  const targets = new Float32Array(sim.n * 3)
  const nowFollow = follow.map(mat), fromFollow = follow.map(mat), stepFollow = follow.map(mat)
  const nowHead = mat(), fromHead = mat(), stepHead = mat()
  const capEnds = () => binds.map(() => ({ a: [0, 0, 0] as Vec3, b: [0, 0, 0] as Vec3, r: 0 }))
  const nowCaps = capEnds(), fromCaps = capEnds()
  const copy = (src: Mat4, out: number[]) => { for (let i = 0; i < 16; i++) out[i] = src[i] }
  const jointNow = (i: number): Mat4 => jointNowFrom(mesh.matrixWorld.elements, mesh.bindMatrixInverse.elements,
    bones[i].matrixWorld.elements, mesh.skeleton.boneInverses[i].elements, mesh.bindMatrix.elements).bindToWorld
  /** The pose now: follow matrices, head, capsules. */
  const sample = () => {
    follow.forEach((b, k) => copy(jointNow(b), nowFollow[k]))
    copy(jointNow(head), nowHead)
    if (collision) {
      collision.update()
      collision.capsules.forEach((c, i) => {
        const n = nowCaps[i]
        for (let d = 0; d < 3; d++) { n.a[d] = c.now.a[d]; n.b[d] = c.now.b[d] }
        n.r = c.now.r
      })
    }
  }
  /** The pose of a step at fraction `s` of the frame (0 the last frame's, 1 this one's): the follow matrices and
   *  the head slerped, the capsule ends linear, the targets from the follow matrices. */
  const poseAt = (s: number) => {
    const t = s >= 1 - 1e-9 ? 1 : s
    follow.forEach((_, k) => lerpFrame(fromFollow[k], nowFollow[k], t, stepFollow[k]))
    lerpFrame(fromHead, nowHead, t, stepHead)
    strandTargets(record, stepFollow, targets)
    frameCaps.forEach((fc, i) => {
      const a = fromCaps[i], b = nowCaps[i]
      for (let d = 0; d < 3; d++) {
        fc.a[d] = a.a[d] + (b.a[d] - a.a[d]) * t
        fc.b[d] = a.b[d] + (b.b[d] - a.b[d]) * t
      }
      fc.r = a.r + (b.r - a.r) * t
    })
  }
  /** This frame's pose becomes the next frame's start. */
  const keepPose = () => {
    follow.forEach((_, k) => copy(nowFollow[k], fromFollow[k]))
    copy(nowHead, fromHead)
    nowCaps.forEach((n, i) => {
      const f = fromCaps[i]
      for (let d = 0; d < 3; d++) { f.a[d] = n.a[d]; f.b[d] = n.b[d] }
      f.r = n.r
    })
  }
  /** `m · p` for a point, in place. */
  const movePoint = (m: Mat4, p: number[] | Float32Array, o = 0) => {
    const x = p[o], y = p[o + 1], z = p[o + 2]
    p[o] = m[0] * x + m[4] * y + m[8] * z + m[12]
    p[o + 1] = m[1] * x + m[5] * y + m[9] * z + m[13]
    p[o + 2] = m[2] * x + m[6] * y + m[10] * z + m[14]
  }
  const scratch = mat()
  /** `a · b` (column-major 4×4) into `out` (which may be `b`). */
  const mul4 = (a: Mat4, b: Mat4, out: number[]) => {
    const r = scratch
    for (let c = 0; c < 4; c++) {
      for (let k = 0; k < 4; k++) {
        r[4 * c + k] = a[k] * b[4 * c] + a[4 + k] * b[4 * c + 1] + a[8 + k] * b[4 * c + 2] + a[12 + k] * b[4 * c + 3]
      }
    }
    copy(r, out)
    return out
  }
  /** A world → world carry of the rows (`sim.carry`) and the targets; `pose` also the last frame's pose. */
  const carryAll = (m: Mat4, pose: boolean) => {
    sim.carry(m)
    for (let o = 0; o < targets.length; o += 3) movePoint(m, targets, o)
    if (!pose) return
    fromFollow.forEach(f => mul4(m, f, f))
    mul4(m, fromHead, fromHead)
    fromCaps.forEach(c => { movePoint(m, c.a); movePoint(m, c.b) })
  }
  /** The step's pose becomes the start of the rest of the frame (a long frame, after its untaken part). */
  const startAtStep = () => {
    follow.forEach((_, k) => copy(stepFollow[k], fromFollow[k]))
    copy(stepHead, fromHead)
    frameCaps.forEach((fc, i) => {
      const f = fromCaps[i]
      for (let d = 0; d < 3; d++) { f.a[d] = fc.a[d]; f.b[d] = fc.b[d] }
      f.r = fc.r
    })
  }

  let owned: BufferGeometry | null = null
  let posOut: BufferAttribute | null = null
  let nrmOut: BufferAttribute | null = null
  let acc = 0
  let lastHead: Vec3 | null = null
  let costMs = record.cards * STRAND_MS_PER_CARD
  let costRan = false
  const inertia = new RootInertia()

  /** The rows into head-bind space through the head of the last step (`stepHead`). */
  const rebuild = () => {
    if (!posOut || !nrmOut) return
    sim.rebuild(invertAffine(stepHead), posOut.array as Float32Array, nrmOut.array as Float32Array)
    posOut.needsUpdate = true
    nrmOut.needsUpdate = true
  }
  /** Every row on its target of this frame's pose. */
  const reset = () => {
    keepPose()
    poseAt(1)
    sim.reset(targets)
    acc = 0
    inertia.reset()
    inertia.update(root.matrixWorld.elements, 0)    // records the root; the next frame measures its motion
    rebuild()
  }

  const handle: StrandHair = {
    mesh, sim, targets,
    capsuleIds: (collision?.capsules ?? []).map(c => c.capsule.id),
    get enabled() { return owned !== null },
    get costMs() { return costMs },
    setEnabled(on: boolean) {
      if (on === (owned !== null)) return
      if (on) {
        const g = template.clone()
        // Plain position / normal arrays the rebuild writes into (a clone of an interleaved attribute stays one).
        posOut = new three.BufferAttribute(Float32Array.from(pos0), 3)
        nrmOut = new three.BufferAttribute(Float32Array.from(nrm0), 3)
        g.setAttribute('position', posOut)
        g.setAttribute('normal', nrmOut)
        const si = g.getAttribute('skinIndex'), sw = g.getAttribute('skinWeight')
        const vk = sim.binding.vk
        for (let v = 0; v < vk.length; v++) {
          if (vk[v] < 0) continue
          si.setXYZW(v, head, 0, 0, 0)
          sw.setXYZW(v, 1, 0, 0, 0)
        }
        si.needsUpdate = true
        sw.needsUpdate = true
        owned = g
        mesh.geometry = g
        root.updateWorldMatrix(true, true)
        sample()
        lastHead = [nowHead[12], nowHead[13], nowHead[14]]
        reset()
      } else {
        mesh.geometry = template
        owned?.dispose()
        owned = null
        posOut = null
        nrmOut = null
        lastHead = null
        acc = 0
      }
    },
    setStiffness(factor: number) {
      params.stiffness = base.stiffness * (Number.isFinite(factor) && factor > 0 ? factor : 1)
    },
    update(realDelta: number, opts: { frozen?: boolean } = {}) {
      if (!owned || opts.frozen) return
      const t0 = performance.now()
      sample()
      const h: Vec3 = [nowHead[12], nowHead[13], nowHead[14]]
      const jump = lastHead ? Math.hypot(h[0] - lastHead[0], h[1] - lastHead[1], h[2] - lastHead[2]) : 0
      lastHead = h
      if (!(realDelta <= STRAND_RESET_DELTA_S) || jump > STRAND_RESET_JUMP_M) { reset(); return }
      const carry = inertia.update(root.matrixWorld.elements, realDelta)
      if (carry) carryAll(carry, true)
      // Ruling H-R11 (module docstring "THE CLOCK"): step k of this frame ends k/60 s after the sim's last step,
      // i.e. at (k·dt − acc) / delta of the frame; beyond 4 steps the frame's last 4/60 s, the head's motion before
      // them carried rigidly.
      const delta = Math.max(0, realDelta)
      let steps = Math.floor((acc + delta) / STRAND_DT + 1e-6)
      let start = -acc, span = delta     // step k at (start + k·dt) / span of what is left of the frame
      if (steps > STRAND_MAX_STEPS) {
        steps = STRAND_MAX_STEPS
        poseAt(1 - steps * STRAND_DT / delta)
        carryAll(mul4(stepHead, invertAffine(fromHead), mat()), false)
        startAtStep()
        start = 0
        span = steps * STRAND_DT
        acc = 0
      } else {
        acc = Math.max(0, acc + delta - steps * STRAND_DT)
      }
      for (let k = 1; k <= steps; k++) {
        poseAt((start + k * STRAND_DT) / span)
        sim.step(STRAND_DT, { targets, head: stepHead, capsules: frameCaps, follow: stepFollow }, params)
      }
      keepPose()
      if (!steps) return
      rebuild()
      const ms = performance.now() - t0
      costMs = costRan ? costMs + (ms - costMs) * COST_EMA : ms
      costRan = true
    },
    dispose() { handle.setEnabled(false) },
  }
  return handle
}
