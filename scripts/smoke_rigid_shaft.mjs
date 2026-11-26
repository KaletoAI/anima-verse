#!/usr/bin/env node
/**
 * Usage: node scripts/smoke_rigid_shaft.mjs
 *
 * RIGID SHAFT (packages/scene-render/src/secondaryMotion.ts, module docstring; `MotionGroup.rigid`): with r = 1 a
 * chain moves only at its root link. Fixture, metres, three's Y-up: Hips at the origin; the chain A → B → C, A's head
 * at (0, 1, 0), B 1 m along +X of A, C 1 m along +X of B; one vertex per link, skinned 1.0 to it, at x = .5 / 1.5 /
 * 2.5 (y = 1). So every link has mass 1, its centroid half a metre past its head, and C's tip (its most protruding
 * own vertex) at (2.5, 1, 0). freq 2 Hz, zeta .3, max_deg 25, sag_max_deg 30, squash [.8, 1.2].
 *
 * [1] STATIC DROOP, one update (the first one puts every particle on its static target — no swing yet).
 *     gravity .5 at gravity_scale 2 against the baked 1 g: F = (2 − 1) · 9.81 · .5 = 4.905 m/s² down per link.
 *     ω² = (2π · 2)² = 157.9137; e = F / ω² = 0.0310613 m. The chain centre is 1.5 m out from A's head, so the
 *     whole-chain droop is total = atan(e / 1.5) = atan(0.0207075) = 1.18628°.
 *     Its split over the joints (torque × span, small-angle, unsagged chain): A: Σ lever × F = (.5 + 1.5 + 2.5) F,
 *     span 1 → 4.5; B: (.5 + 1.5) F · 1 → 2; C: .5 F, span 2 × .5 = 1 → .5. Relative weights 4.5 : 2 : .5.
 *       r = 0:  A = total · 4.5/7 = 0.762611°, B = total · 2/7 = 0.338938°, C = total · .5/7 = 0.084735°.
 *       r = .5: inner weights × (1 − r) → 4.5 : 1 : .25 → A = 0.928396°, B = 0.206310°, C = 0.051578°.
 *       r = 1:  A = total = 1.18628°, B = C = 0 (the shaft droops as one piece).
 *     Each joint angle is the angle of the bone's local rotation against its bind local rotation (all about Z).
 *     Every link length (head to next head, C: its own X axis) stays 1 (stretch/flatten 0).
 * [2] LATERAL SHAKE, gravity 0, Hips moved along Z by .05 · sin(2π · 1.5 t) for 90 frames of 1/60 s:
 *       r = 0: the inner joints swing (max angle > .05°);
 *       r = 1: the inner joints stay at 0 (< 1e-5°) and every inner link length at 1 (|ℓ − 1| < 1e-9) while the
 *              root turns (max angle > .05°).
 * [3] THE ROOT KEEPS THE SHAFT TIP OUTSIDE a partner capsule (gravity 0, gain 0, one update): a capsule along Z
 *     through (2.5, 0.97) with r = .05 holds C's tip (2.5, 1) 0.03 deep.
 *       r = 1: the inner links may not turn (their cap × (1 − r) = 0); the root turns about A's head (0, 1) by the
 *              smallest θ that puts the shaft tip (2.5 cos θ, 1 + 2.5 sin θ) outside: (2.5 cos θ − 2.5)² +
 *              (2.5 sin θ + .03)² = .05², solved by bisection here → θ ≈ 0.4584°; B and C stay at 0.
 *       r = 0: the root's own tip (B's head, 1 m out) is far from the capsule, A does not turn; C turns itself.
 * [4] r = 0 IS THE FREE CHAIN BIT FOR BIT: [2] and [3] give identical bone matrices for r absent, r = 0 and the
 *     solver of commit e89bf0419 (before the rule).
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import assert from 'node:assert/strict'

const BASELINE = 'e89bf0419'
if (!process.env.RIGID_SHAFT_BUNDLED) {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..')
  const bin = ['node_modules/esbuild/bin/esbuild']
    .map(rel => join(root, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const dir = mkdtempSync(join(root, 'scripts/.smoke-rigid-shaft-'))
  let status = 1
  try {
    const output = join(dir, 'bundle.mjs'), old = join(dir, 'old.mjs')
    const built = spawnSync(bin, [fileURLToPath(import.meta.url), '--bundle', '--platform=node', '--format=esm',
      '--external:three', `--outfile=${output}`, '--log-level=error'], { stdio: 'inherit' })
    assert.equal(built.status, 0)
    const source = spawnSync('git', ['show', `${BASELINE}:packages/scene-render/src/secondaryMotion.ts`], { cwd: root, encoding: 'utf8' })
    assert.equal(source.status, 0, 'baseline source unavailable')
    const entry = join(root, 'packages/scene-render/src/.smoke-rigid-shaft-old.ts')
    writeFileSync(entry, source.stdout)
    try {
      const oldBuilt = spawnSync(bin, [entry, '--bundle', '--platform=node', '--format=esm', '--external:three',
        `--outfile=${old}`, '--log-level=error'], { stdio: 'inherit' })
      assert.equal(oldBuilt.status, 0)
    } finally { rmSync(entry, { force: true }) }
    const run = spawnSync('node', [output], { stdio: 'inherit', env: { ...process.env, RIGID_SHAFT_BUNDLED: '1', RIGID_SHAFT_OLD: old } })
    status = run.status ?? 1
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
  process.exit(status)
}
const THREE = await import('three')
const { createSecondaryMotion } = await import('../packages/scene-render/src/secondaryMotion.ts')
const OLD = await import(process.env.RIGID_SHAFT_OLD)

const DEG = 180 / Math.PI
const defaults = { freq_hz: 2, zeta: .3, gravity: 0, gravity_scale: 1, gain: 1,
  max_deg: 25, sag_max_deg: 30, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: .5, flatten_floor: 1, spill: 0, translate: 0,
  squash: [.8, 1.2], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90,
  straighten_deg: 0, freetext_clothing_gain: 1, op: 'appendage_chain' }
let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

function rig() {
  const root = new THREE.Group()
  const bone = (name, parent, at) => { const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? root).add(b); return b }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const a = bone('mixamorig:ShaftA', hips, [0, 1, 0])
  const b = bone('mixamorig:ShaftB', a, [1, 0, 0])
  const c = bone('mixamorig:ShaftC', b, [1, 0, 0])
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([.5, 1, 0, 1.5, 1, 0, 2.5, 1, 0], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, a, b, c]))
  return { root, hips, links: [a, b, c] }
}
const payload = (over) => ({ rev: 'fixture', groups: { tail_chain: { ...defaults, bones: ['ShaftA', 'ShaftB', 'ShaftC'], ...over } } })
const BIND = new THREE.Quaternion()
/** Signed joint angle (degrees, about Z) of a bone's local rotation against its bind local rotation (identity). */
const jointDeg = (bone) => {
  const q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3()
  bone.matrix.decompose(p, q, s)
  const angle = q.angleTo(BIND) * DEG
  return Math.sign(q.z * q.w) * angle
}
const headOf = (bone) => new THREE.Vector3().setFromMatrixPosition(bone.matrixWorld)
const lengths = (f) => {
  f.root.updateMatrixWorld(true)
  const [a, b, c] = f.links
  const cAxis = new THREE.Vector3(1, 0, 0).applyMatrix4(c.matrixWorld).sub(headOf(c)).length()
  return [headOf(a).distanceTo(headOf(b)), headOf(b).distanceTo(headOf(c)), cAxis]
}
const near = (x, y, tol) => Math.abs(x - y) <= tol

