#!/usr/bin/env node
/**
 * Hair chains collide with the head and torso capsules (`MotionGroup.hair`, `hairChainCapsules`,
 * packages/scene-render/src/secondaryMotion.ts; plan docs/superpowers/plans/2026-11-12-hairdeck-spring-chains.md
 * Task 6). Hand-derived.
 *
 * Usage: node scripts/smoke_hair_chain_contact.mjs   (no server, no world; bundles itself with esbuild)
 *
 * [1] PURE. `hairChainCapsules` keeps every bound capsule whose region is in `HAIR_REGIONS`
 *     (torso, arm, head, shoulder_hair, chest_hair), in payload order, ancestors NOT excluded. Payload: head
 *     (a Head, region head), chest (a Spine2, torso), left_upper_arm (arm), left_shoulder_hair (a LeftShoulder,
 *     shoulder_hair), a pack capsule (a Breast_L, region chest), chest_hair (a Breast_L) → head, chest,
 *     left_upper_arm, left_shoulder_hair, chest_hair. `extensionCapsules` of a chain under Head (ancestors head,
 *     neck, spine2, spine1, spine, hips) is unchanged: head and chest are ancestor capsules, shoulder_hair and
 *     chest_hair are hair-only → left_upper_arm and the pack capsule (its start joint Breast_L is no ancestor of
 *     the chain). A capsule of the partner-only region outer_trunk (collision v6, a Spine1) added at the end →
 *     neither list takes it (both lists unchanged).
 *
 * FIXTURE (metres, every bind rotation identity, one body skin with all bones):
 *   Hips (0,0,0) → Head (0,1.6,0) = H → HairGen_c00_00 at local (0,0.1,−0.07) = J0 (0,1.7,−0.07)
 *   → HairGen_c00_01 at local (0,−0.1,0) = J1 (0,1.6,−0.07). One vertex weighted 1 to each link, 0.05 below
 *   its joint: (0,1.65,−0.07) on _00, (0,1.55,−0.07) on _01. Head capsule = a sphere on Head, r 0.05
 *   (a = b = Head, no bind positions). Link _00's tip is the next chain joint J1: |J1 − H| = 0.07 at bind,
 *   0.02 outside the sphere → bind factor min(1, 0.07/0.05) = 1. Swing budget: spans 0.1 (J0→J1) and
 *   2 × 0.05 (the last link's centroid lever) → shares 0.2²·0.1 : 0.1²·0.1 = 0.8 : 0.2, so link _00 may turn
 *   0.8 × 35° = 28°.
 *   Link _00 turned about +X through J0 by ψ = −β (relative to Head) puts its tip at
 *   H + (0, 0.1(1 − cos β), −0.07 + 0.1 sin β): distance² = 0.01(1 − cos β)² + (0.1 sin β − 0.07)², which
 *   reaches 0.05² at β ≈ 11.5° (10°: 0.0527, 12°: 0.0492) and is 0.0363 at 20°. A head pitch of −40°
 *   about +X carries J0 backwards (−z, by 4.8 cm at the end of the ramp); the hanging link stays behind and so
 *   turns towards the head (measured: the control tip reaches 34.9 mm from H, i.e. β ≈ 17°).
 *   Motion: the hair constants of app/core/hair_motion.py (zeta 0.5, max 35°, sag 10°, gain 1), gravity 0,
 *   freq 1 Hz; the head pitches to −40° over 0.25 s (2.79 rad/s, under the solver's 2π rad/s anchor cap), then
 *   holds; 60 fps, 1.5 s.
 *
 * [2] CONTACT. Control (no collision payload): the tip sinks deeper than 5 mm into the sphere (measured; the
 *     precondition of the test). `hair: true` with the payload: `contactTips()` names the head capsule for both
 *     links, and the tip depth stays ≤ 1 mm in every frame (the contact turns the link back to the surface
 *     within the 1e-6 m slack; the frame is the rendered one). Without `hair`: no contact (Head is an ancestor
 *     of the chain) — `contactTips()` is empty and the tip sinks exactly as in the control.
 * [3] INERT on a model without a chain: a payload naming HairGen_c07_00 (absent here) next to hair_c00 —
 *     `configure` does not throw, `contactTips()` lists only the c00 links, and c00 still swings (its tip
 *     leaves its bind place under the pitch). Only hair_c07: no driven bone, `update` changes nothing.
 * [4] FAILS ON THE OLD CODE (pinned c061f759): `packages/scene-render/src` of that commit, bundled with this
 *     file's [2] (the payload in that tree's own `COLLISION_VERSION`, so the binding works) — `hairChainCapsules` is not exported and the `hair: true` chain gets no contact (the head
 *     capsule is an ancestor capsule), so its tip sinks as in the control.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'

const OLD = 'c061f759'
if (!process.env.HAIR_CONTACT_BUNDLED) {
  const here = fileURLToPath(import.meta.url)
  const repo = path.resolve(path.dirname(here), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => path.join(repo, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const bundle = (entry, output, env = {}) => {
    const built = spawnSync(bin, [entry, '--bundle', '--platform=node', '--format=esm', `--outfile=${output}`,
      '--log-level=error'], { stdio: 'inherit', env: { ...process.env, NODE_PATH: path.join(repo, 'node_modules'), ...env } })
    assert.equal(built.status, 0)
  }
  bundle(here, '/tmp/smoke_hair_chain_contact.mjs')
  const run = spawnSync('node', ['/tmp/smoke_hair_chain_contact.mjs'], { stdio: 'inherit', env: { ...process.env, HAIR_CONTACT_BUNDLED: '1' } })
  if (run.status !== 0) process.exit(run.status ?? 1)
  // [4] the same file against the pinned old scene-render sources
  const old = mkdtempSync(path.join(tmpdir(), 'hair-contact-old-'))
  try {
    const tar = spawnSync('sh', ['-c', `git -C "${repo}" archive ${OLD} packages/scene-render/src | tar -x -C "${old}"`], { stdio: 'inherit' })
    assert.equal(tar.status, 0, `git archive ${OLD} failed`)
    mkdirSync(path.join(old, 'scripts'))
    copyFileSync(here, path.join(old, 'scripts', 'smoke_hair_chain_contact.mjs'))
    bundle(path.join(old, 'scripts', 'smoke_hair_chain_contact.mjs'), '/tmp/smoke_hair_chain_contact_old.mjs')
    const oldRun = spawnSync('node', ['/tmp/smoke_hair_chain_contact_old.mjs'], { stdio: 'inherit',
      env: { ...process.env, HAIR_CONTACT_BUNDLED: '1', HAIR_CONTACT_OLD: '1' } })
    process.exit(oldRun.status ?? 1)
  } finally { rmSync(old, { recursive: true, force: true }) }
}
const THREE = await import('three')
const SM = await import('../packages/scene-render/src/secondaryMotion.ts')
const { createSecondaryMotion, extensionCapsules, hairChainCapsules } = SM
// The payload version of the sources under test (the old tree of [4] understands its own version only).
const { COLLISION_VERSION, bindCollision } = await import('../packages/scene-render/src/collision.ts')

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}
const hairGroup = { freq_hz: 1, zeta: 0.5, gravity: 0, gravity_scale: 1, gain: 1,
  max_deg: 35, sag_max_deg: 10, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
  flatten: 0, stretch: 0, spread: 0.5, flatten_floor: 1, spill: 0, translate: 0,
  squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90, rigid_tail: 0, scale_axis: 'centroid',
  straighten_deg: 0, freetext_clothing_gain: 1 }
const H = new THREE.Vector3(0, 1.6, 0)
const R = 0.05
const headCapsule = { id: 'head', a: 'mixamorig:Head', b: 'mixamorig:Head', r: R, region: 'head' }
const collision = { version: COLLISION_VERSION, capsules: [headCapsule] }

function rig() {
  const root = new THREE.Group()
  const bone = (name, parent, at) => {
    const b = new THREE.Bone(); b.name = name; b.position.set(...at); (parent ?? root).add(b); return b
  }
  const hips = bone('mixamorig:Hips', null, [0, 0, 0])
  const head = bone('mixamorig:Head', hips, [0, 1.6, 0])
  const c0 = bone('HairGen_c00_00', head, [0, 0.1, -0.07])
  const c1 = bone('HairGen_c00_01', c0, [0, -0.1, 0])
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0, 1.65, -0.07, 0, 1.55, -0.07], 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([2, 0, 0, 0, 3, 0, 0, 0], 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0], 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton([hips, head, c0, c1]))
  return { root, head, c0, c1 }
}
/** Play the pitch; per frame the depth of link _00's tip (the J1 joint) inside the sphere (≤ 0 = outside). */
function play({ hair, withCollision, groups }) {
  const f = rig()
  const group = { ...hairGroup, bones: ['HairGen_c00_00', 'HairGen_c00_01'], ...(hair ? { hair: true } : {}) }
  const motion = createSecondaryMotion(THREE, f.root, { rev: 'fixture', groups: groups ?? { hair_c00: group } })
  if (withCollision) motion.setCollision(collision)
  const tips = motion.contactTips()
  const dt = 1 / 60
  let deepest = -Infinity, moved = 0
  const tip = new THREE.Vector3(), bindTip = new THREE.Vector3(0, 1.6, -0.07)
  for (let frame = 1; frame <= 90; frame++) {
    const angle = -Math.min(1, frame * dt / 0.25) * 40 * Math.PI / 180
    f.head.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), angle)
    f.root.updateMatrixWorld(true)
    motion.update(dt)
    f.c1.updateWorldMatrix(true, false)
    tip.setFromMatrixPosition(f.c1.matrixWorld)
    deepest = Math.max(deepest, R - tip.distanceTo(H))
    // where the tip would be if the link rode the head rigidly
    const rigid = bindTip.clone().sub(H).applyQuaternion(f.head.quaternion).add(H)
    moved = Math.max(moved, tip.distanceTo(rigid))
  }
  motion.dispose()
  return { deepest, moved, tips }
}

