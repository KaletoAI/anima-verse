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
 * THE CLOCK (spec § 6.2.2). A fixed step of 1/60 s with an accumulator of at most 4 steps per frame; a frame
 * delta > 0.25 s or a head jump > 0.5 m (teleport, rebuild) resets the sim to the targets; `frozen` holds it
 * still (nothing is written). The rebuild runs once per frame that stepped; a frame without a step leaves the
 * hair where the last one put it, carried by the head.
 *
 * THE ROOT'S MOTION (Ruling H-R10). Before the steps of a frame the simulated rows are carried by the part of the
 * root's (`root`, the figure instance) motion the strands do not feel (`RootInertia`, `STRAND_ROOT_LIMITS`): the
 * game's 10/s turn ease, its snaps and its walk starts at full speed in one frame flung the free rows out
 * horizontally; within the spike's tuning motions everything is felt as before.
 *
 * COST. `costMs` is an EMA of the measured sim + rebuild milliseconds per stepping frame — what the figure
 * budget (`pickStrandFigures`) adds up. Before the first run it is an estimate from the card count
 * (`STRAND_MS_PER_CARD`).
 *
 * `three` is injected, never imported.
 */
import type { BufferAttribute, BufferGeometry, Object3D, SkinnedMesh } from 'three'
import { normBoneName } from './clipRetarget'
import { bindCollision, jointNowFrom } from './collision'
import type { CollisionBinding, Mat4, Vec3 } from './collision'
import { capsuleInFrame } from './garmentCollision'
import type { CollideCapsule } from './garmentCollision'
import { bindStrands, invertAffine, RootInertia, StrandMismatch, strandCapsules, strandParams, StrandSim,
  strandTargets } from './hairSimMath'
import type { HairStrandRecord, StrandParams } from './hairSimMath'

type Three = typeof import('three')

/** The fixed step (s). */
export const STRAND_DT = 1 / 60
/** Steps one frame may take at most. */
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
  /** The targets of the last frame (world, cards · 17 · 3). */
  readonly targets: Float32Array
  /** The ids of the capsules the sim collides with (the record's hair capsules without the head, Ruling H-R7). */
  readonly capsuleIds: readonly string[]
  /** Running per strand now. */
  readonly enabled: boolean
  /** EMA of the sim + rebuild ms per stepping frame (an estimate before the first run). */
  readonly costMs: number
  /** On: owned geometry clone, Head-only skin on the card vertices, reset to the targets. Off: the template's
   *  geometry object back, the clone freed. */
  setEnabled(on: boolean): void
  /** The Stiffness slider: × the record's `params.stiffness`. */
  setStiffness(factor: number): void
  /** Step the frame (fixed 1/60 s, ≤ 4 steps; resets on a long frame or a head jump; `frozen` holds still). */
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
  // bind-pose ends in the hair primitive's geometry space, once.
  const capsules = strandCapsules(record).filter(c => c.region !== SKIPPED_REGION)
  const collision: CollisionBinding | null = capsules.length
    ? bindCollision(three, root, { version: record.capsules.version, capsules }) : null
  const binds = (collision?.capsules ?? []).map(c => {
    const l = capsuleInFrame(c.bind, mesh.bindMatrixInverse.elements)
    return { a: l.a, b: l.b }
  })
  const frameCaps: CollideCapsule[] = binds.map(bind => ({ a: [0, 0, 0] as Vec3, b: [0, 0, 0] as Vec3, r: 0, bind }))

  const targets = new Float32Array(sim.n * 3)
  const followMats: Mat4[] = follow.map(() => new Array<number>(16).fill(0))
  let headMat: Mat4 = new Array<number>(16).fill(0)
  const jointNow = (i: number): Mat4 => jointNowFrom(mesh.matrixWorld.elements, mesh.bindMatrixInverse.elements,
    bones[i].matrixWorld.elements, mesh.skeleton.boneInverses[i].elements, mesh.bindMatrix.elements).bindToWorld
  /** The frame now: follow matrices, head, targets, capsules. */
  const sample = () => {
    follow.forEach((b, k) => { followMats[k] = jointNow(b) })
    headMat = jointNow(head)
    strandTargets(record, followMats, targets)
    if (collision) {
      collision.update()
      collision.capsules.forEach((c, i) => {
        const fc = frameCaps[i]
        fc.a = c.now.a; fc.b = c.now.b; fc.r = c.now.r
      })
    }
  }

  let owned: BufferGeometry | null = null
  let posOut: BufferAttribute | null = null
  let nrmOut: BufferAttribute | null = null
  let acc = 0
  let lastHead: Vec3 | null = null
  let costMs = record.cards * STRAND_MS_PER_CARD
  let costRan = false
  const inertia = new RootInertia()

  const rebuild = () => {
    if (!posOut || !nrmOut) return
    sim.rebuild(invertAffine(headMat), posOut.array as Float32Array, nrmOut.array as Float32Array)
    posOut.needsUpdate = true
    nrmOut.needsUpdate = true
  }
  const reset = () => {
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
        lastHead = [headMat[12], headMat[13], headMat[14]]
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
      const h: Vec3 = [headMat[12], headMat[13], headMat[14]]
      const jump = lastHead ? Math.hypot(h[0] - lastHead[0], h[1] - lastHead[1], h[2] - lastHead[2]) : 0
      lastHead = h
      if (!(realDelta <= STRAND_RESET_DELTA_S) || jump > STRAND_RESET_JUMP_M) { reset(); return }
      const carry = inertia.update(root.matrixWorld.elements, realDelta)
      if (carry) sim.carry(carry)
      acc = Math.min(acc + Math.max(0, realDelta), STRAND_MAX_STEPS * STRAND_DT)
      let steps = 0
      while (acc >= STRAND_DT - 1e-9 && steps < STRAND_MAX_STEPS) {
        sim.step(STRAND_DT, { targets, head: headMat, capsules: frameCaps }, params)
        acc -= STRAND_DT
        steps++
      }
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
