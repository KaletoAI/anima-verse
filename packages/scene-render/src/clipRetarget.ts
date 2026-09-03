/**
 * clipRetarget.ts — READING A LIBRARY CLIP AS A ROTATION AWAY FROM REST.
 *
 * The shared clip library is authored on ONE skeleton: every clip is
 * retargeted onto `shared/models/rig/reference.fbx` by the importer, so a
 * clip's local quaternion tracks are written in THAT rig's rest frame.
 *
 * Copying those tracks onto another rig 1:1 sets each bone to the DONOR's
 * local orientation and therefore overwrites whatever the target rig holds in
 * its own bind pose. The mesh is skinned to that bind, so the copy twists
 * every limb around its own axis by the difference of the two bone frames —
 * measured over 20 generated characters on `idle.fbx`, a mean 30.4° of twist
 * across the arm bones and 166° at worst, with finger rolls up to 180°.
 *
 * DERIVATION. Write `R_b` for a bone's REST orientation in WORLD space (the
 * product of the local rest rotations from the skeleton root down to `b`),
 * `W_b(t)` for its animated world orientation, and `c_b` for the clip's local
 * value. What skinning shows is the DEFORMATION `M_b = W_b(t)·R_b⁻¹`, and
 * "play the actor's motion on this body" means the target must deform exactly
 * as the donor did, `M_t,b = M_d,b`, hence
 *
 *     W_t,b = W_d,b · R_d,b⁻¹ · R_t,b = W_d,b · K_b      K_b = R_d,b⁻¹ · R_t,b
 *
 * `q_b` is what the target bone is DRIVEN with, i.e. `W_t,b = W_t,p · q_b`
 * for the parent `p`. Substituting the same relation for the parent gives
 * `W_t,p⁻¹ · W_d,p = K_p⁻¹`, so
 *
 *     q_b = K_p⁻¹ · c_b · K_b
 *
 * TWO factors, and BOTH are built from the ACCUMULATED world rests. The
 * induction is exact whether or not a bone carries a track: an untracked bone
 * stays at its own rest `R_t,b`, which is `W_d,b·K_b` with the donor likewise
 * at rest — the relation the next bone down assumes.
 *
 * WHY NOT THE LOCAL FORM. Until 2026-09-03 this file used ONE factor built
 * from LOCAL rests, `q = c · d⁻¹·t`. Its derivation held the parent "at its
 * bind orientation" and thereby assumed the two rigs' parent frames agree.
 * They do not, and a local rest is not even a geometric property of a bone:
 * it says how a rigger distributed orientation along the chain, so two
 * skeletons with the SAME world rest can hold wildly different local ones.
 * Measured: `figure/x-bot.fbx` sits 0.0° from the reference at Arm, ForeArm
 * and Hand — and the one-factor form still bent its arms by 9.3°, against
 * 0.0° for a plain copy and 3.0° for the rule above. On the generated
 * characters it cost 15.9° at the arms and, unlike both alternatives, the
 * error depended on the CLIP. The rule here adds nothing of its own: over 20
 * characters × 3 clips × 4 sample times the posed deviation equals the REST
 * deviation to 0.000° and the deformation error is 0.00°.
 *
 * IDENTITY. When the target IS the reference rig every `K` is the identity,
 * `restCorrections` returns an EMPTY map and the caller keeps its tracks
 * verbatim — bit-identical to a 1:1 copy, which is the correct answer there.
 *
 * THE RESTS ARE COMPARED IN THE ROOT BONE'S FRAME, `R̃_b = R_root⁻¹·R_b`, not
 * in the world's. A rig's global attitude is not a body feature — it is how
 * the whole figure stands, and a character is supposed to stand the way the
 * clip stands. Measured over the 20 generated characters, the auto-rigger
 * pitches the hips a mean 4.7° and up to 10.4° FORWARD (>97 % pitch about X,
 * roll under 1°) because the T-pose mesh it read leans that way, and that
 * pitch multiplies on down the whole torso chain: comparing world rests would
 * tip four of them 8–10° further forward than they stand today.
 *
 * In the root frame that attitude divides out, and the consequence is exact:
 * EVERY bone's deformation becomes `M_d,b · G` with ONE constant
 * `G = R_d,root⁻¹`-side rotation `R_d,root·R_t,root⁻¹` — a RIGID rotation of
 * the whole character, no relative distortion anywhere (measured spread over
 * all bones of all 20 characters: 0.0009°). The figure is stood upright as a
 * piece and keeps every joint's own bind relative to its pelvis.
 *
 * Aligning only the root BONE instead does not work and was tried: it takes
 * 1.5° of lean off and puts a 10.4° kink at the pelvis, because the lean sits
 * in the torso chain, not in the one joint.
 *
 * `K̃_root` is the identity by construction (measured 0.00001°), so the root
 * needs no special case — it drops out under the threshold on its own. Its
 * left factor is the armature term `A_t⁻¹·A_d`, the general form of the
 * `hipsRotFix` the 3D client falls back to when no donor rest is available.
 *
 * WHY THIS LIVES HERE. Both renderers bind the library onto CHARACTER rigs:
 * `client3d/src/scene/figures.adaptExternalClips` and the admin's
 * `frontend/src/tabs/characters/Model3DViewer` (which loads a clip FBX and
 * plays it on the loaded character GLB). The correction is geometry both need
 * and must agree on, so it is not allowed to exist twice.
 *
 * three is a PARAMETER, never an import — the admin loads it lazily.
 */
