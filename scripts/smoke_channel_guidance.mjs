#!/usr/bin/env node
/**
 * Smoke check for the CHANNEL GUIDANCE RULE — `packages/scene-render/src/channels.ts`
 * (cross-person collision, stage 2; spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` Part 4
 * "Guidance rule", derivation D2 of plan
 * `docs/superpowers/plans/2026-11-14-cross-person-collision.md`): the channel
 * frame, the zones, the radial clamp, the depth scale, engagement with its
 * hysteresis and blend, suppression, the gate, the admin test rod, the draft
 * preview and the binding by the endpoint rule.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_channel_guidance.mjs
 *
 * No server, no world DB, no outbound request. `three` is bundled for [12] and
 * the wireframe only; the rules themselves never touch it.
 *
 * Every expected number is derived BY HAND from the spec's formulas (§ B5a).
 * Fixture D2: O = origin, u = +z, R = 0.02, D = 0.12, α = 30°, funnel F = 0.05
 * (F is not in D2; it only bounds the funnel cases below). r_c = 0 unless said.
 * Frame of a point P: s = (P − O)·u, ρ = |P − O − s·u|.
 *
 * [1] Joint J = (0, 0, −0.05), tip T = (0.03, 0, 0.05). Lever = (0.03, 0, 0.10),
 *     |lever| = √(0.0009 + 0.01) = 0.104403, at atan(0.03 / 0.10) = 16.699° from u.
 *     T: s = 0.05 (inside 0..D), ρ = 0.03 > R' = R = 0.02. J sits on the axis, so a
 *     turn by φ in the xz-plane leaves ρ = 0.104403 · sin(16.699° − φ). ρ = R' at
 *     16.699° − φ = asin(0.02 / 0.104403) = 11.044° → turn φ = 5.655° (±0.005);
 *     the tip ends at s = −0.05 + 0.104403 · cos 11.044° = −0.05 + 0.102470 =
 *     0.05247 (±1e-5) and ρ = 0.02. The turn axis is −y (the turn moves the tip
 *     towards −x).
 * [2] r_c = 0.005: R' = 0.015, guided angle asin(0.015 / 0.104403) = 8.260°,
 *     turn 16.699° − 8.260° = 8.439° (±0.005).
 * [3] Budget 4° (the caller's cap min(5.655°, 4°) = 4°): the lever ends at 12.699°
 *     from u, ρ = 0.104403 · sin 12.699° = 0.022951 > R (±1e-5).
 * [4] Depth, s_e = 0, r_c = 0 (k = max(compress_min, (D − r_c − s_e)/(s_tip − s_e))
 *     when s_tip > D − r_c, else 1; the tip lands at s_e + k·(s_tip − s_e)):
 *     - s_tip 0.15, compress_min 0.8: 0.12 / 0.15 = 0.8 → k = 0.8, tip at 0.12;
 *     - s_tip 0.16: 0.12 / 0.16 = 0.75 → clamped to 0.8, tip at 0.128, 8 mm past;
 *     - compress_min 1.0: k = 1;
 *     - s_tip 0.10 ≤ D: k = 1.
 *     s_e < 0 (fix round 1: no joint inside, the joint nearest before the opening):
 *     - s_tip 0.15, s_e −0.05: (0.12 + 0.05) / (0.15 + 0.05) = 0.17 / 0.2 = 0.85 → k = 0.85,
 *       tip at −0.05 + 0.85 · 0.2 = 0.12;
 *     - s_tip 0.20, s_e −0.05: 0.17 / 0.25 = 0.68 → clamped to 0.8, tip at −0.05 + 0.8 · 0.25 = 0.15.
 *     `depthJoint` (axial joint positions root first → the index of s_e): [−0.05, 0.01, 0.07] → 1 (the
 *     first at s ≥ 0); [0, 0.05] → 0; [−0.08, −0.03] → 1 and [−0.03, −0.08] → 0 (none inside: the largest
 *     s); [−0.02, −0.02] → 1 (tie → the later); [] → −1.
 * [5] Funnel: R'(−0.02) = 0.02 + 0.02 · tan 30° = 0.02 + 0.011547 = 0.031547 (±1e-6).
 *     Zones: (s 0.05, ρ 0.01) cylinder; (s 0.13, ρ 0) null (past the bottom);
 *     (s −0.02, ρ 0.03) funnel (0.03 ≤ 0.031547); (s −0.06, ρ 0) null (beyond F).
 * [6] Hysteresis, h = CHANNEL_HYST_M = 0.005, δ = CHANNEL_HYST_DEG = 10°: the grown
 *     cylinder reaches R + h = 0.025.
 *     - Engaged, tip at s 0.05, ρ 0.023: plain zone null (0.023 > 0.02), grown zone
 *       cylinder → stays engaged.
 *     - ρ 0.026 > 0.025 → grown zone null → released.
 *     - Grown funnel at s −0.02: R + h + 0.02 · tan 40° = 0.025 + 0.016782 = 0.041782,
 *       so ρ 0.035 is in the grown funnel and not in the plain one (0.031547).
 *     - s −0.052 (ρ 0): beyond F = 0.05, within F + h = 0.055 → grown funnel only.
 *     - Past the bottom (s 0.13 > D): the plain zone and `{h}` alone say null; the release
 *       zone (`CHANNEL_GROW`, `pastBottom`) says cylinder at ρ 0.024 ≤ R + h, null at 0.026.
 *     - Engaging needs the lever within α: a tip in the zone with the lever at 35°
 *       does not engage, at 20° it does.
 * [7] Blend, CHANNEL_BLEND_S = 0.2: w ramps by dt / 0.2. From the engaging frame,
 *     steps of 0.02 s: after 5 (0.1 s) w = 0.5, after 10 (0.2 s) w = 1 (±1e-9).
 *     A release (gate false) from w = 1: 10 steps of 0.02 s reach 0, no step
 *     changes w by more than 0.02 / 0.2 = 0.1 (never jumps), w never below 0.
 * [8] Suppression, suppress = {cap_a, cap_b}: a tip at (0, 0, 0.05) is in C → that
 *     set; a tip at s = −0.01 (funnel) → the empty set.
 * [9] Gate (accepts [op_x], min_length 1.0, the partner's interaction {i1, k2}):
 *     wrong op → false; length 0.9 → false; reader interaction i2 → false; reader
 *     without an interaction → false; kinds [k1] with the partner's kind k2 → false;
 *     all matching (op_x, length 1.0, i1, kinds null or [k2]) → true.
 * [10] guideRod, 1 link, length 0.15, radius 0, tilt 0, insertion 0.15: the root sits
 *     on the axis at s = insertion − length = 0, the tip at s 0.15, ρ 0 — no turn.
 *     s_e = 0 (the root is the first joint past the opening), k = 0.8 (as [4]),
 *     the tip at 0.12, pastBottomM 0, the tip in C → suppressed [cap_a, cap_b].
 *     Insertion 0.16: root s 0.01 = s_e, k = max(0.8, 0.11 / 0.15 = 0.7333) = 0.8,
 *     tip at 0.01 + 0.8 · 0.15 = 0.13, pastBottomM 0.01.
 *     Insertion 0.13 (fix round 1): the root at s −0.02 is the only joint, none inside → s_e = −0.02,
 *     k = max(0.8, (0.12 + 0.02) / (0.13 + 0.02) = 0.14 / 0.15 = 0.933333), the tip at
 *     −0.02 + 0.14 = 0.12, pastBottomM 0 (the first-joint-inside rule gave k 1, tip 0.13, 10 mm past).
 *     Tilted (A102c: the tilt pivots about the opening centre O, root = O + dir·(insertion − length)):
 *     length 0.104403, tilt 30°, insertion 0.08 → dir = (sin 30°, 0, cos 30°), J = −0.024403·dir =
 *     (−0.0122015, 0, −0.0211339), tip before guidance 0.08·dir = (0.04, 0, 0.069282), ρ 0.04 > R.
 *     A turn by φ in the xz-plane leaves ρ = −0.0122015 + 0.104403·sin(30° − φ); ρ = R = 0.02 at
 *     sin(30° − φ) = 0.0322015 / 0.104403 = 0.308435 → 30° − φ = 17.965°, φ = 12.035° (±0.01); the tip at
 *     s = −0.0211339 + 0.104403·cos 17.965° = 0.078179 (±1e-5), k 1. Budget 4° → 4°, ρ > R.
 *     Tilt 16.699°, insertion 0.054403: tip 0.054403·dir at ρ 0.015633 < R → no turn; the rod crosses s = 0 at ρ 0.
 * [11] previewChannel, frame side (1,0,0), up (0, 0.6, 0.8), front (0, −0.8, 0.6),
 *     a_pos (0,1,0), b_pos (0,1,0.1), r 0.02, cone 30, applied neutral:
 *     - offset_mm (0, +10, 0) → a_pos + 0.01 · up = (0, 1.006, 0.008), b_pos the
 *       same shift = (0, 1.006, 0.108);
 *     - radius_scale applied 1.25, draft 1.5 → r · 1.2 = 0.024;
 *     - depth_scale applied 1, draft 2 → b − a doubled: b_pos = (0, 1, 0.2);
 *     - cone_deg replaced (45), `applied` = the draft;
 *     - the applied offset (0, 10, 0) with the same draft → no shift;
 *     - applied null counts as neutral.
 * [12] bindChannels: one bone at bind (0, 1, 0); record a = b = that joint, a_pos
 *     (0, 1, 0.1), b_pos (0, 1, 0.22), r 0.02, funnel 0.05. The figure moved by
 *     (1, 0, 0): o = a_pos + (1,0,0) = (1, 1, 0.1), u = (0, 0, 1), depth = |b_pos −
 *     a_pos| = 0.12, r 0.02. Moved again by +1 and `update()`: o = (2, 1, 0.1), the
 *     earlier ChannelNow object unchanged. Scaled × 0.5 about its origin:
 *     r 0.01, funnel 0.025, depth 0.06. Another version or a missing joint → null.
 *     The wireframe: every vertex lies at −F ≤ s ≤ D, ρ ≤ R + F · tan α.
 * [13] The constants: CHANNEL_BLEND_S 0.2, CHANNEL_HYST_M 0.005, CHANNEL_HYST_DEG 10.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_channel_guidance_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  const C = await import('../packages/scene-render/src/channels.ts')
  const { COLLISION_VERSION } = await import('../packages/scene-render/src/collision.ts')
  const THREE = await import('three')
  const { channelCoords, inZone, allowedRadius, radialGuidanceAngle, depthJoint, depthScale, stepEngagement, channelGate,
    suppressedIds, guideRod, previewChannel, bindChannels, channelWireframe, placeChannelWireframe,
    CHANNEL_BLEND_S, CHANNEL_HYST_M, CHANNEL_HYST_DEG, CHANNEL_GROW } = C

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (x, want, tol) => typeof x === 'number' && Math.abs(x - want) <= tol
  const vnear = (v, want, tol) => Array.isArray(v) && v.length === 3 && v.every((x, i) => near(x, want[i], tol))
  const fmt = (v) => `(${[...v].map((x) => +x.toFixed(6)).join(', ')})`
  const DEG = Math.PI / 180

  /** Rotate p about the line through `pivot` along unit `axis` by `angle` (Rodrigues). */
  const rotateAbout = (p, pivot, axis, angle) => {
    const v = [p[0] - pivot[0], p[1] - pivot[1], p[2] - pivot[2]]
    const [kx, ky, kz] = axis
    const c = Math.cos(angle), s = Math.sin(angle)
    const kv = kx * v[0] + ky * v[1] + kz * v[2]
    const cx = ky * v[2] - kz * v[1], cy = kz * v[0] - kx * v[2], cz = kx * v[1] - ky * v[0]
    return [0, 1, 2].map(i => pivot[i] + v[i] * c + [cx, cy, cz][i] * s + axis[i] * kv * (1 - c))
  }

  const ch = (over = {}) => ({
    id: 'pkg:chan', o: [0, 0, 0], u: [0, 0, 1], depth: 0.12, r: 0.02, coneDeg: 30, funnel: 0.05,
    accepts: ['op_x'], minLength: 1.0, compressMin: 0.8, kinds: null, suppress: new Set(['cap_a', 'cap_b']),
    ...over,
  })
  const D2 = ch()

  // [1] the radial clamp
  const J = [0, 0, -0.05], T = [0.03, 0, 0.05]
  const t0 = channelCoords(T, D2)
  check('[1] tip frame s 0.05, ρ 0.03', near(t0.s, 0.05, 1e-12) && near(t0.rho, 0.03, 1e-12), JSON.stringify(t0))
  const lever = Math.hypot(0.03, 0.1)
  check('[1] lever 0.104403 at 16.699° from u', near(lever, 0.104403, 1e-6) && near(Math.atan2(0.03, 0.1) / DEG, 16.699, 1e-3))
  const g1 = radialGuidanceAngle(J, T, D2, 0)
  check('[1] turn 5.655° (±0.005)', !!g1 && near(g1.angle / DEG, 5.655, 0.005), String(g1 && g1.angle / DEG))
  check('[1] turn axis −y', !!g1 && vnear(g1.axis, [0, -1, 0], 1e-9), g1 ? fmt(g1.axis) : 'null')
  const T1 = g1 ? rotateAbout(T, J, g1.axis, g1.angle) : T
  const t1 = channelCoords(T1, D2)
  check('[1] tip ends at s 0.05247 (±1e-5), ρ = R', near(t1.s, 0.05247, 1e-5) && near(t1.rho, 0.02, 1e-7), JSON.stringify(t1))
  check('[1] a tip already within R\' → null', radialGuidanceAngle(J, [0.01, 0, 0.05], D2, 0) === null)

  // [2] r_c 0.005
  const g2 = radialGuidanceAngle(J, T, D2, 0.005)
  check('[2] r_c 0.005: turn 8.439° (±0.005)', !!g2 && near(g2.angle / DEG, 8.439, 0.005), String(g2 && g2.angle / DEG))
  const T2 = g2 ? rotateAbout(T, J, g2.axis, g2.angle) : T
  check('[2] guided angle 8.260° (ρ = 0.015)', near(channelCoords(T2, D2).rho, 0.015, 1e-7) &&
    near(Math.asin(0.015 / lever) / DEG, 8.260, 1e-3))

  // [3] the caller's cap
  const capped = g1 ? Math.min(g1.angle, 4 * DEG) : 0
  check('[3] budget 4° caps the turn at 4°', near(capped / DEG, 4, 1e-12))
  const T3 = g1 ? rotateAbout(T, J, g1.axis, capped) : T
  const rho3 = channelCoords(T3, D2).rho
  check('[3] the tip keeps ρ 0.022951 > R', rho3 > D2.r && near(rho3, 0.022951, 1e-5), String(rho3))

  // [4] depth
  const k1 = depthScale(0.15, 0, D2, 0)
  check('[4] s_tip 0.15, compress_min 0.8 → k 0.8, tip at 0.12', near(k1, 0.8, 1e-12) && near(0.15 * k1, 0.12, 1e-12), String(k1))
  const k2 = depthScale(0.16, 0, D2, 0)
  check('[4] s_tip 0.16 → k 0.8, tip at 0.128 (8 mm past)', near(k2, 0.8, 1e-12) && near(0.16 * k2, 0.128, 1e-12) &&
    near(0.16 * k2 - D2.depth, 0.008, 1e-12), String(k2))
  check('[4] compress_min 1.0 → k 1', depthScale(0.16, 0, ch({ compressMin: 1.0 }), 0) === 1)
  check('[4] s_tip 0.10 ≤ D → k 1', depthScale(0.10, 0, D2, 0) === 1)
  const k3 = depthScale(0.15, -0.05, D2, 0)
  check('[4] s_e −0.05, s_tip 0.15 → k 0.85, tip at 0.12', near(k3, 0.85, 1e-12) && near(-0.05 + k3 * 0.2, 0.12, 1e-12), String(k3))
  const k4 = depthScale(0.20, -0.05, D2, 0)
  check('[4] s_e −0.05, s_tip 0.20 → k 0.8, tip at 0.15', near(k4, 0.8, 1e-12) && near(-0.05 + k4 * 0.25, 0.15, 1e-12), String(k4))
  check('[4] depthJoint: first inside, else the nearest before, tie → later, none → −1',
    depthJoint([-0.05, 0.01, 0.07]) === 1 && depthJoint([0, 0.05]) === 0 && depthJoint([-0.08, -0.03]) === 1
    && depthJoint([-0.03, -0.08]) === 0 && depthJoint([-0.02, -0.02]) === 1 && depthJoint([]) === -1)

  // [5] funnel and zones
  check('[5] allowedRadius(−0.02) 0.031547', near(allowedRadius(-0.02, D2, 0), 0.031547, 1e-6), String(allowedRadius(-0.02, D2, 0)))
  check('[5] allowedRadius in C = R − r_c', near(allowedRadius(0.05, D2, 0.005), 0.015, 1e-12))
  check('[5] allowedRadius never below 0', allowedRadius(0.05, D2, 0.03) === 0)
  check('[5] zone (0.05, 0.01) cylinder', inZone(0.05, 0.01, D2) === 'cylinder')
  check('[5] zone (0.13, 0) null', inZone(0.13, 0, D2) === null)
  check('[5] zone (−0.02, 0.03) funnel', inZone(-0.02, 0.03, D2) === 'funnel')
  check('[5] zone (−0.06, 0) null', inZone(-0.06, 0, D2) === null)

  // [6] hysteresis
  const engaged = { engaged: true, w: 1 }
  const dt = 1 / 60
  const tipAt = (rho) => channelCoords([rho, 0, 0.05], D2)
  const a = tipAt(0.023)
  check('[6] ρ 0.023: plain zone null, grown cylinder', inZone(a.s, a.rho, D2) === null &&
    inZone(a.s, a.rho, D2, CHANNEL_GROW) === 'cylinder')
  const stay = stepEngagement(engaged, { gate: true, tipInZone: inZone(a.s, a.rho, D2) !== null,
    tipInGrownZone: inZone(a.s, a.rho, D2, CHANNEL_GROW) !== null, leverAngleDeg: 40 }, D2, dt)
  check('[6] leaving C to ρ 0.023 stays engaged', stay.engaged === true && stay.w === 1, JSON.stringify(stay))
  const b = tipAt(0.026)
  const gone = stepEngagement(engaged, { gate: true, tipInZone: false,
    tipInGrownZone: inZone(b.s, b.rho, D2, CHANNEL_GROW) !== null, leverAngleDeg: 0 }, D2, dt)
  check('[6] ρ 0.026 releases', gone.engaged === false && gone.w < 1, JSON.stringify(gone))
  check('[6] grown funnel at s −0.02 holds ρ 0.035, the plain one not',
    inZone(-0.02, 0.035, D2) === null && inZone(-0.02, 0.035, D2, CHANNEL_GROW) === 'funnel' &&
    inZone(-0.02, 0.0417, D2, CHANNEL_GROW) === 'funnel' && inZone(-0.02, 0.0419, D2, CHANNEL_GROW) === null)
  check('[6] s −0.052: grown funnel only', inZone(-0.052, 0, D2) === null && inZone(-0.052, 0, D2, CHANNEL_GROW) === 'funnel')
  check('[6] past the bottom: only the release zone holds it', inZone(0.13, 0, D2) === null &&
    inZone(0.13, 0, D2, { h: CHANNEL_HYST_M }) === null && inZone(0.13, 0.024, D2, CHANNEL_GROW) === 'cylinder' &&
    inZone(0.13, 0.026, D2, CHANNEL_GROW) === null)
  const free = { engaged: false, w: 0 }
  check('[6] lever 35° > α does not engage', stepEngagement(free, { gate: true, tipInZone: true, tipInGrownZone: true,
    leverAngleDeg: 35 }, D2, dt).engaged === false)
  check('[6] lever 20° engages', stepEngagement(free, { gate: true, tipInZone: true, tipInGrownZone: true,
    leverAngleDeg: 20 }, D2, dt).engaged === true)
  check('[6] a failed gate never engages', stepEngagement(free, { gate: false, tipInZone: true, tipInGrownZone: true,
    leverAngleDeg: 0 }, D2, dt).engaged === false)

  // [7] blend
  const into = { gate: true, tipInZone: true, tipInGrownZone: true, leverAngleDeg: 0 }
  let e = { engaged: false, w: 0 }
  const ws = []
  for (let i = 0; i < 10; i++) { e = stepEngagement(e, into, D2, 0.02); ws.push(e.w) }
  check('[7] w 0.5 after 0.1 s', near(ws[4], 0.5, 1e-9), String(ws[4]))
  check('[7] w 1 after 0.2 s', near(ws[9], 1, 1e-9) && e.engaged, String(ws[9]))
  e = stepEngagement(e, into, D2, 0.02)
  check('[7] w stays at 1', e.w === 1)
  let prevW = 1, maxStep = 0, minW = 1
  for (let i = 0; i < 10; i++) {
    e = stepEngagement(e, { ...into, gate: false }, D2, 0.02)
    maxStep = Math.max(maxStep, Math.abs(e.w - prevW)); minW = Math.min(minW, e.w); prevW = e.w
  }
  check('[7] a release from 1 reaches 0 after 0.2 s', near(e.w, 0, 1e-9) && !e.engaged, String(e.w))
  check('[7] never jumps (|Δw| ≤ 0.1 per 0.02 s), never below 0', maxStep <= 0.1 + 1e-12 && minW >= 0, `max step ${maxStep}`)

  // [8] suppression
  const inC = suppressedIds([0, 0, 0.05], D2)
  check('[8] a tip in C gives the suppress set', inC.size === 2 && inC.has('cap_a') && inC.has('cap_b'))
  check('[8] at s −0.01 the empty set', suppressedIds([0, 0, -0.01], D2).size === 0)

  // [9] gate
  const partner = { name: 'p', capsules: [], channels: [D2], interaction: { id: 'i1', kind: 'k2' } }
  const reader = { interaction: { id: 'i1' } }
  const group = { op: 'op_x', length: 1.0 }
  check('[9] wrong op → false', channelGate({ ...group, op: 'op_y' }, D2, reader, partner) === false)
  check('[9] no op → false', channelGate({ length: 1.0 }, D2, reader, partner) === false)
  check('[9] length 0.9 < min 1.0 → false', channelGate({ ...group, length: 0.9 }, D2, reader, partner) === false)
  check('[9] another interaction id → false', channelGate(group, D2, { interaction: { id: 'i2' } }, partner) === false)
  check('[9] reader without an interaction → false', channelGate(group, D2, { interaction: null }, partner) === false)
  check('[9] partner without an interaction → false', channelGate(group, D2, reader, { ...partner, interaction: null }) === false)
  check('[9] kinds [k1] with kind k2 → false', channelGate(group, ch({ kinds: ['k1'] }), reader, partner) === false)
  check('[9] all matching → true', channelGate(group, D2, reader, partner) === true &&
    channelGate(group, ch({ kinds: ['k2'] }), reader, partner) === true)

  // [10] guideRod
  const rod = { length: 0.15, radius: 0, links: 1, insertion: 0.15, tiltDeg: 0, budgetDeg: 30 }
  const r10 = guideRod(D2, rod)
  const tip10 = channelCoords(r10.joints[r10.joints.length - 1], D2)
  check('[10] root at s 0', near(channelCoords(r10.joints[0], D2).s, 0, 1e-12) && r10.joints.length === 2)
  check('[10] k 0.8, tip at 0.12, pastBottomM 0', near(r10.k, 0.8, 1e-12) && near(tip10.s, 0.12, 1e-12) &&
    near(r10.pastBottomM, 0, 1e-12), JSON.stringify({ k: r10.k, s: tip10.s, past: r10.pastBottomM }))
  check('[10] no turn, suppressed [cap_a, cap_b]', r10.turnsDeg.length === 1 && r10.turnsDeg[0] === 0 &&
    JSON.stringify(r10.suppressed) === '["cap_a","cap_b"]', JSON.stringify(r10))
  const r10b = guideRod(D2, { ...rod, insertion: 0.16 })
  check('[10] insertion 0.16: k 0.8, tip 0.13, pastBottomM 0.01', near(r10b.k, 0.8, 1e-12) &&
    near(channelCoords(r10b.joints[1], D2).s, 0.13, 1e-12) && near(r10b.pastBottomM, 0.01, 1e-12),
  JSON.stringify({ k: r10b.k, past: r10b.pastBottomM }))
  const r10f = guideRod(D2, { ...rod, insertion: 0.13 })
  check('[10] insertion 0.13 (root s −0.02 = s_e): k 0.933333, tip 0.12, pastBottomM 0', near(r10f.k, 0.14 / 0.15, 1e-12) &&
    near(channelCoords(r10f.joints[1], D2).s, 0.12, 1e-12) && near(r10f.pastBottomM, 0, 1e-12),
  JSON.stringify({ k: r10f.k, past: r10f.pastBottomM }))
  const tilted = { length: lever, radius: 0, links: 1, insertion: 0.08, tiltDeg: 30, budgetDeg: 30 }
  const r10c = guideRod(D2, tilted)
  check('[10] tilt 30° about the opening: turn 12.035°, tip s 0.078179, k 1', near(r10c.turnsDeg[0], 12.035, 0.01) && r10c.k === 1 &&
    near(channelCoords(r10c.joints[1], D2).s, 0.078179, 1e-5) && near(channelCoords(r10c.joints[1], D2).rho, 0.02, 1e-6),
  JSON.stringify(r10c.turnsDeg))
  const r10g = guideRod(D2, { ...tilted, tiltDeg: Math.atan2(0.03, 0.1) / DEG, insertion: lever - 0.05 })
  const [rg0, rg1] = r10g.joints
  check('[10] tilt 16.699°: no turn, the rod crosses the opening at its centre', r10g.turnsDeg[0] === 0 &&
    near(rg0[0] + (rg1[0] - rg0[0]) * (-rg0[2] / (rg1[2] - rg0[2])), 0, 1e-12), JSON.stringify(r10g.joints))
  const r10d = guideRod(D2, { ...tilted, budgetDeg: 4 })
  check('[10] budget 4° → 4°, ρ > R', near(r10d.turnsDeg[0], 4, 1e-9) && channelCoords(r10d.joints[1], D2).rho > D2.r,
    JSON.stringify(r10d.turnsDeg))
  const r10e = guideRod(D2, { ...tilted, links: 3, length: 0.18, insertion: 0.13, budgetDeg: 30 })
  check('[10] 3 links: 4 joints, 3 turns', r10e.joints.length === 4 && r10e.turnsDeg.length === 3)

  // [11] previewChannel
  const record = {
    id: 'pkg:chan', kind: 'channel', a: 'Hips', b: 'Hips', a_pos: [0, 1, 0], b_pos: [0, 1, 0.1], r: 0.02,
    cone_deg: 30, funnel: 0.05, accepts: ['op_x'], min_length: 1, compress_min: 0.8, suppress: ['cap_a'],
    frame: { side: [1, 0, 0], up: [0, 0.6, 0.8], front: [0, -0.8, 0.6] }, placement: 'declared', applied: null,
  }
  const neutral = { offset_mm: [0, 0, 0], radius_scale: 1, depth_scale: 1, cone_deg: 30 }
  const p1 = previewChannel(record, neutral, { ...neutral, offset_mm: [0, 10, 0] })
  check('[11] offset +10 up: a_pos (0, 1.006, 0.008)', vnear(p1.a_pos, [0, 1.006, 0.008], 1e-12), fmt(p1.a_pos))
  check('[11] b_pos shifted the same (0, 1.006, 0.108)', vnear(p1.b_pos, [0, 1.006, 0.108], 1e-12), fmt(p1.b_pos))
  const p2 = previewChannel(record, { ...neutral, radius_scale: 1.25 }, { ...neutral, radius_scale: 1.5 })
  check('[11] radius 1.25 → 1.5: r 0.024', near(p2.r, 0.024, 1e-12), String(p2.r))
  const p3 = previewChannel(record, neutral, { ...neutral, depth_scale: 2 })
  check('[11] depth ×2: b_pos (0, 1, 0.2), a_pos kept', vnear(p3.b_pos, [0, 1, 0.2], 1e-12) && vnear(p3.a_pos, [0, 1, 0], 0), fmt(p3.b_pos))
  const draft4 = { ...neutral, cone_deg: 45 }
  const p4 = previewChannel(record, neutral, draft4)
  check('[11] cone replaced, applied = the draft', p4.cone_deg === 45 && JSON.stringify(p4.applied) === JSON.stringify(draft4))
  const p5 = previewChannel(record, { ...neutral, offset_mm: [0, 10, 0] }, { ...neutral, offset_mm: [0, 10, 0] })
  check('[11] the applied offset again → no shift', vnear(p5.a_pos, [0, 1, 0], 1e-15) && vnear(p5.b_pos, [0, 1, 0.1], 1e-15))
  const p6 = previewChannel(record, null, { ...neutral, offset_mm: [0, 10, 0] })
  check('[11] applied null counts as neutral', vnear(p6.a_pos, [0, 1.006, 0.008], 1e-12))
  check('[11] the record is not mutated', vnear(record.a_pos, [0, 1, 0], 0) && record.r === 0.02)

  // [12] bindChannels
  const bone = new THREE.Bone(); bone.name = 'mixamorig:Hips'
  bone.position.set(0, 1, 0)
  const figure = new THREE.Group()
  figure.add(bone)
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 1, 0], 3))
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([0, 0, 0, 0], 4))
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0], 4))
  const body = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial())
  figure.add(body)
  figure.updateMatrixWorld(true)
  body.bind(new THREE.Skeleton([bone]))
  const chRecord = { ...record, a: 'mixamorig:Hips', b: 'mixamorig:Hips', a_pos: [0, 1, 0.1], b_pos: [0, 1, 0.22],
    r: 0.02, funnel: 0.05, suppress: ['cap_a'] }
  const payload = { version: COLLISION_VERSION, capsules: [], channels: [chRecord] }
  figure.position.set(1, 0, 0)
  figure.updateMatrixWorld(true)
  const bound = bindChannels(THREE, figure, payload)
  const c0 = bound?.channels[0]
  check('[12] o = a_pos + (1, 0, 0)', !!c0 && vnear(c0.o, [1, 1, 0.1], 1e-6), c0 ? fmt(c0.o) : 'null')
  check('[12] u +z, depth 0.12, r 0.02', !!c0 && vnear(c0.u, [0, 0, 1], 1e-6) && near(c0.depth, 0.12, 1e-6) &&
    near(c0.r, 0.02, 1e-9), c0 ? JSON.stringify({ u: c0.u, depth: c0.depth, r: c0.r }) : 'null')
  check('[12] the record\'s fields carried', !!c0 && c0.id === 'pkg:chan' && c0.coneDeg === 30 && c0.minLength === 1 &&
    c0.compressMin === 0.8 && c0.kinds === null && c0.suppress.has('cap_a') && c0.accepts[0] === 'op_x')
  figure.position.set(2, 0, 0)
  figure.updateMatrixWorld(true)
  bound?.update()
  const c1 = bound?.channels[0]
  check('[12] update(): o (2, 1, 0.1), the earlier object kept', !!c1 && vnear(c1.o, [2, 1, 0.1], 1e-6) &&
    !!c0 && vnear(c0.o, [1, 1, 0.1], 1e-6), c1 ? fmt(c1.o) : 'null')
  figure.position.set(0, 0, 0)
  figure.scale.setScalar(0.5)
  figure.updateMatrixWorld(true)
  bound?.update()
  const c2 = bound?.channels[0]
  check('[12] scaled ×0.5: r 0.01, funnel 0.025, depth 0.06', !!c2 && near(c2.r, 0.01, 1e-6) && near(c2.funnel, 0.025, 1e-6) &&
    near(c2.depth, 0.06, 1e-6), c2 ? JSON.stringify({ r: c2.r, funnel: c2.funnel, depth: c2.depth }) : 'null')
  check('[12] another version → null', bindChannels(THREE, figure, { ...payload, version: COLLISION_VERSION - 1 }) === null)
  check('[12] a missing joint → null', bindChannels(THREE, figure,
    { ...payload, channels: [{ ...chRecord, a: 'mixamorig:Head', b: 'mixamorig:Head' }] }) === null)
  check('[12] no channels → null', bindChannels(THREE, figure, { version: COLLISION_VERSION, capsules: [] }) === null &&
    bindChannels(THREE, figure, null) === null)
  const wire = channelWireframe(THREE, D2, 0xff3b30)
  placeChannelWireframe(THREE, wire, D2)
  const pos = wire.geometry.getAttribute('position')
  const v = new THREE.Vector3()
  let wireOk = pos.count > 0, sMin = Infinity, sMax = -Infinity
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(wire.matrixWorld)
    const f = channelCoords([v.x, v.y, v.z], D2)
    sMin = Math.min(sMin, f.s); sMax = Math.max(sMax, f.s)
    if (f.s < -D2.funnel - 1e-6 || f.s > D2.depth + 1e-6 || f.rho > D2.r + D2.funnel * Math.tan(30 * DEG) + 1e-6) wireOk = false
  }
  check('[12] the wireframe spans −F..D inside the funnel radius', wireOk && near(sMin, -0.05, 1e-6) && near(sMax, 0.12, 1e-6),
    `s ${sMin}..${sMax}`)
  wire.geometry.dispose(); wire.material.dispose()

  // [13] constants
  check('[13] CHANNEL_BLEND_S 0.2, CHANNEL_HYST_M 0.005, CHANNEL_HYST_DEG 10',
    CHANNEL_BLEND_S === 0.2 && CHANNEL_HYST_M === 0.005 && CHANNEL_HYST_DEG === 10 &&
    CHANNEL_GROW.h === CHANNEL_HYST_M && CHANNEL_GROW.deg === CHANNEL_HYST_DEG)

  if (failures.length) {
    console.error(`\n${failures.length} check(s) failed`)
    process.exit(1)
  }
  console.log('\nall channel guidance checks passed')
}

main().catch((err) => { console.error(err); process.exit(1) })
