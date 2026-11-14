#!/usr/bin/env node
/**
 * Hair and extension chains pushed out of PARTNER capsules on the CPU
 * (`SecondaryMotion.update(dt, { partners })`, packages/scene-render/src/secondaryMotion.ts, contract header
 * "PARTNER CAPSULES"; spec docs/superpowers/specs/2026-11-13-cross-person-collision-design.md Part 3).
 * Hand-derived; every number below comes from the geometry, not from a recorded run.
 *
 * Usage: node scripts/smoke_partner_contact.mjs   (no server, no world; bundles itself with esbuild)
 *
 * FIXTURE (metres, bind rotations identity): Hips (0,0,0) → TestLink joint at the origin; OwnA / OwnB under Hips
 * (an own capsule's joints, bound at y = ±0.5 far from the tip, moved at runtime). Two vertices weighted 1 to
 * TestLink at (0,0,0) and (0.10,0,0): centroid lever (0.05,0,0), tip = the own vertex reaching farthest along it =
 * (0.10,0,0) — the lever 0.10 along +x. One driven single-link group (motionShare 1), gravity 0, gain 0: the
 * link is static at its bind frame, so every turn below is the contact alone. The partner snapshot `p` holds the
 * capsule `c`, parallel to z (a = (x, y, −1), b = (x, y, 1)); the turn is measured as atan2(tip.y, tip.x).
 *
 * [1] D1 integrated (spec Part 3): c through (0.10, −0.02), r 0.03. The tip lies 0.02 from the axis (10 mm deep),
 *     the way out is +y, the turn is about +z: outside ⇔ (0.1 cosθ − 0.1)² + (0.1 sinθ + 0.02)² ≥ 0.03²
 *     ⇔ 0.02 cosθ − 0.004 sinθ ≤ 0.0195 → θ = 5.737°. max_deg 25 (budget 25°): 5.737° ±0.02, and
 *     contactTips()[0].partner = ['p:c']. max_deg 4: the budget caps the turn at 4° (±0.02); at 4° the distance is
 *     √((0.1 cos4° − 0.1)² + (0.1 sin4° + 0.02)²) = 0.026977 → 3.02 ±0.02 mm stay inside.
 * [2] NO BIND RULE: with the bind factor (bind tip 0.02 from the axis → radius capped at 0.02) the tip would lie on
 *     the surface and nothing would move; the partner capsule applies at full radius → the turn exists (> 5°).
 * [3] HYSTERESIS (PARTNER_HYST_M 0.003): c through (0.10, −0.031), r 0.03 — the tip is 0.031 from the axis.
 *     A fresh link: outside at r → not pushed (tip stays (0.10,0,0), partner []). After a frame in which c pushed
 *     (c through (0.10, −0.029): 1 mm deep → 0.02(1 − cosθ) + 0.0058 sinθ = 0.03² − 0.029² → θ = 0.573°), the
 *     same c at −0.031 tests with r 0.033: 0.02(1 − cosθ) + 0.0062 sinθ = 0.033² − 0.031² → θ = 1.146°, the tip
 *     ends 0.033 from the axis. The release floor of that frame is 0.573° − 240°/s · 1/60 s < 0 → no influence.
 * [4] RELEASE (PARTNER_RELEASE_DEG_S 240): max_deg 10, c through (0.10, −0.01), r 0.03 (20 mm deep). At 10° the
 *     distance is √((0.1 cos10° − 0.1)² + (0.1 sin10° + 0.01)²) = 0.027407 < 0.03 → no angle in the budget is
 *     outside: the shallowest one, 10° (±0.01). The capsule removed (`partners: []`, and a snapshot without it):
 *     next frame at dt 1/60 → 10° − 240/60 = 6° (exactly the previous turn − 4°), then − 4° again, then 0 and
 *     the link drops out of `contactTips` (back on the plain path).
 * [5] CONSUMERS (spec Part 1 table): the D1 capsule with region `chest_hair` pushes a hair chain (`hair: true`,
 *     5.737°) and not an extension chain (0°); with region `outer_trunk` it pushes both (5.737°). An OWN capsule
 *     OwnA→OwnB moved to the D1 place, r 0.03 (bind distance 0.5 → bind factor 1): region `outer_trunk` never
 *     pushes (hair and extension: 0°); the control, region `arm`, pushes both (5.737°).
 * [5b] The same on the hair loop's path (a hair group with `anchor_blend` { TestLink: { Hips: 1 } }, `anchor_from`
 *     Hips: today's skin is Hips, the swing share 1, so the drawn frame is the rigid one): chest_hair → 5.737°;
 *     the release of [4] → 10°, then the previous − 4°.
 * [6] INERT: no `partners` and `partners: []` give bitwise-identical bone matrices over 60 frames of a swinging
 *     link (gain 1, gravity 1, own `arm` capsule bound, Hips turning).
 * [7] OWN WINS: own `arm` capsule through (0.10, +0.035), r 0.03 (tip 0.035 from it: outside), and the D1 partner
 *     capsule. Turning toward +y enters the own capsule at 0.02(1 − cosθ) + 0.000325 = 0.007 sinθ → θ = 2.866° and
 *     leaves it only at 35.7° > the 25° budget, while the partner needs 5.737°: no angle is outside both. The own
 *     depth decides: the tip ends at ≈ 2.866° (±0.02), at least 0.03 − 1e-5 from the own axis, still inside the
 *     partner (0.0250 < 0.03).
 * [8] THE CAP DROPS THE FARTHEST: one snapshot of 20 capsules, all region `arm` (r 0.01 unless named), listed in
 *     this order: 19 capsules f0 … f18 parallel to z through (−0.10, −0.027 + 0.003·k), then the D1 capsule `c`
 *     through (0.10, −0.02), r 0.03, LAST. Broad phase at the root joint (the origin), lever 0.10 + 0.003: an fk lies
 *     hypot(0.10, y_k) ≤ 0.10358 ≤ 0.113 from it, `c` 0.10198 ≤ 0.133 → all 20 kept, more than the push's 16
 *     (COLLIDE_MAX). Ranked by distance − r (`nearestCapsules`): `c` 0.07198, the fk ≥ 0.09 → the 16 nearest are `c`
 *     and f2 … f16 (|y_k| ≤ 0.021); f0, f1, f17, f18 (|y_k| 0.024 / 0.027) drop. The fk sit at x ≤ −0.09, the tip at
 *     x ≥ 0.1·cos 25° = 0.0906: none of them touches it, so the turn is D1's 5.737° (±0.02) and the row's partner is
 *     ['p:c']. Dropping by list order instead keeps f0 … f15 and loses `c`: no turn (the case fails on 09b3143f3).
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import assert from 'node:assert/strict'

if (!process.env.PARTNER_CONTACT_BUNDLED) {
  // The bundle keeps `three` external and lives under scripts/ so that it resolves the repo's own three.
  const root = join(dirname(fileURLToPath(import.meta.url)), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => join(root, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const dir = mkdtempSync(join(root, 'scripts/.smoke-partner-contact-'))
  let status = 1
  try {
    const output = join(dir, 'bundle.mjs')
    const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm',
      '--external:three', `--outfile=${output}`, '--log-level=error'], { stdio: 'inherit' })
    assert.equal(built.status, 0)
    const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, PARTNER_CONTACT_BUNDLED: '1' } })
    status = run.status ?? 1
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
  process.exit(status)
}
const THREE = await import('three')
const { createSecondaryMotion } = await import('../packages/scene-render/src/secondaryMotion.ts')
const { COLLISION_VERSION } = await import('../packages/scene-render/src/collision.ts')

const defaults = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
  max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1 }
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const DEG = 180 / Math.PI

function rig() {
  const root = new THREE.Group()
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? root).add(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const link = bone('mixamorig:TestLink', hips, [0, 0, 0])
  const ownA = bone('mixamorig:OwnA', hips, [0.1, -0.5, -1])
  const ownB = bone('mixamorig:OwnB', hips, [0.1, -0.5, 1])
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0.1, 0, 0], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, link, ownA, ownB]))
  /** Move the own capsule's joints so its axis runs parallel to z through (x, y). */
  const placeOwn = (x, y) => { ownA.position.set(x, y, -1); ownB.position.set(x, y, 1) }
  return { root, hips, link, placeOwn }
}
const group = (over = {}) => ({ rev: 'fixture', groups: { g: { ...defaults, bones: ['TestLink'], ...over } } })
const snapshot = (x, y, r = 0.03, region = 'arm', id = 'c') => ({ name: 'p', channels: [], interaction: null,
  capsules: [{ id, region, now: { a: [x, y, -1], b: [x, y, 1], r } }] })