const F = 9.81 * .5, omega2 = (2 * Math.PI * 2) ** 2, e = F / omega2
const total = Math.atan(e / 1.5) * DEG

console.log('--- [1] static droop ---')
for (const [r, w] of [[0, [4.5, 2, .5]], [.5, [4.5, 1, .25]], [1, [4.5, 0, 0]]]) {
  const f = rig()
  const motion = createSecondaryMotion(THREE, f.root, payload({ gravity: .5, gravity_scale: 2, rigid: r }))
  motion.update(1 / 60)
  const sum = w[0] + w[1] + w[2]
  const want = w.map(x => -total * x / sum)
  const got = f.links.map(jointDeg)
  check(`r = ${r}: joint angles A/B/C = total × ${w.join(':')} (total ${total.toFixed(5)}°)`,
    got.every((g, i) => near(g, want[i], 1e-6)), `${got.map(x => x.toFixed(6)).join(', ')} vs ${want.map(x => x.toFixed(6)).join(', ')}`)
  const ls = lengths(f)
  check(`r = ${r}: link lengths 1`, ls.every(l => near(l, 1, 1e-9)), ls.map(l => l.toFixed(12)).join(', '))
  motion.dispose()
}

console.log('--- [2] lateral shake ---')
const shake = (solver, r, frames = 90) => {
  const f = rig()
  const motion = solver(THREE, f.root, payload(r === undefined ? {} : { rigid: r }))
  const maxDeg = [0, 0, 0]
  let maxLen = 0
  const angle = (bone) => { const q = new THREE.Quaternion(); bone.matrix.decompose(new THREE.Vector3(), q, new THREE.Vector3()); return q.angleTo(BIND) * DEG }
  const matrices = []
  for (let i = 0; i < frames; i++) {
    f.hips.position.z = .05 * Math.sin(2 * Math.PI * 1.5 * i / 60)
    f.root.updateMatrixWorld(true)
    motion.update(1 / 60)
    f.links.forEach((b, j) => { maxDeg[j] = Math.max(maxDeg[j], angle(b)) })
    const ls = lengths(f)
    maxLen = Math.max(maxLen, Math.abs(ls[1] - 1), Math.abs(ls[2] - 1))
    matrices.push(...f.links.flatMap(b => b.matrix.elements))
  }
  motion.dispose()
  return { maxDeg, maxLen, matrices }
}
{
  const free = shake(createSecondaryMotion, 0)
  check('r = 0: the inner joints swing', free.maxDeg[1] > .05 && free.maxDeg[2] > .05, free.maxDeg.map(x => x.toFixed(4)).join(', '))
  const rigid = shake(createSecondaryMotion, 1)
  check('r = 1: the root turns', rigid.maxDeg[0] > .05, rigid.maxDeg[0].toFixed(4))
  check('r = 1: inner joint angles stay 0', rigid.maxDeg[1] < 1e-5 && rigid.maxDeg[2] < 1e-5, rigid.maxDeg.map(x => x.toExponential(2)).join(', '))
  check('r = 1: inner link lengths stay 1', rigid.maxLen < 1e-9, rigid.maxLen.toExponential(2))
  console.log('--- [4] r = 0 is the free chain bit for bit (shake) ---')
  const absent = shake(createSecondaryMotion, undefined)
  const old = shake(OLD.createSecondaryMotion, undefined)
  check('r absent == r 0', absent.matrices.every((x, i) => Object.is(x, free.matrices[i])))
  check(`r 0 == solver of ${BASELINE}`, old.matrices.every((x, i) => Object.is(x, free.matrices[i])), `${old.matrices.length} numbers`)
}

