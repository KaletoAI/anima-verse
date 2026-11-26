/**
 * pairHeightPose.ts — the per-frame application of a figure's PAIR HEIGHT offset (`pairHeight.ts`): the hips move
 * straight up or down by the offset and a two-bone leg IK (`twoBoneIk`) brings every PLANTED leg's ankle back to
 * where the clip put it, the foot keeping its world rotation; a leg that is not planted moves with the hips. The ONE
 * routine of both browser renderers (the 3D client's `Figure.update`, the Pose library's "Real heights" preview);
 * `three` is injected. The native twin is native/Figures/PairHeightModifier.cs.
 *
 * Order in a frame: after the clip pose and the root placement (phase A), before the runtime's `poseStep` and phase B
 * (partner snapshot, channels, the chain bend) — every later step sees the moved hips. An offset of exactly 0 does
 * nothing at all (no matrix is touched), so equal heights stay bit-identical.
 */
import type { Object3D, Quaternion, Vector3 } from 'three'
import { twoBoneIk } from './twoBoneIk'
import type { Quat, Vec3 } from './twoBoneIk'
import { normBoneName } from './clipRetarget'

type Three = typeof import('three')

/** The bones the offset moves: the hips and per leg [left, right] thigh, shin and foot. */
export interface PairHeightRig {
  hips: Object3D
  legs: ({ upper: Object3D; lower: Object3D; foot: Object3D } | null)[]
}

const isBelow = (bone: Object3D, ancestor: Object3D): boolean => {
  for (let p = bone.parent; p; p = p.parent) if (p === ancestor) return true
  return false
}

/** The rig of a figure (Mixamo names, `normBoneName`); null without hips. A leg whose chain is incomplete is null. */
export function pairHeightRigOf(root: Object3D): PairHeightRig | null {
  const byKey = new Map<string, Object3D>()
  root.traverse((o) => {
    if (!(o as { isBone?: boolean }).isBone) return
    const k = normBoneName(o.name)
    if (!byKey.has(k)) byKey.set(k, o)
  })
  const hips = byKey.get('hips')
  if (!hips) return null
  const legs = (['left', 'right'] as const).map((side) => {
    const upper = byKey.get(`${side}upleg`), lower = byKey.get(`${side}leg`), foot = byKey.get(`${side}foot`)
    return upper && lower && foot && isBelow(upper, hips) && isBelow(lower, upper) && isBelow(foot, lower)
      ? { upper, lower, foot } : null
  })
  return { hips, legs }
}

/** A per-figure poser around `applyPairHeight`, called once per frame after the clip pose. A clip does NOT rewrite a
 *  bone whose value did not change since the last frame (three.js' PropertyMixer writes only a changed value: a held,
 *  frozen or clamped clip, a static track, the Pose library's dropped hips track). So every bone this routine wrote
 *  last frame — the hips position and the held legs' thigh, shin and foot rotations — that still holds exactly what it
 *  wrote is put back to the value it had before, FIRST; only then is this frame's offset applied. Without that the IK
 *  of the next frame starts from last frame's IK result: a held ankle climbs by the offset every frame. An offset of 0
 *  after a non-zero one only puts the bones back; 0 throughout touches nothing. */
export function pairHeightPoser(three: Three, rig: PairHeightRig): (offsetM: number, planted: readonly boolean[]) => void {
  type Written = { o: Object3D; key: 'position' | 'quaternion'; base: Vector3 | Quaternion; set: Vector3 | Quaternion }
  let written: Written[] = []
  const bones = (): Object3D[] => [rig.hips, ...rig.legs.flatMap((l) => (l ? [l.upper, l.lower, l.foot] : []))]
  const valueOf = (o: Object3D, key: Written['key']) => (key === 'position' ? o.position.clone() : o.quaternion.clone())
  return (offsetM, planted) => {
    let restored = false
    for (const w of written) {
      const now = w.key === 'position' ? w.o.position : w.o.quaternion
      if (!(now as { equals(v: unknown): boolean }).equals(w.set)) continue
      if (w.key === 'position') w.o.position.copy(w.base as Vector3)
      else w.o.quaternion.copy(w.base as Quaternion)
      restored = true
    }
    written = []
    if (restored) rig.hips.updateMatrixWorld(true)
    if (!(offsetM !== 0 && Number.isFinite(offsetM))) return
    const before = bones().map((o, i) => ({ o, key: (i === 0 ? 'position' : 'quaternion') as Written['key'] }))
      .map((b) => ({ ...b, base: valueOf(b.o, b.key) }))
    applyPairHeight(three, rig, offsetM, planted)
    written = before.map((b) => ({ ...b, set: valueOf(b.o, b.key) }))
  }
}

/** Move the hips by `offsetM` (world metres, + = up) and hold the planted legs' ankles (`planted` [left, right]).
 *  The caller has the figure's world matrices current (the clip pose and the root of this frame). */
export function applyPairHeight(three: Three, rig: PairHeightRig, offsetM: number, planted: readonly boolean[]): void {
  if (!(offsetM !== 0 && Number.isFinite(offsetM))) return
  const wp = (o: Object3D): Vector3 => o.getWorldPosition(new three.Vector3())
  const wq = (o: Object3D): Quaternion => o.getWorldQuaternion(new three.Quaternion())
  const v3 = (p: Vector3): Vec3 => [p.x, p.y, p.z]
  const held = rig.legs.map((leg, i) => (leg && planted[i] ? { leg, ankle: wp(leg.foot), foot: wq(leg.foot) } : null))
  // the hips: straight up/down in world space
  const hips = rig.hips
  const target = wp(hips)
  target.y += offsetM
  if (hips.parent) hips.parent.worldToLocal(target)
  hips.position.copy(target)
  hips.updateMatrixWorld(true)
  const setWorld = (o: Object3D, q: Quaternion) => {
    const parent = o.parent ? wq(o.parent) : new three.Quaternion()
    o.quaternion.copy(parent.invert().multiply(q))
    o.updateMatrixWorld(true)
  }
  const toThree = (q: Quat): Quaternion => new three.Quaternion(q[1], q[2], q[3], q[0])
  for (const h of held) {
    if (!h) continue
    const { leg } = h
    const ik = twoBoneIk(v3(wp(leg.upper)), v3(wp(leg.lower)), v3(wp(leg.foot)), v3(h.ankle), v3(wp(leg.lower)))
    setWorld(leg.upper, toThree(ik.upper).multiply(wq(leg.upper)))
    setWorld(leg.lower, toThree(ik.lower).multiply(wq(leg.lower)))
    setWorld(leg.foot, h.foot)
  }
}
