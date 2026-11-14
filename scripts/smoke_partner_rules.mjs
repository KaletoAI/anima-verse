#!/usr/bin/env node
/**
 * Smoke check for the PARTNER RULES — `packages/scene-render/src/partnerContact.ts`
 * (cross-person collision, stage 1; spec
 * `docs/superpowers/specs/2026-11-13-cross-person-collision-design.md` Parts 1
 * and 3, derivations D1 / D6 / D7 of plan
 * `docs/superpowers/plans/2026-11-14-cross-person-collision.md`): body and
 * reach spheres, partner selection, the consumer filters, the broad phase, the
 * combined own + partner contact search, the release rate and the snapshot.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *   node scripts/smoke_partner_rules.mjs
 *
 * No server, no world DB, no outbound request; `three` is not loaded.
 * Every expected number is derived BY HAND (§ B5a):
 *
 * [1] D6 body sphere. Capsules A (0,0,0)→(0,1,0) r 0.1, B a = b = (0.5,1,0)
 *     r 0.05. Centre = mean of the four endpoints = (0.25, 0.75, 0).
 *     Endpoint distances: (0,0,0) √(0.0625 + 0.5625) = 0.790569,
 *     (0,1,0) √(0.0625 + 0.0625) = 0.353553, (0.5,1,0) 0.353553.
 *     r = max(0.790569 + 0.1, 0.353553 + 0.1, 0.353553 + 0.05) = 0.890569 (±1e-6).
 *     No capsules → null.
 * [2] D6 selection. Reach centred (0,1,0), r 1.0; candidate body spheres r 0.5
 *     at (x,1,0): x = 1.4 "m" (member), 0.5 "a", 1.0 "b", 1.2 "c", 1.5 "d",
 *     3.0 "e". Gap = x − 1.0 − 0.5: −0.1, −1.0, −0.5, −0.3, 0.0, 1.5.
 *     "e" is out (gap > 0), "d" touches (gap 0 counts). Members first, then the
 *     smallest gap: m, a, b, c, d — cut at PARTNER_MAX = 4 → [m, a, b, c].
 *     Without the member mark: a, b, c, m → [a, b, c, m]. max 2 → [m, a].
 * [3] Reach. The [1] body, lever 0.3 → r = 0.890569 + 0.3 = 1.190569, centre
 *     unchanged. Lever 0 and one hair sphere at c + (0, −0.6, 0), r 0.5 →
 *     r = max(0.890569, 0.6 + 0.5) = 1.1. Hair sphere at c, r 0.1 → 0.890569.
 * [4] Broad phase. Joint (0,0,0), lever 0.1. Capsules vertical (y −1..1),
 *     r 0.05: at x = 0.2 the segment distance 0.2 > 0.1 + 0.05 → culled; at
 *     x = 0.14, 0.14 ≤ 0.15 → kept. Indices → [1].
 * [5] contactAnglePair (angles in degrees here — the search is unit-free):
 *     a) own = max(0, θ − 8), partner = max(0, 6 − θ), budget 10, depth0
 *        [0, 6]: outside both on [6, 8], so the smallest outside angle is
 *        6.00 (±0.02).
 *     b) own = max(0, θ − 2), partner = max(0, 6 − θ): never outside both;
 *        own is 0 on [0, 2] and grows after, partner falls → the smallest own
 *        depth with the smallest partner depth is θ = 2.00 (±0.02): the own
 *        body wins over a deeper partner.
 *     c) D1 (spec Part 3): joint at the origin, lever 0.10 along +x, tip
 *        (0.1 cos θ, 0.1 sin θ, 0); partner capsule parallel to z through
 *        (0.10, −0.02), r 0.03, full radius (no bind rule); partner depth =
 *        how far `pushOutOfCapsules` moves the tip, own depth 0. Outside ⇔
 *        0.02 cos θ − 0.004 sin θ ≤ 0.0195: √(0.02² + 0.004²) = 0.0203961,
 *        φ = atan(0.2) = 11.3099°, θ + φ = acos(0.0195 / 0.0203961) =
 *        17.0466° → θ = 5.737° (±0.01), searched in radians with budget 10°.
 *        Budget 4° → 4° (±0.01): the tip ends 0.026977 from the axis, so its
 *        depth there is 0.03 − 0.026977 = 3.02 mm (±0.01 mm).
 *     d) null: own = 1 + θ, partner = 1, depth0 [1, 1] → no angle better than 0;
 *        already outside both at 0 (depth0 [0, 0]) → null.
 *     e) an outside window narrower than a scan step: own 0, partner =
 *        max(0, |θ − 4.5| − 0.05), budget 10 (scan step 0.8333, samples 4.1667
 *        and 5.0 both inside) → the window's near edge 4.45 (±0.01).
 * [6] D7 releasedAngle (PARTNER_RELEASE_DEG_S 240, dt 1/60 → 4° per frame):
 *     (prev 10, want 0) = max(0, 6, 0) = 6; (10, 8) = 8; (3, 0) = max(0, −1, 0)
 *     = 0; engaging is immediate: (0, 7) = 7.
 * [7] Consumer filters, one capsule per region torso, outer_trunk, chest_hair,
 *     shoulder_hair, arm:
 *     hair → outer_trunk, chest_hair, shoulder_hair, arm (torso dropped, R7);
 *     extension → outer_trunk, arm (HAIR_ONLY_REGIONS dropped too);
 *     without outer_trunk: hair → torso, chest_hair, shoulder_hair, arm;
 *     extension → torso, arm.
 * [8] nearestCapsules, sphere centre (0,0,0): capsules vertical at x = 0.5
 *     r 0.1 (0.4), x = 0.3 r 0.05 (0.25), x = 1.0 r 0.7 (0.3) → max 2 → [1, 2];
 *     max 5 → [1, 2, 0].
 * [9] snapshotPartner on a stub binding: `update()` called exactly once, the
 *     snapshot holds the capsules AFTER that update (ids, regions, ends),
 *     channels [], interaction passed through; a later update leaves it intact.
 * [10] The starting constants of the plan's Global Constraints: PARTNER_MAX 4,
 *     PARTNER_COLLIDE_MAX 8, PARTNER_PUSH_MAX_M 0.04, PARTNER_HYST_M 0.003,
 *     PARTNER_RELEASE_DEG_S 240, PARTNER_PREFILTER_SLACK_M 1.0.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_partner_rules_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild', 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm', '--external:three', `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' }, cwd: root,
    })
    process.exit(run.status ?? 1)
  }

  const P = await import('../packages/scene-render/src/partnerContact.ts')
  const { pushOutOfCapsules } = await import('../packages/scene-render/src/garmentCollision.ts')
  const { bodySphere, reachSphere, selectPartners, partnerCapsules, broadPhase, contactAnglePair, releasedAngle,
    nearestCapsules, snapshotPartner } = P

  const failures = []
  const check = (label, ok, detail = '') => {
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
    if (!ok) failures.push(label)
  }
  const near = (x, want, tol) => typeof x === 'number' && Math.abs(x - want) <= tol
  const DEG = Math.PI / 180

  // [1] D6 body sphere
  const A = { a: [0, 0, 0], b: [0, 1, 0], r: 0.1 }
  const B = { a: [0.5, 1, 0], b: [0.5, 1, 0], r: 0.05 }
  const body = bodySphere([A, B])
  check('[1] D6 body sphere centre (0.25, 0.75, 0)',
    !!body && near(body.c[0], 0.25, 1e-12) && near(body.c[1], 0.75, 1e-12) && near(body.c[2], 0, 1e-12), JSON.stringify(body?.c))
  check('[1] D6 body sphere r 0.890569', !!body && near(body.r, 0.890569, 1e-6), String(body?.r))
  check('[1] no capsules → null', bodySphere([]) === null)

  // [2] D6 selection
  const reach = { c: [0, 1, 0], r: 1.0 }
  const cands = [['m', 1.4], ['a', 0.5], ['b', 1.0], ['c', 1.2], ['d', 1.5], ['e', 3.0]]
    .map(([name, x]) => ({ name, body: { c: [x, 1, 0], r: 0.5 } }))
  const sel = selectPartners(reach, new Set(['m']), cands)
  check('[2] D6 selection [m, a, b, c]', JSON.stringify(sel) === '["m","a","b","c"]', JSON.stringify(sel))
  const selNoMember = selectPartners(reach, new Set(), cands)
  check('[2] without a member: [a, b, c, m]', JSON.stringify(selNoMember) === '["a","b","c","m"]', JSON.stringify(selNoMember))
  const selTwo = selectPartners(reach, new Set(['m']), cands, 2)
  check('[2] max 2: [m, a]', JSON.stringify(selTwo) === '["m","a"]', JSON.stringify(selTwo))
  const selAll = selectPartners(reach, new Set(['m']), cands, 10)
  check('[2] gap 0 counts, gap 1.5 does not: [m, a, b, c, d]', JSON.stringify(selAll) === '["m","a","b","c","d"]', JSON.stringify(selAll))

  // [3] Reach
  const r1 = reachSphere(body, 0.3)
  check('[3] reach lever 0.3: r 1.190569', near(r1.r, 1.190569, 1e-6), String(r1.r))
  check('[3] reach keeps the centre', near(r1.c[0], 0.25, 1e-12) && near(r1.c[1], 0.75, 1e-12) && near(r1.c[2], 0, 1e-12))
  const r2 = reachSphere(body, 0, [{ c: [body.c[0], body.c[1] - 0.6, body.c[2]], r: 0.5 }])
  check('[3] reach lever 0 + hair sphere: r 1.1', near(r2.r, 1.1, 1e-9), String(r2.r))
  const r3 = reachSphere(body, 0, [{ c: [...body.c], r: 0.1 }])
  check('[3] reach with an inner hair sphere: r 0.890569', near(r3.r, 0.890569, 1e-6), String(r3.r))

  // [4] Broad phase
  const vertical = (x, r) => ({ a: [x, -1, 0], b: [x, 1, 0], r })
  const bp = broadPhase([0, 0, 0], 0.1, [vertical(0.2, 0.05), vertical(0.14, 0.05)])
  check('[4] broad phase: x 0.2 culled, x 0.14 kept → [1]', JSON.stringify(bp) === '[1]', JSON.stringify(bp))

  // [5] contactAnglePair
  const a5a = contactAnglePair(t => [Math.max(0, t - 8), Math.max(0, 6 - t)], [0, 6], 10)
  check('[5a] outside both: 6.00°', near(a5a, 6, 0.02), String(a5a))
  const a5b = contactAnglePair(t => [Math.max(0, t - 2), Math.max(0, 6 - t)], [0, 6], 10)
  check('[5b] own body wins: 2.00°', near(a5b, 2, 0.02), String(a5b))
  const partnerD1 = [{ a: [0.10, -0.02, -1], b: [0.10, -0.02, 1], r: 0.03 }]
  const depthD1 = (t) => {
    const tip = [0.1 * Math.cos(t), 0.1 * Math.sin(t), 0]
    const p = pushOutOfCapsules(tip, partnerD1)
    return [0, Math.hypot(p[0] - tip[0], p[1] - tip[1], p[2] - tip[2])]
  }
  const d0 = depthD1(0)
  check('[5c] D1 depth at 0: 10 mm', near(d0[1], 0.01, 1e-9), String(d0[1]))
  const a5c = contactAnglePair(depthD1, d0, 10 * DEG)
  check('[5c] D1 turn 5.737°', near(a5c / DEG, 5.737, 0.01), String(a5c / DEG))
  const a5c4 = contactAnglePair(depthD1, d0, 4 * DEG)
  check('[5c] D1 budget 4° → 4°', near(a5c4 / DEG, 4, 0.01), String(a5c4 / DEG))
  check('[5c] D1 budget 4°: 3.02 mm stays inside', near(depthD1(a5c4)[1] * 1000, 3.02, 0.01), String(depthD1(a5c4)[1] * 1000))
  check('[5d] nothing better than 0 → null', contactAnglePair(t => [1 + t, 1], [1, 1], 10) === null)
  check('[5d] outside both at 0 → null', contactAnglePair(() => [0, 0], [0, 0], 10) === null)
  const a5e = contactAnglePair(t => [0, Math.max(0, Math.abs(t - 4.5) - 0.05)], [0, 4.45], 10)
  check('[5e] a window the scan stepped over: near edge 4.45', near(a5e, 4.45, 0.01), String(a5e))

  // [6] D7 releasedAngle
  check('[6] D7 (10, 0, 1/60) = 6', near(releasedAngle(10, 0, 1 / 60), 6, 1e-9), String(releasedAngle(10, 0, 1 / 60)))
  check('[6] D7 (10, 8, 1/60) = 8', near(releasedAngle(10, 8, 1 / 60), 8, 1e-9), String(releasedAngle(10, 8, 1 / 60)))
  check('[6] D7 (3, 0, 1/60) = 0', releasedAngle(3, 0, 1 / 60) === 0, String(releasedAngle(3, 0, 1 / 60)))
  check('[6] engaging is immediate: (0, 7, 1/60) = 7', releasedAngle(0, 7, 1 / 60) === 7)

  // [7] Consumer filters
  const regions = (list) => list.map(region => ({ capsule: { region } }))
  const ids = (list) => list.map(e => e.capsule.region).join(',')
  const full = regions(['torso', 'outer_trunk', 'chest_hair', 'shoulder_hair', 'arm'])
  check('[7] hair: outer_trunk, chest_hair, shoulder_hair, arm', ids(partnerCapsules('hair', full)) === 'outer_trunk,chest_hair,shoulder_hair,arm', ids(partnerCapsules('hair', full)))
  check('[7] extension: outer_trunk, arm', ids(partnerCapsules('extension', full)) === 'outer_trunk,arm', ids(partnerCapsules('extension', full)))
  const noOuter = regions(['torso', 'chest_hair', 'shoulder_hair', 'arm'])
  check('[7] hair without outer_trunk keeps torso', ids(partnerCapsules('hair', noOuter)) === 'torso,chest_hair,shoulder_hair,arm', ids(partnerCapsules('hair', noOuter)))
  check('[7] extension without outer_trunk keeps torso', ids(partnerCapsules('extension', noOuter)) === 'torso,arm', ids(partnerCapsules('extension', noOuter)))

  // [8] nearestCapsules
  const caps8 = [vertical(0.5, 0.1), vertical(0.3, 0.05), vertical(1.0, 0.7)]
  const n2 = nearestCapsules({ c: [0, 0, 0], r: 0.2 }, caps8, 2)
  check('[8] nearest 2: [1, 2]', JSON.stringify(n2) === '[1,2]', JSON.stringify(n2))
  const n5 = nearestCapsules({ c: [0, 0, 0], r: 0.2 }, caps8, 5)
  check('[8] nearest 5: [1, 2, 0]', JSON.stringify(n5) === '[1,2,0]', JSON.stringify(n5))

  // [9] snapshotPartner
  let updates = 0
  const stub = {
    capsules: [
      { capsule: { id: 'c0', region: 'outer_trunk' }, now: { a: [0, 0, 0], b: [0, 0, 0], r: 0.1 } },
      { capsule: { id: 'c1', region: 'arm' }, now: { a: [0, 0, 0], b: [0, 0, 0], r: 0.05 } },
    ],
    missing: [],
    update() {
      updates++
      for (const e of this.capsules) e.now = { a: [updates, 0, 0], b: [updates, 1, 0], r: e.now.r }
    },
  }
  const inter = { id: 'i1', kind: 'pair' }
  const snap = snapshotPartner('p', stub, inter)
  check('[9] update() called once', updates === 1, String(updates))
  check('[9] ids and regions', snap.capsules.map(c => `${c.id}:${c.region}`).join() === 'c0:outer_trunk,c1:arm')
  check('[9] capsules after the update', snap.capsules.every(c => c.now.a[0] === 1 && c.now.b[1] === 1))
  check('[9] channels [] and interaction passed through', Array.isArray(snap.channels) && snap.channels.length === 0
    && snap.interaction === inter && snap.name === 'p')
  stub.update()
  check('[9] a later update leaves the snapshot intact', snap.capsules.every(c => c.now.a[0] === 1))

  // [10] constants
  const want = { PARTNER_MAX: 4, PARTNER_COLLIDE_MAX: 8, PARTNER_PUSH_MAX_M: 0.04, PARTNER_HYST_M: 0.003,
    PARTNER_RELEASE_DEG_S: 240, PARTNER_PREFILTER_SLACK_M: 1.0 }
  for (const [k, v] of Object.entries(want)) check(`[10] ${k} = ${v}`, P[k] === v, String(P[k]))

  if (failures.length) {
    console.log(`\nFAIL — ${failures.length} check(s): ${failures.join('; ')}`)
    process.exit(1)
  }
  console.log('\nOK — partner spheres, selection, filters, broad phase, contact search and release as derived')
}

main().catch((e) => { console.error(e); process.exit(1) })
