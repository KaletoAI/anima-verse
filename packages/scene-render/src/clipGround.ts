/**
 * clipGround.ts — WHERE A CLIP PUTS THE FIGURE OVER THE GROUND, measured once
 * per clip on the figure's own skinning. The ONE ground rule of both
 * renderers: the 3D client applies it while a terrain move clip plays
 * (`client3d/src/scene/clipGround.ts` delegates here), the admin Wardrobe
 * preview while it shows a shod figure on its floor grid.
 *
 * THE BARE RULE (the swim finding, acceptance round 2026-08-13, finding 3).
 * A figure is anchored ONCE, in its BIND pose — soles on y = 0 — and every
 * clip plays against that anchor. A clip authored on a line of its own
 * (`swim.fbx`, a water line) holds the body +0.26 … +0.32 m over it. So the
 * lowest body point of every clip is measured once and stored as the clip's
 * `groundOffset`, and the caller decides when the ground is the reference.
 * NEVER NEGATIVE (`groundOffsetOf`): a clip that dips BELOW the bind pose (a
 * crouch, a lunge planting a knee under the sole plane) is authored on the
 * floor already and is not lifted out of it — a lift would show as feet over
 * the ground on every step of a walk cycle.
 *
 * THE SHOD RULE (P2 fix round, 2026-11-10). A fitted shoe is RIGID on the
 * foot and its root lift was solved in the straight-legged bind pose. Every
 * clip bends the knees a little, and a bare foot has a reserve for that —
 * the generated bind feet stand heel-up (23–27 mm on the measured
 * character), so a clip that flattens the foot about an ankle 8 mm lower
 * still keeps the bare sole over the floor — while the rigid sole under the
 * same ankle sinks: measured, the idle clip put the sole 8.6 mm under the
 * floor with its pitch already right, a flat-foot walk frame 20 mm. So for
 * a figure whose foot pose matches the shoes it carries, the ground is
 * measured ON THE SOLE and the offset is SIGNED (`soleGroundOffsetOf`): the
 * raise the bare rule refuses is exactly what the fit's own lift does for
 * the bind pose. The sole is the foot pose's contacts (heel tip, ball, toe
 * tip per side — the collision endpoint rule, `footContactsNow`), read in
 * the same frames as the body samples; the shoe meshes are sampled like any
 * skinned mesh but can only confirm them.
 *
 * STANCE, for a sweeping clip. A walk pitches the bare foot −12° … +37°
 * (heel strike … heel off) and the rigid shoe follows it, so its lowest
 * frame (the stiletto tip at heel strike) is no ground: grounding on it
 * floats the whole stance by 36 mm. The ground is where the sole STANDS
 * FLAT: the frames in which a side's heel and ball contacts are level within
 * `SOLE_LEVEL_M` are that clip's stance, and the offset is the lowest sole
 * point over them (never the heel strike, never the heel off). A clip with
 * no level frame (dangling feet, tiptoe) falls back to all frames. The
 * heel-strike pierce and the heel-off float of a walk are NOT this
 * measure's to fix — a per-clip constant cannot — they need a per-frame
 * foot plant (Task 19 / follow-up).
 *
 * `rootY` is the constant vertical placement the caller will add when it
 * plays these clips on this figure (the shod lift of the ground height
 * group, an admin preview's hips drop): it enters the sample arithmetic, so
 * the stored offset is right for the figure AS PLACED. The unit is the
 * figure's own metre: the measurement runs on the unscaled template, so a
 * consumer that scales its instance scales the offset with it.
 *
 * THE MEASUREMENT IS THE SKINNING, not the skeleton: vertices through
 * `SkinnedMesh.getVertexPosition` over `GROUND_SAMPLE_FRAMES` frames, spread
 * over all skinned meshes with one stride (`GROUND_SAMPLE_VERTICES`). The
 * anchor is `figureBox(probe, fp).min.y` — the bind box WITHOUT garment
 * subtrees: the shoes hang off the un-extended bind foot and would lower it;
 * for a matching record the BARE body's box the server shipped (the served
 * body is cut under the shoe).
 * The caller hands in a PROBE it does not mind posing (a `SkeletonUtils`
 * clone in the client; the preview's own figure before it plays), because
 * the mixer poses a skeleton. `three` is injected, never imported.
 */
import type { AnimationClip, Object3D, SkinnedMesh, Vector3 } from 'three'
import { figureBox } from './figure'
import { footContactsNow, footPoseMatches } from './footPose'
import type { FootPose, FootSide } from './footPose'

type Three = typeof import('three')

/** Frames a clip is sampled at, evenly over its whole duration (start and end
 *  both included, so it is this many + 1 poses). 24 is the rate the retarget
 *  path already samples at — a swimming stroke has no detail under 1/24 s. */
export const GROUND_SAMPLE_FRAMES = 24

/** Vertex budget per pose, spread over ALL skinned meshes of the model with one
 *  stride. A full mesh is 20 000 vertices and 20 clips are 500 poses: sampling
 *  every vertex would be ten million skinning evaluations on a load path, for a
 *  number whose consumer is a centimetre-scale drop. The stride costs at most
 *  the local mesh resolution (millimetres to a centimetre on a body). */
export const GROUND_SAMPLE_VERTICES = 1024

/** A side's sole counts as standing flat when its heel and ball contacts are
 *  within this of each other in height — 10 mm over the ~13 cm between them
 *  is 4.4°; the fitted stand itself reads them within 1 mm. */
