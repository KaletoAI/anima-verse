#!/usr/bin/env node
/**
 * Smoke check for Ruling A161 — THE CHANNEL GROWS WITH THE PART
 * (`packages/scene-render/src/channels.ts`: `CHANNEL_PART_MARGIN_M`, `effectiveChannelRadius`, `channelForPart`;
 * used by `secondaryMotion.ts` per engagement, by `guideRod` for the admin test rod, and by
 * `figureRuntime.applyChannelOpenings` / `inspect()` for the opening band and the wireframe).
 *
 * Usage: node scripts/smoke_channel_grows.mjs   (self-bundling via esbuild; no server, no DB, no request)
 *
 * Rule: while a part engages a channel, R_eff = max(R, r_part + m), r_part = its largest link radius (core × girth,
 * the radius guidance uses), m = 5 mm (the pack's sizing rule R − r_c ≥ 5 mm).
 * Fixture: O = origin, u = +z, R = 0.035 (the declared inset channel), D = 0.12, α = 30°, F = 0.05.
 *
 * Expected numbers, derived BY HAND:
 * [1] r_part 0.037 (the thick aroused part): R_eff = max(0.035, 0.042) = 0.042; lateral room
 *     R_eff − r_c = 0.005. On the declared R the room was max(0, 0.035 − 0.037) = 0.
 * [2] r_part 0.018 (a thin part): R_eff = max(0.035, 0.023) = 0.035 — unchanged, `channelForPart` returns the
 *     SAME object. r_part 0.030: 0.035 exactly (0.030 + 0.005 = R) — unchanged. r_part 0: unchanged.
 * [3] Guidance, joint J = (0, 0, −0.05), tip T = (0.03, 0, 0.05): lever (0.03, 0, 0.10), |lever| = 0.104403,
 *     16.699° from u; J on the axis, so ρ(φ) = 0.104403·sin(16.699° − φ).
 *     - r_c 0.037 on the grown channel: R' = 0.005 → 16.699° − φ = asin(0.005 / 0.104403) = asin(0.047891)
 *       = 2.745° → φ = 13.954° (±0.01); the tip ends at ρ 0.005 (±1e-5) — inside, with 5 mm room.
 *     - r_c 0.037 on the declared R: R' = 0 — no turn brings the tip strictly inside (it can only graze the
 *       axis at 16.699°), so the guidance falls back to a closest-approach turn (recorded, not asserted as a
 *       value): the A161 defect this ruling removes.
 *     - r_c 0.018 grown (= declared): R' = 0.017 → asin(0.017 / 0.104403) = asin(0.162831) = 9.371° →
 *       φ = 7.328° (±0.01), identical on both.
 * [4] guideRod, 1 link, length 0.104403, radius 0.037, tilt 16.699°, insertion 0.08, budget 90°:
 *     dir = (sin 16.699°, 0, cos 16.699°) = (0.287348, 0, 0.957826); J = −0.024403·dir → x_J = −0.0070122;
 *     tip before guidance 0.08·dir, ρ = 0.022988 > R' = 0.042 − 0.037 = 0.005. ρ(φ) = −0.0070122 +
 *     0.104403·sin(16.699° − φ) = 0.005 → sin = 0.0120122 / 0.104403 = 0.115056 → 6.607°, φ = 10.092° (±0.01).
 *     With radius 0.018 the channel stays R = 0.035: R' = 0.017, sin = 0.0240122 / 0.104403 = 0.229996 →
 *     13.297°, φ = 3.402° (±0.01).
 * [5] The grown channel shares everything but R: depth, funnel, cone, gate fields and the `suppress` set
 *     (same reference); the input channel is not mutated.
 * [6] THE CHANNEL READOUT (`channelReadout.ts`) on the DECLARED channel at its 2026-11-19 sizes: O = origin, u = +z,
 *     D = 0.20, R_rest = 0.0303 (r_mean 25.25 mm of the stored entering parts + c 5 mm, rounded up). s = z.
 *     a. outside: one link z −0.15 → −0.05, r 0.025: front −0.05 + 0.025 < 0 → insertion 0, of D 0, of length 0,
 *        stretch 0 (no link reaches s ≥ 0), k 1.
 *     b. funnel: one link z −0.11 → −0.01, r 0.025: the surface front −0.01 + 0.025 = 0.015 → insertion 0.015,
 *        of D 0.075; the axis is not past the plane: of length 0, stretch 0.
 *     c. half in: links z −0.06 → 0 (r 0.034) and 0 → 0.06 (r 0.025): front max(0 + 0.034, 0.06 + 0.025) = 0.085,
 *        of D 0.425; length inside 0 + 0.06 of 0.12 = 0.5; stretch: the first link reaches s = 0, excess
 *        0.034 − 0.0303 = 0.0037 (s 0, at the opening: stretchOpening 0.0037), the second 0.025 < R → 0; stretch
 *        0.0037, diameter 0.0074, ratio 0.0037 / 0.0303 = 0.1221122.
 *     d. bottomed, compressed: links z 0.02 → 0.10 → 0.18, r 0.03, k 0.8: front 0.21, of D 1.05, of length 1,
 *        k 0.8; r 0.03 < R_rest 0.0303 → stretch 0 (a part thinner than the rest radius never stretches).
 *     e. r > R_rest: one link z 0.01 → 0.09, r 0.0336 (the thickest stored surface link but one): excess 0.0033 at
 *        s 0.01, ratio 0.0033 / 0.0303 = 0.1089109; the link does not cross the plane → stretchOpening 0; front
 *        0.1236, of D 0.618.
 *     f. an oblique link (x 0.01 → 0.03, z 0 → 0.04) counts by its s only: front 0.04 + 0.02 = 0.06.
 *     No segments → null.
 *     g. Nothing past the bottom at D 0.20 (compress_min 0.8): the thickest and longest stored entering part (core
 *        r_c 0.0356, chain 0.1264 m) fully in from the opening (s_e 0, tip s 0.1264): floor D − r_c = 0.1644 ≥
 *        0.1264 → k = 1 (no compression). The same part at state length 1.35 (tip 0.17064): k = 0.1644 / 0.17064 =
 *        0.9634318; at length 2 (tip 0.2528): 0.6503165 → clamped to 0.8. Its R_eff (A161) = 0.0356 + 0.005 =
 *        0.0406 > R_rest: room 5 mm, never 0 (`allowedRadius` past the funnel).
 * [7] The live publisher of client3d (`client3d/src/game/channelReadouts.ts`, interval 100 ms): frames at t = 0 [A],
 *     50 [A], 100 [A, B], 150 [], 200 [B], 300 [], 400 [], 450 [] → publications at 0 ([A], released []), 100 ([A, B]),
 *     200 ([B], released [key A]) and 300 (null); nothing at 50 / 150 (throttled), 400 / 450 (nothing engaged after
 *     the final null). An empty first frame publishes nothing.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_channel_grows_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) { console.error('esbuild not found (npm install) — nothing was checked'); process.exit(1) }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`],
      { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], { stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root })
    process.exit(run.status ?? 1)
  }
  const C = await import('../packages/scene-render/src/channels.ts')
  const failures = []
  const check = (name, ok, detail = '') => {
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(name)
  }
  const near = (a, b, tol) => Math.abs(a - b) <= tol
  const DEG = Math.PI / 180
  const suppress = new Set(['cap_a'])
  const ch = { id: 'inset', o: [0, 0, 0], u: [0, 0, 1], depth: 0.12, r: 0.035, coneDeg: 30, funnel: 0.05,
    accepts: ['attached_part'], minLength: 0, compressMin: 0.8, kinds: null, suppress }

  // [1]
  check('[1] margin constant 5 mm', C.CHANNEL_PART_MARGIN_M === 0.005)
  const thick = C.channelForPart(ch, 0.037)
  check('[1] r_part 0.037 → R_eff 0.042', near(thick.r, 0.042, 1e-12), `${thick.r}`)
  check('[1] lateral room 0.005 (was 0)', near(C.allowedRadius(0.05, thick, 0.037), 0.005, 1e-12)
    && C.allowedRadius(0.05, ch, 0.037) === 0)
  // [2]
  check('[2] r_part 0.018 → unchanged, same object', C.channelForPart(ch, 0.018) === ch
    && C.effectiveChannelRadius(0.035, 0.018) === 0.035)
  check('[2] r_part 0.030 → exactly R, unchanged', C.channelForPart(ch, 0.030) === ch)
  check('[2] r_part 0 → unchanged', C.channelForPart(ch, 0) === ch)
  // [3]
  const J = [0, 0, -0.05], T = [0.03, 0, 0.05]
  const rot = (g) => { // tip after turning about J by g.angle about g.axis (Rodrigues)
    const v = [T[0] - J[0], T[1] - J[1], T[2] - J[2]], k = g.axis, c = Math.cos(g.angle), s = Math.sin(g.angle)
    const kd = k[0] * v[0] + k[1] * v[1] + k[2] * v[2]
    const kx = [k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0]]
    return [0, 1, 2].map(i => J[i] + v[i] * c + kx[i] * s + k[i] * kd * (1 - c))
  }
  const gGrown = C.radialGuidanceAngle(J, T, thick, 0.037)
  const tipG = rot(gGrown)
  check('[3] grown: turn 13.954°', near(gGrown.angle / DEG, 13.954, 0.01), `${(gGrown.angle / DEG).toFixed(4)}`)
  check('[3] grown: tip at ρ 0.005', near(Math.hypot(tipG[0], tipG[1]), 0.005, 1e-5), `${Math.hypot(tipG[0], tipG[1])}`)
  const gOld = C.radialGuidanceAngle(J, T, ch, 0.037)
  check('[3] declared R: no turn reaches room (no 13.954° solution)', !gOld || !near(gOld.angle / DEG, 13.954, 0.5),
    gOld ? `closest-approach turn ${(gOld.angle / DEG).toFixed(4)}°` : 'null')
  const thin = C.channelForPart(ch, 0.018)
  const gThin = C.radialGuidanceAngle(J, T, thin, 0.018), gThinOld = C.radialGuidanceAngle(J, T, ch, 0.018)
  check('[3] thin: 7.328° on both', near(gThin.angle / DEG, 7.328, 0.01) && gThin.angle === gThinOld.angle,
    `${(gThin.angle / DEG).toFixed(4)}`)
  // [4]
  const rod = { length: 0.104403, links: 1, tiltDeg: 16.699, insertion: 0.08, budgetDeg: 90 }
  const rThick = C.guideRod(ch, { ...rod, radius: 0.037 })
  check('[4] guideRod radius 0.037: turn 10.092°', near(rThick.turnsDeg[0], 10.092, 0.01), `${rThick.turnsDeg[0].toFixed(4)}`)
  const rThin = C.guideRod(ch, { ...rod, radius: 0.018 })
  check('[4] guideRod radius 0.018: turn 3.402°', near(rThin.turnsDeg[0], 3.402, 0.01), `${rThin.turnsDeg[0].toFixed(4)}`)
  // [5]
  check('[5] grown shares all but R', thick.suppress === suppress && thick.depth === 0.12 && thick.funnel === 0.05
    && thick.coneDeg === 30 && thick.accepts === ch.accepts && thick.id === 'inset' && ch.r === 0.035)

  // [6]
  const RO = await import('../packages/scene-render/src/channelReadout.ts')
  const dch = { o: [0, 0, 0], u: [0, 0, 1], depth: 0.20, r: 0.0303 }
  const link = (z0, z1, r, x0 = 0, x1 = 0) => ({ a: [x0, 0, z0], b: [x1, 0, z1], r })
  const ro = (segs, k) => RO.channelReadout(dch, segs, k)
  const a6 = ro([link(-0.15, -0.05, 0.025)])
  check('[6a] outside: all 0, k 1', a6.insertionM === 0 && a6.insertionOfDepth === 0 && a6.insertionOfLength === 0
    && a6.stretchM === 0 && a6.compressK === 1, JSON.stringify(a6))
  const b6 = ro([link(-0.11, -0.01, 0.025)])
  check('[6b] funnel: insertion 0.015 (of D 0.075), of length 0, stretch 0', near(b6.insertionM, 0.015, 1e-12)
    && near(b6.insertionOfDepth, 0.075, 1e-12) && b6.insertionOfLength === 0 && b6.stretchM === 0, JSON.stringify(b6))
  const c6 = ro([link(-0.06, 0, 0.034), link(0, 0.06, 0.025)])
  check('[6c] half in: insertion 0.085 (0.425), of length 0.5', near(c6.insertionM, 0.085, 1e-12)
    && near(c6.insertionOfDepth, 0.425, 1e-12) && near(c6.insertionOfLength, 0.5, 1e-12), JSON.stringify(c6))
  check('[6c] stretch 0.0037 at s 0, diameter 0.0074, ratio 0.1221122, at the opening 0.0037',
    near(c6.stretchM, 0.0037, 1e-12) && c6.stretchAtM === 0 && near(c6.stretchDiameterM, 0.0074, 1e-12)
    && near(c6.stretchRatio, 0.1221122, 1e-7) && near(c6.stretchOpeningM, 0.0037, 1e-12), JSON.stringify(c6))
  const d6 = ro([link(0.02, 0.10, 0.03), link(0.10, 0.18, 0.03)], 0.8)
  check('[6d] bottomed: insertion 0.21 (1.05), of length 1, k 0.8, stretch 0', near(d6.insertionM, 0.21, 1e-12)
    && near(d6.insertionOfDepth, 1.05, 1e-12) && d6.insertionOfLength === 1 && d6.compressK === 0.8 && d6.stretchM === 0,
    JSON.stringify(d6))
  const e6 = ro([link(0.01, 0.09, 0.0336)])
  check('[6e] r > R_rest: stretch 0.0033 at s 0.01, ratio 0.1089109, not at the opening, insertion 0.1236 (0.618)',
    near(e6.stretchM, 0.0033, 1e-12) && near(e6.stretchAtM, 0.01, 1e-12) && near(e6.stretchRatio, 0.1089109, 1e-7)
    && e6.stretchOpeningM === 0 && near(e6.insertionM, 0.1236, 1e-12) && near(e6.insertionOfDepth, 0.618, 1e-12),
    JSON.stringify(e6))
  const f6 = ro([link(0, 0.04, 0.02, 0.01, 0.03)])
  check('[6f] oblique: front by s only, 0.06', near(f6.insertionM, 0.06, 1e-12), JSON.stringify(f6))
  check('[6] no segments → null', RO.channelReadout(dch, []) === null)
  const pelvis = { ...ch, depth: 0.20, r: 0.0303, compressMin: 0.8 }
  check('[6g] k 1 for the longest stored part fully in', C.depthScale(0.1264, 0, pelvis, 0.0356) === 1,
    `${C.depthScale(0.1264, 0, pelvis, 0.0356)}`)
  check('[6g] k 0.9634318 at state length 1.35', near(C.depthScale(0.17064, 0, pelvis, 0.0356), 0.9634318, 1e-7),
    `${C.depthScale(0.17064, 0, pelvis, 0.0356)}`)
  check('[6g] k clamps at 0.8 at length 2', near(C.depthScale(0.2528, 0, pelvis, 0.0356), 0.8, 1e-12))
  const grownP = C.channelForPart(pelvis, 0.0356)
  check('[6g] grown R 0.0406, room 5 mm', near(grownP.r, 0.0406, 1e-12)
    && near(C.allowedRadius(0.05, grownP, 0.0356), 0.005, 1e-12), `${grownP.r}`)
  // [7]
  const P = await import('../client3d/src/game/channelReadouts.ts')
  const got = []
  const pub = P.createReadoutPublisher((state) => got.push(state), 100)
  const A = { receiver: 'R', channel: 'inset', entering: 'E1' }, B = { receiver: 'R', channel: 'mouth', entering: 'E2' }
  pub([], -10)
  check('[7] an empty first frame publishes nothing', got.length === 0)
  for (const [t, rs] of [[0, [A]], [50, [A]], [100, [A, B]], [150, []], [200, [B]], [300, []], [400, []], [450, []]]) pub(rs, t)
  check('[7] four publications: 0, 100, 200, null', got.length === 4 && got[0].at === 0 && got[1].at === 100
    && got[2].at === 200 && got[3] === null, JSON.stringify(got.map((g) => g && g.at)))
  check('[7] contents and releases', got[0].readouts.length === 1 && got[0].released.length === 0
    && got[1].readouts.length === 2 && got[2].readouts.length === 1 && got[2].released.join() === 'R|inset|E1',
    JSON.stringify(got))
  check('[7] key format', RO.channelReadoutKey(A) === 'R|inset|E1')

  if (failures.length) { console.error(`\n${failures.length} check(s) failed`); process.exit(1) }
  console.log('\nall channel-grows checks passed')
}
main().catch((err) => { console.error(err); process.exit(1) })