if (process.env.HAIR_CONTACT_OLD) {
  console.log(`--- [4] fails on the old code (${OLD}) ---`)
  const control = play({ hair: true, withCollision: false })
  const old = play({ hair: true, withCollision: true })
  // the payload binds in that tree (its own version): no contact comes from the ancestor rule, not from the binding
  const bound = bindCollision(THREE, rig().root, collision)?.capsules.length ?? 0
  const ok = typeof hairChainCapsules !== 'function' && bound === 1 && old.tips.length === 0 && old.deepest > 0.005
    && Math.abs(old.deepest - control.deepest) < 1e-9
  console.log(`${ok ? 'OK  ' : 'FAIL'} old code: hairChainCapsules ${typeof hairChainCapsules}, head capsule bound ${bound}, hair:true contacts `
    + `${old.tips.length}, tip depth ${(old.deepest * 1000).toFixed(2)} mm (control ${(control.deepest * 1000).toFixed(2)} mm)`)
  process.exit(ok ? 0 : 1)
}

console.log('--- [1] pure: hairChainCapsules / extensionCapsules ---')
{
  const bound = [
    { capsule: { id: 'head', a: 'mixamorig:Head', region: 'head' } },
    { capsule: { id: 'chest', a: 'mixamorig:Spine2', region: 'torso' } },
    { capsule: { id: 'left_upper_arm', a: 'mixamorig:LeftArm', region: 'arm' } },
    { capsule: { id: 'left_shoulder_hair', a: 'mixamorig:LeftShoulder', region: 'shoulder_hair' } },
    { capsule: { id: 'pack:Breast_L', a: 'Breast_L', region: 'chest' } },
    { capsule: { id: 'pack:Breast_L:chest_hair', a: 'Breast_L', region: 'chest_hair' } },
  ]
  check('hairChainCapsules is a function', typeof hairChainCapsules === 'function', typeof hairChainCapsules)
  const kept = typeof hairChainCapsules === 'function' ? hairChainCapsules(bound).map(e => e.capsule.id) : []
  check('hair keeps head, chest, left_upper_arm, left_shoulder_hair, chest_hair (payload order, ancestors kept)',
    JSON.stringify(kept) === JSON.stringify(['head', 'chest', 'left_upper_arm', 'left_shoulder_hair', 'pack:Breast_L:chest_hair']), kept.join(' '))
  const ext = extensionCapsules(bound, new Set(['head', 'neck', 'spine2', 'spine1', 'spine', 'hips'])).map(e => e.capsule.id)
  check('extensionCapsules unchanged: ancestors and hair-only dropped',
    JSON.stringify(ext) === JSON.stringify(['left_upper_arm', 'pack:Breast_L']), ext.join(' '))
  const withOuter = [...bound, { capsule: { id: 'outer_spine', a: 'mixamorig:Spine1', region: 'outer_trunk' } }]
  const hairOuter = typeof hairChainCapsules === 'function' ? hairChainCapsules(withOuter).map(e => e.capsule.id) : []
  check('hair chains never take outer_trunk (partner contact only)', JSON.stringify(hairOuter) === JSON.stringify(kept), hairOuter.join(' '))
  const extOuter = extensionCapsules(withOuter, new Set(['head', 'neck'])).map(e => e.capsule.id)
  check('extension chains never take outer_trunk (partner contact only)', !extOuter.includes('outer_spine'), extOuter.join(' '))
}