const tipOf = (f) => { f.link.updateWorldMatrix(true, false); return new THREE.Vector3(0.1, 0, 0).applyMatrix4(f.link.matrixWorld) }
const turnOf = (f) => { const t = tipOf(f); return Math.atan2(t.y, t.x) * DEG }
const axisDistance = (tip, x, y) => Math.hypot(tip.x - x, tip.y - y)
const ownPayload = (region) => ({ version: COLLISION_VERSION,
  capsules: [{ id: 'own', a: 'mixamorig:OwnA', b: 'mixamorig:OwnB', r: 0.03, region }] })

console.log('--- [1] D1 integrated ---')
{
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group())
  motion.update(1 / 60, { partners: [snapshot(0.1, -0.02)] })
  const turn = turnOf(f)
  check('max_deg 25: the tip turns 5.737° toward +y', Math.abs(turn - 5.737) <= 0.02, turn.toFixed(4))
  const rows = motion.contactTips()
  check('contactTips()[0].partner = [p:c]', rows.length === 1 && JSON.stringify(rows[0].partner) === '["p:c"]',
    JSON.stringify(rows.map(r => r.partner)))
  check('reach() = the lever 0.10 (float32 vertex)', Math.abs(motion.reach() - 0.1) < 1e-6, String(motion.reach()))
  const none = createSecondaryMotion(THREE, rig().root, { rev: 'none', groups: {} })
  check('reach() = 0 without links', none.reach() === 0)
  const g = rig()
  const capped = createSecondaryMotion(THREE, g.root, group({ max_deg: 4 }))
  capped.update(1 / 60, { partners: [snapshot(0.1, -0.02)] })
  const t4 = turnOf(g)
  check('max_deg 4: the turn is 4°', Math.abs(t4 - 4) <= 0.02, t4.toFixed(4))
  const inside = (0.03 - axisDistance(tipOf(g), 0.1, -0.02)) * 1000
  check('max_deg 4: 3.02 mm stay inside', Math.abs(inside - 3.02) <= 0.02, `${inside.toFixed(4)} mm`)
}

