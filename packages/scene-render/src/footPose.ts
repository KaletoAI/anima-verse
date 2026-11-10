/**
 * footPose.ts — WHAT A FITTED SHOE DOES TO THE FOOT. The served (assembled)
 * model sidecar carries `foot_pose` beside a fitted footwear piece (server
 * `app/core/footwear_fit.py::fit_pair` + `app/core/garment_footwear.py`,
 * which adds `source`); `null` without a fitted shoe. Both renderers read it
 * through this module and nowhere else.
 *
 * THE EXTENSION. A shoe with a heel stands the foot on its toes: the fit
 * turns Foot by `deg` about `axis` and ToeBase back by its own turn, each
 * axis in that bone's LOCAL frame of the bind pose (the server solves the
 * world axis into the joint's bind matrix). In three terms each key of the
 * bone's quaternion track becomes `q' = q · R(axis, deg)` — the turn rides
 * on whatever the clip does with the foot. It is baked ONCE per clip, right
 * after the retarget / bind-relative step (`applyFootPose`); a figure shown
 * without a clip gets the same local turns once (`applyFootPoseToPose`).
 * Both mark what they did (`userData.footPosed = fsig`) and do nothing on a
 * marked input, so a second call can never double the turn.
 *
 * THE EXTENSION IS RELATIVE TO THE BIND FOOT — the only pose the server has.
 * A retargeted clip, though, is relative to the rest the transplant plays
 * (`transplantedRestPose`): the kernel divides the rig's global attitude
 * out and may turn leg or foot subtrees, so under every clip the Foot already
 * sits some degrees from its bind rotation before the clip moves it. Measured
 * on a generated character (P2 acceptance, 2026-11-10): 4.64° heel-down on
 * both feet, which left the fitted sole 13 mm under the floor at the heel in
 * the idle clip and shifted every walk frame by the same amount. So a caller
 * that hands in the target's rest AND that transplanted rest gets the delta
 * carried: for the top named bone of a side (the Foot) the turn becomes
 * `D⁻¹ · R` with `D = W_bind⁻¹ · W_clip` its WORLD delta — the sole stands
 * where the fit put it whatever the parents did; a named bone under a named
 * one (the ToeBase) takes its LOCAL delta, because its parent's turn already
 * carries the world. A bone without a track keeps its bind local under the
 * mixer, so its delta is read with that local in place. Without a
 * transplanted rest the turn is `R` alone — the still pose, or a clip played
 * against the bind itself.
 *
 * THE LIFT. The shod sole stands `root_lift_m` higher than the bare one. It
 * is never baked into a track: standing (`clipHeightGroup` 'ground', which
 * includes unknown groups) lifts the root by it, seated and lying figures
 * by nothing (`footPoseLiftM`).
 *
 * THE MATCH. `glb_sha256` binds the record to the GLB on the server side;
 * a renderer cannot cheaply hash the GLB it loaded, so it checks the shoe
 * nodes it actually has: a garment node of kind `footwear` with the same
 * `fsig` and `item_id` (`footPoseMatches`). A record that does not match
 * the loaded shoes is not applied.
 *
 * THE CONTACTS. Heel, ball and toe of each sole are bind-space points fixed
 * to their bone — exactly the collision capsules' endpoint rule
 * (`jointNowFrom` in `collision.ts`), so `footContactsNow` reads them the
 * same way the capsules are read.
 *
 * `three` is injected, never imported. Every function is a no-op (returns
 * its input / 0 / empty / false) for a null record or one of another version.
 */
import type { AnimationClip, KeyframeTrack, Object3D, Quaternion, SkinnedMesh, Vector3 } from 'three'
import { normBoneName } from './clipRetarget'
import type { RestPose } from './clipRetarget'
import { jointNowFrom, transformPoint } from './collision'
import { FIGURE_HEIGHT_M, clipHeightGroup, inGarment } from './figure'

type Three = typeof import('three')

export type FootSide = 'left' | 'right'

/** One sole contact: a bind-space point fixed to `bone`. */
export interface FootContact {
  bone: string
  pos: [number, number, number]
  role: 'heel' | 'ball' | 'toe'
}

/** The `foot_pose` record of the served model sidecar. */
export interface FootPose {
  version: 1
  source: { item_id: string; fsig: string; glb_sha256: string }
  /** Joint name (as in the GLB) → a turn about a unit axis in the bone's local bind frame. */
  bones: Record<string, { axis: [number, number, number]; deg: number }>
  root_lift_m: number
  contacts: Record<FootSide, FootContact[]>
}

/** The record version this module understands; anything else is ignored. */
export const FOOT_POSE_VERSION = 1

const SIDES: FootSide[] = ['left', 'right']

function usable(fp: FootPose | null | undefined): fp is FootPose {
  return !!fp && fp.version === FOOT_POSE_VERSION && !!fp.source && typeof fp.source.fsig === 'string'
}

