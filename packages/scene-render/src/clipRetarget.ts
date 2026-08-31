/**
 * clipRetarget.ts — READING A LIBRARY CLIP AS A ROTATION AWAY FROM REST.
 *
 * The shared clip library is authored on ONE skeleton: every clip is
 * retargeted onto `shared/models/rig/reference.fbx` by the importer, so a
 * clip's local quaternion tracks are written in THAT rig's rest frame.
 *
 * Copying those tracks onto another rig 1:1 — what both renderers did until
 * 2026-08-31 — sets each bone to the DONOR's local orientation and therefore
 * overwrites whatever the target rig holds in its own bind pose. For a rig
 * whose T-pose stands with the feet splayed 17° outwards, playing a clip
 * turned the feet 17° INWARDS on top of everything else, because the mesh is
 * skinned to that splayed bind and the clip took it away.
 *
 * DERIVATION. All quaternions below are LOCAL (a bone relative to its
 * parent): `d` the donor rest, `c` the clip's value at time t, `t` the target
 * rest, `q` what the target bone should be driven with. What skinning shows
 * is the DEFORMATION `M = W(t) · W(bind)⁻¹` in world space. With the parent
 * held at its bind orientation `W_p`:
 *
 *     donor    M_d = (W_p · c) · (W_p · d)⁻¹ = W_p · c·d⁻¹ · W_p⁻¹
 *     target   M_t = (W_p · q) · (W_p · t)⁻¹ = W_p · q·t⁻¹ · W_p⁻¹
 *
 * The target must be deformed exactly as the donor was — that IS "play the
 * actor's motion on this body" — so `M_t = M_d`, hence `q·t⁻¹ = c·d⁻¹` and
 *
 *     q = c · d⁻¹ · t = c · k       with the CONSTANT   k = d⁻¹ · t
 *
 * The whole transplant is therefore ONE fixed right-multiplication per bone,
 * computed once per rig. The ORDER is not free: `c · k` puts the correction
 * in the BONE's own frame, which is what cancels out of the deformation;
 * `k · c` does not cancel and shears the pose.
 *
 * IDENTITY. When the target IS the reference rig, `t = d`, every `k` is the
 * identity and `restCorrections` returns an EMPTY map — the caller then keeps
 * its tracks verbatim, so the result is bit-identical to the 1:1 copy it
 * replaces. Measured on `shared/models/rig/reference.fbx`: 0 corrections over
 * the 0.05° threshold, and the posed feet land on the same digits.
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

/** A bone / track node name reduced to what is comparable across rigs: the
 *  `mixamorig` prefix and any namespace colons are noise, case is not. */
export function normBoneName(name: string): string {
  return name.replace(/^mixamorig:?/i, '').replace(/:/g, '').toLowerCase()
}

/**
 * The REST pose of a skeleton: normalised bone name → local rest quaternion.
 *
 * Read it off the reference RIG (`/assets/animation-rig`), never off a clip
 * file: an FBX carrying an animation stores its nodes' default transforms at
 * the take's first frame, not at the rest. Measured against the rig, the
 * clip files' node defaults sit a mean 7.6° and up to 100° away (`idle.fbx`,
 * arms down instead of T-pose) — using them as the donor rest would inject
 * the first frame of every clip into every bone.
 */
export function restPoseOf(three: THREE, root: Object3D): Map<string, Quaternion> {
  const out = new Map<string, Quaternion>()
  root.traverse((o) => {
    if (!(o as { isBone?: boolean }).isBone) return
    const key = normBoneName(o.name)
    if (!out.has(key)) out.set(key, new three.Quaternion().copy(o.quaternion))
  })
  return out
}

/**
 * `k = d⁻¹ · t` per bone — the constant that turns a donor-frame clip value
 * into a target-frame one (`q = c · k`).
 *
 * Bones whose two rests agree to within `epsDeg` are LEFT OUT, so a caller
 * that finds no entry keeps its track untouched and pays nothing. That also
 * makes the identity case exact rather than merely close.
 */
export function restCorrections(three: THREE,
                                donorRest: Map<string, Quaternion>,
                                target: Object3D,
                                epsDeg = 0.05): Map<string, Quaternion> {
  const out = new Map<string, Quaternion>()
  if (!donorRest.size) return out
  const seen = new Set<string>()
  target.traverse((o) => {
    if (!(o as { isBone?: boolean }).isBone) return
    const key = normBoneName(o.name)
    if (seen.has(key)) return
    seen.add(key)
    const d = donorRest.get(key)
    if (!d) return
    const k = new three.Quaternion().copy(d).invert().multiply(o.quaternion)
    // the rotation angle of k, in degrees
    const ang = 2 * Math.acos(Math.min(1, Math.abs(k.w))) * (180 / Math.PI)
    if (ang > epsDeg) out.set(key, k)
  })
  return out
}

/**
 * A quaternion track's values with `k` applied (`q = c · k`), or `null` when
 * there is nothing to correct — the caller then keeps the original array,
 * which is what makes the no-op case free AND exact.
 */
export function bindRelativeValues(three: THREE,
                                   values: ArrayLike<number>,
                                   k: Quaternion | undefined): Float32Array | null {
  if (!k) return null
  const out = new Float32Array(values.length)
  const q = new three.Quaternion()
  for (let i = 0; i + 3 < values.length; i += 4) {
    q.set(values[i], values[i + 1], values[i + 2], values[i + 3]).multiply(k)
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
                                 corrections: Map<string, Quaternion>): AnimationClip {
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
