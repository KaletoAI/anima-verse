#!/usr/bin/env node
/**
 * Smoke check for THE OPENING of a declared channel (Ruling A102) — `packages/scene-render/src/channelOpening.ts`:
 * the receiving body's surface moves out around whatever occupies the channel, by the channel's zone and the
 * occupant's radius.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_channel_opening.mjs
 *
 * No server, no world DB, no outbound request. `three` is bundled for [6] only.
 *
 * Every expected number is derived BY HAND from the rule in the module docstring.
 * Fixture (the D2 channel of smoke_channel_guidance): O = origin, u = +z, R = 0.02, D = 0.12, α = 30°, F = 0.05.
 * m = 0.002, axial falloff f = 0.02, band floor 0.015, candidate slack 0.06 (the defaults).
 * The synthetic channel mesh: rings of N = 8 points at ρ = r0 = 0.02 (the channel wall) at
 * s ∈ {0.05, 0.125, 0.13, 0.15, −0.02, −0.08}, one ring at ρ = 0.01, s = 0.05 (deep inside the band), one ring at
 * ρ = 0.07, s = 0.05 (outside the band).
 * The occupant ("rod"): ONE segment on the axis from s = −0.10 to s = 0.15, radius r.
 *
 * [1] The radial map f(d), rod r = 0.03: T = 0.032, B = max(0.015, 0.018) = 0.018, b = 0.05, d0 = T − B = 0.014,
 *     L = 0.036. d ≤ 0.014 → exactly T = 0.032 (d 0, d 0.01). d = 0.02: t = 1/6, Hermite basis h00 = 100/108,
 *     h01 = 8/108, h11 = −5/216 → f = 0.032·100/108 + 0.05·8/108 − 0.036·5/216 = 3.6/108 − 0.18/216 = 0.0325.
 *     d ≥ 0.05 → d (0.05, 0.07). Monotone and C1: f nondecreasing over d ∈ [0, 0.08] in 1e-4 steps, slope → 0 at d0⁺
 *     and → 1 at b⁻ (finite difference within 0.01).
 *     r = 0.015: T = 0.017, B = 0.015, b = 0.032, d0 = 0.002, L = 0.03; d = 0.02: t = 0.6, h00 = 0.352, h01 = 0.648,
 *     h11 = −0.144 → f = 0.005984 + 0.020736 − 0.00432 = 0.0224.
 *     r = 0.003: T = 0.005, B = 0.015, b = 0.02 → f(0.02) = 0.02 (no move).
 * [2] openingWeight (axial only), z = 1 − smoothstep(e/f), smoothstep(t) = t²(3 − 2t):
 *     s 0.05 → 1; s 0.125 (e 0.005, t 0.25): 1 − 0.0625·2.5 = 0.84375; s 0.13 (t 0.5): 0.5; s 0.15 (e 0.03) → 0; s −0.08
 *     (e 0.03) → 0; s −0.02 (inside the funnel's axial range) → 1.
 * [3] Rod r = 0.03. Every nearest point is on the axis at the point's own s, so d = ρ and the end radius is
 *     ρ + z·(f(ρ) − ρ):
 *       ρ 0.02  s 0.05   z 1        → 0.0325
 *       ρ 0.02  s 0.125  z 0.84375  → 0.02 + 0.84375·0.0125 = 0.030546875
 *       ρ 0.02  s 0.13   z 0.5      → 0.02625
 *       ρ 0.02  s 0.15   —          → 0.02 (not a candidate)
 *       ρ 0.02  s −0.02  z 1        → 0.0325
 *       ρ 0.02  s −0.08  —          → 0.02 (not even a candidate)
 *       ρ 0.01  s 0.05   z 1        → exactly T = 0.032 (the inside ends at T; order kept: 0.032 < 0.0325)
 *       ρ 0.07  s 0.05   z 1        → 0.07 (d ≥ b)
 *     Candidates: −F − f = −0.07 ≤ s ≤ D + f = 0.14 and ρ ≤ R + f + slack = 0.1 → every ring but s = −0.08 and s = 0.15:
 *     6 · 8 = 48. Moved: 5 rings · 8 = 40. Max push 0.032 − 0.01 = 0.022.
 * [4] Rod r = 0.003 (b = 0.02 = r0): the ρ 0.02 rings do not move; r = 0.015: the s 0.05 wall ends at 0.0224.
 * [5] A point ON the rod axis, P = (0, 0, 0.05): d = 0 ≤ d0 → T; ρ = 0 → the perpendicular u × x = (0, 1, 0);
 *     displacement (0, 0.032, 0).
 * [6] The three binding on a skinned mesh of those points (one bone, bone turned +90° about y and moved to x = 1):
 *     the bind-space channel axis +z becomes world u = R_y(90°)·(0,0,1) = (1, 0, 0), O = (1, 0, 0). With the rod of
 *     [3] carried the same way: the skinned world positions of the s = 0.05 wall end at ρ 0.0325 (±1e-5), the s 0.15
 *     wall at 0.02; 40 moved, 48 candidates. The narrowing (rod ρ 0, s −0.10…0.15, reach b 0.05 + pose slack 0.01:
 *     s ∈ [−0.16, 0.21], ρ ≤ 0.06) keeps the 6 candidate rings minus the ρ 0.07 ring = 40 visited. restore() puts the ORIGINAL
 *     geometry object back with positions and normals bit-identical.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_channel_opening_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [__filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`],
      { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], { stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root })
    process.exit(run.status ?? 1)
  }
  const O = await import('../packages/scene-render/src/channelOpening.ts')
  const THREE = await import('three')
  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol

  const ch = { id: 'c', o: [0, 0, 0], u: [0, 0, 1], depth: 0.12, r: 0.02, coneDeg: 30, funnel: 0.05, accepts: [],
    minLength: 0, compressMin: 0.8, kinds: null, suppress: new Set() }
  // [1]
  const f = (d, r) => O.openedDistance(d, r)
  check('[1] f(d), r 0.03: T inside, 0.0325 at 0.02, identity from b', near(f(0, 0.03), 0.032) && near(f(0.01, 0.03), 0.032)
    && near(f(0.02, 0.03), 0.0325, 1e-9) && f(0.05, 0.03) === 0.05 && f(0.07, 0.03) === 0.07, String(f(0.02, 0.03)))
  let mono = true
  for (const r of [0.003, 0.015, 0.03, 0.05]) for (let d = 0; d < 0.08; d += 1e-4) if (f(d + 1e-4, r) < f(d, r) - 1e-12) mono = false
  const h = 1e-6
  const slope0 = (f(0.014 + 2 * h, 0.03) - f(0.014 + h, 0.03)) / h, slope1 = (f(0.05 - h, 0.03) - f(0.05 - 2 * h, 0.03)) / h
  check('[1] monotone, C1 at both band ends', mono && Math.abs(slope0) < 0.01 && Math.abs(slope1 - 1) < 0.01,
    `${slope0.toFixed(4)} ${slope1.toFixed(4)}`)
  check('[1] r 0.015 → 0.0224, r 0.003 → 0.02', near(f(0.02, 0.015), 0.0224, 1e-9) && near(f(0.02, 0.003), 0.02, 1e-12))
  // [2]
  const w = (s) => O.openingWeight(s, ch)
  check('[2] openingWeight', near(w(0.05), 1) && near(w(0.125), 0.84375) && near(w(0.13), 0.5) && w(0.14) === 0
    && w(-0.08) === 0 && w(-0.02) === 1, [w(0.125), w(0.13)].join(' '))
  // The synthetic mesh.
  const N = 8
  const rings = [[0.02, 0.05], [0.02, 0.125], [0.02, 0.13], [0.02, 0.15], [0.02, -0.02], [0.02, -0.08], [0.01, 0.05], [0.07, 0.05]]
  const pts = []
  for (const [rho, s] of rings) for (let i = 0; i < N; i++) {
    const th = (i / N) * Math.PI * 2
    pts.push(rho * Math.cos(th), rho * Math.sin(th), s)
  }
  const cand = O.openingCandidates(pts, ch)
  check('[3] candidates 48 (not the s 0.15 / −0.08 rings)', cand.length === 48 && !cand.some(i => (i >= 24 && i < 32) || (i >= 40 && i < 48)), String(cand.length))
  const rod = (r) => [{ a: [0, 0, -0.1], b: [0, 0, 0.15], r }]
  const out = new Float32Array(pts.length)
  const endRho = (i) => { const k = cand.indexOf(i); const dx = k >= 0 ? out[3 * k] : 0, dy = k >= 0 ? out[3 * k + 1] : 0
    return Math.hypot(pts[3 * i] + dx, pts[3 * i + 1] + dy) }
  const got = O.channelOpening(pts, cand, ch, rod(0.03), out)
  const want = [0.0325, 0.030546875, 0.02625, 0.02, 0.0325, 0.02, 0.032, 0.07]
  let ringsOk = true
  rings.forEach((_, r) => { for (let i = 0; i < N; i++) if (!near(endRho(r * N + i), want[r], 1e-6)) ringsOk = false })
  check('[3] rod r 0.03: end radii as derived', ringsOk, rings.map((_, r) => endRho(r * N).toFixed(6)).join(' '))
  check('[3] moved 40, max push 0.022', got.moved === 40 && near(got.maxPush, 0.022, 1e-6), `${got.moved} ${got.maxPush}`)
  O.channelOpening(pts, cand, ch, rod(0.003), out)
  let thinOk = true
  for (let r = 0; r < 6; r++) for (let i = 0; i < N; i++) if (!near(endRho(r * N + i), 0.02, 1e-9)) thinOk = false
  O.channelOpening(pts, cand, ch, rod(0.015), out)
  check('[4] r 0.003: the 0.02 wall stays; r 0.015: s 0.05 wall at 0.0224', thinOk && near(endRho(0), 0.0224, 1e-6),
    String(endRho(0)))
  const onAxis = O.openingDisplacement([0, 0, 0.05], ch, rod(0.03))
  check('[5] on-axis point → (0, 0.032, 0)', !!onAxis && near(onAxis[0], 0) && near(onAxis[1], 0.032) && near(onAxis[2], 0),
    JSON.stringify(onAxis))
  // [6] the three binding.
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
  const n = pts.length / 3
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(Array.from({ length: n * 3 }, (_, i) => (i % 3 === 2 ? 1 : 0)), 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(n * 4).fill(0), 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(Array.from({ length: n * 4 }, (_, i) => (i % 4 === 0 ? 1 : 0)), 4))
  const bone = new THREE.Bone()
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  const root = new THREE.Group()
  root.add(bone, mesh)
  root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([bone]))
  bone.position.set(1, 0, 0)
  bone.rotation.y = Math.PI / 2
  root.updateMatrixWorld(true)
  const before = new Float32Array(geo.attributes.position.array)
  const beforeN = new Float32Array(geo.attributes.normal.array)
  const chW = { ...ch, o: [1, 0, 0], u: [1, 0, 0] }
  const bound = O.bindChannelOpening(THREE, root, chW)
  const res = bound.apply(chW, [{ a: [0.9, 0, 0], b: [1.15, 0, 0], r: 0.03 }])
  const v = new THREE.Vector3()
  const worldRho = (i) => { mesh.getVertexPosition(i, v).applyMatrix4(mesh.matrixWorld); return Math.hypot(v.y, v.z) }
  check('[6] binding: s 0.05 wall at 0.0325, s 0.15 wall 0.02, 40 moved, 48 candidates, 40 visited',
    near(worldRho(0), 0.0325, 1e-5) && near(worldRho(3 * N), 0.02, 1e-5) && res.moved === 40 && bound.candidates === 48
    && res.visited === 40, `${worldRho(0)} ${worldRho(3 * N)} ${res.moved} ${bound.candidates} ${res.visited}`)
  bound.restore()
  const same = mesh.geometry === geo && geo.attributes.position.array.every((x, i) => x === before[i])
    && geo.attributes.normal.array.every((x, i) => x === beforeN[i])
  check('[6] restore: original geometry, positions and normals bit-identical', same)
  bound.dispose()

  if (failures.length) { console.error(`\nFAILED: ${failures.join(', ')}`); process.exit(1) }
  console.log('\nALL OK')
}
main()