import type { AnimationClip, KeyframeTrack, Object3D, Quaternion } from 'three'

/** The three namespace, as a PARAMETER — a type-only import, so the package
 *  never pulls the library into the admin's main bundle. */
type THREE = typeof import('three')

/**
 * A skeleton's rest pose in WORLD orientations, keyed by normalised bone name:
 * `world` holds `R_b` per bone, `parent` the same value for that bone's PARENT
 * (the armature frame for the root bone, which has no bone above it).
 */
export interface RestPose {
  world: Map<string, Quaternion>
  parent: Map<string, Quaternion>
  /** normalised name of the bone ABOVE each bone — `null` at the root bone,
   *  whose parent is the armature rather than another bone. */
  parentBone: Map<string, string | null>
}

/** `K_p⁻¹` and `K_b` of one bone — the two factors of `q = left·c·right`. */
export interface RestCorrection {
  left: Quaternion
  right: Quaternion
}

/** A bone / track node name reduced to what is comparable across rigs: the
 *  `mixamorig` prefix and any namespace colons are noise, case is not. */
export function normBoneName(name: string): string {
  return name.replace(/^mixamorig:?/i, '').replace(/:/g, '').toLowerCase()
}

/**
 * The REST pose of a skeleton, accumulated down the hierarchy from `root`.
 *
 * Read it off the reference RIG (`/assets/animation-rig`), never off a clip
 * file: an FBX carrying an animation stores its nodes' default transforms at
 * the take's first frame, not at the rest. Measured against the rig, the
 * clip files' node defaults sit a mean 7.6° and up to 100° away (`idle.fbx`,
 * arms down instead of T-pose) — using them as the donor rest would inject
 * the first frame of every clip into every bone.
 *
 * The walk multiplies LOCAL quaternions rather than reading world matrices:
 * a world matrix reflects the pose the object is in right now, and this has
 * to be the rest whether or not a mixer has already touched the skeleton.
 * Nodes above the first bone are walked too — that is how the armature frame
 * reaches the root bone's parent entry.
 */
export function restPoseOf(three: THREE, root: Object3D): RestPose {
  const world = new Map<string, Quaternion>()
  const parent = new Map<string, Quaternion>()
  const parentBone = new Map<string, string | null>()
  const walk = (node: Object3D, above: Quaternion, aboveBone: string | null) => {
    const here = new three.Quaternion().copy(above).multiply(node.quaternion)
    const bone = !!(node as { isBone?: boolean }).isBone
    const key = bone ? normBoneName(node.name) : ''
    if (bone && !world.has(key)) {
      world.set(key, here)
      parent.set(key, above)
      parentBone.set(key, aboveBone)
    }
    for (const child of node.children) walk(child, here, bone ? key : aboveBone)
  }
  walk(root, new three.Quaternion(), null)
  return { world, parent, parentBone }
}

/** the rotation angle of a quaternion, in degrees */
function angleOf(q: Quaternion): number {
  return 2 * Math.acos(Math.min(1, Math.abs(q.w))) * (180 / Math.PI)
}