/** normalised bone name → the local turn of `fp` (bones with a degenerate axis or angle left out). */
function turnsOf(three: Three, fp: FootPose): Map<string, Quaternion> {
  const out = new Map<string, Quaternion>()
  for (const [name, turn] of Object.entries(fp.bones ?? {})) {
    const axis = turn?.axis
    const deg = turn?.deg
    if (!Array.isArray(axis) || axis.length !== 3 || typeof deg !== 'number' || !Number.isFinite(deg)) continue
    const v = new three.Vector3(axis[0], axis[1], axis[2])
    const len = v.length()
    if (!(len > 1e-12) || !Number.isFinite(len)) continue
    out.set(normBoneName(name), new three.Quaternion().setFromAxisAngle(v.divideScalar(len), deg * Math.PI / 180))
  }
  return out
}

/** `key`'s local rest rotation in `pose`, identity when the pose lacks it. */
function localOf(three: Three, pose: RestPose | null | undefined, key: string): Quaternion {
  const out = new three.Quaternion()
  const world = pose?.world.get(key)
  const parent = pose?.parent.get(key)
  if (world && parent) out.copy(parent).invert().multiply(world)
  return out
}

/**
 * The turn a named bone gets under a clip relative to `clipRest`
 * (module docstring, "relative to the bind foot"): `D⁻¹ · R`, with `D` the
 * bone's WORLD delta bind → transplanted rest when no ancestor is named,
 * else its LOCAL delta. `hasTrack` false = the bone keeps its bind local
 * under the mixer, so the delta is read with that local in place of the
 * transplant's. `R` alone when either rest is missing or lacks the bone.
 */
function turnUnderClip(three: Three, key: string, R: Quaternion, hasTrack: boolean,
  named: Set<string>, rest?: RestPose | null, clipRest?: RestPose | null): Quaternion {
  if (!rest || !clipRest) return R
  const bindWorld = rest.world.get(key)
  const clipParent = clipRest.parent.get(key)
  const clipWorld = clipRest.world.get(key)
  if (!bindWorld || !clipParent || !clipWorld) return R
  let ancestorNamed = false
  for (let above = rest.parentBone.get(key); above; above = rest.parentBone.get(above)) {
    if (named.has(above)) { ancestorNamed = true; break }
  }
  const bindLocal = localOf(three, rest, key)
  const clipLocal = hasTrack ? new three.Quaternion().copy(clipParent).invert().multiply(clipWorld) : bindLocal
  const delta = ancestorNamed
    ? new three.Quaternion().copy(bindLocal).invert().multiply(clipLocal)
    : new three.Quaternion().copy(bindWorld).invert().multiply(clipParent).multiply(clipLocal)
  return delta.invert().multiply(R)
}

/**
 * A clone of `clip` with the extension baked in: every quaternion key of a
 * bone `fp` names (matched by `normBoneName`) becomes `q · R(axis, deg)`; a
 * named bone without a quaternion track gets a constant one-key track
 * `rest · R`, where `rest` is that bone's local rest rotation from the
 * TARGET figure's `RestPose` (identity when no rest pose is given or it
 * lacks the bone). With `clipRest` — the rest the retargeted clip is
 * relative to, `transplantedRestPose` of the same figure and corrections —
 * `R` becomes `D⁻¹ · R` per bone (module docstring), so the sole stands
 * where the fit put it although the transplant moved the foot off its bind.
 * The result is marked `userData.footPosed = fsig`; a
 * marked clip is returned unchanged, and so is `clip` for a null record.
 * The input clip is never modified (a cached clip may be shared by shod and
 * bare figures); tracks the record does not touch are shared with it, as in
 * `bindRelativeClip`.
 */
export function applyFootPose(three: Three, clip: AnimationClip, fp: FootPose | null | undefined,
  rest?: RestPose | null, clipRest?: RestPose | null): AnimationClip {
  if (!usable(fp)) return clip
  if ((clip.userData as { footPosed?: unknown } | undefined)?.footPosed) return clip
  const turns = turnsOf(three, fp)
  const named = new Set(turns.keys())
  const tracks: KeyframeTrack[] = []
  const seen = new Set<string>()
  const q = new three.Quaternion()
  for (const track of clip.tracks) {
    const dot = track.name.lastIndexOf('.')
    const key = dot > 0 && track.name.slice(dot + 1) === 'quaternion' ? normBoneName(track.name.slice(0, dot)) : ''
    const R = key ? turns.get(key) : undefined
    if (!R) { tracks.push(track); continue }
    seen.add(key)
    const turn = turnUnderClip(three, key, R, true, named, rest, clipRest)
    const values = new Float32Array(track.values.length)
    for (let i = 0; i + 3 < track.values.length; i += 4) {
      q.set(track.values[i], track.values[i + 1], track.values[i + 2], track.values[i + 3]).multiply(turn)
      values[i] = q.x; values[i + 1] = q.y; values[i + 2] = q.z; values[i + 3] = q.w
    }
    tracks.push(new three.QuaternionKeyframeTrack(track.name, track.times, values))
  }
  // Named bones without a track: a constant track, named the way the GLB loader names the node
  // (three drops the reserved characters, e.g. the colon of `mixamorig:LeftFoot`).
  for (const [name] of Object.entries(fp.bones ?? {})) {
    const key = normBoneName(name)
    const R = turns.get(key)
    if (!R || seen.has(key)) continue
    seen.add(key)
    const value = localOf(three, rest, key).multiply(turnUnderClip(three, key, R, false, named, rest, clipRest))
    const node = three.PropertyBinding.sanitizeNodeName(name)
    tracks.push(new three.QuaternionKeyframeTrack(`${node}.quaternion`, [0],
      [value.x, value.y, value.z, value.w]))
  }
  const out = new three.AnimationClip(clip.name, clip.duration, tracks, clip.blendMode)
  out.userData = { ...(clip.userData ?? {}), footPosed: fp.source.fsig }
  return out
}