console.log('--- [2] no bind rule ---')
{
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group())
  motion.update(1 / 60, { partners: [snapshot(0.1, -0.02)] })
  const turn = turnOf(f)
  check('the turn exists at full radius (a bind factor would leave 0°)', turn > 5, turn.toFixed(4))
}

console.log('--- [3] hysteresis ---')
{
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group())
  motion.update(1 / 60, { partners: [snapshot(0.1, -0.031)] })
  const tip = tipOf(f)
  check('fresh: 0.031 from an r 0.03 axis is not pushed', tip.distanceTo(new THREE.Vector3(0.1, 0, 0)) < 1e-9, tip.toArray().join())
  check('fresh: no partner row', motion.contactTips().length === 0)
  const g = rig()
  const held = createSecondaryMotion(THREE, g.root, group())
  held.update(1 / 60, { partners: [snapshot(0.1, -0.029)] })
  const first = turnOf(g)
  check('frame 1: c pushes (0.573°)', Math.abs(first - 0.573) <= 0.02, first.toFixed(4))
  held.update(1 / 60, { partners: [snapshot(0.1, -0.031)] })
  const d = axisDistance(tipOf(g), 0.1, -0.031)
  check('frame 2: pushed to r + 0.003 = 0.033', Math.abs(d - 0.033) <= 2e-5, d.toFixed(6))
  const second = turnOf(g)
  check('frame 2: 1.146°', Math.abs(second - 1.146) <= 0.02, second.toFixed(4))
  check('frame 2: partner [p:c]', JSON.stringify(held.contactTips()[0]?.partner) === '["p:c"]')
}

