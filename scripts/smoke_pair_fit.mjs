#!/usr/bin/env node
/**
 * Ruling A129: the pair geometry of `packages/scene-render/src/pairFit.ts` — its fix solved for shift AND partner B's
 * tilt/roll (through the two-key-frame Auto-align of `pairAlign.ts` solveAlign, with a cap wide enough not to bind
 * unless a check says so; no root angle, no channel inequalities: the samples carry neither), partner B's stored turn
 * and yaw, the pivot and the honest check. Every expected
 * number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_pair_fit.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE A (metres). Channel O = (0, 0, 0), u = (0, 0, 1). The shaft runs along d = (0, sin 10°, cos 10°)
 *   = (0, 0.17364818, 0.98480775): tips T_c = c·d for c = 0 and 0.03, base = T − 0.1·d, pivot p = −0.3·d
 *   = (0, −0.05209445, −0.29544233) (on the shaft's line). Axes: tilt (1, 0, 0), roll (0, 1, 0). solveAlign with basis I,
 *   no start, cap ±0.5 m on every axis and 20°. Its key frames: deep = c = 0.03, shallow = c = 0; residuals = the root
 *   (the base) and the tip off the axis at both.
 *   [1] ROTATION about +X by α maps (0, sin β, cos β) to (0, sin(β − α), cos(β − α)); α = 10° lays d on u.
 *       Then R(T_c − p) + p = p + (0.3 + c)·u = (0, −0.05209445, 0.00455767 + c), so Δ = (0, 0.05209445, Δz) puts root
 *       and tip on the axis for ANY Δz — the depth is not pulled to a target, and the ridge keeps the null direction
 *       where it is: Δz = 0. Expect tilt 10° (±0.01°), roll 0° (±0.01°), Δ = (0, 0.05209445, 0) (±1e-5 m).
 *   [2] fixSample of that fix: tips (0, 0, 0.00455767) and (0, 0, 0.03455767) (±1e-5), shaft against the axis 0°
 *       (contactReport axisDeg < 0.05°). Before the fix the angle is 10° (acos(d·u)).
 *   [3] BOUND: angle cap 5° → tilt exactly 5° (held on its bound, named in hits), |Δ_i| ≤ 0.5.
 * FIXTURE B = A126's fixture 1 (smoke_channel_contact.mjs): no axes → the shift-only solve; root and tip are off by
 *   (0.01, −0.02) at every frame → Δ = (−0.01, 0.02, 0) ± 1e-6 (the forward is the null direction again).
 *   [5] the solve without axes = (−0.01, 0.02, 0) ± 1e-6.
 * [6] roleTurnFix(10, −5, identity frame) = turn (10°, 0, −5°) in radians: (0.17453293, 0, −0.08726646).
 * [6b] Ruling A165, partner B's yaw about its own vertical axis (identity frame, pivot p = (1, 0, 2)):
 *     yaw 90° first, then tilt 10° about +X. Point p + (0, 0, 1): Ry(90°) maps (0, 0, 1) to (1, 0, 0), Rx leaves +X
 *     alone → (2, 0, 2). Point p + (0, 1, 0): Ry keeps it, Rx(10°) maps (0, 1, 0) to (0, cos 10°, sin 10°) →
 *     (1, 0.98480775, 2.17364818). roleYawFix(90, Ry(90°) frame) turns about that frame's up (0, 1, 0): π/2 on y.
 * [7] fixPivot((1, 0, 2), Ry(90°) row-major [0,0,1, 0,1,0, −1,0,0], hips (0, 0.9, 0.1)) = (1 + 0.1, 0.9, 2 − 0) =
 *     (1.1, 0.9, 2).
 * THE HONEST CHECK (A129.5): entering E with part capsule `part`, receiving R whose channel allows `pelvis`.
 *   Contacts: E|part–R|pelvis 0.03 (exempt), R|pelvis–E|part 0.04 (exempt, reversed order), E|part–R|thigh 0.01
 *   (counts: the part may only pass the allowed capsule), E|thigh–R|pelvis 0.02 (counts: not the part).
 *   [16] depth 0.02 at E thigh ↔ R pelvis. Without the exemption the deepest would be 0.04.
 *   [17] lamps: 5 mm green, 5.1 yellow, 20 yellow, 20.1 red.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-fit-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: ROOT, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const SR = await loadSR()
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`)
const s10 = Math.sin(10 * Math.PI / 180), c10 = Math.cos(10 * Math.PI / 180)
const d = [0, s10, c10], U = [0, 0, 1], O = [0, 0, 0]
const pivot = d.map((v) => -0.3 * v)
const A = [0, 0.03].map((c) => ({ tip: d.map((v) => c * v), base: d.map((v) => (c - 0.1) * v), o: O, u: U, pivot }))
const AXES = [[1, 0, 0], [0, 1, 0]]

const I3 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
const CAP = (angleDeg) => ({ sideM: 0.5, upM: 0.5, forwardM: 0.5, angleDeg })
const solve = (samples, axes, angleDeg = 20) => SR.solveAlign({ relations: [{ samples }], basis: I3, axes, cap: CAP(angleDeg) })
const sol = solve(A, AXES)                                                                    // [1]
const fix = sol.fix
const [tilt, roll] = sol.deg
near(tilt, 10, 0.01, 'tilt'); near(roll, 0, 0.01, 'roll')
near(fix.shift[0], 0, 1e-5, 'dx'); near(fix.shift[1], 0.05209445, 1e-5, 'dy'); near(fix.shift[2], 0, 1e-5, 'dz')
const moved = A.map((x) => SR.fixSample(x, fix))                                             // [2]
near(moved[0].tip[1], 0, 1e-5, 'tip0 y'); near(moved[0].tip[2], 0.00455767, 1e-5, 'tip0 z'); near(moved[1].tip[2], 0.03455767, 1e-5, 'tip1 z')
near(SR.contactReport(A).axisDeg, 10, 1e-6, 'angle before')
assert.ok(SR.contactReport(moved).axisDeg < 0.05, 'angle after')
const lim = solve(A, AXES, 5)                                                                 // [3]
near(lim.deg[0], 5, 1e-9, 'bounded tilt'); assert.ok(lim.hits.includes('tilt'), 'tilt named')
assert.ok(lim.fix.shift.every((v) => Math.abs(v) <= 0.5))
const B = [-0.05, 0, 0.03].map((z) => ({ tip: [0.01, -0.02, z], base: [0.01, -0.02, z - 0.1], o: O, u: U, pivot: [0, 0, 0] }))
const fb = solve(B, [])                                                                       // [5]
;[-0.01, 0.02, 0].forEach((v, i) => near(fb.fix.shift[i], v, 1e-6, 'shift-only'))
const pt = SR.roleTurnFix(10, -5, [1, 0, 0, 0, 1, 0, 0, 0, 1])                            // [6]
near(pt.turn[0], 0.17453293, 1e-8, 'turn x'); near(pt.turn[1], 0, 1e-12, 'turn y'); near(pt.turn[2], -0.08726646, 1e-8, 'turn z')
{                                                                                             // [6b]
  const I = [1, 0, 0, 0, 1, 0, 0, 0, 1], p = [1, 0, 2]
  const yt = SR.roleTurnFix(10, 0, I, 90)
  ;[2, 0, 2].forEach((v, i) => near(SR.fixPoint(yt, p, [1, 0, 3])[i], v, 1e-9, 'yaw then tilt, forward point'))
  ;[1, 0.98480775, 2.17364818].forEach((v, i) => near(SR.fixPoint(yt, p, [1, 1, 2])[i], v, 1e-8, 'yaw then tilt, up point'))
  const yf = SR.roleYawFix(90, [0, 0, 1, 0, 1, 0, -1, 0, 0])
  near(yf.turn[1], Math.PI / 2, 1e-12, 'yaw axis'); near(yf.turn[0], 0, 1e-12, 'yaw x'); near(yf.turn[2], 0, 1e-12, 'yaw z')
}
const pv = SR.fixPivot([1, 0, 2], [0, 0, 1, 0, 1, 0, -1, 0, 0], [0, 0.9, 0.1])               // [7]
;[1.1, 0.9, 2].forEach((v, i) => near(pv[i], v, 1e-12, 'pivot'))
const contacts = [{ a: 'E', capA: 'part', b: 'R', capB: 'pelvis', depth: 0.03 },
  { a: 'R', capA: 'pelvis', b: 'E', capB: 'part', depth: 0.04 }, { a: 'E', capA: 'part', b: 'R', capB: 'thigh', depth: 0.01 },
  { a: 'E', capA: 'thigh', b: 'R', capB: 'pelvis', depth: 0.02 }]
const hon = SR.pairInterpenetration(contacts, { entering: 'E', parts: new Set(['part']), receiving: 'R', allowed: new Set(['pelvis']) })
near(hon.depth, 0.02, 1e-12, 'honest depth'); assert.deepEqual(hon.worst, { a: 'E', capA: 'thigh', b: 'R', capB: 'pelvis' })  // [16]
near(SR.pairInterpenetration(contacts, { entering: 'E', parts: new Set(), receiving: 'R', allowed: new Set() }).depth, 0.04, 1e-12, 'no exemption')
assert.deepEqual([5, 5.1, 20, 20.1].map(SR.clearLamp), ['green', 'yellow', 'yellow', 'red'])                                       // [17]
console.log('smoke_pair_fit: OK')
