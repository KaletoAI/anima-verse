/**
 * footPlant.ts — THE SHOD FOOT PLANT, per frame, baked once into a clip of a
 * figure that wears a fitted shoe. The ONE routine of both renderers (the 3D
 * client's clip paths, the admin Wardrobe preview); `three` is injected.
 *
 * WHY (P2 fix round, 2026-11-10). A fitted shoe is RIGID on the foot. The
 * extension (`footPose.ts`) stands the bind foot on the shoe, and the shared
 * ground (`clipGround.ts`) puts the FLAT stance of a clip on the floor — but
 * a bare-foot walk clip sweeps the foot −12° … +37° (heel strike … heel off)
 * and the rigid shoe follows it: measured on the spike material, the stiletto
 * tip pierced the floor 17 mm at heel strike, and the sole floated up to
 * 58 mm from mid-stance to heel off, because the extended foot stands so
 * steep that no turn about the ankle can bring the ball down to the floor
 * while the ankle rides the bare clip's leg (the ankle sits 72 mm higher
 * than bare, the ankle→ball chord is 173 mm). A per-clip constant cannot fix
 * either; only a per-frame plant can.
 *
 * THE RULE, per sample frame and side, for a figure whose foot pose matches
 * the shoes it carries (`footPoseMatches`); everything else is left alone:
 *
 *  STANCE is decided by the BARE contacts — the ankle and ball JOINTS of the
 *    UNPOSED clip (the clip before the extension), through the importer's
 *    contact rule `footLock.contactWeights` (height band over each point's
 *    own ground, vertical-speed band). No shoe data decides what stance is.
 *    The foot's weight is the larger of its two points, and the end of every
 *    run of contact decays over `PLANT_FADE_S` into the frames after it
 *    (`fadeRuns`), so the leg never pops at lift-off; the LEVEL weight is the
 *    smaller of the two (both points planted = the bare sole stands flat).
 *  LEVEL — the Foot is turned about the fit's axis (`foot_pose.bones` of the
 *    Foot, carried by the Foot's world rotation) so that the sole's heel and
 *    ball contacts (`foot_pose.contacts`, the collision endpoint rule) stand
 *    level, by the level weight: a bare sole that stands flat wears a shoe
 *    that stands flat.
 *  HOLD — the forepart (ToeBase) is RIGID with the shank except that it may
 *    flex UP at the ball: its world rotation is the stand pose's forepart
 *    under the turned Foot (the bind local times the fit's counter-turn) and,
 *    where that would pitch the ball→toe line below the insole slope α (the
 *    slope the still pose has), it is turned up about the fit's toe axis
 *    until the line is at α again. Through heel off the shank rises while the
 *    forepart stays on the floor, as a sole flexes at the ball; at heel strike
 *    the forepart stays in line (toe up), as a sole cannot bend the other
 *    way. Blended with the clip's own toe by the foot's weight.
 *  THE GROUND — the lowest of the side's contacts after LEVEL and HOLD is
 *    put on the clip's floor by a two-bone leg IK (`twoBoneIk`, the twin of
 *    the importer's foot plant; UpLeg and Leg turn, the knee stays in its
 *    plane, the Foot keeps its turned world rotation): lowered by the foot's
 *    weight when it floats, raised IN FULL when it pierces — a floor is solid
 *    whatever the contact weight. The floor is the figure's bind-sole plane
 *    (`figureBox(probe, fp).min.y` — the BARE body's box the record ships,
 *    garments excluded) lowered by `rootY`, the
 *    root lift the caller adds when it plays the clip (`footPoseLiftM` of
 *    the ground group); the clip is baked for the ground height group.
 *
 * Units: the probe's own (the model's metres); `unitsPerCm` turns them into
 * the centimetres the contact bands are written in (1/100 for a model in
 * metres; `1 / (100 · scale)` in the client, as the foot lock uses).
 *
 * THE PROBE is a figure the caller does not mind posing (a `SkeletonUtils`
 * clone) that arrives in its BIND pose: the bind locals, the rest heights
 * and the still pose are read off it before any clip plays, and every bone
 * is put back as found at the end, so one probe serves a whole library.
 *
 * Side-effect free on the clips: a NEW clip is returned with the four leg
 * tracks of each planted side (UpLeg, Leg, Foot, ToeBase quaternions) on the
 * sample times (the keys of the hips position track, else 30 fps), every
 * other track shared with the input, marked `userData.footPlanted = fsig`.
 * A marked clip, a clip of a foot pose that does not match the probe, a rig
 * without the leg bones or a clip in which no frame is planted comes back
 * unchanged (the last one marked, so nothing re-measures it).
 *
 * Order in a clip path: retarget / bind-relative → `applyFootPose` →
 * `plantFootPose` (this) → `measureClipGround`. The ground measure then
 * reads a planted stance at the floor (its offset is the residual, ≈ 0).
 */