console.log('--- [4] release ---')
for (const [label, gone] of [['partners: []', []], ['a snapshot without the capsule', [{ ...snapshot(0, 0), capsules: [] }]]]) {
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group({ max_deg: 10 }))
  motion.update(1 / 60, { partners: [snapshot(0.1, -0.01)] })
  const first = turnOf(f)
  check(`${label}: frame at the 10° budget`, Math.abs(first - 10) <= 0.01, first.toFixed(4))
  motion.update(1 / 60, { partners: gone })
  const second = turnOf(f)
  check(`${label}: next frame 6° (the previous − 4°)`, Math.abs(second - (first - 4)) <= 1e-6 && Math.abs(second - 6) <= 0.01, second.toFixed(6))
  motion.update(1 / 60, { partners: gone })
  const third = turnOf(f)
  check(`${label}: then 2°`, Math.abs(third - (first - 8)) <= 1e-6, third.toFixed(6))
  motion.update(1 / 60, { partners: gone })
  const fourth = turnOf(f)
  check(`${label}: then 0°, no row`, Math.abs(fourth) < 1e-9 && motion.contactTips().length === 0, fourth.toFixed(9))
}

console.log('--- [5] consumers ---')
{
  const run = (over, partners, own) => {
    const f = rig()
    const motion = createSecondaryMotion(THREE, f.root, group(over))
    if (own) { f.placeOwn(0.1, -0.02); motion.setCollision(ownPayload(own)) }
    motion.update(1 / 60, partners ? { partners } : {})
    return turnOf(f)
  }
  const hair = { hair: true }
  const near = (x, v) => Math.abs(x - v) <= 0.02
  const a = run(hair, [snapshot(0.1, -0.02, 0.03, 'chest_hair')])
  check('hair chain ← partner chest_hair', near(a, 5.737), a.toFixed(4))
  const b = run({}, [snapshot(0.1, -0.02, 0.03, 'chest_hair')])
  check('extension chain ignores partner chest_hair', Math.abs(b) < 1e-9, b.toFixed(6))
  const c = run(hair, [snapshot(0.1, -0.02, 0.03, 'outer_trunk')])
  const d = run({}, [snapshot(0.1, -0.02, 0.03, 'outer_trunk')])
  check('both ← partner outer_trunk', near(c, 5.737) && near(d, 5.737), `${c.toFixed(4)} / ${d.toFixed(4)}`)
  const e = run(hair, null, 'outer_trunk')
  const g = run({}, null, 'outer_trunk')
  check('own outer_trunk never pushes (hair / extension)', Math.abs(e) < 1e-9 && Math.abs(g) < 1e-9, `${e} / ${g}`)
  const h = run(hair, null, 'arm')
  const k = run({}, null, 'arm')
  check('control: own arm pushes both', near(h, 5.737) && near(k, 5.737), `${h.toFixed(4)} / ${k.toFixed(4)}`)
  const m = run({}, [], 'outer_trunk')
  check('own outer_trunk with partners: [] still never pushes', Math.abs(m) < 1e-9, String(m))
}

