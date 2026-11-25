#!/usr/bin/env node
/**
 * Owner decision 2026-11-25 ("build the vertical size compensation"): the PAIR HEIGHT rule of
 * `packages/scene-render/src/pairHeight.ts` (who takes a contact's vertical gap) and its per-frame application
 * `pairHeightPose.ts`. Every expected number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_pair_height.mjs   (no server, no world; bundles scene-render with esbuild, three from
 *        node_modules)
 *
 * LEGS (both sides alike, x = ±0.10 m, thigh = shin = l = 0.45 m, support 0, ankle at (x, 0.08, 0)):
 *   CROUCH: hip (x, 0.88, 0), knee (x, 0.48, √(0.45² − 0.40²) = √0.0425 = 0.20615528), hips 0.95. The ankle (0.08) is
 *     planted (≤ 0.16), the knee is not (0.48 > 0.13). Hip–ankle d = 0.80: interior knee angle
 *     acos((2l² − d²)/(2l²)) = acos((0.405 − 0.64)/0.405) = acos(−0.58025) = 125.47°, bend 54.53° ≥ 35° → "bent".
 *   STAND: hip (x, 0.96, 0), knee (x, 0.52, √(0.2025 − 0.1936) = 0.09433981), d = 0.88: acos((0.405 − 0.7744)/0.405)
 *     = acos(−0.91210) = 155.78°, bend 24.22° < 35° → "standing" (lowering only).
 * [1] THE GAP (`pairHeightGap`): both on the floor, 1.86 m on 1.70 m, h_c 0.852 m: (1.86/1.70 − 1)·0.852 = 0.16/1.70 ·
 *     0.852 = 0.08018824 m = 80.2 mm (the measured miss of the diagnosis). 1.65 m receiving, 1.86 m entering,
 *     h_c 0.875: (0.21/1.70)·0.875 = 0.10808824. On a bed (both supports 0.50, a_p = 1.1, a_r = 1, h_c 0.90):
 *     0.5 + 1.1·0.4 − 0.9 = 0.04. Equal scales on the floor: exactly 0.
 * [2] THE HIP RAISE AND ITS CLAMP (CROUCH, a = 1): the IK keeps the ankle, so the hip may rise until the leg keeps only
 *     MIN_BEND 12°: d_max = 2l·cos 6° = 0.9·0.99452190 = 0.89506971 → up = 0.89506971 − 0.80 = 0.09506971 (bisection
 *     ±1e-9). Down: at −0.15 d = 0.65 (no fold), the knee at 0.08 + 0.325 = 0.405 ≥ 0.06 → down = −MAX = −0.15.
 *     The knee at +0.05 (d = 0.85): (x, 0.08 + 0.425, √(0.2025 − 0.180625)) = (x, 0.505, 0.14790199) (`ikKnee`).
 * [3] THE STANDING KNEE BEND (STAND, a = 1): up = 0 (standing), down = −0.15 (d 0.73, knee 0.445). Lowered by the gap
 *     of [1], δ = −0.08018824: d = 0.79981176, knee (x, 0.08 + d/2, √(0.2025 − 0.39990588²) = √0.04257529) = (x, 0.47990588, 0.20633779).
 *     Applied to a three.js bone chain (`applyPairHeight`): the hips go down by δ, the ankle stays (< 1e-9 m) — the
 *     planted joint does not move — the knee lands on that hand value, the foot keeps its world rotation.
 * [4] TAKES NOTHING: LYING (hips 0.15 < 0.22) → "resting" [0, 0]; on a BED (support 0.45 > 0.05) → "fixed";
 *     CARRIED (ankles 0.50, knees 0.70: no leg planted) → "free".
 * [5] THE PAIR (`pairHeightOffsets`), entering b = STAND at a_b = 1.2 (scaled: still standing; at −0.15 d = 1.056 − 0.15),
 *     receiving a = CROUCH at 1.0; Δ = (1.2 − 1)·h_c.
 *     h_c 0.40 → Δ 0.08: b's range downward (0.15) beats a's upward (0.09506971): b takes it all, o_b = −0.08, o_a = 0.
 *     h_c 1.00 → Δ 0.20: b takes its 0.15, a the remaining 0.05 (a SPLIT), residual 0.
 *     h_c 1.50 → Δ 0.30: b −0.15, a +0.09506971, residual 0.30 − 0.24506971 = 0.05493029 (left to the chain bend).
 * [6] THE GROUP (least squares): a = CROUCH (1.0) receives b = LYING (a_b 1.2, h_c 0.6 → Δ1 = 0.12) and c = STAND
 *     (a_c 1.1, h_c 0.2 → Δ2 = 0.02). b takes nothing. Minimise (o_a − 0.12)² + (o_a − o_c − 0.02)², o_a ≤ 0.09506971,
 *     o_c ∈ [−0.15, 0]: for o_a > 0.02 the best o_c is 0 and (o_a − 0.12)² + (o_a − 0.02)² is least at o_a = 0.07 (value
 *     0.005); o_a ≤ 0.02 costs ≥ (0.02 − 0.12)² = 0.01. So o_a = 0.07, o_b = o_c = 0, residuals +0.05 / −0.05.
 * [7] SAME HEIGHTS: a_b = a_a = 1 → every gap exactly 0, every offset exactly 0, no range computed; an offset of 0
 *     touches no bone (positions and quaternions bit-identical). The poser (`pairHeightPoser`, for a renderer whose clip
 *     does not write the hips) applied twice with +0.05 leaves the hips at 0.90 + 0.05 = 0.95, not 1.00; 0 puts them back.
 * [8] THE WIRE (`pairContactHeightsOf`): cm → metres; a key whose roles miss the part or the receiver, a value out of
 *     bounds, a role letter outside a..e are skipped; `pairRolePoseCm` rounds to 0.1 cm with x/z relative to the hips.
 *
 * VECTOR: shared/test-vectors/pair_scale.json carries [1], [2], [3] (ranges, knee), [4], [5], [6], [7] and [8] (parse)
 * as the functions pairHeightGap / pairRoleRange / ikKnee / pairHeightOffsets / pairContactHeightsOf for the native
 * client; scripts/smoke_pair_scale.mjs replays the file.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-height-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(pathToFileURL(file).href)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const S = await loadSR()
const THREE = await import(pathToFileURL(join(ROOT, 'node_modules/three/build/three.module.js')).href)
let n = 0
const ok = (label) => { n++; console.log('  ok', label) }
const near = (got, want, eps, label) => assert.ok(Math.abs(got - want) <= eps, `${label}: ${got} vs ${want}`)

const leg = (x, hipY, kneeY, kneeZ, ankleY = 0.08) => ({ hip: [x, hipY, 0], knee: [x, kneeY, kneeZ], ankle: [x, ankleY, 0] })
const CROUCH = { supportM: 0, hipsM: 0.95, legs: [leg(0.1, 0.88, 0.48, Math.sqrt(0.0425)), leg(-0.1, 0.88, 0.48, Math.sqrt(0.0425))] }
const STAND = { supportM: 0, hipsM: 1.03, legs: [leg(0.1, 0.96, 0.52, Math.sqrt(0.0089)), leg(-0.1, 0.96, 0.52, Math.sqrt(0.0089))] }
const LYING = { supportM: 0, hipsM: 0.15, legs: [leg(0.1, 0.12, 0.12, 0.45, 0.10), leg(-0.1, 0.12, 0.12, 0.45, 0.10)] }
const BED = { ...CROUCH, supportM: 0.45 }
const CARRIED = { supportM: 0, hipsM: 1.2, legs: [leg(0.1, 1.1, 0.7, 0.2, 0.5), leg(-0.1, 1.1, 0.7, 0.2, 0.5)] }
const UP = 0.9 * Math.cos(6 * Math.PI / 180) - 0.8

// [1]
near(S.pairHeightGap(0.852, 0, 1.86 / 1.7, 0, 1), 0.16 / 1.7 * 0.852, 1e-15, 'gap 1.86/1.70')
near(S.pairHeightGap(0.852, 0, 1.86 / 1.7, 0, 1), 0.08018824, 1e-8, 'gap 80.2 mm')
near(S.pairHeightGap(0.875, 0, 1.86 / 1.7, 0, 1.65 / 1.7), 0.10808824, 1e-8, 'gap 1.86/1.65')
near(S.pairHeightGap(0.9, 0.5, 1.1, 0.5, 1), 0.04, 1e-12, 'gap on a bed')
assert.equal(S.pairHeightGap(0.852, 0, 1, 0, 1), 0)
ok('[1] Δ = 80.2 mm (1.86 on 1.70 at h_c 0.852), 108.1 mm (1.86 on 1.65 at 0.875), 40 mm on a bed, 0 for equal heights')

// [2]
{
  const r = S.pairRoleRange(CROUCH, 1)
  assert.equal(r.stance, 'bent'); assert.deepEqual(r.planted, [true, true])
  near(r.up, UP, 1e-9, 'crouch up'); near(UP, 0.09506971, 1e-8, 'hand up')
  near(r.down, -0.15, 1e-12, 'crouch down')
  const k = S.ikKnee([0.1, 0.93, 0], [0.1, 0.53, Math.sqrt(0.0425)], [0.1, 0.13, 0], [0.1, 0.08, 0])
  near(k[0], 0.1, 1e-12, 'knee x'); near(k[1], 0.505, 1e-12, 'knee y'); near(k[2], 0.14790199, 1e-8, 'knee z')
  ok(`[2] crouch: up ${r.up.toFixed(8)} (min bend 12°), down −0.15 (MAX); knee at +0.05 = (0.1, 0.505, 0.14790199)`)
}
// [3]
const DELTA = 0.16 / 1.7 * 0.852
{
  const r = S.pairRoleRange(STAND, 1)
  assert.equal(r.stance, 'standing'); assert.equal(r.up, 0); near(r.down, -0.15, 1e-12, 'stand down')
  const d = 0.88 - DELTA
  const k = S.ikKnee([0.1, 0.96 - DELTA, 0], [0.1, 0.52 - DELTA, Math.sqrt(0.0089)], [0.1, 0.08 - DELTA, 0], [0.1, 0.08, 0])
  near(k[1], 0.08 + d / 2, 1e-12, 'stand knee y'); near(k[1], 0.47990588, 1e-8, 'stand knee y hand')
  near(k[2], Math.sqrt(0.2025 - (d / 2) ** 2), 1e-12, 'stand knee z'); near(k[2], 0.20633779, 1e-8, 'stand knee z hand')
  // the three.js chain: hips → leftupleg → leftleg → leftfoot, the legs posed as STAND
  const mk = (name, parent, p) => { const b = new THREE.Bone(); b.name = name; b.position.set(...p); parent?.add(b); return b }
  const root = new THREE.Group()
  const hips = mk('mixamorig:Hips', null, [0, 1.03, 0]); root.add(hips)
  const up = mk('mixamorig:LeftUpLeg', hips, [0.1, -0.07, 0])
  const lo = mk('mixamorig:LeftLeg', up, [0, -0.44, Math.sqrt(0.0089)])
  const ft = mk('mixamorig:LeftFoot', lo, [0, -0.44, -Math.sqrt(0.0089)])
  mk('mixamorig:LeftToeBase', ft, [0, -0.05, 0.12])
  root.updateMatrixWorld(true)
  const rig = S.pairHeightRigOf(root)
  assert.ok(rig && rig.legs[0] && !rig.legs[1])
  const ankle0 = ft.getWorldPosition(new THREE.Vector3()), foot0 = ft.getWorldQuaternion(new THREE.Quaternion())
  S.applyPairHeight(THREE, rig, -DELTA, [true, true])
  root.updateMatrixWorld(true)
  const ankle1 = ft.getWorldPosition(new THREE.Vector3()), knee1 = lo.getWorldPosition(new THREE.Vector3())
  assert.ok(ankle1.distanceTo(ankle0) < 1e-9, `ankle moved ${ankle1.distanceTo(ankle0)}`)
  near(hips.getWorldPosition(new THREE.Vector3()).y, 1.03 - DELTA, 1e-12, 'hips lowered')
  near(knee1.y, 0.47990588, 1e-8, 'chain knee y'); near(knee1.z, 0.20633779, 1e-8, 'chain knee z')
  assert.ok(ft.getWorldQuaternion(new THREE.Quaternion()).angleTo(foot0) < 1e-9, 'foot turned')
  ok(`[3] standing: lowering only (down −0.15); lowered by ${(DELTA * 1000).toFixed(1)} mm the knee goes to (0.47990588, 0.20633779), the planted ankle moves ${(ankle1.distanceTo(ankle0) * 1000).toExponential(1)} mm`)
}
// [4]
{
  for (const [pose, stance] of [[LYING, 'resting'], [BED, 'fixed'], [CARRIED, 'free']]) {
    const r = S.pairRoleRange(pose, 1.1)
    assert.equal(r.stance, stance); assert.equal(r.down, 0); assert.equal(r.up, 0)
  }
  ok('[4] lying → resting [0, 0]; on a bed → fixed; carried → free: they take nothing')
}
// [5] and [6]
const wireLeg = (l) => [l.hip, l.knee, l.ankle].map((p) => p.map((v) => v * 100))
const wireRole = (p) => ({ support_cm: p.supportM * 100, hips_cm: p.hipsM * 100, legs: p.legs.map(wireLeg) })
const pairWire = (h) => ({ 'b>a:mouth': { height_cm: h * 100, roles: { a: wireRole(CROUCH), b: wireRole(STAND) } } })
{
  const scales = { a: 1, b: 1.2 }
  const run = (h) => S.pairHeightOffsets(S.pairContactHeightsOf(pairWire(h)), (r) => scales[r])
  let s = run(0.40)
  near(s.gaps['b>a:mouth'], 0.08, 1e-12, 'gap 0.08'); near(s.offsets.b, -0.08, 1e-12, 'b takes it'); assert.equal(s.offsets.a, 0)
  s = run(1.00)
  near(s.offsets.b, -0.15, 1e-12, 'b max'); near(s.offsets.a, 0.05, 1e-12, 'a the rest'); near(s.residuals['b>a:mouth'], 0, 1e-12, 'res 0')
  s = run(1.50)
  near(s.offsets.b, -0.15, 1e-12, 'b max'); near(s.offsets.a, UP, 1e-9, 'a max'); near(s.residuals['b>a:mouth'], 0.05493029, 1e-8, 'res')
  ok('[5] pair: Δ 0.08 → b −0.08 alone; Δ 0.20 → b −0.15 + a +0.05 (split); Δ 0.30 → residual 0.05493029')
}
{
  const wire = { 'b>a:mouth': { height_cm: 60, roles: { a: wireRole(CROUCH), b: wireRole(LYING) } },
    'c>a:channel': { height_cm: 20, roles: { a: wireRole(CROUCH), c: wireRole(STAND) } } }
  const scales = { a: 1, b: 1.2, c: 1.1 }
  const s = S.pairHeightOffsets(S.pairContactHeightsOf(wire), (r) => scales[r])
  near(s.offsets.a, 0.07, 1e-12, 'o_a'); assert.equal(s.offsets.b, 0); assert.equal(s.offsets.c, 0)
  near(s.residuals['b>a:mouth'], 0.05, 1e-12, 'res b'); near(s.residuals['c>a:channel'], -0.05, 1e-12, 'res c')
  ok('[6] group: o_a = 0.07, o_b = o_c = 0, residuals +0.05 / −0.05 (the least-squares optimum)')
}
// [7]
{
  const s = S.pairHeightOffsets(S.pairContactHeightsOf(pairWire(0.852)), () => 1)
  assert.equal(s.gaps['b>a:mouth'], 0); assert.equal(s.offsets.a, 0); assert.equal(s.offsets.b, 0)
  assert.deepEqual(s.ranges, {})
  const root = new THREE.Group(), hips = new THREE.Bone(); hips.name = 'Hips'; hips.position.set(0.01, 0.9, 0.02); root.add(hips)
  const q = hips.quaternion.clone(), p = hips.position.clone()
  S.applyPairHeight(THREE, { hips, legs: [null, null] }, 0, [true, true])
  assert.ok(hips.position.equals(p) && hips.quaternion.equals(q))
  // the poser of an in-place renderer (no clip writes the hips): the offset never accumulates, 0 puts the hips back
  const pose = S.pairHeightPoser(THREE, { hips, legs: [null, null] })
  pose(0.05, []); pose(0.05, [])
  near(hips.position.y, 0.95, 1e-12, 'poser once')
  pose(0, [])
  assert.ok(hips.position.equals(p), 'poser restores')
  ok('[7] equal heights: every gap and offset exactly 0, no range computed, an offset 0 touches no bone; the poser never accumulates')
}
// [8]
{
  assert.deepEqual(S.pairContactHeightsOf(null), [])
  const good = pairWire(0.852)
  const bad = { ...good, 'c>a:mouth': { height_cm: 50, roles: { a: wireRole(CROUCH) } },
    'b>a:hand_left': { height_cm: 400, roles: good['b>a:mouth'].roles },
    'b>a:hand_right': { height_cm: 50, roles: { ...good['b>a:mouth'].roles, f: wireRole(STAND) } } }
  const got = S.pairContactHeightsOf(bad)
  assert.equal(got.length, 1); assert.equal(got[0].key, 'b>a:mouth'); near(got[0].heightM, 0.852, 1e-15, 'h')
  near(got[0].roles.a.legs[0].knee[2], Math.sqrt(0.0425), 1e-12, 'leg')
  const w = S.pairRolePoseCm([1.0, 0.4044, 2.0], [{ hip: [1.1, 0.38, 2.0], knee: [1.3, 0.06, 2.05], ankle: [0.9, 0.1, 2.3] }], 0)
  assert.deepEqual(w, { support_cm: 0, hips_cm: 40.4, legs: [[[10, 38, 0], [30, 6, 5], [-10, 10, 30]]] })
  ok('[8] wire: cm → m, malformed relations skipped; pairRolePoseCm rounds to 0.1 cm relative to the hips')
}
console.log(`smoke_pair_height: ${n} ok`)