import type { AnimationClip, Bone, KeyframeTrack, Object3D, Quaternion, SkinnedMesh, Vector3 } from 'three'
import { contactWeights, groundHeights } from './footLock'
import type { Tracks, Vec3 } from './footLock'
import { twoBoneIk } from './twoBoneIk'
import type { Quat } from './twoBoneIk'
import { normBoneName } from './clipRetarget'
import { figureBox, inGarment } from './figure'
import { FOOT_POSE_VERSION, footPoseMatches } from './footPose'
import type { FootPose, FootSide } from './footPose'

type Three = typeof import('three')

/** How long a run's last contact weight decays after lift-off, s
 *  (`fadeRuns`): 5 frames at 30 fps. Measured on the walk, 3 frames left the
 *  lift-off frame — whose bare toes still read within 10 mm of the floor —
 *  at +13.7 mm (a quarter of the unplanted float), 5 frames bring it to
 *  +11 and let the shod foot lift over 0.17 s, close to the bare foot's own
 *  0.1 s. */
export const PLANT_FADE_S = 0.15

/** Sample rate for a clip without a hips position track, fps. */
export const PLANT_FALLBACK_FPS = 30

export interface FootPlantOptions {
  /** The constant vertical placement the caller adds when playing the clip
   *  (the shod lift of the ground group), probe units. Default 0. */
  rootY?: number
  /** Probe units per centimetre (1/100 for a model in metres). Default 0.01. */
  unitsPerCm?: number
}

const SIDES: FootSide[] = ['left', 'right']

/** The sample times: the keys of the clip's hips POSITION track, else a
 *  uniform `PLANT_FALLBACK_FPS` over the duration (at least two). */
export function plantSampleTimes(clip: AnimationClip): number[] {
  const hips = clip.tracks.find((t) => {
    const dot = t.name.lastIndexOf('.')
    return dot > 0 && t.name.slice(dot + 1) === 'position' && /hips$/.test(normBoneName(t.name.slice(0, dot)))
  })
  if (hips && hips.times.length >= 2) return Array.from(hips.times)
  const n = Math.max(2, Math.round(clip.duration * PLANT_FALLBACK_FPS) + 1)
  return Array.from({ length: n }, (_, i) => (clip.duration * i) / (n - 1))
}

/**
 * The weights of every run of `w > 0`, each run's last weight decaying OVER
 * THE `F = round(fadeS · fps)` FRAMES AFTER IT: `w'(b + k) = w(b) · (F − k + 1)
 * / (F + 1)`, k = 1 … F, where that is more than the frame's own weight — a
 * run that ends on the take's last frame decays into nothing (a held last
 * frame, a loop seam). Inside a run the weights stay as they are. Why
 * outward and only at the end: the contact rule drops a lifting foot to 0 in
 * ONE frame (its speed band), and a plant that stopped there would pop the
 * leg back up by its whole correction (56 mm on the measured walk); fading
 * the LAST stance frames instead left the heel off floating by 29 mm —
 * exactly the frames the plant is for. Touchdown needs no fade: the height
 * band ramps a landing foot in over several frames, and a pierce is lifted
 * in full anyway. Hand-checked in `scripts/smoke_foot_plant.mjs`.
 */