console.log('--- [5b] hair on today\'s skin ---')
{
  // anchor_blend { TestLink: { Hips: 1 } }, anchor_from Hips: today's skin = Hips, the full swing share — the
  // drawn frame is the rigid one, so the numbers of [1] and [4] hold on the hair loop's own contact path.
  const today = { hair: true, anchor_blend: { TestLink: { 'mixamorig:Hips': 1 } }, anchor_from: 'mixamorig:Hips' }
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group(today))
  motion.update(1 / 60, { partners: [snapshot(0.1, -0.02, 0.03, 'chest_hair')] })
  const turn = turnOf(f)
  check('today\'s-skin hair chain ← partner chest_hair: 5.737°', Math.abs(turn - 5.737) <= 0.02, turn.toFixed(4))
  const g = rig()
  const held = createSecondaryMotion(THREE, g.root, group({ ...today, max_deg: 10 }))
  held.update(1 / 60, { partners: [snapshot(0.1, -0.01)] })
  const first = turnOf(g)
  held.update(1 / 60, { partners: [] })
  const second = turnOf(g)
  check('today\'s-skin release: 10° then 6°', Math.abs(first - 10) <= 0.01 && Math.abs(second - (first - 4)) <= 1e-6,
    `${first.toFixed(4)} → ${second.toFixed(6)}`)
}

console.log('--- [6] inert ---')
{
  const swing = { gain: 1, gravity: 1, max_deg: 30, sag_max_deg: 30 }
  const runs = [undefined, []].map(partners => {
    const f = rig()
    f.placeOwn(0.1, -0.03)
    const motion = createSecondaryMotion(THREE, f.root, group(swing))
    motion.setCollision(ownPayload('arm'))
    const frames = []
    for (let i = 0; i < 60; i++) {
      f.hips.rotation.set(0, 0, Math.sin(i / 6) * 0.6)
      motion.update(1 / 60, partners ? { partners } : undefined)
      frames.push([...f.link.matrixWorld.elements])
    }
    return frames
  })
  const same = runs[0].every((m, i) => m.every((x, j) => Object.is(x, runs[1][i][j])))
  check('no partners ≡ partners: [] bit for bit over 60 frames', same)
  const moved = runs[0].some(m => Math.abs(m[1]) > 1e-3)
  check('the fixture swings (not a static tautology)', moved)
}

console.log('--- [7] own wins ---')
{
  const f = rig()
  f.placeOwn(0.1, 0.035)
  const motion = createSecondaryMotion(THREE, f.root, group())
  motion.setCollision(ownPayload('arm'))
  motion.update(1 / 60, { partners: [snapshot(0.1, -0.02)] })
  const tip = tipOf(f)
  const turn = turnOf(f)
  const own = axisDistance(tip, 0.1, 0.035)
  const partner = axisDistance(tip, 0.1, -0.02)
  check('the tip stays outside the own capsule', own >= 0.03 - 1e-5, own.toFixed(6))
  check('it turns as far as the own body lets it (2.866°)', Math.abs(turn - 2.866) <= 0.02, turn.toFixed(4))
  check('the rest stays inside the partner', partner < 0.03 && Math.abs(partner - 0.0250) < 1e-3, partner.toFixed(6))
}

console.log('--- [8] the cap drops the farthest ---')
{
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, group())
  const far = Array.from({ length: 19 }, (_, k) => ({ id: `f${k}`, region: 'arm',
    now: { a: [-0.10, -0.027 + 0.003 * k, -1], b: [-0.10, -0.027 + 0.003 * k, 1], r: 0.01 } }))
  const snap = { name: 'p', channels: [], interaction: null,
    capsules: [...far, { id: 'c', region: 'arm', now: { a: [0.1, -0.02, -1], b: [0.1, -0.02, 1], r: 0.03 } }] }
  motion.update(1 / 60, { partners: [snap] })
  const turn = turnOf(f)
  check('20 capsules, c listed last: c survives the 16-cap, the tip turns 5.737°', Math.abs(turn - 5.737) <= 0.02, turn.toFixed(4))
  check('… and the row\'s partner is [p:c]', JSON.stringify(motion.contactTips()[0]?.partner) === '["p:c"]',
    JSON.stringify(motion.contactTips().map(r => r.partner)))
}

console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed')
process.exit(failures ? 1 : 0)