/**
 * The still pose: the same local turns applied ONCE to the bones under
 * `root` (every bone node whose `normBoneName` matches), for a figure shown
 * without a clip. Marks `root.userData.footPosed = fsig`; a marked root is
 * left alone, so is everything for a null record. Call `updateMatrixWorld`
 * afterwards as usual.
 */
export function applyFootPoseToPose(three: Three, root: Object3D, fp: FootPose | null | undefined): void {
  if (!usable(fp) || root.userData.footPosed) return
  const turns = turnsOf(three, fp)
  root.traverse(o => {
    if (!(o as { isBone?: boolean }).isBone) return
    const turn = turns.get(normBoneName(o.name))
    if (turn) o.quaternion.multiply(turn)
  })
  root.userData.footPosed = fp.source.fsig
}

/**
 * How far the root stands higher for the shod sole: `root_lift_m` when the
 * height group is 'ground' (`clipHeightGroup` — unknown and absent groups
 * are ground), else 0. Scaled by `figureHeight / FIGURE_HEIGHT_M` like
 * `clipHeightOffsetM` (no scaling when omitted).
 */
export function footPoseLiftM(fp: FootPose | null | undefined, group: string | null | undefined,
  figureHeight = FIGURE_HEIGHT_M): number {
  if (!usable(fp) || clipHeightGroup(group) !== 'ground') return 0
  const lift = fp.root_lift_m
  if (typeof lift !== 'number' || !Number.isFinite(lift)) return 0
  return lift * figureHeight / FIGURE_HEIGHT_M
}

/**
 * Whether `root` carries the shoes `fp` was fitted for: a node (anywhere
 * under it) whose `userData.garment` has kind `footwear` and the record's
 * `fsig` and `item_id`. False for a null record.
 */
export function footPoseMatches(root: Object3D, fp: FootPose | null | undefined): boolean {
  if (!usable(fp)) return false
  let found = false
  root.traverse(o => {
    if (found) return
    const g = (o.userData as { garment?: { kind?: unknown; fsig?: unknown; item_id?: unknown } } | undefined)?.garment
    if (g && g.kind === 'footwear' && g.fsig === fp.source.fsig && g.item_id === fp.source.item_id) found = true
  })
  return found
}

/**
 * The sole contacts in WORLD space in the current frame, per side, in record
 * order — each a bind-space point fixed to its bone, by the collision
 * endpoint rule (`jointNowFrom`). The bone is looked up in the skeleton of a
 * BODY skinned mesh (never a garment's: the points live in the body's bind
 * space); a contact whose bone the figure lacks is left out. Call after
 * `updateMatrixWorld`. `out` is reused (its arrays resized, its vectors
 * overwritten). Both sides empty for a null record.
 */
export function footContactsNow(three: Three, root: Object3D, fp: FootPose | null | undefined,
  out?: Record<FootSide, Vector3[]>): Record<FootSide, Vector3[]> {
  const res = out ?? { left: [], right: [] }
  if (!usable(fp)) {
    res.left.length = 0
    res.right.length = 0
    return res
  }
  const joints = new Map<string, { mesh: SkinnedMesh; index: number }>()
  root.traverse(o => {
    const mesh = o as SkinnedMesh
    if (!mesh.isSkinnedMesh || !mesh.skeleton || inGarment(mesh)) return
    mesh.skeleton.bones.forEach((bone, index) => {
      const key = normBoneName(bone.name)
      if (!joints.has(key)) joints.set(key, { mesh, index })
    })
  })
  for (const side of SIDES) {
    const list = res[side] ?? (res[side] = [])
    let n = 0
    for (const contact of fp.contacts?.[side] ?? []) {
      const ref = joints.get(normBoneName(contact.bone))
      if (!ref || !Array.isArray(contact.pos) || contact.pos.length !== 3) continue
      const { mesh, index } = ref
      const joint = jointNowFrom(mesh.matrixWorld.elements, mesh.bindMatrixInverse.elements,
        mesh.skeleton.bones[index].matrixWorld.elements, mesh.skeleton.boneInverses[index].elements,
        mesh.bindMatrix.elements)
      const p = transformPoint(joint.bindToWorld, contact.pos)
      const v = list[n] ?? (list[n] = new three.Vector3())
      v.set(p[0], p[1], p[2])
      n += 1
    }
    list.length = n
  }
  return res
}