export function fadeRuns(w: readonly number[], fps: number, fadeS = PLANT_FADE_S): number[] {
  const n = w.length
  const out = w.map((x) => (x > 0 ? x : 0))
  const fade = Math.max(0, Math.round(fadeS * fps))
  for (let b = 0; b < n; b++) {
    if (!(w[b] > 0) || (b + 1 < n && w[b + 1] > 0)) continue   // not a run's end
    for (let k = 1; k <= fade && b + k < n; k++) {
      out[b + k] = Math.max(out[b + k], w[b] * (fade - k + 1) / (fade + 1))
    }
  }
  return out
}

/**
 * The turn δ about unit axis `a` (right hand) that makes the two ends of
 * `d` level — `(R(a, δ)·d).y = 0` — with the smallest |δ|, in radians.
 * `A cos δ + B sin δ + C = 0` with `A = d_y − a_y(a·d)`, `B = (a×d)_y`,
 * `C = a_y(a·d)`; when no δ reaches 0 (the axis too steep for it) the δ
 * that brings `|(R·d).y|` closest to 0 is answered. Hand cases in
 * `scripts/smoke_foot_plant.mjs`: an axis +x and `d = (0, 0.15·sin θ,
 * 0.15·cos θ)` answer +θ (`(R·d).y = 0.15·sin(θ − δ)`); the plant's own
 * `d = heel − ball` points back and answers −θ.
 */
export function levelTurn(a: Vec3, d: Vec3): number {
  const ad = a[0] * d[0] + a[1] * d[1] + a[2] * d[2]
  const C = a[1] * ad
  const A = d[1] - C
  const B = a[2] * d[0] - a[0] * d[2]   // (a × d)_y
  const r = Math.hypot(A, B)
  if (!(r > 1e-12)) return 0
  const phi = Math.atan2(B, A)           // A cos δ + B sin δ = r · cos(δ − φ)
  if (Math.abs(C) > r) {
    // unreachable: the extremum nearest to zero is at δ = φ (r·cos = ±r)
    const cand = [phi, phi + Math.PI, phi - Math.PI]
    return cand.reduce((best, x) => (Math.abs(x) < Math.abs(best) ? x : best))
  }
  const k = Math.acos(-C / r)            // cos(δ − φ) = −C / r
  const cands = [phi + k, phi - k].flatMap((x) => [x, x + 2 * Math.PI, x - 2 * Math.PI])
  return cands.reduce((best, x) => (Math.abs(x) < Math.abs(best) ? x : best))
}

interface LegBones { upper: Object3D; lower: Object3D; foot: Object3D; toe: Object3D | null }

/** One contact, its bone on the probe and its offset in that bone's local frame. */
interface ContactLocal { bone: Object3D; onToe: boolean; local: Vector3; role: 'heel' | 'ball' | 'toe' }

function isBelow(bone: Object3D, ancestor: Object3D): boolean {
  for (let p = bone.parent; p; p = p.parent) if (p === ancestor) return true
  return false
}

const toThree = (three: Three, q: Quat): Quaternion => new three.Quaternion(q[1], q[2], q[3], q[0])

/** Signed pitch of `v` above the horizontal, radians. */
function pitchOf(v: Vector3): number {
  return Math.atan2(v.y, Math.hypot(v.x, v.z))
}

/**
 * Bake the shod foot plant (module docstring) into `posed` — the clip with
 * the extension already applied (`applyFootPose`) — using `bare`, the same
 * clip WITHOUT it, for the stance decision. Returns a new clip, or `posed`
 * itself when there is nothing to do.
 */
