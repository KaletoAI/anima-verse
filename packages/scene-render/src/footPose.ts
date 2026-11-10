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

/**
 * A clone of `clip` with the extension baked in: every quaternion key of a
 * bone `fp` names (matched by `normBoneName`) becomes `q · R(axis, deg)`; a
 * named bone without a quaternion track gets a constant one-key track
 * `rest · R`, where `rest` is that bone's local rest rotation from the
 * TARGET figure's `RestPose` (identity when no rest pose is given or it
 * lacks the bone). The result is marked `userData.footPosed = fsig`; a
 * marked clip is returned unchanged, and so is `clip` for a null record.
 * The input clip is never modified (a cached clip may be shared by shod and
 * bare figures); tracks the record does not touch are shared with it, as in
 * `bindRelativeClip`.
 */
export function applyFootPose(three: Three, clip: AnimationClip, fp: FootPose | null | undefined,
  rest?: RestPose | null): AnimationClip {
  if (!usable(fp)) return clip
  if ((clip.userData as { footPosed?: unknown } | undefined)?.footPosed) return clip
  const turns = turnsOf(three, fp)
  const tracks: KeyframeTrack[] = []
  const seen = new Set<string>()
  const q = new three.Quaternion()
  for (const track of clip.tracks) {
    const dot = track.name.lastIndexOf('.')
    const key = dot > 0 && track.name.slice(dot + 1) === 'quaternion' ? normBoneName(track.name.slice(0, dot)) : ''
    const turn = key ? turns.get(key) : undefined
    if (!turn) { tracks.push(track); continue }
    seen.add(key)
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
    const turn = turns.get(key)
    if (!turn || seen.has(key)) continue
    seen.add(key)
    const restLocal = new three.Quaternion()
    const world = rest?.world.get(key)
    const parent = rest?.parent.get(key)
    if (world && parent) restLocal.copy(parent).invert().multiply(world)
    restLocal.multiply(turn)
    const node = three.PropertyBinding.sanitizeNodeName(name)
    tracks.push(new three.QuaternionKeyframeTrack(`${node}.quaternion`, [0],
      [restLocal.x, restLocal.y, restLocal.z, restLocal.w]))
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