export const SOLE_LEVEL_M = 0.01

/**
 * The drop a clip needs so its lowest body point reaches the ground, from the
 * two measured heights — the bare rule, hand-checked in
 * `client3d/scripts/smoke_clip_ground.mjs` and `scripts/smoke_clip_ground_sole.mjs`.
 * Never negative (module docstring); non-finite readings (a clip with no
 * vertices sampled, an empty mesh) are no measurement and answer 0.
 */
export function groundOffsetOf(clipMinY: number, bindMinY: number): number {
  const drop = clipMinY - bindMinY
  return Number.isFinite(drop) && drop > 0 ? drop : 0
}

/**
 * The shod rule: the signed distance of the sole's standing height over the
 * anchor — positive lowers the figure, negative RAISES it (module
 * docstring). Non-finite → 0, as above.
 */
export function soleGroundOffsetOf(soleMinY: number, bindMinY: number): number {
  const drop = soleMinY - bindMinY
  return Number.isFinite(drop) ? drop : 0
}

/** The offset a clip carries, in the figure's metres — 0 for every clip that was
 *  never measured (a model's own embedded clips, a retargeted borrow). */
export function clipGroundOffset(clip: AnimationClip): number {
  const raw = (clip.userData as { groundOffset?: unknown } | undefined)?.groundOffset
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
}

export interface ClipGroundOptions {
  /** The figure's foot pose; the shod rule applies when it matches the shoes
   *  the probe carries (`footPoseMatches`), else the bare rule. */
  footPose?: FootPose | null
  /** The constant vertical placement the caller adds when playing these
   *  clips (shod lift, hips drop …), in the probe's units. Default 0. */
  rootY?: number
}

const SIDES: FootSide[] = ['left', 'right']

/**
 * Measure `groundOffset` for every clip on `probe` (module docstring) and
 * store it on the clip (`clip.userData.groundOffset`). The probe IS posed.
 * A probe without a skinned mesh (static props, the animal rigs that walk
 * procedurally) is left alone: there is no body to measure, and the clips
 * keep the 0 they started with.
 */
export function measureClipGround(three: Three, clips: readonly AnimationClip[], probe: Object3D,
  options: ClipGroundOptions = {}): void {
  if (!clips.length) return
  probe.updateMatrixWorld(true)
  const skins: SkinnedMesh[] = []
  probe.traverse((o) => {
    if ((o as SkinnedMesh).isSkinnedMesh) skins.push(o as SkinnedMesh)
  })
  if (!skins.length) return
  const rootY = Number.isFinite(options.rootY) ? (options.rootY as number) : 0
  const fp = options.footPose && footPoseMatches(probe, options.footPose) ? options.footPose : null
  // The anchor the consumer uses: the figure's BIND box, garments excluded
  // (`figureBox` reads a skinned mesh's geometry box, the bind pose whatever
  // the bones are doing) — the same y = 0 the figure stands on.
  const bindMinY = figureBox(three, probe, fp).min.y
  const total = skins.reduce((n, s) => n + s.geometry.attributes.position.count, 0)
  const stride = Math.max(1, Math.ceil(total / GROUND_SAMPLE_VERTICES))
  const mixer = new three.AnimationMixer(probe)
  const v = new three.Vector3()
  const contacts: Record<FootSide, Vector3[]> = { left: [], right: [] }
  const roleIndex = (side: FootSide, role: 'heel' | 'ball'): number =>
    fp ? (fp.contacts?.[side] ?? []).findIndex((c) => c.role === role) : -1
  for (const clip of clips) {
    const action = mixer.clipAction(clip)
    action.play()
    let allMin = Infinity
    let stanceMin = Infinity
    for (let f = 0; f <= GROUND_SAMPLE_FRAMES; f++) {
      mixer.setTime((clip.duration * f) / GROUND_SAMPLE_FRAMES)
      probe.updateMatrixWorld(true)
      let bodyMin = Infinity
      for (const skin of skins) {
        const count = skin.geometry.attributes.position.count
        for (let i = 0; i < count; i += stride) {
          skin.getVertexPosition(i, v)
          skin.localToWorld(v)
          if (v.y < bodyMin) bodyMin = v.y
        }
      }
      if (bodyMin < allMin) allMin = bodyMin
      if (!fp) continue
      footContactsNow(three, probe, fp, contacts)
      for (const side of SIDES) {
        const list = contacts[side]
        if (!list.length) continue
        let soleMin = Infinity
        for (const c of list) if (c.y < soleMin) soleMin = c.y
        if (soleMin < allMin) allMin = soleMin
        // STANCE: this side's heel and ball contacts are level (module docstring).
        const heel = roleIndex(side, 'heel')
        const ball = roleIndex(side, 'ball')
        if (heel < 0 || ball < 0 || !list[heel] || !list[ball]) continue
        if (Math.abs(list[heel].y - list[ball].y) > SOLE_LEVEL_M) continue
        const frameMin = Math.min(soleMin, bodyMin)
        if (frameMin < stanceMin) stanceMin = frameMin
      }
    }
    action.stop()
    mixer.uncacheClip(clip)
    const offset = fp
      ? soleGroundOffsetOf((Number.isFinite(stanceMin) ? stanceMin : allMin) + rootY, bindMinY)
      : groundOffsetOf(allMin + rootY, bindMinY)
    ;(clip.userData as Record<string, unknown>).groundOffset = offset
  }
}