export function plantFootPose(three: Three, posed: AnimationClip, bare: AnimationClip, probe: Object3D,
  fp: FootPose | null | undefined, options: FootPlantOptions = {}): AnimationClip {
  if (!fp || fp.version !== FOOT_POSE_VERSION || !fp.source || typeof fp.source.fsig !== 'string') return posed
  if ((posed.userData as { footPlanted?: unknown } | undefined)?.footPlanted) return posed
  if (!footPoseMatches(probe, fp)) return posed
  const unitsPerCm = Number.isFinite(options.unitsPerCm) && (options.unitsPerCm as number) > 0
    ? (options.unitsPerCm as number) : 0.01
  const rootY = Number.isFinite(options.rootY) ? (options.rootY as number) : 0

  probe.updateMatrixWorld(true)
  const byKey = new Map<string, Object3D>()
  let body: SkinnedMesh | null = null
  probe.traverse((o) => {
    if ((o as Bone).isBone) {
      const key = normBoneName(o.name)
      if (!byKey.has(key)) byKey.set(key, o)
    }
    const mesh = o as SkinnedMesh
    if (!body && mesh.isSkinnedMesh && mesh.skeleton && !inGarment(mesh)) body = mesh
  })
  if (!body) return posed
  const skin = body as SkinnedMesh
  const legs = new Map<FootSide, LegBones>()
  for (const side of SIDES) {
    const upper = byKey.get(`${side}upleg`)
    const lower = byKey.get(`${side}leg`)
    const foot = byKey.get(`${side}foot`)
    const toe = byKey.get(`${side}toebase`) ?? null
    if (!upper || !lower || !foot || !upper.parent || !isBelow(lower, upper) || !isBelow(foot, lower)) continue
    if (toe && !isBelow(toe, foot)) continue
    legs.set(side, { upper, lower, foot, toe })
  }
  if (!legs.size) return posed

  // Every bone as found: put back at the end (one probe serves a library).
  const saved = new Map<Object3D, { q: Quaternion; p: Vector3 }>()
  probe.traverse((o) => { if ((o as Bone).isBone) saved.set(o, { q: o.quaternion.clone(), p: o.position.clone() }) })
  const restore = () => {
    for (const [o, s] of saved) { o.quaternion.copy(s.q); o.position.copy(s.p) }
    probe.updateMatrixWorld(true)
  }

  // The contacts' offsets in their bone's local frame — the collision endpoint
  // rule (`jointNowFrom`): `boneInverse · bindMatrix · pos`, constant per bone.
  const boneIndex = new Map<string, number>()
  skin.skeleton.bones.forEach((b, i) => { const k = normBoneName(b.name); if (!boneIndex.has(k)) boneIndex.set(k, i) })
  const contacts = new Map<FootSide, ContactLocal[]>()
  for (const side of SIDES) {
    const leg = legs.get(side)
    if (!leg) continue
    const list: ContactLocal[] = []
    for (const c of fp.contacts?.[side] ?? []) {
      const key = normBoneName(c.bone)
      const bone = byKey.get(key)
      const idx = boneIndex.get(key)
      if (!bone || idx === undefined || !Array.isArray(c.pos) || c.pos.length !== 3) continue
      if (bone !== leg.foot && !isBelow(bone, leg.foot)) continue
      const local = new three.Vector3(c.pos[0], c.pos[1], c.pos[2])
        .applyMatrix4(skin.bindMatrix).applyMatrix4(skin.skeleton.boneInverses[idx])
      list.push({ bone, onToe: !!leg.toe && (bone === leg.toe || isBelow(bone, leg.toe)), local, role: c.role })
    }
    if (list.some((c) => c.role === 'heel') && list.some((c) => c.role === 'ball')) contacts.set(side, list)
  }
  if (!contacts.size) return posed

  // The fit's axes (bone-local, unit) and turns.
  const axisOf = (name: string): Vector3 | null => {
    for (const [n, t] of Object.entries(fp.bones ?? {})) {
      if (normBoneName(n) !== name) continue
      const a = t?.axis
      if (!Array.isArray(a) || a.length !== 3) return null
      const v = new three.Vector3(a[0], a[1], a[2])
      return v.lengthSq() > 1e-24 ? v.normalize() : null
    }
    return null
  }
  const turnOf = (name: string): Quaternion => {
    const q = new three.Quaternion()
    for (const [n, t] of Object.entries(fp.bones ?? {})) {
      if (normBoneName(n) !== name) continue
      const a = axisOf(name)
      if (a && typeof t?.deg === 'number' && Number.isFinite(t.deg)) q.setFromAxisAngle(a, (t.deg * Math.PI) / 180)
    }
    return q
  }

  // Bind readings: the floor, the rest heights of ankle and ball (cm over the
  // bind soles) and, per side, the STAND pose — the toe's local under the fit
  // and the insole slope α of its ball→toe line.
  const bindMinY = figureBox(three, probe, fp).min.y
  const floorY = bindMinY - rootY
  const worldOf = (o: Object3D): Vector3 => o.getWorldPosition(new three.Vector3())
  const contactWorld = (c: ContactLocal): Vector3 => c.local.clone().applyMatrix4(c.bone.matrixWorld)
  const rest: Record<string, number> = {}
  const stand = new Map<FootSide, { toeLocal: Quaternion; alpha: number; footAxis: Vector3 | null; toeAxis: Vector3 | null }>()
  for (const side of SIDES) {
    const leg = legs.get(side)
    if (!leg || !contacts.has(side)) continue
    rest[`${side}foot`] = (worldOf(leg.foot).y - bindMinY) / unitsPerCm
    rest[`${side}toebase`] = ((leg.toe ? worldOf(leg.toe) : worldOf(leg.foot)).y - bindMinY) / unitsPerCm
  }
  for (const side of SIDES) {
    const leg = legs.get(side)
    if (!leg || !contacts.has(side)) continue
    leg.foot.quaternion.multiply(turnOf(`${side}foot`))
    if (leg.toe) leg.toe.quaternion.multiply(turnOf(`${side}toebase`))
  }
  probe.updateMatrixWorld(true)
  for (const side of SIDES) {
    const leg = legs.get(side)
    const list = contacts.get(side)
    if (!leg || !list) continue
    const ball = list.find((c) => c.role === 'ball')
    const toe = list.find((c) => c.role === 'toe')
    const alpha = ball && toe ? pitchOf(contactWorld(toe).sub(contactWorld(ball))) : 0
    stand.set(side, {
      toeLocal: leg.toe ? leg.toe.quaternion.clone() : new three.Quaternion(),
      alpha,
      footAxis: axisOf(`${side}foot`),
      toeAxis: axisOf(`${side}toebase`) ?? axisOf(`${side}foot`),
    })
  }
  restore()

  const times = plantSampleTimes(posed)
  const n = times.length
  const span = times[n - 1] - times[0]
  const fps = span > 0 ? (n - 1) / span : PLANT_FALLBACK_FPS
  const mixer = new three.AnimationMixer(probe)
  const sample = (clip: AnimationClip, visit: (f: number) => void) => {
    const action = mixer.clipAction(clip)
    action.setLoop(three.LoopOnce, 1)
    action.clampWhenFinished = true
    action.play()
    times.forEach((t, f) => {
      action.paused = false
      mixer.setTime(t)
      probe.updateMatrixWorld(true)
      visit(f)
    })
    action.stop()
    mixer.uncacheClip(clip)
  }

  // PASS A — the bare contacts: ankle and ball joints of the unposed clip.
  const tracks: Tracks = {}
  for (const side of contacts.keys()) { tracks[`${side}foot`] = []; tracks[`${side}toebase`] = [] }
  sample(bare, () => {
    for (const side of contacts.keys()) {
      const leg = legs.get(side)!
      const a = worldOf(leg.foot)
      const b = leg.toe ? worldOf(leg.toe) : a
      tracks[`${side}foot`].push([a.x / unitsPerCm, (a.y - bindMinY) / unitsPerCm, a.z / unitsPerCm])
      tracks[`${side}toebase`].push([b.x / unitsPerCm, (b.y - bindMinY) / unitsPerCm, b.z / unitsPerCm])
    }
  })
  const weights = contactWeights(tracks, groundHeights(tracks, rest), fps)
  const footWeight = new Map<FootSide, number[]>()
  const levelWeight = new Map<FootSide, number[]>()
  for (const side of contacts.keys()) {
    const wa = weights[`${side}foot`] ?? []
    const wb = weights[`${side}toebase`] ?? []
    const raw = Array.from({ length: n }, (_, f) => Math.max(wa[f] ?? 0, wb[f] ?? 0))
    const faded = fadeRuns(raw, fps)
    footWeight.set(side, faded)
    levelWeight.set(side, Array.from({ length: n }, (_, f) => Math.min(wa[f] ?? 0, wb[f] ?? 0, faded[f])))
  }
  if (![...footWeight.values()].some((w) => w.some((x) => x > 0))) {
    // No planted frame anywhere: nothing to bake (a pierce needs a contact
    // too — a swing foot under the floor is the clip's business, not a plant's).
    restore()
    const out = new three.AnimationClip(posed.name, posed.duration, [...posed.tracks], posed.blendMode)
    out.userData = { ...(posed.userData ?? {}), footPlanted: fp.source.fsig }
    return out
  }

  // PASS B — the shod frames: joints, world rotations, locals, contacts.
  interface Frame {
    hip: Vec3; knee: Vec3; ankle: Vector3
    wUpperParent: Quaternion; wUpper: Quaternion; wLowerParent: Quaternion; wLower: Quaternion
    wFootParent: Quaternion; wFoot: Quaternion
    local: [Quaternion, Quaternion, Quaternion, Quaternion]
    toeJoint: Vector3 | null
    contacts: Vector3[]
  }
  const frames = new Map<FootSide, Frame[]>()
  for (const side of contacts.keys()) frames.set(side, [])
  const wq = (o: Object3D): Quaternion => o.getWorldQuaternion(new three.Quaternion())
  const asVec = (p: Vector3): Vec3 => [p.x, p.y, p.z]
  sample(posed, () => {
    for (const side of contacts.keys()) {
      const leg = legs.get(side)!
      frames.get(side)!.push({
        hip: asVec(worldOf(leg.upper)), knee: asVec(worldOf(leg.lower)), ankle: worldOf(leg.foot),
        wUpperParent: wq(leg.upper.parent!), wUpper: wq(leg.upper),
        wLowerParent: wq(leg.lower.parent!), wLower: wq(leg.lower),
        wFootParent: wq(leg.foot.parent!), wFoot: wq(leg.foot),
        local: [leg.upper.quaternion.clone(), leg.lower.quaternion.clone(), leg.foot.quaternion.clone(),
          leg.toe ? leg.toe.quaternion.clone() : new three.Quaternion()],
        toeJoint: leg.toe ? worldOf(leg.toe) : null,
        contacts: contacts.get(side)!.map(contactWorld),
      })
    }
  })
  restore()

  // THE PLANT per side and frame → four tracks.
  const out: KeyframeTrack[] = [...posed.tracks]
  const keyTimes = Float32Array.from(times)
  let planted = false
  const replace = (bone: Object3D, values: Float32Array) => {
    const key = normBoneName(bone.name)
    const matches = (t: KeyframeTrack): boolean => {
      const dot = t.name.lastIndexOf('.')
      return dot > 0 && t.name.slice(dot + 1) === 'quaternion' && normBoneName(t.name.slice(0, dot)) === key
    }
    const track = new three.QuaternionKeyframeTrack(`${bone.name}.quaternion`, keyTimes, values)
    const at = out.findIndex(matches)
    if (at < 0) out.push(track)
    else {
      out[at] = track
      for (let i = out.length - 1; i > at; i--) if (matches(out[i])) out.splice(i, 1)
    }
  }
  for (const side of contacts.keys()) {
    const leg = legs.get(side)!
    const list = contacts.get(side)!
    const st = stand.get(side)!
    const wf = footWeight.get(side)!
    const wl = levelWeight.get(side)!
    const fr = frames.get(side)!
    const heelAt = list.findIndex((c) => c.role === 'heel')
    const ballAt = list.findIndex((c) => c.role === 'ball')
    const values = [0, 1, 2, 3].map(() => new Float32Array(n * 4))
    const prev: Array<Quaternion | null> = [null, null, null, null]
    let changed = false
    for (let f = 0; f < n; f++) {
      const F = fr[f]
      let local: Quaternion[] = F.local
      // Where the side's contacts stand this frame, after LEVEL and HOLD.
      let wFoot = F.wFoot
      const points = F.contacts.map((p) => p.clone())
      const w = wf[f]
      if (w > 0 || points.some((p) => p.y < floorY)) {
        // LEVEL: the Foot turned about the fit's axis so heel and ball are level.
        let turn = new three.Quaternion()
        if (st.footAxis && wl[f] > 0) {
          const axisW = st.footAxis.clone().applyQuaternion(F.wFoot).normalize()
          const d = points[heelAt].clone().sub(points[ballAt])
          const delta = levelTurn(asVec(axisW), asVec(d)) * wl[f]
          turn = new three.Quaternion().setFromAxisAngle(axisW, delta)
        }
        wFoot = turn.clone().multiply(F.wFoot)
        const toeJoint = F.toeJoint ? F.toeJoint.clone().sub(F.ankle).applyQuaternion(turn).add(F.ankle) : null
        for (let i = 0; i < points.length; i++) {
          if (list[i].onToe) continue
          points[i].sub(F.ankle).applyQuaternion(turn).add(F.ankle)
        }
        // HOLD: the forepart rigid with the shank, flexed up at the ball only
        // as far as the insole slope α needs, blended by the foot's weight.
        let wToe = wFoot.clone().multiply(F.local[3])   // the clip's toe under the turned foot
        if (leg.toe && toeJoint) {
          const target = wFoot.clone().multiply(st.toeLocal)
          const ball = list[ballAt]
          const toe = list.find((c) => c.role === 'toe')
          if (toe && toe.onToe && ball.onToe && st.toeAxis) {
            const lineAt = (q: Quaternion): Vector3 => toe.local.clone().applyQuaternion(q).sub(ball.local.clone().applyQuaternion(q))
            for (let k = 0; k < 4; k++) {
              const line = lineAt(target)
              const slope = pitchOf(line)
              if (slope >= st.alpha - 1e-6) break
              const axisW = st.toeAxis.clone().applyQuaternion(target).normalize()
              const up = new three.Vector3().crossVectors(axisW, line).y >= 0 ? 1 : -1
              target.premultiply(new three.Quaternion().setFromAxisAngle(axisW, up * (st.alpha - slope)))
            }
          }
          wToe = w >= 1 ? target : wToe.slerp(target, w)
          for (let i = 0; i < points.length; i++) {
            if (!list[i].onToe) continue
            points[i].copy(list[i].local).applyQuaternion(wToe).add(toeJoint)
          }
        }
        // THE GROUND: the lowest contact to the floor — lowered by the weight,
        // raised in full.
        let lowest = Infinity
        for (const p of points) if (p.y < lowest) lowest = p.y
        const dy = floorY - lowest
        const vert = dy > 0 ? dy : w * dy
        const targetAnkle: Vec3 = [F.ankle.x, F.ankle.y + vert, F.ankle.z]
        const ik = twoBoneIk(F.hip, F.knee, asVec(F.ankle), targetAnkle, F.knee)
        const du = toThree(three, ik.upper)
        const dl = toThree(three, ik.lower)
        const dul = dl.clone().multiply(du)
        local = [
          F.wUpperParent.clone().invert().multiply(du.clone().multiply(F.wUpper)),
          du.clone().multiply(F.wLowerParent).invert().multiply(dul.clone().multiply(F.wLower)),
          dul.clone().multiply(F.wFootParent).invert().multiply(wFoot),
          wFoot.clone().invert().multiply(wToe),
        ]
        changed = true
      }
      local.forEach((q, i) => {
        // One hemisphere per track: a sign flip is the same rotation, but the
        // track interpolates component-wise between neighbours.
        const o = q.clone()
        if (prev[i] && o.dot(prev[i]!) < 0) o.set(-o.x, -o.y, -o.z, -o.w)
        o.toArray(values[i], f * 4)
        prev[i] = o
      })
    }
    if (!changed) continue
    planted = true
    replace(leg.upper, values[0])
    replace(leg.lower, values[1])
    replace(leg.foot, values[2])
    if (leg.toe) replace(leg.toe, values[3])
  }
  const result = new three.AnimationClip(posed.name, posed.duration, planted ? out : [...posed.tracks], posed.blendMode)
  result.userData = { ...(posed.userData ?? {}), footPlanted: fp.source.fsig }
  return result
}