console.log('--- [3] the root keeps the shaft tip outside a partner capsule ---')
const capsule = { name: 'p', channels: [], interaction: null,
  capsules: [{ id: 'c', region: 'arm', now: { a: [2.5, .97, -1], b: [2.5, .97, 1], r: .05 } }] }
const contact = (solver, r) => {
  const f = rig()
  const motion = solver(THREE, f.root, payload({ gain: 0, ...(r === undefined ? {} : { rigid: r }) }))
  motion.update(1 / 60, { partners: [capsule] })
  f.root.updateMatrixWorld(true)
  const tip = new THREE.Vector3(.5, 0, 0).applyMatrix4(f.links[2].matrixWorld)
  const out = { angles: f.links.map(jointDeg), tip, matrices: f.links.flatMap(b => [...b.matrix.elements]) }
  motion.dispose()
  return out
}
{
  // The hand root: the smallest θ > 0 with (2.5 cos θ − 2.5)² + (2.5 sin θ + .03)² = .05².
  const g = t => (2.5 * Math.cos(t) - 2.5) ** 2 + (2.5 * Math.sin(t) + .03) ** 2 - .0025
  let lo = 0, hi = .05
  for (let i = 0; i < 200; i++) { const m = (lo + hi) / 2; if (g(m) < 0) lo = m; else hi = m }
  const theta = hi * DEG
  const rigid = contact(createSecondaryMotion, 1)
  check(`r = 1: the root turns by θ = ${theta.toFixed(4)}° (±.01°)`, near(rigid.angles[0], theta, .01), rigid.angles[0].toFixed(5))
  check('r = 1: B and C stay at 0', Math.abs(rigid.angles[1]) < 1e-5 && Math.abs(rigid.angles[2]) < 1e-5, rigid.angles.slice(1).map(x => x.toExponential(2)).join(', '))
  const depth = .05 - Math.hypot(rigid.tip.x - 2.5, rigid.tip.y - .97)
  check('r = 1: the shaft tip is outside the capsule (within 1 mm)', depth < 1e-3, `depth ${(depth * 1000).toFixed(3)} mm`)
  const free = contact(createSecondaryMotion, 0)
  check('r = 0: the root does not turn, C turns itself', Math.abs(free.angles[0]) < 1e-9 && free.angles[2] > .1, free.angles.map(x => x.toFixed(4)).join(', '))
  console.log('--- [4] r = 0 is the free chain bit for bit (contact) ---')
  const absent = contact(createSecondaryMotion, undefined), old = contact(OLD.createSecondaryMotion, undefined)
  check('r absent == r 0', absent.matrices.every((x, i) => Object.is(x, free.matrices[i])))
  check(`r 0 == solver of ${BASELINE}`, old.matrices.every((x, i) => Object.is(x, free.matrices[i])))
}

if (failures) { console.log(`${failures} check(s) FAILED`); process.exit(1) }
console.log('all rigid shaft checks passed')