/**
 * `left = K_p⁻¹` and `right = K_b` per bone (`q = left·c·right`), both built
 * from the ACCUMULATED world rests of donor and target.
 *
 * Bones whose two factors are both under `epsDeg` are LEFT OUT, so a caller
 * that finds no entry keeps its track untouched and pays nothing. That also
 * makes the identity case exact rather than merely close.
 */
export function restCorrections(three: THREE,
                                donor: RestPose,
                                target: Object3D,
                                epsDeg = 0.05): Map<string, RestCorrection> {
  const out = new Map<string, RestCorrection>()
  if (!donor.world.size) return out
  const self = restPoseOf(three, target)
  // Both rests, read in their own rig's ROOT BONE frame — that is what divides
  // the figure's standing attitude out of the comparison.
  const rootRest = (pose: RestPose): Quaternion | undefined => {
    for (const [key, above] of pose.parentBone) if (above === null) return pose.world.get(key)
    return undefined
  }
  const donorRoot = rootRest(donor)
  const targetRoot = rootRest(self)
  const inRootFrame = (root: Quaternion | undefined, q: Quaternion): Quaternion => {
    const out = new three.Quaternion().copy(q)
    return root ? out.premultiply(new three.Quaternion().copy(root).invert()) : out
  }
  const k = new Map<string, Quaternion>()
  for (const [key, targetWorld] of self.world) {
    const donorWorld = donor.world.get(key)
    if (!donorWorld) continue
    k.set(key, inRootFrame(donorRoot, donorWorld).invert()
      .multiply(inRootFrame(targetRoot, targetWorld)))
  }
  for (const [key, right] of k) {
    const above = self.parentBone.get(key) ?? null
    let left: Quaternion
    if (above === null) {
      // the armature frame: A_d⁻¹·A_t, inverted
      const donorParent = donor.parent.get(key)
      const targetParent = self.parent.get(key)
      if (!donorParent || !targetParent) continue
      left = new three.Quaternion().copy(donorParent).invert()
        .multiply(targetParent).invert()
    } else {
      const parentK = k.get(above)
      // a parent the donor does not carry leaves this bone alone
      if (!parentK) continue
      left = parentK.clone().invert()
    }
    if (angleOf(right) > epsDeg || angleOf(left) > epsDeg) out.set(key, { left, right })
  }
  return out
}

/**
 * A quaternion track's values with the correction applied (`q = left·c·right`),
 * or `null` when there is nothing to correct — the caller then keeps the
 * original array, which is what makes the no-op case free AND exact.
 */
export function bindRelativeValues(three: THREE,
                                   values: ArrayLike<number>,
                                   k: RestCorrection | undefined): Float32Array | null {
  if (!k) return null
  const out = new Float32Array(values.length)
  const q = new three.Quaternion()
  for (let i = 0; i + 3 < values.length; i += 4) {
    q.set(values[i], values[i + 1], values[i + 2], values[i + 3])
      .premultiply(k.left).multiply(k.right)
    out[i] = q.x; out[i + 1] = q.y; out[i + 2] = q.z; out[i + 3] = q.w
  }
  return out
}

/**
 * A clone of `clip` whose quaternion tracks are transplanted onto the bind
 * pose the corrections were built for. Position/scale tracks pass through
 * untouched — the hips POSITION is a length, not a rotation, and every
 * consumer scales it its own way.
 *
 * For consumers that bind a clip to a rig as it comes (the admin viewers).
 * `client3d` rebuilds its tracks anyway and uses `bindRelativeValues` inside
 * that loop instead — same arithmetic, one implementation.
 */
export function bindRelativeClip(three: THREE, clip: AnimationClip,
                                 corrections: Map<string, RestCorrection>): AnimationClip {
  if (!corrections.size) return clip
  const tracks: KeyframeTrack[] = []
  let touched = 0
  for (const track of clip.tracks) {
    const dot = track.name.lastIndexOf('.')
    const k = dot > 0 && track.name.slice(dot + 1) === 'quaternion'
      ? corrections.get(normBoneName(track.name.slice(0, dot)))
      : undefined
    const values = bindRelativeValues(three, track.values, k)
    if (!values) { tracks.push(track); continue }
    touched += 1
    tracks.push(new three.QuaternionKeyframeTrack(track.name, track.times, values))
  }
  if (!touched) return clip
  return new three.AnimationClip(clip.name, clip.duration, tracks)
}
