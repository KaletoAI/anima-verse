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
 * m = 0.002, axial falloff f = 0.02, band floor 0.015, band factor K = 1.5, candidate slack 0.08 (the defaults).
 * The synthetic channel mesh: rings of N = 8 points at ρ = r0 = 0.02 (the channel wall) at
 * s ∈ {0.05, 0.125, 0.13, 0.15, −0.02, −0.08}, one ring at ρ = 0.01, s = 0.05 (deep inside), one ring at
 * ρ = 0.07, s = 0.05 (the surrounding region).
 * The occupant ("rod"): ONE segment on the axis from s = −0.10 to s = 0.15, radius r.
 *
 * [1] The radial map (A102c) f(d) = d + T·(1 − d/b)² for d < b, else d; T = r + m, B = max(0.015, 1.5·max(r, R)),
 *     b = T + B.
 *     r = 0.03: T = 0.032, B = max(0.015, 0.045) = 0.045, b = 0.077.
 *       f(0) = 0.032 (= T);
 *       f(0.01) = 0.01 + 0.032·(1 − 0.129870)² = 0.01 + 0.032·0.757126 = 0.0342280;
 *       f(0.02) = 0.02 + 0.032·(1 − 0.259740)² = 0.02 + 0.032·0.547985 = 0.0375355;
 *       f(0.07) = 0.07 + 0.032·(1 − 0.909091)² = 0.07 + 0.032·0.0082645 = 0.0702645 (the surrounding region moves too);
 *       f(0.077) = 0.077, f(0.09) = 0.09.
 *     Monotone (B ≥ T ⇒ f' ≥ 1 − 2T/b ≥ 0) and C1 at b: f nondecreasing over d ∈ [0, 0.12] in 1e-4 steps for
 *     r ∈ {0.003, 0.012, 0.015, 0.02, 0.03, 0.04}; f ≥ T and f ≥ d; slope → 1 at b⁻ (finite difference within 0.01).
 *     The band carries more with a wider occupant: the push at d = 0.04 grows with r — r 0.012: T 0.014, B 0.03,
 *     b 0.044, 0.014·(1 − 0.909091)² = 0.0001157; r 0.02: T 0.022, B 0.03, b 0.052, 0.022·(0.230769)² = 0.0011716;
 *     r 0.03: 0.032·(1 − 0.519481)² = 0.0073888; r 0.04: T 0.042, B 0.06, b 0.102, 0.042·(0.607843)² = 0.0155179.
 *     r = 0.015: T = 0.017, B = 0.03, b = 0.047: f(0.02) = 0.02 + 0.017·(0.574468)² = 0.02 + 0.017·0.330013 = 0.0256102.
 *     r = 0.003: T = 0.005, B = 0.03, b = 0.035: f(0.02) = 0.02 + 0.005·(0.428571)² = 0.0209184; f(0.04) = 0.04.
 * [2] openingWeight (axial only), z = 1 − smoothstep(e/f), smoothstep(t) = t²(3 − 2t):
 *     s 0.05 → 1; s 0.125 (e 0.005, t 0.25): 1 − 0.0625·2.5 = 0.84375; s 0.13 (t 0.5): 0.5; s 0.15 (e 0.03) → 0; s −0.08
 *     (e 0.03) → 0; s −0.02 (inside the funnel's axial range) → 1.
 * [3] Rod r = 0.03. Every nearest point is on the axis at the point's own s, so d = ρ and the end radius is
 *     ρ + z·(f(ρ) − ρ):
 *       ρ 0.02  s 0.05   z 1        → 0.0375355
 *       ρ 0.02  s 0.125  z 0.84375  → 0.02 + 0.84375·0.0175355 = 0.0347956
 *       ρ 0.02  s 0.13   z 0.5      → 0.0287678
 *       ρ 0.02  s 0.15   —          → 0.02 (not a candidate)
 *       ρ 0.02  s −0.02  z 1        → 0.0375355
 *       ρ 0.02  s −0.08  —          → 0.02 (not a candidate)
 *       ρ 0.01  s 0.05   z 1        → 0.0342280 (order kept: 0.0342 < 0.0375 < 0.0703)
 *       ρ 0.07  s 0.05   z 1        → 0.0702645
 *     Candidates: −0.07 ≤ s ≤ 0.14 and ρ ≤ R + f + slack = 0.12 → every ring but s 0.15 and s −0.08: 6 · 8 = 48.
 *     Moved: all 48. Max push 0.0342280 − 0.01 = 0.0242280.
 * [4] r = 0.003: s 0.05 wall at 0.0209184, the ρ 0.07 ring unchanged; r = 0.015: s 0.05 wall at 0.0256102.
 * [5] A point ON the rod axis, P = (0, 0, 0.05): d = 0 → f = T; ρ = 0 → the perpendicular u × x = (0, 1, 0);
 *     displacement (0, 0.032, 0).
 * [6] The three binding on a skinned mesh of those points (one bone, bone turned +90° about y and moved to x = 1):
 *     the bind-space channel axis +z becomes world u = R_y(90°)·(0,0,1) = (1, 0, 0), O = (1, 0, 0). With the rod of
 *     [3] carried the same way: the skinned world positions of the s = 0.05 wall end at ρ 0.0375355 (±1e-5), the s 0.15
 *     wall at 0.02; 48 moved, 48 candidates. The narrowing (rod ρ 0, s −0.10…0.15, reach b 0.077 + pose slack 0.01:
 *     ρ ≤ 0.087) keeps all 48. restore() puts the ORIGINAL geometry object back with positions and normals
 *     bit-identical.
 * [7] A TILTED rod (A102c). guideRod pivots the tilt about the opening: tilt 20°, length 0.2, insertion 0.05, 1 link,
 *     radius 0.01, budget 0 → dir = R_y(20°)·u = (sin 20°, 0, cos 20°) = (0.342020, 0, 0.939693), root = −0.15·dir =
 *     (−0.051303, 0, −0.140954), tip = 0.05·dir = (0.017101, 0, 0.046985): the rod line crosses s = 0 at ρ = 0 (the
 *     opening centre). The opening around it is centred: P± = (±0.02, 0, 0) lie at |P × dir| = 0.02·cos 20° =
 *     0.0187939 from the rod axis on both sides; T = 0.012, B = max(0.015, 1.5·0.02) = 0.03, b = 0.042:
 *     f = 0.0187939 + 0.012·(1 − 0.447474)² = 0.0187939 + 0.012·0.305285 = 0.0224573 → push 0.0036634 each side,
 *     along ±(cos 20°, 0, −sin 20°) (perpendicular to the rod): d± = ±(0.0034425, 0, −0.0012530), point-symmetric
 *     about the crossing.
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
  const f = (d, r) => O.openedDistance(d, r, {}, 0.02)
  check('[1] f(d), r 0.03: 0.032 / 0.0342280 / 0.0375355 / 0.0702645 / identity from b', near(f(0, 0.03), 0.032)
    && near(f(0.01, 0.03), 0.0342280, 1e-7) && near(f(0.02, 0.03), 0.0375355, 1e-7) && near(f(0.07, 0.03), 0.0702645, 1e-7)
    && f(0.077, 0.03) === 0.077 && f(0.09, 0.03) === 0.09, [f(0.01, 0.03), f(0.02, 0.03), f(0.07, 0.03)].join(' '))
  let mono = true
  for (const r of [0.003, 0.012, 0.015, 0.02, 0.03, 0.04]) {
    const T = r + 0.002
    for (let d = 0; d < 0.12; d += 1e-4) {
      if (f(d + 1e-4, r) < f(d, r) - 1e-12 || f(d, r) < T - 1e-12 || f(d, r) < d - 1e-12) mono = false
    }
  }
  const h = 1e-6
  const slope1 = (f(0.077 - h, 0.03) - f(0.077 - 2 * h, 0.03)) / h
  check('[1] monotone, f ≥ T, f ≥ d, C1 at b', mono && Math.abs(slope1 - 1) < 0.01, slope1.toFixed(4))
  const push4 = (r) => f(0.04, r) - 0.04
  check('[1] the surrounding region at d 0.04 moves more with r: 0.0001157 / 0.0011716 / 0.0073888 / 0.0155179',
    near(push4(0.012), 0.0001157, 1e-7) && near(push4(0.02), 0.0011716, 1e-7) && near(push4(0.03), 0.0073888, 1e-7)
    && near(push4(0.04), 0.0155179, 1e-7), [0.012, 0.02, 0.03, 0.04].map(push4).map(v => v.toFixed(7)).join(' '))
  check('[1] r 0.015 → 0.0256102, r 0.003 → 0.0209184 / 0.04', near(f(0.02, 0.015), 0.0256102, 1e-7)
    && near(f(0.02, 0.003), 0.0209184, 1e-7) && f(0.04, 0.003) === 0.04)
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
  const want = [0.0375355, 0.0347956, 0.0287678, 0.02, 0.0375355, 0.02, 0.0342280, 0.0702645]
  let ringsOk = true
  rings.forEach((_, r) => { for (let i = 0; i < N; i++) if (!near(endRho(r * N + i), want[r], 2e-7)) ringsOk = false })
  check('[3] rod r 0.03: end radii as derived', ringsOk, rings.map((_, r) => endRho(r * N).toFixed(6)).join(' '))
  check('[3] moved 48, max push 0.0242280', got.moved === 48 && near(got.maxPush, 0.0242280, 2e-7), `${got.moved} ${got.maxPush}`)
  O.channelOpening(pts, cand, ch, rod(0.003), out)
  const thin = [endRho(0), endRho(7 * N)]
  O.channelOpening(pts, cand, ch, rod(0.015), out)
  check('[4] r 0.003: wall 0.0209184, ρ 0.07 unchanged; r 0.015: wall 0.0256102', near(thin[0], 0.0209184, 2e-7)
    && near(thin[1], 0.07, 1e-9) && near(endRho(0), 0.0256102, 2e-7), `${thin} ${endRho(0)}`)
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
  check('[6] binding: s 0.05 wall at 0.0375355, s 0.15 wall 0.02, 48 moved, 48 candidates, 48 visited',
    near(worldRho(0), 0.0375355, 1e-5) && near(worldRho(3 * N), 0.02, 1e-5) && res.moved === 48 && bound.candidates === 48
    && res.visited === 48, `${worldRho(0)} ${worldRho(3 * N)} ${res.moved} ${bound.candidates} ${res.visited}`)
  bound.restore()
  const same = mesh.geometry === geo && geo.attributes.position.array.every((x, i) => x === before[i])
    && geo.attributes.normal.array.every((x, i) => x === beforeN[i])
  check('[6] restore: original geometry, positions and normals bit-identical', same)
  bound.dispose()
  // [7] the tilted rod
  const C = await import('../packages/scene-render/src/channels.ts')
  const g7 = C.guideRod(ch, { length: 0.2, radius: 0.01, links: 1, insertion: 0.05, tiltDeg: 20, budgetDeg: 0 })
  const [root7, tip7] = g7.joints
  const vn = (a, b, tol) => a.every((x, i) => near(x, b[i], tol))
  const t0 = -root7[2] / (tip7[2] - root7[2])
  const crossX = root7[0] + (tip7[0] - root7[0]) * t0
  check('[7] tilt 20°: root (−0.051303, 0, −0.140954), tip (0.017101, 0, 0.046985), crossing at the opening centre',
    vn(root7, [-0.051303, 0, -0.140954], 1e-6) && vn(tip7, [0.017101, 0, 0.046985], 1e-6) && near(crossX, 0, 1e-12),
    JSON.stringify(g7.joints))
  const seg7 = [{ a: root7, b: tip7, r: 0.01 }]
  const dPlus = O.openingDisplacement([0.02, 0, 0], ch, seg7), dMinus = O.openingDisplacement([-0.02, 0, 0], ch, seg7)
  const len7 = (v) => Math.hypot(v[0], v[1], v[2])
  check('[7] the opening is centred on the crossing: push 0.0036634 on both sides, point-symmetric',
    !!dPlus && !!dMinus && near(len7(dPlus), 0.0036634, 2e-7) && near(len7(dMinus), 0.0036634, 2e-7)
    && vn(dPlus, [0.0034425, 0, -0.0012530], 2e-7) && vn(dMinus, [-0.0034425, 0, 0.0012530], 2e-7), `${dPlus} ${dMinus}`)

  if (failures.length) { console.error(`\nFAILED: ${failures.join(', ')}`); process.exit(1) }
  console.log('\nALL OK')
}
main()
