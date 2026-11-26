#!/usr/bin/env node
/**
 * Owner decision 2026-11-25, reworked 2026-11-26 ("the gap from what is really there"): the PAIR HEIGHT rule of
 * `packages/scene-render/src/pairHeight.ts` (who takes a contact's vertical gap, from one sampled loop) and its
 * per-frame application `pairHeightPose.ts`. Every expected number is derived BY HAND below (§ B5a), never recorded.
 *
 * Usage: node scripts/smoke_pair_height.mjs   (no server, no world; bundles scene-render with esbuild, three from
 *        node_modules; [9] also bundles pairHeightPose.ts as of commit f32fd65fc through `git show`)
 *
 * LEGS (x = ±0.10 m, thigh = shin = l = 0.45 m, leg length 0.90, ground 0, ankle at (x, 0.08, 0)):
 *   CROUCH: hip (x, 0.88, 0), knee (x, 0.48, √(0.45² − 0.40²) = √0.0425 = 0.20615528), hips 0.95. The lowest joint is
 *     the ankle (0.08); the ankle is 0 above it (≤ DOWN 0.12·0.90 = 0.108: down), the knee 0.40 (> UP 0.22·0.90 =
 *     0.198: up) → the leg is down (planted), its knee not held. Hip–ankle d = 0.80: interior knee angle
 *     acos((2l² − d²)/(2l²)) = acos(−0.58025) = 125.47°, bend 54.53° ≥ 35° → "bent".
 *   CROUCH_HI: the same with the hip at 0.93 (d = 0.85), knee (x, 0.505, √(0.2025 − 0.180625) = 0.14790199), hips 1.00.
 *   STAND: hip (x, 0.96, 0), knee (x, 0.52, √0.0089 = 0.09433981), hips 1.03, d = 0.88: bend 24.22° < 35° → "standing".
 *   LYING: hips 0.15, hip/knee 0.12, ankle 0.10 → hips 0.05 above the lowest joint (< 0.22): "resting".
 *   CARRIED: ankles 0.50, knees 0.70 → the lowest joint 0.50 above the ground (> 0.35): "free".
 * [1] THE GAP (`pairAxisGap`), root P, unit axis u, opening O:
 *     a) P (0, 1, 0), u (0, 0, 1), O (0, 0.92, 0.15): λ = 0.15/1 = 0.15, Δ = 1 + 0 − 0.92 = 0.08 (the axis 8 cm above).
 *     b) u (0, −0.6, 0.8), O (0, 0.80, 0.20): λ = 0.2·0.8/0.64 = 0.25, Δ = 1 − 0.6·0.25 − 0.80 = 0.05.
 *     c) u (0, −1, 0) (vertical, |u_xz|² = 0), O (0.01, 0.70, 0): λ = ⟨O − P, u⟩ = 0.30, Δ = 1 − 0.30 − 0.70 = 0.
 *     d) O behind the root (0, 0.9, −0.1) with u of a): λ clamps to 0, Δ = 1 − 0.9 = 0.10.
 *     `pairRelationFrame` of the chain [(0,1,0), (0,1.06,0.08)] = u (0, 0.6, 0.8), L 0.10.
 *     `pairNeededBendDeg` of a): atan(0.08/0.15) = 28.0725°; with the part figure 8 cm down: 0°.
 * [2] THE CONTACT PHASE (`pairContactFrame`): frames [a with O at y 0.60 (distance 0.40), a (0.08), null, b (distance
 *     of (0, 0.8, 0.2) from the segment: t = ⟨(0, −0.2, 0.2), u⟩ = 0.12 + 0.16 = 0.28 > L 0.2 → the end (0, 0.88, 0.16):
 *     √(0.0064 + 0.0016) = 0.0894)] → index 1. All null → −1.
 * [3] THE CLASS over the whole loop (`pairRoleClass`): CROUCH ×4 → bent, planted [T, T], knees [F, F]; STAND ×4 →
 *     standing; LYING → resting; CARRIED → free; `fixed` → fixed (nothing read).
 *     A LIFTED LEG: four frames of CROUCH where the RIGHT leg is 0.24 m higher (moved rigidly, length 0.90) in three of them
 *     (0.24 > 0.198: up) → right not planted (1 down < 3 up), left planted.
 *     THE BAND: the right leg 0.15 above the left in every frame (0.108 < 0.15 ≤ 0.198, its knee up): a leg's word is
 *     its lower joint's, max(ankle, knee) with down +1, undecided 0, up −1 → 0 in every frame: down 0 = up 0 → not
 *     planted; the same at 0.14 and 0.16 (a re-measure inside the band cannot flip it). At 0.10 (≤ 0.108) it is.
 *     SCALE-FREE: CROUCH scaled about the ground by 1.094 (every coordinate × 1.094) keeps its class.
 * [4] THE RANGE over the frames (`pairRoleRange`): CROUCH: up = 2l·cos 6° − 0.80 = 0.9·0.99452190 − 0.8 = 0.09506971,
 *     down −0.15 (at −0.15 d = 0.65 > |l1 − l2| + 0.02; the knee at 0.08 + 0.325 = 0.405 ≥ 0.06). CROUCH + CROUCH_HI:
 *     the smaller up wins, 0.89506971 − 0.85 = 0.04506971. STAND: up 0, down −0.15. The others [0, 0].
 *     `ikKnee` with the hip at +0.05 from CROUCH: (0.1, 0.505, 0.14790199).
 * [5] THE PAIR (`pairHeightOffsets`), part b = STAND, receiver a = CROUCH, one frame, a's gap from [1]a with the
 *     opening at y 1 − Δ: Δ 0.08 → b's range downward (0.15) beats a's upward (0.09506971): o_b = −0.08, o_a = 0.
 *     Δ 0.20 → o_b = −0.15, o_a = +0.05, residual 0. Δ 0.30 → o_b −0.15, o_a 0.09506971, residual 0.05493029.
 * [6] THE GROUP: a = CROUCH receives b = LYING (Δ 0.12) and c = STAND (Δ 0.02): minimise (o_a − 0.12)² + (o_a − o_c −
 *     0.02)², o_a ≤ 0.09506971, o_c ∈ [−0.15, 0], o_b = 0: o_a = 0.07, o_c = 0, residuals +0.05 / −0.05.
 * [7] THE DEADBAND: Δ 0.004 (< 0.005) → gap 0, every offset exactly 0, no range computed; a relation whose frames are
 *     all null is left out.
 * [8] APPLIED on a three.js chain (`applyPairHeight`), the legs posed as STAND, lowered by 0.08: d = 0.80 →
 *     knee (0.1, 0.48, √0.0425 = 0.20615528) (the crouch knee), the ankle stays (< 1e-9 m), the foot keeps its world
 *     rotation; hips 1.03 − 0.08 = 0.95. An offset of 0 touches nothing.
 * [9] THE REAL CALL ORDER (the /play finding: the planted ankle ROSE by the offset). A three.js AnimationMixer plays a
 *     CONSTANT clip (hips (0, 1, 0); thighs turned 0.4 rad, shins −0.8 rad about x) with timeScale 0 — the mixer writes
 *     a value only when it changed, so from the second frame on it writes nothing. Hips bind (0, 1, 0), thigh at
 *     (±0.1, −0.05, 0), shin 0.45, foot 0.42 below. Clip ankle height: 0.95 − 0.45·cos 0.4 − 0.42·cos(0.4 − 0.8)
 *     = 0.95 − 0.87·0.92106099 = 0.14867694. Per frame: mixer.update(1/60) → matrices → poser(−0.08, [left]).
 *     Expect for four frames: the left ankle 0.14867694 (held), the right 0.06867694, the hips 0.92 (±1e-6: the clip's
 *     keyframes are float32); then
 *     poser(0) puts everything back: left 0.14867694, right 0.14867694, hips 1.0. Fails on the poser of commit
 *     f32fd65fc (it put back only the hips): there the held ankle climbs 0.08 per frame (≥ 0.05 above the clip by the
 *     second frame — asserted, so the proof stays honest).
 *
 * VECTOR: shared/test-vectors/pair_scale.json carries [1], [2], [3], [4], [5], [6], [7] (cases H[…]) as the functions
 * pairAxisGap / pairContactFrame / pairRoleClass / pairRoleRange / ikKnee / pairHeightOffsets for the native client;
 * scripts/smoke_pair_scale.mjs replays the file.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const THREE_URL = pathToFileURL(join(ROOT, 'node_modules/three/build/three.module.js')).href
async function bundle(contents, resolveDir) {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-height-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents, resolveDir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'b.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'b.mjs')
    // one three.js instance for the bundle and this script
    await writeFile(file, built.outputFiles[0].text.replace(/from "three"/g, `from "${THREE_URL}"`), 'utf8')
    return await import(pathToFileURL(file).href)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const S = await bundle("export * from '@anima/scene-render';", join(ROOT, 'client3d'))
const THREE = await import(THREE_URL)
let n = 0
const ok = (label) => { n++; console.log('  ok', label) }
const near = (got, want, eps, label) => assert.ok(Math.abs(got - want) <= eps, `${label}: ${got} vs ${want}`)

const leg = (x, hipY, kneeY, kneeZ, ankleY = 0.08) => ({ hip: [x, hipY, 0], knee: [x, kneeY, kneeZ], ankle: [x, ankleY, 0] })
const frame = (hipsM, l, r) => ({ groundM: 0, hipsM, legs: [l, r] })
const CROUCH = frame(0.95, leg(0.1, 0.88, 0.48, Math.sqrt(0.0425)), leg(-0.1, 0.88, 0.48, Math.sqrt(0.0425)))
const CROUCH_HI = frame(1.0, leg(0.1, 0.93, 0.505, Math.sqrt(0.021875)), leg(-0.1, 0.93, 0.505, Math.sqrt(0.021875)))
const STAND = frame(1.03, leg(0.1, 0.96, 0.52, Math.sqrt(0.0089)), leg(-0.1, 0.96, 0.52, Math.sqrt(0.0089)))
const LYING = frame(0.15, leg(0.1, 0.12, 0.12, 0.45, 0.10), leg(-0.1, 0.12, 0.12, 0.45, 0.10))
const CARRIED = frame(1.2, leg(0.1, 1.1, 0.7, 0.2, 0.5), leg(-0.1, 1.1, 0.7, 0.2, 0.5))
const role = (...frames) => ({ frames })
const UP = 0.9 * Math.cos(6 * Math.PI / 180) - 0.8
/** The right leg moved up rigidly by dy (hip, knee and ankle: its length stays 0.90). */
const lift = (f, dy) => ({ ...f, legs: [f.legs[0], { hip: [f.legs[1].hip[0], f.legs[1].hip[1] + dy, f.legs[1].hip[2]], knee: [f.legs[1].knee[0], f.legs[1].knee[1] + dy, f.legs[1].knee[2]],
  ankle: [f.legs[1].ankle[0], f.legs[1].ankle[1] + dy, f.legs[1].ankle[2]] }] })
