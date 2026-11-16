/**
 * Smoke: the Library's alignment DRAFT over the saved orientation (`clipCalibration`, @anima/scene-render) puts
 * a figure where the BAKED clip will put it — no jump across Apply (Ruling A110 phase 2, spec
 * docs/superpowers/specs/2026-11-16-poses-tab-redesign-design.md § 2.2 "Draft flow"; acceptance: max hips
 * position delta < 1 mm and body yaw delta < 0.1° before vs after Apply).
 *
 * Usage: node scripts/smoke_clip_calibration.mjs   (no server, no world; bundles the module with esbuild)
 *
 * The bake (animation_clips.orient_clip → clip_orient.py): hips path P' = R·(P + S_role), hips rotation R·Q,
 * R = Ry(yaw)·Rx(tilt)·Rz(roll); `shift_cm` adds up in the sidecar (rounded to 0.01 cm), a height save stores the
 * draft value of the surface group. "Before" = saved clip + draft, "after" = baked clip + saved' + empty draft.
 *
 * [1] Hand case — solo clip, seat place facing 90°, place yaw π/2, anchor (1, 0.11, 0):
 *     hips bind H = (0, 0.95, 0), stand reference 0.95 m, saved hips now P = (0.2, 0.475, 0.1)
 *     draft yaw +90° → P' = Ry(90°)·P = (cos·0.2 + sin·0.1, 0.475, −sin·0.2 + cos·0.1) = (0.1, 0.475, −0.2)
 *     solo plays in place → local = (0, −drop, 0), drop = 0.95·(1 − 0.475/0.95) = 0.475
 *     H − R·H = 0 (H on the turn axis); Ry(π/2)·(0, −0.475, 0) = (0, −0.475, 0)
 *     saved shift [10, 0] cm → clipShiftM: x = 0.1·cos 90° = 0, z = −0.1·sin 90° = −0.1
 *     saved seat height 2 cm → +0.02
 *     root = (1 + 0, 0.11 − 0.475 + 0.02, 0 − 0.1) = (1, −0.345, −0.1); root yaw = π/2 + π/2 = π.
 *     After Apply (P' baked, draft 0): the same root, root yaw π/2 (the turn now lives in the bones).
 * [2] Pair role b, all dials at once (yaw 17°, tilt 8°, roll −5°, role shift b (3, 1, −2) cm, draft shift
 *     [4, −3] cm over saved [1, 2], draft seat height 3 cm over saved 1, hips bind off-axis (0.01, 0.93, −0.02)),
 *     60 samples of a moving hips path: max |hips before − hips after| < 1 mm and the body rotation
 *     Rframe(before) vs Ry·R (after) < 0.1°. Same with tilt/roll only on a solo clip.
 * [3] D4 lamp: (2.9°, 1.9 cm) green, (3.1°, 1 cm) yellow, (1°, 6 cm) yellow, (10.5°, 0) red, (0, 6.1 cm) red.
 *     alignmentDelta: forward (1, 0) is yaw 90°; against facing 80 → +10°; hips (0.03, 0.04) vs slot 0 → 5 cm.
 *     median([5, 1, 3]) = 3, median([4, 1, 3, 2]) = 2.5.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const near = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps

const dir = await mkdtemp(join(tmpdir(), 'clip-calibration-'))
try {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    entryPoints: [join(ROOT, 'packages/scene-render/src/clipCalibration.ts')],
    bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
  })
  const file = join(dir, 'cal.mjs')
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  const C = await import(`file://${file}`)
  const { clipCalibration, calibratedRoot, eulerYXZ, mulVec, alignmentLamp, alignmentDelta, median, EMPTY_DRAFT } = C

  // ── [1] hand case ──
  console.log('[1] solo, hand-derived')
  const draft1 = { ...EMPTY_DRAFT, yawDeg: 90 }
  const saved1 = { shiftCm: [10, 0], heightOffsetsCm: { seat: 2 } }
  const H = { x: 0, y: 0.95, z: 0 }
  const P = { x: 0.2, y: 0.475, z: 0.1 }
  const cal1 = clipCalibration(draft1, saved1, Math.PI / 2, 'seat')
  const r1 = calibratedRoot(cal1, { anchor: { x: 1, y: 0.11, z: 0 }, role: '', hips: P, inPlace: true, hipsBind: H, standRefM: 0.95 })
  check('root before = (1, -0.345, -0.1)', near(r1.x, 1) && near(r1.y, -0.345) && near(r1.z, -0.1), JSON.stringify(r1))
  check('root yaw before = π', near(cal1.euler[1], Math.PI))
  const baked = mulVec(eulerYXZ(0, Math.PI / 2, 0), P)
  check('baked hips = (0.1, 0.475, -0.2)', near(baked.x, 0.1) && near(baked.y, 0.475) && near(baked.z, -0.2), JSON.stringify(baked))
  const cal1b = clipCalibration(EMPTY_DRAFT, saved1, Math.PI / 2, 'seat')
  const r1b = calibratedRoot(cal1b, { anchor: { x: 1, y: 0.11, z: 0 }, role: '', hips: baked, inPlace: true, hipsBind: H, standRefM: 0.95 })
  check('root after = root before', near(r1b.x, 1) && near(r1b.y, -0.345) && near(r1b.z, -0.1), JSON.stringify(r1b))
  check('root yaw after = π/2', near(cal1b.euler[1], Math.PI / 2))

  // ── [2] all dials, moving path ──
  const rotAngleDeg = (A, B) => {
    // angle of A·Bᵀ
    const m = [0, 1, 2].map((i) => [0, 1, 2].map((j) => A[i * 3] * B[j * 3] + A[i * 3 + 1] * B[j * 3 + 1] + A[i * 3 + 2] * B[j * 3 + 2]))
    const tr = m[0][0] + m[1][1] + m[2][2]
    return Math.acos(Math.min(1, Math.max(-1, (tr - 1) / 2))) * 180 / Math.PI
  }
  const mat = (a, b) => [0, 1, 2].flatMap((i) => [0, 1, 2].map((j) => a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j]))
  const runCase = (label, draft, saved, placeYaw, role, inPlace, hipsBind) => {
    console.log(label)
    const cal = clipCalibration(draft, saved, placeYaw, 'seat')
    // Apply: the server's bookkeeping (shift_cm rounded to 0.01 cm, the height stored as the draft value).
    const savedAfter = {
      shiftCm: [0, 1].map((i) => Math.round(((saved.shiftCm?.[i] ?? 0) + draft.shiftCm[i]) * 100) / 100),
      heightOffsetsCm: { ...(saved.heightOffsetsCm || {}), ...draft.heightCm },
    }
    const calAfter = clipCalibration(EMPTY_DRAFT, savedAfter, placeYaw, 'seat')
    const anchor = { x: 0.4, y: 0.12, z: -0.3 }
    let maxMm = 0
    for (let i = 0; i < 60; i++) {
      const t = i / 59
      const hips = { x: 0.15 * Math.sin(6 * t), y: 0.5 + 0.08 * Math.cos(4 * t), z: -0.1 + 0.2 * t }
      const rootBefore = calibratedRoot(cal, { anchor, role, hips, inPlace, hipsBind, standRefM: 0.95 })
      const s = cal.roleShift(role)
      const bakedHips = mulVec(cal.bake, { x: hips.x + s.x, y: hips.y + s.y, z: hips.z + s.z })
      const rootAfter = calibratedRoot(calAfter, { anchor, role, hips: bakedHips, inPlace, hipsBind, standRefM: 0.95 })
      // hips world = root + frame · H (the bone sits at its bind point under the turned root)
      const hb = mulVec(cal.frame, hipsBind)
      const ha = mulVec(calAfter.frame, hipsBind)
      const d = Math.hypot(rootBefore.x + hb.x - rootAfter.x - ha.x, rootBefore.y + hb.y - rootAfter.y - ha.y,
        rootBefore.z + hb.z - rootAfter.z - ha.z)
      maxMm = Math.max(maxMm, d * 1000)
    }
    // body rotation: before = frame (Ry·R) · Q, after = Ry · (R·Q)
    const deg = rotAngleDeg(cal.frame, mat(calAfter.frame, cal.bake))
    check(`max hips delta ${maxMm.toFixed(4)} mm < 1 mm`, maxMm < 1)
    check(`body rotation delta ${deg.toFixed(5)}° < 0.1°`, deg < 0.1)
    return { maxMm, deg }
  }
  const pairDraft = { yawDeg: 17, tiltDeg: 8, rollDeg: -5, shiftCm: [4, -3], roleShiftM: { b: [0.03, 0.01, -0.02] }, heightCm: { seat: 3 } }
  const facing = 30
  const pairYaw = (facing - 90) * Math.PI / 180
  const a = runCase('[2a] pair role b, all dials', pairDraft, { shiftCm: [1, 2], heightOffsetsCm: { seat: 1 } }, pairYaw, 'b', false,
    { x: 0.01, y: 0.93, z: -0.02 })
  const b = runCase('[2b] solo, tilt + roll only', { ...EMPTY_DRAFT, tiltDeg: 12, rollDeg: 7 }, {}, facing * Math.PI / 180, '', true,
    { x: 0.01, y: 0.93, z: -0.02 })

  // ── [3] readout ──
  console.log('[3] lamp + delta')
  check('2.9°/1.9 cm green', alignmentLamp(2.9, 1.9) === 'green')
  check('3.1°/1 cm yellow', alignmentLamp(3.1, 1) === 'yellow')
  check('1°/6 cm yellow', alignmentLamp(1, 6) === 'yellow')
  check('10.5°/0 red', alignmentLamp(10.5, 0) === 'red')
  check('0/6.1 cm red', alignmentLamp(0, 6.1) === 'red')
  const d = alignmentDelta({ x: 1, z: 0 }, 80, { x: 0.03, z: 0.04 }, { x: 0, z: 0 })
  check('Δyaw +10°', near(d.dyaw, 10, 1e-9), String(d.dyaw))
  check('Δpos 5 cm', near(d.dpos, 5, 1e-9), String(d.dpos))
  check('median odd', median([5, 1, 3]) === 3)
  check('median even', median([4, 1, 3, 2]) === 2.5)
  console.log(`acceptance: pair max ${a.maxMm.toExponential(2)} mm / ${a.deg.toExponential(2)}°, solo tilt ${b.maxMm.toExponential(2)} mm / ${b.deg.toExponential(2)}°`)
} finally {
  await rm(dir, { recursive: true, force: true })
}
assert.equal(failures, 0, `${failures} check(s) failed`)
console.log('smoke_clip_calibration: all OK')