console.log('--- [2] contact with the head capsule ---')
{
  const control = play({ hair: true, withCollision: false })
  check('control: the lag drives the tip > 5 mm into the sphere', control.deepest > 0.005,
    `${(control.deepest * 1000).toFixed(2)} mm`)
  const on = play({ hair: true, withCollision: true })
  const named = on.tips.map(t => `${t.bone}:${t.capsules.join(',')}`)
  check('hair: contactTips names the head capsule on both links',
    on.tips.length === 2 && on.tips.every(t => t.capsules.length === 1 && t.capsules[0] === 'head'), named.join(' '))
  check('hair: tip depth ≤ 1 mm in every frame', on.deepest <= 0.001, `${(on.deepest * 1000).toFixed(3)} mm`)
  check('hair: the chain still swings (tip off its rigid place > 5 mm)', on.moved > 0.005, `${(on.moved * 1000).toFixed(1)} mm`)
  const plain = play({ hair: false, withCollision: true })
  check('without hair: no contact (Head is an ancestor)', plain.tips.length === 0, String(plain.tips.length))
  check('without hair: the tip sinks as in the control', Math.abs(plain.deepest - control.deepest) < 1e-9,
    `${(plain.deepest * 1000).toFixed(3)} vs ${(control.deepest * 1000).toFixed(3)} mm`)
}

