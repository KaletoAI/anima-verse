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

  if (failures.length) { console.error(`\n${failures.length} check(s) failed`); process.exit(1) }
  console.log('\nall channel-grows checks passed')
}
main().catch((err) => { console.error(err); process.exit(1) })