/** One relation frame of [1]a with the opening Δ below the axis. */
const relFrame = (gap) => ({ root: [0, 1, 0], axis: [0, 0, 1], lengthM: 0.2, opening: [0, 1 - gap, 0.15] })

// [1]
{
  near(S.pairAxisGap({ root: [0, 1, 0], axis: [0, 0, 1], lengthM: 0.2, opening: [0, 0.92, 0.15] }), 0.08, 1e-12, 'a')
  near(S.pairAxisGap({ root: [0, 1, 0], axis: [0, -0.6, 0.8], lengthM: 0.2, opening: [0, 0.80, 0.20] }), 0.05, 1e-12, 'b')
  near(S.pairAxisGap({ root: [0, 1, 0], axis: [0, -1, 0], lengthM: 0.4, opening: [0.01, 0.70, 0] }), 0, 1e-12, 'c')
  near(S.pairAxisGap({ root: [0, 1, 0], axis: [0, 0, 1], lengthM: 0.2, opening: [0, 0.9, -0.1] }), 0.10, 1e-12, 'd')
  const f = S.pairRelationFrame([[0, 1, 0], [0, 1.06, 0.08]], [0, 0, 0])
  near(f.axis[1], 0.6, 1e-12, 'u y'); near(f.axis[2], 0.8, 1e-12, 'u z'); near(f.lengthM, 0.1, 1e-12, 'L')
  assert.equal(S.pairRelationFrame([[0, 1, 0]], [0, 0, 0]), null)
  const fa = { root: [0, 1, 0], axis: [0, 0, 1], lengthM: 0.2, opening: [0, 0.92, 0.15] }
  near(S.pairNeededBendDeg(fa), Math.atan(0.08 / 0.15) * 180 / Math.PI, 1e-9, 'bend'); near(S.pairNeededBendDeg(fa), 28.0725, 1e-4, 'bend hand')
  near(S.pairNeededBendDeg(fa, -0.08, 0), 0, 1e-6, 'bend 0')
  ok('[1] the gap: 0.08 (level axis), 0.05 (tilted), 0 (vertical), 0.10 (behind the root); bend 28.07° → 0° at o_p −0.08')
}
// [2]
{
  const far = { root: [0, 1, 0], axis: [0, 0, 1], lengthM: 0.2, opening: [0, 0.60, 0.15] }
  const a = { root: [0, 1, 0], axis: [0, 0, 1], lengthM: 0.2, opening: [0, 0.92, 0.15] }
  const b = { root: [0, 1, 0], axis: [0, -0.6, 0.8], lengthM: 0.2, opening: [0, 0.80, 0.20] }
  near(S.pairAxisDistance(b), Math.sqrt(0.008), 1e-12, 'b distance')
  assert.equal(S.pairContactFrame([far, a, null, b]), 1)
  assert.equal(S.pairContactFrame([null, null]), -1)
  ok('[2] the contact phase: the frame nearest the straight segment (index 1); none → −1')
}
// [3]
{
  const c = (r) => { const x = S.pairRoleClass(r); return [x.stance, x.planted, x.kneeHeld] }
  assert.deepEqual(c(role(CROUCH, CROUCH, CROUCH, CROUCH)), ['bent', [true, true], [false, false]])
  assert.deepEqual(c(role(STAND, STAND, STAND, STAND))[0], 'standing')
  assert.deepEqual(c(role(LYING))[0], 'resting')
  assert.deepEqual(c(role(CARRIED))[0], 'free')
  assert.deepEqual(c({ frames: [CROUCH], fixed: true }), ['fixed', [false, false], [false, false]])
  assert.deepEqual(c(role(lift(CROUCH, 0.24), lift(CROUCH, 0.24), CROUCH, lift(CROUCH, 0.24))), ['bent', [true, false], [false, false]])
  for (const dy of [0.14, 0.15, 0.16]) assert.deepEqual(c(role(lift(CROUCH, dy), lift(CROUCH, dy)))[1], [true, false], `band ${dy}`)
  assert.deepEqual(c(role(lift(CROUCH, 0.10)))[1], [true, true])
  const sc = (f, k) => ({ groundM: 0, hipsM: f.hipsM * k, legs: f.legs.map((l) => ({ hip: l.hip.map((v) => v * k), knee: l.knee.map((v) => v * k), ankle: l.ankle.map((v) => v * k) })) })
  assert.deepEqual(c(role(sc(lift(CROUCH, 0.15), 1.094))), c(role(lift(CROUCH, 0.15))))
  ok('[3] class over the loop: bent / standing / resting / free / fixed; a leg up in 3 of 4 frames is not planted; the band 0.108..0.198 never flips; scale-free')
}
// [4]
{
  const r = S.pairRoleRange(role(CROUCH, CROUCH))
  assert.equal(r.stance, 'bent'); near(r.up, UP, 1e-9, 'up'); near(UP, 0.09506971, 1e-8, 'up hand'); near(r.down, -0.15, 1e-12, 'down')
  const r2 = S.pairRoleRange(role(CROUCH, CROUCH_HI))
  near(r2.up, 0.9 * Math.cos(6 * Math.PI / 180) - 0.85, 1e-9, 'min up'); near(r2.up, 0.04506971, 1e-8, 'min up hand')
  const s = S.pairRoleRange(role(STAND)); assert.equal(s.stance, 'standing'); assert.equal(s.up, 0); near(s.down, -0.15, 1e-12, 'stand')
  for (const f of [LYING, CARRIED]) { const x = S.pairRoleRange(role(f)); assert.equal(x.up, 0); assert.equal(x.down, 0) }
  const k = S.ikKnee([0.1, 0.93, 0], [0.1, 0.53, Math.sqrt(0.0425)], [0.1, 0.13, 0], [0.1, 0.08, 0])
  near(k[1], 0.505, 1e-12, 'knee y'); near(k[2], 0.14790199, 1e-8, 'knee z')
  ok(`[4] ranges: crouch up ${r.up.toFixed(8)}, down −0.15; the smaller up of two frames (0.04506971); standing lowers only`)
}
// [5] [6] [7]
const one = (key, part, receiver, gap) => ({ key, part, receiver, frames: [relFrame(gap)] })
{
  const run = (gap) => S.pairHeightOffsets({ roles: { a: role(CROUCH), b: role(STAND) }, relations: [one('b>a:channel', 'b', 'a', gap)] })
  let s = run(0.08)
  near(s.gaps['b>a:channel'], 0.08, 1e-12, 'gap'); near(s.offsets.b, -0.08, 1e-12, 'b'); assert.equal(s.offsets.a, 0)
  assert.equal(s.contactFrames['b>a:channel'], 0)
  s = run(0.20); near(s.offsets.b, -0.15, 1e-12, 'b'); near(s.offsets.a, 0.05, 1e-12, 'a'); near(s.residuals['b>a:channel'], 0, 1e-12, 'r')
  s = run(0.30); near(s.offsets.a, UP, 1e-9, 'a max'); near(s.residuals['b>a:channel'], 0.05493029, 1e-8, 'res')
  ok('[5] pair: Δ 0.08 → b −0.08 alone; 0.20 → −0.15 / +0.05; 0.30 → residual 0.05493029')
}
{
  const s = S.pairHeightOffsets({ roles: { a: role(CROUCH), b: role(LYING), c: role(STAND) },
    relations: [one('b>a:mouth', 'b', 'a', 0.12), one('c>a:channel', 'c', 'a', 0.02)] })
  near(s.offsets.a, 0.07, 1e-12, 'o_a'); assert.equal(s.offsets.b, 0); assert.equal(s.offsets.c, 0)
  near(s.residuals['b>a:mouth'], 0.05, 1e-12, 'rb'); near(s.residuals['c>a:channel'], -0.05, 1e-12, 'rc')
  ok('[6] group: o_a 0.07, o_b = o_c = 0, residuals ±0.05')
}
{
  const s = S.pairHeightOffsets({ roles: { a: role(CROUCH), b: role(STAND) },
    relations: [one('b>a:channel', 'b', 'a', 0.004), { key: 'b>a:mouth', part: 'b', receiver: 'a', frames: [null] }] })
  assert.equal(s.gaps['b>a:channel'], 0); assert.equal(s.offsets.a, 0); assert.equal(s.offsets.b, 0)
  assert.deepEqual(s.ranges, {}); assert.ok(!('b>a:mouth' in s.gaps))
  ok('[7] deadband: Δ 4 mm → 0, offsets exactly 0, no range; an unresolved relation is left out')
}
// [8]
{
  const mk = (name, parent, p) => { const b = new THREE.Bone(); b.name = name; b.position.set(...p); parent?.add(b); return b }
  const root = new THREE.Group()
  const hips = mk('mixamorig:Hips', null, [0, 1.03, 0]); root.add(hips)
  const up = mk('mixamorig:LeftUpLeg', hips, [0.1, -0.07, 0])
  const lo = mk('mixamorig:LeftLeg', up, [0, -0.44, Math.sqrt(0.0089)])
  const ft = mk('mixamorig:LeftFoot', lo, [0, -0.44, -Math.sqrt(0.0089)])
  root.updateMatrixWorld(true)
  const rig = S.pairHeightRigOf(root)
  const ankle0 = ft.getWorldPosition(new THREE.Vector3()), foot0 = ft.getWorldQuaternion(new THREE.Quaternion())
  S.applyPairHeight(THREE, rig, -0.08, [true, true])
  root.updateMatrixWorld(true)
  const knee = lo.getWorldPosition(new THREE.Vector3())
  assert.ok(ft.getWorldPosition(new THREE.Vector3()).distanceTo(ankle0) < 1e-9, 'ankle held')
  near(hips.getWorldPosition(new THREE.Vector3()).y, 0.95, 1e-12, 'hips'); near(knee.y, 0.48, 1e-9, 'knee y'); near(knee.z, Math.sqrt(0.0425), 1e-9, 'knee z')
  assert.ok(ft.getWorldQuaternion(new THREE.Quaternion()).angleTo(foot0) < 1e-9, 'foot turned')
  const p = hips.position.clone(); S.applyPairHeight(THREE, rig, 0, [true]); assert.ok(hips.position.equals(p))
  ok('[8] applied: hips 0.95, knee (0.48, 0.20615528), the planted ankle and the foot stay; 0 touches nothing')
}
// [9]
async function mixerRun(P) {
  const mk = (name, parent, pos) => { const b = new THREE.Bone(); b.name = name; b.position.set(...pos); parent.add(b); return b }
  const fig = new THREE.Group()
  const hips = mk('mixamorigHips', fig, [0, 1.0, 0])
  const feet = {}
  for (const [side, x] of [['Left', 0.1], ['Right', -0.1]]) {
    const u = mk(`mixamorig${side}UpLeg`, hips, [x, -0.05, 0]), l = mk(`mixamorig${side}Leg`, u, [0, -0.45, 0])
    feet[side] = mk(`mixamorig${side}Foot`, l, [0, -0.42, 0])
  }
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.4, 0, 0)), qk = new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.8, 0, 0))
  const tracks = [new THREE.VectorKeyframeTrack('mixamorigHips.position', [0, 1], [0, 1, 0, 0, 1, 0])]
  for (const s of ['Left', 'Right']) {
    tracks.push(new THREE.QuaternionKeyframeTrack(`mixamorig${s}UpLeg.quaternion`, [0, 1], [...q.toArray(), ...q.toArray()]))
    tracks.push(new THREE.QuaternionKeyframeTrack(`mixamorig${s}Leg.quaternion`, [0, 1], [...qk.toArray(), ...qk.toArray()]))
  }
  const mixer = new THREE.AnimationMixer(fig)
  const action = mixer.clipAction(new THREE.AnimationClip('pair', 1, tracks)); action.play(); action.timeScale = 0
  const pose = P.pairHeightPoser(THREE, P.pairHeightRigOf(fig))
  const y = (o) => o.getWorldPosition(new THREE.Vector3()).y
  const frames = []
  mixer.update(0); fig.updateMatrixWorld(true)
  for (let i = 0; i < 4; i++) {
    mixer.update(1 / 60); fig.updateMatrixWorld(true)
    pose(-0.08, [true, false]); fig.updateMatrixWorld(true)
    frames.push([y(feet.Left), y(feet.Right), y(hips)])
  }
  mixer.update(1 / 60); fig.updateMatrixWorld(true); pose(0, []); fig.updateMatrixWorld(true)
  return { frames, back: [y(feet.Left), y(feet.Right), y(hips)] }
}
{
  const ANKLE = 0.95 - 0.87 * Math.cos(0.4)
  near(ANKLE, 0.14867694, 1e-8, 'clip ankle hand')
  const now = await mixerRun(S)
  for (const [i, [l, r, h]] of now.frames.entries()) {
    near(l, ANKLE, 1e-6, `held ankle frame ${i}`); near(r, ANKLE - 0.08, 1e-6, `free ankle frame ${i}`); near(h, 0.92, 1e-6, `hips ${i}`)
  }
  near(now.back[0], ANKLE, 1e-6, 'back L'); near(now.back[1], ANKLE, 1e-6, 'back R'); near(now.back[2], 1.0, 1e-6, 'back hips')
  // the poser as of f32fd65fc (explicit commit, never HEAD): the held ankle climbs
  const oldSrc = execFileSync('git', ['show', 'f32fd65fc:packages/scene-render/src/pairHeightPose.ts'], { cwd: ROOT, encoding: 'utf8' })
  const old = await bundle(oldSrc, join(ROOT, 'packages/scene-render/src'))
  const was = await mixerRun(old)
  assert.ok(was.frames[1][0] - ANKLE >= 0.05, `the old poser held the ankle (${was.frames[1][0]})`)
  ok(`[9] real call order (constant clip, timeScale 0): held ankle ${(ANKLE * 1000).toFixed(2)} mm every frame, free −80 mm, hips 0.92; back to the clip at 0 — the poser of f32fd65fc let it climb to ${(was.frames[3][0] * 1000).toFixed(1)} mm`)
}
console.log(`smoke_pair_height: ${n} ok`)