console.log('--- [3] a chain the model lacks ---')
{
  const c00 = { ...hairGroup, bones: ['HairGen_c00_00', 'HairGen_c00_01'], hair: true }
  const c07 = { ...hairGroup, bones: ['HairGen_c07_00'], hair: true }
  let both
  try { both = play({ hair: true, withCollision: true, groups: { hair_c00: c00, hair_c07: c07 } }) } catch (e) { both = e }
  check('configure with HairGen_c07_00 absent does not throw', !(both instanceof Error), String(both?.message ?? ''))
  if (!(both instanceof Error)) {
    check('no particle for c07: contact tips are the c00 links only',
      both.tips.map(t => t.bone).join(' ') === 'HairGen_c00_00 HairGen_c00_01', both.tips.map(t => t.bone).join(' '))
    check('c00 still swings', both.moved > 0.005, `${(both.moved * 1000).toFixed(1)} mm`)
  }
  const f = rig()
  let only
  try {
    const motion = createSecondaryMotion(THREE, f.root, { rev: 'fixture', groups: { hair_c07: c07 } })
    motion.setCollision(collision)
    motion.configure({ rev: 'fixture2', groups: { hair_c07: c07 } })
    const before = f.c0.matrix.clone()
    f.head.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.5)
    f.root.updateMatrixWorld(true)
    motion.update(1 / 60)
    only = { tips: motion.contactTips().length, same: f.c0.matrix.equals(before) }
    motion.dispose()
  } catch (e) { only = e }
  check('only c07: no throw, no contact, the chain bones untouched',
    !(only instanceof Error) && only.tips === 0 && only.same, only instanceof Error ? only.message : JSON.stringify(only))
}

if (failures) { console.log(`FAILED: ${failures}`); process.exit(1) }
console.log('ALL OK')
